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

async function bootstrap() {
  // Backend authorization, not localStorage, establishes restored tenant state.
  const appStore = useAppStore()
  await appStore.initAuth()

  app.use(VueVirtualScroller)
  app.use(router)
  app.mount('#app')
}

bootstrap()
