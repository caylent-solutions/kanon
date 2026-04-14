# Integration Test Plan for kanon CLI

This document provides a step-by-step integration test plan for the `kanon` CLI.
Each test includes the exact command, expected output patterns, and pass/fail criteria.
Tests use local `file://` URLs with git repos created in `/tmp/` so no network access
or private repositories are required.

---

## 1. Setup

### 1.1 Install kanon-cli

**Post-release (from PyPI):**

```bash
pipx install kanon-cli
```

**Pre-merge (editable from local checkout):**

```bash
cd /path/to/kanon
pip install -e .
```

Use the editable install when testing unreleased changes before merge and PyPI release. After the release, re-run the full test suite using the PyPI-installed version to verify the published package.

**Verify:**

```bash
kanon --version
```

**Pass criteria:** Exit code 0. Output contains a version string matching the pattern `kanon X.Y.Z`.

### 1.2 Create a working directory

```bash
export KANON_TEST_ROOT="/tmp/kanon-integration-tests"
rm -rf "${KANON_TEST_ROOT}"
mkdir -p "${KANON_TEST_ROOT}"
```

---

## 2. Category 1: Help and Version (8 tests)

### HV-01: Top-level help

```bash
kanon --help
```

**Pass criteria:** Exit code 0. stdout contains all of: `install`, `clean`, `validate`, `bootstrap`.

### HV-02: Version flag

```bash
kanon --version
```

**Pass criteria:** Exit code 0. stdout matches the pattern `kanon \d+\.\d+\.\d+`.

### HV-03: Install subcommand help

```bash
kanon install --help
```

**Pass criteria:** Exit code 0. stdout contains `kanonenv_path`.

### HV-04: Clean subcommand help

```bash
kanon clean --help
```

**Pass criteria:** Exit code 0. stdout contains `kanonenv_path`.

### HV-05: Validate subcommand help

```bash
kanon validate --help
```

**Pass criteria:** Exit code 0. stdout contains both `xml` and `marketplace`.

### HV-06: Validate xml sub-subcommand help

```bash
kanon validate xml --help
```

**Pass criteria:** Exit code 0. stdout contains `--repo-root`.

### HV-07: Validate marketplace sub-subcommand help

```bash
kanon validate marketplace --help
```

**Pass criteria:** Exit code 0. stdout contains `--repo-root`.

### HV-08: Bootstrap subcommand help

```bash
kanon bootstrap --help
```

**Pass criteria:** Exit code 0. stdout contains `package` and `--output-dir`.

---

## 3. Category 2: Bootstrap -- Bundled Catalog (5 tests)

### BS-01: List bundled packages

```bash
kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `kanon`.

### BS-02: Bootstrap kanon package (default output dir)

```bash
cd "${KANON_TEST_ROOT}"
mkdir bs02 && cd bs02
kanon bootstrap kanon
```

**Pass criteria:** Exit code 0. Files `.kanon` and `kanon-readme.md` exist in the current directory. stdout contains `kanon install .kanon`.

**Cleanup:**

```bash
rm -rf "${KANON_TEST_ROOT}/bs02"
```

### BS-03: Bootstrap kanon package with --output-dir

```bash
kanon bootstrap kanon --output-dir "${KANON_TEST_ROOT}/bs03-output"
```

**Pass criteria:** Exit code 0. Files `${KANON_TEST_ROOT}/bs03-output/.kanon` and `${KANON_TEST_ROOT}/bs03-output/kanon-readme.md` exist.

**Cleanup:**

```bash
rm -rf "${KANON_TEST_ROOT}/bs03-output"
```

### BS-04: Conflict -- bootstrap into dir with existing .kanon

```bash
mkdir -p "${KANON_TEST_ROOT}/bs04"
echo "existing" > "${KANON_TEST_ROOT}/bs04/.kanon"
kanon bootstrap kanon --output-dir "${KANON_TEST_ROOT}/bs04"
```

**Pass criteria:** Exit code 1. stderr contains `already exist`.

**Cleanup:**

```bash
rm -rf "${KANON_TEST_ROOT}/bs04"
```

### BS-05: Unknown package name

```bash
kanon bootstrap nonexistent
```

**Pass criteria:** Exit code 1. stderr contains `Unknown package 'nonexistent'`.

---

## 4. Category 3: Creating Local Test Fixtures

All fixtures are bare git repos in `/tmp/` that the `repo` tool can clone via
`file://` URLs. The manifests reference each other using `file://` paths.

### 4.1 Package Content Repo A: `pkg-alpha`

This repo simulates a content repository that provides a single package directory.

```bash
export PKG_ALPHA_DIR="${KANON_TEST_ROOT}/fixtures/content-repos/pkg-alpha"
mkdir -p "${PKG_ALPHA_DIR}"
cd "${PKG_ALPHA_DIR}"
git init
mkdir -p src
echo 'print("alpha")' > src/main.py
echo "# Alpha Package" > README.md
git add .
git commit -m "Initial commit for pkg-alpha"
git branch -m main
```

### 4.2 Package Content Repo B: `pkg-bravo`

```bash
export PKG_BRAVO_DIR="${KANON_TEST_ROOT}/fixtures/content-repos/pkg-bravo"
mkdir -p "${PKG_BRAVO_DIR}"
cd "${PKG_BRAVO_DIR}"
git init
mkdir -p src
echo 'print("bravo")' > src/main.py
echo "# Bravo Package" > README.md
git add .
git commit -m "Initial commit for pkg-bravo"
git branch -m main
```

### 4.3 Collision Content Repo: `pkg-collider`

This repo produces a package with the same `path` attribute as `pkg-alpha`, causing
a collision when both sources are active.

```bash
export PKG_COLLIDER_DIR="${KANON_TEST_ROOT}/fixtures/content-repos/pkg-collider"
mkdir -p "${PKG_COLLIDER_DIR}"
cd "${PKG_COLLIDER_DIR}"
git init
mkdir -p src
echo 'print("collider")' > src/main.py
echo "# Collider Package (same name as alpha)" > README.md
git add .
git commit -m "Initial commit for pkg-collider"
git branch -m main
```

### 4.4 Linkfile Content Repo: `pkg-linked`

This repo contains configuration files that will be symlinked via `<linkfile>` elements.

```bash
export PKG_LINKED_DIR="${KANON_TEST_ROOT}/fixtures/content-repos/pkg-linked"
mkdir -p "${PKG_LINKED_DIR}"
cd "${PKG_LINKED_DIR}"
git init
mkdir -p config
echo '{"setting": "value"}' > config/app-config.json
echo "lint_rule = true" > config/lint.toml
echo "# Linked Package" > README.md
git add .
git commit -m "Initial commit for pkg-linked"
git branch -m main
```

### 4.5 Manifest Repo: `manifest-primary`

This manifest repo contains the XML manifests that reference the content repos above.
It provides two manifests: one for `pkg-alpha` and one for `pkg-bravo`.

```bash
export MANIFEST_PRIMARY_DIR="${KANON_TEST_ROOT}/fixtures/manifest-repos/manifest-primary"
mkdir -p "${MANIFEST_PRIMARY_DIR}/repo-specs"
cd "${MANIFEST_PRIMARY_DIR}"
git init
```

Create the remote definition file:

```bash
cat > repo-specs/remote.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${KANON_TEST_ROOT}/fixtures/content-repos" />
  <default remote="local" revision="main" sync-j="4" />
</manifest>
XMLEOF
```

Create the main manifest that references both packages:

```bash
cat > repo-specs/packages.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <include name="repo-specs/remote.xml" />
  <project name="pkg-alpha" path=".packages/pkg-alpha" remote="local" revision="main" />
  <project name="pkg-bravo" path=".packages/pkg-bravo" remote="local" revision="main" />
</manifest>
XMLEOF
```

Create a single-package manifest (alpha only):

```bash
cat > repo-specs/alpha-only.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <include name="repo-specs/remote.xml" />
  <project name="pkg-alpha" path=".packages/pkg-alpha" remote="local" revision="main" />
</manifest>
XMLEOF
```

Commit the manifest repo:

```bash
cd "${MANIFEST_PRIMARY_DIR}"
git add .
git commit -m "Initial manifest with alpha and bravo packages"
git branch -m main
```

### 4.6 Collision Manifest Repo: `manifest-collision`

This manifest repo references `pkg-collider` under the same `.packages/pkg-alpha`
path, which causes a collision with `manifest-primary`.

```bash
export MANIFEST_COLLISION_DIR="${KANON_TEST_ROOT}/fixtures/manifest-repos/manifest-collision"
mkdir -p "${MANIFEST_COLLISION_DIR}/repo-specs"
cd "${MANIFEST_COLLISION_DIR}"
git init

cat > repo-specs/remote.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${KANON_TEST_ROOT}/fixtures/content-repos" />
  <default remote="local" revision="main" sync-j="4" />
</manifest>
XMLEOF

cat > repo-specs/collision.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <include name="repo-specs/remote.xml" />
  <project name="pkg-collider" path=".packages/pkg-alpha" remote="local" revision="main" />
</manifest>
XMLEOF

git add .
git commit -m "Collision manifest (produces pkg-alpha path)"
git branch -m main
```

### 4.7 Linkfile Manifest Repo: `manifest-linkfile`

This manifest repo uses `<linkfile>` elements to create symlinks for config files.

```bash
export MANIFEST_LINKFILE_DIR="${KANON_TEST_ROOT}/fixtures/manifest-repos/manifest-linkfile"
mkdir -p "${MANIFEST_LINKFILE_DIR}/repo-specs"
cd "${MANIFEST_LINKFILE_DIR}"
git init

cat > repo-specs/remote.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${KANON_TEST_ROOT}/fixtures/content-repos" />
  <default remote="local" revision="main" sync-j="4" />
</manifest>
XMLEOF

cat > repo-specs/linkfile.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <include name="repo-specs/remote.xml" />
  <project name="pkg-linked" path=".packages/pkg-linked" remote="local" revision="main">
    <linkfile src="config/app-config.json" dest="app-config.json" />
    <linkfile src="config/lint.toml" dest="lint.toml" />
  </project>
</manifest>
XMLEOF

git add .
git commit -m "Linkfile manifest with config symlinks"
git branch -m main
```

### 4.8 Verify fixtures

After creating all fixtures, verify each repo is a valid git repo:

```bash
for repo_dir in \
  "${PKG_ALPHA_DIR}" \
  "${PKG_BRAVO_DIR}" \
  "${PKG_COLLIDER_DIR}" \
  "${PKG_LINKED_DIR}" \
  "${MANIFEST_PRIMARY_DIR}" \
  "${MANIFEST_COLLISION_DIR}" \
  "${MANIFEST_LINKFILE_DIR}"; do
  git -C "${repo_dir}" log --oneline -1 || { echo "FAIL: ${repo_dir} is not a valid git repo"; exit 1; }
done
echo "All fixture repos verified."
```

**Pass criteria:** All repos print a single-line commit hash and message. Final output: `All fixture repos verified.`

---

## 5. Category 4: Install/Clean Lifecycle (4 tests)

These tests use the fixtures from Category 3 and validate the `kanon install` and
`kanon clean` end-to-end lifecycle. They require `pipx` and the `repo` tool
(automatically installed by `kanon install`).

### IC-01: Single source, no marketplace -- install and clean

```bash
export IC01_DIR="${KANON_TEST_ROOT}/test-ic01"
mkdir -p "${IC01_DIR}"

cat > "${IC01_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${IC01_DIR}"
kanon install .kanon
```

**Pass criteria (install):**
- Exit code 0
- stdout contains `kanon install: done`
- Directory `.kanon-data/sources/primary/` exists
- Directory `.packages/` exists
- `.packages/pkg-alpha` is a symlink
- Symlink target path contains `.kanon-data/sources/primary/.packages/pkg-alpha`
- `.gitignore` exists and contains both `.packages/` and `.kanon-data/`

**Clean:**

```bash
cd "${IC01_DIR}"
kanon clean .kanon
```

**Pass criteria (clean):**
- Exit code 0
- stdout contains `kanon clean: done`
- `.packages/` directory does not exist
- `.kanon-data/` directory does not exist

**Cleanup:**

```bash
rm -rf "${IC01_DIR}"
```

### IC-02: Shell variable expansion (${HOME})

```bash
export IC02_DIR="${KANON_TEST_ROOT}/test-ic02"
mkdir -p "${IC02_DIR}"

cat > "${IC02_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
CLAUDE_MARKETPLACES_DIR=\${HOME}/.claude-marketplaces
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${IC02_DIR}"
kanon install .kanon
```

**Pass criteria:**
- Exit code 0
- The `.kanon` file contains the literal string `${HOME}` (not expanded in the file itself)
- The install succeeds, meaning `${HOME}` was correctly expanded during parsing
- stdout contains `kanon install: done`

**Cleanup:**

```bash
cd "${IC02_DIR}"
kanon clean .kanon
rm -rf "${IC02_DIR}"
```

### IC-03: Comments and blank lines in .kanon

```bash
export IC03_DIR="${KANON_TEST_ROOT}/test-ic03"
mkdir -p "${IC03_DIR}"

cat > "${IC03_DIR}/.kanon" << KANONEOF
# This is a comment
# Another comment

KANON_MARKETPLACE_INSTALL=false

# Blank lines above and below should be ignored

KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml

# Trailing comment
KANONEOF

cd "${IC03_DIR}"
kanon install .kanon
```

**Pass criteria:**
- Exit code 0
- stdout contains `kanon install: done`
- Comments and blank lines did not cause parsing errors
- `.packages/pkg-alpha` symlink exists

**Cleanup:**

```bash
cd "${IC03_DIR}"
kanon clean .kanon
rm -rf "${IC03_DIR}"
```

### IC-04: KANON_MARKETPLACE_INSTALL=false explicit

```bash
export IC04_DIR="${KANON_TEST_ROOT}/test-ic04"
mkdir -p "${IC04_DIR}"

cat > "${IC04_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${IC04_DIR}"
kanon install .kanon
```

**Pass criteria:**
- Exit code 0
- stdout does NOT contain `marketplace` (marketplace lifecycle was skipped)
- stdout contains `kanon install: done`

**Cleanup:**

```bash
cd "${IC04_DIR}"
kanon clean .kanon
rm -rf "${IC04_DIR}"
```

---

## 6. Category 5: Multi-Source (1 test)

### MS-01: Two sources aggregate packages from both

```bash
export MS01_DIR="${KANON_TEST_ROOT}/test-ms01"
mkdir -p "${MS01_DIR}"

cat > "${MS01_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_alpha_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_alpha_REVISION=main
KANON_SOURCE_alpha_PATH=repo-specs/alpha-only.xml
KANON_SOURCE_bravo_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_bravo_REVISION=main
KANON_SOURCE_bravo_PATH=repo-specs/packages.xml
KANONEOF

cd "${MS01_DIR}"
kanon install .kanon
```

**Pass criteria:**
- Exit code 0
- `.kanon-data/sources/alpha/` directory exists
- `.kanon-data/sources/bravo/` directory exists
- `.packages/` directory contains symlinks
- stdout contains `kanon install: done`

**Cleanup:**

```bash
cd "${MS01_DIR}"
kanon clean .kanon
rm -rf "${MS01_DIR}"
```

---

## 7. Category 6: Collision Detection (2 tests)

### CD-01: Two sources producing the same package name

```bash
export CD01_DIR="${KANON_TEST_ROOT}/test-cd01"
mkdir -p "${CD01_DIR}"

cat > "${CD01_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANON_SOURCE_secondary_URL=file://${MANIFEST_COLLISION_DIR}
KANON_SOURCE_secondary_REVISION=main
KANON_SOURCE_secondary_PATH=repo-specs/collision.xml
KANONEOF

cd "${CD01_DIR}"
kanon install .kanon
```

**Pass criteria:**
- Exit code 1
- stderr contains `Package collision` and `pkg-alpha`

**Cleanup:**

```bash
rm -rf "${CD01_DIR}"
```

### CD-02: Three sources, collision between two

```bash
export CD02_DIR="${KANON_TEST_ROOT}/test-cd02"
mkdir -p "${CD02_DIR}"

cat > "${CD02_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_aaa_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_aaa_REVISION=main
KANON_SOURCE_aaa_PATH=repo-specs/alpha-only.xml
KANON_SOURCE_bbb_URL=file://${MANIFEST_COLLISION_DIR}
KANON_SOURCE_bbb_REVISION=main
KANON_SOURCE_bbb_PATH=repo-specs/collision.xml
KANON_SOURCE_ccc_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_ccc_REVISION=main
KANON_SOURCE_ccc_PATH=repo-specs/packages.xml
KANONEOF

cd "${CD02_DIR}"
kanon install .kanon
```

**Pass criteria:**
- Exit code 1
- stderr contains `Package collision` and `pkg-alpha`
- Sources are processed alphabetically: `aaa` processes first, then `bbb` collides on `pkg-alpha`

**Cleanup:**

```bash
rm -rf "${CD02_DIR}"
```

---

## 8. Category 7: Linkfile Packages (1 test)

### LF-01: Package with linkfile elements creates symlinks

```bash
export LF01_DIR="${KANON_TEST_ROOT}/test-lf01"
mkdir -p "${LF01_DIR}"

cat > "${LF01_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_linked_URL=file://${MANIFEST_LINKFILE_DIR}
KANON_SOURCE_linked_REVISION=main
KANON_SOURCE_linked_PATH=repo-specs/linkfile.xml
KANONEOF

cd "${LF01_DIR}"
kanon install .kanon
```

**Pass criteria:**
- Exit code 0
- `.packages/pkg-linked` exists (symlink into `.kanon-data/sources/`)
- `.kanon-data/sources/linked/app-config.json` exists as a symlink (created by the repo tool linkfile element inside the source directory)
- `.kanon-data/sources/linked/lint.toml` exists as a symlink
- Symlinks resolve to valid files

**Cleanup:**

```bash
cd "${LF01_DIR}"
kanon clean .kanon
rm -rf "${LF01_DIR}"
```

---

## 9. Category 8: Error Cases (9 tests)

### EC-01: Missing .kanon file

```bash
export EC01_DIR="${KANON_TEST_ROOT}/test-ec01"
mkdir -p "${EC01_DIR}"
cd "${EC01_DIR}"
kanon install .kanon
```

**Pass criteria:** Exit code 1. stderr contains `.kanon file not found` or `Error`.

**Cleanup:**

```bash
rm -rf "${EC01_DIR}"
```

### EC-02: Empty .kanon file

```bash
export EC02_DIR="${KANON_TEST_ROOT}/test-ec02"
mkdir -p "${EC02_DIR}"
touch "${EC02_DIR}/.kanon"
cd "${EC02_DIR}"
kanon install .kanon
```

**Pass criteria:** Exit code 1. stderr contains `No sources found`.

**Cleanup:**

```bash
rm -rf "${EC02_DIR}"
```

### EC-03: Undefined shell variable

```bash
export EC03_DIR="${KANON_TEST_ROOT}/test-ec03"
mkdir -p "${EC03_DIR}"

cat > "${EC03_DIR}/.kanon" << 'KANONEOF'
KANON_SOURCE_test_URL=${UNDEFINED_VAR_THAT_DOES_NOT_EXIST}
KANON_SOURCE_test_REVISION=main
KANON_SOURCE_test_PATH=meta.xml
KANONEOF

cd "${EC03_DIR}"
kanon install .kanon
```

**Pass criteria:** Exit code 1. stderr contains `Undefined shell variable`.

**Cleanup:**

```bash
rm -rf "${EC03_DIR}"
```

### EC-04: Missing source URL (only REVISION and PATH defined)

```bash
export EC04_DIR="${KANON_TEST_ROOT}/test-ec04"
mkdir -p "${EC04_DIR}"

cat > "${EC04_DIR}/.kanon" << 'KANONEOF'
KANON_SOURCE_test_REVISION=main
KANON_SOURCE_test_PATH=meta.xml
KANONEOF

cd "${EC04_DIR}"
kanon install .kanon
```

**Pass criteria:** Exit code 1. stderr contains `No sources found` (since source names are discovered from `_URL` keys, no sources are found).

**Cleanup:**

```bash
rm -rf "${EC04_DIR}"
```

### EC-05: KANON_SOURCES explicitly set (legacy, no longer supported)

```bash
export EC05_DIR="${KANON_TEST_ROOT}/test-ec05"
mkdir -p "${EC05_DIR}"

cat > "${EC05_DIR}/.kanon" << 'KANONEOF'
KANON_SOURCES=build
KANON_SOURCE_build_URL=https://example.com/repo.git
KANON_SOURCE_build_REVISION=main
KANON_SOURCE_build_PATH=meta.xml
KANONEOF

cd "${EC05_DIR}"
kanon install .kanon
```

**Pass criteria:** Exit code 1. stderr contains `no longer supported`.

**Cleanup:**

```bash
rm -rf "${EC05_DIR}"
```

### EC-06: KANON_MARKETPLACE_INSTALL=true without CLAUDE_MARKETPLACES_DIR

```bash
export EC06_DIR="${KANON_TEST_ROOT}/test-ec06"
mkdir -p "${EC06_DIR}"

cat > "${EC06_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=true
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${EC06_DIR}"
kanon install .kanon
```

**Pass criteria:** Exit code 1. stderr contains `KANON_MARKETPLACE_INSTALL=true but CLAUDE_MARKETPLACES_DIR is not defined`.

**Cleanup:**

```bash
rm -rf "${EC06_DIR}"
```

### EC-07: No subcommand

```bash
kanon
```

**Pass criteria:** Exit code 2. stdout or stderr shows usage information.

### EC-08: Invalid subcommand

```bash
kanon nonexistent
```

**Pass criteria:** Exit code 2.

### EC-09: Missing required args for subcommands

**Install without path:**

```bash
kanon install
```

**Pass criteria:** Exit code 2.

**Clean without path:**

```bash
kanon clean
```

**Pass criteria:** Exit code 2.

**Validate without target:**

```bash
kanon validate
```

**Pass criteria:** Exit code 2. stderr contains `Must specify a validation target`.

---

## 10. Category 9: Idempotency (3 tests)

### ID-01: Double install succeeds

```bash
export ID01_DIR="${KANON_TEST_ROOT}/test-id01"
mkdir -p "${ID01_DIR}"

cat > "${ID01_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${ID01_DIR}"
kanon install .kanon
kanon install .kanon
```

**Pass criteria:**
- Both invocations exit with code 0
- Second install produces `kanon install: done`
- `.packages/pkg-alpha` symlink exists after second run

**Cleanup:**

```bash
cd "${ID01_DIR}"
kanon clean .kanon
rm -rf "${ID01_DIR}"
```

### ID-02: Clean without prior install succeeds

```bash
export ID02_DIR="${KANON_TEST_ROOT}/test-id02"
mkdir -p "${ID02_DIR}"

cat > "${ID02_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${ID02_DIR}"
kanon clean .kanon
```

**Pass criteria:**
- Exit code 0
- stdout contains `kanon clean: done`
- No directories `.packages/` or `.kanon-data/` exist (they were never created)

**Cleanup:**

```bash
rm -rf "${ID02_DIR}"
```

### ID-03: Double clean succeeds

```bash
export ID03_DIR="${KANON_TEST_ROOT}/test-id03"
mkdir -p "${ID03_DIR}"

cat > "${ID03_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${ID03_DIR}"
kanon install .kanon
kanon clean .kanon
kanon clean .kanon
```

**Pass criteria:**
- All three invocations exit with code 0
- After the second clean, `.packages/` and `.kanon-data/` do not exist

**Cleanup:**

```bash
rm -rf "${ID03_DIR}"
```

---

## 11. Category 10: Environment Variable Overrides (3 tests)

### EV-01: GITBASE override via environment

```bash
export EV01_DIR="${KANON_TEST_ROOT}/test-ev01"
mkdir -p "${EV01_DIR}"

cat > "${EV01_DIR}/.kanon" << KANONEOF
GITBASE=https://default.example.com
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${EV01_DIR}"
GITBASE=https://override.example.com kanon install .kanon
```

**Pass criteria:**
- Exit code 0
- The environment variable `GITBASE` overrides the file value
- stdout contains `kanon install: done`

**Cleanup:**

```bash
cd "${EV01_DIR}"
kanon clean .kanon
rm -rf "${EV01_DIR}"
```

### EV-02: KANON_MARKETPLACE_INSTALL override via environment

```bash
export EV02_DIR="${KANON_TEST_ROOT}/test-ev02"
mkdir -p "${EV02_DIR}"

cat > "${EV02_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=true
CLAUDE_MARKETPLACES_DIR=/tmp/kanon-test-marketplaces
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${EV02_DIR}"
KANON_MARKETPLACE_INSTALL=false kanon install .kanon
```

**Pass criteria:**
- Exit code 0
- stdout does NOT contain `marketplace` (the env override set it to false)
- stdout contains `kanon install: done`

**Cleanup:**

```bash
cd "${EV02_DIR}"
KANON_MARKETPLACE_INSTALL=false kanon clean .kanon
rm -rf "${EV02_DIR}"
```

### EV-03: KANON_CATALOG_SOURCE env var for bootstrap

This test requires a local git repo that acts as a remote catalog source.

```bash
export CUSTOM_CATALOG_DIR="${KANON_TEST_ROOT}/fixtures/custom-catalog"
mkdir -p "${CUSTOM_CATALOG_DIR}/catalog/my-template"
cd "${CUSTOM_CATALOG_DIR}"
git init

cat > catalog/my-template/.kanon << 'KANONEOF'
# Custom catalog template
KANON_MARKETPLACE_INSTALL=false
KANONEOF

echo "# Custom Template" > catalog/my-template/custom-readme.md
git add .
git commit -m "Initial custom catalog"
git tag v1.0.0

export EV03_DIR="${KANON_TEST_ROOT}/test-ev03"
mkdir -p "${EV03_DIR}"
KANON_CATALOG_SOURCE="file://${CUSTOM_CATALOG_DIR}@v1.0.0" kanon bootstrap list
```

**Pass criteria:**
- Exit code 0
- stdout contains `my-template`

**Cleanup:**

```bash
rm -rf "${EV03_DIR}" "${CUSTOM_CATALOG_DIR}"
```

---

## 12. Category 11: Validate Commands (4 tests)

### VA-01: Validate xml in a repo with manifests

```bash
export VA01_DIR="${KANON_TEST_ROOT}/test-va01"
mkdir -p "${VA01_DIR}/repo-specs"
cd "${VA01_DIR}"
git init

cat > repo-specs/test.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com" />
  <project name="proj" path=".packages/proj" remote="origin" revision="main" />
</manifest>
XMLEOF

git add .
git commit -m "Add valid manifest"
kanon validate xml
```

**Pass criteria:**
- Exit code 0
- stdout contains `valid` or `1 manifest files are valid`

**Cleanup:**

```bash
rm -rf "${VA01_DIR}"
```

### VA-02: Validate marketplace in a repo with marketplace manifests

```bash
export VA02_DIR="${KANON_TEST_ROOT}/test-va02"
mkdir -p "${VA02_DIR}/repo-specs"
cd "${VA02_DIR}"
git init

cat > repo-specs/test-marketplace.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/proj/1.0.0">
    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
  </project>
</manifest>
XMLEOF

git add .
git commit -m "Add valid marketplace manifest"
kanon validate marketplace
```

**Pass criteria:**
- Exit code 0
- stdout contains `passed` or `1 marketplace files passed`

**Cleanup:**

```bash
rm -rf "${VA02_DIR}"
```

### VA-03: Validate xml with --repo-root from outside the repo

```bash
export VA03_DIR="${KANON_TEST_ROOT}/test-va03"
mkdir -p "${VA03_DIR}/repo-specs"
cd "${VA03_DIR}"
git init

cat > repo-specs/another.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com" />
  <project name="proj" path=".packages/proj" remote="origin" revision="main" />
</manifest>
XMLEOF

git add .
git commit -m "Add manifest"

cd /tmp
kanon validate xml --repo-root "${VA03_DIR}"
```

**Pass criteria:**
- Exit code 0
- stdout contains `valid`

**Cleanup:**

```bash
rm -rf "${VA03_DIR}"
```

### VA-04: Validate in empty directory (no repo-specs)

```bash
export VA04_DIR="${KANON_TEST_ROOT}/test-va04"
mkdir -p "${VA04_DIR}/repo-specs"
cd "${VA04_DIR}"
git init
git commit --allow-empty -m "empty repo"

kanon validate xml --repo-root "${VA04_DIR}"
```

**Pass criteria:**
- Exit code 1
- stderr contains `No XML files found`

**Cleanup:**

```bash
rm -rf "${VA04_DIR}"
```

---

## 13. Category 12: Entry Points (2 tests)

### EP-01: python -m kanon_cli --version

```bash
python -m kanon_cli --version
```

**Pass criteria:** Exit code 0. stdout matches `kanon \d+\.\d+\.\d+`.

### EP-02: python -m kanon_cli --help

```bash
python -m kanon_cli --help
```

**Pass criteria:** Exit code 0. stdout contains `install`, `clean`, `validate`, `bootstrap`.

---

## 14. Category 13: Catalog Source PEP 440 Constraints (26 tests)

These tests verify that `--catalog-source` and `KANON_CATALOG_SOURCE` resolve PEP 440 version constraints against git tags before cloning. Every PEP 440 operator is tested via both the CLI flag and the environment variable.

Run this category twice:
1. **Pre-merge:** with kanon installed in editable mode (`pip install -e .`) from the local checkout
2. **Post-release:** with kanon installed from PyPI (`pipx install kanon-cli`) after the release

### Fixture setup

Create a local catalog repo with multiple semver tags:

```bash
export CS_CATALOG_DIR="${KANON_TEST_ROOT}/fixtures/cs-catalog"
mkdir -p "${CS_CATALOG_DIR}/catalog/test-entry"
cd "${CS_CATALOG_DIR}"
git init

cat > catalog/test-entry/.kanon << 'KANONEOF'
KANON_MARKETPLACE_INSTALL=false
KANONEOF

git add .
git commit -m "init"
git tag 1.0.0
git commit --allow-empty -m "1.0.1"
git tag 1.0.1
git commit --allow-empty -m "1.1.0"
git tag 1.1.0
git commit --allow-empty -m "1.2.0"
git tag 1.2.0
git commit --allow-empty -m "2.0.0"
git tag 2.0.0
git commit --allow-empty -m "2.1.0"
git tag 2.1.0
git commit --allow-empty -m "3.0.0"
git tag 3.0.0
```

### CS-01: Wildcard `*` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@*"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to tag `3.0.0`.

### CS-02: Wildcard `*` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@*" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to tag `3.0.0`.

### CS-03: `latest` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@latest"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to tag `3.0.0`.

### CS-04: `latest` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@latest" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to tag `3.0.0`.

### CS-05: Compatible release `~=1.0.0` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@~=1.0.0"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `1.0.1` (highest matching `>=1.0.0,<1.1.0`).

### CS-06: Compatible release `~=1.0.0` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@~=1.0.0" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `1.0.1`.

### CS-07: Compatible release `~=2.0.0` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@~=2.0.0"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `2.0.0` (highest matching `>=2.0.0,<2.1.0`).

### CS-08: Compatible release `~=2.0.0` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@~=2.0.0" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `2.0.0`.

### CS-09: Range `>=1.0.0,<2.0.0` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@>=1.0.0,<2.0.0"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `1.2.0` (highest 1.x).

### CS-10: Range `>=1.0.0,<2.0.0` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@>=1.0.0,<2.0.0" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `1.2.0`.

### CS-11: Range `>=2.0.0,<3.0.0` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@>=2.0.0,<3.0.0"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `2.1.0` (highest 2.x).

### CS-12: Range `>=2.0.0,<3.0.0` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@>=2.0.0,<3.0.0" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `2.1.0`.

### CS-13: Minimum `>=1.0.0` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@>=1.0.0"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `3.0.0` (highest available).

### CS-14: Minimum `>=1.0.0` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@>=1.0.0" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `3.0.0`.

### CS-15: Less than `<2.0.0` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@<2.0.0"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `1.2.0` (highest below 2.0.0).

### CS-16: Less than `<2.0.0` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@<2.0.0" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `1.2.0`.

### CS-17: Less than or equal `<=2.0.0` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@<=2.0.0"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `2.0.0`.

### CS-18: Less than or equal `<=2.0.0` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@<=2.0.0" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `2.0.0`.

### CS-19: Exact `==1.1.0` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@==1.1.0"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to exactly `1.1.0`.

### CS-20: Exact `==1.1.0` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@==1.1.0" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to exactly `1.1.0`.

### CS-21: Exclusion `!=1.0.0` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@!=1.0.0"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `3.0.0` (highest non-excluded).

### CS-22: Exclusion `!=1.0.0` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@!=1.0.0" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `3.0.0`.

### CS-23: Open range `>1.0.0,<2.0.0` via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@>1.0.0,<2.0.0"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `1.2.0` (highest in open range).

### CS-24: Open range `>1.0.0,<2.0.0` via env var

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@>1.0.0,<2.0.0" kanon bootstrap list
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. Resolves to `1.2.0`.

### CS-25: Plain branch passthrough via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@main"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. No constraint resolution occurs; `main` is passed directly to `git clone --branch`.

### CS-26: Plain tag passthrough via flag

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@2.0.0"
```

**Pass criteria:** Exit code 0. stdout contains `test-entry`. No constraint resolution occurs; `2.0.0` is passed directly to `git clone --branch`.

**Cleanup:**

```bash
rm -rf "${CS_CATALOG_DIR}"
```

---

## 15. Install Verification Details

After any successful `kanon install`, verify the following artifacts:

### 14.1 .gitignore contents

```bash
grep -q "^\.packages/$" .gitignore && echo "PASS: .packages/ in .gitignore" || echo "FAIL"
grep -q "^\.kanon-data/$" .gitignore && echo "PASS: .kanon-data/ in .gitignore" || echo "FAIL"
```

### 14.2 .packages/ contains symlinks

```bash
for entry in .packages/*; do
  if [ -L "${entry}" ]; then
    echo "PASS: ${entry} is a symlink"
  else
    echo "FAIL: ${entry} is not a symlink"
  fi
done
```

### 14.3 Symlinks point into .kanon-data/sources/

```bash
for entry in .packages/*; do
  target=$(readlink -f "${entry}")
  if echo "${target}" | grep -q ".kanon-data/sources/"; then
    echo "PASS: ${entry} -> ${target} (inside .kanon-data/sources/)"
  else
    echo "FAIL: ${entry} -> ${target} (not inside .kanon-data/sources/)"
  fi
done
```

### 14.4 .kanon-data/sources/ has one directory per source

```bash
source_count=$(ls -1d .kanon-data/sources/*/ 2>/dev/null | wc -l)
echo "Source directories found: ${source_count}"
ls -1d .kanon-data/sources/*/
```

**Pass criteria:** The number of directories matches the number of `KANON_SOURCE_<name>_URL` entries in the `.kanon` file. Each directory name matches the `<name>` portion of the source variable.

---

## 16. How to Run

### Full sequential run

Execute all tests sequentially. Each test section is independent and includes
its own cleanup. Run them in order from Category 1 through Category 13.

```bash
set -euo pipefail

export KANON_TEST_ROOT="/tmp/kanon-integration-tests"
rm -rf "${KANON_TEST_ROOT}"
mkdir -p "${KANON_TEST_ROOT}"

# 1. Run Category 1 (Help & Version) -- HV-01 through HV-08
# 2. Run Category 2 (Bootstrap) -- BS-01 through BS-05
# 3. Run Category 3 (Create Fixtures) -- all fixture setup commands
# 4. Run Category 4 (Install/Clean Lifecycle) -- IC-01 through IC-04
# 5. Run Category 5 (Multi-Source) -- MS-01
# 6. Run Category 6 (Collision Detection) -- CD-01 through CD-02
# 7. Run Category 7 (Linkfile Packages) -- LF-01
# 8. Run Category 8 (Error Cases) -- EC-01 through EC-09
# 9. Run Category 9 (Idempotency) -- ID-01 through ID-03
# 10. Run Category 10 (Environment Variable Overrides) -- EV-01 through EV-03
# 11. Run Category 11 (Validate Commands) -- VA-01 through VA-04
# 12. Run Category 12 (Entry Points) -- EP-01 through EP-02
# 13. Run Category 13 (Catalog Source PEP 440 Constraints) -- CS-01 through CS-26
```

### Cleanup between tests

Each test includes its own cleanup section. If a test fails mid-execution,
run the cleanup for that test before proceeding.

### Global cleanup

To remove all test artifacts:

```bash
rm -rf "${KANON_TEST_ROOT}"
```

### Test execution notes

- Categories 1, 2, 8 (error cases), 9, 11, and 12 do not depend on the
  fixtures from Category 3.
- Categories 4, 5, 6, and 7 require the fixtures from Category 3 to be
  created first.
- Category 10 (EV-03 specifically) creates its own fixture.
- For tests that expect non-zero exit codes, capture the exit code before
  asserting on it:

```bash
set +e
kanon install .kanon
exit_code=$?
set -e
if [ "${exit_code}" -ne 1 ]; then
  echo "FAIL: expected exit code 1, got ${exit_code}"
fi
```

### Test summary format

For each test, report results as:

```
[PASS] HV-01: Top-level help
[FAIL] HV-02: Version flag -- expected exit code 0, got 1
```
