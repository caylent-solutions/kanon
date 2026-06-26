"""J5 functional journey: kanon marketplace enable/disable/status (FR-17, FR-18).

Drives the real ``kanon marketplace`` CLI (via subprocess) through the
enable/disable/status arc against a synthetic ``.kanon`` file, asserting at each
step that:

- ``enable`` writes ``KANON_SOURCE_<alias>_MARKETPLACE=true``;
- ``disable`` removes the line entirely (absence is the canonical false; no
  ``=false`` is ever written);
- ``status`` renders an explicit ``=false`` and an absent line identically (both
  "disabled");
- ``.kanon.lock`` is never created or modified by any of the three operations
  (the command edits only ``.kanon`` -- spec Section 4.4 / Section 10.4 J5).

Spec reference: ``specs/kanon-refinements.md`` Section 10.4 J5, Section 4.4,
FR-17, FR-18.
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon


_ALIAS = "aws_control_tower"


_FALSE_ALIAS = "explicit_false"


_LOCK_SENTINEL = "SENTINEL .kanon.lock -- must not be touched by marketplace\n"


def _block(alias: str, *, marketplace: str | None) -> list[str]:
    """Return the .kanon lines for one complete alias block.

    Args:
        alias: The canonical source alias.
        marketplace: ``None`` for no ``_MARKETPLACE`` line, else the literal value
            (``"true"`` / ``"false"``).

    Returns:
        The block lines (no trailing newlines).
    """
    lines = [
        f"KANON_SOURCE_{alias}_URL=https://example.com/org/{alias}.git",
        f"KANON_SOURCE_{alias}_REF=1.0.0",
        f"KANON_SOURCE_{alias}_PATH=repo-specs/{alias}-marketplace.xml",
        f"KANON_SOURCE_{alias}_NAME={alias}",
        f"KANON_SOURCE_{alias}_GITBASE=https://example.com/org",
    ]
    if marketplace is not None:
        lines.append(f"KANON_SOURCE_{alias}_MARKETPLACE={marketplace}")
    return lines


@pytest.fixture()
def journey_workspace(tmp_path: pathlib.Path) -> "tuple[pathlib.Path, pathlib.Path, pathlib.Path]":
    """Create a workspace with a seeded ``.kanon`` and a sentinel ``.kanon.lock``.

    Args:
        tmp_path: pytest-provided temporary directory.

    Returns:
        A 3-tuple ``(workspace, kanon_file, lock_file)``.
    """
    workspace = tmp_path / "project"
    workspace.mkdir()
    kanon_file = workspace / ".kanon"
    body = _block(_ALIAS, marketplace="true") + [""] + _block(_FALSE_ALIAS, marketplace="false")
    kanon_file.write_text("\n".join(body) + "\n", encoding="utf-8")
    kanon_file.chmod(0o600)

    lock_file = workspace / ".kanon.lock"
    lock_file.write_text(_LOCK_SENTINEL, encoding="utf-8")
    return workspace, kanon_file, lock_file


@pytest.mark.functional
def test_marketplace_enable_disable_status_journey(
    journey_workspace: "tuple[pathlib.Path, pathlib.Path, pathlib.Path]",
) -> None:
    """Drive enable -> disable -> status and assert .kanon.lock is untouched."""
    workspace, kanon_file, lock_file = journey_workspace

    status_initial = _run_kanon("marketplace", "status", "--all", cwd=workspace)
    assert status_initial.returncode == 0, status_initial.stderr
    initial_row = next(line for line in status_initial.stdout.splitlines() if line.startswith(_ALIAS))
    assert "claude-marketplace" in initial_row
    assert initial_row.split()[-1] == "enabled"

    false_row = next(line for line in status_initial.stdout.splitlines() if line.startswith(_FALSE_ALIAS))
    assert false_row.split()[-1] == "disabled"
    assert lock_file.read_text(encoding="utf-8") == _LOCK_SENTINEL

    disable_result = _run_kanon("marketplace", "disable", _ALIAS, cwd=workspace)
    assert disable_result.returncode == 0, disable_result.stderr
    after_disable = kanon_file.read_text(encoding="utf-8")
    assert f"KANON_SOURCE_{_ALIAS}_MARKETPLACE" not in after_disable

    assert f"KANON_SOURCE_{_ALIAS}_MARKETPLACE=false" not in after_disable
    assert lock_file.read_text(encoding="utf-8") == _LOCK_SENTINEL

    status_after_disable = _run_kanon("marketplace", "status", "--all", cwd=workspace)
    assert status_after_disable.returncode == 0, status_after_disable.stderr
    absent_row = next(line for line in status_after_disable.stdout.splitlines() if line.startswith(_ALIAS))
    explicit_false_row = next(
        line for line in status_after_disable.stdout.splitlines() if line.startswith(_FALSE_ALIAS)
    )
    assert absent_row.split()[-1] == "disabled"
    assert explicit_false_row.split()[-1] == "disabled"

    enable_result = _run_kanon("marketplace", "enable", _FALSE_ALIAS, cwd=workspace)
    assert enable_result.returncode == 0, enable_result.stderr
    after_enable = kanon_file.read_text(encoding="utf-8")
    assert f"KANON_SOURCE_{_FALSE_ALIAS}_MARKETPLACE=true" in after_enable
    assert f"KANON_SOURCE_{_FALSE_ALIAS}_MARKETPLACE=false" not in after_enable
    assert lock_file.read_text(encoding="utf-8") == _LOCK_SENTINEL

    status_after_enable = _run_kanon("marketplace", "status", "--all", cwd=workspace)
    assert status_after_enable.returncode == 0, status_after_enable.stderr
    enabled_row = next(line for line in status_after_enable.stdout.splitlines() if line.startswith(_FALSE_ALIAS))
    assert enabled_row.split()[-1] == "enabled"

    assert lock_file.read_text(encoding="utf-8") == _LOCK_SENTINEL


@pytest.mark.functional
def test_marketplace_help_advertises_subcommands(tmp_path: pathlib.Path) -> None:
    """``kanon marketplace --help`` advertises enable | disable | status (AC-26)."""
    result = _run_kanon("marketplace", "--help", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    for token in ("enable", "disable", "status"):
        assert token in result.stdout


_MARKETPLACES_DIR_HEADER = "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces"


@pytest.mark.functional
def test_marketplace_enable_adds_header_and_disable_prunes_it(tmp_path: pathlib.Path) -> None:
    """enable inserts the CLAUDE_MARKETPLACES_DIR header; disable of the last marketplace prunes it (Feature A)."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    kanon_file = workspace / ".kanon"
    kanon_file.write_text("\n".join(_block(_ALIAS, marketplace="false")) + "\n", encoding="utf-8")

    assert "CLAUDE_MARKETPLACES_DIR" not in kanon_file.read_text(encoding="utf-8")

    enable_result = _run_kanon("marketplace", "enable", _ALIAS, cwd=workspace)
    assert enable_result.returncode == 0, enable_result.stderr
    after_enable = kanon_file.read_text(encoding="utf-8")
    assert after_enable.count(_MARKETPLACES_DIR_HEADER) == 1, (
        f"enable must auto-insert the marketplace header exactly once; got:\n{after_enable}"
    )
    assert f"KANON_SOURCE_{_ALIAS}_MARKETPLACE=true" in after_enable
    assert not (workspace / ".kanon-data").exists(), (
        "kanon marketplace enable must not create a .kanon-data lock dir in the project CWD"
    )

    disable_result = _run_kanon("marketplace", "disable", _ALIAS, cwd=workspace)
    assert disable_result.returncode == 0, disable_result.stderr
    after_disable = kanon_file.read_text(encoding="utf-8")
    assert "CLAUDE_MARKETPLACES_DIR" not in after_disable, (
        f"disable of the last marketplace must prune the header; got:\n{after_disable}"
    )


@pytest.mark.functional
def test_marketplace_disable_keeps_header_when_another_marketplace_remains(tmp_path: pathlib.Path) -> None:
    """Disabling one of two enabled marketplaces keeps the header (one remains) (Feature A)."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    kanon_file = workspace / ".kanon"
    second_alias = "second_market"
    body = _block(_ALIAS, marketplace="true") + [""] + _block(second_alias, marketplace="true")
    kanon_file.write_text(_MARKETPLACES_DIR_HEADER + "\n" + "\n".join(body) + "\n", encoding="utf-8")

    disable_result = _run_kanon("marketplace", "disable", _ALIAS, cwd=workspace)
    assert disable_result.returncode == 0, disable_result.stderr
    after_disable = kanon_file.read_text(encoding="utf-8")
    assert f"KANON_SOURCE_{_ALIAS}_MARKETPLACE" not in after_disable
    assert f"KANON_SOURCE_{second_alias}_MARKETPLACE=true" in after_disable
    assert after_disable.count(_MARKETPLACES_DIR_HEADER) == 1, (
        f"the header must remain while another marketplace is still enabled; got:\n{after_disable}"
    )
