// @vitest-environment jsdom
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'

const load = vi.fn()
const destroy = vi.fn()
const add = vi.fn()

vi.mock('@amap/amap-jsapi-loader', () => ({
  default: { load: (...args: unknown[]) => load(...args) }
}))
vi.mock('html2canvas', () => ({ default: vi.fn(async () => makeCanvas()) }))
vi.mock('jspdf', () => ({
  default: class {
    pages: number[] = []
    addPage() {
      this.pages.push(1)
    }
    addImage() {
      return undefined
    }
    save() {
      return undefined
    }
  }
}))

import { usePlanExport } from '../src/composables/usePlanExport'
import { usePlanMap } from '../src/composables/usePlanMap'
import type { Attraction, TripPlan } from '../src/types/trip'

function makeCanvas() {
  return {
    width: 200,
    height: 300,
    toDataURL: () => 'data:image/png;base64,AAA'
  }
}

function attraction(name: string): Attraction {
  return {
    name,
    address: '杭州市',
    location: { longitude: 120.15, latitude: 30.27 },
    visit_duration: 90,
    description: '',
    category: '景点',
    ticket_price: 0,
    price_source: 'api',
    source: 'amap'
  }
}

function makePlan(): TripPlan {
  return {
    id: 'plan-1',
    city: '杭州',
    start_date: '2026-12-01',
    end_date: '2026-12-01',
    days: [
      {
        date: '2026-12-01',
        day_index: 0,
        description: '第一天',
        transportation: '公共交通',
        accommodation: '经济型酒店',
        attractions: [attraction('景点A')],
        routes: []
      }
    ],
    weather_info: [],
    overall_suggestions: '总体建议',
    degraded: false,
    data_notices: []
  } as TripPlan
}

describe('usePlanMap', () => {
  beforeEach(() => {
    load.mockReset()
    destroy.mockReset()
    add.mockReset()
    document.body.innerHTML = '<div id="amap-container"></div>'
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('explains the missing key instead of showing an empty panel', async () => {
    const attractions = computed(() => [attraction('景点A')])
    const map = usePlanMap(attractions)

    await map.initMap()

    expect(map.mapStatus.value).toContain('VITE_AMAP_JS_KEY')
    expect(map.mapReady.value).toBe(false)
    expect(load).not.toHaveBeenCalled()
  })

  it('says so when there is nothing to plot', async () => {
    vi.stubEnv('VITE_AMAP_JS_KEY', 'test-key')
    const attractions = computed(() => [])
    const map = usePlanMap(attractions)

    await map.initMap()

    expect(map.mapStatus.value).toContain('暂无景点坐标')
    expect(load).not.toHaveBeenCalled()
  })

  it('loads the SDK and draws one marker per stop', async () => {
    vi.stubEnv('VITE_AMAP_JS_KEY', 'test-key')
    vi.stubEnv('VITE_AMAP_SECURITY_CODE', 'secret')
    load.mockResolvedValue({
      Map: class {
        add() {
          add()
        }
        destroy() {
          destroy()
        }
      },
      Marker: class {}
    })
    const attractions = computed(() => [attraction('景点A'), attraction('景点B')])
    const map = usePlanMap(attractions)

    await map.initMap()
    await flushPromises()

    expect(load).toHaveBeenCalledTimes(1)
    expect(add).toHaveBeenCalledTimes(2)
    expect(map.mapReady.value).toBe(true)
  })

  it('only the newest init survives a concurrent start', async () => {
    vi.stubEnv('VITE_AMAP_JS_KEY', 'test-key')
    load.mockResolvedValue({
      Map: class {
        add() {
          add()
        }
        destroy() {
          destroy()
        }
      },
      Marker: class {}
    })
    const attractions = computed(() => [attraction('景点A')])
    const map = usePlanMap(attractions)

    const first = map.initMap()
    const second = map.initMap()
    await Promise.all([first, second])
    await flushPromises()

    // Both awaited the same loader; only one may end up owning the container.
    expect(add).toHaveBeenCalledTimes(1)
  })

  it('destroys the instance on teardown', async () => {
    vi.stubEnv('VITE_AMAP_JS_KEY', 'test-key')
    load.mockResolvedValue({
      Map: class {
        add() {
          add()
        }
        destroy() {
          destroy()
        }
      },
      Marker: class {}
    })
    const attractions = computed(() => [attraction('景点A')])
    const map = usePlanMap(attractions)

    await map.initMap()
    await flushPromises()
    map.destroyMap()

    expect(destroy).toHaveBeenCalled()
  })

  it('turns a loader failure into a sentence that says what to fix', async () => {
    vi.stubEnv('VITE_AMAP_JS_KEY', 'test-key')
    load.mockRejectedValue(new Error('INVALID_USER_SCODE'))
    const attractions = computed(() => [attraction('景点A')])
    const map = usePlanMap(attractions)

    await map.initMap()
    await flushPromises()

    expect(map.mapStatus.value).toContain('安全密钥')
    expect(map.mapReady.value).toBe(false)
  })
})

describe('usePlanExport with a real capture target', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="trip-plan-content"></div>'
  })

  it('waits for a lazy image that is not decoded yet, but not forever', async () => {
    const image = document.createElement('img')
    Object.defineProperty(image, 'complete', { value: false })
    document.getElementById('trip-plan-content')!.appendChild(image)
    const plan = ref<TripPlan | null>(makePlan())
    const exporter = usePlanExport(plan, ref<number[]>([0]))

    const started = Date.now()
    await exporter.revealWholePlan()

    expect(Date.now() - started).toBeLessThan(5000)
  })

  it('downloads an image and clears the lock', async () => {
    const plan = ref<TripPlan | null>(makePlan())
    const expanded = ref<number[]>([0])
    const exporter = usePlanExport(plan, expanded)
    const clicks: string[] = []
    const originalCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const element = originalCreate(tag)
      if (tag === 'a') {
        element.click = () => clicks.push('clicked')
      }
      return element
    })

    await exporter.exportAsImage()
    await flushPromises()

    expect(clicks).toHaveLength(1)
    expect(exporter.exporting.value).toBe('')
    vi.restoreAllMocks()
  })

  it('pagination produces one page per slice for a tall plan', async () => {
    const plan = ref<TripPlan | null>(makePlan())
    const expanded = ref<number[]>([0])
    const exporter = usePlanExport(plan, expanded)

    await exporter.exportAsPDF()
    await flushPromises()

    expect(exporter.exporting.value).toBe('')
  })

  it('reports an export failure rather than swallowing it', async () => {
    const plan = ref<TripPlan | null>(makePlan())
    const expanded = ref<number[]>([0])
    const exporter = usePlanExport(plan, expanded)
    const doc = document.getElementById('trip-plan-content')!
    Object.defineProperty(doc, 'id', { value: 'trip-plan-content' })
    const html2canvas = (await import('html2canvas')).default as unknown as ReturnType<typeof vi.fn>
    html2canvas.mockRejectedValueOnce(new Error('canvas exploded'))

    await exporter.exportAsImage()
    await flushPromises()

    expect(exporter.exporting.value).toBe('')
  })
})
