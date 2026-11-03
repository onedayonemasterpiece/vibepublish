"""Native MAX attachments remain visible without downloaded-byte evidence."""
import json
from dataclasses import asdict

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from adapters.max.bridge import MaxAdapter
from contracts.social_mcp_v1 import DEFS
from social_operations.service import Application
from social_operations.storage import Store


@pytest.mark.parametrize('count', [1, 2])
@pytest.mark.parametrize('stored_binding', [False, True])
def test_max_read_projects_ordered_existing_media_without_download(tmp_path, count, stored_binding):
    store = Store(tmp_path / 'ledger.sqlite')
    actor = store.authenticate(store.create_principal('t', 'owner', owner=True))
    store.add_connection(actor, 'max', 'max', account_type='max_web', secret_ref='VIBEPUBLISH_MAX_PROFILE')
    store.bind(actor, 'owner', 'max', 'max', '-101')
    refs = [f'https://cdn.example/{i}?signed=private' for i in range(count)]
    remote = MaxAdapter._remote(dict(id='native-post', target='-101', namespace='feed',
        text='Photo caption', entities=[], media=refs, scheduled_at=None,
        observed_at='2026-11-03T20:24:49Z'))
    with store.tx() as db:
        binding = store.binding(db, actor, alias='max')
        if stored_binding:
            binding = db.execute('SELECT * FROM bindings WHERE id=?', (binding['id'],)).fetchone()
        item = Application(store).project_item(db, actor, binding, asdict(remote))
        saved = json.loads(db.execute('SELECT snapshot FROM item_refs WHERE id=?', (item['ref'],)).fetchone()[0])
    assert item['media'] == [{'source': {'kind': 'existing', 'position': i}, 'role': 'auto'} for i in range(count)]
    assert saved['provider_media'] == refs
    assert 'media_evidence' not in item and 'cdn.example' not in json.dumps(item)
    Draft202012Validator({'$ref': '#/$defs/read_item', '$defs': DEFS},
        format_checker=FormatChecker()).validate(item)
