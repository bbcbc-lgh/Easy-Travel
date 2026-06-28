# Easy Travel

Easy Travel is an AI-powered travel planning web app. Tell it where you want to go, when you are traveling, what you care about, and your budget level; it generates an editable itinerary with attractions, meals, hotels, weather, route visualization, and budget estimates.

The project is built as a full-stack Agent application:

- FastAPI backend for API routing, validation, orchestration, and external service integration.
- Vue 3 + TypeScript frontend for form input, itinerary review, editing, map display, and export.
- A small multi-agent planning pipeline for attraction search, weather lookup, hotel recommendation, itinerary generation, and quality review.
- Graceful fallback data when external API keys are missing or unavailable, so the app can still run locally.

## Features

- AI itinerary generation based on city, dates, preferences, budget, transport, and accommodation type.
- AMap-backed attraction, meal, hotel, weather, route, and budget planning in one response.
- AMap-based map visualization for attraction markers when a JS API key is configured.
- Editable daily itinerary with move/delete actions for attractions.
- SQLite persistence for generated plans, editable saved results, and local share links.
- Built-in quality checks for repeated attractions, empty days, overloaded days, weather coverage, and candidate data sufficiency.
- Export itinerary content as image or PDF.
- Works without MySQL, Redis, or vector database.

## Tech Stack

Backend:

- Python
- FastAPI
- Pydantic
- httpx
- OpenAI-compatible LLM API client

Frontend:

- Vue 3
- TypeScript
- Vite
- Ant Design Vue
- AMap JS API
- html2canvas + jsPDF

External services:

- OpenAI-compatible LLM API
- AMap Web Service API
- AMap JavaScript API
- SQLite

## Project Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── agents/      # Attraction, weather, hotel, planner, and review agents
│   │   ├── api/         # FastAPI routes and dependencies
│   │   ├── models/      # Pydantic request/response schemas
│   │   ├── services/    # LLM, AMap, and fallback data services
│   │   └── config.py
│   ├── tests/
│   ├── requirements.txt
│   └── run.py
└── frontend/
    ├── src/
    │   ├── router/
    │   ├── services/
    │   ├── styles/
    │   ├── types/
    │   └── views/
    └── package.json
```

## Configuration

Backend configuration:

```powershell
cd backend
Copy-Item .env.example .env
```

Fill in `backend/.env` as needed:

```env
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=gpt-4o-mini
AMAP_WEB_SERVICE_KEY=
DATABASE_PATH=data/easy_travel.sqlite3
```

Frontend configuration:

```powershell
cd frontend
Copy-Item .env.example .env
```

Fill in `frontend/.env`:

```env
VITE_API_BASE_URL=http://localhost:8000/api
VITE_AMAP_JS_KEY=
```

If you do not provide API keys, the backend will use deterministic sample data. This is useful for demos, tests, and offline development.

SQLite is used through Python's built-in `sqlite3` module. No extra database server is required. If you want to inspect the local database manually on Windows, this project can be opened with `D:\SQLite\sqlite3.exe backend\data\easy_travel.sqlite3`.

## AMap Web Service Scope

The current backend needs these AMap Web Service API capabilities:

- District search: resolve a city name to `adcode` and city center coordinates.
- Place text search 2.0: search attractions, hotels, and restaurants by keyword, region, type code, pagination, and extended fields.
- Place text search 1.0 fallback: use the older `/v3/place/text` response when 2.0 is unavailable.
- Weather query: fetch forecast weather by city `adcode`.
- Route planning: estimate daily hotel-to-attraction and attraction-to-attraction travel legs.

Useful request examples to provide next:

- `/v3/config/district` for city/adcode lookup.
- `/v5/place/text` for scenic spots, parks, museums, landmarks, hotels, restaurants, and food streets.
- `/v3/place/text` as a fallback request example.
- `/v3/weather/weatherInfo` for forecast data.
- `/v5/direction/driving`, `/v5/direction/walking`, and transit route examples.

The frontend map uses AMap JavaScript API through `VITE_AMAP_JS_KEY`; keep that key in `frontend/.env`.

## Run Locally

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python run.py
```

API docs will be available at:

```text
http://localhost:8000/docs
```

Recommended Python version: 3.10-3.12. On Windows, Python 3.14 may require local Rust compilation for `pydantic-core`.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

## Test and Build

Backend tests:

```powershell
cd backend
.\.venv\Scripts\python -m pytest
```

Frontend production build:

```powershell
cd frontend
npm run build
```

## API Overview

Health check:

```text
GET /api/health
```

Generate travel plan:

```text
POST /api/trip/plan
```

Saved plans:

```text
GET /api/trip/plans
GET /api/trip/plans/{plan_id}
PUT /api/trip/plans/{plan_id}
```

After a plan is generated, the frontend opens `/result/{plan_id}`. That local link can be copied and reopened while the backend and SQLite database are available.

Example request:

```json
{
  "city": "北京",
  "start_date": "2026-07-01",
  "days": 3,
  "preferences": "历史文化、城市漫游、美食，节奏适中",
  "budget": "中等",
  "transportation": "公共交通",
  "accommodation": "经济型酒店"
}
```

## Notes

- `backend/.env` and `frontend/.env` are intentionally ignored by Git.
- AMap Web Service can be sensitive to network routing. If you are using a VPN and the AMap request fails, the app will fall back to sample data instead of failing the whole planning flow.
- The first production build may show a large chunk warning because Ant Design Vue and map/export libraries are bundled into the app. It does not prevent the build from succeeding.
