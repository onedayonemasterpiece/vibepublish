"""Real SQLite tests, separate from the unchanged schema-design suite."""
import concurrent.futures
import hashlib
import io
import logging
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
import pytest
from PIL import Image
from social_operations.assets import import_image
from social_operations.domain import DomainError, canonical, parse_source
from social_operations.storage import Store


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'ledger.sqlite'
        self.store = Store(self.path)
        self.token = self.store.create_principal('tenant', 'owner', owner=True)
        self.owner = self.store.authenticate(self.token)
        self.store.add_connection(self.owner, 'connection', 'telegram', account_type='fake')
        self.binding = self.store.bind(self.owner, 'owner', 'channel', 'connection', '123')

    def test_token_hashed_and_unknown_denied(self):
        with self.store.connection() as db:
            value = db.execute('SELECT token_hash FROM principals').fetchone()[0]
            self.assertEqual(value, hashlib.sha256(self.token.encode()).hexdigest())
            self.assertNotIn(self.token, value)
        with self.assertRaises(DomainError):
            self.store.authenticate('incorrect_token_which_is_long_enough')

    def test_database_is_private_wal_foreign_keys(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with self.store.connection() as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 12)
            self.assertIsNotNone(db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_store_assets'").fetchone())
            self.assertIsNotNone(db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='telegram_media_admissions'").fetchone())
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO profiles VALUES('other','owner','channel',1,'{}')")

    def test_scoped_binding_revocation_and_cursor(self):
        with self.store.tx() as db:
            cursor = self.store.cursor(db, self.owner, 'test', 'scope', 3)
        token = self.store.create_principal('other', 'partner')
        partner = self.store.authenticate(token)
        with self.store.tx() as db:
            with self.assertRaises(DomainError):
                self.store.cursor_position(db, partner, cursor, 'test', 'scope')
        self.store.revoke_binding(self.owner, self.binding)
        with self.store.tx() as db:
            with self.assertRaises(DomainError):
                self.store.cursor_position(db, self.owner, cursor, 'test', 'scope')
        with self.store.connection() as db:
            self.assertFalse(self.store.bindings(db, self.store.authenticate(self.token)))

    def test_operator_shared_binding_is_explicit(self):
        token = self.store.create_principal('other', 'partner')
        with self.assertRaises(DomainError):
            self.store.bind(self.owner, 'partner', 'channel', 'connection', '123')
        self.store.add_connection(self.owner, 'shared', 'vk', account_type='fake', shared=True)
        self.store.bind(self.owner, 'partner', 'vk_channel', 'shared', '-123')
        with self.store.connection() as db:
            b = self.store.binding(db, self.store.authenticate(token), alias='vk_channel')
            self.assertEqual(b['native_id'], '-123')

    def test_asset_bytes_derivative_and_mime(self):
        output = io.BytesIO()
        Image.new('RGB', (20, 10)).save(output, format='PNG')
        data = output.getvalue()
        asset = import_image(self.store, self.owner, data, 'image/png')
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM assets WHERE id=?', (asset,)).fetchone()
            self.assertEqual(row['sha256'], hashlib.sha256(row['bytes']).hexdigest())
            self.assertEqual(row['source_sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(db.execute('SELECT count(*) FROM assets').fetchone()[0], 2)
        with self.assertRaises(DomainError):
            import_image(self.store, self.owner, data, 'image/jpeg')
        with self.assertRaises(DomainError):
            import_image(self.store, self.owner, b'<svg/>', 'image/svg+xml')

    def test_concurrent_separate_connections_and_restart(self):
        def insert(index):
            store = Store(self.path)
            return store.create_principal('tenant', 'p_'+str(index))
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            tokens = list(pool.map(insert, range(12)))
        reopened = Store(self.path)
        self.assertEqual(len({reopened.authenticate(t).principal_id for t in tokens}), 12)

    def test_backup_includes_committed_wal(self):
        backup = self.path.with_name('backup.sqlite')
        self.store.backup(backup)
        restored = Store(backup)
        self.assertEqual(restored.authenticate(self.token).principal_id, 'owner')
        with restored.connection() as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_forward_urls_bounded_and_private_distinct(self):
        s = parse_source('https://t.me/venue/123?utm_source=fixture')
        self.assertEqual(s.canonical_url, 'https://t.me/venue/123')
        self.assertFalse(parse_source('https://t.me/c/123/4').public_candidate)
        self.assertEqual(parse_source('https://vk.com/wall-123_4').canonical_url, 'https://vk.ru/wall-123_4')
        for url in ('https://example.org/post', 'https://t.me/venue', 'https://t.me/venue/1?comment=3',
                    'https://user:pass@t.me/venue/1', 'https://vk.ru/wall-1_2?reply=3', 'http://t.me/venue/1'):
            with self.subTest(url=url), self.assertRaises(DomainError):
                parse_source(url)


@pytest.mark.parametrize('rollback', [False, True])
@pytest.mark.parametrize('handler_fails', [False, True])
def test_slow_writer_diagnostic_runs_after_release_without_changing_outcome(tmp_path, rollback, handler_fails):
    store = Store(tmp_path / 'ledger.sqlite')
    with store.connection() as db:
        db.execute('CREATE TABLE private_sql_probe(value TEXT)')
    records = []
    writer_acquired = []

    class ProbeHandler(logging.Handler):
        def emit(self, record):
            records.append(record)
            # A handler invoked under the original writer fails immediately.
            observer = sqlite3.connect(store.path, timeout=0, isolation_level=None)
            try:
                observer.execute('BEGIN IMMEDIATE')
                observer.execute("INSERT INTO private_sql_probe VALUES('observer')")
                observer.commit()
                writer_acquired.append(True)
            finally:
                observer.close()
            if handler_fails:
                raise RuntimeError('private handler failure')

    logger = logging.getLogger('social_operations.storage')
    handler = ProbeHandler()
    previous_level = logger.level
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    original_error = ValueError('private rollback exception')
    private_value = 'private SQL argument'

    def perform():
        with store.tx() as db:
            db.execute('INSERT INTO private_sql_probe VALUES(?)', (private_value,))
            time.sleep(1.02)  # An actual hold beyond the diagnostic's one-second threshold.
            if rollback:
                raise original_error

    try:
        with store.tx() as db:
            assert db.execute('SELECT 1').fetchone()[0] == 1
        assert not records
        if rollback:
            with pytest.raises(ValueError) as error:
                perform()
            assert error.value is original_error
        else:
            perform()  # A broken logging handler must not turn a committed write into failure.
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    assert writer_acquired == [True]
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    message = records[0].getMessage()
    event, *fields = message.split()
    assert event == 'sqlite_writer_slow_hold'
    details = dict(field.split('=', 1) for field in fields)
    assert set(details) == {'duration_ms', 'pid', 'thread', 'source', 'function', 'lineno'}
    assert int(details['duration_ms']) >= 1000
    assert int(details['pid']) == os.getpid()
    assert int(details['thread']) == threading.get_ident()
    assert details['source'] == 'test_storage.py' and details['function'] == 'perform'
    assert int(details['lineno']) > 0 and records[0].exc_info is None
    for private in ('private_sql_probe', private_value, str(original_error), 'private handler failure', str(tmp_path)):
        assert private not in message
    with store.connection() as db:
        values = [row[0] for row in db.execute('SELECT value FROM private_sql_probe ORDER BY value')]
    assert values == (['observer'] if rollback else ['observer', private_value])


if __name__ == '__main__':
    unittest.main(verbosity=2)
