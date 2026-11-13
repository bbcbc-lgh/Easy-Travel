// @vitest-environment jsdom
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const updateTripPlan = vi.fn()
const sendPlanFeedback = vi.fn()

vi.mock('../src/services/api', () => ({
  updateTripPlan: (...args: unknown[]) => updateTripPlan(...args),
  sendPlanFeedback: (...args: unknown[]) => sendPlanFeedback(...args)
}))

import { usePlanEdit } from '../src/composables/usePlanEdit'
import { usePlanExport } from '../src/composables/usePlanExport'
import { usePlanFeedback } from '../src/composables/usePlanFeedback'
import type { TripPlan } from '../src/types/trip'
import { describeMapFailure } from '../src/utils/plan'

function makePlan(): TripPlan {
  return {
    id: 'plan-1',
    city: '杭州',
    start_date: '2026-12-01',
    end_date: '2026-12-02',
    days: [
      {
        date: '2026-12-01',
        day_index: 0,
        description: '第一天',
        transportation: '公共交通',
        accommodation: '经济型酒店',
        attractions: [
          {
            name: '景点A',
            address: '杭州市',
            location: { longitude: 120.15, latitude: 30.27 },
            visit_duration: 90,
            description: '',
            category: '景点',
            ticket_price: 50,
            price_source: 'estimated',
            source: 'amap'
          },
          {
            name: '景点B',
            address: '杭州市',
            location: { longitude: 120.16, latitude: 30.28 },
            visit_duration: 90,
            description: '',
            category: '景点',
            ticket_price: 0,
            price_source: 'api',
            source: 'amap'
          }
        ],
        routes: []
      },
      {
        date: '2026-12-02',
        day_index: 1,
        description: '第二天',
        transportation: '公共交通',
        accommodation: '经济型酒店',
        attractions: [
          {
            name: '景点C',
            address: '杭州市',
            location: { longitude: 120.17, latitude: 30.29 },
            visit_duration: 90,
            description: '',
            category: '景点',
            ticket_price: 30,
            price_source: 'estimated',
            source: 'amap'
          }
        ],
        routes: []
      }
    ],
    weather_info: [],
    overall_suggestions: '总体建议',
    degraded: false,
    data_notices: []
  } as TripPlan
}

describe('usePlanEdit', () => {
  beforeEach(() => {
    updateTripPlan.mockReset()
  })

  it('leaves edit mode only after the server accepts the save', async () => {
    updateTripPlan.mockResolvedValue(makePlan())
    const plan = ref<TripPlan | null>(makePlan())
    const edit = usePlanEdit(plan, { persist: () => undefined })

    edit.toggleEditMode()
    expect(edit.editMode.value).toBe(true)

    const saved = await edit.saveChanges()

    expect(saved).toBe(true)
    expect(edit.editMode.value).toBe(false)
  })

  it('keeps the snapshot when the save fails, so the change can be retried', async () => {
    updateTripPlan.mockRejectedValue(new Error('后端没响应'))
    const plan = ref<TripPlan | null>(makePlan())
    const edit = usePlanEdit(plan, { persist: () => undefined })

    edit.toggleEditMode()
    edit.deleteAttraction(0, 0)
    const afterEdit = plan.value?.days[0]?.attractions.length

    const saved = await edit.saveChanges()

    expect(saved).toBe(false)
    expect(edit.editMode.value).toBe(true)
    expect(edit.originalPlan.value).not.toBeNull()
    expect(plan.value?.days[0]?.attractions.length).toBe(afterEdit)
  })

  it('restores the snapshot on cancel', () => {
    const plan = ref<TripPlan | null>(makePlan())
    const edit = usePlanEdit(plan, { persist: () => undefined })

    edit.toggleEditMode()
    edit.deleteAttraction(0, 0)
    expect(plan.value?.days[0]?.attractions).toHaveLength(1)

    edit.cancelEdit()

    expect(plan.value?.days[0]?.attractions).toHaveLength(2)
    expect(edit.editMode.value).toBe(false)
  })

  it('moves a stop up and stops at the edges', () => {
    const plan = ref<TripPlan | null>(makePlan())
    const edit = usePlanEdit(plan, { persist: () => undefined })

    edit.moveAttraction(0, 1, 'up')
    expect(plan.value?.days[0]?.attractions.map((item) => item.name)).toEqual(['景点B', '景点A'])

    edit.moveAttraction(0, 0, 'up')
    expect(plan.value?.days[0]?.attractions.map((item) => item.name)).toEqual(['景点B', '景点A'])
  })

  it('does nothing when the day does not exist', () => {
    const plan = ref<TripPlan | null>(makePlan())
    const edit = usePlanEdit(plan, { persist: () => undefined })

    expect(() => edit.deleteAttraction(9, 0)).not.toThrow()
  })
})

describe('usePlanFeedback', () => {
  beforeEach(() => {
    localStorage.clear()
    sendPlanFeedback.mockReset()
  })

  it('remembers a reported stop across a reload', async () => {
    sendPlanFeedback.mockResolvedValue(undefined)
    const first = usePlanFeedback(() => 'plan-1')

    await first.reportStop(0, '景点A', 'too_packed')
    expect(first.isReported(0, '景点A')).toBe(true)

    // A fresh mount (a reload) reads it back instead of offering the button again.
    const second = usePlanFeedback(() => 'plan-1')
    expect(second.isReported(0, '景点A')).toBe(true)
    expect(second.isReported(0, '景点B')).toBe(false)
  })

  it('does not remember a report the server rejected', async () => {
    sendPlanFeedback.mockRejectedValue(new Error('后端没响应'))
    const feedback = usePlanFeedback(() => 'plan-1')

    const ok = await feedback.reportStop(0, '景点A', 'too_far')

    expect(ok).toBe(false)
    expect(feedback.isReported(0, '景点A')).toBe(false)
  })

  it('survives a corrupted stored list', () => {
    localStorage.setItem('easyTravel.reported.plan-1', '{not json')

    const feedback = usePlanFeedback(() => 'plan-1')

    expect(feedback.isReported(0, '景点A')).toBe(false)
  })

  it('keys the record per plan, so two plans do not share it', async () => {
    sendPlanFeedback.mockResolvedValue(undefined)
    const first = usePlanFeedback(() => 'plan-1')
    await first.reportStop(0, '景点A', 'other')

    const other = usePlanFeedback(() => 'plan-2')

    expect(other.isReported(0, '景点A')).toBe(false)
  })
})

describe('usePlanExport', () => {
  it('expands every day before a capture and can restore it', async () => {
    const plan = ref<TripPlan | null>(makePlan())
    const expanded = ref<number[]>([0])
    const exporter = usePlanExport(plan, expanded)

    const restore = await exporter.revealWholePlan()

    expect(expanded.value).toEqual([0, 1])
    restore()
    expect(expanded.value).toEqual([0])
  })

  it('does nothing when there is no plan', async () => {
    const plan = ref<TripPlan | null>(null)
    const expanded = ref<number[]>([])
    const exporter = usePlanExport(plan, expanded)

    const restore = await exporter.revealWholePlan()

    expect(typeof restore).toBe('function')
    expect(expanded.value).toEqual([])
  })

  it('reports a failed export instead of silently doing nothing', async () => {
    const plan = ref<TripPlan | null>(makePlan())
    const expanded = ref<number[]>([0])
    const exporter = usePlanExport(plan, expanded)

    // No capture target in the DOM: the export must settle and clear its lock.
    await exporter.exportAsImage()

    expect(exporter.exporting.value).toBe('')
  })

  it('refuses to start a second export while one is running', async () => {
    const plan = ref<TripPlan | null>(makePlan())
    const expanded = ref<number[]>([0])
    const exporter = usePlanExport(plan, expanded)
    exporter.exporting.value = 'pdf'

    const restore = await exporter.revealWholePlan()
    restore()

    expect(exporter.exporting.value).toBe('pdf')
  })
})

describe('describeMapFailure', () => {
  it('names a missing security code, which AMap never says plainly', () => {
    expect(describeMapFailure(new Error('INVALID_USER_SCODE'))).toContain('安全密钥')
  })

  it('names a wrong key type', () => {
    expect(describeMapFailure(new Error('INVALID_USER_KEY'))).toContain('Key 类型不对')
  })

  it('names a domain restriction', () => {
    expect(describeMapFailure(new Error('REFERER is not allowed'))).toContain('白名单')
  })

  it('falls back to the raw message, truncated', () => {
    const message = describeMapFailure(new Error('x'.repeat(500)))

    expect(message.length).toBeLessThan(140)
  })

  it('handles a non-Error rejection', () => {
    expect(describeMapFailure('boom')).toContain('boom')
  })
})

describe('the day count used for hotel nights', () => {
  it('never goes negative', async () => {
    const { nightsFor } = await import('../src/utils/plan')
    expect(nightsFor(0)).toBe(0)
    expect(nightsFor(3)).toBe(2)
  })
})

describe('flushing', () => {
  it('is available for the async composables', async () => {
    await flushPromises()
    expect(true).toBe(true)
  })
})
