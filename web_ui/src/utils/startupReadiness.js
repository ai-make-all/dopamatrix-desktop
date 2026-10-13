export const STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS = 15000
export const STARTUP_BACKEND_READINESS_INITIAL_DELAY_MS = 200
export const STARTUP_BACKEND_READINESS_MAX_DELAY_MS = 1000
export const STARTUP_BACKEND_READINESS_REQUEST_TIMEOUT_MS = 1000

export const STARTUP_TRACE_STORAGE_KEY = 'dopamatrix_startup_trace_v1'
export const STARTUP_TRACE_MAX_EVENTS = 8

export const STARTUP_EVENT = Object.freeze({
  BACKEND_WAIT_BEGIN: 'STARTUP_BACKEND_READINESS_WAIT_BEGIN',
  BACKEND_READY: 'STARTUP_BACKEND_READY',
  BACKEND_EXHAUSTED: 'STARTUP_BACKEND_READINESS_EXHAUSTED',
  BACKEND_FAILED: 'STARTUP_BACKEND_READINESS_FAILED',
  SESSION_BEGIN: 'STARTUP_SESSION_RESTORE_BEGIN',
  SESSION_SUCCESS: 'STARTUP_SESSION_RESTORE_SUCCESS',
  SESSION_EXHAUSTED: 'STARTUP_SESSION_RESTORE_EXHAUSTED',
  SESSION_FAILED: 'STARTUP_SESSION_RESTORE_FAILED',
})

const SAFE_STARTUP_EVENTS = new Set(Object.values(STARTUP_EVENT))
const RETRYABLE_READINESS_HTTP_STATUSES = new Set([502, 503, 504])
const RETRYABLE_READINESS_AXIOS_CODES = new Set([
  'ECONNABORTED',
  'ECONNREFUSED',
  'ECONNRESET',
  'EHOSTUNREACH',
  'ENETUNREACH',
  'ERR_NETWORK',
  'ETIMEDOUT',
])

function sleepFor(delayMs) {
  return new Promise(resolve => setTimeout(resolve, delayMs))
}

function monotonicNow() {
  return globalThis.performance?.now?.() ?? Date.now()
}

function safeEmit(onEvent, event) {
  try {
    onEvent(event)
  } catch {
    // Startup diagnostics are non-authoritative and must not affect startup.
  }
}

function checkedNow(now) {
  const value = now()
  if (!Number.isFinite(value)) {
    throw new StartupBackendReadinessError('STARTUP_BACKEND_READINESS_CLOCK_INVALID')
  }
  return value
}

function elapsedSince(now, startedAt) {
  return Math.max(0, checkedNow(now) - startedAt)
}

function validHealthPayload(data) {
  return (
    data !== null
    && typeof data === 'object'
    && data.status === 'DopaMatrix Engine is running'
    && typeof data.version === 'string'
    && data.version.trim().length > 0
    && data.db === 'connected'
  )
}

export class StartupBackendReadinessError extends Error {
  constructor(code, options) {
    super(code, options)
    this.name = 'StartupBackendReadinessError'
    this.code = code
  }
}

export function isRetryableBackendReadinessError(error) {
  if (error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError') return false
  if (error?.isAxiosError !== true) return false

  const status = error?.response?.status
  if (RETRYABLE_READINESS_HTTP_STATUSES.has(status)) return true
  if (error?.response) return false

  if (RETRYABLE_READINESS_AXIOS_CODES.has(error?.code)) return true
  return Boolean(error?.request)
}

export function createStartupTrace(storage, {
  now = monotonicNow,
} = {}) {
  let startedAt
  try {
    startedAt = checkedNow(now)
  } catch {
    startedAt = 0
  }
  const events = []

  return function recordStartupEvent(event) {
    if (!SAFE_STARTUP_EVENTS.has(event) || events.length >= STARTUP_TRACE_MAX_EVENTS) return

    let elapsedMs = 0
    try {
      elapsedMs = Math.max(0, Math.round(checkedNow(now) - startedAt))
    } catch {
      // Keep the trace bounded and safe even if diagnostic timing is unavailable.
    }

    events.push({ event, elapsed_ms: elapsedMs })
    try {
      storage.setItem(STARTUP_TRACE_STORAGE_KEY, JSON.stringify({ events }))
    } catch {
      // Diagnostic persistence must never affect authentication or startup.
    }
  }
}

export async function waitForBackendReadiness({
  httpClient,
  apiBase,
}, {
  sleep = sleepFor,
  now = monotonicNow,
  onEvent = () => {},
} = {}) {
  if (!httpClient || typeof httpClient.get !== 'function' || typeof apiBase !== 'string') {
    throw new StartupBackendReadinessError('STARTUP_BACKEND_READINESS_ARGUMENT_INVALID')
  }

  const startedAt = checkedNow(now)
  let attempt = 0
  safeEmit(onEvent, STARTUP_EVENT.BACKEND_WAIT_BEGIN)

  function throwExhausted(cause) {
    safeEmit(onEvent, STARTUP_EVENT.BACKEND_EXHAUSTED)
    throw new StartupBackendReadinessError(
      'STARTUP_BACKEND_READINESS_EXHAUSTED',
      cause ? { cause } : undefined,
    )
  }

  while (true) {
    const elapsedBeforeAttempt = elapsedSince(now, startedAt)
    if (attempt > 0 && elapsedBeforeAttempt >= STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS) {
      throwExhausted()
    }

    const remainingMs = Math.max(
      1,
      STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS - elapsedBeforeAttempt,
    )
    attempt += 1

    try {
      const response = await httpClient.get(`${apiBase}/health`, {
        timeout: Math.min(STARTUP_BACKEND_READINESS_REQUEST_TIMEOUT_MS, remainingMs),
        withCredentials: false,
      })

      if (elapsedSince(now, startedAt) >= STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS) {
        throwExhausted()
      }

      if (RETRYABLE_READINESS_HTTP_STATUSES.has(response?.status)) {
        const error = new Error('STARTUP_BACKEND_HEALTH_RETRYABLE')
        error.isAxiosError = true
        error.response = { status: response.status }
        throw error
      }
      if (response?.status !== 200 || !validHealthPayload(response?.data)) {
        throw new StartupBackendReadinessError('STARTUP_BACKEND_HEALTH_UNEXPECTED')
      }

      safeEmit(onEvent, STARTUP_EVENT.BACKEND_READY)
      return response.data
    } catch (error) {
      if (error?.code === 'STARTUP_BACKEND_READINESS_EXHAUSTED') throw error
      if (!isRetryableBackendReadinessError(error)) {
        safeEmit(onEvent, STARTUP_EVENT.BACKEND_FAILED)
        throw error
      }

      const elapsedAfterAttempt = elapsedSince(now, startedAt)
      const remainingAfterAttempt = (
        STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS - elapsedAfterAttempt
      )
      if (remainingAfterAttempt <= 1) throwExhausted(error)

      const retryDelay = Math.min(
        STARTUP_BACKEND_READINESS_INITIAL_DELAY_MS * (2 ** (attempt - 1)),
        STARTUP_BACKEND_READINESS_MAX_DELAY_MS,
      )
      const boundedDelay = Math.min(retryDelay, remainingAfterAttempt - 1)
      if (boundedDelay <= 0) throwExhausted(error)

      await sleep(boundedDelay)
      if (elapsedSince(now, startedAt) >= STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS) {
        throwExhausted(error)
      }
    }
  }
}
