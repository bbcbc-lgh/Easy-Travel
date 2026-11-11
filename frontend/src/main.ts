import {
  Alert,
  Button,
  Checkbox,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Menu,
  Segmented,
  Select,
  Statistic,
  Tag,
  Textarea
} from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import { createApp } from 'vue'
import type { Plugin } from 'vue'

import App from './App.vue'
import router from './router'
import './styles/main.css'

const app = createApp(App)

// Register only the components the app actually uses. Importing the whole
// library (`app.use(Antd)`) shipped ~430 kB gzip of unused components.
const components = [
  Alert,
  Button,
  Checkbox,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Menu,
  Segmented,
  Select,
  Statistic,
  Tag,
  Textarea
] as unknown as Plugin[]

for (const component of components) {
  app.use(component)
}

app.use(router).mount('#app')
