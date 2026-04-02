<script setup>
import { ref, computed, onUnmounted } from 'vue'

const props = defineProps({
  item:    { type: Object, required: true },
  apiBase: { type: String, required: true },
})

const emit = defineEmits(['emotion-change'])

// ── Playback ───────────────────────────────────────────────────────────────
const isPlaying = ref(false)
let audioInstance = null

const audioSrc = computed(() =>
  `${props.apiBase}/api/v1/assets/stream?path=${encodeURIComponent(props.item.file_path)}`
)

function togglePlay() {
  if (!audioInstance) {
    audioInstance = new Audio(audioSrc.value)
    audioInstance.addEventListener('ended', () => { isPlaying.value = false })
    audioInstance.addEventListener('error', () => {
      isPlaying.value = false
      audioInstance = null
    })
  }
  if (isPlaying.value) {
    audioInstance.pause()
    isPlaying.value = false
  } else {
    audioInstance.play().catch(() => { isPlaying.value = false })
    isPlaying.value = true
  }
}

onUnmounted(() => {
  if (audioInstance) { audioInstance.pause(); audioInstance = null }
})

// ── Fatigue bar ────────────────────────────────────────────────────────────
const healthWidth = computed(() => {
  if (props.item.is_exhausted)       return '100%'
  if (props.item.usage_count === 0)  return '100%'
  return Math.max(10, 100 - props.item.usage_count * 10) + '%'
})

const healthColor = computed(() => {
  if (props.item.is_exhausted)       return '#f87171'
  if (props.item.usage_count === 0)  return '#4ade80'
  return '#fbbf24'
})

// ── Waveform bar heights (deterministic pseudo-random from filename) ────────
const BAR_COUNT = 32
const waveHeights = computed(() => {
  const seed = props.item.file_path?.length ?? 20
  return Array.from({ length: BAR_COUNT }, (_, i) => {
    const h = 18 + Math.abs(Math.sin(i * 0.9 + seed * 0.03) * Math.cos(i * 0.4)) * 64
    return Math.round(h)
  })
})

const emotionColorMap = {
  asmr:    '#34d399',
  epic:    '#f472b6',
  funny:   '#fbbf24',
  general: '#38bdf8',
}
const vibeAccent = computed(() => emotionColorMap[props.item.emotion_tag] ?? '#a78bfa')
</script>

<template>
  <div class="audio-card" :style="{ '--vibe': vibeAccent }">

    <!-- ── Waveform + Play zone ── -->
    <div class="audio-waveform-bg">
      <!-- Animated waveform bars -->
      <div class="waveform-bars" aria-hidden="true">
        <span
          v-for="(h, i) in waveHeights"
          :key="i"
          class="waveform-bar"
          :class="{ 'waveform-bar--active': isPlaying }"
          :style="{
            height: h + '%',
            animationDelay: (i * 0.055).toFixed(3) + 's',
            animationDuration: (0.8 + (i % 5) * 0.12).toFixed(2) + 's',
          }"
        ></span>
      </div>

      <!-- Play / Pause button -->
      <button
        class="audio-play-btn"
        :class="{ 'audio-play-btn--playing': isPlaying }"
        @click="togglePlay"
        :title="isPlaying ? '暂停试听' : '▶ 试听'"
      >
        <svg v-if="isPlaying" width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
          <rect x="6" y="4" width="4" height="16" rx="1"/>
          <rect x="14" y="4" width="4" height="16" rx="1"/>
        </svg>
        <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
          <path d="M8 5v14l11-7L8 5z"/>
        </svg>
      </button>

      <!-- Usage badge -->
      <div class="audio-badge-wrap">
        <span class="badge-ref">引用: {{ item.usage_count }}次</span>
      </div>

      <!-- Playing pulse ring -->
      <div v-if="isPlaying" class="audio-pulse-ring"></div>
    </div>

    <!-- ── Info section ── -->
    <div class="asset-info">
      <div class="asset-name" :title="item.file_path">
        {{ item.file_path.split(/[/\\]/).pop() }}
      </div>

      <!-- Fatigue bar -->
      <div class="asset-health" title="健康度 (疲劳度)">
        <div
          class="health-bar"
          :style="{ width: healthWidth, background: healthColor }"
        ></div>
      </div>

      <!-- Emotion tag dropdown -->
      <div class="asset-role-wrap" style="margin-top: 0.4rem; margin-bottom: 0.2rem;">
        <select
          v-model="item.emotion_tag"
          @change="emit('emotion-change', item)"
          class="role-select role-audio-emotion"
          :style="{ borderColor: `color-mix(in srgb, var(--vibe) 50%, transparent)` }"
        >
          <option value="asmr">🎧 ASMR / 沉浸解压</option>
          <option value="epic">💥 史诗震撼 / 强节奏</option>
          <option value="funny">🤪 荒诞鬼畜 / 模因音效</option>
          <option value="general">🎵 通用音乐 (General)</option>
        </select>
      </div>

      <!-- Tags -->
      <div class="asset-tags">
        <span
          v-if="item.is_exhausted"
          class="tag"
          style="background:rgba(239,68,68,0.15);color:#fca5a5;border-color:rgba(239,68,68,0.3);"
        >疲劳警告</span>
        <span v-else-if="item.usage_count === 0" class="tag">全新</span>
        <span v-if="item.emotion_tag" class="tag audio-vibe-tag">{{ item.emotion_tag }}</span>
      </div>
    </div>

  </div>
</template>

<style scoped>
.audio-card {
  background: rgba(10, 8, 28, 0.75);
  border: 1px solid rgba(139, 92, 246, 0.2);
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: all .22s ease;
}
.audio-card:hover {
  transform: translateY(-4px);
  border-color: color-mix(in srgb, var(--vibe) 60%, transparent);
  box-shadow: 0 12px 28px rgba(0,0,0,0.45), 0 0 22px color-mix(in srgb, var(--vibe) 30%, transparent);
}

/* ── Waveform background ── */
.audio-waveform-bg {
  height: 110px;
  background:
    radial-gradient(ellipse at 50% 110%, color-mix(in srgb, var(--vibe) 18%, transparent) 0%, transparent 70%),
    linear-gradient(180deg, rgba(5,3,20,0.98) 0%, rgba(12,8,40,0.92) 100%);
  border-bottom: 1px solid rgba(139,92,246,0.12);
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ── Waveform bars ── */
.waveform-bars {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2.5px;
  padding: 0 10px;
}
.waveform-bar {
  flex: 1;
  max-width: 5px;
  min-height: 3px;
  border-radius: 2px;
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--vibe) 80%, #fff) 0%,
    color-mix(in srgb, var(--vibe) 40%, transparent) 100%
  );
  opacity: 0.28;
  transform-origin: center;
  transition: opacity .3s;
}
.waveform-bar--active {
  opacity: 0.7;
  animation: waveform-dance var(--dur, 0.9s) ease-in-out infinite alternate;
}
@keyframes waveform-dance {
  from { transform: scaleY(0.35); }
  to   { transform: scaleY(1); }
}

/* ── Play / Pause button ── */
.audio-play-btn {
  position: relative;
  z-index: 2;
  width: 46px; height: 46px;
  border-radius: 50%;
  background: rgba(139, 92, 246, 0.18);
  border: 1.5px solid rgba(167,139,250,0.4);
  color: #c4b5fd;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all .2s;
  box-shadow: 0 0 14px rgba(139,92,246,0.25);
}
.audio-play-btn:hover {
  background: rgba(139,92,246,0.38);
  border-color: rgba(167,139,250,0.75);
  box-shadow: 0 0 26px rgba(139,92,246,0.5);
  transform: scale(1.1);
}
.audio-play-btn--playing {
  background: color-mix(in srgb, var(--vibe) 25%, transparent) !important;
  border-color: color-mix(in srgb, var(--vibe) 70%, transparent) !important;
  color: var(--vibe) !important;
  box-shadow: 0 0 22px color-mix(in srgb, var(--vibe) 45%, transparent) !important;
}

/* ── Usage badge ── */
.audio-badge-wrap {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  z-index: 2;
}
.badge-ref {
  background: rgba(0,0,0,0.65);
  backdrop-filter: blur(4px);
  color: #cbd5e1;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.63rem;
  padding: 0.2rem 0.5rem;
  border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.1);
}

/* ── Playing pulse ring ── */
.audio-pulse-ring {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  animation: pulse-border 1.8s ease-out infinite;
  pointer-events: none;
}
@keyframes pulse-border {
  0%   { box-shadow: 0 0 0 0   color-mix(in srgb, var(--vibe) 50%, transparent); }
  70%  { box-shadow: 0 0 0 14px color-mix(in srgb, var(--vibe) 0%, transparent); }
  100% { box-shadow: 0 0 0 0   color-mix(in srgb, var(--vibe) 0%, transparent); }
}

/* ── Reuse parent global styles for info area ── */
.asset-info {
  padding: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.asset-name {
  color: #e2e8f0;
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: 'Inter', sans-serif;
}
.asset-health {
  height: 5px;
  background: rgba(255,255,255,0.07);
  border-radius: 99px;
  overflow: hidden;
}
.health-bar {
  height: 100%;
  border-radius: 99px;
  transition: width .3s ease;
}
.asset-role-wrap {}
.role-select {
  background: rgba(10, 8, 28, 0.9);
  border: 1px solid rgba(255,255,255,0.1);
  color: #94a3b8;
  font-size: 0.72rem;
  padding: 0.22rem 0.4rem;
  border-radius: 6px;
  width: 100%;
  outline: none;
  cursor: pointer;
  transition: border-color .18s;
}
.role-select:focus { border-color: rgba(167,139,250,0.5); }
.role-select option { background: #0a0820; color: #e2e8f0; }
.role-audio-emotion { color: #c4b5fd; }

.asset-tags {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.tag {
  background: rgba(56,189,248,0.1);
  color: #38bdf8;
  border: 1px solid rgba(56,189,248,0.25);
  font-size: 0.63rem;
  padding: 0.12rem 0.4rem;
  border-radius: 4px;
}
.audio-vibe-tag {
  background: color-mix(in srgb, var(--vibe) 12%, transparent);
  color: var(--vibe);
  border-color: color-mix(in srgb, var(--vibe) 35%, transparent);
  font-family: 'JetBrains Mono', monospace;
  text-transform: uppercase;
  letter-spacing: .04em;
}
</style>
