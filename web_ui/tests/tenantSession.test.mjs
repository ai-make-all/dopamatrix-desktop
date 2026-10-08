import assert from 'node:assert/strict'
import test from 'node:test'

import {
  TENANT_SESSION_STORAGE_KEY,
  establishTenantSession,
  restoreTenantSession,
} from '../src/utils/tenantSession.js'


function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  }
}


test('unauthorized login does not persist or install tenant authority', async () => {
  const storage = memoryStorage()
  const headers = {}
  const httpClient = {
    post: async () => {
      const error = new Error('forbidden')
      error.response = { status: 403 }
      throw error
    },
  }

  await assert.rejects(establishTenantSession({
    httpClient,
    apiBase: 'http://127.0.0.1:8000',
    storage,
    headers,
    tenantId: 'testduplicate',
  }))
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), null)
  assert.equal(headers['X-Local-User'], undefined)
})


test('authorized provisioned tenant is committed only after backend validation', async () => {
  const storage = memoryStorage()
  const headers = {}
  const httpClient = {
    post: async () => ({
      data: {
        tenant_id: 'ph-elv-0001',
        authorized: true,
        provisioned: true,
        usable: true,
      },
    }),
  }

  const tenant = await establishTenantSession({
    httpClient,
    apiBase: 'http://127.0.0.1:8000',
    storage,
    headers,
    tenantId: 'ph-elv-0001',
  })
  assert.equal(tenant, 'ph-elv-0001')
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), 'ph-elv-0001')
  assert.equal(headers['X-Local-User'], 'ph-elv-0001')
})


test('stale unauthorized localStorage tenant is removed during restoration', async () => {
  const storage = memoryStorage({ [TENANT_SESSION_STORAGE_KEY]: 'testduplicate' })
  const headers = { 'X-Local-User': 'testduplicate' }
  const httpClient = {
    post: async () => {
      const error = new Error('forbidden')
      error.response = { status: 403 }
      throw error
    },
  }

  await assert.rejects(restoreTenantSession({
    httpClient,
    apiBase: 'http://127.0.0.1:8000',
    storage,
    headers,
    tenantId: 'testduplicate',
  }))
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), null)
  assert.equal(headers['X-Local-User'], undefined)
})


test('malformed tenant HTTP 400 clears persisted restoration authority', async () => {
  const storage = memoryStorage({ [TENANT_SESSION_STORAGE_KEY]: 'malformed' })
  const headers = { 'X-Local-User': 'malformed' }
  const httpClient = {
    post: async () => {
      const error = new Error('bad request')
      error.response = { status: 400 }
      throw error
    },
  }

  await assert.rejects(restoreTenantSession({
    httpClient,
    apiBase: 'http://127.0.0.1:8000',
    storage,
    headers,
    tenantId: 'malformed',
  }))
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), null)
  assert.equal(headers['X-Local-User'], undefined)
})


test('non-authoritative HTTP 500 retains only the persisted restoration hint', async () => {
  const storage = memoryStorage({ [TENANT_SESSION_STORAGE_KEY]: 'ph-elv-0001' })
  const headers = { 'X-Local-User': 'ph-elv-0001' }
  const httpClient = {
    post: async () => {
      const error = new Error('server error')
      error.response = { status: 500 }
      throw error
    },
  }

  await assert.rejects(restoreTenantSession({
    httpClient,
    apiBase: 'http://127.0.0.1:8000',
    storage,
    headers,
    tenantId: 'ph-elv-0001',
  }))
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), 'ph-elv-0001')
  assert.equal(headers['X-Local-User'], undefined)
})
