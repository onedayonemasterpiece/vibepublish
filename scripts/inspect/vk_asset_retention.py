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
from social_operations.assets import retired_asset_rows


def summarize(db, now):
    rows = retired_asset_rows(db, now)
    buckets = defaultdict(lambda: {"rows": 0, "bytes": 0})
    for row in rows:
        bucket = buckets[row["reason"]]
        bucket["rows"] += 1
        bucket["bytes"] += row["size_bytes"]
    pending = db.execute(
        """SELECT o.id AS operation_id, t.alias AS destination, t.state,
                  o.work_state, json_extract(t.plan,'$.scheduled_at') AS scheduled_at,
                  COUNT(DISTINCT json_extract(j.value,'$.ref')) AS assets
           FROM attempts t JOIN operations o ON o.id=t.operation_id
           JOIN json_each(t.plan,'$.assets') j
           WHERE o.work_state!='done' OR o.state='outcome_unknown'
              OR t.state='outcome_unknown'
           GROUP BY o.id, t.id ORDER BY o.created DESC LIMIT 100"""
    ).fetchall()
    return rows, {
        "total": {"rows": len(rows), "bytes": sum(row["size_bytes"] for row in rows)},
        "by_reason": dict(sorted(buckets.items())),
        "remaining": {
            "rows": sum(bucket["rows"] for key, bucket in buckets.items() if key != "reclaim"),
            "bytes": sum(bucket["bytes"] for key, bucket in buckets.items() if key != "reclaim"),
        },
        "operations_requiring_bytes": [dict(row) for row in pending],
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
    try:
        if not args.apply:
            db.execute("PRAGMA query_only=ON")
        before_bytes = path.stat().st_size
        now = time.time()
        if args.apply:
            db.execute("BEGIN IMMEDIATE")
        rows, report = summarize(db, now)
        report["mode"] = "apply" if args.apply else "dry_run"
        report["sqlite_file_bytes_before"] = before_bytes
        if args.apply:
            db.executemany("DELETE FROM assets WHERE id=?", [
                (row["id"],) for row in rows if row["reason"] == "reclaim"
            ])
            db.commit()
            db.execute("VACUUM")
            report["sqlite_file_bytes_after"] = path.stat().st_size
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
