# Contributing to RPM CLI

Thank you for your interest in contributing to the RPM CLI! This document provides guidelines and instructions for contributing to this project.

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/caylent-solutions/rpm.git
   cd rpm
   ```

2. Install development dependencies:
   ```bash
   make install-dev
   ```

3. Set up git hooks to ensure code quality:
   ```bash
   make install-hooks
   ```

   This will:
   - Install pre-commit hooks (secrets detection, formatting, YAML validation)
   - Set up a pre-push hook that runs lint + tests before pushing

4. Run tests to verify your setup:
   ```bash
   make test
   ```

## Code Style and Quality

We use the following tools to maintain code quality:

- **Ruff**: For code formatting and linting
- **yamllint**: For YAML validation and formatting
- **pre-commit**: For automated checks on commit

Before submitting a pull request, ensure your code passes all checks:

```bash
make lint
```

To auto-fix formatting issues:

```bash
make format
```

To run all pre-commit checks:

```bash
make pre-commit-check
```

## Commit Message Conventions

This project follows [Conventional Commits](https://www.conventionalcommits.org/) for commit messages. This enables automatic semantic versioning and changelog generation.

### How Version Bumps Work

**The PR title is the single most important thing for versioning.**

When a PR is squash-merged to `main`, GitHub generates a squash commit whose title is the PR title. `python-semantic-release` reads that squash commit to determine the version bump. This means:

1. Your **PR title** must follow the conventional commit format
2. Individual commit messages on your branch can be anything (but conventional format is recommended)
3. The squash commit title (= PR title) drives the version bump

### Commit Message Format

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Supported Commit Types

| Type | Description | Version Bump | Example |
|------|-------------|--------------|---------|
| `feat` | New feature | **Minor** (0.1.0 -> 0.2.0) | `feat: add new command option` |
| `fix` | Bug fix | **Patch** (0.1.0 -> 0.1.1) | `fix: resolve parsing error` |
| `perf` | Performance improvement | **Patch** (0.1.0 -> 0.1.1) | `perf: optimize file processing` |
| `security` | Security fix | **Patch** (0.1.0 -> 0.1.1) | `security: fix path traversal vulnerability` |
| `revert` | Revert previous change | **Patch** (0.1.0 -> 0.1.1) | `revert: undo feature X implementation` |
| `build` | Build system changes | No bump | `build: update dependencies` |
| `chore` | Maintenance tasks | No bump | `chore: update documentation` |
| `ci` | CI/CD changes | No bump | `ci: add workflow caching` |
| `docs` | Documentation changes | No bump | `docs: update API examples` |
| `refactor` | Code refactoring | No bump | `refactor: simplify error handling` |
| `style` | Code style changes | No bump | `style: fix formatting` |
| `test` | Test changes | No bump | `test: add unit tests for parser` |

### Breaking Changes

Any commit type with `!` suffix OR `BREAKING CHANGE:` in the footer triggers a **Major** version bump (0.1.0 -> 1.0.0):

```
feat!: change CLI interface

BREAKING CHANGE: The configure command now requires explicit manifest path argument
```

### Examples

- `feat: add support for custom templates`
- `fix: handle missing configuration files gracefully`
- `perf: cache parsed templates for improved performance`
- `docs: add troubleshooting section to README`
- `chore(deps): update semantic-release to v9.0.0`

## Testing

### Unit Tests

Unit tests are located in the `tests/unit` directory. They test individual components in isolation.

```bash
make test-unit
```

### Functional Tests

Functional tests are located in the `tests/functional` directory. They test the CLI commands as used by actual users.

```bash
make test-functional
```

### Test Requirements

- **Unit Tests**: Must maintain at least 85% code coverage
- **Functional Tests**: Must test all CLI commands and common error scenarios
- All tests must pass before merging

### Running All Tests

```bash
make test
```

### Coverage Report

```bash
make test-cov
```

## Pull Request Process

### Branch Naming

Use descriptive branch names with type prefixes:
- `feat/add-export-command`
- `fix/handle-empty-config`
- `docs/update-readme`

### Steps

1. Pull `main`: `git checkout main && git pull`
2. Create a new branch: `git checkout -b feat/my-change`
3. Implement your changes with appropriate tests
4. Ensure all tests pass: `make test`
5. Ensure lint passes: `make lint`
6. Commit and push: `git add <files> && git commit -m "feat: description" && git push`
7. Open a PR to `main`
   - **Set the PR title** using conventional commit format (this drives the version bump!)
   - Request review from code owners
8. Address review feedback
9. PR will be **squash-merged** to `main`

### PR Title Format

The PR title **must** follow conventional commit format because it becomes the squash commit message that drives semantic versioning:

- `feat: add new bootstrap template` -> triggers MINOR bump
- `fix(configure): handle missing rpmenv` -> triggers PATCH bump
- `docs: update CLI reference` -> no version bump
- `feat!: redesign manifest format` -> triggers MAJOR bump

## Release Process

The release pipeline is fully automated. When changes are merged to `main`:

1. Main branch validation runs (lint, tests, security scan)
2. A manual QA approval gate pauses the pipeline
3. After QA approval, `python-semantic-release` computes the next version from commit messages
4. The pipeline generates a changelog, updates version files, creates a release PR, merges it, tags the release, and triggers PyPI publishing

**You do not need to manually bump versions, update changelogs, or create tags.** The pipeline handles all of this based on your PR title's conventional commit prefix.

## Adding New Features

When adding new features:

1. Create unit tests for all new code
2. Create functional tests that test the feature from a user perspective
3. Update documentation in the README.md if user-facing behavior changes
4. Update help text in the CLI commands
