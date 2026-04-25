<script setup>
import { ref, watch, onMounted } from 'vue'
import { open } from '@tauri-apps/plugin-dialog'
import axios from 'axios'
import AudioAssetCard from '../components/AudioAssetCard.vue'
import { useAppStore } from '../stores/appStore'

const store = useAppStore()

const activeTab        = ref('video')
const audioAssetSubTab = ref('audio_bgm')
const assetList        = ref([])

const showAudioImportModal = ref(false)
const pendingAudioFiles    = ref([])
const pendingEmotionTag    = ref('')

async function fetchAssets() {
  const type = activeTab.value === 'audio' ? audioAssetSubTab.value : activeTab.value
  try {
    const resp = await axios.get(`${store.API_BASE}/api/v1/assets?asset_type=${type}`)
    assetList.value = resp.data
  } catch (err) {
    store.showToast('获取素材失败: ' + err.message)
  }
}

async function importAssets() {
  let filterName = '视频素材'
  let filterExts = ['mp4', 'mov']

  if (activeTab.value === 'logo') {
    filterName = 'Logo 水印'; filterExts = ['png']
  } else if (activeTab.value === 'sticker') {
    filterName = '互动贴纸'; filterExts = ['png']
  } else if (activeTab.value === 'audio') {
    filterName = '听觉资产 (BGM/SFX)'; filterExts = ['mp3', 'wav']
  }

  try {
    const selected = await open({ multiple: true, filters: [{ name: filterName, extensions: filterExts }] })
    if (!selected || selected.length === 0) return

    if (activeTab.value === 'audio') {
      pendingAudioFiles.value = Array.isArray(selected) ? selected : [selected]
      pendingEmotionTag.value = ''
      showAudioImportModal.value = true
      return
    }

    store.showToast('正在导入并计算素材哈希...')
    const resp = await axios.post(`${store.API_BASE}/api/v1/assets/import`, {
      file_paths: selected,
      asset_type: activeTab.value,
      video_role: 'general',
      tags: [],
    })
    store.showToast(resp.data.message)
    fetchAssets()
  } catch (err) {
    console.error('[Import Assets] 导入失败：', err)
    store.showToast('导入失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function confirmAudioImport() {
  if (!pendingEmotionTag.value) {
    store.showToast('⚠️ 请先选择情绪标签，这是后端 DopaMatrix 引擎的强制要求！')
    return
  }
  showAudioImportModal.value = false
  store.showToast('正在导入并计算音频哈希...')
  try {
    const resp = await axios.post(`${store.API_BASE}/api/v1/assets/import`, {
      file_paths:  pendingAudioFiles.value,
      asset_type:  audioAssetSubTab.value,
      emotion_tag: pendingEmotionTag.value,
      tags:        [pendingEmotionTag.value],
    })
    store.showToast(resp.data.message)
    fetchAssets()
  } catch (err) {
    store.showToast('导入失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    pendingAudioFiles.value = []
    pendingEmotionTag.value = ''
  }
}

async function updateAudioEmotion(item) {
  try {
    await axios.patch(`${store.API_BASE}/api/v1/assets/${item.id}/emotion`, { emotion_tag: item.emotion_tag })
    store.showToast(`🎵 情绪标签已更新为 ${item.emotion_tag}`)
  } catch (err) {
    store.showToast('情绪标签更新失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function updateVideoRole(item) {
  try {
    await axios.patch(`${store.API_BASE}/api/v1/assets/${item.id}/role`, { video_role: item.video_role })
    store.showToast(`成功将素材设为 ${item.video_role === 'hook' ? '黄金片头 (Hook)' : (item.video_role === 'body' ? '混剪 (Body)' : '通用 (General)')}`)
  } catch (err) {
    store.showToast('角色更新失败: ' + (err.response?.data?.detail || err.message))
  }
}

onMounted(fetchAssets)
watch([activeTab, audioAssetSubTab], fetchAssets)
</script>

<template>
  <div class="assets-wrap">
    <!-- Header -->
    <div class="assets-header">
      <h2 class="assets-title">数字资产管理 (DAM)</h2>
      <button class="cta-glow-btn" style="padding: 0.5rem 1.25rem; font-size: 0.85rem;" @click="importAssets">➕ 导入本地素材</button>
    </div>

    <!-- Tabs -->
    <div class="assets-tabs">
      <button :class="['tab-btn', activeTab === 'video'   ? 'tab-active' : '']"               @click="activeTab = 'video'">🎬 视频骨料 (X轴)</button>
      <button :class="['tab-btn', activeTab === 'logo'    ? 'tab-active' : '']"               @click="activeTab = 'logo'">🏷️ 品牌水印 (Logo)</button>
      <button :class="['tab-btn', activeTab === 'sticker' ? 'tab-active' : '']"               @click="activeTab = 'sticker'">✨ 互动贴纸 (Sticker)</button>
      <button :class="['tab-btn', activeTab === 'audio'   ? 'tab-active tab-active-audio' : '']" @click="activeTab = 'audio'">🎵 听觉资产 (Audio)</button>
    </div>

    <!-- Audio sub-filter pills -->
    <Transition name="subtab-fade">
      <div v-if="activeTab === 'audio'" class="audio-subtabs">
        <button
          :class="['audio-subtab-btn', audioAssetSubTab === 'audio_bgm' ? 'audio-subtab-active' : '']"
          @click="audioAssetSubTab = 'audio_bgm'"
        >🎼 背景音乐 (BGM)</button>
        <button
          :class="['audio-subtab-btn', audioAssetSubTab === 'audio_sfx' ? 'audio-subtab-active' : '']"
          @click="audioAssetSubTab = 'audio_sfx'"
        >⚡ 短促音效 (SFX)</button>
      </div>
    </Transition>

    <!-- Audio grid -->
    <div v-if="activeTab === 'audio'" class="assets-grid">
      <div v-if="assetList.length === 0" style="color: #64748b; font-size: 0.85rem; padding: 1rem;">
        暂无听觉资产，请点击右上角导入。
      </div>
      <AudioAssetCard
        v-for="item in assetList"
        :key="item.id"
        :item="item"
        :api-base="store.API_BASE"
        @emotion-change="updateAudioEmotion"
      />
    </div>

    <!-- Video / Logo / Sticker grid -->
    <div v-else class="assets-grid">
      <div v-if="assetList.length === 0" style="color: #64748b; font-size: 0.85rem; padding: 1rem;">
        暂无素材，请点击右上角导入。
      </div>
      <div
        v-for="item in assetList"
        :key="item.id"
        :class="['asset-card', item.video_role === 'hook' && activeTab === 'video' ? 'asset-card-hook' : '']"
      >
        <div class="asset-thumb">
          <video
            v-if="activeTab === 'video'"
            :src="store.buildVideoUrl(item.file_path)"
            controls muted preload="metadata"
            class="w-full h-48 object-contain bg-black/40 rounded-md mb-3"
          ></video>
          <img
            v-else-if="activeTab === 'logo' || activeTab === 'sticker'"
            :src="store.buildVideoUrl(item.file_path)"
            class="w-full h-48 object-contain bg-black/40 rounded-md mb-3"
          />
          <div class="asset-badges" style="position: absolute; top: 0.5rem; right: 0.5rem;">
            <span class="badge-ref">引用: {{ item.usage_count }}次</span>
          </div>
        </div>
        <div class="asset-info">
          <div class="asset-name" :title="item.file_path">{{ item.file_path.split(/[/\\]/).pop() }}</div>
          <div class="asset-health" title="健康度 (疲劳度)">
            <div class="health-bar" :style="{
              width: item.is_exhausted ? '100%' : (item.usage_count === 0 ? '100%' : Math.max(10, 100 - item.usage_count * 10) + '%'),
              background: item.is_exhausted ? '#f87171' : (item.usage_count === 0 ? '#4ade80' : '#fbbf24')
            }"></div>
          </div>
          <div v-if="activeTab === 'video'" class="asset-role-wrap" style="margin-top:0.35rem; margin-bottom:0.2rem;">
            <select v-model="item.video_role" @change="updateVideoRole(item)" :class="['role-select', item.video_role === 'hook' ? 'role-hook' : (item.video_role === 'body' ? 'role-body' : '')]">
              <option value="body">混剪 (Body)</option>
              <option value="hook">黄金片头 (Hook)</option>
              <option value="general">通用 (General)</option>
            </select>
          </div>
          <div class="asset-tags">
            <span v-for="(tag, idx) in item.tags || []" :key="idx" class="tag">{{ tag }}</span>
            <span v-if="item.is_exhausted" class="tag" style="background: rgba(239,68,68,0.15); color: #fca5a5; border-color: rgba(239,68,68,0.3);">疲劳警告</span>
            <span v-else-if="item.usage_count === 0" class="tag">全新</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Audio Emotion Import Modal -->
    <Transition name="modal-fade">
      <div v-if="showAudioImportModal" class="modal-overlay" @click.self="showAudioImportModal = false">
        <div class="modal-box">
          <div class="modal-header">
            <span class="modal-icon">🎵</span>
            <div>
              <div class="modal-title">打标情绪标签</div>
              <div class="modal-sub">DopaMatrix 引擎强制要求，所有听觉资产必须绑定情绪标签才能参与混音调度</div>
            </div>
          </div>

          <div class="modal-files">
            <div class="modal-files-label">待导入文件 ({{ pendingAudioFiles.length }} 个)</div>
            <div class="modal-file-list">
              <div v-for="(f, i) in pendingAudioFiles" :key="i" class="modal-file-item">
                🎧 {{ f.split(/[/\\]/).pop() }}
              </div>
            </div>
          </div>

          <div class="modal-field">
            <label class="modal-label">选择情绪标签 <span class="modal-required">* 必填</span></label>
            <div class="modal-emotion-pills">
              <button
                v-for="opt in [
                  { value: 'asmr',    label: '🎧 ASMR / 沉浸解压' },
                  { value: 'epic',    label: '💥 史诗震撼 / 强节奏' },
                  { value: 'funny',   label: '🤪 荒诞鬼畜 / 模因音效' },
                  { value: 'general', label: '🎵 通用音乐 (General)' },
                ]"
                :key="opt.value"
                :class="['emotion-pill', pendingEmotionTag === opt.value ? 'emotion-pill--active' : '']"
                @click="pendingEmotionTag = opt.value"
              >{{ opt.label }}</button>
            </div>
          </div>

          <div class="modal-actions">
            <button class="modal-cancel-btn" @click="showAudioImportModal = false">取消</button>
            <button
              class="modal-confirm-btn"
              :class="{ 'modal-confirm-btn--disabled': !pendingEmotionTag }"
              @click="confirmAudioImport"
            >
              <span v-if="!pendingEmotionTag">请先选择标签</span>
              <span v-else>✅ 确认导入并打标</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>

  </div>
</template>
