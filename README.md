# EasyTravel

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)
![Vue](https://img.shields.io/badge/Vue-3-42B883.svg)

**在你自己电脑上跑的 AI 旅行规划工具。** 填一个城市、几个日期、一点偏好，它一次性生成一份可以直接照着走的多日行程：每天去哪几个地方、什么时刻、怎么串联、住哪里、大概花多少钱。

没有账号，没有云端，不用注册。数据存在你机器上的一个 SQLite 文件里，模型和地图 Key 也用你自己的。

> 这是**本地单用户工具**，不是在线服务：默认只监听 `127.0.0.1`，没有鉴权。请不要把它暴露到公网，详见[隐私与安全](#隐私与安全)。

---

## 它能做什么

打开页面填一张表（城市、日期、天数、预算、交通、住宿、偏好），然后：

| 你可能想 | 它怎么做 |
|---|---|
| 先看看排出来什么样 | 几十秒后得到 1–14 天的行程：每天 1–3 个景点、起止时刻、站间路线、住宿、天气、预算 |
| "这次我一定要去西湖" | **必去地点**填进去，行程里就会出现且只出现一次；实时数据里找不到会直接告诉你，不会悄悄忽略 |
| "我周五下午才到" | 填**到达时间 15:00**，那天就按半天算，不会一落地就给你排三个景点 |
| "第三天太赶了" | 结果页底部用一句自然语言改，后端只动变化的部分，坐标、路线、时刻、预算全部重算 |
| "这家酒店太贵/这个点不想去" | 直接**手动编辑**：上下移动、删除景点，换酒店，然后保存 |
| "这个安排不对" | 每个景点旁边有个小旗标，点一下选原因（太满/不合适/不开放/太远），攒起来看规律 |
| 想带在路上看 | 导出图片、导出 PDF，或者**打印成文字可选的 PDF** |
| 想回头再找 | `/plans` 里有所有历史行程，可以逐条打开或删除 |

## 它不做什么

说清楚比较好用：

- **不规划餐食**。吃什么、在哪吃由你到了当地决定，工具只按预算档位给一个餐费估算。
- **不做预订**。没有门票余量、房态、餐厅可订位，价格是估算或接口给的参考值。
- **没有账号体系**。换台电脑、清一次浏览器数据，旧行程就找不到了（文件还在）。
- **不做多用户/多进程**。单进程 SQLite，`--workers > 1` 会锁库。
- **不猜开放时间**。数据里没写就是"未知"，不会替你编一个营业时间出来。

---

## 三步启动

要求：**Python 3.11+**（CI 覆盖 3.11 与 3.13）、**Node.js 20.19+ 或 22.12+**（CI 用 22）。

```bash
git clone https://github.com/bbcbc-lgh/Easy-Travel.git
cd Easy-Travel
```

### 1. 填配置

```bash
cp .env.example .env
```

全项目**只有这一份 `.env`**，放在仓库根目录。后端和前端都读它（Vite 通过 `envDir` 指向同一个文件），只有 `VITE_` 开头的键会被编译进浏览器包，所以服务端密钥不会漏到前端。

至少填一项能用的模型配置（任意 OpenAI 兼容服务）：

```env
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

再填一个高德 **Web 服务** Key（个人开发者免费申请），否则景点和路线会是演示数据：

```env
FASTAPI_AMAP_WEB_KEY=你的高德Key
```

想让结果页的地图能用，还需要**另一个**高德 Key——类型必须选「Web端(JS API)」，连它的安全密钥一起填。这两个 Key 不通用：

```env
VITE_AMAP_JS_KEY=你的JS API Key
VITE_AMAP_SECURITY_CODE=该Key对应的安全密钥
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

脚本会建虚拟环境、装依赖、补 `.env`，然后同时拉起后端和前端。

### 3. 打开

前端 <http://127.0.0.1:5173> · API 文档 <http://127.0.0.1:8000/docs>

不想用脚本就手动起两个终端：

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

> **一个 Key 都没有也能跑。** 会进入「规则规划」模式：用本地样例地点按距离和强度排出一份可演示的行程，页面上明确标注"规则生成"，质量分压到 60 以下。适合先看看界面长什么样。

---

## 它怎么工作

一次生成由三层拼起来：

| 层 | 负责 | 数据来源 |
|---|---|---|
| 数据层 | 候选景点、酒店、天气、路线 | 高德 Web 服务 + 和风天气（可选）/ Open-Meteo |
| 模型 | 只决定"每天去哪几个、住哪家、怎么描述" | 任意 OpenAI 兼容接口 |
| 确定性排程 | 按距离排序、按区域分组、按单日强度裁剪、排时刻 | 本地计算 |

模型返回的只有**名称**。坐标、门票、日期、预算、路线、时刻全部由服务端回填，所以模型无法编造价格和位置。

几处刻意的取舍：

- **降级会明说。** 模型连不上或输出不可用时，行程顶部写"规则生成"并给出原因（超时、鉴权、连不上等），不会假装成功。
- **价格有来源。** 每个价格带 `接口 / 估算 / 未知` 三种来源；`未知` 直接不显示金额，而不是显示 0 元。
- **编辑不造假数据。** 手动修改只接受库里已有的地点，客户端提交的坐标和价格一律丢弃。
- **单日强度是硬约束。** 模型挑哪几个，但"一天装得下几个"是算术：超标先让模型减一次，仍超标就按上限裁掉尾部，并在页面上写明移除了哪一个。
- **候选带事实，不只是名字。** prompt 里每个候选都写着类型、门票来源、建议时长、闭馆日、距酒店距离——模型看不到的事实它就会排错，而纠错要靠一次付费重排。
- **两阶段生成。** 先只决定"每天去哪几个"，等裁剪定稿后再单独写当日文案。这样长行程不会因为一次输出太长被截断，文案也不会写到已经被裁掉的景点。
- **有时刻表，但不猜开放时间。** 每个景点算出起止时刻；只有数据里**确实写了**营业时间，才会据此调整顺序。
- **必去点是硬要求。** 填了就必须出现且只出现一次。
- **到达/离开日不是完整的一天。** 首日下午才到、末日中午要走，那天的强度上限会收紧。
- **进度是真的。** 页面显示的是真实阶段（收集候选 → 规划 → 路线 → 检查 → 时刻表 → 文案）和真实耗时，最后一段文案是逐字流出来的。

---

## 配置项

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | 建议 | 模型密钥。留空则走规则规划 |
| `LLM_BASE_URL` | 否 | 兼容服务地址；用 OpenAI 官方可留空 |
| `LLM_MODEL` | 建议 | 模型名 |
| `LLM_TIMEOUT_SECONDS` | 否 | 单次调用超时，默认 120 |
| `LLM_MAX_TOKENS` | 否 | 输出上限，`0` = 服务商默认。推理型模型的思考 token 也占这个预算 |
| `LLM_REASONING_EFFORT` | 否 | 推理模型的思考预算：`minimal` / `low` / `medium` / `high`。留空用服务商默认 |
| `LLM_PROFILES` | 否 | 多模型回退链（JSON 数组），不填则由 `LLM_MODEL` 生成单个 |
| `LLM_JSON_SCHEMA` | 否 | 让服务商按 schema 强制结构化输出，默认关。**只在服务支持 `json_schema` 时打开**，否则请求会被拒 |
| `PLAN_TWO_PHASE` | 否 | 两阶段生成（先路线、后文案），默认开 |
| `PLAN_TOOL_LOOP` | 否 | 有界检索重试：模型点了候选里没有的地点时按名字查一次，默认开 |
| `FASTAPI_AMAP_WEB_KEY` | 建议 | 高德 Web 服务 Key；留空则用样例地点 |
| `FASTAPI_QWEATHER_API_KEY` | 否 | 和风天气 Key；配置后优先取预报 |
| `FASTAPI_QWEATHER_HOST` | 否 | **必须填控制台给你的 API Host**（形如 `abc123.re.qweatherapi.com`）。旧的 `devapi.qweather.com` 对新 Key 会返回 `403 Invalid Host` |
| `USE_SAMPLE_DATA` | 否 | `true` 强制离线：不调模型、不调高德，全部走本地样例 |
| `DATABASE_PATH` | 否 | SQLite 路径，默认 `backend/data/easy_travel.sqlite3` |
| `PLAN_DAILY_LIMIT` | 否 | 本机成本保护：同一浏览器每日生成次数，默认 20。**失败或中断的生成会退还次数**，只有真出结果的才计数 |
| `PLAN_MAX_CONCURRENCY` | 否 | 同时生成的上限，默认 2。只防你自己误点连开烧额度，不是产品限流 |
| `CACHE_ENABLED` / `CACHE_TTL_SECONDS` | 否 | POI / 天气 / 路线缓存，默认开启、10 分钟 |
| `LOG_LEVEL` / `LOG_FORMAT` | 否 | `text` 或 `json` |

和风天气只覆盖未来 7 天；行程超出这个范围会自动回退到 Open-Meteo，不用你处理。

---

## 费用与耗时

一次生成大约 **600–1000 输入 token + 3000–7000 输出 token**（推理型模型大部分消耗在思考 token 上）。按常见 API 价格，一次约几分钱到几毛钱人民币。

耗时（20 次真实生成、最多 3 天行程、0 降级）：

| 口径 | 中位数 | P95 |
|---|---|---|
| 单次模型调用 | 约 6 秒 | 约 17 秒 |
| **整单生成（你实际等的）** | **约 17 秒** | 约 28 秒 |

两个数要分开看：两阶段生成一次要调两三次模型，单次调用变快了不代表整单变快了。触发一次重排或重试会到 30 秒上下。

不想花钱先看效果：把 `USE_SAMPLE_DATA=true`，或者跑 `python -m evals --mode sample`（34 个用例，纯本地，不调模型）。

---

## 记一条"这个安排不对"

结果页每个景点右边有个小旗标按钮。点一下选个原因：**排得太满 / 地点不合适 / 当时不开放 / 距离太远 / 其他**。记过之后按钮变灰，同一处不会重复记（刷新也记得）。

为什么要有：评测能测出"排得满不满"，测不出"**这个地点我根本不想去**"。只有真的用它的人知道。

反馈存在 SQLite 的 `plan_feedback` 表里，**独立于行程**——行程被改或被删，反馈还在，因为它说的是规划器的问题。攒一些之后：

```bash
cd backend
python -m src.cli.feedback_report
python -m src.cli.feedback_report --notes 10   # 连自由文本说明一起看
```

第一行就是"最常见的问题是什么"。

---

## 常见问题

**生成出来写着"规则生成"？**
模型没生效。检查 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`，然后看后端日志里的 `llm.failed`，原因会写清楚（超时、鉴权、模型名错误、连不上等）。

**高德数据都是"演示数据"？**
`FASTAPI_AMAP_WEB_KEY` 没读到。后端变量统一带 `FASTAPI_` 前缀，和前端 `VITE_*` 放在同一个 `.env` 里。

**地图是空白 / 报"安全密钥"？**
两个高德 Key 不通用。结果页地图用的是 `VITE_AMAP_JS_KEY`（类型必须是「Web端(JS API)」）加上它对应的 `VITE_AMAP_SECURITY_CODE`，缺一个都是空白。页面会直接把原因写在原来的地图位置上。

**天气报 `403 Invalid Host`？**
和风现在按账号分配 API Host，把 `FASTAPI_QWEATHER_HOST` 改成控制台里的那个主机名。

**历史计划不见了？**
浏览器数据被清过，匿名 ID 变了。这是设计上的限制：靠浏览器里的匿名 ID 隔离数据，不是账号。

**能多开几个 worker 吗？**
不能。单进程 SQLite + 进程内计数，`--workers > 1` 会锁库、统计也不一致。

**`ModuleNotFoundError: No module named 'pydantic'`？**
你用系统 Python 跑了。依赖都装在 `backend/.venv` 里：

```powershell
cd backend
.venv\Scripts\Activate.ps1      # Windows
source .venv/bin/activate       # macOS / Linux
```

或者不激活，直接指定解释器：`.venv\Scripts\python -m evals ...`。

---

## 隐私与安全

- 所有行程存在 `backend/data/easy_travel.sqlite3`，**删掉这个文件就等于清空**。
- 只有模型请求会带上你的城市和偏好，发给**你自己配的那个模型服务**；高德只收到城市名和关键词。没有第三方统计、没有埋点、没有回传。
- 页面用浏览器里的匿名 ID 区分"谁的行程"，**这不是账号，也不是鉴权**：
  - 清浏览器数据后，旧行程变成找不到的孤儿记录（文件还在）；
  - 同一浏览器才能看到自己生成的行程；
  - 不带这个 ID 的请求（`curl`、`/docs`、脚本）统一落到 `local` 这一个桶里，不会被拒绝。

**安全边界。** 默认只监听 `127.0.0.1`。如果你改成 `0.0.0.0`（比如想让手机在同一局域网访问），等于把一个**没有鉴权**的服务暴露给整个网络：谁能访问这个端口，谁就能看你的所有行程、消耗你的模型额度。仅在同一可信网络下临时这么做，不要部署到公网 IP。真要上线，需要先加鉴权、限流和 HTTPS——那不在本项目范围内。

每日次数计数存在进程内存里，重启就清零，它是"防手滑"的护栏，**不是**成本上限；真正兜住花费的是你在模型服务商后台设的额度。

---

## 一个端口跑（可选）

不想开两个终端、也不要 Vite 开发服务器时，构建一次前端，然后只跑后端——FastAPI 会把 `frontend/dist` 一起服务：

```bash
cd frontend && npm run build
cd ../backend
. .venv/bin/activate                # Windows: .venv\Scripts\Activate.ps1
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000> 即可，前后端同一个端口，不需要代理。后端启动时会检查 `frontend/dist/index.html`，存在才挂载；不存在就只提供 API。日常改代码还是用 `scripts/dev.ps1`（有热更新）。

---

## 开发与测试

```bash
cd backend
python -m venv .venv                # 首次；scripts/dev.ps1 已经建过就跳过
.venv\Scripts\Activate.ps1          # Windows（macOS / Linux：source .venv/bin/activate）
pip install -r requirements-dev.txt

ruff check src tests evals          # lint（含 flake8-bandit 安全规则）
ruff format --check src tests evals
python -m pyright                   # 类型检查
pip-audit -r requirements.txt       # 依赖漏洞
python -m pytest -q                 # 400 个测试 + 覆盖率
python -m evals --mode sample       # 34 条用例的离线基线，不调模型、不花钱
python -m evals --mode live --limit 5 --min-usable-ratio 0.8   # 真实模型，会花钱

cd ../frontend
npm run lint                        # ESLint（类型感知 + 无障碍规则，--max-warnings=0）
npm run lint:style                  # stylelint
npm run format:check                # Prettier
npm test                            # Vitest 单测
npm run test:e2e                    # Playwright：6 条关键路径
npm run build                       # 类型检查 + 打包
```

以上全部在 CI 里跑（`.github/workflows/ci.yml`），后端另外跑 Python 3.11 与 3.13。

想在提交前拿到反馈，装一次钩子：

```bash
pip install pre-commit
pre-commit install
```

跑 e2e 前要装一次浏览器。**国内网络下官方 CDN 通常下不动**，走镜像：

```bash
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://cdn.npmmirror.com/binaries/playwright"   # Windows
export PLAYWRIGHT_DOWNLOAD_HOST="https://cdn.npmmirror.com/binaries/playwright"  # macOS / Linux
npx playwright install chromium
```

### 质量门禁

| 检查 | 后端 | 前端 |
|---|---|---|
| lint | `ruff check`（E/F/I/UP/B/S） | `eslint`（类型感知 + a11y，`--max-warnings=0`） |
| 格式 | `ruff format --check` | `prettier --check` + `stylelint` |
| 类型 | `pyright`（standard，src + evals） | `vue-tsc`（strict + `noUncheckedIndexedAccess`） |
| 测试 | `pytest` 400 个，覆盖率 81% | Vitest 77 个（覆盖率 62%）+ Playwright 6 条 |
| 依赖 | `pip-audit` + `pip check` | `npm audit`（0 漏洞，含 dev 依赖） |
| 自动升级 | Dependabot（pip / npm / actions） | 同左 |

覆盖率**只测量不设门槛**：数字用来定位该补哪里，不当作"代码对不对"的证明。

本地 Python 建议 **3.11–3.13**。3.14 通常也能跑，但它不在 CI 矩阵里。

### 评测：两把尺子

`evals` 回答两个不同的问题，各自有门禁：

| 尺子 | 问题 | CI 门禁 |
|---|---|---|
| 综合分 | 行程**好不好**（动线、约束、偏好、预算加权） | `--min-score 70` |
| **可用率** | 打印出来**能不能直接照着走** | `--min-usable-ratio 1.0` |

可用率逐天检查 7 件事，全部复用应用自身的阈值：每天有景点、单日移动不超 20 公里、游览时长不超 7 小时、单日强度不超上限、当天没有闭馆地点、没有重复景点、说明只提当天的地点。**不调用模型、不花钱**，所以每次 push 都跑。

评测只用确定性指标——不调用模型给自己打分。一个不准的"AI 评审"产出的不是证据，是看起来像证据的数字。

**离线模式的可用率恒为 100%**：规则引擎本身就是确定性几何，排不出走不通的行程。所以 CI 那条是"结构回归守门员"，真正测模型要用：

```bash
python -m evals --mode live --limit 5 --min-usable-ratio 0.8
```

跑完**先看 `degraded` 那一行**：如果 5 次全降级，说明模型没调通，这次测到的还是规则引擎，可用率 100% 说明不了模型的表现。

### 想改 prompt 或排程，先量再改

"这版比上版好了"不是结论，除非有分母。首轮通过率（一次生成就通过检查、没被打回重排的比例）和降级率，决定了改动到底有没有用，而日志里已经有全部原料：

```bash
LOG_FORMAT=json python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 > run.log

cd backend
python -m src.cli.quality_report --log ../run.log
```

```text
行程数     : 20
规划尝试   : 22（成功 22 · 降级 0）
重排请求   : 2
首轮通过率 : 90%
降级率     : 0%
模型调用   : 42 次
单次调用   : P50 5824ms · P95 16976ms
整单生成   : P50 17351ms · P95 27566ms（用户实际等待）
token 均值 : 输入 608 · 输出 1076
```

没有成功的生成时它显示 `n/a` 而不是 `0%`——"没测到"和"很差"是两件事。

改偏好相关的东西时，先看看高德真实返回的类型串，别照着自己的想象写映射：

```bash
python -m src.cli.poi_types --cities 杭州,北京
```

它会列出每个类型段出现了多少次、映射到哪个偏好轴，以及哪些段**根本没有映射**（那些景点在任何偏好上都不得分）。

### 目录结构

```text
backend/
├── src/agent/       LangGraph 编排与规划/评审 Agent
├── src/planning/    排程、预算、强度、营业时间、时间轴、critic、修订
├── src/service/     LLM 网关、高德、天气、SQLite、缓存、日志
├── src/api/         FastAPI 路由、依赖、数据隔离
├── src/cli/         反馈汇总、质量报告、类型映射检查
├── evals/           用例、确定性指标、可用率、门禁
└── tests/
frontend/
├── src/views/       首页、结果页、历史页
├── src/composables/ 结果页的四块独立逻辑（编辑 / 地图 / 导出 / 反馈）
├── src/utils/       纯函数：价格文案、地图错误、PDF 分页
└── e2e/             Playwright
scripts/             Windows / macOS 一键启动脚本
```

## 许可证

[MIT License](LICENSE)
