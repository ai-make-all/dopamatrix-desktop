<script setup>
import { ref, computed, onUnmounted, nextTick } from 'vue'
import { open } from '@tauri-apps/plugin-dialog'
import { readDir } from '@tauri-apps/plugin-fs'
import axios from 'axios'
import Dashboard from './components/Dashboard.vue'

// ── View routing ───────────────────────────────────────────────────────────
const currentView = ref('dashboard')  // 'dashboard' | 'workspace'

const API_BASE = 'http://127.0.0.1:8000'
const POLL_INTERVAL_MS = 3000

// ── Omnibox form state (persistent across sends) ───────────────────────────
const omniPrompt      = ref('')
const batchSize       = ref(1)
const localAssetDir   = ref('')
const localLogoDir    = ref('')
const localStickerDir = ref('')
const aspectRatio     = ref('9:16')
const testLanguage    = ref('en')

const xAssetCount      = ref(0)
const isBatchOverLimit = computed(() => {
  return batchSize.value > Math.floor(xAssetCount.value * 1.5)
})

// ── Task Feed ──────────────────────────────────────────────────────────────
const feedItems = ref([])   // { id, type:'queued'|'completed'|'failed', taskId, lang, filePath, fileHash, ts }
let feedIdCounter = 0

// ── Poll state ─────────────────────────────────────────────────────────────
let pollTimer = null

// ── Toast ──────────────────────────────────────────────────────────────────
const toastVisible = ref(false)
const toastMsg     = ref('')
let toastTimer     = null

function showToast(msg, duration = 5000) {
  if (toastTimer) clearTimeout(toastTimer)
  toastMsg.value     = msg
  toastVisible.value = true
  toastTimer = setTimeout(() => { toastVisible.value = false }, duration)
}

function clearPollTimer() {
  if (pollTimer !== null) { clearInterval(pollTimer); pollTimer = null }
}

function buildVideoUrl(filePath) {
  if (!filePath) return ''
  const normalized = filePath.replace(/\\/g, '/')
  const withSlash  = normalized.startsWith('/') ? normalized : '/' + normalized
  return API_BASE + withSlash
}

// ── Tauri folder pickers ───────────────────────────────────────────────────
async function pickFolder(type, label) {
  try {
    const selected = await open({ directory: true, multiple: false })
    if (selected && typeof selected === 'string') {
      if (type === 'xAsset') localAssetDir.value = selected
      else if (type === 'logo') localLogoDir.value = selected
      else if (type === 'sticker') localStickerDir.value = selected

      if (type === 'xAsset') {
        try {
          const entries = await readDir(selected)
          const videoCount = entries.filter(e => e.name && (e.name.toLowerCase().endsWith('.mp4') || e.name.toLowerCase().endsWith('.mov'))).length
          xAssetCount.value = videoCount
        } catch (e) {
          console.error('[Tauri FS] 读取 X轴素材 目录失败：', e)
          xAssetCount.value = 0
        }
      }
    }
  } catch (err) {
    console.error(`[Tauri Dialog] ${label} 打开失败：`, err)
  }
}

// ── Submit ─────────────────────────────────────────────────────────────────
async function sendTask() {
  const prompt = omniPrompt.value.trim()
  if (!prompt) return

  // Immediately clear prompt (non-blocking UX), retain all config
  omniPrompt.value = ''

  // Push a queued card into the feed
  const localFeedId = ++feedIdCounter
  feedItems.value.unshift({
    id: localFeedId,
    type: 'queued',
    prompt: prompt.slice(0, 60) + (prompt.length > 60 ? '…' : ''),
    taskId: null,
    ts: new Date().toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
  })

  // Scroll feed to top
  await nextTick()

  try {
    const resp = await axios.post(`${API_BASE}/api/v1/tasks/submit`, {
      prompt,
      batch_size:         batchSize.value || 1,
      local_asset_dir:    localAssetDir.value   || null,
      local_logo_dir:     localLogoDir.value    || null,
      local_sticker_dir:  localStickerDir.value || null,
      aspect_ratio:       aspectRatio.value,
      test_language:      testLanguage.value,
    })

    const data = resp.data
    const taskId = String(data.task_id ?? data.id ?? '')
    if (!taskId) throw new Error('后端未返回任务 id')

    // Update queued card with real task id
    const card = feedItems.value.find(c => c.id === localFeedId)
    if (card) card.taskId = taskId

    // Start global polling
    startGlobalPolling()

  } catch (err) {
    const raw = err.response?.data?.detail
    let detail
    if (Array.isArray(raw))        detail = raw.map(e => e.msg ?? JSON.stringify(e)).join('；')
    else if (raw && typeof raw === 'string') detail = raw
    else                           detail = err.message ?? '未知错误'

    const status = err.response?.status
    showToast(`[${status ?? 'ERR'}] 提交失败：${detail}`)

    // Mark card as failed
    const card = feedItems.value.find(c => c.id === localFeedId)
    if (card) card.type = 'failed'
  }
}

function startGlobalPolling() {
  // If already polling, no need to start another interval
  if (pollTimer !== null) return

  pollTimer = setInterval(async () => {
    // Find active tasks that are waiting for generation
    const activeTasks = feedItems.value.filter(c => c.type === 'queued' && c.taskId)
    
    // Stop polling if there are no active tasks left
    if (activeTasks.length === 0) {
      clearPollTimer()
      return
    }

    // Ping status for all active tasks
    for (const task of activeTasks) {
      try {
        const resp = await axios.get(`${API_BASE}/api/v1/tasks/${task.taskId}`)
        const data = resp.data

        if (data.status === 'completed') {
          const assets = Array.isArray(data.assets) ? data.assets : []
          if (assets.length > 0) {
            // Update the existing Task card to completed with the first video's data
            task.type = 'completed'
            task.lang = assets[0].language || 'N/A'
            task.filePath = assets[0].file_path
            task.fileHash = assets[0].file_hash
            task.ts = new Date().toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

            // If it's a batch generation, add the rest of the videos as new cards
            for (let i = 1; i < assets.length; i++) {
              feedItems.value.unshift({
                id: ++feedIdCounter,
                type: 'completed',
                taskId: task.taskId,
                lang: assets[i].language || 'N/A',
                filePath: assets[i].file_path,
                fileHash: assets[i].file_hash,
                ts: new Date().toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
              })
            }
          } else {
            task.type = 'failed'
            task.ts = new Date().toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          }
        } else if (data.status === 'failed') {
          task.type = 'failed'
          task.ts = new Date().toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        }
      } catch (err) {
        if (err.response?.status === 404) {
          task.type = 'failed'
        }
      }
    }
  }, POLL_INTERVAL_MS)
}

// ── Dashboard stats (static for MVP) ──────────────────────────────────────
const dashStats = computed(() => ({
  assets:   feedItems.value.filter(c => c.type === 'completed').length,
  savings:  (feedItems.value.filter(c => c.type === 'completed').length * 4.2).toFixed(2),
  gpu:      'ONLINE',
}))

onUnmounted(clearPollTimer)
</script>

<template>
  <!-- ── TOAST ── -->
  <Transition name="toast">
    <div v-if="toastVisible" class="toast-wrap" role="alert">
      <span style="font-size:1.1rem;flex-shrink:0">⚠️</span>
      <p class="toast-msg">{{ toastMsg }}</p>
      <button @click="toastVisible=false" class="toast-close">✕</button>
    </div>
  </Transition>

  <!-- ── APP SHELL (sidebar + content) ── -->
  <div class="app-shell">

    <!-- ══ SIDEBAR ═══════════════════════════════════════════════════════ -->
    <aside class="sidebar">
      <!-- Logo -->
      <div class="sidebar-logo">
        <div class="logo-icon">⚡</div>
        <span class="logo-text">ClipFlow</span>
      </div>

      <!-- Nav -->
      <nav class="sidebar-nav">
        <button
          @click="currentView = 'dashboard'"
          :class="['nav-item', currentView === 'dashboard' ? 'nav-active' : '']"
        >
          <span class="nav-icon">📈</span>
          <span>商业看板</span>
        </button>
        <button
          @click="currentView = 'workspace'"
          :class="['nav-item', currentView === 'workspace' ? 'nav-active nav-active-cyan' : '']"
        >
          <span class="nav-icon">💬</span>
          <span>矩阵工厂</span>
        </button>
      </nav>

      <!-- Footer profile -->
      <div class="sidebar-footer">
        <div class="profile-avatar">👤</div>
        <div class="profile-info">
          <div class="profile-name">未登录</div>
          <div class="profile-sub">内测账户</div>
        </div>
        <span class="pulse-dot" style="margin-left:auto;flex-shrink:0"></span>
      </div>
    </aside>

    <!-- ══ MAIN CONTENT ══════════════════════════════════════════════════ -->
    <main class="main-content">

      <!-- ─────────────────────────────── DASHBOARD ─────────────────────── -->
      <template v-if="currentView === 'dashboard'">
        <div class="dashboard-wrap">

          <!-- Stat cards -->
          <div class="stat-grid">
            <div class="stat-card stat-violet">
              <div class="stat-label">📦 累计生产资产</div>
              <div class="stat-value">{{ dashStats.assets }}</div>
              <div class="stat-sub">本次会话</div>
            </div>
            <div class="stat-card stat-cyan">
              <div class="stat-label">💰 预估节省成本</div>
              <div class="stat-value">${{ dashStats.savings }}</div>
              <div class="stat-sub">对比人工剪辑</div>
            </div>
            <div class="stat-card stat-green">
              <div class="stat-label">⚡ GPU 算力状态</div>
              <div class="stat-value" style="font-size:1.4rem">{{ dashStats.gpu }}</div>
              <div class="stat-sub">渲染引擎就绪</div>
            </div>
          </div>

          <!-- ROI Dashboard component -->
          <Dashboard />

          <!-- CTA -->
          <div class="dashboard-cta-wrap">
            <button @click="currentView = 'workspace'" class="cta-glow-btn">
              🚀 去新建矩阵任务
            </button>
          </div>

        </div>
      </template>

      <!-- ─────────────────────────────── WORKSPACE ─────────────────────── -->
      <template v-else-if="currentView === 'workspace'">
        <div class="workspace-wrap">

          <!-- ── TASK FEED (upper 80%) ────────────────────────────────── -->
          <div class="task-feed">
            <!-- Empty state -->
            <div v-if="feedItems.length === 0" class="feed-empty">
              <div style="font-size:3rem;opacity:.18">🎬</div>
              <p style="color:#475569;font-size:.85rem;max-width:260px;text-align:center;margin-top:.75rem">
                在下方输入创作指令并发送，AI 将实时反馈生成进度
              </p>
            </div>

            <!-- Feed cards -->
            <TransitionGroup name="feed" tag="div" class="feed-list">
              <div
                v-for="item in feedItems"
                :key="item.id"
                :class="['feed-card', `feed-card-${item.type}`]"
              >
                <!-- QUEUED card -->
                <template v-if="item.type === 'queued'">
                  <div class="feed-card-header">
                    <svg class="w-4 h-4 spin" fill="none" viewBox="0 0 24 24" style="color:#38bdf8;flex-shrink:0">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                    </svg>
                    <span class="feed-badge feed-badge-processing">排队中</span>
                    <span class="feed-ts">{{ item.ts }}</span>
                  </div>
                  <div class="feed-prompt">⏳ {{ item.prompt }}</div>
                  <div v-if="item.taskId" class="feed-meta">Task #{{ item.taskId }}</div>
                </template>

                <!-- COMPLETED card -->
                <template v-else-if="item.type === 'completed'">
                  <div class="feed-card-header">
                    <span style="color:#4ade80;font-size:1rem">✓</span>
                    <span class="feed-badge feed-badge-completed">已完成</span>
                    <span class="feed-badge" style="border-color:rgba(139,92,246,.4);color:#a78bfa;background:rgba(139,92,246,.1);margin-left:.25rem">{{ item.lang }}</span>
                    <span class="feed-ts">{{ item.ts }}</span>
                  </div>
                  <video
                    v-if="item.filePath"
                    controls
                    class="feed-video"
                    :src="buildVideoUrl(item.filePath)"
                    preload="metadata"
                  />
                  <div v-if="item.fileHash" class="feed-hash">
                    🔒 {{ item.fileHash }}
                  </div>
                  <a
                    v-if="item.filePath"
                    :href="buildVideoUrl(item.filePath)"
                    :download="item.filePath.split(/[/\\]/).pop()"
                    class="feed-dl"
                  >↓ 下载视频</a>
                </template>

                <!-- FAILED card -->
                <template v-else-if="item.type === 'failed'">
                  <div class="feed-card-header">
                    <span style="color:#f87171;font-size:1rem">✕</span>
                    <span class="feed-badge feed-badge-failed">失败</span>
                    <span class="feed-ts">{{ item.ts }}</span>
                  </div>
                  <div class="feed-prompt" style="color:#f87171;opacity:.75">任务执行失败，请查看后端日志。</div>
                </template>
              </div>
            </TransitionGroup>
          </div>

          <!-- ── OMNIBOX (lower 20%) ──────────────────────────────────── -->
          <div class="omnibox">
            <!-- Textarea -->
            <textarea
              v-model="omniPrompt"
              @keydown.enter.ctrl.prevent="sendTask"
              placeholder="输入内容指令… Ctrl+Enter 发送"
              class="omni-textarea"
              rows="3"
            ></textarea>

            <!-- Toolbar -->
            <div class="omni-toolbar">
              <!-- ① X轴素材 -->
              <button class="tool-btn" @click="pickFolder('xAsset', 'X轴素材')" :title="localAssetDir || '未选择'">
                <span>📁</span>
                <span class="tool-label">X轴素材</span>
                <span v-if="localAssetDir" class="tool-dot"></span>
              </button>

              <!-- ② Logo水印 -->
              <button class="tool-btn" @click="pickFolder('logo', 'Logo水印')" :title="localLogoDir || '未选择'">
                <span>🏷️</span>
                <span class="tool-label">Logo</span>
                <span v-if="localLogoDir" class="tool-dot"></span>
              </button>

              <!-- ③ 促销贴纸 -->
              <button class="tool-btn" @click="pickFolder('sticker', '促销贴纸')" :title="localStickerDir || '未选择'">
                <span>✨</span>
                <span class="tool-label">贴纸</span>
                <span v-if="localStickerDir" class="tool-dot"></span>
              </button>

              <!-- Divider -->
              <div class="tool-divider"></div>

              <!-- ④ 画幅 -->
              <div class="tool-select-wrap">
                <span class="tool-select-icon">📐</span>
                <select v-model="aspectRatio" class="tool-select">
                  <option value="9:16">9:16 竖屏</option>
                  <option value="16:9">16:9 横屏</option>
                  <option value="1:1">1:1 方形</option>
                </select>
              </div>

              <!-- ⑤ 测试语言 -->
              <div class="tool-select-wrap">
                <span class="tool-select-icon">🌐</span>
                <select v-model="testLanguage" class="tool-select">
                  <option value="en">EN 英语</option>
                  <option value="ar">AR 阿语</option>
                  <option value="zh">ZH 中文</option>
                </select>
              </div>

              <!-- ⑥ 批量数 -->
              <div class="tool-num-wrap">
                <span class="tool-select-icon">🔢</span>
                <input
                  v-model.number="batchSize"
                  type="number" min="1" max="20"
                  class="tool-num"
                  title="批量数量"
                />
              </div>

              <!-- Send button -->
              <button
                @click="sendTask"
                :disabled="!omniPrompt.trim()"
                class="send-btn"
              >🚀 发送</button>
            </div>

            <!-- Warning -->
            <div v-if="xAssetCount > 0 && isBatchOverLimit" class="text-yellow-400" style="color:#facc15; font-size:0.75rem; display:flex; align-items:center; gap:0.4rem;">
              <span>⚠️</span>
              <span style="opacity:0.9">当前素材量仅为 {{xAssetCount}} 段，生成超过 {{Math.floor(xAssetCount * 1.5)}} 条变体极易触发平台查重限流，请谨慎操作！</span>
            </div>
          </div>

        </div>
      </template>

    </main>
  </div>
</template>

<style>
/* ── App shell ─────────────────────────────────────────────────────────── */
.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ── Sidebar ───────────────────────────────────────────────────────────── */
.sidebar {
  width: 220px;
  flex-shrink: 0;
  background: rgba(9, 14, 30, 0.96);
  border-right: 1px solid rgba(56, 189, 248, 0.12);
  display: flex;
  flex-direction: column;
  padding: 1.25rem 0.75rem;
  gap: 0.5rem;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0 0.5rem 1rem;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  margin-bottom: 0.5rem;
}
.logo-icon {
  width: 2rem; height: 2rem;
  border-radius: 0.5rem;
  background: linear-gradient(135deg, #0ea5e9, #8b5cf6);
  display: flex; align-items: center; justify-content: center;
  font-size: 0.95rem;
  box-shadow: 0 0 16px rgba(99,102,241,.4);
}
.logo-text {
  font-weight: 900;
  font-size: 1rem;
  background: linear-gradient(90deg, #38bdf8, #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: -0.01em;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 0.75rem;
  border-radius: 0.6rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: #64748b;
  background: transparent;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.18s ease;
  text-align: left;
  width: 100%;
}
.nav-item:hover { color: #94a3b8; background: rgba(255,255,255,0.04); }
.nav-icon { font-size: 1rem; }

.nav-active {
  color: #a78bfa !important;
  background: rgba(139,92,246,0.12) !important;
  border-color: rgba(139,92,246,0.3) !important;
  box-shadow: 0 0 16px rgba(139,92,246,0.15), inset 0 0 0 1px rgba(139,92,246,0.08);
}
.nav-active-cyan {
  color: #38bdf8 !important;
  background: rgba(56,189,248,0.10) !important;
  border-color: rgba(56,189,248,0.28) !important;
  box-shadow: 0 0 16px rgba(56,189,248,0.13), inset 0 0 0 1px rgba(56,189,248,0.06);
}

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.75rem 0.5rem 0;
  border-top: 1px solid rgba(255,255,255,0.06);
  margin-top: 0.5rem;
}
.profile-avatar {
  width: 2rem; height: 2rem;
  border-radius: 50%;
  background: rgba(51,65,85,0.8);
  border: 1px solid rgba(56,189,248,0.2);
  display: flex; align-items: center; justify-content: center;
  font-size: 0.9rem;
  flex-shrink: 0;
}
.profile-name { font-size: 0.75rem; font-weight: 700; color: #94a3b8; }
.profile-sub  { font-size: 0.63rem; color: #475569; }

/* ── Main content ─────────────────────────────────────────────────── */
.main-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Dashboard ─────────────────────────────────────────────────────── */
.dashboard-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.stat-card {
  border-radius: 14px;
  padding: 1.25rem 1.5rem;
  backdrop-filter: blur(12px);
  border: 1px solid;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.stat-violet { background: rgba(139,92,246,0.1); border-color: rgba(139,92,246,0.25); }
.stat-cyan   { background: rgba(56,189,248,0.08); border-color: rgba(56,189,248,0.22); }
.stat-green  { background: rgba(34,197,94,0.08);  border-color: rgba(34,197,94,0.22); }

.stat-label { font-size: 0.72rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: .06em; }
.stat-value { font-size: 2rem; font-weight: 900; color: #e2e8f0; line-height: 1; font-family: 'JetBrains Mono', monospace; }
.stat-sub   { font-size: 0.65rem; color: #475569; }

.dashboard-cta-wrap {
  display: flex;
  justify-content: center;
  padding: 1rem 0 0.5rem;
}
.cta-glow-btn {
  padding: 0.85rem 2.5rem;
  border-radius: 12px;
  background: linear-gradient(135deg, #0ea5e9 0%, #6366f1 50%, #8b5cf6 100%);
  color: #fff;
  font-weight: 900;
  font-size: 1rem;
  border: none;
  cursor: pointer;
  box-shadow: 0 0 32px rgba(99,102,241,.55), 0 4px 16px rgba(0,0,0,.5);
  transition: all .25s ease;
  letter-spacing: .02em;
}
.cta-glow-btn:hover {
  box-shadow: 0 0 56px rgba(99,102,241,.75), 0 6px 24px rgba(0,0,0,.6);
  transform: translateY(-2px) scale(1.02);
}
.cta-glow-btn:active { transform: translateY(0) scale(.99); }

/* ── Workspace ─────────────────────────────────────────────────────── */
.workspace-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* Task Feed */
.task-feed {
  flex: 1;
  overflow-y: auto;
  padding: 1.25rem 1.25rem 0.75rem;
  display: flex;
  flex-direction: column;
}

.feed-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.feed-list { display: flex; flex-direction: column; gap: 0.75rem; }

.feed-card {
  border-radius: 12px;
  padding: 0.9rem 1rem;
  border: 1px solid;
  backdrop-filter: blur(8px);
  transition: transform 0.15s;
}
.feed-card:hover { transform: translateX(3px); }
.feed-card-queued    { background: rgba(56,189,248,0.06);  border-color: rgba(56,189,248,0.2); }
.feed-card-completed { background: rgba(34,197,94,0.06);   border-color: rgba(34,197,94,0.22); }
.feed-card-failed    { background: rgba(239,68,68,0.06);   border-color: rgba(239,68,68,0.22); }

.feed-card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.6rem;
}

.feed-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: .66rem;
  padding: 1px 8px;
  border-radius: 99px;
  border: 1px solid;
}
.feed-badge-processing { background: rgba(56,189,248,.12); color: #38bdf8; border-color: rgba(56,189,248,.35); }
.feed-badge-completed  { background: rgba(34,197,94,.12);  color: #4ade80; border-color: rgba(34,197,94,.35); }
.feed-badge-failed     { background: rgba(239,68,68,.12);  color: #f87171; border-color: rgba(239,68,68,.35); }

.feed-ts { font-size: .65rem; color: #475569; margin-left: auto; font-family: 'JetBrains Mono', monospace; }
.feed-prompt { font-size: .8rem; color: #94a3b8; margin-bottom: .4rem; line-height:1.5; }
.feed-meta { font-size: .65rem; color: #38bdf8; font-family: 'JetBrains Mono', monospace; }
.feed-video {
  width: 100%;
  max-height: 240px;
  border-radius: 8px;
  background: #000;
  margin-bottom: .5rem;
  object-fit: contain;
}
.feed-hash {
  font-family: 'JetBrains Mono', monospace;
  font-size: .65rem;
  color: #4ade80;
  background: rgba(34,197,94,.08);
  border: 1px solid rgba(34,197,94,.2);
  border-radius: 6px;
  padding: .3rem .6rem;
  word-break: break-all;
  margin-bottom: .4rem;
}
.feed-dl {
  display: block;
  text-align: center;
  font-size: .72rem;
  padding: .35rem;
  border-radius: 6px;
  background: rgba(255,255,255,.04);
  border: 1px solid rgba(255,255,255,.08);
  color: #64748b;
  text-decoration: none;
  transition: all .2s;
}
.feed-dl:hover { color: #38bdf8; border-color: rgba(56,189,248,.3); }

/* Omnibox */
.omnibox {
  flex-shrink: 0;
  border-top: 1px solid rgba(56,189,248,0.12);
  background: rgba(9,14,30,0.96);
  padding: 0.75rem 1.25rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.omni-textarea {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  color: #e2e8f0;
  font-family: 'Inter', sans-serif;
  font-size: 0.9rem;
  line-height: 1.6;
  caret-color: #38bdf8;
}
.omni-textarea::placeholder { color: #334155; }

.omni-toolbar {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: nowrap;
  overflow-x: auto;
}

.tool-btn {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.65rem;
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04);
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all .18s;
  position: relative;
}
.tool-btn:hover { border-color: rgba(56,189,248,.35); color: #94a3b8; background: rgba(56,189,248,.06); }
.tool-label { font-size: .68rem; }
.tool-dot {
  position: absolute;
  top: 4px; right: 4px;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #38bdf8;
}

.tool-divider {
  width: 1px; height: 1.4rem;
  background: rgba(255,255,255,0.08);
  margin: 0 0.15rem;
  flex-shrink: 0;
}

.tool-select-wrap {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  background: rgba(255,255,255,0.03);
  padding: 0.25rem 0.55rem;
}
.tool-select-icon { font-size: 0.8rem; }
.tool-select {
  background: transparent;
  border: none;
  outline: none;
  color: #94a3b8;
  font-size: 0.7rem;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
}
.tool-select option { background: #0f172a; }

.tool-num-wrap {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  background: rgba(255,255,255,0.03);
  padding: 0.25rem 0.55rem;
}
.tool-num {
  width: 2.5rem;
  background: transparent;
  border: none;
  outline: none;
  color: #94a3b8;
  font-size: 0.7rem;
  font-family: 'JetBrains Mono', monospace;
  text-align: center;
}
.tool-num::-webkit-inner-spin-button { opacity: 0.4; }

.send-btn {
  margin-left: auto;
  flex-shrink: 0;
  padding: 0.4rem 1.1rem;
  border-radius: 9px;
  background: linear-gradient(135deg,#0ea5e9,#6366f1);
  color: #fff;
  font-weight: 800;
  font-size: 0.78rem;
  border: none;
  cursor: pointer;
  box-shadow: 0 0 18px rgba(99,102,241,.45);
  transition: all .2s;
  white-space: nowrap;
}
.send-btn:hover:not(:disabled) {
  box-shadow: 0 0 28px rgba(99,102,241,.7);
  transform: scale(1.03);
}
.send-btn:disabled { opacity: .35; cursor: not-allowed; }

/* ── Shared utils ──────────────────────────────────────────────────── */
.pulse-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #38bdf8;
  animation: pulse-ring 1.5s ease-out infinite;
  display: inline-block;
}

/* ── Transitions ──────────────────────────────────────────────────── */
.feed-enter-active { animation: feedIn .3s cubic-bezier(.22,1,.36,1) both; }
.feed-leave-active { animation: feedOut .2s ease-in forwards; }
.feed-move         { transition: transform .3s ease; }

@keyframes feedIn {
  from { opacity:0; transform: translateY(-10px); }
  to   { opacity:1; transform: translateY(0); }
}
@keyframes feedOut {
  from { opacity:1; transform: translateX(0); }
  to   { opacity:0; transform: translateX(-20px); }
}

.toast-wrap {
  position: fixed; top: 1.25rem; left: 50%; transform: translateX(-50%);
  z-index: 9999; max-width: 480px; width: calc(100vw - 2rem);
  display: flex; align-items: flex-start; gap: .75rem;
  background: rgba(15,8,8,.92);
  border: 1px solid rgba(239,68,68,.45);
  box-shadow: 0 0 24px rgba(239,68,68,.18), 0 4px 20px rgba(0,0,0,.5);
  backdrop-filter: blur(12px);
  border-radius: .75rem; padding: .85rem 1rem;
}
.toast-msg   { flex:1; font-size:.78rem; line-height:1.5; color:#fca5a5; word-break:break-all; margin:0; }
.toast-close { flex-shrink:0; background:none; border:none; cursor:pointer; color:#f87171; font-size:1rem; padding:.1rem .2rem; }

.toast-enter-active { animation: toastIn .28s cubic-bezier(.22,1,.36,1); }
.toast-leave-active { animation: toastOut .22s ease-in forwards; }

@keyframes toastIn  {
  from { opacity:0; transform: translateX(-50%) translateY(-14px) scale(.97); }
  to   { opacity:1; transform: translateX(-50%) translateY(0) scale(1); }
}
@keyframes toastOut {
  from { opacity:1; transform: translateX(-50%) translateY(0) scale(1); }
  to   { opacity:0; transform: translateX(-50%) translateY(-8px) scale(.97); }
}

.spin { animation: spin .9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse-ring {
  0%  { box-shadow: 0 0 0 0   rgba(56,189,248,.55); }
  70% { box-shadow: 0 0 0 10px rgba(56,189,248,0); }
  100%{ box-shadow: 0 0 0 0   rgba(56,189,248,0); }
}
</style>
