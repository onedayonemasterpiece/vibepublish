from __future__ import annotations

import io
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from adapters.telegram import TelegramAdapter
from social_operations.assets import import_image
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.scripted import ScriptedTL
from tests.providers.test_native_adapters import NOW
from tests.providers.test_telegram_topics import ForumTelegramClient, TARGET

TOPIC_URL = 'https://t.me/c/101/3'


def png(rgb):
    out = io.BytesIO()
    Image.new('RGB', (5, 5), rgb).save(out, format='PNG')
    return out.getvalue()


@pytest.mark.asyncio
async def test_thread_url_publish_read_downloads_into_private_assets():
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp) / 'ledger.sqlite', clock=lambda: NOW)
        token = store.create_principal('tenant', 'owner', owner=True)
        actor = store.authenticate(token)
        store.add_connection(actor, 'conn_tg', 'telegram', account_type='mtproto_user',
                             secret_ref='VIBEPUBLISH_TELEGRAM_SESSION', shared=True)
        store.bind(actor, 'owner', 'telegram', 'conn_tg', TARGET)
        first = import_image(store, actor, png((10, 20, 30)), 'image/png')
        second = import_image(store, actor, png((40, 50, 60)), 'image/png')
        client = ForumTelegramClient()
        adapter = TelegramAdapter(client, connection_id='conn_tg', tl=ScriptedTL(), clock=lambda: NOW)
        app = Application(store)
        worker = Worker(store, {'conn_tg': adapter}, worker_id='worker-topic')

        photo_publish = await app.call(actor, 'vibepublish_publish', {
            'to': ['telegram'], 'thread_ref': TOPIC_URL,
            'content': {'text': 'Topic photo'},
            'media': [{'source': {'kind': 'asset', 'id': first}, 'role': 'image'}],
            'request_key': 'topic-photo-1',
        })
        assert photo_publish['state'] == 'accepted', photo_publish
        await worker.run_once()
        photo_done = (await app.call(actor, 'vibepublish_status', {'ids': [photo_publish['operation_id']]}))['receipts'][0]
        assert photo_done['state'] == 'verified', photo_done

        document_publish = await app.call(actor, 'vibepublish_publish', {
            'to': ['telegram'], 'thread_ref': TOPIC_URL,
            'content': {'text': 'Topic document'},
            'media': [{'source': {'kind': 'asset', 'id': second}, 'role': 'document'}],
            'request_key': 'topic-document-1',
        })
        assert document_publish['state'] == 'accepted', document_publish
        await worker.run_once()
        document_done = (await app.call(actor, 'vibepublish_status', {'ids': [document_publish['operation_id']]}))['receipts'][0]
        assert document_done['state'] == 'verified', document_done
        assert client.effects == 2

        read = await app.call(actor, 'vibepublish_read', {
            'query': {'kind': 'thread', 'item_ref': TOPIC_URL}, 'limit': 10,
        })
        assert read['state'] == 'accepted', read
        await worker.run_once()
        result = (await app.call(actor, 'vibepublish_status', {'ids': [read['operation_id']]}))['receipts'][0]
        assert result['state'] == 'verified', result
        assert [item['text'] for item in result['items']] == ['Topic document', 'Topic photo']
        assert [[m['role'] for m in item['media']] for item in result['items']] == [['document'], ['image']]
        evidence = [e for item in result['items'] for e in item['media_evidence']]
        assert [e['media_kind'] for e in evidence] == ['document', 'photo']
        assert all(e['resource_uri'] == 'vibepublish://assets/' + e['asset_ref'] for e in evidence)
        for e in evidence:
            data, mime, sha = app.read_asset(actor, e['asset_ref'])
            assert data.startswith(b'\x89PNG\r\n\x1a\n') and mime == 'image/png' and len(sha) == 64

        with store.connection() as db:
            count_before = db.execute('SELECT count(*) FROM assets').fetchone()[0]
        repeated = await app.call(actor, 'vibepublish_read', {
            'query': {'kind': 'thread', 'item_ref': TOPIC_URL}, 'limit': 10,
        })
        await worker.run_once()
        repeated_result = (await app.call(actor, 'vibepublish_status', {'ids': [repeated['operation_id']]}))['receipts'][0]
        assert repeated_result['state'] == 'verified'
        with store.connection() as db:
            assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == count_before



@pytest.mark.asyncio
async def test_thread_url_never_creates_or_expands_binding():
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp) / 'ledger.sqlite', clock=lambda: NOW)
        token = store.create_principal('tenant', 'owner', owner=True)
        actor = store.authenticate(token)
        store.add_connection(actor, 'conn_tg', 'telegram', account_type='mtproto_user',
                             secret_ref='VIBEPUBLISH_TELEGRAM_SESSION', shared=True)
        store.bind(actor, 'owner', 'telegram', 'conn_tg', TARGET)
        app = Application(store)
        other = 'https://t.me/c/202/3'
        denied = await app.call(actor, 'vibepublish_read', {'query': {'kind': 'thread', 'item_ref': other}})
        assert denied['error']['code'] == 'access_denied' and 'operation_id' not in denied
        denied = await app.call(actor, 'vibepublish_publish', {
            'to': ['telegram'], 'thread_ref': other, 'content': {'text': 'No grant'}})
        assert denied['error']['code'] == 'access_denied' and 'operation_id' not in denied
        with store.connection() as db:
            assert db.execute('SELECT count(*) FROM bindings').fetchone()[0] == 1

@pytest.mark.asyncio
async def test_topic_publication_keeps_native_identity_through_edit_and_delete():
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp) / 'ledger.sqlite', clock=lambda: NOW)
        token = store.create_principal('tenant', 'owner', owner=True)
        actor = store.authenticate(token)
        store.add_connection(actor, 'conn_tg', 'telegram', account_type='mtproto_user',
                             secret_ref='VIBEPUBLISH_TELEGRAM_SESSION', shared=True)
        store.bind(actor, 'owner', 'telegram', 'conn_tg', TARGET)
        client = ForumTelegramClient()
        adapter = TelegramAdapter(client, connection_id='conn_tg', tl=ScriptedTL(), clock=lambda: NOW)
        app = Application(store)
        worker = Worker(store, {'conn_tg': adapter}, worker_id='worker-topic-life')

        accepted = await app.call(actor, 'vibepublish_publish', {
            'to': ['telegram'], 'thread_ref': TOPIC_URL, 'content': {'text': 'Before'}, 'request_key': 'topic-life'})
        await worker.run_once()
        published = (await app.call(actor, 'vibepublish_status', {'ids': [accepted['operation_id']]}))['receipts'][0]
        first_delivery = published['deliveries'][0]
        native_url = first_delivery.get('url')
        assert published['deliveries'][0]['observed'] == 'published'

        edited = await app.call(actor, 'vibepublish_publication_update', {
            'publication_id': accepted['resource_id'], 'expected_revision': 1,
            'change': {'kind': 'edit', 'content': {'text': 'After'}}, 'request_key': 'topic-edit'})
        await worker.run_once()
        edited_done = (await app.call(actor, 'vibepublish_status', {'ids': [edited['operation_id']]}))['receipts'][0]
        assert edited_done['state'] == 'verified'
        assert edited_done['deliveries'][0].get('url') == native_url
        thread = await adapter.read(__import__('adapters.port', fromlist=['ReadRequest']).ReadRequest(
            'conn_tg', TARGET, 'thread', 10, topic_root_id='3'), __import__('adapters.port', fromlist=['Hooks']).Hooks(
            lambda *a: _noop(), lambda *a: _noop(), lambda *a: _noop()))
        assert [item.text for item in thread.items] == ['After']

        deleted = await app.call(actor, 'vibepublish_publication_update', {
            'publication_id': accepted['resource_id'], 'expected_revision': 2,
            'change': {'kind': 'delete'}, 'request_key': 'topic-delete'})
        await worker.run_once()
        deleted_done = (await app.call(actor, 'vibepublish_status', {'ids': [deleted['operation_id']]}))['receipts'][0]
        assert deleted_done['state'] == 'verified'
        assert deleted_done['deliveries'][0]['observed'] == 'deleted'
        assert client.effects == 3


async def _noop():
    return None

@pytest.mark.asyncio
async def test_topic_preview_approval_preserves_topic_target():
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp) / 'ledger.sqlite', clock=lambda: NOW)
        token = store.create_principal('tenant', 'owner', owner=True)
        actor = store.authenticate(token)
        store.add_connection(actor, 'conn_tg', 'telegram', account_type='mtproto_user',
                             secret_ref='VIBEPUBLISH_TELEGRAM_SESSION', shared=True)
        store.bind(actor, 'owner', 'telegram', 'conn_tg', TARGET)
        client = ForumTelegramClient()
        adapter = TelegramAdapter(client, connection_id='conn_tg', tl=ScriptedTL(), clock=lambda: NOW)
        app = Application(store)
        worker = Worker(store, {'conn_tg': adapter}, worker_id='worker-topic-preview')

        accepted = await app.call(actor, 'vibepublish_publish', {
            'to': ['telegram'], 'thread_ref': TOPIC_URL, 'content': {'text': 'Previewed'},
            'mode': 'preview', 'request_key': 'topic-preview'})
        await worker.run_once()
        preview = (await app.call(actor, 'vibepublish_status', {'ids': [accepted['operation_id']]}))['receipts'][0]
        assert preview['state'] == 'needs_approval' and client.effects == 0
        approved = await app.call(actor, 'vibepublish_publication_update', {
            'publication_id': accepted['resource_id'], 'expected_revision': 1,
            'change': {'kind': 'approve', 'token': preview['review_token']}, 'request_key': 'topic-preview-approve'})
        await worker.run_once()
        done = (await app.call(actor, 'vibepublish_status', {'ids': [approved['operation_id']]}))['receipts'][0]
        assert done['state'] == 'verified' and client.effects == 1
        sent = next(message for (peer, ident), message in client.messages.items() if peer == 101 and ident not in {3, 9})
        assert sent.reply_to.forum_topic and sent.reply_to.reply_to_top_id == 3
