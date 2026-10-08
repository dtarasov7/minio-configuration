# Changes

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
