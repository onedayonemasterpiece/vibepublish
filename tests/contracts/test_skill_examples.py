"""Canonical skill text/examples, not a weak-agent effectiveness benchmark."""
import json
import re
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from contracts.social_mcp_v1 import catalog

SKILL = Path(__file__).resolve().parents[2]/'docs/llm/vibepublish-social-skill.md'


class SkillExamplesTests(unittest.TestCase):
    def test_all_tagged_examples_match_the_canonical_schema(self):
        tools = {t['name']: t for t in catalog()['tools']}
        current = None
        count = 0
        tokens = re.split(r'(### `vibepublish_[a-z_]+`[^\n]*\n)', SKILL.read_text())
        for token in tokens:
            heading = re.match(r'### `(vibepublish_[a-z_]+)`', token)
            if heading:
                current = heading.group(1)
            else:
                for source in re.findall(r'```json\n(.*?)\n```', token, flags=re.S):
                    self.assertIsNotNone(current)
                    Draft202012Validator(tools[current]['inputSchema'], format_checker=FormatChecker()).validate(json.loads(source))
                    count += 1
        self.assertGreaterEqual(count, 8)

    def test_current_skill_contains_forwarding_routing_and_offline_boundary(self):
        text = SKILL.read_text()
        for phrase in ('Version: `1.5.0`', '## Native forwarding', '## Saved editorial destinations',
                       'routing_revision', 'expected_revision', '## Current offline implementation boundary'):
            self.assertIn(phrase, text)


if __name__ == '__main__':
    unittest.main()
