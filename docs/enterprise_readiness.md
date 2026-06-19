# ServiceGuard Agent 企业化就绪说明

## 当前结论

当前版本已经超过普通 RAG Demo，适合用于企业内部 POC、实习项目投递、面试演示和小规模离线样例评测。它还不能直接作为多部门、多租户、高并发生产系统上线。

## 已补齐能力

| 类别 | 当前能力 |
| --- | --- |
| 配置 | `.env` + pydantic-settings，模型、向量库、路径、全局请求体大小、CORS、鉴权均可配置；production 启动前会做安全自检 |
| 数据库治理 | SQLite 初始化带轻量 schema_migrations 版本台账；连接启用 busy timeout、foreign_keys、WAL journal mode 和 NORMAL synchronous；ready、安全状态和 Prometheus 指标可查看当前/期望版本、待迁移数量、quick check、外键开关和 busy timeout |
| 鉴权 | `REQUIRE_API_KEY=true` 后业务接口要求 `X-API-Key`、`Authorization: Bearer` 或可信网关身份头；支持 user/admin key、`API_KEY_HASHES` / `ADMIN_API_KEY_HASHES` SHA-256 摘要，也支持由 SSO/API Gateway 注入用户与角色头；可信网关头必须带共享密钥，报告和后台任务按创建者隔离，admin 可全局查看 |
| 前端 | 侧边栏可输入 API key，支持中文/英文界面切换，批量质检支持同步和后台任务模式，文档上传后展示索引块数、脱敏统计和提示注入风险，并可触发历史知识库隐私治理、安全扫描、隔离文档批准/拒绝和运维中心巡检 |
| 安全 | CORS 白名单、全局请求体大小限制、上传文件读取后字节数复核、进程内接口限流、安全响应头、密钥不入库 |
| 隐私 | 工单文本在检索、模型调用、响应和落库前脱敏手机号、邮箱、身份证、银行卡；知识库文档在 chunk/向量化/持久化前脱敏手机号、邮箱、身份证、银行卡、OpenAI key、JWT、Bearer token 和常见 secret/password 字段 |
| 知识库安全 | 上传知识库文档会标记指令覆盖、角色改写、提示词泄露、策略绕过和命令执行类 prompt injection 风险；默认隔离风险文档，不写入 chunk/Chroma，管理员批准后才入库，也可拒绝并清空索引；管理员可扫描历史 chunk 和本地上传文件，接口只返回类别与次数，不回显可疑原文 |
| 可观测 | LLM 调用日志、工具链路、延迟、错误、request id、结构化审计事件，审计事件哈希链校验 |
| 运维巡检 | `/api/admin/security/status` 汇总鉴权、CORS、限流、远程模型、SQLite 运行状态、批量任务边界与活跃容量、保留周期和审计链状态；Streamlit 运维中心集中展示安全状态、运行指标、审计链校验、最近审计事件和数据保留清理 |
| 健康检查 | `/health` 基础检查，`/ready` 依赖检查，`/metrics` JSON 指标，`/metrics/prometheus` Prometheus 指标，Prometheus 抓取配置、Alertmanager 路由示例和 `deploy/prometheus/serviceguard_alerts.yml` 告警规则，包含安全隔离队列积压和后台任务活跃容量告警；`scripts/smoke_test.py` 可对已启动实例执行 HTTP 级运行验收 |
| 部署入口 | 提供可选 Nginx gateway Compose，把 API、健康检查、指标和 Streamlit 前端统一到 `localhost:8080`；提供生产 HTTPS/TLS 示例配置 |
| RAG 稳定性 | 引用溯源、Citation Verifier、无依据时人工复核 |
| 人工复核 | `need_human_review=true` 的报告自动进入 `pending` 队列，管理员可标记 approved/rejected/escalated 并写入备注 |
| 数据治理 | 管理员可 dry-run/执行过期报告、LLM 日志、批量任务清理；审计事件需显式 include_audit 才清理；支持 dry-run/执行历史知识库 chunk、向量文本和上传文件脱敏补救；支持 scan-only 历史知识库提示注入巡检与上传文档准入隔离 |
| 备份快照 | 管理员可创建、列出、校验、恢复演练和下载本地 ZIP 备份，包含 SQLite 元数据和上传文件，可选包含 Chroma 向量库；manifest 记录文件级 SHA256，配置 `BACKUP_SIGNING_KEY` 后写入 HMAC-SHA256 签名，校验覆盖 ZIP、manifest、签名、文件哈希和 SQLite integrity_check；restore dry-run 会临时解包 SQLite、检查核心表并对比 manifest 表计数 |
| 批量处理 | 支持同步 CSV 质检，也支持后台 batch job 提交、查询、取消、部分结果保留和结果持久化；`MAX_BATCH_ROWS` 限制单次 CSV 行数，`BATCH_JOB_TIMEOUT_SECONDS` 限制后台任务总运行时间，`MAX_ACTIVE_BATCH_JOBS` / `MAX_ACTIVE_BATCH_JOBS_PER_ACTOR` 限制全局和单创建者 pending/running 任务数量；创建后台任务支持 `Idempotency-Key`，客户端重试不会重复排队，重放请求不会被活跃容量限制误拦截；服务重启会把遗留 pending/running 任务标记为 interrupted 并保留已有进度 |
| 质量 | pytest 覆盖主链路，ruff lint/format，前端编译检查，Docker Compose 配置校验；评测脚本输出 JSON/Markdown 报告，并按风险准确率、违规类型准确率、引用覆盖率和高风险召回率阈值失败退出；smoke test 从 HTTP 外部验证已启动后端主链路；GitHub Actions 自动运行测试、评测门禁、运行时 smoke test 和前后端 Docker 镜像构建 |
| 容器安全 | 后端/前端镜像使用非 root 用户运行；`.dockerignore` 排除 `.venv`、本地数据库、Chroma、上传文件、日志、备份和学习资料，避免污染构建上下文 |
| 数据 | 合成政策文档与 20 条工单评测集，避免真实隐私数据；评测报告记录混淆矩阵、逐行命中情况和平均耗时 |

## 尚未达到完整生产级的部分

| 缺口 | 企业生产要求 | 后续升级建议 |
| --- | --- | --- |
| 身份权限 | 当前是 API key 或可信网关身份头级别 user/admin，支持哈希形式配置以减少明文密钥暴露，可接在企业 SSO/API Gateway 后面，但还不是完整内置账号体系 | 生产化可直接接 OAuth/OIDC，区分组织、用户、角色和会话生命周期 |
| 数据库 | SQLite 适合 POC；当前已有轻量 schema 版本台账、WAL/busy timeout/外键开启和 quick check 运行自检，但不是完整迁移框架，也不是多租户高并发数据库 | 迁移 PostgreSQL，加 Alembic migration 和回滚策略 |
| 文件存储 | 本地目录适合 Demo | 接对象存储或企业文档系统 |
| 异步任务 | 当前是 FastAPI 进程内 background job，适合 POC；报告和任务结果已按 API key 创建者隔离，支持协作式取消、协作式超时、创建接口幂等重试、全局/单创建者活跃任务限额，并能在服务重启后标记 interrupted 遗留任务 | 生产化改为 Celery/RQ/Arq + Redis，并加硬超时、分布式并发控制、任务重放和跨进程 worker 管理 |
| 接口限流 | 当前是单进程内存限流，适合单机演示 | 生产化放到 API Gateway/Nginx 或 Redis 分布式限流 |
| 部署入口 | Docker Compose 适合单机；已有可选 Nginx gateway、生产 TLS 示例配置，CI 构建前后端镜像并校验主 Compose、gateway Compose 与 monitoring Compose 配置 | 接入正式证书管理、镜像仓库、环境分层部署和发布回滚 |
| 监控告警 | 当前已有 JSON/Prometheus 指标，包含 pending/reviewed 报告、后台任务状态、HTTP 5xx、429 限流和延迟观测，并提供 Prometheus 抓取配置、Alertmanager 路由示例、alert rules 和可选 monitoring Compose | 生产化接企业告警路由、OpenTelemetry/Langfuse、日志平台和 SLA 值班流程 |
| 审计可信度 | 新审计事件带 previous_hash/event_hash，可校验内容与链路是否被篡改 | 生产化接 WORM 存储、SIEM 或云审计服务 |
| 合规审批 | 当前已有 POC 级人工复核 API，但不是完整审批工单系统 | 接企业审批流、SLA、复核人分配和通知 |
| 数据生命周期 | 当前已有 POC 级保留周期清理 API、历史知识库隐私补救 API、本地 ZIP 备份快照、文件级 SHA256 校验、manifest HMAC 签名、备份完整性校验和只读恢复演练 | 生产化接企业数据保留策略、归档、对象存储异地备份、加密、定期恢复演练和审批删除 |
| 生产配置 | 当前会阻止 production 使用无鉴权、开放 CORS、无远程模型 key、关闭限流、无备份签名 key 等危险配置 | 后续可接集中配置中心、密钥管理服务和配置漂移检测 |
| 脱敏范围 | 覆盖常见手机号、邮箱、身份证、银行卡、OpenAI key、JWT、Bearer token 和常见 secret/password 字段，并已覆盖工单与知识库上传链路 | 后续接企业 DLP/PII 检测服务，覆盖地址、姓名等更复杂实体 |
| 提示注入防护 | 当前能在上传和历史巡检中标记常见 prompt injection 文本，上传风险文档默认进入隔离区，批准后才入向量库，并在系统提示中约束检索内容只能引用不能执行 | 生产化应接入正式文档准入审批、风险分级、模型侧上下文隔离和红队评测 |

## 推荐面试表述

可以说：

> 这个项目当前定位是企业客服质检 POC，而不是直接替代生产质检系统。它已经具备 RAG、结构化质检报告、引用校验、中英文界面、工单与知识库文档脱敏、知识库提示注入风险扫描与隔离复核、历史知识库隐私扫描/补救、日志、Prometheus 指标与告警规则、Prometheus/Alertmanager 示例部署、Nginx 统一入口和 HTTPS 示例配置、user/admin API key、API key SHA-256 哈希配置、可信网关身份头认证、接口限流、生产配置自检、安全状态总览、前端运维中心、数据库 schema 版本台账、SQLite WAL/busy timeout/quick check 运行自检、审计事件哈希链、后台批量任务查询/取消/超时/幂等提交/活跃容量限制/中断恢复标记、报告/任务结果隔离、人工复核 API、数据保留清理、本地备份快照、文件级 SHA256 校验、manifest HMAC 签名、只读恢复演练、健康检查、运行时 smoke test、样例工单评测门禁、Docker Compose 部署、非 root 容器和 GitHub Actions 质量门禁；如果要生产化，我会优先做内置 OIDC/权限模型、PostgreSQL/Alembic、Redis/Celery 队列、对象存储、正式证书管理和企业告警路由。

不要说：

> 这个项目已经是完整企业级生产系统。
