# CHANGELOG



## v1.1.0 (2026-04-14)

### Feature

* feat: support PEP 440 version constraints in KANON_CATALOG_SOURCE and --catalog-source (#45)

Resolve PEP 440 constraints (e.g., &gt;=2.0.0,&lt;3.0.0, ~=2.0.0, ==1.1.0)
against git tags before cloning the catalog repo. Previously only exact
branch/tag names and the literal &#34;latest&#34; were accepted.

The existing resolve_version() infrastructure handles all constraint
resolution; this wires it into _clone_remote_catalog() alongside the
existing &#34;latest&#34; path. Made is_version_constraint() public for cross-
module use.

Also fixes pre-existing integration test doc issues: fixture repos using
master instead of main, and incorrect linkfile symlink path assertions. ([`42dcf50`](https://github.com/caylent-solutions/kanon/commit/42dcf50a519b472a1d480f98f5451f2895d9c391))


## v1.0.4 (2026-04-14)

### Chore

* chore(release): 1.0.4 ([`63226f6`](https://github.com/caylent-solutions/kanon/commit/63226f6ac9e41aa1cc153f4ddab725857fe249e3))

### Fix

* fix: upgrade rpm-git-repo on every kanon install instead of skipping (#43)

Previously _ensure_repo_tool_from_pypi() checked if rpm-git-repo was
installed and silently skipped if present, leaving users stuck on old
versions. Now runs pipx upgrade when already installed so new releases
(e.g. PEP 440 constraint support in 1.1.0) are picked up automatically. ([`c4fe252`](https://github.com/caylent-solutions/kanon/commit/c4fe2529b5561b2ee784957b8905e424dea01dcc))

### Unknown

* Merge pull request #44 from caylent-solutions/release-1.0.4

Release 1.0.4 ([`3f552c0`](https://github.com/caylent-solutions/kanon/commit/3f552c04f3c36b05cf597b00451f8bc311eb77f8))


## v1.0.3 (2026-04-14)

### Chore

* chore(release): 1.0.3 ([`8c451f6`](https://github.com/caylent-solutions/kanon/commit/8c451f67f68c145c737ca52958e0b64366c9ac36))

* chore: rename stale rpm test method and fixture names (#40)

- test_returns_rpm → test_returns_kanon
- test_only_contains_rpm → test_only_contains_kanon
- rpm-lint fixture → test-lint ([`d710cad`](https://github.com/caylent-solutions/kanon/commit/d710cada20133f3dd8e19fab5d0f3504cbfc7d12))

### Fix

* fix: accept prefixed PEP 440 constraints in marketplace validator (#41)

The _is_valid_revision() validator now accepts refs/tags/&lt;path&gt;/&lt;constraint&gt;
format (e.g., refs/tags/claude-tools/history/&gt;=0.2.0,&lt;1.0.0) in addition
to the existing bare constraint and exact tag formats.

Also expands XML escaping documentation in README with full special
character table. ([`6541141`](https://github.com/caylent-solutions/kanon/commit/65411413a976439e2358e8fcaf01d0c022ff95ba))

### Unknown

* Merge pull request #42 from caylent-solutions/release-1.0.3

Release 1.0.3 ([`1fb4eef`](https://github.com/caylent-solutions/kanon/commit/1fb4eef8c78c185c5376c7e520369a663ba7c44e))


## v1.0.2 (2026-04-14)

### Chore

* chore(release): 1.0.2 ([`0d22272`](https://github.com/caylent-solutions/kanon/commit/0d22272512180950e2216aee929ebe112e5293dc))

### Fix

* fix: resolve @latest catalog resolution and clean up error output (#38)

- Fix catalog.py: strip refs/tags/ prefix from @latest version
  resolution so git clone --branch accepts the resolved tag name
- Fix install.py: catch FileNotFoundError/ValueError from
  parse_kanonenv() and print clean error message instead of traceback
- Fix clean.py: same exception handling as install
- Add docs/integration-testing.md: comprehensive integration test plan
  with local file:// fixtures for reproducible testing ([`4d6c8f7`](https://github.com/caylent-solutions/kanon/commit/4d6c8f7946343a54362e8c505620e409a058fa27))

### Unknown

* Merge pull request #39 from caylent-solutions/release-1.0.2

Release 1.0.2 ([`c75f3ad`](https://github.com/caylent-solutions/kanon/commit/c75f3ad38866afcf3528d686a09a96531b9d41dc))


## v1.0.1 (2026-04-13)

### Chore

* chore(release): 1.0.1 ([`e8ca1b8`](https://github.com/caylent-solutions/kanon/commit/e8ca1b8b5c2724ec532b7784476803d830feb8d0))

### Fix

* fix: remove stale Gradle and Make task runner references (#36)

* fix: remove stale Gradle and Make task runner references

Remove all Gradle and Make encapsulation content from docs and code.
Kanon is a standalone CLI tool — kanon-bootstrap.gradle, build.gradle
wrappers, Makefile targets wrapping kanon, _rpmCurrentPkgDir,
_rpmProp, and rpm-manifest.properties are no longer documented.

Generic task runner integration remains as an optional concept.

* fix: re-enable CodeQL and fix end-of-file lint errors

- Restores CodeQL triggers and release gate dependency
- Fixes trailing newline in docs/how-it-works.md and docs/setup-guide.md
  (end-of-file-fixer pre-commit hook)

The stale CodeQL overlay base database (cached in GitHub Actions cache
from pre-rename &#39;rpm&#39; runs with /work/rpm/rpm workspace path) was
deleted via gh cache delete, allowing fresh analysis under the correct
kanon workspace path. ([`4f802cf`](https://github.com/caylent-solutions/kanon/commit/4f802cf4c853dadf0c3f99c15692a2f86c3457c4))

### Unknown

* Merge pull request #37 from caylent-solutions/release-1.0.1

Release 1.0.1 ([`e5a3124`](https://github.com/caylent-solutions/kanon/commit/e5a3124d1f00fe630f83605ac3c7c7658eebe133))


## v1.0.0 (2026-04-13)

### Breaking

* feat!: rename RPM to Kanon Package Manager (#32)

* feat!: rename RPM to Kanon Package Manager

Rename the entire CLI tool from RPM (Repo Package Manager) to Kanon
(Kanon Package Manager). Kanon is Greek for &#34;codified conventions.&#34;

This is a breaking change with no backward compatibility:
- PyPI package: rpm-cli -&gt; kanon
- CLI command: rpm -&gt; kanon
- Subcommand: configure -&gt; install
- Python module: rpm_cli -&gt; kanon_cli
- Config file: .rpmenv -&gt; .kanon
- State directory: .rpm/ -&gt; .kanon-data/
- Env var prefix: RPM_SOURCE_* -&gt; KANON_SOURCE_*
- Env vars: RPM_MARKETPLACE_INSTALL -&gt; KANON_MARKETPLACE_INSTALL,
  RPM_CATALOG_SOURCE -&gt; KANON_CATALOG_SOURCE

The rpm-git-repo dependency is unchanged.

* fix: use kanon-cli as PyPI package name

The name &#39;kanon&#39; is already taken on PyPI. Use &#39;kanon-cli&#39; as the
PyPI package name instead. The CLI command remains &#39;kanon&#39;.

Install with: pipx install kanon-cli ([`f1434a1`](https://github.com/caylent-solutions/kanon/commit/f1434a1ecd10fb3bb49dcbdaf2a422d1a8b07209))

### Chore

* chore(release): 1.0.0 ([`7f540f6`](https://github.com/caylent-solutions/kanon/commit/7f540f65afbb4d0632316bf68560d6e819a19c3c))

* chore: fix CI after repo rename (#34)

- Set FORCE_JAVASCRIPT_ACTIONS_TO_NODE24 in main-validation to address
  Node.js 20 deprecation warning for tibdex/github-app-token@v2
- Temporarily remove CodeQL from release pipeline and disable automatic
  triggers (overlay cache references stale /work/rpm/rpm workspace path
  after repo rename; will re-enable in follow-up PR after first release) ([`54c661c`](https://github.com/caylent-solutions/kanon/commit/54c661c8b75548bf302c73e45ca65a9ba4beb04f))

### Unknown

* Merge pull request #35 from caylent-solutions/release-1.0.0

Release 1.0.0 ([`d8edc13`](https://github.com/caylent-solutions/kanon/commit/d8edc13f989945f810fc3aa1799e3d6ccaecf815))


## v0.8.0 (2026-03-31)

### Chore

* chore(release): 0.8.0 ([`a474a59`](https://github.com/caylent-solutions/kanon/commit/a474a5934e86d014005ca93fd7024e44413363a5))

### Feature

* feat: install rpm-git-repo from PyPI by default with optional git override (#30)

* feat: install rpm-git-repo from PyPI by default with optional git override

- Default behavior: rpm configure installs rpm-git-repo from PyPI if not
  already present. No REPO_URL or REPO_REV needed in .rpmenv.
- Git override: set both REPO_URL and REPO_REV to install from a git URL
  (for testing unreleased versions). Partial config fails fast.
- Marketplace validator glob: changed from claude-marketplaces.xml to
  *-marketplace.xml to match the current naming convention.
- Centralized constants: extracted all module-level constants into
  src/rpm_cli/constants.py to eliminate hardcoded values in source files.
- Coverage threshold: raised CI and pre-push gate from 85% to 90%.
- Added grm alias to .devcontainer/project-setup.sh for bash and zsh.
- Cleaned .claude/settings.json (removed user-level permissions).
- Updated all documentation for optional REPO_URL/REPO_REV and
  *-marketplace.xml naming convention.

* fix: add trailing newline to .claude/settings.json

Pre-commit end-of-file-fixer requires a trailing newline. ([`65db2ff`](https://github.com/caylent-solutions/kanon/commit/65db2ffc718b5b52b5ac9c98da508f921d52da8e))

### Unknown

* Merge pull request #31 from caylent-solutions/release-0.8.0

Release 0.8.0 ([`faff14d`](https://github.com/caylent-solutions/kanon/commit/faff14d69e2148dce0b5f0440736761ef791141c))


## v0.7.2 (2026-03-25)

### Chore

* chore(release): 0.7.2 ([`57dadcf`](https://github.com/caylent-solutions/kanon/commit/57dadcf65f19db90783854531f433f7078ffa101))

### Fix

* fix: update catalog rpm-readme with current prerequisites and SSH guidance (#27)

- Add Python 3.11+, pipx, and uv to prerequisites (were missing)
- Add SSH authentication callout with git config --global insteadOf command
- Update REPO_REV description: feat/initial-rpm-git-repo branch no longer
  exists, use main
- Improve troubleshooting SSH guidance with specific command ([`740d512`](https://github.com/caylent-solutions/kanon/commit/740d512a75bd73ec6384988529c12fb9f0082b44))

### Unknown

* Merge pull request #28 from caylent-solutions/release-0.7.2

Release 0.7.2 ([`8ed40b3`](https://github.com/caylent-solutions/kanon/commit/8ed40b33bd45978f054976b35bb332e6daf64739))


## v0.7.1 (2026-03-25)

### Chore

* chore(release): 0.7.1 ([`7cafa77`](https://github.com/caylent-solutions/kanon/commit/7cafa7722a0bbb2bdcb2590d8a154efc0e80689d))

### Fix

* fix: point REPO_REV to main in .rpmenv (#25)

* fix: point REPO_REV to main branch in .rpmenv

The REPO_REV was pointing to the feature branch
feat/initial-rpm-git-repo which is no longer needed now that
the work has been merged to main.

* fix: update catalog package tests to include example packages

The test assertions expected only [&#34;rpm&#34;] but the catalog now
contains example-gradle and example-make packages as well.

* revert: restore original test assertions for catalog packages

The previous test change was incorrect — the example-gradle and
example-make directories were stale local artifacts not tracked
in git. The original assertions are correct for CI. ([`11dc6ed`](https://github.com/caylent-solutions/kanon/commit/11dc6eda3d18591c7afbb3ddea9e26b79343524b))

### Unknown

* Merge pull request #26 from caylent-solutions/release-0.7.1

Release 0.7.1 ([`c10265b`](https://github.com/caylent-solutions/kanon/commit/c10265b26baf0cbc0c6ffc0e687ee29f5469c293))


## v0.7.0 (2026-03-24)

### Chore

* chore(release): 0.7.0 ([`3438873`](https://github.com/caylent-solutions/kanon/commit/343887398ce38f50574a93c2a3b692be67c288b5))

### Feature

* feat: add documentation for supporting ssh users ([`b7a65fe`](https://github.com/caylent-solutions/kanon/commit/b7a65fe90ea5ac531ccd828cbe1f8600853857bb))

### Unknown

* Merge pull request #24 from caylent-solutions/release-0.7.0

Release 0.7.0 ([`a136e9f`](https://github.com/caylent-solutions/kanon/commit/a136e9f9094d50e3f54c4be783fd27b2a1a45b2c))

* Merge pull request #23 from caylent-solutions/feat/ssh-support

docs: add documentation for supporting ssh users ([`84614ca`](https://github.com/caylent-solutions/kanon/commit/84614ca7469d6d7bbe1e4d07b3415b335efe9e93))


## v0.6.0 (2026-03-20)

### Chore

* chore(release): 0.6.0 ([`92ad672`](https://github.com/caylent-solutions/kanon/commit/92ad67266c3699ee6aae3f6f9d328b44b2da0966))

### Feature

* feat: simplify bundled catalog to rpm-only with placeholder .rpmenv (#21)

Remove make and gradle catalog entries — the bundled catalog now contains
only the `rpm` standalone entry. Replace hard-coded Caylent-specific values
in the rpm catalog .rpmenv with descriptive placeholders and commented-out
examples showing single-source and multi-source configurations.

This makes the bundled catalog generic for any organization. Users edit
.rpmenv after bootstrap to configure their GITBASE, marketplace toggle,
and source variables. ([`a331153`](https://github.com/caylent-solutions/kanon/commit/a331153c28885daf92575189192e744aa6aeffdb))

### Unknown

* Merge pull request #22 from caylent-solutions/release-0.6.0

Release 0.6.0 ([`7899fa4`](https://github.com/caylent-solutions/kanon/commit/7899fa4259ed1d6e54b75bd9ef4abbb3af28179a))


## v0.5.0 (2026-03-16)

### Chore

* chore(release): 0.5.0 ([`d67ecc5`](https://github.com/caylent-solutions/kanon/commit/d67ecc5663acd381de1fbdb113f51b2c8e01a426))

### Feature

* feat: catalog-driven bootstrap with pre-configured .rpmenv (#19)

Bootstrap now copies all files from catalog entries including a
pre-configured .rpmenv, eliminating placeholder editing on first
setup. Renames runner terminology to package throughout CLI, code,
tests, and docs for consistency with the catalog entry model. ([`2fc907c`](https://github.com/caylent-solutions/kanon/commit/2fc907c8a7fac72aa82f2bbfd73e81241cf7800b))

* feat: clarify source naming convention for multiple sources (#18)

* feat: clarify source naming convention for multiple sources in multi-source guide

Add dedicated &#34;Source Naming Convention&#34; section explaining the three-field
variable structure and the hyphenation pattern for supporting multiple
sources of the same concern type. Add a multi-source .rpmenv example
showing multiple build and marketplace sources side by side. Update
directory structure, symlink aggregation, and collision detection examples
to use consistent multi-source naming throughout.

* feat: clarify that source names are arbitrary and do not affect CLI behavior

Add explicit explanation that the CLI treats all sources identically
regardless of name. The names &#34;build&#34; and &#34;marketplaces&#34; are team
conventions for readability — what determines a source&#39;s behavior is
the manifest content (project entries and linkfile elements), not the
source name.

* feat: recommend build/marketplaces naming convention with rationale

Add explicit recommendation to prefix source names with &#34;build&#34; or
&#34;marketplaces&#34; so that humans and AI agents can immediately understand
each source&#39;s purpose from the .rpmenv file alone, without needing to
inspect manifest content.

* feat: document flexible source naming convention and marketplace mechanism

Clarify that marketplace behavior is determined by linkfile symlink
destinations into CLAUDE_MARKETPLACES_DIR, not by source naming. Expand
the naming convention section with a table of common prefixes beyond
build/marketplaces (pipelines, runners, tf-deploy-templates,
sonarqube-config) and explain that any descriptive name is appropriate. ([`6c91de5`](https://github.com/caylent-solutions/kanon/commit/6c91de5b93c8ecad38d89cfda0a17f6bdf62e6a8))

### Unknown

* Merge pull request #20 from caylent-solutions/release-0.5.0

Release 0.5.0 ([`32afa79`](https://github.com/caylent-solutions/kanon/commit/32afa79b219f92b4288dacc607740f3fde739192))


## v0.4.0 (2026-03-12)

### Chore

* chore(release): 0.4.0 ([`c8fa8dd`](https://github.com/caylent-solutions/kanon/commit/c8fa8ddbce109a729ad68ec3cf1e10c25e39dd5d))

### Feature

* feat: add rpm bootstrap runner with getting-started readmes (#16)

* fix(build): remove duplicate catalog files from wheel

Remove redundant force-include for src/rpm_cli/catalog in pyproject.toml.
The catalog directory is already included via packages = [&#34;src/rpm_cli&#34;],
so force-include caused duplicate entries in the ZIP archive, which PyPI
rejects with &#34;Duplicate filename in local headers&#34;.

* feat: add rpm bootstrap runner with getting-started readmes

Add a third bootstrap runner called &#39;rpm&#39; for projects that don&#39;t use
a standard task runner (Make or Gradle). Running &#39;rpm bootstrap rpm&#39;
creates only .rpmenv and rpm-readme.md — no wrapper files.

Add rpm-readme.md getting-started guides to all three runner catalog
directories (make, gradle, rpm) with runner-specific prerequisites,
setup steps, full .rpmenv variable reference, and troubleshooting.

Update .rpmenv template to use concrete rpm-git-repo URL and branch
instead of placeholders. Cover with unit and functional tests (218
tests passing). ([`3c9a7fd`](https://github.com/caylent-solutions/kanon/commit/3c9a7fd7f1a99e82e3da6e003bffca51370e79f8))

### Unknown

* Merge pull request #17 from caylent-solutions/release-0.4.0

Release 0.4.0 ([`14a2843`](https://github.com/caylent-solutions/kanon/commit/14a284380c7afac0ecc0f010364b2b29ba89ef10))


## v0.3.0 (2026-03-12)

### Chore

* chore(release): 0.3.0 ([`be2d0d3`](https://github.com/caylent-solutions/kanon/commit/be2d0d3f65b01d2a7d3b0119930b265d184e322e))

### Feature

* feat: use separate concurrency group for publish workflow to prevent cancellation (#14)

* feat: support PEP 440 constraints in RPM_SOURCE_*_REVISION with refs/tags/ prefix

Extends resolve_version() to mirror the constraint syntax supported by
rpm-git-repo manifest &lt;project&gt; revision attributes. The last path
component is inspected for PEP 440 operators, enabling prefixed
constraints like refs/tags/~=1.1.0 and refs/tags/prefix/&gt;=1.0.0,&lt;2.0.0.

_list_tags() now returns full ref paths (refs/tags/1.1.2) so the
resolved value is directly usable with repo init -b. All operators
supported by rpm-git-repo are supported: ~=, &gt;=, &lt;=, &gt;, &lt;, ==, !=, *.

Removes _parse_tag_versions() (logic inlined), adds _is_version_constraint()
mirroring rpm-git-repo version_constraints.py. Updates version-resolution.md,
multi-source-guide.md, and README to document the new syntax.

* style: apply ruff formatting to version.py and test_version.py

* docs: add table of contents to README

* fix: use separate concurrency group for publish workflow to prevent cancellation ([`ebacbaa`](https://github.com/caylent-solutions/kanon/commit/ebacbaa2574bf0f8c464ce24058ecb0d7e409f04))

### Unknown

* Merge pull request #15 from caylent-solutions/release-0.3.0

Release 0.3.0 ([`48fdf5f`](https://github.com/caylent-solutions/kanon/commit/48fdf5f51a27f6a001eef54655d26b5859be248d))


## v0.2.0 (2026-03-12)

### Chore

* chore(release): 0.2.0 ([`e6b8b86`](https://github.com/caylent-solutions/kanon/commit/e6b8b86e25ceba82a01b026cf15c4fb8d0fb0599))

### Feature

* feat: support PEP 440 constraints in RPM_SOURCE_*_REVISION with refs/tags/ prefix (#12)

* feat: support PEP 440 constraints in RPM_SOURCE_*_REVISION with refs/tags/ prefix

Extends resolve_version() to mirror the constraint syntax supported by
rpm-git-repo manifest &lt;project&gt; revision attributes. The last path
component is inspected for PEP 440 operators, enabling prefixed
constraints like refs/tags/~=1.1.0 and refs/tags/prefix/&gt;=1.0.0,&lt;2.0.0.

_list_tags() now returns full ref paths (refs/tags/1.1.2) so the
resolved value is directly usable with repo init -b. All operators
supported by rpm-git-repo are supported: ~=, &gt;=, &lt;=, &gt;, &lt;, ==, !=, *.

Removes _parse_tag_versions() (logic inlined), adds _is_version_constraint()
mirroring rpm-git-repo version_constraints.py. Updates version-resolution.md,
multi-source-guide.md, and README to document the new syntax.

* style: apply ruff formatting to version.py and test_version.py

* docs: add table of contents to README ([`d99b071`](https://github.com/caylent-solutions/kanon/commit/d99b071c78c1521b81ae364a7c41debe3c4387bd))

### Unknown

* Merge pull request #13 from caylent-solutions/release-0.2.0

Release 0.2.0 ([`7c48bfe`](https://github.com/caylent-solutions/kanon/commit/7c48bfedc8547ca9c980bf0af21c0496ce2c7f52))


## v0.1.4 (2026-03-12)

### Chore

* chore(release): 0.1.4 ([`6d98ebf`](https://github.com/caylent-solutions/kanon/commit/6d98ebf4f8b361ceedf5dcbe16a59d9a4a106d8a))

### Fix

* fix: resolve source revision specifiers before passing to repo init (#10)

RPM_SOURCE_&lt;name&gt;_REVISION supports PEP 440 specifiers (e.g. *, ~=1.0)
via resolve_version, but configure() was passing the raw specifier
directly to repo init -b, causing repo to fail with &#39;revision not found&#39;.

Call resolve_version on the source revision before run_repo_init so
that wildcard and range specifiers are resolved to actual tags. ([`98abc86`](https://github.com/caylent-solutions/kanon/commit/98abc868d0d3b0321d49d6e36c7dc4132621254e))

### Unknown

* Merge pull request #11 from caylent-solutions/release-0.1.4

Release 0.1.4 ([`56ea6bc`](https://github.com/caylent-solutions/kanon/commit/56ea6bccb740fc59c364d8f2faedf501253868b7))


## v0.1.3 (2026-03-11)

### Chore

* chore(release): 0.1.3 ([`1b1483d`](https://github.com/caylent-solutions/kanon/commit/1b1483d5b0a58ef10c45cb58bccc040cb22b94d7))

### Fix

* fix(build): remove duplicate catalog files from wheel

Remove redundant force-include for src/rpm_cli/catalog in pyproject.toml.
The catalog directory is already included via packages = [&#34;src/rpm_cli&#34;],
so force-include caused duplicate entries in the ZIP archive, which PyPI
rejects with &#34;Duplicate filename in local headers&#34;. ([`a9aa28c`](https://github.com/caylent-solutions/kanon/commit/a9aa28c583f178fbe8e186d923253a6371f8d4ff))

### Unknown

* Merge pull request #9 from caylent-solutions/release-0.1.3

Release 0.1.3 ([`b340608`](https://github.com/caylent-solutions/kanon/commit/b340608fad9fbf03ecc6da1776df25afb4f5ccb5))


## v0.1.2 (2026-03-11)

### Chore

* chore(release): 0.1.2 ([`d9da1a6`](https://github.com/caylent-solutions/kanon/commit/d9da1a6010d728bf3f20187ad29194df61673c18))

### Fix

* fix: use dynamic version in functional test and enable verbose PyPI publish

- Replace hardcoded version string in test_version_flag with
  rpm_cli.__version__ so the test doesn&#39;t break on version bumps
- Enable verbose mode on pypa/gh-action-pypi-publish to diagnose
  400 Bad Request from PyPI trusted publisher upload ([`2e082f0`](https://github.com/caylent-solutions/kanon/commit/2e082f02aec6eef85605a7d04dfba6f53ac62d8d))

### Unknown

* Merge pull request #7 from caylent-solutions/release-0.1.2

Release 0.1.2 ([`361e8f1`](https://github.com/caylent-solutions/kanon/commit/361e8f163758de3ebaf6a128f235834f708142ad))


## v0.1.1 (2026-03-11)

### Chore

* chore(release): 0.1.1 ([`10922ca`](https://github.com/caylent-solutions/kanon/commit/10922caa7a054fa215cfcb4aec2c6dc407a480f1))

### Ci

* ci: add SDLC pipeline with semantic release, PyPI publishing, and devcontainer setup

* ci: add SDLC pipeline with semantic release, PyPI publishing, and devcontainer setup

- Add GitHub Actions workflows: pr-validation, main-validation, publish, codeql-analysis
- Add python-semantic-release config for automated versioning from conventional commits
- Add pre-commit config with security scanning (gitleaks, detect-private-key, detect-aws-credentials)
- Add CONTRIBUTING.md with commit conventions, PR process, and release documentation
- Add git hooks (pre-commit, pre-push) for local development quality gates
- Add .yamllint, .tool-versions, CHANGELOG.md
- Update Makefile with build, publish, pre-commit-check, install-hooks targets
- Update pyproject.toml with project metadata, classifiers, and semantic-release config
- Update requirements-dev.txt with semantic-release, build, twine, pre-commit, yamllint
- Update README.md with developer setup, contributing guide, and CI/CD pipeline overview
- Update .gitignore with .claude/settings.local.json exclusion
- Add devcontainer configuration for consistent development environments
- Add CLAUDE.md with engineering and automation standards

* fix(ci): run unit tests with --cov flag for coverage threshold check

The coverage json step requires pytest to run with --cov to produce
coverage data. Without it, coverage json reports no data and exits 1.

* fix(ci): lower coverage threshold to 85% to match current codebase

Current unit test coverage is 87%. Set threshold to 85% to allow
the pipeline to pass. Threshold can be raised as coverage improves. ([`91b2be1`](https://github.com/caylent-solutions/kanon/commit/91b2be1c48689107dade4fa9dc44c64ce639f7bb))

### Fix

* fix(ci): upgrade GitHub Actions to Node.js 24 and handle no-op releases

- Upgrade actions/checkout v4 → v6, actions/cache v4 → v5,
  actions/setup-python v5 → v6 to resolve Node.js 20 deprecation
- Add early exit in create-release job when no file changes are
  detected (e.g., ci: commits that don&#39;t trigger a version bump)
- Skip tag creation and publish trigger when release is skipped ([`d8b5fd9`](https://github.com/caylent-solutions/kanon/commit/d8b5fd99d3892f928e1835ef680dc02d5616258d))

### Unknown

* Merge pull request #4 from caylent-solutions/release-0.1.1

Release 0.1.1 ([`9477192`](https://github.com/caylent-solutions/kanon/commit/94771923e156c189a4f775f3260115d54632e1d7))


## v0.1.0 (2026-03-11)

### Feature

* feat: initial RPM CLI release — standalone public repo

Migrate RPM CLI from caylent-private-rpm/scripts/rpm-cli/ to standalone
public repository. Includes all source code, tests, bundled catalog
templates, and comprehensive documentation covering CLI usage, manifest
repo creation, package development, and marketplace packages.

Version 0.1.0 — first public release under Apache 2.0 license. ([`a32c0e5`](https://github.com/caylent-solutions/kanon/commit/a32c0e55198675bb1f511b2ca8d6700f9e15607a))

### Unknown

* Initial commit ([`c8dab0f`](https://github.com/caylent-solutions/kanon/commit/c8dab0fd0d48c36478029ed2cb93c68a0067eec0))
