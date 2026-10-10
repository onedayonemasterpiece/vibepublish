"""Cross-channel footer regression: real plan generation, semantic links and safety."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from social_operations.domain import DomainError
from social_operations.network_footers import ROUTES, append_network_footer
from social_operations.rich_text import normalized_entities, utf16
from social_operations.service import Application
from social_operations.storage import Store


class NetworkFooterUnitTests(unittest.TestCase):
    targets = {
        "lovekenig_tg": {"provider": "telegram", "native_id": "-10011", "handle": "@fixture_love"},
        "tg_74cd62f2688ba88ab5fd": {"provider": "telegram", "native_id": "-10022", "handle": "https://t.me/fixture_events"},
        "lovekenig_vk": {"provider": "vk", "native_id": "-11"},
        "vk_972b45c6f71c0f2a1fb9": {"provider": "vk", "native_id": "-22"},
        "vk_027d33367c33ba2599ee": {"provider": "vk", "native_id": "-33"},
        "max_lovekenig_announcements": {"provider": "max", "native_id": "-44"},
        "tg_5060f37d74cf460135ee": {"provider": "telegram", "native_id": "-10055"},
    }

    def compile(self, source, provider, content, *, has_media=False):
        return append_network_footer(source, provider, content,
                                     self.targets.__getitem__, has_media=has_media)

    def test_each_route_is_semantic_and_ordered(self):
        expected = {
            "lovekenig_tg": ("https://t.me/fixture_love", "https://vk.com/club11"),
            "tg_74cd62f2688ba88ab5fd": (
                "https://t.me/fixture_events", "https://vk.com/club22", "https://max.ru/channel_kenigevents"),
            "tg_5060f37d74cf460135ee": (
                "https://t.me/kenigevents", "https://vk.com/club33", "https://max.ru/channel_kenigevents"),
            "max_lovekenig_announcements": (
                "https://max.ru/channel_kenigevents", "https://vk.com/club22", "https://t.me/kenigevents"),
        }
        for source, urls in expected.items():
            with self.subTest(source=source):
                provider = "max" if source.startswith("max_") else "telegram"
                before = {"text": "🌊 Событие"}
                result = self.compile(source, provider, before)
                self.assertEqual(before, {"text": "🌊 Событие"})  # Immutable original.
                self.assertEqual(
                    tuple(e["url"] for e in result["entities"] if e["type"] == "text_link"),
                    urls,
                )
                self.assertIn("\n\n", result["text"])
                self.assertIn("  ·  ", result["text"] if len(urls) > 1 else "  ·  ")
                self.assertEqual(
                    result["format"],
                    "max_entities" if provider == "max" else "telegram_entities",
                )
                self.assertEqual(self.compile(source, provider, result), result)
                self.assertEqual(len(result["entities"]), len(urls))
                normalized_entities(result["text"], result["entities"])

    def test_utf16_offsets_and_original_format_survive(self):
        text = "🎨 Событие"
        content = {"text": text, "format": "telegram_entities",
                   "entities": [{"type": "bold", "offset": 3, "length": 7}],
                   "emoji_snapshot": [{"original": "kept"}]}
        result = self.compile("lovekenig_tg", "telegram", content)
        self.assertEqual(result["entities"][0], content["entities"][0])
        self.assertEqual(result["entities"][1]["offset"], utf16(text + "\n\n"))
        self.assertEqual(result["emoji_snapshot"], content["emoji_snapshot"])
        self.assertEqual(content["text"], text)

    def test_idempotent_media_only_post_without_newline(self):
        post = self.compile("lovekenig_tg", "telegram", {"text": ""}, has_media=True)
        self.assertEqual(post["text"], "Подписаться  ·  ВКонтакте")
        self.assertEqual(self.compile("lovekenig_tg", "telegram", post, has_media=True), post)

    def test_semantic_existing_footer_detects_vk_public_alias_without_byte_match(self):
        text = "Событие\n\n  vk  "
        content = {"text": text, "format": "telegram_entities", "entities": [
            {"type": "text_link", "offset": utf16("Событие\n\n  "), "length": 2,
             "url": "https://vk.ru/public11/"}]}
        result = self.compile("lovekenig_tg", "telegram", content)
        self.assertEqual(result["text"], "Событие\n\nПодписаться  ·  ВКонтакте")
        self.assertEqual(len(result["entities"]), 2)
        self.assertEqual(self.compile("lovekenig_tg", "telegram", result), result)

    def test_body_reference_does_not_suppress_real_footer(self):
        text = "Про наш канал в VK"
        content = {"text": text, "format": "telegram_entities", "entities": [
            {"type": "text_link", "offset": utf16("Про наш канал в "),
             "length": 2, "url": "https://vk.com/club11"}]}
        result = self.compile("lovekenig_tg", "telegram", content)
        self.assertEqual(len(result["entities"]), 3)
        self.assertTrue(result["text"].endswith("\n\nПодписаться  ·  ВКонтакте"))

    def test_non_target_is_untouched_and_missing_target_fails_closed(self):
        content = {"text": "Событие"}
        self.assertIs(self.compile("vk_random", "vk", content), content)
        with self.assertRaises(DomainError) as context:
            append_network_footer("lovekenig_tg", "telegram", content, lambda alias: None)
        self.assertFalse(context.exception.code == "empty_publication")

    def test_overflow_fails_before_provider_and_without_truncating_body(self):
        with self.assertRaises(DomainError) as context:
            self.compile("lovekenig_tg", "telegram", {"text": "А" * 4088})
        self.assertEqual(context.exception.code, "network_footer_limit")
        with self.assertRaises(DomainError):
            self.compile("lovekenig_tg", "telegram", {"text": "А" * 1017},
                         has_media=True)


    def test_current_url_is_required_and_never_inferred_from_label_or_id(self):
        targets = dict(self.targets)
        targets["lovekenig_tg"] = {"provider": "telegram", "native_id": "-10011",
                                  "label": "fixture_love", "handle": ""}
        with self.assertRaises(DomainError) as context:
            append_network_footer("lovekenig_tg", "telegram", {"text": "Событие"},
                                  targets.get)
        self.assertEqual(context.exception.code, "network_footer_source_url_unavailable")

    def test_current_link_moves_first_and_duplicate_urls_are_removed(self):
        text = "Событие\n\nVK · Канал · Ещё VK"
        entities = []
        for label, url in [("VK", "https://vk.com/club11"),
                           ("Канал", "https://t.me/fixture_love"),
                           ("Ещё VK", "https://vk.ru/public11/")]:
            offset = text.index(label)
            entities.append({"type": "text_link", "offset": utf16(text[:offset]),
                             "length": utf16(label), "url": url})
        result = self.compile("lovekenig_tg", "telegram",
                              {"text": text, "format": "telegram_entities", "entities": entities})
        self.assertEqual(result["text"], "Событие\n\nПодписаться  ·  ВКонтакте")
        self.assertEqual(len(result["entities"]), 2)
        self.assertEqual(self.compile("lovekenig_tg", "telegram", result), result)

    def test_unlisted_vk_native_markup_is_unchanged(self):
        content = {"text": "Событие\n\n[club11|Подписаться] · https://t.me/fixture_love"}
        self.assertIs(self.compile("lovekenig_vk", "vk", content), content)

    def test_unlisted_eventsbot_max_footer_is_not_added_again(self):
        content = {"text": "Дайджест\n\nПодписаться · Телеграм · Вконтакте",
                   "format": "max_entities", "entities": [
                       {"type": "text_link", "offset": 10, "length": 11,
                        "url": "https://max.ru/channel_uh_kaliningrad"}]}
        self.assertIs(self.compile("max_excursion_fixture", "max", content), content)


class NetworkFooterPlanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "ledger.sqlite")
        token = self.store.create_principal("tenant", "owner", owner=True)
        self.actor = self.store.authenticate(token)
        for provider in ("telegram", "vk", "max"):
            self.store.add_connection(self.actor, "conn_" + provider, provider,
                                      account_type="fake", shared=True)
        self.native_ids = {
            "lovekenig_tg": "-100111",
            "tg_74cd62f2688ba88ab5fd": "-100222",
            "tg_5060f37d74cf460135ee": "-100333",
            "max_lovekenig_announcements": "-444",
            "lovekenig_vk": "-111",
            "vk_972b45c6f71c0f2a1fb9": "-222",
            "vk_027d33367c33ba2599ee": "-333",
        }
        for alias, ident in self.native_ids.items():
            provider = "max" if alias.startswith("max_") else "vk" if alias.startswith("vk_") or alias == "lovekenig_vk" else "telegram"
            self.store.bind(self.actor, "owner", alias, "conn_" + provider, ident,
                            handle="@fixture_" + alias if provider == "telegram" else "")
        self.store.bind(self.actor, "owner", "other_tg", "conn_telegram", "-100999")
        self.app = Application(self.store)

    async def _plan(self, to, text="Анонс"):
        r = await self.app.call(self.actor, "vibepublish_publish",
                                {"to": [to], "content": {"text": text}})
        self.assertEqual(r["state"], "accepted", r)
        with self.store.connection() as db:
            row = db.execute("SELECT plan FROM attempts WHERE operation_id=?", (r["operation_id"],)).fetchone()
        return json.loads(row["plan"])

    async def test_compile_is_in_provider_plan_not_only_model_skill(self):
        for alias in ROUTES:
            with self.subTest(alias=alias):
                plan = await self._plan(alias)
                compiled = json.loads(plan["content_json"])
                self.assertEqual(len(compiled["entities"]), len(ROUTES[alias]) + 1)
                self.assertTrue(compiled["text"].split("\n")[-1].startswith("Подписаться"))
                self.assertTrue(compiled["text"].startswith("Анонс\n\n"))
                self.assertIn("·", compiled["text"] if len(ROUTES[alias]) > 1 else "·")
        other = await self._plan("other_tg")
        self.assertEqual(json.loads(other["content_json"]), {"text": "Анонс"})

    async def test_empty_original_remains_invalid(self):
        r = await self.app.call(self.actor, "vibepublish_publish",
                                {"to": ["lovekenig_tg"], "content": {"text": ""}})
        self.assertEqual(r["error"]["code"], "empty_publication")
