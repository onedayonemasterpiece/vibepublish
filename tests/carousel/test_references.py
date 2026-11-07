"""Reference reads use actual pixels, fresh authorization and private local files."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from social_operations.carousel_references import ReferenceBank, render_asset_full
from social_operations.domain import DomainError
from social_operations.storage import Store


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'ledger.sqlite')
        self.actor = self.store.authenticate(self.store.create_principal('t', 'owner', owner=True))
        self.bank = ReferenceBank(self.store)
        self.bank.root.mkdir(mode=0o700)
        image = Image.new('RGB', (3000, 120), 'blue')
        image.paste((255, 0, 0), (2900, 20, 3000, 120))
        image.save(self.bank.root / 'sample.png')
        self.rows = [{'id': 'E01', 'file': 'sample.png', 'title': 'Органическая панель',
                      'tags': ['панель'], 'look_for': 'Look at the seam', 'transfer': 'One shared shape',
                      'source': {'slack_url': 'https://example.slack.com/archives/C1/p1', 'file_id': 'F1'},
                      'use_note': 'Visual reference; republication rights unknown'}]
        self.save_catalog()

    def save_catalog(self):
        (self.bank.root / 'catalog.json').write_text(json.dumps({
            'owner': {'tenant_id': 't', 'principal_id': 'owner'}, 'references': self.rows}))

    def code(self, expected, action):
        with self.assertRaises(DomainError) as caught:
            action()
        self.assertEqual(caught.exception.code, expected)
        return caught.exception.output()

    def test_full_bounded_and_crop_uses_original_pixels(self):
        full = self.bank.get(self.actor, 'E01')
        self.assertLessEqual(full.metadata['width'], 2560)
        self.assertLessEqual(len(full.data), 2 * 1024 * 1024)
        self.assertEqual((full.metadata['source_width'], full.metadata['source_height']), (3000, 120))
        self.assertEqual(full.metadata['view'], 'full')
        crop = self.bank.get(self.actor, 'E01', [2900, 20, 100, 100])
        with Image.open(io.BytesIO(crop.data)) as image:
            self.assertEqual(image.size, (100, 100))
            self.assertEqual(image.getpixel((50, 50)), (255, 0, 0))
        self.assertEqual(crop.metadata['view'], 'crop')
        self.assertEqual(crop.metadata['region'], [2900, 20, 100, 100])
        self.assertEqual(crop.metadata['source_sha256'], full.metadata['source_sha256'])
        for invalid in ([0, 0, 0, 1], [-1, 0, 1, 1], [2999, 0, 2, 1], [True, 0, 1, 1], [0, 1]):
            self.code('carousel_reference_region_invalid', lambda: self.bank.get(self.actor, 'E01', invalid))

    def test_list_grows_without_reload_and_reports_missing(self):
        self.assertEqual(self.bank.list(self.actor, 'ПАНЕЛЬ')['total'], 1)
        self.rows += [{**self.rows[0], 'id': 'E02'}, {**self.rows[0], 'id': 'E03', 'file': 'absent.png'}]
        self.save_catalog()
        page = self.bank.list(self.actor, limit=2)
        self.assertEqual((page['total'], page['next_offset']), (3, 2))
        last = self.bank.list(self.actor, offset=2)['references'][0]
        self.assertFalse(last['available'])
        self.assertNotIn('file', page['references'][0])
        self.assertTrue(self.bank.describe(self.actor, 'E02')['available'])
        self.code('carousel_reference_unavailable', lambda: self.bank.get(self.actor, 'E03'))
        self.code('carousel_reference_not_found', lambda: self.bank.describe(self.actor, 'unknown'))

    def test_crop_handles_palette_transparency_and_cmyk_jpeg(self):
        source = Image.new('P', (10, 10), 0)
        source.putpalette([255, 0, 0] + [0] * 765)
        source.save(self.bank.root / 'sample.png', transparency=0)
        with Image.open(io.BytesIO(self.bank.get(self.actor, 'E01', [0, 0, 5, 5]).data)) as crop:
            self.assertEqual(crop.convert('RGBA').getpixel((0, 0)), (255, 0, 0, 0))
        Image.new('CMYK', (10, 10), (0, 255, 255, 0)).save(self.bank.root / 'sample.png', format='JPEG')
        with Image.open(io.BytesIO(self.bank.get(self.actor, 'E01', [0, 0, 5, 5]).data)) as crop:
            self.assertEqual(crop.getpixel((0, 0)), (255, 0, 0))

    def test_fresh_owner_scope_and_revocation_gate_all_reads(self):
        outsider = self.store.authenticate(self.store.create_principal('t', 'reader', scopes=['visual']))
        for method in (lambda a: self.bank.list(a), lambda a: self.bank.describe(a, 'E01'),
                       lambda a: self.bank.get(a, 'E01')):
            self.code('access_denied', lambda: method(outsider))
        with self.store.tx() as db:
            db.execute("UPDATE principals SET scopes='[]' WHERE id='owner'")
        self.code('visual_scope_required', lambda: self.bank.get(self.actor, 'E01'))
        with self.store.tx() as db:
            db.execute("UPDATE principals SET scopes='[\"visual\"]',owner=0 WHERE id='owner'")
        self.code('access_denied', lambda: self.bank.describe(self.actor, 'E01'))
        with self.store.tx() as db:
            db.execute("UPDATE principals SET owner=1,epoch=epoch+1 WHERE id='owner'")
        self.code('access_revoked', lambda: self.bank.list(self.actor))

    def test_traversal_and_extra_metadata_do_not_disclose_private_paths(self):
        self.rows[0]['private_path'] = '/private/secret.txt'
        self.rows[0]['source']['private_path'] = '/private/secret.txt'
        self.save_catalog()
        self.assertNotIn('secret', json.dumps(self.bank.list(self.actor)))
        for bad in ('../secret.txt', '/private/secret.txt', 'folder/file.png', 'folder\\file.png'):
            self.rows[0]['file'] = bad
            self.save_catalog()
            result = self.code('carousel_reference_catalog_invalid', lambda: self.bank.list(self.actor))
            self.assertNotIn('secret', json.dumps(result))
            self.assertNotIn(str(self.root), json.dumps(result))

    def test_catalog_owner_binding_and_revocation_during_render(self):
        other = self.store.authenticate(self.store.create_principal('other', 'other-owner', owner=True))
        for call in (lambda: self.bank.list(other), lambda: self.bank.describe(other, 'E01'),
                     lambda: self.bank.get(other, 'E01')):
            self.code('access_denied', call)
        (self.bank.root / 'catalog.json').write_text(json.dumps({'references': self.rows}))
        self.code('carousel_reference_catalog_invalid', lambda: self.bank.list(self.actor))
        self.save_catalog()
        def revoke(*args):
            with self.store.tx() as db:
                db.execute("UPDATE principals SET epoch=epoch+1 WHERE id='owner'")
            return render_asset_full(*args)
        with patch('social_operations.carousel_references.render_asset_full', side_effect=revoke):
            self.code('access_revoked', lambda: self.bank.get(self.actor, 'E01'))

    def test_bad_metadata_is_a_catalog_error_before_output_validation(self):
        entry = self.rows[0]
        for change in ({'title': 'x' * 1001}, {'file': 'new example.png'},
                       {'source': {**entry['source'], 'slack_url': 'not a URL'}}):
            self.rows[0] = {**entry, **change}
            self.save_catalog()
            self.code('carousel_reference_catalog_invalid', lambda: self.bank.list(self.actor))

    def test_symlinks_bad_images_and_uninstalled_bank_are_explicit(self):
        (self.root / 'secret.png').write_bytes(b'private contents')
        (self.bank.root / 'sample.png').unlink()
        (self.bank.root / 'sample.png').symlink_to(self.root / 'secret.png')
        self.assertFalse(self.bank.list(self.actor)['references'][0]['available'])
        self.code('carousel_reference_unavailable', lambda: self.bank.get(self.actor, 'E01'))
        (self.bank.root / 'sample.png').unlink()
        (self.bank.root / 'sample.png').write_bytes(b'not an image')
        self.code('invalid_image', lambda: self.bank.get(self.actor, 'E01'))
        (self.bank.root / 'catalog.json').unlink()
        self.code('carousel_reference_unavailable', lambda: self.bank.list(self.actor))
        (self.bank.root / 'catalog.json').symlink_to(self.root / 'secret.png')
        self.code('carousel_reference_unavailable', lambda: self.bank.list(self.actor))
        self.bank.root.rename(self.root / 'hidden-bank')
        self.bank.root.symlink_to(self.root / 'hidden-bank', target_is_directory=True)
        self.code('carousel_reference_unavailable', lambda: self.bank.list(self.actor))


    def test_semantic_token_overlap_uses_russian_inflections_and_never_hides_bank(self):
        self.rows += [
            {**self.rows[0], 'id': 'E02', 'title': 'Монументальная архитектура',
             'tags': ['памятник'], 'look_for': 'Масштаб фасада'},
            {**self.rows[0], 'id': 'E03', 'title': 'Типография и плакат',
             'tags': ['леттеринг'], 'look_for': 'Крупный заголовок'},
        ]
        self.save_catalog()
        result = self.bank.list(self.actor, 'типографика памятник монумент архитектура')
        self.assertEqual([row['id'] for row in result['references']], ['E02', 'E03', 'E01'])
        self.assertEqual([row['matched'] for row in result['references']], [True, True, False])
        no_hits = self.bank.list(self.actor, 'абсолютнонесуществующее')
        self.assertEqual([row['id'] for row in no_hits['references']], ['E01', 'E02', 'E03'])
        self.assertTrue(all(row['matched'] is False for row in no_hits['references']))
        self.assertEqual(self.bank.list(self.actor, 'nothing', offset=99)['references'], [])

    def test_ranked_library_paginates_once_and_stops_at_end(self):
        self.rows += [{**self.rows[0], 'id': f'E0{number}'} for number in range(2, 6)]
        self.save_catalog()
        ids, offset, sizes = [], 0, []
        while True:
            page = self.bank.list(self.actor, 'панель', limit=2, offset=offset)
            self.assertEqual(page['offset'], offset)
            self.assertEqual(page['total'], 5)
            ids.extend(row['id'] for row in page['references'])
            sizes.append(len(page['references']))
            if page['next_offset'] is None:
                break
            offset = page['next_offset']
        self.assertEqual(sizes, [2, 2, 1])
        self.assertEqual(ids, ['E01', 'E02', 'E03', 'E04', 'E05'])
        for offset in (5, 99):
            end = self.bank.list(self.actor, 'панель', limit=2, offset=offset)
            self.assertEqual(end['references'], [])
            self.assertEqual(end['offset'], offset)
            self.assertIsNone(end['next_offset'])
