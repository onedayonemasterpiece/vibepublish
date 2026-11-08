"""Real SQLite writer contention must not turn asset reads into cleanup writes."""
import io
from concurrent.futures import ThreadPoolExecutor, wait
from threading import Barrier

from PIL import Image

from social_operations.assets import import_image
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store


def test_carousel_asset_reads_do_not_wait_for_unrelated_writer(tmp_path):
    now = 1_800_000_000
    store = Store(tmp_path / 'ledger.sqlite', clock=lambda: now)
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    app = Application(store)

    refs = []
    for colour in ('red', 'green', 'blue'):
        image = io.BytesIO()
        Image.new('RGB', (32, 32), colour).save(image, format='PNG')
        refs.append(import_image(store, actor, image.getvalue(), 'image/png'))
    ordinary, retained, expired = refs
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="384" height="160">'
           f'<image href="asset:{retained}" width="384" height="160"/></svg>')
    app.carousels.command(actor, {'command': {'kind': 'create', 'brief': 'Saved image',
        'card_count': 3, 'card_width': 128, 'card_height': 160, 'svg': svg},
        'request_key': 'saved-image'})
    expected = [app.carousels._composition_asset(actor, ref) for ref in refs[:2]]
    with store.tx() as db:
        db.executemany('INSERT INTO media_store_assets VALUES(?,?,?,?)',
            [(ref, None, 'download_cache', now - 1) for ref in (retained, expired)])

    started = Barrier(4)

    def resolve(ref):
        started.wait(timeout=5)
        try:
            return app.carousels._composition_asset(actor, ref)
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=3) as readers:
        with store.connection() as writer:
            # Observe the normal Store configuration; do not enable a test-only mode.
            assert writer.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
            writer.execute('BEGIN IMMEDIATE')
            try:
                futures = [readers.submit(resolve, ref) for ref in refs]
                started.wait(timeout=5)
                _, pending = wait(futures, timeout=2)
                assert writer.in_transaction
            finally:
                writer.rollback()
        results = [future.result() for future in futures]

    assert not pending, 'Asset reads waited for an unrelated SQLite writer'
    assert results[:2] == expected
    assert results[2] == 'asset_not_available'
    with store.connection() as db:
        # Logical expiry is immediate; physical deletion belongs to normal cleanup.
        assert db.execute('SELECT 1 FROM assets WHERE id=?', (expired,)).fetchone()
    with store.tx() as db:
        app._purge_media_store_assets(db)
        assert db.execute('SELECT 1 FROM assets WHERE id=?', (expired,)).fetchone() is None
        assert db.execute('SELECT 1 FROM assets WHERE id=?', (retained,)).fetchone()
