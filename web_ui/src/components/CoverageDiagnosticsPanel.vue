<script setup lang="ts">
import { computed } from 'vue'

import type {
  CoverageClassificationV1,
  CoverageDiagnosticsV1,
} from '../utils/coverageDiagnostics'
import {
  beatDisplayName,
  coverageStatusLabel,
  coverageStatusReason,
  coverageSummary,
  distributionText,
  previewSeedSummary,
  rejectionSummary,
  terminationPresentation,
} from '../utils/coveragePresentation'

const props = defineProps<{
  diagnostics: CoverageDiagnosticsV1
}>()

const emit = defineEmits<{
  toggle: [open: boolean]
}>()

const summary = computed(() => coverageSummary(props.diagnostics))
const termination = computed(() => terminationPresentation(props.diagnostics.termination_reason))
const rejection = computed(() => rejectionSummary(props.diagnostics))
const preview = computed(() => previewSeedSummary(props.diagnostics))

function onToggle(event: Event) {
  emit('toggle', (event.currentTarget as HTMLDetailsElement).open)
}

function statusClass(classification: CoverageClassificationV1 | null): string {
  if (classification === 'VARIABLE_BALANCED') return 'coverage-status--balanced'
  if (classification === 'FIXED_BY_CAPACITY') return 'coverage-status--fixed'
  if (classification === 'VARIABLE_TARGET_NOT_MET') return 'coverage-status--attention'
  return 'coverage-status--unavailable'
}
</script>

<template>
  <details class="coverage-panel" @toggle="onToggle">
    <summary class="coverage-summary">
      <span>{{ summary }}</span>
      <span class="coverage-summary-action" aria-hidden="true">查看详情</span>
    </summary>

    <div class="coverage-content">
      <div class="coverage-table-scroll">
        <table class="coverage-table">
          <thead>
            <tr>
              <th scope="col">Beat</th>
              <th scope="col">可用候选</th>
              <th scope="col">已使用</th>
              <th scope="col">未使用</th>
              <th scope="col">分布</th>
              <th scope="col">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="beat in diagnostics.beats" :key="`${beat.beat_index}:${beat.beat_identity}`">
              <th scope="row">
                <span class="coverage-beat-name">{{ beatDisplayName(beat) }}</span>
              </th>
              <td>{{ beat.pool_size }}</td>
              <td>{{ beat.unique_used }}</td>
              <td>{{ beat.unused_count }}</td>
              <td class="coverage-distribution">{{ distributionText(beat) }}</td>
              <td class="coverage-status-cell">
                <span :class="['coverage-status', statusClass(beat.classification)]">
                  {{ coverageStatusLabel(beat.classification) }}
                </span>
                <small>{{ coverageStatusReason(beat.classification) }}</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <section class="coverage-planning-context" aria-label="覆盖规划上下文">
        <div class="coverage-context-grid">
          <span><b>计划接受</b>{{ diagnostics.accepted_count }} / {{ diagnostics.requested_count }}</span>
          <span><b>已检查组合</b>{{ diagnostics.examined_count }} / {{ diagnostics.candidate_space_size }}</span>
          <span><b>搜索预算</b>{{ diagnostics.search_budget }}</span>
          <span><b>规划状态</b>{{ termination.label }}</span>
        </div>
        <p v-if="termination.explanation" class="coverage-context-note">
          {{ termination.explanation }}
        </p>
        <p v-if="rejection" class="coverage-context-note">{{ rejection }}</p>
        <p v-if="preview" class="coverage-context-note">{{ preview }}</p>
      </section>
    </div>
  </details>
</template>

<style scoped>
.coverage-panel {
  flex-shrink: 0;
  min-width: 0;
  margin: 0 0 6px;
  border: 1px solid rgba(56, 189, 248, 0.16);
  border-radius: 7px;
  background: rgba(15, 23, 42, 0.5);
  color: #cbd5e1;
}

.coverage-summary {
  min-height: 28px;
  box-sizing: border-box;
  padding: 5px 9px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  color: #bae6fd;
  font-size: 0.7rem;
  font-weight: 650;
  line-height: 1.35;
}

.coverage-summary:focus-visible {
  outline: 2px solid #38bdf8;
  outline-offset: 2px;
}

.coverage-summary-action {
  flex-shrink: 0;
  color: #64748b;
  font-size: 0.62rem;
  font-weight: 500;
}

.coverage-panel[open] .coverage-summary-action {
  font-size: 0;
}

.coverage-panel[open] .coverage-summary-action::after {
  content: '收起';
  font-size: 0.62rem;
}

.coverage-content {
  padding: 0 9px 9px;
  border-top: 1px solid rgba(148, 163, 184, 0.1);
}

.coverage-table-scroll {
  max-width: 100%;
  overflow-x: auto;
  padding-top: 7px;
}

.coverage-table {
  width: 100%;
  min-width: 660px;
  border-collapse: collapse;
  color: #94a3b8;
  font-size: 0.68rem;
  font-variant-numeric: tabular-nums;
}

.coverage-table th,
.coverage-table td {
  padding: 6px 7px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  text-align: left;
  vertical-align: top;
}

.coverage-table thead th {
  color: #64748b;
  font-size: 0.62rem;
  font-weight: 650;
  white-space: nowrap;
}

.coverage-table tbody th {
  color: #cbd5e1;
  font-weight: 650;
}

.coverage-beat-name {
  display: block;
}

.coverage-distribution {
  white-space: nowrap;
}

.coverage-status-cell {
  min-width: 185px;
}

.coverage-status {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border: 1px solid transparent;
  border-radius: 10px;
  font-size: 0.62rem;
  font-weight: 700;
  white-space: nowrap;
}

.coverage-status-cell small {
  display: block;
  margin-top: 3px;
  color: #64748b;
  font-size: 0.58rem;
  font-weight: 400;
  line-height: 1.35;
}

.coverage-status--balanced {
  border-color: rgba(74, 222, 128, 0.25);
  background: rgba(74, 222, 128, 0.09);
  color: #86efac;
}

.coverage-status--fixed {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(148, 163, 184, 0.08);
  color: #cbd5e1;
}

.coverage-status--attention {
  border-color: rgba(245, 158, 11, 0.28);
  background: rgba(245, 158, 11, 0.09);
  color: #fcd34d;
}

.coverage-status--unavailable {
  border-color: rgba(100, 116, 139, 0.2);
  background: rgba(100, 116, 139, 0.07);
  color: #94a3b8;
}

.coverage-planning-context {
  padding-top: 8px;
}

.coverage-context-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 5px 12px;
  color: #94a3b8;
  font-size: 0.65rem;
}

.coverage-context-grid span {
  display: flex;
  gap: 5px;
  min-width: 0;
}

.coverage-context-grid b {
  color: #64748b;
  font-weight: 600;
  white-space: nowrap;
}

.coverage-context-note {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 0.62rem;
  line-height: 1.4;
}

@media (max-width: 760px) {
  .coverage-context-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
