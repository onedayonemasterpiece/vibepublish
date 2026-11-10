"""Real Store regression for owner-scoped image lookup amid unrelated assets."""
import hashlib
import io

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from social_operations.assets import insert_verified_image, verify_image
from social_operations.storage import Store


def image(number):
    output = io.BytesIO()
    metadata = PngInfo()
    metadata.add_text("source", str(number))
    Image.new("RGB", (1, 1), (number % 256, (number // 256) % 256, 71)).save(
        output, "PNG", pnginfo=metadata)
    return verify_image(output.getvalue(), "image/png")


def test_owned_image_reuse_does_not_scan_unrelated_asset_inventory(tmp_path):
    now = 1_800_000_000
    store = Store(tmp_path / "ledger.sqlite", clock=lambda: now)
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    other = store.authenticate(store.create_principal("tenant", "other"))
    wanted = image(0)
    with store.tx() as db:
        expected = insert_verified_image(store, db, actor, wanted)
        for number in range(1, 1001):
            insert_verified_image(store, db, actor, image(number))
        foreign = insert_verified_image(store, db, other, wanted)
        # A later valid owned copy must retain ORDER BY created DESC semantics.
        db.execute("""INSERT INTO assets
            SELECT 'asset_later_owned',tenant_id,principal_id,sha256,mime,width,height,
                   bytes,source_sha256,created+1 FROM assets WHERE id=?""", (expected,))
        before = db.execute("SELECT count(*),SUM(length(bytes)) FROM assets").fetchone()
        steps = [0]
        def progress():
            steps[0] += 100
            return 0
        db.set_progress_handler(progress, 100)
        try:
            result = insert_verified_image(store, db, actor, wanted)
        finally:
            db.set_progress_handler(None, 0)
        assert steps[0] < 2000, (
            "Reusing one image scanned unrelated inventory", steps[0])
        assert result == "asset_later_owned" and result != foreign
        assert tuple(db.execute("SELECT count(*),SUM(length(bytes)) FROM assets").fetchone()) == tuple(before)
        row = db.execute("SELECT * FROM assets WHERE id=?", (result,)).fetchone()
        assert row["bytes"] == wanted.data
        assert row["sha256"] == hashlib.sha256(wanted.data).hexdigest()
        assert row["source_sha256"] == hashlib.sha256(wanted.original).hexdigest()
        assert (row["tenant_id"], row["principal_id"]) == (actor.tenant_id, actor.principal_id)

    # Opening an existing v12 database is additive/idempotent, without rewriting bytes.
    for _ in range(2):
        reopened = Store(store.path, clock=store.clock)
        with reopened.connection() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 13
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
            assert tuple(db.execute("SELECT count(*),SUM(length(bytes)) FROM assets").fetchone()) == tuple(before)
        with reopened.tx() as db:
            assert insert_verified_image(reopened, db, actor, wanted) == result
