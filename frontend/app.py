import io
import os

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

TEXT = {
    "zh": {
        "language": "语言",
        "api_ok": "API 正常",
        "api_unavailable": "API 不可用",
        "status": "状态",
        "documents": "文档管理",
        "knowledge_qa": "知识库问答",
        "ticket_inspect": "单条质检",
        "batch_inspect": "批量质检",
        "review": "人工复核",
        "operations": "运维中心",
        "logs": "日志",
        "policy_document": "政策文档",
        "upload": "上传",
        "indexed": "已入库",
        "question": "问题",
        "question_example": "客户申请退款时，客服能不能直接承诺一定全额退款？",
        "top_k": "召回数量 Top K",
        "ask": "提问",
        "ticket_text": "工单内容",
        "ticket_example": "客户：我要退款。客服：我保证给您全额退款，不用看物流，今天马上到账。",
        "inspect_ticket": "开始质检",
        "score": "评分",
        "risk": "风险",
        "confidence": "置信度",
        "human_review": "人工复核",
        "review_status": "复核状态",
        "review_comment": "复核备注",
        "review_decision": "复核结论",
        "submit_review": "提交复核",
        "refresh_reports": "刷新报告",
        "report_id": "报告 ID",
        "latest_reports": "最近报告",
        "ticket_csv": "工单 CSV",
        "batch_mode": "处理模式",
        "sync_batch": "同步处理",
        "async_batch": "后台任务",
        "run_batch": "运行批量质检",
        "create_job": "创建后台任务",
        "refresh_job": "刷新任务",
        "cancel_job": "取消任务",
        "job_id": "任务 ID",
        "job_status": "任务状态",
        "total": "总数",
        "succeeded": "成功数量",
        "failed": "失败数量",
        "latest_jobs": "最近后台任务",
        "download_json": "下载 JSON",
        "download_csv": "下载 CSV",
        "error_only": "仅显示错误",
        "download_logs": "下载日志",
        "backups": "备份快照",
        "include_uploads": "包含上传文件",
        "include_chroma": "包含 Chroma 向量库",
        "create_backup": "创建备份",
        "download_backup": "下载备份",
        "verify_backup": "校验备份",
        "restore_backup_dry_run": "恢复演练",
        "api_key": "API Key（可选）",
        "saved": "已保存",
        "chunks_indexed": "索引块数",
        "sensitive_redactions": "脱敏统计",
        "no_sensitive_data": "未发现敏感信息",
        "prompt_injection_risks": "提示注入风险",
        "no_prompt_injection_risks": "未发现提示注入风险",
        "privacy_remediation": "历史知识库隐私治理",
        "dry_run": "仅预览，不修改数据",
        "run_privacy_remediation": "扫描/修复历史敏感信息",
        "document_security_scan": "历史知识库安全扫描",
        "run_document_security_scan": "扫描提示注入风险",
        "quarantined_documents": "待安全复核文档",
        "select_document": "选择文档",
        "approve_document": "批准入库",
        "reject_document": "拒绝入库",
        "document_review_result": "文档复核结果",
        "security_status": "安全状态",
        "runtime_metrics": "运行指标",
        "audit_chain": "审计链",
        "retention_purge": "数据保留清理",
        "refresh_security_status": "刷新安全状态",
        "refresh_metrics": "刷新指标",
        "verify_audit_chain": "校验审计链",
        "run_retention_purge": "执行保留清理",
        "production_ready": "生产就绪",
        "warnings": "告警",
        "controls": "控制项",
        "control": "控制项",
        "value": "值",
        "metric": "指标",
        "warning": "告警",
        "audit_events": "审计事件",
        "tampered": "疑似篡改",
        "data_older_than_days": "运行数据超过天数",
        "audit_older_than_days": "审计数据超过天数",
        "include_audit": "包含审计事件",
        "app_env": "运行环境",
        "pending_review": "待复核",
        "quarantined": "已隔离",
        "yes": "是",
        "no": "否",
        "status_ok": "正常",
        "status_warning": "告警",
        "status_pending": "待处理",
        "status_not_required": "无需复核",
        "status_approved": "已通过",
        "status_rejected": "已拒绝",
        "status_escalated": "已升级",
        "status_running": "运行中",
        "status_interrupted": "已中断",
        "status_cancelled": "已取消",
        "status_failed": "失败",
        "status_succeeded": "成功",
        "status_low": "低",
        "status_medium": "中",
        "status_high": "高",
        "status_critical": "严重",
    },
    "en": {
        "language": "Language",
        "api_ok": "API ok",
        "api_unavailable": "API unavailable",
        "status": "Status",
        "documents": "Documents",
        "knowledge_qa": "Knowledge QA",
        "ticket_inspect": "Ticket Inspect",
        "batch_inspect": "Batch Inspect",
        "review": "Review",
        "operations": "Operations",
        "logs": "Logs",
        "policy_document": "Policy document",
        "upload": "Upload",
        "indexed": "Indexed",
        "question": "Question",
        "question_example": "Can support promise a full refund before checking the order?",
        "top_k": "Top K",
        "ask": "Ask",
        "ticket_text": "Ticket text",
        "ticket_example": (
            "Customer: I want a refund. Agent: I guarantee a full refund without "
            "checking logistics. It will arrive today."
        ),
        "inspect_ticket": "Inspect ticket",
        "score": "Score",
        "risk": "Risk",
        "confidence": "Confidence",
        "human_review": "Human Review",
        "review_status": "Review status",
        "review_comment": "Review comment",
        "review_decision": "Review decision",
        "submit_review": "Submit review",
        "refresh_reports": "Refresh reports",
        "report_id": "Report ID",
        "latest_reports": "Latest reports",
        "ticket_csv": "Ticket CSV",
        "batch_mode": "Mode",
        "sync_batch": "Sync batch",
        "async_batch": "Background job",
        "run_batch": "Run batch",
        "create_job": "Create job",
        "refresh_job": "Refresh job",
        "cancel_job": "Cancel job",
        "job_id": "Job ID",
        "job_status": "Job status",
        "total": "Total",
        "succeeded": "Succeeded",
        "failed": "Failed",
        "latest_jobs": "Latest jobs",
        "download_json": "Download JSON",
        "download_csv": "Download CSV",
        "error_only": "Error only",
        "download_logs": "Download logs",
        "backups": "Backups",
        "include_uploads": "Include uploads",
        "include_chroma": "Include Chroma vector store",
        "create_backup": "Create backup",
        "download_backup": "Download backup",
        "verify_backup": "Verify backup",
        "restore_backup_dry_run": "Restore dry-run",
        "api_key": "API Key (optional)",
        "saved": "Saved",
        "chunks_indexed": "Chunks indexed",
        "sensitive_redactions": "Sensitive redactions",
        "no_sensitive_data": "No sensitive data found",
        "prompt_injection_risks": "Prompt-injection risks",
        "no_prompt_injection_risks": "No prompt-injection risks found",
        "privacy_remediation": "Historical knowledge privacy",
        "dry_run": "Preview only",
        "run_privacy_remediation": "Scan/remediate historical sensitive data",
        "document_security_scan": "Historical knowledge security",
        "run_document_security_scan": "Scan prompt-injection risks",
        "quarantined_documents": "Documents awaiting security review",
        "select_document": "Select document",
        "approve_document": "Approve indexing",
        "reject_document": "Reject indexing",
        "document_review_result": "Document review result",
        "security_status": "Security status",
        "runtime_metrics": "Runtime metrics",
        "audit_chain": "Audit chain",
        "retention_purge": "Retention purge",
        "refresh_security_status": "Refresh security status",
        "refresh_metrics": "Refresh metrics",
        "verify_audit_chain": "Verify audit chain",
        "run_retention_purge": "Run retention purge",
        "production_ready": "Production ready",
        "warnings": "Warnings",
        "controls": "Controls",
        "control": "Control",
        "value": "Value",
        "metric": "Metric",
        "warning": "Warning",
        "audit_events": "Audit events",
        "tampered": "Tampered",
        "data_older_than_days": "Operational data older than days",
        "audit_older_than_days": "Audit data older than days",
        "include_audit": "Include audit events",
        "app_env": "App environment",
        "pending_review": "Pending review",
        "quarantined": "Quarantined",
        "yes": "Yes",
        "no": "No",
        "status_ok": "OK",
        "status_warning": "Warning",
        "status_pending": "Pending",
        "status_not_required": "Not required",
        "status_approved": "Approved",
        "status_rejected": "Rejected",
        "status_escalated": "Escalated",
        "status_running": "Running",
        "status_interrupted": "Interrupted",
        "status_cancelled": "Cancelled",
        "status_failed": "Failed",
        "status_succeeded": "Succeeded",
        "status_low": "Low",
        "status_medium": "Medium",
        "status_high": "High",
        "status_critical": "Critical",
    },
}

REVIEW_STATUS_OPTIONS = ["pending", "not_required", "approved", "rejected", "escalated"]
REVIEW_DECISION_OPTIONS = ["approved", "rejected", "escalated", "pending"]


st.set_page_config(page_title="ServiceGuard Agent", layout="wide")


with st.sidebar:
    language_label = TEXT["zh"]["language"] + " / " + TEXT["en"]["language"]
    lang = st.selectbox(
        language_label,
        ["zh", "en"],
        format_func=lambda item: "中文" if item == "zh" else "English",
    )
    api_key = st.text_input(TEXT[lang]["api_key"], type="password")


def t(key: str) -> str:
    return TEXT[lang][key]


def enum_label(value: object) -> str:
    key = f"status_{str(value).lower()}"
    return TEXT[lang].get(key, str(value))


def bool_label(value: object) -> str:
    return t("yes") if bool(value) else t("no")


st.title("ServiceGuard Agent")


def api_url(path: str) -> str:
    return f"{API_BASE_URL}{path}"


def api_headers() -> dict[str, str]:
    return {"X-API-Key": api_key} if api_key else {}


def show_response_error(response: requests.Response) -> None:
    try:
        payload = response.json()
        detail = payload.get("error", {}).get("message") or payload.get("detail") or response.text
    except ValueError:
        detail = response.text
    st.error(f"{response.status_code}: {detail}")


with st.sidebar:
    st.caption(API_BASE_URL)
    health = requests.get(api_url("/health"), headers=api_headers(), timeout=10)
    if health.ok:
        st.success(t("api_ok"))
        st.json(health.json(), expanded=False)
    else:
        st.error(t("api_unavailable"))


documents_tab, chat_tab, inspect_tab, batch_tab, review_tab, operations_tab, logs_tab = st.tabs(
    [
        t("documents"),
        t("knowledge_qa"),
        t("ticket_inspect"),
        t("batch_inspect"),
        t("review"),
        t("operations"),
        t("logs"),
    ]
)

with documents_tab:
    left, right = st.columns([1, 1])
    with left:
        uploaded = st.file_uploader(t("policy_document"), type=["txt", "md", "markdown", "pdf"])
        if st.button(t("upload"), disabled=uploaded is None):
            files = {"file": (uploaded.name, uploaded.getvalue())}
            response = requests.post(
                api_url("/api/documents/upload"),
                files=files,
                headers=api_headers(),
                timeout=120,
            )
            if response.ok:
                payload = response.json()
                st.success(f"{t('indexed')} · {t('chunks_indexed')}: {payload['chunks_indexed']}")
                redactions = payload.get("sensitive_redactions") or {}
                if redactions:
                    redaction_text = ", ".join(
                        f"{name}: {count}" for name, count in sorted(redactions.items())
                    )
                    st.info(f"{t('sensitive_redactions')}: {redaction_text}")
                else:
                    st.info(t("no_sensitive_data"))
                prompt_risks = payload.get("prompt_injection_risks") or {}
                if payload.get("prompt_injection_detected") and prompt_risks:
                    risk_text = ", ".join(
                        f"{name}: {count}" for name, count in sorted(prompt_risks.items())
                    )
                    st.warning(f"{t('prompt_injection_risks')}: {risk_text}")
                else:
                    st.info(t("no_prompt_injection_risks"))
                st.json(payload)
            else:
                show_response_error(response)
        st.divider()
        st.subheader(t("privacy_remediation"))
        remediation_dry_run = st.checkbox(t("dry_run"), value=True)
        if st.button(t("run_privacy_remediation")):
            response = requests.post(
                api_url("/api/admin/documents/privacy/remediate"),
                json={"dry_run": remediation_dry_run},
                headers=api_headers(),
                timeout=120,
            )
            if response.ok:
                st.json(response.json())
            else:
                show_response_error(response)
        st.divider()
        st.subheader(t("document_security_scan"))
        if st.button(t("run_document_security_scan")):
            response = requests.get(
                api_url("/api/admin/documents/security/scan"),
                headers=api_headers(),
                timeout=120,
            )
            if response.ok:
                payload = response.json()
                prompt_risks = payload.get("prompt_injection_risks") or {}
                if payload.get("prompt_injection_detected") and prompt_risks:
                    risk_text = ", ".join(
                        f"{name}: {count}" for name, count in sorted(prompt_risks.items())
                    )
                    st.warning(f"{t('prompt_injection_risks')}: {risk_text}")
                else:
                    st.info(t("no_prompt_injection_risks"))
                st.json(payload)
            else:
                show_response_error(response)
    with right:
        response = requests.get(api_url("/api/documents"), headers=api_headers(), timeout=20)
        if response.ok:
            docs = response.json()
            st.dataframe(pd.DataFrame(docs), use_container_width=True, hide_index=True)
            quarantined_docs = [doc for doc in docs if doc.get("status") == "quarantined"]
            if quarantined_docs:
                st.subheader(t("quarantined_documents"))
                selected_doc_id = st.selectbox(
                    t("select_document"),
                    [doc["id"] for doc in quarantined_docs],
                    format_func=lambda doc_id: next(
                        doc["filename"] for doc in quarantined_docs if doc["id"] == doc_id
                    ),
                )
                col_approve, col_reject = st.columns(2)
                with col_approve:
                    if st.button(t("approve_document"), disabled=not selected_doc_id):
                        response = requests.post(
                            api_url(f"/api/admin/documents/{selected_doc_id}/approve"),
                            headers=api_headers(),
                            timeout=120,
                        )
                        if response.ok:
                            st.success(t("saved"))
                            st.json(response.json(), expanded=False)
                        else:
                            show_response_error(response)
                with col_reject:
                    if st.button(t("reject_document"), disabled=not selected_doc_id):
                        response = requests.post(
                            api_url(f"/api/admin/documents/{selected_doc_id}/reject"),
                            headers=api_headers(),
                            timeout=120,
                        )
                        if response.ok:
                            st.success(t("document_review_result"))
                            st.json(response.json(), expanded=False)
                        else:
                            show_response_error(response)
        else:
            show_response_error(response)

with chat_tab:
    query = st.text_area(t("question"), value=t("question_example"))
    top_k = st.slider(t("top_k"), min_value=1, max_value=10, value=5)
    if st.button(t("ask")):
        response = requests.post(
            api_url("/api/chat"),
            json={"query": query, "top_k": top_k},
            headers=api_headers(),
            timeout=120,
        )
        if response.ok:
            data = response.json()
            st.markdown(data["answer"])
            st.dataframe(pd.DataFrame(data["citations"]), use_container_width=True, hide_index=True)
        else:
            show_response_error(response)

with inspect_tab:
    ticket_text = st.text_area(t("ticket_text"), value=t("ticket_example"), height=180)
    if st.button(t("inspect_ticket")):
        response = requests.post(
            api_url("/api/tickets/inspect"),
            json={"ticket_text": ticket_text, "top_k": 5},
            headers=api_headers(),
            timeout=120,
        )
        if response.ok:
            data = response.json()
            report = data["report"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric(t("score"), report["score"])
            c2.metric(t("risk"), enum_label(report["risk_level"]))
            c3.metric(t("confidence"), f"{report['confidence']:.2f}")
            c4.metric(t("human_review"), bool_label(report["need_human_review"]))
            st.json(report)
            if report["violations"]:
                st.dataframe(
                    pd.DataFrame(report["violations"]),
                    use_container_width=True,
                    hide_index=True,
                )
            if report["citations"]:
                st.dataframe(
                    pd.DataFrame(report["citations"]),
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            show_response_error(response)

with batch_tab:
    batch_mode = st.segmented_control(
        t("batch_mode"),
        [t("sync_batch"), t("async_batch")],
        default=t("sync_batch"),
    )
    csv_file = st.file_uploader(t("ticket_csv"), type=["csv"])
    if batch_mode == t("sync_batch") and st.button(t("run_batch"), disabled=csv_file is None):
        files = {"file": (csv_file.name, csv_file.getvalue())}
        response = requests.post(
            api_url("/api/tickets/batch"),
            files=files,
            headers=api_headers(),
            timeout=300,
        )
        if response.ok:
            data = response.json()
            st.metric(t("succeeded"), data["succeeded"])
            rows = []
            for item in data["results"]:
                report = item.get("report") or {}
                rows.append(
                    {
                        "row_number": item["row_number"],
                        "ticket_id": item["ticket_id"],
                        "ok": item["ok"],
                        "risk_level": enum_label(report.get("risk_level")),
                        "score": report.get("score"),
                        "error": item.get("error"),
                    }
                )
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button(
                t("download_json"),
                data=response.text,
                file_name="serviceguard_batch_results.json",
                mime="application/json",
            )
            if not df.empty:
                st.download_button(
                    t("download_csv"),
                    data=df.to_csv(index=False).encode("utf-8-sig"),
                    file_name="serviceguard_batch_summary.csv",
                    mime="text/csv",
                )
        else:
            show_response_error(response)

    if batch_mode == t("async_batch"):
        if st.button(t("create_job"), disabled=csv_file is None):
            files = {"file": (csv_file.name, csv_file.getvalue())}
            response = requests.post(
                api_url("/api/tickets/batch/jobs"),
                files=files,
                headers=api_headers(),
                timeout=120,
            )
            if response.ok:
                data = response.json()
                st.session_state["batch_job_id"] = data["job_id"]
                st.success(f"{t('job_id')}: {data['job_id']}")
            else:
                show_response_error(response)

        job_id = st.text_input(t("job_id"), value=st.session_state.get("batch_job_id", ""))
        if st.button(t("refresh_job"), disabled=not job_id):
            response = requests.get(
                api_url(f"/api/tickets/batch/jobs/{job_id}"),
                headers=api_headers(),
                timeout=20,
            )
            if response.ok:
                job = response.json()
                c1, c2, c3, c4 = st.columns(4)
                c1.metric(t("job_status"), enum_label(job["status"]))
                c2.metric(t("total"), job["total"])
                c3.metric(t("succeeded"), job["succeeded"])
                c4.metric(t("failed"), job["failed"])
                st.json(job)
            else:
                show_response_error(response)
        if st.button(t("cancel_job"), disabled=not job_id):
            response = requests.post(
                api_url(f"/api/tickets/batch/jobs/{job_id}/cancel"),
                headers=api_headers(),
                timeout=20,
            )
            if response.ok:
                st.success(t("saved"))
                st.json(response.json())
            else:
                show_response_error(response)

        response = requests.get(
            api_url("/api/tickets/batch/jobs"),
            headers=api_headers(),
            timeout=20,
        )
        if response.ok:
            jobs = response.json()
            for job in jobs:
                job["status"] = enum_label(job.get("status"))
            st.subheader(t("latest_jobs"))
            st.dataframe(pd.DataFrame(jobs), use_container_width=True, hide_index=True)
        else:
            show_response_error(response)

with review_tab:
    review_status = st.selectbox(
        t("review_status"),
        REVIEW_STATUS_OPTIONS,
        format_func=enum_label,
    )
    response = requests.get(
        api_url("/api/reports"),
        params={"limit": 100, "review_status": review_status},
        headers=api_headers(),
        timeout=20,
    )
    if response.ok:
        reports = response.json()
        rows = []
        for item in reports:
            report = item.get("report") or {}
            rows.append(
                {
                    "id": item["id"],
                    "ticket_id": item["ticket_id"],
                    "review_status": enum_label(item["review_status"]),
                    "risk_level": enum_label(report.get("risk_level")),
                    "score": report.get("score"),
                    "need_human_review": bool_label(report.get("need_human_review")),
                    "created_at": item["created_at"],
                }
            )
        st.subheader(t("latest_reports"))
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        show_response_error(response)

    st.divider()
    st.subheader(t("backups"))
    include_uploads = st.checkbox(t("include_uploads"), value=True)
    include_chroma = st.checkbox(t("include_chroma"), value=False)
    if st.button(t("create_backup")):
        response = requests.post(
            api_url("/api/admin/backups"),
            json={"include_uploads": include_uploads, "include_chroma": include_chroma},
            headers=api_headers(),
            timeout=120,
        )
        if response.ok:
            st.success(t("saved"))
            st.json(response.json(), expanded=False)
        else:
            show_response_error(response)

    backups_response = requests.get(
        api_url("/api/admin/backups"),
        headers=api_headers(),
        timeout=20,
    )
    if backups_response.ok:
        backups = backups_response.json()
        st.dataframe(pd.DataFrame(backups), use_container_width=True, hide_index=True)
        for backup in backups[:5]:
            if st.button(
                f"{t('verify_backup')}: {backup['filename']}",
                key=f"verify_backup_{backup['id']}",
            ):
                verify_response = requests.get(
                    api_url(f"/api/admin/backups/{backup['id']}/verify"),
                    headers=api_headers(),
                    timeout=120,
                )
                if verify_response.ok:
                    st.json(verify_response.json())
                else:
                    show_response_error(verify_response)
            if st.button(
                f"{t('restore_backup_dry_run')}: {backup['filename']}",
                key=f"restore_backup_{backup['id']}",
            ):
                restore_response = requests.post(
                    api_url(f"/api/admin/backups/{backup['id']}/restore/dry-run"),
                    headers=api_headers(),
                    timeout=120,
                )
                if restore_response.ok:
                    st.json(restore_response.json())
                else:
                    show_response_error(restore_response)
            if st.button(
                f"{t('download_backup')}: {backup['filename']}",
                key=f"prepare_backup_{backup['id']}",
            ):
                download_response = requests.get(
                    api_url(f"/api/admin/backups/{backup['id']}/download"),
                    headers=api_headers(),
                    timeout=120,
                )
                if download_response.ok:
                    st.download_button(
                        f"{t('download_backup')}: {backup['filename']}",
                        data=download_response.content,
                        file_name=backup["filename"],
                        mime="application/zip",
                        key=f"download_backup_{backup['id']}",
                    )
                else:
                    show_response_error(download_response)
    else:
        show_response_error(backups_response)
        reports = []

    default_report_id = reports[0]["id"] if reports else ""
    report_id = st.text_input(t("report_id"), value=default_report_id)
    if st.button(t("refresh_reports"), disabled=not report_id):
        response = requests.get(
            api_url(f"/api/reports/{report_id}"),
            headers=api_headers(),
            timeout=20,
        )
        if response.ok:
            st.session_state["review_report"] = response.json()
        else:
            show_response_error(response)

    report = st.session_state.get("review_report")
    if report and report.get("id") == report_id:
        st.json(report, expanded=False)

    decision = st.selectbox(
        t("review_decision"),
        REVIEW_DECISION_OPTIONS,
        format_func=enum_label,
    )
    review_comment = st.text_area(t("review_comment"), height=100)
    if st.button(t("submit_review"), disabled=not report_id):
        response = requests.patch(
            api_url(f"/api/reports/{report_id}/review"),
            json={"review_status": decision, "review_comment": review_comment or None},
            headers=api_headers(),
            timeout=20,
        )
        if response.ok:
            st.session_state["review_report"] = response.json()
            st.success(t("saved"))
            st.json(response.json(), expanded=False)
        else:
            show_response_error(response)

with operations_tab:
    security_col, metrics_col = st.columns([1, 1])
    with security_col:
        st.subheader(t("security_status"))
        if st.button(t("refresh_security_status")):
            st.session_state["refresh_security_status"] = True
        response = requests.get(
            api_url("/api/admin/security/status"),
            headers=api_headers(),
            timeout=20,
        )
        if response.ok:
            security = response.json()
            c1, c2, c3 = st.columns(3)
            c1.metric(t("status"), enum_label(security["status"]))
            c2.metric(t("app_env"), security["app_env"])
            c3.metric(t("production_ready"), bool_label(security["production_ready"]))
            warnings = security.get("warnings") or []
            if warnings:
                st.warning(f"{t('warnings')}: {len(warnings)}")
                st.dataframe(
                    pd.DataFrame({t("warning"): warnings}),
                    use_container_width=True,
                    hide_index=True,
                )
            controls = security.get("controls") or {}
            st.caption(t("controls"))
            st.dataframe(
                pd.DataFrame(
                    [{t("control"): key, t("value"): str(value)} for key, value in controls.items()]
                ),
                use_container_width=True,
                hide_index=True,
            )
            st.json(security, expanded=False)
        else:
            show_response_error(response)

    with metrics_col:
        st.subheader(t("runtime_metrics"))
        if st.button(t("refresh_metrics")):
            st.session_state["refresh_metrics"] = True
        response = requests.get(api_url("/metrics"), headers=api_headers(), timeout=20)
        if response.ok:
            metrics = response.json()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric(t("documents"), metrics.get("documents_total", 0))
            c2.metric(t("chunks_indexed"), metrics.get("chunks_total", 0))
            c3.metric(t("pending_review"), metrics.get("reports_pending_review", 0))
            c4.metric(t("quarantined"), metrics.get("documents_quarantined", 0))
            c5, c6, c7, c8 = st.columns(4)
            c5.metric(t("latest_reports"), metrics.get("reports_total", 0))
            c6.metric(t("audit_events"), metrics.get("audit_events_total", 0))
            c7.metric("HTTP", metrics.get("http_requests_total", 0))
            c8.metric("HTTP 429", metrics.get("http_rate_limited_total", 0))
            st.dataframe(
                pd.DataFrame(
                    [{t("metric"): key, t("value"): value} for key, value in metrics.items()]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            show_response_error(response)

    st.divider()
    audit_col, retention_col = st.columns([1, 1])
    with audit_col:
        st.subheader(t("audit_chain"))
        if st.button(t("verify_audit_chain")):
            response = requests.get(
                api_url("/api/audit-events/verify"),
                headers=api_headers(),
                timeout=20,
            )
            if response.ok:
                audit = response.json()
                c1, c2, c3 = st.columns(3)
                c1.metric(t("status"), bool_label(audit["valid"]))
                c2.metric(t("audit_events"), audit["total_events"])
                c3.metric(t("tampered"), audit["tampered_events"])
                st.json(audit, expanded=False)
            else:
                show_response_error(response)

        response = requests.get(
            api_url("/api/audit-events"),
            params={"limit": 50},
            headers=api_headers(),
            timeout=20,
        )
        if response.ok:
            audit_events = response.json()
            st.dataframe(pd.DataFrame(audit_events), use_container_width=True, hide_index=True)
        else:
            show_response_error(response)

    with retention_col:
        st.subheader(t("retention_purge"))
        data_older_than_days = st.number_input(
            t("data_older_than_days"),
            min_value=1,
            max_value=3650,
            value=30,
            step=1,
        )
        audit_older_than_days = st.number_input(
            t("audit_older_than_days"),
            min_value=1,
            max_value=3650,
            value=180,
            step=1,
        )
        include_audit = st.checkbox(t("include_audit"), value=False)
        dry_run = st.checkbox(t("dry_run"), value=True, key="retention_dry_run")
        if st.button(t("run_retention_purge")):
            response = requests.post(
                api_url("/api/admin/retention/purge"),
                json={
                    "data_older_than_days": data_older_than_days,
                    "audit_older_than_days": audit_older_than_days,
                    "include_audit": include_audit,
                    "dry_run": dry_run,
                },
                headers=api_headers(),
                timeout=120,
            )
            if response.ok:
                st.success(t("saved"))
                st.json(response.json(), expanded=False)
            else:
                show_response_error(response)

with logs_tab:
    error_only = st.checkbox(t("error_only"))
    response = requests.get(
        api_url("/api/logs"),
        params={"limit": 100, "error_only": error_only},
        headers=api_headers(),
        timeout=20,
    )
    if response.ok:
        logs = response.json()
        st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
        if logs:
            buffer = io.StringIO()
            pd.DataFrame(logs).to_csv(buffer, index=False)
            st.download_button(
                t("download_logs"),
                data=buffer.getvalue().encode("utf-8-sig"),
                file_name="serviceguard_logs.csv",
                mime="text/csv",
            )
    else:
        show_response_error(response)
