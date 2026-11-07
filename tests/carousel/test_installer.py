"""A malformed addition cannot replace a working private reference catalog."""
import json
import pytest
from PIL import Image

from scripts.ops.install_carousel_references import install
from social_operations.carousel_references import ReferenceBank
from social_operations.domain import DomainError
from social_operations.storage import Store


def test_bank_growth_validates_before_replacing_catalog(tmp_path):
    store = Store(tmp_path / 'ledger.sqlite')
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    incoming = tmp_path / 'incoming'; incoming.mkdir()
    Image.new('RGB', (30, 20), 'red').save(incoming / 'one.png')
    row = {'id': 'E01', 'file': 'one.png', 'title': 'Панель', 'tags': ['панель'],
        'look_for': 'Общая зона', 'transfer': 'Объединить два кадра',
        'source': {'slack_url': 'https://example.slack.com/archives/C1/p1', 'file_id': 'F1'},
        'use_note': 'Reference only'}
    source = incoming / 'catalog.json'
    source.write_text(json.dumps({'references': [row]}))
    assert install(source, incoming, store.path)['references'] == 1
    bank = ReferenceBank(store)
    before = (bank.root / 'catalog.json').read_bytes()
    for patch in ({'file': 'new example.png'}, {'title': 'x' * 1001},
                  {'source': {'slack_url': 'not-a-url', 'file_id': 'F2'}}):
        source.write_text(json.dumps({'references': [{**row, 'id': 'E02', **patch}]}))
        with pytest.raises(DomainError, match='catalog'):
            install(source, incoming, store.path)
        assert (bank.root / 'catalog.json').read_bytes() == before
        assert bank.list(actor)['total'] == 1
    source.write_text(json.dumps({'references': [{**row, 'id': 'E02'}]}))
    assert install(source, incoming, store.path)['references'] == 2
    assert bank.list(actor)['total'] == 2
