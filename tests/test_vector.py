"""Tests for vector store."""

import pytest
from unittest.mock import MagicMock, patch

from src.agentframework.vector import VectorStore


class TestVectorStoreInit:
    def test_init_without_chromadb(self):
        with patch("src.agentframework.vector.chromadb", None):
            store = VectorStore(persist_directory="/tmp/vector_test")
            assert store.collection is None

    def test_init_with_chromadb(self):
        mock_chroma = MagicMock()
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_chroma.PersistentClient.return_value = mock_client
        mock_client.get_or_create_collection.return_value = mock_collection
        with patch("src.agentframework.vector.chromadb", mock_chroma):
            store = VectorStore(persist_directory="/tmp/vector_test")
            assert store.collection is mock_collection
            mock_chroma.PersistentClient.assert_called_once_with(
                path="/tmp/vector_test"
            )

    def test_init_exception_handling(self):
        mock_chroma = MagicMock()
        mock_chroma.PersistentClient.side_effect = Exception("db error")
        with patch("src.agentframework.vector.chromadb", mock_chroma):
            store = VectorStore(persist_directory="/tmp/vector_test")
            assert store.collection is None


class TestVectorStoreAddDocuments:
    @pytest.fixture
    def store(self):
        mock_chroma = MagicMock()
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_chroma.PersistentClient.return_value = mock_client
        mock_client.get_or_create_collection.return_value = mock_collection
        with patch("src.agentframework.vector.chromadb", mock_chroma):
            store = VectorStore(persist_directory="/tmp/vector_test")
        store.collection = mock_collection
        return store

    def test_add_documents_with_ids(self, store):
        ids = store.add_documents(
            ["doc1", "doc2"],
            ids=["id1", "id2"],
        )
        assert ids == ["id1", "id2"]
        store.collection.add.assert_called_once()
        call_kwargs = store.collection.add.call_args.kwargs
        assert call_kwargs["ids"] == ["id1", "id2"]
        assert call_kwargs["documents"] == ["doc1", "doc2"]

    def test_add_documents_auto_generates_ids(self, store):
        ids = store.add_documents(["doc1"])
        assert len(ids) == 1
        assert isinstance(ids[0], str)

    def test_add_documents_with_metadatas(self, store):
        ids = store.add_documents(
            ["doc1"],
            metadatas=[{"source": "test", "priority": 1}],
        )
        store.collection.add.assert_called_once()
        call_kwargs = store.collection.add.call_args.kwargs
        assert call_kwargs["metadatas"] == [{"source": "test", "priority": 1}]

    def test_add_documents_default_metadata(self, store):
        ids = store.add_documents(["doc1"])
        store.collection.add.assert_called_once()
        call_kwargs = store.collection.add.call_args.kwargs
        assert call_kwargs["metadatas"] == [{"source": "manual_ingestion"}]

    def test_add_documents_filters_invalid_metadata(self, store):
        ids = store.add_documents(
            ["doc1"],
            metadatas=[{"valid_str": "ok", "valid_int": 1, "bad_list": [1, 2, 3]}],
        )
        call_kwargs = store.collection.add.call_args.kwargs
        assert "valid_str" in call_kwargs["metadatas"][0]
        assert "valid_int" in call_kwargs["metadatas"][0]
        assert "bad_list" not in call_kwargs["metadatas"][0]

    def test_add_documents_no_collection(self, store):
        store.collection = None
        with pytest.raises(RuntimeError, match="not initialized"):
            store.add_documents(["doc1"])


class TestVectorStoreSearch:
    @pytest.fixture
    def store(self):
        mock_chroma = MagicMock()
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_chroma.PersistentClient.return_value = mock_client
        mock_client.get_or_create_collection.return_value = mock_collection
        with patch("src.agentframework.vector.chromadb", mock_chroma):
            store = VectorStore(persist_directory="/tmp/vector_test")
        store.collection = mock_collection
        return store

    def test_search_returns_structured_results(self, store):
        store.collection.query.return_value = {
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"source": "test"}, {"source": "test2"}]],
            "distances": [[0.1, 0.2]],
        }
        results = store.search("test query", n_results=2)
        assert len(results) == 2
        assert results[0]["document"] == "doc1"
        assert results[0]["metadata"] == {"source": "test"}
        assert results[0]["distance"] == 0.1
        assert results[1]["document"] == "doc2"

    def test_search_no_results(self, store):
        store.collection.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        results = store.search("no match")
        assert results == []

    def test_search_no_metadatas_fallback(self, store):
        store.collection.query.return_value = {
            "documents": [["doc1"]],
            "distances": [[0.5]],
        }
        results = store.search("test")
        assert len(results) == 1
        assert results[0]["document"] == "doc1"
        assert results[0]["metadata"] == {}
        assert results[0]["distance"] == 0.5

    def test_search_no_collection(self, store):
        store.collection = None
        with pytest.raises(RuntimeError, match="not initialized"):
            store.search("test")

    def test_search_passes_n_results(self, store):
        store.collection.query.return_value = {"documents": [[]]}
        store.search("query", n_results=10)
        store.collection.query.assert_called_once_with(
            query_texts=["query"], n_results=10
        )


class TestVectorStoreClose:
    def test_close(self):
        mock_chroma = MagicMock()
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_chroma.PersistentClient.return_value = mock_client
        mock_client.get_or_create_collection.return_value = mock_collection
        with patch("src.agentframework.vector.chromadb", mock_chroma):
            store = VectorStore(persist_directory="/tmp/vector_test")
        store.close()
        mock_client.close.assert_called_once()

    def test_close_no_client(self):
        store = VectorStore.__new__(VectorStore)
        store.close()

    def test_close_exception_handling(self):
        mock_chroma = MagicMock()
        mock_client = MagicMock()
        mock_chroma.PersistentClient.return_value = mock_client
        mock_client.close.side_effect = Exception("close failed")
        with patch("src.agentframework.vector.chromadb", mock_chroma):
            store = VectorStore(persist_directory="/tmp/vector_test")
        store.close()
