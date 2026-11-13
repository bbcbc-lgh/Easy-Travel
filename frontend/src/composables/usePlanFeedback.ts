import { message } from 'ant-design-vue'
import { computed, ref, watch } from 'vue'

import { sendPlanFeedback } from '../services/api'
import type { FeedbackReason } from '../services/api'

export interface FeedbackReasonOption {
  value: FeedbackReason
  label: string
}

export const FEEDBACK_REASONS: FeedbackReasonOption[] = [
  { value: 'too_packed', label: '排得太满' },
  { value: 'wrong_place', label: '地点不合适' },
  { value: 'closed', label: '当时不开放' },
  { value: 'too_far', label: '距离太远' },
  { value: 'other', label: '其他' }
]

const STORAGE_PREFIX = 'easyTravel.reported.'

function storageKey(planId: string): string {
  return `${STORAGE_PREFIX}${planId}`
}

function readReported(planId: string): Set<string> {
  if (!planId || typeof window === 'undefined') return new Set()
  try {
    const raw = window.localStorage.getItem(storageKey(planId))
    if (!raw) return new Set()
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed)
      ? new Set(parsed.filter((item): item is string => typeof item === 'string'))
      : new Set()
  } catch {
    // A corrupted list must not break the page; forgetting it only means a stop
    // could be reported twice, which the backend tolerates.
    return new Set()
  }
}

function writeReported(planId: string, keys: Set<string>): void {
  if (!planId || typeof window === 'undefined') return
  try {
    window.localStorage.setItem(storageKey(planId), JSON.stringify([...keys]))
  } catch {
    // Private-mode storage can be full or unavailable; the in-memory set still works.
  }
}

export function stopKey(dayIndex: number, name: string): string {
  return `${dayIndex}|${name}`
}

/**
 * "This stop is wrong", recorded once per stop.
 *
 * The set of already-reported stops used to live in component state, so a reload
 * brought every greyed-out button back and the same complaint could be filed
 * again - which inflates exactly the signal this feature exists to collect. It is
 * now persisted per plan.
 */
export function usePlanFeedback(planId: () => string) {
  const reportedStops = ref<Set<string>>(new Set())
  const reporting = ref(false)

  watch(
    () => planId(),
    (id) => {
      reportedStops.value = readReported(id)
    },
    { immediate: true }
  )

  function isReported(dayIndex: number, name: string): boolean {
    return reportedStops.value.has(stopKey(dayIndex, name))
  }

  async function reportStop(
    dayIndex: number,
    name: string,
    reason: FeedbackReason
  ): Promise<boolean> {
    const id = planId()
    if (!id || reporting.value) return false
    reporting.value = true
    try {
      await sendPlanFeedback(id, {
        day_index: dayIndex,
        target: 'attraction',
        target_name: name,
        reason
      })
      const next = new Set([...reportedStops.value, stopKey(dayIndex, name)])
      reportedStops.value = next
      writeReported(id, next)
      message.success('已记录，谢谢')
      return true
    } catch (error) {
      message.error(`反馈没有记上：${error instanceof Error ? error.message : '请稍后再试'}`)
      return false
    } finally {
      reporting.value = false
    }
  }

  const reportedCount = computed(() => reportedStops.value.size)

  return { reporting, reportedCount, isReported, reportStop, FEEDBACK_REASONS }
}
