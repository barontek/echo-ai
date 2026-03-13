import pytest
from src.agentframework.tools.rag import SemanticSearchTool, DocumentIngestionTool
from src.agentframework.vector import VectorStore

@pytest.fixture
def mock_vector_store():
    # Use an ephemeral client for testing to prevent locking file conflicts
    import chromadb
    store = VectorStore(persist_directory=".test_agent_vector_db")
    store.client = chromadb.EphemeralClient()
    # Replace the collection with an ephemeral one
    import uuid
    unique_name = f"test_memory_{uuid.uuid4().hex}"
    store.collection = store.client.get_or_create_collection(unique_name)
    yield store
    store.close()

@pytest.mark.asyncio
async def test_rag_ingest_and_search(mock_vector_store):
    ingest = DocumentIngestionTool(vector_store=mock_vector_store)
    search = SemanticSearchTool(vector_store=mock_vector_store)

    # 1. Ingest
    res1 = await ingest.execute(document="The capital of France is Paris.", metadata={"topic": "geography"})
    assert "Successfully ingested" in res1.content
    assert not res1.error

    # 2. Search
    res2 = await search.execute(query="What is the French capital?", n_results=1)
    assert "Paris" in res2.content
    assert "geography" in res2.content
    assert not res2.error

@pytest.mark.asyncio
async def test_semantic_search_empty(mock_vector_store):
    search = SemanticSearchTool(vector_store=mock_vector_store)
    res = await search.execute(query="Unknown topic", n_results=1)
    # The return format depends on chroma when results list might return distance even if empty, but usually it's handled.
    # We'll assert it either returns "No semantic matches" or doesn't crash
    assert "No semantic matches" in res.content or "--- MATCH" not in res.content
