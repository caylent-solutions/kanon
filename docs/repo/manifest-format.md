# repo Manifest Format

A repo manifest describes the structure of a repo client; that is
the directories that are visible and where they should be obtained
from with git.

The basic structure of a manifest is a bare Git repository holding
a single `default.xml` XML file in the top level directory.

Manifests are inherently version controlled, since they are kept
within a Git repository.  Updates to manifests are automatically
obtained by clients during `repo sync`.

[TOC]


## XML File Format

A manifest XML file (e.g. `default.xml`) roughly conforms to the
following DTD:

```xml
<!DOCTYPE manifest [

  <!ELEMENT manifest (notice?,
                      remote*,
                      default?,
                      manifest-server?,
                      submanifest*?,
                      remove-project*,
                      project*,
                      extend-project*,
                      repo-hooks?,
                      superproject?,
                      contactinfo?,
                      include*)>

  <!ELEMENT notice (#PCDATA)>

  <!ELEMENT remote (annotation*)>
  <!ATTLIST remote name         ID    #REQUIRED>
  <!ATTLIST remote alias        CDATA #IMPLIED>
  <!ATTLIST remote fetch        CDATA #REQUIRED>
  <!ATTLIST remote pushurl      CDATA #IMPLIED>
  <!ATTLIST remote review       CDATA #IMPLIED>
  <!ATTLIST remote revision     CDATA #IMPLIED>

  <!ELEMENT default EMPTY>
  <!ATTLIST default remote      IDREF #IMPLIED>
  <!ATTLIST default revision    CDATA #IMPLIED>
  <!ATTLIST default dest-branch CDATA #IMPLIED>
  <!ATTLIST default upstream    CDATA #IMPLIED>
  <!ATTLIST default sync-j      CDATA #IMPLIED>
  <!ATTLIST default sync-c      CDATA #IMPLIED>
  <!ATTLIST default sync-s      CDATA #IMPLIED>
  <!ATTLIST default sync-tags   CDATA #IMPLIED>

  <!ELEMENT manifest-server EMPTY>
  <!ATTLIST manifest-server url CDATA #REQUIRED>

  <!ELEMENT submanifest EMPTY>
  <!ATTLIST submanifest name           ID #REQUIRED>
  <!ATTLIST submanifest remote         IDREF #IMPLIED>
  <!ATTLIST submanifest project        CDATA #IMPLIED>
  <!ATTLIST submanifest manifest-name  CDATA #IMPLIED>
  <!ATTLIST submanifest revision       CDATA #IMPLIED>
  <!ATTLIST submanifest path           CDATA #IMPLIED>
  <!ATTLIST submanifest groups         CDATA #IMPLIED>
  <!ATTLIST submanifest default-groups CDATA #IMPLIED>

  <!ELEMENT project (annotation*,
                     project*,
                     copyfile*,
                     linkfile*)>
  <!ATTLIST project name        CDATA #REQUIRED>
  <!ATTLIST project path        CDATA #IMPLIED>
  <!ATTLIST project remote      IDREF #IMPLIED>
  <!ATTLIST project revision    CDATA #IMPLIED>
  <!ATTLIST project dest-branch CDATA #IMPLIED>
  <!ATTLIST project groups      CDATA #IMPLIED>
  <!ATTLIST project sync-c      CDATA #IMPLIED>
  <!ATTLIST project sync-s      CDATA #IMPLIED>
  <!ATTLIST project sync-tags   CDATA #IMPLIED>
  <!ATTLIST project upstream CDATA #IMPLIED>
  <!ATTLIST project clone-depth CDATA #IMPLIED>
  <!ATTLIST project force-path CDATA #IMPLIED>

  <!ELEMENT annotation EMPTY>
  <!ATTLIST annotation name  CDATA #REQUIRED>
  <!ATTLIST annotation value CDATA #REQUIRED>
  <!ATTLIST annotation keep  CDATA "true">

  <!ELEMENT copyfile EMPTY>
  <!ATTLIST copyfile src  CDATA #REQUIRED>
  <!ATTLIST copyfile dest CDATA #REQUIRED>

  <!ELEMENT linkfile EMPTY>
  <!ATTLIST linkfile src CDATA #REQUIRED>
  <!ATTLIST linkfile dest CDATA #REQUIRED>
  <!ATTLIST linkfile exclude CDATA #IMPLIED>

  <!ELEMENT extend-project EMPTY>
  <!ATTLIST extend-project name CDATA #REQUIRED>
  <!ATTLIST extend-project path CDATA #IMPLIED>
  <!ATTLIST extend-project dest-path CDATA #IMPLIED>
  <!ATTLIST extend-project groups CDATA #IMPLIED>
  <!ATTLIST extend-project revision CDATA #IMPLIED>
  <!ATTLIST extend-project remote CDATA #IMPLIED>
  <!ATTLIST extend-project dest-branch CDATA #IMPLIED>
  <!ATTLIST extend-project upstream CDATA #IMPLIED>
  <!ATTLIST extend-project base-rev CDATA #IMPLIED>

  <!ELEMENT remove-project EMPTY>
  <!ATTLIST remove-project name     CDATA #IMPLIED>
  <!ATTLIST remove-project path     CDATA #IMPLIED>
  <!ATTLIST remove-project optional CDATA #IMPLIED>
  <!ATTLIST remove-project base-rev CDATA #IMPLIED>

  <!ELEMENT repo-hooks EMPTY>
  <!ATTLIST repo-hooks in-project CDATA #REQUIRED>
  <!ATTLIST repo-hooks enabled-list CDATA #REQUIRED>

  <!ELEMENT superproject EMPTY>
  <!ATTLIST superproject name     CDATA #REQUIRED>
  <!ATTLIST superproject remote   IDREF #IMPLIED>
  <!ATTLIST superproject revision CDATA #IMPLIED>

  <!ELEMENT contactinfo EMPTY>
  <!ATTLIST contactinfo bugurl  CDATA #REQUIRED>

  <!ELEMENT include EMPTY>
  <!ATTLIST include name     CDATA #REQUIRED>
  <!ATTLIST include groups   CDATA #IMPLIED>
  <!ATTLIST include revision CDATA #IMPLIED>
]>
```

For compatibility purposes across repo releases, all unknown elements are
silently ignored.  However, repo reserves all possible names for itself for
future use.  If you want to use custom elements, the `x-*` namespace is
reserved for that purpose, and repo guarantees to never allocate any
corresponding names.

A description of the elements and their attributes follows.


### Element manifest

The root element of the file.

### Element notice

Arbitrary text that is displayed to users whenever `repo sync` finishes.
The content is simply passed through as it exists in the manifest.

### Element remote

One or more remote elements may be specified.  Each remote element
specifies a Git URL shared by one or more projects and (optionally)
the Gerrit review server those projects upload changes through.

Attribute `name`: A short name unique to this manifest file.  The
name specified here is used as the remote name in each project's
.git/config, and is therefore automatically available to commands
like `git fetch`, `git remote`, `git pull` and `git push`.

Attribute `alias`: The alias, if specified, is used to override
`name` to be set as the remote name in each project's .git/config.
Its value can be duplicated while attribute `name` has to be unique
in the manifest file. This helps each project to be able to have
same remote name which actually points to different remote url.

Attribute `fetch`: The Git URL prefix for all projects which use
this remote.  Each project's name is appended to this prefix to
form the actual URL used to clone the project.

Attribute `pushurl`: The Git "push" URL prefix for all projects
which use this remote.  Each project's name is appended to this
prefix to form the actual URL used to "git push" the project.
This attribute is optional; if not specified then "git push"
will use the same URL as the `fetch` attribute.

Attribute `review`: Hostname of the Gerrit server where reviews
are uploaded to by `repo upload`.  This attribute is optional;
if not specified then `repo upload` will not function.

Attribute `revision`: Name of a Git branch (e.g. `main` or
`refs/heads/main`). Remotes with their own revision will override
the default revision.

### Element default

At most one default element may be specified.  Its remote and
revision attributes are used when a project element does not
specify its own remote or revision attribute.

Attribute `remote`: Name of a previously defined remote element.
Project elements lacking a remote attribute of their own will use
this remote.

Attribute `revision`: Name of a Git branch (e.g. `main` or
`refs/heads/main`).  Project elements lacking their own
revision attribute will use this revision.

Attribute `dest-branch`: Name of a Git branch (e.g. `main`).
Project elements not setting their own `dest-branch` will inherit
this value. If this value is not set, projects will use `revision`
by default instead.

Attribute `upstream`: Name of the Git ref in which a sha1
can be found.  Used when syncing a revision locked manifest in
-c mode to avoid having to sync the entire ref space. Project elements
not setting their own `upstream` will inherit this value.

Attribute `sync-j`: Number of parallel jobs to use when synching.

Attribute `sync-c`: Set to true to only sync the given Git
branch (specified in the `revision` attribute) rather than the
whole ref space.  Project elements lacking a sync-c element of
their own will use this value.

Attribute `sync-s`: Set to true to also sync sub-projects.

Attribute `sync-tags`: Set to false to only sync the given Git
branch (specified in the `revision` attribute) rather than
the other ref tags.


### Element manifest-server

At most one manifest-server may be specified. The url attribute
is used to specify the URL of a manifest server, which is an
XML RPC service.

See the [smart sync documentation](./smart-sync.md) for more details.


### Element submanifest

One or more submanifest elements may be specified.  Each element describes a
single manifest to be checked out as a child.

Attribute `name`: A unique name (within the current (sub)manifest) for this
submanifest. It acts as a default for `revision` below.  The same name can be
used for submanifests with different parent (sub)manifests.

Attribute `remote`: Name of a previously defined remote element.
If not supplied the remote given by the default element is used.

Attribute `project`: The manifest project name.  The project's name is appended
onto its remote's fetch URL to generate the actual URL to configure the Git
remote with.  The URL gets formed as:

    ${remote_fetch}/${project_name}.git

where ${remote_fetch} is the remote's fetch attribute and
${project_name} is the project's name attribute.  The suffix ".git"
is always appended as repo assumes the upstream is a forest of
bare Git repositories.  If the project has a parent element, its
name will be prefixed by the parent's.

The project name must match the name Gerrit knows, if Gerrit is
being used for code reviews.

`project` must not be empty, and may not be an absolute path or use "." or ".."
path components.  It is always interpreted relative to the remote's fetch
settings, so if a different base path is needed, declare a different remote
with the new settings needed.

If not supplied the remote and project for this manifest will be used: `remote`
cannot be supplied.

Projects from a submanifest and its submanifests are added to the
submanifest::path:<path_prefix> group.

Attribute `manifest-name`: The manifest filename in the manifest project.  If
not supplied, `default.xml` is used.

Attribute `revision`: Name of a Git branch (e.g. "main" or "refs/heads/main"),
tag (e.g. "refs/tags/stable"), or a commit hash.  If not supplied, `name` is
used.

Attribute `path`: An optional path relative to the top directory
of the repo client where the submanifest repo client top directory
should be placed.  If not supplied, `revision` is used.

`path` may not be an absolute path or use "." or ".." path components.

Attribute `groups`: List of additional groups to which all projects
in the included submanifest belong. This appends and recurses, meaning
all projects in submanifests carry all parent submanifest groups.
Same syntax as the corresponding element of `project`.

Attribute `default-groups`: The list of manifest groups to sync if no
`--groups=` parameter was specified at init.  When that list is empty, use this
list instead of "default" as the list of groups to sync.

### Element project

One or more project elements may be specified.  Each element
describes a single Git repository to be cloned into the repo
client workspace.  You may specify Git-submodules by creating a
nested project.  Git-submodules will be automatically
recognized and inherit their parent's attributes, but those
may be overridden by an explicitly specified project element.

Attribute `name`: A unique name for this project.  The project's
name is appended onto its remote's fetch URL to generate the actual
URL to configure the Git remote with.  The URL gets formed as:

    ${remote_fetch}/${project_name}.git

where ${remote_fetch} is the remote's fetch attribute and
${project_name} is the project's name attribute.  The suffix ".git"
is always appended as repo assumes the upstream is a forest of
bare Git repositories.  If the project has a parent element, its
name will be prefixed by the parent's.

The project name must match the name Gerrit knows, if Gerrit is
being used for code reviews.

"name" must not be empty, and may not be an absolute path or use "." or ".."
path components.  It is always interpreted relative to the remote's fetch
settings, so if a different base path is needed, declare a different remote
with the new settings needed.
These restrictions are not enforced for [Local Manifests].

Attribute `path`: An optional path relative to the top directory
of the repo client where the Git working directory for this project
should be placed.  If not supplied the project "name" is used.
If the project has a parent element, its path will be prefixed
by the parent's.

"path" may not be an absolute path or use "." or ".." path components.
These restrictions are not enforced for [Local Manifests].

If you want to place files into the root of the checkout (e.g. a README or
Makefile or another build script), use the [copyfile] or [linkfile] elements
instead.

Attribute `remote`: Name of a previously defined remote element.
If not supplied the remote given by the default element is used.

Attribute `revision`: Name of the Git branch the manifest wants
to track for this project.  Names can be relative to refs/heads
(e.g. just "main") or absolute (e.g. "refs/heads/main").
Tags and/or explicit SHA-1s should work in theory, but have not
been extensively tested.  If not supplied the revision given by
the remote element is used if applicable, else the default
element is used.

PEP 440 version constraints are also supported as the last path
component. The constraint is resolved against remote tags via
`git ls-remote` at sync time, selecting the highest matching
version. Supported operators: `~=`, `>=`, `<=`, `>`, `<`, `==`,
`!=`, `*` (wildcard). Examples:

    refs/tags/my-pkg/~=1.2.0          (>=1.2.0, <1.3.0)
    refs/tags/my-pkg/>=1.0.0,<2.0.0   (range)
    refs/tags/my-pkg/*                 (latest)
    refs/tags/ns/path/~=0.3.0         (namespaced)

**XML escaping:** The `<` character is reserved in XML and must
be escaped as `&lt;` inside attribute values. Other characters
that require escaping in XML attributes:

| Character | Escape     | Example in revision attribute |
|-----------|------------|-------------------------------|
| `<`       | `&lt;`     | `>=1.0.0,&lt;2.0.0`          |
| `>`       | `&gt;`     | (optional, `>` is valid in attributes but `&gt;` also works) |
| `&`       | `&amp;`    | (required if `&` appears in a value) |
| `"`       | `&quot;`   | (required inside `"` delimited attributes) |
| `'`       | `&apos;`   | (required inside `'` delimited attributes) |

Example with range constraint:

```xml
<project name="my-package"
         path=".packages/my-package"
         remote="origin"
         revision="refs/tags/my-package/>=1.0.0,&lt;2.0.0" />
```

Attribute `dest-branch`: Name of a Git branch (e.g. `main`).
When using `repo upload`, changes will be submitted for code
review on this branch. If unspecified both here and in the
default element, `revision` is used instead.

Attribute `groups`: List of groups to which this project belongs,
whitespace or comma separated.  All projects belong to the group
"all", and each project automatically belongs to a group of
its name:`name` and path:`path`.  E.g. for
`<project name="monkeys" path="barrel-of"/>`, that project
definition is implicitly in the following manifest groups:
default, name:monkeys, and path:barrel-of.  If you place a project in the
group "notdefault", it will not be automatically downloaded by repo.
If the project has a parent element, the `name` and `path` here
are the prefixed ones.

Attribute `sync-c`: Set to true to only sync the given Git
branch (specified in the `revision` attribute) rather than the
whole ref space.

Attribute `sync-s`: Set to true to also sync sub-projects.

Attribute `upstream`: Name of the Git ref in which a sha1
can be found.  Used when syncing a revision locked manifest in
-c mode to avoid having to sync the entire ref space.

Attribute `clone-depth`: Set the depth to use when fetching this
project.  If specified, this value will override any value given
to repo init with the --depth option on the command line.

Attribute `force-path`: Set to true to force this project to create the
local mirror repository according to its `path` attribute (if supplied)
rather than the `name` attribute.  This attribute only applies to the
local mirrors syncing, it will be ignored when syncing the projects in a
client working directory.

### Element extend-project

Modify the attributes of the named project.

This element is mostly useful in a local manifest file, to modify the
attributes of an existing project without completely replacing the
existing project definition.  This makes the local manifest more robust
against changes to the original manifest.

Attribute `path`: If specified, limit the change to projects checked out
at the specified path, rather than all projects with the given name.

Attribute `dest-path`: If specified, a path relative to the top directory
of the repo client where the Git working directory for this project
should be placed.  This is used to move a project in the checkout by
overriding the existing `path` setting.

Attribute `groups`: List of additional groups to which this project
belongs.  Same syntax as the corresponding element of `project`.

Attribute `revision`: If specified, overrides the revision of the original
project.  Same syntax as the corresponding element of `project`.

Attribute `remote`: If specified, overrides the remote of the original
project.  Same syntax as the corresponding element of `project`.

Attribute `dest-branch`: If specified, overrides the dest-branch of the original
project.  Same syntax as the corresponding element of `project`.

Attribute `upstream`: If specified, overrides the upstream of the original
project.  Same syntax as the corresponding element of `project`.

Attribute `base-rev`: If specified, adds a check against the revision
to be extended. Manifest parse will fail and give a list of mismatch extends
if the revisions being extended have changed since base-rev was set.
Intended for use with layered manifests using hash revisions to prevent
patch branches hiding newer upstream revisions. Also compares named refs
like branches or tags but is misleading if branches are used as base-rev.
Same syntax as the corresponding element of `project`.

### Element annotation

Zero or more annotation elements may be specified as children of a
project or remote element. Each element describes a name-value pair.
For projects, this name-value pair will be exported into each project's
environment during a 'forall' command, prefixed with `REPO__`.  In addition,
there is an optional attribute "keep" which accepts the case insensitive values
"true" (default) or "false".  This attribute determines whether or not the
annotation will be kept when exported with the manifest subcommand.

### Element copyfile

Zero or more copyfile elements may be specified as children of a
project element. Each element describes a src-dest pair of files;
the "src" file will be copied to the "dest" place during `repo sync`
command.

"src" is project relative, "dest" is relative to the top of the tree.
Copying from paths outside of the project or to paths outside of the repo
client is not allowed.

"src" and "dest" must be files.  Directories or symlinks are not allowed.
Intermediate paths must not be symlinks either.

Parent directories of "dest" will be automatically created if missing.

### Element linkfile

It's just like copyfile and runs at the same time as copyfile but
instead of copying it creates a symlink.

The symlink is created at "dest" (relative to the top of the tree) and
points to the path specified by "src" which is a path in the project.

Parent directories of "dest" will be automatically created if missing.

The symlink target may be a file or directory, but it may not point outside
of the repo client.

#### Absolute dest paths

Unlike `copyfile`, `linkfile` permits absolute paths in the `dest` attribute.
This is intended for use with `repo envsubst`, where an environment variable
expands to an absolute filesystem path at sync time.  For example:

    <linkfile src="config/settings.yml"
              dest="${CLAUDE_MARKETPLACES_DIR}/settings.yml" />

After `repo envsubst` resolves `${CLAUDE_MARKETPLACES_DIR}`, the resulting
absolute path is used directly.  Parent directories are created automatically.

Absolute dest paths are still validated: path components such as `..`, `.git`,
and other unsafe patterns are rejected.  However, the path is not restricted
to the repo client tree.

Note: `copyfile` dest remains relative-only.  Absolute dest paths are
supported exclusively by `linkfile`.

#### Exclude attribute

When the optional `exclude` attribute is present and `src` is a directory,
`linkfile` creates `dest` as a real directory and individually symlinks each
non-excluded immediate child of `src` into `dest`, rather than creating a
single symlink pointing to the entire source directory.

The `exclude` value is a comma-separated list of immediate child names to
omit.  Matching is exact (no glob or regex patterns) and applies only to
direct children of `src` (not recursive).  The `src` must be a directory
when `exclude` is set; using `exclude` with a file source raises an error.
Combining `exclude` with glob patterns in `src` is also an error.

Example:

    <linkfile src="common/example/cli-agent"
              dest="${CLAUDE_MARKETPLACES_DIR}/rpm-claude-example"
              exclude="tests,docs,__pycache__" />

**Auto-skipped entries:** When `exclude` is present, the following
repo-internal entries are always excluded automatically, regardless of
whether they appear in the `exclude` value:

| Entry | Behavior | Reason |
|---|---|---|
| `.git` | Always skipped | Git internal directory |
| `.repo`, `.repo*` | Always skipped | Repo tool internal directories |
| `.packages` | Always skipped | RPM package sync directory |
| `.config`, `.env`, etc. | Symlinked normally | May be legitimate plugin content |
| User-specified excludes | Skipped | Controlled by `exclude` attribute |

### Element remove-project

Deletes a project from the internal manifest table, possibly
allowing a subsequent project element in the same manifest file to
replace the project with a different source.

This element is mostly useful in a local manifest file, where
the user can remove a project, and possibly replace it with their
own definition.

The project `name` or project `path` can be used to specify the remove target
meaning one of them is required. If only name is specified, all
projects with that name are removed.

If both name and path are specified, only projects with the same name and
path are removed, meaning projects with the same name but in other
locations are kept.

If only path is specified, a matching project is removed regardless of its
name. Logic otherwise behaves like both are specified.

Attribute `optional`: Set to true to ignore remove-project elements with no
matching `project` element.

Attribute `base-rev`: If specified, adds a check against the revision
to be removed. Manifest parse will fail and give a list of mismatch removes
if the revisions being removed have changed since base-rev was set.
Intended for use with layered manifests using hash revisions to prevent
patch branches hiding newer upstream revisions. Also compares named refs
like branches or tags but is misleading if branches are used as base-rev.
Same syntax as the corresponding element of `project`.

### Element repo-hooks

NB: See the [practical documentation](./repo-hooks.md) for using repo hooks.

Only one repo-hooks element may be specified at a time.
Attempting to redefine it will fail to parse.

Attribute `in-project`: The project where the hooks are defined.  The value
must match the `name` attribute (**not** the `path` attribute) of a previously
defined `project` element.

Attribute `enabled-list`: List of hooks to use, whitespace or comma separated.

### Element superproject

***
*Note*: This is currently a WIP.
***

NB: See the [git superprojects documentation](
https://en.wikibooks.org/wiki/Git/Submodules_and_Superprojects) for background
information.

This element is used to specify the URL of the superproject. It has "name" and
"remote" as atrributes. Only "name" is required while the others have
reasonable defaults. At most one superproject may be specified.
Attempting to redefine it will fail to parse.

Attribute `name`: A unique name for the superproject. This attribute has the
same meaning as project's name attribute. See the
[element project](#element-project) for more information.

Attribute `remote`: Name of a previously defined remote element.
If not supplied the remote given by the default element is used.

Attribute `revision`: Name of the Git branch the manifest wants
to track for this superproject. If not supplied the revision given
by the remote element is used if applicable, else the default
element is used.

### Element contactinfo

***
*Note*: This is currently a WIP.
***

This element is used to let manifest authors self-register contact info.
It has "bugurl" as a required atrribute. This element can be repeated,
and any later entries will clobber earlier ones. This would allow manifest
authors who extend manifests to specify their own contact info.

Attribute `bugurl`: The URL to file a bug against the manifest owner.

### Element include

This element provides the capability of including another manifest
file into the originating manifest.  Normal rules apply for the
target manifest to include - it must be a usable manifest on its own.

Attribute `name`: the manifest to include, specified relative to
the manifest repository's root.

"name" may not be an absolute path or use "." or ".." path components.
These restrictions are not enforced for [Local Manifests].

Attribute `groups`: List of additional groups to which all projects
in the included manifest belong. This appends and recurses, meaning
all projects in included manifests carry all parent include groups.
Same syntax as the corresponding element of `project`.

Attribute `revision`: Name of a Git branch (e.g. `main` or `refs/heads/main`)
default to which all projects in the included manifest belong.

## Local Manifests {#local-manifests}

Additional remotes and projects may be added through local manifest
files stored in `$TOP_DIR/.repo/local_manifests/*.xml`.

For example:

    $ ls .repo/local_manifests
    local_manifest.xml
    another_local_manifest.xml

    $ cat .repo/local_manifests/local_manifest.xml
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <project path="manifest"
               name="tools/manifest" />
      <project path="platform-manifest"
               name="platform/manifest" />
    </manifest>

Users may add projects to the local manifest(s) prior to a `repo sync`
invocation, instructing repo to automatically download and manage
these extra projects.

Manifest files stored in `$TOP_DIR/.repo/local_manifests/*.xml` will
be loaded in alphabetical order.

Projects from local manifest files are added into
local::<local manifest filename> group.

The legacy `$TOP_DIR/.repo/local_manifest.xml` path is no longer supported.


[copyfile]: #Element-copyfile
[linkfile]: #Element-linkfile
[Local Manifests]: #local-manifests
