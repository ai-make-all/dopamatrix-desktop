import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { Worker as NodeWorker } from 'node:worker_threads'

import {
  applyQueueUpdate,
  computeQueueStats,
  normalizeQueueSnapshot,
} from '../src/utils/queueStateFallback.js'
import { createQueueWorkerBridge } from '../src/utils/queueWorkerBridge.js'

const root = fileURLToPath(new URL('../', import.meta.url))
const storeSource = readFileSync(`${root}src/stores/useQueueStore.ts`, 'utf8')
const workerSource = readFileSync(`${root}src/workers/queueWorker.ts`, 'utf8')
const queueViewSource = readFileSync(`${root}src/views/QueueView.vue`, 'utf8')
const workspaceSource = readFileSync(`${root}src/views/WorkspaceView.vue`, 'utf8')

test('production Worker uses Vite constructor import and READY failover protocol', () => {
  assert.match(storeSource, /import QueueWorker from '\.\.\/workers\/queueWorker\.ts\?worker'/)
  assert.match(storeSource, /createWorker:\s*\(\) => new QueueWorker\(\)/)
  assert.doesNotMatch(storeSource, /new URL\('\.\.\/workers\/queueWorker\.ts'/)
  assert.match(storeSource, /WORKER_READY_TIMEOUT_MS/)
  assert.match(storeSource, /tick\.revision < _stateRevision/)
  assert.match(workerSource, /postMessage\(\{ type: 'READY' \}\)/)
  assert.match(workerSource, /revision: _revision/)
})

class MockWorker {
  constructor({ throwOnPost = false } = {}) {
    this.throwOnPost = throwOnPost
    this.messages = []
    this.terminated = false
    this.onmessage = null
    this.onerror = null
    this.onmessageerror = null
  }

  postMessage(message) {
    if (this.throwOnPost) throw new Error('mock-post-failure')
    this.messages.push(message)
  }

  terminate() {
    this.terminated = true
  }

  emit(type, payload) {
    this.onmessage?.({ data: { type, payload } })
  }
}

test('Worker READY seeds the accepted snapshot and routes later messages', () => {
  const worker = new MockWorker()
  const unavailable = []
  const ticks = []
  const bridge = createQueueWorkerBridge({
    createWorker: () => worker,
    getInitialState: () => ({ tasks: [{ id: 'pending-1' }], revision: 7 }),
    onTick: payload => ticks.push(payload),
    onUnavailable: reason => unavailable.push(reason),
    scheduleTimeout: () => 1,
    cancelTimeout: () => {},
  })

  assert.equal(bridge.start(), true)
  assert.equal(bridge.post({ type: 'WS_UPDATE' }), false)
  worker.emit('READY')
  assert.equal(bridge.isReady(), true)
  assert.deepEqual(worker.messages[0], {
    type: 'INIT_TASKS', payload: [{ id: 'pending-1' }], revision: 7,
  })
  assert.equal(bridge.post({ type: 'WS_UPDATE', revision: 8 }), true)
  worker.emit('TICK', { tasks: [], stats: {}, revision: 8 })
  assert.equal(ticks.length, 1)
  assert.deepEqual(unavailable, [])
})

test('construction, load, message, timeout, and post failures disable the Worker', () => {
  const cases = [
    {
      expected: 'construction-failed',
      createWorker: () => { throw new Error('mock-construction-failure') },
      trigger: () => {},
    },
    {
      expected: 'load-or-runtime-error',
      createWorker: () => new MockWorker(),
      trigger: worker => worker.onerror?.(),
    },
    {
      expected: 'message-deserialization-error',
      createWorker: () => new MockWorker(),
      trigger: worker => worker.onmessageerror?.(),
    },
    {
      expected: 'ready-timeout',
      createWorker: () => new MockWorker(),
      trigger: (_worker, timeout) => timeout(),
    },
    {
      expected: 'post-message-failed',
      createWorker: () => new MockWorker(),
      trigger: (worker, _timeout, bridge) => {
        worker.emit('READY')
        worker.throwOnPost = true
        bridge.post({ type: 'WS_UPDATE', revision: 1 })
      },
    },
  ]

  for (const item of cases) {
    const unavailable = []
    let timeout = () => {}
    let created
    const bridge = createQueueWorkerBridge({
      createWorker: () => {
        created = item.createWorker()
        return created
      },
      getInitialState: () => ({ tasks: [], revision: 0 }),
      onTick: () => {},
      onUnavailable: reason => unavailable.push(reason),
      scheduleTimeout: callback => { timeout = callback; return 1 },
      cancelTimeout: () => {},
    })
    bridge.start()
    item.trigger(created, timeout, bridge)
    assert.equal(bridge.isReady(), false)
    assert.deepEqual(unavailable, [item.expected])
    if (created) assert.equal(created.terminated, true)
  }
})

test('a failed Worker can be replaced without losing the authoritative snapshot', () => {
  const first = new MockWorker()
  const second = new MockWorker()
  const workers = [first, second]
  const acceptedTasks = [{ id: 'accepted-before-failure', type: 'pending' }]
  const bridge = createQueueWorkerBridge({
    createWorker: () => workers.shift(),
    getInitialState: () => ({ tasks: acceptedTasks, revision: 11 }),
    onTick: () => {},
    onUnavailable: () => {},
    scheduleTimeout: () => 1,
    cancelTimeout: () => {},
  })

  bridge.start()
  first.onerror?.()
  assert.equal(first.terminated, true)
  assert.equal(bridge.start(), true)
  second.emit('READY')
  assert.deepEqual(second.messages[0], {
    type: 'INIT_TASKS', payload: acceptedTasks, revision: 11,
  })
})

test('pending to running to completed is deduplicated by logical task ID', () => {
  const taskId = 'logical-task-batch-1'
  let tasks = []
  tasks = applyQueueUpdate(tasks, { taskId, status: 'pending', requestedCount: 1 }, undefined, 1_000)
  tasks = applyQueueUpdate(tasks, { taskId, status: 'running' }, undefined, 2_000)
  tasks = applyQueueUpdate(tasks, { taskId, status: 'completed', succeededCount: 1 }, undefined, 4_000)
  tasks = applyQueueUpdate(tasks, { taskId, status: 'completed', succeededCount: 1 }, undefined, 5_000)

  assert.equal(tasks.length, 1)
  assert.equal(tasks[0].type, 'completed')
  assert.equal(tasks[0].requestedCount, 1)
  assert.equal(tasks[0].succeededCount, 1)
  assert.equal(tasks[0].duration, '3.0s')
  assert.deepEqual(computeQueueStats(tasks), {
    totalPending: 0,
    totalRunning: 0,
    totalCompleted: 1,
    totalFailed: 0,
    estimatedETA_seconds: 0,
  })
})

test('Batch 1 and Batch N remain one counter entry per backend logical task ID', () => {
  let tasks = []
  tasks = applyQueueUpdate(tasks, {
    taskId: 'batch-one', status: 'completed', requestedCount: 1, succeededCount: 1,
  }, undefined, 1_000)
  tasks = applyQueueUpdate(tasks, {
    taskId: 'batch-many', status: 'completed', requestedCount: 4, succeededCount: 4,
  }, undefined, 2_000)
  tasks = applyQueueUpdate(tasks, {
    taskId: 'batch-many', status: 'completed', requestedCount: 4, succeededCount: 4,
  }, undefined, 3_000)

  assert.equal(tasks.length, 2)
  assert.equal(computeQueueStats(tasks).totalCompleted, 2)
})

test('history hydration deduplicates IDs and immediately recomputes both Factory tabs', () => {
  const snapshot = normalizeQueueSnapshot([
    { id: 'pending-1', type: 'pending' },
    { id: 'completed-1', type: 'completed' },
    { id: 'completed-1', type: 'completed' },
  ])
  const stats = computeQueueStats(snapshot)

  assert.deepEqual(snapshot.map(task => task.id), ['pending-1', 'completed-1'])
  assert.equal(stats.totalPending + stats.totalRunning, 1)
  assert.equal(stats.totalCompleted, 1)
})

test('main-thread mirror is updated before optional Worker delivery', () => {
  const pushBody = storeSource.slice(
    storeSource.indexOf('function pushTaskUpdate'),
    storeSource.indexOf('/**', storeSource.indexOf('function pushTaskUpdate')),
  )
  assert.ok(pushBody.indexOf('_fallbackUpdate(payload)') < pushBody.indexOf('_postToReadyWorker'))
  assert.match(storeSource, /tasks\.value = normalizeQueueSnapshot\(initialTasks\)/)
  assert.match(storeSource, /stats\.value = computeQueueStats\(tasks\.value\)/)
})

test('AI Draft, Direct Render registration, Factory filters, and badges remain wired', () => {
  assert.match(workspaceSource, /\/api\/v1\/tasks\/draft-blueprint/)
  assert.match(workspaceSource, /\/api\/v1\/tasks\/submit-dsl/)
  assert.match(workspaceSource, /queueStore\.pushTaskUpdate\(/)
  assert.match(queueViewSource, /queueStore\.initTasks\(/)
  assert.match(queueViewSource, /t\.type === 'pending' \|\| t\.type === 'running' \|\| t\.type === 'failed'/)
  assert.match(queueViewSource, /t\.type === 'completed'/)
  assert.match(queueViewSource, /queueStore\.stats\.totalCompleted/)
})

const distDir = process.env.QUEUE_WORKER_DIST_DIR

test('isolated production output contains one compiled JavaScript Worker and a real main-bundle reference', {
  skip: !distDir,
}, () => {
  const assetDir = `${distDir}/assets`
  const assetNames = readdirSync(assetDir)
  const workerNames = assetNames.filter(name => /^queueWorker-.*\.js$/.test(name))
  assert.equal(workerNames.length, 1)

  const workerName = workerNames[0]
  const compiledWorker = readFileSync(`${assetDir}/${workerName}`, 'utf8')
  const mainJavaScript = assetNames
    .filter(name => name.endsWith('.js') && name !== workerName)
    .map(name => readFileSync(`${assetDir}/${name}`, 'utf8'))
    .join('\n')

  assert.ok(mainJavaScript.includes(workerName))
  assert.doesNotMatch(mainJavaScript, /queueWorker-[^"']+\.ts/)
  assert.doesNotMatch(compiledWorker, /\bexport\s+(?:type|interface)\b/)
  assert.doesNotMatch(compiledWorker, /DedicatedWorkerGlobalScope/)
  assert.doesNotMatch(compiledWorker, /from\s+["']\.\.\//)
  assert.doesNotMatch(compiledWorker, /normalizeCoverageDiagnostics\s+from/)
})

test('compiled production Worker starts in a real worker thread and processes queue messages', {
  skip: !distDir,
}, async () => {
  const assetDir = `${distDir}/assets`
  const workerName = readdirSync(assetDir).find(name => /^queueWorker-.*\.js$/.test(name))
  assert.ok(workerName)
  const compiledWorker = readFileSync(`${assetDir}/${workerName}`, 'utf8')
  const bootstrap = `
    const { parentPort } = require('node:worker_threads');
    global.self = {
      onmessage: null,
      postMessage(message) { parentPort.postMessage(message); },
    };
    parentPort.on('message', data => {
      if (typeof global.self.onmessage === 'function') global.self.onmessage({ data });
    });
    ${compiledWorker}
  `
  const worker = new NodeWorker(bootstrap, { eval: true })

  function nextMessage(predicate, timeoutMs = 2_000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        cleanup()
        reject(new Error('compiled Worker message timeout'))
      }, timeoutMs)
      const onMessage = message => {
        if (!predicate(message)) return
        cleanup()
        resolve(message)
      }
      const onError = error => {
        cleanup()
        reject(error)
      }
      function cleanup() {
        clearTimeout(timer)
        worker.off('message', onMessage)
        worker.off('error', onError)
      }
      worker.on('message', onMessage)
      worker.on('error', onError)
    })
  }

  try {
    await nextMessage(message => message?.type === 'READY')
    worker.postMessage({
      type: 'INIT_TASKS',
      revision: 1,
      payload: [{
        id: 'history-completed', type: 'completed', prompt: 'history',
        ts: '00:00:00', startTime: 1, startTs: '00:00:00', assets: [],
      }],
    })
    const historyTick = await nextMessage(message =>
      message?.type === 'TICK' && message.payload?.stats?.totalCompleted === 1)
    assert.equal(historyTick.payload.tasks.length, 1)

    worker.postMessage({
      type: 'WS_UPDATE',
      revision: 2,
      payload: { taskId: 'live-batch', status: 'pending', requestedCount: 4 },
    })
    await nextMessage(message =>
      message?.type === 'TICK' && message.payload?.stats?.totalPending === 1)

    worker.postMessage({
      type: 'WS_UPDATE',
      revision: 3,
      payload: { taskId: 'live-batch', status: 'running', requestedCount: 4 },
    })
    await nextMessage(message =>
      message?.type === 'TICK' && message.payload?.stats?.totalRunning === 1)

    worker.postMessage({
      type: 'WS_UPDATE',
      revision: 4,
      payload: { taskId: 'live-batch', status: 'completed', requestedCount: 4, succeededCount: 4 },
    })
    const completedTick = await nextMessage(message =>
      message?.type === 'TICK' && message.payload?.stats?.totalCompleted === 2)
    assert.equal(completedTick.payload.tasks.filter(task => task.id === 'live-batch').length, 1)
    assert.equal(completedTick.payload.tasks.find(task => task.id === 'live-batch').succeededCount, 4)
  } finally {
    await worker.terminate()
  }
})
