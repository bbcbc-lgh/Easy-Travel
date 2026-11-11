import { describe, expect, it } from 'vitest'

import {
  degradedReasonLabel,
  formatDistance,
  mealTypeLabel,
  moveItem,
  nightsFor,
  priceText,
  removeAt,
  ticketText,
  weatherSourceLabel
} from '../src/utils/plan'

describe('nightsFor', () => {
  it('counts nights, not days', () => {
    expect(nightsFor(3)).toBe(2)
    expect(nightsFor(1)).toBe(0)
  })

  it('never goes negative', () => {
    expect(nightsFor(0)).toBe(0)
  })
})

describe('formatDistance', () => {
  it('switches to kilometres at a thousand metres', () => {
    expect(formatDistance(999)).toBe('999 米')
    expect(formatDistance(1000)).toBe('1.0 公里')
    expect(formatDistance(1249)).toBe('1.2 公里')
  })
})

describe('labels', () => {
  it('maps meal types and falls back for unknown ones', () => {
    expect(mealTypeLabel('breakfast')).toBe('早餐')
    expect(mealTypeLabel('dinner')).toBe('晚餐')
    expect(mealTypeLabel('brunch')).toBe('餐饮')
  })

  it('maps weather sources, treating unknown ones as unavailable', () => {
    expect(weatherSourceLabel('qweather')).toBe('和风天气')
    expect(weatherSourceLabel('unavailable')).toBe('暂无预报')
    expect(weatherSourceLabel(undefined)).toBe('暂无预报')
    expect(weatherSourceLabel('nonsense')).toBe('暂无预报')
  })
})

describe('priceText', () => {
  it('never renders a number for an unknown price', () => {
    expect(priceText(0, 'unknown')).toBe('以现场为准')
    expect(priceText(120, 'unknown')).toBe('以现场为准')
  })

  it('marks estimated prices as estimates', () => {
    expect(priceText(60, 'estimated')).toBe('约 60 元（估算）')
  })

  it('shows a confirmed price plainly', () => {
    expect(priceText(60, 'api')).toBe('60 元')
  })

  it('applies the same rule to tickets', () => {
    expect(ticketText({ ticket_price: 0, price_source: 'unknown' })).toBe('门票以现场为准')
    expect(ticketText({ ticket_price: 50, price_source: 'estimated' })).toBe(
      '门票 约 50 元（估算）'
    )
  })
})

describe('degradedReasonLabel', () => {
  it('explains a known failure in human words', () => {
    expect(degradedReasonLabel('llm_provider_timeout')).toBe('模型响应超时')
  })

  it('falls back to a generic sentence when there is no reason', () => {
    expect(degradedReasonLabel(null)).toBe('模型暂不可用')
    expect(degradedReasonLabel(undefined)).toBe('模型暂不可用')
  })

  it('passes an unrecognised reason through rather than hiding it', () => {
    expect(degradedReasonLabel('llm_something_new')).toBe('llm_something_new')
  })
})

describe('moveItem', () => {
  it('swaps with the neighbour in the requested direction', () => {
    const items = ['a', 'b', 'c']

    expect(moveItem(items, 1, 'up')).toBe(true)
    expect(items).toEqual(['b', 'a', 'c'])

    expect(moveItem(items, 1, 'down')).toBe(true)
    expect(items).toEqual(['b', 'c', 'a'])
  })

  it('refuses to move past either end', () => {
    const items = ['a', 'b']

    expect(moveItem(items, 0, 'up')).toBe(false)
    expect(moveItem(items, 1, 'down')).toBe(false)
    expect(items).toEqual(['a', 'b'])
  })

  it('refuses an out-of-range index', () => {
    expect(moveItem(['a'], 5, 'up')).toBe(false)
  })
})

describe('removeAt', () => {
  it('removes the item at the index', () => {
    const items = ['a', 'b', 'c']

    expect(removeAt(items, 1)).toBe(true)
    expect(items).toEqual(['a', 'c'])
  })

  it('reports a miss without throwing', () => {
    const items = ['a']

    expect(removeAt(items, 3)).toBe(false)
    expect(items).toEqual(['a'])
  })
})
