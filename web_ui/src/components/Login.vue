<script setup>
import { ref } from 'vue'

const emit = defineEmits(['login-success'])

const username = ref('')
const isEntering = ref(false)
const errorShake = ref(false)

async function handleEnter() {
  const name = username.value.trim()
  if (!name) {
    errorShake.value = true
    setTimeout(() => { errorShake.value = false }, 600)
    return
  }
  isEntering.value = true
  // Simulate brief auth "handshake" animation
  await new Promise(r => setTimeout(r, 900))
  emit('login-success', name)
}

function onKeydown(e) {
  if (e.key === 'Enter') handleEnter()
}
</script>

<template>
  <div class="login-root">
    <!-- Animated grid background -->
    <div class="grid-bg" aria-hidden="true"></div>

    <!-- Floating orbs -->
    <div class="orb orb-1" aria-hidden="true"></div>
    <div class="orb orb-2" aria-hidden="true"></div>
    <div class="orb orb-3" aria-hidden="true"></div>

    <!-- Scanline overlay -->
    <div class="scanlines" aria-hidden="true"></div>

    <!-- Center card -->
    <div class="login-card" :class="{ 'card-loading': isEntering }">

      <!-- Top glow bar -->
      <div class="card-glow-bar"></div>

      <!-- Brand -->
      <div class="brand-wrap">
        <div class="brand-logo">
          <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
            <rect width="36" height="36" rx="10" fill="url(#logoGrad)"/>
            <path d="M10 18 L18 10 L26 18 L18 26 Z" stroke="white" stroke-width="2" fill="none" stroke-linejoin="round"/>
            <circle cx="18" cy="18" r="3" fill="white"/>
            <defs>
              <linearGradient id="logoGrad" x1="0" y1="0" x2="36" y2="36">
                <stop offset="0%" stop-color="#0ea5e9"/>
                <stop offset="100%" stop-color="#8b5cf6"/>
              </linearGradient>
            </defs>
          </svg>
        </div>
        <div class="brand-name">DopaMatrix</div>
      </div>

      <!-- Slogan -->
      <div class="slogan-wrap">
        <div class="slogan-eyebrow">SYSTEM READY · v1.1-ALPHA</div>
        <h1 class="slogan-text">The Next-Gen<br><span class="slogan-accent">Attention Engine</span></h1>
        <p class="slogan-sub">Multi-account · Isolated · Autonomous</p>
      </div>

      <!-- Divider -->
      <div class="card-divider">
        <span class="divider-label">// TESTNET · RAPID ONBOARD</span>
      </div>

      <!-- Input area -->
      <div class="input-section">
        <label class="input-label">
          <span class="input-label-icon">◈</span>
          输入你的代号 / 工作区标识
        </label>
        <div class="input-wrap" :class="{ shake: errorShake }">
          <span class="input-prefix">@</span>
          <input
            v-model="username"
            @keydown="onKeydown"
            type="text"
            class="identity-input"
            placeholder="例：alpha_001 / 矩阵猎人"
            autocomplete="off"
            spellcheck="false"
            maxlength="32"
            :disabled="isEntering"
          />
          <span class="input-cursor" aria-hidden="true">_</span>
        </div>
        <p class="input-hint">任意代号皆可，此为本机离线工作区隔离标识</p>
      </div>

      <!-- CTA button -->
      <button
        class="enter-btn"
        :class="{ 'enter-btn--loading': isEntering }"
        @click="handleEnter"
        :disabled="isEntering"
      >
        <template v-if="!isEntering">
          <span class="enter-btn-icon">⬡</span>
          Enter Workspace
          <span class="enter-btn-arrow">→</span>
        </template>
        <template v-else>
          <span class="enter-spinner"></span>
          Initializing Matrix...
        </template>
      </button>

      <!-- Footer meta -->
      <div class="card-footer-meta">
        <span class="meta-dot meta-dot--green"></span>
        <span>Engine Node Online</span>
        <span class="meta-sep">·</span>
        <span class="meta-dot meta-dot--cyan"></span>
        <span>Local Mode · No Cloud Required</span>
      </div>
    </div>

    <!-- Version watermark -->
    <div class="version-watermark">DOPAMATRIX // DESKTOP ALPHA // BUILD 001</div>
  </div>
</template>

<style scoped>
/* ── Root & background ───────────────────────────────────────────────────── */
.login-root {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #020817;
  overflow: hidden;
  z-index: 9999;
  font-family: 'Inter', 'JetBrains Mono', monospace, sans-serif;
}

/* Animated grid */
.grid-bg {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(56, 189, 248, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(56, 189, 248, 0.04) 1px, transparent 1px);
  background-size: 48px 48px;
  animation: gridDrift 20s linear infinite;
}
@keyframes gridDrift {
  from { background-position: 0 0; }
  to   { background-position: 48px 48px; }
}

/* Scanlines */
.scanlines {
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 3px,
    rgba(0, 0, 0, 0.07) 3px,
    rgba(0, 0, 0, 0.07) 4px
  );
  pointer-events: none;
}

/* Floating orbs */
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  pointer-events: none;
  animation: orbFloat 8s ease-in-out infinite;
}
.orb-1 {
  width: 500px; height: 500px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.18), transparent 70%);
  top: -15%; left: -10%;
  animation-duration: 10s;
}
.orb-2 {
  width: 380px; height: 380px;
  background: radial-gradient(circle, rgba(56, 189, 248, 0.14), transparent 70%);
  bottom: -10%; right: -8%;
  animation-duration: 12s;
  animation-delay: -3s;
}
.orb-3 {
  width: 280px; height: 280px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.12), transparent 70%);
  top: 30%; right: 20%;
  animation-duration: 15s;
  animation-delay: -6s;
}
@keyframes orbFloat {
  0%, 100% { transform: translateY(0) scale(1); }
  50%       { transform: translateY(-30px) scale(1.05); }
}

/* ── Login card ─────────────────────────────────────────────────────────── */
.login-card {
  position: relative;
  width: 460px;
  max-width: calc(100vw - 2rem);
  background: rgba(9, 14, 30, 0.75);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 20px;
  padding: 0 2rem 2rem;
  box-shadow:
    0 0 0 1px rgba(56, 189, 248, 0.06),
    0 0 60px rgba(99, 102, 241, 0.15),
    0 32px 80px rgba(0, 0, 0, 0.6),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
  transition: box-shadow 0.3s ease;
  animation: cardReveal 0.6s cubic-bezier(0.22, 1, 0.36, 1) both;
}
.login-card.card-loading {
  box-shadow:
    0 0 0 1px rgba(56, 189, 248, 0.15),
    0 0 80px rgba(56, 189, 248, 0.25),
    0 32px 80px rgba(0, 0, 0, 0.6),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
}
@keyframes cardReveal {
  from { opacity: 0; transform: translateY(24px) scale(0.97); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

/* Top glow bar */
.card-glow-bar {
  height: 2px;
  background: linear-gradient(90deg, transparent, #38bdf8, #8b5cf6, #38bdf8, transparent);
  border-radius: 20px 20px 0 0;
  margin: 0 -2rem;
  animation: barShimmer 3s linear infinite;
  background-size: 200% 100%;
}
@keyframes barShimmer {
  from { background-position: 200% 0; }
  to   { background-position: -200% 0; }
}

/* ── Brand ──────────────────────────────────────────────────────────────── */
.brand-wrap {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  margin-top: 2.25rem;
  margin-bottom: 0.25rem;
}
.brand-logo {
  width: 44px; height: 44px;
  border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 24px rgba(99, 102, 241, 0.45), 0 0 0 1px rgba(56,189,248,0.2);
  flex-shrink: 0;
}
.brand-name {
  font-size: 1.75rem;
  font-weight: 900;
  letter-spacing: -0.03em;
  background: linear-gradient(90deg, #38bdf8 0%, #a78bfa 50%, #38bdf8 100%);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: nameShimmer 4s linear infinite;
}
@keyframes nameShimmer {
  from { background-position: 200% 0; }
  to   { background-position: -200% 0; }
}

/* ── Slogan ──────────────────────────────────────────────────────────────── */
.slogan-wrap {
  margin-bottom: 1.75rem;
}
.slogan-eyebrow {
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  color: #38bdf8;
  opacity: 0.6;
  margin-bottom: 0.5rem;
  font-family: 'JetBrains Mono', monospace;
}
.slogan-text {
  margin: 0 0 0.4rem;
  font-size: 1.6rem;
  font-weight: 900;
  color: #f1f5f9;
  line-height: 1.2;
  letter-spacing: -0.02em;
}
.slogan-accent {
  background: linear-gradient(90deg, #38bdf8, #8b5cf6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.slogan-sub {
  margin: 0;
  font-size: 0.72rem;
  color: #475569;
  letter-spacing: 0.04em;
  font-family: 'JetBrains Mono', monospace;
}

/* ── Divider ─────────────────────────────────────────────────────────────── */
.card-divider {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}
.card-divider::before,
.card-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(56,189,248,0.2));
}
.card-divider::after {
  background: linear-gradient(270deg, transparent, rgba(56,189,248,0.2));
}
.divider-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.58rem;
  color: #38bdf8;
  opacity: 0.55;
  white-space: nowrap;
  letter-spacing: 0.08em;
}

/* ── Input ───────────────────────────────────────────────────────────────── */
.input-section {
  margin-bottom: 1.25rem;
}
.input-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.7rem;
  font-weight: 700;
  color: #64748b;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin-bottom: 0.6rem;
}
.input-label-icon {
  color: #38bdf8;
  font-size: 0.75rem;
}
.input-wrap {
  display: flex;
  align-items: center;
  background: rgba(2, 8, 23, 0.6);
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 12px;
  padding: 0 1rem;
  gap: 0.5rem;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-wrap:focus-within {
  border-color: rgba(56, 189, 248, 0.6);
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.08), 0 0 20px rgba(56, 189, 248, 0.12);
}
.input-wrap.shake {
  animation: inputShake 0.5s cubic-bezier(0.36, 0.07, 0.19, 0.97);
  border-color: rgba(239, 68, 68, 0.6);
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.08);
}
@keyframes inputShake {
  10%, 90% { transform: translateX(-2px); }
  20%, 80% { transform: translateX(4px); }
  30%, 50%, 70% { transform: translateX(-4px); }
  40%, 60% { transform: translateX(4px); }
}
.input-prefix {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.1rem;
  color: #38bdf8;
  opacity: 0.7;
  flex-shrink: 0;
}
.identity-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #e2e8f0;
  font-size: 1rem;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  caret-color: #38bdf8;
  padding: 0.85rem 0;
}
.identity-input::placeholder {
  color: #1e293b;
  font-weight: 400;
}
.identity-input:disabled {
  opacity: 0.5;
}
.input-cursor {
  font-family: 'JetBrains Mono', monospace;
  color: #38bdf8;
  opacity: 0;
  animation: blinkCursor 1.1s step-end infinite;
}
.input-wrap:focus-within .input-cursor {
  opacity: 1;
}
@keyframes blinkCursor {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0; }
}
.input-hint {
  margin: 0.5rem 0 0;
  font-size: 0.65rem;
  color: #1e3a5f;
  font-family: 'JetBrains Mono', monospace;
}

/* ── Enter button ────────────────────────────────────────────────────────── */
.enter-btn {
  width: 100%;
  padding: 0.95rem 1.5rem;
  border-radius: 12px;
  border: 1px solid rgba(56, 189, 248, 0.35);
  background: linear-gradient(135deg,
    rgba(14, 165, 233, 0.18) 0%,
    rgba(99, 102, 241, 0.22) 50%,
    rgba(139, 92, 246, 0.18) 100%
  );
  color: #e2e8f0;
  font-size: 0.95rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  position: relative;
  overflow: hidden;
  transition: all 0.25s ease;
  box-shadow:
    0 0 24px rgba(56, 189, 248, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
  margin-bottom: 1.5rem;
}
.enter-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg,
    rgba(56, 189, 248, 0.1),
    rgba(139, 92, 246, 0.1)
  );
  opacity: 0;
  transition: opacity 0.25s;
}
.enter-btn:hover:not(:disabled)::before { opacity: 1; }
.enter-btn:hover:not(:disabled) {
  border-color: rgba(56, 189, 248, 0.65);
  box-shadow:
    0 0 40px rgba(56, 189, 248, 0.22),
    0 0 80px rgba(99, 102, 241, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.1);
  transform: translateY(-1px);
}
.enter-btn:active:not(:disabled) { transform: translateY(0); }
.enter-btn:disabled { opacity: 0.7; cursor: not-allowed; }
.enter-btn--loading {
  border-color: rgba(56, 189, 248, 0.5) !important;
  animation: btnPulse 1.2s ease-in-out infinite;
}
@keyframes btnPulse {
  0%, 100% { box-shadow: 0 0 24px rgba(56, 189, 248, 0.2); }
  50%       { box-shadow: 0 0 48px rgba(56, 189, 248, 0.4); }
}
.enter-btn-icon {
  font-size: 0.85rem;
  color: #38bdf8;
}
.enter-btn-arrow {
  margin-left: auto;
  font-size: 1rem;
  color: #38bdf8;
  transition: transform 0.2s;
}
.enter-btn:hover .enter-btn-arrow { transform: translateX(4px); }

/* Loading spinner */
.enter-spinner {
  width: 16px; height: 16px;
  border-radius: 50%;
  border: 2px solid rgba(56, 189, 248, 0.25);
  border-top-color: #38bdf8;
  animation: spin 0.75s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Footer meta ─────────────────────────────────────────────────────────── */
.card-footer-meta {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  justify-content: center;
  font-size: 0.62rem;
  color: #1e3a5f;
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.04em;
}
.meta-dot {
  width: 5px; height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}
.meta-dot--green { background: #4ade80; box-shadow: 0 0 6px #4ade80; }
.meta-dot--cyan  { background: #38bdf8; box-shadow: 0 0 6px #38bdf8; }
.meta-sep { opacity: 0.4; }

/* ── Version watermark ────────────────────────────────────────────────────── */
.version-watermark {
  position: fixed;
  bottom: 1rem;
  left: 50%;
  transform: translateX(-50%);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.55rem;
  color: rgba(56, 189, 248, 0.12);
  letter-spacing: 0.18em;
  white-space: nowrap;
  pointer-events: none;
  user-select: none;
}
</style>
