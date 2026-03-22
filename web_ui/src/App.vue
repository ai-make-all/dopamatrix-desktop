<script setup>
import { ref, computed, onUnmounted, nextTick, watch } from 'vue'
import { open } from '@tauri-apps/plugin-dialog'
import { open as openPath } from '@tauri-apps/plugin-shell'
import { readDir } from '@tauri-apps/plugin-fs'
import axios from 'axios'
import Dashboard from './components/Dashboard.vue'

// ── View routing ───────────────────────────────────────────────────────────
const currentView = ref('dashboard')  // 'dashboard' | 'assets' | 'workspace' | 'history'

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
const targetDuration  = ref(15)

const globalOutputDir = ref(localStorage.getItem('clipflow_output_dir') || '')

async function pickGlobalOutputFolder() {
  try {
    const selected = await open({ directory: true, multiple: false })
    if (selected && typeof selected === 'string') {
      globalOutputDir.value = selected
      localStorage.setItem('clipflow_output_dir', selected)
      showToast('✅ 输出目录已更新: ' + selected)
    }
  } catch (err) {
    console.error('[Tauri Dialog] 设置目录打开失败：', err)
  }
}

async function openDiagnosticLogs() {
  try {
    const res = await axios.get(`${API_BASE}/api/v1/tasks/system/logs/path`)
    const logPath = res.data.path
    await openPath(logPath)
  } catch (err) {
    const msg = err?.message || String(err)
    console.error('[DiagnosticLogs] 打开日志目录失败：', err)
    showToast(`❌ 打开日志目录失败：${msg}`)
  }
}

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
  // 经由后端的 /stream 接口代理读取本地绝对路径，打破跨盘符/浏览器安全区限制
  return `${API_BASE}/api/v1/assets/stream?path=${encodeURIComponent(filePath)}`
}

async function copyToClipboard(text) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    showToast('📁 路径已复制')
  } catch (err) {
    console.error('复制失败:', err)
    showToast('复制失败: ' + err.message)
  }
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
  const now = new Date()
  feedItems.value.unshift({
    id: localFeedId,
    type: 'queued',
    prompt: prompt.slice(0, 60) + (prompt.length > 60 ? '…' : ''),
    taskId: null,
    ts: now.toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    startTime: Date.now(),
    startTs: now.toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    assets: []
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
      target_duration:    targetDuration.value,
      output_dir:         globalOutputDir.value || null,
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
            task.type = 'completed'
            task.assets = assets
            task.endTime = Date.now()
            task.endTs = new Date().toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
            task.duration = ((task.endTime - task.startTime) / 1000).toFixed(1) + 's'
          } else {
            task.type = 'failed'
            task.endTime = Date.now()
            task.endTs = new Date().toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          }
        } else if (data.status === 'failed') {
          task.type = 'failed'
          task.endTime = Date.now()
          task.endTs = new Date().toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
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

// ── DAM Assets ─────────────────────────────────────────────────────────────
const activeTab = ref('video') // 'video' | 'logo' | 'sticker'
const assetList = ref([])

async function fetchAssets() {
  try {
    const resp = await axios.get(`${API_BASE}/api/v1/assets?asset_type=${activeTab.value}`)
    assetList.value = resp.data
  } catch (err) {
    showToast('获取素材失败: ' + err.message)
  }
}

async function importAssets() {
  let filterName = '视频素材'
  let filterExts = ['mp4', 'mov']
  
  if (activeTab.value === 'logo') {
    filterName = 'Logo 水印'
    filterExts = ['png']
  } else if (activeTab.value === 'sticker') {
    filterName = '互动贴纸'
    filterExts = ['png']
  }

  try {
    const selected = await open({
      multiple: true,
      filters: [{ name: filterName, extensions: filterExts }]
    })
    
    if (!selected || selected.length === 0) return

    showToast('正在导入并计算素材哈希...')
    const resp = await axios.post(`${API_BASE}/api/v1/assets/import`, {
      file_paths: selected,
      asset_type: activeTab.value,
      video_role: 'general',
      tags: []
    })
    
    showToast(resp.data.message)
    
    // Auto-refresh the asset list if the import was successful
    fetchAssets()
  } catch (err) {
    console.error('[Import Assets] 导入失败：', err)
    showToast('导入失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function updateVideoRole(item) {
  try {
    await axios.patch(`${API_BASE}/api/v1/assets/${item.id}/role`, {
      video_role: item.video_role
    })
    showToast(`成功将素材设为 ${item.video_role === 'hook' ? '黄金片头 (Hook)' : (item.video_role === 'body' ? '混剪 (Body)' : '通用 (General)')}`)
  } catch (err) {
    showToast('角色更新失败: ' + (err.response?.data?.detail || err.message))
  }
}

watch([currentView, activeTab], ([newView]) => {
  if (newView === 'assets') {
    fetchAssets()
  } else if (newView === 'history') {
    fetchHistory()
  }
}, { immediate: true })

// ── History Log ────────────────────────────────────────────────────────────
const historyList = ref([])
const historySearchQuery = ref('')

const filteredHistoryList = computed(() => {
  const query = historySearchQuery.value.trim().toLowerCase()
  if (!query) {
    return historyList.value
  }
  return historyList.value.filter(item => item.prompt && item.prompt.toLowerCase().includes(query))
})

async function fetchHistory() {
  try {
    const resp = await axios.get(`${API_BASE}/api/v1/history`)
    historyList.value = resp.data || []
  } catch (err) {
    showToast('获取历史记录失败: ' + err.message)
  }
}

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
          @click="currentView = 'assets'"
          :class="['nav-item', currentView === 'assets' ? 'nav-active' : '']"
        >
          <span class="nav-icon">🗂️</span>
          <span>素材库</span>
        </button>
        <button
          @click="currentView = 'workspace'"
          :class="['nav-item', currentView === 'workspace' ? 'nav-active nav-active-cyan' : '']"
        >
          <span class="nav-icon">💬</span>
          <span>矩阵工厂</span>
        </button>
        <button
          @click="currentView = 'history'"
          :class="['nav-item', currentView === 'history' ? 'nav-active' : '']"
        >
          <span class="nav-icon">🕒</span>
          <span>历史记录</span>
        </button>
        <button
          @click="currentView = 'settings'"
          :class="['nav-item', currentView === 'settings' ? 'nav-active' : '']"
        >
          <span class="nav-icon">⚙️</span>
          <span>设置</span>
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
      <!-- ─────────────────────────────── ASSETS (DAM) ─────────────────────── -->
      <template v-else-if="currentView === 'assets'">
        <div class="assets-wrap">
          <!-- Header -->
          <div class="assets-header">
            <h2 class="assets-title">数字资产管理 (DAM)</h2>
            <button class="cta-glow-btn" style="padding: 0.5rem 1.25rem; font-size: 0.85rem;" @click="importAssets">➕ 导入本地素材</button>
          </div>
          
          <!-- Tabs -->
          <div class="assets-tabs">
            <button :class="['tab-btn', activeTab === 'video' ? 'tab-active' : '']" @click="activeTab = 'video'">🎬 视频骨料 (X轴)</button>
            <button :class="['tab-btn', activeTab === 'logo' ? 'tab-active' : '']" @click="activeTab = 'logo'">🏷️ 品牌水印 (Logo)</button>
            <button :class="['tab-btn', activeTab === 'sticker' ? 'tab-active' : '']" @click="activeTab = 'sticker'">✨ 互动贴纸 (Sticker)</button>
          </div>

          <!-- Grid -->
          <div class="assets-grid">
            <div v-if="assetList.length === 0" style="color: #64748b; font-size: 0.85rem; padding: 1rem;">
              暂无素材，请点击右上角导入。
            </div>
            <div
              v-for="item in assetList"
              :key="item.id"
              :class="['asset-card', item.video_role === 'hook' && activeTab === 'video' ? 'asset-card-hook' : '']"
            >
              <div class="asset-thumb">
                <!-- Dynamic Media Preview -->
                <video 
                  v-if="activeTab === 'video'"
                  :src="buildVideoUrl(item.file_path)"
                  controls
                  muted
                  preload="metadata"
                  class="w-full h-48 object-contain bg-black/40 rounded-md mb-3"
                ></video>
                <img 
                  v-else-if="activeTab === 'logo' || activeTab === 'sticker'"
                  :src="buildVideoUrl(item.file_path)"
                  class="w-full h-48 object-contain bg-black/40 rounded-md mb-3"
                />
                
                <div class="asset-badges" style="position: absolute; top: 0.5rem; right: 0.5rem;">
                  <span class="badge-ref">引用: {{ item.usage_count }}次</span>
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
                <div v-if="activeTab === 'video'" class="asset-role-wrap" style="margin-top:0.35rem; margin-bottom:0.2rem;">
                   <select v-model="item.video_role" @change="updateVideoRole(item)" :class="['role-select', item.video_role === 'hook' ? 'role-hook' : (item.video_role === 'body' ? 'role-body' : '')]">
                      <option value="body">混剪 (Body)</option>
                      <option value="hook">黄金片头 (Hook)</option>
                      <option value="general">通用 (General)</option>
                   </select>
                </div>
                <div class="asset-tags">
                  <span v-for="(tag, idx) in item.tags || []" :key="idx" class="tag">{{ tag }}</span>
                  <span v-if="item.is_exhausted" class="tag" style="background: rgba(239,68,68,0.15); color: #fca5a5; border-color: rgba(239,68,68,0.3);">疲劳警告</span>
                  <span v-else-if="item.usage_count === 0" class="tag">全新</span>
                </div>
              </div>
            </div>
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
                    <span class="feed-ts">开始: {{ item.startTs || item.ts }}</span>
                  </div>
                  <div class="feed-prompt">⏳ {{ item.prompt }}</div>
                  <div v-if="item.taskId" class="feed-meta">Task #{{ item.taskId }}</div>
                </template>

                <!-- COMPLETED card -->
                <template v-else-if="item.type === 'completed'">
                  <div class="feed-card-header">
                    <span style="color:#4ade80;font-size:1rem">✓</span>
                    <span class="feed-badge feed-badge-completed">已完成</span>
                    <span class="feed-ts text-gray-300 font-medium" v-if="item.duration">
                      开始: {{ item.startTs }} | 结束: {{ item.endTs }} | 
                      <span class="text-cyan-400 font-bold">耗时: {{ item.duration }}</span>
                    </span>
                    <span class="feed-ts text-gray-300 font-medium" v-else>{{ item.ts }}</span>
                  </div>
                  <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div v-for="(asset, idx) in item.assets" :key="idx" class="flex flex-col">
                      <video
                        controls
                        class="aspect-[4/5] object-contain bg-black rounded-md w-full mb-2"
                        :src="buildVideoUrl(asset.file_path)"
                        preload="metadata"
                      />
                      <div class="feed-hash" style="margin-bottom:0.4rem">
                        🔒 {{ asset.file_hash }}
                      </div>
                      <button
                        @click="copyToClipboard(asset.file_path)"
                        class="feed-dl w-full mt-auto cursor-pointer"
                        style="font-family: inherit;"
                      >📁 复制本地路径</button>
                    </div>
                  </div>
                </template>

                <!-- FAILED card -->
                <template v-else-if="item.type === 'failed'">
                  <div class="feed-card-header">
                    <span style="color:#f87171;font-size:1rem">✕</span>
                    <span class="feed-badge feed-badge-failed">失败</span>
                    <span class="feed-ts" v-if="item.endTs">开始: {{ item.startTs }} | 结束: {{ item.endTs }}</span>
                    <span class="feed-ts" v-else>{{ item.ts }}</span>
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
              placeholder="描述你想生成的视频内容，如：汽车减震器出海，强调极其耐用，适合中东路况…"
              class="omni-textarea"
              rows="3"
            ></textarea>

            <!-- Toolbar -->
            <div class="omni-toolbar">
              <!-- 主动作按钮: 统一资产选取 -->
              <!-- (原有的 Tauri FS 逻辑代码在 script 中保留，仅替换 UI) -->
              <button class="tool-btn tool-btn-primary" @click="currentView = 'assets'" title="打开 DAM 添加素材">
                <span style="font-size: 1.1rem;">📦</span>
                <span class="tool-label">从素材库装载弹药</span>
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

              <!-- ⑥ 目标时长 -->
              <div class="tool-select-wrap">
                <span class="tool-select-icon">⏱️</span>
                <select v-model.number="targetDuration" class="tool-select">
                  <option :value="15">短平快 (15秒)</option>
                  <option :value="30">信息流 (30秒)</option>
                  <option :value="60">完整故事 (60秒)</option>
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

      <!-- ─────────────────────────────── HISTORY LOG ─────────────────────── -->
      <template v-else-if="currentView === 'history'">
        <div class="workspace-wrap" style="padding: 1.5rem; overflow-y: auto;">
          <div class="assets-header" style="margin-bottom: 1.5rem;">
            <h2 class="assets-title">历史生成记录 (History Log)</h2>
            <div style="flex:1"></div>
            <!-- 前端极速搜索框 -->
            <input 
              v-model="historySearchQuery"
              type="text" 
              placeholder="🔍 检索历史提示词 (如：减震器、中东)..." 
              class="tool-num" 
              style="width: 280px; text-align: left; padding-left: 1rem;" 
            />
          </div>

          <div v-if="historyList.length === 0" class="feed-empty">
            <div style="font-size:3rem;opacity:.18">🕒</div>
            <p style="color:#475569;font-size:.85rem;max-width:260px;text-align:center;margin-top:.75rem">
              暂无生成历史，快去矩阵工厂创作吧！
            </p>
          </div>

          <div class="feed-list" style="max-width: 1200px; margin: 0 auto; width: 100%;">
            <div v-for="item in filteredHistoryList" :key="item.id" class="feed-card feed-card-completed" style="margin-bottom: 1rem; padding: 1.25rem;">
              <div class="feed-card-header" style="border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 0.75rem; margin-bottom: 0.75rem;">
                <span style="color:#a78bfa;font-size:1rem">🗄️</span>
                <span class="feed-badge" style="background: rgba(167, 139, 250, 0.15); color: #c4b5fd; border: 1px solid rgba(167, 139, 250, 0.3);">
                  Task ID: {{ item.task_id }}
                </span>
                <span class="feed-ts text-gray-300 font-medium">生成时间: {{ new Date(item.created_at).toLocaleString('zh') }}</span>
                <span class="feed-ts ml-auto text-gray-300 font-medium" style="margin-left: auto;">
                  <span class="text-cyan-400 font-bold">耗时: {{ item.duration }}s</span>
                </span>
              </div>
              
              <div class="feed-prompt" style="font-size: 1rem; font-weight: 500; color: #e2e8f0; margin-bottom: 1rem; border-left: 3px solid #38bdf8; padding-left: 0.75rem;">
                {{ item.prompt }}
              </div>

              <div class="grid grid-cols-2 md:grid-cols-3 gap-4" v-if="item.output_assets && item.output_assets.length > 0">
                <div v-for="(asset, idx) in item.output_assets" :key="idx" class="flex flex-col">
                  <video
                    controls
                    class="aspect-[4/5] object-contain bg-black rounded-md w-full mb-2"
                    :src="buildVideoUrl(asset.path)"
                    preload="metadata"
                  />
                  <div class="feed-hash" style="margin-bottom:0.4rem; font-size: 0.7rem;">
                    🔒 {{ asset.hash }}
                  </div>
                  <button
                    @click="copyToClipboard(asset.path)"
                    class="feed-dl w-full mt-auto cursor-pointer"
                    style="font-family: inherit;"
                  >📁 复制本地路径</button>
                </div>
              </div>
              <div v-else class="text-sm text-slate-500 italic mt-2">
                此任务未包含最终输出视频或已丢失。
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ─────────────────────────────── SETTINGS ─────────────────────── -->
      <template v-else-if="currentView === 'settings'">
        <div class="workspace-wrap" style="padding: 2.5rem; overflow-y: auto;">
          <h2 class="assets-title" style="margin-bottom: 2rem;">全局安全与输出设置</h2>
          
          <div class="feed-card" style="padding: 2rem; margin-bottom: 2rem; background: rgba(15,23,42,0.6); border: 1px solid rgba(56,189,248,0.2);">
            <div style="display:flex; align-items:center; gap: 1.5rem; margin-bottom: 1rem;">
              <div style="width:60px; height:60px; border-radius:50%; background:#38bdf8; display:flex; align-items:center; justify-content:center; font-size:1.8rem;">
                👨‍💻
              </div>
              <div>
                <div style="font-size: 1.2rem; font-weight:bold; color:#f8fafc; margin-bottom: 0.2rem;">TeleUser_8891</div>
                <div style="color: #94a3b8; font-size: 0.9rem;">Telegram 授权账户 (内测阶段待正式对接)</div>
              </div>
            </div>
          </div>

          <div class="feed-card" style="padding: 2rem; background: rgba(15,23,42,0.6); border: 1px solid rgba(56,189,248,0.2);">
            <h3 style="color:#e2e8f0; font-size:1.1rem; margin-bottom: 1rem;">📁 本地输出目录绑定</h3>
            <p style="color:#94a3b8; font-size:0.9rem; margin-bottom: 1.5rem;">
              设置统一的成品短视频输出绝对路径。若不设置，默认输出至工程 <code style="color:#38bdf8; background: rgba(56,189,248,0.1); padding: 0.15rem 0.35rem; border-radius: 0.25rem;">output/</code> 下。
            </p>
            <div style="display:flex; align-items:center; padding: 1rem; background:rgba(0,0,0,0.3); border-radius: 0.5rem; margin-bottom:1.5rem; border: 1px dashed rgba(255,255,255,0.1);">
              <span style="color:#38bdf8; margin-right: 0.5rem; flex-shrink:0;">当前路径：</span>
              <span style="color:#f8fafc; word-break: break-all; font-family: monospace;">{{ globalOutputDir || '未设置 (默认跟随引擎输出)' }}</span>
            </div>
            <div style="display:flex; gap: 1rem; flex-wrap: wrap;">
              <button @click="pickGlobalOutputFolder" class="cta-glow-btn" style="padding: 0.75rem 1.5rem; width: auto; font-size: 0.95rem;">
                📁 更改成品视频输出目录
              </button>
              <button @click="openDiagnosticLogs" class="cta-glow-btn" style="padding: 0.75rem 1.5rem; width: auto; font-size: 0.95rem; background: linear-gradient(135deg, rgba(99,102,241,0.15), rgba(139,92,246,0.15)); border-color: rgba(139,92,246,0.4);">
                📁 导出/查看诊断日志
              </button>
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

/* ── Assets (DAM) ──────────────────────────────────────────────────── */
.assets-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  background: radial-gradient(circle at top right, rgba(139,92,246,0.03), transparent 50%);
}

.assets-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.assets-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 800;
  color: #e2e8f0;
  background: linear-gradient(90deg, #a78bfa, #38bdf8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: .02em;
}

.assets-tabs {
  display: flex;
  gap: 0.75rem;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  padding-bottom: 0.5rem;
}
.tab-btn {
  background: transparent;
  border: none;
  color: #64748b;
  font-size: 0.85rem;
  font-weight: 600;
  padding: 0.5rem 1rem;
  cursor: pointer;
  border-radius: 8px;
  transition: all .2s;
}
.tab-btn:hover { background: rgba(255,255,255,0.04); color: #94a3b8; }
.tab-active {
  background: rgba(139,92,246,0.1) !important;
  color: #a78bfa !important;
  box-shadow: inset 0 0 0 1px rgba(139,92,246,0.2);
}

.assets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1.25rem;
}

.asset-card {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: all .2s;
}
.asset-card:hover {
  transform: translateY(-4px);
  border-color: rgba(139,92,246,0.3);
  box-shadow: 0 10px 20px rgba(0,0,0,0.4), 0 0 15px rgba(139,92,246,0.15);
}

.asset-card-hook {
  border-color: rgba(168, 85, 247, 0.6) !important;
  box-shadow: 0 0 15px rgba(168, 85, 247, 0.25) !important;
}

.role-select {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #94a3b8;
  font-size: 0.72rem;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  width: 100%;
  outline: none;
  cursor: pointer;
}
.role-hook {
  color: #d8b4fe;
  border-color: rgba(168, 85, 247, 0.4);
}
.role-body {
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.2);
}

.asset-thumb {
  height: 120px;
  background: #090e1a;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.thumb-icon { font-size: 2.5rem; opacity: 0.3; }
.asset-badges {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  display: flex;
  gap: 0.4rem;
}
.badge-ref {
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(4px);
  color: #cbd5e1;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem;
  padding: 0.2rem 0.5rem;
  border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.1);
}

.asset-info {
  padding: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.asset-name {
  color: #e2e8f0;
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: 'Inter', sans-serif;
}
.asset-health {
  height: 6px;
  background: rgba(255,255,255,0.08);
  border-radius: 99px;
  overflow: hidden;
}
.health-bar {
  height: 100%;
  border-radius: 99px;
  transition: width .3s ease;
}
.asset-tags {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.asset-tags .tag {
  background: rgba(56,189,248,0.1);
  color: #38bdf8;
  border: 1px solid rgba(56,189,248,0.25);
  font-size: 0.65rem;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
}

.tool-btn-primary {
  background: linear-gradient(135deg, rgba(139,92,246,0.15), rgba(56,189,248,0.15));
  border-color: rgba(139,92,246,0.4);
}
.tool-btn-primary:hover {
  background: linear-gradient(135deg, rgba(139,92,246,0.25), rgba(56,189,248,0.25));
  border-color: rgba(139,92,246,0.6);
  box-shadow: 0 0 12px rgba(139,92,246,0.2);
}
.tool-btn-primary .tool-label {
  color: #e2e8f0 !important;
}

</style>
