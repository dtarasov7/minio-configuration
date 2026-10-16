# Роль `minio-configuration`

Версия роли: **3.8.0**.

## Режимы запуска — кратко

| Действие | Параметры `ansible-playbook` |
|---|---|
| Применить конфигурацию | `-e minio_configuration_mode=apply` (по умолчанию) |
| Экспортировать текущую конфигурацию | `-e minio_configuration_mode=export` |
| Посмотреть план без изменений | `-e minio_configuration_mode=dry` |

Режим задаётся переменной `minio_configuration_mode`: `apply`, `dry` или `export`.
Её можно определить в inventory (`group_vars`/`host_vars`) либо через `-e` при запуске.
`--check` — независимый штатный режим Ansible, который можно добавить к любому режиму роли.
Подробности и команды — в разделах ниже.

Роль управляет бакетами и пользователями MinIO в соответствии с описанием в переменных.
Бакеты, пустые и непустые, удаляет только администратор вручную на кластере.
Бакеты, отсутствующие в inventory, и их содержимое сохраняются.

## Что делает роль

- подключается к MinIO через `mc`;
- создает/изменяет бакеты из `minio_configuration_backets`;
- создает/изменяет пользователей из `minio_configuration_users`;
- назначает явные IAM-правила пользователям и группам, создаёт отдельную политику для каждого правила владельца;
- управляет анонимным доступом к бакетам и объектам;
- экспортирует текущие бакеты, политики, пользователей и группы в YAML-файл переменных для inventory;
- удаляет лишних пользователей только если включен флаг удаления;
- защищает администратора и пользователя метрик от автоматического удаления.

## Требования

До запуска роли установите `mc` (или `mcli`) и настройте административный alias на
`minio_configuration_delegate_host`. В `minio_configuration_mc_binary_path` укажите
полный путь с правильным именем бинарника. Роль выполняет `admin info <alias>` и
останавливается, если бинарник отсутствует, alias не настроен или доступ не работает.

Alias должен быть доступен пользователю, от которого Ansible выполняет команды,
с учётом `become`. Адрес сервера, учётные данные и TLS задаются в конфигурации `mc`.
Перед применением экспорта на другом сервере/delegate настройте alias отдельно.
Если включено удаление пользователей, добавьте нестандартные административные и
технические учётные записи в `minio_configuration_protected_users`.

## Переменные роли

| Переменная | По умолчанию | Описание |
|---|---|---|
| `minio_configuration_mode` | `apply` | `apply` — применение, `dry` — план без изменений, `export` — выгрузка |
| `minio_configuration_dry_report_path` | `{{ playbook_dir }}/minio-plan.yml` | YAML-сводка dry на контроллере; пустая строка отключает запись |
| `minio_configuration_nodes_group` | `minio_cluster` | Группа узлов MinIO |
| `minio_configuration_delegate_host` | первый узел группы | Хост, где выполняются команды `mc` |
| `minio_configuration_metrics_user` | `minio_prometheus` | Пользователь метрик (защищен от удаления) |
| `minio_configuration_alias` | `local` | Имя alias mc для всех команд и экспорта, например `production` |
| `minio_configuration_mc_binary_path` | `/usr/local/bin/mc` | Полный путь с именем бинарника, например `/opt/minio/mcli` |
| `minio_configuration_users_delete` | `false` | Разрешить удаление лишних пользователей |
| `minio_configuration_backets` | см. ниже | Desired-state бакетов |
| `minio_configuration_users` | см. ниже | Desired-state пользователей |
| `minio_configuration_export_path` | `{{ playbook_dir }}/minio-inventory.yml` | YAML-файл переменных на контроллере; родительский каталог должен существовать |
| `minio_configuration_policy_dir` | `/etc/minio/policies` | Каталог файлов политик на delegate-хосте |
| `minio_configuration_no_log` | `true` | Скрывать задачи с паролями |
| `minio_configuration_groups` | `[]` | Группы: `name`, необязательные `members`, `statements`, `status` (`enabled`/`disabled`) |
| `minio_configuration_hashi_vault_path_password` | `''` | Путь для использования в lookup HashiCorp Vault в переменных |
| `minio_configuration_protected_users` | `[minioadmin, minio_prometheus]` | Пользователи, которых нельзя удалять ролью |

### Значения по умолчанию

```yaml
minio_configuration_backets:
- name: b-default
  versioning: false
minio_configuration_users:
- name: u_default_ro
  secret_key: u_default_ro_password_change_me
  groups: []
  statements:
  - Effect: Allow
    Action:
    - s3:ListBucket
    Resource:
    - arn:aws:s3:::b-default
    Sid: ListBucket
  - Effect: Allow
    Action:
    - s3:GetObject
    Resource:
    - arn:aws:s3:::b-default/*
    Sid: ReadObjects
- name: u_default_rw
  secret_key: u_default_rw_password_change_me
  groups: []
  statements:
  - Effect: Allow
    Action:
    - s3:ListBucket
    Resource:
    - arn:aws:s3:::b-default
    Sid: ListBucket
  - Effect: Allow
    Action:
    - s3:GetObject
    - s3:PutObject
    - s3:DeleteObject
    - s3:AbortMultipartUpload
    Resource:
    - arn:aws:s3:::b-default/*
    Sid: ManageObjects
```

## Теги

- `install` — подготовка каталога политик; установка пакетов и скачивание `mc` не выполняются
- `config`
- `user`
- `backet`
- `ssl`

Задачи файла `pre-req.yaml` и проверка существующего alias в `config` помечены `always` и выполняются
при выборе рабочих тегов. `user` и `backet` также создают каталог политик, если нужны файлы политик. Вложенные проверки и задачи согласования получают необходимые теги.
Теги выбирают этапы применения и соответствующие части плана в режиме `dry`.
В режиме `export` выполняются проверки доступа и выгрузка; выбранные теги этапов не включают применение.

## Вывод Ansible

Без `-v` успешные проверки роли используют `assert: quiet: true`, а циклы выводят
имена бакетов, пользователей, групп и Sid вместо полных описаний. Неактивные этапы
не загружаются; ошибки проверок по-прежнему останавливают роль. Сообщение о TLS
показывается только с `-v`.

Сводка `dry` выводится без `-v`, но полные документы политик показываются только
с `-v`; YAML-отчёт на контроллере всегда содержит все подробности.
Обычные строки `TASK`, `ok`, `changed`, `skipping` формирует stdout callback Ansible.
Чтобы скрыть пропуски в стандартном callback, задайте в своём `ansible.cfg`:

```ini
[defaults]
display_skipped_hosts = false
```

Роль не изменяет настройки callback всего playbook. Параметр
`display_ok_hosts = false` скрывает успешные результаты, включая вывод `debug`
со сводкой dry; сохранение отчёта от этого не зависит.
Подробнее: [параметры стандартного callback Ansible](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/default_callback.html).
`no_log` используется для защиты секретов и не заменяет настройку объёма вывода.

## Пример inventory

```yaml
minio_cluster:
  hosts:
    minio1:
      ansible_host: 10.10.10.11
    minio2:
      ansible_host: 10.10.10.12
  vars:
    ansible_user: ansible
    ansible_become: true
    minio_configuration_mode: apply
    minio_configuration_alias: production
    minio_configuration_mc_binary_path: /usr/local/bin/mc
    minio_configuration_protected_users: [minio_admin, minio_prometheus]
    minio_configuration_backets:
    - name: project-a
      versioning: true
    minio_configuration_users:
    - name: app_ro
      secret_key: '{{ vault_app_secret }}'
      statements:
      - Effect: Allow
        Action:
        - s3:GetObject
        Resource:
        - arn:aws:s3:::project-a/*
        Sid: Rule1
```

## Применение конфигурации

При `minio_configuration_mode: apply` роль применяет бакеты, пользователей, группы и политики из inventory.
Для отдельных частей используйте `--tags user` или `--tags backet`.
Экспорт выполняется при `minio_configuration_mode: export`.

```bash
ansible-playbook -i inventory.ini roles/minio-configuration/examples/playbook.yml
```

## Анонимный доступ

В описании бакета укажите **одно** из полей: `anonymous` или `anonymous_policy`.
Без обоих полей существующая политика не изменяется.
`anonymous`: `none`/`private`, `download`, `upload`, `public` — стандартные режимы `mc`.
`none` удаляет публичную политику. `anonymous_policy` заменяет политику бакета целиком.

```yaml
minio_configuration_backets:
- name: downloads
  anonymous: download
- name: incoming
  anonymous: upload
- name: documents
  anonymous_policy:
    Version: '2012-10-17'
    Statement:
    - Sid: ReadPublicObjects
      Effect: Allow
      Principal:
        AWS:
        - '*'
      Action:
      - s3:GetObject
      Resource:
      - arn:aws:s3:::documents/public/*
```

Последняя политика разрешает анонимно читать известные ключи `public/*`, но не
разрешает `s3:ListBucket`: аноним не сможет получить список объектов. Для одного
объекта используйте полный ключ, например `arn:aws:s3:::documents/public/manual.pdf`.
Не добавляйте без необходимости `Deny` с `Principal: '*'` в политику бакета:
такой запрет распространяется и на авторизованных пользователей.

## Несколько правил пользователя

Прямые права задаются полем `statements`: списком стандартных IAM Statement.
`Effect`, `Action`, `Resource`, `Condition`, `Sid`, `NotAction`, `NotResource`
передаются в JSON без изменения. Для пользователя и группы используется одна форма записи.

```yaml
minio_configuration_users:
- name: app
  secret_key: '{{ vault_app_secret }}'
  statements:
  - Sid: ReadProjects
    Effect: Allow
    Action:
    - s3:GetObject
    Resource:
    - arn:aws:s3:::project-*/reports/*
    - arn:aws:s3:::documents/public/manual.pdf
  - Sid: UploadIncoming
    Effect: Allow
    Action:
    - s3:PutObject
    Resource:
    - arn:aws:s3:::incoming/team-a/*
  - Sid: NeverCreateBuckets
    Effect: Deny
    Action:
    - s3:CreateBucket
    Resource:
    - arn:aws:s3:::*
  - Sid: ListOnlyReports
    Effect: Allow
    Action:
    - s3:ListBucket
    Resource:
    - arn:aws:s3:::project-*
    Condition:
      StringLike:
        s3:prefix:
        - reports/*
```

`Resource` с ARN бакета используется для операций над бакетом; ARN с `/ключ`
или `/маска` — для операций над объектами. Явный `Deny` имеет приоритет над `Allow`,
в том числе полученным через другую политику или группу. Вызов ListObjects
в последнем примере должен содержать `prefix=reports/`.

Каждое правило пользователя и группы должно иметь непустой `Sid` из латинских
букв и цифр. Повтор одного `Sid` внутри одного владельца — ошибка до изменения MinIO.
У разных пользователей и групп одинаковые `Sid` разрешены. Проверка учитывает регистр.

Роль создаёт **отдельную политику для каждого правила**:

- `policy-user-<имя пользователя>-<Sid>`;
- `policy-grp-<имя группы>-<Sid>`.

Например, правило `ReadReports` у пользователя `alice` создаёт
`policy-user-alice-ReadReports`, а у группы `alice` —
`policy-grp-alice-ReadReports`. Одинаковые правила разных владельцев
не объединяются. Политика группы назначается только этой группе, а участники
получают её права через членство.

Файл документа политики на delegate-хосте называется `<имя политики>.json`
и находится в `minio_configuration_policy_dir`. Например:
`/etc/minio/policies/policy-user-alice-ReadReports.json`.
Это же имя файла используется при загрузке документа в MinIO.
Имя файла вместе с `.json` должно укладываться в 255 байт UTF-8;
разделители пути `/`, `\` и управляющие символы в имени не допускаются.
Права файла — `0600`.

Прямые назначения синхронизируются с текущим списком `statements`.
`statements: []` или отсутствие поля снимает все прямые политики владельца.
Повторный запуск обновляет документ с тем же именем. При удалении/переименовании
`Sid` прежняя политика отсоединяется, новая создаётся и назначается. Неиспользуемый
документ старой политики на сервере не удаляется автоматически.

Права задаются в `statements` каждого пользователя или группы. Перед любым
изменением конфигурации роль читает прямые назначения внутренних пользователей
и групп. Если политика с генерируемым именем уже назначена другой сущности
(даже созданной вне роли), запуск прерывается до её изменения. Роль не снимает
чужие назначения автоматически. Проверка отражает состояние на момент чтения;
не выполняйте параллельно ручные изменения назначений.

`secret_key` можно опустить для существующего пользователя. Для нового пользователя
это ошибка, а не повод назначить общий пароль. Если пароль задан, он обновляется
без удаления пользователя. `status: enabled|disabled` задаёт состояние учётной записи;
без `status` роль не выполняет отдельную команду переключения состояния.

Группы объявляются в `minio_configuration_groups`, а членство управляемого
пользователя — в его поле `groups`. Права группы задаются её полем `statements`. Роль создаёт группы, назначает им политики
и синхронизирует членство каждого управляемого пользователя **во всех текущих группах**.
Отсутствующее `groups` равнозначно `groups: []`: пользователь будет удалён из всех групп,
включая группы, не объявленные в inventory. Пользователи, не управляемые ролью,
при такой синхронизации не затрагиваются.

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
  secret_key: '{{ vault_bob_secret }}'
  groups: []
  statements: []
```

Alice получает чтение через группу `readers`, Bob удаляется из всех групп.
Без прямых `statements` пользователь получает права только через группы.
Удаление Alice из `readers` в её `groups` снимает эти права при следующем запуске.

Поле `members` у группы необязательно. Если оно отсутствует, роль сохраняет остальных
членов группы и синхронизирует только управляемых пользователей через `user.groups`.
Если `members` указано, это полный дополнительный список: неуказанные члены удаляются,
а пользователи из `user.groups` добавляются. Нельзя перечислять управляемого пользователя
в `group.members`, если его `user.groups` не содержит эту группу — preflight отклонит
противоречивую конфигурацию. Прямые политики группы синхронизируются с её `statements`;
пустой список или отсутствие поля снимает все прямые политики группы.

Группу с первым участником можно создать через `mc`; новую пустую группу создать
таким способом нельзя. Задайте хотя бы одного пользователя в `groups`, либо обновляйте
уже существующую пустую группу. `groups` пользователя может ссылаться и на существующие
группы вне `minio_configuration_groups`; их политики роль при этом не изменяет.

## Экспорт текущей конфигурации

На `minio_configuration_delegate_host` должны быть установлены `mc` и настроен alias.
Роль проверяет доступ через `mc admin info`, читает MinIO и сохраняет YAML на
**контроллере Ansible**. Alias, endpoint и учётные данные роль не изменяет.
Экспорт не изменяет объекты MinIO, в том числе при `minio_configuration_users_delete: true`.
Для выгрузки задайте `minio_configuration_mode: export` в inventory или через `-e`.

Из корня проекта:

```bash
ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.ini roles/minio-configuration/examples/playbook.yml \
  -e minio_configuration_mode=export \
  -e minio_configuration_export_path="$PWD/minio-configuration.yml"

ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.ini roles/minio-configuration/examples/playbook.yml \
  -e @minio-configuration.yml
```

Выгрузка содержит только три переменные верхнего уровня в следующем порядке:
`minio_configuration_users`, `minio_configuration_groups`, `minio_configuration_backets`.
Это файл переменных для `group_vars`, `vars_files` или `-e @файл.yml`; его также можно
перенести в секцию `vars` inventory. Обёртка `all/children/hosts`, параметры подключения,
alias, флаг удаления пользователей и отдельный список политик в файл не включаются.

Поля сущностей сохраняют порядок: `name` всегда идёт первым. У бакетов далее следуют
`anonymous` либо `anonymous_policy`, затем `versioning`. Например:

```yaml
minio_configuration_users: []
minio_configuration_groups: []
minio_configuration_backets:
- name: private-bucket
  anonymous: none
  versioning: false
```

Во всей выгрузке отключена алфавитная сортировка ключей. У пользователей и групп
`name` также идёт первым, остальные поля сохраняют порядок формирования. Документ
анонимной политики начинается с `Version`, затем `Statement`. В правилах порядок такой:
`Sid`, `Effect`, `Principal`/`NotPrincipal`, `Action`/`NotAction`,
`Resource`/`NotResource`, `Condition`; отсутствующие поля пропускаются.
Дополнительные поля и вложенные условия сохраняются без потери данных.

Списки `Action`, `NotAction`, `Resource` и `NotResource` выводятся компактно в одну строку.
Списки сущностей и правил остаются многострочными. Кавычки добавляются автоматически
по правилам YAML; значения и типы не меняются. Например:

```yaml
statements:
- Sid: ReadObjects
  Effect: Allow
  Action: ['s3:GetObject', 's3:ListBucket']
  Resource: ['arn:aws:s3:::xxx', 'arn:aws:s3:::xxx/*']
```

Экспорт включает все бакеты и их анонимные политики, обычных внутренних пользователей,
группы, статусы и членство пользователей в группах. Документы назначенных прямых
политик разворачиваются в `statements` каждого владельца; ссылки на общие политики
и неназначенные политики отдельно не выгружаются. При последующем применении создаются
отдельные политики владельцев без изменения исходных общих политик.
Стандартные анонимные режимы экспортируются как точные документы политики;
закрытый бакет — как `anonymous: none`. Права файла — `0600`.
Параметры подключения и удаления пользователей задаются отдельно в inventory.
Ошибка чтения прерывает экспорт; файл не заменяется частичным результатом.
Повторный запуск экспорта заменяет файл целиком.

При экспорте корректный уникальный `Sid` сохраняется. Если он отсутствует,
содержит недопустимые символы или повторяется между прямыми политиками одного владельца,
экспорт назначает устойчивый `Sid` вида `Export<sha256>`. Содержимое правил сохраняется.

Секретные ключи пользователей и администратора не извлекаются. На исходном сервере
экспорт можно применять без изменения паролей; при переносе на новый сервер добавьте
`secret_key` каждому пользователю и заранее настройте alias на новый сервер.
Встроенный root, service accounts, временные STS-ключи и внешние LDAP/OIDC-идентичности
не входят в список обычных пользователей `mc admin user list` и этим режимом не копируются.
Экспорт не является резервной копией объектов, lifecycle, квот, TLS или конфигурации сервера.
Сохраняется включённость versioning, но не его расширенные настройки (MFA, исключения).

Пароли прикладных пользователей можно задавать через inventory, Ansible Vault или
lookup HashiCorp Vault в переменных, например `secret_key: "{{ vault_app_secret }}"`.
Для таких lookup используется переменная `minio_configuration_hashi_vault_path_password`.

## Dry — просмотр операций

```bash
ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.ini roles/minio-configuration/examples/playbook.yml -e minio_configuration_mode=dry
ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.ini roles/minio-configuration/examples/playbook.yml -e minio_configuration_mode=dry --check
```

При `minio_configuration_mode: dry` роль читает состояние кластера и выводит сводку:
**«Планируем добавить»**, **«Планируем изменить»**, **«Планируем удалить»**.
В каждом списке указаны тип объекта, имя, операция и параметры; документы политик
на экране показываются только с `-v`. Сводка доступна
в `minio_configuration_plan`: ключи `add`, `change`, `delete`. При отсутствии
изменений выводится «Изменения в кластере не требуются».

В сводку входят бакеты, пользователи, группы, документы политик, назначения политик
и членство в группах. Чтения текущего состояния, подготовка каталогов и файлов
политик в сводку не включаются. Запросы чтения выполняются сразу для сравнения;
служебные задачи Ansible по-прежнему видны в обычном журнале запуска.
Изменяющие команды `mc` не выполняются.

Существующие бакеты не показываются как добавляемые. Совпадающие versioning,
статусы, явные JSON-политики и назначения пропускаются. Если у существующего
пользователя задан `secret_key`, смена ключа всегда включается в план: текущее
значение нельзя прочитать и сравнить. Ключи заменяются на `[REDACTED]`.
Публичные пресеты `anonymous: download|upload|public` показываются как планируемая
установка пресета: снимок содержит JSON-политику, а не исходное имя пресета.
Удаление назначения политики означает отзыв прямого назначения, а не удаление
документа политики на сервере. Бакеты не удаляются.

Та же сводка сохраняется **на Ansible-контроллере** в
`minio_configuration_dry_report_path` (по умолчанию `{{ playbook_dir }}/minio-plan.yml`).
Формат — YAML, права — `0600`; повторный запуск заменяет файл. Родительский каталог
должен существовать. Пустая строка отключает сохранение. С `--check` сводка выводится,
а файл не создаётся и не перезаписывается согласно штатному поведению `copy`.

```bash
ansible-playbook -i inventory.ini roles/minio-configuration/examples/playbook.yml \
  -e minio_configuration_mode=dry -e minio_configuration_dry_report_path=/tmp/minio-plan.yml
```

Для пользователей/групп: `-e minio_configuration_mode=dry --tags user`. Для бакетов замените `user` на `backet`.
Без тегов режим `dry` показывает полный план; `--skip-tags` исключает выбранные этапы.
План отражает момент чтения: параллельные изменения и разрешения на запись могут повлиять на применение.
Для выбора режима в inventory достаточно записи `minio_configuration_mode: dry`.

## Штатный check mode Ansible

`--check` не меняет `minio_configuration_mode`. Допустимы все сочетания:

```bash
ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.ini roles/minio-configuration/examples/playbook.yml --check
ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.ini roles/minio-configuration/examples/playbook.yml -e minio_configuration_mode=dry --check
ANSIBLE_ROLES_PATH=roles ansible-playbook -i inventory.ini roles/minio-configuration/examples/playbook.yml -e minio_configuration_mode=export --check
```

Задачи выбранного действия выполняются согласно поддержке check mode их модулями.
При обычном прогоне в check mode задачи применения проверяются модулями Ansible,
а изменяющие команды `mc` пропускаются. Запросы чтения выполняются для проверки доступа
и получения текущего состояния. Явный план `minio_configuration_plan` выводится в режиме `dry`.
С `export --check` состояние MinIO читается, а модуль `copy` проверяет запись выгрузки
без создания или перезаписи файла.

## Проверки

Molecule использует четыре Docker-контейнера `redos:7.3.6` и роль `minio-cluster`.
Сценарий проверяет изменение конфигурации, удаление пользователей, сохранение бакетов и данных, чтение/запись, запрет записи для пользователя с правом только чтения, анонимное чтение
без списка, маски объектов и бакетов, запрет создания бакетов и экспорт с повторным
применением. Образы и зависимости должны быть доступны заранее.

```bash
cd roles/minio-configuration
molecule test
```

Локальные проверки из корня проекта (без MinIO):

```bash
python -m unittest discover -s roles/minio-configuration/tests -v
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/export.yml -e minio_configuration_mode=export
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/tags.yml --tags user
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/dryrun.yml -e minio_configuration_mode=dry
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/check.yml --check
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/export-check.yml -e minio_configuration_mode=export --check
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/prerequisites.yml
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/groups.yml
ANSIBLE_ROLES_PATH=roles ansible-playbook -i roles/minio-configuration/tests/inventory.yml roles/minio-configuration/tests/ownership.yml
```

Форматы команд: [mc anonymous](https://docs.min.io/aistor/reference/cli/mc-anonymous/),
[mc admin policy](https://docs.min.io/aistor/reference/cli/admin/mc-admin-policy/).

## S3 Action для MinIO RELEASE.2025-10-15T17-29-55Z

Версия `20251015T172955Z` соответствует релизу `RELEASE.2025-10-15T17-29-55Z`.
Он использует `github.com/minio/pkg/v3 v3.1.3`: ниже полный перечень имён `s3:`,
распознаваемых валидатором IAM этой версии. Источники закреплены по версиям:
[go.mod релиза](https://github.com/minio/minio/blob/RELEASE.2025-10-15T17-29-55Z/go.mod),
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

Распознаваемое имя не гарантирует реализацию соответствующего API:
`s3:HeadBucket` помечен в библиотеке как неиспользуемый; не рассчитывайте на него
как на отдельное разрешение HEAD. Для обычного доступа к бакету используйте `s3:ListBucket`.
PUT/DELETE CORS бакета возвращают `NotImplemented` в этом серверном релизе, несмотря
на наличие имён `s3:PutBucketCors`/`s3:DeleteBucketCors` в валидаторе.
Это проверено по [маршрутам API релиза](https://github.com/minio/minio/blob/RELEASE.2025-10-15T17-29-55Z/cmd/api-router.go).

`CopyObject`, создание/завершение multipart и `HeadObject` — имена API, а не
отдельные Action из этого списка. Для копирования нужны `s3:GetObject` источника и
`s3:PutObject` назначения; для начала/записи/завершения multipart — `s3:PutObject`.
Для чтения метаданных объекта обычно используется `s3:GetObject`.
Расширения MinIO присутствуют в том же пространстве имён `s3:`.

## Ресурсы, не совпадающие с выражением

В IAM используются wildcard-маски: `*` — произвольная последовательность,
`?` — один символ; `*` может включать `/`. Это не регулярные выражения:
`^`, `$`, группы и отрицательные lookahead не поддерживаются как regex.
Для отрицания используйте `NotResource` вместо `Resource` либо отдельный `Deny`.
[Сопоставление масок](https://github.com/minio/pkg/blob/v3.1.3/wildcard/match.go),
[обработка NotResource](https://github.com/minio/pkg/blob/v3.1.3/policy/statement.go).

Читать объекты во всех бакетах, кроме `private-*`, и исключить объекты с префиксом
`secret/` в любом бакете:

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

Это даёт чтение известных ключей вне исключений, без разрешения списка объектов.
`NotResource` с `Allow` не запрещает другие политики: группа может дополнительно
разрешить исключённые объекты. Если исключение должно действовать при любых других
назначениях, задайте отдельный `Deny`:

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
  Resource:
  - arn:aws:s3:::private-*/*
  - arn:aws:s3:::*/secret/*
  - arn:aws:s3:::*/*.key
  Sid: Rule2
```

Для запрета чтения также конкретных версий объектов `.key` добавьте:

```yaml
- Effect: Deny
  Action:
  - s3:GetObject
  - s3:GetObjectVersion
  Resource:
  - arn:aws:s3:::*/*.key
  Sid: Rule1
```

Для операций над бакетами указывайте ARN **без `/объект`**. Например, получить
списки объектов в бакетах, имена которых не начинаются с `private-`:

```yaml
statements:
- Effect: Allow
  Action:
  - s3:ListBucket
  NotResource:
  - arn:aws:s3:::private-*
  Sid: Rule1
```

`s3:ListBucket` разрешает запрос списка целиком. Исключение `GetObject` для
`secret/*` не скрывает эти имена из разрешённого ListObjects; IAM не фильтрует
каждый элемент ответа. Если имена тоже должны быть недоступны, не выдавайте
`ListBucket` либо разрешайте только запросы с безопасным `s3:prefix`.
`ListAllMyBuckets` также не следует использовать как фильтр имён бакетов.
Для чтения конкретных версий учитывайте отдельное действие `s3:GetObjectVersion`.
