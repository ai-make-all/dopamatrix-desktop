<script setup>
import { ref, onMounted } from 'vue'
import { open } from '@tauri-apps/plugin-dialog'
import { open as openPath } from '@tauri-apps/plugin-shell'
import axios from 'axios'
import { useAppStore } from '../stores/appStore'

const store = useAppStore()

// ── LLM Settings (BYOK) ───────────────────────────────────────────────────
const llmApiKeyInput  = ref('')
const llmMaskedKey    = ref('')
const llmIsConfigured = ref(false)
const llmSaving       = ref(false)
const showLlmKeyText  = ref(false)

async function loadLlmSettings() {
  try {
    const resp = await axios.get(`${store.API_BASE}/api/v1/settings/llm`)
    llmMaskedKey.value    = resp.data.api_key    || ''
    llmIsConfigured.value = resp.data.is_configured ?? false
  } catch (err) {
    console.error('[LLM Settings] 获取配置失败：', err)
  }
}

async function saveLlmSettings() {
  const key = llmApiKeyInput.value.trim()
  if (!key) {
    store.showToast('⚠️ 请先输入有效的 API Key')
    return
  }
  llmSaving.value = true
  try {
    await axios.post(`${store.API_BASE}/api/v1/settings/llm`, { api_key: key })
    llmApiKeyInput.value = ''
    showLlmKeyText.value = false
    await loadLlmSettings()
    store.showToast('✅ API Key 保存成功！大模型配置已生效。')
  } catch (err) {
    store.showToast(`❌ 保存失败：${err.response?.data?.detail || err.message}`)
  } finally {
    llmSaving.value = false
  }
}

// ── Output dir ────────────────────────────────────────────────────────────
async function pickGlobalOutputFolder() {
  try {
    const selected = await open({ directory: true, multiple: false })
    if (selected && typeof selected === 'string') {
      store.setGlobalOutputDir(selected)
      store.showToast('✅ 输出目录已更新: ' + selected)
    }
  } catch (err) {
    console.error('[Tauri Dialog] 设置目录打开失败：', err)
  }
}

async function openDiagnosticLogs() {
  try {
    const res = await axios.get(`${store.API_BASE}/api/v1/tasks/system/logs/path`)
    await openPath(res.data.path)
  } catch (err) {
    store.showToast(`❌ 打开日志目录失败：${err?.message || String(err)}`)
  }
}

onMounted(loadLlmSettings)
</script>

<template>
  <div class="workspace-wrap" style="padding: 2.5rem; overflow-y: auto; gap: 1.5rem; display: flex; flex-direction: column;">
    <h2 class="assets-title" style="margin-bottom: 0.5rem;">全局安全与输出设置</h2>

    <!-- 账户信息占位卡 -->
    <div class="feed-card" style="padding: 2rem; background: rgba(15,23,42,0.6); border: 1px solid rgba(56,189,248,0.2);">
      <div style="display:flex; align-items:center; gap: 1.5rem;">
        <div style="width:60px; height:60px; border-radius:50%; background: linear-gradient(135deg,#0ea5e9,#6366f1); display:flex; align-items:center; justify-content:center; font-size:1.8rem; flex-shrink:0;">
          👨‍💻
        </div>
        <div>
          <div style="font-size: 1.15rem; font-weight:bold; color:#f8fafc; margin-bottom: 0.2rem;">TeleUser_8891</div>
          <div style="color: #64748b; font-size: 0.82rem;">Telegram 授权账户 (内测阶段待正式对接)</div>
        </div>
      </div>
    </div>

    <!-- LLM 大模型配置卡 -->
    <div class="settings-card settings-card--llm">
      <div class="settings-card-title">
        <span class="settings-card-icon">🤖</span>
        <div>
          <div style="font-size:1.05rem; font-weight:800; color:#e2e8f0;">大模型配置 <span style="color:#64748b; font-size:0.78rem; font-weight:400;">LLM Configuration</span></div>
          <div style="font-size:0.75rem; color:#475569; margin-top:0.15rem; line-height:1.5;">
            采用 BYOK（Bring Your Own Key）零信任架构。Key 仅写入本地 SQLite，绝不外传。
          </div>
        </div>
      </div>

      <div style="margin-bottom:1.25rem;">
        <span v-if="llmIsConfigured" class="llm-status-badge llm-status-badge--ok">
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" style="flex-shrink:0"><circle cx="5" cy="5" r="5" fill="#4ade80"/></svg>
          已配置 &nbsp;<code style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;opacity:0.8;">{{ llmMaskedKey }}</code>
        </span>
        <span v-else class="llm-status-badge llm-status-badge--warn">
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" style="flex-shrink:0"><circle cx="5" cy="5" r="5" fill="#f87171"/></svg>
          尚未配置 — 发起生成任务将报错
        </span>
      </div>

      <div class="settings-field">
        <label class="settings-label">服务提供商</label>
        <div class="tool-select-wrap" style="width:fit-content; opacity:0.6; pointer-events:none; cursor:default;">
          <span class="tool-select-icon">🧠</span>
          <select class="tool-select" style="font-size:0.82rem; padding:0.1rem 0; min-width:14rem;">
            <option>OpenAI / Compatible API（DeepSeek · Moonshot · 通义）</option>
          </select>
        </div>
        <p class="settings-hint">后续版本将支持多服务商切换</p>
      </div>

      <div class="settings-field">
        <label class="settings-label">API Key</label>
        <div class="llm-key-input-wrap">
          <input
            v-model="llmApiKeyInput"
            :type="showLlmKeyText ? 'text' : 'password'"
            :placeholder="llmIsConfigured
              ? `当前 ${llmMaskedKey}  ·  输入新 Key 可覆盖`
              : 'sk-...  或兼容 OpenAI Chat Completions 格式的密钥'"
            class="llm-key-input"
            autocomplete="off"
            spellcheck="false"
            @keydown.enter="saveLlmSettings"
          />
          <button
            class="llm-eye-btn"
            type="button"
            @click="showLlmKeyText = !showLlmKeyText"
            :title="showLlmKeyText ? '隐藏 Key' : '显示 Key'"
          >
            <svg v-if="!showLlmKeyText" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
            <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
              <line x1="1" y1="1" x2="23" y2="23"/>
            </svg>
          </button>
        </div>
        <p class="settings-hint">支持 OpenAI、DeepSeek、Moonshot、通义千问等兼容 OpenAI 格式的服务</p>
      </div>

      <div>
        <button
          @click="saveLlmSettings"
          :disabled="llmSaving || !llmApiKeyInput.trim()"
          class="cta-glow-btn llm-save-btn"
        >
          <span v-if="llmSaving" style="display:inline-flex;align-items:center;gap:0.4rem;">
            <svg class="spin" width="14" height="14" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
            保存中...
          </span>
          <span v-else>🔑 保存 API Key</span>
        </button>
      </div>
    </div>

    <!-- 输出目录卡 -->
    <div class="settings-card">
      <div class="settings-card-title">
        <span class="settings-card-icon">📁</span>
        <div>
          <div style="font-size:1.05rem; font-weight:800; color:#e2e8f0;">本地输出目录绑定</div>
          <div style="font-size:0.75rem; color:#475569; margin-top:0.15rem;">
            成品短视频的统一落地目录。若不设置，默认写入工程
            <code style="color:#38bdf8; background:rgba(56,189,248,0.1); padding:0.1rem 0.3rem; border-radius:3px;">output/</code>
          </div>
        </div>
      </div>
      <div class="settings-path-row">
        <span style="color:#64748b; font-size:0.75rem; white-space:nowrap; flex-shrink:0;">当前路径：</span>
        <span style="color:#94a3b8; word-break:break-all; font-family:'JetBrains Mono',monospace; font-size:0.78rem;">
          {{ store.globalOutputDir || '未设置 (默认跟随引擎 output/)' }}
        </span>
      </div>
      <div style="display:flex; gap: 0.75rem; flex-wrap: wrap;">
        <button @click="pickGlobalOutputFolder" class="cta-glow-btn" style="padding:0.65rem 1.5rem; width:auto; font-size:0.88rem;">
          📁 更改输出目录
        </button>
        <button @click="openDiagnosticLogs" class="cta-glow-btn" style="padding:0.65rem 1.5rem; width:auto; font-size:0.88rem; background:linear-gradient(135deg,rgba(99,102,241,0.15),rgba(139,92,246,0.15)); border-color:rgba(139,92,246,0.4);">
          🗒️ 导出 / 查看诊断日志
        </button>
      </div>
    </div>

  </div>
</template>
