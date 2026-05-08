# 股票量化智能投研与模拟交易平台

一个面向 A 股市场的量化投研、AI 选股、风险复核与模拟交易平台。项目重点不是单一指标选股，而是把行情数据、资金流、K 线形态、公告风险、历史相似规则、游资短线经验和大模型复核串成一套可运行的决策流水线。

## 在线实例

- 在线访问：[https://www.ljreach.com](https://www.ljreach.com)
- GitHub 分支展示：[codex/global-audit-backup](https://github.com/tian1144/stock-quant-trading/tree/codex/global-audit-backup)

> 说明：线上实例用于项目演示，真实交易、券商连接、AI 密钥、邮箱验证码、验证码服务等敏感配置均通过服务器环境变量或本地私有配置管理，不提交到仓库。

## 项目亮点

- 全市场 A 股扫描：支持沪深北股票池、实时行情、K 线、分时、资金流、板块与新闻公告等数据融合。
- AI 分批选股流水线：先由本地量化引擎生成候选池，再分批交给大模型做质量打分，最后进入重点复核池并输出 2-3 只模拟推荐。
- 独立风控复核：支持主模型和风控模型分离，避免单一模型直接给出未经复核的交易建议。
- 策略记忆层：将短线交易原则、游资交割单/PDF/OCR 资料提炼为模型无关记忆，切换不同 OpenAI 兼容模型后仍能继承站内策略习惯。
- 历史相似规则校验：对当前形态构造历史样本，统计未来收益、胜率、止损命中与最大回撤，作为 AI 质量评分的先验。
- 可视化前端：单页 H5 展示行情、智能筛选、AI 推荐、重点复核池、模拟持仓、风控状态和站内 AI 助手。
- 后台任务化：全市场筛选、AI 选股、公告缓存、数据补齐等长任务均通过后台 job 和轮询进度完成，避免浏览器长请求超时。

## 技术栈

- 后端：Python、FastAPI、Uvicorn、Pandas、NumPy、Requests、APScheduler
- 前端：原生 H5 单页应用、ECharts；另包含 uni-app 小程序/H5 工程
- 数据层：本地 JSON/CSV 缓存、行情与公告数据源适配、策略记忆文件
- AI 能力：OpenAI 兼容接口、Claude/Gemini 等提供商适配、JSON 输出约束、任务级模型策略
- 部署：Cloudflare Tunnel / 服务器部署，前后端同域相对 API 路径

## 核心功能

### 1. 智能选股

系统会对全市场股票进行多因子评分，主要因子包括：

- 技术结构：趋势、支撑位、回落幅度、K 线形态、均线斜率
- 量价状态：成交额、量比、换手、分时承接
- 资金与板块：主力资金、板块热度、市场情绪
- 风险过滤：ST、停牌、公告风险、退市风险、监管/减持/业绩预警等
- 历史有效性：相似规则样本的胜率、平均收益、回撤表现
- 游资经验因子：情绪周期、主线板块、龙头地位、盘口承接、仓位纪律

### 2. AI 质量打分与复核池

全市场模式不会直接把所有股票塞进模型，而是采用流水线：

1. 本地量化引擎扫描全市场。
2. 生成第二阶段候选池。
3. 候选池分批交给 AI 做质量评分。
4. 选出约 20 只进入重点复核池。
5. 最终复核输出模拟推荐、观察理由、止损/止盈参考和风险提示。

### 3. 模拟交易与风控

- 支持模拟持仓、买卖信号、收益跟踪。
- 支持熔断开关、权限控制、访问账号/管理员角色。
- 推荐结果会标记为模拟盘参考，不作为真实投资建议。

### 4. 站内 AI 助手

站内 AI 可基于当前行情、任务产物、策略记忆和数据缓存回答问题，也可生成投研报告、复盘摘要、邮件发送任务等。任务执行使用后台 job 管理，支持进度与结果轮询。

## 目录结构

```text
backend/
  app/                 FastAPI 应用、服务层、AI 选股、风控、数据抓取
  scripts/             数据抽取、OCR、策略记忆写入等辅助脚本
  static/index.html    H5 单页前端
  requirements.txt     后端依赖
deploy/                公网访问与 Cloudflare Tunnel 示例配置
miniapp/               uni-app 小程序/H5 工程
tools/                 本地辅助工具
```

## 本地运行

### 后端

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main_simple:app --host 127.0.0.1 --port 8000
```

访问：

```text
http://127.0.0.1:8000
http://127.0.0.1:8000/api/v1/health
```

### uni-app 前端

```powershell
cd miniapp
npm install
npm run dev:h5
```

## 环境变量与私有配置

项目支持通过环境变量或本地私有 JSON 配置接入外部服务：

- `TUSHARE_TOKEN`：正式公告/财报等数据源
- `EMAIL_SENDER`、`EMAIL_AUTH_CODE`：邮箱验证码
- `TENCENT_CAPTCHA_APP_ID`、`TENCENT_CAPTCHA_APP_SECRET_KEY`：腾讯验证码
- `SMTP_HOST`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`：站内报告邮件发送

以下内容不会提交到仓库：

- AI 模型密钥
- 邮箱/验证码/券商账号配置
- 用户会话、验证码日志、任务产物
- 服务器 SSH 信息和私钥路径
- 行情缓存、公告缓存、模拟盘运行状态

## 部署说明

当前线上实例通过服务器后端服务加公网隧道提供访问。前端使用相对 API 路径，因此部署后 H5 页面和 API 可以在同一域名下工作。

部署参考文档：

- [deploy/public_access.md](deploy/public_access.md)
- [deploy/cloudflared/config.yml.example](deploy/cloudflared/config.yml.example)

## 验证记录

本版本推送前已执行：

```powershell
python -m py_compile backend/app/main_simple.py backend/app/services/auth_service.py backend/app/services/email_code_service.py backend/app/services/tencent_captcha_service.py backend/app/services/sms_code_service.py backend/app/services/data_fetcher.py
python -m compileall backend/app
```

前端内联脚本已抽取并通过 `node --check` 语法检查。

## 免责声明

本项目用于量化投研、模拟交易和工程能力展示。系统输出的股票筛选、AI 推荐、止盈止损和风险提示仅供学习与模拟盘参考，不构成任何投资建议。
