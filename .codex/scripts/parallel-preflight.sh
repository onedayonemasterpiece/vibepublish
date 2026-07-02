#!/usr/bin/env bash
set -euo pipefail

echo "== Repo =="
git rev-parse --show-toplevel

echo
echo "== Branch =="
git status --short --branch

echo
echo "== HEAD =="
git rev-parse HEAD

echo
echo "== Worktrees =="
git worktree list

echo
echo "== Remotes =="
git remote -v || true

echo
echo "== Dirty files =="
git status --porcelain=v1
