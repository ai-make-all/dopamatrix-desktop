/**
 * useQueueStore.ts — Pinia 桥梁层
 *
 * 职责：
 *  1. 持有 tasks / stats 两个 reactive 引用及可降级的主线程镜像
 *  2. 创建 Web Worker，握手成功后监听其 TICK 消息并覆写 state
 *  3. 维护 WebSocket 连接，将任务更新写入镜像并转发给可用 Worker
 *  4. 暴露 pushTaskUpdate / initTasks 以兼容现有 REST 轮询模式
 *
 * 设计原则：Worker 负责高频状态机；Worker 不可用时由等价的最小主线程逻辑接管。
 */

import { defineStore } from 'pinia'
import { ref }         from 'vue'
import { normalizeCoverageDiagnostics } from '../utils/coverageDiagnostics'
import {
  applyQueueUpdate,
  computeQueueStats,
  normalizeQueueSnapshot,
} from '../utils/queueStateFallback.js'
import { createQueueWorkerBridge } from '../utils/queueWorkerBridge.js'
import QueueWorker from '../workers/queueWorker.ts?worker'

// ── 从 Worker 侧复用类型（避免重复定义） ──────────────────────────────────────
export type { QueueTask, QueueTaskAsset, QueueStats, TaskStatus, WsUpdatePayload } from '../workers/queueWorker'
import type { QueueTask, QueueStats, WsUpdatePayload } from '../workers/queueWorker'

// ── 默认初始统计值 ────────────────────────────────────────────────────────────
const EMPTY_STATS: QueueStats = {
  totalPending:         0,
  totalRunning:         0,
  totalCompleted:       0,
  totalFailed:          0,
  estimatedETA_seconds: 0,
}

const WORKER_READY_TIMEOUT_MS = 2_000

type QueueWorkerInboundMessage =
  | { type: 'WS_UPDATE'; payload: WsUpdatePayload; revision: number }
  | { type: 'INIT_TASKS'; payload: QueueTask[]; revision: number }
  | { type: 'STOP' }

// ── Store 定义 ────────────────────────────────────────────────────────────────
export const useQueueStore = defineStore('queue', () => {

  // ── 核心状态（Worker TICK 或故障降级镜像驱动；视图层只读） ────────────────
  const tasks = ref<QueueTask[]>([])
  const stats = ref<QueueStats>({ ...EMPTY_STATS })

  // ── 内部句柄（不暴露） ─────────────────────────────────────────────────────
  let _stateRevision       = 0
  let _ws:                WebSocket | null = null
  let _wsReconnectTimer:  ReturnType<typeof setTimeout> | null = null
  let _wsReconnectDelay   = 1_000         // 指数退避起始值（ms）
  let _wsTargetUrl        = ''

  // ── 船票鉴权上下文（重连时重新购票所需） ──────────────────────────────────
  // 由 connectEventBus() 写入，供 _scheduleWsReconnect 在重连时重新申请新票。
  // 注意：ticket 是一次性的，_wsTargetUrl 中包含旧 ticket，重连绝对不能复用。
  let _wsUserId  = ''
  let _wsBaseUrl = ''

  const MAX_WS_RECONNECT_DELAY_MS = 30_000

  const _workerBridge = createQueueWorkerBridge({
    createWorker: () => new QueueWorker(),
    readyTimeoutMs: WORKER_READY_TIMEOUT_MS,
    getInitialState: () => ({
      tasks: normalizeQueueSnapshot(tasks.value),
      revision: _stateRevision,
    }),
    onTick: (payload: unknown) => {
      const tick = payload as { tasks: QueueTask[]; stats: QueueStats; revision: number }
      if (!tick || !Array.isArray(tick.tasks) || !tick.stats) return
      if (!Number.isSafeInteger(tick.revision) || tick.revision < _stateRevision) return
      tasks.value = tick.tasks
      stats.value = tick.stats
    },
    onUnavailable: (reason: string) => {
      console.warn(`[QueueStore] Worker unavailable (${reason}); main-thread queue state remains active.`)
    },
  })

  function _postToReadyWorker(message: QueueWorkerInboundMessage): boolean {
    return _workerBridge.post(message)
  }

  // ── Worker 初始化 ──────────────────────────────────────────────────────────
  /**
   * 必须在组件 setup / onMounted 中显式调用，否则 Worker 不会启动。
   * 多次调用安全，内部有幂等保护。
   */
  function initWorker(): void {
    if (typeof Worker === 'undefined') {
      console.warn('[QueueStore] 当前环境不支持 Web Worker，降级为直接状态更新。')
      return
    }
    _workerBridge.start()
  }

  // ── WebSocket 桥接 ─────────────────────────────────────────────────────────
  /**
   * 连接到 WebSocket 端点。连接断开后按指数退避自动重连。
   *
   * @param url  ws:// 或 wss:// 地址，例如 'ws://127.0.0.1:8000/ws/tasks'
   */
  function connectWebSocket(url: string): void {
    if (!url) return

    // 防止同一 URL 重复连接
    if (
      _ws &&
      _wsTargetUrl === url &&
      (_ws.readyState === WebSocket.CONNECTING || _ws.readyState === WebSocket.OPEN)
    ) {
      return
    }

    _wsTargetUrl = url

    try {
      _ws = new WebSocket(url)
    } catch (err) {
      console.error('[QueueStore] WebSocket 构造失败:', err)
      _scheduleWsReconnect()
      return
    }

    _ws.onopen = () => {
      console.info('[QueueStore] WebSocket 已连接:', url)
      _wsReconnectDelay = 1_000  // 连接成功，重置退避计数
    }

    _ws.onmessage = (event: MessageEvent) => {
      // 后端信封协议：{ "type": string, "payload": dict }
      // 例如：{ "type": "WS_UPDATE", "payload": { "taskId": "1", "status": "running", ... } }
      let envelope: { type: string; payload: unknown }
      try {
        envelope = JSON.parse(event.data as string)
      } catch {
        console.warn('[QueueStore] WebSocket 消息 JSON 解析失败，已忽略。', event.data)
        return
      }

      if (!envelope?.type) {
        console.warn('[QueueStore] WebSocket 消息缺少 type 字段，已忽略。', envelope)
        return
      }

      if (envelope.type === 'WS_UPDATE') {
        // Always retain a deduplicated main-thread mirror so a later Worker load,
        // runtime, or message failure cannot discard an accepted task update.
        const payload = envelope.payload as WsUpdatePayload
        if (payload?.taskId) {
          _fallbackUpdate(payload)
          _postToReadyWorker({
            type: 'WS_UPDATE',
            payload,
            revision: _stateRevision,
          })
        }
      }
    }

    _ws.onerror = (err: Event) => {
      console.error('[QueueStore] WebSocket 连接错误:', err)
    }

    _ws.onclose = (evt: CloseEvent) => {
      console.warn(
        `[QueueStore] WebSocket 断开 (code=${evt.code})，将在 ${_wsReconnectDelay}ms 后重试...`
      )
      _scheduleWsReconnect()
    }
  }

  /**
   * 持票上船：先向后端申请一次性船票，再建立 WebSocket 连接。
   *
   * 这是推荐的 WebSocket 接入入口，替代直接调用 connectWebSocket()。
   * 调用时会记录 _wsUserId / _wsBaseUrl，供断线重连时重新购票使用。
   *
   * @param userId  当前登录用户（对应 X-Local-User 请求头，与 appStore.loggedInUser 保持一致）
   * @param baseUrl 后端地址，默认 'http://127.0.0.1:8000'
   */
  async function connectEventBus(
    userId: string,
    baseUrl = 'http://127.0.0.1:8000',
  ): Promise<void> {
    // 持久化上下文，重连时 _scheduleWsReconnect 可读取并重新购票
    _wsUserId  = userId  || 'default'
    _wsBaseUrl = baseUrl || 'http://127.0.0.1:8000'

    try {
      // ── 第一步：购票（REST）─────────────────────────────────────────────
      const res = await fetch(`${_wsBaseUrl}/api/v1/auth/ws-ticket`, {
        method:  'POST',
        headers: { 'X-Local-User': _wsUserId },
      })

      if (!res.ok) {
        console.error(`[QueueStore] 申请 WS 船票失败（HTTP ${res.status}），将在退避后重试...`)
        _scheduleWsReconnect()
        return
      }

      const { ticket } = (await res.json()) as { ticket: string }

      // ── 第二步：持票上船（WebSocket）────────────────────────────────────
      // ticket 仅 10 秒有效，立即使用，严禁缓存复用。
      // http(s) → ws(s) 协议转换，确保 HTTPS 后端下使用 wss://
      const wsUrl = _wsBaseUrl
        .replace(/^https/, 'wss')
        .replace(/^http/,  'ws')
        .replace(/\/$/,    '')
        + `/ws/events?ticket=${ticket}`

      connectWebSocket(wsUrl)

    } catch (err) {
      // 网络错误（后端未启动、DNS 失败等），按退避重试
      console.error('[QueueStore] connectEventBus 网络错误，将在退避后重试:', err)
      _scheduleWsReconnect()
    }
  }

  function _scheduleWsReconnect(): void {
    if (_wsReconnectTimer !== null) return  // 已有重连计划，跳过

    _wsReconnectTimer = setTimeout(() => {
      _wsReconnectTimer = null
      _wsReconnectDelay = Math.min(_wsReconnectDelay * 2, MAX_WS_RECONNECT_DELAY_MS)

      // ⚠️ 关键修复：ticket 是一次性的，重连必须重新购票。
      // 若通过 connectEventBus 接入（_wsUserId 已记录）→ 重新购票建连。
      // 若通过旧版 connectWebSocket 直接接入（_wsUserId 为空）→ 降级复用旧 URL。
      if (_wsUserId) {
        connectEventBus(_wsUserId, _wsBaseUrl)
      } else {
        connectWebSocket(_wsTargetUrl)
      }
    }, _wsReconnectDelay)
  }

  // ── 与现有 REST 轮询的兼容桥 ───────────────────────────────────────────────
  /**
   * 直接向 Worker 推送一条任务更新，用于与旧版 HTTP 轮询逻辑兼容。
   * 新架构下如果 WebSocket 已接管，此方法可忽略。
   */
  function pushTaskUpdate(payload: WsUpdatePayload): void {
    if (!payload?.taskId) return

    _fallbackUpdate(payload)
    _postToReadyWorker({ type: 'WS_UPDATE', payload, revision: _stateRevision })
  }

  /**
   * 用服务端快照初始化 Worker 内部任务列表（适用于页面刷新后的数据恢复）。
   */
  function initTasks(initialTasks: QueueTask[]): void {
    if (!Array.isArray(initialTasks)) return

    tasks.value = normalizeQueueSnapshot(initialTasks)
    stats.value = computeQueueStats(tasks.value)
    _stateRevision += 1
    _postToReadyWorker({
      type: 'INIT_TASKS',
      payload: tasks.value,
      revision: _stateRevision,
    })
  }

  // ── 降级逻辑（Worker 不可用时） ────────────────────────────────────────────
  function _fallbackUpdate(payload: WsUpdatePayload): void {
    tasks.value = applyQueueUpdate(
      tasks.value,
      payload,
      normalizeCoverageDiagnostics(payload.coverageDiagnostics),
    ) as QueueTask[]
    stats.value = computeQueueStats(tasks.value)
    _stateRevision += 1
  }

  // ── 清理（路由离开或应用卸载时调用） ───────────────────────────────────────
  /**
   * 释放 Worker 和 WebSocket 资源。
   * 由于 Pinia setup store 内的 onUnmounted 生命周期不可靠，
   * 建议在挂载此 Store 的顶层组件的 onUnmounted 钩子中手动调用。
   */
  function dispose(): void {
    // 1. 取消所有挂起的重连计划，防止 dispose 后仍触发新连接
    if (_wsReconnectTimer !== null) {
      clearTimeout(_wsReconnectTimer)
      _wsReconnectTimer = null
    }

    // 2. 先摘掉 Worker 的所有消息回调，再发 STOP 并 terminate。
    //    这样在 terminate 返回前不会有任何 TICK 写入 tasks/stats。
    _workerBridge.stop()

    // 3. 先摘掉 WebSocket 的所有事件钩子，再关闭连接。
    //    摘掉 onclose 可阻断 _scheduleWsReconnect 的触发链。
    if (_ws) {
      _ws.onopen    = null
      _ws.onmessage = null
      _ws.onerror   = null
      _ws.onclose   = null
      _ws.close()
      _ws = null
    }

    // 4. 回调全部屏蔽后，安全地清空响应式状态
    tasks.value = []
    stats.value = { ...EMPTY_STATS }
    _stateRevision = 0
  }

  return {
    // ── 状态（只读，禁止在视图层直接写入） ──
    tasks,
    stats,
    // ── 生命周期 ──
    initWorker,
    dispose,
    // ── WebSocket（推荐入口：持票上船；旧版直连保留作降级） ──
    connectEventBus,
    connectWebSocket,
    // ── 兼容接口 ──
    pushTaskUpdate,
    initTasks,
  }
})
