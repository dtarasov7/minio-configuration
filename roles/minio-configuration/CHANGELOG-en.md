# Changes

## 3.2.0 — 2026-10-16

- Role behavior is selected by `minio_configuration_mode`: `apply` (default), `dry` or `export`, configured in inventory or through `-e`.
- Removed the mode-selection tags `dry`, `dryrun` and `export` and the intermediate mode fact derived from tags.
- Stage tags filter apply tasks and corresponding plan sections; export mode only checks access and exports configuration.
- Native Ansible `--check` is independent of the role mode. Reads execute, mutating commands honor check mode, and export with `--check` does not write a file.
- Added mode validation and updated local tests and the Molecule scenario.
- Restored the complete Russian and English changelog history. READMEs describe only the current role interface.

## 3.1.0 — 2026-10-16

- Added blank lines before every task in the role, examples, local tests and Molecule, including nested block/rescue/always tasks.

## 3.0.0 — 2026-10-16

- Established readable policy field ordering; Action/NotAction and Resource/NotResource lists are exported inline with correct YAML quoting.
- Export contains only the users/groups/backets variable lists without inventory wrappers or metadata; each entity starts with name, followed by anonymous/anonymous_policy and versioning for buckets.
- Removed public `minio_configuration_mode`; actions use tags and preview also supports `--check`.
- The role stops with migration instructions when the old variable is present.
- Prerequisite tasks inherit only `always`; removed the `pre-req` tag and redundant static task tags.
- Export uses `never`/`export`, requires explicit selection and does not write a mode variable to inventory.
- Both READMEs start with a brief command summary and retain detailed behavior in the relevant sections.
- Updated local tests and Molecule to select export/dryrun with CLI tags.

## 2.0.0 — 2026-10-15

- The role uses an installed `mc` and existing alias; `admin info` checks access and stops the run on errors.
- Removed alias configuration, administrator credentials and connection/client download variables.
- `minio_configuration_mc_binary_path` specifies the full path including the executable name (`mc` or `mcli`).
- Added `dryrun`: read current state, print operations without writes, redact passwords, support tags and `--check`.
- `install` only prepares the policy directory; `user`/`backet` tags also prepare it when policy files are needed.
- Export no longer includes an endpoint or administrator credentials.
- Added dryrun and missing alias/binary coverage; updated Molecule prerequisites.

- Fixed prerequisite, connection and nested task tagging.
- `--tags export` selects export without mutating MinIO objects, including combined tag runs.
- Export includes a reference snapshot of all original IAM policies, including unassigned policies.
- Added integration coverage for the `export` and `user` tags.

## 1.0.0 — 2026-10-08

- Added anonymous access presets and explicit IAM anonymous access policies.
- Added multiple IAM statements and named policies per user, explicit denies,
  bucket/object patterns and access conditions.
- Users are updated without deletion; existing users may omit their password.
- Added YAML inventory export for buckets, policies, users and groups.
- Removed support for variables without the `minio_configuration_` prefix.
- Added local checks and Molecule coverage for access policies and export.

- Defaults use explicit IAM statements with unchanged default permissions.
- User membership is configured through groups and synchronized across all current groups;
  omission removes all memberships. Groups are created from assigned users.
- The mc alias is configured through minio_configuration_alias and preserved in export.
- Documented 59 named S3 actions plus s3:* for the 2025-10-15 release, API limitations,
  NotResource examples and explicit Deny exclusions.

- Removed shorthand user permissions; permissions use IAM statements.
- Groups support inline statements in the same format as users.
- Generated policy names use separate entity namespaces: minio-configuration-user-<name>
  and minio-configuration-group-<name>. Identical direct permissions for different users
  create separate policies; group permissions are inherited by all members.

- Each user/group rule creates a separate policy named with its owner,
  Sid and user/grp type. Shared assignment of role-generated policies is prohibited.
- Sid is mandatory and unique within each owner; other owners may reuse it.
- Direct assignments to all built-in users and groups, including entities created
  outside the role, are checked before policy updates; foreign assignments block updates.
- Removed shared policy lists. Export expands current policies into owner statements
  and supplies stable Sids for missing/duplicate identifiers.
