import { message } from 'ant-design-vue'
import { nextTick, ref } from 'vue'
import type { Ref } from 'vue'

import type { TripPlan } from '../types/trip'
import { paginateCanvas } from '../utils/pdf'

export type ExportKind = '' | 'image' | 'pdf' | 'print'

/**
 * Capturing and printing the plan.
 *
 * Two rules baked in, both learned from real use:
 *
 * * every export expands the day cards and waits for the lazy images first -
 *   otherwise html2canvas captures the sections it just revealed as blank boxes;
 * * a failure says so. The old code swallowed the error, so "nothing happened"
 *   looked like a broken button.
 */
export function usePlanExport(plan: Ref<TripPlan | null>, expandedDays: Ref<number[]>) {
  const exporting = ref<ExportKind>('')

  const IMAGE_WAIT_MS = 3000

  async function waitForImage(image: HTMLImageElement): Promise<void> {
    if (image.complete) return
    // `decode()` is not on every image implementation (older Safari, jsdom), so
    // feature-detect rather than assume: a missing method used to throw here and
    // take the whole export down with it.
    if (typeof image.decode === 'function') {
      await image.decode().catch(() => undefined)
      return
    }
    // A broken image never fires either event; an export that waits forever is a
    // frozen button, so give up and capture whatever is on screen.
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, IMAGE_WAIT_MS)
      const done = () => {
        clearTimeout(timer)
        resolve()
      }
      image.addEventListener('load', done, { once: true })
      image.addEventListener('error', done, { once: true })
    })
  }

  async function revealWholePlan(): Promise<() => void> {
    const visibleDays = [...expandedDays.value]
    if (!plan.value) return () => undefined
    expandedDays.value = plan.value.days.map((_, index) => index)
    await nextTick()
    const element = document.getElementById('trip-plan-content')
    const images = element ? Array.from(element.querySelectorAll('img')) : []
    await Promise.all(images.map((image) => waitForImage(image)))
    return () => {
      expandedDays.value = visibleDays
    }
  }

  async function capturePlanContent() {
    const element = document.getElementById('trip-plan-content')
    if (!element || !plan.value) return null
    // html2canvas is heavy and only needed on export: load it on demand.
    const { default: html2canvas } = await import('html2canvas')
    const restore = await revealWholePlan()
    try {
      return await html2canvas(element, { backgroundColor: '#ffffff', scale: 2, useCORS: true })
    } finally {
      restore()
    }
  }

  async function exportAsImage(): Promise<void> {
    if (!plan.value || exporting.value) return
    exporting.value = 'image'
    try {
      const canvas = await capturePlanContent()
      if (!canvas) return
      const link = document.createElement('a')
      link.download = `${plan.value.city}旅行计划.png`
      link.href = canvas.toDataURL('image/png')
      link.click()
    } catch (error) {
      message.error(`导出图片失败：${error instanceof Error ? error.message : '请稍后再试'}`)
    } finally {
      exporting.value = ''
    }
  }

  async function exportAsPDF(): Promise<void> {
    if (!plan.value || exporting.value) return
    exporting.value = 'pdf'
    try {
      const canvas = await capturePlanContent()
      if (!canvas) return
      const { default: jsPDF } = await import('jspdf')
      const pdf = new jsPDF('p', 'mm', 'a4')
      const margin = 8
      const contentWidth = 210 - margin * 2
      const scale = contentWidth / canvas.width
      const slices = paginateCanvas(canvas.width, canvas.height)

      slices.forEach((slice, index) => {
        const pageCanvas = document.createElement('canvas')
        pageCanvas.width = canvas.width
        pageCanvas.height = slice.height
        const context = pageCanvas.getContext('2d')
        if (!context) return
        context.drawImage(
          canvas,
          0,
          slice.offsetY,
          canvas.width,
          slice.height,
          0,
          0,
          canvas.width,
          slice.height
        )
        if (index > 0) pdf.addPage()
        // JPEG, not PNG: a two-day plan was a multi-megabyte file when every page
        // was a lossless screenshot, and the content is text on white.
        pdf.addImage(
          pageCanvas.toDataURL('image/jpeg', 0.92),
          'JPEG',
          margin,
          margin,
          contentWidth,
          slice.height * scale
        )
      })

      pdf.save(`${plan.value.city}旅行计划.pdf`)
    } catch (error) {
      message.error(`导出 PDF 失败：${error instanceof Error ? error.message : '请稍后再试'}`)
    } finally {
      exporting.value = ''
    }
  }

  async function printPlan(): Promise<void> {
    if (!plan.value || exporting.value) return
    exporting.value = 'print'
    const restore = await revealWholePlan()
    try {
      // The print dialog's "save as PDF" produces real, selectable text with the
      // system's own Chinese font; the raster export stays for pixel-exact layout.
      window.print()
    } finally {
      restore()
      exporting.value = ''
    }
  }

  return { exporting, revealWholePlan, capturePlanContent, exportAsImage, exportAsPDF, printPlan }
}
