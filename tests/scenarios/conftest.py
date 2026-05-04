"""Harness for end-to-end scenario tests mirroring `docs/integration-testing.md`.

Each scenario in the doc is automated as a `pytest.mark.scenario` test that
invokes real `kanon` / `git` subprocesses against on-disk fixtures, exactly
as a human or agent would. This module provides the Python equivalents of
the doc's bash helpers (`rp_ro_setup`, `mk_rx_xml`, `mk_mfst_xml`, `pk_xml`,
`mk_plugin_repo`, `cs_catalog_repo`, etc.) so individual scenario tests can
delegate fixture construction to a single source of truth.

Subprocess wrappers and synthetic git-repo builders live here as standalone
helpers so scenarios remain importable without sys.path manipulation. The
`tests/functional/` package contains its own (similar) helpers tuned for
its specific lifecycle assumptions; the two coexist intentionally and
should not cross-import.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
from collections.abc import Iterator
from typing import Iterable

import pytest


# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

INTEGRATION_DOC = pathlib.Path(__file__).resolve().parents[2] / "docs" / "integration-testing.md"

_DEFAULT_GIT_USER_NAME = "Kanon Scenario Test"
_DEFAULT_GIT_USER_EMAIL = "scenario-test@kanon.example"
_DEFAULT_GIT_BRANCH = "main"


# ---------------------------------------------------------------------------
# Doc parsing helpers
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^### ([A-Z][A-Za-z-]*-\d+):\s*(.+)$", re.MULTILINE)


def all_scenario_ids() -> list[str]:
    """Return every scenario ID declared in `docs/integration-testing.md`."""
    return [m.group(1) for m in _HEADING_RE.finditer(INTEGRATION_DOC.read_text())]


def scenario_block(scenario_id: str) -> str:
    """Return the markdown block (heading -> next ### heading) for a scenario."""
    text = INTEGRATION_DOC.read_text()
    pattern = re.compile(rf"^### {re.escape(scenario_id)}:.*?(?=^### |\Z)", re.MULTILINE | re.DOTALL)
    m = pattern.search(text)
    if not m:
        raise LookupError(f"Scenario {scenario_id!r} not found in {INTEGRATION_DOC}")
    return m.group(0)


# ---------------------------------------------------------------------------
# Subprocess wrappers
# ---------------------------------------------------------------------------


def run_kanon(
    *args: str,
    cwd: pathlib.Path | str | None = None,
    env: dict[str, str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Invoke `python -m kanon_cli <args>` and return the completed process.

    Mirrors `tests/functional/conftest._run_kanon` but lives in the scenarios
    package so it stays importable without sys.path tricks.
    """
    if env is not None and extra_env is not None:
        raise ValueError("Provide either 'env' or 'extra_env', not both.")
    resolved_env: dict[str, str] | None
    if env is not None:
        resolved_env = env
    elif extra_env is not None:
        resolved_env = dict(os.environ)
        resolved_env.update(extra_env)
    else:
        resolved_env = None
    resolved_cwd = str(cwd) if cwd is not None else None
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=resolved_cwd,
        env=resolved_env,
    )


def run_git(args: list[str], cwd: pathlib.Path) -> subprocess.CompletedProcess:
    """Run `git <args>` in cwd; raise RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}: stdout={result.stdout!r} stderr={result.stderr!r}")
    return result


def init_git_work_dir(
    work_dir: pathlib.Path,
    *,
    branch: str = _DEFAULT_GIT_BRANCH,
    user_name: str = _DEFAULT_GIT_USER_NAME,
    user_email: str = _DEFAULT_GIT_USER_EMAIL,
) -> None:
    """Initialise a git working directory with user config set."""
    work_dir.mkdir(parents=True, exist_ok=True)
    run_git(["init", "-b", branch], work_dir)
    run_git(["config", "user.name", user_name], work_dir)
    run_git(["config", "user.email", user_email], work_dir)


def clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into bare_dir; return resolved bare_dir."""
    run_git(["clone", "--bare", str(work_dir), str(bare_dir)], work_dir.parent)
    return bare_dir.resolve()


# ---------------------------------------------------------------------------
# Synthetic git fixture builders
# ---------------------------------------------------------------------------


def make_bare_repo_with_tags(parent: pathlib.Path, name: str, tags: Iterable[str]) -> pathlib.Path:
    """Create a bare git repo `name.git` under `parent` with each tag in `tags`.

    Each tag points at a commit whose `version.txt` content is the tag name.
    Default branch is `main`.
    """
    work = parent / f"{name}.work"
    bare = parent / f"{name}.git"
    init_git_work_dir(work)
    for tag in tags:
        (work / "version.txt").write_text(tag)
        run_git(["add", "version.txt"], work)
        run_git(["commit", "-m", f"version {tag}"], work)
        run_git(["tag", tag], work)
    return clone_as_bare(work, bare)


def make_plain_repo(parent: pathlib.Path, name: str, files: dict[str, str]) -> pathlib.Path:
    """Create a bare git repo containing the given files on `main`."""
    work = parent / f"{name}.work"
    bare = parent / f"{name}.git"
    init_git_work_dir(work)
    for relpath, content in files.items():
        target = work / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        run_git(["add", relpath], work)
    run_git(["commit", "-m", f"seed {name}"], work)
    return clone_as_bare(work, bare)


def mk_plugin_repo(
    parent: pathlib.Path,
    name: str,
    tags: tuple[str, ...] = ("1.0.0", "2.0.0", "3.0.0"),
) -> pathlib.Path:
    """Build a synthetic marketplace plugin git repo.

    Mirrors §15 `mk_plugin_repo`: writes `.claude-plugin/marketplace.json` +
    `.claude-plugin/plugin.json`, commits, tags each entry in `tags`.
    Returns the bare repo path.
    """
    work = parent / f"{name}.work"
    bare = parent / f"{name}.git"
    init_git_work_dir(work)
    cp = work / ".claude-plugin"
    cp.mkdir()
    (cp / "marketplace.json").write_text(json.dumps({"name": name, "plugins": [{"name": name}]}))
    (cp / "plugin.json").write_text(json.dumps({"name": name, "description": f"synthetic plugin {name}"}))
    run_git(["add", ".claude-plugin"], work)
    run_git(["commit", "-m", f"seed plugin {name}"], work)
    for tag in tags:
        run_git(["tag", tag], work)
    return clone_as_bare(work, bare)


_CS_CATALOG_TAGS = ("1.0.0", "1.0.1", "1.1.0", "2.0.0", "3.0.0")


def cs_catalog_repo(parent: pathlib.Path) -> pathlib.Path:
    """Create a bare cs-catalog repo with semver tags 1.0.0..3.0.0.

    HEAD on `main` is pinned to refs/tags/3.0.0 so PEP 440 constraints
    (`latest`, `*`, `>=X`, etc.) resolve cleanly via
    `--revision-as-tag`. Mirrors the E2-F3-S2-T6 reset contract.
    """
    return make_bare_repo_with_tags(parent, "cs-catalog", _CS_CATALOG_TAGS)


# ---------------------------------------------------------------------------
# XML manifest builders (escape `<`/`>`/`&` per E2-F3-S2-T5)
# ---------------------------------------------------------------------------


def xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mk_rx_xml(
    parent: pathlib.Path,
    fetch_url: str,
    project_name: str,
    revision: str,
    *,
    filename: str | None = None,
) -> pathlib.Path:
    """Build a minimal RX-style manifest XML pointing at `fetch_url/project_name`.

    `revision` may carry PEP 440 operators (`<=`, `>=`, etc.); they are
    XML-escaped so the manifest parser sees the original constraint string.
    """
    rev = xml_escape(revision)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_url}" />\n'
        '  <default remote="origin" revision="main" />\n'
        f'  <project name="{project_name}" path="{project_name}" revision="{rev}" />\n'
        "</manifest>\n"
    )
    out = parent / (filename or f"{project_name}.xml")
    out.write_text(xml)
    return out


def mk_mfst_xml(
    parent: pathlib.Path,
    fetch_url: str,
    plugin_name: str,
    revision: str,
    marketplaces_dir: pathlib.Path,
    *,
    filename: str | None = None,
) -> pathlib.Path:
    """Build an MK-style manifest XML with a <linkfile> into `marketplaces_dir`."""
    rev = xml_escape(revision)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_url}" />\n'
        '  <default remote="origin" revision="main" />\n'
        f'  <project name="{plugin_name}" path="{plugin_name}" revision="{rev}">\n'
        f'    <linkfile src="." dest="{marketplaces_dir}/{plugin_name}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )
    out = parent / (filename or f"{plugin_name}-mfst.xml")
    out.write_text(xml)
    return out


def pk_xml(
    parent: pathlib.Path,
    fetch_url: str,
    project_name: str,
    revision: str,
    *,
    filename: str | None = None,
) -> pathlib.Path:
    """Build a PK-style (plain package) manifest XML."""
    return mk_rx_xml(parent, fetch_url, project_name, revision, filename=filename)


# ---------------------------------------------------------------------------
# Kanonenv builder
# ---------------------------------------------------------------------------


def write_kanonenv(
    target_dir: pathlib.Path,
    sources: Iterable[tuple[str, str, str, str]],
    *,
    marketplace_install: str | None = None,
    extra_lines: Iterable[str] = (),
) -> pathlib.Path:
    """Write a `.kanon` file declaring `sources` as KANON_SOURCE_<name>_* triplets.

    Each `sources` entry: `(name, url, revision, path)`. `marketplace_install`
    appends `KANON_MARKETPLACE_INSTALL=<value>`. `extra_lines` are appended
    verbatim.
    """
    lines: list[str] = []
    for name, url, revision, path in sources:
        lines.append(f"KANON_SOURCE_{name}_URL={url}")
        lines.append(f"KANON_SOURCE_{name}_REVISION={revision}")
        lines.append(f"KANON_SOURCE_{name}_PATH={path}")
    if marketplace_install is not None:
        lines.append(f"KANON_MARKETPLACE_INSTALL={marketplace_install}")
    lines.extend(extra_lines)
    target = target_dir / ".kanon"
    target.write_text("\n".join(lines) + "\n")
    return target


# ---------------------------------------------------------------------------
# Lifecycle wrappers
# ---------------------------------------------------------------------------


def kanon_install(working_dir: pathlib.Path, **kwargs) -> subprocess.CompletedProcess:
    """Run `kanon install` from `working_dir`."""
    return run_kanon("install", cwd=working_dir, **kwargs)


def kanon_clean(working_dir: pathlib.Path, **kwargs) -> subprocess.CompletedProcess:
    """Run `kanon clean` from `working_dir`."""
    return run_kanon("clean", cwd=working_dir, **kwargs)


# ---------------------------------------------------------------------------
# Shared pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _scenarios_clear_session_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-test removal of session-scoped env vars set by other suites.

    The ``tests/functional/conftest.py::functional_repo_dir`` fixture is
    session-scoped + autouse and sets ``KANON_REPO_DIR`` to a fixture path
    whose ``.repo/manifests/default.xml`` declares
    ``<remote fetch="https://github.com/caylent-solutions/">``. Without
    explicit cleanup, this env var leaks into every scenario subprocess
    that runs after any functional test in the same pytest session, so
    ``kanon repo manifest --revision-as-tag`` reads the wrong manifest
    and KS/RX/UJ scenario assertions fail.

    Each scenario test runs against its own freshly-built repo checkout
    and never expects an inherited ``KANON_REPO_DIR``. The function-scope
    delenv complements the module-scope cleanup below so per-test
    subprocess invocations see a clean environment.
    """
    monkeypatch.delenv("KANON_REPO_DIR", raising=False)


@pytest.fixture(autouse=True, scope="module")
def _scenarios_clear_session_env_module() -> Iterator[None]:
    """Module-scope removal of cross-suite leaked env vars.

    Module-scoped fixtures (e.g. ``rp_ro_checkout`` in
    ``tests/scenarios/test_rp_*.py``) build their checkouts via
    ``kanon repo init`` BEFORE any function-scoped autouse fixture fires.
    If ``KANON_REPO_DIR`` is set when ``repo init`` runs, the init
    subprocess writes its ``.repo`` artefacts to the inherited path
    (the functional suite's tmp dir) instead of the per-fixture checkout
    dir, leaving ``<checkout>/.repo/manifest.xml`` missing and every
    downstream RP-* test failing with ``error parsing manifest ...
    [Errno 2] No such file or directory``.

    Removing ``KANON_REPO_DIR`` at module setup ensures the init
    subprocess writes to the expected per-test checkout dir. The
    original value is restored on module teardown so other suites'
    fixtures keep working.
    """
    previous = os.environ.pop("KANON_REPO_DIR", None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ["KANON_REPO_DIR"] = previous


@pytest.fixture()
def scenario_workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """A clean per-test workspace dir, isolated from other scenarios."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def claude_marketplaces_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Per-test CLAUDE_MARKETPLACES_DIR (where kanon symlinks plugins)."""
    d = tmp_path / "claude-marketplaces"
    d.mkdir()
    return d


__all__ = [
    "INTEGRATION_DOC",
    "all_scenario_ids",
    "scenario_block",
    "run_kanon",
    "run_git",
    "init_git_work_dir",
    "clone_as_bare",
    "make_bare_repo_with_tags",
    "make_plain_repo",
    "mk_plugin_repo",
    "cs_catalog_repo",
    "xml_escape",
    "mk_rx_xml",
    "mk_mfst_xml",
    "pk_xml",
    "write_kanonenv",
    "kanon_install",
    "kanon_clean",
    "scenario_workspace",
    "claude_marketplaces_dir",
]
