"""Regression tests for VK mention markup render, person/group, stale candidate, and readback normalization."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path

import pytest

from social_operations.rich_text import compile_content
from social_operations.vk_mentions import (
    VKMention,
    validate_registry_entry,
    resolve_mention,
    discover_mentions,
    validate_mention,
    normalize_vk_mentions_for_comparison,
    vk_mentions_equal,
    load_registry,
    CACHE_FILE,
    REGISTRY_URL,
)


class TestVKMentionRegistry:
    """Tests for VK mention registry loading and validation."""

    def setup_method(self):
        # Create a temporary cache file for testing
        self.temp_dir = tempfile.mkdtemp()
        self.temp_cache = Path(self.temp_dir) / "vk_mentions_registry.json"
        # Save original cache path and override
        import social_operations.vk_mentions as vk_mentions
        self.original_cache_file = vk_mentions.CACHE_FILE
        vk_mentions.CACHE_FILE = self.temp_cache

        # Write test registry to cache
        test_registry = {
            "entries": [
                {
                    "target_ref": "lovekenig",
                    "type": "club",
                    "numeric_id": 241261191,
                    "display_name": "Полюбить Калининград",
                    "verified": True
                },
                {
                    "target_ref": "ivan_petrov",
                    "type": "id",
                    "numeric_id": 123456789,
                    "display_name": "Иван Петров",
                    "verified": True
                },
                {
                    "target_ref": "unverified_group",
                    "type": "club",
                    "numeric_id": 999999999,
                    "display_name": "Unverified Group",
                    "verified": False
                },
                {
                    "target_ref": "stale_candidate",
                    "type": "id",
                    "numeric_id": 555555555,
                    "display_name": "Stale Candidate",
                    "verified": False
                }
            ]
        }
        with self.temp_cache.open("w", encoding="utf-8") as f:
            json.dump(test_registry, f, ensure_ascii=False)

    def teardown_method(self):
        import social_operations.vk_mentions as vk_mentions
        vk_mentions.CACHE_FILE = self.original_cache_file
        # Clean up temp files
        if self.temp_cache.exists():
            self.temp_cache.unlink()
        os.rmdir(self.temp_dir)

    def test_validate_registry_entry_club(self):
        entry = {
            "target_ref": "lovekenig",
            "type": "club",
            "numeric_id": 241261191,
            "display_name": "Полюбить Калининград",
            "verified": True
        }
        mention = validate_registry_entry(entry)
        assert mention.target_ref == "lovekenig"
        assert mention.type == "club"
        assert mention.numeric_id == 241261191
        assert mention.display_name == "Полюбить Калининград"
        assert mention.markup == "[club241261191|Полюбить Калининград]"
        assert mention.verified is True

    def test_validate_registry_entry_id(self):
        entry = {
            "target_ref": "ivan_petrov",
            "type": "id",
            "numeric_id": 123456789,
            "display_name": "Иван Петров",
            "verified": True
        }
        mention = validate_registry_entry(entry)
        assert mention.target_ref == "ivan_petrov"
        assert mention.type == "id"
        assert mention.numeric_id == 123456789
        assert mention.display_name == "Иван Петров"
        assert mention.markup == "[id123456789|Иван Петров]"
        assert mention.verified is True

    def test_validate_registry_entry_invalid_type(self):
        entry = {
            "target_ref": "test",
            "type": "invalid",
            "numeric_id": 123,
            "display_name": "Test",
            "verified": True
        }
        with pytest.raises(Exception) as exc:
            validate_registry_entry(entry)
        assert exc.value.code == "vk_mention_invalid"

    def test_validate_registry_entry_invalid_numeric_id(self):
        entry = {
            "target_ref": "test",
            "type": "club",
            "numeric_id": -1,
            "display_name": "Test",
            "verified": True
        }
        with pytest.raises(Exception) as exc:
            validate_registry_entry(entry)
        assert exc.value.code == "vk_mention_invalid"

    def test_resolve_mention_unverified_raises(self):
        with pytest.raises(Exception) as exc:
            resolve_mention("unverified_group")
        assert exc.value.code == "vk_mention_unverified"

    def test_resolve_mention_not_found_raises(self):
        with pytest.raises(Exception) as exc:
            resolve_mention("nonexistent")
        assert exc.value.code == "vk_mention_not_found"

    def test_discover_mentions_empty_query(self):
        results = discover_mentions("")
        assert len(results) == 4  # All entries
        target_refs = {r["target_ref"] for r in results}
        assert target_refs == {"lovekenig", "ivan_petrov", "unverified_group", "stale_candidate"}

    def test_discover_mentions_with_query(self):
        results = discover_mentions("ivan")
        assert len(results) == 1
        assert results[0]["target_ref"] == "ivan_petrov"

    def test_discover_mentions_limit(self):
        results = discover_mentions("", limit=2)
        assert len(results) == 2

    def test_validate_mention(self):
        result = validate_mention("lovekenig")
        assert result["target_ref"] == "lovekenig"
        assert result["type"] == "club"
        assert result["numeric_id"] == 241261191
        assert result["display_name"] == "Полюбить Калининград"
        assert result["markup"] == "[club241261191|Полюбить Калининград]"
        assert result["verified"] is True


class TestVKMentionNormalization:
    """Tests for VK mention normalization for readback equivalence."""

    def test_normalize_alt_club_syntax(self):
        text = "Hello @club241261191 (Полюбить Калининград) world"
        normalized = normalize_vk_mentions_for_comparison(text)
        assert normalized == "Hello [club241261191|Полюбить Калининград] world"

    def test_normalize_alt_id_syntax(self):
        text = "Hello @id123456789 (Иван Петров) world"
        normalized = normalize_vk_mentions_for_comparison(text)
        assert normalized == "Hello [id123456789|Иван Петров] world"

    def test_normalize_multiple_mentions(self):
        text = "@club241261191 (Полюбить Калининград) and @id123456789 (Иван Петров)"
        normalized = normalize_vk_mentions_for_comparison(text)
        assert normalized == "[club241261191|Полюбить Калининград] and [id123456789|Иван Петров]"

    def test_normalize_canonical_unchanged(self):
        text = "Hello [club241261191|Полюбить Калининград] world"
        normalized = normalize_vk_mentions_for_comparison(text)
        assert normalized == text

    def test_normalize_mixed_syntax(self):
        text = "[club241261191|Полюбить Калининград] and @id123456789 (Иван Петров)"
        normalized = normalize_vk_mentions_for_comparison(text)
        assert normalized == "[club241261191|Полюбить Калининград] and [id123456789|Иван Петров]"

    def test_vk_mentions_equal_canonical_vs_alt(self):
        expected = "Hello [club241261191|Полюбить Калининград] world"
        observed = "Hello @club241261191 (Полюбить Калининград) world"
        assert vk_mentions_equal(expected, observed) is True

    def test_vk_mentions_equal_both_canonical(self):
        expected = "Hello [club241261191|Полюбить Калининград] world"
        observed = "Hello [club241261191|Полюбить Калининград] world"
        assert vk_mentions_equal(expected, observed) is True

    def test_vk_mentions_equal_both_alt(self):
        expected = "Hello @club241261191 (Полюбить Калининград) world"
        observed = "Hello @club241261191 (Полюбить Калининград) world"
        assert vk_mentions_equal(expected, observed) is True

    def test_vk_mentions_equal_different_content(self):
        expected = "Hello [club241261191|Полюбить Калининград] world"
        observed = "Hello [club241261191|Другой текст] world"
        assert vk_mentions_equal(expected, observed) is False

    def test_vk_mentions_equal_non_mention_text_exact(self):
        expected = "Hello world"
        observed = "Hello world"
        assert vk_mentions_equal(expected, observed) is True

    def test_vk_mentions_equal_non_mention_text_differs(self):
        expected = "Hello world"
        observed = "Hello there"
        assert vk_mentions_equal(expected, observed) is False


class TestVKMentionCompileContent:
    """Tests for VK mention compilation in rich_text.compile_content."""

    def setup_method(self):
        # Create a temporary cache file for testing
        self.temp_dir = tempfile.mkdtemp()
        self.temp_cache = Path(self.temp_dir) / "vk_mentions_registry.json"
        import social_operations.vk_mentions as vk_mentions
        self.original_cache_file = vk_mentions.CACHE_FILE
        vk_mentions.CACHE_FILE = self.temp_cache

        # Write test registry to cache
        test_registry = {
            "entries": [
                {
                    "target_ref": "lovekenig",
                    "type": "club",
                    "numeric_id": 241261191,
                    "display_name": "Полюбить Калининград",
                    "verified": True
                },
                {
                    "target_ref": "ivan_petrov",
                    "type": "id",
                    "numeric_id": 123456789,
                    "display_name": "Иван Петров",
                    "verified": True
                },
            ]
        }
        with self.temp_cache.open("w", encoding="utf-8") as f:
            json.dump(test_registry, f, ensure_ascii=False)

    def teardown_method(self):
        import social_operations.vk_mentions as vk_mentions
        vk_mentions.CACHE_FILE = self.original_cache_file
        if self.temp_cache.exists():
            self.temp_cache.unlink()
        os.rmdir(self.temp_dir)

    def test_compile_mention_club(self):
        content = {
            "paragraphs": [[
                {"kind": "text", "text": "Hello "},
                {"kind": "mention", "target_ref": "lovekenig", "label": "Полюбить Калининград"},
                {"kind": "text", "text": "!"}
            ]]
        }
        result = compile_content(content, lambda name: None, provider="vk")
        assert result["format"] == "plain"
        assert result["text"] == "Hello [club241261191|Полюбить Калининград]!"

    def test_compile_mention_id(self):
        content = {
            "paragraphs": [[
                {"kind": "text", "text": "Hello "},
                {"kind": "mention", "target_ref": "ivan_petrov", "label": "Иван Петров"},
                {"kind": "text", "text": "!"}
            ]]
        }
        result = compile_content(content, lambda name: None, provider="vk")
        assert result["format"] == "plain"
        assert result["text"] == "Hello [id123456789|Иван Петров]!"

    def test_compile_multiple_mentions(self):
        content = {
            "paragraphs": [[
                {"kind": "mention", "target_ref": "lovekenig", "label": "Полюбить Калининград"},
                {"kind": "text", "text": " and "},
                {"kind": "mention", "target_ref": "ivan_petrov", "label": "Иван Петров"}
            ]]
        }
        result = compile_content(content, lambda name: None, provider="vk")
        assert result["format"] == "plain"
        assert result["text"] == "[club241261191|Полюбить Калининград] and [id123456789|Иван Петров]"

    def test_compile_mention_unverified_raises(self):
        # Add unverified entry to registry
        import social_operations.vk_mentions as vk_mentions
        with self.temp_cache.open("r", encoding="utf-8") as f:
            registry = json.load(f)
        registry["entries"].append({
            "target_ref": "unverified",
            "type": "club",
            "numeric_id": 999,
            "display_name": "Unverified",
            "verified": False
        })
        with self.temp_cache.open("w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False)

        content = {
            "paragraphs": [[
                {"kind": "mention", "target_ref": "unverified", "label": "Unverified"}
            ]]
        }
        with pytest.raises(Exception) as exc:
            compile_content(content, lambda name: None, provider="vk")
        assert exc.value.code == "vk_mention_unverified"

    def test_compile_mention_not_found_raises(self):
        content = {
            "paragraphs": [[
                {"kind": "mention", "target_ref": "nonexistent", "label": "Nonexistent"}
            ]]
        }
        with pytest.raises(Exception) as exc:
            compile_content(content, lambda name: None, provider="vk")
        assert exc.value.code == "vk_mention_not_found"

    def test_compile_mention_telegram_raises(self):
        content = {
            "paragraphs": [[
                {"kind": "mention", "target_ref": "lovekenig", "label": "Полюбить Калининград"}
            ]]
        }
        with pytest.raises(Exception) as exc:
            compile_content(content, lambda name: None, provider="telegram")
        assert exc.value.code == "rich_fallback_needs_review"

    def test_compile_mention_max_raises(self):
        content = {
            "paragraphs": [[
                {"kind": "mention", "target_ref": "lovekenig", "label": "Полюбить Калининград"}
            ]]
        }
        with pytest.raises(Exception) as exc:
            compile_content(content, lambda name: None, provider="max", max_native=True)
        assert exc.value.code == "rich_fallback_needs_review"


class TestVKMentionWorkerComparison:
    """Tests for worker content readback comparison with VK mentions."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_cache = Path(self.temp_dir) / "vk_mentions_registry.json"
        import social_operations.vk_mentions as vk_mentions
        self.original_cache_file = vk_mentions.CACHE_FILE
        vk_mentions.CACHE_FILE = self.temp_cache

        test_registry = {
            "entries": [
                {
                    "target_ref": "lovekenig",
                    "type": "club",
                    "numeric_id": 241261191,
                    "display_name": "Полюбить Калининград",
                    "verified": True
                },
            ]
        }
        with self.temp_cache.open("w", encoding="utf-8") as f:
            json.dump(test_registry, f, ensure_ascii=False)

    def teardown_method(self):
        import social_operations.vk_mentions as vk_mentions
        vk_mentions.CACHE_FILE = self.original_cache_file
        if self.temp_cache.exists():
            self.temp_cache.unlink()
        os.rmdir(self.temp_dir)

    def test_worker_comparison_vk_mention_normalization(self):
        from social_operations.vk_mentions import vk_mentions_equal
        # Simulate the worker comparison logic
        plan = {
            "action": "publish",
            "provider": "vk",
            "content_json": json.dumps({"text": "Hello [club241261191|Полюбить Калининград]!", "format": "plain"}),
        }
        expected_text = json.loads(plan["content_json"])["text"]
        observed_text = "Hello @club241261191 (Полюбить Калининград)!"

        # This is the comparison logic from worker.py
        if plan["provider"] == "vk":
            assert vk_mentions_equal(expected_text, observed_text) is True
        else:
            assert expected_text == observed_text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])