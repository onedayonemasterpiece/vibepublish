from pathlib import Path
import importlib.util
import hashlib
import pytest

spec = importlib.util.spec_from_file_location('dependency_gate', Path(__file__).parents[2]/'scripts/verify/dependencies.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.mark.parametrize('text', ['', 'one>=1', 'one==1.*', 'one==1\none==1', 'one[extra]==1', 'one==1; python_version>"3"', 'one @ https://example.invalid/a.whl'])
def test_rejects_non_exact_graph(tmp_path, text):
    path = tmp_path/'lock'; path.write_text(text)
    with pytest.raises(ValueError): gate.pins(path)


def test_wheelhouse_requires_complete_exact_unique_set(tmp_path):
    lock = tmp_path/'lock'; lock.write_text('some-package==1.2.0\n')
    with pytest.raises(ValueError, match='Missing'): gate.wheel_lock(lock, tmp_path)
    wheel = tmp_path/'some_package-1.2.0-py3-none-any.whl'; wheel.write_bytes(b'unit fixture not an installed wheel')
    expected = hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert f'some-package==1.2.0 --hash=sha256:{expected}' in gate.wheel_lock(lock, tmp_path)
    other = tmp_path/'other-1.0-py3-none-any.whl'; other.write_bytes(b'other')
    with pytest.raises(ValueError, match='Unexpected'): gate.wheel_lock(lock, tmp_path)


def test_rejects_symlink(tmp_path):
    lock = tmp_path/'lock'; lock.write_text('one==1.0\n')
    (tmp_path/'source').write_text('x'); (tmp_path/'one-1.0-py3-none-any.whl').symlink_to('source')
    with pytest.raises(ValueError, match='regular'): gate.wheel_lock(lock, tmp_path)


def test_check_reports_missing_wrong_and_unexpected(tmp_path, monkeypatch):
    lock = tmp_path/'lock'; lock.write_text('one==1.0\n')
    class Dist:
        def __init__(self,name,version): self.metadata={'Name':name}; self.version=version
    monkeypatch.setattr(gate.metadata, 'distributions', lambda: [Dist('pip','25'), Dist('one','1.0')])
    assert gate.check(lock)['packages'] == 1
    monkeypatch.setattr(gate.metadata, 'distributions', lambda: [Dist('other','1.0')])
    with pytest.raises(ValueError, match='version_mismatches'): gate.check(lock)


@pytest.mark.parametrize('included', ['one==1.1', 'one>=1', 'two==1.0', '-r requirements.in'])
def test_input_drift_and_cycles_rejected(tmp_path, included):
    lock = tmp_path/'lock'; lock.write_text('one==1.0\n')
    inputs = tmp_path/'requirements.in'; inputs.write_text(included)
    with pytest.raises(ValueError): gate.check_inputs(lock, inputs)


def test_direct_extra_includes_and_same_pin_duplicates(tmp_path):
    lock = tmp_path/'lock'; lock.write_text('one==1.0\nother==2.0\n')
    (tmp_path/'base.in').write_text('one[extra]==1.0\n')
    inputs = tmp_path/'requirements.in'; inputs.write_text('-r base.in\none==1.0\n')
    assert gate.check_inputs(lock, inputs)['direct_pins'] == {'one': '1.0'}


def test_include_cannot_escape_source_directory(tmp_path):
    (tmp_path/'other.in').write_text('one==1.0')
    sub = tmp_path/'source'; sub.mkdir()
    lock=sub/'lock'; lock.write_text('one==1.0\n')
    inputs=sub/'requirements.in'; inputs.write_text('-r ../other.in')
    with pytest.raises(ValueError, match='include'): gate.check_inputs(lock,inputs)
