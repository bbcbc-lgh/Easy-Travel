<template>
  <main class="app-shell">
    <section class="planner-layout">
      <header class="intro-panel">
        <div class="brand-mark">
          <Plane :size="44" />
        </div>
        <p class="eyebrow">EasyTravel</p>
        <h1>从一份清楚的旅行需求开始</h1>
      </header>

      <section class="form-card" aria-label="旅行规划表单">
        <a-alert
          v-if="llmReady === false"
          class="config-hint"
          type="info"
          show-icon
          message="当前未配置模型，生成会使用规则规划"
          description="在 backend/.env 里填写 LLM_API_KEY 与 LLM_BASE_URL 后重启后端，即可使用 AI 规划。"
        />
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
            <div class="loading-summary">
              <strong>{{ currentStageLabel }}</strong>
              <span class="loading-elapsed">已用时 {{ elapsedSeconds }} 秒</span>
            </div>
            <ul class="stage-list">
              <li v-for="stage in stageOrder" :key="stage.key" :class="['stage-item', stageState(stage.key)]">
                <span class="stage-indicator" aria-hidden="true" />
                <span class="stage-label">{{ stage.label }}</span>
                <small v-if="stageDurations[stage.key] !== undefined">
                  {{ (stageDurations[stage.key] / 1000).toFixed(1) }} 秒
                </small>
              </li>
            </ul>
            <p class="loading-hint">模型正在规划行程，通常需要 30–70 秒，请不要关闭页面。</p>
          </div>

          <div class="actions-row">
            <a-button size="large" :disabled="loading" @click="resetForm">
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
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getHealth, streamTripPlan } from '../services/api'
import type { PlanStageEvent } from '../services/api'
import type { TripPlan, TripPlanRequest } from '../types/trip'

const router = useRouter()
const loading = ref(false)
const elapsedSeconds = ref(0)
const llmReady = ref<boolean | null>(null)

const stageOrder = [
  { key: 'collect_candidates', label: '收集候选地点' },
  { key: 'create_plan', label: '规划行程' },
  { key: 'enrich_routes', label: '计算路线' },
  { key: 'review_plan', label: '质量检查' }
] as const

const stageStatus = ref<Record<string, 'pending' | 'active' | 'done'>>({})
const stageDurations = ref<Record<string, number>>({})

const currentStageLabel = computed(() => {
  const active = stageOrder.find((stage) => stageStatus.value[stage.key] === 'active')
  return active ? `正在${active.label}` : '正在准备'
})

let elapsedTimer: number | undefined

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

function stageState(key: string) {
  return stageStatus.value[key] || 'pending'
}

function markStage(event: PlanStageEvent) {
  stageStatus.value = {
    ...stageStatus.value,
    [event.stage]: event.status === 'done' ? 'done' : 'active'
  }
  if (event.status === 'done' && event.elapsed_ms !== undefined) {
    stageDurations.value = { ...stageDurations.value, [event.stage]: event.elapsed_ms }
  }
}

function stopTimer() {
  if (elapsedTimer !== undefined) {
    window.clearInterval(elapsedTimer)
    elapsedTimer = undefined
  }
}

async function handleSubmit() {
  const { budget, days, transportation, accommodation } = formData
  if (!budget || !days || !transportation || !accommodation) {
    return
  }

  loading.value = true
  stageStatus.value = {}
  stageDurations.value = {}
  elapsedSeconds.value = 0
  const startedAt = Date.now()
  elapsedTimer = window.setInterval(() => {
    elapsedSeconds.value = Math.floor((Date.now() - startedAt) / 1000)
  }, 1000)

  let failure: string | null = null
  let finished = false

  try {
    await streamTripPlan(
      {
        city: formData.city,
        start_date: formData.start_date,
        days,
        preferences: buildPreferences(),
        budget,
        transportation,
        accommodation
      },
      {
        onStage: markStage,
        onPlan: (plan: TripPlan) => {
          finished = true
          sessionStorage.setItem('tripPlan', JSON.stringify(plan))
          void router.push(plan.id ? { name: 'shared-result', params: { id: plan.id } } : { name: 'result' })
        },
        onError: (detail: string) => {
          failure = detail
        }
      }
    )
  } catch (error) {
    failure = error instanceof Error ? error.message : '请检查后端服务或 API 配置'
  } finally {
    stopTimer()
    loading.value = false
  }

  if (failure) {
    message.error(`生成计划失败：${failure}`)
  } else if (!finished) {
    message.error('生成未完成，请重试')
  }
}

onBeforeUnmount(stopTimer)

onMounted(async () => {
  try {
    const health = await getHealth()
    llmReady.value = Boolean(health.services?.llm)
  } catch {
    llmReady.value = null
  }
})
</script>
