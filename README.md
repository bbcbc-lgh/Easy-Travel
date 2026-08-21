# EasyTravel

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)
![Vue](https://img.shields.io/badge/Vue-3-42B883.svg)

EasyTravel 是一个可以直接在本地运行的 AI 旅行规划 Web 应用。输入目的地、日期、偏好和预算后，它会生成可编辑的多日行程，并展示景点、餐饮、住宿、天气、路线和预算信息。

项目适合用来体验 FastAPI、Vue 3、LangGraph 和 OpenAI 兼容接口的组合，也可以在没有 API Key 的情况下使用内置样例数据进行开发和演示。

## 你可以用它做什么

- 根据城市、日期、旅行偏好、预算、交通和住宿要求生成行程。
- 接入高德 Web Service API 获取景点、餐饮、酒店、天气和路线信息。
- 通过 OpenAI 兼容接口生成结构化计划；没有密钥或外部服务不可用时自动使用 fallback 数据。
- 在浏览器中编辑每日行程、查看地图标记、保存历史计划，并导出图片或 PDF。
- 通过 FastAPI 文档直接调试 API，或将前端替换为自己的客户端。

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 20.19+（或 22.12+）
- npm

### 获取代码

```powershell
git clone https://github.com/bbcbc-lgh/Easy-Travel.git
cd Easy-Travel
```

### 1. 启动后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn src.API.Main:app --host 127.0.0.1 --port 8000 --reload
```

后端地址：<http://127.0.0.1:8000>

API 文档：<http://127.0.0.1:8000/docs>

### 2. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

前端地址：<http://127.0.0.1:5173>

启动两个服务后，打开前端地址即可生成第一份旅行计划。首次运行不配置任何密钥也可以完成完整流程。

## 配置

### 后端

在 `backend/.env` 中填写需要的配置。可以从 `backend/.env.example` 开始：

```env
APP_NAME=EasyTravel
APP_ENV=development
FASTAPI_API_HOST=127.0.0.1
FASTAPI_API_PORT=8000
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=gpt-4o-mini

FASTAPI_AMAP_WEB_KEY=
USE_SAMPLE_DATA=false
DATABASE_PATH=data/easy_travel.sqlite3
```

- `LLM_API_KEY`：OpenAI 或其他 OpenAI 兼容服务的密钥。留空时使用规则 fallback。
- `LLM_BASE_URL`：兼容服务的 API 地址；使用 OpenAI 时可留空。
- `FASTAPI_AMAP_WEB_KEY`：高德 Web Service Key。留空或请求失败时使用样例地点和本地距离估算。
- `USE_SAMPLE_DATA=true`：强制离线模式，跳过 LLM 和高德请求，适合 CI、调试和演示。
- `DATABASE_PATH`：SQLite 文件路径，默认保存在 `backend/data/` 下。

### 前端

在 `frontend/.env` 中填写：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api
VITE_AMAP_JS_KEY=
```

`VITE_AMAP_JS_KEY` 只影响地图加载；不配置时仍可生成和编辑行程。

## API 示例

所有接口都以 `/api` 为前缀：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 查看服务状态 |
| `POST` | `/api/trip/plan` | 生成并保存旅行计划 |
| `GET` | `/api/trip/plans` | 获取历史计划列表 |
| `GET` | `/api/trip/plans/{plan_id}` | 获取计划详情 |
| `PUT` | `/api/trip/plans/{plan_id}` | 保存编辑后的计划 |

生成计划的请求示例：

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

`budget` 支持 `经济`、`中等`、`舒适`、`豪华`；`days` 支持 1 到 14 天。更完整的请求和响应模型可在 `/docs` 中查看。

## 开发命令

```powershell
# 后端测试
cd backend
.\.venv\Scripts\python -m pytest

# 前端生产构建
cd ..\frontend
npm run build
```

后端使用 Python 内置 SQLite，不需要额外启动数据库服务。外部服务不可用时，fallback 逻辑仍可用于本地开发。

## 项目结构

```text
.
├── backend/
│   ├── src/Agent/      # Agent 和 LangGraph 编排
│   ├── src/API/        # FastAPI 应用与路由
│   ├── src/Model/      # Pydantic 数据模型
│   ├── src/Service/    # LLM、高德、SQLite 和样例数据服务
│   └── tests/          # 后端测试
└── frontend/
    └── src/             # Vue 页面、路由、API client 和类型
```

## 参与贡献

欢迎通过 Issue 报告问题或提出功能建议，也欢迎提交 Pull Request。

提交前请至少运行：

1. `backend/.venv/Scripts/python -m pytest`
2. `frontend/npm run build`

提交 Issue 时，尽量附上运行环境、复现步骤、相关日志，以及是否开启了 `USE_SAMPLE_DATA`。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
