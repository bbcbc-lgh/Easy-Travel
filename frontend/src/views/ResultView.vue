<template>
  <main class="result-shell" v-if="tripPlan">
    <aside class="side-nav">
      <a-button class="back-button" @click="router.push('/')">
        <template #icon><ArrowLeft :size="17" /></template>
        返回
      </a-button>
      <a-menu v-model:selectedKeys="selectedKeys" mode="inline" @click="scrollToSection">
        <a-menu-item key="budget"><WalletCards :size="16" /> 预算明细</a-menu-item>
        <a-menu-item key="map"><MapPinned :size="16" /> 地图路线</a-menu-item>
        <a-menu-item key="days"><CalendarDays :size="16" /> 每日行程</a-menu-item>
        <a-menu-item key="weather"><CloudSun :size="16" /> 天气信息</a-menu-item>
        <a-menu-item v-if="qualityWarnings.length" key="quality"><ShieldCheck :size="16" /> 行程提醒</a-menu-item>
      </a-menu>
    </aside>

    <section class="result-content" id="trip-plan-content">
      <header class="result-header" id="overview">
        <div>
          <p class="eyebrow">行程计划</p>
          <h1>{{ tripPlan.city }} <span class="trip-day-count">{{ tripPlan.days.length }}</span> 天游</h1>
          <p>{{ tripPlan.start_date }} 至 {{ tripPlan.end_date }}</p>
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
          <a-button v-if="editMode" type="primary" @click="saveChanges">
            <template #icon><Save :size="17" /></template>
            保存
          </a-button>
          <a-button v-if="editMode" @click="cancelEdit">
            <template #icon><Undo2 :size="17" /></template>
            取消
          </a-button>
          <a-button v-if="tripPlan.id" @click="copyShareLink">
            <template #icon><Link2 :size="17" /></template>
            复制链接
          </a-button>
          <a-dropdown :trigger="['click']">
            <a-button>
              <template #icon><Download :size="17" /></template>
              导出
            </a-button>
            <template #overlay>
              <a-menu>
                <a-menu-item @click="exportAsImage">导出图片</a-menu-item>
                <a-menu-item @click="exportAsPDF">导出 PDF</a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
      </header>

      <a-alert
        v-for="notice in tripPlan.data_notices || []"
        :key="notice"
        class="data-notice"
        :message="notice"
        type="warning"
        show-icon
      />

      <section class="section-block" id="budget" v-if="tripPlan.budget">
        <h2>预算明细</h2>
        <div class="budget-grid">
          <a-statistic title="景点门票" :value="tripPlan.budget.total_attractions" suffix="元" />
          <a-statistic title="酒店住宿" :value="tripPlan.budget.total_hotels" suffix="元" />
          <a-statistic title="餐饮费用" :value="tripPlan.budget.total_meals" suffix="元" />
          <a-statistic title="交通费用" :value="tripPlan.budget.total_transportation" suffix="元" />
          <a-statistic class="total-budget" title="预估总费用" :value="tripPlan.budget.total" suffix="元" />
        </div>
        <p class="budget-note">住宿按 {{ hotelNights }} 晚计算（{{ tripPlan.days.length }} 天行程通常为 {{ hotelNights }} 晚）；不含往返大交通、购物和个人消费。预算档位不会覆盖你单独选择的住宿与交通方式。</p>
      </section>

      <section class="section-block" id="map" data-html2canvas-ignore>
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

      <section class="section-block" id="days">
        <h2>每日行程</h2>
        <div class="day-list">
          <article v-for="(day, dayIndex) in tripPlan.days" :key="day.date" class="day-card" :class="{ 'is-collapsed': !isDayExpanded(dayIndex) }">
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
                <small>{{ day.hotel.address }}  ·  {{ day.hotel.price_range }}  ·  约 {{ day.hotel.estimated_cost }} 元/晚</small>
              </div>
              <a-tag v-if="day.hotel.source === 'sample'" color="warning">演示数据</a-tag>
            </div>

              <div class="attraction-list">
              <div v-for="(attraction, attractionIndex) in day.attractions" :key="`${day.date}-${attraction.name}`" class="attraction-item">
                <div class="attraction-rank">{{ attractionIndex + 1 }}</div>
                <div>
                  <h4>{{ attraction.name }}</h4>
                  <small>{{ attraction.address }} · 建议 {{ attraction.visit_duration }} 分钟 · 门票 {{ attraction.ticket_price }} 元</small>
                </div>
                <div v-if="editMode" class="edit-buttons" data-html2canvas-ignore>
                  <a-button size="small" :disabled="attractionIndex === 0" @click="moveAttraction(dayIndex, attractionIndex, 'up')">
                    <template #icon><ArrowUp :size="15" /></template>
                  </a-button>
                  <a-button size="small" :disabled="attractionIndex === day.attractions.length - 1" @click="moveAttraction(dayIndex, attractionIndex, 'down')">
                    <template #icon><ArrowDown :size="15" /></template>
                  </a-button>
                  <a-button size="small" danger @click="deleteAttraction(dayIndex, attractionIndex)">
                    <template #icon><Trash2 :size="15" /></template>
                  </a-button>
                </div>
              </div>
              </div>

              <div class="meal-list">
              <div v-for="meal in day.meals" :key="`${day.date}-${meal.type}-${meal.name}`" class="meal-item">
                <div>
                  <span>{{ mealTypeLabel(meal.type) }}</span>
                  <strong>{{ meal.name }}</strong>
                  <small>{{ meal.address || meal.description || '暂无可导航地址' }}</small>
                </div>
                <div class="meal-cost">
                  <a-tag v-if="meal.source === 'sample'" color="warning">演示数据</a-tag>
                  <span>约 {{ meal.estimated_cost }} 元</span>
                </div>
              </div>
              </div>

              <div v-if="(day.routes || []).length" class="route-list">
              <div v-for="route in day.routes || []" :key="`${day.date}-${route.origin}-${route.destination}`">
                <Route :size="15" />
                <span>{{ route.origin }} → {{ route.destination }}</span>
                <small>{{ formatDistance(route.distance_meters) }} · 约 {{ route.duration_minutes }} 分钟 · {{ route.mode }}</small>
              </div>
              </div>
            </template>
          </article>
        </div>
      </section>

      <section class="section-block" id="weather">
        <h2>天气信息</h2>
        <div class="weather-grid">
          <div v-for="weather in tripPlan.weather_info" :key="weather.date" class="weather-card">
            <span>{{ weather.date }}</span>
            <strong>{{ weather.day_weather }}</strong>
            <a-tag :color="weather.forecast_available !== false ? 'blue' : 'default'">{{ weatherSourceLabel(weather.source) }}</a-tag>
            <small v-if="weather.forecast_available !== false">
              {{ weather.night_temp }} 至 {{ weather.day_temp }} ℃ · {{ weather.wind_direction }}风 {{ weather.wind_power }}
            </small>
            <small v-else>{{ weather.notice || '当前日期暂无可用预报，请在临近出行时再查。' }}</small>
          </div>
        </div>
      </section>

      <section v-if="qualityWarnings.length" class="section-block" id="quality">
        <div class="section-title-row">
          <h2>行程提醒</h2>
        </div>
        <a-alert v-for="warning in qualityWarnings" :key="warning" class="quality-warning" :message="warning" type="warning" show-icon />
      </section>
    </section>
  </main>

  <main class="empty-state" v-else>
    <h1>还没有生成行程</h1>
    <a-button type="primary" @click="router.push('/')">返回首页</a-button>
  </main>
</template>

<script setup lang="ts">
import AMapLoader from '@amap/amap-jsapi-loader'
import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CalendarDays,
  ChevronDown,
  CloudSun,
  Download,
  Hotel,
  Link2,
  MapPinned,
  Pencil,
  Route,
  Save,
  ShieldCheck,
  Trash2,
  Undo2,
  WalletCards
} from 'lucide-vue-next'
import { message } from 'ant-design-vue'
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getTripPlan, updateTripPlan } from '../services/api'
import type { TripPlan } from '../types/trip'

const router = useRouter()
const route = useRoute()
const selectedKeys = ref(['overview'])
const editMode = ref(false)
const originalPlan = ref<TripPlan | null>(null)
const mapReady = ref(false)
const mapStatus = ref('正在准备地图')

const routePlanId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const tripPlan = ref<TripPlan | null>(loadInitialPlan())
const allAttractions = computed(() => tripPlan.value?.days.flatMap((day) => day.attractions) || [])
const hotelNights = computed(() => Math.max((tripPlan.value?.days.length || 1) - 1, 1))
const expandedDayIndices = ref<number[]>([0])
const qualityWarnings = computed(() => tripPlan.value?.quality?.warnings || [])
let mapInstance: { destroy: () => void } | null = null

function loadInitialPlan(): TripPlan | null {
  const cached = sessionStorage.getItem('tripPlan')
  return cached ? (JSON.parse(cached) as TripPlan) : null
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

function toggleEditMode() {
  editMode.value = !editMode.value
  if (editMode.value && tripPlan.value) {
    originalPlan.value = JSON.parse(JSON.stringify(tripPlan.value)) as TripPlan
  }
}

async function saveChanges() {
  editMode.value = false
  originalPlan.value = null
  if (tripPlan.value?.id) {
    try {
      tripPlan.value = await updateTripPlan(tripPlan.value.id, tripPlan.value)
    } catch (error) {
      const detail = error instanceof Error ? error.message : '请稍后再试'
      message.error(`保存失败：${detail}`)
      return
    }
  }
  persistPlan()
  void initMap()
  message.success('修改已保存')
}

function cancelEdit() {
  if (originalPlan.value) {
    tripPlan.value = originalPlan.value
  }
  editMode.value = false
  originalPlan.value = null
  void initMap()
}

function moveAttraction(dayIndex: number, attractionIndex: number, direction: 'up' | 'down') {
  const attractions = tripPlan.value?.days[dayIndex].attractions
  if (!attractions) return
  const newIndex = direction === 'up' ? attractionIndex - 1 : attractionIndex + 1
  if (newIndex >= 0 && newIndex < attractions.length) {
    ;[attractions[attractionIndex], attractions[newIndex]] = [attractions[newIndex], attractions[attractionIndex]]
  }
}

function deleteAttraction(dayIndex: number, attractionIndex: number) {
  tripPlan.value?.days[dayIndex].attractions.splice(attractionIndex, 1)
}

function persistPlan() {
  if (tripPlan.value) {
    sessionStorage.setItem('tripPlan', JSON.stringify(tripPlan.value))
  }
}

function formatDistance(value: number) {
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)} 公里`
  }
  return `${value} 米`
}

function mealTypeLabel(type: string) {
  return { breakfast: '早餐', lunch: '午餐', dinner: '晚餐', snack: '加餐' }[type] || '餐饮'
}

function weatherSourceLabel(source?: string) {
  return { amap: '高德天气', open_meteo: '天气预报', sample: '演示天气', unavailable: '暂无预报' }[source || 'unavailable'] || '暂无预报'
}

async function copyShareLink() {
  if (!tripPlan.value?.id) return
  const url = `${window.location.origin}/result/${tripPlan.value.id}`
  await navigator.clipboard.writeText(url)
  message.success('链接已复制')
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

async function initMap() {
  mapReady.value = false
  mapStatus.value = '正在准备地图'
  const key = import.meta.env.VITE_AMAP_JS_KEY
  if (!key) {
    mapStatus.value = '未配置 VITE_AMAP_JS_KEY，当前显示为静态行程数据'
    return
  }
  if (!allAttractions.value.length) {
    mapStatus.value = '暂无景点坐标'
    return
  }

  try {
    await nextTick()
    mapInstance?.destroy()
    mapInstance = null
    const first = allAttractions.value[0]
    const AMap = await AMapLoader.load({ key, version: '2.0' })
    const map = new AMap.Map('amap-container', {
      zoom: 12,
      center: [first.location.longitude, first.location.latitude]
    })
    mapInstance = map
    allAttractions.value.forEach((attraction, index) => {
      const marker = new AMap.Marker({
        position: [attraction.location.longitude, attraction.location.latitude],
        title: attraction.name,
        label: { content: `${index + 1}`, direction: 'top' }
      })
      map.add(marker)
    })
    mapReady.value = true
  } catch (error) {
    mapStatus.value = '地图加载失败，请检查高德 JS Key'
  }
}

async function exportAsImage() {
  const element = document.getElementById('trip-plan-content')
  if (!element || !tripPlan.value) return
  const visibleDays = [...expandedDayIndices.value]
  expandedDayIndices.value = tripPlan.value.days.map((_, index) => index)
  await nextTick()
  const canvas = await html2canvas(element, { backgroundColor: '#ffffff', scale: 2, useCORS: true })
  expandedDayIndices.value = visibleDays
  const link = document.createElement('a')
  link.download = `${tripPlan.value.city}旅行计划.png`
  link.href = canvas.toDataURL('image/png')
  link.click()
}

async function exportAsPDF() {
  const element = document.getElementById('trip-plan-content')
  if (!element || !tripPlan.value) return
  const visibleDays = [...expandedDayIndices.value]
  expandedDayIndices.value = tripPlan.value.days.map((_, index) => index)
  await nextTick()
  const canvas = await html2canvas(element, { backgroundColor: '#ffffff', scale: 2, useCORS: true })
  expandedDayIndices.value = visibleDays
  const pdf = new jsPDF('p', 'mm', 'a4')
  const imgData = canvas.toDataURL('image/png')
  const imgWidth = 210
  const imgHeight = (canvas.height * imgWidth) / canvas.width
  pdf.addImage(imgData, 'PNG', 0, 0, imgWidth, imgHeight)
  pdf.save(`${tripPlan.value.city}旅行计划.pdf`)
}

onMounted(async () => {
  await loadPlanFromRoute()
  void initMap()
})
</script>
