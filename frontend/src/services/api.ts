import axios from 'axios'

import type { TripPlan, TripPlanRequest, TripPlanSummary } from '../types/trip'

const isLocalHost = ['localhost', '127.0.0.1'].includes(window.location.hostname)
const defaultApiBaseUrl = isLocalHost
  ? 'http://localhost:8000/api'
  : 'https://easy-travel-production-d58a.up.railway.app/api'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || defaultApiBaseUrl,
  timeout: 60000
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

export async function listTripPlans(limit = 20): Promise<TripPlanSummary[]> {
  try {
    const response = await api.get<TripPlanSummary[]>('/trip/plans', { params: { limit } })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

function throwApiError(error: unknown): never {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join('; ')
      : detail || error.message
    throw new Error(message)
  }
  throw error
}
