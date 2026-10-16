# Changes

## 3.1.0 — in development

- The role uses an installed `mc`/`mcli` and configured alias; `admin info` checks access.
- Actions use tags: apply, export, dry/dryrun and cleanup. Native Ansible `--check` is independent of action selection.
- Configuration covers buckets, versioning, anonymous access, users, groups and memberships.
- IAM permissions use inline `statements`; each rule has an exclusive owner policy with a unique `Sid` within that owner.
- Direct policy assignments are checked for exclusive ownership before policy updates.
- Export contains three lists: `minio_configuration_users`, `minio_configuration_groups`, `minio_configuration_backets`.
- YAML exports use readable field ordering and inline Action/NotAction and Resource/NotResource lists.
- Flags control undeclared object deletion; protected users are excluded from deletion.
- Blank lines precede tasks, including nested blocks and test playbooks.
- Local tests and a Molecule scenario cover a Docker-based MinIO cluster.
