<script setup>
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/appStore'
import Dashboard from '../components/Dashboard.vue'

const router = useRouter()
const store  = useAppStore()
</script>

<template>
  <div class="dashboard-wrap">
    <!-- Stat cards -->
    <div class="stat-grid">
      <div class="stat-card stat-violet">
        <div class="stat-label">📦 累计生产资产</div>
        <div class="stat-value">{{ store.dashStats.assets }}</div>
        <div class="stat-sub">本次会话</div>
      </div>
      <div class="stat-card stat-cyan">
        <div class="stat-label">💰 预估节省成本</div>
        <div class="stat-value">${{ store.dashStats.savings }}</div>
        <div class="stat-sub">对比人工剪辑</div>
      </div>
      <div class="stat-card stat-green">
        <div class="stat-label">⚡ GPU 算力状态</div>
        <div class="stat-value" style="font-size:1.4rem">{{ store.dashStats.gpu }}</div>
        <div class="stat-sub">渲染引擎就绪</div>
      </div>
    </div>

    <!-- ROI Dashboard component -->
    <Dashboard />

    <!-- CTA -->
    <div class="dashboard-cta-wrap">
      <button @click="router.push('/workspace')" class="cta-glow-btn">
        🚀 去新建矩阵任务
      </button>
    </div>
  </div>
</template>
