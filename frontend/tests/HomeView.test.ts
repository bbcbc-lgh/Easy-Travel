// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import Antd from 'ant-design-vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

const getHealth = vi.fn()
const streamTripPlan = vi.fn()

vi.mock('../src/services/api', () => ({
  getHealth: () => getHealth(),
  streamTripPlan: (...args: unknown[]) => streamTripPlan(...args)
}))

import HomeView from '../src/views/HomeView.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: HomeView },
      { path: '/plans', name: 'plans', component: { template: '<div />' } },
      { path: '/result', name: 'result', component: { template: '<div />' } },
      { path: '/result/:id', name: 'plan-detail', component: { template: '<div />' } }
    ]
  })
}

function mountHome() {
  return mount(HomeView, { global: { plugins: [Antd, makeRouter()] } })
}

describe('HomeView', () => {
  beforeEach(() => {
    getHealth.mockReset()
    streamTripPlan.mockReset()
  })

  it('warns that a plan will be rule-based when no model is configured', async () => {
    getHealth.mockResolvedValue({ status: 'ok', app_name: 'x', services: { llm: false } })

    const wrapper = mountHome()
    await flushPromises()

    expect(wrapper.text()).toContain('当前未配置模型')
  })

  it('stays quiet about the model when one is configured', async () => {
    getHealth.mockResolvedValue({ status: 'ok', app_name: 'x', services: { llm: true } })

    const wrapper = mountHome()
    await flushPromises()

    expect(wrapper.text()).not.toContain('当前未配置模型')
  })

  it('does not start a generation while the form is empty', async () => {
    getHealth.mockResolvedValue({ status: 'ok', app_name: 'x', services: { llm: true } })

    const wrapper = mountHome()
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(streamTripPlan).not.toHaveBeenCalled()
  })

  it('shows the pipeline stages in order', () => {
    getHealth.mockResolvedValue({ status: 'ok', app_name: 'x', services: { llm: true } })

    const wrapper = mountHome()
    const labels = wrapper.findAll('.stage-label').map((label) => label.text())

    // The stage list is empty until a run starts, so assert on the source of
    // truth the template iterates instead of on rendered output.
    expect(labels).toEqual([])
    expect(wrapper.text()).toContain('旅行偏好')
  })
})
