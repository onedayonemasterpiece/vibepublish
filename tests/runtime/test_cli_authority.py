"""Least-privilege local administration: no real credentials or provider effects."""
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from contracts.social_mcp_v1 import catalog
from social_operations import cli, storage
from social_operations.domain import DomainError
from social_operations.storage import ALL_BINDING_RIGHTS, ALL_SCOPES, DEFAULT_BINDING_RIGHTS, Store


class RecordingStore:
    def __init__(self):
        self.calls = []

    def authenticate(self, value):
        return SimpleNamespace(owner=True)

    def create_principal(self, tenant, principal, **kwargs):
        self.calls.append(("principal", tenant, principal, kwargs))
        return "offline-test-placeholder"

    def bind(self, actor, principal, alias, connection, native_id, **kwargs):
        self.calls.append(("bind", principal, alias, connection, native_id, kwargs))
        return "bind_offline_test"


@pytest.fixture
def recording_cli(monkeypatch):
    store = RecordingStore()
    monkeypatch.setattr(cli, "Store", lambda path: store)
    monkeypatch.setattr(cli.os, "getenv", lambda *args: "offline-owner-placeholder")
    monkeypatch.setattr(cli.getpass, "getpass", lambda *args: "offline-owner-placeholder")
    return store


def run_cli(monkeypatch, arguments):
    monkeypatch.setattr("sys.argv", ["vibepublish", "--db", "offline-only.sqlite", *arguments])
    cli.main()


def test_explicit_principal_scopes_replace_broad_defaults(recording_cli, monkeypatch, capsys):
    run_cli(monkeypatch, ["principal", "--tenant", "test", "--principal", "publisher",
                         "--scope", "bootstrap", "--scope", "publish", "--scope", "status",
                         "--scope", "publish"])
    assert recording_cli.calls == [
        ("principal", "test", "publisher", {"scopes": frozenset({"bootstrap", "publish", "status"})})]
    assert "offline-test-placeholder" in capsys.readouterr().out


def test_principal_omitted_scopes_preserve_legacy_defaults(recording_cli, monkeypatch):
    run_cli(monkeypatch, ["principal", "--tenant", "test", "--principal", "publisher"])
    assert recording_cli.calls[0][-1] == {"scopes": frozenset({
        "bootstrap", "publish", "publication.manage", "visual", "status",
        "forward", "destination.profile"})}


BIND_ARGS = ["bind", "--principal", "publisher", "--alias", "test_max",
             "--connection", "offline_max", "--native-id", "-100001", "--label", "Offline"]


def test_explicit_binding_rights_replace_broad_defaults(recording_cli, monkeypatch):
    run_cli(monkeypatch, [*BIND_ARGS, "--right", "publish", "--right", "publish"])
    assert recording_cli.calls[0][-1] == {"label": "Offline", "rights": ("publish",)}


def test_bind_omitted_rights_keep_store_default(recording_cli, monkeypatch):
    run_cli(monkeypatch, BIND_ARGS)
    assert recording_cli.calls[0][-1] == {"label": "Offline"}
    assert Store.bind.__kwdefaults__["rights"] == (
        "publish", "edit", "reschedule", "cancel", "delete", "forward")


@pytest.mark.parametrize("arguments", [
    ["principal", "--tenant", "test", "--principal", "publisher", "--scope", "unknown"],
    ["principal", "--tenant", "test", "--principal", "publisher", "--scope", "source.snapshot"],
    ["principal", "--tenant", "test", "--principal", "publisher", "--scope", ""],
    ["principal", "--tenant", "test", "--principal", "publisher", "--scope"],
    [*BIND_ARGS, "--right", "unknown"],
    [*BIND_ARGS, "--right", "source.snapshot"],
    [*BIND_ARGS, "--right", ""],
    [*BIND_ARGS, "--right"],
    ["grant-rights", "--binding-id", "bind_offline", "--right", "unknown"],
])
def test_cli_rejects_bad_authority_before_opening_store(monkeypatch, arguments):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid authority must fail before store or authentication access")
    monkeypatch.setattr(cli, "Store", forbidden)
    with pytest.raises(SystemExit) as error:
        run_cli(monkeypatch, arguments)
    assert error.value.code == 2


@pytest.mark.parametrize("values", [
    None, "publish", {"publish": True}, 1, ["unknown"], ["source.snapshot"],
    ["publish", None], ["publish", []],
])
def test_store_rejects_unknown_or_malformed_scopes_before_effect(monkeypatch, values):
    store = Store.__new__(Store)
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid authority must not generate credentials or enter a transaction")
    monkeypatch.setattr(store, "tx", forbidden)
    monkeypatch.setattr(storage.secrets, "token_urlsafe", forbidden)
    with pytest.raises(DomainError) as error:
        store.create_principal("offline", "offline", scopes=values)
    assert error.value.code == "invalid_principal_scopes"


@pytest.mark.parametrize("values", [
    None, "publish", {"publish": True}, 1, ["unknown"], ["source.snapshot"],
    ["publish", None], ["publish", []],
])
def test_store_rejects_bad_binding_and_grant_rights_before_effect(monkeypatch, values):
    store = Store.__new__(Store)
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid authority must not enter a transaction")
    monkeypatch.setattr(store, "tx", forbidden)
    owner = SimpleNamespace(owner=True)
    with pytest.raises(DomainError) as error:
        store.bind(owner, "offline", "test_max", "offline_max", "-100001", rights=values)
    assert error.value.code == "invalid_binding_rights"
    with pytest.raises(DomainError) as error:
        store.grant_binding_rights(owner, "bind_offline", values)
    assert error.value.code == "invalid_binding_rights"


@pytest.mark.parametrize("values", [[], (), set(), frozenset()])
def test_empty_authority_remains_safe_and_compatible(values):
    assert storage._validated_permissions(values, ALL_SCOPES, "invalid_principal_scopes") == ()
    assert storage._validated_permissions(values, ALL_BINDING_RIGHTS, "invalid_binding_rights") == ()


def test_valid_authority_is_deduplicated_without_adding_rights():
    assert storage._validated_permissions(
        ["publish", "publish"], ALL_BINDING_RIGHTS, "invalid_binding_rights") == ("publish",)
    assert set(storage._validated_permissions(
        ALL_SCOPES, ALL_SCOPES, "invalid_principal_scopes")) == ALL_SCOPES
    assert set(DEFAULT_BINDING_RIGHTS) < ALL_BINDING_RIGHTS


@pytest.mark.parametrize("provider,url", [
    ("telegram", "https://t.me/offline_channel"), ("vk", "https://vk.com/offline_channel"),
    ("max", "https://max.ru/offline_channel"),
])
def test_exact_destination_resolve_accepts_provider_urls(provider, url):
    schema = next(t["inputSchema"] for t in catalog()["tools"]
                  if t["name"] == "vibepublish_destinations")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate({"command": {"kind": "resolve", "provider": provider, "url": url}})


@pytest.mark.parametrize("provider", ["telegram", "vk", "max"])
def test_raw_destination_ids_remain_telegram_vk_only(provider):
    schema = next(t["inputSchema"] for t in catalog()["tools"]
                  if t["name"] == "vibepublish_destinations")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    command = {"kind": "resolve", "provider": provider, "provider_id": "-100001"}
    assert bool(list(validator.iter_errors({"command": command}))) == (provider == "max")
    command["url"] = "https://max.ru/offline_channel"
    assert list(validator.iter_errors({"command": command}))
