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
        run: pip install kanon-cli
      - name: Kanon Install
        shell: bash
        run: kanon install .kanon
      - uses: actions/cache/save@v4
        with:
          path: |
            .packages
            .repo
          key: kanon-packages-${{ hashFiles('.kanon') }}

  build:
    needs: kanon-install
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/cache/restore@v4
        with:
          path: |
            .packages
            .repo
          key: kanon-packages-${{ hashFiles('.kanon') }}
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
        run: pip install kanon-cli
      - name: Kanon Clean
        shell: bash
        run: kanon clean .kanon
```

## Overriding GITBASE in Pipelines

CI/CD pipelines can override `GITBASE` to use internal Git mirrors:

```yaml
- name: Kanon Install
  shell: bash
  run: kanon install .kanon
  env:
    GITBASE: https://git.internal.company.com/kanon-packages/
```

The `.kanon` value is overridden by the environment variable. No file changes needed.
