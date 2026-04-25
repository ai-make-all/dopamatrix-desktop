import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const API_BASE = 'http://127.0.0.1:8000'
const POLL_INTERVAL_MS = 3000

export const useAppStore = defineStore('app', () => {
  // ── Auth ──────────────────────────────────────────────────────────────────
  const isLoggedIn   = ref(false)
  const loggedInUser = ref('')

  function initAuth() {
    const stored = localStorage.getItem('dopamatrix_user')
    if (stored) {
      loggedInUser.value = stored
      isLoggedIn.value   = true
      axios.defaults.headers.common['X-Local-User'] = stored
    }
  }

  function handleLogin(username) {
    localStorage.setItem('dopamatrix_user', username)
    loggedInUser.value = username
    isLoggedIn.value   = true
    axios.defaults.headers.common['X-Local-User'] = username
  }

  function handleLogout() {
    localStorage.removeItem('dopamatrix_user')
    localStorage.removeItem('clipflow_output_dir')
    loggedInUser.value = ''
    isLoggedIn.value   = false
    delete axios.defaults.headers.common['X-Local-User']
  }

  // ── Toast ─────────────────────────────────────────────────────────────────
  const toastVisible = ref(false)
  const toastMsg     = ref('')
  let _toastTimer    = null

  function showToast(msg, duration = 5000) {
    if (_toastTimer) clearTimeout(_toastTimer)
    toastMsg.value     = msg
    toastVisible.value = true
    _toastTimer = setTimeout(() => { toastVisible.value = false }, duration)
  }

  // ── Task Feed ─────────────────────────────────────────────────────────────
  const feedItems    = ref([])
  let _feedIdCounter = 0
  let _pollTimer     = null

  function clearPollTimer() {
    if (_pollTimer !== null) { clearInterval(_pollTimer); _pollTimer = null }
  }

  function pushQueuedItem(promptText) {
    const localFeedId = ++_feedIdCounter
    const now = new Date()
    feedItems.value.unshift({
      id:        localFeedId,
      type:      'queued',
      prompt:    promptText.slice(0, 60) + (promptText.length > 60 ? '…' : ''),
      taskId:    null,
      ts:        now.toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      startTime: Date.now(),
      startTs:   now.toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      assets:    [],
    })
    return localFeedId
  }

  function setFeedItemTaskId(localFeedId, taskId) {
    const card = feedItems.value.find(c => c.id === localFeedId)
    if (card) card.taskId = taskId
  }

  function markFeedItemFailed(localFeedId) {
    const card = feedItems.value.find(c => c.id === localFeedId)
    if (card) card.type = 'failed'
  }

  function startGlobalPolling() {
    if (_pollTimer !== null) return
    _pollTimer = setInterval(async () => {
      const activeTasks = feedItems.value.filter(c => c.type === 'queued' && c.taskId)
      if (activeTasks.length === 0) {
        clearPollTimer()
        return
      }
      for (const task of activeTasks) {
        try {
          const resp = await axios.get(`${API_BASE}/api/v1/tasks/${task.taskId}`)
          const data = resp.data
          if (data.status === 'completed') {
            const assets = Array.isArray(data.assets) ? data.assets : []
            if (assets.length > 0) {
              task.type     = 'completed'
              task.assets   = assets
              task.endTime  = Date.now()
              task.endTs    = new Date().toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
              task.duration = ((task.endTime - task.startTime) / 1000).toFixed(1) + 's'
            } else {
              task.type    = 'failed'
              task.endTime = Date.now()
              task.endTs   = new Date().toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
            }
          } else if (data.status === 'failed') {
            task.type    = 'failed'
            task.endTime = Date.now()
            task.endTs   = new Date().toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          }
        } catch (err) {
          if (err.response?.status === 404) task.type = 'failed'
        }
      }
    }, POLL_INTERVAL_MS)
  }

  // ── Shared state ──────────────────────────────────────────────────────────
  const globalOutputDir = ref(localStorage.getItem('clipflow_output_dir') || '')

  function setGlobalOutputDir(path) {
    globalOutputDir.value = path
    localStorage.setItem('clipflow_output_dir', path)
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function buildVideoUrl(filePath) {
    if (!filePath) return ''
    return `${API_BASE}/api/v1/assets/stream?path=${encodeURIComponent(filePath)}`
  }

  async function copyToClipboard(text) {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      showToast('📁 路径已复制')
    } catch (err) {
      showToast('复制失败: ' + err.message)
    }
  }

  const dashStats = computed(() => ({
    assets:  feedItems.value.filter(c => c.type === 'completed').length,
    savings: (feedItems.value.filter(c => c.type === 'completed').length * 4.2).toFixed(2),
    gpu:     'ONLINE',
  }))

  return {
    // Auth
    isLoggedIn, loggedInUser,
    initAuth, handleLogin, handleLogout,
    // Toast
    toastVisible, toastMsg, showToast,
    // Feed
    feedItems,
    clearPollTimer, startGlobalPolling,
    pushQueuedItem, setFeedItemTaskId, markFeedItemFailed,
    // Shared state
    globalOutputDir, setGlobalOutputDir,
    // Helpers
    buildVideoUrl, copyToClipboard, dashStats,
    // Constants
    API_BASE,
  }
})
