"""Observed MAX editor actions and semantic DOM evidence; no editor internals.

Core compiles/validates UTF-16 entity intents. This helper only selects visible
DOM ranges, invokes observed keyboard/dialog controls, and reads rendered spans.
"""
from playwright.async_api import expect
from .profile import MaxBlocked

QUALIFIED = {'bold', 'italic', 'text_link'}


def qualified(entities):
    if any(entity.get('type') not in QUALIFIED for entity in entities):
        raise MaxBlocked('rich_recipe_not_qualified')


# MAX renders ordinary Unicode emoji as non-editable raster decorators. Their
# textContent is empty (and may contain loader whitespace), not the glyph value.
DOM_HELPERS = r"""
const emojiValue=n=>{
 if(n.nodeType!==1)return null;
 if(n.hasAttribute('data-lexical-emoji'))return n.getAttribute('data-lexical-emoji');
 if(n.classList.contains('emojiWrapper')||n.classList.contains('emoji')){
  const inner=n.querySelector('[data-lexical-emoji]');if(inner)return inner.getAttribute('data-lexical-emoji');
  const img=n.querySelector('img');if(img?.src.startsWith('https://st.max.ru/emojis/')&&img.alt)return img.alt;
 }
 return null;
};
const semanticText=n=>{if(!n)return '';const emoji=emojiValue(n);if(emoji!==null)return emoji;
 if(n.nodeType===3)return n.textContent;return [...n.childNodes].map(semanticText).join('');};
"""
TEXT_JS = '(root)=>{' + DOM_HELPERS + 'return semanticText(root);}'
ROW_SELECTOR = '({queryAll(root,selector){' + DOM_HELPERS + """
 const x=JSON.parse(selector);return [...root.querySelectorAll('.messageWrapper')].filter(row=>{
  const content=row.querySelector('.bubbleContent > .text');
  return content&&semanticText(content)===x.text&&(!x.outgoing||row.classList.contains('messageWrapper--isOut'));
 });},query(root,selector){return this.queryAll(root,selector)[0]||null;}})
"""


async def register(selectors):
    await selectors.register('maxrow',script=ROW_SELECTOR)


SNAPSHOT_JS = DOM_HELPERS + r"""
const semanticSnapshot=root=>{

        const entities=[],emojiSpans=[];let text='',offset=0,unsupported=false;
        const walk=node=>{
            const emoji=emojiValue(node);
            if(emoji!==null){emojiSpans.push({offset,length:emoji.length});text+=emoji;offset+=emoji.length;return;}
            if(node.nodeType===3){text+=node.textContent;offset+=node.textContent.length;return;}
            if(node.nodeType!==1&&node.nodeType!==11)return;
            const start=offset,tag=node.nodeType===1?node.tagName.toLowerCase():'';
            for(const child of node.childNodes)walk(child);
            const length=offset-start;if(!length)return;
            let type=null,url=null;
            if(['b','strong'].includes(tag)||node.classList?.contains('bold'))type='bold';
            else if(['i','em'].includes(tag)||node.classList?.contains('italic'))type='italic';
            else if(tag==='a'){
                url=node.href;if(!/^https?:\/\//.test(url)){unsupported=true;return;}
                if(url.replace(/\/$/,'')===semanticText(node).replace(/\/$/,''))return;
                type='text_link';
            }else if(['code','pre','u','s','del','blockquote','img'].includes(tag))unsupported=true;
            if(type)entities.push({type,offset:start,length,...(url?{url}:{})});
        };
        walk(root);
        // Same MAX visual semantics as core: a raster emoji has no meaningful
        // font weight/slant. Links retain their exact full spans, including emoji.
        const neutral=[];
        for(const part of new Intl.Segmenter('und',{granularity:'grapheme'}).segment(text)){
            const glyph=part.segment;
            if(!glyph.includes('\uFE0E')&&(/\p{Emoji_Presentation}/u.test(glyph)||
                (glyph.includes('\uFE0F')&&/\p{Emoji}/u.test(glyph))||/^[0-9#*]\uFE0F?\u20E3$/u.test(glyph)))
                neutral.push([part.index,part.index+glyph.length]);
        }
        for(const kind of ['bold','italic']){
            const spans=[];
            for(const e of entities.filter(e=>e.type===kind)){
                let parts=[[e.offset,e.offset+e.length]];
                for(const [a,b] of neutral)parts=parts.flatMap(([start,end])=>[[start,Math.min(end,a)],[Math.max(start,b),end]]).filter(([a,b])=>a<b);
                for(const [a,b] of parts)spans.push({type:kind,offset:a,length:b-a});
            }
            spans.sort((a,b)=>a.offset-b.offset);const merged=[];
            for(const span of spans){
                const previous=merged[merged.length-1];
                if(previous&&previous.offset+previous.length>=span.offset){previous.length=Math.max(previous.offset+previous.length,span.offset+span.length)-previous.offset;continue;}
                merged.push({...span});
            }
            for(let i=entities.length-1;i>=0;i--)if(entities[i].type===kind)entities.splice(i,1);
            entities.push(...merged);
        }
        entities.sort((a,b)=>a.offset-b.offset||b.length-a.length||a.type.localeCompare(b.type));
        return {text,entities,unsupported};

};
"""


async def capture(element):
    value=await element.evaluate('(root)=>{' + SNAPSHOT_JS + 'return semanticSnapshot(root);}')
    if value['unsupported']:
        raise MaxBlocked('rich_recipe_not_qualified')
    return value


def same_entities(left, right):
    # Order-insensitive DOM projection comparison; schema/overlap validation is
    # exclusively core's job, not a second rich-text compiler here.
    return sorted(map(_key, left)) == sorted(map(_key, right))


def _key(value):
    return tuple(sorted(value.items()))


async def select_range(composer, text, offset, length):
    ok = await composer.evaluate('(root,x)=>{' + DOM_HELPERS + r"""
        if(semanticText(root)!==x.text||!root.isConnected)return false;
        root.focus();const tokens=[];let position=0;
        const visit=n=>{
            const emoji=emojiValue(n);
            if(emoji!==null){tokens.push({node:n,emoji:true,start:position,end:position+emoji.length});position+=emoji.length;return;}
            if(n.nodeType===3){tokens.push({node:n,start:position,end:position+n.textContent.length});position+=n.textContent.length;return;}
            for(const child of n.childNodes)visit(child);
        };visit(root);
        const point=(offset,end)=>{
            const token=tokens.find(t=>end?offset>t.start&&offset<=t.end:offset>=t.start&&offset<t.end);
            if(!token)return null;
            if(!token.emoji)return [token.node,offset-token.start];
            if(offset!==token.start&&offset!==token.end)return null;
            return [token.node.parentNode,[...token.node.parentNode.childNodes].indexOf(token.node)+(offset===token.end?1:0)];
        };
        const start=point(x.offset,false),end=point(x.offset+x.length,true);if(!start||!end)return false;
        const range=document.createRange();range.setStart(...start);range.setEnd(...end);
        const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
        return selection.rangeCount===1&&semanticText(selection.getRangeAt(0).cloneContents())===x.text.slice(x.offset,x.offset+x.length);
    }""",dict(text=text,offset=offset,length=length))
    if not ok:
        raise MaxBlocked('rich_selection_changed')


async def fill(page, composer, text, entities):
    qualified(entities)
    await page.bring_to_front()
    await composer.fill(text)
    # Observed MAX 'Обычный' shortcut removes prior links/styles as well; this
    # prevents edit mode from carrying the old span's format into new plain text.
    await composer.press('Control+a')
    await composer.press('Control+Backslash')
    for entity in entities:
        await select_range(composer,text,entity['offset'],entity['length'])
        if entity['type'] in {'bold','italic'}:
            await page.keyboard.press('Control+b' if entity['type']=='bold' else 'Control+i')
        else:
            await page.keyboard.press('Control+k')
            dialog=page.get_by_role('dialog')
            await expect(dialog).to_have_count(1)
            await expect(dialog.get_by_text('Ссылка',exact=True)).to_have_count(1)
            await dialog.get_by_placeholder('https://max.ru',exact=True).fill(entity['url'])
            await dialog.get_by_role('button',name='Добавить',exact=True).click()
            await expect(dialog).to_have_count(0)
    value=await capture(composer)
    if value['text']!=text or not same_entities(value['entities'],entities):
        raise MaxBlocked('rich_composer_mismatch')
