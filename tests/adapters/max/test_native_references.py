"""Literal public post references need a separately verified exact target binding."""
import pytest
from adapters.max.references import native_reference_id


@pytest.mark.parametrize('value,public_url,expected', [
    ('https://max.ru/c/-202/AaEmK_9-x', None, 'AaEmK_9-x'),
    ('https://max.ru/channel_fixture/AaEmK_9-x', 'https://max.ru/channel_fixture', 'AaEmK_9-x'),
    ('https://max.ru/Channel_Fixture/aBcD', 'https://max.ru/Channel_Fixture', 'aBcD'),
])
def test_exact_bound_reference_preserves_opaque_slug_case(value, public_url, expected):
    assert native_reference_id(value, '-202', public_url=public_url) == expected


@pytest.mark.parametrize('value,public_url', [
    ('https://max.ru/channel_fixture/post', None),
    ('https://max.ru/channel_fixture/post', 'https://max.ru/other_channel'),
    ('https://max.ru/channel_fixture/post', 'https://max.ru/Channel_Fixture'),
    ('https://max.ru/c/-303/post', 'https://max.ru/channel_fixture'),
    ('https://max.ru/channel_fixture/post?query=value', 'https://max.ru/channel_fixture'),
    ('https://max.ru/channel_fixture/post#fragment', 'https://max.ru/channel_fixture'),
    ('https://max.ru/channel_fixture/post?', 'https://max.ru/channel_fixture'),
    ('https://max.ru/channel_fixture/post#', 'https://max.ru/channel_fixture'),
    ('https://max.ru/channel_fixture/p%2Fost', 'https://max.ru/channel_fixture'),
    ('https://max.ru/channel_fixture/%70ost', 'https://max.ru/channel_fixture'),
    ('https://max.ru/channel_fixture/post/extra', 'https://max.ru/channel_fixture'),
    ('https://person@max.ru/channel_fixture/post', 'https://max.ru/channel_fixture'),
    ('https://max.ru:443/channel_fixture/post', 'https://max.ru/channel_fixture'),
    ('https://MAX.RU/channel_fixture/post', 'https://max.ru/channel_fixture'),
    ('https://max.ru.evil.test/channel_fixture/post', 'https://max.ru/channel_fixture'),
    ('https://max.ru/channel_fixture/post\n', 'https://max.ru/channel_fixture'),
    ('https://max.ru/channel_fixture/post', 'https://max.ru/channel_fixture/'),
    ('https://max.ru/login/post', 'https://max.ru/login'),
    ('https://max.ru/token/post', 'https://max.ru/token'),
    ('https://max.ru/invite/post', 'https://max.ru/invite'),
    ('https://max.ru/channel_fixture/' + 'x' * 129, 'https://max.ru/channel_fixture'),
])
def test_unbound_ambiguous_or_nonliteral_reference_is_rejected(value, public_url):
    assert native_reference_id(value, '-202', public_url=public_url) is None


@pytest.mark.parametrize('target', [None, '', '-0', '-202?x', '202', 202])
def test_reference_never_infers_native_target(target):
    assert native_reference_id('https://max.ru/channel_fixture/post', target,
                               public_url='https://max.ru/channel_fixture') is None
