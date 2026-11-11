<template>
  <main class="history-shell">
    <header class="history-header">
      <a-button @click="router.push('/')">
        <template #icon><ArrowLeft :size="17" /></template>
        返回
      </a-button>
      <div class="history-title">
        <p class="eyebrow">已保存的行程</p>
        <h1>历史行程</h1>
      </div>
      <span v-if="!loading && !error" class="history-count">{{ plans.length }} 份</span>
    </header>

    <a-alert v-if="error" class="history-alert" type="error" show-icon :message="error" />

    <p v-if="loading" class="history-empty">正在加载…</p>

    <div v-else-if="!plans.length && !error" class="history-empty">
      <p>还没有保存过行程。生成第一份后，这里会按时间列出。</p>
      <a-button type="primary" @click="router.push('/')">去生成一份</a-button>
    </div>

    <ul v-else-if="plans.length" class="history-list">
      <li v-for="plan in plans" :key="plan.id" class="history-item">
        <button class="history-main" type="button" @click="openPlan(plan.id)">
          <strong>{{ plan.city }}</strong>
          <span>{{ plan.start_date }} → {{ plan.end_date }} · {{ plan.days }} 天</span>
        </button>
        <span class="history-updated">{{ formatUpdated(plan.updated_at) }}</span>
        <a-button size="small" danger @click="removePlan(plan)">
          <template #icon><Trash2 :size="14" /></template>
          删除
        </a-button>
      </li>
    </ul>
  </main>
</template>

<script setup lang="ts">
import { Modal, message } from 'ant-design-vue'
import { ArrowLeft, Trash2 } from 'lucide-vue-next'
import dayjs from 'dayjs'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { deleteTripPlan, listTripPlans } from '../services/api'
import type { TripPlanSummary } from '../types/trip'

const router = useRouter()
const plans = ref<TripPlanSummary[]>([])
const loading = ref(true)
const error = ref('')

async function loadPlans() {
  loading.value = true
  error.value = ''
  try {
    plans.value = await listTripPlans(50)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载失败，请稍后再试'
  } finally {
    loading.value = false
  }
}

function openPlan(id: string) {
  void router.push({ name: 'plan-detail', params: { id } })
}

function formatUpdated(value: string) {
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm') : value
}

function removePlan(plan: TripPlanSummary) {
  Modal.confirm({
    title: `删除「${plan.city}」这份行程？`,
    content: '删除后无法恢复。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await deleteTripPlan(plan.id)
        plans.value = plans.value.filter((item) => item.id !== plan.id)
        message.success('行程已删除')
      } catch (cause) {
        message.error(`删除失败：${cause instanceof Error ? cause.message : '请稍后再试'}`)
      }
    }
  })
}

onMounted(loadPlans)
</script>
