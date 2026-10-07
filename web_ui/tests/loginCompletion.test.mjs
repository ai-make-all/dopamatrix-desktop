import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { nextTick, reactive, ref } from 'vue'

import {
  AUTHENTICATED_HOME_ROUTE,
  installLoginCompletionRedirect,
} from '../src/utils/loginCompletion.js'
import {
  TENANT_SESSION_STORAGE_KEY,
  establishTenantSession,
} from '../src/utils/tenantSession.js'


function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  }
}


function loginHarness({ isLoggedIn = false, path = '/login' } = {}) {
  const store = reactive({ isLoggedIn, loggedInUser: '' })
  const currentRoute = ref({ path })
  const navigations = []
  const router = {
    currentRoute,
    replace: async target => {
      navigations.push(target)
      currentRoute.value = { path: target }
    },
  }
  const stop = installLoginCompletionRedirect({ store, router })
  return { store, currentRoute, navigations, stop }
}


async function flushLoginCompletion() {
  await nextTick()
  await Promise.resolve()
  await nextTick()
}


test('valid provisioned login commits once and navigates exactly once', async t => {
  const harness = loginHarness()
  t.after(harness.stop)
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

  async function handleLogin() {
    const tenant = await establishTenantSession({
      httpClient,
      apiBase: 'http://127.0.0.1:8000',
      storage,
      headers,
      tenantId: 'ph-elv-0001',
    })
    harness.store.loggedInUser = tenant
    harness.store.isLoggedIn = true
    return tenant
  }

  assert.equal(await handleLogin(), 'ph-elv-0001')
  await flushLoginCompletion()

  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), 'ph-elv-0001')
  assert.equal(headers['X-Local-User'], 'ph-elv-0001')
  assert.equal(harness.store.loggedInUser, 'ph-elv-0001')
  assert.equal(harness.store.isLoggedIn, true)
  assert.equal(harness.currentRoute.value.path, AUTHENTICATED_HOME_ROUTE)
  assert.deepEqual(harness.navigations, [AUTHENTICATED_HOME_ROUTE])
})


test('store transition cannot leave a successful login stranded on /login', async t => {
  const harness = loginHarness()
  t.after(harness.stop)

  harness.store.isLoggedIn = true
  await flushLoginCompletion()

  assert.equal(harness.currentRoute.value.path, AUTHENTICATED_HOME_ROUTE)
})


test('invalid tenant neither commits a session nor navigates', async t => {
  const harness = loginHarness()
  t.after(harness.stop)
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
    tenantId: 'abc',
  }))
  await flushLoginCompletion()

  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), null)
  assert.equal(headers['X-Local-User'], undefined)
  assert.equal(harness.store.isLoggedIn, false)
  assert.equal(harness.currentRoute.value.path, '/login')
  assert.deepEqual(harness.navigations, [])
})


test('approved but unprovisioned tenant neither commits nor navigates', async t => {
  const harness = loginHarness()
  t.after(harness.stop)
  const storage = memoryStorage()
  const headers = {}
  const httpClient = {
    post: async () => ({
      data: {
        tenant_id: 'ph-elv-0001',
        authorized: true,
        provisioned: false,
        usable: false,
      },
    }),
  }

  await assert.rejects(establishTenantSession({
    httpClient,
    apiBase: 'http://127.0.0.1:8000',
    storage,
    headers,
    tenantId: 'ph-elv-0001',
  }), /TENANT_SESSION_NOT_USABLE/)
  await flushLoginCompletion()

  assert.equal(storage.getItem(TENANT_SESSION_STORAGE_KEY), null)
  assert.equal(headers['X-Local-User'], undefined)
  assert.equal(harness.store.isLoggedIn, false)
  assert.equal(harness.currentRoute.value.path, '/login')
  assert.deepEqual(harness.navigations, [])
})


test('already logged-in state on /login redirects deterministically', async t => {
  const harness = loginHarness({ isLoggedIn: true, path: '/login' })
  t.after(harness.stop)
  await flushLoginCompletion()

  assert.equal(harness.currentRoute.value.path, AUTHENTICATED_HOME_ROUTE)
  assert.deepEqual(harness.navigations, [AUTHENTICATED_HOME_ROUTE])
})


test('one login completion does not navigate twice', async t => {
  const harness = loginHarness()
  t.after(harness.stop)

  harness.store.isLoggedIn = true
  await flushLoginCompletion()
  harness.store.isLoggedIn = true
  await flushLoginCompletion()

  assert.deepEqual(harness.navigations, [AUTHENTICATED_HOME_ROUTE])
})


test('production wiring has one state-driven navigation owner and no child emit path', async () => {
  const appSource = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
  const loginSource = await readFile(new URL('../src/components/Login.vue', import.meta.url), 'utf8')

  assert.match(appSource, /installLoginCompletionRedirect\(\{ store, router \}\)/)
  assert.match(appSource, /<Login v-if="!store\.isLoggedIn" \/>/)
  assert.doesNotMatch(appSource, /@login-success=/)
  assert.doesNotMatch(appSource, /router\.push\('\/dashboard'\)/)
  assert.doesNotMatch(loginSource, /defineEmits/)
  assert.doesNotMatch(loginSource, /emit\(['"]login-success['"]/)
})
