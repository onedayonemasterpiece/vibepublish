"""Mandatory real-SDK checks. Missing Telethon fails collection, never skips."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
import telethon
from telethon import functions

from scripts.verify.telegram_wire import deny_network, roundtrip, verify


def test_eight_byte_config_request_is_valid_native_tl():
    request = functions.help.GetAppConfigRequest(hash=0)
    assert len(bytes(request)) == 8
    assert roundtrip(request).hash == 0


def test_all_actual_adapter_requests_and_custom_entities_roundtrip():
    result = verify(core=True)
    assert len(result['requests']) == 14
    assert result['evidence'] == 'real_sdk_and_core_compiler'
    assert result['live_provider_verified'] is False


def test_wrong_sdk_version_is_a_failure(monkeypatch):
    monkeypatch.setattr(telethon, '__version__', '1.43.0')
    with pytest.raises(RuntimeError, match='Expected Telethon'):
        verify(core=True)


@pytest.mark.parametrize('event', ['socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.sendto'])
def test_wire_gate_forbids_network(event):
    with pytest.raises(RuntimeError, match='network_forbidden'):
        deny_network(event, ())


def test_original_sdk_entrypoint_now_checks_full_core():
    script = Path(__file__).parents[2]/'scripts/verify/telegram_sdk.py'
    result = subprocess.run([sys.executable, str(script)], check=True, capture_output=True, text=True, timeout=20)
    receipt = json.loads(result.stdout)
    assert len(receipt['requests']) == 14
    assert receipt['native_entities'] == 3
    assert receipt['network_calls'] == 0
