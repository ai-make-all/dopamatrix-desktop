<script setup>
import { ref, computed, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { useAppStore }         from '../stores/appStore'
import { useQueueStore }       from '../stores/useQueueStore'
import QueueView               from './QueueView.vue'
import DslOrchestratorDrawer   from './DslOrchestratorDrawer.vue'
import VideoDetailDrawer       from './VideoDetailDrawer.vue'

const router     = useRouter()
const store      = useAppStore()
const queueStore = useQueueStore()

// ── 沉浸式详情抽屉（零路由跳转，父页面状态完全保留）──────────────────────
const activeDetailHash = ref('')

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
const audioVibe      = ref('auto')

// ── DB 素材列表（真相源：后端 API）──────────────────────────────────────────
const dbAssetList = ref([])

// 全域资产注册表：所有维度并发拉取，扁平合并
const ASSET_REGISTRY = ['video', 'image', 'audio_bgm', 'vfx', 'sfx']

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
const dslTracks = ref(dslTemplates.content.map(t => ({ ...t, items: [] })))

// ── 抽屉控制 ────────────────────────────────────────────────────────────────
const showOrchestrator = ref(false)

function onOrchestratorConfirm({ tracks, template }) {
  dslTracks.value   = tracks
  currentTemplate.value = template
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

const canSubmit = computed(() => {
  const hasPrompt = omniPrompt.value.trim().length > 0
  const hasBlocks = dslTracks.value.some(t => t.items.length > 0)
  return !isSubmitting.value && (hasPrompt || hasBlocks)
})

// ── Submit ───────────────────────────────────────────────────────────────────
async function sendTask() {
  const hasPrompt = omniPrompt.value.trim().length > 0
  const hasBlocks = dslTracks.value.some(t => t.items.length > 0)

  if (!hasPrompt && !hasBlocks) {
    store.showToast('⚠️ 请输入提示词，或在战术板中装填素材 / 语义标签')
    return
  }

  isSubmitting.value = true

  const activeBeatCount = dslTracks.value.filter(t => t.items.length > 0).length
  const displayLabel = omniPrompt.value.trim() ||
    `DSL · ${currentTemplate.value} · ${activeBeatCount} 个节拍 · ${aspectRatio.value}`

  try {
    const timeline = hasBlocks
      ? dslTracks.value
          .map(track => {
            const physicals = track.items.filter(i => i.type === 'physical_asset' || !i.type)
            const tags      = track.items.filter(i => i.type === 'semantic_tag')
            return {
              beat:          track.id,
              role:          track.role,
              address_mode:  physicals.length > 0 ? 'locked' : 'smart',
              asset_hashes:  physicals.map(i => i.hash),
              semantic_tags: tags.map(i => i.tag),
            }
          })
          .filter(b => b.asset_hashes.length > 0 || b.semantic_tags.length > 0)
      : dslTracks.value.map(track => ({
          beat:          track.id,
          role:          track.role,
          address_mode:  'smart',
          asset_hashes:  [],
          semantic_tags: [],
        }))

    const payload = {
      engine_type:     currentTemplate.value,
      timeline,
      aspect_ratio:    aspectRatio.value,
      target_duration: targetDuration.value,
      batch_size:      batchSize.value,
      test_language:   testLanguage.value,
      tenant_id:       store.loggedInUser || 'default',
      ...(hasPrompt && { prompt: omniPrompt.value.trim() }),
    }

    const resp   = await axios.post(`${store.API_BASE}/api/v1/tasks/submit-dsl`, payload)
    const taskId = resp.data.task_id
    if (!taskId) throw new Error('后端未返回 task_id，请检查后端日志')

    // batch_size 个子渲染全部共用同一 task_id，只推一张卡片；
    // 全部渲染完成后后端发送一次 completed 事件，轮播展示所有视频。
    queueStore.pushTaskUpdate({
      taskId,
      status:    'pending',
      prompt:    displayLabel,
      startTime: Date.now(),
    })
    await nextTick()

    dslTracks.value.forEach(t => { t.items = [] })
    omniPrompt.value = ''

    const bs = batchSize.value
    store.showToast(
      bs > 1
        ? `✅ 已下发批量任务 ×${bs} · ID: ${taskId.slice(0, 8)}…`
        : `✅ 渲染任务已下发 · ID: ${taskId.slice(0, 8)}…`
    )

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

    <!-- ── 底部 Omnibox ──────────────────────────────────────────────────── -->
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

      <textarea
        v-model="omniPrompt"
        @keydown.enter.ctrl.prevent="sendTask"
        :placeholder="omniPlaceholder"
        class="omni-textarea"
        rows="3"
      ></textarea>

      <div class="omni-toolbar">

        <!-- ⚡ 装填弹药 ── 唤起编排抽屉 -->
        <button class="ammo-load-btn" @click="showOrchestrator = true">
          <span class="ammo-icon">⚡</span>
          <span class="ammo-label">装填弹药</span>
          <Transition name="badge-pop">
            <span v-if="stagedBlockCount > 0" class="ammo-badge">{{ stagedBlockCount }}</span>
          </Transition>
        </button>

        <div class="omni-toolbar-divider" />

        <div class="tool-select-wrap">
          <span class="tool-select-icon">📐</span>
          <select v-model="aspectRatio" class="tool-select">
            <option value="9:16">9:16 竖屏</option>
            <option value="16:9">16:9 横屏</option>
            <option value="1:1">1:1 方形</option>
          </select>
        </div>

        <div class="tool-select-wrap">
          <span class="tool-select-icon">🌐</span>
          <select v-model="testLanguage" class="tool-select">
            <option value="en">EN 英语</option>
            <option value="ar">AR 阿语</option>
            <option value="zh">ZH 中文</option>
          </select>
        </div>

        <div class="tool-select-wrap">
          <span class="tool-select-icon">⏱️</span>
          <select v-model.number="targetDuration" class="tool-select">
            <option :value="15">短平快 (15秒)</option>
            <option :value="30">信息流 (30秒)</option>
            <option :value="60">完整故事 (60秒)</option>
          </select>
        </div>

        <div class="tool-select-wrap tool-select-wrap--vibe">
          <span class="tool-select-icon">🎵</span>
          <select v-model="audioVibe" class="tool-select tool-select--vibe">
            <option value="auto">🎵 AI 智能匹配 (Auto)</option>
            <option value="asmr">🎧 ASMR / 沉浸解压</option>
            <option value="epic">💥 史诗震撼 / 强节奏</option>
            <option value="funny">🤪 荒诞鬼畜 / 模因音效</option>
            <option value="none">🔇 纯人声解说 (无 BGM)</option>
          </select>
        </div>

        <div class="tool-num-wrap">
          <span class="tool-select-icon">🔢</span>
          <input
            v-model.number="batchSize"
            type="number" min="1" max="20"
            class="tool-num"
            title="批量数量"
          />
        </div>

        <!-- 购物车状态指示器 -->
        <Transition name="cart-pop">
          <div v-if="lockedAssetHashes.length > 0" class="cart-indicator">
            🔒 已锁定 <strong>{{ lockedAssetHashes.length }}</strong> 个素材
          </div>
        </Transition>

        <div class="send-btn-wrap">
          <button
            @click="sendTask"
            :disabled="!canSubmit"
            class="send-btn"
            :class="{ 'send-btn--locked': lockedAssetHashes.length > 0 }"
          >
            {{ isSubmitting ? '⏳ 下发中…' : lockedAssetHashes.length > 0 ? '🔒 锁定渲染' : '🚀 渲染' }}
          </button>
          <Transition name="hint-fade">
            <div
              v-if="omniPrompt.trim() && !dslTracks.some(t => t.items.length > 0)"
              class="auto-mode-hint"
            >
              💡 全自动模式，系统将根据提示词智能匹配素材
            </div>
          </Transition>
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
      :build-video-url="store.buildVideoUrl"
      :api-base="store.API_BASE"
      :show-toast="store.showToast"
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
  grid-area: omni;
  background: rgba(9, 14, 30, 0.98);
  border-top: 1px solid rgba(56, 189, 248, 0.12);
  box-shadow: 0 -8px 32px rgba(0, 0, 0, 0.3);
}

.script-mode-tabs {
  display:     flex;
  gap:         0;
  border-bottom: 1px solid rgba(99, 102, 241, 0.1);
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

.omni-textarea {
  width:       100%;
  box-sizing:  border-box;
  background:  transparent;
  border:      none;
  border-bottom: 1px solid rgba(99, 102, 241, 0.08);
  color:       #e2e8f0;
  font-size:   0.85rem;
  line-height: 1.6;
  padding:     0.75rem 1rem;
  resize:      none;
  outline:     none;
  font-family: inherit;
}
.omni-textarea::placeholder { color: #334155; }

/* ── Omni Toolbar ────────────────────────────────────────────────────────── */
.omni-toolbar {
  display:     flex;
  align-items: center;
  flex-wrap:   wrap;
  gap:         0.5rem;
  min-width:   0;
  padding:     0.55rem 0.9rem;
}

.omni-toolbar-divider {
  width:       1px;
  height:      1.5rem;
  background:  rgba(99, 102, 241, 0.15);
  flex-shrink: 0;
  margin:      0 0.15rem;
}

/* ── 装填弹药按钮 ────────────────────────────────────────────────────────── */
.ammo-load-btn {
  position:    relative;
  display:     flex;
  align-items: center;
  gap:         0.4rem;
  padding:     0.38rem 0.9rem;
  border-radius: 8px;
  border:      1px solid rgba(99, 102, 241, 0.45);
  background:  linear-gradient(135deg, rgba(49, 46, 129, 0.5), rgba(30, 27, 75, 0.4));
  color:       #a5b4fc;
  font-size:   0.8rem;
  font-weight: 600;
  cursor:      pointer;
  letter-spacing: 0.02em;
  transition:  background 0.2s, border-color 0.2s, box-shadow 0.2s, transform 0.15s;
  flex-shrink: 0;
  box-shadow:  0 0 12px rgba(99, 102, 241, 0.15);
}
.ammo-load-btn:hover {
  background:   linear-gradient(135deg, rgba(79, 70, 229, 0.5), rgba(49, 46, 129, 0.5));
  border-color: rgba(139, 92, 246, 0.7);
  box-shadow:   0 0 20px rgba(99, 102, 241, 0.35);
  transform:    translateY(-1px);
}
.ammo-load-btn:active { transform: translateY(0); }

.ammo-icon  { font-size: 0.9rem; filter: drop-shadow(0 0 6px rgba(99, 102, 241, 0.8)); }
.ammo-label { white-space: nowrap; }

.ammo-badge {
  position:    absolute;
  top:         -6px;
  right:       -6px;
  min-width:   18px;
  height:      18px;
  padding:     0 4px;
  border-radius: 9px;
  background:  linear-gradient(135deg, #f43f5e, #e11d48);
  color:       #fff;
  font-size:   0.62rem;
  font-weight: 700;
  display:     flex;
  align-items: center;
  justify-content: center;
  border:      2px solid rgba(9, 14, 30, 0.95);
  box-shadow:  0 2px 6px rgba(244, 63, 94, 0.45);
}

.badge-pop-enter-active, .badge-pop-leave-active { transition: opacity 0.2s, transform 0.2s; }
.badge-pop-enter-from, .badge-pop-leave-to       { opacity: 0; transform: scale(0.5); }

/* ── Tool selects ────────────────────────────────────────────────────────── */
.tool-select-wrap {
  display:     flex;
  align-items: center;
  gap:         0.25rem;
  flex-shrink: 0;
}

.tool-select-icon {
  font-size:   0.82rem;
  flex-shrink: 0;
  opacity:     0.75;
}

.tool-select {
  background:  rgba(15, 23, 42, 0.9);
  border:      1px solid rgba(99, 102, 241, 0.2);
  color:       #94a3b8;
  font-size:   0.72rem;
  padding:     0.25rem 0.55rem;
  border-radius: 5px;
  cursor:      pointer;
  outline:     none;
  transition:  border-color 0.15s;
}
.tool-select:hover  { border-color: rgba(99, 102, 241, 0.45); }
.tool-select--vibe  { max-width: 165px; }

.tool-num-wrap {
  display:     flex;
  align-items: center;
  gap:         0.25rem;
}

.tool-num {
  width:        3.5rem;
  background:   rgba(15, 23, 42, 0.9);
  border:       1px solid rgba(99, 102, 241, 0.2);
  color:        #94a3b8;
  font-size:    0.72rem;
  padding:      0.25rem 0.4rem;
  border-radius: 5px;
  outline:      none;
  text-align:   center;
}

/* ── 购物车指示器 ────────────────────────────────────────────────────────── */
.cart-indicator {
  display:     flex;
  align-items: center;
  gap:         0.35rem;
  padding:     0.28rem 0.7rem;
  border-radius: 20px;
  background:  rgba(167, 139, 250, 0.1);
  border:      1px solid rgba(167, 139, 250, 0.32);
  color:       #c4b5fd;
  font-size:   0.72rem;
  white-space: nowrap;
}
.cart-indicator strong { color: #a78bfa; }

.cart-pop-enter-active, .cart-pop-leave-active { transition: opacity 0.2s, transform 0.2s; }
.cart-pop-enter-from, .cart-pop-leave-to       { opacity: 0; transform: scale(0.85); }

/* ── Send button ─────────────────────────────────────────────────────────── */
.send-btn-wrap {
  display:        flex;
  flex-direction: column;
  align-items:    flex-end;
  gap:            0.3rem;
  flex-shrink:    0;
  margin-left:    auto;
}

.send-btn {
  background:    linear-gradient(135deg, #0ea5e9, #6366f1);
  border:        none;
  color:         #fff;
  font-size:     0.82rem;
  font-weight:   700;
  padding:       0.45rem 1.4rem;
  border-radius: 8px;
  cursor:        pointer;
  letter-spacing: 0.04em;
  transition:    opacity 0.2s, box-shadow 0.2s, transform 0.15s;
  box-shadow:    0 0 16px rgba(99, 102, 241, 0.3);
  white-space:   nowrap;
}
.send-btn:hover:not(:disabled) {
  box-shadow: 0 0 24px rgba(99, 102, 241, 0.5);
  transform:  translateY(-1px);
}
.send-btn:disabled    { opacity: 0.4; cursor: not-allowed; transform: none; }
.send-btn--locked     {
  background: linear-gradient(135deg, #7c3aed, #6366f1) !important;
  box-shadow: 0 0 14px rgba(167, 139, 250, 0.35) !important;
}

.auto-mode-hint {
  font-size:    0.62rem;
  color:        #7dd3fc;
  background:   rgba(56, 189, 248, 0.07);
  border:       1px solid rgba(56, 189, 248, 0.2);
  border-radius: 4px;
  padding:      0.18rem 0.55rem;
  white-space:  nowrap;
}

.hint-fade-enter-active, .hint-fade-leave-active { transition: opacity 0.2s, transform 0.2s; }
.hint-fade-enter-from, .hint-fade-leave-to       { opacity: 0; transform: translateY(-4px); }
</style>
