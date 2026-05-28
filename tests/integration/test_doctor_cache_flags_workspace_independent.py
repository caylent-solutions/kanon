"""Integration tests for 'kanon doctor --refresh-completion-cache' and
'kanon doctor --prune-cache' in a workspace-free working directory.

DEFECT-013: Both flags error with "no kanon workspace in .: '.kanon' not
found" when the cwd contains no .kanon file, even though the cache operations
do not require a workspace. These tests assert the expected post-fix contract
(exit 0, info-line emitted, no workspace-error on stderr) and FAIL against
the unfixed feat branch HEAD.

Autouse fixtures from tests/integration/conftest.py (spec sec 3.2) are
inherited automatically: _mock_resolve_ref_to_sha, _mock_check_sha_reachable,
_auto_create_manifest_on_walk, _default_allow_insecure_remotes.
"""

from __future__ import annotations

import argparse
import pathlib
import typing

import pytest

from kanon_cli.commands.doctor import DoctorArgsTypeError, run_doctor


# ---------------------------------------------------------------------------
# Parametrized fixture data
# ---------------------------------------------------------------------------

_CACHE_FLAG_PARAMS = [
    pytest.param(
        {"refresh_completion_cache": True, "prune_cache": False},
        "Completion cache refreshed:",
        id="refresh_completion_cache",
    ),
    pytest.param(
        {"prune_cache": True, "refresh_completion_cache": False},
        "Cache pruned:",
        id="prune_cache",
    ),
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _build_args(**overrides: object) -> argparse.Namespace:
    """Build a minimal argparse.Namespace for doctor_command.

    Fills every flag that doctor_command reads with a safe default and then
    applies the caller-supplied overrides.

    Args:
        **overrides: Attribute values that override the defaults.

    Returns:
        A Namespace instance ready to pass to run_doctor.
    """
    defaults: dict[str, object] = {
        "kanon_file": None,
        "lock_file": None,
        "strict_drift": False,
        "no_color": False,
        "refresh_completion_cache": False,
        "prune_cache": False,
        "catalog_source": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDoctorCacheFlagsWorkspaceIndependent:
    """Doctor cache flags must succeed in a workspace-free cwd.

    Both --refresh-completion-cache and --prune-cache perform cache operations
    that are independent of the .kanon workspace. When only these flags are
    active, the command must exit 0, emit an info-line about the cache action,
    and not raise the "no kanon workspace" diagnostic.
    """

    @pytest.mark.parametrize("flag_kwargs,expected_message", _CACHE_FLAG_PARAMS)
    def test_refresh_completion_cache_succeeds_in_empty_cwd(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        flag_kwargs: dict[str, object],
        expected_message: str,
    ) -> None:
        """Cache flag exits 0 and emits info-line in an empty cwd (no .kanon).

        Parameterised over --refresh-completion-cache and --prune-cache.
        _print_finding emits 'INFO: {finding.message}' to stderr; assertions
        check for the message substring (e.g. 'Completion cache refreshed:'
        or 'Cache pruned:') rather than the internal finding.code field value.

        Args:
            tmp_path: Pytest-provided temporary directory (no .kanon present).
            monkeypatch: Pytest monkeypatch fixture for env and cwd isolation.
            capsys: Pytest capture fixture to inspect stdout and stderr.
            flag_kwargs: Dict of flag keyword arguments for _build_args.
            expected_message: Substring of the info-line message emitted by
                _print_finding that must appear in combined output.
        """
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(mode=0o700)

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("KANON_CACHE_DIR", str(cache_dir))

        args = _build_args(**flag_kwargs)
        exit_code = run_doctor(args)

        captured = capsys.readouterr()
        combined_output = captured.out + captured.err

        assert exit_code == 0, (
            f"Expected exit 0 for cache-only flag in workspace-free cwd; "
            f"got {exit_code}.\nstdout: {captured.out!r}\nstderr: {captured.err!r}"
        )
        assert expected_message in combined_output, (
            f"Expected info-line message '{expected_message}' in output; "
            f"got:\nstdout: {captured.out!r}\nstderr: {captured.err!r}"
        )
        assert "no kanon workspace" not in captured.err, (
            f"Expected no workspace-not-found diagnostic in stderr; got:\nstderr: {captured.err!r}"
        )

    @pytest.mark.parametrize("flag_kwargs,expected_message", _CACHE_FLAG_PARAMS)
    def test_prune_cache_succeeds_in_empty_cwd(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        flag_kwargs: dict[str, object],
        expected_message: str,
    ) -> None:
        """Cache flag exits 0 and does not emit workspace diagnostic (no .kanon).

        Mirrors test_refresh_completion_cache_succeeds_in_empty_cwd to provide
        an independently-named test method per AC-FUNC-001 while sharing the
        same parametrize coverage. _print_finding emits 'INFO: {finding.message}'
        to stderr; assertions check for the message substring rather than the
        internal finding.code field value.

        Args:
            tmp_path: Pytest-provided temporary directory (no .kanon present).
            monkeypatch: Pytest monkeypatch fixture for env and cwd isolation.
            capsys: Pytest capture fixture to inspect stdout and stderr.
            flag_kwargs: Dict of flag keyword arguments for _build_args.
            expected_message: Substring of the info-line message emitted by
                _print_finding that must appear in combined output.
        """
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(mode=0o700)

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("KANON_CACHE_DIR", str(cache_dir))

        args = _build_args(**flag_kwargs)
        exit_code = run_doctor(args)

        captured = capsys.readouterr()
        combined_output = captured.out + captured.err

        assert exit_code == 0, (
            f"Expected exit 0 for cache-only flag in workspace-free cwd; "
            f"got {exit_code}.\nstdout: {captured.out!r}\nstderr: {captured.err!r}"
        )
        assert expected_message in combined_output, (
            f"Expected info-line message '{expected_message}' in output; "
            f"got:\nstdout: {captured.out!r}\nstderr: {captured.err!r}"
        )
        assert "no kanon workspace" not in captured.err, (
            f"Expected no workspace-not-found diagnostic in stderr; got:\nstderr: {captured.err!r}"
        )


# ---------------------------------------------------------------------------
# DoctorArgsTypeError contract
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDoctorArgsTypeError:
    """doctor_command raises DoctorArgsTypeError when args is not a Namespace.

    This covers the defensive type-guard introduced by DEFECT-013 fix in
    doctor_command. The exception carries the received type so callers can
    emit a structured error message.
    """

    @pytest.mark.parametrize(
        "bad_args",
        [
            pytest.param({}, id="dict"),
            pytest.param(object(), id="object"),
            pytest.param("string", id="str"),
        ],
    )
    def test_non_namespace_args_raises_doctor_args_type_error(
        self,
        bad_args: object,
    ) -> None:
        """Non-Namespace args raises DoctorArgsTypeError with received type.

        Args:
            bad_args: A non-Namespace object that must trigger the type guard.
        """
        with pytest.raises(DoctorArgsTypeError) as exc_info:
            run_doctor(typing.cast(argparse.Namespace, bad_args))
        assert exc_info.value.received_type is type(bad_args), (
            f"Expected received_type={type(bad_args)!r}; got {exc_info.value.received_type!r}"
        )
        assert "argparse.Namespace" in str(exc_info.value), (
            f"Expected 'argparse.Namespace' in error message; got: {str(exc_info.value)!r}"
        )
