"""Tools for semantic RAG document ingestion and query."""

from pydantic import BaseModel, Field
from typing import Any
from . import Tool, ToolResult
from ..vector import VectorStore

class SemanticSearchParams(BaseModel):
    query: str = Field(..., description="The conceptual meaning or semantic query to search for.")
    n_results: int = Field(5, description="Number of matches to return.")

class DocumentIngestParams(BaseModel):
    document: str = Field(..., description="The raw, chunked text to embed and memorize.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary JSON metadata tags like 'source' or 'author'.")

class SemanticSearchTool(Tool):
    """Query the Chroma VectorStore for semantic documentation."""

    parameters_model = SemanticSearchParams

    def __init__(self, vector_store: VectorStore | None = None):
        super().__init__(
            name="semantic_search",
            description="Searches the agent's vectorized memory database for documents matching the conceptual meaning of the query. Better than exact grep for finding related topics."
        )
        self.vector_store = vector_store or VectorStore()

    async def execute(self, query: str, n_results: int = 5) -> ToolResult:
        try:
            results = self.vector_store.search(query=query, n_results=n_results)
            if not results:
                return ToolResult(content="No semantic matches found in vector memory.")

            formatted = []
            for item in results:
                formatted.append(f"--- MATCH (Dist: {item['distance']:.3f}) ---\nMetadata:{item['metadata']}\nContent:\n{item['document']}")

            return ToolResult(content="\n\n".join(formatted))
        except Exception as e:
            return ToolResult(error=str(e))


class DocumentIngestionTool(Tool):
    """Ingest new documents directly into the persistent VectorStore."""

    parameters_model = DocumentIngestParams

    def __init__(self, vector_store: VectorStore | None = None):
        super().__init__(
            name="ingest_document",
            description="Embeds a chunk of text into the vector database so it can be retrieved later semantically. Use this when reading large files to compress them into memory."
        )
        self.vector_store = vector_store or VectorStore()

    async def execute(self, document: str, metadata: dict[str, Any]) -> ToolResult:
        try:
            ids = self.vector_store.add_documents([document], [metadata])
            return ToolResult(content=f"Successfully ingested document. Vector UUID: {ids[0]}")
        except Exception as e:
            return ToolResult(error=str(e))
