# Per-command happy + error path audit

Produced by: E15-F4-S1-T3
Date: 2026-05-21
Branch: feat/kanon-deps-work-2026-05
Spec ref: spec/cleanup-2026-05/impl-gaps-spec.md section 4.4 (AC-4.2)

## Scope

Ten new commands added by the feature branch under audit:

1. `kanon list`
2. `kanon add`
3. `kanon remove`
4. `kanon outdated`
5. `kanon why`
6. `kanon doctor`
7. `kanon catalog audit`
8. `kanon install`
9. `kanon completion`
10. `kanon bootstrap` (deprecation shim)

For each command the table enumerates at least one happy-path test and at
least one error-path test, assigns a Gap label, and records the closure plan.

Test categorization labels:
- `happy-path`: invokes the command with valid inputs; asserts exit 0 or
  expected stdout/side-effect.
- `error-path`: invokes the command with invalid inputs or fault injection;
  asserts non-zero exit AND expected stderr substring.

## Audit table

| Command | Happy-path tests (file::class::test_name) | Error-path tests (file::class::test_name) | Gap | Closure plan |
|---------|-------------------------------------------|-------------------------------------------|-----|--------------|
| `kanon list` | `tests/integration/test_list_default.py::TestListDefaultHappyPath::test_exits_0`; `tests/integration/test_list_default.py::TestListDefaultHappyPath::test_stdout_contains_three_sorted_entry_names`; `tests/integration/test_list_detail.py` (multiple); `tests/integration/test_list_tree.py` (multiple); `tests/integration/test_list_filter.py` (multiple); `tests/integration/test_list_format_json.py` (multiple); `tests/integration/test_list_all_versions.py` (multiple) | `tests/integration/test_list_default.py::TestListDefaultMissingCatalogSource::test_exits_nonzero_when_no_source`; `tests/integration/test_list_default.py::TestListDefaultMissingCatalogSource::test_stderr_contains_error_when_no_source` | none | Already covered -- no new test needed. |
| `kanon add` | `tests/integration/test_add_core.py::TestAddCoreCreateWithHeader::test_exit_0_on_happy_path`; `tests/integration/test_add_core.py::TestAddCoreCreateWithHeader::test_file_created_with_standard_header`; `tests/integration/test_add_dry_run.py::TestAddDryRun::test_dry_run_exits_0`; `tests/integration/test_add_dry_run.py::TestAddForce::test_force_exits_0` | `tests/integration/test_add_core.py::TestAddCoreUnknownEntry::test_unknown_entry_exits_nonzero`; `tests/integration/test_add_zero_tags.py::TestAddZeroTagsErrorPath::test_exits_nonzero`; `tests/integration/test_add_dry_run.py::TestAddCollisionError::test_collision_exits_nonzero` | none | Already covered -- no new test needed. |
| `kanon remove` | `tests/integration/test_remove_core.py::TestRemoveCoreHappyPath::test_source_name_input_removes_block`; `tests/integration/test_remove_core.py::TestRemoveCoreHappyPath::test_entry_name_input_removes_block`; `tests/integration/test_remove_dry_run.py` (multiple) | `tests/integration/test_remove_core.py::TestRemoveCoreErrorPaths::test_missing_kanon_file_exits_nonzero`; `tests/integration/test_remove_core.py::TestRemoveCoreErrorPaths::test_fewer_than_three_keys_exits_nonzero` | none | Already covered -- no new test needed. |
| `kanon outdated` | `tests/integration/test_outdated.py::TestOutdatedCoreTableOutput::test_row_content_with_lockfile`; `tests/integration/test_outdated.py::TestOutdatedCoreTableOutput::test_exit_code_zero_always`; `tests/integration/test_outdated_format_json.py` (multiple); `tests/integration/test_outdated_branch_drift.py` (multiple); `tests/integration/test_outdated_fail_on_upgrade.py` (multiple) | `tests/integration/test_outdated.py::TestOutdatedCoreTableOutput::test_missing_catalog_source_exits_nonzero`; `tests/integration/test_outdated.py::TestOutdatedCoreTableOutput::test_missing_kanon_file_exits_nonzero` | none | Already covered -- no new test needed. |
| `kanon why` | `tests/integration/test_why_chain_walker.py::TestWhyChainWalkerIntegration::test_single_chain_via_subprocess`; `tests/integration/test_why_chain_walker.py::TestWhyChainWalkerIntegration::test_chain_contains_source_name`; `tests/integration/test_why_format_json.py` (multiple); `tests/integration/test_why_ambiguous.py::TestWhyUrlOnlyMatch::test_url_only_match_exit_zero` | `tests/integration/test_why_chain_walker.py::TestWhyChainWalkerIntegration::test_not_found_exits_nonzero`; `tests/integration/test_why_ambiguous.py::TestWhyAmbiguousXmlPathAndSourceName::test_ambiguity_xml_path_and_source_name_exits_nonzero`; `tests/integration/test_why_not_found_suggestion.py::TestWhyNotFoundWithSuggestion::test_typo_in_source_name_includes_suggestion` | none | Already covered -- no new test needed. |
| `kanon doctor` | `tests/integration/test_doctor_consistency.py::TestDoctorAbsentLockfile::test_no_lockfile_exits_zero`; `tests/integration/test_doctor_consistency.py::TestDoctorBranchDrift::test_drift_without_strict_exits_zero`; `tests/integration/test_doctor_consistency.py::TestDoctorDanglingSha::test_reachable_sha_exits_zero`; `tests/integration/test_doctor_remote_check.py::TestDoctorRemoteReachabilityFullCli::test_all_reachable_remotes_no_warn_findings` | `tests/integration/test_doctor_consistency.py::TestDoctorAbsentKanonFile::test_no_kanon_file_exits_nonzero`; `tests/integration/test_doctor_consistency.py::TestDoctorHashMismatch::test_hash_mismatch_exits_nonzero`; `tests/integration/test_doctor_consistency.py::TestDoctorOrphanLock::test_orphan_lock_exits_nonzero`; `tests/integration/test_doctor_consistency.py::TestDoctorDanglingSha::test_dangling_sha_exits_nonzero` | none | Already covered -- no new test needed. |
| `kanon catalog audit` | `tests/integration/test_catalog_audit_strict.py` (strict-mode happy paths -- XML passes all checks); `tests/integration/test_catalog_audit_metadata.py` (well-formed metadata happy paths); `tests/integration/test_catalog_audit_framework.py::TestCatalogAuditHelp::test_help_exits_0` | `tests/integration/test_catalog_audit_strict.py` (strict-mode rejection paths); `tests/integration/test_catalog_audit_tag_format.py` (tag format violation paths); `tests/integration/test_catalog_audit_framework.py::TestCatalogAuditArgparseErrors::test_invalid_check_value_exits_2`; `tests/integration/test_catalog_audit_framework.py::TestCatalogAuditArgparseErrors::test_all_mixed_with_other_exits_2` | none | Already covered -- no new test needed. |
| `kanon install` | `tests/integration/test_install_required_vars.py::TestInstallAllVarsPresent::test_install_proceeds_when_all_required_vars_supplied`; `tests/integration/test_install_paths.py` (path resolution happy paths); `tests/integration/test_install_lock_file_derivation.py` (happy path lock file derivation) | `tests/integration/test_install_errors.py::TestParseFailureExitsOne::test_no_sources_defined_exits_1_with_parse_error`; `tests/integration/test_install_errors.py::TestGitSyncFailureExitsOne::test_repo_sync_failure_exits_1`; `tests/integration/test_install_required_vars.py::TestInstallMissingRequiredVars::test_install_exits_1_when_required_var_missing` | none | Already covered -- no new test needed. |
| `kanon completion` | `tests/integration/test_completion_subcommand.py::test_completion_bash_exit_zero`; `tests/integration/test_completion_subcommand.py::test_completion_zsh_exit_zero`; `tests/integration/test_completion_bash.py::test_bash_version_gte_4`; `tests/functional/test_completion_snapshots.py::test_completion_snapshot_matches_fixture` | `tests/integration/test_completion_subcommand.py::test_completion_fish_exits_nonzero`; `tests/integration/test_completion_subcommand.py::test_completion_fish_stderr_names_valid_choices` | none | Already covered -- no new test needed. |
| `kanon bootstrap` shim | `tests/integration/test_bootstrap_help.py::TestBootstrapHelpSnapshot::test_exit_code_is_zero`; `tests/integration/test_bootstrap_help.py::TestBootstrapHelpSnapshot::test_stdout_matches_fixture_byte_for_byte` (see note below re: happy-path semantics) | `tests/integration/test_bootstrap_shim.py::TestBootstrapShimKanonPackage::test_exit_code_is_3`; `tests/integration/test_bootstrap_shim.py::TestBootstrapShimListSubcommand::test_exit_code_is_3`; `tests/functional/test_bootstrap_errors.py::TestBootstrapShimAnyPackageExits3::test_any_package_name_exits_3` | none | Already covered -- no new test needed. |

## Gap summary

All 10 commands in scope have at least one happy-path test and at least one
error-path test in `tests/functional/` or `tests/integration/`. No command
has an open gap. No new test files were required.

| Command | Happy covered | Error covered | Gap |
|---------|--------------|---------------|-----|
| `kanon list` | yes | yes | none |
| `kanon add` | yes | yes | none |
| `kanon remove` | yes | yes | none |
| `kanon outdated` | yes | yes | none |
| `kanon why` | yes | yes | none |
| `kanon doctor` | yes | yes | none |
| `kanon catalog audit` | yes | yes | none |
| `kanon install` | yes | yes | none |
| `kanon completion` | yes | yes | none |
| `kanon bootstrap` shim | yes | yes | none |

## Notes on bootstrap shim happy-path classification

The `kanon bootstrap` shim is a pure deprecation redirect: every invocation
with a package argument exits 3 (the documented shim exit code). The shim's
"happy path" is `kanon bootstrap --help`, which exits 0 and emits the
migration guide. This is tested by
`tests/integration/test_bootstrap_help.py::TestBootstrapHelpSnapshot::test_exit_code_is_zero`.
The "error path" consists of any actual deprecated invocation (e.g.,
`kanon bootstrap kanon`), which exits 3 with a WARN message and performs no
filesystem mutation. This is tested by
`tests/integration/test_bootstrap_shim.py::TestBootstrapShimKanonPackage::test_exit_code_is_3`.

## Notes on pre-existing baseline failures

The following test files contain pre-existing failures that are NOT related
to this task. They are documented here per the standard baseline-failure
check requirement (AC-CYCLE-001):

- `tests/integration/test_install_lifecycle.py` -- multiple classes fail
  with `MissingCatalogSourceError` because the fixtures do not set
  `KANON_CATALOG_SOURCE`. These are pre-existing failures from the
  bootstrap-deprecation migration gap (documented in
  `spec/cleanup-2026-05/_workspace/ci_failures.md`).
- `tests/functional/test_cli_entry_point.py::TestKanonBootstrapList` and
  `TestKanonBootstrapKanon` -- expect old bootstrap behavior (exit 0); the
  shim exits 3. These pre-date this task.
- `tests/functional/test_exit_code_matrix.py::TestInstallSuccessExitsZero`
  -- fails due to missing catalog source; pre-existing.

The tests in scope for this audit (the per-command happy + error path
verification set) all pass as documented in the table above.

## Verification commands

Run the representative happy+error path tests for all 10 commands:

```
uv run pytest \
  tests/integration/test_list_default.py \
  tests/integration/test_add_core.py \
  tests/integration/test_add_zero_tags.py \
  tests/integration/test_remove_core.py \
  tests/integration/test_outdated.py \
  tests/integration/test_why_chain_walker.py \
  tests/integration/test_why_ambiguous.py \
  tests/integration/test_doctor_consistency.py \
  tests/integration/test_catalog_audit_strict.py \
  tests/integration/test_catalog_audit_metadata.py \
  tests/integration/test_install_required_vars.py \
  tests/integration/test_install_errors.py::TestParseFailureExitsOne \
  tests/integration/test_install_errors.py::TestGitSyncFailureExitsOne \
  tests/integration/test_completion_subcommand.py \
  tests/integration/test_bootstrap_shim.py \
  tests/integration/test_bootstrap_help.py \
  tests/functional/test_bootstrap_errors.py \
  tests/functional/test_bootstrap_list_and_default_target.py \
  tests/functional/test_completion_snapshots.py \
  -q
```

See AC-CYCLE-001 evidence in the work unit TDD Cycle Log for the verified
exit code.
