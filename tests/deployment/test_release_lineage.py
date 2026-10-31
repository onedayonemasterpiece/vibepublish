"""INC-2026-10-18: a deploy from main must not silently drop code the server runs."""
import importlib.util
import subprocess
from pathlib import Path

GUARD = Path(__file__).resolve().parents[2] / 'deploy' / 'devcoveer' / 'check_release_lineage.py'


def load():
    spec = importlib.util.spec_from_file_location('check_release_lineage', GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def commit(repo, name):
    (repo / name).write_text(name)
    subprocess.run(['git', '-C', str(repo), 'add', name], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', name], check=True)
    return subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()


def repo_with_branch_release(tmp_path):
    origin, work = tmp_path / 'origin', tmp_path / 'work'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(origin)], check=True)
    subprocess.run(['git', 'clone', '-q', str(origin), str(work)], check=True)
    subprocess.run(['git', '-C', str(work), 'checkout', '-qb', 'main'], check=True)
    base = commit(work, 'base')
    subprocess.run(['git', '-C', str(work), 'push', '-q', 'origin', 'main'], check=True)
    subprocess.run(['git', '-C', str(work), 'checkout', '-qb', 'feature'], check=True)
    feature = commit(work, 'feature')  # deployed but never merged
    subprocess.run(['git', '-C', str(work), 'checkout', '-q', 'main'], check=True)
    later = commit(work, 'later')
    subprocess.run(['git', '-C', str(work), 'push', '-q', 'origin', 'main'], check=True)
    return work, base, feature, later


def run(guard, monkeypatch, work, candidate, running):
    monkeypatch.setattr(guard, 'running_releases', lambda: running)
    monkeypatch.setattr('sys.argv', ['guard', '--candidate', candidate, '--repo', str(work)])
    return guard.main()


def test_main_deploy_over_an_unmerged_branch_release_is_refused(tmp_path, monkeypatch, capsys):
    guard = load()
    work, _, feature, later = repo_with_branch_release(tmp_path)
    assert run(guard, monkeypatch, work, later, {'vibepublish.service': feature}) == 2
    assert 'would drop' in capsys.readouterr().err


def test_a_branch_candidate_is_refused_and_a_main_superset_is_accepted(tmp_path, monkeypatch):
    guard = load()
    work, base, feature, later = repo_with_branch_release(tmp_path)
    assert run(guard, monkeypatch, work, feature, {'vibepublish.service': base}) == 2
    subprocess.run(['git', '-C', str(work), '-c', 'user.name=t', '-c', 'user.email=t@t', 'merge', '-q', '--no-edit', feature], check=True)
    subprocess.run(['git', '-C', str(work), 'push', '-q', 'origin', 'main'], check=True)
    merged = subprocess.run(['git', '-C', str(work), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    assert run(guard, monkeypatch, work, merged, {'vibepublish.service': feature, 'vibepublish-worker.service': later}) == 0


def test_no_running_releases_is_refused(tmp_path, monkeypatch, capsys):
    guard = load()
    work, _, _, later = repo_with_branch_release(tmp_path)
    assert run(guard, monkeypatch, work, later, {}) == 2
    assert 'no running VibePublish release found' in capsys.readouterr().err
