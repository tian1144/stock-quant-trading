# AGENTS.md

### 2026-05-04 对话 77：独立风控模型检测非 JSON 响应兜底

- 用户在页面配置独立风控交叉验证模型时遇到 `风控模型检测异常：Expecting value: line 1 column 1 (char 0)`，原因是部分 OpenAI 兼容网关不支持 `/models` 或返回 HTML/空响应，后端直接执行 `response.json()` 导致底层解析异常透出。
- 已修改 `backend/app/services/ai_model_service.py`：新增非 JSON 响应安全解析，主模型检测与独立风控模型检测都会返回友好中文错误、HTTP 状态、content-type 和短响应预览，不再把 `Expecting value` 直接抛给前端。
- 已修改 `backend/static/index.html`：独立风控模型检测失败时，如果用户已手动填写模型名，会自动调用保存配置并提示“可直接用于风控复核”；如果未填写模型名，则提示可手动填写后保存，兼容不支持 `/models` 的网关。
- 验证：`ai_model_service.py`、`multi_model_verify.py`、`main_simple.py` 语法检查通过，`backend/app` 全量 `compileall` 通过，前端内联 JS `node --check` 通过；本地模拟 HTML 响应确认主模型和风控模型检测均返回“接口返回的不是 JSON”友好错误。
- 后续用户重新填写小米 MiMo 网关后，已将独立风控复核模型切换为 `mimo-v2.5-pro`，保留用户新填的 `https://api.xiaomimimo.com/v1` 与密钥；修复风控模型“选择”按钮：点击时会同步输入框、给切换提示，并允许手动模型 ID 写入最近模型列表，避免不在旧检测列表时点选无反应。

### 2026-05-04 对话 73：游资交割单资料抽取与模型无关策略记忆喂入

- 用户提供本地资料目录 `E:\迅雷\下载目录\游资交割单`，要求仔细阅读分析游资交割单并将精华喂给项目 AI。
- 已新增只读抽取脚本 `backend/scripts/extract_youzi_trade_notes.py`：不修改源目录，使用 Python 标准库解析 `.docx/.pptx/.xlsx/.txt`，并输出统一报告到 `backend/data/ai/youzi_trade_notes/youzi_extraction_report.json`。
- 本轮扫描源目录共 880 个文件：PDF 395、DOCX 118、MP4 76、PNG 163、JPG 66、PPTX 14、XLS/XLSX 9 等；成功解析 134 份结构化文档。PDF、图片、视频、音频和旧版 Office 文件本轮先做索引，未做 OCR/转写。
- 抽取主题命中集中在：板块/龙头、买卖点、情绪周期、仓位风控、公告信息、看盘盘口、龙虎榜/交割单复盘。
- 已新增 `backend/scripts/append_youzi_memory_note.py`，将抽取结果压缩为 `游资交割单与短线课程抽取精华 v1` 学习笔记，写入 `backend/data/ai/strategy_memory.json`。
- 学习笔记沉淀的核心经验：短线围绕情绪周期、主线板块、龙头辨识度和承接强弱做概率选择；公告战法必须看市场氛围与板块联动；龙虎榜/交割单重点拆解买入位置、题材级别、卖出纪律和亏损处理；亏损时必须先降级，不允许补仓掩盖判断失败。
- 已修改 `backend/app/services/strategy_memory_service.py`：AI 上下文会自动注入最近 3 条学习笔记摘要，因此切换 DeepSeek、OpenAI 兼容模型或其他模型时仍可继承站内短线习惯。
- 验证：`backend/app` 全量 `compileall` 通过，新增脚本与 `preview_server.py` 语法检查通过；本地检查确认策略记忆学习笔记数为 3，AI 质量打分上下文已包含游资资料摘要。

### 2026-05-04 对话 74：游资经验落地到 AI 质量评分

- 用户要求把从游资交割单和短线课程中学到的经验落到 AI 评分中。
- 已在 `backend/app/services/stock_screener.py` 新增 `youzi_experience` 因子权重：默认 5%、短线 8%、长线 3%、事件驱动 8%。
- 新增 `score_youzi_experience()`：把情绪周期、低位回落支撑、主线/板块资金、龙头/次龙头地位、盘口承接、主力/散户结构、公告/消息是否被板块确认、历史相似规则和仓位赢面纪律合成 0-100 分。
- 逐只选股结果新增 `score_detail.youzi_experience` 与 `screening_logic.youzi_experience`，字段包含 `market_phase`、`leader_status`、`tape_status`、`position_advice`、`sector_confirmed`、`main_retail_confirmed`、`news_confirmed_by_sector` 和原因 notes。
- 已修改 `backend/app/services/ai_stock_picker.py`：AI 分批质量打分输入新增 `youzi_experience` 压缩证据；schema 新增 `youzi_quality_view`；系统提示要求 AI 必须复核情绪周期、主线板块、龙头地位、盘口承接、公告确认和仓位纪律。
- 本地 AI 质量兜底排序也纳入 `youzi_experience`，避免模型超时后游资经验完全失效。
- 最终交易复核候选也带上 `youzi_experience`，要求推荐理由说明游资经验字段，不再只看综合量化分。
- 验证：`backend/app` 全量 `compileall` 通过；合成样本测试 `score_youzi_experience()` 正常输出高赢面和仓位建议；已重启 `http://127.0.0.1:8000`，真实智能筛选后台任务跑完全市场 5511 只，返回候选已包含 `youzi_experience` 分与详细逻辑。

### 2026-05-04 对话 75：游资经验因子三层硬接入与前端展示

- 用户再次强调“这些数据作为 AI 打分因子，一定要接入”。
- 已增强 `backend/app/services/ai_stock_picker.py`：最终复核本地置信度从 `综合分/AI质量分/资金/K线` 改为加入 `youzi_experience`，当前权重约 16%；最终原因会写入“游资经验分、仓位纪律、游资复核 notes”。
- 新增 `_youzi_adjusted_quality_score()`：即使大模型返回了 AI 质量分，也会按本地游资经验再次校正；退潮、盘口过热、仓位建议仅观察会压分，主线确认且主力/散户结构确认会加分。
- AI 质量打分与最终交易建议 schema 均要求输出 `youzi_quality_view`，并在缺失时用本地游资经验 notes 补齐，防止模型忽略该因子。
- 已修改 `backend/static/index.html`：智能选股分项展示新增“游资经验”；选股上下文展示游资分、情绪阶段、龙头地位、盘口状态、仓位建议；AI 推荐购买、重点复核池、详情页 AI 复核都展示游资经验因子。
- 验证：后端 `compileall` 通过，前端内联 JS `node --check` 通过；合成校正测试显示强游资因子可把 70 分校正到 74.2，退潮+过热+仅观察可压到 51.4；已重启 `8000`，真实后台选股跑完全市场 5511 只，Top 候选返回 `score_detail.youzi_experience=73.0`、`market_phase=repair_or_hot`、`position_advice=中低仓模拟`。

### 2026-05-04 对话 76：PDF/OCR/图片交割单转写与学习，视频后置

- 用户要求开始处理 PDF/OCR/图片交割单转写并学习，视频放到最后。
- 已使用 PDF 技能流程检查依赖：项目 venv 缺少 `pypdf/pdfplumber/PIL/tesseract`，但 Codex bundled Python 具备 `pypdf` 与 `PIL`；Windows 系统自带 OCR 可用且有 `zh-Hans-CN` 识别器。
- 新增 `backend/scripts/extract_pdf_image_trade_notes.py`：只读扫描 `E:\迅雷\下载目录\游资交割单`，使用 `pypdf` 抽取 PDF 可复制文字，使用 `PIL` 建图片索引和 OCR 队列，输出 `backend/data/ai/youzi_trade_notes/pdf_image_extraction_report.json`。
- 本轮 PDF/图片扫描结果：PDF 395 份，其中 258 份成功抽取文字、87 份为扫描版需 OCR、50 份结构异常；图片 229 张，其中 141 张进入 OCR 队列、84 张低分辨率需后续增强、4 张打开失败。
- 新增 `backend/scripts/append_pdf_trade_memory_note.py`：将 258 份 PDF 文字资料压缩为 `游资PDF文字资料精华 v1` 写入策略记忆。PDF 主题命中集中在买点/低吸、仓位风控、龙头板块、情绪周期、龙虎榜复盘。
- 新增 `backend/scripts/ocr_image_winrt.ps1` 与 `backend/scripts/run_windows_ocr_images.py`：调用 Windows 内置 OCR，并在 OCR 前做灰度、放大、对比度和锐化预处理；输出 `backend/data/ai/youzi_trade_notes/image_ocr/windows_ocr_report.json`。
- 图片 OCR 结果：141 张高优先级图片全部尝试 OCR，127 张达到可学习阈值；覆盖退学炒股、BJ炒家、轮回666、善行天助、陈小群和部分课程截图。赵老哥等部分 JPG 识别质量较低，进入后续增强队列。
- 新增 `backend/scripts/append_ocr_trade_memory_note.py`：将 OCR 结果压缩为 `游资图片交割单OCR精华 v1` 写入策略记忆；强调图片 OCR 暂不直接生成精确逐笔流水，低置信度字段只能进入备注，不能参与权重训练。
- 当前策略记忆学习笔记数为 5，最近三条已自动注入 AI 上下文：图片交割单 OCR 精华、PDF 文字资料精华、游资交割单/短线课程精华。
- 验证：新增脚本 `py_compile` 通过，`backend/app` 全量 `compileall` 通过；未修改源资料目录，所有派生文件均写入 `backend/data/ai/youzi_trade_notes/`。

### 2026-05-03 对话 72：模型无关短线策略记忆与初始训练资料沉淀

- 用户提出希望 AI 后续可以根据模拟盘盈亏自我总结、调整选股因子，并且即使切换 DeepSeek 以外的模型也能继承记忆和习惯。
- 已明确实现方式：不是底层模型微调，而是建立模型无关的站内策略记忆层，所有 AI 调用自动注入同一份本地策略记忆。
- 已检索并整理外部资料方向：AkShare 龙虎榜接口、涨停池/跌停池接口，以及开源 A 股数据/多 Agent 项目（如 InStock、aiagents-stock）作为后续龙虎榜席位、涨停情绪、游资行为统计的数据源参考；不直接复制外部代码。
- 新增 `backend/app/services/strategy_memory_service.py`：管理 `backend/data/ai/strategy_memory.json`，包含短线猎人原则、偏好形态、避坑形态、入场/退出规则、因子学习纪律、后续龙虎榜/涨停池数据源建议和复盘问题清单。
- 已修改 `backend/app/services/ai_model_service.py`：`chat_json()` 和 `chat_text()` 会自动追加“站内策略记忆”，因此无论切换 OpenAI、Claude、Gemini、OpenRouter、DeepSeek 或其他 OpenAI 兼容模型，都能继承同一份策略习惯。
- 新增接口 `GET /api/v1/ai/strategy-memory` 查看策略记忆；新增 `POST /api/v1/ai/strategy-memory/notes` 追加人工/复盘学习笔记。
- 已写入两条初始学习笔记：一条为短线猎人初始训练摘要；一条来自真实 `8000` 服务最新智能筛选的 50 只候选样本摘要，包含前 10 只样本、历史有效性分和支撑池状态。
- 验证：`backend/app` 全量 `compileall` 通过；重启 `8000` 后 `GET /api/v1/ai/strategy-memory` 返回 `version=short-hunter-memory-v1`，学习笔记数为 2，策略记忆文件路径为 `backend/data/ai/strategy_memory.json`。
### 2026-05-03 对话 71：智能筛选后台任务化与进度轮询

- 用户要求继续检查测试并按建议推进。先确认真实 `8000` 服务健康、Tushare Token 后端可见、公告缓存状态正常，历史有效性权重仍在。
- 已新增智能筛选后台任务状态 `_screening_jobs` 和 `_run_screening_job()`，避免全市场同步筛选导致浏览器 HTTP 请求超时。
- 新增接口 `POST /api/v1/quant/screening/run/start`：启动后台智能筛选任务并返回 `job_id`。
- 新增接口 `GET /api/v1/quant/screening/run/status/{job_id}`：返回任务状态、阶段、进度、结果或错误。
- 保留旧接口 `POST /api/v1/quant/screening/run`，并改为 `asyncio.to_thread()` 执行，降低阻塞 FastAPI 事件循环的风险。
- 已修改 `backend/static/index.html`：`runScreening()` 改为启动后台任务并轮询状态；筛选页展示后台任务进度、失败原因；分项因子和选股上下文新增“历史有效”展示。
- 已修改 `backend/app/services/stock_screener.py`：`run_screening()` 支持 `progress_callback`，每 100 只更新一次进度，例如“智能选股评分中：1200/4816”。
- 验证：后端 `compileall app` 通过，前端内联 JS `node --check` 通过；TestClient 验证后台任务启动返回 200 且进入 `running`；真实 `8000` 验证后台任务可启动，状态显示全市场 5511 只且服务健康检查仍可响应。
### 2026-05-03 对话 70：相似规则历史有效性接入 AI 质量打分

- 用户确认公告缓存层可继续后，按建议顺序推进“相似规则历史回测有效性”。
- 新增 `backend/app/services/historical_rule_service.py`：读取正式日K，按候选当前形态构造近似规则样本，统计未来 5 日胜率、目标命中率、止损命中率、平均收益、平均最大涨幅和平均最大回撤；样本统计只作为历史先验，不用未来数据生成当前信号。
- 已修改 `backend/app/services/stock_screener.py`：选股权重新增 `historical_rule`，候选结果新增 `score_detail.historical_rule` 与 `screening_logic.historical_rule`；短线支撑/观察池或初筛质量较高的票会触发详细历史统计，其余返回中性 `not_triggered`，避免全市场逐只回测导致接口卡死。
- 已修改 `backend/app/services/ai_stock_picker.py`：AI 质量打分输入新增 `historical_rule_effectiveness`，包含历史样本数、胜率、目标命中率、止损命中率、平均收益和回撤；本地质量评分兜底也会纳入历史规则分。
- 已修正新增权重后的总分计算：按权重和归一化，避免因为增加历史因子导致整体分数阈值被抬高。
- 验证：`backend/app` 全量 `compileall` 通过；单股 `600519` 历史有效性测试返回 `sample_count=35`、`win_rate_pct=60.0`、`avg_return_pct=1.51`；120只小样本筛选成功，结果已带 `historical_rule` 字段。
- 真实 `8000` 服务已重启，`GET /api/v1/health` 返回新进程 `pid=18656`；公告状态接口仍正常，Tushare Token 后端可见。
### 2026-05-03 对话 69：正式公告/财报风险批量缓存层

- 用户确认页面已看到新服务生效后，继续按建议顺序推进“真实稳定的财报/公告源”。
- 已增强 `backend/app/services/disclosure_service.py`：公告风险命中返回 `risk_labels` 和 `matched_terms`，补充业绩修正、退市风险警示、集中竞价减持、监管工作函、证监会立案、内控否定、平仓风险等关键词；Tushare 返回非 0 状态时明确标记 `provider_error`，避免把权限/限流问题误判为无风险。
- 已新增正式公告/财报风险批量回填任务状态 `_disclosure_backfill_job`，并实现 `_run_disclosure_backfill()`，支持 `limit`、`offset`、`days`、`force_refresh`、`sleep_seconds`，默认低速调用，避免触发 Tushare 限流。
- 已新增接口 `GET /api/v1/market/disclosures/status`：返回回填任务进度、公告风险覆盖率、缓存目录和后端是否能看到 `TUSHARE_TOKEN`。
- 已新增接口 `POST /api/v1/market/disclosures/backfill`：启动正式公告/财报风险缓存回填，可先小批验证再分段扩大全市场覆盖。
- 验证：`backend/app` 全量 `compileall` 通过；`preview_server.py` 用 AST 纯语法检查通过；TestClient 验证公告状态接口返回 200，小批 1 只股票回填完成，`success=1`、`failed=0`。
### 2026-05-03 对话 65：AI 选股结果弹窗、失败持久化与旧服务排查

- 用户反馈再次运行 AI 选股仍没有结果，并提供截图：页面显示 `AI选股失败：signal is aborted without reason`，且信号页仅展示 `AI本次未完成`。
- 排查确认：此前取消本地降级推荐后，AI 失败状态没有持久化到后端 `state_store.ai_recommendations`；前端随后刷新 `/api/v1/quant/signals` 时会被后端空状态覆盖，造成“没有结果也没有清晰原因”。
- 已修改 `backend/app/services/ai_stock_picker.py`：新增 `_persist_ai_error_result()`，AI 未配置、质量打分失败/超时、最终复核失败/超时都会写入后端 AI 推荐缓存，并清除本轮 AI 买入信号；失败时不生成任何推荐结果。
- 已修改 `backend/app/main_simple.py`：`GET /api/v1/quant/signals` 返回前会对 `ai_recommendations` 做 `_json_safe()`，避免 AI 结果里包含 numpy/pandas 类型导致接口 500。
- 已修改 `backend/static/index.html`：前端 API 对 `AbortError`、`signal is aborted`、`Failed to fetch` 统一转成中文错误；AI 选股成功或失败后都会弹出需要点击“确定”的结果弹窗。
- 成功弹窗会总结：本次扫描股票数、按当前策略交给 AI 的候选数、AI 重点复核池数量、推荐购买数量和推荐股票名称；失败弹窗会展示失败范围、失败原因，并明确不生成推荐、不写入模拟买入信号。
- 排查发现用户浏览器仍连着占用 `8000` 端口的旧 python 进程，普通权限无法停止，导致新代码未生效；已用提升权限结束旧 8000 服务并启动新 `uvicorn app.main_simple:app --host 127.0.0.1 --port 8000`。
- 已完成检查：后端 `py_compile` 通过、前端内联 JS 语法通过；用 TestClient 验证 `/api/v1/quant/signals` 返回 200；实测关注股票 AI 选股 `002079` 调用 DeepSeek 成功，返回 `used_ai=true`、`reviewed_candidates=1`、`recommendations=0`，并能通过 `/api/v1/quant/signals` 读回复核池。

### 2026-05-03 对话 66：AI 全市场选股改为后端分批流水线

- 用户询问是否可以“在后端分批次请求，像流水线一样工作，直到所有批次全部请求完成再弹出提示框”。结论：这是全市场 AI 选股的正确架构，避免浏览器等待一个超长 HTTP 请求导致 `AbortError`。
- 已新增 `POST /api/v1/quant/signals/ai-pick/start`：前端只启动后台任务并拿到 `job_id`，后端线程继续执行量化筛选、AI 分批质量打分、重点复核池和最终交易建议。
- 已新增 `GET /api/v1/quant/signals/ai-pick/status/{job_id}`：前端轮询任务状态，直到 `done` 或 `failed` 后再弹出最终总结框。
- 已修改 `backend/app/services/ai_stock_picker.py`：`run_ai_stock_picking()` 和 `_ai_quality_score_candidates()` 支持 `progress_callback`；后端会持续写入阶段进度，包括准备股票池、量化筛选、候选完成、AI质量打分第 `x/y` 批、重点复核池和最终交易建议。
- 已修改 `backend/static/index.html`：AI 选股按钮改为启动后台任务，然后轮询状态；进度提示展示后端真实阶段与批次，例如“AI质量打分进行中：已完成3/7批”；所有批次和最终复核完成后才弹出成功/失败总结弹窗。
- 已完成检查：后端 `py_compile` 通过、前端内联 JS 语法通过；已重启 `http://localhost:8000`。用关注股票 `002079` 实测后台任务：状态从 `quant_screening` 到 `ai_quality_scoring` 第 `0/1` 批，再到 `final_decision/done`，最终 `used_ai=true`、复核池 1 只。

### 2026-05-03 对话 67：收紧短线猎人震荡支撑池口径

- 用户质疑短线猎人候选有四千多只不合理，指出类似“嘉美包装”这类震荡回落到支撑位且低位的股票应该是少数。
- 排查确认：此前 3614 只候选全部是 `support_pending_data`，即“K线不足、低吸形态待确认”，不是实际震荡支撑票；原因是全市场筛选没有主动读取正式日K缓存，并且短线 `return_all=True` 会把待确认池交给 AI。
- 已修改 `backend/app/services/stock_screener.py`：全市场逐只评分时会从正式日K缓存读取 `period_101`，用于判断箱体、支撑位、回落幅度、MA20斜率、5日涨跌和换手。
- 已修改短线入池逻辑：`support_pending_data` 只作为数据待补状态，不再进入 AI 全市场候选；入池不再只看支撑分，而是增加硬条件：贴近支撑、从箱体高位回落、箱体宽度合理、MA20斜率平缓、近5日不过热、当日不追高、换手不过热。
- 已修改 `run_screening(return_all=True)`：AI 全市场短线候选只返回严格 `support_pool`；前端普通 Top50 仍可展示少量 `near_support_watch` 观察池，便于人工查看。
- 已修改 `backend/app/services/ai_stock_picker.py`：若短线严格支撑池为空，会明确返回“短线支撑池为空”，不会把数据待确认股票交给 AI 硬选。
- 验证结果：原先 AI 候选约 3614 只；修正读取K线和硬条件后，AI 全市场严格候选为 314 只，全部为 `support_pool`，约占 5511 只的 5.7%；前端 Top50 中包含 18 只严格支撑池和 32 只近支撑观察池。
- 已完成后端 `py_compile`，并重启 `http://localhost:8000`。
- 用户随后反馈页面仍显示 4824 只候选、分 10 批且进度一直 0/10。继续排查确认：AI 选股传入了 `strategy=short`，但 `stock_screener.run_screening()` 仍从全局 `state_store.user_settings.trading_style` 读取策略，若全局策略不是短线，就会走普通综合排序并把硬过滤后的几千只股票交给 AI。
- 已修改 `backend/app/services/stock_screener.py`：`get_screening_weights(style=None)` 和 `run_screening(..., strategy=None)` 支持显式策略参数；显式传入短线时不再依赖全局用户设置。
- 已修改 `backend/app/services/ai_stock_picker.py`：AI 全市场选股和关注池兜底筛选都会调用 `stock_screener.run_screening(..., strategy=strategy)`，确保信号页下拉选择的策略真正贯穿后端。
- 验证：即使把全局 `trading_style` 设置为 `long`，显式 `strategy='short'` 仍只返回 314 只严格 `support_pool`；显式 `strategy='long'` 才返回 5115 只综合候选。重启后真实全市场 AI 后台任务状态显示“共315只候选，分1批”，不再是 4824 只/10批。

### 2026-05-03 对话 64：取消 AI 选股降级推荐、保护密钥、修复 V4Pro 切换

- 用户要求：DeepSeek 超时时不要再用本地规则降级生成推荐结果，而是明确弹出“AI响应超时”和处理建议；用户还反馈密钥被删除、点击切换 `deepseek-v4-pro` 没反应。
- 已修改 `backend/app/services/ai_stock_picker.py`：AI 选股必须在模型已配置且真实 AI 调用成功时才生成推荐；若质量打分或最终复核阶段超时/失败，接口直接返回 `error`、空 `recommendations`、空 `reviewed_candidates`、`signal_count=0`，不会写入本地规则推荐。
- 已修改 `backend/static/index.html`：前端收到 AI 选股错误时会清空本次 AI 推荐与复核池，并在鼠标位置提示具体失败原因和建议；文案从“AI降级选股完成”改为只显示“AI选股完成”或“AI未完成”。
- 已修改 `backend/app/services/ai_model_service.py`：保存连接配置时，空密钥或脱敏密钥不会覆盖本地已保存密钥；空接口地址也不会误删已有接口地址。模型检测时如果输入框为空但本地已有密钥，会自动使用本地密钥检测，不再要求重复粘贴。
- 已修改 `backend/static/index.html`：点击模型切换时不再先“假切换”界面，而是等待后端保存成功后再刷新模型状态；检测模型允许使用已保存密钥。
- 已修复并验证 `backend/data/ai/model_config.json`：当前 `selected_model=deepseek-v4-pro`，`has_api_key=True`，密钥仅以脱敏状态返回前端。
- 已完成检查：后端 `py_compile` 通过、前端内联 JS 语法通过；用测试桩验证 AI 超时会返回错误且不生成推荐；用接口实测从 `deepseek-v4-flash` 切回 `deepseek-v4-pro` 成功，且密钥仍保留。

### 2026-05-03 对话 63：修复 AI 选股 Failed to fetch 与系统状态 500

- 用户反馈点击 AI 选股后提示 `AI选股失败：Failed to fetch`。
- 排查发现 `8000` 端口旧进程处于监听但健康检查不可连接状态，已重启预览服务；随后发现 `/api/v1/quant/system/status` 返回 500，原因是 `backend/app/services/trading_engine.py` 使用 `risk_manager.get_risk_status()` 但未导入 `risk_manager`。
- 已修复 `backend/app/services/trading_engine.py`：补充 `risk_manager` 导入，系统状态接口恢复 200。
- 已修复 `backend/app/main_simple.py`：`POST /api/v1/quant/signals/ai-pick` 改为 `await asyncio.to_thread(...)` 执行阻塞 AI 选股流程，避免全市场 AI 分析期间卡死 FastAPI 事件循环，导致页面其他请求失败或浏览器显示 `Failed to fetch`。
- 已同步前端 AI 配置页 `backend/static/index.html`：新增“全候选质量打分”任务配置项，默认上下文 500；最终交易建议默认超时 90 秒、上下文 80；上下文输入上限提升到 1000。
- 已更新 `backend/data/ai/model_config.json`：写入 `ai_quality_scoring` 策略，并把 `trade_decision` 同步到 90 秒/80 条上下文。
- 已完成检查：后端 `py_compile` 通过、前端内联 JS 语法通过；重启后 `GET /api/v1/health` 与 `GET /api/v1/quant/system/status` 均返回 200。关注股模式实测 AI 选股接口返回 200；当前 DeepSeek 外部请求出现 read timeout 时会走本地降级结果，不再让页面空白。

### 2026-05-03 对话 62：全候选池 AI 分批质量打分与复核池优化

- 用户明确要求：不能只把 Top40/Top50 丢给 AI；应在第二阶段所有候选出来后，把全部候选交给 AI 做质量打分，再把 AI 认为合格的股票放入 20 只复核池，最终从复核池里选出最优 2-3 只推荐购买。
- 已修改 `backend/app/services/stock_screener.py::run_screening()`：新增 `limit` 与 `return_all` 参数。普通前端智能筛选仍展示前 50；AI 全市场选股可拿到完整第二阶段候选池。本次本地验证：5511 只股票硬过滤后约 4811 只，短线第二阶段候选池约 3414-3421 只。
- 已修改 `backend/app/services/ai_model_service.py`：新增 `ai_quality_scoring` 任务策略，温度 0.10、超时 120 秒、单批上下文候选数 500；`trade_decision` 调整为 90 秒、80 条复核上下文，用于“质量打分”和“最终交易建议”两段式分工。
- 已修改 `backend/app/services/ai_stock_picker.py`：全市场模式会重新生成完整候选池，对所有候选分批压缩为质量评分输入，并用最多 4 个并发批次调用 AI；AI 评分后按 `ai_quality_score` 取 20 只进入详细复核，再生成最终推荐。若 AI 批次失败，会按本地量化因子降级补齐，保证页面不空白。
- AI 质量打分输入已覆盖：量价、K线技术分、成交额/量比/换手、资金流、板块热度、新闻公告、估值/财务字段缺失、支撑回落结构、风险等级和本地选股理由。
- 已修改 `backend/static/index.html`：全市场 AI 选股按钮文案改为“全市场扫描 -> 第二阶段候选 AI 分批打分 -> 20 只复核池”；前端超时提升到 10 分钟，最终提示会显示 AI 评分股票数、推荐购买数和过滤观察数。
- 已完成检查：前端内联 JS 语法通过，后端 `py_compile` 通过；使用禁用真实 AI 的测试桩验证全市场链路返回 `market_scan_count=5511`、`eligible_count=3414`、`ai_scored_count=3414`、`candidate_count=20`、`reviewed_candidates=20`、`recommendations=3`、`signal_count=3`、`quality_batches=7`。

### 2026-05-03 对话 59：AI 选股范围拆分为关注股票与所有股票

- 用户要求把 AI 选股范围改为两个：`所有股票选股` 从 5511 只全市场候选中先量化筛选再 AI 复核；`关注股票选股` 从自选、智能筛选、短线震荡池、AI列表、持仓等用户或系统已关注股票中复核。
- 已修改 `backend/static/index.html`：信号页“启动AI选股”按钮右侧新增带向下箭头的 `AI选股范围` 下拉框，可选择 `关注股票选股` 或 `所有股票选股`，选择会保存到 `localStorage`。
- 前端新增 `buildAIFocusCodes()`：自动汇总自选、智能筛选结果、短线震荡池、AI列表和持仓中的股票代码，关注模式会把这些代码传给后端；若关注池为空，会提示先加入自选或运行智能筛选。
- 已修改 `backend/app/main_simple.py`：`POST /api/v1/quant/signals/ai-pick` 接收 `scope` 与 `focus_codes`，并记录到决策 Agent 事件。
- 已修改 `backend/app/services/ai_stock_picker.py`：新增关注股票候选构建逻辑；`scope=focus` 时按前端传入股票代码构造候选并合并已有筛选/实时数据，`scope=all` 时继续使用全市场智能筛选池排序后交给 AI；结果返回 `scope_label`、`focus_count` 和 `candidate_count`。
- 已完成前端内联 JS 语法检查与后端 `py_compile`；TestClient 实测关注模式和全市场模式均返回 200，并能正确区分 `关注股票选股` 与 `所有股票选股`。

### 2026-05-03 对话 60：所有股票选股无结果时显示 AI 复核观察候选

- 用户反馈点击 `所有股票选股` 后仍然一只股票都没有返回。
- 已复现实测：全市场模式会从 5511 只股票中量化筛选并送候选给 DeepSeekV4Pro，但后端此前只返回 `recommend_buy=true` 的推荐购买结果；当 AI/风控把全部候选判为观察、等待或风控未通过时，前端就会显示 0 只。
- 已修改 `backend/app/services/ai_stock_picker.py`：AI 选股结果新增 `reviewed_candidates`，保留最多 20 只已被 AI 复核但未达到买点的候选，同时继续只把 `recommend_buy=true` 写入 `recommendations` 和买入信号。
- 已修改 `backend/static/index.html`：信号页新增 `AI复核观察候选` 表格，展示被 AI 看过但暂不推荐买入的股票、AI分、结论、暂不推荐原因和单股 AI 判断入口；`AI推荐购买` 仍只显示真正买点。
- 已完成前端 JS 语法检查和后端 `py_compile`；TestClient 实测全市场模式返回 `candidate_count=20`、`reviewed_candidates=20`、`recommendations=0`，页面现在不会再完全空白。

### 2026-05-03 对话 61：全市场 AI 选股固定输出复核池与 2-3 只推荐

- 用户明确要求 `所有股票选股` 必须让系统把 5511 只股票全市场扫一遍，选出 20 只优质股票进入复核池重点观察，并从中选出 2-3 只推荐购买；同时反馈点击后仍然没反应。
- 已调整 `backend/app/services/ai_stock_picker.py`：全市场模式保留 `market_scan_count`，确认量化引擎会逐只扫描当前 5511 股票池；AI深度复核仍对量化筛出的高质量候选执行，避免把 5511 只全部原文塞进模型导致上下文爆掉。
- 全市场模式若严格 AI/风控没有给出买点，会从复核池内相对最优股票中强制挑选最多 3 只作为 `可小仓试单`，写入 `recommendations` 和模拟买入信号；同时在 `ai_reason` 中明确标注这是复核池内相对最优试单，仍需模拟盘与人工二次确认。
- `reviewed_candidates` 继续固定返回最多 20 只重点复核池，并按推荐购买优先、AI分排序；前端 `AI重点复核池` 会显示推荐股和观察股。
- 已将信号页文案从 `AI复核观察候选` 调整为 `AI重点复核池`，说明全市场模式会先扫全市场、保留 20 只重点复核、再选 2-3 只推荐购买。
- 已完成前端 JS 语法检查、后端 `py_compile`；TestClient 实测全市场模式返回 `market_scan_count=5511`、`candidate_count=40`、`reviewed_candidates=20`、`recommendations=3`、`signal_count=3`。
- 已重启 `http://localhost:8000` 预览服务，新页面已确认包含 `AI重点复核池`，避免浏览器继续连旧进程导致点击无反馈。

### 2026-05-03 对话 49：DeepSeekV4Pro 接入 AI 选股信号链路

- 用户要求检查 AI 工作分配是否遗漏、确认各板块 AI 接入是否合理，并在“信号”页新增按钮启动 AI 选股；推荐股票需要可进入详情，详情里展示买入理由、建议买入时间、买单价、卖单价、止损价、下个交易日 -10% 到 +10% 概率分布，以及 K线、交易量、业绩/暴雷风险等依据。
- 已在 `backend/app/services/ai_model_service.py` 新增通用 JSON 聊天调用能力：读取本地模型配置、按任务策略使用温度/超时/上下文限制，并调用 OpenAI 兼容的 `/chat/completions`；模型不可用时返回明确元信息，供业务降级。
- 已新增 `backend/app/services/ai_stock_picker.py`：先用现有量化选股池，再逐只补充评分卡、结构化决策、风控复核、K线摘要、量价、资金、新闻公告、估值财务可用性，交给 DeepSeekV4Pro 做交易复核；若模型或数据源不可用，使用本地规则生成可预览的降级推荐。
- 新增接口 `POST /api/v1/quant/signals/ai-pick`：启动 AI 选股复核，结果写入内存 `ai_recommendations`；只有达到可试单条件的推荐才写入买入信号，风控未通过或低分等待股只展示为推荐观察。
- `GET /api/v1/quant/signals` 已返回 `ai_recommendations`；股票详情 `/api/v1/stocks/{code}/detail` 已带回对应个股的 AI 推荐详情。
- 前端 `backend/static/index.html` 的“信号”页新增“启动AI选股”按钮、AI 推荐表、模型使用状态；股票详情新增“AI选股复核”模块，展示 AI 分、建议买入时间、买单价、卖单价、止损价、买入/等待理由、K线依据、成交量依据、业绩/暴雷风险说明、风控结论和 -10% 到 +10% 的 21 档概率表。
- 已验证 DeepSeekV4Pro 配置读取成功，并通过 TestClient 实际调用模型：`selected_model=deepseek-v4-pro`，`used_ai=True`。当前测试环境外部行情/板块/K线源多次代理断连，AI 基于本地股票池缓存和可用字段给出偏谨慎结论，推荐上汽集团、金发科技、中国船舶等为“风控未通过，暂不买入”，因此买入信号数为 0，这是正确的风控行为。
- 已完成 `backend\venv\Scripts\python.exe -m compileall backend\app`、`backend\venv\Scripts\python.exe -m py_compile preview_server.py`、前端内联 JS 语法检查。

### 2026-05-03 对话 50：个股详情 AI 分析按钮与站内 AI 对话窗口

- 用户要求每只个股详情内新增“AI分析”按钮，点击后该股票自动进入信号页的信息列表；打开后可以看到是否推荐购买、偏长期还是短期，并复用原有概率表和分析依据。
- 已新增 `backend/app/services/ai_stock_picker.py::analyze_single_stock()`：对单股聚合评分卡、结构化决策、风控复核、K线、量价、资金、新闻和估值财务字段，再调用 DeepSeekV4Pro 输出单股 AI 分析；结果写入 `state_store.ai_recommendations`，供信号页和详情页展示。
- 新增接口 `POST /api/v1/quant/stocks/{code}/ai-analysis`，用于详情页触发单股 AI 分析，并记录到决策 Agent 日志。
- 前端 `backend/static/index.html` 的股票详情操作条新增“AI分析”按钮；点击后会调用单股分析接口，把该股票加入“信号”页 AI 推荐/分析列表，并在详情中展示“AI选股复核”模块。
- AI 推荐表新增周期判断展示；详情分析模块新增“周期判断”，明确推荐购买/不急于买入、偏短期/长期。
- 用户要求网站内置 AI 对话模块，按 `Ctrl+Shift+A` 调出，可以和当前接入的大模型实时对话，且模型理解整个网站。
- 已新增 `backend/app/services/ai_model_service.py::chat_text()`，支持普通文本对话调用当前默认模型。
- 新增接口 `POST /api/v1/ai/chat`：会把当前页面、当前股票、策略、股票池数量、选股结果、AI推荐、持仓、风控、熔断、新闻样本和系统状态作为上下文传给模型；系统提示要求模型理解本站所有功能，并在交易问题中强调仅供研究/模拟盘参考、不能跳过风控。
- 前端新增右下角 AI 圆形按钮与浮动聊天窗，支持 `Ctrl+Shift+A` 唤起；聊天窗支持回车发送、Shift+Enter 换行。
- 已完成后端 `compileall backend\app`、`preview_server.py` 语法检查、前端内联 JS 语法检查。
- 已用 FastAPI TestClient 实测：`/api/v1/quant/stocks/600519/ai-analysis` 调用 `deepseek-v4-pro` 成功，返回 21 档概率表；`/api/v1/ai/chat` 调用 `deepseek-v4-pro` 成功并返回站内功能回答。当前外部行情/K线仍可能受代理断连影响，单股 AI 会在数据不足时给出偏谨慎结论。
本文件是本项目新的长期上下文记忆与 Agent 协作规范入口。后续开发时，优先读取并更新本文件；旧的 `上下文记忆.md` 作为历史流水归档保留，不再作为首要入口。

## 项目定位

- 项目路径：`C:\Users\Administrator\Desktop\lianghua1`
- 项目类型：股票量化智能投研、信号分析、模拟托管交易与 H5 预览工具。
- 核心参考：必须优先靠齐 `量化手册.txt`，量化手册没有覆盖的部分，再参考产品策划书和功能设计文档。
- 产品定位：不是大型量化公司的工业级高频机器，而是“小型、灵活、信息理解能力强的猎人”。
- 核心优势：高质量信号、低频率执行、小容量机会、强新闻/公告/情绪理解能力、灵活策略切换。
- 默认安全边界：先做只读分析和模拟交易；真实交易 API 默认关闭，必须经过长期测试、人工确认、权限隔离和合规审查后才允许接入。

## 长期目标

最终系统至少实现以下能力：

1. 数据层：查询股票列表、实时行情、分时、K线、成交量、盘口/资金/板块等数据。
2. 回测层：根据策略条件执行历史回测，输出收益、回撤、胜率、交易次数等指标，避免未来函数。
3. 新闻监控层：定时抓取新闻、公告、宏观数据、重要人物动态，并能在关键发布时间附近高频刷新。
4. 决策层：输出结构化交易建议，不做简单喊单。
5. 风控层：多模型验证、信息真伪校验、仓位控制、一票否决、熔断开关。
6. 执行层：先模拟交易，后续预留券商/QMT/交易 API。
7. 前端层：H5 可直接预览，界面参考手机端和 iPad 端同花顺，白色为主、红色为辅，信息密度高且精致。

## 核心交付物

量化手册定义的核心 JSON/报告需要持续实现并在前端展示：

- `market_snapshot.json`：行情快照。
- `backtest_report.json`：回测报告。
- `event_stream.json`：新闻/公告/宏观事件流。
- `score_card.json`：评分卡。
- `decision.json`：结构化交易建议。
- `risk_report.json`：风控复核报告。
- `paper_trade_log.csv`：模拟交易流水。

## 技术栈与入口

### 后端

- 语言：Python 3.10+
- 框架：FastAPI + Uvicorn
- 当前 H5 预览主入口：`backend/app/main_simple.py`
- 预览启动脚本：`preview_server.py`
- 双击启动脚本：`启动H5预览.bat`
- 默认预览地址：`http://localhost:8000`
- API 文档地址：`http://localhost:8000/docs`

常用命令：

```powershell
backend\venv\Scripts\python.exe preview_server.py
```

或双击根目录：

```text
启动H5预览.bat
```

### 前端

- 当前可直接预览页面：`backend/static/index.html`
- 访问方式：启动后端后打开 `http://localhost:8000`
- 兼容方式：若误用 `file:///.../backend/static/index.html` 打开，页面会请求 `http://localhost:8000`，但后端仍必须运行。
- 旧 `miniapp/` 目录保留为后续 uni-app/小程序方向，不是当前最快预览路径。

## 重要目录

```text
backend/app/services/      核心业务服务：行情、新闻、技术分析、选股、信号、风控、持仓、交易引擎
backend/app/analysis/      事件评分、情绪评分、K线评分、资金评分、决策结构、多模型验证、风控复核
backend/app/backtest/      回测引擎、指标、A股规则、反未来函数检查
backend/app/execution/     熔断开关、模拟交易执行
backend/app/reports/       日报与交易报告
backend/static/index.html  当前 H5 工作台
backend/data/backtest/     回测结果数据
```

## 当前已接入的关键 API

行情与股票：

- `GET /api/v1/health`
- `GET /api/v1/stocks`
- `GET /api/v1/stocks/search`
- `GET /api/v1/stocks/{code}/detail`
- `GET /api/v1/stocks/{code}/minutes`
- `GET /api/v1/stocks/{code}/kline`
- `GET /api/v1/stocks/{code}/chips`

量化功能：

- `POST /api/v1/quant/screening/run`
- `GET /api/v1/quant/screening/results`
- `GET /api/v1/quant/signals`
- `GET /api/v1/quant/news`
- `GET /api/v1/quant/risk`
- `GET /api/v1/quant/score/{code}`
- `GET /api/v1/quant/decision/{code}`
- `POST /api/v1/quant/risk-review/{code}`
- `POST /api/v1/quant/backtest/run`
- `GET /api/v1/quant/kill-switch/status`
- `POST /api/v1/quant/kill-switch/activate`
- `POST /api/v1/quant/kill-switch/deactivate`

组合与交易：

- `GET /api/v1/quant/portfolio`
- `GET /api/v1/quant/portfolio/positions`
- `GET /api/v1/quant/portfolio/orders`
- `POST /api/v1/quant/portfolio/buy`
- `POST /api/v1/quant/portfolio/sell`

## 当前 H5 预览页状态

`backend/static/index.html` 已具备：

- 总览页：资产、盈亏、市场情绪、熔断状态、Top5 选股、执行安全状态。
- 实时行情：股票列表、搜索、价格、涨跌幅、成交额。
- 搜索联想：输入一个字或代码片段即可显示候选股票；点击后在当前页面打开详情弹窗，不跳转外部网页。
- 股票详情：基础信息、分时图、日K线、成交量、技术指标、资金流、评分卡、结构化交易建议、风控复核、回测报告。
- 智能选股：运行选股、Top50、综合分、信号类型、理由、风险等级。
- 交易信号：买入/卖出信号，显式展示熔断状态。
- 模拟盘持仓：资产、现金、持仓市值、盈亏、持仓列表。
- 新闻监控：市场情绪、正负面新闻统计、事件流。
- 风控黑盒：总仓位、日亏损限制、今日交易次数、熔断开关、风控配置。
- 预留 UI：盘口结构分析、宏观数据日历、重要人物动态、holaOS Agent 桌面、回测实验室、QMT/券商接口。

UI 方向：

- 白色为主，红色为辅，参考同花顺移动端/iPad。
- 重要上涨/买入/正向信号用红色；下跌/卖出/负向信号用绿色或弱化色。
- 界面要高信息密度、清晰分区、避免营销式首页。
- 未开发功能可以预留 UI 位置，但必须标明状态，不要伪装成可用功能。

## 已完成的重要修复

- `backend/app/backtest/engine.py`：修复 MA5/MA20 策略持仓判断，使用 `bool(positions)`，避免单标的无法正常买卖。
- `backend/app/backtest/metrics.py`：按已平仓交易统计回测指标，新增 `order_count`，无亏损时盈亏比使用 `999.99` 避免 JSON 无穷值。
- `backend/app/services/risk_manager.py`：买入/卖出风控入口接入熔断检查。
- `backend/app/services/trading_engine.py`：自动交易执行前检查熔断；初始化阻塞逻辑改为 `asyncio.to_thread(...)`。
- `backend/app/services/data_fetcher.py`：新闻数据补充 `source` 字段。
- `preview_server.py`：新增稳定 H5 预览启动器，自动启动 FastAPI 并打开 `http://localhost:8000`。
- `启动H5预览.bat`：重写为可见前台服务窗口，避免双击后无反馈。
- `backend/static/index.html`：增强搜索联想、股票详情中文化、Canvas 分时/K线/成交量图表、评分/决策/风控/回测展示。

## 开发规范

1. 每次修改代码或关键决策后，更新本 `AGENTS.md` 的“工作记录”。
2. 任何功能实现优先对齐 `量化手册.txt`。
3. 不删除用户已有文件和历史记录，除非用户明确要求。
4. 改前端时优先保证 `backend/static/index.html` 可直接预览。
5. 后端改动后至少做语法/编译检查：

```powershell
backend\venv\Scripts\python.exe -m py_compile preview_server.py
```

```powershell
cd backend
.\venv\Scripts\python.exe -m compileall app
```

6. 前端改动后至少检查内联脚本语法，必要时启动预览服务验证。
7. 涉及交易执行、真实下单、仓位控制、熔断逻辑时，默认选择保守实现。
8. 真实交易 API 只能预留接口和 UI，不允许默认启用。

## holaOS 方向

用户提供的参考项目：`https://github.com/holaboss-ai/holaOS`

规划用途：

- 长周期工作流沙盒。
- Harness 状态持久化与断点续传。
- 多应用并发与全景桌面端，用于观察每个 Agent 在做什么。
- 高级路由，用于不同任务分配不同模型算力。
- 高级模型交叉验证和风险评估。
- 检索增强与反思能力，用于深度行业分析。

当前项目尚未正式集成 holaOS。后续若集成，必须先建立清晰边界：行情/新闻/回测/决策/风控/执行各自 Agent 的职责、状态文件、失败恢复方式。

## 风险与注意事项

- 当前服务依赖外部行情/新闻数据源，首次加载股票列表或详情可能较慢。
- 当前前端图表为轻量 Canvas 实现，不是专业行情图表库；后续可升级为 ECharts/K线专业组件。
- 当前预览服务必须保持黑色后端窗口运行；关闭窗口后网页会连接失败。
- PowerShell 可能显示 profile 执行策略警告，一般不影响项目运行。
- 当前项目以模拟盘为主，不构成投资建议。

## 工作记录

### 2026-05-04 对话 72：独立风控复核模型接口与多模型交叉验证落地

- 用户询问“多模型风控交叉验证，不能只靠一个 DeepSeek”是否已完成，并提出是否要新增另一个 AI 的 URL 和密钥输入。
- 结论：此前只有技术、资金、情绪、宏观四个本地规则裁判和接口框架，不是真正第二个独立 LLM 风控模型；本轮已补齐第二套独立 AI 风控复核配置和调用链。
- 已修改 `backend/app/services/ai_model_service.py`：`model_config.json` 新增 `risk_verifier` 配置区，独立保存风控复核模型的 provider、base_url、api_key、selected_model、available_models、enabled 状态；公开配置会脱敏返回 `api_key_masked/has_api_key`。
- 新增 `update_risk_verifier_config()`、`detect_risk_verifier_models()`、`select_risk_verifier_model()`、`risk_verifier_ready()`、`chat_json_with_risk_verifier()`；风控模型使用独立 URL/密钥/模型名，不复用主 AI。
- 已重写 `backend/app/analysis/multi_model_verify.py`：保留本地 `technical/capital/sentiment/macro` 四个裁判，并新增 `external_ai_risk` 独立 AI 风控裁判；若独立 AI 返回 `veto=true`，`can_execute` 会被否决。
- 未配置第二模型时，`external_ai_ready=false`，`external_ai_risk.reason=风控复核模型尚未配置或未启用`，不会伪装成已经做了外部 AI 复核。
- 已新增后端接口：`POST /api/v1/ai/risk-verifier/config`、`POST /api/v1/ai/risk-verifier/models/detect`、`POST /api/v1/ai/risk-verifier/models/select`。
- 已修改 `backend/static/index.html`：智能模型页新增“独立风控交叉验证模型”配置区，可启用、填写另一家 AI 的 URL/密钥/模型名、检测模型、选择模型；说明该模型只参与风控交叉验证，否决时会限制或禁止执行。
- 已完成检查：`ai_model_service.py`、`multi_model_verify.py`、`main_simple.py` py_compile 通过，`backend\app` compileall 通过，前端内联 JS `node --check` 通过。
- 已用 TestClient 验证：`GET /api/v1/ai/config` 返回 `risk_verifier`；保存风控配置接口返回 200；`GET /api/v1/quant/multi-model/600519` 返回 `external_ai_ready=false` 并明确提示未配置第二模型。
- 已清理测试占位 `risk-test-model` 和 `example.invalid` URL；当前独立风控模型处于未启用空配置。
- 已重启 `http://127.0.0.1:8000`，健康检查通过，当前 `boot_id=21388-1777870538`。

### 2026-05-04 对话 71：AI学习内容总盘点、对齐验证与站内AI问答修复

- 用户要求总结本轮对话从头到尾让 AI 学到了什么，检查是否与 AI 对齐，并验证代码和功能，确认 AI 是否理解透彻。
- 已检查 `backend/data/ai/strategy_memory.json`：当前模型无关策略记忆版本为 `short-hunter-memory-v1`，共有 7 条学习笔记，最新包括 `游资视频关键帧OCR精华 v1`、`交割单复盘候选表与AI学习边界 v1`、`游资图片交割单OCR精华 v1`、`游资PDF文字资料精华 v1` 等。
- 已确认 `ai_model_service.chat_json()` 与 `chat_text()` 会在真实模型调用前注入 `strategy_memory_service.get_model_memory_context(task_key)`，AI 质量打分、最终交易建议、深度分析都会收到站内策略记忆。
- 已确认 AI 输入上下文包含：低位箱体/支撑低吸、主力/散户结构、公告财报风险、historical_rule 历史相似规则有效性、youzi_experience 游资经验、OCR 候选不能当事实、视频关键帧短线经验。
- 已修复 `backend/app/services/strategy_memory_service.py` 默认兜底记忆里的历史乱码，确保未来迁移或重建 `strategy_memory.json` 时仍是干净中文。
- 验证站内 AI 对话时发现 `POST /api/v1/ai/chat` 返回 500；原因是 `_site_ai_stock_universe()` 在 `state_store.get_stock_universe()` 返回 dict 时直接迭代 key，导致 `_site_ai_match_stocks()` 里把字符串当股票 dict 使用。
- 已修复 `backend/app/main_simple.py::_site_ai_stock_universe()`：当股票池为 dict 时统一转换为 `list(stocks.values())`。
- 已完成检查：`main_simple.py` 与 `strategy_memory_service.py` py_compile 通过，前端内联 JS `node --check` 通过。
- 已用 TestClient 验证 `/api/v1/ai/chat` 从 500 恢复为 200，并真实调用 `deepseek-v4-pro`；模型能正确说明 OCR 候选不是事实、PDF 是原则/纪律、已校验复盘才可训练权重，并能概括买点类型、次日承接、亏损归因、主力散户、历史规则、公告风险等新增打分要求。
- 已重启 `http://127.0.0.1:8000`，健康检查返回 `status=ok`，当前 `boot_id=21128-1777869804`。

### 2026-05-04 对话 70：交割单校验页与视频关键帧学习

- 用户确认可以做交割单校验页，并要求做完后开始分析视频。
- 已新增 `backend/app/services/trade_review_service.py`：提供 OCR/PDF 交割单候选表读取、人工校验 upsert、`verified_trade_reviews.csv/json` 落盘，以及可选写入 AI 策略记忆。
- 已新增后端接口：`GET /api/v1/ai/trade-review/candidates`、`POST /api/v1/ai/trade-review/verify`；候选字段明确不是事实，必须人工确认后才进入正式复盘样本。
- 已修改 `backend/static/index.html`：系统配置菜单新增“交割单/复盘校验”页，可筛选候选状态、搜索来源/关键词、查看 OCR/PDF 预览、填写日期/股票/买卖方向/买点类型/盈亏/亏损归因/复盘备注，并可勾选写入 AI 策略记忆。
- 已验证接口：候选表读取返回 221 条；临时接口测试样本已清除，正式 `verified_trade_reviews` 当前为 0 条，未污染真实校验样本。
- 已修正 `backend/scripts/build_trade_review_candidates.py` 的中文分类与标签常量，避免后续重跑时把目录名和模式标签写成乱码。
- 已新增 `backend/scripts/index_youzi_videos.py`：扫描 `E:\迅雷\下载目录\游资交割单` 下 84 个视频，使用 `E:\ffmpeg\ffmpeg-n7.1-latest-win64-gpl-shared-7.1\bin\ffprobe.exe` 提取时长、分辨率、大小和主题优先级；输出 `backend/data/ai/youzi_trade_notes/video/video_index.json/csv`。
- 已新增 `backend/scripts/extract_video_frames_for_ocr.py`：对前 8 个高优先级视频抽关键帧，共抽取 50 张帧图；主题覆盖盘中异动、热点龙头、共振低吸、系统化止损、建仓拉升出货等。
- 已新增 `backend/scripts/run_windows_ocr_video_frames.py`：调用 Windows 简体中文 OCR 识别视频关键帧；首批 8 个视频全部可用，累计 OCR 字符数 21392，输出 `video_frame_ocr_report.json`。
- 已新增并运行 `backend/scripts/append_video_trade_memory_note.py`：写入 `游资视频关键帧OCR精华 v1` 到模型无关策略记忆，AI 质量打分现在会继承视频经验：盘中异动需结合板块联动、前排辨识度、资金承接和新主线；低吸买点重视热点未死、关键均线/支撑、恐慌释放后承接；止损和仓位纪律作为硬约束。
- 已完成检查：新增脚本与后端 py_compile 通过、`backend\app` compileall 通过、前端内联 JS `node --check` 通过；已重启 `http://127.0.0.1:8000`，交割单候选接口返回 200。

### 2026-05-04 对话 69：PDF/OCR/图片交割单转写与AI学习边界

- 用户要求先做 PDF/OCR/图片交割单转写学习，视频资料放到最后；资料目录为 `E:\迅雷\下载目录\游资交割单`。
- 已采用“候选复盘表优先、正式流水谨慎写入”的方案：不把 OCR 噪声直接写进 `paper_trade_log.csv`，避免错误股票代码、价格、买卖方向污染模拟盘和因子权重。
- 已新增并运行 `backend/scripts/extract_pdf_image_trade_notes.py`：扫描 395 个 PDF 和 229 张图片；PDF 中 258 份可直接抽文字、87 份需要 OCR 或为扫描版、50 份异常；输出 `backend/data/ai/youzi_trade_notes/pdf_image_extraction_report.json` 和 PDF 文本缓存。
- 已新增并运行 `backend/scripts/ocr_image_winrt.ps1`、`backend/scripts/run_windows_ocr_images.py`：调用 Windows 简体中文 OCR，完成 141 张待 OCR 图片，127 张可用、14 张低质量；输出 `backend/data/ai/youzi_trade_notes/image_ocr/windows_ocr_report.json`。
- 已新增并运行 `append_pdf_trade_memory_note.py`、`append_ocr_trade_memory_note.py`：将 PDF 文字资料和图片 OCR 中较可靠的短线经验写入模型无关策略记忆，供所有后续 AI 模型继承。
- 已新增并运行 `backend/scripts/build_trade_review_candidates.py`：生成 `trade_review_candidates.json/csv`，共 221 条候选复盘记录，其中 127 条需人工校验、14 条低质量待增强、80 条可作为经验摘要；覆盖退学炒股、赵老哥、BJ炒家、轮回666、陈小群、善行天助等目录。
- 已新增并运行 `backend/scripts/append_trade_review_schema_memory.py`：写入 `交割单复盘候选表与AI学习边界 v1`，明确 AI 可引用候选表的模式标签和复盘问题，但不得使用未校验 OCR 盈亏数据调整权重。
- 当前 `strategy_memory_service.get_model_memory_context()` 已能读到最新 6 条学习笔记，AI 质量打分会继承这些经验和边界。
- 已完成检查：`build_trade_review_candidates.py` 与 `append_trade_review_schema_memory.py` 语法检查通过，`backend\app` compileall 通过。
- 下一步建议：新增“交割单校验页”，展示原图/OCR/候选字段，由人工确认后写入 `verified_trade_reviews.csv`；之后再与 `paper_trade_log.csv` 合并，用于日报、周报、AI 复盘和因子权重微调。

### 2026-05-03 对话 68：项目体检后按顺序修复接口一致性、公告风险、AI评分因子与报告流水

- 用户要求按体检报告建议顺序开始修复，并在完成后说明已做、未做和下一步建议。
- 已修复运行环境一致性：`GET /api/v1/health` 新增 `boot_id`、`pid`、`cwd`、`project_root`、`hostname`、`code_mtime`，用于确认浏览器连接的是当前源码服务，避免旧 8000 进程导致接口行为与代码不一致。
- 已重启 `http://127.0.0.1:8000` 到当前源码，真实 HTTP 验证 `/api/v1/quant/score/600519`、`/api/v1/quant/decision/600519`、`POST /api/v1/quant/risk-review/600519` 均返回 200，旧服务导致的 500 风险已收口。
- 新增 `backend/app/services/disclosure_service.py`：结构化公告/财报风险摘要服务，支持可选 `TUSHARE_TOKEN` 拉取正式公告；未配置正式源时只使用站内新闻关键词兜底，并明确返回 `missing_formal_source`，不伪装成已完成正式公告核验。
- 新增 `GET /api/v1/stocks/{code}/disclosure-risk`，并把公告/财报风险挂入单股 `data-availability` 的 `disclosure_risk` 项。
- 已修改 `backend/app/services/stock_screener.py`：估值财务层纳入公告/财报风险扣分；新增 `summarize_retail_institution_flow()`，从内存或 E 盘资金流缓存计算主力净流入、主力占比、散户/中单压力、主力情绪和散户情绪。
- 已修改 `backend/app/services/ai_stock_picker.py`：AI 质量打分候选和最终复核上下文加入个股主力/散户结构、公告财报风险、大盘主力散户情绪；提示词要求 AI 把主力散户占比、大盘资金情绪、公告财报风险和相似规则历史有效性纳入评分。
- 已修改 `backend/app/reports/daily_report.py`：`generate_paper_trade_log()` 会落地 `backend/data/reports/paper_trade_log.csv`；新增 `generate_weekly_report()`。
- 已修改 `backend/app/main_simple.py`：`GET /api/v1/quant/report/paper-trade` 返回 CSV 路径和记录数；新增 `GET /api/v1/quant/report/weekly`。
- 已完成检查：后端 `compileall backend\app`、`preview_server.py` 语法检查、前端内联 JS 语法检查均通过；真实 HTTP 验证健康检查、评分、决策、风控复核、公告风险、数据可用性、覆盖率、paper trade、周报接口均返回 200。
- 尚未完成真实 Level2 五档/逐笔/撤单接入、多模型真实 LLM 风控、全市场正式公告/财报源覆盖和全量 K 线补库恢复到 100%；原因是这些依赖外部授权账号/数据商或长耗时全市场任务，后续应按“数据授权 -> 缓存补库 -> 风控/AI融合 -> 前端展示”的顺序继续。

### 2026-05-03 对话 51：行情数据补库与分时量/均线修复

- 用户要求继续获取缺失行情数据，并指出分时量和均线显示仍有问题。
- 已修复 `backend/app/services/data_fetcher.py::fetch_intraday_minutes()` 对东方财富 `trends2` 的字段解析：成交量改取第 6 字段、成交额改取第 7 字段、分时均价改取第 8 字段，避免把高价/低价误当作量和额。
- 已新增 `intraday_minutes_valid()` 并在读取分时缓存、`/api/v1/stocks/{code}/minutes` 返回前校验数据形态；旧的异常分时缓存不会再优先展示。
- 已重启 `127.0.0.1:8010` 预览服务，接口验证 `600519` 分时首分钟为成交量 408 手、成交额 5712 万、均价 1400.000。
- 已升级 `backend/scripts/fill_missing_market_data.py`：支持 `--intraday-only` 单独补缺失分时；周/月 K 聚合日期改为该周期最后一个真实交易日，避免节假日标签错位。
- 已修复覆盖率股票池口径：当前导入分母锁定 `active_total=5511`，原始缓存 `raw_total=5849` 只作为主数据变更参考，不再进入覆盖率进度条。
- 已继续修正前端显示链路：`refreshAll()` 对覆盖率/缓存状态请求使用 no-cache，数据覆盖率页股票池卡片和第二阶段进度条优先使用 active scope；`/` 首页响应也加 no-store，避免浏览器继续展示旧的 5849/93.96%。
- 已修正 `_stock_universe_incomplete()`：当当前 active 股票池达到 5511 时视为完整，避免后台监控线程因北交所样本检查再次触发外网刷新并把分母扩回 5849。
- 用户刷新后仍看到旧值，排查发现默认 `8000` 预览服务仍是旧进程，返回 `5849`；已重启 `preview_server.py`，现在 `8000` 与 `8010` 的覆盖率接口均返回 `stock_total=5511`、日/周/月 K `5496/5511=99.73%`。
- 修复股票详情数据闪现后消失的问题：`startRealtimePolling()` 之前会调用 `stopRealtimePolling()` 并清空 `state.liveMinutes/liveKlines`，导致详情图表刚渲染就被 1 秒轮询初始化清空；现改为只有关闭弹窗时才清空图表数据，启动/重启轮询只停止旧定时器。
- 用户反馈第二阶段卡在 5496；排查发现缺口集中在 `600843-600860` 的 15 只正常交易股票，已逐只强制拉取 verified 日K，并重新派生周K/月K；同时补齐这 15 只分时。
- 覆盖率统计已从“目录文件总数”改为“当前 5511 股票池逐代码匹配缓存”，避免历史缓存文件导致假满格或错误分母。
- 已改用新浪当前 A 股池恢复干净的 5511 股票池；当前 `8000` 与 `8010` 均验证：日K/周K/月K/实时/分时均为 `5511/5511=100%`。
- 用户要求详情 K 线像炒股软件一样有价格轴、时间轴、滚轮缩放和鼠标拖拽平移，并指出部分日K只显示一天。已修复 `/api/v1/stocks/{code}/kline`：当日K缓存短于展示窗口时强制刷新真实 K 线，不再直接返回 1 条旧缓存；以 `600519` 验证当前日K返回 86 条。
- 前端 `backend/static/index.html` 的日K/日线成交量图新增共享时间窗口：日K左侧价格轴、底部日期轴，鼠标滚轮缩放，按住拖拽平移；日线成交量跟随同一窗口同步缩放/平移。
- 已启动两条后台补库：资金流/筹码补库继续运行，分时补库单独运行；当前日/周/月 K 与实时覆盖约 94%，资金流继续增长，分时覆盖开始从个位数增长。
- 已完成 `backend\venv\Scripts\python.exe -m py_compile` 与 `backend\venv\Scripts\python.exe -m compileall app scripts` 检查。

### 2026-05-01 对话 15：规范上下文记忆并创建 AGENTS.md

- 用户要求将“上下文记忆.txt”规范化，并改成 `AGENTS.md`。
- 实际根目录存在 `上下文记忆.md`，未发现 `上下文记忆.txt`。
- 已创建新的 `AGENTS.md`，作为后续 Agent 协作、项目记忆、开发规范的首要入口。
- 旧 `上下文记忆.md` 暂时保留为历史流水归档，避免丢失早期上下文。

### 2026-05-01 对话 16：按同花顺截图重做股票详情交互

- 用户指出当前股票详情很多展示不准，要求参考同花顺详情页，并支持鼠标点击某个图表点位时单独显示当时信息。
- 已在 `backend/static/index.html` 新增同花顺式详情布局：顶部行情摘要、速递栏、分时/日K标签、左侧分时与指标图、右侧买盘口/明细、股票信息、涨停基因、量化复核。
- 分时图、MACD 指标图、量比图已支持鼠标悬停和点击显示点位信息；点击后信息框会固定在当前点位附近。
- 当前盘口、封单、内外盘等字段优先使用现有接口数据，接口缺字段时以现有实时行情/分时数据推导展示，后续应接入更完整的 L1/L2 盘口接口以替换估算值。
- 已完成 `preview_server.py` 语法检查、后端 `compileall app`、前端内联脚本解析检查，并确认本地 `http://localhost:8000/` 与 `603687` 分时接口可访问。

### 2026-05-01 对话 17：修正分时图全天时间轴与电脑端排版

- 用户反馈分时图有误，要求显示全天走势、点击可查看精确数据，并按电脑常规屏幕尺寸重新设计，画面干净整洁、数据合理。
- 已将 `backend/static/index.html` 中分时图横轴从“按数据点数量铺满”改为固定 A 股交易日时间轴：09:30-11:30、13:00-15:00；缺失时段不再被拉伸。
- 鼠标点击/悬停时按固定交易分钟坐标寻找最近真实分钟数据点，弹窗展示该分钟的时间、价格、涨幅、均价、成交等精确信息。
- MACD 与量比指标图同步改为同一交易日横轴，减少主图和指标图横向错位。
- 详情弹窗改为更适合电脑端的宽版布局：最大宽度提升，顶部行情区和右侧盘口区收紧，主图区域更宽，指标区高度降低，整体更清爽。
- 已再次完成前端内联脚本解析、后端 `compileall app` 和 `preview_server.py` 语法检查。

### 2026-05-01 对话 16：补强 H5 可用功能

- 用户反馈当前可用功能太少，希望继续完善功能，并在完成后说明已做内容与后续建议。
- 本轮优先增强 `backend/static/index.html`，把已有后端能力变成可直接点击体验的前端工作流。
- 新增“自选观察池”：可从行情列表或详情页加入自选，本地持久化到 `localStorage`，支持移出、打开详情、生成研究。
- 新增“个股研究报告”：输入股票代码后聚合详情、评分卡、结构化决策、风控复核、回测报告，形成中文投研摘要。
- 新增“回测实验室”：可输入股票代码、短均线、长均线和样本天数，调用 `/api/v1/quant/backtest/run` 展示收益、回撤、胜率、交易次数。
- 股票详情页新增操作条：加入自选、生成研究报告、跳转回测、模拟买入、模拟卖出；模拟交易仍会经过风控和熔断检查。
- 行情列表新增“自选”按钮，减少只能点详情查看的单一路径。

### 2026-05-01 对话 17：整体巡检、修复 UI 和预览可用性

- 用户要求检查整体代码和每个板块，修复 BUG，统一界面，左侧保持功能板块，修复部分板块缺少左上返回键和暗色残留。
- 已重构 `backend/static/index.html` 为单一干净实现，删除重复的 `openStock`、`amount`、`drawStockCharts` 覆盖问题。
- 当前 H5 统一为白色主界面、红色辅助，保留左侧功能导航：总览、行情、自选、研究、选股、信号、持仓、回测、新闻、风控、Agent、预留。
- 股票详情弹窗左上角固定加入“返回”按钮，同时保留右上角关闭按钮。
- 各板块重新梳理为空态、按钮、表格和卡片结构，避免暗色主题残留。
- 后端 `/api/v1/stocks` 和 `/api/v1/stocks/search` 改为优先返回缓存/本地演示股票池，避免外部行情源不可达时页面卡死。
- 为 `600519` 等演示股票提供行情 fallback，保证搜索、详情、研究和预览流程可验收。
- 已完成自动化检查：
  - `index.html` 内联脚本语法通过。
  - 前端函数重复检查通过，无重复核心函数。
  - 暗色主题残留检查通过。
  - 页面结构检查通过，12 个功能 section 均存在。
  - 后端 `preview_server.py` 和 `backend/app` 编译通过。
  - 临时启动预览服务后测试：首页、股票列表、中文单字搜索、代码搜索、股票详情、K线、组合、风控、熔断、信号、新闻接口均返回成功。
- 浏览器实点测试尝试使用 Codex in-app browser 和 Edge headless，但受当前环境权限限制未能完成；已用 HTTP/结构/脚本测试替代覆盖。

### 2026-05-01 对话 18：回测增强接入新闻情绪与市场状态

- 用户要求“回测增强”：把新闻情绪和当时市场状态并入回测。
- 已新增 `backend/app/backtest/context.py`，按回测日期构建上下文：新闻事件只在其发布时间之后、指定窗口内参与评分，避免把今天新闻泄漏到历史交易。
- 回测上下文包括新闻分数、正负面/恐慌/FOMO计数、K线推导的市场状态、MA20乖离、5日动量、20日波动率、综合上下文分、风险暂停、仓位倍率。
- `BacktestEngine` 已支持可选 `context_provider`，每天生成上下文历史；买入会按上下文风险过滤并调整仓位，卖出可被极端上下文触发风险退出。
- 新增 `create_context_ma_crossover_strategy`，作为带情绪/市场状态过滤的 MA 均线回测策略。
- `/api/v1/quant/backtest/run` 已改用上下文增强策略，并在报告中返回 `context_summary` 与 `context_samples`。
- `generate_backtest_report` 已保留上下文摘要和样本，供 H5 或后续报告展示。
- 已完成 `preview_server.py` 语法检查、后端 `compileall app`，并用最小样本验证 `context_summary` 可生成。

### 2026-05-01 对话 18：新增策略配置中心

- 用户要求新增“策略配置中心”，支持长线、短线、事件驱动三种策略切换。
- 已在 `backend/static/index.html` 新增独立“策略”导航页，提供三张策略卡片，展示持有周期、复核频率、评分重点、默认回测参数和执行规则。
- 当前策略会持久化到 `localStorage`，顶部工具栏显示当前策略，切换后会清空旧研究/回测结果，避免不同策略结果混淆。
- 个股研究报告、股票详情评分/决策/风控复核、回测实验室默认参数已跟随当前策略：长线默认 MA20/MA60、短线默认 MA5/MA20、事件驱动默认 MA3/MA10。
- 事件驱动当前前端已传递 `event_driven` 策略参数，并强化事件/情绪/可信度说明；后端评分权重若未专门定义，会沿用现有短线兜底逻辑，后续应在 `decision_schema.py` 中补齐事件驱动权重。

### 2026-05-01 对话 18：新增 Agent 工作台

- 用户要求把数据、新闻、评分、风控、执行拆成多个 Agent 状态卡，为后续 holaOS 集成铺路。
- 已在 `backend/static/index.html` 新增“Agent 工作台”导航入口与页面。
- 工作台包含 5 张 Agent 状态卡：数据 Agent、新闻 Agent、评分 Agent、风控 Agent、执行 Agent。
- 每张卡展示职责边界、当前状态、关键指标、对应产物文件和后续 holaOS 状态文件接入点。
- 新增 Agent 流水线视图：数据采集 -> 事件理解 -> 评分决策 -> 风控否决 -> 模拟执行。
- 新增 holaOS 集成边界说明：独立 state.json、断点恢复、模型路由、安全边界和后续落地清单。
- 已完成前端内联脚本语法检查、`preview_server.py` 语法检查、后端 `compileall backend\app`，并确认本地健康检查接口可访问。

### 2026-05-01 对话 18：盘口结构分析真实 UI

- 用户要求把“盘口结构分析”从预留功能做成真实 UI，覆盖买卖五档、委比、封单、撤单风险。
- 已在 `backend/static/index.html` 新增盘口结构分析样式与计算逻辑：优先读取实时五档字段，缺少 L2/五档字段时使用实时行情、分时成交、量比、涨跌幅等做保守推断，并在 UI 中明确标注数据来源。
- 股票详情弹窗右侧盘口区已升级为卖五到买五完整盘口、委比、封单额、封单/成交额、撤单风险评分与解释，不再只显示单侧买盘。
- “预留功能位”中的盘口结构分析已改为可输入股票代码的分析卡片，可直接拉取详情、分时和 K 线数据后展示盘口结构结论，并支持跳转打开个股详情。
- 已完成前端内联脚本语法检查、`preview_server.py` 语法检查和后端 `compileall app` 编译检查。

### 2026-05-01 对话 19：新闻/公告影响因子评分面板

- 用户要求新增“新闻/公告影响因子评分面板”，并把新闻直接绑定到个股研究报告。
- 已在 `backend/static/index.html` 复用现有事件评分口径，新增 S/A/B/C 影响等级、事件影响分、平均冲击、情绪同振、方向结构、可信度和风控复核提示的前端展示。
- 个股研究报告生成时新增并行请求 `/api/v1/quant/news/event-score/{code}` 与 `/api/v1/quant/sentiment?code={code}`，报告头部新增“新闻影响”指标，正文新增“新闻/公告影响因子”面板。
- 个股报告内的新闻列表会优先展示后端按股票代码/名称匹配出的直接相关新闻；若事件评分接口已有结构化事件，则优先展示结构化评分事件。
- 新闻监控页新增全市场影响因子排序，展示最高影响分、S/A 事件数量、B 级公司事件和噪音/待证实事件，并按事件影响分排序展示。
- 已完成前端内联脚本语法检查、`preview_server.py` 语法检查和后端 `compileall backend\app` 编译检查。

### 2026-05-02 对话 20：策略配置中心三策略切换

- 用户要求做“策略配置中心”，支持短线猎人、长线观察、事件驱动三套策略可切换。
- 已在 `backend/static/index.html` 新增“策略”导航页，三张策略卡展示持有周期、复核频率、默认回测参数、评分重点和执行规则。
- 当前策略持久化到浏览器 `localStorage`，顶部工具栏会显示当前策略；切换策略会清空旧研究/回测结果，避免不同策略口径混用。
- 个股研究、详情弹窗、评分卡、结构化决策、风控复核和回测实验室已跟随当前策略传参。
- 后端 `decision_schema.py` 已补充 `event_driven` 权重，并为事件驱动策略设置更短窗口的止损/止盈和事件证伪失效条件。
- 后端 `/api/v1/quant/backtest/run` 已接收策略参数并在报告中返回 `strategy_type`；策略列表接口补充三套业务策略说明。

### 2026-05-02 对话 20：新闻/公告影响因子绑定评分与仓位

- 用户要求继续做“新闻/公告影响因子评分”，把新闻直接和个股评分、仓位建议绑定。
- 已在 `backend/app/analysis/event_scoring.py` 新增 `news_impact_factor`：综合事件等级、方向、可信度、是否已反映、正负面数量，输出影响分、方向偏向、仓位倍率、仓位上限、动作偏向和风险提示。
- `get_event_score_for_symbol` 返回的 `event_score` 已改为新闻影响因子调整后的事件分，避免高影响负面新闻只作为展示信息、不影响综合评分。
- `backend/app/analysis/decision_schema.py` 新增 `event_driven` 权重；评分卡新增 `news_impact_score` 和 `position_policy`，仓位建议会按新闻影响因子进行增强、降仓、暂停或待核验处理。
- `backend/app/analysis/risk_review.py` 已接入同一套 `news_impact_factor` 与 `position_policy`，风控报告会按新闻因子压低仓位上限，严重负面或暂停信号可否决执行；即使方向为 `wait` 也保留新闻/仓位因子。
- `backend/static/index.html` 的个股研究报告和详情弹窗新增“新闻/公告影响因子”卡片，展示影响分、方向、事件数、最高等级、仓位倍率、仓位上限、动作偏向、建议仓位、摘要和风险提示。
- 已完成 `preview_server.py` 语法检查、后端 `compileall app`、前端内联脚本语法检查，并用 `600519` 验证评分卡、决策和风控报告均返回新闻影响与仓位策略字段。

### 2026-05-02 对话 20：完善盘口结构分析

- 用户要求实现“盘口结构分析”：买卖五档、委比、封单、主动买卖、大单异动。
- 已在 `backend/static/index.html` 新增盘口分析计算与展示：买卖五档、委比、封单额/封成比、主动买入/主动卖出、分钟级大单异动、盘口强度、撤单风险和结论。
- 若实时接口缺少完整 L1/L2 五档字段，前端会基于实时行情、分时成交、成交额、量比和资金流做保守推导，并在 UI 中明确展示数据口径，避免伪装成真实逐笔数据。
- 股票详情弹窗中的“预留盘口结构”已替换为真实盘口结构分析面板。
- 个股研究报告已绑定盘口结构分析结果，生成报告时同步拉取详情、分时和 K 线数据用于盘口复核。
- “预留”页已改为可直接输入股票代码运行的“盘口结构分析”入口，保留宏观日历、重要人物动态、券商/QMT 接口为后续预留项。
- 已完成前端内联脚本语法检查、`preview_server.py` 语法检查、后端 `compileall backend\app`，并用临时预览服务验证健康检查、`600519` 详情和分时接口均返回成功。

### 2026-05-02 对话 20：新闻情绪联合回测

- 用户要求做“新闻情绪联合回测”：回测时叠加当时新闻、公告、情绪环境。
- 已升级 `backend/app/backtest/context.py`：按事件发布时间构建联合上下文，拆分新闻、公告、情绪环境和当时 K 线市场状态，避免未来新闻/公告泄漏到历史交易日。
- 联合分数权重为：新闻 25%、公告 20%、情绪环境 20%、市场状态 35%；风险暂停会受 S 级事件、负面公告、恐慌情绪、市场 stress 状态共同触发。
- `BacktestEngine` 的交易记录和 `context_samples` 已保留新闻、公告、情绪环境样本，`context_summary` 新增平均新闻分、公告分、情绪分、公告覆盖率、极端情绪天数和风险暂停占比。
- `/api/v1/quant/backtest/run` 新增 `news_window_days` 与 `announcement_window_days` 参数，并返回 `joint_context` 说明与权重。
- `backend/static/index.html` 的回测实验室、个股研究报告和股票详情回测卡已展示“新闻情绪联合回测”摘要。
- 已修正情绪/市场快照防未来函数逻辑：没有历史时间戳的快照不再平铺到旧回测日期，带 `scored_at` 的情绪只在对应日期短窗口内参与，否则按中性处理。
- 已完成 `preview_server.py` 语法检查、后端 `compileall app`、前端内联脚本语法检查，并用最小样本和真实接口验证事件只在发布时间之后参与回测。

### 2026-05-02 对话 20：Agent 工作台实装

- 用户要求实装“Agent 工作台”：数据、新闻、评分、决策、风控、执行各自状态与日志，为 holaOS 集成铺路。
- 已新增 `backend/app/services/agent_workspace.py`，统一定义 6 个 Agent 的职责、产物、状态文件、日志文件和安全边界。
- 新增接口：
  - `GET /api/v1/quant/agents`：返回 6 个 Agent 状态、指标、最近日志、流水线和本地存储根目录。
  - `POST /api/v1/quant/agents/snapshot`：写入每个 Agent 的 `state.json`，为后续 holaOS Harness 接管预留。
  - `GET /api/v1/quant/agents/logs`：读取指定或全部 Agent 的事件日志。
- 已把选股、信号检测、评分卡、结构化决策、风控复核、熔断、模拟买卖等关键动作写入对应 Agent 的 `events.jsonl`。
- 前端 `backend/static/index.html` 的 Agent 工作台已改为真实 API 驱动，展示 6 个 Agent 状态卡、指标、最近日志、产物、handoff 路径、流水线和 holaOS 接入约束。
- 本地状态与日志路径为 `backend/data/agents/{data|news|score|decision|risk|execution}/state.json` 与 `events.jsonl`；真实交易仍默认关闭，执行 Agent 仅显示和记录模拟盘动作。
- 已完成 `preview_server.py` 语法检查、后端 `compileall backend\app`、前端内联脚本语法检查，并用 FastAPI TestClient 验证 `/api/v1/quant/agents` 和 `/api/v1/quant/agents/snapshot` 均返回 6 个 Agent。

### 2026-05-02 对话 21：修复股票详情错误行情数据

- 用户反馈股票详情中分时图、K线、交易量等大部分数据错误，要求先修复当前错误数据。
- 已修改 `backend/app/services/data_fetcher.py`：分时数据默认不再失败后生成估算曲线；K线函数新增 `allow_fallback`，真实详情接口可关闭估算 fallback；真实分时/K线行增加 `source` 字段，估算数据也明确标记为 `estimated`。
- 已修改 `backend/app/main_simple.py`：`/api/v1/stocks/{code}/minutes` 与 `/api/v1/stocks/{code}/kline` 不再把估算数据静默返回给股票详情；数据源不可用时返回 `status/source/message`，明确提示“停止使用估算曲线/K线”。
- 股票详情技术指标获取日K时同样关闭估算 fallback，避免用虚假K线计算 MA、MACD、RSI 等指标。
- 已修改 `backend/static/index.html`：成交额和成交量分开格式化，成交量显示为“手/万手/亿手”；详情图表标题展示数据源或缺失状态；分时图改为 A 股固定交易时间轴 09:30-11:30、13:00-15:00，避免半天数据被拉伸成全天走势。
- 已完成 `preview_server.py` 语法检查、后端 `compileall backend\app`、前端内联脚本语法检查；当前环境访问东方财富被代理断开，接口会返回 unavailable 状态，不再显示伪造图表。

### 2026-05-02 对话 22：补充日K落盘缓存

- 用户指出当前仍然没有日K缓存。
- 已在 `backend/app/services/data_fetcher.py` 新增 K线落盘缓存目录：`backend/data/market_cache/kline/period_{period}/{code}.csv`。
- 真实 K线/日K从东方财富拉取成功后会自动写入 CSV 缓存；数据源失败或返回空时，会优先读取本地缓存并将 `source` 标记为 `cache_file`。
- `fetch_daily_bars` 与 `fetch_kline` 都已接入同一套缓存，股票详情、技术指标、回测等复用日K时可从历史真实缓存恢复，不再依赖内存缓存或估算K线。
- 已完成 `preview_server.py` 语法检查、后端 `compileall backend\app`，并用临时测试 DataFrame 验证缓存写入和读取；测试文件已按单文件明确路径删除。

### 2026-05-02 对话 22：新闻板块多源聚合与去重

- 用户要求新闻来源不能太单一，需要加入更多财经新闻源，包括韭研公社、华尔街见闻等，并对重复新闻去重，保证消息面广泛。
- 已在 `backend/app/services/data_fetcher.py` 新增多源新闻聚合：财联社、新浪财经、东方财富 7x24、证券时报、华尔街见闻、韭研公社；单个外部源失败不会影响整体刷新。
- 已新增新闻标准化、标题指纹去重、重复来源合并、来源统计和来源保底逻辑；去重后仍会保留各成功来源的代表内容，避免小众题材源被时间排序挤掉。
- 已在 `backend/app/services/state_store.py` 增加 `news_meta`，保存来源数量、原始条数、去重后条数、重复合并条数和来源分布。
- 已修改 `backend/app/services/news_service.py` 和 `backend/app/main_simple.py`：`/api/v1/quant/news` 与 `/api/v1/quant/news/refresh` 返回 `source_meta`，新闻 Agent 日志记录来源覆盖和去重数量。
- 已修改 `backend/app/analysis/event_scoring.py`：同一新闻被多个来源命中时，事件可信度按多来源确认提高，减少单源传闻权重过高的问题。
- 已修改 `backend/static/index.html` 新闻监控页：新增“刷新多源新闻”按钮、来源覆盖、原始/去重数量、来源分布和每条新闻的合并来源展示。
- 已完成 `preview_server.py` 语法检查、后端 `compileall app`、前端内联脚本语法检查，并用真实刷新验证可获取新浪财经、东方财富、证券时报、华尔街见闻、韭研公社 5 个来源，样本去重后保留 150 条。

### 2026-05-03 对话 23：补充传统财经媒体与同花顺自选消息

- 用户要求把金融时报、证券时报等传统财经媒体发布的新闻公告纳入消息面，并尽量接入同花顺自选股推送消息。
- 已扩展 `backend/app/services/data_fetcher.py` 新闻源：金融时报/中国金融新闻网、FT中文网、证券时报更多栏目、上海证券报、同花顺公开财经/股票新闻。
- 已新增同花顺自选兜底采集：前端刷新新闻时会把浏览器本地自选股代码传给 `/api/v1/quant/news/refresh`，后端按代码抓取 `stockpage.10jqka.com.cn/{code}/news/` 的个股新闻公告，并标记为 `同花顺自选`。
- 真实同花顺 App 登录后的自选推送依赖用户登录态/设备推送通道，当前不伪造登录；先使用同花顺公开个股新闻公告页作为可运行数据源。
- `news_service.refresh_news()` 与 `fetch_news_multi_source()` 已支持 `watchlist_codes` 参数；新闻 Agent 日志会记录本轮自选代码数量。
- 新闻页说明已更新为覆盖传统财经媒体、同花顺公开新闻和自选股个股消息。
- 已完成 `preview_server.py` 语法检查、后端 `compileall app`、前端内联脚本语法检查；用 `600519/300750/000858` 自选样本真实刷新验证，当前可获取金融时报、FT中文网、证券时报、上海证券报、同花顺、同花顺自选等 9 个来源。

### 2026-05-02 对话 23：新增板块资金流与新闻归因工作区

- 用户要求新增左侧“板块”板块，展示所有行业/概念板块、资金流入流出、新闻集成、板块详情、龙头股/热门股、行情走势和总板块资金流入折线图。
- 已扩展 `backend/app/services/data_fetcher.py`：板块列表和板块资金流支持行业板块与概念板块两类东方财富口径，单次最多拉取 300 条并带 `sector_type`。
- 已重写 `backend/app/services/sector_service.py`：合并行业/概念板块，记录服务运行期间的总板块主力净流入快照，按新闻标题/正文给每条新闻打利好、利空、中性标签，并按板块名和关键词分配到相关板块。
- 新增/增强接口：`GET /api/v1/sectors` 返回板块概览、总资金流快照、新闻归因统计；`POST /api/v1/sectors/refresh` 刷新板块和资金流；`GET /api/v1/sectors/{code}` 返回板块详情、资金分拆、龙头股、热门股、成分股和主要新闻。
- 已在 `backend/static/index.html` 左侧导航新增“板块”，页面包含总板块资金流入图、板块资金流/新闻热度列表、板块详情、资金流分拆、龙头股/热门股和板块主要新闻；刷新新闻后会同步重算板块新闻标签。
- 已完成 `preview_server.py` 语法检查、后端 `compileall app`、前端内联脚本语法检查，并用 FastAPI TestClient 验证板块接口可返回 200 个行业/概念板块；真实刷新新闻后已有半导体、军工、AI 芯片等板块被打上新闻标签。

### 2026-05-02 对话 24：AI 模型接口配置中心

- 用户要求开始接入 AI 模型接口：输入 URL 和密钥后检测当前密钥可用模型，支持官方 API 和主流第三方 API，并由系统统一管理后续接口调用配置。
- 已新增 `backend/app/services/ai_model_service.py`：支持 OpenAI 官方、OpenAI 兼容网关、Anthropic Claude、Google Gemini 和自定义供应商；OpenAI 兼容网关用于适配 DeepSeek、通义千问、Moonshot、智谱、OpenRouter、硅基流动、火山方舟等支持 `/v1/models` 的服务。
- 新增接口：`GET /api/v1/ai/providers`、`GET /api/v1/ai/config`、`POST /api/v1/ai/models/detect`、`POST /api/v1/ai/models/select`、`POST /api/v1/ai/policy`、`POST /api/v1/ai/config/clear`。
- AI 密钥只保存在后端本地 `backend/data/ai/model_config.json`，前端和接口只回传脱敏状态；`.gitignore` 已忽略该配置文件，避免误提交密钥。
- 前端 `backend/static/index.html` 新增左侧“AI模型”页面：可选择供应商、填写 API Base URL 与 API Key、检测模型、选择默认模型、清空配置，并配置温度、超时、最大上下文事件数、是否必须风控复核等调用策略。
- 默认安全策略保持保守：AI 可参与新闻理解、评分、决策和风控复核，但真实交易决策默认关闭，仍必须经过风控复核。
- 已完成后端 `compileall app`、`preview_server.py` 语法检查、前端内联脚本语法检查，并用 FastAPI TestClient 验证 AI 配置、模型检测空密钥提示、模型选择和清空配置接口可用。

### 2026-05-03 对话 25：修复个股详情 AI 分析 500

- 用户反馈点击个股详情“AI分析”后提示 `AI分析失败：500 /api/v1/quant/stocks/600126/ai-analysis`。
- 已复现问题：`ai_stock_picker.analyze_single_stock()` 组装模型上下文时混入 pandas/numpy 标量，`json.dumps` 无法序列化，导致后端 500。
- 已在 `backend/app/services/ai_model_service.py` 增加 `_json_safe()`，模型调用前统一把 pandas/numpy 标量、时间、集合等转换为普通 JSON 类型。
- 已在 `backend/app/services/ai_stock_picker.py` 增加结果级 `_json_safe()`，保证 AI 分析返回给前端时不会再因为 numpy 类型触发响应序列化错误。
- 已给 `POST /api/v1/quant/stocks/{code}/ai-analysis` 增加异常捕获和 Agent 错误日志，后续即使内部异常也会返回结构化错误，不再直接 500。
- 已完成后端 `compileall app`、`preview_server.py` 语法检查、前端内联脚本语法检查；用 FastAPI TestClient 验证 `/api/v1/quant/stocks/600126/ai-analysis` 返回 200，并能返回 `analysis.ai_action`、`ai_rank_score` 和 `ai_meta.used_ai`。
- 用户再次反馈页面仍显示 500，经确认是 `localhost:8000` 上的旧预览进程仍在运行，且重启后默认生命周期初始化会拖住健康检查。
- 已将 `preview_server.py` 的 Uvicorn 预览启动改为 `lifespan="off"`，让 H5 预览优先响应页面和接口，行情/缓存继续按接口懒加载，避免启动初始化阻塞调试。
- 已停止旧 8000 端口进程并重启预览服务；真实 `http://localhost:8000/api/v1/health` 返回 ok，真实 `POST /api/v1/quant/stocks/600126/ai-analysis` 返回 200，返回 AI 结论、评分和 `used_ai=True`。

### 2026-05-02 对话 24：阅读量化选股.docx 并升级智能选股

- 用户在项目根目录新增 `量化选股.docx`，要求阅读后判断合理性，并结合已完成的板块、新闻、情绪、数据功能升级智能选股。
- 文档思路整体合理：基础资格过滤、估值/PB/市值、现金流健康、新闻热点、AI 选股、尾盘/竞价/价量/连续下跌接近支撑等都可作为选股框架；但财务和日内逐笔/集合竞价字段当前数据源不完整，不能伪装成真实结论，需按中性分并标记缺失。
- 已升级 `backend/app/services/stock_screener.py` 为 `sector-news-factor-v2`：新增资格层、估值财务层、板块热度层、个股新闻层、短线形态层，并保留量价、资金、技术和市场情绪。
- 选股权重按策略区分：短线偏量价/资金/板块，长线偏资格/估值财务/技术，事件驱动偏板块/新闻/资金。
- 板块层会读取行业/概念板块排名、主力资金流和新闻归因，并抓取热点板块成分股映射到个股；个股新闻层会匹配股票代码/名称，并考虑多源新闻去重后的来源确认。
- 估值财务层支持 `pe_ttm`、`pb`、总市值、经营现金流、资本开支、自由现金流；字段缺失时返回中性分和 `missing` 列表，不直接否定或美化。
- 前端 `backend/static/index.html` 的“智能选股”页已展示新逻辑版本、权重、分项分、板块/新闻匹配和财务缺失字段。
- `/api/v1/quant/screening/results` 与 `/api/v1/quant/screening/run` 已返回 `logic` 说明，单个候选返回 `screening_logic` 详情。
- 已完成 `preview_server.py` 语法检查、后端 `compileall app`、前端内联脚本解析，并用 FastAPI TestClient 验证 `/api/v1/stocks` 初始化和 `/api/v1/quant/screening/run` 能返回新结构。

### 2026-05-02 对话 25：加入板块资金异动和龙头跟随选股逻辑

- 用户强调板块的重要性：当某板块大批资金流入并把龙头股拉到涨停时，应快速识别跟涨次龙头；当次龙头出现大批资金入场时，可作为模拟买入候选。
- 已把智能选股升级为 `sector-news-leader-v3`，新增两个独立因子：
  - `sector_momentum`：板块资金异动分，结合板块主力净流入、最近两次快照的主力净流入增量、板块涨跌和主力占比。
  - `leader_follow`：龙头跟随分，识别板块龙头接近涨停、候选股是否为板块涨幅前列/次龙头、是否有量比/换手/成交额确认。
- `backend/app/services/sector_service.py` 的板块资金快照新增每个板块的 `sectors` 明细，并提供 `get_sector_flow_momentum()` 计算最近两次快照的资金增量；首次快照没有上一帧时增量为 0，避免启动时误判资金加速。
- `backend/app/services/data_fetcher.py` 的板块成分股详情新增换手率 `turnover_rate` 和量比 `volume_ratio` 字段，供次龙头确认使用。
- `backend/app/services/stock_screener.py` 的策略权重已重排：
  - 短线猎人：更重视量价、资金、板块资金异动。
  - 长线观察：更重视资格、估值财务、技术趋势，弱化秒级板块跟随。
  - 事件驱动：最高权重给板块资金异动，其次是板块共振、新闻、资金和龙头跟随。
- `backend/static/index.html` 的策略中心新增当前策略因子占比；智能选股页新增“板块异动”“龙头跟随”分项；板块页展示资金加速板块与资金增量，并在板块页打开时每 8 秒刷新一次板块资金快照。
- `/api/v1/quant/screening/run` 支持接收 `strategy`，前端运行选股时会传当前策略，使后端因子权重与前端策略一致。
- 已完成 `preview_server.py` 语法检查、后端 `compileall app`、前端内联脚本解析；用 FastAPI TestClient 验证板块刷新、三种策略选股、`sector_momentum` 与 `leader_follow` 返回正常。

### 2026-05-02 对话 26：短线选股改为震荡支撑低吸优先

- 用户进一步明确短线侧重点：尽量选取嘉美包装、二六三这类震荡股票，等跌到支撑位附近买入，而不是默认追最强题材或高位龙头。
- 已新增 `support_pullback` 因子，作为短线策略最高权重因子，识别 20 日箱体震荡、MA20 斜率平缓、当前价格贴近箱体支撑、近 5 日回调但未破位、当日未追高、换手适中等条件。
- 短线权重已调整为低吸优先：`support_pullback` 22%、资金 16%、量价 14%、技术 11%、板块 9%、板块异动 8%、龙头跟随 3%、新闻 5%、短线形态 6%、资格 6%、估值财务 5%。
- 长线和事件驱动也保留 `support_pullback`，但权重低于短线；事件驱动仍偏事件/板块，长线仍偏资格/财务/趋势。
- 前端策略中心和智能选股页已展示“支撑低吸”因子、箱体宽度、距离支撑比例等说明。
- 选股时若候选池规模不大，会尝试拉取真实日K以判断支撑低吸；当前环境访问东方财富历史 K 线接口被代理断开，验证中 `002969` 嘉美包装与 `002467` 二六三日K返回 `None`，系统会按中性/待确认处理，不用估算K线伪造支撑结论。
- 已完成后端 `compileall app`、前端内联脚本解析，并验证 `/api/v1/quant/screening/run` 返回 `support-pullback-sector-v4` 与 `support_pullback` 分项。

### 2026-05-02 对话 27：短线改为先支撑形态入池再池内选优

- 用户确认短线流程应先找到一批类似嘉美包装、二六三的低位支撑形态股票，再在这批票里按剩余因子权重筛优。
- 已将短线选股升级为两段式 `support-pool-quality-v5`：
  1. 先按 `support_pullback` 判断是否进入支撑形态池：`support_pool`、`near_support_watch`、`support_pending_data`、`support_rejected`、`support_unmatched`。
  2. 若存在严格支撑池，优先只在严格池和近支撑观察池中排序；若真实K线不可用但存在待确认池，则降级只在待确认池内排序；若完全没有支撑候选，才回退到全量综合排序。
  3. 池内排序使用 `quality_score`，排除 `support_pullback` 后按资金、量价、技术、板块、新闻、盘口等剩余权重归一化选优。
- 单个选股结果新增 `support_pool_status`、`support_pool_mode`、`quality_score`，`screening_logic` 中也保留对应字段，前端智能选股页展示“支撑池/待K线确认/未入池”等状态。
- 已完成后端 `compileall app`、前端内联脚本解析，并用 TestClient 验证短线选股返回 `support-pool-quality-v5`、`support_pool_status` 和 `quality_score`。

### 2026-05-02 对话 28：复查智能选股 BUG 并统一策略权重

- 用户要求重新遍历代码，检查智能选股是否存在 BUG、错误或不合理之处，并优化后总结各策略选股逻辑。
- 已修复三套策略权重总和不为 100% 的问题：短线、长线、事件驱动、默认权重均重新归一到 `1.0`，避免综合分虚高或跨策略不可比。
- 已修复行情字段类型隐患：硬过滤、量价评分、风险等级、推荐理由里的 `price`、`volume`、`pct_change`、`volume_ratio`、`turnover_rate`、`amount` 均先转为数值，避免外部数据源返回字符串时比较报错。
- 已修复板块热点排序口径：`get_sector_rankings()` 不再按主力净流入绝对值排序，避免大额流出板块被误排成热点；现在按净流入、净流入增量、涨跌幅和新闻影响正向排序。
- 已修复手动选股冷启动问题：当后台股票宇宙尚未初始化完成时，`/api/v1/quant/screening/run` 会先写入本地演示股票池，避免接口立即返回 0 条。
- 已优化短线信号口径：短线结果进入支撑池后，`signal_type` 与 `risk_level` 改按池内 `quality_score` 和 `support_pool_mode` 重新判断；`support_pending_data` 不再因为总分被误标为买入候选。
- 已同步前端策略中心与智能选股页权重显示，并修复 `activeStrategy().holding` 字段不存在导致当前策略说明为空的问题。
- 已完成 `preview_server.py` 语法检查、后端 `compileall app`、前端内联脚本解析、权重求和测试、字符串数值字段测试，以及 FastAPI TestClient 选股接口验证；当前环境访问东方财富历史 K 线仍会被代理断开，系统会返回 `support_pending_data` 或缺失状态，不伪造支撑结论。

### 2026-05-02 对话 24：公网访问与自定义域名准备

- 用户要求开始制作内网穿透，让外部用户无需同一局域网即可访问，并将网址改为 `www.lianghuagongju222333.com`。
- 已新增 `deploy/public_access.md`，明确 Cloudflare Tunnel 推荐方案、首次配置步骤、日常启动方式、临时测试方式和公网安全边界。
- 已新增 `deploy/cloudflared/config.yml.example`，把 `www.lianghuagongju222333.com` 映射到本机 `http://localhost:8000`。
- 已新增 `启动公网访问.bat`，用于日常启动本地 H5 后端并运行名为 `lianghua-h5` 的 Cloudflare Tunnel。
- 已更新 `.gitignore`，避免提交 Cloudflare 隧道凭证、证书和本地穿透敏感文件。
- 当前无法替用户完成域名注册、DNS 托管或 Cloudflare 登录；正式域名生效前，必须先拥有 `lianghuagongju222333.com` 并把 DNS 接入 Cloudflare。

### 2026-05-02 对话 24：新增临时公网访问脚本

- 用户询问是否可以暂时不注册域名，只先让外地朋友访问。
- 已新增 `启动临时公网访问.bat`，基于 `cloudflared tunnel --url http://localhost:8000` 创建临时 `trycloudflare.com` 公网地址。
- 已更新 `deploy/public_access.md`，补充无需域名的临时访问流程。
- 临时地址每次启动可能变化，关闭窗口后失效；适合短期测试，不适合长期固定访问。
- 用户运行脚本后出现 Windows CMD 中文编码乱码和 `cloudflared` 查找异常；已将 `启动临时公网访问.bat` 改为纯英文输出、自动切换到项目目录，并自动查找 Downloads、Desktop、`C:\cloudflared` 和项目根目录中的 `cloudflared.exe`。
### 2026-05-02 对话 29：E盘市场数据仓库与全市场缓存预热

- 用户指出当前节假日/闭市，要求先获取所有股票历史数据并长期缓存，后续更新也保留到缓存，缓存放在 E 盘，网站打开时优先拿到准确的 K线、分时线、筹码、量比、换手率、成交量等重要信息。
- 已将 `backend/app/services/data_fetcher.py` 的市场缓存根目录改为默认 `E:\lianghua_market_cache`，并支持 `LIANGHUA_MARKET_CACHE_DIR` 环境变量覆盖。
- 已新增缓存分区：`kline`、`intraday`、`realtime`、`money_flow`、`chips`、`universe`；K线继续 CSV 落盘，分时 CSV 按日期落盘，实时行情/资金流/筹码/股票池用 JSON 保存。
- 实时行情已缓存量比、换手率、成交量、成交额、开高低收等字段；K线缓存保存成交量、成交额、振幅、涨跌幅、换手率；筹码缓存由真实日K和成交量推导后落盘。
- 筹码分布已关闭估算 K 线 fallback，只允许基于真实日 K 或本地 K 线缓存推导，避免缺数据时生成伪筹码。
- 分时、K线、实时行情、资金流、筹码在外部数据源失败或闭市不可用时会优先读取本地缓存，并将 `source` 标记为 `cache_file`，避免回到估算数据。
- 已新增接口：`GET /api/v1/market/cache/status` 查看 E 盘缓存仓库状态；`POST /api/v1/market/cache/warmup` 在后台预热市场缓存，支持 limit/offset/days/periods 以及是否拉取实时、分时、资金流、筹码。
- 已在 E 盘创建 `E:\lianghua_market_cache` 及子目录。
- 已完成 `preview_server.py` 语法检查、后端 `compileall backend\app`，并用 FastAPI TestClient 验证缓存状态接口返回 `E:\lianghua_market_cache`。

### 2026-05-02 对话 30：多源校验行情缓存与2秒实盘刷新

- 用户要求历史数据优先读取缓存，东方财富、同花顺等多平台一起验证；实时数据每 2 秒刷新并验证后写入缓存；每天 15:00 闭市后做最终校验并缓存准确数据。
- 已在 `backend/app/services/data_fetcher.py` 增加实时行情多源校验：东方财富为主源，同时接入新浪和同花顺官网快照做交叉比对；至少两个来源价格/成交量/成交额在容差内一致时，正式写入 `E:\lianghua_market_cache\realtime`。
- 实时校验报告落盘到 `E:\lianghua_market_cache\validation\realtime\YYYYMMDD\{code}.json`，记录来源、校验状态、冲突字段和接受源；冲突或单源数据只作为候选/待校验，不覆盖正式可信缓存。
- K线读取改为普通业务默认优先读 E 盘缓存；只有预热或闭市校验任务才会强制外部刷新。日 K 最新一根会用新浪/同花顺实时快照辅助校验，并把校验状态写入 K线数据和 validation 报告。
- 已修复 `fetch_realtime_batch([])` 空列表误读筹码缓存的问题。
- `backend/app/main_simple.py` 新增实时观察池：打开个股详情、快照或批量快照时会加入观察池，后台默认每 2 秒调用多源校验刷新；`GET /api/v1/market/cache/status` 会返回实时刷新状态、观察股票和闭市校验状态。
- 新增 `POST /api/v1/market/realtime/watch` 手动加入 2 秒实时校验列表；新增 `POST /api/v1/market/post-close/validate` 手动启动闭市后全市场校验；后台调度会在交易日 15:05 自动触发一次闭市全市场校验缓存。
- 前端 `backend/static/index.html` 个股详情新增 2 秒实时快照轮询，只更新实时价格、涨跌幅、成交额和校验来源提示，不反复重跑评分/回测。
- 已完成后端 `compileall backend\app`、前端内联脚本语法检查；用 `600519` 实测新浪与同花顺一致后返回 `validation_status=verified`，东方财富当前连接仍可能被代理断开，但系统会记录来源缺失并使用其他已验证来源。

### 2026-05-02 对话 31：首页与分组导航、全功能联通复查

- 用户反馈左侧板块过多，要求确定一个首页，并把同类型功能合并到总板块下，点击总板块展开子板块，再点击子板块进入页面。
- 已将 `backend/static/index.html` 的左侧导航改为分组结构：`首页`、`行情投研`、`策略交易`、`消息风控`、`系统配置`、`后续建设`；原有 15 个功能页均保留为子板块。
- 已确定 `总览` 为首页，并新增三个首页快捷入口：行情投研、策略交易、消息风控，方便从首页进入主要工作流。
- 已修复当前运行的 8000 端口服务仍是旧代码的问题：停止旧 `python` 预览进程并重新启动 `preview_server.py`，确认最新 AI 模型接口和导航页面已由 `http://localhost:8000` 提供。
- 已完成前端内联脚本语法检查，确认 `openStock`、`amount`、`drawStockCharts`、`switchSection`、`initNav`、`toggleNavGroup` 均只有一个实现，避免重复覆盖。
- 已完成后端 `preview_server.py` 语法检查与 `backend/app` 编译检查。
- 已通过 FastAPI TestClient 和真实 `localhost:8000` HTTP 烟测验证：首页、健康检查、股票列表/搜索/详情、分时、K线、筹码、板块、选股、信号、新闻、风控、持仓、评分卡、结构化决策、风控复核、回测、Agent 工作台、AI 配置和熔断状态接口均可返回。
- 当前可用性限制：本机网络到东方财富 K线/分时/资金流接口仍可能被代理断开；系统会优先读 `E:\lianghua_market_cache`，没有缓存时返回 `unavailable` 并明确提示，不再展示估算 K线或估算分时。
- 当前 AI 模型接口配置中心可用，但尚未配置 API Key，因此处于 `not_configured`；后续 AI 深度解读、模型交叉验证和自动调用需要用户在页面配置供应商、Base URL 与密钥。

### 2026-05-02 对话 32：中文化、导航折叠、新闻与行情交互优化

- 用户提出 15 项前端与功能联动优化：去英文、首页单项不展开、策略文案、因子解释、新闻板块重排、搜索修复、行情分栏、板块左右独立滚动、研究/回测按名称联想、选股策略切换、信号实时建议、持仓实操盘/模拟盘分栏、智能体中文化、预留清单。
- 已修改 `backend/static/index.html`：
  - 菜单栏和主要页面文案改为中文；`Agent` 显示为“智能体”，`AI模型` 显示为“智能模型”，风控参数键名做中文映射。
  - 首页作为单独入口，不再展开子菜单；进入任一子页面后只展开当前所属总板块，其他总板块自动合并。
  - 短线猎人显示文案改为“先震荡回落到支撑位的股票，不追已大幅拉升的板块高位股。”
  - 策略中心“当前因子占比”每个因子新增小字解释，说明资格、估值财务、量价、资金、技术、支撑低吸、板块、新闻等具体含义。
  - 修复顶部搜索：输入联想按名称/代码前缀优先排序；若输入框里是“名称 + 代码”，会先提取 6 位代码再打开详情。
  - 个股研究和回测实验室支持输入股票名称或代码，并提供同顶部搜索一样的单字联想。
  - 行情页新增分栏：全部A股、上证A股、深圳A股、北证A股、创业板、全球；A股按成交额优先显示热门股，全球页先作为指数与美股涨跌板块预留展示。
  - 板块页左侧板块列表和右侧板块详情改为独立滚动区域，避免滚到底部后看不到右侧详情。
  - 新闻页左侧改为“两日重要新闻”，右侧为“两日最新时间流”，新闻可点击查看详情。
  - 选股页顶部新增当前策略下拉框，可直接切换策略。
  - 信号页新增“选股与自选实时建议”，对选股候选和自选股给出建议购买时间、建议挂单金额、上涨/下跌概率。
  - 持仓页顶部拆成“实操盘”和“模拟盘”，实操盘仅预留接口说明，模拟盘继续展示当前模拟交易数据。
  - 预留页改为按 1、2、3 方式列出未完成能力清单，同时保留盘口结构分析入口。
- 已修改后端：
  - `GET /api/v1/quant/news` 支持 `limit` 参数，默认最多返回 500 条，避免前端只能看到 50 条。
  - 新闻刷新接口返回前 500 条。
  - `backend/app/services/sector_service.py` 新增板块利好/利空新闻归档，正负面板块新闻会进入对应板块 `news_timeline`，服务运行期内保留约 31 天，供板块详情时间线展示。
- 已完成前端内联脚本语法检查、`preview_server.py` 语法检查、后端 `compileall backend/app` 编译检查，并重启 `localhost:8000` 预览服务。
- 已用本地 HTTP 验证：首页、新闻、板块、智能体、智能模型接口均返回 200；中文搜索通过浏览器同等 UTF-8 请求可返回 `600519 贵州茅台`。

### 2026-05-02 对话 33：个股详情与板块详情加载缓存优化

- 用户反馈个股详情加载慢且字段为空、顶部搜索缺少清空按钮、所有搜索栏不应有默认字/数字、板块详情加载慢且失败率高，希望把确定性数据放入缓存。
- 已修改 `backend/static/index.html`：
  - 顶部股票搜索栏新增“×”清空按钮，点击后会清空输入、关闭联想并聚焦回搜索框。
  - 顶部搜索、个股研究、回测实验室、盘口分析等搜索输入默认留空，不再预填股票代码或提示文本。
  - 个股详情改为两段式加载：先并行加载行情、分时、K线并立即渲染；评分卡、结构化建议、风控复核、回测报告改为后台补充，补完后自动刷新详情弹窗。
  - 前端新增个股详情缓存和板块详情缓存，同一只股票或同一板块再次打开时优先秒开缓存结果。
- 已修改 `backend/app/main_simple.py`：
  - 个股详情接口优先使用 E 盘实时行情缓存、内存行情缓存、股票池缓存和本地 K线缓存，首屏不再阻塞等待外部资金流接口。
  - 当股票池中已有价格、涨跌幅、成交量、成交额等确定字段时，会先作为 `stock_universe_cache` 返回，减少空字段和外部接口等待。
  - 个股详情接口保留短时内存缓存，连续打开同一股票会返回 `cache_hit`。
- 已修改 `backend/app/services/sector_service.py`：
  - 新增板块本地落盘缓存目录 `backend/data/sector_cache`，成功获取的板块列表、板块资金流、板块成分股会写入 JSON 缓存。
  - 板块刷新失败时会回退到本地缓存；板块详情再次打开时优先返回内存/落盘缓存，避免每次点击都等待外部板块成分股接口。
  - 板块概览保留短时缓存，降低频繁切换页面时的重复聚合计算。
- 已完成前端内联脚本语法检查、`preview_server.py` 语法检查、后端 `compileall backend/app` 编译检查。
- 已用 FastAPI TestClient 验证：`/api/v1/stocks/600519/detail` 连续请求第二次返回缓存命中；`/api/v1/sectors` 返回 200 个板块；`/api/v1/sectors/BK0963` 连续请求第二次返回缓存命中且包含 50 只成分股。

### 2026-05-02 对话 34：板块时间线、资金流多线图与连续流入统计

- 用户补充两张参考图，要求板块详情时间线按日期节点展示，利好/利空/重大利好/重大利空使用不同浅色或深色；板块资金流图改成盘中曲线样式，并继续扩展资金流统计。
- 已修改 `backend/static/index.html`：
  - 板块详情“主要新闻”和“时间线”合并为“板块新闻时间线”，按日期分组展示，保留竖线和节点，不使用参考图中的火焰图标和蓝色话题标签。
  - 时间线颜色规则：轻微利好为浅红，轻微利空为浅绿，重大利好为红色，重大利空为绿色，其他为灰色。
  - 修复板块详情自动刷新导致右侧滚动条回到顶部的问题；定时刷新和全局刷新时会保留左侧板块列表与右侧详情滚动位置。
  - 行情分栏修正为“深证A股”，并放宽上证/深证/北证/创业板过滤规则；创业板页同时包含创业板与科创板，北证页在股票池为空时提供北证50代表股票兜底。
  - 板块资金流图改为展示最新主力净流入前三和净流出前三共 6 个板块，每个板块一条不同颜色折线，并在图上标注板块名称和净流入/流出金额。
  - 板块页新增“连续资金流入超过3天的板块”统计表，只展示连续流入 4 天及以上的板块。
- 已修改 `backend/app/services/sector_service.py`：
  - 板块资金流快照新增日期字段，便于前端只展示当日曲线；非交易日没有新快照时展示最近一次交易日快照。
  - 新增 `sector_daily_flow_history` 落盘缓存，按日期记录每个板块当日最新主力净流入，用于计算连续流入天数。
  - `/api/v1/sectors` 返回 `consecutive_inflow_sectors`，包含连续天数和连续期间累计净流入；缓存天数不足时返回空列表。
  - 放宽新闻利好/利空识别词库与打标口径，只有无板块、无价格/政策/订单/监管含义的消息才保持中性。
- 已完成前端内联脚本语法检查、`preview_server.py` 语法检查、后端 `compileall backend/app` 编译检查。
- 已用 FastAPI TestClient 验证 `/api/v1/sectors` 返回 200 个板块、资金流快照和连续流入字段；当前本地历史缓存只有当天数据，所以连续流入超过3天列表暂为空，后续连续运行多个交易日后会自动出现。

### 2026-05-02 对话 35：取消板块资金图与连续流入统计

- 用户决定取消“板块资金流入图”和“连续资金流入统计”。
- 已从 `backend/static/index.html` 板块页移除资金流入图展示和连续资金流入统计表，仅保留板块概览、板块列表、板块详情、资金分拆、龙头/热门股和板块新闻时间线。
- 已从 `backend/app/services/sector_service.py` 移除连续流入统计的写入、计算和接口返回字段；`/api/v1/sectors` 不再返回 `consecutive_inflow_sectors`。
- 已完成前端内联脚本语法检查、`preview_server.py` 语法检查、后端 `compileall backend/app` 编译检查，并用 FastAPI TestClient 验证 `/api/v1/sectors` 返回正常且不再包含连续流入字段。

### 2026-05-02 对话 36：新闻页重要消息口径修正

- 用户指出“消息风控-新闻”左侧重要新闻不应出现大量中性消息，必须只展示对 A股整体或具体板块有利好/利空影响的重大消息；要求标题改为“重要消息”，利好红色、利空蓝色；重要消息保留一个月，两日内可点开详情，两日后的旧消息只保留摘要不可点击。
- 已修改 `backend/app/main_simple.py`：`/api/v1/quant/news` 和 `/api/v1/quant/news/refresh` 返回新闻前，会调用板块新闻分类逻辑补充 `sentiment`、`impact_score`、`sector_tags` 等字段。
- 已扩展 `backend/app/services/sector_service.py` 新闻打标词库：补充美联储、特朗普、伊朗、霍尔木兹、稀土涨价、电算协同、算力、电力等宏观和板块关键词；普通天气/无市场影响消息仍保持中性。
- 已修改 `backend/static/index.html`：
  - 左侧标题由“两日重要新闻”改为“重要消息”。
  - 左侧重要消息范围扩展到 31 天，只保留 `positive/negative` 且与 A股整体或板块相关的消息，中性消息不进入左侧。
  - 两日内的重要消息可点击查看详情；两日后的消息标注为摘要保留，不绑定详情弹窗。
  - 新闻页利好用红色，利空用蓝色；最新时间流仍保留两日内普通新闻详情。
- 已完成前端内联脚本语法检查、`preview_server.py` 语法检查、后端 `compileall backend/app` 编译检查。
- 已重启 `http://localhost:8000` 预览服务，并验证新闻刷新接口返回 200；样例验证中，特朗普/伊朗/霍尔木兹被识别为负面，降息预期、稀土涨价、电算协同被识别为正面，普通天气保持中性。

### 2026-05-02 对话 37：修复实时行情分栏股票池不完整

- 用户反馈“实时行情”仍未正确分好类。
- 排查发现后端股票池缓存只返回 720 只，且只有北交所和上交所，深交所股票缺失；前端还只拉取前 300 只，并且顶部搜索会把完整股票池覆盖为搜索结果。
- 已新增 `backend/app/services/data_fetcher.py::fetch_all_stocks_eastmoney()`，通过东方财富补充沪深京 A 股股票池，包含代码、名称、交易所、市场、价格、涨跌幅、成交量、成交额。
- 已在 `backend/app/main_simple.py` 增加股票池规范化和完整性检查：发现股票池少于 3000 只或缺沪/深/京任一市场时，会自动重新拉取全市场并按代码修正 `exchange` 与 `market`。
- 已修正 `920xxx` 北交所代码被误判为上交所的问题；`688/689` 为科创板，`300/301` 为创业板。
- 已修改 `backend/static/index.html`：实时行情启动时拉取最多 10000 只股票；顶部搜索结果不再覆盖完整股票池，而是单独存在 `marketSearchRows`，切换分栏或点击恢复后回到完整行情。
- 已完成前端内联脚本语法检查、后端 `compileall backend/app` 编译检查，并重启 `http://localhost:8000`。
- 已验证 `/api/v1/stocks?limit=10000&offset=0` 返回 5511 只，其中上交所 2311 只、深交所 2889 只、北交所 311 只；创业板/科创板按代码可分出 2004 只。

### 2026-05-02 对话 38：实时行情三源多数决与1秒刷新

- 用户强调数据是软件底层核心：同花顺、东方财富、新浪财经三平台拉取所有股票数据，三合一核对；确认的历史数据进入缓存；交易日实时数据每 1 秒刷新，三源核对后取多数正确数据。
- 已修改 `backend/app/services/data_fetcher.py`：
  - 实时行情校验从“东方财富主源 + 其他源对比”升级为“三源多数决”。
  - 东方财富、新浪财经、同花顺任意两家在价格、成交量、成交额容差内一致，即标记 `verified` 并写入正式实时缓存。
  - 第三家不一致时会写入 `rejected_sources` 和 validation 报告，不参与正式缓存。
  - 三家互相冲突时标记 `conflict`，只写候选缓存，不污染正式可信缓存。
  - 实时结果增加 `accepted_sources`、`rejected_sources`、`validation_checked_at` 等字段。
- 已修改 `backend/app/main_simple.py`：
  - 后台实时观察池默认刷新间隔从 2 秒改为 1 秒。
  - `/api/v1/market/realtime/watch` 默认 `interval_seconds=1`，并支持 `all_market=true` 将全市场股票加入观察池。
- 已修改 `backend/static/index.html`：个股详情实时轮询从 2 秒改为 1 秒，请求实时观察池时也传入 1 秒间隔。
- 已完成前端内联脚本语法检查、`preview_server.py` 语法检查、后端 `compileall backend/app` 编译检查。
- 已用样例验证三源多数决：东方财富和新浪一致、同花顺异常时，接受东方财富+新浪并拒绝同花顺；三家互相冲突时返回 `conflict` 且不验证。
- 已重启 `http://localhost:8000`，并验证 `/api/v1/market/realtime/watch` 可设置 1 秒刷新，缓存状态显示实时刷新线程运行中。
- 注意：当前已具备“三源实时多数决”和“确认后写正式实时缓存”。历史 K线目前仍以东方财富历史接口为主，并用新浪/同花顺实时快照校验最新交易日；若要做到每一根历史K线都三平台逐条核对，需要继续接入可稳定批量返回历史K线的同花顺/新浪历史接口或授权数据源。

### 2026-05-02 对话 39：股票主数据监控

- 用户补充要求：新股上市、股票退市、更名、停牌、ST 等股票主数据必须第一时间更新。
- 已修改 `backend/app/services/data_fetcher.py`：
  - 股票池缓存写入时会对比上一版股票池，生成 `E:\lianghua_market_cache\universe\changes.json`。
  - 变更类型包括：`new_listed` 新股、`removed_or_delisted` 退市或消失、`name_changed` 更名、`st_changed` ST状态变化、`suspension_changed` 停复牌变化。
  - 东方财富股票池采集新增 `is_suspended` 与 `trade_status` 字段；新浪股票池也补充停牌兜底字段。
  - 新增读取股票池元信息和变更日志的方法。
- 已修改 `backend/app/main_simple.py`：
  - 新增股票主数据后台监控线程 `_stock_universe_monitor_loop`。
  - 交易时段每 60 秒刷新一次股票主数据；非交易时段每 600 秒刷新一次。
  - 若发现新股/退市/更名/ST/停复牌变化，会记录到数据 Agent 日志。
  - `/api/v1/market/cache/status` 新增 `stock_universe` 状态，显示最近刷新时间、股票总数和变更摘要。
  - 新增 `GET /api/v1/stocks/universe/changes`，用于查看最近一次股票主数据变化明细。
  - `POST /api/v1/stocks/sync` 强制刷新股票池后会返回变更摘要。
- 前端首页已新增股票主数据监控卡片，显示股票总数、最近更新时间、新股/退市、更名/ST、停复牌变化数量。
- 已完成前端内联脚本语法检查、后端 `compileall backend/app` 编译检查，并重启 `http://localhost:8000`。
- 已验证主数据监控线程可运行，当前股票池 5511 只；由于当前刷新前后股票池一致，最近一次变更摘要均为 0。

### 2026-05-02 对话 40：历史K线可信缓存层

- 用户要求继续补齐“历史K线逐条三平台校验”：历史K线不再只以东方财富历史接口为主，正式缓存只允许三源一致或至少双源一致的数据写入。
- 已修改 `backend/app/services/data_fetcher.py`：
  - 新增东方财富历史K线、 Sina 历史日K、同花顺最新交易日日K三类采样入口。
  - 新增历史K线逐日多数决校验：按交易日逐条比较开盘价、收盘价、最高价、最低价；任意两源在容差内一致即生成 `verified_kline`。
  - 正式 K线缓存 `E:\lianghua_market_cache\kline\period_101\{code}.csv` 只写入 `validation_status=verified` 的日K。
  - 单源样本或三源冲突样本不写正式缓存，只写入 `E:\lianghua_market_cache\kline\candidates\period_101\{date}\{code}.csv` 与 validation 报告，避免污染回测底座。
  - validation 报告新增 `source_counts`、`source_coverage`、`trusted_rows`、`candidate_rows`、`single_source_rows`、`conflict_rows` 等字段。
  - `fetch_daily_bars()` 已接入同一套可信日K入口，技术指标、回测、筹码分布会复用可信缓存。
  - 修正 `920xxx` 北交所代码在 `_get_secid()` 与 `_sina_symbol()` 中的交易所识别。
- 已修改 `backend/app/main_simple.py`：
  - `/api/v1/stocks/{code}/kline` 返回 `validation` 与 `validation_report`，当前只返回通过至少双源一致校验的正式日K；未通过的样本会提示已进入候选缓存和校验报告。
  - 修复 K线 CSV 缓存读回后空值 `NaN` 导致 FastAPI JSON 序列化失败的问题，K线接口出参会先转为 JSON 安全值。
- 已完成 `preview_server.py` 语法检查和后端 `compileall backend/app` 编译检查。
- 已用 `600519`、`000001`、`300750`、`688981` 做真实接口验证：当前环境东方财富历史接口被代理断开，Sina 历史日K可用，同花顺最新日日K可用；因此最新交易日可由 Sina+同花顺双源验证写入正式缓存，其余历史行因只有 Sina 单源而进入候选缓存。后续若要做到完整历史三平台逐条覆盖，仍需接入稳定可批量返回历史日K的同花顺授权数据源或第三方授权行情源。

### 2026-05-02 对话 41：修复板块页空数据

- 用户反馈行情内“板块”页面显示“暂无板块数据，点击刷新板块资金流”。
- 排查发现 `/api/v1/sectors` 返回了空板块概览，并且空结果被短 TTL 缓存；原因是东方财富板块接口当前返回空列表但没有抛异常，原逻辑只在异常时读取本地板块缓存。
- 已修改 `backend/app/services/sector_service.py`：
  - 新增 `_load_cached_sector_data()`，统一从 `backend/data/sector_cache/sector_list.json` 与 `sector_money_flow.json` 恢复板块列表和资金流。
  - `refresh_sector_data()` 在外部接口返回空列表时，会自动回退本地板块缓存；外部板块有数据但资金流为空时，也会回退本地资金流缓存。
  - `get_sector_rankings()` 在内存状态为空时优先加载本地缓存。
  - `get_sector_overview()` 不再缓存空板块概览，避免前端持续看到空状态。
- 已完成后端 `compileall backend/app` 与 `preview_server.py` 语法检查，并重启预览服务。
- 已验证 `/api/v1/sectors` 返回 200 个板块，健康检查接口返回 200。

### 2026-05-02 对话 42：新闻风控时间排序与红绿深浅

- 用户要求消息风控里的新闻从上到下按时间顺序排列，最新新闻在最上面；颜色使用红绿色，并用不同深浅展示重要程度。
- 已修改 `backend/static/index.html`：
  - “重要消息”不再按重要分数优先排序，改为按发布时间倒序排列，最新在最上。
  - “最新时间流”同样先补充情绪/板块/重要度推断，再按发布时间倒序排列。
  - 新增 `enrichNewsList()`、`sortNewsByTimeDesc()`、`newsLevelClass()`、`newsToneClass()`，统一处理新闻增强、排序和颜色等级。
  - 利好使用红色系，利空使用绿色系；按重要度分为浅色、中色、深色三档。
  - 最新时间流也显示利好/利空/中性标签和关联板块，不再只是普通白色卡片。
- 已完成前端内联脚本语法检查、`preview_server.py` 语法检查、后端 `compileall backend/app`，并重启预览服务；健康检查返回 200。

### 2026-05-02 对话 43：两周新闻池与板块新闻归档标记

- 用户要求消息风控的重要消息收集两周内新闻，两日内可打开详情，两日后只保留摘要；每次获取到的新闻都进入缓存，超过两周自动删除；重要消息权重门槛上升，避免消息过多。
- 用户追加要求：板块内利好/利空消息留存一个月；分到对应板块内的消息缓存期一个月；重大和特重大利好/利空缓存两个月；板块内消息可手动标记为重大或特重大。
- 已修改 `backend/app/services/news_service.py`：
  - 新增本地新闻归档 `backend/data/news_cache/news_archive.json`。
  - 每次刷新新闻会与本地归档合并去重，并只保留最近 14 天。
  - 服务重启后 `/api/v1/quant/news` 会先从本地归档恢复新闻池。
  - 新闻接口元信息新增 `archive_retention_days`、`archive_count`、`archive_path` 等字段。
- 已修改 `backend/static/index.html`：
  - 重要消息窗口从 31 天改为 14 天。
  - 重要消息入选阈值从 3 提高到 5，减少两周缓存变大后的噪音。
  - 页面说明改为“两周重要消息，两日内可点开详情，两日后只保留摘要”。
- 已修改 `backend/app/services/sector_service.py`：
  - 新增板块新闻归档落盘 `backend/data/sector_cache/sector_news_archive.json`。
  - 普通板块利好/利空保留 31 天；`major`/`super_major` 重大或特重大消息保留 62 天。
  - 板块详情时间线会合并实时归因消息和归档消息。
  - 新增 `mark_sector_news()`，支持手动标记 `normal`、`major`、`super_major`，并可同步修正利好/利空方向。
- 已修改 `backend/app/main_simple.py`：
  - `/api/v1/quant/news` 接入新闻归档加载。
  - 新增 `POST /api/v1/sectors/{code}/news/mark`，用于板块新闻手动标记重大/特重大。
- 已完成后端 `compileall backend/app`、前端内联脚本语法检查、`preview_server.py` 语法检查。
- 已验证新闻刷新接口可获取并归档 149 条新闻，`/api/v1/quant/news` 可从两周归档池返回；已重启预览服务，健康检查返回 200。

### 2026-05-02 对话 44：修复板块新闻手动标记与小按钮交互

- 用户反馈板块新闻时间线中部分新闻手动标记会显示“未找到这条板块新闻”，并要求把标记控件移动到右侧改成小按钮，点击后可选择利好/利空，再按选择渲染红色/绿色和深浅程度。
- 已修复 `backend/app/services/sector_service.py`：板块新闻标记不再只按标题匹配，改为优先使用 `fingerprint/dedupe_key` 稳定 key，标题仅作为 fallback。
- 若新闻尚未进入板块归档，`mark_sector_news()` 会从当前板块新闻映射中查找并补写归档，再执行手动标记，避免首次标记中性或新新闻时报“未找到”。
- 已修改 `backend/app/main_simple.py` 的 `POST /api/v1/sectors/{code}/news/mark`，支持前端传入 `news_key`，Agent 日志也会记录该 key。
- 已修改 `backend/static/index.html`：板块时间线每条新闻右侧新增小型“标记”下拉控件，可选择“利好 / 重大利好 / 特重大利好 / 利空 / 重大利空 / 特重大利空”。
- 板块时间线颜色规则已同步：利好为红色系，利空为绿色系；普通为浅色，重大为较深色，特重大为最深色并带左侧强调线。
- 已完成后端 `compileall backend\app`、`preview_server.py` 语法检查、前端内联脚本解析检查，并用 FastAPI TestClient 验证随机板块新闻通过 `news_key` 标记为重大利好返回 `ok: True`。

### 2026-05-02 对话 45：修复智能模型配置自动跳回官方与接口地址无法清空

- 用户反馈“智能模型”配置页切换到其他模型/供应商后会自动跳回官方模型，并且接口地址删不掉；用户希望接口地址可以留空。
- 已修改 `backend/static/index.html`：AI 配置页默认供应商改为“OpenAI 兼容网关”，不再在渲染时把官方默认接口地址自动写入输入框。
- 供应商下拉切换后会保存当前供应商，避免 15 秒全局刷新重新读取旧配置后跳回官方；接口地址输入框失焦时会保存当前值，空字符串也会被保留。
- 新增“保存连接”按钮，用于只保存供应商、接口地址和密钥，不强制检测模型。
- 已修改 `backend/app/services/ai_model_service.py`：新增 `update_connection_config()`，支持保存空接口地址；模型检测时若用户留空地址，可临时使用供应商默认地址检测，但保存配置时仍保留用户输入的空地址。
- 已修改 `backend/app/main_simple.py`：新增 `POST /api/v1/ai/config`，用于保存 AI 连接配置。
- 已完成后端 `compileall backend\app`、`preview_server.py` 语法检查、前端内联脚本解析检查，并用 FastAPI TestClient 验证保存为 `openai_compatible` 且 `base_url=""` 后，再读取配置仍保持不变。

### 2026-05-03 对话 46：修复 AI 接口地址粘贴后被自动覆盖

- 用户反馈在“智能模型”配置页粘贴 URL 后，输入框内容会自动消失。
- 排查原因：接口地址输入框失焦保存后会立即重绘 AI 页面；如果保存请求与全局刷新交错，旧配置会覆盖用户刚粘贴的内容。
- 已修改 `backend/static/index.html`：`saveAIConnectionConfig(false)` 不再自动重绘页面，先把当前输入框的供应商与接口地址写入本地 `state.ai.config`，避免 UI 被旧状态覆盖。
- `render()` 与 `refreshAIConfig()` 在用户正在编辑 `aiProvider`、`aiBaseUrl`、`aiApiKey` 时不会重绘 AI 表单；刷新配置时会保留当前输入框里的内容。
- `aiBaseUrl` 新增 `oninput/onpaste` 本地状态同步，粘贴后即使后台刷新也不会把输入值清空。
- 已完成前端内联脚本解析、后端 `compileall backend\app`、`preview_server.py` 语法检查；并用 FastAPI TestClient 验证带路径 URL 可保存和读回。测试用假地址已清回空，避免污染本地配置。

### 2026-05-03 对话 47：修复 AI 模型选择被连接保存覆盖

- 用户反馈点击 `deepseek-v4-pro` 后默认模型仍停留在 `deepseek-v4-flash`。
- 排查确认 `/api/v1/ai/models/select` 后端接口可以正常把默认模型切换到 `deepseek-v4-pro`；问题出在前端点击模型按钮时，接口地址输入框失焦会同时触发“保存连接”，晚返回的连接保存结果可能带着旧默认模型覆盖 UI 状态。
- 已修改 `backend/app/services/ai_model_service.py`：`update_connection_config()` 在写入前重新读取最新配置，避免用旧配置覆盖刚保存的 `selected_model`。
- 已修改 `backend/static/index.html`：点击模型选择时先把 `selected_model` 乐观更新到前端状态并立即重绘，让界面马上显示新默认模型。
- 已完成后端 `compileall backend\app`、`preview_server.py` 语法检查、前端内联脚本解析检查；并用 FastAPI TestClient 模拟“先选模型、再保存旧连接”的竞态，最终默认模型保持 `deepseek-v4-pro`。

### 2026-05-03 对话 48：AI 调用策略按任务拆分并写入最高性能默认值

- 用户认可按任务拆分 AI 调用参数，并要求按最高性能配置写入，不用过度保守。
- 已修改 `backend/app/services/ai_model_service.py`：新增 `DEFAULT_TASK_POLICIES`，把 AI 调用策略拆成五类任务：新闻粗筛、深度研判、风控复核、最终交易建议、行业深度报告。
- 全局默认策略已调整为：默认温度 `0.15`、调用超时 `60` 秒、最大事件上下文 `80` 条。
- 五类任务默认参数已写入：
  - 新闻粗筛：温度 `0.2`、超时 `25` 秒、上下文 `30` 条。
  - 深度研判：温度 `0.18`、超时 `75` 秒、上下文 `80` 条。
  - 风控复核：温度 `0.05`、超时 `45` 秒、上下文 `45` 条。
  - 最终交易建议：温度 `0.08`、超时 `60` 秒、上下文 `60` 条。
  - 行业深度报告：温度 `0.25`、超时 `120` 秒、上下文 `120` 条。
- `update_usage_policy()` 已支持保存 `task_policies`，旧配置读取时会自动合并新增任务默认值，避免历史配置缺字段。
- 已修改 `backend/static/index.html`：AI 调用管理策略页新增五类任务的独立温度、超时、上下文输入框；保存时会把所有任务策略写入后端配置。
- 已通过接口把上述推荐参数写入本地 `backend/data/ai/model_config.json`；真实下单开关仍保持关闭，真实交易接入继续由独立交易权限控制。
- 已完成后端 `compileall backend\app`、`preview_server.py` 语法检查、前端内联脚本解析检查，并用 FastAPI TestClient 验证 `/api/v1/ai/policy` 已返回五类任务策略。
### 2026-05-03 对话 49：提示气泡跟随鼠标与 AI 对话窗自由布局

- 用户要求把右下角提示改为在鼠标所在位置显示，并让 `Ctrl+Shift+A` 打开的站内 AI 对话框可以任意拖拽和改变大小。
- 已修改 `backend/static/index.html`：全局记录最近鼠标位置，`toast()` 显示时会贴近当前指针并自动限制在视口内，刷新、启动选股、AI 分析、回测、交易等所有复用提示都会同步生效。
- 已增强站内 AI 对话框：标题栏可拖拽，窗口支持浏览器原生右下角缩放，拖动和缩放后的 `left/top/width/height` 会保存到 `localStorage`，刷新页面后仍保持上次布局。
- AI 对话框在窗口尺寸变化时会自动夹紧到可视区域内，避免拖到屏幕外后找不回来。
- 已完成前端内联脚本语法检查：`inline js ok 1`。

### 2026-05-03 对话 50：调整 AI 选股推荐口径与信号页结构

- 用户指出 AI 自动选股不应展示“暂不买入、无推荐购买时间”的股票；只有真正推荐购买的股票才进入“AI推荐购买”。
- 已修改 `backend/app/services/ai_stock_picker.py`：新增购买推荐判定，自动 AI 选股只保留 `recommend_buy=true` 的推荐购买结果，并记录被过滤的等待/观察数量；手动单股 AI 分析继续保留“暂不推荐购买、建议短线、建议长线”等结论。
- 已修改 `backend/app/main_simple.py`：`/api/v1/quant/signals` 只把 `recommend_buy=true` 的 AI 结果写入买入信号，避免暂不买入股票进入买入列表。
- 已修改 `backend/static/index.html`：信号页改为策略选择后启动 AI 选股；自动推荐购买、手动 AI 判断、短线专属震荡池、策略交易自选四块分开展示。
- 原“选股与自选实时建议”已移除，替换为“短线专属震荡池”：AI/人工先从震荡股池中挑，再按支撑、资金、K线、新闻、风控等逻辑选优。
- 策略配置页新增“策略交易自选”表格，专门承接用户自选股并提供 AI 判断入口。
- 已完成前端内联脚本语法检查、`main_simple.py` 与 `ai_stock_picker.py` 语法检查。

### 2026-05-03 对话 51：站内 AI 对话接入全站只读检索

- 用户指出站内 AI 不应回答“不知道某只股票”，它应能掌握整个网站的只读数据；除不能修改网站参数、不能下单、不能回答密钥外，应能查询全站信息。
- 已修改 `backend/app/main_simple.py`：`/api/v1/ai/chat` 新增站内只读检索层，会从用户问题中识别股票名称或 6 位代码，并自动匹配股票池、实时行情缓存、K线缓存、评分卡、决策、风控、AI推荐、新闻、持仓等上下文。
- 对股票问题，模型提示词已改为必须优先使用 `matched_stocks` 中的站内数据回答，不能在命中股票后再说站内没有该股票。
- 新增权限边界上下文：站内 AI 可查询行情、K线、分时、选股、信号、风控、新闻、板块、自选、持仓、模拟盘、Agent 状态；禁止修改参数、真实/模拟下单、泄露 API Key 或本地敏感配置。
- 前端 `sendAIChat()` 已把浏览器本地自选股和当前策略一并传给后端，便于 AI 回答用户自己的自选相关问题。
- 已验证“大胜达/603687”可被站内 AI 检索命中；在 K线不足时会使用站内股票池/实时缓存兜底，判断最新可用交易日涨跌幅约 `+9.99%`。
- 已完成 `main_simple.py` 语法检查与前端内联脚本语法检查。

### 2026-05-03 对话 52：策略交易自选页、AI列表删除与AI判断进度提示

- 用户要求“策略交易”左侧分组内新增单独的“自选”列表，用于存放用户自选股票；不同于行情投研下的自选入口，这里服务于策略交易、AI判断和信号复核。
- 已在 `backend/static/index.html` 新增 `strategyWatchlist` 页面，并把它加入“策略交易”子菜单；该页面复用浏览器本地 `quant_watchlist` 自选数据，提供去行情添加、去信号页、刷新短线震荡池和对单股执行 AI 判断的入口。
- 信号页的“AI推荐购买”和“手动AI判断”两张表最右侧新增“删除”按钮，点击后会把该股票从当前 AI 列表中移除，并同步保存到本地 `quant_ai_recommendations_local`，刷新页面后仍保持删除结果。
- 点击“AI判断”后，鼠标当前位置的提示框会显示进度条并保持显示，直到接口完成后才改为完成或失败提示，避免用户误以为点击无效。
- 已完成前端内联脚本语法检查：`inline js ok 1`。

### 2026-05-03 对话 53：扫描个股底层数据覆盖缺口

- 用户要求扫描个股数据，确认还缺哪些底层数据，例如 K线、日线、交易量，并给出实时引入方案。
- 当前本地行情缓存根目录为 `E:\lianghua_market_cache`，股票主列表 `universe/stocks.json` 已覆盖约 `5511` 只 A 股。
- 扫描结果：正式可信日K仅覆盖 `27` 只，候选日K覆盖 `27` 只，且正式日K当前多为单行最新交易日；实时行情缓存覆盖 `62` 只；分时缓存覆盖 `0` 只；资金流缓存覆盖 `0` 只；筹码缓存覆盖 `0` 只；日K校验报告 `27` 份，实时校验报告 `63` 份。
- 主要缺口：全市场历史日K/周K/月K、盘中分时、成交量历史序列、盘口五档/逐笔或大单、资金流、筹码分布、财务指标、公告/研报结构化数据。
- 现有代码已有缓存目录和读写函数：`kline/`、`intraday/`、`realtime/`、`money_flow/`、`chips/`、`validation/`，也已有三源实时校验和日K候选校验雏形；下一步应重点做“全市场数据引入调度器”和“可信缓存覆盖率面板”。

### 2026-05-03 对话 54：行情数据引入中枢与个股详情复刻增强

- 用户要求建设“行情数据引入中枢”：开盘前/收盘后同步股票池、新股、退市、更名、ST、停复牌；全市场历史日K/周K/月K分批补库；交易日 09:25-15:00 全市场三源实时快照 1 秒刷新；重点股票分时 15-30 秒刷新；按自选、持仓、AI推荐、短线震荡池、热门板块、涨跌幅/成交额前列和全市场低频补齐分优先级。
- 已新增 `backend/app/services/market_data_hub.py`：统一描述中枢规则、调度状态、优先队列、K线补库批次、实时快照刷新、重点分时刷新、单股数据可用性和全市场数据覆盖率。
- `main_simple.py` 已接入中枢启动线程 `_market_data_hub_loop`：非交易时段维护优先级队列，开盘前/收盘后触发主数据同步，交易窗口按优先级刷新实时快照和重点分时；现有 E 盘缓存根目录继续使用 `E:\lianghua_market_cache`。
- 新增接口：`GET /api/v1/market/data-hub/status`、`GET /api/v1/market/data-hub/coverage`、`GET /api/v1/stocks/{code}/data-availability`；`/api/v1/market/cache/status` 也带回 `market_data_hub`。
- 个股详情 `/api/v1/stocks/{code}/detail` 已返回 `chips`、`stock_info_panel`、`limit_gene`、`data_availability`。筹码峰基于已验证日K缓存推导并写入 `E:\lianghua_market_cache\chips`；截图里的盘口/F10/涨停基因等缺真实源字段先明确标为缺失或待接入，不伪造。
- 前端 `backend/static/index.html` 新增“数据覆盖率”页面，展示日K、周K、月K、实时、分时、资金流、盘口、财务覆盖率、候选缓存数量、校验报告数量和高频优先队列。
- 个股详情新增“筹码峰”“数据可用性”“股票信息”“涨停基因”模块，尽量复刻截图中的筹码分布、基础行情/F10字段和涨停基因结构；缺失数据会显示来源、校验状态和说明。
- 修复了导航配置中因历史编码破损导致的前端脚本解析问题，并把导航中文恢复为正常文本。
- 已完成 `preview_server.py` 语法检查、后端 `compileall backend\app`、前端内联 JS 语法检查；FastAPI TestClient 验证中枢状态、覆盖率、单股可用性和 `600519` 详情接口均返回 200，覆盖率接口识别股票池 `5511` 只。

### 2026-05-03 对话 55：个股分时折线改为交易日实时推进

- 用户强调截图中的折线不是静态图片，而应在交易日按时间线从左到右实时更新。
- 已修改 `backend/static/index.html`：个股详情打开后会把初始分时数据写入 `state.liveMinutes`，实时轮询每秒获取 `/api/v1/market/snapshot/{code}` 后按当前交易分钟合并；同一分钟更新当前点，跨分钟追加新点，横轴仍固定为 A 股交易时间 09:30-11:30、13:00-15:00。
- 分时区从单一静态图扩展为实时工作区：分时价格线、均价线、分时量、量比线、分时 MACD 都基于同一条实时分钟序列重画，图线会随着快照从左向右推进。
- `/api/v1/market/snapshot/{code}` 已补充 `high`、`low`、`pre_close`、`pct_change`、`updated_at` 等字段，保证前端能按实时快照计算涨跌幅、均价、分时指标和时间桶。
- 已完成前端内联 JS 语法检查、`preview_server.py` 语法检查、后端 `compileall backend\app`；用 TestClient 验证 `600126` 实时快照返回 `current_price/open/high/low/pre_close/pct_change/volume/amount/updated_at`。

### 2026-05-03 对话 56：同花顺 APP 探测、腾讯证券补强与全市场导入入口

- 用户打开同花顺 APP 后要求确认能否获取所有股票数据，并强调不能只读单股。
- 已探测同花顺进程：`hexin.exe`、`HxDataService.exe`、`hexinhelper.exe`、`xiadan.exe` 等运行中；`127.0.0.1:16197` 实际为飞鸟加速 `core.exe` 代理，不是同花顺行情服务；同花顺自身主要连接远端 `8601/8901/9601`，未发现可直接调用的本地 HTTP 行情端口。
- 已确认同花顺会写本地历史文件，例如 `D:\同花顺\同花顺\history\shase\day\600126.day` 和 `extra\600126.ext`；当前本地 `.day` 覆盖仅 42 只股票（沪 27、深 14、北 1），不是 5511 只全市场库，适合作为增量高可信本地源而非唯一全市场来源。
- 已新增 `data_fetcher.fetch_realtime_tencent_batch()`，接入腾讯证券 `qt.gtimg.cn`，补齐五档盘口、内盘/外盘、涨跌停、均价、量比、换手、委比、PE/PB、市值、股本等字段，并参与实时多数校验。
- `600126` 实测实时校验接受源为 `新浪 + 腾讯`，参与源包含 `新浪/腾讯/同花顺`，已补回买一/卖一、内外盘、涨跌停、均价、PE/PB、市值、股本、委比、量比、换手等字段。
- 已新增同花顺本地只读覆盖接口 `GET /api/v1/market/ths-local/status`，返回本地 `.day` 覆盖数量、市场分布、文件样本和说明。
- 已新增全市场导入入口 `POST /api/v1/market/data-hub/import-all`：面向 5511 只股票启动股票池、实时快照、日/周/月K、资金流和筹码导入；分时不默认全市场高频拉取，仍按自选/持仓/AI推荐/震荡池优先队列刷新。
- 已完成 `compileall backend\app`、`preview_server.py` 语法检查、前端内联 JS 语法检查；TestClient 验证 `/api/v1/market/ths-local/status` 和 `/api/v1/market/data-hub/coverage` 均返回 200。
### 2026-05-03 对话 57：启动全市场数据导入并补强进度/覆盖率口径

- 用户要求“现在开始全市场导入”，已在更新后的 8010 服务上启动 `POST /api/v1/market/data-hub/import-all`，参数为 5511 只全市场股票、1000 天、日/周/月 K、实时快照、资金流和筹码，缓存根目录为 `E:\lianghua_market_cache`。
- 当前导入正在第一阶段“全市场实时快照三源校验”，不中断旧任务；实时缓存持续增长，已观察到从 380、603、797、1870、1922 增至 2119 个文件，覆盖率约 38.45%，validation 报告同步增长至 2145 个。
- 已确认旧 8010 运行实例仍使用早先进度字段，导入第一阶段只增长文件数，`done/success` 会等实时批处理后进入逐只历史补库阶段才变化；为后续任务已在 `backend/app/main_simple.py` 增加 `stage/stage_label/current_batch/realtime_batches_done/realtime_codes_done/kline_periods_done/money_flow_done/chips_done` 等细粒度进度字段。
- 已在 `backend/app/services/market_data_hub.py` 增加基于实时缓存字段的盘口/估值覆盖率统计辅助函数，并用新的 `get_stock_data_availability()` 覆盖旧实现：腾讯实时快照里的五档盘口计为 `orderbook` 可用，PE/PB/市值等计为实时估值快照；深度 F10 财务和逐笔/L2 仍标记为待接入。
- 已完成 `backend\venv\Scripts\python.exe -m compileall backend\app` 与 `backend\venv\Scripts\python.exe -m py_compile preview_server.py`。为了不打断正在写 E 盘缓存的导入任务，未重启 8010；新增进度字段会在下一次启动新版服务后生效。
- 用户准备关机前的断点：实时全市场已完成 `5511/5511`；第二阶段历史补库正在跑，最近一次查询为 `done=761/5511`、`success=761`、`failed=0`、`current=600604`；日K覆盖 `777/5511`，K线缓存文件 `2335`，validation 报告 `6301`。关机后运行中的 8010 进程会停止，但 `E:\lianghua_market_cache` 已落盘缓存保留；明天应先启动新版服务，再检查覆盖率，继续从未覆盖股票补库，避免重复全量从头跑。

### 2026-05-03 对话 58：复查 AI 选股按钮、全局数据缺口与当前问题

- 用户反馈当前页面已做出，但希望继续扫描项目、确认还缺什么数据、是否有 BUG，并指出“启动AI选股”点击后没反应。
- 已确认 `/api/v1/quant/signals/ai-pick` 后端接口可用：TestClient 实测返回 200，DeepSeekV4Pro 被调用，耗时约 39 秒；本次 20 只候选全部被 AI/风控判为观察或过滤，因此推荐购买数量为 0、买入信号为 0，这属于当前严格过滤逻辑的结果。
- 已修复 `backend/static/index.html` 的 AI 选股交互：点击“启动AI选股”后改用鼠标位置的持续进度提示，接口完成或失败后才收起，并在完成提示中展示推荐购买数量和过滤观察数量，避免用户误以为按钮无效。
- 已补充保存 AI 选股结果到浏览器本地缓存，避免刷新或信号页重绘时刚返回的结果丢失。
- 已修复信号页 AI 推荐购买/手动 AI 判断表头缺少“操作”列的问题，使右侧删除按钮与 9 列表格结构一致。
- 已复查底层数据覆盖：当前股票池 5511 只；`E:\lianghua_market_cache` 已存在实时 5524 文件、分时 5511 文件、日/周/月 K 文件均约 5511，但数据覆盖率接口按当前股票池校验后显示日K/周K/月K可用 5198/5511，资金流 5444/5511，筹码 2243/5511，说明仍有部分缓存文件与当前股票池或可信校验口径不完全匹配。
- 已发现一个真实数据问题：`backend/data/sector_cache/sector_news_archive.json` 当前 JSON 已损坏且内容存在编码乱码，导致板块新闻归档无法正常读取，板块时间线和新闻因子会受影响；后续应优先做新闻缓存清洗、原文编码修复和归档原子写入。
- 已完成前端内联 JS 语法检查、后端 `compileall backend\app` 检查，并用 TestClient 验证健康检查、缓存状态、数据覆盖率、信号和板块接口均可返回。
