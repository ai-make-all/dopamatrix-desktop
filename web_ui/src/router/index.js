import { createRouter, createWebHashHistory } from 'vue-router'
import { useAppStore } from '../stores/appStore'

const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/login',
    component: () => import('../components/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/dashboard',
    component: () => import('../views/DashboardView.vue'),
  },
  {
    path: '/workspace',
    component: () => import('../views/WorkspaceView.vue'),
  },
  {
    path: '/assets',
    component: () => import('../views/AssetsView.vue'),
  },
  {
    path: '/approval',
    name: 'Approval',
    component: () => import('../views/ApprovalView.vue'),
  },
  {
    path: '/settings',
    component: () => import('../views/SettingsView.vue'),
  },
  {
    path: '/video/:id',
    name: 'VideoDetail',
    component: () => import('../views/VideoDetailView.vue'),
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// Auth guard: redirect unauthenticated users to /login
router.beforeEach((to) => {
  const store = useAppStore()
  if (!to.meta.public && !store.isLoggedIn) {
    return { path: '/login' }
  }
  if (to.path === '/login' && store.isLoggedIn) {
    return { path: '/dashboard' }
  }
})

export default router
