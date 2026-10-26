# Валидация фронтенда

Читать **только когда правишь** `web/**` или `modules/*/web/**`.
Когда что запускать — CLAUDE.md §3.

## Обязательный минимум после правки

```bash
node --check web/app.js
node --check web/components/<изменённый>.js     # каждый изменённый компонент
```

Баланс скобок CSS — читать **только так** (в файле битый UTF-8 хвост и base64-блоб шрифта):

```bash
python - <<'PY'
css = open('web/app.css', encoding='utf-8', errors='surrogateescape').read()
assert css.count('{') == css.count('}'), 'CSS braces!'
PY
```

Баланс `div`/`span` в `index.html`:

```bash
python - <<'PY'
import re
h = open('web/index.html', encoding='utf-8').read()
assert len(re.findall(r'<div\b', h)) == h.count('</div>'), 'div!'
assert len(re.findall(r'<span\b', h)) == h.count('</span>'), 'span!'
PY
```

## Компиляция Vue-шаблона — обязательна

Runtime-компилятор молча не рендерит битый шаблон, поэтому синтаксической проверки JS мало.

**`@vue/compiler-dom` в этом проекте не устанавливается** (зависимости не ставятся; см. политику
разрешений). Компилировать через уже лежащий в репозитории `web/vendor/vue.esm-browser.js`
с заглушкой `document`. Готовая обвязка — в тестах, которые это делают: искать в `tools/`
по `vue.esm-browser`. Для `index.html` извлекается содержимое `<div id="app">…</div>` и
прогоняется через тот же `compile()`.

Контроль эталоном из HEAD обязателен: если компиляция «зелёная» на заведомо битом шаблоне,
проверка вакуумна.

## Бейк-ин после правок `app.js`

```bash
grep -c "ref('{{ VERSION }}')" web/app.js     # ровно 1
grep -c CHANGELOG_B64 web/app.js              # ровно 1
```

## Хрупкие места

- **`web/app.css`** — ⚠️ править только через Python с `errors='surrogateescape'`; безопасно —
  дописывать в конец. Никаких построчных инструментов и обычных редакторов: замерено 16.09.2026 —
  одна правка обычным редактором переписала переводы строк у 252 строк, и коммит показал 252
  изменённые строки вместо одной. Содержимое тогда уцелело (сверка байтов: отличалась ровно одна
  строка, знаков замены не прибавилось), поэтому назад не чинили — но в истории владельца осталась
  шумная правка, а это ровно то, чего правило и не велит делать. Сверка после такой правки:
  `git diff --ignore-cr-at-eol <было> <стало> -- web/app.css` обязан показать только свои строки.
- **`web/ui3/**`** — второй интерфейс (UI 3.0). Файлы обычные, править можно свободно, но
  подключать что-либо из `web/app.css` / `web/app.js` запрещено: развязка — единственное, что
  делает переделки нового интерфейса безопасными для рабочего. Проверяется тем же обязательным
  минимумом (`node --check`, баланс скобок и тегов, компиляция шаблона) — `checks.py` берёт
  файлы `web/ui3/**` автоматически — плюс набором `tools/test_ui3_groundwork.py`.
- **`web/index.html`** — одна гигантская строка: править только по уникальным якорям.
- **Vue runtime-компилятор**: голый `<template>` без v-директивы молча не рендерится (Edge/V8);
  regex-литералы в атрибутах шаблона (`v-if="/x/.test(...)"`) роняют Firefox; на SVG `<g>` —
  `transform-box:view-box` + явный `transform-origin` (Firefox).
- **Tailwind статический**: произвольных классов (`w-[13px]`) в сборке НЕТ — новые
  фиксированные размеры задавать инлайном `style="..."`.
- **CSS-переменные темы**: `--fm-accent(-rgb)`, `--fm-surface-*`, `--fm-text-*`, `--fm-border-*`;
  для статусов есть `--fm-danger`, `--fm-success`, `--fm-error`. Переменной `--fm-warn` **нет** —
  для янтарного предупреждения использовать `#f5a524`.
- **Иконки** `<svg-icon name>` (`web/design/icons.js`): activity add alert archive bed bulb
  camera cap check clipboard close delete download drive edit file folder gear layers link
  module moon navigation nozzle pencil printer refresh sun trash undo upload.
- **CSS-инвариант 🔒**: `overscroll-behavior:contain` на
  `.ex-list/.ex-side/.ex-prev/.fm-users-list/.fm-audit-list/.fm-set-scroll/.diag-body/.fm-changelog-scroll`
  — убрать нельзя, иначе прокрутка списка листает страницу позади.

## Новый UI-компонент ядра

`web/components/<область>/X.js` (по образцу `InventoryPanel`) → импорт и
`__app.component('X', X)` в `app.js` → тег в `index.html` → проверки выше.

## Браузерные тесты

26 файлов в `tools/` поднимают headless-Edge. Они медленные и хрупкие; запускать точечно те,
что относятся к изменённой области. Профили браузера убираются **только по своему маркеру**;
глобальный kill по имени процесса запрещён — убьёт браузер владельца.

### Осмотр «на четырёх масштабах» — масштаб задаёт ШИРИНА ОКНА

Замерено 16.09.2026: `--force-device-scale-factor` в `extra_args` **ширину страницы не меняет**.
При одном `window_size` все четыре прогона дают ~1576 CSS-точек — то есть одна и та же раскладка
проверяется четырежды, а отчёт владельцу «осмотрено на четырёх масштабах» оказывается неточным.
Разные раскладки даёт только явный размер окна:

```python
for scale, size in (("0.8", (1920, 1200)), ("1.0", (1600, 1150)),
                    ("1.25", (1366, 900)), ("1.5", (1180, 820))):
    R = stage.run(JS, window_size=size, settle_ms=5200, path="/ui3",
                  extra_args=("--force-device-scale-factor=%s" % scale,), shot_path=shot)
```

→ 1897 / 1576 / 1343 / 1156 точек. `window.innerWidth` печатать в отчёте обязательно: без него
не видно, были ли ширины разными на самом деле.

Какой профиль нужен для конкретной правки — [profile-selection.md](profile-selection.md).
