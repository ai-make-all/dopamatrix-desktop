<script setup>
import { ref, computed, watch, reactive } from 'vue'
import draggable from 'vuedraggable'
import axios from 'axios'
import { getTagPillParts, parseFacetedTags } from '../utils/tagParser.js'

// ── Props & Emits ────────────────────────────────────────────────────────────
const props = defineProps({
  modelValue:      { type: Boolean,  default: false },
  dbAssetList:     { type: Array,    default: () => [] },
  dslTracks:       { type: Array,    default: () => [] },
  templates:       { type: Object,   required: true },
  currentTemplate: { type: String,   default: 'content' },
  buildVideoUrl:   { type: Function, required: true },
  apiBase:         { type: String,   required: true },
  showToast:       { type: Function, default: () => {} },
})

const emit = defineEmits(['update:modelValue', 'confirm'])

// ── Asset registry & facet namespace config ───────────────────────────────────
const ASSET_TYPE_REGISTRY = [
  { type: 'all',          label: '全部',  icon: '📦' },
  { type: 'video',        label: '视频',  icon: '🎬' },
  { type: 'image',        label: '图片',  icon: '🖼️' },
  { type: 'audio_bgm',    label: 'BGM',   icon: '🎵' },
  { type: 'vfx',          label: 'VFX',   icon: '✨' },
  { type: 'sfx',          label: 'SFX',   icon: '🔊' },
  { type: 'scene_master', label: '底模',  icon: '🏛️' },
]

/** parseFacetedTags 的 theme → 抽屉既有 orch-* 色键（仅 UI，与 DAM 解析无关） */
const FACET_THEME_COLOR = {
  hook: 'purple',
  entity: 'green',
  vibe: 'sky',
  vfx: 'amber',
  sfx: 'orange',
  generic: 'indigo',
}

// ── Local editor state ───────────────────────────────────────────────────────
const localTracks     = ref([])
const localTemplate   = ref('content')
const leftTab         = ref('assets')
const assetSearch     = ref('')
const activeTag       = ref(null)
const assetTypeFilter = ref('video')

// Dry-run preview
const isPreviewLoading = ref(false)
const previewData      = ref(null)
const showPreviewModal = ref(false)

// ── Phase 8.7：底模母槽 (Master Track) 状态 ─────────────────────────────────
// masterDropList: 母槽 draggable 数组，最多容纳 1 个 scene_master 克隆
const masterDropList = ref([])
// slotItemsMap: 插槽 key → [bound_asset_clone]，reactive 保证 v-model 实时响应
const slotItemsMap   = reactive({})

// 当前已装载底模的插槽定义列表
const activeSlotDefs = computed(() => masterDropList.value[0]?.manifest?.slots ?? [])

// 根据插槽 key 推断色彩主题
function getSlotTheme(slotKey) {
  const k = (slotKey || '').toLowerCase()
  if (k.includes('hook') || k.includes('head')   || k.includes('open'))  return 'purple'
  if (k.includes('vfx')  || k.includes('weapon') || k.includes('hit'))   return 'amber'
  if (k.includes('avatar')|| k.includes('face')  || k.includes('target'))return 'sky'
  if (k.includes('text') || k.includes('caption')|| k.includes('logo'))  return 'green'
  return 'rose'
}

// ── Sync on open ─────────────────────────────────────────────────────────────
watch(() => props.modelValue, (opened) => {
  if (!opened) return
  localTracks.value     = JSON.parse(JSON.stringify(props.dslTracks))
  localTemplate.value   = props.currentTemplate
  leftTab.value         = 'assets'
  assetSearch.value     = ''
  activeTag.value       = null
  assetTypeFilter.value = 'video'
  // 重置底模母槽
  masterDropList.value = []
  for (const k in slotItemsMap) delete slotItemsMap[k]
})

// Re-init tracks when template switches inside the drawer
watch(localTemplate, (newTpl, oldTpl) => {
  if (newTpl === oldTpl) return
  const tpl = props.templates[newTpl]
  if (!tpl) return
  localTracks.value = tpl.map(t => ({ ...t, items: [] }))
})

// ── Computed ──────────────────────────────────────────────────────────────────
const uniqueTags = computed(() => {
  const seen = new Set()
  for (const asset of props.dbAssetList)
    for (const tag of (asset.tags || []))
      if (tag) seen.add(tag)
  return [...seen].sort()
})

// 分面标签池：与 DAM 共用 parseFacetedTags（SSOT），全库 uniqueTags 聚合成伪资产再分桶
const facetedTags = computed(() => {
  const pool = { tags: uniqueTags.value }
  return parseFacetedTags(pool.tags).map(facet => ({
    ...facet,
    tags: facet.values.map(v => v.raw),
    color: FACET_THEME_COLOR[facet.theme] || 'indigo',
  }))
})

const filteredAssets = computed(() => {
  let list = props.dbAssetList
  if (assetTypeFilter.value !== 'all')
    list = list.filter(a => a.asset_type === assetTypeFilter.value)
  const q = assetSearch.value.trim().toLowerCase()
  if (q)
    list = list.filter(a =>
      a.asset_name?.toLowerCase().includes(q) ||
      a.file_path?.toLowerCase().includes(q)  ||
      (a.tags || []).some(t => t.toLowerCase().includes(q))
    )
  if (activeTag.value)
    list = list.filter(a => (a.tags || []).includes(activeTag.value))
  return list
})

const lockedHashes = computed(() => {
  const seen = new Set()
  for (const t of localTracks.value)
    for (const item of t.items)
      if (item.hash) seen.add(item.hash)
  return [...seen]
})

const totalStaged = computed(() =>
  localTracks.value.reduce((s, t) => s + t.items.length, 0)
)

// ── Clone factories ───────────────────────────────────────────────────────────
function cloneAsset(asset) {
  return {
    uuid:       `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    type:       'physical_asset',
    id:         asset.id,
    hash:       asset.file_hash,
    asset_type: asset.asset_type || 'video',
    file_path:  asset.file_path,
    name:       asset.file_path.split(/[/\\]/).pop(),
    manifest:   asset.manifest ?? null,
  }
}

function cloneTag(tag) {
  return {
    uuid: `tag_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    type: 'semantic_tag',
    tag,
  }
}

function removeBlock(track, uuid) {
  track.items = track.items.filter(b => b.uuid !== uuid)
}

function clearAll() {
  localTracks.value.forEach(t => { t.items = [] })
}

// ── 底模母槽事件处理 ──────────────────────────────────────────────────────────
function onMasterTrackChange(evt) {
  if (!evt.added) return
  const item = evt.added.element
  if (item.asset_type !== 'scene_master') {
    // 拒绝非底模资产，从列表中移除
    const idx = masterDropList.value.findIndex(i => i.uuid === item.uuid)
    if (idx !== -1) masterDropList.value.splice(idx, 1)
    props.showToast('⚠️ 母槽仅接受【场景底模】类型资产，请从 DAM 导入底模后再拖入')
    return
  }
  // 仅保留最新一个底模
  if (masterDropList.value.length > 1)
    masterDropList.value.splice(0, masterDropList.value.length - 1)
  // 裂变：初始化插槽绑定 Map
  for (const k in slotItemsMap) delete slotItemsMap[k]
  const slots = item.manifest?.slots ?? []
  slots.forEach(s => { slotItemsMap[s.slot_key] = [] })
}

function onMasterRemoved(evt) {
  if (evt.removed && masterDropList.value.length === 0) {
    for (const k in slotItemsMap) delete slotItemsMap[k]
  }
}

function clearMasterTrack() {
  masterDropList.value = []
  for (const k in slotItemsMap) delete slotItemsMap[k]
}

// 单插槽接收 — 每槽最多绑定 1 个资产
function onSlotChange(slotKey, evt) {
  if (!evt.added) return
  const list = slotItemsMap[slotKey]
  if (list && list.length > 1) list.splice(0, list.length - 1)
}

function unbindSlot(slotKey) {
  if (slotItemsMap[slotKey]) slotItemsMap[slotKey] = []
}

// ── DSL Dry-run preview ───────────────────────────────────────────────────────
async function runPreview() {
  const active = localTracks.value.filter(t => t.items.length > 0)
  if (active.length === 0) {
    props.showToast('⚠️ 请至少装填一个节拍后再预览')
    return
  }
  isPreviewLoading.value = true
  try {
    const payload = {
      engine_type: localTemplate.value,
      timeline: localTracks.value.map(track => {
        const physicals = track.items.filter(i => i.type === 'physical_asset')
        const semantics  = track.items.filter(i => i.type === 'semantic_tag')
        return {
          beat:          track.id,
          role:          track.role,
          address_mode:  physicals.length > 0 ? 'locked' : 'smart',
          asset_hashes:  physicals.map(i => i.hash),
          semantic_tags: semantics.map(i => i.tag),
        }
      }).filter(b => b.asset_hashes.length > 0 || b.semantic_tags.length > 0),
    }
    const resp = await axios.post(`${props.apiBase}/api/v1/tasks/submit-dsl`, payload)
    previewData.value      = resp.data
    showPreviewModal.value = true
    props.showToast('✅ DSL 解析成功，已生成作战蓝图')
  } catch (err) {
    const raw    = err.response?.data?.detail
    const detail = Array.isArray(raw)
      ? raw.map(e => e.msg ?? JSON.stringify(e)).join('；')
      : (raw ?? err.message ?? '未知错误')
    props.showToast(`[${err.response?.status ?? 'ERR'}] DSL 解析失败：${detail}`)
  } finally {
    isPreviewLoading.value = false
  }
}

// ── Confirm / Cancel ──────────────────────────────────────────────────────────
function handleConfirm() {
  const masterItem = masterDropList.value[0] ?? null
  // 精准指纹回传：底模 ID + 各插槽绑定的 File Hash
  const masterTrackPlan = masterItem ? {
    scene_master_id:   masterItem.id,
    scene_master_hash: masterItem.hash,
    dsl_layer:         'SceneMaster',
    slot_bindings:     Object.entries(slotItemsMap)
      .filter(([, arr]) => arr.length > 0)
      .map(([slot_key, arr]) => ({
        slot_key,
        asset_hash: arr[0].hash,
        asset_type: arr[0].asset_type,
        asset_name: arr[0].name,
      })),
  } : null

  emit('confirm', {
    tracks:       JSON.parse(JSON.stringify(localTracks.value)),
    template:     localTemplate.value,
    master_track: masterTrackPlan,
  })
  emit('update:modelValue', false)
}

function handleCancel() {
  emit('update:modelValue', false)
}
</script>

<template>
  <Teleport to="body">

    <!-- ── Backdrop ──────────────────────────────────────────────────────────── -->
    <Transition name="backdrop-fade">
      <div
        v-if="modelValue"
        class="orch-backdrop"
        @click.self="handleCancel"
      />
    </Transition>

    <!-- ── Drawer Panel ───────────────────────────────────────────────────────── -->
    <Transition name="drawer-slide">
      <div v-if="modelValue" class="orch-drawer" role="dialog" aria-modal="true" aria-label="编排战术板">

        <!-- Header ─────────────────────────────────────────────────────────── -->
        <div class="orch-header">
          <div class="orch-header-left">
            <span class="orch-header-icon">⚡</span>
            <span class="orch-header-title">编排战术板</span>
            <span v-if="totalStaged > 0" class="orch-staged-pill">{{ totalStaged }} 已装填</span>
          </div>

          <div class="orch-header-right">
            <select v-model="localTemplate" class="orch-template-select">
              <option value="content">📝 Content</option>
              <option value="ua">🎯 UA / 用户获取</option>
            </select>

            <button
              class="orch-btn orch-btn--preview"
              :class="{ 'orch-btn--loading': isPreviewLoading }"
              :disabled="isPreviewLoading"
              @click="runPreview"
              title="Dry-run 解析，验证素材寻址"
            >{{ isPreviewLoading ? '⏳ 解析中…' : '🔬 蓝图预览' }}</button>

            <button
              v-if="totalStaged > 0"
              class="orch-btn orch-btn--ghost"
              @click="clearAll"
              title="清空所有轨道"
            >✕ 清空</button>

            <button class="orch-btn orch-btn--cancel" @click="handleCancel">取消</button>

            <button class="orch-btn orch-btn--confirm" @click="handleConfirm">
              ✓ 确认装填
              <span v-if="totalStaged > 0" class="orch-confirm-count">{{ totalStaged }}</span>
            </button>
          </div>
        </div>

        <!-- Body ────────────────────────────────────────────────────────────── -->
        <div class="orch-body">

          <!-- ════ 上半部分：弹药仓库 ════════════════════════════════════════ -->
          <div class="orch-warehouse">

            <!-- Tab 行 + 搜索框 -->
            <div class="orch-toolbar-row">
              <div class="orch-tabs">
                <button
                  :class="['orch-tab', leftTab === 'assets' ? 'orch-tab--active' : '']"
                  @click="leftTab = 'assets'"
                >🎬 素材库</button>
                <button
                  :class="['orch-tab', leftTab === 'tags' ? 'orch-tab--active' : '']"
                  @click="leftTab = 'tags'"
                >🏷️ 标签库</button>
              </div>

              <div class="orch-search-wrap">
                <span class="orch-search-icon">🔍</span>
                <input
                  v-model="assetSearch"
                  class="orch-search-input"
                  placeholder="检索素材名称或标签..."
                  type="text"
                  autocomplete="off"
                  spellcheck="false"
                />
                <button
                  v-if="assetSearch"
                  class="orch-search-clear"
                  @click="assetSearch = ''"
                >✕</button>
              </div>
            </div>

            <!-- 资产类型筛选胶囊（素材库模式下显示）-->
            <div v-if="leftTab === 'assets'" class="orch-type-filter-row">
              <button
                v-for="item in ASSET_TYPE_REGISTRY"
                :key="item.type"
                :class="['orch-type-pill', assetTypeFilter === item.type ? 'orch-type-pill--active' : '']"
                @click="assetTypeFilter = item.type; activeTag = null"
              >{{ item.icon }} {{ item.label }}</button>
            </div>

            <!-- 标签筛选流（素材库模式下显示）-->
            <div
              v-if="leftTab === 'assets' && uniqueTags.length > 0"
              class="orch-tag-filter-row"
            >
              <button
                :class="['orch-filter-pill', !activeTag ? 'orch-filter-pill--active' : '']"
                @click="activeTag = null"
              >全部</button>
              <button
                v-for="tag in uniqueTags"
                :key="tag"
                :class="['orch-filter-pill', activeTag === tag ? 'orch-filter-pill--active' : '']"
                @click="activeTag = (activeTag === tag ? null : tag)"
              >
                <template v-for="pill in [getTagPillParts(tag)]" :key="tag + '-pill'">
                  <span :class="['tag-pill', pill.facetClass, 'tag-pill--mini']">
                    <template v-if="pill.showHead">
                      <span class="tag-pill-head">{{ pill.head }}</span>
                      <span class="tag-pill-sep"> | </span>
                    </template>
                    <span class="tag-pill-val">{{ pill.val }}</span>
                  </span>
                </template>
              </button>
            </div>

            <!-- 素材网格 -->
            <div v-show="leftTab === 'assets'" class="orch-scroll-area">
              <div v-if="filteredAssets.length === 0" class="orch-empty">
                {{ assetSearch || activeTag ? '未找到匹配素材' : '暂无素材，请前往 DAM 导入' }}
              </div>
              <draggable
                :list="filteredAssets"
                :clone="cloneAsset"
                item-key="id"
                :group="{ name: 'orch-blocks', pull: 'clone', put: false }"
                :sort="false"
                :force-fallback="true"
                class="orch-asset-grid"
              >
                <template #item="{ element: asset }">
                  <div
                    class="orch-asset-card"
                    :class="{ 'orch-asset-card--locked': lockedHashes.includes(asset.file_hash) }"
                  >
                    <div class="orch-asset-thumb">
                      <video
                        v-if="!asset.asset_type || asset.asset_type === 'video'"
                        :src="buildVideoUrl(asset.file_path)"
                        muted
                        preload="metadata"
                        class="orch-asset-video"
                      />
                      <img
                        v-else-if="asset.asset_type === 'image'"
                        :src="buildVideoUrl(asset.file_path)"
                        class="orch-asset-image"
                      />
                      <div
                        v-else
                        class="orch-asset-icon-thumb"
                        :class="`orch-asset-icon-thumb--${asset.asset_type}`"
                      >
                        {{ asset.asset_type === 'audio_bgm' || asset.asset_type === 'sfx' ? '🎵' : asset.asset_type === 'vfx' ? '✨' : '📄' }}
                      </div>
                      <div v-if="lockedHashes.includes(asset.file_hash)" class="orch-lock-badge">🔒</div>
                    </div>
                    <div class="orch-asset-footer">
                      <span class="orch-asset-name" :title="asset.file_path">
                        {{ asset.file_path.split(/[/\\]/).pop() }}
                      </span>
                      <div class="orch-asset-meta-pills">
                        <span
                          class="orch-use-badge"
                          :class="{ 'orch-use-badge--warn': asset.is_exhausted }"
                        >×{{ asset.usage_count }}</span>
                        <span v-if="asset.is_exhausted" class="orch-exhausted-badge">疲</span>
                      </div>
                    </div>
                  </div>
                </template>
              </draggable>
            </div>

            <!-- 标签库（分面高亮展示）-->
            <div v-show="leftTab === 'tags'" class="orch-scroll-area">
              <div v-if="uniqueTags.length === 0" class="orch-empty">
                暂无语义标签，请前往 DAM 为素材打标
              </div>
              <template v-for="facet in facetedTags" :key="facet.key">
                <div class="orch-facet-section">
                  <div class="orch-facet-header" :class="`orch-facet-header--${facet.color}`">
                    <span>{{ facet.label ? `${facet.icon} ${facet.label}` : '🔖 其他' }}</span>
                    <span class="orch-facet-count">{{ facet.values.length }}</span>
                  </div>
                  <draggable
                    :list="facet.tags"
                    :clone="cloneTag"
                    :item-key="t => t"
                    :group="{ name: 'orch-blocks', pull: 'clone', put: false }"
                    :sort="false"
                    :force-fallback="true"
                    class="orch-tag-grid"
                  >
                    <template #item="{ element: tag }">
                      <div class="orch-tag-card" :class="`orch-tag-card--${facet.color}`">
                        <template v-for="pill in [getTagPillParts(tag)]" :key="tag">
                          <span :class="['tag-pill', pill.facetClass, 'orch-drag-pill']">
                            <template v-if="pill.showHead">
                              <span class="tag-pill-head">{{ pill.head }}</span>
                              <span class="tag-pill-sep"> | </span>
                            </template>
                            <span class="tag-pill-val">{{ pill.val }}</span>
                          </span>
                        </template>
                      </div>
                    </template>
                  </draggable>
                </div>
              </template>
            </div>

          </div>

          <!-- ════ 分割线 ════════════════════════════════════════════════════ -->
          <div class="orch-divider">
            <span class="orch-divider-label">🎞️ 装填线 · 拖拽素材到节拍槽</span>
          </div>

          <!-- ════ 下半部分：DSL 装填线（横向轨道）════════════════════════════ -->
          <div class="orch-trackline">

            <!-- ╔═══ 🏛️ 底模装载母槽 (Master Track) — 仅在底模筛选激活时显示 ═══╗ -->
            <div
              v-if="assetTypeFilter === 'scene_master'"
              class="master-zone"
              :class="{ 'master-zone--loaded': masterDropList.length > 0 }"
            >
              <div class="master-zone-header">
                <span class="master-zone-icon">🏛️</span>
                <span class="master-zone-title">底模装载母槽 <span class="master-zone-eng">Master Track</span></span>
                <span v-if="masterDropList.length > 0" class="master-zone-badge">{{ activeSlotDefs.length }} 插槽已裂变</span>
                <button
                  v-if="masterDropList.length > 0"
                  class="master-unload-btn"
                  @click="clearMasterTrack"
                  title="卸载底模"
                >✕ 卸载底模</button>
              </div>

              <!-- 未装载状态：拖放目标区 -->
              <draggable
                v-model="masterDropList"
                item-key="uuid"
                group="orch-blocks"
                :force-fallback="true"
                class="master-drop-zone"
                :class="{ 'master-drop-zone--hidden': masterDropList.length > 0 }"
                @change="evt => { onMasterTrackChange(evt); onMasterRemoved(evt) }"
              >
                <template #item><!-- items rendered below --></template>
                <template #footer>
                  <div v-if="masterDropList.length === 0" class="master-empty-hint">
                    <span class="master-empty-icon">🏛️</span>
                    <div>
                      <div class="master-empty-title">拖入【场景底模】以激活动态插槽裂变</div>
                      <div class="master-empty-sub">底模将驱动 B端 FFmpeg 压制 · C端伴侣引擎同步输出</div>
                    </div>
                  </div>
                </template>
              </draggable>

              <!-- 已装载状态：底模信息 + 插槽裂变区 -->
              <Transition name="fission-expand">
                <div v-if="masterDropList.length > 0" class="master-loaded-area">

                  <!-- 底模资产芯片 -->
                  <div class="master-asset-chip">
                    <span class="master-asset-icon">🏛️</span>
                    <span class="master-asset-name">{{ masterDropList[0].name }}</span>
                    <code class="master-asset-hash">{{ (masterDropList[0].hash || '').slice(0, 10) }}…</code>
                    <span class="master-layer-chip">SceneMaster</span>
                  </div>

                  <!-- 插槽动态裂变区 -->
                  <div v-if="activeSlotDefs.length > 0" class="slot-fission-row">
                    <div
                      v-for="slotDef in activeSlotDefs"
                      :key="slotDef.slot_key"
                      :class="['slot-cell', `slot-cell--${getSlotTheme(slotDef.slot_key)}`, slotItemsMap[slotDef.slot_key]?.length > 0 ? 'slot-cell--bound' : '']"
                    >
                      <!-- 插槽头部 -->
                      <div class="slot-cell-header">
                        <span class="slot-cell-key">{{ slotDef.slot_key }}</span>
                        <span v-if="slotDef.accepts" class="slot-cell-accepts">{{ slotDef.accepts }}</span>
                        <button
                          v-if="slotItemsMap[slotDef.slot_key]?.length > 0"
                          class="slot-unbind-btn"
                          @click.stop="unbindSlot(slotDef.slot_key)"
                          title="解绑素材"
                        >✕</button>
                      </div>

                      <!-- 已绑定素材展示 -->
                      <div v-if="slotItemsMap[slotDef.slot_key]?.length > 0" class="slot-bound-content">
                        <span class="slot-bound-icon">
                          {{ slotItemsMap[slotDef.slot_key][0].asset_type === 'video' ? '🎬'
                           : slotItemsMap[slotDef.slot_key][0].asset_type === 'image' ? '🖼️'
                           : slotItemsMap[slotDef.slot_key][0].asset_type === 'vfx'   ? '✨'
                           : '📄' }}
                        </span>
                        <span class="slot-bound-name">{{ slotItemsMap[slotDef.slot_key][0].name }}</span>
                        <code class="slot-bound-hash">{{ (slotItemsMap[slotDef.slot_key][0].hash || '').slice(0, 8) }}…</code>
                      </div>

                      <!-- 未绑定：拖放区 -->
                      <draggable
                        v-else
                        :list="slotItemsMap[slotDef.slot_key]"
                        item-key="uuid"
                        group="orch-blocks"
                        :force-fallback="true"
                        class="slot-drop-zone"
                        @change="evt => onSlotChange(slotDef.slot_key, evt)"
                      >
                        <template #item><!-- items managed via onSlotChange --></template>
                        <template #footer>
                          <div class="slot-empty-label">
                            <span class="slot-empty-icon">⊕</span>
                            <span>待装填: {{ slotDef.label || slotDef.slot_key }}</span>
                          </div>
                        </template>
                      </draggable>
                    </div>
                  </div>

                  <!-- 无插槽清单提示 -->
                  <div v-else class="no-manifest-hint">
                    底模未携带 <code>manifest.slots</code> 清单，将作为纯结构底模使用
                  </div>
                </div>
              </Transition>
            </div>
            <!-- ╚════════════════════════════════════════════╝ -->

            <div class="orch-tracks-scroll">
              <Transition name="tracks-fade" mode="out-in">
                <div :key="localTemplate" class="orch-tracks-row">
                  <div
                    v-for="track in localTracks"
                    :key="track.id"
                    class="orch-track"
                    :class="`orch-track--${track.role}`"
                  >
                    <div class="orch-track-label">
                      <span class="orch-track-name">{{ track.name }}</span>
                      <span
                        v-if="track.items.length > 0"
                        class="orch-track-count"
                      >{{ track.items.length }}</span>
                    </div>

                    <draggable
                      v-model="track.items"
                      item-key="uuid"
                      group="orch-blocks"
                      :force-fallback="true"
                      class="orch-track-drop"
                      :class="{ 'orch-track-drop--filled': track.items.length > 0 }"
                    >
                      <template #item="{ element }">
                        <div
                          class="orch-block"
                          :class="{ 'orch-block--tag': element.type === 'semantic_tag' }"
                        >
                          <video
                            v-if="element.type !== 'semantic_tag' && (!element.asset_type || element.asset_type === 'video')"
                            :src="buildVideoUrl(element.file_path)"
                            muted
                            preload="metadata"
                            class="orch-block-thumb"
                          />
                          <img
                            v-else-if="element.type !== 'semantic_tag' && element.asset_type === 'image'"
                            :src="buildVideoUrl(element.file_path)"
                            class="orch-block-thumb orch-block-thumb--img"
                          />
                          <span
                            v-else-if="element.type !== 'semantic_tag'"
                            class="orch-block-icon-thumb"
                          >{{ element.asset_type === 'audio_bgm' || element.asset_type === 'sfx' ? '🎵' : element.asset_type === 'vfx' ? '✨' : '📄' }}</span>
                          <template v-if="element.type === 'semantic_tag'">
                            <template v-for="pill in [getTagPillParts(element.tag)]" :key="element.uuid">
                              <span :class="['tag-pill', pill.facetClass, 'orch-block-pill']">
                                <template v-if="pill.showHead">
                                  <span class="tag-pill-head">{{ pill.head }}</span>
                                  <span class="tag-pill-sep"> | </span>
                                </template>
                                <span class="tag-pill-val">{{ pill.val }}</span>
                              </span>
                            </template>
                          </template>
                          <span v-else class="orch-block-name">{{ element.name }}</span>
                          <button
                            class="orch-block-remove"
                            @click.stop="removeBlock(track, element.uuid)"
                            title="移除"
                          >✕</button>
                        </div>
                      </template>
                      <template #footer>
                        <div v-if="track.items.length === 0" class="orch-track-empty">
                          <span class="orch-track-empty-icon">⊕</span>
                          <span>拖入素材<br/>或留空 AI 选</span>
                        </div>
                      </template>
                    </draggable>
                  </div>
                </div>
              </Transition>
            </div>
          </div>

        </div>

        <!-- ── DSL 蓝图调试弹窗 ──────────────────────────────────────────────── -->
        <Teleport to="body">
          <Transition name="modal-fade">
            <div
              v-if="showPreviewModal"
              class="preview-modal-backdrop"
              @click.self="showPreviewModal = false"
            >
              <div class="preview-modal">
                <div class="preview-modal-header">
                  <span class="preview-modal-title">🛠️ DSL 渲染蓝图 (Compilation Plan)</span>
                  <div v-if="previewData" class="preview-modal-badges">
                    <span class="prev-badge prev-badge--engine">engine: {{ previewData.engine_type }}</span>
                    <span class="prev-badge prev-badge--ok">✓ {{ previewData.summary?.resolved_beats }} resolved</span>
                    <span
                      v-if="previewData.summary?.unresolved_beats > 0"
                      class="prev-badge prev-badge--warn"
                    >⚠ {{ previewData.summary.unresolved_beats }} unresolved</span>
                  </div>
                </div>
                <div class="preview-modal-body">
                  <pre class="preview-pre"><code>{{ JSON.stringify(previewData, null, 2) }}</code></pre>
                </div>
                <div class="preview-modal-footer">
                  <button class="preview-close-btn" @click="showPreviewModal = false">✕ 关闭</button>
                </div>
              </div>
            </div>
          </Transition>
        </Teleport>

      </div>
    </Transition>

  </Teleport>
</template>

<style scoped>
/* ── Backdrop ───────────────────────────────────────────────────────────────── */
.orch-backdrop {
  position:        fixed;
  inset:           0;
  left:            220px; /* leave sidebar visible */
  background:      rgba(2, 6, 23, 0.78);
  backdrop-filter: blur(6px);
  z-index:         1000;
}

/* ── Drawer Panel ───────────────────────────────────────────────────────────── */
.orch-drawer {
  position:         fixed;
  left:             220px; /* sidebar width */
  right:            0;
  top:              0;
  bottom:           0;
  z-index:          1001;
  display:          flex;
  flex-direction:   column;
  background:       linear-gradient(180deg, #0a0f1e 0%, #0d1117 100%);
  border-left:      1px solid rgba(99, 102, 241, 0.2);
  box-shadow:       -24px 0 80px rgba(0, 0, 0, 0.6), -4px 0 16px rgba(99, 102, 241, 0.08);
  overflow:         hidden;
}

/* ── Animations ─────────────────────────────────────────────────────────────── */
.backdrop-fade-enter-active,
.backdrop-fade-leave-active { transition: opacity 0.25s ease; }
.backdrop-fade-enter-from,
.backdrop-fade-leave-to     { opacity: 0; }

.drawer-slide-enter-active  { transition: transform 0.3s ease-out; }
.drawer-slide-leave-active  { transition: transform 0.25s ease-in; }
.drawer-slide-enter-from,
.drawer-slide-leave-to      { transform: translateX(100%); }

.tracks-fade-enter-active { transition: opacity 0.22s ease, transform 0.22s ease; }
.tracks-fade-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.tracks-fade-enter-from   { opacity: 0; transform: translateX(12px); }
.tracks-fade-leave-to     { opacity: 0; transform: translateX(-8px); }

/* ── Header ─────────────────────────────────────────────────────────────────── */
.orch-header {
  display:         flex;
  align-items:     center;
  justify-content: space-between;
  padding:         0 1.5rem;
  height:          56px;
  flex-shrink:     0;
  background:      rgba(10, 15, 30, 0.95);
  border-bottom:   1px solid rgba(99, 102, 241, 0.18);
  gap:             1rem;
}

.orch-header-left {
  display:     flex;
  align-items: center;
  gap:         0.6rem;
  flex-shrink: 0;
}

.orch-header-icon {
  font-size: 1.1rem;
  filter:    drop-shadow(0 0 8px rgba(99, 102, 241, 0.7));
}

.orch-header-title {
  font-size:      1rem;
  font-weight:    700;
  color:          #e2e8f0;
  letter-spacing: 0.03em;
}

.orch-staged-pill {
  font-size:        0.7rem;
  font-weight:      600;
  padding:          0.18rem 0.6rem;
  border-radius:    20px;
  background:       rgba(99, 102, 241, 0.2);
  border:           1px solid rgba(99, 102, 241, 0.45);
  color:            #a5b4fc;
  letter-spacing:   0.02em;
}

.orch-header-right {
  display:     flex;
  align-items: center;
  gap:         0.5rem;
  flex-wrap:   wrap;
}

/* ── Header Buttons ──────────────────────────────────────────────────────────── */
.orch-btn {
  font-size:      0.75rem;
  font-weight:    600;
  padding:        0.32rem 0.85rem;
  border-radius:  6px;
  cursor:         pointer;
  border:         1px solid transparent;
  transition:     background 0.18s, border-color 0.18s, box-shadow 0.18s, opacity 0.18s;
  letter-spacing: 0.02em;
  white-space:    nowrap;
  flex-shrink:    0;
}

.orch-btn--preview {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.14), rgba(99, 102, 241, 0.1));
  border-color: rgba(16, 185, 129, 0.4);
  color: #6ee7b7;
}
.orch-btn--preview:hover:not(:disabled) {
  background:  linear-gradient(135deg, rgba(16, 185, 129, 0.26), rgba(99, 102, 241, 0.2));
  border-color: rgba(16, 185, 129, 0.7);
  box-shadow:  0 0 12px rgba(16, 185, 129, 0.22);
}
.orch-btn--loading,
.orch-btn--preview:disabled { opacity: 0.5; cursor: not-allowed; }

.orch-btn--ghost {
  background:   rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.25);
  color:        #f87171;
}
.orch-btn--ghost:hover {
  background:   rgba(239, 68, 68, 0.16);
  border-color: rgba(239, 68, 68, 0.5);
}

.orch-btn--cancel {
  background:   rgba(100, 116, 139, 0.1);
  border-color: rgba(100, 116, 139, 0.3);
  color:        #94a3b8;
}
.orch-btn--cancel:hover {
  background:   rgba(100, 116, 139, 0.2);
  border-color: rgba(100, 116, 139, 0.5);
  color:        #e2e8f0;
}

.orch-btn--confirm {
  display:     flex;
  align-items: center;
  gap:         0.45rem;
  background:  linear-gradient(135deg, #4f46e5, #6366f1);
  border-color: rgba(139, 92, 246, 0.5);
  color:        #ffffff;
  box-shadow:  0 0 16px rgba(99, 102, 241, 0.3);
}
.orch-btn--confirm:hover {
  background:  linear-gradient(135deg, #4338ca, #4f46e5);
  box-shadow:  0 0 22px rgba(99, 102, 241, 0.5);
}

.orch-confirm-count {
  background:    rgba(255, 255, 255, 0.2);
  border-radius: 10px;
  font-size:     0.68rem;
  padding:       0.05rem 0.4rem;
  font-weight:   700;
}

/* ── Template select ──────────────────────────────────────────────────────────── */
.orch-template-select {
  background:       linear-gradient(135deg, rgba(10, 18, 40, 0.95), rgba(30, 27, 75, 0.9));
  border:           1px solid rgba(99, 102, 241, 0.35);
  color:            #a5b4fc;
  font-size:        0.72rem;
  font-weight:      600;
  padding:          0.28rem 1.5rem 0.28rem 0.55rem;
  border-radius:    6px;
  cursor:           pointer;
  outline:          none;
  letter-spacing:   0.03em;
  -webkit-appearance: none;
  appearance:       none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236366f1'/%3E%3C/svg%3E");
  background-repeat:   no-repeat;
  background-position: right 0.45rem center;
  transition:       border-color 0.2s, box-shadow 0.2s;
}
.orch-template-select:hover { border-color: rgba(139, 92, 246, 0.65); }

/* ── Body ───────────────────────────────────────────────────────────────────── */
.orch-body {
  flex:           1;
  min-height:     0;
  display:        flex;
  flex-direction: column;
  overflow:       hidden;
}

/* ── Warehouse (top section) ────────────────────────────────────────────────── */
.orch-warehouse {
  flex:           0 0 46%;
  display:        flex;
  flex-direction: column;
  overflow:       hidden;
  border-bottom:  none;
}

/* ── Toolbar Row ─────────────────────────────────────────────────────────────── */
.orch-toolbar-row {
  display:     flex;
  align-items: center;
  gap:         0.75rem;
  padding:     0.55rem 1.25rem;
  border-bottom: 1px solid rgba(99, 102, 241, 0.1);
  flex-shrink: 0;
  background:  rgba(10, 15, 30, 0.6);
}

/* ── Tabs ────────────────────────────────────────────────────────────────────── */
.orch-tabs {
  display:     flex;
  gap:         0.25rem;
  flex-shrink: 0;
}

.orch-tab {
  background:     transparent;
  border:         1px solid transparent;
  color:          #64748b;
  font-size:      0.75rem;
  font-weight:    500;
  padding:        0.3rem 0.75rem;
  border-radius:  6px;
  cursor:         pointer;
  transition:     color 0.15s, background 0.15s, border-color 0.15s;
  white-space:    nowrap;
}
.orch-tab:hover       { color: #94a3b8; background: rgba(99, 102, 241, 0.06); }
.orch-tab--active     {
  color:        #a5b4fc !important;
  background:   rgba(99, 102, 241, 0.12) !important;
  border-color: rgba(99, 102, 241, 0.3) !important;
}

/* ── Search ─────────────────────────────────────────────────────────────────── */
.orch-search-wrap {
  flex:        1;
  display:     flex;
  align-items: center;
  gap:         0.4rem;
  background:  rgba(15, 23, 42, 0.8);
  border:      1px solid rgba(99, 102, 241, 0.2);
  border-radius: 8px;
  padding:     0.3rem 0.65rem;
  transition:  border-color 0.2s;
}
.orch-search-wrap:focus-within { border-color: rgba(99, 102, 241, 0.5); }

.orch-search-icon { font-size: 0.8rem; flex-shrink: 0; }

.orch-search-input {
  flex:        1;
  background:  transparent;
  border:      none;
  outline:     none;
  font-size:   0.8rem;
  color:       #e2e8f0;
  font-family: inherit;
}
.orch-search-input::placeholder { color: #475569; }

.orch-search-clear {
  background:    transparent;
  border:        none;
  color:         #475569;
  font-size:     0.7rem;
  cursor:        pointer;
  padding:       0.1rem 0.2rem;
  border-radius: 3px;
  flex-shrink:   0;
  transition:    color 0.12s;
}
.orch-search-clear:hover { color: #94a3b8; }

/* ── Tag filter strip ────────────────────────────────────────────────────────── */
.orch-tag-filter-row {
  display:    flex;
  align-items: center;
  gap:        0.4rem;
  padding:    0.4rem 1.25rem;
  overflow-x: auto;
  flex-shrink: 0;
  border-bottom: 1px solid rgba(99, 102, 241, 0.08);
  background: rgba(5, 10, 25, 0.4);
  scrollbar-width: none;
}
.orch-tag-filter-row::-webkit-scrollbar { display: none; }

.orch-filter-pill {
  flex-shrink:   0;
  display:       inline-flex;
  align-items:   center;
  justify-content: center;
  background:    transparent;
  border:        1px solid rgba(99, 102, 241, 0.2);
  color:         #64748b;
  font-size:     0.7rem;
  font-weight:   500;
  padding:       0.18rem 0.5rem;
  border-radius: 20px;
  cursor:        pointer;
  white-space:   nowrap;
  transition:    color 0.15s, background 0.15s, border-color 0.15s;
}
.orch-filter-pill .tag-pill { cursor: inherit; }
.orch-filter-pill:hover       { color: #94a3b8; border-color: rgba(99, 102, 241, 0.4); }
.orch-filter-pill--active     {
  background:   rgba(99, 102, 241, 0.18) !important;
  border-color: rgba(99, 102, 241, 0.55) !important;
  color:        #a5b4fc !important;
}

/* ── Scroll Area (common for grid + tag list) ────────────────────────────────── */
.orch-scroll-area {
  flex:       1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding:    0.9rem 1.25rem;
  scrollbar-width: thin;
  scrollbar-color: rgba(99, 102, 241, 0.2) transparent;
}
.orch-scroll-area::-webkit-scrollbar { width: 4px; }
.orch-scroll-area::-webkit-scrollbar-track { background: transparent; }
.orch-scroll-area::-webkit-scrollbar-thumb { background: rgba(99, 102, 241, 0.22); border-radius: 2px; }

.orch-empty {
  display:     flex;
  align-items: center;
  justify-content: center;
  height:      100px;
  color:       #334155;
  font-size:   0.8rem;
}

/* ── Asset Grid ──────────────────────────────────────────────────────────────── */
.orch-asset-grid {
  display:               grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap:                   0.65rem;
  align-content:         start;
}

.orch-asset-card {
  display:        flex;
  flex-direction: column;
  border-radius:  10px;
  border:         1px solid rgba(99, 102, 241, 0.12);
  background:     rgba(20, 30, 55, 0.5);
  overflow:       hidden;
  cursor:         grab;
  transition:     border-color 0.2s, background 0.2s, box-shadow 0.2s, transform 0.15s;
  user-select:    none;
}
.orch-asset-card:active { cursor: grabbing; }
.orch-asset-card:hover  {
  border-color: rgba(99, 102, 241, 0.4);
  background:   rgba(99, 102, 241, 0.08);
  transform:    translateY(-2px);
  box-shadow:   0 4px 16px rgba(0, 0, 0, 0.3);
}
.orch-asset-card--locked {
  border-color: rgba(167, 139, 250, 0.55) !important;
  background:   rgba(167, 139, 250, 0.08) !important;
  box-shadow:   0 0 10px rgba(167, 139, 250, 0.18);
}

.orch-asset-thumb {
  width:        100%;
  aspect-ratio: 16 / 9;
  background:   #000;
  overflow:     hidden;
  position:     relative;
  flex-shrink:  0;
}

.orch-asset-video {
  width:          100%;
  height:         100%;
  object-fit:     cover;
  -webkit-user-drag: none;
  pointer-events: none;
  display:        block;
}

.orch-lock-badge {
  position:   absolute;
  inset:      0;
  display:    flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
  font-size:  0.85rem;
}

.orch-asset-footer {
  padding:     0.4rem 0.5rem;
  display:     flex;
  align-items: center;
  gap:         0.3rem;
}

.orch-asset-name {
  flex:          1;
  min-width:     0;
  font-size:     0.68rem;
  color:         #94a3b8;
  white-space:   nowrap;
  overflow:      hidden;
  text-overflow: ellipsis;
}

.orch-asset-meta-pills {
  display:     flex;
  gap:         0.2rem;
  flex-shrink: 0;
}

.orch-use-badge {
  font-size:   0.6rem;
  padding:     0.05rem 0.28rem;
  border-radius: 3px;
  background:  rgba(99, 102, 241, 0.1);
  color:       #94a3b8;
  border:      1px solid rgba(99, 102, 241, 0.15);
}
.orch-use-badge--warn { color: #fca5a5; }

.orch-exhausted-badge {
  font-size:   0.6rem;
  padding:     0.05rem 0.28rem;
  border-radius: 3px;
  background:  rgba(239, 68, 68, 0.12);
  color:       #fca5a5;
  border:      1px solid rgba(239, 68, 68, 0.25);
}

/* ── Tag Grid ────────────────────────────────────────────────────────────────── */
.orch-tag-grid {
  display:        flex;
  flex-wrap:      wrap;
  gap:            0.5rem;
  align-content:  start;
}

.orch-tag-card {
  display:     flex;
  align-items: center;
  gap:         0.3rem;
  padding:     0.4rem 0.75rem;
  border-radius: 8px;
  border:      1px dashed rgba(167, 139, 250, 0.45);
  background:  rgba(139, 92, 246, 0.1);
  cursor:      grab;
  user-select: none;
  transition:  border-color 0.15s, background 0.15s;
}
.orch-tag-card:active { cursor: grabbing; }
.orch-tag-card:hover  {
  border-color: rgba(167, 139, 250, 0.75);
  background:   rgba(139, 92, 246, 0.2);
}

.orch-drag-pill {
  max-width:     100%;
  overflow:      hidden;
  text-overflow: ellipsis;
}

/* ── Divider ─────────────────────────────────────────────────────────────────── */
.orch-divider {
  flex-shrink:    0;
  height:         36px;
  display:        flex;
  align-items:    center;
  justify-content: center;
  background:     rgba(5, 10, 25, 0.7);
  border-top:     1px solid rgba(99, 102, 241, 0.15);
  border-bottom:  1px solid rgba(99, 102, 241, 0.15);
}

.orch-divider-label {
  font-size:      0.68rem;
  font-weight:    600;
  color:          #475569;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

/* ── Trackline (bottom section) ──────────────────────────────────────────────── */
.orch-trackline {
  flex:       1;
  min-height: 0;
  display:    flex;
  flex-direction: column;
  overflow:   hidden;
}

.orch-tracks-scroll {
  flex:       1;
  min-height: 0;
  overflow-x: auto;
  overflow-y: auto;
  padding:    0.85rem 1.25rem;
  scrollbar-width: thin;
  scrollbar-color: rgba(99, 102, 241, 0.2) transparent;
}
.orch-tracks-scroll::-webkit-scrollbar { height: 4px; width: 4px; }
.orch-tracks-scroll::-webkit-scrollbar-thumb { background: rgba(99, 102, 241, 0.22); border-radius: 2px; }

.orch-tracks-row {
  display:    flex;
  flex-direction: row;
  gap:        0.75rem;
  min-height: 100%;
  height:     100%;
}

/* ── Individual Track ────────────────────────────────────────────────────────── */
.orch-track {
  flex:           1;
  min-width:      180px;
  max-width:      280px;
  display:        flex;
  flex-direction: column;
  border-radius:  10px;
  border:         1px solid rgba(99, 102, 241, 0.12);
  background:     rgba(10, 18, 36, 0.5);
  overflow:       hidden;
}

.orch-track--hook { border-top: 3px solid #f59e0b; }
.orch-track--body { border-top: 3px solid #6366f1; }
.orch-track--cta  { border-top: 3px solid #f43f5e; }

.orch-track-label {
  display:      flex;
  align-items:  center;
  justify-content: space-between;
  padding:      0.55rem 0.75rem 0.4rem;
  flex-shrink:  0;
}

.orch-track-name {
  font-size:      0.75rem;
  font-weight:    700;
  letter-spacing: 0.03em;
}
.orch-track--hook .orch-track-name { color: #fcd34d; }
.orch-track--body .orch-track-name { color: #a5b4fc; }
.orch-track--cta  .orch-track-name { color: #fb7185; }

.orch-track-count {
  font-size:     0.65rem;
  font-weight:   600;
  padding:       0.08rem 0.38rem;
  border-radius: 10px;
  background:    rgba(99, 102, 241, 0.18);
  color:         #818cf8;
  border:        1px solid rgba(99, 102, 241, 0.3);
}

/* Drop zone */
.orch-track-drop {
  flex:           1;
  min-height:     100px;
  padding:        0.4rem 0.5rem 0.5rem;
  display:        flex;
  flex-direction: column;
  gap:            0.4rem;
  transition:     background 0.15s;
}
.orch-track-drop--filled { background: rgba(99, 102, 241, 0.04); }

.orch-track-empty {
  flex:            1;
  display:         flex;
  flex-direction:  column;
  align-items:     center;
  justify-content: center;
  gap:             0.3rem;
  border:          1.5px dashed rgba(99, 102, 241, 0.18);
  border-radius:   8px;
  color:           #334155;
  font-size:       0.68rem;
  text-align:      center;
  line-height:     1.5;
  pointer-events:  none;
  padding:         0.75rem;
}
.orch-track-empty-icon {
  font-size: 1.2rem;
  opacity:   0.4;
}

/* ── Block Card ─────────────────────────────────────────────────────────────── */
.orch-block {
  display:        flex;
  align-items:    center;
  gap:            0.35rem;
  padding:        0.35rem 0.4rem;
  border-radius:  7px;
  background:     rgba(30, 41, 59, 0.75);
  border:         1px solid rgba(99, 102, 241, 0.22);
  cursor:         grab;
  transition:     border-color 0.15s, background 0.15s, box-shadow 0.15s;
  overflow:       hidden;
  flex-shrink:    0;
}
.orch-block:active { cursor: grabbing; }
.orch-block:hover  {
  border-color: rgba(99, 102, 241, 0.5);
  background:   rgba(99, 102, 241, 0.1);
  box-shadow:   0 2px 8px rgba(0, 0, 0, 0.3);
}

.orch-block--tag {
  border:     1px dashed rgba(167, 139, 250, 0.55) !important;
  background: rgba(139, 92, 246, 0.15) !important;
}
.orch-block--tag:hover {
  border-color: rgba(167, 139, 250, 0.85) !important;
  background:   rgba(139, 92, 246, 0.28) !important;
}

.orch-block-thumb {
  width:          44px;
  height:         32px;
  object-fit:     cover;
  border-radius:  4px;
  flex-shrink:    0;
  background:     #000;
  -webkit-user-drag: none;
  pointer-events: none;
}

.orch-block-name {
  flex:          1;
  min-width:     0;
  font-size:     0.68rem;
  color:         #94a3b8;
  white-space:   nowrap;
  overflow:      hidden;
  text-overflow: ellipsis;
}

.orch-block-pill {
  flex:          1;
  min-width:     0;
  font-size:     0.62rem;
  white-space:   nowrap;
  overflow:      hidden;
  text-overflow: ellipsis;
}

.orch-block-remove {
  background:    transparent;
  border:        none;
  color:         #475569;
  font-size:     0.65rem;
  cursor:        pointer;
  padding:       0.12rem 0.18rem;
  border-radius: 3px;
  flex-shrink:   0;
  line-height:   1;
  transition:    color 0.12s, background 0.12s;
}
.orch-block-remove:hover {
  color:       #f87171;
  background:  rgba(239, 68, 68, 0.12);
}

/* ── Preview Modal ───────────────────────────────────────────────────────────── */
.preview-modal-backdrop {
  position:        fixed;
  inset:           0;
  background:      rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(4px);
  z-index:         2000;
  display:         flex;
  align-items:     center;
  justify-content: center;
  padding:         1.5rem;
}

.preview-modal {
  width:       min(840px, 100%);
  max-height:  84vh;
  background:  #0d1117;
  border:      1px solid rgba(16, 185, 129, 0.35);
  border-radius: 10px;
  box-shadow:  0 0 48px rgba(16, 185, 129, 0.1), 0 24px 64px rgba(0, 0, 0, 0.65);
  display:     flex;
  flex-direction: column;
  overflow:    hidden;
}

.preview-modal-header {
  display:     flex;
  align-items: center;
  flex-wrap:   wrap;
  gap:         0.6rem;
  padding:     0.75rem 1.1rem;
  border-bottom: 1px solid rgba(16, 185, 129, 0.18);
  flex-shrink: 0;
  background:  rgba(16, 185, 129, 0.04);
}

.preview-modal-title {
  font-size:      0.82rem;
  font-weight:    700;
  color:          #6ee7b7;
  letter-spacing: 0.04em;
  flex:           1;
}

.preview-modal-badges { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }

.prev-badge {
  font-size:      0.62rem;
  font-weight:    600;
  padding:        0.12rem 0.45rem;
  border-radius:  20px;
  letter-spacing: 0.03em;
}
.prev-badge--engine { background: rgba(99, 102, 241, 0.15); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.3); }
.prev-badge--ok     { background: rgba(16, 185, 129, 0.12); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.3); }
.prev-badge--warn   { background: rgba(245, 158, 11, 0.12); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.3); }

.preview-modal-body {
  flex:       1;
  overflow-y: auto;
  padding:    0.75rem 1.1rem;
}
.preview-modal-body::-webkit-scrollbar       { width: 5px; }
.preview-modal-body::-webkit-scrollbar-thumb { background: rgba(16, 185, 129, 0.28); border-radius: 3px; }

.preview-pre {
  margin:      0;
  padding:     1rem 1.25rem;
  background:  #1e1e1e;
  border:      1px solid rgba(16, 185, 129, 0.15);
  border-radius: 7px;
  color:       #10b981;
  font-family: 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  font-size:   0.72rem;
  line-height: 1.65;
  white-space: pre;
  overflow-x:  auto;
}

.preview-modal-footer {
  display:         flex;
  justify-content: flex-end;
  padding:         0.65rem 1.1rem;
  border-top:      1px solid rgba(16, 185, 129, 0.15);
  flex-shrink:     0;
  background:      rgba(13, 17, 23, 0.8);
}

.preview-close-btn {
  background:  rgba(16, 185, 129, 0.1);
  border:      1px solid rgba(16, 185, 129, 0.4);
  color:       #6ee7b7;
  font-size:   0.72rem;
  font-weight: 600;
  cursor:      pointer;
  padding:     0.3rem 1.1rem;
  border-radius: 5px;
  transition:  background 0.15s, box-shadow 0.15s;
}
.preview-close-btn:hover {
  background: rgba(16, 185, 129, 0.22);
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.2);
}

/* modal fade */
.modal-fade-enter-active, .modal-fade-leave-active { transition: opacity 0.22s ease; }
.modal-fade-enter-from, .modal-fade-leave-to       { opacity: 0; }

/* ── Asset Type Filter Row ───────────────────────────────────────────────────── */
.orch-type-filter-row {
  display:         flex;
  align-items:     center;
  gap:             0.3rem;
  padding:         0.32rem 1.25rem;
  overflow-x:      auto;
  flex-shrink:     0;
  background:      rgba(5, 10, 25, 0.55);
  border-bottom:   1px solid rgba(99, 102, 241, 0.1);
  scrollbar-width: none;
}
.orch-type-filter-row::-webkit-scrollbar { display: none; }

.orch-type-pill {
  flex-shrink:   0;
  background:    transparent;
  border:        1px solid rgba(99, 102, 241, 0.18);
  color:         #475569;
  font-size:     0.67rem;
  font-weight:   600;
  padding:       0.18rem 0.58rem;
  border-radius: 20px;
  cursor:        pointer;
  white-space:   nowrap;
  transition:    color 0.15s, background 0.15s, border-color 0.15s, box-shadow 0.15s;
}
.orch-type-pill:hover {
  color:        #94a3b8;
  border-color: rgba(99, 102, 241, 0.35);
}
.orch-type-pill--active {
  background:   rgba(56, 189, 248, 0.12) !important;
  border-color: rgba(56, 189, 248, 0.5)  !important;
  color:        #7dd3fc !important;
  box-shadow:   0 0 8px rgba(56, 189, 248, 0.15);
}

/* ── Multi-modal asset thumbs ────────────────────────────────────────────────── */
.orch-asset-image {
  width:          100%;
  height:         100%;
  object-fit:     cover;
  -webkit-user-drag: none;
  pointer-events: none;
  display:        block;
}

.orch-asset-icon-thumb {
  width:           100%;
  height:          100%;
  display:         flex;
  align-items:     center;
  justify-content: center;
  font-size:       1.9rem;
  background:      rgba(15, 23, 42, 0.65);
}
.orch-asset-icon-thumb--audio_bgm { background: rgba(99,  102, 241, 0.08); }
.orch-asset-icon-thumb--sfx       { background: rgba(56,  189, 248, 0.08); }
.orch-asset-icon-thumb--vfx       { background: rgba(139,  92, 246, 0.08); }

/* ── Block track: image / icon thumbs ───────────────────────────────────────── */
.orch-block-thumb--img {
  object-fit:        cover;
  -webkit-user-drag: none;
  pointer-events:    none;
}

.orch-block-icon-thumb {
  width:           44px;
  height:          32px;
  border-radius:   4px;
  flex-shrink:     0;
  background:      rgba(15, 23, 42, 0.8);
  display:         flex;
  align-items:     center;
  justify-content: center;
  font-size:       0.95rem;
}

/* ── Faceted Tag Sections ────────────────────────────────────────────────────── */
.orch-facet-section          { margin-bottom: 1.1rem; }
.orch-facet-section:last-child { margin-bottom: 0; }

.orch-facet-header {
  display:         flex;
  align-items:     center;
  justify-content: space-between;
  font-size:       0.63rem;
  font-weight:     700;
  letter-spacing:  0.07em;
  text-transform:  uppercase;
  padding:         0 0.1rem 0.28rem;
  border-bottom:   1px solid;
  margin-bottom:   0.45rem;
}

.orch-facet-header--purple { color: #a78bfa; border-color: rgba(139,  92, 246, 0.3); }
.orch-facet-header--green  { color: #34d399; border-color: rgba( 16, 185, 129, 0.3); }
.orch-facet-header--sky    { color: #38bdf8; border-color: rgba( 56, 189, 248, 0.3); }
.orch-facet-header--amber  { color: #fbbf24; border-color: rgba(245, 158,  11, 0.3); }
.orch-facet-header--orange { color: #fb923c; border-color: rgba(251, 146,  60, 0.35); }
.orch-facet-header--rose   { color: #fb7185; border-color: rgba(244, 114, 182, 0.35); }
.orch-facet-header--indigo { color: #818cf8; border-color: rgba( 99, 102, 241, 0.25); }

.orch-facet-count {
  font-size:     0.6rem;
  font-weight:   700;
  padding:       0.05rem 0.38rem;
  border-radius: 10px;
  background:    currentColor;
  color:         #060c1a;
  opacity:       0.85;
}

/* Facet-tinted tag cards — micro-glow borders per face */
.orch-tag-card--purple {
  border-color: rgba(139, 92, 246, 0.55) !important;
  box-shadow:   0 0 7px rgba(139, 92, 246, 0.2);
}
.orch-tag-card--purple:hover { border-color: rgba(167, 139, 250, 0.85) !important; }

.orch-tag-card--green {
  border-color: rgba(16, 185, 129, 0.5) !important;
  box-shadow:   0 0 7px rgba(16, 185, 129, 0.18);
}
.orch-tag-card--green:hover { border-color: rgba(52, 211, 153, 0.8) !important; }

.orch-tag-card--sky {
  border-color: rgba(56, 189, 248, 0.5) !important;
  box-shadow:   0 0 7px rgba(56, 189, 248, 0.18);
}
.orch-tag-card--sky:hover { border-color: rgba(125, 211, 252, 0.8) !important; }

.orch-tag-card--amber {
  border-color: rgba(245, 158, 11, 0.5) !important;
  box-shadow:   0 0 7px rgba(245, 158, 11, 0.18);
}
.orch-tag-card--amber:hover { border-color: rgba(251, 191, 36, 0.8) !important; }

.orch-tag-card--orange {
  border-color: rgba(251, 146, 60, 0.5) !important;
  box-shadow:   0 0 7px rgba(251, 146, 60, 0.18);
}
.orch-tag-card--orange:hover { border-color: rgba(253, 186, 116, 0.85) !important; }

.orch-tag-card--rose {
  border-color: rgba(244, 114, 182, 0.45) !important;
  box-shadow:   0 0 7px rgba(244, 114, 182, 0.16);
}
.orch-tag-card--rose:hover { border-color: rgba(251, 207, 232, 0.85) !important; }

.orch-tag-card--indigo { border-color: rgba(99, 102, 241, 0.4) !important; }

/* ════════════════════════════════════════════════════════════
   Phase 8.7 — 底模母槽 (Master Track) + 插槽动态裂变
   ════════════════════════════════════════════════════════════ */

/* ── 母槽外壳 ─────────────────────────────────────────────── */
.master-zone {
  flex-shrink:     0;
  margin:          0.65rem 1.25rem 0;
  border-radius:   10px;
  border:          1.5px dashed rgba(236, 72, 153, 0.35);
  background:      rgba(236, 72, 153, 0.04);
  transition:      border-color 0.25s, background 0.25s, box-shadow 0.25s;
  overflow:        hidden;
}
.master-zone--loaded {
  border-style:  solid;
  border-color:  rgba(236, 72, 153, 0.55);
  background:    rgba(236, 72, 153, 0.06);
  box-shadow:    0 0 24px rgba(236, 72, 153, 0.12), inset 0 0 20px rgba(236, 72, 153, 0.04);
}

/* ── 母槽标题行 ────────────────────────────────────────────── */
.master-zone-header {
  display:      flex;
  align-items:  center;
  gap:          0.5rem;
  padding:      0.45rem 0.85rem 0.4rem;
  border-bottom: 1px solid rgba(236, 72, 153, 0.12);
  flex-shrink:  0;
}
.master-zone-icon {
  font-size:   0.95rem;
  filter:      drop-shadow(0 0 6px rgba(236, 72, 153, 0.6));
  flex-shrink: 0;
}
.master-zone-title {
  font-size:      0.75rem;
  font-weight:    700;
  color:          #f9a8d4;
  letter-spacing: 0.04em;
  flex:           1;
}
.master-zone-eng {
  font-size:   0.62rem;
  font-family: 'JetBrains Mono', monospace;
  color:       rgba(249, 168, 212, 0.55);
  font-weight: 500;
  margin-left: 0.35rem;
  letter-spacing: 0.05em;
}
.master-zone-badge {
  font-size:     0.62rem;
  font-weight:   700;
  padding:       0.12rem 0.5rem;
  border-radius: 20px;
  background:    rgba(236, 72, 153, 0.18);
  border:        1px solid rgba(236, 72, 153, 0.45);
  color:         #f472b6;
  animation:     master-badge-glow 2.5s ease-in-out infinite;
}
@keyframes master-badge-glow {
  0%, 100% { box-shadow: 0 0 0   rgba(236, 72, 153, 0); }
  50%       { box-shadow: 0 0 10px rgba(236, 72, 153, 0.4); }
}
.master-unload-btn {
  background:    rgba(239, 68, 68, 0.08);
  border:        1px solid rgba(239, 68, 68, 0.2);
  color:         #fca5a5;
  font-size:     0.62rem;
  font-weight:   600;
  padding:       0.18rem 0.55rem;
  border-radius: 5px;
  cursor:        pointer;
  white-space:   nowrap;
  flex-shrink:   0;
  transition:    background 0.15s, border-color 0.15s;
}
.master-unload-btn:hover {
  background:  rgba(239, 68, 68, 0.18);
  border-color: rgba(239, 68, 68, 0.45);
}

/* ── 空投放区 ──────────────────────────────────────────────── */
.master-drop-zone {
  padding: 0.55rem 0.85rem 0.6rem;
  min-height: 56px;
}
.master-drop-zone--hidden { display: none; }

.master-empty-hint {
  display:     flex;
  align-items: center;
  gap:         0.75rem;
  padding:     0.35rem 0.25rem;
}
.master-empty-icon {
  font-size:   1.6rem;
  opacity:     0.45;
  flex-shrink: 0;
  animation:   master-icon-float 3.5s ease-in-out infinite;
}
@keyframes master-icon-float {
  0%, 100% { transform: translateY(0); }
  50%       { transform: translateY(-3px); }
}
.master-empty-title {
  font-size:   0.75rem;
  font-weight: 600;
  color:       #94a3b8;
  line-height: 1.4;
}
.master-empty-sub {
  font-size:  0.62rem;
  color:      #475569;
  margin-top: 0.15rem;
  font-family: 'JetBrains Mono', monospace;
}

/* ── 已装载区域 ─────────────────────────────────────────────── */
.master-loaded-area {
  padding:        0.5rem 0.85rem 0.65rem;
  display:        flex;
  flex-direction: column;
  gap:            0.5rem;
}

/* ── 底模资产芯片 ──────────────────────────────────────────── */
.master-asset-chip {
  display:       flex;
  align-items:   center;
  gap:           0.45rem;
  background:    rgba(236, 72, 153, 0.1);
  border:        1px solid rgba(236, 72, 153, 0.35);
  border-radius: 7px;
  padding:       0.3rem 0.65rem;
}
.master-asset-icon { font-size: 0.9rem; flex-shrink: 0; }
.master-asset-name {
  flex:          1;
  min-width:     0;
  font-size:     0.72rem;
  font-weight:   600;
  color:         #f9a8d4;
  white-space:   nowrap;
  overflow:      hidden;
  text-overflow: ellipsis;
}
.master-asset-hash {
  font-size:   0.6rem;
  font-family: 'JetBrains Mono', monospace;
  color:       rgba(249, 168, 212, 0.5);
  flex-shrink: 0;
  letter-spacing: 0.03em;
}
.master-layer-chip {
  font-size:     0.58rem;
  font-family:   'JetBrains Mono', monospace;
  font-weight:   700;
  color:         #ec4899;
  background:    rgba(236, 72, 153, 0.14);
  border:        1px solid rgba(236, 72, 153, 0.3);
  border-radius: 4px;
  padding:       0.05rem 0.4rem;
  flex-shrink:   0;
  letter-spacing: 0.04em;
}

/* ── 插槽裂变横排 ──────────────────────────────────────────── */
.slot-fission-row {
  display:    flex;
  flex-wrap:  wrap;
  gap:        0.45rem;
}

/* ── 单个插槽格 ────────────────────────────────────────────── */
.slot-cell {
  flex:           1 1 140px;
  max-width:      220px;
  display:        flex;
  flex-direction: column;
  gap:            0.3rem;
  border-radius:  8px;
  border:         1.5px dashed;
  padding:        0.4rem 0.55rem 0.45rem;
  transition:     border-color 0.2s, background 0.2s, box-shadow 0.2s;
  animation:      slot-cell-appear 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

@keyframes slot-cell-appear {
  from { opacity: 0; transform: translateY(8px) scale(0.94); }
  to   { opacity: 1; transform: translateY(0)   scale(1); }
}

/* 色彩主题 */
.slot-cell--purple { border-color: rgba(192, 132, 252, 0.45); background: rgba(192, 132, 252, 0.05); }
.slot-cell--amber  { border-color: rgba(251, 191,  36, 0.45); background: rgba(251, 191,  36, 0.05); }
.slot-cell--sky    { border-color: rgba( 56, 189, 248, 0.45); background: rgba( 56, 189, 248, 0.05); }
.slot-cell--green  { border-color: rgba( 74, 222, 128, 0.45); background: rgba( 74, 222, 128, 0.05); }
.slot-cell--rose   { border-color: rgba(236,  72, 153, 0.45); background: rgba(236,  72, 153, 0.05); }

/* 已绑定：边框实线 + 发光 */
.slot-cell--bound.slot-cell--purple { border-style: solid; box-shadow: 0 0 10px rgba(192, 132, 252, 0.2); }
.slot-cell--bound.slot-cell--amber  { border-style: solid; box-shadow: 0 0 10px rgba(251, 191,  36, 0.2); }
.slot-cell--bound.slot-cell--sky    { border-style: solid; box-shadow: 0 0 10px rgba( 56, 189, 248, 0.2); }
.slot-cell--bound.slot-cell--green  { border-style: solid; box-shadow: 0 0 10px rgba( 74, 222, 128, 0.2); }
.slot-cell--bound.slot-cell--rose   { border-style: solid; box-shadow: 0 0 10px rgba(236,  72, 153, 0.2); }

/* ── 插槽格头部 ────────────────────────────────────────────── */
.slot-cell-header {
  display:     flex;
  align-items: center;
  gap:         0.3rem;
}
.slot-cell-key {
  font-size:      0.62rem;
  font-family:    'JetBrains Mono', monospace;
  font-weight:    700;
  letter-spacing: 0.04em;
  flex:           1;
  min-width:      0;
  overflow:       hidden;
  text-overflow:  ellipsis;
  white-space:    nowrap;
}
.slot-cell--purple .slot-cell-key { color: #c084fc; }
.slot-cell--amber  .slot-cell-key { color: #fbbf24; }
.slot-cell--sky    .slot-cell-key { color: #38bdf8; }
.slot-cell--green  .slot-cell-key { color: #4ade80; }
.slot-cell--rose   .slot-cell-key { color: #f472b6; }

.slot-cell-accepts {
  font-size:     0.55rem;
  color:         #475569;
  font-family:   'JetBrains Mono', monospace;
  white-space:   nowrap;
  flex-shrink:   0;
}
.slot-unbind-btn {
  background:    none;
  border:        none;
  color:         #475569;
  font-size:     0.6rem;
  cursor:        pointer;
  padding:       0.05rem 0.2rem;
  border-radius: 3px;
  flex-shrink:   0;
  line-height:   1;
  transition:    color 0.12s, background 0.12s;
}
.slot-unbind-btn:hover { color: #f87171; background: rgba(239, 68, 68, 0.1); }

/* ── 插槽空投放区 ──────────────────────────────────────────── */
.slot-drop-zone {
  flex:           1;
  min-height:     36px;
  border-radius:  5px;
  display:        flex;
  align-items:    center;
}
.slot-empty-label {
  display:     flex;
  align-items: center;
  gap:         0.3rem;
  font-size:   0.62rem;
  color:       #334155;
  font-style:  italic;
  padding:     0.2rem 0.1rem;
  pointer-events: none;
}
.slot-empty-icon { font-size: 0.75rem; opacity: 0.5; }

/* ── 插槽已绑定内容 ─────────────────────────────────────────── */
.slot-bound-content {
  display:       flex;
  align-items:   center;
  gap:           0.3rem;
  background:    rgba(2, 8, 23, 0.45);
  border-radius: 5px;
  padding:       0.22rem 0.4rem;
  overflow:      hidden;
}
.slot-bound-icon { font-size: 0.75rem; flex-shrink: 0; }
.slot-bound-name {
  flex:          1;
  min-width:     0;
  font-size:     0.62rem;
  color:         #94a3b8;
  white-space:   nowrap;
  overflow:      hidden;
  text-overflow: ellipsis;
}
.slot-bound-hash {
  font-size:   0.55rem;
  font-family: 'JetBrains Mono', monospace;
  color:       #334155;
  flex-shrink: 0;
  letter-spacing: 0.02em;
}

/* ── 无插槽清单提示 ─────────────────────────────────────────── */
.no-manifest-hint {
  font-size:   0.65rem;
  color:       #475569;
  font-style:  italic;
  padding:     0.25rem 0.1rem;
}
.no-manifest-hint code {
  font-family: 'JetBrains Mono', monospace;
  color:       #64748b;
  font-style:  normal;
  font-size:   0.6rem;
}

/* ── 裂变展开动画 ──────────────────────────────────────────── */
.fission-expand-enter-active {
  transition: all 0.38s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.fission-expand-leave-active { transition: all 0.2s ease; }
.fission-expand-enter-from   { opacity: 0; transform: translateY(-8px) scale(0.97); }
.fission-expand-leave-to     { opacity: 0; transform: translateY(-4px) scale(0.98); }

/* ── orch-asset-icon-thumb scene_master 专属底色 ─────────────── */
.orch-asset-icon-thumb--scene_master { background: rgba(236, 72, 153, 0.1); }
</style>
