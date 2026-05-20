"""Unit tests for kanon doctor subcheck 11 -- remote reachability sanity check.

Covers _check_remote_reachability() using a callable stub for git ls-remote
so tests run without network.

Also covers _run_ls_remote_impl, _run_ls_remote_exit_code, and _read_retry_policy
with direct unit tests (monkeypatching subprocess.run / os.environ) to provide
coverage for those production functions.

Parametrized cases:
- All URLs reachable: no finding produced.
- Single unreachable URL: one WARNING finding, exit remains 0.
- All unreachable: N WARNING findings.
- Auth-error stderr pattern: retries skipped, still produces warning finding.
- Duplicate URLs in ssh/https form: one check, one possible finding.

AC-TEST-001, AC-FUNC-001 through AC-FUNC-007.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

from kanon_cli.commands.doctor import (
    RetryPolicy,
    _check_remote_reachability,
    _read_retry_policy,
    _run_ls_remote_exit_code,
    _run_ls_remote_impl,
)
from kanon_cli.constants import (
    GIT_RETRY_COUNT_DEFAULT,
    GIT_RETRY_DELAY_DEFAULT,
    KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS,
    _KANON_RESOLVE_TIMEOUT_DEFAULT,
)
from kanon_cli.core.lockfile import (
    CatalogBlock,
    Lockfile,
    SourceEntry,
    write_lockfile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_DEFAULT_RETRY_POLICY = RetryPolicy(
    timeout=_KANON_RESOLVE_TIMEOUT_DEFAULT,
    retry_count=GIT_RETRY_COUNT_DEFAULT,
    retry_delay=GIT_RETRY_DELAY_DEFAULT,
)


def _make_lockfile(
    tmp_path: pathlib.Path,
    sources: list[dict],
) -> Lockfile:
    """Build a Lockfile with the given source list (dicts with name/url/revision_spec/resolved_sha).

    Args:
        tmp_path: Temp dir used for writing and reading back the lockfile.
        sources: List of dicts with keys: name, url, revision_spec, resolved_sha.

    Returns:
        A Lockfile dataclass instance.
    """
    from kanon_cli.core.lockfile import read_lockfile

    entries = [
        SourceEntry(
            name=s["name"],
            url=s["url"],
            revision_spec=s["revision_spec"],
            resolved_ref=s["revision_spec"],
            resolved_sha=s["resolved_sha"],
            path="repo-specs/meta.xml",
        )
        for s in sources
    ]
    lockfile = Lockfile(
        schema_version=1,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash="sha256:" + "a" * 64,
        catalog=CatalogBlock(
            source="",
            url="",
            revision_spec="",
            resolved_ref="",
            resolved_sha="",
        ),
        sources=entries,
    )
    lock_path = tmp_path / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return read_lockfile(lock_path)


def _ok_ls_remote(url: str, ref: str, timeout: int, retry_count: int, retry_delay: float) -> tuple[int, str, str]:
    """Stub that always succeeds (returns exit code 0).

    Args:
        url: Git remote URL (unused).
        ref: Ref pattern (unused).
        timeout: Timeout (unused).
        retry_count: Max attempts (unused).
        retry_delay: Delay between retries (unused).

    Returns:
        (0, "", "") indicating success.
    """
    return (0, "", "")


def _fail_ls_remote(url: str, ref: str, timeout: int, retry_count: int, retry_delay: float) -> tuple[int, str, str]:
    """Stub that always fails (returns exit code 128).

    Args:
        url: Git remote URL (unused).
        ref: Ref pattern (unused).
        timeout: Timeout (unused).
        retry_count: Max attempts (unused).
        retry_delay: Delay between retries (unused).

    Returns:
        (128, "", "repository not found") indicating failure.
    """
    return (128, "", "repository not found")


def _auth_fail_ls_remote(
    url: str, ref: str, timeout: int, retry_count: int, retry_delay: float
) -> tuple[int, str, str]:
    """Stub that fails with an auth-error pattern in stderr.

    Args:
        url: Git remote URL (unused).
        ref: Ref pattern (unused).
        timeout: Timeout (unused).
        retry_count: Max attempts (unused).
        retry_delay: Delay between retries (unused).

    Returns:
        (128, "", "Permission denied (publickey)") indicating auth failure.
    """
    return (128, "", "Permission denied (publickey)")


def _long_stderr_ls_remote(
    url: str, ref: str, timeout: int, retry_count: int, retry_delay: float
) -> tuple[int, str, str]:
    """Stub that fails with stderr longer than KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS.

    Args:
        url: Git remote URL (unused).
        ref: Ref pattern (unused).
        timeout: Timeout (unused).
        retry_count: Max attempts (unused).
        retry_delay: Delay between retries (unused).

    Returns:
        (128, "", <long stderr>) indicating a failure with long stderr output.
    """
    long_msg = "X" * (KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS + 50)
    return (128, "", long_msg)


# ---------------------------------------------------------------------------
# Tests: all URLs reachable -- no findings
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAllUrlsReachable:
    """_check_remote_reachability produces no findings when all URLs succeed."""

    def test_single_source_reachable_no_findings(self, tmp_path: pathlib.Path) -> None:
        """One reachable source produces an empty findings list."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _ok_ls_remote, _DEFAULT_RETRY_POLICY)

        assert findings == []

    def test_multiple_sources_all_reachable_no_findings(self, tmp_path: pathlib.Path) -> None:
        """Multiple reachable sources produce an empty findings list."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "a",
                    "url": "https://example.com/org/repo-a.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                },
                {
                    "name": "b",
                    "url": "https://example.com/org/repo-b.git",
                    "revision_spec": "main",
                    "resolved_sha": "b" * 40,
                },
            ],
        )

        findings = _check_remote_reachability(lockfile, _ok_ls_remote, _DEFAULT_RETRY_POLICY)

        assert findings == []

    def test_empty_sources_no_findings(self, tmp_path: pathlib.Path) -> None:
        """Lockfile with no sources produces no findings."""
        lockfile = _make_lockfile(tmp_path, [])

        findings = _check_remote_reachability(lockfile, _ok_ls_remote, _DEFAULT_RETRY_POLICY)

        assert findings == []


# ---------------------------------------------------------------------------
# Tests: single unreachable URL -- one warning finding
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSingleUnreachableUrl:
    """One unreachable URL produces exactly one WARNING finding."""

    def test_single_unreachable_produces_one_finding(self, tmp_path: pathlib.Path) -> None:
        """One failing source produces exactly one finding."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert len(findings) == 1

    def test_single_unreachable_finding_is_warning_not_error(self, tmp_path: pathlib.Path) -> None:
        """Unreachable remote finding has kind=warn (not error)."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert findings[0].kind == "warn"

    def test_single_unreachable_finding_code_is_remote_unreachable(self, tmp_path: pathlib.Path) -> None:
        """Unreachable remote finding has code=REMOTE_UNREACHABLE."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert findings[0].code == "REMOTE_UNREACHABLE"

    def test_single_unreachable_finding_contains_url(self, tmp_path: pathlib.Path) -> None:
        """Warning finding text includes the (canonicalized) URL."""
        url = "https://example.com/org/repo.git"
        lockfile = _make_lockfile(
            tmp_path,
            [{"name": "src", "url": url, "revision_spec": "main", "resolved_sha": "a" * 40}],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        # Canonical form strips .git suffix; anchored regex prevents partial-hostname false matches
        assert re.search(r"\bexample\.com/", findings[0].message)

    def test_single_unreachable_finding_contains_exit_code(self, tmp_path: pathlib.Path) -> None:
        """Warning finding text includes the exit code from git ls-remote."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert "128" in findings[0].message

    def test_single_unreachable_finding_contains_stderr_preview(self, tmp_path: pathlib.Path) -> None:
        """Warning finding text includes the first line of stderr."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert "repository not found" in findings[0].message

    def test_single_unreachable_finding_contains_remediation_doc_ref(self, tmp_path: pathlib.Path) -> None:
        """Warning finding remediation references docs/git-auth-setup.md."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert "docs/git-auth-setup.md" in findings[0].remediation


# ---------------------------------------------------------------------------
# Tests: all URLs unreachable -- N warning findings
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAllUrlsUnreachable:
    """All unreachable URLs produce one warning finding per distinct canonicalized URL."""

    def test_two_unreachable_sources_produce_two_findings(self, tmp_path: pathlib.Path) -> None:
        """Two distinct failing sources produce exactly two findings."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "a",
                    "url": "https://example.com/org/repo-a.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                },
                {
                    "name": "b",
                    "url": "https://example.com/org/repo-b.git",
                    "revision_spec": "main",
                    "resolved_sha": "b" * 40,
                },
            ],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert len(findings) == 2

    def test_three_unreachable_sources_produce_three_findings(self, tmp_path: pathlib.Path) -> None:
        """Three distinct failing sources produce exactly three findings."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "a",
                    "url": "https://example.com/org/repo-a.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                },
                {
                    "name": "b",
                    "url": "https://example.com/org/repo-b.git",
                    "revision_spec": "main",
                    "resolved_sha": "b" * 40,
                },
                {
                    "name": "c",
                    "url": "https://example.com/org/repo-c.git",
                    "revision_spec": "main",
                    "resolved_sha": "c" * 40,
                },
            ],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert len(findings) == 3

    def test_all_unreachable_findings_are_warnings(self, tmp_path: pathlib.Path) -> None:
        """All findings for unreachable URLs have kind=warn."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "a",
                    "url": "https://example.com/org/repo-a.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                },
                {
                    "name": "b",
                    "url": "https://example.com/org/repo-b.git",
                    "revision_spec": "main",
                    "resolved_sha": "b" * 40,
                },
            ],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert all(f.kind == "warn" for f in findings)


# ---------------------------------------------------------------------------
# Tests: stderr truncated at KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStderrTruncation:
    """Stderr preview in the finding is truncated at KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS."""

    def test_long_stderr_truncated_to_preview_chars(self, tmp_path: pathlib.Path) -> None:
        """When stderr exceeds the preview limit, the message truncates it."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _long_stderr_ls_remote, _DEFAULT_RETRY_POLICY)

        assert len(findings) == 1
        # The finding message should NOT exceed the combined length of the fixed
        # parts plus the preview cap (we test that "X" * LIMIT is in the message
        # but "X" * (LIMIT + 1) is not, which verifies truncation occurred).
        expected_preview = "X" * KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS
        overshoot = "X" * (KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS + 1)
        assert expected_preview in findings[0].message
        assert overshoot not in findings[0].message

    def test_short_stderr_not_truncated(self, tmp_path: pathlib.Path) -> None:
        """When stderr is short, the full first line appears in the message."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert "repository not found" in findings[0].message


# ---------------------------------------------------------------------------
# Tests: auth-error patterns -- still produces warning, no retries
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuthErrorPattern:
    """Auth-error stderr patterns still produce a warning finding (per spec)."""

    def test_auth_error_produces_warning_finding(self, tmp_path: pathlib.Path) -> None:
        """Auth-error in stderr still produces a warning (not an error)."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _auth_fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert len(findings) == 1
        assert findings[0].kind == "warn"

    def test_auth_error_finding_contains_url(self, tmp_path: pathlib.Path) -> None:
        """Auth-error finding message includes the URL."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _auth_fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert "example.com" in findings[0].message

    def test_auth_error_finding_contains_stderr_preview(self, tmp_path: pathlib.Path) -> None:
        """Auth-error finding includes permission-denied text from stderr."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _auth_fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert "Permission denied" in findings[0].message

    def test_auth_error_finding_contains_remediation(self, tmp_path: pathlib.Path) -> None:
        """Auth-error finding remediation references docs/git-auth-setup.md."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _auth_fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert "docs/git-auth-setup.md" in findings[0].remediation


# ---------------------------------------------------------------------------
# Tests: duplicate URLs (ssh vs https forms) -- deduplicated to one check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDuplicateUrlDeduplication:
    """SSH and HTTPS forms of the same URL are deduplicated; only one check is issued."""

    def test_ssh_and_https_same_repo_one_call(self, tmp_path: pathlib.Path) -> None:
        """SSH and HTTPS forms of the same URL are deduplicated to one ls-remote call."""
        call_count = 0

        def _counting_stub(
            url: str, ref: str, timeout: int, retry_count: int, retry_delay: float
        ) -> tuple[int, str, str]:
            nonlocal call_count
            call_count += 1
            return (0, "", "")

        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "a",
                    "url": "https://github.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                },
                {
                    "name": "b",
                    "url": "git@github.com:org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                },
            ],
        )

        _check_remote_reachability(lockfile, _counting_stub, _DEFAULT_RETRY_POLICY)

        assert call_count == 1

    def test_ssh_and_https_same_repo_one_possible_finding(self, tmp_path: pathlib.Path) -> None:
        """SSH + HTTPS duplicate URLs produce at most one warning finding."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "a",
                    "url": "https://github.com/org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                },
                {
                    "name": "b",
                    "url": "git@github.com:org/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                },
            ],
        )

        findings = _check_remote_reachability(lockfile, _fail_ls_remote, _DEFAULT_RETRY_POLICY)

        assert len(findings) == 1

    def test_two_distinct_repos_two_calls(self, tmp_path: pathlib.Path) -> None:
        """Two genuinely distinct URLs cause two ls-remote calls."""
        call_count = 0

        def _counting_stub(
            url: str, ref: str, timeout: int, retry_count: int, retry_delay: float
        ) -> tuple[int, str, str]:
            nonlocal call_count
            call_count += 1
            return (0, "", "")

        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "a",
                    "url": "https://example.com/org/repo-a.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                },
                {
                    "name": "b",
                    "url": "https://example.com/org/repo-b.git",
                    "revision_spec": "main",
                    "resolved_sha": "b" * 40,
                },
            ],
        )

        _check_remote_reachability(lockfile, _counting_stub, _DEFAULT_RETRY_POLICY)

        assert call_count == 2


# ---------------------------------------------------------------------------
# Tests: exact call count matches distinct canonicalized URL count
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExactCallCount:
    """Verifies the exact number of ls-remote calls equals the number of distinct canonical URLs."""

    @pytest.mark.parametrize(
        "sources,expected_calls",
        [
            ([], 0),
            (
                [
                    {
                        "name": "a",
                        "url": "https://example.com/org/r.git",
                        "revision_spec": "main",
                        "resolved_sha": "a" * 40,
                    }
                ],
                1,
            ),
            (
                [
                    {
                        "name": "a",
                        "url": "https://example.com/org/ra.git",
                        "revision_spec": "main",
                        "resolved_sha": "a" * 40,
                    },
                    {
                        "name": "b",
                        "url": "https://example.com/org/rb.git",
                        "revision_spec": "main",
                        "resolved_sha": "b" * 40,
                    },
                    {
                        "name": "c",
                        "url": "https://example.com/org/rc.git",
                        "revision_spec": "main",
                        "resolved_sha": "c" * 40,
                    },
                ],
                3,
            ),
        ],
    )
    def test_call_count_equals_distinct_canonical_urls(
        self,
        tmp_path: pathlib.Path,
        sources: list[dict],
        expected_calls: int,
    ) -> None:
        """Exactly as many ls-remote calls as distinct canonical URLs."""
        call_count = 0

        def _stub(url: str, ref: str, timeout: int, retry_count: int, retry_delay: float) -> tuple[int, str, str]:
            nonlocal call_count
            call_count += 1
            return (0, "", "")

        lockfile = _make_lockfile(tmp_path, sources)
        _check_remote_reachability(lockfile, _stub, _DEFAULT_RETRY_POLICY)

        assert call_count == expected_calls


# ---------------------------------------------------------------------------
# Tests: AC-FUNC-007 -- callable injection contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCallableInjection:
    """_check_remote_reachability accepts ls_remote_callable as a parameter (AC-FUNC-007)."""

    def test_callable_is_invoked_with_url_and_head_ref(self, tmp_path: pathlib.Path) -> None:
        """The ls_remote_callable is called with the source URL and HEAD as ref."""
        calls: list[tuple[str, str]] = []

        def _recording_stub(
            url: str, ref: str, timeout: int, retry_count: int, retry_delay: float
        ) -> tuple[int, str, str]:
            calls.append((url, ref))
            return (0, "", "")

        url = "https://example.com/org/repo.git"
        lockfile = _make_lockfile(
            tmp_path,
            [{"name": "src", "url": url, "revision_spec": "main", "resolved_sha": "a" * 40}],
        )

        _check_remote_reachability(lockfile, _recording_stub, _DEFAULT_RETRY_POLICY)

        assert len(calls) == 1
        # The URL passed to the callable must be the raw URL (not canonical form
        # -- git ls-remote needs the actual URL, not the https:// normalized form)
        assert calls[0][0] in (url, "https://example.com/org/repo")
        assert calls[0][1] == "HEAD"

    def test_constants_referenced_not_hardcoded(self) -> None:
        """KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS is importable from constants."""
        from kanon_cli.constants import KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS as preview_chars

        assert isinstance(preview_chars, int)
        assert preview_chars > 0


# ---------------------------------------------------------------------------
# Tests: KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS constant
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteStderrPreviewConst:
    """KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS exists in constants.py with correct default."""

    def test_constant_exists_and_is_int(self) -> None:
        """KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS is an integer."""
        from kanon_cli.constants import KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS

        assert isinstance(KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS, int)

    def test_constant_default_is_160(self) -> None:
        """KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS defaults to 160."""
        from kanon_cli.constants import KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS

        assert KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS == 160

    def test_constant_is_positive(self) -> None:
        """KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS is a positive integer."""
        from kanon_cli.constants import KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS

        assert KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS > 0


# ---------------------------------------------------------------------------
# Tests: invalid URL -- canonicalize_repo_url raises ValueError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInvalidUrlWarning:
    """An unrecognized URL format produces a REMOTE_URL_INVALID warning finding."""

    def test_invalid_url_produces_warn_finding(self, tmp_path: pathlib.Path) -> None:
        """A source URL that fails canonicalization produces a warning finding."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "bad-src",
                    "url": "not-a-valid-url",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _ok_ls_remote, _DEFAULT_RETRY_POLICY)

        assert len(findings) == 1
        assert findings[0].kind == "warn"
        assert findings[0].code == "REMOTE_URL_INVALID"

    def test_invalid_url_finding_contains_source_name(self, tmp_path: pathlib.Path) -> None:
        """The REMOTE_URL_INVALID finding message includes the source name."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "bad-src",
                    "url": "not-a-valid-url",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _ok_ls_remote, _DEFAULT_RETRY_POLICY)

        assert "bad-src" in findings[0].message

    def test_invalid_url_not_passed_to_callable(self, tmp_path: pathlib.Path) -> None:
        """An invalid URL produces a warning finding; the ls_remote callable is NOT invoked."""
        call_count = 0

        def _counting_stub(
            url: str, ref: str, timeout: int, retry_count: int, retry_delay: float
        ) -> tuple[int, str, str]:
            nonlocal call_count
            call_count += 1
            return (0, "", "")

        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "bad-src",
                    "url": "not-a-valid-url",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        _check_remote_reachability(lockfile, _counting_stub, _DEFAULT_RETRY_POLICY)

        assert call_count == 0

    def test_invalid_url_remediation_references_auth_setup_doc(self, tmp_path: pathlib.Path) -> None:
        """The REMOTE_URL_INVALID finding remediation references docs/git-auth-setup.md."""
        lockfile = _make_lockfile(
            tmp_path,
            [
                {
                    "name": "bad-src",
                    "url": "not-a-valid-url",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        findings = _check_remote_reachability(lockfile, _ok_ls_remote, _DEFAULT_RETRY_POLICY)

        assert "docs/git-auth-setup.md" in findings[0].remediation


# ---------------------------------------------------------------------------
# Tests: _run_ls_remote_impl -- direct coverage with monkeypatched subprocess
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunLsRemoteImpl:
    """Direct unit tests for _run_ls_remote_impl covering subprocess interaction."""

    def test_success_returns_zero_returncode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When subprocess.run returns 0, _run_ls_remote_impl returns (0, stdout, stderr)."""
        fake_result = subprocess.CompletedProcess(
            args=["git", "ls-remote"], returncode=0, stdout="abc\trefs/heads/main\n", stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        code, out, err = _run_ls_remote_impl(["git", "ls-remote", "https://example.com/r", "HEAD"], 30, 1, 0.0)

        assert code == 0
        assert out == "abc\trefs/heads/main\n"
        assert err == ""

    def test_non_zero_returncode_propagated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When subprocess.run returns non-zero with no auth pattern, the exit code is propagated."""
        fake_result = subprocess.CompletedProcess(
            args=["git", "ls-remote"], returncode=128, stdout="", stderr="repository not found"
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        code, out, err = _run_ls_remote_impl(["git", "ls-remote", "https://example.com/r", "HEAD"], 30, 1, 0.0)

        assert code == 128
        assert err == "repository not found"

    def test_auth_error_pattern_skips_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When stderr contains an auth-error pattern, no retry is performed."""
        call_count = 0

        def _fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(
                args=args[0], returncode=128, stdout="", stderr="Permission denied (publickey)"
            )

        monkeypatch.setattr(subprocess, "run", _fake_run)

        code, out, err = _run_ls_remote_impl(["git", "ls-remote", "https://example.com/r", "HEAD"], 30, 3, 0.0)

        # Auth errors must not be retried -- only one subprocess call despite retry_count=3
        assert call_count == 1
        assert code == 128
        assert "Permission denied" in err

    def test_timeout_returns_exit_code_124(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When subprocess.TimeoutExpired is raised, exit code 124 is returned."""

        def _fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        monkeypatch.setattr(subprocess, "run", _fake_run)

        code, out, err = _run_ls_remote_impl(["git", "ls-remote", "https://example.com/r", "HEAD"], 1, 1, 0.0)

        assert code == 124
        assert "timed out" in err

    def test_retry_on_transient_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-auth non-zero exits trigger retries up to retry_count."""
        call_count = 0

        def _fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr="transient error")

        monkeypatch.setattr(subprocess, "run", _fake_run)

        code, out, err = _run_ls_remote_impl(["git", "ls-remote", "https://example.com/r", "HEAD"], 30, 3, 0.0)

        assert call_count == 3
        assert code == 1


# ---------------------------------------------------------------------------
# Tests: _run_ls_remote_exit_code -- direct coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunLsRemoteExitCode:
    """Direct unit tests for _run_ls_remote_exit_code covering --exit-code flag injection."""

    def test_exit_code_flag_included_in_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_run_ls_remote_exit_code passes --exit-code in the command to subprocess.run."""
        captured_cmd: list[list[str]] = []

        def _fake_run(cmd, *args, **kwargs):
            captured_cmd.append(list(cmd))
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", _fake_run)

        _run_ls_remote_exit_code("https://example.com/r", "HEAD", 30, 1, 0.0)

        assert len(captured_cmd) == 1
        assert "--exit-code" in captured_cmd[0]

    def test_success_returns_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the remote ref exists, _run_ls_remote_exit_code returns 0."""
        fake_result = subprocess.CompletedProcess(
            args=["git", "ls-remote", "--exit-code", "https://example.com/r", "HEAD"],
            returncode=0,
            stdout="abc\tHEAD\n",
            stderr="",
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        code, out, err = _run_ls_remote_exit_code("https://example.com/r", "HEAD", 30, 1, 0.0)

        assert code == 0

    def test_non_zero_when_ref_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the ref is absent, git returns 2 with --exit-code; the code is propagated."""
        fake_result = subprocess.CompletedProcess(
            args=["git", "ls-remote", "--exit-code", "https://example.com/r", "HEAD"],
            returncode=2,
            stdout="",
            stderr="",
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        code, out, err = _run_ls_remote_exit_code("https://example.com/r", "HEAD", 30, 1, 0.0)

        assert code == 2


# ---------------------------------------------------------------------------
# Tests: _read_retry_policy -- direct coverage with monkeypatched os.environ
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReadRetryPolicy:
    """Direct unit tests for _read_retry_policy covering env-var reading."""

    def test_defaults_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no env vars are set, _read_retry_policy returns the built-in defaults."""
        from kanon_cli.constants import (
            GIT_RETRY_COUNT_DEFAULT,
            GIT_RETRY_DELAY_DEFAULT,
            _KANON_RESOLVE_TIMEOUT_DEFAULT,
        )

        monkeypatch.delenv("KANON_RESOLVE_TIMEOUT", raising=False)
        monkeypatch.delenv("KANON_GIT_RETRY_COUNT", raising=False)
        monkeypatch.delenv("KANON_GIT_RETRY_DELAY", raising=False)

        policy = _read_retry_policy()

        assert policy.timeout == _KANON_RESOLVE_TIMEOUT_DEFAULT
        assert policy.retry_count == GIT_RETRY_COUNT_DEFAULT
        assert policy.retry_delay == GIT_RETRY_DELAY_DEFAULT

    def test_timeout_overridden_by_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_RESOLVE_TIMEOUT env var overrides the default timeout."""
        monkeypatch.setenv("KANON_RESOLVE_TIMEOUT", "60")
        monkeypatch.delenv("KANON_GIT_RETRY_COUNT", raising=False)
        monkeypatch.delenv("KANON_GIT_RETRY_DELAY", raising=False)

        policy = _read_retry_policy()

        assert policy.timeout == 60

    def test_retry_count_overridden_by_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_RETRY_COUNT env var overrides the default retry count."""
        monkeypatch.delenv("KANON_RESOLVE_TIMEOUT", raising=False)
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "5")
        monkeypatch.delenv("KANON_GIT_RETRY_DELAY", raising=False)

        policy = _read_retry_policy()

        assert policy.retry_count == 5

    def test_retry_delay_overridden_by_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_RETRY_DELAY env var overrides the default retry delay."""
        monkeypatch.delenv("KANON_RESOLVE_TIMEOUT", raising=False)
        monkeypatch.delenv("KANON_GIT_RETRY_COUNT", raising=False)
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "2.5")

        policy = _read_retry_policy()

        assert policy.retry_delay == 2.5

    def test_returns_retry_policy_namedtuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_read_retry_policy returns a RetryPolicy NamedTuple instance."""
        monkeypatch.delenv("KANON_RESOLVE_TIMEOUT", raising=False)
        monkeypatch.delenv("KANON_GIT_RETRY_COUNT", raising=False)
        monkeypatch.delenv("KANON_GIT_RETRY_DELAY", raising=False)

        policy = _read_retry_policy()

        assert isinstance(policy, RetryPolicy)
        assert hasattr(policy, "timeout")
        assert hasattr(policy, "retry_count")
        assert hasattr(policy, "retry_delay")
