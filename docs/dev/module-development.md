**Русский** · [English](module-development.en.md)

# Разработка модулей

Модуль — папка с `module.json`, необязательным `backend.py` и необязательным интерфейсом в `web/`.
Ставится архивом `.zip` в `DATA_DIR/modules/<id>/`. Готовые примеры —
[examples/modules/demo_free](../../examples/modules/demo_free) и
[examples/modules/demo_paid](../../examples/modules/demo_paid).

## module.json

```json
{"id": "my_module", "ru": "Мой модуль", "en": "My module", "version": "1.0.0",
 "icon": "module", "entry": "web/Panel.js", "settings_entry": "web/Settings.js",
 "core_contract": "1.0.0"}
```

- `id` — только латиница, цифры, `_` и `-`.
- `version` — номер выпуска, меняется свободно. `core_contract` — номер версии маршрутов модуля в
  карте прав ядра; меняется, только когда меняются маршруты.
- `entry` — компонент окна модуля (Vue, ES-модуль), `settings_entry` — ячейка в «Настройки → Модули».

## backend.py

```python
def register(core):
    core.add_route("hello", api_hello, ["GET"], policy_id="my_module.hello")
```

Возможности `core` (`ModuleCore` в `server.py`):

- маршруты `add_route(path, handler, methods, policy_id)` → `/api/mod/<id>/<path>`; платные —
  `add_paid_route(path, handler, feature, methods, policy_id)`;
- своя база `resolve_db("farm_<id>.db")` в папке данных;
- своя папка для файлов `data_dir()` → `<папка данных>/module_data/<id>` (создаётся при первом
  обращении, 16.10.2026): кэш, выгрузки, копии документов. Она переезжает вместе с папкой данных и
  НЕ удаляется при удалении или переустановке модуля. Папка программы модуля (`module_dir`) —
  только для чтения: её целиком заменяет каждая переустановка, замена подписанного пакета и
  возврат прежней версии. Ежедневная копия покрывает только базы `farm_*.db` — важные файлы модуль
  включает в свой провайдер резервной копии;
- принтеры и их состояние только для чтения: `printers()`, `printer_states()`,
  `get_printer_filament_snapshot()`, `get_printer_reported_filament()`;
- печатные хуки `add_hook(name, fn)`: `pre_print_check`, `after_dispatch`, `print_run_started`,
  `print_run_finished`;
- значки и филамент на карточках принтеров: `add_printer_badge_provider`,
  `add_printer_filament_provider`;
- лицензии и подписанный пакет: `license_documents()`, `license_revision()`, `install_id()`,
  `package_document()`, `import_module_file()` — см.
  [MODULE_LICENSING_FOUNDATION.md](../licensing/MODULE_LICENSING_FOUNDATION.md).

Права маршрута задаются только в `app/route_policy_registry.py` по `policy_id`. Маршрут, которого
там нет, при включённой защите входом доступен только администратору.

## Данные и резервные копии

У модуля с пользовательскими данными должен быть провайдер резервной копии в
`app/config_backup/module_providers.py` (или объявление, что данных нет). Без него полная копия
настроек откажет, пока модуль установлен — в том числе отключённый: отключённые и не
загрузившиеся модули тоже входят в копию. Поменял таблицы модуля — поправь провайдер и подними
его `backup_schema_version` с миграцией со старой схемы; ограничения UNIQUE объяви в
`TableSpec(unique=...)`, чтобы конфликт находился в плане, а не откатом восстановления.
Правила — [MODULE_BACKUP_CONTRACT.md](../MODULE_BACKUP_CONTRACT.md).

## Упаковка

```bash
python tools/module_package.py --module-dir path/to/my_module --out my_module-1.0.0.zip
```

С подписью и вшитыми ключами для платного компонента — раздел 9 документа об основе лицензирования.

## Правила

- Модуль не импортирует `server.py` и не лезет во внутренности ядра — только через `core`.
- Соседние файлы — через `core.import_module_file("helper.py")`: у подписанного пакета так они
  грузятся из проверенных байтов.
- Модуль не отправляет принтерам команд в обход ядра.
- Отказ лицензии не должен останавливать печать и прятать данные пользователя. Ядро само
  превращает отказ `pre_print_check` с `reason_class: "license"` в уведомление.
- Сроки (16.10.2026): `register()` — 30 с (иначе модуль не подключается, состояние `load_error`,
  причина `timeout`, поздние `add_route`/`add_hook` отклоняются); хуки `pre_print_check` — 20 с,
  `after_dispatch` — 30 с, `print_run_*` — 10 с. Не ответивший вовремя хук пропускается, печать
  идёт; пока он висит, следующие вызовы `pre_print_check` и `print_run_*` пропускаются сразу.
  `after_dispatch` не пропускается: каждый вызов идёт в своём потоке, срок ограничивает только
  ожидание отправки, а опоздавшее списание выполняется позже (одновременно зависших вызовов
  одного хука — не больше 8). Хуки вызываются в отдельном потоке.
- Левая внешняя катушка H2D — внутренний слот `-2`. Хук, который её понимает, объявляет
  именованный параметр `ext_left`; остальным ядро `-2` не показывает (план с пустыми слотами,
  `after_dispatch` пропускается).
