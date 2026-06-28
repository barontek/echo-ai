"""Vector database abstraction for semantic memory."""

import os
import uuid
import logging
from typing import Any
try:
    import chromadb
except ImportError:  # pragma: no cover - optional runtime dependency
    chromadb = None

from .constants import ECHO_DATA_DIR

logger = logging.getLogger(__name__)


class VectorStore:
    """A wrapper for chromadb to handle persistent document storage and semantic search."""

    def __init__(self, persist_directory: str | None = None, collection_name: str = "agent_memory"):
        """Initialize the persistent Chroma client."""
        if persist_directory is None:
            persist_directory = str(ECHO_DATA_DIR / "vector")
        # Ensure the directory exists
        os.makedirs(persist_directory, exist_ok=True)

        if chromadb is None:
            logger.warning("chromadb is not installed; vector features are disabled.")
            self.collection = None
            return

        try:
            self.client = chromadb.PersistentClient(path=persist_directory)
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},  # Default similarity strategy
            )
            logger.debug("Successfully initialized chromadb backend at %s", persist_directory)
        except Exception as e:
            logger.error("Failed to initialize chromadb: %s", e)
            self.collection = None

    def add_documents(self, documents: list[str], metadatas: list[dict[str, Any]] | None = None, ids: list[str] | None = None) -> list[str]:
        """Ingest new documents into the vector space.

        Returns the list of generated or provided UUIDs.
        """
        if not self.collection:
            raise RuntimeError("Vector database is not initialized.")

        if not ids:
            ids = [str(uuid.uuid4()) for _ in documents]

        if not metadatas:
            metadatas = [{"source": "manual_ingestion"} for _ in documents]

        cleaned_metadatas = []
        for meta in metadatas:
            cleaned_meta = {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))}
            cleaned_metadatas.append(cleaned_meta)

        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=cleaned_metadatas,  # type: ignore
        )
        return ids

    def search(self, query: str, n_results: int = 5) -> list[dict[str, Any]]:
        """Perform a semantic search against the loaded documents."""
        if not self.collection:
            raise RuntimeError("Vector database is not initialized.")

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )

        # Zip documents, metadatas, and distances into a unified structure
        structured_results = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            raw_metas = results["metadatas"][0] if "metadatas" in results and results.get("metadatas") else None
            if raw_metas is None:
                metas = [{} for _ in docs]
            else:
                metas = [m if m is not None else {} for m in raw_metas]
            dists = results["distances"][0] if "distances" in results and results["distances"] else [0.0] * len(docs)

            for doc, meta, dist in zip(docs, metas, dists):
                structured_results.append({
                    "document": doc,
                    "metadata": meta,
                    "distance": dist
                })

        return structured_results

    def close(self) -> None:
        """Explicitly close the Chroma client connection."""
        if hasattr(self, "client") and self.client:
            try:
                close_method = getattr(self.client, "close", None)
                if close_method:
                    close_method()
                logger.debug("Successfully closed chromadb client.")
            except Exception as e:
                logger.error("Failed to close chromadb client: %s", e)
