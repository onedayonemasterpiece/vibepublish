"""A native photo read must not hold SQLite's writer during image processing."""
import asyncio
import io
from concurrent.futures import ThreadPoolExecutor, wait
from threading import Event

from PIL import Image

from adapters.vk import VKAdapter
from social_operations import assets
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.scripted import VKTransport


def test_native_photo_verification_does_not_block_carousel_journal(tmp_path, monkeypatch):
    store = Store(tmp_path / 'ledger.sqlite')
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    store.add_connection(actor, 'vk', 'vk', account_type='vk_user')
    store.bind(actor, 'owner', 'vk_fixture', 'vk', '-101', rights=('publish', 'edit'))
    app = Application(store)
    saved = app.carousels.command(actor, {
        'command': {'kind': 'create', 'brief': 'Concurrent journal',
            'card_count': 3, 'card_width': 128, 'card_height': 160,
            'svg': '<svg xmlns="http://www.w3.org/2000/svg" width="384" height="160">'
                   '<rect width="384" height="160" fill="white"/></svg>'},
        'request_key': 'carousel-before-read',
    })

    binary = io.BytesIO()
    Image.new('RGB', (1080, 1350), 'orange').save(binary, format='JPEG')
    expected = binary.getvalue()
    url = 'https://sun9-3.userapi.com/fixture.jpg'
    transport = VKTransport()
    transport.groups[101] = {'id': 101, 'is_admin': 1, 'admin_level': 3, 'is_closed': 0}
    transport.posts[(-101, 223)] = {
        'owner_id': -101, 'id': 223, 'date': 1_800_000_000, 'text': 'Native photo',
        'post_type': 'post', 'attachments': [
            {'type': 'photo', 'photo': {'owner_id': -101, 'id': 789,
                'sizes': [{'url': url, 'width': 1080, 'height': 1350}]}},
        ],
    }

    async def download_photo(requested):
        assert requested == url
        return expected

    transport.download_photo = download_photo
    pending = asyncio.run(app.call(actor, 'vibepublish_read', {
        'query': {'kind': 'item', 'item_ref': 'https://vk.com/wall-101_223'},
    }))
    assert pending['state'] == 'accepted', pending
    worker = Worker(store, {'vk': VKAdapter(transport, connection_id='vk')})
    entered, release = Event(), Event()
    verify_image = assets.verify_image

    def paused_verification(data, mime, **kwargs):
        # Synchronize at the expensive work, then run the real decoder/encoder.
        # No database result, transaction or image verification is mocked.
        assert data == expected
        entered.set()
        assert release.wait(timeout=20), 'Native image verification was not released'
        return verify_image(data, mime, **kwargs)

    monkeypatch.setattr(assets, 'verify_image', paused_verification)
    with store.connection() as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    with ThreadPoolExecutor(max_workers=2) as threads:
        read = threads.submit(
            asyncio.run, worker.run_once(operation_id=pending['operation_id']))
        try:
            assert entered.wait(timeout=5), 'Worker did not reach image verification'
            render = threads.submit(app.carousels.render, actor, {
                'carousel_id': saved['carousel_id'], 'revision': 1,
                'view': 'master', 'scale': 0.5, 'cutlines': True,
            })
            _, waiting = wait([render], timeout=2)
        finally:
            release.set()
        assert read.result(timeout=10)
        preview = render.result(timeout=10)

    assert not waiting, 'Carousel journal waited for unrelated native image processing'
    assert preview.metadata['mime_type'] == 'image/jpeg'
    journal = app.carousels.get(actor, {
        'carousel_id': saved['carousel_id'], 'scope': 'journal',
    })['journal']
    assert sum(entry['kind'] == 'render' for entry in journal) == 1
    completed = store.receipt(actor, pending['operation_id'])
    assert completed['state'] == 'verified', completed
    item, = completed['items']
    data, mime, _ = app.read_asset(actor, item['media'][0]['source']['id'])
    assert data == expected
    assert mime == 'image/jpeg'
