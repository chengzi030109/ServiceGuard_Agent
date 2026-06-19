import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class SmokeCheck:
    name: str
    ok: bool
    status_code: int | None = None
    latency_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def run_smoke_test(
    *,
    base_url: str,
    api_key: str = "",
    admin_api_key: str = "",
    timeout: float = 10.0,
    include_admin: bool = True,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    client = session or requests.Session()
    base_url = base_url.rstrip("/")
    user_headers = _auth_headers(api_key)
    admin_headers = _auth_headers(admin_api_key or api_key)
    checks: list[SmokeCheck] = []

    health = _get_json(client, f"{base_url}/health", headers=user_headers, timeout=timeout)
    checks.append(
        _expect(
            "health",
            health,
            lambda payload: payload.get("status") == "ok",
            {"status": health.payload.get("status") if health.payload else None},
        )
    )

    ready = _get_json(client, f"{base_url}/ready", headers=user_headers, timeout=timeout)
    checks.append(
        _expect(
            "readiness",
            ready,
            lambda payload: (
                payload.get("status") == "ready"
                and payload.get("database") == "ok"
                and payload.get("vector_store") == "ok"
                and payload.get("database_quick_check_ok") is not False
            ),
            {
                "status": ready.payload.get("status") if ready.payload else None,
                "database": ready.payload.get("database") if ready.payload else None,
                "vector_store": ready.payload.get("vector_store") if ready.payload else None,
                "database_quick_check_ok": (
                    ready.payload.get("database_quick_check_ok") if ready.payload else None
                ),
            },
        )
    )

    metrics = _get_json(client, f"{base_url}/metrics", headers=user_headers, timeout=timeout)
    checks.append(
        _expect(
            "metrics-json",
            metrics,
            lambda payload: (
                "documents_total" in payload
                and "reports_total" in payload
                and payload.get("database_schema_pending_migrations") == 0
                and payload.get("database_sqlite_quick_check_ok") == 1
            ),
            {
                "documents_total": metrics.payload.get("documents_total")
                if metrics.payload
                else None,
                "reports_total": metrics.payload.get("reports_total") if metrics.payload else None,
                "database_schema_pending_migrations": (
                    metrics.payload.get("database_schema_pending_migrations")
                    if metrics.payload
                    else None
                ),
                "database_sqlite_quick_check_ok": (
                    metrics.payload.get("database_sqlite_quick_check_ok")
                    if metrics.payload
                    else None
                ),
            },
        )
    )

    prometheus = _get_text(
        client,
        f"{base_url}/metrics/prometheus",
        headers=user_headers,
        timeout=timeout,
    )
    checks.append(
        _expect_text(
            "metrics-prometheus",
            prometheus,
            [
                "serviceguard_reports_total",
                "serviceguard_database_schema_pending_migrations",
                "serviceguard_database_sqlite_quick_check_ok",
            ],
        )
    )

    search = _post_json(
        client,
        f"{base_url}/api/search",
        headers=user_headers,
        timeout=timeout,
        json_body={"query": "退款 核验 售后", "top_k": 1},
    )
    checks.append(
        _expect(
            "rag-search",
            search,
            lambda payload: isinstance(payload.get("results"), list),
            {"result_count": len(search.payload.get("results", [])) if search.payload else None},
        )
    )

    inspect_payload = {
        "ticket_text": "客户：我要退款。客服：我保证给您全额退款，不用核验订单。",
        "top_k": 3,
        "channel": "smoke",
    }
    inspect = _post_json(
        client,
        f"{base_url}/api/tickets/inspect",
        headers=user_headers,
        timeout=timeout,
        json_body=inspect_payload,
    )
    report_id = inspect.payload.get("report_id") if inspect.payload else None
    report = inspect.payload.get("report", {}) if inspect.payload else {}
    checks.append(
        _expect(
            "ticket-inspect",
            inspect,
            lambda payload: (
                payload.get("report_id")
                and payload.get("request_id")
                and payload.get("report", {}).get("risk_level") == "high"
                and len(payload.get("report", {}).get("violations", [])) >= 1
            ),
            {
                "report_id": report_id,
                "risk_level": report.get("risk_level"),
                "violation_count": len(report.get("violations", [])) if report else None,
                "citation_count": len(report.get("citations", [])) if report else None,
            },
        )
    )

    if report_id:
        report_fetch = _get_json(
            client,
            f"{base_url}/api/reports/{report_id}",
            headers=user_headers,
            timeout=timeout,
        )
        checks.append(
            _expect(
                "report-fetch",
                report_fetch,
                lambda payload: payload.get("id") == report_id,
                {"report_id": report_fetch.payload.get("id") if report_fetch.payload else None},
            )
        )
    else:
        checks.append(
            SmokeCheck(
                name="report-fetch",
                ok=False,
                error="ticket-inspect produced no report_id",
            )
        )

    if include_admin:
        security_status = _get_json(
            client,
            f"{base_url}/api/admin/security/status",
            headers=admin_headers,
            timeout=timeout,
        )
        checks.append(
            _expect(
                "admin-security-status",
                security_status,
                lambda payload: (
                    payload.get("status") in {"ready", "warning"}
                    and "controls" in payload
                    and "audit_chain" in payload
                ),
                {
                    "status": security_status.payload.get("status")
                    if security_status.payload
                    else None,
                    "production_ready": (
                        security_status.payload.get("production_ready")
                        if security_status.payload
                        else None
                    ),
                },
            )
        )

        audit_verify = _get_json(
            client,
            f"{base_url}/api/audit-events/verify",
            headers=admin_headers,
            timeout=timeout,
        )
        checks.append(
            _expect(
                "audit-chain-verify",
                audit_verify,
                lambda payload: (
                    payload.get("valid") is True and payload.get("tampered_events") == 0
                ),
                {
                    "valid": audit_verify.payload.get("valid") if audit_verify.payload else None,
                    "tampered_events": (
                        audit_verify.payload.get("tampered_events")
                        if audit_verify.payload
                        else None
                    ),
                },
            )
        )

        audit_anchor = _post_json(
            client,
            f"{base_url}/api/admin/audit-anchors",
            headers=admin_headers,
            timeout=timeout,
            json_body={},
        )
        anchor_id = audit_anchor.payload.get("id") if audit_anchor.payload else None
        checks.append(
            _expect(
                "audit-anchor-create",
                audit_anchor,
                lambda payload: (
                    payload.get("id")
                    and payload.get("event_count", 0) >= 1
                    and payload.get("chain_valid_at_anchor") is True
                    and payload.get("manifest_sha256")
                ),
                {
                    "anchor_id": anchor_id,
                    "event_count": (
                        audit_anchor.payload.get("event_count") if audit_anchor.payload else None
                    ),
                    "chain_valid_at_anchor": (
                        audit_anchor.payload.get("chain_valid_at_anchor")
                        if audit_anchor.payload
                        else None
                    ),
                },
            )
        )

        if anchor_id:
            anchor_verify = _get_json(
                client,
                f"{base_url}/api/admin/audit-anchors/{anchor_id}/verify",
                headers=admin_headers,
                timeout=timeout,
            )
            checks.append(
                _expect(
                    "audit-anchor-verify",
                    anchor_verify,
                    lambda payload: (
                        payload.get("valid") is True
                        and payload.get("checks", {}).get("manifest_sha256_valid") is True
                        and payload.get("checks", {}).get("current_audit_prefix_matches_anchor")
                        is True
                    ),
                    {
                        "anchor_id": anchor_id,
                        "valid": (
                            anchor_verify.payload.get("valid") if anchor_verify.payload else None
                        ),
                        "errors": (
                            anchor_verify.payload.get("errors") if anchor_verify.payload else None
                        ),
                    },
                )
            )
        else:
            checks.append(
                SmokeCheck(
                    name="audit-anchor-verify",
                    ok=False,
                    error="audit-anchor-create produced no anchor_id",
                )
            )

    passed = all(check.ok for check in checks)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "passed": passed,
        "total": len(checks),
        "failed": sum(1 for check in checks if not check.ok),
        "checks": [asdict(check) for check in checks],
    }


@dataclass
class HttpResult:
    status_code: int | None
    latency_ms: int | None
    payload: dict[str, Any] | None = None
    text: str = ""
    error: str | None = None


def _get_json(
    client: requests.Session,
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
) -> HttpResult:
    return _request_json(client, "GET", url, headers=headers, timeout=timeout)


def _post_json(
    client: requests.Session,
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    json_body: dict[str, Any],
) -> HttpResult:
    return _request_json(client, "POST", url, headers=headers, timeout=timeout, json_body=json_body)


def _request_json(
    client: requests.Session,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    json_body: dict[str, Any] | None = None,
) -> HttpResult:
    started = time.perf_counter()
    try:
        response = client.request(
            method,
            url,
            headers=headers,
            json=json_body,
            timeout=timeout,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return HttpResult(
            status_code=response.status_code,
            latency_ms=latency_ms,
            payload=payload,
            text=response.text[:1000],
        )
    except requests.RequestException as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return HttpResult(status_code=None, latency_ms=latency_ms, error=str(exc))


def _get_text(
    client: requests.Session,
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
) -> HttpResult:
    started = time.perf_counter()
    try:
        response = client.get(url, headers=headers, timeout=timeout)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return HttpResult(
            status_code=response.status_code,
            latency_ms=latency_ms,
            text=response.text,
        )
    except requests.RequestException as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return HttpResult(status_code=None, latency_ms=latency_ms, error=str(exc))


def _expect(
    name: str,
    result: HttpResult,
    predicate,
    details: dict[str, Any],
) -> SmokeCheck:
    if result.error:
        return SmokeCheck(
            name=name,
            ok=False,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            details=details,
            error=result.error,
        )
    if result.status_code != 200:
        return SmokeCheck(
            name=name,
            ok=False,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            details={**details, "response": result.text[:500]},
            error=f"expected HTTP 200, got {result.status_code}",
        )
    if result.payload is None:
        return SmokeCheck(
            name=name,
            ok=False,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            details=details,
            error="response was not JSON",
        )
    try:
        ok = bool(predicate(result.payload))
    except Exception as exc:
        return SmokeCheck(
            name=name,
            ok=False,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            details=details,
            error=f"predicate failed: {exc}",
        )
    return SmokeCheck(
        name=name,
        ok=ok,
        status_code=result.status_code,
        latency_ms=result.latency_ms,
        details=details,
        error=None if ok else "response did not satisfy smoke assertion",
    )


def _expect_text(name: str, result: HttpResult, required_fragments: list[str]) -> SmokeCheck:
    missing = [fragment for fragment in required_fragments if fragment not in result.text]
    ok = result.error is None and result.status_code == 200 and not missing
    error = result.error
    if result.status_code != 200:
        error = f"expected HTTP 200, got {result.status_code}"
    if missing:
        error = f"missing fragments: {', '.join(missing)}"
    return SmokeCheck(
        name=name,
        ok=ok,
        status_code=result.status_code,
        latency_ms=result.latency_ms,
        details={"missing": missing},
        error=error,
    )


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key} if api_key else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--admin-api-key", default="")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--skip-admin", action="store_true")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "data" / "smoke_summary.json"))
    args = parser.parse_args()

    summary = run_smoke_test(
        base_url=args.base_url,
        api_key=args.api_key,
        admin_api_key=args.admin_api_key,
        timeout=args.timeout,
        include_admin=not args.skip_admin,
    )
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
