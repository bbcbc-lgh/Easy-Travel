import { message } from 'ant-design-vue'
import { computed, ref } from 'vue'
import type { Ref } from 'vue'

import { updateTripPlan } from '../services/api'
import type { TripPlan } from '../types/trip'
import { moveItem, removeAt } from '../utils/plan'

/**
 * Editing an existing plan in place.
 *
 * The ordering rule matters and is the reason this is not just "toggle a ref":
 * edit mode is left **after** the server accepts the change. Clearing it first
 * discarded the snapshot, hid the save button and left a failed save with no way
 * to retry or cancel.
 */
export function usePlanEdit(
  plan: Ref<TripPlan | null>,
  hooks: { persist: () => void; onSaved?: () => void } = { persist: () => undefined }
) {
  const editMode = ref(false)
  const saving = ref(false)
  const originalPlan = ref<TripPlan | null>(null)

  const canEdit = computed(() => plan.value !== null)

  function toggleEditMode(): void {
    editMode.value = !editMode.value
    if (editMode.value && plan.value) {
      originalPlan.value = JSON.parse(JSON.stringify(plan.value)) as TripPlan
    }
  }

  async function saveChanges(): Promise<boolean> {
    if (!plan.value || saving.value) return false
    saving.value = true
    try {
      if (plan.value.id) {
        plan.value = await updateTripPlan(plan.value.id, plan.value)
      }
      editMode.value = false
      originalPlan.value = null
      hooks.persist()
      hooks.onSaved?.()
      message.success('修改已保存')
      return true
    } catch (error) {
      const detail = error instanceof Error ? error.message : '请稍后再试'
      message.error(`保存失败：${detail}`)
      return false
    } finally {
      saving.value = false
    }
  }

  function cancelEdit(): void {
    if (saving.value) return
    if (originalPlan.value) {
      plan.value = originalPlan.value
    }
    editMode.value = false
    originalPlan.value = null
    hooks.onSaved?.()
  }

  function moveAttraction(
    dayIndex: number,
    attractionIndex: number,
    direction: 'up' | 'down'
  ): void {
    const attractions = plan.value?.days[dayIndex]?.attractions
    if (!attractions) return
    moveItem(attractions, attractionIndex, direction)
  }

  function deleteAttraction(dayIndex: number, attractionIndex: number): void {
    const attractions = plan.value?.days[dayIndex]?.attractions
    if (!attractions) return
    removeAt(attractions, attractionIndex)
  }

  return {
    editMode,
    saving,
    originalPlan,
    canEdit,
    toggleEditMode,
    saveChanges,
    cancelEdit,
    moveAttraction,
    deleteAttraction
  }
}
