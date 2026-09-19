from pathlib import Path
import importlib.util

import pytest


spec = importlib.util.spec_from_file_location(
    'telegram_login', Path(__file__).resolve().parents[2] / 'deploy/devcoveer/telegram_login.py')
login = importlib.util.module_from_spec(spec)
spec.loader.exec_module(login)


def test_private_output_does_not_replace_existing_credentials(tmp_path):
    target = tmp_path / 'credentials.env'
    login.private_write(target, b'original', exclusive=True)
    with pytest.raises(FileExistsError):
        login.private_write(target, b'replacement', exclusive=True)
    assert target.read_bytes() == b'original'
    assert target.stat().st_mode & 0o777 == 0o600


def test_qr_refresh_rejects_symlink(tmp_path):
    target = tmp_path / 'existing'
    target.write_bytes(b'preserve')
    link = tmp_path / 'qr.png'
    link.symlink_to(target)
    with pytest.raises(OSError):
        login.private_write(link, b'new')
    assert target.read_bytes() == b'preserve'
