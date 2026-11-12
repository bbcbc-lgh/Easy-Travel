import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { routes } from '../src/router/routes'

/**
 * Route matching, checked with `resolve()` so nothing is loaded.
 *
 * This exists because the router had no coverage at all, which is why the
 * vue-router 5 upgrade was closed: a major bump changes path matching, and nothing
 * would have noticed. These are the cases the app actually depends on.
 */
function makeRouter() {
  return createRouter({ history: createMemoryHistory(), routes })
}

function resolve(path: string) {
  return makeRouter().resolve(path)
}

describe('routes', () => {
  it('maps / to the home view', () => {
    expect(resolve('/').name).toBe('home')
  })

  it('maps /plans to the history view', () => {
    expect(resolve('/plans').name).toBe('history')
  })

  it('maps /result to the result view without an id', () => {
    const route = resolve('/result')
    expect(route.name).toBe('result')
    expect(route.params.id).toBeUndefined()
  })

  it('carries the id of a shared plan link', () => {
    const route = resolve('/result/9f2c1a')
    expect(route.name).toBe('plan-detail')
    expect(route.params.id).toBe('9f2c1a')
  })

  it('keeps /result and /result/:id as different routes', () => {
    expect(resolve('/result').name).not.toBe(resolve('/result/abc').name)
  })

  it('sends an unknown path to the not-found view', () => {
    expect(resolve('/somewhere/else').name).toBe('not-found')
  })

  it('does not let a deeper result path fall through to the result view', () => {
    expect(resolve('/result/abc/extra').name).toBe('not-found')
  })

  it('keeps a trailing slash on a plan link lenient', () => {
    const route = resolve('/result/abc/')
    expect(route.name).toBe('plan-detail')
    expect(route.params.id).toBe('abc')
  })

  it('builds the plan-detail link from a name and params', () => {
    expect(makeRouter().resolve({ name: 'plan-detail', params: { id: 'p1' } }).href).toBe(
      '/result/p1'
    )
  })

  it('builds the bare result link when there is no saved plan', () => {
    expect(makeRouter().resolve({ name: 'result' }).href).toBe('/result')
  })
})
