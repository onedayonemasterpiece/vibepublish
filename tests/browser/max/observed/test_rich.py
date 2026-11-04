"""Semantic DOM projection tests; live editor qualification is recorded separately."""
import pytest
from adapters.max.rich import capture, qualified, select_range, same_entities
from adapters.max.profile import MaxBlocked
from tests.browser.max.observed.test_submit import writer

pytestmark=pytest.mark.asyncio


async def test_rich_dom_nested_utf16_spans_and_exact_link(writer):
    _,page,_,_=writer
    await page.set_content('<div role="textbox" contenteditable>A<strong>🙂<em>B</em></strong><a href="https://example.com/item">label</a></div>')
    editor=page.get_by_role('textbox')
    result=await capture(editor)
    assert result['text']=='A🙂Blabel'
    assert same_entities(result['entities'],[
        dict(type='bold',offset=3,length=1),dict(type='italic',offset=3,length=1),
        dict(type='text_link',offset=4,length=5,url='https://example.com/item')])
    await select_range(editor,result['text'],1,2)
    assert await page.evaluate('getSelection().toString()')=='🙂'


async def test_rich_selection_refuses_changed_content(writer):
    _,page,_,_=writer
    await page.set_content('<div role="textbox" contenteditable>Changed</div>')
    with pytest.raises(MaxBlocked,match='selection_changed'):
        await select_range(page.get_by_role('textbox'),'Original',0,3)


async def test_literal_url_must_match_its_actual_destination(writer):
    _,page,_,_=writer
    await page.set_content('<div role="textbox"><a href="https://example.com/">https://example.com</a></div>')
    assert (await capture(page.get_by_role('textbox')))['entities']==[]
    await page.locator('a').evaluate('(e)=>e.href="https://example.org/"')
    assert (await capture(page.get_by_role('textbox')))['entities'][0]['url']=='https://example.org/'


async def test_unqualified_format_is_not_silently_stripped(writer):
    _,page,_,_=writer
    await page.set_content('<div role="textbox"><u>Text</u></div>')
    with pytest.raises(MaxBlocked,match='rich_recipe_not_qualified'):
        await capture(page.get_by_role('textbox'))
    with pytest.raises(MaxBlocked,match='rich_recipe_not_qualified'):
        qualified([dict(type='spoiler',offset=0,length=4)])


async def test_raster_unicode_emoji_text_range_and_neutral_style_gap(writer):
    _,page,_,_=writer
    from adapters.max.rich import TEXT_JS
    await page.set_content('<div role="textbox" contenteditable><strong>A</strong><span class="emojiWrapper" contenteditable="false"><span data-lexical-emoji="😀"><span> </span></span></span><strong>B</strong></div>')
    c=page.get_by_role('textbox')
    assert await c.text_content()=='A B'
    assert await c.evaluate(TEXT_JS)=='A😀B'
    value=await capture(c)
    assert value['entities']==[dict(type='bold',offset=0,length=1),dict(type='bold',offset=3,length=1)]
    await select_range(c,'A😀B',0,4)
    assert await page.evaluate('(root)=>{'+__import__('adapters.max.rich',fromlist=['DOM_HELPERS']).DOM_HELPERS+'return semanticText(getSelection().getRangeAt(0).cloneContents());}')=='A😀B'


async def test_semantic_row_selector_rebinds_emoji_and_order_not_position(writer):
    d,page,_,_=writer
    await page.goto(d.origin+'/-101')
    await page.set_content('<main><div class="messageWrapper messageWrapper--isOut"><div class="bubbleContent"><span class="text">A<span class="emoji" data-lexical-emoji="😀"></span>B</span></div></div><div class="messageWrapper"><div class="bubbleContent"><span class="text">A<span class="emoji" data-lexical-emoji="🙂"></span>B</span></div></div></main>')
    row=d._rows(page.locator('main'),'A😀B',outgoing=True)
    assert await row.count()==1
    await page.locator('main').evaluate('(e)=>e.append(e.firstElementChild)')
    assert await row.count()==1
    assert await row.locator('[data-lexical-emoji]').get_attribute('data-lexical-emoji')=='😀'


async def test_native_dialog_has_implicit_role_not_explicit_attribute(writer):
    _,page,_,_=writer
    await page.set_content('<dialog open><button>Отправить завтра в 10:30</button></dialog>')
    dialog=page.get_by_role('dialog')
    assert await dialog.count()==1
    button=dialog.get_by_role('button')
    # Regression for the observed unreachable v0 scheduling guard. No click is
    # performed: the old predicate could not reach the effect on this surface.
    assert await button.evaluate('e=>e.closest("[role=dialog]")===null')
    assert await button.evaluate('e=>e.closest("dialog,[role=dialog]").tagName')=='DIALOG'


async def test_group_native_queue_heading_is_distinct_from_channel(writer):
    d,page,_,_=writer
    await d.open('-101')
    await page.locator('main').evaluate('e=>e.innerHTML="<span>Отложенные сообщения</span>"')
    assert await (await d._scope('-101','scheduled')).count()==1
    d.timeout=.2
    with pytest.raises((AssertionError,MaxBlocked)):await d._scope('-101','feed')


async def test_rich_mismatch_diagnostic_keeps_text_and_urls_private(writer, monkeypatch, caplog):
    import json
    from adapters.max import rich
    _, page, _, _ = writer
    await page.set_content('<div role="textbox" contenteditable></div>')
    async def observed(_):
        return {'text': 'private-observed', 'entities': [
            {'type': 'text_link', 'offset': 0, 'length': 7, 'url': 'https://private.example/secret'}]}
    monkeypatch.setattr(rich, 'capture', observed)
    with pytest.raises(MaxBlocked, match='^rich_composer_mismatch$'):
        await rich.fill(page, page.get_by_role('textbox'), 'private-intent', [])
    record = next(r for r in caplog.records if r.message.startswith('MAX rich composer mismatch '))
    details = json.loads(record.message.removeprefix('MAX rich composer mismatch '))
    assert details['text_equal'] is False and details['first_entity_difference'] == 0
    assert details['observed_span'] == {'type': 'text_link', 'offset': 0, 'length': 7}
    assert all(value not in record.message for value in (
        'private-intent', 'private-observed', 'private.example', '/secret'))

async def test_entity_range_survives_editor_focus_selection_restoration(writer):
    _, page, _, _ = writer
    await page.set_content('<button>Outside</button><div role="textbox" contenteditable><strong>Heading</strong> tour label</div>')
    editor = page.get_by_role('textbox')
    # A rendered editor can restore its cached selection when focus returns from
    # a link dialog. That focus work must finish before a new entity is selected.
    await editor.evaluate("""root => {
        const saved = document.createRange();
        saved.selectNodeContents(root.querySelector('strong'));
        root.addEventListener('focus', () => queueMicrotask(() => {
            const selection = getSelection();
            selection.removeAllRanges();
            selection.addRange(saved.cloneRange());
        }));
    }""")
    await page.get_by_role('button', name='Outside').focus()
    class EventObservedComposer:
        async def focus(self):
            await editor.focus()
        async def evaluate(self, script, value):
            # Observe the native event at helper completion, before another
            # browser task/keyboard action can accidentally hide the race.
            wrapped = '''async(root, value) => {
                let consumed = false;
                const consume = () => consumed = true;
                document.addEventListener('selectionchange', consume);
                try {
                    const result = await (''' + script + ''')(root, value);
                    root.dataset.selectionConsumed = String(consumed);
                    return result;
                } finally { document.removeEventListener('selectionchange', consume); }
            }'''
            return await editor.evaluate(wrapped, value)
    await select_range(EventObservedComposer(), 'Heading tour label', 8, 10)
    assert await page.evaluate('getSelection().toString()') == 'tour label'
    assert await editor.get_attribute('data-selection-consumed') == 'true'

async def test_link_assertion_diagnostic_preserves_original_and_privacy(writer, monkeypatch, caplog):
    import json
    from adapters.max import rich
    _, page, _, _ = writer
    await page.set_content('<div role="textbox" contenteditable></div>')
    original = AssertionError("Locator expected count 1; actual 0")
    class Expected:
        async def to_have_count(self, _):
            raise original
    monkeypatch.setattr(rich, 'expect', lambda _: Expected())
    with pytest.raises(AssertionError) as caught:
        await rich.fill(page, page.get_by_role('textbox'), 'private-label',
                        [dict(type='text_link', offset=0, length=13, url='https://private.example/secret')])
    assert caught.value is original
    record = next(r for r in caplog.records if r.message.startswith('MAX rich link assertion '))
    details = json.loads(record.message.removeprefix('MAX rich link assertion '))
    assert details['phase'] == 'open' and details['dialog_count'] == 0
    assert details['entity_index'] == 0 and details['selection_length'] == 13
    assert all(s not in record.message for s in ('private-label', 'private.example', '/secret'))
