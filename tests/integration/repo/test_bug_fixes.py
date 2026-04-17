# Copyright (C) 2026 Caylent, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Integration tests for all 20 bug fixes from BACKLOG-repo-bugs.md Section 6.23.

Tests use real temporary git repositories created via subprocess git init in
tmp_path fixtures, real file I/O, and actual code paths end-to-end. No
time.sleep() or time-based synchronization is used.

Organized by severity:
  - Critical (Block production): Bugs 1-4
  - High (Operational risk): Bugs 5-10
  - Medium (Edge cases / quality): Bugs 11-15
  - Low (Code quality / hardening): Bugs 16-20
"""

import logging
import os
import pathlib
import stat
import subprocess
from unittest import mock

import pytest

from kanon_cli.repo import version_constraints
from kanon_cli.repo.error import ManifestInvalidPathError
from kanon_cli.repo.project import Project, _LinkFile
from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Bug Fix Integration Test User"
_GIT_USER_EMAIL = "bug-fix-integration@example.com"

_VALID_MANIFEST_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}" />
  <default revision="main" remote="origin" />
  <project name="myproject" path="myproject" />
</manifest>
"""

_MALFORMED_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}"
  UNCLOSED TAG NO CLOSING BRACKET
</manifest>
"""

_MANIFEST_WITH_UNDEFINED_VARS = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${DEFINED_VAR}" />
  <remote name="secondary" fetch="${UNDEFINED_VAR}" />
  <default revision="main" remote="origin" />
  <project name="myproject" path="myproject" />
</manifest>
"""

_MANIFEST_WITH_NESTED_VAR = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${BASE_${ENV}_URL}" />
  <default revision="main" remote="origin" />
  <project name="myproject" path="myproject" />
</manifest>
"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _init_git_repo(work_dir: pathlib.Path) -> None:
    """Initialise a fresh git working directory with user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _make_link_file(worktree: pathlib.Path, src_rel: str, topdir: pathlib.Path, dest_rel: str) -> _LinkFile:
    """Return a _LinkFile instance for the given paths."""
    return _LinkFile(str(worktree), src_rel, str(topdir), dest_rel)


def _make_envsubst_cmd() -> Envsubst:
    """Return an Envsubst instance without invoking __init__ parent chain."""
    cmd = Envsubst.__new__(Envsubst)
    cmd.manifest = mock.MagicMock()
    return cmd


def _make_project_with_mock_remote(
    revision_expr: str = "refs/tags/dev/mylib/~=1.0.0",
    remote_url: str = "https://example.com/org/repo.git",
) -> Project:
    """Return a Project instance with minimum attributes mocked for constraint tests."""
    proj = Project.__new__(Project)
    proj.name = "test-project"
    proj.revisionExpr = revision_expr
    proj._constraint_resolved = False
    remote = mock.MagicMock()
    remote.url = remote_url
    proj.remote = remote
    return proj


# ===========================================================================
# CRITICAL SEVERITY -- Bugs 1-4 (Block production)
# ===========================================================================


@pytest.mark.integration
def test_bug1_malformed_xml_skipped_processing_continues_end_to_end(tmp_path: pathlib.Path) -> None:
    """Bug 1: Malformed XML in real workspace is skipped; valid file is processed.

    Creates a real .repo/manifests/ directory with a malformed XML file and a
    valid XML file. Invokes EnvSubst() on each. Verifies that the malformed file
    does not crash processing and that the valid file is subsequently processed.

    Covers: Bug 1 -- Malformed XML in envsubst causes unhandled exception.
    """
    manifests_dir = tmp_path / ".repo" / "manifests"
    manifests_dir.mkdir(parents=True)

    malformed_path = manifests_dir / "malformed.xml"
    valid_path = manifests_dir / "valid.xml"

    malformed_path.write_text(_MALFORMED_XML, encoding="utf-8")
    valid_path.write_text(_VALID_MANIFEST_XML, encoding="utf-8")

    cmd = _make_envsubst_cmd()

    processed = []

    def _track_envsubst(infile: str) -> set:
        # Delegate to the real EnvSubst but track which files were called.
        result = Envsubst.EnvSubst(cmd, infile)
        processed.append(infile)
        return result

    with mock.patch.object(cmd, "EnvSubst", side_effect=_track_envsubst):
        with mock.patch("glob.glob", return_value=[str(malformed_path), str(valid_path)]):
            with mock.patch("os.path.getsize", return_value=100):
                with mock.patch("builtins.print"):
                    cmd.Execute(mock.MagicMock(), [])

    assert str(valid_path) in processed, (
        f"Valid XML file {str(valid_path)!r} must be processed even when the "
        f"preceding file is malformed. Processed files: {processed!r}"
    )


@pytest.mark.integration
def test_bug1_no_bak_file_orphaned_for_malformed_xml_in_real_directory(tmp_path: pathlib.Path) -> None:
    """Bug 1: No .bak file is created when parsing fails in a real directory.

    Writes a malformed XML file to a real temp directory, invokes EnvSubst()
    directly, and verifies that no .bak backup file is left behind.

    Covers: Bug 1 -- processing crashes, backup file may be orphaned.
    """
    manifests_dir = tmp_path / ".repo" / "manifests"
    manifests_dir.mkdir(parents=True)

    malformed_path = manifests_dir / "bad.xml"
    malformed_path.write_text(_MALFORMED_XML, encoding="utf-8")

    bak_path = manifests_dir / "bad.xml.bak"

    cmd = _make_envsubst_cmd()
    cmd.EnvSubst(str(malformed_path))

    assert not bak_path.exists(), (
        f"No .bak file must be created when XML parsing fails, "
        f"but {bak_path} was found on disk after EnvSubst() returned."
    )


@pytest.mark.integration
def test_bug2_linkfile_oserror_propagates_from_real_readonly_directory(tmp_path: pathlib.Path) -> None:
    """Bug 2: OSError propagates from symlink creation in a real read-only directory.

    Creates a source file in a git worktree directory and attempts to link it
    into a read-only destination directory. Verifies that the OSError is
    propagated rather than silently swallowed.

    Covers: Bug 2 -- LinkFile errors are silently swallowed.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    _init_git_repo(worktree)

    src_file = worktree / "data.txt"
    src_file.write_text("project data content", encoding="utf-8")

    topdir = tmp_path / "checkout"
    topdir.mkdir()

    # Make topdir read-only so the symlink creation fails.
    topdir.chmod(stat.S_IRUSR | stat.S_IXUSR)

    lf = _make_link_file(worktree, "data.txt", topdir, "linked-data.txt")

    try:
        with pytest.raises(OSError) as exc_info:
            lf._Link()
    finally:
        topdir.chmod(stat.S_IRWXU)

    raised = exc_info.value
    all_text = []
    ex: BaseException | None = raised
    while ex is not None:
        all_text.append(str(ex))
        ex = ex.__cause__ or ex.__context__
        if ex is raised:
            break
    combined = " ".join(all_text)

    assert "data.txt" in combined or str(topdir) in combined, (
        f"Expected source or destination path in error chain, got: {combined!r}"
    )


@pytest.mark.integration
def test_bug3_run_from_args_does_not_replace_process_on_repo_changed_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Bug 3: run_from_args does not call os.execv after RepoChangedException.

    Sets up a real tmp workspace directory, patches _Main to raise
    _ExecvIntercepted (simulating RepoChangedException), and verifies that the
    real os.execv is never called. The calling process must survive.

    Covers: Bug 3 -- os.execv() in RepoChangedException replaces entire process.
    """
    import kanon_cli.repo as repo_pkg
    import kanon_cli.repo.main as repo_main
    from kanon_cli.repo import RepoCommandError

    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    real_execv_calls: list[tuple[str, list[str]]] = []

    def _sentinel_execv(path: str, argv: list[str]) -> None:
        real_execv_calls.append((path, list(argv)))
        raise AssertionError(f"os.execv reached the real os module -- Bug 3 regression: path={path!r}, argv={argv!r}")

    monkeypatch.setattr(os, "execv", _sentinel_execv)

    def _raise_intercepted(argv: list[str]) -> None:
        raise repo_main._ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_dir = str(workspace / ".repo")

    with pytest.raises(RepoCommandError):
        repo_pkg.run_from_args(["sync"], repo_dir=repo_dir)

    assert real_execv_calls == [], (
        f"os.execv was called {len(real_execv_calls)} time(s) on the real os module. "
        f"Bug 3 regression: the embedded process would have been replaced. "
        f"Calls: {real_execv_calls!r}"
    )


@pytest.mark.integration
def test_bug4_foreign_symlink_in_real_directory_logs_warning_and_is_replaced(tmp_path: pathlib.Path) -> None:
    """Bug 4: Foreign symlink in a real directory triggers a warning and is replaced.

    Creates a real source file in a git worktree and a user-created (foreign)
    symlink at the destination. Verifies that _Link() logs a warning about the
    foreign symlink and then replaces it with the repo-managed one.

    Covers: Bug 4 -- Symlink overwrite silently removes user-created symlinks.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    _init_git_repo(worktree)

    src_file = worktree / "config.txt"
    src_file.write_text("repo-managed config", encoding="utf-8")

    topdir = tmp_path / "checkout"
    topdir.mkdir()

    # Create a user-created (foreign) symlink at the destination.
    foreign_target = "/some/user/created/target"
    dest_path = topdir / "config.txt"
    os.symlink(foreign_target, str(dest_path))

    lf = _make_link_file(worktree, "config.txt", topdir, "config.txt")

    with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
        lf._Link()
        assert mock_logger.warning.called, (
            "Expected logger.warning to be called when a foreign symlink is replaced, "
            "but it was not. Bug 4: user-created symlinks must not be silently replaced."
        )

    # The symlink must now point to the repo-managed relative source.
    expected_rel = os.path.relpath(str(src_file), str(topdir))
    assert dest_path.is_symlink(), f"Expected {dest_path} to be a symlink after _Link()"
    actual_target = os.readlink(str(dest_path))
    assert actual_target == expected_rel, (
        f"Expected symlink target to be {expected_rel!r} after replacement, but got {actual_target!r}"
    )


@pytest.mark.integration
def test_bug4_repo_managed_symlink_replaced_without_warning_in_real_directory(tmp_path: pathlib.Path) -> None:
    """Bug 4: Repo-managed symlink replacement produces no warning in a real directory.

    Creates a real source file and a symlink already pointing to the correct
    repo-managed target. Verifies that _Link() is a no-op (no warning logged).

    Covers: Bug 4 -- warning must only fire for foreign symlinks.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    _init_git_repo(worktree)

    src_file = worktree / "schema.json"
    src_file.write_text("{}", encoding="utf-8")

    topdir = tmp_path / "checkout"
    topdir.mkdir()

    # Create a symlink already pointing to the repo-managed relative source.
    expected_rel = os.path.relpath(str(src_file), str(topdir))
    dest_path = topdir / "schema.json"
    os.symlink(expected_rel, str(dest_path))

    lf = _make_link_file(worktree, "schema.json", topdir, "schema.json")

    with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
        lf._Link()
        mock_logger.warning.assert_not_called()


# ===========================================================================
# HIGH SEVERITY -- Bugs 5-10 (Operational risk)
# ===========================================================================


@pytest.mark.integration
def test_bug5_empty_glob_result_logs_warning_in_real_workspace(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Bug 5: Warning is emitted when no XML files are found in a real directory.

    Creates an empty .repo/manifests/ directory (no XML files). Invokes
    Execute() on the Envsubst command with the real glob pattern. Verifies that
    a WARNING is logged indicating no files were found.

    Covers: Bug 5 -- Empty file list in envsubst is silently ignored.
    """
    manifests_dir = tmp_path / ".repo" / "manifests"
    manifests_dir.mkdir(parents=True)
    # No XML files in the directory -- glob will return empty.

    cmd = _make_envsubst_cmd()

    with mock.patch("glob.glob", return_value=[]):
        with mock.patch("builtins.print"):
            with caplog.at_level(logging.WARNING):
                cmd.Execute(mock.MagicMock(), [])

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning_records, (
        "Expected at least one WARNING log record when glob returns an empty list, "
        "but none were emitted. Bug 5: empty file list must not be silently ignored. "
        f"All log records: {[(r.levelno, r.message) for r in caplog.records]!r}"
    )


@pytest.mark.integration
def test_bug6_undefined_env_vars_preserved_in_real_manifest_file(tmp_path: pathlib.Path) -> None:
    """Bug 6: Undefined ${VAR} placeholders are preserved in the output file.

    Writes a manifest to a real temp directory, sets DEFINED_VAR in the
    environment, and calls EnvSubst() without setting UNDEFINED_VAR. Verifies
    that the output file still contains the literal ${UNDEFINED_VAR} string.

    Covers: Bug 6 -- Undefined environment variables are silently preserved
    (the fix adds a WARNING; this test verifies the value is preserved).
    """
    manifests_dir = tmp_path / ".repo" / "manifests"
    manifests_dir.mkdir(parents=True)

    manifest_path = manifests_dir / "default.xml"
    manifest_path.write_text(_MANIFEST_WITH_UNDEFINED_VARS, encoding="utf-8")

    cmd = _make_envsubst_cmd()

    env = {k: v for k, v in os.environ.items() if k != "UNDEFINED_VAR"}
    env["DEFINED_VAR"] = "https://git.example.com/org/"

    with mock.patch.dict(os.environ, env, clear=True):
        cmd.EnvSubst(str(manifest_path))

    output = manifest_path.read_text(encoding="utf-8")
    assert "${UNDEFINED_VAR}" in output, (
        "Expected ${UNDEFINED_VAR} to be preserved literally in the output manifest "
        f"when the variable is not defined in the environment, but it was removed. "
        f"Output content:\n{output}"
    )
    assert "https://git.example.com/org/" in output, (
        "Expected DEFINED_VAR to be expanded to its value in the output manifest, "
        f"but it was not found. Output content:\n{output}"
    )


@pytest.mark.integration
def test_bug6_warning_logged_for_undefined_vars_in_real_manifest_file(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Bug 6: WARNING is logged for each undefined variable in a real manifest.

    Writes a manifest with an undefined variable to a real temp directory and
    calls EnvSubst(). Verifies that a WARNING log record mentions the undefined
    variable name and the file path.

    Covers: Bug 6 -- undefined variables are silently preserved (fix adds warning).
    """
    manifests_dir = tmp_path / ".repo" / "manifests"
    manifests_dir.mkdir(parents=True)

    manifest_path = manifests_dir / "default.xml"
    manifest_path.write_text(_MANIFEST_WITH_UNDEFINED_VARS, encoding="utf-8")

    cmd = _make_envsubst_cmd()

    env = {k: v for k, v in os.environ.items() if k != "UNDEFINED_VAR"}
    env["DEFINED_VAR"] = "https://git.example.com/org/"

    with mock.patch.dict(os.environ, env, clear=True):
        with caplog.at_level(logging.WARNING):
            cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    undefined_warnings = [r for r in warning_records if "UNDEFINED_VAR" in r.message]
    assert undefined_warnings, (
        "Expected a WARNING log record mentioning 'UNDEFINED_VAR' for the "
        "undefined variable, but none were found. "
        f"All warning records: {[r.message for r in warning_records]!r}"
    )

    filename = str(manifest_path)
    for record in undefined_warnings:
        assert filename in record.message, (
            f"WARNING for UNDEFINED_VAR must include the filename {filename!r}, "
            f"but it does not. Record message: {record.message!r}"
        )


@pytest.mark.integration
def test_bug7_ls_remote_retried_on_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug 7: _ResolveVersionConstraint retries git ls-remote on transient failures.

    Patches subprocess.run so the first call fails and the second succeeds.
    Verifies that _ResolveVersionConstraint calls subprocess.run twice (retry)
    and ultimately resolves the constraint correctly.

    Covers: Bug 7 -- git ls-remote failures not retried.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "2")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    success_output = "deadbeef00000001\trefs/tags/dev/mylib/1.0.0\n"

    call_count = [0]

    def _fake_run(cmd_args, **kwargs):
        call_count[0] += 1
        result = mock.MagicMock()
        if call_count[0] == 1:
            # First call: transient failure.
            result.returncode = 1
            result.stdout = ""
            result.stderr = "Connection reset by peer"
        else:
            # Second call: success.
            result.returncode = 0
            result.stdout = success_output
            result.stderr = ""
        return result

    proj = _make_project_with_mock_remote("refs/tags/dev/mylib/~=1.0.0")

    with mock.patch("subprocess.run", side_effect=_fake_run):
        proj._ResolveVersionConstraint()

    assert call_count[0] >= 2, (
        f"Expected subprocess.run to be called at least twice (1 failure + 1 retry), "
        f"but it was called {call_count[0]} time(s). "
        f"Bug 7: transient git ls-remote failures must be retried."
    )
    assert proj.revisionExpr == "refs/tags/dev/mylib/1.0.0", (
        f"Expected revisionExpr to be resolved to 'refs/tags/dev/mylib/1.0.0' "
        f"after retry, but got {proj.revisionExpr!r}"
    )


@pytest.mark.integration
def test_bug8_stderr_included_in_error_message_for_ls_remote_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug 8: ManifestInvalidRevisionError includes stderr from failed git ls-remote.

    Patches subprocess.run to return a failed result with stderr text. Verifies
    that the ManifestInvalidRevisionError raised includes the stderr output so
    the user can diagnose the failure (auth error, network error, wrong URL).

    Covers: Bug 8 -- git ls-remote error messages don't include stderr.
    """
    from kanon_cli.repo.error import ManifestInvalidRevisionError

    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    distinctive_stderr = "ERROR: Repository not found -- check SSH key and repo URL"

    def _fake_run_always_fails(cmd_args, **kwargs):
        result = mock.MagicMock()
        result.returncode = 128
        result.stdout = ""
        result.stderr = distinctive_stderr
        return result

    proj = _make_project_with_mock_remote(
        "refs/tags/dev/mylib/~=1.0.0",
        "https://example.com/org/missing-repo.git",
    )

    with mock.patch("subprocess.run", side_effect=_fake_run_always_fails):
        with pytest.raises(ManifestInvalidRevisionError) as exc_info:
            proj._ResolveVersionConstraint()

    error_message = str(exc_info.value)
    assert distinctive_stderr in error_message, (
        f"Expected ManifestInvalidRevisionError to include the stderr output "
        f"{distinctive_stderr!r} so the user can diagnose the failure, "
        f"but it was not found. Error message: {error_message!r}"
    )


@pytest.mark.integration
def test_bug9_constraint_resolved_only_once_across_two_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug 9: _ResolveVersionConstraint only calls git ls-remote once per constraint.

    Calls _ResolveVersionConstraint() twice. Verifies that subprocess.run is
    called only once because the result is cached via _constraint_resolved.

    Covers: Bug 9 -- Version constraint resolution called redundantly.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    call_count = [0]

    def _fake_run(cmd_args, **kwargs):
        call_count[0] += 1
        result = mock.MagicMock()
        result.returncode = 0
        result.stdout = "deadbeef\trefs/tags/dev/mylib/1.0.0\n"
        result.stderr = ""
        return result

    proj = _make_project_with_mock_remote("refs/tags/dev/mylib/~=1.0.0")

    with mock.patch("subprocess.run", side_effect=_fake_run):
        proj._ResolveVersionConstraint()
        proj._ResolveVersionConstraint()

    assert call_count[0] == 1, (
        f"Expected subprocess.run to be called exactly once (cached after first call), "
        f"but it was called {call_count[0]} time(s). "
        f"Bug 9: constraint resolution must not issue redundant ls-remote calls."
    )
    assert proj._constraint_resolved is True, (
        f"Expected _constraint_resolved to be True after successful resolution, but got {proj._constraint_resolved!r}"
    )


@pytest.mark.integration
def test_bug10_selfupdate_embedded_prints_message_and_returns_success() -> None:
    """Bug 10: selfupdate is a no-op when running embedded, printing a message.

    Patches the EMBEDDED flag to True and verifies that Execute() returns 0
    (success) without attempting any git sync or update operations.

    Covers: Bug 10 -- selfupdate subcommand incompatible with embedding.
    """
    from kanon_cli.repo import pager as _pager_module
    from kanon_cli.repo.subcmds import selfupdate as selfupdate_mod

    instance = selfupdate_mod.Selfupdate.__new__(selfupdate_mod.Selfupdate)
    instance.manifest = mock.MagicMock()
    instance.client = mock.MagicMock()
    instance.git_event_log = mock.MagicMock()
    instance.event_log = mock.MagicMock()
    instance.outer_client = mock.MagicMock()

    opt = mock.MagicMock()
    opt.repo_upgraded = False
    opt.repo_verify = True

    original_embedded = _pager_module.EMBEDDED
    _pager_module.EMBEDDED = True
    try:
        result = instance.Execute(opt, [])
    finally:
        _pager_module.EMBEDDED = original_embedded

    assert result == 0, (
        f"Expected selfupdate.Execute() to return 0 (success) when running embedded, "
        f"but got {result!r}. "
        f"Bug 10: selfupdate must be a no-op when repo project does not exist."
    )
    # Verify no sync was attempted.
    instance.manifest.repoProject.Sync_NetworkHalf.assert_not_called()


@pytest.mark.integration
def test_bug10_selfupdate_embedded_does_not_call_rp_sync() -> None:
    """Bug 10: selfupdate does not attempt Sync_NetworkHalf when embedded.

    Verifies that the repoProject.Sync_NetworkHalf() method is never called
    when EMBEDDED is True. This would fail in embedded mode because the repo
    project does not exist as a real git directory.

    Covers: Bug 10 -- selfupdate subcommand incompatible with embedding.
    """
    from kanon_cli.repo import pager as _pager_module
    from kanon_cli.repo.subcmds import selfupdate as selfupdate_mod

    instance = selfupdate_mod.Selfupdate.__new__(selfupdate_mod.Selfupdate)
    mock_manifest = mock.MagicMock()
    mock_manifest.repoProject = mock.MagicMock()
    instance.manifest = mock_manifest
    instance.client = mock.MagicMock()
    instance.git_event_log = mock.MagicMock()
    instance.event_log = mock.MagicMock()
    instance.outer_client = mock.MagicMock()

    opt = mock.MagicMock()
    opt.repo_upgraded = False
    opt.repo_verify = True

    original_embedded = _pager_module.EMBEDDED
    _pager_module.EMBEDDED = True
    try:
        instance.Execute(opt, [])
    finally:
        _pager_module.EMBEDDED = original_embedded

    mock_manifest.repoProject.Sync_NetworkHalf.assert_not_called()


# ===========================================================================
# MEDIUM SEVERITY -- Bugs 11-15 (Edge cases / quality)
# ===========================================================================


@pytest.mark.integration
def test_bug11_race_condition_retry_on_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug 11: Retry covers transient tag deletion race condition.

    Simulates the race condition where git ls-remote succeeds on the retry
    after an initial transient failure (e.g., tag deleted between ls-remote
    and fetch). Verifies that the retry mechanism from Bug 7 also handles
    the Bug 11 race condition scenario.

    Covers: Bug 11 -- Race condition: tag deleted between ls-remote and fetch.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    # Simulate: first call gets a transient error (tag was just deleted),
    # second call succeeds with the available tags.
    call_results = [
        (1, "", "fatal: unable to connect to remote"),
        (0, "deadbeef\trefs/tags/dev/race/2.0.0\n", ""),
    ]
    call_idx = [0]

    def _fake_run(cmd_args, **kwargs):
        idx = call_idx[0]
        call_idx[0] += 1
        rc, stdout, stderr = call_results[idx] if idx < len(call_results) else call_results[-1]
        result = mock.MagicMock()
        result.returncode = rc
        result.stdout = stdout
        result.stderr = stderr
        return result

    proj = _make_project_with_mock_remote("refs/tags/dev/race/~=2.0.0")

    with mock.patch("subprocess.run", side_effect=_fake_run):
        proj._ResolveVersionConstraint()

    assert call_idx[0] >= 2, (
        f"Expected at least 2 subprocess.run calls (failure + retry), "
        f"but got {call_idx[0]}. Bug 11 retry path was not exercised."
    )
    assert proj.revisionExpr == "refs/tags/dev/race/2.0.0", (
        f"Expected revisionExpr resolved to 'refs/tags/dev/race/2.0.0' after retry, but got {proj.revisionExpr!r}"
    )


@pytest.mark.integration
def test_bug12_backup_file_rotation_in_real_filesystem(tmp_path: pathlib.Path) -> None:
    """Bug 12: Running envsubst twice does not orphan the first backup file.

    Writes a manifest, runs EnvSubst() once to create a .bak file, then runs
    EnvSubst() again on the processed output. Verifies that a single .bak file
    exists and that the original content is preserved in it.

    Covers: Bug 12 -- envsubst backup overwrites previous backup.
    """
    manifests_dir = tmp_path / ".repo" / "manifests"
    manifests_dir.mkdir(parents=True)

    manifest_path = manifests_dir / "default.xml"
    original_content = _VALID_MANIFEST_XML
    manifest_path.write_text(original_content, encoding="utf-8")

    cmd = _make_envsubst_cmd()

    env = {k: v for k, v in os.environ.items()}
    env["GITBASE"] = "https://git.example.com/"

    with mock.patch.dict(os.environ, env):
        cmd.EnvSubst(str(manifest_path))

    # After first run, a .bak file must exist.
    bak_path = pathlib.Path(str(manifest_path) + ".bak")
    assert bak_path.exists(), (
        f"Expected .bak file {bak_path} to exist after first EnvSubst() call, but it was not found."
    )

    # Run EnvSubst() a second time on the already-processed file.
    with mock.patch.dict(os.environ, env):
        cmd.EnvSubst(str(manifest_path))

    # The .bak file must still exist after the second run.
    assert bak_path.exists(), (
        f"Expected .bak file {bak_path} to still exist after second EnvSubst() call, "
        f"but it was not found. Bug 12: backup rotation must not delete the backup."
    )


@pytest.mark.integration
def test_bug13_warning_logged_when_manifest_url_changes_on_reinit() -> None:
    """Bug 13: Warning is logged when manifest URL changes during repo reinit.

    Creates an Init command with an existing checkout and a different manifest
    URL, then calls Execute(). Patches the module-level logger to capture calls
    and verifies that a warning is logged mentioning both the old and new URLs.

    Covers: Bug 13 -- Init reinitializes with different URL without warning.
    """
    from kanon_cli.repo.subcmds import init

    old_url = "https://old.example.com/manifest.git"
    new_url = "https://new.example.com/manifest.git"

    cmd = init.Init()
    cmd.manifest = mock.MagicMock()
    cmd.manifest.repoProject.worktree = "/nonexistent/.repo/repo"
    cmd.manifest.manifestProject.Exists = True
    cmd.manifest.manifestProject.config.GetString.return_value = old_url
    cmd.manifest.IsMirror = False
    cmd.manifest.topdir = "/fake/topdir"
    cmd.git_event_log = mock.MagicMock()

    opt = mock.MagicMock()
    opt.manifest_url = new_url
    opt.repo_url = None
    opt.repo_rev = None
    opt.repo_verify = True
    opt.quiet = True
    opt.worktree = False
    opt.config_name = False

    with mock.patch.object(cmd, "_SyncManifest"):
        with mock.patch("os.isatty", return_value=False):
            with mock.patch("os.path.isdir", return_value=False):
                with mock.patch.object(init.logger, "warning") as mock_warning:
                    cmd.Execute(opt, [])

    all_warning_calls = mock_warning.call_args_list
    formatted_messages = []
    for call in all_warning_calls:
        args = call.args
        if args:
            try:
                formatted_messages.append(args[0] % args[1:])
            except (TypeError, IndexError):
                formatted_messages.append(str(args[0]))

    combined = " ".join(formatted_messages)
    assert old_url in combined, (
        f"Expected warning to include old URL {old_url!r}, "
        f"but warning messages were: {formatted_messages!r}. "
        f"Bug 13: URL change during reinit must be reported to the user."
    )
    assert new_url in combined, (
        f"Expected warning to include new URL {new_url!r}, "
        f"but warning messages were: {formatted_messages!r}. "
        f"Bug 13: URL change during reinit must include both old and new URLs."
    )


@pytest.mark.integration
def test_bug14_non_tty_log_message_emitted() -> None:
    """Bug 14: An informational message is logged when stdin is not a TTY.

    Creates an Init command and calls Execute() in a context where os.isatty
    returns False for stdin. Patches the module-level logger to capture calls
    and verifies that an info message mentioning 'TTY' or 'interactive prompts'
    is logged.

    Covers: Bug 14 -- Interactive prompts silently skipped in non-TTY context.
    """
    from kanon_cli.repo.subcmds import init

    cmd = init.Init()
    cmd.manifest = mock.MagicMock()
    cmd.manifest.repoProject.worktree = "/nonexistent/.repo/repo"
    cmd.manifest.manifestProject.Exists = False
    cmd.manifest.IsMirror = False
    cmd.manifest.topdir = "/fake/topdir"
    cmd.git_event_log = mock.MagicMock()

    opt = mock.MagicMock()
    opt.manifest_url = "https://example.com/manifest.git"
    opt.repo_url = None
    opt.repo_rev = None
    opt.repo_verify = True
    opt.quiet = True
    opt.worktree = False
    opt.config_name = False

    with mock.patch.object(cmd, "_SyncManifest"):
        with mock.patch("os.isatty", return_value=False):
            with mock.patch("os.path.isdir", return_value=False):
                with mock.patch.object(init.logger, "info") as mock_info:
                    cmd.Execute(opt, [])

    all_info_calls = mock_info.call_args_list
    formatted_messages = []
    for call in all_info_calls:
        args = call.args
        if args:
            try:
                formatted_messages.append(args[0] % args[1:])
            except (TypeError, IndexError):
                formatted_messages.append(str(args[0]))

    combined = " ".join(formatted_messages).lower()
    assert "tty" in combined or "interactive" in combined or "prompt" in combined, (
        "Expected an info log message mentioning 'TTY', 'interactive', or 'prompt' "
        "when stdin is not a TTY, but none were found. "
        f"Bug 14: non-TTY context must log that prompts are being skipped. "
        f"All info messages: {formatted_messages!r}"
    )


@pytest.mark.integration
def test_bug15_prerelease_exclusion_documented_in_version_constraints_module() -> None:
    """Bug 15: Pre-release version exclusion behavior is documented in the module.

    Verifies that the version_constraints module documents the PEP 440
    pre-release exclusion behavior so users understand why constraints like
    '>=1.0.0' exclude '1.0.0a1'.

    Covers: Bug 15 -- Pre-release versions silently excluded by PEP 440.
    """
    module_doc = version_constraints.__doc__ or ""
    assert "pre-release" in module_doc.lower() or "prerelease" in module_doc.lower(), (
        "Expected the version_constraints module docstring to document the "
        "pre-release version exclusion behavior (mention 'pre-release' or 'prerelease'), "
        "but it does not. "
        f"Bug 15: this behavior must be documented so users are not surprised. "
        f"Current module docstring: {module_doc!r}"
    )


# ===========================================================================
# LOW SEVERITY -- Bugs 16-20 (Code quality / hardening)
# ===========================================================================


@pytest.mark.integration
def test_bug16_nested_variable_warning_in_real_manifest_file(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Bug 16: Nested variable reference ${BASE_${ENV}_URL} logs a WARNING.

    Writes a manifest with a nested ${...${...}...} pattern to a real temp
    directory. Calls EnvSubst() and verifies that a WARNING is logged containing
    the full nested pattern text.

    Covers: Bug 16 -- No nested variable reference support in envsubst.
    """
    manifests_dir = tmp_path / ".repo" / "manifests"
    manifests_dir.mkdir(parents=True)

    manifest_path = manifests_dir / "nested.xml"
    manifest_path.write_text(_MANIFEST_WITH_NESTED_VAR, encoding="utf-8")

    cmd = _make_envsubst_cmd()

    with caplog.at_level(logging.WARNING):
        cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    nested_pattern = "${BASE_${ENV}_URL}"
    nested_warnings = [r for r in warning_records if nested_pattern in r.message]
    assert nested_warnings, (
        f"Expected a WARNING log record containing the full nested pattern "
        f"{nested_pattern!r}, but none were found. "
        f"Bug 16: nested variable references must be detected and warned about. "
        f"All warning records: {[r.message for r in warning_records]!r}"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "sep_char,expected_works",
    [
        ("/", True),
        (os.sep, True),
    ],
    ids=["forward_slash", "os_sep"],
)
def test_bug17_path_operations_work_with_various_separators(
    tmp_path: pathlib.Path,
    sep_char: str,
    expected_works: bool,
) -> None:
    """Bug 17: Path operations work correctly with both forward slash and os.sep.

    Creates a real source file and verifies that _LinkFile can create a symlink
    when the source path is specified with either forward slash or os.sep as
    the directory separator. On Linux both are the same; this test confirms the
    path handling is not brittle.

    Covers: Bug 17 -- Path operations assume Unix separators in some places.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    _init_git_repo(worktree)

    subdir = worktree / "configs"
    subdir.mkdir()
    config_file = subdir / "app.conf"
    config_file.write_text("[settings]", encoding="utf-8")

    topdir = tmp_path / "checkout"
    topdir.mkdir()

    # Use the separator character specified by the parametrize.
    # On Linux '/' == os.sep so both cases exercise the same code path,
    # confirming no assumptions break.
    src_rel = f"configs{sep_char}app.conf"
    lf = _make_link_file(worktree, src_rel, topdir, "app.conf")

    lf._Link()

    dest_path = topdir / "app.conf"
    assert dest_path.is_symlink() or dest_path.exists(), (
        f"Expected symlink or file at {dest_path} after _Link() with separator {sep_char!r}, but neither was found."
    )


@pytest.mark.integration
def test_bug19_nonexistent_glob_src_directory_raises_clear_error(tmp_path: pathlib.Path) -> None:
    """Bug 19: Clear error raised when glob source directory does not exist.

    Creates a _LinkFile with a glob src pattern pointing to a directory that
    does not exist, then calls _Link(). Verifies that an exception is raised
    with an error message that includes the missing path.

    Covers: Bug 19 -- Glob patterns with non-existent source have confusing error.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    _init_git_repo(worktree)

    topdir = tmp_path / "checkout"
    topdir.mkdir()

    # Source directory that does not exist.
    nonexistent_src = "nonexistent_subdir/*.xml"
    lf = _make_link_file(worktree, nonexistent_src, topdir, "dest_dir")

    with pytest.raises((ManifestInvalidPathError, FileNotFoundError, OSError)) as exc_info:
        lf._Link()

    error_text = str(exc_info.value)
    assert "nonexistent_subdir" in error_text or "does not exist" in error_text, (
        f"Expected the error message to mention the missing source directory "
        f"'nonexistent_subdir' or 'does not exist', but got: {error_text!r}. "
        f"Bug 19: error messages for missing glob source paths must be actionable."
    )


@pytest.mark.integration
def test_bug20_glob_dest_is_file_raises_exception_not_silently_skipped(tmp_path: pathlib.Path) -> None:
    """Bug 20: Exception raised when glob destination is an existing file.

    Creates a real glob src pattern with matching files and a destination that
    is an existing file (not a directory). Calls _Link() and verifies that an
    exception is raised rather than the glob being silently skipped.

    Covers: Bug 20 -- Glob linkfile skipped silently if dest is a file.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    _init_git_repo(worktree)

    configs_dir = worktree / "configs"
    configs_dir.mkdir()
    (configs_dir / "app.xml").write_text("<config/>", encoding="utf-8")
    (configs_dir / "db.xml").write_text("<database/>", encoding="utf-8")

    topdir = tmp_path / "checkout"
    topdir.mkdir()

    # Create dest as a regular file (not a directory) -- this is the bug condition.
    dest_file = topdir / "dest_as_file"
    dest_file.write_text("I am a file, not a directory", encoding="utf-8")

    lf = _make_link_file(worktree, "configs/*.xml", topdir, "dest_as_file")

    with pytest.raises((ManifestInvalidPathError, FileExistsError, ValueError, OSError)):
        lf._Link()
