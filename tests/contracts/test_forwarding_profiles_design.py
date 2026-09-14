"""Design checks, not provider/access/runtime tests. Run with unittest discovery."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jsonschema import Draft202012Validator, FormatChecker
from contracts.social_mcp_v1 import catalog, project_catalog

TOOLS = {t['name']: t for t in catalog()['tools']}

def valid(tool, args):
    return Draft202012Validator(TOOLS['vibepublish_' + tool]['inputSchema'],
        format_checker=FormatChecker()).is_valid(args)

def forward(source='https://t.me/venue/123', **extra):
    return {'command': {'kind': 'forward', 'item_ref': source, 'to': ['announcements_tg'], **extra}}

# Grammar-valid cases include runtime denials; labels are requirements, not simulated outcomes.
CASES = [
    ('Перешли пост площадки из Telegram', 'engage', forward(), 'native_forward_origin_readback'),
    ('Сделай репост ВК', 'engage', forward('https://vk.ru/wall-123_456', to=['announcements_vk']), 'native_vk_repost'),
    ('Используй ссылку vk.com', 'engage', forward('https://vk.com/wall-123_456', to=['announcements_vk']), 'normalize_same_native_source'),
    ('Перешли полученное сообщение', 'engage', forward('incoming_1'), 'require_owned_incoming_reference'),
    ('Перешли весь альбом Telegram', 'engage', forward(selection='post'), 'verify_grouped_source_and_target_items'),
    ('Перешли только выбранное сообщение', 'engage', forward(selection='message'), 'one_message_only'),
    ('Отложи форвард Telegram', 'engage', forward(delivery={'kind':'at','at':'2026-09-06T12:00:00+02:00'}), 'native_schedule_only'),
    ('Отложи репост VK', 'engage', forward('https://vk.ru/wall-123_456', to=['announcements_vk'], delivery={'kind':'at','at':'2026-09-06T12:00:00+02:00'}), 'deny_until_native_repost_schedule_proved'),
    ('Сначала покажи форвард', 'engage', forward(mode='preview'), 'no_provider_write'),
    ('Перешли публичный пост чужого канала', 'engage', forward('https://t.me/public_venue/12'), 'exact_public_source_only_no_feed_grant'),
    ('Перешли приватный пост, видимый только оператору', 'engage', forward('https://t.me/c/123/456'), 'deny_without_caller_source_authority'),
    ('Перешли Telegram в смешанный набор площадок', 'engage', forward(to=['all_platforms']), 'reject_incompatible_targets_before_any_mutation'),
    ('Найди мои прошлые пересылки', 'read', {'query': {'kind':'history','author':'mine','publication_kind':'forward'}}, 'local_history_with_current_authorization'),
    ('Запомни назначение канала', 'destinations', {'command': {'kind':'profile_update','alias':'announcements_tg','expected_revision':0,'profile':{'purpose':'Анонсы концертов'}}}, 'persist_personal_profile_not_provider_title'),
    ('Добавь основные каналы и правила выбора', 'destinations', {'command': {'kind':'profile_update','alias':'announcements_tg','expected_revision':1,'profile':{'usage':'primary','topics':['концерты'],'avoid_topics':['личное'],'selection':'agent_may_choose'}}}, 'cas_profile_then_bump_routing_revision'),
    ('Удали мой комментарий к каналу', 'destinations', {'command': {'kind':'profile_update','alias':'announcements_tg','expected_revision':2,'profile':{'notes':''}}}, 'clear_notes_only'),
    ('Дай раздел скилла о пересылках', 'get_started', {'section':'forwarding'}, 'canonical_skill_text_and_examples'),
    ('Дай раздел скилла об основных каналах', 'get_started', {'section':'destinations'}, 'canonical_skill_plus_authorized_profiles'),
    ('Дай весь готовый скилл', 'get_started', {'section':'all'}, 'one_skill_no_synonym_tool'),
    ('Публикуй по выбранному назначению из настроек', 'publish', {'to':['announcements_tg'],'content':{'text':'Анонс'},'routing_revision':3}, 'reject_stale_routing_before_dispatch'),
]
INVALID = [
    ('engage', forward('http://t.me/venue/1')),
    ('engage', forward('file:///etc/passwd')),
    ('engage', forward(selection='copy')),
    ('engage', forward(drop_author=True)),
    ('engage', forward(content={'text':'Рерайт'})),
    ('engage', forward(copy_if_forbidden=True)),
    ('engage', forward(delivery={'kind':'at','at':'2026-09-06T12:00:00Z','backend':'service'})),
    ('engage', forward(delivery={'kind':'at','at':'2026-09-06T12:00:00'})),
    ('destinations', {'command':{'kind':'profile_update','alias':'x','expected_revision':0,'profile':{}}}),
    ('destinations', {'command':{'kind':'profile_update','alias':'x','profile':{'purpose':'x'}}}),
    ('destinations', {'command':{'kind':'profile_update','alias':'x','expected_revision':0,'profile':{'grant_admin':True}}}),
    ('destinations', {'command':{'kind':'profile_update','alias':'x','expected_revision':0,'profile':{'selection':'publish_everything'}}}),
    ('publish', {'to':['x'],'content':{'text':'x'},'routing_revision':0}),
    ('get_started', {'section':'secrets'}),
]

class ForwardingProfilesDesignTests(unittest.TestCase):
    def test_twenty_new_golden_calls(self):
        self.assertEqual(len(CASES), 20)
        for text, tool, args, oracle in CASES:
            with self.subTest(job=text):
                self.assertTrue(oracle)
                self.assertTrue(valid(tool, args))

    def test_fourteen_negative_calls(self):
        self.assertEqual(len(INVALID), 14)
        for tool, args in INVALID:
            with self.subTest(args=args):
                self.assertFalse(valid(tool, args))

    def test_existing_tool_count_no_skill_or_forward_alias(self):
        self.assertEqual(len(TOOLS), 8)
        self.assertNotIn('vibepublish_skill_get', TOOLS)
        self.assertNotIn('vibepublish_forward', TOOLS)

    def test_forward_permission_does_not_expose_react_reply(self):
        scopes = {'bootstrap','publish','status','forward','destination.profile'}
        projected = {t['name']: t for t in project_catalog(scopes, publish_destinations=['announcements_tg'])}
        self.assertIn('vibepublish_read', projected)
        branches = projected['vibepublish_engage']['inputSchema']['properties']['command']['oneOf']
        self.assertEqual([b['properties']['kind']['const'] for b in branches], ['forward'])
        branches = projected['vibepublish_destinations']['inputSchema']['properties']['command']['oneOf']
        self.assertEqual({b['properties']['kind']['const'] for b in branches}, {'list','profile_update','emoji_set_register','emoji_alias_select','emoji_rule_put'})

    def test_unbound_task_scope_does_not_inherit_tools(self):
        projected = {t['name'] for t in project_catalog({'publish','forward','destination.profile'})}
        self.assertNotIn('vibepublish_engage', projected)
        self.assertNotIn('vibepublish_destinations', projected)

    def test_profile_contains_no_identity_or_grant_fields(self):
        d = TOOLS['vibepublish_get_started']['outputSchema']['$defs']['destination_profile']
        self.assertEqual(set(d['properties']), {'usage','purpose','audience','topics','avoid_topics','notes','selection'})
        self.assertFalse(d['additionalProperties'])

    def test_forward_origin_evidence_is_typed(self):
        d = TOOLS['vibepublish_engage']['outputSchema']['$defs']['forward_origin']
        v = Draft202012Validator(d)
        sample = {'source_ref':'source_1','provider':'telegram','mode':'native','origin_check':'matched'}
        self.assertTrue(v.is_valid(sample))
        sample['mode'] = 'rewritten'
        self.assertFalse(v.is_valid(sample))

    def test_updated_schemas_remain_valid_and_deterministic(self):
        for item in TOOLS.values():
            Draft202012Validator.check_schema(item['inputSchema'])
            Draft202012Validator.check_schema(item['outputSchema'])
        self.assertEqual(catalog()['version'], '1.5.0-runtime')
        self.assertEqual(catalog()['tools'], list(TOOLS.values()))

if __name__ == '__main__':
    unittest.main(verbosity=2)
