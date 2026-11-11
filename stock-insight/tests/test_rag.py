from core.rag import InvestmentKnowledgeBase


def test_builtin_knowledge_is_searchable():
    kb = InvestmentKnowledgeBase()
    result = kb.search("止损", top_k=3)
    assert "止损" in result


def test_chunking_splits_long_text():
    kb = InvestmentKnowledgeBase()
    chunks = kb._chunk_text("测试" * 500, max_length=100)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)


def test_unknown_query_returns_something_not_crash():
    kb = InvestmentKnowledgeBase()
    result = kb.search("量子纠缠与超导材料", top_k=3)
    assert isinstance(result, str)
    assert result != ""
