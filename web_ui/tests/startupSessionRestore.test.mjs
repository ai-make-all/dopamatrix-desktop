import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import axios from 'axios'
import { createPinia, setActivePinia } from 'pinia'

import { useAppStore } from '../src/stores/appStore.js'
import {
  STARTUP_RESTORE_MAX_ATTEMPTS,
  STARTUP_RESTORE_MAX_ELAPSED_MS,
  TENANT_SESSION_STORAGE_KEY,
} from '../src/utils/tenantSession.js'
import {
  STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS,
  STARTUP_TRACE_STORAGE_KEY,
} from '../src/utils/startupReadiness.js'


const TENANT = 'ph-elv-0001'


function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  let setCount = 0
  const setCounts = new Map()
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => {
      setCount += 1
      setCounts.set(key, (setCounts.get(key) ?? 0) + 1)
      values.set(key, String(value))
    },
    removeItem: key => values.delete(key),
    get setCount() { return setCount },
    getSetCount: key => setCounts.get(key) ?? 0,
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


function healthyResponse(version = '1.5.0-rc2') {
  return {
    status: 200,
    data: {
      status: 'DopaMatrix Engine is running',
      version,
      db: 'connected',
    },
  }
}


function healthyReadinessClient(onRequest) {
  const calls = []
  return {
    calls,
    async get(url, config) {
      calls.push({ url, config })
      onRequest?.(url, config)
      return healthyResponse()
    },
  }
}


function initStoreAuth(store, sessionRuntime, overrides = {}) {
  return store.initAuth({
    readinessClient: overrides.readinessClient ?? healthyReadinessClient(),
    readinessRuntime: overrides.readinessRuntime ?? fakeRetryRuntime(),
    sessionRuntime,
    traceRuntime: overrides.traceRuntime,
  })
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

  assert.equal(await initStoreAuth(store, runtime), true)
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

  assert.equal(await initStoreAuth(store, runtime), true)
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

  assert.equal(await initStoreAuth(store, runtime), true)
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

  assert.equal(await initStoreAuth(store, runtime), true)
  assert.equal(requests.length, 4)
  assert.deepEqual(runtime.delays, [200, 400, 800])
  assert.equal(storage.getSetCount(TENANT_SESSION_STORAGE_KEY), 1)
  assert.equal(store.isLoggedIn, true)
})


for (const status of [400, 403]) {
  test(`HTTP ${status} clears authority without retry`, async () => {
    const runtime = fakeRetryRuntime()
    const { store, storage, requests } = prepareStore({
      responder: async () => { throw httpError(status) },
    })

    assert.equal(await initStoreAuth(store, runtime), false)
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

  assert.equal(await initStoreAuth(store, runtime), false)
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

  assert.equal(await initStoreAuth(store, runtime), false)
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

  assert.equal(await initStoreAuth(store, runtime), false)
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

  assert.equal(await initStoreAuth(store, runtime), false)
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

  assert.equal(await initStoreAuth(store, runtime), false)
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

  assert.equal(await initStoreAuth(store, runtime), false)
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

  assert.equal(await initStoreAuth(store, runtime), false)
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

    assert.equal(await initStoreAuth(store, runtime), true)
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

  assert.equal(await initStoreAuth(store, runtime), true)
  assert.equal(requests.length, 3)
  assert.equal(storage.getSetCount(TENANT_SESSION_STORAGE_KEY), 1)
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), TENANT)
  assert.equal(axios.defaults.headers.common['X-Local-User'], TENANT)
})


test('no persisted tenant hint makes zero restore requests', async () => {
  const runtime = fakeRetryRuntime()
  const { store, requests } = prepareStore({
    storedTenant: null,
    responder: async () => { throw new Error('restore must not be called') },
  })

  const readinessClient = {
    calls: 0,
    async get() {
      this.calls += 1
      throw new Error('readiness must not be called')
    },
  }

  assert.equal(await initStoreAuth(store, runtime, { readinessClient }), false)
  assert.equal(requests.length, 0)
  assert.equal(readinessClient.calls, 0)
  assert.equal(store.isLoggedIn, false)
})


test('hint-bearing startup completes readiness before session validation', async () => {
  const order = []
  const readinessClient = healthyReadinessClient(() => order.push('health'))
  const { store, storage, requests } = prepareStore({
    responder: async () => {
      order.push('session')
      return usableResponse()
    },
  })

  assert.equal(await initStoreAuth(store, fakeRetryRuntime(), { readinessClient }), true)
  assert.deepEqual(order, ['health', 'session'])
  assert.equal(readinessClient.calls.length, 1)
  assert.equal(requests.length, 1)

  const trace = JSON.parse(storage.getItem(STARTUP_TRACE_STORAGE_KEY))
  assert.deepEqual(trace.events.map(event => event.event), [
    'STARTUP_BACKEND_READINESS_WAIT_BEGIN',
    'STARTUP_BACKEND_READY',
    'STARTUP_SESSION_RESTORE_BEGIN',
    'STARTUP_SESSION_RESTORE_SUCCESS',
  ])
})


test('session validation cannot begin while readiness is still retrying', async () => {
  const readinessRuntime = fakeRetryRuntime()
  let healthCalls = 0
  let sessionCalls = 0
  const readinessClient = {
    async get() {
      healthCalls += 1
      assert.equal(sessionCalls, 0)
      if (healthCalls < 3) throw axiosTransportError('ECONNREFUSED')
      return healthyResponse()
    },
  }
  const { store } = prepareStore({
    responder: async () => {
      sessionCalls += 1
      assert.equal(healthCalls, 3)
      return usableResponse()
    },
  })

  assert.equal(await initStoreAuth(store, fakeRetryRuntime(), {
    readinessClient,
    readinessRuntime,
  }), true)
  assert.equal(healthCalls, 3)
  assert.equal(sessionCalls, 1)
  assert.deepEqual(readinessRuntime.delays, [200, 400])
})


test('field-shape delayed readiness gives session a fresh full 8000-ms budget', async () => {
  const readinessRuntime = fakeRetryRuntime()
  const sessionRuntime = fakeRetryRuntime()
  const readinessClient = {
    async get(_, config) {
      if (readinessRuntime.elapsed >= 10000) return healthyResponse()
      await readinessRuntime.sleep(config.timeout)
      throw axiosTransportError('ECONNREFUSED')
    },
  }
  const { store, requests } = prepareStore({ responder: usableResponse })

  assert.equal(await initStoreAuth(store, sessionRuntime, {
    readinessClient,
    readinessRuntime,
  }), true)
  assert.ok(readinessRuntime.elapsed >= 10000)
  assert.ok(readinessRuntime.elapsed < STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS)
  assert.equal(sessionRuntime.elapsed, 0)
  assert.equal(requests.length, 1)
  assert.equal(requests[0].timeout, STARTUP_RESTORE_MAX_ELAPSED_MS)
  assert.equal(store.isLoggedIn, true)
})


test('readiness exhaustion retains hint, skips session, and exposes safe Login state', async () => {
  const readinessRuntime = fakeRetryRuntime()
  const readinessClient = {
    async get(_, config) {
      await readinessRuntime.sleep(config.timeout)
      throw axiosTransportError('ETIMEDOUT')
    },
  }
  const { store, storage, requests } = prepareStore({
    responder: async () => { throw new Error('session must not be called') },
  })

  assert.equal(await initStoreAuth(store, fakeRetryRuntime(), {
    readinessClient,
    readinessRuntime,
    traceRuntime: readinessRuntime,
  }), false)
  assert.equal(readinessRuntime.elapsed, STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS)
  assert.equal(requests.length, 0)
  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), TENANT)
  assert.equal(store.isLoggedIn, false)
  assert.equal(store.loggedInUser, '')
  assert.equal(store.startupRestoreIssue, 'BACKEND_UNAVAILABLE')

  const trace = JSON.parse(storage.getItem(STARTUP_TRACE_STORAGE_KEY))
  assert.equal(trace.events.at(-1).event, 'STARTUP_BACKEND_READINESS_EXHAUSTED')
  assert.equal(trace.events.at(-1).elapsed_ms, STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS)
})


test('Login presents only the bounded backend-unavailable diagnostic', async () => {
  const loginSource = await readFile(new URL('../src/components/Login.vue', import.meta.url), 'utf8')
  assert.match(loginSource, /startupRestoreIssue === 'BACKEND_UNAVAILABLE'/)
  assert.match(loginSource, /Local engine did not become ready\./)
  assert.match(loginSource, /saved workspace session was retained/)
  assert.doesNotMatch(loginSource, /Tenant invalid|session invalid/i)
})


test('production readiness client is isolated from session authority defaults', async () => {
  const storeSource = await readFile(new URL('../src/stores/appStore.js', import.meta.url), 'utf8')
  assert.match(storeSource, /startupReadinessClient = axios\.create\(\{ withCredentials: false \}\)/)
  assert.match(storeSource, /delete startupReadinessClient\.defaults\.headers\.common\['X-Local-User'\]/)
  assert.match(storeSource, /delete startupReadinessClient\.defaults\.headers\.common\.Authorization/)
  const readinessCall = storeSource.match(/await waitForBackendReadiness\(\{([\s\S]*?)\}, \{/)
  assert.ok(readinessCall)
  assert.doesNotMatch(readinessCall[1], /tenantId|headers|Authorization|cookie|api.?key/i)
})
