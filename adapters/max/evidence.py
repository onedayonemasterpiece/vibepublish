"""Lossy structural export for review; never exports live DOM verbatim.

This is NOT an automatic privacy certification. Dynamic text, IDs, assets,
URLs, scripts, styles and arbitrary attributes/classes are dropped, not hashed.
Replay data must then be authored separately using fictitious values and reviewed.
"""
from html import escape
from html.parser import HTMLParser

TAGS=frozenset('main aside nav div span button h2 h3 input textarea'.split())
CLASSES=frozenset('main main--active item cell name text title searchResultsList messageWrapper messageWrapper--isOut history bubbleContent media meta composer'.split())
LABELS=frozenset({'Настройки','Найти','Сообщение','Открыть отложенные сообщения','Отправить сообщение','Загрузить файл','Открыть меню стикеров','Запланированные посты','Скопировать ссылку на сообщение','Удалить','Редактировать','Изменить время'})


def structure_only(raw: str) -> str:
    class Export(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts=[]
            self.hidden=0
        def handle_starttag(self,tag,attrs):
            if tag in {'script','style'}:
                self.hidden+=1
            if self.hidden or tag not in TAGS:
                return
            clean=[]
            for key,value in attrs:
                if key=='class':
                    value=' '.join(x for x in (value or '').split() if x in CLASSES)
                elif key in {'aria-label','placeholder','aria-placeholder'}:
                    value=value if value in LABELS else ''
                elif key=='role':
                    value=value if value in {'textbox','listitem','presentation','dialog','menu','menuitem','region'} else ''
                elif key=='aria-labelledby':
                    value=value if value=='main-header-title' else ''
                elif key=='data-lexical-editor':
                    value=value if value=='true' else ''
                else:
                    continue
                if value:
                    clean.append(f'{key}="{escape(value,quote=True)}"')
            self.parts.append('<'+tag+(' '+ ' '.join(clean) if clean else '')+'>')
        def handle_endtag(self,tag):
            if tag in {'script','style'} and self.hidden:
                self.hidden-=1
                return
            if not self.hidden and tag in TAGS:
                self.parts.append('</'+tag+'>')
        def handle_data(self,data):
            if not self.hidden and data.strip() in LABELS:
                self.parts.append(escape(data.strip()))
    p=Export();p.feed(raw);p.close()
    return ''.join(p.parts)
