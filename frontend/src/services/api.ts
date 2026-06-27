import axios from 'axios'

import type { TripPlan, TripPlanRequest } from '../types/trip'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api',
  timeout: 60000
})

export async function generateTripPlan(payload: TripPlanRequest): Promise<TripPlan> {
  const response = await api.post<TripPlan>('/trip/plan', payload)
  return response.data
}
