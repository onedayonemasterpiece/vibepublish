#!/usr/bin/env python3
"""Install the canonical DevCoveer production worker with real Codex imagegen."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

HOME = Path("/home/dev")
UNIT_NAME = "vibepublish-worker.service"
UNIT_SOURCE = Path(__file__).with_name(UNIT_NAME)
UNIT_TARGET = HOME / ".config/systemd/user" / UNIT_NAME
IMAGEGEN_ROOT = HOME / ".local/state/vibepublish/imagegen"
IMAGEGEN_TASK_ROOT = IMAGEGEN_ROOT.parent / (IMAGEGEN_ROOT.name + "-tasks")
IMAGEGEN_ARG = f"--codex-task-artifacts {IMAGEGEN_ROOT}"


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    st = path.lstat()
    if (
        stat.S_ISLNK(st.st_mode)
        or not stat.S_ISDIR(st.st_mode)
        or st.st_uid != os.getuid()
        or st.st_mode & 0o077
    ):
        raise SystemExit(f"unsafe private directory: {path}")


def _validate_unit(data: bytes) -> None:
    text = data.decode("utf-8")
    if text.count(IMAGEGEN_ARG) != 1:
        raise SystemExit("canonical worker unit must contain exactly one imagegen artifact argument")
    required = (
        "--db /home/dev/.local/state/vibepublish/vibepublish.sqlite3",
        "--telegram-env-file /home/dev/.env",
        "--telegram-session-key TELEGRAM_VIBE_PUBLISH",
        "--telegram-api-id-key TELEGRAM_API_ID",
        "--telegram-api-hash-key TELEGRAM_API_HASH",
        "--providers telegram vk",
        "--vk-env-file /home/dev/.env",
        "--vk-token-key VK_USER_TOKEN1",
    )
    if any(item not in text for item in required):
        raise SystemExit("canonical worker unit lost the approved production provider mapping")
    if "OPENAI_API_KEY" in text or "CODEX_API_KEY" in text:
        raise SystemExit("API-key imagegen fallback is forbidden")


def _systemd_env() -> dict[str, str]:
    runtime = f"/run/user/{os.getuid()}"
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(HOME),
        "LANG": "C.UTF-8",
        "XDG_RUNTIME_DIR": runtime,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
    }


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/systemctl", "--user", *args],
        check=True,
        text=True,
        capture_output=True,
        env=_systemd_env(),
    )


def _atomic_install(data: bytes) -> None:
    UNIT_TARGET.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    temporary = UNIT_TARGET.with_name("." + UNIT_TARGET.name + ".tmp")
    temporary.unlink(missing_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o644)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, UNIT_TARGET)
        directory_fd = os.open(UNIT_TARGET.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def install() -> dict[str, object]:
    if Path.home().resolve() != HOME:
        raise SystemExit("installer must run as the DevCoveer service user")
    data = UNIT_SOURCE.read_bytes()
    _validate_unit(data)
    _private_dir(IMAGEGEN_ROOT)
    _private_dir(IMAGEGEN_TASK_ROOT)
    _atomic_install(data)
    _systemctl("daemon-reload")
    _systemctl("restart", UNIT_NAME)
    state = _systemctl(
        "show", UNIT_NAME, "--no-pager",
        "--property=ActiveState,SubState,ExecStart",
    ).stdout
    if "ActiveState=active" not in state or "SubState=running" not in state:
        raise SystemExit("production worker did not become active/running")
    if IMAGEGEN_ARG not in state:
        raise SystemExit("live worker ExecStart does not contain the imagegen artifact root")
    return {
        "unit": UNIT_NAME,
        "unit_sha256": hashlib.sha256(data).hexdigest(),
        "imagegen_root": str(IMAGEGEN_ROOT),
        "imagegen_task_root": str(IMAGEGEN_TASK_ROOT),
        "imagegen_root_mode": oct(IMAGEGEN_ROOT.stat().st_mode & 0o777),
        "imagegen_task_root_mode": oct(IMAGEGEN_TASK_ROOT.stat().st_mode & 0o777),
        "active": True,
        "imagegen_wired": True,
    }


if __name__ == "__main__":
    print(json.dumps(install(), sort_keys=True))
