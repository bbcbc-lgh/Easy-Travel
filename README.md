# Easy Travel 智能旅行规划系统

Easy Travel 是一个面向旅行规划场景的 AI Agent 全栈应用。用户输入目的地、出行日期、旅行偏好、预算档位、交通方式和住宿偏好后，系统会自动生成包含景点、餐饮、酒店、天气、路线估算和预算明细的可编辑行程。

项目采用 FastAPI + Vue 3 + TypeScript 构建，后端通过多 Agent 流程完成候选数据检索、天气查询、酒店与餐饮推荐、行程编排和质量检查；前端提供表单录入、结果展示、地图标记、行程编辑、分享链接和图片/PDF 导出能力。

## 在线演示

https://stellar-compassion-production-bea1.up.railway.app

## 功能特性

- 根据城市、日期、偏好、预算、交通方式和住宿类型生成旅行计划。
- 集成高德 Web Service API，支持景点、餐饮、酒店、天气、城市坐标和路线估算。
- 支持 OpenAI 兼容接口生成结构化 JSON 行程，失败时自动切换到规则 fallback。
- 支持无 API Key 本地运行，使用确定性样例数据完成演示和开发调试。
- 使用 SQLite 持久化生成结果，支持历史列表、详情读取、编辑保存和本地分享链接。
- 内置质量检查，覆盖重复景点、空行程、每日强度、天气覆盖和候选数量等问题。
- 前端支持高德地图景点标记、每日路线距离/耗时展示、行程移动/删除和图片/PDF 导出。

## 技术栈

后端：

- Python
- FastAPI
- Pydantic
- httpx
- SQLite
- OpenAI 兼容 LLM API
- 高德 Web Service API

前端：

- Vue 3
- TypeScript
- Vite
- Ant Design Vue
- 高德 JavaScript API
- html2canvas
- jsPDF

## 系统流程

```text
用户输入旅行需求
  -> 景点 Agent / 酒店 Agent / 餐饮 Agent / 天气 Agent 并行检索候选数据
  -> 规划 Agent 生成每日行程
  -> 高德路线估算补充日内交通信息
  -> 质量检查 Agent 生成评分和提醒
  -> SQLite 保存结果
  -> 前端展示、编辑、分享和导出
```

## 项目结构

```text
.
├── backend/
│   ├── app/
│   │   ├── agents/       # 景点、天气、酒店、餐饮、规划和质量检查 Agent
│   │   ├── api/          # FastAPI 路由、依赖和应用入口
│   │   ├── models/       # Pydantic 请求/响应模型
│   │   ├── services/     # LLM、高德服务、SQLite 仓储和样例数据
│   │   └── Config.py     # 后端配置
│   ├── tests/            # 后端测试
│   ├── requirements.txt
│   └── run.py
└── frontend/
    ├── src/
    │   ├── router/       # 前端路由
    │   ├── services/     # API client
    │   ├── styles/       # 全局样式
    │   ├── types/        # TypeScript 类型
    │   └── views/        # 页面视图
    └── package.json
```

## 本地运行

### 1. 启动后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python run.py
```

后端默认运行在：

```text
http://localhost:8000
```

接口文档：

```text
http://localhost:8000/docs
```

### 2. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

前端默认运行在：

```text
http://localhost:5173
```

## 环境变量

后端可在 `backend/.env` 中配置：

```env
APP_NAME=Easy Travel
API_HOST=127.0.0.1
API_PORT=8000
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=gpt-4o-mini

AMAP_WEB_SERVICE_KEY=
DATABASE_PATH=data/easy_travel.sqlite3
```

前端可在 `frontend/.env` 中配置：

```env
VITE_API_BASE_URL=http://localhost:8000/api
VITE_AMAP_JS_KEY=
```

说明：

- `LLM_API_KEY` 为空时，后端会跳过大模型生成并使用规则 fallback。
- `AMAP_WEB_SERVICE_KEY` 为空或请求失败时，后端会使用样例数据和本地距离估算。
- `VITE_AMAP_JS_KEY` 为空时，前端不会加载高德地图，但仍可展示行程内容。

## API 概览

```text
GET  /api/health
POST /api/trip/plan
GET  /api/trip/plans
GET  /api/trip/plans/{plan_id}
PUT  /api/trip/plans/{plan_id}
```

示例请求：

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

## 测试与构建

后端测试：

```powershell
cd backend
.\.venv\Scripts\python -m pytest
```

前端构建：

```powershell
cd frontend
npm run build
```

## 开发说明

- 后端使用 Python 内置 `sqlite3` 模块，无需单独安装数据库服务。
- 外部 API 不可用时，系统会降级到本地样例数据，便于离线开发和演示。
- 生产构建中 Ant Design Vue、地图和导出相关库会带来较大的前端包体积，这是当前实现的正常现象。
