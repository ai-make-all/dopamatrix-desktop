<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/appStore'

const store  = useAppStore()
const router = useRouter()

const historyList        = ref([])
const historySearchQuery = ref('')

const filteredHistoryList = computed(() => {
  const query = historySearchQuery.value.trim().toLowerCase()
  if (!query) return historyList.value
  return historyList.value.filter(item => item.prompt && item.prompt.toLowerCase().includes(query))
})

async function fetchHistory() {
  try {
    const resp = await axios.get(`${store.API_BASE}/api/v1/history`)
    historyList.value = resp.data || []
  } catch (err) {
    store.showToast('获取历史记录失败: ' + err.message)
  }
}

onMounted(fetchHistory)
</script>

<template>
  <div class="workspace-wrap" style="padding: 1.5rem; overflow-y: auto;">
    <div class="assets-header" style="margin-bottom: 1.5rem;">
      <h2 class="assets-title">历史生成记录 (History Log)</h2>
      <div style="flex:1"></div>
      <input
        v-model="historySearchQuery"
        type="text"
        placeholder="🔍 检索历史提示词 (如：减震器、中东)..."
        class="tool-num"
        style="width: 280px; text-align: left; padding-left: 1rem;"
      />
    </div>

    <div v-if="historyList.length === 0" class="feed-empty">
      <div style="font-size:3rem;opacity:.18">🕒</div>
      <p style="color:#475569;font-size:.85rem;max-width:260px;text-align:center;margin-top:.75rem">
        暂无生成历史，快去矩阵工厂创作吧！
      </p>
    </div>

    <div class="feed-list" style="max-width: 1200px; margin: 0 auto; width: 100%;">
      <div
        v-for="item in filteredHistoryList"
        :key="item.id"
        class="feed-card feed-card-completed"
        style="margin-bottom: 1rem; padding: 1.25rem;"
      >
        <div class="feed-card-header" style="border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 0.75rem; margin-bottom: 0.75rem;">
          <span style="color:#a78bfa;font-size:1rem">🗄️</span>
          <span class="feed-badge" style="background: rgba(167, 139, 250, 0.15); color: #c4b5fd; border: 1px solid rgba(167, 139, 250, 0.3);">
            Task ID: {{ item.task_id }}
          </span>
          <span class="feed-ts text-gray-300 font-medium">生成时间: {{ new Date(item.created_at).toLocaleString('zh') }}</span>
          <span class="feed-ts ml-auto text-gray-300 font-medium" style="margin-left: auto;">
            <span class="text-cyan-400 font-bold">耗时: {{ item.duration }}s</span>
          </span>
        </div>

        <div class="feed-prompt" style="font-size: 1rem; font-weight: 500; color: #e2e8f0; margin-bottom: 1rem; border-left: 3px solid #38bdf8; padding-left: 0.75rem;">
          {{ item.prompt }}
        </div>

        <div class="grid grid-cols-2 md:grid-cols-3 gap-4" v-if="item.output_assets && item.output_assets.length > 0">
          <div v-for="(asset, idx) in item.output_assets" :key="idx" class="flex flex-col">
            <video
              controls
              class="aspect-[4/5] object-contain bg-black rounded-md w-full mb-2"
              :src="store.buildVideoUrl(asset.path)"
              preload="metadata"
            />
            <div class="feed-hash" style="margin-bottom:0.4rem; font-size: 0.7rem;">🔒 {{ asset.hash }}</div>
            <div class="asset-btn-row">
              <button
                @click="store.copyToClipboard(asset.path)"
                class="feed-dl asset-btn-copy cursor-pointer"
                style="font-family: inherit;"
              >📁 复制路径</button>
              <button
                @click="router.push('/video/' + asset.hash)"
                class="feed-dl asset-btn-dna cursor-pointer"
                style="font-family: inherit;"
              >🧬 解析基因</button>
            </div>
          </div>
        </div>
        <div v-else class="text-sm text-slate-500 italic mt-2">
          此任务未包含最终输出视频或已丢失。
        </div>
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
.asset-btn-copy { flex: 1; }
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
