# Easy Travel

Easy Travel is an AI-powered travel planning web app. Tell it where you want to go, when you are traveling, what you care about, and your budget level; it generates an editable itinerary with attractions, meals, hotels, weather, route visualization, and budget estimates.

The project is built as a full-stack Agent application:

- FastAPI backend for API routing, validation, orchestration, and external service integration.
- Vue 3 + TypeScript frontend for form input, itinerary review, editing, map display, and export.
- A small multi-agent planning pipeline for attraction search, weather lookup, hotel recommendation, itinerary generation, and quality review.
- Graceful fallback data when external API keys are missing or unavailable, so the app can still run locally.

## Features

- AI itinerary generation based on city, dates, preferences, budget, transport, and accommodation type.
- Attraction, meal, hotel, weather, and budget planning in one response.
- AMap-based map visualization for attraction markers when a JS API key is configured.
- Editable daily itinerary with move/delete actions for attractions.
- Built-in quality checks for repeated attractions, empty days, overloaded days, weather coverage, and candidate data sufficiency.
- Export itinerary content as image or PDF.
- Works without a database; no MySQL, Redis, or vector database is required.

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
