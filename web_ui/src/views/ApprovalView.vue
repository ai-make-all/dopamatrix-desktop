<script setup>
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/appStore'
import { updateVideoStatus } from '../api'
import CoverPreviewCard from '../components/matrix/CoverPreviewCard.vue'
import MasterPreviewModal from '../components/MasterPreviewModal.vue'

const store  = useAppStore()
const router = useRouter()

// ── 数据 ────────────────────────────────────────────────────────────────────
const historyList        = ref([])
const historySearchQuery = ref('')
const viewMode           = ref('grid')   // 'grid' | 'list'
const isExporting        = ref(false)
const selectedIds        = ref([])
const reviewMode         = ref('active') // 'active' | 'trash'
const expandedIds           = reactive(new Set())
const purgedIds             = reactive(new Set())
const hoverVideoId          = ref(null)
// 乐观锁定集合：已提交后端但尚未打包完成的 hash，前端强制隔离出导出漏斗
const pendingExportHashes   = reactive(new Set())

// ── 多维过滤漏斗状态 ──────────────────────────────────────────────────────────
const filterDateFrom = ref('')    // 'YYYY-MM-DD' 或空
const filterDateTo   = ref('')    // 'YYYY-MM-DD' 或空
const filterMode     = ref('ALL') // 'ALL' | 'director' | 'blind' | ...
const filterStatus   = ref('ALL') // 'ALL' | 'PENDING' | 'APPROVED' | 'REJECTED'
const VALID_VARIANT_STATUSES = new Set([
  'PENDING',
  'APPROVED',
  'REJECTED',
  'DELETED',
  'PROCESSING',
])

const isFiltered = computed(() =>
  filterDateFrom.value || filterDateTo.value ||
  filterMode.value !== 'ALL' || filterStatus.value !== 'ALL' ||
  historySearchQuery.value.trim() !== ''
)

async function clearFilters() {
  filterDateFrom.value   = ''
  filterDateTo.value     = ''
  filterMode.value       = 'ALL'
  filterStatus.value     = 'ALL'
  historySearchQuery.value = ''
  await fetchApprovalList()
}

function parseSocialMeta(record, asset = {}) {
  let details = record.prompt_details || {}
  if (typeof details === 'string') {
    try {
      details = JSON.parse(details)
    } catch {
      details = {}
    }
  }
  return {
    ...(details?.meta || {}),
    ...(asset?.meta || {}),
    social_title: asset.social_title || asset?.meta?.social_title || details?.meta?.social_title || '',
    social_caption: asset.social_caption || asset?.meta?.social_caption || details?.meta?.social_caption || '',
    social_hashtags: asset.social_hashtags || asset?.meta?.social_hashtags || details?.meta?.social_hashtags || '',
  }
}

function getAssetPath(asset = {}) {
  return asset.path || asset.file_path || asset.raw_path || ''
}

function getAssetHash(asset = {}) {
  return asset.hash || asset.file_hash || asset.asset_hash || ''
}

function getAssetVideoUrl(asset = {}) {
  return asset.video_url || asset.url || store.buildVideoUrl(getAssetPath(asset))
}

function getAssetCoverUrl(asset = {}) {
  return asset.cover_url || (asset.cover_path ? store.buildVideoUrl(asset.cover_path) : '')
}

/**
 * 后端审核状态缓存：itemKey → 标准大写枚举。
 * itemKey = `${task_id}__${asset_hash}`
 */
const statusMap      = reactive({})
const loadingMap     = reactive({})   // itemKey → Boolean（单条审批中的 loading）
/**
 * 交付链接缓存：asset_hash → tracking_link（字符串）。
 * 从 /approval/list 接口写入，保证刷新后高亮状态能正确熄灭。
 */
const trackingLinkMap = reactive({})

// ── 全局播放器 ───────────────────────────────────────────────────────────────
const isModalVisible     = ref(false)
const selectedVideoIndex = ref(0)

// ── 计算属性 ────────────────────────────────────────────────────────────────

function itemKey(item) {
  return `${item.task_id}__${item.hash}`
}

function normalizeStatus(status) {
  const normalized = String(status || 'PENDING').toUpperCase()
  return VALID_VARIANT_STATUSES.has(normalized) ? normalized : 'PENDING'
}

function getStatusLabel(status) {
  const map = {
    PENDING: 'PENDING',
    APPROVED: 'APPROVED',
    REJECTED: 'REJECTED',
  }
  const normalized = normalizeStatus(status)
  return map[normalized] || normalized
}

/**
 * 将 TaskHistory 记录展平为每个 output_asset 独立一条展示项。
 */
const flatItems = computed(() => {
  const items = []
  for (const record of historyList.value) {
    const assets = record.output_assets || []
    const recordMeta = parseSocialMeta(record)
    if (assets.length === 0) {
      items.push({
        id:              record.id,
        task_id:         record.task_id,
        prompt:          record.prompt,
        duration:        record.duration,
        created_at:      record.created_at,
        generation_mode: record.generation_mode || '',
        cover_url:       '',
        video_url:       '',
        hash:            '',
        status:          'PENDING',
        download_url:    '',
        raw_path:        '',
        meta:            recordMeta,
      })
    } else {
      assets.forEach((asset, idx) => {
        const assetPath = getAssetPath(asset)
        const assetHash = getAssetHash(asset)
        items.push({
          id:              `${record.id}_${idx}`,
          task_id:         record.task_id,
          prompt:          record.prompt,
          duration:        record.duration,
          created_at:      record.created_at,
          generation_mode: record.generation_mode || '',
          cover_url:       getAssetCoverUrl(asset),
          video_url:       getAssetVideoUrl(asset),
          hash:            assetHash,
          status:          normalizeStatus(
            statusMap[`${record.task_id}__${assetHash}`] || asset.status
          ),
          tracking_link:   trackingLinkMap[assetHash] || asset.tracking_link || '',
          exported_at:     asset.exported_at || null,
          download_url:    asset.download_url || '',
          raw_path:        assetPath,
          meta:            parseSocialMeta(record, asset),
        })
      })
    }
  }
  return items
})

/**
 * 应用四维过滤漏斗：提示词搜索 · 日期范围 · 生成模式 · 审批状态
 */
const filteredItems = computed(() => {
  let items = flatItems.value.filter(item => !purgedIds.has(item.id))

  items = reviewMode.value === 'trash'
    ? items.filter(item => getStatus(item) === 'REJECTED')
    : items.filter(item => !['REJECTED', 'DELETED', 'PROCESSING'].includes(getStatus(item)))

  // ── 1. 提示词/任务 ID 模糊搜索 ─────────────────────────────────────────────
  const q = historySearchQuery.value.trim().toLowerCase()
  if (q) {
    items = items.filter(
      i => (i.prompt  || '').toLowerCase().includes(q)
        || (i.task_id || '').toLowerCase().includes(q)
    )
  }

  // ── 2. 日期范围 ────────────────────────────────────────────────────────────
  if (filterDateFrom.value) {
    const from = new Date(filterDateFrom.value).getTime()
    items = items.filter(i => i.created_at && new Date(i.created_at).getTime() >= from)
  }
  if (filterDateTo.value) {
    // 包含结束日当天（+1天再比较）
    const to = new Date(filterDateTo.value).getTime() + 86_400_000
    items = items.filter(i => i.created_at && new Date(i.created_at).getTime() < to)
  }

  // ── 3. 生成模式 ────────────────────────────────────────────────────────────
  if (filterMode.value !== 'ALL') {
    items = items.filter(i => (i.generation_mode || '') === filterMode.value)
  }

  // ── 4. 审批状态 ────────────────────────────────────────────────────────────
  if (filterStatus.value !== 'ALL') {
    items = items.filter(i => getStatus(i) === filterStatus.value)
  }

  return items
})

const previewVideoList = computed(() =>
  filteredItems.value.map(item => ({
    ...item,
    url:       item.video_url,
    cover_url: item.cover_url,
    status:    getStatus(item),
  }))
)

const approvedCount = computed(() =>
  flatItems.value.filter(i => getStatus(i) === 'APPROVED').length
)

const exportableItems = computed(() => {
  const selectedIdSet = new Set(selectedIds.value)
  if (selectedIds.value.length > 0) {
    return filteredItems.value.filter(item =>
      selectedIdSet.has(item.id)
      && item.hash
      && getStatus(item) === 'APPROVED'
    )
  }

  return filteredItems.value.filter(item =>
    item.hash
    && getStatus(item) === 'APPROVED'
    && !item.tracking_link
    && !pendingExportHashes.has(item.hash)
  )
})

// ── 状态辅助 ─────────────────────────────────────────────────────────────────
function getStatus(item)  { return normalizeStatus(item.status) }
function getLoading(item) { return loadingMap[itemKey(item)] || false }

// ── 数据加载 ─────────────────────────────────────────────────────────────────
async function fetchHistory() {
  try {
    const resp = await axios.get(`${store.API_BASE}/api/v1/history`)
    historyList.value = resp.data || []
    await fetchApprovalList()
  } catch (err) {
    store.showToast('⚠️ 获取质检记录失败: ' + err.message)
  }
}

/**
 * 按筛选条件拉取审核状态，并按 task_id + asset_hash 合并。
 */
async function fetchApprovalList() {
  try {
    reviewMode.value = filterStatus.value === 'REJECTED' ? 'trash' : 'active'
    const resp = await axios.get(`${store.API_BASE}/api/v1/approval/list`, {
      params: { status: filterStatus.value },
    })
    for (const approval of resp.data || []) {
      statusMap[`${approval.task_id}__${approval.asset_hash}`] =
        normalizeStatus(approval.status)
      // 持久化交付链接，使 exportableItems 过滤逻辑能正确判断"已交付"状态
      if (approval.tracking_link) {
        trackingLinkMap[approval.asset_hash] = approval.tracking_link
      }
    }
  } catch (err) {
    console.warn('[ApprovalView] fetchApprovalList 失败（已忽略）:', err.message)
  }
}

function onDeliveryReady() {
  fetchHistory()
  pendingExportHashes.clear()
}

onMounted(() => {
  fetchHistory()
  window.addEventListener('matrix-delivery-ready', onDeliveryReady)
})

onUnmounted(() => {
  window.removeEventListener('matrix-delivery-ready', onDeliveryReady)
})

// ── 审批操作 ─────────────────────────────────────────────────────────────────
async function handleApprove(item) {
  if (!item.hash || !item.task_id) return
  // 若已通过则撤销（切回 PENDING）
  const newStatus = getStatus(item) === 'APPROVED' ? 'PENDING' : 'APPROVED'
  await setVariantStatus(item, newStatus)
}

async function handleReject(item) {
  if (!item.hash || !item.task_id) return
  // 若已毙掉则撤销（切回 PENDING）
  const newStatus = getStatus(item) === 'REJECTED' ? 'PENDING' : 'REJECTED'
  await setVariantStatus(item, newStatus)
}

async function setVariantStatus(item, newStatus, { silent = false } = {}) {
  const key = itemKey(item)
  loadingMap[key] = true
  try {
    await updateVideoStatus(item.hash, newStatus)
    for (const candidate of flatItems.value) {
      if (candidate.hash === item.hash) {
        statusMap[itemKey(candidate)] = newStatus
      }
    }
    if (
      (reviewMode.value === 'active' && newStatus === 'REJECTED') ||
      (reviewMode.value === 'trash' && newStatus !== 'REJECTED')
    ) {
      selectedIds.value = selectedIds.value.filter(id => id !== item.id)
    }

    if (!silent) {
      const label = newStatus === 'APPROVED' ? '✅ 已通过'
                  : newStatus === 'REJECTED' ? '❌ 已毙掉'
                  : '↩ 已撤销'
      store.showToast(`${label}：#${(item.task_id || '').slice(0, 8)}`)
    }
    return true
  } catch (err) {
    const msg = err.response?.data?.detail || err.message
    if (!silent) store.showToast(`⚠️ 状态更新失败: ${msg}`)
    return false
  } finally {
    loadingMap[key] = false
  }
}

async function setReviewMode(mode) {
  reviewMode.value = mode
  filterStatus.value = mode === 'trash' ? 'REJECTED' : 'ALL'
  selectedIds.value = []
  hoverVideoId.value = null
  await fetchApprovalList()
}

async function updateSelectedStatus(newStatus) {
  const selected = flatItems.value.filter(item => selectedIds.value.includes(item.id))
  if (!selected.length) return

  try {
    const hashes = [...new Set(selected.map(item => item.hash).filter(Boolean))]
    await updateVideoStatus(hashes, newStatus)
    for (const candidate of flatItems.value) {
      if (hashes.includes(candidate.hash)) {
        statusMap[itemKey(candidate)] = newStatus
      }
    }
    selectedIds.value = []
    store.showToast(`✅ 已批量更新 ${selected.length} 个变体`)
  } catch (err) {
    const msg = err.response?.data?.detail?.message
      || err.response?.data?.detail
      || err.message
    store.showToast(`⚠️ 批量状态更新失败: ${msg}`)
  }
}

function handleBatchApprove() {
  return updateSelectedStatus('APPROVED')
}

function handleBatchReject() {
  return updateSelectedStatus('REJECTED')
}

function restoreVariant(item) {
  return setVariantStatus(item, 'APPROVED')
}

async function purgeVariant(item) {
  if (!item.hash) return
  try {
    await updateVideoStatus(item.hash, 'DELETED')
    for (const candidate of flatItems.value) {
      if (candidate.hash === item.hash) purgedIds.add(candidate.id)
    }
    selectedIds.value = selectedIds.value.filter(id => id !== item.id)
    store.showToast('已彻底销毁视频文件')
  } catch (err) {
    const msg = err.response?.data?.detail?.message
      || err.response?.data?.detail
      || err.message
    store.showToast(`⚠️ 彻底销毁失败: ${msg}`)
  }
}

async function purgeSelectedVariants() {
  const selected = flatItems.value.filter(item => selectedIds.value.includes(item.id))
  if (!selected.length) return
  try {
    const hashes = [...new Set(selected.map(item => item.hash).filter(Boolean))]
    if (!hashes.length) return
    await updateVideoStatus(hashes, 'DELETED')
    for (const candidate of flatItems.value) {
      if (hashes.includes(candidate.hash)) purgedIds.add(candidate.id)
    }
    selectedIds.value = []
    store.showToast(`已彻底销毁 ${selected.length} 个变体`)
  } catch (err) {
    const msg = err.response?.data?.detail?.message
      || err.response?.data?.detail
      || err.message
    store.showToast(`⚠️ 批量销毁失败: ${msg}`)
  }
}

// ── 导出交付包 ───────────────────────────────────────────────────────────────
async function handleExport() {
  const targets = exportableItems.value
  if (targets.length === 0) {
    store.showToast('⚠️ 当前选择或列表中没有已通过的变体可供导出。')
    return
  }

  isExporting.value = true
  const hashesToExport = [...new Set(targets.map(item => item.hash))]

  try {
    const exportUrl = `${store.API_BASE}/api/v1/matrix/export`
    const { data } = await axios.post(exportUrl, { hashes: hashesToExport })

    // 乐观锁定：提交成功后立即将本批 hash 隔离出导出漏斗，阻断重复提交
    hashesToExport.forEach(h => pendingExportHashes.add(h))

    store.startGlobalExportPolling(data.filename, hashesToExport.length)
    store.showToast('🚚 异步提货单已下发，请留意左上角侧边栏通知！')
    selectedIds.value = []
  } catch (err) {
    store.showToast('⚠️ 提交打包任务失败')
    console.error('[Export Error]:', err)
  } finally {
    isExporting.value = false
  }
}

function openPreview(index) {
  if (index < 0 || index >= filteredItems.value.length) return
  selectedVideoIndex.value = index
  isModalVisible.value = true
}

function closePreview() {
  isModalVisible.value = false
}

async function handleApprovalPreviewAction({ action, hash, index }) {
  if (action === 'tune') return
  const item = filteredItems.value[index]
  if (!item || item.hash !== hash) return
  await setVariantStatus(item, action === 'approve' ? 'APPROVED' : 'REJECTED')
}

function handleApprovalOpenDetail(hash) {
  closePreview()
  router.push('/video/' + hash)
}

// ── 工具函数 ─────────────────────────────────────────────────────────────────
function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour:  '2-digit', minute: '2-digit',
  })
}
</script>

<template>
  <div class="approval-wrap">

    <!-- ══ 顶部工具栏 ═════════════════════════════════════════════════════ -->
    <div class="approval-header">
      <div class="approval-title-block">
        <h2 class="approval-title">矩阵质检舱</h2>
        <span class="approval-subtitle">
          Approval Studio · {{ filteredItems.length }} 条记录 ·
          <span class="approved-badge">{{ approvedCount }} 已通过</span>
        </span>
      </div>

      <!-- 视图切换 -->
      <div class="view-switcher">
        <button
          :class="['switch-btn', viewMode === 'grid' ? 'switch-btn--active' : '']"
          @click="viewMode = 'grid'"
          title="网格视图"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <rect x="3" y="3" width="8" height="8" rx="1.5"/>
            <rect x="13" y="3" width="8" height="8" rx="1.5"/>
            <rect x="3" y="13" width="8" height="8" rx="1.5"/>
            <rect x="13" y="13" width="8" height="8" rx="1.5"/>
          </svg>
          Grid
        </button>
        <button
          :class="['switch-btn', viewMode === 'list' ? 'switch-btn--active' : '']"
          @click="viewMode = 'list'"
          title="列表视图"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="3" y1="6" x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
          List
        </button>
      </div>

      <!-- 导出交付包按钮 -->
      <button
        :class="['export-btn', exportableItems.length === 0 && 'export-btn--disabled']"
        :disabled="exportableItems.length === 0 || isExporting"
        @click="handleExport"
        :title="exportableItems.length === 0 ? '没有可导出的成片' : `打包 ${exportableItems.length} 个视频与 CSV`"
      >
        <svg v-if="!isExporting" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        <div v-else class="export-spin"></div>

        <span v-if="isExporting">打包与生成短链中…</span>
        <span v-else-if="selectedIds.length > 0">📦 导出已选 ({{ exportableItems.length }})</span>
        <span v-else>📦 增量导出未交付 ({{ exportableItems.length }})</span>
      </button>
    </div>

    <!-- ══ 过滤漏斗栏 ═══════════════════════════════════════════════════ -->
    <div class="filter-bar">
      <div class="review-mode-switch">
        <button
          :class="['review-mode-btn', { 'review-mode-btn--active': reviewMode === 'active' }]"
          @click="setReviewMode('active')"
        >
          待审变体
        </button>
        <button
          :class="['review-mode-btn', { 'review-mode-btn--active': reviewMode === 'trash' }]"
          @click="setReviewMode('trash')"
        >
          🗑️ 回收站 (已废弃)
        </button>
      </div>

      <!-- 日期范围 -->
      <div class="filter-group">
        <span class="filter-label">📅</span>
        <input
          type="date"
          v-model="filterDateFrom"
          class="filter-input filter-date"
          title="开始日期"
        />
        <span class="filter-sep">—</span>
        <input
          type="date"
          v-model="filterDateTo"
          class="filter-input filter-date"
          title="结束日期"
        />
      </div>

      <!-- 提示词搜索 -->
      <div class="filter-group filter-group--grow">
        <span class="filter-label">🔍</span>
        <input
          v-model="historySearchQuery"
          type="text"
          placeholder="提示词 / 任务 ID…"
          class="filter-input filter-search"
        />
      </div>

      <!-- 生成模式 -->
      <div class="filter-group">
        <span class="filter-label">🎬</span>
        <select v-model="filterMode" class="filter-input filter-select">
          <option value="ALL">全部模式</option>
          <option value="director">Director</option>
          <option value="blind">Blind</option>
        </select>
      </div>

      <!-- 审批状态 -->
      <div class="filter-group">
        <span class="filter-label">🔖</span>
        <select v-model="filterStatus" class="filter-input filter-select" @change="fetchApprovalList">
          <option value="ALL">全部状态 (不含废弃)</option>
          <option value="PENDING">🟡 待审核</option>
          <option value="APPROVED">🟢 已通过</option>
          <option value="REJECTED">🔴 回收站(已废弃)</option>
        </select>
      </div>

      <!-- 清除筛选 -->
      <Transition name="filter-clear-fade">
        <button
          v-if="isFiltered"
          class="filter-clear-btn"
          @click="clearFilters"
          title="清除所有筛选条件"
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
          清除
        </button>
      </Transition>
    </div>

    <!-- ══ 空态 ════════════════════════════════════════════════════════ -->
    <div v-if="filteredItems.length === 0" class="approval-empty">
      <div class="empty-icon">🔬</div>
      <p class="empty-text">
        {{ reviewMode === 'trash' ? '回收站为空，没有已废弃变体。' : '质检舱空空如也，去矩阵工厂生产吧！' }}
      </p>
      <button v-if="reviewMode === 'active'" class="empty-cta" @click="router.push('/workspace')">前往矩阵工厂</button>
    </div>

    <!-- ══ GRID 模式 ═══════════════════════════════════════════════════ -->
    <div v-else-if="viewMode === 'grid'" class="approval-grid">
      <div
        v-for="(item, index) in filteredItems"
        :key="item.id"
        :class="['qc-card-shell', {
          'qc-card-shell--selected': selectedIds.includes(item.id),
          'qc-card-shell--trash': reviewMode === 'trash',
        }]"
        @click="openPreview(index)"
      >
        <div
          class="corner-ribbon"
          :class="`ribbon-${item.status.toLowerCase()}`"
        >
          <span>{{ getStatusLabel(item.status) }}</span>
        </div>
        <span
          v-if="item.tracking_link"
          class="delivered-badge delivered-badge--grid"
          title="已生成专属追踪链并导出过"
        >
          🔗 已挂链
        </span>

        <label class="qc-checkbox" @click.stop>
          <input v-model="selectedIds" type="checkbox" :value="item.id" />
          <span>✓</span>
        </label>

        <CoverPreviewCard
          :item="item"
          :status="getStatus(item)"
          :loading="getLoading(item)"
          @approve="handleApprove"
          @reject="handleReject"
          @preview="openPreview(index)"
        />

        <div
          class="qc-meta-box"
          :class="{ 'qc-meta-box--expanded': expandedIds.has(item.id) }"
          @click.stop
        >
          <div class="qc-meta-title">{{ item.meta?.social_title || '未生成社交标题' }}</div>
          <div class="qc-meta-tags">{{ item.meta?.social_hashtags || '暂无话题标签' }}</div>
          <div class="qc-meta-desc">{{ item.meta?.social_caption || '暂无社交文案' }}</div>
          <div
            v-if="!expandedIds.has(item.id)"
            class="qc-meta-mask"
            @click="expandedIds.add(item.id)"
          />
          <button
            class="qc-expand-btn"
            @click.stop="expandedIds.has(item.id) ? expandedIds.delete(item.id) : expandedIds.add(item.id)"
          >
            {{ expandedIds.has(item.id) ? '↑ 收起' : '↓ 展开' }}
          </button>
        </div>

        <div v-if="reviewMode === 'trash'" class="qc-trash-actions" @click.stop>
          <button class="list-btn list-btn--approve" @click="restoreVariant(item)">↺ 恢复已审</button>
          <button class="list-btn list-btn--purge" @click="purgeVariant(item)">⚠ 彻底销毁</button>
        </div>
      </div>
    </div>

    <!-- ══ LIST 模式 ═══════════════════════════════════════════════════ -->
    <div v-else class="approval-list-wrap">
      <table class="approval-table">
        <thead>
          <tr>
            <th class="col-select">
              <input
                type="checkbox"
                :checked="filteredItems.length > 0 && filteredItems.every(item => selectedIds.includes(item.id))"
                @change="selectedIds = $event.target.checked ? filteredItems.map(item => item.id) : []"
              />
            </th>
            <th class="col-cover">封面</th>
            <th class="col-status">状态</th>
            <th class="col-id">任务 ID</th>
            <th class="col-prompt">提示词</th>
            <th class="col-social">社交文案</th>
            <th class="col-time">生成时间</th>
            <th class="col-dur">耗时</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(item, index) in filteredItems"
            :key="item.id"
            :class="['list-row', {
              'list-row--approved': getStatus(item) === 'APPROVED',
              'list-row--rejected': getStatus(item) === 'REJECTED',
              'list-row--selected': selectedIds.includes(item.id),
            }]"
            @click="openPreview(index)"
          >
            <td class="col-select" @click.stop>
              <input v-model="selectedIds" type="checkbox" :value="item.id" />
            </td>

            <!-- 封面缩略图 -->
            <td class="col-cover">
              <div
                class="list-thumb-wrap"
                @mouseenter="hoverVideoId = item.id"
                @mouseleave="hoverVideoId = null"
                @click.stop="openPreview(index)"
              >
                <video
                  v-if="hoverVideoId === item.id && item.video_url"
                  :src="item.video_url"
                  class="list-thumb"
                  muted
                  loop
                  autoplay
                  playsinline
                  preload="metadata"
                />
                <img
                  v-else-if="item.cover_url"
                  :src="item.cover_url"
                  class="list-thumb"
                  loading="lazy"
                />
                <div v-else class="list-thumb list-thumb--empty">
                  <span style="font-size:1.2rem;opacity:.3">🎬</span>
                </div>
                <div class="list-thumb-play">▶</div>
              </div>
            </td>

            <!-- 审批状态 -->
            <td class="col-status">
              <div class="list-status-stack">
                <span :class="['list-status-pill', `list-status-pill--${getStatus(item).toLowerCase()}`]">
                  {{ getStatus(item) === 'APPROVED' ? '✅ 通过' :
                     getStatus(item) === 'REJECTED' ? '✕ 毙掉' : '— 待审' }}
                </span>
                <span
                  v-if="item.tracking_link"
                  class="delivered-badge"
                  title="已生成专属追踪链并导出过"
                >
                  🔗 已挂链
                </span>
              </div>
            </td>

            <!-- 任务 ID -->
            <td class="col-id">
              <span class="mono text-cyan">#{{ (item.task_id || '').slice(0, 8) }}</span>
            </td>

            <!-- 提示词 -->
            <td class="col-prompt">
              <p class="list-prompt">{{ item.prompt }}</p>
            </td>

            <td class="col-social">
              <div class="list-social-title">{{ item.meta?.social_title || '未生成社交标题' }}</div>
              <div class="list-social-tags">{{ item.meta?.social_hashtags || '—' }}</div>
            </td>

            <!-- 生成时间 -->
            <td class="col-time">
              <span class="list-meta">{{ formatDate(item.created_at) }}</span>
            </td>

            <!-- 耗时 -->
            <td class="col-dur">
              <span class="list-dur mono">{{ item.duration || '—' }}s</span>
            </td>

            <!-- 操作 -->
            <td class="col-actions" @click.stop>
              <div class="list-actions">
                <template v-if="reviewMode === 'trash'">
                  <button
                    class="list-btn list-btn--approve"
                    :disabled="getLoading(item)"
                    @click="restoreVariant(item)"
                  >↺ 恢复已审</button>
                  <button
                    class="list-btn list-btn--purge"
                    @click="purgeVariant(item)"
                  >⚠ 彻底销毁</button>
                </template>
                <template v-else-if="getStatus(item) === 'PENDING'">
                  <button
                    class="list-btn list-btn--approve"
                    :disabled="getLoading(item)"
                    @click="handleApprove(item)"
                  >通过</button>
                  <button
                    class="list-btn list-btn--reject"
                    :disabled="getLoading(item)"
                    @click="handleReject(item)"
                  >毙掉</button>
                </template>
                <template v-else-if="getStatus(item) === 'APPROVED'">
                  <button
                    class="list-btn list-btn--revoke"
                    :disabled="getLoading(item)"
                    @click="handleApprove(item)"
                  >↩ 撤销</button>
                </template>
                <button
                  class="list-btn list-btn--dna"
                  :disabled="!item.hash"
                  @click="router.push('/video/' + item.hash)"
                >基因</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="selectedIds.length > 0" class="dam-floating-action-bar">
      <span class="action-count">已选中 {{ selectedIds.length }} 个变体</span>
      <template v-if="reviewMode === 'active'">
        <button class="action-btn action-btn--success" @click="handleBatchApprove">✓ 批量通过</button>
        <button class="action-btn action-btn--danger" @click="handleBatchReject">✕ 批量废弃</button>
      </template>
      <template v-else>
        <button class="action-btn action-btn--success" @click="handleBatchApprove">↺ 批量恢复已审</button>
        <button class="action-btn action-btn--danger" @click="purgeSelectedVariants">⚠ 批量销毁</button>
      </template>
      <button class="action-btn" @click="selectedIds = []">取消</button>
    </div>

    <MasterPreviewModal
      v-if="isModalVisible"
      :visible="isModalVisible"
      :video-list="previewVideoList"
      :initial-index="selectedVideoIndex"
      @close="closePreview"
      @open-detail="handleApprovalOpenDetail"
      @action="handleApprovalPreviewAction"
    />

  </div>
</template>

<style scoped>
/* ── 布局容器 ───────────────────────────────────────────────────────── */
.approval-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: radial-gradient(ellipse at top right, rgba(139, 92, 246, 0.04), transparent 60%);
}

/* ── 顶部工具栏 ──────────────────────────────────────────────────────── */
.approval-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.9rem 1.5rem 0.7rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  flex-wrap: wrap;
}

.approval-title-block {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  margin-right: auto;
}
.approval-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 900;
  background: linear-gradient(90deg, #a78bfa, #38bdf8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: .02em;
}
.approval-subtitle {
  font-size: 0.67rem;
  color: #334155;
  font-family: 'JetBrains Mono', monospace;
}
.approved-badge {
  color: #4ade80;
  font-weight: 700;
}

/* 视图切换器 */
.view-switcher {
  display: flex;
  gap: 0;
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 8px;
  overflow: hidden;
  background: rgba(15, 23, 42, 0.6);
}
.switch-btn {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.32rem 0.75rem;
  font-size: 0.73rem;
  font-weight: 600;
  color: #475569;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.16s ease;
}
.switch-btn + .switch-btn { border-left: 1px solid rgba(255, 255, 255, 0.08); }
.switch-btn:hover:not(.switch-btn--active) { color: #94a3b8; background: rgba(255,255,255,0.04); }
.switch-btn--active {
  color: #e2e8f0;
  background: linear-gradient(135deg, rgba(139,92,246,0.25), rgba(56,189,248,0.15));
}

/* ── 过滤漏斗栏 ──────────────────────────────────────────────────────── */
.filter-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1.5rem 0.55rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  background: rgba(9, 14, 30, 0.6);
  flex-wrap: wrap;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  flex-shrink: 0;
}
.filter-group--grow { flex: 1 1 160px; }

.filter-label {
  font-size: 0.75rem;
  flex-shrink: 0;
  line-height: 1;
}

.filter-sep {
  font-size: 0.72rem;
  color: #334155;
}

.filter-input {
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 7px;
  color: #e2e8f0;
  font-size: 0.75rem;
  font-family: 'Inter', sans-serif;
  outline: none;
  transition: border-color 0.18s;
  padding: 0.3rem 0.6rem;
}
.filter-input:focus { border-color: rgba(139, 92, 246, 0.5); }
.filter-input::placeholder { color: #334155; }

.filter-date {
  width: 128px;
  /* 统一日历 icon 颜色 */
  color-scheme: dark;
}

.filter-search {
  min-width: 0;
  width: 100%;
}

.filter-select {
  padding: 0.3rem 0.55rem;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%23475569' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.5rem center;
  padding-right: 1.6rem;
}
.filter-select option { background: #0f172a; }

.filter-clear-btn {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.75rem;
  border-radius: 7px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: #f87171;
  font-size: 0.72rem;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}
.filter-clear-btn:hover {
  background: rgba(239, 68, 68, 0.16);
  border-color: rgba(239, 68, 68, 0.45);
}
.filter-clear-fade-enter-active, .filter-clear-fade-leave-active { transition: opacity 0.18s, transform 0.18s; }
.filter-clear-fade-enter-from, .filter-clear-fade-leave-to { opacity: 0; transform: scale(0.88); }

/* 导出按钮 */
.export-btn {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.38rem 1rem;
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(34,197,94,0.18), rgba(56,189,248,0.12));
  border: 1px solid rgba(34, 197, 94, 0.45);
  color: #4ade80;
  font-size: 0.78rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.18s ease;
  white-space: nowrap;
}
.export-btn:hover:not(.export-btn--disabled):not(:disabled) {
  background: linear-gradient(135deg, rgba(34,197,94,0.28), rgba(56,189,248,0.2));
  box-shadow: 0 0 18px rgba(34, 197, 94, 0.3);
  transform: translateY(-1px);
}
.export-btn--disabled, .export-btn:disabled {
  opacity: 0.38;
  cursor: not-allowed;
  background: rgba(255,255,255,0.04);
  border-color: rgba(255,255,255,0.1);
  color: #475569;
}
.export-spin {
  width: 13px; height: 13px;
  border: 2px solid rgba(255,255,255,0.15);
  border-top-color: #4ade80;
  border-radius: 50%;
  animation: spin 0.75s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── 空态 ────────────────────────────────────────────────────────────── */
.approval-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
}
.empty-icon  { font-size: 3.5rem; opacity: 0.15; }
.empty-text  { font-size: 0.85rem; color: #334155; }
.empty-cta {
  padding: 0.5rem 1.5rem;
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(139,92,246,0.18), rgba(56,189,248,0.12));
  border: 1px solid rgba(139,92,246,0.3);
  color: #a78bfa;
  font-size: 0.8rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.18s;
}
.empty-cta:hover {
  background: linear-gradient(135deg, rgba(139,92,246,0.28), rgba(56,189,248,0.2));
  box-shadow: 0 0 14px rgba(139,92,246,0.25);
}

/* ── GRID 模式 ───────────────────────────────────────────────────────── */
.approval-grid {
  flex: 1;
  overflow-y: auto;
  padding: 1.1rem 1.4rem;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 220px));
  grid-auto-flow: row;
  grid-auto-rows: max-content;
  gap: 1rem;
  align-content: start;
  justify-content: start;
  align-items: start;
}

/* ── LIST 模式 ───────────────────────────────────────────────────────── */
.approval-list-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 1.5rem;
}

.approval-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 0.8rem;
}
.approval-table th {
  position: sticky;
  top: 0;
  z-index: 120;
  padding: 0.5rem 0.75rem;
  text-align: left;
  font-size: 0.63rem;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: .06em;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  background: rgba(8, 13, 28, 0.98);
  backdrop-filter: blur(14px);
  box-shadow: 0 8px 18px rgba(0, 0, 0, 0.28);
  white-space: nowrap;
}

.col-cover   { width: 56px; }
.col-status  { width: 88px; }
.col-id      { width: 100px; }
.col-prompt  { min-width: 180px; }
.col-time    { width: 112px; }
.col-dur     { width: 66px; }
.col-actions { width: 185px; }

.list-row {
  border-bottom: 1px solid rgba(255,255,255,0.04);
  transition: background 0.15s;
}
.list-row:hover { background: rgba(139,92,246,0.045); }
.list-row--approved { background: rgba(34,197,94,0.035); }
.list-row--rejected { opacity: 0.52; filter: grayscale(80%); }
.list-row td { padding: 0.55rem 0.75rem; vertical-align: middle; }

/* 状态 pill */
.list-status-pill {
  display: inline-block;
  padding: 0.18rem 0.55rem;
  border-radius: 99px;
  font-size: 0.65rem;
  font-weight: 700;
  white-space: nowrap;
}
.list-status-pill--pending  { background: rgba(255,255,255,.05); color: #475569; border: 1px solid rgba(255,255,255,.08); }
.list-status-pill--approved { background: rgba(34,197,94,.15);  color: #4ade80; border: 1px solid rgba(34,197,94,.3); }
.list-status-pill--rejected { background: rgba(239,68,68,.1);   color: #f87171; border: 1px solid rgba(239,68,68,.25); }
.list-status-stack { display: flex; align-items: center; gap: .3rem; }
.delivered-badge {
  display: inline-block;
  font-size: 0.6rem;
  font-weight: 700;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.4);
  white-space: nowrap;
}
.delivered-badge--grid {
  position: absolute;
  top: 8px;
  left: 38px;
  z-index: 9;
}

/* 封面缩略图 */
.list-thumb-wrap {
  position: relative;
  width: 34px; height: 60px;
  border-radius: 5px;
  overflow: hidden;
  cursor: pointer;
}
.list-thumb { width: 34px; height: 60px; object-fit: cover; display: block; }
.list-thumb--empty {
  display: flex; align-items: center; justify-content: center;
  background: rgba(15,23,42,0.8);
}
.list-thumb-play {
  position: absolute; inset: 0;
  background: rgba(0,0,0,.45); color: #fff;
  font-size: 0.55rem;
  display: flex; align-items: center; justify-content: center;
  opacity: 0; transition: opacity 0.15s;
}
.list-thumb-wrap:hover .list-thumb-play { opacity: 1; }

.mono      { font-family: 'JetBrains Mono', monospace; }
.text-cyan { color: #38bdf8; }
.list-prompt {
  margin: 0; color: #94a3b8; line-height: 1.45;
  display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden;
}
.list-meta { color: #475569; font-size: 0.7rem; }
.list-dur  { color: #38bdf8; font-size: 0.7rem; }

/* 操作按钮 */
.list-actions { display: flex; gap: 0.3rem; }
.list-btn {
  padding: 0.22rem 0.6rem;
  border-radius: 6px;
  font-size: 0.68rem;
  font-weight: 700;
  cursor: pointer;
  border: 1px solid;
  transition: all 0.15s;
  white-space: nowrap;
}
.list-btn:disabled { opacity: 0.38; cursor: not-allowed; }
.list-btn--approve { background: rgba(34,197,94,.1);  border-color: rgba(34,197,94,.35); color: #4ade80; }
.list-btn--approve:hover { background: rgba(34,197,94,.2); }
.list-btn--reject  { background: rgba(239,68,68,.08); border-color: rgba(239,68,68,.3);  color: #f87171; }
.list-btn--reject:hover  { background: rgba(239,68,68,.18); }
.list-btn--revoke  { background: rgba(255,255,255,.04); border-color: rgba(255,255,255,.1); color: #64748b; }
.list-btn--revoke:hover  { color: #94a3b8; }
.list-btn--dna     { background: rgba(56,189,248,.08); border-color: rgba(56,189,248,.22); color: #38bdf8; }
.list-btn--dna:hover     { background: rgba(56,189,248,.15); }
.list-btn--purge   { background: rgba(127,29,29,.18); border-color: rgba(248,113,113,.4); color: #fca5a5; }
.list-btn--purge:hover { background: rgba(127,29,29,.35); }

/* 质检视图切换 */
.review-mode-switch {
  display: flex;
  flex-shrink: 0;
  border: 1px solid rgba(99,102,241,.2);
  border-radius: 8px;
  overflow: hidden;
  background: rgba(15,23,42,.7);
}
.review-mode-btn {
  padding: .32rem .7rem;
  border: 0;
  background: transparent;
  color: #64748b;
  font-size: .7rem;
  font-weight: 700;
  cursor: pointer;
}
.review-mode-btn + .review-mode-btn { border-left: 1px solid rgba(99,102,241,.2); }
.review-mode-btn--active { color: #c4b5fd; background: rgba(99,102,241,.16); }

/* Grid 质检外壳与元数据 */
.qc-card-shell {
  position: relative;
  isolation: isolate;
  min-width: 0;
  width: 100%;
  height: max-content;
  display: flex;
  flex-direction: column;
  align-self: start;
  grid-row: auto;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,.07);
  border-radius: 12px;
  background: rgba(13,18,38,.88);
  transition: border-color .18s, box-shadow .18s;
  contain: layout paint;
}
.qc-card-shell--selected {
  border-color: rgba(139,92,246,.75);
  box-shadow: 0 0 0 2px rgba(139,92,246,.2), 0 10px 28px rgba(0,0,0,.4);
}
/* 卡片右上角斜向丝带角标 */
.corner-ribbon {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 76px;
  height: 76px;
  overflow: hidden;
  z-index: 4;
  pointer-events: none;
}
.corner-ribbon span {
  position: absolute;
  top: 18px;
  right: -26px;
  width: 110px;
  transform: rotate(45deg);
  text-align: center;
  color: #fff;
  font-size: .54rem;
  font-weight: 900;
  line-height: 1;
  letter-spacing: .08em;
  white-space: nowrap;
  box-shadow: 0 2px 4px rgba(0,0,0,.3);
  padding: 3px 0;
}
.ribbon-pending span { background: #f59e0b; }
.ribbon-approved span { background: #10b981; }
.ribbon-rejected span { background: #ef4444; }
.qc-card-shell :deep(.cover-card) {
  flex: 0 0 auto;
  width: 100%;
  height: auto;
  min-height: 0;
  position: relative;
  z-index: 1;
  border: 0;
  border-radius: 0;
  box-shadow: none;
  transform: none;
}
.qc-card-shell :deep(.cover-card:hover) { transform: none; }
.qc-card-shell :deep(.status-badge) { display: none; }
.qc-card-shell--trash :deep(.cover-actions) { display: none; }
.qc-checkbox {
  position: absolute;
  z-index: 8;
  top: 8px;
  left: 8px;
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(196,181,253,.55);
  border-radius: 6px;
  background: rgba(15,23,42,.82);
  cursor: pointer;
}
.qc-checkbox input { position: absolute; opacity: 0; pointer-events: none; }
.qc-checkbox span { opacity: 0; color: #fff; font-size: .75rem; }
.qc-checkbox:has(input:checked) { background: #7c3aed; border-color: #a78bfa; }
.qc-checkbox:has(input:checked) span { opacity: 1; }
.qc-meta-box {
  position: relative;
  z-index: 2;
  flex: 0 0 auto;
  width: 100%;
  box-sizing: border-box;
  padding: .5rem .5rem 1.25rem;
  background: rgba(15,23,42,.8);
  border-top: 1px solid rgba(99,102,241,.2);
  max-height: 80px;
  overflow: hidden;
  transition: max-height .3s ease;
}
.qc-meta-box--expanded { max-height: 400px; }
.qc-meta-title { font-size: .75rem; font-weight: bold; color: #e2e8f0; margin-bottom: .2rem; }
.qc-meta-tags { font-size: .65rem; color: #38bdf8; margin-bottom: .3rem; word-break: break-word; }
.qc-meta-desc { font-size: .65rem; color: #94a3b8; line-height: 1.4; white-space: pre-wrap; }
.qc-meta-mask {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 30px;
  background: linear-gradient(transparent, rgba(15,23,42,1));
  cursor: pointer;
}
.qc-expand-btn {
  position: absolute;
  bottom: 2px;
  right: 8px;
  z-index: 2;
  border: none;
  background: transparent;
  color: #818cf8;
  font-size: .6rem;
  cursor: pointer;
}

@media (max-width: 900px) {
  .approval-grid {
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    padding: .8rem;
    gap: .75rem;
  }
}
.qc-trash-actions {
  display: flex;
  gap: .4rem;
  padding: .55rem;
  border-top: 1px solid rgba(248,113,113,.14);
}
.qc-trash-actions .list-btn { flex: 1; }

/* List 选择、文案与 hover video */
.col-select { width: 34px; text-align: center !important; }
.col-social { min-width: 180px; max-width: 260px; }
.col-select input { accent-color: #7c3aed; cursor: pointer; }
.list-row--selected { outline: 1px solid rgba(139,92,246,.45); outline-offset: -1px; }
.list-social-title {
  color: #cbd5e1;
  font-size: .72rem;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.list-social-tags {
  margin-top: .15rem;
  color: #38bdf8;
  font-size: .64rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* DAM 同款浮动操作栏 */
.dam-floating-action-bar {
  position: fixed;
  bottom: 1.5rem;
  left: 50%;
  z-index: 500;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: .6rem;
  padding: .6rem 1.1rem;
  border: 1px solid rgba(139,92,246,.45);
  border-radius: 99px;
  background: rgba(15,5,35,.86);
  backdrop-filter: blur(16px);
  box-shadow: 0 0 30px rgba(139,92,246,.3), 0 8px 32px rgba(0,0,0,.6);
  white-space: nowrap;
}
.action-count { padding: 0 .3rem; color: #c4b5fd; font-size: .8rem; font-weight: 600; }
.dam-floating-action-bar .action-btn {
  padding: .36rem .85rem;
  border: 1px solid rgba(148,163,184,.25);
  border-radius: 99px;
  background: rgba(255,255,255,.05);
  color: #cbd5e1;
  font-size: .75rem;
  font-weight: 700;
  cursor: pointer;
}
.dam-floating-action-bar .action-btn--success {
  border-color: rgba(34,197,94,.4);
  background: rgba(34,197,94,.13);
  color: #4ade80;
}
.dam-floating-action-bar .action-btn--danger {
  border-color: rgba(239,68,68,.4);
  background: rgba(239,68,68,.12);
  color: #f87171;
}
</style>
