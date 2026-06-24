# Git Authentication Setup

This document explains how to configure your local git client so that
`git clone` and `git ls-remote` -- the two git operations kanon calls
internally -- succeed against private repositories.

## Scope

kanon does NOT handle credentials. It inherits the operator's local git
configuration (`~/.gitconfig`, credential helpers, SSH agent,
`url.insteadOf` rewrites) and delegates every authentication decision to
the operator's git client.

This document is a how-to for setting up that local git config so that the
git operations kanon invokes succeed. Auth setup is the operator's
responsibility. kanon never prompts for a password, never stores a token,
and never contacts an authentication provider directly.

See [`docs/security-model.md`](security-model.md) for the full trust-model
rationale and [`docs/troubleshooting.md`](troubleshooting.md) for common
authentication error messages and their fixes.

## macOS

### HTTPS via credential helpers

macOS ships with the `osxkeychain` credential helper, which stores
credentials in the system Keychain.

**Enable osxkeychain (native):**

```sh
git config --global credential.helper osxkeychain
```

The first time you authenticate against a host the OS Keychain dialog
appears and stores the credential. Subsequent operations are silent.

**OAuth via git-credential-oauth:**

`git-credential-oauth` exchanges an OAuth device-flow or browser-based flow
for a short-lived token and caches it using the system keychain.

```sh
# Install (Homebrew)
brew install git-credential-oauth

# Configure as the preferred helper; fall back to osxkeychain for storage
git config --global credential.helper "cache --timeout=7200"
git config --global --add credential.helper oauth
```

**PAT via the keychain:**

Store a Personal Access Token (PAT) once using `git credential approve`:

```sh
git credential approve <<EOF
protocol=https
host=git.example.com
username=<your-username>
password=<your-pat>
EOF
```

macOS Keychain stores the entry; subsequent `git clone` calls for
`git.example.com` retrieve it automatically.

### SSH via ~/.ssh/config + ssh-agent

Generate a key and add it to your SSH agent:

```sh
ssh-keygen -t ed25519 -C "<label>" -f ~/.ssh/id_git_example
ssh-add ~/.ssh/id_git_example
```

Configure `~/.ssh/config` to use the key for a specific host:

```text
Host git.example.com
    HostName git.example.com
    User git
    IdentityFile ~/.ssh/id_git_example
    AddKeysToAgent yes
    UseKeychain yes
```

On macOS, `ssh-add --apple-use-keychain ~/.ssh/id_git_example` stores the
passphrase in the system Keychain so the key survives reboots without
re-entering the passphrase.

### url.insteadOf

`url.insteadOf` rewrites let you remap one transport to another without
touching individual repository URLs:

```sh
# Rewrite HTTPS to SSH for a specific host
git config --global url."git@git.example.com:".insteadOf "https://git.example.com/"

# Rewrite SSH to HTTPS (useful in environments without outbound SSH)
git config --global url."https://git.example.com/".insteadOf "git@git.example.com:"
```

### Clean-slate procedure (macOS)

If you suspect a stale or incorrect credential is blocking access on macOS:

1. Open **Keychain Access** and search for the host name.
2. Delete any matching internet-password entries.
3. Run `git credential reject` to clear the git credential cache:

   ```sh
   git credential reject <<EOF
   protocol=https
   host=git.example.com
   EOF
   ```

4. Re-authenticate by running:

   ```sh
   git ls-remote https://git.example.com/<repo>.git
   ```

## Linux

### HTTPS via credential helpers

Linux provides several credential helper options depending on the desktop
environment and distribution.

**git-credential-libsecret (GNOME Keyring / KWallet):**

```sh
# Install (Debian/Ubuntu)
sudo apt-get install git libsecret-1-dev
sudo make --directory /usr/share/doc/git/contrib/credential/libsecret

# Configure
git config --global credential.helper \
    /usr/share/doc/git/contrib/credential/libsecret/git-credential-libsecret
```

On Fedora/RHEL, install `git-credential-libsecret` from the distribution
package manager and set the helper path accordingly.

**Git Credential Manager (GCM):**

GCM is a cross-platform helper that supports OAuth, PAT, and device-flow
authentication. It stores credentials in the system secret store.

```sh
# Install via package manager or from the GCM releases page.
# After installation, run:
git-credential-manager configure
```

GCM sets `credential.helper=manager` in `~/.gitconfig` automatically.

**OAuth via git-credential-oauth:**

```sh
# Install (Debian/Ubuntu -- adjust for your distribution)
sudo apt-get install git-credential-oauth

# Configure
git config --global credential.helper oauth
```

### SSH via ~/.ssh/config + ssh-agent

Generate a key and start the agent:

```sh
ssh-keygen -t ed25519 -C "<label>" -f ~/.ssh/id_git_example
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_git_example
```

Add to `~/.ssh/config`:

```text
Host git.example.com
    HostName git.example.com
    User git
    IdentityFile ~/.ssh/id_git_example
    AddKeysToAgent yes
```

To start the agent automatically, add the `eval "$(ssh-agent -s)"` and
`ssh-add` lines to `~/.bashrc` or `~/.zshrc`, or use a systemd user unit
for `ssh-agent`.

### url.insteadOf

```sh
# Rewrite HTTPS to SSH for a specific host
git config --global url."git@git.example.com:".insteadOf "https://git.example.com/"

# Rewrite SSH to HTTPS
git config --global url."https://git.example.com/".insteadOf "git@git.example.com:"
```

### Clean-slate procedure (Linux)

To clear a stale credential on Linux:

1. If using `libsecret` or GCM, open your system secret manager
   (e.g., GNOME Keyring via `seahorse`) and delete entries for the host.

2. Run `git credential reject`:

   ```sh
   git credential reject <<EOF
   protocol=https
   host=git.example.com
   EOF
   ```

3. If the credential helper is `store` (plain-text file at
   `~/.git-credentials`), remove the relevant line:

   ```sh
   git credential-store erase <<EOF
   protocol=https
   host=git.example.com
   EOF
   ```

4. Re-authenticate by running:

   ```sh
   git ls-remote https://git.example.com/<repo>.git
   ```

## Windows (not currently supported -- use WSL2)

Windows is **not currently supported (planned)**: native Windows support is
on the roadmap but not yet available. In the meantime, run kanon under WSL2
(Windows Subsystem for Linux) and follow the [Linux](#linux) git-auth
instructions above -- inside a WSL2 distribution, kanon and git behave
exactly as they do on Linux, including credential helpers, `ssh-agent`, and
`url.insteadOf` rewrites.

See the README [Platform support](../README.md#platform-support) note for
the project-wide statement of supported platforms.

## Per-host configuration patterns

When you need different credentials for different hosts -- for example, a
PAT for one internal host and OAuth for another -- use
`[credential "https://<host>"]` blocks in `~/.gitconfig` and
`Host <host>` blocks in `~/.ssh/config`.

**HTTPS credential helper per host (`~/.gitconfig`):**

```ini
[credential "https://git.example.com"]
    helper = /path/to/credential-helper-for-example

[credential "https://internal.example.org"]
    helper = manager
```

Git evaluates credential sections from most-specific to least-specific, so
a host-scoped block takes precedence over the global `[credential]` block.

**SSH key per host (`~/.ssh/config`):**

```text
Host git.example.com
    HostName git.example.com
    User git
    IdentityFile ~/.ssh/id_example_com

Host internal.example.org
    HostName internal.example.org
    User git
    IdentityFile ~/.ssh/id_internal
```

**url.insteadOf per host (`~/.gitconfig`):**

```ini
[url "git@git.example.com:"]
    insteadOf = https://git.example.com/

[url "https://internal.example.org/"]
    insteadOf = git@internal.example.org:
```

Multiple `[url "..."]` blocks coexist; git applies the first match for each
URL it encounters.

## kanon never handles credentials

kanon enforces a strict no-credential-handling invariant (spec Section 3.6):

- kanon NEVER prompts for a password or token.
- kanon NEVER caches credentials.
- kanon NEVER reads credentials from any source other than by delegating to
  the operator's git client.
- kanon NEVER calls provider HTTP APIs or provider CLIs.

When a `git clone` or `git ls-remote` call fails with an authentication
error, kanon propagates the raw git stderr verbatim to its own stderr,
prefixed with:

```text
ERROR: git authentication failed against <url>. See docs/git-auth-setup.md.
```

kanon then exits with a non-zero exit code. No retry is attempted for
authentication failures (retrying a bad credential risks locking out the
account).

If you see this error, configure the appropriate credential helper for your
platform (see the platform sections above) and re-run the kanon command.

## See also

- [`docs/security-model.md`](security-model.md) -- full trust-model
  description, provider-agnosticism invariant, and auth-delegation policy.
- [`docs/troubleshooting.md`](troubleshooting.md) -- common error messages
  with reproducers and fixes, including the "git auth failure" entry that
  cross-references this document.
