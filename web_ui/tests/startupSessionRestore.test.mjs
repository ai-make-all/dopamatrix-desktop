import assert from 'node:assert/strict'
import test from 'node:test'

import axios from 'axios'
import { createPinia, setActivePinia } from 'pinia'

import { useAppStore } from '../src/stores/appStore.js'
import {
  STARTUP_RESTORE_MAX_ATTEMPTS,
  STARTUP_RESTORE_MAX_ELAPSED_MS,
  TENANT_SESSION_STORAGE_KEY,
} from '../src/utils/tenantSession.js'


const TENANT = 'ph-elv-0001'


function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  let setCount = 0
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => {
      setCount += 1
      values.set(key, String(value))
    },
    removeItem: key => values.delete(key),
    get setCount() { return setCount },
  }
}


function fakeRetryRuntime() {
  let elapsed = 0
  const delays = []
  return {
    now: () => elapsed,
    sleep: async delay => {
      delays.push(delay)
      elapsed += delay
    },
    get elapsed() { return elapsed },
    get delays() { return [...delays] },
  }
}


function usableResponse() {
  return {
    data: {
      tenant_id: TENANT,
      authorized: true,
      provisioned: true,
      usable: true,
    },
  }
}


function axiosTransportError(code = 'ERR_NETWORK') {
  const error = new Error(code)
  error.code = code
  error.isAxiosError = true
  error.request = {}
  return error
}


function httpError(status) {
  const error = new Error(`HTTP ${status}`)
  error.isAxiosError = true
  error.response = { status }
  return error
}


function prepareStore({ storedTenant = TENANT, responder }) {
  const storage = memoryStorage(
    storedTenant ? { [TENANT_SESSION_STORAGE_KEY]: storedTenant } : {},
  )
  globalThis.localStorage = storage
  setActivePinia(createPinia())
  delete axios.defaults.headers.common['X-Local-User']

  const requests = []
  axios.post = async (url, body, config) => {
    requests.push({ url, body, timeout: config?.timeout })
    return responder(requests.length)
  }
  axios.get = async () => ({ data: { delivery_root: '' } })

  return { store: useAppStore(), storage, requests }
}


test('stored valid tenant restores immediately in one authoritative attempt', async () => {
  const runtime = fakeRetryRuntime()
  const { store, storage, requests } = prepareStore({ responder: usableResponse })

  assert.equal(await store.initAuth(runtime), true)
  assert.equal(requests.length, 1)
  assert.equal(store.isLoggedIn, true)
  assert.equal(store.loggedInUser, TENANT)
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), TENANT)
  assert.equal(axios.defaults.headers.common['X-Local-User'], TENANT)
})


test('first transient transport failure retries and later restores', async () => {
  const runtime = fakeRetryRuntime()
  const { store, requests } = prepareStore({
    responder: async attempt => {
      if (attempt === 1) throw axiosTransportError()
      return usableResponse()
    },
  })

  assert.equal(await store.initAuth(runtime), true)
  assert.equal(requests.length, 2)
  assert.deepEqual(runtime.delays, [200])
  assert.equal(store.isLoggedIn, true)
})


test('Axios timeout is retryable and later restores', async () => {
  const runtime = fakeRetryRuntime()
  const { store, requests } = prepareStore({
    responder: async attempt => {
      if (attempt === 1) throw axiosTransportError('ECONNABORTED')
      return usableResponse()
    },
  })

  assert.equal(await store.initAuth(runtime), true)
  assert.equal(requests.length, 2)
  assert.deepEqual(runtime.delays, [200])
})


test('multiple transient failures stop immediately after eventual success', async () => {
  const runtime = fakeRetryRuntime()
  const { store, storage, requests } = prepareStore({
    responder: async attempt => {
      if (attempt < 4) throw axiosTransportError('ECONNREFUSED')
      return usableResponse()
    },
  })

  assert.equal(await store.initAuth(runtime), true)
  assert.equal(requests.length, 4)
  assert.deepEqual(runtime.delays, [200, 400, 800])
  assert.equal(storage.setCount, 1)
  assert.equal(store.isLoggedIn, true)
})


for (const status of [400, 403]) {
  test(`HTTP ${status} clears authority without retry`, async () => {
    const runtime = fakeRetryRuntime()
    const { store, storage, requests } = prepareStore({
      responder: async () => { throw httpError(status) },
    })

    assert.equal(await store.initAuth(runtime), false)
    assert.equal(requests.length, 1)
    assert.deepEqual(runtime.delays, [])
    assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), null)
    assert.equal(axios.defaults.headers.common['X-Local-User'], undefined)
    assert.equal(store.isLoggedIn, false)
  })
}


test('HTTP 500 is nonretryable and cannot authorize', async () => {
  const runtime = fakeRetryRuntime()
  const { store, storage, requests } = prepareStore({
    responder: async () => { throw httpError(500) },
  })

  assert.equal(await store.initAuth(runtime), false)
  assert.equal(requests.length, 1)
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), TENANT)
  assert.equal(axios.defaults.headers.common['X-Local-User'], undefined)
  assert.equal(store.isLoggedIn, false)
})


test('other HTTP 4xx is nonretryable and retains only the hint', async () => {
  const runtime = fakeRetryRuntime()
  const { store, storage, requests } = prepareStore({
    responder: async () => { throw httpError(404) },
  })

  assert.equal(await store.initAuth(runtime), false)
  assert.equal(requests.length, 1)
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), TENANT)
  assert.equal(axios.defaults.headers.common['X-Local-User'], undefined)
  assert.equal(store.isLoggedIn, false)
})


test('malformed or unusable HTTP 200 is nonretryable and cannot authorize', async () => {
  const runtime = fakeRetryRuntime()
  const { store, storage, requests } = prepareStore({
    responder: async () => ({
      data: { tenant_id: TENANT, authorized: true, provisioned: true, usable: false },
    }),
  })

  assert.equal(await store.initAuth(runtime), false)
  assert.equal(requests.length, 1)
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), TENANT)
  assert.equal(axios.defaults.headers.common['X-Local-User'], undefined)
  assert.equal(store.isLoggedIn, false)
})


test('programming error is nonretryable even with a network-like code', async () => {
  const runtime = fakeRetryRuntime()
  const { store, storage, requests } = prepareStore({
    responder: async () => {
      const error = new Error('programming failure')
      error.code = 'ERR_NETWORK'
      throw error
    },
  })

  assert.equal(await store.initAuth(runtime), false)
  assert.equal(requests.length, 1)
  assert.deepEqual(runtime.delays, [])
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), TENANT)
  assert.equal(store.isLoggedIn, false)
})


test('plain non-Axios error with HTTP 503 shape is nonretryable', async () => {
  const runtime = fakeRetryRuntime()
  const { store, storage, requests } = prepareStore({
    responder: async () => {
      const error = new Error('programming failure with response-shaped metadata')
      error.response = { status: 503 }
      throw error
    },
  })

  assert.equal(await store.initAuth(runtime), false)
  assert.equal(requests.length, 1)
  assert.deepEqual(runtime.delays, [])
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), TENANT)
  assert.equal(axios.defaults.headers.common['X-Local-User'], undefined)
  assert.equal(store.isLoggedIn, false)
})


test('canceled Axios error with HTTP 503 shape is nonretryable', async () => {
  const runtime = fakeRetryRuntime()
  const { store, storage, requests } = prepareStore({
    responder: async () => {
      const error = httpError(503)
      error.code = 'ERR_CANCELED'
      error.name = 'CanceledError'
      throw error
    },
  })

  assert.equal(await store.initAuth(runtime), false)
  assert.equal(requests.length, 1)
  assert.deepEqual(runtime.delays, [])
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), TENANT)
  assert.equal(axios.defaults.headers.common['X-Local-User'], undefined)
  assert.equal(store.isLoggedIn, false)
})


test('transient exhaustion is bounded, logged out, headerless, and retains hint', async () => {
  const runtime = fakeRetryRuntime()
  const { store, storage, requests } = prepareStore({
    responder: async () => { throw axiosTransportError() },
  })

  assert.equal(await store.initAuth(runtime), false)
  assert.ok(requests.length <= STARTUP_RESTORE_MAX_ATTEMPTS)
  assert.ok(runtime.elapsed <= STARTUP_RESTORE_MAX_ELAPSED_MS)
  assert.equal(requests.length, 10)
  assert.deepEqual(runtime.delays, [200, 400, 800, 1000, 1000, 1000, 1000, 1000, 1000])
  assert.equal(requests[0].timeout, STARTUP_RESTORE_MAX_ELAPSED_MS)
  assert.equal(requests.at(-1).timeout, 600)
  assert.ok(requests.every(request => request.timeout > 0))
  assert.ok(requests.every(request => request.timeout <= STARTUP_RESTORE_MAX_ELAPSED_MS))
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), TENANT)
  assert.equal(axios.defaults.headers.common['X-Local-User'], undefined)
  assert.equal(store.isLoggedIn, false)
  assert.equal(store.loggedInUser, '')
})


for (const status of [502, 503, 504]) {
  test(`HTTP ${status} is retryable and may reach authoritative success`, async () => {
    const runtime = fakeRetryRuntime()
    const { store, requests } = prepareStore({
      responder: async attempt => {
        if (attempt === 1) throw httpError(status)
        return usableResponse()
      },
    })

    assert.equal(await store.initAuth(runtime), true)
    assert.equal(requests.length, 2)
    assert.deepEqual(runtime.delays, [200])
    assert.equal(store.isLoggedIn, true)
  })
}


test('eventual success commits the canonical session exactly once', async () => {
  const runtime = fakeRetryRuntime()
  const { store, storage, requests } = prepareStore({
    responder: async attempt => {
      if (attempt < 3) throw axiosTransportError('ETIMEDOUT')
      return usableResponse()
    },
  })

  assert.equal(await store.initAuth(runtime), true)
  assert.equal(requests.length, 3)
  assert.equal(storage.setCount, 1)
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), TENANT)
  assert.equal(axios.defaults.headers.common['X-Local-User'], TENANT)
})


test('no persisted tenant hint makes zero restore requests', async () => {
  const runtime = fakeRetryRuntime()
  const { store, requests } = prepareStore({
    storedTenant: null,
    responder: async () => { throw new Error('restore must not be called') },
  })

  assert.equal(await store.initAuth(runtime), false)
  assert.equal(requests.length, 0)
  assert.equal(store.isLoggedIn, false)
})
