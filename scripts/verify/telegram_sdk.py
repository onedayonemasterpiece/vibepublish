"""Require the real pinned SDK AND the VibePublish compiler, without network.

Kept as the existing CI entry point. An empty GetAppConfigRequest is correctly
8 bytes: success means TL roundtrip and semantic equality, not arbitrary size.
"""
import json
import sys
from telegram_wire import deny_network, verify


def main():
    sys.addaudithook(deny_network)
    print(json.dumps(verify(core=True), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
