<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

// ── Mock Data (replace with real API calls in v2) ─────────────────────────
const stats = ref({
  totalVideos:       1284,
  totalFingerprints: 1284,
  runtimeSeconds:    847320,   // ~9.8 days
  estimatedCostUsd:  23.47,
})

// Simulate a live clock ticking up engine runtime
let runtimeTimer = null
onMounted(() => {
  runtimeTimer = setInterval(() => {
    stats.value.runtimeSeconds++
  }, 1000)
})
onUnmounted(() => clearInterval(runtimeTimer))

// Format seconds → "X 天 HH:MM:SS"
const fmtRuntime = computed(() => {
  const s = stats.value.runtimeSeconds
  const days  = Math.floor(s / 86400)
  const hours = Math.floor((s % 86400) / 3600).toString().padStart(2, '0')
  const mins  = Math.floor((s % 3600) / 60).toString().padStart(2, '0')
  const secs  = (s % 60).toString().padStart(2, '0')
  return `${days}d ${hours}:${mins}:${secs}`
})

// Animated counter helper – just show the raw formatted value
const fmtNum = (n) => n.toLocaleString('en-US')
const fmtUsd = (n) => `$${n.toFixed(2)}`

// ── Trend sparkline data (mock) ───────────────────────────────────────────
const sparklinePoints = [12, 19, 8, 27, 34, 22, 45, 38, 60, 52, 71, 88]
const toSvgPath = (pts) => {
  const max = Math.max(...pts)
  const h = 48, w = 160
  const stepX = w / (pts.length - 1)
  return pts.map((v, i) => `${i === 0 ? 'M' : 'L'} ${i * stepX},${h - (v / max) * h}`).join(' ')
}
</script>

<template>
  <div class="dashboard-root">

    <!-- ═══════════════════════════════════════════════════════════════ -->
    <!--  LEFT HALF  –  真实成本测算                                      -->
    <!-- ═══════════════════════════════════════════════════════════════ -->
    <div class="dash-panel left-panel">

      <!-- Panel header -->
      <div class="panel-header">
        <span class="header-dot dot-cyan"></span>
        <span class="panel-title">真实成本测算</span>
        <span class="panel-subtitle">Real-Time ROI Tracker · ClipFlow Engine</span>
      </div>

      <!-- Big stat cards -->
      <div class="stat-grid">

        <!-- Stat: Videos -->
        <div class="stat-card">
          <div class="stat-icon icon-cyan">🎬</div>
          <div class="stat-body">
            <div class="stat-value">{{ fmtNum(stats.totalVideos) }}</div>
            <div class="stat-label">累计生成视频资产</div>
            <div class="stat-sub">Video Assets Generated</div>
          </div>
          <svg class="sparkline" viewBox="0 0 160 48" preserveAspectRatio="none">
            <path :d="toSvgPath(sparklinePoints)" fill="none" stroke="#22d3ee" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>

        <!-- Stat: Fingerprints -->
        <div class="stat-card">
          <div class="stat-icon icon-violet">🛡️</div>
          <div class="stat-body">
            <div class="stat-value">{{ fmtNum(stats.totalFingerprints) }}</div>
            <div class="stat-label">累计防重指纹数</div>
            <div class="stat-sub">Anti-Dup MD5 Fingerprints</div>
          </div>
          <svg class="sparkline" viewBox="0 0 160 48" preserveAspectRatio="none">
            <path :d="toSvgPath([5,14,9,22,18,30,25,41,35,50,44,60])" fill="none" stroke="#a78bfa" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>

        <!-- Stat: Runtime -->
        <div class="stat-card stat-card-wide">
          <div class="stat-icon icon-emerald">⏱️</div>
          <div class="stat-body">
            <div class="stat-value stat-mono">{{ fmtRuntime }}</div>
            <div class="stat-label">引擎累计运行时长</div>
            <div class="stat-sub">Engine Uptime · Live Counter</div>
          </div>
          <span class="live-badge">● LIVE</span>
        </div>

        <!-- Stat: API Cost -->
        <div class="stat-card stat-card-wide cost-card">
          <div class="stat-icon icon-amber">💰</div>
          <div class="stat-body">
            <div class="stat-value cost-value">{{ fmtUsd(stats.estimatedCostUsd) }}</div>
            <div class="stat-label">累计 API 调用成本</div>
            <div class="stat-sub">estimated_cost_usd · GPT-4 / TTS / Whisper</div>
          </div>
          <div class="cost-breakdown">
            <div class="cost-row">
              <span>GPT-4o Script</span><span class="cost-amt">$14.20</span>
            </div>
            <div class="cost-row">
              <span>Azure TTS</span><span class="cost-amt">$6.83</span>
            </div>
            <div class="cost-row">
              <span>Misc</span><span class="cost-amt">$2.44</span>
            </div>
          </div>
        </div>

      </div>

      <!-- Footer note -->
      <div class="panel-footer">
        <span class="footer-dot"></span>
        数据每次任务完成后自动上报至 ClipFlow Engine DB
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════════════════ -->
    <!--  RIGHT HALF  –  GrowthOS 收益预期 (Locked)                      -->
    <!-- ═══════════════════════════════════════════════════════════════ -->
    <div class="dash-panel right-panel">

      <!-- Panel header -->
      <div class="panel-header">
        <span class="header-dot dot-violet"></span>
        <span class="panel-title">GrowthOS 收益预期</span>
        <span class="panel-subtitle">Projected Revenue Intelligence · v2.0</span>
      </div>

      <!-- Placeholder content blocks (dimmed behind overlay) -->
      <div class="growth-blocks">

        <!-- Block 1: 多账号矩阵分发 -->
        <div class="growth-block">
          <div class="block-header">
            <span class="block-icon">📡</span>
            <span>多账号矩阵分发</span>
            <span class="block-tag">Multi-Account Matrix</span>
          </div>
          <div class="bar-chart">
            <div v-for="(h, i) in [55, 72, 48, 88, 65, 93, 79]" :key="i"
                 class="bar-column">
              <div class="bar-fill" :style="{ height: h + '%', opacity: 0.4 + i*0.08 }"></div>
              <span class="bar-label">{{ ['一', '二', '三', '四', '五', '六', '日'][i] }}</span>
            </div>
          </div>
        </div>

        <!-- Block 2: TikTok / Reels 播放量趋势 -->
        <div class="growth-block">
          <div class="block-header">
            <span class="block-icon">📈</span>
            <span>TikTok / Reels 播放量</span>
            <span class="block-tag">Views Trend</span>
          </div>
          <svg class="area-chart" viewBox="0 0 300 80" preserveAspectRatio="none">
            <defs>
              <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#a78bfa" stop-opacity="0.5"/>
                <stop offset="100%" stop-color="#a78bfa" stop-opacity="0.02"/>
              </linearGradient>
            </defs>
            <path d="M0,70 L30,55 L60,62 L90,40 L120,30 L150,35 L180,18 L210,10 L240,15 L270,5 L300,2 L300,80 L0,80 Z"
                  fill="url(#areaGrad)"/>
            <path d="M0,70 L30,55 L60,62 L90,40 L120,30 L150,35 L180,18 L210,10 L240,15 L270,5 L300,2"
                  fill="none" stroke="#a78bfa" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
          <div class="chart-labels">
            <span v-for="l in ['W1','W2','W3','W4','W5','W6','W7','W8','W9','W10']" :key="l" class="chart-lbl">{{ l }}</span>
          </div>
        </div>

        <!-- Block 3: 互动率转化漏斗 -->
        <div class="growth-block">
          <div class="block-header">
            <span class="block-icon">🔽</span>
            <span>互动率转化漏斗</span>
            <span class="block-tag">Engagement Funnel</span>
          </div>
          <div class="funnel">
            <div v-for="(row, i) in [
              { label: '曝光 Impressions', pct: 100, color: '#22d3ee' },
              { label: '点击 Click-thru',  pct: 68,  color: '#818cf8' },
              { label: '互动 Engagement',  pct: 34,  color: '#a78bfa' },
              { label: '转化 Conversion',  pct: 12,  color: '#f59e0b' },
            ]" :key="i" class="funnel-row">
              <span class="funnel-label">{{ row.label }}</span>
              <div class="funnel-bar-bg">
                <div class="funnel-bar-fill" :style="{ width: row.pct + '%', background: row.color }"></div>
              </div>
              <span class="funnel-pct">{{ row.pct }}%</span>
            </div>
          </div>
        </div>

      </div>

      <!-- ████  FROSTED GLASS LOCK OVERLAY  ████ -->
      <div class="lock-overlay">
        <div class="lock-content">
          <div class="lock-glow-ring">
            <svg class="lock-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round"
                d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"/>
            </svg>
          </div>
          <div class="lock-title">MatrixBrain 中枢分析系统</div>
          <div class="lock-subtitle">未接入</div>
          <div class="lock-divider"></div>
          <div class="lock-message">
            敬请期待 <span class="version-badge">v2.0</span><br>
            自动排期与数据回流
          </div>
          <div class="lock-chips">
            <span class="chip">🔗 数据回流</span>
            <span class="chip">📅 自动排期</span>
            <span class="chip">🤖 AI 分析</span>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
/* ── Layout ─────────────────────────────────────────────── */
.dashboard-root {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.25rem;
  min-height: 0;
  flex: 1;
}

@media (max-width: 1024px) {
  .dashboard-root { grid-template-columns: 1fr; }
}

/* ── Panel base ─────────────────────────────────────────── */
.dash-panel {
  background: rgba(15, 20, 35, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 1rem;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  position: relative;
  overflow: hidden;
}

.dash-panel::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 1rem;
  pointer-events: none;
  background: radial-gradient(ellipse at top left, rgba(34, 211, 238, 0.04) 0%, transparent 60%);
}

.right-panel::before {
  background: radial-gradient(ellipse at top right, rgba(167, 139, 250, 0.05) 0%, transparent 60%);
}

/* ── Panel header ───────────────────────────────────────── */
.panel-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  padding-bottom: 0.75rem;
  flex-wrap: wrap;
}

.header-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-cyan   { background: #22d3ee; box-shadow: 0 0 8px #22d3ee; }
.dot-violet { background: #a78bfa; box-shadow: 0 0 8px #a78bfa; }

.panel-title {
  font-size: 0.875rem;
  font-weight: 800;
  color: #e2e8f0;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.panel-subtitle {
  font-size: 0.65rem;
  color: #475569;
  margin-left: auto;
  letter-spacing: 0.03em;
}

/* ── Stat grid ──────────────────────────────────────────── */
.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  flex: 1;
}

.stat-card {
  background: rgba(8, 12, 25, 0.6);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 0.75rem;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  position: relative;
  overflow: hidden;
  transition: border-color 0.2s;
}
.stat-card:hover { border-color: rgba(34, 211, 238, 0.25); }

.stat-card-wide {
  grid-column: span 2;
  flex-direction: row;
  align-items: flex-start;
  gap: 1rem;
}

.stat-icon {
  font-size: 1.5rem;
  line-height: 1;
  flex-shrink: 0;
}

.stat-body { flex: 1; min-width: 0; }

.stat-value {
  font-size: 2rem;
  font-weight: 900;
  color: #f1f5f9;
  line-height: 1;
  letter-spacing: -0.02em;
}
.stat-mono { font-family: 'Fira Mono', 'Courier New', monospace; font-size: 1.5rem; }

.stat-label {
  font-size: 0.7rem;
  color: #94a3b8;
  margin-top: 0.25rem;
  font-weight: 600;
}
.stat-sub {
  font-size: 0.6rem;
  color: #475569;
  margin-top: 0.1rem;
}

/* Sparkline */
.sparkline {
  width: 100%;
  height: 32px;
  margin-top: auto;
  opacity: 0.7;
}

/* Live badge */
.live-badge {
  font-size: 0.55rem;
  font-weight: 800;
  color: #4ade80;
  background: rgba(74, 222, 128, 0.12);
  border: 1px solid rgba(74, 222, 128, 0.3);
  border-radius: 0.3rem;
  padding: 0.15rem 0.4rem;
  letter-spacing: 0.1em;
  align-self: flex-start;
  flex-shrink: 0;
  animation: blink 1.8s ease-in-out infinite;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.4} }

/* Cost card */
.cost-value { color: #fbbf24; }
.cost-breakdown {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  min-width: 130px;
  background: rgba(251, 191, 36, 0.05);
  border: 1px solid rgba(251, 191, 36, 0.15);
  border-radius: 0.5rem;
  padding: 0.5rem 0.75rem;
  align-self: center;
}
.cost-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.6rem;
  color: #94a3b8;
}
.cost-amt { color: #fbbf24; font-weight: 700; font-family: monospace; }

/* Stat icon colours */
.icon-cyan   { filter: drop-shadow(0 0 6px rgba(34,211,238,0.5)); }
.icon-violet { filter: drop-shadow(0 0 6px rgba(167,139,250,0.5)); }
.icon-emerald{ filter: drop-shadow(0 0 6px rgba(52,211,153,0.5)); }
.icon-amber  { filter: drop-shadow(0 0 6px rgba(251,191,36,0.5)); }

/* ── Panel footer ───────────────────────────────────────── */
.panel-footer {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.6rem;
  color: #334155;
  border-top: 1px solid rgba(255,255,255,0.04);
  padding-top: 0.5rem;
}
.footer-dot {
  width: 5px; height: 5px;
  border-radius: 50%;
  background: #22d3ee;
  box-shadow: 0 0 5px #22d3ee;
  animation: blink 2s infinite;
}

/* ── Growth blocks (placeholder content) ───────────────── */
.growth-blocks {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  flex: 1;
}

.growth-block {
  background: rgba(8, 12, 25, 0.5);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 0.75rem;
  padding: 0.9rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.block-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.7rem;
  font-weight: 700;
  color: #94a3b8;
}
.block-icon { font-size: 0.9rem; }
.block-tag {
  margin-left: auto;
  font-size: 0.55rem;
  background: rgba(167,139,250,0.1);
  border: 1px solid rgba(167,139,250,0.25);
  color: #a78bfa;
  border-radius: 0.25rem;
  padding: 0.1rem 0.4rem;
}

/* Bar chart */
.bar-chart {
  display: flex;
  align-items: flex-end;
  gap: 0.35rem;
  height: 48px;
}
.bar-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.2rem;
  height: 100%;
  justify-content: flex-end;
}
.bar-fill {
  width: 100%;
  background: linear-gradient(to top, #a78bfa, #22d3ee);
  border-radius: 0.2rem 0.2rem 0 0;
}
.bar-label { font-size: 0.5rem; color: #475569; }

/* Area chart */
.area-chart { width: 100%; height: 60px; }
.chart-labels {
  display: flex;
  justify-content: space-between;
}
.chart-lbl { font-size: 0.5rem; color: #334155; }

/* Funnel */
.funnel { display: flex; flex-direction: column; gap: 0.35rem; }
.funnel-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.funnel-label {
  font-size: 0.58rem;
  color: #475569;
  width: 100px;
  flex-shrink: 0;
}
.funnel-bar-bg {
  flex: 1;
  height: 6px;
  background: rgba(255,255,255,0.05);
  border-radius: 3px;
  overflow: hidden;
}
.funnel-bar-fill {
  height: 100%;
  border-radius: 3px;
  opacity: 0.5;
}
.funnel-pct {
  font-size: 0.58rem;
  font-weight: 700;
  color: #64748b;
  width: 28px;
  text-align: right;
}

/* ══════════════════════════════════════════════════════════
   FROSTED GLASS LOCK OVERLAY
══════════════════════════════════════════════════════════ */
.lock-overlay {
  position: absolute;
  inset: 0;
  border-radius: 1rem;
  backdrop-filter: blur(14px) saturate(120%);
  -webkit-backdrop-filter: blur(14px) saturate(120%);
  background: rgba(5, 8, 20, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
}

.lock-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.65rem;
  text-align: center;
  padding: 1.5rem;
}

/* Glowing ring around lock */
.lock-glow-ring {
  width: 72px; height: 72px;
  border-radius: 50%;
  border: 2px solid rgba(167, 139, 250, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(circle, rgba(167,139,250,0.15) 0%, transparent 70%);
  box-shadow:
    0 0 20px rgba(167,139,250,0.35),
    0 0 60px rgba(167,139,250,0.15),
    inset 0 0 20px rgba(167,139,250,0.08);
  animation: pulse-ring 2.5s ease-in-out infinite;
}
@keyframes pulse-ring {
  0%,100% { box-shadow: 0 0 20px rgba(167,139,250,0.35), 0 0 60px rgba(167,139,250,0.15); }
  50%      { box-shadow: 0 0 30px rgba(167,139,250,0.6),  0 0 80px rgba(167,139,250,0.25); }
}

.lock-icon {
  width: 32px; height: 32px;
  color: #a78bfa;
  filter: drop-shadow(0 0 10px rgba(167,139,250,0.9));
}

.lock-title {
  font-size: 1rem;
  font-weight: 900;
  color: #e2e8f0;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.lock-subtitle {
  font-size: 0.7rem;
  font-weight: 700;
  color: #f87171;
  letter-spacing: 0.15em;
  text-transform: uppercase;
}

.lock-divider {
  width: 60px;
  height: 1px;
  background: linear-gradient(to right, transparent, rgba(167,139,250,0.5), transparent);
}

.lock-message {
  font-size: 0.78rem;
  color: #94a3b8;
  line-height: 1.7;
}
.version-badge {
  background: linear-gradient(135deg, #a78bfa, #22d3ee);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-weight: 900;
}

.lock-chips {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 0.25rem;
}
.chip {
  font-size: 0.6rem;
  font-weight: 600;
  color: #94a3b8;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 2rem;
  padding: 0.25rem 0.65rem;
  letter-spacing: 0.04em;
}
</style>
