export type CoverageClassificationV1 =
  | 'FIXED_BY_CAPACITY'
  | 'VARIABLE_BALANCED'
  | 'VARIABLE_TARGET_NOT_MET'

export interface CoverageHistogramEntryV1 {
  normalized_file_hash: string
  asset_id: number
  count: number
}

export interface CoverageBeatDiagnosticsV1 {
  beat_index: number
  beat_identity: string
  role: string
  pool_size: number
  selected_histogram: CoverageHistogramEntryV1[]
  selected_count: number
  unique_used: number
  unused_count: number
  ideal_floor: number | null
  ideal_ceil: number | null
  max_min_gap: number | null
  classification: CoverageClassificationV1 | null
}

export interface CoverageRejectionCountsV1 {
  materialization_mismatch_count: number
  invalid_plan_count: number
  duplicate_fingerprint_reject_count: number
}

export interface CoverageDiagnosticsV1 {
  type: 'balanced_axis_coverage'
  version: 1
  variant_planning_policy: 'exact_main_visual_balanced'
  requested_count: number
  accepted_count: number
  candidate_space_size: number
  search_budget: number
  examined_count: number
  proposal_attempted_count: number
  termination_reason: string
  preview_seeded: boolean
  preview_child_index: number | null
  preview_fingerprint_digest: string | null
  accepted_fingerprint_digests: string[]
  rejection_counts: CoverageRejectionCountsV1
  beats: CoverageBeatDiagnosticsV1[]
}

type UnknownRecord = Record<string, unknown>

const CLASSIFICATIONS = new Set<CoverageClassificationV1>([
  'FIXED_BY_CAPACITY',
  'VARIABLE_BALANCED',
  'VARIABLE_TARGET_NOT_MET',
])

const SHA256_HEX = /^[0-9a-f]{64}$/

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value)
}

function isNonNegativeInteger(value: unknown): value is number {
  return isInteger(value) && value >= 0
}

function isNullableNonNegativeInteger(value: unknown): value is number | null {
  return value === null || isNonNegativeInteger(value)
}

function isDigest(value: unknown): value is string {
  return typeof value === 'string' && SHA256_HEX.test(value)
}

function normalizeHistogramEntry(value: unknown): CoverageHistogramEntryV1 | undefined {
  if (!isRecord(value)) return undefined
  if (
    typeof value.normalized_file_hash !== 'string'
    || value.normalized_file_hash.trim().length === 0
    || !isInteger(value.asset_id)
    || !isInteger(value.count)
    || value.count <= 0
  ) {
    return undefined
  }
  return {
    normalized_file_hash: value.normalized_file_hash,
    asset_id: value.asset_id,
    count: value.count,
  }
}

function normalizeBeat(value: unknown): CoverageBeatDiagnosticsV1 | undefined {
  if (!isRecord(value) || !Array.isArray(value.selected_histogram)) return undefined
  if (
    !isNonNegativeInteger(value.beat_index)
    || typeof value.beat_identity !== 'string'
    || typeof value.role !== 'string'
    || !isNonNegativeInteger(value.pool_size)
    || !isNonNegativeInteger(value.selected_count)
    || !isNonNegativeInteger(value.unique_used)
    || !isNonNegativeInteger(value.unused_count)
    || !isNullableNonNegativeInteger(value.ideal_floor)
    || !isNullableNonNegativeInteger(value.ideal_ceil)
    || !isNullableNonNegativeInteger(value.max_min_gap)
    || !(
      value.classification === null
      || (
        typeof value.classification === 'string'
        && CLASSIFICATIONS.has(value.classification as CoverageClassificationV1)
      )
    )
  ) {
    return undefined
  }

  const selectedHistogram: CoverageHistogramEntryV1[] = []
  for (const entry of value.selected_histogram) {
    const normalized = normalizeHistogramEntry(entry)
    if (!normalized) return undefined
    selectedHistogram.push(normalized)
  }

  return {
    beat_index: value.beat_index,
    beat_identity: value.beat_identity,
    role: value.role,
    pool_size: value.pool_size,
    selected_histogram: selectedHistogram,
    selected_count: value.selected_count,
    unique_used: value.unique_used,
    unused_count: value.unused_count,
    ideal_floor: value.ideal_floor,
    ideal_ceil: value.ideal_ceil,
    max_min_gap: value.max_min_gap,
    classification: value.classification as CoverageClassificationV1 | null,
  }
}

export function normalizeCoverageDiagnostics(
  value: unknown,
): CoverageDiagnosticsV1 | undefined {
  if (!isRecord(value)) return undefined
  if (
    value.type !== 'balanced_axis_coverage'
    || value.version !== 1
    || value.variant_planning_policy !== 'exact_main_visual_balanced'
    || !isNonNegativeInteger(value.requested_count)
    || !isNonNegativeInteger(value.accepted_count)
    || !isNonNegativeInteger(value.candidate_space_size)
    || !isNonNegativeInteger(value.search_budget)
    || !isNonNegativeInteger(value.examined_count)
    || !isNonNegativeInteger(value.proposal_attempted_count)
    || typeof value.termination_reason !== 'string'
    || typeof value.preview_seeded !== 'boolean'
    || !(value.preview_child_index === null || isInteger(value.preview_child_index))
    || !(value.preview_fingerprint_digest === null || isDigest(value.preview_fingerprint_digest))
    || !Array.isArray(value.accepted_fingerprint_digests)
    || !value.accepted_fingerprint_digests.every(isDigest)
    || !isRecord(value.rejection_counts)
    || !isNonNegativeInteger(value.rejection_counts.materialization_mismatch_count)
    || !isNonNegativeInteger(value.rejection_counts.invalid_plan_count)
    || !isNonNegativeInteger(value.rejection_counts.duplicate_fingerprint_reject_count)
    || !Array.isArray(value.beats)
  ) {
    return undefined
  }

  const beats: CoverageBeatDiagnosticsV1[] = []
  for (const beat of value.beats) {
    const normalized = normalizeBeat(beat)
    if (!normalized) return undefined
    beats.push(normalized)
  }

  return {
    type: 'balanced_axis_coverage',
    version: 1,
    variant_planning_policy: 'exact_main_visual_balanced',
    requested_count: value.requested_count,
    accepted_count: value.accepted_count,
    candidate_space_size: value.candidate_space_size,
    search_budget: value.search_budget,
    examined_count: value.examined_count,
    proposal_attempted_count: value.proposal_attempted_count,
    termination_reason: value.termination_reason,
    preview_seeded: value.preview_seeded,
    preview_child_index: value.preview_child_index,
    preview_fingerprint_digest: value.preview_fingerprint_digest,
    accepted_fingerprint_digests: [...value.accepted_fingerprint_digests],
    rejection_counts: {
      materialization_mismatch_count: value.rejection_counts.materialization_mismatch_count,
      invalid_plan_count: value.rejection_counts.invalid_plan_count,
      duplicate_fingerprint_reject_count: value.rejection_counts.duplicate_fingerprint_reject_count,
    },
    beats,
  }
}

export function mergeCoverageDiagnostics(
  current: CoverageDiagnosticsV1 | undefined,
  incoming: CoverageDiagnosticsV1 | undefined,
): CoverageDiagnosticsV1 | undefined {
  return incoming ?? current
}
