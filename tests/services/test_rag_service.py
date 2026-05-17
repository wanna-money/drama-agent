"""Tests for RAG service."""
import pytest
import tempfile
import os


def test_rag_seeds_prompt_templates(tmp_path):
    """RAG service should seed prompt templates on first run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Patch settings to use temp dir
        import drama_agent.config as config_module
        original = config_module.settings.chroma_dir
        config_module.settings.chroma_dir = tmpdir

        from drama_agent.services.rag_service import RAGService
        svc = RAGService()
        results = svc.query_prompt_templates("CU", "seedance", n_results=2)
        assert len(results) > 0
        assert any("Close-up" in r or "近景" in r or "CU" in r for r in results)

        config_module.settings.chroma_dir = original


def test_rag_saves_and_retrieves_character(tmp_path):
    """Save and retrieve character profile from RAG."""
    with tempfile.TemporaryDirectory() as tmpdir:
        import drama_agent.config as config_module
        config_module.settings.chroma_dir = tmpdir

        from drama_agent.services.rag_service import RAGService
        svc = RAGService()
        svc.save_character_profile("proj1", "Alice", "Short brown hair, blue eyes, red dress")
        result = svc.get_character_description("proj1", "Alice")
        assert result == "Short brown hair, blue eyes, red dress"
