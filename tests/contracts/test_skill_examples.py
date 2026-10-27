"""Normal-agent skill contract: short default recipe, links for rare operations."""
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / 'docs/llm/vibepublish-social-skill.md'


class SkillExamplesTests(unittest.TestCase):
    def test_normal_recipe_is_short_and_executable(self):
        text = SKILL.read_text()
        recipe = text.split('## Обычная публикация — короткий рецепт', 1)[1].split(
            '## Boundaries and exceptional paths', 1
        )[0].strip()
        self.assertLessEqual(len(recipe.splitlines()), 40)
        for phrase in ('vibepublish_get_started', 'vibepublish_visual',
                       'vibepublish_publish', 'vibepublish_status',
                       '"wait_final":true', 'request_key', 'summary.networks'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, recipe)
        for forbidden in ('import_begin', 'import_chunk', 'retry_failed',
                          'review_outcome', 'source_sha256'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, recipe)

    def test_rare_flows_are_linked_not_inlined(self):
        text = SKILL.read_text()
        self.assertIn('Version: `1.7.1`', text)
        for path in ('mcp-contract-v1.md', 'asset-ingress.md', 'media-store/README.md',
                     'vk-media-binding.md', 'network-footers.md',
                     'telegram-custom-emoji-v1.md'):
            with self.subTest(path=path):
                self.assertIn(path, text)
        self.assertIn('No manual LLM base64 or SHA-256', text)
        self.assertNotIn('## Native forwarding', text)


if __name__ == '__main__':
    unittest.main()
