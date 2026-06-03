<script setup lang="ts">
/**
 * QueueView.vue — Phase 7.1 双轨隔离重构版
 *
 * Tab 1 (processing): 轰鸣流水线 — 极简监控条，DOM 超轻量，并发 20+ 无压力
 * Tab 2 (completed):  战果阅兵场 — Phase 7 完整三行式高密度卡片
 *
 * 性能核心：
 *   - v-if / v-else 物理隔离两个 Tab 的 DOM 树，切换时彻底销毁对方节点
 *   - 流水线 Tab 零 <video>/<img> 渲染，每条目仅约 8 个 DOM 节点
 */

import { onMounted, onUnmounted, computed, ref, reactive } from 'vue'
import { useQueueStore }  from '../stores/useQueueStore'
import type { QueueTask } from '../stores/useQueueStore'
import { useAppStore }    from '../stores/appStore'
import MasterPreviewModal from '../components/MasterPreviewModal.vue'
import CoverPreviewCard   from '../components/matrix/CoverPreviewCard.vue'

const queueStore = useQueueStore()
const appStore   = useAppStore()

// ── 今日态水合（解决刷新丢失已完成任务）─────────────────────────────────────
async function fetchTodayTasks(): Promise<void> {
  try {
    const userId = appStore.loggedInUser || 'default'
    const resp = await fetch(`${appStore.API_BASE}/api/v1/tasks/today`, {
      headers: { 'X-Local-User': userId },
    })
    if (!resp.ok) return

    const records: any[] = await resp.json()

    const todayCompleted: QueueTask[] = records.map(r => {
      const createdAt = new Date(r.created_at)
      const ts = createdAt.toLocaleTimeString('zh', {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      })
      return {
        id:        r.task_id,
        type:      'completed' as const,
        prompt:    r.prompt || '',
        ts,
        startTime: createdAt.getTime(),
        startTs:   ts,
        endTs:     ts,
        duration:  r.duration != null ? `${Number(r.duration).toFixed(1)}s` : '',
        assets: (r.output_assets || []).map((asset: any) => ({
          file_path:  asset.path       || '',
          file_hash:  asset.hash       || '',
          cover_path: asset.cover_path || '',
          status:     asset.status     || 'PENDING',
        })),
      }
    })

    // 仅追加本地尚未记录的任务，不覆盖 WS 实时推送的任务
    const existingIds = new Set(queueStore.tasks.map(t => t.id))
    const newTasks    = todayCompleted.filter(t => !existingIds.has(t.id))
    if (newTasks.length > 0) {
      queueStore.initTasks([...queueStore.tasks, ...newTasks])
    }
  } catch (err) {
    console.warn('[QueueView] fetchTodayTasks 失败（已忽略）:', err)
  }
}

// ── 生命周期 ─────────────────────────────────────────────────────────────────
onMounted(() => {
  queueStore.initWorker()
  queueStore.connectEventBus(appStore.loggedInUser || 'default')
  fetchTodayTasks()
})
onUnmounted(() => {
  queueStore.dispose()
})

// ── Tab 视口状态 ──────────────────────────────────────────────────────────────
const activeTab = ref<'processing' | 'completed'>('processing')

// ── 双轨计算流 ────────────────────────────────────────────────────────────────
const processingTasks = computed<QueueTask[]>(() =>
  queueStore.tasks.filter(t => t.type === 'pending' || t.type === 'running' || t.type === 'failed')
)
const completedTasks = computed<QueueTask[]>(() =>
  queueStore.tasks.filter(t => t.type === 'completed')
)

// ── Tab 气泡计数 ──────────────────────────────────────────────────────────────
const processingBadge = computed(() => queueStore.stats.totalPending + queueStore.stats.totalRunning)

// ── 统计 ─────────────────────────────────────────────────────────────────────
const etaDisplay = computed<string>(() => {
  const s = queueStore.stats.estimatedETA_seconds
  if (s <= 0) return '--'
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0 ? `${m}分 ${String(r).padStart(2, '0')}秒` : `${r} 秒`
})

const progressPct = computed<number>(() => {
  const { totalCompleted, totalPending, totalRunning, totalFailed } = queueStore.stats
  const total = totalCompleted + totalPending + totalRunning + totalFailed
  return total === 0 ? 0 : Math.round((totalCompleted / total) * 100)
})

// ── 工具 ─────────────────────────────────────────────────────────────────────
function statusLabel(type: QueueTask['type']): string {
  return { pending: '排队中', running: '生成中', completed: '已完成', failed: '失败' }[type] ?? type
}
function statusClass(type: QueueTask['type']): string {
  return { pending: 'badge-pending', running: 'badge-running', completed: 'badge-completed', failed: 'badge-failed' }[type] ?? ''
}

// ── Row-2 展开状态（completed tab 专用）──────────────────────────────────────
const expandedPrompts = reactive<Set<string>>(new Set())
function togglePrompt(id: string) {
  if (expandedPrompts.has(id)) expandedPrompts.delete(id)
  else expandedPrompts.add(id)
}

// ── Row-3 轮播状态（completed tab 专用）─────────────────────────────────────
interface CarouselState { page: number; activeIdx: number }
const carouselMap = reactive<Map<string, CarouselState>>(new Map())

function getCarousel(taskId: string): CarouselState {
  if (!carouselMap.has(taskId)) carouselMap.set(taskId, { page: 0, activeIdx: 1 })
  return carouselMap.get(taskId)!
}

const PAGE_SIZE = 3

function carouselPrev(taskId: string, total: number, e: Event) {
  e.stopPropagation()
  const c = getCarousel(taskId)
  if (c.page > 0) {
    c.page--
    c.activeIdx = c.page * PAGE_SIZE + 1
  }
}

function carouselNext(taskId: string, total: number, e: Event) {
  e.stopPropagation()
  const c = getCarousel(taskId)
  const maxPage = Math.ceil(total / PAGE_SIZE) - 1
  if (c.page < maxPage) {
    c.page++
    c.activeIdx = Math.min(c.page * PAGE_SIZE + 1, total - 1)
  }
}

function getVisibleAssets(task: QueueTask) {
  const c = getCarousel(task.id)
  const start = c.page * PAGE_SIZE
  return (task.assets ?? []).slice(start, start + PAGE_SIZE)
}

function getGlobalIdx(task: QueueTask, localIdx: number): number {
  const c = getCarousel(task.id)
  return c.page * PAGE_SIZE + localIdx
}

// ── MasterPreviewModal 控制 ──────────────────────────────────────────────────
const modalOpen     = ref(false)
const modalTask     = ref<QueueTask | null>(null)
const modalAssetIdx = ref(0)

function openModal(task: QueueTask, globalIdx: number) {
  const c = getCarousel(task.id)
  c.activeIdx     = globalIdx
  modalTask.value     = task
  modalAssetIdx.value = globalIdx
  modalOpen.value     = true
}

/** CoverPreviewCard @preview 事件的适配器（localIdx → globalIdx → openModal） */
function handleCardPreview(task: QueueTask, localIdx: number) {
  openModal(task, getGlobalIdx(task, localIdx))
}

function onModalClose() {
  modalOpen.value = false
}

// ── 向上透传"微调"事件 ────────────────────────────────────────────────────────
const emit = defineEmits<{ (e: 'open-detail', hash: string): void }>()

function onOpenDetail(hash: string) {
  modalOpen.value = false
  emit('open-detail', hash)
}

// ── 压力测试（调试时取消注释）────────────────────────────────────────────────
/*
const isStressTesting  = ref(false)
const isRealWsFlooding = ref(false)

const runStressTest = () => {
  if (isStressTesting.value) return
  isStressTesting.value = true

  const mockTasks: QueueTask[] = Array.from({ length: 500 }).map((_, i) => {
    const now = Date.now() - Math.random() * 10000
    const ts  = new Date(now).toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    return { id: `mock_test_task_${i}`, type: 'pending', prompt: `【极限压测】第 ${i} 号并发任务`, ts, startTime: now, startTs: ts, assets: [] }
  })
  queueStore.initTasks(mockTasks)

  const floodInterval = setInterval(() => {
    const pending = queueStore.tasks.filter(t => t.type === 'pending')
    const running = queueStore.tasks.filter(t => t.type === 'running')
    if (pending.length === 0 && running.length === 0) {
      clearInterval(floodInterval)
      isStressTesting.value = false
      return
    }
    if (pending.length > 0 && Math.random() > 0.4) {
      const idx = Math.floor(Math.random() * pending.length)
      queueStore.pushTaskUpdate({ taskId: pending[idx].id, status: 'running', startTime: Date.now() })
    }
    if (running.length > 0 && Math.random() > 0.6) {
      const idx = Math.floor(Math.random() * running.length)
      queueStore.pushTaskUpdate({
        taskId: running[idx].id, status: 'completed',
        assets: [
          { file_path: `/mock/output_${running[idx].id}_a.mp4`, file_hash: `hash_${Math.random().toString(16).slice(2, 10)}` },
          { file_path: `/mock/output_${running[idx].id}_b.mp4`, file_hash: `hash_${Math.random().toString(16).slice(2, 10)}` },
          { file_path: `/mock/output_${running[idx].id}_c.mp4`, file_hash: `hash_${Math.random().toString(16).slice(2, 10)}` },
          { file_path: `/mock/output_${running[idx].id}_d.mp4`, file_hash: `hash_${Math.random().toString(16).slice(2, 10)}` },
          { file_path: `/mock/output_${running[idx].id}_e.mp4`, file_hash: `hash_${Math.random().toString(16).slice(2, 10)}` },
        ]
      })
    }
  }, 50)
}

const triggerRealWsFlood = async () => {
  if (isRealWsFlooding.value) return
  isRealWsFlooding.value = true
  try {
    const userId = appStore.loggedInUser || 'default'
    const res = await fetch('http://127.0.0.1:8000/api/v1/test/flood-ws', {
      method: 'POST',
      headers: { 'X-Local-User': userId },
    })
    if (!res.ok) console.error(`[WS-REAL-TEST] HTTP ${res.status}`)
  } catch (err) {
    console.error('[WS-REAL-TEST] 请求失败：', err)
  } finally {
    isRealWsFlooding.value = false
  }
}
*/
</script>

<template>
  <div class="queue-layout">

    <!-- ══ StatsHeader ════════════════════════════════════════════════════════ -->
    <header class="stats-header">
      <div class="stats-row">
        <div class="stat-item">
          <span class="stat-label">⏳ 预计剩余</span>
          <span class="stat-value stat-eta">{{ etaDisplay }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">📋 排队</span>
          <span class="stat-value">{{ queueStore.stats.totalPending }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">⚡ 生成中</span>
          <span class="stat-value stat-running">{{ queueStore.stats.totalRunning }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">✓ 完成</span>
          <span class="stat-value stat-done">{{ queueStore.stats.totalCompleted }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">✕ 失败</span>
          <span class="stat-value stat-fail">{{ queueStore.stats.totalFailed }}</span>
        </div>
      </div>

      <!-- 调试压测按钮（需要时取消注释，并恢复 script 中对应逻辑）
      <button @click="runStressTest" :disabled="isStressTesting" class="debug-btn debug-btn--red">
        {{ isStressTesting ? '🌋 压测中...' : '🚀 注入 500 任务' }}
      </button>
      <button @click="triggerRealWsFlood" :disabled="isRealWsFlooding" class="debug-btn debug-btn--blue">
        {{ isRealWsFlooding ? '🌊 WS 压测中...' : '🌊 WS 真实压测' }}
      </button>
      -->

      <div class="progress-track">
        <div
          class="progress-fill"
          :style="{ width: progressPct + '%' }"
          role="progressbar"
          :aria-valuenow="progressPct"
          aria-valuemin="0"
          aria-valuemax="100"
        />
      </div>
    </header>

    <!-- ══ Tab 导航栏 ══════════════════════════════════════════════════════════ -->
    <nav class="tab-nav">
      <button
        :class="['tab-btn', { 'tab-btn--active': activeTab === 'processing' }]"
        @click="activeTab = 'processing'"
      >
        <span class="tab-icon">⏳</span>
        <span class="tab-label">轰鸣流水线</span>
        <Transition name="badge-pop">
          <span v-if="processingBadge > 0" class="tab-badge tab-badge--hot">{{ processingBadge }}</span>
        </Transition>
      </button>

      <button
        :class="['tab-btn', { 'tab-btn--active': activeTab === 'completed' }]"
        @click="activeTab = 'completed'"
      >
        <span class="tab-icon">🏆</span>
        <span class="tab-label">战果阅兵场</span>
        <Transition name="badge-pop">
          <span v-if="queueStore.stats.totalCompleted > 0" class="tab-badge tab-badge--gold">
            {{ queueStore.stats.totalCompleted }}
          </span>
        </Transition>
      </button>
    </nav>

    <!-- ══ 轰鸣流水线（v-if — 切换时物理销毁对方 DOM 树）════════════════════ -->
    <section v-if="activeTab === 'processing'" class="task-scroll-area">

      <div v-if="processingTasks.length === 0" class="empty-state">
        <div class="empty-icon">⚡</div>
        <p>流水线空闲，前往工作台创建矩阵任务</p>
      </div>

      <!-- item-size = strip(52px) + margin-bottom(8px) = 60 -->
      <RecycleScroller
        v-else
        class="task-scroller"
        :items="processingTasks"
        :item-size="60"
        :prerender="14"
        key-field="id"
        v-slot="{ item }"
      >
        <!-- 极简监控条：零 <video>/<img>，~8 DOM 节点 -->
        <div :class="['monitor-strip', `monitor-strip--${item.type}`]">

          <div class="ms-left">
            <span :class="['ms-pulse', { 'ms-pulse--running': item.type === 'running' }]" />
            <span class="ms-id">#{{ item.id.slice(-8) }}</span>
            <span :class="['ms-badge', statusClass(item.type)]">{{ statusLabel(item.type) }}</span>
          </div>

          <p class="ms-prompt">{{ item.prompt || '（无描述）' }}</p>

          <div class="ms-right">
            <template v-if="item.type === 'running'">
              <div class="ms-bar" aria-hidden="true">
                <div class="ms-bar-fill" />
              </div>
              <svg class="ms-spin" fill="none" viewBox="0 0 24 24" width="14" height="14">
                <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" opacity="0.25"/>
                <path fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" opacity="0.8"/>
              </svg>
            </template>
            <span v-else-if="item.type === 'failed'" class="ms-fail-tag">✕ 错误</span>
            <span v-else class="ms-ts">{{ item.startTs || '--' }}</span>
          </div>

        </div>
      </RecycleScroller>

    </section>

    <!-- ══ 战果阅兵场（v-else — 切换时物理销毁流水线 DOM 树）════════════════ -->
    <section v-else class="task-scroll-area">

      <div v-if="completedTasks.length === 0" class="empty-state">
        <div class="empty-icon">🏆</div>
        <p>暂无完成成果，等待流水线产出战果</p>
      </div>

      <!-- item-size = card(220px) + margin-bottom(12px) = 232 -->
      <RecycleScroller
        v-else
        class="task-scroller"
        :items="completedTasks"
        :item-size="232"
        :prerender="8"
        key-field="id"
        v-slot="{ item }"
      >
        <!-- ── Phase 7 完整三行式卡片 ── -->
        <div class="task-card task-card--completed">

          <!-- ══ ROW 1: 元数据 ══ -->
          <div class="row-meta">
            <div class="meta-left">
              <span class="meta-task-id">#{{ item.id.slice(-8) }}</span>
              <span v-if="item.assets?.length" class="meta-batch">包含 {{ item.assets.length }} 个视频</span>
              <span class="status-badge badge-completed">已完成</span>
            </div>
            <div class="meta-right">
              <span v-if="item.startTs" class="meta-time">
                {{ item.startTs }}<template v-if="item.endTs"> → {{ item.endTs }}</template>
              </span>
              <span v-if="item.duration" class="meta-duration">{{ item.duration }}</span>
            </div>
          </div>

          <!-- ══ ROW 2: 提示词（可展开）══ -->
          <div class="row-prompt" :class="{ 'row-prompt--expanded': expandedPrompts.has(item.id) }">
            <p class="prompt-text" :class="{ 'prompt-text--clamp': !expandedPrompts.has(item.id) }">
              {{ item.prompt || '（无描述）' }}
            </p>
            <button
              v-if="(item.prompt?.length ?? 0) > 60"
              class="prompt-toggle"
              @click.stop="togglePrompt(item.id)"
              :aria-label="expandedPrompts.has(item.id) ? '折叠' : '展开'"
            >
              <svg
                class="toggle-arrow"
                :class="{ 'toggle-arrow--up': expandedPrompts.has(item.id) }"
                width="12" height="12" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" stroke-width="2.5"
                stroke-linecap="round" stroke-linejoin="round"
              >
                <polyline points="6 9 12 15 18 9"/>
              </svg>
            </button>
          </div>

          <!-- ══ ROW 3: 资产轮播（1:1 强制比例横向轮播）══ -->
          <template v-if="item.assets?.length">
            <div
              class="row-carousel"
              :class="{ 'row-carousel--few': item.assets.length <= PAGE_SIZE }"
            >
              <!-- 左翻页 -->
              <button
                class="carousel-arrow carousel-arrow--left"
                :disabled="getCarousel(item.id).page === 0"
                @click="carouselPrev(item.id, item.assets.length, $event)"
                v-show="item.assets.length > PAGE_SIZE"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2.5"
                     stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="15 18 9 12 15 6"/>
                </svg>
              </button>

              <!-- 轮播视口 -->
              <div
                class="carousel-viewport"
                :class="{ 'carousel-viewport--few': item.assets.length <= PAGE_SIZE }"
              >
                <div
                  v-for="(asset, localIdx) in getVisibleAssets(item)"
                  :key="asset.file_hash || localIdx"
                  :class="[
                    'carousel-cell',
                    { 'carousel-cell--active': getGlobalIdx(item, localIdx) === getCarousel(item.id).activeIdx },
                    { 'carousel-cell--fixed': item.assets.length <= PAGE_SIZE },
                  ]"
                >
                  <!-- CoverPreviewCard 替代裸 video，复用封面/状态角标/hover 交互 -->
                  <CoverPreviewCard
                    :variant="{
                      id:             asset.file_hash,
                      task_id:        item.id,
                      video_url:      appStore.buildVideoUrl(asset.file_path),
                      cover_url:      asset.cover_path ? appStore.buildVideoUrl(asset.cover_path) : '',
                      status:         asset.status || 'PENDING',
                      cover_strategy: 'EXTRACT',
                    }"
                    :hide-actions="true"
                    aspect-ratio="1/1"
                    @preview="handleCardPreview(item, localIdx)"
                  />
                </div>
              </div>

              <!-- 右翻页 -->
              <button
                class="carousel-arrow carousel-arrow--right"
                :disabled="getCarousel(item.id).page >= Math.ceil(item.assets.length / PAGE_SIZE) - 1"
                @click="carouselNext(item.id, item.assets.length, $event)"
                v-show="item.assets.length > PAGE_SIZE"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2.5"
                     stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="9 18 15 12 9 6"/>
                </svg>
              </button>

              <!-- 页码点 -->
              <div v-if="item.assets.length > PAGE_SIZE" class="carousel-dots">
                <span
                  v-for="p in Math.ceil(item.assets.length / PAGE_SIZE)"
                  :key="p"
                  :class="['dot', { 'dot--active': p - 1 === getCarousel(item.id).page }]"
                />
              </div>
            </div>
          </template>
          <template v-else>
            <div class="row-empty" />
          </template>

        </div>
      </RecycleScroller>

    </section>

    <!-- ══ MasterPreviewModal ════════════════════════════════════════════════ -->
    <MasterPreviewModal
      v-if="modalOpen && modalTask"
      :task="modalTask"
      :initial-index="modalAssetIdx"
      @close="onModalClose"
      @open-detail="onOpenDetail"
    />

  </div>
</template>

<style scoped>
/* ── Layout ──────────────────────────────────────────────────────────────── */
.queue-layout {
  display:        flex;
  flex-direction: column;
  height:         100%;
  min-height:     0;
  background:     #0f172a;
  color:          #e2e8f0;
}

/* ── StatsHeader ─────────────────────────────────────────────────────────── */
.stats-header {
  position:        sticky;
  top:             0;
  z-index:         10;
  display:         flex;
  flex-direction:  column;
  align-items:     stretch;
  gap:             0.45rem;
  padding:         0.65rem 1.25rem;
  background:      rgba(15, 23, 42, 0.94);
  backdrop-filter: blur(12px);
  border-bottom:   1px solid rgba(148, 163, 184, 0.1);
  flex-shrink:     0;
}
.stats-row {
  display:         flex;
  align-items:     center;
  justify-content: space-between;
  width:           100%;
  gap:             0.5rem;
}
.stat-item {
  display:        flex;
  flex-direction: column;
  align-items:    center;
  gap:            0.1rem;
  flex:           1 1 0;
  min-width:      0;
}
.stat-label { font-size: 0.62rem; color: #64748b; white-space: nowrap; font-weight: 500; }
.stat-value { font-size: 1.1rem; font-weight: 700; color: #e2e8f0; line-height: 1; }
.stat-eta     { color: #38bdf8; font-variant-numeric: tabular-nums; }
.stat-running { color: #facc15; }
.stat-done    { color: #4ade80; }
.stat-fail    { color: #f87171; }
.progress-track {
  width: 100%; height: 3px; background: rgba(148, 163, 184, 0.1);
  border-radius: 2px; overflow: hidden;
}
.progress-fill {
  height: 100%; background: linear-gradient(90deg, #38bdf8, #818cf8);
  border-radius: 2px; transition: width 0.6s ease;
}
.debug-btn {
  padding: 3px 10px; border: none; border-radius: 4px;
  color: white; font-weight: 700; font-size: 0.7rem; cursor: pointer;
}
.debug-btn--red  { background: #ef4444; }
.debug-btn--blue { background: #3b82f6; }

/* ── Tab 导航栏 ──────────────────────────────────────────────────────────── */
.tab-nav {
  display:       flex;
  flex-shrink:   0;
  background:    rgba(9, 14, 30, 0.97);
  border-bottom: 1px solid rgba(99, 102, 241, 0.12);
  padding:       0 0.5rem;
}
.tab-btn {
  position:    relative;
  display:     flex;
  align-items: center;
  gap:         0.4rem;
  padding:     0.6rem 1.1rem;
  background:  transparent;
  border:      none;
  border-bottom: 2px solid transparent;
  color:       #475569;
  font-size:   0.78rem;
  font-weight: 600;
  cursor:      pointer;
  letter-spacing: 0.02em;
  transition:  color 0.15s, border-color 0.15s, background 0.15s;
  white-space: nowrap;
}
.tab-btn:hover { color: #94a3b8; background: rgba(99, 102, 241, 0.04); }
.tab-btn--active {
  color:         #a5b4fc;
  border-bottom-color: #6366f1;
  background:    rgba(99, 102, 241, 0.06);
}
.tab-icon  { font-size: 0.9rem; }
.tab-label { }

.tab-badge {
  min-width:    18px;
  height:       18px;
  padding:      0 5px;
  border-radius: 9px;
  font-size:    0.6rem;
  font-weight:  700;
  display:      inline-flex;
  align-items:  center;
  justify-content: center;
  line-height:  1;
}
.tab-badge--hot  {
  background: linear-gradient(135deg, #f59e0b, #ef4444);
  color: #fff;
  box-shadow: 0 0 8px rgba(245, 158, 11, 0.4);
}
.tab-badge--gold {
  background: linear-gradient(135deg, #4ade80, #22d3ee);
  color: #0f172a;
  box-shadow: 0 0 8px rgba(74, 222, 128, 0.3);
}
.badge-pop-enter-active, .badge-pop-leave-active { transition: opacity 0.2s, transform 0.2s; }
.badge-pop-enter-from, .badge-pop-leave-to       { opacity: 0; transform: scale(0.5); }

/* ── ScrollArea ──────────────────────────────────────────────────────────── */
.task-scroll-area {
  flex:           1 1 0;
  min-height:     200px;
  overflow-y:     hidden;
  display:        flex;
  flex-direction: column;
}
.task-scroller {
  height:          100%;
  padding:         0.6rem 0.9rem;
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.2) transparent;
}
.task-scroller::-webkit-scrollbar       { width: 5px; }
.task-scroller::-webkit-scrollbar-track { background: transparent; }
.task-scroller::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.2); border-radius: 3px; }

/* ── Empty State ─────────────────────────────────────────────────────────── */
.empty-state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 0.75rem; height: 100%;
  color: #475569; user-select: none;
}
.empty-icon { font-size: 3rem; opacity: 0.18; }
.empty-state p { font-size: 0.82rem; max-width: 260px; text-align: center; line-height: 1.5; }

/* ══════════════════════════════════════════════════════════════════════════
   轰鸣流水线 — 极简监控条
   高度：52px + margin-bottom 8px = 60px（匹配 RecycleScroller item-size）
══════════════════════════════════════════════════════════════════════════ */
.monitor-strip {
  height:         52px;
  box-sizing:     border-box;
  margin-bottom:  8px;
  padding:        0 0.85rem;
  border-radius:  8px;
  border:         1px solid rgba(148, 163, 184, 0.08);
  background:     rgba(22, 32, 52, 0.7);
  display:        flex;
  align-items:    center;
  gap:            0.75rem;
  transition:     border-color 0.2s, background 0.2s;
  overflow:       hidden;
}
.monitor-strip--pending { border-left: 3px solid #64748b; }
.monitor-strip--running {
  border-left: 3px solid #38bdf8;
  background:  rgba(56, 189, 248, 0.04);
}
.monitor-strip--failed  {
  border-left: 3px solid #f87171;
  opacity:     0.65;
}

/* 左侧信息组 */
.ms-left {
  display:     flex;
  align-items: center;
  gap:         0.45rem;
  flex-shrink: 0;
}

/* 脉冲指示灯 */
.ms-pulse {
  width:         8px;
  height:        8px;
  border-radius: 50%;
  flex-shrink:   0;
  background:    #475569;
  transition:    background 0.2s;
}
.ms-pulse--running {
  background: #38bdf8;
  box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.6);
  animation:  pulse-ring 1.4s ease-out infinite;
}
@keyframes pulse-ring {
  0%   { box-shadow: 0 0 0 0   rgba(56, 189, 248, 0.6); }
  70%  { box-shadow: 0 0 0 6px rgba(56, 189, 248, 0);   }
  100% { box-shadow: 0 0 0 0   rgba(56, 189, 248, 0);   }
}

.ms-id {
  font-size:    0.68rem;
  font-weight:  700;
  color:        #475569;
  font-family:  'Courier New', monospace;
  font-variant-numeric: tabular-nums;
  white-space:  nowrap;
}
.ms-badge {
  font-size:    0.6rem;
  font-weight:  600;
  padding:      1px 6px;
  border-radius: 4px;
  letter-spacing: 0.02em;
  white-space:  nowrap;
}

/* 提示词（中间截断单行）*/
.ms-prompt {
  flex:          1 1 0;
  min-width:     0;
  font-size:     0.75rem;
  color:         #64748b;
  white-space:   nowrap;
  overflow:      hidden;
  text-overflow: ellipsis;
  margin:        0;
}

/* 右侧状态区 */
.ms-right {
  display:     flex;
  align-items: center;
  gap:         0.5rem;
  flex-shrink: 0;
}

/* 不定态进度条 */
.ms-bar {
  width:         80px;
  height:        4px;
  border-radius: 2px;
  background:    rgba(56, 189, 248, 0.12);
  overflow:      hidden;
  flex-shrink:   0;
}
.ms-bar-fill {
  height:     100%;
  width:      40%;
  border-radius: 2px;
  background: linear-gradient(90deg, transparent, #38bdf8, transparent);
  background-size: 200% 100%;
  animation:  sweep 1.5s ease-in-out infinite;
}
@keyframes sweep {
  0%   { background-position: -100% 0; }
  100% { background-position:  200% 0; }
}

/* running 旋转图标 */
.ms-spin {
  color:     #38bdf8;
  flex-shrink: 0;
  animation: spin-icon 1s linear infinite;
}
@keyframes spin-icon { to { transform: rotate(360deg); } }

/* 失败标签 */
.ms-fail-tag {
  font-size:   0.65rem;
  font-weight: 700;
  color:       #f87171;
  white-space: nowrap;
}

/* 时间戳 */
.ms-ts {
  font-size:    0.65rem;
  color:        #334155;
  font-family:  monospace;
  font-variant-numeric: tabular-nums;
  white-space:  nowrap;
}

/* ══════════════════════════════════════════════════════════════════════════
   战果阅兵场 — Phase 7 完整三行式卡片
   高度：220px + margin-bottom 12px = 232px（匹配 RecycleScroller item-size）
══════════════════════════════════════════════════════════════════════════ */
.task-card {
  height:         220px;
  box-sizing:     border-box;
  margin-bottom:  12px;
  padding:        0.6rem 0.85rem 0.5rem;
  border-radius:  10px;
  border:         1px solid rgba(148, 163, 184, 0.1);
  background:     rgba(30, 41, 59, 0.62);
  overflow:       hidden;
  display:        flex;
  flex-direction: column;
  gap:            0;
  transition:     border-color 0.2s, background 0.2s;
}
.task-card--completed { border-left: 3px solid #4ade80; }

/* ── Row 1: Meta ─────────────────────────────────────────────────────────── */
.row-meta {
  display:         flex;
  align-items:     center;
  justify-content: space-between;
  gap:             0.5rem;
  flex-shrink:     0;
  height:          24px;
  margin-bottom:   5px;
}
.meta-left, .meta-right {
  display:     flex;
  align-items: center;
  gap:         0.4rem;
  min-width:   0;
}
.meta-task-id {
  font-size:    0.7rem;
  font-weight:  700;
  color:        #475569;
  font-family:  'Courier New', monospace;
  font-variant-numeric: tabular-nums;
  white-space:  nowrap;
}
.meta-batch {
  font-size:    0.65rem;
  color:        #a78bfa;
  background:   rgba(167, 139, 250, 0.1);
  border:       1px solid rgba(167, 139, 250, 0.22);
  border-radius: 10px;
  padding:      1px 7px;
  white-space:  nowrap;
}
.meta-time {
  font-size:    0.65rem;
  color:        #475569;
  font-family:  'Courier New', monospace;
  font-variant-numeric: tabular-nums;
  white-space:  nowrap;
}
.meta-duration {
  font-size:    0.7rem;
  font-weight:  600;
  color:        #38bdf8;
  font-variant-numeric: tabular-nums;
  white-space:  nowrap;
}
.status-badge {
  font-size: 0.62rem; font-weight: 600;
  padding: 1px 7px; border-radius: 4px;
  letter-spacing: 0.02em; white-space: nowrap;
}
.badge-pending   { background: rgba(100, 116, 139, 0.2); color: #94a3b8; }
.badge-running   { background: rgba(56,  189, 248, 0.15); color: #38bdf8; }
.badge-completed { background: rgba(74,  222, 128, 0.15); color: #4ade80; }
.badge-failed    { background: rgba(248, 113, 113, 0.15); color: #f87171; }

/* ── Row 2: Prompt ───────────────────────────────────────────────────────── */
.row-prompt {
  position:    relative;
  flex-shrink: 0;
  display:     flex;
  align-items: flex-start;
  gap:         0.25rem;
  margin-bottom: 6px;
  max-height:  36px;
  transition:  max-height 0.3s ease;
  overflow:    hidden;
}
.row-prompt--expanded { max-height: 200px; }
.prompt-text {
  font-size:   0.78rem;
  color:       #94a3b8;
  line-height: 1.45;
  margin:      0;
  flex:        1;
  min-width:   0;
}
.prompt-text--clamp {
  display:             -webkit-box;
  -webkit-line-clamp:  2;
  -webkit-box-orient:  vertical;
  overflow:            hidden;
}
.row-prompt--expanded .prompt-text--clamp {
  display:             block;
  overflow:            visible;
  -webkit-line-clamp:  unset;
}
.prompt-toggle {
  flex-shrink: 0;
  width:       20px;
  height:      20px;
  display:     flex;
  align-items: center;
  justify-content: center;
  border:      none;
  background:  transparent;
  cursor:      pointer;
  color:       #64748b;
  border-radius: 4px;
  padding:     0;
  transition:  color 0.15s, background 0.15s;
  margin-top:  1px;
}
.prompt-toggle:hover { color: #a5b4fc; background: rgba(99, 102, 241, 0.1); }
.toggle-arrow { transition: transform 0.25s ease; }
.toggle-arrow--up { transform: rotate(180deg); }

/* ── Row 3: Carousel ─────────────────────────────────────────────────────── */
.row-carousel {
  flex:     1 1 0;
  display:  flex;
  align-items: center;
  gap:      0.3rem;
  min-height: 0;
  position: relative;
}
.carousel-viewport {
  flex:     1 1 0;
  display:  flex;
  gap:      0.4rem;
  align-items: stretch;
  height:   100%;
  overflow: hidden;
}
.carousel-viewport--few {
  flex:            0 0 auto;
  justify-content: flex-start;
}
.row-carousel--few {
  justify-content: flex-start;
}
.carousel-cell {
  flex:          1 1 0;
  position:      relative;
  cursor:        pointer;
  border-radius: 7px;
  border:        2px solid transparent;
  overflow:      hidden;
  transition:    border-color 0.2s, box-shadow 0.2s, transform 0.15s;
  /* 1:1 相册方块比例 */
  aspect-ratio:  1 / 1;
  background:    #000;
}
.carousel-cell--fixed {
  flex:       0 0 auto;
  width:      78px;
  aspect-ratio: 1 / 1;
  max-width:  78px;
}
.carousel-cell:hover {
  transform:    scale(1.03);
  border-color: rgba(99, 102, 241, 0.5);
}
.carousel-cell--active {
  border-color: #a78bfa !important;
  box-shadow:   0 0 0 2px rgba(167, 139, 250, 0.35), 0 0 16px rgba(167, 139, 250, 0.4);
}
.carousel-arrow {
  flex-shrink: 0;
  width:       24px;
  height:      24px;
  border:      1px solid rgba(99, 102, 241, 0.3);
  background:  rgba(15, 23, 42, 0.8);
  color:       #94a3b8;
  border-radius: 6px;
  display:     flex;
  align-items: center;
  justify-content: center;
  cursor:      pointer;
  padding:     0;
  transition:  border-color 0.15s, color 0.15s, background 0.15s;
}
.carousel-arrow:hover:not(:disabled) {
  border-color: #a78bfa;
  color:        #a78bfa;
  background:   rgba(167, 139, 250, 0.1);
}
.carousel-arrow:disabled { opacity: 0.25; cursor: not-allowed; }
.carousel-dots {
  position:  absolute;
  bottom:    -2px;
  right:     28px;
  display:   flex;
  gap:       3px;
  pointer-events: none;
}
.dot {
  width: 5px; height: 5px;
  border-radius: 50%;
  background: rgba(148, 163, 184, 0.3);
  transition: background 0.2s;
}
.dot--active { background: #a78bfa; }

/* ── Empty Placeholder ───────────────────────────────────────────────────── */
.row-empty { flex: 1 1 0; }
</style>
