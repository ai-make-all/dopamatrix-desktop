<script setup>
import { ref, watch, onMounted, computed, reactive } from 'vue'
import { open } from '@tauri-apps/plugin-dialog'
import axios from 'axios'
import AudioAssetCard from '../components/AudioAssetCard.vue'
import { useAppStore } from '../stores/appStore'
import { parseFacetedTags, getVisiblePills, getTagPillParts } from '../utils/tagParser.js'
import { ASSET_REGISTRY, FACET_NAMESPACES } from '../utils/assetConfig.js'

const store = useAppStore()

const activeCategory  = ref('video')
const viewMode        = ref('grid')   // 'grid' | 'list'
const assetList       = ref([])

const isAudioCategory = computed(() => ['audio_bgm', 'sfx'].includes(activeCategory.value))
const activeMeta      = computed(() => ASSET_REGISTRY[activeCategory.value])

// ── Search / Filter / Bulk-select ─────────────────────────────
const searchQuery        = ref('')
const filterOnlyUntagged = ref(false)
// selectedIds 独立内存 — 视图模式切换时 100% 保留，分类切换时重置
const selectedIds        = ref([])

const filteredAssetList = computed(() => {
  const q           = searchQuery.value.trim().toLowerCase()
  const isTagSearch = q.startsWith('#')
  const qClean      = isTagSearch ? q.slice(1) : q

  return assetList.value.filter(item => {
    if (qClean) {
      if (isTagSearch) {
        if (!(item.tags || []).some(t => t.toLowerCase().includes(qClean))) return false
      } else {
        const fileName = (item.file_path || '').split(/[/\\]/).pop().toLowerCase()
        const tagHit   = (item.tags || []).some(t => t.toLowerCase().includes(qClean))
        if (!fileName.includes(qClean) && !tagHit) return false
      }
    }
    if (filterOnlyUntagged.value && (item.tags || []).length > 0) return false
    return true
  })
})

function toggleSelect(id) {
  const idx = selectedIds.value.indexOf(id)
  if (idx === -1) selectedIds.value.push(id)
  else selectedIds.value.splice(idx, 1)
}

function selectAll() {
  const allIds = filteredAssetList.value.map(i => i.id)
  selectedIds.value = selectedIds.value.length === allIds.length ? [] : [...allIds]
}

function bulkAddTag() {
  openTagModal()
}

// ── FacetBuckets 打标桶配置 (静态元数据，非响应式) ─────────────
const FACET_BUCKETS = [
  { key: 'hook',   prefix: 'hook:',   label: '剧情钩子区', icon: '⚓', theme: 'hook',   ph: '如 残血 / 炫技 / 高光开局…'   },
  { key: 'entity', prefix: 'entity:', label: '视觉实体区', icon: '🏷', theme: 'entity', ph: '如 美女 / 街景 / 产品特写…'   },
  { key: 'vibe',   prefix: 'vibe:',   label: '情绪氛围区', icon: '🌊', theme: 'vibe',   ph: '如 燃 / 治愈 / 悬疑紧张…'    },
  { key: 'layer',  prefix: '',        label: 'Y轴扩展层',  icon: '⚡', theme: 'layer',  ph: '如 vfx:粒子爆炸 / sfx:打击音…' },
]

// ── Text Template Modal ────────────────────────────────────────
const showTextModal = ref(false)
const textForm = reactive({ asset_name: '', zh: '', en: '', ar: '' })

// ── Import Modal ───────────────────────────────────────────────
const showImportModal     = ref(false)
const pendingImportFiles  = ref([])
const pendingEmotionTag   = ref('')

// 分面打标桶 — 每个 key 存储完整 raw tag（含前缀）
const pendingFacetBuckets = ref({ hook: [], entity: [], vibe: [], layer: [] })
// 每个打标桶的输入框绑定
const bucketInputs        = ref({ hook: '', entity: '', vibe: '', layer: '' })
// 全局词云：从后端拉取或从当前列表聚合
const globalTagCloud      = ref([])

// 将词云平铺 tags 按分面前缀分发到各桶的候选列表
const bucketClouds = computed(() => {
  const clouds = { hook: [], entity: [], vibe: [], layer: [] }
  for (const raw of globalTagCloud.value) {
    const ci = raw.indexOf(':')
    if (ci === -1) continue
    const prefix = raw.slice(0, ci).toLowerCase()
    const value  = raw.slice(ci + 1)
    if      (prefix === 'hook')                       clouds.hook.push({ raw, display: value })
    else if (prefix === 'entity')                     clouds.entity.push({ raw, display: value })
    else if (prefix === 'vibe')                       clouds.vibe.push({ raw, display: value })
    else if (prefix === 'vfx' || prefix === 'sfx')   clouds.layer.push({ raw, display: raw })
  }
  return clouds
})

// 所有桶的标签展平，用于最终 payload
const allPendingTags = computed(() => Object.values(pendingFacetBuckets.value).flat())

async function fetchGlobalTagCloud() {
  try {
    const resp = await axios.get(`${store.API_BASE}/api/v1/assets/tags`)
    globalTagCloud.value = Array.isArray(resp.data) ? resp.data : (resp.data?.tags ?? [])
  } catch {
    // fallback：从当前已加载列表中聚合
    const seen = new Set()
    assetList.value.forEach(item => (item.tags || []).forEach(t => seen.add(t)))
    globalTagCloud.value = [...seen]
  }
}

// 从输入框向打标桶写入标签（自动追加命名空间前缀）
function addBucketInput(bucketKey) {
  const raw = bucketInputs.value[bucketKey].trim()
  if (!raw) return
  let fullTag
  if (bucketKey === 'layer') {
    // Layer 桶：若已有 vfx:/sfx: 前缀则保留，否则默认追加 vfx:
    fullTag = /^(vfx|sfx):/.test(raw) ? raw : `vfx:${raw}`
  } else {
    const bucket   = FACET_BUCKETS.find(b => b.key === bucketKey)
    const stripped = raw.replace(new RegExp(`^(hook|entity|vibe):`), '').trim()
    fullTag        = stripped ? `${bucket.prefix}${stripped}` : ''
  }
  if (!fullTag || pendingFacetBuckets.value[bucketKey].includes(fullTag)) {
    bucketInputs.value[bucketKey] = ''
    return
  }
  pendingFacetBuckets.value[bucketKey].push(fullTag)
  bucketInputs.value[bucketKey] = ''
}

// 词云一键飞入打标桶
function injectCloudTag(bucketKey, rawTag) {
  if (!pendingFacetBuckets.value[bucketKey].includes(rawTag))
    pendingFacetBuckets.value[bucketKey].push(rawTag)
}

function removeFromBucket(bucketKey, tag) {
  pendingFacetBuckets.value[bucketKey] = pendingFacetBuckets.value[bucketKey].filter(t => t !== tag)
}

async function fetchAssets() {
  try {
    const resp = await axios.get(`${store.API_BASE}/api/v1/assets?asset_type=${activeCategory.value}`)
    assetList.value = resp.data
  } catch (err) {
    store.showToast('获取素材失败: ' + err.message)
  }
}

async function importAssets() {
  const meta = ASSET_REGISTRY[activeCategory.value] ?? ASSET_REGISTRY.video
  if (!meta.extensions || meta.extensions.length === 0) {
    if (activeCategory.value === 'text_template') {
      textForm.asset_name = ''; textForm.zh = ''; textForm.en = ''; textForm.ar = ''
      showTextModal.value = true
    } else {
      store.showToast('⚠️ 该资产类型不支持直接导入文件')
    }
    return
  }
  const filter = { name: meta.label, extensions: meta.extensions }
  try {
    const selected = await open({ multiple: true, filters: [filter] })
    if (!selected || selected.length === 0) return
    pendingImportFiles.value  = Array.isArray(selected) ? selected : [selected]
    pendingEmotionTag.value   = ''
    pendingFacetBuckets.value = { hook: [], entity: [], vibe: [], layer: [] }
    bucketInputs.value        = { hook: '', entity: '', vibe: '', layer: '' }
    fetchGlobalTagCloud()
    showImportModal.value     = true
  } catch (err) {
    console.error('[Import Assets] 文件选择失败：', err)
    store.showToast('文件选择失败: ' + err.message)
  }
}

async function confirmImport() {
  if (isAudioCategory.value && !pendingEmotionTag.value) {
    store.showToast('⚠️ 请先选择情绪标签，这是后端 DopaMatrix 引擎的强制要求！')
    return
  }
  showImportModal.value = false
  store.showToast('正在导入并计算素材哈希...')

  const payload = {
    file_paths: pendingImportFiles.value,
    asset_type: activeCategory.value,
    tags:       isAudioCategory.value ? [pendingEmotionTag.value] : allPendingTags.value,
    ...(isAudioCategory.value  && { emotion_tag: pendingEmotionTag.value }),
  }

  try {
    const resp = await axios.post(`${store.API_BASE}/api/v1/assets/import`, payload)
    const tagSummary = payload.tags.length
      ? `，已打标：${payload.tags.map(t => `#${t}`).join(' ')}`
      : ''
    store.showToast(`✅ ${resp.data.message ?? '导入成功'}${tagSummary}`)
    fetchAssets()
  } catch (err) {
    store.showToast('导入失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    pendingImportFiles.value  = []
    pendingEmotionTag.value   = ''
    pendingFacetBuckets.value = { hook: [], entity: [], vibe: [], layer: [] }
  }
}

async function submitTextAsset() {
  if (!textForm.asset_name.trim()) {
    store.showToast('⚠️ 请填写资产名称')
    return
  }
  if (!textForm.zh.trim() && !textForm.en.trim() && !textForm.ar.trim()) {
    store.showToast('⚠️ 至少填写一种语言的内容')
    return
  }
  const payload = {
    asset_name: textForm.asset_name.trim(),
    content_matrix: {
      ...(textForm.zh.trim() && { zh: textForm.zh.trim() }),
      ...(textForm.en.trim() && { en: textForm.en.trim() }),
      ...(textForm.ar.trim() && { ar: textForm.ar.trim() }),
    },
  }
  try {
    await axios.post(`${store.API_BASE}/api/v1/assets/text`, payload)
    showTextModal.value = false
    store.showToast(`✅ 文本资产「${payload.asset_name}」已成功写入 DAM`)
    fetchAssets()
  } catch (err) {
    store.showToast('创建失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function updateAudioEmotion(item) {
  try {
    await axios.patch(`${store.API_BASE}/api/v1/assets/${item.id}/emotion`, { emotion_tag: item.emotion_tag })
    store.showToast(`🎵 情绪标签已更新为 ${item.emotion_tag}`)
  } catch (err) {
    store.showToast('情绪标签更新失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function removeTag(item, tagToRemove) {
  const oldTags = [...item.tags]
  item.tags = item.tags.filter(t => t !== tagToRemove)
  try {
    await axios.patch(`${store.API_BASE}/api/v1/assets/${item.id}/tags`, { tags: item.tags })
  } catch (err) {
    item.tags = oldTags
    store.showToast('标签移除失败: ' + (err.response?.data?.detail || err.message))
  }
}

// ── Data Grid 交互状态 ─────────────────────────────────────────
const hoverPreview = ref(null)  // { id, src, isVideo, isSceneMaster, slots, x, y }

// 格式化轴类型显示（X_STRUCTURE → X结构）
function formatAxisLabel(axisType) {
  if (axisType === 'X_STRUCTURE') return 'X结构'
  return axisType
}

// 底模分类检测
const isContainerCategory = computed(() => ASSET_REGISTRY[activeCategory.value]?.is_container ?? false)

// 场景底模在 Data Grid 列表模式额外展示插槽数列
const dgVisualGridStyle = computed(() =>
  activeCategory.value === 'scene_master'
    ? { gridTemplateColumns: '40px 56px 1fr 80px 2fr 76px 44px' }
    : {}
)

function showPreview(item, event) {
  const rect          = event.currentTarget.getBoundingClientRect()
  const isSceneMaster = activeCategory.value === 'scene_master'
  hoverPreview.value = {
    id:            item.id,
    src:           store.buildVideoUrl(item.file_path),
    isVideo:       activeCategory.value === 'video',
    isSceneMaster,
    slots:         isSceneMaster ? (item.manifest?.slots ?? []) : [],
    x:             rect.right + 12,
    y:             Math.min(rect.top, window.innerHeight - 360),
  }
}
function hidePreview() { hoverPreview.value = null }

// ── 分面打标 Modal（批量 / 单条统一入口）──────────────────────
const showTagModal         = ref(false)
const tagModalMode         = ref('bulk') // 'bulk' | 'single'
const tagModalItem         = ref(null)
const selectedFacetPrefix  = ref('')
const tagValue             = ref('')

// 当前打标目标的资产类型：单选时取素材自身类型，批量时取当前分类页
const tagTargetType = computed(() =>
  tagModalItem.value?.asset_type || activeCategory.value
)

function openTagModal(item) {
  tagValue.value = ''
  if (item !== undefined && item !== null) {
    tagModalMode.value = 'single'
    tagModalItem.value = item
  } else {
    if (!selectedIds.value.length) {
      store.showToast('请先框选要打标的素材')
      return
    }
    tagModalMode.value = 'bulk'
    tagModalItem.value = null
  }
  // 强制初始化为该类型的第一个合法前缀，杜绝无前缀空提交
  const allowedPrefixes = ASSET_REGISTRY[tagTargetType.value]?.facet_prefix ?? []
  selectedFacetPrefix.value = allowedPrefixes[0] ?? ''
  showTagModal.value = true
}

function cancelTagModal() {
  showTagModal.value = false
  tagModalItem.value = null
}

async function confirmTagModal() {
  const v = tagValue.value.trim()
  if (!v) return
  const finalTag = selectedFacetPrefix.value ? `${selectedFacetPrefix.value}:${v}` : v
  showTagModal.value = false
  if (tagModalMode.value === 'bulk') {
    const ids = [...selectedIds.value]
    let successCount = 0
    for (const id of ids) {
      const row = assetList.value.find(a => a.id === id)
      if (!row) continue
      if (!row.tags) row.tags = []
      if (row.tags.includes(finalTag)) continue
      row.tags.push(finalTag)
      try {
        await axios.patch(`${store.API_BASE}/api/v1/assets/${id}/tags`, { tags: row.tags })
        successCount++
      } catch {
        row.tags.splice(row.tags.indexOf(finalTag), 1)
      }
    }
    store.showToast(`✅ 已为 ${successCount} 个素材添加标签「${finalTag}」`)
    selectedIds.value = []
    tagModalItem.value = null
  } else {
    const row = tagModalItem.value
    tagModalItem.value = null
    if (!row) return
    if (!row.tags) row.tags = []
    if (row.tags.includes(finalTag)) {
      store.showToast(`「${finalTag}」已存在`)
      return
    }
    row.tags.push(finalTag)
    try {
      await axios.patch(`${store.API_BASE}/api/v1/assets/${row.id}/tags`, { tags: row.tags })
      store.showToast(`✅ 已追加标签「${finalTag}」`)
    } catch (err) {
      row.tags.splice(row.tags.indexOf(finalTag), 1)
      store.showToast('标签添加失败: ' + (err.response?.data?.detail || err.message))
    }
  }
}

// ── 移入回收站 / 批量 / 彻底销毁：应用内确认（避免 Tauri WebView 下 window.confirm 与业务逻辑竞态） ──
const trashConfirmOpen       = ref(false)
const trashConfirmKind       = ref(null) // 'archive-one' | 'archive-many' | 'purge-one'
const trashConfirmItem       = ref(null)
const trashBulkIdsSnapshot   = ref([])

function openTrashArchiveOne(item) {
  trashConfirmKind.value     = 'archive-one'
  trashConfirmItem.value     = item
  trashBulkIdsSnapshot.value = []
  trashConfirmOpen.value     = true
}

function openTrashArchiveMany() {
  if (!selectedIds.value.length) return
  trashConfirmKind.value     = 'archive-many'
  trashConfirmItem.value     = null
  trashBulkIdsSnapshot.value = [...selectedIds.value]
  trashConfirmOpen.value     = true
}

function openTrashPurgeOne(item) {
  trashConfirmKind.value     = 'purge-one'
  trashConfirmItem.value     = item
  trashBulkIdsSnapshot.value = []
  trashConfirmOpen.value     = true
}

function cancelTrashConfirm() {
  trashConfirmOpen.value     = false
  trashConfirmKind.value     = null
  trashConfirmItem.value     = null
  trashBulkIdsSnapshot.value = []
}

async function confirmTrashAction() {
  const kind = trashConfirmKind.value
  const item = trashConfirmItem.value
  try {
    if (kind === 'archive-one' && item) {
      await axios.patch(`${store.API_BASE}/api/v1/assets/${item.id}/trash`)
      assetList.value   = assetList.value.filter(a => a.id !== item.id)
      selectedIds.value = selectedIds.value.filter(id => id !== item.id)
      store.showToast('✅ 已移入回收站')
    } else if (kind === 'archive-many' && trashBulkIdsSnapshot.value.length) {
      const ids = [...trashBulkIdsSnapshot.value]
      let count = 0
      for (const id of ids) {
        try {
          await axios.patch(`${store.API_BASE}/api/v1/assets/${id}/trash`)
          assetList.value = assetList.value.filter(a => a.id !== id)
          count++
        } catch { /* skip */ }
      }
      selectedIds.value = []
      store.showToast(`✅ 已将 ${count} 个素材移入回收站`)
    } else if (kind === 'purge-one' && item) {
      await axios.delete(`${store.API_BASE}/api/v1/assets/${item.id}/purge`)
      trashedAssets.value = trashedAssets.value.filter(a => a.id !== item.id)
      store.showToast('💀 已永久销毁')
    }
  } catch (err) {
    store.showToast('操作失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    cancelTrashConfirm()
  }
}

// ── 语义对齐雷达 — 基于 facet:tag 生成 DSL 召回定位提示 ──────
function buildAlignmentHints(item, categoryKey) {
  const meta  = ASSET_REGISTRY[categoryKey]
  const hints = []

  // 底模容器专属路径 — 直接展示插槽结构信息
  if (meta.is_container) {
    const slots = item.manifest?.slots ?? []
    if (slots.length > 0) {
      hints.push(`🏛️ SceneMaster 结构轨 — 检测到 ${slots.length} 个动态插槽`)
      for (const s of slots.slice(0, 4)) {
        const coord = s.spatial ? `@(${s.spatial.x},${s.spatial.y} ${s.spatial.w}×${s.spatial.h}%)` : ''
        hints.push(`  └ [${s.slot_key}] ${s.accepts ? '接受: ' + s.accepts : ''} ${coord}`.trim())
      }
      if (slots.length > 4) hints.push(`  └ …及 ${slots.length - 4} 个更多插槽`)
    } else {
      hints.push(`🏛️ SceneMaster 底模已注册 — 建议在 manifest.slots 声明插槽坐标以激活裂变引导`)
    }
    hints.push(`⚡ B端 FFmpeg 压制 / C端伴侣引擎 — 双端复用 → dsl_layer: SceneMaster`)
    return hints
  }

  const facets = parseFacetedTags(item.tags || [])
  for (const group of facets) {
    const vals = group.values.map(v => `#${v.display}`).join('、')
    if (group.theme === 'hook')
      hints.push(`🎯 蓝图解析器将于 Hook 槽位精准召回此素材 (${vals})`)
    else if (group.theme === 'entity')
      hints.push(`🏷 实体标签 ${vals} 将匹配 DSL entity_filter 过滤器`)
    else if (group.theme === 'vibe')
      hints.push(`🌊 Vibe 分面 ${vals} 将驱动情绪轨道混音调度`)
    else if (group.theme === 'layer')
      hints.push(`⚡ ${meta.label}将跟随 ${vals} 自动寻址 ${meta.dsl_layer} 叠加层`)
  }

  if (hints.length === 0) {
    hints.push(
      meta.axis_type.startsWith('X')
        ? `⚠️ 尚无分面标签 — 解析器将退化为随机池泛选，建议打标后再纳入蓝图`
        : `⚠️ 尚无层级标签 — ${meta.label}将无法被 DSL 精准寻址`
    )
  }
  return hints
}

onMounted(fetchAssets)
// 分类切换 → 清空选中 + 重新拉取；viewMode 切换不触发，保留 selectedIds
watch(activeCategory, () => {
  selectedIds.value = []
  fetchAssets()
})

// ── 回收站中台 (Trash Bin Workflow) ──────────────────────────
const isTrashMode   = ref(false)
const trashedAssets = ref([])

async function fetchTrashedAssets() {
  try {
    const resp = await axios.get(`${store.API_BASE}/api/v1/assets?is_deleted=true`)
    trashedAssets.value = Array.isArray(resp.data) ? resp.data : []
  } catch (err) {
    store.showToast('获取回收站失败: ' + err.message)
  }
}
function enterTrashMode() { isTrashMode.value = true; fetchTrashedAssets() }

async function exitTrashMode() {
  isTrashMode.value = false
  await fetchAssets()
}

async function restoreAsset(item) {
  try {
    await axios.patch(`${store.API_BASE}/api/v1/assets/${item.id}/restore`)
    trashedAssets.value = trashedAssets.value.filter(a => a.id !== item.id)
    await fetchAssets()
    store.showToast(`✅ 已恢复「${item.file_path.split(/[/\\]/).pop()}」`)
  } catch (err) {
    store.showToast('恢复失败: ' + (err.response?.data?.detail || err.message))
  }
}
</script>

<template>
  <div class="assets-wrap">

    <!-- ── Header ─────────────────────────────────────────────── -->
    <div class="assets-header">
      <h2 class="assets-title">数字资产管理 (DAM)</h2>
      <div class="assets-header-actions">
        <button class="trash-entry-btn" @click="enterTrashMode" title="查看回收站废弃资产">
          <svg class="trash-entry-icon" viewBox="0 0 16 16" fill="currentColor">
            <path d="M2 3h12v1.5H2V3zm1.5 2h9l-.75 8H4.25L3.5 5zm3.25 2v4h1V7h-1zm2.5 0v4h1V7h-1z"/>
          </svg>
          回收站
        </button>
        <button class="cta-glow-btn" style="padding: 0.5rem 1.25rem; font-size: 0.85rem;" @click="importAssets">➕ 导入本地素材</button>
      </div>
    </div>

    <!-- ── Omni-Search + Untagged Filter + Viewport Toggle ─────── -->
    <div class="search-bar-strip">
      <div class="search-input-wrap">
        <span class="search-icon-glyph">⌕</span>
        <input
          v-model="searchQuery"
          class="omni-search-input"
          placeholder="全局搜索文件名 / 标签 … (以 # 开头精准匹配标签)"
        />
        <button v-if="searchQuery" class="search-clear-btn" @click="searchQuery = ''" title="清除搜索">✕</button>
      </div>
      <div
        :class="['untagged-toggle', filterOnlyUntagged ? 'untagged-toggle--on' : '']"
        @click="filterOnlyUntagged = !filterOnlyUntagged"
        title="仅显示尚未打标的素材"
      >
        <div class="toggle-track"><div class="toggle-knob"></div></div>
        <span class="toggle-label">⚠️ 仅看未打标</span>
      </div>

      <!-- ── 双轨视口切换控件 ── -->
      <div class="view-mode-group" role="group" aria-label="视口模式">
        <button
          :class="['vm-btn', viewMode === 'grid' ? 'vm-btn--active' : '']"
          @click="viewMode = 'grid'"
          title="网格视图"
        >
          <svg class="vm-icon" viewBox="0 0 16 16" fill="currentColor">
            <rect x="1" y="1" width="6" height="6" rx="1"/><rect x="9" y="1" width="6" height="6" rx="1"/>
            <rect x="1" y="9" width="6" height="6" rx="1"/><rect x="9" y="9" width="6" height="6" rx="1"/>
          </svg>
          <span class="vm-label">网格</span>
        </button>
        <button
          :class="['vm-btn', viewMode === 'list' ? 'vm-btn--active' : '']"
          @click="viewMode = 'list'"
          title="列表视图"
        >
          <svg class="vm-icon" viewBox="0 0 16 16" fill="currentColor">
            <rect x="1" y="2" width="14" height="2.5" rx="1"/><rect x="1" y="6.75" width="14" height="2.5" rx="1"/>
            <rect x="1" y="11.5" width="14" height="2.5" rx="1"/>
          </svg>
          <span class="vm-label">列表</span>
        </button>
      </div>
    </div>

    <!-- ── 动态 Tab 导航 (ASSET_REGISTRY SSOT 驱动) ─────────── -->
    <div class="assets-tabs">
      <button
        v-for="(meta, key) in ASSET_REGISTRY"
        :key="key"
        :class="['tab-btn', activeCategory === key ? 'tab-active' : '']"
        :style="activeCategory === key
          ? { '--tab-color': meta.color, borderBottomColor: meta.color, color: meta.color }
          : {}"
        @click="activeCategory = key"
      >
        {{ meta.icon }} {{ meta.label }}
        <span
          class="tab-axis-badge"
          :style="activeCategory === key ? { color: meta.color, borderColor: meta.color, background: `${meta.color}18` } : {}"
        >{{ formatAxisLabel(meta.axis_type) }}轴</span>
      </button>
    </div>

    <!-- ── 统一内容区 (Scrollable Viewport Body) ────────────── -->
    <div class="assets-grid">

      <!-- ══ 回收站中台 ══ -->
      <div v-if="isTrashMode" class="trash-bin-view">
        <div class="trash-header-row">
          <div class="trash-title-block">
            <span class="trash-title-glyph">🗑️</span>
            <span class="trash-title-text">回收站中台</span>
            <span class="trash-count-badge">{{ trashedAssets.length }} 件废弃资产</span>
          </div>
          <button class="trash-exit-btn" @click="exitTrashMode">← 返回资产库</button>
        </div>
        <div v-if="trashedAssets.length === 0" class="trash-empty-state">
          <div class="trash-empty-icon">🧹</div>
          <div class="trash-empty-text">回收站为空 — 未发现废弃资产</div>
        </div>
        <div v-else class="trash-list">
          <div v-for="item in trashedAssets" :key="item.id" class="trash-item">
            <div class="trash-item-icon">{{ ASSET_REGISTRY[item.asset_type]?.icon ?? '📄' }}</div>
            <div class="trash-item-name" :title="item.file_path">{{ item.file_path.split(/[/\\]/).pop() }}</div>
            <div class="trash-item-type">{{ ASSET_REGISTRY[item.asset_type]?.label ?? item.asset_type }}</div>
            <div class="trash-item-tags">
              <span v-for="t in (item.tags || []).slice(0, 4)" :key="t" class="tag-pill facet-generic">{{ t }}</span>
            </div>
            <div class="trash-item-ops">
              <button class="trash-restore-btn" @click="restoreAsset(item)">🔄 恢复资产</button>
              <button type="button" class="trash-purge-btn" @click="openTrashPurgeOne(item)">⚠️ 彻底销毁</button>
            </div>
          </div>
        </div>
      </div>

      <!-- ══ 正常资产视图 ══ -->
      <template v-else>

        <!-- 空状态：无数据 -->
        <div v-if="assetList.length === 0" class="empty-base-state">
          暂无 {{ activeMeta.label }} 素材，请点击右上角导入。
        </div>

        <!-- 空状态：搜索/过滤无结果 -->
        <template v-else-if="filteredAssetList.length === 0">
          <div class="empty-filtered-state">
            <div class="empty-filtered-icon">🎯</div>
            <div class="empty-filtered-text">没有找到匹配的弹药，请调整过滤条件</div>
          </div>
        </template>

        <template v-else>

          <!-- ══ AUDIO 分类 ══ -->
          <template v-if="isAudioCategory">
            <!-- Grid -->
            <div v-if="viewMode === 'grid'" class="assets-card-grid">
              <div
                v-for="item in filteredAssetList"
                :key="item.id"
                class="audio-card-selectable-wrap"
                :class="{ 'audio-card-selected': selectedIds.includes(item.id) }"
              >
                <div class="card-checkbox-wrap" @click.stop="toggleSelect(item.id)">
                  <div :class="['card-checkbox', selectedIds.includes(item.id) ? 'checkbox-checked' : '']">
                    <span v-if="selectedIds.includes(item.id)">✓</span>
                  </div>
                </div>
                <AudioAssetCard :item="item" :api-base="store.API_BASE" @open-tag-modal="openTagModal" />
              </div>
            </div>

            <!-- Data Grid (List Mode) -->
            <div v-else class="dg-table">
              <div class="dg-header">
                <div class="dg-cell dg-col-check">
                  <div :class="['card-checkbox', selectedIds.length > 0 && selectedIds.length === filteredAssetList.length ? 'checkbox-checked' : '']" @click.stop="selectAll" title="全选/取消全选">
                    <span v-if="selectedIds.length > 0 && selectedIds.length === filteredAssetList.length">✓</span>
                  </div>
                </div>
                <div class="dg-cell dg-col-thumb">缩略</div>
                <div class="dg-cell dg-col-name">素材指纹</div>
                <div class="dg-cell dg-col-tags">分面标签墙</div>
                <div class="dg-cell dg-col-usage">消耗</div>
                <div class="dg-cell dg-col-ops"></div>
              </div>
              <div
                v-for="item in filteredAssetList"
                :key="item.id"
                :class="['dg-row', selectedIds.includes(item.id) ? 'dg-row-selected' : '']"
                @click="toggleSelect(item.id)"
              >
                <div class="dg-cell dg-col-check" @click.stop="toggleSelect(item.id)">
                  <div :class="['card-checkbox', selectedIds.includes(item.id) ? 'checkbox-checked' : '']">
                    <span v-if="selectedIds.includes(item.id)">✓</span>
                  </div>
                </div>
                <div class="dg-cell dg-col-thumb" @click.stop>
                  <div class="dg-thumb-wrap">
                    <div class="dg-thumb-audio-icon">{{ activeMeta.icon }}</div>
                  </div>
                </div>
                <div class="dg-cell dg-col-name" @click.stop>
                  <span class="dg-name-text" :title="item.file_path">{{ item.file_path.split(/[/\\]/).pop() }}</span>
                </div>
                <div class="dg-cell dg-col-tags dg-col-tags-pos" @click.stop>
                  <div class="dg-tag-wall">
                    <span
                      v-for="pill in getVisiblePills(item.tags).visible"
                      :key="pill.raw"
                      :class="['tag-pill', `facet-${pill.theme}`]"
                    >{{ pill.display }}<button class="tag-rm-btn" @click.stop="removeTag(item, pill.raw)">×</button></span>
                    <span v-if="!item.tags?.length" class="dg-no-tags">未打标</span>
                    <span v-if="getVisiblePills(item.tags).overflow > 0" class="dg-overflow-badge">+{{ getVisiblePills(item.tags).overflow }}</span>
                    <button class="dg-quick-tag-btn" @click.stop="openTagModal(item)" title="快速打标">＋</button>
                  </div>
                </div>
                <div class="dg-cell dg-col-usage">
                  <span class="dg-usage-count">{{ item.usage_count }}<span class="dg-usage-unit">次</span></span>
                  <div class="dg-health-track">
                    <div class="health-bar" :style="{ width: item.usage_count === 0 ? '100%' : Math.max(5, 100 - item.usage_count * 10) + '%', background: '#4ade80' }"></div>
                  </div>
                </div>
                <div class="dg-cell dg-col-ops" @click.stop>
                  <button type="button" class="dg-op-btn" @click.stop.prevent="openTrashArchiveOne(item)" title="移入回收站">
                    <svg viewBox="0 0 16 16" fill="currentColor" class="dg-op-icon"><path d="M2 3h12v1.5H2V3zm1.5 2h9l-.75 8H4.25L3.5 5zm3.25 2v4h1V7h-1zm2.5 0v4h1V7h-1z"/></svg>
                  </button>
                </div>
              </div>
            </div>
          </template>

          <!-- ══ VISUAL 分类 (video / image / vfx) ══ -->
          <template v-else>
            <!-- Grid -->
            <div v-if="viewMode === 'grid'" class="assets-card-grid">
              <div
                v-for="item in filteredAssetList"
                :key="item.id"
                :class="['asset-card', selectedIds.includes(item.id) ? 'asset-card-selected' : '']"
              >
                <div class="card-checkbox-wrap" @click.stop="toggleSelect(item.id)">
                  <div :class="['card-checkbox', selectedIds.includes(item.id) ? 'checkbox-checked' : '']">
                    <span v-if="selectedIds.includes(item.id)">✓</span>
                  </div>
                </div>

                <div class="asset-thumb">
                  <!-- 9:16 强制比例媒体帧 -->
                  <div class="asset-media-frame">
                    <video
                      v-if="activeCategory === 'video'"
                      :src="store.buildVideoUrl(item.file_path)"
                      controls muted preload="metadata"
                      class="asset-media-el"
                    ></video>
                    <div
                      v-else-if="item.asset_type === 'text_template'"
                      class="text-asset-preview"
                    >{{ item.manifest?.content_matrix?.zh || item.asset_name || '📝 文本资产' }}</div>
                    <img
                      v-else
                      :src="store.buildVideoUrl(item.file_path)"
                      class="asset-media-el"
                    />
                    <!-- ① 引用次数 (左上) -->
                    <span class="badge-ref badge-ref-overlay">引用: {{ item.usage_count }}次</span>
                    <!-- ② DSL 轴类型角标 (右上) -->
                    <div :class="['axis-badge', activeMeta.axis_type.startsWith('X') ? 'axis-badge-x' : 'axis-badge-y']">
                      {{ activeMeta.axis_type === 'X' ? 'X轴主轨' : activeMeta.axis_type === 'X_STRUCTURE' ? 'X轴结构' : 'Y轴叠加层' }}
                    </div>
                    <!-- ③ 场景底模：动态插槽虚线框叠加层 -->
                    <div
                      v-if="isContainerCategory && (item.manifest?.slots?.length ?? 0) > 0"
                      class="slot-overlays"
                    >
                      <div
                        v-for="slot in item.manifest.slots"
                        :key="slot.slot_key"
                        class="slot-box"
                        :style="{
                          left:   (slot.spatial?.x ?? 5)  + '%',
                          top:    (slot.spatial?.y ?? 10) + '%',
                          width:  (slot.spatial?.w ?? 90) + '%',
                          height: (slot.spatial?.h ?? 20) + '%',
                        }"
                      >
                        <span class="slot-label-badge">插槽: {{ slot.slot_key }}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="asset-info">
                  <div class="asset-name" :title="item.file_path">{{ item.file_path.split(/[/\\]/).pop() }}</div>
                  <div class="asset-health" title="健康度 (疲劳度)">
                    <div class="health-bar" :style="{
                      width: item.is_exhausted ? '100%' : (item.usage_count === 0 ? '100%' : Math.max(10, 100 - item.usage_count * 10) + '%'),
                      background: item.is_exhausted ? '#f87171' : (item.usage_count === 0 ? '#4ade80' : '#fbbf24')
                    }"></div>
                  </div>
                  <!-- 场景底模插槽汇总徽章 -->
                  <div v-if="isContainerCategory" class="asset-slot-summary">
                    <span class="slot-count-badge">
                      🔲 {{ item.manifest?.slots?.length ?? 0 }} 个动态插槽
                      <span v-if="(item.manifest?.slots?.length ?? 0) === 0" class="slot-hint-dim">— 尚未声明</span>
                    </span>
                  </div>

                  <div class="facet-tag-matrix">
                    <template v-for="group in parseFacetedTags(item.tags || [])" :key="group.key">
                      <div :class="['facet-group', group.label ? 'facet-group--labeled' : '']">
                        <span v-if="group.label" :class="['facet-label', `facet-label-${group.theme}`]">{{ group.icon }} {{ group.label }}</span>
                        <span
                          v-for="v in group.values"
                          :key="v.raw"
                          :class="['tag-pill', `facet-${group.theme}`]"
                        >{{ v.display }}<button class="tag-rm-btn" @click.stop="removeTag(item, v.raw)" title="移除">×</button></span>
                      </div>
                    </template>
                    <span v-if="item.is_exhausted" class="tag-pill tag-pill-danger">疲劳警告</span>
                    <span v-else-if="item.usage_count === 0" class="tag-pill tag-pill-fresh">全新</span>
                    <button type="button" class="quick-tag-btn" @click.stop="openTagModal(item)">＋ 快速打标</button>
                  </div>

                  <!-- 语义对齐雷达 -->
                  <div class="alignment-radar">
                    <div class="radar-header">
                      <svg class="radar-icon" viewBox="0 0 12 12" fill="none" stroke="currentColor">
                        <circle cx="6" cy="6" r="4.5" stroke-width="1"/>
                        <circle cx="6" cy="6" r="2.5" stroke-width="0.8" stroke-opacity="0.5"/>
                        <circle cx="6" cy="6" r="1" fill="currentColor" stroke="none" opacity="0.9"/>
                        <line x1="6" y1="1.5" x2="6" y2="10.5" stroke-width="0.5" stroke-opacity="0.35"/>
                        <line x1="1.5" y1="6" x2="10.5" y2="6" stroke-width="0.5" stroke-opacity="0.35"/>
                      </svg>
                      <span class="radar-title">DSL 召回定位</span>
                      <span class="radar-layer-chip">{{ activeMeta.dsl_layer }}</span>
                    </div>
                    <div
                      v-for="(hint, i) in buildAlignmentHints(item, activeCategory)"
                      :key="i"
                      class="radar-hint"
                    >{{ hint }}</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Data Grid (List Mode) -->
            <div v-else class="dg-table">
              <div class="dg-header" :style="dgVisualGridStyle">
                <div class="dg-cell dg-col-check">
                  <div :class="['card-checkbox', selectedIds.length > 0 && selectedIds.length === filteredAssetList.length ? 'checkbox-checked' : '']" @click.stop="selectAll" title="全选/取消全选">
                    <span v-if="selectedIds.length > 0 && selectedIds.length === filteredAssetList.length">✓</span>
                  </div>
                </div>
                <div class="dg-cell dg-col-thumb">缩略</div>
                <div class="dg-cell dg-col-name">素材指纹</div>
                <div v-if="isContainerCategory" class="dg-cell dg-col-slots">预留插槽</div>
                <div class="dg-cell dg-col-tags">分面标签墙</div>
                <div class="dg-cell dg-col-usage">消耗</div>
                <div class="dg-cell dg-col-ops"></div>
              </div>
              <div
                v-for="item in filteredAssetList"
                :key="item.id"
                :class="[
                  'dg-row',
                  selectedIds.includes(item.id) ? 'dg-row-selected'  : '',
                  item.is_exhausted ? 'dg-row-exhausted' : '',
                ]"
                :style="dgVisualGridStyle"
                @click="toggleSelect(item.id)"
              >
                <!-- ① 复选框 -->
                <div class="dg-cell dg-col-check" @click.stop="toggleSelect(item.id)">
                  <div :class="['card-checkbox', selectedIds.includes(item.id) ? 'checkbox-checked' : '']">
                    <span v-if="selectedIds.includes(item.id)">✓</span>
                  </div>
                </div>

                <!-- ② 1:1 微缩动态缩略图 (hover → 浮层预览) -->
                <div
                  class="dg-cell dg-col-thumb"
                  @mouseenter="showPreview(item, $event)"
                  @mouseleave="hidePreview"
                  @click.stop
                >
                  <div class="dg-thumb-wrap">
                    <video
                      v-if="activeCategory === 'video'"
                      :src="store.buildVideoUrl(item.file_path)"
                      muted preload="metadata"
                      class="dg-thumb-media"
                    ></video>
                    <div
                      v-else-if="item.asset_type === 'text_template'"
                      class="text-asset-preview text-asset-preview--thumb"
                    >{{ item.manifest?.content_matrix?.zh || item.asset_name || '📝' }}</div>
                    <img
                      v-else
                      :src="store.buildVideoUrl(item.file_path)"
                      class="dg-thumb-media"
                    />
                  </div>
                </div>

                <!-- ③ 素材指纹 / 物理名称 -->
                <div class="dg-cell dg-col-name" @click.stop>
                  <span class="dg-name-text" :title="item.file_path">{{ item.file_path.split(/[/\\]/).pop() }}</span>
                </div>

                <!-- ③.5 插槽数格 (仅 scene_master 分类) -->
                <div v-if="isContainerCategory" class="dg-cell dg-col-slots" @click.stop>
                  <span class="dg-slot-count">{{ item.manifest?.slots?.length ?? 0 }}</span>
                  <span class="dg-slot-unit">槽</span>
                </div>

                <!-- ④ 分面标签墙 -->
                <div class="dg-cell dg-col-tags dg-col-tags-pos" @click.stop>
                  <div class="dg-tag-wall">
                    <span
                      v-for="pill in getVisiblePills(item.tags).visible"
                      :key="pill.raw"
                      :class="['tag-pill', `facet-${pill.theme}`]"
                    >{{ pill.display }}<button class="tag-rm-btn" @click.stop="removeTag(item, pill.raw)">×</button></span>
                    <span v-if="item.is_exhausted" class="tag-pill tag-pill-danger">疲劳</span>
                    <span v-if="!item.tags?.length && !item.is_exhausted" class="dg-no-tags">未打标</span>
                    <span v-if="getVisiblePills(item.tags).overflow > 0" class="dg-overflow-badge">+{{ getVisiblePills(item.tags).overflow }}</span>
                    <button class="dg-quick-tag-btn" @click.stop="openTagModal(item)" title="快速打标">＋</button>
                  </div>
                </div>

                <!-- ⑤ 消耗次数 + 耗损进度条 -->
                <div class="dg-cell dg-col-usage">
                  <span class="dg-usage-count">{{ item.usage_count }}<span class="dg-usage-unit">次</span></span>
                  <div class="dg-health-track">
                    <div class="health-bar" :style="{
                      width: item.is_exhausted ? '100%' : (item.usage_count === 0 ? '100%' : Math.max(5, 100 - item.usage_count * 10) + '%'),
                      background: item.is_exhausted ? '#f87171' : (item.usage_count === 0 ? '#4ade80' : '#fbbf24')
                    }"></div>
                  </div>
                </div>

                <!-- ⑥ 快捷操作 -->
                <div class="dg-cell dg-col-ops" @click.stop>
                  <button type="button" class="dg-op-btn" @click.stop.prevent="openTrashArchiveOne(item)" title="移入回收站">
                    <svg viewBox="0 0 16 16" fill="currentColor" class="dg-op-icon"><path d="M2 3h12v1.5H2V3zm1.5 2h9l-.75 8H4.25L3.5 5zm3.25 2v4h1V7h-1zm2.5 0v4h1V7h-1z"/></svg>
                  </button>
                </div>
              </div>
            </div>
          </template>

        </template>

      </template>

    </div>

    <!-- ── 战术操作条 (Floating Action Bar) ──────────────────── -->
    <Transition name="fab-slide">
      <div v-if="selectedIds.length > 0" class="floating-action-bar">
        <div class="fab-status">
          <span class="fab-dot"></span>
          <span class="fab-count">已选定 <strong>{{ selectedIds.length }}</strong> 项资产</span>
        </div>
        <div class="fab-sep"></div>
        <button class="fab-btn fab-btn-all" @click="selectAll">
          {{ selectedIds.length === filteredAssetList.length ? '↩ 取消全选' : '☑ 全选当前视图' }}
        </button>
        <button class="fab-btn fab-btn-tag" @click="bulkAddTag">＋ 批量分类打标</button>
        <button type="button" class="fab-btn fab-btn-danger" @click.prevent.stop="openTrashArchiveMany">🗑 一键移入回收站</button>
        <button class="fab-btn fab-btn-cancel" @click="selectedIds = []">✕ 取消</button>
      </div>
    </Transition>

    <!-- ── 毫秒级浮窗速览 (固定层，pointer-events: none) ─────── -->
    <Transition name="preview-fade">
      <div
        v-if="hoverPreview"
        class="hover-preview-layer"
        :style="{ left: hoverPreview.x + 'px', top: hoverPreview.y + 'px' }"
      >
        <video
          v-if="hoverPreview.isVideo"
          :src="hoverPreview.src"
          autoplay muted loop playsinline
          class="preview-media"
        ></video>
        <img v-else :src="hoverPreview.src" class="preview-media" />
        <div class="preview-category-badge">{{ activeMeta.icon }} {{ activeMeta.label }}</div>

        <!-- 场景底模插槽坐标虚线框叠加层 -->
        <div
          v-if="hoverPreview.isSceneMaster && hoverPreview.slots.length > 0"
          class="slot-overlays"
        >
          <div
            v-for="slot in hoverPreview.slots"
            :key="slot.slot_key"
            class="slot-box"
            :style="{
              left:   (slot.spatial?.x ?? 5)  + '%',
              top:    (slot.spatial?.y ?? 10) + '%',
              width:  (slot.spatial?.w ?? 90) + '%',
              height: (slot.spatial?.h ?? 20) + '%',
            }"
          >
            <span class="slot-label-badge">插槽: {{ slot.slot_key }}</span>
          </div>
        </div>
        <!-- 无插槽清单时的场景底模提示 -->
        <div v-else-if="hoverPreview.isSceneMaster" class="preview-no-slots-hint">
          🏛️ 底模 · 无插槽清单
        </div>
      </div>
    </Transition>

    <!-- ── 分面打标 Modal（批量 / 单条统一）────────────────────── -->
    <Transition name="modal-fade">
      <div v-if="showTagModal" class="modal-overlay cpm-overlay" @click.self="cancelTagModal">
        <div class="modal-box cpm-box">
          <div class="cpm-header">
            <span class="cpm-icon">🏷</span>
            <span class="cpm-title">标签注入 · 战术打标</span>
          </div>
          <div class="cpm-body">
            <p v-if="tagModalMode === 'bulk'" class="cpm-desc">
              将向已选中的 <strong>{{ selectedIds.length }}</strong> 项资产写入同一标签；左侧选定维度后，由系统自动拼接命名空间与冒号。
            </p>
            <p v-else class="cpm-desc">
              为「{{ tagModalItem?.file_path?.split(/[/\\]/).pop() }}」追加标签。
            </p>
            <div class="cpm-input-group">
              <select v-model="selectedFacetPrefix" class="cpm-facet-select">
                <option
                  v-for="prefix in ASSET_REGISTRY[tagTargetType]?.facet_prefix ?? []"
                  :key="prefix"
                  :value="prefix"
                >{{ FACET_NAMESPACES.find(f => f.value === prefix)?.label || prefix }}</option>
              </select>
              <input
                v-model="tagValue"
                class="cpm-input cpm-input--grow"
                type="text"
                placeholder="输入具体标签词…"
                @keyup.enter="confirmTagModal"
                @keyup.escape="cancelTagModal"
                autofocus
              />
            </div>
          </div>
          <div class="cpm-actions">
            <button class="cpm-cancel-btn" @click="cancelTagModal">取消</button>
            <button
              class="cpm-confirm-btn"
              :disabled="!tagValue.trim()"
              @click="confirmTagModal"
            >确认注入</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- ── 回收站 / 批量删除 / 彻底销毁：应用内确认（Tauri 下替代 window.confirm） ── -->
    <Transition name="modal-fade">
      <div
        v-if="trashConfirmOpen"
        class="modal-overlay cpm-overlay"
        @click.self="cancelTrashConfirm"
      >
        <div class="modal-box cpm-box" role="alertdialog" aria-modal="true">
          <div class="cpm-header">
            <span class="cpm-icon">{{ trashConfirmKind === 'purge-one' ? '⚠️' : '🗑' }}</span>
            <span class="cpm-title">{{ trashConfirmKind === 'purge-one' ? '彻底销毁确认' : '移入回收站确认' }}</span>
          </div>
          <div class="cpm-body">
            <p v-if="trashConfirmKind === 'archive-one' && trashConfirmItem" class="cpm-desc">
              确认将「{{ trashConfirmItem.file_path.split(/[/\\]/).pop() }}」移入回收站？
            </p>
            <p v-else-if="trashConfirmKind === 'archive-many'" class="cpm-desc">
              确认将 {{ trashBulkIdsSnapshot.length }} 个素材移入回收站？
            </p>
            <p v-else-if="trashConfirmKind === 'purge-one' && trashConfirmItem" class="cpm-desc">
              彻底销毁「{{ trashConfirmItem.file_path.split(/[/\\]/).pop() }}」？此操作不可逆，数据库记录将被移除。
            </p>
          </div>
          <div class="cpm-actions">
            <button type="button" class="cpm-cancel-btn" @click="cancelTrashConfirm">取消</button>
            <button
              type="button"
              :class="['cpm-confirm-btn', trashConfirmKind === 'purge-one' ? 'cpm-confirm-btn--danger' : '']"
              @click="confirmTrashAction"
            >{{ trashConfirmKind === 'purge-one' ? '永久销毁' : '确认移入回收站' }}</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- ── Universal Import & Tag Modal ─────────────────────── -->
    <Transition name="modal-fade">
      <div v-if="showImportModal" class="modal-overlay" @click.self="showImportModal = false">
        <div class="modal-box">

          <div class="modal-header">
            <span class="modal-icon">{{ activeMeta.icon }}</span>
            <div>
              <div class="modal-title">确认导入 &amp; 批量打标</div>
              <div class="modal-sub">
                <template v-if="isAudioCategory">DopaMatrix 引擎强制要求，所有听觉资产必须绑定情绪标签才能参与混音调度</template>
                <template v-else>可选：为本批素材预设父级标签，导入后可继续单独编辑</template>
              </div>
            </div>
          </div>

          <div class="modal-files">
            <div class="modal-files-label">
              待导入文件
              <span class="modal-files-count">{{ pendingImportFiles.length }} 个</span>
            </div>
            <div class="modal-file-list">
              <div v-for="(f, i) in pendingImportFiles" :key="i" class="modal-file-item">
                {{ activeMeta.icon }} {{ f.split(/[/\\]/).pop() }}
              </div>
            </div>
          </div>

          <!-- AUDIO: emotion pills -->
          <div v-if="isAudioCategory" class="modal-field">
            <label class="modal-label">选择情绪标签 <span class="modal-required">* 必填</span></label>
            <div class="modal-emotion-pills">
              <button
                v-for="opt in [
                  { value: 'asmr',    label: '🎧 ASMR / 沉浸解压' },
                  { value: 'epic',    label: '💥 史诗震撼 / 强节奏' },
                  { value: 'funny',   label: '🤪 荒诞鬼畜 / 模因音效' },
                  { value: 'general', label: '🎵 通用音乐 (General)' },
                ]"
                :key="opt.value"
                :class="['emotion-pill', pendingEmotionTag === opt.value ? 'emotion-pill--active' : '']"
                @click="pendingEmotionTag = opt.value"
              >{{ opt.label }}</button>
            </div>
          </div>

          <!-- NON-AUDIO: 分面打标工作台 -->
          <div v-else class="modal-field">
            <div class="bucket-field-header">
              <span class="modal-label">分面打标工作台</span>
              <span class="modal-optional">可选 · 录入即自动追加命名空间前缀</span>
            </div>

            <div class="facet-buckets-grid">
              <div
                v-for="bucket in FACET_BUCKETS"
                :key="bucket.key"
                :class="['facet-bucket', `facet-bucket-${bucket.theme}`]"
              >
                <!-- 桶标题 -->
                <div class="bucket-head">
                  <span class="bucket-icon">{{ bucket.icon }}</span>
                  <span class="bucket-label">{{ bucket.label }}</span>
                  <span v-if="pendingFacetBuckets[bucket.key].length > 0" class="bucket-count">
                    {{ pendingFacetBuckets[bucket.key].length }}
                  </span>
                </div>

                <!-- 已选标签积木 -->
                <div v-if="pendingFacetBuckets[bucket.key].length > 0" class="bucket-selected">
                  <span
                    v-for="tag in pendingFacetBuckets[bucket.key]"
                    :key="tag"
                    :class="['tag-pill', `facet-${bucket.theme}`]"
                  >
                    {{ tag.includes(':') ? tag.split(':').slice(1).join(':') : tag }}
                    <button class="tag-rm-btn" @click="removeFromBucket(bucket.key, tag)" title="移除">×</button>
                  </span>
                </div>

                <!-- 输入行 -->
                <div class="bucket-input-row">
                  <input
                    v-model="bucketInputs[bucket.key]"
                    @keyup.enter="addBucketInput(bucket.key)"
                    :placeholder="bucket.ph"
                    :class="['bucket-input', `bucket-input-${bucket.theme}`]"
                    maxlength="40"
                  />
                  <button class="bucket-add-btn" @click="addBucketInput(bucket.key)" title="添加">＋</button>
                </div>

                <!-- 词云候选积木 -->
                <div v-if="bucketClouds[bucket.key] && bucketClouds[bucket.key].length > 0" class="bucket-cloud">
                  <button
                    v-for="item in bucketClouds[bucket.key]"
                    :key="item.raw"
                    :class="[
                      'cloud-chip',
                      `cloud-chip-${bucket.theme}`,
                      pendingFacetBuckets[bucket.key].includes(item.raw) ? 'cloud-chip--active' : '',
                    ]"
                    @click="injectCloudTag(bucket.key, item.raw)"
                    :title="`注入: ${item.raw}`"
                  >{{ item.display }}</button>
                </div>
                <div v-else class="bucket-cloud-empty">暂无历史词云，直接录入后将自动积累</div>
              </div>
            </div>

            <div v-if="allPendingTags.length === 0" class="batch-tag-hint">
              直接在打标桶内录入，或从词云一键注入；不添加也可直接导入
            </div>
          </div>

          <div class="modal-actions">
            <button class="modal-cancel-btn" @click="showImportModal = false">取消</button>
            <button
              class="modal-confirm-btn"
              :class="{ 'modal-confirm-btn--disabled': isAudioCategory && !pendingEmotionTag }"
              :disabled="isAudioCategory && !pendingEmotionTag"
              @click="confirmImport"
            >
              <template v-if="isAudioCategory && !pendingEmotionTag">请先选择情绪标签</template>
              <template v-else-if="allPendingTags.length > 0">✅ 导入并打标 ({{ allPendingTags.length }} 个标签)</template>
              <template v-else>✅ 确认导入</template>
            </button>
          </div>

        </div>
      </div>
    </Transition>

    <!-- ── 文本资产多语种创建弹窗 ───────────────────────────────── -->
    <Transition name="modal-fade">
      <div v-if="showTextModal" class="modal-overlay cpm-overlay" @click.self="showTextModal = false">
        <div class="modal-box cpm-box text-modal-box">
          <div class="cpm-header">
            <span class="cpm-icon">📝</span>
            <span class="cpm-title">文本动态资产 · 多语种创建</span>
          </div>
          <div class="cpm-body">
            <p class="cpm-desc">虚拟创建一个 <code>text_template</code> 资产，无需物理文件；多语种内容将写入 DAM。</p>
            <div class="text-modal-field">
              <label class="text-modal-label">资产名称 <span class="modal-required">* 必填</span></label>
              <input
                v-model="textForm.asset_name"
                class="text-modal-input"
                placeholder="如：主推文案 · 双十一版"
                maxlength="120"
              />
            </div>
            <div class="text-modal-field">
              <label class="text-modal-label">🇨🇳 ZH 中文内容</label>
              <textarea
                v-model="textForm.zh"
                class="text-modal-textarea"
                rows="3"
                placeholder="输入中文版本文案..."
              ></textarea>
            </div>
            <div class="text-modal-field">
              <label class="text-modal-label">🇬🇧 EN 英语内容</label>
              <textarea
                v-model="textForm.en"
                class="text-modal-textarea"
                rows="3"
                placeholder="Enter English copy..."
              ></textarea>
            </div>
            <div class="text-modal-field">
              <label class="text-modal-label">🇸🇦 AR 阿语内容</label>
              <textarea
                v-model="textForm.ar"
                class="text-modal-textarea text-modal-textarea--rtl"
                rows="3"
                placeholder="أدخل النص العربي..."
                dir="rtl"
              ></textarea>
            </div>
          </div>
          <div class="cpm-actions">
            <button type="button" class="cpm-cancel-btn" @click="showTextModal = false">取消</button>
            <button type="button" class="cpm-confirm-btn" @click="submitTextAsset">✅ 确认创建</button>
          </div>
        </div>
      </div>
    </Transition>

  </div>
</template>

<style scoped>
/* ── Tag controls ─────────────────────────────────────────────── */
.asset-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
}
.tag-rm-btn {
  background: none;
  border: none;
  color: #64748b;
  margin-left: 0.2rem;
  line-height: 1;
  cursor: pointer;
  padding: 0;
  font-size: 0.8rem;
  transition: color 0.15s;
}
.tag-rm-btn:hover { color: #ef4444; }
.tag-input {
  background: rgba(15, 23, 42, 0.4);
  border: none;
  outline: none;
  font-size: 0.65rem;
  color: #cbd5e1;
  width: 90px;
  border-radius: 4px;
  padding: 0.15rem 0.35rem;
  transition: background 0.2s, box-shadow 0.2s;
}
.tag-input::placeholder { color: #475569; }
.tag-input:focus {
  background: rgba(30, 41, 59, 0.8);
  box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.4);
}

/* ── Omni-Search Strip ─────────────────────────────────────────── */
.search-bar-strip {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.55rem 0.8rem;
  background: rgba(2, 8, 23, 0.55);
  border: 1px solid rgba(56, 189, 248, 0.1);
  border-radius: 10px;
  backdrop-filter: blur(8px);
}
.search-input-wrap {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
}
.search-icon-glyph {
  position: absolute;
  left: 0.6rem;
  font-size: 1.1rem;
  color: #475569;
  pointer-events: none;
  line-height: 1;
  top: 50%;
  transform: translateY(-50%);
}
.omni-search-input {
  width: 100%;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(56, 189, 248, 0.15);
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 0.82rem;
  font-family: 'Inter', sans-serif;
  padding: 0.4rem 2rem 0.4rem 2.1rem;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.omni-search-input::placeholder { color: #475569; }
.omni-search-input:focus {
  border-color: rgba(56, 189, 248, 0.5);
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.08);
}
.search-clear-btn {
  position: absolute;
  right: 0.5rem;
  background: none;
  border: none;
  color: #64748b;
  font-size: 0.75rem;
  cursor: pointer;
  padding: 0.1rem 0.3rem;
  border-radius: 4px;
  line-height: 1;
  transition: color 0.15s, background 0.15s;
}
.search-clear-btn:hover { color: #e2e8f0; background: rgba(255,255,255,0.06); }

/* ── Untagged Toggle ──────────────────────────────────────────── */
.untagged-toggle {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  cursor: pointer;
  user-select: none;
  padding: 0.3rem 0.6rem;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  transition: background 0.2s, border-color 0.2s;
  white-space: nowrap;
}
.untagged-toggle:hover { background: rgba(255,255,255,0.04); }
.untagged-toggle--on {
  background: rgba(251, 191, 36, 0.08);
  border-color: rgba(251, 191, 36, 0.3);
}
.toggle-track {
  width: 28px;
  height: 15px;
  border-radius: 99px;
  background: rgba(100, 116, 139, 0.3);
  border: 1px solid rgba(255,255,255,0.1);
  position: relative;
  transition: background 0.2s;
  flex-shrink: 0;
}
.untagged-toggle--on .toggle-track {
  background: rgba(251, 191, 36, 0.35);
  border-color: rgba(251, 191, 36, 0.5);
}
.toggle-knob {
  position: absolute;
  top: 1px;
  left: 1px;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: #64748b;
  transition: transform 0.2s, background 0.2s;
}
.untagged-toggle--on .toggle-knob { transform: translateX(13px); background: #fbbf24; }
.toggle-label {
  font-size: 0.75rem;
  color: #94a3b8;
  font-weight: 500;
  transition: color 0.2s;
}
.untagged-toggle--on .toggle-label { color: #fbbf24; }

/* ── 双轨视口切换控件 ────────────────────────────────────────── */
.view-mode-group {
  display: flex;
  align-items: center;
  gap: 2px;
  background: rgba(2, 8, 23, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 2px;
  flex-shrink: 0;
}
.vm-btn {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.28rem 0.65rem;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #475569;
  font-size: 0.72rem;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  letter-spacing: 0.02em;
  transition: background 0.15s, color 0.15s, box-shadow 0.15s;
  white-space: nowrap;
}
.vm-btn:hover { color: #94a3b8; background: rgba(255,255,255,0.04); }
.vm-btn--active {
  background: rgba(56, 189, 248, 0.12);
  color: #38bdf8;
  box-shadow: 0 0 10px rgba(56, 189, 248, 0.15);
}
.vm-btn--active:hover { background: rgba(56, 189, 248, 0.18); }
.vm-icon {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}
.vm-label { line-height: 1; }

/* ── 动态 Tab 导航 ────────────────────────────────────────────── */
.assets-tabs {
  display: flex;
  gap: 0.25rem;
  padding-bottom: 2px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.tab-btn {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 0.9rem;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: #64748b;
  font-size: 0.82rem;
  font-weight: 500;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  border-radius: 6px 6px 0 0;
  transition: color 0.18s, border-color 0.18s, background 0.18s;
  white-space: nowrap;
  margin-bottom: -2px;
}
.tab-btn:hover {
  color: #94a3b8;
  background: rgba(255,255,255,0.04);
}
.tab-active {
  font-weight: 600;
  /* border-bottom-color and color driven by inline :style + --tab-color */
  text-shadow: 0 0 12px var(--tab-color, rgba(56,189,248,0.4));
}
.tab-axis-badge {
  font-size: 0.6rem;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  padding: 0.08rem 0.35rem;
  border-radius: 99px;
  border: 1px solid rgba(255,255,255,0.1);
  color: #475569;
  background: rgba(255,255,255,0.04);
  letter-spacing: 0.03em;
  transition: color 0.18s, border-color 0.18s, background 0.18s;
}

/* ── Card checkbox ────────────────────────────────────────────── */
.asset-card { position: relative; }
.card-checkbox-wrap {
  position: absolute;
  top: 0.45rem;
  left: 0.45rem;
  z-index: 10;
  opacity: 0;
  transition: opacity 0.15s;
}
.asset-card:hover .card-checkbox-wrap,
.asset-card-selected .card-checkbox-wrap { opacity: 1; }
.card-checkbox {
  width: 18px;
  height: 18px;
  border-radius: 5px;
  border: 1.5px solid rgba(139, 92, 246, 0.5);
  background: rgba(2, 8, 23, 0.75);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 0.7rem;
  color: #fff;
  transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
}
.card-checkbox:hover { border-color: rgba(139, 92, 246, 0.9); }
.checkbox-checked {
  background: rgba(139, 92, 246, 0.85);
  border-color: #a78bfa;
  box-shadow: 0 0 8px rgba(139, 92, 246, 0.5);
}
.asset-card-selected {
  border-color: rgba(139, 92, 246, 0.6) !important;
  box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.25), 0 8px 20px rgba(0,0,0,0.4) !important;
}

/* ── Audio card selectable wrapper ───────────────────────────── */
.audio-card-selectable-wrap {
  position: relative;
  border-radius: 12px;
  border: 1px solid transparent;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.audio-card-selectable-wrap .card-checkbox-wrap { opacity: 0; z-index: 20; }
.audio-card-selectable-wrap:hover .card-checkbox-wrap,
.audio-card-selected .card-checkbox-wrap { opacity: 1; }
.audio-card-selected {
  border-color: rgba(139, 92, 246, 0.5) !important;
  box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.2) !important;
}

/* ── 列表视图 ─────────────────────────────────────────────────── */
.assets-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding-top: 0.5rem;
}
.asset-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.45rem 0.75rem;
  background: rgba(2, 8, 23, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
  min-height: 52px;
}
.asset-row:hover {
  background: rgba(15, 23, 42, 0.65);
  border-color: rgba(255, 255, 255, 0.09);
}
.asset-row-selected {
  border-color: rgba(139, 92, 246, 0.45) !important;
  background: rgba(139, 92, 246, 0.05) !important;
  box-shadow: 0 0 0 1px rgba(139, 92, 246, 0.15);
}
.asset-row-hook {
  border-color: rgba(251, 191, 36, 0.3) !important;
  background: rgba(251, 191, 36, 0.04) !important;
}
.row-check {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}
.row-thumb {
  flex-shrink: 0;
  width: 64px;
  height: 40px;
  border-radius: 5px;
  overflow: hidden;
  background: rgba(0,0,0,0.35);
  display: flex;
  align-items: center;
  justify-content: center;
}
.row-thumb-media {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.row-thumb-audio {
  font-size: 1.5rem;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255,255,255,0.06);
}
.row-name {
  flex: 1;
  min-width: 0;
  font-size: 0.78rem;
  font-weight: 500;
  color: #cbd5e1;
  font-family: 'JetBrains Mono', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.row-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
  flex: 1;
  min-width: 0;
}
.row-role {
  flex-shrink: 0;
}
.row-meta {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.3rem;
}
.row-health {
  width: 56px;
  height: 4px;
  background: rgba(255,255,255,0.06);
  border-radius: 99px;
  overflow: hidden;
}
.row-health .health-bar {
  height: 100%;
  border-radius: 99px;
  transition: width 0.4s;
}

/* ── Empty states ─────────────────────────────────────────────── */
.empty-base-state {
  color: #64748b;
  font-size: 0.85rem;
  padding: 1rem;
}
.empty-filtered-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 3rem 1rem;
  text-align: center;
}
.empty-filtered-icon { font-size: 2.5rem; opacity: 0.5; }
.empty-filtered-text {
  color: #475569;
  font-size: 0.88rem;
  font-weight: 500;
  letter-spacing: 0.01em;
}

/* ── Floating Action Bar ──────────────────────────────────────── */
.floating-action-bar {
  position: fixed;
  bottom: 1.5rem;
  left: 50%;
  transform: translateX(-50%);
  z-index: 500;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 1.1rem;
  background: rgba(15, 5, 35, 0.82);
  border: 1px solid rgba(139, 92, 246, 0.45);
  border-radius: 99px;
  backdrop-filter: blur(16px);
  box-shadow: 0 0 30px rgba(139, 92, 246, 0.3), 0 8px 32px rgba(0,0,0,0.6);
  white-space: nowrap;
}
.fab-count { font-size: 0.8rem; color: #c4b5fd; font-weight: 500; padding: 0 0.3rem; }
.fab-count strong { color: #e9d5ff; font-weight: 700; }
.fab-sep { width: 1px; height: 18px; background: rgba(139, 92, 246, 0.3); margin: 0 0.1rem; }
.fab-btn {
  border: none;
  border-radius: 99px;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 0.35rem 0.85rem;
  cursor: pointer;
  transition: all 0.18s;
  font-family: 'Inter', sans-serif;
}
.fab-btn-all {
  background: rgba(56, 189, 248, 0.1);
  color: #7dd3fc;
  border: 1px solid rgba(56, 189, 248, 0.25);
}
.fab-btn-all:hover { background: rgba(56, 189, 248, 0.2); border-color: rgba(56, 189, 248, 0.5); }
.fab-btn-tag {
  background: linear-gradient(135deg, rgba(139,92,246,0.35), rgba(99,102,241,0.35));
  color: #e9d5ff;
  border: 1px solid rgba(139, 92, 246, 0.5);
  box-shadow: 0 0 12px rgba(139, 92, 246, 0.2);
}
.fab-btn-tag:hover {
  background: linear-gradient(135deg, rgba(139,92,246,0.55), rgba(99,102,241,0.55));
  box-shadow: 0 0 18px rgba(139, 92, 246, 0.4);
}
.fab-btn-cancel {
  background: rgba(239, 68, 68, 0.08);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.2);
}
.fab-btn-cancel:hover { background: rgba(239, 68, 68, 0.18); border-color: rgba(239, 68, 68, 0.45); }

.fab-slide-enter-active { transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1); }
.fab-slide-leave-active { transition: all 0.18s ease; }
.fab-slide-enter-from, .fab-slide-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(20px) scale(0.9);
}

/* ── Modal ────────────────────────────────────────────────────── */
.modal-files-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
  background: rgba(139, 92, 246, 0.15);
  color: #c4b5fd;
  border: 1px solid rgba(139, 92, 246, 0.3);
  border-radius: 99px;
  padding: 0.05rem 0.5rem;
  margin-left: 0.4rem;
}
.modal-optional {
  font-size: 0.68rem;
  color: #475569;
  font-weight: 400;
  margin-left: 0.35rem;
  font-style: italic;
}

/* ── Batch tag input ──────────────────────────────────────────── */
.batch-tag-input-wrap { display: flex; gap: 0.45rem; align-items: center; }
.batch-tag-input {
  flex: 1;
  background: rgba(2, 8, 23, 0.7);
  border: 1px solid rgba(139, 92, 246, 0.25);
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 0.82rem;
  font-family: 'Inter', sans-serif;
  padding: 0.42rem 0.75rem;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.batch-tag-input::placeholder { color: #475569; }
.batch-tag-input:focus {
  border-color: rgba(139, 92, 246, 0.6);
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.1);
}
.batch-tag-add-btn {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid rgba(139, 92, 246, 0.35);
  background: rgba(139, 92, 246, 0.12);
  color: #c4b5fd;
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, border-color 0.15s;
  flex-shrink: 0;
}
.batch-tag-add-btn:hover { background: rgba(139, 92, 246, 0.25); border-color: rgba(139, 92, 246, 0.6); }
.batch-tag-pills { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.6rem; }
.batch-tag-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: rgba(139, 92, 246, 0.14);
  border: 1px solid rgba(139, 92, 246, 0.35);
  color: #c4b5fd;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 0.2rem 0.55rem;
  border-radius: 99px;
  font-family: 'JetBrains Mono', monospace;
  transition: background 0.15s;
}
.batch-tag-pill:hover { background: rgba(139, 92, 246, 0.22); }
.batch-pill-rm {
  background: none;
  border: none;
  color: #7c3aed;
  font-size: 0.8rem;
  cursor: pointer;
  padding: 0;
  line-height: 1;
  margin-left: 0.1rem;
  transition: color 0.15s;
}
.batch-pill-rm:hover { color: #f87171; }
.batch-tag-hint {
  margin-top: 0.55rem;
  font-size: 0.72rem;
  color: #334155;
  font-style: italic;
}

/* ════════════════════════════════════════════════════════════
   Facet Tag Matrix — 分面标签矩阵容器（胶囊视觉见 src/style.css）
   ════════════════════════════════════════════════════════════ */

/* ── 分面标签矩阵容器 ─────────────────────────────────────── */
.facet-tag-matrix {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin-top: 0.4rem;
}

.facet-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
}

.quick-tag-btn {
  margin-top: 0.12rem;
  width: 100%;
  padding: 0.38rem 0.55rem;
  border-radius: 8px;
  border: 1px solid rgba(139, 92, 246, 0.48);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.22), rgba(139, 92, 246, 0.12));
  color: #c4b5fd;
  font-size: 0.72rem;
  font-weight: 700;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}
.quick-tag-btn:hover {
  border-color: rgba(167, 139, 250, 0.85);
  box-shadow: 0 0 14px rgba(139, 92, 246, 0.28);
}

/* 分组标签样式见全局 style.css — .facet-label-* */

/* ── Grid 卡片分面胶囊容器（Step 4: 统一标签展示区） ─────── */
.asset-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.2rem;
  overflow: hidden;
  margin-top: 0.3rem;
}

/* ── 列表模式：折叠为单行紧凑流，隐藏分组标签 ─────────────── */
.assets-list .facet-tag-matrix {
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.2rem;
  margin-top: 0;
}
.assets-list .facet-group {
  display: contents; /* 子元素直接参与父 flex 流，消除嵌套 */
}
.assets-list .facet-label {
  display: none;
}
.assets-list .tag-pill {
  font-size: 0.62rem;
  padding: 0.1rem 0.35rem;
}

/* ════════════════════════════════════════════════════════════
   分面打标工作台 — Facet Bucket Workbench
   ════════════════════════════════════════════════════════════ */

.bucket-field-header {
  display: flex;
  align-items: baseline;
  gap: 0.55rem;
  margin-bottom: 0.7rem;
}

/* ── 2×2 桶容器 ───────────────────────────────────────────── */
.facet-buckets-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.6rem;
}

/* ── 单个打标桶 ───────────────────────────────────────────── */
.facet-bucket {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding: 0.65rem 0.7rem 0.55rem;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  background: rgba(2, 8, 23, 0.5);
  transition: border-color 0.2s, box-shadow 0.2s;
}
/* 各桶主题边框 */
.facet-bucket-hook   { border-color: rgba(192, 132, 252, 0.18); }
.facet-bucket-entity { border-color: rgba(74, 222, 128, 0.18);  }
.facet-bucket-vibe   { border-color: rgba(56, 189, 248, 0.18);  }
.facet-bucket-layer  { border-color: rgba(251, 191, 36, 0.18);  }

.facet-bucket-hook:focus-within   { border-color: rgba(192, 132, 252, 0.45); box-shadow: 0 0 0 3px rgba(192, 132, 252, 0.07); }
.facet-bucket-entity:focus-within { border-color: rgba(74, 222, 128, 0.45);  box-shadow: 0 0 0 3px rgba(74, 222, 128, 0.07);  }
.facet-bucket-vibe:focus-within   { border-color: rgba(56, 189, 248, 0.45);  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.07);  }
.facet-bucket-layer:focus-within  { border-color: rgba(251, 191, 36, 0.45);  box-shadow: 0 0 0 3px rgba(251, 191, 36, 0.07);  }

/* ── 桶标题行 ─────────────────────────────────────────────── */
.bucket-head {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.bucket-icon {
  font-size: 0.85rem;
  line-height: 1;
}
.bucket-label {
  font-size: 0.72rem;
  font-weight: 700;
  font-family: 'Inter', sans-serif;
  color: #94a3b8;
  letter-spacing: 0.02em;
  flex: 1;
}
.bucket-count {
  font-size: 0.62rem;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  padding: 0.05rem 0.38rem;
  border-radius: 99px;
  background: rgba(139, 92, 246, 0.18);
  color: #c4b5fd;
  border: 1px solid rgba(139, 92, 246, 0.3);
}

/* ── 已选标签区 ───────────────────────────────────────────── */
.bucket-selected {
  display: flex;
  flex-wrap: wrap;
  gap: 0.22rem;
  min-height: 1.4rem;
}

/* ── 输入行 ───────────────────────────────────────────────── */
.bucket-input-row {
  display: flex;
  gap: 0.3rem;
  align-items: center;
}
.bucket-input {
  flex: 1;
  background: rgba(2, 8, 23, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 6px;
  color: #e2e8f0;
  font-size: 0.72rem;
  font-family: 'Inter', sans-serif;
  padding: 0.3rem 0.55rem;
  outline: none;
  transition: border-color 0.18s, box-shadow 0.18s;
}
.bucket-input::placeholder { color: #334155; font-size: 0.68rem; }
.bucket-input-hook:focus   { border-color: rgba(192, 132, 252, 0.5); box-shadow: 0 0 0 2px rgba(192, 132, 252, 0.08); }
.bucket-input-entity:focus { border-color: rgba(74, 222, 128, 0.5);  box-shadow: 0 0 0 2px rgba(74, 222, 128, 0.08);  }
.bucket-input-vibe:focus   { border-color: rgba(56, 189, 248, 0.5);  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.08);  }
.bucket-input-layer:focus  { border-color: rgba(251, 191, 36, 0.5);  box-shadow: 0 0 0 2px rgba(251, 191, 36, 0.08);  }

.bucket-add-btn {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  color: #64748b;
  font-size: 0.95rem;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
  flex-shrink: 0;
}
.bucket-add-btn:hover { background: rgba(255,255,255,0.1); color: #e2e8f0; border-color: rgba(255,255,255,0.25); }

/* ── 词云候选积木 ─────────────────────────────────────────── */
.bucket-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 0.2rem;
  padding-top: 0.25rem;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}
.bucket-cloud-empty {
  font-size: 0.62rem;
  color: #1e293b;
  font-style: italic;
  padding-top: 0.2rem;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}

/* ── 词云积木 (cloud-chip) ────────────────────────────────── */
.cloud-chip {
  display: inline-flex;
  align-items: center;
  font-size: 0.63rem;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  padding: 0.1rem 0.38rem;
  border-radius: 4px;
  border: 1px dashed transparent;
  cursor: pointer;
  transition: background 0.15s, border-color 0.18s, box-shadow 0.18s, transform 0.12s;
  white-space: nowrap;
}
.cloud-chip:hover { transform: translateY(-1px); }
.cloud-chip:active { transform: translateY(0); }

/* 各主题词云积木 */
.cloud-chip-hook   { color: rgba(192,132,252,0.7); background: rgba(192,132,252,0.06); border-color: rgba(192,132,252,0.2); }
.cloud-chip-entity { color: rgba(74,222,128,0.7);  background: rgba(74,222,128,0.06);  border-color: rgba(74,222,128,0.2);  }
.cloud-chip-vibe   { color: rgba(56,189,248,0.7);  background: rgba(56,189,248,0.06);  border-color: rgba(56,189,248,0.2);  }
.cloud-chip-layer  { color: rgba(251,191,36,0.7);  background: rgba(251,191,36,0.06);  border-color: rgba(251,191,36,0.2);  }

.cloud-chip-hook:hover   { color: #c084fc; background: rgba(192,132,252,0.14); border-color: rgba(192,132,252,0.45); box-shadow: 0 0 6px rgba(192,132,252,0.2); border-style: solid; }
.cloud-chip-entity:hover { color: #4ade80; background: rgba(74,222,128,0.14);  border-color: rgba(74,222,128,0.45);  box-shadow: 0 0 6px rgba(74,222,128,0.2);  border-style: solid; }
.cloud-chip-vibe:hover   { color: #38bdf8; background: rgba(56,189,248,0.14);  border-color: rgba(56,189,248,0.45);  box-shadow: 0 0 6px rgba(56,189,248,0.2);  border-style: solid; }
.cloud-chip-layer:hover  { color: #fbbf24; background: rgba(251,191,36,0.14);  border-color: rgba(251,191,36,0.45);  box-shadow: 0 0 6px rgba(251,191,36,0.2);  border-style: solid; }

/* 已注入状态 */
.cloud-chip--active.cloud-chip-hook   { color: #c084fc; background: rgba(192,132,252,0.2); border-color: rgba(192,132,252,0.5); border-style: solid; opacity: 0.6; cursor: default; }
.cloud-chip--active.cloud-chip-entity { color: #4ade80; background: rgba(74,222,128,0.2);  border-color: rgba(74,222,128,0.5);  border-style: solid; opacity: 0.6; cursor: default; }
.cloud-chip--active.cloud-chip-vibe   { color: #38bdf8; background: rgba(56,189,248,0.2);  border-color: rgba(56,189,248,0.5);  border-style: solid; opacity: 0.6; cursor: default; }
.cloud-chip--active.cloud-chip-layer  { color: #fbbf24; background: rgba(251,191,36,0.2);  border-color: rgba(251,191,36,0.5);  border-style: solid; opacity: 0.6; cursor: default; }

/* ════════════════════════════════════════════════════════════
   Phase 8.4 — Data Grid 高密度数据流视图
   ════════════════════════════════════════════════════════════ */

/* ── 表格容器 ─────────────────────────────────────────────── */
.dg-table {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 0.35rem;
  width: 100%;    /* 确保行宽 = 容器宽，1fr/2fr 列按实际可用宽度分配 */
}

/* 列定义：[40px checkbox][56px thumb][1fr name][2fr tags][76px usage][44px ops] */
.dg-header,
.dg-row {
  display: grid;
  grid-template-columns: 40px 56px 1fr 2fr 76px 44px;
  align-items: center;
  width: 100%;      /* 确保行占满容器，1fr/2fr 按实际宽度分配 */
}
/* overflow: visible 让标签气泡/输入框可以溢出格子；min-width: 0 阻止 grid 单元格把 1fr 撑爆 */
.dg-cell { overflow: visible; min-width: 0; }

/* ── 表头（列表模式）：高对比 + 字号与正文行对齐感 ─────────── */
.dg-header {
  padding: 0.35rem 0;
  margin-bottom: 4px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.72);
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: none;
  color: #e2e8f0;
  font-family: 'Inter', sans-serif;
}
.dg-header .dg-cell {
  padding: 0.35rem 0.5rem;
  color: #e2e8f0;
}

/* ── 数据行 ───────────────────────────────────────────────── */
.dg-row {
  min-height: 48px;
  /* max-height 已移除：不再截断标签墙及输入框内容 */
  background: rgba(2, 8, 23, 0.42);
  border: 1px solid rgba(255, 255, 255, 0.04);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.1s, border-color 0.1s, box-shadow 0.1s;
  position: relative;
  overflow: visible; /* 允许快捷打标气泡溢出行边界 */
}
.dg-row:hover {
  background: rgba(15, 23, 42, 0.75);
  border-color: rgba(255, 255, 255, 0.09);
}
.dg-row-selected {
  background: rgba(139, 92, 246, 0.07) !important;
  border-color: rgba(139, 92, 246, 0.38) !important;
  box-shadow: inset 0 0 0 1px rgba(139, 92, 246, 0.12);
}
.dg-row-exhausted { opacity: 0.55; }
.dg-row .dg-cell { padding: 0 0.5rem; }
.dg-col-check { display: flex; align-items: center; justify-content: center; padding: 0 !important; }

/* ── 缩略图格 ─────────────────────────────────────────────── */
.dg-col-thumb { padding: 4px 0.35rem !important; }
.dg-thumb-wrap {
  width: 48px;
  height: 48px;
  border-radius: 4px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.45);
  flex-shrink: 0;
  cursor: crosshair;
}
.dg-thumb-media {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.2s;
}
.dg-thumb-wrap:hover .dg-thumb-media { transform: scale(1.08); }
.dg-thumb-audio-icon {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  background: rgba(15, 23, 42, 0.7);
}

/* ── 名称格 ───────────────────────────────────────────────── */
.dg-col-name {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  justify-content: center;
  min-width: 0;
}
.dg-name-text {
  font-size: 0.71rem;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 500;
  color: #cbd5e1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}

/* ── 标签墙格 ─────────────────────────────────────────────── */
.dg-col-tags-pos { position: relative; }
.dg-tag-wall {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 0.18rem;
  overflow: hidden;
}
.dg-no-tags {
  font-size: 0.62rem;
  color: #1e293b;
  font-style: italic;
}
.dg-overflow-badge {
  flex-shrink: 0;
  font-size: 0.58rem;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
  color: #475569;
  background: rgba(71, 85, 105, 0.14);
  border: 1px solid rgba(71, 85, 105, 0.2);
  border-radius: 3px;
  padding: 0.05rem 0.28rem;
  white-space: nowrap;
}
.dg-quick-tag-btn {
  flex-shrink: 0;
  margin-left: auto;
  background: none;
  border: 1px dashed rgba(139, 92, 246, 0.28);
  border-radius: 4px;
  color: rgba(139, 92, 246, 0.5);
  font-size: 0.68rem;
  font-weight: 700;
  padding: 0.08rem 0.28rem;
  cursor: pointer;
  line-height: 1.2;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
  white-space: nowrap;
  opacity: 0;
  transition: opacity 0.15s, border-color 0.15s, color 0.15s, background 0.15s;
}
.dg-row:hover .dg-quick-tag-btn { opacity: 1; }
.dg-quick-tag-btn:hover {
  border-color: rgba(139, 92, 246, 0.65);
  color: #c4b5fd;
  background: rgba(139, 92, 246, 0.09);
}

/* ── 消耗格 ───────────────────────────────────────────────── */
.dg-col-usage {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.22rem;
  justify-content: center;
}
.dg-usage-count {
  font-size: 0.72rem;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #e2e8f0;
  line-height: 1;
}
.dg-usage-unit {
  font-size: 0.58rem;
  font-weight: 400;
  color: #475569;
  margin-left: 0.1rem;
}
.dg-health-track {
  width: 52px;
  height: 3px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 99px;
  overflow: hidden;
}
.dg-health-track .health-bar { height: 100%; border-radius: 99px; transition: width 0.4s; }

/* ── 操作格 ───────────────────────────────────────────────── */
.dg-col-ops {
  display: flex;
  align-items: center;
  justify-content: center;
}
.dg-op-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid rgba(239, 68, 68, 0.14);
  background: rgba(239, 68, 68, 0.04);
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.15s, background 0.15s, border-color 0.15s, color 0.15s;
}
.dg-row:hover .dg-op-btn { opacity: 1; }
.dg-op-btn:hover {
  background: rgba(239, 68, 68, 0.18);
  border-color: rgba(239, 68, 68, 0.45);
  color: #fca5a5;
}
.dg-op-icon { width: 13px; height: 13px; }

/* ── 毫秒级浮窗预览层 ─────────────────────────────────────── */
.hover-preview-layer {
  position: fixed;
  width: 200px;
  aspect-ratio: 9 / 16;
  border-radius: 12px;
  overflow: hidden;
  z-index: 9999;
  pointer-events: none;
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.05),
    0 16px 64px rgba(0, 0, 0, 0.78),
    0 0 30px rgba(0, 0, 0, 0.4);
  background: #000;
}
.preview-media {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.preview-category-badge {
  position: absolute;
  bottom: 0.5rem;
  left: 0.5rem;
  font-size: 0.6rem;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  color: rgba(255, 255, 255, 0.75);
  background: rgba(0, 0, 0, 0.55);
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  backdrop-filter: blur(6px);
}

/* Preview 淡入出 */
.preview-fade-enter-active { transition: opacity 0.14s, transform 0.14s; }
.preview-fade-leave-active { transition: opacity 0.1s; }
.preview-fade-enter-from   { opacity: 0; transform: scale(0.95) translateY(6px); }
.preview-fade-leave-to     { opacity: 0; }

/* Quick-tag 气泡弹出 */
/* ════════════════════════════════════════════════════════════
   Phase 8.5 — Grid 视觉纪律 + 轴类型角标 + 语义对齐雷达
   ════════════════════════════════════════════════════════════ */

/* ── 缩略图容器高度解锁 (覆盖 App.vue 全局 height:120px 遗留规则)
   全局规则将 .asset-thumb 固定为 120px，而帧使用 aspect-ratio:9/16，
   两者叠加后帧会在 align-items:center 下向上溢出约 109px，第一行被
   scroll container (overflow-y:auto) 裁切，导致第一行显示残缺。
   设为 auto 后容器随帧自适应高度，溢出消除，所有行渲染一致。 */
.asset-thumb {
  height: auto;
}

/* ── 9:16 强制比例媒体帧 ──────────────────────────────────── */
.asset-media-frame {
  position: relative;
  width: 100%;
  aspect-ratio: 9 / 16;
  overflow: hidden;
  border-radius: 8px;
  margin-bottom: 0.55rem;
  background: #000;
  /* 消除因原片画幅差异导致的底部参差 */
}
.asset-media-el {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
/* video controls 固定在帧底部 */
.asset-media-frame video.asset-media-el {
  position: absolute;
  inset: 0;
}

/* ── 引用角标 (帧内左上) ──────────────────────────────────── */
.badge-ref-overlay {
  position: absolute;
  top: 0.45rem;
  left: 0.45rem;
  z-index: 4;
  pointer-events: none;
}

/* ── DSL 轴类型角标 (帧内右上) ───────────────────────────── */
.axis-badge {
  position: absolute;
  top: 0.42rem;
  right: 0.42rem;
  z-index: 5;
  font-size: 0.57rem;
  font-weight: 800;
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  pointer-events: none;
  backdrop-filter: blur(6px);
}
.axis-badge-x {
  color: #93c5fd;
  background: rgba(59, 130, 246, 0.28);
  border: 1px solid rgba(59, 130, 246, 0.5);
  box-shadow: 0 0 10px rgba(59, 130, 246, 0.35);
}
.axis-badge-y {
  color: #fde68a;
  background: rgba(251, 191, 36, 0.22);
  border: 1px solid rgba(251, 191, 36, 0.48);
  box-shadow: 0 0 10px rgba(251, 191, 36, 0.3);
}

/* ── 语义对齐雷达 ─────────────────────────────────────────── */
.alignment-radar {
  margin-top: 0.55rem;
  padding: 0.45rem 0.55rem;
  background: rgba(2, 8, 23, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 7px;
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
}
.radar-header {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-bottom: 0.1rem;
}
.radar-icon {
  width: 11px;
  height: 11px;
  flex-shrink: 0;
  color: #475569;
}
.radar-title {
  font-size: 0.6rem;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #334155;
  flex: 1;
}
.radar-layer-chip {
  font-size: 0.58rem;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  color: #475569;
  background: rgba(71, 85, 105, 0.15);
  border: 1px solid rgba(71, 85, 105, 0.2);
  border-radius: 3px;
  padding: 0.05rem 0.32rem;
  letter-spacing: 0.03em;
  white-space: nowrap;
}
.radar-hint {
  font-size: 0.65rem;
  color: #64748b;
  line-height: 1.45;
  font-family: 'Inter', sans-serif;
  /* 有标签时高亮度 */
}
.radar-hint:not(:has(⚠️)):not(:first-of-type) { color: #7c8fa3; }

/* 有效召回提示增强对比 */
.alignment-radar:has(.radar-hint:not(:empty)) .radar-icon { color: #38bdf8; }

/* ── FAB 升级：危险操作按钮 ───────────────────────────────── */
.fab-status {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.fab-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #a78bfa;
  box-shadow: 0 0 6px rgba(167, 139, 250, 0.8);
  animation: fab-pulse 1.8s ease-in-out infinite;
  flex-shrink: 0;
}
@keyframes fab-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.6; transform: scale(0.75); }
}
.fab-btn-danger {
  background: rgba(239, 68, 68, 0.1);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.28);
}
.fab-btn-danger:hover {
  background: rgba(239, 68, 68, 0.22);
  border-color: rgba(239, 68, 68, 0.55);
  box-shadow: 0 0 14px rgba(239, 68, 68, 0.25);
}

/* ════════════════════════════════════════════════════════════
   Phase 8.7 — 场景底模 (SceneMaster) 插槽可视化体系
   ════════════════════════════════════════════════════════════ */

/* ── 插槽叠加层容器 (asset-media-frame + hover-preview-layer 复用) ── */
.slot-overlays {
  position:       absolute;
  inset:          0;
  pointer-events: none;
  z-index:        6;
}

/* ── 单个插槽虚线框 ─────────────────────────────────────────── */
.slot-box {
  position:         absolute;
  border:           1.5px dashed #ec4899;
  background:       rgba(236, 72, 153, 0.07);
  border-radius:    4px;
  display:          flex;
  align-items:      flex-start;
  padding:          3px 5px;
  box-sizing:       border-box;
  transition:       border-color 0.2s, background 0.2s;
  animation:        slot-pulse 3s ease-in-out infinite;
}

@keyframes slot-pulse {
  0%, 100% { border-color: rgba(236, 72, 153, 0.7); background: rgba(236, 72, 153, 0.07); }
  50%       { border-color: rgba(236, 72, 153, 1);   background: rgba(236, 72, 153, 0.12); }
}

/* ── 插槽标签徽章 ─────────────────────────────────────────── */
.slot-label-badge {
  font-size:        0.52rem;
  font-family:      'JetBrains Mono', monospace;
  font-weight:      700;
  color:            #ec4899;
  background:       rgba(0, 0, 0, 0.72);
  border:           1px solid rgba(236, 72, 153, 0.45);
  padding:          1px 4px;
  border-radius:    3px;
  line-height:      1.3;
  white-space:      nowrap;
  max-width:        100%;
  overflow:         hidden;
  text-overflow:    ellipsis;
  letter-spacing:   0.02em;
  backdrop-filter:  blur(4px);
}

/* ── 浮层速览：无插槽清单时的提示 ──────────────────────────── */
.preview-no-slots-hint {
  position:      absolute;
  bottom:        2.2rem;
  left:          0.5rem;
  right:         0.5rem;
  font-size:     0.6rem;
  color:         rgba(236, 72, 153, 0.7);
  background:    rgba(0, 0, 0, 0.55);
  border:        1px dashed rgba(236, 72, 153, 0.3);
  border-radius: 5px;
  padding:       0.25rem 0.5rem;
  text-align:    center;
  backdrop-filter: blur(4px);
  pointer-events: none;
}

/* ── Grid 卡片：底模插槽汇总区 ─────────────────────────────── */
.asset-slot-summary {
  display:    flex;
  align-items: center;
  gap:        0.35rem;
  margin-top: 0.3rem;
}

.slot-count-badge {
  display:       inline-flex;
  align-items:   center;
  gap:           0.28rem;
  font-size:     0.67rem;
  font-weight:   700;
  font-family:   'JetBrains Mono', monospace;
  color:         #ec4899;
  background:    rgba(236, 72, 153, 0.1);
  border:        1px solid rgba(236, 72, 153, 0.3);
  border-radius: 5px;
  padding:       0.15rem 0.5rem;
  letter-spacing: 0.02em;
  box-shadow:    0 0 8px rgba(236, 72, 153, 0.12);
}

.slot-hint-dim {
  font-weight: 400;
  color:       rgba(236, 72, 153, 0.45);
  font-size:   0.6rem;
}

/* ── Data Grid：插槽数格 ──────────────────────────────────── */
.dg-col-slots {
  display:     flex;
  align-items: center;
  gap:         0.18rem;
  padding:     0 0.5rem;
}

.dg-slot-count {
  font-size:   0.75rem;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color:       #ec4899;
  line-height: 1;
}

.dg-slot-unit {
  font-size:  0.58rem;
  font-weight: 400;
  color:      rgba(236, 72, 153, 0.55);
  margin-left: 0.05rem;
}

/* ── scene_master Tab 的专属玫瑰红描边动效 ──────────────────── */
.tab-active[style*="ec4899"] {
  text-shadow: 0 0 14px rgba(236, 72, 153, 0.5) !important;
}

/* ════════════════════════════════════════════════════════════
   Phase 8.8 — Step 1: 视口固化与滚动隔离
   ════════════════════════════════════════════════════════════ */

.assets-wrap {
  display: flex;
  flex-direction: column;
  flex: 1;             /* 作为 .main-content 的 flex 子项，正确填满可用空间 */
  min-height: 0;       /* 防止 flex 子项撑破父容器 */
  overflow: hidden;
  box-sizing: border-box;
  /* 显式设置，覆盖 App.vue 全局同名规则中 padding/gap 的遗留值 */
  padding: 1.5rem;
  gap: 0.5rem;
}

/* 常驻操作带锁定 */
.assets-header   { flex-shrink: 0; }
.search-bar-strip { flex-shrink: 0; }
.assets-tabs     { flex-shrink: 0; }

/* 滚动容器释能
   display:flex 显式覆盖 App.vue 遗留的全局 display:grid 规则（全局规则优先级低但
   未被 scoped 同名属性覆盖时会漏出），防止子内容区被当作 220px 网格单元格处理。 */
.assets-grid {
  display: flex;           /* ← 覆盖全局遗留 display:grid */
  flex-direction: column;
  gap: 0;                  /* ← 覆盖全局遗留 gap:1.25rem，子区块自行管理间距 */
  flex: 1;
  min-height: 0;
  min-width: 0;            /* 防止 flex 子项宽度收缩至内容最小宽度 */
  width: 100%;             /* 显式撑满，避免 BFC 上下文中宽度计算歧义 */
  overflow-y: auto;
  overflow-x: hidden;
  padding-bottom: 80px;
}

/* ── Header 布局扩展 ──────────────────────────────────────── */
.assets-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.65rem 0 0.75rem;
}
.assets-title {
  font-size: 1.05rem;
  font-weight: 700;
  font-family: 'Inter', sans-serif;
  color: #e2e8f0;
  margin: 0;
  letter-spacing: 0.01em;
}
.assets-header-actions {
  display: flex;
  align-items: center;
  gap: 0.55rem;
}
.trash-entry-btn {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.42rem 0.85rem;
  border-radius: 8px;
  border: 1px solid rgba(239, 68, 68, 0.25);
  background: rgba(239, 68, 68, 0.06);
  color: #fca5a5;
  font-size: 0.78rem;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  transition: all 0.18s;
}
.trash-entry-btn:hover {
  background: rgba(239, 68, 68, 0.14);
  border-color: rgba(239, 68, 68, 0.5);
  box-shadow: 0 0 12px rgba(239, 68, 68, 0.2);
}
.trash-entry-icon { width: 13px; height: 13px; flex-shrink: 0; }

/* ════════════════════════════════════════════════════════════
   Phase 8.8 — Step 2: Grid 卡片截断消除 & 输入层级提升
   ════════════════════════════════════════════════════════════ */

/* 卡片网格布局 */
.assets-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 0.85rem;
  padding: 0.5rem 0;
  width: 100%;      /* 确保 auto-fill 有明确的可用宽度进行列数计算 */
  box-sizing: border-box;
  align-items: start; /* 各行高度独立，防止等高拉伸遮盖邻行输入框 */
}

/* 卡片基础框架 — overflow: visible 确保下拉气泡不被截断 */
.asset-card {
  position: relative;
  z-index: 0;           /* 为每张卡片建立独立 stacking context 基线 */
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  background: rgba(2, 8, 23, 0.55);
  transition: border-color 0.2s, box-shadow 0.2s, z-index 0s;
  overflow: visible;    /* 允许标签输入框溢出卡片边界 */
}
.asset-card:hover {
  border-color: rgba(255, 255, 255, 0.12);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
}

/* 焦点态 Z-Index 防御 — 将激活卡片提升至同行所有相邻卡片之上 */
.asset-card:focus-within {
  z-index: 30;
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.6), 0 12px 24px rgba(0, 0, 0, 0.6);
}

/* asset-info 不应截断内容 */
.asset-info {
  padding: 0.5rem 0.6rem 0.65rem;
}
.asset-name {
  font-size: 0.72rem;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 500;
  color: #cbd5e1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 0.3rem;
}
.asset-health {
  width: 100%;
  height: 3px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 99px;
  overflow: hidden;
  margin: 0.3rem 0;
}
.asset-health .health-bar {
  height: 100%;
  border-radius: 99px;
  transition: width 0.4s;
}

/* ════════════════════════════════════════════════════════════
   Phase 8.8 — Step 3: 极客风自定义标签注入对话框
   ════════════════════════════════════════════════════════════ */

/* Modal 基础层 (scoped 补全，全局若有则覆盖无影响) */
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 8000;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  box-sizing: border-box;
}
.modal-box {
  background: rgba(8, 14, 34, 0.97);
  border: 1px solid rgba(139, 92, 246, 0.3);
  border-radius: 16px;
  padding: 1.5rem;
  max-width: 680px;
  width: 100%;
  max-height: 85vh;
  overflow-y: auto;
  box-shadow: 0 0 60px rgba(139, 92, 246, 0.18), 0 24px 80px rgba(0, 0, 0, 0.7);
  position: relative;
}

/* Custom Prompt Modal 专属覆盖 */
.cpm-overlay { z-index: 9000; }
.cpm-box {
  max-width: 440px;
  border-color: rgba(139, 92, 246, 0.45);
  box-shadow: 0 0 40px rgba(139, 92, 246, 0.25), 0 20px 60px rgba(0, 0, 0, 0.75);
}
.cpm-header {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  margin-bottom: 1rem;
  padding-bottom: 0.65rem;
  border-bottom: 1px solid rgba(139, 92, 246, 0.18);
}
.cpm-icon { font-size: 1.25rem; line-height: 1; }
.cpm-title {
  font-size: 1rem;
  font-weight: 700;
  font-family: 'Inter', sans-serif;
  color: #e2e8f0;
  letter-spacing: 0.01em;
}
.cpm-body {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  margin-bottom: 1.2rem;
}
.cpm-desc {
  font-size: 0.78rem;
  color: #64748b;
  line-height: 1.5;
  margin: 0;
}
.cpm-input-wrap { position: relative; }
.cpm-input-group {
  display: flex;
  align-items: stretch;
  gap: 0.45rem;
  width: 100%;
}
.cpm-facet-select {
  flex: 0 0 auto;
  min-width: 9.5rem;
  max-width: 46%;
  background: rgba(2, 8, 23, 0.9);
  border: 1px solid rgba(139, 92, 246, 0.35);
  border-radius: 9px;
  color: #c4b5fd;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 0.45rem 0.55rem;
  outline: none;
  cursor: pointer;
  font-family: 'Inter', sans-serif;
}
.cpm-facet-select:focus {
  border-color: rgba(139, 92, 246, 0.75);
  box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.12);
}
.cpm-input {
  width: 100%;
  background: rgba(2, 8, 23, 0.8);
  border: 1px solid rgba(139, 92, 246, 0.35);
  border-radius: 9px;
  color: #e2e8f0;
  font-size: 0.88rem;
  font-family: 'Inter', sans-serif;
  padding: 0.6rem 0.85rem;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.cpm-input--grow {
  flex: 1;
  min-width: 0;
  width: auto;
}
.cpm-input:focus {
  border-color: rgba(139, 92, 246, 0.75);
  box-shadow:
    0 0 0 3px rgba(139, 92, 246, 0.12),
    0 0 20px rgba(139, 92, 246, 0.15),
    inset 0 0 8px rgba(139, 92, 246, 0.04);
}
.cpm-input::placeholder { color: #334155; font-size: 0.8rem; }
.cpm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.6rem;
}
.cpm-cancel-btn {
  padding: 0.45rem 1rem;
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04);
  color: #94a3b8;
  font-size: 0.8rem;
  font-weight: 500;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.cpm-cancel-btn:hover { background: rgba(255,255,255,0.08); color: #e2e8f0; }
.cpm-confirm-btn {
  padding: 0.45rem 1.25rem;
  border-radius: 8px;
  border: 1px solid rgba(139,92,246,0.55);
  background: linear-gradient(135deg, rgba(139,92,246,0.3), rgba(99,102,241,0.3));
  color: #e9d5ff;
  font-size: 0.8rem;
  font-weight: 700;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  letter-spacing: 0.02em;
  transition: all 0.18s;
  box-shadow: 0 0 14px rgba(139,92,246,0.2);
}
.cpm-confirm-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(139,92,246,0.5), rgba(99,102,241,0.5));
  box-shadow: 0 0 22px rgba(139,92,246,0.4);
  border-color: rgba(139,92,246,0.8);
}
.cpm-confirm-btn:disabled { opacity: 0.32; cursor: not-allowed; }
.cpm-confirm-btn--danger {
  border-color: rgba(239, 68, 68, 0.55);
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.35), rgba(185, 28, 28, 0.28));
  color: #fecaca;
  box-shadow: 0 0 14px rgba(239, 68, 68, 0.22);
}
.cpm-confirm-btn--danger:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.52), rgba(185, 28, 68, 0.42));
  border-color: rgba(248, 113, 113, 0.85);
  box-shadow: 0 0 22px rgba(239, 68, 68, 0.35);
}

/* ════════════════════════════════════════════════════════════
   Phase 8.8 — Step 5: 回收站中台样式
   ════════════════════════════════════════════════════════════ */

.trash-bin-view { padding: 0.5rem 0; }

.trash-header-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.55rem 0 0.75rem;
  border-bottom: 1px solid rgba(239, 68, 68, 0.15);
  margin-bottom: 0.75rem;
}
.trash-title-block {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
}
.trash-title-glyph { font-size: 1.1rem; line-height: 1; }
.trash-title-text {
  font-size: 0.95rem;
  font-weight: 700;
  font-family: 'Inter', sans-serif;
  color: #fca5a5;
  letter-spacing: 0.01em;
}
.trash-count-badge {
  font-size: 0.67rem;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  padding: 0.07rem 0.5rem;
  border-radius: 99px;
  background: rgba(239, 68, 68, 0.14);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.3);
}
.trash-exit-btn {
  padding: 0.35rem 0.85rem;
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04);
  color: #94a3b8;
  font-size: 0.78rem;
  font-weight: 500;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.trash-exit-btn:hover {
  background: rgba(56,189,248,0.08);
  color: #38bdf8;
  border-color: rgba(56,189,248,0.3);
}

.trash-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 3rem 1rem;
}
.trash-empty-icon { font-size: 2.5rem; opacity: 0.4; }
.trash-empty-text { color: #475569; font-size: 0.88rem; font-weight: 500; }

.trash-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.trash-item {
  display: grid;
  grid-template-columns: 26px 1fr 88px 1fr auto;
  align-items: center;
  gap: 0.65rem;
  padding: 0.55rem 0.75rem;
  background: rgba(239, 68, 68, 0.03);
  border: 1px solid rgba(239, 68, 68, 0.1);
  border-radius: 8px;
  transition: background 0.15s, border-color 0.15s;
}
.trash-item:hover {
  background: rgba(239, 68, 68, 0.06);
  border-color: rgba(239, 68, 68, 0.22);
}
.trash-item-icon { font-size: 1.05rem; text-align: center; line-height: 1; }
.trash-item-name {
  font-size: 0.72rem;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 500;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.trash-item-type {
  font-size: 0.65rem;
  color: #475569;
  font-family: 'Inter', sans-serif;
  font-weight: 500;
  white-space: nowrap;
}
.trash-item-tags { display: flex; flex-wrap: wrap; gap: 0.2rem; min-width: 0; }
.trash-item-ops  { display: flex; gap: 0.45rem; flex-shrink: 0; }

.trash-restore-btn {
  padding: 0.28rem 0.65rem;
  border-radius: 6px;
  border: 1px solid rgba(74, 222, 128, 0.3);
  background: rgba(74, 222, 128, 0.07);
  color: #4ade80;
  font-size: 0.72rem;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}
.trash-restore-btn:hover {
  background: rgba(74, 222, 128, 0.15);
  border-color: rgba(74, 222, 128, 0.55);
  box-shadow: 0 0 10px rgba(74, 222, 128, 0.2);
}
.trash-purge-btn {
  padding: 0.28rem 0.65rem;
  border-radius: 6px;
  border: 1px solid rgba(239, 68, 68, 0.3);
  background: rgba(239, 68, 68, 0.07);
  color: #fca5a5;
  font-size: 0.72rem;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}
.trash-purge-btn:hover {
  background: rgba(239, 68, 68, 0.18);
  border-color: rgba(239, 68, 68, 0.55);
  box-shadow: 0 0 10px rgba(239, 68, 68, 0.2);
}

/* Modal 淡入出动效 (scoped 本地定义，若全局已有则此处无副作用) */
.modal-fade-enter-active { transition: opacity 0.2s, transform 0.22s cubic-bezier(0.34, 1.3, 0.64, 1); }
.modal-fade-leave-active { transition: opacity 0.15s; }
.modal-fade-enter-from  { opacity: 0; transform: scale(0.96) translateY(8px); }
.modal-fade-leave-to    { opacity: 0; }

/* ── Text Template 专属预览块 ─────────────────────────────────── */
.text-asset-preview {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.75rem;
  box-sizing: border-box;
  background: linear-gradient(135deg, #4c1d95 0%, #2e1065 50%, #1e1b4b 100%);
  color: #fff;
  font-weight: 700;
  font-size: 0.82rem;
  line-height: 1.45;
  text-align: center;
  word-break: break-all;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  border-radius: 4px;
  letter-spacing: 0.01em;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.5);
}
.text-asset-preview--thumb {
  font-size: 0.7rem;
  -webkit-line-clamp: 2;
  padding: 0.4rem;
  border-radius: 3px;
}

/* ── 文本创建弹窗 ──────────────────────────────────────────────── */
.text-modal-box { max-width: 560px; width: 90vw; }
.text-modal-field { display: flex; flex-direction: column; gap: 0.35rem; margin-bottom: 1rem; }
.text-modal-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.7);
  letter-spacing: 0.02em;
}
.text-modal-input,
.text-modal-textarea {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(139, 92, 246, 0.35);
  border-radius: 6px;
  color: #e2e8f0;
  font-size: 0.85rem;
  padding: 0.55rem 0.75rem;
  outline: none;
  resize: vertical;
  transition: border-color 0.18s, box-shadow 0.18s;
  font-family: inherit;
}
.text-modal-input:focus,
.text-modal-textarea:focus {
  border-color: rgba(139, 92, 246, 0.7);
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.15);
}
.text-modal-textarea--rtl { direction: rtl; text-align: right; }
</style>
