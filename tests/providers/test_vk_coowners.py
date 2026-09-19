from copy import deepcopy
from types import SimpleNamespace

import pytest

from adapters.port import ReadRequest
from adapters.vk import VKAdapter
from social_operations.domain import DomainError
from .test_native_adapters import Journal


def shared_post():
    return {'id': 1885, 'owner_id': -202, 'post_type': 'post', 'text': 'fixture',
            'coowners': {'coowner_post_id': {'owner_id': -101, 'post_id': 16},
                         'list': [{'owner_id': -101, 'status': 'approved', 'post_id': 16}]}}


def adapter():
    return VKAdapter(SimpleNamespace(), connection_id='connection')


def test_shared_post_uses_exact_requested_wall_identity():
    raw = shared_post()
    before = deepcopy(raw)
    item = adapter()._item(raw, 'published', '-101')
    assert (item.native_target, item.native_id, item.url) == ('-101', '16', 'https://vk.ru/wall-101_16')
    assert item.member_ids == ('16',)
    assert raw == before


@pytest.mark.parametrize('change', ['no_mapping', 'wrong_wall', 'pending', 'wrong_id', 'duplicate', 'bool_id'])
def test_unproven_shared_identity_rejected(change):
    raw = shared_post()
    co = raw['coowners']
    if change == 'no_mapping': del co['coowner_post_id']
    if change == 'wrong_wall': co['coowner_post_id']['owner_id'] = -303
    if change == 'pending': co['list'][0]['status'] = 'pending'
    if change == 'wrong_id': co['list'][0]['post_id'] = 99
    if change == 'duplicate': co['list'].append(dict(co['list'][0]))
    if change == 'bool_id': co['coowner_post_id']['post_id'] = True
    with pytest.raises(DomainError):
        adapter()._item(raw, 'published', '-101')


def test_coowner_mapping_never_applies_to_scheduled_posts():
    with pytest.raises(DomainError):
        adapter()._item(shared_post(), 'scheduled', '-101')


@pytest.mark.asyncio
async def test_feed_and_exact_read_agree_on_coowner_id():
    class Transport:
        async def invoke(self, *, role, method, params):
            assert method in {'wall.get', 'wall.getById'}
            if method == 'wall.getById':
                assert params['posts'] in {'-101_16', '-101_17'}
            return {'items': [shared_post()]}
    a = VKAdapter(Transport(), connection_id='connection')
    page = await a.read(ReadRequest('connection', '-101', 'feed', 3), Journal().hooks)
    exact = await a._exact('-101', '16', 'published')
    assert page.items[0].native_id == exact.native_id == '16'
    with pytest.raises(DomainError):
        await a._exact('-101', '17', 'published')
