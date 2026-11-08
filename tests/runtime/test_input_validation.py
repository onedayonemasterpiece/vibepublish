"""Real SQLite and public-call checks; no live tools, renderer or provider."""
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator

from contracts.social_mcp_v1 import catalog
from social_operations.domain import DomainError, OutcomeUnknown
from social_operations.service import Application
from social_operations.storage import Store


@pytest.fixture
def runtime(tmp_path):
    store = Store(tmp_path / 'ledger.sqlite')
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    return store, actor, Application(store)


def counts(store):
    with store.connection() as db:
        return {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                for table in ('operations', 'carousel_versions', 'request_keys', 'attempts', 'assets')}


@pytest.mark.asyncio
@pytest.mark.parametrize('args,field,rule', [
    ({'command': {'kind': 'create', 'brief': 'private author words'}},
     'request_key', 'required'),
    ({'command': {'kind': 'create', 'brief': 'private author words' + 'x' * 12000},
      'request_key': 'private-key'}, 'command.brief', 'maxLength 12000'),
    ({'command': {'kind': 'create', 'brief': 'private author words', 'note': 'private note'},
      'request_key': 'private-key'}, 'command.note', 'additionalProperties false'),
])
async def test_invalid_input_is_precise_before_dispatch_and_any_write(runtime, args, field, rule, caplog):
    store, actor, app = runtime
    before = counts(store)
    with patch.object(app.carousels, 'command') as handler:
        with caplog.at_level('INFO', logger='social_operations.service'):
            result = await app.call(actor, 'vibepublish_carousel', args)
        handler.assert_not_called()
    assert counts(store) == before == dict.fromkeys(before, 0)
    assert result == {
        'error': {'code': 'invalid_input', 'field': field, 'message': field + ': ' + rule},
        'message': field + ': ' + rule, 'next_action': 'fix_input', 'retry_safe': True,
    }
    schema = next(t['outputSchema'] for t in catalog()['tools'] if t['name'] == 'vibepublish_carousel')
    Draft202012Validator(schema).validate(result)
    for private in ('private author words', 'private note', 'private-key'):
        assert private not in json.dumps(result) and private not in caplog.text


@pytest.mark.asyncio
async def test_s01_example_creates_once_and_replays_the_same_key(runtime):
    store, actor, app = runtime
    text = (Path(__file__).resolve().parents[2] / 'docs/llm/carousel/steps/s01.md').read_text()
    args = json.loads(re.search(r'```json\s*(\{.*?\})\s*```', text, re.S).group(1))
    first = await app.call(actor, 'vibepublish_carousel', args)
    replay = await app.call(actor, 'vibepublish_carousel', args)
    assert first['operation_id'] == replay['operation_id']
    assert first['carousel_id'] == replay['carousel_id']
    assert first['private'] is True and first['scene_ready'] is False
    assert counts(store) == {'operations': 1, 'carousel_versions': 1, 'request_keys': 1,
                             'attempts': 0, 'assets': 0}


@pytest.mark.asyncio
async def test_non_schema_and_unknown_failures_do_not_become_retryable(runtime):
    store, actor, app = runtime
    result = await app.call(actor, 'vibepublish_carousel', {
        'command': {'kind': 'get', 'scope': 'story', 'carousel_id': 'carousel_missing'}})
    assert result['error']['code'] == 'carousel_not_available'
    assert result['retry_safe'] is False
    with patch.object(app.carousels, 'command', side_effect=OutcomeUnknown()):
        result = await app.call(actor, 'vibepublish_carousel', {
            'command': {'kind': 'create', 'brief': 'valid input'}, 'request_key': 'unknown'})
    assert result['error']['code'] == 'outcome_unknown'
    assert result['next_action'] == 'review_outcome' and result['retry_safe'] is False
    assert DomainError('invalid_input').output()['retry_safe'] is False
    # The internal service guard is distinct from public schema validation.
    with pytest.raises(DomainError) as missing:
        app.carousels.command(actor, {'command': {'kind': 'create', 'brief': 'internal call'}})
    assert missing.value.code == 'carousel_request_key_required'
    assert missing.value.output()['retry_safe'] is False
    assert all(value == 0 for value in counts(store).values())
