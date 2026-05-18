<script setup>
/**
 * VideoDetailDrawer.vue — 沉浸式视频微调详情抽屉
 *
 * 以 position:fixed 全屏覆盖的方式展示，完全不触发路由跳转，
 * 父页面状态（滚动位置、DSL 编排、队列列表）全程零刷新、零重载。
 *
 * 与 VideoDetailView.vue 的核心区别：
 *   - 接收 assetHash prop 而非 useRoute().params.id
 *   - 发出 close 事件而非 router.push('/history')
 *   - 以 Teleport to="body" + slide-in 动画呈现
 */
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import axios from 'axios'
import { useAppStore } from '../stores/appStore'

const props = defineProps({
  assetHash: { type: String, required: true },
})
const emit = defineEmits(['close'])

const store = useAppStore()

// ── Remote data hydration ─────────────────────────────────────────────────
const isLoading  = ref(true)
const loadError  = ref('')
const videoUrl   = ref('')

const videoManifest = ref({
  video_id:   '',
  created_at: '',
  bgm:        '',
  roi_stats:  { spend: '--', ctr: '--', cvr: '--', hook_retention: '--' },
  blocks:     [],
})

async function fetchManifest(hash) {
  if (!hash) { isLoading.value = false; return }
  isLoading.value = true
  loadError.value = ''
  videoUrl.value  = ''
  try {
    const resp   = await axios.get(`${store.API_BASE}/api/v1/video/asset-info/${hash}`)
    const remote = resp.data

    if (remote.file_path) {
      videoUrl.value = store.buildVideoUrl(remote.file_path)
    }

    const manifest = remote.manifest
    if (manifest) {
      videoManifest.value = {
        ...videoManifest.value,
        ...manifest,
        created_at: remote.created_at
          ? new Date(remote.created_at).toLocaleString('zh')
          : videoManifest.value.created_at,
      }
      chatMessages.value = [{
        id: 1,
        role: 'ai',
        text: `基因配方已加载 [${manifest.video_id}]，共 ${manifest.blocks?.length ?? 0} 个剧情区块。选中区块后告诉我你想怎么修改？`,
      }]
    } else {
      videoManifest.value.video_id   = hash.slice(0, 12)
      videoManifest.value.created_at = new Date().toLocaleString('zh')
      loadError.value = '该视频的基因配方尚未生成，可能由旧版引擎产出。'
    }
  } catch (err) {
    videoManifest.value.video_id   = hash.slice(0, 12)
    videoManifest.value.created_at = new Date().toLocaleString('zh')
    if (err.response?.status === 404) {
      loadError.value = '该视频的基因配方尚未生成，可能由旧版引擎产出。'
    } else {
      loadError.value = err.message || '网络请求失败，已展示 Mock 数据。'
    }
  } finally {
    isLoading.value = false
  }
}

// hash 变化时重新加载
watch(() => props.assetHash, (h) => fetchManifest(h), { immediate: true })

// ── Copilot state ─────────────────────────────────────────────────────────
const selectedBlockId = ref(null)
const chatInput       = ref('')
const isAiTyping      = ref(false)
const chatMessagesEl  = ref(null)

const chatMessages = ref([{
  id: 1,
  role: 'ai',
  text: '你好，我是 DopaMatrix 引擎。选中左侧的剧情区块，告诉我你想怎么修改？',
}])

const selectedBlock = computed(() =>
  videoManifest.value.blocks.find(b => b.id === selectedBlockId.value) ?? null
)

async function scrollToBottom() {
  await nextTick()
  if (chatMessagesEl.value) chatMessagesEl.value.scrollTop = chatMessagesEl.value.scrollHeight
}

async function sendMessage() {
  const text = chatInput.value.trim()
  if (!text) return
  chatMessages.value.push({ id: Date.now(), role: 'user', text })
  chatInput.value = ''
  await scrollToBottom()
  isAiTyping.value = true
  await scrollToBottom()
  setTimeout(async () => {
    const blockLabel = selectedBlock.value
      ? getTypeLabel(selectedBlock.value.type) + ' (' + selectedBlock.value.id + ')'
      : '目标区块'
    chatMessages.value.push({
      id:   Date.now() + 1,
      role: 'ai',
      text: `指令已收到。正在重新调度 FFmpeg 渲染 ${blockLabel}，请稍候...`,
    })
    isAiTyping.value = false
    await scrollToBottom()
  }, 1500)
}

// ── ROI / type / emotion helpers ──────────────────────────────────────────
const roiCards = [
  { label: '广告消耗',   key: 'spend',         icon: '💸', color: '#f472b6' },
  { label: '点击率 CTR', key: 'ctr',            icon: '👆', color: '#38bdf8' },
  { label: '转化率 CVR', key: 'cvr',            icon: '🎯', color: '#a78bfa' },
  { label: '3s完播率',   key: 'hook_retention', icon: '🔥', color: '#4ade80' },
]

const emotionMap = {
  frustration: { label: '痛点',  color: '#f87171' },
  solution:    { label: '方案',  color: '#a78bfa' },
  urgency:     { label: '紧迫',  color: '#fb923c' },
  curiosity:   { label: '好奇',  color: '#38bdf8' },
  trust:       { label: '信任',  color: '#4ade80' },
}
const typeMap = {
  hook: { label: 'Hook', color: '#38bdf8' },
  body: { label: 'Body', color: '#a78bfa' },
  cta:  { label: 'CTA',  color: '#4ade80' },
}

function getEmotionStyle(emotion) {
  const e = emotionMap[emotion] || { label: emotion, color: '#94a3b8' }
  return { color: e.color, borderColor: e.color + '55', background: e.color + '18' }
}
function getEmotionLabel(emotion) {
  return (emotionMap[emotion] || { label: emotion }).label
}
function getTypeStyle(type) {
  return { color: (typeMap[type] || { color: '#94a3b8' }).color }
}
function getTypeLabel(type) {
  return (typeMap[type] || { label: type?.toUpperCase?.() ?? type }).label
}

// ── Keyboard: Escape → close ─────────────────────────────────────────────
function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', onKeydown))
import { onUnmounted } from 'vue'
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer-slide">
      <div class="drawer-root" role="dialog" aria-modal="true">

        <!-- 半透明遮罩（点击关闭）-->
        <div class="drawer-mask" @click="emit('close')" />

        <!-- 主体面板 -->
        <div class="drawer-panel">

          <!-- ══ LOADING ══════════════════════════════════════════════════════ -->
          <Transition name="vd-overlay">
            <div v-if="isLoading" class="vd-loading-overlay">
              <div class="vd-loader">
                <div class="loader-ring"></div>
                <div class="loader-ring loader-ring--2"></div>
                <div class="loader-ring loader-ring--3"></div>
              </div>
              <div class="loader-label">正在解析视频基因配方</div>
              <div class="loader-sub">{{ assetHash }}</div>
            </div>
          </Transition>

          <!-- ══ ERROR BANNER ═════════════════════════════════════════════════ -->
          <Transition name="vd-overlay">
            <div v-if="!isLoading && loadError" class="vd-error-banner">
              <span class="error-icon">⚠️</span>
              <span class="error-text">{{ loadError }}（已展示 Mock 数据）</span>
              <button class="error-dismiss" @click="loadError = ''">✕</button>
            </div>
          </Transition>

          <!-- ══ TOP NAV ══════════════════════════════════════════════════════ -->
          <header class="vd-topbar glass-panel">
            <button class="back-btn" @click="emit('close')">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="15 18 9 12 15 6"/>
              </svg>
              返回工作台
            </button>
            <div class="topbar-title">
              <span class="title-badge">VIDEO DNA</span>
              <span class="title-id">{{ videoManifest.video_id || assetHash.slice(0, 12) }}</span>
              <span class="title-meta">{{ videoManifest.created_at }}</span>
            </div>
            <div class="topbar-bgm">
              <span class="bgm-icon">🎵</span>
              <span class="bgm-name">{{ videoManifest.bgm || 'auto' }}</span>
            </div>
          </header>

          <!-- ══ THREE-COLUMN GRID ════════════════════════════════════════════ -->
          <div class="vd-grid">

            <!-- ── LEFT: Result & ROI ──────────────────────────────────────── -->
            <aside class="vd-col vd-col-left glass-panel">
              <div class="col-header">
                <span class="col-dot dot-cyan"></span>
                <span class="col-title">Result &amp; ROI</span>
              </div>

              <div class="player-wrap">
                <div class="player-frame">
                  <video
                    v-if="videoUrl"
                    class="player-video"
                    :src="videoUrl"
                    controls
                    playsinline
                    preload="metadata"
                  />
                  <div v-else class="player-inner">
                    <div class="player-icon">▶</div>
                    <div class="player-label">视频预览</div>
                    <div class="player-sub">{{ assetHash.slice(0, 12) }}</div>
                  </div>
                  <div class="player-scanline" />
                </div>
              </div>

              <div class="roi-grid">
                <div
                  v-for="card in roiCards"
                  :key="card.key"
                  class="roi-card"
                  :style="{ '--accent': card.color }"
                >
                  <div class="roi-icon">{{ card.icon }}</div>
                  <div class="roi-value">{{ videoManifest.roi_stats[card.key] }}</div>
                  <div class="roi-label">{{ card.label }}</div>
                  <div class="roi-bar"><div class="roi-bar-fill" /></div>
                </div>
              </div>
            </aside>

            <!-- ── CENTER: DNA Recipe ──────────────────────────────────────── -->
            <section class="vd-col vd-col-center glass-panel">
              <div class="col-header">
                <span class="col-dot dot-violet"></span>
                <span class="col-title">DNA Recipe</span>
                <span class="col-badge">{{ videoManifest.blocks.length }} 块</span>
              </div>

              <div class="dna-list">
                <div
                  v-for="(block, idx) in videoManifest.blocks"
                  :key="block.id"
                  class="dna-card"
                >
                  <div v-if="idx < videoManifest.blocks.length - 1" class="dna-connector" />
                  <div
                    class="dna-card-inner"
                    :class="{ 'dna-card-inner--selected': selectedBlockId === block.id }"
                    @click="selectedBlockId = block.id"
                  >
                    <div class="dna-index">{{ idx + 1 }}</div>
                    <div class="dna-thumb-wrap">
                      <img
                        v-if="block.thumb"
                        :src="block.thumb"
                        :alt="block.type"
                        class="dna-thumb"
                      />
                      <div v-else class="dna-thumb dna-thumb-placeholder" :style="getTypeStyle(block.type)">
                        <span class="dna-thumb-type">{{ getTypeLabel(block.type) }}</span>
                        <span class="dna-thumb-ts">{{ block.time?.split(' - ')[0] }}</span>
                      </div>
                      <div class="dna-time-badge">{{ block.time }}</div>
                    </div>
                    <div class="dna-info">
                      <div class="dna-info-top">
                        <span class="dna-type" :style="getTypeStyle(block.type)">{{ getTypeLabel(block.type) }}</span>
                        <span class="dna-emotion-tag" :style="getEmotionStyle(block.emotion)">{{ getEmotionLabel(block.emotion) }}</span>
                      </div>
                      <div class="dna-script">"{{ block.script }}"</div>
                      <div class="dna-id">{{ block.id }}</div>
                    </div>
                  </div>
                </div>

                <!-- 无数据时的占位 -->
                <div v-if="!isLoading && videoManifest.blocks.length === 0" class="dna-empty">
                  <span>暂无区块数据</span>
                </div>
              </div>
            </section>

            <!-- ── RIGHT: AI Copilot ───────────────────────────────────────── -->
            <aside class="vd-col vd-col-right glass-panel">
              <div class="col-header">
                <span class="col-dot dot-green"></span>
                <span class="col-title">AI Copilot</span>
              </div>

              <div class="chat-subheader">✨ AI 局部重铸 <span class="chat-subheader-en">Fine-Tuning</span></div>

              <div class="chat-messages" ref="chatMessagesEl">
                <template v-for="msg in chatMessages" :key="msg.id">
                  <div :class="['chat-bubble', msg.role === 'ai' ? 'bubble-ai' : 'bubble-user']">
                    <div v-if="msg.role === 'ai'" class="bubble-avatar">🤖</div>
                    <div class="bubble-text">{{ msg.text }}</div>
                    <div v-if="msg.role === 'user'" class="bubble-avatar bubble-avatar--user">👤</div>
                  </div>
                </template>
                <div v-if="isAiTyping" class="chat-bubble bubble-ai">
                  <div class="bubble-avatar">🤖</div>
                  <div class="bubble-text typing-dots">
                    <span /><span /><span />
                  </div>
                </div>
              </div>

              <div class="chat-input-wrap">
                <Transition name="ctx-tag">
                  <div v-if="selectedBlock" class="chat-ctx-tag">
                    🎯 正在重铸:
                    <span class="ctx-tag-type" :style="getTypeStyle(selectedBlock.type)">{{ getTypeLabel(selectedBlock.type) }}</span>
                    <span class="ctx-tag-id">{{ selectedBlock.id }}</span>
                  </div>
                </Transition>
                <div class="chat-input-row">
                  <textarea
                    v-model="chatInput"
                    class="chat-textarea"
                    placeholder="输入改写指令，例如：把 Hook 改得更有情绪张力..."
                    rows="3"
                    @keydown.enter.exact.prevent="sendMessage"
                  />
                  <button
                    class="chat-send-btn"
                    :class="{ 'chat-send-btn--active': chatInput.trim().length > 0 }"
                    @click="sendMessage"
                    :disabled="isAiTyping"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="2.5"
                         stroke-linecap="round" stroke-linejoin="round">
                      <line x1="22" y1="2" x2="11" y2="13"/>
                      <polygon points="22 2 15 22 11 13 2 9 22 2"/>
                    </svg>
                  </button>
                </div>
                <div class="chat-hint">⏎ Enter 发送 · 选中区块后精准重铸</div>
              </div>
            </aside>

          </div><!-- .vd-grid -->

        </div><!-- .drawer-panel -->
      </div><!-- .drawer-root -->
    </Transition>
  </Teleport>
</template>

<style scoped>
/* ── Drawer root + mask ──────────────────────────────────────────────────── */
.drawer-root {
  position: fixed;
  inset:    0;
  z-index:  9999;
  display:  flex;
}

.drawer-mask {
  position:   absolute;
  inset:      0;
  background: rgba(2, 6, 20, 0.65);
  backdrop-filter: blur(4px);
}

/* ── Slide-in panel ──────────────────────────────────────────────────────── */
.drawer-panel {
  position:        relative;
  margin-left:     auto;
  width:           min(1400px, 96vw);
  height:          100%;
  background:      #0d1526;
  display:         flex;
  flex-direction:  column;
  gap:             10px;
  padding:         10px 12px 12px;
  box-sizing:      border-box;
  overflow:        hidden;
  box-shadow:      -8px 0 40px rgba(0, 0, 0, 0.6);
  border-left:     1px solid rgba(99, 102, 241, 0.2);
}

/* ── Slide transition ────────────────────────────────────────────────────── */
.drawer-slide-enter-active {
  transition: opacity 0.22s ease, transform 0.28s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}
.drawer-slide-leave-active {
  transition: opacity 0.18s ease, transform 0.22s cubic-bezier(0.55, 0, 1, 0.45);
}
.drawer-slide-enter-from,
.drawer-slide-leave-to {
  opacity:   0;
  transform: translateX(60px);
}

/* ── Shared glass panel ──────────────────────────────────────────────────── */
.glass-panel {
  background:      rgba(15, 23, 42, 0.7);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border:          1px solid rgba(255, 255, 255, 0.07);
  border-radius:   14px;
}

/* ── Top nav ─────────────────────────────────────────────────────────────── */
.vd-topbar {
  display:     flex;
  align-items: center;
  gap:         16px;
  padding:     8px 16px;
  flex-shrink: 0;
  border-radius: 10px;
}
.back-btn {
  display:     flex;
  align-items: center;
  gap:         6px;
  padding:     5px 14px;
  background:  rgba(56, 189, 248, 0.1);
  border:      1px solid rgba(56, 189, 248, 0.3);
  border-radius: 8px;
  color:       #38bdf8;
  font-size:   0.78rem;
  font-weight: 600;
  cursor:      pointer;
  transition:  background 0.15s, border-color 0.15s;
  white-space: nowrap;
}
.back-btn:hover { background: rgba(56, 189, 248, 0.2); border-color: rgba(56, 189, 248, 0.6); }

.topbar-title { display: flex; align-items: center; gap: 10px; flex: 1; }
.title-badge {
  font-size: 0.62rem; font-weight: 700; letter-spacing: 0.12em;
  padding: 2px 7px; border-radius: 5px;
  background: rgba(167, 139, 250, 0.15); border: 1px solid rgba(167, 139, 250, 0.35);
  color: #a78bfa;
}
.title-id {
  font-size: 0.95rem; font-weight: 700; color: #e2e8f0;
  font-family: 'Courier New', monospace;
}
.title-meta { font-size: 0.7rem; color: #475569; }
.topbar-bgm { display: flex; align-items: center; gap: 6px; font-size: 0.72rem; color: #64748b; margin-left: auto; }
.bgm-icon  { font-size: 0.82rem; }
.bgm-name  { font-family: 'Courier New', monospace; color: #94a3b8; }

/* ── Three-column grid ───────────────────────────────────────────────────── */
.vd-grid {
  display:               grid;
  grid-template-columns: 300px 1fr 330px;
  gap:                   10px;
  flex:                  1;
  min-height:            0;
}
.vd-col {
  display:        flex;
  flex-direction: column;
  gap:            12px;
  padding:        14px;
  overflow:       hidden;
}

/* ── Column header ───────────────────────────────────────────────────────── */
.col-header { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.col-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot-cyan   { background: #38bdf8; box-shadow: 0 0 6px #38bdf8; }
.dot-violet { background: #a78bfa; box-shadow: 0 0 6px #a78bfa; }
.dot-green  { background: #4ade80; box-shadow: 0 0 6px #4ade80; }
.col-title {
  font-size: 0.78rem; font-weight: 700; letter-spacing: 0.1em;
  text-transform: uppercase; color: #94a3b8;
}
.col-badge {
  margin-left: auto; font-size: 0.65rem; padding: 1px 7px; border-radius: 20px;
  background: rgba(167, 139, 250, 0.12); border: 1px solid rgba(167, 139, 250, 0.25); color: #a78bfa;
}

/* ── LEFT: video player ──────────────────────────────────────────────────── */
.player-wrap { display: flex; justify-content: center; flex-shrink: 0; }
.player-frame {
  position: relative; width: 120px; aspect-ratio: 9/16;
  background: #000; border-radius: 10px;
  border: 1px solid rgba(56, 189, 248, 0.25);
  overflow: hidden;
  box-shadow: 0 0 20px rgba(56, 189, 248, 0.1), inset 0 0 24px rgba(0,0,0,0.5);
}
.player-video { width: 100%; height: 100%; object-fit: contain; display: block; background: #000; }
.player-inner { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; gap: 6px; }
.player-icon  { font-size: 1.6rem; color: rgba(56, 189, 248, 0.45); line-height: 1; }
.player-label { font-size: 0.65rem; color: #475569; font-weight: 600; letter-spacing: 0.04em; }
.player-sub   { font-size: 0.58rem; color: #334155; font-family: 'Courier New', monospace; }
.player-scanline {
  position: absolute; inset: 0; pointer-events: none;
  background: repeating-linear-gradient(0deg, transparent, transparent 2px,
    rgba(255,255,255,0.012) 2px, rgba(255,255,255,0.012) 4px);
}

/* ── ROI cards ───────────────────────────────────────────────────────────── */
.roi-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
.roi-card {
  position: relative; padding: 9px; border-radius: 9px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255,255,255,0.06); overflow: hidden;
  transition: border-color 0.2s;
}
.roi-card:hover { border-color: var(--accent, #38bdf8); }
.roi-icon  { font-size: 0.95rem; line-height: 1; margin-bottom: 3px; }
.roi-value { font-size: 1.1rem; font-weight: 700; color: var(--accent, #e2e8f0); font-family: 'Courier New', monospace; line-height: 1.1; }
.roi-label { font-size: 0.6rem; color: #64748b; margin-top: 2px; font-weight: 600; letter-spacing: 0.04em; }
.roi-bar   { position: absolute; bottom: 0; left: 0; right: 0; height: 2px; background: rgba(255,255,255,0.05); }
.roi-bar-fill { height: 100%; width: 65%; background: var(--accent, #38bdf8); opacity: 0.6; border-radius: 2px; }

/* ── CENTER: DNA blocks ──────────────────────────────────────────────────── */
.vd-col-center { overflow: hidden; }
.dna-list {
  display: flex; flex-direction: column; gap: 0;
  overflow-y: auto; flex: 1; padding-right: 4px;
  scrollbar-width: thin; scrollbar-color: rgba(167, 139, 250, 0.3) transparent;
}
.dna-list::-webkit-scrollbar { width: 4px; }
.dna-list::-webkit-scrollbar-track { background: transparent; }
.dna-list::-webkit-scrollbar-thumb { background: rgba(167, 139, 250, 0.3); border-radius: 4px; }

.dna-card { position: relative; padding-bottom: 10px; }
.dna-connector {
  position: absolute; left: 20px; bottom: 0;
  top: calc(100% - 10px); width: 2px;
  background: linear-gradient(to bottom, rgba(167, 139, 250, 0.4), rgba(167, 139, 250, 0.1));
}
.dna-card-inner {
  display: flex; align-items: flex-start; gap: 10px; padding: 11px;
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255,255,255,0.06); border-radius: 10px;
  transition: border-color 0.2s, background 0.2s, box-shadow 0.2s; cursor: pointer;
}
.dna-card-inner:hover { border-color: rgba(167, 139, 250, 0.35); background: rgba(167, 139, 250, 0.05); }
.dna-card-inner--selected {
  border-color: rgba(56, 189, 248, 0.6) !important;
  background: rgba(56, 189, 248, 0.07) !important;
  box-shadow: 0 0 15px rgba(56, 189, 248, 0.35), inset 0 0 12px rgba(56, 189, 248, 0.06);
}
.dna-index {
  width: 22px; height: 22px; border-radius: 50%;
  background: rgba(167, 139, 250, 0.15); border: 1px solid rgba(167, 139, 250, 0.3);
  color: #a78bfa; font-size: 0.68rem; font-weight: 700;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px;
}
.dna-thumb-wrap { position: relative; flex-shrink: 0; }
.dna-thumb {
  width: 52px; height: 52px; object-fit: cover; border-radius: 7px;
  border: 1px solid rgba(255,255,255,0.08); display: block;
}
.dna-thumb-placeholder {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 3px; background: rgba(15, 23, 42, 0.75);
}
.dna-thumb-type { font-size: 0.58rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
.dna-thumb-ts   { font-size: 0.5rem; color: rgba(255,255,255,0.45); font-family: 'Courier New', monospace; }
.dna-time-badge {
  position: absolute; bottom: 2px; left: 0; right: 0; text-align: center;
  font-size: 0.5rem; font-weight: 700; color: rgba(255,255,255,0.8);
  background: rgba(0,0,0,0.65); padding: 1px 3px;
  border-radius: 0 0 6px 6px; letter-spacing: 0.03em; font-family: 'Courier New', monospace;
}
.dna-info { flex: 1; min-width: 0; }
.dna-info-top { display: flex; align-items: center; gap: 6px; margin-bottom: 5px; flex-wrap: wrap; }
.dna-type     { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
.dna-emotion-tag { font-size: 0.6rem; font-weight: 600; padding: 1px 6px; border-radius: 20px; border: 1px solid; letter-spacing: 0.04em; }
.dna-script   { font-size: 0.78rem; color: #cbd5e1; line-height: 1.5; font-style: italic; word-break: break-all; }
.dna-id       { margin-top: 4px; font-size: 0.56rem; color: #334155; font-family: 'Courier New', monospace; }
.dna-empty    { display: flex; align-items: center; justify-content: center; height: 80px; color: #475569; font-size: 0.78rem; }

/* ── RIGHT: Copilot ──────────────────────────────────────────────────────── */
.vd-col-right { gap: 9px; }
.chat-subheader {
  font-size: 0.75rem; font-weight: 700; color: #94a3b8;
  letter-spacing: 0.06em; flex-shrink: 0;
  padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.05);
}
.chat-subheader-en { font-weight: 400; color: #475569; margin-left: 4px; font-size: 0.65rem; }

.chat-messages {
  flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 9px;
  padding-right: 4px;
  scrollbar-width: thin; scrollbar-color: rgba(74, 222, 128, 0.25) transparent;
}
.chat-messages::-webkit-scrollbar { width: 3px; }
.chat-messages::-webkit-scrollbar-track { background: transparent; }
.chat-messages::-webkit-scrollbar-thumb { background: rgba(74, 222, 128, 0.25); border-radius: 4px; }

.chat-bubble { display: flex; align-items: flex-start; gap: 8px; max-width: 100%; }
.bubble-ai   { flex-direction: row; }
.bubble-user { flex-direction: row-reverse; }
.bubble-avatar { font-size: 0.95rem; line-height: 1; flex-shrink: 0; margin-top: 2px; }
.bubble-avatar--user { order: 1; }
.bubble-text {
  padding: 7px 11px; border-radius: 12px; font-size: 0.76rem; line-height: 1.55;
  max-width: calc(100% - 36px); word-break: break-word;
}
.bubble-ai   .bubble-text { background: rgba(74, 222, 128, 0.08); border: 1px solid rgba(74, 222, 128, 0.18); color: #cbd5e1; border-radius: 4px 12px 12px 12px; }
.bubble-user .bubble-text { background: rgba(56, 189, 248, 0.1);  border: 1px solid rgba(56, 189, 248, 0.22); color: #e2e8f0; border-radius: 12px 4px 12px 12px; }

.typing-dots { display: flex; align-items: center; gap: 4px; padding: 11px 13px; }
.typing-dots span {
  display: inline-block; width: 5px; height: 5px; border-radius: 50%;
  background: #4ade80; animation: dot-blink 1.2s ease-in-out infinite;
}
.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes dot-blink { 0%,80%,100% { opacity: 0.2; transform: scale(0.8); } 40% { opacity: 1; transform: scale(1.1); } }

.chat-input-wrap { flex-shrink: 0; display: flex; flex-direction: column; gap: 5px; }
.chat-ctx-tag {
  display: flex; align-items: center; gap: 5px;
  font-size: 0.63rem; color: #94a3b8;
  background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.2);
  padding: 3px 9px; border-radius: 6px;
}
.ctx-tag-type { font-weight: 700; }
.ctx-tag-id   { font-family: 'Courier New', monospace; color: #475569; }
.ctx-tag-enter-active { transition: opacity 0.2s, transform 0.2s; }
.ctx-tag-leave-active { transition: opacity 0.15s; }
.ctx-tag-enter-from   { opacity: 0; transform: translateY(-4px); }
.ctx-tag-leave-to     { opacity: 0; }

.chat-input-row { display: flex; gap: 7px; align-items: flex-end; }
.chat-textarea {
  flex: 1; background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255,255,255,0.08); border-radius: 10px;
  color: #e2e8f0; font-size: 0.76rem; line-height: 1.5;
  padding: 7px 11px; resize: none; outline: none; font-family: inherit;
  transition: border-color 0.15s;
}
.chat-textarea::placeholder { color: #334155; }
.chat-textarea:focus { border-color: rgba(56, 189, 248, 0.4); }
.chat-send-btn {
  flex-shrink: 0; width: 36px; height: 36px; border-radius: 10px; border: none;
  background: rgba(255,255,255,0.06); color: #475569;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; transition: background 0.2s, color 0.2s, box-shadow 0.2s;
}
.chat-send-btn--active {
  background: linear-gradient(135deg, #38bdf8, #a78bfa);
  color: #fff; box-shadow: 0 0 14px rgba(56, 189, 248, 0.4);
}
.chat-send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.chat-hint { font-size: 0.58rem; color: #1e293b; text-align: right; letter-spacing: 0.04em; }

/* ── Loading overlay ─────────────────────────────────────────────────────── */
.vd-loading-overlay {
  position: absolute; inset: 0; z-index: 100;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px;
  background: rgba(5, 10, 24, 0.9); backdrop-filter: blur(8px); border-radius: 0;
}
.vd-loader { position: relative; width: 60px; height: 60px; }
.loader-ring {
  position: absolute; inset: 0; border-radius: 50%;
  border: 2px solid transparent; border-top-color: #38bdf8;
  animation: spin 1.1s linear infinite;
}
.loader-ring--2 { inset: 10px; border-top-color: #a78bfa; animation-duration: 0.75s; animation-direction: reverse; }
.loader-ring--3 { inset: 20px; border-top-color: #4ade80; animation-duration: 1.5s; }
@keyframes spin { to { transform: rotate(360deg); } }
.loader-label { font-size: 0.8rem; font-weight: 600; color: #94a3b8; letter-spacing: 0.08em; }
.loader-sub   { font-size: 0.62rem; color: #334155; font-family: 'Courier New', monospace; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── Error banner ────────────────────────────────────────────────────────── */
.vd-error-banner {
  display: flex; align-items: center; gap: 9px;
  padding: 7px 14px; border-radius: 9px;
  background: rgba(251, 146, 60, 0.1); border: 1px solid rgba(251, 146, 60, 0.3); flex-shrink: 0;
}
.error-icon   { font-size: 0.88rem; flex-shrink: 0; }
.error-text   { font-size: 0.73rem; color: #fdba74; flex: 1; }
.error-dismiss {
  background: none; border: none; color: #64748b;
  cursor: pointer; font-size: 0.73rem; padding: 2px 6px;
  border-radius: 4px; transition: color 0.15s;
}
.error-dismiss:hover { color: #94a3b8; }

.vd-overlay-enter-active { transition: opacity 0.25s ease; }
.vd-overlay-leave-active { transition: opacity 0.2s ease; }
.vd-overlay-enter-from, .vd-overlay-leave-to { opacity: 0; }
</style>
