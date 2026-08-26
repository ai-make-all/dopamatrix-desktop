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
    localStorage.removeItem('dopamatrix_output_dir')
    loggedInUser.value = ''
    isLoggedIn.value   = false
    delete axios.defaults.headers.common['X-Local-User']
  }

  // ── Toast ─────────────────────────────────────────────────────────────────
  const toastVisible = ref(false)
  const toastMsg     = ref('')
  const toastType    = ref('info')   // 'info' | 'success' | 'warn' | 'error'
  let _toastTimer    = null

  function showToast(msg, duration = 5000) {
    if (_toastTimer) clearTimeout(_toastTimer)
    // 自动从消息首字符推断类型，无需调用方手动传参
    const m = msg.trim()
    toastType.value =
      /^[⚠️❌🚫]/.test(m)               ? 'error'   :
      /^[✅🪄🏷️💎🎉🔥✨🎬]/.test(m) ? 'success' :
      /^[💡ℹ️🔍]/.test(m)               ? 'info'    : 'warn'
    toastMsg.value     = msg
    toastVisible.value = true
    _toastTimer = setTimeout(() => { toastVisible.value = false }, duration)
  }

  // ── Delivery Hub Notifications ───────────────────────────────────────────
  const notifications = ref([])
  const unreadCount = computed(() => notifications.value.filter(n => !n.isRead).length)
  const exportPollTimers = new Map()

  function addNotification(notif) {
    const id = 'msg_' + Date.now() + Math.random().toString(36).slice(2, 5)
    notifications.value.unshift({
      id,
      isRead: false,
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      ...notif,
    })
    return id
  }

  function updateNotification(id, updates) {
    const idx = notifications.value.findIndex(n => n.id === id)
    if (idx !== -1) {
      notifications.value[idx] = {
        ...notifications.value[idx],
        ...updates,
        timestamp: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      }
    }
  }

  function markAllRead() {
    notifications.value.forEach(n => { n.isRead = true })
  }

  function stopExportPolling(filename) {
    const pollTimer = exportPollTimers.get(filename)
    if (pollTimer) {
      clearInterval(pollTimer)
      exportPollTimers.delete(filename)
    }
  }

  function startGlobalExportPolling(filename, count) {
    if (!filename) return
    stopExportPolling(filename)

    const ticketId = addNotification({
      type: 'loading',
      title: '📦 交付任务下发成功',
      message: `正在后台并发打包装填 ${count} 个视频，您可以继续处理其他工作。`,
    })

    const pollTimer = setInterval(async () => {
      try {
        const res = await axios.get(`${API_BASE}/api/v1/matrix/export/status`, {
          params: { filename },
        })
        if (res.data.status === 'ready') {
          stopExportPolling(filename)
          updateNotification(ticketId, {
            type: 'success',
            isRead: false,
            title: '⚡ 矩阵弹药箱装填完毕',
            message: `成功打包 ${count} 个成片与专属短链 CSV，请点击立即提货。`,
            downloadUrl: `${API_BASE}${res.data.download_url}`,
            localPath: res.data.local_path,
          })
          // 全局总线：通知质检舱数据库已完成 tracking_link 写入，触发列表刷新
          window.dispatchEvent(new CustomEvent('matrix-delivery-ready'))
        } else if (res.data.status === 'failed') {
          stopExportPolling(filename)
          updateNotification(ticketId, {
            type: 'error',
            isRead: false,
            title: '⚠️ 交付包生成失败',
            message: '后台打包未完成，请确认已通过变体的物理文件仍然存在后重试。',
          })
        }
      } catch (e) {
        console.error('[Polling Failed]', e)
      }
    }, POLL_INTERVAL_MS)

    exportPollTimers.set(filename, pollTimer)
  }

  // ── Task Feed ─────────────────────────────────────────────────────────────
  const feedItems    = ref([])
  let _feedIdCounter = 0
  let _pollTimer     = null

  function clearPollTimer() {
    if (_pollTimer !== null) { clearInterval(_pollTimer); _pollTimer = null }
    for (const timer of exportPollTimers.values()) clearInterval(timer)
    exportPollTimers.clear()
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
  const globalOutputDir = ref(localStorage.getItem('dopamatrix_output_dir') || '')

  function setGlobalOutputDir(path) {
    globalOutputDir.value = path
    localStorage.setItem('dopamatrix_output_dir', path)
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  /**
   * 动态流媒体网关 URL 构造器（Dynamic Media Streaming Gateway）
   *
   * 替代旧版 StaticFiles 挂载方案。
   * 判断依据：路径含斜杠（/ 或 \）则视为本地绝对路径，通过网关透传；
   * 否则原样透传（兼容已经是完整 HTTP URL 的历史数据）。
   *
   * 必须使用 encodeURIComponent：Windows 路径中的空格、#、& 等字符
   * 若不编码会破坏 URL 的查询字符串结构，导致后端解析错误。
   */
  function buildVideoUrl(filePath) {
    if (!filePath) return ''
    if (/^(https?:|blob:|data:)/i.test(filePath)) return filePath
    // 含路径分隔符 → 本地绝对路径，走动态流媒体网关
    if (filePath.includes('/') || filePath.includes('\\')) {
      return `${API_BASE}/api/v1/media/preview?path=${encodeURIComponent(filePath)}`
    }
    // 无分隔符（如纯文件名或已是 HTTP URL），原样返回
    return filePath
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
    toastVisible, toastMsg, toastType, showToast,
    // Delivery Hub
    notifications, unreadCount, markAllRead, updateNotification, startGlobalExportPolling,
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
