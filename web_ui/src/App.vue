<script setup>
import { onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from './stores/appStore'
import Login from './components/Login.vue'

const router = useRouter()
const store  = useAppStore()

onUnmounted(() => store.clearPollTimer())

function handleLogin(username) {
  store.handleLogin(username)
  router.push('/dashboard')
}

function handleLogout() {
  store.handleLogout()
  router.push('/login')
}
</script>

<template>
  <!-- ── AUTH GATE ── -->
  <Transition name="auth-fade">
    <Login v-if="!store.isLoggedIn" @login-success="handleLogin" />
  </Transition>

  <!-- ── APP SHELL ── -->
  <template v-if="store.isLoggedIn">

    <!-- Global Toast — Teleported to body to guarantee it paints above ALL Drawer overlays -->
    <Teleport to="body">
      <Transition name="toast">
        <div
          v-if="store.toastVisible"
          :class="['toast-wrap', `toast-wrap--${store.toastType}`]"
          role="alert"
        >
          <span class="toast-icon" aria-hidden="true">{{
            store.toastType === 'success' ? '✅' :
            store.toastType === 'error'   ? '❌' :
            store.toastType === 'info'    ? '💡' : '⚠️'
          }}</span>
          <p class="toast-msg">{{ store.toastMsg }}</p>
          <button @click="store.toastVisible = false" class="toast-close" aria-label="关闭">✕</button>
        </div>
      </Transition>
    </Teleport>

    <div class="app-shell">

      <!-- ══ SIDEBAR ════════════════════════════════════════════════════ -->
      <aside class="sidebar">
        <div class="sidebar-logo">
          <div class="logo-icon">⚡</div>
          <span class="logo-text">DopaMatrix</span>
        </div>

        <nav class="sidebar-nav">
          <router-link to="/dashboard" custom v-slot="{ navigate, isActive }">
            <button @click="navigate" :class="['nav-item', isActive ? 'nav-active' : '']">
              <span class="nav-icon">📈</span><span>商业看板</span>
            </button>
          </router-link>
          <router-link to="/assets" custom v-slot="{ navigate, isActive }">
            <button @click="navigate" :class="['nav-item', isActive ? 'nav-active' : '']">
              <span class="nav-icon">🗂️</span><span>素材库</span>
            </button>
          </router-link>
          <router-link to="/workspace" custom v-slot="{ navigate, isActive }">
            <button @click="navigate" :class="['nav-item', isActive ? 'nav-active nav-active-cyan' : '']">
              <span class="nav-icon">💬</span><span>矩阵工厂</span>
            </button>
          </router-link>
          <router-link to="/history" custom v-slot="{ navigate, isActive }">
            <button @click="navigate" :class="['nav-item', isActive ? 'nav-active' : '']">
              <span class="nav-icon">🕒</span><span>历史记录</span>
            </button>
          </router-link>
          <router-link to="/settings" custom v-slot="{ navigate, isActive }">
            <button @click="navigate" :class="['nav-item', isActive ? 'nav-active' : '']">
              <span class="nav-icon">⚙️</span><span>设置</span>
            </button>
          </router-link>
        </nav>

        <div class="sidebar-footer">
          <div class="profile-avatar">⬡</div>
          <div class="profile-info">
            <div class="profile-name">@{{ store.loggedInUser }}</div>
            <div class="profile-sub">工作区已隔离</div>
          </div>
          <button class="logout-btn" @click="handleLogout" title="退出 / Logout">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
              <polyline points="16 17 21 12 16 7"/>
              <line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
          </button>
        </div>
      </aside>

      <!-- ══ MAIN CONTENT ══════════════════════════════════════════════ -->
      <main class="main-content">
        <router-view v-slot="{ Component }">
          <Transition name="view-fade" mode="out-in">
            <component :is="Component" />
          </Transition>
        </router-view>
      </main>

    </div>
  </template>
</template>

<style>
/* ── View fade transition ───────────────────────────────────────────────── */
.view-fade-enter-active { transition: opacity 0.18s ease, transform 0.18s ease; }
.view-fade-leave-active { transition: opacity 0.12s ease; }
.view-fade-enter-from   { opacity: 0; transform: translateY(6px); }
.view-fade-leave-to     { opacity: 0; }

/* ── Auth fade transition ──────────────────────────────────────────────── */
.auth-fade-enter-active { transition: opacity 0.3s ease, transform 0.3s ease; }
.auth-fade-leave-active { transition: opacity 0.4s ease, transform 0.4s ease; }
.auth-fade-enter-from   { opacity: 0; transform: scale(1.02); }
.auth-fade-leave-to     { opacity: 0; transform: scale(0.98); }

/* ── App shell ─────────────────────────────────────────────────────────── */
.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ── Sidebar ───────────────────────────────────────────────────────────── */
.sidebar {
  width: 220px;
  flex-shrink: 0;
  background: rgba(9, 14, 30, 0.96);
  border-right: 1px solid rgba(56, 189, 248, 0.12);
  display: flex;
  flex-direction: column;
  padding: 1.25rem 0.75rem;
  gap: 0.5rem;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0 0.5rem 1rem;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  margin-bottom: 0.5rem;
}
.logo-icon {
  width: 2rem; height: 2rem;
  border-radius: 0.5rem;
  background: linear-gradient(135deg, #0ea5e9, #8b5cf6);
  display: flex; align-items: center; justify-content: center;
  font-size: 0.95rem;
  box-shadow: 0 0 16px rgba(99,102,241,.4);
}
.logo-text {
  font-weight: 900;
  font-size: 1rem;
  background: linear-gradient(90deg, #38bdf8, #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: -0.01em;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 0.75rem;
  border-radius: 0.6rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: #64748b;
  background: transparent;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.18s ease;
  text-align: left;
  width: 100%;
}
.nav-item:hover { color: #94a3b8; background: rgba(255,255,255,0.04); }
.nav-icon { font-size: 1rem; }

.nav-active {
  color: #a78bfa !important;
  background: rgba(139,92,246,0.12) !important;
  border-color: rgba(139,92,246,0.3) !important;
  box-shadow: 0 0 16px rgba(139,92,246,0.15), inset 0 0 0 1px rgba(139,92,246,0.08);
}
.nav-active-cyan {
  color: #38bdf8 !important;
  background: rgba(56,189,248,0.10) !important;
  border-color: rgba(56,189,248,0.28) !important;
  box-shadow: 0 0 16px rgba(56,189,248,0.13), inset 0 0 0 1px rgba(56,189,248,0.06);
}

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.75rem 0.5rem 0;
  border-top: 1px solid rgba(255,255,255,0.06);
  margin-top: 0.5rem;
}
.profile-avatar {
  width: 2rem; height: 2rem;
  border-radius: 50%;
  background: rgba(51,65,85,0.8);
  border: 1px solid rgba(56,189,248,0.2);
  display: flex; align-items: center; justify-content: center;
  font-size: 0.9rem;
  flex-shrink: 0;
}
.profile-name { font-size: 0.75rem; font-weight: 700; color: #94a3b8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 90px; }
.profile-sub  { font-size: 0.63rem; color: #475569; }

.logout-btn {
  margin-left: auto;
  flex-shrink: 0;
  width: 28px; height: 28px;
  border-radius: 8px;
  background: transparent;
  border: 1px solid rgba(239, 68, 68, 0.18);
  color: #475569;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
  transition: all 0.18s ease;
}
.logout-btn:hover {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.45);
  color: #f87171;
  box-shadow: 0 0 10px rgba(239, 68, 68, 0.15);
}

/* ── Main content ─────────────────────────────────────────────────── */
.main-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Dashboard ─────────────────────────────────────────────────────── */
.dashboard-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.stat-card {
  border-radius: 14px;
  padding: 1.25rem 1.5rem;
  backdrop-filter: blur(12px);
  border: 1px solid;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.stat-violet { background: rgba(139,92,246,0.1); border-color: rgba(139,92,246,0.25); }
.stat-cyan   { background: rgba(56,189,248,0.08); border-color: rgba(56,189,248,0.22); }
.stat-green  { background: rgba(34,197,94,0.08);  border-color: rgba(34,197,94,0.22); }

.stat-label { font-size: 0.72rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: .06em; }
.stat-value { font-size: 2rem; font-weight: 900; color: #e2e8f0; line-height: 1; font-family: 'JetBrains Mono', monospace; }
.stat-sub   { font-size: 0.65rem; color: #475569; }

.dashboard-cta-wrap {
  display: flex;
  justify-content: center;
  padding: 1rem 0 0.5rem;
}
.cta-glow-btn {
  padding: 0.85rem 2.5rem;
  border-radius: 12px;
  background: linear-gradient(135deg, #0ea5e9 0%, #6366f1 50%, #8b5cf6 100%);
  color: #fff;
  font-weight: 900;
  font-size: 1rem;
  border: none;
  cursor: pointer;
  box-shadow: 0 0 32px rgba(99,102,241,.55), 0 4px 16px rgba(0,0,0,.5);
  transition: all .25s ease;
  letter-spacing: .02em;
}
.cta-glow-btn:hover {
  box-shadow: 0 0 56px rgba(99,102,241,.75), 0 6px 24px rgba(0,0,0,.6);
  transform: translateY(-2px) scale(1.02);
}
.cta-glow-btn:active { transform: translateY(0) scale(.99); }

/* ── Workspace ─────────────────────────────────────────────────────── */
.workspace-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* Task Feed — RecycleScroller 宿主：禁止外层滚动，高度由子组件接管 */
.task-feed {
  flex: 1;
  min-height: 0;      /* 修复 flex 子项 overflow 失效 */
  overflow: hidden;   /* RecycleScroller 自身管理滚动，外层不得干预 */
  display: flex;
  flex-direction: column;
}

.feed-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.feed-list { display: flex; flex-direction: column; gap: 0.75rem; }

.feed-card {
  border-radius: 12px;
  padding: 0.9rem 1rem;
  border: 1px solid;
  backdrop-filter: blur(8px);
  transition: transform 0.15s;
}
.feed-card:hover { transform: translateX(3px); }
.feed-card-queued    { background: rgba(56,189,248,0.06);  border-color: rgba(56,189,248,0.2); }
.feed-card-completed { background: rgba(34,197,94,0.06);   border-color: rgba(34,197,94,0.22); }
.feed-card-failed    { background: rgba(239,68,68,0.06);   border-color: rgba(239,68,68,0.22); }

.feed-card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.6rem;
}

.feed-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: .66rem;
  padding: 1px 8px;
  border-radius: 99px;
  border: 1px solid;
}
.feed-badge-processing { background: rgba(56,189,248,.12); color: #38bdf8; border-color: rgba(56,189,248,.35); }
.feed-badge-completed  { background: rgba(34,197,94,.12);  color: #4ade80; border-color: rgba(34,197,94,.35); }
.feed-badge-failed     { background: rgba(239,68,68,.12);  color: #f87171; border-color: rgba(239,68,68,.35); }

.feed-ts { font-size: .65rem; color: #475569; margin-left: auto; font-family: 'JetBrains Mono', monospace; }
.feed-prompt { font-size: .8rem; color: #94a3b8; margin-bottom: .4rem; line-height:1.5; }
.feed-meta { font-size: .65rem; color: #38bdf8; font-family: 'JetBrains Mono', monospace; }
.feed-video {
  width: 100%;
  max-height: 240px;
  border-radius: 8px;
  background: #000;
  margin-bottom: .5rem;
  object-fit: contain;
}
.feed-hash {
  font-family: 'JetBrains Mono', monospace;
  font-size: .65rem;
  color: #4ade80;
  background: rgba(34,197,94,.08);
  border: 1px solid rgba(34,197,94,.2);
  border-radius: 6px;
  padding: .3rem .6rem;
  word-break: break-all;
  margin-bottom: .4rem;
}
.feed-dl {
  display: block;
  text-align: center;
  font-size: .72rem;
  padding: .35rem;
  border-radius: 6px;
  background: rgba(255,255,255,.04);
  border: 1px solid rgba(255,255,255,.08);
  color: #64748b;
  text-decoration: none;
  transition: all .2s;
}
.feed-dl:hover { color: #38bdf8; border-color: rgba(56,189,248,.3); }

/* Script Mode Tab Switcher */
.script-mode-tabs {
  display: flex;
  gap: 0;
  align-self: flex-start;
  border: 1px solid rgba(56,189,248,0.15);
  border-radius: 6px;
  overflow: hidden;
  background: rgba(15,23,42,0.6);
}
.script-mode-tab {
  padding: 0.3rem 0.9rem;
  font-size: 0.75rem;
  font-family: 'Inter', sans-serif;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: #475569;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: color .18s, background .18s;
  white-space: nowrap;
}
.script-mode-tab + .script-mode-tab {
  border-left: 1px solid rgba(56,189,248,0.15);
}
.script-mode-tab:hover:not(.script-mode-tab--active) {
  color: #94a3b8;
  background: rgba(56,189,248,0.05);
}
.script-mode-tab--active {
  color: #0f172a;
  background: linear-gradient(90deg, #38bdf8, #818cf8);
  font-weight: 600;
}

/* Omnibox */
.omnibox {
  flex-shrink: 0;
  border-top: 1px solid rgba(56,189,248,0.12);
  background: rgba(9,14,30,0.96);
  padding: 0.75rem 1.25rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.omni-textarea {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  color: #e2e8f0;
  font-family: 'Inter', sans-serif;
  font-size: 0.9rem;
  line-height: 1.6;
  caret-color: #38bdf8;
}
.omni-textarea::placeholder { color: #334155; }

.omni-toolbar {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: nowrap;
  overflow-x: auto;
}

.tool-btn {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.65rem;
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04);
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all .18s;
  position: relative;
}
.tool-btn:hover { border-color: rgba(56,189,248,.35); color: #94a3b8; background: rgba(56,189,248,.06); }
.tool-label { font-size: .68rem; }
.tool-dot {
  position: absolute;
  top: 4px; right: 4px;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #38bdf8;
}

.tool-divider {
  width: 1px; height: 1.4rem;
  background: rgba(255,255,255,0.08);
  margin: 0 0.15rem;
  flex-shrink: 0;
}

.tool-select-wrap {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  background: rgba(255,255,255,0.03);
  padding: 0.25rem 0.55rem;
}
.tool-select-icon { font-size: 0.8rem; }
.tool-select {
  background: transparent;
  border: none;
  outline: none;
  color: #94a3b8;
  font-size: 0.7rem;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
}
.tool-select option { background: #0f172a; }

.tool-num-wrap {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  background: rgba(255,255,255,0.03);
  padding: 0.25rem 0.55rem;
}
.tool-num {
  width: 2.5rem;
  background: transparent;
  border: none;
  outline: none;
  color: #94a3b8;
  font-size: 0.7rem;
  font-family: 'JetBrains Mono', monospace;
  text-align: center;
}
.tool-num::-webkit-inner-spin-button { opacity: 0.4; }

.send-btn {
  margin-left: auto;
  flex-shrink: 0;
  padding: 0.4rem 1.1rem;
  border-radius: 9px;
  background: linear-gradient(135deg,#0ea5e9,#6366f1);
  color: #fff;
  font-weight: 800;
  font-size: 0.78rem;
  border: none;
  cursor: pointer;
  box-shadow: 0 0 18px rgba(99,102,241,.45);
  transition: all .2s;
  white-space: nowrap;
}
.send-btn:hover:not(:disabled) {
  box-shadow: 0 0 28px rgba(99,102,241,.7);
  transform: scale(1.03);
}
.send-btn:disabled { opacity: .35; cursor: not-allowed; }

/* ── Shared utils ──────────────────────────────────────────────────── */
.pulse-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #38bdf8;
  animation: pulse-ring 1.5s ease-out infinite;
  display: inline-block;
}

/* ── Transitions ──────────────────────────────────────────────────── */
.feed-enter-active { animation: feedIn .3s cubic-bezier(.22,1,.36,1) both; }
.feed-leave-active { animation: feedOut .2s ease-in forwards; }
.feed-move         { transition: transform .3s ease; }

@keyframes feedIn {
  from { opacity:0; transform: translateY(-10px); }
  to   { opacity:1; transform: translateY(0); }
}
@keyframes feedOut {
  from { opacity:1; transform: translateX(0); }
  to   { opacity:0; transform: translateX(-20px); }
}

/* ─── Global Toast ────────────────────────────────────────────────────────
   position: fixed + Teleport to body → beats every Drawer / Modal overlay.
   z-index: 99999 ensures it is above DslOrchestratorDrawer (z-index ≤ 3001)
   and any future UI layer.
──────────────────────────────────────────────────────────────────────────── */
.toast-wrap {
  position:        fixed;
  top:             2rem;
  left:            50%;
  transform:       translateX(-50%);
  z-index:         99999;          /* nuclear option — above everything */
  max-width:       520px;
  width:           calc(100vw - 2rem);
  display:         flex;
  align-items:     flex-start;
  gap:             .75rem;
  background:      rgba(10, 14, 30, 0.94);
  border:          1px solid rgba(99, 102, 241, 0.4);
  box-shadow:      0 0 0 1px rgba(99,102,241,.12),
                   0 8px 32px rgba(0, 0, 0, 0.55),
                   0 0 24px rgba(99,102,241,.12);
  backdrop-filter: blur(14px);
  border-radius:   .85rem;
  padding:         .85rem 1rem;
  pointer-events:  auto;
}

/* per-type border/glow theming */
.toast-wrap--success {
  border-color: rgba(16, 185, 129, 0.5);
  box-shadow:   0 0 0 1px rgba(16,185,129,.1),
                0 8px 32px rgba(0,0,0,.55),
                0 0 20px rgba(16,185,129,.14);
}
.toast-wrap--error {
  border-color: rgba(239, 68, 68, 0.5);
  box-shadow:   0 0 0 1px rgba(239,68,68,.1),
                0 8px 32px rgba(0,0,0,.55),
                0 0 20px rgba(239,68,68,.14);
}
.toast-wrap--warn {
  border-color: rgba(245, 158, 11, 0.5);
  box-shadow:   0 0 0 1px rgba(245,158,11,.1),
                0 8px 32px rgba(0,0,0,.55),
                0 0 20px rgba(245,158,11,.12);
}

.toast-icon  { font-size:1.1rem; flex-shrink:0; line-height:1.4; }
.toast-msg   { flex:1; font-size:.8rem; line-height:1.55; color:#e2e8f0; word-break:break-word; margin:0; }
.toast-close {
  flex-shrink: 0; background: none; border: none; cursor: pointer;
  color: #475569; font-size: 1rem; padding: .1rem .25rem;
  border-radius: 4px; transition: color .15s, background .15s;
}
.toast-close:hover { color: #94a3b8; background: rgba(255,255,255,0.06); }

.toast-enter-active { animation: toastIn  .3s cubic-bezier(.22,1,.36,1); }
.toast-leave-active { animation: toastOut .22s ease-in forwards; }

@keyframes toastIn {
  from { opacity: 0; transform: translateX(-50%) translateY(-16px) scale(.96); }
  to   { opacity: 1; transform: translateX(-50%) translateY(0)     scale(1);   }
}
@keyframes toastOut {
  from { opacity: 1; transform: translateX(-50%) translateY(0)    scale(1);   }
  to   { opacity: 0; transform: translateX(-50%) translateY(-10px) scale(.97); }
}

.spin { animation: spin .9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse-ring {
  0%  { box-shadow: 0 0 0 0   rgba(56,189,248,.55); }
  70% { box-shadow: 0 0 0 10px rgba(56,189,248,0); }
  100%{ box-shadow: 0 0 0 0   rgba(56,189,248,0); }
}

/* ── Assets (DAM) ──────────────────────────────────────────────────── */
.assets-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  background: radial-gradient(circle at top right, rgba(139,92,246,0.03), transparent 50%);
}

.assets-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.assets-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 800;
  color: #e2e8f0;
  background: linear-gradient(90deg, #a78bfa, #38bdf8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: .02em;
}

.assets-tabs {
  display: flex;
  gap: 0.75rem;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  padding-bottom: 0.5rem;
}
.tab-btn {
  background: transparent;
  border: none;
  color: #64748b;
  font-size: 0.85rem;
  font-weight: 600;
  padding: 0.5rem 1rem;
  cursor: pointer;
  border-radius: 8px;
  transition: all .2s;
}
.tab-btn:hover { background: rgba(255,255,255,0.04); color: #94a3b8; }
.tab-active {
  background: rgba(139,92,246,0.1) !important;
  color: #a78bfa !important;
  box-shadow: inset 0 0 0 1px rgba(139,92,246,0.2);
}

.assets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1.25rem;
}

.asset-card {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: all .2s;
}
.asset-card:hover {
  transform: translateY(-4px);
  border-color: rgba(139,92,246,0.3);
  box-shadow: 0 10px 20px rgba(0,0,0,0.4), 0 0 15px rgba(139,92,246,0.15);
}

.asset-card-hook {
  border-color: rgba(168, 85, 247, 0.6) !important;
  box-shadow: 0 0 15px rgba(168, 85, 247, 0.25) !important;
}

.role-select {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #94a3b8;
  font-size: 0.72rem;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  width: 100%;
  outline: none;
  cursor: pointer;
}
.role-hook {
  color: #d8b4fe;
  border-color: rgba(168, 85, 247, 0.4);
}
.role-body {
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.2);
}

.asset-thumb {
  height: 120px;
  background: #090e1a;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.thumb-icon { font-size: 2.5rem; opacity: 0.3; }
.asset-badges {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  display: flex;
  gap: 0.4rem;
}
.badge-ref {
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(4px);
  color: #cbd5e1;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem;
  padding: 0.2rem 0.5rem;
  border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.1);
}

.asset-info {
  padding: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
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
  height: 6px;
  background: rgba(255,255,255,0.08);
  border-radius: 99px;
  overflow: hidden;
}
.health-bar {
  height: 100%;
  border-radius: 99px;
  transition: width .3s ease;
}
.asset-tags {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.asset-tags .tag {
  background: rgba(56,189,248,0.1);
  color: #38bdf8;
  border: 1px solid rgba(56,189,248,0.25);
  font-size: 0.65rem;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
}

.tool-btn-primary {
  background: linear-gradient(135deg, rgba(139,92,246,0.15), rgba(56,189,248,0.15));
  border-color: rgba(139,92,246,0.4);
}
.tool-btn-primary:hover {
  background: linear-gradient(135deg, rgba(139,92,246,0.25), rgba(56,189,248,0.25));
  border-color: rgba(139,92,246,0.6);
  box-shadow: 0 0 12px rgba(139,92,246,0.2);
}
.tool-btn-primary .tool-label {
  color: #e2e8f0 !important;
}

/* ── Audio Tab active state ────────────────────────────────────────── */
.tab-active-audio {
  background: rgba(167, 139, 250, 0.12) !important;
  color: #c4b5fd !important;
  box-shadow: inset 0 0 0 1px rgba(167,139,250,0.25) !important;
}

/* ── Audio Sub-tabs (BGM / SFX pills) ──────────────────────────────── */
.audio-subtabs {
  display: flex;
  gap: 0.5rem;
  padding: 0.1rem 0 0.5rem;
}
.audio-subtab-btn {
  padding: 0.3rem 0.9rem;
  border-radius: 99px;
  border: 1px solid rgba(139,92,246,0.25);
  background: rgba(139,92,246,0.06);
  color: #64748b;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  transition: all .18s;
}
.audio-subtab-btn:hover { color: #a78bfa; border-color: rgba(139,92,246,0.45); }
.audio-subtab-active {
  background: rgba(139,92,246,0.2) !important;
  color: #c4b5fd !important;
  border-color: rgba(167,139,250,0.5) !important;
  box-shadow: 0 0 10px rgba(139,92,246,0.2);
}

.subtab-fade-enter-active { transition: all .2s ease; }
.subtab-fade-leave-active { transition: all .15s ease; }
.subtab-fade-enter-from, .subtab-fade-leave-to { opacity: 0; transform: translateY(-6px); }

/* ── Audio Import Modal ─────────────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0; z-index: 9000;
  background: rgba(0,0,0,0.72);
  backdrop-filter: blur(6px);
  display: flex; align-items: center; justify-content: center;
  padding: 1rem;
}
.modal-box {
  width: 100%; max-width: 500px;
  background: rgba(10,15,35,0.98);
  border: 1px solid rgba(139,92,246,0.35);
  border-radius: 16px;
  padding: 1.75rem;
  box-shadow: 0 0 60px rgba(139,92,246,0.2), 0 20px 40px rgba(0,0,0,0.6);
  display: flex; flex-direction: column; gap: 1.25rem;
}
.modal-header { display: flex; gap: 0.85rem; align-items: flex-start; }
.modal-icon { font-size: 1.6rem; flex-shrink: 0; line-height: 1; }
.modal-title { font-size: 1.05rem; font-weight: 800; color: #e2e8f0; margin-bottom: 0.25rem; }
.modal-sub { font-size: 0.75rem; color: #64748b; line-height: 1.5; }
.modal-files-label { font-size: 0.72rem; color: #475569; margin-bottom: 0.4rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
.modal-file-list { display: flex; flex-direction: column; gap: 0.3rem; max-height: 100px; overflow-y: auto; }
.modal-file-item { font-size: 0.75rem; color: #94a3b8; font-family: 'JetBrains Mono', monospace; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; padding: 0.3rem 0.6rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.modal-label { display: block; font-size: 0.75rem; font-weight: 700; color: #94a3b8; margin-bottom: 0.6rem; }
.modal-required { color: #f87171; font-size: 0.7rem; }
.modal-emotion-pills { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.emotion-pill {
  padding: 0.4rem 0.85rem;
  border-radius: 99px;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04);
  color: #64748b;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  transition: all .18s;
}
.emotion-pill:hover { border-color: rgba(139,92,246,0.4); color: #a78bfa; }
.emotion-pill--active {
  background: rgba(139,92,246,0.22) !important;
  border-color: rgba(167,139,250,0.6) !important;
  color: #e9d5ff !important;
  box-shadow: 0 0 12px rgba(139,92,246,0.3);
}
.modal-actions { display: flex; gap: 0.75rem; justify-content: flex-end; }
.modal-cancel-btn {
  padding: 0.5rem 1.1rem; border-radius: 8px;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
  color: #64748b; font-size: 0.82rem; font-weight: 600; cursor: pointer;
  transition: all .18s;
}
.modal-cancel-btn:hover { color: #94a3b8; border-color: rgba(255,255,255,0.2); }
.modal-confirm-btn {
  padding: 0.5rem 1.4rem; border-radius: 8px;
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  border: none; color: #fff; font-size: 0.82rem; font-weight: 800;
  cursor: pointer; transition: all .2s;
  box-shadow: 0 0 16px rgba(99,102,241,0.4);
}
.modal-confirm-btn:hover:not(.modal-confirm-btn--disabled) {
  box-shadow: 0 0 28px rgba(99,102,241,0.65); transform: scale(1.03);
}
.modal-confirm-btn--disabled { opacity: 0.45; cursor: not-allowed; transform: none !important; }
.modal-fade-enter-active { transition: all .25s cubic-bezier(.22,1,.36,1); }
.modal-fade-leave-active { transition: all .18s ease-in; }
.modal-fade-enter-from, .modal-fade-leave-to { opacity: 0; }
.modal-fade-enter-from .modal-box { transform: scale(.95) translateY(10px); }

/* ── Audio Vibe selector ───────────────────────────────────────────── */
.tool-select-wrap--vibe {
  border-color: rgba(167,139,250,0.25);
  background: linear-gradient(135deg, rgba(139,92,246,0.08), rgba(56,189,248,0.05));
  transition: border-color .2s, box-shadow .2s;
}
.tool-select-wrap--vibe:hover {
  border-color: rgba(167,139,250,0.5);
  box-shadow: 0 0 10px rgba(139,92,246,0.2);
}
.tool-select--vibe {
  color: #c4b5fd;
  font-weight: 600;
  min-width: 9rem;
}
.tool-select--vibe option { background: #0f172a; color: #e2e8f0; }

/* ── Settings page cards ────────────────────────────────────────────── */
.settings-card {
  padding: 1.75rem 2rem;
  background: rgba(15,23,42,0.6);
  border: 1px solid rgba(56,189,248,0.15);
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  backdrop-filter: blur(10px);
}
.settings-card--llm {
  border-color: rgba(139,92,246,0.28);
  background: rgba(12,10,30,0.7);
  box-shadow: 0 0 40px rgba(139,92,246,0.07), inset 0 0 0 1px rgba(139,92,246,0.06);
}
.settings-card-title {
  display: flex;
  align-items: flex-start;
  gap: 0.9rem;
}
.settings-card-icon {
  font-size: 1.65rem;
  line-height: 1;
  flex-shrink: 0;
  margin-top: 0.05rem;
}
.settings-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.settings-label {
  font-size: 0.7rem;
  font-weight: 700;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: .07em;
}
.settings-hint {
  margin: 0;
  font-size: 0.68rem;
  color: #334155;
  line-height: 1.5;
}
.settings-path-row {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: rgba(0,0,0,0.25);
  border-radius: 8px;
  border: 1px dashed rgba(255,255,255,0.08);
}

/* ── LLM status badge ────────────────────────────────────────────────── */
.llm-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.25rem 0.75rem;
  border-radius: 99px;
  border: 1px solid;
  font-family: 'Inter', sans-serif;
}
.llm-status-badge--ok   { background: rgba(34,197,94,0.1);  border-color: rgba(34,197,94,0.3);  color: #4ade80; }
.llm-status-badge--warn { background: rgba(239,68,68,0.1); border-color: rgba(239,68,68,0.25); color: #f87171; }

/* ── LLM Key input ───────────────────────────────────────────────────── */
.llm-key-input-wrap {
  display: flex;
  align-items: stretch;
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(139,92,246,0.22);
  border-radius: 9px;
  overflow: hidden;
  transition: border-color .2s, box-shadow .2s;
}
.llm-key-input-wrap:focus-within {
  border-color: rgba(139,92,246,0.55);
  box-shadow: 0 0 0 3px rgba(139,92,246,0.1);
}
.llm-key-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  padding: 0.7rem 0.9rem;
  color: #e2e8f0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.82rem;
  letter-spacing: 0.04em;
  min-width: 0;
}
.llm-key-input::placeholder { color: #2d3748; }
.llm-eye-btn {
  flex-shrink: 0;
  padding: 0 0.8rem;
  background: transparent;
  border: none;
  border-left: 1px solid rgba(255,255,255,0.06);
  color: #475569;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color .18s, background .18s;
}
.llm-eye-btn:hover { color: #a78bfa; background: rgba(139,92,246,0.08); }

/* ── LLM save button ─────────────────────────────────────────────────── */
.llm-save-btn {
  padding: 0.65rem 1.75rem;
  width: auto;
  font-size: 0.9rem;
  background: linear-gradient(135deg, rgba(109,40,217,0.85), rgba(99,102,241,0.85));
  border-color: rgba(139,92,246,0.5);
  box-shadow: 0 0 24px rgba(99,102,241,0.3);
}
.llm-save-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
  transform: none !important;
  box-shadow: none;
}
</style>
