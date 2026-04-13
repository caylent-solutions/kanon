# Pipeline Integration

How to use Kanon tasks in CI/CD pipelines.

## Overview

Kanon tasks map to CI/CD pipeline stages. Gradle projects use `./gradlew` tasks; Make projects use `make` targets. Both can run stages in parallel for faster pipelines.

## GitHub Actions — Gradle Example

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
      - uses: actions/setup-java@v4
        with:
          distribution: 'temurin'
          java-version: '17'
      - name: Kanon Install
        run: ./gradlew kanonInstall
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
      - run: ./gradlew build

  checkstyle:
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
      - run: ./gradlew checkstyleMain

  unit-test:
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
      - run: ./gradlew unitTest jacocoTestReport

  integration-test:
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
      - run: ./gradlew integrationTest

  security:
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
      - run: ./gradlew securityCheck

  sonarqube:
    needs: [unit-test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/cache/restore@v4
        with:
          path: |
            .packages
            .repo
          key: kanon-packages-${{ hashFiles('.kanon') }}
      - run: ./gradlew sonar
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
```

## GitHub Actions — Make Example

For Make-based projects, the CI/QA/Release workflows in this repository
(`.github/workflows/`) delegate to Makefile targets via a shared composite
action (`.github/actions/setup/`):

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  ci:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup
      - name: Lint Python
        shell: bash
        run: make lint-python
      - name: Lint Markdown
        shell: bash
        run: make lint-markdown
      - name: Lint YAML
        shell: bash
        run: make lint-yaml
      - name: Lint XML
        shell: bash
        run: make lint-xml
      - name: Format check
        shell: bash
        run: make format-check
      - name: Test
        shell: bash
        run: make test
```

The shared composite action sets up Python and installs dependencies,
keeping workflow files minimal. Each validation runs as a discrete step
so failures are immediately visible. All `run` steps use `shell: bash`.

## Overriding GITBASE in Pipelines

CI/CD pipelines can override `GITBASE` to use internal Git mirrors:

```yaml
- name: Kanon Install (Gradle)
  run: ./gradlew kanonInstall
  env:
    GITBASE: https://git.internal.company.com/kanon-packages/

```

The `.kanon` value is overridden by the environment variable. No file changes needed.
