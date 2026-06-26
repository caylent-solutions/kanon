# Pipeline Integration

How to use Kanon in CI/CD pipelines.

## Overview

Kanon integrates with CI/CD pipelines via the `kanon install` and `kanon clean` CLI commands. These commands map to pipeline stages and can be cached for faster subsequent runs. Projects that use a task runner can optionally wrap these commands in task runner targets.

## GitHub Actions Example

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  kanon-install:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install kanon-cli
        shell: bash
        run: pipx install kanon-cli
      - name: Kanon Install
        shell: bash
        run: kanon install .kanon
      - uses: actions/cache/save@v4
        with:
          path: |
            ~/.kanon
          key: kanon-store-${{ hashFiles('.kanon.lock') }}

  build:
    needs: kanon-install
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/cache/restore@v4
        with:
          path: |
            ~/.kanon
          key: kanon-store-${{ hashFiles('.kanon.lock') }}
      - name: Run tests
        shell: bash
        run: echo "Run your project tests here"

  cleanup:
    needs: [build]
    runs-on: ubuntu-latest
    if: always()
    steps:
      - uses: actions/checkout@v4
      - name: Install kanon-cli
        shell: bash
        run: pipx install kanon-cli
      - name: Kanon Clean
        shell: bash
        run: kanon clean .kanon
```

## Where install artifacts live

`kanon install` writes its fetched data into the shared `KANON_HOME` store
(`$KANON_HOME`, default `~/.kanon`), content-addressed and deduped across
projects. Cache that directory between runs (keyed on `.kanon.lock`) to
avoid re-cloning; the example above caches `~/.kanon`. Set `KANON_HOME`
(or the `--home` / `--store-dir` flag) to relocate the store, for example
to a path that your CI runner caches by default.

## Overriding the org base in pipelines

Each dependency carries its own org base in
`KANON_SOURCE_<alias>_GITBASE` inside `.kanon`. To point a dependency at an
internal Git mirror without editing the committed file, override that
dependency's `KANON_SOURCE_<alias>_GITBASE` via an environment variable
(environment variables take precedence over `.kanon` file values):

```yaml
- name: Kanon Install
  shell: bash
  run: kanon install .kanon
  env:
    KANON_SOURCE_my_dep_GITBASE: https://git.internal.company.com/kanon-packages
```

The `.kanon` value is overridden by the environment variable. No file changes needed.
