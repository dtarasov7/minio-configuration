#!/usr/bin/env bash
# Check the lab-test inventory policy using the installed minio-client binary.
set -euo pipefail

admin_alias="${MINIO_LAB_ADMIN_ALIAS:-lab}"
endpoint="${MINIO_LAB_ENDPOINT:-http://127.0.0.1:9000}"
test_password="${MINIO_LAB_TEST_PASSWORD:-Test-Only-123}"
command -v minio-client >/dev/null
minio-client admin info "$admin_alias" >/dev/null

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/minio-access-check.XXXXXX")"
namespace="access-check-$(date +%Y%m%dT%H%M%S)-${work_dir##*.}"
inside="lab-other/other/$namespace"
outside="lab-other/$namespace"
cleanup_targets=("$inside/existing.txt" "$inside/new.txt" "$outside/existing.txt" "$outside/forbidden.txt")

cleanup() {
    local result=$?
    trap - EXIT
    for target in "${cleanup_targets[@]}"; do
        if ! minio-client --json stat "$admin_alias/$target" > "$work_dir/cleanup.log" 2>&1; then
            if grep -Eiq 'NoSuchKey|NoSuchObject|does not exist|not found' "$work_dir/cleanup.log"; then
                continue
            fi
            printf 'Не удалось проверить тестовый объект для очистки: %s\n' "$target" >&2
            cat "$work_dir/cleanup.log" >&2
            result=1
            continue
        fi
        if ! minio-client rm "$admin_alias/$target" >/dev/null 2>&1; then
            printf 'Не удалось удалить тестовый объект: %s\n' "$target" >&2
            result=1
        fi
    done
    rm -rf -- "$work_dir"
    exit "$result"
}
trap cleanup EXIT

mkdir -m 0700 "$work_dir/client"
minio-client --config-dir "$work_dir/client" alias set test "$endpoint" lab-test "$test_password" >/dev/null
unset test_password
printf 'initial test content\n' > "$work_dir/original.txt"
printf 'updated test content\n' > "$work_dir/updated.txt"

# Seed uniquely named objects through the preconfigured administrative alias.
minio-client cp "$work_dir/original.txt" "$admin_alias/$inside/existing.txt" >/dev/null
minio-client cp "$work_dir/original.txt" "$admin_alias/$outside/existing.txt" >/dev/null

expect_denied() {
    local description=$1
    shift
    if "$@" > "$work_dir/denied.log" 2>&1; then
        printf 'FAIL: операция неожиданно разрешена: %s\n' "$description" >&2
        return 1
    fi
    if ! grep -Eiq 'AccessDenied|access[[:space:]]+denied|insufficient permissions' "$work_dir/denied.log"; then
        printf 'FAIL: вместо отказа доступа получена другая ошибка: %s\n' "$description" >&2
        cat "$work_dir/denied.log" >&2
        return 1
    fi
    printf 'PASS: запрещено — %s\n' "$description"
}

# L: list the permitted prefix and its nested prefix. Both must return a seeded object.
minio-client --config-dir "$work_dir/client" --json ls test/lab-other/other/ > "$work_dir/list.json"
grep -Fq "$namespace" "$work_dir/list.json"
minio-client --config-dir "$work_dir/client" --json ls "test/$inside/" > "$work_dir/list.json"
grep -Fq 'existing.txt' "$work_dir/list.json"
printf 'PASS: список объектов внутри other/\n'

# R: known object names can be read both inside and outside other/.
minio-client --config-dir "$work_dir/client" cat "test/$inside/existing.txt" > "$work_dir/read.txt"
cmp "$work_dir/original.txt" "$work_dir/read.txt"
minio-client --config-dir "$work_dir/client" cat "test/$outside/existing.txt" > "$work_dir/read.txt"
cmp "$work_dir/original.txt" "$work_dir/read.txt"
printf 'PASS: чтение по известному имени внутри и вне other/\n'

# W/D: create, overwrite, verify contents and delete inside the permitted prefix.
minio-client --config-dir "$work_dir/client" cp "$work_dir/original.txt" "test/$inside/new.txt" >/dev/null
minio-client --config-dir "$work_dir/client" cp "$work_dir/updated.txt" "test/$inside/new.txt" >/dev/null
minio-client --config-dir "$work_dir/client" cat "test/$inside/new.txt" > "$work_dir/read.txt"
cmp "$work_dir/updated.txt" "$work_dir/read.txt"
minio-client --config-dir "$work_dir/client" rm "test/$inside/new.txt" >/dev/null
minio-client --json ls "$admin_alias/$inside/" > "$work_dir/after-delete.json"
if grep -Fq 'new.txt' "$work_dir/after-delete.json"; then
    printf 'FAIL: объект после удаления всё ещё существует\n' >&2
    exit 1
fi
printf 'PASS: создание, перезапись и удаление внутри other/\n'

# Negative checks must fail specifically with AccessDenied.
expect_denied 'список всего lab-other' \
    minio-client --config-dir "$work_dir/client" --json ls test/lab-other/
expect_denied 'список постороннего префикса' \
    minio-client --config-dir "$work_dir/client" --json ls "test/$outside/"
expect_denied 'создание объекта вне other/' \
    minio-client --config-dir "$work_dir/client" --json cp "$work_dir/updated.txt" "test/$outside/forbidden.txt"
expect_denied 'перезапись объекта вне other/' \
    minio-client --config-dir "$work_dir/client" --json cp "$work_dir/updated.txt" "test/$outside/existing.txt"
expect_denied 'удаление объекта вне other/' \
    minio-client --config-dir "$work_dir/client" --json rm "test/$outside/existing.txt"

# Verify that the denied overwrite/delete attempts left the original data intact.
minio-client cat "$admin_alias/$outside/existing.txt" > "$work_dir/read.txt"
cmp "$work_dir/original.txt" "$work_dir/read.txt"
printf 'Все проверки прав lab-test пройдены. Удаляем только объекты этого запуска.\n'
