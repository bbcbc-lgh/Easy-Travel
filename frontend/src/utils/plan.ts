import type { Attraction, PriceSource } from '../types/trip'

/**
 * Presentation rules that were inlined in ResultView.
 *
 * They are pure, they carry domain decisions (how a price is described, how a
 * degradation reason reads to a human) and they were untestable while they lived
 * inside a 750-line component.
 */

const MEAL_LABELS: Record<string, string> = {
  breakfast: '早餐',
  lunch: '午餐',
  dinner: '晚餐',
  snack: '加餐'
}

const WEATHER_SOURCE_LABELS: Record<string, string> = {
  amap: '高德天气',
  open_meteo: '天气预报',
  qweather: '和风天气',
  sample: '演示天气',
  unavailable: '暂无预报'
}

const DEGRADED_LABELS: Record<string, string> = {
  llm_disabled: '未配置可用的模型服务',
  llm_provider_timeout: '模型响应超时',
  llm_provider_connection: '无法连接模型服务',
  llm_rate_limited: '模型服务限流',
  llm_http_401: '模型服务鉴权失败',
  llm_http_429: '模型服务限流',
  llm_schema_invalid: '模型输出未通过校验',
  llm_empty_content: '模型返回空内容',
  llm_truncated: '模型输出被截断',
  llm_invalid_json: '模型返回内容不是合法 JSON',
  llm_budget_exhausted: '模型调用超出时间预算'
}

/** Nights actually slept: every day but the last, never negative. */
export function nightsFor(days: number): number {
  return Math.max(days - 1, 0)
}

export function formatDistance(meters: number): string {
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} 公里` : `${meters} 米`
}

export function mealTypeLabel(type: string): string {
  return MEAL_LABELS[type] ?? '餐饮'
}

export function weatherSourceLabel(source?: string): string {
  return WEATHER_SOURCE_LABELS[source ?? 'unavailable'] ?? '暂无预报'
}

/** An unknown price must never render as a number. */
export function priceText(value: number, source?: PriceSource): string {
  if (source === 'unknown') return '以现场为准'
  if (source === 'estimated') return `约 ${value} 元（估算）`
  return `${value} 元`
}

export function ticketText(attraction: Pick<Attraction, 'ticket_price' | 'price_source'>): string {
  if (attraction.price_source === 'unknown') return '门票以现场为准'
  return `门票 ${priceText(attraction.ticket_price, attraction.price_source)}`
}

export function degradedReasonLabel(reason?: string | null): string {
  if (!reason) return '模型暂不可用'
  return DEGRADED_LABELS[reason] ?? reason
}

/** Move `index` one slot in `items`; returns whether anything moved. */
export function moveItem<T>(items: T[], index: number, direction: 'up' | 'down'): boolean {
  const target = direction === 'up' ? index - 1 : index + 1
  const current = items[index]
  const neighbour = items[target]
  if (current === undefined || neighbour === undefined) return false
  items[index] = neighbour
  items[target] = current
  return true
}

/** Remove `index` from `items`; returns whether anything was removed. */
export function removeAt<T>(items: T[], index: number): boolean {
  if (items[index] === undefined) return false
  items.splice(index, 1)
  return true
}
