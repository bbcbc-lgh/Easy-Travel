# EasyTravel

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)
![Vue](https://img.shields.io/badge/Vue-3-42B883.svg)

**本地运行的 AI 旅行规划工具。** 克隆仓库、填上自己的模型 Key、跑起来，就能生成可编辑的多日行程：景点、餐饮、住宿、天气、路线和预算都在一页里。

没有账号，没有云端服务，数据存在你自己电脑上的一个 SQLite 文件里。

> **这是本地单用户工具，不是在线服务。** 默认只监听 `127.0.0.1`，也没有鉴权——请不要把它直接暴露到公网，详见[安全边界](#安全边界)。

---

## 三步启动

要求：Python 3.11+（CI 在 3.12 上跑）、Node.js 20.19+（或 22.12+）。

```bash
git clone https://github.com/bbcbc-lgh/Easy-Travel.git
cd Easy-Travel
```

### 1. 填配置

```bash
cp backend/.env.example backend/.env
```

打开 `backend/.env`，至少填一项能用的模型配置：

```env
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.deepseek.com   # 任意 OpenAI 兼容服务；用 OpenAI 可留空
LLM_MODEL=deepseek-chat
```

再填一个高德 Web 服务 Key（个人开发者免费申请）：

```env
AMAP_WEB_KEY=你的高德Key
```

### 2. 启动

**Windows**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

**macOS / Linux**

```bash
bash scripts/dev.sh
```

脚本会自动建虚拟环境、装依赖、补 `.env`，然后同时拉起后端和前端。

### 3. 打开

前端 <http://127.0.0.1:5173> · API 文档 <http://127.0.0.1:8000/docs>

不想用脚本，也可以手动起两个终端：

```bash
# 终端 1
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
.venv/bin/python -m pip install -r requirements.txt       # macOS / Linux
.venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload

# 终端 2
cd frontend
npm install
npm run dev
```

> 完全没有 Key 也能跑：会进入**规则规划模式**，用样例地点生成一份可演示的行程，页面上会明确标注“规则生成”。

---

## 它怎么工作

一次生成由三层组合完成：

| 层 | 负责 | 数据来源 |
|---|---|---|
| 数据层 | 候选景点、餐饮、酒店、天气、路线 | 高德 Web 服务 + 和风天气（可选）/ Open-Meteo |
| 模型 | 只决定“每天去哪几个、住哪家、怎么描述” | 任意 OpenAI 兼容接口 |
| 确定性排程 | 按距离排序、按区域分组、按预算与距离选餐厅 | 本地计算 |

模型返回的只有**名称**，坐标、门票、日期、预算、路线全部由服务端回填——所以模型无法编造价格和位置。生成完还有一道 `PlanCritic` 检查：单日过密、当天闭馆、餐饮超预算都会变成页面上的提醒。

几处刻意的设计：

- **降级会明说**：模型不可用时行程顶部标注“规则生成”，质量分被压到 60 以下。
- **价格有来源**：每个价格都带 `api` / `estimated` / `unknown`，`unknown` 直接不显示金额。
- **编辑不放假数据**：手动修改只接受库里已有的地点，客户端提交的坐标和价格会被丢弃。
- **单日强度是硬约束**：模型决定去哪几个，但"一天装得下几个"是算术，交给服务端。
  某天超出强度上限时，先让模型自己减一次（`PlanCritic` 把过载当问题而不是提示），
  仍然超标就按上限裁掉尾部的景点，并在页面上写明移除了哪一个。
- **流式进度**：生成需要几十秒，页面显示的是真实阶段（收集候选 → 规划 → 路线 → 检查）和真实耗时。

---

## 配置项

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | 是（可留空） | 模型密钥。留空则规则规划 |
| `LLM_BASE_URL` | 否 | 兼容服务地址，OpenAI 官方可留空 |
| `LLM_MODEL` | 是 | 模型名 |
| `LLM_TIMEOUT_SECONDS` | 否 | 单次调用超时，默认 120 |
| `LLM_MAX_TOKENS` | 否 | 输出上限，`0` = 服务商默认。推理型模型的思考 token 也占这个预算 |
| `LLM_REASONING_EFFORT` | 否 | 推理模型的思考预算：`minimal` / `low` / `medium` / `high`。实测 `minimal` 把 3 天行程从约 45s 降到约 28s，评分不变；留空用服务商默认 |
| `LLM_PROFILES` | 否 | 多模型回退链（JSON 数组），不填则由 `LLM_MODEL` 生成单个 |
| `AMAP_WEB_KEY` | 建议 | 高德 Web 服务 Key；留空则用样例地点 |
| `QWEATHER_API_KEY` | 否 | 和风天气 Key；配置后优先取预报 |
| `QWEATHER_HOST` | 否 | **必须填控制台给你的 API Host**（形如 `abc123.re.qweatherapi.com`）。旧的 `devapi.qweather.com` 对新 Key 会返回 `403 Invalid Host` |
| `USE_SAMPLE_DATA` | 否 | `true` 强制离线：不调模型、不调高德，全部走本地样例 |
| `DATABASE_PATH` | 否 | SQLite 路径，默认 `backend/data/easy_travel.sqlite3` |
| `PLAN_DAILY_LIMIT` | 否 | 本机成本保护：同一浏览器每日生成次数，默认 20。**失败或中断的生成会退还次数**，只有真正出结果的才计数 |
| `PLAN_MAX_CONCURRENCY` | 否 | 同时生成的任务上限，默认 2。只防你自己误点连开的账单，不是产品限流 |
| `CACHE_ENABLED` / `CACHE_TTL_SECONDS` | 否 | POI / 天气 / 路线缓存，默认开启、10 分钟 |
| `LOG_LEVEL` / `LOG_FORMAT` | 否 | `text` 或 `json` |

和风天气只覆盖未来 7 天；行程超出这个范围会自动回退到 Open-Meteo，不需要你处理。

---

## 数据与隐私

- 所有行程存在 `backend/data/easy_travel.sqlite3`，删掉这个文件就等于清空。
- 页面上可以直接**删除单份行程**（结果页右上角）；`/plans` 能看到所有保存过的行程并逐条删除。
- “谁的行程”靠浏览器里的匿名 ID 区分，**不是账号，也不是鉴权**：
  - 清除浏览器数据后，旧行程会变成找不到的孤儿记录（文件还在）。
  - 同一浏览器才能看到自己生成的行程。
  - 不带这个 ID 的请求（`curl`、`/docs`、脚本）统一落到 `local` 这一个桶里，不会被拒绝——单机自用时不值得为这种事设门槛。

---

## 安全边界

默认 `FASTAPI_API_HOST=127.0.0.1`，只有本机能访问。

如果你把它改成 `0.0.0.0`（例如想让手机在同一局域网访问），等于**把一个没有鉴权的服务暴露给整个网络**：任何能访问该端口的人都能看你生成的所有行程、消耗你的模型额度。仅在同一可信网络下临时这样做。

同理，不要把它直接部署到公网 IP。真要做在线服务，需要先加鉴权、限流和 HTTPS——这些不在本项目的范围内。

浏览器里的匿名 ID 只做数据隔离，不做鉴权；它也**不是**成本保护，每日次数计数存在进程内存里，重启即清零。真正兜住花费的是你在模型服务商那边设的额度上限。

---

## 一个端口跑（可选）

不想开两个终端、也不要 Vite 开发服务器时，把前端构建一次，然后只跑后端——FastAPI 会自己把 `frontend/dist` 一起服务：

```bash
cd frontend && npm run build        # 只在第一次或前端改动后需要
cd ../backend
. .venv/bin/activate                # Windows: .venv\Scripts\Activate.ps1
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000> 即可，前端和后端在同一个端口，不需要代理。后端启动时会检查 `frontend/dist/index.html` 是否存在，存在才挂载；不存在就只提供 API。

日常改代码请用上面的 `scripts/dev.ps1`（有热更新），这个方式适合"跑起来用"而不是"改代码"。

---

## 费用

一次生成大约消耗 **600–1000 输入 token + 3000–7000 输出 token**，其中大部分是推理模型的思考 token。按常见 API 价格，一次约几分钱到几毛钱人民币。

耗时方面：默认配置约 25–45 秒；把 `LLM_REASONING_EFFORT` 设为 `minimal` 可降到 18–29 秒，评分基本不变。

想先看看效果、不想花钱：把 `USE_SAMPLE_DATA=true`，或用 `python -m evals --mode sample` 离线跑一遍 24 个用例。

---

## 常见问题

**生成出来写着“规则生成”？**
模型没生效。检查 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`，然后看后端日志里的 `llm.failed` 一行，原因会写清楚（超时、鉴权、模型名错误等）。

**高德相关数据都是“演示数据”？**
`AMAP_WEB_KEY` 没读到。注意变量名是 `AMAP_WEB_KEY`，不是旧版的 `FASTAPI_AMAP_WEB_KEY`。

**天气报 `403 Invalid Host`？**
和风现在按账号分配 API Host，把 `QWEATHER_HOST` 改成控制台里的那个主机名。

**历史计划不见了？**
浏览器数据被清过，匿名 ID 变了。这是当前设计的已知限制。

**能多开几个 worker 吗？**
不能。单进程 SQLite + 进程内的成本计数，`--workers > 1` 会导致锁库和统计不一致。

**能不能不带 `X-Client-Id` 直接调接口？**
可以。`curl` 和 `/docs` 不用带它，请求会落到 `local` 这一个桶里；只有想让多个浏览器各自隔离时才需要带。

---

**`ModuleNotFoundError: No module named 'pydantic'`？**
你用系统 Python 跑了。项目依赖都装在 `backend/.venv` 里，先进虚拟环境：

```powershell
cd backend
.venv\Scripts\Activate.ps1      # Windows
source .venv/bin/activate       # macOS / Linux
```

或者不用激活，直接指定解释器：`.venv\Scripts\python -m evals ...`（macOS/Linux：`.venv/bin/python -m evals ...`）。
下面的开发命令都假定已经激活。

---

## 开发与测试

```bash
cd backend
python -m venv .venv                # 首次；scripts/dev.ps1 已经建过就跳过
.venv\Scripts\Activate.ps1          # Windows（macOS / Linux：source .venv/bin/activate）
pip install -r requirements-dev.txt
ruff check src tests evals          # 后端 lint（含 flake8-bandit 安全规则）
ruff format --check src tests evals # 格式检查
python -m pyright                   # 类型检查（0 错误）
pip-audit -r requirements.txt       # 依赖漏洞
pip check                           # 依赖一致性
python -m pytest -q                 # 185 个测试 + 覆盖率（当前 81%）
python -m evals --mode sample       # 24 条 golden case 的离线基线（mean ≈ 72，可用率 100%）
python -m evals --mode live --limit 3 --judge   # 真实模型；只有这条能测出模型的真实可用性
cd ../frontend
npm run lint                        # ESLint（含类型感知与无障碍规则）
npm run lint:style                  # stylelint
npm run format:check                # Prettier
npm test                            # Vitest 单测（9 个，覆盖率当前 12.9%）
npm run test:e2e                    # Playwright：生成 / 编辑保存 / 导出 PDF
npm run build                       # 类型检查 + 打包
```

以上全部在 CI 里跑（`.github/workflows/ci.yml`），后端另外跑 Python 3.11 与 3.13 两个版本。

想在提交前就拿到反馈（而不是等 CI），装一次钩子：

```bash
pip install pre-commit
pre-commit install
```

跑 e2e 前需要先装一次浏览器。**国内网络下官方 CDN 通常下不动**，走镜像：

```bash
# 先装浏览器（只需一次）
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://cdn.npmmirror.com/binaries/playwright"   # Windows
export PLAYWRIGHT_DOWNLOAD_HOST="https://cdn.npmmirror.com/binaries/playwright"  # macOS / Linux
npx playwright install chromium
```

CI 里用的是官方 CDN，所以 `--with-deps` 那套只在 CI 需要。

### 质量门禁一览

| 检查 | 后端 | 前端 |
|---|---|---|
| lint | `ruff check`（E/F/I/UP/B/S） | `eslint`（recommended + 类型感知 + a11y，`--max-warnings=0`） |
| 格式 | `ruff format --check` | `prettier --check` + `stylelint` |
| 类型 | `pyright`（standard，src + evals） | `vue-tsc`（strict + `noUncheckedIndexedAccess`） |
| 测试 | `pytest` 185 个，覆盖率 81% | Vitest 9 个（覆盖率 12.9%）+ Playwright 3 条关键路径 |
| 依赖 | `pip-audit` + `pip check` | `npm audit`（**0 漏洞**，含 dev 依赖） |
| 自动升级 | Dependabot（pip / npm / actions） | 同左 |

覆盖率**只测量不设门槛**：数字用来定位该补哪里，不当作"代码对不对"的证明。

### 评测里的两把尺子

`evals` 回答两个不同的问题，都有独立门禁：

| 尺子 | 问题 | 门禁 |
|---|---|---|
| 综合分 | 行程**好不好**（动线、约束、偏好、预算加权） | CI：`--min-score 70` |
| **可用率** | 打印出来**能不能直接照着走** | CI：`--min-usable-ratio 1.0` |

可用率复用应用自身的阈值逐天检查 8 件事：有没有景点、景点间移动是否超 20 公里、
游览时长是否超 7 小时、单日强度是否超上限、三餐是否齐全、餐费是否超预算档位、
当天有没有闭馆、有没有重复景点。**不调用模型，不花钱**，所以每次 push 都跑。

需要知道的一点：**离线模式（`--mode sample`）下可用率恒为 100%** —— 因为规则引擎
本身就是确定性几何，排不出走不通的行程。所以 CI 那条是"结构回归守门员"，真正的
可用性测量要看模型：

```bash
python -m evals --mode live --limit 5 --min-usable-ratio 0.8
```

这一步会花钱（5 次真实生成），但它是唯一能回答"AI 排出来的行程能不能直接用"的命令。
运行后**先看 `degraded` 那一行**：如果 5 次全部降级，说明模型没调通，这次测到的还是
规则引擎，可用率 100% 并不能说明模型的表现。

### 在 GitHub 上手动触发（不用本地配环境）

仓库里有一个手动 workflow：`.github/workflows/live-eval.yml`。点 **Actions → Live eval → Run workflow** 即可，
可以在输入框里改用例数、可用率下限、允许的降级比例，以及是否加 LLM 评审。

首次使用需要在仓库设置里配四个值：

| 类型 | 名称 | 值 |
|---|---|---|
| Secret | `LLM_API_KEY` | 你的模型密钥 |
| Secret | `AMAP_WEB_KEY` | 高德 Web 服务 Key |
| Variable | `LLM_BASE_URL` | 例如 `https://api.deepseek.com` |
| Variable | `LLM_MODEL` | 例如 `deepseek-chat` |

用命令行配（会提示你粘贴，值不会进 shell 历史）：

```bash
gh secret set LLM_API_KEY
gh secret set AMAP_WEB_KEY
gh variable set LLM_BASE_URL
gh variable set LLM_MODEL
```

跑完在 run 页面直接能看到报告摘要；完整报告在 artifact `live-eval-report` 里。
配置缺失时它会在第一步就带一句明确提示失败，而不是跑出一份"降级率 100% 但可用率 100%"的假结果。


> 离线基线在 2026-11 从 85.9 降到 72.3，原因是修掉了一个指标缺陷：偏好命中率原本会把景点描述里的文字也算进去，而样例数据会把偏好串原样回显到描述里，于是"关键词出现了"被当成"行程符合偏好"。数字变低是尺子变准了——规则引擎用的是通用模板，本来就不该拿高分。判据写在 `outputs/平台化升级指导书.md` 的 ADR-6。

### 目录结构

```text
backend/
├── src/agent/       LangGraph 编排与规划/评审 Agent
├── src/planning/    排程、预算、密度、营业时间、critic、对话式修订
├── src/service/     LLM 网关、高德、天气、SQLite、缓存、日志
├── src/api/         FastAPI 路由、依赖、身份隔离
├── evals/           golden case 与评测指标
└── tests/
frontend/            Vue 3 + Vite + Ant Design Vue
scripts/             Windows / macOS 一键启动脚本
```

## 许可证

[MIT License](LICENSE)
