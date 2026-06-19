import hashlib
import hmac
import json
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.database import get_database


class BackupService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.db = get_database()

    def create_backup(
        self,
        *,
        include_uploads: bool = True,
        include_chroma: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        backup_id = f"backup_{now.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        backup_path = self.settings.backup_path / f"{backup_id}.zip"
        manifest = {
            "version": 2,
            "backup_id": backup_id,
            "created_at": now.isoformat(),
            "app": "ServiceGuard Agent",
            "include_uploads": include_uploads,
            "include_chroma": include_chroma,
            "database_stats": self.db.stats(),
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            sqlite_copy = Path(tmp_dir) / "serviceguard.db"
            self._copy_sqlite(sqlite_copy)
            manifest["files"] = [self._file_manifest_entry(sqlite_copy, "sqlite/serviceguard.db")]
            if include_uploads:
                manifest["files"].extend(
                    self._directory_manifest_entries(self.settings.upload_path, "uploads")
                )
            if include_chroma:
                manifest["files"].extend(
                    self._directory_manifest_entries(self.settings.chroma_path, "chroma")
                )
            self._sign_manifest(manifest)
            with zipfile.ZipFile(
                backup_path, mode="w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
                archive.write(sqlite_copy, "sqlite/serviceguard.db")
                if include_uploads:
                    self._add_directory(archive, self.settings.upload_path, "uploads")
                if include_chroma:
                    self._add_directory(archive, self.settings.chroma_path, "chroma")

        return self._snapshot_from_path(backup_path)

    def list_backups(self) -> list[dict[str, Any]]:
        backups = [
            self._snapshot_from_path(path)
            for path in self.settings.backup_path.glob("backup_*.zip")
            if path.is_file()
        ]
        backups.sort(key=lambda item: str(item["created_at"]), reverse=True)
        return backups

    def resolve_backup_path(self, backup_id: str) -> Path | None:
        requested = backup_id.removesuffix(".zip")
        for path in self.settings.backup_path.glob("backup_*.zip"):
            if path.stem == requested or path.name == backup_id:
                return path
        return None

    def verify_backup(self, backup_id: str) -> dict[str, Any] | None:
        backup_path = self.resolve_backup_path(backup_id)
        if not backup_path:
            return None

        errors: list[str] = []
        checks = {
            "zip_readable": False,
            "manifest_present": False,
            "manifest_id_matches": False,
            "manifest_signature_valid": True,
            "file_checksums_ok": True,
            "sqlite_present": False,
            "sqlite_integrity_ok": False,
        }
        manifest: dict[str, Any] = {}
        file_counts = {"uploads": 0, "chroma": 0}
        verified_files = 0
        manifest_signed = False
        sqlite_integrity_result: str | None = None

        try:
            with zipfile.ZipFile(backup_path) as archive:
                archive.testzip()
                checks["zip_readable"] = True
                names = archive.namelist()
                file_counts["uploads"] = sum(1 for name in names if name.startswith("uploads/"))
                file_counts["chroma"] = sum(1 for name in names if name.startswith("chroma/"))

                if "manifest.json" in names:
                    checks["manifest_present"] = True
                    try:
                        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                        checks["manifest_id_matches"] = (
                            manifest.get("backup_id") == backup_path.stem
                        )
                        signature_check = self._verify_manifest_signature(manifest)
                        checks["manifest_signature_valid"] = signature_check["ok"]
                        manifest_signed = signature_check["signed"]
                        errors.extend(signature_check["errors"])
                        file_check = self._verify_manifest_files(archive, manifest)
                        checks["file_checksums_ok"] = file_check["ok"]
                        verified_files = file_check["verified_files"]
                        errors.extend(file_check["errors"])
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        errors.append(f"manifest_invalid: {exc}")
                else:
                    errors.append("manifest.json is missing")

                if "sqlite/serviceguard.db" in names:
                    checks["sqlite_present"] = True
                    sqlite_integrity_result = self._verify_sqlite_from_archive(archive)
                    checks["sqlite_integrity_ok"] = sqlite_integrity_result == "ok"
                    if sqlite_integrity_result != "ok":
                        errors.append(f"sqlite_integrity_check_failed: {sqlite_integrity_result}")
                else:
                    errors.append("sqlite/serviceguard.db is missing")
        except zipfile.BadZipFile as exc:
            errors.append(f"zip_invalid: {exc}")
        except OSError as exc:
            errors.append(f"backup_unreadable: {exc}")

        return {
            "id": backup_path.stem,
            "filename": backup_path.name,
            "valid": bool(checks["zip_readable"] and all(checks.values()) and not errors),
            "checks": checks,
            "errors": errors,
            "manifest": manifest,
            "manifest_signed": manifest_signed,
            "file_counts": file_counts,
            "verified_files": verified_files,
            "sqlite_integrity_result": sqlite_integrity_result,
        }

    def restore_backup_dry_run(self, backup_id: str) -> dict[str, Any] | None:
        backup_path = self.resolve_backup_path(backup_id)
        if not backup_path:
            return None

        verification = self.verify_backup(backup_id)
        if not verification:
            return None

        errors: list[str] = list(verification["errors"])
        checks = {
            "backup_verification_valid": bool(verification["valid"]),
            "sqlite_extracted": False,
            "sqlite_integrity_ok": False,
            "expected_tables_present": False,
            "table_counts_match_manifest": False,
        }
        sqlite_integrity_result: str | None = None
        restored_database_stats: dict[str, int] = {}
        manifest_database_stats = dict(verification.get("manifest", {}).get("database_stats") or {})
        missing_tables: list[str] = []

        if not verification["valid"]:
            errors.append("backup_verification_failed")
            return {
                "id": backup_path.stem,
                "filename": backup_path.name,
                "dry_run": True,
                "restore_ready": False,
                "checks": checks,
                "errors": errors,
                "verification": verification,
                "sqlite_integrity_result": sqlite_integrity_result,
                "missing_tables": missing_tables,
                "manifest_database_stats": manifest_database_stats,
                "restored_database_stats": restored_database_stats,
            }

        try:
            with zipfile.ZipFile(backup_path) as archive:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    sqlite_path = Path(tmp_dir) / "serviceguard.db"
                    sqlite_path.write_bytes(archive.read("sqlite/serviceguard.db"))
                    checks["sqlite_extracted"] = True
                    sqlite_integrity_result = self._sqlite_integrity_check(sqlite_path)
                    checks["sqlite_integrity_ok"] = sqlite_integrity_result == "ok"
                    if sqlite_integrity_result != "ok":
                        errors.append(f"sqlite_integrity_check_failed: {sqlite_integrity_result}")

                    restored_database_stats, missing_tables = self._database_stats_from_sqlite(
                        sqlite_path
                    )
                    checks["expected_tables_present"] = not missing_tables
                    if missing_tables:
                        errors.append(f"missing_expected_tables: {', '.join(missing_tables)}")
                    checks["table_counts_match_manifest"] = self._database_stats_match(
                        restored_database_stats,
                        manifest_database_stats,
                    )
                    if not checks["table_counts_match_manifest"]:
                        errors.append("database_stats_mismatch")
        except (KeyError, OSError, zipfile.BadZipFile) as exc:
            errors.append(f"restore_dry_run_failed: {exc}")

        return {
            "id": backup_path.stem,
            "filename": backup_path.name,
            "dry_run": True,
            "restore_ready": bool(all(checks.values()) and not errors),
            "checks": checks,
            "errors": errors,
            "verification": verification,
            "sqlite_integrity_result": sqlite_integrity_result,
            "missing_tables": missing_tables,
            "manifest_database_stats": manifest_database_stats,
            "restored_database_stats": restored_database_stats,
        }

    def _copy_sqlite(self, target: Path) -> None:
        source = sqlite3.connect(str(self.settings.sqlite_path))
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

    def _add_directory(self, archive: zipfile.ZipFile, root: Path, prefix: str) -> None:
        if not root.exists():
            return
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, f"{prefix}/{path.relative_to(root).as_posix()}")

    def _directory_manifest_entries(self, root: Path, prefix: str) -> list[dict[str, Any]]:
        if not root.exists():
            return []
        return [
            self._file_manifest_entry(path, f"{prefix}/{path.relative_to(root).as_posix()}")
            for path in sorted(root.rglob("*"))
            if path.is_file()
        ]

    def _file_manifest_entry(self, path: Path, archive_path: str) -> dict[str, Any]:
        return {
            "path": archive_path,
            "size_bytes": path.stat().st_size,
            "sha256": self._sha256_path(path),
        }

    def _verify_manifest_files(
        self,
        archive: zipfile.ZipFile,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        entries = manifest.get("files")
        if entries is None:
            return {"ok": True, "verified_files": 0, "errors": []}
        if not isinstance(entries, list):
            return {
                "ok": False,
                "verified_files": 0,
                "errors": ["manifest_files_invalid: files must be a list"],
            }

        errors: list[str] = []
        verified_files = 0
        archive_names = set(archive.namelist())
        for item in entries:
            if not isinstance(item, dict):
                errors.append("manifest_files_invalid: file entry must be an object")
                continue
            path = str(item.get("path") or "")
            expected_size = item.get("size_bytes")
            expected_sha256 = str(item.get("sha256") or "")
            if not path:
                errors.append("manifest_files_invalid: file path is empty")
                continue
            if path not in archive_names:
                errors.append(f"manifest_file_missing: {path}")
                continue

            data = archive.read(path)
            actual_size = len(data)
            actual_sha256 = hashlib.sha256(data).hexdigest()
            if actual_size != expected_size:
                errors.append(f"manifest_file_size_mismatch: {path}")
                continue
            if actual_sha256 != expected_sha256:
                errors.append(f"manifest_file_sha256_mismatch: {path}")
                continue
            verified_files += 1
        return {"ok": not errors, "verified_files": verified_files, "errors": errors}

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
                return {
                    "ok": False,
                    "signed": False,
                    "errors": ["manifest_signature_missing"],
                }
            return {"ok": True, "signed": False, "errors": []}

        if not signing_key:
            return {
                "ok": False,
                "signed": True,
                "errors": ["backup_signing_key_missing"],
            }
        if not isinstance(signature, dict):
            return {
                "ok": False,
                "signed": True,
                "errors": ["manifest_signature_invalid"],
            }
        if signature.get("algorithm") != "HMAC-SHA256":
            return {
                "ok": False,
                "signed": True,
                "errors": ["manifest_signature_algorithm_unsupported"],
            }

        expected = self._manifest_signature(manifest, signing_key)
        actual = str(signature.get("value") or "")
        if not hmac.compare_digest(actual, expected):
            return {
                "ok": False,
                "signed": True,
                "errors": ["manifest_signature_mismatch"],
            }
        return {"ok": True, "signed": True, "errors": []}

    def _manifest_signature(self, manifest: dict[str, Any], signing_key: str) -> str:
        payload = {key: value for key, value in manifest.items() if key != "manifest_signature"}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hmac.new(
            signing_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _sha256_path(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _verify_sqlite_from_archive(self, archive: zipfile.ZipFile) -> str:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sqlite_path = Path(tmp_dir) / "serviceguard.db"
            sqlite_path.write_bytes(archive.read("sqlite/serviceguard.db"))
            return self._sqlite_integrity_check(sqlite_path)

    def _sqlite_integrity_check(self, sqlite_path: Path) -> str:
        conn = sqlite3.connect(str(sqlite_path))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
        return str(row[0]) if row else "no result"

    def _database_stats_from_sqlite(self, sqlite_path: Path) -> tuple[dict[str, int], list[str]]:
        expected_tables = [
            "documents",
            "chunks",
            "reports",
            "llm_call_logs",
            "audit_events",
            "batch_jobs",
            "idempotency_records",
        ]
        stats: dict[str, int] = {}
        missing_tables: list[str] = []
        conn = sqlite3.connect(str(sqlite_path))
        try:
            existing_tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            for table in expected_tables:
                if table not in existing_tables:
                    missing_tables.append(table)
                    continue
                stats[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if "documents" in existing_tables:
                stats["documents_quarantined"] = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM documents WHERE status = 'quarantined'"
                    ).fetchone()[0]
                )
        finally:
            conn.close()
        return stats, missing_tables

    def _database_stats_match(
        self,
        restored_database_stats: dict[str, int],
        manifest_database_stats: dict[str, Any],
    ) -> bool:
        if not manifest_database_stats:
            return False
        for key, expected_value in manifest_database_stats.items():
            if int(expected_value) != restored_database_stats.get(key):
                return False
        return True

    def _snapshot_from_path(self, path: Path) -> dict[str, Any]:
        manifest = self._read_manifest(path)
        created_at = (
            manifest.get("created_at")
            or datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=UTC,
            ).isoformat()
        )
        backup_id = str(manifest.get("backup_id") or path.stem)
        return {
            "id": backup_id,
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "created_at": created_at,
            "include_uploads": bool(manifest.get("include_uploads", False)),
            "include_chroma": bool(manifest.get("include_chroma", False)),
            "database_stats": manifest.get("database_stats") or {},
        }

    def _read_manifest(self, path: Path) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(path) as archive:
                with archive.open("manifest.json") as manifest_file:
                    return json.loads(manifest_file.read().decode("utf-8"))
        except (KeyError, OSError, ValueError, zipfile.BadZipFile):
            return {}


@lru_cache
def get_backup_service() -> BackupService:
    return BackupService()
