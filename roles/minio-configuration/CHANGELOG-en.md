# Changes

## 3.12.2 — 2026-10-19

- Matrix distinguishes a row's own rules (L/R/W/D) from broader matching rules (l/r/w/d), including ListBucket and supported prefix conditions.
- Explicit Allow takes uppercase when a broader Allow also applies. Denials use !R/!r according to Deny scope and still override Allow; unknown remains a standalone ?.
- Added regressions for prefix rows introduced by other users, explicit/broader rules, denials and conditional listing. Updated the legend, both READMEs and lab examples.

## 3.12.1 — 2026-10-19

- Matrix rows show only rules covering the row's entire range; narrower grants and denials appear in their own rows without summary markers on broader rows.
- Unknown calculations caused by unsupported rules use a standalone ? in the fixed L/R/W/D slot, without the action letter. No partial-permission marker is used.
- Supported positive prefix comparisons are intersected; restricted listing grants appear only on their corresponding rows.
- Updated the legend, lab examples, both READMEs and matrix checks.

## 3.12.0 — 2026-10-19

- Matrix Condition support for ListBucket: StringLike/StringEquals on s3:prefix, scalar/list values, literal prefixes and trailing StringLike wildcards.
- Conditional Allow/Deny is evaluated over prefix-request ranges; conditions add rows and mixed ranges retain L?. Unsupported conditions remain explicitly unknown.
- Added a lab-test conditional policy and lab/check-access.sh using minio-client: positive/negative checks, access-denial versus network-error detection and cleanup limited to its own objects.
- Added unit and Ansible condition checks; access checks and real JSON collection passed against a separate temporary MinIO 20251015T172955Z using the RED OS client.

## 3.11.1 — 2026-10-19

- Combined bucket and object matrix rows: ListBucket appears in the L slot of bucket/* and prefix rows while still being evaluated against the original bucket ARN.
- Shortened user headers to u:<name>, changed CSV delimiter to semicolon and fixed L/R/W/D slots with placeholders for missing permissions.
- Added bucket/prefix* object prefixes. Unsupported resource masks no longer spread uncertainty to clearly unrelated buckets.
- Notes include Action/Resource of limited rules. Added regressions for two direct policies, prefixes, bucket isolation and D alignment; updated both READMEs and Molecule assertions.

## 3.11.0 — 2026-10-19

- Added `matrix` mode: a controller CSV of direct built-in user and anonymous access from the current cluster, without changing MinIO.
- Supports L/R/W/D, unconditional Allow/Deny, concrete buckets, objects and prefixes; conditions, unsupported rules and mixed resource areas are explicitly marked uncertain.
- Group permissions are excluded; a dedicated collector preserves direct policy names and Sids without listing objects or reading versioning.
- CSV and explanations use mode 0600; native `--check` calculates the report without writing files.
- Added unit, local Ansible and Molecule matrix checks and updated both READMEs.

## 3.10.0 — 2026-10-17

- `versioning: false` preserves the initial Unversioned state of a new bucket; `mc version suspend` is only called when versioning is enabled.
- The role reads current state before changing it and skips matching settings; Enabled → false uses Suspended, while Suspended → true uses Enabled.
- Native `--check` does not read versioning for buckets that have not been created and skips mutating commands.
- Updated both READMEs with Disabled/Unversioned, Enabled and Suspended semantics; the fixture verifies transitions, new unversioned buckets and native check. Molecule verifies the initial state of buckets declared with false.

## 3.9.0 — 2026-10-16

- Removing a user, dropping a rule or changing its Sid removes unused owner policies named `policy-user-…` / `policy-grp-…`.
- Dry models surviving assignments and lists obsolete document deletions as `remove_policy`, including username changes with multiple rules.
- Apply rereads assignments after reconciliation and user deletion; policies with surviving owners, unrelated documents and policies of untouched protected users are retained.
- User deletion and policy candidate selection share the same protected deletion list; native `--check` does not execute mutating commands.
- Updated both READMEs and added coverage for renaming a user with three policies, shared assignments, protected users, Sid changes and dry/apply/check agreement.

## 3.8.0 — 2026-10-16

- Generated IAM policies use the `policy-` prefix: `policy-user-<name>-<Sid>` and `policy-grp-<name>-<Sid>`.
- JSON filenames match policy names, for example `policy-user-alice-ReadReports.json`.
- Updated both READMEs and checks for name generation, filename length, assignments, groups, dry summaries and exclusive policy ownership.

## 3.7.0 — 2026-10-16

- IAM policy documents use `<policy-name>.json` in `minio_configuration_policy_dir` instead of SHA-256 filenames; policy loading uses the same path.
- Added filename validation: no path separators or control characters, and at most 255 UTF-8 bytes including `.json`.
- Updated both READMEs and filename tests, including length limits and Unicode.

## 3.6.0 — 2026-10-16

- Successful assertions use `quiet: true`; loop labels show short entity names and Sids rather than entire mappings.
- Operational stages are included dynamically only for the selected mode, reducing skipped-task output while preserving stage tags.
- Without `-v`, the dry console summary omits full policy documents; complete details remain in the YAML report and appear on screen with `-v`.
- The TLS informational message requires `-v`; secret protection and validation failures remain enforced.
- Documented output controls through the standard Ansible callback and updated local tests.

## 3.5.0 — 2026-10-16

- Dry prints a summary of cluster additions, updates and removals; reads and local directory/file preparation are excluded from the plan.
- The plan compares bucket existence, versioning, statuses, JSON policies and assignments with current state; distinguishes policy creation from updates and includes group creation.
- Added `minio_configuration_dry_report_path` for a mode-0600 YAML report on the Ansible controller; an empty string disables saving and native `--check` does not write the report.
- Passwords are redacted; explicit password updates and public anonymous preset settings remain planned operations.
- Updated both READMEs and tests for state comparison, summaries, tag filtering and report persistence.

## 3.4.0 — 2026-10-16

- Completely removed the `clean` stage: its task file, import, `clean`/`never` tags, and cleanup of declared users and generated policy files.
- Removed cleanup operations from the dry plan; retained deletion of users omitted from inventory through the explicit `minio_configuration_users_delete` flag, respecting protected accounts.
- Updated tests, both READMEs and request documentation. Preserved changelog history.

## 3.3.0 — 2026-10-16

- Completely excluded bucket deletion, both for buckets omitted from inventory and declared buckets during `clean`; empty/nonempty buckets and their contents are preserved.
- Removed `minio_configuration_backets_delete`, its derived settings and bucket-deletion operations from the dry plan.
- `clean` only removes declared unprotected users and generated policy files on the delegate host.
- Updated READMEs, request documentation and tests; Molecule checks preservation of an empty bucket and data in a nonempty bucket omitted from inventory.

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
