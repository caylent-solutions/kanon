# Coverage gaps -- E15-F4-S1-T1 diagnostic output

Coverage report command: `uv run pytest --cov=src --cov-report=term-missing tests/unit tests/integration tests/functional`

Note: The full test command (including integration and functional suites) exceeded the 480-second
timeout on the available runner. The coverage data below was derived from the unit-only run:
`uv run pytest --cov=src --cov-report=term-missing tests/unit`
The integration/functional suites have pre-existing failures (bootstrap-deprecation migration
gaps, env-var isolation leaks documented in ci_failures.md) that do not affect the new-code
coverage gaps identified here. No new-code uncovered line in the gap table below is plausibly
reached by the failing integration/functional tests.

Run date: 2026-05-20T20:18:53Z
Overall coverage (unit suite): 93%
New-code file count (from branch_added_files.txt): 32 files

## New-code coverage by file

| File | Stmts | Miss | Cover | Missing ranges |
|------|-------|------|-------|----------------|
| src/kanon_cli/commands/add.py | 219 | 0 | 100% | |
| src/kanon_cli/commands/catalog.py | 257 | 0 | 100% | |
| src/kanon_cli/commands/completion.py | 13 | 0 | 100% | |
| src/kanon_cli/commands/doctor.py | 347 | 17 | 95% | 114, 184, 219-223, 454, 1114-1116, 1121-1123, 1128-1130, 1139 |
| src/kanon_cli/commands/list.py | 444 | 46 | 90% | 156-160, 164-171, 220-228, 314-363 |
| src/kanon_cli/commands/outdated.py | 153 | 0 | 100% | |
| src/kanon_cli/commands/remove.py | 99 | 0 | 100% | |
| src/kanon_cli/commands/why.py | 242 | 0 | 100% | |
| src/kanon_cli/completions/__init__.py | 0 | 0 | 100% | |
| src/kanon_cli/completions/cache.py | 147 | 0 | 100% | |
| src/kanon_cli/completions/cached_catalogs.py | 54 | 0 | 100% | |
| src/kanon_cli/completions/catalog_entries.py | 119 | 0 | 100% | |
| src/kanon_cli/completions/catalog_versions.py | 128 | 0 | 100% | |
| src/kanon_cli/completions/lockfile_names.py | 46 | 0 | 100% | |
| src/kanon_cli/completions/midtoken.py | 49 | 0 | 100% | |
| src/kanon_cli/completions/pep440_filter.py | 13 | 0 | 100% | |
| src/kanon_cli/completions/preamble.py | 4 | 0 | 100% | |
| src/kanon_cli/completions/project_versions.py | 123 | 0 | 100% | |
| src/kanon_cli/completions/sanitize.py | 31 | 0 | 100% | |
| src/kanon_cli/completions/source_names.py | 51 | 0 | 100% | |
| src/kanon_cli/core/cli_args.py | 23 | 0 | 100% | |
| src/kanon_cli/core/include_walker.py | 54 | 0 | 100% | |
| src/kanon_cli/core/kanon_hash.py | 30 | 0 | 100% | |
| src/kanon_cli/core/lockfile.py | 237 | 7 | 97% | 320, 822-824, 826-828 |
| src/kanon_cli/core/manifest.py | 67 | 0 | 100% | |
| src/kanon_cli/core/metadata.py | 106 | 0 | 100% | |
| src/kanon_cli/core/remote_url.py | 46 | 0 | 100% | |
| src/kanon_cli/core/url.py | 35 | 0 | 100% | |
| src/kanon_cli/utils/__init__.py | 0 | 0 | 100% | |
| src/kanon_cli/utils/concurrency.py | 19 | 0 | 100% | |
| src/kanon_cli/utils/levenshtein.py | 21 | 0 | 100% | |
| src/kanon_cli/utils/lock_file_path.py | 9 | 0 | 100% | |

New-code coverage: 3 files have gaps (29 new-code files are at 100%).

## Line count methodology

pytest-cov's `Missing` column lists ranges of lines within which at least one executable
statement is uncovered. Ranges include non-executable lines (continuation lines, blank lines,
comment-only lines) in the displayed range. The Miss count (17, 46, 7 = 70 total executable
statements) differs from the range-expansion count (18, 72, 7 = 97 total lines-in-range)
because coverage tracks statements, not lines. This document lists one row per line-in-range
(97 rows) as the Approach specifies ("expand them into individual line numbers"). Lines that
are non-executable are noted in the Source snippet column.

## Gaps

| File | Line | Source snippet | Category | Notes | Closed by |
|------|------|----------------|----------|-------|-----------|
| src/kanon_cli/commands/doctor.py | 114 | `return False` | test-needed | `_is_branch_revision` returns False when revision_spec starts with "refs/"; no test exercises this path. Add unit test passing a refs/-prefixed revision_spec. R66: 100% line coverage on new code. | tests/unit/test_doctor_coverage_gaps.py::test_is_branch_revision |
| src/kanon_cli/commands/doctor.py | 184 | `time.sleep(retry_delay)` | test-needed | `_run_ls_remote_impl` inter-retry sleep path; only reached when `attempt < retry_count - 1` after a TimeoutExpired and `retry_count >= 2`; no test covers a second-attempt timeout scenario. Add a test that triggers two consecutive timeouts to exercise the sleep branch. R66. | tests/unit/test_doctor_coverage_gaps.py::TestRunLsRemoteImplTimeoutSleepPath |
| src/kanon_cli/commands/doctor.py | 219 | `if ref:` | test-needed | `_run_ls_remote` body is entirely uncovered because all tests that exercise the branch-drift and dangling-SHA subchecks mock `_run_ls_remote` via `unittest.mock.patch`. Add a direct unit test for `_run_ls_remote` (analogous to `TestRunLsRemoteImpl` in `test_doctor_remote_reachability.py`) that monkeypatches subprocess.run and asserts the correct `cmd` list is constructed when `ref` is non-empty. R66. | tests/unit/test_doctor_coverage_gaps.py::TestRunLsRemoteDirectly |
| src/kanon_cli/commands/doctor.py | 220 | `cmd = ["git", "ls-remote", url, ref]` | test-needed | Continuation of line 219: branch taken when ref is truthy; uncovered for same reason as line 219. Same remediation. R66. | tests/unit/test_doctor_coverage_gaps.py::TestRunLsRemoteDirectly |
| src/kanon_cli/commands/doctor.py | 221 | `else:` | test-needed | Non-executable `else:` clause of `if ref:` block in `_run_ls_remote`; included in range by coverage display. Covered implicitly when the else-branch body (line 222) is reached. Same remediation as line 219. R66. | tests/unit/test_doctor_coverage_gaps.py::TestRunLsRemoteDirectly |
| src/kanon_cli/commands/doctor.py | 222 | `cmd = ["git", "ls-remote", url]` | test-needed | Else-branch in `_run_ls_remote` when ref is falsy; uncovered because `_run_ls_remote` is never called directly in tests. Add a test with an empty-ref argument to exercise this branch too. R66. | tests/unit/test_doctor_coverage_gaps.py::TestRunLsRemoteDirectly |
| src/kanon_cli/commands/doctor.py | 223 | `return _run_ls_remote_impl(cmd, ...)` | test-needed | Return statement in `_run_ls_remote`; uncovered because the function is always mocked. Same remediation as line 219. R66. | tests/unit/test_doctor_coverage_gaps.py::TestRunLsRemoteDirectly |
| src/kanon_cli/commands/doctor.py | 454 | `continue` | test-needed | Inside `_check_branch_drift`: the `continue` on returncode != 0 (network failure skip) is never triggered in tests; all mock returns use returncode 0. Add a test scenario where `_run_ls_remote` returns non-zero to cover the skip path. R66/R68 (error-path coverage). | tests/unit/test_doctor_coverage_gaps.py::TestCheckBranchDriftNonZeroReturncode |
| src/kanon_cli/commands/doctor.py | 1114 | `_print_finding(finding)` | test-needed | Loop body inside `run_doctor` for orphan-lock findings; only reached when `_check_orphan_locks` returns non-empty findings. No test calls `run_doctor` end-to-end with an orphan lock present. Add an integration-level test (or a direct unit test for `run_doctor`) with a lockfile containing an orphan entry. R66/R68. | tests/unit/test_doctor_coverage_gaps.py::TestDoctorCommandOrphanLockFindings |
| src/kanon_cli/commands/doctor.py | 1115 | `if finding.kind == "error":` | test-needed | Continuation of orphan-lock loop in `run_doctor`; same gap as line 1114. R66/R68. | tests/unit/test_doctor_coverage_gaps.py::TestDoctorCommandOrphanLockFindings |
| src/kanon_cli/commands/doctor.py | 1116 | `has_errors = True` | test-needed | `has_errors` flag set on orphan-lock error finding in `run_doctor`; requires a test that exercises the error-level orphan finding path end-to-end. R66/R68. | tests/unit/test_doctor_coverage_gaps.py::TestDoctorCommandOrphanLockFindings::test_orphan_lock_error_finding_causes_nonzero_exit |
| src/kanon_cli/commands/doctor.py | 1121 | `_print_finding(finding)` | test-needed | Loop body inside `run_doctor` for branch-drift findings; only reached when `_check_branch_drift` returns non-empty findings. No test calls `run_doctor` end-to-end with drift present. Same gap class as 1114-1116 but for check 4. R66/R68. | tests/unit/test_doctor_coverage_gaps.py::TestDoctorCommandBranchDriftFindings |
| src/kanon_cli/commands/doctor.py | 1122 | `if finding.kind == "error":` | test-needed | Continuation of branch-drift loop in `run_doctor`; same gap as line 1121. R66/R68. | tests/unit/test_doctor_coverage_gaps.py::TestDoctorCommandBranchDriftFindings |
| src/kanon_cli/commands/doctor.py | 1123 | `has_errors = True` | test-needed | `has_errors` flag set on drift error finding in `run_doctor`; requires a test that exercises strict-drift end-to-end through `run_doctor`. R66/R68. | tests/unit/test_doctor_coverage_gaps.py::TestDoctorCommandBranchDriftFindings::test_strict_drift_error_finding_causes_nonzero_exit |
| src/kanon_cli/commands/doctor.py | 1128 | `_print_finding(finding)` | test-needed | Loop body inside `run_doctor` for dangling-SHA findings; only reached when `_check_dangling_shas` returns non-empty findings. No test calls `run_doctor` end-to-end with a dangling SHA. Same gap class as 1114-1116 but for check 5. R66/R68. | tests/unit/test_doctor_coverage_gaps.py::TestDoctorCommandDanglingShaFindings |
| src/kanon_cli/commands/doctor.py | 1129 | `if finding.kind == "error":` | test-needed | Continuation of dangling-SHA loop in `run_doctor`; same gap as line 1128. R66/R68. | tests/unit/test_doctor_coverage_gaps.py::TestDoctorCommandDanglingShaFindings |
| src/kanon_cli/commands/doctor.py | 1130 | `has_errors = True` | test-needed | `has_errors` flag set on dangling-SHA error finding in `run_doctor`. Requires end-to-end test. R66/R68. | tests/unit/test_doctor_coverage_gaps.py::TestDoctorCommandDanglingShaFindings::test_dangling_sha_error_finding_causes_nonzero_exit |
| src/kanon_cli/commands/doctor.py | 1139 | `_print_finding(finding)` | test-needed | Loop body inside `run_doctor` for remote-reachability findings from check 11; only reached when `_check_remote_reachability` returns non-empty findings. No end-to-end `run_doctor` test exercises a failing remote. R66/R68. | tests/unit/test_doctor_coverage_gaps.py::TestDoctorCommandRemoteReachabilityFindings |
| src/kanon_cli/commands/list.py | 156 | `print(` | test-needed | `_list_tags_from_url` error path: git ls-remote failure print; only reached when subprocess returns non-zero. No test exercises this error path in `_list_tags_from_url`. Add a unit test that monkeypatches subprocess.run to return returncode=1. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlErrorPath |
| src/kanon_cli/commands/list.py | 157 | `f"ERROR: git ls-remote failed for {url}: {result.stderr}",` | test-needed | Continuation of print statement on line 156; same gap. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlErrorPath |
| src/kanon_cli/commands/list.py | 158 | `file=sys.stderr,` | test-needed | Continuation of print statement on line 156; same gap. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlErrorPath |
| src/kanon_cli/commands/list.py | 159 | `)` | test-needed | Continuation of print statement on line 156; same gap. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlErrorPath |
| src/kanon_cli/commands/list.py | 160 | `sys.exit(1)` | test-needed | `_list_tags_from_url` exits 1 on git ls-remote failure; uncovered. Same remediation as line 156. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlErrorPath |
| src/kanon_cli/commands/list.py | 164 | `if not line:` | test-needed | Inside `_list_tags_from_url`: guard for empty lines in ls-remote output; no test supplies output with blank lines. The entire parsing loop (164-171) is uncovered because no test calls `_list_tags_from_url` with a successful subprocess result. Add a unit test that injects multi-line ls-remote output including blank lines. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlParsingLoop |
| src/kanon_cli/commands/list.py | 165 | `continue` | test-needed | Empty-line skip in `_list_tags_from_url` parsing loop; same gap as line 164. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlParsingLoop |
| src/kanon_cli/commands/list.py | 166 | `parts = line.split("\t")` | test-needed | Tab-split inside parsing loop in `_list_tags_from_url`; uncovered because no test exercises the success path. Same remediation as line 164. R66. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlParsingLoop |
| src/kanon_cli/commands/list.py | 167 | `if len(parts) < 2:` | test-needed | Malformed-line guard in `_list_tags_from_url`; no test supplies output with lines missing a tab character. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlParsingLoop |
| src/kanon_cli/commands/list.py | 168 | `continue` | test-needed | Malformed-line skip; same gap as line 167. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlParsingLoop |
| src/kanon_cli/commands/list.py | 169 | `sha, ref = parts[0], parts[1]` | test-needed | SHA/ref destructuring in `_list_tags_from_url`; uncovered because no test exercises the success path. Same remediation as line 164. R66. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlParsingLoop |
| src/kanon_cli/commands/list.py | 170 | `if ref.startswith("refs/tags/") and not ref.endswith("^{}"):` | test-needed | Tag-filter guard in `_list_tags_from_url`; no test reaches this line. Add tests covering both the matching and non-matching ref patterns (e.g., annotated-tag peeled refs ending in `^{}`). R66/R68. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlParsingLoop |
| src/kanon_cli/commands/list.py | 171 | `pairs.append((ref, sha))` | test-needed | Append to pairs list in `_list_tags_from_url`; uncovered. Same remediation as line 164. R66. | tests/unit/test_list_coverage_gaps.py::TestListTagsFromUrlParsingLoop |
| src/kanon_cli/commands/list.py | 220 | `parsed: list[tuple[str, Version, str]] = []` | test-needed | Entire body of `_sort_version_pairs_newest_first` is uncovered; function is used by `_list_all_versions_for_url` which itself has no tests. Add a unit test calling `_sort_version_pairs_newest_first` directly with a list of (ref, sha) pairs, asserting correct sort order and version parsing. R66. | tests/unit/test_list_coverage_gaps.py::TestSortVersionPairsNewestFirst |
| src/kanon_cli/commands/list.py | 221 | `for ref, sha in pairs:` | test-needed | Loop header of `_sort_version_pairs_newest_first`; same gap as line 220. R66. | tests/unit/test_list_coverage_gaps.py::TestSortVersionPairsNewestFirst |
| src/kanon_cli/commands/list.py | 222 | `version_str = ref.rsplit("/", 1)[-1]` | test-needed | Version string extraction in `_sort_version_pairs_newest_first`; same gap as line 220. R66. | tests/unit/test_list_coverage_gaps.py::TestSortVersionPairsNewestFirst |
| src/kanon_cli/commands/list.py | 223 | `try:` | test-needed | Try block in `_sort_version_pairs_newest_first`; same gap as line 220. R66. | tests/unit/test_list_coverage_gaps.py::TestSortVersionPairsNewestFirst |
| src/kanon_cli/commands/list.py | 224 | `parsed.append((ref, Version(version_str), sha))` | test-needed | Parsed append inside try block; same gap as line 220. R66. | tests/unit/test_list_coverage_gaps.py::TestSortVersionPairsNewestFirst |
| src/kanon_cli/commands/list.py | 225 | `except InvalidVersion:` | test-needed | Exception handler for non-PEP-440 tags; uncovered because `_sort_version_pairs_newest_first` is never called in tests. Add a test that passes a ref with a non-PEP-440 version string (e.g., `refs/tags/not-a-version`) to exercise this branch. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestSortVersionPairsNewestFirst::test_non_pep440_tag_skipped |
| src/kanon_cli/commands/list.py | 226 | `continue` | test-needed | Non-PEP-440 tag skip in `_sort_version_pairs_newest_first`; same gap as line 225. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestSortVersionPairsNewestFirst::test_non_pep440_tag_skipped |
| src/kanon_cli/commands/list.py | 227 | `parsed.sort(key=lambda t: t[1], reverse=True)` | test-needed | Sort after parsing in `_sort_version_pairs_newest_first`; same gap as line 220. R66. | tests/unit/test_list_coverage_gaps.py::TestSortVersionPairsNewestFirst |
| src/kanon_cli/commands/list.py | 228 | `return parsed` | test-needed | Return statement of `_sort_version_pairs_newest_first`; same gap as line 220. R66. | tests/unit/test_list_coverage_gaps.py::TestSortVersionPairsNewestFirst |
| src/kanon_cli/commands/list.py | 314 | `sorted_triples = _sort_version_pairs_newest_first(pairs)` | test-needed | `_list_all_versions_for_url` body starts here; entire function is uncovered -- no test calls `_list_all_versions_for_url` or the higher-level `run_list` invocation that routes to it. Add integration-level tests for the `--all-versions` list path. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 315 | `if not sorted_triples:` | test-needed | Zero-PEP-440-tags guard in `_list_all_versions_for_url`; uncovered. Add test that provides a URL returning only non-PEP-440 tags. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_zero_pep440_tags_exits_with_error |
| src/kanon_cli/commands/list.py | 316 | `# Zero PEP 440-parseable tags...` | test-needed | Comment line inside the zero-sorted-triples block; non-executable. Covered when line 317 is covered. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_zero_pep440_tags_exits_with_error |
| src/kanon_cli/commands/list.py | 317 | `skipped = [ref for ref, _ in pairs]` | test-needed | List comprehension building skipped-tag list for error message; same gap as line 315. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_zero_pep440_tags_exits_with_error |
| src/kanon_cli/commands/list.py | 318 | `from kanon_cli.version import _format_zero_pep440_tags_error` | test-needed | Lazy import inside error path; same gap as line 315. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_zero_pep440_tags_exits_with_error |
| src/kanon_cli/commands/list.py | 319 | `(blank line)` | test-needed | Blank line inside zero-tags block; non-executable. Covered by surrounding lines. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_zero_pep440_tags_exits_with_error |
| src/kanon_cli/commands/list.py | 320 | `msg = _format_zero_pep440_tags_error("refs/tags", skipped)` | test-needed | Error message construction in zero-tags path; same gap as line 315. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_zero_pep440_tags_exits_with_error |
| src/kanon_cli/commands/list.py | 321 | `print(f"ERROR: {msg}", file=sys.stderr)` | test-needed | Error print to stderr in zero-tags path; same gap as line 315. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_zero_pep440_tags_exits_with_error |
| src/kanon_cli/commands/list.py | 322 | `sys.exit(1)` | test-needed | Exit on zero PEP-440 tags in `_list_all_versions_for_url`; same gap as line 315. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_zero_pep440_tags_exits_with_error |
| src/kanon_cli/commands/list.py | 323 | `(blank line)` | test-needed | Blank line; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 324 | `if since_version is not None:` | test-needed | `--since` version filter guard in `_list_all_versions_for_url`; uncovered because function is never called. Add test passing `since_version` to exercise this branch. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_since_version_filter_removes_older_versions |
| src/kanon_cli/commands/list.py | 325 | `try:` | test-needed | Try block for constraint parsing in `_list_all_versions_for_url`; same gap as line 324. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_since_version_filter_removes_older_versions |
| src/kanon_cli/commands/list.py | 326 | `sorted_triples = _filter_versions_by_constraint(...)` | test-needed | Constraint filtering call in `_list_all_versions_for_url`; same gap as line 324. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_since_version_filter_removes_older_versions |
| src/kanon_cli/commands/list.py | 327 | `except ValueError as exc:` | test-needed | Invalid constraint exception handler; uncovered. Add test passing an invalid version-constraint string. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_invalid_since_version_exits_with_error |
| src/kanon_cli/commands/list.py | 328 | `print(f"ERROR: {exc}", file=sys.stderr)` | test-needed | Error print for invalid constraint; same gap as line 327. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_invalid_since_version_exits_with_error |
| src/kanon_cli/commands/list.py | 329 | `sys.exit(1)` | test-needed | Exit on invalid version constraint; same gap as line 327. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_invalid_since_version_exits_with_error |
| src/kanon_cli/commands/list.py | 330 | `(blank line)` | test-needed | Blank line; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 331 | `# Apply version cap. limit=0 means unlimited.` | test-needed | Comment; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 332 | `if limit > 0:` | test-needed | Version-count limit guard in `_list_all_versions_for_url`; uncovered. Add test passing `limit > 0`. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_limit_applied_to_sorted_triples |
| src/kanon_cli/commands/list.py | 333 | `sorted_triples = sorted_triples[:limit]` | test-needed | Slice to limit in `_list_all_versions_for_url`; same gap as line 332. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_limit_applied_to_sorted_triples |
| src/kanon_cli/commands/list.py | 334 | `(blank line)` | test-needed | Blank line; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 335 | `if not sorted_triples:` | test-needed | Empty-after-filter guard in `_list_all_versions_for_url`; uncovered. Add test where all versions are filtered out by constraint. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_all_versions_filtered_out_returns_empty |
| src/kanon_cli/commands/list.py | 336 | `return []` | test-needed | Early return on empty filtered results; same gap as line 335. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_all_versions_filtered_out_returns_empty |
| src/kanon_cli/commands/list.py | 337 | `(blank line)` | test-needed | Blank line; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 338 | `# For the all-versions output we do NOT clone each version...` | test-needed | Comment; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 339 | `# we clone the repo once at the newest version to obtain...` | test-needed | Comment; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 340 | `# names, then emit one row per (name, version)...` | test-needed | Comment; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 341 | `# This matches the spec worked-example...` | test-needed | Comment; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 342 | `# exist in the manifest repo's HEAD...` | test-needed | Comment; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 343 | `newest_ref = sorted_triples[0][0]` | test-needed | Extract newest-ref in `_list_all_versions_for_url`; uncovered. Same gap as line 314. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 344 | `newest_version_str = newest_ref.rsplit("/", 1)[-1]` | test-needed | Strip version from newest ref; same gap as line 314. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 345 | `(blank line)` | test-needed | Blank line; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 346 | `clone_dir = pathlib.Path(tempfile.mkdtemp(...))` | test-needed | Temp dir creation for manifest repo clone in `_list_all_versions_for_url`; uncovered. Add integration test that exercises this clone path with a real or fake git server. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 347 | `repo_dir = clone_dir / "repo"` | test-needed | Path construction for clone target; same gap as line 346. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 348 | `(blank line)` | test-needed | Blank line; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 349 | `clone_result = subprocess.run(` | test-needed | Git clone subprocess call in `_list_all_versions_for_url`; uncovered. Same gap as line 346. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 350 | `["git", "clone", "--depth", "1", ...],` | test-needed | Continuation of subprocess.run call; same gap as line 349. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 351 | `capture_output=True,` | test-needed | Continuation; same gap as line 349. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 352 | `text=True,` | test-needed | Continuation; same gap as line 349. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 353 | `check=False,` | test-needed | Continuation; same gap as line 349. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 354 | `)` | test-needed | Closing paren of subprocess.run; same gap as line 349. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 355 | `if clone_result.returncode != 0:` | test-needed | Clone failure guard in `_list_all_versions_for_url`; uncovered. Add test that monkeypatches subprocess.run to return a non-zero clone result. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_clone_failure_exits_with_error |
| src/kanon_cli/commands/list.py | 356 | `print(` | test-needed | Print start for clone-failure error message; same gap as line 355. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_clone_failure_exits_with_error |
| src/kanon_cli/commands/list.py | 357 | `f"ERROR: Failed to clone manifest repo..."` | test-needed | Error message string continuation; same gap as line 355. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_clone_failure_exits_with_error |
| src/kanon_cli/commands/list.py | 358 | `file=sys.stderr,` | test-needed | Print kwarg continuation; same gap as line 355. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_clone_failure_exits_with_error |
| src/kanon_cli/commands/list.py | 359 | `)` | test-needed | Closing paren of print; same gap as line 355. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_clone_failure_exits_with_error |
| src/kanon_cli/commands/list.py | 360 | `sys.exit(1)` | test-needed | Exit on clone failure; same gap as line 355. R66/R68. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_clone_failure_exits_with_error |
| src/kanon_cli/commands/list.py | 361 | `(blank line)` | test-needed | Blank line; non-executable. R66. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions |
| src/kanon_cli/commands/list.py | 362 | `catalog_names = _build_sorted_index(repo_dir)` | test-needed | Catalog index build from cloned repo in `_list_all_versions_for_url`; uncovered. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_successful_walk_returns_version_rows |
| src/kanon_cli/commands/list.py | 363 | `return _build_all_versions_rows(catalog_names, sorted_triples)` | test-needed | Return of all-versions rows; last line of `_list_all_versions_for_url`; uncovered. R66/R67. | tests/unit/test_list_coverage_gaps.py::TestWalkAllVersions::test_successful_walk_returns_version_rows |
| src/kanon_cli/core/lockfile.py | 320 | `raise LockfileValidationError(` | test-needed | `_validate_kanon_hash` raises on malformed hash value; no test passes an invalid kanon_hash string to trigger this raise. Add a unit test calling the validator with a non-matching hash string (e.g., `"sha256:badvalue"`). R66/R68. | tests/unit/test_lockfile_coverage_gaps.py::TestValidateKanonHash |
| src/kanon_cli/core/lockfile.py | 822 | `except Exception:` | test-needed | Inner exception handler in `write_lockfile_atomically`: cleans up tmp file if fdopen/flush/fsync fails; uncovered because no test injects a write-path I/O error. Add a unit test that monkeypatches `os.fsync` to raise OSError and verifies the temp file is unlinked. R66/R68. | tests/unit/test_lockfile_coverage_gaps.py::TestWriteLockfileInnerExceptionHandler |
| src/kanon_cli/core/lockfile.py | 823 | `tmp_path.unlink(missing_ok=True)` | test-needed | Temp file cleanup on write error; same gap as line 822. R66/R68. | tests/unit/test_lockfile_coverage_gaps.py::TestWriteLockfileInnerExceptionHandler |
| src/kanon_cli/core/lockfile.py | 824 | `raise` | test-needed | Re-raise after cleanup in inner exception handler; same gap as line 822. R66/R68. | tests/unit/test_lockfile_coverage_gaps.py::TestWriteLockfileInnerExceptionHandler |
| src/kanon_cli/core/lockfile.py | 826 | `except Exception:` | test-needed | Outer exception handler in `write_lockfile_atomically`: cleans up tmp file if the outer try block fails (e.g., `tempfile.mkstemp` or `os.replace` raises); uncovered because no test injects a failure at this level. Add a unit test that monkeypatches `os.replace` to raise OSError. R66/R68. | tests/unit/test_lockfile_coverage_gaps.py::TestWriteLockfileOuterExceptionHandler |
| src/kanon_cli/core/lockfile.py | 827 | `tmp_path.unlink(missing_ok=True)` | test-needed | Temp file cleanup in outer exception handler; same gap as line 826. R66/R68. | tests/unit/test_lockfile_coverage_gaps.py::TestWriteLockfileOuterExceptionHandler |
| src/kanon_cli/core/lockfile.py | 828 | `raise` | test-needed | Re-raise in outer exception handler; same gap as line 826. R66/R68. | tests/unit/test_lockfile_coverage_gaps.py::TestWriteLockfileOuterExceptionHandler |

## Summary

Total gap rows: 97 (18 in doctor.py, 72 in list.py, 7 in lockfile.py)
Total uncovered executable statements (Miss): 70 (17 in doctor.py, 46 in list.py, 7 in lockfile.py)
All 97 gaps are categorized `test-needed` -- no lines require `restructure-needed` or
`exclude-with-justification`. Every uncovered line is reachable by a test exercising an error
path, an edge-case branch, or an untested function (see Notes column for specific remediation).

R69 note: No defensive "should-never-happen" branches were found among the uncovered lines.
All uncovered lines represent legitimate error-handling paths and untested but reachable code
paths. Restructuring is not required; tests are the correct closure for every gap.

Consumed by: E15-F4-S1-T2 (close per-line coverage gaps), E15-F4-S1-T3 (per-command audit).

## Closure status

All 97 gap rows closed by E15-F4-S1-T2 (2026-05-21). New test files added:
- tests/unit/test_doctor_coverage_gaps.py -- 27 tests covering doctor.py gaps
- tests/unit/test_list_coverage_gaps.py -- 28 tests covering list.py gaps
- tests/unit/test_lockfile_coverage_gaps.py -- 14 tests covering lockfile.py gaps

Verified by: `uv run pytest --cov=src --cov-report=term-missing tests/unit -q`
Result: doctor.py 100%, list.py 100%, lockfile.py 100% (all 3 gap files at 100% line coverage).
