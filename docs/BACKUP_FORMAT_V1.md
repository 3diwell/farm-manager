# Формат резервной копии конфигурации `.3diwell-backup` — версия 1

**Статус: ЗАМОРОЖЕН (Alpha 2.827). Этот документ описывает ПОСТОЯННЫЙ публичный контракт.**
Значения версий и смысл байтов при них неизменны навсегда. Несовместимые изменения делаются
ТОЛЬКО повышением версии и добавлением миграции — см. [BACKUP_COMPATIBILITY_CONTRACT.md](BACKUP_COMPATIBILITY_CONTRACT.md).

> V1 остаётся поддерживаемым навсегда; новые экспорты используют V2 (см. [BACKUP_FORMAT_V2.md](BACKUP_FORMAT_V2.md)). Смысл v1 ниже не меняется.

Чистая реализация: `app/config_backup/` (крипто/контейнер/миграции не импортируют `server.py`).
Адаптер хранилища и маршруты — в `server.py`.

## Назначение

Логический, версионированный, зашифрованный снимок ПОЛЬЗОВАТЕЛЬСКОЙ КОНФИГУРАЦИИ фермы:
настройки ядра и парк принтеров (с идентичностью и доступом). Это **не** копия SQLite, **не**
копия `config.json`, **не** ZIP папки данных и **не** pickle. Копия предназначена пережить годы
и смену мажорных версий приложения.

## Внешний контейнер (`container_format_version = 1`)

Файл `.3diwell-backup` — это ZIP ровно с двумя записями и строго фиксированными именами:

| запись        | содержимое                                                        |
|---------------|-------------------------------------------------------------------|
| `header.json` | НЕсекретные метаданные + параметры шифрования (соль/nonce/KDF)     |
| `payload.enc` | шифртекст логического payload (AES-256-GCM)                        |

Строгий разбор (`app/config_backup/container_v1.py`): ровно две записи, никаких лишних/повторных
имён, путей с `/`, `\`, `..`, symlink, вложенных архивов, ZIP-с-паролем; жёсткие лимиты размера и
анти-ZIP-bomb (порог соотношения сжатия). Данные из копии **никогда не исполняются**.

### `header.json` (несекретный)

```json
{
  "format_id": "com.3diwell.farm-manager.configuration-backup",
  "container_format_version": 1,
  "payload_schema_version": 1,
  "created_by_app": "3DIWELL Farm Manager Alpha 2.827",
  "created_at": "2026-07-24 12:00:00",
  "printer_count": 3,
  "module_count": 0,
  "required_reader_capabilities": ["aes256gcm-scrypt-v1"],
  "encryption": {
    "kdf": "scrypt", "n": 32768, "r": 8, "p": 1,
    "salt": "<base64>", "cipher": "AES-256-GCM", "nonce": "<base64>"
  }
}
```

`required_reader_capabilities` — список возможностей, БЕЗ которых копию читать нельзя. Незнакомая
обязательная возможность → безопасный отказ (неизвестное нельзя трактовать как известное).

## Шифрование (заморожено)

- **KDF:** scrypt (`cryptography.hazmat`), выход 256 бит. Выпуск v1: `n=2^15 (32768), r=8, p=1`.
  Границы навсегда: `n ∈ [2^14, 2^20]` (floor против слабости, ceiling против DoS), `r ∈ [8,32]`,
  `p ∈ [1,16]`, `n` — степень двойки.
- **Шифр:** AES-256-GCM.
- **AAD:** канонические байты `header.json`. Подмена любого поля header ломает расшифровку.
- **Соль и nonce** случайны на КАЖДУЮ копию.
- **Пароль:** UTF-8, **без** trim и **без** нормализации Unicode (правило зафиксировано). Пустой
  пароль запрещён.
- **Без oracle:** неверный пароль и повреждение дают ОДИН и тот же код
  `backup_corrupted_or_wrong_password` — по ошибке нельзя отличить одно от другого.
- **Потерянный пароль восстановить невозможно.** UI обязан честно предупреждать об этом.

Никакого самописного шифра, XOR, Fernet, ZIP-пароля или «только HMAC».

## Логический payload (`payload_schema_version = 1`)

Внутри `payload.enc` — канонический JSON (sort_keys, компактно, UTF-8):

```json
{
  "manifest": {"payload_schema_version": 1, "created_by": "...",
               "include_secrets": true, "sections": ["core", "printers", "modules"]},
  "core": {"schema_version": 1, "values": {...}, "machine_bound": {...}, "extensions": {}},
  "printers": [{"stable_id": "...", "adapter": "bambu", "adapter_schema_version": 1,
                "display_name": "...", "model": "...", "enabled": true,
                "connection": {"ip": "...", "port": 8883, "gen": "auto", "serial": "..."},
                "options": {"order_idx": 0},
                "credentials": {"token": "<секрет — только внутри шифра>"},
                "extensions": {}}],
  "modules": [],
  "extensions": {}
}
```

Версии секций (`core`/`printers`/`module`) и схем адаптеров растут **независимо** от
`payload_schema_version` и **никогда** не равны `APP_VERSION` (та — лишь метаданные).

### Что переносится, а что нет (реестр `settings_registry.py`)

Каждая постоянная настройка ядра классифицирована (тест `test_config_backup_contract.py`
краснеет, если в `server.py` появился незарегистрированный ключ):

- **portable** → переносится (`core.values`): `lan_access_enabled` (с предупреждением о сети),
  `project_print_enabled`, `modules_disabled`, `net_monitor`, `security_enabled` (с предупреждением),
  `slicer_callback_enabled`, `printer_files_read_enabled`, `printer_files_delete_enabled`
  (**деструктив → импортируется как OFF**).
- **machine_bound** → в `core.machine_bound`, по умолчанию **не применяется** (пути/порт этой
  машины): `data_dir`, `server_port`, `archive_dir`, `slicer_path`.
- **operational / secret_derived** → **исключены** из снимка: `pending_server_port`,
  `previous_server_port`, `migrate_from`, `slicer_callback_token_hash`,
  `slicer_callback_token_created_at`.

Секреты (`token`/checkcode/API-ключ принтера) сохраняются **только** внутри AES-GCM — в открытом
виде их нет нигде. Кэш `last_parts` (операционный) не переносится.

## Восстановление (state machine)

`READ → DECRYPT → VALIDATE → MIGRATE(в памяти) → PLAN → CONFIRM → PRE-SNAPSHOT(журнал) →
APPLY(атомарно) → VERIFY → COMMIT | ROLLBACK`.

- **PLAN** — только чтение: что добавится/изменится по секциям, предупреждения (сеть/безопасность/
  деструктив), нужен ли рестарт.
- **APPLY** — `config.json` атомарно (temp+fsync+os.replace); `app_settings`/`printers`
  транзакциями SQLite. Сбой на любом шаге → компенсирующий откат к pre-image.
- **Журнал восстановления** (`recovery.py`) живёт в `DATA_DIR`, переживает падение процесса:
  `prepared → applying → committed_pending_verify → complete`; при сбое `→ rollback_required →
  complete`. После завершения pre-image **затирается** (секреты не задерживаются на диске).
- Идентичность принтеров (`stable_id`) сохраняется; принтеры «только на текущей машине»
  не удаляются.

## Границы доступа

Экспорт/inspect/restore — **только system-admin и только локально** (loopback). Restore
запрещён при активной печати и выполняется по одному за раз. Пароль копии не логируется,
не сохраняется и не отправляется в запросы к принтерам.

## Замороженная фикстура

`tools/fixtures/config_backup/v1/sample.3diwell-backup` — эталон формата v1 (снят один раз).
`test_config_backup_compatibility_forever.py` требует, чтобы любая будущая версия его
восстанавливала. **Фикстуру нельзя менять или перегенерировать никогда** (сверяется по SHA-256).
