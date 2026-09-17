import copy
import json
import pytest
from social_operations.domain import DomainError, canonical
from social_operations.rich_text import compile_content, utf16, normalized_entities, provider_content
from .fixtures import PAIR, THUMB, FREE


def alias(ids=PAIR, alts=None, **extra):
    alts = alts or ['🖼']*len(ids)
    return {'alias': 'selected', 'revision': 1, 'fallback': 'Третьяковская галерея',
            'parts': [{'document_id': i, 'alt': a, 'preview_sha256': 'a'*64} for i, a in zip(ids, alts)], **extra}


def compile_alias(value, prefix=''):
    return compile_content({'paragraphs': [[{'kind': 'text', 'text': prefix}, {'kind': 'emoji', 'alias': 'selected'}]]}, lambda _: value)


def test_E04_exact_tretyakov_not_duplicated_thumbnail_and_free_label():
    c = compile_alias(alias())
    assert [e['document_id'] for e in c['entities']] == ['5188445640325099838','5188470637034758005']
    assert THUMB not in canonical(c)
    c = compile_alias(alias(FREE, ['🆓']*4))
    assert [e['document_id'] for e in c['entities']] == ['5406749623865857008','5407072545276973461','5406815783542085177','5406927577245833438']
    assert [e['offset'] for e in c['entities']] == [0,2,4,6]


@pytest.mark.parametrize('alts', [['❤️'], ['👩🏽\u200d💻'], ['🇷🇺'], ['🎟️'], ['1️⃣'], ['🖼','❤️','👩🏽\u200d💻','🇷🇺']])
@pytest.mark.parametrize('prefix', ['', '😀 ', 'Текст \n'])
def test_E05_exact_utf16_variable_parts(alts, prefix):
    c = compile_alias(alias([str(i+1) for i in range(len(alts))], alts), prefix)
    encoded = c['text'].encode('utf-16-le')
    for part, entity in zip(alts, c['entities']):
        assert encoded[2*entity['offset']:2*(entity['offset']+entity['length'])].decode('utf-16-le') == part
        assert entity['length'] == len(part.encode('utf-16-le'))//2
    assert c['entities'][0]['offset'] == len(prefix.encode('utf-16-le'))//2


def test_E04_repeated_selection_keeps_order_not_deduplicated():
    c = compile_alias(alias([PAIR[1],PAIR[0],PAIR[1]]))
    assert [e['document_id'] for e in c['entities']] == [PAIR[1],PAIR[0],PAIR[1]]


def test_E06_rich_preserved_exclusions_and_unknown_emoji():
    content = {'paragraphs': [[{'kind':'text','text':'🎭','style':'bold'},
        {'kind':'link','label':'🎭 Билеты','url':'https://example.org/🎭'},
        {'kind':'text','text':'🎭','style':'code'},
        {'kind':'text','text':' https://example.org/🎭 @mention 🦀'}]]}
    original = copy.deepcopy(content)
    c = compile_content(content, lambda _: alias(FREE, ['🆓']*4), [{'match':'🎭','alias':'selected'}])
    assert content == original
    custom = [e for e in c['entities'] if e['type']=='custom_emoji']
    assert len(custom) == 8
    bold = next(e for e in c['entities'] if e['type']=='bold')
    assert bold['length'] == 8
    link = next(e for e in c['entities'] if e['type']=='text_link')
    assert link['url'] == 'https://example.org/🎭' and link['length'] == utf16('🆓'*4+' Билеты')
    assert c['text'].endswith('🎭 https://example.org/🎭 @mention 🦀')


def test_E07_idempotence_freezes_alias_and_rules_once():
    c = compile_content({'text':'🎭'}, lambda _: alias(), [{'match':'🎭','alias':'selected'}])
    def forbidden(_):
        pytest.fail('frozen content was re-expanded')
    assert compile_content(c, forbidden, [{'match':'🖼','alias':'other'}]) == c
    c['emoji_snapshot'][0]['parts'][0]['document_id'] = '1'
    assert alias()['parts'][0]['document_id'] == PAIR[0]


def test_E07_longest_and_equal_length_overlap():
    rules = [{'match':'🟡','alias':'single'}, {'match':'🟡 Бесплатно','alias':'long'}]
    c = compile_content({'text':'🟡 Бесплатно'}, lambda name: alias(FREE, ['🆓']*4) if name=='long' else alias(), rules)
    assert [e['document_id'] for e in c['entities']] == FREE
    with pytest.raises(DomainError, match='emoji rule ambiguous'):
        compile_content({'text':'🎭'}, lambda _: alias(), [{'match':'🎭','alias':'a'},{'match':'🎭','alias':'b'}])


@pytest.mark.parametrize('text,match', [('❤️','❤'),('👩🏽\u200d💻','👩'),('🇷🇺','🇷'),('🎟️','🎟'),('1️⃣','1')])
def test_E05_no_partial_emoji_rule_match(text, match):
    assert compile_content({'text':text}, lambda _:alias(), [{'match':match,'alias':'a'}]) == {'text':text}


def test_context_is_semantic_and_word_substrings_are_not_venue_rules():
    rule = {'match':'Третьяковка','alias':'a','context':{'venue':'tretyakov'}}
    c = compile_content({'text':'Третьяковка'}, lambda _:alias(), [rule])
    assert c == {'text':'Третьяковка'}
    assert compile_content({'text':'Третьяковка'},lambda _:alias(),[rule],context={'venue':'tretyakov'})['entities']
    assert compile_content({'text':'неТретьяковка'},lambda _:alias(),[rule],context={'venue':'tretyakov'}) == {'text':'неТретьяковка'}


def test_E06_partial_formatting_overlap_blocks_not_drops():
    content = {'paragraphs': [[{'kind':'text','text':'🟡 ','style':'bold'}, {'kind':'text','text':'Бесплатно'}]]}
    with pytest.raises(DomainError, match='emoji format overlap'):
        compile_content(content,lambda _:alias(),[{'match':'🟡 Бесплатно','alias':'a'}])


def test_E11_explicit_semantic_fallback_not_custom_unicode():
    content = {'paragraphs': [[{'kind':'emoji','alias':'selected'}]]}
    with pytest.raises(DomainError, match='emoji fallback required'):
        compile_content(content,lambda _:alias(),provider='vk')
    assert compile_content(content,lambda _:alias(),provider='vk',fallback=True) == {'text':'Третьяковская галерея'}


@pytest.mark.parametrize('entity', [
    {'type':'custom_emoji','offset':1,'length':1,'document_id':'12'},
    {'type':'bold','offset':0,'length':999},
    {'type':'custom_emoji','offset':0,'length':2,'document_id':12},
    {'type':'unknown','offset':0,'length':2}])
def test_invalid_native_entities_fail_closed(entity):
    with pytest.raises(DomainError):
        normalized_entities('😀', [entity])


def test_existing_native_media_keeps_caption_limit_without_staged_assets():
    from types import SimpleNamespace
    from social_operations.rich_text import telegram_text_limit, provider_content
    import json
    from social_operations.domain import DomainError
    req=SimpleNamespace(assets=(),existing=SimpleNamespace(provider_media=('photo:123',)))
    assert telegram_text_limit(req)==1024
    with pytest.raises(DomainError):
        provider_content(json.dumps({'text':'x'*1025}),telegram_text_limit(req))
