<template>
  <main class="app-shell">
    <section class="planner-layout">
      <div class="intro-panel">
        <p class="eyebrow">Easy Travel</p>
        <h1>智能旅行助手</h1>
        <p class="intro-copy">输入目的地、日期、偏好与预算，生成包含景点、餐饮、酒店、天气和预算的可编辑行程。</p>
        <div class="status-grid">
          <div>
            <span>5</span>
            <small>专属 Agent</small>
          </div>
          <div>
            <span>5</span>
            <small>核心功能</small>
          </div>
          <div>
            <span>0</span>
            <small>必需数据库</small>
          </div>
        </div>
      </div>

      <a-card class="form-card" :bordered="false">
        <a-form layout="vertical" :model="formData" @finish="handleSubmit">
          <div class="form-grid">
            <a-form-item label="目的地城市" name="city" :rules="[{ required: true, message: '请输入目的地城市' }]">
              <a-input v-model:value="formData.city" placeholder="如：北京" />
            </a-form-item>
            <a-form-item label="开始日期" name="start_date" :rules="[{ required: true, message: '请选择开始日期' }]">
              <a-input v-model:value="formData.start_date" type="date" />
            </a-form-item>
            <a-form-item label="旅行天数" name="days">
              <a-input-number v-model:value="formData.days" :min="1" :max="14" class="full-width" />
            </a-form-item>
            <a-form-item label="预算档位" name="budget">
              <a-segmented v-model:value="formData.budget" :options="budgetOptions" block />
            </a-form-item>
            <a-form-item label="交通方式" name="transportation">
              <a-select v-model:value="formData.transportation" :options="transportOptions" />
            </a-form-item>
            <a-form-item label="住宿偏好" name="accommodation">
              <a-select v-model:value="formData.accommodation" :options="hotelOptions" />
            </a-form-item>
          </div>

          <a-form-item label="旅行偏好" name="preferences">
            <a-textarea
              v-model:value="formData.preferences"
              :rows="4"
              placeholder="例如：历史文化、亲子、城市漫游、美食、摄影、轻松不赶路"
            />
          </a-form-item>

          <div v-if="loading" class="loading-box">
            <a-progress :percent="loadingProgress" status="active" />
            <span>{{ loadingStatus }}</span>
          </div>

          <div class="actions-row">
            <a-button size="large" @click="resetForm">
              <template #icon><RotateCcw :size="17" /></template>
              重置
            </a-button>
            <a-button type="primary" size="large" html-type="submit" :loading="loading">
              <template #icon><Sparkles :size="17" /></template>
              开始规划
            </a-button>
          </div>
        </a-form>
      </a-card>
    </section>
  </main>
</template>

<script setup lang="ts">
import dayjs from 'dayjs'
import { message } from 'ant-design-vue'
import { RotateCcw, Sparkles } from 'lucide-vue-next'
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { generateTripPlan } from '../services/api'
import type { TripPlanRequest } from '../types/trip'

const router = useRouter()
const loading = ref(false)
const loadingProgress = ref(0)
const loadingStatus = ref('')

const defaultForm = (): TripPlanRequest => ({
  city: '北京',
  start_date: dayjs().add(7, 'day').format('YYYY-MM-DD'),
  days: 3,
  preferences: '历史文化、城市漫游、美食，节奏适中',
  budget: '中等',
  transportation: '公共交通',
  accommodation: '经济型酒店'
})

const formData = reactive<TripPlanRequest>(defaultForm())
const budgetOptions = ['经济', '中等', '舒适', '豪华']
const transportOptions = ['公共交通', '打车', '自驾'].map((value) => ({ label: value, value }))
const hotelOptions = ['青年旅舍', '经济型酒店', '舒适型酒店', '高端酒店'].map((value) => ({ label: value, value }))

function resetForm() {
  Object.assign(formData, defaultForm())
}

async function handleSubmit() {
  loading.value = true
  loadingProgress.value = 0
  loadingStatus.value = '正在理解旅行需求'

  const statuses = ['正在搜索景点', '正在查询天气', '正在推荐酒店', '正在生成行程计划']
  const timer = window.setInterval(() => {
    if (loadingProgress.value < 88) {
      loadingProgress.value += 8
      loadingStatus.value = statuses[Math.min(Math.floor(loadingProgress.value / 25), statuses.length - 1)]
    }
  }, 500)

  try {
    const plan = await generateTripPlan({ ...formData })
    window.clearInterval(timer)
    loadingProgress.value = 100
    loadingStatus.value = '规划完成'
    sessionStorage.setItem('tripPlan', JSON.stringify(plan))
    await router.push(plan.id ? { name: 'shared-result', params: { id: plan.id } } : { name: 'result' })
  } catch (error) {
    const detail = error instanceof Error ? error.message : '请检查后端服务或 API 配置'
    message.error(`生成计划失败：${detail}`)
  } finally {
    window.clearInterval(timer)
    loading.value = false
  }
}
</script>
