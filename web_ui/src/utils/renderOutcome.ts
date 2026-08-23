export const RENDER_WARNING_CODES = {
  insufficientCapacity: 'INSUFFICIENT_UNIQUE_CAPACITY',
  searchLimit: 'PLANNING_SEARCH_LIMIT_REACHED',
  childFailure: 'CHILD_EXECUTION_FAILED',
  historyFailure: 'HISTORY_PERSIST_FAILED',
} as const

export interface RenderOutcomeSource {
  status?: string
  type?: string
  partial?: boolean
  requestedCount?: number
  plannedCount?: number
  succeededCount?: number
  failedCount?: number
  historyPersisted?: boolean
  warningCodes?: string[]
}

export interface RenderOutcomeSummary {
  severity: 'warning' | 'error'
  headline: string
  details: string[]
  text: string
}

function count(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? Math.floor(value)
    : undefined
}

/** Map backend terminal facts to one deterministic, user-facing outcome summary. */
export function deriveRenderOutcomeSummary(
  source: RenderOutcomeSource,
): RenderOutcomeSummary | null {
  const warningCodes = Array.isArray(source.warningCodes) ? source.warningCodes : []
  const warnings = new Set(warningCodes)
  const requested = count(source.requestedCount)
  const planned = count(source.plannedCount)
  const succeeded = count(source.succeededCount)
  const failed = count(source.failedCount)

  const insufficient = warnings.has(RENDER_WARNING_CODES.insufficientCapacity)
  const searchLimited = warnings.has(RENDER_WARNING_CODES.searchLimit)
  const childFailed = warnings.has(RENDER_WARNING_CODES.childFailure)
  const historyFailed = source.historyPersisted === false
    && warnings.has(RENDER_WARNING_CODES.historyFailure)
  const hasVisibleWarning = insufficient || searchLimited || childFailed || historyFailed
  const status = source.status ?? source.type

  // New exact-success payloads and legacy payloads keep the existing success UX.
  if (!hasVisibleWarning) return null

  const zeroOutput = status === 'failed' && succeeded === 0
  let headline: string
  const details: string[] = []

  if (zeroOutput && insufficient) {
    headline = '未生成任何版本：当前素材组合无法形成可执行的不同主视觉版本。'
  } else if (zeroOutput && searchLimited) {
    headline = '未生成任何版本：本次规划达到搜索上限，未在搜索范围内找到可执行组合；可能仍存在其他有效组合。'
  } else if (
    requested !== undefined
    && planned !== undefined
    && succeeded !== undefined
    && succeeded < planned
  ) {
    headline = `已完成 ${succeeded} 个输出；规划 ${planned}/${requested} 个。`
  } else if (requested !== undefined && succeeded !== undefined) {
    headline = `已生成 ${succeeded}/${requested} 个版本。`
  } else if (status === 'failed') {
    headline = '本次未生成可用版本。'
  } else {
    headline = '视频已生成。'
  }

  if (insufficient && !zeroOutput) {
    const plannedLabel = planned === undefined ? '有限数量的' : `${planned} 个`
    details.push(`当前素材组合只能形成 ${plannedLabel}不同的主视觉版本。`)
  }
  if (searchLimited && !zeroOutput) {
    details.push('本次规划达到搜索上限，可能仍存在其他有效组合。')
  }
  if (childFailed) {
    details.push(
      failed === undefined
        ? '部分已规划版本生成失败。'
        : `另有 ${failed} 个已规划版本生成失败。`,
    )
  }
  if (historyFailed) {
    details.push('视频已生成，但历史记录保存失败。')
  }

  return {
    severity: status === 'failed' ? 'error' : 'warning',
    headline,
    details,
    text: [headline, ...details].join(' '),
  }
}
