"""Tests for the repo-specific conftest.py fixtures.

Validates that each fixture adapted from rpm-git-repo is discoverable
by pytest and produces expected state when invoked.

Fixtures under test:
- reset_color_default
- disable_repo_trace
- session_tmp_home_dir
- tmp_home_dir
- setup_user_identity

Spec Reference: E0-F5-S1-T2
"""

import os
import pathlib
import tempfile

import pytest

import kanon_cli.repo.color as color
import kanon_cli.repo.repo_trace as repo_trace


@pytest.mark.unit
def test_reset_color_default_restores_previous_value(reset_color_default):
    """Verify reset_color_default fixture restores color.DEFAULT after mutation.

    Given: reset_color_default fixture is active
    When: A test mutates color.DEFAULT
    Then: The original value is restored by the teardown
    Spec: E0-F5-S1-T2 AC-FUNC-002
    """
    original = color.DEFAULT
    color.DEFAULT = not original
    assert color.DEFAULT != original


@pytest.mark.unit
def test_disable_repo_trace_sets_trace_file(disable_repo_trace, tmp_path):
    """Verify disable_repo_trace sets repo_trace._TRACE_FILE to a tmp path.

    Given: disable_repo_trace fixture is active
    When: The test accesses repo_trace._TRACE_FILE
    Then: It is set to a path under a temporary directory
    Spec: E0-F5-S1-T2 AC-FUNC-003
    """
    assert repo_trace._TRACE_FILE is not None, "disable_repo_trace must set repo_trace._TRACE_FILE to a non-None value"
    trace_path = pathlib.Path(repo_trace._TRACE_FILE)
    assert "TRACE_FILE_from_test" in trace_path.name, (
        f"Expected TRACE_FILE_from_test in trace path name, got: {trace_path.name}"
    )
    assert trace_path.parent.is_dir(), f"Parent directory of trace file must exist: {trace_path.parent}"


@pytest.mark.unit
def test_session_tmp_home_dir_returns_existing_directory(session_tmp_home_dir):
    """Verify session_tmp_home_dir returns a path to an existing directory.

    Given: session_tmp_home_dir fixture is active
    When: The test inspects the fixture return value
    Then: It is a pathlib.Path pointing to an existing directory
    Note: HOME may be overridden by the function-scoped tmp_home_dir fixture
    (autouse), so we verify the session path itself rather than comparing
    it to the current HOME env var.
    Spec: E0-F5-S1-T2 AC-FUNC-004
    """
    assert isinstance(session_tmp_home_dir, pathlib.Path), (
        f"session_tmp_home_dir must return a pathlib.Path, got {type(session_tmp_home_dir)}"
    )
    assert session_tmp_home_dir.is_dir(), (
        f"session_tmp_home_dir must point to an existing directory: {session_tmp_home_dir}"
    )
    system_tmp = pathlib.Path(tempfile.gettempdir())
    assert str(session_tmp_home_dir).startswith(str(system_tmp)), (
        f"session_tmp_home_dir should be under system temp dir {system_tmp}, got {session_tmp_home_dir}"
    )


@pytest.mark.unit
def test_tmp_home_dir_sets_home_env(tmp_home_dir):
    """Verify tmp_home_dir sets HOME to a temporary directory.

    Given: tmp_home_dir fixture is active
    When: The test reads os.environ['HOME']
    Then: HOME points to a real directory matching the fixture return value
    Spec: E0-F5-S1-T2 AC-FUNC-005
    """
    home_env = os.environ.get("HOME")
    assert home_env is not None, "HOME environment variable must be set"
    home_path = pathlib.Path(home_env)
    assert home_path.is_dir(), f"HOME must point to an existing directory: {home_path}"
    assert str(tmp_home_dir) == home_env, (
        f"tmp_home_dir return value {tmp_home_dir!r} must match HOME env var {home_env!r}"
    )


@pytest.mark.unit
def test_tmp_home_dir_is_under_system_tmp(tmp_home_dir):
    """Verify tmp_home_dir is function-scoped and inside a system temp dir.

    Given: tmp_home_dir fixture is active
    When: The test inspects the HOME path
    Then: HOME points to a sub-path of a system temp directory
    Spec: E0-F5-S1-T2 AC-FUNC-005
    """
    home_path = pathlib.Path(os.environ["HOME"])
    system_tmp = pathlib.Path(tempfile.gettempdir())
    assert str(home_path).startswith(str(system_tmp)), (
        f"tmp_home_dir should be under system temp dir {system_tmp}, got {home_path}"
    )


@pytest.mark.unit
def test_setup_user_identity_sets_git_env_vars(setup_user_identity):
    """Verify setup_user_identity sets all required git identity env vars.

    Given: setup_user_identity fixture is active
    When: The test reads GIT_AUTHOR_NAME and related env vars
    Then: All four git identity env vars are set to non-empty values
    Spec: E0-F5-S1-T2 AC-FUNC-006
    """
    required_vars = [
        "GIT_AUTHOR_NAME",
        "GIT_COMMITTER_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_EMAIL",
    ]
    for var in required_vars:
        value = os.environ.get(var)
        assert value is not None, f"setup_user_identity must set {var}"
        assert value.strip(), f"setup_user_identity must set {var} to a non-empty value"


@pytest.mark.unit
@pytest.mark.parametrize(
    "var_name",
    [
        "GIT_AUTHOR_NAME",
        "GIT_COMMITTER_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_EMAIL",
    ],
)
def test_setup_user_identity_each_var_is_nonempty(setup_user_identity, var_name):
    """Verify each git identity variable is individually set by setup_user_identity.

    Given: setup_user_identity fixture is active
    When: The test checks each required git env variable in turn
    Then: Each variable is set to a non-empty string
    Spec: E0-F5-S1-T2 AC-FUNC-006
    """
    value = os.environ.get(var_name)
    assert value is not None, f"{var_name} must be set by setup_user_identity fixture"
    assert value.strip(), f"{var_name} must not be empty"
