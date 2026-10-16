# minio-configuration

Role version: **2.0.0**.

Configure MinIO buckets, anonymous access and built-in IAM users through `mc`,
or export their current configuration as an Ansible YAML inventory.

## Prerequisites and migration from 1.x

Install `mc` (or `mcli`) and configure an authenticated administrative alias on
`minio_configuration_delegate_host` before invoking the role. Set
`minio_configuration_mc_binary_path` to the full executable path, including its filename.
The role runs that executable with `admin info <alias>` and stops on a missing binary,
unknown alias or access error. It does not install packages, download mc, change aliases,
or require an administrator password.

The alias must be available to the effective Ansible execution user, including `become`.
It defines the endpoint, credentials and TLS settings. Configure aliases separately on
any new delegate/server before reusing an export. Add custom administrative/technical
accounts to `minio_configuration_protected_users` when deletion is enabled.

Version 2.0.0 removes role variables for endpoint/scheme/port, root credentials,
mc download URL/checksum and download certificate validation. Remove those settings
from inventory; configure them outside the role where appropriate. Application user
`secret_key` values remain supported.

## Variables

| Variable | Default | Meaning |
|---|---|---|
| `minio_configuration_nodes_group` | `minio_cluster` | Inventory group |
| `minio_configuration_delegate_host` | First group member | Host running `mc` |
| `minio_configuration_metrics_user` | `minio_prometheus` | Protected metrics user |
| `minio_configuration_alias` | `local` | mc alias for every command and export |
| `minio_configuration_mc_binary_path` | `/usr/local/bin/mc` | Full path including the executable name, e.g. `/opt/minio/mcli` |
| `minio_configuration_backets` | Bucket `b-default`, versioning disabled | Bucket definitions; spelling is intentional for compatibility |
| `minio_configuration_users` | Explicit read and write IAM statements on `b-default` | See defaults/main.yml; override passwords |
| `minio_configuration_backets_delete` | `false` | Delete undeclared buckets |
| `minio_configuration_users_delete` | `false` | Delete undeclared users |
| `minio_configuration_protected_users` | `[minioadmin, minio_prometheus]` | Excluded from automatic deletion |
| `minio_configuration_mode` | `apply` | `apply`, `export` or `dryrun` |
| `minio_configuration_export_path` | `{{ playbook_dir }}/minio-inventory.yml` | Controller output file; parent directory must exist |
| `minio_configuration_no_log` | `true` | Hide tasks containing passwords |
| `minio_configuration_policy_dir` | `/etc/minio/policies` | Policy files on delegate host |
| `minio_configuration_groups` | `[]` | Groups: `name`, optional `members`, `statements`, `status` |
| `minio_configuration_hashi_vault_path_password` | `''` | Optional path used in variable-level HashiCorp Vault lookups |

## Anonymous access

Set either `anonymous` (`none`, `private`, `download`, `upload`, `public`) or a full
`anonymous_policy`. Omit both to preserve existing access. `none` removes the
public policy; an explicit document replaces the entire bucket policy.

```yaml
minio_configuration_backets:
- name: incoming
  anonymous: upload
- name: documents
  anonymous_policy:
    Version: '2012-10-17'
    Statement:
    - Effect: Allow
      Principal:
        AWS:
        - '*'
      Action:
      - s3:GetObject
      Resource:
      - arn:aws:s3:::documents/public/*
```

This permits anonymous GET of known public keys without granting ListBucket.
Avoid a bucket-policy Deny with `Principal: '*'` unless it should also apply to
authenticated users. Exact object keys and wildcard prefixes are supported.

## User policies

Define a `statements` list directly on users and groups. IAM statements are passed
through unchanged, including conditions, Allow/Deny and resource patterns.

```yaml
minio_configuration_users:
- name: app
  secret_key: '{{ vault_app_secret }}'
  statements:
  - Effect: Allow
    Action:
    - s3:GetObject
    Resource:
    - arn:aws:s3:::project-*/reports/*
    - arn:aws:s3:::documents/manual.pdf
    Sid: Rule1
  - Effect: Deny
    Action:
    - s3:CreateBucket
    Resource:
    - arn:aws:s3:::*
    Sid: Rule2
```

Use bucket ARNs for bucket operations and object ARNs for object operations.
Explicit Deny overrides Allow, including permissions from other policies/groups.
For prefix-restricted listing, grant ListBucket on the bucket ARN with a
`Condition: {StringLike: {'s3:prefix': ['reports/*']}}`.

Each user/group rule requires a non-empty alphanumeric Sid. Duplicate Sid within
one owner is rejected before changing MinIO; different owners may reuse the same Sid.
Comparison is case-sensitive. Each rule gets its own exclusively owned policy:

- `minio-configuration-user-<username>-<Sid>`;
- `minio-configuration-grp-<groupname>-<Sid>`.

A user and group named alice with Sid ReadReports get distinct names. Identical
rules across owners are never merged. A group policy is attached only to that group;
its members inherit the permissions through membership.

Direct attachments exactly match statements. Empty/omitted statements remove all
direct policies. Changing a Sid detaches its old policy and creates a new one;
unattached old policy documents are retained on the server. Shared named policies
and policies fields are unsupported. Before configuration changes, the role reads
all built-in direct assignments and refuses to update a generated policy attached
to any other owner, including entities created outside the role. Foreign assignments
are not removed automatically. Do not change assignments concurrently with the run.

Existing users may omit `secret_key`; new users require it. Updating a password
never deletes the user. Optional `status: enabled|disabled` sets account status.
Declare groups in `minio_configuration_groups` with `name`, inline `statements` and optional
`status`. Assign users using `users[].groups: [readers]`. Groups are created with their
first assigned member. Omitted user.groups means an empty list: the managed user is
removed from every current group, including groups absent from inventory. Group-only
users can omit direct statements. Export preserves user.groups.

```yaml
minio_configuration_alias: production
minio_configuration_groups:
- name: readers
  statements:
  - Effect: Allow
    Action:
    - s3:GetObject
    Resource:
    - arn:aws:s3:::project-*/reports/*
    Sid: Rule1
  status: enabled
minio_configuration_users:
- name: alice
  secret_key: '{{ vault_alice_secret }}'
  groups:
  - readers
- name: bob
  groups: []
  statements: []
```

Alice inherits the reader policy; existing Bob loses all group and direct permissions.
Group.members is optional: omitted means preserve other members; specified means
reconcile its complete additional membership list plus assignments from user.groups.
A group.members entry contradicting a managed user's groups is rejected. Group-only
membership reconciliation preserves unmanaged users. Empty group creation is not
supported by mc; creating a group requires its first member. Existing empty groups
can be updated. Users may reference groups outside role declarations; their policies
remain unchanged. Group attachments match statements; empty or omitted statements remove all direct group attachments.

## Inventory and playbook

```yaml
minio_cluster:
  hosts:
    minio1:
      ansible_host: 10.10.10.11
  vars:
    minio_configuration_alias: production
    minio_configuration_mc_binary_path: /usr/local/bin/mc
```

```yaml
- hosts: minio_cluster
  become: true
  roles:
  - minio-configuration
```

From the repository root:

```bash
ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.yml roles/minio-configuration/examples/playbook.yml
ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.yml roles/minio-configuration/examples/playbook.yml \
  --tags export -e minio_configuration_export_path="$PWD/minio-inventory.yml"
ANSIBLE_ROLES_PATH=roles ansible-playbook -i minio-inventory.yml roles/minio-configuration/examples/playbook.yml
```

Use `--tags export` to select export mode automatically; `-e minio_configuration_mode=export` remains supported.
Export uses the installed client and existing alias. It checks `mc admin info`, reads
the server and writes a mode-0600 inventory on the controller. Server objects remain
unchanged even when deletion flags are true.
The inventory contains buckets, exact anonymous policy documents, ordinary built-in
users, groups and statuses. Current direct policy documents are expanded into each
owner's statements, without shared policy references. All original IAM policies, including
unassigned policies, are also saved by name in `minio_configuration_exported_policies`.
This reference snapshot is ignored by apply mode. Reapplying the export creates
exclusive policies without modifying the former shared policies used by other entities.
Valid unique Sids are preserved. Missing, invalid or duplicate Sids receive stable
Export<sha256> identifiers; the remaining rule content is preserved. Export aborts on read
errors without replacing the file with partial results. Repeated exports replace
the file. The resulting inventory uses apply mode and disables deletion.

Passwords cannot be recovered. Existing users keep passwords; migration to a new server
requires adding their secret_key values and preconfiguring the alias for that server.
The exported inventory contains no administrator credentials or endpoint.
The protected user list is also preserved in the inventory.
Root, service accounts, STS credentials and external LDAP/OIDC identities are not
ordinary users returned by mc admin user list and are not copied. Objects,
lifecycle rules, quotas, TLS and server configuration are outside this export.
Only the versioning enabled state is preserved, not MFA/prefix exclusion settings.

Application user passwords can use inventory variables, Ansible Vault, or variable-level
HashiCorp Vault lookups, for example `secret_key: "{{ vault_app_secret }}"`.
`minio_configuration_hashi_vault_path_password` remains available for these lookups.

## Dryrun

```bash
ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.yml roles/minio-configuration/examples/playbook.yml --tags dryrun
ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.yml roles/minio-configuration/examples/playbook.yml -e minio_configuration_mode=dryrun
ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.yml roles/minio-configuration/examples/playbook.yml --check
```

Dryrun validates input, checks the alias and reads the current buckets, users, groups,
policies and assignments. It prints `minio_configuration_plan` with operation names,
targets, policy documents, membership changes and deletions permitted by the flags.
User passwords appear as `[REDACTED]`. It does not write policy files, create directories,
export inventory, or run mutating mc commands. Reads against MinIO are performed.
The plan describes operations the apply tasks would attempt, including repeated
policy updates, password updates and versioning settings; it is not an exact change count.
It is a snapshot: concurrent changes and server-side write authorization can affect apply.

Use `-e minio_configuration_mode=dryrun --tags user` or `--tags dryrun,user` for user/group
operations only; replace `user` with `backet` for buckets or `clean` for cleanup.
`--tags dryrun` alone previews the normal full run, excluding cleanup.
The `export` tag takes precedence over `dryrun` when both are selected.
Standard `--check` previews apply/clean; export in check mode reads the server and previews
writing the inventory through Ansible's copy module.

## Tags and tests

Tags: `pre-req`, `install`, `config`, `backet`, `user`, `ssl`, `export`,
`dryrun`, `clean` (never runs by default). Preflight and existing alias checks use
`always` and run with each operational tag. `install` only prepares the policy directory;
`user` and `backet` also prepare it when policy files are needed. Nested validation and reconciliation tasks receive the required tags.
Selecting `export` suppresses installation, apply and cleanup even when combined
with other tags.
Cleanup removes declared users/buckets and is explicitly invoked with `--tags clean`.

Molecule uses four prebuilt `redos:7.3.6` Docker containers and `minio-cluster`.
It covers CRUD, read/write restrictions, granular access, anonymous presets,
explicit bucket-creation denial, dryrun without side effects and export/replay. Run `molecule test` from the
role directory with images and dependencies available.

Local tests from the repository root:

```bash
python -m unittest discover -s roles/minio-configuration/tests -v
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/export.yml
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/export.yml --tags export
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/tags.yml --tags user
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/dryrun.yml --tags dryrun
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/prerequisites.yml
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/groups.yml
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/ownership.yml
```

References: [mc anonymous](https://docs.min.io/aistor/reference/cli/mc-anonymous/),
[mc admin policy](https://docs.min.io/aistor/reference/cli/admin/mc-admin-policy/).

## S3 Action names in RELEASE.2025-10-15T17-29-55Z

`20251015T172955Z` identifies `RELEASE.2025-10-15T17-29-55Z`, which pins
`github.com/minio/pkg/v3 v3.1.3`. The table lists every S3 action name recognized
by that IAM validator. Sources: [release go.mod](https://github.com/minio/minio/blob/RELEASE.2025-10-15T17-29-55Z/go.mod),
[supportedActions](https://github.com/minio/pkg/blob/v3.1.3/policy/action.go).

| Категория / Category | Action |
|---|---|
| Объекты / Objects | `s3:GetObject`, `s3:GetObjectAttributes`, `s3:PutObject`, `s3:DeleteObject`, `s3:RestoreObject`, `s3:PutObjectFanOut` |
| Multipart | `s3:AbortMultipartUpload`, `s3:ListMultipartUploadParts`, `s3:ListBucketMultipartUploads` |
| Версии объектов / Object versions | `s3:GetObjectVersion`, `s3:GetObjectVersionAttributes`, `s3:DeleteObjectVersion`, `s3:ListBucketVersions` |
| Теги объектов / Object tags | `s3:GetObjectTagging`, `s3:PutObjectTagging`, `s3:DeleteObjectTagging`, `s3:GetObjectVersionTagging`, `s3:PutObjectVersionTagging`, `s3:DeleteObjectVersionTagging` |
| Бакеты и списки / Buckets and listing | `s3:CreateBucket`, `s3:DeleteBucket`, `s3:ForceDeleteBucket`, `s3:GetBucketLocation`, `s3:ListAllMyBuckets`, `s3:ListBucket`, `s3:HeadBucket` |
| Политики бакетов / Bucket policies | `s3:GetBucketPolicy`, `s3:PutBucketPolicy`, `s3:DeleteBucketPolicy`, `s3:GetBucketPolicyStatus` |
| Конфигурация бакетов / Bucket configuration | `s3:GetBucketVersioning`, `s3:PutBucketVersioning`, `s3:GetBucketTagging`, `s3:PutBucketTagging`, `s3:GetLifecycleConfiguration`, `s3:PutLifecycleConfiguration`, `s3:GetEncryptionConfiguration`, `s3:PutEncryptionConfiguration` |
| Уведомления / Notifications | `s3:GetBucketNotification`, `s3:PutBucketNotification`, `s3:ListenNotification`, `s3:ListenBucketNotification` |
| Object Lock | `s3:GetBucketObjectLockConfiguration`, `s3:PutBucketObjectLockConfiguration`, `s3:GetObjectRetention`, `s3:PutObjectRetention`, `s3:GetObjectLegalHold`, `s3:PutObjectLegalHold`, `s3:BypassGovernanceRetention` |
| Репликация / Replication | `s3:GetReplicationConfiguration`, `s3:PutReplicationConfiguration`, `s3:ReplicateObject`, `s3:ReplicateDelete`, `s3:ReplicateTags`, `s3:GetObjectVersionForReplication`, `s3:ResetBucketReplicationState` |
| CORS | `s3:GetBucketCors`, `s3:PutBucketCors`, `s3:DeleteBucketCors` |
| Все действия / All actions | `s3:*` |

Recognition does not guarantee an implemented API. HeadBucket is marked unused
in the policy library. Use ListBucket for ordinary bucket access. PUT/DELETE bucket
CORS return NotImplemented in this release despite recognized policy names:
[release API routes](https://github.com/minio/minio/blob/RELEASE.2025-10-15T17-29-55Z/cmd/api-router.go).
CopyObject needs GetObject on the source and PutObject on the destination.
Multipart creation, parts and completion use PutObject; HeadObject normally uses
GetObject. These API names are not additional action names.

## Excluding resource patterns

Patterns support `*` (including `/`) and `?`, not regular expressions or negative
lookahead. Use NotResource for a complement or a separate Deny for an exclusion
that must override other policies. Sources: [wildcards](https://github.com/minio/pkg/blob/v3.1.3/wildcard/match.go),
[NotResource evaluation](https://github.com/minio/pkg/blob/v3.1.3/policy/statement.go).

```yaml
statements:
- Effect: Allow
  Action:
  - s3:GetObject
  NotResource:
  - arn:aws:s3:::private-*/*
  - arn:aws:s3:::*/secret/*
  Sid: Rule1
```

This grants reads outside the exclusions without listing. Another user/group policy
can still grant the excluded reads. For an unconditional exclusion:

```yaml
statements:
- Effect: Allow
  Action:
  - s3:GetObject
  Resource:
  - arn:aws:s3:::*/*
  Sid: Rule1
- Effect: Deny
  Action:
  - s3:GetObject
  - s3:GetObjectVersion
  Resource:
  - arn:aws:s3:::private-*/*
  - arn:aws:s3:::*/secret/*
  - arn:aws:s3:::*/*.key
  Sid: Rule2
```

Bucket operations use ARNs without an object suffix. List objects in buckets
whose names do not begin with private-:

```yaml
statements:
- Effect: Allow
  Action:
  - s3:ListBucket
  NotResource:
  - arn:aws:s3:::private-*
  Sid: Rule1
```

ListBucket authorizes the entire listing request; an object-read exclusion does not
hide object names in an allowed listing. Omit ListBucket to hide names, or restrict
requests to safe s3:prefix values. ListAllMyBuckets should not be treated as a
bucket-name filter. Reading specific versions requires GetObjectVersion separately.
