# Privacy & Telemetry

kanon emits one usage-telemetry event per command so the maintainers can
understand which commands are used, which package sources are installed, and
where failures occur. This page documents exactly what is collected, why, how it
is protected in transit and at rest, and how to turn it off.

## Design principles

- **On by default.** Telemetry is enabled out of the box for every user. There
  is no opt-in prompt, no first-run consent gate, and no enable toggle.
- **Silent and non-blocking.** The event payload is built in the foreground from
  local git and lockfile reads only (no network). The actual HTTPS POST is fired
  in a detached background process, so your command is never blocked, delayed on
  the network, or failed by telemetry. A happy-path command prints nothing about
  telemetry on stdout or stderr.
- **Never-fail.** Any telemetry error (payload build, serialisation, or network)
  is swallowed for this best-effort feature and, where possible, recorded in a
  background error log (`${KANON_HOME}/cache/telemetry-errors.log`). It never
  surfaces to your command.
- **Zero secrets by construction.** Only an explicit allowlist of kanon-computed
  fields is serialised. Raw argv is never emitted. SSH/private keys, tokens,
  credentials, key files, `~/.ssh`, environment-variable values, and file
  contents are never read or emitted. Every git/source URL is credential-stripped
  (any `user:pass@` / `token@` userinfo is dropped; host, org, and repo are kept)
  before it is serialised.

## What is collected

Each event is a single OTLP/HTTP log record whose body is a flat JSON object with
four top-level keys -- `tool` (always `kanon`), `timestamp`, `event_type`
(always `cli_command`), and `payload`. The rich fields ride inside `payload`:

| Field | Where | Collected? | Why / notes |
|-------|-------|-----------|-------------|
| `tool` = `kanon`, `timestamp`, `event_type` = `cli_command` | body | Yes | Routing and partitioning; `tool` is the partition key. |
| `schema_version`, `run_id` | payload | Yes | Payload schema version and a per-invocation random id (a fresh UUID each run -- never a stable device or user id). |
| `environment`: `kanon_version`, `python_version`, `os`, `arch`, `install_type`, `is_ci` | payload | Yes | Understand the runtime mix (versions, platform, wheel/editable/source install, CI vs interactive). No hostname, username, or path. |
| `invocation`: `command`, `subcommand`, boolean flag **names**, allowlisted flag **values** | payload | Yes | Which command/subcommand ran and which boolean flags were set (names only). Only closed-domain values (e.g. `--format text|json`) are recorded. Never raw argv. |
| `outcome`: `exit_code`, `status`, `error_type`, `duration_ms` | payload | Yes | Success/failure rates and latency. `error_type` is the exception **class name** only -- never a message or traceback. |
| `git`: `user_email`, `remote_host`, `org`, `repo`, `branch` | payload | Yes | Attribute usage to a team/repo. The remote URL is **credential-stripped**; only host/org/repo are kept. |
| `install_graph` (on `kanon install`) | payload | Yes | The complete resolved graph: per direct source (`alias`, `name`, `manifest_url`, `ref_spec`, `resolved_ref`, `resolved_sha`, `registered_marketplaces`) plus its transitive `projects[]` (`name`, `url`, `canonical_url`, `resolved_ref`, `resolved_sha`) and the include chain. All URLs credential-stripped. |
| `installed_packages[]` (on `kanon install`) | payload | Yes | Flattened list of every direct source (`scope: direct`) and every transitive repo package (`scope: transitive`) with `name`, `url`, and `sha` -- easy analytics of what was installed. |
| Raw argv, non-allowlisted or secret-capable flag values | -- | **Never** | -- |
| SSH/private keys, tokens, credentials, key files, `~/.ssh`, env-var values | -- | **Never** | Never read or emitted. |
| Source code, file contents, full local file paths | -- | **Never** | -- |
| Error messages / stack traces | -- | **Never** | Exception class name only. |

The serialised install graph is capped well under the collector's body limit. If
a graph is very large it is dropped in favour of the flattened
`installed_packages[]` summary plus `install_graph_truncated: true`, so the fact
that packages were installed is never lost.

## Encryption

- **In transit:** the event is POSTed over HTTPS/TLS to the collector. The
  emitter enforces an HTTPS-only guard and refuses any non-`https://` endpoint.
- **At rest:** the collector stores events in an S3-backed data lake encrypted
  with a customer-managed KMS key (SSE-KMS).

## How to turn it off

Set the environment variable `KANON_TELEMETRY_DISABLED` to a truthy value
(`1`, `true`, `yes`, or `on`). This is the **only** opt-out -- there is no
`--no-telemetry` flag.

```bash
# Disable telemetry for the whole session
export KANON_TELEMETRY_DISABLED=1

# Or for a single command
KANON_TELEMETRY_DISABLED=1 kanon install .kanon
```

## Inspecting exactly what is sent

Use the `--telemetry-debug` global flag (or `KANON_TELEMETRY_DEBUG=1`) to print
the exact JSON that would be sent to stderr. This does not change the
non-blocking send behaviour; it only surfaces the payload so you can audit it.

```bash
kanon --telemetry-debug install .kanon
```

## Related configuration

See [docs/configuration.md](configuration.md#usage-telemetry) for the full list
of telemetry environment variables (endpoint override, timeouts, size caps, and
the error-log path) and [docs/cli-reference.md](cli-reference.md#global-flags)
for the global flags.
