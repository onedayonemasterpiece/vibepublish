"""Authenticated, no-cache static-media selection UI; never writes a palette itself."""
from __future__ import annotations
import base64
import html
import json
import secrets
from urllib.parse import quote


def render_catalog(service, actor, catalog):
    c = catalog['emoji_catalog']
    cells = []
    for entry in c['entries']:
        data, mime, sha = service.read_asset(actor, entry['preview_ref'])
        if sha != entry['preview_sha256']:
            from .domain import DomainError
            raise DomainError('emoji_preview_integrity')
        uri = 'data:'+mime+';base64,'+base64.b64encode(data).decode()
        cells.append(f'<button class="cell" type="button" data-cell="{entry["cell"]}" aria-label="Добавить эмодзи {entry["cell"]}">'
                     f'<img src="{uri}" alt="{html.escape(entry["alt"], quote=True)}">'
                     f'<strong>№ {entry["cell"]}</strong><small>{entry["document_id"]}</small></button>')
    command = {'kind':'emoji_alias_select','catalog_ref':c['catalog_ref'], 'catalog_revision':c['revision'],
               'selection_token':c['selection_token'],'cells':[], 'alias':'my_emoji', 'expected_revision':0, 'fallback':''}
    encoded = json.dumps(command, ensure_ascii=True).replace('<','\\u003c').replace('&','\\u0026')
    next_page = ''
    if catalog.get('next_cursor'):
        href = '/v1/emoji/catalogs/'+quote(c['catalog_ref'], safe='')+'?cursor='+quote(catalog['next_cursor'], safe='')
        next_page = '<p><a href="'+html.escape(href, quote=True)+'">Следующая страница каталога</a>. Выбор на этой странице не переносится автоматически; сохраните номера частей.</p>'
    nonce = secrets.token_urlsafe(24)
    page = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Выбор Telegram emoji — VibePublish</title>
<style>body{font:16px system-ui,sans-serif;margin:0;background:#f5f6f7;color:#20252c}main{max-width:1000px;margin:auto;padding:20px;box-sizing:border-box}h1{font-size:26px;margin:0 0 8px}p{line-height:1.45}button,input{font:inherit}button{cursor:pointer}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:10px}.cell{background:white;border:1px solid #bcc5ce;border-radius:10px;padding:10px;display:flex;flex-direction:column;align-items:center;gap:6px}.cell img{width:72px;height:72px;object-fit:contain}.cell small{font-size:10px}.cell:focus-visible{outline:3px solid #2764d1}#chain{display:flex;flex-wrap:wrap;min-height:90px;gap:0;background:white;border:1px solid #bcc5ce;padding:8px;border-radius:10px}#chain figure{margin:0;text-align:center}#chain img{width:50px;height:50px;object-fit:contain}#chain figcaption{font-size:12px}.controls{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}input{max-width:100%;box-sizing:border-box;padding:8px}label{display:flex;flex-direction:column;gap:4px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:14px;border-radius:10px;font-size:13px}#notice{min-height:24px}button#clear{padding:10px 16px}footer{font-size:14px} @media(max-width:420px){main{padding:12px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}h1{font-size:23px}}</style>
<main><h1>Выберите одиночный эмодзи или цепочку</h1><p>Набор <strong>PACK_NAME</strong>, ревизия REVISION. Это статические миниатюры фактических файлов провайдера, не проверка анимации. Нажатия добавляют части в выбранном порядке; повторное нажатие сохраняет повтор.</p>
<section class="grid" aria-label="Нумерованный каталог">CELLS</section>NEXT_PAGE
<h2>Выбранная цепочка</h2><div id="chain" aria-label="Порядок выбранных эмодзи"></div><p id="notice" role="status">Ничего не выбрано. Максимум 16 частей.</p>
<button id="clear" type="button">Очистить выбор</button>
<div class="controls"><label>Личный псевдоним<input id="alias" value="my_emoji" pattern="[a-z][a-z0-9_-]*" maxlength="80"></label><label>Текст для других платформ<input id="fallback" maxlength="300" placeholder="Например: Третьяковская галерея"></label></div>
<p>Команда для VibePublish. Она ещё не выполнена; сохранение требует явного вызова destinations. Для изменения существующего псевдонима укажите его актуальную expected_revision.</p><pre id="command"></pre>
<footer>Выбор действует 15 минут и только для этой ревизии. Переносы и размеры в Telegram могут отличаться. Приватная страница не предназначена для публичной ссылки.</footer></main>
<script nonce="NONCE">const command=COMMAND;const order=[];const grid=document.querySelector('.grid');const chain=document.querySelector('#chain');const notice=document.querySelector('#notice');
function draw(){command.cells=order.map(x=>x.cell);command.alias=document.querySelector('#alias').value;command.fallback=document.querySelector('#fallback').value;chain.replaceChildren();for(const item of order){const f=document.createElement('figure');const im=item.button.querySelector('img').cloneNode(true);const label=document.createElement('figcaption');label.textContent='№ '+item.cell;f.append(im,label);chain.append(f)}notice.textContent=order.length?'Порядок: '+command.cells.join(' → '):'Ничего не выбрано. Максимум 16 частей.';document.querySelector('#command').textContent=JSON.stringify({command},null,2)}
grid.addEventListener('click',e=>{const button=e.target.closest('[data-cell]');if(!button)return;if(order.length===16){notice.textContent='Максимум 16 частей';return}order.push({cell:Number(button.dataset.cell),button});draw()});document.querySelector('#clear').addEventListener('click',()=>{order.length=0;draw()});document.querySelectorAll('input').forEach(i=>i.addEventListener('input',draw));draw();</script></html>'''
    page = page.replace('PACK_NAME',html.escape(c['short_name'])).replace('REVISION',str(c['revision'])).replace('CELLS',''.join(cells)).replace('NEXT_PAGE',next_page).replace('NONCE',nonce).replace('COMMAND',encoded)
    return page, { 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':f"default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'" }
