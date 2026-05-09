# AGENTS.md

本文件用于约束之后所有 Codex 任务。当前项目目标是先稳定现有股票量化分析网页，不做大规模重构，不改变现有页面主体风格。

## 项目背景

- 项目类型：股票量化分析网页，包含行情、K 线、智能筛选、AI 选股、模拟持仓、风控、策略记忆等功能。
- 当前主架构：FastAPI 单体后端 + 原生 HTML/CSS/JS 单页前端。
- 当前不使用 React/Vue 作为主前端框架。
- 当前优化方向：先提升稳定性、缓存、错误处理、任务控制和可维护性，再逐步考虑 Redis、PostgreSQL、Worker、router 拆分和前端拆文件。

## 项目目录结构

```text
.
├── backend/
│   ├── app/
│   │   ├── main_simple.py        # 当前主要 FastAPI 入口
│   │   ├── main.py               # 早期/备用 FastAPI 入口，当前主链路优先看 main_simple.py
│   │   ├── api/v1/               # 已存在的 router 雏形
│   │   ├── services/             # 主要业务逻辑：行情、筛选、AI、风控、组合、新闻等
│   │   ├── models/               # SQLAlchemy 模型雏形
│   │   ├── schemas/              # Pydantic schema
│   │   ├── core/                 # 配置、Redis、数据库、调度等基础模块
│   │   ├── analysis/             # K线、资金流、事件、风险复核等分析模块
│   │   ├── backtest/             # 回测模块
│   │   └── reports/              # 报告模块
│   ├── static/
│   │   ├── index.html            # 当前主前端页面
│   │   └── assets/               # 静态资源
│   ├── scripts/                  # 数据抽取、OCR、策略记忆、任务脚本等
│   ├── data/                     # 本地缓存、AI 策略记忆、资料抽取结果等
│   ├── tests/                    # 测试
│   ├── requirements.txt
│   └── run_simple.py             # 简化启动脚本
├── miniapp/                      # uni-app/Vue 风格移动端/H5 工程，非当前主网页
├── deploy/                       # 公网访问、Cloudflare Tunnel 等部署配置
├── tools/                        # 本地辅助工具
├── preview_server.py             # 本地预览启动器
├── 启动H5预览.bat
├── 架构优化策划书.md
└── AGENTS.md
```

## 启动方式

优先使用当前主入口：

```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main_simple:app --host 127.0.0.1 --port 8000
```

也可以使用：

```powershell
cd backend
.\venv\Scripts\python.exe run_simple.py
```

或在项目根目录运行：

```powershell
.\启动H5预览.bat
```

常用访问地址：

```text
http://127.0.0.1:8000
http://127.0.0.1:8000/api/v1/health
```

## 后端主要入口

- 当前优先入口：`backend/app/main_simple.py`
- 静态页面返回：`backend/app/main_simple.py` 读取 `backend/static/index.html`
- 主要接口路径：`/api/v1/...`
- 主要业务服务：`backend/app/services/`

开发时应先确认请求链路：

```text
backend/static/index.html
  ↓ fetch /api/v1/...
backend/app/main_simple.py
  ↓ 调用
backend/app/services/*.py
```

## 前端主要文件

- 当前主前端：`backend/static/index.html`
- 前端类型：原生 HTML/CSS/JS 单页应用
- 当前 API 请求封装在 `index.html` 内部
- 当前全局状态也主要在 `index.html` 内部
- 静态资源目录：`backend/static/assets/`

除非用户明确要求，不要把主前端迁移到 React、Vue、Next.js 或其它大框架。后续如需优化前端，优先考虑在原生 H5 基础上拆分 JS 文件，例如：

```text
backend/static/js/api.js
backend/static/js/state.js
backend/static/js/stocks.js
backend/static/js/aiPicker.js
backend/static/js/screener.js
backend/static/js/portfolio.js
backend/static/js/charts.js
```

## 开发约束

1. 修改前必须先简要说明计划，包括将改哪些文件、为什么改、预计如何验证。
2. 不要大规模重构；优先做小步、可验证、可回滚的修改。
3. 不要随意引入 React/Vue 或构建工具。
4. 不要改变现有页面主体风格，除非用户明确要求 UI 改版。
5. 不要删除现有功能；修复问题时要保持原有入口和主要行为兼容。
6. 修改接口时要保持现有前端调用兼容，除非同时更新前端并说明影响。
7. 新增功能必须考虑错误处理、超时、空数据、第三方接口失败和用户提示。
8. 涉及 AI、行情、K线、新闻、板块、回测等慢接口时，要考虑缓存、并发限制和失败兜底。
9. 涉及 API Key、模型配置、券商配置等敏感信息时，不能明文输出到前端或日志。
10. 不要把几千只股票一次性直接交给 AI；必须先本地规则粗筛，再分批复核。

## 文件删除约束

禁止批量删除文件或目录。不要使用：

```powershell
del /s
rd /s
rmdir /s
Remove-Item -Recurse
rm -rf
```

需要删除文件时，只能一次删除一个明确路径的文件，例如：

```powershell
Remove-Item "C:\path\to\file.txt"
```

如果需要批量删除文件，应停止操作并请求用户手动处理。

## 修改后必须说明

每次完成修改后，最终回复必须包含：

1. 修改了哪些文件。
2. 每个文件的主要改动。
3. 测试或检查方法。
4. 测试结果。
5. 如果有未测试项，明确说明原因。

## 推荐测试方法

后端语法检查：

```powershell
cd backend
.\venv\Scripts\python.exe -m py_compile app\main_simple.py
.\venv\Scripts\python.exe -m compileall app
```

前端内联 JS 语法检查可按现有项目方式抽取脚本后使用：

```powershell
node --check <extracted-js-file>
```

服务健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

关键页面检查：

```text
http://127.0.0.1:8000
```

涉及功能时，应优先给出可复现的接口或页面操作步骤，例如：

- 智能筛选：启动任务 -> 查询任务状态 -> 查看结果。
- AI 选股：启动后台任务 -> 轮询状态 -> 查看推荐和复核池。
- 股票详情：打开详情 -> 检查 K线、分时、评分、风险提示。
- 模拟交易：买入/卖出 -> 查看持仓、订单、统计。

## 架构优化方向

近期优先级：

1. 给行情、K线、市场快照、新闻、板块、AI 结果加缓存。
2. 限制 AI 选股、全市场筛选、回测任务并发。
3. 降低前端轮询频率，完成或失败后立即停止。
4. 给后端加统一错误处理、日志和请求耗时统计。
5. 记录慢接口，先找真实瓶颈再优化。

中期方向：

1. job 状态迁到 Redis。
2. 热点行情和短期任务结果迁到 Redis。
3. 用户配置、模拟持仓、订单、策略配置、AI 推荐历史迁到 PostgreSQL。
4. `main_simple.py` 逐步拆成多个 router。
5. `index.html` 内联 JS 逐步拆成模块文件。

长期方向：

1. AI、筛选、回测、日报周报迁到独立 Worker。
2. Redis 作为任务队列和状态中心。
3. PostgreSQL 作为核心业务数据源。
4. 后续再评估是否迁移主前端到 Vue/React。

## 重要原则

先稳定，再拆分；先缓存和限流，再上 Worker；先保持页面行为一致，再做前端工程化。每一步都要能独立验证，避免一次性大改导致问题难以定位。
