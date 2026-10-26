// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// ============================================================================
//  Реестр интерактивных подсказок (обучение при наведении курсора).
//
//  КАК ДОБАВИТЬ ПОДСКАЗКУ К ЛЮБОЙ КНОПКЕ ИЛИ ПОЛЮ — ВСЕГО 2 ШАГА:
//    1) В web/index.html на нужный элемент добавить атрибут:
//           data-help="мой_ключ"
//       (подходит любой элемент: <button>, <input>, <select>, <div>, <g> в SVG…)
//    2) Сюда, в HELP_HINTS, добавить запись с тем же ключом:
//           "мой_ключ": { title: "Заголовок", text: "Полное объяснение…" }
//
//  Всё остальное система делает сама:
//    • ждёт наведение и задержку 0.5 с;
//    • показывает красивую подсказку из этого реестра;
//    • ставит её рядом с элементом — НЕ перекрывая его;
//    • не даёт ей выйти за край экрана и не обрезает.
//  Больше ничего трогать не нужно.
//
//  ДВУЯЗЫЧНОСТЬ (необязательно). По умолчанию title/text — русские.
//  Чтобы задать английский вариант, добавьте блок en:
//    "ключ": { title:"Рус", text:"Рус…", en:{ title:"Eng", text:"Eng…" } }
//  Если en нет — в английском интерфейсе покажется русский текст.
//
//  ПРАВИЛО ТЕКСТА: коротко и по делу, 2–4 предложения. Это гарантирует, что
//  подсказка поместится на экране и никогда не обрежется.
// ============================================================================

export const HELP_HINTS = {
  "newproj": {
    title: "Новый проект",
    text: "Создаёт проект — папку деталей и файлов под одно изделие или заказ. Внутри ведётся учёт: сколько деталей нужно, сколько уже напечатано и что осталось.",
    en: { title: "New project", text: "Creates a project — a folder of parts and files for one product or order. Inside you track how many parts are needed, how many are printed and what's left." }
  },
  "settings": {
    title: "Настройки",
    text: "Открывает панель настроек: тема и шрифт интерфейса, язык, слайсер, инструменты и хранение данных. Здесь же включается этот режим подсказок.",
    en: { title: "Settings", text: "Opens the settings panel: theme and font, language, slicer, tools and data storage. This is also where you turn these hints on." }
  },
  "lang": {
    title: "Язык интерфейса",
    text: "Переключает весь интерфейс между русским (RU) и английским (EN). Выбор сохраняется и применяется сразу.",
    en: { title: "Interface language", text: "Switches the whole interface between Russian (RU) and English (EN). Your choice is saved and applied instantly." }
  },
  "set-theme-toggle": {
    title: "Тема оформления",
    text: "Переключает светлую и тёмную тему. Тёмная удобнее в цеху при слабом свете, светлая — при ярком. Выбор сохраняется.",
    en: { title: "Appearance theme", text: "Switches between light and dark themes. Dark suits a dim workshop, light suits bright rooms. Your choice is saved." }
  },
  "set-suggestions-toggle": {
    title: "Рекомендации в карточках",
    text: "Включает умные подсказки прямо в карточках — например, какой принтер свободен под деталь. Это не то же самое, что подсказки при наведении.",
    en: { title: "Card suggestions", text: "Turns on smart hints inside cards — for example, which printer is free for a part. This is not the same as hover hints." }
  },
  "help-hints-toggle": {
    title: "Подсказки при наведении",
    text: "Это режим подсказок: когда он включён, наведите курсор на любую кнопку или поле и задержитесь на 0.5 с — появится объяснение, что это и как работает. Выключается здесь же.",
    en: { title: "Hover hints", text: "This is the hints mode: when on, hover any button or field and pause for 0.5s to see what it is and how it works. Turn it off here too." }
  },
  "set-update-check": {
    title: "Проверять обновления",
    text: "Когда включено, программа раз в 6 часов спрашивает сайт 3diwell.com, вышла ли новая версия, и показывает в «Подсказках» кнопку загрузки. Выключите, если ферма должна работать без обращений в интернет. Настройка общая для всех компьютеров фермы.",
    en: { title: "Check for updates", text: "When on, every 6 hours the program asks 3diwell.com whether a new version is out and shows a download button in Hints. Turn it off if the farm must not reach the internet. The setting is shared by all computers of the farm." }
  },

  // ---- Принтеры (левая колонка) ----
  "broker": {
    title: "Связь и синхронизация",
    text: "Точка показывает связь интерфейса с сервером: зелёная — связь есть, красная — потеряна. Значок синхронизации рядом загорается в момент сохранения; всё сохраняется автоматически.",
    en: { title: "Connection and sync", text: "The dot shows the link to the server: green means connected, red means lost. The sync icon beside it lights up while changes are being saved — everything saves automatically." }
  },
  "psort": {
    title: "Принтеры · сортировка",
    text: "Это колонка ваших принтеров. Нажмите на заголовок, чтобы переключить сортировку карточек: по статусу (занятые и свободные группируются) или по имени.",
    en: { title: "Printers · sorting", text: "This is your printers column. Click the heading to switch how cards are sorted: by status (busy and free grouped) or by name." }
  },
  "pview": {
    title: "Список или сетка",
    text: "Переключает принтеры между подробным списком (полное управление каждым) и компактной сеткой (много принтеров сразу на экране).",
    en: { title: "List or grid", text: "Switches the printers between a detailed list (full controls each) and a compact grid (many printers on screen at once)." }
  },
  "add-printer": {
    title: "Добавить принтер",
    text: "Открывает каталог поддерживаемых моделей. Выберите свою, укажите адрес и параметры — и принтер встаёт в строй, готовый к работе.",
    en: { title: "Add a printer", text: "Opens a catalog of supported models. Pick yours, enter its address and details, and the printer joins the fleet ready to work." }
  },
  "pcard": {
    title: "Карточка принтера",
    text: "Карточка принтера. Показывает статус (цветом ячейки), прогресс печати, время и процент готовности. В компактной сетке — кратко; в режиме списка карточка раскрывается в полный пульт: температуры, превью, кнопки управления и слоты AMS.",
    en: { title: "Printer card", text: "A printer card. Shows status (by the cell color), print progress, elapsed time and completion percentage. Compact in the grid view; in the list view it expands into a full control panel \u2014 temperatures, preview, control buttons and AMS slots." }
  },
  "pexp": {
    title: "Раскрытая карточка",
    text: "Полный пульт принтера: кнопки Старт/Стоп/Пауза/Печать, выбор файла, живые температуры, превью детали, прогресс и кнопка камеры. Во время печати нижний ряд кнопок неактивен.",
    en: { title: "Expanded card", text: "The printer's full control panel: Start/Stop/Pause/Print, a file picker, live temperatures, a part preview, progress and a camera button. During a print the bottom button row is inactive." }
  },

  // ---- Проекты, Задачи, Подсказки (правая колонка) ----
  "projects-head": {
    title: "Проекты · сортировка",
    text: "Это область проектов — ваша производственная доска. Каждый проект объединяет детали и файлы одного заказа. Нажмите на заголовок, чтобы сортировать карточки по имени или по дате добавления.",
    en: { title: "Projects · sorting", text: "This is the projects area — your production board. Each project groups the parts and files of one order. Click the heading to sort cards by name or by date added." }
  },
  "quick": {
    title: "Задачи",
    text: "Печать отдельных файлов без проекта — удобно для разовых и пробных деталей. Готовый G-код печатается сразу; модель (STL/STEP) сначала нужно нарезать в слайсере.",
    en: { title: "Tasks", text: "Printing single files without a project — handy for one-offs and test pieces. A ready g-code prints right away; a model (STL/STEP) must be sliced first." }
  },
  "qtdrop": {
    title: "Зона перетаскивания",
    text: "Перетащите сюда файл или нажмите, чтобы выбрать — он добавится в Задачи и будет ждать отправки на любой совместимый свободный принтер.",
    en: { title: "Drop zone", text: "Drop a file here or click to pick one — it goes into Tasks and waits to be sent to any compatible free printer." }
  },
  "suggest-fold": {
    title: "Свернуть подсказки",
    text: "Клик по строке сворачивает панель в один заголовок и разворачивает обратно. Выбор запоминается до следующего запуска. Чтобы убрать панель совсем, есть отдельная галка в настройках.",
    en: { title: "Collapse suggestions", text: "Clicking the row folds the panel into a single header line and unfolds it back. The header keeps the count of active sends and queue entries. The choice is remembered for next time. To hide the panel entirely there is a separate checkbox in Settings." }
  },
  "pc-diag": {
    title: "Диагностика принтера",
    text: "Открывает окно, где Farm Manager безопасно читает поддерживаемые команды и макросы принтера и складывает их в отчёт. Команды движения, калибровки и печати не отправляются. Значок есть только у принтеров на Klipper.",
    en: { title: "Printer diagnostics", text: "Opens a window where Farm Manager safely reads the printer supported commands and macros into a report. No movement, calibration or printing commands are sent. The icon is shown for Klipper printers only." }
  },
  "kl-report": {
    title: "Диагностический отчёт",
    text: "Отчёт нужен разработчику, чтобы починить работу с этой маркой принтера. Соберите его, сохраните файл и передайте разработчику. Читаются только настройки, ничего не запускается.",
    en: { title: "Diagnostic report", text: "The report helps the developer support this printer brand. Collect it, save the file and send it to the developer. Only settings are read; nothing is executed." }
  },
  "suggest": {
    title: "Подсказки: отправки и очереди",
    text: "Здесь видно всё, что программа делает с принтерами прямо сейчас: какие файлы отправляются и на каком они шаге, кто стоит в очереди на запуск, и что ждёт в очереди ожидания подходящего принтера. Отправку можно закрыть, когда она завершилась; очередь — снять или запустить. В свёрнутом виде заголовок показывает число активных дел и мигает, пока они идут.",
    en: { title: "Suggestions: sends and queues", text: "Everything the program is doing with the printers right now: which files are being sent and at what step, who is queued to start, and what waits in the queue for a suitable printer. A finished send can be dismissed; a queue entry can be removed or started. When collapsed, the header shows the number of active tasks and pulses while they run." }
  },
  "suggest-count": {
    title: "Активные дела",
    text: "Сколько дел идёт прямо сейчас: отправки на принтеры, принтеры в очереди на запуск и файлы в очереди ожидания. Точка рядом мигает, пока хоть одно дело не закончено. Разверните панель, чтобы увидеть подробности.",
    en: { title: "Active tasks", text: "How many tasks are running right now: sends to printers, printers queued to start and files in the waiting queue. The dot beside it pulses while anything is still in progress. Expand the panel to see details." }
  },
  "suggest-sends": {
    title: "Отправки на принтеры",
    text: "Каждая строка — файл, который программа отправляет на принтер, и шаг, на котором он сейчас: ожидание, подготовка принтера, загрузка, подтверждение запуска. Завершённую или неудачную отправку можно закрыть крестиком; текст ошибки остаётся в строке.",
    en: { title: "Sends to printers", text: "Each row is a file being sent to a printer and its current step: waiting, preparing the printer, uploading, confirming the start. A finished or failed send can be dismissed with the cross; the error text stays in the row." }
  },
  "suggest-queue": {
    title: "Очередь на запуск",
    text: "Принтеры, на которые запуск уже назначен: программа запускает их по очереди, с паузой между запусками. Отметьте галочками и нажмите «Отменить», чтобы снять запуск, который ещё не начался.",
    en: { title: "Launch queue", text: "Printers with a launch already assigned: the program starts them one by one with a pause in between. Tick rows and press Cancel to withdraw a launch that has not started yet." }
  },
  "suggest-wait": {
    title: "Очередь ожидания",
    text: "Файлы, для которых принтер подбирает сама программа: свободный, с нужным материалом и с вашим разрешением запускать из очереди. Когда принтер найден — появляется кнопка «Запустить»; печать начнётся только по вашему нажатию.",
    en: { title: "Waiting queue", text: "Files for which the program picks a printer itself: free, with the right material and allowed by you to start from the queue. Once a printer is found, a Start button appears; printing begins only when you press it." }
  },
  "import-plan": {
    title: "Импорт плана/архива",
    text: "Загружает план производства (подготовленный в CAD) или архив файлов — чтобы быстро наполнить проекты и задачи, не добавляя всё вручную.",
    en: { title: "Import plan/archive", text: "Loads a production plan (prepared in your CAD) or a file archive — to quickly fill projects and tasks without adding everything by hand." }
  },
  "proj-edit": {
    title: "Редактировать проект",
    text: "Включает режим правки проекта: переименовать, добавить или убрать детали и файлы, задать нужное и напечатанное количество, сменить статус. Выход — кнопкой «Готово».",
    en: { title: "Edit project", text: "Turns on the project edit mode: rename it, add or remove parts and files, set needed and printed counts, change statuses. Leave it with the Done button." }
  },

  // ---- Внутри проекта (раскрытая деталь) ----
  "part-row": {
    title: "Строка детали",
    text: "Нажмите на деталь, чтобы развернуть управление: задать нужное и напечатанное количество, привязать файл, отправить на печать на свободный принтер. Когда деталь печатается, её статус кликабелен — покажет, на каких принтерах идёт печать.",
    en: { title: "Part row", text: "Click a part to expand its controls: set needed and printed counts, attach a file, send it to a free printer. While a part is printing its status is clickable — it shows which printers are running it." }
  },

  // ---- Настройки ----
  "set-edition": {
    title: "Режим интерфейса",
    text: "Меняет только набор видимых разделов. Все функции программы бесплатны; платными бывают только отдельные модули.",
    en: { title: "Interface mode", text: "Only changes which sections are visible. All program features are free; only some separate modules are paid." }
  },
  "set-font": {
    title: "Шрифт интерфейса",
    text: "Меняет начертание текста во всей программе. По умолчанию стоит «3DIWELL Wide J» (из свободного шрифта Jura); «3DIWELL Wide P» (из Play) — чуть мельче; остальные — шрифты Windows. Выбор сохраняется на этом компьютере.",
    en: { title: "Interface font", text: "Changes the typeface used across the whole program. The default is 3DIWELL Wide J (from the free Jura font); 3DIWELL Wide P (from Play) is slightly smaller; the others are Windows fonts. Your choice is saved on this computer." }
  },
  "set-text-size": {
    title: "Размер текста",
    text: "Делает все надписи программы крупнее или мельче — от 90 до 130 %. Окна, кнопки и отступы остаются прежними, поэтому при крупном тексте длинные подписи сокращаются многоточием. Выбор сохраняется на этом компьютере.",
    en: { title: "Text size", text: "Makes all program text larger or smaller — from 90 to 130%. Windows, buttons and spacing keep their size, so long labels are shortened with an ellipsis at larger sizes. Your choice is saved on this computer." }
  },
  "set-dates": {
    title: "Сроки",
    text: "Включите даты создания и сроки проектов. Задайте, за сколько дней до срока проект начинает предупреждать жёлтым, чтобы не пропустить дедлайн.",
    en: { title: "Dates", text: "Turn on creation dates and project deadlines. Set how many days before a deadline a project starts warning in yellow, so you never miss it." }
  },
  "set-slicer": {
    title: "Слайсер",
    text: "Выберите, в каком слайсере открываются модели — автоопределение или конкретная программа. Используется при отправке модели на нарезку.",
    en: { title: "Slicer", text: "Choose which slicer opens your models — auto-detect or a specific program. Used when you send a model to slice." }
  },
  "set-tools": {
    title: "Инструменты",
    text: "Служебные инструменты, в том числе Диагностика — журнал сервера в реальном времени, помогающий найти причину сбоя.",
    en: { title: "Tools", text: "Service tools, including Diagnostics — a live server log that helps you find the cause of a failure." }
  },
  "set-data": {
    title: "Хранение данных",
    text: "Папка, где хранятся базы, модули, лицензии и файлы программы. Выбирайте пустую папку: туда, где уже есть базы Farm Manager, данные не переносятся. Смена применяется после перезапуска: программа копирует данные, сверяет каждую копию с оригиналом и только потом удаляет оригинал. Если что-то не удалось, ничего не удаляется: программа остаётся на прежней папке и пишет причину здесь же. Для переноса нужно свободное место не меньше объёма папки данных, даже на том же диске; большая папка переносится несколько минут — не закрывайте программу. Настройки запуска и кэш превью остаются на прежнем месте.",
    en: { title: "Data storage", text: "The folder that holds the app's databases, modules, licenses and files. Choose an empty folder: data is not moved into a folder that already holds Farm Manager databases. A change applies after a restart: the app copies the data, checks every copy against the original and only then deletes the original. If anything fails, nothing is deleted: the app stays on the previous folder and shows the reason right here. The move needs free space at least the size of the data folder, even on the same drive; a large folder takes several minutes — do not close the app. Startup settings and the preview cache stay where they are." }
  },
  "set-security": {
    title: "Доступ и аудит",
    text: "Защита фермы входом по логину. Каждый входит под своим именем и паролем со своей ролью; важные действия пишутся в журнал аудита. Здесь же управление пользователями.",
    en: { title: "Access & audit", text: "Protect the farm with sign-in. Everyone logs in with their own name, password and role; important actions are written to an audit log. User management lives here too." }
  },
  "set-tab-modules": {
    ru: { title: "Модули", text: "Отдельная вкладка для расширений программы: что установлено, что включено, и установка нового файлом .zip. Настройки самого модуля живут в его окне — откройте модуль строкой списка." },
    en: { title: "Modules", text: "A separate tab for program extensions: what is installed, what is enabled, and installing a new one from a .zip. A module's own settings live inside it — open it from the list." },
  },
  "set-mod-install": {
    ru: { title: "Установка и обновление", text: "Модуль ставится одним файлом .zip любой версии — новее или старее установленной: файл заменяет прежнюю версию, данные модуля остаются. Подписанный пакет сначала проверяется: повреждённый или изменённый не ставится, а новая версия платного модуля, вышедшая после оплаченных обновлений, не заменит рабочую. Если программа знает версию новее, она предупредит. После установки программу нужно перезапустить." },
    en: { title: "Install and update", text: "A module is installed from a single .zip of any version, newer or older than the installed one: it replaces the previous version and keeps the module data. A signed package is checked first: a damaged or modified one is not installed, and a new paid module version released after your paid updates does not replace the working one. If the app knows a newer version, it warns you. A restart is required afterwards." },
  },
  "set-licenses": {
    ru: { title: "Лицензии модулей", text: "Лицензии платных модулей: ключ из письма или файл .fmlic. Программа проверяет подпись поставщика — модуль работает сразу и без интернета. Когда у компьютера есть интернет, программа сообщает службе лицензий 3DiWell номер лицензии и номер этого компьютера: так один ключ не работает на чужих компьютерах. Купленная версия модуля работает бессрочно, новые версии — пока идёт оплаченный период обновлений." },
    en: { title: "Module licenses", text: "Paid module licenses: a key from the email or a .fmlic file. The app checks the vendor signature, so the module works right away and without internet. When the computer is online, the app reports the license number and this computer's number to the 3DiWell license service, so one key does not work on other people's computers. A purchased module version works forever, and new versions come while the paid update period lasts." },
  },
  "set-license-key": {
    ru: { title: "Ключ лицензии", text: "Ключ приходит в письме после покупки и есть в личном кабинете на сайте. Скопируйте его целиком, вставьте сюда и нажмите «Добавить ключ». Поддельный или повреждённый ключ не принимается." },
    en: { title: "License key", text: "The key comes in the email after the purchase and is shown in your account on the website. Copy it whole, paste it here and press “Add the key”. A forged or damaged key is not accepted." },
  },
  "set-license-sent": {
    ru: { title: "Что передаётся", text: "Ровно то, что программа отправляет службе лицензий: номер лицензии, проверочная сумма лицензии, номер этого компьютера (необратимая свёртка), названия и версии модуля и программы. Ни имён, ни адресов, ни принтеров, ни заказов, ни файлов." },
    en: { title: "What is sent", text: "Exactly what the app sends to the license service: the license number, a license checksum, this computer's number (an irreversible hash), and the module and app names and versions. No names, addresses, printers, orders or files." },
  },
  "set-license-add": {
    ru: { title: "Добавить лицензию", text: "Выберите файл .fmlic, полученный от поставщика. Подделанный или повреждённый файл не принимается и не сохраняется. Продление — это новый файл: добавьте его так же." },
    en: { title: "Add a license", text: "Pick the .fmlic file you got from the vendor. A forged or damaged file is not accepted and not saved. A renewal is a new file: add it the same way." },
  },
  "set-license-request": {
    ru: { title: "Запрос активации", text: "Сохраняет небольшой файл с номером этой установки, версией программы и списком модулей — без имён, адресов и данных фермы. Отправьте его поставщику, если лицензия должна быть привязана к этому компьютеру." },
    en: { title: "Activation request", text: "Saves a small file with this installation's ID, the app version and the module list — no names, addresses or farm data. Send it to the vendor if the license must be bound to this computer." },
  },
  "set-license-remove": {
    ru: { title: "Удалить лицензию", text: "Убирает файл лицензии: платные функции по ней закрываются сразу. Данные модулей и программы остаются. Вернуть можно тем же файлом." },
    en: { title: "Remove the license", text: "Removes the license file: paid features covered by it close right away. Module and program data stay. You can bring it back with the same file." },
  },
  "set-browser-settings": {
    ru: { title: "Настройки этого окна", text: "Камеры видеостены, темы оформления и профили этикеток хранятся только в этом окне браузера и пропадают при смене порта или компьютера. Сохраните их в файл и загрузите на новом месте." },
    en: { title: "This window settings", text: "Video wall cameras, themes and label profiles live only in this browser window and are lost when the port or the computer changes. Save them to a file and load it in the new place." },
  },
  "set-mod-pick": {
    ru: { title: "Установить модуль", text: "Откроется встроенный Проводник программы. Выберите файл модуля .zip: он лежит в папке выпуска рядом с установщиком или там, куда вы его скачали." },
    en: { title: "Install a module", text: "The built-in Explorer opens. Pick the module .zip: it is in the release folder next to the installer, or wherever you downloaded it." },
  },
  "set-modules": {
    title: "Модули",
    text: "Дополнительные модули программы. Активные запускаются прямо из этого меню; остальные помечены как «скоро».",
    en: { title: "Modules", text: "Optional add-on modules. Active ones launch straight from this menu; the rest are marked as coming soon." }
  },
  "set-about": {
    title: "О программе",
    text: "Открывает карточку с названием, точной версией сборки, режимом интерфейса, сайтом и поддержкой — удобно при обращении в поддержку или проверке версии.",
    en: { title: "About", text: "Opens a card with the name, exact build version, interface mode, website and support — handy when contacting support or checking your version." }
  },

  // ---- Диагностика ----
  "diag-filter": {
    title: "Журнал · фильтр",
    text: "Журнал сервера в реальном времени. Кнопки фильтруют записи по уровню: Все / Важное / Предупреждения / Ошибки. Журнал только показывает события и на принтеры не влияет.",
    en: { title: "Log · filter", text: "A live server log. The buttons filter records by level: All / Info+ / Warnings / Errors. The log only shows events and never affects the printers." }
  },
  "diag-verbose": {
    title: "Подробная консоль",
    text: "Выводит подробную debug-телеметрию в окно CMD. На эту панель не влияет — нужна для глубокой диагностики.",
    en: { title: "Verbose console", text: "Streams detailed debug telemetry to the CMD window. It doesn't affect this panel — for deep diagnostics." }
  },
  "diag-autoscroll": {
    title: "Автопрокрутка",
    text: "Когда включена, журнал сам прокручивается к свежим записям. Выключите, чтобы спокойно читать старые.",
    en: { title: "Auto-scroll", text: "When on, the log scrolls itself to the newest records. Turn it off to read older ones calmly." }
  },
  "diag-clear": {
    title: "Очистить",
    text: "Очищает список записей на экране. Сам журнал на сервере при этом не удаляется.",
    en: { title: "Clear", text: "Clears the list of records on screen. The server's own log is not deleted." }
  },
  "diag-download": {
    title: "Скачать логи",
    text: "Сохраняет журнал в файл — удобно отправить в техподдержку при разборе проблемы.",
    en: { title: "Download logs", text: "Saves the log to a file — handy to send to support when troubleshooting." }
  },
  "diag-conn": {
    title: "Вкладка «Связь»",
    text: "Переключает на диагностику сети: проверка связи с принтерами, задержки и фоновый мониторинг.",
    en: { title: "Connection tab", text: "Switches to network diagnostics: connectivity checks to printers, latency and background monitoring." }
  },

  // ---- Файловый менеджер (проводник) ----
  "fm-up": {
    title: "На уровень вверх",
    text: "Переход в родительскую папку. Рядом — кнопка обновления и адресная строка с цепочкой папок.",
    en: { title: "Up one level", text: "Goes to the parent folder. Beside it are a refresh button and an address bar with the folder breadcrumb." }
  },
  "fm-side": {
    title: "Быстрый доступ",
    text: "Боковая панель с ярлыками: Рабочий стол, Загрузки, Документы и диски компьютера — быстрый переход к нужной папке.",
    en: { title: "Quick access", text: "A side panel of shortcuts: Desktop, Downloads, Documents and your computer's drives — jump to a folder fast." }
  },
  "fm-prev": {
    title: "Превью файла",
    text: "Показывает изображение или иконку выбранного файла, его имя, тип и размер — чтобы убедиться, что выбран нужный файл.",
    en: { title: "File preview", text: "Shows the selected file's image or icon, name, type and size — to make sure it's the file you want." }
  },
  "fm-load": {
    title: "Загрузить в задачи",
    text: "Отправляет выбранные печатаемые файлы в Задачи, готовые к печати. В других режимах кнопка меняется на «Привязать», «Добавить» или «Импорт».",
    en: { title: "Load to tasks", text: "Sends the selected printable files to Tasks, ready to print. In other modes this button becomes Attach, Add or Import." }
  },
  "fm-sort": {
    title: "Сортировка файлов",
    text: "Заголовки столбцов кликабельны — сортируйте файлы по имени, дате, типу или размеру.",
    en: { title: "Sort files", text: "The column headers are clickable — sort files by name, date, type or size." }
  },

  // ---- Форма принтера (добавить/изменить) ----
  "pf-model": {
    title: "Модель принтера",
    text: "Выберите модель из каталога — это позволяет программе сопоставлять принтер с подходящим g-code и не предлагать несовместимые файлы.",
    en: { title: "Printer model", text: "Pick the model from the catalog — it lets the app match this printer to compatible g-code and avoid incompatible files." }
  },
  "pf-ip": {
    title: "Сетевой адрес",
    text: "IP-адрес принтера в вашей сети; порт указывается в поле рядом. По этому адресу программа связывается с принтером.",
    en: { title: "Network address", text: "The printer's IP address on your network; the port is in the field beside it. The app reaches the printer at this address." }
  },
  "pf-token": {
    title: "Токен доступа",
    text: "Ключ доступа к принтеру (для FlashForge — Serial:CheckCode). Берётся в сетевых настройках самого принтера.",
    en: { title: "Access token", text: "The printer's access key (for FlashForge it's Serial:CheckCode). Found in the printer's own network settings." }
  },
  "pf-creality-link": {
    title: "Как подключён принтер Creality",
    text: "«Заводская прошивка» — программа подключается к родной службе Creality (порт 9999), как Creality Print: root и Moonraker не нужны. «Moonraker» — если на принтере включён root и поставлен Moonraker (Fluidd или Mainsail).",
    en: { title: "How the Creality printer is connected", text: "\"Stock firmware\" — the app connects to the native Creality service (port 9999), like Creality Print: no root or Moonraker needed. \"Moonraker\" — if root is enabled on the printer and Moonraker is installed (Fluidd or Mainsail)." }
  },
  "pf-gen": {
    title: "Поколение (формат печати)",
    text: "Формат пути для отправки печати. Оставьте «Автоопределение» — меняйте вручную, только если печать не запускается (ошибка 0500-4002).",
    en: { title: "Generation (print format)", text: "The print path format. Leave Auto-detect — only change it manually if a print won't start (error 0500-4002)." }
  },
  "pf-save": {
    title: "Сохранить принтер",
    text: "Добавляет принтер в ферму (или сохраняет изменения). Нужны имя, адрес и выбранная модель.",
    en: { title: "Save printer", text: "Adds the printer to the fleet (or saves changes). Needs a name, address and a selected model." }
  },
  "pf-delete": {
    title: "Удалить принтер",
    text: "Удаляет этот принтер из фермы. Доступно только при редактировании существующего принтера.",
    en: { title: "Delete printer", text: "Removes this printer from the fleet. Available only when editing an existing printer." }
  },

  // ---- Выбор слота AMS ----
  "ams-pick": {
    title: "Выбор слота AMS",
    text: "Появляется при запуске печати на принтере с AMS. Выберите слот с нужным пластиком — печать начнётся. «Внешняя катушка» — печать с катушки снаружи AMS.",
    en: { title: "AMS slot picker", text: "Appears when starting a print on a printer with AMS. Pick the slot with the filament you need and printing starts. 'Ext. spool' prints from a spool outside the AMS." }
  },

  // ---- Доступ: вход, пользователи, аудит ----
  "login": {
    title: "Вход в систему",
    text: "Когда включена защита доступа, вход выполняется по логину и паролю. У каждого пользователя своя роль с разными правами.",
    en: { title: "Sign in", text: "When access control is on, you sign in with a username and password. Each user has a role with different permissions." }
  },
  "user-add": {
    title: "Добавить пользователя",
    text: "Создаёт нового пользователя: логин, пароль (не короче 6 символов) и роль. Доступно администратору.",
    en: { title: "Add user", text: "Creates a new user: a username, a password (at least 6 characters) and a role. Available to an administrator." }
  },
  "user-role": {
    title: "Роль пользователя",
    text: "Меняет права: Администратор — полный контроль, Оператор — печать и проекты, Сборщик — отметка готовых деталей, Наблюдатель — только просмотр.",
    en: { title: "User role", text: "Changes permissions: Administrator — full control, Operator — printing and projects, Assembler — marking parts done, Observer — view only." }
  },
  "user-devices": {
    title: "Запомненные устройства",
    text: "Телефоны, где при входе включено «Запомнить это устройство»: они входят сами, без пароля. «Отозвать» сразу закрывает доступ — на телефоне понадобится снова ввести логин и пароль.",
    en: { title: "Remembered devices", text: "Phones that signed in with “Remember this device”: they sign in on their own, without a password. “Revoke” closes access at once — the phone will need the username and password again." }
  },
  "about-license": {
    title: "Лицензия",
    text: "Ядро программы — открытое, по лицензии Mozilla Public License 2.0: его можно бесплатно использовать, изучать, изменять и распространять на её условиях. Платные модули, если они появятся, идут по своим условиям. Полный текст — файл LICENSE.txt в папке программы.",
    en: { title: "License", text: "The program core is open source under the Mozilla Public License 2.0: you may use, study, change and distribute it free of charge under its terms. Paid modules, if any, come with their own terms. The full text is LICENSE.txt in the program folder." }
  },
  "about-source": {
    title: "Исходный код",
    text: "Исходный код ядра этой версии можно получить, написав в техподдержку. Когда откроется публичный репозиторий, здесь появится ссылка на него.",
    en: { title: "Source code", text: "You can get the core source code of this version by writing to support. Once the public repository opens, a link to it will appear here." }
  },
  "audit": {
    title: "Журнал аудита",
    text: "Запись важных действий: входы, изменения проектов и деталей, архивирование, импорт — видно, кто, что и когда сделал.",
    en: { title: "Audit log", text: "A record of important actions: sign-ins, project and part changes, archiving and imports — see who did what and when." }
  },

  // ---- Карточка проекта, столбцы таблицы деталей, доп. поля принтера ----
  "project-card": {
    title: "Карточка проекта",
    text: "Каждый проект — карточка с именем и числом готовых деталей из общего. Цвет и заполнение показывают статус; значок перепечатки — что деталь нужно напечатать заново; чип срока желтеет к дедлайну. Клик открывает проект; правый клик — меню действий: «Архив» и «Удалить».",
    en: { title: "Project card", text: "Each project is a card with its name and how many parts are done out of the total. Color and fill show status; a rework badge means a part must be reprinted; a due chip turns yellow near the deadline. Click to open the project; right-click for the actions menu: Archive and Delete." }
  },
  "col-name": {
    title: "Столбец «Деталь»",
    text: "Название детали в проекте. Клик по заголовку сортирует таблицу по этому столбцу.",
    en: { title: "Column · Part", text: "The part's name in the project. Click the heading to sort the table by this column." }
  },
  "col-req": {
    title: "Столбец «Требуется»",
    text: "Сколько штук этой детали нужно по проекту. Например, в сборку идёт 4 кронштейна — значит здесь стоит 4.",
    en: { title: "Column · Required", text: "How many of this part the project needs. For example, an assembly uses 4 brackets — so this shows 4." }
  },
  "col-prnt": {
    title: "Столбец «Напечатано»",
    text: "Сколько штук уже напечатано и принято. Когда «напечатано» догоняет «требуется», деталь считается готовой.",
    en: { title: "Column · Printed", text: "How many have been printed and accepted. When 'printed' reaches 'required', the part counts as done." }
  },
  "col-defect": {
    title: "Столбец «Брак»",
    text: "Сколько штук ушло в брак и требует перепечатки. Неудачная печать или забракованная деталь увеличивает счётчик — эти штуки нужно напечатать заново.",
    en: { title: "Column · Defect", text: "How many went to scrap and need reprinting. A failed print or a rejected piece bumps this counter — those need printing again." }
  },
  "col-status": {
    title: "Столбец «Статус»",
    text: "Состояние детали: ожидание, в процессе или готово. Определяется напечатанным количеством и активной печатью.",
    en: { title: "Column · Status", text: "The part's state: pending, in process or done. It follows the printed count and any active print." }
  },
  "col-printing": {
    title: "Столбец «Печатается»",
    text: "Идёт ли сейчас печать этой детали. Если да — статус становится кликабельным и подсвечивает принтеры, на которых она печатается.",
    en: { title: "Column · Printing", text: "Whether this part is printing right now. If it is, the status becomes clickable and highlights the printers running it." }
  },
  "pf-name": {
    title: "Имя принтера",
    text: "Понятное имя принтера для отображения в ферме (например, «Bambu цех-1»). Обязательное поле.",
    en: { title: "Printer name", text: "A friendly name for the printer shown in the fleet (e.g. 'Bambu shop-1'). Required." }
  },
  "pf-port": {
    title: "Порт",
    text: "Сетевой порт принтера. Обычно подставляется автоматически под модель; меняйте, только если порт нестандартный (у FlashForge — 8898).",
    en: { title: "Port", text: "The printer's network port. Usually filled automatically for the model; change it only for a non-standard port (FlashForge uses 8898)." }
  },
  "pf-serial": {
    title: "Серийный номер",
    text: "Необязательное поле. Заполняется только для Bambu P1P/P1S/P1C — серийник нужен, чтобы запрашивать у них статус. Для X1/H2D и остальных оставьте пустым.",
    en: { title: "Serial number", text: "Optional. Fill it only for Bambu P1P/P1S/P1C — the serial lets the app request their status. Leave empty for X1/H2D and others." }
  },

  // ---- Строка детали, раскрытая деталь ----
  "pr-prev": {
    title: "Эскиз детали",
    text: "Эскиз детали из привязанного файла \u2014 быстрый визуальный ориентир, что это за деталь.",
    en: { title: "Part thumbnail", text: "A thumbnail of the part from its attached file \u2014 a quick visual cue of what the part is." }
  },
  "pr-chip": {
    title: "В скольких файлах деталь",
    text: "Сколько разных печатных файлов содержат эту деталь. «1» \u2014 деталь в одном файле; «\u25a3 N» \u2014 встречается в N файлах. Разверните строку, чтобы увидеть все варианты и их платы.",
    en: { title: "How many files contain the part", text: "How many different printable files contain this part. '1' means one file; '\u25a3 N' means it appears in N files. Expand the row to see all variants and their plates." }
  },
  "pr-notes": {
    title: "Заметка к детали",
    text: "Свободная заметка к детали \u2014 например, материал, цвет или особенности печати. Сохраняется автоматически.",
    en: { title: "Part note", text: "A free-form note for the part \u2014 e.g. material, color or print specifics. Saved automatically." }
  },
  "pr-openloc": {
    title: "Открыть расположение файла",
    text: "Открывает встроенный файловый менеджер на папке этого файла, с подсветкой самого файла \u2014 чтобы быстро найти его на диске.",
    en: { title: "Open file location", text: "Opens the built-in file manager at this file's folder with the file highlighted \u2014 to quickly find it on disk." }
  },
  "pr-onplate": {
    title: "Количество на плате",
    text: "Сколько копий этой детали на одной плате данного файла. Например, \u00d74 \u2014 за одну печать выходит 4 штуки.",
    en: { title: "On-plate count", text: "How many copies of this part are on one plate of this file. For example, \u00d74 \u2014 a single print yields 4 pieces." }
  },
  "pr-print": {
    title: "Печать детали",
    text: "Запускает печать этого файла: открывается выбор свободного совместимого принтера, затем (если есть AMS) выбор слота. Появляется только для готовых к печати файлов.",
    en: { title: "Print part", text: "Starts printing this file: a picker of free compatible printers opens, then (if there's an AMS) a slot picker. Appears only for ready-to-print files." }
  },
  "pr-slice": {
    title: "Нарезать модель",
    text: "Открывает модель (STL/STEP/3MF) в выбранном слайсере и добавляет её на плиту. Появляется для моделей, которые ещё не нарезаны в g-code.",
    en: { title: "Slice model", text: "Opens the model (STL/STEP/3MF) in your chosen slicer and adds it to the plate. Appears for models not yet sliced into g-code." }
  },

  // ---- Режим редактирования проекта ----
  "edit-simple": {
    title: "Обычный режим правки",
    text: "Обычный режим: для каждой детали задаются нужное и напечатанное количество, статус и заметка, деталь можно удалить. Имена и состав плат берутся из файлов и вручную не меняются.",
    en: { title: "Simple edit mode", text: "Simple mode: for each part you set the needed and printed counts, status and a note, and can delete a part. Part names and plate contents come from the files and are not edited by hand." }
  },
  "edit-advanced": {
    title: "Продвинутый режим правки",
    text: "Продвинутый режим: дополнительно открывает у каждого g-code редактор «Детали на плате» \u2014 там можно вручную переименовать детали, изменить их количество на плате и добавить недостающие. Нужен для старых g-code без меток, где программа не распознала состав сама.",
    en: { title: "Advanced edit mode", text: "Advanced mode: additionally opens a 'Parts on plate' editor for each g-code \u2014 there you can manually rename parts, change their on-plate counts and add missing ones. It's for older g-codes without labels, where the app could not detect the contents itself." }
  },
  "edit-part-name": {
    title: "Имя детали",
    text: "Имя детали, считанное из файла. В обычном режиме только для чтения; переименовать можно в продвинутом режиме в блоке «Детали на плате».",
    en: { title: "Part name", text: "The part name read from the file. Read-only in simple mode; rename it in advanced mode in the 'Parts on plate' block." }
  },
  "edit-del-part": {
    title: "Удалить деталь",
    text: "Удаляет деталь из проекта. Файл и его содержимое не затрагиваются \u2014 убирается только эта запись детали.",
    en: { title: "Delete part", text: "Removes the part from the project. The file and its contents are untouched \u2014 only this part entry is deleted." }
  },
  "edit-files": {
    title: "Файлы проекта",
    text: "Файлы проекта: модели (STL/3MF) сверху, g-code снизу. Когда добавляется g-code, программа читает его содержимое, разбивает на отдельные детали, считает количество каждой на плате и формирует общий список деталей. Поэтому список деталей образуется из файлов автоматически.",
    en: { title: "Project files", text: "The project's files: models (STL/3MF) on top, g-code below. When a g-code is added, the app reads its contents, splits it into individual parts, counts how many of each are on the plate, and builds the overall parts list. So the parts list is formed from the files automatically." }
  },
  "edit-del-file": {
    title: "Удалить файл",
    text: "Удаляет файл из проекта. Вместе с ним убираются все детали, взятые из этого файла \u2014 список деталей пересобирается по оставшимся файлам.",
    en: { title: "Delete file", text: "Removes the file from the project. All parts that came from this file are removed with it \u2014 the parts list is rebuilt from the remaining files." }
  },
  "edit-onplate": {
    title: "Детали на плате",
    text: "Состав платы этого g-code: какие детали на ней и по сколько штук. Обычно заполняется автоматически при добавлении файла; здесь, в продвинутом режиме, можно поправить вручную для старых файлов без меток \u2014 переименовать деталь, задать количество на плате (\u00d7N), добавить или убрать деталь.",
    en: { title: "Parts on plate", text: "This g-code's plate contents: which parts are on it and how many of each. Usually filled automatically when the file is added; here, in advanced mode, you can fix it by hand for old unlabeled files \u2014 rename a part, set its on-plate count (\u00d7N), add or remove a part." }
  },
  "edit-addpart": {
    title: "Добавить деталь на плату",
    text: "Добавляет новую деталь в состав платы этого файла \u2014 на случай, если программа не распознала её сама. Укажите имя и количество на плате.",
    en: { title: "Add part to plate", text: "Adds a new part to this file's plate contents \u2014 in case the app did not detect it. Give it a name and an on-plate count." }
  },

  // ---- Раздел «Задачи» (добавление файлов) ----
  "qt-open": {
    title: "Добавить файлы",
    text: "Открывает встроенный файловый менеджер, чтобы выбрать и добавить файлы в Задачи. Файлы также можно перетащить в зону слева.",
    en: { title: "Add files", text: "Opens the built-in file manager to pick and add files to Tasks. You can also drag files into the drop zone on the left." }
  },
  "qt-row": {
    title: "Строка задачи",
    text: "Строка задачи: файл, число нужных и напечатанных копий, статус. Нажмите, чтобы развернуть \u2014 заметка, печать, расположение файла и состав платы. Правый клик по имени файла \u2014 меню с пунктом «Удалить» (файл на диске не трогается).",
    en: { title: "Task row", text: "A task row: the file, its needed and printed copy counts, and status. Click to expand \u2014 note, print, file location and plate contents. Right-click the file name for a menu with Delete (the file on disk is untouched)." }
  },
  "qt-name": {
    title: "Имя файла",
    text: "Имя файла задачи. Клик по заголовку сортирует список по имени.",
    en: { title: "File name", text: "The task file's name. Click the heading to sort the list by name." }
  },
  "reports": {
    title: "Отчёты и статистика",
    text: "Экран считает по журналу печатей: сколько запусков было за 7, 30 или 90 дней, сколько завершилось, сколько сбоев, сколько отменено и по скольким исход не ясен. Есть разбивка по принтерам, по дням и список того, что печаталось чаще. Журнал ведёт модуль «Качество печати»: без него считать не из чего, и экран прямо об этом скажет. Как именно считается доля успеха — написано внизу экрана.",
    en: { title: "Reports and statistics", text: "This screen counts from the print log: how many runs happened over 7, 30 or 90 days, how many finished, failed, were cancelled, and how many ended with an unclear outcome. It breaks the numbers down by printer and by day and lists the most printed files. The log is kept by the Print quality module; without it there is nothing to count and the screen says so. The exact success-rate formula is printed at the bottom of the screen." }
  },
  "ui-switch": {
    title: "Версия интерфейса",
    text: "UI 2.0 — этот, рабочий интерфейс. UI 3.0 — новый, который делается сейчас: он живёт отдельной страницей со своими файлами, поэтому правки в нём не могут задеть рабочий. Выбор запоминается: после перезапуска программа откроет тот интерфейс, в котором вы были. Если новый интерфейс однажды не откроется — введите адрес /?ui=2, он вернёт рабочий и сотрёт выбор.",
    en: { title: "Interface version", text: "UI 2.0 is this working interface. UI 3.0 is the new one being built: it lives on its own page with its own files, so changes there cannot affect the working one. The choice is remembered, so a restart reopens the interface you were in. If the new interface ever fails to open, type the address /?ui=2 — it returns the working one and clears the choice." }
  },
  "qt-group": {
    title: "Группировка задач",
    text: "Задачи можно разложить по группам. «По проекту» — задача попадает в группу проекта, если файл с ТАКИМ ЖЕ именем числится за этим проектом; если такое имя есть сразу в двух проектах, программа не гадает и оставляет задачу во «Вне проектов». Совпадение имени — не доказательство: имена плит повторяются от заказа к заказу, поэтому группировка только показывает и ни на что в печати и учёте не влияет. Способ «по папке» появляется, только если у задач сохранён путь, откуда взят файл. Клик по заголовку группы сворачивает её.",
    en: { title: "Task grouping", text: "Tasks can be split into groups. «By project» puts a task into a project group when a file with the SAME name belongs to that project; if the same name exists in two projects the program does not guess and leaves the task in «Outside projects». A matching name is not proof — plate names repeat from order to order — so grouping only changes the view and affects neither printing nor stock accounting. The «By folder» mode appears only when tasks carry the path the file came from. Click a group heading to collapse it." }
  },
  "qt-problem": {
    title: "Проблемы задачи",
    text: "Красная метка «файла нет» — файл задачи пропал с диска, печать не начнётся: верните файл на место или удалите задачу. Жёлтая метка «нет подходящего принтера» — файл нарезан под модель или сопло, которых на ферме нет. Кнопка «Проблемы» над списком показывает только такие задачи.",
    en: { title: "Task problems", text: "A red «file is gone» mark means the task file has disappeared from disk and printing will not start: put the file back or delete the task. A yellow «no printer fits» mark means the file is sliced for a model or nozzle the farm does not have. The Problems button above the list shows only such tasks." }
  },
  "qt-req": {
    title: "Нужно копий",
    text: "Сколько копий этого файла нужно напечатать. Например, 10 \u2014 нужно 10 готовых штук.",
    en: { title: "Copies needed", text: "How many copies of this file you need to print. For example, 10 \u2014 you need 10 finished pieces." }
  },
  "qt-prnt": {
    title: "Напечатано копий",
    text: "Сколько копий уже напечатано. Когда «напечатано» догоняет «нужно», задача считается выполненной.",
    en: { title: "Copies printed", text: "How many copies are already printed. When 'printed' reaches 'needed', the task is done." }
  },
  "qt-status": {
    title: "Статус задачи",
    text: "Состояние задачи: ожидание, в процессе или готово. Если файл печатается \u2014 статус кликабелен и подсветит принтеры.",
    en: { title: "Task status", text: "The task's state: pending, in process or done. While the file is printing the status is clickable and highlights the printers." }
  },
  "qt-printing": {
    title: "Печатается",
    text: "Сколько копий этого файла печатается прямо сейчас (на всех принтерах вместе). «\u2014», если печать не идёт.",
    en: { title: "Printing", text: "How many copies of this file are printing right now (across all printers). '\u2014' if nothing is printing." }
  },
  "qt-parts": {
    title: "Детали на плате",
    text: "Состав платы файла: какие детали в нём и по сколько штук. Считывается из файла автоматически при добавлении \u2014 так же, как в проектах.",
    en: { title: "Parts on plate", text: "The file's plate contents: which parts are in it and how many of each. Read from the file automatically when added \u2014 the same as in projects." }
  },
  "qt-total": {
    title: "Всего на плате",
    text: "Всего деталей на плате этого файла \u2014 сумма всех количеств.",
    en: { title: "Total on plate", text: "Total parts on this file's plate \u2014 the sum of all counts." }
  },

  "due-chip": {
    title: "Срок сдачи",
    text: "Срок сдачи проекта клиенту. Нажмите, чтобы задать дату — пресетами (+3 дня / +1 нед / +2 нед) или через календарь, либо убрать срок. Чип краснеет в день срока и накануне, желтеет за несколько дней до него — так дедлайн не теряется из виду. Мелким шрифтом рядом — когда проект создан.",
    en: { title: "Due date", text: "The project's due date for the client. Click to set a date — with presets (+3d / +1wk / +2wk) or a calendar, or clear it. The chip turns red on and just before the due day, and yellow a few days before — so the deadline stays visible. The small text beside it shows when the project was created." }
  },
  "arch-import": {
    title: "Импорт из архива",
    text: "Возвращает проект из архива обратно на доску. Откроется файловый менеджер — выберите сохранённый файл архива, и проект восстановится со всеми деталями, файлами и количествами.",
    en: { title: "Import from archive", text: "Brings a project back from the archive onto the board. The file manager opens — pick a saved archive file and the project is restored with all its parts, files and quantities." }
  },
  "arch-move": {
    title: "Убрать в архив",
    text: "Переносит выбранные проекты с доски в архив: проект исчезает из активного списка, а его файл сохраняется в папку архивов. Доска разгружается, но проект не теряется — его всегда можно вернуть кнопкой «Импорт». Папку архивов можно сменить в Настройки → Хранение данных.",
    en: { title: "Move to archive", text: "Moves the selected projects from the board into the archive: a project disappears from the active list and its file is saved to the archive folder. The board is freed up but nothing is lost — you can always bring it back with the Import button. The archive folder can be changed in Settings → Data storage." }
  },
  "arch-save": {
    title: "Сохранить в архив",
    text: "Сохраняет копию выбранных проектов в архив, оставляя их на доске — это резервная копия на случай потери. Файлы кладутся в ту же папку архивов (её можно сменить в Настройки → Хранение данных).",
    en: { title: "Save to archive", text: "Saves a copy of the selected projects to the archive while leaving them on the board — a backup in case something is lost. Files go to the same archive folder (changeable in Settings → Data storage)." }
  },
  "arch-cancel": {
    title: "Отмена",
    text: "Выходит из режима архива без изменений: снимает выделение с проектов и возвращает обычный вид доски.",
    en: { title: "Cancel", text: "Exits archive mode without changes: clears the project selection and returns the board to its normal view." }
  },
  "set-archive": {
    title: "Папка архивов",
    text: "Папка, куда сохраняются архивы проектов (кнопки «Убрать в архив» и «Сохранить в архив»). Нажмите «Выбрать папку», чтобы указать своё место — например, сетевой или внешний диск для резервных копий. Рядом можно открыть текущую папку или сбросить на расположение по умолчанию.",
    en: { title: "Archive folder", text: "The folder where project archives are saved (used by the Move to archive and Save to archive buttons). Click Choose folder to set your own location — for example a network or external drive for backups. Next to it you can open the current folder or reset to the default location." }
  },
  //  ════════════════════════════════════════════════════════════════════════════════════════
  //  16.10.2026 (R-152, R-110): тексты для элементов оформления 3.0, у которых data-help был,
  //  а записи не было — подсказка молча не появлялась (пульт принтера, окно запуска печати,
  //  добавление принтера, филамент, настройки модулей, диагностика). Сверено с разметкой и кодом;
  //  полноту проверяет tools/test_help_hints_coverage.py.
  //  ════════════════════════════════════════════════════════════════════════════════════════

  // ---- Общее окно вопроса и значок проблем ----
  "ask-confirm": {
    title: "Подтверждение действия",
    text: "Программа спрашивает, прежде чем выполнить важное действие. Кнопка справа названа самим действием; Enter — согласиться, Esc или щелчок мимо окна — отказаться.",
    en: { title: "Confirm the action", text: "The program asks before carrying out an important action. The right-hand button is named after the action; Enter agrees, Esc or a click outside the window cancels." }
  },
  "alerts": {
    title: "Проблемы принтеров",
    text: "Сколько принтеров сейчас сообщают об ошибке — сбой печати или неисправность. Цвет значка — самая серьёзная из них. Нажмите, чтобы открыть список проблем.",
    en: { title: "Printer problems", text: "How many printers are reporting an error right now — a print failure or a fault. The badge colour shows the most serious one. Click to open the list of problems." }
  },

  // ---- Окно «Параметры запуска печати» ----
  "pso-ext": {
    title: "Внешняя катушка",
    text: "Программа не видит у этого принтера AMS, поэтому печать пойдёт с катушки на внешнем держателе. Перед запуском проверьте, что на нём стоит нужный материал.",
    en: { title: "External spool", text: "The program sees no AMS on this printer, so the print will use the spool on the external holder. Check that the right material is loaded before you start." }
  },
  "pso-src": {
    title: "Источник филамента",
    text: "Откуда принтер возьмёт материал. «Авто (как в файле)» — слоты AMS назначатся по нарезанному файлу, как в Bambu Studio; это безопасный выбор. Отдельный слот AMS или внешняя катушка — для файла с одним материалом: у файла с несколькими материалами программа назначит слоты сама, а с внешней катушкой его не отправит.",
    en: { title: "Filament source", text: "Where the printer takes the material from. “Auto (as in file)” assigns AMS slots from the sliced file, as Bambu Studio does — the safe choice. A single AMS slot or the external spool is for single-material files: for a multi-material file the program assigns the slots itself and will not send it with the external spool." }
  },
  "pso-ext-note": {
    title: "Внешняя катушка при AMS",
    text: "Вся печать пойдёт с внешнего держателя, слоты AMS не используются. Файл с несколькими материалами с внешней катушкой программа не отправит и скажет об этом — для него выберите «Авто» или слот AMS.",
    en: { title: "External spool with an AMS", text: "The whole print uses the external holder; AMS slots are not used. A multi-material file is not sent with the external spool, and the program says so — choose Auto or an AMS slot for it." }
  },
  "pso-cfs": {
    title: "Ячейка CFS",
    text: "Выбор ячейки короба CFS у Creality K2. Номер ячейки записан в самом файле; программа может заменить его перед отправкой. Многоцветный файл не изменяется никогда.",
    en: { title: "CFS slot", text: "Choose the CFS box slot on a Creality K2. The slot number is written in the file itself; the program can change it before sending. A multi-colour file is never modified." }
  },
  "pso-cfs-sel": {
    title: "Какая ячейка",
    text: "«Как в файле» — файл уходит без изменений. Выбранная ячейка — программа поставит её номер в файл перед отправкой. Если в ячейке другой материал, печать не начнётся.",
    en: { title: "Which slot", text: "“As in file” sends the file unchanged. For a chosen slot the program writes its number into the file before sending. If that slot holds a different material, the print will not start." }
  },
  "pso-kl": {
    title: "Подготовка Klipper",
    text: "Дополнительные шаги перед печатью, которые конфигурация этого принтера точно поддерживает: программа читает их у самого принтера. Без галочек печать идёт как в файле. Неактивная галочка — программа не может гарантировать этот шаг, например он уже задан в файле.",
    en: { title: "Klipper preparation", text: "Extra steps before the print that this printer's configuration is proven to support — the program reads them from the printer itself. With nothing ticked the print runs as in the file. A greyed-out box means the program cannot guarantee that step, for example because the file already does it." }
  },

  // ---- Панель добавления принтера ----
  "pf-sheet": {
    title: "Добавление принтера",
    text: "Здесь заводится новый принтер или меняются данные существующего: имя, модель, адрес и способ подключения. Пока не заполнены имя, адрес и модель, кнопка сохранения недоступна.",
    en: { title: "Add a printer", text: "Register a new printer or change an existing one: name, model, address and connection. The save button stays unavailable until the name, address and model are filled in." }
  },
  "pf-find": {
    title: "Найти в сети",
    text: "Программа 25 секунд слушает, что принтеры объявляют о себе в локальной сети, и сама спрашивает «кто здесь»; по выбранной строке она заполняет форму. Код доступа вводите вы: по сети он не передаётся.",
    en: { title: "Find on the network", text: "For 25 seconds the program listens to what printers announce on the local network and asks “who is here” itself; it fills in the form from the row you pick. You enter the access code yourself — it is not sent over the network." }
  },
  "pf-demo-n": {
    title: "Сколько виртуальных",
    text: "Сколько виртуальных принтеров добавить за один раз — от 1 до 50.",
    en: { title: "How many virtual", text: "How many virtual printers to add at once — from 1 to 50." }
  },
  "pf-demo": {
    title: "Виртуальные принтеры",
    text: "Добавляет принтеры для проверок: адрес и код им не нужны. Печатают по часам — 10 с греют стол, 10 с сопло, 20 с печатают — и проходят очередь и счёт в задачах так же, как настоящие.",
    en: { title: "Virtual printers", text: "Adds printers for testing — they need no address or code. They print on a timer (10 s bed, 10 s nozzle, 20 s printing) and go through the queue and task counting just like real ones." }
  },
  "pf-save-copy": {
    title: "Сохранить копию",
    text: "Добавляет принтер и оставляет форму заполненной — удобно заводить несколько одинаковых. Поменяйте имя, адрес и код и сохраните следующий.",
    en: { title: "Save copy", text: "Adds the printer and keeps the form filled in — handy for several identical printers. Change the name, address and code, then save the next one." }
  },

  // ---- Карточки принтеров ----
  "pick-num": {
    title: "Порядок выбора",
    text: "Номер — в каком порядке вы выбрали этот принтер для запуска печати. Повторный щелчок по карточке снимает выбор.",
    en: { title: "Selection order", text: "The number shows the order in which you picked this printer for the print. Click the card again to unselect it." }
  },
  "pc-dash": {
    title: "Карточка дашборда",
    text: "Короткая сводка принтера: печатает — файл, ход и остаток времени; завершил — «освободите стол»; ошибка или пауза — что случилось. Карточки выстроены по важности.",
    en: { title: "Dashboard card", text: "A short summary of the printer: printing — file, progress and time left; finished — “clear the plate”; error or pause — what happened. Cards are ordered by importance." }
  },

  // ---- Панель «Подсказки» ----
  "suggest-msgs": {
    title: "Сообщения",
    text: "Что сообщает программа: отправки файлов, запуск печати, списание филамента, ошибки связи. Обычные сообщения уходят сами через несколько секунд, предупреждения — когда перестают быть актуальными (не позже чем через 20 минут), ошибки остаются, пока вы их не закроете (× или «Очистить»).",
    en: { title: "Messages", text: "What the program reports: file sends, print starts, filament write-offs, connection errors. Ordinary messages go away by themselves after a few seconds, warnings once they no longer apply (after 20 minutes at most), and errors stay until you close them (× or Clear)." }
  },

  // ---- Пульт принтера (оформление 3.0) ----
  "ui3-pp": {
    title: "Пульт принтера",
    text: "Всё управление одним принтером: печать, температуры, материал, служебные действия, камера и текущее задание. Закрывается крестиком справа вверху.",
    en: { title: "Printer panel", text: "All controls for one printer: printing, temperatures, material, service actions, camera and the current job. Close it with the × at the top right." }
  },
  "pp-state": {
    title: "Состояние принтера",
    text: "Что принтер делает сейчас: печатает, пауза, готовится, готово, сбой, свободен, занят или не в сети. Обновляется само по данным принтера.",
    en: { title: "Printer state", text: "What the printer is doing now: printing, paused, preparing, done, failed, idle, busy or offline. Updates by itself from the printer's data." }
  },
  "pp-close": {
    title: "Закрыть пульт",
    text: "Возвращает к проектам и задачам. Печать на принтере это не затрагивает.",
    en: { title: "Close the panel", text: "Returns to projects and tasks. The print on the printer is not affected." }
  },
  "pp-alert": {
    title: "Главная проблема",
    text: "Самая серьёзная проблема этого принтера понятными словами. «+N» — сколько ещё; «Подробнее» открывает список проблем.",
    en: { title: "Main problem", text: "The most serious problem of this printer in plain words. “+N” is how many more there are; Details opens the list of problems." }
  },
  "pp-hms": {
    title: "Сообщения принтера",
    text: "Сообщения с экрана самого принтера. Известные коды переведены; незнакомые показаны кодом — полный текст на экране принтера или по QR-коду на нём.",
    en: { title: "Printer messages", text: "Messages from the printer's own screen. Known codes are translated; unknown ones are shown as a code — the full text is on the printer screen or behind its QR code." }
  },
  "pp-print": {
    title: "Печать",
    text: "Во время печати — пауза, продолжение и стоп. Когда принтер свободен — выбор файла на принтере и запуск или отправка файла с компьютера.",
    en: { title: "Print", text: "While printing — pause, resume and stop. When the printer is free — pick a file on the printer and start it, or send a file from this computer." }
  },
  "pp-resume": {
    title: "Продолжить",
    text: "Продолжает печать после паузы с того же места. Перед продолжением проверьте материал и стол.",
    en: { title: "Resume", text: "Continues the print from where it paused. Check the material and the plate before resuming." }
  },
  "pp-pause": {
    title: "Пауза",
    text: "Приостанавливает печать без подтверждения; деталь остаётся на столе. Продолжить можно отсюда или с экрана принтера.",
    en: { title: "Pause", text: "Pauses the print without asking; the part stays on the plate. Resume it here or on the printer screen." }
  },
  "pp-stop": {
    title: "Стоп",
    text: "Прерывает печать насовсем — продолжить её будет нельзя. Перед остановкой программа спросит подтверждение.",
    en: { title: "Stop", text: "Aborts the print for good — it cannot be resumed. The program asks for confirmation first." }
  },
  "pp-pfiles": {
    title: "Файлы принтера",
    text: "Открывает проводник файлов, которые лежат на этом принтере: поиск, сортировка, предпросмотр. Удалять файлы может администратор, если удаление включено в настройках и принтер это умеет; файл идущей печати защищён.",
    en: { title: "Printer files", text: "Opens the browser of files stored on this printer: search, sorting, preview. An administrator can delete files if deletion is turned on in the settings and the printer supports it; the active print file is protected." }
  },
  "pp-file": {
    title: "Файл на принтере",
    text: "Выберите файл, который уже лежит на принтере, — потом нажмите «Печатать». Цифра справа — сколько файлов на принтере.",
    en: { title: "File on the printer", text: "Choose a file that is already on the printer, then press Print. The number on the right is how many files the printer holds." }
  },
  "pp-files-menu": {
    title: "Список файлов",
    text: "Файлы, которые сообщил принтер. Щелчок выбирает файл для печати; сама печать начнётся только по кнопке «Печатать».",
    en: { title: "File list", text: "Files reported by the printer. A click selects the file to print; printing starts only when you press Print." }
  },
  "pp-go": {
    title: "Печатать",
    text: "Запускает выбранный файл на этом принтере. У Bambu с AMS программа сначала спросит, с какой катушки печатать, и запомнит выбор до закрытия пульта.",
    en: { title: "Print", text: "Starts the selected file on this printer. On a Bambu printer with an AMS the program first asks which spool to use and remembers the choice until the panel is closed." }
  },
  "pp-ams-menu": {
    title: "Катушка для печати",
    text: "С какого слота AMS или с внешней катушки печатать. Рядом — остаток со склада, если катушка привязана. Выбор сразу запускает печать.",
    en: { title: "Spool for this print", text: "Which AMS slot, or the external spool, to print from. The stock remainder is shown next to it if a spool is bound. Choosing starts the print right away." }
  },
  "pp-upload": {
    title: "Отправить файл с компьютера",
    text: "Выберите файл печати (.gcode или .3mf) на этом компьютере — после окна параметров запуска программа отправит его на принтер и запустит. С модулем «Складской учёт» материал сверяется со складом так же, как в очереди.",
    en: { title: "Send a file from this computer", text: "Pick a print file (.gcode or .3mf) on this computer — after the print start options window the program sends it to the printer and starts it. With the Inventory module, material is checked against stock the same way as in the queue." }
  },
  "pp-temps": {
    title: "Температуры",
    text: "Текущая температура → заданная. Кнопки «−/+» меняют задание на 5° и меньше чем через секунду отправляют его принтеру; в поле можно ввести число и нажать Enter.",
    en: { title: "Temperatures", text: "Current temperature → target. The −/+ buttons change the target by 5° and send it to the printer in under a second; you can also type a number and press Enter." }
  },
  "pp-nozzle": {
    title: "Сопло",
    text: "Температура сопла: сейчас → цель. Во время печати меняйте осторожно: слишком низкая температура или 0 срывает печать.",
    en: { title: "Nozzle", text: "Nozzle temperature: now → target. Change it carefully while printing — too low a value or 0 ruins the print." }
  },
  "pp-bed": {
    title: "Стол",
    text: "Температура стола: сейчас → цель. Если во время печати выключить нагрев, деталь может оторваться от стола.",
    en: { title: "Bed", text: "Bed temperature: now → target. Turning the heat off during a print can make the part come loose." }
  },
  "pp-chamber": {
    title: "Термокамера",
    text: "Температура камеры: сейчас → цель, до 65 °C. Строка видна только у принтеров с нагревом камеры.",
    en: { title: "Chamber", text: "Chamber temperature: now → target, up to 65 °C. The row is shown only for printers with a heated chamber." }
  },
  "pp-presets": {
    title: "Пресеты прогрева",
    text: "Один щелчок задаёт сопло и стол по пресету (и камеру, если она у пресета задана, а принтер её греет). «Остыть» выключает нагрев. Пресеты общие для всей фермы.",
    en: { title: "Preheat presets", text: "One click sets the nozzle and bed from the preset (and the chamber, if the preset has it and the printer heats it). Cool down turns the heating off. Presets are shared by the whole farm." }
  },
  "pp-presets-edit": {
    title: "Изменить пресеты",
    text: "Открывает редактор пресетов прогрева. Изменения увидят все компьютеры и телефоны фермы.",
    en: { title: "Edit presets", text: "Opens the preheat preset editor. Changes are seen by every computer and phone of the farm." }
  },
  "pp-presets-editor": {
    title: "Редактор пресетов",
    text: "Имя до 12 знаков, температура сопла, стола и камеры; пустая камера — не трогать её. «Встроенные» подставляет заводской набор, «Сохранить» записывает пресеты для всей фермы.",
    en: { title: "Preset editor", text: "Name up to 12 characters, nozzle, bed and chamber temperatures; leave the chamber empty to keep it as is. Built-in fills in the default set, Save stores the presets for the whole farm." }
  },
  "pp-material": {
    title: "Материал",
    text: "Слоты AMS или CFS так, как их сообщает принтер; подсвечен слот, из которого идёт печать. Ниже — катушки со склада, привязанные к принтеру.",
    en: { title: "Material", text: "AMS or CFS slots as the printer reports them; the slot in use is highlighted. Below are the stock spools bound to this printer." }
  },
  "pp-stock": {
    title: "Катушки со склада",
    text: "Сколько граммов осталось на привязанных катушках по учёту модуля «Складской учёт». Выделенная строка — на катушке осталось 15 % или меньше.",
    en: { title: "Stock spools", text: "Grams left on the bound spools according to the Inventory module. A highlighted row means 15 % or less is left on the spool." }
  },
  "pp-tools": {
    title: "Служебное",
    text: "Действия, которые сейчас имеют смысл для этого принтера: подтвердить «Стол очищен», сверить катушки со складом, собрать диагностику Klipper.",
    en: { title: "Service", text: "Actions that make sense for this printer right now: confirm “Plate cleared”, reconcile spools with stock, collect a Klipper diagnostics report." }
  },
  "pp-view": {
    title: "Камера или деталь",
    text: "Переключает правую часть пульта между живой камерой принтера и картинкой печатаемой детали.",
    en: { title: "Camera or part", text: "Switches the right side of the panel between the printer's live camera and a picture of the part being printed." }
  },
  "pp-full": {
    title: "Во весь экран",
    text: "Открывает камеру этого принтера во весь экран.",
    en: { title: "Full screen", text: "Shows this printer's camera full screen." }
  },
  "pp-cam-on": {
    title: "Показать камеру",
    text: "Включает живую картинку с камеры этого принтера прямо в пульте.",
    en: { title: "Show the camera", text: "Turns on the live picture from this printer's camera inside the panel." }
  },
  "pp-part": {
    title: "Деталь",
    text: "Картинка детали из файла печати. Если у файла нет картинки или принтер свободен, здесь об этом написано.",
    en: { title: "Part", text: "A picture of the part from the print file. If the file has no picture or the printer is idle, it says so here." }
  },
  "pp-job": {
    title: "Задание",
    text: "Что печатается: файл, детали на плите, ход в процентах, сколько осталось и прошло, когда начато и к какому времени будет готово.",
    en: { title: "Job", text: "What is printing: the file, parts on the plate, progress in percent, time left and elapsed, when it started and when it will be done." }
  },

  // ---- Панель «Проекты · Задачи · Очередь · Филамент» ----
  "ui3-rtabs-mod": {
    title: "Кнопка модуля",
    text: "Открывает окно установленного модуля. Какие модули показывать здесь, выбирается в «Настройки → Модули».",
    en: { title: "Module button", text: "Opens the window of an installed module. Which modules appear here is chosen in Settings → Modules." }
  },
  "ui3-fil": {
    title: "Филамент фермы",
    text: "Одна таблица на всю ферму: где какая катушка стоит и сколько на ней осталось. Экран только показывает — ни печать, ни склад он не меняет.",
    en: { title: "Farm filament", text: "One table for the whole farm: which spool sits where and how much is left. This screen only shows data — it changes neither prints nor stock." }
  },
  "fil-sum": {
    title: "Итог по ферме",
    text: "Сколько принтеров и слотов, сколько граммов на ферме по складу, сколько катушек скоро кончится и сколько слотов пусто.",
    en: { title: "Farm totals", text: "How many printers and slots, how many grams are on the farm by stock records, how many spools are running low and how many slots are empty." }
  },
  "fil-threshold": {
    title: "Порог предупреждения",
    text: "Ниже какого остатка, в процентах, катушка считается «скоро кончится». Порог общий для всех компьютеров фермы.",
    en: { title: "Warning threshold", text: "Below which remainder, in percent, a spool counts as running low. The threshold is shared by all computers of the farm." }
  },
  "fil-printer": {
    title: "Принтер и его слоты",
    text: "Слоты одного принтера. Щелчок по имени открывает пульт принтера.",
    en: { title: "Printer and its slots", text: "The slots of one printer. Click the name to open the printer panel." }
  },
  "fil-slot": {
    title: "Слот",
    text: "Материал, цвет и производитель в слоте и остаток в граммах и процентах. Граммы видны, если к слоту привязана катушка со склада. Подсвечен — скоро кончится или пусто.",
    en: { title: "Slot", text: "Material, colour and brand in the slot, and what is left in grams and percent. Grams show when a stock spool is bound to the slot. Highlighted — running low or empty." }
  },

  // ---- Проекты и задачи ----
  "pr-reveal": {
    title: "Открыть расположение файла",
    text: "Открывает проводник программы на папке, где лежит файл этой детали, и выделяет его.",
    en: { title: "Open file location", text: "Opens the program's file browser at the folder that holds this part's file and highlights it." }
  },
  "qt-sync": {
    title: "Синхронизация с проектом",
    text: "Включено — каждая удачная печать засчитывается и в задаче, и в проекте. Выключено — только в задаче. Переключать может тот, у кого есть право на проекты.",
    en: { title: "Sync with project", text: "On — every successful print counts in both the task and the project. Off — only in the task. Only users with project rights can switch it." }
  },
  "col-notes": {
    title: "Заметка к детали",
    text: "Свободный текст к детали: цвет, особенности, кому отдать. Сохраняется, когда вы уходите из поля.",
    en: { title: "Part note", text: "Free text for the part: colour, special notes, who it is for. Saved when you leave the field." }
  },
  "qt-reveal": {
    title: "Открыть расположение файла",
    text: "Открывает проводник программы на папке, где лежит файл этой задачи, и выделяет его.",
    en: { title: "Open file location", text: "Opens the program's file browser at the folder that holds this task's file and highlights it." }
  },

  // ---- Настройки ----
  "set-pf-read": {
    title: "Чтение файлов с принтеров",
    text: "Разрешает программе показывать список файлов, который хранит принтер. Ничего на принтере не меняет. Функция пробная.",
    en: { title: "Read files from printers", text: "Lets the program show the list of files stored on the printer. Changes nothing on the printer. Experimental." }
  },
  "set-pf-del": {
    title: "Разрешить удаление файлов",
    text: "Без этого флажка кнопка удаления недоступна. Удаление необратимо; файл идущей печати и служебные файлы защищены всегда.",
    en: { title: "Allow deleting files", text: "Without this box the delete button is unavailable. Deletion cannot be undone; the active print file and system files are always protected." }
  },
  "set-mod-bar": {
    title: "Кнопки модулей на панели",
    text: "Отметьте модули, которые нужны под рукой: их кнопки встанут справа на панели «Проекты · Задачи · Очередь · Филамент». Выбор общий для всей фермы.",
    en: { title: "Module buttons on the bar", text: "Tick the modules you want at hand: their buttons appear on the right of the “Projects · Tasks · Queue · Filament” bar. The choice is shared by the whole farm." }
  },
  "set-mod-cfg": {
    title: "Настройки модуля",
    text: "Настройки этого модуля прямо здесь: у него нет отдельного окна. Изменения касаются только этого модуля.",
    en: { title: "Module settings", text: "This module's settings, right here — it has no window of its own. Changes affect only this module." }
  },

  // ---- Диагностика и камера ----
  "diag-queue": {
    title: "Вкладка «Очередь запуска»",
    text: "Сохранённая на сервере очередь поэтапного запуска: принтер, время старта, попытки и последняя ошибка. Ожидающий запуск можно отменить — один или всю пачку.",
    en: { title: "Launch queue tab", text: "The staged launch queue saved on the server: printer, start time, attempts and the last error. A pending launch can be cancelled — one or the whole batch." }
  },
  "diag-sniff": {
    title: "Вкладка «Перехват Studio»",
    text: "Инструмент для разбора проблем с Bambu Lab: программа только слушает и показывает, что Bambu Studio отправляет принтеру по кнопке Send. Сама ничего не шлёт, останавливается через 2 минуты или по кнопке; запускает перехват администратор.",
    en: { title: "Studio capture tab", text: "A tool for Bambu Lab troubleshooting: the program only listens and shows what Bambu Studio sends to the printer when you press Send. It sends nothing itself and stops after 2 minutes or by the button; an administrator starts the capture." }
  },
  "cam-fmp4": {
    title: "Без перекодирования",
    text: "Показывает видео Bambu как есть: картинку разбирает видеокарта, сервер почти не нагружается. Если изображение не появилось, выключите. Выбор хранится в этом браузере.",
    en: { title: "No transcoding", text: "Shows the Bambu video as is: the graphics card decodes it and the server is barely loaded. If no picture appears, turn it off. The choice is kept in this browser." }
  }
};
