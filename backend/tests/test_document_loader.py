from backend.app.services.document_loader import DocumentLoader


def test_document_loader_reads_markdown(tmp_path) -> None:
    path = tmp_path / "policy.md"
    path.write_text("# Policy\n客服不得保证退款。", encoding="utf-8")

    docs = DocumentLoader().load(path)

    assert len(docs) == 1
    assert "不得保证退款" in docs[0].text
    assert docs[0].source == "policy.md"
