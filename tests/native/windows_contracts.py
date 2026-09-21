"""Native Windows acceptance; run with --confcutdir=tests/native.

These tests execute real Windows APIs, child interpreters, and filesystem ACLs.
No Windows mocking, POSIX emulation, network services, or production workspace
is involved. The separate test root does not inherit the POSIX process-group
lifecycle harness used by the existing Linux suite.
"""

import functools
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from kanon_cli.core.kanonenv import _check_permissions
from kanon_cli.core.marketplace import create_dirsymlink
from kanon_cli.utils.spawn import _spawn_detached_windows
from worker_callbacks import fail, output

TIMEOUT = float(os.environ.get("KANON_TEST_SUBPROCESS_TIMEOUT", "30"))


def wait_worker(child):
    """Bound native workers and remove their process trees on a failed wait."""
    try:
        return child.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["taskkill.exe", "/PID", str(child.pid), "/T", "/F"], check=True, capture_output=True, timeout=TIMEOUT
        )
        child.wait(timeout=TIMEOUT)
        raise


@pytest.fixture(autouse=True)
def native_environment(monkeypatch):
    assert sys.platform == "win32", "This acceptance suite must execute on native Windows"
    paths = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2] / "src")]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(paths))
    monkeypatch.setenv("KANON_TELEMETRY_DISABLED", "1")


def test_parent_exits_before_worker_release(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(TIMEOUT)
        code = (
            "from functools import partial; from pathlib import Path; "
            "from worker_callbacks import wait_for_release; "
            "from kanon_cli.utils.spawn import spawn_detached; "
            f"spawn_detached(partial(wait_for_release, {listener.getsockname()[1]}, {TIMEOUT}), "
            f"log_path=Path({str(tmp_path / 'worker.log')!r}))"
        )
        parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            channel, _ = listener.accept()
            with channel:
                channel.settimeout(TIMEOUT)
                assert channel.recv(5) == b"ready"
                stdout, stderr = parent.communicate(timeout=TIMEOUT)
                assert parent.returncode == 0, stderr
                assert stdout == b""
                channel.sendall(b"!")
                assert channel.recv(4) == b"done"
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.wait(timeout=TIMEOUT)


@pytest.mark.parametrize("callback, expected", [(output, 0), (fail, 1)])
def test_worker_logs_and_exit_status(tmp_path, callback, expected):
    log = tmp_path / "new" / "nested" / "worker.log"
    child = _spawn_detached_windows(callback, log_path=log)
    assert wait_worker(child) == expected
    text = log.read_text(encoding="utf-8")
    assert "hidden" not in text
    assert ("visible-stderr-café" if expected == 0 else "native-worker-controlled-failure") in text


def test_real_nested_update_callback(tmp_path):
    from kanon_cli.completions.cache import _run_refresh_with_logging
    from worker_callbacks import marker

    destination = tmp_path / "marker"
    child = _spawn_detached_windows(
        functools.partial(_run_refresh_with_logging, functools.partial(marker, destination), "native"),
        log_path=tmp_path / "nested" / "completion-errors.log",
    )
    assert wait_worker(child) == 0
    assert destination.read_text(encoding="utf-8") == "completed"


def test_directory_symlink(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "content").write_text("native", encoding="utf-8")
    link = tmp_path / "link"
    create_dirsymlink(link, target)
    assert link.is_symlink()
    assert (link / "content").read_text(encoding="utf-8") == "native"


def test_windows_acl_rejects_untrusted_writer(tmp_path):
    path = tmp_path / ".kanon"
    path.write_text("", encoding="utf-8")
    _check_permissions(path)
    result = subprocess.run(["icacls.exe", str(path), "/grant", "*S-1-1-0:(W)"], capture_output=True, timeout=TIMEOUT)
    assert result.returncode == 0, result.stderr
    with pytest.raises(ValueError, match="Windows write access"):
        _check_permissions(path)


@pytest.fixture
def native_store():
    """Keep the shared store short enough for Git for Windows' GIT_DIR limit."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="kn-", dir=os.environ.get("KANON_NATIVE_STORE_ROOT")) as directory:
        yield Path(directory)


def test_cli_local_catalog_lifecycle(tmp_path, monkeypatch, native_store):
    """Run add/install/reinstall/list/doctor/remove against local Git fixtures."""
    catalog_xml = (
        "<manifest><catalog-metadata><name>widget</name><display-name>Native widget</display-name>"
        "<description>Native Windows fixture</description><version>1.0.0</version><type>plugin</type>"
        "<owner-name>Native test</owner-name><owner-email>native@kanon.example</owner-email>"
        "<keywords>native</keywords></catalog-metadata></manifest>"
    )

    monkeypatch.setenv("KANON_HOME", str(native_store))
    monkeypatch.setenv("KANON_SKIP_UPDATE_CHECK", "1")
    monkeypatch.setenv("KANON_ALLOW_INSECURE_REMOTES", "1")
    monkeypatch.setenv("KANON_PERMITTED_ABS_ROOTS", str(tmp_path))
    monkeypatch.setenv("KANON_SYNC_JOBS", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "core.longpaths")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "true")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    catalog = tmp_path / "catalog"
    catalog.mkdir()

    def git(*args, cwd=catalog):
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
        assert result.returncode == 0, result.stderr
        return result.stdout

    git("init", "-b", "main")
    git("config", "user.name", "Native test")
    git("config", "user.email", "native@kanon.example")
    content = tmp_path / "content"
    content.mkdir()
    git("init", "-b", "main", cwd=content)
    git("config", "user.name", "Native test", cwd=content)
    git("config", "user.email", "native@kanon.example", cwd=content)
    (content / "file.txt").write_text("native synced content", encoding="utf-8")
    git("add", ".", cwd=content)
    git("commit", "-m", "content fixture", cwd=content)
    catalog_xml = catalog_xml.replace(
        "</manifest>",
        f'<remote name="local" fetch="{tmp_path.as_uri()}/"/>'
        '<default remote="local" revision="refs/heads/main"/>'
        '<project name="content" path=".packages/content"/></manifest>',
    )
    specs = catalog / "repo-specs"
    specs.mkdir()
    (specs / "widget-marketplace.xml").write_text(catalog_xml, encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "fixture")
    git("tag", "widget/1.0.0")
    from kanon_cli.completions.project_versions import _fetch_and_cache_versions
    from kanon_cli.completions.cache import _run_refresh_with_logging

    from kanon_cli.completions.cache import project_entry_dir

    cache = project_entry_dir(catalog.as_uri())
    child = _spawn_detached_windows(
        functools.partial(
            _run_refresh_with_logging,
            functools.partial(_fetch_and_cache_versions, catalog.as_uri(), cache),
            "project-versions",
        ),
        log_path=tmp_path / "completion" / "errors.log",
    )
    assert wait_worker(child) == 0
    assert "1.0.0" in (cache / "tags.txt").read_text(encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def cli(*args):
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", *args], cwd=workspace, capture_output=True, text=True, timeout=TIMEOUT
        )
        assert result.returncode == 0, f"{args}: {result.stdout}\n{result.stderr}"
        return result.stdout

    cli("--version")
    assert "Register-ArgumentCompleter" in cli("completion", "powershell")
    cli("add", "widget", "--catalog-source", f"{catalog.as_uri()}@main")
    assert "widget" in (workspace / ".kanon").read_text(encoding="utf-8")
    cli("install")
    assert (workspace / ".kanon.lock").exists()
    package = native_store / "store" / ".packages" / "content"
    assert package.is_symlink()
    assert (package / "file.txt").read_text(encoding="utf-8") == "native synced content"
    cli("install")
    cli("list")
    cli("doctor")
    cli("remove", "widget")
    assert "KANON_SOURCE_widget_URL" not in (workspace / ".kanon").read_text(encoding="utf-8")


def test_update_refresh_persists_cache(tmp_path, monkeypatch):
    """Verify real process/cache behavior while replacing only the remote response."""
    from kanon_cli.completions.cache import _run_refresh_with_logging
    from kanon_cli.core.update_check import read_cached_version
    from worker_callbacks import refresh_update_fixture
    import time

    monkeypatch.setenv("KANON_HOME", str(tmp_path / "home"))
    child = _spawn_detached_windows(
        functools.partial(_run_refresh_with_logging, refresh_update_fixture, "update-check"),
        log_path=tmp_path / "update" / "errors.log",
    )
    assert wait_worker(child) == 0
    version, _ = read_cached_version(int(time.time()), int(TIMEOUT))
    assert version == "9.8.7"
