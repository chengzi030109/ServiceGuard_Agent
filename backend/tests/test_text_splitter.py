from backend.app.services.document_loader import DocumentText
from backend.app.services.text_splitter import TextSplitter


def test_text_splitter_preserves_overlap_and_metadata() -> None:
    text = "退款政策。" * 80
    splitter = TextSplitter(chunk_size=120, chunk_overlap=20)
    chunks = splitter.split([DocumentText(text=text, source="refund.md", page=1)])

    assert len(chunks) > 1
    assert chunks[0].source == "refund.md"
    assert chunks[0].page == 1
    assert all(chunk.token_count > 0 for chunk in chunks)
    assert chunks[0].text[-10:] in chunks[1].text
