<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  // ── 旧接口（ApprovalView 使用，保持向后兼容）────────────────────────────────
  item: {
    type: Object,
    default: null,
    // item: { id, task_id, prompt, created_at, duration, cover_url, video_url, hash }
  },
  status: {
    type: String,
    default: 'PENDING',  // 'PENDING' | 'APPROVED' | 'REJECTED'
  },
  loading: {
    type: Boolean,
    default: false,
  },

  // ── 新接口（QueueView 轮播图 / 灵活复用）────────────────────────────────────
  /**
   * variant 合并了 item + status 的信息，供轮播图等场景直接注入 WS 数据结构。
   * 优先级：variant > item + status
   */
  variant: {
    type: Object,
    default: null,
    // variant: { id, task_id, video_url, cover_url, status, prompt?, duration? }
  },

  /** 隐藏底部通过/毙掉操作区及信息区（用于轮播缩略图等纯展示场景）*/
  hideActions: {
    type: Boolean,
    default: false,
  },

  /** 封面比例（CSS aspect-ratio 格式：'w/h'），仅在非填充模式下生效 */
  aspectRatio: {
    type: String,
    default: '9/16',
  },
})

const emit = defineEmits(['approve', 'reject', 'preview'])

const imgError = ref(false)

function handleImgError() {
  imgError.value = true
}

// ── 统一数据源（variant 优先）────────────────────────────────────────────────
const effectiveItem = computed(() => {
  if (props.variant) {
    return {
      task_id:    props.variant.task_id || props.variant.id || '',
      cover_url:  props.variant.cover_url  || '',
      video_url:  props.variant.video_url  || '',
      hash:       props.variant.id         || '',
      prompt:     props.variant.prompt     || '',
      duration:   props.variant.duration   || null,
    }
  }
  return props.item || {}
})

const effectiveStatus = computed(() => {
  if (props.variant && props.variant.status) return props.variant.status
  return props.status
})

/**
 * 填充模式：hideActions=true 时，卡片拉伸填满父容器，
 * ratio-box 以 flex-grow 撑高而非 padding-top 撑开。
 */
const isFill = computed(() => props.hideActions)

/** ratio-box 的动态内联样式 */
const ratioBoxStyle = computed(() => {
  if (isFill.value) return {}          // 填充模式：CSS class 接管布局
  const parts = props.aspectRatio.split('/')
  const w = parseFloat(parts[0]) || 9
  const h = parseFloat(parts[1]) || 16
  return { paddingTop: `${(h / w) * 100}%` }
})

// ── 点击预览逻辑 ──────────────────────────────────────────────────────────────
function onPreview() {
  // 填充模式下 REJECTED 不阻断（轮播场景允许预览任何状态）
  if (!props.hideActions && effectiveStatus.value === 'REJECTED') return
  emit('preview', effectiveItem.value)
}

/** 缺料熔断：WebSocket 推送 status=failed 或 status=ASSET_MISSING 时触发 */
const isAssetMissing = computed(() => {
  const s = effectiveStatus.value
  return s === 'failed' || s === 'ASSET_MISSING'
})

// ── 卡片样式类 ────────────────────────────────────────────────────────────────
const cardClass = computed(() => ({
  'cover-card--approved':      effectiveStatus.value === 'APPROVED',
  'cover-card--rejected':      effectiveStatus.value === 'REJECTED' && !isFill.value,
  'cover-card--loading':       props.loading,
  'cover-card--fill':          isFill.value,
  'cover-card--asset-missing': isAssetMissing.value,
}))
</script>

<template>
  <div :class="['cover-card', cardClass]" @click.self="onPreview">

    <!-- ── 封面图区（动态比例容器）─────────────────────────────── -->
    <div
      :class="['cover-ratio-box', { 'cover-ratio-box--fill': isFill }]"
      :style="ratioBoxStyle"
      @click="onPreview"
    >
      <!-- ⚠️ 缺料熔断态：覆盖全部正常内容 -->
      <div v-if="isAssetMissing" class="cover-asset-missing">
        <div class="missing-icon-wrap">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
        </div>
        <span class="missing-label">缺素材拦截</span>
        <span class="missing-hint">主视觉视频未命中素材库</span>
      </div>

      <!-- 正常封面 / 占位（非缺料熔断时显示）-->
      <template v-else>
        <img
          v-if="effectiveItem.cover_url && !imgError"
          :src="effectiveItem.cover_url"
          :alt="`封面 - ${effectiveItem.task_id}`"
          class="cover-img"
          loading="lazy"
          @error="handleImgError"
        />
        <!-- 封面加载失败 / 无封面 → 优雅占位块（hover 仍可播放） -->
        <div v-else class="cover-placeholder">
          <div class="placeholder-icon-wrap">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="placeholder-film-icon">
              <rect x="2" y="2" width="20" height="20" rx="2.5"/>
              <path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 7h5M17 17h5"/>
            </svg>
          </div>
          <span class="placeholder-text">🎥 无封面</span>
          <span v-if="!isFill" class="placeholder-hint">（点击仍可审核播放）</span>
        </div>

        <!-- Hover 播放遮罩（缺料熔断时不渲染） -->
        <div
          v-if="!(effectiveStatus === 'REJECTED' && !isFill)"
          class="cover-hover-overlay"
        >
          <div class="play-icon-wrap">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="white">
              <circle cx="12" cy="12" r="11" fill="rgba(0,0,0,0.55)" />
              <polygon points="10,8 18,12 10,16" fill="white" />
            </svg>
          </div>
        </div>
      </template>

      <!-- ── 状态角标 ──────────────────────────────────────────── -->

      <!-- ❌ 缺料熔断角标 -->
      <div v-if="isAssetMissing" class="status-badge status-badge--missing">
        <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/>
        </svg>
        缺料拦截
      </div>

      <!-- 🟡 待审核角标（仅显示于 hideActions=true 的缩略图场景） -->
      <div v-if="effectiveStatus === 'PENDING' && isFill && !isAssetMissing" class="status-badge status-badge--pending">
        <svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="12" cy="12" r="10"/>
        </svg>
        待审
      </div>

      <!-- ✅ 已通过角标 -->
      <div v-if="effectiveStatus === 'APPROVED' && !isAssetMissing" class="status-badge status-badge--approved">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
        已通过
      </div>

      <!-- ✕ 已毙掉角标 -->
      <div v-if="effectiveStatus === 'REJECTED' && !isAssetMissing" class="status-badge status-badge--rejected">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
        已毙掉
      </div>

      <!-- 右上角时长标签（仅 PENDING 非填充态显示） -->
      <div v-if="effectiveStatus === 'PENDING' && effectiveItem.duration && !isFill" class="cover-duration-badge">
        {{ effectiveItem.duration }}s
      </div>

      <!-- 审批中 Loading 蒙层 -->
      <div v-if="loading" class="cover-loading-overlay">
        <div class="loading-spinner"></div>
      </div>
    </div>

    <!-- ── 信息区（hideActions=true 时隐藏）───────────────────── -->
    <div v-if="!hideActions" class="cover-info">
      <p class="cover-task-id" :title="effectiveItem.task_id">
        <span class="mono">#{{ (effectiveItem.task_id || '').slice(0, 8) }}</span>
      </p>
      <p class="cover-prompt" :title="effectiveItem.prompt">{{ effectiveItem.prompt }}</p>
    </div>

    <!-- ── 操作区（hideActions=true 或缺料熔断时隐藏）──────────── -->
    <div v-if="!hideActions && !isAssetMissing" class="cover-actions">
      <!-- PENDING 态：通过 / 毙掉 -->
      <template v-if="effectiveStatus === 'PENDING'">
        <button
          class="action-btn action-approve"
          :disabled="loading"
          @click.stop="emit('approve', effectiveItem)"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          通过
        </button>
        <button
          class="action-btn action-reject"
          :disabled="loading"
          @click.stop="emit('reject', effectiveItem)"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
          毙掉
        </button>
      </template>

      <!-- APPROVED 态：撤销按钮 -->
      <button
        v-else-if="effectiveStatus === 'APPROVED'"
        class="action-btn action-revoke"
        :disabled="loading"
        @click.stop="emit('reject', effectiveItem)"
      >
        ↩ 撤销通过
      </button>

      <!-- REJECTED 态：撤销按钮 -->
      <button
        v-else-if="effectiveStatus === 'REJECTED'"
        class="action-btn action-revoke-reject"
        :disabled="loading"
        @click.stop="emit('approve', effectiveItem)"
      >
        ↩ 撤销毙掉
      </button>
    </div>

  </div>
</template>

<style scoped>
.cover-card {
  display: flex;
  flex-direction: column;
  background: rgba(13, 18, 38, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 12px;
  overflow: hidden;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease, filter 0.25s ease;
  cursor: pointer;
}
.cover-card:hover {
  transform: translateY(-4px);
  border-color: rgba(139, 92, 246, 0.4);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.5), 0 0 18px rgba(139, 92, 246, 0.15);
}

/* ─── 填充模式（hideActions=true）：撑满父容器 ──────────────── */
.cover-card--fill {
  height: 100%;
  width: 100%;
  border-radius: 0;
  border: none;
  background: transparent;
}
.cover-card--fill:hover {
  /* 父 carousel-cell 已有 scale 效果，此处不叠加位移 */
  transform: none;
  box-shadow: none;
  border-color: transparent;
}

/* ─── 已通过：绿色边框发光 ─────────────────────────────── */
.cover-card--approved {
  border-color: rgba(34, 197, 94, 0.55) !important;
  box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.15),
              0 0 20px rgba(34, 197, 94, 0.2),
              0 8px 20px rgba(0, 0, 0, 0.4) !important;
}
.cover-card--approved:hover {
  transform: translateY(-3px);
  box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.25),
              0 0 32px rgba(34, 197, 94, 0.3),
              0 12px 24px rgba(0, 0, 0, 0.5) !important;
}

/* ─── 已毙掉：灰阶降透明度（非填充模式）────────────────────── */
.cover-card--rejected {
  filter: grayscale(100%) opacity(0.48);
  border-color: rgba(255, 255, 255, 0.06) !important;
  cursor: default;
  transform: none !important;
}
.cover-card--rejected:hover {
  transform: none;
  box-shadow: none !important;
}

/* ─── 缺料熔断：深红警戒状态 ─────────────────────────────────── */
.cover-card--asset-missing {
  border-color: rgba(185, 28, 28, 0.6) !important;
  box-shadow: 0 0 0 1px rgba(185, 28, 28, 0.25),
              0 0 20px rgba(185, 28, 28, 0.25),
              0 8px 20px rgba(0, 0, 0, 0.5) !important;
  cursor: not-allowed;
}
.cover-card--asset-missing:hover {
  transform: none !important;
  box-shadow: 0 0 0 1px rgba(185, 28, 28, 0.35),
              0 0 28px rgba(185, 28, 28, 0.3),
              0 8px 20px rgba(0, 0, 0, 0.5) !important;
}

/* 缺料熔断覆盖层 */
.cover-asset-missing {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.55rem;
  /* 斜条纹警告背景 */
  background:
    repeating-linear-gradient(
      -45deg,
      rgba(185, 28, 28, 0.12) 0px,
      rgba(185, 28, 28, 0.12) 8px,
      rgba(10, 10, 20, 0.92) 8px,
      rgba(10, 10, 20, 0.92) 20px
    ),
    linear-gradient(160deg, rgba(30, 10, 10, 0.98) 0%, rgba(15, 5, 5, 0.99) 100%);
}
.missing-icon-wrap {
  width: 56px; height: 56px;
  border-radius: 14px;
  background: rgba(185, 28, 28, 0.15);
  border: 1px solid rgba(185, 28, 28, 0.4);
  display: flex; align-items: center; justify-content: center;
  color: #f87171;
  box-shadow: 0 0 16px rgba(185, 28, 28, 0.3);
}
.cover-card--fill .missing-icon-wrap {
  width: 36px; height: 36px;
  border-radius: 9px;
}
.missing-label {
  font-size: 0.8rem;
  font-weight: 800;
  color: #fca5a5;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.cover-card--fill .missing-label { font-size: 0.65rem; }
.missing-hint {
  font-size: 0.62rem;
  color: #7f1d1d;
  text-align: center;
  padding: 0 0.75rem;
  line-height: 1.4;
}
.cover-card--fill .missing-hint { display: none; }

/* 缺料熔断角标 */
.status-badge--missing {
  background: rgba(185, 28, 28, 0.9);
  color: #fecaca;
  box-shadow: 0 0 10px rgba(185, 28, 28, 0.55);
  font-size: 0.58rem;
  padding: 0.18rem 0.42rem;
}

/* ─── 审批中：轻微脉冲 ──────────────────────────────────── */
.cover-card--loading {
  pointer-events: none;
  opacity: 0.75;
}

/* ── 比例容器（正常模式：padding-top 撑开比例）─────────────── */
.cover-ratio-box {
  position: relative;
  width: 100%;
  background: #060b18;
  overflow: hidden;
  /* padding-top 由 JS 通过 :style 动态设置（默认 177.78% = 9:16） */
}

/* ── 填充模式：flex-grow 接管高度，ratio-box 撑满卡片 ────────── */
.cover-ratio-box--fill {
  flex: 1 1 0;
  min-height: 0;
  padding-top: 0 !important;
  height: 0; /* flex-grow 最终决定实际高度 */
}

.cover-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.3s ease;
}
.cover-card:not(.cover-card--rejected):hover .cover-img {
  transform: scale(1.03);
}

.cover-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  background: linear-gradient(
    160deg,
    rgba(15, 23, 42, 0.96) 0%,
    rgba(20, 30, 58, 0.94) 60%,
    rgba(13, 18, 40, 0.98) 100%
  );
}
.placeholder-icon-wrap {
  width: 52px; height: 52px;
  border-radius: 12px;
  background: rgba(56, 189, 248, 0.06);
  border: 1px solid rgba(56, 189, 248, 0.12);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 0.1rem;
}
.cover-card--fill .placeholder-icon-wrap {
  width: 32px; height: 32px;
  border-radius: 8px;
}
.placeholder-film-icon { color: #334155; }
.placeholder-text {
  font-size: 0.72rem;
  font-weight: 600;
  color: #475569;
  letter-spacing: .01em;
}
.cover-card--fill .placeholder-text { font-size: 0.6rem; }
.placeholder-hint {
  font-size: 0.6rem;
  color: #1e293b;
  text-align: center;
  padding: 0 0.5rem;
  line-height: 1.3;
}

/* Hover 播放遮罩 */
.cover-hover-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s ease;
}
.cover-card:hover .cover-hover-overlay { opacity: 1; }
.play-icon-wrap {
  transform: scale(0.85);
  transition: transform 0.2s ease;
  filter: drop-shadow(0 0 8px rgba(255, 255, 255, 0.6));
}
.cover-card:hover .play-icon-wrap { transform: scale(1); }

/* ── 状态角标 ────────────────────────────────────────────────── */
.status-badge {
  position: absolute;
  top: 0.55rem;
  right: 0.55rem;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.62rem;
  font-weight: 800;
  padding: 0.2rem 0.5rem;
  border-radius: 99px;
  backdrop-filter: blur(6px);
  letter-spacing: .04em;
}
/* 🟡 待审核 */
.status-badge--pending {
  background: rgba(234, 179, 8, 0.82);
  color: #422006;
  box-shadow: 0 0 10px rgba(234, 179, 8, 0.45);
  font-size: 0.58rem;
  padding: 0.18rem 0.42rem;
}
/* ✅ 已通过 */
.status-badge--approved {
  background: rgba(34, 197, 94, 0.88);
  color: #052e16;
  box-shadow: 0 0 10px rgba(34, 197, 94, 0.5);
}
/* ✕ 已毙掉 */
.status-badge--rejected {
  background: rgba(239, 68, 68, 0.82);
  color: #fff;
  box-shadow: 0 0 10px rgba(239, 68, 68, 0.4);
}

/* 时长标签 */
.cover-duration-badge {
  position: absolute;
  bottom: 0.5rem;
  right: 0.5rem;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  color: #e2e8f0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem;
  padding: 0.15rem 0.45rem;
  border-radius: 5px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

/* 审批中 loading 蒙层 */
.cover-loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
}
.loading-spinner {
  width: 24px; height: 24px;
  border: 2px solid rgba(255, 255, 255, 0.15);
  border-top-color: #a78bfa;
  border-radius: 50%;
  animation: spin 0.75s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* 信息区 */
.cover-info {
  padding: 0.6rem 0.75rem 0.35rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.cover-task-id { margin: 0; font-size: 0.65rem; color: #38bdf8; }
.mono { font-family: 'JetBrains Mono', monospace; }
.cover-prompt {
  margin: 0;
  font-size: 0.72rem;
  color: #64748b;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 操作按钮区 */
.cover-actions {
  display: flex;
  gap: 0.4rem;
  padding: 0.4rem 0.6rem 0.7rem;
}
.action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.3rem;
  padding: 0.35rem 0;
  border-radius: 7px;
  font-size: 0.73rem;
  font-weight: 700;
  cursor: pointer;
  border: 1px solid;
  transition: all 0.16s ease;
}
.action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  pointer-events: none;
}
.action-approve {
  background: rgba(34, 197, 94, 0.1);
  border-color: rgba(34, 197, 94, 0.35);
  color: #4ade80;
}
.action-approve:hover {
  background: rgba(34, 197, 94, 0.22);
  border-color: rgba(34, 197, 94, 0.6);
  box-shadow: 0 0 12px rgba(34, 197, 94, 0.25);
}
.action-reject {
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.3);
  color: #f87171;
}
.action-reject:hover {
  background: rgba(239, 68, 68, 0.2);
  border-color: rgba(239, 68, 68, 0.55);
  box-shadow: 0 0 12px rgba(239, 68, 68, 0.2);
}
.action-revoke {
  background: rgba(34, 197, 94, 0.06);
  border-color: rgba(34, 197, 94, 0.2);
  color: #4ade80;
  font-size: 0.68rem;
}
.action-revoke:hover { background: rgba(34, 197, 94, 0.14); }
.action-revoke-reject {
  background: rgba(239, 68, 68, 0.05);
  border-color: rgba(239, 68, 68, 0.18);
  color: #f87171;
  font-size: 0.68rem;
}
.action-revoke-reject:hover { background: rgba(239, 68, 68, 0.14); }
</style>
