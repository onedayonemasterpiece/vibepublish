#!/usr/bin/env bash
set -euo pipefail

git worktree list --porcelain | awk '
  /^worktree / { wt=$2; print wt }
' | while read -r wt; do
  echo "== $wt =="
  git -C "$wt" status --short --branch || true
  echo
done
