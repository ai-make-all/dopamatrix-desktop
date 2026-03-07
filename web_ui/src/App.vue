<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { open } from '@tauri-apps/plugin-dialog'
import axios from 'axios'
import Dashboard from './components/Dashboard.vue'

// ── Tab navigation ─────────────────────────────────────────────────────────
// 'workbench' | 'dashboard'
const activeTab = ref('workbench')

const API_BASE = 'http://127.0.0.1:8000'
const POLL_INTERVAL_MS = 3000

// ── state ──────────────────────────────────────────────────────
const form        = ref({ prompt: '', batch_size: 3, local_asset_dir: '', local_overlay_dir: '' })
const loading     = ref(false)
const taskId      = ref('')
const taskStatus  = ref('')
const progressMsg = ref('')
const assets      = ref([])
const errorMsg    = ref('')

// ── toast ──────────────────────────────────────────────────────
const toastVisible = ref(false)
const toastMsg     = ref('')
const toastType    = ref('error')   // 'error' | 'warning'
let   toastTimer   = null

/**
 * 显示页面内浮动 Toast 提示，duration ms 后自动收起。
 * 同时将错误内容同步写入 errorMsg（左侧面板内联展示）。
 */
function showToast(msg, type = 'error', duration = 6000) {
  if (toastTimer) clearTimeout(toastTimer)
  toastMsg.value     = msg
  toastType.value    = type
  toastVisible.value = true
  errorMsg.value     = msg          // 同步左侧内联错误区
  toastTimer = setTimeout(() => { toastVisible.value = false }, duration)
}

let pollTimer = null

// ── helpers ────────────────────────────────────────────────────

/** Always-safe timer teardown */
function clearPollTimer() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

/** Normalise any file_path to a full URL (handles Windows backslashes) */
function buildVideoUrl(filePath) {
  if (!filePath) return ''
  const normalized = filePath.replace(/\\/g, '/')
  const withSlash  = normalized.startsWith('/') ? normalized : '/' + normalized
  return API_BASE + withSlash
}

/** Computed badge class for the status indicator */
const badgeClass = computed(() => {
  const map = {
    pending:    'badge badge-pending',
    processing: 'badge badge-processing',
    completed:  'badge badge-completed',
    failed:     'badge badge-failed',
  }
  return map[taskStatus.value] ?? 'badge badge-pending'
})

// ── local asset dir ───────────────────────────────────────────

/** Open native folder picker for X-axis video assets */
async function selectLocalFolder() {
  try {
    const selected = await open({ directory: true, multiple: false })
    if (selected && typeof selected === 'string') {
      form.value.local_asset_dir = selected
    }
  } catch (err) {
    console.error('[Tauri Dialog] 打开文件夹失败：', err)
  }
}

/** Open native folder picker for Y-axis PNG overlay assets */
async function selectOverlayFolder() {
  try {
    const selected = await open({ directory: true, multiple: false })
    if (selected && typeof selected === 'string') {
      form.value.local_overlay_dir = selected
    }
  } catch (err) {
    console.error('[Tauri Dialog] 打开贴图文件夹失败：', err)
  }
}

// ── core logic ─────────────────────────────────────────────────

/** Submit a new render task */
async function submitTask() {
  if (!form.value.prompt.trim()) return

  // ① Kill any lingering poll from a previous run
  clearPollTimer()

  // ② Reset reactive state
  errorMsg.value     = ''
  toastVisible.value = false
  assets.value       = []
  taskId.value       = ''
  taskStatus.value   = ''
  progressMsg.value  = ''
  loading.value      = true

  try {
    const resp = await axios.post(`${API_BASE}/api/v1/tasks/submit`, {
      prompt:           form.value.prompt.trim(),
      batch_size:       form.value.batch_size || 1,
      local_asset_dir:  form.value.local_asset_dir  || null,
      local_overlay_dir: form.value.local_overlay_dir || null,
    })

    const data = resp.data
    // ⚠ Backend VideoTaskResponse uses `id`, not `task_id`
    taskId.value      = String(data.id ?? '')
    taskStatus.value  = data.status ?? 'pending'
    progressMsg.value = '任务已提交，正在初始化渲染管道…'

    if (!taskId.value) {
      throw new Error('后端未返回任务 id，原始响应：' + JSON.stringify(data))
    }

    // ③ First immediate check, then schedule interval
    await pollTask()
    pollTimer = setInterval(pollTask, POLL_INTERVAL_MS)

  } catch (err) {
    // ④ 确保 loading 立即恢复，按钮变回可点击状态
    clearPollTimer()
    loading.value = false

    // ⑤ 精准提取后端 detail 字段
    //    FastAPI 验证错误：detail 是对象数组 [{loc, msg, type}, …]
    //    业务层 HTTPException / ValueError：detail 是字符串
    const raw = err.response?.data?.detail
    let detail
    if (Array.isArray(raw)) {
      // Pydantic ValidationError — 取第一条 msg
      detail = raw.map(e => e.msg ?? JSON.stringify(e)).join('；')
    } else if (raw && typeof raw === 'string') {
      detail = raw
    } else {
      detail = err.message ?? '未知错误'
    }

    const httpStatus = err.response?.status
    const prefix = httpStatus ? `[${httpStatus}] ` : ''
    showToast(`${prefix}提交失败：${detail}`, 'error')
  }
}

/** Poll task status */
async function pollTask() {
  if (!taskId.value) return

  try {
    const resp = await axios.get(`${API_BASE}/api/v1/tasks/${taskId.value}`)
    const data = resp.data

    taskStatus.value  = data.status ?? taskStatus.value
    progressMsg.value = data.message ?? ''

    if (data.status === 'completed') {
      clearPollTimer()                    // ⑤ stop on success
      loading.value = false
      assets.value  = Array.isArray(data.assets) ? data.assets : []
      if (assets.value.length === 0) {
        progressMsg.value = '任务完成，但后端未返回任何资产，请检查 output 目录。'
      }
    } else if (data.status === 'failed') {
      clearPollTimer()                    // ⑥ stop on failure
      loading.value     = false
      progressMsg.value = data.message ?? '任务执行失败，请查看后端日志。'
    }

  } catch (err) {
    // Network / server error during polling — show message but keep retrying
    progressMsg.value =
      '轮询异常（将继续重试）：' + (err.response?.data?.detail ?? err.message ?? '网络错误')

    // If 404 (task not found), stop retrying
    if (err.response?.status === 404) {
      clearPollTimer()
      loading.value     = false
      taskStatus.value  = 'failed'
      progressMsg.value = `Task ${taskId.value} 不存在，已停止轮询。`
    }
  }
}

// ⑦ Cleanup when component unmounts (page refresh / SPA teardown)
onUnmounted(clearPollTimer)
</script>

<template>
  <!-- ── ERROR TOAST ── -->
  <Transition name="toast">
    <div
      v-if="toastVisible"
      role="alert"
      style="
        position: fixed; top: 1.25rem; left: 50%; transform: translateX(-50%);
        z-index: 9999; max-width: 520px; width: calc(100vw - 2rem);
        display: flex; align-items: flex-start; gap: 0.75rem;
        background: rgba(15, 8, 8, 0.92);
        border: 1px solid rgba(239, 68, 68, 0.45);
        box-shadow: 0 0 28px rgba(239, 68, 68, 0.18), 0 4px 24px rgba(0,0,0,0.5);
        backdrop-filter: blur(12px);
        border-radius: 0.8rem; padding: 0.9rem 1rem;
      "
    >
      <!-- icon -->
      <span style="font-size:1.2rem; flex-shrink:0; line-height:1.4">⚠️</span>
      <!-- message -->
      <p style="flex:1; font-size:0.78rem; line-height:1.5; color:#fca5a5; word-break:break-all; margin:0">
        {{ toastMsg }}
      </p>
      <!-- dismiss -->
      <button
        @click="toastVisible = false"
        style="flex-shrink:0; background:none; border:none; cursor:pointer;
               color:#f87171; font-size:1rem; line-height:1; padding:0.1rem 0.25rem;"
        aria-label="关闭"
      >✕</button>
    </div>
  </Transition>

  <!-- ── NAVBAR ── -->
  <nav class="glass-card mx-4 mt-4 px-6 py-3 flex items-center justify-between sticky top-4 z-50">
    <div class="flex items-center gap-3">
      <div
        class="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-violet-500 flex items-center justify-center text-sm font-black shadow-lg shadow-cyan-500/30">
        ⚡
      </div>
      <span class="font-black text-lg tracking-tight bg-gradient-to-r from-cyan-400 to-violet-400 bg-clip-text text-transparent">
        ClipFlow Matrix Console
      </span>
    </div>

    <!-- ── TAB SWITCHER ── -->
    <div class="tab-switcher">
      <button
        @click="activeTab = 'workbench'"
        :class="['tab-btn', activeTab === 'workbench' ? 'tab-active' : '']"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
        </svg>
        工作台
      </button>
      <button
        @click="activeTab = 'dashboard'"
        :class="['tab-btn', activeTab === 'dashboard' ? 'tab-active tab-roi' : '']"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
        </svg>
        ROI 看板
      </button>
    </div>

    <div class="flex items-center gap-2 text-xs text-slate-500">
      <span class="pulse-dot"></span>
      <span>Engine Online</span>
      <span
        v-if="taskId && taskStatus !== 'completed' && taskStatus !== 'failed'"
        class="ml-3 badge badge-processing">
        Task Active
      </span>
    </div>
  </nav>

  <!-- ── DASHBOARD VIEW ── -->
  <div v-if="activeTab === 'dashboard'" class="max-w-7xl mx-auto px-4 py-6 flex flex-col" style="min-height:calc(100vh - 90px)">
    <Dashboard />
  </div>

  <!-- ── WORKBENCH MAIN LAYOUT ── -->
  <main v-show="activeTab === 'workbench'" class="max-w-7xl mx-auto px-4 py-6 grid grid-cols-1 lg:grid-cols-5 gap-6 min-h-[calc(100vh-90px)]">

    <!-- LEFT PANEL -->
    <aside class="lg:col-span-2 flex flex-col gap-4">
      <div class="glass-card p-6 flex flex-col gap-5 flex-1">

        <div class="flex items-center gap-2 text-xs font-semibold text-cyan-400 uppercase tracking-widest">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
          </svg>
          控制面板
        </div>

        <!-- 📂 本地素材库 (X轴) -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-medium text-slate-400 uppercase tracking-wider">
            📂 本地素材库 <span class="text-cyan-500/70">(X轴 · Local Assets)</span>
          </label>
          <div class="flex gap-2 items-stretch">
            <input
              type="text"
              readonly
              :value="form.local_asset_dir || ''"
              placeholder="未选择 — 将使用默认素材库…"
              class="input-cyber flex-1 p-3 text-sm font-mono text-slate-400 cursor-default truncate"
              :title="form.local_asset_dir"
            />
            <button
              type="button"
              @click="selectLocalFolder"
              :disabled="loading"
              class="shrink-0 px-4 rounded-xl border border-cyan-500/40 bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-400 hover:text-cyan-300 text-sm font-bold transition-all duration-200 hover:border-cyan-400/70 hover:shadow-lg hover:shadow-cyan-500/10 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              选择
            </button>
          </div>
          <p class="text-xs text-slate-600">选取本地实拍素材所在文件夹，绝对路径将透传给 FFmpeg 渲染引擎</p>
        </div>

        <!-- 📁 本地贴图库 (Y轴) -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-medium text-slate-400 uppercase tracking-wider">
            📁 本地贴图库 <span class="text-violet-400/70">(Y轴 · Overlays)</span>
          </label>
          <div class="flex gap-2 items-stretch">
            <input
              type="text"
              readonly
              :value="form.local_overlay_dir || ''"
              placeholder="未选择 — 将使用默认叠层素材…"
              class="input-cyber flex-1 p-3 text-sm font-mono text-slate-400 cursor-default truncate"
              :title="form.local_overlay_dir"
              style="border-color: rgba(139,92,246,0.25);"
            />
            <button
              type="button"
              @click="selectOverlayFolder"
              :disabled="loading"
              class="shrink-0 px-4 rounded-xl border border-violet-500/40 bg-violet-500/10 hover:bg-violet-500/20 text-violet-400 hover:text-violet-300 text-sm font-bold transition-all duration-200 hover:border-violet-400/70 hover:shadow-lg hover:shadow-violet-500/10 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              选择
            </button>
          </div>
          <p class="text-xs text-slate-600">
            请选择包含透明背景的 <span class="text-violet-400/60 font-mono">.png</span>
            格式 Logo 或促销贴纸文件夹（单文件限制 &lt; 5MB）
          </p>
        </div>

        <!-- Prompt -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-medium text-slate-400 uppercase tracking-wider">内容 Prompt</label>
          <textarea
            id="promptInput"
            v-model="form.prompt"
            rows="7"
            :disabled="loading"
            placeholder="描述你想要生成的视频内容…&#10;&#10;例：拍摄一款高端轿车的减震器安装教程，强调德国工艺与耐久性，适合 TikTok 矩阵投放。"
            class="input-cyber w-full resize-none p-3 text-sm leading-relaxed">
          </textarea>
        </div>

        <!-- Batch size -->
        <div class="flex flex-col gap-2">
          <label for="batchInput" class="text-xs font-medium text-slate-400 uppercase tracking-wider">
            批量数量 (Batch Size)
          </label>
          <input
            id="batchInput"
            v-model.number="form.batch_size"
            type="number" min="1" max="20"
            :disabled="loading"
            class="input-cyber w-full p-3 text-sm font-mono"
            placeholder="3" />
          <p class="text-xs text-slate-600">每次任务并行生成的视频变体数量（建议 1–10）</p>
        </div>

        <!-- Error -->
        <div
          v-if="errorMsg"
          class="text-xs text-red-400 bg-red-500/10 border border-red-500/25 rounded-lg px-3 py-2 break-words">
          ⚠ {{ errorMsg }}
        </div>

        <!-- Submit -->
        <button
          id="submitBtn"
          @click="submitTask"
          :disabled="loading || !form.prompt.trim()"
          class="btn-neon w-full py-4 rounded-xl font-black text-lg text-white tracking-wide mt-auto">
          <span v-if="!loading">⚡ 启动矩阵裂变</span>
          <span v-else class="flex items-center justify-center gap-2">
            <svg class="w-5 h-5 spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
            渲染矩阵中…
          </span>
        </button>

      </div>
    </aside>

    <!-- RIGHT PANEL -->
    <section class="lg:col-span-3 flex flex-col gap-4">

      <!-- Empty state -->
      <div
        v-if="!taskId && !assets.length"
        class="glass-card flex-1 flex flex-col items-center justify-center gap-4 py-20 text-center">
        <div class="text-6xl opacity-20">🎬</div>
        <p class="text-slate-500 text-sm max-w-xs">
          在左侧填写 Prompt 并点击按钮，任务状态与生成的视频矩阵将在此处呈现。
        </p>
      </div>

      <!-- Task Status Panel (active) -->
      <div
        v-if="taskId && taskStatus !== 'completed' && taskStatus !== 'failed'"
        class="glass-card p-6 relative overflow-hidden fade-in">
        <div class="scan-line"></div>

        <div class="flex items-center gap-3 mb-5">
          <svg class="w-5 h-5 text-cyan-400 spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          <span class="font-semibold text-cyan-400 text-sm uppercase tracking-widest">任务状态面板</span>
          <span :class="badgeClass" class="ml-auto">{{ taskStatus || 'pending' }}</span>
        </div>

        <div class="grid grid-cols-2 gap-3 text-xs">
          <div class="bg-slate-900/60 rounded-lg p-3 border border-slate-800">
            <div class="text-slate-500 mb-1 uppercase tracking-wider">Task ID</div>
            <div class="font-mono text-cyan-300 truncate">{{ taskId }}</div>
          </div>
          <div class="bg-slate-900/60 rounded-lg p-3 border border-slate-800">
            <div class="text-slate-500 mb-1 uppercase tracking-wider">状态</div>
            <div class="font-mono text-yellow-300">{{ taskStatus || 'initializing…' }}</div>
          </div>
          <div class="bg-slate-900/60 rounded-lg p-3 border border-slate-800 col-span-2">
            <div class="text-slate-500 mb-1 uppercase tracking-wider">进度消息</div>
            <div class="text-slate-300">{{ progressMsg || '正在拼命渲染中… 请稍候' }}</div>
          </div>
        </div>

        <div class="mt-4 h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div class="h-full bg-gradient-to-r from-cyan-500 to-violet-500 rounded-full animate-pulse" style="width:65%"></div>
        </div>
        <p class="text-xs text-slate-600 mt-2 text-right">每 3 秒自动轮询…</p>
      </div>

      <!-- Failed state -->
      <div v-if="taskStatus === 'failed'" class="glass-card p-6 border-red-500/30 fade-in">
        <div class="flex items-center gap-2 text-red-400 font-semibold mb-2">✕ 任务执行失败</div>
        <p class="text-xs text-slate-500">Task ID: <span class="font-mono text-slate-400">{{ taskId }}</span></p>
        <p class="text-xs text-red-400 mt-2">{{ progressMsg }}</p>
      </div>

      <!-- Assets Delivery -->
      <div v-if="assets.length" class="fade-in flex flex-col gap-4">

        <div class="glass-card px-5 py-3 flex items-center gap-3">
          <span class="text-green-400 text-lg">✓</span>
          <div>
            <div class="font-semibold text-green-400 text-sm">矩阵裂变完成！</div>
            <div class="text-xs text-slate-500">共生成 {{ assets.length }} 个视频资产</div>
          </div>
          <span class="badge badge-completed ml-auto">completed</span>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div v-for="(asset, idx) in assets" :key="asset.id ?? idx" class="asset-card fade-in">

            <!-- Video player -->
            <video controls class="w-full aspect-video bg-black" :src="buildVideoUrl(asset.file_path)" preload="metadata">
              您的浏览器不支持 HTML5 视频播放。
            </video>

            <!-- Metadata -->
            <div class="p-4 flex flex-col gap-3">

              <!-- Language + index -->
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-xs font-semibold text-slate-300 uppercase tracking-wider">语言</span>
                <span class="badge badge-processing">{{ asset.language || 'N/A' }}</span>
                <span class="text-xs text-slate-600 ml-auto font-mono">#{{ idx + 1 }}</span>
              </div>

              <!-- File path -->
              <div class="text-xs text-slate-500 font-mono truncate" :title="asset.file_path">
                {{ asset.file_path || '—' }}
              </div>

              <!-- Anti-dup fingerprint -->
              <div class="flex flex-col gap-1">
                <div class="flex items-center gap-1.5 text-xs font-semibold text-emerald-400 uppercase tracking-wider">
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round"
                      d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                  防重指纹 MD5
                </div>
                <div class="font-mono text-xs font-semibold text-green-400 bg-green-950/40 border border-green-500/30 rounded-lg px-3 py-2 break-all leading-relaxed tracking-wide">
                  {{ asset.file_hash || '—' }}
                </div>
              </div>

              <!-- Download -->
              <a
                :href="buildVideoUrl(asset.file_path)"
                :download="asset.file_path ? asset.file_path.split(/[/\\]/).pop() : 'video.mp4'"
                class="mt-1 w-full text-center text-xs py-2 rounded-lg bg-slate-800/70 hover:bg-slate-700/70 border border-slate-700 hover:border-cyan-500/40 transition-all text-slate-300 hover:text-cyan-400">
                ↓ 下载视频
              </a>
            </div>

          </div>
        </div>
      </div>

    </section>
  </main>

  <footer class="text-center text-xs text-slate-700 pb-6 mt-4">
    ClipFlow Engine v0.7.0 &nbsp;·&nbsp; Matrix Console &nbsp;·&nbsp; Phase 7 · Desktop MVP
  </footer>
</template>

<style>
/* ── Tab switcher ──────────────────────────────────────────────────── */
.tab-switcher {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  background: rgba(8, 12, 25, 0.7);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 0.6rem;
  padding: 0.25rem;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.9rem;
  border-radius: 0.4rem;
  font-size: 0.72rem;
  font-weight: 700;
  color: #64748b;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.18s ease;
  letter-spacing: 0.03em;
  white-space: nowrap;
}
.tab-btn:hover { color: #94a3b8; background: rgba(255,255,255,0.04); }

.tab-active {
  color: #22d3ee !important;
  background: rgba(34, 211, 238, 0.1) !important;
  border: 1px solid rgba(34, 211, 238, 0.25) !important;
  box-shadow: 0 0 12px rgba(34, 211, 238, 0.12);
}

.tab-roi.tab-active {
  color: #a78bfa !important;
  background: rgba(167, 139, 250, 0.1) !important;
  border: 1px solid rgba(167, 139, 250, 0.25) !important;
  box-shadow: 0 0 12px rgba(167, 139, 250, 0.15);
}

/* ── Error Toast transition ─────────────────────────────────────────── */
.toast-enter-active { animation: toastIn 0.28s cubic-bezier(0.22, 1, 0.36, 1); }
.toast-leave-active { animation: toastOut 0.22s ease-in forwards; }

@keyframes toastIn {
  from { opacity: 0; transform: translateX(-50%) translateY(-14px) scale(0.97); }
  to   { opacity: 1; transform: translateX(-50%) translateY(0)     scale(1);    }
}
@keyframes toastOut {
  from { opacity: 1; transform: translateX(-50%) translateY(0)     scale(1);    }
  to   { opacity: 0; transform: translateX(-50%) translateY(-8px)  scale(0.97); }
}
</style>
