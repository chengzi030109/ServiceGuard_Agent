# ServiceGuard Agent 任务计划书

## 1. 项目定位

ServiceGuard Agent 是一个企业知识库驱动的客服/工单质检智能体。系统基于企业 SOP、产品 FAQ、售后政策和隐私合规规则构建 RAG 知识库，并对客服对话或工单执行质检，输出可追溯的结构化报告。

核心目标不是做一个泛聊天机器人，而是做一个可演示、可部署、可解释、可评测的 Agent 应用项目。

## 2. 最终交付范围

P0 必做：

- FastAPI 后端，提供健康检查、文档上传、文档列表、检索、RAG 问答、单条工单质检、批量工单质检、报告查询、人工复核、日志查询、数据保留清理接口。
- 文档入库链路，支持 TXT、Markdown、PDF 文本抽取，入库前执行敏感信息脱敏，再进行 chunk 切分、embedding、向量检索和引用溯源。
- 文档入库链路在脱敏后执行提示注入风险扫描，返回风险类别与次数，不回显可疑原文；风险文档默认隔离，管理员批准后才进入 chunk/向量库。
- 工单质检 workflow，包含检索政策、抽取风险、规则判定、评分、建议生成、引用校验和日志记录。
- Pydantic 结构化报告，包含 score、risk_level、violations、citations、suggested_reply、need_human_review、confidence、missing_info。
- 高风险或缺少依据的报告进入人工复核队列，管理员可写入 approved/rejected/escalated 结论。
- 管理员可 dry-run 预览并清理过期报告、LLM 日志、批量任务和审计事件。
- 管理员可 dry-run 预览并执行历史知识库敏感信息扫描与脱敏补救，覆盖 SQLite chunk、Chroma 向量文本和本地上传文件。
- 管理员可 scan-only 巡检历史知识库提示注入风险，覆盖 SQLite chunk 和本地上传文件；可批准或拒绝隔离中的风险文档。
- 管理员可创建、列出、校验、恢复演练和下载本地 ZIP 备份快照，覆盖 SQLite 元数据和上传文件，可选包含 Chroma 向量库，并通过 manifest 文件级 SHA256 清单和可选 HMAC 签名校验完整性。
- 后台批量质检任务支持提交、查询、协作式取消、部分结果保留和用户/管理员可见性隔离。
- 服务启动时会把上次进程遗留的 pending/running 批量任务标记为 interrupted，避免任务永久卡在运行态。
- `APP_ENV=production` 时执行安全配置自检，阻止无鉴权、开放 CORS、关闭限流、无远程模型 key 等危险启动配置。
- 生产配置自检要求备份签名 key，避免生产备份缺少 manifest 防篡改证据。
- 新审计事件写入 previous_hash/event_hash，管理员可校验审计哈希链是否被篡改，并可创建可签名审计锚点证据，记录事件前缀 SHA256、最后事件 hash、链校验摘要和 schema 版本。
- `/metrics/prometheus` 输出 Prometheus 文本指标，并提供 Prometheus 抓取配置、Alertmanager 路由示例、alert rules 和可选 monitoring Compose，便于企业监控系统抓取和告警。
- 管理员可通过 `/api/admin/security/status` 查看当前运行安全状态总览。
- SQLite 初始化记录轻量 schema_migrations 版本台账，连接启用 WAL、busy timeout、foreign key，并在 ready、安全状态和指标中暴露当前/期望版本、quick check 与运行配置。
- Streamlit 前端，默认中文，支持切换 English，支持上传政策文档、知识库问答、单条/批量质检、查看引用和下载结果。
- Streamlit 运维中心展示安全状态、运行指标、审计链校验、最近审计事件和数据保留清理。
- SQLite 日志与元数据存储，记录文档、chunk、报告和模型调用信息。
- 样例政策文档、样例工单 CSV、评测脚本和 pytest 测试。
- Dockerfile、docker-compose、README 和 AGENTS.md。
- `.dockerignore` 控制构建上下文，避免把本地虚拟环境、数据库、向量库、日志、备份和资料文档打入镜像。
- GitHub Actions CI 自动运行 lint、format check、pytest、前端编译、主 Compose/gateway Compose/monitoring Compose 配置校验和前后端镜像构建。
- 可选 Nginx gateway 统一代理后端 API、健康检查、指标和 Streamlit 前端；提供生产 HTTPS/TLS 配置示例。

P1 加分：

- OpenAI-compatible LLM 与 embedding 封装。
- 无 API key 时使用 deterministic local fallback，保证项目开箱可演示和测试。
- Citation verifier 对无依据违规结论降置信度并标记人工复核。
- 评测脚本输出 JSON/Markdown 报告，包含成功率、风险分类准确率、违规类型准确率、引用覆盖率、高风险召回率、混淆矩阵和平均耗时，并支持阈值门禁失败退出。

暂不做：

- React/Next.js 前端、多租户权限、Kubernetes、复杂 MCP、真实客户数据、本地大模型微调。

## 3. 技术路线

- Python 3.12
- FastAPI + Pydantic v2 + pydantic-settings
- OpenAI Python SDK，兼容 OPENAI_BASE_URL
- Chroma PersistentClient 作为本地向量库
- SQLite 保存业务元数据和日志
- Streamlit 做演示前端
- pytest + ruff 做质量检查
- Docker Compose 做本地部署

## 4. 里程碑

### M1: 项目骨架

- 建立目录结构、依赖文件、环境变量示例、README、AGENTS。
- 实现 /health 和基础配置。
- 写最小测试。

### M2: RAG 知识库

- 实现文档解析、chunk 切分、embedding、Chroma 入库。
- 实现文档上传、列表、检索、debug chunks。
- 实现 RAG 问答和 citation 输出。

### M3: 工单质检 Agent

- 定义 TicketInspectRequest、QualityReport、Violation、Citation 等 schema。
- 实现 inspect_ticket workflow。
- 加入引用校验、评分、风险分级和 fallback 规则。
- 实现单条和批量质检接口。

### M4: 日志、评测、前端

- 记录 LLM 调用、工具链路、延迟、错误信息。
- 实现 /api/logs、/api/reports、/api/reports/{report_id}、/api/reports/{report_id}/review、/api/admin/retention/purge、/api/admin/security/status、/api/audit-events/verify。
- 编写 Streamlit 页面和评测脚本。
- 加入样例数据和测试。

### M5: 部署与验收

- 编写 Dockerfile、docker-compose。
- 补充 Nginx gateway 和监控 Compose 覆盖文件。
- 补充 `.dockerignore` 和 GitHub Actions 质量门禁。
- 编写运行时 smoke test，从 HTTP 外部验证健康检查、指标、RAG、质检、安全状态、审计链和审计锚点。
- 运行 pytest、ruff、评测门禁和 smoke test。
- 更新 README 的启动命令、接口说明、演示流程和面试讲法。

## 5. 验收标准

- 本地 `pytest` 通过。
- `GET /health` 返回 ok。
- 上传样例政策文档后，`POST /api/search` 能返回 chunk 和相似度。
- `POST /api/chat` 能返回 answer 和 citations。
- `POST /api/tickets/inspect` 能返回固定 JSON 质检报告。
- 批量 CSV 质检能生成多条报告。
- Streamlit 能完成上传、问答、质检展示。
- Streamlit 默认中文，可切换英文；文档上传后能展示脱敏统计和提示注入风险，支持隔离文档安全复核，并能在运维中心完成安全巡检。
- 生产配置可使用 `API_KEY_HASHES` / `ADMIN_API_KEY_HASHES`，不必把明文 API key 写入部署环境。
- 可启用 `TRUSTED_PROXY_AUTH_ENABLED`，由企业 SSO/API Gateway 通过共享密钥保护的身份头传入 user/admin 角色。
- `MAX_UPLOAD_MB` 作为全局请求体大小限制，上传入口读取后再次校验实际字节数。
- 后台批量任务创建接口支持 `Idempotency-Key`，客户端重试不会重复创建任务。
- 批量 CSV 有 `MAX_BATCH_ROWS` 行数限制，后台任务有 `BATCH_JOB_TIMEOUT_SECONDS` 协作式超时保护，并通过 `MAX_ACTIVE_BATCH_JOBS` / `MAX_ACTIVE_BATCH_JOBS_PER_ACTOR` 限制全局和单创建者活跃任务数量。
- `.env` 不入库，README 能指导别人复现。
