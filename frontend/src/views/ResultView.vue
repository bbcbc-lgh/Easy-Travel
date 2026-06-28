<template>
  <main class="result-shell" v-if="tripPlan">
    <aside class="side-nav">
      <a-button class="back-button" @click="router.push('/')">
        <template #icon><ArrowLeft :size="17" /></template>
        返回
      </a-button>
      <a-menu v-model:selectedKeys="selectedKeys" mode="inline" @click="scrollToSection">
        <a-menu-item key="overview"><LayoutDashboard :size="16" /> 行程概览</a-menu-item>
        <a-menu-item key="quality"><ShieldCheck :size="16" /> 质量检查</a-menu-item>
        <a-menu-item key="budget"><WalletCards :size="16" /> 预算明细</a-menu-item>
        <a-menu-item key="map"><MapPinned :size="16" /> 地图路线</a-menu-item>
        <a-menu-item key="days"><CalendarDays :size="16" /> 每日行程</a-menu-item>
        <a-menu-item key="weather"><CloudSun :size="16" /> 天气信息</a-menu-item>
      </a-menu>
    </aside>

    <section class="result-content" id="trip-plan-content">
      <header class="result-header" id="overview">
        <div>
          <p class="eyebrow">Trip Plan</p>
          <h1>{{ tripPlan.city }} {{ tripPlan.days.length }} 天游</h1>
          <p>{{ tripPlan.start_date }} 至 {{ tripPlan.end_date }}</p>
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

      <a-alert class="suggestion" :message="tripPlan.overall_suggestions" type="info" show-icon />

      <section class="section-block quality-block" id="quality" v-if="tripPlan.quality">
        <div class="section-title-row">
          <h2>质量检查</h2>
          <a-tag :color="qualityColor">{{ tripPlan.quality.score }} 分</a-tag>
        </div>
        <div class="quality-grid">
          <div v-for="item in qualityChecks" :key="item.key" class="quality-item">
            <CheckCircle2 v-if="item.passed" :size="18" class="quality-pass" />
            <CircleAlert v-else :size="18" class="quality-warn" />
            <span>{{ item.label }}</span>
          </div>
        </div>
        <a-alert
          v-if="tripPlan.quality.warnings.length"
          class="quality-warning"
          type="warning"
          show-icon
          :message="tripPlan.quality.warnings.join(' ')"
        />
      </section>

      <section class="section-block" id="budget" v-if="tripPlan.budget">
        <h2>预算明细</h2>
        <div class="budget-grid">
          <a-statistic title="景点门票" :value="tripPlan.budget.total_attractions" suffix="元" />
          <a-statistic title="酒店住宿" :value="tripPlan.budget.total_hotels" suffix="元" />
          <a-statistic title="餐饮费用" :value="tripPlan.budget.total_meals" suffix="元" />
          <a-statistic title="交通费用" :value="tripPlan.budget.total_transportation" suffix="元" />
          <a-statistic class="total-budget" title="预估总费用" :value="tripPlan.budget.total" suffix="元" />
        </div>
      </section>

      <section class="section-block" id="map" data-html2canvas-ignore>
        <h2>地图路线</h2>
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
          <article v-for="(day, dayIndex) in tripPlan.days" :key="day.date" class="day-card">
            <div class="day-card-header">
              <div>
                <span>Day {{ day.day_index + 1 }}</span>
                <h3>{{ day.date }}</h3>
                <p>{{ day.description }}</p>
              </div>
              <a-tag>{{ day.transportation }}</a-tag>
            </div>

            <div v-if="day.hotel" class="hotel-strip">
              <Hotel :size="18" />
              <span>{{ day.hotel.name }}</span>
              <small>{{ day.hotel.price_range }} · {{ day.hotel.distance }}</small>
            </div>

            <div class="attraction-list">
              <div v-for="(attraction, attractionIndex) in day.attractions" :key="`${day.date}-${attraction.name}`" class="attraction-item">
                <div>
                  <h4>{{ attraction.name }}</h4>
                  <p>{{ attraction.description }}</p>
                  <small>{{ attraction.category }} · {{ attraction.visit_duration }} 分钟 · 门票 {{ attraction.ticket_price }} 元</small>
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

            <div class="meal-row">
              <a-tag v-for="meal in day.meals" :key="meal.type">{{ meal.name }} {{ meal.estimated_cost }} 元</a-tag>
            </div>

            <div v-if="(day.routes || []).length" class="route-list">
              <div v-for="route in day.routes || []" :key="`${day.date}-${route.origin}-${route.destination}`">
                <Route :size="15" />
                <span>{{ route.origin }} → {{ route.destination }}</span>
                <small>{{ formatDistance(route.distance_meters) }} · 约 {{ route.duration_minutes }} 分钟 · {{ route.mode }}</small>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section class="section-block" id="weather">
        <h2>天气信息</h2>
        <div class="weather-grid">
          <div v-for="weather in tripPlan.weather_info" :key="weather.date" class="weather-card">
            <span>{{ weather.date }}</span>
            <strong>{{ weather.day_weather }}</strong>
            <small v-if="weather.forecast_available !== false">
              {{ weather.night_temp }} 至 {{ weather.day_temp }} ℃ · {{ weather.wind_direction }}风 {{ weather.wind_power }}
            </small>
            <small v-else>{{ weather.notice || '行程日期太久远，无法保证查询天气。' }}</small>
          </div>
        </div>
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
  CheckCircle2,
  CircleAlert,
  CloudSun,
  Download,
  Hotel,
  LayoutDashboard,
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
const qualityLabels: Record<string, string> = {
  no_duplicate_attractions: '景点不重复',
  all_days_have_attractions: '每日有行程',
  daily_duration_reasonable: '每日强度合理',
  weather_complete: '天气覆盖完整',
  enough_candidates: '候选景点充足'
}
const qualityChecks = computed(() =>
  Object.entries(tripPlan.value?.quality?.checks || {}).map(([key, passed]) => ({
    key,
    passed,
    label: qualityLabels[key] || key
  }))
)
const qualityColor = computed(() => {
  const score = tripPlan.value?.quality?.score || 0
  if (score >= 85) return 'green'
  if (score >= 70) return 'gold'
  return 'red'
})
let mapInstance: { destroy: () => void } | null = null

function loadInitialPlan(): TripPlan | null {
  const cached = sessionStorage.getItem('tripPlan')
  return cached ? (JSON.parse(cached) as TripPlan) : null
}

function scrollToSection({ key }: { key: string }) {
  selectedKeys.value = [key]
  document.getElementById(key)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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
  const canvas = await html2canvas(element, { backgroundColor: '#ffffff', scale: 2, useCORS: true })
  const link = document.createElement('a')
  link.download = `${tripPlan.value.city}旅行计划.png`
  link.href = canvas.toDataURL('image/png')
  link.click()
}

async function exportAsPDF() {
  const element = document.getElementById('trip-plan-content')
  if (!element || !tripPlan.value) return
  const canvas = await html2canvas(element, { backgroundColor: '#ffffff', scale: 2, useCORS: true })
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
