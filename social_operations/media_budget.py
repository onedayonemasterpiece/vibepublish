"""Connection-wide Telegram media admission using durable dispatch evidence.

Caller holds the existing cross-process connection lane. No reservations,
secondary scheduler or wall-clock sleeps are needed. Unknown sends count too.
"""
import json
from .domain import DomainError

LIMIT = 20
WINDOW = 60


class MediaBudgetDeferred(DomainError):
    def __init__(self, until):
        self.until = until
        super().__init__('telegram_media_budget', 'Telegram media capacity is durably deferred', 'check_status')


def media_files(plan):
    assets = plan.get('assets', [])
    if plan.get('action') == 'publish':
        return len(assets)
    if plan.get('action') == 'edit':
        existing = plan.get('existing') or {}
        return len(assets) if [a['sha256'] for a in assets] != list(existing.get('media_hashes', [])) else 0
    return 0


def wait_until(db, plan, now):
    if plan.get('provider') not in (None, 'telegram'):
        return None
    count = media_files(plan)
    if not count:
        return None
    if count > LIMIT:
        raise DomainError('telegram_media_budget_operation_too_large')
    rows = db.execute("SELECT plan,dispatch_at FROM attempts WHERE provider='telegram' AND dispatched=1 AND dispatch_at>=? ORDER BY dispatch_at,id", (now-WINDOW,))
    events = [(row['dispatch_at'], media_files(json.loads(row['plan']))) for row in rows
              if json.loads(row['plan'])['connection_id'] == plan['connection_id']]
    used = sum(n for _, n in events)
    if used + count <= LIMIT:
        return None
    for dispatched, n in events:
        used -= n
        if used + count <= LIMIT:
            # Inclusive rolling boundary: release just beyond 60 seconds.
            return dispatched + WINDOW + .001
    raise RuntimeError('media budget evidence inconsistent')
