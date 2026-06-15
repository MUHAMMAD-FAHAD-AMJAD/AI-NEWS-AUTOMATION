"""
orchestrator/llm/__init__.py
------------------------------
Public API for the LLM package.
Exports summarize_with_fallback only — callers never import providers directly.
"""

from orchestrator.llm.summarizer import summarize_with_fallback

__all__ = ["summarize_with_fallback"]
