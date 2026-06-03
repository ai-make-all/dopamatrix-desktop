<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/appStore'
import CoverPreviewCard from '../components/matrix/CoverPreviewCard.vue'

const store  = useAppStore()
const router = useRouter()

// ── 数据 ────────────────────────────────────────────────────────────────────
const historyList        = ref([])
const historySearchQuery = ref('')
const viewMode           = ref('grid')   // 'grid' | 'list'
const isExporting        = ref(false)

// ── 多维过滤漏斗状态 ──────────────────────────────────────────────────────────
const filterDateFrom = ref('')    // 'YYYY-MM-DD' 或空
const filterDateTo   = ref('')    // 'YYYY-MM-DD' 或空
const filterMode     = ref('ALL') // 'ALL' | 'director' | 'blind' | ...
const filterStatus   = ref('ALL') // 'ALL' | 'PENDING' | 'APPROVED' | 'REJECTED'

const isFiltered = computed(() =>
  filterDateFrom.value || filterDateTo.value ||
  filterMode.value !== 'ALL' || filterStatus.value !== 'ALL' ||
  historySearchQuery.value.trim() !== ''
)

function clearFilters() {
  filterDateFrom.value   = ''
  filterDateTo.value     = ''
  filterMode.value       = 'ALL'
  filterStatus.value     = 'ALL'
  historySearchQuery.value = ''
}

/**
 * 审批状态映射表：itemKey → 'PENDING' | 'APPROVED' | 'REJECTED'
 * itemKey = `${task_id}__${asset_hash}`
 * 不合并进 flatItems computed，避免状态变更触发全量重计算。
 */
const statusMap  = reactive({})
const loadingMap = reactive({})   // itemKey → Boolean（单条审批中的 loading）

// ── 全局播放器 ───────────────────────────────────────────────────────────────
const previewVisible = ref(false)
const previewItem    = ref(null)
const videoRef       = ref(null)

// ── 计算属性 ────────────────────────────────────────────────────────────────

function itemKey(item) {
  return `${item.task_id}__${item.hash}`
}

/**
 * 将 TaskHistory 记录展平为每个 output_asset 独立一条展示项。
 */
const flatItems = computed(() => {
  const items = []
  for (const record of historyList.value) {
    const assets = record.output_assets || []
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
        download_url:    '',
        raw_path:        '',
      })
    } else {
      assets.forEach((asset, idx) => {
        items.push({
          id:              `${record.id}_${idx}`,
          task_id:         record.task_id,
          prompt:          record.prompt,
          duration:        record.duration,
          created_at:      record.created_at,
          generation_mode: record.generation_mode || '',
          cover_url:       asset.cover_url || (asset.cover_path ? store.buildVideoUrl(asset.cover_path) : ''),
          video_url:       store.buildVideoUrl(asset.path),
          hash:            asset.hash || '',
          download_url:    asset.download_url || '',
          raw_path:        asset.path || '',
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
  let items = flatItems.value

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

const approvedCount = computed(() =>
  flatItems.value.filter(i => getStatus(i) === 'APPROVED').length
)

// ── 状态辅助 ─────────────────────────────────────────────────────────────────
function getStatus(item)  { return statusMap[itemKey(item)]  || 'PENDING' }
function getLoading(item) { return loadingMap[itemKey(item)] || false }

// ── 数据加载 ─────────────────────────────────────────────────────────────────
async function fetchHistory() {
  try {
    const resp = await axios.get(`${store.API_BASE}/api/v1/history`)
    historyList.value = resp.data || []
    await fetchAllApprovals()
  } catch (err) {
    store.showToast('⚠️ 获取质检记录失败: ' + err.message)
  }
}

/**
 * 拉取全量审批状态并合并到 statusMap。
 * 后端返回 { asset_hash: status } 扁平字典。
 */
async function fetchAllApprovals() {
  try {
    const resp = await axios.get(`${store.API_BASE}/api/v1/matrix/approvals`)
    const remoteMap = resp.data || {}
    // 仅覆盖已存在记录的状态（新条目保持 PENDING）
    for (const item of flatItems.value) {
      if (item.hash && remoteMap[item.hash] !== undefined) {
        statusMap[itemKey(item)] = remoteMap[item.hash]
      }
    }
  } catch (err) {
    // 审批状态拉取失败不阻断主流程，静默处理
    console.warn('[ApprovalView] fetchAllApprovals 失败（已忽略）:', err.message)
  }
}

onMounted(fetchHistory)

// ── 审批操作 ─────────────────────────────────────────────────────────────────
async function handleApprove(item) {
  if (!item.hash || !item.task_id) return
  const key = itemKey(item)
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

async function setVariantStatus(item, newStatus) {
  const key = itemKey(item)
  loadingMap[key] = true
  try {
    await axios.put(
      `${store.API_BASE}/api/v1/matrix/variants/${item.task_id}/${item.hash}/status`,
      { status: newStatus }
    )
    // 极速无感刷新：直接修改本地状态，不整页刷新
    statusMap[key] = newStatus

    const label = newStatus === 'APPROVED' ? '✅ 已通过'
                : newStatus === 'REJECTED' ? '❌ 已毙掉'
                : '↩ 已撤销'
    store.showToast(`${label}：#${(item.task_id || '').slice(0, 8)}`)
  } catch (err) {
    const msg = err.response?.data?.detail || err.message
    store.showToast(`⚠️ 状态更新失败: ${msg}`)
  } finally {
    loadingMap[key] = false
  }
}

// ── 导出交付包 ───────────────────────────────────────────────────────────────
async function handleExport() {
  if (approvedCount.value === 0) {
    store.showToast('⚠️ 请先通过至少一个变体，再导出交付包。')
    return
  }
  isExporting.value = true
  try {
    const exportUrl = `${store.API_BASE}/api/v1/matrix/export`
    // 触发浏览器原生文件下载
    const link = document.createElement('a')
    link.href = exportUrl
    link.download = 'dopamatrix_approved.zip'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    store.showToast('📦 交付包下载已启动！')
  } catch (err) {
    store.showToast('⚠️ 导出失败: ' + err.message)
  } finally {
    setTimeout(() => { isExporting.value = false }, 2000)
  }
}

// ── 全局播放器 ───────────────────────────────────────────────────────────────
function handlePreview(item) {
  previewItem.value   = item
  previewVisible.value = true
}

function closePreview() {
  previewVisible.value = false
  if (videoRef.value) {
    videoRef.value.pause()
    videoRef.value.src = ''
  }
  previewItem.value = null
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
        :class="['export-btn', approvedCount === 0 && 'export-btn--disabled']"
        :disabled="approvedCount === 0 || isExporting"
        @click="handleExport"
        :title="approvedCount === 0 ? '请先通过至少一个变体' : `导出 ${approvedCount} 个已通过成片`"
      >
        <svg v-if="!isExporting" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        <div v-else class="export-spin"></div>
        {{ isExporting ? '打包中…' : `📦 导出 (${approvedCount})` }}
      </button>
    </div>

    <!-- ══ 过滤漏斗栏 ═══════════════════════════════════════════════════ -->
    <div class="filter-bar">
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
        <select v-model="filterStatus" class="filter-input filter-select">
          <option value="ALL">全部状态</option>
          <option value="PENDING">🟡 待审核</option>
          <option value="APPROVED">✅ 已通过</option>
          <option value="REJECTED">❌ 已毙掉</option>
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
      <p class="empty-text">质检舱空空如也，去矩阵工厂生产吧！</p>
      <button class="empty-cta" @click="router.push('/workspace')">前往矩阵工厂</button>
    </div>

    <!-- ══ GRID 模式 ═══════════════════════════════════════════════════ -->
    <div v-else-if="viewMode === 'grid'" class="approval-grid">
      <CoverPreviewCard
        v-for="item in filteredItems"
        :key="item.id"
        :item="item"
        :status="getStatus(item)"
        :loading="getLoading(item)"
        @approve="handleApprove"
        @reject="handleReject"
        @preview="handlePreview"
      />
    </div>

    <!-- ══ LIST 模式 ═══════════════════════════════════════════════════ -->
    <div v-else class="approval-list-wrap">
      <table class="approval-table">
        <thead>
          <tr>
            <th class="col-cover">封面</th>
            <th class="col-status">状态</th>
            <th class="col-id">任务 ID</th>
            <th class="col-prompt">提示词</th>
            <th class="col-time">生成时间</th>
            <th class="col-dur">耗时</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in filteredItems"
            :key="item.id"
            :class="['list-row', {
              'list-row--approved': getStatus(item) === 'APPROVED',
              'list-row--rejected': getStatus(item) === 'REJECTED',
            }]"
          >
            <!-- 封面缩略图 -->
            <td class="col-cover">
              <div class="list-thumb-wrap" @click="handlePreview(item)">
                <img
                  v-if="item.cover_url"
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
              <span :class="['list-status-pill', `list-status-pill--${getStatus(item).toLowerCase()}`]">
                {{ getStatus(item) === 'APPROVED' ? '✅ 通过' :
                   getStatus(item) === 'REJECTED' ? '✕ 毙掉' : '— 待审' }}
              </span>
            </td>

            <!-- 任务 ID -->
            <td class="col-id">
              <span class="mono text-cyan">#{{ (item.task_id || '').slice(0, 8) }}</span>
            </td>

            <!-- 提示词 -->
            <td class="col-prompt">
              <p class="list-prompt">{{ item.prompt }}</p>
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
            <td class="col-actions">
              <div class="list-actions">
                <template v-if="getStatus(item) === 'PENDING'">
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
                <template v-else>
                  <button
                    class="list-btn list-btn--revoke"
                    :disabled="getLoading(item)"
                    @click="getStatus(item) === 'APPROVED' ? handleReject(item) : handleApprove(item)"
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

    <!-- ══ 全局唯一视频播放弹窗 ══════════════════════════════════════════ -->
    <Teleport to="body">
      <Transition name="preview-fade">
        <div v-if="previewVisible" class="preview-overlay" @click.self="closePreview">
          <div class="preview-modal">
            <!-- 标题栏 -->
            <div class="preview-header">
              <div class="preview-meta">
                <span class="preview-task-id mono">#{{ (previewItem?.task_id || '').slice(0, 8) }}</span>
                <span class="preview-prompt">{{ previewItem?.prompt }}</span>
              </div>
              <button class="preview-close" @click="closePreview">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>

            <!-- 视频播放器：仅弹窗打开时赋值 src，防止后台预加载 -->
            <video
              ref="videoRef"
              class="preview-video"
              controls
              autoplay
              preload="auto"
              :src="previewVisible && previewItem?.video_url ? previewItem.video_url : ''"
            />

            <!-- 底部操作 -->
            <div class="preview-footer">
              <button
                :class="['preview-action-btn', 'preview-approve',
                  previewItem && getStatus(previewItem) === 'APPROVED' ? 'preview-action-btn--active-green' : '']"
                @click="handleApprove(previewItem)"
                :disabled="previewItem && getLoading(previewItem)"
              >
                {{ previewItem && getStatus(previewItem) === 'APPROVED' ? '✅ 已通过' : '✅ 通过' }}
              </button>
              <button
                :class="['preview-action-btn', 'preview-reject',
                  previewItem && getStatus(previewItem) === 'REJECTED' ? 'preview-action-btn--active-red' : '']"
                @click="handleReject(previewItem)"
                :disabled="previewItem && getLoading(previewItem)"
              >
                {{ previewItem && getStatus(previewItem) === 'REJECTED' ? '❌ 已毙掉' : '❌ 毙掉' }}
              </button>
              <a
                v-if="previewItem?.download_url"
                :href="previewItem.download_url"
                target="_blank"
                class="preview-action-btn preview-dl"
              >⬇ 下载</a>
              <button
                v-if="previewItem?.hash"
                class="preview-action-btn preview-dna"
                @click="router.push('/video/' + previewItem.hash); closePreview()"
              >🧬 基因</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

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
  grid-template-columns: repeat(auto-fill, minmax(162px, 1fr));
  gap: 0.9rem;
  align-content: start;
}

/* ── LIST 模式 ───────────────────────────────────────────────────────── */
.approval-list-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 1.5rem;
}

.approval-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.approval-table th {
  padding: 0.5rem 0.75rem;
  text-align: left;
  font-size: 0.63rem;
  font-weight: 700;
  color: #334155;
  text-transform: uppercase;
  letter-spacing: .06em;
  border-bottom: 1px solid rgba(255,255,255,0.06);
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

/* ── 全局播放器弹窗 ──────────────────────────────────────────────────── */
.preview-overlay {
  position: fixed; inset: 0; z-index: 9500;
  background: rgba(0,0,0,0.78);
  backdrop-filter: blur(8px);
  display: flex; align-items: center; justify-content: center;
  padding: 1.5rem;
}
.preview-modal {
  width: 100%; max-width: 420px;
  background: rgba(9,14,30,0.98);
  border: 1px solid rgba(139,92,246,0.3);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 0 60px rgba(139,92,246,0.2), 0 24px 48px rgba(0,0,0,0.7);
  display: flex; flex-direction: column;
}
.preview-header {
  display: flex; align-items: flex-start; gap: 0.75rem;
  padding: 1rem 1.1rem 0.75rem;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.preview-meta { flex: 1; display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; }
.preview-task-id { font-size: 0.67rem; color: #38bdf8; font-family: 'JetBrains Mono', monospace; }
.preview-prompt {
  font-size: 0.77rem; color: #94a3b8; line-height: 1.4;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.preview-close {
  flex-shrink: 0; width: 28px; height: 28px;
  border-radius: 7px;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04);
  color: #475569; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.preview-close:hover { color: #f87171; border-color: rgba(239,68,68,0.35); }

.preview-video {
  width: 100%; background: #000; display: block;
  max-height: 65vh; object-fit: contain;
}
.preview-footer {
  display: flex; gap: 0.45rem; padding: 0.7rem 1rem;
  border-top: 1px solid rgba(255,255,255,0.06);
  flex-wrap: wrap;
}
.preview-action-btn {
  flex: 1; padding: 0.42rem 0.4rem;
  border-radius: 8px; font-size: 0.76rem; font-weight: 700;
  cursor: pointer; border: 1px solid;
  text-align: center; text-decoration: none;
  transition: all 0.16s; white-space: nowrap; display: block;
}
.preview-action-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.preview-approve {
  background: rgba(34,197,94,.1); border-color: rgba(34,197,94,.35); color: #4ade80;
}
.preview-approve:hover:not(:disabled) { background: rgba(34,197,94,.22); }
.preview-action-btn--active-green {
  background: rgba(34,197,94,.28) !important;
  border-color: rgba(34,197,94,.6) !important;
  box-shadow: 0 0 12px rgba(34,197,94,.3);
}
.preview-reject {
  background: rgba(239,68,68,.08); border-color: rgba(239,68,68,.3); color: #f87171;
}
.preview-reject:hover:not(:disabled) { background: rgba(239,68,68,.2); }
.preview-action-btn--active-red {
  background: rgba(239,68,68,.25) !important;
  border-color: rgba(239,68,68,.55) !important;
  box-shadow: 0 0 12px rgba(239,68,68,.25);
}
.preview-dl   {
  background: rgba(255,255,255,.04); border-color: rgba(255,255,255,.1); color: #94a3b8;
}
.preview-dl:hover     { color: #38bdf8; border-color: rgba(56,189,248,.3); }
.preview-dna  {
  background: rgba(56,189,248,.08); border-color: rgba(56,189,248,.22); color: #38bdf8;
}
.preview-dna:hover    { background: rgba(56,189,248,.16); }

/* ── 弹窗过渡 ───────────────────────────────────────────────────────── */
.preview-fade-enter-active { transition: all 0.22s cubic-bezier(.22,1,.36,1); }
.preview-fade-leave-active { transition: all 0.16s ease-in; }
.preview-fade-enter-from, .preview-fade-leave-to { opacity: 0; }
.preview-fade-enter-from .preview-modal { transform: scale(0.94) translateY(12px); }
</style>
