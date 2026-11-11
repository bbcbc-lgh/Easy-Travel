import { describe, expect, it } from 'vitest'

import { paginateCanvas } from '../src/utils/pdf'

describe('paginateCanvas', () => {
  it('returns a single slice when the content fits on one page', () => {
    // 1000 px wide -> 194 mm printable width -> 0.194 mm per px -> ~1000 px per page
    const slices = paginateCanvas(1000, 900)

    expect(slices).toHaveLength(1)
    expect(slices[0]).toEqual({ offsetY: 0, height: 900 })
  })

  it('splits tall content into consecutive pages without gaps', () => {
    const slices = paginateCanvas(1000, 3000)

    expect(slices.length).toBeGreaterThan(1)
    expect(slices[0].offsetY).toBe(0)
    for (let index = 1; index < slices.length; index += 1) {
      expect(slices[index].offsetY).toBe(slices[index - 1].offsetY + slices[index - 1].height)
    }
    const covered = slices.reduce((total, slice) => total + slice.height, 0)
    expect(covered).toBe(3000)
  })

  it('keeps every page but the last at the same height', () => {
    const slices = paginateCanvas(1000, 5000)
    const pageHeight = slices[0].height

    for (const slice of slices.slice(0, -1)) {
      expect(slice.height).toBe(pageHeight)
    }
    expect(slices.at(-1)?.height).toBeLessThanOrEqual(pageHeight)
  })

  it('returns nothing for an empty canvas', () => {
    expect(paginateCanvas(0, 100)).toEqual([])
    expect(paginateCanvas(100, 0)).toEqual([])
  })
})
