"""Unit tests for the stdlib no-comments check (tools/lint/check_no_comments.py).

These tests pin the Section 4.1 / Section 10 semantics of the no-comments gate
that the python-comment-purge (E18) depends on:

- A real ``#`` comment is an offense (non-zero exit, offender on stderr).
- A line-1 shebang and a PEP 263 encoding cookie (line 1 or 2) are the only two
  allowed exceptions; docstrings and ``#`` inside string literals are never
  flagged (an intrinsic property of ``tokenize`` token types).
- The vendored ``src/kanon_cli/repo`` subtree is excluded by default and
  ``--exclude`` replaces the default exclusion set.
- Directory arguments are walked recursively for ``*.py`` files.
- A missing path and an untokenizable file both fail fast with a clear stderr
  message and a non-zero exit.
- Multiple offenders are reported sorted by (path, line) with a summary count.

Fixtures are built dynamically under ``tmp_path`` (input-driven, no hard-coded
repository paths). The check is invoked both in-process (the importable
``run_check`` entry function) and via subprocess (the real CLI exit code).
"""

import importlib.util
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).parents[2]
CHECK_PATH = REPO_ROOT / "tools" / "lint" / "check_no_comments.py"

SUCCESS_LINE = "check_no_comments: no disallowed comments found"


def _load_check_module():
    """Import the check module by file path (it lives outside the package tree)."""
    spec = importlib.util.spec_from_file_location("check_no_comments", CHECK_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load check module from {CHECK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_module = _load_check_module()


def _run_in_process(capsys, argv):
    """Invoke the importable entry function and capture (exit_code, out, err)."""
    exit_code = check_module.run_check(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _run_subprocess(argv):
    """Invoke the CLI as a subprocess to assert the real process exit code."""
    return subprocess.run(
        [sys.executable, str(CHECK_PATH), *argv],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.unit
def test_check_module_file_exists():
    """The check module is a net-new file under tools/lint/."""
    assert CHECK_PATH.is_file(), f"missing check module: {CHECK_PATH}"


@pytest.mark.unit
def test_forbidden_comment_fails_in_process(tmp_path, capsys):
    """Case 1: a real `#` comment is an offense; offender output names line+text."""
    target = tmp_path / "offender.py"
    target.write_text("x = 1  # nope\n", encoding="utf-8")

    exit_code, out, err = _run_in_process(capsys, [str(target)])

    assert exit_code != 0
    assert "# nope" in err
    assert f"{target}:1:" in err
    assert SUCCESS_LINE not in out


@pytest.mark.unit
def test_forbidden_comment_fails_via_subprocess(tmp_path):
    """Case 1 (CLI): the subprocess exits non-zero on a real `#` comment."""
    target = tmp_path / "offender.py"
    target.write_text("y = 2  # forbidden\n", encoding="utf-8")

    result = _run_subprocess([str(target)])

    assert result.returncode != 0
    assert "# forbidden" in result.stderr
    assert f"{target}:1:" in result.stderr


@pytest.mark.unit
def test_comment_free_fixture_passes(tmp_path, capsys):
    """Case 2: shebang + encoding cookie + docstring + string-`#` is clean (exit 0)."""
    target = tmp_path / "clean.py"
    target.write_text(
        "#!/usr/bin/env python3\n"
        "# -*- coding: utf-8 -*-\n"
        '"""Module docstring -- not a comment."""\n'
        'URL = "https://example.com/#frag"\n',
        encoding="utf-8",
    )

    exit_code, out, err = _run_in_process(capsys, [str(target)])

    assert exit_code == 0
    assert SUCCESS_LINE in out
    assert err == ""


@pytest.mark.unit
@pytest.mark.parametrize(
    ("line1", "expect_offense"),
    [
        ("#!/usr/bin/env python3", False),
        ("# header", True),
    ],
    ids=["shebang-allowed", "non-shebang-line1-offense"],
)
def test_line1_shebang_vs_comment(tmp_path, capsys, line1, expect_offense):
    """Case 3: a line-1 shebang is allowed; a non-shebang `#` on line 1 is an offense."""
    target = tmp_path / "first_line.py"
    target.write_text(f"{line1}\nx = 1\n", encoding="utf-8")

    exit_code, _out, err = _run_in_process(capsys, [str(target)])

    if expect_offense:
        assert exit_code != 0
        assert f"{target}:1:" in err
    else:
        assert exit_code == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cookie_line", "expect_offense"),
    [
        (1, False),
        (2, False),
        (3, True),
    ],
    ids=["cookie-line1-allowed", "cookie-line2-allowed", "cookie-line3-offense"],
)
def test_encoding_cookie_line_window(tmp_path, capsys, cookie_line, expect_offense):
    """Case 4: an encoding cookie on line 1/2 is allowed; on line 3 it is an offense."""
    cookie = "# -*- coding: utf-8 -*-"
    lines = ["x = 1", "y = 2", "z = 3"]
    lines.insert(cookie_line - 1, cookie)
    target = tmp_path / "cookie.py"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    exit_code, _out, err = _run_in_process(capsys, [str(target)])

    if expect_offense:
        assert exit_code != 0
        assert f"{target}:{cookie_line}:" in err
    else:
        assert exit_code == 0


@pytest.mark.unit
def test_vendored_exclusion_skips_offender(tmp_path, capsys):
    """Case 5: a `#` comment under an excluded prefix is not flagged."""
    vendored_root = tmp_path / "src" / "kanon_cli" / "repo"
    vendored_root.mkdir(parents=True)
    (vendored_root / "vendored.py").write_text("a = 1  # vendored comment\n", encoding="utf-8")

    scan_root = tmp_path / "src" / "kanon_cli"
    exclude_prefix = scan_root / "repo"

    exit_code, out, _err = _run_in_process(
        capsys,
        [str(scan_root), "--exclude", str(exclude_prefix)],
    )

    assert exit_code == 0
    assert SUCCESS_LINE in out


@pytest.mark.unit
def test_vendored_file_flagged_without_exclusion(tmp_path, capsys):
    """Control for case 5: the same file IS flagged when not excluded."""
    vendored_root = tmp_path / "src" / "kanon_cli" / "repo"
    vendored_root.mkdir(parents=True)
    offender = vendored_root / "vendored.py"
    offender.write_text("a = 1  # vendored comment\n", encoding="utf-8")

    scan_root = tmp_path / "src" / "kanon_cli"

    exit_code, _out, err = _run_in_process(capsys, [str(scan_root)])

    assert exit_code != 0
    assert "# vendored comment" in err


@pytest.mark.unit
def test_directory_recursion_reports_nested(tmp_path, capsys):
    """Case 6: a directory argument is walked recursively for nested offenders."""
    nested = tmp_path / "pkg" / "sub"
    nested.mkdir(parents=True)
    nested_offender = nested / "deep.py"
    nested_offender.write_text("value = 3  # deep comment\n", encoding="utf-8")
    (tmp_path / "pkg" / "clean.py").write_text('"""ok"""\nx = 1\n', encoding="utf-8")

    exit_code, _out, err = _run_in_process(capsys, [str(tmp_path / "pkg")])

    assert exit_code != 0
    assert f"{nested_offender}:1:" in err
    assert "# deep comment" in err


@pytest.mark.unit
def test_pycache_dir_skipped_during_walk(tmp_path, capsys):
    """A `#` inside a canonical generated dir (__pycache__) is never scanned."""
    cache_dir = tmp_path / "pkg" / "__pycache__"
    cache_dir.mkdir(parents=True)
    (cache_dir / "stale.py").write_text("g = 1  # generated comment\n", encoding="utf-8")
    (tmp_path / "pkg" / "real.py").write_text('"""ok"""\n', encoding="utf-8")

    exit_code, out, _err = _run_in_process(capsys, [str(tmp_path / "pkg")])

    assert exit_code == 0
    assert SUCCESS_LINE in out


@pytest.mark.unit
def test_missing_path_errors(tmp_path, capsys):
    """Case 7: a non-existent path argument fails fast with `path not found`."""
    missing = tmp_path / "does_not_exist.py"

    exit_code, _out, err = _run_in_process(capsys, [str(missing)])

    assert exit_code != 0
    assert "path not found" in err
    assert str(missing) in err


@pytest.mark.unit
def test_untokenizable_file_errors(tmp_path, capsys):
    """Case 8: a file that cannot be tokenized fails fast with `could not tokenize`."""
    target = tmp_path / "broken.py"
    target.write_text('x = "unterminated\n', encoding="utf-8")

    exit_code, _out, err = _run_in_process(capsys, [str(target)])

    assert exit_code != 0
    assert "could not tokenize" in err
    assert str(target) in err


@pytest.mark.unit
def test_multiple_offenders_sorted_with_count(tmp_path, capsys):
    """Case 9: two `#` comments are both reported, sorted by line, count == 2."""
    target = tmp_path / "two.py"
    target.write_text("a = 1  # first\nb = 2\nc = 3  # second\n", encoding="utf-8")

    exit_code, _out, err = _run_in_process(capsys, [str(target)])

    assert exit_code != 0
    first_index = err.index(f"{target}:1:")
    second_index = err.index(f"{target}:3:")
    assert first_index < second_index, "offenders must be sorted by line"
    assert "# first" in err
    assert "# second" in err
    assert "2" in err


@pytest.mark.unit
def test_offenders_sorted_across_files(tmp_path, capsys):
    """Offenders across multiple files are sorted by (path, line)."""
    file_b = tmp_path / "b.py"
    file_a = tmp_path / "a.py"
    file_b.write_text("v = 1  # in b\n", encoding="utf-8")
    file_a.write_text("w = 2  # in a\n", encoding="utf-8")

    exit_code, _out, err = _run_in_process(capsys, [str(file_b), str(file_a)])

    assert exit_code != 0
    assert err.index(f"{file_a}:1:") < err.index(f"{file_b}:1:")


@pytest.mark.unit
def test_empty_file_is_clean(tmp_path, capsys):
    """Edge case: an empty file contributes no offense."""
    target = tmp_path / "empty.py"
    target.write_text("", encoding="utf-8")

    exit_code, out, _err = _run_in_process(capsys, [str(target)])

    assert exit_code == 0
    assert SUCCESS_LINE in out


@pytest.mark.unit
def test_non_py_file_argument_ignored(tmp_path, capsys):
    """A non-`.py` file argument is ignored (only `*.py` files are scanned)."""
    target = tmp_path / "notes.txt"
    target.write_text("# this is a text file comment\n", encoding="utf-8")

    exit_code, out, _err = _run_in_process(capsys, [str(target)])

    assert exit_code == 0
    assert SUCCESS_LINE in out
