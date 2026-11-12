// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import Antd from 'ant-design-vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

const getTripPlan = vi.fn()
const updateTripPlan = vi.fn()
const sendPlanFeedback = vi.fn()

vi.mock('../src/services/api', () => ({
  getTripPlan: (...args: unknown[]) => getTripPlan(...args),
  updateTripPlan: (...args: unknown[]) => updateTripPlan(...args),
  deleteTripPlan: vi.fn(),
  reviseTripPlan: vi.fn(),
  sendPlanFeedback: (...args: unknown[]) => sendPlanFeedback(...args)
}))

import ResultView from '../src/views/ResultView.vue'

function attraction(name: string) {
  return {
    name,
    address: '杭州市',
    location: { longitude: 120.15, latitude: 30.27 },
    visit_duration: 90,
    description: '',
    category: '景点',
    rating: 4.5,
    image_url: null,
    ticket_price: 50,
    price_source: 'estimated',
    opening_hours: null,
    contact_phone: null,
    level: null,
    source: 'amap'
  }
}

function plan() {
  const day = (index: number) => ({
    date: `2026-12-0${index + 1}`,
    day_index: index,
    description: `第 ${index + 1} 天`,
    transportation: '公共交通',
    accommodation: '经济型酒店',
    hotel: {
      name: '甲酒店',
      address: '杭州市',
      estimated_cost: 300,
      price_source: 'estimated',
      source: 'amap'
    },
    attractions: [attraction(`景点${index}-1`), attraction(`景点${index}-2`)],
    meals: [
      {
        type: 'breakfast',
        name: '早餐铺',
        address: '杭州',
        estimated_cost: 20,
        price_source: 'estimated',
        source: 'amap'
      }
    ],
    routes: []
  })

  return {
    id: 'plan-1',
    city: '杭州',
    start_date: '2026-12-01',
    end_date: '2026-12-02',
    days: [day(0), day(1)],
    weather_info: [],
    overall_suggestions: '总体建议',
    budget: {
      total_attractions: 0,
      total_hotels: 0,
      total_meals: 0,
      total_transportation: 0,
      total: 0
    },
    quality: { score: 80, warnings: [], checks: {} },
    degraded: false,
    degraded_reason: null,
    data_notices: []
  }
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/plans', name: 'plans', component: { template: '<div />' } },
      { path: '/result/:id', name: 'plan-detail', component: ResultView }
    ]
  })
}

async function mountResult() {
  sessionStorage.setItem('tripPlan', JSON.stringify(plan()))
  const router = makeRouter()
  await router.push('/result/plan-1')
  await router.isReady()

  const wrapper = mount(ResultView, { global: { plugins: [Antd, router] } })
  await flushPromises()
  return wrapper
}

describe('ResultView', () => {
  beforeEach(() => {
    sessionStorage.clear()
    getTripPlan.mockReset()
    updateTripPlan.mockReset()
    sendPlanFeedback.mockReset()
  })

  it('renders one card per day, with the day count and city', async () => {
    const wrapper = await mountResult()

    expect(wrapper.findAll('article.day-card')).toHaveLength(2)
    expect(wrapper.text()).toContain('杭州')
    expect(wrapper.text()).toContain('第 1 天')
    expect(wrapper.text()).toContain('第 2 天')
  })

  it('uses the cached plan instead of refetching it', async () => {
    await mountResult()

    expect(getTripPlan).not.toHaveBeenCalled()
  })

  it('shows save and cancel controls only while editing', async () => {
    const wrapper = await mountResult()
    const buttons = () => wrapper.findAll('button').map((button) => button.text())

    expect(buttons()).toContain('编辑行程')
    expect(buttons()).not.toContain('保存')

    const editButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('编辑行程'))
    expect(editButton).toBeTruthy()
    await editButton!.trigger('click')

    expect(buttons()).toContain('保存')
    expect(buttons()).toContain('取消')
  })

  it('drops a stop when its delete control is used, and saves what remains', async () => {
    updateTripPlan.mockResolvedValue(plan())
    const wrapper = await mountResult()

    const before = wrapper.findAll('.attraction-item').length
    expect(before).toBeGreaterThan(0)

    const editButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('编辑行程'))
    await editButton!.trigger('click')

    // The trash icon is the last button in the row's edit controls.
    await wrapper.get('.attraction-item .edit-buttons button:last-child').trigger('click')
    expect(wrapper.findAll('.attraction-item').length).toBe(before - 1)

    const saveButton = wrapper.findAll('button').find((button) => button.text() === '保存')
    await saveButton!.trigger('click')
    await flushPromises()

    expect(updateTripPlan).toHaveBeenCalledTimes(1)
    const savedPayload = updateTripPlan.mock.calls[0]?.[1] as { days: { attractions: unknown[] }[] }
    expect(savedPayload.days[0]?.attractions).toHaveLength(1)
  })
})

describe('feedback on a stop', () => {
  it('records the reason and then goes quiet', async () => {
    sendPlanFeedback.mockResolvedValue(undefined)
    const wrapper = await mountResult()

    const flag = wrapper.get('button.feedback-button')
    expect(flag.attributes('disabled')).toBeUndefined()

    await flag.trigger('click')
    await flushPromises()

    const reason = [...document.querySelectorAll('.ant-dropdown-menu-item')].find((item) =>
      item.textContent?.includes('排得太满')
    )
    expect(reason, 'the reason menu should open on click').toBeTruthy()
    ;(reason as HTMLElement).click()
    await flushPromises()

    expect(sendPlanFeedback).toHaveBeenCalledTimes(1)
    expect(sendPlanFeedback).toHaveBeenCalledWith(
      'plan-1',
      expect.objectContaining({
        day_index: 0,
        target: 'attraction',
        reason: 'too_packed'
      })
    )

    // One complaint per stop: the button must not invite a duplicate.
    expect(wrapper.get('button.feedback-button').attributes('disabled')).toBeDefined()
  })

  it('reports a failure instead of pretending it was saved', async () => {
    sendPlanFeedback.mockRejectedValue(new Error('后端没响应'))
    const wrapper = await mountResult()

    await wrapper.get('button.feedback-button').trigger('click')
    await flushPromises()
    const reason = [...document.querySelectorAll('.ant-dropdown-menu-item')].find((item) =>
      item.textContent?.includes('距离太远')
    )
    ;(reason as HTMLElement).click()
    await flushPromises()

    expect(wrapper.get('button.feedback-button').attributes('disabled')).toBeUndefined()
  })
})
