<script setup>
import { ref, computed, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { useAppStore }         from '../stores/appStore'
import { ASSET_REGISTRY as ASSET_REGISTRY_MAP } from '../utils/assetConfig.js'
import { useQueueStore }       from '../stores/useQueueStore'
import QueueView               from './QueueView.vue'
import DslOrchestratorDrawer   from './DslOrchestratorDrawer.vue'
import VideoDetailDrawer       from './VideoDetailDrawer.vue'

const router     = useRouter()
const store      = useAppStore()
const queueStore = useQueueStore()

// ── 沉浸式详情抽屉（零路由跳转，父页面状态完全保留）──────────────────────
const activeDetailHash = ref('')

// ── @ 唤醒智能词典 (Phase 9.3) ─────────────────────────────────────────────
const omniTextareaRef  = ref(null)
const showMentionMenu  = ref(false)
const mentionKeyword   = ref('')
const cursorPosition   = ref(0)

const availableTags = computed(() => {
  const seen = new Set()
  const result = []
  for (const asset of dbAssetList.value) {
    const tags = asset?.tags
    if (!Array.isArray(tags)) continue
    for (const t of tags) {
      if (t == null || String(t).trim() === '') continue
      const lower = String(t).trim().toLowerCase()
      if (!seen.has(lower)) {
        seen.add(lower)
        result.push(lower)
      }
    }
  }
  return result.sort()
})

const filteredTags = computed(() => {
  const kw = mentionKeyword.value.trim().toLowerCase()
  if (!kw) return availableTags.value
  return availableTags.value.filter(tag => tag.includes(kw))
})

function handleInput(e) {
  const el = e.target
  const pos = el.selectionStart ?? 0
  cursorPosition.value = pos
  const before = omniPrompt.value.slice(0, pos)
  const match = before.match(/(^|\s)@([^ \n]*)$/)
  if (match) {
    showMentionMenu.value = true
    mentionKeyword.value = match[2] ?? ''
  } else {
    showMentionMenu.value = false
    mentionKeyword.value = ''
  }
}

function selectTag(tag) {
  const text = omniPrompt.value
  const pos = cursorPosition.value
  const before = text.slice(0, pos)
  const after = text.slice(pos)
  const match = before.match(/(^|\s)@([^ \n]*)$/)
  if (!match) {
    showMentionMenu.value = false
    return
  }
  const atStart = match.index + match[1].length
  const label = tag.replace(/^#/, '')
  const insert = `@${label} `
  const newBefore = text.slice(0, atStart) + insert
  omniPrompt.value = newBefore + after
  showMentionMenu.value = false
  mentionKeyword.value = ''
  const newCursor = newBefore.length
  nextTick(() => {
    const el = omniTextareaRef.value
    if (!el) return
    el.focus()
    el.setSelectionRange(newCursor, newCursor)
    cursorPosition.value = newCursor
  })
}

// ── 硬约束标签剥离器 (Phase 9.3.7) ─────────────────────────────────────────
/**
 * 从原始文本中剥离所有 @tag 硬指令，返回净化后的纯文本与标签数组。
 * 例如："帮我写个脚本 @bgm:燃向 @style:快剪" →
 *   { pureText: "帮我写个脚本", hardTags: ["bgm:燃向", "style:快剪"] }
 */
function extractHardTags(rawText) {
  const hardTags = []
  const TAG_RE = /(?:^|(?<=\s))@([^\s@]+)/g
  let pureText = rawText.replace(TAG_RE, (_, tag) => {
    hardTags.push(tag)
    return ''
  })
  pureText = pureText.replace(/\s{2,}/g, ' ').trim()
  return { pureText, hardTags }
}

// ── Omnibox form state ──────────────────────────────────────────────────────
const omniPrompt      = ref('')
const scriptMode      = ref('auto')
const omniPlaceholder = computed(() =>
  scriptMode.value === 'rewrite'
    ? '粘贴您的核心营销文案全文。AI 将在保持卖点绝对不变的前提下，为您裂变出 N 个语气不同的变体文案，完美规避 TikTok 音频查重...'
    : '描述你想生成的视频内容，如：汽车减震器出海，强调极其耐用，适合中东路况...'
)
const batchSize      = ref(1)
const aspectRatio    = ref('9:16')
const testLanguage   = ref('en')
const targetDuration = ref(15)
const enableTts      = ref(true)
const enableSubtitles = ref(true)

// ── DB 素材列表（真相源：后端 API）──────────────────────────────────────────
const dbAssetList = ref([])

// 全域资产注册表：从 assetConfig.js SSOT 动态读取，确保新增类型自动被纳入
const ASSET_REGISTRY = Object.keys(ASSET_REGISTRY_MAP)

async function fetchDbAssets() {
  try {
    const results = await Promise.all(
      ASSET_REGISTRY.map(type =>
        axios.get(`${store.API_BASE}/api/v1/assets?asset_type=${type}`)
          .then(r => r.data)
          .catch(() => [])
      )
    )
    dbAssetList.value = results.flat()
  } catch (err) {
    store.showToast('⚠️ 素材库加载失败：' + (err.response?.data?.detail || err.message))
  }
}

onMounted(fetchDbAssets)

// ── 业务引擎模板系统 ────────────────────────────────────────────────────────
const dslTemplates = {
  content: [
    { id: 'hook',    name: '👑 Hook',    role: 'hook' },
    { id: 'context', name: '📖 Context', role: 'body' },
    { id: 'build',   name: '🛠️ Build',   role: 'body' },
    { id: 'reveal',  name: '✨ Reveal',  role: 'body' },
    { id: 'cta',     name: '🎯 CTA',     role: 'cta'  },
  ],
  ua: [
    { id: 'problem',  name: '💥 Problem',  role: 'hook' },
    { id: 'failure',  name: '💀 Failure',  role: 'body' },
    { id: 'near_win', name: '📈 Near Win', role: 'body' },
    { id: 'reward',   name: '🏆 Reward',   role: 'cta'  },
  ],
}

const currentTemplate = ref('content')

// ── Story DSL 轨道状态（规范数据层，由抽屉写入）────────────────────────────
const dslTracks = ref(dslTemplates.content.map(t => ({
  ...t,
  items: [],
  script_text: '',
  visual_script: '',
  emotion: '',
})))
const draftMeta = ref(null)

// ── 抽屉控制 ────────────────────────────────────────────────────────────────
const showOrchestrator = ref(false)

function onOrchestratorConfirm({ tracks, template, directRender, params, meta }) {
  dslTracks.value = tracks
  currentTemplate.value = template
  draftMeta.value = meta ?? draftMeta.value

  // 将战术舱局部参数回写全局状态，override 工具栏中的值
  if (params) {
    batchSize.value       = params.batchSize
    aspectRatio.value     = params.aspectRatio
    testLanguage.value    = params.language
    enableTts.value       = params.enableTts
    enableSubtitles.value = params.enableSubtitles
  }

  if (directRender) {
    import('vue').then(({ nextTick }) => {
      nextTick(() => { blindFission() })
    })
  }
}

// ── 已装填积木总数（用于 Badge 气泡）──────────────────────────────────────
const stagedBlockCount = computed(() =>
  dslTracks.value.reduce((sum, t) => sum + t.items.length, 0)
)

// ── 兼容层：lockedAssetHashes（作战状态栏 & 发送按钮样式）────────────────
const lockedAssetHashes = computed(() => {
  const seen = new Set()
  for (const track of dslTracks.value)
    for (const item of track.items)
      if (item.hash) seen.add(item.hash)
  return [...seen]
})

// ── 提交条件 ────────────────────────────────────────────────────────────────
const isSubmitting = ref(false)
const isDrafting   = ref(false)
const isEnhancing  = ref(false)

const canFission = computed(() => {
  const hasPrompt = omniPrompt.value.trim().length > 0
  const hasBlocks = dslTracks.value.some(t => t.items.length > 0)
  return !isSubmitting.value && !isDrafting.value && (hasPrompt || hasBlocks)
})

/** 将 draft-blueprint 返回的 timeline 行映射到当前模板轨道的 items（战术板 semantic_tag） */
function applyBlueprintTimelineToTracks(apiTimeline) {
  const rows = Array.isArray(apiTimeline) ? apiTimeline : []
  dslTracks.value = dslTracks.value.map((track, index) => {
    // 用索引直接对位：LLM 的 beat 字段是自由文本，不做字符串匹配
    const row = rows[index]
    if (!row || !Array.isArray(row.semantic_tags)) {
      return {
        ...track,
        items: [],
        script_text: '',
        visual_script: '',
        emotion: '',
      }
    }

    const base = Date.now()
    const items = row.semantic_tags
      .map(t => (t == null ? '' : String(t).trim()))
      .filter(Boolean)
      .map((tag, idx) => ({
        uuid: `tag_${base}_${index}_${idx}_${Math.random().toString(36).slice(2, 9)}`,
        type: 'semantic_tag',
        tag,
      }))
    return {
      ...track,
      items,
      script_text: row.script_text || '',
      visual_script: row.visual_script || '',
      emotion: row.emotion || '',
    }
  })
}

async function enhancePrompt() {
  const prompt = omniPrompt.value.trim()
  if (!prompt || isEnhancing.value) return

  isEnhancing.value = true
  store.showToast('⏳ 正在召唤大模型进行魔法扩写，请稍候...')
  try {
    const resp = await axios.post(`${store.API_BASE}/api/v1/tasks/enhance-prompt`, {
      prompt,
      available_tags: availableTags.value,
    })
    const enhanced = resp.data?.enhanced_prompt
    if (enhanced && String(enhanced).trim()) {
      omniPrompt.value = String(enhanced).trim() + ' '
      showMentionMenu.value = false
      store.showToast('✨ 魔法扩写完成')
    } else {
      store.showToast('⚠️ 扩写结果为空，请重试')
    }
  } catch (err) {
    const raw    = err.response?.data?.detail
    const detail = Array.isArray(raw)
      ? raw.map(e => e.msg ?? JSON.stringify(e)).join('；')
      : (typeof raw === 'string' ? raw : (err.message ?? '未知错误'))
    store.showToast(`[${err.response?.status ?? 'ERR'}] 魔法扩写失败：${detail}`)
  } finally {
    isEnhancing.value = false
  }
}

async function draftBlueprint() {
  const raw = omniPrompt.value.trim()
  if (!raw) {
    store.showToast('⚠️ 请先填写提示词，再发起智能起草')
    return
  }
  if (isDrafting.value) return

  const { pureText, hardTags } = extractHardTags(raw)

  isDrafting.value = true
  try {
    const resp = await axios.post(
      `${store.API_BASE}/api/v1/tasks/draft-blueprint`,
      {
        prompt:          pureText || raw,
        mode:            scriptMode.value,
        duration:        targetDuration.value,
        langs:           [testLanguage.value],
        available_tags:  availableTags.value,
        user_hard_tags:  hardTags,
      },
      { timeout: 15000 },
    )
    const data = resp.data || {}
    draftMeta.value = data.meta || null
    applyBlueprintTimelineToTracks(data.timeline)
    // 等待 Vue 完成本轮响应式更新，确保抽屉 watch 读到已含 items 的 dslTracks
    await nextTick()
    showOrchestrator.value = true
    store.showToast('✨ 蓝图已生成，请在战术板验收语义标签')
  } catch (err) {
    // 绝对不清空用户输入，仅分诊错误类型上报
    if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
      store.showToast('❌ 导演大模型响应超时（超过15秒），请检查网络或稍后重试。')
    } else if ((err.response?.status ?? 0) >= 500) {
      store.showToast('❌ 云端算力节点拥挤，导演大模型开小差了 (5xx)，请稍后重试。')
    } else {
      store.showToast('❌ 起草失败: ' + (err.response?.data?.detail || err.message))
    }
  } finally {
    isDrafting.value = false
  }
}

function buildTimelineFromTracks() {
  return dslTracks.value
    .map(track => {
      const physicals = track.items.filter(i => i.type === 'physical_asset' || !i.type)
      const tags      = track.items.filter(i => i.type === 'semantic_tag')
      // Phase 9.7.3 — 空间排版意图：hash → position_key（仅含已设置排版的素材）
      const layoutHints = {}
      physicals.forEach(pill => { if (pill.layout) layoutHints[pill.hash] = pill.layout })
      const beatNode = {
        beat:          track.id,
        role:          track.role,
        script_text:   track.script_text   || '',
        visual_script: track.visual_script || '',
        emotion:       track.emotion       || '',
        address_mode:  physicals.length > 0 ? 'locked' : 'smart',
        asset_hashes:  physicals.map(i => i.hash),
        semantic_tags: tags.map(i => i.tag),
      }
      if (Object.keys(layoutHints).length > 0) beatNode.layout_hints = layoutHints
      return beatNode
    })
    .filter(b => b.asset_hashes.length > 0 || b.semantic_tags.length > 0)
}

/** 极速裂变：timeline 为空 + 有 prompt → 后端盲裂变；战术板有装填 → 完整 timeline + script_text */
async function blindFission() {
  const rawPrompt = omniPrompt.value.trim()
  const hasPrompt = rawPrompt.length > 0
  const hasBlocks = dslTracks.value.some(t => t.items.length > 0)

  if (!hasPrompt && !hasBlocks) {
    store.showToast('⚠️ 请输入提示词，或在战术板中装填素材 / 语义标签')
    return
  }

  const { pureText, hardTags } = extractHardTags(rawPrompt)

  isSubmitting.value = true

  const activeBeatCount = dslTracks.value.filter(t => t.items.length > 0).length
  const displayLabel = rawPrompt ||
    `DSL · ${currentTemplate.value} · ${activeBeatCount} 个节拍 · ${aspectRatio.value}`

  const blind = hasPrompt && !hasBlocks
  const timeline = blind ? [] : buildTimelineFromTracks()

  if (!blind && !timeline.length) {
    store.showToast('⚠️ 战术板节拍为空，请装填标签或素材后再提交')
    isSubmitting.value = false
    return
  }

  try {
    const payload = {
      engine_type:      currentTemplate.value,
      timeline,
      aspect_ratio:     aspectRatio.value,
      target_duration:  targetDuration.value,
      batch_size:       batchSize.value,
      test_language:    testLanguage.value,
      tenant_id:        store.loggedInUser || 'default',
      mode:             scriptMode.value,
      user_hard_tags:   hardTags,
      meta:             draftMeta.value,
      enable_tts:       enableTts.value,
      enable_subtitles: enableSubtitles.value,
      ...(hasPrompt && { prompt: pureText || rawPrompt }),
    }

    const resp   = await axios.post(`${store.API_BASE}/api/v1/tasks/submit-dsl`, payload)
    const taskId = resp.data.task_id
    if (!taskId) throw new Error('后端未返回 task_id，请检查后端日志')

    queueStore.pushTaskUpdate({
      taskId,
      status:    'pending',
      prompt:    displayLabel,
      startTime: Date.now(),
    })
    await nextTick()

    dslTracks.value.forEach(t => {
      t.items = []
      t.script_text = ''
      t.visual_script = ''
      t.emotion = ''
    })
    draftMeta.value = null
    omniPrompt.value = ''

    store.showToast('🚀 矩阵任务已投入后台熔炉')
  } catch (err) {
    const raw    = err.response?.data?.detail
    const detail = Array.isArray(raw)
      ? raw.map(e => e.msg ?? JSON.stringify(e)).join('；')
      : (typeof raw === 'string' ? raw : (err.message ?? '未知错误'))
    store.showToast(`[${err.response?.status ?? 'ERR'}] 提交失败：${detail}`)
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="workspace-wrap">

    <!-- ── 任务监控流（全宽）───────────────────────────────────────────────── -->
    <div class="task-feed">
      <QueueView @open-detail="hash => activeDetailHash = hash" />
    </div>

    <!-- ── 底部 Omnibox（沉浸式指令舱）──────────────────────────────────────── -->
    <div class="omnibox">
      <div class="script-mode-tabs">
        <button
          class="script-mode-tab"
          :class="{ 'script-mode-tab--active': scriptMode === 'auto' }"
          @click="scriptMode = 'auto'"
        >✨ AI 智能创作</button>
        <button
          class="script-mode-tab"
          :class="{ 'script-mode-tab--active': scriptMode === 'rewrite' }"
          @click="scriptMode = 'rewrite'"
        >📝 专属文案洗稿</button>
      </div>

      <div class="omni-command-center">

        <!-- ── 导演推演阻断遮罩 ──────────────────────────────────────────── -->
        <Transition name="drafting-mask">
          <div v-if="isDrafting" class="drafting-overlay">
            <span class="drafting-spinner" aria-hidden="true"></span>
            <span class="drafting-label">🧠 导演大模型推演中，请稍候…</span>
          </div>
        </Transition>

        <Transition name="fade-slide">
          <div v-if="showMentionMenu && filteredTags.length > 0" class="mention-palette">
            <div class="mention-header">🏷️ 插入分面标签</div>
            <ul class="mention-list">
              <li
                v-for="tag in filteredTags"
                :key="tag"
                @mousedown.prevent="selectTag(tag)"
              >
                <span class="mention-prefix">@</span>{{ tag.replace(/^#/, '') }}
              </li>
            </ul>
          </div>
        </Transition>

        <div class="omni-input-wrap">
          <textarea
            ref="omniTextareaRef"
            v-model="omniPrompt"
            @input="handleInput"
            @keyup="handleInput"
            @click="handleInput"
            @keydown.enter.ctrl.prevent="blindFission"
            :placeholder="omniPlaceholder"
            class="omni-textarea"
            rows="2"
          ></textarea>
          <button
            type="button"
            class="magic-enhance-btn"
            :class="{ 'is-loading': isEnhancing }"
            :disabled="isEnhancing || !omniPrompt.trim()"
            title="AI 智能扩写与自动打标"
            @click="enhancePrompt"
          >
            ✨
          </button>
        </div>

        <div class="omni-toolbar">
          <div class="toolbar-left">
            <button
              type="button"
              class="ammo-load-btn ghost-btn"
              title="打开手动战术板"
              @click="showOrchestrator = true"
            >
              <span class="ammo-icon">🛠️</span>
              <span v-if="stagedBlockCount > 0" class="ammo-badge">{{ stagedBlockCount }}</span>
            </button>

            <div class="omni-toolbar-divider" />

            <div class="tool-pill">
              <span>📐</span>
              <select v-model="aspectRatio">
                <option value="9:16">9:16 竖屏</option>
                <option value="16:9">16:9 横屏</option>
                <option value="1:1">1:1 方形</option>
              </select>
            </div>

            <div class="tool-pill">
              <span>🌐</span>
              <select v-model="testLanguage">
                <option value="en">EN 英语</option>
                <option value="ar">AR 阿语</option>
                <option value="zh">ZH 中文</option>
              </select>
            </div>

            <div class="tool-pill">
              <span>⏱️</span>
              <select v-model.number="targetDuration">
                <option :value="15">15秒</option>
                <option :value="30">30秒</option>
                <option :value="60">60秒</option>
              </select>
            </div>

            <div class="tool-pill tool-num-pill">
              <span>🔢</span>
              <input
                v-model.number="batchSize"
                type="number"
                min="1"
                max="20"
                title="批量数量"
              />
            </div>

            <div class="omni-toolbar-divider" />

            <button
              type="button"
              class="pipeline-toggle"
              :class="{ 'pipeline-toggle--on': enableTts }"
              :title="enableTts ? '🎙️ AI 语音已开启（点击关闭）' : '🎙️ AI 语音已关闭（点击开启）'"
              @click="enableTts = !enableTts"
            >
              🎙️
              <span class="toggle-label">语音</span>
              <span class="toggle-dot" :class="enableTts ? 'toggle-dot--on' : 'toggle-dot--off'" />
            </button>

            <button
              type="button"
              class="pipeline-toggle"
              :class="{ 'pipeline-toggle--on': enableSubtitles }"
              :title="enableSubtitles ? '📝 字幕已开启（点击关闭）' : '📝 字幕已关闭（点击开启）'"
              @click="enableSubtitles = !enableSubtitles"
            >
              📝
              <span class="toggle-label">字幕</span>
              <span class="toggle-dot" :class="enableSubtitles ? 'toggle-dot--on' : 'toggle-dot--off'" />
            </button>
          </div>

          <div class="toolbar-right">
            <span
              v-if="omniPrompt.trim() && !dslTracks.some(t => t.items.length > 0)"
              class="auto-mode-hint"
            >直接裂变或 AI 起草</span>
            <button
              type="button"
              class="draft-btn"
              :class="{ 'draft-btn--drafting': isDrafting }"
              :disabled="isSubmitting || isDrafting"
              @click="draftBlueprint"
            >
              {{ isDrafting ? '🧠 导演推演中...' : '✨ AI 起草' }}
            </button>
            <button
              type="button"
              class="fission-btn"
              :class="{ 'fission-btn--locked': lockedAssetHashes.length > 0 }"
              :disabled="!canFission"
              @click="blindFission"
            >
              {{
                isSubmitting
                  ? '⏳ 裂变中…'
                  : `🚀 极速裂变 (×${batchSize})`
              }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ── DSL 编排抽屉 ─────────────────────────────────────────────────── -->
    <DslOrchestratorDrawer
      v-model="showOrchestrator"
      :db-asset-list="dbAssetList"
      :dsl-tracks="dslTracks"
      :templates="dslTemplates"
      :current-template="currentTemplate"
      :draft-meta="draftMeta"
      :build-video-url="store.buildVideoUrl"
      :api-base="store.API_BASE"
      :show-toast="store.showToast"
      :default-batch-size="batchSize"
      :default-aspect-ratio="aspectRatio"
      :default-language="testLanguage"
      :default-target-duration="targetDuration"
      :default-enable-tts="enableTts"
      :default-enable-subtitles="enableSubtitles"
      :tenant-id="store.loggedInUser || 'default'"
      @confirm="onOrchestratorConfirm"
    />

    <!-- ── 沉浸式视频详情抽屉（position:fixed, 零路由跳转）──────────────── -->
    <VideoDetailDrawer
      v-if="activeDetailHash"
      :asset-hash="activeDetailHash"
      @close="activeDetailHash = ''"
    />

  </div>
</template>

<style scoped>
/* ── 整体布局：纯双行，任务流占满全宽 ────────────────────────────────────── */
.workspace-wrap {
  display: grid;
  grid-template-rows: 1fr auto;
  grid-template-areas:
    "feed"
    "omni";
  height:   100%;
  overflow: hidden;
}

.task-feed {
  grid-area: feed;
  overflow:  hidden;
  min-height: 0;
}

/* ── Omnibox ─────────────────────────────────────────────────────────────── */
.omnibox {
  grid-area:   omni;
  background:  rgba(9, 14, 30, 0.98);
  border-top:  1px solid rgba(56, 189, 248, 0.12);
  box-shadow:  0 -8px 32px rgba(0, 0, 0, 0.3);
  padding:     0 0.65rem 0.65rem;
}

.script-mode-tabs {
  display:        flex;
  gap:            0;
  border-bottom:  1px solid rgba(99, 102, 241, 0.1);
  border-radius:  12px 12px 0 0;
  overflow:       hidden;
}

.script-mode-tab {
  flex:           1;
  background:     transparent;
  border:         none;
  color:          #475569;
  font-size:      0.72rem;
  font-weight:    500;
  padding:        0.45rem 0.75rem;
  cursor:         pointer;
  transition:     color 0.15s, background 0.15s;
  letter-spacing: 0.01em;
}
.script-mode-tab:hover { color: #94a3b8; background: rgba(99, 102, 241, 0.04); }
.script-mode-tab--active {
  color:       #a5b4fc !important;
  background:  rgba(99, 102, 241, 0.08) !important;
  border-bottom: 2px solid #6366f1;
}

/* ── 操作舱主容器 ────────────────────────────────────────────────────────── */
.omni-command-center {
  position:      relative;
  background:    rgba(15, 23, 42, 0.6);
  border-radius: 0 0 12px 12px;
  border:        1px solid rgba(56, 189, 248, 0.1);
  border-top:    none;
  display:       flex;
  flex-direction: column;
  transition:    border-color 0.3s, box-shadow 0.3s;
}

/* ── @ 唤醒标签词典 ──────────────────────────────────────────────────────── */
.mention-palette {
  position:        absolute;
  left:            1rem;
  right:           1rem;
  bottom:          100%;
  margin-bottom:   0.35rem;
  z-index:         40;
  background:      rgba(15, 23, 42, 0.95);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border:          1px solid rgba(99, 102, 241, 0.25);
  border-radius:   10px;
  box-shadow:      0 -8px 24px rgba(0, 0, 0, 0.35);
  max-height:      200px;
  overflow:        hidden;
  display:         flex;
  flex-direction:  column;
}

.mention-header {
  padding:       0.45rem 0.75rem;
  font-size:     0.68rem;
  font-weight:   600;
  color:         #94a3b8;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-bottom: 1px solid rgba(99, 102, 241, 0.12);
  flex-shrink:   0;
}

.mention-list {
  list-style: none;
  margin:     0;
  padding:    0.25rem 0;
  overflow-y: auto;
  max-height: 160px;
}

.mention-list li {
  padding:     0.45rem 0.85rem;
  font-size:   0.82rem;
  color:       #cbd5e1;
  cursor:      pointer;
  transition:  background 0.12s, color 0.12s;
  font-family: 'Consolas', 'Monaco', monospace;
}

.mention-list li:hover {
  background: rgba(99, 102, 241, 0.15);
  color:      #a5b4fc;
}

.mention-prefix {
  color:       #6366f1;
  font-weight: 600;
  margin-right: 0.15rem;
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity:   0;
  transform: translateY(6px);
}
.omni-command-center:focus-within {
  border-color: rgba(99, 102, 241, 0.4);
  box-shadow:   0 4px 20px rgba(99, 102, 241, 0.05);
}

.omni-input-wrap {
  position: relative;
}

.omni-textarea {
  width:       100%;
  box-sizing:  border-box;
  background:  transparent;
  border:      none;
  color:       #f8fafc;
  font-size:   0.9rem;
  line-height: 1.5;
  padding:     1rem 3rem 1rem 1.2rem;
  resize:      none;
  outline:     none;
  font-family: inherit;
}
.omni-textarea::placeholder { color: #475569; }

/* ── 魔法棒 Loading 动效 ────────────────────────────────────────────────── */
.magic-enhance-btn {
  position:      absolute;
  right:         0.8rem;
  top:           0.8rem;
  background:    transparent;
  border:        none;
  font-size:     1.2rem;
  line-height:   1;
  cursor:        pointer;
  padding:       0.2rem;
  transition:    all 0.3s ease;
  z-index:       5;
}
.magic-enhance-btn:hover:not(:disabled) {
  filter: drop-shadow(0 0 6px rgba(167, 139, 250, 0.8));
}
.magic-enhance-btn:disabled:not(.is-loading) {
  opacity: 0.35;
  cursor:  not-allowed;
}
.magic-enhance-btn.is-loading {
  cursor:    wait !important;
  opacity:   1 !important;
  animation: magic-pulse 1.2s ease-in-out infinite;
}

@keyframes magic-pulse {
  0% {
    transform: scale(1);
    filter: drop-shadow(0 0 2px rgba(167, 139, 250, 0.4));
    opacity: 0.8;
  }
  50% {
    transform: scale(1.2);
    filter: drop-shadow(0 0 15px rgba(167, 139, 250, 1));
    opacity: 1;
  }
  100% {
    transform: scale(1);
    filter: drop-shadow(0 0 2px rgba(167, 139, 250, 0.4));
    opacity: 0.8;
  }
}

/* ── 底部控制栏 ────────────────────────────────────────────────────────── */
.omni-toolbar {
  display:         flex;
  justify-content: space-between;
  align-items:     center;
  flex-wrap:       wrap;
  gap:             1rem;
  min-width:       0;
  padding:         0.6rem 1rem 0.8rem 1rem;
  border-top:      1px dashed rgba(99, 102, 241, 0.15);
}

.toolbar-left {
  display:     flex;
  align-items: center;
  flex-wrap:   wrap;
  gap:         0.5rem;
}

.toolbar-right {
  display:         flex;
  align-items:     center;
  flex-wrap:       wrap;
  gap:             0.6rem;
  justify-content: flex-end;
  margin-left:     auto;
}

.omni-toolbar-divider {
  width:       1px;
  height:      1.2rem;
  background:  rgba(99, 102, 241, 0.3);
  flex-shrink: 0;
  margin:      0 0.2rem;
}

/* ── 轻量级胶囊参数 (Pills) ──────────────────────────────────────────────── */
/* ── 轻量级胶囊参数 (Pills) 修复 ────────────────────────────────────────── */
.tool-pill {
  display: flex;
  align-items: center;
  background: rgba(30, 41, 59, 0.5);
  border-radius: 20px;
  padding: 0.2rem 0.6rem 0.2rem 0.4rem;
  border: 1px solid transparent;
  transition: all 0.2s;
}
.tool-pill:hover {
  background: rgba(30, 41, 59, 0.9);
  border-color: rgba(99, 102, 241, 0.3);
}
.tool-pill span {
  font-size: 0.75rem;
  margin-right: 0.3rem;
}

/* 修复1：给 select 增加右侧 padding，防止文字挤出边缘 */
.tool-pill select, .tool-pill input {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 0.75rem;
  outline: none;
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
  padding-right: 0.4rem; /* 增加呼吸空间，解决溢出 */
}
.tool-pill select:hover, .tool-pill input:hover { 
  color: #e2e8f0; 
}

/* 修复2：强制覆盖原生 Option 的白底问题，打造深色极客质感 */
.tool-pill select option {
  background-color: #0f172a; /* 极深蓝底色 */
  color: #e2e8f0;            /* 亮白文字 */
  font-weight: 500;
  padding: 0.5rem;           /* 增加上下间距 */
}

.tool-num-pill input { 
  width: 2.2rem; 
  text-align: center; 
  padding-right: 0; /* 数量框不需要右侧防挤 */
}

/* ── 幽灵战术板按钮 ────────────────────────────────────────────────────── */
.ammo-load-btn.ghost-btn {
  position:    relative;
  display:     flex;
  align-items: center;
  justify-content: center;
  min-width:   2rem;
  min-height:  2rem;
}
.ghost-btn {
  background: transparent;
  border:       none;
  color:        #64748b;
  font-size:    1.1rem;
  cursor:       pointer;
  padding:      0.3rem;
  border-radius: 6px;
  transition:   background 0.2s, color 0.2s, transform 0.2s;
  box-shadow:   none;
}
.ghost-btn:hover {
  background: rgba(99, 102, 241, 0.1);
  color:      #818cf8;
  transform:  translateY(-1px);
}

.ammo-icon {
  font-size: 1.1rem;
  line-height: 1;
}

.ammo-badge {
  position:    absolute;
  top:         -4px;
  right:       -4px;
  min-width:   18px;
  height:      18px;
  padding:     0 4px;
  border-radius: 9px;
  background:  linear-gradient(135deg, #f43f5e, #e11d48);
  color:       #fff;
  font-size:   0.62rem;
  font-weight: 700;
  display:       flex;
  align-items:   center;
  justify-content: center;
  border:      2px solid rgba(15, 23, 42, 0.95);
  box-shadow:  0 2px 6px rgba(244, 63, 94, 0.45);
}

/* ── 引擎组按钮 ─────────────────────────────────────────────────────────── */
.draft-btn {
  background:   rgba(30, 41, 59, 0.8);
  border:       1px solid rgba(167, 139, 250, 0.4);
  color:        #e2e8f0;
  font-size:    0.82rem;
  font-weight:  600;
  padding:      0.4rem 1rem;
  border-radius: 8px;
  cursor:       pointer;
  transition:   all 0.2s ease;
  box-shadow:   0 0 10px rgba(167, 139, 250, 0.1);
  white-space:  nowrap;
}
.draft-btn:hover:not(:disabled) {
  background:   rgba(49, 46, 129, 0.6);
  border-color: rgba(167, 139, 250, 0.8);
  box-shadow:   0 0 16px rgba(167, 139, 250, 0.3);
}
.draft-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.draft-btn--drafting {
  background:   rgba(49, 46, 129, 0.5);
  border-color: rgba(167, 139, 250, 0.7);
  box-shadow:   0 0 20px rgba(167, 139, 250, 0.25);
  animation:    draft-pulse 1.8s ease-in-out infinite;
}

@keyframes draft-pulse {
  0%, 100% { box-shadow: 0 0 10px rgba(167, 139, 250, 0.15); }
  50%       { box-shadow: 0 0 22px rgba(167, 139, 250, 0.45); }
}

/* ── 导演推演阻断遮罩 ────────────────────────────────────────────────────── */
.drafting-overlay {
  position:        absolute;
  inset:           0;
  z-index:         30;
  display:         flex;
  align-items:     center;
  justify-content: center;
  gap:             0.75rem;
  background:      rgba(9, 14, 30, 0.72);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  border-radius:   0 0 12px 12px;
  pointer-events:  all;
}

.drafting-spinner {
  width:        18px;
  height:       18px;
  border:       2.5px solid rgba(167, 139, 250, 0.25);
  border-top-color: #a78bfa;
  border-radius: 50%;
  animation:    spin 0.75s linear infinite;
  flex-shrink:  0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.drafting-label {
  font-size:   0.82rem;
  font-weight: 600;
  color:       #c4b5fd;
  letter-spacing: 0.02em;
}

.drafting-mask-enter-active,
.drafting-mask-leave-active {
  transition: opacity 0.2s ease;
}
.drafting-mask-enter-from,
.drafting-mask-leave-to {
  opacity: 0;
}

.fission-btn {
  background:    linear-gradient(135deg, #0ea5e9, #6366f1);
  border:        none;
  color:         #ffffff;
  font-size:     0.82rem;
  font-weight:   700;
  padding:       0.4rem 1.2rem;
  border-radius: 8px;
  cursor:        pointer;
  letter-spacing: 0.02em;
  transition:    all 0.2s ease;
  box-shadow:    0 0 16px rgba(99, 102, 241, 0.3);
  white-space:   nowrap;
}
.fission-btn:hover:not(:disabled) {
  transform:  translateY(-1px);
  box-shadow: 0 0 24px rgba(99, 102, 241, 0.5);
}
.fission-btn:disabled {
  opacity:   0.5;
  cursor:    not-allowed;
  transform: none;
}

.fission-btn--locked {
  background: linear-gradient(135deg, #7c3aed, #6366f1) !important;
  box-shadow: 0 0 14px rgba(167, 139, 250, 0.35) !important;
}

.toolbar-right .auto-mode-hint {
  font-size:     0.65rem;
  color:           #94a3b8;
  background:    rgba(56, 189, 248, 0.06);
  border:        1px solid rgba(56, 189, 248, 0.15);
  border-radius: 999px;
  padding:       0.2rem 0.65rem;
  white-space:   nowrap;
}

/* ── 管线开关：🎙️ 语音 / 📝 字幕 ─────────────────────────────────── */
.pipeline-toggle {
  display:       flex;
  align-items:   center;
  gap:           0.28rem;
  padding:       0.22rem 0.55rem;
  border-radius: 999px;
  border:        1px solid rgba(99, 102, 241, 0.2);
  background:    rgba(30, 41, 59, 0.6);
  color:         #64748b;
  font-size:     0.72rem;
  font-weight:   500;
  cursor:        pointer;
  transition:    all 0.18s ease;
  white-space:   nowrap;
  user-select:   none;
}
.pipeline-toggle:hover {
  border-color: rgba(99, 102, 241, 0.45);
  color:        #94a3b8;
}
.pipeline-toggle--on {
  border-color: rgba(99, 102, 241, 0.5);
  background:   rgba(99, 102, 241, 0.12);
  color:        #a78bfa;
}
.toggle-label {
  letter-spacing: 0.01em;
}
.toggle-dot {
  width:         7px;
  height:        7px;
  border-radius: 50%;
  flex-shrink:   0;
  transition:    background 0.18s ease;
}
.toggle-dot--on  { background: #818cf8; }
.toggle-dot--off { background: #334155; }
</style>
