import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  mergeCoverageDiagnostics,
  normalizeCoverageDiagnostics,
} from '../src/utils/coverageDiagnostics.ts'

const DIGEST_A = 'a'.repeat(64)
const DIGEST_B = 'b'.repeat(64)

function representativePayload() {
  return {
    type: 'balanced_axis_coverage',
    version: 1,
    variant_planning_policy: 'exact_main_visual_balanced',
    requested_count: 4,
    accepted_count: 4,
    candidate_space_size: 32,
    search_budget: 32,
    examined_count: 4,
    proposal_attempted_count: 3,
    termination_reason: 'REQUEST_SATISFIED',
    preview_seeded: true,
    preview_child_index: 0,
    preview_fingerprint_digest: DIGEST_A,
    accepted_fingerprint_digests: [DIGEST_A, DIGEST_B],
    rejection_counts: {
      materialization_mismatch_count: 1,
      invalid_plan_count: 2,
      duplicate_fingerprint_reject_count: 3,
    },
    beats: [
      {
        beat_index: 0,
        beat_identity: 'hook',
        role: 'X',
        pool_size: 4,
        selected_histogram: [
          { normalized_file_hash: 'hash-a', asset_id: 11, count: 1 },
          { normalized_file_hash: 'hash-b', asset_id: 12, count: 1 },
        ],
        selected_count: 2,
        unique_used: 2,
        unused_count: 2,
        ideal_floor: 0,
        ideal_ceil: 1,
        max_min_gap: 1,
        classification: 'VARIABLE_BALANCED',
      },
      {
        beat_index: 1,
        beat_identity: 'context',
        role: 'X',
        pool_size: 1,
        selected_histogram: [
          { normalized_file_hash: 'hash-fixed', asset_id: 21, count: 4 },
        ],
        selected_count: 4,
        unique_used: 1,
        unused_count: 0,
        ideal_floor: 4,
        ideal_ceil: 4,
        max_min_gap: 0,
        classification: 'FIXED_BY_CAPACITY',
      },
      ...['build', 'reveal', 'cta'].map((beatIdentity, offset) => ({
        beat_index: offset + 2,
        beat_identity: beatIdentity,
        role: 'X',
        pool_size: 2,
        selected_histogram: [
          { normalized_file_hash: `hash-${beatIdentity}`, asset_id: 30 + offset, count: 2 },
        ],
        selected_count: 2,
        unique_used: 1,
        unused_count: 1,
        ideal_floor: 1,
        ideal_ceil: 1,
        max_min_gap: 1,
        classification: 'VARIABLE_TARGET_NOT_MET',
      })),
    ],
  }
}

test('valid V1 normalizes five Beats and returns a detached copy', () => {
  const source = representativePayload()
  const normalized = normalizeCoverageDiagnostics(source)

  assert.ok(normalized)
  assert.equal(normalized.beats.length, 5)
  assert.deepEqual(normalized, source)
  assert.notStrictEqual(normalized, source)
  assert.notStrictEqual(normalized.beats, source.beats)
  assert.notStrictEqual(normalized.beats[0].selected_histogram, source.beats[0].selected_histogram)
  assert.notStrictEqual(normalized.rejection_counts, source.rejection_counts)
  assert.notStrictEqual(
    normalized.accepted_fingerprint_digests,
    source.accepted_fingerprint_digests,
  )
})

test('old or absent diagnostics fail closed without throwing', () => {
  assert.equal(normalizeCoverageDiagnostics(undefined), undefined)
  assert.equal(normalizeCoverageDiagnostics(null), undefined)
  assert.equal(normalizeCoverageDiagnostics({}), undefined)
})

test('identity fields are independently enforced', () => {
  for (const [field, invalid] of [
    ['type', 'other'],
    ['version', 2],
    ['variant_planning_policy', 'exact_main_visual'],
  ]) {
    const payload = representativePayload()
    payload[field] = invalid
    assert.equal(normalizeCoverageDiagnostics(payload), undefined, field)
  }
})

test('unsafe structural shapes fail closed', () => {
  const mutations = [
    payload => { payload.beats[0].pool_size = -1 },
    payload => { payload.accepted_count = '4' },
    payload => { payload.beats[0].classification = 'UNKNOWN' },
    payload => { payload.accepted_fingerprint_digests[0] = 'not-a-digest' },
    payload => { payload.beats = {} },
    payload => { payload.beats[0].selected_histogram[0].count = 0 },
  ]

  for (const mutate of mutations) {
    const payload = representativePayload()
    mutate(payload)
    assert.equal(normalizeCoverageDiagnostics(payload), undefined)
  }
})

test('P=0 and B<P backend edge shapes are preserved without frontend math', () => {
  const zeroPool = representativePayload()
  zeroPool.beats[0] = {
    beat_index: 0,
    beat_identity: 'hook',
    role: 'X',
    pool_size: 0,
    selected_histogram: [],
    selected_count: 0,
    unique_used: 0,
    unused_count: 0,
    ideal_floor: null,
    ideal_ceil: null,
    max_min_gap: null,
    classification: null,
  }
  assert.deepEqual(normalizeCoverageDiagnostics(zeroPool)?.beats[0], zeroPool.beats[0])

  const fewerSelectionsThanPool = representativePayload()
  const normalized = normalizeCoverageDiagnostics(fewerSelectionsThanPool)
  assert.ok(normalized)
  assert.equal(normalized.beats[0].pool_size, 4)
  assert.equal(normalized.beats[0].selected_histogram.length, 2)
  assert.equal(normalized.beats[0].unused_count, 2)
  assert.equal(normalized.beats[0].classification, 'VARIABLE_BALANCED')
})

test('live and historical paths share one normalizer and produce equal objects', () => {
  const payload = representativePayload()
  const live = normalizeCoverageDiagnostics(payload)
  const planningSummary = { coverage_diagnostics: payload }
  const historical = normalizeCoverageDiagnostics(planningSummary.coverage_diagnostics)
  assert.deepEqual(live, historical)

  const root = fileURLToPath(new URL('../', import.meta.url))
  const worker = readFileSync(`${root}src/workers/queueWorker.ts`, 'utf8')
  const store = readFileSync(`${root}src/stores/useQueueStore.ts`, 'utf8')
  const queueView = readFileSync(`${root}src/views/QueueView.vue`, 'utf8')
  assert.match(worker, /normalizeCoverageDiagnostics\(payload\.coverageDiagnostics\)/)
  assert.match(store, /normalizeCoverageDiagnostics\(payload\.coverageDiagnostics\)/)
  assert.match(queueView, /normalizeCoverageDiagnostics\(summary\.coverage_diagnostics\)/)
})

test('historical absence preserves existing live diagnostics', () => {
  const live = normalizeCoverageDiagnostics(representativePayload())
  assert.ok(live)
  assert.strictEqual(mergeCoverageDiagnostics(live, undefined), live)
})

test('malformed historical diagnostics preserve existing live diagnostics', () => {
  const live = normalizeCoverageDiagnostics(representativePayload())
  const malformed = normalizeCoverageDiagnostics({ type: 'invalid' })
  assert.ok(live)
  assert.equal(malformed, undefined)
  assert.strictEqual(mergeCoverageDiagnostics(live, malformed), live)
})

test('valid historical diagnostics replace an existing live value', () => {
  const live = normalizeCoverageDiagnostics(representativePayload())
  const historicalPayload = representativePayload()
  historicalPayload.search_budget = 64
  const historical = normalizeCoverageDiagnostics(historicalPayload)
  assert.ok(live)
  assert.ok(historical)
  assert.strictEqual(mergeCoverageDiagnostics(live, historical), historical)
  assert.equal(mergeCoverageDiagnostics(live, historical)?.search_budget, 64)
})

test('standalone old historical task remains without diagnostics', () => {
  assert.equal(mergeCoverageDiagnostics(undefined, undefined), undefined)
})

test('historical merge snapshot retains preserved live diagnostics', () => {
  const liveCoverage = normalizeCoverageDiagnostics(representativePayload())
  assert.ok(liveCoverage)
  const liveTask = { id: 'task-1', coverageDiagnostics: liveCoverage }
  const historicalTask = { id: 'task-1', coverageDiagnostics: undefined }
  const mergedTask = {
    ...liveTask,
    ...historicalTask,
    coverageDiagnostics: mergeCoverageDiagnostics(
      liveTask.coverageDiagnostics,
      historicalTask.coverageDiagnostics,
    ),
  }
  const initTasksSnapshot = [mergedTask]
  assert.strictEqual(initTasksSnapshot[0].coverageDiagnostics, liveCoverage)
})
