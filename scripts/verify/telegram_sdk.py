"""Require the real pinned SDK AND the VibePublish compiler, without network.

Kept as the existing CI entry point. An empty GetAppConfigRequest is correctly
8 bytes: success means TL roundtrip and semantic equality, not arbitrary size.
"""
import json
from pathlib import Path
import sys

# Verify the checkout/release containing this script, not an older installed
# VibePublish package that happens to share the production interpreter.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram_wire import deny_network, verify


def main():
    sys.addaudithook(deny_network)
    print(json.dumps(verify(core=True), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
