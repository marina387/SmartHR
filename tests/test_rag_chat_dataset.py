from scripts.generate_rag_chat_dataset import document_sections, onet_examples


def test_document_sections_extract_numbered_sections():
    sections = document_sections("Title\n\n1. First\nAlpha\n\n2. Second\nBeta")
    assert sections == [
        {"section": "1. First", "text": "Alpha"},
        {"section": "2. Second", "text": "Beta"},
    ]


def test_onet_example_contains_tool_context_and_citation():
    occupations = [{
        "id": "onet_1", "code": "15-0000.00", "title": "Example Role",
        "description": "Perform documented example tasks.",
        "source": {"source_url": "https://example.test/onet"},
    }]
    record = onet_examples(occupations, 1)[0]
    assert [message["role"] for message in record["messages"]] == ["system", "user", "tool", "assistant"]
    assert record["citations"][0]["section"] == "15-0000.00"
    assert "Perform documented example tasks" in record["messages"][-1]["content"]
