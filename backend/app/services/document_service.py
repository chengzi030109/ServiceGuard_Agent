import shutil
import uuid
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.database import get_database
from backend.app.schemas.document import DocumentRecord
from backend.app.services.document_loader import DocumentLoader, DocumentText
from backend.app.services.privacy import get_privacy_redactor
from backend.app.services.prompt_injection import get_prompt_injection_scanner
from backend.app.services.text_splitter import TextSplitter
from backend.app.services.vector_store import get_vector_store


class DocumentService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.db = get_database()
        self.loader = DocumentLoader()
        self.privacy = get_privacy_redactor()
        self.prompt_injection = get_prompt_injection_scanner()
        self.vector_store = get_vector_store()

    def ingest_upload(
        self, filename: str, source_path: Path
    ) -> tuple[DocumentRecord, int, dict[str, int], dict[str, int]]:
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        suffix = source_path.suffix.lower()
        safe_name = Path(filename).name.replace(" ", "_")
        target = self.settings.upload_path / f"{doc_id}_{safe_name}"
        shutil.copyfile(source_path, target)

        self.db.upsert_document(
            doc_id=doc_id,
            filename=filename,
            file_type=suffix.removeprefix("."),
            status="processing",
            path=str(target),
            security_review_status="pending",
        )
        try:
            texts, sensitive_redactions = self._load_redacted_texts(target)
            prompt_injection_risks = self._scan_document_texts(texts)
            stored_path = self._write_sanitized_upload(target, texts)
        except Exception:
            if target.exists():
                target.unlink()
            raise

        if prompt_injection_risks and self.settings.quarantine_prompt_injection_documents:
            self.db.replace_chunks(doc_id, [])
            self.vector_store.delete_by_doc_id(doc_id)
            self.db.upsert_document(
                doc_id=doc_id,
                filename=filename,
                file_type=suffix.removeprefix("."),
                status="quarantined",
                path=str(stored_path),
                chunk_count=0,
                security_review_status="pending",
                prompt_injection_risks=prompt_injection_risks,
            )
            return (
                DocumentRecord(**self.db.get_document(doc_id)),  # type: ignore[arg-type]
                0,
                sensitive_redactions,
                prompt_injection_risks,
            )

        doc_chunks = self._index_texts(doc_id, filename, texts)
        security_review_status = "approved_with_warnings" if prompt_injection_risks else "approved"
        self.db.upsert_document(
            doc_id=doc_id,
            filename=filename,
            file_type=suffix.removeprefix("."),
            status="indexed",
            path=str(stored_path),
            chunk_count=len(doc_chunks),
            security_review_status=security_review_status,
            prompt_injection_risks=prompt_injection_risks,
        )
        return (
            DocumentRecord(**self.db.get_document(doc_id)),  # type: ignore[arg-type]
            len(doc_chunks),
            sensitive_redactions,
            prompt_injection_risks,
        )

    def list_documents(self) -> list[DocumentRecord]:
        return [DocumentRecord(**item) for item in self.db.list_documents()]

    def delete_document(self, doc_id: str) -> bool:
        document = self.db.get_document(doc_id)
        if not document:
            return False
        self.vector_store.delete_by_doc_id(doc_id)
        self.db.delete_document(doc_id)
        path = Path(document["path"])
        if path.exists():
            path.unlink()
        return True

    def approve_document(self, doc_id: str) -> tuple[DocumentRecord, int] | None:
        document = self.db.get_document(doc_id)
        if not document:
            return None

        file_path = Path(str(document["path"]))
        if not file_path.exists():
            raise FileNotFoundError(file_path)

        texts = self.loader.load(file_path)
        prompt_injection_risks = self._scan_document_texts(texts) or dict(
            document.get("prompt_injection_risks") or {}
        )
        doc_chunks = self._index_texts(doc_id, str(document["filename"]), texts)
        self.db.upsert_document(
            doc_id=doc_id,
            filename=str(document["filename"]),
            file_type=str(document["file_type"]),
            status="indexed",
            path=str(file_path),
            chunk_count=len(doc_chunks),
            security_review_status="approved",
            prompt_injection_risks=prompt_injection_risks,
        )
        return DocumentRecord(**self.db.get_document(doc_id)), len(doc_chunks)  # type: ignore[arg-type]

    def reject_document(self, doc_id: str) -> DocumentRecord | None:
        document = self.db.get_document(doc_id)
        if not document:
            return None

        self.vector_store.delete_by_doc_id(doc_id)
        self.db.replace_chunks(doc_id, [])
        self.db.upsert_document(
            doc_id=doc_id,
            filename=str(document["filename"]),
            file_type=str(document["file_type"]),
            status="rejected",
            path=str(document["path"]),
            chunk_count=0,
            security_review_status="rejected",
            prompt_injection_risks=dict(document.get("prompt_injection_risks") or {}),
        )
        return DocumentRecord(**self.db.get_document(doc_id))  # type: ignore[arg-type]

    def debug_chunks(self, limit: int = 100) -> list[dict]:
        return self.db.list_chunks(limit=limit)

    def remediate_sensitive_data(self, *, dry_run: bool = True) -> dict[str, object]:
        scanned_documents = 0
        scanned_chunks = 0
        affected_chunks = 0
        affected_files = 0
        remediated_chunks = 0
        remediated_files = 0
        missing_files = 0
        skipped_files = 0
        redaction_counts: dict[str, int] = {}
        affected_document_ids: set[str] = set()

        for document in self.db.list_documents():
            scanned_documents += 1
            doc_id = str(document["id"])
            chunks = self.db.list_chunks_by_doc_id(doc_id)
            scanned_chunks += len(chunks)

            redacted_chunks: list[dict] = []
            doc_affected_chunks = 0
            for chunk in chunks:
                redacted_text, counts = self.privacy.redact_text_with_counts(str(chunk["text"]))
                if counts:
                    doc_affected_chunks += 1
                    self._merge_counts(redaction_counts, counts)
                    affected_document_ids.add(doc_id)
                redacted_chunks.append(
                    {
                        "id": chunk["id"],
                        "doc_id": doc_id,
                        "document_name": document["filename"],
                        "chunk_index": chunk["chunk_index"],
                        "text": redacted_text,
                        "source": chunk["source"],
                        "page": chunk.get("page"),
                        "token_count": chunk["token_count"],
                    }
                )

            affected_chunks += doc_affected_chunks
            if doc_affected_chunks and not dry_run:
                self.db.replace_chunks(doc_id, redacted_chunks)
                self.vector_store.upsert_chunks(redacted_chunks)
                remediated_chunks += doc_affected_chunks

            file_path = Path(str(document["path"]))
            if not file_path.exists():
                missing_files += 1
                continue

            try:
                redacted_texts, file_counts = self._load_redacted_texts(file_path)
            except Exception:
                skipped_files += 1
                continue

            if not file_counts:
                continue

            affected_files += 1
            affected_document_ids.add(doc_id)
            self._merge_counts(redaction_counts, file_counts)
            if dry_run:
                continue

            sanitized_path = self._write_sanitized_stored_file(file_path, redacted_texts)
            self.db.upsert_document(
                doc_id=doc_id,
                filename=str(document["filename"]),
                file_type=str(document["file_type"]),
                status=str(document["status"]),
                path=str(sanitized_path),
                chunk_count=int(document["chunk_count"]),
            )
            remediated_files += 1

        return {
            "dry_run": dry_run,
            "scanned_documents": scanned_documents,
            "scanned_chunks": scanned_chunks,
            "affected_documents": len(affected_document_ids),
            "affected_chunks": affected_chunks,
            "affected_files": affected_files,
            "remediated_chunks": remediated_chunks,
            "remediated_files": remediated_files,
            "missing_files": missing_files,
            "skipped_files": skipped_files,
            "redaction_counts": redaction_counts,
            "document_ids": sorted(affected_document_ids),
        }

    def scan_prompt_injection_risks(self) -> dict[str, object]:
        scanned_documents = 0
        scanned_chunks = 0
        affected_chunks = 0
        affected_files = 0
        missing_files = 0
        skipped_files = 0
        risk_counts: dict[str, int] = {}
        affected_document_ids: set[str] = set()

        for document in self.db.list_documents():
            scanned_documents += 1
            doc_id = str(document["id"])
            chunks = self.db.list_chunks_by_doc_id(doc_id)
            scanned_chunks += len(chunks)

            for chunk in chunks:
                counts = self.prompt_injection.scan_text(str(chunk["text"]))
                if counts:
                    affected_chunks += 1
                    affected_document_ids.add(doc_id)
                    self._merge_counts(risk_counts, counts)

            file_path = Path(str(document["path"]))
            if not file_path.exists():
                missing_files += 1
                continue

            try:
                texts = self.loader.load(file_path)
            except Exception:
                skipped_files += 1
                continue

            file_counts = self._scan_document_texts(texts)
            if file_counts:
                affected_files += 1
                affected_document_ids.add(doc_id)
                self._merge_counts(risk_counts, file_counts)

        return {
            "scanned_documents": scanned_documents,
            "scanned_chunks": scanned_chunks,
            "affected_documents": len(affected_document_ids),
            "affected_chunks": affected_chunks,
            "affected_files": affected_files,
            "missing_files": missing_files,
            "skipped_files": skipped_files,
            "prompt_injection_detected": bool(risk_counts),
            "prompt_injection_risks": risk_counts,
            "document_ids": sorted(affected_document_ids),
        }

    def _load_redacted_texts(self, target: Path) -> tuple[list[DocumentText], dict[str, int]]:
        texts = self.loader.load(target)
        redacted_texts: list[DocumentText] = []
        total_counts: dict[str, int] = {}
        for item in texts:
            redacted, counts = self.privacy.redact_text_with_counts(item.text)
            for name, count in counts.items():
                total_counts[name] = total_counts.get(name, 0) + count
            redacted_texts.append(DocumentText(text=redacted, source=item.source, page=item.page))
        return redacted_texts, total_counts

    def _scan_document_texts(self, texts: list[DocumentText]) -> dict[str, int]:
        return self.prompt_injection.scan_texts([item.text for item in texts])

    def _index_texts(
        self,
        doc_id: str,
        filename: str,
        texts: list[DocumentText],
    ) -> list[dict]:
        splitter = TextSplitter(self.settings.chunk_size, self.settings.chunk_overlap)
        split_chunks = splitter.split(texts)
        doc_chunks = [
            {
                "id": f"chunk_{doc_id}_{chunk.chunk_index}",
                "doc_id": doc_id,
                "document_name": filename,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "source": chunk.source,
                "page": chunk.page,
                "token_count": chunk.token_count,
            }
            for chunk in split_chunks
        ]
        self.db.replace_chunks(doc_id, doc_chunks)
        self.vector_store.upsert_chunks(doc_chunks)
        return doc_chunks

    def _write_sanitized_upload(self, raw_target: Path, texts: list[DocumentText]) -> Path:
        sanitized_target = self._sanitized_path(raw_target)
        self._write_redacted_sections(sanitized_target, texts)
        if raw_target.exists() and raw_target != sanitized_target:
            raw_target.unlink()
        return sanitized_target

    def _write_sanitized_stored_file(self, raw_target: Path, texts: list[DocumentText]) -> Path:
        sanitized_target = self._sanitized_path(raw_target)
        self._write_redacted_sections(sanitized_target, texts)
        if raw_target.exists() and raw_target != sanitized_target:
            raw_target.unlink()
        return sanitized_target

    def _write_redacted_sections(self, target: Path, texts: list[DocumentText]) -> None:
        sections: list[str] = []
        for item in texts:
            page_label = f" page={item.page}" if item.page is not None else ""
            sections.append(f"--- source={item.source}{page_label} ---\n{item.text}")
        target.write_text("\n\n".join(sections), encoding="utf-8")

    def _sanitized_path(self, raw_target: Path) -> Path:
        if raw_target.name.endswith(".redacted.txt"):
            return raw_target
        return raw_target.with_name(f"{raw_target.name}.redacted.txt")

    def _merge_counts(self, total: dict[str, int], counts: dict[str, int]) -> None:
        for name, count in counts.items():
            total[name] = total.get(name, 0) + count


def get_document_service() -> DocumentService:
    return DocumentService()
