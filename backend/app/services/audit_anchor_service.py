import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings, get_settings
from backend.app.core.database import Database, get_database


class AuditAnchorService:
    """Create and verify point-in-time evidence for the audit hash chain."""

    def __init__(self, *, settings: Settings | None = None, db: Database | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = db or get_database()

    def create_anchor(self, *, actor_role: str, actor_hash: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        anchor_id = f"audit_anchor_{now.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        events = self._audit_events()
        chain = self.db.verify_audit_chain()
        first_event_created_at = events[0]["created_at"] if events else None
        last_event_created_at = events[-1]["created_at"] if events else None
        manifest = {
            "version": 1,
            "anchor_id": anchor_id,
            "created_at": now.isoformat(),
            "app": "ServiceGuard Agent",
            "created_by_role": actor_role,
            "created_by_hash": actor_hash,
            "event_count": len(events),
            "events_sha256": self._events_sha256(events),
            "first_event_created_at": first_event_created_at,
            "last_event_created_at": last_event_created_at,
            "last_event_hash": chain.get("last_event_hash"),
            "chain_verification": chain,
            "database_schema": self.db.schema_status(),
        }
        manifest["manifest_sha256"] = self._manifest_sha256(manifest)
        self._sign_manifest(manifest)

        path = self.settings.audit_anchor_path / f"{anchor_id}.json"
        self._write_json_atomic(path, manifest)
        return self._snapshot_from_manifest(path, manifest)

    def list_anchors(self) -> list[dict[str, Any]]:
        anchors = []
        for path in self.settings.audit_anchor_path.glob("audit_anchor_*.json"):
            manifest = self._read_manifest(path)
            if manifest:
                anchors.append(self._snapshot_from_manifest(path, manifest))
        anchors.sort(key=lambda item: str(item["created_at"]), reverse=True)
        return anchors

    def resolve_anchor_path(self, anchor_id: str) -> Path | None:
        requested = anchor_id.removesuffix(".json")
        for path in self.settings.audit_anchor_path.glob("audit_anchor_*.json"):
            if path.stem == requested or path.name == anchor_id:
                return path
        return None

    def verify_anchor(self, anchor_id: str) -> dict[str, Any] | None:
        path = self.resolve_anchor_path(anchor_id)
        if not path:
            return None

        errors: list[str] = []
        checks = {
            "file_readable": False,
            "manifest_sha256_valid": False,
            "manifest_signature_valid": True,
            "chain_was_valid_at_anchor": False,
            "current_audit_prefix_matches_anchor": False,
        }
        manifest = self._read_manifest(path)
        manifest_signed = False
        current_chain = self.db.verify_audit_chain()
        current_event_count = 0
        current_prefix_sha256: str | None = None
        current_prefix_last_event_hash: str | None = None

        if not manifest:
            errors.append("anchor_manifest_unreadable")
        else:
            checks["file_readable"] = True
            expected_manifest_sha256 = self._manifest_sha256(manifest)
            actual_manifest_sha256 = str(manifest.get("manifest_sha256") or "")
            checks["manifest_sha256_valid"] = hmac.compare_digest(
                actual_manifest_sha256,
                expected_manifest_sha256,
            )
            if not checks["manifest_sha256_valid"]:
                errors.append("manifest_sha256_mismatch")

            signature_check = self._verify_manifest_signature(manifest)
            checks["manifest_signature_valid"] = signature_check["ok"]
            manifest_signed = signature_check["signed"]
            errors.extend(signature_check["errors"])

            chain_at_anchor = manifest.get("chain_verification") or {}
            checks["chain_was_valid_at_anchor"] = chain_at_anchor.get("valid") is True
            if not checks["chain_was_valid_at_anchor"]:
                errors.append("audit_chain_was_invalid_at_anchor")

            anchor_event_count = int(manifest.get("event_count") or 0)
            current_events = self._audit_events(limit=anchor_event_count)
            current_event_count = len(current_events)
            current_prefix_sha256 = self._events_sha256(current_events)
            current_prefix_last_event_hash = self._last_event_hash(current_events)
            checks["current_audit_prefix_matches_anchor"] = (
                current_event_count == anchor_event_count
                and current_prefix_sha256 == manifest.get("events_sha256")
                and current_prefix_last_event_hash == manifest.get("last_event_hash")
            )
            if not checks["current_audit_prefix_matches_anchor"]:
                errors.append("current_audit_prefix_mismatch")

        return {
            "id": path.stem,
            "filename": path.name,
            "valid": bool(all(checks.values()) and not errors),
            "checks": checks,
            "errors": errors,
            "manifest": manifest,
            "manifest_signed": manifest_signed,
            "current_chain": current_chain,
            "current_event_count": current_chain["total_events"],
            "current_prefix_event_count": current_event_count,
            "current_prefix_sha256": current_prefix_sha256,
            "current_prefix_last_event_hash": current_prefix_last_event_hash,
        }

    def _audit_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        columns = """
            id, request_id, actor_role, actor_hash, method, path,
            status_code, latency_ms, client_host, previous_hash, event_hash, created_at
        """
        query = f"SELECT {columns} FROM audit_events ORDER BY rowid ASC"
        params: tuple[int, ...] = ()
        if limit is not None:
            query = f"{query} LIMIT ?"
            params = (limit,)
        with self.db.connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def _events_sha256(self, events: list[dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        for event in events:
            canonical = json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            digest.update(canonical.encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()

    def _last_event_hash(self, events: list[dict[str, Any]]) -> str | None:
        for event in reversed(events):
            event_hash = str(event.get("event_hash") or "")
            if event_hash:
                return event_hash
        return None

    def _manifest_sha256(self, manifest: dict[str, Any]) -> str:
        payload = {
            key: value
            for key, value in manifest.items()
            if key not in {"manifest_sha256", "manifest_signature"}
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _sign_manifest(self, manifest: dict[str, Any]) -> None:
        signing_key = self.settings.backup_signing_key.strip()
        if not signing_key:
            return
        manifest["manifest_signature"] = {
            "algorithm": "HMAC-SHA256",
            "value": self._manifest_signature(manifest, signing_key),
        }

    def _verify_manifest_signature(self, manifest: dict[str, Any]) -> dict[str, Any]:
        signature = manifest.get("manifest_signature")
        signing_key = self.settings.backup_signing_key.strip()
        if not signature:
            if signing_key:
                return {"ok": False, "signed": False, "errors": ["manifest_signature_missing"]}
            return {"ok": True, "signed": False, "errors": []}

        if not signing_key:
            return {"ok": False, "signed": True, "errors": ["backup_signing_key_missing"]}
        if not isinstance(signature, dict):
            return {"ok": False, "signed": True, "errors": ["manifest_signature_invalid"]}
        if signature.get("algorithm") != "HMAC-SHA256":
            return {
                "ok": False,
                "signed": True,
                "errors": ["manifest_signature_algorithm_unsupported"],
            }

        expected = self._manifest_signature(manifest, signing_key)
        actual = str(signature.get("value") or "")
        if not hmac.compare_digest(actual, expected):
            return {"ok": False, "signed": True, "errors": ["manifest_signature_mismatch"]}
        return {"ok": True, "signed": True, "errors": []}

    def _manifest_signature(self, manifest: dict[str, Any], signing_key: str) -> str:
        payload = {key: value for key, value in manifest.items() if key != "manifest_signature"}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hmac.new(
            signing_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _write_json_atomic(self, path: Path, manifest: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def _read_manifest(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _snapshot_from_manifest(self, path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        chain = manifest.get("chain_verification") or {}
        signature = manifest.get("manifest_signature")
        return {
            "id": str(manifest.get("anchor_id") or path.stem),
            "filename": path.name,
            "created_at": str(manifest.get("created_at") or ""),
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "event_count": int(manifest.get("event_count") or 0),
            "last_event_hash": manifest.get("last_event_hash"),
            "events_sha256": str(manifest.get("events_sha256") or ""),
            "manifest_sha256": str(manifest.get("manifest_sha256") or ""),
            "chain_valid_at_anchor": chain.get("valid") is True,
            "manifest_signed": isinstance(signature, dict) and bool(signature.get("value")),
            "created_by_role": str(manifest.get("created_by_role") or "unknown"),
            "created_by_hash": str(manifest.get("created_by_hash") or "unknown"),
        }


@lru_cache
def get_audit_anchor_service() -> AuditAnchorService:
    return AuditAnchorService()
