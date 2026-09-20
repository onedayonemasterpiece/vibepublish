from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "deploy/devcoveer/vibepublish-worker.service"
INSTALLER = ROOT / "deploy/devcoveer/install_production_worker.py"


def _installer_module():
    spec = spec_from_file_location("production_worker_installer", INSTALLER)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_worker_unit_wires_existing_codex_task_imagegen_without_provider_drift():
    text = UNIT.read_text()
    assert text.count(
        "--codex-task-artifacts /home/dev/.local/state/vibepublish/imagegen"
    ) == 1
    for required in (
        "--db /home/dev/.local/state/vibepublish/vibepublish.sqlite3",
        "--telegram-env-file /home/dev/.env",
        "--telegram-session-key TELEGRAM_VIBE_PUBLISH",
        "--telegram-api-id-key TELEGRAM_API_ID",
        "--telegram-api-hash-key TELEGRAM_API_HASH",
        "--providers telegram vk",
        "--vk-env-file /home/dev/.env",
        "--vk-token-key VK_USER_TOKEN1",
    ):
        assert required in text
    assert "OPENAI_API_KEY" not in text
    assert "CODEX_API_KEY" not in text
    assert "NoNewPrivileges=true" in text
    assert "PrivateTmp=true" in text
    assert "UMask=0077" in text


def test_installer_uses_private_sibling_roots_and_validates_unit(tmp_path):
    module = _installer_module()
    assert module.IMAGEGEN_ROOT == Path("/home/dev/.local/state/vibepublish/imagegen")
    assert module.IMAGEGEN_TASK_ROOT == Path(
        "/home/dev/.local/state/vibepublish/imagegen-tasks"
    )
    module._validate_unit(UNIT.read_bytes())
    private = tmp_path / "private"
    module._private_dir(private)
    assert private.stat().st_mode & 0o077 == 0
