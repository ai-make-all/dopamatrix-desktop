export function createQueueWorkerBridge({
  createWorker,
  getInitialState,
  onTick,
  onUnavailable,
  readyTimeoutMs = 2_000,
  scheduleTimeout = setTimeout,
  cancelTimeout = clearTimeout,
}) {
  let worker = null
  let ready = false
  let readyTimer = null

  function clearReadyTimer() {
    if (readyTimer !== null) {
      cancelTimeout(readyTimer)
      readyTimer = null
    }
  }

  function disable(candidate, reason) {
    if (worker !== candidate) return
    clearReadyTimer()
    candidate.onmessage = null
    candidate.onerror = null
    candidate.onmessageerror = null
    candidate.terminate()
    worker = null
    ready = false
    onUnavailable(reason)
  }

  function start() {
    if (worker) return true

    let candidate
    try {
      candidate = createWorker()
    } catch {
      onUnavailable('construction-failed')
      return false
    }

    worker = candidate
    ready = false
    candidate.onmessage = event => {
      if (worker !== candidate) return
      const message = event?.data

      if (message?.type === 'READY') {
        if (ready) return
        ready = true
        clearReadyTimer()
        const initial = getInitialState()
        try {
          candidate.postMessage({
            type: 'INIT_TASKS',
            payload: initial.tasks,
            revision: initial.revision,
          })
        } catch {
          disable(candidate, 'initial-state-transfer-failed')
        }
        return
      }

      if (message?.type === 'TICK') onTick(message.payload)
    }
    candidate.onerror = () => disable(candidate, 'load-or-runtime-error')
    candidate.onmessageerror = () => disable(candidate, 'message-deserialization-error')
    readyTimer = scheduleTimeout(() => disable(candidate, 'ready-timeout'), readyTimeoutMs)
    return true
  }

  function post(message) {
    const candidate = worker
    if (!candidate || !ready) return false
    try {
      candidate.postMessage(message)
      return true
    } catch {
      disable(candidate, 'post-message-failed')
      return false
    }
  }

  function stop() {
    const candidate = worker
    clearReadyTimer()
    if (!candidate) return

    candidate.onmessage = null
    candidate.onerror = null
    candidate.onmessageerror = null
    try {
      candidate.postMessage({ type: 'STOP' })
    } catch {
      // Termination is still authoritative if the Worker channel is broken.
    }
    candidate.terminate()
    worker = null
    ready = false
  }

  return {
    start,
    post,
    stop,
    isReady: () => ready,
  }
}
