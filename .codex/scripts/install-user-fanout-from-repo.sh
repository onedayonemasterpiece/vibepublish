#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$HOME/.codex/backups/feature-fanout-from-repo-$ts"
mkdir -p "$backup_dir" "$HOME/.codex" "$HOME/.codex/agents" "$HOME/.codex/scripts" "$HOME/.codex/rules" "$HOME/.agents/skills"

backup_file() {
  local f="$1"
  if [ -e "$f" ]; then
    local rel="${f#$HOME/}"
    mkdir -p "$backup_dir/$(dirname "$rel")"
    cp -a "$f" "$backup_dir/$rel"
  fi
}

for f in \
  "$HOME/.codex/AGENTS.md" \
  "$HOME/.codex/AGENTS.override.md" \
  "$HOME/.codex/config.toml" \
  "$HOME/.agents/skills/feature-fanout/SKILL.md"; do
  backup_file "$f"
done
for d in "$HOME/.codex/agents" "$HOME/.codex/scripts" "$HOME/.codex/rules"; do
  if [ -d "$d" ]; then
    rel="${d#$HOME/}"
    mkdir -p "$backup_dir/$(dirname "$rel")"
    cp -a "$d" "$backup_dir/$rel"
  fi
done

mkdir -p "$HOME/.agents/skills/feature-fanout" "$HOME/.codex/agents" "$HOME/.codex/scripts" "$HOME/.codex/rules"
cp -a "$repo_root/.agents/skills/feature-fanout/SKILL.md" "$HOME/.agents/skills/feature-fanout/SKILL.md"
cp -a "$repo_root/.codex/agents/." "$HOME/.codex/agents/"
cp -a "$repo_root/.codex/scripts/parallel-preflight.sh" "$HOME/.codex/scripts/parallel-preflight.sh"
cp -a "$repo_root/.codex/scripts/worktree-audit.sh" "$HOME/.codex/scripts/worktree-audit.sh"
cp -a "$repo_root/.codex/rules/parallel-workflow-safety.rules" "$HOME/.codex/rules/parallel-workflow-safety.rules"
chmod +x "$HOME/.codex/scripts/parallel-preflight.sh" "$HOME/.codex/scripts/worktree-audit.sh"

if [ -s "$HOME/.codex/AGENTS.override.md" ]; then
  active="$HOME/.codex/AGENTS.override.md"
else
  active="$HOME/.codex/AGENTS.md"
fi

python3 - "$repo_root" "$active" <<'PY_INSTALL'
from pathlib import Path
import re, sys, tomllib
repo = Path(sys.argv[1])
active = Path(sys.argv[2])
agents = repo/'AGENTS.md'
text = agents.read_text() if agents.exists() else ''
match = re.search(r'<!-- codex-feature-fanout:start -->.*?<!-- codex-feature-fanout:end -->', text, re.S)
if not match:
    raise SystemExit('repo AGENTS.md lacks codex-feature-fanout managed block')
block = match.group(0) + '\n'
current = active.read_text() if active.exists() else ''
pat = re.compile(r'<!-- codex-feature-fanout:start -->.*?<!-- codex-feature-fanout:end -->\n?', re.S)
current = pat.sub(block, current) if pat.search(current) else current.rstrip() + ('\n\n' if current.strip() else '') + block
active.parent.mkdir(parents=True, exist_ok=True)
active.write_text(current)

cfg = Path.home()/'.codex/config.toml'
text = cfg.read_text() if cfg.exists() else ''
tomllib.loads(text or '')
if re.search(r'(?m)^\[agents\]\s*$', text):
    lines=text.splitlines(); out=[]; in_agents=False; has_threads=False; has_depth=False; inserted=False
    for line in lines:
        if re.match(r'^\[.*\]\s*$', line):
            if in_agents and not inserted:
                if not has_threads: out.append('max_threads = 6')
                if not has_depth: out.append('max_depth = 1')
                inserted=True
            in_agents=(line.strip()=='[agents]')
        if in_agents:
            if re.match(r'^\s*max_threads\s*=', line): has_threads=True
            if re.match(r'^\s*max_depth\s*=', line): has_depth=True
        out.append(line)
    if in_agents and not inserted:
        if not has_threads: out.append('max_threads = 6')
        if not has_depth: out.append('max_depth = 1')
    text='\n'.join(out)+'\n'
else:
    text=text.rstrip()+('\n\n' if text.strip() else '')+'[agents]\nmax_threads = 6\nmax_depth = 1\n'
tomllib.loads(text)
cfg.write_text(text)
PY_INSTALL

echo "Installed feature-fanout user-global defaults from $repo_root"
echo "Backups: $backup_dir"
