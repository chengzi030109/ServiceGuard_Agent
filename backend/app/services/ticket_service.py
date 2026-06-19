import csv
import hashlib
import io
import json
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from backend.app.core.config import get_settings
from backend.app.core.database import get_database
from backend.app.core.security import can_view_owned_resource
from backend.app.schemas.common import Citation, RetrievedChunk
from backend.app.schemas.ticket import (
    BatchInspectResponse,
    BatchJobRecord,
    BatchTicketResult,
    QualityReport,
    TicketInspectResponse,
    Violation,
)
from backend.app.services.llm_client import LLMClient
from backend.app.services.privacy import get_privacy_redactor
from backend.app.services.rag_service import get_rag_service


class BatchJobCanceled(Exception):
    def __init__(self, result: BatchInspectResponse):
        super().__init__("Batch job was canceled")
        self.result = result


class BatchJobTimedOut(Exception):
    def __init__(self, result: BatchInspectResponse):
        super().__init__("Batch job exceeded timeout")
        self.result = result


class BatchJobCapacityExceeded(Exception):
    """Raised when active background batch jobs exceed configured limits."""


class IdempotencyConflict(Exception):
    """Raised when a client reuses an Idempotency-Key for different content."""


class TicketService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.db = get_database()
        self.rag = get_rag_service()
        self.llm = LLMClient(self.settings)
        self.privacy = get_privacy_redactor()

    def inspect_ticket(
        self,
        ticket_text: str,
        channel: str = "demo",
        top_k: int | None = None,
        actor_role: str = "dev",
        actor_hash: str = "auth-disabled",
    ) -> TicketInspectResponse:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        ticket_id = f"ticket_{uuid.uuid4().hex[:12]}"
        start = time.perf_counter()
        safe_ticket_text = self.privacy.redact_text(ticket_text)
        chunks = self.rag.search(safe_ticket_text, top_k or self.settings.top_k)
        llm_result = self.llm.inspect_ticket_with_schema(safe_ticket_text, chunks, ticket_id)
        error: str | None = None

        report = None
        if llm_result and llm_result.content and llm_result.content != "{}":
            try:
                report = QualityReport.model_validate_json(llm_result.content)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                error = f"schema_validation_failed: {exc}"

        if report is None:
            report = self._local_rule_report(ticket_id, safe_ticket_text, chunks)

        report = self._verify_report(report, chunks)
        report = self.privacy.redact_model(report, QualityReport)
        report_id = f"report_{uuid.uuid4().hex[:12]}"
        self.db.save_report(
            report_id,
            ticket_id,
            safe_ticket_text,
            report.model_dump(),
            actor_role=actor_role,
            actor_hash=actor_hash,
            review_status="pending" if report.need_human_review else "not_required",
        )

        latency_ms = int((time.perf_counter() - start) * 1000)
        self.db.save_llm_log(
            log_id=f"log_{uuid.uuid4().hex[:12]}",
            request_id=request_id,
            model=llm_result.model if llm_result else "local-fallback",
            prompt_version=self.settings.prompt_version,
            latency_ms=llm_result.latency_ms if llm_result else latency_ms,
            input_tokens=llm_result.input_tokens if llm_result else 0,
            output_tokens=llm_result.output_tokens if llm_result else 0,
            total_tokens=llm_result.total_tokens if llm_result else 0,
            tool_calls=[
                "search_policy_docs",
                "audit_ticket",
                "verify_citations",
                f"channel:{channel}",
            ],
            error=error or (llm_result.error if llm_result else None),
        )
        return TicketInspectResponse(report_id=report_id, request_id=request_id, report=report)

    def batch_inspect_csv(
        self,
        csv_bytes: bytes,
        top_k: int | None = None,
        *,
        actor_role: str = "dev",
        actor_hash: str = "auth-disabled",
        cancel_check: Callable[[], bool] | None = None,
        timeout_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[BatchInspectResponse], None] | None = None,
    ) -> BatchInspectResponse:
        text = csv_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV must contain headers")

        text_field = self._select_text_field(reader.fieldnames)
        rows = list(reader)
        if self.settings.max_batch_rows > 0 and len(rows) > self.settings.max_batch_rows:
            raise ValueError(
                f"CSV row count {len(rows)} exceeds MAX_BATCH_ROWS={self.settings.max_batch_rows}"
            )
        results: list[BatchTicketResult] = []
        total_rows = len(rows)
        for row_number, row in enumerate(rows, start=1):
            if cancel_check and cancel_check():
                raise BatchJobCanceled(self._batch_response(total_rows, results))
            if timeout_check and timeout_check():
                raise BatchJobTimedOut(self._batch_response(total_rows, results))
            raw_text = (row.get(text_field) or "").strip()
            ticket_id = row.get("ticket_id") or row.get("id") or f"row_{row_number}"
            if not raw_text:
                results.append(
                    BatchTicketResult(
                        row_number=row_number,
                        ticket_id=ticket_id,
                        ok=False,
                        error=f"Missing text in column {text_field}",
                    )
                )
                if progress_callback:
                    progress_callback(self._batch_response(total_rows, results))
                continue
            try:
                response = self.inspect_ticket(
                    raw_text,
                    channel="batch_csv",
                    top_k=top_k,
                    actor_role=actor_role,
                    actor_hash=actor_hash,
                )
                results.append(
                    BatchTicketResult(
                        row_number=row_number,
                        ticket_id=ticket_id,
                        ok=True,
                        report_id=response.report_id,
                        report=response.report,
                    )
                )
            except Exception as exc:
                results.append(
                    BatchTicketResult(
                        row_number=row_number,
                        ticket_id=ticket_id,
                        ok=False,
                        error=str(exc),
                    )
                )
            if progress_callback:
                progress_callback(self._batch_response(total_rows, results))
        return self._batch_response(total_rows, results)

    def create_batch_job(
        self,
        *,
        actor_role: str = "dev",
        actor_hash: str = "auth-disabled",
    ) -> BatchJobRecord:
        self._enforce_batch_job_capacity(actor_hash)
        job_id = f"batch_{uuid.uuid4().hex[:12]}"
        self.db.create_batch_job(job_id, actor_role=actor_role, actor_hash=actor_hash)
        return BatchJobRecord(**self.db.get_batch_job(job_id))  # type: ignore[arg-type]

    def create_or_reuse_batch_job(
        self,
        csv_bytes: bytes,
        *,
        top_k: int | None = None,
        actor_role: str = "dev",
        actor_hash: str = "auth-disabled",
        idempotency_key: str | None = None,
    ) -> tuple[BatchJobRecord, bool]:
        normalized_key = self._normalize_idempotency_key(idempotency_key)
        if not normalized_key:
            return self.create_batch_job(actor_role=actor_role, actor_hash=actor_hash), True

        job_id = f"batch_{uuid.uuid4().hex[:12]}"
        request_hash = self._batch_job_request_hash(csv_bytes, top_k)
        try:
            existing_job = self.db.get_idempotent_batch_job(
                actor_hash=actor_hash,
                idempotency_key=normalized_key,
                request_hash=request_hash,
            )
            if existing_job:
                return BatchJobRecord(**existing_job), False

            self._enforce_batch_job_capacity(actor_hash)
            job, created = self.db.create_batch_job_with_idempotency(
                job_id,
                actor_role=actor_role,
                actor_hash=actor_hash,
                idempotency_key=normalized_key,
                request_hash=request_hash,
            )
        except ValueError as exc:
            raise IdempotencyConflict(str(exc)) from exc
        except BatchJobCapacityExceeded:
            try:
                existing_job = self.db.get_idempotent_batch_job(
                    actor_hash=actor_hash,
                    idempotency_key=normalized_key,
                    request_hash=request_hash,
                )
            except ValueError as exc:
                raise IdempotencyConflict(str(exc)) from exc
            if existing_job:
                return BatchJobRecord(**existing_job), False
            raise
        return BatchJobRecord(**job), created

    def run_batch_job(
        self,
        job_id: str,
        csv_bytes: bytes,
        top_k: int | None = None,
        actor_role: str = "dev",
        actor_hash: str = "auth-disabled",
    ) -> None:
        if self._is_batch_job_canceled(job_id):
            return
        self.db.update_batch_job(job_id, status="running")
        deadline = time.monotonic() + self.settings.batch_job_timeout_seconds
        try:
            result = self.batch_inspect_csv(
                csv_bytes,
                top_k=top_k,
                actor_role=actor_role,
                actor_hash=actor_hash,
                cancel_check=lambda: self._is_batch_job_canceled(job_id),
                timeout_check=lambda: time.monotonic() >= deadline,
                progress_callback=lambda progress: self._save_batch_job_progress(
                    job_id,
                    progress,
                ),
            )
            if self._is_batch_job_canceled(job_id):
                self._save_canceled_batch_job(job_id, result)
                return
            self.db.update_batch_job(
                job_id,
                status="succeeded",
                total=result.total,
                succeeded=result.succeeded,
                failed=result.failed,
                result=result.model_dump(),
            )
        except BatchJobCanceled as exc:
            self._save_canceled_batch_job(job_id, exc.result)
        except BatchJobTimedOut as exc:
            self._save_timed_out_batch_job(job_id, exc.result)
        except Exception as exc:
            if self._is_batch_job_canceled(job_id):
                empty_result = BatchInspectResponse(
                    total=0,
                    succeeded=0,
                    failed=0,
                    results=[],
                )
                self._save_canceled_batch_job(job_id, empty_result)
                return
            self.db.update_batch_job(
                job_id,
                status="failed",
                error=str(exc),
            )

    def get_batch_job(
        self,
        job_id: str,
        *,
        requester_role: str = "dev",
        requester_hash: str = "auth-disabled",
    ) -> BatchJobRecord | None:
        data = self.db.get_batch_job(job_id)
        if not data or not self._can_view_batch_job(data, requester_role, requester_hash):
            return None
        return BatchJobRecord(**data) if data else None

    def list_batch_jobs(
        self,
        limit: int = 100,
        *,
        requester_role: str = "dev",
        requester_hash: str = "auth-disabled",
    ) -> list[BatchJobRecord]:
        actor_hash = (
            None
            if self._can_view_all_batch_jobs(requester_role, requester_hash)
            else requester_hash
        )
        return [
            BatchJobRecord(**item)
            for item in self.db.list_batch_jobs(limit=limit, actor_hash=actor_hash)
        ]

    def cancel_batch_job(
        self,
        job_id: str,
        *,
        requester_role: str = "dev",
        requester_hash: str = "auth-disabled",
    ) -> BatchJobRecord | None:
        data = self.db.get_batch_job(job_id)
        if not data or not self._can_view_batch_job(data, requester_role, requester_hash):
            return None
        if data.get("status") in {"pending", "running"}:
            self.db.cancel_batch_job(job_id)
            data = self.db.get_batch_job(job_id)
        return BatchJobRecord(**data) if data else None

    def _batch_response(
        self,
        total_rows: int,
        results: list[BatchTicketResult],
    ) -> BatchInspectResponse:
        succeeded = sum(1 for item in results if item.ok)
        failed = sum(1 for item in results if not item.ok)
        return BatchInspectResponse(
            total=total_rows,
            succeeded=succeeded,
            failed=failed,
            results=results,
        )

    def _is_batch_job_canceled(self, job_id: str) -> bool:
        job = self.db.get_batch_job(job_id)
        return bool(job and job.get("status") == "canceled")

    def _save_batch_job_progress(self, job_id: str, result: BatchInspectResponse) -> None:
        if self._is_batch_job_canceled(job_id):
            return
        self.db.update_batch_job(
            job_id,
            status="running",
            total=result.total,
            succeeded=result.succeeded,
            failed=result.failed,
            result=result.model_dump(),
        )

    def _save_canceled_batch_job(self, job_id: str, result: BatchInspectResponse) -> None:
        self.db.update_batch_job(
            job_id,
            status="canceled",
            total=result.total,
            succeeded=result.succeeded,
            failed=result.failed,
            result=result.model_dump(),
            error="Canceled by requester",
        )

    def _save_timed_out_batch_job(self, job_id: str, result: BatchInspectResponse) -> None:
        self.db.update_batch_job(
            job_id,
            status="timed_out",
            total=result.total,
            succeeded=result.succeeded,
            failed=result.failed,
            result=result.model_dump(),
            error="Batch job exceeded timeout",
        )

    def _can_view_batch_job(
        self,
        job: dict[str, Any],
        requester_role: str,
        requester_hash: str,
    ) -> bool:
        if self._can_view_all_batch_jobs(requester_role, requester_hash):
            return True
        return job.get("actor_hash") == requester_hash

    def _can_view_all_batch_jobs(self, requester_role: str, requester_hash: str) -> bool:
        return can_view_owned_resource(
            requester_role,
            requester_hash,
            owner_hash="__global__",
        )

    def _normalize_idempotency_key(self, idempotency_key: str | None) -> str | None:
        if idempotency_key is None:
            return None
        normalized = idempotency_key.strip()
        if not normalized:
            return None
        if len(normalized) > 200:
            raise ValueError("Idempotency-Key must be at most 200 characters")
        return normalized

    def _enforce_batch_job_capacity(self, actor_hash: str) -> None:
        global_limit = self.settings.max_active_batch_jobs
        actor_limit = self.settings.max_active_batch_jobs_per_actor
        global_active = self.db.active_batch_job_count()
        if global_limit > 0 and global_active >= global_limit:
            raise BatchJobCapacityExceeded(
                "Too many active batch jobs. Try again after existing jobs finish."
            )

        actor_active = self.db.active_batch_job_count(actor_hash=actor_hash)
        if actor_limit > 0 and actor_active >= actor_limit:
            raise BatchJobCapacityExceeded(
                "Too many active batch jobs for this requester. "
                "Try again after existing jobs finish."
            )

    def _batch_job_request_hash(self, csv_bytes: bytes, top_k: int | None) -> str:
        effective_top_k = top_k or self.settings.top_k
        digest = hashlib.sha256()
        digest.update(b"serviceguard.batch_job.v1\0")
        digest.update(str(effective_top_k).encode("utf-8"))
        digest.update(b"\0")
        digest.update(csv_bytes)
        return digest.hexdigest()

    def _select_text_field(self, fieldnames: list[str]) -> str:
        candidates = ["ticket_text", "raw_text", "conversation", "text", "工单内容", "客服对话"]
        for candidate in candidates:
            if candidate in fieldnames:
                return candidate
        return fieldnames[0]

    def _local_rule_report(
        self,
        ticket_id: str,
        ticket_text: str,
        chunks: list[RetrievedChunk],
    ) -> QualityReport:
        citations = [self._citation_from_chunk(chunk) for chunk in chunks]
        violations: list[Violation] = []
        agent_text = self._agent_text(ticket_text)

        rule_specs = [
            {
                "type": "over_promise",
                "severity": "high",
                "patterns": [
                    r"一定",
                    r"保证",
                    r"百分之百",
                    r"100%",
                    r"必定",
                    r"马上退款",
                    r"全额退款",
                ],
                "policy_terms": ["承诺", "退款", "赔付", "核验"],
                "explanation": "客服在未完成政策要求的核验前做出了确定性承诺。",
                "fix": "先核验订单、支付、物流和售后条件，再给出可执行方案，避免绝对化承诺。",
                "skip_when_protective": True,
            },
            {
                "type": "process_missing",
                "severity": "medium",
                "patterns": [
                    r"不用核验",
                    r"不需要核验",
                    r"不用看订单",
                    r"不用看物流",
                    r"直接退",
                    r"跳过",
                ],
                "policy_terms": ["核验", "订单", "物流", "流程", "凭证"],
                "explanation": "客服疑似跳过订单、物流、凭证等必要流程。",
                "fix": "按 SOP 逐项核验订单状态、售后期限、物流和凭证，再处理诉求。",
            },
            {
                "type": "privacy_risk",
                "severity": "high",
                "patterns": [r"密码", r"验证码", r"完整身份证", r"银行卡密码", r"身份证正反面"],
                "policy_terms": ["隐私", "验证码", "密码", "身份证", "银行卡"],
                "explanation": "客服索取或诱导提供高风险隐私信息。",
                "fix": "只收集必要信息，并通过安全渠道进行身份核验，不索取密码或验证码。",
                "skip_when_protective": True,
            },
            {
                "type": "attitude_issue",
                "severity": "medium",
                "patterns": [r"你自己", r"别烦", r"不归我管", r"爱投诉", r"随便你"],
                "policy_terms": ["礼貌", "态度", "服务", "沟通"],
                "explanation": "客服表达存在态度风险，可能引发投诉升级。",
                "fix": "使用礼貌、共情、可执行的话术，说明当前能处理的下一步。",
            },
            {
                "type": "policy_conflict",
                "severity": "high",
                "patterns": [r"过期也能退", r"售后期外.*退", r"无需凭证.*赔"],
                "policy_terms": ["售后", "期限", "凭证", "政策"],
                "explanation": "客服表述可能与售后政策或凭证要求冲突。",
                "fix": "明确售后期限和凭证要求，对不确定情况升级人工复核。",
                "skip_when_protective": True,
            },
        ]

        for spec in rule_specs:
            evidence = self._first_match(agent_text, spec["patterns"])
            if not evidence:
                continue
            if spec.get("skip_when_protective") and self._is_protective_statement(evidence):
                continue
            matched_citations = self._match_policy_citations(chunks, spec["policy_terms"])
            violations.append(
                Violation(
                    type=spec["type"],  # type: ignore[arg-type]
                    severity=spec["severity"],  # type: ignore[arg-type]
                    evidence_from_ticket=evidence,
                    policy_citation_ids=[chunk.chunk_id for chunk in matched_citations[:2]],
                    explanation=spec["explanation"],
                    fix_suggestion=spec["fix"],
                )
            )

        score = self._score(violations)
        missing_info = []
        if not chunks:
            missing_info.append("知识库未检索到相关政策片段")
        if any(not violation.policy_citation_ids for violation in violations):
            missing_info.append("部分违规结论缺少可引用的政策依据")

        risk_level = self._risk_level(score, violations)
        summary = self._summary(agent_text, violations)
        suggested_reply = self._suggested_reply(violations)
        confidence = 0.85 if violations and not missing_info else 0.65 if chunks else 0.35
        if not violations and chunks:
            confidence = 0.72

        return QualityReport(
            ticket_id=ticket_id,
            score=score,
            risk_level=risk_level,
            summary=summary,
            violations=violations,
            citations=citations,
            suggested_reply=suggested_reply,
            need_human_review=bool(missing_info) or risk_level == "high",
            confidence=confidence,
            missing_info=missing_info,
        )

    def _verify_report(self, report: QualityReport, chunks: list[RetrievedChunk]) -> QualityReport:
        valid_ids = {chunk.chunk_id for chunk in chunks}
        missing_info = list(report.missing_info)
        verified_violations: list[Violation] = []
        for violation in report.violations:
            citation_ids = [
                chunk_id for chunk_id in violation.policy_citation_ids if chunk_id in valid_ids
            ]
            if not citation_ids:
                if "部分违规结论缺少可引用的政策依据" not in missing_info:
                    missing_info.append("部分违规结论缺少可引用的政策依据")
            verified_violations.append(
                violation.model_copy(update={"policy_citation_ids": citation_ids})
            )

        citations_by_id = {chunk.chunk_id: self._citation_from_chunk(chunk) for chunk in chunks}
        used_ids = {
            chunk_id
            for violation in verified_violations
            for chunk_id in violation.policy_citation_ids
        }
        citations = [
            citations_by_id[chunk_id] for chunk_id in used_ids if chunk_id in citations_by_id
        ]
        if not citations:
            citations = [self._citation_from_chunk(chunk) for chunk in chunks]

        need_human_review = report.need_human_review or bool(missing_info)
        confidence = min(report.confidence, 0.68) if missing_info else report.confidence
        return report.model_copy(
            update={
                "violations": verified_violations,
                "citations": citations,
                "need_human_review": need_human_review,
                "confidence": confidence,
                "missing_info": missing_info,
            }
        )

    def _match_policy_citations(
        self,
        chunks: list[RetrievedChunk],
        terms: list[str],
    ) -> list[RetrievedChunk]:
        scored: list[tuple[int, RetrievedChunk]] = []
        for chunk in chunks:
            score = sum(1 for term in terms if term in chunk.text)
            if score:
                scored.append((score, chunk))
        scored.sort(key=lambda item: (item[0], item[1].similarity), reverse=True)
        return [chunk for _, chunk in scored] or chunks[:1]

    def _first_match(self, text: str, patterns: list[str]) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                start = max(0, match.start() - 28)
                end = min(len(text), match.end() + 28)
                return text[start:end].strip()
        return None

    def _agent_text(self, ticket_text: str) -> str:
        markers = ["客服：", "客服:", "agent:", "Agent:"]
        for marker in markers:
            if marker in ticket_text:
                return ticket_text.split(marker, maxsplit=1)[1].strip()
        return ticket_text

    def _is_protective_statement(self, evidence: str) -> bool:
        protective_terms = ["不要", "不会", "不能", "不得", "请勿", "无法", "不可以", "需要先"]
        return any(term in evidence for term in protective_terms)

    def _score(self, violations: list[Violation]) -> int:
        penalties = {"high": 30, "medium": 18, "low": 10}
        return max(0, 100 - sum(penalties[item.severity] for item in violations))

    def _risk_level(self, score: int, violations: list[Violation]) -> str:
        if any(item.severity == "high" for item in violations) or score <= 60:
            return "high"
        if violations or score <= 82:
            return "medium"
        return "low"

    def _summary(self, ticket_text: str, violations: list[Violation]) -> str:
        if not violations:
            return "未发现明确违规风险，仍建议人工抽检关键承诺与隐私信息。"
        types = "、".join(sorted({item.type for item in violations}))
        short_text = ticket_text[:60].replace("\n", " ")
        return f"该工单疑似存在 {types} 风险；原文片段：{short_text}"

    def _suggested_reply(self, violations: list[Violation]) -> str:
        if not violations:
            return (
                "您好，我们已收到您的问题。我们会根据订单状态、售后期限和相关凭证"
                "为您核验，并给出符合政策的处理方案。"
            )
        return (
            "您好，我们理解您的诉求。为确保处理结果准确，请先提供订单号和必要凭证，"
            "我们会核验订单状态、售后期限和物流情况，再根据平台政策给出可执行方案。"
            "如当前信息不足，我们会为您升级人工复核。"
        )

    def _citation_from_chunk(self, chunk: RetrievedChunk) -> Citation:
        return Citation(
            chunk_id=chunk.chunk_id,
            document_name=chunk.document_name,
            source_text=chunk.text[:500],
            similarity=chunk.similarity,
        )


def quality_report_to_eval_row(
    report: QualityReport,
    expected_risk: str | None = None,
) -> dict[str, Any]:
    violation_types = sorted({violation.type for violation in report.violations})
    citation_count = sum(len(violation.policy_citation_ids) for violation in report.violations)
    return {
        "ticket_id": report.ticket_id,
        "score": report.score,
        "risk_level": report.risk_level,
        "violation_types": ",".join(violation_types),
        "need_human_review": report.need_human_review,
        "confidence": report.confidence,
        "citation_count": citation_count,
        "expected_risk": expected_risk,
        "risk_match": expected_risk is None or report.risk_level == expected_risk,
    }


def get_ticket_service() -> TicketService:
    return TicketService()
