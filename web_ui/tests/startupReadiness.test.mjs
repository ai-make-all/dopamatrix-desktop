import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS,
  STARTUP_BACKEND_READINESS_REQUEST_TIMEOUT_MS,
  STARTUP_EVENT,
  STARTUP_TRACE_MAX_EVENTS,
  STARTUP_TRACE_STORAGE_KEY,
  createStartupTrace,
  waitForBackendReadiness,
} from '../src/utils/startupReadiness.js'


const API_BASE = 'http://127.0.0.1:8000'


function fakeClock() {
  let elapsed = 0
  const delays = []
  return {
    now: () => elapsed,
    sleep: async delay => {
      delays.push(delay)
      elapsed += delay
    },
    advance: delay => { elapsed += delay },
    get elapsed() { return elapsed },
    get delays() { return [...delays] },
  }
}


function healthResponse(version = '1.5.0-rc2') {
  return {
    status: 200,
    data: {
      status: 'DopaMatrix Engine is running',
      version,
      db: 'connected',
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


function clientWith(responder) {
  const calls = []
  return {
    calls,
    async get(url, config) {
      calls.push({ url, config })
      return responder(calls.length, config)
    },
  }
}


test('already-ready first probe succeeds immediately without auth or Tenant authority', async () => {
  const runtime = fakeClock()
  const client = clientWith(() => healthResponse())
  const events = []

  const health = await waitForBackendReadiness({
    httpClient: client,
    apiBase: API_BASE,
  }, {
    ...runtime,
    onEvent: event => events.push(event),
  })

  assert.equal(health.version, '1.5.0-rc2')
  assert.equal(client.calls.length, 1)
  assert.equal(client.calls[0].url, `${API_BASE}/health`)
  assert.equal(client.calls[0].config.timeout, STARTUP_BACKEND_READINESS_REQUEST_TIMEOUT_MS)
  assert.equal(client.calls[0].config.withCredentials, false)
  assert.equal(Object.hasOwn(client.calls[0].config, 'headers'), false)
  assert.deepEqual(runtime.delays, [])
  assert.deepEqual(events, [
    STARTUP_EVENT.BACKEND_WAIT_BEGIN,
    STARTUP_EVENT.BACKEND_READY,
  ])
})


test('temporary transport failure follows the accepted backoff then succeeds', async () => {
  const runtime = fakeClock()
  const client = clientWith(attempt => {
    if (attempt < 4) throw axiosTransportError('ECONNREFUSED')
    return healthResponse()
  })

  await waitForBackendReadiness({ httpClient: client, apiBase: API_BASE }, runtime)

  assert.equal(client.calls.length, 4)
  assert.deepEqual(runtime.delays, [200, 400, 800])
})


test('HTTP 502, 503, and 504 are retryable readiness results', async () => {
  const runtime = fakeClock()
  const statuses = [502, 503, 504]
  const client = clientWith(attempt => {
    if (attempt <= statuses.length) return { status: statuses[attempt - 1], data: {} }
    return healthResponse()
  })

  await waitForBackendReadiness({ httpClient: client, apiBase: API_BASE }, runtime)

  assert.equal(client.calls.length, 4)
  assert.deepEqual(runtime.delays, [200, 400, 800])
})


for (const code of [
  'ECONNABORTED',
  'ECONNREFUSED',
  'ECONNRESET',
  'EHOSTUNREACH',
  'ENETUNREACH',
  'ERR_NETWORK',
  'ETIMEDOUT',
]) {
  test(`${code} is retryable readiness transport failure`, async () => {
    const runtime = fakeClock()
    const client = clientWith(attempt => {
      if (attempt === 1) throw axiosTransportError(code)
      return healthResponse()
    })

    await waitForBackendReadiness({ httpClient: client, apiBase: API_BASE }, runtime)
    assert.equal(client.calls.length, 2)
    assert.deepEqual(runtime.delays, [200])
  })
}


test('cancellation, programming failure, HTTP 500, and malformed health do not broadly retry', async t => {
  const canceled = httpError(503)
  canceled.code = 'ERR_CANCELED'
  canceled.name = 'CanceledError'

  const cases = [
    ['cancellation', () => { throw canceled }],
    ['programming', () => { throw new Error('programming failure') }],
    ['http500', () => { throw httpError(500) }],
    ['malformed', () => ({ status: 200, data: { status: 'wrong' } })],
  ]

  for (const [name, responder] of cases) {
    await t.test(name, async () => {
      const runtime = fakeClock()
      const client = clientWith(responder)
      await assert.rejects(
        waitForBackendReadiness({ httpClient: client, apiBase: API_BASE }, runtime),
      )
      assert.equal(client.calls.length, 1)
      assert.deepEqual(runtime.delays, [])
    })
  }
})


test('readiness deadline is authoritative and request timeout is bounded by remaining time', async () => {
  const runtime = fakeClock()
  const events = []
  const client = clientWith((_, config) => {
    runtime.advance(config.timeout)
    throw axiosTransportError('ETIMEDOUT')
  })

  await assert.rejects(
    waitForBackendReadiness({ httpClient: client, apiBase: API_BASE }, {
      ...runtime,
      onEvent: event => events.push(event),
    }),
    error => error?.code === 'STARTUP_BACKEND_READINESS_EXHAUSTED',
  )

  assert.equal(runtime.elapsed, STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS)
  assert.ok(client.calls.every(call => call.config.timeout > 0))
  assert.ok(client.calls.every(call => call.config.timeout <= 1000))
  assert.equal(events.at(-1), STARTUP_EVENT.BACKEND_EXHAUSTED)
})


test('health completion is accepted just before but not at or after the readiness deadline', async t => {
  await t.test('just before', async () => {
    const runtime = fakeClock()
    const health = await waitForBackendReadiness({
      httpClient: clientWith(() => {
        runtime.advance(STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS - 1)
        return healthResponse()
      }),
      apiBase: API_BASE,
    }, runtime)
    assert.equal(health.db, 'connected')
  })

  for (const [name, elapsed] of [
    ['at deadline', STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS],
    ['after deadline', STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS + 1],
  ]) {
    await t.test(name, async () => {
      const runtime = fakeClock()
      await assert.rejects(waitForBackendReadiness({
        httpClient: clientWith(() => {
          runtime.advance(elapsed)
          return healthResponse()
        }),
        apiBase: API_BASE,
      }, runtime), error => error?.code === 'STARTUP_BACKEND_READINESS_EXHAUSTED')
    })
  }
})


test('field-shape health becomes usable after more than 8000 ms but before 15000 ms', async () => {
  const runtime = fakeClock()
  const client = clientWith((_, config) => {
    if (runtime.elapsed >= 10000) return healthResponse()
    runtime.advance(config.timeout)
    throw axiosTransportError('ECONNREFUSED')
  })

  const health = await waitForBackendReadiness(
    { httpClient: client, apiBase: API_BASE },
    runtime,
  )

  assert.equal(health.db, 'connected')
  assert.ok(runtime.elapsed >= 10000)
  assert.ok(runtime.elapsed < STARTUP_BACKEND_READINESS_MAX_ELAPSED_MS)
})


test('generic readiness validates a nonempty observed version without RC2 literal coupling', async () => {
  const source = await readFile(new URL('../src/utils/startupReadiness.js', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /1\.5\.0-rc2/)

  const health = await waitForBackendReadiness({
    httpClient: clientWith(() => healthResponse('future-version')),
    apiBase: API_BASE,
  }, fakeClock())
  assert.equal(health.version, 'future-version')
})


test('startup trace is fixed-code, bounded, overwriting, and secret-free by construction', () => {
  const values = new Map()
  const storage = {
    setItem: (key, value) => values.set(key, value),
  }
  const runtime = fakeClock()
  const record = createStartupTrace(storage, runtime)
  const allowed = Object.values(STARTUP_EVENT)

  for (let index = 0; index < 12; index += 1) {
    runtime.advance(10)
    record(allowed[index % allowed.length])
  }
  record('SECRET_EVENT_NOT_ALLOWED')

  const raw = values.get(STARTUP_TRACE_STORAGE_KEY)
  const trace = JSON.parse(raw)
  assert.equal(trace.events.length, STARTUP_TRACE_MAX_EVENTS)
  assert.ok(trace.events.every(event => (
    Object.keys(event).sort().join(',') === 'elapsed_ms,event'
  )))
  assert.ok(trace.events.every(event => allowed.includes(event.event)))
  assert.doesNotMatch(raw, /tenant|authorization|cookie|api.?key|token|dpapi/i)
})


test('startup trace storage failure never changes startup control flow', () => {
  const record = createStartupTrace({
    setItem: () => { throw new Error('storage unavailable') },
  }, fakeClock())
  assert.doesNotThrow(() => record(STARTUP_EVENT.BACKEND_WAIT_BEGIN))
})
