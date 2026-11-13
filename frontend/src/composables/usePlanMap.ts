import AMapLoader from '@amap/amap-jsapi-loader'
import { nextTick, onBeforeUnmount, ref } from 'vue'
import type { ComputedRef } from 'vue'

import type { Attraction } from '../types/trip'
import { describeMapFailure } from '../utils/plan'

/**
 * The map panel: load the SDK, draw the markers, and clean up after itself.
 *
 * Two defects this fixes, both from a real run: the instance was never destroyed,
 * so route changes leaked listeners and DOM; and `initMap` had no lock, so two
 * concurrent calls (a save plus a route change) drew two maps into one container.
 * `seq` invalidates any init that was awaiting the loader while a newer one began.
 */
export function usePlanMap(attractions: ComputedRef<Attraction[]>, containerId = 'amap-container') {
  const mapReady = ref(false)
  const mapStatus = ref('正在准备地图')
  let instance: { destroy: () => void } | null = null
  let seq = 0

  async function initMap(): Promise<void> {
    const current = ++seq
    mapReady.value = false
    mapStatus.value = '正在准备地图'
    const key = import.meta.env.VITE_AMAP_JS_KEY
    const securityCode = import.meta.env.VITE_AMAP_SECURITY_CODE
    if (!key) {
      mapStatus.value = '未配置 VITE_AMAP_JS_KEY，当前显示为静态行程数据'
      return
    }
    if (!attractions.value.length) {
      mapStatus.value = '暂无景点坐标'
      return
    }

    try {
      await nextTick()
      const first = attractions.value[0]
      if (!first) {
        mapStatus.value = '暂无景点坐标'
        return
      }
      // AMap JS API 2.0 refuses to load without the security code that belongs to
      // this key, and the loader gives no useful error otherwise.
      if (securityCode) {
        ;(
          window as unknown as { _AMapSecurityConfig?: { securityJsCode: string } }
        )._AMapSecurityConfig = {
          securityJsCode: securityCode
        }
      }
      const AMap = await AMapLoader.load({ key, version: '2.0' })
      // A newer init (after a save/revise/unmount) started while we awaited the
      // loader; drop this one instead of leaving two maps on the page.
      if (current !== seq) return

      instance?.destroy()
      instance = null
      const map = new AMap.Map(containerId, {
        zoom: 12,
        center: [first.location.longitude, first.location.latitude]
      })
      instance = map
      attractions.value.forEach((attraction, index) => {
        const marker = new AMap.Marker({
          position: [attraction.location.longitude, attraction.location.latitude],
          title: attraction.name,
          label: { content: `${index + 1}`, direction: 'top' }
        })
        map.add(marker)
      })
      mapReady.value = true
    } catch (error) {
      mapStatus.value = describeMapFailure(error)
    }
  }

  function destroyMap(): void {
    seq += 1
    instance?.destroy()
    instance = null
    mapReady.value = false
  }

  onBeforeUnmount(destroyMap)

  return { mapReady, mapStatus, initMap, destroyMap }
}
