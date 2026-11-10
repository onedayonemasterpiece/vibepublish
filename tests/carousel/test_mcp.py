"""The model receives real reference/render pixels through the MCP SDK transport."""
import base64
import io
import json

from PIL import Image
from starlette.testclient import TestClient

from social_operations.server import create_app
from social_operations.storage import Store


def test_model_sees_reference_changes_seam_and_exports_via_mcp(tmp_path):
    store = Store(tmp_path / 'ledger.sqlite')
    token = store.create_principal('tenant', 'owner', owner=True)
    bank = tmp_path / 'carousel-references'
    bank.mkdir()
    Image.new('RGB', (100, 80), '#e1b24b').save(bank / 'reference.png')
    (bank / 'catalog.json').write_text(json.dumps({'owner': {'tenant_id': 'tenant', 'principal_id': 'owner'},
        'references': [{'id': 'E01', 'file': 'reference.png', 'title': 'Общая панель',
        'tags': ['панель'], 'look_for': 'Панель пересекает шов', 'transfer': 'Объединить зоны',
        'source': {'slack_url': 'https://example.slack.com/archives/C1/p1', 'file_id': 'F1'},
        'use_note': 'Reference only'}]}))
    with TestClient(create_app(store)) as client:
        client.headers.update({'Authorization': 'Bearer ' + token,
                               'Accept': 'application/json, text/event-stream'})

        def rpc(method, params):
            response = client.post('/mcp/', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
            assert response.status_code == 200, response.text
            return response.json()['result']

        def call(command, key=None):
            arguments = {'command': command, **({'request_key': key} if key else {})}
            result = rpc('tools/call', {'name': 'vibepublish_carousel', 'arguments': arguments})
            assert not result.get('isError'), result
            return result

        def picture(result):
            blocks = [block for block in result['content'] if block['type'] == 'image']
            assert len(blocks) == 1
            with Image.open(io.BytesIO(base64.b64decode(blocks[0]['data']))) as image:
                return image.convert('RGB')

        rpc('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                           'clientInfo': {'name': 'carousel-test', 'version': '1'}})
        tool = next(t for t in rpc('tools/list', {})['tools'] if t['name'] == 'vibepublish_carousel')
        assert tool['annotations']['readOnlyHint'] is False
        assert tool['annotations']['destructiveHint'] is False
        assert tool['annotations']['openWorldHint'] is True  # icons may read public SVG Repo over HTTP
        listed = call({'kind': 'get', 'scope': 'library', 'query': 'панель'})
        assert listed['structuredContent']['references'][0]['id'] == 'E01'
        assert not any(b['type'] == 'image' for b in listed['content'])
        seen = call({'kind': 'get', 'scope': 'reference', 'reference_id': 'E01', 'region': [20, 10, 30, 40]})
        assert picture(seen).size == (30, 40)
        assert picture(seen).getpixel((10, 10)) == (225, 178, 75)
        denied = rpc('tools/call', {'name': 'vibepublish_carousel', 'arguments': {
            'command': {'kind': 'create', 'brief': 'Cannot embed a reference-bank URI',
                'svg': '<svg xmlns="http://www.w3.org/2000/svg"><image href="vibepublish://carousel-references/E01"/></svg>'},
            'request_key': 'reference-is-not-an-asset'}})
        assert denied['isError'] and denied['structuredContent']['error']['code'] == 'carousel_svg_unsafe'
        created = call({'kind': 'create', 'brief': 'Памятник и его исторический смысл',
                        'card_count': 3, 'card_width': 128, 'card_height': 160}, 'create')['structuredContent']
        ident = created['carousel_id']
        revised = call({'kind': 'revise', 'carousel_id': ident, 'expected_revision': 1,
            'svg': '<svg xmlns="http://www.w3.org/2000/svg"><rect x="100" y="20" width="100" height="120" fill="#e1b24b"/></svg>',
            'reference_use': {'reference_id': 'E01', 'observation': 'Одна панель пересекает шов',
                              'change': 'Панель пересекает шов между первой и второй карточкой'}}, 'revise')
        assert revised['structuredContent']['revision'] == 2
        crop = call({'kind': 'render', 'carousel_id': ident, 'revision': 2,
                     'view': 'region', 'region': [118, 30, 20, 100]})
        assert picture(crop).size == (20, 100)
        assert picture(crop).getextrema() == ((225, 225), (178, 178), (75, 75))
        exported = call({'kind': 'export', 'carousel_id': ident, 'revision': 2}, 'export')['structuredContent']
        assert [c['index'] for c in exported['cards']] == [1, 2, 3]
        assert exported['private'] and exported['generation_dispatch'] == 'not_sent'
        assert call({'kind': 'export', 'carousel_id': ident, 'revision': 2}, 'export')['structuredContent']['operation_id'] == exported['operation_id']
    with store.connection() as db:
        for table in ('publications', 'attempts', 'visual_jobs'):
            assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_work_context_is_model_visible_revision_bound_and_frozen_on_replay(tmp_path, monkeypatch):
    from social_operations import carousel_guide
    store = Store(tmp_path / 'context.sqlite')
    token = store.create_principal('tenant', 'owner', owner=True)
    story = {'materials': [{'id': 'm1', 'text': 'Сначала источник, затем его толкование.'}],
        'points': [{'id': 'p1', 'text': 'Автор наблюдает смену назначения места',
                    'material_ids': ['m1'], 'modality': 'observation'}],
        'narrative': 'Изменение места и его значение.',
        'cards': [{'id': 'c1', 'text': 'Место изменилось', 'point_ids': []}]}
    with TestClient(create_app(store)) as client:
        client.headers.update({'Authorization': 'Bearer ' + token,
                               'Accept': 'application/json, text/event-stream'})
        def rpc(method, params):
            response = client.post('/mcp/', json={'jsonrpc': '2.0', 'id': 1,
                                                'method': method, 'params': params})
            assert response.status_code == 200, response.text
            return response.json()['result']
        def call(command, key=None):
            result = rpc('tools/call', {'name': 'vibepublish_carousel', 'arguments': {
                'command': command, **({'request_key': key} if key else {})}})
            assert not result.get('isError'), result
            structured = result['structuredContent']
            # Both ordinary JSON replies and image renders expose the same context.
            visible = json.loads(next(b['text'] for b in result['content'] if b['type'] == 'text'))
            assert visible['work_context'] == structured['work_context']
            return structured
        rpc('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                           'clientInfo': {'name': 'cold-context-contract', 'version': '1'}})
        create = {'kind': 'create', 'story': story, 'card_count': 3,
                  'card_width': 128, 'card_height': 160}
        first = call(create, 'create')
        ident = first['carousel_id']
        context = first['work_context']
        assert context['revision'] == 1 and context['guide_sha256'] == carousel_guide.guide_digest()
        assert context['recommendation']['suggested_focus'] == 'declared_coverage'
        assert 'p1' in context['facts'][1]['text'] and story['points'][0]['text'] in context['facts'][1]['text']
        assert {f['basis'] for f in context['facts']} == {'observed', 'model_declared', 'reviewed'}
        assert context['facts'][2]['status'] == 'not_registered'
        # The single recommendation really resolves through the normal guide command.
        advised = rpc('tools/call', {'name': 'vibepublish_carousel', 'arguments': {
            'command': context['recommendation']['get']}})
        assert not advised.get('isError') and advised['structuredContent']['topic'] == 'steps/s02'
        edit = {'kind': 'revise', 'carousel_id': ident, 'expected_revision': 1,
            'story_changes': [{'kind': 'card_patch', 'id': 'c1', 'point_ids': ['p1']}],
            'svg': '<svg xmlns="http://www.w3.org/2000/svg" width="384" height="160">'
                   '<rect width="384" height="160" fill="#123456"/></svg>'}
        revised = call(edit, 'edit')
        assert revised['work_context']['revision'] == 2
        assert revised['work_context']['recommendation']['suggested_focus'] == 'visual_review'
        call({'kind': 'revise', 'carousel_id': ident, 'expected_revision': 2,
              'note': 'New current revision, same pixels'}, 'note')
        rendered = call({'kind': 'render', 'carousel_id': ident, 'revision': 2, 'view': 'master'})
        old_story = call({'kind': 'get', 'scope': 'story', 'carousel_id': ident, 'revision': 2})
        export = {'kind': 'export', 'carousel_id': ident, 'revision': 2}
        exported = call(export, 'export')
        for result in (rendered, old_story, exported):
            assert result['work_context']['revision'] == 2
        assert exported['work_context']['recommendation']['get']['section'] == 'Перед публикацией'
        # Simulate a later installed guide corpus without modifying repository files.
        later_guide = tmp_path / 'later-guide'
        later_guide.mkdir()
        (later_guide / 'README.md').write_text('Later guide release')
        monkeypatch.setattr(carousel_guide, '_DOC_DIR', later_guide)
        fresh = call({'kind': 'get', 'scope': 'story', 'carousel_id': ident})['work_context']
        assert fresh['revision'] == 3 and fresh['guide_sha256'] != context['guide_sha256']
        for command, key, receipt in ((create, 'create', first), (edit, 'edit', revised),
                                      (export, 'export', exported)):
            replay = call(command, key)
            assert replay['operation_id'] == receipt['operation_id']
            assert replay['work_context'] == receipt['work_context']
            status = rpc('tools/call', {'name': 'vibepublish_status',
                'arguments': {'ids': [receipt['operation_id']]}})
            assert not status.get('isError'), status
            assert status['structuredContent']['receipts'][0]['work_context'] == receipt['work_context']
            text = json.loads(next(b['text'] for b in status['content'] if b['type'] == 'text'))
            assert text['receipts'][0]['work_context'] == receipt['work_context']
