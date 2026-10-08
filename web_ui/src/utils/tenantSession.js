export const TENANT_SESSION_STORAGE_KEY = 'dopamatrix_user'

export const STARTUP_RESTORE_MAX_ATTEMPTS = 12
export const STARTUP_RESTORE_MAX_ELAPSED_MS = 8000
export const STARTUP_RESTORE_INITIAL_DELAY_MS = 200
export const STARTUP_RESTORE_MAX_DELAY_MS = 1000

const RETRYABLE_STARTUP_HTTP_STATUSES = new Set([502, 503, 504])
const RETRYABLE_AXIOS_ERROR_CODES = new Set([
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

export function isRetryableStartupRestoreError(error) {
  if (error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError') return false
  if (error?.isAxiosError !== true) return false

  const status = error?.response?.status
  if (RETRYABLE_STARTUP_HTTP_STATUSES.has(status)) return true
  if (error?.response) return false

  if (RETRYABLE_AXIOS_ERROR_CODES.has(error?.code)) return true
  return Boolean(error?.request)
}

export async function validateTenantSession(httpClient, apiBase, tenantId, requestConfig) {
  const response = await httpClient.post(`${apiBase}/api/v1/tenant/session/validate`, {
    tenant_id: tenantId,
  }, requestConfig)
  if (!response?.data?.authorized || !response?.data?.provisioned || !response?.data?.usable) {
    throw new Error('TENANT_SESSION_NOT_USABLE')
  }
  return response.data.tenant_id
}

export function commitTenantSession(storage, headers, tenantId) {
  storage.setItem(TENANT_SESSION_STORAGE_KEY, tenantId)
  headers['X-Local-User'] = tenantId
}

export function clearTenantSession(storage, headers) {
  storage.removeItem(TENANT_SESSION_STORAGE_KEY)
  delete headers['X-Local-User']
}

export async function establishTenantSession({
  httpClient,
  apiBase,
  storage,
  headers,
  tenantId,
  requestConfig,
}) {
  const canonicalTenant = await validateTenantSession(
    httpClient,
    apiBase,
    tenantId,
    requestConfig,
  )
  commitTenantSession(storage, headers, canonicalTenant)
  return canonicalTenant
}

export async function restoreTenantSession(options) {
  delete options.headers['X-Local-User']
  try {
    return await establishTenantSession(options)
  } catch (error) {
    if (error?.response?.status === 400 || error?.response?.status === 403) {
      clearTenantSession(options.storage, options.headers)
    }
    throw error
  }
}

export async function restoreTenantSessionWithRetry(options, {
  sleep = sleepFor,
  now = Date.now,
} = {}) {
  const startedAt = now()

  for (let attempt = 1; attempt <= STARTUP_RESTORE_MAX_ATTEMPTS; attempt += 1) {
    const elapsedBeforeAttempt = Math.max(0, now() - startedAt)
    if (attempt > 1 && elapsedBeforeAttempt >= STARTUP_RESTORE_MAX_ELAPSED_MS) {
      throw new Error('STARTUP_RESTORE_DEADLINE_EXCEEDED')
    }

    const remainingMs = Math.max(1, STARTUP_RESTORE_MAX_ELAPSED_MS - elapsedBeforeAttempt)

    try {
      return await restoreTenantSession({
        ...options,
        requestConfig: {
          ...options.requestConfig,
          timeout: remainingMs,
        },
      })
    } catch (error) {
      if (
        !isRetryableStartupRestoreError(error)
        || attempt >= STARTUP_RESTORE_MAX_ATTEMPTS
      ) {
        throw error
      }

      const elapsedAfterAttempt = Math.max(0, now() - startedAt)
      const remainingAfterAttempt = STARTUP_RESTORE_MAX_ELAPSED_MS - elapsedAfterAttempt
      const retryDelay = Math.min(
        STARTUP_RESTORE_INITIAL_DELAY_MS * (2 ** (attempt - 1)),
        STARTUP_RESTORE_MAX_DELAY_MS,
      )

      if (remainingAfterAttempt <= 0 || retryDelay >= remainingAfterAttempt) {
        throw error
      }

      await sleep(retryDelay)

      if (now() - startedAt >= STARTUP_RESTORE_MAX_ELAPSED_MS) {
        throw error
      }
    }
  }

  throw new Error('STARTUP_RESTORE_ATTEMPTS_EXHAUSTED')
}
