import type {
  CoverageBeatDiagnosticsV1,
  CoverageClassificationV1,
  CoverageDiagnosticsV1,
} from './coverageDiagnostics'

const STATUS_LABELS: Record<CoverageClassificationV1, string> = {
  FIXED_BY_CAPACITY: '容量固定',
  VARIABLE_BALANCED: '均衡',
  VARIABLE_TARGET_NOT_MET: '未达到均衡目标',
}

const STATUS_REASONS: Record<CoverageClassificationV1, string> = {
  FIXED_BY_CAPACITY: '该 Beat 只有 1 个可用主视觉候选，重复使用由候选容量决定。',
  VARIABLE_BALANCED: '当前计划已在可用候选间尽可能均匀分配。',
  VARIABLE_TARGET_NOT_MET: '当前实际分布未达到该 Beat 的均衡覆盖目标。',
}

const TERMINATION_LABELS: Record<string, string> = {
  REQUEST_SATISFIED: '已满足请求数量',
  TRUE_SPACE_EXHAUSTED: '已检查全部候选组合',
  PLANNING_SEARCH_LIMIT_REACHED: '已达到规划搜索上限',
}

export interface CoverageTerminationPresentation {
  label: string
  explanation?: string
}

export function coverageSummary(diagnostics: CoverageDiagnosticsV1): string {
  let balanced = 0
  let fixed = 0
  let targetNotMet = 0
  let unavailable = 0

  for (const beat of diagnostics.beats) {
    if (beat.classification === 'VARIABLE_BALANCED') balanced += 1
    else if (beat.classification === 'FIXED_BY_CAPACITY') fixed += 1
    else if (beat.classification === 'VARIABLE_TARGET_NOT_MET') targetNotMet += 1
    else unavailable += 1
  }

  const parts: string[] = []
  if (targetNotMet > 0) parts.push(`${targetNotMet} 个 Beat 未达到均衡目标`)
  if (balanced > 0) parts.push(`${balanced} 个可变 Beat 均衡`)
  if (fixed > 0) parts.push(`${fixed} 个容量固定`)
  if (unavailable > 0) parts.push(`${unavailable} 个状态不可用`)

  return parts.length > 0 ? `覆盖：${parts.join(' · ')}` : '覆盖：暂无 Beat 覆盖信息'
}

export function beatDisplayName(beat: CoverageBeatDiagnosticsV1): string {
  return beat.beat_identity.trim() || `Beat ${beat.beat_index + 1}`
}

export function distributionText(beat: CoverageBeatDiagnosticsV1): string {
  const counts = beat.selected_histogram.map((entry) => entry.count)
  return counts.length > 0 ? counts.join(' / ') : '—'
}

export function coverageStatusLabel(
  classification: CoverageClassificationV1 | null,
): string {
  return classification === null ? '状态不可用' : STATUS_LABELS[classification]
}

export function coverageStatusReason(
  classification: CoverageClassificationV1 | null,
): string {
  return classification === null
    ? '当前没有可用于正常覆盖分类的候选容量信息。'
    : STATUS_REASONS[classification]
}

export function terminationPresentation(reason: string): CoverageTerminationPresentation {
  const label = TERMINATION_LABELS[reason]
  if (!label) return { label: reason }
  if (reason === 'PLANNING_SEARCH_LIMIT_REACHED') {
    return {
      label,
      explanation: '规划在搜索预算内停止；候选空间仍可能存在未检查组合。',
    }
  }
  return { label }
}

export function rejectionSummary(diagnostics: CoverageDiagnosticsV1): string | undefined {
  const counts = diagnostics.rejection_counts
  if (
    counts.materialization_mismatch_count === 0
    && counts.invalid_plan_count === 0
    && counts.duplicate_fingerprint_reject_count === 0
  ) {
    return undefined
  }

  return `规划过程中跳过：映射不匹配 ${counts.materialization_mismatch_count}`
    + ` · 无效计划 ${counts.invalid_plan_count}`
    + ` · 重复组合 ${counts.duplicate_fingerprint_reject_count}`
}

export function previewSeedSummary(diagnostics: CoverageDiagnosticsV1): string | undefined {
  return diagnostics.preview_seeded
    ? '预览种子已作为第 1 个计划纳入覆盖统计。'
    : undefined
}
