# Archive

Documentation for upgrades between major releases.

Nothing here is needed on a current installation. These notes are retained only
so the path is not lost for the unlikely case that someone is still on an older
major version; nothing in the current documentation should route a reader here.

| Document | Covers |
| --- | --- |
| [upgrading-from-2x.md](upgrading-from-2x.md) | `kanon bootstrap`, removed in 3.0.0, and its replacement by `kanon search` / `kanon add` |
| [migrating-existing-kanon-files.md](migrating-existing-kanon-files.md) | Converting a pre-3.0 `.kanon` file to the current manifest and lockfile shape |

There is no migration between 3.x releases. Upgrading kanon requires no operator
action: `kanon doctor` reports anything left behind by an older layout, and
`kanon clean` reclaims it.
