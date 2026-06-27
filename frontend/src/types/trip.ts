export interface Location {
  longitude: number
  latitude: number
}

export interface Attraction {
  name: string
  address: string
  location: Location
  visit_duration: number
  description: string
  category: string
  rating?: number | null
  image_url?: string | null
  ticket_price: number
}

export interface Meal {
  type: 'breakfast' | 'lunch' | 'dinner' | 'snack'
  name: string
  address?: string | null
  location?: Location | null
  description?: string | null
  estimated_cost: number
}

export interface Hotel {
  name: string
  address: string
  location?: Location | null
  price_range: string
  rating: string
  distance: string
  type: string
  estimated_cost: number
}

export interface Budget {
  total_attractions: number
  total_hotels: number
  total_meals: number
  total_transportation: number
  total: number
}

export interface PlanQuality {
  score: number
  warnings: string[]
  checks: Record<string, boolean>
}

export interface DayPlan {
  date: string
  day_index: number
  description: string
  transportation: string
  accommodation: string
  hotel?: Hotel | null
  attractions: Attraction[]
  meals: Meal[]
}

export interface WeatherInfo {
  date: string
  day_weather: string
  night_weather: string
  day_temp: number
  night_temp: number
  wind_direction: string
  wind_power: string
}

export interface TripPlanRequest {
  city: string
  start_date: string
  end_date?: string
  days: number
  preferences: string
  budget: '经济' | '中等' | '舒适' | '豪华'
  transportation: string
  accommodation: string
}

export interface TripPlan {
  city: string
  start_date: string
  end_date: string
  days: DayPlan[]
  weather_info: WeatherInfo[]
  overall_suggestions: string
  budget?: Budget | null
  quality?: PlanQuality | null
}
