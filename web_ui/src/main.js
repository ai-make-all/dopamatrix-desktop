import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router/index.js'
import './style.css'
import App from './App.vue'
import { useAppStore } from './stores/appStore'
import VueVirtualScroller from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'

const pinia = createPinia()
const app   = createApp(App)

app.use(pinia)

// Hydrate auth state from localStorage before first navigation guard runs
const appStore = useAppStore()
appStore.initAuth()

app.use(VueVirtualScroller)
app.use(router)
app.mount('#app')
