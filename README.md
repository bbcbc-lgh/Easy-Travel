# Chapter13 智能旅行助手

一个基于 FastAPI + Vue 3 + TypeScript 的智能旅行规划综合案例。项目按课程文本拆成前端层、后端层、智能体层、外部服务层；没有外部密钥时会使用内置示例数据，方便先跑通流程。

## 架构

- `backend/`: FastAPI API、Pydantic 数据模型、服务封装、4 个 Agent。
- `frontend/`: Vue 3 页面、旅行计划展示、地图占位/高德地图加载、导出图片/PDF。

## 需要你提供的配置

复制 `backend/.env.example` 为 `backend/.env`，按需填写：

- `LLM_API_KEY`: OpenAI/DeepSeek 等兼容 OpenAI API 的密钥。
- `LLM_BASE_URL`: 兼容 OpenAI API 的服务地址，例如 DeepSeek 的地址。
- `LLM_MODEL`: 使用的模型名称。
- `AMAP_WEB_SERVICE_KEY`: 高德 Web 服务 Key，用于景点、天气、地理编码查询。
- `VITE_AMAP_JS_KEY`: 高德 JS API Key，用于前端地图。
- `UNSPLASH_ACCESS_KEY`: Unsplash Access Key，用于景点图片。

当前版本不需要 MySQL、Redis 或向量数据库。

## 启动

后端：

```powershell
cd E:\Source\Hello-Agents\Chapter13\backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python run.py
```

建议使用 Python 3.10-3.12。当前依赖中的 `pydantic-core` 在 Windows Python 3.14 下可能需要本地 Rust 编译，容易安装失败。

前端：

```powershell
cd E:\Source\Hello-Agents\Chapter13\frontend
npm install
npm run dev
```

访问：

- 后端文档: http://localhost:8000/docs
- 前端页面: http://localhost:5173

## 测试

```powershell
cd E:\Source\Hello-Agents\Chapter13\backend
.\.venv\Scripts\python -m pytest

cd E:\Source\Hello-Agents\Chapter13\frontend
npm run build
```
