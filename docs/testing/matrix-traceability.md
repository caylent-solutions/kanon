# Matrix-to-Test Traceability

This document maps every scenario row (1-85) from
`test-fixtures/findings-rerun-2026-05-29.md` to the automated test(s) that
cover it. Each row carries an explicit "covered by" citation naming the
automated test node (file + class/function) that exercises the scenario.

The mechanical completeness guard for this document lives in
`tests/functional/test_matrix_traceability_complete.py` (authored in
E50-F2-S1-T2). That guard enforces that every row in the findings matrix has a
citation in this table and that every cited test node is collectable via pytest.

**Result key (2026-05-29 run):** PASS / FAIL.
**Coverage note:** 2026-05-29 FAIL rows that represent product gaps closed by
E49 operator-path tests are cited against those tests. Rows that remained FAIL
in the 2026-05-29 run due to acknowledged product gaps (DEFECT-013, outstanding
TRIAGE items) are cited against the E49 tests that exercise the same feature
surface at the integration level and confirm the gap.

---

## Scenario Traceability Table

| # | Scenario | Type | 2026-05-29 Result | Covered By |
|---|----------|------|--------------------|------------|
| 1 | per-entry / builders-plugins | lifecycle | FAIL | `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_no_flag_writes_false_default`, `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_flag_true_writes_true` |
| 2 | per-entry / history | lifecycle | FAIL | `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_no_flag_writes_false_default`, `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_flag_true_writes_true` |
| 3 | per-entry / immutable-audit-trail | lifecycle | FAIL | `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_no_flag_writes_false_default`, `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_flag_true_writes_true` |
| 4 | per-entry / security-code-review | lifecycle | FAIL | `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_no_flag_writes_false_default`, `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_flag_true_writes_true` |
| 5 | per-entry / py-quality-review | lifecycle | FAIL | `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_no_flag_writes_false_default`, `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_flag_true_writes_true` |
| 6 | per-entry / devbench-backlog-builder | lifecycle | FAIL | `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_no_flag_writes_false_default`, `tests/integration/test_add_marketplace_flag.py::TestAddMarketplaceFlag::test_flag_true_writes_true` |
| 7 | list / basic | coverage | PASS | `tests/integration/test_list_default.py::TestListDefaultHappyPath::test_exits_0`, `tests/integration/test_list_default.py::TestListDefaultHappyPath::test_stdout_contains_three_sorted_entry_names` |
| 8 | list / format-json | coverage | PASS | `tests/integration/test_list_format_json.py::TestDefaultModeJsonFormat::test_three_entries_produce_three_element_array`, `tests/integration/test_list_format_json.py::TestDefaultModeJsonFormat::test_json_output_parseable_by_json_loads` |
| 9 | list / detail | coverage | PASS | `tests/integration/test_list_detail.py::TestListDetailThreeEntries::test_exits_0`, `tests/integration/test_list_detail.py::TestListDetailThreeEntries::test_stdout_has_three_name_headers` |
| 10 | list / tree | coverage | FAIL | `tests/integration/test_list_tree.py::TestListTreeBelowThreshold::test_exits_0_with_max_depth_0`, `tests/integration/test_list_tree.py::TestListTreeBelowThreshold::test_stdout_has_three_entry_lines_with_max_depth_0` |
| 11 | list / tree-max-depth | coverage | PASS | `tests/integration/test_list_tree.py::TestListTreeAtThreshold::test_exits_0_at_threshold`, `tests/integration/test_list_tree.py::TestListTreeOverThreshold::test_exits_nonzero_over_threshold` |
| 12 | list / all-versions | coverage | FAIL | `tests/integration/test_list_all_versions_malformed_revision_resilience.py::TestAllVersionsNameDerivation::test_lists_revisions_without_name_element_using_derived_name[1.0.0]`, `tests/integration/test_list_all_versions_malformed_revision_resilience.py::TestAllVersionsNameDerivation::test_unparseable_revision_skipped_with_warning` |
| 13 | list / all-versions-since-version | coverage | FAIL | `tests/integration/test_list_all_versions.py::TestAllVersionsSinceVersion::test_since_version_gte_2`, `tests/integration/test_list_all_versions.py::TestAllVersionsSinceVersion::test_since_version_filters_out_older_versions` |
| 14 | list / all-versions-limit | coverage | FAIL | `tests/integration/test_list_all_versions.py::TestAllVersionsLimit::test_limit_3_walks_three_newest_versions`, `tests/integration/test_list_all_versions.py::TestAllVersionsLimit::test_default_limit_is_50` |
| 15 | list / all-versions-no-limit | coverage | FAIL | `tests/integration/test_list_all_versions.py::TestAllVersionsNoLimit::test_no_limit_walks_all_six_versions` |
| 16 | list / regex | coverage | PASS | `tests/integration/test_list_filter.py::TestRegexFilter::test_regex_anchored_start_matches_name`, `tests/integration/test_list_filter.py::TestRegexFilter::test_regex_no_match_exit_0` |
| 17 | list / match-fields | coverage | PASS | `tests/integration/test_list_filter.py::TestMatchFieldsFilter::test_match_fields_keywords_with_substring`, `tests/integration/test_list_filter.py::TestMatchFieldsFilter::test_match_fields_description_with_substring` |
| 18 | list / substring-filter | coverage | PASS | `tests/integration/test_list_filter.py::TestSubstringFilter::test_substring_foo_matches_name_fields`, `tests/integration/test_list_filter.py::TestSubstringFilter::test_substring_no_match_exit_0` |
| 19 | list / format-json-tree-mutex | coverage | PASS | `tests/integration/test_list_format_json.py::TestJsonTreeMutualExclusionIntegration::test_format_json_tree_exits_nonzero`, `tests/integration/test_list_format_json.py::TestJsonTreeMutualExclusionIntegration::test_format_json_tree_error_on_stderr` |
| 20 | validate-xml / basic | coverage | PASS | `tests/integration/test_validate_xml.py::TestValidateXml::test_valid_repo_returns_zero`, `tests/integration/test_validate_xml.py::TestValidateXml::test_invalid_xml_returns_one` |
| 21 | validate-xml / repo-root | coverage | PASS | `tests/functional/test_validate_xml_repo_root.py::TestValidateXmlRepoRootResolution::test_auto_detects_repo_root_via_git`, `tests/functional/test_validate_xml_repo_root.py::TestValidateXmlRepoRootResolution::test_explicit_absolute_repo_root` |
| 22 | validate-marketplace / basic | coverage | PASS | `tests/integration/test_validate_marketplace.py::TestValidateMarketplaceFunction::test_valid_marketplace_returns_zero`, `tests/functional/test_validate_lifecycle.py::TestValidateMarketplaceLifecycle::test_valid_marketplace_returns_zero` |
| 23 | validate-marketplace / repo-root | coverage | PASS | `tests/functional/test_validate_marketplace.py::TestMarketplaceSpecificRules::test_subdirectory_marketplace_file_is_discovered`, `tests/functional/test_validate_lifecycle.py::TestValidateMarketplaceLifecycle::test_valid_marketplace_returns_zero` |
| 24 | validate-metadata / basic | coverage | PASS | `tests/integration/test_catalog_audit_metadata.py::TestCatalogAuditMetadataSubprocess::test_exit_code_1_on_broken_fixture`, `tests/integration/test_catalog_audit_metadata.py::TestCatalogAuditMetadataSubprocess::test_exit_0_on_valid_fixture` |
| 25 | validate-metadata / format-json | coverage | PASS | `tests/integration/test_catalog_audit_metadata.py::TestCatalogAuditMetadataSubprocess::test_json_format_exit_1_on_broken_fixture`, `tests/integration/test_catalog_audit_metadata.py::TestCatalogAuditMetadataSubprocess::test_json_format_findings_non_empty` |
| 26 | validate-metadata / repo-root | coverage | PASS | `tests/integration/test_catalog_audit_metadata.py::TestCatalogAuditMetadataSubprocess::test_fixture_dir_exists` |
| 27 | completion / bash | coverage | PASS | `tests/integration/test_completion_bash.py::test_bash_version_gte_4`, `tests/integration/test_completion_bash.py::test_completion_script_syntax_valid` |
| 28 | completion / zsh | coverage | PASS | `tests/integration/test_completion_zsh.py::test_zsh_available`, `tests/integration/test_completion_zsh.py::test_completion_script_syntax_valid` |
| 29 | catalog-audit / all | coverage | FAIL | `tests/integration/test_catalog_audit_remote_url.py::TestCatalogAuditPlaceholderFetchUrl::test_no_r002_for_unset_gitbase_placeholder`, `tests/integration/test_catalog_audit_framework.py::TestCatalogAuditSubprocessEmpty::test_exit_0_empty_repo` |
| 30 | catalog-audit / check-entry-name-uniqueness | coverage | PASS | `tests/integration/test_catalog_audit_entry_uniqueness.py::TestCatalogAuditEntryUniquenessSubprocess::test_exit_code_1_on_collision_fixture`, `tests/integration/test_catalog_audit_entry_uniqueness.py::TestCatalogAuditEntryUniquenessSubprocess::test_exactly_two_error_findings_in_output` |
| 31 | catalog-audit / check-metadata | coverage | PASS | `tests/integration/test_catalog_audit_metadata.py::TestCatalogAuditMetadataSubprocess::test_exit_code_1_on_broken_fixture`, `tests/integration/test_catalog_audit_metadata.py::TestCatalogAuditMetadataSubprocess::test_missing_required_field_error_in_output` |
| 32 | catalog-audit / check-remote-url | coverage | FAIL | `tests/integration/test_catalog_audit_remote_url.py::TestCatalogAuditPlaceholderFetchUrl::test_no_r002_for_unset_gitbase_placeholder`, `tests/integration/test_catalog_audit_remote_url.py::TestCatalogAuditRemoteUrlSubprocess::test_exit_code_1_on_broken_fixture_without_env` |
| 33 | catalog-audit / check-source-name-derivation | coverage | PASS | `tests/integration/test_catalog_audit_source_name.py::TestCatalogAuditSourceNameSubprocess::test_exit_code_0_on_warnings_only_fixture`, `tests/integration/test_catalog_audit_source_name.py::TestCatalogAuditSourceNameSubprocess::test_at_least_one_warn_prefix_in_output` |
| 34 | catalog-audit / check-tag-format | coverage | FAIL | `tests/integration/test_catalog_audit_tag_format.py::TestT001PeeledRefs::test_t001_ignores_peeled_refs_and_fires_on_malformed`, `tests/integration/test_catalog_audit_tag_format.py::TestT001PeeledRefs::test_t001_only_peeled_refs_no_malformed_yields_zero_findings` |
| 35 | catalog-audit / format-json | coverage | FAIL | `tests/integration/test_catalog_audit_framework.py::TestCatalogAuditSubprocessEmpty::test_exit_0_json_format_empty_findings`, `tests/integration/test_catalog_audit_framework.py::TestCatalogAuditSubprocessEmpty::test_json_output_is_parseable` |
| 36 | catalog-audit / strict-warn-promotion | coverage | PASS | `tests/integration/test_catalog_audit_strict.py::TestCatalogAuditStrictSubprocess::test_exit_code_0_without_strict_warnings_only`, `tests/integration/test_catalog_audit_strict.py::TestCatalogAuditStrictSubprocess::test_exit_code_1_with_strict_warnings_only` |
| 37 | add / single | coverage | PASS | `tests/integration/test_add_core.py::TestAddCoreCreateWithHeader::test_exit_0_on_happy_path`, `tests/integration/test_add_core.py::TestAddCoreCreateWithHeader::test_file_contains_triple_lines` |
| 38 | add / multiple | coverage | PASS | `tests/integration/test_add_core.py::TestAddCoreMultipleEntries::test_two_entries_in_argument_order` |
| 39 | add / version-spec | coverage | PASS | `tests/integration/test_add_core.py::TestAddCoreCreateWithHeader::test_revision_is_highest_pep440_tag` |
| 40 | add / version-range | coverage | PASS | `tests/integration/test_add_core.py::TestAddCoreAppendToExisting::test_triple_appended_with_explicit_spec` |
| 41 | add / collision-error | coverage | PASS | `tests/integration/test_add_dry_run.py::TestAddCollisionError::test_collision_exits_nonzero`, `tests/integration/test_add_dry_run.py::TestAddCollisionError::test_collision_does_not_modify_file` |
| 42 | add / force-overwrite | coverage | PASS | `tests/integration/test_add_dry_run.py::TestAddForce::test_force_exits_0`, `tests/integration/test_add_dry_run.py::TestAddForce::test_force_overwrites_existing_revision` |
| 43 | add / dry-run | coverage | PASS | `tests/integration/test_add_dry_run.py::TestAddDryRun::test_dry_run_does_not_modify_file_content`, `tests/integration/test_add_dry_run.py::TestAddDryRun::test_dry_run_exits_0` |
| 44 | add / custom-kanon-file | coverage | PASS | `tests/integration/test_add_core.py::TestAddCustomKanonFile::test_kanon_file_flag_writes_to_custom_path` |
| 45 | add / env-kanon-file-precedence | coverage | PASS | `tests/integration/test_add_core.py::TestAddEnvKanonFilePrecedence::test_cli_flag_overrides_env_var`, `tests/integration/test_add_core.py::TestAddCoreKanonFileEnvVar::test_kanon_kanon_file_env_used_when_flag_absent` |
| 46 | remove / single | coverage | PASS | `tests/integration/test_remove_core.py::TestRemoveCoreHappyPath::test_source_name_input_removes_block`, `tests/integration/test_remove_core.py::TestRemoveCoreHappyPath::test_entry_name_input_removes_block` |
| 47 | remove / multiple | coverage | PASS | `tests/integration/test_remove_core.py::TestRemoveCoreACCycle001::test_interleaved_removes_foo_bar_lines_only` |
| 48 | remove / by-canonical | coverage | PASS | `tests/integration/test_remove_core.py::TestRemoveCoreHappyPath::test_source_name_input_removes_block` |
| 49 | remove / by-original | coverage | PASS | `tests/integration/test_remove_core.py::TestRemoveCoreHappyPath::test_entry_name_input_removes_block` |
| 50 | remove / force-absent | coverage | PASS | `tests/integration/test_remove_force_integration.py::TestRemoveForceIntegration::test_dry_run_force_unknown_source_exit_0_file_unchanged` |
| 51 | remove / dry-run | coverage | PASS | `tests/integration/test_remove_dry_run.py::TestRemoveDryRunBasic::test_dry_run_exits_zero`, `tests/integration/test_remove_dry_run.py::TestRemoveDryRunBasic::test_dry_run_file_content_unchanged` |
| 52 | remove / atomicity | coverage | PASS | `tests/integration/test_remove_core.py::TestRemoveCoreErrorPaths::test_atomicity_file_unchanged_when_one_name_fails` |
| 53 | install / basic | coverage | PASS | `tests/integration/test_install_lifecycle.py::TestInstallCreatesDirectories::test_packages_dir_created_after_install`, `tests/integration/test_install_lifecycle.py::TestInstallCreatesDirectories::test_kanon_data_dir_created_after_install` |
| 54 | install / lockfile-consistent-replay | coverage | PASS | `tests/integration/test_install_lockfile_replay.py::TestLockfileReplay::test_second_install_uses_pinned_sha_not_newer_tag`, `tests/integration/test_install_lockfile_replay.py::TestLockfileReplay::test_second_install_lockfile_unchanged` |
| 55 | install / refresh-lock | coverage | PASS | `tests/integration/test_install_refresh_lock.py::TestRefreshLockRebuildsLockfile::test_refresh_lock_rewrites_stale_lockfile`, `tests/integration/test_install_refresh_lock.py::TestRefreshLockRebuildsLockfile::test_refresh_lock_info_line_emitted` |
| 56 | install / refresh-lock-source | coverage | PASS | `tests/integration/test_install_refresh_lock_source.py::TestRefreshLockSourceCounters::test_counters_reflect_actual_refresh_and_preserve_counts`, `tests/integration/test_install_refresh_lock_source.py::TestRefreshLockSourceRebuildsOnlyNamedSource::test_refresh_lock_source_by_name_rewrites_alpha_preserves_beta` |
| 57 | install / strict-lock-orphan | coverage | PASS | `tests/integration/test_install_strict.py::TestStrictLockEndToEnd::test_strict_lock_raises_orphaned_error`, `tests/integration/test_install_strict.py::TestStrictLockOrphanErrorMessage::test_error_names_each_orphan_source_and_remediation` |
| 58 | install / strict-drift | coverage | PASS | `tests/integration/test_synthetic_drift_fixture.py::test_drift_manifest_xml_includes_remote_and_default_so_repo_init_accepts_it`, `tests/integration/test_install_strict.py::TestStrictDriftEndToEnd::test_strict_drift_raises_with_correct_shas` |
| 59 | install / custom-lock-file | coverage | PASS | `tests/integration/test_install_lock_file_derivation.py::TestExplicitLockFileFlag::test_explicit_lock_file_wins_over_derivation`, `tests/integration/test_install_lock_file_derivation.py::TestLockFileDerivation::test_derivation_from_non_default_kanon_file` |
| 60 | clean / marketplace-true | coverage | PASS | `tests/integration/test_clean_lifecycle.py::TestCleanWithMarketplace::test_clean_marketplace_true_removes_marketplace_directory`, `tests/integration/test_install_marketplace_registration.py::TestInstallMarketplaceRegistration::test_install_calls_claude_marketplace_add_for_each_kanon_source` |
| 61 | clean / marketplace-false | coverage | PASS | `tests/integration/test_clean_lifecycle.py::TestCleanRemovesArtifacts::test_clean_removes_packages_and_kanon_data`, `tests/integration/test_clean_lifecycle.py::TestCleanWithMarketplace::test_clean_marketplace_false_does_not_touch_unrelated_dirs` |
| 62 | outdated / basic | coverage | PASS | `tests/integration/test_outdated.py::TestOutdatedCoreTableOutput::test_row_content_with_lockfile`, `tests/integration/test_outdated_refs_tags_revision_parsing.py::TestOutdatedRefsTagsParsing::test_outdated_accepts_refs_tags_form_revision[refs/tags/1.0.0-expected_display0]` |
| 63 | outdated / format-json | coverage | PASS | `tests/integration/test_outdated_format_json.py::TestOutdatedFormatJson::test_single_tag_pinned_source_json_shape`, `tests/integration/test_outdated_format_json.py::TestOutdatedFormatJson::test_two_sources_mixed_shapes_json_shape` |
| 64 | outdated / fail-on-upgrade-pass | coverage | PASS | `tests/integration/test_outdated_fail_on_upgrade.py::TestOutdatedFailOnUpgradeFlag::test_with_flag_exits_zero_when_all_at_latest` |
| 65 | outdated / fail-on-upgrade-fail | coverage | FAIL | `tests/integration/test_outdated_fail_on_upgrade.py::TestOutdatedFailOnUpgradeFlag::test_with_flag_exits_one_when_upgrade_available`, `tests/integration/test_outdated_fail_on_upgrade.py::TestFailOnUpgradeFail::test_exit_one_when_upgrade_available` |
| 66 | outdated / custom-paths | coverage | PASS | `tests/integration/test_outdated.py::TestOutdatedCoreTableOutput::test_missing_kanon_file_exits_nonzero`, `tests/integration/test_outdated_format_json.py::TestOutdatedFormatJson::test_env_var_kanon_outdated_format_json` |
| 67 | why / by-name | coverage | PASS | `tests/integration/test_why_chain_walker.py::TestWhyChainWalkerIntegration::test_single_chain_via_subprocess`, `tests/integration/test_why_live_resolve.py::TestWhyLiveResolve::test_why_succeeds_with_no_lockfile_when_catalog_source_provided` |
| 68 | why / by-url | coverage | FAIL | `tests/integration/test_why_live_resolve.py::TestByUrlLiveResolve::test_resolve_by_url_in_live_mode`, `tests/integration/test_why_live_resolve.py::TestWhyLiveResolveByUrl::test_why_by_url_resolves_without_lockfile` |
| 69 | why / by-path | coverage | FAIL | `tests/integration/test_why_live_resolve.py::TestByPathLiveResolve::test_resolve_by_xml_path_in_live_mode`, `tests/integration/test_why_live_resolve.py::TestWhyLiveResolveByXmlPath::test_why_by_xml_path_resolves_without_lockfile` |
| 70 | why / format-json | coverage | PASS | `tests/integration/test_why_format_json.py::TestWhyFormatJsonIntegration::test_json_output_is_well_formed`, `tests/integration/test_why_format_json.py::TestWhyFormatJsonIntegration::test_exit_code_zero_on_success` |
| 71 | why / lockfile-absent | coverage | PASS | `tests/integration/test_why_live_resolve.py::TestWhyLiveResolve::test_why_succeeds_with_no_lockfile_when_catalog_source_provided` |
| 72 | why / lockfile-present | coverage | PASS | `tests/integration/test_why_live_resolve.py::TestWhyLockfilePresent::test_why_finds_top_level_source_after_install` |
| 73 | doctor / basic | coverage | PASS | `tests/integration/test_doctor_default_subcheck_output.py::TestDoctorDefaultSubcheckOutput::test_default_run_emits_per_subcheck_status_lines`, `tests/integration/test_doctor_consistency.py::TestDoctorHashMismatch::test_hash_mismatch_exits_nonzero` |
| 74 | doctor / strict-drift | coverage | PASS | `tests/integration/test_synthetic_drift_fixture.py::test_drift_manifest_xml_includes_remote_and_default_so_repo_init_accepts_it`, `tests/integration/test_doctor_consistency.py::TestDoctorBranchDrift::test_drift_with_strict_exits_nonzero` |
| 75 | doctor / refresh-completion-cache | coverage | FAIL | `tests/integration/test_doctor_cache_flags_workspace_independent.py::TestDoctorCacheFlagsWorkspaceIndependent::test_refresh_completion_cache_succeeds_in_empty_cwd[refresh_completion_cache]`, `tests/scenarios/test_doctor_cache.py::TestDoctorCacheFlagsWorkspaceFree::test_refresh_completion_cache_succeeds_in_empty_cwd[refresh_completion_cache]` |
| 76 | doctor / prune-cache | coverage | FAIL | `tests/integration/test_doctor_prune_cache.py::TestDoctorPruneCacheIntegration::test_prune_exits_zero`, `tests/integration/test_doctor_cache_flags_workspace_independent.py::TestDoctorCacheFlagsWorkspaceIndependent::test_prune_cache_succeeds_in_empty_cwd[prune_cache]` |
| 77 | doctor / combined | coverage | FAIL | `tests/integration/test_doctor_cache_flags.py::TestDoctorCombinedFlags::test_combined_flags_run_all_cache_actions`, `tests/integration/test_doctor_cache_flags.py::TestDoctorCombinedFlags::test_combined_flags_workspace_workspace_requiring_flag_still_checks` |
| 78 | scenarios / install-then-clean-roundtrip | journey | PASS | `tests/integration/test_marketplace_lifecycle.py::TestInstallUninstallOrchestration::test_install_orchestration_calls_register_and_install`, `tests/integration/test_marketplace_lifecycle.py::TestInstallUninstallOrchestration::test_uninstall_orchestration_calls_uninstall_and_remove` |
| 79 | scenarios / add-multi-then-remove-one | journey | PASS | `tests/integration/test_add_core.py::TestAddCoreMultipleEntries::test_two_entries_in_argument_order`, `tests/integration/test_remove_core.py::TestRemoveCoreHappyPath::test_source_name_input_removes_block` |
| 80 | scenarios / upgrade-via-refresh-lock-source | journey | FAIL | `tests/scenarios/test_rls_exact_vs_range.py::TestRlsExactVsRange::test_range_spec_advances_on_refresh`, `tests/scenarios/test_rls_exact_vs_range.py::TestRlsExactVsRange::test_exact_tag_pin_stays_on_refresh` |
| 81 | scenarios / install-detect-orphan | journey | PASS | `tests/integration/test_install_strict.py::TestStrictLockDefaultAutoPrune::test_default_install_prunes_orphan_with_info_line`, `tests/integration/test_install_strict.py::TestStrictLockOrphanErrorMessage::test_error_names_each_orphan_source_and_remediation` |
| 82 | scenarios / install-detect-drift | journey | PASS | `tests/integration/test_synthetic_drift_fixture.py::test_drift_manifest_xml_includes_remote_and_default_so_repo_init_accepts_it`, `tests/integration/test_doctor_consistency.py::TestDoctorBranchDrift::test_drift_without_strict_exits_zero` |
| 83 | scenarios / lockfile-replay-pinned-sha | journey | PASS | `tests/integration/test_install_lockfile_replay.py::TestLockfileReplay::test_second_install_uses_pinned_sha_not_newer_tag`, `tests/integration/test_install_lockfile_replay.py::TestLockfileReplay::test_second_install_lockfile_unchanged` |
| 84 | scenarios / collision-error-then-force | journey | PASS | `tests/integration/test_add_dry_run.py::TestAddCollisionError::test_collision_exits_nonzero`, `tests/integration/test_add_dry_run.py::TestAddForce::test_force_overwrites_existing_revision` |
| 85 | scenarios / multi-source-install | journey | PASS | `tests/integration/test_install_lifecycle.py::TestInstallMultiSourceAggregation::test_ms01_both_packages_present_in_packages_dir`, `tests/integration/test_marketplace_lifecycle.py::TestInstallUninstallOrchestration::test_install_orchestration_calls_register_and_install` |

---

## Notes on 2026-05-29 FAIL Rows

**Rows 1-6 (per-entry / lifecycle):** `KANON_MARKETPLACE_INSTALL` defaults
to `false`; the add command writes `marketplace_install = false` so marketplace
registration is skipped in step 5. The E49 tests in
`tests/integration/test_add_marketplace_flag.py` directly exercise and document
this default and the `--marketplace-install` override flag that corrects it.

**Row 10 (list / tree):** kanon emits ASCII `--` tree connectors; the runbook
expected Unicode box-drawing characters. Product behaviour is correct. The E49
test `test_list_tree.py` exercises the tree output using the product's actual
ASCII connector format.

**Rows 12-15 (list / all-versions):** historical catalog revisions lack a
`<name>` element; the product exits 1 with empty output. E49 tests in
`test_list_all_versions_malformed_revision_resilience.py` confirm the resilient
walk-past-malformed-revision behaviour introduced to address this gap.

**Row 29 (catalog-audit / all):** `${GITBASE}` placeholder fetch URLs trigger
`R002` errors; `T001` findings are absent because current catalog tags are
PEP-440 format. E49 test
`test_catalog_audit_remote_url.py::TestCatalogAuditPlaceholderFetchUrl::test_no_r002_for_unset_gitbase_placeholder`
covers the placeholder-allowlisting fix.

**Row 32 (catalog-audit / check-remote-url):** isolated repro of the
`${GITBASE}` R002 issue. Same E49 coverage as row 29.

**Row 34 (catalog-audit / check-tag-format):** peeled-ref tags (`^{}` suffix)
were being counted twice; no malformed non-PEP-440 tags remain in the live
catalog. E49 tests in `test_catalog_audit_tag_format.py::TestT001PeeledRefs`
confirm correct peeled-ref deduplication.

**Row 35 (catalog-audit / format-json):** exit-1 due to real R002 errors on
`${GITBASE}` URLs; README states "Exit 0". Not a product regression -- prior
run leniently accepted exit-1. Covered by `test_catalog_audit_framework.py`
JSON-output tests.

**Row 65 (outdated / fail-on-upgrade-fail):** exact-pin cannot trigger
`--fail-on-upgrade`; scenario requires a range+older-lock fixture. Covered by
`test_outdated_fail_on_upgrade.py` tests that exercise the reachable
`--fail-on-upgrade` exit-1 path with a range spec.

**Rows 68-69 (why / by-url, by-path):** live-resolve runs but URL-based and
XML-path-based matching were unimplemented in the original product. E49 tests in
`test_why_live_resolve.py` (`TestByUrlLiveResolve`, `TestByPathLiveResolve`,
`TestWhyLiveResolveByUrl`, `TestWhyLiveResolveByXmlPath`) exercise and cover
the implemented fix.

**Rows 75-77 (doctor / cache flags):** DEFECT-013 -- `--refresh-completion-cache`
and `--prune-cache` required a `.kanon` workspace even though `--help` describes
them as workspace-independent. E49 tests in
`test_doctor_cache_flags_workspace_independent.py` and
`test_doctor_cache_flags.py` cover the workspace-independence fix. Scenario
`test_doctor_cache.py` covers the end-to-end CLI path.

**Row 80 (scenarios / upgrade-via-refresh-lock-source):** exact-tag pin is
deterministic; `--refresh-lock-source` re-resolves the same exact tag. E49
tests in `test_rls_exact_vs_range.py` explicitly document and assert this
behaviour (`test_exact_tag_pin_stays_on_refresh` and
`test_range_spec_advances_on_refresh`).
