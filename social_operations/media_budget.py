"""Connection-wide durable Telegram media admission.

The caller holds the existing cross-process connection lane. Admission is
persisted before adapter.execute(), therefore before the first Telegram upload.
A failed or interrupted pre-dispatch upload is conservatively counted for the
rolling window; provider dispatch/unknown-outcome semantics remain separate.
"""
from .domain import DomainError, new_id

LIMIT = 20
WINDOW = 60.0
RETENTION = 86400.0
EPSILON = 0.001


class MediaBudgetDeferred(DomainError):
    def __init__(self, until):
        self.until = until
        super().__init__(
            'telegram_media_budget',
            'Telegram media capacity is durably deferred',
            'check_status',
        )


def media_files(plan):
    assets = plan.get('assets', [])
    if plan.get('action') == 'publish':
        return len(assets)
    if plan.get('action') == 'edit':
        existing = plan.get('existing') or {}
        return (
            len(assets)
            if [a['sha256'] for a in assets]
            != list(existing.get('media_hashes', []))
            else 0
        )
    return 0


def reserve(db, plan, attempt_id, now):
    """Reserve this upload batch or raise with the earliest safe retry time."""
    if plan.get('provider') not in (None, 'telegram'):
        return 0
    count = media_files(plan)
    if not count:
        return 0
    if count > LIMIT:
        raise DomainError('telegram_media_budget_operation_too_large')

    connection_id = plan['connection_id']
    db.execute(
        'DELETE FROM telegram_media_admissions WHERE admitted_at<=?',
        (now - RETENTION,),
    )
    rows = list(db.execute(
        'SELECT admitted_at,media_count FROM telegram_media_admissions '
        'WHERE connection_id=? AND admitted_at>? ORDER BY admitted_at,id',
        (connection_id, now - WINDOW),
    ))
    used = sum(row['media_count'] for row in rows)
    if used + count > LIMIT:
        needed = used + count - LIMIT
        released = 0
        for row in rows:
            released += row['media_count']
            if released >= needed:
                raise MediaBudgetDeferred(row['admitted_at'] + WINDOW + EPSILON)
        raise RuntimeError('telegram media budget evidence inconsistent')

    db.execute(
        'INSERT INTO telegram_media_admissions'
        '(id,connection_id,attempt_id,media_count,admitted_at) '
        'VALUES(?,?,?,?,?)',
        (new_id('tgmedia'), connection_id, attempt_id, count, now),
    )
    return count
