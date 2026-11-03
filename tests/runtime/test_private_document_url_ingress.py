"""Private HTTPS DOCUMENT import must not expose service credentials or a second publication path."""
import hashlib

import pytest

from social_operations.domain import DomainError
from social_operations.ingress import IngressApplication
from social_operations.document_url_ingress import PublicDocument, validate_archive_document_url
from social_operations.storage import Store
from .test_media_store import runtime

PDF = b"%PDF-1.7\nPrivate original test source.\n"
URL = "https://prussia.online/Data/Book/test/test-book/Original%20Book.pdf"


def command(url=URL, sha=None, filename="Original Book.pdf"):
    return {"command": {"kind": "put_url", "to": "vault",
            "thread_ref": "https://t.me/c/4379835477/5", "url": url,
            "mime": "application/pdf", "filename": filename,
            "expected_sha256": sha or hashlib.sha256(PDF).hexdigest()},
            "request_key": "original-book-url-key"}


@pytest.mark.parametrize("url", [
    "http://prussia.online/Data/Book/a/b/a.pdf",
    "https://prussia.online.evil.test/Data/Book/a/b/a.pdf",
    "https://evil.prussia.online/Data/Book/a/b/a.pdf",
    "https://127.0.0.1/Data/Book/a/b/a.pdf",
    "https://prussia.online:8443/Data/Book/a/b/a.pdf",
    "https://user:password@prussia.online/Data/Book/a/b/a.pdf",
    "https://prussia.online/private/a.pdf",
    "https://prussia.online/Data/Book/a/b/%2e%2e%2fa.pdf",
    "https://prussia.online/Data/Book/a/b/a.pdf?key=secret",
    "https://prussia.online/Data/Book/a/b/a.pdf#fragment",
    "https://prussia.online/Data/Book/a/b/a.png",
])
def test_document_ingress_rejects_untrusted_or_unbounded_urls(url):
    with pytest.raises(DomainError):
        validate_archive_document_url(url, "application/pdf")


@pytest.mark.asyncio
async def test_owner_original_url_put_is_single_verified_document_and_safe_replay(tmp_path):
    store,owner,_asset,provider,_app,worker=runtime(tmp_path)
    calls=[]
    async def fetch(url,mime):
        calls.append(url)
        return PublicDocument(PDF,"application/pdf",url)
    app=IngressApplication(store,document_fetcher=fetch)
    assert "vibepublish_media_store" in {t["name"] for t in app.tools(owner)}
    first=await app.call(owner,"vibepublish_media_store",command())
    assert first.get("operation_id"),first
    repeated=await app.call(owner,"vibepublish_media_store",command())
    assert repeated["operation_id"]==first["operation_id"]
    assert len(calls)==1
    await worker.run_once()
    done=store.receipt(owner,first["operation_id"])
    assert done["state"]=="verified",done
    again=await app.call(owner,"vibepublish_media_store",command())
    assert again["operation_id"]==first["operation_id"]
    assert len(calls)==1 and provider.effects==1
    # Alias replay is keyed to the original URL+filename+target, not a loose command key.
    changed=await app.call(owner,"vibepublish_media_store",command(filename="Different.pdf"))
    assert changed["error"]["code"]=="idempotency_conflict"
    assert provider.effects==1


@pytest.mark.asyncio
async def test_url_import_checks_scope_target_and_hash_before_dispatch(tmp_path):
    store,owner,_asset,provider,_app,worker=runtime(tmp_path)
    fetched=[]
    async def fetch(url,mime):
        fetched.append(url)
        return PublicDocument(PDF,"application/pdf",url)
    app=IngressApplication(store,document_fetcher=fetch)
    denied=await app.call(owner,"vibepublish_media_store",
        {**command(), "command": {**command()["command"],"to":"unbound"}})
    assert denied["error"]["code"]=="access_denied"
    bad=await app.call(owner,"vibepublish_media_store",command(sha="a"*64))
    assert bad["error"]["code"]=="asset_integrity"
    assert provider.effects==0
    assert len(fetched)==1
    other=store.authenticate(store.create_principal("t","media-service",scopes={"media.store"}))
    owner_binding=store.bind(owner,other.principal_id,"vault-service","connection","-1004379835477",rights=("publish",))
    store.set_service_media_topic(owner,other.principal_id,"vault-service","5")
    service_command=command()
    service_command["command"]["to"]="vault-service"
    blocked=await app.call(other,"vibepublish_media_store",service_command)
    assert blocked["error"]["code"]=="access_denied"
    assert provider.effects==0


@pytest.mark.asyncio
async def test_plain_put_url_source_remains_denied_and_nonowner_cannot_reach_fetcher(tmp_path):
    store,owner,asset,provider,_app,worker=runtime(tmp_path)
    fetched=[]
    async def fetch(url,mime):
        fetched.append(url)
        return PublicDocument(PDF,"application/pdf",url)
    app=IngressApplication(store,document_fetcher=fetch)
    legacy={"command":{"kind":"put","to":"vault",
            "thread_ref":"https://t.me/c/4379835477/5","content":{"text":""},
            "media":[{"source":{"kind":"url","url":URL},"role":"document"}]},
            "request_key":"legacy-url-denial"}
    old=await app.call(owner,"vibepublish_media_store",legacy)
    assert old["error"]["code"]=="media_ingress_not_enabled"
    assert fetched==[] and provider.effects==0

@pytest.mark.asyncio
async def test_document_original_magic_is_checked_without_optional_hash(tmp_path):
    store,owner,_asset,provider,_app,worker=runtime(tmp_path)
    async def fetch(url,mime):
        return PublicDocument(b"not a PDF at all", "application/pdf", url)
    app=IngressApplication(store,document_fetcher=fetch)
    supplied=command()
    supplied["command"].pop("expected_sha256")
    denied=await app.call(owner,"vibepublish_media_store",supplied)
    assert denied["error"]["code"]=="asset_container_invalid"
    assert provider.effects==0


@pytest.mark.asyncio
async def test_owner_djvu_url_import_and_sha_without_pdf_assumption(tmp_path):
    store,owner,_asset,provider,_app,worker=runtime(tmp_path)
    djvu=b"AT&TFORM" + b"\x00\x00\x00\x00" + b"DJVU" + b"archived scanned pages"
    url="https://prussia.online/Data/Book/ve/vergessene-kultur/Original.djvu"
    async def fetch(incoming,mime):
        assert incoming==url and mime=="image/vnd.djvu"
        return PublicDocument(djvu,mime,url)
    app=IngressApplication(store,document_fetcher=fetch)
    args=command(url=url,filename="Original.djvu",sha=hashlib.sha256(djvu).hexdigest())
    args["command"]["mime"]="image/vnd.djvu"
    result=await app.call(owner,"vibepublish_media_store",args)
    assert result.get("operation_id"),result
    await worker.run_once()
    assert store.receipt(owner,result["operation_id"])["state"]=="verified"
    assert provider.effects==1


@pytest.mark.asyncio
async def test_repeated_key_with_changed_url_is_conflict_before_refetch(tmp_path):
    store,owner,_asset,provider,_app,worker=runtime(tmp_path)
    fetches=[]
    async def fetch(url,mime):
        fetches.append(url)
        return PublicDocument(PDF,mime,url)
    app=IngressApplication(store,document_fetcher=fetch)
    first=await app.call(owner,"vibepublish_media_store",command())
    assert first.get("operation_id"),first
    changed=command(url="https://prussia.online/Data/Book/test/test-book/Second.pdf")
    denied=await app.call(owner,"vibepublish_media_store",changed)
    assert denied["error"]["code"]=="idempotency_conflict"
    assert fetches==[URL]
    assert provider.effects==0

def cached_schema_command(url=URL, sha=None, filename="Original Book.pdf", key="cached-owner-source-1"):
    """The already-installed owner's MCP schema permits put/source.kind=url."""
    return {
        "command": {
            "kind": "put", "to": "vault",
            "thread_ref": "https://t.me/c/4379835477/5",
            "content": {"text": ""},
            "media": [{"source": {"kind": "url", "url": url},
                       "role": "document", "caption": "", "alt_text": filename}],
            "origin": {"system": "prussia_online",
                       "ref": "https://prussia.online/books/example",
                       "sha256": sha or hashlib.sha256(PDF).hexdigest()},
        },
        "request_key": key,
    }


@pytest.mark.asyncio
async def test_cached_owner_mcp_put_url_shape_fetches_original_and_reuses_native_receipt(tmp_path):
    from jsonschema import Draft202012Validator
    store, owner, _asset, provider, _app, worker = runtime(tmp_path)
    calls = []
    async def fetch(url, mime):
        calls.append((url, mime))
        return PublicDocument(PDF, "application/pdf", url)
    app = IngressApplication(store, document_fetcher=fetch)
    arguments = cached_schema_command()
    declared = next(t["inputSchema"] for t in app.tools(owner)
                    if t["name"] == "vibepublish_media_store")
    assert Draft202012Validator(declared).is_valid(arguments)
    received = await app.call(owner, "vibepublish_media_store", arguments)
    assert received.get("operation_id"), received
    assert (await app.call(owner, "vibepublish_media_store", arguments))["operation_id"] == received["operation_id"]
    assert calls == [(URL, "application/pdf")]
    await worker.run_once()
    result = store.receipt(owner, received["operation_id"])
    assert result["state"] == "verified" and provider.effects == 1
    listed = await app.call(owner, "vibepublish_media_store", {"command": {
        "kind": "list", "to": "vault", "thread_ref": "https://t.me/c/4379835477/5"}})
    assert any(item.get("origin", {}).get("sha256") == hashlib.sha256(PDF).hexdigest()
               for item in listed.get("media_store_items", [])), listed
    assert (await app.call(owner, "vibepublish_media_store", arguments))["operation_id"] == received["operation_id"]
    assert len(calls) == 1
    wrong = cached_schema_command(url="https://prussia.online/Data/Book/a/b/changed.pdf")
    denied = await app.call(owner, "vibepublish_media_store", wrong)
    assert denied["error"]["code"] == "idempotency_conflict"
    assert len(calls) == 1 and provider.effects == 1


@pytest.mark.asyncio
async def test_cached_mcp_url_owner_guards_do_not_fetch_or_publish(tmp_path):
    store, owner, _asset, provider, _app, _worker = runtime(tmp_path)
    calls=[]
    async def fetch(url, mime):
        calls.append(url)
        return PublicDocument(PDF, mime, url)
    app = IngressApplication(store, document_fetcher=fetch)
    variants = [
        ({"to": "not-bound"}, "access_denied"),
        ({"content": {"text": "must be blank"}}, "media_store_document_required"),
        ({"media": [cached_schema_command()["command"]["media"][0]] * 2},
         "media_store_document_required"),
        ({"media": [{"source": {"kind": "url", "url": URL},
                    "role": "image", "alt_text": "Original Book.pdf"}]},
         "media_store_document_required"),
        ({"origin": {"system": "prussia_online",
                     "ref": "https://prussia.online/books/example"}},
         "media_ingress_not_enabled"),
    ]
    for change, expected in variants:
        args = cached_schema_command(key="blocked-cached-" + str(len(calls)) + "-" + repr(change)[:40])
        args["command"].update(change)
        result = await app.call(owner, "vibepublish_media_store", args)
        assert result["error"]["code"] == expected, result
        assert calls == [] and provider.effects == 0
    foreign = cached_schema_command(
        url="https://evil.example/Data/Book/a/b/source.pdf", key="cached-foreign")
    denied = await app.call(owner, "vibepublish_media_store", foreign)
    assert denied["error"]["code"] == "document_url_not_allowed"
    not_owner = store.authenticate(store.create_principal("t", "scoped-client", scopes={"media.store"}))
    rejected = await app.call(not_owner, "vibepublish_media_store",
                              cached_schema_command(key="cached-nonowner-denied"))
    assert rejected["error"]["code"] == "access_denied"
    assert calls == [] and provider.effects == 0


@pytest.mark.asyncio
async def test_cached_owner_mcp_url_declared_sha_prevents_mismatched_original(tmp_path):
    store, owner, _asset, provider, _app, _worker = runtime(tmp_path)
    async def fetch(url,mime):
        return PublicDocument(PDF, mime, url)
    app=IngressApplication(store,document_fetcher=fetch)
    bad=cached_schema_command(sha="0"*64,key="cached-integrity-negative")
    result=await app.call(owner,"vibepublish_media_store",bad)
    assert result["error"]["code"]=="asset_integrity"
    assert provider.effects==0

@pytest.mark.asyncio
async def test_prussia_iis_legacy_djvu_accept_mime_prevents_406(monkeypatch):
    """The archive serves DjVu as image/x.djvu and rejects a narrower Accept (HTTP 406)."""
    from social_operations import document_url_ingress as ingress

    url = "https://prussia.online/Data/Book/test/legacy/Source.djvu"
    body = b"AT&TFORM" + b"\\x00\\x00\\x00\\x00" + b"DJVU" + b"scan data"

    async def resolve(_url):
        assert _url == url
        return "prussia.online", ["93.184.216.34"]

    class Response:
        def __init__(self, accept):
            # Model the production IIS content negotiation observed on 2026-11-03.
            self.status = 200 if "image/x.djvu" in accept.split(",") else 406
            self.headers = {"Content-Length": str(len(body))}
            self.content = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def iter_chunked(self, _size):
            yield body

    class Session:
        def __init__(self, **kwargs):
            self.accept = kwargs["headers"]["Accept"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def get(self, requested_url, *, allow_redirects):
            assert requested_url == url and allow_redirects is False
            return Response(self.accept)

    monkeypatch.setattr(ingress, "resolve_public_https", resolve)
    monkeypatch.setattr(ingress, "_PinnedResolver", lambda *_: object())
    monkeypatch.setattr(ingress.aiohttp, "TCPConnector", lambda **_: object())
    monkeypatch.setattr(ingress.aiohttp, "ClientSession", Session)
    result = await ingress.fetch_public_document(url, "image/vnd.djvu")
    assert result == ingress.PublicDocument(body, "image/vnd.djvu", url)
