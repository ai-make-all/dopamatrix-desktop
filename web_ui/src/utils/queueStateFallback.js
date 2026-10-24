const TASK_STATUSES = new Set(['pending', 'running', 'completed', 'failed'])

function formatTimestamp(nowMs) {
  return new Date(nowMs).toLocaleTimeString('zh', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function normalizeAssets(assets) {
  if (!Array.isArray(assets)) return []
  return assets
    .filter(asset => asset && typeof asset === 'object')
    .map(asset => ({
      ...asset,
      file_path: typeof asset.file_path === 'string'
        ? asset.file_path
        : (typeof asset.path === 'string' ? asset.path : ''),
      file_hash: typeof asset.file_hash === 'string'
        ? asset.file_hash
        : (typeof asset.hash === 'string' ? asset.hash : ''),
      cover_path: typeof asset.cover_path === 'string' ? asset.cover_path : undefined,
    }))
}

export function normalizeQueueSnapshot(initialTasks) {
  if (!Array.isArray(initialTasks)) return []

  const seen = new Set()
  const result = []
  for (const task of initialTasks) {
    if (!task || typeof task.id !== 'string' || !task.id || seen.has(task.id)) continue
    seen.add(task.id)
    result.push(task)
  }
  return result
}

export function computeQueueStats(tasks) {
  const counts = { pending: 0, running: 0, completed: 0, failed: 0 }
  for (const task of Array.isArray(tasks) ? tasks : []) {
    if (TASK_STATUSES.has(task?.type)) counts[task.type] += 1
  }
  return {
    totalPending: counts.pending,
    totalRunning: counts.running,
    totalCompleted: counts.completed,
    totalFailed: counts.failed,
    estimatedETA_seconds: 0,
  }
}

export function applyQueueUpdate(currentTasks, payload, coverageDiagnostics, nowMs = Date.now()) {
  if (!payload?.taskId) return Array.isArray(currentTasks) ? currentTasks : []

  const tasks = normalizeQueueSnapshot(currentTasks).map(task => ({ ...task }))
  const index = tasks.findIndex(task => task.id === payload.taskId)
  const status = TASK_STATUSES.has(payload.status) ? payload.status : 'pending'

  if (index < 0) {
    const ts = formatTimestamp(nowMs)
    tasks.unshift({
      id: payload.taskId,
      type: status,
      prompt: payload.prompt?.trim()
        ? payload.prompt.slice(0, 120)
        : '正在解析任务描述...',
      mode: payload.mode || payload.generation_mode,
      generation_mode: payload.generation_mode || payload.mode,
      ts,
      startTime: payload.startTime ?? nowMs,
      startTs: ts,
      assets: normalizeAssets(payload.assets),
      partial: payload.partial,
      requestedCount: payload.requestedCount,
      plannedCount: payload.plannedCount,
      succeededCount: payload.succeededCount,
      failedCount: payload.failedCount,
      historyPersisted: payload.historyPersisted,
      warningCodes: Array.isArray(payload.warningCodes) ? [...payload.warningCodes] : undefined,
      coverageDiagnostics,
    })
    return tasks
  }

  const existing = tasks[index]
  const previousStatus = existing.type
  existing.type = status
  if (payload.partial !== undefined) existing.partial = payload.partial
  if (payload.requestedCount !== undefined) existing.requestedCount = payload.requestedCount
  if (payload.plannedCount !== undefined) existing.plannedCount = payload.plannedCount
  if (payload.succeededCount !== undefined) existing.succeededCount = payload.succeededCount
  if (payload.failedCount !== undefined) existing.failedCount = payload.failedCount
  if (payload.historyPersisted !== undefined) existing.historyPersisted = payload.historyPersisted
  if (Array.isArray(payload.warningCodes)) existing.warningCodes = [...payload.warningCodes]
  if (coverageDiagnostics) existing.coverageDiagnostics = coverageDiagnostics
  if (payload.mode || payload.generation_mode) {
    existing.mode = payload.mode || payload.generation_mode
    existing.generation_mode = payload.generation_mode || payload.mode
  }
  if (Array.isArray(payload.assets) && payload.assets.length > 0) {
    existing.assets = normalizeAssets(payload.assets)
  }

  if (previousStatus !== 'completed' && status === 'completed') {
    existing.endTime = nowMs
    existing.endTs = formatTimestamp(nowMs)
    if (existing.startTime) {
      existing.duration = ((nowMs - existing.startTime) / 1_000).toFixed(1) + 's'
    }
  } else if (
    (previousStatus === 'pending' || previousStatus === 'running') &&
    status === 'failed'
  ) {
    existing.endTime = nowMs
    existing.endTs = formatTimestamp(nowMs)
  }

  return tasks
}
