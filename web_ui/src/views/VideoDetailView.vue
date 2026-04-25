<script setup>
import { ref, computed, nextTick, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import axios from 'axios'
import { useAppStore } from '../stores/appStore'

const router = useRouter()
const route  = useRoute()
const store  = useAppStore()

// ── Remote data hydration ──────────────────────────────────────────────────────
const isLoading = ref(true)
const loadError = ref('')
const videoUrl   = ref('')

async function fetchManifest() {
  const fileHash = route.params.id
  if (!fileHash) {
    isLoading.value = false
    return
  }
  try {
    // asset-info 同时返回 file_path（视频流 URL 拼接用）和 manifest（配方数据）
    const resp = await axios.get(
      `${store.API_BASE}/api/v1/video/asset-info/${fileHash}`
    )
    const remote = resp.data

    // ── 1. 视频流 URL：用 store.buildVideoUrl 统一走流式代理端点 ──
    if (remote.file_path) {
      videoUrl.value = store.buildVideoUrl(remote.file_path)
    }

    // ── 2. 配方数据注水 ──
    const manifest = remote.manifest
    if (manifest) {
      videoManifest.value = {
        ...videoManifest.value,  // 保留 roi_stats 等本地占位
        ...manifest,
        // 如果后端返回了资产创建时间，格式化后覆盖 mock 的 created_at
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
      loadError.value = '该视频的基因配方尚未生成，可能由旧版引擎产出。'
    }
  } catch (err) {
    if (err.response?.status === 404) {
      loadError.value = '该视频的基因配方尚未生成，可能由旧版引擎产出。'
    } else {
      loadError.value = err.message || '网络请求失败，已展示 Mock 数据。'
    }
  } finally {
    isLoading.value = false
  }
}

// ── Copilot state ─────────────────────────────────────────────────────────────
const selectedBlockId = ref(null)
const chatInput       = ref('')
const isAiTyping      = ref(false)
const chatMessagesEl  = ref(null)

const chatMessages = ref([
  {
    id: 1,
    role: 'ai',
    text: '你好，我是 DopaMatrix 引擎。选中左侧的剧情区块，告诉我你想怎么修改？',
  },
])

const selectedBlock = computed(() =>
  videoManifest.value.blocks.find(b => b.id === selectedBlockId.value) ?? null
)

async function scrollToBottom() {
  await nextTick()
  if (chatMessagesEl.value) {
    chatMessagesEl.value.scrollTop = chatMessagesEl.value.scrollHeight
  }
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
      id: Date.now() + 1,
      role: 'ai',
      text: `指令已收到。正在重新调度 FFmpeg 渲染 ${blockLabel}，请稍候...`,
    })
    isAiTyping.value = false
    await scrollToBottom()
  }, 1500)
}

const videoManifest = ref({
  video_id: 'vid_9942X',
  created_at: '2026-04-02 14:30',
  bgm: 'epic_cyberpunk_01.mp3',
  roi_stats: { spend: '$24.50', ctr: '4.8%', cvr: '2.1%', hook_retention: '72%' },
  blocks: [
    {
      id: 'b1',
      type: 'hook',
      time: '00:00 - 00:03',
      emotion: 'frustration',
      script: '又被TikTok限流了？',
      thumb: 'https://via.placeholder.com/150/1e293b/38bdf8?text=Hook',
    },
    {
      id: 'b2',
      type: 'body',
      time: '00:03 - 00:12',
      emotion: 'solution',
      script: '其实你只是没用对自动化矩阵引擎...',
      thumb: 'https://via.placeholder.com/150/1e293b/a78bfa?text=Body',
    },
    {
      id: 'b3',
      type: 'cta',
      time: '00:12 - 00:15',
      emotion: 'urgency',
      script: '点击左下角，立即获取免费算力！',
      thumb: 'https://via.placeholder.com/150/1e293b/4ade80?text=CTA',
    },
  ],
})

onMounted(fetchManifest)

const roiCards = [
  { label: '广告消耗',   key: 'spend',          icon: '💸', color: '#f472b6' },
  { label: '点击率 CTR', key: 'ctr',             icon: '👆', color: '#38bdf8' },
  { label: '转化率 CVR', key: 'cvr',             icon: '🎯', color: '#a78bfa' },
  { label: '3s完播率',   key: 'hook_retention',  icon: '🔥', color: '#4ade80' },
]

const emotionMap = {
  frustration: { label: '痛点',  color: '#f87171' },
  solution:    { label: '方案',  color: '#a78bfa' },
  urgency:     { label: '紧迫',  color: '#fb923c' },
  curiosity:   { label: '好奇',  color: '#38bdf8' },
  trust:       { label: '信任',  color: '#4ade80' },
}

const typeMap = {
  hook: { label: 'Hook',  color: '#38bdf8' },
  body: { label: 'Body',  color: '#a78bfa' },
  cta:  { label: 'CTA',   color: '#4ade80' },
}

function getEmotionStyle(emotion) {
  const e = emotionMap[emotion] || { label: emotion, color: '#94a3b8' }
  return { color: e.color, borderColor: e.color + '55', background: e.color + '18' }
}
function getEmotionLabel(emotion) {
  return (emotionMap[emotion] || { label: emotion }).label
}
function getTypeStyle(type) {
  const t = typeMap[type] || { color: '#94a3b8' }
  return { color: t.color }
}
function getTypeLabel(type) {
  return (typeMap[type] || { label: type.toUpperCase() }).label
}
</script>

<template>
  <div class="vd-root">

    <!-- ══ LOADING OVERLAY ══════════════════════════════════════════════════ -->
    <Transition name="vd-overlay">
      <div v-if="isLoading" class="vd-loading-overlay">
        <div class="vd-loader">
          <div class="loader-ring"></div>
          <div class="loader-ring loader-ring--2"></div>
          <div class="loader-ring loader-ring--3"></div>
        </div>
        <div class="loader-label">正在解析视频基因配方</div>
        <div class="loader-sub">{{ route.params.id }}</div>
      </div>
    </Transition>

    <!-- ══ ERROR BANNER ══════════════════════════════════════════════════════ -->
    <Transition name="vd-overlay">
      <div v-if="!isLoading && loadError" class="vd-error-banner">
        <span class="error-icon">⚠️</span>
        <span class="error-text">{{ loadError }}（已展示 Mock 数据）</span>
        <button class="error-dismiss" @click="loadError = ''">✕</button>
      </div>
    </Transition>

    <!-- ══ TOP NAV ══════════════════════════════════════════════════════════ -->
    <header class="vd-topbar glass-panel">
      <button class="back-btn" @click="router.push('/history')">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"/>
        </svg>
        返回矩阵工厂
      </button>
      <div class="topbar-title">
        <span class="title-badge">VIDEO DNA</span>
        <span class="title-id">{{ videoManifest.video_id }}</span>
        <span class="title-meta">{{ videoManifest.created_at }}</span>
      </div>
      <div class="topbar-bgm">
        <span class="bgm-icon">🎵</span>
        <span class="bgm-name">{{ videoManifest.bgm }}</span>
      </div>
    </header>

    <!-- ══ THREE-COLUMN GRID ════════════════════════════════════════════════ -->
    <div class="vd-grid">

      <!-- ── LEFT: Result & ROI ──────────────────────────────────────────── -->
      <aside class="vd-col vd-col-left glass-panel">
        <div class="col-header">
          <span class="col-dot dot-cyan"></span>
          <span class="col-title">Result & ROI</span>
        </div>

        <!-- 9:16 video player -->
        <div class="player-wrap">
          <div class="player-frame">
            <!-- 真实视频流：仅在 videoUrl 就绪后挂载，防止空 src 导致播放器初始化失败 -->
            <video
              v-if="videoUrl"
              class="player-video"
              :src="videoUrl"
              controls
              playsinline
              preload="metadata"
            ></video>
            <!-- 降级占位：数据加载中或接口未返回 file_path 时展示 -->
            <div v-else class="player-inner">
              <div class="player-icon">▶</div>
              <div class="player-label">视频预览</div>
              <div class="player-sub">{{ videoManifest.video_id }}</div>
            </div>
            <div class="player-scanline"></div>
          </div>
        </div>

        <!-- ROI stat cards -->
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
            <div class="roi-bar">
              <div class="roi-bar-fill"></div>
            </div>
          </div>
        </div>
      </aside>

      <!-- ── CENTER: DNA Recipe ──────────────────────────────────────────── -->
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
            <!-- connector line between cards -->
            <div v-if="idx < videoManifest.blocks.length - 1" class="dna-connector"></div>

            <div
              class="dna-card-inner"
              :class="{ 'dna-card-inner--selected': selectedBlockId === block.id }"
              @click="selectedBlockId = block.id"
            >
              <!-- index bubble -->
              <div class="dna-index">{{ idx + 1 }}</div>

              <!-- thumbnail：thumb 为空时展示占位块，避免空 src 触发裂图 -->
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

              <!-- info -->
              <div class="dna-info">
                <div class="dna-info-top">
                  <span class="dna-type" :style="getTypeStyle(block.type)">
                    {{ getTypeLabel(block.type) }}
                  </span>
                  <span class="dna-emotion-tag" :style="getEmotionStyle(block.emotion)">
                    {{ getEmotionLabel(block.emotion) }}
                  </span>
                </div>
                <div class="dna-script">"{{ block.script }}"</div>
                <div class="dna-id">{{ block.id }}</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ── RIGHT: AI Copilot ───────────────────────────────────────────── -->
      <aside class="vd-col vd-col-right glass-panel">
        <div class="col-header">
          <span class="col-dot dot-green"></span>
          <span class="col-title">AI Copilot</span>
        </div>

        <!-- chat header -->
        <div class="chat-subheader">✨ AI 局部重铸 <span class="chat-subheader-en">Fine-Tuning</span></div>

        <!-- message list -->
        <div class="chat-messages" ref="chatMessagesEl">
          <template v-for="msg in chatMessages" :key="msg.id">
            <div :class="['chat-bubble', msg.role === 'ai' ? 'bubble-ai' : 'bubble-user']">
              <div v-if="msg.role === 'ai'" class="bubble-avatar">🤖</div>
              <div class="bubble-text">{{ msg.text }}</div>
              <div v-if="msg.role === 'user'" class="bubble-avatar bubble-avatar--user">👤</div>
            </div>
          </template>

          <!-- typing indicator -->
          <div v-if="isAiTyping" class="chat-bubble bubble-ai">
            <div class="bubble-avatar">🤖</div>
            <div class="bubble-text typing-dots">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>

        <!-- input area -->
        <div class="chat-input-wrap">
          <!-- context tag -->
          <Transition name="ctx-tag">
            <div v-if="selectedBlock" class="chat-ctx-tag">
              🎯 正在重铸:
              <span class="ctx-tag-type" :style="getTypeStyle(selectedBlock.type)">
                {{ getTypeLabel(selectedBlock.type) }}
              </span>
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
            ></textarea>
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

    </div>
  </div>
</template>

<style scoped>
/* ── Root layout ──────────────────────────────────────────────────────────── */
.vd-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 12px;
  padding: 0;
  box-sizing: border-box;
  overflow: hidden;
}

/* ── Shared glass panel ───────────────────────────────────────────────────── */
.glass-panel {
  background: rgba(15, 23, 42, 0.7);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 14px;
}

/* ── Top navigation bar ───────────────────────────────────────────────────── */
.vd-topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 20px;
  flex-shrink: 0;
  border-radius: 12px;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: rgba(56, 189, 248, 0.1);
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 8px;
  color: #38bdf8;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  white-space: nowrap;
}
.back-btn:hover {
  background: rgba(56, 189, 248, 0.2);
  border-color: rgba(56, 189, 248, 0.6);
}

.topbar-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
}
.title-badge {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  padding: 3px 8px;
  border-radius: 5px;
  background: rgba(167, 139, 250, 0.15);
  border: 1px solid rgba(167, 139, 250, 0.35);
  color: #a78bfa;
}
.title-id {
  font-size: 1rem;
  font-weight: 700;
  color: #e2e8f0;
  font-family: 'Courier New', monospace;
}
.title-meta {
  font-size: 0.72rem;
  color: #475569;
}

.topbar-bgm {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: #64748b;
  margin-left: auto;
}
.bgm-icon { font-size: 0.85rem; }
.bgm-name {
  font-family: 'Courier New', monospace;
  color: #94a3b8;
}

/* ── Three-column grid ───────────────────────────────────────────────────── */
.vd-grid {
  display: grid;
  grid-template-columns: 320px 1fr 350px;
  gap: 12px;
  flex: 1;
  min-height: 0;
}

.vd-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  overflow: hidden;
}

/* ── Column header ───────────────────────────────────────────────────────── */
.col-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.col-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-cyan   { background: #38bdf8; box-shadow: 0 0 6px #38bdf8; }
.dot-violet { background: #a78bfa; box-shadow: 0 0 6px #a78bfa; }
.dot-green  { background: #4ade80; box-shadow: 0 0 6px #4ade80; }

.col-title {
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #94a3b8;
}
.col-badge {
  margin-left: auto;
  font-size: 0.68rem;
  padding: 2px 8px;
  border-radius: 20px;
  background: rgba(167, 139, 250, 0.12);
  border: 1px solid rgba(167, 139, 250, 0.25);
  color: #a78bfa;
}

/* ── LEFT col: video player ──────────────────────────────────────────────── */
.player-wrap {
  display: flex;
  justify-content: center;
  flex-shrink: 0;
}
.player-frame {
  position: relative;
  width: 130px;
  aspect-ratio: 9 / 16;
  background: #000;
  border-radius: 10px;
  border: 1px solid rgba(56, 189, 248, 0.25);
  overflow: hidden;
  box-shadow: 0 0 20px rgba(56, 189, 248, 0.12), inset 0 0 30px rgba(0, 0, 0, 0.5);
}
.player-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
  background: #000;
}

.player-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 6px;
}
.player-icon {
  font-size: 1.8rem;
  color: rgba(56, 189, 248, 0.5);
  line-height: 1;
}
.player-label {
  font-size: 0.68rem;
  color: #475569;
  font-weight: 600;
  letter-spacing: 0.05em;
}
.player-sub {
  font-size: 0.6rem;
  color: #334155;
  font-family: 'Courier New', monospace;
}
/* scanline effect */
.player-scanline {
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(255, 255, 255, 0.015) 2px,
    rgba(255, 255, 255, 0.015) 4px
  );
  pointer-events: none;
}

/* ── LEFT col: ROI cards ─────────────────────────────────────────────────── */
.roi-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.roi-card {
  position: relative;
  padding: 10px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.06);
  overflow: hidden;
  transition: border-color 0.2s;
}
.roi-card:hover {
  border-color: var(--accent, #38bdf8);
}
.roi-icon { font-size: 1rem; line-height: 1; margin-bottom: 4px; }
.roi-value {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--accent, #e2e8f0);
  line-height: 1.1;
  font-family: 'Courier New', monospace;
}
.roi-label {
  font-size: 0.62rem;
  color: #64748b;
  margin-top: 2px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.roi-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: rgba(255, 255, 255, 0.05);
}
.roi-bar-fill {
  height: 100%;
  width: 65%;
  background: var(--accent, #38bdf8);
  opacity: 0.6;
  border-radius: 2px;
}

/* ── CENTER col: DNA blocks ──────────────────────────────────────────────── */
.vd-col-center { overflow: hidden; }

.dna-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  overflow-y: auto;
  flex: 1;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(167, 139, 250, 0.3) transparent;
}
.dna-list::-webkit-scrollbar { width: 4px; }
.dna-list::-webkit-scrollbar-track { background: transparent; }
.dna-list::-webkit-scrollbar-thumb {
  background: rgba(167, 139, 250, 0.3);
  border-radius: 4px;
}

.dna-card {
  position: relative;
  padding-bottom: 12px;
}
.dna-connector {
  position: absolute;
  left: 20px;
  bottom: 0;
  top: calc(100% - 12px);
  width: 2px;
  background: linear-gradient(to bottom, rgba(167, 139, 250, 0.4), rgba(167, 139, 250, 0.1));
}

.dna-card-inner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  transition: border-color 0.2s, background 0.2s, box-shadow 0.2s;
  cursor: pointer;
}
.dna-card-inner:hover {
  border-color: rgba(167, 139, 250, 0.35);
  background: rgba(167, 139, 250, 0.05);
}
.dna-card-inner--selected {
  border-color: rgba(56, 189, 248, 0.6) !important;
  background: rgba(56, 189, 248, 0.07) !important;
  box-shadow: 0 0 15px rgba(56, 189, 248, 0.4), inset 0 0 12px rgba(56, 189, 248, 0.06);
}

.dna-index {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(167, 139, 250, 0.15);
  border: 1px solid rgba(167, 139, 250, 0.3);
  color: #a78bfa;
  font-size: 0.7rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.dna-thumb-wrap {
  position: relative;
  flex-shrink: 0;
}
.dna-thumb {
  width: 54px;
  height: 54px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  display: block;
}
.dna-thumb-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  background: rgba(15, 23, 42, 0.75);
}
.dna-thumb-type {
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.dna-thumb-ts {
  font-size: 0.5rem;
  color: rgba(255, 255, 255, 0.45);
  font-family: 'Courier New', monospace;
}

.dna-time-badge {
  position: absolute;
  bottom: 2px;
  left: 0;
  right: 0;
  text-align: center;
  font-size: 0.5rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.8);
  background: rgba(0, 0, 0, 0.65);
  padding: 1px 3px;
  border-radius: 0 0 6px 6px;
  letter-spacing: 0.03em;
  font-family: 'Courier New', monospace;
}

.dna-info { flex: 1; min-width: 0; }
.dna-info-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.dna-type {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.dna-emotion-tag {
  font-size: 0.62rem;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 20px;
  border: 1px solid;
  letter-spacing: 0.04em;
}
.dna-script {
  font-size: 0.8rem;
  color: #cbd5e1;
  line-height: 1.5;
  font-style: italic;
  word-break: break-all;
}
.dna-id {
  margin-top: 5px;
  font-size: 0.58rem;
  color: #334155;
  font-family: 'Courier New', monospace;
}

/* ── RIGHT col: Copilot chat ─────────────────────────────────────────────── */
.vd-col-right { gap: 10px; }

.chat-subheader {
  font-size: 0.78rem;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: 0.06em;
  flex-shrink: 0;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.chat-subheader-en {
  font-weight: 400;
  color: #475569;
  margin-left: 4px;
  font-size: 0.68rem;
}

/* message list */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(74, 222, 128, 0.25) transparent;
}
.chat-messages::-webkit-scrollbar { width: 3px; }
.chat-messages::-webkit-scrollbar-track { background: transparent; }
.chat-messages::-webkit-scrollbar-thumb {
  background: rgba(74, 222, 128, 0.25);
  border-radius: 4px;
}

.chat-bubble {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  max-width: 100%;
}
.bubble-ai  { flex-direction: row; }
.bubble-user { flex-direction: row-reverse; }

.bubble-avatar {
  font-size: 1rem;
  line-height: 1;
  flex-shrink: 0;
  margin-top: 2px;
}
.bubble-avatar--user { order: 1; }

.bubble-text {
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 0.78rem;
  line-height: 1.55;
  max-width: calc(100% - 36px);
  word-break: break-word;
}
.bubble-ai .bubble-text {
  background: rgba(74, 222, 128, 0.08);
  border: 1px solid rgba(74, 222, 128, 0.18);
  color: #cbd5e1;
  border-radius: 4px 12px 12px 12px;
}
.bubble-user .bubble-text {
  background: rgba(56, 189, 248, 0.1);
  border: 1px solid rgba(56, 189, 248, 0.22);
  color: #e2e8f0;
  border-radius: 12px 4px 12px 12px;
}

/* typing dots */
.typing-dots {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 14px;
}
.typing-dots span {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #4ade80;
  animation: dot-blink 1.2s ease-in-out infinite;
}
.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes dot-blink {
  0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); }
  40%           { opacity: 1;   transform: scale(1.1); }
}

/* input area */
.chat-input-wrap {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.chat-ctx-tag {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.65rem;
  color: #94a3b8;
  background: rgba(56, 189, 248, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.2);
  padding: 4px 10px;
  border-radius: 6px;
}
.ctx-tag-type { font-weight: 700; }
.ctx-tag-id {
  font-family: 'Courier New', monospace;
  color: #475569;
}

/* ctx-tag transition */
.ctx-tag-enter-active { transition: opacity 0.2s, transform 0.2s; }
.ctx-tag-leave-active { transition: opacity 0.15s; }
.ctx-tag-enter-from   { opacity: 0; transform: translateY(-4px); }
.ctx-tag-leave-to     { opacity: 0; }

.chat-input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.chat-textarea {
  flex: 1;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  color: #e2e8f0;
  font-size: 0.78rem;
  line-height: 1.5;
  padding: 8px 12px;
  resize: none;
  outline: none;
  font-family: inherit;
  transition: border-color 0.15s;
}
.chat-textarea::placeholder { color: #334155; }
.chat-textarea:focus {
  border-color: rgba(56, 189, 248, 0.4);
}

.chat-send-btn {
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  border: none;
  background: rgba(255, 255, 255, 0.06);
  color: #475569;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.2s, color 0.2s, box-shadow 0.2s;
}
.chat-send-btn--active {
  background: linear-gradient(135deg, #38bdf8, #a78bfa);
  color: #fff;
  box-shadow: 0 0 14px rgba(56, 189, 248, 0.45);
}
.chat-send-btn--active:hover {
  box-shadow: 0 0 20px rgba(56, 189, 248, 0.65);
}
.chat-send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.chat-hint {
  font-size: 0.6rem;
  color: #1e293b;
  text-align: right;
  letter-spacing: 0.04em;
}

/* ── Loading overlay ─────────────────────────────────────────────────────── */
.vd-loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 100;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  background: rgba(5, 10, 24, 0.88);
  backdrop-filter: blur(8px);
  border-radius: 14px;
}

.vd-loader {
  position: relative;
  width: 64px;
  height: 64px;
}
.loader-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2px solid transparent;
  border-top-color: #38bdf8;
  animation: spin 1.1s linear infinite;
}
.loader-ring--2 {
  inset: 10px;
  border-top-color: #a78bfa;
  animation-duration: 0.75s;
  animation-direction: reverse;
}
.loader-ring--3 {
  inset: 20px;
  border-top-color: #4ade80;
  animation-duration: 1.5s;
}

.loader-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: #94a3b8;
  letter-spacing: 0.08em;
}
.loader-sub {
  font-size: 0.64rem;
  color: #334155;
  font-family: 'Courier New', monospace;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Error banner ────────────────────────────────────────────────────────── */
.vd-error-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  border-radius: 10px;
  background: rgba(251, 146, 60, 0.1);
  border: 1px solid rgba(251, 146, 60, 0.3);
  flex-shrink: 0;
}
.error-icon { font-size: 0.9rem; flex-shrink: 0; }
.error-text { font-size: 0.75rem; color: #fdba74; flex: 1; }
.error-dismiss {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  font-size: 0.75rem;
  padding: 2px 6px;
  border-radius: 4px;
  transition: color 0.15s;
}
.error-dismiss:hover { color: #94a3b8; }

/* ── Overlay transition ──────────────────────────────────────────────────── */
.vd-overlay-enter-active { transition: opacity 0.25s ease; }
.vd-overlay-leave-active { transition: opacity 0.2s ease; }
.vd-overlay-enter-from,
.vd-overlay-leave-to     { opacity: 0; }

/* loading overlay 需要 position:relative 的父容器 */
.vd-root { position: relative; }
</style>
