"""Unit tests for _check_completion_script_staleness in kanon_cli.commands.doctor.

Covers subcheck 9: completion-script staleness.

Parametrized cases:
- No static scripts installed: no finding emitted (returns empty list).
- Bash script in-sync: no finding for that shell.
- Bash script drifted: one warn finding naming the on-disk path and shell.
- Zsh script drifted: one warn finding for zsh.
- Both bash + zsh drifted: two warn findings, one per shell.
"""

from __future__ import annotations

import hashlib
import pathlib

import pytest


def _sha256_of(text: str) -> str:
    """Return the hex SHA-256 digest of a UTF-8 encoded string.

    Args:
        text: The string to hash.

    Returns:
        Lowercase hex SHA-256 digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_generator(output: str):
    """Return a callable that simulates generate_completion_script for a shell.

    The returned callable ignores its argument (shell name) and always returns
    ``output``.

    Args:
        output: The script text the generator should return.

    Returns:
        A callable(shell: str) -> str.
    """

    def _generator(shell: str) -> str:
        return output

    return _generator


@pytest.mark.unit
class TestCheckCompletionScriptStalenessNoScripts:
    """When no static completion scripts are installed, no findings are emitted."""

    def test_no_scripts_installed_returns_empty(self, tmp_path: pathlib.Path) -> None:
        """Returns an empty list when no search-path files exist on disk.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        findings = _check_completion_script_staleness(
            search_paths=[],
            completion_generator=_make_generator("# bash completion"),
        )

        assert findings == []

    def test_search_paths_with_missing_files_returns_empty(self, tmp_path: pathlib.Path) -> None:
        """Returns an empty list when search path files do not exist on disk.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        missing_bash = tmp_path / "bash_completion"
        missing_zsh = tmp_path / "_kanon"

        findings = _check_completion_script_staleness(
            search_paths=[
                ("bash", str(missing_bash)),
                ("zsh", str(missing_zsh)),
            ],
            completion_generator=_make_generator("# script"),
        )

        assert findings == []


@pytest.mark.unit
class TestCheckCompletionScriptStalenessInSync:
    """A static script whose hash matches the freshly generated script: no finding."""

    def test_bash_in_sync_returns_no_finding(self, tmp_path: pathlib.Path) -> None:
        """A bash script that matches the generated output produces no finding.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        script_content = "# kanon bash completion\n_kanon() { echo done; }\ncomplete -F _kanon kanon\n"
        script_file = tmp_path / "kanon_completion.bash"
        script_file.write_text(script_content, encoding="utf-8")

        findings = _check_completion_script_staleness(
            search_paths=[("bash", str(script_file))],
            completion_generator=_make_generator(script_content),
        )

        assert findings == []

    def test_zsh_in_sync_returns_no_finding(self, tmp_path: pathlib.Path) -> None:
        """A zsh script that matches the generated output produces no finding.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        script_content = "#compdef kanon\n_kanon() { compadd done; }\n"
        script_file = tmp_path / "_kanon"
        script_file.write_text(script_content, encoding="utf-8")

        findings = _check_completion_script_staleness(
            search_paths=[("zsh", str(script_file))],
            completion_generator=_make_generator(script_content),
        )

        assert findings == []

    def test_both_shells_in_sync_returns_empty(self, tmp_path: pathlib.Path) -> None:
        """Both bash and zsh scripts in-sync: no findings produced.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        bash_content = "# bash completion\n_kanon_bash() { echo done; }\n"
        zsh_content = "#compdef kanon\n_kanon_zsh() { echo done; }\n"

        bash_file = tmp_path / "kanon_completion.bash"
        zsh_file = tmp_path / "_kanon"
        bash_file.write_text(bash_content, encoding="utf-8")
        zsh_file.write_text(zsh_content, encoding="utf-8")

        def _generator(shell: str) -> str:
            if shell == "bash":
                return bash_content
            return zsh_content

        findings = _check_completion_script_staleness(
            search_paths=[
                ("bash", str(bash_file)),
                ("zsh", str(zsh_file)),
            ],
            completion_generator=_generator,
        )

        assert findings == []


@pytest.mark.unit
class TestCheckCompletionScriptStalenessDrift:
    """A static script whose hash differs from generated output: one warn per shell."""

    def test_bash_drifted_returns_one_warn_finding(self, tmp_path: pathlib.Path) -> None:
        """A drifted bash script produces exactly one warn-level finding.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        stale_content = "# OLD bash completion\n"
        fresh_content = "# NEW bash completion\n"
        script_file = tmp_path / "kanon_completion.bash"
        script_file.write_text(stale_content, encoding="utf-8")

        findings = _check_completion_script_staleness(
            search_paths=[("bash", str(script_file))],
            completion_generator=_make_generator(fresh_content),
        )

        assert len(findings) == 1
        assert findings[0].kind == "warn"

    def test_bash_drifted_finding_names_path(self, tmp_path: pathlib.Path) -> None:
        """The drift warning names the on-disk script path.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        stale_content = "# OLD bash completion\n"
        fresh_content = "# NEW bash completion\n"
        script_file = tmp_path / "kanon_completion.bash"
        script_file.write_text(stale_content, encoding="utf-8")

        findings = _check_completion_script_staleness(
            search_paths=[("bash", str(script_file))],
            completion_generator=_make_generator(fresh_content),
        )

        assert str(script_file) in findings[0].message, (
            f"Expected the on-disk path {str(script_file)!r} to appear in the finding message "
            f"but got: {findings[0].message!r}"
        )

    def test_bash_drifted_finding_names_shell(self, tmp_path: pathlib.Path) -> None:
        """The drift warning names the shell (bash).

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        stale_content = "# OLD\n"
        fresh_content = "# NEW\n"
        script_file = tmp_path / "kanon_completion.bash"
        script_file.write_text(stale_content, encoding="utf-8")

        findings = _check_completion_script_staleness(
            search_paths=[("bash", str(script_file))],
            completion_generator=_make_generator(fresh_content),
        )

        assert "bash" in findings[0].message, (
            f"Expected shell name 'bash' to appear in the finding message but got: {findings[0].message!r}"
        )

    def test_zsh_drifted_returns_one_warn_finding(self, tmp_path: pathlib.Path) -> None:
        """A drifted zsh script produces exactly one warn-level finding.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        stale_content = "# OLD zsh completion\n"
        fresh_content = "# NEW zsh completion\n"
        script_file = tmp_path / "_kanon"
        script_file.write_text(stale_content, encoding="utf-8")

        findings = _check_completion_script_staleness(
            search_paths=[("zsh", str(script_file))],
            completion_generator=_make_generator(fresh_content),
        )

        assert len(findings) == 1
        assert findings[0].kind == "warn"

    def test_zsh_drifted_finding_names_shell(self, tmp_path: pathlib.Path) -> None:
        """The drift warning for a zsh script names the shell as 'zsh'.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        stale_content = "# OLD\n"
        fresh_content = "# NEW\n"
        script_file = tmp_path / "_kanon"
        script_file.write_text(stale_content, encoding="utf-8")

        findings = _check_completion_script_staleness(
            search_paths=[("zsh", str(script_file))],
            completion_generator=_make_generator(fresh_content),
        )

        assert "zsh" in findings[0].message, (
            f"Expected shell name 'zsh' to appear in finding message but got: {findings[0].message!r}"
        )


@pytest.mark.unit
class TestCheckCompletionScriptStalenessMultiShell:
    """Multiple shells with drifted scripts: one warning per drifted shell."""

    def test_both_drifted_returns_two_findings(self, tmp_path: pathlib.Path) -> None:
        """When both bash and zsh scripts are drifted, two warn findings are returned.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        bash_file = tmp_path / "kanon_completion.bash"
        zsh_file = tmp_path / "_kanon"
        bash_file.write_text("# stale bash\n", encoding="utf-8")
        zsh_file.write_text("# stale zsh\n", encoding="utf-8")

        def _generator(shell: str) -> str:
            return f"# fresh {shell}\n"

        findings = _check_completion_script_staleness(
            search_paths=[
                ("bash", str(bash_file)),
                ("zsh", str(zsh_file)),
            ],
            completion_generator=_generator,
        )

        assert len(findings) == 2
        assert all(f.kind == "warn" for f in findings)

    def test_both_drifted_each_finding_names_its_shell(self, tmp_path: pathlib.Path) -> None:
        """Each finding in a multi-shell drift report names its respective shell.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        bash_file = tmp_path / "kanon_completion.bash"
        zsh_file = tmp_path / "_kanon"
        bash_file.write_text("# stale bash\n", encoding="utf-8")
        zsh_file.write_text("# stale zsh\n", encoding="utf-8")

        def _generator(shell: str) -> str:
            return f"# fresh {shell}\n"

        findings = _check_completion_script_staleness(
            search_paths=[
                ("bash", str(bash_file)),
                ("zsh", str(zsh_file)),
            ],
            completion_generator=_generator,
        )

        messages = [f.message for f in findings]
        assert any("bash" in m for m in messages), "Expected a finding mentioning 'bash'"
        assert any("zsh" in m for m in messages), "Expected a finding mentioning 'zsh'"

    def test_one_drifted_one_in_sync_returns_one_finding(self, tmp_path: pathlib.Path) -> None:
        """When bash is drifted and zsh is in-sync, only one finding is returned.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        bash_file = tmp_path / "kanon_completion.bash"
        zsh_file = tmp_path / "_kanon"
        bash_file.write_text("# stale bash\n", encoding="utf-8")
        fresh_zsh = "# fresh zsh\n"
        zsh_file.write_text(fresh_zsh, encoding="utf-8")

        def _generator(shell: str) -> str:
            if shell == "bash":
                return "# fresh bash\n"
            return fresh_zsh

        findings = _check_completion_script_staleness(
            search_paths=[
                ("bash", str(bash_file)),
                ("zsh", str(zsh_file)),
            ],
            completion_generator=_generator,
        )

        assert len(findings) == 1
        assert "bash" in findings[0].message

    def test_drifted_finding_code_is_stale_completion_script(self, tmp_path: pathlib.Path) -> None:
        """DoctorFinding.code is STALE_COMPLETION_SCRIPT for each drift finding.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness

        script_file = tmp_path / "kanon_completion.bash"
        script_file.write_text("# stale\n", encoding="utf-8")

        findings = _check_completion_script_staleness(
            search_paths=[("bash", str(script_file))],
            completion_generator=_make_generator("# fresh\n"),
        )

        assert len(findings) == 1
        assert findings[0].code == "STALE_COMPLETION_SCRIPT"


@pytest.mark.unit
class TestRunCompletionSubchecks:
    """_run_completion_subchecks invokes subcheck 7 and 9 and prints findings to stderr."""

    def test_run_completion_subchecks_prints_stale_finding_to_stderr(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """_run_completion_subchecks with a stale script emits a WARN to stderr.

        Args:
            tmp_path: Pytest temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest capture fixture.
        """
        from kanon_cli.commands.doctor import _check_completion_script_staleness, _run_completion_subchecks

        stale_content = "# stale\n"
        fresh_content = "# fresh\n"
        script_file = tmp_path / "kanon.bash"
        script_file.write_text(stale_content, encoding="utf-8")

        findings = _check_completion_script_staleness(
            search_paths=[("bash", str(script_file))],
            completion_generator=_make_generator(fresh_content),
        )
        assert len(findings) == 1

        import kanon_cli.commands.doctor as doctor_module

        original_paths = doctor_module.KANON_STATIC_COMPLETION_SEARCH_PATHS
        monkeypatch.setattr(
            doctor_module,
            "KANON_STATIC_COMPLETION_SEARCH_PATHS",
            (("bash", str(script_file)),),
        )
        try:
            _run_completion_subchecks(completion_generator=_make_generator(fresh_content))
        finally:
            monkeypatch.setattr(
                doctor_module,
                "KANON_STATIC_COMPLETION_SEARCH_PATHS",
                original_paths,
            )

        captured = capsys.readouterr()
        assert "WARN:" in captured.err
        assert "bash" in captured.err

    def test_run_completion_subchecks_no_generator_skips_staleness(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """_run_completion_subchecks with no generator emits nothing for staleness.

        Args:
            capsys: Pytest capture fixture.
        """
        from kanon_cli.commands.doctor import _run_completion_subchecks

        _run_completion_subchecks(completion_generator=None)

        captured = capsys.readouterr()

        assert "STALE" not in captured.err
