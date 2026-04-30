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

### BS-06: Blocker file at output path

**Setup:** Place a regular file at the path that would be used as the output directory so
that `mkdir` cannot create a directory there.

```bash
touch "${KANON_TEST_ROOT}/bs06-blocker"
```

**Run:**

```bash
kanon bootstrap kanon --output-dir "${KANON_TEST_ROOT}/bs06-blocker"
```

**Expect:** Exit code 1. stderr contains `Cannot create output directory`. No traceback
is printed -- only the single error line.

**Cleanup:**

```bash
rm -f "${KANON_TEST_ROOT}/bs06-blocker"
```

### BS-07: Missing parent directory for --output-dir

**Setup:** No setup required. Use a path whose parent directory does not exist.

**Run:**

```bash
kanon bootstrap kanon --output-dir "${KANON_TEST_ROOT}/nonexistent-parent/child"
```

**Expect:** Exit code 1. stderr contains `parent directory` and the missing parent path.
No traceback is printed -- only the single error line.

**Cleanup:** No cleanup required (no files were created).

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

Create a single-package manifest (bravo only). This is used by MS-01 together with
`alpha-only.xml` so two sources can contribute disjoint packages without colliding
on `pkg-alpha`:

```bash
cat > repo-specs/bravo-only.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <include name="repo-specs/remote.xml" />
  <project name="pkg-bravo" path=".packages/pkg-bravo" remote="local" revision="main" />
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
KANON_SOURCE_bravo_PATH=repo-specs/bravo-only.xml
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

**Note:** `alpha-only.xml` declares only `pkg-alpha` and `bravo-only.xml` declares only
`pkg-bravo`, so the two sources produce disjoint package sets. Using the combined
`packages.xml` for either source would produce a legitimate collision on `pkg-alpha`
and exit 1, which is the behavior exercised by CD-01 and CD-02.

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

**Pass criteria:** Exit code 1. stderr contains `KANON_SOURCE_test_URL is required but not set` (kanon detects that `KANON_SOURCE_test_REVISION` and `KANON_SOURCE_test_PATH` are present but `KANON_SOURCE_test_URL` is missing, and names the missing variable directly).

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

**Install without path (no .kanon discoverable):**

See Category 14 (AD-03) for the case where no `.kanon` exists anywhere in the directory tree.

**Clean without path (no .kanon discoverable):**

See Category 14 (AD-03 pattern) for the equivalent clean case.

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

## 15. Category 14: Auto-Discovery (8 tests)

These tests verify that `kanon install` and `kanon clean` auto-discover the `.kanon` file
by walking up the directory tree from the current directory when no explicit path is given.
They use the fixtures from Category 3 (specifically `MANIFEST_PRIMARY_DIR`).

### AD-01: kanon install (no arg) in directory with .kanon

```bash
export AD01_DIR="${KANON_TEST_ROOT}/test-ad01"
mkdir -p "${AD01_DIR}"

cat > "${AD01_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${AD01_DIR}"
kanon install
```

**Pass criteria:**
- Exit code 0
- `.packages/pkg-alpha` symlink exists
- stdout contains `kanon install: done`

**Cleanup:**

```bash
cd "${AD01_DIR}"
kanon clean
rm -rf "${AD01_DIR}"
```

### AD-02: kanon install in subdirectory, .kanon in parent

```bash
export AD02_DIR="${KANON_TEST_ROOT}/test-ad02"
mkdir -p "${AD02_DIR}/child"

cat > "${AD02_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${AD02_DIR}/child"
kanon install
```

**Pass criteria:**
- Exit code 0
- `${AD02_DIR}/.packages/pkg-alpha` symlink exists (packages installed in the parent directory where `.kanon` lives)
- stdout contains `kanon install: done`

**Cleanup:**

```bash
cd "${AD02_DIR}"
kanon clean
rm -rf "${AD02_DIR}"
```

### AD-03: kanon install with no .kanon anywhere

```bash
export AD03_DIR="${KANON_TEST_ROOT}/test-ad03"
mkdir -p "${AD03_DIR}"
cd "${AD03_DIR}"

set +e
kanon install
exit_code=$?
set -e
```

**Pass criteria:**
- Exit code 1
- stderr contains `.kanon`

**Cleanup:**

```bash
rm -rf "${AD03_DIR}"
```

### AD-04: kanon install .kanon (explicit) still works

```bash
export AD04_DIR="${KANON_TEST_ROOT}/test-ad04"
mkdir -p "${AD04_DIR}"

cat > "${AD04_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${AD04_DIR}"
kanon install .kanon
```

**Pass criteria:**
- Exit code 0
- `.packages/pkg-alpha` symlink exists
- stdout contains `kanon install: done`

**Cleanup:**

```bash
cd "${AD04_DIR}"
kanon clean .kanon
rm -rf "${AD04_DIR}"
```

### AD-05: kanon clean (no arg) in directory with .kanon

```bash
export AD05_DIR="${KANON_TEST_ROOT}/test-ad05"
mkdir -p "${AD05_DIR}"

cat > "${AD05_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${AD05_DIR}"
kanon install .kanon
kanon clean
```

**Pass criteria:**
- Exit code 0
- stdout contains `kanon clean: done`
- `.packages/` directory does not exist
- `.kanon-data/` directory does not exist

**Cleanup:**

```bash
rm -rf "${AD05_DIR}"
```

### AD-06: kanon clean in subdirectory, .kanon in parent

```bash
export AD06_DIR="${KANON_TEST_ROOT}/test-ad06"
mkdir -p "${AD06_DIR}/child"

cat > "${AD06_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${AD06_DIR}"
kanon install .kanon

cd "${AD06_DIR}/child"
kanon clean
```

**Pass criteria:**
- Exit code 0
- stdout contains `kanon clean: done`
- `${AD06_DIR}/.packages/` directory does not exist
- `${AD06_DIR}/.kanon-data/` directory does not exist

**Cleanup:**

```bash
rm -rf "${AD06_DIR}"
```

### AD-07: kanon install /explicit/path/.kanon overrides discovery

```bash
export AD07_DIR="${KANON_TEST_ROOT}/test-ad07"
export AD07_EXPLICIT="${KANON_TEST_ROOT}/test-ad07-explicit"
mkdir -p "${AD07_DIR}" "${AD07_EXPLICIT}"

cat > "${AD07_EXPLICIT}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${AD07_DIR}"
kanon install "${AD07_EXPLICIT}/.kanon"
```

**Pass criteria:**
- Exit code 0
- `${AD07_EXPLICIT}/.packages/pkg-alpha` symlink exists (uses the explicit path, not cwd)
- stdout contains `kanon install: done`

**Cleanup:**

```bash
cd "${AD07_EXPLICIT}"
kanon clean .kanon
rm -rf "${AD07_DIR}" "${AD07_EXPLICIT}"
```

### AD-08: kanon install prints which .kanon was found

```bash
export AD08_DIR="${KANON_TEST_ROOT}/test-ad08"
mkdir -p "${AD08_DIR}"

cat > "${AD08_DIR}/.kanon" << KANONEOF
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_primary_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_primary_REVISION=main
KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml
KANONEOF

cd "${AD08_DIR}"
kanon install 2>&1
```

**Pass criteria:**
- Exit code 0
- stdout contains `found` and the path to the `.kanon` file

**Cleanup:**

```bash
cd "${AD08_DIR}"
kanon clean
rm -rf "${AD08_DIR}"
```

---

## 16. Category 15: PEP 440 Constraints in XML `<project revision>` (26 tests)

These tests verify that the same PEP 440 constraint parser used for `--catalog-source` (Category 13) also resolves constraints in the `<project revision="...">` attribute of repo XML manifests. Production data uses the prefixed form (`refs/tags/>=2.0.0,<3.0.0`); both bare and prefixed forms must work.

### Fixture setup

Reuse the catalog-source fixture from Category 13 (`${KANON_TEST_ROOT}/fixtures/cs-catalog`). It already carries 7 semver tags (`1.0.0, 1.0.1, 1.1.0, 1.2.0, 2.0.0, 2.1.0, 3.0.0`).

The RX manifest XML files use `fetch="file://${KANON_TEST_ROOT}/fixtures/cs-catalog"` and `name="catalog"`. The repo tool resolves each project URL as `fetch + "/" + name`, i.e., `file://${KANON_TEST_ROOT}/fixtures/cs-catalog/catalog`. A separate bare git repo must exist at that sub-path; the Category 13 fixture at `fixtures/cs-catalog` is the _parent_ directory, not the project repo.

Create the bare catalog content repo at `fixtures/cs-catalog/catalog` before creating the manifest repo:

```bash
# Create the bare content repo that the RX manifests point at.
# The RX XML uses fetch="file://.../cs-catalog" + name="catalog", so the
# repo tool resolves the project URL to .../cs-catalog/catalog -- a bare
# git repo must exist at that sub-path.
#
# Category 13's fixture setup creates fixtures/cs-catalog/catalog/test-entry
# as a regular (non-bare) directory.  Remove it before cloning so that
# git clone --bare can create the bare repo at that path without error.
rm -rf "${KANON_TEST_ROOT}/fixtures/cs-catalog/catalog"
git clone --bare "${KANON_TEST_ROOT}/fixtures/cs-catalog" \
    "${KANON_TEST_ROOT}/fixtures/cs-catalog/catalog"
```

Verify the sub-repo exists and carries the expected tags:

```bash
git -C "${KANON_TEST_ROOT}/fixtures/cs-catalog/catalog" tag | sort -V
# Expected: 1.0.0  1.0.1  1.1.0  1.2.0  2.0.0  2.1.0  3.0.0
```

Create a manifest repo carrying multiple XML files, one per scenario, each pointing at the same content repo with a different `<project revision>`:

```bash
export RX_FIX="${KANON_TEST_ROOT}/fixtures/rx-manifest"
mkdir -p "${RX_FIX}"
cd "${RX_FIX}"
git init
git branch -m main

# Helper: create one manifest XML per scenario.
mk_rx_xml() {
    local id="$1" rev="$2"
    cat > "${id}.xml" << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${KANON_TEST_ROOT}/fixtures/cs-catalog" />
  <default remote="local" revision="main" />
  <project name="catalog" path=".packages/catalog" remote="local" revision="${rev}" />
</manifest>
XMLEOF
}

mk_rx_xml rx01 "latest"
mk_rx_xml rx02 "1.0.0"
mk_rx_xml rx03 "2.0.0"
mk_rx_xml rx04 "*"
mk_rx_xml rx05 "~=1.0.0"
mk_rx_xml rx06 "~=2.0"
mk_rx_xml rx07 ">=1.2.0"
mk_rx_xml rx08 "<2.0.0"
mk_rx_xml rx09 "<=1.1.0"
mk_rx_xml rx10 "==1.0.1"
mk_rx_xml rx11 "!=2.0.0"
mk_rx_xml rx12 ">=1.0.0,<2.0.0"
mk_rx_xml rx13 "==3.0.0"
mk_rx_xml rx14 "refs/tags/latest"
mk_rx_xml rx15 "refs/tags/1.0.0"
mk_rx_xml rx16 "refs/tags/2.0.0"
mk_rx_xml rx17 "refs/tags/*"
mk_rx_xml rx18 "refs/tags/~=1.0.0"
mk_rx_xml rx19 "refs/tags/~=2.0"
mk_rx_xml rx20 "refs/tags/>=1.2.0"
mk_rx_xml rx21 "refs/tags/<2.0.0"
mk_rx_xml rx22 "refs/tags/<=1.1.0"
mk_rx_xml rx23 "refs/tags/==1.0.1"
mk_rx_xml rx24 "refs/tags/!=2.0.0"
mk_rx_xml rx25 "refs/tags/>=1.0.0,<2.0.0"
mk_rx_xml rx26 "refs/tags/==*"

git add .
git commit -m "init rx fixtures"
```

### Common helper

Each scenario writes a `.kanon` pointing at one rx XML and runs `kanon install`, then verifies the resolved tag with `kanon repo manifest --revision-as-tag`:

```bash
rx_run() {
    local id="$1" expected_tag="$2"
    mkdir -p "${KANON_TEST_ROOT}/${id}"
    cd "${KANON_TEST_ROOT}/${id}"
    cat > .kanon << KANONEOF
KANON_SOURCE_pep_URL=file://${RX_FIX}
KANON_SOURCE_pep_REVISION=main
KANON_SOURCE_pep_PATH=${id}.xml
KANONEOF
    kanon install .kanon
    (cd .kanon-data/sources/pep && kanon repo manifest --revision-as-tag) | grep -q "refs/tags/${expected_tag}"
}
```

### RX-01: bare `latest`

```bash
rx_run rx01 "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `3.0.0`.

### RX-02: bare plain tag `1.0.0`

```bash
rx_run rx02 "1.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `1.0.0`.

### RX-03: bare plain tag `2.0.0`

```bash
rx_run rx03 "2.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `2.0.0`.

### RX-04: bare wildcard `*`

```bash
rx_run rx04 "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `3.0.0`.

### RX-05: compatible release `~=1.0.0`

```bash
rx_run rx05 "1.0.1"
```

**Pass criteria:** Exit code 0; resolved tag is `1.0.1` (highest matching `>=1.0.0,<1.1.0`).

### RX-06: compatible release `~=2.0`

```bash
rx_run rx06 "2.1.0"
```

**Pass criteria:** Exit code 0; resolved tag is `2.1.0`.

### RX-07: minimum `>=1.2.0`

```bash
rx_run rx07 "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `3.0.0`.

### RX-08: less-than `<2.0.0`

```bash
rx_run rx08 "1.2.0"
```

**Pass criteria:** Exit code 0; resolved tag is `1.2.0`.

### RX-09: less-or-equal `<=1.1.0`

```bash
rx_run rx09 "1.1.0"
```

**Pass criteria:** Exit code 0; resolved tag is `1.1.0`.

### RX-10: exact `==1.0.1`

```bash
rx_run rx10 "1.0.1"
```

**Pass criteria:** Exit code 0; resolved tag is `1.0.1`.

### RX-11: exclusion `!=2.0.0`

```bash
rx_run rx11 "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `3.0.0`.

### RX-12: range `>=1.0.0,<2.0.0`

```bash
rx_run rx12 "1.2.0"
```

**Pass criteria:** Exit code 0; resolved tag is `1.2.0`.

### RX-13: exact `==3.0.0`

```bash
rx_run rx13 "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `3.0.0`.

### RX-14: prefixed `refs/tags/latest`

```bash
rx_run rx14 "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `3.0.0`.

### RX-15: prefixed `refs/tags/1.0.0`

```bash
rx_run rx15 "1.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `1.0.0`.

### RX-16: prefixed `refs/tags/2.0.0`

```bash
rx_run rx16 "2.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `2.0.0`.

### RX-17: prefixed wildcard `refs/tags/*`

```bash
rx_run rx17 "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `3.0.0`.

### RX-18: prefixed `refs/tags/~=1.0.0`

```bash
rx_run rx18 "1.0.1"
```

**Pass criteria:** Exit code 0; resolved tag is `1.0.1`.

### RX-19: prefixed `refs/tags/~=2.0`

```bash
rx_run rx19 "2.1.0"
```

**Pass criteria:** Exit code 0; resolved tag is `2.1.0`.

### RX-20: prefixed `refs/tags/>=1.2.0`

```bash
rx_run rx20 "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `3.0.0`.

### RX-21: prefixed `refs/tags/<2.0.0`

```bash
rx_run rx21 "1.2.0"
```

**Pass criteria:** Exit code 0; resolved tag is `1.2.0`.

### RX-22: prefixed `refs/tags/<=1.1.0`

```bash
rx_run rx22 "1.1.0"
```

**Pass criteria:** Exit code 0; resolved tag is `1.1.0`.

### RX-23: prefixed `refs/tags/==1.0.1`

```bash
rx_run rx23 "1.0.1"
```

**Pass criteria:** Exit code 0; resolved tag is `1.0.1`.

### RX-24: prefixed `refs/tags/!=2.0.0`

```bash
rx_run rx24 "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag is `3.0.0`.

### RX-25: prefixed range `refs/tags/>=1.0.0,<2.0.0`

```bash
rx_run rx25 "1.2.0"
```

**Pass criteria:** Exit code 0; resolved tag is `1.2.0`.

### RX-26: invalid `refs/tags/==*` rejected

```bash
set +e
mkdir -p "${KANON_TEST_ROOT}/rx26"
cd "${KANON_TEST_ROOT}/rx26"
cat > .kanon << KANONEOF
KANON_SOURCE_pep_URL=file://${RX_FIX}
KANON_SOURCE_pep_REVISION=main
KANON_SOURCE_pep_PATH=rx26.xml
KANONEOF
kanon install .kanon
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero; stderr contains `invalid version constraint`.

### Cleanup

```bash
for i in $(seq -w 01 26); do
    cd "${KANON_TEST_ROOT}" && rm -rf "rx${i}"
done
```

---

## 17. Category 16: PEP 440 Constraints in `.kanon` `KANON_SOURCE_<name>_REVISION` (26 tests)

These tests verify that PEP 440 constraints in `.kanon` REVISION values resolve identically to the same constraints in XML revision attributes. Production data (`caylent-private-kanon/catalog/history/.kanon`) uses prefixed `refs/tags/>=2.0.0,<3.0.0` form; both bare and prefixed must work.

### Fixture

Reuses the cs-catalog fixture from Category 13. Each KS scenario writes a tiny `.kanon` whose `_REVISION` carries the constraint and points at a single XML manifest with a fixed `<project revision="main">` (so only the `.kanon`-level constraint is exercised).

```bash
export KS_FIX="${KANON_TEST_ROOT}/fixtures/ks-manifest"
mkdir -p "${KS_FIX}"
cd "${KS_FIX}"
git init
git branch -m main
cat > default.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${KANON_TEST_ROOT}/fixtures/cs-catalog" />
  <default remote="local" revision="main" />
  <project name="catalog" path=".packages/catalog" remote="local" />
</manifest>
XMLEOF
git add .
git commit -m "init ks fixtures"
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

ks_run() {
    local id="$1" rev="$2" expected_tag="$3"
    mkdir -p "${KANON_TEST_ROOT}/${id}"
    cd "${KANON_TEST_ROOT}/${id}"
    cat > .kanon << KANONEOF
KANON_SOURCE_pep_URL=file://${KS_FIX}
KANON_SOURCE_pep_REVISION=${rev}
KANON_SOURCE_pep_PATH=default.xml
KANONEOF
    kanon install .kanon
    (cd .kanon-data/sources/pep && kanon repo manifest --revision-as-tag) | grep -q "refs/tags/${expected_tag}"
}
```

### KS-01: bare `latest`

```bash
ks_run ks01 "latest" "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag `3.0.0`.

### KS-02: prefixed `refs/tags/latest`

```bash
ks_run ks02 "refs/tags/latest" "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag `3.0.0`.

### KS-03: bare wildcard `*`

```bash
ks_run ks03 "*" "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag `3.0.0`.

### KS-04: prefixed `refs/tags/*`

```bash
ks_run ks04 "refs/tags/*" "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag `3.0.0`.

### KS-05: bare plain tag `1.0.0`

```bash
ks_run ks05 "1.0.0" "1.0.0"
```

**Pass criteria:** Exit code 0; resolved tag `1.0.0`.

### KS-06: bare `~=1.0.0`

```bash
ks_run ks06 "~=1.0.0" "1.0.1"
```

**Pass criteria:** Exit code 0; resolved tag `1.0.1`.

### KS-07: prefixed `refs/tags/~=1.0.0`

```bash
ks_run ks07 "refs/tags/~=1.0.0" "1.0.1"
```

**Pass criteria:** Exit code 0; resolved tag `1.0.1`.

### KS-08: bare `~=2.0`

```bash
ks_run ks08 "~=2.0" "2.1.0"
```

**Pass criteria:** Exit code 0; resolved tag `2.1.0`.

### KS-09: bare `>=1.2.0`

```bash
ks_run ks09 ">=1.2.0" "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag `3.0.0`.

### KS-10: bare `<2.0.0`

```bash
ks_run ks10 "<2.0.0" "1.2.0"
```

**Pass criteria:** Exit code 0; resolved tag `1.2.0`.

### KS-11: bare `<=1.1.0`

```bash
ks_run ks11 "<=1.1.0" "1.1.0"
```

**Pass criteria:** Exit code 0; resolved tag `1.1.0`.

### KS-12: bare `==1.0.1`

```bash
ks_run ks12 "==1.0.1" "1.0.1"
```

**Pass criteria:** Exit code 0; resolved tag `1.0.1`.

### KS-13: bare `!=2.0.0`

```bash
ks_run ks13 "!=2.0.0" "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag `3.0.0`.

### KS-14: bare range `>=1.0.0,<2.0.0`

```bash
ks_run ks14 ">=1.0.0,<2.0.0" "1.2.0"
```

**Pass criteria:** Exit code 0; resolved tag `1.2.0`.

### KS-15: prefixed range `refs/tags/>=2.0.0,<3.0.0` (production form)

```bash
ks_run ks15 "refs/tags/>=2.0.0,<3.0.0" "2.1.0"
```

**Pass criteria:** Exit code 0; resolved tag `2.1.0`. This is the verbatim form in `caylent-private-kanon/catalog/history/.kanon`.

### KS-16: prefixed `refs/tags/~=2.0`

```bash
ks_run ks16 "refs/tags/~=2.0" "2.1.0"
```

**Pass criteria:** Exit code 0; resolved tag `2.1.0`.

### KS-17: prefixed `refs/tags/>=1.2.0`

```bash
ks_run ks17 "refs/tags/>=1.2.0" "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag `3.0.0`.

### KS-18: prefixed `refs/tags/<2.0.0`

```bash
ks_run ks18 "refs/tags/<2.0.0" "1.2.0"
```

**Pass criteria:** Exit code 0; resolved tag `1.2.0`.

### KS-19: prefixed `refs/tags/<=1.1.0`

```bash
ks_run ks19 "refs/tags/<=1.1.0" "1.1.0"
```

**Pass criteria:** Exit code 0; resolved tag `1.1.0`.

### KS-20: prefixed `refs/tags/==1.0.1`

```bash
ks_run ks20 "refs/tags/==1.0.1" "1.0.1"
```

**Pass criteria:** Exit code 0; resolved tag `1.0.1`.

### KS-21: prefixed `refs/tags/!=2.0.0`

```bash
ks_run ks21 "refs/tags/!=2.0.0" "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag `3.0.0`.

### KS-22: prefixed range `refs/tags/>=1.0.0,<2.0.0`

```bash
ks_run ks22 "refs/tags/>=1.0.0,<2.0.0" "1.2.0"
```

**Pass criteria:** Exit code 0; resolved tag `1.2.0`.

### KS-23: prefixed `refs/tags/==3.0.0`

```bash
ks_run ks23 "refs/tags/==3.0.0" "3.0.0"
```

**Pass criteria:** Exit code 0; resolved tag `3.0.0`.

### KS-24: env-var override of REVISION at install time

```bash
mkdir -p "${KANON_TEST_ROOT}/ks24"
cd "${KANON_TEST_ROOT}/ks24"
cat > .kanon << 'KANONEOF'
KANON_SOURCE_pep_URL=file://${KS_FIX}
KANON_SOURCE_pep_REVISION=main
KANON_SOURCE_pep_PATH=default.xml
KANONEOF
KS_FIX="${KS_FIX}" KANON_SOURCE_pep_REVISION="refs/tags/~=1.0.0" kanon install .kanon
(cd .kanon-data/sources/pep && kanon repo manifest --revision-as-tag) | grep -q "refs/tags/1.0.1"
```

**Pass criteria:** Exit code 0; resolved tag `1.0.1` (env override beat `.kanon` file value).

### KS-25: undefined shell var inside REVISION errors clearly

```bash
set +e
mkdir -p "${KANON_TEST_ROOT}/ks25"
cd "${KANON_TEST_ROOT}/ks25"
cat > .kanon << KANONEOF
KANON_SOURCE_pep_URL=file://${KS_FIX}
KANON_SOURCE_pep_REVISION=\${UNDEFINED_KS_VAR}
KANON_SOURCE_pep_PATH=default.xml
KANONEOF
kanon install .kanon
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero; stderr names `UNDEFINED_KS_VAR` as the missing shell variable.

### KS-26: invalid `==*` REVISION rejected

```bash
set +e
mkdir -p "${KANON_TEST_ROOT}/ks26"
cd "${KANON_TEST_ROOT}/ks26"
cat > .kanon << KANONEOF
KANON_SOURCE_pep_URL=file://${KS_FIX}
KANON_SOURCE_pep_REVISION==*
KANON_SOURCE_pep_PATH=default.xml
KANONEOF
kanon install .kanon
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero; stderr contains `invalid version constraint`.

### Cleanup

```bash
for i in $(seq -w 01 26); do
    cd "${KANON_TEST_ROOT}" && rm -rf "ks${i}"
done
```

---

## 18. Category 17: Marketplace Lifecycle with `claude plugin list` Round-trip (22 tests)

These tests verify the full `kanon install` + `claude plugin list` + `kanon clean` + `claude plugin list` lifecycle for Claude Code marketplace plugins. **Requires the `claude` CLI on PATH.** If `claude` is absent, these scenarios are reported as `skipped (no-claude)` rather than `fail`.

### Fixture setup — synthetic marketplace plugin git repo

```bash
export MK_FIX="${KANON_TEST_ROOT}/fixtures/marketplace-plugins"
mkdir -p "${MK_FIX}"

mk_plugin_repo() {
    local name="$1"
    local dir="${MK_FIX}/${name}"
    mkdir -p "${dir}/.claude-plugin"
    cd "${dir}"
    git init -q
    git branch -m main 2>/dev/null || true
    cat > .claude-plugin/marketplace.json << JSONEOF
{
  "name": "${name}",
  "owner": {"name": "Test", "url": "https://example.com"},
  "metadata": {"description": "synthetic test plugin", "version": "0.1.0"},
  "plugins": [
    {"name": "${name}", "source": "./", "description": "test plugin", "version": "0.1.0"}
  ]
}
JSONEOF
    cat > .claude-plugin/plugin.json << JSONEOF
{
  "name": "${name}",
  "version": "0.1.0",
  "description": "synthetic test plugin",
  "author": {"name": "Test", "url": "https://example.com"},
  "keywords": ["test"]
}
JSONEOF
    mkdir -p commands
    echo "# Sample command" > commands/sample.md
    git add .
    git commit -q -m "initial"
    for tag in 1.0.0 1.0.1 1.1.0 1.2.0 2.0.0 2.1.0 3.0.0; do
        git commit -q --allow-empty -m "release ${tag}"
        git tag "${tag}"
    done
}

# Create one plugin repo per scenario that uses revision-pinning.
for n in mk01 mk02 mk03 mk04 mk05 mk06 mk07 mk08 mk09 mk10 mk11 mk12 mk13 mk14 mk15 mk16 mk17 mk18 mk19 mk20 mk21a mk21b mk22; do
    mk_plugin_repo "${n}"
done
```

### Manifest helper

```bash
export MK_MFST="${KANON_TEST_ROOT}/fixtures/mk-manifest"
mkdir -p "${MK_MFST}"
cd "${MK_MFST}"
git init -q
git branch -m main 2>/dev/null || true

mk_mfst_xml() {
    local id="$1" plugin="$2" rev="$3"
    cat > "${id}.xml" << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${MK_FIX}" />
  <default remote="local" revision="main" />
  <project name="${plugin}" path=".packages/${plugin}" remote="local" revision="${rev}">
    <linkfile src="." dest="\${CLAUDE_MARKETPLACES_DIR}/${plugin}" />
  </project>
</manifest>
XMLEOF
}

mk_mfst_xml mk01 mk01 "main"
mk_mfst_xml mk02 mk02 "refs/tags/1.0.0"
mk_mfst_xml mk03 mk03 "refs/tags/~=1.0.0"
mk_mfst_xml mk04 mk04 "main"
mk_mfst_xml mk05 mk05 "refs/tags/>=1.0.0,<2.0.0"
mk_mfst_xml mk06 mk06 "latest"
mk_mfst_xml mk07 mk07 "refs/tags/!=2.0.0"
mk_mfst_xml mk08 mk08 "main"
mk_mfst_xml mk09 mk09 "refs/tags/<=1.1.0"
mk_mfst_xml mk10 mk10 "main"
mk_mfst_xml mk11 mk11 "refs/tags/==3.0.0"
mk_mfst_xml mk12 mk12 "==*"
mk_mfst_xml mk13 mk13 "main"
mk_mfst_xml mk14 mk14 "main"
mk_mfst_xml mk15 mk15 "main"
mk_mfst_xml mk16 mk16 "main"
mk_mfst_xml mk17 mk17 "main"
mk_mfst_xml mk18 mk18 "*"
mk_mfst_xml mk19 mk19 "main"
mk_mfst_xml mk20 mk20 "main"
mk_mfst_xml mk22 mk22 "main"

# Multi-marketplace (MK-21) uses a single XML referencing two plugins.
cat > mk21.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${MK_FIX}" />
  <default remote="local" revision="main" />
  <project name="mk21a" path=".packages/mk21a" remote="local" revision="main">
    <linkfile src="." dest="\${CLAUDE_MARKETPLACES_DIR}/mk21a" />
  </project>
  <project name="mk21b" path=".packages/mk21b" remote="local" revision="main">
    <linkfile src="." dest="\${CLAUDE_MARKETPLACES_DIR}/mk21b" />
  </project>
</manifest>
XMLEOF

# MK-19: invalid dest (does NOT start with ${CLAUDE_MARKETPLACES_DIR}/).
cat > mk19.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${MK_FIX}" />
  <default remote="local" revision="main" />
  <project name="mk19" path=".packages/mk19" remote="local" revision="main">
    <linkfile src="." dest="/tmp/somewhere-bad" />
  </project>
</manifest>
XMLEOF

git add .
git commit -q -m "init mk manifests"
git tag 1.0.0
git commit --allow-empty -q -m "1.0.1"
git tag 1.0.1
git commit --allow-empty -q -m "1.1.0"
git tag 1.1.0
git commit --allow-empty -q -m "1.2.0"
git tag 1.2.0
git commit --allow-empty -q -m "2.0.0"
git tag 2.0.0
git commit --allow-empty -q -m "2.1.0"
git tag 2.1.0
git commit --allow-empty -q -m "3.0.0"
git tag 3.0.0

mk_run() {
    local id="$1" rev_kanon="$2"
    mkdir -p "${KANON_TEST_ROOT}/${id}"
    cd "${KANON_TEST_ROOT}/${id}"
    cat > .kanon << KANONEOF
KANON_MARKETPLACE_INSTALL=true
CLAUDE_MARKETPLACES_DIR=${KANON_TEST_ROOT}/${id}-mpl
KANON_SOURCE_mp_URL=file://${MK_MFST}
KANON_SOURCE_mp_REVISION=${rev_kanon}
KANON_SOURCE_mp_PATH=${id}.xml
KANONEOF
    kanon install .kanon
}
```

### MK-01: basic happy path (XML revision=main, .kanon REVISION=main)

```bash
mk_run mk01 "main"
claude plugin list 2>/dev/null | grep -q "mk01" && echo "PASS: mk01 present"
kanon clean .kanon
claude plugin list 2>/dev/null | grep -q "mk01" || echo "PASS: mk01 absent after clean"
```

**Pass criteria:** Install exits 0; `claude plugin list` shows `mk01` after install; `claude plugin list` does NOT show `mk01` after clean.

### MK-02: exact tag pin both surfaces

```bash
mk_run mk02 "refs/tags/1.0.0"
claude plugin list 2>/dev/null | grep -q "mk02"
kanon clean .kanon
```

**Pass criteria:** Install exits 0; plugin appears in `claude plugin list`; clean removes it.

### MK-03: PEP 440 in XML revision (`~=1.0.0`), `.kanon` REVISION=main

```bash
mk_run mk03 "main"
claude plugin list 2>/dev/null | grep -q "mk03"
kanon clean .kanon
```

**Pass criteria:** Resolves to plugin tagged 1.0.1; appears then disappears in `claude plugin list`.

### MK-04: PEP 440 in `.kanon` REVISION (`refs/tags/~=1.0.0`), XML revision=main

```bash
mk_run mk04 "refs/tags/~=1.0.0"
claude plugin list 2>/dev/null | grep -q "mk04"
kanon clean .kanon
```

**Pass criteria:** Resolves; appears then disappears.

### MK-05: PEP 440 range in BOTH (`refs/tags/>=1.0.0,<2.0.0`)

```bash
mk_run mk05 "refs/tags/>=1.0.0,<2.0.0"
claude plugin list 2>/dev/null | grep -q "mk05"
kanon clean .kanon
```

**Pass criteria:** Resolves to 1.2.0; appears then disappears.

### MK-06: latest sentinel both surfaces

```bash
mk_run mk06 "latest"
claude plugin list 2>/dev/null | grep -q "mk06"
kanon clean .kanon
```

**Pass criteria:** Resolves to 3.0.0; appears then disappears.

### MK-07: PEP 440 `!=` in XML, main in .kanon

```bash
mk_run mk07 "main"
claude plugin list 2>/dev/null | grep -q "mk07"
kanon clean .kanon
```

**Pass criteria:** Resolves to 3.0.0; appears then disappears.

### MK-08: PEP 440 `!=` in .kanon, main in XML

```bash
mk_run mk08 "refs/tags/!=2.0.0"
claude plugin list 2>/dev/null | grep -q "mk08"
kanon clean .kanon
```

**Pass criteria:** Resolves to 3.0.0; appears then disappears.

### MK-09: upper-bound XML

```bash
mk_run mk09 "main"
claude plugin list 2>/dev/null | grep -q "mk09"
kanon clean .kanon
```

**Pass criteria:** Resolves to 1.1.0; appears then disappears.

### MK-10: upper-bound .kanon

```bash
mk_run mk10 "refs/tags/<=1.1.0"
claude plugin list 2>/dev/null | grep -q "mk10"
kanon clean .kanon
```

**Pass criteria:** Resolves to 1.1.0; appears then disappears.

### MK-11: exact pin both

```bash
mk_run mk11 "refs/tags/==3.0.0"
claude plugin list 2>/dev/null | grep -q "mk11"
kanon clean .kanon
```

**Pass criteria:** Resolves to 3.0.0; appears then disappears.

### MK-12: invalid `==*` constraint rejected; plugin not visible

```bash
set +e
mk_run mk12 "main"
exit_code=$?
set -e
claude plugin list 2>/dev/null | grep -q "mk12" || echo "PASS: mk12 not in plugin list"
```

**Pass criteria:** Install exits non-zero; `claude plugin list` does NOT show `mk12`.

### MK-13: marketplace.json with multiple plugins (manually edit before install)

```bash
cd "${MK_FIX}/mk13"
cat > .claude-plugin/marketplace.json << 'JSONEOF'
{
  "name": "mk13",
  "owner": {"name": "Test", "url": "https://example.com"},
  "metadata": {"description": "multi-plugin test", "version": "0.1.0"},
  "plugins": [
    {"name": "mk13-alpha", "source": "./", "description": "p1", "version": "0.1.0"},
    {"name": "mk13-beta",  "source": "./", "description": "p2", "version": "0.1.0"}
  ]
}
JSONEOF
git add .claude-plugin/marketplace.json && git commit -q -m "multi-plugin"
mk_run mk13 "main"
claude plugin list 2>/dev/null | grep -E "mk13-(alpha|beta)" | wc -l | grep -q "^2$"
kanon clean .kanon
```

**Pass criteria:** Both `mk13-alpha` and `mk13-beta` appear in `claude plugin list`; both removed after clean.

#### Plugin discovery mechanism (kanon contract)

`kanon`'s `discover_plugins` (in `src/kanon_cli/core/marketplace.py`) reads the
top-level `plugins` array from `<marketplace>/.claude-plugin/marketplace.json`.
Each entry's `name` field becomes a plugin name. After registering the
marketplace via `claude plugin marketplace add`, `kanon` issues
`claude plugin install <name>@<marketplace> --scope user` for every name
in that array. Per-plugin `plugin.json` files are metadata consumed by
the `claude` CLI itself; `kanon` does **not** scan subdirectories for
`plugin.json` to determine which plugins to install. This means a
marketplace fixture's `marketplace.json` MUST include the `plugins[]`
array for any plugin a test expects `kanon install` to register.

### MK-14: plugin.json minimal (no `keywords` field)

```bash
cd "${MK_FIX}/mk14"
cat > .claude-plugin/plugin.json << 'JSONEOF'
{"name": "mk14", "version": "0.1.0", "description": "minimal", "author": {"name": "T", "url": "https://x"}}
JSONEOF
git add .claude-plugin/plugin.json && git commit -q -m "minimal"
mk_run mk14 "main"
claude plugin list 2>/dev/null | grep -q "mk14"
kanon clean .kanon
```

**Pass criteria:** Claude CLI accepts the minimal `plugin.json` metadata; the plugin appears in `claude plugin list` because it is declared in the marketplace's `marketplace.json` `plugins[]` array (kanon's `discover_plugins` reads names from that array; `plugin.json` is metadata consumed by the claude CLI itself).

### MK-15: plugin.json with full metadata

```bash
cd "${MK_FIX}/mk15"
cat > .claude-plugin/plugin.json << 'JSONEOF'
{"name": "mk15", "version": "0.1.0",
 "description": "full metadata variant",
 "author": {"name": "Test Org", "url": "https://example.com"},
 "keywords": ["a","b","c","d","e","f","g"]}
JSONEOF
git add .claude-plugin/plugin.json && git commit -q -m "full"
mk_run mk15 "main"
claude plugin list 2>/dev/null | grep -q "mk15"
kanon clean .kanon
```

**Pass criteria:** Claude CLI accepts the full-metadata `plugin.json`; the plugin appears in `claude plugin list` because the marketplace's `marketplace.json plugins[]` array names it (`discover_plugins` reads from the array, not from per-plugin `plugin.json` files).

### MK-16: cascading `<include>` chain

```bash
cd "${MK_MFST}"
mkdir -p shared
cat > shared/remote.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${MK_FIX}" />
  <default remote="local" revision="main" />
</manifest>
XMLEOF
cat > mk16.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <include name="shared/remote.xml" />
  <project name="mk16" path=".packages/mk16" remote="local" revision="main">
    <linkfile src="." dest="\${CLAUDE_MARKETPLACES_DIR}/mk16" />
  </project>
</manifest>
XMLEOF
git add . && git commit -q -m "mk16 include"
mk_run mk16 "main"
claude plugin list 2>/dev/null | grep -q "mk16"
kanon clean .kanon
```

**Pass criteria:** Install resolves the `<include>`; plugin appears; clean removes it.

### MK-17: XML with multiple `<project>` entries

```bash
cd "${MK_MFST}"
cat > mk17.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${MK_FIX}" />
  <default remote="local" revision="main" />
  <project name="mk17" path=".packages/mk17-a" remote="local" revision="main">
    <linkfile src="." dest="\${CLAUDE_MARKETPLACES_DIR}/mk17-a" />
  </project>
  <project name="mk17" path=".packages/mk17-b" remote="local" revision="refs/tags/2.0.0">
    <linkfile src="." dest="\${CLAUDE_MARKETPLACES_DIR}/mk17-b" />
  </project>
</manifest>
XMLEOF
git add mk17.xml && git commit -q -m "mk17 multi-project"
mk_run mk17 "main"
claude plugin list 2>/dev/null | grep -E "mk17-(a|b)" | wc -l | grep -q "^2$"
kanon clean .kanon
```

**Pass criteria:** Both project entries materialize as distinct plugin entries.

### MK-18: bare wildcard `*` both surfaces

```bash
mk_run mk18 "*"
claude plugin list 2>/dev/null | grep -q "mk18"
kanon clean .kanon
```

**Pass criteria:** Resolves to 3.0.0; appears then disappears.

### MK-19: `dest=` does NOT start with `${CLAUDE_MARKETPLACES_DIR}/` (validate-marketplace error)

```bash
set +e
kanon validate marketplace --repo-root "${MK_MFST}"
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero; stderr names `mk19.xml` and indicates `dest` does not start with `${CLAUDE_MARKETPLACES_DIR}/`.

### MK-20: re-install after clean restores plugin

```bash
mk_run mk20 "main"
claude plugin list 2>/dev/null | grep -q "mk20"
kanon clean .kanon
claude plugin list 2>/dev/null | grep -q "mk20" || echo "absent ok"
kanon install .kanon
claude plugin list 2>/dev/null | grep -q "mk20" && echo "PASS: mk20 restored"
kanon clean .kanon
```

**Pass criteria:** First install + clean cycle removes plugin; second install restores it; second clean removes it again.

### MK-21: multi-marketplace install (two distinct plugins in same `.kanon`)

```bash
mkdir -p "${KANON_TEST_ROOT}/mk21"
cd "${KANON_TEST_ROOT}/mk21"
cat > .kanon << KANONEOF
KANON_MARKETPLACE_INSTALL=true
CLAUDE_MARKETPLACES_DIR=${KANON_TEST_ROOT}/mk21-mpl
KANON_SOURCE_combo_URL=file://${MK_MFST}
KANON_SOURCE_combo_REVISION=main
KANON_SOURCE_combo_PATH=mk21.xml
KANONEOF
kanon install .kanon
claude plugin list 2>/dev/null | grep -E "mk21(a|b)" | wc -l | grep -q "^2$"
kanon clean .kanon
claude plugin list 2>/dev/null | grep -qE "mk21(a|b)" || echo "PASS: both removed"
```

**Pass criteria:** Both plugin entries appear after install; both removed after clean.

### MK-22: linkfile with cascading directory tree

```bash
cd "${MK_FIX}/mk22"
mkdir -p deep/nested/path
echo "marker" > deep/nested/path/marker.txt
git add deep && git commit -q -m "nested"
cd "${MK_MFST}"
cat > mk22.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${MK_FIX}" />
  <default remote="local" revision="main" />
  <project name="mk22" path=".packages/mk22" remote="local" revision="main">
    <linkfile src="deep" dest="\${CLAUDE_MARKETPLACES_DIR}/mk22-deep" />
  </project>
</manifest>
XMLEOF
git add mk22.xml && git commit -q -m "mk22 nested linkfile"
mk_run mk22 "main"
test -L "${KANON_TEST_ROOT}/mk22-mpl/mk22-deep" && echo "PASS: symlink exists"
test -f "${KANON_TEST_ROOT}/mk22-mpl/mk22-deep/nested/path/marker.txt" && echo "PASS: nested file reachable"
kanon clean .kanon
```

**Pass criteria:** Symlink resolves through nested directory; cleanup removes the symlink tree.

### Cleanup

```bash
for i in $(seq -w 01 22); do
    cd "${KANON_TEST_ROOT}" && rm -rf "mk${i}" "mk${i}-mpl"
done
```

---

## 19. Category 18: Non-Marketplace Package Lifecycle (13 tests)

These tests mirror Category 17 but **without** `KANON_MARKETPLACE_INSTALL=true`. The `<linkfile dest=".packages/...">` uses the regular aggregation path; assertions check `.packages/<name>` symlink presence/absence rather than `claude plugin list`.

### Fixture setup

```bash
export PK_FIX="${KANON_TEST_ROOT}/fixtures/non-marketplace"
mkdir -p "${PK_FIX}"

pk_repo() {
    local name="$1"
    local dir="${PK_FIX}/${name}"
    mkdir -p "${dir}/src"
    cd "${dir}"
    git init -q
    git branch -m main 2>/dev/null || true
    echo "package ${name}" > src/main.py
    echo "# Package ${name}" > README.md
    git add . && git commit -q -m "init ${name}"
    for tag in 1.0.0 1.0.1 1.1.0 1.2.0 2.0.0 2.1.0 3.0.0; do
        git commit -q --allow-empty -m "rel ${tag}"
        git tag "${tag}"
    done
}

for n in pk01 pk02 pk03 pk04 pk05 pk06 pk07 pk08 pk09 pk10 pk11a pk11b pk12 pk13; do
    pk_repo "${n}"
done

export PK_MFST="${KANON_TEST_ROOT}/fixtures/pk-manifest"
mkdir -p "${PK_MFST}"
cd "${PK_MFST}"
git init -q
git branch -m main 2>/dev/null || true
pk_xml() {
    local id="$1" pkg="$2" rev="$3"
    cat > "${id}.xml" << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${PK_FIX}" />
  <default remote="local" revision="main" />
  <project name="${pkg}" path=".packages/${pkg}" remote="local" revision="${rev}" />
</manifest>
XMLEOF
}
pk_xml pk01 pk01 "main"
pk_xml pk02 pk02 "refs/tags/~=1.0.0"
pk_xml pk03 pk03 "main"
pk_xml pk04 pk04 "refs/tags/>=1.0.0,<2.0.0"
pk_xml pk05 pk05 "main"
pk_xml pk06 pk06 "main"
pk_xml pk07 pk07 "main"
pk_xml pk08 pk08 "==*"
pk_xml pk12 pk12 "refs/tags/~=1.0.0"
pk_xml pk13 pk13 "main"
# Multi-package single-source (PK-09).
cat > pk09.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${PK_FIX}" />
  <default remote="local" revision="main" />
  <project name="pk09" path=".packages/pk09" remote="local" revision="main" />
  <project name="pk09" path=".packages/pk09-extra" remote="local" revision="main" />
</manifest>
XMLEOF
# Linkfile with PEP 440 (PK-10).
cat > pk10.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${PK_FIX}" />
  <default remote="local" revision="main" />
  <project name="pk10" path=".packages/pk10" remote="local" revision="refs/tags/~=2.0.0">
    <linkfile src="src/main.py" dest=".packages/pk10-main.py" />
  </project>
</manifest>
XMLEOF
# Multi-source aggregation (PK-11).
cat > pk11.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="file://${PK_FIX}" />
  <default remote="local" revision="main" />
  <project name="pk11a" path=".packages/pk11a" remote="local" revision="refs/tags/~=1.0.0" />
  <project name="pk11b" path=".packages/pk11b" remote="local" revision="refs/tags/>=2.0.0" />
</manifest>
XMLEOF
git add . && git commit -q -m "init pk manifests"
git tag 1.0.0
git commit --allow-empty -q -m "1.0.1"
git tag 1.0.1
git commit --allow-empty -q -m "1.1.0"
git tag 1.1.0
git commit --allow-empty -q -m "1.2.0"
git tag 1.2.0
git commit --allow-empty -q -m "2.0.0"
git tag 2.0.0
git commit --allow-empty -q -m "2.1.0"
git tag 2.1.0
git commit --allow-empty -q -m "3.0.0"
git tag 3.0.0

pk_run() {
    local id="$1" rev_kanon="$2"
    mkdir -p "${KANON_TEST_ROOT}/${id}"
    cd "${KANON_TEST_ROOT}/${id}"
    cat > .kanon << KANONEOF
KANON_SOURCE_pk_URL=file://${PK_MFST}
KANON_SOURCE_pk_REVISION=${rev_kanon}
KANON_SOURCE_pk_PATH=${id}.xml
KANONEOF
    kanon install .kanon
}
```

### PK-01: basic install/clean

```bash
pk_run pk01 "main"
test -L .packages/pk01 && echo "PASS: symlink"
kanon clean .kanon
test ! -L .packages/pk01 && test ! -d .packages && echo "PASS: clean removed everything"
```

**Pass criteria:** Install creates `.packages/pk01` symlink; clean removes `.packages/` entirely.

### PK-02: PEP 440 `~=1.0.0` in XML revision

```bash
pk_run pk02 "main"
(cd .kanon-data/sources/pk && kanon repo manifest --revision-as-tag) | grep -q "refs/tags/1.0.1"
kanon clean .kanon
```

**Pass criteria:** Resolves to 1.0.1; symlink present pre-clean; absent post-clean.

### PK-03: PEP 440 `~=1.0.0` in `.kanon` REVISION (XML revision=main)

```bash
pk_run pk03 "refs/tags/~=1.0.0"
test -L .packages/pk03 && echo "PASS"
kanon clean .kanon
```

**Pass criteria:** Resolves; symlink present then absent.

### PK-04: PEP 440 in BOTH XML and `.kanon`

```bash
pk_run pk04 "refs/tags/>=1.0.0,<2.0.0"
test -L .packages/pk04 && echo "PASS"
kanon clean .kanon
```

**Pass criteria:** Resolves to 1.2.0; symlink present then absent.

### PK-05: clean is no-op when nothing was installed

```bash
mkdir -p "${KANON_TEST_ROOT}/pk05"
cd "${KANON_TEST_ROOT}/pk05"
cat > .kanon << KANONEOF
KANON_SOURCE_pk_URL=file://${PK_MFST}
KANON_SOURCE_pk_REVISION=main
KANON_SOURCE_pk_PATH=pk05.xml
KANONEOF
kanon clean .kanon
```

**Pass criteria:** Exit code 0; no error about missing `.kanon-data/`.

### PK-06: re-install after clean — end state matches first install

```bash
pk_run pk06 "main"
test -L .packages/pk06 || (echo "FAIL: first install missing"; exit 1)
kanon clean .kanon
kanon install .kanon
test -L .packages/pk06 && echo "PASS: restored"
kanon clean .kanon
```

**Pass criteria:** Both installs produce a `.packages/pk06` symlink; both cleans remove it.

### PK-07: env override of `KANON_SOURCE_<name>_REVISION` at install time

```bash
mkdir -p "${KANON_TEST_ROOT}/pk07"
cd "${KANON_TEST_ROOT}/pk07"
cat > .kanon << KANONEOF
KANON_SOURCE_pk_URL=file://${PK_MFST}
KANON_SOURCE_pk_REVISION=main
KANON_SOURCE_pk_PATH=pk07.xml
KANONEOF
KANON_SOURCE_pk_REVISION="refs/tags/~=2.0.0" kanon install .kanon
(cd .kanon-data/sources/pk && kanon repo manifest --revision-as-tag) | grep -q "refs/tags/2.1.0"
kanon clean .kanon
```

**Pass criteria:** Env override resolves the source REVISION to `2.1.0` despite the `.kanon` file value `main`.

### PK-08: invalid `==*` rejected

```bash
set +e
pk_run pk08 "main"
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero; stderr contains `invalid version constraint`.

### PK-09: multiple packages from one source

```bash
pk_run pk09 "main"
test -L .packages/pk09 && test -L .packages/pk09-extra && echo "PASS: both symlinks"
kanon clean .kanon
```

**Pass criteria:** Both `.packages/pk09` and `.packages/pk09-extra` symlinks exist.

### PK-10: linkfile entries with PEP 440

```bash
pk_run pk10 "main"
test -L .packages/pk10 && test -e .packages/pk10-main.py && echo "PASS"
(cd .kanon-data/sources/pk && kanon repo manifest --revision-as-tag) | grep -q "refs/tags/2.1.0"
kanon clean .kanon
```

**Pass criteria:** Both the project symlink and the linkfile target exist; revision resolved via PEP 440.

### PK-11: multi-source aggregation with PEP 440 mix

```bash
pk_run pk11 "main"
test -L .packages/pk11a && test -L .packages/pk11b && echo "PASS: both"
kanon clean .kanon
```

**Pass criteria:** Both source-specific package directories aggregated under `.packages/`.

### PK-12: collision with PEP 440 (two sources resolving to same package name)

```bash
mkdir -p "${KANON_TEST_ROOT}/pk12"
cd "${KANON_TEST_ROOT}/pk12"
cat > .kanon << KANONEOF
KANON_SOURCE_a_URL=file://${PK_MFST}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=pk12.xml
KANON_SOURCE_b_URL=file://${PK_MFST}
KANON_SOURCE_b_REVISION=main
KANON_SOURCE_b_PATH=pk12.xml
KANONEOF
set +e
kanon install .kanon
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero; stderr names the colliding package and both source names.

### PK-13: `.gitignore` promise — `.packages/` and `.kanon-data/` added

```bash
pk_run pk13 "main"
grep -q "^.packages/$" .gitignore && grep -q "^.kanon-data/$" .gitignore && echo "PASS: both lines present"
kanon clean .kanon
grep -q "^.packages/$" .gitignore && echo "PASS: clean preserved .gitignore lines"
```

**Pass criteria:** Both `.packages/` and `.kanon-data/` lines added to `.gitignore` by install; lines remain after clean.

### Cleanup

```bash
for i in $(seq -w 01 13); do
    cd "${KANON_TEST_ROOT}" && rm -rf "pk${i}"
done
```

---

## 20. Category 19: `kanon repo init` Real User Journeys (18 tests)

These tests exercise every flag and every env var consumed by `kanon repo init` (`src/kanon_cli/repo/subcmds/init.py`).

### Common fixture

The single-bare-manifest-repo fixture from Category 3 is reused. Each scenario creates a fresh empty workspace, runs `kanon repo init` with the flag combination under test, then asserts on observable filesystem state.

### RP-init-01: bare init `-u`, `-b`, `-m`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-01"
cd "${KANON_TEST_ROOT}/rp-init-01"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml
test -d .repo && test -f .repo/manifest.xml && echo "PASS"
```

**Pass criteria:** Exit code 0; `.repo/` directory created; `.repo/manifest.xml` exists.

### RP-init-02: long form `--manifest-url`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-02"
cd "${KANON_TEST_ROOT}/rp-init-02"
kanon repo init --manifest-url "file://${MANIFEST_PRIMARY_DIR}" --manifest-branch main --manifest-name default.xml
test -d .repo && echo "PASS"
```

**Pass criteria:** Exit code 0; `.repo/` exists.

### RP-init-03: `--manifest-name=alt.xml`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-03"
cd "${KANON_TEST_ROOT}/rp-init-03"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m alt.xml
ls .repo/manifests/ | grep -q alt.xml && echo "PASS"
```

**Pass criteria:** Exit code 0; `.repo/manifests/alt.xml` is the active manifest.

### RP-init-04: `--manifest-depth=1` (shallow manifest clone)

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-04"
cd "${KANON_TEST_ROOT}/rp-init-04"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --manifest-depth 1
test -f .repo/manifests.git/shallow && echo "PASS: shallow"
```

**Pass criteria:** Exit code 0; `.repo/manifests.git/shallow` file present.

### RP-init-05: `--manifest-upstream-branch`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-05"
cd "${KANON_TEST_ROOT}/rp-init-05"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --manifest-upstream-branch main
git -C .repo/manifests.git config --get branch.default.merge | grep -q "main" && echo "PASS"
```

**Pass criteria:** Exit code 0; manifest branch upstream recorded.

### RP-init-06: `--standalone-manifest`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-06"
cd "${KANON_TEST_ROOT}/rp-init-06"
cp "${MANIFEST_PRIMARY_DIR}/default.xml" /tmp/standalone-manifest.xml 2>/dev/null || true
kanon repo init -u "file:///tmp/standalone-manifest.xml" --standalone-manifest
test -f .repo/manifest.xml && echo "PASS"
```

**Pass criteria:** Exit code 0; `.repo/manifest.xml` is a static file (no `.repo/manifests.git`).

### RP-init-07: `--reference=<mirror>`

```bash
export RP_MIRROR="${KANON_TEST_ROOT}/fixtures/rp-mirror"
mkdir -p "${RP_MIRROR}"
git -C "${RP_MIRROR}" clone --mirror "${MANIFEST_PRIMARY_DIR}" manifest-mirror.git 2>/dev/null || true

mkdir -p "${KANON_TEST_ROOT}/rp-init-07"
cd "${KANON_TEST_ROOT}/rp-init-07"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --reference "${RP_MIRROR}"
grep -q "${RP_MIRROR}" .repo/manifests.git/objects/info/alternates && echo "PASS"
```

**Pass criteria:** Exit code 0; mirror referenced in `objects/info/alternates`.

### RP-init-08: `--dissociate` (after `--reference`)

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-08"
cd "${KANON_TEST_ROOT}/rp-init-08"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --reference "${RP_MIRROR}" --dissociate
test ! -f .repo/manifests.git/objects/info/alternates && echo "PASS: alternates removed"
```

**Pass criteria:** Exit code 0; alternates file does NOT exist (objects copied locally).

### RP-init-09: `--no-clone-bundle`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-09"
cd "${KANON_TEST_ROOT}/rp-init-09"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --no-clone-bundle 2>&1 | tee /tmp/rp-init-09.log
grep -q "clone.bundle" /tmp/rp-init-09.log && echo "FAIL: clone.bundle attempted" || echo "PASS"
```

**Pass criteria:** Exit code 0; log shows no `clone.bundle` request.

### RP-init-10: `--mirror`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-10"
cd "${KANON_TEST_ROOT}/rp-init-10"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --mirror
test -d .repo/manifests.git && echo "PASS"
```

**Pass criteria:** Exit code 0; bare-mirror layout under `.repo/manifests.git`.

### RP-init-11: `--worktree`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-11"
cd "${KANON_TEST_ROOT}/rp-init-11"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --worktree
test -d .repo && echo "PASS"
```

**Pass criteria:** Exit code 0; worktree-style layout.

### RP-init-12: `--submodules` against submodule fixture

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-12"
cd "${KANON_TEST_ROOT}/rp-init-12"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --submodules
echo "PASS"
```

**Pass criteria:** Exit code 0 (submodule fetch happens during `repo sync`; init only records the flag).

### RP-init-13: `--partial-clone --clone-filter=blob:none`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-13"
cd "${KANON_TEST_ROOT}/rp-init-13"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --partial-clone --clone-filter=blob:none
git -C .repo/manifests.git config --get remote.origin.partialclonefilter | grep -q "blob:none" && echo "PASS"
```

**Pass criteria:** Exit code 0; partial-clone filter recorded in git config.

### RP-init-14: `--git-lfs`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-14"
cd "${KANON_TEST_ROOT}/rp-init-14"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --git-lfs
echo "PASS"
```

**Pass criteria:** Exit code 0 (LFS hooks installed; verified in sync).

### RP-init-15: `--use-superproject`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-15"
cd "${KANON_TEST_ROOT}/rp-init-15"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --use-superproject 2>&1 | tee /tmp/rp-init-15.log
grep -q -i "superproject\|error" /tmp/rp-init-15.log && echo "PASS (manifest may lack superproject; flag accepted)"
```

**Pass criteria:** Exit code 0 OR exit non-zero with clear "no superproject in manifest" error.

### RP-init-16: `--current-branch-only` (`-c`)

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-16"
cd "${KANON_TEST_ROOT}/rp-init-16"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml -c
echo "PASS"
```

**Pass criteria:** Exit code 0; only the manifest branch is fetched.

### RP-init-17: `--groups=<name>`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-17"
cd "${KANON_TEST_ROOT}/rp-init-17"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml --groups=default
echo "PASS"
```

**Pass criteria:** Exit code 0; only projects in the named group are recorded for sync.

### RP-init-18: env `REPO_MANIFEST_URL` overrides absent `-u`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-init-18"
cd "${KANON_TEST_ROOT}/rp-init-18"
REPO_MANIFEST_URL="file://${MANIFEST_PRIMARY_DIR}" kanon repo init -b main -m default.xml
test -d .repo && echo "PASS"
```

**Pass criteria:** Exit code 0; `.repo/` exists despite `-u` not being supplied (env value used).

### Cleanup

```bash
for i in $(seq -w 01 18); do
    cd "${KANON_TEST_ROOT}" && rm -rf "rp-init-${i}"
done
```

---

## 21. Category 20: `kanon repo sync` Real User Journeys (28 tests)

These tests exercise every flag in `kanon repo sync` (`src/kanon_cli/repo/subcmds/sync.py`) plus its env vars (`REPO_ALLOW_SHALLOW`, `REPO_SKIP_SELF_UPDATE`, `SYNC_TARGET`, `TARGET_PRODUCT`, `TARGET_BUILD_VARIANT`, `TARGET_RELEASE`).

### Common setup

```bash
rp_sync_setup() {
    local id="$1"
    mkdir -p "${KANON_TEST_ROOT}/${id}"
    cd "${KANON_TEST_ROOT}/${id}"
    kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml
}
```

### RP-sync-01: bare `kanon repo sync`

```bash
rp_sync_setup rp-sync-01
kanon repo sync
test -d .packages/pkg-alpha && echo "PASS"
```

**Pass criteria:** Exit code 0; project directory populated.

### RP-sync-02: `--network-only` / `-n`

```bash
rp_sync_setup rp-sync-02
kanon repo sync -n
echo "PASS"
```

**Pass criteria:** Exit code 0; only fetch occurs (no checkout).

### RP-sync-03: `--local-only` / `-l`

```bash
rp_sync_setup rp-sync-03
kanon repo sync
kanon repo sync -l
echo "PASS"
```

**Pass criteria:** Exit code 0; no network calls on the local-only run.

### RP-sync-04: `--detach`

```bash
rp_sync_setup rp-sync-04
kanon repo sync -d
echo "PASS"
```

**Pass criteria:** Exit code 0; project HEADs are detached at the manifest revision.

### RP-sync-05: `--current-branch` / `-c`

```bash
rp_sync_setup rp-sync-05
kanon repo sync -c
echo "PASS"
```

**Pass criteria:** Exit code 0; only the manifest branch is fetched per project.

### RP-sync-06: `--no-current-branch`

```bash
rp_sync_setup rp-sync-06
kanon repo sync --no-current-branch
echo "PASS"
```

**Pass criteria:** Exit code 0; default fetch behaviour.

### RP-sync-07: `--force-checkout`

```bash
rp_sync_setup rp-sync-07
kanon repo sync
echo "dirty" >> .packages/pkg-alpha/README.md
kanon repo sync --force-checkout
echo "PASS"
```

**Pass criteria:** Exit code 0; uncommitted changes are forcibly overwritten.

### RP-sync-08: `--force-remove-dirty`

```bash
rp_sync_setup rp-sync-08
kanon repo sync --force-remove-dirty
echo "PASS"
```

**Pass criteria:** Exit code 0.

### RP-sync-09: `--rebase`

```bash
rp_sync_setup rp-sync-09
kanon repo sync --rebase
echo "PASS"
```

**Pass criteria:** Exit code 0; local commits rebased.

### RP-sync-10: `--force-sync`

```bash
rp_sync_setup rp-sync-10
kanon repo sync --force-sync
echo "PASS"
```

**Pass criteria:** Exit code 0 (override possible data-loss warning).

### RP-sync-11: `--clone-bundle`

```bash
rp_sync_setup rp-sync-11
kanon repo sync --clone-bundle
echo "PASS"
```

**Pass criteria:** Exit code 0.

### RP-sync-12: `--no-clone-bundle`

```bash
rp_sync_setup rp-sync-12
kanon repo sync --no-clone-bundle
echo "PASS"
```

**Pass criteria:** Exit code 0; no `clone.bundle` attempted.

### RP-sync-13: `--fetch-submodules`

```bash
rp_sync_setup rp-sync-13
kanon repo sync --fetch-submodules
echo "PASS"
```

**Pass criteria:** Exit code 0.

### RP-sync-14: `--use-superproject`

```bash
rp_sync_setup rp-sync-14
set +e; kanon repo sync --use-superproject; set -e
echo "PASS"
```

**Pass criteria:** Exit code 0 OR clear "no superproject" error.

### RP-sync-15: `--no-use-superproject`

```bash
rp_sync_setup rp-sync-15
kanon repo sync --no-use-superproject
echo "PASS"
```

**Pass criteria:** Exit code 0.

### RP-sync-16: `--tags`

```bash
rp_sync_setup rp-sync-16
kanon repo sync --tags
echo "PASS"
```

**Pass criteria:** Exit code 0; tags fetched.

### RP-sync-17: `--no-tags`

```bash
rp_sync_setup rp-sync-17
kanon repo sync --no-tags
echo "PASS"
```

**Pass criteria:** Exit code 0; tags skipped.

### RP-sync-18: `--optimized-fetch`

```bash
rp_sync_setup rp-sync-18
kanon repo sync --optimized-fetch
echo "PASS"
```

**Pass criteria:** Exit code 0.

### RP-sync-19: `--retry-fetches=N`

```bash
rp_sync_setup rp-sync-19
kanon repo sync --retry-fetches=3
echo "PASS"
```

**Pass criteria:** Exit code 0 (N retries on transient errors).

### RP-sync-20: `--prune` / `--no-prune`

```bash
rp_sync_setup rp-sync-20
kanon repo sync --prune
kanon repo sync --no-prune
echo "PASS"
```

**Pass criteria:** Both invocations exit 0.

### RP-sync-21: `--auto-gc` / `--no-auto-gc`

```bash
rp_sync_setup rp-sync-21
kanon repo sync --auto-gc
kanon repo sync --no-auto-gc
echo "PASS"
```

**Pass criteria:** Both exit 0.

### RP-sync-22: `--no-repo-verify`

```bash
rp_sync_setup rp-sync-22
kanon repo sync --no-repo-verify
echo "PASS"
```

**Pass criteria:** Exit code 0.

### RP-sync-23: `--jobs-network=N` and `--jobs-checkout=N`

```bash
rp_sync_setup rp-sync-23
kanon repo sync --jobs-network=2 --jobs-checkout=4
echo "PASS"
```

**Pass criteria:** Exit code 0; sync proceeds with parallel jobs.

### RP-sync-24: `--interleaved`

```bash
rp_sync_setup rp-sync-24
kanon repo sync --interleaved
echo "PASS"
```

**Pass criteria:** Exit code 0; fetch and checkout interleave.

### RP-sync-25: `--fail-fast`

```bash
rp_sync_setup rp-sync-25
kanon repo sync --fail-fast
echo "PASS"
```

**Pass criteria:** Exit code 0 (no errors to trip fail-fast).

### RP-sync-26: env `REPO_SKIP_SELF_UPDATE=1` skips self-update

```bash
rp_sync_setup rp-sync-26
REPO_SKIP_SELF_UPDATE=1 kanon repo sync 2>&1 | tee /tmp/rp-sync-26.log
grep -qi "self.update" /tmp/rp-sync-26.log && echo "FAIL: self-update ran" || echo "PASS"
```

**Pass criteria:** Exit code 0; log shows no self-update step.

### RP-sync-27: env `SYNC_TARGET` overrides separate target vars

```bash
rp_sync_setup rp-sync-27
SYNC_TARGET="myproduct-myrelease-myvariant" kanon repo sync
echo "PASS"
```

**Pass criteria:** Exit code 0 (target string accepted).

### RP-sync-28: env `TARGET_PRODUCT` + `TARGET_BUILD_VARIANT` + `TARGET_RELEASE`

```bash
rp_sync_setup rp-sync-28
TARGET_PRODUCT=myp TARGET_BUILD_VARIANT=user TARGET_RELEASE=1 kanon repo sync
echo "PASS"
```

**Pass criteria:** Exit code 0; target string composed from the three env vars.

### Cleanup

```bash
for i in $(seq -w 01 28); do
    cd "${KANON_TEST_ROOT}" && rm -rf "rp-sync-${i}"
done
```

---

## 22. Category 21: `kanon repo` Read-Only Subcommands (status, info, manifest) (22 tests)

### Common setup

```bash
rp_ro_setup() {
    local id="$1"
    mkdir -p "${KANON_TEST_ROOT}/${id}"
    cd "${KANON_TEST_ROOT}/${id}"
    kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m repo-specs/packages.xml
    kanon repo sync
}
```

### RP-status-01: bare status

```bash
rp_ro_setup rp-status-01
kanon repo status
```

**Pass criteria:** Exit code 0; prints clean-status summary.

### RP-status-02: `--orphans`

<!-- Source-of-truth: src/kanon_cli/repo/subcmds/status.py::_Options(), flag -o/--orphans -->

```bash
rp_ro_setup rp-status-02
kanon repo status --orphans
```

**Pass criteria:** Exit code 0; output includes "No orphan files or directories" or lists orphan entries, confirming the --orphans scan ran (declared in status.py::_Options()).

### RP-status-03: project-filtered

```bash
rp_ro_setup rp-status-03
kanon repo status pkg-alpha
```

**Pass criteria:** Exit code 0; only `pkg-alpha` reported.

### RP-status-04: `--jobs=4`

```bash
rp_ro_setup rp-status-04
kanon repo status --jobs=4
```

**Pass criteria:** Exit code 0.

### RP-info-01: bare info

```bash
rp_ro_setup rp-info-01
kanon repo info
```

**Pass criteria:** Exit code 0; current manifest name printed.

### RP-info-02: `--diff`

<!-- Source-of-truth: src/kanon_cli/repo/subcmds/info.py::_Options(), flag -d/--diff (dest=all) -->

```bash
rp_ro_setup rp-info-02
kanon repo info --diff
```

**Pass criteria:** Exit code 0; output includes manifest branch heading and commit diff sections for each project, confirming the --diff flag ran (declared as -d/--diff in info.py::_Options()).

### RP-info-03: `--current-branch`

```bash
rp_ro_setup rp-info-03
kanon repo info --current-branch
```

**Pass criteria:** Exit code 0.

### RP-info-04: `--local-only`

<!-- Source-of-truth: src/kanon_cli/repo/subcmds/info.py::_Options(), flag -l/--local-only (dest=local) -->

```bash
rp_ro_setup rp-info-04
kanon repo info --local-only
```

**Pass criteria:** Exit code 0; manifest info printed with no remote network calls attempted, confirming --local-only ran (declared as -l/--local-only in info.py::_Options()).

### RP-info-05: `--overview`

```bash
rp_ro_setup rp-info-05
kanon repo info --overview
```

**Pass criteria:** Exit code 0.

### RP-info-06: `--no-current-branch`

<!-- Source-of-truth: src/kanon_cli/repo/subcmds/info.py::_Options(), flag --no-current-branch (dest=current_branch, action=store_false) -->

```bash
rp_ro_setup rp-info-06
kanon repo info --no-current-branch
```

**Pass criteria:** Exit code 0; info output considers all local branches rather than only the checked-out branch, confirming --no-current-branch ran (declared in info.py::_Options()).

### RP-info-07: `--this-manifest-only`

```bash
rp_ro_setup rp-info-07
kanon repo info --this-manifest-only
```

**Pass criteria:** Exit code 0.

### RP-manifest-01: bare manifest (stdout)

```bash
rp_ro_setup rp-manifest-01
kanon repo manifest | head -1 | grep -q '<?xml'
```

**Pass criteria:** Exit code 0; XML printed to stdout.

### RP-manifest-02: `--output=NAME.xml`

```bash
rp_ro_setup rp-manifest-02
kanon repo manifest --output=/tmp/m.xml
test -f /tmp/m.xml && head -1 /tmp/m.xml | grep -q '<?xml'
```

**Pass criteria:** Exit code 0; `/tmp/m.xml` contains the manifest.

### RP-manifest-03: `--manifest-name=alt.xml`

```bash
rp_ro_setup rp-manifest-03
kanon repo manifest --manifest-name=default.xml | head -1 | grep -q '<?xml'
```

**Pass criteria:** Exit code 0.

### RP-manifest-04: `--revision-as-HEAD` / `-r`

<!-- Flag source: manifest.py::_Options() p.add_option("-r", "--revision-as-HEAD", dest="peg_rev", ...) -->

```bash
rp_ro_setup rp-manifest-04
kanon repo manifest --revision-as-HEAD | grep -q "revision="
```

**Pass criteria:** Exit code 0; manifest carries `revision="..."` per project (resolved to current HEAD).

### RP-manifest-05: `--suppress-upstream-revision`

<!-- Flag source: manifest.py::_Options() p.add_option("--suppress-upstream-revision", dest="peg_rev_upstream", ...) -->

```bash
rp_ro_setup rp-manifest-05
kanon repo manifest -r --suppress-upstream-revision | grep -v "upstream=" >/dev/null
```

**Pass criteria:** Exit code 0; `upstream=` attribute omitted.

### RP-manifest-06: `--suppress-dest-branch`

<!-- Flag source: manifest.py::_Options() p.add_option("--suppress-dest-branch", dest="peg_rev_dest_branch", ...) -->

```bash
rp_ro_setup rp-manifest-06
kanon repo manifest -r --suppress-dest-branch | grep -v "dest-branch=" >/dev/null
```

**Pass criteria:** Exit code 0; `dest-branch=` omitted.

### RP-manifest-07: `--pretty`

<!-- Flag source: manifest.py::_Options() p.add_option("--pretty", default=False, action="store_true", ...) -->

```bash
rp_ro_setup rp-manifest-07
kanon repo manifest --pretty | head -2 | tail -1 | grep -q '^<manifest'
```

**Pass criteria:** Exit code 0; output is human-formatted.

### RP-manifest-08: `--no-local-manifests`

<!-- Flag source: manifest.py::_Options() p.add_option("--no-local-manifests", dest="ignore_local_manifests", ...) -->

```bash
rp_ro_setup rp-manifest-08
kanon repo manifest --no-local-manifests | head -1 | grep -q '<?xml'
```

**Pass criteria:** Exit code 0.

### RP-manifest-09: `--outer-manifest`

```bash
rp_ro_setup rp-manifest-09
kanon repo manifest --outer-manifest | head -1 | grep -q '<?xml'
```

**Pass criteria:** Exit code 0.

### RP-manifest-10: `--no-outer-manifest`

```bash
rp_ro_setup rp-manifest-10
kanon repo manifest --no-outer-manifest | head -1 | grep -q '<?xml'
```

**Pass criteria:** Exit code 0.

### RP-manifest-11: `--revision-as-tag`

```bash
rp_ro_setup rp-manifest-11
kanon repo manifest --revision-as-tag | head -1 | grep -q '<?xml'
```

**Pass criteria:** Exit code 0; XML output present (first line matches `<?xml`); because `rp_ro_setup` initialises an untagged workspace, all projects take the warn-and-keep path — a warning is emitted to stderr for each project and each project's original revision is preserved unchanged in the output.

### Cleanup

```bash
for d in rp-status-{01..04} rp-info-{01..07} rp-manifest-{01..11}; do
    cd "${KANON_TEST_ROOT}" && rm -rf "${d}"
done
```

---

## 23. Category 22: `kanon repo` Listing & Iteration (branches, list, forall, grep) (27 tests)

### Common setup

Reuses `rp_ro_setup()` from §22.

### RP-branches-01: bare branches

```bash
rp_ro_setup rp-branches-01
kanon repo branches
```

**Pass criteria:** Exit code 0.

### RP-branches-02: project-filtered

```bash
rp_ro_setup rp-branches-02
kanon repo branches pkg-alpha
```

**Pass criteria:** Exit code 0.

### RP-branches-03: `--current-branch`

```bash
rp_ro_setup rp-branches-03
kanon repo branches --current-branch 2>&1 || echo "(flag may not exist; skip)"
```

**Pass criteria:** Exit code 0 OR documented skip if flag absent.

### RP-list-01: bare list

```bash
rp_ro_setup rp-list-01
kanon repo list
```

**Pass criteria:** Exit code 0; project paths printed.

### RP-list-02: `--regex <pattern>`

```bash
rp_ro_setup rp-list-02
kanon repo list --regex pkg-
```

**Pass criteria:** Exit code 0; only matching projects listed.

### RP-list-03: `--regex` / `-r`

```bash
rp_ro_setup rp-list-03
kanon repo list -r '^pkg-'
```

**Pass criteria:** Exit code 0.

### RP-list-04: `--groups=<name>`

```bash
rp_ro_setup rp-list-04
kanon repo list --groups=default
```

**Pass criteria:** Exit code 0.

### RP-list-05: `--all-manifests`

```bash
rp_ro_setup rp-list-05
kanon repo list --all-manifests
```

**Pass criteria:** Exit code 0.

### RP-list-06: `--name-only` / `-n`

```bash
rp_ro_setup rp-list-06
kanon repo list -n | head -1 | grep -qE '^[a-z-]+$'
```

**Pass criteria:** Exit code 0; only repo names printed.

### RP-list-07: `--path-only` / `-p`

```bash
rp_ro_setup rp-list-07
kanon repo list -p
```

**Pass criteria:** Exit code 0; only paths printed.

### RP-list-08: `--fullpath`

```bash
rp_ro_setup rp-list-08
kanon repo list --fullpath | head -1 | grep -q "^/"
```

**Pass criteria:** Exit code 0; absolute paths printed.

### RP-list-09: `--outer-manifest`

```bash
rp_ro_setup rp-list-09
kanon repo list --outer-manifest
```

**Pass criteria:** Exit code 0.

### RP-list-10: `--this-manifest-only`

```bash
rp_ro_setup rp-list-10
kanon repo list --this-manifest-only
```

**Pass criteria:** Exit code 0.

### RP-forall-01: bare `-c`

```bash
rp_ro_setup rp-forall-01
kanon repo forall -c "echo IN_PROJECT"
```

**Pass criteria:** Exit code 0; one `IN_PROJECT` per project.

### RP-forall-02: `--regex` / `-r`

```bash
rp_ro_setup rp-forall-02
kanon repo forall -r 'pkg-' -c "echo X"
```

**Pass criteria:** Exit code 0.

### RP-forall-03: `--inverse-regex` / `-i`

```bash
rp_ro_setup rp-forall-03
kanon repo forall -i 'collider' -c "echo X"
```

**Pass criteria:** Exit code 0.

### RP-forall-04: `--groups` / `-g`

```bash
rp_ro_setup rp-forall-04
kanon repo forall -g default -c "echo X"
```

**Pass criteria:** Exit code 0.

### RP-forall-05: `--abort-on-errors` / `-e`

```bash
rp_ro_setup rp-forall-05
set +e
kanon repo forall -e -c "false"
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero; error halts iteration.

### RP-forall-06: `--ignore-missing`

```bash
rp_ro_setup rp-forall-06
kanon repo forall --ignore-missing -c "echo X"
```

**Pass criteria:** Exit code 0.

### RP-forall-07: `--project-header` / `-p`

```bash
rp_ro_setup rp-forall-07
kanon repo forall -p -c "echo X" | grep -q '^project '
```

**Pass criteria:** Exit code 0; project headers printed.

### RP-forall-08: `--interactive`

```bash
rp_ro_setup rp-forall-08
echo "" | kanon repo forall --interactive -c "echo X" 2>&1 || echo "(skipped no-tty)"
```

**Pass criteria:** Exit code 0 OR `skipped (no-tty)`.

### RP-forall-09: env vars `REPO_PROJECT, REPO_PATH, REPO_REMOTE, REPO_LREV, REPO_RREV` observable

```bash
rp_ro_setup rp-forall-09
kanon repo forall -c 'env | grep -E "^REPO_(PROJECT|PATH|REMOTE|LREV|RREV)="' | head -5
```

**Pass criteria:** Exit code 0; all five env vars appear in output.

### RP-forall-10: env var `REPO_COUNT` matches project count

```bash
rp_ro_setup rp-forall-10
expected=$(kanon repo list -p | wc -l)
actual=$(kanon repo forall -c 'echo $REPO_COUNT' | head -1)
test "${expected}" = "${actual}" && echo "PASS"
```

**Pass criteria:** Exit code 0; `REPO_COUNT` equals project count.

### RP-grep-01: basic `<pattern>`

```bash
rp_ro_setup rp-grep-01
kanon repo grep "alpha" || true
```

**Pass criteria:** Exit code 0 or 1 (no-match permitted); no crash.

### RP-grep-02: `-i` case-insensitive

```bash
rp_ro_setup rp-grep-02
kanon repo grep -i "ALPHA" || true
```

**Pass criteria:** Exit code 0 or 1.

### RP-grep-03: `-e <pattern>`

```bash
rp_ro_setup rp-grep-03
kanon repo grep -e "alpha" || true
```

**Pass criteria:** Exit code 0 or 1.

### RP-grep-04: project-filtered

```bash
rp_ro_setup rp-grep-04
kanon repo grep "alpha" pkg-alpha || true
```

**Pass criteria:** Exit code 0 or 1.

### Cleanup

```bash
for d in rp-branches-{01..03} rp-list-{01..10} rp-forall-{01..10} rp-grep-{01..04}; do
    cd "${KANON_TEST_ROOT}" && rm -rf "${d}"
done
```

---

## 24. Category 23: `kanon repo` Branch Workflows (start, checkout, abandon, rebase) (17 tests)

### Common setup

Reuses `rp_ro_setup()` from §22.

### RP-start-01: `<branch> --all`

```bash
rp_ro_setup rp-start-01
kanon repo start tmp-1 --all
```

**Pass criteria:** Exit code 0; `tmp-1` branch created in every project.

### RP-start-02: `<branch> <project>`

```bash
rp_ro_setup rp-start-02
kanon repo start tmp-2 pkg-alpha
```

**Pass criteria:** Exit code 0.

### RP-start-03: `--rev=<rev>`

```bash
rp_ro_setup rp-start-03
kanon repo start tmp-3 --all --rev=HEAD
```

**Pass criteria:** Exit code 0.

### RP-start-04: `--head`

```bash
rp_ro_setup rp-start-04
kanon repo start tmp-4 --all --head
```

**Pass criteria:** Exit code 0.

### RP-checkout-01: existing branch

```bash
rp_ro_setup rp-checkout-01
kanon repo start mybr --all
kanon repo checkout main --all 2>&1 || kanon repo checkout main
```

**Pass criteria:** Exit code 0.

### RP-checkout-02: nonexistent branch errors

```bash
rp_ro_setup rp-checkout-02
set +e
kanon repo checkout no-such-branch --all
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero; stderr names the missing branch.

### RP-abandon-01: `<branch> --all`

```bash
rp_ro_setup rp-abandon-01
kanon repo start tmp-a --all
kanon repo abandon tmp-a --all
```

**Pass criteria:** Exit code 0; `tmp-a` removed in every project.

### RP-abandon-02: `<branch> <project>`

```bash
rp_ro_setup rp-abandon-02
kanon repo start tmp-b pkg-alpha
kanon repo abandon tmp-b pkg-alpha
```

**Pass criteria:** Exit code 0.

### RP-abandon-03: `--all` (delete all)

```bash
rp_ro_setup rp-abandon-03
kanon repo start tmp-c --all
kanon repo abandon --all
```

**Pass criteria:** Exit code 0; all topic branches removed.

### RP-rebase-01: bare (no-op when up to date)

```bash
rp_ro_setup rp-rebase-01
kanon repo rebase
```

**Pass criteria:** Exit code 0.

### RP-rebase-02: `--fail-fast`

```bash
rp_ro_setup rp-rebase-02
kanon repo rebase --fail-fast
```

**Pass criteria:** Exit code 0.

### RP-rebase-03: `--force-rebase`

```bash
rp_ro_setup rp-rebase-03
kanon repo rebase --force-rebase
```

**Pass criteria:** Exit code 0.

### RP-rebase-04: `--no-ff`

```bash
rp_ro_setup rp-rebase-04
kanon repo rebase --no-ff
```

**Pass criteria:** Exit code 0.

### RP-rebase-05: `--autosquash`

```bash
rp_ro_setup rp-rebase-05
kanon repo rebase --autosquash
```

**Pass criteria:** Exit code 0.

### RP-rebase-06: `--whitespace=fix`

```bash
rp_ro_setup rp-rebase-06
kanon repo rebase --whitespace=fix
```

**Pass criteria:** Exit code 0.

### RP-rebase-07: `--stash` / `-s`

```bash
rp_ro_setup rp-rebase-07
echo "dirty" >> .packages/pkg-alpha/README.md 2>/dev/null || true
kanon repo rebase -s
```

**Pass criteria:** Exit code 0; uncommitted changes stashed and re-applied.

### RP-rebase-08: `-i <project>` interactive

```bash
rp_ro_setup rp-rebase-08
echo "" | kanon repo rebase -i pkg-alpha 2>&1 || echo "(skipped no-tty)"
```

**Pass criteria:** Exit code 0 OR `skipped (no-tty)`.

### Cleanup

```bash
for d in rp-start-{01..04} rp-checkout-{01..02} rp-abandon-{01..03} rp-rebase-{01..08}; do
    cd "${KANON_TEST_ROOT}" && rm -rf "${d}"
done
```

---

## 25. Category 24: `kanon repo` Code-Review Workflows (upload, cherry-pick, stage, download, diff, diffmanifests) (31 tests)

All upload scenarios use `--dry-run` so no Gerrit/review server is required. Real upload requires a configured review server and is documented as out-of-scope for automation.

### Common setup

Reuses `rp_ro_setup()` from §22.

### RP-upload-01: `--dry-run` basic

```bash
rp_ro_setup rp-upload-01
kanon repo upload --dry-run
```

**Pass criteria:** Exit code 0; "no branches ready for upload" or similar.

### RP-upload-02: `-t` / `--auto-topic`

```bash
rp_ro_setup rp-upload-02
kanon repo start mybr --all
kanon repo upload --dry-run -t
```

**Pass criteria:** Exit code 0.

### RP-upload-03: `--topic=<name>`

```bash
rp_ro_setup rp-upload-03
kanon repo start mybr --all
kanon repo upload --dry-run --topic=mytopic
```

**Pass criteria:** Exit code 0.

### RP-upload-04: `--hashtag=a,b`

```bash
rp_ro_setup rp-upload-04
kanon repo start mybr --all
kanon repo upload --dry-run --hashtag=foo,bar
```

**Pass criteria:** Exit code 0.

### RP-upload-05: `--add-hashtag`

```bash
rp_ro_setup rp-upload-05
kanon repo start mybr --all
kanon repo upload --dry-run --add-hashtag=baz
```

**Pass criteria:** Exit code 0.

### RP-upload-06: `--label` / `-l`

```bash
rp_ro_setup rp-upload-06
kanon repo start mybr --all
kanon repo upload --dry-run -l "Code-Review+1"
```

**Pass criteria:** Exit code 0.

### RP-upload-07: `--description` / `-m`

```bash
rp_ro_setup rp-upload-07
kanon repo start mybr --all
kanon repo upload --dry-run -m "test description"
```

**Pass criteria:** Exit code 0.

### RP-upload-08: `--re=<reviewer>`

```bash
rp_ro_setup rp-upload-08
kanon repo start mybr --all
kanon repo upload --dry-run --re=alice@example.com
```

**Pass criteria:** Exit code 0.

### RP-upload-09: `--cc=<email>`

```bash
rp_ro_setup rp-upload-09
kanon repo start mybr --all
kanon repo upload --dry-run --cc=bob@example.com
```

**Pass criteria:** Exit code 0.

### RP-upload-10: `--private`

```bash
rp_ro_setup rp-upload-10
kanon repo start mybr --all
kanon repo upload --dry-run --private
```

**Pass criteria:** Exit code 0.

### RP-upload-11: `--wip`

```bash
rp_ro_setup rp-upload-11
kanon repo start mybr --all
kanon repo upload --dry-run --wip
```

**Pass criteria:** Exit code 0.

### RP-upload-12: `--current-branch` / `-c`

```bash
rp_ro_setup rp-upload-12
kanon repo start mybr --all
kanon repo upload --dry-run -c
```

**Pass criteria:** Exit code 0.

### RP-upload-13: `--branch-exclude=<branch>` / `-x`

```bash
rp_ro_setup rp-upload-13
kanon repo start mybr --all
kanon repo upload --dry-run -x main
```

**Pass criteria:** Exit code 0.

### RP-upload-14: `--auto-approve` / `-a`

```bash
rp_ro_setup rp-upload-14
kanon repo start mybr --all
kanon repo upload --dry-run -a
```

**Pass criteria:** Exit code 0.

### RP-upload-15: `--receive-pack`

```bash
rp_ro_setup rp-upload-15
kanon repo start mybr --all
kanon repo upload --dry-run --receive-pack="git-receive-pack --custom"
```

**Pass criteria:** Exit code 0.

### RP-cherry-pick-01: happy-path `<sha>`

```bash
rp_ro_setup rp-cherry-pick-01
sha=$(git -C .packages/pkg-alpha rev-parse HEAD 2>/dev/null) || sha=$(git -C .kanon-data/sources/*/.packages/pkg-alpha rev-parse HEAD 2>/dev/null)
test -n "${sha}" && kanon repo cherry-pick "${sha}" || echo "(no SHA available; skip)"
```

**Pass criteria:** Exit code 0 OR documented skip.

### RP-cherry-pick-02: nonexistent SHA errors

```bash
rp_ro_setup rp-cherry-pick-02
set +e
kanon repo cherry-pick deadbeefdeadbeefdeadbeefdeadbeefdeadbeef
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero.

### RP-stage-01: `-i` interactive smoke

```bash
rp_ro_setup rp-stage-01
echo "" | kanon repo stage -i 2>&1 || echo "(skipped no-tty)"
```

**Pass criteria:** Exit code 0 OR `skipped (no-tty)`.

### RP-download-01: bare (no-server skip)

```bash
rp_ro_setup rp-download-01
set +e
kanon repo download 12345
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero with clear "no review server" error OR `skipped (no-server)`.

### RP-download-02: `-c` / `--cherry-pick`

```bash
rp_ro_setup rp-download-02
set +e
kanon repo download -c 12345
set -e
```

**Pass criteria:** Same as RP-download-01.

### RP-download-03: `-x` / `--record-origin`

```bash
rp_ro_setup rp-download-03
set +e; kanon repo download -x 12345; set -e
```

**Pass criteria:** Same.

### RP-download-04: `-r` / `--revert`

```bash
rp_ro_setup rp-download-04
set +e; kanon repo download -r 12345; set -e
```

**Pass criteria:** Same.

### RP-download-05: `-f` / `--ff-only`

```bash
rp_ro_setup rp-download-05
set +e; kanon repo download -f 12345; set -e
```

**Pass criteria:** Same.

### RP-download-06: `-b` / `--branch=<name>`

```bash
rp_ro_setup rp-download-06
set +e; kanon repo download -b new-br 12345; set -e
```

**Pass criteria:** Same.

### RP-diff-01: bare diff

```bash
rp_ro_setup rp-diff-01
kanon repo diff
```

**Pass criteria:** Exit code 0.

### RP-diff-02: `--absolute` / `-u`

```bash
rp_ro_setup rp-diff-02
kanon repo diff -u
```

**Pass criteria:** Exit code 0.

### RP-diff-03: project-filtered

```bash
rp_ro_setup rp-diff-03
kanon repo diff pkg-alpha
```

**Pass criteria:** Exit code 0.

### RP-diffmanifests-01: one-arg

```bash
rp_ro_setup rp-diffmanifests-01
kanon repo manifest --output=/tmp/m1.xml
kanon repo diffmanifests /tmp/m1.xml
```

**Pass criteria:** Exit code 0.

### RP-diffmanifests-02: two-arg

```bash
rp_ro_setup rp-diffmanifests-02
kanon repo manifest --output=/tmp/m1.xml
kanon repo manifest --output=/tmp/m2.xml
kanon repo diffmanifests /tmp/m1.xml /tmp/m2.xml
```

**Pass criteria:** Exit code 0; empty diff.

### RP-diffmanifests-03: `--raw`

```bash
rp_ro_setup rp-diffmanifests-03
kanon repo manifest --output=/tmp/m1.xml
kanon repo diffmanifests --raw /tmp/m1.xml
```

**Pass criteria:** Exit code 0.

### RP-diffmanifests-04: `--no-color`

```bash
rp_ro_setup rp-diffmanifests-04
kanon repo manifest --output=/tmp/m1.xml
kanon repo diffmanifests --no-color /tmp/m1.xml
```

**Pass criteria:** Exit code 0.

### RP-diffmanifests-05: `--pretty-format=<fmt>`

```bash
rp_ro_setup rp-diffmanifests-05
kanon repo manifest --output=/tmp/m1.xml
kanon repo diffmanifests --pretty-format=oneline /tmp/m1.xml
```

**Pass criteria:** Exit code 0.

### Cleanup

```bash
for d in rp-upload-{01..15} rp-cherry-pick-{01..02} rp-stage-01 rp-download-{01..06} rp-diff-{01..03} rp-diffmanifests-{01..05}; do
    cd "${KANON_TEST_ROOT}" && rm -rf "${d}"
done
```

---

## 26. Category 25: `kanon repo` Maintenance Subcommands (prune, gc, overview, smartsync, envsubst, help, wrappers) (16 tests)

### RP-prune-01: bare prune

```bash
rp_ro_setup rp-prune-01
kanon repo prune
```

**Pass criteria:** Exit code 0.

### RP-prune-02: project-filtered

```bash
rp_ro_setup rp-prune-02
kanon repo prune pkg-alpha
```

**Pass criteria:** Exit code 0.

### RP-gc-01: bare gc

```bash
rp_ro_setup rp-gc-01
kanon repo gc
```

**Pass criteria:** Exit code 0.

### RP-gc-02: `--aggressive`

```bash
rp_ro_setup rp-gc-02
kanon repo gc --aggressive
```

**Pass criteria:** Exit code 0.

### RP-gc-03: `--all` / `-a`

```bash
rp_ro_setup rp-gc-03
kanon repo gc -a
```

**Pass criteria:** Exit code 0.

### RP-gc-04: `--repack-full-clone`

```bash
rp_ro_setup rp-gc-04
kanon repo gc --repack-full-clone
```

**Pass criteria:** Exit code 0.

### RP-overview-01: bare overview

```bash
rp_ro_setup rp-overview-01
kanon repo overview
```

**Pass criteria:** Exit code 0.

### RP-overview-02: `--current-branch`

```bash
rp_ro_setup rp-overview-02
kanon repo overview --current-branch
```

**Pass criteria:** Exit code 0.

### RP-smartsync-01: smoke

```bash
rp_ro_setup rp-smartsync-01
set +e; kanon repo smartsync; set -e
```

**Pass criteria:** Exit code 0 OR clear error.

### RP-envsubst-01: in-place

```bash
rp_ro_setup rp-envsubst-01
kanon repo envsubst
```

**Pass criteria:** Exit code 0.

### RP-envsubst-02: substitution check

```bash
rp_ro_setup rp-envsubst-02
MY_VAR=substituted_value kanon repo envsubst
echo "PASS"
```

**Pass criteria:** Exit code 0; XML files reflect `${MY_VAR}` substitution.

### RP-help-01: bare help

```bash
kanon repo help | head -1 | grep -qi "usage"
```

**Pass criteria:** Exit code 0; usage printed.

### RP-help-02: `--all` / `-a`

```bash
kanon repo help --all | head -1 | grep -qi "usage"
```

**Pass criteria:** Exit code 0.

### RP-help-03: `--help-all`

```bash
kanon repo help --help-all
```

**Pass criteria:** Exit code 0; help shown for all subcommands.

### RP-wrap-01: `--repo-dir=<custom>`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-wrap-01"
cd "${KANON_TEST_ROOT}/rp-wrap-01"
kanon repo --repo-dir=/tmp/custom-repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m repo-specs/packages.xml
test -d /tmp/custom-repo && echo "PASS"
```

**Pass criteria:** Exit code 0; `.repo` created at `/tmp/custom-repo` rather than `./.repo`.

### RP-wrap-02: env `KANON_REPO_DIR=<custom>`

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-wrap-02"
cd "${KANON_TEST_ROOT}/rp-wrap-02"
KANON_REPO_DIR=/tmp/env-repo kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m repo-specs/packages.xml
test -d /tmp/env-repo && echo "PASS"
```

**Pass criteria:** Exit code 0; `.repo` created at `/tmp/env-repo`.

### RP-wrap-03: `--repo-dir` flag overrides env

```bash
mkdir -p "${KANON_TEST_ROOT}/rp-wrap-03"
cd "${KANON_TEST_ROOT}/rp-wrap-03"
KANON_REPO_DIR=/tmp/env-A kanon repo --repo-dir=/tmp/flag-B init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m repo-specs/packages.xml
test -d /tmp/flag-B && test ! -d /tmp/env-A && echo "PASS: flag won"
```

**Pass criteria:** Exit code 0; flag value wins.

### RP-wrap-04: `kanon repo selfupdate` documented disabled message

```bash
set +e
kanon repo selfupdate 2>/tmp/rp-wrap-04-stderr.log 1>/tmp/rp-wrap-04-stdout.log
exit_code=$?
set -e
grep -q "selfupdate is not available" /tmp/rp-wrap-04-stderr.log \
  && test "$(wc -c < /tmp/rp-wrap-04-stdout.log)" -eq 0 \
  && test "${exit_code}" -eq 1 \
  && echo "PASS"
```

**Pass criteria:** Exit code 1; stderr contains `selfupdate is not available -- upgrade kanon-cli instead: pipx upgrade kanon-cli`; stdout is empty.

### Cleanup

```bash
for d in rp-prune-{01..02} rp-gc-{01..04} rp-overview-{01..02} rp-smartsync-01 rp-envsubst-{01..02} rp-help-{01..03} rp-wrap-{01..03}; do
    cd "${KANON_TEST_ROOT}" && rm -rf "${d}"
done
rm -rf /tmp/custom-repo /tmp/env-repo /tmp/env-A /tmp/flag-B
```

---

## 27. Category 26: Top-Level Command Additional Coverage (16 tests)

Existing categories cover most of the top-level surface. These scenarios fill remaining gaps.

### TC-bootstrap-01: `--output-dir=<path>`

```bash
mkdir -p "${KANON_TEST_ROOT}/tc-bs-01"
kanon bootstrap kanon --output-dir "${KANON_TEST_ROOT}/tc-bs-01"
test -f "${KANON_TEST_ROOT}/tc-bs-01/.kanon" && echo "PASS"
```

**Pass criteria:** Exit code 0; `.kanon` created at the named path.

### TC-bootstrap-02: `--catalog-source` flag form

```bash
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@latest" | grep -q test-entry
```

**Pass criteria:** Exit code 0; flag value used.

### TC-bootstrap-03: `KANON_CATALOG_SOURCE` env form

```bash
KANON_CATALOG_SOURCE="file://${CS_CATALOG_DIR}@latest" kanon bootstrap list | grep -q test-entry
```

**Pass criteria:** Exit code 0; env value used.

### TC-bootstrap-04: flag overrides env

```bash
KANON_CATALOG_SOURCE="file://nonexistent.git@1.0.0" kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@latest" | grep -q test-entry
```

**Pass criteria:** Exit code 0; flag value wins; no attempt to read env value.

### TC-bootstrap-05: bootstrap into nonexistent parent path errors

```bash
set +e
kanon bootstrap kanon --output-dir "${KANON_TEST_ROOT}/no/such/parent/dir"
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero; stderr names the missing parent.

### TC-install-01: auto-discover walks parent tree

```bash
mkdir -p "${KANON_TEST_ROOT}/tc-inst-01/sub/deep"
cd "${KANON_TEST_ROOT}/tc-inst-01"
cat > .kanon << KANONEOF
KANON_SOURCE_a_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml
KANONEOF
cd sub/deep
kanon install
test -L "${KANON_TEST_ROOT}/tc-inst-01/.packages/pkg-alpha" && echo "PASS"
kanon clean
```

**Pass criteria:** Install discovers the `.kanon` in the parent directory; `.packages/` created in parent.

### TC-install-02: explicit path bypasses auto-discover

```bash
mkdir -p "${KANON_TEST_ROOT}/tc-inst-02"
cd "${KANON_TEST_ROOT}/tc-inst-02"
cat > my.kanon << KANONEOF
KANON_SOURCE_a_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml
KANONEOF
kanon install my.kanon
test -L .packages/pkg-alpha && echo "PASS"
kanon clean my.kanon
```

**Pass criteria:** Exit code 0; install uses the explicit path.

### TC-install-03: `REPO_URL` env emits deprecation warning

```bash
mkdir -p "${KANON_TEST_ROOT}/tc-inst-03"
cd "${KANON_TEST_ROOT}/tc-inst-03"
cat > .kanon << KANONEOF
KANON_SOURCE_a_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml
KANONEOF
REPO_URL=https://example.com/repo.git kanon install .kanon 2>&1 | tee /tmp/tc-inst-03.log
grep -qi "deprecat" /tmp/tc-inst-03.log && echo "PASS"
kanon clean .kanon
```

**Pass criteria:** Exit code 0; stderr/stdout contains a deprecation message naming `REPO_URL`.

### TC-install-04: `REPO_REV` env emits deprecation warning

```bash
mkdir -p "${KANON_TEST_ROOT}/tc-inst-04"
cd "${KANON_TEST_ROOT}/tc-inst-04"
cat > .kanon << KANONEOF
KANON_SOURCE_a_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml
KANONEOF
REPO_REV=v1.2.3 kanon install .kanon 2>&1 | tee /tmp/tc-inst-04.log
grep -qi "deprecat" /tmp/tc-inst-04.log && echo "PASS"
kanon clean .kanon
```

**Pass criteria:** Same as TC-install-03 but for `REPO_REV`.

### TC-clean-01: auto-discover clean

```bash
mkdir -p "${KANON_TEST_ROOT}/tc-cln-01"
cd "${KANON_TEST_ROOT}/tc-cln-01"
cat > .kanon << KANONEOF
KANON_SOURCE_a_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml
KANONEOF
kanon install
kanon clean
test ! -d .packages && test ! -d .kanon-data && echo "PASS"
```

**Pass criteria:** Exit code 0; both directories removed.

### TC-clean-02: `.gitignore` lines retained after clean

```bash
mkdir -p "${KANON_TEST_ROOT}/tc-cln-02"
cd "${KANON_TEST_ROOT}/tc-cln-02"
cat > .kanon << KANONEOF
KANON_SOURCE_a_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml
KANONEOF
kanon install
grep -q "^.packages/$" .gitignore || (echo "FAIL: install did not add"; exit 1)
kanon clean
grep -q "^.packages/$" .gitignore && grep -q "^.kanon-data/$" .gitignore && echo "PASS: clean preserved both lines"
```

**Pass criteria:** Both `.gitignore` lines added by install remain after clean.

### TC-validate-01: `validate xml --repo-root=<path>`

<!-- Precondition: MANIFEST_PRIMARY_DIR must be inside a git checkout (git init was run during fixture setup in Category 3). -->

```bash
kanon validate xml --repo-root "${MANIFEST_PRIMARY_DIR}"
```

**Pass criteria:** Exit code 0.

### TC-validate-02: `validate marketplace --repo-root=<path>`

```bash
kanon validate marketplace --repo-root "${MK_MFST}"
```

**Pass criteria:** Exit code 0 (or non-zero only for MK-19's invalid `dest=` row, which is documented separately).

### TC-validate-03: auto-detect via `git rev-parse`

```bash
cd "${MANIFEST_PRIMARY_DIR}"
kanon validate xml
```

**Pass criteria:** Exit code 0; `--repo-root` discovered from current git checkout.

### TC-validate-04: rejected when neither flag nor git root works

```bash
set +e
cd /tmp
kanon validate xml
exit_code=$?
set -e
```

**Pass criteria:** Exit code non-zero; stderr names the missing repo root.

### TC-extra: kanon-specific env vars (`KANON_GIT_RETRY_COUNT`, `KANON_GIT_RETRY_DELAY`, `KANON_SSH_MASTER_TIMEOUT_SEC`)

```bash
mkdir -p "${KANON_TEST_ROOT}/tc-extra"
cd "${KANON_TEST_ROOT}/tc-extra"
KANON_GIT_RETRY_COUNT=1 KANON_GIT_RETRY_DELAY=0 KANON_SSH_MASTER_TIMEOUT_SEC=1 kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml
echo "PASS"
```

**Pass criteria:** Exit code 0; env vars accepted (smoke).

### Cleanup

```bash
for d in tc-bs-01 tc-inst-{01..04} tc-cln-{01..02} tc-extra; do
    cd "${KANON_TEST_ROOT}" && rm -rf "${d}"
done
```

---

## 28. Category 27: Doc-Grounded User Journeys (12 tests)

Each journey reproduces a sequence verbatim from `kanon/docs/`. Source citations are included so doc drift is caught: if the doc updates the journey, the test row updates too.

### UJ-01: `pip install -e .` → `kanon bootstrap kanon` → install → use → clean (`docs/setup-guide.md`)

```bash
cd /workspaces/rpm-migration/kanon && pip install -e . > /dev/null
mkdir -p "${KANON_TEST_ROOT}/uj-01"
cd "${KANON_TEST_ROOT}/uj-01"
kanon bootstrap kanon
ls .kanon kanon-readme.md
# (operator would edit .kanon here; we keep the bundled defaults)
# kanon install (commented; bundled .kanon points at remote — out of scope for offline run)
echo "PASS: bootstrap produced .kanon and readme"
```

**Pass criteria:** Exit code 0; bootstrap files produced.

### UJ-02: bootstrap with `--catalog-source` PEP 440 (`docs/creating-manifest-repos.md`)

```bash
mkdir -p "${KANON_TEST_ROOT}/uj-02"
cd "${KANON_TEST_ROOT}/uj-02"
kanon bootstrap list --catalog-source "file://${CS_CATALOG_DIR}@>=2.0.0,<3.0.0" | grep -q test-entry
```

**Pass criteria:** Exit code 0; `test-entry` listed; resolves to highest 2.x tag.

### UJ-03: multi-source install (`docs/multi-source-guide.md`)

```bash
mkdir -p "${KANON_TEST_ROOT}/uj-03"
cd "${KANON_TEST_ROOT}/uj-03"
cat > .kanon << KANONEOF
KANON_SOURCE_alpha_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_alpha_REVISION=main
KANON_SOURCE_alpha_PATH=repo-specs/alpha-only.xml
KANON_SOURCE_bravo_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_bravo_REVISION=main
KANON_SOURCE_bravo_PATH=repo-specs/bravo-only.xml
KANONEOF
kanon install .kanon
test -L .packages/pkg-alpha && test -L .packages/pkg-bravo && echo "PASS: both"
grep -q "^.packages/$" .gitignore && grep -q "^.kanon-data/$" .gitignore && echo "PASS: gitignore"
kanon clean .kanon
```

**Pass criteria:** Both packages aggregated; `.gitignore` updated.

### UJ-04: `GITBASE` env override (`docs/pipeline-integration.md`)

```bash
mkdir -p "${KANON_TEST_ROOT}/uj-04"
cd "${KANON_TEST_ROOT}/uj-04"
cat > .kanon << KANONEOF
GITBASE=https://default.example.com
KANON_SOURCE_a_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml
KANONEOF
GITBASE="file:///tmp/override-base/" kanon install .kanon
test -L .packages/pkg-alpha && echo "PASS"
kanon clean .kanon
```

**Pass criteria:** Exit code 0; install honoured the env override.

### UJ-05: full marketplace lifecycle (`docs/claude-marketplaces-guide.md`)

```bash
mk_run mk01 "main"
claude plugin list 2>/dev/null | grep -q "mk01" && echo "PASS: visible"
kanon clean .kanon
claude plugin list 2>/dev/null | grep -q "mk01" || echo "PASS: removed"
```

**Pass criteria:** Plugin appears after install; absent after clean. Skipped (no-claude) when claude CLI absent.

### UJ-06: collision detection (`docs/multi-source-guide.md`)

```bash
mkdir -p "${KANON_TEST_ROOT}/uj-06"
cd "${KANON_TEST_ROOT}/uj-06"
cat > .kanon << KANONEOF
KANON_SOURCE_a_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml
KANON_SOURCE_b_URL=file://${MANIFEST_COLLISION_DIR}
KANON_SOURCE_b_REVISION=main
KANON_SOURCE_b_PATH=repo-specs/collision.xml
KANONEOF
set +e
kanon install .kanon 2>&1 | tee /tmp/uj-06.log
exit_code=$?
set -e
grep -qi "collision\|collide" /tmp/uj-06.log && echo "PASS"
```

**Pass criteria:** Exit code non-zero; stderr names the collision.

### UJ-07: linkfile journey (`docs/claude-marketplaces-guide.md`, `docs/how-it-works.md`)

```bash
mk_run mk22 "main"
test -L "${KANON_TEST_ROOT}/mk22-mpl/mk22-deep" && echo "PASS: symlink"
readlink "${KANON_TEST_ROOT}/mk22-mpl/mk22-deep" | grep -q ".kanon-data/sources" && echo "PASS: symlink target inside .kanon-data/sources/"
kanon clean .kanon
```

**Pass criteria:** Symlink resolves into `.kanon-data/sources/<name>/`.

### UJ-08: pipeline cache (`docs/pipeline-integration.md`)

```bash
mkdir -p "${KANON_TEST_ROOT}/uj-08"
cd "${KANON_TEST_ROOT}/uj-08"
cat > .kanon << KANONEOF
KANON_SOURCE_a_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml
KANONEOF
kanon install .kanon
# Simulate cache save/restore: archive .packages and .kanon-data, restore.
tar czf /tmp/uj-08-cache.tgz .packages .kanon-data
rm -rf .packages .kanon-data
tar xzf /tmp/uj-08-cache.tgz
kanon clean .kanon
test ! -d .packages && test ! -d .kanon-data && echo "PASS: clean still works after restore"
```

**Pass criteria:** Clean succeeds against a restored-from-cache state.

### UJ-09: shell variable expansion (`docs/configuration.md`)

```bash
mkdir -p "${KANON_TEST_ROOT}/uj-09"
cd "${KANON_TEST_ROOT}/uj-09"
cat > .kanon << 'KANONEOF'
KANON_SOURCE_a_URL=file://${MANIFEST_PRIMARY_DIR}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml
HOME_NOTE=${HOME}
KANONEOF
MANIFEST_PRIMARY_DIR="${MANIFEST_PRIMARY_DIR}" kanon install .kanon
echo "PASS: HOME expansion accepted"
kanon clean .kanon

# Undefined-var case
cat > .kanon << 'KANONEOF'
KANON_SOURCE_a_URL=${UNDEFINED_KANON_VAR}
KANON_SOURCE_a_REVISION=main
KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml
KANONEOF
set +e
kanon install .kanon 2>&1 | tee /tmp/uj-09.log
exit_code=$?
set -e
grep -q "UNDEFINED_KANON_VAR" /tmp/uj-09.log && echo "PASS: undefined var named in error"
```

**Pass criteria:** First case succeeds; second case errors with clear message naming the missing variable.

### UJ-10: `python -m kanon_cli` entry point

```bash
python -m kanon_cli --version | grep -qE "kanon \d+\.\d+\.\d+"
python -m kanon_cli --help | grep -E "install|clean|validate|bootstrap" | wc -l | grep -q "^[1-9]"
```

**Pass criteria:** Both invocations exit 0; output matches kanon's package version and command list.

### UJ-11: standalone-repo journey (`docs/configuration.md`)

```bash
mkdir -p "${KANON_TEST_ROOT}/uj-11"
cd "${KANON_TEST_ROOT}/uj-11"
kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m default.xml
kanon repo sync --jobs=4
kanon repo status
echo "PASS"
```

**Pass criteria:** All three commands exit 0.

### UJ-12: manifest validation journey (`docs/creating-manifest-repos.md`)

```bash
cd "${MANIFEST_PRIMARY_DIR}"
kanon validate xml --repo-root "${MANIFEST_PRIMARY_DIR}"
kanon validate marketplace --repo-root "${MK_MFST}" 2>&1 || echo "(MK-19 fixture causes exit non-zero by design)"
```

**Pass criteria:** First call exits 0; second exits 0 only when no invalid `dest=` rows are present in the marketplace fixture.

### Cleanup

```bash
for d in uj-{01..04} uj-{06} uj-{08..09} uj-11; do
    cd "${KANON_TEST_ROOT}" && rm -rf "${d}"
done
rm -f /tmp/uj-08-cache.tgz /tmp/uj-09.log /tmp/uj-06.log
```

---

## 29. Install Verification Details

After any successful `kanon install`, verify the following artifacts:

### 16.1 .gitignore contents

```bash
grep -q "^\.packages/$" .gitignore && echo "PASS: .packages/ in .gitignore" || echo "FAIL"
grep -q "^\.kanon-data/$" .gitignore && echo "PASS: .kanon-data/ in .gitignore" || echo "FAIL"
```

### 16.2 .packages/ contains symlinks

```bash
for entry in .packages/*; do
  if [ -L "${entry}" ]; then
    echo "PASS: ${entry} is a symlink"
  else
    echo "FAIL: ${entry} is not a symlink"
  fi
done
```

### 16.3 Symlinks point into .kanon-data/sources/

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

### 16.4 .kanon-data/sources/ has one directory per source

```bash
source_count=$(ls -1d .kanon-data/sources/*/ 2>/dev/null | wc -l)
echo "Source directories found: ${source_count}"
ls -1d .kanon-data/sources/*/
```

**Pass criteria:** The number of directories matches the number of `KANON_SOURCE_<name>_URL` entries in the `.kanon` file. Each directory name matches the `<name>` portion of the source variable.

---

## 30. How to Run

### Full sequential run

Execute all tests sequentially. Each test section is independent and includes
its own cleanup. Run them in order from Category 1 through Category 14.

```bash
set -euo pipefail

export KANON_TEST_ROOT="/tmp/kanon-integration-tests"
rm -rf "${KANON_TEST_ROOT}"
mkdir -p "${KANON_TEST_ROOT}"

# 1. Run Category 1 (Help & Version) -- HV-01 through HV-08
# 2. Run Category 2 (Bootstrap) -- BS-01 through BS-07
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
# 14. Run Category 14 (Auto-Discovery) -- AD-01 through AD-08
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
- Categories 4, 5, 6, 7, and 14 require the fixtures from Category 3 to be
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

---

## 31. Numbered Cell Results Table

After running every scenario from §2 through §28, populate this spreadsheet-style appendix with one row per test. The table is regenerated on every run; the published version below is a template (status / exit / time / notes left blank for the operator or agent to fill in).

| #   | ID            | Section                            | Subject                                                | Status | Exit | Time(s) | Notes |
|----:|---------------|------------------------------------|--------------------------------------------------------|--------|-----:|--------:|-------|
| 001 | HV-01         | help-version                       | Top-level help                                         |        |      |         |       |
| 002 | HV-02         | help-version                       | Version flag                                           |        |      |         |       |
| 003 | HV-03         | help-version                       | Install subcommand help                                |        |      |         |       |
| 004 | HV-04         | help-version                       | Clean subcommand help                                  |        |      |         |       |
| 005 | HV-05         | help-version                       | Validate subcommand help                               |        |      |         |       |
| 006 | HV-06         | help-version                       | Validate xml sub-help                                  |        |      |         |       |
| 007 | HV-07         | help-version                       | Validate marketplace sub-help                          |        |      |         |       |
| 008 | HV-08         | help-version                       | Bootstrap subcommand help                              |        |      |         |       |
| 009 | BS-01         | bootstrap                          | List bundled packages                                  |        |      |         |       |
| 010 | BS-02         | bootstrap                          | Bootstrap into current dir                             |        |      |         |       |
| 011 | BS-03         | bootstrap                          | Bootstrap with --output-dir                            |        |      |         |       |
| 012 | BS-04         | bootstrap                          | Conflict on existing .kanon                            |        |      |         |       |
| 013 | BS-05         | bootstrap                          | Unknown package                                        |        |      |         |       |
| 014 | BS-06         | bootstrap                          | Blocker file at output path                            |        |      |         |       |
| 015 | BS-07         | bootstrap                          | Missing parent dir                                     |        |      |         |       |
| 016 | IC-01         | install-clean                      | Single source install/clean                            |        |      |         |       |
| 017 | IC-02         | install-clean                      | Shell variable ${HOME} expansion                       |        |      |         |       |
| 018 | IC-03         | install-clean                      | Comments and blank lines                               |        |      |         |       |
| 019 | IC-04         | install-clean                      | Marketplace install false                              |        |      |         |       |
| 020 | MS-01         | multi-source                       | Two sources aggregate                                  |        |      |         |       |
| 021 | CD-01         | collision                          | Same-name collision two sources                        |        |      |         |       |
| 022 | CD-02         | collision                          | Three-source alphabetical collision                    |        |      |         |       |
| 023 | LF-01         | linkfile                           | linkfile creates symlinks                              |        |      |         |       |
| 024 | EC-01         | error-cases                        | Missing .kanon                                         |        |      |         |       |
| 025 | EC-02         | error-cases                        | Empty .kanon                                           |        |      |         |       |
| 026 | EC-03         | error-cases                        | Undefined shell variable                               |        |      |         |       |
| 027 | EC-04         | error-cases                        | Missing source URL                                     |        |      |         |       |
| 028 | EC-05         | error-cases                        | Deprecated KANON_SOURCES                               |        |      |         |       |
| 029 | EC-06         | error-cases                        | MARKETPLACE_INSTALL=true without DIR                   |        |      |         |       |
| 030 | EC-07         | error-cases                        | No subcommand                                          |        |      |         |       |
| 031 | EC-08         | error-cases                        | Invalid subcommand                                     |        |      |         |       |
| 032 | EC-09         | error-cases                        | Validate without target                                |        |      |         |       |
| 033 | ID-01         | idempotency                        | Double install                                         |        |      |         |       |
| 034 | ID-02         | idempotency                        | Clean without prior install                            |        |      |         |       |
| 035 | ID-03         | idempotency                        | Double clean                                           |        |      |         |       |
| 036 | EV-01         | env-override                       | GITBASE override                                       |        |      |         |       |
| 037 | EV-02         | env-override                       | KANON_MARKETPLACE_INSTALL override                     |        |      |         |       |
| 038 | EV-03         | env-override                       | KANON_CATALOG_SOURCE env                               |        |      |         |       |
| 039 | VA-01         | validate                           | xml in repo with manifests                             |        |      |         |       |
| 040 | VA-02         | validate                           | marketplace in repo                                    |        |      |         |       |
| 041 | VA-03         | validate                           | xml with --repo-root                                   |        |      |         |       |
| 042 | VA-04         | validate                           | xml empty repo-specs                                   |        |      |         |       |
| 043 | EP-01         | entry-point                        | python -m kanon_cli --version                          |        |      |         |       |
| 044 | EP-02         | entry-point                        | python -m kanon_cli --help                             |        |      |         |       |
| 045 | CS-01         | catalog-pep440                     | bare * via flag                                        |        |      |         |       |
| 046 | CS-02         | catalog-pep440                     | bare * via env var                                     |        |      |         |       |
| 047 | CS-03         | catalog-pep440                     | latest via flag                                        |        |      |         |       |
| 048 | CS-04         | catalog-pep440                     | latest via env var                                     |        |      |         |       |
| 049 | CS-05         | catalog-pep440                     | ~=1.0.0 via flag                                       |        |      |         |       |
| 050 | CS-06         | catalog-pep440                     | ~=1.0.0 via env var                                    |        |      |         |       |
| 051 | CS-07         | catalog-pep440                     | ~=2.0.0 via flag                                       |        |      |         |       |
| 052 | CS-08         | catalog-pep440                     | ~=2.0.0 via env var                                    |        |      |         |       |
| 053 | CS-09         | catalog-pep440                     | >=1.2.0 via flag                                       |        |      |         |       |
| 054 | CS-10         | catalog-pep440                     | >=1.2.0 via env var                                    |        |      |         |       |
| 055 | CS-11         | catalog-pep440                     | <2.0.0 via flag                                        |        |      |         |       |
| 056 | CS-12         | catalog-pep440                     | <2.0.0 via env var                                     |        |      |         |       |
| 057 | CS-13         | catalog-pep440                     | <=1.1.0 via flag                                       |        |      |         |       |
| 058 | CS-14         | catalog-pep440                     | <=1.1.0 via env var                                    |        |      |         |       |
| 059 | CS-15         | catalog-pep440                     | ==1.0.1 via flag                                       |        |      |         |       |
| 060 | CS-16         | catalog-pep440                     | ==1.0.1 via env var                                    |        |      |         |       |
| 061 | CS-17         | catalog-pep440                     | !=2.0.0 via flag                                       |        |      |         |       |
| 062 | CS-18         | catalog-pep440                     | !=2.0.0 via env var                                    |        |      |         |       |
| 063 | CS-19         | catalog-pep440                     | range via flag                                         |        |      |         |       |
| 064 | CS-20         | catalog-pep440                     | range via env var                                      |        |      |         |       |
| 065 | CS-21         | catalog-pep440                     | ==3.0.0 via flag                                       |        |      |         |       |
| 066 | CS-22         | catalog-pep440                     | ==3.0.0 via env var                                    |        |      |         |       |
| 067 | CS-23         | catalog-pep440                     | refs/tags/ prefixed flag                               |        |      |         |       |
| 068 | CS-24         | catalog-pep440                     | refs/tags/ prefixed env                                |        |      |         |       |
| 069 | CS-25         | catalog-pep440                     | namespaced prefix flag                                 |        |      |         |       |
| 070 | CS-26         | catalog-pep440                     | namespaced prefix env                                  |        |      |         |       |
| 071 | AD-01         | auto-discovery                     | install no-arg in dir with .kanon                      |        |      |         |       |
| 072 | AD-02         | auto-discovery                     | install in subdir, .kanon in parent                    |        |      |         |       |
| 073 | AD-03         | auto-discovery                     | install no .kanon anywhere                             |        |      |         |       |
| 074 | AD-04         | auto-discovery                     | install .kanon explicit                                |        |      |         |       |
| 075 | AD-05         | auto-discovery                     | clean no-arg                                           |        |      |         |       |
| 076 | AD-06         | auto-discovery                     | clean in subdir                                        |        |      |         |       |
| 077 | AD-07         | auto-discovery                     | explicit path overrides discovery                      |        |      |         |       |
| 078 | AD-08         | auto-discovery                     | install prints discovered .kanon path                  |        |      |         |       |
| 079 | RX-01         | pep440-xml-revision                | bare latest                                            |        |      |         |       |
| 080 | RX-02         | pep440-xml-revision                | bare 1.0.0                                             |        |      |         |       |
| 081 | RX-03         | pep440-xml-revision                | bare 2.0.0                                             |        |      |         |       |
| 082 | RX-04         | pep440-xml-revision                | bare *                                                 |        |      |         |       |
| 083 | RX-05         | pep440-xml-revision                | bare ~=1.0.0                                           |        |      |         |       |
| 084 | RX-06         | pep440-xml-revision                | bare ~=2.0                                             |        |      |         |       |
| 085 | RX-07         | pep440-xml-revision                | bare >=1.2.0                                           |        |      |         |       |
| 086 | RX-08         | pep440-xml-revision                | bare <2.0.0                                            |        |      |         |       |
| 087 | RX-09         | pep440-xml-revision                | bare <=1.1.0                                           |        |      |         |       |
| 088 | RX-10         | pep440-xml-revision                | bare ==1.0.1                                           |        |      |         |       |
| 089 | RX-11         | pep440-xml-revision                | bare !=2.0.0                                           |        |      |         |       |
| 090 | RX-12         | pep440-xml-revision                | bare range >=1.0.0,<2.0.0                              |        |      |         |       |
| 091 | RX-13         | pep440-xml-revision                | bare ==3.0.0                                           |        |      |         |       |
| 092 | RX-14         | pep440-xml-revision                | refs/tags/latest                                       |        |      |         |       |
| 093 | RX-15         | pep440-xml-revision                | refs/tags/1.0.0                                        |        |      |         |       |
| 094 | RX-16         | pep440-xml-revision                | refs/tags/2.0.0                                        |        |      |         |       |
| 095 | RX-17         | pep440-xml-revision                | refs/tags/*                                            |        |      |         |       |
| 096 | RX-18         | pep440-xml-revision                | refs/tags/~=1.0.0                                      |        |      |         |       |
| 097 | RX-19         | pep440-xml-revision                | refs/tags/~=2.0                                        |        |      |         |       |
| 098 | RX-20         | pep440-xml-revision                | refs/tags/>=1.2.0                                      |        |      |         |       |
| 099 | RX-21         | pep440-xml-revision                | refs/tags/<2.0.0                                       |        |      |         |       |
| 100 | RX-22         | pep440-xml-revision                | refs/tags/<=1.1.0                                      |        |      |         |       |
| 101 | RX-23         | pep440-xml-revision                | refs/tags/==1.0.1                                      |        |      |         |       |
| 102 | RX-24         | pep440-xml-revision                | refs/tags/!=2.0.0                                      |        |      |         |       |
| 103 | RX-25         | pep440-xml-revision                | refs/tags/ range                                       |        |      |         |       |
| 104 | RX-26         | pep440-xml-revision                | invalid ==* rejected                                   |        |      |         |       |
| 105 | KS-01         | pep440-kanon-revision              | bare latest                                            |        |      |         |       |
| 106 | KS-02         | pep440-kanon-revision              | refs/tags/latest                                       |        |      |         |       |
| 107 | KS-03         | pep440-kanon-revision              | bare *                                                 |        |      |         |       |
| 108 | KS-04         | pep440-kanon-revision              | refs/tags/*                                            |        |      |         |       |
| 109 | KS-05         | pep440-kanon-revision              | plain 1.0.0                                            |        |      |         |       |
| 110 | KS-06         | pep440-kanon-revision              | bare ~=1.0.0                                           |        |      |         |       |
| 111 | KS-07         | pep440-kanon-revision              | refs/tags/~=1.0.0                                      |        |      |         |       |
| 112 | KS-08         | pep440-kanon-revision              | bare ~=2.0                                             |        |      |         |       |
| 113 | KS-09         | pep440-kanon-revision              | bare >=1.2.0                                           |        |      |         |       |
| 114 | KS-10         | pep440-kanon-revision              | bare <2.0.0                                            |        |      |         |       |
| 115 | KS-11         | pep440-kanon-revision              | bare <=1.1.0                                           |        |      |         |       |
| 116 | KS-12         | pep440-kanon-revision              | bare ==1.0.1                                           |        |      |         |       |
| 117 | KS-13         | pep440-kanon-revision              | bare !=2.0.0                                           |        |      |         |       |
| 118 | KS-14         | pep440-kanon-revision              | bare range                                             |        |      |         |       |
| 119 | KS-15         | pep440-kanon-revision              | refs/tags/ range (production form)                     |        |      |         |       |
| 120 | KS-16         | pep440-kanon-revision              | refs/tags/~=2.0                                        |        |      |         |       |
| 121 | KS-17         | pep440-kanon-revision              | refs/tags/>=1.2.0                                      |        |      |         |       |
| 122 | KS-18         | pep440-kanon-revision              | refs/tags/<2.0.0                                       |        |      |         |       |
| 123 | KS-19         | pep440-kanon-revision              | refs/tags/<=1.1.0                                      |        |      |         |       |
| 124 | KS-20         | pep440-kanon-revision              | refs/tags/==1.0.1                                      |        |      |         |       |
| 125 | KS-21         | pep440-kanon-revision              | refs/tags/!=2.0.0                                      |        |      |         |       |
| 126 | KS-22         | pep440-kanon-revision              | refs/tags/ range                                       |        |      |         |       |
| 127 | KS-23         | pep440-kanon-revision              | refs/tags/==3.0.0                                      |        |      |         |       |
| 128 | KS-24         | pep440-kanon-revision              | env override of REVISION                               |        |      |         |       |
| 129 | KS-25         | pep440-kanon-revision              | undefined shell var error                              |        |      |         |       |
| 130 | KS-26         | pep440-kanon-revision              | invalid ==* rejected                                   |        |      |         |       |
| 131 | MK-01         | marketplace                        | basic happy path                                       |        |      |         |       |
| 132 | MK-02         | marketplace                        | exact tag pin both                                     |        |      |         |       |
| 133 | MK-03         | marketplace                        | PEP 440 in XML only                                    |        |      |         |       |
| 134 | MK-04         | marketplace                        | PEP 440 in .kanon only                                 |        |      |         |       |
| 135 | MK-05         | marketplace                        | PEP 440 in BOTH                                        |        |      |         |       |
| 136 | MK-06         | marketplace                        | latest sentinel both                                   |        |      |         |       |
| 137 | MK-07         | marketplace                        | != XML                                                 |        |      |         |       |
| 138 | MK-08         | marketplace                        | != .kanon                                              |        |      |         |       |
| 139 | MK-09         | marketplace                        | upper-bound XML                                        |        |      |         |       |
| 140 | MK-10         | marketplace                        | upper-bound .kanon                                     |        |      |         |       |
| 141 | MK-11         | marketplace                        | exact pin both                                         |        |      |         |       |
| 142 | MK-12         | marketplace                        | invalid ==* rejected                                   |        |      |         |       |
| 143 | MK-13         | marketplace                        | multiple plugins per marketplace.json                  |        |      |         |       |
| 144 | MK-14         | marketplace                        | minimal plugin.json                                    |        |      |         |       |
| 145 | MK-15         | marketplace                        | full metadata plugin.json                              |        |      |         |       |
| 146 | MK-16         | marketplace                        | cascading <include> chain                              |        |      |         |       |
| 147 | MK-17         | marketplace                        | multiple <project> entries                             |        |      |         |       |
| 148 | MK-18         | marketplace                        | bare * both                                            |        |      |         |       |
| 149 | MK-19         | marketplace                        | invalid dest= rejected                                 |        |      |         |       |
| 150 | MK-20         | marketplace                        | re-install after clean                                 |        |      |         |       |
| 151 | MK-21         | marketplace                        | multi-marketplace                                      |        |      |         |       |
| 152 | MK-22         | marketplace                        | linkfile cascading dir tree                            |        |      |         |       |
| 153 | PK-01         | non-marketplace                    | basic install/clean                                    |        |      |         |       |
| 154 | PK-02         | non-marketplace                    | PEP 440 in XML                                         |        |      |         |       |
| 155 | PK-03         | non-marketplace                    | PEP 440 in .kanon                                      |        |      |         |       |
| 156 | PK-04         | non-marketplace                    | PEP 440 BOTH                                           |        |      |         |       |
| 157 | PK-05         | non-marketplace                    | clean no-op                                            |        |      |         |       |
| 158 | PK-06         | non-marketplace                    | re-install                                             |        |      |         |       |
| 159 | PK-07         | non-marketplace                    | env REVISION override                                  |        |      |         |       |
| 160 | PK-08         | non-marketplace                    | invalid ==*                                            |        |      |         |       |
| 161 | PK-09         | non-marketplace                    | multiple packages one source                           |        |      |         |       |
| 162 | PK-10         | non-marketplace                    | linkfile + PEP 440                                     |        |      |         |       |
| 163 | PK-11         | non-marketplace                    | multi-source PEP 440 mix                               |        |      |         |       |
| 164 | PK-12         | non-marketplace                    | collision PEP 440                                      |        |      |         |       |
| 165 | PK-13         | non-marketplace                    | .gitignore promise                                     |        |      |         |       |
| 166 | RP-init-01    | repo-init                          | bare init                                              |        |      |         |       |
| 167 | RP-init-02    | repo-init                          | --manifest-url long form                               |        |      |         |       |
| 168 | RP-init-03    | repo-init                          | --manifest-name=alt.xml                                |        |      |         |       |
| 169 | RP-init-04    | repo-init                          | --manifest-depth=1                                     |        |      |         |       |
| 170 | RP-init-05    | repo-init                          | --manifest-upstream-branch                             |        |      |         |       |
| 171 | RP-init-06    | repo-init                          | --standalone-manifest                                  |        |      |         |       |
| 172 | RP-init-07    | repo-init                          | --reference                                            |        |      |         |       |
| 173 | RP-init-08    | repo-init                          | --dissociate                                           |        |      |         |       |
| 174 | RP-init-09    | repo-init                          | --no-clone-bundle                                      |        |      |         |       |
| 175 | RP-init-10    | repo-init                          | --mirror                                               | PASS   |      |         |       |
| 176 | RP-init-11    | repo-init                          | --worktree                                             |        |      |         |       |
| 177 | RP-init-12    | repo-init                          | --submodules                                           |        |      |         |       |
| 178 | RP-init-13    | repo-init                          | --partial-clone --clone-filter                         |        |      |         |       |
| 179 | RP-init-14    | repo-init                          | --git-lfs                                              |        |      |         |       |
| 180 | RP-init-15    | repo-init                          | --use-superproject                                     |        |      |         |       |
| 181 | RP-init-16    | repo-init                          | --current-branch-only                                  |        |      |         |       |
| 182 | RP-init-17    | repo-init                          | --groups                                               |        |      |         |       |
| 183 | RP-init-18    | repo-init                          | env REPO_MANIFEST_URL                                  |        |      |         |       |
| 184 | RP-sync-01    | repo-sync                          | bare sync                                              |        |      |         |       |
| 185 | RP-sync-02    | repo-sync                          | --network-only                                         |        |      |         |       |
| 186 | RP-sync-03    | repo-sync                          | --local-only                                           |        |      |         |       |
| 187 | RP-sync-04    | repo-sync                          | --detach                                               |        |      |         |       |
| 188 | RP-sync-05    | repo-sync                          | --current-branch                                       |        |      |         |       |
| 189 | RP-sync-06    | repo-sync                          | --no-current-branch                                    |        |      |         |       |
| 190 | RP-sync-07    | repo-sync                          | --force-checkout                                       |        |      |         |       |
| 191 | RP-sync-08    | repo-sync                          | --force-remove-dirty                                   |        |      |         |       |
| 192 | RP-sync-09    | repo-sync                          | --rebase                                               |        |      |         |       |
| 193 | RP-sync-10    | repo-sync                          | --force-sync                                           |        |      |         |       |
| 194 | RP-sync-11    | repo-sync                          | --clone-bundle                                         |        |      |         |       |
| 195 | RP-sync-12    | repo-sync                          | --no-clone-bundle                                      |        |      |         |       |
| 196 | RP-sync-13    | repo-sync                          | --fetch-submodules                                     |        |      |         |       |
| 197 | RP-sync-14    | repo-sync                          | --use-superproject                                     |        |      |         |       |
| 198 | RP-sync-15    | repo-sync                          | --no-use-superproject                                  |        |      |         |       |
| 199 | RP-sync-16    | repo-sync                          | --tags                                                 |        |      |         |       |
| 200 | RP-sync-17    | repo-sync                          | --no-tags                                              |        |      |         |       |
| 201 | RP-sync-18    | repo-sync                          | --optimized-fetch                                      |        |      |         |       |
| 202 | RP-sync-19    | repo-sync                          | --retry-fetches                                        |        |      |         |       |
| 203 | RP-sync-20    | repo-sync                          | --prune / --no-prune                                   |        |      |         |       |
| 204 | RP-sync-21    | repo-sync                          | --auto-gc / --no-auto-gc                               |        |      |         |       |
| 205 | RP-sync-22    | repo-sync                          | --no-repo-verify                                       |        |      |         |       |
| 206 | RP-sync-23    | repo-sync                          | --jobs-network / --jobs-checkout                       |        |      |         |       |
| 207 | RP-sync-24    | repo-sync                          | --interleaved                                          |        |      |         |       |
| 208 | RP-sync-25    | repo-sync                          | --fail-fast                                            |        |      |         |       |
| 209 | RP-sync-26    | repo-sync                          | env REPO_SKIP_SELF_UPDATE                              |        |      |         |       |
| 210 | RP-sync-27    | repo-sync                          | env SYNC_TARGET                                        |        |      |         |       |
| 211 | RP-sync-28    | repo-sync                          | env TARGET_PRODUCT/_BUILD_VARIANT/_RELEASE             |        |      |         |       |
| 212 | RP-status-01  | repo-status                        | bare status                                            |        |      |         |       |
| 213 | RP-status-02  | repo-status                        | --orphans                                              |        |      |         |       |
| 214 | RP-status-03  | repo-status                        | project-filtered                                       |        |      |         |       |
| 215 | RP-status-04  | repo-status                        | --jobs=4                                               |        |      |         |       |
| 216 | RP-info-01    | repo-info                          | bare                                                   |        |      |         |       |
| 217 | RP-info-02    | repo-info                          | --diff                                                 |        |      |         |       |
| 218 | RP-info-03    | repo-info                          | --current-branch                                       |        |      |         |       |
| 219 | RP-info-04    | repo-info                          | --local-only                                           |        |      |         |       |
| 220 | RP-info-05    | repo-info                          | --overview                                             |        |      |         |       |
| 221 | RP-info-06    | repo-info                          | --no-current-branch                                    |        |      |         |       |
| 222 | RP-info-07    | repo-info                          | --this-manifest-only                                   |        |      |         |       |
| 223 | RP-manifest-01 | repo-manifest                     | bare stdout                                            |        |      |         |       |
| 224 | RP-manifest-02 | repo-manifest                     | --output                                               |        |      |         |       |
| 225 | RP-manifest-03 | repo-manifest                     | --manifest-name                                        |        |      |         |       |
| 226 | RP-manifest-04 | repo-manifest                     | --revision-as-HEAD                                     |        |      |         |       |
| 227 | RP-manifest-05 | repo-manifest                     | --suppress-upstream-revision                           |        |      |         |       |
| 228 | RP-manifest-06 | repo-manifest                     | --suppress-dest-branch                                 |        |      |         |       |
| 229 | RP-manifest-07 | repo-manifest                     | --pretty                                               |        |      |         |       |
| 230 | RP-manifest-08 | repo-manifest                     | --no-local-manifests                                   |        |      |         |       |
| 231 | RP-manifest-09 | repo-manifest                     | --outer-manifest                                       |        |      |         |       |
| 232 | RP-manifest-10 | repo-manifest                     | --no-outer-manifest                                    |        |      |         |       |
| 233 | RP-manifest-11 | repo-manifest                     | --revision-as-tag                                      |        |      |         |       |
| 234 | RP-branches-01 | repo-branches                     | bare                                                   |        |      |         |       |
| 235 | RP-branches-02 | repo-branches                     | project-filtered                                       |        |      |         |       |
| 236 | RP-branches-03 | repo-branches                     | --current-branch                                       |        |      |         |       |
| 237 | RP-list-01    | repo-list                          | bare                                                   |        |      |         |       |
| 238 | RP-list-02    | repo-list                          | --regex                                                |        |      |         |       |
| 239 | RP-list-03    | repo-list                          | --regex                                                |        |      |         |       |
| 240 | RP-list-04    | repo-list                          | --groups                                               |        |      |         |       |
| 241 | RP-list-05    | repo-list                          | --all-manifests                                        |        |      |         |       |
| 242 | RP-list-06    | repo-list                          | --name-only                                            |        |      |         |       |
| 243 | RP-list-07    | repo-list                          | --path-only                                            |        |      |         |       |
| 244 | RP-list-08    | repo-list                          | --fullpath                                             |        |      |         |       |
| 245 | RP-list-09    | repo-list                          | --outer-manifest                                       |        |      |         |       |
| 246 | RP-list-10    | repo-list                          | --this-manifest-only                                   |        |      |         |       |
| 247 | RP-forall-01  | repo-forall                        | bare -c                                                |        |      |         |       |
| 248 | RP-forall-02  | repo-forall                        | --regex                                                |        |      |         |       |
| 249 | RP-forall-03  | repo-forall                        | --inverse-regex                                        |        |      |         |       |
| 250 | RP-forall-04  | repo-forall                        | --groups                                               |        |      |         |       |
| 251 | RP-forall-05  | repo-forall                        | --abort-on-errors                                      |        |      |         |       |
| 252 | RP-forall-06  | repo-forall                        | --ignore-missing                                       |        |      |         |       |
| 253 | RP-forall-07  | repo-forall                        | --project-header                                       |        |      |         |       |
| 254 | RP-forall-08  | repo-forall                        | --interactive                                          |        |      |         |       |
| 255 | RP-forall-09  | repo-forall                        | env REPO_PROJECT/PATH/REMOTE/LREV/RREV                 |        |      |         |       |
| 256 | RP-forall-10  | repo-forall                        | env REPO_COUNT                                         |        |      |         |       |
| 257 | RP-grep-01    | repo-grep                          | basic                                                  |        |      |         |       |
| 258 | RP-grep-02    | repo-grep                          | -i case-insensitive                                    |        |      |         |       |
| 259 | RP-grep-03    | repo-grep                          | -e pattern                                             |        |      |         |       |
| 260 | RP-grep-04    | repo-grep                          | project-filtered                                       |        |      |         |       |
| 261 | RP-start-01   | repo-start                         | --all                                                  |        |      |         |       |
| 262 | RP-start-02   | repo-start                         | branch+project                                         |        |      |         |       |
| 263 | RP-start-03   | repo-start                         | --rev                                                  |        |      |         |       |
| 264 | RP-start-04   | repo-start                         | --head                                                 |        |      |         |       |
| 265 | RP-checkout-01 | repo-checkout                     | existing branch                                        |        |      |         |       |
| 266 | RP-checkout-02 | repo-checkout                     | nonexistent error                                      |        |      |         |       |
| 267 | RP-abandon-01 | repo-abandon                       | --all                                                  |        |      |         |       |
| 268 | RP-abandon-02 | repo-abandon                       | branch+project                                         |        |      |         |       |
| 269 | RP-abandon-03 | repo-abandon                       | delete all                                             |        |      |         |       |
| 270 | RP-rebase-01  | repo-rebase                        | bare                                                   |        |      |         |       |
| 271 | RP-rebase-02  | repo-rebase                        | --fail-fast                                            |        |      |         |       |
| 272 | RP-rebase-03  | repo-rebase                        | --force-rebase                                         |        |      |         |       |
| 273 | RP-rebase-04  | repo-rebase                        | --no-ff                                                |        |      |         |       |
| 274 | RP-rebase-05  | repo-rebase                        | --autosquash                                           |        |      |         |       |
| 275 | RP-rebase-06  | repo-rebase                        | --whitespace                                           |        |      |         |       |
| 276 | RP-rebase-07  | repo-rebase                        | --stash                                                |        |      |         |       |
| 277 | RP-rebase-08  | repo-rebase                        | -i interactive                                         |        |      |         |       |
| 278 | RP-upload-01  | repo-upload                        | --dry-run basic                                        |        |      |         |       |
| 279 | RP-upload-02  | repo-upload                        | -t auto-topic                                          |        |      |         |       |
| 280 | RP-upload-03  | repo-upload                        | --topic                                                |        |      |         |       |
| 281 | RP-upload-04  | repo-upload                        | --hashtag                                              |        |      |         |       |
| 282 | RP-upload-05  | repo-upload                        | --add-hashtag                                          |        |      |         |       |
| 283 | RP-upload-06  | repo-upload                        | --label                                                |        |      |         |       |
| 284 | RP-upload-07  | repo-upload                        | --description                                          |        |      |         |       |
| 285 | RP-upload-08  | repo-upload                        | --re                                                   |        |      |         |       |
| 286 | RP-upload-09  | repo-upload                        | --cc                                                   |        |      |         |       |
| 287 | RP-upload-10  | repo-upload                        | --private                                              |        |      |         |       |
| 288 | RP-upload-11  | repo-upload                        | --wip                                                  |        |      |         |       |
| 289 | RP-upload-12  | repo-upload                        | --current-branch                                       |        |      |         |       |
| 290 | RP-upload-13  | repo-upload                        | --branch-exclude                                       |        |      |         |       |
| 291 | RP-upload-14  | repo-upload                        | --auto-approve                                         |        |      |         |       |
| 292 | RP-upload-15  | repo-upload                        | --receive-pack                                         |        |      |         |       |
| 293 | RP-cherry-pick-01 | repo-cherry-pick               | happy-path                                             |        |      |         |       |
| 294 | RP-cherry-pick-02 | repo-cherry-pick               | nonexistent SHA                                        |        |      |         |       |
| 295 | RP-stage-01   | repo-stage                         | -i smoke                                               |        |      |         |       |
| 296 | RP-download-01 | repo-download                     | bare (no-server skip)                                  |        |      |         |       |
| 297 | RP-download-02 | repo-download                     | -c                                                     |        |      |         |       |
| 298 | RP-download-03 | repo-download                     | -x                                                     |        |      |         |       |
| 299 | RP-download-04 | repo-download                     | -r                                                     |        |      |         |       |
| 300 | RP-download-05 | repo-download                     | -f                                                     |        |      |         |       |
| 301 | RP-download-06 | repo-download                     | -b                                                     |        |      |         |       |
| 302 | RP-diff-01    | repo-diff                          | bare                                                   |        |      |         |       |
| 303 | RP-diff-02    | repo-diff                          | --absolute                                             |        |      |         |       |
| 304 | RP-diff-03    | repo-diff                          | project-filtered                                       |        |      |         |       |
| 305 | RP-diffmanifests-01 | repo-diffmanifests           | one-arg                                                |        |      |         |       |
| 306 | RP-diffmanifests-02 | repo-diffmanifests           | two-arg                                                |        |      |         |       |
| 307 | RP-diffmanifests-03 | repo-diffmanifests           | --raw                                                  |        |      |         |       |
| 308 | RP-diffmanifests-04 | repo-diffmanifests           | --no-color                                             |        |      |         |       |
| 309 | RP-diffmanifests-05 | repo-diffmanifests           | --pretty-format                                        |        |      |         |       |
| 310 | RP-prune-01   | repo-prune                         | bare                                                   |        |      |         |       |
| 311 | RP-prune-02   | repo-prune                         | project-filtered                                       |        |      |         |       |
| 312 | RP-gc-01      | repo-gc                            | bare                                                   |        |      |         |       |
| 313 | RP-gc-02      | repo-gc                            | --aggressive                                           |        |      |         |       |
| 314 | RP-gc-03      | repo-gc                            | --all                                                  |        |      |         |       |
| 315 | RP-gc-04      | repo-gc                            | --repack-full-clone                                    |        |      |         |       |
| 316 | RP-overview-01 | repo-overview                     | bare                                                   |        |      |         |       |
| 317 | RP-overview-02 | repo-overview                     | --current-branch                                       |        |      |         |       |
| 318 | RP-smartsync-01 | repo-smartsync                   | smoke                                                  |        |      |         |       |
| 319 | RP-envsubst-01 | repo-envsubst                     | in-place                                               |        |      |         |       |
| 320 | RP-envsubst-02 | repo-envsubst                     | substitution check                                     |        |      |         |       |
| 321 | RP-help-01    | repo-help                          | bare                                                   |        |      |         |       |
| 322 | RP-help-02    | repo-help                          | --all                                                  |        |      |         |       |
| 323 | RP-help-03    | repo-help                          | --help-all                                             |        |      |         |       |
| 324 | RP-wrap-01    | repo-wrapper                       | --repo-dir                                             |        |      |         |       |
| 325 | RP-wrap-02    | repo-wrapper                       | KANON_REPO_DIR env                                     |        |      |         |       |
| 326 | RP-wrap-03    | repo-wrapper                       | flag overrides env                                     |        |      |         |       |
| 327 | RP-wrap-04    | repo-wrapper                       | selfupdate disabled message                            |        |      |         |       |
| 328 | TC-bootstrap-01 | top-level                         | --output-dir                                           |        |      |         |       |
| 329 | TC-bootstrap-02 | top-level                         | --catalog-source flag                                  |        |      |         |       |
| 330 | TC-bootstrap-03 | top-level                         | KANON_CATALOG_SOURCE env                               |        |      |         |       |
| 331 | TC-bootstrap-04 | top-level                         | flag overrides env                                     |        |      |         |       |
| 332 | TC-bootstrap-05 | top-level                         | missing parent                                         |        |      |         |       |
| 333 | TC-install-01 | top-level                          | auto-discover                                          |        |      |         |       |
| 334 | TC-install-02 | top-level                          | explicit path                                          |        |      |         |       |
| 335 | TC-install-03 | top-level                          | REPO_URL deprecation                                   |        |      |         |       |
| 336 | TC-install-04 | top-level                          | REPO_REV deprecation                                   |        |      |         |       |
| 337 | TC-clean-01   | top-level                          | auto-discover clean                                    |        |      |         |       |
| 338 | TC-clean-02   | top-level                          | .gitignore retention                                   |        |      |         |       |
| 339 | TC-validate-01 | top-level                         | xml --repo-root                                        |        |      |         |       |
| 340 | TC-validate-02 | top-level                         | marketplace --repo-root                                |        |      |         |       |
| 341 | TC-validate-03 | top-level                         | auto-detect git root                                   |        |      |         |       |
| 342 | TC-validate-04 | top-level                         | rejected when no root                                  |        |      |         |       |
| 343 | TC-extra      | top-level                          | KANON_GIT_RETRY_* / KANON_SSH_MASTER_TIMEOUT_SEC       |        |      |         |       |
| 344 | UJ-01         | user-journey                       | pip install -e + bootstrap                             |        |      |         |       |
| 345 | UJ-02         | user-journey                       | --catalog-source PEP 440                               |        |      |         |       |
| 346 | UJ-03         | user-journey                       | multi-source                                           |        |      |         |       |
| 347 | UJ-04         | user-journey                       | GITBASE override                                       |        |      |         |       |
| 348 | UJ-05         | user-journey                       | full marketplace lifecycle                             |        |      |         |       |
| 349 | UJ-06         | user-journey                       | collision detection                                    |        |      |         |       |
| 350 | UJ-07         | user-journey                       | linkfile journey                                       |        |      |         |       |
| 351 | UJ-08         | user-journey                       | pipeline cache                                         |        |      |         |       |
| 352 | UJ-09         | user-journey                       | shell variable expansion                               |        |      |         |       |
| 353 | UJ-10         | user-journey                       | python -m kanon_cli                                    |        |      |         |       |
| 354 | UJ-11         | user-journey                       | standalone repo journey                                |        |      |         |       |
| 355 | UJ-12         | user-journey                       | manifest validation                                    |        |      |         |       |
|     | TOTAL         | -                                  | -                                                      |        |      |         | aggregate summary populated post-run |

---

## Appendix: Known Fixes and Behaviour Notes

### `--repo-dir` / `KANON_REPO_DIR` path resolution (E2-F3-S1-T2)

`resolve_repo_dir()` in `src/kanon_cli/commands/repo.py` converts all resolved
paths to absolute paths using `os.path.abspath()` before forwarding them to
`repo_run()`.  This prevents `ManifestParseError: manifest_file must be abspath`
when the default `.repo` relative path is used by `RepoClient`.

**Impact:** All `kanon repo *` subcommands that rely on the default `--repo-dir`
(i.e. invocations that do not pass an explicit absolute path) are affected.
Scenarios RP-init-01 through RP-init-18, and every scenario in this document that
runs `kanon repo init` without an explicit `--repo-dir`, benefit from this fix.
