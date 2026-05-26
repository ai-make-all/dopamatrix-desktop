<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { getTagPillParts } from '../utils/tagParser.js'

const props = defineProps({
  item:    { type: Object, required: true },
  apiBase: { type: String, required: true },
})

const emit = defineEmits(['open-tag-modal'])

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

      <!-- 标签注入按钮 -->
      <button
        class="audio-inject-tag-btn"
        @click.stop="emit('open-tag-modal', item)"
        title="注入分面标签"
      >🏷️ 注入标签</button>

      <!-- 分面标签胶囊 -->
      <div class="asset-card-tags">
        <span v-if="item.is_exhausted" class="tag-pill tag-pill-danger tag-pill--mini">疲劳警告</span>
        <span v-else-if="item.usage_count === 0" class="tag-pill tag-pill-fresh tag-pill--mini">全新</span>
        <template v-if="item.tags && item.tags.length">
          <span
            v-for="pill in item.tags.map(getTagPillParts)"
            :key="pill.val"
            :class="['tag-pill', pill.facetClass, 'tag-pill--mini']"
          >
            <span v-if="pill.showHead" class="tag-pill-head">{{ pill.head }}</span>
            <span v-if="pill.showHead" class="tag-pill-sep"> | </span>
            <span class="tag-pill-val">{{ pill.val }}</span>
          </span>
        </template>
        <span v-if="!item.tags?.length && !item.is_exhausted && item.usage_count > 0" class="audio-no-tags">— 未打标</span>
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
/* ── 标签注入按钮 ─────────────────────────────────────────── */
.audio-inject-tag-btn {
  width: 100%;
  padding: 0.32rem 0.55rem;
  border-radius: 7px;
  border: 1px dashed rgba(139, 92, 246, 0.4);
  background: rgba(139, 92, 246, 0.06);
  color: rgba(196, 181, 253, 0.7);
  font-size: 0.7rem;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  letter-spacing: 0.02em;
  transition: border-color 0.15s, color 0.15s, background 0.15s, box-shadow 0.15s;
  text-align: center;
  margin-top: 0.3rem;
}
.audio-inject-tag-btn:hover {
  border-color: rgba(167, 139, 250, 0.75);
  color: #c4b5fd;
  background: rgba(139, 92, 246, 0.13);
  box-shadow: 0 0 12px rgba(139, 92, 246, 0.2);
  border-style: solid;
}

/* ── 分面标签胶囊容器 ─────────────────────────────────────── */
.asset-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.2rem;
  overflow: hidden;
  margin-top: 0.25rem;
  min-height: 1rem;
}
.audio-no-tags {
  font-size: 0.6rem;
  color: #1e293b;
  font-style: italic;
  align-self: center;
}
</style>
