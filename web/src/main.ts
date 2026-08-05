import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import { createPinia } from 'pinia'
import { applyDemoMode } from './api/request'
import './style.css'

const app = createApp(App)

// 全局注册 Element Plus 图标，方便在各页面以 <组件名/> 形式使用。
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component as never)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

// 根据当前演示（mock）开关设置 axios 适配器：开启演示则使用本地 mock 适配器。
applyDemoMode()

app.mount('#app')
