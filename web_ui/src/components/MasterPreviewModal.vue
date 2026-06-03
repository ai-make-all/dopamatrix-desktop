<script setup lang="ts">
/**
 * MasterPreviewModal.vue — 沉浸式资产初筛工作台
 *
 * 功能：
 *  - 全屏遮罩 + 居中 9:16 播放器
 *  - 任务内资产上一个 / 下一个无缝切换
 *  - 状态机操作栏：废弃 / 已审 / 微调（微调触发 open-detail 事件，禁止路由跳转）
 */

import { ref, computed, watch } from 'vue'
import { useAppStore } from '../stores/appStore'
import type { QueueTask } from '../stores/useQueueStore'

const props = defineProps<{
  task:         QueueTask
  initialIndex: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'open-detail', hash: string): void
}>()

const store = useAppStore()

// ── 当前预览索引 ──────────────────────────────────────────────────────────
const currentIdx = ref(props.initialIndex)

// 确保索引合法
watch(() => props.initialIndex, (v) => { currentIdx.value = v }, { immediate: true })

const assets = computed(() => props.task.assets ?? [])

const currentAsset = computed(() => assets.value[currentIdx.value] ?? null)
const hasPrev      = computed(() => currentIdx.value > 0)
const hasNext      = computed(() => currentIdx.value < assets.value.length - 1)

const videoUrl = computed(() =>
  currentAsset.value ? store.buildVideoUrl(currentAsset.value.file_path) : ''
)

function prev() { if (hasPrev.value) currentIdx.value-- }
function next() { if (hasNext.value) currentIdx.value++ }

// ── 状态机 ───────────────────────────────────────────────────────────────
// 每个资产的状态独立存储（hash → status）
type AssetStatus = 'none' | 'discarded' | 'approved' | 'fine-tune'
const assetStatusMap = ref<Map<string, AssetStatus>>(new Map())

function getStatus(hash: string | undefined): AssetStatus {
  return hash ? (assetStatusMap.value.get(hash) ?? 'none') : 'none'
}

function setStatus(status: AssetStatus) {
  const hash = currentAsset.value?.file_hash
  if (!hash) return
  assetStatusMap.value.set(hash, status)
}

const currentStatus = computed(() => getStatus(currentAsset.value?.file_hash))

function doDiscard()  { setStatus('discarded') }
function doApprove()  { setStatus('approved')  }
function doFineTune() {
  const hash = currentAsset.value?.file_hash
  if (!hash) return
  setStatus('fine-tune')
  emit('open-detail', hash)
}

// ── 键盘快捷键 ───────────────────────────────────────────────────────────
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape')      { emit('close') }
  else if (e.key === 'ArrowLeft')  { prev() }
  else if (e.key === 'ArrowRight') { next() }
}
// 挂载时注册
import { onMounted, onUnmounted } from 'vue'
onMounted(()   => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop" @click.self="emit('close')">

      <!-- 关闭按钮 -->
      <button class="modal-close" @click="emit('close')" aria-label="关闭">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>

      <!-- 进度角标 -->
      <div class="modal-counter">
        {{ currentIdx + 1 }} / {{ assets.length }}
      </div>

      <!-- 左切换 -->
      <button
        class="nav-btn nav-btn--left"
        :disabled="!hasPrev"
        @click="prev"
        aria-label="上一个"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"/>
        </svg>
      </button>

      <!-- 中心播放器 -->
      <div class="modal-player-wrap">
        <!-- 状态覆盖层 -->
        <Transition name="status-overlay">
          <div
            v-if="currentStatus !== 'none'"
            :class="['status-overlay', `status-overlay--${currentStatus}`]"
          >
            <span class="status-overlay-icon">
              {{ currentStatus === 'discarded' ? '🗑️' : currentStatus === 'approved' ? '✅' : '🛠️' }}
            </span>
            <span class="status-overlay-text">
              {{ currentStatus === 'discarded' ? '已废弃' : currentStatus === 'approved' ? '已审核' : '微调中' }}
            </span>
          </div>
        </Transition>

        <div class="player-frame">
          <video
            v-if="videoUrl"
            :key="videoUrl"
            :src="videoUrl"
            class="player-video"
            controls
            autoplay
            playsinline
            preload="metadata"
          />
          <div v-else class="player-placeholder">
            <div class="placeholder-icon">▶</div>
            <div class="placeholder-text">视频加载中…</div>
          </div>
          <div class="scanline" />
        </div>

        <!-- hash 信息 -->
        <div class="asset-info">
          <span class="asset-hash">{{ currentAsset?.file_hash ?? '' }}</span>
          <span class="asset-index">第 {{ currentIdx + 1 }} 个 · 共 {{ assets.length }} 个</span>
        </div>
      </div>

      <!-- 右切换 -->
      <button
        class="nav-btn nav-btn--right"
        :disabled="!hasNext"
        @click="next"
        aria-label="下一个"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 18 15 12 9 6"/>
        </svg>
      </button>

      <!-- 操作栏 -->
      <div class="action-bar">
        <button
          :class="['action-btn', 'action-btn--discard', { 'action-btn--active': currentStatus === 'discarded' }]"
          @click="doDiscard"
        >
          <span>🗑️</span>
          <span>废弃</span>
        </button>
        <button
          :class="['action-btn', 'action-btn--approve', { 'action-btn--active': currentStatus === 'approved' }]"
          @click="doApprove"
        >
          <span>✅</span>
          <span>已审</span>
        </button>
        <button
          :class="['action-btn', 'action-btn--finetune', { 'action-btn--active': currentStatus === 'fine-tune' }]"
          @click="doFineTune"
        >
          <span>🛠️</span>
          <span>微调</span>
        </button>
      </div>

      <!-- 缩略图条 -->
      <div v-if="assets.length > 1" class="thumbnail-strip">
        <div
          v-for="(asset, idx) in assets"
          :key="asset.file_hash || idx"
          :class="['strip-cell', { 'strip-cell--active': idx === currentIdx }]"
          @click="currentIdx = idx"
        >
          <img
            v-if="asset.cover_path"
            :src="store.buildVideoUrl(asset.cover_path)"
            :alt="`缩略图 ${idx + 1}`"
            class="strip-thumb"
            loading="lazy"
          />
          <div v-else class="strip-thumb-placeholder" />
          <span
            v-if="getStatus(asset.file_hash) !== 'none'"
            :class="['strip-status', `strip-status--${getStatus(asset.file_hash)}`]"
          >
            {{ getStatus(asset.file_hash) === 'discarded' ? '🗑️' : getStatus(asset.file_hash) === 'approved' ? '✅' : '🛠️' }}
          </span>
        </div>
      </div>

    </div>
  </Teleport>
</template>

<style scoped>
/* ── Backdrop ────────────────────────────────────────────────────────────── */
.modal-backdrop {
  position:   fixed;
  inset:      0;
  z-index:    9000;
  background: rgba(2, 6, 20, 0.92);
  backdrop-filter: blur(8px);
  display:    flex;
  align-items: center;
  justify-content: center;
  gap:        2rem;
  animation:  fade-in 0.18s ease;
}
@keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }

/* ── Close & Counter ─────────────────────────────────────────────────────── */
.modal-close {
  position:   absolute;
  top:        1rem;
  right:      1rem;
  width:      36px;
  height:     36px;
  border:     1px solid rgba(148, 163, 184, 0.2);
  background: rgba(15, 23, 42, 0.8);
  color:      #94a3b8;
  border-radius: 8px;
  cursor:     pointer;
  display:    flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.15s, color 0.15s;
  z-index:    1;
}
.modal-close:hover { border-color: #f87171; color: #f87171; }

.modal-counter {
  position:   absolute;
  top:        1.1rem;
  left:       50%;
  transform:  translateX(-50%);
  font-size:  0.72rem;
  color:      #64748b;
  font-family: 'Courier New', monospace;
  pointer-events: none;
}

/* ── Nav buttons ─────────────────────────────────────────────────────────── */
.nav-btn {
  flex-shrink: 0;
  width:       52px;
  height:      52px;
  border:      1px solid rgba(99, 102, 241, 0.35);
  background:  rgba(30, 41, 59, 0.7);
  color:       #94a3b8;
  border-radius: 50%;
  cursor:      pointer;
  display:     flex;
  align-items: center;
  justify-content: center;
  transition:  border-color 0.15s, color 0.15s, background 0.15s, transform 0.12s;
}
.nav-btn:hover:not(:disabled) {
  border-color: #a78bfa;
  color:        #a78bfa;
  background:   rgba(167, 139, 250, 0.12);
  transform:    scale(1.07);
}
.nav-btn:disabled { opacity: 0.2; cursor: not-allowed; }

/* ── Player wrap ─────────────────────────────────────────────────────────── */
.modal-player-wrap {
  display:        flex;
  flex-direction: column;
  align-items:    center;
  gap:            0.6rem;
  position:       relative;
}
.player-frame {
  position:     relative;
  width:        min(45vh, 300px);
  aspect-ratio: 9 / 16;
  background:   #000;
  border-radius: 14px;
  border:       1px solid rgba(56, 189, 248, 0.25);
  overflow:     hidden;
  box-shadow:   0 0 40px rgba(56, 189, 248, 0.1), 0 20px 60px rgba(0,0,0,0.5);
}
.player-video {
  width: 100%; height: 100%; object-fit: contain; display: block; background: #000;
}
.player-placeholder {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; height: 100%; gap: 8px;
}
.placeholder-icon { font-size: 2rem; color: rgba(56, 189, 248, 0.35); }
.placeholder-text { font-size: 0.72rem; color: #475569; }
.scanline {
  position: absolute; inset: 0; pointer-events: none;
  background: repeating-linear-gradient(0deg, transparent, transparent 2px,
    rgba(255,255,255,0.012) 2px, rgba(255,255,255,0.012) 4px);
}

/* ── Status overlay ──────────────────────────────────────────────────────── */
.status-overlay {
  position:   absolute;
  inset:      0;
  z-index:    5;
  display:    flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap:        0.5rem;
  border-radius: 12px;
  pointer-events: none;
}
.status-overlay--discarded { background: rgba(248, 113, 113, 0.25); }
.status-overlay--approved  { background: rgba(74, 222, 128, 0.2);  }
.status-overlay--fine-tune { background: rgba(167, 139, 250, 0.2); }
.status-overlay-icon { font-size: 2.5rem; }
.status-overlay-text { font-size: 0.85rem; font-weight: 700; color: #fff; letter-spacing: 0.06em; }
.status-overlay-enter-active, .status-overlay-leave-active { transition: opacity 0.2s; }
.status-overlay-enter-from, .status-overlay-leave-to { opacity: 0; }

/* ── Asset info ──────────────────────────────────────────────────────────── */
.asset-info {
  display:     flex;
  align-items: center;
  gap:         0.75rem;
}
.asset-hash {
  font-size:   0.65rem;
  font-family: monospace;
  color:       #475569;
}
.asset-index {
  font-size:   0.65rem;
  color:       #475569;
}

/* ── Action bar ──────────────────────────────────────────────────────────── */
.action-bar {
  position:   absolute;
  bottom:     5.5rem;
  left:       50%;
  transform:  translateX(-50%);
  display:    flex;
  gap:        0.75rem;
}
.action-btn {
  display:     flex;
  flex-direction: column;
  align-items: center;
  gap:         0.2rem;
  padding:     0.55rem 1.1rem;
  border-radius: 10px;
  border:      1px solid transparent;
  background:  rgba(30, 41, 59, 0.8);
  color:       #94a3b8;
  font-size:   0.72rem;
  font-weight: 600;
  cursor:      pointer;
  transition:  border-color 0.15s, background 0.15s, color 0.15s, transform 0.12s;
  letter-spacing: 0.02em;
  min-width:   64px;
}
.action-btn:hover { transform: translateY(-2px); }
.action-btn--discard:hover, .action-btn--discard.action-btn--active {
  border-color: #f87171;
  background:   rgba(248, 113, 113, 0.15);
  color:        #f87171;
}
.action-btn--approve:hover, .action-btn--approve.action-btn--active {
  border-color: #4ade80;
  background:   rgba(74, 222, 128, 0.15);
  color:        #4ade80;
}
.action-btn--finetune:hover, .action-btn--finetune.action-btn--active {
  border-color: #a78bfa;
  background:   rgba(167, 139, 250, 0.15);
  color:        #a78bfa;
}
.action-btn span:first-child { font-size: 1.1rem; }

/* ── Thumbnail strip ─────────────────────────────────────────────────────── */
.thumbnail-strip {
  position:   absolute;
  bottom:     1rem;
  left:       50%;
  transform:  translateX(-50%);
  display:    flex;
  gap:        0.35rem;
  max-width:  90vw;
  overflow-x: auto;
  padding:    0.25rem;
  scrollbar-width: none;
}
.thumbnail-strip::-webkit-scrollbar { display: none; }

.strip-cell {
  position:     relative;
  width:        48px;
  height:       48px;
  flex-shrink:  0;
  border-radius: 6px;
  border:       2px solid transparent;
  overflow:     hidden;
  cursor:       pointer;
  transition:   border-color 0.15s, transform 0.12s;
  background:   #000;
}
.strip-cell:hover      { transform: scale(1.06); border-color: rgba(99, 102, 241, 0.5); }
.strip-cell--active    { border-color: #a78bfa; box-shadow: 0 0 8px rgba(167, 139, 250, 0.5); }
.strip-thumb { width: 100%; height: 100%; object-fit: cover; display: block; aspect-ratio: 1/1; }
.strip-thumb-placeholder {
  width: 100%; height: 100%;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
  display: flex; align-items: center; justify-content: center;
}

.strip-status {
  position:   absolute;
  top:        1px;
  right:      1px;
  font-size:  0.7rem;
  line-height: 1;
}
</style>
