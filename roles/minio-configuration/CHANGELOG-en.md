# Changes

## 3.1.0 — 2026-10-16

- Added blank lines before every task in the role, examples, local tests and Molecule, including nested block/rescue/always tasks.

## 3.0.0 — 2026-10-16

- Added consistent policy field ordering and inline Action/NotAction and Resource/NotResource lists with correct YAML quoting.
- Export contains only the users/groups/backets variable lists without inventory wrappers or metadata; each entity starts with name, followed by anonymous/anonymous_policy and versioning for buckets.
- Removed public `minio_configuration_mode`; actions use tags and preview also supports `--check`.
- The role rejects the old variable with migration instructions.
- Prerequisite tasks inherit only `always`; removed the `pre-req` tag and redundant static task tags.
- Export uses `never`/`export`, requires explicit selection and no longer writes a mode variable to inventory.
- Both READMEs start with a brief command summary and retain detailed behavior in the relevant sections.
- Updated local tests and Molecule to select export/dryrun with CLI tags.

## 2.0.0 — 2026-10-15

- Use an installed `mc` and existing alias; `admin info` checks access and stops on errors.
- Removed alias configuration, administrator credentials and connection/client download variables.
- `minio_configuration_mc_binary_path` specifies the full path including the executable name (`mc` or `mcli`).
- Added `dryrun`: read current state, print operations without writes, redact passwords, support tags and `--check`.
- `install` only prepares policy files' directory, also prepared with `user`/`backet` tags when needed.
- Export no longer includes an endpoint or administrator credentials.
- Added dryrun and missing alias/binary coverage; updated Molecule prerequisites.

- Fixed prerequisite, connection and nested task tagging.
- `--tags export` selects export without mutating MinIO objects, including combined tag runs.
- Export now includes a reference snapshot of all original IAM policies, including unassigned policies.
- Added integration coverage for the `export` and `user` tags.

## 1.0.0 — 2026-10-08

- Added anonymous access presets and explicit IAM bucket policies.
- Added multiple statements and named policies per user, explicit denies,
  bucket/object patterns and conditions.
- Update users without deleting them; existing users may omit their password.
- Added YAML inventory export for buckets, policies, users and groups.
- Removed support for variables without the `minio_configuration_` prefix.
- Added local tests and Molecule access-policy and export/replay coverage.

- Defaults now use explicit IAM statements with unchanged standard permissions.
- User.groups reconciles all current memberships; omission removes all memberships.
  Groups are created from assigned users, and export preserves membership lists.
- Added minio_configuration_alias for every mc command and exported inventory.
- Documented 59 named S3 actions plus s3:* for the 2025-10-15 release, API limitations,
  NotResource examples and explicit Deny exclusions.

- Removed shorthand user permissions; use explicit IAM statements.
- Groups support inline statements in the same format as users.
- Generated policy names use separate user/group namespaces:
  minio-configuration-user-<name> and minio-configuration-group-<name>.
  Identical inline user permissions create distinct policies; group permissions
  are inherited by all group members.

- Each owner rule gets its own policy named with user/grp, owner name and Sid.
- Sid is mandatory and unique within each owner; other owners may reuse it.
- Direct built-in user/group assignments are checked before policy updates;
  assignments to foreign owners, including entities created outside the role, block updates.
- Removed shared policy lists. Export expands current policies into owner statements
  and supplies stable identifiers for missing/invalid/duplicate Sids.
