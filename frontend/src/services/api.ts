import axios from 'axios'

import type { TripPlan, TripPlanRequest } from '../types/trip'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api',
  timeout: 60000
})

export async function generateTripPlan(payload: TripPlanRequest): Promise<TripPlan> {
  try {
    const response = await api.post<TripPlan>('/trip/plan', payload)
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail
      const message = Array.isArray(detail)
        ? detail.map((item) => item.msg).join('；')
        : detail || error.message
      throw new Error(message)
    }
    throw error
  }
}
