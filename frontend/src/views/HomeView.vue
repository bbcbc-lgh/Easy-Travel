<template>
  <main class="app-shell">
    <section class="planner-layout">
      <header class="intro-panel">
        <div class="brand-mark">
          <Plane :size="44" />
        </div>
        <p class="eyebrow">Easy Travel</p>
        <h1>从一份清楚的旅行需求开始</h1>
      </header>

      <section class="form-card" aria-label="旅行规划表单">
        <a-form layout="vertical" :model="formData" @finish="handleSubmit">
          <div class="form-section">
            <div class="form-section-title">
              <MapPin :size="20" />
              <div>
                <h2>出行时间</h2>
                <p>地点、出发日期和天数</p>
              </div>
            </div>
            <div class="form-grid">
              <a-form-item label="目的地" name="city" :rules="[{ required: true, message: '请输入目的地城市' }]">
                <a-input v-model:value="formData.city" placeholder="如：北京" />
              </a-form-item>
              <a-form-item label="出发日期" name="start_date" :rules="[{ required: true, message: '请选择出发日期' }]">
                <a-input v-model:value="formData.start_date" type="date" placeholder="选择出发日期" />
              </a-form-item>
              <a-form-item label="计划天数" name="days" :rules="[{ required: true, message: '请输入计划天数' }]">
                <a-input-number v-model:value="formData.days" :min="1" :max="14" placeholder="如：3" class="full-width" />
              </a-form-item>
            </div>
          </div>

          <div class="form-section">
            <div class="form-section-title">
              <Settings2 :size="20" />
              <div>
                <h2>出行方式</h2>
                <p>预算、交通和住宿</p>
              </div>
            </div>
            <div class="form-grid">
              <a-form-item label="预算范围" name="budget" :rules="[{ required: true, message: '请选择预算范围' }]">
                <a-segmented v-model:value="formData.budget" :options="budgetOptions" block />
              </a-form-item>
              <a-form-item label="市内出行" name="transportation" :rules="[{ required: true, message: '请选择市内出行方式' }]">
                <a-select v-model:value="formData.transportation" :options="transportOptions" placeholder="如：公共交通" />
              </a-form-item>
              <a-form-item label="住宿标准" name="accommodation" :rules="[{ required: true, message: '请选择住宿标准' }]">
                <a-select v-model:value="formData.accommodation" :options="hotelOptions" placeholder="如：经济型酒店" />
              </a-form-item>
            </div>
          </div>
          <div class="form-section">
            <div class="form-section-title">
              <MessageSquareText :size="20" />
              <div>
                <h2>旅行偏好</h2>
                <p>选择重点，补充必要要求</p>
              </div>
            </div>
            <a-form-item label="优先安排" name="preferencePresets">
              <a-checkbox-group v-model:value="selectedPreferences" class="preference-grid">
                <a-checkbox v-for="option in preferenceOptions" :key="option" :value="option">
                  {{ option }}
                </a-checkbox>
              </a-checkbox-group>
            </a-form-item>
            <a-form-item label="特别需求（可选）" name="extraRequirements">
              <a-textarea
                v-model:value="extraRequirements"
                :rows="4"
                placeholder="例如：带儿童出行、需要无障碍设施、海鲜过敏，或希望每天安排轻松一些"
              />
            </a-form-item>
          </div>

          <div v-if="loading" class="loading-box">
            <a-progress :percent="loadingProgress" status="active" />
            <span>{{ loadingStatus }}</span>
          </div>

          <div class="actions-row">
            <a-button size="large" @click="resetForm">
              <template #icon><RotateCcw :size="17" /></template>
              重新填写
            </a-button>
            <a-button type="primary" size="large" html-type="submit" :loading="loading">
              <template #icon><Sparkles :size="17" /></template>
              生成行程
            </a-button>
          </div>
        </a-form>
      </section>
    </section>
  </main>
</template>

<script setup lang="ts">
import { message } from 'ant-design-vue'
import { MapPin, MessageSquareText, Plane, RotateCcw, Settings2, Sparkles } from 'lucide-vue-next'
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { generateTripPlan } from '../services/api'
import type { TripPlanRequest } from '../types/trip'

const router = useRouter()
const loading = ref(false)
const loadingProgress = ref(0)
const loadingStatus = ref('')

type TripPlanForm = Omit<TripPlanRequest, 'budget' | 'days' | 'preferences'> & {
  budget?: TripPlanRequest['budget']
  days?: number
}

const defaultForm = (): TripPlanForm => ({
  city: '',
  start_date: '',
  days: undefined,
  budget: undefined,
  transportation: '',
  accommodation: ''
})

const formData = reactive<TripPlanForm>(defaultForm())
const selectedPreferences = ref<string[]>([])
const extraRequirements = ref('')
const preferenceOptions = ['历史文化', '自然风光', '美食', '购物', '艺术', '休闲', '亲子', '摄影']
const budgetOptions = ['经济', '中等', '舒适', '豪华']
const transportOptions = ['公共交通', '打车', '自驾'].map((value) => ({ label: value, value }))
const hotelOptions = ['青年旅舍', '经济型酒店', '舒适型酒店', '高端酒店'].map((value) => ({ label: value, value }))

function resetForm() {
  Object.assign(formData, defaultForm())
  selectedPreferences.value = []
  extraRequirements.value = ''
}

function buildPreferences() {
  const parts = [...selectedPreferences.value]
  const extra = extraRequirements.value.trim()
  if (extra) {
    parts.push(extra)
  }
  return parts.join('、')
}

async function handleSubmit() {
  const { budget, days, transportation, accommodation } = formData
  if (!budget || !days || !transportation || !accommodation) {
    return
  }

  loading.value = true
  loadingProgress.value = 0
  loadingStatus.value = '正在整理你的行程需求'

  const statuses = ['正在匹配景点', '正在查询天气', '正在挑选住宿', '正在编排行程']
  const timer = window.setInterval(() => {
    if (loadingProgress.value < 88) {
      loadingProgress.value += 8
      loadingStatus.value = statuses[Math.min(Math.floor(loadingProgress.value / 25), statuses.length - 1)]
    }
  }, 500)

  try {
    const plan = await generateTripPlan({
      city: formData.city,
      start_date: formData.start_date,
      days,
      preferences: buildPreferences(),
      budget,
      transportation,
      accommodation
    })
    window.clearInterval(timer)
    loadingProgress.value = 100
    loadingStatus.value = '行程已生成'
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
