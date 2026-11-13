<template>
  <main v-if="tripPlan" class="result-shell">
    <aside class="side-nav">
      <a-button class="back-button" @click="router.push('/')">
        <template #icon><ArrowLeft :size="17" /></template>
        返回
      </a-button>
      <a-menu v-model:selected-keys="selectedKeys" mode="inline" @click="scrollToSection">
        <a-menu-item key="budget"><WalletCards :size="16" /> 预算明细</a-menu-item>
        <a-menu-item key="map"><MapPinned :size="16" /> 地图路线</a-menu-item>
        <a-menu-item key="days"><CalendarDays :size="16" /> 每日行程</a-menu-item>
        <a-menu-item key="weather"><CloudSun :size="16" /> 天气信息</a-menu-item>
        <a-menu-item v-if="qualityWarnings.length" key="quality"
          ><ShieldCheck :size="16" /> 行程提醒</a-menu-item
        >
      </a-menu>
    </aside>

    <section id="trip-plan-content" class="result-content">
      <header id="overview" class="result-header">
        <div>
          <p class="eyebrow">行程计划</p>
          <h1>
            {{ tripPlan.city }} <span class="trip-day-count">{{ tripPlan.days.length }}</span> 天游
          </h1>
          <p>
            {{ tripPlan.start_date }} 至 {{ tripPlan.end_date }}
            <a-tag v-if="tripPlan.degraded" color="error" class="plan-source-tag">规则生成</a-tag>
            <a-tag v-else-if="tripPlan.quality" color="success" class="plan-source-tag"
              >AI 规划</a-tag
            >
          </p>
          <div class="overview-metrics">
            <div>
              <span>{{ allAttractions.length }}</span>
              <small>景点</small>
            </div>
            <div>
              <span>{{ tripPlan.weather_info.length }}</span>
              <small>天气</small>
            </div>
            <div v-if="tripPlan.budget">
              <span>{{ tripPlan.budget.total }}</span>
              <small>元预算</small>
            </div>
          </div>
        </div>
        <div class="header-actions" data-html2canvas-ignore>
          <a-button @click="toggleEditMode">
            <template #icon><Pencil :size="17" /></template>
            {{ editMode ? '退出编辑' : '编辑行程' }}
          </a-button>
          <a-button v-if="editMode" type="primary" :loading="saving" @click="saveChanges">
            <template #icon><Save :size="17" /></template>
            保存
          </a-button>
          <a-button v-if="editMode" :disabled="saving" @click="cancelEdit">
            <template #icon><Undo2 :size="17" /></template>
            取消
          </a-button>
          <a-button v-if="tripPlan.id" danger @click="confirmDelete">
            <template #icon><Trash2 :size="17" /></template>
            删除
          </a-button>
          <a-dropdown :trigger="['click']">
            <a-button>
              <template #icon><Download :size="17" /></template>
              导出
            </a-button>
            <template #overlay>
              <a-menu>
                <a-menu-item @click="exportAsImage">导出图片</a-menu-item>
                <a-menu-item @click="exportAsPDF">导出 PDF（图片版）</a-menu-item>
                <a-menu-item @click="printPlan">打印 / 另存为 PDF（文字可选）</a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
      </header>

      <a-alert
        v-if="tripPlan.degraded"
        class="data-notice"
        type="error"
        show-icon
        message="本次行程由规则引擎生成，未经 AI 规划"
        :description="`原因：${degradedReasonLabel(tripPlan.degraded_reason)}。内容仅供参考。`"
      />

      <a-alert
        v-for="notice in tripPlan.data_notices || []"
        :key="notice"
        class="data-notice"
        :message="notice"
        type="warning"
        show-icon
      />

      <section v-if="tripPlan.budget" id="budget" class="section-block">
        <h2>预算明细</h2>
        <div class="budget-grid">
          <a-statistic title="景点门票" :value="tripPlan.budget.total_attractions" suffix="元" />
          <a-statistic title="酒店住宿" :value="tripPlan.budget.total_hotels" suffix="元" />
          <a-statistic title="餐费估算" :value="tripPlan.budget.total_meals" suffix="元" />
          <a-statistic title="交通费用" :value="tripPlan.budget.total_transportation" suffix="元" />
          <a-statistic
            class="total-budget"
            title="预估总费用"
            :value="tripPlan.budget.total"
            suffix="元"
          />
        </div>
        <p class="budget-note">
          住宿按 {{ hotelNights }} 晚计算（{{ tripPlan.days.length }} 天行程通常为
          {{ hotelNights }}
          晚）；不含往返大交通、购物和个人消费。预算档位不会覆盖你单独选择的住宿与交通方式。
        </p>
      </section>

      <section id="map" class="section-block" data-html2canvas-ignore>
        <div class="section-title-row">
          <h2>地图路线</h2>
          <a-tag>{{ allAttractions.length }} 个地点</a-tag>
        </div>
        <div class="map-panel">
          <div id="amap-container" class="map-canvas"></div>
          <div v-if="!mapReady" class="map-fallback">
            <MapPinned :size="28" />
            <p>{{ mapStatus }}</p>
          </div>
        </div>
      </section>

      <section id="revise" class="section-block revise-block" data-html2canvas-ignore>
        <div class="section-title-row">
          <h2>用一句话调整</h2>
          <a-tag v-if="revising" color="processing">调整中</a-tag>
        </div>
        <div class="revise-row">
          <a-input
            v-model:value="reviseInstruction"
            :disabled="revising"
            placeholder="例如：第 2 天下午换成室内活动，别太赶"
            @press-enter="submitRevision"
          />
          <a-button
            type="primary"
            :loading="revising"
            :disabled="!reviseInstruction.trim() || !tripPlan.id"
            @click="submitRevision"
          >
            调整
          </a-button>
        </div>
        <p class="revise-hint">只会改动你提到的部分，坐标、价格和路线会重新计算。</p>
        <a-alert
          v-if="reviseReply"
          class="data-notice"
          type="success"
          show-icon
          :message="reviseReply"
        />
        <a-alert
          v-if="reviseError"
          class="data-notice"
          type="error"
          show-icon
          :message="reviseError"
        />
      </section>

      <section id="days" class="section-block">
        <h2>每日行程</h2>
        <div class="day-list">
          <article
            v-for="(day, dayIndex) in tripPlan.days"
            :key="day.date"
            class="day-card"
            :class="{ 'is-collapsed': !isDayExpanded(dayIndex) }"
          >
            <button class="day-card-header" type="button" @click="toggleDay(dayIndex)">
              <div>
                <span>第 {{ day.day_index + 1 }} 天</span>
                <h3>{{ day.date }}</h3>
              </div>
              <div class="day-header-meta">
                <a-tag>{{ day.transportation }}</a-tag>
                <ChevronDown :size="18" class="day-toggle-icon" />
              </div>
            </button>

            <template v-if="isDayExpanded(dayIndex)">
              <div v-if="day.hotel" class="hotel-strip">
                <Hotel :size="18" />
                <div>
                  <strong>{{ day.hotel.name }}</strong>
                  <small
                    >{{ day.hotel.address }} · {{ day.hotel.price_range }} ·
                    {{ priceText(day.hotel.estimated_cost, day.hotel.price_source) }}/晚</small
                  >
                </div>
                <a-tag v-if="day.hotel.source === 'sample'" color="warning">演示数据</a-tag>
              </div>

              <div
                v-if="day.timeline && day.timeline.length"
                class="timeline-strip"
                aria-label="当天时间轴"
              >
                <div
                  v-for="slot in day.timeline"
                  :key="`${slot.start}-${slot.name}`"
                  class="timeline-slot"
                >
                  <span class="timeline-clock">{{ slot.start }}–{{ slot.end }}</span>
                  <span class="timeline-name">{{ slot.name }}</span>
                </div>
              </div>

              <div class="attraction-list">
                <div
                  v-for="(attraction, attractionIndex) in day.attractions"
                  :key="`${day.date}-${attraction.name}`"
                  class="attraction-item"
                >
                  <div class="attraction-rank">{{ attractionIndex + 1 }}</div>
                  <div>
                    <img
                      v-if="attraction.image_url"
                      :src="attraction.image_url"
                      alt=""
                      loading="lazy"
                      class="attraction-thumb"
                    />
                    <h4>
                      {{ attraction.name }}
                      <a-tag v-if="attraction.level" color="green" class="attraction-level">{{
                        attraction.level
                      }}</a-tag>
                    </h4>
                    <small>
                      {{ attraction.address }} · 建议 {{ attraction.visit_duration }} 分钟 ·
                      {{ ticketText(attraction) }}
                      <template v-if="attraction.opening_hours">
                        · 开放 {{ attraction.opening_hours }}</template
                      >
                      <template v-if="attraction.contact_phone">
                        · {{ attraction.contact_phone }}</template
                      >
                    </small>
                  </div>
                  <div v-if="editMode" class="edit-buttons" data-html2canvas-ignore>
                    <a-button
                      size="small"
                      :disabled="attractionIndex === 0"
                      @click="moveAttraction(dayIndex, attractionIndex, 'up')"
                    >
                      <template #icon><ArrowUp :size="15" /></template>
                    </a-button>
                    <a-button
                      size="small"
                      :disabled="attractionIndex === day.attractions.length - 1"
                      @click="moveAttraction(dayIndex, attractionIndex, 'down')"
                    >
                      <template #icon><ArrowDown :size="15" /></template>
                    </a-button>
                    <a-button
                      size="small"
                      danger
                      @click="deleteAttraction(dayIndex, attractionIndex)"
                    >
                      <template #icon><Trash2 :size="15" /></template>
                    </a-button>
                  </div>
                  <!-- Available outside edit mode on purpose: the user notices a
                       bad stop while reading the plan, not while editing it. -->
                  <div class="feedback-action" data-html2canvas-ignore>
                    <a-dropdown :trigger="['click']" placement="bottomRight">
                      <a-button
                        size="small"
                        type="text"
                        class="feedback-button"
                        :class="{ 'feedback-button-done': isReported(dayIndex, attraction.name) }"
                        :title="
                          isReported(dayIndex, attraction.name)
                            ? '已经记下这个反馈'
                            : '这个安排不对'
                        "
                        :disabled="isReported(dayIndex, attraction.name)"
                        @click="pendingStop = { dayIndex, name: attraction.name }"
                      >
                        <template #icon><Flag :size="14" /></template>
                      </a-button>
                      <template #overlay>
                        <a-menu @click="onFeedbackMenu">
                          <a-menu-item
                            v-for="reason in FEEDBACK_REASONS"
                            :key="reason.value"
                            class="feedback-reason"
                          >
                            {{ reason.label }}
                          </a-menu-item>
                        </a-menu>
                      </template>
                    </a-dropdown>
                  </div>
                </div>
              </div>

              <div v-if="(day.routes || []).length" class="route-list">
                <div
                  v-for="leg in day.routes || []"
                  :key="`${day.date}-${leg.origin}-${leg.destination}`"
                >
                  <Route :size="15" />
                  <span>{{ leg.origin }} → {{ leg.destination }}</span>
                  <small
                    >{{ formatDistance(leg.distance_meters) }} · 约 {{ leg.duration_minutes }} 分钟
                    · {{ leg.mode }}</small
                  >
                </div>
              </div>
            </template>
          </article>
        </div>
      </section>

      <section id="weather" class="section-block">
        <h2>天气信息</h2>
        <div class="weather-grid">
          <div v-for="weather in tripPlan.weather_info" :key="weather.date" class="weather-card">
            <span>{{ weather.date }}</span>
            <strong>{{ weather.day_weather }}</strong>
            <a-tag :color="weather.forecast_available !== false ? 'blue' : 'default'">{{
              weatherSourceLabel(weather.source)
            }}</a-tag>
            <small v-if="weather.forecast_available !== false">
              {{ weather.night_temp }} 至 {{ weather.day_temp }} ℃ · {{ weather.wind_direction }}风
              {{ weather.wind_power }}
            </small>
            <small v-else>{{
              weather.notice || '当前日期暂无可用预报，请在临近出行时再查。'
            }}</small>
          </div>
        </div>
      </section>

      <section v-if="qualityWarnings.length" id="quality" class="section-block">
        <div class="section-title-row">
          <h2>行程提醒</h2>
        </div>
        <a-alert
          v-for="warning in qualityWarnings"
          :key="warning"
          class="quality-warning"
          :message="warning"
          type="warning"
          show-icon
        />
      </section>
    </section>
  </main>

  <main v-else class="empty-state">
    <h1>还没有生成行程</h1>
    <a-button type="primary" @click="router.push('/')">返回首页</a-button>
  </main>
</template>

<script setup lang="ts">
import { message, Modal } from 'ant-design-vue'
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CalendarDays,
  ChevronDown,
  CloudSun,
  Download,
  Flag,
  Hotel,
  MapPinned,
  Pencil,
  Route,
  Save,
  ShieldCheck,
  Trash2,
  Undo2,
  WalletCards
} from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { usePlanEdit } from '../composables/usePlanEdit'
import { usePlanExport } from '../composables/usePlanExport'
import { FEEDBACK_REASONS, usePlanFeedback } from '../composables/usePlanFeedback'
import { usePlanMap } from '../composables/usePlanMap'
import { deleteTripPlan, getTripPlan, reviseTripPlan } from '../services/api'
import type { FeedbackReason } from '../services/api'
import type { TripPlan } from '../types/trip'
import {
  degradedReasonLabel,
  formatDistance,
  nightsFor,
  priceText,
  ticketText,
  weatherSourceLabel
} from '../utils/plan'

const router = useRouter()
const route = useRoute()

const selectedKeys = ref(['overview'])
const expandedDayIndices = ref<number[]>([0])
const pendingStop = ref<{ dayIndex: number; name: string } | null>(null)
const reviseInstruction = ref('')
const revising = ref(false)
const reviseReply = ref('')
const reviseError = ref('')

const routePlanId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const tripPlan = ref<TripPlan | null>(loadInitialPlan())
const allAttractions = computed(() => tripPlan.value?.days.flatMap((day) => day.attractions) || [])
const hotelNights = computed(() => nightsFor(tripPlan.value?.days.length || 1))
const qualityWarnings = computed(() => tripPlan.value?.quality?.warnings || [])

// Each of these owns one concern and cleans up after itself; the view is the glue.
const { mapReady, mapStatus, initMap } = usePlanMap(allAttractions)
const { exportAsImage, exportAsPDF, printPlan } = usePlanExport(tripPlan, expandedDayIndices)
const {
  editMode,
  saving,
  toggleEditMode,
  saveChanges,
  cancelEdit,
  moveAttraction,
  deleteAttraction
} = usePlanEdit(tripPlan, { persist: persistPlan, onSaved: () => void initMap() })
const { isReported, reportStop } = usePlanFeedback(() => tripPlan.value?.id ?? '')

function loadInitialPlan(): TripPlan | null {
  const cached = sessionStorage.getItem('tripPlan')
  if (!cached) return null
  try {
    return JSON.parse(cached) as TripPlan
  } catch {
    // A stale or truncated cache must not blank the page; drop it and refetch.
    sessionStorage.removeItem('tripPlan')
    return null
  }
}

function persistPlan() {
  if (tripPlan.value) {
    sessionStorage.setItem('tripPlan', JSON.stringify(tripPlan.value))
  }
}

function scrollToSection({ key }: { key: string }) {
  selectedKeys.value = [key]
  document.getElementById(key)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function isDayExpanded(dayIndex: number) {
  return expandedDayIndices.value.includes(dayIndex)
}

function toggleDay(dayIndex: number) {
  expandedDayIndices.value = isDayExpanded(dayIndex)
    ? expandedDayIndices.value.filter((index) => index !== dayIndex)
    : [...expandedDayIndices.value, dayIndex]
}

/**
 * Record "this stop is wrong".
 *
 * No confirm dialog and no note field: the value of this signal is that it costs
 * one click, and the note can wait until there is a reason to ask for it. The
 * backend resolves the name against the stored plan, so nothing here is trusted.
 */
async function onFeedbackMenu(info: { key: string | number }) {
  const stop = pendingStop.value
  pendingStop.value = null
  if (!stop) return
  await reportStop(stop.dayIndex, stop.name, String(info.key) as FeedbackReason)
}

function confirmDelete() {
  const id = tripPlan.value?.id
  if (!id) return
  Modal.confirm({
    title: '删除这份行程？',
    content: '删除后无法恢复，历史列表里也不会再出现。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await deleteTripPlan(id)
        sessionStorage.removeItem('tripPlan')
        tripPlan.value = null
        message.success('行程已删除')
        await router.push('/')
      } catch (error) {
        message.error(`删除失败：${error instanceof Error ? error.message : '请稍后再试'}`)
      }
    }
  })
}

async function submitRevision() {
  const instruction = reviseInstruction.value.trim()
  if (!instruction || !tripPlan.value?.id || revising.value) return

  revising.value = true
  reviseReply.value = ''
  reviseError.value = ''
  try {
    const result = await reviseTripPlan(tripPlan.value.id, instruction)
    tripPlan.value = result.plan
    reviseReply.value = result.reply
    reviseInstruction.value = ''
    persistPlan()
    void initMap()
  } catch (error) {
    reviseError.value = error instanceof Error ? error.message : '调整失败，请稍后再试'
  } finally {
    revising.value = false
  }
}

async function loadPlanFromRoute() {
  if (!routePlanId.value) return
  const cached = loadInitialPlan()
  if (cached?.id === routePlanId.value) {
    tripPlan.value = cached
    return
  }
  try {
    tripPlan.value = await getTripPlan(routePlanId.value)
    persistPlan()
  } catch (error) {
    const detail = error instanceof Error ? error.message : '请返回首页重新生成'
    message.error(`行程加载失败：${detail}`)
    tripPlan.value = null
  }
}

onMounted(async () => {
  await loadPlanFromRoute()
  void initMap()
})
</script>
