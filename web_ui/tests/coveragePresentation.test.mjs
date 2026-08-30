import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  coverageStatusLabel,
  coverageStatusReason,
  coverageSummary,
  distributionText,
  previewSeedSummary,
  rejectionSummary,
  terminationPresentation,
} from '../src/utils/coveragePresentation.ts'

function beat(classification, counts = [1], unusedCount = 0) {
  return {
    beat_index: 0,
    beat_identity: 'hook',
    role: 'X',
    pool_size: counts.length + unusedCount,
    selected_histogram: counts.map((count, index) => ({
      normalized_file_hash: `hash-${index}`,
      asset_id: index + 1,
      count,
    })),
    selected_count: counts.reduce((sum, count) => sum + count, 0),
    unique_used: counts.length,
    unused_count: unusedCount,
    ideal_floor: null,
    ideal_ceil: null,
    max_min_gap: null,
    classification,
  }
}

function diagnostics(beats = []) {
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
    preview_seeded: false,
    preview_child_index: null,
    preview_fingerprint_digest: null,
    accepted_fingerprint_digests: [],
    rejection_counts: {
      materialization_mismatch_count: 0,
      invalid_plan_count: 0,
      duplicate_fingerprint_reject_count: 0,
    },
    beats,
  }
}

test('summary counts backend classifications without reclassifying coverage', () => {
  const healthy = diagnostics([
    ...Array.from({ length: 4 }, () => beat('VARIABLE_BALANCED')),
    beat('FIXED_BY_CAPACITY'),
  ])
  assert.equal(coverageSummary(healthy), '覆盖：4 个可变 Beat 均衡 · 1 个容量固定')

  const attention = diagnostics([
    beat('VARIABLE_TARGET_NOT_MET'),
    ...Array.from({ length: 3 }, () => beat('VARIABLE_BALANCED')),
    beat('FIXED_BY_CAPACITY'),
  ])
  assert.equal(
    coverageSummary(attention),
    '覆盖：1 个 Beat 未达到均衡目标 · 3 个可变 Beat 均衡 · 1 个容量固定',
  )

  assert.equal(
    coverageSummary(diagnostics([beat('FIXED_BY_CAPACITY'), beat('FIXED_BY_CAPACITY')])),
    '覆盖：2 个容量固定',
  )
  assert.equal(
    coverageSummary(diagnostics([beat('VARIABLE_BALANCED'), beat(null)])),
    '覆盖：1 个可变 Beat 均衡 · 1 个状态不可用',
  )
  assert.equal(coverageSummary(diagnostics()), '覆盖：暂无 Beat 覆盖信息')
})

test('distribution preserves selected histogram order and does not invent zeroes', () => {
  assert.equal(distributionText(beat('VARIABLE_BALANCED', [1, 1, 1, 1])), '1 / 1 / 1 / 1')
  assert.equal(distributionText(beat('VARIABLE_BALANCED', [1, 1], 2)), '1 / 1')
  assert.equal(distributionText(beat(null, [], 2)), '—')
})

test('status labels and reasons map only backend classifications', () => {
  const cases = [
    ['FIXED_BY_CAPACITY', '容量固定', '该 Beat 只有 1 个可用主视觉候选，重复使用由候选容量决定。'],
    ['VARIABLE_BALANCED', '均衡', '当前计划已在可用候选间尽可能均匀分配。'],
    ['VARIABLE_TARGET_NOT_MET', '未达到均衡目标', '当前实际分布未达到该 Beat 的均衡覆盖目标。'],
    [null, '状态不可用', '当前没有可用于正常覆盖分类的候选容量信息。'],
  ]
  for (const [classification, label, reason] of cases) {
    assert.equal(coverageStatusLabel(classification), label)
    assert.equal(coverageStatusReason(classification), reason)
  }
})

test('termination presentation maps known reasons and safely presents unknown values', () => {
  assert.deepEqual(terminationPresentation('REQUEST_SATISFIED'), { label: '已满足请求数量' })
  assert.deepEqual(terminationPresentation('TRUE_SPACE_EXHAUSTED'), { label: '已检查全部候选组合' })
  assert.deepEqual(terminationPresentation('PLANNING_SEARCH_LIMIT_REACHED'), {
    label: '已达到规划搜索上限',
    explanation: '规划在搜索预算内停止；候选空间仍可能存在未检查组合。',
  })
  assert.deepEqual(terminationPresentation('FUTURE_REASON'), { label: 'FUTURE_REASON' })
})

test('rejection text is quiet for zeroes and task-level for nonzero counts', () => {
  assert.equal(rejectionSummary(diagnostics()), undefined)
  const value = diagnostics()
  value.rejection_counts = {
    materialization_mismatch_count: 1,
    invalid_plan_count: 0,
    duplicate_fingerprint_reject_count: 2,
  }
  assert.equal(rejectionSummary(value), '规划过程中跳过：映射不匹配 1 · 无效计划 0 · 重复组合 2')
})

test('preview provenance appears only for a seeded preview and never exposes its digest', () => {
  const value = diagnostics()
  assert.equal(previewSeedSummary(value), undefined)
  value.preview_seeded = true
  value.preview_fingerprint_digest = 'a'.repeat(64)
  const text = previewSeedSummary(value)
  assert.equal(text, '预览种子已作为第 1 个计划纳入覆盖统计。')
  assert.equal(text.includes(value.preview_fingerprint_digest), false)
})

test('QueueView integrates the panel without changing the historical mode badge mapping', () => {
  const queueViewPath = fileURLToPath(new URL('../src/views/QueueView.vue', import.meta.url))
  const source = readFileSync(queueViewPath, 'utf8')
  assert.match(source, /import CoverageDiagnosticsPanel from ['"]\.\.\/components\/CoverageDiagnosticsPanel\.vue['"]/)
  assert.equal(
    (source.match(/<CoverageDiagnosticsPanel\s+v-if="item\.coverageDiagnostics"/g) ?? []).length,
    2,
    'completed and failed-terminal list items both render from diagnostics availability',
  )
  assert.doesNotMatch(source, /v-if="item\.type === 'completed'"[^>]*>\s*<CoverageDiagnosticsPanel/)
  assert.match(source, /if \(mode === 'director'\) return 'AI起草模式'/)
  assert.match(source, /return '手工战术板模式'/)
})

test('panel source uses disclosure and table semantics without rendering internal identities', () => {
  const panelPath = fileURLToPath(new URL('../src/components/CoverageDiagnosticsPanel.vue', import.meta.url))
  const source = readFileSync(panelPath, 'utf8')
  assert.match(source, /<details/)
  assert.match(source, /<summary/)
  assert.match(source, /<table/)
  for (const internalField of [
    'normalized_file_hash',
    'accepted_fingerprint_digests',
    'preview_fingerprint_digest',
    'asset_id',
  ]) {
    assert.equal(source.includes(internalField), false)
  }
})
