import assert from 'node:assert/strict'
import test from 'node:test'

import { deriveRenderOutcomeSummary } from '../src/utils/renderOutcome.ts'

test('UX1 exact success keeps normal success UX', () => {
  assert.equal(deriveRenderOutcomeSummary({
    status: 'completed', partial: false,
    requestedCount: 4, plannedCount: 4, succeededCount: 4, failedCount: 0,
    historyPersisted: true, warningCodes: [],
  }), null)
})

test('UX2 true capacity warning states 2 of 4 and proven capacity', () => {
  const result = deriveRenderOutcomeSummary({
    status: 'completed', partial: true,
    requestedCount: 4, plannedCount: 2, succeededCount: 2, failedCount: 0,
    historyPersisted: true, warningCodes: ['INSUFFICIENT_UNIQUE_CAPACITY'],
  })
  assert.match(result.text, /2\/4/)
  assert.match(result.text, /只能形成 2 个不同的主视觉版本/)
})

test('UX3 search limit states 7 of 20 without claiming exhaustion', () => {
  const result = deriveRenderOutcomeSummary({
    status: 'completed', partial: true,
    requestedCount: 20, plannedCount: 7, succeededCount: 7, failedCount: 0,
    historyPersisted: true, warningCodes: ['PLANNING_SEARCH_LIMIT_REACHED'],
  })
  assert.match(result.text, /7\/20/)
  assert.match(result.text, /达到搜索上限/)
  assert.match(result.text, /可能仍存在其他有效组合/)
  assert.doesNotMatch(result.text, /只有 7 个|素材不足/)
})

test('UX4 planning and child failures both remain visible', () => {
  const result = deriveRenderOutcomeSummary({
    status: 'completed', partial: true,
    requestedCount: 4, plannedCount: 3, succeededCount: 2, failedCount: 1,
    historyPersisted: true,
    warningCodes: ['INSUFFICIENT_UNIQUE_CAPACITY', 'CHILD_EXECUTION_FAILED'],
  })
  assert.match(result.text, /已完成 2 个输出；规划 3\/4 个/)
  assert.match(result.text, /只能形成 3 个不同的主视觉版本/)
  assert.match(result.text, /1 个已规划版本生成失败/)
})

test('UX5 history failure preserves render success', () => {
  const result = deriveRenderOutcomeSummary({
    status: 'completed', partial: false,
    requestedCount: 4, plannedCount: 4, succeededCount: 4, failedCount: 0,
    historyPersisted: false, warningCodes: ['HISTORY_PERSIST_FAILED'],
  })
  assert.match(result.text, /已生成 4\/4 个版本/)
  assert.match(result.text, /视频已生成，但历史记录保存失败/)
  assert.doesNotMatch(result.text, /视频生成失败/)
})

test('UX6 zero-plan true exhaustion has capacity wording', () => {
  const result = deriveRenderOutcomeSummary({
    type: 'failed', partial: false,
    requestedCount: 4, plannedCount: 0, succeededCount: 0, failedCount: 0,
    historyPersisted: false, warningCodes: ['INSUFFICIENT_UNIQUE_CAPACITY'],
  })
  assert.match(result.text, /未生成任何版本/)
  assert.match(result.text, /无法形成可执行的不同主视觉版本/)
})

test('UX7 zero-plan search limit does not claim true exhaustion', () => {
  const result = deriveRenderOutcomeSummary({
    type: 'failed', partial: false,
    requestedCount: 4, plannedCount: 0, succeededCount: 0, failedCount: 0,
    historyPersisted: false, warningCodes: ['PLANNING_SEARCH_LIMIT_REACHED'],
  })
  assert.match(result.text, /达到搜索上限/)
  assert.match(result.text, /可能仍存在其他有效组合/)
  assert.doesNotMatch(result.text, /素材组合无法形成|素材不足/)
})

test('UX8 legacy completed payload keeps existing behavior', () => {
  assert.equal(deriveRenderOutcomeSummary({ status: 'completed' }), null)
})
