/// <reference lib="webworker" />
/**
 * queueWorker.ts — Web Worker 状态机引擎
 *
 * 职责：在独立线程中维护任务队列与统计摘要。
 * 每秒通过 postMessage 向主线程推送 TICK，彻底将高频计算移出 UI 线程。
 *
 * ────── 接收的消息类型 ──────
 *  { type: 'WS_UPDATE',  payload: WsUpdatePayload }  — 新增或更新一条任务
 *  { type: 'INIT_TASKS', payload: QueueTask[]      }  — 页面刷新时批量初始化
 *  { type: 'STOP'                                  }  — 清理定时器并退出
 *
 * ────── 推送的消息类型 ──────
 *  { type: 'TICK', payload: { tasks: QueueTask[], stats: QueueStats } }
 */

// ── 共享类型定义 ─────────────────────────────────────────────────────────────

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface QueueTaskAsset {
  file_path: string
  file_hash: string
  /** 封面帧路径（历史水合后注入，WS 推送时可能为空）*/
  cover_path?: string
  /** 审批状态（历史水合后注入）*/
  status?: string
}

export interface QueueTask {
  id: string
  type: TaskStatus
  prompt: string
  ts: string
  startTime: number
  startTs: string
  endTime?: number
  endTs?: string
  duration?: string
  assets?: QueueTaskAsset[]
}

export interface QueueStats {
  totalPending: number
  totalRunning: number
  totalCompleted: number
  totalFailed: number
  /** 当前剩余预估秒数（倒计时由 Worker 内部驱动，每秒 -1）*/
  estimatedETA_seconds: number
}

export interface WsUpdatePayload {
  taskId: string
  status: TaskStatus
  prompt?: string
  assets?: QueueTaskAsset[]
  startTime?: number
}

// ── 内部状态 ─────────────────────────────────────────────────────────────────

let _tasks: QueueTask[] = []

let _stats: QueueStats = {
  totalPending:          0,
  totalRunning:          0,
  totalCompleted:        0,
  totalFailed:           0,
  estimatedETA_seconds:  0,
}

/**
 * ETA 动态校准：用滑动窗口追踪最近 N 条已完成任务的真实耗时均值。
 * 初始假设每任务 45 秒，随实测数据持续修正。
 */
const DEFAULT_TASK_DURATION_S = 45
const ETA_WINDOW_SIZE          = 20   // 只保留最近 20 个样本，避免早期慢任务永久拉高 ETA

const _durationSamples: number[] = []

function _getAvgDuration(): number {
  if (_durationSamples.length === 0) return DEFAULT_TASK_DURATION_S
  const sum = _durationSamples.reduce((acc, v) => acc + v, 0)
  return sum / _durationSamples.length
}

function _recordCompletedDuration(durationSec: number): void {
  _durationSamples.push(durationSec)
  if (_durationSamples.length > ETA_WINDOW_SIZE) {
    _durationSamples.shift()
  }
}

// ── 核心计算 ─────────────────────────────────────────────────────────────────

function _recomputeStats(): void {
  let pending = 0, running = 0, completed = 0, failed = 0

  for (const t of _tasks) {
    switch (t.type) {
      case 'pending':   pending++;   break
      case 'running':   running++;   break
      case 'completed': completed++; break
      case 'failed':    failed++;    break
    }
  }

  _stats = {
    totalPending:         pending,
    totalRunning:         running,
    totalCompleted:       completed,
    totalFailed:          failed,
    // 校准 ETA：以未完成任务数 × 平均耗时为基准。
    // 当倒计时已经比重算值更小时（用户等待时间内已有进展），保留当前值，避免时间"跳涨"。
    estimatedETA_seconds: Math.max(
      _stats.estimatedETA_seconds,
      Math.round((pending + running) * _getAvgDuration())
    ),
  }

  // 全部任务清零时，ETA 也归零
  if (pending === 0 && running === 0) {
    _stats.estimatedETA_seconds = 0
  }
}

function _broadcastTick(): void {
  // 发出浅拷贝，防止 transferable 意外污染内部状态
  ;(self as DedicatedWorkerGlobalScope).postMessage({
    type:    'TICK',
    payload: {
      tasks: _tasks.slice(),
      stats: { ..._stats },
    },
  })
}

// ── 每秒倒计时驱动 ───────────────────────────────────────────────────────────

const _tickInterval = setInterval(() => {
  if (_stats.totalPending > 0 || _stats.totalRunning > 0) {
    _stats = {
      ..._stats,
      estimatedETA_seconds: Math.max(0, _stats.estimatedETA_seconds - 1),
    }
  }
  _broadcastTick()
}, 1_000)

// ── 消息处理器 ───────────────────────────────────────────────────────────────

;(self as DedicatedWorkerGlobalScope).onmessage = (event: MessageEvent) => {
  const msg = event.data as { type: string; payload?: unknown }
  if (!msg?.type) return

  switch (msg.type) {

    case 'WS_UPDATE':
      _handleWsUpdate(msg.payload as WsUpdatePayload)
      break

    case 'INIT_TASKS': {
      const incoming = msg.payload
      if (Array.isArray(incoming)) {
        _tasks = (incoming as QueueTask[]).filter(t => t && typeof t.id === 'string')
        _recomputeStats()
        _broadcastTick()
      }
      break
    }

    case 'STOP':
      clearInterval(_tickInterval)
      break

    default:
      break
  }
}

// ── WS_UPDATE 处理逻辑 ───────────────────────────────────────────────────────

function _handleWsUpdate(payload: WsUpdatePayload): void {
  if (!payload?.taskId) return

  const existing = _tasks.find(t => t.id === payload.taskId)

  if (!existing) {
    // ── 新任务入队 ───────────────────────────────────────────────────────────
    const now = new Date()
    const ts  = now.toLocaleTimeString('zh', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })

    _tasks.unshift({
      id:        payload.taskId,
      type:      payload.status ?? 'pending',
      prompt:    (payload.prompt?.trim() ? payload.prompt : '正在解析任务描述...').slice(0, 120),
      ts,
      startTime: payload.startTime ?? Date.now(),
      startTs:   ts,
      assets:    payload.assets ?? [],
    })
  } else {
    // ── 更新已有任务 ─────────────────────────────────────────────────────────
    const prevType = existing.type

    existing.type = payload.status

    if (payload.assets?.length) {
      existing.assets = payload.assets
        .filter(a => a && typeof a === 'object')
        .map(a => ({
          file_path:  typeof a.file_path  === 'string' ? a.file_path  : '',
          file_hash:  typeof a.file_hash  === 'string' ? a.file_hash  : '',
          cover_path: typeof a.cover_path === 'string' ? a.cover_path : undefined,
        }))
    }

    const nowMs  = Date.now()
    const nowStr = new Date(nowMs).toLocaleTimeString('zh', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })

    if (prevType !== 'completed' && payload.status === 'completed') {
      existing.endTime = nowMs
      existing.endTs   = nowStr

      if (existing.startTime) {
        const durationSec  = (nowMs - existing.startTime) / 1_000
        existing.duration  = durationSec.toFixed(1) + 's'
        _recordCompletedDuration(durationSec)
      }

    } else if (
      (prevType === 'pending' || prevType === 'running') &&
      payload.status === 'failed'
    ) {
      existing.endTime = nowMs
      existing.endTs   = nowStr
    }
  }

  _recomputeStats()
  _broadcastTick()
}
