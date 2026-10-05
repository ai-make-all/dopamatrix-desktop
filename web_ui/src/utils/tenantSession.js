export const TENANT_SESSION_STORAGE_KEY = 'dopamatrix_user'

export async function validateTenantSession(httpClient, apiBase, tenantId) {
  const response = await httpClient.post(`${apiBase}/api/v1/tenant/session/validate`, {
    tenant_id: tenantId,
  })
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
}) {
  const canonicalTenant = await validateTenantSession(httpClient, apiBase, tenantId)
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
