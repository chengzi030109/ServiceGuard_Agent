from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DocumentText:
    text: str
    source: str
    page: int | None = None


class DocumentLoaderError(ValueError):
    """Raised when a document cannot be parsed into text."""


class DocumentLoader:
    supported_suffixes = {".txt", ".md", ".markdown", ".pdf"}

    def load(self, path: Path) -> list[DocumentText]:
        suffix = path.suffix.lower()
        if suffix not in self.supported_suffixes:
            raise DocumentLoaderError(f"Unsupported file type: {suffix}")
        if suffix == ".pdf":
            return self._load_pdf(path)
        return [DocumentText(text=self._read_text(path), source=path.name)]

    def _read_text(self, path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise DocumentLoaderError(f"Could not decode text file: {path.name}")

    def _load_pdf(self, path: Path) -> list[DocumentText]:
        try:
            import fitz
        except ImportError as exc:
            raise DocumentLoaderError("PyMuPDF is required for PDF parsing") from exc

        pages: list[DocumentText] = []
        with fitz.open(path) as doc:
            for index, page in enumerate(doc, start=1):
                text = page.get_text("text").strip()
                if text:
                    pages.append(DocumentText(text=text, source=path.name, page=index))
        if not pages:
            raise DocumentLoaderError(f"No extractable text found in PDF: {path.name}")
        return pages
