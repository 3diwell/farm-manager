# 3DIWELL Farm Manager — ревизия селекторов обучения

Дата проверки: 2026-06-29  
База проверки: версия после `3DIWELL_tour_update_15_fix_language_highlight.zip`

## Правило безопасности

Проверялись только элементы интерактивного обучения: селекторы подсветки, точки привязки, линии-выноски и позиция окна описания. Сервер, API, базы, реальные принтеры, Quick Tasks, проекты и логика печати не менялись.

## Что проверялось

Для каждого пункта обучения проверялось:

1. селектор существует в `web/index.html` или создаётся демо-данными тура;
2. селектор указывает на тот элемент, который описан в тексте пункта;
3. подсветка не должна захватывать соседние элементы без необходимости;
4. окно описания не должно намеренно перекрывать важный подсвеченный элемент;
5. точка привязки и линия-выноска должны быть построены от правильного элемента.

## Найденные и исправленные замечания

### 1. Пункт 10 — «Диагностика»

**Было:** пункт показывал демо-окно диагностики, но селектор подсветки оставался на шестерёнке настроек:

```text
[data-tour="settings"]
```

**Стало:** подсветка перенесена на тело демо-журнала диагностики:

```text
[data-tour="diag"]
```

В `web/index.html` для демо-окна добавлен отдельный безопасный маркер:

```html
<div data-tour="diag" data-scene="diagbody" ...>
```

Это не настоящее окно диагностики и не серверный лог. Это только визуальная демо-сцена обучения.

### 2. Пункт 18 — «Карточка и цвета статусов»

**Было:** использовался общий селектор карточки принтера:

```text
[data-tour="pcard"]
```

Во время тура обычно остаётся только демо-принтер, но такой селектор всё равно менее точный.

**Стало:** пункт привязан напрямую к демо-карточке принтера:

```text
#tour-demo-printer
```

Теперь пункт 18, 19 и 20 последовательно работают с одной и той же демо-карточкой принтера.

## Таблица ревизии всех пунктов

| № | id шага | Селектор | Статус | Комментарий |
|---:|---|---|---|---|
| 1 | `welcome` | `[data-tour="header"]` | OK | Подсвечивает шапку/логотип, соответствует приветствию. |
| 2 | `connection-sync` | `[data-tour="broker"]` | OK | Подсвечивает Data Broker и индикатор синхронизации. |
| 3 | `language` | `[data-tour="lang"]` | OK | После предыдущей правки подсвечивает только EN/RU, без шестерёнки. |
| 4 | `settings-open` | `[data-tour="settings"]` | OK | Подсвечивает кнопку настроек. |
| 5 | `settings-edition` | `[data-tour="set-edition"]` | OK | Подсвечивает блок «Режим интерфейса» в настройках. |
| 6 | `settings-appearance` | `[data-tour="set-theme"]` | OK | Подсвечивает тему и шрифт. |
| 7 | `settings-dates` | `[data-tour="set-dates"]` | OK | Подсвечивает даты создания и сроки. |
| 8 | `settings-slicer` | `[data-tour="set-slicer"]` | OK | Подсвечивает выбор слайсера. |
| 9 | `settings-tools` | `[data-tour="set-tools"]` | OK | Подсвечивает блок инструментов. |
| 10 | `diagnostics-demo` | `[data-tour="diag"]` | Исправлено | Теперь подсвечивает демо-журнал диагностики, а не шестерёнку. |
| 11 | `settings-access-roles-audit` | `[data-tour="set-security"]` | OK | Подсвечивает доступ, роли и аудит. |
| 12 | `settings-modules` | `[data-tour="set-modules"]` | OK | Подсвечивает блок модулей. |
| 13 | `settings-about` | `[data-tour="set-about"]` | OK | Подсвечивает блок «О программе». |
| 14 | `printers-overview` | `[data-tour="printers"]` | OK | Подсвечивает колонку принтеров целиком. |
| 15 | `printers-sort` | `[data-tour="psort"]` | OK | Подсвечивает переключатель сортировки. |
| 16 | `printers-view` | `[data-tour="pview"]` | OK | Подсвечивает переключатель список/сетка. |
| 17 | `printers-add` | `[data-tour="add-printer"]` | OK | Подсвечивает кнопку добавления принтера. |
| 18 | `printer-card-grid` | `#tour-demo-printer` | Исправлено | Теперь привязка точная к демо-принтеру, а не к общему селектору карточек. |
| 19 | `printer-card-expanded` | `#tour-demo-printer` | OK | Подсветка и нумерованные метки проверены после правки превью. |
| 20 | `printer-ams-print` | `#tour-demo-printer` | OK | Подсвечивает демо-принтер во время сцены печати/AMS. |
| 21 | `projects-overview` | `#tour-demo-project-board` | OK | Подсвечивает демо-панель проекта. |
| 22 | `projects-create` | `[data-tour="newproj"]` | OK | Подсвечивает кнопку создания проекта. |
| 23 | `projects-import-files` | `#tour-demo-project-import` | OK | Подсвечивает импорт файлов в демо-проекте. |
| 24 | `projects-part-counters` | `#tour-demo-project-table` | OK | Подсвечивает таблицу счётчиков и подсказки колонок. |
| 25 | `projects-label-objects` | `#tour-demo-project-labels` | OK | Подсвечивает блок Label Objects. |
| 26 | `projects-counting-fallback` | `#tour-demo-project-fallback` | OK | Подсвечивает предупреждение о невозможности надёжного подсчёта. |
| 27 | `projects-card` | `#tour-demo-projcell` | OK | Подсвечивает карточку Demo Project в реальной сетке проектов. |
| 28 | `projects-archive` | `[data-tour="archivebtn"]` | OK | Подсвечивает кнопку архива. |
| 29 | `quick-tasks-overview` | `[data-tour="qtsection"]` | OK | Подсвечивает раздел Quick Tasks. |
| 30 | `quick-tasks-drop` | `[data-tour="qtdrop"]` | OK | Подсвечивает зону перетаскивания файлов. |
| 31 | `quick-tasks-load` | `[data-tour="qtsection"]` | OK | Подсвечивает Quick Tasks на фоне демо-сцены загрузки файла. |
| 32 | `quick-tasks-row` | `#tour-demo-staging` | OK | Подсвечивает демо-строку файла в Quick Tasks. |
| 33 | `quick-tasks-find-printer` | `#tour-demo-status` | OK | Подсвечивает кликабельный статус файла. |
| 34 | `suggestions-alerts` | `[data-tour="suggest"]` | OK | Подсвечивает блок предложений и предупреждений. |
| 35 | `finish` | `[data-tour="header"]` | OK | Финальный шаг возвращает подсветку к шапке. |

## Проверки после ревизии

После исправлений нужно запускать:

```bash
node --check web/app.js
node --check web/composables/tourSteps.js
node --check web/tour/validate-tour.mjs
node web/tour/validate-tour.mjs
python3 -m py_compile server.py app/*.py
```

Ожидаемый результат валидатора: `OK. Обучение прошло автоматическую проверку.`
