"""Synthetic media and real-shaped native metadata. NOT screenshots of a live pack."""
from __future__ import annotations
import io
from PIL import Image, ImageDraw
from tests.providers.scripted import TelegramClient, obj

PAIR = ['5188445640325099838', '5188470637034758005']
THUMB = '5188683852096234620'
FREE = ['5406749623865857008', '5407072545276973461', '5406815783542085177', '5406927577245833438']
ALTS = ['🖼', '🖼', '🖼']+['🆓']*4+['❤️', '👩🏽\u200d💻', '🇷🇺', '🎟️', '1️⃣']


def fixture_png(number):
    out = io.BytesIO()
    image = Image.new('RGB', (80, 80), 'white')
    ImageDraw.Draw(image).text((14, 32), 'FIXTURE '+str(number), fill='black')
    image.save(out, format='PNG')
    return out.getvalue()


class EmojiClient(TelegramClient):
    def __init__(self):
        super().__init__()
        self.premium, self.maximum, self.pack_emoji = True, 100, True
        self.docs = [obj('Document', id=int(i), size=len(fixture_png(n)), mime_type='image/png', thumbs=[],
            attributes=[obj('DocumentAttributeCustomEmoji', alt=alt, free=False, stickerset=obj('InputStickerSetID', id=99))],
            preview=fixture_png(n)) for n, (i, alt) in enumerate(zip([THUMB]+PAIR+FREE+['11','12','13','14','15'], ALTS), 1)]
        self.downloads = []

    async def get_me(self):
        result = await super().get_me()
        result.premium = self.premium
        return result

    async def download_media(self, doc, *, file, **kwargs):
        self.downloads.append((doc.id, kwargs))
        file.write(doc.preview)

    async def __call__(self, req):
        name = type(req).__name__
        if name in {'GetStickerSetRequest', 'GetCustomEmojiDocumentsRequest', 'GetAppConfigRequest'}:
            self.calls.append((name, req))
            if name == 'GetStickerSetRequest':
                assert req.hash == 0
                return obj('StickerSet', set=obj('StickerSet', id=99, emojis=self.pack_emoji,
                        short_name=req.stickerset.short_name), documents=self.docs)
            if name == 'GetCustomEmojiDocumentsRequest':
                return [d for d in self.docs if d.id in req.document_id]
            return obj('AppConfig', config=obj('JsonObject', value=[obj('JsonObjectValue',
                key='message_animated_emoji_max', value=obj('JsonNumber', value=self.maximum))]))
        return await super().__call__(req)
