from src.core.rag_pipeline import RagPipeline


def test_rag_pipeline_returns_relevant_hits():
    docs = {
        "doc1": "RAG помогает находить нужные фрагменты документов перед генерацией ответа.",
        "doc2": "Для обучения достаточно небольшого набора примеров и простой логики поиска.",
    }

    rag = RagPipeline(backend="tfidf")
    rag.build_index(docs, chunk_size_words=20, overlap_words=5)
    result = rag.ask("что такое rag", top_k=2)

    assert result.hits
    assert result.hits[0].score > 0
    assert "rag" in result.hits[0].chunk.text.lower()
