import { createApp } from 'vue'
import App from './App.vue'
import './design/tokens.css'
import './style.css'
import { applyTheme, getTheme } from './design/theme.js'
applyTheme(getTheme())
createApp(App).mount('#app')
