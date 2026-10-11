"""P25/P26: real isolated files; injected failures retain durable originals."""
import json
import multiprocessing
import shutil
from pathlib import Path

import pytest

from memory_core import MemoryStore
from trajecta_identity import cli, recipe

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "spec/golden/identity-open/store.sqlite3"


def inventory(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None
            for p in root.rglob("*")}


@pytest.fixture
def installed(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAJECTA_IDENTITY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TRAJECTA_IDENTITY_PROFILES", str(tmp_path / "data/profiles"))
    data = json.loads((ROOT / "trajecta_identity/profiles/example/profile.json").read_bytes())
    incoming = tmp_path / "incoming.json"
    incoming.write_text(json.dumps(data), encoding="utf8")
    recipe.resolve(str(incoming), remember_choice=False)
    target = tmp_path / "data/profiles/example/profile.json"
    return data, incoming, target


def test_conflict_is_typed_exit_one_and_writes_nothing(installed, tmp_path, capsys):
    data, incoming, _ = installed
    data["core"]["summary"] = "new summary"
    incoming.write_text(json.dumps(data), encoding="utf8")
    before = inventory(tmp_path)
    with pytest.raises(SystemExit) as caught:
        cli.main(["-p", str(incoming), "status"])
    assert caught.value.code == 1
    assert capsys.readouterr().err == (
        "ProfileConflict: profile 'example' differs from the installed copy; "
        "pass --replace-profile to overwrite\n")
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("extra", [None, float("nan"), float("inf"), -float("inf")])
def test_identical_writer_bytes_preserve_mtime_inventory(installed, tmp_path, replace, extra):
    data, incoming, target = installed
    data["extra"] = extra
    raw = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf8")
    target.write_bytes(raw)
    incoming.write_text(json.dumps(data), encoding="utf8")
    before, mtime = inventory(tmp_path), target.stat().st_mtime_ns
    recipe.resolve(str(incoming), remember_choice=False, replace_profile=replace)
    assert inventory(tmp_path) == before
    assert target.stat().st_mtime_ns == mtime


@pytest.mark.parametrize("difference", ["spacing", "key-order", "invalid-installed"])
def test_comparison_never_parses_installed_and_refuses_byte_differences(installed, tmp_path, difference):
    data, incoming, target = installed
    if difference == "spacing":
        target.write_bytes(target.read_bytes() + b" ")
    elif difference == "key-order":
        target.write_bytes((json.dumps(dict(reversed(list(data.items()))), ensure_ascii=False, indent=2) + "\n").encode())
    else:
        target.write_bytes(b"{broken")
    before = inventory(tmp_path)
    with pytest.raises(ValueError, match="differs from the installed copy") as caught:
        recipe.resolve(str(incoming), remember_choice=False)
    assert type(caught.value).__name__ == "ProfileConflict"
    assert inventory(tmp_path) == before


def test_replace_keeps_original_backup_and_commits_new(installed, tmp_path):
    data, incoming, target = installed
    old = target.read_bytes()
    data["core"]["summary"] = "replacement"
    incoming.write_text(json.dumps(data), encoding="utf8")
    recipe.resolve(str(incoming), remember_choice=False, replace_profile=True)
    backups = list(target.parent.glob("profile.json.*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == old
    assert json.loads(target.read_bytes()) == data
    assert __import__("re").fullmatch(r"profile\.json\.\d{8}T\d{12}Z\.bak", backups[0].name)
    assert not list(target.parent.glob(".profile-*"))


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_replace_failure_preserves_original_keeps_reports_backup(installed, monkeypatch, tmp_path, capsys, failure):
    data, incoming, target = installed
    old = target.read_bytes()
    data["core"]["summary"] = "replacement"
    incoming.write_text(json.dumps(data), encoding="utf8")
    error = OSError("injected failure")
    if failure == "replace":
        def fail(*args): raise error
        monkeypatch.setattr(recipe.os, "replace", fail)
    else:
        real = recipe.os.fdopen
        class Failing:
            def __init__(self, *a, **k): self.stream = real(*a, **k)
            def __enter__(self): return self
            def write(self, text): self.stream.write(text[:10]); raise error
            def __exit__(self, *a): self.stream.close()
        monkeypatch.setattr(recipe.os, "fdopen", Failing)
    with pytest.raises(OSError) as caught:
        recipe.resolve(str(incoming), remember_choice=False, replace_profile=True)
    assert caught.value is error
    backups = list(target.parent.glob("profile.json.*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == old
    assert str(backups[0]) in capsys.readouterr().err
    assert target.read_bytes() == old
    assert not list(target.parent.glob(".profile-*"))


def test_invalid_incoming_refused_before_conflict_and_backup(installed, tmp_path):
    _, incoming, _ = installed
    incoming.write_bytes(b"{broken")
    before = inventory(tmp_path)
    with pytest.raises(json.JSONDecodeError):
        recipe.resolve(str(incoming), remember_choice=False, replace_profile=True)
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("failure", [False, True])
def test_dry_run_removes_missing_parent_chain_on_every_exit(tmp_path, monkeypatch, failure):
    source = tmp_path / "source.sqlite3"
    shutil.copyfile(LEGACY, source)
    target = tmp_path / "new/deep/target.sqlite3"
    before = inventory(tmp_path)
    if failure:
        def fail(*a, **k): raise OSError("copy failed")
        monkeypatch.setattr(shutil, "copy2", fail)
        with pytest.raises(OSError, match="copy failed"):
            MemoryStore(source).migrate_to(target, dry_run=True)
    else:
        assert MemoryStore(source).migrate_to(target, dry_run=True)["state"] == "ready"
    assert inventory(tmp_path) == before


def create_parent(path):
    Path(path).mkdir()


def test_dry_run_keeps_parent_created_by_another_process(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    shutil.copyfile(LEGACY, source)
    target = tmp_path / "external/owned/deep/target.sqlite3"
    real = Path.mkdir
    triggered = False
    def race(path, *a, **k):
        nonlocal triggered
        if path == target.parent.parent.parent and not triggered:
            triggered = True
            process = multiprocessing.get_context("spawn").Process(target=create_parent, args=(str(path),))
            process.start(); process.join(10)
            assert process.exitcode == 0
        return real(path, *a, **k)
    monkeypatch.setattr(Path, "mkdir", race)
    before = inventory(tmp_path)
    MemoryStore(source).migrate_to(target, dry_run=True)
    assert triggered
    assert inventory(tmp_path) == {**before, "external": None}


def test_backup_name_collision_never_overwrites(installed, monkeypatch):
    from datetime import datetime, timezone
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None): return cls(2026, 10, 11, 1, 2, 3, 456789, tzinfo=timezone.utc)
    monkeypatch.setattr(recipe, "datetime", Fixed)
    data, incoming, target = installed
    base = target.with_name("profile.json.20261011T010203456789Z.bak")
    base.write_bytes(b"collision zero")
    base.with_name(base.name + ".1").write_bytes(b"collision one")
    old = target.read_bytes()
    data["core"]["summary"] = "replacement"
    incoming.write_text(json.dumps(data), encoding="utf8")
    recipe.resolve(str(incoming), remember_choice=False, replace_profile=True)
    assert base.read_bytes() == b"collision zero"
    assert base.with_name(base.name + ".1").read_bytes() == b"collision one"
    assert base.with_name(base.name + ".2").read_bytes() == old


def test_backup_write_failure_is_reported_and_preserves_installed(installed, monkeypatch, capsys):
    data, incoming, target = installed
    old = target.read_bytes()
    data["core"]["summary"] = "replacement"
    incoming.write_text(json.dumps(data), encoding="utf8")
    real = Path.open
    error = OSError("backup failed")
    class Partial:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def write(self, raw): self.stream.write(raw[:7]); raise error
        def __exit__(self, *a): self.stream.close()
    def failing(path, *a, **k):
        stream = real(path, *a, **k)
        return Partial(stream) if a and a[0] == "xb" else stream
    monkeypatch.setattr(Path, "open", failing)
    with pytest.raises(OSError) as caught:
        recipe.resolve(str(incoming), remember_choice=False, replace_profile=True)
    assert caught.value is error
    backup, = target.parent.glob("profile.json.*.bak")
    assert str(backup) in capsys.readouterr().err
    assert target.read_bytes() == old
    assert backup.read_bytes() == old[:7]


def test_number_kind_is_not_erased_by_canonical_comparison(installed):
    data, incoming, target = installed
    data["number"] = 1
    target.write_text(json.dumps(data), encoding="utf8")
    data["number"] = 1.0
    incoming.write_text(json.dumps(data), encoding="utf8")
    with pytest.raises(ValueError, match="differs from the installed copy"):
        recipe.resolve(str(incoming), remember_choice=False)


@pytest.mark.skipif(__import__('os').name == 'nt', reason='POSIX permission bits; Windows has no equivalent chmod mode law')
@pytest.mark.parametrize('mode', [0o644, 0o640])
def test_replace_preserves_installed_posix_mode(installed, mode):
    import stat
    data, incoming, target = installed
    target.chmod(mode)
    data['core']['summary'] = 'replacement'
    incoming.write_text(json.dumps(data), encoding='utf8')
    recipe.resolve(str(incoming), remember_choice=False, replace_profile=True)
    assert stat.S_IMODE(target.stat().st_mode) == mode


def test_dry_run_unreachable_root_reraises_original_enoent(tmp_path, monkeypatch):
    import errno
    source = tmp_path / 'source.sqlite3'
    shutil.copyfile(LEGACY, source)
    before = inventory(tmp_path)
    error = FileNotFoundError(errno.ENOENT, 'synthetic unreachable root')
    def fail(*a, **k): raise error
    monkeypatch.setattr(Path, 'mkdir', fail)
    with pytest.raises(FileNotFoundError) as caught:
        MemoryStore(source).migrate_to(tmp_path / 'missing/target.sqlite3', dry_run=True)
    assert caught.value is error
    assert inventory(tmp_path) == before
