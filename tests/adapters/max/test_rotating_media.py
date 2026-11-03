"""Native MAX identity survives signed CDN URL rotation between page loads."""
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from adapters.max import queue
from adapters.max.bridge import MaxAdapter
from adapters.max.driver import FixtureDriver
from adapters.max.profile import MaxBlocked
from adapters.port import Asset, ProviderRequest
from social_operations.domain import OutcomeUnknown


def row():
    return dict(id='native-1', url=None, target='-101', namespace='scheduled',
                text='Frozen caption', entities=[], media=['https://i.oneme.ru/photo?sig=old'],
                observed_media=[], correlation_id='native-correlation',
                scheduled_at='2030-11-12T16:45:00Z', observed_at='2030-11-11T00:00:00Z')


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', [None, 'id', 'text', 'scheduled_at', 'media_count'])
async def test_two_native_queue_loads_ignore_url_rotation_but_preserve_intent(monkeypatch, changed):
    first = row()
    second = dict(first, media=['https://i.oneme.ru/photo?sig=fresh'])
    if changed == 'media_count':
        second['media'].append('https://i.oneme.ru/second')
    elif changed:
        second[changed] = 'different'
    values = iter([first, second])

    class Observer:
        def __init__(self, *args): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

    monkeypatch.setattr(queue, 'QueueObserver', Observer)
    monkeypatch.setattr(queue, 'open_queue', AsyncMock(return_value=[{'id': 'native-1'}]))
    monkeypatch.setattr(queue, 'item', AsyncMock(side_effect=lambda *args: next(values)))
    driver = NS(page=NS(goto=AsyncMock()), origin='https://web.max.ru',
                evidence_pages=(), _account=AsyncMock(), _scope=AsyncMock())
    if changed:
        with pytest.raises(MaxBlocked, match='native_queue_changed'):
            await queue.read(driver, '-101')
    else:
        result = await queue.read(driver, '-101')
        assert result == [second]
        assert result[0]['media'] != first['media']


@pytest.mark.parametrize('count', [1, 2])
def test_native_receipt_binds_fresh_references_and_retains_attachment_count(count):
    driver = FixtureDriver(NS(set_default_timeout=lambda value: None), None,
                           origin='http://127.0.0.1', account='offline',
                           allowed_targets=frozenset({'-101'}))
    adapter = MaxAdapter(driver, connection_id='max')
    request = ProviderRequest('op', 'attempt', 'plan', 'max', 'max_web',
        'VIBEPUBLISH_MAX_PROFILE', 'destination', '-101', 'publish', 'post',
        json.dumps({'text': 'Frozen caption'}),
        (Asset('asset', 'a'*64, 'image/png', 10),), '2030-11-12T16:45:00Z', 2000000000)
    fresh = dict(row(), media=['https://i.oneme.ru/photo?sig=fresh'] * count)
    if count != 1:
        with pytest.raises(OutcomeUnknown):
            adapter._observation(request, [fresh], {'media': row()['media']})
    else:
        observed = adapter._observation(request, [fresh], {'media': row()['media']})
        assert observed.observed == 'provider_scheduled'
        assert observed.items[0].provider_media == tuple(fresh['media'])
        assert observed.items[0].media_hashes == ('a'*64,)
