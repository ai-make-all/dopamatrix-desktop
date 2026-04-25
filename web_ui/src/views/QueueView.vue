<script setup lang="ts">
/**
 * QueueView.vue — 任务队列视图
 *
 * 布局策略：
 *   ┌─────────────────────────────────────────┐
 *   │  StatsHeader  (position: sticky, top:0) │  ← 固定高度，显示倒计时与汇总统计
 *   ├─────────────────────────────────────────┤
 *   │                                         │
 *   │  TaskScrollArea  (flex-grow: 1,         │  ← 占据全部剩余高度
 *   │                   overflow-y: auto)     │
 *   │                                         │
 *   └─────────────────────────────────────────┘
 *
 * 虚拟列表集成指南（vue-virtual-scroller）：
 *   1. 安装依赖：npm install vue-virtual-scroller@next
 *   2. 在 main.js 全局注册（或在此处局部引入）：
 *        import { RecycleScroller } from 'vue-virtual-scroller'
 *        import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
 *   3. 将下方 <TaskScrollArea> 内的 v-for 替换为 <RecycleScroller>：
 *        <RecycleScroller
 *          class="task-scroller"
 *          :items="queueStore.tasks"
 *          :item-size="TASK_CARD_HEIGHT"
 *          key-field="id"
 *          v-slot="{ item }"
 *        >
 *          <TaskCard :task="item" />
 *        </RecycleScroller>
 *      其中 TASK_CARD_HEIGHT 为像素高度常量（如 88）。
 *      RecycleScroller 要求宿主元素有明确的固定高度，因此 .task-scroller
 *      需要 height: 100% 并继承父容器的 flex-grow: 1 撑满高度。
 */

import { onMounted, onUnmounted, computed, ref } from 'vue'
import { useQueueStore }                    from '../stores/useQueueStore'
import type { QueueTask }                  from '../stores/useQueueStore'
import { useAppStore }                     from '../stores/appStore'

const queueStore = useQueueStore()
// ==================== 🚧 极限压力测试脚本 🚧 ====================

// 定义一个压测标志位，防止重复点击
const isStressTesting = ref(false)

// [STRESS_TEST] 真实 WS 洪流压测标志位，防止重复点击
// 测试完成后注释掉：isRealWsFlooding + triggerRealWsFlood 整个函数
const isRealWsFlooding = ref(false)

/**
 * [STRESS_TEST] 触发后端真实 WS 洪流压测。
 *
 * 向 POST /api/v1/test/flood-ws 发起请求，携带当前用户的 X-Local-User。
 * 后端收到后在 BackgroundTask 中执行 run_ws_flood_test()，
 * 通过真实的 broadcast_sync → WebSocket 管道将 500 个任务推送到前端。
 *
 * 测试完成后应注释掉：
 *   1. isRealWsFlooding ref
 *   2. 本函数（triggerRealWsFlood）
 *   3. 模板中的 [WS-REAL-TEST] 按钮
 */
const triggerRealWsFlood = async () => {  // [STRESS_TEST]
  if (isRealWsFlooding.value) return
  isRealWsFlooding.value = true

  const userId = appStore.loggedInUser || 'default'
  console.log(`🌊 [WS-REAL-TEST] 正在向后端发起真实 WebSocket 洪流压测，user=${userId}...`)

  try {
    const res = await fetch('http://127.0.0.1:8000/api/v1/test/flood-ws', {
      method:  'POST',
      headers: { 'X-Local-User': userId },
    })

    if (res.ok) {
      const data = await res.json()
      console.log('🌊 [WS-REAL-TEST] 压测已启动，后端正在通过真实 WebSocket 管道推送 500 条消息：', data)
    } else {
      console.error(`🌊 [WS-REAL-TEST] 压测接口返回错误 HTTP ${res.status}，请确认后端已启动且 test_router 已挂载。`)
    }
  } catch (err) {
    console.error('🌊 [WS-REAL-TEST] 请求失败（后端未启动或网络异常）：', err)
  } finally {
    // 后端异步执行，约 15-30s 后完成；前端标志位在请求返回后立即解锁（允许重复触发）
    isRealWsFlooding.value = false
  }
}

const runStressTest = () => {
  if (isStressTesting.value) return
  isStressTesting.value = true
  console.log('🚀 [压测启动] 正在注入 500 个并发任务...')

  // 1. 瞬间造 500 个假任务（模拟历史数据初始化）
  const mockTasks: QueueTask[] = Array.from({ length: 500 }).map((_, i) => {
    const now = Date.now() - Math.random() * 10000;
    const ts = new Date(now).toLocaleTimeString('zh', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    return {
      id: `mock_test_task_${i}`,
      type: 'pending', // 初始全部设为排队中
      prompt: `【极限压测】第 ${i} 号并发渲染任务。模拟极端复杂的 Prompt，包含赛博朋克风格、多巴胺色彩、极速运镜和阿拉伯语唇形同步要求...`,
      ts: ts,
      startTime: now,
      startTs: ts,
      assets: []
    }
  })

  // 瞬间推入 Worker 引擎
  queueStore.initTasks(mockTasks)

  // 2. 模拟高频 WebSocket 状态洪水 (WebSocket Flood Simulation)
  console.log('🌊 [压测中] 启动高频状态流推送 (50ms/次)...')
  
  const floodInterval = setInterval(() => {
    // 从 store 中实时获取当前各状态的任务池
    const pendingTasks = queueStore.tasks.filter(t => t.type === 'pending')
    const runningTasks = queueStore.tasks.filter(t => t.type === 'running')

    if (pendingTasks.length === 0 && runningTasks.length === 0) {
      clearInterval(floodInterval)
      isStressTesting.value = false
      console.log('✅ [压测结束] 500 个任务已全部模拟执行完毕！')
      return
    }

    // 动作 A：随机拉起 1~3 个 pending 任务进入 running 状态
    if (pendingTasks.length > 0 && Math.random() > 0.4) {
      const idx = Math.floor(Math.random() * pendingTasks.length)
      queueStore.pushTaskUpdate({
        taskId: pendingTasks[idx].id,
        status: 'running',
        startTime: Date.now()
      })
    }

    // 动作 B：随机把 1 个 running 任务变成 completed (附带模拟渲染好的视频文件)
    if (runningTasks.length > 0 && Math.random() > 0.6) {
      const idx = Math.floor(Math.random() * runningTasks.length)
      queueStore.pushTaskUpdate({
        taskId: runningTasks[idx].id,
        status: 'completed',
        assets: [
          { file_path: `/mock/output_${runningTasks[idx].id}.mp4`, file_hash: `hash_${Math.random().toString(16).slice(2, 10)}` }
        ]
      })
    }
    
    // 每 50ms 触发一次，这比真实的 WebSocket 并发还要快 10 倍！
  }, 50) 
}
// ==============================================================

const appStore   = useAppStore()

// ── 生命周期 ─────────────────────────────────────────────────────────────────

onMounted(() => {
  queueStore.initWorker()

  /**
   * 持票上船：先向后端申请一次性船票，再建立鉴权 WebSocket 连接。
   * 断线后 _scheduleWsReconnect 会自动重新购票，无需手动干预。
   * 任务列表仅由 WebSocket 实时驱动，不再从本地缓存同步旧数据。
   */
  queueStore.connectEventBus(appStore.loggedInUser || 'default')
})

onUnmounted(() => {
  // 离开队列页时释放 Worker 与 WebSocket，避免后台持续占用资源
  queueStore.dispose()
})

// ── 统计派生计算 ──────────────────────────────────────────────────────────────

const etaDisplay = computed<string>(() => {
  const s = queueStore.stats.estimatedETA_seconds
  if (s <= 0) return '--'
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0
    ? `${m}分 ${String(r).padStart(2, '0')}秒`
    : `${r} 秒`
})

const progressPct = computed<number>(() => {
  const { totalCompleted, totalPending, totalRunning, totalFailed } = queueStore.stats
  const total = totalCompleted + totalPending + totalRunning + totalFailed
  return total === 0 ? 0 : Math.round((totalCompleted / total) * 100)
})

// ── 工具函数 ─────────────────────────────────────────────────────────────────

function statusLabel(type: QueueTask['type']): string {
  return { pending: '排队中', running: '生成中', completed: '已完成', failed: '失败' }[type] ?? type
}

function statusClass(type: QueueTask['type']): string {
  return {
    pending:   'badge-pending',
    running:   'badge-running',
    completed: 'badge-completed',
    failed:    'badge-failed',
  }[type] ?? ''
}
</script>

<template>
  <div class="queue-layout">

    <!-- ══════════════════════════════════════════════════════════════════════ -->
    <!--  StatsHeader — sticky 顶部统计栏                                      -->
    <!-- ══════════════════════════════════════════════════════════════════════ -->
    <header class="stats-header">

      <div class="stat-item">
        <span class="stat-label">⏳ 预计剩余</span>
        <span class="stat-value stat-eta">{{ etaDisplay }}</span>
      </div>

      <div class="stat-divider" />

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

      <button 
        @click="runStressTest" 
        :disabled="isStressTesting"
        style="margin-left: auto; padding: 4px 12px; background: #ef4444; color: white; border: none; border-radius: 4px; font-weight: bold; cursor: pointer;"
      >
        {{ isStressTesting ? '🌋 压测洪水中...' : '🚀 注入 500 任务压测' }}
      </button>

      <!-- [WS-REAL-TEST] 真实 WebSocket 洪流压测按钮 — 测试完成后注释掉此整段 button -->
      <button
        @click="triggerRealWsFlood"
        :disabled="isRealWsFlooding"
        style="padding: 4px 12px; background: #3b82f6; color: white; border: none; border-radius: 4px; font-weight: bold; cursor: pointer; opacity: 1;"
        :style="isRealWsFlooding ? { opacity: '0.6', cursor: 'not-allowed' } : {}"
      >
        {{ isRealWsFlooding ? '🌊 WS 压测发送中...' : '🌊 启动 WS 真实压测' }}
      </button>

      <!-- 进度条 -->
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

    <!-- ══════════════════════════════════════════════════════════════════════ -->
    <!--  TaskScrollArea — 可滚动任务列表（此处挂载虚拟列表）                  -->
    <!--                                                                       -->
    <!--  【虚拟列表替换方案】                                                  -->
    <!--  将下方的 <div v-for ...> 整块替换为：                                 -->
    <!--                                                                       -->
    <!--    <RecycleScroller                                                    -->
    <!--      class="task-scroller"                                            -->
    <!--      :items="queueStore.tasks"                                        -->
    <!--      :item-size="88"                                                  -->
    <!--      key-field="id"                                                   -->
    <!--      v-slot="{ item }"                                                -->
    <!--    >                                                                   -->
    <!--      <TaskCard :task="item" />                                        -->
    <!--    </RecycleScroller>                                                 -->
    <!--                                                                       -->
    <!--  注意：.task-scroller 需要继承父容器高度（height: 100%），            -->
    <!--  RecycleScroller 自身负责管理 overflow-y: auto。                     -->
    <!-- ══════════════════════════════════════════════════════════════════════ -->
    <section class="task-scroll-area">

      <div v-if="queueStore.tasks.length === 0" class="empty-state">
        <div class="empty-icon">🎬</div>
        <p>暂无任务，前往工作台创建矩阵任务</p>
      </div>

      <!-- RecycleScroller 虚拟列表：只渲染可视区域内的卡片，DOM 节点数恒定 -->
      <RecycleScroller
        class="task-scroller"
        :items="queueStore.tasks"
        :item-size="110"
        :prerender="10"
        key-field="id"
        v-slot="{ item }"
      >
        <div :class="['task-card', `task-card--${item.type}`]">
          <!-- 卡片头部 -->
          <div class="task-card__header">
            <!-- 状态动画图标 -->
            <svg
              v-if="item.type === 'running'"
              class="spin-icon"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle class="spin-track" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/>
              <path class="spin-fill" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
            <span v-else-if="item.type === 'completed'" class="icon-done">✓</span>
            <span v-else-if="item.type === 'failed'"    class="icon-fail">✕</span>
            <span v-else                                class="icon-pending">·</span>

            <span :class="['status-badge', statusClass(item.type)]">
              {{ statusLabel(item.type) }}
            </span>

            <span class="task-id">Task #{{ item.id }}</span>

            <span v-if="item.duration" class="task-duration">{{ item.duration }}</span>
            <span v-else-if="item.startTs" class="task-ts">{{ item.startTs }}</span>
          </div>

          <!-- Prompt 摘要 -->
          <p class="task-prompt">{{ item.prompt || '（无描述）' }}</p>

          <!-- 完成时展示资产缩略 -->
          <div v-if="item.type === 'completed' && item.assets?.length" class="task-assets">
            <div
              v-for="(asset, idx) in item.assets"
              :key="idx"
              class="asset-chip"
            >
              <span class="asset-chip__hash">{{ asset.file_hash?.slice(0, 8) }}…</span>
            </div>
          </div>
        </div>
      </RecycleScroller>

    </section>

  </div>
</template>

<style scoped>
/* ── 顶层容器：占满父级高度，纵向弹性布局 ─────────────────────────────────── */
.queue-layout {
  display:        flex;
  flex-direction: column;
  height:         100%;
  min-height:     0;       /* 防止 flex 子元素撑破父容器 */
  background:     #0f172a;
  color:          #e2e8f0;
  font-family:    inherit;
}

/* ── StatsHeader ──────────────────────────────────────────────────────────── */
.stats-header {
  position:         sticky;
  top:              0;
  z-index:          10;
  display:          flex;
  align-items:      center;
  gap:              1.25rem;
  flex-wrap:        wrap;
  padding:          0.75rem 1.25rem;
  background:       rgba(15, 23, 42, 0.92);
  backdrop-filter:  blur(12px);
  border-bottom:    1px solid rgba(148, 163, 184, 0.12);
  flex-shrink:      0;   /* 不随 flex 压缩 */
}

.stat-item {
  display:        flex;
  flex-direction: column;
  align-items:    center;
  gap:            0.15rem;
  min-width:      3.5rem;
}

.stat-label {
  font-size:   0.68rem;
  color:       #64748b;
  white-space: nowrap;
  font-weight: 500;
}

.stat-value {
  font-size:   1.25rem;
  font-weight: 700;
  line-height: 1;
  color:       #e2e8f0;
}

.stat-eta     { color: #38bdf8; font-variant-numeric: tabular-nums; }
.stat-running { color: #facc15; }
.stat-done    { color: #4ade80; }
.stat-fail    { color: #f87171; }

.stat-divider {
  width:       1px;
  height:      2rem;
  background:  rgba(148, 163, 184, 0.15);
  flex-shrink: 0;
}

/* 进度条 */
.progress-track {
  flex:             1 1 100%;
  height:           3px;
  background:       rgba(148, 163, 184, 0.1);
  border-radius:    2px;
  overflow:         hidden;
  margin-top:       0.25rem;
}

.progress-fill {
  height:           100%;
  background:       linear-gradient(90deg, #38bdf8, #818cf8);
  border-radius:    2px;
  transition:       width 0.6s ease;
  will-change:      width;
}

/* ── TaskScrollArea ────────────────────────────────────────────────────────── */
.task-scroll-area {
  flex:           1 1 0;     /* flex-grow: 1，占据全部剩余高度 */
  min-height:     200px;     /* 防御性最小高度，避免初始高度为 0 导致渲染死循环 */
  overflow-y:     hidden;    /* RecycleScroller 自身接管滚动，此处关闭 */
  display:        flex;
  flex-direction: column;
}

/* RecycleScroller 容器：继承父高度，自身负责 overflow-y: auto */
.task-scroller {
  height:  100%;
  padding: 1rem 1.25rem;

  /* 自定义滚动条（Webkit） */
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.2) transparent;
}

.task-scroller::-webkit-scrollbar       { width: 5px; }
.task-scroller::-webkit-scrollbar-track { background: transparent; }
.task-scroller::-webkit-scrollbar-thumb {
  background:    rgba(148, 163, 184, 0.2);
  border-radius: 3px;
}

/* ── 空状态 ────────────────────────────────────────────────────────────────── */
.empty-state {
  display:         flex;
  flex-direction:  column;
  align-items:     center;
  justify-content: center;
  gap:             0.75rem;
  height:          100%;
  color:           #475569;
  user-select:     none;
}

.empty-icon {
  font-size:  3.5rem;
  opacity:    0.18;
}

.empty-state p {
  font-size:    0.85rem;
  max-width:    280px;
  text-align:   center;
  line-height:  1.5;
}

/* ── TaskCard ──────────────────────────────────────────────────────────────── */
/* height(100px) + margin-bottom(10px) = 110px，与 RecycleScroller item-size 严格对齐 */
.task-card {
  height:        100px;
  box-sizing:    border-box;
  margin-bottom: 10px;
  padding:       0.65rem 0.9rem;
  border-radius: 8px;
  border:        1px solid rgba(148, 163, 184, 0.1);
  background:    rgba(30, 41, 59, 0.6);
  transition:    border-color 0.2s, background 0.2s;
  overflow:      hidden;   /* 防止内容超出固定高度时撑破虚拟列表布局 */
}

.task-card--pending   { border-left: 3px solid #64748b; }
.task-card--running   { border-left: 3px solid #38bdf8; background: rgba(56, 189, 248, 0.04); }
.task-card--completed { border-left: 3px solid #4ade80; }
.task-card--failed    { border-left: 3px solid #f87171; opacity: 0.7; }

.task-card__header {
  display:     flex;
  align-items: center;
  gap:         0.5rem;
  flex-wrap:   wrap;
  margin-bottom: 0.35rem;
}

/* 旋转动画图标 */
.spin-icon {
  width:       16px;
  height:      16px;
  color:       #38bdf8;
  flex-shrink: 0;
  animation:   spin 1s linear infinite;
}

.spin-track { opacity: 0.25; }
.spin-fill  { opacity: 0.75; }

@keyframes spin {
  to { transform: rotate(360deg); }
}

.icon-done    { color: #4ade80; font-size: 0.95rem; line-height: 1; }
.icon-fail    { color: #f87171; font-size: 0.95rem; line-height: 1; }
.icon-pending { color: #64748b; font-size: 1.2rem;  line-height: 1; }

/* 状态徽章 */
.status-badge {
  font-size:     0.68rem;
  font-weight:   600;
  padding:       0.12rem 0.45rem;
  border-radius: 4px;
  letter-spacing: 0.02em;
  white-space:   nowrap;
}

.badge-pending   { background: rgba(100, 116, 139, 0.2); color: #94a3b8; }
.badge-running   { background: rgba(56,  189, 248, 0.15); color: #38bdf8; }
.badge-completed { background: rgba(74,  222, 128, 0.15); color: #4ade80; }
.badge-failed    { background: rgba(248, 113, 113, 0.15); color: #f87171; }

.task-id {
  font-size:    0.68rem;
  color:        #475569;
  font-variant-numeric: tabular-nums;
  margin-left:  auto;
}

.task-duration {
  font-size:    0.72rem;
  font-weight:  600;
  color:        #38bdf8;
  font-variant-numeric: tabular-nums;
}

.task-ts {
  font-size: 0.68rem;
  color:     #475569;
}

/* Prompt 摘要 */
.task-prompt {
  font-size:     0.8rem;
  color:         #94a3b8;
  margin:        0;
  line-height:   1.5;
  /* 超长文本折叠为 2 行 */
  display:             -webkit-box;
  -webkit-line-clamp:  2;
  -webkit-box-orient:  vertical;
  overflow:            hidden;
}

/* 资产 chip 列表 */
.task-assets {
  display:   flex;
  flex-wrap: wrap;
  gap:       0.35rem;
  margin-top: 0.45rem;
}

.asset-chip {
  display:       flex;
  align-items:   center;
  gap:           0.25rem;
  padding:       0.1rem 0.5rem;
  border-radius: 4px;
  background:    rgba(56, 189, 248, 0.1);
  border:        1px solid rgba(56, 189, 248, 0.2);
}

.asset-chip__hash {
  font-size:   0.65rem;
  color:       #7dd3fc;
  font-family: monospace;
}
</style>
