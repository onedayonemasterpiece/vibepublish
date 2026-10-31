"""One-time SQLite asset reclamation; default mode is strictly read-only.

Use --apply only during an explicitly approved, coordinated release maintenance.
The worker uses the same retention query for its ordinary periodic cleanup.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from social_operations.assets import retired_asset_rows, reclaim_asset_bytes, stale_unsent_attempts


def summarize(db, now):
    rows = retired_asset_rows(db, now)
    buckets = defaultdict(lambda: {"rows": 0, "bytes": 0})
    for row in rows:
        bucket = buckets[row["reason"]]
        bucket["rows"] += 1
        bucket["bytes"] += row["size_bytes"]
    stale = stale_unsent_attempts(db, now)
    reclaim = {row['id'] for row in rows if row['reason'] == 'reclaim'}
    candidates = [row['id'] for row in db.execute(
        'SELECT id,asset_ref,art_ref FROM visual_candidates')
        if row['asset_ref'] in reclaim and row['art_ref'] in reclaim]
    origins = sum(row['asset_id'] in reclaim for row in db.execute(
        'SELECT asset_id FROM visual_asset_origins'))
    feedback = sum(row['candidate_id'] in candidates for row in db.execute(
        'SELECT candidate_id FROM visual_feedback'))
    unknown = []
    for row in db.execute(
        """SELECT o.id,a.provider,o.created,o.worker_seen
           FROM attempts a JOIN operations o ON o.id=a.operation_id
           WHERE a.state='outcome_unknown'"""):
        age = (now - max(row['created'], row['worker_seen'] or row['created'])) / 86400
        if age >= 3:
            unknown.append({'operation_id': row['id'], 'provider': row['provider'],
                            'age_days': round(age, 2)})
    return rows, {
        "total": {"rows": len(rows), "bytes": sum(row["size_bytes"] for row in rows)},
        "by_reason": dict(sorted(buckets.items())),
        "remaining": {
            "rows": sum(bucket["rows"] for key, bucket in buckets.items() if key != "reclaim"),
            "bytes": sum(bucket["bytes"] for key, bucket in buckets.items() if key != "reclaim"),
        },
        "would_close_operations": len({row["operation_id"] for row in stale}),
        "would_close_attempts": [{**row, "age_days": round(row["age_days"], 2)} for row in stale],
        "old_unknown_effects_releasing_bytes": unknown,
        "expired_visual_metadata": {
            "candidates": len(candidates), "origins": origins, "feedback": feedback,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="Delete eligible assets and VACUUM; never use before release approval")
    args = parser.parse_args()
    path = args.db.resolve()
    db = (sqlite3.connect(str(path)) if args.apply else
          sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        now = time.time()
        if args.apply:
            from social_operations.storage import Store
            from social_operations.worker import Worker
            worker = Worker(Store(path, clock=lambda: now))
            db.execute("BEGIN IMMEDIATE")
        else:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")  # One read snapshot across operations and asset references.
        before_bytes = path.stat().st_size
        rows, report = summarize(db, now)
        report["mode"] = "apply" if args.apply else "dry_run"
        report["sqlite_file_bytes_before"] = before_bytes
        if args.apply:
            worker.expire_stale_unsent(db, now)
            reclaim_asset_bytes(db, rows)
            db.commit()
            db.execute("VACUUM")
            report["sqlite_file_bytes_after"] = path.stat().st_size
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
