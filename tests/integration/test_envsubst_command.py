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

"""Integration tests for BV-09: envsubst .bak preserves first-run content.

Invokes the kanon repo envsubst command via subprocess.run against a real
temp directory to confirm skip-if-exists .bak semantics hold end-to-end.

The workspace is initialised with a real ``repo init`` so that the manifest
file is tracked in a git repository, exactly as users would encounter in
production. This exercises the full envsubst code path rather than just the
unit-level Envsubst class.

AC-TEST-005
"""

import os
import pathlib
import subprocess
import sys

import pytest


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANIFEST_DIR = pathlib.Path(".repo") / "manifests"
_MANIFEST_NAME = "default.xml"
_GIT_USER_NAME = "BV09 Test User"
_GIT_USER_EMAIL = "bv09-test@example.com"

_ORIGINAL_MANIFEST = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${BV09_FETCH_URL}" />
  <default revision="main" remote="origin" />
  <project name="myproject" path="myproject" />
</manifest>
"""

_FETCH_URL = "https://integration.example.com/repos"


# ---------------------------------------------------------------------------
# Workspace setup helpers
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


def _make_manifest_bare_repo(base: pathlib.Path, manifest_xml: str) -> pathlib.Path:
    """Create a bare git repository containing the given manifest XML.

    Returns the path to the bare repository.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir(parents=True)
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)
    (work_dir / _MANIFEST_NAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_NAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    bare_dir = base / "manifest-bare"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)
    return bare_dir


def _repo_init_workspace(workspace: pathlib.Path, manifest_url: str) -> None:
    """Run repo init in workspace using the given manifest_url."""
    from kanon_cli.repo.main import run_from_args

    repo_dot_dir = str(workspace / ".repo")
    run_from_args(
        [
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            "-b",
            "main",
            "-m",
            _MANIFEST_NAME,
        ],
        repo_dir=repo_dot_dir,
    )


def _make_workspace(tmp_path: pathlib.Path, manifest_xml: str) -> pathlib.Path:
    """Create a fully initialised workspace with the given manifest XML.

    Returns the workspace directory (contains .repo/).
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    bare = _make_manifest_bare_repo(repos_base, manifest_xml)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _repo_init_workspace(workspace, f"file://{bare}")
    return workspace


def _run_envsubst(workspace: pathlib.Path, fetch_url: str) -> subprocess.CompletedProcess:
    """Run ``kanon repo envsubst`` in workspace via subprocess.

    Passes ``--repo-dir`` as an absolute path so that manifest_xml.py can
    resolve the manifest file to an absolute path (a relative .repo path
    causes ManifestParseError when the subprocess resolves symlinks).
    """
    env = {**os.environ, "BV09_FETCH_URL": fetch_url}
    repo_dir = str(workspace / ".repo")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "kanon_cli",
            "repo",
            "--repo-dir",
            repo_dir,
            "envsubst",
        ],
        cwd=str(workspace),
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# AC-TEST-005: BV-09 end-to-end scenario via subprocess
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_bv09_bak_preserved_across_two_runs(tmp_path: pathlib.Path) -> None:
    """AC-TEST-005: .bak is created once and preserved across two envsubst runs.

    Step 1: Write original manifest with ${BV09_FETCH_URL} placeholder.
    Step 2: Run envsubst. Assert .bak exists and contains the original bytes.
    Step 3: Run envsubst again. Assert .bak is byte-identical to step-2 .bak
            (the substituted manifest from run 1 is NOT written to .bak by run 2).

    BV-09
    """
    workspace = _make_workspace(tmp_path, _ORIGINAL_MANIFEST)
    manifests_dir = workspace / _MANIFEST_DIR
    manifest_path = manifests_dir / _MANIFEST_NAME
    original_bytes = manifest_path.read_bytes()
    bak_path = manifests_dir / (_MANIFEST_NAME + ".bak")

    # --- First run ---
    result_1 = _run_envsubst(workspace, _FETCH_URL)
    assert result_1.returncode == 0, (
        f"First envsubst run must exit 0. Got {result_1.returncode}.\n"
        f"stdout: {result_1.stdout!r}\n"
        f"stderr: {result_1.stderr!r}"
    )
    assert bak_path.exists(), (
        f"First run must create .bak at {bak_path}. "
        f"Manifests dir contents: {sorted(str(p) for p in manifests_dir.iterdir())!r}"
    )
    bak_after_first = bak_path.read_bytes()
    assert bak_after_first == original_bytes, (
        f"AC-TEST-001 (in BV-09): .bak after first run must contain original bytes. "
        f"Expected {original_bytes!r}, got {bak_after_first!r}"
    )

    # Confirm substitution happened in the manifest
    manifest_after_first = manifest_path.read_text(encoding="utf-8")
    assert _FETCH_URL in manifest_after_first, (
        f"Expected manifest to contain substituted URL after first run. Got: {manifest_after_first!r}"
    )
    assert "${BV09_FETCH_URL}" not in manifest_after_first, (
        f"Expected placeholder to be replaced after first run. Got: {manifest_after_first!r}"
    )

    # --- Second run ---
    result_2 = _run_envsubst(workspace, _FETCH_URL)
    assert result_2.returncode == 0, (
        f"Second envsubst run must exit 0. Got {result_2.returncode}.\n"
        f"stdout: {result_2.stdout!r}\n"
        f"stderr: {result_2.stderr!r}"
    )
    bak_after_second = bak_path.read_bytes()
    assert bak_after_second == original_bytes, (
        f"AC-TEST-002 (in BV-09): .bak after second run must still equal original bytes. "
        f"Second run must NOT overwrite .bak with post-substitution content. "
        f"Expected {original_bytes!r}, got {bak_after_second!r}"
    )


@pytest.mark.integration
def test_bv09_pre_existing_bak_not_overwritten(tmp_path: pathlib.Path) -> None:
    """AC-TEST-003 (subprocess): Pre-existing .bak is left untouched by envsubst.

    Creates a .bak file with user content before running envsubst.
    After envsubst completes, the .bak content must be unchanged.
    """
    workspace = _make_workspace(tmp_path, _ORIGINAL_MANIFEST)
    manifests_dir = workspace / _MANIFEST_DIR
    bak_path = manifests_dir / (_MANIFEST_NAME + ".bak")
    user_content = b"user-managed backup -- envsubst must not touch this"
    bak_path.write_bytes(user_content)

    result = _run_envsubst(workspace, _FETCH_URL)
    assert result.returncode == 0, (
        f"envsubst must exit 0 even when pre-existing .bak is present. "
        f"Got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert bak_path.read_bytes() == user_content, (
        f"Pre-existing .bak must be unchanged after envsubst. Expected {user_content!r}, got {bak_path.read_bytes()!r}"
    )
