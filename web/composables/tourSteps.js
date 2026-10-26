// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
/*
============================================================================
3DIWELL Farm Manager — сценарий интерактивного обучения

Этот файл содержит только порядок шагов, тексты, селекторы подсветки и
параметры демонстрационных сцен. Здесь НЕ должно быть запросов к серверу,
изменения принтеров, расчётов, API или логики производства.

Безопасное правило правок:
  - можно менять title/text/more/card/sel/order/group/id;
  - можно добавлять новый шаг, если подсвечиваемый элемент уже есть в index.html;
  - если нужен новый элемент интерфейса, сначала добавить data-tour в index.html;
  - если для обучения нужна новая демо-сцена или изменение поведения приложения,
    это уже правка app.js — перед такой правкой нужно отдельно проверить риски.

Термины, которые используем в текстах обучения:
  - «файл печати» — готовый g-code / 3MF, который можно отправить на принтер;
  - «модель» — STL / STEP или другой файл, который ещё нужно нарезать;
  - «плита» — набор деталей внутри одного файла печати;
  - «На плате» — сколько конкретной детали печатается одним файлом;
  - «Нужно» — требуемое количество деталей;
  - «Напечат.» — принятое готовое количество;
  - «перепечатка» — повторная печать детали после брака или rework;
  - Tasks оставляем как название раздела интерфейса.

Допустимые scene в текущем app.js:
  diag    — демонстрация окна диагностики;
  print   — демонстрация выбора файла и AMS-слота;
  load    — демонстрация загрузки файла в Tasks;
  project — демонстрационная панель проекта и подсчёта деталей;
  attach  — старая сцена привязки файла к детали, сейчас не используется;
  slice   — старая сцена открытия модели в слайсере, сейчас не используется;
  reveal  — старая сцена открытия расположения файла, сейчас не используется.

Поля шага:
  id      — стабильный внутренний идентификатор шага;
  group   — группа шага; используется и для навигации, и для короткого тура;
  sel     — CSS-селектор подсвечиваемого элемента;
  title   — английский ключ заголовка, перевод хранится в RU в app.js;
  text    — короткий основной текст карточки, перевод хранится в RU в app.js;
  more    — необязательный подробный текст для раскрываемого блока «Подробнее»;
  card    — позиция карточки: below/above/tr/br/tl/bl/left/right/top/bottom;
  view    — grid/list для временного переключения вида принтеров;
  scene   — демо-сцена;
  expand  — раскрыть демо-карточку принтера;
  marks   — цифровые бейджи на элементах управления.
============================================================================
*/


// Отображаемые названия разделов обучения.
// Используются карточкой тура, кнопкой «Пропустить раздел» и валидатором.
export const tourGroupLabels = {
    "basics": "Basics",
    "settings": "Settings",
    "printers": "Printers",
    "projects": "Projects and production",
    "quick_tasks": "Tasks",
    "alerts": "Suggestions and alerts",
    "finish": "Finish"
};

// Порядок разделов нужен только для читаемости и будущих проверок.
export const tourGroupOrder = [
    "basics",
    "settings",
    "printers",
    "projects",
    "quick_tasks",
    "alerts",
    "finish"
];

export const tourSteps = [
    {
        "id": "welcome",
        "group": "basics",
        "sel": "[data-tour=\"header\"]",
        "card": "below",
        "title": "Welcome",
        "text": "Farm Manager combines printers, projects and Tasks on one screen. This tour uses temporary demo data and does not change your real printers, projects or tasks.",
        "more": "During the tour a demo printer, demo project and demo task may appear. They exist only while the tour is open. When you close the tour, the previous interface state is restored."
    },
    {
        "id": "connection-sync",
        "group": "basics",
        "sel": "[data-tour=\"broker\"]",
        "card": "below",
        "title": "Connection and sync",
        "text": "This indicator shows the connection to the local 3DIWELL server. Green means connected, red means disconnected. The sync icon shows when changes are being saved automatically."
    },
    {
        "id": "language",
        "group": "basics",
        "sel": "[data-tour=\"lang\"]",
        "card": "below",
        "title": "Interface language",
        "text": "Use these buttons to switch the interface between Russian and English. The selected language is remembered in this browser."
    },
    {
        "id": "settings-open",
        "group": "settings",
        "sel": "[data-tour=\"settings\"]",
        "card": "below",
        "title": "Settings",
        "text": "The gear opens Settings. Here you configure the interface mode, appearance, dates, slicer, tools, access, modules and information about the program."
    },
    {
        "id": "settings-edition",
        "group": "settings",
        "sel": "[data-tour=\"set-edition\"]",
        "tab": "general",
        "card": "left",
        "openSettings": true,
        "title": "Interface mode",
        "text": "Choose the interface mode. It only changes which sections are visible. All program features are free; only some separate modules are paid.",
        "more": "Personal is for one workstation and hides projects and deadlines. Team and Business show every section. Access & audit is available in any mode."
    },
    {
        "id": "settings-appearance",
        "group": "settings",
        "sel": "[data-tour=\"set-theme\"]",
        "tab": "general",
        "card": "left",
        "openSettings": true,
        "title": "Appearance",
        "text": "Appearance controls the interface theme and font. Use it to make the screen easier to read in your workshop.",
        "more": "The theme switches between light and dark mode. The font setting changes the text style across the interface. Both choices are saved on this computer."
    },
    {
        "id": "settings-dates",
        "group": "settings",
        "sel": "[data-tour=\"set-dates\"]",
        "tab": "general",
        "card": "left",
        "openSettings": true,
        "title": "Dates and deadlines",
        "text": "Enable creation dates and project deadlines. The warning period decides when a project starts turning yellow before the deadline."
    },
    {
        "id": "settings-slicer",
        "group": "settings",
        "sel": "[data-tour=\"set-slicer\"]",
        "tab": "print",
        "card": "left",
        "openSettings": true,
        "title": "Default slicer",
        "text": "Choose which slicer opens model files: automatic detection or a specific program. This is used when a model needs to be prepared for printing."
    },
    {
        "id": "settings-tools",
        "group": "settings",
        "sel": "[data-tour=\"set-tools\"]",
        "tab": "system",
        "card": "left",
        "openSettings": true,
        "title": "Tools and diagnostics",
        "text": "Service tools are grouped here. Diagnostics opens a live server log that helps find the cause of a problem."
    },
    {
        "id": "diagnostics-demo",
        "group": "settings",
        "sel": "[data-tour=\"diag\"]",
        "card": "br",
        "scene": "diag",
        "title": "Diagnostics",
        "text": "This demo shows the diagnostics log. It displays server events for troubleshooting and does not send commands to printers."
    },
    {
        "id": "settings-access-roles-audit",
        "group": "settings",
        "sel": "[data-tour=\"set-security\"]",
        "tab": "system",
        "card": "left",
        "openSettings": true,
        "title": "Access, roles and audit",
        "text": "Access control lets different people use different parts of the farm interface.",
        "more": "Administrator has full control. Operator manages printing and projects. Assembler marks finished parts and sends parts to rework. Observer is view-only. Important actions are written to the audit log."
    },
    {
        "id": "settings-modules",
        "group": "settings",
        "sel": "[data-tour=\"set-modules\"]",
        "tab": "modules",
        "card": "left",
        "openSettings": true,
        "title": "Modules",
        "text": "Optional modules appear here. Active modules can be opened from this menu; unavailable modules are marked as coming soon."
    },
    {
        "id": "settings-about",
        "group": "settings",
        "sel": "[data-tour=\"set-about\"]",
        "tab": "general",
        "card": "left",
        "openSettings": true,
        "title": "About the program",
        "text": "About shows the program name, build version, interface mode, website and support links. This is useful when reporting a problem."
    },
    {
        "id": "printers-overview",
        "group": "printers",
        "sel": "[data-tour=\"printers\"]",
        "title": "Your printers",
        "text": "This column is the printer fleet. Each card shows status, progress and print time. Sorting and the view switch are at the top."
    },
    {
        "id": "printers-sort",
        "group": "printers",
        "sel": "[data-tour=\"psort\"]",
        "title": "Sort printers",
        "text": "Sort printers by status or by name. This helps quickly find a free, busy or problem printer."
    },
    {
        "id": "printers-view",
        "group": "printers",
        "sel": "[data-tour=\"pview\"]",
        "title": "List and grid view",
        "text": "Switch between a compact grid and a detailed list. The grid shows many printers at once; the list gives full controls for each printer."
    },
    {
        "id": "printers-add",
        "group": "printers",
        "sel": "[data-tour=\"add-printer\"]",
        "title": "Add a printer",
        "text": "Add Printer opens the model catalog. Choose the printer model, enter its connection details and add it to the farm."
    },
    {
        "id": "printer-card-grid",
        "group": "printers",
        "sel": "#tour-demo-printer",
        "view": "grid",
        "title": "Compact printer card",
        "text": "In grid view, each printer is shown as a compact card with status color, progress and completion percentage.",
        "more": "The same status colors are used across the interface: free, printing, paused and error each have their own shade. This makes the whole farm easier to read at a glance."
    },
    {
        "id": "printer-card-expanded",
        "group": "printers",
        "sel": "#tour-demo-printer",
        "view": "list",
        "expand": true,
        "marks": [
            {
                "m": "ctl-start",
                "n": 1,
                "pos": "tr"
            },
            {
                "m": "ctl-stop",
                "n": 2,
                "pos": "tr"
            },
            {
                "m": "ctl-pause",
                "n": 3,
                "pos": "tr"
            },
            {
                "m": "ctl-print",
                "n": 4,
                "pos": "tr"
            }
        ],
        "title": "Expanded printer card",
        "text": "In list view, the printer card becomes a control panel with start, stop, pause, print, upload, temperatures, preview, progress, camera and materials.",
        "more": "The numbered controls are: 1 Start or resume, 2 Stop with confirmation, 3 Pause, and 4 PRINT for the file selected in the Select file box. Upld uploads a file from your computer to the printer. During active printing, the lower control row stays inactive."
    },
    {
        "id": "printer-ams-print",
        "group": "printers",
        "sel": "#tour-demo-printer",
        "card": "below",
        "view": "list",
        "scene": "print",
        "expand": true,
        "title": "Print with AMS",
        "text": "Press Load, choose a print file in the built-in file manager and press Print. If the printer has AMS or a similar system, choose the filament slot before printing starts."
    },
    {
        "id": "projects-overview",
        "group": "projects",
        "sel": "#tour-demo-projexp",
        "expandProject": true,
        "card": "tl",
        "title": "Projects",
        "text": "Projects are the production board. A project groups the parts, files and progress of one order or production batch.",
        "more": "Use projects when you need to produce a set of parts and track completion, not just print one file. Project cards can be sorted by name or by the date they were added."
    },
    {
        "id": "projects-create",
        "group": "projects",
        "sel": "[data-tour=\"newproj\"]",
        "expandProject": true,
        "title": "Create project",
        "text": "New Project creates an empty project by name. After that, you can add parts and attach print files to them.",
        "more": "A project can also be started from files. In that case Farm Manager can create the project and add detected parts automatically."
    },
    {
        "id": "projects-import-files",
        "group": "projects",
        "sel": "[data-tour=\"newproj\"]",
        "expandProject": true,
        "card": "left",
        "title": "Import project from files",
        "text": "A project can be created from files. This reduces manual entry and helps the operator prepare production faster.",
        "more": "When importing g-code, 3MF, STL or STEP files, Farm Manager can create a dated project and prepare parts and printable plates from the selected files."
    },
    {
        "id": "projects-part-counters",
        "group": "projects",
        "sel": "#tour-demo-pvtbl",
        "expandProject": true,
        "card": "left",
        "title": "Counters in project",
        "text": "Each project part has counters: part name, On plate, Needed, Printed and Status.",
        "more": "Part name identifies the item. On plate is how many copies of this exact part are produced by one print file. Needed is the required quantity. Printed is the accepted finished quantity. Status shows whether the part is ready, in progress or needs rework."
    },
    {
        "id": "projects-label-objects",
        "group": "projects",
        "sel": "#tour-demo-pvtbl",
        "expandProject": true,
        "card": "left",
        "title": "Label Objects for counting",
        "text": "Automatic part counting is most reliable when the print file contains object labels from the slicer.",
        "more": "Enable Label Objects / gcode_label_objects before exporting g-code or 3MF. These labels help Farm Manager detect which parts are on the plate and how many copies of each part are present."
    },
    {
        "id": "projects-counting-fallback",
        "group": "projects",
        "sel": "#tour-demo-pvtbl",
        "expandProject": true,
        "card": "left",
        "title": "If counting is unavailable",
        "text": "If a file has no labels or the result is unclear, Farm Manager should not guess the quantity.",
        "more": "The operator can check the first print and manually correct the On plate value. This is safer than silently adding the wrong number of parts to the project."
    },
    {
        "id": "projects-card",
        "group": "projects",
        "sel": "#tour-demo-projcell",
        "card": "right",
        "title": "Project card",
        "text": "A project card shows the project name, overall progress, status color, deadline and rework warnings.",
        "more": "Open the card to work inside the project: switch between By parts and By files, edit names and files, send parts to compatible free printers and track finished quantities."
    },
    {
        "id": "projects-archive",
        "group": "projects",
        "sel": "#tour-demo-projcell",
        "card": "right",
        "title": "Archive and delete",
        "text": "Right-click a project card to open its menu: Archive tucks the project away without deleting (it can be restored later), Delete removes the project after a confirmation."
    },
    {
        "id": "quick-tasks-overview",
        "group": "quick_tasks",
        "sel": "[data-tour=\"qtsection\"]",
        "title": "Tasks",
        "text": "Tasks is for printing individual files without creating a project. It is useful for one-off prints, tests and urgent files."
    },
    {
        "id": "quick-tasks-drop",
        "group": "quick_tasks",
        "sel": "[data-tour=\"qtdrop\"]",
        "title": "Drop or select a file",
        "text": "Drop a file into this area or click to select one. Ready print files can be sent to a compatible free printer; model files must be sliced first."
    },
    {
        "id": "quick-tasks-load",
        "group": "quick_tasks",
        "sel": "[data-tour=\"qtsection\"]",
        "card": "tr",
        "view": "list",
        "scene": "load",
        "title": "Load into Tasks",
        "text": "Open launches the built-in file manager. Select a print file and press Load to tasks.",
        "more": "The same file manager opens when you click a file name in Tasks or in a project. It opens the folder and highlights the selected file, so the operator can quickly find it."
    },
    {
        "id": "quick-tasks-row",
        "group": "quick_tasks",
        "sel": "#tour-demo-staging",
        "view": "list",
        "title": "Task row",
        "text": "A Task row shows the file name, Needed, Printed and current status.",
        "more": "Expand the row to add a note, open a model in the slicer, print the file or open its folder. The counters follow the same idea as project parts."
    },
    {
        "id": "quick-tasks-find-printer",
        "group": "quick_tasks",
        "sel": "#tour-demo-status",
        "view": "list",
        "spot": true,
        "frameStatus": true,
        "noDim": true,
        "title": "Find the printer",
        "text": "When a file or part is printing, its status becomes clickable. Click it to highlight the printer or printers running that job."
    },
    {
        "id": "suggestions-alerts",
        "group": "alerts",
        "sel": "[data-tour=\"suggest\"]",
        "card": "above",
        "title": "Suggestions and alerts",
        "text": "This area shows what the program is doing with the printers right now: files being sent, printers queued to start, and jobs waiting for a suitable printer. Collapsed, it keeps a counter of active tasks.",
        "more": "Alerts can include a failed print, incompatible g-code, a paused printer or missing filament. The goal is to show problems immediately instead of hiding them in the workflow."
    },
    {
        "id": "finish",
        "group": "finish",
        "sel": "[data-tour=\"header\"]",
        "card": "below",
        "title": "You are all set",
        "text": "That is the main interface: printers, projects, Tasks, archive, settings and suggestions. You can replay this tour from Settings at any time.",
        "more": "The interface also works on a phone or tablet in the same local network, so you can monitor the farm and start files away from the main workstation."
    }
];

// Короткий тур для первого знакомства.
// Он не дублирует шаги: выбирает нужные id из полного сценария выше.
// Если id переименован или удалён, шаг просто не попадёт в короткий тур.
export const quickTourStepIds = [
    "welcome",
    "connection-sync",
    "settings-open",
    "printers-overview",
    "printers-add",
    "printer-card-expanded",
    "projects-overview",
    "projects-part-counters",
    "projects-label-objects",
    "quick-tasks-overview",
    "quick-tasks-load",
    "suggestions-alerts",
    "finish"
];

export const quickTourSteps = quickTourStepIds
    .map((id) => tourSteps.find((step) => step.id === id))
    .filter(Boolean);
