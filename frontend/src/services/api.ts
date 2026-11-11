import axios from 'axios'

import type { TripPlan, TripPlanRequest, TripPlanSummary } from '../types/trip'

// Same-origin by default: the SPA is served either by Vite (which proxies /api
// to the backend) or by FastAPI itself, so a hard-coded localhost:8000 breaks
// custom ports and LAN access.
const defaultApiBaseUrl = `${window.location.origin}/api`
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || defaultApiBaseUrl
const clientIdKey = 'easyTravel.clientId'

const api = axios.create({
  baseURL: apiBaseUrl,
  timeout: 180000
})

/**
 * Anonymous ownership: the backend groups plans by this id, so a browser only
 * ever sees the itineraries it created itself.
 */
export function getClientId(): string {
  const existing = window.localStorage.getItem(clientIdKey)
  if (existing && /^[A-Za-z0-9_-]{8,64}$/.test(existing)) {
    return existing
  }
  const generated =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().replace(/-/g, '')
      : `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
  window.localStorage.setItem(clientIdKey, generated)
  return generated
}

api.interceptors.request.use((config) => {
  config.headers.set('X-Client-Id', getClientId())
  return config
})

export async function generateTripPlan(payload: TripPlanRequest): Promise<TripPlan> {
  try {
    const response = await api.post<TripPlan>('/trip/plan', payload)
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function getTripPlan(id: string): Promise<TripPlan> {
  try {
    const response = await api.get<TripPlan>(`/trip/plans/${id}`)
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function updateTripPlan(id: string, payload: TripPlan): Promise<TripPlan> {
  try {
    const response = await api.put<TripPlan>(`/trip/plans/${id}`, payload)
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export interface ReviseResult {
  plan: TripPlan
  reply: string
}/** Conversational edit: the backend turns the instruction into an applied patch. */
export async function reviseTripPlan(id: string, instruction: string): Promise<ReviseResult> {
  try {
    const response = await api.post<ReviseResult>(
      `/trip/plans/${id}/revise`,
      { instruction },
      { timeout: 300000 }
    )
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function listTripPlans(limit = 20): Promise<TripPlanSummary[]> {
  try {
    const response = await api.get<TripPlanSummary[]>('/trip/plans', { params: { limit } })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

// --- streaming generation ----------------------------------------------------

export interface PlanStageEvent {
  stage: string
  status: 'start' | 'done'
  elapsed_ms?: number
  revision?: number
  degraded?: boolean
  score?: number
  attractions?: number
  hotels?: number
  meals?: number
  weather?: number
}

export interface PlanStreamHandlers {
  onStage?: (event: PlanStageEvent) => void
  onHeartbeat?: (elapsedMs: number) => void
  onPlan: (plan: TripPlan) => void
  onError: (message: string) => void
}

/**
 * Streams a plan over Server-Sent Events.
 *
 * The model can take a minute, so the progress the user sees is the real
 * pipeline state, not a timer guessing at it.
 */
export async function streamTripPlan(payload: TripPlanRequest, handlers: PlanStreamHandlers): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}/trip/plan/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        'X-Client-Id': getClientId()
      },
      body: JSON.stringify(payload)
    })
  } catch (error) {
    handlers.onError(error instanceof Error ? error.message : '无法连接后端服务')
    return
  }

  if (response.status === 401) {
    handlers.onError('浏览器标识缺失，请刷新页面后重试')
    return
  }
  if (!response.ok || !response.body) {
    handlers.onError(`生成失败（HTTP ${response.status}）`)
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const consume = (raw: string) => {
    const event = parseSseBlock(raw)
    if (!event) return
    if (event.name === 'stage') {
      handlers.onStage?.(JSON.parse(event.data) as PlanStageEvent)
      return
    }
    if (event.name === 'heartbeat') {
      const payloadData = JSON.parse(event.data) as { elapsed_ms?: number }
      handlers.onHeartbeat?.(payloadData.elapsed_ms ?? 0)
      return
    }
    if (event.name === 'plan') {
      const payloadData = JSON.parse(event.data) as { plan: TripPlan }
      handlers.onPlan(payloadData.plan)
      return
    }
    if (event.name === 'error') {
      const payloadData = JSON.parse(event.data) as { detail?: string }
      handlers.onError(payloadData.detail || '生成失败，请稍后重试')
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      consume(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
    }
  }
}

function parseSseBlock(raw: string): { name: string; data: string } | null {
  let name = 'message'
  const data: string[] = []
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) {
      name = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      data.push(line.slice(5).trim())
    }
  }
  if (!data.length) return null
  return { name, data: data.join('\n') }
}

export interface HealthStatus {
  status: string
  app_name: string
  services: Record<string, boolean>
}

/** Whether the model is actually configured; used to warn before generating. */
export async function getHealth(): Promise<HealthStatus> {
  const response = await api.get<HealthStatus>('/health')
  return response.data
}

export async function deleteTripPlan(id: string): Promise<void> {
  await api.delete(`/trip/plans/${id}`)
}

function throwApiError(error: unknown): never {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 401) {
      throw new Error('浏览器标识缺失，请刷新页面后重试')
    }
    if (error.response?.status === 429) {
      const detail = error.response.data?.detail
      throw new Error(typeof detail === 'string' ? detail : '请求过于频繁，请稍后再试')
    }
    const detail = error.response?.data?.detail
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join('; ')
      : detail || error.message
    throw new Error(message)
  }
  throw error
}
