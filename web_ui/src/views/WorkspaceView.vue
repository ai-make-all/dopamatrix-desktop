<script setup>
import { ref, computed, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { open } from '@tauri-apps/plugin-dialog'
import { readDir } from '@tauri-apps/plugin-fs'
import axios from 'axios'
import { useAppStore } from '../stores/appStore'
import QueueView from './QueueView.vue'

const router = useRouter()
const store  = useAppStore()

// ── Omnibox form state ──────────────────────────────────────────────────────
const omniPrompt      = ref('')
const scriptMode      = ref('auto')
const omniPlaceholder = computed(() =>
  scriptMode.value === 'rewrite'
    ? '粘贴您的核心营销文案全文。AI 将在保持卖点绝对不变的前提下，为您裂变出 N 个语气不同的变体文案，完美规避 TikTok 音频查重...'
    : '描述你想生成的视频内容，如：汽车减震器出海，强调极其耐用，适合中东路况...'
)
const batchSize       = ref(1)
const aspectRatio     = ref('9:16')
const testLanguage    = ref('en')
const targetDuration  = ref(15)
const audioVibe       = ref('auto')

// ── Tauri-backed local dirs ────────────────────────────────────────────────
const localAssetDir   = ref('')
const localLogoDir    = ref('')
const localStickerDir = ref('')
const xAssetCount     = ref(0)
const isBatchOverLimit = computed(() => batchSize.value > Math.floor(xAssetCount.value * 1.5))

async function pickFolder(type, label) {
  try {
    const selected = await open({ directory: true, multiple: false })
    if (selected && typeof selected === 'string') {
      if (type === 'xAsset') localAssetDir.value   = selected
      else if (type === 'logo')    localLogoDir.value    = selected
      else if (type === 'sticker') localStickerDir.value = selected

      if (type === 'xAsset') {
        try {
          const entries = await readDir(selected)
          xAssetCount.value = entries.filter(e =>
            e.name && (e.name.toLowerCase().endsWith('.mp4') || e.name.toLowerCase().endsWith('.mov'))
          ).length
        } catch (e) {
          console.error('[Tauri FS] 读取 X轴素材 目录失败：', e)
          xAssetCount.value = 0
        }
      }
    }
  } catch (err) {
    console.error(`[Tauri Dialog] ${label} 打开失败：`, err)
  }
}

// ── Submit ─────────────────────────────────────────────────────────────────
async function sendTask() {
  const prompt = omniPrompt.value.trim()
  if (!prompt) return

  omniPrompt.value = ''

  const localFeedId = store.pushQueuedItem(prompt)
  await nextTick()

  try {
    const payload = {
      prompt,
      script_mode:       scriptMode.value,
      batch_size:        batchSize.value || 1,
      local_asset_dir:   localAssetDir.value   || null,
      local_logo_dir:    localLogoDir.value    || null,
      local_sticker_dir: localStickerDir.value || null,
      aspect_ratio:      aspectRatio.value,
      test_language:     testLanguage.value,
      target_duration:   targetDuration.value,
      output_dir:        store.globalOutputDir || null,
    }

    if (['asmr', 'epic', 'funny'].includes(audioVibe.value)) {
      payload.audio_scape = { bgm: { emotion: audioVibe.value } }
    }

    const resp   = await axios.post(`${store.API_BASE}/api/v1/tasks/submit`, payload)
    const data   = resp.data
    const taskId = String(data.task_id ?? data.id ?? '')
    if (!taskId) throw new Error('后端未返回任务 id')

    store.setFeedItemTaskId(localFeedId, taskId)
    store.startGlobalPolling()

  } catch (err) {
    const raw = err.response?.data?.detail
    let detail
    if (Array.isArray(raw))              detail = raw.map(e => e.msg ?? JSON.stringify(e)).join('；')
    else if (raw && typeof raw === 'string') detail = raw
    else                                 detail = err.message ?? '未知错误'

    store.showToast(`[${err.response?.status ?? 'ERR'}] 提交失败：${detail}`)
    store.markFeedItemFailed(localFeedId)
  }
}
</script>

<template>
  <div class="workspace-wrap">

    <!-- ── TASK FEED (高性能 Worker 驱动的虚拟列表) ────────────────────── -->
    <div class="task-feed">
      <QueueView />
    </div>

    <!-- ── OMNIBOX ─────────────────────────────────────────────────────────── -->
    <div class="omnibox">
      <div class="script-mode-tabs">
        <button
          class="script-mode-tab"
          :class="{ 'script-mode-tab--active': scriptMode === 'auto' }"
          @click="scriptMode = 'auto'"
        >✨ AI 智能创作</button>
        <button
          class="script-mode-tab"
          :class="{ 'script-mode-tab--active': scriptMode === 'rewrite' }"
          @click="scriptMode = 'rewrite'"
        >📝 专属文案洗稿</button>
      </div>

      <textarea
        v-model="omniPrompt"
        @keydown.enter.ctrl.prevent="sendTask"
        :placeholder="omniPlaceholder"
        class="omni-textarea"
        rows="3"
      ></textarea>

      <div class="omni-toolbar">
        <button class="tool-btn tool-btn-primary" @click="router.push('/assets')" title="打开 DAM 添加素材">
          <span style="font-size: 1.1rem;">📦</span>
          <span class="tool-label">从素材库装载弹药</span>
        </button>

        <div class="tool-divider"></div>

        <div class="tool-select-wrap">
          <span class="tool-select-icon">📐</span>
          <select v-model="aspectRatio" class="tool-select">
            <option value="9:16">9:16 竖屏</option>
            <option value="16:9">16:9 横屏</option>
            <option value="1:1">1:1 方形</option>
          </select>
        </div>

        <div class="tool-select-wrap">
          <span class="tool-select-icon">🌐</span>
          <select v-model="testLanguage" class="tool-select">
            <option value="en">EN 英语</option>
            <option value="ar">AR 阿语</option>
            <option value="zh">ZH 中文</option>
          </select>
        </div>

        <div class="tool-select-wrap">
          <span class="tool-select-icon">⏱️</span>
          <select v-model.number="targetDuration" class="tool-select">
            <option :value="15">短平快 (15秒)</option>
            <option :value="30">信息流 (30秒)</option>
            <option :value="60">完整故事 (60秒)</option>
          </select>
        </div>

        <div class="tool-select-wrap tool-select-wrap--vibe">
          <span class="tool-select-icon">🎵</span>
          <select v-model="audioVibe" class="tool-select tool-select--vibe" title="声音情绪 (Audio Vibe)">
            <option value="auto">🎵 AI 智能匹配 (Auto)</option>
            <option value="asmr">🎧 ASMR / 沉浸解压</option>
            <option value="epic">💥 史诗震撼 / 强节奏</option>
            <option value="funny">🤪 荒诞鬼畜 / 模因音效</option>
            <option value="none">🔇 纯人声解说 (无 BGM)</option>
          </select>
        </div>

        <div class="tool-num-wrap">
          <span class="tool-select-icon">🔢</span>
          <input
            v-model.number="batchSize"
            type="number" min="1" max="20"
            class="tool-num"
            title="批量数量"
          />
        </div>

        <button
          @click="sendTask"
          :disabled="!omniPrompt.trim()"
          class="send-btn"
        >🚀 发送</button>
      </div>

      <div v-if="xAssetCount > 0 && isBatchOverLimit" style="color:#facc15; font-size:0.75rem; display:flex; align-items:center; gap:0.4rem;">
        <span>⚠️</span>
        <span style="opacity:0.9">当前素材量仅为 {{ xAssetCount }} 段，生成超过 {{ Math.floor(xAssetCount * 1.5) }} 条变体极易触发平台查重限流，请谨慎操作！</span>
      </div>
    </div>

  </div>
</template>

<style scoped>
.asset-btn-row {
  display: flex;
  gap: 6px;
  margin-top: auto;
}
.asset-btn-copy {
  flex: 1;
}
.asset-btn-dna {
  flex: 1;
  background: linear-gradient(135deg, rgba(56,189,248,0.12), rgba(167,139,250,0.12)) !important;
  border-color: rgba(167,139,250,0.35) !important;
  color: #a78bfa !important;
  transition: background 0.2s, box-shadow 0.2s !important;
}
.asset-btn-dna:hover {
  background: linear-gradient(135deg, rgba(56,189,248,0.22), rgba(167,139,250,0.22)) !important;
  box-shadow: 0 0 10px rgba(167,139,250,0.35);
}
</style>
