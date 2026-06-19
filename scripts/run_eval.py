import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.document_service import get_document_service  # noqa: E402
from backend.app.services.ticket_service import (  # noqa: E402
    get_ticket_service,
    quality_report_to_eval_row,
)

RISK_LEVELS = ("low", "medium", "high")


@dataclass(frozen=True)
class EvalThresholds:
    min_risk_accuracy: float | None = None
    min_violation_accuracy: float | None = None
    min_citation_coverage: float | None = None
    min_high_risk_recall: float | None = None

    def as_dict(self) -> dict[str, float]:
        values = {
            "risk_accuracy": self.min_risk_accuracy,
            "violation_accuracy": self.min_violation_accuracy,
            "citation_coverage": self.min_citation_coverage,
            "high_risk_recall": self.min_high_risk_recall,
        }
        return {key: float(value) for key, value in values.items() if value is not None}


def ingest_sample_docs() -> None:
    service = get_document_service()
    existing = {doc.filename for doc in service.list_documents()}
    for path in (PROJECT_ROOT / "data" / "sample_docs").glob("*.md"):
        if path.name not in existing:
            service.ingest_upload(path.name, path)


def run_eval(
    tickets_path: Path,
    output_path: Path,
    *,
    report_path: Path | None = None,
    thresholds: EvalThresholds | None = None,
) -> dict[str, Any]:
    ingest_sample_docs()
    ticket_service = get_ticket_service()
    df = pd.read_csv(tickets_path)
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        case_id = _cell_text(row.get("ticket_id")) or f"row_{len(rows) + 1}"
        expected_risk = _cell_text(row.get("expected_risk"))
        expected_violation = _cell_text(row.get("expected_violation"))
        started = time.perf_counter()
        try:
            response = ticket_service.inspect_ticket(str(row["ticket_text"]), channel="eval")
            latency_ms = int((time.perf_counter() - started) * 1000)
            eval_row = quality_report_to_eval_row(
                response.report,
                expected_risk=expected_risk or None,
            )
            eval_row["ticket_id"] = case_id
            eval_row["ok"] = True
            eval_row["error"] = None
            eval_row["latency_ms"] = latency_ms
            eval_row["expected_violation"] = expected_violation
            eval_row["violation_match"] = _violation_matches(
                eval_row["violation_types"],
                expected_violation,
            )
            rows.append(eval_row)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            rows.append(
                {
                    "ticket_id": case_id,
                    "ok": False,
                    "error": str(exc),
                    "latency_ms": latency_ms,
                    "score": None,
                    "risk_level": "",
                    "violation_types": "",
                    "need_human_review": False,
                    "confidence": 0.0,
                    "citation_count": 0,
                    "expected_risk": expected_risk or None,
                    "risk_match": False if expected_risk else None,
                    "expected_violation": expected_violation,
                    "violation_match": False if expected_violation else None,
                }
            )

    summary = _build_summary(rows, tickets_path=tickets_path, thresholds=thresholds)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_format_markdown_report(summary), encoding="utf-8")
    return summary


def _build_summary(
    rows: list[dict[str, Any]],
    *,
    tickets_path: Path,
    thresholds: EvalThresholds | None = None,
) -> dict[str, Any]:
    result_df = pd.DataFrame(rows)
    total = int(len(result_df))
    rows_with_expected_risk = result_df[result_df["expected_risk"].notna()]
    rows_with_predicted_violations = result_df[result_df["violation_types"] != ""]
    rows_with_expected_violation = result_df[
        result_df["expected_violation"].notna() & (result_df["expected_violation"] != "")
    ]
    expected_high = result_df[result_df["expected_risk"] == "high"]

    summary: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(tickets_path),
        "total": total,
        "json_success_rate": _mean_bool(result_df["ok"]) if total else 0.0,
        "risk_accuracy": (
            _mean_bool(rows_with_expected_risk["risk_match"])
            if len(rows_with_expected_risk)
            else None
        ),
        "violation_accuracy": (
            _mean_bool(result_df["violation_match"])
            if "violation_match" in result_df and total
            else None
        ),
        "expected_violation_recall": (
            _mean_bool(rows_with_expected_violation["violation_match"])
            if len(rows_with_expected_violation)
            else None
        ),
        "citation_coverage": (
            float((rows_with_predicted_violations["citation_count"] > 0).mean())
            if len(rows_with_predicted_violations)
            else 1.0
        ),
        "high_risk_recall": (
            float((expected_high["risk_level"] == "high").mean()) if len(expected_high) else None
        ),
        "average_score": _safe_float_mean(result_df["score"]),
        "average_latency_ms": _safe_float_mean(result_df["latency_ms"]),
        "risk_counts": result_df["risk_level"].value_counts().to_dict(),
        "expected_risk_counts": result_df["expected_risk"].value_counts().to_dict(),
        "confusion_matrix": _confusion_matrix(result_df),
        "rows": rows,
    }
    failures = _threshold_failures(summary, thresholds or EvalThresholds())
    summary["thresholds"] = (thresholds or EvalThresholds()).as_dict()
    summary["passed"] = not failures
    summary["failures"] = failures
    return summary


def _threshold_failures(summary: dict[str, Any], thresholds: EvalThresholds) -> list[str]:
    failures: list[str] = []
    for metric, minimum in thresholds.as_dict().items():
        value = summary.get(metric)
        if value is None or float(value) < minimum:
            failures.append(f"{metric}={value} is below threshold {minimum}")
    return failures


def _format_markdown_report(summary: dict[str, Any]) -> str:
    metric_rows = [
        ("Total cases", summary["total"], None),
        ("JSON success rate", _format_metric(summary["json_success_rate"]), None),
        ("Risk accuracy", _format_metric(summary["risk_accuracy"]), "risk_accuracy"),
        ("Violation accuracy", _format_metric(summary["violation_accuracy"]), "violation_accuracy"),
        (
            "Expected violation recall",
            _format_metric(summary["expected_violation_recall"]),
            "expected_violation_recall",
        ),
        ("Citation coverage", _format_metric(summary["citation_coverage"]), "citation_coverage"),
        ("High-risk recall", _format_metric(summary["high_risk_recall"]), "high_risk_recall"),
        ("Average score", _format_metric(summary["average_score"]), None),
        ("Average latency ms", _format_metric(summary["average_latency_ms"]), None),
    ]
    thresholds = summary.get("thresholds") or {}
    lines = [
        "# ServiceGuard Evaluation Report",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Dataset: `{summary['dataset']}`",
        f"- Gate status: `{'PASS' if summary['passed'] else 'FAIL'}`",
        "",
        "## Summary",
        "",
        "| Metric | Value | Threshold |",
        "| --- | ---: | ---: |",
    ]
    for label, value, threshold_key in metric_rows:
        threshold = thresholds.get(threshold_key, "") if threshold_key else ""
        lines.append(f"| {label} | {value} | {threshold} |")

    lines.extend(
        [
            "",
            "## Confusion Matrix",
            "",
            "| Expected \\ Predicted | low | medium | high | other |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    confusion = summary.get("confusion_matrix") or {}
    for expected in RISK_LEVELS:
        row = confusion.get(expected, {})
        lines.append(
            f"| {expected} | {row.get('low', 0)} | {row.get('medium', 0)} | "
            f"{row.get('high', 0)} | {row.get('other', 0)} |"
        )

    if summary.get("failures"):
        lines.extend(["", "## Gate Failures", ""])
        lines.extend(f"- {item}" for item in summary["failures"])

    lines.extend(
        [
            "",
            "## Row Results",
            "",
            (
                "| Ticket | Expected risk | Predicted risk | Expected violation | "
                "Predicted violations | Risk match | Violation match | Citations | Latency ms |"
            ),
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary["rows"]:
        lines.append(
            "| {ticket_id} | {expected_risk} | {risk_level} | {expected_violation} | "
            "{violation_types} | {risk_match} | {violation_match} | {citation_count} | "
            "{latency_ms} |".format(
                ticket_id=row.get("ticket_id", ""),
                expected_risk=row.get("expected_risk") or "",
                risk_level=row.get("risk_level") or "",
                expected_violation=row.get("expected_violation") or "",
                violation_types=row.get("violation_types") or "",
                risk_match=row.get("risk_match"),
                violation_match=row.get("violation_match"),
                citation_count=row.get("citation_count", 0),
                latency_ms=row.get("latency_ms", 0),
            )
        )
    return "\n".join(lines) + "\n"


def _confusion_matrix(result_df: pd.DataFrame) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {}
    for expected in RISK_LEVELS:
        expected_rows = result_df[result_df["expected_risk"] == expected]
        matrix[expected] = {
            predicted: int((expected_rows["risk_level"] == predicted).sum())
            for predicted in RISK_LEVELS
        }
        matrix[expected]["other"] = int((~expected_rows["risk_level"].isin(RISK_LEVELS)).sum())
    return matrix


def _violation_matches(predicted: str, expected: str) -> bool:
    predicted_types = {item.strip() for item in predicted.split(",") if item.strip()}
    if not expected:
        return not predicted_types
    return expected in predicted_types


def _cell_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _mean_bool(values: pd.Series) -> float:
    return float(values.fillna(False).astype(bool).mean())


def _safe_float_mean(values: pd.Series) -> float | None:
    mean_value = values.dropna().mean()
    if pd.isna(mean_value):
        return None
    return float(mean_value)


def _format_metric(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tickets",
        default=str(PROJECT_ROOT / "data" / "samples" / "tickets_sample.csv"),
    )
    parser.add_argument("--out", default=str(PROJECT_ROOT / "data" / "eval_summary.json"))
    parser.add_argument("--report", default=str(PROJECT_ROOT / "data" / "eval_report.md"))
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--min-risk-accuracy", type=float)
    parser.add_argument("--min-violation-accuracy", type=float)
    parser.add_argument("--min-citation-coverage", type=float)
    parser.add_argument("--min-high-risk-recall", type=float)
    args = parser.parse_args()
    thresholds = EvalThresholds(
        min_risk_accuracy=args.min_risk_accuracy,
        min_violation_accuracy=args.min_violation_accuracy,
        min_citation_coverage=args.min_citation_coverage,
        min_high_risk_recall=args.min_high_risk_recall,
    )
    summary = run_eval(
        Path(args.tickets),
        Path(args.out),
        report_path=None if args.no_report else Path(args.report),
        thresholds=thresholds,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
