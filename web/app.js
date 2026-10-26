// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.

/*
============================================================================
3DIWELL Farm Manager — КЛИЕНТСКАЯ ЛОГИКА VUE

Файл управляет состоянием интерфейса, WebSocket, HTTP API, принтерами,
проектами, Tasks, диагностикой, обучением и двумя файловыми менеджерами.
Он намеренно остаётся одним модулем на этом этапе: добавлены только русские
комментарии, без изменения вычислений, запросов, таймеров и обработчиков.

Связь файлов:
  index.html  — Vue-шаблон и расположение блоков;
  app.css     — оформление, цвета, размеры, переходы и keyframes;
  app.js      — данные, действия пользователя, API и жизненный цикл;
  vendor/*    — локальные Vue и статически собранный Tailwind.
============================================================================
*/
// БЛОК: загрузка Vue и старт клиентского модуля.
import { usePrinterBadges } from './composables/usePrinterBadges.js';
import { createFmp4Player } from './composables/useCameraFmp4.js';   // Alpha 2.870: камера без перекодирования
import { usePrinterFilament } from './composables/usePrinterFilament.js';
import { createApp, ref, reactive, computed, onMounted, onUnmounted, nextTick, watch, provide, markRaw } from 'vue';
import { tourSteps as FULL_TOUR_STEPS, quickTourSteps as QUICK_TOUR_STEPS, tourGroupLabels as TOUR_GROUP_LABELS, tourGroupOrder as TOUR_GROUP_ORDER } from './composables/tourSteps.js';
import { HELP_HINTS } from './composables/helpHints.js';
// Компоненты (Фаза 1+ миграции: выносим разметку из index.html в .js-файлы).
import StatusBadge from './components/ui/StatusBadge.js';
import Toast from './components/ui/Toast.js';
import ProjectCell from './components/projects/ProjectCell.js';
import DueChip from './components/projects/DueChip.js';
import ViewModeSwitch from './components/printers/ViewModeSwitch.js';
import ContextMenu from './components/ui/ContextMenu.js';
import DiagRow from './components/diagnostics/DiagRow.js';
import SvgIcon from './components/ui/SvgIcon.js';
import { icons, svgAssets } from '../design/icons.js';
//  Обучение (тур по интерфейсу) ВЫКЛЮЧЕНО — решение владельца 12.09.2026: на этом этапе его не
//  видно и оно не запускается ни при старте, ни из настроек. Код тура НЕ удалён — его будут
//  дорабатывать; вернуть = поставить true. Подсказки при наведении — отдельная функция, работают.
const TOUR_ENABLED = false;
console.log('%c[3DIWELL] UI {{ VERSION }} загружен', 'color:#4da6ff;font-weight:bold');


// БЛОК: единая доставка ошибок браузера в серверную live-диагностику.
// --- Изоляция сбоев интерфейса (Стадия 3) -----------------------------------
// ПРАВИЛО: любой сбой в UI (исключение в компоненте Vue, глобальная ошибка JS,
// «повисшее» отклонение промиса) НЕ должен гасить интерфейс и обязан попасть в
// панель диагностики. Клиентские ошибки шлём на сервер (POST /api/diagnostics/client)
// и кладём в тот же кольцевой буфер, что и серверные — единое окно для анализа.
// reportClientError сам НИКОГДА не бросает (иначе перехватчик породил бы новый сбой)
// и дедуплицирует одинаковые сообщения (защита от потока при повторяющейся ошибке рендера).
const _reportedErrors = {};
const reportClientError = (level, msg, where) => {
    try {
        const text = (where ? '[' + where + '] ' : '') + (msg || '');
        const now = Date.now();
        if (_reportedErrors[text] && now - _reportedErrors[text] < 5000) return;   // не чаще раза в 5с на одинаковое
        _reportedErrors[text] = now;
        fetch('/api/diagnostics/client', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ level: level || 'error', msg: text }) }).catch(() => {});
    } catch (e) { /* отчёт об ошибке не имеет права сам бросать */ }
};
// Глобальная синхронная ошибка JS (вне Vue): ловим и шлём в панель, вывод в консоль браузера не подавляем.
window.onerror = (message, source, lineno, colno, error) => {
    reportClientError('error', String(message) + (lineno ? ' @' + lineno + ':' + colno : ''), 'window');
    return false;
};
// «Повисшее» отклонение промиса (например, упавший fetch без .catch) — иначе исчезло бы тихо.
window.addEventListener('unhandledrejection', (ev) => {
    const r = ev && ev.reason;
    reportClientError('warning', (r && r.message ? r.message : String(r)), 'promise');
});
// Перехват console.error / console.warn: то, что в F12 выглядит как ошибка/предупреждение
// (в т.ч. ВСТРОЕННЫЕ предупреждения Vue — например «свойство использовано в шаблоне, но не
// возвращено из setup», битый шаблон, неразрешённый компонент), дублируем в серверный журнал.
// Оригинальный console сохраняем — в F12 всё по-прежнему видно. Дедуп в reportClientError
// защищает от потока повторов. console.log НЕ трогаем (это обычный шум, не сбой).
(function () {
    const _ce = console.error.bind(console), _cw = console.warn.bind(console);
    const _txt = (args) => {
        try {
            return Array.prototype.map.call(args, function (a) {
                if (a instanceof Error) return (a.stack || a.message || String(a));
                if (a && typeof a === 'object') { try { return JSON.stringify(a); } catch (e) { return String(a); } }
                return String(a);
            }).join(' ');
        } catch (e) { return ''; }
    };
    console.error = function () { _ce.apply(console, arguments); try { reportClientError('error', _txt(arguments), 'console'); } catch (e) {} };
    console.warn = function () { _cw.apply(console, arguments); try { reportClientError('warning', _txt(arguments), 'console'); } catch (e) {} };
})();


// БЛОК: глобальное включение адаптивной версии без изменения десктопа.
// ===== Рубильник мобильной версии =====
// Один выключатель на ВСЮ мобильную адаптацию. false → класс .m-ui не вешается (мобильный CSS
// весь под .m-ui — становится неактивным) И isMobile всегда false (вся логика-разметка возвращается
// к десктопной). То есть установка false полностью откатывает интерфейс к исходному, ничего не удаляя.
const MOBILE_UI_ENABLED = true;
if (MOBILE_UI_ENABLED) document.documentElement.classList.add('m-ui');

const __app = createApp({
setup() {

    // ------------------------------------------------------------------------
    // БЛОК: локализация и пользовательские настройки отображения.
    // RU содержит словарь, tr() выбирает перевод, localStorage запоминает язык
    // и режим карточек принтеров.
    // ------------------------------------------------------------------------
    // ===== i18n (EN/RU) =====
    const RU = {"Nozzle": "Сопло", "Bed": "Стол", "Dashboard": "Дашборд", "Dashboard view": "Дашборд", "Print finished": "Печать завершена", "Clear the plate": "Освободите стол", "Free": "Свободен", "Paused": "На паузе", "Busy": "Занят", "Progress": "Прогресс", "Failed to start print.": "Не удалось запустить печать.", "send rejected": "Отправка отклонена", "Offline": "Не в сети", "Chamber": "Камера", "left": "осталось", "Preparing": "Готовится", "Needs attention": "Требует внимания", "No printers yet": "Принтеров пока нет", "a project": "проекте", "This model is in project": "Эта модель есть в проекте", "Prints count only in the task. Click to also count them in the project.": "Печати считаются только в задаче. Нажмите, чтобы считать их и в проекте.", "Synced with project": "Синхронизировано с проектом", "Every print counts in the task and in the project. Click to turn off.": "Каждая печать считается и в задаче, и в проекте. Нажмите, чтобы выключить.", "Could not change project sync": "Не удалось переключить синхронизацию с проектом", "Welcome": "Добро пожаловать", "This is 3DIWELL Farm Manager — it runs your whole 3D printer farm from one screen: printers on the left, projects and Tasks on the right. This tour walks you through every part of the interface. Your real printers, projects and tasks are never touched during the tour.": "Это 3DIWELL Farm Manager — управление всей фермой 3D-принтеров с одного экрана: принтеры слева, проекты и задачи справа. Это обучение проведёт вас по всем частям интерфейса. Ваши реальные принтеры, проекты и задачи во время обучения не затрагиваются.", "Connection and sync": "Связь и сохранение", "This indicator shows whether the interface is connected to the running 3DIWELL server. Green means connected, red means the connection is lost. The sync icon beside it lights up the instant your changes are being saved — everything you do is saved automatically.": "Этот индикатор показывает, есть ли связь интерфейса с работающим сервером 3DIWELL. Зелёный — связь есть, красный — связь потеряна. Значок синхронизации рядом загорается в момент сохранения изменений — всё, что вы делаете, сохраняется автоматически.", "Interface language": "Язык интерфейса", "Click the flag to switch the whole interface between Russian and English at any moment. Your choice is remembered for next time.": "Нажмите на флаг, чтобы переключить весь интерфейс между русским и английским в любой момент. Выбор запоминается на будущее.", "Undo": "Отмена", "Undo your last action — deleting a project or a part, a rename and similar changes. The button appears only when there is something to undo.": "Отмена последнего действия — удаления проекта или детали, переименования и подобных изменений. Кнопка появляется, только когда есть что отменить.", "Settings": "Настройки", "The gear opens Settings. Let us open it and walk through every section: editions, appearance, deadlines, slicer, tools, access, modules and more.": "Шестерёнка открывает настройки. Давайте откроем их и пройдём по всем разделам: редакции, оформление, сроки, слайсер, инструменты, доступ, модули и другое.", "Program editions": "Редакции программы", "3DIWELL comes in three editions. Personal — a single workstation. Team — shared work with deadlines and suggestions. Business — everything, plus user roles and an audit log. A higher edition unlocks more sections of this very menu.": "3DIWELL выпускается в трёх редакциях. Индивидуальный — одно рабочее место. Коллективный — совместная работа со сроками и подсказками. Корпоративный — всё это плюс роли пользователей и журнал аудита. Старшая редакция открывает больше разделов этого же меню.", "Appearance": "Оформление", "Appearance has two settings. Theme switches the whole interface between a light and a dark look, to suit your workshop and the time of day. Font changes the typeface used across the program. Both choices are saved on this computer.": "Здесь два параметра. Тема переключает весь интерфейс между светлым и тёмным видом — под ваш цех и время суток. Шрифт меняет начертание текста во всей программе. Оба выбора сохраняются на этом компьютере.", "Due dates": "Сроки", "Turn on creation dates and project deadlines. Set how many days before a deadline a project starts warning you in yellow, so a due date is never missed.": "Включите даты создания и сроки проектов. Задайте, за сколько дней до срока проект начинает предупреждать жёлтым, чтобы ни один дедлайн не был пропущен.", "Default slicer": "Слайсер по умолчанию", "Choose which slicer opens your models — auto-detect or a specific program. It is used whenever you send a model to be sliced.": "Выберите, в каком слайсере открываются модели — автоопределение или конкретная программа. Используется при отправке модели на нарезку.", "Tools": "Инструменты", "Service tools live here, including Diagnostics — a live log of the server that helps you find the cause of a problem. We will see it in action on the next step.": "Здесь живут служебные инструменты, в том числе диагностика — журнал сервера в реальном времени, помогающий найти причину проблемы. На следующем шаге увидим её в действии.", "Diagnostics": "Диагностика", "This is the diagnostics log: a live stream of server events. It only shows what is happening and never affects the printers — use it to track down a failure. Shown here as a demo.": "Это журнал диагностики: поток событий сервера в реальном времени. Он только показывает происходящее и никогда не влияет на принтеры — используйте его, чтобы найти причину сбоя. Показано как демонстрация.", "Access, roles and audit": "Доступ, роли и аудит", "Protect the farm with a sign-in. When access control is on, everyone logs in with their own name and password. Each user gets a role: Administrator has full control, Operator runs printing and projects, Assembler marks parts done and sends them for rework, and Observer is view-only — the interface hides whatever a role may not use. Every important action — sign-ins, project and part changes, archiving and imports — is written to the audit log, so you always see who did what and when.": "Защитите ферму входом по логину. Когда контроль доступа включён, каждый входит под своим именем и паролем. У каждого пользователя своя роль: Администратор — полный контроль, Оператор управляет печатью и проектами, Сборщик отмечает готовые детали и отправляет их на перепечатку, Наблюдатель — только просмотр; интерфейс скрывает то, что роли недоступно. Каждое важное действие — входы, изменения проектов и деталей, архивирование, импорт — пишется в журнал аудита, поэтому всегда видно, кто, что и когда сделал.", "Modules": "Модули", "Optional add-on modules appear here. Active ones can be launched straight from this menu; the rest are marked as coming soon.": "Здесь появляются дополнительные модули. Активные запускаются прямо из этого меню; остальные помечены как «скоро».", "About the program": "О программе", "About opens a card with the program name, the exact build version, your edition, the website and support — handy when you report an issue or check which version you are running.": "«О программе» открывает карточку с названием, точной версией сборки, вашей редакцией, сайтом и поддержкой — удобно, когда сообщаете о проблеме или проверяете, какая версия запущена.", "Your printers": "Ваши принтеры", "This column is your printer fleet. Every card shows live status, print progress and elapsed time. Sorting and the view switch sit at the top of the column.": "Эта колонка — ваш парк принтеров. Каждая карточка показывает живой статус, прогресс печати и прошедшее время. Сортировка и переключатель вида — вверху колонки.", "Sort printers": "Сортировка принтеров", "Sort the cards by status — busy and free grouped together — or by name, so the printer you need is easy to find.": "Сортируйте карточки по статусу — занятые и свободные группируются вместе — или по имени, чтобы нужный принтер было легко найти.", "List or grid": "Список или сетка", "Switch between a detailed list and a compact grid. The grid fits many printers on screen at once; the list shows full controls for each.": "Переключайтесь между подробным списком и компактной сеткой. Сетка вмещает много принтеров сразу; список показывает полное управление каждым.", "Add a printer": "Добавить принтер", "Add Printer opens a catalog of supported models. Pick yours and fill in its address and details, and the printer joins the fleet ready to work.": "«Добавить принтер» открывает каталог поддерживаемых моделей. Выберите свою, укажите адрес и параметры — и принтер встаёт в строй, готовый к работе.", "Compact card and status colors": "Карточка и цвета статусов", "In the grid each printer is a compact card, tinted with its status color and showing a progress bar and the completion percentage — a quick read across the whole farm. The colors are consistent everywhere: free, printing, paused and error each have their own shade, so a glance at the wall of cards tells you the state of every machine.": "В сетке каждый принтер — компактная карточка, окрашенная в цвет статуса, с полосой прогресса и процентом готовности — быстрый обзор по всей ферме. Цвета одинаковы везде: свободен, печатает, пауза и ошибка — у каждого свой оттенок, поэтому одного взгляда на стену карточек достаточно, чтобы понять состояние любой машины.", "Expanded card": "Раскрытая карточка", "In the list a card expands into a full control panel. The four numbered buttons are: 1 Start runs or resumes a print, 2 Stop aborts the job (it asks for confirmation first, so nothing is cancelled by accident), 3 Pause pauses it, and 4 PRINT sends the file chosen in the Select file box beside the buttons. The Upld button uploads a file from your computer onto the printer. While a print is running this bottom row stays inactive. The panel also shows the live nozzle and bed temperatures, a preview of the part on the plate, the print progress with a real elapsed-time stopwatch, the camera button, and the loaded material or AMS slots when the printer has them.": "В списке карточка раскрывается в полный пульт управления. Четыре пронумерованные кнопки: 1 Старт запускает или продолжает печать, 2 Стоп прерывает задание (сначала спрашивает подтверждение, чтобы ничего не отменить случайно), 3 Пауза приостанавливает, 4 ПЕЧАТЬ отправляет файл, выбранный в ячейке «Выбрать файл» рядом с кнопками. Кнопка «Загр.» загружает файл с вашего компьютера на принтер. Во время печати этот нижний ряд остаётся неактивным. Панель также показывает живые температуры сопла и стола, превью детали на плате, прогресс печати с реальным секундомером, кнопку камеры и загруженный материал или слоты AMS, если они у принтера есть.", "Print with an AMS slot": "Печать с выбором слота AMS", "Press Load, pick a file in the built-in file manager and press Print. If the printer has an AMS or a similar system, a slot picker appears — choose the slot with the filament you need and printing begins. Shown here as a demo.": "Нажмите «Загрузить», выберите файл во встроенном файл-менеджере и нажмите «Печать». Если у принтера есть AMS или похожая система, появится выбор слота — укажите слот с нужным пластиком, и печать начнётся. Показано как демонстрация.", "Projects": "Проекты", "This is the projects area — your production board. A project groups the parts and files of one order together and tracks how many of each part are finished. Click the Projects heading at the top to sort the cards by name or by the date they were added.": "Это область проектов — ваша производственная доска. Проект объединяет детали и файлы одного заказа и отслеживает, сколько каждой детали готово. Нажмите на заголовок «Проекты» вверху, чтобы сортировать карточки по имени или по дате добавления.", "Create a project": "Создать проект", "New Project creates an empty project by name; you then add its parts and attach a printable file to each. You can also start from files: load a set of models or g-codes and a dated project is built for you automatically, already filled with parts.": "«Новый проект» создаёт пустой проект по имени; затем вы добавляете его детали и прикрепляете к каждой печатный файл. Можно начать и с файлов: загрузите набор моделей или G-кодов — и проект с датой создастся автоматически, уже заполненный деталями.", "Project card": "Карточка проекта", "Each project is a card showing its name and how many parts are finished out of the total. The card is tinted by status and fills up as parts get printed, so a wall of projects reads like a dashboard. A rework badge appears when a part needs reprinting — a failed print or a rejected piece — so projects needing attention stand out. A deadline shows as a chip and turns yellow as the date nears. Click a card to open the project: there you switch between the By parts and By files views, edit it to rename it or add and remove parts and files, and send parts to print directly onto any compatible free printer — the finished counts update as parts come off the machines.": "Каждый проект — это карточка с именем и числом готовых деталей из общего. Карточка окрашена по статусу и заполняется по мере печати, поэтому стена проектов читается как сводка. Значок перепечатки появляется, когда деталь нужно перепечатать — неудачная печать или брак — чтобы проекты, требующие внимания, выделялись. Срок показан чипом и желтеет по мере приближения даты. Нажмите на карточку, чтобы открыть проект: внутри переключаются виды «По деталям» и «По файлам», в режиме правки проект можно переименовать, добавить или убрать детали и файлы, а детали отправляются на печать напрямую на любой совместимый свободный принтер — счётчики готового обновляются по мере выхода деталей с машин.", "Archive": "Архив", "Archive keeps finished work without cluttering the board. From here you move or save a project into the archive, and bring it back later by importing it again.": "Архив хранит завершённую работу, не загромождая доску. Отсюда проект убирается или сохраняется в архив, а позже возвращается обратно повторным импортом.", "Tasks": "Задачи", "Tasks is for printing single files without a project — handy for one-offs and test pieces. Files dropped here are ready to print on any compatible free printer.": "Задачи — для печати отдельных файлов без проекта, удобно для разовых и пробных деталей. Брошенные сюда файлы готовы к печати на любом совместимом свободном принтере.", "Drag and drop": "Перетащите файл", "Drop a file onto this zone, or click to pick one, and it is added to Tasks until you send it to a printer. A ready g-code can print straight away; a model — an STL or a STEP — must be sliced into g-code first, so only printable files can actually start.": "Перетащите файл в эту зону или нажмите, чтобы выбрать — он добавится в задачи и будет ждать там, пока вы не отправите его на принтер. Готовый G-код печатается сразу; модель — STL или STEP — сначала нужно нарезать в G-код, поэтому начать печать могут только готовые файлы.", "Load a file into tasks": "Загрузка файла в задачи", "The Open button launches the built-in file manager. Select a printable file there and press Load to tasks — the file lands in Tasks, ready to go. The same file manager opens whenever you click a file name in Tasks or on a project part, jumping straight to that file with it highlighted, so you never lose track of where things live. Shown here as a demo.": "Кнопка «Открыть» запускает встроенный файл-менеджер. Выберите там готовый файл и нажмите «Загрузить в задачи» — файл попадёт в задачи, готовый к печати. Тот же файл-менеджер открывается по клику на имя файла в задачах или на детали проекта — сразу на этом файле с подсветкой, чтобы вы не теряли, где что лежит. Показано как демонстрация.", "A task row": "Строка задачи", "Each task is a row showing the file name, how many copies are needed and already printed, and its current status — the same simple counting used for project parts. Expand a row for everything else: add a note, open a model in the slicer, print the file, or jump to its location on disk.": "Каждая задача — строка с именем файла, числом нужных и уже напечатанных копий и текущим статусом — тот же простой подсчёт, что и у деталей проекта. Разверните строку для всего остального: добавить заметку, открыть модель в слайсере, напечатать файл или перейти к его расположению на диске.", "Find where it is printing": "Где печатается", "When a part or a file is printing, its status becomes clickable. Click it and the printers running that job light up while the rest dim, so you instantly see where it is being printed. Shown here as a demo.": "Когда деталь или файл печатается, его статус становится кликабельным. Нажмите — и принтеры, выполняющие это задание, подсветятся, а остальные погаснут, чтобы вы сразу увидели, где идёт печать. Показано как демонстрация.", "Suggestions and alerts": "Подсказки и оповещения", "For every free printer the system suggests the next suitable file to print, so an idle machine never sits waiting for you to decide what is next. Anything that needs your attention also shows up here as an alert — a failed print, an incompatible g-code, or a printer out of filament — so problems surface instead of hiding.": "Для каждого свободного принтера система предлагает следующий подходящий файл, чтобы простаивающая машина не ждала, пока вы решите, что печатать дальше. Всё, что требует внимания, тоже появляется здесь оповещением — неудачная печать, несовместимый G-код или закончившийся пластик — чтобы проблемы всплывали, а не прятались.", "You are all set": "Всё готово", "That is the whole interface — printers, projects, Tasks, the archive, settings and the suggestions. The same farm fits your phone, so you can watch prints and start files while away from the workstation, and you can replay this tour any time from Settings, Help, Interface tour. Enjoy a calmer, clearer farm — and happy printing!": "Вот и весь интерфейс — принтеры, проекты, задачи, архив, настройки и подсказки. Та же ферма помещается в телефон, чтобы следить за печатью и запускать файлы вдали от рабочего места, а это обучение можно пройти заново в любой момент: Настройки → Обучение → Обучение интерфейсу. Лёгкой и понятной вам фермы — и удачной печати!", "Error": "Ошибка", "ms": "мс", "Failed to load files.": "Не удалось загрузить файлы.", "LINK": "СВЯЗЬ", "hide": "скрыть", "By part": "По деталям", "By file": "По файлам", "Expand all": "Развернуть все", "Collapse all": "Свернуть все", "Edit project": "Редактировать", "Any printer": "Любой принтер", "Collapse project": "Свернуть проект", "View": "Просмотр", "Print on": "Печать на", "No compatible idle printers.": "Нет совместимых свободных принтеров.", "Select printer": "Выбрать принтер", "Sending…": "Отправка…", "Start printing": "Запустить на печать", "Sent to printers": "Отправлено на принтеры", "Sending to printers…": "Отправка на принтеры…", "File is not compatible with this printer.": "Файл несовместим с этим принтером.", "Could not start print.": "Не удалось запустить печать.", "+ New Project": "+ Новый проект", "Project name": "Название проекта", "Create": "Создать", "No projects yet.": "Пока нет проектов.", "+ File": "+ Файл", "Upload file": "Загрузить файл", "Add files (.gcode / .3mf)": "Добавить файлы (.gcode / .3mf)", "No files in this project.": "В этом проекте нет файлов.", "On plate": "На плате", "No parts found": "Детали не найдены", "+ Add part": "+ Добавить деталь", "Part name": "Название детали", "Sliced for:": "Нарезано под:", "Hide": "Скрыть", "connection issue": "проблема со связью", "Latency trend": "Тренд задержки", "Speed test": "Тест скорости", "Testing…": "Тест…", "Speed test unavailable for FlashForge": "Тест скорости недоступен для Flashforge", "Test failed": "Тест не удался", "The printer is printing. The speed test will upload and delete a small file, which may briefly affect the print. Continue?": "Принтер сейчас печатает. Тест скорости зальёт и удалит маленький файл — это может кратковременно повлиять на печать. Продолжить?", "Background monitor": "Фоновый мониторинг", "Continuous background latency monitoring": "Непрерывный фоновый мониторинг задержки", "Log": "Журнал", "Connection": "Связь", "Checking…": "Проверка…", "Refresh": "Обновить", "Printer": "Принтер", "Status": "Статус", "Network": "Сеть", "Issues": "Проблемы", "Checking connection…": "Проверка связи…", "No printers": "Нет принтеров", "Stop the print? The current job will be aborted and cannot be resumed.": "Остановить печать? Текущее задание будет прервано без возможности возобновления.", "Show printer": "Показать принтер", "Remaining": "Осталось", "For example": "Например", "New Project": "Новый проект", "Select a file to preview": "Выберите файл для предпросмотра", "selected": "выбрано", "By status": "По статусу", "By name": "По имени", "Sorting": "Сортировка", "Delete": "Удалить", "Delete this printer?": "Удалить этот принтер?", "Auto-detect now recognizes the path format itself (incl. P2S/H2S) and remembers it. Change this only if a print will not start.": "Автоопределение теперь само распознаёт формат пути (в т.ч. P2S/H2S) и запоминает рабочий. Меняйте вручную, только если печать не запускается.", "FTP (P2S/H2S — ftp://)": "FTP (P2S/H2S — ftp://)", "New (H2D — brtc://emmc/)": "Новое (H2D — brtc://emmc/)", "Print failed with 0500-4002? Set generation: FTP for P2S/H2S, New for H2D, Old for X1/P1.": "Печать не идёт с ошибкой 0500-4002? Поколение: FTP для P2S/H2S, New для H2D, Old для X1/P1.", "Generic": "Универсальные", "Model": "Модель", "Select model": "Выбрать модель", "Search models…": "Поиск моделей…", "No model covers found — put the cover PNGs into a printer_covers folder next to server.py.": "Обложки моделей не найдены — положите PNG-обложки в папку printer_covers рядом с server.py.", "Edit Printer": "Изменить принтер", "Register Printer": "Добавить принтер", "Save Changes": "Сохранить", "Register": "Добавить", "Access Token": "Токен доступа", "Serial number (required for P1P/P1S/P1C)": "Серийный номер (нужен для P1P/P1S/P1C)", "e.g. 01PXXXXXXXXXXXX — P1 series only": "напр. 01PXXXXXXXXXXXX — только серия P1", "P1P/P1S/P1C do not broadcast status — the serial lets us request it (pushall). For X1/H2D leave empty.": "P1P/P1S/P1C не транслируют статус — серийник нужен, чтобы его запросить (pushall). Для X1/H2D оставьте пустым.", "Serial:CheckCode (e.g. SNXXX:1a2b3c)": "Serial:CheckCode (напр. SNXXX:1a2b3c)", "PRINT": "ПЕЧАТЬ", "ERR": "ОШ.", "Select file...": "Выбрать файл...", "Selecting files…": "Выбор файлов…", "drop / insert files": "перетащите / вставьте файлы", "Refresh previews from files": "Обновить превью из файлов", "Updating…": "Обновление…", "Live": "Эфир", "Open file folder: ": "Открыть папку файла: ", "Not ready to print: ": "Не готово к печати: ", "Preview": "Превью", "camera": "камера", "OFFLINE": "офлайн", "IDLE": "свободен", "RUNNING": "печать", "PREPARE": "подгот.", "PAUSE": "пауза", "PAUSED": "пауза", "FINISH": "готово", "FAILED": "сбой", "SLICING": "нарезка", "PRINTING": "печать", "READY": "готов", "STANDBY": "ожидание", "COMPLETE": "завершено", "BUSY": "занят", "UNKNOWN": "неизв.", "OFF": "выкл", "printing": "печать", "ready": "готов", "paused": "пауза", "standby": "ожидание", "complete": "завершено", "error": "ошибка", "cancelled": "отменено", "finish": "готово", "prepare": "подгот.", "running": "печать", "offline": "офлайн", "idle": "свободен", "slicing": "нарезка", "pause": "пауза", "failed": "сбой", "+ Add Component": "Добавить деталь", "+ Add Project": "Добавить проект", "Active Printers": "Принтеры", "Archive": "Архив", "Attach": "Привязать", "Auto": "Авто", "Auto-detect": "Автоопределение", "Choose manually…": "Выбрать вручную…", "Choose slicer": "Выбрать слайсер", "DONE": "ГОТОВО", "Data Broker": "Брокер данных", "Delete Project": "Удалить проект", "Editing...": "Правка...", "Ext. spool": "Внешняя катушка", "File": "Файл", "File name": "Имя файла", "Generation (print format)": "Поколение (формат печати)", "IMPORT PLAN/ARCHIVE": "ИМПОРТ ПЛАНА/АРХИВА", "IN PROCESS": "В ПРОЦЕССЕ", "Idle": "Свободен", "Idle printers:": "Свободные принтеры:", "If printing fails with error 0500-4002, manually select \"New\" for P2S/H2D or \"Old\" for X1/P1.": "Если печать не запускается с ошибкой 0500-4002 — выберите вручную «New» для P2S/H2D или «Old» для X1/P1.", "No compatible printers": "Нет совместимых принтеров", "No files staged yet.": "Пока нет файлов.", "No parts in this project.": "В этом проекте нет деталей.", "Notes": "Заметки", "New (H2D/P2S — brtc://emmc/)": "Новое (H2D/P2S — brtc://emmc/)", "Old (X1/P1 — file:///sdcard/)": "Старое (X1/P1 — file:///sdcard/)", "PART NAME": "НАЗВАНИЕ ДЕТАЛИ", "PENDING": "ОЖИДАНИЕ", "SENDING": "ОТПРАВКА", "Parts on plate": "Детали на плате", "Printers": "Принтеры", "Prnt": "Итог", "Tasks": "Задачи", "Req": "План", "printing now": "печатается", "file is gone": "файла нет", "no printer fits": "нет подходящего принтера", "The file of this task is not on disk any more. Printing it will not start. Put the file back or delete the task.": "Файла этой задачи больше нет на диске. Печать не начнётся. Верните файл на место или удалите задачу.", "This file is sliced for a printer that is not on the farm: the model or the nozzle does not match any of yours.": "Файл нарезан под принтер, которого нет на ферме: модель или сопло не совпадают ни с одним из ваших.", "Problems": "Проблемы", "Group": "Группировка", "No grouping": "нет", "By project": "по проекту", "By folder": "по папке", "Outside projects": "Вне проектов", "No folder": "Без папки",  "Plate contents not recognized": "Состав плиты не распознан", "plate contents parsing is turned off in settings": "разбор состава плиты выключен в настройках", "this file format is not parsed": "этот формат файла не разбирается", "the service data inside the file is damaged or unreadable": "служебные данные внутри файла повреждены или непонятны", "the file has no object names": "в файле нет имён объектов", "object names repeat and cannot be told apart": "имена объектов повторяются, разделить их нельзя", "too many objects on the plate": "слишком много объектов на плите", "the file has no layer marks": "в файле не размечены слои", "the file is too large to parse": "файл слишком большой для разбора", "parsing took too long and was stopped": "разбор занял слишком много времени и был остановлен", "Minus one": "Убавить на одну", "Plus one": "Прибавить на одну", "Saving...": "Сохранение...", "Select AMS slot:": "Выберите слот AMS:", "Serial and Check Code (Printer ID) — in the printer menu: Settings → Network. Format: serial, colon, code. Default port 8898.": "Serial и Check Code (Printer ID) — в меню принтера: Настройки → Сеть. Формат: серийник, двоеточие, код. Порт по умолчанию 8898.", "Slicer:": "Слайсер:", "Status": "Статус", "Synchronized": "Сохранено", "Link to the server": "Связь с сервером", "Saving changes": "Сохранение изменений", "List or grid view": "Список или сетка", "Print progress": "Прогресс печати", "Temperatures": "Температуры", "Drop a file here": "Перетащите файл сюда", "Undo": "Отменить", "Upld": "Загр.", "Waiting...": "Ожидание...", "originals, no copies · Ctrl/Shift to select multiple": "оригиналы, без копий · Ctrl/Shift — выбрать несколько", "⏸ Pause": "⏸ Пауза", "⏹ Stop": "⏹ Стоп", "▶ Print": "▶ Печать", "▶ Start": "▶ Старт", "Attach file (.gcode / .3mf) — no copies, by original": "Привязать файл (.gcode / .3mf) — без копий, по оригиналу", "Camera": "Камера", "List view": "Список", "Grid view": "Сетка", "Detach": "Отвязать", "Edit printer": "Редактировать принтер", "External spool": "Внешняя катушка", "IP Address": "IP-адрес", "Open in slicer (add to plate)": "Открыть в слайсере (добавить на плиту)", "Slice": "Нарезать", "G-code files": "G-code файлы", "Pause": "Пауза", "Port": "Порт", "Print": "Печать", "Printing": "В печати", "Printer Node Name": "Имя принтера", "Re-read previews from the g-code files (overwrite stale ones)": "Перечитать предпросмотры из самих g-кодов (перекрыть устаревшие)", "Start/Resume": "Старт/Продолжить", "Start": "Старт", "Stop": "Стоп", "Total Time": "Общее время", "Total": "Всего", "Elapsed": "Время печати", "Project Yield:": "Выход проекта:", "pcs": "шт", "files": "файлов", "Done": "Готово", "Edit": "Изменить", "Simple": "Обычный", "Advanced": "Продвинутый", "Simple edit mode": "Обычный режим правки", "Advanced edit mode": "Продвинутый режим правки", "Cancel": "Отмена", "＋ Add Printer": "＋ Добавить", "in process": "в процессе", "pending": "ожидание", "sending": "отправка", "done": "готово", "Failed to attach file.": "Не удалось привязать файл.", "Failed to refresh previews.": "Не удалось обновить предпросмотры.", "Incompatible printer! ": "Несовместимый принтер! ", "The file is sliced for a different printer type.": "Файл нарезан для другого типа принтера.", " Print anyway?": " Всё равно запустить печать?", "Print not started. ": "Печать не запущена. ", "Slicer not found automatically. Select the slicer program (.exe) manually?": "Слайсер не найден автоматически. Указать программу-слайсер (.exe) вручную?", "Failed to set the slicer.": "Не удалось указать слайсер.", "Failed to open in slicer: ": "Не удалось открыть в слайсере: ", "Imported: ": "Импортировано: ", " parts": " деталей", "Import failed: ": "Ошибка импорта: ", "unknown": "неизвестно", "Import failed": "Ошибка импорта", "Previews updated: ": "Обновлено предпросмотров: ", "no preview in file": "нет превью в файле", "file not found": "файл не найден", "Could not write the file to the printer. Most likely no microSD card is inserted (or it is full). Insert a card and try again.": "Не удалось записать файл на принтер. Скорее всего, в принтер не вставлена microSD-карта (или она заполнена). Вставьте карту и попробуйте снова.", "No connection to the printer to upload the file. Make sure the printer is powered on and online.": "Нет связи с принтером для загрузки файла. Проверьте, что принтер включён и в сети.", "The file was uploaded to the printer, but the print start command did not get through (no MQTT connection). Please try again.": "Файл загружен на принтер, но команда запуска печати не дошла (нет связи по MQTT). Попробуйте ещё раз.", "only .gcode and .3mf are supported": "поддерживаются только .gcode и .3mf", "Uploading to printer…": "Загрузка на принтер…", "Print started": "Печать запущена", "Sending to printer…": "Отправка на принтер…", "Uploading file…": "Загрузка файла…", "Adding file…": "Добавление файла…", "Adding files…": "Добавление файлов…", "Refreshing previews…": "Обновление превью…", "Importing…": "Импорт…", "Adding to tasks…": "Добавление в задачи…", "you must select a slicer .exe": "нужно выбрать .exe слайсера", "only a model (.stl/.3mf/.obj/.step) can be sent to the slicer": "в слайсер можно отправить только модель (.stl/.3mf/.obj/.step)", "Files": "Файлы", "STL/3MF files": "файлы stl/3mf", "Parts": "Детали", "Server files": "Файлы на сервере", "Up": "Вверх", "Size": "Размер", "Modified": "Изменён", "Download": "Скачать", "This folder is empty": "Папка пуста", "Loading…": "Загрузка…", "Delete this file?": "Удалить этот файл?", "Delete this part?": "Удалить эту деталь?", "Delete part": "Удалить деталь", "Refresh": "Обновить", "read only": "только чтение", "Quick access": "Быстрый доступ", "This PC": "Этот компьютер", "Type": "Тип", "Folder": "Папка", "items": "элементов", "Load to tasks": "Загрузить в задачи", "Open": "Открыть", "Close": "Закрыть", "Desktop": "Рабочий стол", "Downloads": "Загрузки", "Documents": "Документы", "File system": "Файловая система", "Local Disk": "Локальный диск", "Removable Disk": "Съёмный диск", "Network Drive": "Сетевой диск", "CD Drive": "CD-дисковод", "Invalid path": "Некорректный путь", "Not a folder or path is unavailable": "Это не папка или путь недоступен", "No access to this folder": "Нет доступа к этой папке", "Zoom out": "Уменьшить", "Zoom in": "Увеличить", "Reset zoom (100%)": "Сбросить масштаб (100%)", "Choose file": "Выбрать файл", "Add files": "Добавить файлы", "Add folder": "Добавить папку", "Add components from files / folder (STL, 3MF, G-code)": "Добавить детали из файлов / папки (STL, 3MF, G-code)", "No STL / 3MF / G-code files in this folder": "В этой папке нет файлов STL / 3MF / G-code", "Diagnostics": "Диагностика", "Diagnostics — live server log": "Диагностика — журнал сервера в реальном времени", "All": "Все", "Info+": "Важное", "Warnings": "Предупреждения", "Errors": "Ошибки", "Verbose console": "Подробная консоль", "Auto-scroll": "Автопрокрутка", "Clear": "Очистить", "No records yet": "Пока нет записей", "Download logs": "Скачать логи", "Download logs to send to support": "Скачать журнал для отправки в техподдержку", "Stream debug telemetry to the CMD window (does not affect this panel)": "Выводить debug-телеметрию в окно CMD (на эту панель не влияет)", "Delete this project?": "Удалить этот проект?", "Import": "Импорт", "Export archive": "Экспорт архива", "Archive loaded": "Архив загружен", "Drag to resize": "Перетащите, чтобы изменить ширину", "Pick the model — it lets the app match this printer to compatible g-code.": "Выберите модель — программа сможет сопоставлять принтер с подходящим g-code.", "Model not set — this printer may be offered for g-code it cannot print. Click to set the model.": "Модель не задана — принтер может предлагаться под g-code, который он не печатает. Нажмите, чтобы выбрать модель.", "A different printer type responds at this address: ": "По этому адресу отвечает принтер другого типа: ", ". Save with the selected model anyway?": ". Всё равно сохранить с выбранной моделью?", "Printer not reachable yet — check power and network.": "Принтер пока недоступен — проверьте питание и сеть.", "Projects": "Проекты", "Suggestions": "Подсказки", "No suggestions right now": "Пока нет подсказок", "Settings": "Настройки", "Appearance": "Вид", "Theme": "Тема", "Tools": "Инструменты", "Modules": "Модули", "Slicer": "Слайсер", "Update available": "Доступно обновление", "Update": "Обновить", "Send": "Отправить", "Welcome": "Добро пожаловать", "This is 3DIWELL Farm Manager — it runs your whole 3D printer farm from one screen. This tour walks you through the main parts of the interface. Your real printers, projects and tasks are not affected during the tour.": "3DIWELL Farm Manager — пульт управления всей фермой 3D-принтеров с одного экрана. Это обучение проводит вас по основным блокам интерфейса. Реальные принтеры, проекты и задачи во время тура не затрагиваются.", "Connection and sync": "Связь и синхронизация", "The dot shows the live link to your printers (green means connected). Next to it the sync indicator shows when changes are being saved.": "Точка показывает связь с принтерами (зелёная — есть связь). Рядом индикатор синхронизации: когда изменения сохраняются.", "Undo your last action - deleting a project or part, a rename and similar changes. It appears only when there is something to undo.": "Откат последнего действия: удаления проекта или детали, переименования и подобных изменений. Кнопка появляется только тогда, когда есть что отменять.", "Language": "Язык", "Switch the whole interface between English and Russian at any time.": "Переключение всего интерфейса между русским и английским языком. Менять можно в любой момент.", "Sort printers": "Сортировка принтеров", "Sort the printer cards by status (busy and free grouped together) or by name.": "Сортировка карточек принтеров: по статусу (занятые и свободные группируются вместе) или по имени.", "List or grid": "Список или сетка", "Switch the printers between a detailed list and a compact grid of cards.": "Переключение принтеров между подробным списком и компактной сеткой карточек.", "Printer card": "Карточка принтера", "Each card shows status, a progress bar, elapsed time and, if available, a camera and AMS slots. Click it to open controls: start, pause and stop.": "На карточке — статус, полоса прогресса, время печати и, если есть, камера и слоты AMS. Клик открывает управление: старт, пауза, стоп.", "Add a project": "Добавить проект", "Right-click an empty spot in the projects area to add a new project, then add parts to it.": "Чтобы добавить проект, нажмите правой кнопкой мыши по пустому месту в области проектов и выберите создание. После этого добавляйте в проект детали.", "Part row": "Строка детали", "The part row shows the printed / needed counters and the current status. Attach a printable file to the part and press print — then choose a suitable printer in the popup (make sure it is compatible with the selected g-code).": "Строка детали показывает счётчики «напечатано / нужно» и текущий статус. Привяжите к детали печатаемый файл и нажмите печать — после этого во всплывающем окне выберите подходящий принтер (убедитесь, что принтер совместим с выбранным g-code).", "Add a file to Tasks by dragging it in or using the file picker, then print it on any free printer.": "Добавьте файл в Задачи перетаскиванием или через выбор файла, затем печатайте на любом свободном принтере.", "Open file location": "Открыть расположение файла", "Slicer choice": "Выбор слайсера", "Pick which slicer opens your models: auto-detect or a specific program. It is used when you send a model to slice.": "Здесь выбирается, какой слайсер открывает ваши модели: автоопределение или конкретная программа. Это используется, когда вы отправляете модель на нарезку.", "Model not installed": "Модель не установлена", "Your printer fleet with live status, progress and elapsed time. Switch list or grid view and sorting at the top.": "Здесь весь ваш парк принтеров с живым статусом, прогрессом печати и временем. Сверху — переключение вида (список или сетка) и сортировки.", "Add a printer": "Добавить принтер", "The Add Printer button lets you choose the model you need and add it by entering all the required printer details for a correct setup.": "Кнопка «Добавить принтер»: позволяет выбрать нужную модель и добавить её, указав все нужные параметры принтера для корректного добавления.", "Projects and parts": "Проекты и детали", "A project holds parts with printed and needed counters. Attach a printable file (gcode or 3mf) to a part and pick a compatible free printer.": "Проект содержит детали со счётчиком напечатано/нужно. Привяжите к детали печатаемый файл (.gcode/.3mf) и выберите совместимый свободный принтер.", "Print a single file without a project: drop or pick it here. A model (STL or STEP) must be sliced first; only printable files can start.": "Задачи — это печать одиночного файла без проекта. Перетащите сюда файл или выберите его вручную. Модель (STL/STEP) сначала нужно нарезать в слайсере; запускаются только готовые к печати файлы.", "Suggestions and alerts": "Подсказки и предупреждения", "For each free printer the system offers the next suitable file. Problems that need your attention show up here as alerts — for example a print failure, an incompatible g-code, or a printer out of filament.": "Для каждого свободного принтера система предлагает следующий подходящий файл. Здесь появляются предупреждения, требующие вашего внимания — например, сбой печати, несовместимый g-code или закончившийся на принтере филамент.", "Import plan / archive": "Импорт плана / архива", "Load a production plan or an archive of files to quickly fill projects and Tasks.": "Загрузите план производства или архив файлов, чтобы быстро наполнить проекты и Задачи.", "A live log of the server — it helps you find the cause of a failure. It only shows events and never affects the printers. Shown here as a demo.": "Живой журнал работы сервера — нужен, чтобы найти причину сбоя. Он только показывает события и на принтеры никак не влияет. Здесь показан демо-пример.", "Tour": "Обучение", "Interface tour": "Интерактивное обучение по интерфейсу", "Back": "Назад", "Next": "Далее", "Printer": "Принтер", "print failure - check the printer": "сбой печати — проверьте принтер", "offline - no connection": "офлайн — нет связи", "This indicator shows whether the interface is connected to the running 3DIWELL program (the server). Green means connected, red means the connection is lost. Next to it the sync icon lights up the moment your changes are being saved.": "Этот индикатор показывает связь интерфейса с запущенной программой 3DIWELL (сервером). Зелёный — связь есть, красный — потеряна. Рядом загорается значок синхронизации в тот момент, когда ваши изменения сохраняются.", "This button loads a production plan (prepared in your CAD program) or an archive of files — to quickly fill projects and Tasks without adding everything by hand.": "Кнопка загружает план производства (подготовленный в вашей CAD-программе) или архив с файлами — чтобы быстро наполнить проекты и Задачи, не добавляя всё вручную.", "Right now the printers are shown as a compact grid. Each card shows the status (the whole cell is tinted with its color), a progress bar and the completion percentage. On the next step we will expand a card and go through its controls.": "Сейчас принтеры показаны компактной сеткой. На каждой карточке видны статус (вся ячейка окрашена в его цвет), полоса прогресса и проценты выполнения. На следующем шаге мы раскроем карточку и разберём управление.", "Expanded card controls": "Управление в раскрытой карточке", "The expanded card shows temperatures, print time and the controls. The numbered buttons: ① Start runs or resumes the print, ② Stop aborts the job, ③ Pause pauses it. ④ PRINT sends the selected file to print — first pick a file in the Select file… box. While a print is running the bottom row of buttons becomes inactive.": "Раскрытая карточка: температуры, время печати и пульт управления. Кнопки с номерами: ① Старт запускает или продолжает печать, ② Стоп прерывает задание, ③ Пауза приостанавливает. ④ ПЕЧАТЬ запускает выбранный файл на печать — сначала выберите файл в ячейке «Выбрать файл…». Во время печати нижний ряд кнопок становится неактивным.", "Find where a part is printing": "Где печатается деталь", "When a part in a project or a file in Tasks is printing, its status shows as in process and becomes clickable. Click that status and the printer (or printers) running that job light up while the rest dim, so you can instantly see where it is printing. Shown here as a demo.": "Когда деталь в проекте или файл в Задачах печатается, его статус показывает «в процессе» и становится кликабельным. Если нажать на такой статус, принтер или принтеры с этим заданием подсветятся, а остальные затемнятся, и сразу будет видно, на каком или на каких принтерах идёт данная печать. Здесь это показано на демо-примере.", "Loading files into tasks": "Загрузка файлов в задачи", "The Open button launches the built-in file manager. Select a printable file there and press Load to tasks — the file goes into Tasks, ready to print on any compatible free printer. Shown here as a demo.": "Кнопка «Открыть» запускает встроенный файловый менеджер. Выберите в нём печатаемый файл и нажмите «Загрузить в задачи» — файл попадёт в Задачи и будет готов к печати на любом совместимом свободном принтере. Сейчас показан демо-пример того, как это выглядит.", "Editing a part": "Редактирование детали", "In edit mode each part is fully editable: rename it, set how many are needed and printed, change the status, and attach or detach a printable file. Toggle this mode with the Edit button on the project.": "Это режим редактирования детали. В нём деталь настраивается полностью: можно переименовать её, задать сколько нужно и сколько уже напечатано, сменить статус, привязать или отвязать печатаемый файл. Режим включается кнопкой «Изменить» у проекта.", "Print with an AMS slot": "Печать с выбором слота AMS", "Press Load, then in the file manager that opens select a file to print and press Print. If the printer has an AMS (or a similar system), a popup with slot selection appears. As soon as you choose the slot with the filament you need, printing starts. Shown here as a demo.": "Нажмите кнопку «Загрузить», в открывшемся файловом менеджере выберите файл на печать и нажмите «Печать». Если у принтера есть система AMS (или подобная) — появится всплывающее окно с выбором слота. Как только вы выберете нужный слот с филаментом, печать запустится. Здесь показан демо-пример.", "Open a model in the slicer": "Открыть модель в слайсере", "Next to a model file in Tasks there is a slicer button. Click it to open the model in your chosen slicer and add it to the plate. Shown here as a demo.": "Рядом с именем файла-модели в Задачах есть кнопка слайсера. Нажмите её, чтобы открыть модель в выбранном слайсере и добавить её на плиту. Здесь показан демо-пример.", "Opening in slicer…": "Открываю в слайсере…", "Open the file location": "Открыть расположение файла", "Click a file name - in Tasks or on a part in a project - to open the built-in file manager at that file location, with the file highlighted. Shown here as a demo.": "Клик по имени файла — в Задачах или у детали в проекте — открывает встроенный файловый менеджер на папке этого файла, с подсветкой самого файла. Здесь показан демо-пример.", "incompatible g-code for this printer": "несовместимый g-code для этого принтера", "printer error - check the printer": "ошибка принтера — проверьте принтер", "print paused - check filament and the printer": "печать на паузе — проверьте филамент и принтер", "the printer needs attention - check it": "принтеру нужно внимание — проверьте его", "Add to project…": "Добавить в проект…", "New project from file…": "Создать новый проект…", "No projects yet — create one.": "Проектов пока нет — создайте новый.", "New project name:": "Название нового проекта:", "Moved to project: ": "Перенесено в проект: ", "Created project and moved file: ": "Создан проект, файл перенесён: ", "Could not move to project.": "Не удалось перенести в проект.", "Not enough filament on the bound spool. Print anyway?": "На привязанной катушке может не хватить филамента. Печатать всё равно?", "the spool": "катушка", "grams": "г", "A project with this name already exists. Choose a different name.": "Проект с таким названием уже существует. Выберите другое название.", "A folder with this name already exists in Farm Manager storage. Choose a different name.": "Папка с таким названием уже существует в хранилище Farm Manager. Выберите другое название.", "Could not rename the project folder. Close programs that use the project files and try again.": "Не удалось переименовать папку проекта. Закройте программы, использующие файлы проекта, и повторите попытку.", "Enter a project name.": "Введите название проекта.", "This name cannot be used as a folder name. Allowed: letters, digits, spaces and - _ ( ), without a dot at the end.": "Такое название нельзя использовать как имя папки. Допустимы буквы, цифры, пробелы и знаки - _ ( ), без точки в конце.", "This name is reserved by Windows. Choose a different name.": "Это название зарезервировано в Windows. Выберите другое название.", "Project name is too long. Choose a shorter name.": "Название проекта слишком длинное. Выберите более короткое.", "Could not rename the project. Try again.": "Не удалось переименовать проект. Повторите попытку."};

    // Дополнительные переводы для нового производственного блока обучения.
    // Вынесены отдельно, чтобы не править огромный базовый словарь RU вручную.
    Object.assign(RU, {
        "Quick tour": "Короткое обучение",
        "Full tour": "Полное обучение",
        "Project import from files": "Импорт проекта из файлов",
        "You can start a project not only from an empty name, but also from files. When you import g-code, 3MF, STL or STEP files, Farm Manager can prepare a dated project and fill it with parts and printable plates, so the operator does not have to enter everything by hand.": "Проект можно начать не только с пустого названия, но и из файлов. При импорте g-code, 3MF, STL или STEP Farm Manager может подготовить проект с датой и заполнить его деталями и печатными плитами, чтобы оператор не вводил всё вручную.",
        "Part counters": "Счётчики деталей",
        "Inside a project every part has production counters. Part name identifies the item, On plate shows how many of this exact part are printed by the selected file, Needed is the production target, Printed is the accepted finished quantity, and Status helps the operator see what is ready, in progress or needs rework.": "Внутри проекта у каждой детали есть производственные счётчики. Название детали определяет изделие, «На плате» показывает, сколько именно этой детали печатается выбранным файлом, «Нужно» — план производства, «Напечат.» — принятое готовое количество, а статус помогает оператору видеть, что готово, в работе или требует перепечатки.",
        "Automatic part counting": "Автоматический подсчёт деталей",
        "Automatic counting depends on data saved inside the print file. For reliable recognition, enable Label Objects / gcode_label_objects in the slicer before exporting g-code or 3MF. These labels let Farm Manager understand which parts are on the plate and how many copies of each part are present.": "Автоматический подсчёт зависит от данных, сохранённых внутри файла печати. Для надёжного распознавания включайте Label Objects / gcode_label_objects в слайсере перед экспортом g-code или 3MF. Эти метки позволяют Farm Manager понять, какие детали находятся на плите и сколько копий каждой детали есть в файле.",
        "When a file cannot be counted": "Если файл не удалось посчитать",
        "If a file has no object labels or the result is ambiguous, the program should not guess. In this case the operator can check the first print and correct the On plate value manually. This is safer than silently adding the wrong quantity to the project.": "Если в файле нет меток объектов или результат неоднозначный, программа не должна угадывать. В этом случае оператор может проверить первую печать и вручную исправить значение «На плате». Это безопаснее, чем незаметно добавить в проект неправильное количество."
    });

    // Alpha 2.822: подписи миниатюр в редакторе проекта (alt-текст для доступности).
    Object.assign(RU, {
        "Part thumbnail": "Миниатюра детали",
        "File thumbnail": "Миниатюра файла"
    });

    // Alpha 2.823: файловый менеджер принтеров (пункты меню; остальные строки — инлайн в шаблоне).
    Object.assign(RU, {
        "Printer files": "Файлы принтера",
        "Printer files (all)": "Файлы принтеров"
    });
    // Alpha 2.831: сортировка по модели + копирование принтеров.
    Object.assign(RU, {
        "Create copy": "Создать копию",
        "Save copy": "Сохранить копию",
        "Add printer and keep all fields for the next copy": "Добавить принтер и оставить все поля заполненными для следующей копии",
        "Printer added. You can change the fields and save the next copy.": "Принтер добавлен. Можно изменить параметры и сохранить следующую копию.",
        "New printer based on": "Новый принтер на основе",
        "Sort": "Сортировка",
        "Custom order": "Пользовательский порядок",
        "Click again to reverse": "Нажмите ещё раз — обратный порядок",
        "By model": "По модели",
        "By name": "По имени",
        "By status": "По статусу",
        "No model": "Без модели"
    });

    // Подсказки в пустых состояниях (проекты / файлы / детали / задачи) — что делать дальше.
    Object.assign(RU, {
        "No projects yet. Use the + New Project button to create your first one.": "Пока нет проектов. Нажмите «+ Новый проект», чтобы создать первый.",
        "No files in this project yet. Open editing (pencil) and add a .gcode or .3mf file.": "В этом проекте пока нет файлов. Откройте правку (карандаш) и добавьте файл .gcode или .3mf.",
        "No parts yet. Add a file and parts will be detected automatically.": "Деталей пока нет. Добавьте файл — детали определятся автоматически.",
        "No files yet. Drag a .gcode / .3mf file here or click Open.": "Пока нет файлов. Перетащите сюда файл .gcode / .3mf или нажмите «Открыть»."
    });

    // Нейтральная метка «идёт обработка» для индикатора занятости там, где по URL нельзя
    // отличить сохранение от удаления/правки (напр. действия с деталями проекта).
    Object.assign(RU, { "Working…": "Обработка…" });

    // Поиск в «Задачах»: плейсхолдер и подсказка «ничего не найдено».
    Object.assign(RU, { "Search by file name…": "Поиск по имени файла…", "Nothing found": "Ничего не найдено" });

    // Фильтр «Задач» по статусу.
    Object.assign(RU, { "Active": "Активные", "Completed": "Готовые" });

    // Поиск по проектам.
    Object.assign(RU, { "Search projects…": "Поиск по проектам…" });

    // Переводы для навигации по разделам обучения и клавиатурных подсказок.
    Object.assign(RU, {
        "Basics": "Основы",
        "Printers": "Принтеры",
        "Projects and production": "Проекты и производство",
        "Suggestions and alerts": "Предложения и предупреждения",
        "Finish": "Завершение",
        "Section": "Раздел",
        "step": "шаг",
        "of": "из",
        "Skip section": "Пропустить раздел",
        "Keyboard: ← / → — previous / next, Esc — close": "Клавиатура: ← / → — назад / далее, Esc — закрыть"
    });

    // Переводы для раскрываемых подробностей в карточках обучения.
    // Основной текст шагов стал короче, а длинные пояснения открываются кнопкой «Подробнее».
    Object.assign(RU, {
        "More details": "Подробнее",
        "Hide details": "Скрыть подробности",
        "On plate": "На плате",
        "Needed": "Нужно",
        "Printed": "Напечат.",
        "Farm Manager brings printers, projects and Tasks together on one screen. The tour uses only temporary demo data, so your real printers and projects are not changed.": "Farm Manager объединяет принтеры, проекты и задачи на одном экране. Обучение использует только временные демо-данные, поэтому реальные принтеры и проекты не изменяются.",
        "During the tour the program creates a demo printer, a demo project and a demo task only in memory. When you close the tour, the previous interface state is restored.": "Во время обучения программа создаёт демо-принтер, демо-проект и демо-задачу только в памяти. После закрытия обучения прежнее состояние интерфейса восстанавливается.",
        "Access control protects the farm with personal sign-ins and roles. The interface shows only what each role is allowed to use.": "Контроль доступа защищает ферму личными входами и ролями. Интерфейс показывает только то, что разрешено конкретной роли.",
        "Administrator has full control. Operator runs printing and projects. Assembler marks parts done and sends them for rework. Observer is view-only. Important actions are written to the audit log, so you can see who changed what and when.": "Администратор имеет полный контроль. Оператор управляет печатью и проектами. Сборщик отмечает готовые детали и отправляет их на перепечатку. Наблюдатель только смотрит. Важные действия пишутся в журнал аудита, чтобы было видно, кто, что и когда изменил.",
        "In grid view every printer becomes a compact status card with color, progress and completion percentage.": "В режиме сетки каждый принтер становится компактной карточкой со статусным цветом, прогрессом и процентом готовности.",
        "Status colors are consistent across the interface: free, printing, paused and error each have their own shade. This lets you read the whole farm quickly without opening every printer.": "Цвета статусов одинаковы во всём интерфейсе: свободен, печатает, пауза и ошибка имеют свои оттенки. Так можно быстро оценить всю ферму, не открывая каждый принтер.",
        "In list view the printer card opens into a full control panel: start, stop, pause, print, upload, temperatures, preview, progress, camera and materials.": "В режиме списка карточка принтера раскрывается в полный пульт: старт, стоп, пауза, печать, загрузка, температуры, превью, прогресс, камера и материалы.",
        "The numbered controls are: 1 Start or resume, 2 Stop with confirmation, 3 Pause, and 4 PRINT for the file selected in the Select file box. Upld uploads a file from your computer to the printer. While printing, the lower control row stays inactive.": "Пронумерованные элементы: 1 — старт или продолжение, 2 — стоп с подтверждением, 3 — пауза, 4 — ПЕЧАТЬ для файла, выбранного в поле «Выбрать файл». «Загр.» загружает файл с компьютера на принтер. Во время печати нижний ряд управления остаётся неактивным.",
        "Projects are your production board. Each project groups the parts and files of one order and tracks what is already finished.": "Проекты — это производственная доска. Каждый проект объединяет детали и файлы одного заказа и показывает, что уже готово.",
        "Use projects when you need to produce a set of parts, not just print one file. The heading can sort project cards by name or by the date they were added.": "Используйте проекты, когда нужно изготовить набор деталей, а не просто напечатать один файл. Заголовок раздела может сортировать карточки проектов по имени или по дате добавления.",
        "New Project creates an empty project by name. You can then add parts and attach printable files to them.": "«Новый проект» создаёт пустой проект по названию. После этого можно добавить детали и привязать к ним печатные файлы.",
        "You can also start from files: load a set of models or g-codes, and the program can build a dated project automatically with parts already added.": "Также можно начать с файлов: загрузить набор моделей или g-code, и программа сможет автоматически создать проект с датой и уже добавленными деталями.",
        "A project can be created from files, not only from an empty name. This reduces manual entry for the operator.": "Проект можно создать из файлов, а не только из пустого названия. Это уменьшает ручной ввод для оператора.",
        "When you import g-code, 3MF, STL or STEP files, Farm Manager can prepare a dated project and fill it with parts and printable plates.": "При импорте g-code, 3MF, STL или STEP Farm Manager может подготовить проект с датой и заполнить его деталями и печатными плитами.",
        "Each project part has counters: what part it is, how many are on the plate, how many are needed and how many are accepted as printed.": "У каждой детали проекта есть счётчики: что это за деталь, сколько таких деталей на плите, сколько нужно и сколько принято как напечатанные.",
        "Part name identifies the item. On plate shows how many copies of this exact part are produced by the selected file. Needed is the production target. Printed is the accepted finished quantity. Status shows whether the part is ready, in progress or needs rework.": "Название детали определяет изделие. «На плате» показывает, сколько копий именно этой детали делает выбранный файл. «Нужно» — план производства. «Напечат.» — принятое готовое количество. Статус показывает, готова деталь, в работе или требует перепечатки.",
        "Automatic counting works best when the print file contains object labels from the slicer.": "Автоматический подсчёт лучше всего работает, когда файл печати содержит метки объектов из слайсера.",
        "For reliable recognition, enable Label Objects / gcode_label_objects before exporting g-code or 3MF. These labels let Farm Manager understand which parts are on the plate and how many copies of each part are present.": "Для надёжного распознавания включайте Label Objects / gcode_label_objects перед экспортом g-code или 3MF. Эти метки позволяют Farm Manager понять, какие детали находятся на плите и сколько копий каждой детали есть в файле.",
        "If the file has no labels or the result is unclear, the program should not guess the quantity.": "Если в файле нет меток или результат неясен, программа не должна угадывать количество.",
        "The operator can check the first print and correct the On plate value manually. This is safer than silently adding the wrong quantity to the project.": "Оператор может проверить первую печать и вручную исправить значение «На плате». Это безопаснее, чем незаметно добавить в проект неправильное количество.",
        "A project card shows the project name, overall progress, status color, deadline and rework warnings.": "Карточка проекта показывает название, общий прогресс, цвет статуса, срок и предупреждения о перепечатке.",
        "Open a card to work inside the project: switch between By parts and By files, edit names and files, send parts to compatible free printers, and track finished counts as parts come off the machines.": "Откройте карточку, чтобы работать внутри проекта: переключаться между видами «По деталям» и «По файлам», редактировать названия и файлы, отправлять детали на совместимые свободные принтеры и отслеживать готовые количества.",
        "Open launches the built-in file manager. Select a printable file and press Load to tasks.": "«Открыть» запускает встроенный файловый менеджер. Выберите печатный файл и нажмите «Загрузить в задачи».",
        "The same file manager opens when you click a file name in Tasks or on a project part. It jumps straight to that file and highlights it, so you do not lose where files are stored. Shown here as a demo.": "Тот же файловый менеджер открывается при клике по имени файла в задачах или у детали проекта. Он сразу переходит к этому файлу и подсвечивает его, чтобы не терять место хранения. Здесь показан демо-пример.",
        "Each Task row shows the file name, needed quantity, printed quantity and current status.": "Каждая строка задачи показывает имя файла, нужное количество, напечатанное количество и текущий статус.",
        "Expand a row to add a note, open a model in the slicer, print the file, or jump to its location on disk. This uses the same simple counting idea as project parts.": "Раскройте строку, чтобы добавить заметку, открыть модель в слайсере, напечатать файл или перейти к его расположению на диске. Здесь используется та же простая логика счётчиков, что и в деталях проектов.",
        "This area suggests the next suitable file for free printers and shows alerts that need attention.": "Эта область показывает отправки на принтеры и очереди — всё, что программа делает прямо сейчас.",
        "Alerts can include a failed print, incompatible g-code or a printer out of filament. The goal is to surface problems instead of letting them hide in the workflow.": "Предупреждения могут включать сбой печати, несовместимый g-code или закончившийся филамент. Цель — показать проблему сразу, а не прятать её внутри процесса.",
        "That is the interface: printers, projects, Tasks, archive, settings and suggestions. You can replay this tour from Settings at any time.": "Это весь интерфейс: принтеры, проекты, задачи, архив, настройки и предложения. Повторить обучение можно из настроек в любой момент.",
        "The same farm interface also fits a phone or tablet, so you can watch prints and start files while away from the workstation. Happy printing!": "Этот же интерфейс фермы помещается на телефон или планшет, поэтому можно наблюдать за печатью и запускать файлы вдали от рабочего компьютера. Удачной печати!"
    });

    // Переводы для ревизии текстов обучения (этап 17).
    // Вынесены отдельно, чтобы не переписывать большой базовый словарь RU.
    Object.assign(RU, {
        "Welcome": "Добро пожаловать",
        "Farm Manager combines printers, projects and Tasks on one screen. This tour uses temporary demo data and does not change your real printers, projects or tasks.": "Farm Manager объединяет принтеры, проекты и задачи на одном экране. Обучение использует временные демо-данные и не меняет реальные принтеры, проекты или задачи.",
        "During the tour a demo printer, demo project and demo task may appear. They exist only while the tour is open. When you close the tour, the previous interface state is restored.": "Во время обучения могут появляться демо-принтер, демо-проект и демо-задача. Они существуют только пока открыто обучение. После закрытия тура прежнее состояние интерфейса восстанавливается.",
        "Connection and sync": "Связь и сохранение",
        "This indicator shows the connection to the local 3DIWELL server. Green means connected, red means disconnected. The sync icon shows when changes are being saved automatically.": "Этот индикатор показывает связь с локальным сервером 3DIWELL. Зелёный — связь есть, красный — связи нет. Значок синхронизации показывает, когда изменения автоматически сохраняются.",
        "Interface language": "Язык интерфейса",
        "Use these buttons to switch the interface between Russian and English. The selected language is remembered in this browser.": "Эти кнопки переключают интерфейс между русским и английским языком. Выбранный язык запоминается в этом браузере.",
        "Settings": "Настройки",
        "The gear opens Settings. Here you configure the interface mode, appearance, dates, slicer, tools, access, modules and information about the program.": "Шестерёнка открывает настройки. Здесь есть широкий выбор настроек для оптимизации под ваш стиль работы, а также дополнительные сведения.",
        "Interface mode": "Режим интерфейса",
        "Choose the interface mode. It only changes which sections are visible. All program features are free; only some separate modules are paid.": "Выберите режим интерфейса. Он меняет только набор видимых разделов. Все функции программы бесплатны; платными бывают только отдельные модули.",
        "Personal is for one workstation and hides projects and deadlines. Team and Business show every section. Access & audit is available in any mode.": "Индивидуальный — для одного рабочего места: разделы проектов и сроков скрыты. Коллективный и Корпоративный показывают все разделы. «Доступ и аудит» есть в любом режиме.",
        "Appearance": "Оформление",
        "Appearance controls the interface theme and font. Use it to make the screen easier to read in your workshop.": "В оформлении можно изменить настройки интерфейса для более удобной работы с программой.",
        "The theme switches between light and dark mode. The font setting changes the text style across the interface. Both choices are saved on this computer.": "Тема переключает светлый и тёмный режим. Настройка шрифта меняет стиль текста во всём интерфейсе. Оба выбора сохраняются на этом компьютере.",
        "Dates and deadlines": "Даты и сроки",
        "Enable creation dates and project deadlines. The warning period decides when a project starts turning yellow before the deadline.": "Включите даты создания и сроки проектов. Период предупреждения определяет, за сколько дней до срока проект начнёт подсвечиваться жёлтым.",
        "Default slicer": "Слайсер по умолчанию",
        "Choose which slicer opens model files: automatic detection or a specific program. This is used when a model needs to be prepared for printing.": "Выберите, какой слайсер открывает файлы моделей: автоопределение или конкретная программа. Это используется, когда модель нужно подготовить к печати.",
        "Tools and diagnostics": "Инструменты и диагностика",
        "Service tools are grouped here. Diagnostics opens a live server log that helps find the cause of a problem.": "Здесь собраны служебные инструменты. Диагностика открывает живой журнал сервера, который помогает найти причину проблемы.",
        "Diagnostics": "Диагностика",
        "This demo shows the diagnostics log. It displays server events for troubleshooting and does not send commands to printers.": "Это демо показывает журнал диагностики. Он отображает события сервера для поиска проблем.",
        "Access, roles and audit": "Доступ, роли и аудит",
        "Access control lets different people use different parts of the farm interface.": "Контроль доступа позволяет разным людям пользоваться разными частями интерфейса фермы.",
        "Administrator has full control. Operator manages printing and projects. Assembler marks finished parts and sends parts to rework. Observer is view-only. Important actions are written to the audit log.": "Администратор имеет полный доступ. Оператор управляет печатью и проектами. Сборщик отмечает готовые детали и отправляет детали на перепечатку. Наблюдатель работает только в режиме просмотра. Важные действия записываются в журнал аудита.",
        "Modules": "Модули",
        "Optional modules appear here. Active modules can be opened from this menu; unavailable modules are marked as coming soon.": "Здесь появляются дополнительные модули. Активные модули можно открыть из этого меню; недоступные помечены как «скоро».",
        "About the program": "О программе",
        "About shows the program name, build version, interface mode, website and support links. This is useful when reporting a problem.": "Раздел «О программе» показывает название, версию сборки, режим интерфейса, сайт и ссылки поддержки. Это полезно при сообщении о проблеме.",
        "Your printers": "Ваши принтеры",
        "This column is the printer fleet. Each card shows status, progress and print time. Sorting and the view switch are at the top.": "Эта колонка — парк принтеров. Каждая карточка показывает статус, прогресс и время печати. Сортировка и переключатель вида находятся сверху.",
        "Sort printers": "Сортировка принтеров",
        "Sort printers by status or by name. This helps quickly find a free, busy or problem printer.": "Сортируйте принтеры по статусу или имени. Так проще быстро найти свободный, занятый или проблемный принтер.",
        "List and grid view": "Список и сетка",
        "Switch between a compact grid and a detailed list. The grid shows many printers at once; the list gives full controls for each printer.": "Переключайтесь между компактной сеткой и подробным списком. Сетка показывает много принтеров сразу, а список даёт полное управление каждым принтером.",
        "Add a printer": "Добавить принтер",
        "Add Printer opens the model catalog. Choose the printer model, enter its connection details and add it to the farm.": "«Добавить принтер» открывает каталог моделей. Выберите модель принтера, укажите параметры подключения и добавьте его в ферму.",
        "Compact printer card": "Компактная карточка принтера",
        "In grid view, each printer is shown as a compact card with status color, progress and completion percentage.": "В режиме сетки каждый принтер показан компактной карточкой с цветом статуса, прогрессом и процентом готовности.",
        "The same status colors are used across the interface: free, printing, paused and error each have their own shade. This makes the whole farm easier to read at a glance.": "Одни и те же цвета статусов используются во всём интерфейсе: свободен, печатает, пауза и ошибка имеют свои оттенки. Так состояние всей фермы проще понять с первого взгляда.",
        "Expanded printer card": "Раскрытая карточка принтера",
        "In list view, the printer card becomes a control panel with start, stop, pause, print, upload, temperatures, preview, progress, camera and materials.": "В режиме списка карточка принтера превращается в панель управления: старт, стоп, пауза, печать, загрузка, температуры, превью, прогресс, камера и материалы.",
        "The numbered controls are: 1 Start or resume, 2 Stop with confirmation, 3 Pause, and 4 PRINT for the file selected in the Select file box. Upld uploads a file from your computer to the printer. During active printing, the lower control row stays inactive.": "Пронумерованные элементы: 1 — старт или продолжение, 2 — стоп с подтверждением, 3 — пауза, 4 — ПЕЧАТЬ файла, выбранного в поле «Выбрать файл». «Загр.» загружает файл с компьютера на принтер. Во время активной печати нижний ряд управления остаётся неактивным.",
        "Print with AMS": "Печать с AMS",
        "Press Load, choose a print file in the built-in file manager and press Print. If the printer has AMS or a similar system, choose the filament slot before printing starts.": "Нажмите «Загрузить», выберите файл печати во встроенном файл-менеджере и нажмите «Печать». Если у принтера есть AMS или похожая система, перед запуском выберите слот с филаментом.",
        "Projects": "Проекты",
        "Projects are the production board. A project groups the parts, files and progress of one order or production batch.": "Проекты — это производственная доска. Проект объединяет детали, файлы и прогресс одного заказа или производственной партии.",
        "Use projects when you need to produce a set of parts and track completion, not just print one file. Project cards can be sorted by name or by the date they were added.": "Используйте проекты, когда нужно изготовить набор деталей и отслеживать готовность, а не просто напечатать один файл. Карточки проектов можно сортировать по имени или дате добавления.",
        "Create project": "Создание проекта",
        "New Project creates an empty project by name. After that, you can add parts and attach print files to them.": "«Новый проект» создаёт пустой проект по названию. После этого можно добавить детали и привязать к ним файлы печати.",
        "A project can also be started from files. In that case Farm Manager can create the project and add detected parts automatically.": "Проект также можно начать с файлов. В этом случае Farm Manager может создать проект и автоматически добавить найденные детали.",
        "Import project from files": "Импорт проекта из файлов",
        "A project can be created from files. This reduces manual entry and helps the operator prepare production faster.": "Проект можно создать из файлов. Это уменьшает ручной ввод и помогает оператору быстрее подготовить производство.",
        "When importing g-code, 3MF, STL or STEP files, Farm Manager can create a dated project and prepare parts and printable plates from the selected files.": "При импорте g-code, 3MF, STL или STEP Farm Manager может создать проект с датой и подготовить детали и печатные плиты из выбранных файлов.",
        "Counters in project": "Счётчики в проекте",
        "Each project part has counters: part name, On plate, Needed, Printed and Status.": "У каждой детали проекта есть счётчики: название детали, «На плате», «Нужно», «Напечат.» и статус.",
        "Part name identifies the item. On plate is how many copies of this exact part are produced by one print file. Needed is the required quantity. Printed is the accepted finished quantity. Status shows whether the part is ready, in progress or needs rework.": "Название детали определяет изделие. «На плате» — сколько копий именно этой детали делает один файл печати. «Нужно» — требуемое количество. «Напечат.» — принятое готовое количество. Статус показывает, готова деталь, в работе или требует перепечатки.",
        "Label Objects for counting": "Label Objects для подсчёта",
        "Automatic part counting is most reliable when the print file contains object labels from the slicer.": "Автоматический подсчёт деталей наиболее надёжен, когда файл печати содержит метки объектов из слайсера.",
        "Enable Label Objects / gcode_label_objects before exporting g-code or 3MF. These labels help Farm Manager detect which parts are on the plate and how many copies of each part are present.": "Включайте в слайсере Label Objects / gcode_label_objects перед экспортом g-code или 3MF. Эти метки помогают Farm Manager определить, какие детали находятся на плите и сколько копий каждой детали есть в файле.",
        "If counting is unavailable": "Если подсчёт недоступен",
        "If a file has no labels or the result is unclear, Farm Manager should not guess the quantity.": "Если в файле нет меток или результат неясен, Farm Manager не должен угадывать количество.",
        "The operator can check the first print and manually correct the On plate value. This is safer than silently adding the wrong number of parts to the project.": "Оператор может проверить первую печать и вручную исправить значение «На плате». Это безопаснее, чем незаметно добавить в проект неправильное количество деталей.",
        "Project card": "Карточка проекта",
        "A project card shows the project name, overall progress, status color, deadline and rework warnings.": "Карточка проекта показывает название, общий прогресс, цвет статуса, срок и предупреждения о перепечатке.",
        "Open the card to work inside the project: switch between By parts and By files, edit names and files, send parts to compatible free printers and track finished quantities.": "Откройте карточку, чтобы работать внутри проекта: переключаться между видами «По деталям» и «По файлам», редактировать названия и файлы, отправлять детали на совместимые свободные принтеры и отслеживать готовые количества.",
        "Archive": "Архив",
        "Archive and delete": "Архив и удаление",
        "Right-click a project card to open its menu: Archive tucks the project away without deleting (it can be restored later), Delete removes the project after a confirmation.": "Щёлкните по ячейке проекта правой кнопкой мыши — откроется меню: «Архив» убирает проект с экрана без удаления (его можно вернуть позже), «Удалить» удаляет проект после подтверждения.",
        "Tasks": "Задачи",
        "Tasks is for printing individual files without creating a project. It is useful for one-off prints, tests and urgent files.": "Задачи — для печати отдельных файлов без создания проекта. Это удобно для разовых печатей, тестов и срочных файлов.",
        "Drop or select a file": "Перетащите или выберите файл",
        "Drop a file into this area or click to select one. Ready print files can be sent to a compatible free printer; model files must be sliced first.": "Перетащите файл в эту область или нажмите, чтобы выбрать его. Готовые файлы печати можно отправлять на совместимый свободный принтер; файлы моделей сначала нужно нарезать в слайсере.",
        "Load into Tasks": "Загрузка в Tasks",
        "Open launches the built-in file manager. Select a print file and press Load to tasks.": "«Открыть» запускает встроенный файл-менеджер. Выберите файл печати и нажмите «Загрузить в задачи». ",
        "The same file manager opens when you click a file name in Tasks or in a project. It opens the folder and highlights the selected file, so the operator can quickly find it.": "Тот же файл-менеджер открывается при клике по имени файла в Tasks или в проекте. Он открывает папку и подсвечивает выбранный файл, чтобы оператор быстро его нашёл.",
        "Task row": "Строка Task",
        "A Task row shows the file name, Needed, Printed and current status.": "Строка задачи показывает имя файла, «Нужно», «Напечат.» и текущий статус.",
        "Expand the row to add a note, open a model in the slicer, print the file or open its folder. The counters follow the same idea as project parts.": "Раскройте строку, чтобы добавить заметку, открыть модель в слайсере, напечатать файл или открыть его папку. Счётчики работают по той же идее, что и у деталей проекта.",
        "Find the printer": "Найти принтер",
        "When a file or part is printing, its status becomes clickable. Click it to highlight the printer or printers running that job.": "Когда файл или деталь печатается, её статус становится кликабельным. Нажмите на него, чтобы подсветить принтер или принтеры, которые выполняют это задание.",
        "Suggestions and alerts": "Предложения и предупреждения",
        "This area shows what the program is doing with the printers right now: files being sent, printers queued to start, and jobs waiting for a suitable printer. Collapsed, it keeps a counter of active tasks.": "Эта область показывает, что программа делает с принтерами прямо сейчас: какие файлы отправляются, кто стоит в очереди на запуск и что ждёт подходящего принтера. В свёрнутом виде она держит счётчик активных дел.",
        "Alerts can include a failed print, incompatible g-code, a paused printer or missing filament. The goal is to show problems immediately instead of hiding them in the workflow.": "Предупреждения могут сообщать о сбое печати, несовместимом g-code, паузе принтера или отсутствии филамента. Цель — показать проблему сразу, а не спрятать её внутри процесса.",
        "You are all set": "Готово",
        "That is the main interface: printers, projects, Tasks, archive, settings and suggestions. You can replay this tour from Settings at any time.": "Это основной интерфейс: принтеры, проекты, Tasks, архив, настройки и предложения. Повторить обучение можно из настроек в любой момент.",
        "The interface also works on a phone or tablet in the same local network, so you can monitor the farm and start files away from the main workstation.": "Интерфейс также работает на телефоне или планшете в той же локальной сети, поэтому можно наблюдать за фермой и запускать файлы не только с основного компьютера."
});

    const lang = ref('en');
    try { const _l = localStorage.getItem('farm_lang'); if (_l === 'ru' || _l === 'en') lang.value = _l; } catch(e){}
    //  Alpha 2.903: переход во второй интерфейс. Ключ памяти общий с UI 3.0 (farm_ui_version),
    //  поэтому после перезапуска программа откроет тот интерфейс, в котором владелец был.
    //  Обратный путь и аварийный выход — адрес /?ui=2, он же стирает запомненный выбор.
    //  UI 3.0 (с 2.915): ТА ЖЕ страница и ТА ЖЕ раскладка, что в рабочем интерфейсе 2.0 —
    //  владелец вернул исходную точку. Разница только в ОФОРМЛЕНИИ: страница /ui3 подключает
    //  лист web/ui3/ui3.css, который переодевает интерфейс. Второй копии кода нет.
    const ui3Mode = !!(typeof window !== 'undefined' && window.__UI3_MODE__);

    //  2.971: подделки «Демо 30» убраны. Они рисовали тридцать плиток, похожих на принтеры,
    //  но принтерами не были: открыть, удалить или запустить на них печать было нельзя, а при
    //  любом сохранении списка они попадали в базу — там их и нашёл владелец. Их место занял
    //  ВИРТУАЛЬНЫЙ принтер (тип demo): он настоящий, живёт в базе, слушается кнопок и печатает.

    //  Один класс на странице — по нему подключается слой оформления UI 3.0.
    if (ui3Mode) { try { document.documentElement.classList.add('ui3-mode'); } catch (e) { /* нет DOM */ } }

    //  ── UI 3.0: выбранный принтер занимает правую область (2.916) ────────────────────────
    //  Нажатие на карточку в оформлении 3.0 НЕ раскрывает карточку: вместо проектов и задач
    //  справа показывается пульт этого принтера, а если у принтера есть камера — тут же её
    //  живой поток. Камера НЕ переписывается: показывается ТОТ ЖЕ блок камеры программы
    //  (со всей логикой WebRTC/fmp4/кадров), просто пристыкованный к отведённому месту —
    //  поэтому здесь не может быть второй, отстающей реализации.
    const ui3Printer = ref('');
    //  Камера считается «есть», если её показывает сама программа: правило принадлежит
    //  интерфейсу 2.0 (кнопка камеры на карточке), мы его читаем, а не выдумываем.
    //  12.10.2026: FlashForge — камера штатная у Adventurer 5M Pro; у 5M покупается отдельно, поэтому у него
    //  кнопка — только если принтер сам сообщил о камере (has_camera из ответа /detail).
    const _ffHasCamera = (p) => {
        if (/\b5m pro\b/.test(String(p.model || '').toLowerCase().replace(/[^a-z0-9]+/g, ' '))) return true;
        try { return !!((wsData.value || {})[p.id] || {}).has_camera; } catch (e) { return false; }
    };
    const ui3HasCamera = (p) => !!p && (p.type === 'bambu' || p.type === 'klipper' || p.type === 'creality' || (p.type === 'flashforge' && _ffHasCamera(p)));
    //  Стыковка камеры к месту на экране. Тонкость, найденная измерением: страница
    //  интерфейса живёт внутри масштабируемой обёртки, а окно камеры телепортируется НАРУЖУ.
    //  Поэтому координаты места (в точках экрана) нельзя подставлять окну напрямую — оно
    //  считает их в своей, немасштабированной системе. Мы не подгоняем числа на глаз: ставим
    //  пробное значение, ИЗМЕРЯЕМ, куда оно попало, и из одного измерения получаем масштаб и
    //  начало координат — дальше подставляем точно.
    const _ui3SetCam = (d, l, t, w, h) => {
        d.style.setProperty('--u3-cam-left', Math.round(l) + 'px');
        d.style.setProperty('--u3-cam-top', Math.round(t) + 'px');
        d.style.setProperty('--u3-cam-w', Math.round(w) + 'px');
        d.style.setProperty('--u3-cam-h', Math.round(h) + 'px');
    };
    //  29.09.2026 (R-111): пульт прокручивается сам, а окно камеры лежит поверх страницы и
    //  едет за местом под камеру. Видимая часть места — между низом закреплённой шапки пульта
    //  и низом пульта; всё, что за ними, у окна обрезается (clip-path в ui3.css). Отступы
    //  переводятся в единицы окна тем же масштабом k, что и координаты стыковки.
    const _ui3SetCamClip = (d, slot, r, k) => {
        let t = 0, b = 0;
        const pp = slot && slot.closest ? slot.closest('.ui3-pp') : null;
        if (pp) {
            const pr = pp.getBoundingClientRect();
            const head = pp.querySelector('.ui3-pp-head');
            const top = head ? head.getBoundingClientRect().bottom : pr.top;
            t = Math.max(0, top - r.top) / k;
            b = Math.max(0, r.bottom - pr.bottom) / k;
        }
        d.style.setProperty('--u3-cam-clip-t', (Math.round(t * 10) / 10) + 'px');
        d.style.setProperty('--u3-cam-clip-b', (Math.round(b * 10) / 10) + 'px');
    };
    //  2.963: место под камеру меняет высоту вместе с пультом (пришла телеметрия, раскрылось
    //  меню, появилась полоса ошибки) — наблюдатель размера подвигает камеру следом.
    let _ui3RoEl = null, _ui3Ro = null, _ui3RoRaf = 0;
    const _ui3Observe = (slot) => {
        if (_ui3RoEl === slot) return;
        if (_ui3Ro) { try { _ui3Ro.disconnect(); } catch (e) { /* уже отключён */ } _ui3Ro = null; }
        _ui3RoEl = slot;
        //  2.974: пересчёт места вызывается СЛЕДУЮЩИМ кадром, а не прямо из наблюдателя.
        //  Пересчёт меняет размеры, наблюдатель видит это и зовёт пересчёт снова — браузер
        //  сообщает о таком круге отдельной ошибкой в консоли. Через кадр круга нет.
        if (slot && typeof ResizeObserver !== 'undefined') {
            _ui3Ro = new ResizeObserver(() => {
                if (_ui3RoRaf) return;
                _ui3RoRaf = requestAnimationFrame(() => { _ui3RoRaf = 0; _ui3DockCam(); });
            });
            _ui3Ro.observe(slot);
        }
    };
    //  2.974: пока окно камеры не встало на своё место, показывать его нельзя. Оно
    //  открывается своим обычным размером (во весь экран) и лишь потом стыкуется — из-за этого
    //  при каждом переключении на долю секунды мелькало большое окно. Метка ui3-cam-arm гасит
    //  окно на это время; снимается она в тот же кадр, когда место посчитано.
    //  2.976: связь между местом на странице и окном камеры (масштаб и начало координат)
    //  ИЗМЕРЯЕТСЯ и ЗАПОМИНАЕТСЯ. Раньше каждый пересчёт сначала ставил окно по сырым
    //  координатам и лишь следующим кадром поправлял их под масштаб — и ровно на этот кадр окно
    //  показывалось крупнее и правее места. Владелец видел это как вспышку с наложением справа.
    //  Снято покадрово: кадры 4 и 6 после нажатия «Камера» — окно видно, но не на месте.
    //  Теперь окно ставится сразу по запомненной поправке, а показывается только после того,
    //  как измерение подтвердило: окно лежит ровно на месте.
    let _ui3CamFit = null;          // {k, ox, oy}: экран = k * css + o
    let _ui3ArmTimer = 0;
    const _ui3CamReady = () => {
        clearTimeout(_ui3ArmTimer); _ui3ArmTimer = 0;
        try { document.documentElement.classList.remove('ui3-cam-arm'); } catch (e) {}
    };
    const _ui3CamArm = () => {
        try { document.documentElement.classList.add('ui3-cam-arm'); } catch (e) {}
        //  Страховка: что бы ни случилось, дольше полутора секунд окно невидимым не держим.
        clearTimeout(_ui3ArmTimer);
        _ui3ArmTimer = setTimeout(_ui3CamReady, 1500);
    };
    const _ui3DockCam = () => {
        if (!ui3Mode) return;
        if (ui3CamFull.value) { _ui3CamReady(); return; }   // 2.963: камера отпущена во весь экран
        const d = document.documentElement;
        const slot = document.querySelector('.ui3-camslot');
        _ui3Observe(slot);
        const r = slot ? slot.getBoundingClientRect() : null;
        if (!r || r.width < 40 || r.height < 40) { d.classList.remove('ui3-cam-dock'); return; }
        //  Ставим сразу с учётом запомненной поправки — без «сырого» кадра.
        const f = _ui3CamFit || { k: 1, ox: 0, oy: 0 };
        const L = (r.left - f.ox) / f.k, T = (r.top - f.oy) / f.k, W = r.width / f.k, H = r.height / f.k;
        _ui3SetCam(d, L, T, W, H);
        _ui3SetCamClip(d, slot, r, f.k);
        d.classList.add('ui3-cam-dock');
        requestAnimationFrame(() => {
            const ov = document.querySelector('#fm-overlay-root > .fm-cam-ov');
            if (!ov) return;                                   // окна ещё нет: остаётся погашенным до появления
            const b = ov.getBoundingClientRect();
            if (!b.width || !W) return;
            //  Сошлось — окно лежит на месте, показываем.
            if (Math.abs(b.left - r.left) < 1.5 && Math.abs(b.top - r.top) < 1.5 && Math.abs(b.width - r.width) < 1.5) {
                _ui3CamReady();
                return;
            }
            //  Не сошлось: из того, что поставили (L, T, W), и того, где окно оказалось (b),
            //  выводим настоящий масштаб и начало координат, запоминаем и ставим заново.
            const k = b.width / W;
            if (!(k > 0.2 && k < 5)) return;
            _ui3CamFit = { k: k, ox: b.left - L * k, oy: b.top - T * k };
            _ui3SetCam(d, (r.left - _ui3CamFit.ox) / k, (r.top - _ui3CamFit.oy) / k, r.width / k, r.height / k);
            _ui3SetCamClip(d, slot, r, k);
            requestAnimationFrame(_ui3CamReady);              // показываем кадром, где поправка уже применена
        });
    };
    //  2.976: если сверху открыто большое окно (настройки, диагностика, файлы принтеров,
    //  отчёты, проводник), нажатие на принтер закрывает его: иначе пульт остаётся под ним,
    //  а плавающее окно камеры всплывает поверх чужого окна — владелец видел это как «открылась
    //  камера вместо пульта». Возвращает true, если что-то закрыли.
    const _ui3CloseBigWindows = () => {
        let closed = false;
        try { if (showPrinterFiles.value) { closePrinterFiles(); closed = true; } } catch (e) {}
        try { if (showSettings.value) { closeSettings(); closed = true; } } catch (e) {}
        try { if (showDiag.value) { closeDiagnostics(); closed = true; } } catch (e) {}
        try { if (showReports.value) { closeReports(); closed = true; } } catch (e) {}
        try { if (exOpen.value) { exOpen.value = false; closed = true; } } catch (e) {}
        return closed;
    };
    const ui3SelectPrinter = (p, ev) => {
        if (!p) return;
        const hadBig = _ui3CloseBigWindows();
        if (ui3Printer.value === p.id && hadBig) {
            //  Пульт этого принтера и так открыт — он просто был под окном. Показываем его
            //  снова вместе с камерой, а не закрываем.
            if (ui3PpView.value === 'cam' && ui3HasCamera(p)) nextTick(() => setTimeout(ui3PpCamOn, 60));
            return;
        }
        if (ui3Printer.value === p.id) {          // повторное нажатие — закрыть
            ui3Printer.value = '';
            _ui3PpReset();
            activeModalPrinterId.value = null;
            _ui3CamArm();                          // 2.975: закрытие пульта — тоже без вспышки
            closeCamera();
            document.documentElement.classList.remove('ui3-cam-dock');
            return;
        }
        //  2.926: отклик — в ПЕРВОМ ЖЕ кадре. Раньше клик тянул за собой всю подготовку
        //  (поля пульта, запрос файлов, запуск камеры) до первой отрисовки, и на занятой
        //  машине (старт программы, слабый компьютер фермы) первое нажатие выглядело как
        //  «ничего не происходит». Теперь мгновенно ставится выделение и каркас пульта,
        //  а тяжёлое выполняется после отрисовки кадра.
        ui3Printer.value = p.id;
        activeModalPrinterId.value = p.id;         // выделение карточки — сразу
        _ui3PpReset();
        if (ui3HasCamera(p)) { _ui3CamArm(); ui3CamPending.value = true; }   // 2.974/2.977: ни вспышки окна, ни кнопки
        requestAnimationFrame(() => requestAnimationFrame(() => {
            if (ui3Printer.value !== p.id) return; // владелец уже переключился дальше
            //  Готовим поля так же, как обычное раскрытие карточки (температуры, файлы),
            //  но саму карточку не раскрываем: пульт живёт справа.
            openModal(p.id, ev);
            showModal.value = false;
            if (ui3HasCamera(p)) { _ui3CamArm(); openCamera(p); nextTick(() => setTimeout(_ui3DockCam, 60)); }
            else { closeCamera(); document.documentElement.classList.remove('ui3-cam-dock'); }
            ui3CamPending.value = false;
        }));
    };
    if (ui3Mode && typeof window !== 'undefined') {
        window.addEventListener('resize', _ui3DockCam);
        window.addEventListener('scroll', _ui3DockCam, true);
    }

    //  Правая половина в оформлении 3.0: либо проекты, либо задачи — во всю ширину (2.918).
    //  Владельцу нужны два состояния, а не две колонки: так каждому разделу достаётся весь экран.
    const ui3RightTab = ref('projects');
    try {
        const _t3 = localStorage.getItem('ui3_right_tab');
        if (_t3 === 'tasks' || _t3 === 'queue' || _t3 === 'filament') ui3RightTab.value = _t3;
    } catch (e) { /* нет хранилища */ }
    const _ui3ApplyRight = () => {
        if (!ui3Mode) return;
        const cl = document.documentElement.classList;
        cl.toggle('ui3-right-projects', ui3RightTab.value === 'projects');
        cl.toggle('ui3-right-tasks', ui3RightTab.value === 'tasks');
        cl.toggle('ui3-right-queue', ui3RightTab.value === 'queue');
        cl.toggle('ui3-right-filament', ui3RightTab.value === 'filament');   // 2.965
        if (ui3RightTab.value === 'queue') loadQueueWait();
    };
    const setUi3RightTab = (k) => {
        if (k !== 'projects' && k !== 'tasks' && k !== 'queue' && k !== 'filament') return;
        ui3RightTab.value = k;
        try { localStorage.setItem('ui3_right_tab', k); } catch (e) { /* нет хранилища */ }
        _ui3ApplyRight();
    };

    //  ── Очередь ожидания (2.920, заказ владельца) ───────────────────────────────────────
    //  Что печатать — здесь; НА ЧЁМ печатать — решает сервер (подбор по материалу, свободе и
    //  разрешению принтера). Запуск на первом этапе делает владелец нажатием: так он видит,
    //  какой принтер выбран, прежде чем машина начнёт печатать сама.
    const queueWait = ref([]);
    const queueAllowed = ref([]);
    const queueBusy = ref('');
    //  16.09.2026: принтеры, которые ЖДУТ подтверждения «Стол очищен» (закончили печать).
    //  Автозапуск на них не идёт, пока человек не нажмёт кнопку.
    const queuePlateWait = ref([]);
    const queueAutoOn = ref(false);          // выключатель автозапуска на всю ферму
    const queueAutoPids = ref([]);           // кому из отмеченных разрешён автозапуск
    const loadQueueWait = async () => {
        try {
            const j = await (await fetch('/api/queue-wait')).json();
            if (j && j.ok) {
                queueWait.value = j.items || [];
                queueAllowed.value = j.allowed || [];
                queuePlateWait.value = j.plate_wait || [];
            }
        } catch (e) { /* сеть моргнула — прежний список остаётся на экране */ }
        //  16.09.2026: выключатель автозапуска и список принтеров — настройка ФЕРМЫ, её могут
        //  менять с другого компьютера. Раньше они читались ОДИН раз при загрузке страницы,
        //  и вторая вкладка молча затирала чужой выбор своим устаревшим списком.
        try {
            const s = ((await (await fetch('/api/farm-settings')).json()) || {}).settings || {};
            if ('queue_auto_start' in s) queueAutoOn.value = s.queue_auto_start === '1';
            queueAutoPids.value = s.auto_start_printers || [];
            _updateCheckFromServer(s.update_check);   // R-131: выключатель с другого компьютера
        } catch (e) { /* прежние значения остаются на экране */ }
    };
    const queueAwaitsClear = (pid) => !!pid && queuePlateWait.value.some((x) => x.id === pid);
    //  16.09.2026: кнопка «Стол очищен» — ОДНА на принтер, а не на каждой его строке. У одного
    //  принтера в очереди бывает несколько строк, и осмотр показал две кнопки подряд: одно и то же
    //  действие, предложенное дважды, да ещё и на строке, которая уже запускается. Показываем её
    //  на ПЕРВОЙ ожидающей строке этого принтера.
    const queueClearHere = (row) => {
        if (!row || !row.match_printer_id) return false;
        if (row.state === 'launching' || row.state === 'starting') return false;
        if (!queueAwaitsClear(row.match_printer_id)) return false;
        const first = queueWait.value.find((r) => r.match_printer_id === row.match_printer_id
            && r.state !== 'launching' && r.state !== 'starting');
        return !!first && first.id === row.id;
    };
    //  Подтверждение «Стол очищен» вне проектного запуска. Спрашиваем обязательно: это слово
    //  человека о физическом мире, и программа проверить его не может.
    //  Причины отказа подтверждения — словами. Сырой код владельцу не показывается.
    const queueClearError = (r) => {
        const ru = lang.value === 'ru';
        return ({
            printer_busy: ru ? 'принтер сейчас печатает' : 'the printer is printing right now',
            telemetry_stale: ru ? 'нет свежих данных от принтера' : 'no fresh data from the printer',
            printer_unsafe: ru ? 'принтер не в покое — дождитесь, пока он освободится'
                               : 'the printer is not idle — wait until it is free',
            printer_not_finished: ru ? 'принтер не в покое и не закончил печать'
                                     : 'the printer is neither idle nor finished',
            clearance_exists: ru ? 'подтверждение уже дано' : 'the confirmation is already given',
            printer_not_found: ru ? 'принтер не найден' : 'printer not found',
            confirmation_required: ru ? 'подтверждение не принято' : 'the confirmation was not accepted',
        })[String(r || '')] || (ru ? 'принтер не принял подтверждение' : 'the printer did not accept the confirmation');
    };
    const queuePlateClear = async (pid) => {
        if (!pid || queueBusy.value) return;      // двойное нажатие даёт лишний отказ 409
        const ru = lang.value === 'ru';
        const nm = (queuePlateWait.value.find((x) => x.id === pid) || {}).name || pid;
        if (!await askConfirm({ title: _L('Стол очищен?', 'Plate cleared?'),
                                text: (ru ? 'Подтвердите, что с принтера ' : 'Confirm the parts are removed from ')
                                      + nm + (ru ? ' сняты все детали. После этого очередь сможет запустить на нём следующую печать.'
                                                 : '. After that the queue may start the next print on it.'),
                                okText: _L('Стол очищен', 'Plate cleared') })) return;
        queueBusy.value = 'clr:' + pid;
        try {
            const rsp = await fetch('/api/printer/' + encodeURIComponent(pid) + '/plate-clear', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ confirmed: true }) });
            const j = await rsp.json().catch(() => ({}));
            if (j && j.status === 'ok') pushToast(ru ? 'Принято: стол свободен' : 'Accepted: the plate is clear', 'success');
            else pushToast((ru ? 'Не принято: ' : 'Not accepted: ') + queueClearError(j && j.reason), 'info');
        } catch (e) {
            pushToast(ru ? 'Не удалось отправить подтверждение' : 'Could not send the confirmation', 'info');
        }
        queueBusy.value = '';
        loadQueueWait();
    };
    //  Выключатель автозапуска и список принтеров — настройка ФЕРМЫ: одна на все компьютеры.
    //  Шлём ТОЛЬКО свои ключи: сервер пишет по ключам, соседние настройки не затрагиваются.
    //  Ответ сервера ПРОВЕРЯЕМ: молчаливый отказ на выключателе печати — это экран, который
    //  говорит «автозапуск включён», когда он выключен (или наоборот).
    const _queueAutoPush = async (body) => {
        try {
            const j = await (await fetch('/api/farm-settings', { method: 'POST',
                headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
            if (j && j.ok) return true;
            pushToast(lang.value === 'ru' ? 'Настройка не сохранена — попробуйте ещё раз'
                                          : 'The setting was not saved — try again', 'info');
        } catch (e) {
            pushToast(lang.value === 'ru' ? 'Нет связи с программой — настройка не сохранена'
                                          : 'No connection — the setting was not saved', 'info');
        }
        return false;
    };
    const queueAutoToggle = async () => {
        const was = queueAutoOn.value;
        queueAutoOn.value = !was;
        if (!await _queueAutoPush({ queue_auto_start: queueAutoOn.value ? '1' : '0' })) {
            queueAutoOn.value = was;          // не записалось — экран не должен врать
        }
        loadQueueWait();
    };
    const queueAutoHas = (pid) => queueAutoPids.value.indexOf(pid) >= 0;
    const queueAutoSet = async (pid, on) => {
        const was = queueAutoPids.value.slice();
        const cur = queueAutoPids.value.filter((x) => x !== pid);
        if (on) cur.push(pid);
        queueAutoPids.value = cur;
        if (!await _queueAutoPush({ auto_start_printers: cur })) queueAutoPids.value = was;
    };
    //  15.09.2026: причины называются точно. «Программа не видит материал принтера» больше не
    //  выдаётся за «нужного материала нет», и ни один код не показывается владельцу сырым.
    const queueReasonText = (r) => {
        const ru = lang.value === 'ru';
        const t = ({
            ready: ru ? 'принтер найден' : 'printer found',
            material_unknown: ru ? 'материал файла не указан — выберите принтер сами'
                                 : 'file material is not declared — choose a printer yourself',
            not_allowed: ru ? 'ни одному принтеру не разрешён запуск из очереди'
                            : 'no printer is allowed to start from the queue',
            busy: ru ? 'подходящие принтеры заняты или не на связи' : 'suitable printers are busy or offline',
            no_material: ru ? 'у свободных принтеров нет нужного материала'
                            : 'free printers do not have the required material',
            printer_material_unknown: ru ? 'программа не видит материал на свободном принтере'
                                         : 'the program cannot see the material on a free printer',
            incompatible: ru ? 'свободные принтеры не подходят к файлу' : 'free printers do not fit the file',
            not_printable: ru ? 'файл не нарезан — в очередь ставятся только нарезанные файлы'
                              : 'the file is not sliced — only sliced files can be queued',
            file_missing: ru ? 'файл не найден на компьютере фермы' : 'the file is not found on the farm computer',
            file_unreadable: ru ? 'файл есть, но не читается — занят другой программой или не скачан с Диска'
                                : 'the file exists but cannot be read — it is open elsewhere or not downloaded',
            printer_changed: ru ? 'подобранный принтер изменился — проверьте строку и запустите снова'
                                : 'the matched printer has changed — check the row and start again',
            enqueue_rejected: ru ? 'очередь запусков не приняла файл' : 'the launch queue did not accept the file',
            already_started: ru ? 'эту строку уже запустили — обновите список'
                                : 'this row has already been started — refresh the list',
            //  16.10.2026 (R-115): двухсопельный принтер, а сопла в файле не видно — только ручной запуск.
            dual_nozzle_unverified: ru ? 'двухсопельный принтер: в файле не видно, каким соплом печатать — запустите вручную'
                                       : 'dual-nozzle printer: the file does not say which nozzle to use — start it manually',
        })[r];
        if (t) return t;
        return r ? (ru ? 'запуск сейчас невозможен' : 'cannot start right now') : '';
    };
    //  Почему КАЖДЫЙ разрешённый принтер подходит или нет — владелец видит, в чём дело: в катушке,
    //  в файле или в том, что программа не видит материал.
    const queueVerdictText = (c) => {
        const ru = lang.value === 'ru';
        const v = (c && c.verdict) || '';
        if (v === 'ready') return c.finished
            ? (ru ? 'подходит, но на столе может быть прошлая деталь — проверьте стол' : 'fits, but the previous part may still be on the bed — check the bed')
            : (ru ? 'подходит' : 'fits');
        if (v === 'working_stage') {
            //  16.10.2026 (R-138): причина словами сервера — смена филамента в AMS, стадия по-русски.
            //  Без неё — прежний текст, а номер стадии только настоящий (не пусто и не покой -1/255).
            const why = ru ? c.busy_ru : c.busy_en;
            if (why) return why;
            return (ru ? 'выполняет подготовку' : 'is running a preparation step')
                + ((c.stage != null && c.stage !== -1 && c.stage !== 255) ? (ru ? ' (стадия ' : ' (stage ') + c.stage + ')' : '');
        }
        if (v === 'not_free') return (ru ? 'не свободен' : 'not free')
            + (c.status === 'FAILED' ? (ru ? ' (сбой печати)' : ' (print failed)') : '');
        //  16.10.2026 (R-137): у H2D внешняя катушка выбирается по соплу, под которое нарезан файл.
        if (v === 'ext_wrong_side') return c.ext_side === 'left'
            ? (ru ? 'материал на левой внешней катушке, а файл нарезан под правое сопло'
                  : 'the material is on the left external spool, but the file is sliced for the right nozzle')
            : (ru ? 'материал на правой внешней катушке, а файл нарезан под левое сопло'
                  : 'the material is on the right external spool, but the file is sliced for the left nozzle');
        return ({
            in_queue: ru ? 'уже стоит в очереди запусков' : 'already in the launch queue',
            reserved: ru ? 'занят отправкой' : 'busy with a send',
            printing: ru ? 'печатает' : 'printing',
            offline: ru ? 'не на связи' : 'offline',
            incompatible: ru ? 'файл нарезан под другой принтер' : 'the file is sliced for another printer',
            material_mismatch: ru ? 'нет нужного материала' : 'no required material',
            printer_empty: ru ? 'на принтере не задан материал' : 'no material is set on the printer',
            material_unknown_on_printer: ru ? 'материал этого принтера программе не виден'
                                            : 'the printer does not report its material',
            //  16.10.2026 (R-141): FlashForge без станции материалов — подходит только по слову человека.
            owner_check: ru ? 'подходит, если на принтере стоит нужный материал (FlashForge его не сообщает) — только ручной запуск'
                            : 'fits if the right material is loaded (FlashForge does not report it) — manual start only',
            //  16.10.2026 (R-141, разбор пакета): FlashForge, которому файл из очереди не подходит.
            ff_station: ru ? 'у принтера станция материалов — запуск из очереди с неё пока не поддерживается'
                           : 'the printer has a material station — the queue cannot start from it yet',
            single_nozzle_multi: ru ? 'у принтера одно сопло без станции материалов, а в файле несколько филаментов'
                                    : 'the printer has one nozzle and no material station, but the file uses several filaments',
            ext_multi: ru ? 'материал на внешней катушке, а в файле несколько филаментов'
                          : 'the material is on the external spool, but the file uses several filaments',
            left_spool: ru ? 'материал только на левой внешней катушке — с неё очередь не запускает'
                           : 'the material is only on the left external spool — the queue cannot start from it',
            ext_side_unknown: ru ? 'в файле не видно, каким соплом печатать'
                                 : 'the file does not say which nozzle to print with',
            //  16.10.2026 (R-115): подходит по AMS, но сопло не сверить — автозапуск его не берёт.
            dual_nozzle_unverified: ru ? 'подходит, но двухсопельный: в файле не видно сопла — только ручной запуск'
                                       : 'fits, but dual-nozzle: the file does not say which nozzle — manual start only',
            ams_unmapped: ru ? 'материал есть в AMS, но не в тех слотах, куда разложится файл'
                             : 'the material is in the AMS, but not in the slots the file maps to',
            slot_mismatch: ru ? 'в ячейке CFS, указанной в файле, другой материал'
                              : 'the CFS slot named in the file holds another material',
            slot_unknown: ru ? 'в файле не видно, из какой ячейки печатать'
                             : 'the file does not say which slot to print from',
        })[v] || (ru ? 'не подходит' : 'does not fit');
    };
    const queueHaveText = (c) => {
        const ru = lang.value === 'ru';
        const parts = [];
        ((c && c.have) || []).forEach(h => {
            const where = h.where === 'ext' ? (c.dual ? (ru ? 'правая внешняя' : 'right external') : (ru ? 'внешняя' : 'external'))
                : h.where === 'ext_left' ? (ru ? 'левая внешняя' : 'left external')
                : h.where === 'cfs' ? (h.label || 'CFS') : 'AMS';
            const s = where + ' ' + h.material;
            if (!parts.includes(s)) parts.push(s);
        });
        return parts.slice(0, 4).join(', ') + (parts.length > 4 ? '…' : '');
    };
    const queueFileWhyText = (w) => {
        const ru = lang.value === 'ru';
        return ({
            no_tool_line: ru ? 'в g-code нет строки выбора ячейки (T<n>) — принтер возьмёт заправленную сейчас, материал в ней не проверить'
                             : 'the g-code has no slot selection line (T<n>) — the printer will use whatever is loaded now',
            plate_not_described: ru ? 'в файле нет описания нарезанной плиты' : 'the sliced plate is not described in the file',
            plate_without_filaments: ru ? 'в описании плиты не указаны филаменты' : 'the plate description lists no filaments',
            material_not_named: ru ? 'у филамента в файле не указан материал' : 'a filament in the file has no material',
            tool_conflict: ru ? 'расход филамента в файле не совпадает со сменами ячеек'
                              : 'filament usage in the file does not match its slot changes',
            gcode_not_declared: ru ? 'в g-code не указано, каким материалом и из какой ячейки печатать'
                                   : 'the g-code does not state the material and slot',
            unreadable: ru ? 'файл не читается' : 'the file cannot be read',
        })[w] || '';
    };
    const queueMatSource = (row) => {
        const ru = lang.value === 'ru';
        return ({ plate: ru ? 'материал по нарезанной плите' : 'material from the sliced plate',
                  project: ru ? 'материал по всему проекту' : 'material from the whole project',
                  gcode: ru ? 'материал по g-code' : 'material from the g-code' })[(row && row.material_source) || ''] || '';
    };
    //  16.09.2026: состояние самой строки. «Запускается» — исход ещё не известен; «требует
    //  внимания» — прошлый запуск оборвался неясно, и строку нельзя ни закрыть, ни запустить молча.
    const queueStateText = (row) => {
        const ru = lang.value === 'ru';
        const s = (row && row.state) || '';
        if (s === 'launching' || s === 'starting') return ru ? 'запускается…' : 'starting…';
        if (s === 'attention') return ru ? 'требует внимания' : 'needs attention';
        return '';
    };
    //  Строки пояснения под строкой очереди: у найденного — откуда пойдёт печать и не нужно ли
    //  проверить стол; у ненайденного — разрешённые принтеры по одному с причиной.
    //  16.09.2026: пометки, которые пишет АВТОЗАПУСК, хранятся КОДОМ: строку очереди читают
    //  и русский, и английский интерфейс, а сырые коды владельцу не показываются (правило
    //  этого файла). Пометки ручного пути остаются как есть.
    //  16.10.2026 (R-117): почему запуск не состоялся — словами. Коды приходят от очереди запусков,
    //  склада и подбора; сырой код владельцу не показывается никогда. Фраза от принтера или транспорта
    //  (в ней есть пробелы и заглавные) уже написана словами — она показывается как есть.
    const _lcFirst = (t) => (t ? t.charAt(0).toLowerCase() + t.slice(1) : t);
    const queueLaunchWhyText = (code) => {
        const ru = lang.value === 'ru';
        const c = String(code || '').trim();
        if (!c) return ru ? 'причина не названа' : 'no reason given';
        const t = ({
            low_filament: ru ? 'по складу не хватает материала' : 'the stock says there is not enough filament',
            incompatible: ru ? 'файл нарезан под другой принтер' : 'the file is sliced for another printer',
            printer_send_busy: ru ? 'принтер уже принимает другой файл' : 'the printer is already receiving another file',
            'no printer': ru ? 'принтер не найден' : 'printer not found',
            'printer not found': ru ? 'принтер не найден' : 'printer not found',
            'file not found': ru ? 'файл не найден' : 'file not found',
            'file missing on disk': ru ? 'файл не найден на компьютере фермы' : 'the file is not found on the farm computer',
            'read failed': ru ? 'файл не читается' : 'the file cannot be read',
            'queue launch not started': ru ? 'запуск снят в очереди запусков' : 'the launch was removed from the launch queue',
            //  16.10.2026 (R-117, разбор пакета): менеджер отправок так отвечает, когда это задание уже
            //  исполняет другой поток, — ушла ли команда, неизвестно.
            'already running': ru ? 'этот запуск уже выполнялся' : 'this launch was already in progress',
            start_not_confirmed: ru ? 'принтер принял файл, но печать не началась — посмотрите экран принтера'
                                    : 'the printer accepted the file but did not start printing — check the printer screen',
        })[c];
        if (t) return t;
        if (c.indexOf('auto_needs_human:') === 0) return queueAutoWhyText(c.slice('auto_needs_human:'.length));
        const rd = (ru ? READINESS_REASON_RU : READINESS_REASON_EN)[c];
        if (rd) return _lcFirst(rd);
        if (/^[a-z_]+$/.test(c)) return queueReasonText(c);     // код подбора — или «запуск сейчас невозможен»
        //  Фраза принтера — через общий словарь интерфейса: английские ответы отправки (например, «нет
        //  связи для загрузки файла») в нём переведены, как у прямого запуска.
        return tr(c);
    };
    //  16.10.2026 (R-118): почему АВТОЗАПУСК оставил строку человеку (пометка auto_needs_human:<код>).
    const queueAutoWhyText = (code) => {
        const ru = lang.value === 'ru';
        return ({
            external: ru ? 'печать пошла бы с внешней катушки — её материал выбран на экране принтера, датчик его не подтверждает'
                         : 'it would print from the external spool — its material is a printer setting, no sensor confirms it',
            owner_check: ru ? 'FlashForge не сообщает, какой материал заправлен' : 'FlashForge does not report the loaded material',
            dual_nozzle: ru ? 'двухсопельный принтер: в файле не видно, каким соплом печатать'
                            : 'dual-nozzle printer: the file does not say which nozzle to use',
            no_sensor: ru ? 'датчик AMS не подтвердил катушку в слоте' : 'the AMS sensor has not confirmed the spool in the slot',
            variant: ru ? 'в слоте другой вариант материала' : 'the slot holds another variant of the material',
            color_mismatch: ru ? 'цвет катушки отличается от цвета в файле' : 'the spool colour differs from the file',
            color_close: ru ? 'цвет катушки близкий, но не точно тот, что в файле' : 'the spool colour is close but not exactly the file colour',
            color_unknown: ru ? 'цвет катушки или файла не известен' : 'the spool or file colour is unknown',
            feed_unproven: ru ? 'не доказано, откуда пойдёт печать' : 'it is not proven where the filament will come from',
            stock: ru ? 'склад не пропускает запуск' : 'the stock check does not allow the launch',
        })[String(code || '')] || (ru ? 'нужно ваше решение' : 'your decision is needed');
    };
    const queueNoteText = (note) => {
        const ru = lang.value === 'ru';
        const s = String(note || '');
        if (s === 'auto_clearance_used') return ru ? 'подтверждение «стол очищен» уже использовано'
                                                   : 'the plate-clear confirmation was already used';
        if (s === 'auto_exception') return ru ? 'запуск прервался сбоем — строка возвращена в очередь'
                                              : 'the launch failed unexpectedly — the row is back in the queue';
        if (s.indexOf('auto_failed:') === 0) {
            const why = queueLaunchWhyText(s.slice('auto_failed:'.length));
            return (ru ? 'автозапуск не удался три раза подряд: ' : 'auto-start failed three times in a row: ') + why;
        }
        //  16.10.2026 (R-008, R-118): автозапуск строку не взял — почему, и что сделать.
        if (s === 'auto_low_filament') return ru ? 'автозапуск ждёт: по складу не хватает материала — поставьте катушку или запустите вручную'
                                                 : 'auto-start is waiting: the stock says there is not enough filament — load a spool or start manually';
        if (s.indexOf('auto_needs_human:') === 0) return (ru ? 'автозапуск ждёт вас: ' : 'auto-start needs you: ')
            + queueAutoWhyText(s.slice('auto_needs_human:'.length)) + (ru ? ' — запустите вручную' : ' — start it manually');
        //  16.10.2026 (R-117): запуск не состоялся / принтер не начал печать — причина словами.
        if (s === 'start_not_confirmed') return queueLaunchWhyText(s);
        if (s.indexOf('not_started:') === 0) return (ru ? 'запуск не состоялся: ' : 'the launch did not happen: ')
            + queueLaunchWhyText(s.slice('not_started:'.length));
        if (s.indexOf('запуск не состоялся: ') === 0) return (ru ? 'запуск не состоялся: ' : 'the launch did not happen: ')
            + queueLaunchWhyText(s.slice('запуск не состоялся: '.length));    // строки, записанные до 16.10.2026
        //  16.10.2026 (R-117, разбор пакета): исход неясен — «требует внимания» с причиной словами.
        if (s.indexOf('interrupted:') === 0) return (ru ? 'запуск прерван: ' : 'the launch was interrupted: ')
            + queueLaunchWhyText(s.slice('interrupted:'.length)) + (ru ? ' — проверьте принтер' : ' — check the printer');
        return s;
    };
    //  16.10.2026 (R-137): у H2D внешняя катушка — той стороны, под чьё сопло нарезан файл.
    const queueExtSide = (row, ru) => (row && row.match_ext === 254) ? (ru ? 'левой ' : 'left ')
        : (row && row.match_ext === 255) ? (ru ? 'правой ' : 'right ') : '';
    //  16.10.2026 (R-115): двухсопельный принтер, а в файле не видно, каким соплом печатает плита.
    //  16.10.2026 (R-141): у FlashForge (match_feed «unverified») — свой текст: материал проверяет человек.
    const queueUnverifiedText = (row) => {
        const ru = lang.value === 'ru';
        if (row && row.match_feed === 'unverified') return ru
            ? 'FlashForge не сообщает по сети, какой материал заправлен, — проверьте на принтере, что стоит ' + (row.material || 'нужный материал') + '; автозапуск такую строку не запускает'
            : 'FlashForge does not report the loaded material over the network — check on the printer that ' + (row.material || 'the right material') + ' is loaded; auto-start skips this row';
        return ru
            ? 'двухсопельный принтер: в файле не видно, каким соплом печатать, — проверьте, что слоты AMS подают в нужное сопло; автозапуск такую строку не запускает'
            : 'dual-nozzle printer: the file does not say which nozzle to use — check that the AMS slots feed the right nozzle; auto-start skips this row';
    };
    //  16.10.2026 (R-016): цвет словами — приблизительно, по оттенку; точный код рядом в скобках.
    const queueColorName = (hex) => {
        const h = String(hex || '').replace('#', '');
        if (!/^[0-9a-fA-F]{6}$/.test(h)) return '';
        const ru = lang.value === 'ru';
        const r = parseInt(h.slice(0, 2), 16) / 255, g = parseInt(h.slice(2, 4), 16) / 255, b = parseInt(h.slice(4, 6), 16) / 255;
        const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
        const sat = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
        if (l < 0.12) return ru ? 'чёрный' : 'black';
        if (sat < 0.15) return l > 0.85 ? (ru ? 'белый' : 'white') : (ru ? 'серый' : 'grey');
        let hue = mx === r ? ((g - b) / d) % 6 : (mx === g ? (b - r) / d + 2 : (r - g) / d + 4);
        hue = (hue * 60 + 360) % 360;
        const names = [[15, 'красный', 'red'], [45, 'оранжевый', 'orange'], [70, 'жёлтый', 'yellow'], [165, 'зелёный', 'green'],
                       [200, 'голубой', 'light blue'], [255, 'синий', 'blue'], [290, 'фиолетовый', 'purple'],
                       [345, 'розовый', 'pink'], [361, 'красный', 'red']];
        const n = names.find((x) => hue < x[0]);
        return n ? (ru ? n[1] : n[2]) : '';
    };
    const queueColorText = (hex) => {
        if (!hex) return lang.value === 'ru' ? 'не указан' : 'not given';
        const n = queueColorName(hex);
        return n ? n + ' (' + hex + ')' : hex;
    };
    //  Куда пойдёт филамент: слот AMS / ячейка CFS — подписью принтера, внешняя катушка — словами.
    const queueSlotWhere = (sl, row) => {
        const ru = lang.value === 'ru';
        if (sl.where === 'ams' || sl.where === 'cfs') return sl.label || (sl.where === 'ams' ? 'AMS' : 'CFS');
        if (row && row.match_feed === 'unverified') return ru ? 'катушка на принтере' : 'the spool on the printer';
        if (sl.where === 'ext_left' || (row && row.match_ext === 254)) return ru ? 'левая внешняя катушка' : 'left external spool';
        if (row && row.match_ext === 255) return ru ? 'правая внешняя катушка' : 'right external spool';
        return ru ? 'внешняя катушка' : 'external spool';
    };
    //  Строка подачи для строки очереди: «PLA — AMS 1·2, PETG — AMS 1·3» (только слоты и ячейки:
    //  про внешнюю катушку строка очереди говорит отдельной фразой).
    const queueFeedLine = (row) => {
        const ru = lang.value === 'ru';
        const sl = ((row && row.match_slots) || []).filter((x) => x && (x.where === 'ams' || x.where === 'cfs'));
        if (!sl.length) return '';
        const parts = sl.slice(0, 4).map((x) => (x.material || '?') + ' — ' + queueSlotWhere(x, row));
        return (ru ? 'подача: ' : 'feed: ') + parts.join(', ') + (sl.length > 4 ? '…' : '');
    };
    //  «Цвет отличается» и «другой вариант материала» — по каждому филаменту, где это так.
    const queueSlotWarnings = (row) => {
        const ru = lang.value === 'ru';
        const out = [];
        ((row && row.match_slots) || []).forEach((x) => {
            if (!x) return;
            const what = (x.material || '?') + ' (' + queueSlotWhere(x, row) + ')';
            if (x.rel === 'mismatch' || x.rel === 'close') {
                out.push((x.rel === 'mismatch' ? (ru ? 'цвет отличается: ' : 'the colour differs: ')
                                               : (ru ? 'цвет отличается немного: ' : 'the colour differs slightly: '))
                         + what + (ru ? ' — в файле ' : ' — the file has ') + queueColorText(x.file_color)
                         + (ru ? ', на катушке ' : ', the spool has ') + queueColorText(x.slot_color));
            }
            if (x.variant) out.push((ru ? 'другой вариант материала: ' : 'another variant of the material: ') + what
                                    + (ru ? ' — в файле ' : ' — the file has ') + queueFilamentName(x.file_fid)
                                    + (ru ? ', в слоте ' : ', the slot has ') + queueFilamentName(x.slot_fid));
        });
        return out;
    };
    //  16.10.2026 (R-115, разбор пакета): вариант материала — названием, а не кодом Bambu. Коды и имена —
    //  из профилей Bambu Studio (resources/profiles/BBL/filament/*@base.json, поле filament_id; сверено
    //  16.10.2026). Незнакомый код показывается как «профиль <код>».
    const QUEUE_BAMBU_FILAMENTS = {
        GFA00: 'Bambu PLA Basic', GFA01: 'Bambu PLA Matte', GFA02: 'Bambu PLA Metal', GFA05: 'Bambu PLA Silk',
        GFA07: 'Bambu PLA Marble', GFA08: 'Bambu PLA Sparkle', GFA09: 'Bambu PLA Tough', GFA50: 'Bambu PLA-CF',
        GFL99: 'Generic PLA', GFG00: 'Bambu PETG Basic', GFG01: 'Bambu PETG Translucent', GFG02: 'Bambu PETG HF',
        GFG99: 'Generic PETG', GFB00: 'Bambu ABS', GFB99: 'Generic ABS', GFB01: 'Bambu ASA', GFB98: 'Generic ASA',
        GFU01: 'Bambu TPU 95A', GFU99: 'Generic TPU',
    };
    const queueFilamentName = (fid) => {
        const c = String(fid || '').trim().toUpperCase();
        if (QUEUE_BAMBU_FILAMENTS[c]) return QUEUE_BAMBU_FILAMENTS[c];
        return c ? (lang.value === 'ru' ? 'профиль ' : 'profile ') + c : (lang.value === 'ru' ? 'не указан' : 'not given');
    };
    const queueWhyLines = (row, max) => {
        const ru = lang.value === 'ru';
        const out = [];
        if (!row) return out;
        const st = row.state || '';
        //  16.10.2026 (R-117): причина видна и у строки, которая вернулась в ожидание. Пометка «запускается
        //  на …», оставшаяся от прошлой попытки (до 16.10.2026), устарела — её не показываем; пометки
        //  автозапуска — только пока он включён.
        const _note = String(row.note || '');
        const _autoNote = _note === 'auto_low_filament' || _note.indexOf('auto_needs_human:') === 0;
        if (_note && (st === 'launching' || st === 'starting' || st === 'attention'
                      || (st === 'waiting' && _note.indexOf('запускается на ') !== 0 && (!_autoNote || queueAutoOn.value)))) {
            out.push(queueNoteText(_note));
        }
        if (st === 'attention') out.push(ru ? 'прежде чем запускать снова, убедитесь, что принтер не печатает эту деталь'
                                            : 'before starting again, make sure the printer is not printing this part');
        if (st === 'launching' || st === 'starting') return out;
        if (row.match_printer_id) {
            //  16.10.2026 (R-016): куда пойдёт каждый филамент и где цвет или вариант не совпадает.
            const _feed = queueFeedLine(row);
            if (_feed) out.push(_feed);
            queueSlotWarnings(row).forEach((w) => out.push(w));
            if (row.match_feed === 'external') out.push(ru ? 'печать пойдёт с ' + queueExtSide(row, true) + 'внешней катушки — материал взят из настройки принтера, проверьте, что катушка стоит'
                                                          : 'printing will use the ' + queueExtSide(row, false) + 'external spool — the material comes from the printer setting, check the spool is loaded');
            if (row.match_unverified) out.push(queueUnverifiedText(row));
            if (row.match_finished) out.push(ru ? 'на принтере была печать — убедитесь, что стол пуст'
                                               : 'the printer has had a print — make sure the bed is clear');
            return out;
        }
        if (row.match_reason === 'material_unknown') {
            const w = queueFileWhyText(row.file_why);
            if (w) out.push(w);
            return out;
        }
        if (row.match_reason === 'incompatible' && row.file_model) out.push((ru ? 'файл нарезан под ' : 'the file is sliced for ') + row.file_model);
        const cs = row.candidates || [];
        cs.slice(0, max).forEach(c => {
            const have = queueHaveText(c);
            out.push((c.name || c.id) + ': ' + queueVerdictText(c) + (have ? ' (' + have + ')' : ''));
        });
        const more = (row.candidates_more || 0) + Math.max(0, cs.length - max);
        if (more > 0) out.push((ru ? 'и ещё принтеров: ' : 'more printers: ') + more);
        return out;
    };
    const queueAdd = async (f) => {
        const name = (f && (f.filename || f.gcode_file)) || '';
        if (!name) return;
        const ru = lang.value === 'ru';
        try {
            const j = await (await fetch('/api/queue-wait/add', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ gcode_file: name, source: 'quick',
                                       part_name: (f && f.part_name) || '' }) })).json();
            if (j && j.ok) {
                pushToast((ru ? 'В очередь: ' : 'Queued: ') + name + ' — '
                          + (j.match_printer_name
                             ? ((ru ? 'найден ' : 'found ') + j.match_printer_name)
                             : queueReasonText(j.match_reason)), 'success');
            } else {
                pushToast((ru ? 'В очередь поставить не удалось' : 'Could not queue')
                          + (j && j.error === 'not_printable' ? ': ' + queueReasonText('not_printable') : ''), 'info');
            }
        } catch (e) {
            pushToast(ru ? 'В очередь поставить не удалось' : 'Could not queue', 'info');
        }
        loadQueueWait();
    };
    const queueRemove = async (id) => {
        try {
            await fetch('/api/queue-wait/remove', { method: 'POST',
                headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) });
        } catch (e) { /* покажем прежний список */ }
        loadQueueWait();
    };
    const queueStartError = (j) => {
        const ru = lang.value === 'ru';
        const e = (j && j.error) || '';
        if (e === 'enqueue_rejected') {
            const en = (j && j.enqueue) || {};
            const b = (en.blocked || [])[0];
            if (b && (b.reason || b.message)) return queueReasonText(e) + ': ' + (b.reason || b.message);
            if ((en.held || []).length) return ru ? 'принтер удержан другим запуском' : 'the printer is held by another launch';
        }
        if (e === 'printer_changed' && j.printer_name) {
            return queueReasonText(e) + (ru ? ' (сейчас подходит ' : ' (now fits ') + j.printer_name + ')';
        }
        return queueReasonText(e);
    };
    //  Подтверждённый запуск. Спрашиваем ИМЕНЕМ принтера: владелец должен видеть, куда уйдёт
    //  печать, а не нажимать «ок» вслепую. 15.09.2026: заодно — с какой катушки и не лежит ли на
    //  столе прошлая деталь; сервер запускает ровно на подтверждённом принтере.
    const queueStart = async (row) => {
        if (!row || !row.match_printer_id || queueBusy.value) return;
        if (row.state === 'launching' || row.state === 'starting') return;   // исход ещё не известен
        const ru = lang.value === 'ru';
        const notes = [];
        if (row.state === 'attention') notes.push(ru ? 'Прошлый запуск этой строки оборвался неясно — убедитесь, что принтер не печатает эту деталь.'
                                                     : 'The previous launch of this row ended unclear — make sure the printer is not printing this part.');
        if (row.match_feed === 'external') notes.push(ru ? 'Печать пойдёт с ' + queueExtSide(row, true) + 'внешней катушки: материал взят из настройки принтера — проверьте, что катушка стоит.'
                                                      : 'Printing will use the ' + queueExtSide(row, false) + 'external spool: the material comes from the printer setting — check the spool is loaded.');
        //  16.10.2026 (R-141): у FlashForge материал проверяет человек — просьба прямо в окне.
        if (row.match_feed === 'unverified') notes.push(ru
            ? 'FlashForge не сообщает по сети, какой материал заправлен. Проверьте на принтере, что стоит ' + (row.material || 'нужный материал') + '.'
            : 'FlashForge does not report the loaded material over the network. Check on the printer that ' + (row.material || 'the right material') + ' is loaded.');
        else if (row.match_unverified) notes.push(queueUnverifiedText(row).replace(/^./, (ch) => ch.toUpperCase()) + '.');
        if (row.match_finished) notes.push(ru ? 'На принтере была печать — убедитесь, что стол пуст.'
                                             : 'The printer has had a print — make sure the bed is clear.');
        //  16.10.2026 (R-016): куда пойдёт каждый филамент, и где цвет или вариант не совпадает. Решает
        //  человек, как в Bambu Studio: запуск из-за цвета не запрещается.
        const _list = ((row.match_slots) || []).map((x) => (x.material || '?') + ' → ' + queueSlotWhere(x, row)
            + (x.rel === 'mismatch' ? (ru ? ' — цвет отличается' : ' — the colour differs')
               : x.rel === 'close' ? (ru ? ' — цвет отличается немного' : ' — the colour differs slightly')
               : x.rel === 'exact' ? (ru ? ' — цвет совпадает' : ' — the colour matches') : ''));
        queueSlotWarnings(row).forEach((w) => _list.push(w.replace(/^./, (ch) => ch.toUpperCase())));
        if (!await askConfirm({ title: _L('Запустить печать?', 'Start printing?'),
                                text: (ru ? '«' : '"') + row.gcode_file + (ru ? '» на принтере ' : '" on printer ') + row.match_printer_name
                                      + (notes.length ? ' ' + notes.join(' ') : ''),
                                list: _list.join('\n'),
                                okText: _L('Запустить', 'Start') })) return;
        queueBusy.value = row.id;
        //  16.10.2026 (R-008): склад против — то же окно «Материал закончился», что у «Задач», «Проектов»
        //  и «Загрузить»: тот же порядок (сначала очередь приняла запуск, потом списание остатка) и тот
        //  же повтор запуска, с {skip_filament: true} только по решению владельца в окне.
        const _post = async (skipFilament) => (await fetch('/api/queue-wait/start', { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(Object.assign({ id: row.id, printer_id: row.match_printer_id },
                                               skipFilament ? { skip_filament: true } : {})) })).json();
        const _low = (j) => (j && j.error === 'enqueue_rejected')
            ? (((j.enqueue || {}).blocked) || []).filter((b) => b && b.status === 'low_filament')
                .map((b) => Object.assign({ printer_id: row.match_printer_id, printer_name: row.match_printer_name }, b))
            : [];
        const _accepted = (j) => {
            pushToast((ru ? 'Запуск поставлен: ' : 'Launch queued: ') + j.printer_name, 'success');
            ((j.enqueue && j.enqueue.notes) || []).forEach(n => pushFilNote(n));
            fetchPrintQueue();
        };
        const _launch = async (skipFilament) => {
            let r = null;
            try { r = await _post(skipFilament); } catch (e) { r = null; }
            if (r && r.ok) { _accepted(r); loadQueueWait(); return true; }
            const lb = _low(r);
            if (lb.length) return { low_filament: lb[0] };
            pushToast((ru ? 'Запустить не удалось: ' : 'Could not start: ') + queueStartError(r), 'info');
            loadQueueWait();
            return false;
        };
        try {
            const j = await _post(false);
            const lb = _low(j);
            if (j && j.ok) {
                _accepted(j);
            } else if (lb.length) {
                openFilamentDecision(lb, [{ printer_id: row.match_printer_id, launch: _launch }], 0, true);
            } else {
                pushToast((ru ? 'Запустить не удалось: ' : 'Could not start: ') + queueStartError(j), 'info');
            }
        } catch (e) {
            pushToast(ru ? 'Запустить не удалось' : 'Could not start', 'info');
        }
        queueBusy.value = '';
        loadQueueWait();
    };
    //  Отметка «кому разрешён запуск из очереди» ставится ТАМ, ГДЕ ПРИНТЕРЫ (2.921, заказ
    //  владельца): в шапке панели включается режим, и дальше нажатие на карточку ставит и
    //  снимает разрешение. Список галочек на экране очереди для этого не годился — принтеров
    //  на ферме сотни, а решение принимается глядя на сам принтер.
    const queuePickMode = ref(false);
    const queueIsAllowed = (pid) => queueAllowed.value.includes(pid);
    const toggleQueuePick = () => {
        queuePickMode.value = !queuePickMode.value;
        document.documentElement.classList.toggle('ui3-qpick-on', queuePickMode.value);
        if (queuePickMode.value) {
            exitSpotlight();                        // два режима выбора разом — путаница
            loadQueueWait();                        // отметки показываем свежие, а не из памяти
            pushToast(lang.value === 'ru'
                ? 'Нажимайте на принтеры: отметьте, кому разрешён запуск из очереди'
                : 'Click printers to allow or forbid starting from the queue', 'info');
        }
    };
    //  2.973: общие команды нескольким принтерам убраны по решению владельца — на его ферме
    //  они оказались не нужны. Одиночные пауза, продолжение и остановка остались на своих местах.

    const queueSetAllowed = async (pid, allowed) => {
        try {
            await fetch('/api/printer/queue-allowed', { method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ printer_id: pid, allowed: !!allowed }) });
        } catch (e) { /* следующий опрос покажет настоящее состояние */ }
        loadQueueWait();
    };

    if (ui3Mode) { _ui3ApplyRight(); loadQueueWait(); }

    //  ── Настройки фермы — НА СЕРВЕРЕ (2.927, разрешение владельца) ──
    //  Пометки принтера «сопло / материал / группа» (тоже 2.927) удалены 12.09.2026 по решению
    //  владельца: блок из пульта, запись на сервер и разовый перенос из браузера. Колонки в
    //  базе оставлены как были — схема не меняется, прежние значения никуда не отдаются.
    //  Интервал поэтапного запуска — настройка ФЕРМЫ, а не компьютера: тянем с сервера,
    //  пишем на сервер. localStorage остаётся стартовым значением до ответа сервера и
    //  разово мигрирует на него, если на сервере ещё пусто.
    const _farmSettingsPull = async () => {
        try {
            const j = await (await fetch('/api/farm-settings')).json();
            const st = (j && j.settings) || {};
            if ('stagger_on' in st) staggerOn.value = st.stagger_on === '1';
            //  16.09.2026: автозапуск очереди — тоже настройка фермы
            if ('queue_auto_start' in st) queueAutoOn.value = st.queue_auto_start === '1';
            //  R-131: выключатель «Проверять обновления» — настройка фермы; нет записи — включено
            _updateCheckFromServer(st.update_check);
            if ('auto_start_printers' in st) queueAutoPids.value = st.auto_start_printers || [];
            if ('stagger_sec' in st) {
                const n = parseInt(st.stagger_sec, 10);
                if (n >= 5) staggerInterval.value = Math.min(600, n);
            }
            if ('low_pct' in st) _ui3FilLowSet(st.low_pct, false);   // 2.965: порог «скоро кончится»
            if (Array.isArray(st.preheat_presets)) ui3PresetsFromServer(st.preheat_presets);   // R-103: пресеты фермы
            //  Какие модули показывать на баре. Выбор с сервера главнее: он общий для фермы.
            //  Сервер молчит — берём выбор, сделанный на этом компьютере (2.1001); нет и его —
            //  владелец не выбирал, показываем все модули с окном.
            if (Array.isArray(st.bar_modules)) {
                barModuleIds.value = st.bar_modules;
                barLocalOnly.value = false;
                _barLocalWrite(null);
            } else {
                const _loc = _barLocalRead();
                barModuleIds.value = _loc;
                barLocalOnly.value = _loc !== null;
            }
            if (!('stagger_on' in st) && !('stagger_sec' in st)
                && (localStorage.getItem('farm_stagger') !== null
                    || localStorage.getItem('farm_stagger_sec') !== null)) {
                //  На сервере пусто, в браузере есть — заносим местные значения один раз.
                _farmSettingsPush();
            }
        } catch (e) { /* сервер недоступен — работаем с местными значениями */ }
    };
    const _farmSettingsPush = async () => {
        try {
            await fetch('/api/farm-settings', { method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ stagger_on: staggerOn.value ? '1' : '0',
                                       stagger_sec: String(staggerInterval.value),
                                       low_pct: String(ui3FilLowPct.value) }) });
        } catch (e) { /* следующее изменение донесёт */ }
    };

    if (typeof window !== 'undefined') setTimeout(_farmSettingsPull, 0);

    //  2.982 (R-106, решение владельца): интерфейс 3.0 — основной, и главная страница отдаёт
    //  его сама. Переключатель 2.0/3.0 в шапке СКРЫТ, а не удалён: код 2.0 остаётся целиком и
    //  открывается адресом /?ui=2 — «в дальнейшем это нам может снова понадобиться».
    const uiSwitchVisible = false;
    const goToUi2 = () => {
        //  Возврат в рабочий интерфейс тем же адресом, что и аварийный выход: /?ui=2.
        try { localStorage.setItem('farm_ui_version', '2'); } catch (e) { /* нет хранилища */ }
        window.location.href = '/?ui=2';
    };

    const goToUi3 = () => {
        try { localStorage.setItem('farm_ui_version', '3'); } catch (e) {}
        window.location.href = '/ui3';
    };
    const setLang = (l) => { lang.value = l; try { localStorage.setItem('farm_lang', l); } catch(e){} };
    // ===== Тема интерфейса (тёмная/светлая, выбор пользователя, сохраняется в localStorage) =====
    // Светлая палитра задаётся в app.css блоком :root[data-theme="light"]; тёмная — поведение по умолчанию.
    const theme = ref('dark');
    try { const _t = localStorage.getItem('farm_theme'); if (_t === 'light' || _t === 'dark') theme.value = _t; } catch(e){}
    const applyTheme = () => { try { document.documentElement.setAttribute('data-theme', theme.value); } catch(e){} };
    const setTheme = (t) => { theme.value = (t === 'light') ? 'light' : 'dark'; try { localStorage.setItem('farm_theme', theme.value); } catch(e){} applyTheme(); };
    const toggleTheme = () => setTheme(theme.value === 'light' ? 'dark' : 'light');
    applyTheme();
    // ===== Шрифт интерфейса (выбор пользователя, сохраняется в localStorage) =====
    const uiFonts = [
      // 26.09.2026: шрифт по умолчанию — свободный «3DIWELL Wide J» (web/design/fonts/, --fm-font в fonts.css);
      // прежний фирменный шрифт удалён по решению владельца. Пункт 'default' без stack: шрифт задаёт
      // fonts.css, работает увеличение html{zoom:1.196}. Wide P — вторая свободная замена, с тем же увеличением,
      // шапка тем же шрифтом. Подписи короткие: при крупном тексте длинная переносилась в поле на вторую строку.
      { key: 'default',     en: '3DIWELL Wide J',  ru: '3DIWELL Wide J',  stack: '' },
      { key: 'wide-p',      en: '3DIWELL Wide P',  ru: '3DIWELL Wide P',  stack: "'3DIWELL Wide P', sans-serif", brand: true },
      { key: 'segoe',       en: 'Segoe UI',        ru: 'Segoe UI',        stack: "'Segoe UI', system-ui, sans-serif" },
      { key: 'tahoma',      en: 'Tahoma',          ru: 'Tahoma',          stack: "Tahoma, Geneva, sans-serif" },
      { key: 'calibri',     en: 'Calibri',         ru: 'Calibri',         stack: "Calibri, 'Segoe UI', sans-serif" },
      { key: 'arial',       en: 'Arial',           ru: 'Arial',           stack: "Arial, Helvetica, sans-serif" },
      { key: 'verdana',     en: 'Verdana',         ru: 'Verdana',         stack: "Verdana, Geneva, sans-serif" },
      { key: 'trebuchet',   en: 'Trebuchet MS',    ru: 'Trebuchet MS',    stack: "'Trebuchet MS', Tahoma, sans-serif" },
      { key: 'bahnschrift', en: 'Bahnschrift',     ru: 'Bahnschrift',     stack: "Bahnschrift, 'Segoe UI', sans-serif" },
      { key: 'georgia',     en: 'Georgia',         ru: 'Georgia',         stack: "Georgia, 'Times New Roman', serif" },
      { key: 'cambria',     en: 'Cambria',         ru: 'Cambria',         stack: "Cambria, Georgia, serif" },
      { key: 'times',       en: 'Times New Roman', ru: 'Times New Roman', stack: "'Times New Roman', Times, serif" },
      { key: 'mono',        en: 'Consolas',        ru: 'Consolas',        stack: "Consolas, 'Cascadia Mono', ui-monospace, monospace" },
      { key: 'courier',     en: 'Courier New',     ru: 'Courier New',     stack: "'Courier New', Courier, monospace" }
    ];
    const uiFont = ref('default');
    try { let _f = localStorage.getItem('ui_font'); if (_f === 'wide-j') { _f = 'default'; try { localStorage.setItem('ui_font', _f); } catch(e){} } if (_f && uiFonts.some(x => x.key === _f)) uiFont.value = _f; } catch(e){}
    const applyUiFont = () => { try { let el = document.getElementById('ui-font-override'); if (!el) { el = document.createElement('style'); el.id = 'ui-font-override'; document.head.appendChild(el); } const f = uiFonts.find(x => x.key === uiFont.value); const isDefaultFont = !(f && f.stack) || !!(f && f.brand); /* 2.933: буст html{zoom:1.196} при ДРОБНОМ масштабе браузера (110/125%%...) складывался с ним, и фирменный шрифт переставал отрисовываться — строки списка выглядели пустыми (снимок владельца). При дробном devicePixelRatio буст выключен: масштабом управляет браузер. */ const _d = window.devicePixelRatio || 1; const _whole = Math.abs(_d - Math.round(_d)) <= 0.001; const _fsBoost = (isDefaultFont && !isMobile.value && _whole); try { document.documentElement.style.zoom = _fsBoost ? '1.196' : ''; } catch(e){} try { if (exOpen.value && exWin.value.init) exWinClampIntoView(); } catch(e){} el.textContent = (f && f.brand) ? ('* { font-family: ' + f.stack + ' !important; }') : (f && f.stack) ? ('* { font-family: ' + f.stack + " !important; } header.app-header, header.app-header * { font-family: '3DIWELL Wide J', sans-serif !important; }") : ''; try { requestAnimationFrame(function(){ try { recalcLeftCol(); } catch(e){} }); } catch(e){} } catch(e){} };
    // Alpha 2.848: смена шрифта меняет html{zoom}, значит масштаб рабочей области нужно пересчитать.
    // Вызов защищён try: applyWrapZoom объявлен ниже по файлу и на этапе setup ещё не существует —
    // но setUiFont срабатывает только по действию пользователя, когда объявление уже выполнено.
    const setUiFont = (k) => { uiFont.value = k; try { localStorage.setItem('ui_font', k); } catch(e){} applyUiFont(); try { applyWrapZoom(); } catch(e){} applyUiTextSize(); };
    // ===== Размер текста (26.09.2026, заказ владельца: «увеличение и уменьшение, чтобы были варианты») =====
    // Размеры шрифта в программе заданы сотнями разных правил в точках, и переменная --text-scale
    // затрагивает лишь часть из них. Поэтому размер меняется свойством font-size-adjust на ВСЕХ
    // элементах: браузер пересчитывает кегль каждого текста так, чтобы высота строчной буквы стала
    // m × заданный размер / высота строчной выбранного шрифта. Высоту строчной меряем тем же браузером
    // (узел-зонд со значением 1), поэтому это верно для любого выбранного шрифта. Окна и кнопки своих
    // размеров не меняют. 100 % — правила нет вовсе: вид ровно прежний. Выбор — на этом компьютере.
    // Правило стоит на КАЖДОМ элементе с !important, а не на html: сокращённая запись font: у части
    // элементов сбрасывает унаследованное font-size-adjust, и такие надписи оставались бы прежними.
    const uiTextSizes = [
      { key: '90',  v: 0.9, ru: '90 %',              en: '90%' },
      { key: '100', v: 1,   ru: '100 % (обычный)',   en: '100% (standard)' },
      { key: '110', v: 1.1, ru: '110 %',             en: '110%' },
      { key: '120', v: 1.2, ru: '120 %',             en: '120%' },
      { key: '130', v: 1.3, ru: '130 %',             en: '130%' }
    ];
    const uiTextSize = ref('100');
    try { const _t = localStorage.getItem('ui_text_size'); if (_t && uiTextSizes.some(x => x.key === _t)) uiTextSize.value = _t; } catch(e){}
    const _uiFontAspect = (host) => {
        const s = document.createElement('span');
        s.textContent = 'xxxxxxxxxx';
        s.style.cssText = 'position:absolute;left:-9999px;top:0;visibility:hidden;white-space:nowrap;font-size:100px;letter-spacing:0';
        (host || document.getElementById('app') || document.body).appendChild(s);
        s.style.setProperty('font-size-adjust', 'none', 'important');
        const w0 = s.getBoundingClientRect().width;
        s.style.setProperty('font-size-adjust', '1', 'important');
        const w1 = s.getBoundingClientRect().width;
        s.remove();
        return (w0 > 0 && w1 > 0) ? w0 / w1 : 0;
    };
    const applyUiTextSize = () => {
        try {
            let el = document.getElementById('ui-text-size');
            if (!el) { el = document.createElement('style'); el.id = 'ui-text-size'; document.head.appendChild(el); }
            const t = uiTextSizes.find(x => x.key === uiTextSize.value);
            const m = t ? t.v : 1;
            el.textContent = '';                    // мерить без собственной поправки
            if (m === 1) return;
            const a = _uiFontAspect();
            let css = (a > 0.05 && a < 2) ? '*{font-size-adjust:' + (a * m).toFixed(4) + ' !important}' : '';
            //  Шапка при шрифте Windows идёт СВОИМ шрифтом (applyUiFont), а поправка выше замерена шрифтом
            //  страницы: надпись «Брокер данных» росла в 1,4-1,7 раза вместо 1,1-1,3 и вылезала из язычка.
            //  Шапке — своя поправка, замеренная пробой внутри неё самой.
            const hdr = document.querySelector('header.app-header');
            const ah = hdr ? _uiFontAspect(hdr) : 0;
            if (ah > 0.05 && ah < 2 && Math.abs(ah - a) > 0.0005)
                css += 'header.app-header,header.app-header *{font-size-adjust:' + (ah * m).toFixed(4) + ' !important}';
            el.textContent = css;
        } catch(e){}
    };
    const setUiTextSize = (k) => {
        uiTextSize.value = k; try { localStorage.setItem('ui_text_size', k); } catch(e){}
        applyUiTextSize();
        try { setTimeout(() => { try { recalcLeftCol(); } catch(e){} }, 0); } catch(e){}
    };
    // Файл выбранного шрифта догружается позже первого показа — замер пересчитывается, когда он готов.
    try { if (document.fonts) { document.fonts.addEventListener('loadingdone', applyUiTextSize); document.fonts.ready.then(applyUiTextSize); } } catch(e){}
    // Alpha 2.834: переход к секции вкладки «Система» из компактной мини-навигации. Ничего не
    // сохраняет и не отправляет — только прокручивает уже отрендеренную область настроек.
    const setSecActive = ref('');
    // Alpha 2.836: ЕДИНЫЙ источник истины о высоте закреплённой зоны настроек. Величину даёт сам
    // элемент .fm-set-mini (замер, а не константа), она же уезжает в CSS-переменную
    // --fm-set-sticky-h, которой пользуются scroll-padding-top области и scroll-margin-top секций.
    // Так якорный переход любым способом — чипом, нативным якорем, переводом фокуса — оставляет
    // заголовок секции НИЖЕ полосы.
    const SET_STICKY_GAP = 10;          // постоянный визуальный зазор под навигацией
    const setStickyMetrics = () => {
        const box = document.querySelector('.fm-set-scroll');
        if (!box) return null;
        const rect = box.getBoundingClientRect();
        // getBoundingClientRect отдаёт ВИЗУАЛЬНЫЕ px (уже с учётом двойного zoom), а scrollTop
        // живёт в px самого контейнера. Коэффициент перевода МЕРЯЕМ по этому же элементу, а не
        // подбираем константой: так он верен при любом zoom и масштабе шрифта.
        const k = rect.height ? (box.clientHeight / rect.height) : 1;
        const mini = box.querySelector('.fm-set-mini');
        const mr = mini ? mini.getBoundingClientRect() : null;
        const bandVis = (mr && mr.height > 0) ? mr.height + SET_STICKY_GAP : 0;
        box.style.setProperty('--fm-set-sticky-h', Math.round(bandVis * k) + 'px');
        return { box, rect, k, bandVis };
    };
    const setSecGo = (id) => {
        // Alpha 2.835 (ROOT CAUSE верхнего бара). Здесь НЕЛЬЗЯ использовать scrollIntoView: он
        // прокручивает ВСЕХ прокручиваемых предков, включая корневой #app (у него в m-ui задан
        // overflow-y:auto), а внутри #app лежит .zoom-wrap вместе с верхним баром — из-за этого
        // бар уезжал вверх и не возвращался (полосы прокрутки у корня нет). Прокручиваем РОВНО
        // одну область настроек и вычисляем смещение сами.
        // Alpha 2.836 (ROOT CAUSE чипов). Раньше вычиталось ФИКСИРОВАННЫЕ 6px, а закреплённая
        // полоса занимает 56-97px (при узком окне чипы переносятся на две строки) — заголовок
        // целевой секции уезжал ПОД неё. Теперь вычитается реально замеренная высота полосы, а
        // визуальные px переводятся в px прокрутки замеренным коэффициентом.
        try {
            const el = document.getElementById(id);
            const m = setStickyMetrics();
            if (el && m) {
                const deltaVis = el.getBoundingClientRect().top - m.rect.top - m.bandVis;
                m.box.scrollTo({ top: Math.max(0, m.box.scrollTop + deltaVis * m.k), behavior: 'smooth' });
            }
            setSecActive.value = String(id || '');
        } catch (e) {}
    };
    onMounted(applyUiFont);
    onMounted(applyUiTextSize);
    const tr = (s) => (lang.value === 'ru' && RU[s] !== undefined) ? RU[s] : s;
    // Делаем tr/lang доступными дочерним компонентам (.js) через inject — см. composables/useI18n.js.
    provide('tr', tr);
    provide('lang', lang);
    provide('icons', icons);
    // Режимы отображения принтеров. Расширяемо: добавить новый вид = добавить запись сюда
    // (id, подпись, SVG-иконка) + при необходимости ветку отрисовки. Переключатель строится по этому списку.
    //  2.922: в оформлении 3.0 видов три — «Ячейки» (прежний список карточек), настоящий
    //  «Список» строками и «Сетка». Рабочий интерфейс 2.0 остаётся с прежними двумя.
    //  R-107 (2.985): четвёртый вид — «Дашборд»: обзор всей фермы во всю ширину, карточки в
    //  адаптивной сетке, содержимое по состоянию принтера, порядок — по важности.
    const viewModes = ui3Mode ? [
        { id: 'list', title: 'Cells view', icon: 'view-cells' },
        { id: 'rows', title: 'List view', icon: 'view-list' },
        { id: 'grid', title: 'Grid view', icon: 'view-grid' },
        { id: 'dash', title: 'Dashboard view', icon: 'view-dash' },
    ] : [
        { id: 'list', title: 'List view', icon: 'view-list' },
        { id: 'grid', title: 'Grid view', icon: 'view-grid' },
    ];
    const viewMode = ref('list');
    try { const _vm = localStorage.getItem('farm_view'); if (viewModes.some(m => m.id === _vm)) viewMode.value = _vm; } catch(e){}
    const setViewMode = (m) => { viewMode.value = m; try { localStorage.setItem('farm_view', m); } catch(e){} };
    //  Подсказка единственной кнопки-переключателя: с тремя видами «список или сетка» уже
    //  неправда, поэтому в 3.0 подсказка называет текущий вид. В 2.0 остаётся прежняя.
    const viewModeHint = computed(() => {
        if (!ui3Mode) return '';
        const ru = lang.value === 'ru';
        const names = ru ? { list: 'Ячейки', rows: 'Список', grid: 'Сетка', dash: 'Дашборд' }
                         : { list: 'Cells', rows: 'List', grid: 'Grid', dash: 'Dashboard' };
        return (ru ? 'Вид: ' : 'View: ') + (names[viewMode.value] || '')
             + (ru ? ' — нажмите, чтобы переключить' : ' — click to switch');
    });
    const gridPopStyle = ref({});
    // ------------------------------------------------------------------------
    // БЛОК: главное реактивное состояние приложения.
    // parts/printers/stagingFiles приходят с сервера; wsData обновляется по
    // WebSocket. Остальные ref управляют окнами, выбранными файлами и формами.
    // ------------------------------------------------------------------------
    const parts = ref([]);
    const printers = ref([]);
    const stagingFiles = ref([]);
    const isDraggingStaging = ref(false);
    const printMenuUid = ref(null);
    const wsData = ref({});
    const wsConnected = ref(false);
    const syncStatus = ref('idle');
    const showAddPrinterModal = ref(false);
    const cameraPrinterId = ref(null);
    const editingPrinterId = ref(null);
    // Штатные значения формы принтера — ЕДИНЫЙ источник по умолчанию. Каждый вызов отдаёт
    // НОВЫЙ независимый объект: форма создания не должна делить состояние с прошлым принтером.
    const blankPrinterForm = () => ({ name: '', type: 'bambu', ip: '', port: null, token: '', gen: 'auto', serial: '', model: '' });
    const newPrinter = ref(blankPrinterForm());
    // Alpha 2.776: форма больше НЕ держит сохранённый секрет. Поля «токен» и «серийный номер»
    // при редактировании открываются ПУСТЫМИ, а эти флаги лишь помечают, что значение в базе
    // уже настроено — чтобы показать спокойную подпись вместо самого секрета. Пустое поле
    // означает «оставить как есть»: merge выполняет сервер (см. _merge_printer_secret).
    const editingHasToken = ref(false);
    const editingHasSerial = ref(false);
    //  16.10.2026 (R-020): адрес принтера из одних цифр и точек — это всегда IPv4 (имя узла из
    //  одних цифр не бывает, RFC 3696), и он обязан быть полным. «198.68.104» Windows молча
    //  достраивает до ПУБЛИЧНОГО 198.68.0.104 — связь с принтером ушла бы в интернет. Здесь та же
    //  проверка, что на сервере (app/printer_address.py), для строк из цифр; имя узла и IPv6
    //  проверяет сервер, его отказ лежит в printerAddrServerProblem. -> '' | 'short' | 'bad'.
    const printerAddressProblem = (ip) => {
        const s = String(ip == null ? '' : ip).trim();
        if (!s || !/^[0-9.]+$/.test(s)) return '';
        const parts = s.split('.');
        if (parts.filter(x => x).length < 4) return 'short';
        if (parts.length !== 4 || parts.some(x => !/^(0|[1-9][0-9]{0,2})$/.test(x) || Number(x) > 255)) return 'bad';
        return '';
    };
    const printerAddrServerProblem = ref(null);   // { ip, problem } — отказ сервера для ЭТОГО адреса
    const newPrinterAddrProblem = computed(() => {
        const f = newPrinter.value || {};
        if (f.type === 'demo') return '';
        const own = printerAddressProblem(f.ip);
        if (own) return own;
        const sp = printerAddrServerProblem.value;
        return (sp && sp.ip === String(f.ip == null ? '' : f.ip).trim()) ? (sp.problem || 'bad') : '';
    });
    const printerAddrText = (problem) => {
        const ru = lang.value === 'ru';
        if (problem === 'short') return ru ? 'Неполный адрес: нужно 4 числа через точку, например 192.168.1.20.'
                                           : 'Incomplete address: four numbers separated by dots are needed, e.g. 192.168.1.20.';
        if (problem === 'bad') return ru ? 'Так адрес не записывается: нужно 4 числа от 0 до 255 через точку (например 192.168.1.20) или имя принтера в сети.'
                                         : 'This is not a valid address: four numbers 0–255 separated by dots (e.g. 192.168.1.20) or the printer network name are needed.';
        return '';
    };
    const newPrinterAddrText = computed(() => printerAddrText(newPrinterAddrProblem.value));
    //  Метка на карточке: сервер отдаёт address_problem в списке принтеров — связь с таким
    //  принтером не запускается. Нажатие открывает форму, где адрес и правится.
    const printerAddrMark = (p) => {
        const pr = p && p.address_problem;
        if (!pr) return '';
        const ru = lang.value === 'ru';
        return pr === 'short' ? (ru ? 'Неполный адрес' : 'Incomplete address') : (ru ? 'Неверный адрес' : 'Invalid address');
    };
    const printerAddrTip = (p) => {
        if (!p || !p.address_problem) return '';
        const ru = lang.value === 'ru';
        return (ru ? 'Адрес «' : 'Address “') + String(p.ip == null ? '' : p.ip) + (ru ? '» записан неверно. ' : '” is not valid. ')
            + printerAddrText(p.address_problem)
            + (ru ? ' Связь с принтером не запускается. Нажмите, чтобы исправить адрес.' : ' The app does not connect to this printer. Click to fix the address.');
    };
    const copyBaseName = ref('');   // Alpha 2.831: имя исходного принтера для заголовка «на основе …»
    const printerSecretHint = (kind) => {
        const has = (kind === 'token') ? editingHasToken.value : editingHasSerial.value;
        if (!has) return '';
        return lang.value === 'ru' ? 'Сохранён — оставьте пустым, чтобы не менять'
                                   : 'Saved — leave empty to keep current value';
    };
    const showModelPicker = ref(false);
    const printerModels = ref([]);
    const modelSearch = ref('');
    const modelsLoaded = ref(false);
    const loadPrinterModels = async () => {
        if (modelsLoaded.value) return;
        let list = [];
        try { const r = await fetch('/api/printer-models'); if (r.ok) { list = await r.json(); } } catch (e) {}
        list.unshift({ name: 'Klipper', cover: '', generic: true });
        printerModels.value = list;
        modelsLoaded.value = true;
    };
    const openModelPicker = () => { modelSearch.value = ''; loadPrinterModels(); showModelPicker.value = true; };
    const pickModel = (m) => {
        newPrinter.value.model = m.name;
        const n = m.name.toLowerCase();
        if (n.indexOf('bambu') === 0) newPrinter.value.type = 'bambu';
        else if (n.indexOf('flashforge') === 0) newPrinter.value.type = 'flashforge';
        //  12.10.2026: у Creality выбранный способ подключения (заводская прошивка) при смене модели сохраняется.
        else newPrinter.value.type = (newPrinter.value.type === 'creality' && n.indexOf('creality') === 0) ? 'creality' : 'klipper';
        showModelPicker.value = false;
    };
    //  12.10.2026: принтер Creality на заводской прошивке (Ender-3 V3 KE, Ender-5 Max, K1…) — без
    //  Moonraker; программа подключается к родной службе Creality (порт 9999), как Creality Print.
    //  Тип «creality». С root и Moonraker — прежний тип «klipper». Выбор — в форме принтера.
    const isCrealityModel = computed(() => String(newPrinter.value.model || '').trim().toLowerCase().indexOf('creality') === 0);
    const setCrealityLink = (v) => { const t = (v === 'creality') ? 'creality' : 'klipper'; if (newPrinter.value.type !== t) { newPrinter.value.type = t; newPrinter.value.port = null; } };
    const filteredModels = computed(() => {
        const q = modelSearch.value.trim().toLowerCase();
        if (!q) return printerModels.value;
        return printerModels.value.filter(m => m.name.toLowerCase().includes(q));
    });
    // Alpha 2.733: нормализатор ключа модели — зеркало server _norm_model_key (trim + схлопывание пробелов + lower).
    // Имена моделей ASCII (бренды), поэтому toLowerCase эквивалентен casefold сервера.
    const _normModelKey = (s) => s ? String(s).trim().replace(/\s+/g, ' ').toLowerCase() : '';
    const selectedModelCover = computed(() => {
        if (!newPrinter.value.model) return '';
        // ТОЛЬКО готовый canonical cover из registry (/api/printer-models). Путь из сырого model НЕ строим:
        // неизвестная/legacy-модель без записи → '' → показывается fallback-силуэт (не битая картинка).
        // Резолв legacy: по нормализованному model_key (регистр/лишние пробелы), с откатом на точное имя.
        const k = _normModelKey(newPrinter.value.model);
        const hit = printerModels.value.find(m => (m.model_key ? m.model_key === k : m.name === newPrinter.value.model));
        return hit ? hit.cover : '';
    });
    const groupedModels = computed(() => {
        const groups = {};
        for (const m of filteredModels.value) {
            const brand = m.generic ? 'Generic' : ((m.name.split(' ')[0]) || 'Other');
            if (!groups[brand]) groups[brand] = [];
            groups[brand].push(m);
        }
        const order = Object.keys(groups).sort((a, b) => {
            if (a === 'Generic') return -1;
            if (b === 'Generic') return 1;
            return a < b ? -1 : (a > b ? 1 : 0);
        });
        return order.map(b => ({ brand: b, items: groups[b] }));
    });
    // Блокировка прокрутки заднего фона (body/html), пока открыто окно выбора модели — тот же приём, что у настроек (watch(showSettings)). Сброс при закрытии.
    watch(showModelPicker, (v) => {
        try {
            document.body.style.overflow = v ? 'hidden' : 'auto';
            document.documentElement.style.overflow = v ? 'hidden' : '';
        } catch (e) {}
    });

    const printersEditMode = ref(false);              // редактирование секции принтеров (драг)
    const editingProjects = ref({});                  // { projName: true } — проекты в режиме редактирования
    const expandedProjects = ref({});
    const expandedStaging = ref({});   // независимо раскрытые деревья состава плиты в строках Tasks
    const editingProjectNames = ref({});
    const editingProjectDates = ref({});
    const showModal = ref(false);
    const activeModalPrinterId = ref(null);
    const tempNozzle = ref('');
    const tempNozzleL = ref('');
    const tempNozzleR = ref('');
    //  16.10.2026 (R-145): сопло двухсопельного Bambu (H2D) ищется по НОМЕРУ из телеметрии, а не по
    //  месту в списке. У прошивки и Bambu Studio сопло 0 — основное, ПРАВОЕ; 1 — ЛЕВОЕ (так же
    //  ha-bambulab). Раньше «L» показывало и грело сопло 0, то есть правое. Нет номера — место в списке.
    const nozzleById = (st, id) => {
        const list = (st && Array.isArray(st.nozzles)) ? st.nozzles : [];
        return list.find((n) => n && Number(n.id) === id) || (list.some((n) => n && n.id !== undefined && n.id !== null) ? {} : (list[id] || {}));
    };
    const tempBed = ref('');
    const printFileName = ref('');
    const cellAmsOpen = ref(false);
    const cellAmsStyle = ref({});                   // вычисляемая позиция попапа слотов AMS (телепорт в body)
    // Открыть/закрыть попап выбора слота AMS у карточки принтера. Попап телепортируется в body
    // (иначе его режет overflow:hidden карточки) и позиционируется position:fixed рядом с кнопкой
    // ПЕЧАТЬ. Направление (вверх/вниз) выбираем по свободному месту: по умолчанию вверх (как было),
    // но если сверху мало места (ячейка у верхней кромки) — раскрываем вниз. Так попап виден целиком
    // при любом положении ячейки. Координаты делим на html-zoom (элемент в body — вне .zoom-wrap).
    function toggleCellAms(ev, p) {
        if (cellAmsOpen.value && activeModalPrinterId.value === p.id) { cellAmsOpen.value = false; return; }
        const W = 184, M = 6, pad = 8;
        const st = { position: 'fixed', width: W + 'px', zIndex: 100060 };
        try {
            const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1.04;
            const r = ev.currentTarget.getBoundingClientRect();
            const vw = (window.innerWidth || 1280) / z, vh = (window.innerHeight || 800) / z;
            const rTop = r.top / z, rBottom = r.bottom / z, rRight = r.right / z;
            let left = rRight - W;
            if (left < pad) left = pad;
            if (left + W > vw - pad) left = vw - W - pad;
            st.left = left + 'px';
            const spaceBelow = vh - rBottom - pad, spaceAbove = rTop - pad;
            if (spaceAbove >= 140 || spaceAbove >= spaceBelow) {   // по умолчанию вверх; вниз — если сверху тесно
                st.bottom = (vh - rTop + M) + 'px';
                st.maxHeight = Math.max(80, spaceAbove - M) + 'px';
            } else {
                st.top = (rBottom + M) + 'px';
                st.maxHeight = Math.max(80, spaceBelow - M) + 'px';
            }
        } catch (e) {}
        cellAmsStyle.value = st;
        cellAmsOpen.value = true;
    }
    const printAmsSlot = ref(null);                 // выбор для активного язычка (для отправки печати)
    // Bambu: обычный AMS = unit id 0..3 (по 4 лотка), дополнительный AMS HT = unit id >= 128 (один лоток,
    // глобальный index = unit*4 = 512). Признак HT — по РЕАЛЬНОМУ unit, а не по позиции/длине массива.
    const AMS_HT_MIN = 128;
    const amsIsHt = (u) => (u != null && Number(u) >= AMS_HT_MIN);
    // Группируем слоты AMS по физическому блоку (unit). Нумерация РАЗДЕЛЬНАЯ: обычные блоки → «AMS 1/2/…»
    // по порядку, а unit>=128 → «AMS HT» (НЕ порядковый «AMS 2» и НЕ «AMS 129» по id). Поля группы:
    // label — готовая подпись; ht — признак AMS HT; slots — реальные лотки (у HT ровно один, с настоящим index 512).
    //  Alpha 2.887: подписи к ряду CFS (Creality K2). Показ и только показ.
    const cfsTitle = (p) => {
        const pid = (p && typeof p === 'object') ? p.id : p;
        const units = (wsData.value[pid]?.cfs_units) || [];
        const parts = units.map((u) => {
            const bits = [];
            if (u.temp != null) bits.push(u.temp + '°C');
            if (u.humidity != null) bits.push(u.humidity + '%');
            return (lang.value === 'ru' ? 'короб ' : 'box ') + ((u.unit ?? 0) + 1)
                + (bits.length ? ' — ' + bits.join(', ') : '');
        });
        const head = lang.value === 'ru' ? 'CFS: система подачи катушек' : 'CFS: filament system';
        let out = parts.length ? head + ' · ' + parts.join(' · ') : head;
        //  Alpha 2.902: честно про неясность. Принтер сообщает, КАКОЙ материал заправлен, но не
        //  из какого слота. Если под это описание подходит несколько слотов — так и пишем, и
        //  списание филамента в этом случае не делается вовсе.
        const cands = wsData.value[pid]?.cfs_now_candidates || [];
        const trays = (wsData.value[pid]?.cfs_trays) || [];
        if ((wsData.value[pid]?.cfs_now ?? -1) < 0 && cands.length > 1) {
            const names = trays.filter((t) => cands.includes(t.index)).map((t) => t.label || ('#' + t.index));
            out += lang.value === 'ru'
                ? ' · какой слот заправлен — точно не известно: одинаковый материал в ' + names.join(' и ')
                  + '. Пока это так, филамент со слотов не списывается.'
                : ' · which slot is loaded is not known: the same filament sits in ' + names.join(' and ')
                  + '. While this holds, no filament is deducted from the slots.';
        }
        return out;
    };
    const cfsSlotTitle = (p, t) => {
        const pid = (p && typeof p === 'object') ? p.id : p;
        const empty = !t || !t.type || t.type === 'Empty';
        const n = (t && t.tray != null) ? (Number(t.tray) + 1) : '?';
        const unit = (t && t.unit != null) ? (Number(t.unit) + 1) : 1;
        const head = (t && t.label)
            ? ((lang.value === 'ru' ? 'Слот ' : 'Slot ') + t.label)
            : ((lang.value === 'ru' ? 'Короб ' : 'Box ') + unit + ', '
               + (lang.value === 'ru' ? 'слот ' : 'slot ') + n);
        if (empty) {
            //  Alpha 2.942: у опустевшего слота метка прежней катушки остаётся, и раньше он
            //  рисовался полным. Теперь он пуст — но человеку надо объяснить, почему он только
            //  что видел здесь материал, иначе это выглядит как потеря данных.
            const decl = t && t.declared;
            if (decl) {
                return head + ' — ' + (lang.value === 'ru'
                    ? 'пусто. Принтер помнит здесь ' + decl + ': метка осталась от прежней катушки, филамента в слоте нет'
                    : 'empty. The printer still remembers ' + decl + ' here: the label is left over from the previous spool, the slot holds no filament');
            }
            return head + ' — ' + (lang.value === 'ru' ? 'пусто' : 'empty');
        }
        const bits = [t.type];
        if (t.percent != null) bits.push(t.percent + '%');
        if (t.vendor && t.vendor !== 'unknown') bits.push(t.vendor);
        if (wsData.value[pid]?.cfs_now === t.index) {
            bits.push(lang.value === 'ru' ? 'подан' : 'loaded');
        } else if ((wsData.value[pid]?.cfs_now_candidates || []).includes(t.index)) {
            //  Alpha 2.902: в двух слотах один и тот же материал одного цвета — принтер сообщает
            //  только материал заправленного, а не его слот. Утверждать «подан» тут нельзя.
            bits.push(lang.value === 'ru' ? 'возможно, подан именно он' : 'possibly the loaded one');
        }
        return head + ' — ' + bits.join(', ');
    };

    const amsGroups = (p) => {
        const pid = (p && typeof p === 'object') ? p.id : p;
        const trays = (wsData.value[pid]?.ams_trays) || [];
        const order = []; const map = {};
        for (const t of trays) {
            const u = (t.unit == null ? 0 : Number(t.unit));
            if (!(u in map)) { map[u] = []; order.push(u); }
            map[u].push(t);
        }
        let regN = 0, htN = 0;
        return order.map((u) => {
            const ht = amsIsHt(u);
            let n, label;
            if (ht) { htN += 1; n = htN; label = 'AMS HT' + (htN > 1 ? ' ' + htN : ''); }
            else { regN += 1; n = regN; label = 'AMS ' + regN; }
            return { unit: u, n: n, ht: ht, label: label, slots: map[u] };
        });
    };
    const printerFiles = ref([]);
    const loadingFiles = ref(false);
    
    let pollInterval = null;
    let stagingInterval = null;
    let ws = null;
    let saveTimeout = null;

    const projectOrder = ref([]); 
    const sortKey = ref('');
    const sortDir = ref(1);
    const setSort = (key) => {
        if (sortKey.value === key) {
            if (sortDir.value === 1) { sortDir.value = -1; }
            else { sortKey.value = ''; sortDir.value = 1; }
        } else { sortKey.value = key; sortDir.value = 1; }
    };

    //  2.975: порядок статусов задач и деталей — один на всю программу. Сверху то, что идёт
    //  прямо сейчас, снизу — законченное: печатается -> готовится -> на паузе -> в работе ->
    //  ожидание -> готово. Раньше «Задачи» сортировались по внутреннему английскому слову
    //  (ready/printing/done) по алфавиту — то есть не по тому, что владелец видит в столбце.
    const _TASK_STATUS_ORDER = { printing: 0, preparing: 1, paused: 2, in_progress: 3, sending: 4, pending: 5, done: 6 };
    const sortParts = (arr) => {
        if (!sortKey.value) return arr;
        const k = sortKey.value, d = sortDir.value;
        const statusRank = _TASK_STATUS_ORDER;   // 2.975: тот же порядок, что и в «Задачах»
        return [...arr].sort((a, b) => {
            let va, vb;
            if (k === 'part_name') { va = (a.part_name || ''); vb = (b.part_name || ''); return va.localeCompare(vb, undefined, { numeric: true, sensitivity: 'base' }) * d; }
            if (k === 'status') {
                //  2.977 (R-098): как в задачах — по тому статусу, что ВИДЕН в строке: печатается
                //  сейчас (по живым принтерам) раньше «в работе», «ожидание» раньше «готово».
                va = statusRank[liveStatusKey(a.live_printers, p2PartOwnKey(a))] ?? 9;
                vb = statusRank[liveStatusKey(b.live_printers, p2PartOwnKey(b))] ?? 9;
                if (va !== vb) return (va - vb) * d;
                return String(a.part_name || '').localeCompare(String(b.part_name || ''), undefined, { numeric: true, sensitivity: 'base' });
            }
            va = Number(a[k]) || 0; vb = Number(b[k]) || 0;
            return (va - vb) * d;
        });
    };

    // Сортировка Задач по клику на заголовки столбцов (отдельное состояние,
    // чтобы не пересекаться с сортировкой деталей в проектах).
    const stSortKey = ref('');
    const stSortDir = ref(1);
    const setStSort = (key) => {
        if (stSortKey.value === key) {
            if (stSortDir.value === 1) { stSortDir.value = -1; }
            else { stSortKey.value = ''; stSortDir.value = 1; }
        } else { stSortKey.value = key; stSortDir.value = 1; }
    };
    const sortStaging = (arr) => {
        if (!stSortKey.value) return arr;
        const k = stSortKey.value, d = stSortDir.value;
        return [...arr].sort((a, b) => {
            if (k === 'filename') { return (a.filename || '').localeCompare(b.filename || '', undefined, { numeric: true, sensitivity: 'base' }) * d; }
            if (k === 'status') {
                //  Сравниваем ПОКАЗАННЫЙ статус (он же живой), а не поле из базы.
                const ra = _TASK_STATUS_ORDER[stagingStatusKey(a)];
                const rb = _TASK_STATUS_ORDER[stagingStatusKey(b)];
                const va = ra === undefined ? 9 : ra, vb = rb === undefined ? 9 : rb;
                if (va !== vb) return (va - vb) * d;
                return (a.filename || '').localeCompare(b.filename || '', undefined, { numeric: true, sensitivity: 'base' });
            }
            const va = Number(a[k]) || 0, vb = Number(b[k]) || 0;
            return (va - vb) * d;
        });
    };
    // Поиск по имени файла в «Задачах»: фильтр применяется ПЕРЕД sortStaging в обоих видах
    // (десктоп/мобайл). Пустой запрос возвращает исходный массив — поведение без изменений.
    const stSearch = ref('');
    const filterStaging = (arr) => {
        const q = String(stSearch.value || '').trim().toLowerCase();
        if (!q) return arr;
        return (arr || []).filter(f => String((f && f.filename) || '').toLowerCase().includes(q));
    };
    // Сводка «Задач»: суммарно «нужно»/«напечатано» по всем задачам — только для показа в шапке (read-only).
    //  Alpha 2.893: прогресс ОДНОЙ задачи. Учитывается и то, что печатается прямо сейчас:
    //  человеку важно видеть, что остаток уже в работе, а не «ничего не сделано».
    //  Проценты считаются от «нужно»; если нужно 0 — прогресса нет, а не «деление на ноль».
    const stagingProgress = (f) => {
        const req = Math.max(0, Number(f && f.required_qty) || 0);
        const done = Math.max(0, Number(f && f.printed_qty) || 0);
        const live = Math.max(0, Number(liveStagingPrintingQty(f)) || 0);
        if (!req) return { req: 0, done, live, pct: 0, livePct: 0, left: 0, complete: done > 0 };
        const pct = Math.min(100, Math.round((done / req) * 100));
        const livePct = Math.min(100 - pct, Math.round((live / req) * 100));
        return { req, done, live, pct, livePct, left: Math.max(0, req - done), complete: done >= req };
    };
    //  Подпись к полосе: коротко и без жаргона.
    const stagingProgressText = (f) => {
        const p = stagingProgress(f);
        if (!p.req) return '';
        const base = p.done + ' ' + tr('of') + ' ' + p.req + ' · ' + p.pct + '%';
        return p.live ? (base + ' · +' + p.live + ' ' + tr('printing now')) : base;
    };

    const stagingTotals = computed(() => {
        let req = 0, prnt = 0;
        for (const f of (stagingFiles.value || [])) { req += Number(f.required_qty) || 0; prnt += Number(f.printed_qty) || 0; }
        //  Alpha 2.893: та же сводка, но с процентом — чтобы общий ход работы был виден сразу.
        const pct = req ? Math.min(100, Math.round((prnt / req) * 100)) : 0;
        return { req, prnt, pct, left: Math.max(0, req - prnt) };
    });
    // Фильтр «Задач» по статусу: 'all' | 'active' (не готовые) | 'done' (готовые). Применяется ПОСЛЕ
    // поиска (filterStaging) и ПЕРЕД sortStaging; 'all' = поведение без изменений.
    const stStatus = ref('all');
    const filterStagingView = (arr) => {
        const base = filterStaging(arr);
        if (stStatus.value === 'all') return base;
        //  Alpha 2.895: отдельный отбор «с проблемами» — чтобы беду было видно одной кнопкой,
        //  а не поиском глазами по всему списку.
        if (stStatus.value === 'problem') return base.filter(f => stagingProblems(f).length > 0);   // кнопка живёт, пока отбор включён — см. разметку
        return base.filter(f => (stagingStatusKey(f) === 'done') === (stStatus.value === 'done'));
    };

    //  Alpha 2.896: группировка задач. Своей связи с проектом у задач нет и не заводится — это
    //  меняло бы схему базы. Сервер выводит связь ТОЧНЫМ совпадением файла (тот же путь или то же
    //  имя) и при спорном совпадении не выводит ничего. Второй способ — по папке, из которой файл
    //  добавлен: на ферме папка обычно и есть заказ. Группировка — только показ: порядок печати,
    //  очередь и подсчёты она не трогает.
    const ST_GROUPS = ['none', 'project', 'folder'];
    const stGroup = ref('none');
    try { const _g0 = localStorage.getItem('farm_st_group'); if (ST_GROUPS.includes(_g0)) stGroup.value = _g0; } catch (e) {}
    const setStGroup = (v) => {
        if (!ST_GROUPS.includes(v)) return;
        if (v === 'folder' && !stagingFolderKnown.value) return;   // способа нет — и выбрать его нельзя
        stGroup.value = v;
        try { localStorage.setItem('farm_st_group', v); } catch (e) {}
    };
    const stGroupClosed = ref({});
    const toggleStGroup = (key) => {
        stGroupClosed.value = { ...stGroupClosed.value, [key]: !stGroupClosed.value[key] };
    };
    //  Папка файла: путь без имени. Разделители у Windows и у настроек разные, поэтому приводим
    //  к одному виду. Файл без пути (задача создана не перетаскиванием) папки не имеет.
    //  Alpha 2.900. ИЗМЕРЕНО: сервер кладёт задачам src_path='' намеренно — файл копируется в
    //  папку программы, и путь, откуда его взяли, не хранится (server.py, «managed»). Значит
    //  группировать по папке сегодня НЕ ПО ЧЕМУ: все задачи попали бы в одну «Без папки».
    //  Поэтому способ показывается, только если путь у задач реально есть. Появится — вернётся сам.
    const stagingFolderKnown = computed(() =>
        (stagingFiles.value || []).some(f => f && String(f.src_path || '').trim()));
    const stagingFolder = (f) => {
        const p = String((f && f.src_path) || '').replace(/\\/g, '/');
        const i = p.lastIndexOf('/');
        return i > 0 ? p.slice(0, i) : '';
    };
    //  Русское склонение числа задач: 1 задача, 2 задачи, 5 задач, 11 задач, 21 задача.
    //  Подстановка одного слова через словарь тут не годится — форма зависит от числа.
    const tasksWord = (n) => {
        const k = Math.abs(Number(n) || 0);
        if (lang.value !== 'ru') return k === 1 ? 'task' : 'tasks';
        const t = k % 10, h = k % 100;
        if (t === 1 && h !== 11) return 'задача';
        if (t >= 2 && t <= 4 && (h < 12 || h > 14)) return 'задачи';
        return 'задач';
    };
    const stagingViewGroups = computed(() => {
        const list = sortStaging(filterStagingView(stagingFiles.value || []));
        //  Без группировки список остаётся ровно тем же — одна безымянная группа без заголовка.
        //  Сюда же попадаем, если выбран способ «по папке», а путей у задач нет вовсе.
        if (stGroup.value === 'none' || (stGroup.value === 'folder' && !stagingFolderKnown.value)) {
            return [{ key: '__all', title: '', sub: '', files: list, closed: false, req: 0, prnt: 0, pct: 0 }];
        }
        const byKey = new Map();
        for (const f of list) {
            let key = '', title = '', sub = '';
            if (stGroup.value === 'project') {
                key = String(f.project_id || '');
                title = String(f.project_name || '');
            } else {
                sub = stagingFolder(f);
                key = sub.toLowerCase();
                title = sub ? sub.split('/').filter(Boolean).pop() : '';
            }
            if (!key || !title) {
                //  Ключ свой у каждого режима: «Вне проектов» и «Без папки» — разные группы, и
                //  свёрнутость одной не должна перетекать на другую.
                key = '__none:' + stGroup.value;
                title = tr(stGroup.value === 'project' ? 'Outside projects' : 'No folder');
                sub = '';
            }
            if (!byKey.has(key)) byKey.set(key, { key, title, sub, files: [] });
            byKey.get(key).files.push(f);
        }
        const arr = [...byKey.values()];
        //  «Вне проектов» / «Без папки» всегда последними: это остаток, а не равноправная группа.
        arr.sort((a, b) => ((a.key.indexOf('__none') === 0) - (b.key.indexOf('__none') === 0))
            || String(a.title).localeCompare(String(b.title), undefined, { numeric: true, sensitivity: 'base' }));
        for (const g of arr) {
            let req = 0, prnt = 0;
            for (const f of g.files) { req += Number(f.required_qty) || 0; prnt += Number(f.printed_qty) || 0; }
            g.req = req;
            g.prnt = prnt;
            g.pct = req ? Math.min(100, Math.round((prnt / req) * 100)) : 0;
            g.closed = !!stGroupClosed.value[g.key];
        }
        return arr;
    });

    // Сортировка карточек проектов: по имени (А-Я) или по дате добавления (новые сверху).
    const projSort = ref('date');
    try { const _ps2 = localStorage.getItem('farm_proj_sort'); if (_ps2 === 'name' || _ps2 === 'date') projSort.value = _ps2; } catch(e) {}
    const setProjSort = (v) => { projSort.value = v; try { localStorage.setItem('farm_proj_sort', v); } catch(e) {} };
    const sortedProjects2 = computed(() => {
        const arr = [...projects2.value];
        if (projSort.value === 'name') { arr.sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true, sensitivity: 'base' })); }
        else { arr.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))); }
        return arr;
    });
    // Поиск по имени проекта: клиентский фильтр применяется ПОВЕРХ sortedProjects2 в обоих видах
    // (сетка карточек и раскрытые панели). Пустой запрос возвращает исходный массив — без изменений.
    const projSearch = ref('');
    const filterProjects = (arr) => {
        const q = String(projSearch.value || '').trim().toLowerCase();
        if (!q) return arr;
        return (arr || []).filter(p => String((p && p.name) || '').toLowerCase().includes(q));
    };

    // ------------------------------------------------------------------------
    // БЛОК: представление производственного плана.
    // Группировка деталей по проектам, расчёт итогов, сортировка и анимация
    // раскрытия/сворачивания панели проекта.
    // ------------------------------------------------------------------------
    const toggleStagingParts = fn => expandedStaging.value[fn] = !expandedStaging.value[fn];
    // Развернуть / свернуть все файлы Задач разом (как у проектов).
    const stagingExpandAll = () => { const m = { ...expandedStaging.value }; (stagingFiles.value || []).forEach(f => { m[f.filename] = true; }); expandedStaging.value = m; };
    const stagingCollapseAll = () => { const m = { ...expandedStaging.value }; (stagingFiles.value || []).forEach(f => { m[f.filename] = false; }); expandedStaging.value = m; };
    // Tasks: каждая строка раскрывается независимо; одновременно можно открыть несколько файлов.
    const openPlan = ref(null);
    
    const printerSort = ref('status');
    try { const _ps = localStorage.getItem('farm_psort'); if (_ps === 'name' || _ps === 'status') printerSort.value = _ps; } catch(e) {}
    const setPrinterSort = (v) => { printerSort.value = v; try { localStorage.setItem('farm_psort', v); } catch(e) {} };
    // ── Alpha 2.866: направление сортировки принтеров (asc|desc), localStorage. ──
    // Второй клик по уже активному пункту меню переворачивает порядок ЦЕЛИКОМ: и группы
    // (статусы / модели), и имена внутри них. Влияет только на показ, не на очередь и печать.
    const printerSortDir = ref('asc');
    try { const _pd = localStorage.getItem('farm_psort_dir'); if (_pd === 'asc' || _pd === 'desc') printerSortDir.value = _pd; } catch(e) {}
    const setPrinterSortDir = (v) => { printerSortDir.value = v; try { localStorage.setItem('farm_psort_dir', v); } catch(e) {} };
    //  2.975: сортировка «по статусу» выстроена ЛЕСТНИЦЕЙ по срочности, а не тремя кучами.
    //  Раньше беда, пауза и «печать закончена» лежали в одной куче со свободными принтерами —
    //  то есть именно то, ради чего сортировку и включают, наверх не поднималось.
    //  Порядок: беда -> пауза -> печать закончена (снять деталь) -> печатает -> готовится ->
    //  свободен -> офлайн. Внутри ступени — по имени.
    const _PRINTER_STATUS_ORDER = {
        FAILED: 0, ERROR: 0, ATTENTION: 0,
        PAUSED: 1, PAUSE: 1,
        FINISH: 2,
        RUNNING: 3,
        PREPARE: 4, SLICING: 4, BUSY: 4,
        IDLE: 5, READY: 5, STANDBY: 5, OPERATIONAL: 5,
        OFFLINE: 6,
    };
    const _statusRank = (id) => {
        const s = String((wsData.value[id] || {}).status || 'OFFLINE').toUpperCase();
        const r = _PRINTER_STATUS_ORDER[s];
        return r === undefined ? 5 : r;   // незнакомый статус — к свободным, а не в конец списка
    };
    const _byPrinterName = (a, b) => String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true, sensitivity: 'base' });
    // ── Alpha 2.831: режим сортировки принтеров (manual|model), СЕРВЕРНАЯ настройка (в backup). ──
    // 'manual' = прежнее поведение (по статусу/имени через printerSort, localStorage).
    // 'model'  = группировка по модели (natural sort по имени, неизвестные модели в конце).
    // Только ВИЗУАЛЬНЫЙ порядок: физический order_idx, очередь, dispatch и печать НЕ меняются.
    const printerSortMode = ref('manual');
    const loadPrinterSortMode = async () => {
        try { const r = await fetch('/api/printer-sort-mode', { cache: 'no-store' });
              if (r.ok) { const j = await r.json(); if (j && (j.printer_sort_mode === 'manual' || j.printer_sort_mode === 'model')) printerSortMode.value = j.printer_sort_mode; } } catch (e) {}
    };
    const setPrinterSortMode = async (v) => {
        if (v !== 'manual' && v !== 'model') return;
        printerSortMode.value = v;                       // оптимистично: список перестраивается сразу
        try { await fetch('/api/printer-sort-mode', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ printer_sort_mode: v }) }); } catch (e) {}
    };
    // Нормализованное display-имя модели из registry (без зависимости от регистра); неизвестная/
    // пользовательская модель -> её сырое имя (запись НЕ теряется).
    const _printerModelDisplay = (p) => {
        const raw = String((p && p.model) || '').trim();
        if (!raw) return '';
        const k = _normModelKey(raw);
        const hit = printerModels.value.find(m => (m.model_key ? m.model_key === k : m.name === raw));
        return hit ? hit.name : raw;
    };
    const _byPrinterModelThenName = (a, b) => {
        const ma = _printerModelDisplay(a), mb = _printerModelDisplay(b);
        const ua = !ma, ub = !mb;                        // пустая/неизвестная модель — ПОСЛЕ известных
        if (ua !== ub) return ua ? 1 : -1;
        const mc = String(ma).localeCompare(String(mb), undefined, { numeric: true, sensitivity: 'base' });
        if (mc !== 0) return mc;
        const nc = _byPrinterName(a, b);                 // внутри модели — natural sort по имени (X2<X10)
        if (nc !== 0) return nc;
        return String(a.id || '').localeCompare(String(b.id || ''));   // стабильный tie-break по ID
    };
    // Активный ключ сортировки одним значением: 'model' хранится серверной настройкой
    // (printerSortMode), 'status'/'name' — локальной (printerSort). Меню показывает их
    // плоским списком из трёх пунктов.
    const printerSortKey = computed(() => printerSortMode.value === 'model' ? 'model' : printerSort.value);
    const printerSortLabel = computed(() => printerSortKey.value === 'model' ? tr('By model')
                                          : printerSortKey.value === 'name' ? tr('By name') : tr('By status'));
    //  R-107 (2.985): состояние карточки дашборда — одно слово из шести. Ошибки и внимание
    //  (в т. ч. серьёзное оповещение), пауза, «печать завершена — освободите стол», печатает,
    //  свободен, не в сети. Из него же берётся порядок по умолчанию: важное — первым;
    //  печатающие — по ближайшему завершению.
    const _DASH_RANK = { error: 0, paused: 1, done: 2, print: 3, busy: 3, idle: 4, offline: 5 };
    const dashState = (pid) => {
        const s = (wsData.value && wsData.value[pid]) || {};
        const st = String(s.status || 'OFFLINE').toUpperCase();
        if (st === 'OFFLINE') return 'offline';
        const a = cardTopAlert(pid);
        if (st === 'FAILED' || st === 'ERROR' || st === 'ATTENTION'
            || (a && (a.top.severity === 'critical' || a.top.severity === 'error'))) return 'error';
        if (st === 'PAUSED' || st === 'PAUSE') return 'paused';
        if (st === 'FINISH') return 'done';
        if (st === 'RUNNING' || st === 'PREPARE' || st === 'SLICING') return 'print';
        //  12.10.2026: «Занят» (BUSY — калибровка, незнакомое состояние прошивки) — не «Свободен».
        if (st === 'BUSY') return 'busy';
        return 'idle';
    };
    const _dashCmp = (a, b) => {
        const sa = dashState(a.id), sb = dashState(b.id);
        const r = (_DASH_RANK[sa] ?? 4) - (_DASH_RANK[sb] ?? 4);
        if (r) return r;
        if (sa === 'print') {
            const ra = Number((wsData.value[a.id] || {}).remaining_time) || 1e9;
            const rb = Number((wsData.value[b.id] || {}).remaining_time) || 1e9;
            if (ra !== rb) return ra - rb;               // ближайшее завершение — первым
        }
        return _byPrinterName(a, b);
    };
    const dashPct = (pid) => Math.round(Math.max(0, Math.min(100, Number((wsData.value[pid] || {}).percent) || 0)));
    const dashEta = (pid) => { const m = Number((wsData.value[pid] || {}).remaining_time) || 0; return m > 0 ? convertSecondsToReadable(m * 60) : ''; };
    const dashStateText = (pid) => {
        const k = dashState(pid);
        if (k === 'error') { const a = cardTopAlert(pid); return (a && a.top && a.top.title) ? a.top.title : tr('Needs attention'); }
        if (k === 'print') { const st = String((wsData.value[pid] || {}).status || '').toUpperCase(); return st === 'RUNNING' ? tr('Printing') : tr('Preparing'); }
        return ({ paused: tr('Paused'), done: tr('Print finished'), busy: tr('Busy'), idle: tr('Free'), offline: tr('Offline') })[k] || '';
    };
    const sortedPrinters = computed(() => {
        const arr = [...printers.value];
        const cmp = printerSortKey.value === 'model' ? _byPrinterModelThenName
                  : printerSortKey.value === 'name' ? _byPrinterName
                  : (viewMode.value === 'dash' ? _dashCmp
                     : (a, b) => _statusRank(a.id) - _statusRank(b.id) || _byPrinterName(a, b));
        const sign = printerSortDir.value === 'desc' ? -1 : 1;
        arr.sort((a, b) => sign * cmp(a, b));   // возвращается СТРОГО массив принтеров
        return arr;
    });
    // Заголовки групп моделей (ТОЛЬКО в режиме model): показываются перед первым принтером группы.
    const _modelGroupKey = (p) => _printerModelDisplay(p) || (lang.value === 'ru' ? 'Без модели' : 'No model');
    const modelHeaderBefore = (pidx) => {
        if (printerSortMode.value !== 'model') return false;
        const list = visiblePrinters.value;
        if (pidx <= 0) return true;
        return _modelGroupKey(list[pidx]) !== _modelGroupKey(list[pidx - 1]);
    };
    const modelHeaderLabel = (pidx) => {
        const list = visiblePrinters.value; const g = _modelGroupKey(list[pidx]);
        const n = list.filter(x => _modelGroupKey(x) === g).length;
        return g + ' · ' + n;
    };
    // Меню «Сортировка» у заголовка ПРИНТЕРЫ (teleport в body, поверх оверлеев).
    const printerSortMenu = ref({ show: false, x: 0, y: 0 });
    const openPrinterSortMenu = (e) => {
        try { const r = (e.currentTarget || e.target).getBoundingClientRect();
              printerSortMenu.value = { show: true, x: Math.round(r.left), y: Math.round(r.bottom + 4) }; }
        catch (_) { printerSortMenu.value = { show: true, x: 8, y: 64 }; }
    };
    const closePrinterSortMenu = () => { printerSortMenu.value = { show: false, x: 0, y: 0 }; };
    // Клик по пункту: другой ключ — сортировка по нему по возрастанию; повторный клик по
    // активному — обратный порядок. Меню НЕ закрывается, чтобы второй клик делался сразу;
    // закрывается кликом мимо (подложка) — список за меню перестраивается на глазах.
    const pickPrinterSortKey = (k) => {
        if (k !== 'status' && k !== 'name' && k !== 'model') return;
        if (printerSortKey.value === k) { setPrinterSortDir(printerSortDir.value === 'asc' ? 'desc' : 'asc'); return; }
        setPrinterSortDir('asc');
        if (k === 'model') setPrinterSortMode('model');
        else { setPrinterSortMode('manual'); setPrinterSort(k); }
    };
    const spotlight = ref([]);
    const spotlightRow = ref('');
    const enterSpotlight = (ids, rowId) => { const a = (ids || []).filter(Boolean); if (a.length) { spotlight.value = a; spotlightRow.value = rowId || ''; } };
    const printSpotlightCtx = ref(null);   // когда задан — колонка принтеров = выбор принтера для печати этого файла
    const printSel = ref([]);              // 🔒 ОТЛАЖЕНО — мультивыбор принтеров в режиме печати (клик по карточке = выбрать/снять, не печатать сразу). Сбрасывается при входе/выходе из режима. Не менять без перепроверки.
    const _printerNameOf = (pid) => { const p = (printers.value || []).find((x) => x.id === pid); return (p && p.name) || pid; };
    // Alpha 2.728: прежний БЛОКИРУЮЩИЙ store прямых/пакетных отправок (printSending / sendJobs / beginSendJob…)
    // и его .ps-overlay удалены. Панель отправок теперь server-driven и немодальная (см. блок ниже:
    // sendJobsSrv / sendReserved / sendJobsView / handleSendResp / dismissSendJob / startSendPoll).
    // ═══ Alpha 2.728: НЕБЛОКИРУЮЩАЯ панель фоновых отправок — server-driven (GET /api/send-jobs) + оптимистичное
    // добавление сразу после accepted. Никаких overlay/backdrop: пользователь продолжает работать во всех разделах. ═══
    const SEND_TERMINAL = ['completed', 'failed'];
    const SEND_DONE_SHOW_S = 10;                 // completed видно в панели столько секунд (сервер хранит их час — для телефона)
    const sendJobsSrv = ref([]);                 // авторитетный снимок с сервера
    const sendReserved = ref(new Set());         // reserved_printer_ids (для скрытия принтеров из «Доступных»)
    const sendOptimistic = ref([]);              // локально добавленные строки до подтверждения сервером
    let _sendOptSeq = 0, _sendPollTimer = null;
    const addOptimisticJob = (o) => {
        sendOptimistic.value = sendOptimistic.value.concat([{ job_id: o.job_id || ('opt' + (++_sendOptSeq)), printer_id: o.printer_id, printer_name: o.printer_name || o.printer_id, file_name: o.file_name || '', source: o.source || '', state: 'queued', progress: null, bytes_sent: null, bytes_total: null, error: null, created_at: Date.now() / 1000, _opt: true }]);
    };
    const sendJobsView = computed(() => {
        const srv = sendJobsSrv.value || [];
        const ids = new Set(srv.map((j) => j.job_id));
        const opt = (sendOptimistic.value || []).filter((o) => !ids.has(o.job_id));
        return srv.concat(opt).slice().sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
    });
    const sendActiveCount = computed(() => sendJobsView.value.filter((j) => SEND_TERMINAL.indexOf(j.state) < 0).length);
    const fetchSendJobs = async () => {
        try {
            const r = await fetch('/api/send-jobs');
            if (!r.ok) return;
            const d = await r.json();
            const all = Array.isArray(d.jobs) ? d.jobs : [];
            //  10.10.2026: сервер держит completed час (телефону), панель показывает их, как прежде, 10 с.
            const now = Number(d.server_time) || (Date.now() / 1000);
            sendJobsSrv.value = all.filter((j) => {
                if (!j || j.state !== 'completed') return true;
                const t = Number(j.updated_at);   // без времени завершения — не прячем (как до 10.10.2026)
                return !(Number.isFinite(t) && t > 0 && now - t > SEND_DONE_SHOW_S);
            });
            sendReserved.value = new Set(d.reserved_printer_ids || []);
            const ids = new Set(all.map((j) => j.job_id));
            if ((sendOptimistic.value || []).some((o) => ids.has(o.job_id))) sendOptimistic.value = sendOptimistic.value.filter((o) => !ids.has(o.job_id));
        } catch (e) {}
    };
    const _sendScheduleNext = () => { const fast = sendActiveCount.value > 0 || (sendOptimistic.value || []).length > 0; _sendPollTimer = setTimeout(_sendPollLoop, fast ? 1200 : 3500); };
    const _sendPollLoop = async () => { await fetchSendJobs(); _sendScheduleNext(); };
    const startSendPoll = () => { if (_sendPollTimer) return; _sendPollLoop(); };
    const dismissSendJob = async (job_id) => {
        if (!job_id || String(job_id).indexOf('opt') === 0) { sendOptimistic.value = sendOptimistic.value.filter((o) => o.job_id !== job_id); return; }
        try { await fetch('/api/send-jobs/' + encodeURIComponent(job_id) + '/dismiss', { method: 'POST' }); } catch (e) {}
        sendJobsSrv.value = sendJobsSrv.value.filter((j) => j.job_id !== job_id);
    };
    const sendStateLabel = (st) => {
        // Alpha 2.838: у Klipper-подготовки появились СВОИ стадии — пользователь должен видеть,
        // что калибровка идёт и что файл ещё не отправлен, а не гадать по молчащему индикатору.
        // Alpha 2.840: подготовка стола перестала быть одной немой строкой. Пользователь видит,
        // на каком шаге он находится: чтение конфигурации, состояние принтера, парковка, сама
        // калибровка, проверка сетки. Печать при этом ещё НЕ началась — файл уходит последним.
        const ru = { queued: 'Ожидает отправки', preparing: 'Подготовка принтера…', checking_state: 'Проверка состояния принтера…', resolving: 'Проверка конфигурации принтера…', homing: 'Парковка осей…', calibrating: 'Калибровка стола…', awaiting_calibration: 'Ожидание завершения калибровки…', verifying: 'Проверка сетки стола…', calibration_done: 'Калибровка завершена', uploading: 'Отправка на принтер…', starting_file: 'Запуск файла…', sending_command: 'Отправка команды…', waiting_confirmation: 'Ожидание подтверждения принтера…', completed: 'Готово', failed: 'Ошибка' };
        const en = { queued: 'Waiting to send', preparing: 'Preparing the printer…', checking_state: 'Checking the printer state…', resolving: 'Reading the printer configuration…', homing: 'Homing the axes…', calibrating: 'Bed mesh calibration…', awaiting_calibration: 'Waiting for calibration to finish…', verifying: 'Verifying the bed mesh…', calibration_done: 'Calibration finished', uploading: 'Sending to printer…', starting_file: 'Starting the file…', sending_command: 'Sending command…', waiting_confirmation: 'Waiting for printer confirmation…', completed: 'Done', failed: 'Error' };
        return (lang.value === 'ru' ? ru : en)[st] || st;
    };
    // Alpha 2.833: человеческий текст ошибки отправки. Код start_not_confirmed (watchdog: команда
    // отправлена, но принтер устойчиво в покое) НЕ утверждает «печать не запущена» — только то,
    // что подтвердить запуск не удалось; пользователь проверяет принтер перед повторной отправкой.
    const sendErrLabel = (j) => {
        const e = String((j && j.error) || '');
        if (e === 'start_not_confirmed') return lang.value === 'ru'
            ? 'Не удалось подтвердить запуск. Проверьте состояние принтера перед повторной отправкой.'
            : 'Could not confirm the start. Check the printer before sending again.';
        return e || (lang.value === 'ru' ? 'Ошибка отправки' : 'Send error');
    };
    const sendIsTerminal = (st) => SEND_TERMINAL.indexOf(st) >= 0;
    // Alpha 2.728: ячейка принтера «занята» для запуска, если печатает (RUNNING) ИЛИ идёт фоновая отправка (reserved).
    const cellBusy = (pid) => ['RUNNING', 'PREPARE', 'PAUSED', 'PAUSE', 'SLICING', 'BUSY'].includes(wsData.value[pid]?.status) || sendReserved.value.has(pid);
    // Разбор ответа запуска: accepted → оптимистичная строка; 409 printer_send_busy → тост; иначе — вызывающему.
    const handleSendResp = (resp, ctx) => {
        if (resp && resp.accepted) { addOptimisticJob({ job_id: resp.job_id, printer_id: ctx.printer_id, printer_name: ctx.printer_name, file_name: ctx.file_name, source: ctx.source }); fetchSendJobs(); return 'accepted'; }
        if (resp && resp.error === 'printer_send_busy') { pushToast(lang.value === 'ru' ? 'Принтер уже отправляет файл' : 'The printer is already sending a file', 'info'); return 'busy'; }
        return 'other';
    };
    //  15.09.2026 (заказ владельца): строка файла ОБЯЗАНА измениться сразу после запуска, а не когда
    //  принтер подтвердит старт. Иначе при запуске десяти файлов подряд не видно, какие уже пошли,
    //  и тот же файл легко запустить второй раз. Источник — панель отправок (те же job'ы: снимок
    //  сервера + оптимистичная строка, добавленная в момент accepted): по файлу идёт отправка —
    //  строка показывает «Отправка». Завершённый job ещё ~10 с висит в панели — держим «Отправка»,
    //  пока статус задачи не догонит (база и живой статус принтера приходят с задержкой до 4 с).
    //  Ошибка отправки — строка возвращается в «ожидание», причина видна в панели отправок.
    //  Имена сравниваются тем же правилом, что и «кто печатает этот файл» (_normName/_bareName).
    const fileSendState = (filename) => {
        const target = _normName(_bareName(filename));
        if (!target) return '';
        let done = '';
        const now = Date.now() / 1000;
        for (const j of (sendJobsView.value || [])) {
            if (!j || j.state === 'failed' || _normName(_bareName(j.file_name)) !== target) continue;
            //  Оптимистичная строка живёт до первого снимка сервера; если снимок её так и не
            //  подтвердил (сервер перезапущен), через минуту она статус больше не держит.
            if (j._opt && now - (Number(j.created_at) || 0) > 60) continue;
            if (j.state !== 'completed') return j.state || 'queued';
            done = 'completed';
        }
        return done;
    };
    //  Имя файла проекта по id — для оптимистичной строки отправки (сервер знает имя, но его снимок
    //  приходит следующим опросом; строка проекта должна показать «Отправка» сразу).
    const _p2FileNameOf = (pid, fileId) => {
        const fid = String(fileId || '');
        if (!pid || !fid) return '';
        const t = project2Trees.value[pid];
        for (const n of ((t && t.nodes) || [])) if (n && String(n.file_id || n.id || '') === fid) return n.filename || n.name || '';
        for (const pp of ((((project2Parts.value || {})[pid]) || {}).parts || []))
            for (const pl of ((pp && pp.plates) || [])) if (pl && String(pl.file_id || '') === fid) return pl.filename || '';
        return '';
    };
    const exitSpotlight = () => { spotlight.value = []; spotlightRow.value = ''; printSpotlightCtx.value = null; printSel.value = []; };
    // ЕДИНЫЙ сценарий кнопки печати (Проекты и Задачи): кнопка «Выбрать принтер» подсвечивает
    // ТОЛЬКО совместимые принтеры; клик по карточке принтера ВЫДЕЛЯЕТ его (можно выбрать несколько),
    // печать НЕ стартует. Когда выбран ≥1 принтер, кнопка превращается в «Запустить на печать» —
    // по ней уходит пакетная отправка на все выбранные с прогрессом.
    const enterPrintSpotlight = (ctx, fileArg) => {
        const compat = compatiblePrintersFor(fileArg);
        //  Это сообщение — про положение дел в моменте. Освободился подходящий принтер —
        //  оно больше ни о чём, и панель убирает его сама.
        if (!compat.length) {
            pushToast(tr('No compatible idle printers.'), 'info', null,
                      { stale: () => compatiblePrintersFor(fileArg).length > 0 });
            return;
        }
        printSel.value = [];                                // новый выбор — сбрасываем прошлый
        if (queuePickMode.value) {                          // отметка для очереди уступает печати
            queuePickMode.value = false;
            document.documentElement.classList.remove('ui3-qpick-on');
        }
        printSpotlightCtx.value = ctx;
        enterSpotlight(compat.map(p => p.id), (ctx && ctx.rowKey) || '');
        if (isMobile.value) mobileTab.value = 'printers';   // на телефоне переключаемся на колонку принтеров
    };
    const onPrinterCardClick = (p, ev) => {
        const ctx = printSpotlightCtx.value;
        if (ui3Mode && queuePickMode.value && !ctx) {   // режим отметки для очереди
            queueSetAllowed(p.id, !queueIsAllowed(p.id));
        } else if (ctx) {                                          // режим печати: клик = выбрать/снять принтер (НЕ печатать сразу)
            const i = printSel.value.indexOf(p.id);
            if (i >= 0) printSel.value.splice(i, 1); else printSel.value.push(p.id);
        } else if (ui3Mode) {                               // оформление 3.0: пульт справа
            //  2.949: принтер мог быть подсвечен со строки задачи («показать принтер»). Пульт
            //  открывается справа, ПОД затемняющим слоем — и выглядел размытым. Снимаем подсветку
            //  до открытия: человек уже нашёл принтер, дальше ему нужен чёткий пульт.
            if (spotlight.value.length) exitSpotlight();
            ui3SelectPrinter(p, ev);
        } else { openModal(p.id, ev); }                     // обычный режим: открыть карточку
    };
    // активна ли кнопка запуска для данной строки (этот файл в режиме выбора И выбран хотя бы один принтер)
    const printBtnActive = (rowKey) => !!(printSpotlightCtx.value && spotlightRow.value === rowKey && printSel.value.length);
    //  15.09.2026: второй аргумент — имя файла строки; пока по нему идёт отправка, кнопка говорит об
    //  этом сама («Отправка…»), а не зовёт выбрать принтер заново.
    const printBtnLabel = (rowKey, filename) => printBtnActive(rowKey) ? ('▶ ' + tr('Start printing')) : ((filename && fileSendState(filename)) ? tr('Sending…') : tr('Select printer'));
    // ── Alpha 2.848: склад и запуск печати ──────────────────────────────────────────────
    // Согласованный сценарий: учёт сам решает, что может (впритык — пропускаем с уведомлением;
    // катушка кончилась, а такая же есть на складе — меняет её и уведомляет), и спрашивает
    // человека ТОЛЬКО когда заменить нечем. Вопрос при этом не «разрешаешь печатать», а «что
    // стоит на принтере»: ответ чинит учёт и снимает препятствие одним действием.
    // Alpha 2.850: третий ответ — «Печатать всё равно». Нужен там, где заменить нечем физически
    // (материал кончился в слоте AMS либо у слота нет карточки катушки): раньше в этом случае
    // оставалось только «Пропустить принтер», и цепочка запусков рвалась. Кнопка не голая —
    // вместе с запуском она списывает остаток в ноль и оставляет строку в журнале склада,
    // поэтому учёт не остаётся сломанным молча.
    const filDecision = ref({ open: false, rows: [], busy: '', confirm: '' });
    const _filPending = ref({ items: {}, interval: 60 });

    const filShort = (n) => ((n && (n.resolved || n.tight) || [])[0]) || {};
    const filMat = (sh) => ((sh.material || '') + ' ' + (sh.color_name || '')).trim() || tr('the spool');
    // Текст уведомления: что склад сделал сам. Без жаргона — владелец не программист.
    const filNoteText = (n) => {
        const who = n.printer_name || n.printer_id || '';
        const sh = filShort(n);
        // 16.10.2026 (R-151): модуль не ответил вовремя (или упал, или без лицензии) — печать
        // запущена без его проверки. Раньше любое незнакомое уведомление читалось как «на исходе».
        if (n.kind === 'check_unavailable') {
            const ru = lang.value === 'ru';
            // Имя модуля — на языке интерфейса: сначала из списка модулей, затем из уведомления
            // (сервер шлёт оба имени), иначе в английском окне стояло русское название.
            const mi = (installedModules.value || []).find(m => m && m.id === n.module_id) || {};
            const mod = mi[ru ? 'ru' : 'en'] || (ru ? n.module_name : (n.module_name_en || n.module_name)) || n.module_id || '';
            const why = n.reason === 'license'
                ? (ru ? ' работает без действующей лицензии' : ' has no valid license')
                : n.reason === 'error'
                    ? (ru ? ' не смог выполнить проверку' : ' could not run its check')
                    : (ru ? ' не ответил вовремя' : ' did not answer in time');
            return who + ': ' + (ru ? 'модуль «' + mod + '»' : 'module "' + mod + '"') + why
                + (ru ? ' — печать запущена без проверки остатка' : ' — the print started without the stock check');
        }
        if (n.kind === 'spool_replaced') {
            const left = sh.left_in_stock;
            return who + ': ' + filMat(sh) + (lang.value === 'ru'
                ? ' закончился — поставлена катушка со склада' + (left != null ? (', осталось ' + left) : '')
                : ' ran out — a spool from stock was mounted' + (left != null ? (', ' + left + ' left') : ''));
        }
        return who + ': ' + (lang.value === 'ru'
            ? filMat(sh) + ' на исходе — катушку скоро менять'
            : filMat(sh) + ' is running low — replace the spool soon');
    };
    // 16.10.2026 (R-151): уведомление «проверка не выполнена» — предупреждением, а не справкой.
    const pushFilNote = (n) => pushToast(filNoteText(n), (n && n.kind === 'check_unavailable') ? 'warn' : 'info');

    // 29.09.2026 (R-019): direct — окно открыто из «Загрузить» (файл с компьютера на один принтер).
    // Тогда элемент несёт свою функцию запуска launch(skipFilament), а не ставится в очередь:
    // файл лежит на диске по пути, в очереди ему места нет. Ответы и списание — те же самые.
    // 16.10.2026 (R-008, R-019): строка окна — ВСЕ нехватки принтера. Раньше бралась только первая:
    // не хватало на двух катушках — «Печатать всё равно» списывало в ноль одну, у второй оставался
    // остаток, которого нет, а в окне был назван один материал. Шаги списания — со всех катушек;
    // «Поставил новую катушку» — та, для которой склад дал шаги (первая такая), остальное покажет
    // повторная проверка склада после запуска.
    const _filRowOf = (b) => {
        const shorts = ((b && b.shortfall) || []).filter(Boolean);
        const sh = shorts[0] || {};
        const rs = shorts.find(x => (x.resolve_steps || []).length) || sh;
        return {
            printer_id: b.printer_id, printer_name: b.printer_name || b.printer_id,
            material: sh.material || '', color_name: sh.color_name || '',
            needed: Math.round(sh.needed || 0), available: Math.round(sh.available || 0),
            shorts: shorts.map(x => ({ material: x.material || '', color_name: x.color_name || '',
                                       needed: Math.round(x.needed || 0), available: Math.round(x.available || 0) })),
            slot: (rs.slot != null ? rs.slot : -1), external: !!rs.external,
            filament_id: rs.filament_id || '', weight_total_g: rs.weight_total_g || 0,
            resolve_steps: rs.resolve_steps || [],
            override_steps: shorts.flatMap(x => x.override_steps || []),
            reported_material: rs.reported_material || '', state: ''
        };
    };
    const openFilamentDecision = (blocked, items, interval, direct = false) => {
        const byId = {};
        (items || []).forEach(it => { byId[it.printer_id] = it; });
        _filPending.value = { items: byId, interval: interval || 60 };
        filDecision.value = {
            open: true, busy: '', confirm: '', direct: !!direct,
            rows: blocked.map(b => _filRowOf(b))
        };
    };
    // 16.10.2026 (R-019): после «Поставил новую катушку» склад снова против (не хватает на другой
    // катушке) — строка окна остаётся открытой с НОВОЙ нехваткой, а не пишет «не удалось».
    const _filReopenRow = (row, blk) => {
        Object.assign(row, _filRowOf(Object.assign({}, blk, { printer_id: row.printer_id, printer_name: row.printer_name })));
        row.state = '';
        pushToast(row.printer_name + ': ' + (lang.value === 'ru'
            ? 'катушка оприходована, но склад снова сообщает нехватку — решите в окне'
            : 'spool received, but the stock still reports a shortage — decide in the window'), 'info');
    };
    const closeFilamentDecision = () => { filDecision.value = { open: false, rows: [], busy: '', confirm: '' }; };
    const filRowsLeft = computed(() => (filDecision.value.rows || []).filter(r => !r.state).length);

    // «Поставил новую катушку» — оприходовать и запустить.
    // ЯДРО НЕ ЗНАЕТ, КАКОЙ МОДУЛЬ ВЕДЁТ УЧЁТ. Шаги (адрес и тело запроса) приходят вместе с отказом
    // от самого модуля — здесь они лишь выполняются по очереди. Иначе в ядре появилась бы жёсткая
    // привязка к складу, а модули подключаемые (это стережёт test_printer_stock_indicator, S3).
    const filReceiveAndStart = async (row) => {
        if (filDecision.value.busy) return;
        filDecision.value.confirm = '';        // начатое подтверждение «печатать всё равно» снимается
        filDecision.value.busy = row.printer_id;
        try {
            const steps = row.resolve_steps || [];
            if (!steps.length) throw new Error('no steps');
            for (const st of steps) {
                const r = await (await fetch(st.url, { method: st.method || 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(st.body || {}) })).json();
                if (!r || r.ok === false) throw new Error('step failed');
            }
            const it = _filPending.value.items[row.printer_id];
            if (it && it.launch) {
                // R-019: «Загрузить» — катушка оприходована, файл уходит на принтер сразу. Склад
                // спрашивается снова (skipFilament=false): учёт теперь исправен и должен пропустить.
                const res = await it.launch(false);
                if (res === true) {
                    row.state = 'queued';
                    pushToast(row.printer_name + ': ' + (lang.value === 'ru' ? 'катушка оприходована, файл отправляется на принтер' : 'spool received, the file is being sent to the printer'), 'success');
                } else if (res && res.low_filament) {
                    _filReopenRow(row, res.low_filament);    // 16.10.2026 (R-019): склад снова против
                } else { row.state = 'error'; }
            } else if (it) {
                const q = await (await fetch('/api/print-queue/enqueue', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: [it], interval: _filPending.value.interval }) })).json();
                const qb = ((q && q.blocked) || []).filter(b => b && b.status === 'low_filament');
                if (((q && q.queued) || []).length) {
                    row.state = 'queued';
                    pushToast(row.printer_name + ': ' + (lang.value === 'ru' ? 'катушка оприходована, запуск поставлен в очередь' : 'spool received, launch queued'), 'success');
                } else if (qb.length) {
                    _filReopenRow(row, qb[0]);               // 16.10.2026 (R-019): склад снова против
                } else { row.state = 'error'; }
            } else { row.state = 'queued'; }
            fetchPrintQueue();
            fetchSendJobs();
        } catch (e) {
            row.state = 'error';
            pushToast(row.printer_name + ': ' + (lang.value === 'ru' ? 'не удалось оприходовать катушку' : 'could not receive the spool'), 'info');
        }
        filDecision.value.busy = '';
        if (!filRowsLeft.value) setTimeout(closeFilamentDecision, 900);
    };
    const filSkipPrinter = (row) => {
        filDecision.value.confirm = '';        // начатое подтверждение «печатать всё равно» снимается
        row.state = 'skipped';
        if (!filRowsLeft.value) closeFilamentDecision();
    };

    // «Печатать всё равно» (Alpha 2.850) — два клика: первый просит подтверждение прямо на кнопке,
    // второй выполняет. Подтверждение здесь не формальность: остаток катушки списывается в ноль,
    // а печать уходит на принтер, в котором материала может не быть вовсе.
    // ПОРЯДОК ВАЖЕН. Сначала правится учёт, потом ставится запуск: обратный порядок оставил бы
    // печать идущей, а склад — с остатком, которого нет.
    // СКЛАД НЕ ОТМЕНЯЕТ ПЕЧАТЬ. Владелец уже решил печатать; если списание не удалось, запуск всё
    // равно уходит, а тост честно говорит, что учёт поправить не вышло (тихо это скрывать нельзя).
    // Ядро по-прежнему не знает адресов склада — шаги приходят от модуля, как и resolve_steps.
    const filForceStart = async (row) => {
        if (filDecision.value.busy) return;
        if (filDecision.value.confirm !== row.printer_id) { filDecision.value.confirm = row.printer_id; return; }
        filDecision.value.confirm = '';
        filDecision.value.busy = row.printer_id;
        let stockOk = true;
        const _writeOff = async () => {
            for (const st of (row.override_steps || [])) {
                try {
                    const r = await (await fetch(st.url, { method: st.method || 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(st.body || {}) })).json();
                    if (!r || r.ok === false) stockOk = false;
                } catch (e) { stockOk = false; }
            }
        };
        const _itDirect = (_filPending.value.items || {})[row.printer_id];
        // R-019: у «Загрузить» (прямая отправка) порядок обратный — СНАЧАЛА принтер принимает файл,
        // ПОТОМ списывается остаток. Принтер может отказать (удержан планом, уже отправляет файл), и
        // тогда учёт склада остаётся нетронутым. После «принято» принтер уже занят этой отправкой,
        // вклиниться другой печати некуда, а списание идёт следом за доли секунды.
        if (!(_itDirect && _itDirect.launch)) await _writeOff();
        try {
            const it = _filPending.value.items[row.printer_id];
            if (!it) throw new Error('no item');
            if (it.launch) {
                // R-019: «Загрузить» — файл уходит на принтер с решением владельца (skipFilament=true),
                // склад заново не спрашивается; остаток списывается только после «принято».
                if ((await it.launch(true)) === true) {
                    await _writeOff();
                    row.state = 'queued';
                    pushToast(row.printer_name + ': ' + (lang.value === 'ru'
                        ? (stockOk ? 'файл отправляется на принтер, остаток списан' : 'файл отправляется на принтер, но склад поправить не удалось')
                        : (stockOk ? 'the file is being sent to the printer, leftover written off' : 'the file is being sent to the printer, but stock could not be updated')),
                        stockOk ? 'success' : 'info');
                } else { row.state = 'error'; }
            } else {
                // skip_filament — метка «решение принято владельцем»: она едет с элементом до самого
                // старта, иначе очередь через минуту переспросила бы склад и упёрлась в тот же отказ.
                const q = await (await fetch('/api/print-queue/enqueue', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: [Object.assign({}, it, { skip_filament: true })], interval: _filPending.value.interval }) })).json();
                if (((q && q.queued) || []).length) {
                    row.state = 'queued';
                    pushToast(row.printer_name + ': ' + (lang.value === 'ru'
                        ? (stockOk ? 'запуск поставлен в очередь, остаток списан' : 'запуск поставлен в очередь, но склад поправить не удалось')
                        : (stockOk ? 'launch queued, leftover written off' : 'launch queued, but stock could not be updated')),
                        stockOk ? 'success' : 'info');
                } else {
                    row.state = 'error';
                    pushToast(row.printer_name + ': ' + (lang.value === 'ru' ? 'запуск поставить не удалось' : 'could not queue the launch'), 'info');
                }
            }
        } catch (e) {
            row.state = 'error';
            pushToast(row.printer_name + ': ' + (lang.value === 'ru' ? 'запуск поставить не удалось' : 'could not queue the launch'), 'info');
        }
        filDecision.value.busy = '';
        fetchPrintQueue();
        fetchSendJobs();
        if (!filRowsLeft.value) setTimeout(closeFilamentDecision, 900);
    };

    // 🔒 ОТЛАЖЕНО — пакетная печать на выбранные принтеры с прогрессом отправки. Проверено на задачах, тот же сценарий применён к проектам. Ошибки не диалогами — итог тостом. Не менять без перепроверки.
    const launchPrintSelected = async (ev) => {
        const ctx = printSpotlightCtx.value;
        const ids = (printSel.value || []).slice();
        if (!ctx || !ids.length) return;
        // Alpha 2.729: ЕДИНЫЙ поток — одиночный принтер (в т.ч. Bambu с живым AMS) идёт СРАЗУ в окно
        // «Параметры запуска печати» (ветка ids.length===1 ниже). Старое предварительное окно выбора AMS-слота
        // (amsPick) больше НЕ открывается: источник филамента выбирается только в PrintStartDialog — он и есть
        // единственный источник ams_slot. Инвариант пакетной печати (ids≥2: stagger/_doSend, ошибки тостом) не тронут.
        if (staggerOn.value && ids.length >= 2) {        // поэтапный запуск: в серверную очередь вместо мгновенного старта всех
            const nameOf = (pid) => { const pp = (printers.value || []).find(x => x.id === pid); return (pp && pp.name) || pid; };
            const items = ids.map(pid => {
                const it = { printer_id: pid, printer_name: nameOf(pid) };
                if (ctx.flow === 'project') { it.flow = 'project'; it.project_id = ctx.pid; it.file_id = ctx.fileId; }
                else { it.flow = 'quick'; it.gcode_file = ctx.filename; it.source = ctx.source || 'quick'; it.part_name = ctx.partName; }
                return it;
            });
            try {
                // Alpha 2.848: ответ ТЕПЕРЬ читается. Прежде тост сообщал число ВЫБРАННЫХ принтеров, а не
                // реально поставленных, поэтому отказ склада выглядел как успешная постановка.
                const resp = await (await fetch('/api/print-queue/enqueue', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items, interval: staggerInterval.value }) })).json();
                const _queued = ((resp && resp.queued) || []).length;
                if (_queued) pushToast((lang.value === 'ru' ? 'В очередь на запуск: ' : 'Queued to start: ') + _queued, 'success');
                ((resp && resp.notes) || []).forEach(n => pushFilNote(n));
                const _blocked = (resp && resp.blocked) || [];
                if (_blocked.length) openFilamentDecision(_blocked, items, staggerInterval.value);
                else if (!_queued) pushToast(tr('Could not start print.'), 'info');
            } catch (e) { pushToast(tr('Could not start print.'), 'info'); }
            printSel.value = [];
            exitSpotlight();
            fetchPrintQueue();
            fetchSendJobs();   // 15.09.2026: reservation очереди уже в панели — строка файла покажет «Отправка» сразу
            return;
        }
        // Alpha 2.688: собственно отправка (одиночная или пакетная). Пакетное поведение ИДЕНТИЧНО прежнему —
        // при print_opts=null запросы байт-в-байт те же. print_opts применяются backend'ом только для Bambu (whitelist).
        // Alpha 2.723: srcSlot приходит ТОЛЬКО из окна одиночного запуска (ветка ids.length===1 — принтер без
        // живого AMS → окно вернёт -1 «внешняя катушка»); пакет ≥2 его не передаёт — запросы как раньше.
        const _doSend = async (print_opts, srcSlot) => {
            // Alpha 2.728: пакет тоже неблокирующий — каждый принтер даёт accepted → строку в панели отправок;
            // прежний блокирующий оверлей printSending убран. Логика выбора/AMS/spotlight не изменена.
            //  08.10.2026 (обход фермы, R-008: «окно вообще не появляется»). Отказ склада {status:'low_filament'}
            //  здесь считался обычной неудачей — владелец видел только «Отправлено на принтеры: 0/1», а окно
            //  «Материал закончился» с «Печатать всё равно» открывалось лишь у поэтапного запуска. Запуск из
            //  проекта к тому же шёл с skip_filament и склад не спрашивал вовсе. Теперь оба пути спрашивают
            //  склад, отказ открывает то же окно, что «Загрузить» (R-019): у элемента своя функция launch,
            //  повтор идёт тем же запросом, с skip_filament только по решению владельца в окне. Уведомления
            //  склада («впритык», «катушка заменена») показываются тостом, а не теряются.
            let fail = 0;
            const blocked = [], blockedItems = [];
            const sendOne = async (pid) => {
                const _ctx = { printer_id: pid, printer_name: _printerNameOf(pid), file_name: (ctx.flow === 'project' ? _p2FileNameOf(ctx.pid, ctx.fileId) : (ctx.filename || '')), source: (ctx.flow === 'project' ? 'project' : 'task') };
                let url, body;
                if (ctx.flow === 'project') {
                    url = '/api/projects2/' + ctx.pid + '/files/' + ctx.fileId + '/print';
                    body = { printer_id: pid };
                } else {
                    url = '/api/part/print';
                    body = { printer_id: pid, gcode_file: ctx.filename, source: ctx.source || 'quick' };
                    if (ctx.partName) body.part_name = ctx.partName;
                }
                if (print_opts) body.print_opts = print_opts;
                if (ids.length === 1 && srcSlot !== undefined && srcSlot !== null) body.ams_slot = Number(srcSlot);
                const _post = async (b) => (await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })).json().catch(() => ({}));
                const _notes = (r) => ((r && r.notes) || []).forEach(n => pushFilNote(n));
                try {
                    const j = await _post(body);
                    if (j && j.status === 'low_filament') {
                        blocked.push(Object.assign({}, j, { printer_id: pid, printer_name: _ctx.printer_name }));
                        blockedItems.push({ printer_id: pid, launch: async (skipFilament) => {
                            const b = Object.assign({}, body);
                            if (skipFilament) b.skip_filament = true;
                            const r = await _post(b);
                            //  16.10.2026 (R-019): склад снова против — окно покажет новую нехватку.
                            if (!skipFilament && r && r.status === 'low_filament')
                                return { low_filament: Object.assign({}, r, { printer_id: pid, printer_name: _ctx.printer_name }) };
                            _notes(r);
                            const how = handleSendResp(r, _ctx);
                            if (how === 'other') pushToast(_ctx.printer_name + ': ' + ((r && (r.reason === 'printer_held' || r.reason === 'printer_busy'))
                                ? readinessReasonText(r.reason) : tr((r && r.reason) || 'Could not start print.')), 'info');
                            if (how === 'accepted' && ctx.flow === 'project') { try { await loadProject2Tree(ctx.pid); } catch (e) {} }
                            return how === 'accepted';
                        } });
                        return;
                    }
                    _notes(j);
                    if (handleSendResp(j, _ctx) !== 'accepted') fail++;
                } catch (e) { fail++; }
            };
            await Promise.all(ids.map(sendOne));
            if (ctx.flow === 'project') { try { await loadProject2Tree(ctx.pid); } catch (e) {} }
            //  Принтеры, остановленные складом, в счёт отправки не входят: по ним решает окно ниже.
            const total = ids.length - blocked.length;
            if (total) pushToast(fail ? (tr('Sent to printers') + ': ' + (total - fail) + '/' + total) : (tr('Sent to printers') + ': ' + total), fail ? 'info' : 'success');
            printSel.value = [];
            exitSpotlight();
            if (blocked.length) openFilamentDecision(blocked, blockedItems, 0, true);
        };
        // Alpha 2.688: одиночный принтер — сначала окно «Параметры запуска печати» (для Bambu видны реальные опции),
        // печать уходит по кнопке «Печать» с выбранными print_opts. Пакет (≥2) и очередь/stagger — как раньше.
        if (ids.length === 1) {
            const _pid0 = ids[0];
            openPrintStart({ printerId: _pid0, label: (ctx.flow === 'project' ? '' : (ctx.partName || ctx.filename || '')), source: (ctx.source || 'quick'), onConfirm: (opts, srcSlot) => { _doSend(opts, srcSlot); } });
            return;
        }
        await _doSend(null);
    };
    const onPrintBtn = (ctx, fileArg, ev) => {              // клик по кнопке: либо вход в выбор, либо запуск выбранных
        if (printBtnActive((ctx && ctx.rowKey) || '')) launchPrintSelected(ev);
        else enterPrintSpotlight(ctx, fileArg);
    };
    // Единый «подъём» подсвеченной строки/детали над затемнением (один источник для Проектов и Задач).
    const spotlightLift = (key) => (spotlightRow.value === key) ? (tourActive.value ? 'position:relative;z-index:9991' : 'position:relative;z-index:50') : '';
    // 🔒 ОТЛАЖЕНО — подъём детали проекта над затемнением: либо её собственная подсветка ('pt:'),
    // либо идёт выбор принтера для ОДНОГО ИЗ ЕЁ файлов ('p2:'+file_id) — тогда панель с кнопкой не
    // должна гаснуть. Так печать в проектах визуально совпадает с задачами. Не менять без перепроверки.
    const pvPartLift = (pp) => {
        const k = 'pt:' + pp.part_id;
        const z = tourActive.value ? 'position:relative;z-index:9991' : 'position:relative;z-index:50';
        if (spotlightRow.value === k) return z;
        if (printSpotlightCtx.value && (pp.plates || []).some(pl => spotlightRow.value === 'p2:' + pl.file_id)) return z;
        return '';
    };
    // 🔒 ОТЛАЖЕНО — visiblePrinters фильтрует принтеры под печать (сценарий подсказок по типам удалён 05.09.2026); в режиме подсказки показывались ТОЛЬКО подходящие принтеры, поднятые над затемнением. Не убирать фильтр spotlight. Не менять без перепроверки.
    const visiblePrinters = computed(() => {
        if (spotlight.value.length) return sortedPrinters.value.filter(p => spotlight.value.includes(p.id));
        return sortedPrinters.value;
    });
    // 🔒 ОТЛАЖЕНО — onSpotWheel: проброс прокрутки «сквозь» затемняющий оверлей. Он лежит
    // поверх всего и перехватывает колесо, из-за чего список проекта переставал скроллиться
    // (до детали сверху/снизу не доехать, скролл застревал). Пробрасываем wheel в
    // прокручиваемый контейнер под курсором. Не менять без перепроверки.
    const onSpotWheel = (e) => {
        try {
            const ov = e.currentTarget;
            const saved = ov.style.pointerEvents;
            ov.style.pointerEvents = 'none';
            const under = document.elementFromPoint(e.clientX, e.clientY);
            ov.style.pointerEvents = saved;
            let el = under;
            while (el && el !== document.body && el !== document.documentElement) {
                const oy = getComputedStyle(el).overflowY;
                if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 1) {
                    el.scrollTop += (e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY);
                    e.preventDefault();
                    return;
                }
                el = el.parentElement;
            }
        } catch (err) {}
    };

    const anyEditing = () => printersEditMode.value || Object.values(editingProjects.value).some(v => v);
    const partsDirty = ref(false);
    // ------------------------------------------------------------------------
    // БЛОК: периодическая синхронизация с сервером.
    // Загружает детали, принтеры и Tasks. Во время редактирования и тура
    // обновление временно блокируется, чтобы не затереть локальные значения.
    // ------------------------------------------------------------------------
    const fetchStateMatrix = async () => {
        if (tourActive.value) return;
        if (anyEditing() || partsDirty.value) return;
        try {
            const [res, pRes] = await Promise.all([fetch('/api/parts'), fetch('/api/printers')]);
            if(!res.ok) return;
            const jp = await res.json();
            jp.forEach(p => { 
                p._uid = (parts.value.find(x => x.part_name === p.part_name) || {})._uid || (p.part_name + '_' + Math.random().toString(36).substr(2, 5)); 
                if (editingProjectNames.value[p.project_name] === undefined) { 
                    editingProjectNames.value[p.project_name] = p.project_name; 
                    editingProjectDates.value[p.project_name] = p.due_date; 
                } 
                if (!p.preview_base64) p.preview_base64 = '';
                if (!p.notes) p.notes = '';
                if (!p.gcode_file) p.gcode_file = '';
                if (!p.src_path) p.src_path = '';
            });
            parts.value = jp; 
            if(pRes.ok) printers.value = await pRes.json();
        } catch (e) {}
    };
    //  2.928: метки «правится сейчас» стали ПО-ПОЛЕВЫМИ: { filename: { поле: true } }.
    //  Раньше метка на всю строку замораживала на экране и счёт печати, к которому владелец
    //  не прикасался, — клик в поле без правки останавливал видимый счёт навсегда.
    const stagingDirty = ref({});   // { filename: { required_qty|printed_qty|notes: true } }
    const fetchStaging = async () => {
        if (tourActive.value) return;
        try {
            const r = await fetch('/api/staging');
            if (!r.ok) return;
            const fresh = await r.json();
            // Сохраняем локальные значения для строк, которые сейчас редактируются (чтобы число не "прыгало")
            const dirty = stagingDirty.value;
            if (Object.keys(dirty).length) {
                const byName = {};
                stagingFiles.value.forEach(f => { byName[f.filename] = f; });
                fresh.forEach(nf => {
                    const df = dirty[nf.filename];
                    const old = byName[nf.filename];
                    if (df && old) {
                        //  Сохраняем экранное значение ТОЛЬКО у поля, которое правится
                        //  прямо сейчас, — остальные поля всегда живые с сервера.
                        if (df.required_qty) nf.required_qty = old.required_qty;
                        if (df.printed_qty) nf.printed_qty = old.printed_qty;
                        if (df.notes) nf.notes = old.notes;
                        //  Alpha 2.947: то же и для переключателя синхронизации. Обновление
                        //  списка идёт по таймеру и могло прилететь между нажатием и ответом
                        //  сервера — значок мигал бы обратно.
                        if (df.project_sync) nf.project_sync = old.project_sync;
                    }
                });
            }
            stagingFiles.value = fresh;
        } catch (e) {}
    };
    // БЛОК: добавление файлов в Tasks через выбор и drag-and-drop.
    const uploadStagingFiles = async (fileList) => {
        const files = Array.from(fileList || []).filter(f => /[.](stl|3mf|gcode)$/i.test(f.name));
        if (!files.length) return;
        const fd = new FormData();
        files.forEach(f => fd.append('files', f));
        try {
            await uploadWithProgress('/api/staging/upload', fd, 'Uploading file…');
            await fetchStaging();
        } catch (e) {}
    };
    const handleStagingDrop = (e) => {
        isDraggingStaging.value = false;
        if (e.dataTransfer && e.dataTransfer.files) uploadStagingFiles(e.dataTransfer.files);
    };


    // Окно подтверждения удаления с ИМЕНЕМ объекта в кавычках под язык интерфейса — чтобы было
    // видно, что именно удаляется. Пустое имя → прежний обобщённый вопрос (страховка, если имя
    // не удалось получить из состояния).
    const _confirmDelete = (key, name) => {
        const nm = String(name == null ? '' : name).trim();
        return askConfirm({
            title: tr(key),
            text: nm ? ((lang.value === 'ru' ? '«' : '"') + nm + (lang.value === 'ru' ? '»' : '"')) : '',
            okText: _L('Удалить', 'Delete'), danger: true,
        });
    };
    const deleteStagingFile = async (filename) => {
        if (!await _confirmDelete('Delete this file?', filename)) return;   // как у остальных удалений: без подтверждения файл «Задач» удалялся мгновенно, по одному клику
        try {
            await fetch('/api/staging/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename }) });
            await fetchStaging();
        } catch (e) {}
    };

    const pickingFiles = ref(false);

    // ── Поэтапный запуск печати: серверная очередь (/api/print-queue/*) + настройка в localStorage.
    const staggerOn = ref(localStorage.getItem('farm_stagger') === '1');                 // по умолчанию выключено
    const staggerInterval = ref(parseInt(localStorage.getItem('farm_stagger_sec') || '60', 10) || 60);
    const setStaggerOn = (v) => { staggerOn.value = !!v; try { localStorage.setItem('farm_stagger', v ? '1' : '0'); } catch (e) {} _farmSettingsPush(); };
    const setStaggerInterval = (v) => { let n = parseInt(v, 10); if (!(n >= 5)) n = 60; n = Math.max(5, Math.min(600, n)); staggerInterval.value = n; try { localStorage.setItem('farm_stagger_sec', String(n)); } catch (e) {} _farmSettingsPush(); };
    const staggerIntervalInput = computed({ get: () => staggerInterval.value, set: setStaggerInterval });   // буфер для v-model.lazy: одностороннее :value сбрасывало ввод при перерисовке
    const printQueue = ref([]);            // серверная очередь: [{id, printer_id, printer_name, eta}]
    const pqSel = ref([]);                 // отмеченные галочками id для отмены
    const printSendingNow = ref(null);     // Alpha 2.630: что воркер отправляет ПРЯМО СЕЙЧАС {printer_name,…} | null — для индикатора «Отправка на принтер…»
    const queuedPrinterIds = computed(() => new Set((printQueue.value || []).map(q => q.printer_id)));
    const fetchPrintQueue = async () => {
        try {
            const r = await fetch('/api/print-queue');
            if (!r.ok) return;
            const j = await r.json();
            const nq = (j && j.queue) || [];
            if (JSON.stringify(nq) !== JSON.stringify(printQueue.value)) printQueue.value = nq;   // только при реальном изменении — иначе пустой опрос каждую секунду зря перерисовывает весь интерфейс
            const ns = (j && j.sending) || null;   // Alpha 2.630: обновляем ТОЛЬКО при реальной смене — без спама/перерисовок
            if (JSON.stringify(ns) !== JSON.stringify(printSendingNow.value)) printSendingNow.value = ns;
            const ids = new Set(printQueue.value.map(x => x.id));
            if (pqSel.value.some(id => !ids.has(id))) pqSel.value = pqSel.value.filter(id => ids.has(id));   // снять отметки с исчезнувших
        } catch (e) {}
    };
    const togglePqSel = (id) => { const i = pqSel.value.indexOf(id); if (i === -1) pqSel.value.push(id); else pqSel.value.splice(i, 1); };
    const cancelPqSelected = async () => {
        const ids = pqSel.value.slice();
        if (!ids.length) return;
        pqSel.value = [];
        try { await fetch('/api/print-queue/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) }); } catch (e) {}
        fetchPrintQueue();
    };
    const pqEtaLabel = (sec) => {
        if (!(sec > 0)) return lang.value === 'ru' ? 'запуск…' : 'starting…';
        const m = Math.floor(sec / 60), ss = sec % 60;
        return (lang.value === 'ru' ? 'через ' : 'in ') + m + ':' + String(ss).padStart(2, '0');
    };
    const idlePrinters = computed(() => printers.value.filter(p => {
        const st = (wsData.value[p.id]?.status || 'OFFLINE').toUpperCase();
        return st === 'IDLE' || st === 'READY' || st === 'STANDBY' || st === 'FINISH' || st === 'OPERATIONAL' || st === 'FAILED';
    }));
    // ------------------------------------------------------------------------
    // БЛОК: совместимость файла и принтера, запуск из плана/Tasks,
    // выбор AMS и обработка ответа сервера.
    // ------------------------------------------------------------------------
    // Совместимые с конкретным файлом принтеры (фильтр по числу сопел нарезки)
    const compatiblePrintersFor = (arg) => {
        // arg — объект (файл Tasks / деталь проекта) ИЛИ имя файла (тогда находим объект).
        let item = arg;
        if (typeof arg === 'string') {
            item = (stagingFiles.value || []).find(x => x.filename === arg)
                || (parts.value || []).find(x => x.gcode_file === arg)
                || null;
        }
        const ids = (item && Array.isArray(item.compatible_pids)) ? item.compatible_pids : null;
        // Совместимость (модель + экосистема + число сопел) считает бэкенд — единый источник истины.
        // Здесь лишь пересекаем со свободными. Если список неизвестен — показываем все, чтобы не убрать корректный вариант.
        return idlePrinters.value.filter(p => (ids ? ids.indexOf(p.id) !== -1 : true) && !queuedPrinterIds.value.has(p.id) && !sendReserved.value.has(p.id));   // Alpha 2.728: reserved-принтер вне «Доступных»
    };
    const amsSelectFor = ref(null); // {filename, printerId} когда нужен выбор слота AMS
    const isAmsStep = (filename) => !!(amsSelectFor.value && amsSelectFor.value.filename === filename);
    const togglePrintMenu = (uid) => { amsSelectFor.value = null; printMenuUid.value = printMenuUid.value === uid ? null : uid; };
    const onDocClick = (e) => {
        if (_downInField) return;   // «клик» — это завершение выделения текста (нажали в поле, отпустили вне его): не закрываем ничего
        if (ctxMenu.value.show && !e.target.closest('.ctx-menu')) closeContextMenu();
        if (printMenuUid.value && !e.target.closest('.print-menu') && !e.target.closest('.print-toggle')) printMenuUid.value = null;
        if (alertsPanelOpen.value && !e.target.closest('.fm-alert-panel') && !e.target.closest('.fm-alert-indicator')) closeAlertsPanel();   // Alpha 2.731: клик вне закрывает только панель предупреждений
        if (cellAmsOpen.value) cellAmsOpen.value = false;
        //  2.975: меню пульта закрываются щелчком мимо — как и все остальные меню программы.
        if (ui3FilesOpen.value && !e.target.closest('.ui3-pp-fsel')) ui3FilesOpen.value = false;
        if (ui3AmsOpen.value && !e.target.closest('.ui3-pp-split')) ui3AmsOpen.value = false;
        closeAmsPick();
        if (!tourActive.value && showModal.value && !e.target.closest('.printer-card') && !e.target.closest('.grid-pop')) { const _aid = activeModalPrinterId.value; _preserveCardCenter(_aid, () => { showModal.value = false; activeModalPrinterId.value = null; }); }
    };
    // Alpha 2.673: общий Escape-стек. Любой ВЛОЖЕННЫЙ слой (диалоги установленных модулей и т.п.), которого
    // НЕТ в жёсткой цепочке ниже, регистрирует свою close-функцию при открытии и снимает при закрытии.
    // onKeydown закрывает ВЕРХНИЙ слой стека РАНЬШЕ жёсткой цепочки → Escape закрывает только верхнее окно,
    // а не родителя вместе с дочерним. Модули получают register/unregister через provide('escapeLayer').
    let _escSeq = 0;
    const escLayers = [];                                   // [{ token, close }] — LIFO-стек открытых вложенных слоёв
    const registerEscapeLayer = (closeFn, optId) => {
        if (typeof closeFn !== 'function') return null;
        const token = optId ? String(optId) : ('esc' + (++_escSeq));
        escLayers.push({ token, close: closeFn });
        return token;
    };
    const unregisterEscapeLayer = (token) => {
        if (!token) return;
        const i = escLayers.findIndex((l) => l.token === token);
        if (i !== -1) escLayers.splice(i, 1);
    };
    const closeTopEscapeLayer = () => {
        const layer = escLayers.pop();
        if (layer && typeof layer.close === 'function') { try { layer.close(); } catch (e) {} }
        return !!layer;
    };
    // Alpha 2.632: единый обработчик Escape — закрывает ТОЛЬКО самый верхний активный слой (одно нажатие = один слой).
    // Порядок = сверху вниз по стеку z-index/вложенности: сначала эфемерные попапы/меню, затем вложенные окна
    // (выбор модели закрывается РАНЬШЕ окна добавления принтера; проводник/диагностика — раньше настроек), затем
    // прочие модалки, режимы-панели рабочей области и в самом низу — раскрытая карточка принтера (её закрытие по
    // Escape пользователь хочет сохранить). Первое совпадение → закрыть и return, поэтому фон под более верхней
    // модалкой НЕ трогаем. НЕ закрываем по Escape: модалку восстановления очереди (recovery) — там нужен явный выбор
    // кнопкой, Escape не должен трогать очередь/печать/восстановление; подсказки-тултипы (гаснут сами).
    const onKeydown = (e) => {
        if (e.key !== 'Escape') return;
        // Тур ведёт свои клавиши сам (отдельный слушатель window `_tourOnKey`, Escape→endTour) — не вмешиваемся.
        if (showTourStartDialog.value) { dismissTourStartDialog(); return; }
        if (tourActive.value) return;
        // Пока открыта модалка восстановления прерванной очереди — Escape НИЧЕГО не делает (нужен явный выбор
        // «Продолжить/Отменить/Открыть очередь»; фон под ней не закрываем).
        if (recoveryNotice.value) return;
        // Alpha 2.673: общий Escape-стек — ВЛОЖЕННЫЕ слои (диалоги модулей и т.п.) закрываются ПЕРВЫМИ,
        // раньше жёсткой цепочки ниже, чтобы Escape закрыл только верхний слой, а не родителя с ребёнком.
        if (escLayers.length) { e.preventDefault(); e.stopPropagation(); closeTopEscapeLayer(); return; }
        if (printStart.value.open) { closePrintStart(); return; }               // Alpha 2.687: окно «Параметры запуска печати» — закрывается первым, печать НЕ уходит
        if (alertsPanelOpen.value) { closeAlertsPanel(); return; }              // Alpha 2.731: панель предупреждений (немодальна) — Escape закрывает ТОЛЬКО её
        // 1) Эфемерные попапы/меню (самый верх — закрываются первыми)
        if (ctxMenu.value.show) { closeContextMenu(); return; }                 // контекстное меню
        if (printMenuUid.value != null) { printMenuUid.value = null; return; }   // меню печати файла
        if (reworkPart.value) { closeRework(); return; }                        // попап перепечатки детали
        if (amsPick.value.open) { closeAmsPick(); return; }                     // выбор слота AMS (спотлайт-печать)
        if (amsSelectFor.value) { amsSelectFor.value = null; return; }          // выбор слота AMS (обычная печать)
        if (cellAmsOpen.value) { cellAmsOpen.value = false; return; }           // AMS-дропдаун в карточке
        //  2.975: меню пульта 3.0 — их Escape раньше не закрывал (заказ владельца).
        if (ui3FilesOpen.value) { ui3FilesOpen.value = false; return; }          // список файлов принтера
        if (ui3AmsOpen.value) { ui3AmsOpen.value = false; return; }              // выбор катушки для печати
        // Alpha 2.815: единый стек модальных окон. ВЛОЖЕННЫЕ диалоги (уровень >= 2: «Порт сервера»
        // и т.п.) закрываются РАНЬШЕ своих родителей, но ПОЗЖЕ эфемерных меню выше. Escape уносит
        // ровно один — самый верхний — слой, родительское окно остаётся открытым. Окна 1-го уровня
        // ниже по-прежнему закрывает отлаженный жёсткий порядок, он не тронут.
        const _topNested = fmModalTopNested();
        if (_topNested && _topNested.close) { e.preventDefault(); e.stopPropagation(); _topNested.close(); return; }
        // 2) Выбор модели принтера — открыт ПОВЕРХ окна добавления принтера, закрываем его раньше
        if (showModelPicker.value) { showModelPicker.value = false; return; }
        // 3) Верхние/вложенные окна (проводник и диагностика могут открываться ПОВЕРХ настроек → раньше настроек)
        if (exAmsOpen.value) { exAmsOpen.value = false; return; }               // Alpha 2.673: AMS-дропдаун в проводнике — закрываем раньше самого проводника
        if (exOpen.value) { exOpen.value = false; return; }                     // файловый менеджер (проводник)
        if (showDiag.value) { closeDiagnostics(); return; }                     // диагностика (закрытие снимает таймеры)
        if (showPrinterFiles.value) { closePrinterFiles(); return; }            // файлы принтеров (Alpha 2.823)
        if (showReports.value) { closeReports(); return; }                    // отчёты (Alpha 2.898)
        //  2.975: в оформлении 3.0 камера живёт ВНУТРИ пульта, а не отдельным окном. Escape на
        //  ней должен возвращать камеру из полного экрана в пульт, а в пульте — закрывать пульт
        //  целиком, а не гасить камеру и оставлять пустое место.
        if (ui3Mode && ui3Printer.value && cameraPrinterId.value) {
            if (ui3CamFull.value) { ui3PpCamOn(); return; }     // из полного экрана — обратно в пульт
            ui3SelectPrinter({ id: ui3Printer.value });         // повторное нажатие = закрыть пульт
            return;
        }
        if (cameraPrinterId.value) { closeCamera(); return; }                   // окно камеры (поверх карточки)
        if (showChangelog.value) { closeChangelog(); return; }                  // «Что нового» (открыт из «О программе»)
        if (showAbout.value) { closeAbout(); return; }                          // «О программе»
        if (showRestartModal.value) { dismissRestart(); return; }              // окно смены папки/перезапуска
        if (showUsers.value) { showUsers.value = false; return; }               // пользователи
        if (showAudit.value) { showAudit.value = false; return; }               // журнал аудита
        if (showSecuritySetup.value) { showSecuritySetup.value = false; return; }
        if (showSecurityDisable.value) { showSecurityDisable.value = false; return; }
        if (showSettings.value) { closeSettings(); return; }                    // настройки
        // 4) Добавление/редактирование принтера (то же, что кнопка-крестик/фон)
        if (showAddPrinterModal.value) { showAddPrinterModal.value = false; editingPrinterId.value = null; discClose(); return; }
        // Alpha 2.634: окно установленного модуля (напр. «Складской учёт») — открывается из «Настроек» и накрывает
        // весь интерфейс; раньше не закрывалось по Escape. Закрываем тем же способом, что и кнопка ✕/событие @close.
        if (activeModuleComp.value) { closeActiveModule(); return; }
        // 5) Режимы/панели рабочей области
        if (printSpotlightCtx.value || spotlight.value.length) { exitSpotlight(); return; }   // выбор принтеров для печати
        if (queuePickMode.value) { toggleQueuePick(); return; }                 // 2.975: режим отметки принтеров для очереди
        //  2.975: пульт принтера в оформлении 3.0 — Escape закрывает его так же, как повторное
        //  нажатие на карточку. Раньше уходило только выделение, а пульт оставался открытым.
        if (ui3Mode && ui3Printer.value) { ui3SelectPrinter({ id: ui3Printer.value }); return; }
        if (showNewProject2.value) { showNewProject2.value = false; return; }   // форма «Новый проект»
        if (archiveMode.value) { toggleArchiveMode(); return; }                 // режим «Архив»
        if (project2Expanded.value) { project2Expanded.value = ''; return; }     // раскрытый проект
        // 6) Раскрытая карточка принтера — СОХРАНЁННОЕ поведение (Escape закрывает карточку). Самый низ приоритета.
        if (showModal.value || activeModalPrinterId.value) {
            const _aid = activeModalPrinterId.value;
            _preserveCardCenter(_aid, () => { showModal.value = false; activeModalPrinterId.value = null; });
            return;
        }
    };
    // === Alpha 2.687/2.723: единое окно «Параметры запуска печати» (PrintStartDialog). Показывается ПЕРЕД
    // прямой одиночной печатью (Задачи/Проекты/проводник). Alpha 2.723: опции Bambu ВОЗВРАЩЕНЫ в формате,
    // подтверждённом перехватом команд Bambu Studio (2.722): источник филамента (внешняя/авто/реальный слот),
    // таймлапс (выкл.), калибровка потока (выкл.), автокалибровка стола (вкл.). Пакетный запуск/очередь UI не трогает. ===
    const PRINT_OPTS_DEFAULT = { timelapse: false, bed_leveling: true, flow_cal: false };
    const printerCapabilities = (printer) => {
        const t = ((printer && printer.type) || 'bambu').toLowerCase();
        if (t === 'bambu') return { type: 'bambu', bambu: true, klipper: false, fields: ['timelapse', 'bed_leveling', 'flow_cal'] };
        // Alpha 2.833: Klipper — adapter-driven диалог. Опции НЕ копируются с Bambu: список строит
        // backend по РЕАЛЬНЫМ Moonraker objects/macros конкретного принтера (см. openPrintStart).
        if (t === 'klipper') return { type: 'klipper', bambu: false, klipper: true, fields: [] };
        return { type: t, bambu: false, klipper: false, fields: [] };   // flashforge и прочие — простое подтверждение, без фейковых опций
    };
    const _loadPrintOpts = (pid, caps) => {
        const o = Object.assign({}, PRINT_OPTS_DEFAULT);
        if (!caps || !caps.bambu) return o;
        try {
            const raw = localStorage.getItem('fm_printopts_' + pid);
            if (raw) {
                const s = JSON.parse(raw);
                if (s && typeof s === 'object') {
                    ['timelapse', 'bed_leveling', 'flow_cal'].forEach(k => { if (typeof s[k] === 'boolean') o[k] = s[k]; });
                }
            }
        } catch (e) {}   // битый/старый localStorage (в т.ч. записи 2.687 с 6 ключами) → берём только актуальные 3
        return o;
    };
    // Источник филамента для окна: принтер без живого AMS — фиксированно «Внешняя катушка» (-1);
    // с AMS — «Авто (как в файле)» (null) + РЕАЛЬНЫЕ слоты (глобальный index; подпись — фактический
    // unit/tray, юниты нумеруются по порядку появления, как A1/A2 в остальном интерфейсе).
    const _printSrcOptions = (trays, dual) => {
        const opts = [{ v: 'auto', t: (lang.value === 'ru' ? 'Авто (как в файле)' : 'Auto (as in file)') }];
        // Alpha 2.734: «Внешняя катушка» доступна ВСЕМ Bambu, в т.ч. с живым AMS (external spool у Bambu
        // универсален; подтверждено hardware-capture). Выбор шлёт ams_slot:-1 → backend use_ams:false,
        // ams_mapping:[-1], ams_mapping2:[{ams_id:255,slot_id:0}]. vt_tray как capability НЕ используем.
        //  16.10.2026 (R-137): у двухсопельного (H2D) катушку — левую или правую — выбирает файл:
        //  та сторона, под чьё сопло он нарезан (как в Bambu Studio). Оператор сторону не выбирает.
        //  Подпись пункта — та же, что у неизменяемой строки принтера без AMS (printExtLabel).
        opts.push({ v: -1, t: printExtLabel({ dual: !!dual }) });
        const unitOrder = [];
        for (const t of trays) { const u = (t.unit == null ? 0 : t.unit); if (unitOrder.indexOf(u) < 0) unitOrder.push(u); }
        for (const t of trays) {
            const u = (t.unit == null ? 0 : t.unit);
            const uN = unitOrder.indexOf(u) + 1;
            const typ = (t.type && t.type !== 'Empty') ? (' · ' + t.type) : '';
            opts.push({ v: t.index, t: 'AMS A' + uN + ' · ' + (lang.value === 'ru' ? 'Слот ' : 'Slot ') + ((t.tray == null ? t.index % 4 : t.tray) + 1) + typ });
        }
        return opts;
    };
    //  16.10.2026 (R-137): что видно в окне запуска про внешнюю катушку двухсопельного принтера.
    const _extTrayMat = (pid, id) => {
        const e = (((wsData.value[pid] || {}).ext_trays) || {})[id];
        const m = e && typeof e.tray_type === 'string' ? e.tray_type.trim() : '';
        return m || '—';
    };
    //  Подпись внешней катушки — и для пункта списка, и для строки принтера без AMS. У двухсопельного она
    //  длинная и рядом с «Источник филамента» не помещается: в разметке окна строка у такого принтера
    //  переносит значение под подпись (flex-wrap), а не обрезает его и не ломает подпись на две строки.
    const printExtLabel = (ps) => {
        const ru = lang.value === 'ru';
        if (ps && ps.dual) return ru ? 'Внешняя катушка (сторона — по соплу в файле)' : 'External spool (side by the nozzle in the file)';
        return ru ? 'Внешняя катушка' : 'External spool';
    };
    const printExtNote = (ps) => {
        const ru = lang.value === 'ru';
        if (ps && ps.dual) {
            return (ru ? 'Только если плита печатает один материал; на H2D берётся катушка той стороны, под чьё сопло нарезан файл. Сейчас — левая: '
                       : 'Only when the plate prints one material; on H2D the spool on the side of the nozzle the file is sliced for is used. Now — left: ')
                + _extTrayMat(ps.printerId, '254') + (ru ? ' · правая: ' : ' · right: ') + _extTrayMat(ps.printerId, '255') + '.';
        }
        return ru ? 'Только если плита печатает один материал. Иначе выберите «Авто» или слот AMS.'
                  : 'Only when the plate prints one material. Otherwise choose Auto or an AMS slot.';
    };
    const printStart = ref({ open: false, printerId: '', printerName: '', ptype: '', model: '', label: '', caps: null, opts: Object.assign({}, PRINT_OPTS_DEFAULT), src: 'external', hasAms: false, srcOptions: [], c1: false, cfsTrays: [], cfsSlot: 'file', onConfirm: null });
    const openPrintStart = (ctx) => {
        const printer = (printers.value || []).find(p => p.id === ctx.printerId) || {};
        const caps = printerCapabilities(printer);
        // Живые лотки AMS: если их нет — источник фиксирован «Внешняя катушка» (ложных пунктов не предлагаем);
        // предвыбор слота приходит из существующих дропдаунов (ctx.amsSlot: число = слот, null/undefined = авто).
        const trays = caps.bambu ? ((wsData.value[ctx.printerId] && wsData.value[ctx.printerId].ams_trays) || []) : [];
        const hasAms = trays.length > 0;
        //  16.10.2026 (R-137): двухсопельный Bambu — у него две внешние катушки (левая 254, правая 255).
        const dual = !!(caps.bambu && Number((wsData.value[ctx.printerId] || {}).nozzle_count || 1) >= 2);
        let src = 'external';   // нет живого AMS → источник принудительно «Внешняя катушка» (даже если пришёл запомненный слот)
        if (caps.bambu && hasAms) {
            const _pre = (ctx.amsSlot !== undefined && ctx.amsSlot !== null && Number(ctx.amsSlot) >= 0) ? Number(ctx.amsSlot) : null;
            // Запомненный/предвыбранный слот применяем ТОЛЬКО если он существует в СВЕЖЕМ живом отчёте AMS —
            // исчезнувший слот (снятый блок, перестановка) сбрасывается на безопасное «Авто (как в файле)».
            src = (_pre !== null && trays.some(t => Number(t.index) === _pre)) ? _pre : 'auto';
        }
        // Alpha 2.825 (c1): печать УЖЕ существующего файла принтера через C1 — в нём нет
        // «Авто (как в файле)» (null/-1 -> внешняя катушка) и не применяются Bambu-опции
        // запуска; диалог тот же, но без вводящих в заблуждение пунктов.
        let srcOptions = hasAms ? _printSrcOptions(trays, dual) : [];
        if (ctx.c1) { srcOptions = srcOptions.filter(o => o.v !== 'auto'); if (src === 'auto') src = -1; }
        try { console.debug('[PrintStart] open', { printerId: ctx.printerId, type: printer.type, model: printer.model, bambu: caps.bambu, hasAms, src }); } catch (e) {}
        //  Alpha 2.944: живые ячейки CFS (Creality K2). Предлагаем ТОЛЬКО те, в которых
        //  действительно есть филамент: пустой слот выбрать нельзя — печатать из него нечем.
        const cfsTrays = caps.klipper
            ? (((wsData.value[ctx.printerId] || {}).cfs_trays) || []).filter(t => t && t.type && t.type !== 'Empty')
            : [];
        printStart.value = { open: true, printerId: ctx.printerId, printerName: _printerNameOf(ctx.printerId), ptype: (printer.type || 'bambu'), model: (printer.model || ''), label: ctx.label || '', caps, opts: _loadPrintOpts(ctx.printerId, caps), src, hasAms, dual, srcOptions, c1: !!ctx.c1, cfsTrays, cfsSlot: 'file', kl: null, onConfirm: (typeof ctx.onConfirm === 'function' ? ctx.onConfirm : null) };
        // Alpha 2.833: Klipper — асинхронно читаем ДОКАЗАННЫЕ возможности (read-only Moonraker discovery).
        // Отказ запроса/недоступный принтер НЕ блокирует печать: диалог остаётся в режиме «Как в файле».
        // c1 (печать файла, уже лежащего на принтере) предстартовые операции не применяет — как у Bambu.
        if (caps.klipper && !ctx.c1) {
            printStart.value.kl = { loading: true, reachable: false, caps: [], start_macro: '', sel: {} };
            const _pid = ctx.printerId;
            fetch('/api/printer/' + encodeURIComponent(_pid) + '/klipper-prestart').then(r => r.json()).then(j => {
                if (!printStart.value.open || printStart.value.printerId !== _pid) return;   // окно уже закрыто/другой принтер
                const sel = {};
                const caps2 = Array.isArray(j && j.capabilities) ? j.capabilities : [];
                for (const c of caps2) { if (c && c.supported) sel[c.id] = !!((j.prefs || {})[c.id]); }
                printStart.value = Object.assign({}, printStart.value,
                    { kl: { loading: false, reachable: !!(j && j.reachable), caps: caps2, start_macro: String((j && j.start_macro) || ''), sel } });
            }).catch(() => {
                if (!printStart.value.open || printStart.value.printerId !== _pid) return;
                printStart.value = Object.assign({}, printStart.value, { kl: { loading: false, reachable: false, caps: [], start_macro: '', sel: {} } });
            });
        }
    };
    const closePrintStart = () => { if (printStart.value.open) printStart.value = Object.assign({}, printStart.value, { open: false, onConfirm: null }); };
    const confirmPrintStart = () => {
        const st = printStart.value;
        if (!st.open) return;
        const cb = st.onConfirm, caps = st.caps, pid = st.printerId;
        // Alpha 2.723: окно снова отдаёт РЕАЛЬНЫЕ opts (для Bambu) + выбранный источник филамента.
        // srcSlot: -1 = внешняя катушка, null = авто (как в файле), число = глобальный слот AMS.
        let opts = null, srcSlot;
        if (caps && caps.bambu) {
            opts = { timelapse: !!st.opts.timelapse, bed_leveling: !!st.opts.bed_leveling, flow_cal: !!st.opts.flow_cal };
            try { localStorage.setItem('fm_printopts_' + pid, JSON.stringify(opts)); } catch (e) {}
            srcSlot = st.hasAms ? (st.src === 'auto' ? null : Number(st.src)) : -1;
            try { console.debug('[PrintStart] confirm', { opts: Object.assign({}, opts), srcSlot }); } catch (e) {}
        }
        // Alpha 2.833: Klipper — передаём ТОЛЬКО выбранные allowlist-ID (никакого сырого G-code/имён
        // макросов). Пустой выбор → opts=null: запрос уходит байт-в-байт как раньше («Как в файле»).
        // Выбор запоминается per-printer НА СЕРВЕРЕ (backup); неподдерживаемое сервер отбрасывает сам.
        if (caps && caps.klipper && st.kl && !st.kl.loading) {
            // Alpha 2.838: уходят ТОЛЬКО операции уровня supported_automatic. Прежний набор условий
            // сохранён рядом: он остаётся частью контракта, а состояние добавляет к нему запрет
            // vendor-переопределений, выполнение которых Farm Manager гарантировать не может.
            const ids = (st.kl.caps || []).filter(c => c && c.state === 'supported_automatic' && c.supported && !c.file_controlled && c.auto_execute && c.safe_each_print && st.kl.sel[c.id] === true).map(c => c.id);
            if (ids.length) opts = Object.assign({}, opts || {}, { klipper_prestart: ids });
            try {   // сохранить per-printer предпочтения (только если есть что сохранять: есть доказанные операции)
                const prefs = {}; for (const c of (st.kl.caps || [])) { if (c && c.supported) prefs[c.id] = (st.kl.sel[c.id] === true); }
                if (Object.keys(prefs).length) fetch('/api/printer/' + encodeURIComponent(pid) + '/klipper-prestart', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prefs }) }).catch(() => {});
            } catch (e) {}
            try { console.debug('[PrintStart] confirm klipper', { ids }); } catch (e) {}
        }
        //  Alpha 2.944: выбранная ячейка CFS уходит вместе с опциями. 'file' — ничего не
        //  передаём, и файл отправляется байт-в-байт, как раньше.
        if (caps && caps.klipper && st.cfsSlot !== 'file' && st.cfsSlot !== undefined && st.cfsSlot !== null) {
            const _sl = Number(st.cfsSlot);
            if (Number.isFinite(_sl) && _sl >= 0) opts = Object.assign({}, opts || {}, { cfs_slot: _sl });
        }
        printStart.value = Object.assign({}, printStart.value, { open: false, onConfirm: null });
        if (cb) cb(opts, srcSlot);   // не-Bambu без опций: (null, undefined) — запрос уходит байт-в-байт как раньше
    };
    const printStartTypeLabel = (t) => { const m = { bambu: 'BambuLab', flashforge: 'FlashForge', klipper: 'Klipper', creality: 'Creality' }; return m[(t || '').toLowerCase()] || (t || ''); };
    // ── Alpha 2.839: клиентский сбор диагностического отчёта Klipper ─────────────────────────
    // ЗАЧЕМ. Чтобы доказать контракт подготовки печати, нужны данные с самого принтера. У его
    // владельца нет ни Python, ни терминала, ни адреса принтера — поэтому здесь одна кнопка.
    // Интерфейс НЕ передаёт ни адрес, ни токен, ни endpoint: сервер берёт их из своей же
    // конфигурации по printer_id и обращается к принтеру ТОЛЬКО чтением.
    const klRep = ref({ phase: 'idle', report: null, summary: null, filename: '', partial: false, reason: '' });
    // Alpha 2.867: диагностический отчёт Klipper переехал из окна запуска печати на карточку
    // принтера — значок в шапке открывает своё окно. Причина: отчёт нужен по требованию, а не
    // в момент запуска детали, и в окне печати он отвлекал от собственно печати.
    const klDiag = ref({ open: false, printerId: '', printerName: '', model: '' });
    const openKlipperDiag = (p) => {
        if (!p || !printerCapabilities(p).klipper) return;   // отчёт умеет собираться только с Klipper
        klRep.value = { phase: 'idle', report: null, summary: null, filename: '', partial: false, reason: '' };
        klDiag.value = { open: true, printerId: p.id, printerName: p.name || p.id, model: p.model || '' };
    };
    const closeKlipperDiag = () => { klDiag.value = Object.assign({}, klDiag.value, { open: false }); };
    const klRepPhases = {
        idle: ['Готов к проверке', 'Ready to check'],
        reading: ['Чтение конфигурации принтера…', 'Reading printer configuration…'],
        analyzing: ['Анализ макросов…', 'Analysing macros…'],
        checking: ['Проверка безопасности отчёта…', 'Checking report safety…'],
        ready: ['Отчёт готов', 'Report ready'],
        partial: ['Отчёт готов частично', 'Report ready (partial)'],
        unreachable: ['Принтер недоступен', 'Printer unreachable'],
        config_failed: ['Не удалось прочитать конфигурацию', 'Could not read the configuration'],
        blocked: ['Отчёт заблокирован проверкой безопасности', 'Report blocked by the safety check'],
    };
    const klRepPhaseText = () => {
        const e = klRepPhases[klRep.value.phase] || klRepPhases.idle;
        return lang.value === 'ru' ? e[0] : e[1];
    };
    const klRepBusy = computed(() => ['reading', 'analyzing', 'checking'].includes(klRep.value.phase));
    const klRepDone = computed(() => ['ready', 'partial'].includes(klRep.value.phase));
    const collectKlipperReport = async () => {
        if (klRepBusy.value) return;                    // защита от повторного нажатия
        const pid = klDiag.value.printerId;
        if (!pid) return;
        klRep.value = { phase: 'reading', report: null, summary: null, filename: '', partial: false, reason: '' };
        let j = null, ok = false;
        try {
            const r = await fetch('/api/printer/' + encodeURIComponent(pid) + '/klipper-contract-report',
                { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
            j = await r.json().catch(() => null);
            ok = r.ok && j && j.status === 'ok';
            if (!ok) {
                const why = String((j && j.reason) || '');
                klRep.value = Object.assign({}, klRep.value, {
                    phase: why === 'report_redaction_failed' ? 'blocked'
                        : (why === 'unreachable' ? 'unreachable' : 'config_failed'), reason: why });
                return;
            }
        } catch (e) {
            klRep.value = Object.assign({}, klRep.value, { phase: 'unreachable', reason: 'network' });
            return;
        }
        klRep.value = Object.assign({}, klRep.value, { phase: 'analyzing' });
        const rep = j.report || null;
        klRep.value = Object.assign({}, klRep.value, { phase: 'checking' });
        // Клиентская проверка целостности: неизвестная схема отчёта не выдаётся за годную.
        if (!rep || String(rep.report_schema_version || '') !== '3diwell-klipper-contract-report-v1') {
            klRep.value = Object.assign({}, klRep.value, { phase: 'config_failed', reason: 'bad_schema' });
            return;
        }
        klRep.value = { phase: (j.partial ? 'partial' : 'ready'), report: rep, summary: j.summary || null,
                        filename: String(j.filename || 'klipper-report.json'), partial: !!j.partial, reason: '' };
    };
    const saveKlipperReport = () => {
        const st = klRep.value;
        if (!st.report) return;
        try {   // тот же безопасный путь, что у выгрузки резервной копии: файл не хранится на сервере
            const blob = new Blob([JSON.stringify(st.report, null, 1)], { type: 'application/json;charset=utf-8' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = st.filename || 'klipper-report.json';
            document.body.appendChild(a); a.click(); a.remove();
            setTimeout(() => { try { URL.revokeObjectURL(a.href); } catch (e) {} }, 4000);
        } catch (e) { pushToast(lang.value === 'ru' ? 'Не удалось сохранить файл' : 'Save failed', 'warn'); }
    };
    const klRepSummaryText = () => {
        const s = klRep.value.summary || {};
        const ru = lang.value === 'ru';
        const yn = (v) => (v ? (ru ? 'да' : 'yes') : (ru ? 'нет' : 'no'));
        return [
            (ru ? 'Klipper: ' : 'Klipper: ') + (s.klipper_version || '?'),
            (ru ? 'Moonraker: ' : 'Moonraker: ') + (s.moonraker_version || '?'),
            (ru ? 'Стартовый макрос: ' : 'Start macro: ') + (s.start_macro || (ru ? 'не найден' : 'not found')),
            (ru ? 'Его параметры: ' : 'Its parameters: ') + ((s.start_macro_params || []).join(', ') || '—'),
            (ru ? 'Делает калибровку сам: ' : 'Does bed mesh itself: ') + yn(s.start_macro_does_bed_mesh),
            (ru ? 'Паркует оси сам: ' : 'Homes axes itself: ') + yn(s.start_macro_homes),
            (ru ? 'Команда калибровки есть: ' : 'Bed mesh command exists: ') + yn(s.bed_mesh_command_exists),
            (ru ? 'Переопределена макросом: ' : 'Overridden by a macro: ') + yn(s.bed_mesh_overridden),
            (ru ? 'Открытых вопросов: ' : 'Unresolved questions: ') + (s.unresolved_count || 0),
        ].join('\n');
    };
    const klRepSummaryLines = computed(() => (klRep.value.summary ? klRepSummaryText() : ''));
    const copyKlipperSummary = async () => {
        try { await navigator.clipboard.writeText(klRepSummaryText());
              pushToast(lang.value === 'ru' ? 'Сводка скопирована' : 'Summary copied'); }
        catch (e) { pushToast(lang.value === 'ru' ? 'Не удалось скопировать' : 'Copy failed', 'warn'); }
    };
    // Alpha 2.838: ЧЕСТНАЯ подпись под операцией подготовки. Раньше строка говорила лишь
    // «Поддерживается макросом принтера» — и это же читалось как «будет выполнено». Теперь
    // подпись называет уровень доказательства и источник, а активной галочка бывает только у
    // supported_automatic. Значения приходят от сервера; интерфейс их не домысливает.
    // Alpha 2.840: подпись называет ИСТОЧНИК автоматического пути — то, чем Farm Manager
    // доказывает выполнимость: встроенная команда Klipper, макрос принтера, либо операция
    // вообще не наша (её делает стартовый макрос или сам файл). Всё недоказанное подписано
    // одинаково честно: автоматический путь не подтверждён — и объяснено, почему именно.
    const klCapNote = (c) => {
        const ru = lang.value === 'ru';
        if (!c) return '';
        const unproven = ru ? 'Автоматический путь не подтверждён: ' : 'The automatic path is not confirmed: ';
        if (c.state === 'file_controlled')
            return c.state_reason === 'file_start_macro'
                ? (ru ? 'Управляется стартовым макросом или файлом' : 'Controlled by the start macro or the file')
                : (ru ? 'Уже задано в файле' : 'Already set in the file');
        if (c.state === 'supported_manual')
            return unproven + (c.state_reason === 'vendor_override'
                ? (ru ? 'команда переопределена макросом принтера и выполняется только вручную' : 'the command is overridden by a printer macro and can only be run manually')
                : (ru ? 'операция выполняется только вручную на принтере' : 'the operation can only be run manually on the printer'));
        if (c.state === 'detected')
            return unproven + (ru ? 'команда найдена, но настройка не подтверждена' : 'the command was found but its configuration was not confirmed');
        if (c.state === 'supported_automatic')
            return c.source === 'klipper_builtin'
                ? (ru ? 'Встроенная команда Klipper — выполнится до отправки файла' : 'Klipper built-in — runs before the file is sent')
                : (ru ? 'Макрос принтера — выполнится до отправки файла' : 'Printer macro — runs before the file is sent');
        return ru ? 'Не поддерживается' : 'Not supported';
    };

    const printFileOn = async (filename, printerId, amsSlot, source = 'plan', partName = '', print_opts = undefined) => {
        const _trays = wsData.value[printerId]?.ams_trays || [];
        // Если у принтера есть AMS и слот ещё не выбран — показываем шаг выбора слота
        if (_trays.length && amsSlot === undefined) {
            amsSelectFor.value = { filename, printerId, source, partName };
            return;
        }
        // Alpha 2.687: окно параметров запуска ПЕРЕД отправкой. После «Печать» этот же вызов повторяется с print_opts.
        if (print_opts === undefined) {
            printMenuUid.value = null; amsSelectFor.value = null;
            // Alpha 2.723: предвыбор источника в окне — из уже выбранного слота; итоговый источник (srcSlot)
            // окно возвращает вторым аргументом (-1 внешняя / null авто / число — слот) и он ЗАМЕНЯЕТ amsSlot.
            openPrintStart({ printerId, label: (partName || filename), source, amsSlot: (amsSlot === undefined ? null : amsSlot), onConfirm: (opts, srcSlot) => printFileOn(filename, printerId, (srcSlot === undefined ? (amsSlot === undefined ? null : amsSlot) : srcSlot), source, partName, opts) });
            return;
        }
        printMenuUid.value = null;
        amsSelectFor.value = null;
        const _lbl = partName || filename;
        const _ctx = { printer_id: printerId, printer_name: _printerNameOf(printerId), file_name: _lbl, source: 'task' };
        try {
            const body = { printer_id: printerId, gcode_file: filename, source };
            if (partName) body.part_name = partName;
            if (amsSlot !== undefined && amsSlot !== null) body.ams_slot = Number(amsSlot);
            if (print_opts) body.print_opts = print_opts;   // Alpha 2.687: опции запуска (только Bambu); тот же body в retry ниже
            const resp = await (await fetch('/api/part/print', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
            // Alpha 2.728: accepted → строка в панели отправок (без блокировки UI); 409 → тост; incompatible/low_filament → как раньше.
            if (resp.status === 'incompatible') {
                if (await askConfirm({ title: _L('Принтер не тот', 'Wrong printer'), text: tr(resp.reason || 'The file is sliced for a different printer type.'), okText: _L('Печатать всё равно', 'Print anyway') })) {
                    body.force = true; handleSendResp(await (await fetch('/api/part/print', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json(), _ctx);
                }
            } else if (resp.status === 'low_filament') {
                const lines = (resp.shortfall || []).map(sh => (((sh.material || '') + ' ' + (sh.color_name || '')).trim() || tr('the spool')) + '  —  ' + Math.round(sh.available || 0) + ' / ' + Math.round(sh.needed || 0) + ' ' + tr('grams'));
                if (await askConfirm({ title: _L('Филамента может не хватить', 'Filament may run out'), text: tr('Not enough filament on the bound spool. Print anyway?'), list: lines.join('\n'), okText: _L('Печатать всё равно', 'Print anyway') })) {
                    body.skip_filament = true; handleSendResp(await (await fetch('/api/part/print', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json(), _ctx);
                }
            } else if (handleSendResp(resp, _ctx) === 'other') {
                pushToast(tr('Print not started. ') + tr(resp.reason || ''), 'info');
            }
        } catch (e) { pushToast(tr('Could not start print.'), 'info'); }
    };

    const isPreviewable = (n) => /[.](3mf|gcode|stl|obj)$/i.test(n || '');
    const THUMB_FALLBACK = "data:image/svg+xml;charset=utf-8," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#5b5b62" stroke-width="1.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>');
    const onThumbErr = (e) => {
        // не прячем иконку: одна повторная попытка (превью могло ещё генерироваться), затем запасная иконка
        const img = e.target;
        if (!img) return;
        if (img.dataset.fb === '1') return;
        const n = parseInt(img.dataset.try || '0', 10);
        if (n < 1) {
            img.dataset.try = String(n + 1);
            const base = img.src.split('&_r=')[0];
            setTimeout(() => { img.src = base + '&_r=' + Date.now(); }, 900);
            return;
        }
        img.dataset.fb = '1';
        img.src = THUMB_FALLBACK;
    };
    const isSliceable = (n) => /[.](stl|3mf|obj|step|stp)$/i.test(n || '');
    const addToSlicer = async (f) => {
        if (f._slicing) return;
        f._slicing = true;
        try {
            const send = () => fetch('/api/staging/' + encodeURIComponent(f.filename) + '/slice', { method: 'POST' }).then(r => r.json());
            let j = await send();
            if (j.status === 'no_slicer') {
                if (await askConfirm({ title: _L('Слайсер не найден', 'Slicer not found'), text: tr('Slicer not found automatically. Select the slicer program (.exe) manually?'), okText: _L('Выбрать программу', 'Choose program') })) {
                    const pr = await (await fetch('/api/slicer/pick', { method: 'POST' })).json();
                    if (pr.status === 'ok' && pr.path) {
                        loadSlicers();
                        j = await send();
                    } else if (pr.status === 'error') {
                        alert(tr(pr.reason || 'Failed to set the slicer.'));
                    }
                }
            }
            if (j.status === 'error') alert(tr('Failed to open in slicer: ') + tr(j.reason || ''));
        } catch (e) {
        } finally {
            f._slicing = false;
        }
    };
    const slicerList = ref([]);
    const slicerChoice = ref('');
    const loadSlicers = async () => {
        try {
            const j = await (await fetch('/api/slicer/list')).json();
            slicerList.value = j.slicers || [];
            slicerChoice.value = j.choice || '';
        } catch (e) {}
    };
    const chooseSlicer = async (e) => {
        const v = (e && e.target) ? e.target.value : slicerChoice.value;
        if (v === '__pick__') {
            await loadSlicers();          // вернуть select на текущий выбор (не оставлять «Выбрать вручную…»)
            openExplorerForSlicer();      // выбор .exe слайсера через НАШ Проводник вместо системного окна
            return;
        }
        try {
            await fetch('/api/slicer/choose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: v }) });
            slicerChoice.value = v;
        } catch (err) {}
    };
    const revealStaging = (filename) => { const f = (stagingFiles.value || []).find(x => x.filename === filename); exReveal(f ? (f.src_path || '') : ''); }
    //  2.977 (R-097): где лежит файл детали проекта. Деталь знает свою плиту (имя файла),
    //  а путь спрашиваем у сервера отдельно (2.978): в дереве проекта путей больше нет —
    //  его читает и наблюдатель, а показывать ему устройство фермы незачем.
    const revealPart = async (pr, pp) => {
        const plate = ((pp && pp.plates) || [])[0];
        const fileId = plate && (plate.file_id || '');
        if (!pr || !fileId) { pushToast(_L('Файл этой детали на диске не найден.', 'The part file was not found on disk.'), 'warn'); return; }
        try {
            const j = await (await fetch('/api/projects2/' + encodeURIComponent(pr.id)
                                         + '/files/' + encodeURIComponent(fileId) + '/locate',
                                         { method: 'POST' })).json();
            if (j && j.status === 'ok' && j.path) { exReveal(j.path); return; }
        } catch (e) {}
        pushToast(_L('Файл этой детали на диске не найден.', 'The part file was not found on disk.'), 'warn');
    };
    const markStagingDirty = (f, field) => {
        const cur = { ...(stagingDirty.value[f.filename] || {}) };
        cur[field || 'notes'] = true;
        stagingDirty.value = { ...stagingDirty.value, [f.filename]: cur };
    };
    // Статус Tasks: печатает → IN PROGRESS; набрано нужное кол-во → DONE; иначе PENDING
    // ===== ЕДИНАЯ синхронизация статуса детали со статусом печатающего принтера =====
    // Живой статус принтера(ов), печатающего деталь: RUNNING > PREPARE > пауза/прочее-активное; '' если никто.
    const liveJobStatus = (ids) => {
        const wd = wsData.value || {};
        let prep = false, other = '';
        for (const id of (ids || [])) {
            const st = wd[id] && wd[id].status;
            if (st === 'RUNNING') return 'RUNNING';
            else if (st === 'PREPARE') prep = true;
            else if (st && !['OFFLINE','IDLE','FINISH','READY','STANDBY','OPERATIONAL'].includes(st) && !other) other = st;
        }
        return prep ? 'PREPARE' : other;
    };
    // Ключ статуса детали с цветом, синхронизированным с принтером: печать→зелёный, подготовка→синий, пауза→жёлтый.
    const liveStatusKey = (ids, ownKey) => { const s = liveJobStatus(ids); return s === 'RUNNING' ? 'printing' : s === 'PREPARE' ? 'preparing' : (s === 'PAUSE' || s === 'PAUSED') ? 'paused' : s ? 'in_progress' : ownKey; };
    // Метка статуса детали: если печатается — ровно та же, что на принтере (tr(status)); иначе — собственная метка.
    const liveStatusLabel = (ids, ownLabel) => { const s = liveJobStatus(ids); return s ? tr(s) : ownLabel; };
    //  15.09.2026: «отправка» сильнее «ожидания» и «готово» (повторный запуск готовой задачи тоже виден),
    //  но слабее «в процессе» — печать уже подтверждена.
    const _stagingOwnKey = (f) => { if (f.status === 'printing') return 'in_progress'; if (fileSendState(f && f.filename)) return 'sending'; const req = Number(f.required_qty) || 0, prnt = Number(f.printed_qty) || 0; return (req > 0 && prnt >= req) ? 'done' : 'pending'; };
    const stagingStatusKey = (f) => liveStatusKey(printersPrintingFile(f), _stagingOwnKey(f));
    const stagingStatusLabel = (f) => { const k = _stagingOwnKey(f); const own = k === 'in_progress' ? tr('IN PROCESS') : k === 'sending' ? tr('SENDING') : (k === 'done' ? tr('DONE') : tr('PENDING')); return liveStatusLabel(printersPrintingFile(f), own); };
    //  Подсказка у бейджа: печатает — «показать принтер»; отправляется — стадия отправки словами панели.
    const stagingStatusTitle = (f) => { if (printersPrintingFile(f).length) return tr('Show printer'); const s = fileSendState(f && f.filename); return s ? sendStateLabel(s) : ''; };
    // ЕДИНЫЙ механизм «кто печатает этот файл»: по живым статусам принтеров (RUNNING/PREPARE) сверяем
    // имя печатаемого файла с нужным. Откуда запущена печать (План / ячейка принтера / Задачи)
    // значения не имеет — смотрим только на то, что принтер печатает прямо сейчас. Имя у принтера
    // приходит без расширения, поэтому снимаем расширение и у искомого файла.
    const _bareName = (n) => String(n || '').replace(/[.]gcode[.]3mf$/i, '').replace(/[.]gcode$/i, '').replace(/[.]3mf$/i, '').replace(/[.]gx$/i, '');
    // Ключ сравнения имён: буквы/цифры ЛЮБОГО алфавита (раньше [a-z0-9] — кириллические имена
    // схлопывались в пустой/частичный ключ: «Деталь-01» и «Кузов-01» давали один ключ «01» и
    // подсвечивали чужой принтер). NFC — та же нормализация, что у _pc_match_key на сервере.
    const _normName = (s) => String(s || '').normalize('NFC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
    const printersPrintingFileName = (filename) => {
        const out = [];
        const target = _normName(_bareName(filename));
        if (!target) return out;
        const wd = wsData.value || {};
        for (const pid in wd) {
            const st = wd[pid];
            if (st && (st.status === 'RUNNING' || st.status === 'PREPARE') && _normName(st.file_name) === target) out.push(pid);
        }
        return out;
    };
    // Tasks: тот же набор + последний известный printer_id из БД (страховка от рассинхрона имени).
    const printersPrintingFile = (f) => {
        const set = new Set(printersPrintingFileName(f && f.filename));
        if (f && f.printer_id) set.add(f.printer_id);
        return Array.from(set);
    };
    // Tasks: число ЗАПУЩЕННЫХ gcode по этому файлу = сколько принтеров печатают его прямо
    // сейчас (живой подсчёт по статусам). Файл = одна плита = один gcode, деталями НЕ умножаем.
    const liveStagingPrintingQty = (f) => printersPrintingFileName(f && f.filename).length;
    // Проект (деталь): по каждой плате детали — число принтеров, печатающих эту плату, × количество детали на плате.
    const livePartPrintingQty = (pp) => {
        let n = 0;
        for (const pl of ((pp && pp.plates) || [])) n += printersPrintingFileName(pl.filename).length * (pl.on_plate_qty || 0);
        return n;
    };
    // Plan: тот же единый механизм по gcode_file детали. Значок «в процессе» и подсветку принтеров
    // берём отсюда (а не из active_jobs) — поэтому работает независимо от источника запуска печати.
    //  Alpha 2.894: быстрая правка количества кнопками. Шаг ровно один — на ферме меняют
    //  поштучно. Ниже нуля не опускаемся: отрицательный план не имеет смысла, а «напечатано»
    //  меньше нуля сломало бы прогресс и списание.
    //  Alpha 2.900: серия нажатий сводится в ОДНО сохранение. Раньше пять быстрых кликов
    //  давали пять одновременных запросов с абсолютным значением — они приходят на сервер не в
    //  том порядке, в каком нажаты, и последним мог записаться не последний. Значение на экране
    //  меняется сразу, запрос уходит через паузу.
    const _stepTimers = {};
    const stepStagingQty = (f, field, delta) => {
        if (!f || (field !== 'required_qty' && field !== 'printed_qty')) return;
        if (!can('project')) return;
        const cur = Math.max(0, Number(f[field]) || 0);
        const next = Math.max(0, cur + Number(delta || 0));
        if (next === cur) return;
        f[field] = next;
        markStagingDirty(f, field);
        const key = String(f.filename || '') + ':' + field;
        if (_stepTimers[key]) clearTimeout(_stepTimers[key]);
        _stepTimers[key] = setTimeout(() => { delete _stepTimers[key]; saveStaging(f, [field]); }, 350);
    };

    //  Alpha 2.895: заметные проблемы задачи. Сервер считал признаки беды и отдавал их наверх
    //  всегда, а экран молчал: задача с исчезнувшим файлом выглядела точно как исправная, и о
    //  беде владелец узнавал в момент неудачного запуска печати. Здесь ТОЛЬКО то, что известно
    //  наверняка: файла нет на диске, и файл не подходит ни одному принтеру фермы. Догадок нет.
    //  Причины, по которым не распознан состав плиты, приходят ключом (part_reason); человеческий
    //  текст живёт здесь, а незнакомый ключ показывается как есть — сырой ключ лучше выдумки.
    const PART_REASON_TEXT = {
        disabled: 'plate contents parsing is turned off in settings',
        unsupported_format: 'this file format is not parsed',
        malformed_metadata: 'the service data inside the file is damaged or unreadable',
        object_names_missing: 'the file has no object names',
        object_identity_ambiguous: 'object names repeat and cannot be told apart',
        too_many_objects: 'too many objects on the plate',
        layer_boundaries_missing: 'the file has no layer marks',
        archive_limit_exceeded: 'the file is too large to parse',
        time_limit_exceeded: 'parsing took too long and was stopped',
    };
    const stagingPartReason = (f) => {
        const key = String((f && f.part_reason) || '').trim();
        if (!key) return '';
        const known = PART_REASON_TEXT[key];
        return known ? tr(known) : key;
    };
    const stagingProblems = (f) => {
        const out = [];
        if (!f) return out;
        if (f.missing) {
            out.push({ key: 'missing', level: 'bad', label: tr('file is gone'),
                       tip: tr('The file of this task is not on disk any more. Printing it will not start. Put the file back or delete the task.') });
        } else if (f.is_printable && (printers.value || []).length
                   && Array.isArray(f.compatible_pids) && !f.compatible_pids.length) {
            //  Сюда попадаем, только когда принтеры на ферме ЕСТЬ: на пустой ферме это не беда
            //  задачи, а просто ещё не добавленные принтеры.
            out.push({ key: 'nofit', level: 'warn', label: tr('no printer fits'),
                       tip: tr('This file is sliced for a printer that is not on the farm: the model or the nozzle does not match any of yours.') });
        }
        return out;
    };
    const stagingProblemCount = computed(
        () => (stagingFiles.value || []).reduce((n, f) => n + (stagingProblems(f).length ? 1 : 0), 0));

    //  2.928: сохранение ПО-ПОЛЕВОЕ. Шлётся только то, что владелец правил, — счёт печати,
    //  который он не трогал, не может быть затёрт устаревшей экранной копией.
    const saveStaging = async (f, fields) => {
        const list = (fields && fields.length) ? fields : ['required_qty', 'printed_qty', 'notes'];
        const body = { filename: f.filename };
        const cur = { ...(stagingDirty.value[f.filename] || {}) };
        for (const k of list) {
            cur[k] = true;                              // метка синхронно ДО запроса
            if (k === 'notes') { body.notes = f.notes || ''; continue; }
            const n = Math.max(0, Number(f[k]) || 0);
            f[k] = n;                                   // пустое/отрицательное → 0
            body[k] = n;
        }
        stagingDirty.value = { ...stagingDirty.value, [f.filename]: cur };
        try {
            await fetch('/api/staging/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        } catch (e) {}
        // Снимаем метки сохранённых полей после паузы, дав серверу отдать значение в ближайшем fetch
        setTimeout(() => {
            const d = { ...stagingDirty.value };
            const rec = { ...(d[f.filename] || {}) };
            for (const k of list) delete rec[k];
            if (Object.keys(rec).length) d[f.filename] = rec; else delete d[f.filename];
            stagingDirty.value = d;
        }, 3000);
    };


    //  ── Alpha 2.947: синхронизация задачи с проектом ────────────────────────────────────────
    //  Значок появляется только у задачи, чья модель есть в проекте. Выключен — печать считается
    //  ТОЛЬКО в задаче; включён — и в задаче, и в проекте. Правило одинаково для печати из
    //  программы и для повторной печати с экрана принтера.
    const stagingSyncTip = (f) => {
        const pn = (f && f.project_name) ? f.project_name : tr('a project');
        return (f && f.project_sync)
            ? tr('Synced with project') + ': ' + pn + '. ' + tr('Every print counts in the task and in the project. Click to turn off.')
            : tr('This model is in project') + ': ' + pn + '. ' + tr('Prints count only in the task. Click to also count them in the project.');
    };
    //  2.951: цвет рельсы-кнопки в строке задачи (3.0) = бакет статуса, тот же, что у бейджа.
    const ui3RailClass = (f) => { const k = stagingStatusKey(f); if (k === 'sending') return 'st-send'; const b = _statusBucket(k); return b === 'green' ? 'st-done' : b === 'blue' ? 'st-run' : b === 'red' ? 'st-bad' : 'st-wait'; };
    //  2.953 (концепт З1): заметка задачи в 3.0 правится НА МЕСТЕ — второй строкой под именем.
    //  ui3NoteEditFor — имя файла, чья заметка сейчас в поле; Esc возвращает прежний текст.
    //  ── 2.961: строка детали в проектах повторяет строку задачи. Чтобы показать в ней ту же
    //  кнопку синхронизации и тот же значок беды, надо знать, какая ЗАДАЧА печатает эту деталь.
    //  Указатель строится один раз на список задач: проект + имя детали -> файл задачи.
    const _partTaskIndex = computed(() => {
        const m = {};
        for (const f of (stagingFiles.value || [])) {
            if (!f || !f.project_id) continue;
            for (const pt of (f.parts || [])) {
                const k = f.project_id + '\u0000' + _normName(partDisplayName(pt.name));
                if (!m[k]) m[k] = f;
            }
        }
        return m;
    });
    const ui3PartTask = (pid, pp) => (pid && pp)
        ? (_partTaskIndex.value[pid + '\u0000' + _normName(partDisplayName(pp.part_name))] || null) : null;
    //  Цвет рельсы у детали — тот же бакет состояния, что у бейджа: сине — печатается, зелено —
    //  готово, жёлто — ждёт, красно — беда.
    //  15.09.2026: деталь проекта показывает «отправка», пока по любой из её плит идёт отправка
    //  (тот же источник, что у задач). «В процессе» с сервера сильнее: печать уже подтверждена.
    const p2PartSending = (pp) => ((pp && pp.plates) || []).some(pl => !!fileSendState(pl && pl.filename));
    const p2PartOwnKey = (pp) => { const s = (pp && pp.status) || 'pending'; return (s !== 'in_progress' && p2PartSending(pp)) ? 'sending' : s; };
    const p2PartOwnLabel = (pp) => { const k = p2PartOwnKey(pp); return k === 'in_progress' ? tr('in process') : k === 'sending' ? tr('sending') : tr(k); };
    const ui3PartRailClass = (pp) => {
        const k = liveStatusKey(pp && pp.live_printers, p2PartOwnKey(pp));
        if (k === 'sending') return 'st-send';
        const b = _statusBucket(k);
        return b === 'green' ? 'st-done' : b === 'blue' ? 'st-run' : b === 'red' ? 'st-bad' : 'st-wait';
    };
    //  Кнопки «−/+» у детали: то же сохранение по полю, что и в правке проекта.
    const stepPartQty = (pid, pp, field, d) => {
        if (!pp) return;
        pp[field] = Math.max(0, (Number(pp[field]) || 0) + d);
        saveProject2PartField(pid, pp, field);
    };
    const ui3PartPct = (pp) => {
        const req = Number(pp && pp.required_qty) || 0, done = Number(pp && pp.printed_qty) || 0;
        return req > 0 ? Math.max(0, Math.min(100, Math.round(done * 100 / req))) : 0;
    };
    const ui3NoteEditFor = ref('');
    let _ui3NoteOrig = '';
    //  Ключ правки заметки: у задачи это имя файла, у детали проекта — «pt:<id>».
    const ui3NoteStart = (f, key) => {
        if (!f || !can('project')) return;
        _ui3NoteOrig = f.notes || '';
        ui3NoteEditFor.value = key || f.filename;
        nextTick(() => { try { const el = document.querySelector('.pvrow input.ui3-qtnote.editing'); if (el) { el.focus(); const n = el.value.length; el.setSelectionRange(n, n); } } catch (e) {} });
    };
    const ui3NoteStop = () => { ui3NoteEditFor.value = ''; };
    const ui3NoteCancel = (f, key) => { if (f && ui3NoteEditFor.value === (key || f.filename)) f.notes = _ui3NoteOrig; ui3NoteEditFor.value = ''; };
    const toggleStagingSync = async (f) => {
        if (!f || !f.project_id || !can('project')) return;
        const next = !f.project_sync;
        f.project_sync = next;                       // сразу показываем выбор, не дожидаясь сети
        //  Помечаем поле правящимся: обновление списка по таймеру не должно вернуть старое
        //  значение, пока ответ сервера ещё в пути.
        markStagingDirty(f, 'project_sync');
        try {
            const r = await fetch('/api/staging/sync', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: f.filename, enabled: next })
            });
            const d = await r.json();
            //  Сервер — последняя инстанция: он же проверяет, что проект действительно есть.
            f.project_sync = (d && d.status === 'ok') ? !!d.project_sync : !next;
            //  2.958: неудача — это неудача: показываем её как беду, чтобы панель развернулась сама.
            if (!d || d.status !== 'ok') pushToast(tr('Could not change project sync'), 'warn');
        } catch (e) {
            f.project_sync = !next;
            pushToast(tr('Could not change project sync'), 'info');
        }
        //  Метку снимаем с задержкой — так же, как у остальных полей задачи: сервер успевает
        //  отдать новое значение в ближайшем обновлении списка.
        setTimeout(() => {
            const d2 = { ...stagingDirty.value };
            const rec = { ...(d2[f.filename] || {}) };
            delete rec.project_sync;
            if (Object.keys(rec).length) d2[f.filename] = rec; else delete d2[f.filename];
            stagingDirty.value = d2;
        }, 3000);
    };

    const executePostMatrix = async (endpoint, data) => {
        syncStatus.value = 'saving';
        try { 
            const _r = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }); if (endpoint === '/api/parts/save') partsDirty.value = false;
            //  16.10.2026 (R-020): ответ отдаётся вызывающему — форма принтера разбирает отказ
            //  сервера (неверный адрес); отказ при этом не изображается «сохранено».
            if (_r && _r.ok === false) { syncStatus.value = 'idle'; return _r; }
            syncStatus.value = 'saved'; 
            setTimeout(() => { if (syncStatus.value === 'saved') syncStatus.value = 'idle'; }, 1500);
            return _r;
        } catch (e) { syncStatus.value = 'idle'; } 
    };
    const debouncedSave = () => { 
        partsDirty.value = true; clearTimeout(saveTimeout);
        saveTimeout = setTimeout(() => { 
            parts.value.forEach((p, i) => {
                p.order_idx = i;
                const _req = Number(p.required_qty), _prnt = Number(p.printed_qty);
                if (_req > 0 && _prnt >= _req) {
                    p.status = 'done';
                } else if (p.status === 'done') {
                    p.status = 'pending';
                }
            }); 
            executePostMatrix('/api/parts/save', parts.value); 
        }, 500);
    };

    // ------------------------------------------------------------------------
    // БЛОК: регистрация и редактирование принтера, камеры и всплывающие превью.
    // ------------------------------------------------------------------------
    const printerAddBusy = ref(false);   // защита от дублей: пока идёт добавление/сохранение принтера, повторные клики/Enter игнорируются
    // Alpha 2.831: новый стабильный ID нового принтера. Генерируется КЛИЕНТОМ (как и прежде),
    // но с защитой от коллизий при быстром «Сохранить копию»: время + случайность + проверка,
    // что id ещё не занят. ID ИСХОДНОГО принтера при копировании НЕ переиспользуется.
    const _newPrinterId = () => {
        const used = new Set((printers.value || []).map(x => x.id));
        let id; let guard = 0;
        do { id = 'node_' + Date.now().toString(36) + Math.random().toString(36).substring(2, 7); guard++; }
        while (used.has(id) && guard < 50);
        return id;
    };
    // keepOpen (Alpha 2.831 «Сохранить копию»): тот же verify + тот же create-route, что и обычное
    // «Добавить», но после успеха форма ОСТАЁТСЯ открытой в режиме создания со всеми значениями —
    // пользователь меняет отличающиеся поля и сохраняет следующий экземпляр. Только add mode.
    //  2.971: ЕДИНОЕ место, где собирается список для записи в базу. Раньше каждое
    //  сохранение собирало его само, и одно из трёх (удаление принтера) отправляло массив
    //  как есть — вместе с нарисованными подделками и служебными полями DTO. Так тридцать
    //  «Демо» и оказались в базе владельца, хотя подсказка обещала, что не окажутся.
    //  Теперь путь один, и он пропускает только то, что действительно принтер.
    const _printersPayload = (extraTokenFor = null, token = "") => (printers.value || [])
        .filter(x => x && x.id && !x.__demo && !x.__ui3demo)
        .map(x => {
            const o = { id: x.id, name: x.name, type: x.type, ip: x.ip, port: x.port,
                        gen: x.gen || "auto", serial: x.serial || "", model: x.model || "" };
            if (extraTokenFor && x.id === extraTokenFor && token) o.token = token;
            return o;
        });
    const addPrinterNode = async (keepOpen = false) => {
        if (!newPrinter.value.name || !newPrinter.value.ip || !newPrinter.value.model) return;
        if (printerAddBusy.value) return;   // запрос уже идёт (verify/save может длиться секунды) — не создаём дубль по повторному нажатию
        if (keepOpen && editingPrinterId.value) return;   // «Сохранить копию» существует ТОЛЬКО в режиме создания
        //  16.10.2026 (R-020): неполный адрес не сохраняется и не пробуется — ошибка уже видна под полем.
        if (newPrinter.value.type !== 'demo' && printerAddressProblem(newPrinter.value.ip)) return;
        printerAddBusy.value = true;
        try {
            // Проверка типа: реально ли по адресу принтер выбранного типа (ловим «выбран Bambu, а там Klipper» и наоборот).
            try {
                const _vr = await fetch('/api/printer/verify', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ip: newPrinter.value.ip, type: newPrinter.value.type, port: newPrinter.value.port ? parseInt(newPrinter.value.port, 10) : null }) });
                if (_vr.ok) {
                    const _v = await _vr.json();
                    //  16.10.2026 (R-020): сервер адрес не принял и пробовать его не стал — ошибка под полем.
                    if (_v.bad_address) { printerAddrServerProblem.value = { ip: String(newPrinter.value.ip == null ? '' : newPrinter.value.ip).trim(), problem: _v.address_problem || 'bad' }; return; }
                    if (_v.address_warning === 'global') pushToast(_L('Адрес не из локальной сети. Если ферма подключена не через VPN, проверьте адрес.', 'The address is not on the local network. Unless the farm is reached over a VPN, check the address.'), 'warn', 6000);
                    const _tn = { bambu: 'Bambu', klipper: 'Klipper', flashforge: 'FlashForge', creality: 'Creality' };
                    if (_v.reachable && _v.match === false && _v.detected === 'creality' && newPrinter.value.type === 'klipper') {
                        //  12.10.2026: Moonraker на адресе нет, а родная служба Creality отвечает — заводская
                        //  прошивка без root. Предлагаем подключить через службу Creality.
                        if (!(await askConfirm({ title: _L('Принтер на заводской прошивке Creality', 'Creality stock firmware'),
                            text: _L('На этом адресе отвечает служба Creality, а Moonraker нет — похоже, это заводская прошивка без root. Подключить принтер через службу Creality (как Creality Print)?',
                                     'The Creality service answers at this address, but Moonraker does not — this looks like stock firmware without root. Connect the printer through the Creality service (like Creality Print)?'),
                            okText: _L('Подключить через службу Creality', 'Use the Creality service') }))) return;   // отказ — форма остаётся открытой
                        newPrinter.value.type = 'creality';
                        newPrinter.value.port = null;
                    } else if (_v.reachable && _v.match === false && _v.detected) {
                        if (!await askConfirm({ title: _L('На этом адресе другой принтер', 'A different printer answers'),
                            text: tr('A different printer type responds at this address: ') + (_tn[_v.detected] || _v.detected) + tr('. Save with the selected model anyway?'),
                            okText: _L('Сохранить как есть', 'Save anyway') })) return;
                    } else if (!_v.reachable) {
                        pushToast(tr('Printer not reachable yet — check power and network.'), 'warn', 4000);
                    }
                }
            } catch (e) {}
            const _port = newPrinter.value.port ? parseInt(newPrinter.value.port, 10) : null;
            // Alpha 2.777: введённый токен НЕ попадает в общий массив printers.value — он живёт
            // только в состоянии открытой формы и уходит одним payload'ом. Сам массив теперь
            // приходит из безопасного DTO и поля token не содержит вовсе.
            let _editedId = editingPrinterId.value;
            if (_editedId) {
                const _p = printers.value.find(x => x.id === _editedId);
                if (_p) { _p.name = newPrinter.value.name; _p.type = newPrinter.value.type; _p.ip = newPrinter.value.ip; _p.port = _port; _p.gen = newPrinter.value.gen || "auto"; _p.serial = newPrinter.value.serial || ""; _p.model = newPrinter.value.model || ""; }
            } else {
                _editedId = _newPrinterId();   // всегда НОВЫЙ уникальный id; id источника не наследуется
                printers.value.push({ id: _editedId, name: newPrinter.value.name, type: newPrinter.value.type, ip: newPrinter.value.ip, port: _port, gen: newPrinter.value.gen || "auto", serial: newPrinter.value.serial || "", model: newPrinter.value.model || "" });
            }
            // Payload собираем явно: только редактируемые поля. Производные признаки DTO
            // (credential_configured, model_key, cover_url) обратно не отправляем. Токен
            // включаем ТОЛЬКО для изменённого принтера и ТОЛЬКО если человек ввёл непустое
            // значение — пустое поле сервер трактует как «оставить текущее» (Alpha 2.776).
            const _typed = (newPrinter.value.token || "").trim();
            const _sr = await executePostMatrix('/api/printers/save', _printersPayload(_editedId, _typed));
            //  16.10.2026 (R-020): сервер отказал из-за адреса (его проверка строже: имя узла, IPv6).
            //  Форма остаётся открытой с ошибкой под полем, список принтеров — как на сервере.
            if (_sr && _sr.status === 400) {
                let _sj = null; try { _sj = await _sr.json(); } catch (e) {}
                if (_sj && _sj.error === 'bad_address') {
                    //  Отказ про ЭТОТ принтер — ошибка под полем; про другой принтер списка — словами
                    //  с его адресом, чтобы не подсветить исправный адрес в открытой форме.
                    if (!_sj.printer_id || _sj.printer_id === _editedId) {
                        printerAddrServerProblem.value = { ip: String(newPrinter.value.ip == null ? '' : newPrinter.value.ip).trim(), problem: _sj.problem || 'bad' };
                    } else {
                        pushToast(_L('Не сохранено: у другого принтера адрес «', 'Not saved: another printer has the address “') + String(_sj.ip || '') + _L('». ', '”. ') + printerAddrText(_sj.problem || 'bad'), 'warn', 6000);
                    }
                    await fetchStateMatrix();
                    return;
                }
            }
            if (keepOpen) {
                // «Сохранить копию»: форма НЕ закрывается, режим создания сохраняется, значения
                // (adapter/model/поля) остаются заполненными; id созданного принтера в черновик НЕ
                // пишется (черновик — это newPrinter, id ушёл только в массив). Список обновляется в
                // фоне (авторитетное состояние сервера скорректирует оптимистичный push).
                pushToast(tr('Printer added. You can change the fields and save the next copy.'), 'ok', 3500);
                await fetchStateMatrix();
                // остаёмся в add mode: editingPrinterId=null, showAddPrinterModal=true, newPrinter как есть
            } else {
                newPrinter.value = blankPrinterForm();
                editingPrinterId.value = null;
                showAddPrinterModal.value = false;
                copyBaseName.value = '';
                await fetchStateMatrix();
            }
        } finally {
            printerAddBusy.value = false;   // сбрасываем всегда — и при ошибке, и при отмене подтверждения
        }
    };
    //  ── 2.970: виртуальный принтер для проверок (заказ владельца) ──────────────────────
    //  Заводится одной кнопкой: ни адреса, ни кода доступа у него нет и быть не может.
    //  Дальше он ведёт себя как обычный принтер — тот же пульт, те же команды, та же
    //  очередь, тот же счёт в задачах и проектах. Отличие только в том, что печатает он
    //  по часам, а не филаментом: 10 секунд греет стол, 10 сопло, 20 печатает.
    //  Сколько виртуальных принтеров завести за раз — решает владелец (2.971).
    const demoCount = ref(1);
    const setDemoCount = (e) => {
        const el = (e && e.target) ? e.target : null;
        let n = parseInt(el ? el.value : e, 10);
        if (!(n >= 1)) n = 1;
        demoCount.value = Math.max(1, Math.min(50, n));
        //  Поле обязано показывать ровно то число, которое пойдёт в работу. Привязка
        //  односторонняя: если владелец ввёл 0, а в работу идёт 1, само поле останется с нулём
        //  (значение не изменилось — перерисовки нет). Поэтому возвращаем в него итог руками.
        if (el) el.value = String(demoCount.value);
    };
    const addDemoPrinter = async () => {
        if (printerAddBusy.value) return;
        printerAddBusy.value = true;
        try {
            const want = Math.max(1, Math.min(50, parseInt(demoCount.value, 10) || 1));
            let n = (printers.value || []).filter(p => p && p.type === 'demo').length;
            for (let i = 0; i < want; i++) {
                n += 1;
                printers.value.push({ id: _newPrinterId(), name: _L('Виртуальный ', 'Virtual ') + n,
                                      type: 'demo', ip: '', port: null, gen: 'auto', serial: '',
                                      model: _L('Виртуальный принтер', 'Virtual printer') });
            }
            await executePostMatrix('/api/printers/save', _printersPayload());
            showAddPrinterModal.value = false;
            pushToast(_L('Добавлено виртуальных принтеров: ', 'Virtual printers added: ') + want
                + _L('. На них можно запускать печать по-настоящему: 10 секунд нагрев стола, 10 сопла, 20 печать.',
                     '. You can really start prints on them: 10 s bed, 10 s nozzle, 20 s printing.'), 'ok');
            await fetchStateMatrix();
        } finally {
            printerAddBusy.value = false;
        }
    };
    const savePrinterCopy = () => addPrinterNode(true);   // Alpha 2.831: «Сохранить копию»
    const camVideo = ref(null);
    const webrtcFailed = ref(false);
    let _camPc = null;
    const cameraIsWebRTC = computed(() => { const _p = printers.value.find(x => x.id === cameraPrinterId.value); return !!_p && (_p.type === 'klipper' || _p.type === 'creality'); });
    function _stopWebRTC() {
        try { if (_camPc) { _camPc.ontrack = null; _camPc.close(); } } catch (e) {}
        _camPc = null;
        try { if (camVideo.value) camVideo.value.srcObject = null; } catch (e) {}
    }
    async function _startWebRTC(pid) {
        webrtcFailed.value = false;
        try {
            //  16.10.2026 (R-062): как Creality Print 7.3 в локальной сети — без STUN-сервера Google (камера в той
            //  же сети, обращения в интернет больше нет) и с направлением sendrecv, как у родной страницы принтера.
            const pc = new RTCPeerConnection({ iceServers: [] });
            _camPc = pc;
            pc.addTransceiver('video', { direction: 'sendrecv' });
            pc.ontrack = (e) => { if (!camVideo.value) return; const _ms = (e.streams && e.streams[0]) ? e.streams[0] : new MediaStream([e.track]); camVideo.value.srcObject = _ms; camVideo.value.play().catch(() => {}); };
            pc.onconnectionstatechange = () => { if (pc === _camPc && pc.connectionState === 'failed') webrtcFailed.value = true; };
            await pc.setLocalDescription(await pc.createOffer());
            await new Promise((resolve) => {
                if (pc.iceGatheringState === 'complete') return resolve();
                const _t = setTimeout(resolve, 2000);
                pc.addEventListener('icegatheringstatechange', () => { if (pc.iceGatheringState === 'complete') { clearTimeout(_t); resolve(); } });
            });
            if (pc !== _camPc) return;
            const resp = await fetch(`/api/printer/${pid}/webrtc`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'offer', sdp: pc.localDescription.sdp }) });
            if (!resp.ok) throw new Error('signal HTTP ' + resp.status);
            const answer = await resp.json();
            if (!answer || !answer.sdp) throw new Error('no SDP in answer');
            if (pc !== _camPc) return;
            await pc.setRemoteDescription({ type: 'answer', sdp: answer.sdp });
        } catch (e) {
            console.warn('[WebRTC] camera failed, fallback to MJPEG:', e);
            webrtcFailed.value = true;
            _stopWebRTC();
        }
    }
    // ── Alpha 2.858: СТРАХОВОЧНОЕ переподключение штатного окна камеры ─────────────────
    // Восстановление после зависания потока делает сервер и делает прозрачно: владелец потока
    // пересоздаётся внутри, а HTTP-поток зрителя не рвётся (app/camera_hub.py). Здесь закрыт
    // ДРУГОЙ случай — когда рвётся само соединение с сервером: перезапуск программы, обрыв
    // Wi-Fi, спящий ноутбук. Тогда картинка получает ошибку, и без этой страховки окно
    // осталось бы пустым до ручного переоткрытия.
    //
    // ШТОРМА ЗАПРОСОВ НЕТ ПО ПОСТРОЕНИЮ: пауза удваивается (2, 4, 8, 16 с, потолок 20 с),
    // одновременно живёт не больше одной отложенной попытки, а после CAM_RETRY_MAX попыток
    // окно честно перестаёт дёргать сервер и показывает, что связи нет.
    const CAM_RETRY_MAX = 6;
    const camRetry = ref(0);          // сколько неудач подряд
    const camNonce = ref(0);          // меняет адрес, чтобы браузер начал поток заново
    const camGaveUp = ref(false);
    let _camTimer = null;
    const _camClearTimer = () => { if (_camTimer) { clearTimeout(_camTimer); _camTimer = null; } };
    const cameraStreamSrc = computed(() => cameraPrinterId.value
        ? ('/api/printer/' + encodeURIComponent(cameraPrinterId.value) + '/camera'
           + (camNonce.value ? ('?r=' + camNonce.value) : ''))
        : '');
    const onCameraStreamError = () => {
        if (!cameraPrinterId.value || camGaveUp.value || _camTimer) return;
        if (camRetry.value >= CAM_RETRY_MAX) { camGaveUp.value = true; return; }
        camRetry.value += 1;
        const delay = Math.min(20000, 2000 * Math.pow(2, camRetry.value - 1));
        _camTimer = setTimeout(() => { _camTimer = null; if (cameraPrinterId.value) camNonce.value += 1; }, delay);
    };
    const onCameraStreamLoad = () => { camRetry.value = 0; camGaveUp.value = false; };
    const retryCameraNow = () => { _camClearTimer(); camRetry.value = 0; camGaveUp.value = false; camNonce.value += 1; };


    // ── Alpha 2.870, этап 1: показ камеры БЕЗ ПЕРЕКОДИРОВАНИЯ (по выбору) ──────────────
    //  Прежний путь (MJPEG) остаётся выбором по умолчанию и запасным: переключатель
    //  выключен, пока новый путь не проверен на живом принтере. Измерено 23.08.2026:
    //  перекодирование одной камеры стоит ~0,4 ядра, ремукс — в 250 раз меньше, поэтому
    //  именно от этого пути зависит, сколько камер вообще можно показать разом.
    const camFmp4On = ref(false);
    try { camFmp4On.value = localStorage.getItem('farm_cam_fmp4') === '1'; } catch (e) {}
    const camFmp4 = createFmp4Player({ onStatus: (kind, d) => { camFmp4Status.value = kind; if (kind === 'error') camFmp4Reason.value = String((d && d.reason) || ''); } });
    const camFmp4Status = ref('idle');
    const camFmp4Reason = ref('');
    //  P1/P1S отдают собственный поток JPEG (~0,5 кадра в секунду), а не H.264 —
    //  перекладывать там нечего, и переключатель для них не показывается.
    const cameraSupportsFmp4 = (pid) => {
        const p = (printers.value || []).find(x => x && x.id === pid);
        if (!p || String(p.type || '').toLowerCase() !== 'bambu') return false;
        const ser = String(p.serial || '').toUpperCase();
        return !(ser.startsWith('01P') || ser.startsWith('01S'));
    };
    const cameraUsesFmp4 = computed(() => camFmp4On.value && !!cameraPrinterId.value
                                          && cameraSupportsFmp4(cameraPrinterId.value));
    const _startFmp4 = (pid) => {
        camFmp4Status.value = 'starting'; camFmp4Reason.value = '';
        nextTick(() => {
            const el = camVideo.value;
            if (!el) { camFmp4Status.value = 'error'; camFmp4Reason.value = 'no_video_element'; return; }
            camFmp4.start(el, '/api/printer/' + encodeURIComponent(pid) + '/camera.mp4');
        });
    };
    const _stopFmp4 = () => { try { camFmp4.stop(); } catch (e) {} camFmp4Status.value = 'idle'; };
    const setCamFmp4 = (v) => {
        camFmp4On.value = !!v;
        try { localStorage.setItem('farm_cam_fmp4', v ? '1' : '0'); } catch (e) {}
        const pid = cameraPrinterId.value;
        _stopFmp4();
        if (pid && camFmp4On.value && cameraSupportsFmp4(pid)) _startFmp4(pid);
    };
    const openCamera = (p) => { _stopWebRTC(); _stopFmp4(); webrtcFailed.value = false; _camClearTimer(); camRetry.value = 0; camGaveUp.value = false; camNonce.value = 0; cameraPrinterId.value = p.id; if (p.type === 'klipper' || p.type === 'creality') nextTick(() => _startWebRTC(p.id)); else if (camFmp4On.value && cameraSupportsFmp4(p.id)) _startFmp4(p.id); };
    const closeCamera = () => { _stopWebRTC(); _stopFmp4(); _camClearTimer(); camGaveUp.value = false; camRetry.value = 0; cameraPrinterId.value = null; };
    // Превью детали, которая печатается на принтере: берём файл из «Задач»,
    // привязанный к этому принтеру и помеченный как печатающийся (там уже есть превью).
    const printingThumb = (p) => {
        try {
            const f = (stagingFiles.value || []).find(x => x && x.printer_id === p.id && x.status === 'printing' && isPreviewable(x.filename));
            if (f) return '/api/staging/' + encodeURIComponent(f.filename) + '/thumb?v=' + (f.cb || f.mtime || 0);
            const t = wsData.value && wsData.value[p.id] && wsData.value[p.id].thumb;
            return t || null;
        } catch(e) { return null; }
    };
    const _clearThumbClones = () => { document.querySelectorAll('.thumb-pop-clone').forEach(e => e.remove()); };
    const showThumbPop = (ev) => {
        const wrap = ev.currentTarget;
        const src = wrap.querySelector('.thumb-big, .parts-pop');
        if (!src) return;
        _clearThumbClones();
        // Оригинал НЕ двигаем (им управляет Vue). В body показываем КЛОН (position:fixed работает — нет transform-предка).
        const pop = src.cloneNode(true);
        pop.classList.add('thumb-pop-clone');
        pop.classList.remove('hidden');
        pop.style.pointerEvents = 'none';   // клон никогда не перехватывает мышь
        pop.style.visibility = 'hidden';    // позиционируем ДО показа — без вспышки в углу (это и вызывало моргание у кромки)
        pop.style.display = 'block';
        document.body.appendChild(pop);
        const r = wrap.getBoundingClientRect();
        const pw = pop.offsetWidth, ph = pop.offsetHeight;
        const M = 8;
        const vw = window.innerWidth, vh = window.innerHeight;
        //  2.925: предпросмотр задачи (оформление 3.0) стыкуется углом со СТРОКОЙ, а не
        //  висит по центру миниатюры: нижний левый угол попапа = верхний левый угол строки —
        //  так карточка не закрывает данные самой задачи. У верха экрана — под строкой.
        if (pop.classList.contains('ui3-qtzoom')) {
            const rowEl = wrap.closest('.pvrow') || wrap;
            const rr = rowEl.getBoundingClientRect();
            //  Интерфейс может быть в масштабе (zoom на обёртке): координаты строк приходят
            //  экранные, а left/top клона задаются в его собственных, масштабируемых. Делим
            //  на фактический коэффициент, измеренный на самом клоне, — иначе попап уезжает.
            const k = (pop.getBoundingClientRect().width / pw) || 1;
            const phS = ph * k;                     // высота попапа в экранных точках
            let l2 = rr.left, t2 = rr.top - phS;
            if (t2 < M) t2 = rr.bottom;
            if (l2 + pw * k > vw - M) l2 = vw - pw * k - M;
            if (l2 < M) l2 = M;
            pop.style.left = (l2 / k) + 'px';
            pop.style.top = (t2 / k) + 'px';
            pop.style.visibility = 'visible';
            return;
        }
        let left = r.left + r.width/2 - pw/2;
        if (left + pw > vw - M) left = vw - pw - M;
        if (left < M) left = M;
        // Попап деталей раскрываем ВНИЗ из-под имени принтера; превью-картинки — вверх.
        const below = pop.classList.contains('parts-pop');
        let top;
        if (below) {
            top = r.bottom + M;
            if (top + ph > vh - M) top = r.top - ph - M;
        } else {
            top = r.top - ph - M;
            if (top < M) top = r.bottom + M;
            if (top + ph > vh - M) top = vh - ph - M;
        }
        if (top < M) top = M;
        pop.style.left = left + 'px';
        pop.style.top = top + 'px';
        pop.style.visibility = 'visible';
    };
    const hideThumbPop = (ev) => { _clearThumbClones(); };
    const namePop = ref({ show: false, text: '', x: 0, y: 0, below: false });
    const showNamePop = (ev, text) => {
        const el = ev.currentTarget;
        if (el && el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1) return;
        const r = el.getBoundingClientRect();
        const below = r.top < 56;
        namePop.value = { show: true, text: text || '', x: Math.round(r.left + r.width / 2), y: Math.round(below ? r.bottom : r.top), below: below };
    };
    const hideNamePop = () => { if (namePop.value.show) namePop.value = { ...namePop.value, show: false }; };
    const shortFilament = (t) => {
        if (!t) return '';
        const s = String(t).toUpperCase();
        const known = ['PETG','PLA','ABS','ASA','TPU','PA','PC','PVA','HIPS','PET','PP'];
        for (const k of known) { if (s.includes(k)) return k; }
        return s.slice(0, 4);
    };
    const isLightColor = (hex) => {
        if (!hex || typeof hex !== 'string') return false;
        const m = hex.replace('#','');
        if (m.length < 6) return false;
        const r = parseInt(m.slice(0,2),16), g = parseInt(m.slice(2,4),16), b = parseInt(m.slice(4,6),16);
        return (0.299*r + 0.587*g + 0.114*b) > 150;
    };
    const openEditPrinter = (p) => {
        showModal.value = false; activeModalPrinterId.value = null;  // свернуть расширенную карточку, иначе она перекроет окно «Изменить принтер»
        editingPrinterId.value = p.id;
        // Alpha 2.776/2.777: реальный токен во фронтенд больше НЕ приходит вовсе — сервер отдаёт
        // только признак credential_configured. Поле токена открывается пустым: оставить пустым =
        // сохранить действующее значение, ввести новое = заменить.
        editingHasToken.value = !!p.credential_configured;
        // Серийный номер — НЕ секрет: он напечатан на самом принтере и нужен человеку, чтобы
        // проверить настройку Bambu P1 (без него не работает pushall). Поэтому он приходит в DTO
        // и показывается как обычное поле; прятать его было бы ухудшением без причины.
        editingHasSerial.value = false;
        copyBaseName.value = '';   // Alpha 2.831: редактирование существующего — не копия
        newPrinter.value = { name: p.name, type: p.type, ip: p.ip, port: p.port, token: '', gen: p.gen || 'auto', serial: p.serial || '', model: p.model || '' };
        loadPrinterModels();   // Alpha 2.733: подгрузить canonical registry — превью покажет обложку модели; async-загрузка заменит fallback без перезагрузки формы
        showAddPrinterModal.value = true;
    };
    // Alpha 2.831: «Создать копию» — открыть форму СОЗДАНИЯ, заполненную настройками выбранного
    // принтера (persistent editable конфигурация), НО без его stable ID и БЕЗ секрета. Токен во
    // фронтенд не приходит (только признак credential_configured), поэтому реальный код доступа
    // не копируется — поле открывается пустым, пользователь вводит его заново (безопасный контракт
    // формы редактирования не ослабляется). Копируются: имя, adapter, model, ip, port, gen, serial.
    // НЕ копируются: id, статус, задание, ошибки, счётчики, история, привязки склада — их в форме
    // и нет. Исходный принтер НЕ изменяется; в БД ничего не пишется до кнопки сохранения.
    const openCopyPrinter = (p) => {
        showModal.value = false; activeModalPrinterId.value = null;
        editingPrinterId.value = null;            // строго режим СОЗДАНИЯ (add mode), не edit
        editingHasToken.value = false;            // секрет источника недоступен — вводится заново
        editingHasSerial.value = false;
        newPrinter.value = { name: p.name, type: p.type, ip: p.ip, port: p.port, token: '',
                             gen: p.gen || 'auto', serial: p.serial || '', model: p.model || '' };
        copyBaseName.value = String(p.name || '');   // для заголовка «Новый принтер на основе …»
        showModelPicker.value = false;
        loadPrinterModels();
        showAddPrinterModal.value = true;
    };
    // Alpha 2.721: «＋ Добавить принтер» ВСЕГДА открывает чистую форму создания.
    // Причина бага: кнопка шапки лишь переключала showAddPrinterModal, ничего не сбрасывая, —
    // после «Изменить принтер» форма открывалась с данными последнего принтера, а если
    // редактирование было закрыто той же кнопкой («Отмена»), editingPrinterId оставался
    // установленным и «Сохранить» ОБНОВЛЯЛ прежний принтер вместо создания нового.
    const openAddPrinter = () => {
        editingPrinterId.value = null;            // строго режим создания
        editingHasToken.value = false;            // Alpha 2.776: у нового принтера сохранённого секрета нет
        editingHasSerial.value = false;
        copyBaseName.value = '';                  // Alpha 2.831: обычное «Добавить» — не копия
        newPrinter.value = blankPrinterForm();    // новый независимый объект: ни ID, ни данных прошлого принтера
        showModelPicker.value = false;            // временное под-окно выбора модели не переживает переоткрытие
        showAddPrinterModal.value = true;
    };
    //  R-092 (2.980): «Найти в сети». Программа слушает то, что принтеры объявляют о себе
    //  сами, и показывает найденное прямо в форме добавления. Список наполняется ПО МЕРЕ
    //  прихода объявлений, а не в конце: первый Bambu обычно появляется за секунду-две.
    //  Код доступа по сети не приходит — его владелец вводит руками, и об этом сказано прямо.
    const discOpen = ref(false);
    const discInfo = ref({});
    const discBusy = ref(false);
    let discTimer = null;
    const discDevices = computed(() => (discInfo.value && discInfo.value.devices) || []);
    const discStopPoll = () => { if (discTimer) { clearInterval(discTimer); discTimer = null; } };
    const discPoll = async () => {
        try {
            const j = await (await fetch('/api/printer-discovery')).json();
            if (j && j.status === 'ok') {
                discInfo.value = j;
                if (!j.active) discStopPoll();
            }
        } catch (e) { discStopPoll(); }
    };
    const discStart = async () => {
        if (discBusy.value) return;
        discBusy.value = true;
        discOpen.value = true;
        try {
            const j = await (await fetch('/api/printer-discovery/start', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ seconds: 25, ask: true }) })).json();
            if (j && j.status === 'ok') {
                discInfo.value = j;
                discStopPoll();
                discTimer = setInterval(discPoll, 1000);
            } else {
                pushToast(_L('Поиск начать не удалось.', 'Could not start the search.'), 'warn');
            }
        } catch (e) {
            pushToast(_L('Поиск начать не удалось.', 'Could not start the search.'), 'warn');
        }
        discBusy.value = false;
    };
    const discStop = async () => {
        discStopPoll();
        try {
            const j = await (await fetch('/api/printer-discovery/stop', { method: 'POST' })).json();
            if (j && j.status === 'ok') discInfo.value = j;
        } catch (e) {}
    };
    const discClose = () => { discStopPoll(); discOpen.value = false; };
    //  16.10.2026 (R-092): почему поиск мог ничего не найти — обычными словами. Сервер давно
    //  присылает занятые порты и предупреждения, но панель их не показывала, и «найдено 0»
    //  приходило без причины.
    const discWarnLines = computed(() => {
        const j = discInfo.value || {};
        const ru = lang.value === 'ru';
        const out = [];
        const closed = (j.ports || []).filter(p => p && p.open === false).map(p => Number(p.port)).filter(n => n > 0);
        const bambu = closed.filter(n => n === 2021 || n === 1990);
        const other = closed.filter(n => n !== 2021 && n !== 1990);
        if (bambu.length) out.push(ru
            ? 'Порт ' + bambu.join(', ') + ' занят другой программой (обычно Bambu Studio или OrcaSlicer). Если принтер Bambu не нашёлся, закройте слайсер и повторите поиск.'
            : 'Port ' + bambu.join(', ') + ' is used by another program (usually Bambu Studio or OrcaSlicer). If a Bambu printer is missing, close the slicer and search again.');
        if (other.length) out.push(ru
            ? 'Порт ' + other.join(', ') + ' занят другой программой — часть объявлений Klipper и Creality может не дойти.'
            : 'Port ' + other.join(', ') + ' is used by another program — some Klipper and Creality announcements may not arrive.');
        for (const w of (j.warnings || [])) {
            if (!w || w.code === 'port_busy') continue;   // уже сказано выше по списку портов
            if (w.code === 'no_interfaces') out.push(ru ? 'Не найдено ни одной сетевой карты — проверьте, что компьютер подключён к сети.'
                                                        : 'No network adapter found — check that the computer is connected to the network.');
            else out.push((ru ? 'Поиск прервался: ' : 'The search stopped: ') + String(w.text || w.code || ''));
        }
        //  Считаются только ОТВЕТЫ на наши вопросы (ключи «ответ …» в received): на слушатели портов
        //  возвращаются и наши собственные вопросы, и по ним нельзя сказать, что сеть отвечала.
        const rx = Object.entries(j.received || {}).filter(([k]) => String(k).indexOf('ответ ') === 0)
            .reduce((a, [, n]) => a + (Number(n) || 0), 0);
        if (!j.active && !(j.found > 0) && rx > 0) out.push(ru
            ? 'Устройства в сети отвечали (' + rx + '), но ни одно не похоже на принтер.'
            : 'Devices on the network answered (' + rx + '), but none looked like a printer.');
        return out;
    });
    //  Подпись состояния строки: она же объясняет, почему кнопки «Добавить» может не быть.
    const discStateText = (d) => {
        const ru = lang.value === 'ru';
        return ({
            'new': ru ? 'Новый' : 'New',
            'known': ru ? 'Уже заведён' : 'Already added',
            'moved': ru ? 'Сменил адрес' : 'Address changed',
            'conflict': ru ? 'Адрес занят' : 'Address taken',
            'unsupported': ru ? 'Пока не поддерживается' : 'Not supported yet',
        })[d && d.state] || '';
    };
    const discRowNote = (d) => {
        const ru = lang.value === 'ru';
        if (!d) return '';
        if (d.connect_mode === 'cloud') {
            return ru ? 'Принтер в облачном режиме — локально подключиться не получится. Переключите его на экране в режим локальной сети.'
                      : 'The printer is in cloud mode — a local connection will not work. Switch it to LAN mode on the printer screen.';
        }
        if (d.state === 'conflict') {
            return ru ? 'Адрес мог достаться этому принтеру от роутера. Разберитесь, прежде чем что-то менять.'
                      : 'The router may have given this address to another printer. Check before changing anything.';
        }
        if (d.state === 'unsupported') {
            return ru ? 'Программа пока не умеет управлять этой маркой.' : 'This brand is not supported yet.';
        }
        return '';
    };
    //  «Добавить» только ЗАПОЛНЯЕТ форму. Ничего не сохраняется само: владелец вводит код
    //  доступа и жмёт «Зарегистрировать» сам.
    const discUse = (d) => {
        if (!d) return;
        const f = blankPrinterForm();
        f.name = d.name || d.model || (lang.value === 'ru' ? 'Новый принтер' : 'New printer');
        f.type = d.adapter || 'bambu';
        f.ip = d.ip || '';
        f.port = d.port || null;
        f.model = d.model || '';
        f.serial = d.serial || '';
        //  16.10.2026 (R-092): код доступа FlashForge — «серийник:код проверки». Серийник принтер
        //  объявляет сам, поэтому он уже вписан; владельцу остаётся код проверки после двоеточия.
        const _ffSerial = (f.type === 'flashforge') ? String(d.serial || '').trim() : '';
        if (_ffSerial) f.token = _ffSerial + ':';
        newPrinter.value = f;
        discClose();
        if (_ffSerial) {
            pushToast(_L('Форма заполнена. Серийный номер уже вписан в поле кода — допишите после двоеточия код проверки (Printer ID) с экрана принтера.',
                         'The form is filled in. The serial number is already in the code field — add the check code (Printer ID) from the printer screen after the colon.'), 'info');
            return;
        }
        pushToast(_L('Форма заполнена. Код доступа принтер по сети не объявляет — введите его с экрана принтера.',
                     'The form is filled in. The access code is not announced over the network — type it from the printer screen.'), 'info');
    };
    const discRebind = async (d) => {
        if (!d || d.state !== 'moved') return;
        const ru = lang.value === 'ru';
        if (!await askConfirm({
            title: ru ? 'Обновить адрес принтера?' : 'Update the printer address?',
            text: (ru ? 'Адрес изменится с ' : 'The address changes from ') + (d.old_ip || '?')
                  + ' → ' + (d.ip || '?') + (ru ? '. Код доступа, имя и модель не меняются.'
                                                : '. Access code, name and model stay as they are.'),
            okText: ru ? 'Обновить' : 'Update' })) return;
        try {
            const j = await (await fetch('/api/printer-discovery/rebind', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ printer_id: d.printer_id, device_key: d.key }) })).json();
            if (j && j.status === 'ok') {
                pushToast((ru ? 'Адрес обновлён: ' : 'Address updated: ') + j.ip, 'success');
                fetchStateMatrix();
                discPoll();
            } else {
                pushToast(ru ? 'Обновить адрес не удалось.' : 'Could not update the address.', 'warn');
            }
        } catch (e) {
            pushToast(ru ? 'Обновить адрес не удалось.' : 'Could not update the address.', 'warn');
        }
    };

    const toggleAddPrinter = () => {
        // Закрытие кнопкой «Отмена» — тот же сброс режима редактирования, что у клика по фону и Escape.
        if (showAddPrinterModal.value) { showAddPrinterModal.value = false; editingPrinterId.value = null; discClose(); return; }
        openAddPrinter();
    };


    const removePrinterById = async (id) => {
        if (!await askConfirm({ title: tr('Delete this printer?'),
                                text: _L('Принтер исчезнет из списка. Его задачи и история печати останутся.',
                                         'The printer disappears from the list. Its tasks and print history stay.'),
                                okText: _L('Удалить', 'Delete'), danger: true })) return;
        const idx = printers.value.findIndex(x => x.id === id);
        if (idx >= 0) { printers.value.splice(idx, 1); await executePostMatrix('/api/printers/save', _printersPayload()); }
        showAddPrinterModal.value = false; editingPrinterId.value = null;
    };

    // ------------------------------------------------------------------------
    // БЛОК: WebSocket-брокер живых статусов принтеров.
    // При разрыве соединения индикатор становится красным; серверные данные
    // продолжают периодически запрашиваться обычным HTTP.
    // ------------------------------------------------------------------------
    // Alpha 2.786: отказ по правам не должен превращаться в бесконечный реконнект раз в 3 с.
    // Прикладной код закрытия (4401/4403) доходит до браузера ТОЛЬКО если соединение уже было
    // принято — так закрывается сокет при потере доступа на открытом соединении. Отказ на
    // рукопожатии ASGI-сервер отдаёт HTTP-ответом, и браузер видит 1006 без кода, поэтому там
    // переспрашиваем состояние защиты. Отдельного WebSocket-токена нет: ни в localStorage,
    // ни в sessionStorage ничего не сохраняется. При выключенной защите ветка отказа
    // недостижима (enabled=false), и реконнект работает ровно как раньше.
    let wsAuthStopped = false;
    // 16.10.2026 (R-150): сколько раз подряд переподключились после 4401 при действующем входе.
    let wsAuthRetries = 0;
    const connectDataBroker = () => {
        if (wsAuthStopped) return;
        ws = new WebSocket(`${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`);
        ws.onopen = () => wsConnected.value = true;
        ws.onclose = async (e) => {
            wsConnected.value = false;
            let authDenied = !!(e && (e.code === 4401 || e.code === 4403));
            let authed = false;
            try {
                const r = await fetch('/api/auth/status');
                if (r.ok) {
                    const j = await r.json();
                    authEnabled.value = !!j.enabled; authUser.value = j.user || null;
                    authSetupAvailable.value = !!(j.enabled && !j.authenticated && j.setup_available);
                    authed = !!(j.enabled && j.authenticated);
                    if (j.enabled && !j.authenticated) authDenied = true;
                }
            } catch (err) { /* сеть недоступна — это обычный разрыв, реконнектимся */ }
            // 16.10.2026 (R-150): сокет открыт без входа, а защиту включили в соседней вкладке —
            // сервер закрывает его кодом 4401, хотя у браузера вход уже есть (cookie общая).
            // Переподключаемся с новой cookie, но не больше 3 раз подряд; 4403 и «вход нужен»
            // останавливают, как раньше.
            if (authDenied && e && e.code === 4401 && authed && wsAuthRetries < 3) { wsAuthRetries++; authDenied = false; }
            if (authDenied) { wsAuthStopped = true; return; }
            setTimeout(connectDataBroker, 3000);
        };
        ws.onmessage = e => { wsAuthRetries = 0; if (tourActive.value) return; try { wsData.value = JSON.parse(e.data); } catch(err){} };
    };

    
    // Функционал «Отменить» (undo) полностью удалён по запросу пользователя.

    // Единая бакетизация статуса (детали ИЛИ принтера) в цвет: готово=green, ошибка/офлайн=red, подготовка/печать/нарезка=blue, ожидание/пауза=yellow. Единый источник правды для ВСЕХ индикаторов статуса (принтеры / Проекты / Задачи).
    // Alpha 2.791: причины недоступности принтера показываем человеку понятным текстом.
    // Ядро отдаёт стабильные коды (app/printer_state_policy.py); сырая строка прошивки в
    // решении не участвует и остаётся только в диагностической подсказке.
    const READINESS_REASON_RU = {
        'ready': 'Готов к следующему заданию',
        'offline_or_stale': 'Нет свежих данных от принтера',
        'no_status_raw': 'Принтер не сообщил состояние',
        'user_stop_pending': 'Идёт остановка по команде оператора',
        'unknown_transport': 'Тип принтера не распознан',
        'printing': 'Принтер занят печатью',
        'preparing': 'Принтер готовится к печати',
        'paused': 'Печать на паузе',
        'finished_awaiting_clearance': 'Печать завершена — подтвердите очистку стола',
        'job_failed': 'Предыдущее задание завершилось ошибкой',
        'state_unknown': 'Состояние принтера не распознано',
        'send_reservation': 'Идёт отправка задания',
        'in_other_project_run': 'Принтер занят в другом плане',
        'printer_held': 'Принтер удержан',
        'printer_busy': 'Принтер занят печатью — дождитесь, пока он освободится',
    };
    const READINESS_REASON_EN = {
        'ready': 'Ready for the next job',
        'offline_or_stale': 'No fresh data from the printer',
        'no_status_raw': 'Printer did not report its state',
        'user_stop_pending': 'Stop requested by the operator',
        'unknown_transport': 'Printer type not recognized',
        'printing': 'Printer is busy printing',
        'preparing': 'Printer is preparing to print',
        'paused': 'Print is paused',
        'finished_awaiting_clearance': 'Print finished — confirm the plate is cleared',
        'job_failed': 'Previous job finished with an error',
        'state_unknown': 'Printer state not recognized',
        'send_reservation': 'A job is being sent',
        'in_other_project_run': 'Printer is busy in another plan',
        'printer_held': 'Printer is on hold',
        'printer_busy': 'The printer is busy printing — wait until it is free',
    };
    // Причина приходит либо кодом, либо как 'unsafe_state:<код>' — префикс снимаем.
    const readinessReasonText = (code) => {
        const raw = String(code || '');
        const key = raw.indexOf('unsafe_state:') === 0 ? raw.slice('unsafe_state:'.length) : raw;
        const map = (lang.value === 'ru') ? READINESS_REASON_RU : READINESS_REASON_EN;
        return map[key] || key;   // незнакомый код показываем как есть, а не прячем
    };
    const readinessReasonsText = (list) => (list || []).map(readinessReasonText).join(', ');
    const _statusBucket = (s) => (s === 'done' || s === 'FINISH') ? 'green' : (s === 'OFFLINE' || s === 'FAILED' || s === 'error') ? 'red' : (s === 'printing' || s === 'preparing' || s === 'in_progress' || s === 'sending' || s === 'RUNNING' || s === 'PREPARE' || s === 'SLICING') ? 'blue' : 'yellow';
    const dotClass = (k) => { const b = _statusBucket(k); return b === 'green' ? 'd-done' : b === 'blue' ? 'd-print' : 'd-wait'; };   // цвет точки = цвет бейджа (тот же бакет)
    const getStatusStyles = s => { const b = _statusBucket(s); return b === 'green' ? 'text-green-500 bg-green-500/10 shadow-[0_0_6px_rgba(34,197,94,0.1)]' : b === 'blue' ? 'text-blue-400 bg-blue-400/10 shadow-[0_0_6px_rgba(59,130,246,0.1)]' : b === 'red' ? 'text-red-500 bg-red-500/10 shadow-[0_0_6px_rgba(239,68,68,0.1)]' : 'text-yellow-500 bg-yellow-500/10 shadow-[0_0_6px_rgba(234,179,8,0.1)]'; };
    const getStatusIndicator = id => { const b = _statusBucket((wsData.value && wsData.value[id]?.status) || 'OFFLINE'); return b === 'green' ? 'text-green-500 bg-green-500 shadow-[0_0_6px_currentColor]' : b === 'blue' ? 'text-blue-500 bg-blue-500 shadow-[0_0_6px_currentColor]' : b === 'red' ? 'text-red-500 bg-red-500 shadow-[0_0_6px_currentColor]' : 'text-yellow-500 bg-yellow-500 shadow-[0_0_6px_currentColor]'; };
    // Мягкая подсветка всей ячейки цветом статуса (только сетка) — вместо кружка. Низкая прозрачность, не «светофор».
    const getCardTint = id => {
        if (viewMode.value !== 'grid') return '';
        const b = _statusBucket((wsData.value?.[id]?.status) || 'OFFLINE');
        const c = b === 'green' ? '34,197,94' : b === 'blue' ? '59,130,246' : b === 'red' ? '239,68,68' : '234,179,8';
        let css = 'background-image:linear-gradient(180deg,rgba(' + c + ',0.32),rgba(' + c + ',0.18));';
        if (!(activeModalPrinterId.value === id && showModal.value)) css += 'border-color:rgba(' + c + ',0.55);';
        return css;
    };
    const getStatusTextColor = id => { const b = _statusBucket((wsData.value?.[id]?.status) || 'OFFLINE'); return b === 'green' ? 'text-green-400' : b === 'blue' ? 'text-blue-400' : b === 'red' ? 'text-red-400' : 'text-yellow-400'; };
    const getPrinterName = id => (printers.value.find(p => p.id === id) || {}).name || id;
    const convertSecondsToReadable = s => s ? `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m` : '0h 0m';

    // БЛОК: визуальные помощники карточек — статусы, оттенки и SVG-архетипы.
    // Иконка вида принтера в ячейке: оригинальная monoline-графика в стиле остальных значков UI.
    // Сознательно НЕ берём фото производителей: это и лишний вес (single-file), и лицензионные риски
    // при распространении. Архетип выбирается по уже известным полям (type + число сопел + подсказки
    // в имени), поэтому ничего «скачивать» не нужно. Набор и правила легко расширять.
    const PRINTER_ICONS = {
        enclosed: '<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M7 8h10"/><path d="M12 8v1.5"/><path d="M10.8 9.5h2.4l-1.2 1.6z" fill="currentColor"/><path d="M7 16h10"/></svg>',
        dual: '<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M7 8h10"/><path d="M9.6 8v1.4"/><path d="M8.5 9.4h2.2l-1.1 1.5z" fill="currentColor"/><path d="M14.4 8v1.4"/><path d="M13.3 9.4h2.2l-1.1 1.5z" fill="currentColor"/><path d="M7 16h10"/></svg>',
        open: '<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h16"/><path d="M7 20V8"/><path d="M17 20V8"/><path d="M7 8h10"/><path d="M12 8v1.5"/><path d="M10.8 9.5h2.4l-1.2 1.6z" fill="currentColor"/><path d="M8 16h8"/></svg>'
    };
    const printerIcon = p => {
        const t = ((p && p.type) || '').toLowerCase();
        const nm = ((p && p.name) || '').toLowerCase();
        const nc = (wsData.value[p.id]?.nozzle_count) || 0;
        if (t === 'bambu') {
            if (nc >= 2 || nm.includes('h2d') || nm.includes('dual')) return PRINTER_ICONS.dual;  // H2D и двухсопельные
            if (nm.includes('a1')) return PRINTER_ICONS.open;                                      // A1 — открытый bedslinger
            return PRINTER_ICONS.enclosed;                                                         // X1/P1/P1S/P2S — закрытый CoreXY
        }
        if (t === 'flashforge') return PRINTER_ICONS.enclosed;                                     // Adventurer 5M — закрытый
        if (t === 'klipper' || t === 'creality') return svgAssets.printer;   // Alpha 2.635: иконка принтера от владельца (Принтер_01.svg) — та же, что в «Выбрать модель»
        return PRINTER_ICONS.enclosed;
    };
    // Alpha 2.635: иконка плитки «Выбрать модель» = ТОТ ЖЕ источник, что и карточка Klipper (svgAssets.printer от
    // владельца, Принтер_01.svg). Klipper в выборе модели и на карточке рисуются ОДНОЙ И ТОЙ ЖЕ иконкой; безобложечные
    // модели (по сути это generic-Klipper) показывают этот силуэт принтера. Bambu/FlashForge с обложкой — своё фото.
    const modelPickerIcon = (m) => svgAssets.printer;

    // Раскрытие/сворачивание карточки в список-виде: подматываем прокрутку так, чтобы ВЕРХ этой
    // карточки (где имя принтера) остался на том же месте экрана. Тогда карточка раскрывается
    // ТОЛЬКО ВНИЗ: верхняя часть не двигается, нижняя выезжает, а список уходит вниз.
    const _preserveCardCenter = async (refId, mutate) => {
        const el = refId ? document.querySelector('.printer-card[data-pid="' + refId + '"]') : null;
        const scroller = el ? el.closest('.overflow-y-auto') : null;
        let beforeTop = null;
        if (el) { const r = el.getBoundingClientRect(); beforeTop = r.top; }
        mutate();
        await nextTick();
        if (el && scroller && beforeTop != null) {
            const r2 = el.getBoundingClientRect();
            scroller.scrollTop += (r2.top - beforeTop);
        }
    };

    // ------------------------------------------------------------------------
    // БЛОК: раскрытие карточки принтера и загрузка его файлового списка.
    // ------------------------------------------------------------------------
    const openModal = async (id, e) => {
        // Закрытие активной карточки (повторный клик): центр сохраняем → список остаётся на месте.
        if (showModal.value && activeModalPrinterId.value === id) {
            await _preserveCardCenter(id, () => { showModal.value = false; activeModalPrinterId.value = null; });
            return;
        }
        const _wd = wsData.value[id];
        const _isOn = _wd && _wd.status !== 'OFFLINE';
        tempNozzle.value = _wd?.nozzle_target > 0 ? Math.round(_wd.nozzle_target) : (_isOn ? Math.round(_wd.nozzle_temp || 0) : '');
        tempNozzleL.value = _isOn ? Math.round((nozzleById(_wd, 1).temp) || 0) : '';
        tempNozzleR.value = _isOn ? Math.round((nozzleById(_wd, 0).temp) || 0) : '';
        tempBed.value = _wd?.bed_target > 0 ? Math.round(_wd.bed_target) : (_isOn ? Math.round(_wd.bed_temp || 0) : '');
        //  R-104: поле камеры заполняется так же, как сопло и стол (у принтера без камеры оно скрыто).
        tempChamber.value = _wd?.chamber_target > 0 ? Math.round(_wd.chamber_target) : (_isOn ? Math.round(_wd.chamber_temp || 0) : '');
        printFileName.value = ''; 
        printAmsSlot.value = null; cellAmsOpen.value = false;
        printerFiles.value = []; 
        loadingFiles.value = true;
        if (viewMode.value === 'grid') gridPopStyle.value = { visibility: 'hidden' };
        // Открытие/переключение: раздвигаем симметрично — центр этой карточки остаётся на месте.
        await _preserveCardCenter(id, () => { activeModalPrinterId.value = id; showModal.value = true; });
        if (viewMode.value === 'grid') {
            // Полное меню — поповер по центру квадрата (с зажимом в видимую область), без мигания.
            await nextTick();
            const _sq = document.querySelector('.printer-card[data-pid="' + id + '"]');
            const _pop = document.querySelector('.grid-pop');
            if (_sq && _pop) {
                const _r = _sq.getBoundingClientRect();
                const _pw = _pop.offsetWidth, _ph = _pop.offsetHeight, _M = 10;
                let _L = _r.left + _r.width / 2 - _pw / 2;
                _L = Math.max(_M, Math.min(_L, window.innerWidth - _pw - _M));
                let _T = _r.top + _r.height / 2 - _ph / 2;
                _T = Math.max(_M, Math.min(_T, window.innerHeight - _ph - _M));
                gridPopStyle.value = { left: _L + 'px', top: _T + 'px', visibility: 'visible' };
            } else { gridPopStyle.value = { visibility: 'visible' }; }
        }
        try {
            let _r = await (await fetch(`/api/printer/${id}/files`)).json();
            // P1-серия отдаёт очень мало FTP-слотов: при открытой камере список иногда приходит
            // пустым с первого раза. Если пусто и карточка ещё та же — одна повторная попытка.
            if ((!_r || _r.length === 0) && activeModalPrinterId.value === id) {
                await new Promise(r => setTimeout(r, 1500));
                if (activeModalPrinterId.value === id) _r = await (await fetch(`/api/printer/${id}/files`)).json();
            }
            if (activeModalPrinterId.value === id) {
                printerFiles.value = _r || [];
                // Alpha 2.825: «Выбрать для печати» из файлового менеджера — применяем
                // ожидающий выбор к старой выпадашке, если файл реально есть в её списке.
                const _pend = pfCardPending.value;
                if (_pend && _pend.pid === id && printerFiles.value.includes(_pend.name)) printFileName.value = _pend.name;
            }
        } catch(err) {}
        loadingFiles.value = false;
    };
    const printBtnState = ref('');
    //  16.10.2026 (R-145): сервер не выключает нагрев сопла или стола посреди печати без подтверждения
    //  (409 heater_off_while_printing). Спрашиваем один раз на принтер: «Остыть» шлёт сопла и стол
    //  разом, и все отказы этой серии ждут одного ответа.
    let _heatOffAsk = null;
    const _askHeaterOff = (pid) => {
        const now = Date.now();
        if (_heatOffAsk && _heatOffAsk.pid === pid && (!_heatOffAsk.done || now - _heatOffAsk.done < 1000)) return _heatOffAsk.promise;
        const rec = { pid, done: 0, promise: null };
        rec.promise = askConfirm({
            title: _L('Выключить нагрев?', 'Turn heating off?'),
            text: _L('Принтер печатает. Если выключить нагрев сопла или стола, печать сорвётся.',
                     'The printer is printing. Turning the nozzle or bed heater off will ruin the print.'),
            okText: _L('Выключить нагрев', 'Turn heating off'), danger: true,
        }).then((yes) => { rec.done = Date.now(); return yes; });
        _heatOffAsk = rec;
        return rec.promise;
    };
    // БЛОК: единая отправка команд pause/resume/stop/temperature/print принтеру.
    const sendCmd = async (cmd, val='') => { 
        //  13.10.2026: пульт UI3 держит СВОЙ принтер (ui3Printer). После «Изменить → Отмена» общий
        //  activeModalPrinterId сбрасывался, и кнопки пульта молча переставали работать.
        if (!activeModalPrinterId.value && ui3Mode && ui3Printer.value) activeModalPrinterId.value = ui3Printer.value;
        if(!activeModalPrinterId.value) return;
        const _cmdPid = activeModalPrinterId.value;   // 16.10.2026: принтер фиксируем до ответа и окна вопроса
        const body = {cmd, val: String(val)};
        if (cmd === 'start_print') body.ams_slot = (printAmsSlot.value === null || printAmsSlot.value === undefined) ? null : Number(printAmsSlot.value);
        if (cmd === 'start_print') printBtnState.value = 'sending';
        try {
            const r = await fetch(`/api/printer/${activeModalPrinterId.value}/cmd`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
            const j = await r.json().catch(()=>({}));
            // Alpha 2.728: C1 (start_print) идёт через панель отправок; accepted → «отправлено» и окно закрывается,
            // дальше прогресс в панели; 409 → тост; ошибка → строка «Ошибка» в панели. Прочие команды — как раньше.
            if (cmd === 'start_print') {
                const _ctx = { printer_id: activeModalPrinterId.value, printer_name: _printerNameOf(activeModalPrinterId.value), file_name: String(val || '').split(/[\\/]/).pop(), source: 'printer_file' };
                const _applyKind = (kind) => {
                    if (kind === 'accepted') { printBtnState.value = 'sent'; setTimeout(() => { printBtnState.value = ''; showModal.value = false; }, 900); }
                    else if (kind === 'busy') { printBtnState.value = ''; }
                    else { printBtnState.value = 'error'; setTimeout(() => { printBtnState.value = ''; }, 2000); }
                };
                // C1 confirm restore (Alpha 2.728): несовместимый файл без force → ПРЕЖНЕЕ подтверждение (backend
                // проверяет совместимость синхронно, до reservation/job — команда принтеру не уходит). Отмена → ничего
                // не запущено (ни job, ни reservation). Подтверждение → повтор с force=true уходит в общий фоновый
                // механизм (панель отправок); если принтер занят другой вкладкой — придёт 409 (busy → тост).
                if (j && j.status === 'incompatible') {
                    if (await askConfirm({ title: _L('Принтер не тот', 'Wrong printer'), text: tr(j.reason || 'The file is sliced for a different printer type.'), okText: _L('Печатать всё равно', 'Print anyway') })) {
                        body.force = true;
                        _applyKind(handleSendResp(await (await fetch(`/api/printer/${activeModalPrinterId.value}/cmd`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) })).json().catch(()=>({})), _ctx));
                    } else {
                        printBtnState.value = '';
                    }
                    return;
                }
                _applyKind(handleSendResp(j, _ctx));
            } else if (r.status === 409 && j && j.reason === 'heater_off_while_printing') {
                //  16.10.2026 (R-145): выключение нагрева во время печати — только после явного «Выключить».
                if (await _askHeaterOff(_cmdPid)) {
                    body.force = true;
                    const r2 = await fetch(`/api/printer/${_cmdPid}/cmd`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
                    const j2 = await r2.json().catch(()=>({}));
                    if (!r2.ok || (j2 && j2.status && j2.status !== 'ok')) pushToast(cmdFailText(cmd, j2), 'warn');
                }
            } else if (!r.ok || (j && j.status && j.status !== 'ok')) {
                //  13.10.2026: прежде отказ здесь пропадал молча — «Стоп» мог не дойти до принтера, печать
                //  шла дальше, а на экране ничего. Теперь владелец видит, что команда не выполнена.
                pushToast(cmdFailText(cmd, j), 'warn');
            }
        } catch(e) {
            if (cmd === 'start_print') { printBtnState.value = 'error'; setTimeout(()=>printBtnState.value='', 2000); }
            else pushToast(cmdFailText(cmd, null), 'warn');
        }
    };
    const cmdFailText = (cmd, j) => {
        const ru = lang.value === 'ru';
        const why = String((j && (j.reason || j.error)) || '');
        const what = ({ stop: ru ? 'Остановить печать' : 'Stopping the print', pause: ru ? 'Пауза' : 'Pause',
                        resume: ru ? 'Продолжить' : 'Resume', nozzle: ru ? 'Температура сопла' : 'Nozzle temperature',
                        nozzle_l: ru ? 'Температура сопла L' : 'Nozzle L temperature',
                        nozzle_r: ru ? 'Температура сопла R' : 'Nozzle R temperature',
                        bed: ru ? 'Температура стола' : 'Bed temperature',
                        chamber: ru ? 'Температура камеры' : 'Chamber temperature' })[cmd] || (ru ? 'Команда принтеру' : 'Printer command');
        const reason = ({
            stop_not_delivered: ru ? 'принтер не подтвердил остановку — печать может продолжаться, проверьте принтер'
                                   : 'the printer did not confirm the stop — the print may continue, check the printer',
            command_not_confirmed: ru ? 'принтер не подтвердил команду' : 'the printer did not confirm the command',
            //  16.10.2026 (R-145): пауза, продолжение и нагрев теперь тоже проверяют доставку.
            command_not_delivered: ru ? 'команда не дошла до принтера — проверьте связь с ним'
                                      : 'the command did not reach the printer — check the connection to it',
            heater_off_while_printing: ru ? 'принтер печатает — нагрев не выключен, чтобы не сорвать печать'
                                          : 'the printer is printing — heating was not turned off so the print is not ruined',
            unsupported_command: ru ? 'этот принтер такую команду не поддерживает' : 'this printer does not support this command',
        })[why] || (why ? tr(why) : (ru ? 'нет связи с программой' : 'no connection to the program'));
        return what + ': ' + (ru ? 'не выполнено — ' : 'not done — ') + reason;
    };
    const confirmStop = async () => {
        if (await askConfirm({ title: _L('Остановить печать?', 'Stop the print?'),
                               text: tr('Stop the print? The current job will be aborted and cannot be resumed.'),
                               okText: _L('Остановить', 'Stop'), danger: true })) sendCmd('stop');
    };

    //  ── 2.963: пульт принтера по макету владельца ──────────────────────────────────────
    //  Всё, что здесь считается, берётся из того же живого состояния wsData и тех же команд
    //  sendCmd, что и у карточки 2.0: у принтера нет второй логики, есть второй вид. Блок
    //  стоит после sendCmd/confirmStop и полей температур: он на них ссылается.
    const ui3PpP = computed(() => (printers.value || []).find(x => x && x.id === ui3Printer.value) || null);
    const ui3PpS = computed(() => (wsData.value && wsData.value[ui3Printer.value]) || {});
    const _ui3St = () => String(ui3PpS.value.status || '').toUpperCase();
    const ui3PpBusy = computed(() => ['RUNNING', 'PREPARE', 'PAUSED', 'SLICING'].includes(_ui3St()));
    const ui3PpDot = computed(() => {
        const s = _ui3St();
        if (!s || s === 'OFFLINE') return 'off';
        if (s === 'PAUSED') return 'wait';
        if (s === 'FAILED') return 'bad';
        if (s === 'RUNNING' || s === 'PREPARE' || s === 'SLICING') return 'run';
        return 'ok';
    });
    const ui3PpStateText = computed(() => {
        const s = _ui3St(); const ru = lang.value === 'ru';
        const m = ru ? { RUNNING: 'Печатает', PAUSED: 'Пауза', PREPARE: 'Готовится', SLICING: 'Нарезка', FINISH: 'Готово', FAILED: 'Сбой', IDLE: 'Свободен', OFFLINE: 'Не на связи', BUSY: 'Занят' }
                     : { RUNNING: 'Printing', PAUSED: 'Paused', PREPARE: 'Preparing', SLICING: 'Slicing', FINISH: 'Done', FAILED: 'Failed', IDLE: 'Idle', OFFLINE: 'Offline', BUSY: 'Busy' };
        if (!s) return ru ? 'Нет данных' : 'No data';
        return m[s] || s;
    });
    const ui3PpPct = computed(() => Math.min(100, Math.max(0, Math.round(ui3PpS.value.percent || 0))));
    //  Длительность словами: «1 ч 13 мин», «13 мин», «меньше минуты». Вход — секунды.
    const ui3Dur = (sec) => {
        const s = Math.max(0, Math.round(Number(sec) || 0)); const ru = lang.value === 'ru';
        const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
        if (!h && !m) return ru ? 'меньше минуты' : 'under a minute';
        return (h ? h + (ru ? ' ч' : ' h') + (m ? ' ' : '') : '') + (m ? m + (ru ? ' мин' : ' min') : '');
    };
    const _ui3Hm = (d) => { try { return d.toLocaleTimeString(lang.value === 'ru' ? 'ru-RU' : 'en-US', { hour: '2-digit', minute: '2-digit' }); } catch (e) { return ''; } };
    const ui3PpRemainText = computed(() => {
        const s = ui3PpS.value; const ru = lang.value === 'ru'; const st = _ui3St();
        if (st === 'FINISH') return ru ? 'печать закончена' : 'print finished';
        if (st === 'FAILED') return ru ? 'печать прервана' : 'print failed';
        const rm = Number(s.remaining_time || 0);        // минуты — так их присылает сервер
        if (!rm) return ru ? 'осталось: считаю…' : 'remaining: estimating…';
        return (ru ? 'осталось ' : 'remaining ') + ui3Dur(rm * 60);
    });
    const ui3PpFinishText = computed(() => {
        const rm = Number(ui3PpS.value.remaining_time || 0);
        if (!rm || !ui3PpBusy.value) return '';
        return (lang.value === 'ru' ? 'готово к ' : 'done by ') + _ui3Hm(new Date(Date.now() + rm * 60000));
    });
    const ui3PpStartText = computed(() => {
        const el = Number(ui3PpS.value.elapsed || 0);        // секунды от настоящего старта
        return el > 0 ? _ui3Hm(new Date(Date.now() - el * 1000)) : '';
    });
    const ui3PpIdleText = computed(() => {
        const s = _ui3St(); const ru = lang.value === 'ru';
        if (!s) return ru ? 'Данных от принтера пока нет' : 'No data from the printer yet';
        if (s === 'OFFLINE') return ru ? 'Принтер не на связи' : 'The printer is offline';
        return ru ? 'Принтер свободен' : 'The printer is free';
    });
    const ui3PpDeg = (v) => (v == null || ui3PpDot.value === 'off') ? '—' : (Math.round(Number(v) || 0) + '°');
    const ui3PpTgt = (v) => (ui3PpDot.value === 'off') ? '—' : ((Number(v) || 0) > 0 ? Math.round(Number(v)) + '°' : (lang.value === 'ru' ? 'выкл' : 'off'));
    //  Ступени температуры: −/+ меняют цель на 5° и отправляют её принтеру после короткой
    //  паузы, чтобы серия нажатий ушла одной командой, а не пятью.
    //  R-104 (2.983): термокамера. Строка в пульте показывается только у принтеров, у которых
    //  нагрев камеры ЕСТЬ: по модели (список на сервере, поле chamber_heater в списке принтеров)
    //  либо по телеметрии (Creality отдал объект нагревателя). Предел 65° — как в политике команд.
    const tempChamber = ref('');
    const ui3PpChamber = computed(() => {
        const p = ui3PpP.value, s = ui3PpS.value;
        return !!(p && (p.chamber_heater || (s && s.chamber_heater)));
    });
    const _ui3TempRefs = { nozzle: tempNozzle, bed: tempBed, nozzle_l: tempNozzleL, nozzle_r: tempNozzleR, chamber: tempChamber };
    const _ui3TempMax = { nozzle: 320, nozzle_l: 320, nozzle_r: 320, bed: 130, chamber: 65 };
    const _ui3TempTimers = {};
    const ui3TempStep = (kind, delta) => {
        const r = _ui3TempRefs[kind]; if (!r) return;
        const cur = Math.round(Number(r.value) || 0);
        r.value = Math.max(0, Math.min(_ui3TempMax[kind] || 320, cur + delta));
        clearTimeout(_ui3TempTimers[kind]);
        _ui3TempTimers[kind] = setTimeout(() => { sendCmd(kind, r.value); }, 700);
    };
    //  R-103 (2.984): пресеты прогрева ПРАВЯТСЯ оператором и хранятся на сервере — одни на всю
    //  ферму с любого компьютера. Встроенные три остаются умолчанием, пока владелец не сохранил
    //  свои. Поле c — камера, необязательное: шлётся только принтеру с нагревом камеры.
    const _UI3_PRESETS_DEFAULT = [{ name: 'PLA', n: 220, b: 60, c: null }, { name: 'PETG', n: 235, b: 70, c: null }, { name: 'ABS', n: 250, b: 90, c: null }];
    const ui3TempPresets = ref(_UI3_PRESETS_DEFAULT.map(p => ({ ...p })));
    const ui3PresetEdit = ref(false);
    const ui3PresetDraft = ref([]);
    const ui3PresetBusy = ref(false);
    const ui3PresetError = ref('');
    const ui3PresetLimits = { n: [0, 350], b: [0, 120], c: [0, 65] };
    const ui3PresetsFromServer = (arr) => {
        if (!Array.isArray(arr)) return;
        const clean = arr.filter(p => p && typeof p === 'object' && String(p.name || '').trim())
                         .map(p => ({ name: String(p.name).trim().slice(0, 12), n: Number(p.n) || 0, b: Number(p.b) || 0,
                                      c: (p.c === null || p.c === undefined || p.c === '') ? null : (Number(p.c) || 0) }));
        ui3TempPresets.value = clean;
    };
    const ui3PresetTitle = (pr) => {
        const ru = lang.value === 'ru';
        let t = (ru ? 'Сопло ' : 'Nozzle ') + pr.n + '°, ' + (ru ? 'стол ' : 'bed ') + pr.b + '°';
        if (ui3PpChamber.value && pr.c !== null && pr.c !== undefined && pr.c !== '') t += ', ' + (ru ? 'камера ' : 'chamber ') + pr.c + '°';
        return t;
    };
    const ui3PresetEditOpen = () => {
        ui3PresetDraft.value = ui3TempPresets.value.map(p => ({ name: p.name, n: p.n, b: p.b, c: (p.c === null || p.c === undefined) ? '' : p.c }));
        ui3PresetError.value = '';
        ui3PresetEdit.value = true;
    };
    const ui3PresetEditClose = () => { ui3PresetEdit.value = false; ui3PresetDraft.value = []; ui3PresetError.value = ''; };
    const ui3PresetAdd = () => {
        if (ui3PresetDraft.value.length >= 24) return;
        ui3PresetDraft.value.push({ name: '', n: 200, b: 60, c: '' });
    };
    const ui3PresetRemove = (i) => { ui3PresetDraft.value.splice(i, 1); };
    const ui3PresetReset = () => { ui3PresetDraft.value = _UI3_PRESETS_DEFAULT.map(p => ({ name: p.name, n: p.n, b: p.b, c: '' })); };
    const _ui3PresetCheck = () => {
        const ru = lang.value === 'ru';
        const names = new Set();
        for (const p of ui3PresetDraft.value) {
            const name = String(p.name || '').trim();
            if (!name) return ru ? 'У каждого пресета должно быть имя.' : 'Every preset needs a name.';
            if (names.has(name.toLowerCase())) return (ru ? 'Имя повторяется: ' : 'Duplicate name: ') + name;
            names.add(name.toLowerCase());
            for (const k of ['n', 'b', 'c']) {
                const v = p[k];
                if (k === 'c' && (v === '' || v === null || v === undefined)) continue;
                const num = Number(v);
                if (!Number.isInteger(num) || num < ui3PresetLimits[k][0] || num > ui3PresetLimits[k][1]) {
                    const what = k === 'n' ? (ru ? 'сопло' : 'nozzle') : k === 'b' ? (ru ? 'стол' : 'bed') : (ru ? 'камера' : 'chamber');
                    return (ru ? 'Пресет «' : 'Preset “') + name + (ru ? '»: ' : '”: ') + what + ' ' + ui3PresetLimits[k][0] + '…' + ui3PresetLimits[k][1] + '°';
                }
            }
        }
        return '';
    };
    const ui3PresetSave = async () => {
        const why = _ui3PresetCheck();
        if (why) { ui3PresetError.value = why; return; }
        const list = ui3PresetDraft.value.map(p => ({ name: String(p.name).trim().slice(0, 12), n: Number(p.n), b: Number(p.b),
                                                    c: (p.c === '' || p.c === null || p.c === undefined) ? null : Number(p.c) }));
        ui3PresetBusy.value = true;
        try {
            const j = await (await fetch('/api/farm-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                                 body: JSON.stringify({ preheat_presets: list }) })).json();
            if (j && j.ok) {
                ui3PresetsFromServer(j.preheat_presets || list);
                ui3PresetEditClose();
                pushToast(lang.value === 'ru' ? 'Пресеты сохранены — для всех компьютеров фермы' : 'Presets saved for every computer of the farm', 'success');
            } else {
                ui3PresetError.value = (lang.value === 'ru' ? 'Сервер не принял пресеты: ' : 'The server rejected the presets: ') + ((j && j.error) || '');
            }
        } catch (e) {
            ui3PresetError.value = lang.value === 'ru' ? 'Сервер недоступен — пресеты не сохранены.' : 'Server unreachable — presets not saved.';
        }
        ui3PresetBusy.value = false;
    };
    const ui3TempPreset = (pr) => {
        if ((ui3PpS.value.nozzle_count || 1) >= 2) {
            tempNozzleL.value = pr.n; tempNozzleR.value = pr.n; sendCmd('nozzle_l', pr.n); sendCmd('nozzle_r', pr.n);
        } else { tempNozzle.value = pr.n; sendCmd('nozzle', pr.n); }
        tempBed.value = pr.b; sendCmd('bed', pr.b);
        //  R-104: у пресета может быть и камера; шлём её только принтеру с нагревом камеры.
        if (ui3PpChamber.value && pr.c !== undefined && pr.c !== null && pr.c !== '') {
            tempChamber.value = pr.c; sendCmd('chamber', pr.c);
        }
    };
    //  Материал: слоты AMS (Bambu) или CFS (Creality) в одном виде; активный — из телеметрии,
    //  ровно так же, как его подсвечивает карточка 2.0 (ams_now / cfs_now).
    const ui3PpTrays = computed(() => {
        const p = ui3PpP.value, s = ui3PpS.value; if (!p) return [];
        const out = []; const ru = lang.value === 'ru';
        const lbl = (t) => (t.type && t.type !== 'Empty') ? shortFilament(t.type) : (ru ? 'пусто' : 'empty');
        if (p.type === 'bambu') {
            for (const g of (amsGroups(p) || [])) for (const t of (g.slots || [])) {
                const empty = !(t.type && t.type !== 'Empty');
                const n = (t.tray == null ? t.index : t.tray) + 1;
                out.push({ key: 'a' + t.index, color: empty ? '' : (t.color || '#71717a'), short: lbl(t), empty, ext: false,
                           on: s.ams_now === t.index, title: g.label + '·' + n + (empty ? '' : ' · ' + t.type) });
            }
            if (out.length) out.push({ key: 'ext', color: '', short: ru ? 'внешн.' : 'ext.', empty: false, ext: true,
                                       on: s.ams_now === -1, title: ru ? 'Внешняя катушка' : 'External spool' });
        } else {
            (s.cfs_trays || []).forEach((t, i) => {
                const idx = (t.index == null ? i : t.index);
                const empty = !(t.type && t.type !== 'Empty');
                out.push({ key: 'c' + idx, color: empty ? '' : (t.color || '#71717a'), short: lbl(t), empty, ext: false,
                           on: s.cfs_now != null && s.cfs_now === idx, title: 'CFS ' + (idx + 1) + (empty ? '' : ' · ' + t.type) });
            });
        }
        return out;
    });
    const ui3PpNowLabel = computed(() => {
        const t = ui3PpTrays.value.find(x => x.on); if (!t) return '';
        return (lang.value === 'ru' ? 'печатает из ' : 'printing from ') + t.title.split(' · ')[0];
    });
    //  Выбор катушки перед запуском — те же данные и то же поле printAmsSlot, что у карточки 2.0.
    const ui3AmsOpen = ref(false);
    const ui3AmsPicked = ref(false);
    let _ui3AmsWasOpen = false;
    const ui3AmsToggle = () => { ui3AmsOpen.value = !_ui3AmsWasOpen; };
    const ui3PpAmsChoices = computed(() => {
        const p = ui3PpP.value; if (!p || p.type !== 'bambu') return [];
        const groups = amsGroups(p) || []; if (!groups.length) return [];
        const ru = lang.value === 'ru';
        const out = [{ key: 'ext', slot: null, color: '', label: ru ? 'Внешняя катушка' : 'External spool', rem: '', on: printAmsSlot.value === null }];
        const rows = filamentRows(p) || [];
        for (const g of groups) for (const t of (g.slots || [])) {
            if (!(t.type && t.type !== 'Empty')) continue;
            const lab = g.label + '·' + ((t.tray == null ? t.index : t.tray) + 1);
            const row = rows.find(r => r.label === lab);
            out.push({ key: 'a' + t.index, slot: t.index, color: t.color || '#71717a', label: lab + ' · ' + t.type, rem: row ? row.rem : '', on: printAmsSlot.value === t.index });
        }
        return out;
    });
    const ui3PpPrintLabel = computed(() => {
        const ru = lang.value === 'ru';
        if (printBtnState.value === 'sending') return ru ? 'Отправка…' : 'Sending…';
        if (printBtnState.value === 'sent') return ru ? 'Отправлено' : 'Sent';
        if (printBtnState.value === 'error') return ru ? 'Ошибка' : 'Error';
        const c = ui3AmsPicked.value ? ui3PpAmsChoices.value.find(x => x.on) : null;
        return (ru ? 'Печатать' : 'Print') + (c ? ' · ' + c.label.split(' · ')[0] : '');
    });
    const ui3PpPrint = () => {
        if (!printFileName.value || cellBusy(ui3Printer.value)) return;
        //  Как в карточке 2.0: при AMS сначала спрашиваем, какой катушкой, — печать не той
        //  катушкой стоит испорченной детали. Выбор помнится до закрытия пульта.
        if (ui3PpAmsChoices.value.length && !ui3AmsPicked.value) { ui3AmsOpen.value = true; return; }
        sendCmd('start_print', printFileName.value);
    };
    const ui3PpPrintWith = (slot) => {
        printAmsSlot.value = (slot == null) ? null : slot;
        ui3AmsPicked.value = true; ui3AmsOpen.value = false;
        if (!printFileName.value || cellBusy(ui3Printer.value)) return;
        sendCmd('start_print', printFileName.value);
    };
    if (ui3Mode && typeof document !== 'undefined') {
        //  Щелчок где угодно закрывает меню катушек; сама кнопка-стрелка узнаёт, было ли оно
        //  открыто до щелчка, — иначе она не могла бы его закрыть.
        document.addEventListener('click', () => { _ui3AmsWasOpen = ui3AmsOpen.value; ui3AmsOpen.value = false; }, true);
    }
    //  Правая колонка: камера или предпросмотр детали. Камера — ТОТ ЖЕ блок программы,
    //  пристыкованный к .ui3-camslot; «во весь экран» просто отпускает его из места.
    const ui3PpView = ref('cam');
    const ui3CamFull = ref(false);
    //  2.977: «камера вот-вот откроется». Пульт рисуется в первом же кадре, а камера открывается
    //  двумя кадрами позже — и на этот первый кадр в место камеры вставала кнопка «Показать
    //  камеру». Ловец морганий поймал её как вспышку длиной в один кадр. Пока метка стоит,
    //  место камеры пустое и тихое; снимается она, когда камера открылась или не смогла.
    const ui3CamPending = ref(false);
    watch(cameraPrinterId, (v) => { if (v) ui3CamPending.value = false; });
    const ui3PpCamShown = computed(() => !!ui3PpP.value && ui3HasCamera(ui3PpP.value) && ui3PpView.value === 'cam');
    const ui3PpCamOn = () => {
        const p = ui3PpP.value; if (!p || !ui3HasCamera(p)) return;
        ui3CamFull.value = false; ui3PpView.value = 'cam';
        _ui3CamArm(); openCamera(p); nextTick(() => setTimeout(_ui3DockCam, 60));
    };
    const ui3PpSetView = (v) => {
        ui3PpView.value = (v === 'part') ? 'part' : 'cam';
        if (ui3PpView.value === 'part') {
            //  2.975: гасим окно ДО закрытия. Пока камера закрывается, метка стыковки уже снята,
            //  и окно на кадр-другой становится обычным — то есть во весь экран. Владелец видел
            //  это как вспышку с наложением справа (там край окна камеры с его кнопками).
            _ui3CamArm();
            closeCamera();
            document.documentElement.classList.remove('ui3-cam-dock');
        } else ui3PpCamOn();
    };
    const ui3PpCamFull = () => {
        if (!cameraPrinterId.value) { ui3PpCamOn(); return; }
        _ui3CamReady();
        ui3CamFull.value = true;
        document.documentElement.classList.remove('ui3-cam-dock');
    };
    const _ui3PpReset = () => { ui3PpView.value = 'cam'; ui3CamFull.value = false; ui3AmsOpen.value = false; ui3AmsPicked.value = false; ui3FilesOpen.value = false; ui3CamPending.value = false; };

    //  ── 2.975/2.976: файлы принтера выбираются своим списком, а не системным выпадающим
    //  полем — так список выглядит частью пульта, а не чужим элементом. Удаления здесь НЕТ:
    //  владелец попросил его убрать (2.976); файлы удаляются из проводника «Файлы принтеров».
    const ui3FilesOpen = ref(false);
    const ui3FilesToggle = () => {
        if (cellBusy(ui3Printer.value)) return;
        ui3FilesOpen.value = !ui3FilesOpen.value;
        if (ui3FilesOpen.value) ui3AmsOpen.value = false;
    };
    const ui3PickFile = (f) => { printFileName.value = f; ui3FilesOpen.value = false; };

    // ------------------------------------------------------------------------
    // БЛОК: запуск интерфейса.
    // Первичная загрузка, интервалы обновления, WebSocket и глобальные события.
    // ------------------------------------------------------------------------
    // ======== Проекты 2.0 (новая производственная модель) — отдельно от старых Проектов ========
    const projects2 = ref([]);
    const project2Trees = ref({});      // project_id -> {project, nodes}
    const project2Parts = ref({});      // project_id -> {project, parts} — деталь-центричный вид
    const pvExpanded = ref({});         // part_id -> bool: раскрыты ли карточки-плиты детали
    const project2Expanded = ref('');     // id раскрытого проекта ('' = ни один). Одиночное раскрытие как в старых проектах.
    const project2Busy = ref(false);
    const newProject2Name = ref('');
    const showNewProject2 = ref(false);
    // Alpha 2.804: папка проекта называется РОВНО как проект, поэтому названия живых проектов
    // уникальны. Окончательная граница — BACKEND (409/400 с машинным reason); фронтенд только
    // показывает понятное предупреждение и НЕ является границей безопасности: устаревший список
    // проектов её не обходит — сервер проверяет заново перед записью.
    const P2_NAME_MSG = {
        project_name_conflict: 'A project with this name already exists. Choose a different name.',
        project_folder_conflict: 'A folder with this name already exists in Farm Manager storage. Choose a different name.',
        project_folder_locked: 'Could not rename the project folder. Close programs that use the project files and try again.',
        project_name_required: 'Enter a project name.',
        project_name_invalid: 'This name cannot be used as a folder name. Allowed: letters, digits, spaces and - _ ( ), without a dot at the end.',
        project_name_reserved: 'This name is reserved by Windows. Choose a different name.',
        project_name_too_long: 'Project name is too long. Choose a shorter name.',
        project_rename_failed: 'Could not rename the project. Try again.'
    };
    const project2NameErr = ref('');       // reason предупреждения формы «Новый проект» ('' = нет)
    const project2RenameErr = ref({});     // project_id -> reason предупреждения при переименовании
    const p2NameMsg = (reason) => tr(P2_NAME_MSG[reason] || P2_NAME_MSG.project_name_conflict);
    // Ключ сравнения ТОЛЬКО для быстрого локального предупреждения (аналог серверного канона):
    // NFC + обрезка краёв + снятие хвостовых точек/пробелов + регистронезависимость.
    const p2NameKey = (s) => String(s || '').normalize('NFC').trim().replace(/[. ]+$/, '').toLowerCase();
    const _p2Reason = async (r) => { try { const j = await r.json(); return String((j && j.reason) || ''); } catch (e) { return ''; } };
    const _p2FocusNew = () => nextTick(() => { try { const el = document.getElementById('fm-new-project-name'); if (el) { el.focus(); el.select(); } } catch (e) {} });
    const _p2FocusRename = (pid) => nextTick(() => { try { const el = document.getElementById('fm-p2name-' + pid); if (el) { el.focus(); el.select(); } } catch (e) {} });
    const p2RenameBusy = new Set();        // pid, по которым запрос уже летит: повторная отправка блокируется
    const project2Mode = ref({});        // project_id -> 'edit' (отсутствует = просмотр/фиксированный)
    const setProject2Mode = (pid, m) => { project2Mode.value = { ...project2Mode.value, [pid]: m }; };
    const project2EditAdv = ref({});     // project_id -> true: продвинутый режим правки (разметка плиты), иначе обычный
    const setProject2EditAdv = (pid, on) => { project2EditAdv.value = { ...project2EditAdv.value, [pid]: !!on }; };
    // При сворачивании проекта (клик по пустому месту или шапке) выходим из режима правки —
    // чтобы при повторном открытии проект показывался в простом виде, а не снова в правке.
    watch(project2Expanded, (newId, oldId) => {
        if (oldId && oldId !== newId && project2Mode.value[oldId] === 'edit') setProject2Mode(oldId, 'view');
    });
    // Плоский список строк дерева для ОДНОГО файла (фиксированный режим): детали (уровень 1) и,
    // если деталь встречается ещё в каких-то файлах, — те файлы (уровень 2). Флаги веток:
    //   guides[i] — сквозная вертикаль предка на уровне i; through — вертикаль текущего узла идёт вниз (есть младший сосед).
    const loadProjects2 = async () => {
        if (tourActive.value) return;   // тур использует только демо-данные (засеяны напрямую); не трогаем список с сервера
        try { const r = await fetch('/api/projects2'); if (r.ok && !tourActive.value) projects2.value = await r.json(); } catch (e) {}
    };
    // Экспорт всех Проектов 2.0 в CSV-архив: скачивание через временную ссылку (без ухода со страницы).
    const exportProjects2 = () => {
        const a = document.createElement('a');
        a.href = '/api/projects2/export';
        a.download = '';
        document.body.appendChild(a);
        a.click();
        a.remove();
    };
    const loadProject2Tree = async (pid) => {
        if (tourActive.value) return;   // тур: дерево демо-проекта засеяно напрямую
        try { const r = await fetch('/api/projects2/' + pid + '/tree'); if (r.ok && !tourActive.value) { const t = await r.json(); project2Trees.value = { ...project2Trees.value, [pid]: t }; } } catch (e) {}
        await loadPartsView(pid);   // «По деталям» — единственный вид, грузим всегда при раскрытии
    };
    // Порядок файлов в режиме правки: сначала модели (.stl/.3mf), затем нарезанные g-code — для разделителя.
    const p2EditOrdered = (pid) => {
        const t = project2Trees.value[pid];
        if (!t || !t.nodes) return [];
        const n = t.nodes;
        return n.filter(x => !x.is_printable).concat(n.filter(x => x.is_printable));
    };
    const loadPartsView = async (pid) => {
        if (tourActive.value) return;   // тур: детали демо-проекта засеяны напрямую
        try {
            const r = await fetch('/api/projects2/' + pid + '/partsview');
            if (r.ok && !tourActive.value) {
                const pvd = await r.json();
                //  Поля, которые правятся прямо сейчас, оставляем местными: пришедшее с сервера
                //  значение вернуло бы в них то, что было до правки.
                const keys = Object.keys(p2Dirty.value || {});
                if (keys.length && pvd && Array.isArray(pvd.parts)) {
                    const was = {};
                    for (const op of (((project2Parts.value || {})[pid] || {}).parts || [])) {
                        if (op && op.part_id) was[op.part_id] = op;
                    }
                    for (const np of pvd.parts) {
                        const op = was[np && np.part_id];
                        if (!op) continue;
                        for (const k of keys) {
                            const i = k.indexOf(':');
                            if (k.slice(0, i) !== np.part_id) continue;
                            const f = k.slice(i + 1);
                            if (f in op) np[f] = op[f];
                        }
                    }
                }
                project2Parts.value = { ...project2Parts.value, [pid]: pvd };
            }
        } catch (e) {}
    };
    // Имя детали ДЛЯ ПОКАЗА. Имя берётся реальное (из plate_*.json модели), поэтому настоящие
    // пробелы и подчёркивания СОХРАНЯЕМ как есть. Здесь лишь страховка для старых уже сохранённых
    // имён: снимаем хвост экземпляра слайсера (_id_N_copy_M) и расширение модели. БЕЗ замены _ на
    // пробел — иначе терялось бы настоящее подчёркивание в имени детали.
    const partDisplayName = (name) => {
        let s = String(name == null ? '' : name);
        s = s.replace(/[._]id[._]\d+[._]copy[._]\d+$/i, '');                          // маркер экземпляра (старые имена)
        s = s.replace(/\.(gcode\.3mf|3mf|stl|obj|step|stp|gcode|ply|model)$/i, '');   // расширение модели
        return s.trim() || String(name == null ? '' : name);
    };

    // ---- Запрос перепечатки (брак при сборке): отдельный счётчик, основной не трогаем ----
    const reworkPart = ref(null);
    const reworkPos = ref({ top: 0, left: 0 });
    const reworkAddQty = ref(1);
    const openRework = (ev, pid, pp) => {
        try {
            // .rw-pop — position:fixed под html{zoom}. getBoundingClientRect даёт ВИЗУАЛЬНЫЕ
            // (зум) px, поэтому координаты и ширину окна делим на живой zoom — как у контекстного меню.
            const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1.04;
            const r = ev.currentTarget.getBoundingClientRect();
            const vw = (window.innerWidth || 1280) / z;
            const w = 248; let left = r.left / z;
            if (left + w > vw - 8) left = vw - w - 8;
            reworkPos.value = { top: Math.round(r.bottom / z + 6), left: Math.round(Math.max(8, left)) };
        } catch (e) { reworkPos.value = { top: 120, left: 120 }; }
        reworkAddQty.value = 1;
        reworkPart.value = { pid, part_id: pp.part_id, part_name: pp.part_name, rework_qty: pp.rework_qty || 0, rework_done: pp.rework_done || 0 };
    };
    const closeRework = () => { reworkPart.value = null; };
    const _reworkPost = async (pid, partId, body) => {
        try {
            const r = await fetch('/api/projects2/' + pid + '/parts/' + partId + '/rework', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            if (r.ok) { await loadPartsView(pid); await loadProjects2(); }
        } catch (e) {}
        reworkPart.value = null;
    };
    const submitRework = (pid, partId) => { const n = Math.max(1, parseInt(reworkAddQty.value) || 1); _reworkPost(pid, partId, { add: n }); };
    const clearRework = (pid, partId) => { _reworkPost(pid, partId, { clear: true }); };
    // Статус детали (pp.status) приходит из partsview и кэшируется — он НЕ live. Поэтому при смене набора
    // печатающих принтеров (печать началась / остановлена / завершилась) перезапрашиваем детали открытого
    // проекта и сводку: иначе после остановки деталь висит «в процессе» до перезагрузки (бэкенд задание уже
    // снял). Дебаунс 700мс: батчим частые смены и даём бэкенду зафиксировать статус. В режиме правки не
    // трогаем — чтобы не затереть несохранённый ввод.
    const _printingPidsKey = computed(() => {
        const wd = wsData.value || {};
        return Object.keys(wd).filter(pid => ['RUNNING', 'PREPARE'].includes(String((wd[pid] && wd[pid].status) || '').toUpperCase())).sort().join(',');
    });
    let _p2RefreshTimer = null;
    watch(_printingPidsKey, () => {
        if (_p2RefreshTimer) clearTimeout(_p2RefreshTimer);
        _p2RefreshTimer = setTimeout(() => {
            if (anyEditing() || tourActive.value) return;   // во время тура демо-данные засеяны напрямую — фоновое обновление их затёрло бы (исчезающий проект на шаге 21)
            const pid = project2Expanded.value;
            if (pid) loadPartsView(pid);
            loadProjects2();
        }, 700);
    });
    const pvTogglePart = (partId) => { pvExpanded.value = { ...pvExpanded.value, [partId]: !pvExpanded.value[partId] }; };
    // Развернуть / свернуть все детали проекта разом (вид «По деталям»).
    const pvExpandAll = (pid) => {
        const parts = (project2Parts.value[pid] && project2Parts.value[pid].parts) || [];
        const m = { ...pvExpanded.value };
        parts.forEach(p => { m[p.part_id] = true; });
        pvExpanded.value = m;
    };
    const pvCollapseAll = (pid) => {
        const parts = (project2Parts.value[pid] && project2Parts.value[pid].parts) || [];
        const m = { ...pvExpanded.value };
        parts.forEach(p => { m[p.part_id] = false; });
        pvExpanded.value = m;
    };
    // Схематичное превью плиты: N деталей на тёмном столе с сеткой. Реальные миниатюры из .3mf — следующим этапом.
    const pvPlate = (count) => {
        const W = 204, H = 120;
        let s = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%;display:block">';
        s += '<rect x="6" y="5" width="192" height="110" rx="9" fill="#161a21" stroke="#2d3540" stroke-width="1.4"/>';
        for (let gx = 24; gx < 198; gx += 18) s += '<line x1="' + gx + '" y1="7" x2="' + gx + '" y2="113" stroke="#212934" stroke-width="1"/>';
        for (let gy = 22; gy < 115; gy += 18) s += '<line x1="8" y1="' + gy + '" x2="196" y2="' + gy + '" stroke="#212934" stroke-width="1"/>';
        const n = Math.max(1, count | 0);
        const cols = n <= 1 ? 1 : (n <= 2 ? 2 : (n <= 4 ? 2 : (n <= 9 ? 3 : (n <= 12 ? 4 : 5))));
        const rows = Math.ceil(n / cols);
        const padX = 20, padY = 15, gap = 5, areaW = W - 2 * padX, areaH = H - 2 * padY;
        const cw = (areaW - (cols - 1) * gap) / cols, ch = (areaH - (rows - 1) * gap) / rows;
        let i = 0;
        for (let r = 0; r < rows; r++) {
            for (let c = 0; c < cols; c++) {
                if (i >= n) break; i++;
                const x = padX + c * (cw + gap), y = padY + r * (ch + gap);
                const w = Math.min(cw, ch) * 0.82, h = w * 0.78;
                const ox = (x + (cw - w) / 2).toFixed(1), oy = (y + (ch - h) / 2).toFixed(1);
                s += '<rect x="' + ox + '" y="' + oy + '" width="' + w.toFixed(1) + '" height="' + h.toFixed(1) + '" rx="3" fill="#3a82cc"/>';
                s += '<rect x="' + ox + '" y="' + oy + '" width="' + w.toFixed(1) + '" height="' + Math.max(2, h * 0.32).toFixed(1) + '" rx="3" fill="#82c4ff" opacity="0.55"/>';
            }
        }
        return s + '</svg>';
    };
    const p2FlipRect = ref(null);
    let p2PanelBox = null;
    // Тонировка ячейки проекта по состоянию: синий — печатается, зелёный — готов, жёлтый — простой.
    const getProjectTint = (pr) => {
        let c;
        if ((pr.printing_count || 0) > 0) c = '59,130,246';
        else if ((pr.parts_count || 0) > 0 && (pr.done_count || 0) >= pr.parts_count) c = '34,197,94';
        else c = '234,179,8';
        return 'background-image:linear-gradient(180deg,rgba(' + c + ',0.32),rgba(' + c + ',0.18));border-color:rgba(' + c + ',0.55);';
    };

    // Режим архивации: выбор проектов галочками -> подтверждение -> в архив (пропадают из списка).
    const archiveMode = ref(false);
    const selectedForArchive = ref(new Set());
    const toggleArchiveMode = () => { archiveMode.value = !archiveMode.value; selectedForArchive.value = new Set(); if (archiveMode.value) showNewProject2.value = false; };
    // 🔒 ОТЛАЖЕНО — Архив и «Новый проект» взаимоисключающие: открытие одного закрывает другой, иначе их панели накладываются. toggleArchiveMode гасит showNewProject2, toggleNewProject2 гасит archiveMode. Не менять без перепроверки.
    const toggleNewProject2 = () => { showNewProject2.value = !showNewProject2.value; if (showNewProject2.value && archiveMode.value) toggleArchiveMode(); if (showNewProject2.value) nextTick(() => { try { const _el = document.getElementById('fm-new-project-name'); if (_el) _el.focus(); } catch (e) {} }); };   // автофокус поля имени при открытии; взаимоисключение с Архивом (🔒 выше) не тронуто
    const toggleArchiveSelect = (pid) => { const s = new Set(selectedForArchive.value); if (s.has(pid)) s.delete(pid); else s.add(pid); selectedForArchive.value = s; };
    const confirmArchive = async (keep) => {
        const ids = [...selectedForArchive.value];
        if (!ids.length) { archiveMode.value = false; return; }
        try { await fetch('/api/projects2/archive', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids, keep: !!keep }) }); } catch (e) {}
        archiveMode.value = false; selectedForArchive.value = new Set();
        try { const r = await fetch('/api/projects2'); if (r.ok) projects2.value = await r.json(); } catch (e) {}
        pushToast((keep ? (lang.value==='ru' ? 'Сохранено в архив: ' : 'Saved to archive: ') : (lang.value==='ru' ? 'Убрано в архив: ' : 'Moved to archive: ')) + ids.length, 'info');
    };

    const toggleProject2 = async (pid, ev) => {
        if (archiveMode.value) { toggleArchiveSelect(pid); return; }
        const open = project2Expanded.value !== pid;   // повторный клик по тому же проекту — закрыть
        if (open && ev && ev.currentTarget) {
            try { p2FlipRect.value = ev.currentTarget.getBoundingClientRect(); } catch (e) { p2FlipRect.value = null; }
        }
        project2Expanded.value = open ? pid : '';
        if (open && !project2Trees.value[pid]) await loadProject2Tree(pid);
    };
    // Раскрытие: панель «вырастает» из кликнутой ячейки (FLIP — стартует точно в её рамке и габаритах,
    // затем доезжает до своего естественного места). Если ячейка была снизу/справа — анимация идёт оттуда.
    const p2Enter = (el, done) => {
        p2PanelBox = { top: el.offsetTop, left: el.offsetLeft, width: el.offsetWidth };
        const r = p2FlipRect.value;
        const pr = el.getBoundingClientRect();
        if (!r || !pr.width || !pr.height) { done(); return; }
        const dx = r.left - pr.left, dy = r.top - pr.top;
        const sx = Math.max(r.width / pr.width, 0.04), sy = Math.max(r.height / pr.height, 0.04);
        el.style.transformOrigin = 'top left';
        el.style.transform = 'translate(' + dx + 'px,' + dy + 'px) scale(' + sx + ',' + sy + ')';
        el.style.opacity = '0.4';
        el.style.willChange = 'transform,opacity';
        void el.offsetWidth;
        el.style.transition = 'transform .42s cubic-bezier(.22,1,.36,1), opacity .32s ease';
        el.style.transform = 'none';
        el.style.opacity = '1';
        let fin = false;
        const clean = () => { if (fin) return; fin = true; el.style.transition = ''; el.style.transform = ''; el.style.transformOrigin = ''; el.style.opacity = ''; el.style.willChange = ''; done(); };
        const te = (e2) => { if (e2.target === el && e2.propertyName === 'transform') { el.removeEventListener('transitionend', te); clean(); } };
        el.addEventListener('transitionend', te);
        setTimeout(clean, 560);
    };
    // Сворачивание: снимаем панель из потока (по рамке, запомненной при открытии — когда сетки ещё нет,
    // т.е. это её настоящая верхняя позиция), чтобы сетка и «Задачи» сразу заняли место без рывка,
    // и плавно гасим её на месте. Без запомненной рамки offsetTop уже учитывал бы появившуюся сетку → прыжок.
    const p2Leave = (el, done) => {
        if (tourActive.value) { done(); return; }   // во время обучения сворачиваем мгновенно — без анимации, чтобы карточка проекта не мигала на переходах шагов
        const box = p2PanelBox || { top: el.offsetTop, left: el.offsetLeft, width: el.offsetWidth };
        el.style.position = 'absolute';
        el.style.top = box.top + 'px';
        el.style.left = box.left + 'px';
        el.style.width = box.width + 'px';
        el.style.margin = '0';
        el.style.zIndex = '4';
        el.style.pointerEvents = 'none';
        el.style.transformOrigin = 'top center';
        void el.offsetWidth;
        el.style.transition = 'opacity .2s ease, transform .24s cubic-bezier(.4,0,1,1)';
        el.style.opacity = '0';
        el.style.transform = 'translateY(-6px) scale(.99)';
        let fin = false;
        const end = () => { if (fin) return; fin = true; done(); };
        const te = (e2) => { if (e2.target === el && e2.propertyName === 'opacity') { el.removeEventListener('transitionend', te); end(); } };
        el.addEventListener('transitionend', te);
        setTimeout(end, 300);
    };
    const createProject2 = async () => {
        const name = (newProject2Name.value || '').trim();
        if (project2Busy.value) return;                       // повторная отправка того же имени заблокирована
        project2NameErr.value = '';
        if (!name) { project2NameErr.value = 'project_name_required'; _p2FocusNew(); return; }
        const key = p2NameKey(name);                          // быстрый локальный precheck (НЕ граница безопасности)
        if ((projects2.value || []).some(p => p2NameKey(p.name) === key)) {
            project2NameErr.value = 'project_name_conflict'; _p2FocusNew(); return;
        }
        project2Busy.value = true;
        try {
            const r = await fetch('/api/projects2', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
            if (!r.ok) {          // 409/400: форма НЕ закрывается, введённое имя сохраняется, фокус возвращается в поле
                project2NameErr.value = (await _p2Reason(r)) || 'project_name_conflict';
                project2Busy.value = false; _p2FocusNew(); return;
            }
            const pj = await r.json().catch(() => null);
            newProject2Name.value = ''; showNewProject2.value = false;
            await loadProjects2();
            if (pj && pj.id) project2Expanded.value = pj.id;
        } catch (e) {}
        project2Busy.value = false;
    };
    const deleteProject2 = async (pid) => {
        if (!await _confirmDelete('Delete this project?', (projects2.value.find(x => x.id === pid) || {}).name)) return;
        try { await fetch('/api/projects2/' + pid, { method: 'DELETE' }); if (project2Expanded.value === pid) project2Expanded.value = ''; await loadProjects2(); } catch (e) {}
    };
    const exProject2Target = ref('');   // проект, в который Проводник добавит выбранные файлы (режим 'p2add')
    const openExplorerForProject2Files = (pid) => { exProject2Target.value = pid; return exOpenWith('p2add', null); };
    const exAddFilesToProject2 = async () => {
        const pid = exProject2Target.value; const paths = exPartFilesSel.value.slice();
        if (!pid || !paths.length || importProg.value.active) return;
        exOpen.value = false;
        await _runImportWithProgress(paths, (p) => _addOneToProject2(pid, p), 'Adding files…');
        await loadProject2Tree(pid); await loadProjects2();
    };
    const _p2SetRenameErr = (pid, reason) => {
        const m = { ...project2RenameErr.value };
        if (reason) m[pid] = reason; else delete m[pid];
        project2RenameErr.value = m;
    };
    const saveProject2Name = async (pid, name) => {
        // Alpha 2.804: переименование — ОДНА операция (имя проекта + имя папки). При отказе сервера
        // список НЕ перечитывается: введённое пользователем значение остаётся в поле, поле получает
        // подсветку ошибки, фокус возвращается туда же, проект не переименовывается частично.
        const nm = (name || '').trim();
        if (p2RenameBusy.has(pid)) return;                    // повторная отправка заблокирована
        _p2SetRenameErr(pid, '');
        if (!nm) { _p2SetRenameErr(pid, 'project_name_required'); _p2FocusRename(pid); return; }
        const key = p2NameKey(nm);                            // локальный precheck (НЕ граница безопасности)
        if ((projects2.value || []).some(p => p.id !== pid && p2NameKey(p.name) === key)) {
            _p2SetRenameErr(pid, 'project_name_conflict');
            pushToast(p2NameMsg('project_name_conflict'), 'error', 6000); _p2FocusRename(pid); return;
        }
        p2RenameBusy.add(pid);
        try {
            const r = await fetch('/api/projects2/' + pid, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: nm }) });
            if (!r.ok) {
                const reason = (await _p2Reason(r)) || 'project_name_conflict';
                _p2SetRenameErr(pid, reason);
                pushToast(p2NameMsg(reason), 'error', 6000);
                _p2FocusRename(pid); p2RenameBusy.delete(pid); return;
            }
            await loadProjects2();
        } catch (e) {}
        p2RenameBusy.delete(pid);
    };
    const deleteProject2File = async (pid, fileId) => {
        const _fn = (((project2Trees.value || {})[pid] || {}).nodes || []).find(x => x.file_id === fileId);
        if (!await _confirmDelete('Delete this file?', _fn && _fn.filename)) return;
        try {
            const r = await fetch('/api/projects2/' + pid + '/files/' + fileId, { method: 'DELETE' });
            const j = await r.json().catch(() => ({}));
            await loadProject2Tree(pid); await loadProjects2();
        } catch (e) {}
    };
    const deleteProject2Part = async (pid, partId) => {
        const _pp = (((project2Parts.value || {})[pid] || {}).parts || []).find(x => x.part_id === partId);
        if (!await _confirmDelete('Delete this part?', _pp && partDisplayName(_pp.part_name))) return;
        try {
            const r = await fetch('/api/projects2/' + pid + '/parts/' + partId, { method: 'DELETE' });
            const j = await r.json().catch(() => ({}));
            await loadProject2Tree(pid); await loadProjects2();
        } catch (e) {}
    };
    const saveProject2Part = async (pid, partId, patch) => {
        try { await fetch('/api/projects2/' + pid + '/parts/' + partId, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) }); await loadProject2Tree(pid); await loadProjects2(); } catch (e) {}
    };
    // p2FieldFocus оставлен пустой заглушкой: раньше запоминал прежнее значение поля для «Отменить» (undo удалён). Имя сохранено — на него ссылается @focus в шаблоне.
    //  2.974: пока владелец правит поле детали, обновление списка не имеет права вернуть в
    //  него прежнее значение. Список деталей приходит с сервера целиком и раньше затирал
    //  набранное — «Заметки» откатывались через секунду-другую. Помечаем поле правящимся (как
    //  давно сделано у задач) и при обновлении оставляем местное значение.
    const p2Dirty = ref({});
    const _p2Key = (pp, field) => String((pp && pp.part_id) || '') + ':' + field;
    const p2FieldFocus = (pp, field) => {
        if (!pp || !pp.part_id) return;
        p2Dirty.value = { ...p2Dirty.value, [_p2Key(pp, field)]: true };
    };
    //  Метка снимается с задержкой: сервер должен успеть отдать сохранённое значение в
    //  ближайшем обновлении, иначе поле мигнёт старым числом.
    const p2FieldDone = (pp, field) => {
        const k = _p2Key(pp, field);
        setTimeout(() => { const m = { ...p2Dirty.value }; delete m[k]; p2Dirty.value = m; }, 1500);
    };
    const saveProject2PartField = async (pid, pp, field) => {
        const patch = {}; patch[field] = pp[field];
        try {
            await saveProject2Part(pid, pp.part_id, patch);
        } finally {
            p2FieldDone(pp, field);
        }
    };
    const project2PrintFor = ref('');   // file_id, у которого открыт выбор принтера
    // Старые g-code без меток: ручная разметка плиты в режиме правки — добавить именованную деталь к файлу.
    const addProject2PartToFile = async (pid, fileId) => {
        try {
            await fetch('/api/projects2/' + pid + '/files/' + fileId + '/manual-part', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ part_name: '', on_plate_qty: 1 }) });
            await loadProject2Tree(pid); await loadProjects2();
        } catch (e) {}
    };
    // «На плате» (on_plate_qty) — меняем именно связь файл↔деталь.
    const saveProject2OnPlate = async (pid, ch) => {
        try {
            const q = Math.max(0, parseInt(ch.on_plate_qty) || 0);
            await fetch('/api/projects2/' + pid + '/file-parts/' + ch.file_part_id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on_plate_qty: q }) });
            await loadProject2Tree(pid); await loadProjects2();
        } catch (e) {}
    };
    const printProject2File = async (pid, fileId, printerId, amsSlot, print_opts = undefined) => {
        // Alpha 2.687: окно параметров запуска ПЕРЕД отправкой (одиночная печать проектного файла).
        if (print_opts === undefined) {
            project2PrintFor.value = '';
            openPrintStart({ printerId, label: '', source: 'project', amsSlot: (amsSlot === undefined ? null : amsSlot), onConfirm: (opts, srcSlot) => printProject2File(pid, fileId, printerId, (srcSlot === undefined ? (amsSlot === undefined ? null : amsSlot) : srcSlot), opts) });
            return;
        }
        project2PrintFor.value = '';
        project2Busy.value = true;
        const _ctx = { printer_id: printerId, printer_name: _printerNameOf(printerId), file_name: _p2FileNameOf(pid, fileId), source: 'project' };
        try {
            const body = { printer_id: printerId };
            if (amsSlot !== undefined && amsSlot !== null) body.ams_slot = Number(amsSlot);
            if (print_opts) body.print_opts = print_opts;   // Alpha 2.687: опции запуска (только Bambu); тот же body в retry ниже
            const j = await (await fetch('/api/projects2/' + pid + '/files/' + fileId + '/print', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json().catch(() => ({}));
            // Alpha 2.728: accepted → панель отправок; 409 → тост; low_filament/incompatible — как раньше.
            if (j.status === 'low_filament') {
                const lines = (j.shortfall || []).map(sh => (((sh.material || '') + ' ' + (sh.color_name || '')).trim() || tr('the spool')) + '  —  ' + Math.round(sh.available || 0) + ' / ' + Math.round(sh.needed || 0) + ' ' + tr('grams'));
                if (await askConfirm({ title: _L('Филамента может не хватить', 'Filament may run out'), text: tr('Not enough filament on the bound spool. Print anyway?'), list: lines.join('\n'), okText: _L('Печатать всё равно', 'Print anyway') })) {
                    body.skip_filament = true; handleSendResp(await (await fetch('/api/projects2/' + pid + '/files/' + fileId + '/print', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json().catch(() => ({})), _ctx);
                }
            } else if (j.status === 'incompatible') { pushToast(tr('File is not compatible with this printer.') + (j.reason ? ' ' + j.reason : ''), 'info'); }
            else if (handleSendResp(j, _ctx) === 'other') { pushToast(tr('Could not start print.') + (j.reason ? ' ' + j.reason : ''), 'info'); }
            await loadProject2Tree(pid);
        } catch (e) { pushToast(tr('Could not start print.'), 'info'); }
        project2Busy.value = false;
    };

    // === Единое всплывающее окно выбора слота AMS (одинаково для проектов и Задач) ===
    const amsPick = ref({ open: false, style: {}, printerId: '', ctx: null });
    const openAmsPick = (ev, printerId, ctx) => {
        try { ev.stopPropagation(); } catch (_) {}
        const W = 184, M = 6, pad = 8;
        const st = { position: 'fixed', width: W + 'px', zIndex: 100060, overflowY: 'auto' };
        try {
            const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1.04;
            const r = ev.currentTarget.getBoundingClientRect();
            const vw = (window.innerWidth || 1280) / z, vh = (window.innerHeight || 800) / z;
            const rTop = r.top / z, rBottom = r.bottom / z, rRight = r.right / z;
            let left = rRight - W;
            if (left < pad) left = pad;
            if (left + W > vw - pad) left = vw - W - pad;
            st.left = left + 'px';
            const spaceBelow = vh - rBottom - pad, spaceAbove = rTop - pad;
            if (spaceAbove >= 140 || spaceAbove >= spaceBelow) { st.bottom = (vh - rTop + M) + 'px'; st.maxHeight = Math.max(80, spaceAbove - M) + 'px'; }
            else { st.top = (rBottom + M) + 'px'; st.maxHeight = Math.max(80, spaceBelow - M) + 'px'; }
        } catch (e) {}
        amsPick.value = { open: true, style: st, printerId: printerId, ctx: ctx };
    };
    const closeAmsPick = () => { if (amsPick.value.open) { amsPick.value = { open: false, style: {}, printerId: '', ctx: null }; exitSpotlight(); } };
    const amsPickSlot = (slot) => {
        const c = amsPick.value.ctx, pid = amsPick.value.printerId;
        closeAmsPick();
        if (!c) return;
        if (c.flow === 'project') printProject2File(c.pid, c.fileId, pid, slot);
        else printFileOn(c.filename, pid, slot, c.source, c.partName);
    };
    // Клик по принтеру в меню печати (проекты/QT): есть AMS — открыть окно выбора слота, иначе печатать сразу.
    const printPickPrinter = (ev, ctx, printerId) => {
        if ((wsData.value[printerId]?.ams_trays || []).length) {
            openAmsPick(ev, printerId, ctx);
            printMenuUid.value = null; project2PrintFor.value = '';   // закрыть список принтеров — слот выберется в окне
        } else if (ctx.flow === 'project') { printProject2File(ctx.pid, ctx.fileId, printerId); project2PrintFor.value = ''; }
        else printFileOn(ctx.filename, printerId, null, ctx.source, ctx.partName);
    };

    onMounted(() => {
        // Alpha 2.832: сигнал успешного монтирования — гасит аварийный boot-fallback (index.html).
        // onMounted срабатывает ТОЛЬКО если setup и первый render прошли без исключения.
        try { window.__fmBooted = true; var _bf = document.getElementById('fm-boot-fallback'); if (_bf) _bf.style.display = 'none'; } catch (e) {}
        //  17.09.2026: убрать заставку загрузки (она же закрывала мигание голого шаблона в браузере).
        try { if (window.__fmHideBootSplash) window.__fmHideBootSplash(); } catch (e) {}
        fetchStateMatrix();
        loadPrinterModels();
        loadPrinterSortMode();   // Alpha 2.831: режим сортировки принтеров (серверная настройка)
        fetchStaging();
        loadProjects2();
        loadQueueWait();                       // очередь ожидания видна в «Подсказках» с первого кадра
        loadSlicers();
        let _ppTick = 0;
        pollInterval = setInterval(() => { if (!anyEditing() && !tourActive.value) { fetchStateMatrix(); if ((_ppTick++ % 4) === 0) loadQueueWait(); const _epid = project2Expanded.value; if (!(_epid && project2Mode.value[_epid] === 'edit')) { loadProjects2(); if (_epid) loadPartsView(_epid); } } }, 3000); 
        stagingInterval = setInterval(() => { if (!tourActive.value) fetchStaging(); }, 4000);
        connectDataBroker(); 
        document.addEventListener('click', onDocClick);
        document.addEventListener('keydown', onKeydown);
        document.addEventListener('mousedown', onDocMouseDown, true);
        document.addEventListener('contextmenu', onDocContextMenu, true);
        window.addEventListener('resize', _onResize);
        // Alpha 2.848: масштаб рабочей области — ДО замера высоты колонки: recalcLeftCol переводит
        // визуальные px в логические по живому зуму, поэтому сначала зум, потом замер.
        applyWrapZoom();
        nextTick(() => { applyWrapZoom(); recalcLeftCol(); _watchSuggestHeight(); }); setTimeout(() => { applyWrapZoom(); recalcLeftCol(); _watchSuggestHeight(); }, 200);   // первичный замер высоты левой колонки
        checkUpdate();
        updateTimer = setInterval(checkUpdate, 6 * 60 * 60 * 1000);   // перепроверять сайт раз в 6 часов
        _diagAlertTimer = setInterval(pollDiagSummary, 20000);   // проактивные оповещения о деградации связи (раз в 20с)
        startPrinterBadges();   // индикаторы модулей на карточках принтеров
        //  Проверять надо на КАЖДОЕ из трёх событий, а не только на обновление склада:
        //  снимок склада может прийти раньше списка принтеров (тогда проверять нечего),
        //  а сдвинутый порог обязан пересчитать уже показанные катушки.
        if (ui3Mode) watch([printerFilament, () => (printers.value || []).length, ui3FilLowPct],
                           () => { try { _ui3FilCheckLow(); } catch (e) { /* предупреждение не критично */ } },
                           { deep: true });
        startPrinterFilament();   // привязанный филамент (склад) на карточках принтеров
        loadActiveProjectRuns(true);   // «Планы проектов»: восстановление активных планов после перезагрузки (read-only)
        fetchPrintQueue();
        checkRecoveryNotice();   // Alpha 2.629: один раз при загрузке — если после перезапуска очередь удержана, покажем модалку подтверждения
        // Alpha 2.813: якорь «#logs» открывает встроенный журнал сразу — так пункт трея «Открыть
        // журнал Farm Manager» приводит пользователя прямо к нему. В якоре нет ни токена, ни
        // секрета: доступ к записям проверяет сервер при каждом запросе.
        try { if (String(location.hash || '').toLowerCase() === '#logs') openDiagnostics(); } catch (e) {}
        (() => { let _pt = 0; setInterval(() => { _pt++; if (printQueue.value.length || printSendingNow.value || (_pt % 3 === 0)) fetchPrintQueue(); }, 1000); })();   // очередь поэтапного запуска: 1с при активной очереди/отправке, иначе 3с
        startSendPoll();   // Alpha 2.728: server-driven панель фоновых отправок (адаптивный интервал 1.2/3.5с) + восстановление активных при reload
        setTimeout(() => {
            try {
                _tourRefreshSavedProgress();
                tourCompleted.value = _tourReadCompleted();
                if (TOUR_ENABLED && tourStartupPromptEnabled.value && !tourActive.value && !showSettings.value && !showTourStartDialog.value && (savedTourProgress.value || !tourCompleted.value)) {
                    openTourStartDialog();
                }
            } catch (e) {}
        }, 900);
    });
    
    // ------------------------------------------------------------------------
    // БЛОК: глобальные взаимодействия — контекстное меню, клавиатура,
    // долгий тап, определение мобильного режима и расчёт высоты колонок.
    // ------------------------------------------------------------------------
    // --- Live-диагностика: журнал сервера в реальном времени (Стадия 1) ---------
    // ПРАВИЛО: панель только ЧИТАЕТ журнал (GET /api/diagnostics) и переключает
    // шумность консоли (POST .../verbose); командами на принтеры НЕ управляет.
    // Источник данных — кольцевой буфер на сервере; фронт тянет ДЕЛЬТУ по diagLastId
    // (записи новее уже полученных), а не весь буфер каждый тик — дёшево и без рывков.
    // --- Контекстное меню (правый клик) ----------------------------------------
    // ПРАВИЛО: одно меню на всё приложение. Пункты задаются массивом при открытии
    // ({label, action, danger?, icon?}) — будущие опции добавляются в построители ниже,
    // разметку трогать не нужно. Закрытие — клик по бэкдропу или Esc.
    const ctxMenu = ref({ show: false, x: 0, y: 0, items: [] });
    const openContextMenu = (e, items) => {
        // clientX/clientY — ВИЗУАЛЬНЫЕ px (уже с учётом html-zoom). Меню (position:fixed) рендерится
        // под html{zoom}, поэтому его CSS left/top ещё раз домножаются на zoom — без деления меню уезжает
        // вниз-вбок тем сильнее, чем больше zoom (дефолтный шрифт = 1.196). Делим на live-zoom, как спотлайт/AMS-поп-ап.
        const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1.04;
        const vw = (window.innerWidth || 1280) / z, vh = (window.innerHeight || 800) / z;
        const w = 200, h = items.length * 40 + 10;   // прикидка размеров (css-px), чтобы меню не вылезло за экран
        ctxMenu.value = { show: true, x: Math.min(e.clientX / z, vw - w - 6), y: Math.min(e.clientY / z, vh - h - 6), items };
    };
    const closeContextMenu = () => { ctxMenu.value.show = false; };
    const runCtxItem = (it) => { closeContextMenu(); if (it && typeof it.action === 'function') it.action(); };
    provide('openContextMenu', openContextMenu);   // модулям-плагинам: правый клик по своим элементам -> ОБЩЕЕ контекстное меню (единый Escape/клик-мимо/позиционирование)
    provide('escapeLayer', { register: registerEscapeLayer, unregister: unregisterEscapeLayer });   // Alpha 2.673: модули регистрируют свои вложенные диалоги в общий Escape-стек (закрытие верхнего слоя)
    // Отслеживаем, началось ли нажатие мыши внутри поля ввода: «клик», завершившийся ВНЕ поля
    // (мышь вышла за ячейку при выделении текста), — это выделение, а НЕ клик мимо, и он не должен
    // закрывать панели/модалки/меню.
    let _downInField = false;
    const onDocMouseDown = (e) => { _downInField = !!(e.target && e.target.closest && e.target.closest('input, textarea')); };
    // Глобальное правоклик-поведение (capture-фаза — раньше обработчиков элементов):
    //  • нативное меню браузера выключено ВЕЗДЕ, КРОМЕ полей ввода (input/textarea) — там оставляем
    //    штатные Копировать/Вставить;
    //  • сначала гасим текущее меню; затем обработчик конкретного элемента (если он есть) тут же
    //    откроет новое — поэтому правый клик по другому элементу перескакивает СРАЗУ, без второго
    //    нажатия. По пустому месту меню просто закрывается.
    const onDocContextMenu = (e) => {
        if (ctxMenu.value.show) closeContextMenu();
        if (!(e.target && e.target.closest && e.target.closest('input, textarea'))) e.preventDefault();
    };
    const onPrinterMenu = (e, p) => openContextMenu(e, [
        { label: tr('Edit'), icon: 'edit', action: () => openEditPrinter(p) },
        // Alpha 2.831: «Создать копию» — форма создания, заполненная настройками этого принтера
        // (без stable ID и без секрета). Показываем только тем, кто может добавлять принтеры.
        ...(can('printer_write') ? [{ label: tr('Create copy'), icon: 'copy', action: () => openCopyPrinter(p) }] : []),
        //  2.974: пункт «Файлы принтера» убран по решению владельца. Тот же проводник
        //  открывается из настроек, разделом «Файлы принтеров».
        { label: tr('Delete'), icon: 'delete', danger: true, action: () => removePrinterById(p.id) },   // removePrinterById сам спросит подтверждение
    ]);
    // ── ПКМ по ячейке проекта (Alpha 2.703): «Архив» — входит в режим архивации с ЭТИМ проектом уже выбранным
    //    (в шапке появляется прежняя панель Убрать/Сохранить в архив/Импорт/Отмена — так сохраняем выбор keep/move,
    //    импорт архива и мультивыбор); «Удалить» — сразу deleteProject2 (confirm внутри). Обе — по project.id из ячейки.
    //    showNewProject2 гасим (🔒 архив и «Новый проект» взаимоисключающие, см. toggleArchiveMode/toggleNewProject2).
    const onProjectMenu = (e, pr) => {
        if (!can('project')) return;
        openContextMenu(e, [
            { label: tr('Archive'), icon: 'archive', action: () => { showNewProject2.value = false; archiveMode.value = true; selectedForArchive.value = new Set([pr.id]); } },
            { label: tr('Delete'), icon: 'delete', danger: true, action: () => deleteProject2(pr.id) },
        ]);
    };
    // ── Правый клик по имени файла в Tasks: «Добавить в проект…» / «Создать новый проект…» (только в
    //    редакциях с Проектами) и «Удалить» (перенесено из кнопки справа в строке, Alpha 2.702). При переносе
    //    файл физически уходит в папку проекта (project_files/<имя проекта>/) и убирается из задач. Меню — только
    //    при праве 'project' (как раньше и кнопка удаления). Раньше меню целиком гейтилось на edHas('projects'),
    //    поэтому теперь гейт снят с меню и оставлен только на пунктах про проекты — чтобы «Удалить» было и там,
    //    где Проектов нет (напр. Индивидуальная редакция).
    let _stCtxX = 0, _stCtxY = 0;
    const onStagingMenu = (e, f) => {
        if (!can('project')) return;
        _stCtxX = e.clientX; _stCtxY = e.clientY;
        const items = [];
        if (edHas('projects')) {
            items.push({ label: tr('Add to project…'), icon: 'folder', action: () => stagingPickProject(f) });
            items.push({ label: tr('New project from file…'), icon: 'add', action: () => stagingNewProject(f) });
        }
        //  2.920: постановка в очередь ожидания — программа сама подберёт принтер.
        //  15.09.2026: у не нарезанного файла пункта нет — такой файл очередь не примет.
        if (!(f.is_printable === false || f.is_printable === 0)) {
            items.push({ label: lang.value === 'ru' ? 'Добавить в очередь' : 'Add to queue',
                         icon: 'layers', action: () => queueAdd(f) });
        }
        //  2.924: в оформлении 3.0 панель строки не раскрывается, и жившая там кнопка
        //  «Открыть расположение файла» переехала в правое меню. В 2.0 пункта нет: там
        //  кнопка по-прежнему в раскрывающейся панели.
        items.push({ label: tr('Delete'), icon: 'delete', danger: true, action: () => deleteStagingFile(f.filename) });   // deleteStagingFile сам спросит подтверждение (confirm сохранён)
        openContextMenu(e, items);
    };
    const stagingPickProject = async (f) => {
        if (!(projects2.value && projects2.value.length)) { try { await loadProjects2(); } catch (e) {} }
        const list = projects2.value || [];
        if (!list.length) { pushToast(tr('No projects yet — create one.'), 'info'); return; }
        // второй уровень меню — список проектов (на той же позиции, что и первый клик)
        const items = list.map(p => ({ label: p.name, icon: 'folder', action: () => stagingToProject(f, { project_id: p.id }) }));
        openContextMenu({ clientX: _stCtxX, clientY: _stCtxY, preventDefault() {} }, items);
    };
    const stagingNewProject = (f) => {
        const name = (window.prompt(tr('New project name:'), '') || '').trim();
        if (!name) return;
        stagingToProject(f, { new_name: name });
    };
    const stagingToProject = async (f, body) => {
        try {
            const r = await fetch('/api/staging/' + encodeURIComponent(f.filename) + '/to-project', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
            });
            const d = await r.json().catch(() => ({}));
            //  2.976: в проекте уже есть файл с таким именем — программа спрашивает, а не
            //  подсовывает копию « (2)». При замене счёт и заметки задачи переходят в проект.
            if (r.ok && d.status === 'exists') {
                const ok = await askConfirm({
                    title: _L('В проекте уже есть такой файл', 'The project already has this file'),
                    text: _L('«' + f.filename + '» уже есть в проекте «' + ((d.project && d.project.name) || '') + '». Заменить его файлом из задач? Счёт напечатанного и заметки перейдут вместе с файлом.',
                             '"' + f.filename + '" already exists in project "' + ((d.project && d.project.name) || '') + '". Replace it with the file from Tasks? Printed counts and notes move with the file.'),
                    okText: _L('Заменить', 'Replace'), danger: true });
                if (ok) await stagingToProject(f, Object.assign({}, body || {}, { replace: true }));
                return;
            }
            if (r.ok && d.status === 'ok') {
                await fetchStaging();          // файл уходит из Tasks
                await loadProjects2();         // обновляем счётчики проектов
                const pn = (d.project && d.project.name) || '';
                pushToast((d.created_project ? tr('Created project and moved file: ') : tr('Moved to project: ')) + pn, 'info');
            } else {
                pushToast(tr('Could not move to project.') + (d && d.reason ? ' (' + d.reason + ')' : ''), 'warn', 4000);
            }
        } catch (e) {
            pushToast(tr('Could not move to project.'), 'warn', 4000);
        }
    };
    // На тач-устройствах правого клика нет — те же меню вызываем долгим нажатием (~480мс).
    // Сдвиг пальца > 10px = это скролл, отменяем. Колбэк получает синтетическое событие с координатами.
    let _lpTimer = null, _lpX = 0, _lpY = 0;
    const lpStart = (ev, fn) => {
        if (isMobile.value) return;   // на мобильном — только просмотр, контекстные меню (добавить/изменить/удалить) отключены
        const t = (ev.touches && ev.touches[0]) || ev;
        _lpX = t.clientX; _lpY = t.clientY;
        clearTimeout(_lpTimer);
        _lpTimer = setTimeout(() => { _lpTimer = null; try { if (navigator.vibrate) navigator.vibrate(15); } catch (e) {} fn({ clientX: _lpX, clientY: _lpY, preventDefault() {} }); }, 480);
    };
    const lpMove = (ev) => { if (!_lpTimer) return; const t = (ev.touches && ev.touches[0]) || ev; if (Math.abs(t.clientX - _lpX) > 10 || Math.abs(t.clientY - _lpY) > 10) { clearTimeout(_lpTimer); _lpTimer = null; } };
    const lpEnd = () => { clearTimeout(_lpTimer); _lpTimer = null; };
    // Автораспознавание устройства по ширине (порог 820px = телефон/планшет-портрет). Раскладку
    // делает CSS-media; флаг — для условного рендера на следующих этапах (карточки вместо таблиц).
    const _vw = ref(window.innerWidth);
    const isMobile = computed(() => MOBILE_UI_ENABLED && _vw.value <= 820);
    // Высота левой колонки: из-за двойного zoom низ раскладки уходит за экран, и ячейка
    // «Подсказки» (она в самом низу колонки) пряталась. Замеряем реальный верх колонки
    // (визуальные px, уже с учётом zoom) и выставляем высоту так, чтобы низ был в экране
    // с отступом ~12px. Верх колонки от её высоты не зависит — петли пересчёта нет. На телефоне auto.
    const leftColH = ref(null);
    const rightColH = ref(null);   // 2.975: высота правой половины в оформлении 3.0 (см. recalcLeftCol)
    // Alpha 2.848: масштаб рабочей области больше НЕ константа — он подгоняется под окно (см. applyWrapZoom).
    // _WRAP_BASE_ZOOM — проектное значение из app.css (.zoom-wrap{zoom}); живое читаем через _wrapZoom(),
    // иначе всё, что переводит визуальные px в логические (высота колонки, координаты окна проводника),
    // ошибётся ровно во столько раз, во сколько окно уменьшило масштаб, и всплывающие окна уедут.
    const _WRAP_BASE_ZOOM = 1.0971662034375;
    const _WRAP_DESIGN_W = 960;      // ширина, под которую нарисована десктопная раскладка (min-width .zoom-wrap)
    const _WRAP_MIN_ZOOM = 0.55;     // ниже этого не опускаемся: мельче текст уже нечитаем
    const _wrapZoom = () => {
        try {
            const el = document.querySelector('.zoom-wrap');
            if (el) { const z = parseFloat(getComputedStyle(el).zoom); if (z > 0.1 && z < 10) return z; }
        } catch (e) {}
        return _WRAP_BASE_ZOOM;
    };
    // Подгонка масштаба рабочей области под окно. Раскладка нарисована под 960 CSS-px; когда окна не
    // хватает, мы НЕ сжимаем её (от этого в 2.843 поехали настройки: плитки и значки не умеют сжиматься),
    // а уменьшаем масштаб целиком — пропорции сохраняются, вылезать нечему. Шире проектного не растём.
    const applyWrapZoom = () => {
        try {
            const el = document.querySelector('.zoom-wrap');
            if (!el) return;
            if (isMobile.value) { el.style.zoom = ''; return; }   // узкая раскладка живёт своими правилами
            const hz = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
            const fit = (window.innerWidth / hz) / _WRAP_DESIGN_W;   // сколько проектных ширин влезает
            const z = Math.min(_WRAP_BASE_ZOOM, fit);
            el.style.zoom = (z >= _WRAP_BASE_ZOOM - 1e-6) ? '' : String(Math.max(_WRAP_MIN_ZOOM, z));
        } catch (e) {}
    };
    const recalcLeftCol = () => {
        try {
            if (isMobile.value) { leftColH.value = null; rightColH.value = null; return; }
            const el = document.querySelector('.left-col');
            if (!el) return;
            const top = el.getBoundingClientRect().top;          // визуальный верх колонки (с учётом zoom)
            const avail = window.innerHeight - top - 12;         // оставить ~12px визуального отступа снизу
            if (avail < 200) { leftColH.value = null; rightColH.value = null; return; }  // защита от абсурдных значений
            const _hz = parseFloat(getComputedStyle(document.documentElement).zoom) || 1.04;
            const _k = _hz * _wrapZoom();
            leftColH.value = Math.round(avail / _k) + 'px';   // визуальные px -> css (делим на совокупный ЖИВОЙ zoom)
            //  2.975 (заказ владельца): в оформлении 3.0 правая половина кончается ТАМ ЖЕ, где
            //  подсказки, а не у нижнего края окна. Левая колонка ниже подсказок пуста, и правая
            //  половина уходила под них на два десятка точек — край выглядел рваным.
            rightColH.value = null;
            if (ui3Mode) {
                const sg = document.querySelector('[data-help="suggest"]') || document.querySelector('.printers-pane');
                if (sg) {
                    const h = Math.round((sg.getBoundingClientRect().bottom - top) / _k);
                    if (h > 200) rightColH.value = h + 'px';
                }
                //  2.977 (R-096): та же высота — переменной оформления, по ней равняются большие
                //  окна (файлы принтеров, настройки, отчёты, диагностика).
                try { document.documentElement.style.setProperty('--u3-right-h', rightColH.value || ''); } catch (e) {}
            }
        } catch (e) { leftColH.value = null; rightColH.value = null; }
    };
    //  Подсказки растут и сжимаются (пришло сообщение, свернули панель) — правая половина
    //  обязана следовать за ними, иначе выравнивание держалось бы только до первого сообщения.
    let _rcRaf = 0, _rcRo = null;
    const _watchSuggestHeight = () => {
        if (!ui3Mode || _rcRo || typeof ResizeObserver === 'undefined') return;
        const sg = document.querySelector('[data-help="suggest"]');
        if (!sg) return;
        _rcRo = new ResizeObserver(() => {
            if (_rcRaf) return;
            _rcRaf = requestAnimationFrame(() => { _rcRaf = 0; recalcLeftCol(); });
        });
        _rcRo.observe(sg);
    };
    // applyUiFont меняет html{zoom} (он зависит от выбранного шрифта) — поэтому масштаб рабочей области
    // пересчитывается ПОСЛЕ него и ДО замера высоты колонки.
    const _onResize = () => { _vw.value = window.innerWidth; _vh.value = window.innerHeight; applyUiFont(); applyWrapZoom(); nextTick(() => { recalcLeftCol(); _watchSuggestHeight(); }); };
    const mobileTab = ref('printers');   // активная секция на телефоне: 'printers' | 'projects'

    // ------------------------------------------------------------------------
    // БЛОК: подсказки, проверка новой версии и детерминированные алерты.
    // ------------------------------------------------------------------------

    // --- Проверка обновлений: фронт спрашивает наш сервер (он сам ходит на сайт, поэтому без CORS).
    // Если на сайте версия новее — показываем баннер в ячейке «Подсказки». Ошибки тихо игнорируем.
    const updateInfo = ref(null);
    let updateTimer = null;
    //  R-131 (29.09.2026): выключатель «Проверять обновления» — настройка ФЕРМЫ (сервер хранит,
    //  сервер же и не ходит на сайт, когда выключено). По умолчанию включено, как было.
    const updateCheckOn = ref(true);
    const _updateCheckFromServer = (v) => {
        const on = v !== '0';
        const was = updateCheckOn.value;
        updateCheckOn.value = on;
        if (!on) updateInfo.value = null;
        else if (!was) checkUpdate();
    };
    const checkUpdate = async () => {
        if (!updateCheckOn.value) { updateInfo.value = null; return; }
        try { const r = await fetch('/api/update-check'); if (r.ok) updateInfo.value = await r.json(); } catch (e) {}
    };
    const setUpdateCheck = async (on) => {
        const was = updateCheckOn.value;
        updateCheckOn.value = !!on;
        if (!await _queueAutoPush({ update_check: on ? '1' : '0' })) {
            updateCheckOn.value = was;        // не записалось — экран не должен врать
            return;
        }
        if (on) checkUpdate(); else updateInfo.value = null;
    };
    //  R-131: открываем только https-ссылку. Сервер уже пропускает лишь https на официальный
    //  сайт; здесь вторая защита — на случай старого или чужого сервера.
    const updateUrlSafe = (u) => { try { return !!u && new URL(String(u)).protocol === 'https:'; } catch (e) { return false; } };
    const openUpdate = () => { const u = updateInfo.value && updateInfo.value.url; if (updateUrlSafe(u)) window.open(u, '_blank'); };

    //  Сценарий «тип принтера -> подсветка подходящих файлов» удалён (заказ владельца,
    //  05.09.2026): панель «Подсказки» теперь показывает отправки и очереди.

    // ---- Настройки (шестерёнка) + задел под модули-плагины ----
    const showSettings = ref(false);
    const settingsPos = ref({ top: 52, right: 12 });
    const _vh = ref(window.innerHeight);
    // Высота меню настроек ограничивается видимой областью экрана (панель в body → масштабируется только html-зумом),
    // чтобы нижняя грань со скруглением не уходила за низ экрана; если содержимое не помещается — внутренняя прокрутка.
    const settingsMaxH = computed(() => {
        const _d = [ _vh.value, settingsPos.value.top, uiFont.value, isMobile.value, tourActive.value ];   // реактивные зависимости пересчёта
        const hz = parseFloat(getComputedStyle(document.documentElement).zoom) || 1.04;
        const vhz = _vh.value / hz, vwz = (window.innerWidth || 1280) / hz;
        // во время тура низ панели поднимаем выше нижней полосы навигации тура (~74px десктоп / ~112px компактный),
        // иначе подсвечиваемая секция (Доступ/Модули) уходит под полосу с номерами шагов
        const bottomReserve = tourActive.value ? ((vwz < 760 || vhz < 620) ? 124 : 90) : 36;
        return Math.max(180, Math.round(vhz - settingsPos.value.top - bottomReserve));
    });
    const openSettings = (ev) => {
        // Alpha 2.816: «Настройки» — рабочий экран основной области, а не окно. Диагностика занимает
        // тот же слот, поэтому две области не могут быть открыты одновременно — уводим её.
        if (showDiag.value) closeDiagnostics();
        if (showPrinterFiles.value) closePrinterFiles();   // Alpha 2.823: тот же слот
        if (showReports.value) closeReports();             // Alpha 2.898: тот же слот
        pfLoadFlags();                                     // карточка «Файлы принтеров» в Системе
        fetchBootId().then(() => {                          // Alpha 2.829: идентичность процесса
            try {
                const marker = localStorage.getItem('fm_pending_restart_boot') || '';
                if (marker && serverBootId.value && marker !== serverBootId.value) {
                    // Новый процесс уже поднялся: восстановленные настройки загружены — маркер снят.
                    localStorage.removeItem('fm_pending_restart_boot');
                    cbPendingRestart.value = false;
                } else if (marker) {
                    cbPendingRestart.value = true;          // перезапуск ещё требуется
                }
            } catch (e) {}
        });
        try { const r = ev.currentTarget.getBoundingClientRect(); settingsPos.value = { top: Math.round(r.bottom + 6), right: Math.round(window.innerWidth - r.right) }; } catch (e) { settingsPos.value = { top: 52, right: 12 }; }
        showSettings.value = true;
        loadStorageInfo();
        loadNetworkInfo();
        _restoreSetScroll();   // Alpha 2.816: вернуть прокрутку выбранного раздела после повторного открытия
    };
    // Alpha 2.815: закрытие настроек уносит и все вложенные диалоги — иначе на экране остался бы
    // диалог (или его затемнение) без родительского окна.
    const closeSettings = () => { fmCloseNested(); showSettings.value = false; };
    const settingsTab = ref('general');
    const setTabPrintShown = computed(() => can('project') || can('operate'));
    const curSetTab = computed(() => (settingsTab.value === 'print' && !setTabPrintShown.value) ? 'general' : settingsTab.value);
    // Alpha 2.816: раньше здесь окно «Настройки» блокировало прокрутку body/html — модальное поведение.
    // Теперь «Настройки» — рабочий экран, он НЕ должен запирать фон: колонка принтеров обязана
    // прокручиваться. Блокировку фона под ВЛОЖЕННЫМИ диалогами по-прежнему держит стек 2.815 (fmModalLock).
    // Alpha 2.816: память прокрутки разделов настроек. Один прокручиваемый контейнер .fm-settings-content,
    // разделы переключаются через v-show — сохраняем и возвращаем scrollTop по каждому разделу отдельно.
    const setScrollEl = ref(null);
    const _setScrollMem = {};
    const onSetScroll = () => { try { const el = setScrollEl.value; if (el) _setScrollMem[curSetTab.value] = el.scrollTop; } catch (e) {} };
    // Alpha 2.836: восстановленная позиция НЕ имеет права спрятать заголовок секции под
    // закреплённой полосой — иначе вкладка открывается «обрезанной», как на скриншоте владельца.
    // Контракт: позиция раздела помнится, но при возврате доводится до ближайшего корректного
    // якоря, если попала в зону под полосой. Первое открытие вкладки — всегда её начало (памяти
    // ещё нет, _setScrollMem пуст).
    const _setScrollClampSticky = () => {
        try {
            const m = setStickyMetrics();
            if (!m || !m.bandVis) return;
            const band = m.rect.top + m.bandVis;
            const secs = [].slice.call(m.box.querySelectorAll('[id^="fm-sec-"]'));
            for (let i = 0; i < secs.length; i++) {
                const r = secs[i].getBoundingClientRect();
                if (r.top > m.rect.top - 1 && r.top < band - 1) {
                    m.box.scrollTop = Math.max(0, m.box.scrollTop + (r.top - band) * m.k);
                    return;
                }
            }
        } catch (e) {}
    };
    const _restoreSetScroll = () => { nextTick(() => { try { const el = setScrollEl.value; if (el) el.scrollTop = _setScrollMem[curSetTab.value] || 0; _setScrollClampSticky(); } catch (e) {} }); };
    watch(settingsTab, _restoreSetScroll);
    // ── Alpha 2.679: окно «Настройки» — перемещаемое/масштабируемое (тот же паттерн, что окна проводника/диагностики/склада) ──
    // Инлайн-стиль на .fm-set-modal перекрывает CSS-центрирование (inset:0;margin:auto) и размеры; ручки resize — общие .ex-rz ядра.
    // Компенсируем html{zoom} (_setScale), держим окно в экране (clamp), min 600×440, localStorage 'settings_win'.
    // На узком экране (≤700px) и во время тура — возвращаем штатное CSS-центрирование, drag/resize выключены.
    const _SET_MINW = 600, _SET_MINH = 440;
    const _setNarrow = () => (window.innerWidth <= 700);
    const setWin = ref({ x: 0, y: 0, w: 880, h: 660, init: false });
    let _setLastGesture = 0;   // защита от закрытия по backdrop сразу после drag/resize
    const setWinStyle = computed(() => {
        if (!setWin.value.init || _setNarrow() || tourActive.value) return {};   // штатное CSS-центрирование (адаптив/тур)
        const g = setWin.value;
        return { position: 'fixed', left: g.x + 'px', top: g.y + 'px', right: 'auto', bottom: 'auto', margin: '0', width: g.w + 'px', height: g.h + 'px', maxWidth: 'none', maxHeight: 'none' };
    });
    const _setSave = () => { try { const g = setWin.value; localStorage.setItem('settings_win', JSON.stringify({ x: g.x, y: g.y, w: g.w, h: g.h })); } catch (e) {} };
    const setWinClampIntoView = () => {   // держим окно в пределах экрана (после ресайза браузера/перетаскивания)
        const W = window.innerWidth, H = window.innerHeight;
        const g = setWin.value;
        const w = Math.max(_SET_MINW, Math.min(g.w, W)), h = Math.max(_SET_MINH, Math.min(g.h, H));
        const x = Math.max(0, Math.min(Math.max(0, W - w), g.x));
        const y = Math.max(0, Math.min(Math.max(0, H - h), g.y));
        setWin.value = { x, y, w, h, init: true };
    };
    const _setDefault = () => {   // дефолт ≈ как сейчас: width min(880,94vw), height min(660,92vh), по центру
        const W = window.innerWidth, H = window.innerHeight;
        const w = Math.min(880, Math.round(W * 0.94)), h = Math.min(660, Math.round(H * 0.92));
        return { x: Math.round((W - w) / 2), y: Math.round((H - h) / 2), w, h, init: true };
    };
    const setWinEnsure = () => {   // при открытии: восстановить сохранённое или центр по дефолту, затем clamp
        if (!setWin.value.init) {
            let g = null; try { g = JSON.parse(localStorage.getItem('settings_win') || 'null'); } catch (e) {}
            if (g && g.w >= _SET_MINW && g.h >= _SET_MINH) setWin.value = { x: g.x, y: g.y, w: g.w, h: g.h, init: true };
            else setWin.value = _setDefault();
        }
        setWinClampIntoView();
    };
    const setWinReset = (e) => {   // double-click по шапке → дефолтный размер по центру
        if (e && e.target && e.target.closest && e.target.closest('button, input, select, a, label')) return;
        setWin.value = _setDefault(); setWinClampIntoView(); _setSave();
    };
    const _setScale = (e) => {   // окно fixed под html{zoom} — визуальные px → логические (rect/логич. ширина)
        try { const el = e.currentTarget && e.currentTarget.closest ? e.currentTarget.closest('.fm-set-modal') : null; if (el && setWin.value.w) { const k = el.getBoundingClientRect().width / setWin.value.w; if (k > 0.1 && k < 10) return k; } } catch (err) {}
        return 1;
    };
    const setDragStart = (e) => {
        if (_setNarrow() || tourActive.value) return;
        if (e.target && e.target.closest && e.target.closest('button, input, select, a, label')) return;   // не тащим за крестик/интерактив
        e.preventDefault();
        const k = _setScale(e);
        const sx = e.clientX, sy = e.clientY, ox = setWin.value.x, oy = setWin.value.y;
        document.body.style.userSelect = 'none';
        const mv = (ev) => {
            const VIS = 160;   // всегда оставляем ≥160px окна видимыми — нельзя утащить полностью за экран
            let nx = ox + (ev.clientX - sx) / k, ny = oy + (ev.clientY - sy) / k;
            nx = Math.max(VIS - setWin.value.w, Math.min(window.innerWidth - VIS, nx));
            ny = Math.max(0, Math.min(window.innerHeight - 44, ny));
            setWin.value.x = nx; setWin.value.y = ny;
        };
        const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); document.body.style.userSelect = ''; _setLastGesture = Date.now(); _setSave(); };
        window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    };
    const setResizeStart = (e, dir) => {
        if (_setNarrow() || tourActive.value) return;
        e.preventDefault();
        const k = _setScale(e);
        const sx = e.clientX, sy = e.clientY, o = { x: setWin.value.x, y: setWin.value.y, w: setWin.value.w, h: setWin.value.h };
        document.body.style.userSelect = 'none';
        const mv = (ev) => {
            const dx = (ev.clientX - sx) / k, dy = (ev.clientY - sy) / k;
            let x = o.x, y = o.y, w = o.w, h = o.h;
            if (dir.indexOf('e') >= 0) w = o.w + dx;
            if (dir.indexOf('s') >= 0) h = o.h + dy;
            if (dir.indexOf('w') >= 0) { w = o.w - dx; x = o.x + dx; if (w < _SET_MINW) { x = o.x + (o.w - _SET_MINW); w = _SET_MINW; } }
            if (dir.indexOf('n') >= 0) { h = o.h - dy; y = o.y + dy; if (h < _SET_MINH) { y = o.y + (o.h - _SET_MINH); h = _SET_MINH; } }
            if (w < _SET_MINW) w = _SET_MINW;
            if (h < _SET_MINH) h = _SET_MINH;
            if (x < 0) { if (dir.indexOf('w') >= 0) w += x; x = 0; }
            if (y < 0) { if (dir.indexOf('n') >= 0) h += y; y = 0; }
            if (x + w > window.innerWidth) w = window.innerWidth - x;
            if (y + h > window.innerHeight) h = window.innerHeight - y;
            if (w < _SET_MINW) w = _SET_MINW;
            if (h < _SET_MINH) h = _SET_MINH;
            setWin.value.x = x; setWin.value.y = y; setWin.value.w = w; setWin.value.h = h;
        };
        const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); document.body.style.userSelect = ''; _setLastGesture = Date.now(); _setSave(); };
        window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    };
    // Alpha 2.815: клик мимо действует только на ВЕРХНИЙ слой — пока открыт вложенный диалог,
    // затемнение настроек не закрывает их (его и не видно: фон диалога лежит выше).
    const setBackdropClose = () => { if (fmModalTopNested()) return; if (Date.now() - _setLastGesture < 250) return; closeSettings(); };   // клик по затемнению закрывает, но не сразу после жеста
    window.addEventListener('resize', () => { if (showSettings.value && setWin.value.init) setWinClampIntoView(); });
    // Alpha 2.836: при resize и смене увеличения чипы переносятся на другое число строк, поэтому
    // высота закреплённой полосы меняется — пересчитываем её единый источник истины.
    window.addEventListener('resize', () => { if (showSettings.value) { try { setStickyMetrics(); } catch (e) {} } });
    watch(showSettings, (v) => { if (v) setWinEnsure(); });
    const storageInfo = ref({ data_dir: '', archive_dir: '', archive_dir_is_default: true, data_dir_is_default: true });
    const archiveDirInput = ref('');
    const storageBusy = ref(false);
    const dataDirPending = ref('');
    const pickDirTarget = ref('');
    // 29.09.2026: итог последнего переноса папки данных (data-move-report.json) — текстом для
    // «Хранения данных». Неудачный показывается, пока перенос ждёт повтора; удачный — неделю.
    const dataMoveTexts = (m) => {
        if (!m || !m.active) return ['', ''];
        const nm = (a, n) => (a || []).join(', ') + ((n || 0) > (a || []).length ? ' …' : '');
        const gb = (b) => (Math.round((Number(b) || 0) / 1e8) / 10).toFixed(1);
        const _d = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(String(m.at || ''));
        const at = _d ? [_d[3] + '.' + _d[2] + '.' + _d[1] + ' ' + _d[4] + ':' + _d[5], _d[1] + '-' + _d[2] + '-' + _d[3] + ' ' + _d[4] + ':' + _d[5]] : [m.at || '', m.at || ''];
        if (m.status !== 'ok') {
            const it = m.reason_item || '';
            const why = ({
                module_swap_pending: ['не закончена замена модуля — программа завершит её при этом запуске', 'a module update was not finished — the app completes it on this start'],
                target_inside_item: ['новая папка лежит внутри переносимой папки «' + it + '»', 'the new folder is inside the folder being moved: ' + it],
                link_not_supported: ['«' + it + '» — ссылка на другую папку, такие элементы не переносятся', it + ' is a link to another folder; links are not moved'],
                not_enough_space: ['не хватает места: нужно ' + gb(m.needed_bytes) + ' ГБ, свободно ' + gb(m.free_bytes) + ' ГБ', 'not enough space: ' + gb(m.needed_bytes) + ' GB needed, ' + gb(m.free_bytes) + ' GB free'],
                conflict: ['в новой папке уже есть другой файл «' + it + '»', 'the new folder already has a different file ' + it],
                copy_failed: ['не удалось скопировать «' + it + '»', 'could not copy ' + it],
                verify_failed: ['копия «' + it + '» не совпала с оригиналом', 'the copy of ' + it + ' did not match the original'],
                source_unreadable: ['не удалось прочитать прежнюю папку', 'could not read the previous folder'],
            })[m.reason] || ['ошибка ' + (m.reason || '?'), 'error ' + (m.reason || '?')];
            return ['Перенос папки данных не выполнен (' + at[0] + '): ' + why[0] + '. Ничего не удалено: программа работает из прежней папки, перенос повторится при следующем запуске. Чтобы отказаться от переноса, выберите нынешнюю папку ещё раз.',
                    'The data folder was not moved (' + at[1] + '): ' + why[1] + '. Nothing was deleted: the app works from the previous folder and retries on the next start. To cancel the move, choose the current folder again.'];
        }
        let ru = 'Данные перенесены ' + at[0] + ' из ' + m.from + ': элементов ' + m.moved + ', файлов ' + m.files + ', каждый сверен с оригиналом.';
        let en = 'Data moved on ' + at[1] + ' from ' + m.from + ': ' + m.moved + ' items, ' + m.files + ' files, each checked against the original.';
        if (m.left_count) { ru += ' Не перенесено, осталось в прежней папке: ' + nm(m.left, m.left_count) + '.'; en += ' Not moved, left in the previous folder: ' + nm(m.left, m.left_count) + '.'; }
        if (m.unknown_count) { ru += ' Не данные программы, оставлено на месте: ' + nm(m.unknown, m.unknown_count) + '.'; en += ' Not app data, left in place: ' + nm(m.unknown, m.unknown_count) + '.'; }
        return [ru, en];
    };
    const loadStorageInfo = async () => {
        try {
            const j = await (await fetch('/api/storage')).json();
            const _mv = dataMoveTexts(j && j.data_move);
            storageInfo.value = Object.assign({}, j || {}, { data_move_ru: _mv[0], data_move_en: _mv[1],
                data_move_ok: !!(j && j.data_move && j.data_move.status === 'ok') });
            archiveDirInput.value = (j && !j.archive_dir_is_default) ? (j.archive_dir_custom || j.archive_dir || '') : '';
            dataDirPending.value = (j && j.data_dir_pending) || '';
        } catch (e) {}
    };
    // ── Локальное обнаружение (входящий LAN-доступ, Alpha 2.720). Управляет только тем, слушает ли сервер
    //    сеть (0.0.0.0) или только этот ПК (127.0.0.1). Смена host применяется при перезапуске. ──
    // Alpha 2.787: сеть открывается только при включённой авторизации И активном администраторе.
    // Различаем ТРИ разные вещи, которые раньше сливались в одну: что запрошено в настройке,
    // что разрешено проверкой прямо сейчас и что фактически слушает работающий процесс
    // (последнее меняется только при перезапуске). Значения читаем СТРОГО как true —
    // прежняя логика «!== false» считала включённым любое неизвестное состояние.
    const lanAccess = ref(false);           // запрошенное значение (config.json)
    const lanApplied = ref(false);          // фактически применённое (с чем запущен сервер)
    const lanRestartRequired = ref(false);  // запрошенное != применённого -> «Требуется перезапуск»
    const lanCanEnable = ref(false);        // предпосылки выполнены прямо сейчас
    const lanBlockedReason = ref('');       // безопасный код причины блокировки
    const lanAuthEnabled = ref(false);      // включена ли авторизация
    const lanAdminPresent = ref(false);     // есть ли активный администратор
    const lanBusy = ref(false);
    // ── Alpha 2.837 ───────────────────────────────────────────────────────────────────────
    // lanEnableBlocked — причина, по которой ВКЛЮЧЕНИЕ недоступно (поле enable_blocked_reason).
    // Отдельно от lanBlockedReason: тот при выключенном тумблере всегда 'lan_disabled', поэтому
    // ветки объяснений ниже не могли сработать НИКОГДА — флажок был просто погашен без причины.
    const lanEnableBlocked = ref('');
    // Разрешено ли ЭТОМУ клиенту менять машинную настройку. Значение приходит от сервера
    // (change_allowed) и дополнительно сверяется с адресом окна: сервер остаётся авторитетом,
    // интерфейс лишь не предлагает действие, которое всё равно будет отклонено.
    const lanChangeAllowedSrv = ref(true);
    const lanUrl = ref('');                 // адрес в сети — только когда сеть ФАКТИЧЕСКИ слушается
    const lanError = ref('');               // текст последней ошибки сохранения (пусто = ошибок нет)
    const lanHint = computed(() => {
        const ru = lang.value === 'ru';
        if (lanBlockedReason.value === 'auth_required')
            return ru ? 'Для доступа из локальной сети сначала создайте администратора и включите авторизацию.'
                      : 'To allow local network access, first create an administrator and enable authorization.';
        if (lanBlockedReason.value === 'enabled_admin_required')
            return ru ? 'Нужен хотя бы один активный администратор. Создайте его в разделе «Доступ и аудит».'
                      : 'At least one active administrator is required. Create one in Access and audit.';
        if (lanBlockedReason.value === 'admin_check_failed')
            return ru ? 'Не удалось проверить администраторов, сетевой доступ заблокирован.'
                      : 'Administrator check failed; network access is blocked.';
        if (lanBlockedReason.value === 'config_invalid')
            return ru ? 'Настройки повреждены, сетевой доступ заблокирован.'
                      : 'Configuration is invalid; network access is blocked.';
        if (lanRestartRequired.value && lanAccess.value)
            return ru ? 'Настройка сохранена. Сеть откроется после перезапуска программы.'
                      : 'Saved. The network will open after a restart.';
        if (lanRestartRequired.value && !lanAccess.value)
            return ru ? 'После перезапуска сервер будет доступен только на этом компьютере. До перезапуска авторизацию нельзя отключать.'
                      : 'After a restart the server will be local-only. Until then, authorization cannot be disabled.';
        return lanApplied.value
            ? (ru ? 'Сервер сейчас доступен из локальной сети.' : 'The server is currently reachable on the local network.')
            : (ru ? 'Сервер сейчас работает только на этом компьютере.' : 'The server is currently local-only.');
    });
    // ── Серверный порт в настройках (Alpha 2.814) ────────────────────────────
    // Отдельной реализации смены порта здесь НЕТ: интерфейс лишь показывает то, что сказал
    // сервер, и просит его выполнить проверку и смену. Валидация, проверка занятости, запись
    // pending/previous, перезапуск и откат живут в ядре — там же, откуда их зовёт пункт трея.
    const netPort = ref(0);
    const netPendingPort = ref(0);
    const showPortDialog = ref(false);
    const portInput = ref('');
    const portBusy = ref(false);
    const portError = ref('');
    // Менять машинную настройку вправе только тот, кто сидит за компьютером-сервером. Это лишь
    // подсказка интерфейса: настоящую границу держит сервер, и подделать её отсюда нельзя.
    const portCanChange = computed(() => ['localhost', '127.0.0.1', '::1', '[::1]'].includes(location.hostname));
    // Alpha 2.837: сетевой режим — такая же МАШИННАЯ настройка, как порт, и граница у них одна
    // (_require_server_machine на сервере). В удалённом клиенте действие не предлагается вовсе,
    // а не «предлагается и молча не работает».
    const lanChangeAllowed = computed(() => lanChangeAllowedSrv.value && portCanChange.value);
    // Почему флажок недоступен. Пусто = действие разрешено, тогда панель не показывается вовсе.
    const lanBlockedText = computed(() => {
        const ru = lang.value === 'ru';
        if (!lanChangeAllowed.value)
            return ru ? 'Сетевой доступ меняется только на компьютере-сервере. В удалённом клиенте видно состояние, но не изменение.'
                      : 'Network access can only be changed on the server computer. A remote client shows the state but cannot change it.';
        if (lanAccess.value || lanCanEnable.value) return '';
        const r = lanEnableBlocked.value;
        if (r === 'auth_required')
            return ru ? 'Чтобы открыть доступ из локальной сети, сначала создайте администратора и включите авторизацию в разделе «Доступ и аудит».'
                      : 'To open local network access, first create an administrator and enable authorization in Access and audit.';
        if (r === 'enabled_admin_required')
            return ru ? 'Нужен хотя бы один активный администратор. Создайте его в разделе «Доступ и аудит».'
                      : 'At least one active administrator is required. Create one in Access and audit.';
        if (r === 'admin_check_failed')
            return ru ? 'Не удалось проверить администраторов — включение доступа из сети заблокировано.'
                      : 'The administrator check failed — enabling network access is blocked.';
        if (r === 'config_invalid')
            return ru ? 'Настройки повреждены — включение доступа из сети заблокировано.'
                      : 'The configuration is invalid — enabling network access is blocked.';
        return ru ? 'Включение доступа из локальной сети сейчас недоступно.'
                  : 'Enabling local network access is currently unavailable.';
    });
    // Человеческий текст отказа сервера. Безопасные коды причин приходят от ядра; неизвестный
    // код не выдумывается, а превращается в честное «не удалось сохранить».
    const LAN_REASONS = {
        server_machine_only: { ru: 'Изменение доступно только на компьютере-сервере.', en: 'This change is only available on the server computer.' },
        auth_required: { ru: 'Сначала включите авторизацию и создайте администратора.', en: 'First enable authorization and create an administrator.' },
        enabled_admin_required: { ru: 'Нужен хотя бы один активный администратор.', en: 'At least one active administrator is required.' },
        admin_check_failed: { ru: 'Не удалось проверить администраторов. Настройка не изменена.', en: 'The administrator check failed. The setting is unchanged.' },
        config_invalid: { ru: 'Настройки повреждены. Настройка не изменена.', en: 'The configuration is invalid. The setting is unchanged.' },
    };
    const lanErrorText = (code) => {
        const e = LAN_REASONS[String(code || '')];
        if (e) return lang.value === 'ru' ? e.ru : e.en;
        return lang.value === 'ru' ? 'Не удалось сохранить настройку. Показано состояние сервера.'
                                   : 'Could not save the setting. The server state is shown.';
    };
    const PORT_REASONS = {
        server_machine_only: { ru: 'Изменение порта доступно только на компьютере-сервере.', en: 'The port can only be changed on the server computer.' },
        busy: { ru: 'Этот порт уже занят другой программой. Выберите другой.', en: 'That port is already used by another program. Choose another one.' },
        save_fail: { ru: 'Не удалось сохранить настройку. Прежний порт остался без изменений.', en: 'Could not save the setting. The current port is unchanged.' },
        empty: { ru: 'Введите номер порта.', en: 'Enter a port number.' },
        not_int: { ru: 'Порт — целое число от 1024 до 65535.', en: 'The port must be a whole number from 1024 to 65535.' },
        out_of_range: { ru: 'Допустимы порты от 1024 до 65535.', en: 'Ports from 1024 to 65535 are allowed.' },
        forbidden: { ru: 'Недостаточно прав для изменения порта.', en: 'Not enough rights to change the port.' },
        restart_in_progress: { ru: 'Перезапуск уже выполняется.', en: 'A restart is already in progress.' },
    };
    const portReasonText = (code) => {
        const e = PORT_REASONS[String(code || '')];
        if (e) return lang.value === 'ru' ? e.ru : e.en;
        return restartReasonText(code);   // общие причины перезапуска — тем же словарём, что и у трея
    };
    const openPortDialog = () => {
        portError.value = ''; portBusy.value = false;
        portInput.value = String(netPendingPort.value || netPort.value || '');
        showPortDialog.value = true;
    };
    const closePortDialog = () => { if (!portBusy.value) showPortDialog.value = false; };
    const applyPort = async (restartNow) => {
        if (portBusy.value) return;             // двойная отправка = одна операция
        portBusy.value = true; portError.value = '';
        try {
            const r = await fetch('/api/network', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ server_port: portInput.value, restart_now: !!restartNow }),
            });
            const j = await r.json().catch(() => null);
            if (!r.ok || !j || j.status !== 'ok') {
                // Ошибка НЕ закрывает диалог: введённое значение остаётся, его можно поправить.
                portError.value = portReasonText((j && j.reason) || '');
                await loadNetworkInfo();
                return;
            }
            netPort.value = Number(j.active_port) || netPort.value;
            netPendingPort.value = Number(j.pending_port) || 0;
            if (j.restart_armed) {
                // Перезапуск подтверждён ядром (supervisor 2.809/2.811). Показываем тот же экран
                // ожидания, что и у обычного перезапуска, и переезжаем на новый адрес.
                showPortDialog.value = false;
                await restartWaitReady(j.target_origin || '');
                return;
            }
            showPortDialog.value = false;
            await loadNetworkInfo();
            pushToast(j.result === 'noop'
                ? (lang.value === 'ru' ? 'Это текущий порт — ничего не изменилось.' : 'That is the current port — nothing changed.')
                : (lang.value === 'ru' ? 'Новый порт будет применён после перезапуска.' : 'The new port will be applied after a restart.'));
        } catch (e) {
            portError.value = lang.value === 'ru' ? 'Сервер не ответил. Повторите попытку.' : 'The server did not respond. Try again.';
        } finally { portBusy.value = false; }
    };
    const _applyNet = (j) => {
        lanAccess.value = (j.requested_enabled === true) || (j.lan_access_enabled === true);
        lanApplied.value = (j.current_bind_scope ? j.current_bind_scope === 'network' : j.applied === true);
        lanRestartRequired.value = !!j.restart_required;
        lanCanEnable.value = j.can_enable === true;
        lanBlockedReason.value = j.blocked_reason || '';
        lanAuthEnabled.value = j.auth_enabled === true;
        lanAdminPresent.value = j.enabled_admin_present === true;
        // Alpha 2.837: причина недоступности включения и машинная граница — из ответа сервера.
        // Отсутствие полей (старое ядро) НЕ запрещает действие: прежний контракт сохраняется.
        lanEnableBlocked.value = j.enable_blocked_reason || '';
        lanChangeAllowedSrv.value = j.change_allowed !== false;
        // Адрес в сети показываем ТОЛЬКО когда сервер сам сообщил, что сеть уже слушается.
        lanUrl.value = lanApplied.value ? String(j.lan_url || '') : '';
        // Alpha 2.814: порт показываем ТОЛЬКО из ответа сервера. Ни текущего значения, ни 8000
        // «по умолчанию» интерфейс не придумывает: источник истины — работающий сервер.
        netPort.value = Number(j.port) || 0;
        netPendingPort.value = Number(j.pending_port) || 0;
    };
    let _lastNet = {};
    const loadNetworkInfo = async () => {
        try { const j = await (await fetch('/api/network')).json(); _lastNet = j || {}; _applyNet(_lastNet); } catch (e) {}
    };
    const setLanAccess = async (v) => {
        if (lanBusy.value) return;              // busy-guard: двойной клик = один запрос
        if (v && !lanCanEnable.value) { await loadNetworkInfo(); return; }   // предпосылки не выполнены
        if (!lanChangeAllowed.value) { await loadNetworkInfo(); return; }    // машинная граница (2.837)
        const prev = lanAccess.value;
        // Alpha 2.837: результат сохранения виден пользователю. Прежде ошибка молча откатывала
        // тумблер, и «ничего не произошло» выглядело как неработающая настройка.
        let saved = false, why = '';
        lanBusy.value = true; lanAccess.value = !!v; lanError.value = '';   // оптимистично — тумблер сразу
        try {
            const r = await fetch('/api/network', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lan_access_enabled: !!v }) });
            const j = await r.json();
            if (!r.ok || (j && j.status) !== 'ok') { why = (j && (j.reason || j.message)) || ''; throw new Error('save'); }
            //  13.10.2026: ответ сохранения неполный (lan_access_enabled, applied, restart_required, port) —
            //  прежде он ЗАМЕНЯЛ состояние: «можно включить» становилось false, флажок блокировался до
            //  повторного открытия настроек. Теперь дополняем последнее полное состояние; «запрошено»
            //  берём из ответа (иначе при выключении флажок остался бы стоять).
            const _m = Object.assign({}, _lastNet, j);
            if (!('requested_enabled' in j)) _m.requested_enabled = !!j.lan_access_enabled;
            _lastNet = _m; _applyNet(_m); saved = true;
        } catch (e) { lanAccess.value = prev; await loadNetworkInfo(); }   // откат тумблера и свежее состояние
        lanError.value = saved ? '' : lanErrorText(why);
        lanBusy.value = false;
    };
    const applyArchiveDir = async () => {
        storageBusy.value = true;
        try {
            const j = await (await fetch('/api/storage/archive', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: (archiveDirInput.value || '').trim() }) })).json();
            if (j && j.status === 'ok') { await loadStorageInfo(); }
            else { alert((j && j.message) || (lang.value === 'ru' ? 'Не удалось изменить папку' : 'Could not change folder')); }
        } catch (e) { alert(String(e)); }
        storageBusy.value = false;
    };
    const resetArchiveDir = () => { archiveDirInput.value = ''; applyArchiveDir(); };
    const applyDataDir = async (path) => {
        storageBusy.value = true;
        try {
            const j = await (await fetch('/api/storage/data', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: (path || '').trim() }) })).json();
            if (j && j.status === 'ok') {
                await loadStorageInfo();
                if (j.changed) { restartPendingPath.value = j.pending || ''; restartInProgress.value = false; showRestartModal.value = true; }
            } else { alert((j && (lang.value === 'ru' ? j.message : (j.message_en || j.message))) || (lang.value === 'ru' ? 'Не удалось изменить папку' : 'Could not change folder')); }
        } catch (e) { alert(String(e)); }
        storageBusy.value = false;
    };
    const resetDataDir = () => applyDataDir('');
    const openStorageFolder = (which) => {
        const folder = which === 'data' ? (storageInfo.value.data_dir || '') : (storageInfo.value.archive_dir || '');
        if (folder) exOpenWith('tasks', null, folder);   // 🔒 ОТЛАЖЕНО — «Открыть папку» открывает НАШ файловый менеджер (не Windows-проводник). Не менять без перепроверки.
    };
    const showRestartModal = ref(false);
    const restartPendingPath = ref('');
    const restartInProgress = ref(false);
    // ── Перезапуск программы (Alpha 2.809) ───────────────────────────────────
    // Прежняя версия отправляла запрос и СРАЗУ считала перезапуск начавшимся, а по истечении
    // ожидания делала location.reload(). Если сервер не поднимался, пользователь получал
    // пустую страницу ошибки браузера вместо программы — ровно то, что и произошло на ферме.
    // Теперь порядок такой: дождаться подтверждения restart_armed, показать экран ожидания
    // и только после реально ответившего /version перезагрузить интерфейс. Ошибка на любом шаге —
    // отдельное честное состояние с инструкцией, а не молчаливая перезагрузка.
    // Пути пишем абсолютными: раньше здесь стояли обратные слеши, то есть управляющие
    // символы JS, и запрос доходил лишь потому, что браузер чинил URL за нас.
    const restartPhase = ref('idle');     // idle | arming | waiting | failed | timeout
    const restartError = ref('');
    const RESTART_REASONS = {
        restart_in_progress: { ru: 'Перезапуск уже выполняется.', en: 'A restart is already in progress.' },
        executable_missing: { ru: 'Не найден исполняемый файл программы.', en: 'Program executable not found.' },
        entry_missing: { ru: 'Не найден файл запуска программы.', en: 'Program entry point not found.' },
        workdir_missing: { ru: 'Не найдена рабочая папка программы.', en: 'Working folder not found.' },
        wrong_executable: { ru: 'Перезапуск указывает не на серверный файл программы.', en: 'Restart points to a non-server executable.' },
        command_rejected: { ru: 'Команда перезапуска не прошла проверку.', en: 'Restart command rejected by validation.' },
        spawn_failed: { ru: 'Не удалось запустить служебный процесс перезапуска.', en: 'Could not start the restart helper.' },
        journal_unavailable: { ru: 'Нет доступа к служебному файлу перезапуска.', en: 'Restart state file is not accessible.' },
        arm_timeout: { ru: 'Служебный процесс перезапуска не подтвердил готовность.', en: 'The restart helper did not confirm readiness.' },
        journal_invalid: { ru: 'Служебный файл перезапуска повреждён.', en: 'Restart state file is invalid.' },
        stale_plan: { ru: 'План перезапуска устарел.', en: 'The restart plan is stale.' },
        helper_crashed: { ru: 'Служебный процесс перезапуска аварийно завершился.', en: 'The restart helper crashed.' },
    };
    const restartReasonText = (code) => {
        const e = RESTART_REASONS[String(code || '')];
        if (e) return lang.value === 'ru' ? e.ru : e.en;
        return lang.value === 'ru' ? 'Не удалось подготовить перезапуск.' : 'Could not prepare the restart.';
    };
    const restartMessage = computed(() => {
        if (restartPhase.value === 'failed') {
            return restartReasonText(restartError.value) + ' ' +
                (lang.value === 'ru' ? 'Farm Manager продолжает работать.' : 'Farm Manager keeps running.');
        }
        if (restartPhase.value === 'timeout' && dataDirPending.value) {
            // 29.09.2026: перенос большой папки данных идёт ДО подъёма сервера и может занять
            // минуты — «не удалось подключиться» здесь не значит, что программа не работает.
            return lang.value === 'ru'
                ? 'Программа ещё не ответила: возможно, ещё идёт перенос папки данных. Не закрывайте её — подождите и нажмите «Повторить подключение».'
                : 'The app has not answered yet: the data folder may still be moving. Do not close it — wait and press “Retry connection”.';
        }
        if (restartPhase.value === 'timeout') {
            return lang.value === 'ru'
                ? 'Не удалось автоматически подключиться после перезапуска. Если Farm Manager не запущен — завершите его через значок в трее и запустите снова.'
                : 'Could not reconnect automatically after the restart. If Farm Manager is not running, close it via the tray icon and start it again.';
        }
        if (restartPhase.value === 'waiting' || restartPhase.value === 'arming') {
            return lang.value === 'ru' ? 'Farm Manager перезапускается…' : 'Farm Manager is restarting…';
        }
        return '';
    });
    // Машинный код причины для диагностики (Alpha 2.810): только безопасный идентификатор
    // из журнала перезапуска — без путей, команд и traceback. Непохожее на код значение
    // не показывается как есть, а заменяется на 'unknown'.
    const restartReasonCode = computed(() => {
        if (restartPhase.value !== 'failed') return '';
        const c = String(restartError.value || '');
        return /^[a-z0-9_]{1,40}$/i.test(c) ? c : 'unknown';
    });
    const serverBootId = ref('');            // Alpha 2.829: идентичность ТЕКУЩЕГО процесса сервера
    const restartOldBootId = ref('');        // boot_id, зафиксированный ПЕРЕД перезапуском
    const restartWaitLong = ref(false);      // 29.09.2026: преемник переносит папку данных — ждать до 30 минут
    const fetchBootId = async () => {
        try {
            const r = await fetch('/version', { cache: 'no-store' });
            if (r.ok) { const j = await r.json().catch(() => null); if (j && j.boot_id) serverBootId.value = String(j.boot_id); }
        } catch (e) {}
    };
    const restartProbe = async () => {
        // Alpha 2.829: возвращает { alive, bootId }. Bounded: висящий fetch (backlog нового
        // процесса) обрывается, чтобы цикл ожидания оставался управляемым.
        const ctl = new AbortController();
        const tm = setTimeout(() => { try { ctl.abort(); } catch (e) {} }, 4000);
        try {
            const r = await fetch('/version', { cache: 'no-store', signal: ctl.signal });
            if (!r.ok) return { alive: false, bootId: '' };
            const j = await r.json().catch(() => null);
            return { alive: !!(j && j.version), bootId: String((j && j.boot_id) || '') };
        } catch (e) { return { alive: false, bootId: '' }; }
        finally { clearTimeout(tm); }
    };
    const hardReloadOnce = (newBootId) => {
        // Guard от reload-петли: ровно ОДИН hard reload на конкретный новый процесс.
        try {
            const key = 'fm_restart_reload_done';
            if (sessionStorage.getItem(key) === String(newBootId)) return false;
            sessionStorage.setItem(key, String(newBootId));
        } catch (e) {}
        location.reload();
        return true;
    };
    const restartWaitReady = async (targetOrigin) => {
        restartPhase.value = 'waiting';
        // Ограниченное ожидание. Экран ожидания остаётся видимым всё это время:
        // страница уже загружена и от сервера не зависит.
        // Alpha 2.814: при смене порта сервер вернётся по ДРУГОМУ адресу. Опрашивать чужой
        // origin из этой страницы браузер не даст (и ослаблять политику ради этого нельзя),
        // поэтому контракт такой: ждём, пока замолчит текущий адрес, даём ограниченное время на
        // возможный откат — если старый адрес ожил, значит откат, остаёмся здесь; если не ожил,
        // переходим на новый адрес верхнеуровневой навигацией.
        const target = String(targetOrigin || '');
        // Alpha 2.829 ROOT CAUSE FIX: прежний контракт требовал ПОЙМАТЬ окно недоступности
        // (down -> up) опросом раз в секунду. Новый процесс бинд-ит сокет РАНО (контракт порта
        // 2.806), запросы на время старта встают в backlog: fetch не падает, а «висит и отвечает» —
        // окно недоступности невидимо, downSince не устанавливался, reload не выполнялся, overlay
        // висел до таймаута. Теперь НОВЫЙ процесс определяется по СМЕНЕ boot_id (/version), без
        // гонки; down/up остаётся лишь запасным путём для сервера без boot_id.
        const oldBoot = restartOldBootId.value || serverBootId.value || '';
        let downSince = 0;
        // 29.09.2026: при смене папки данных преемник сначала переносит данные (до порта) —
        // на большой папке это минуты, поэтому doRestart просит ждать дольше (до 30 минут).
        const waitLimit = restartWaitLong.value ? 1800 : 90;
        for (let i = 0; i < 1800; i++) {
            if (i >= waitLimit) break;
            await new Promise((res) => setTimeout(res, 1000));
            const probe = await restartProbe();
            if (probe.alive) {
                if (probe.bootId && oldBoot && probe.bootId !== oldBoot) { hardReloadOnce(probe.bootId); return; }
                if (probe.bootId && !oldBoot) { hardReloadOnce(probe.bootId); return; }
                if (!probe.bootId && downSince) { location.reload(); return; }   // запасной путь (без boot_id)
                continue;                                        // всё ещё прежний процесс
            }
            if (!downSince) downSince = (i || 1);
            if (target && (i - downSince) >= 12) { location.assign(target + '/'); return; }
        }
        restartPhase.value = 'timeout';
    };
    const doRestart = async () => {
        if (restartInProgress.value) return;      // двойной клик не создаёт второй перезапуск
        restartInProgress.value = true;
        restartPhase.value = 'arming';
        restartError.value = '';
        restartOldBootId.value = serverBootId.value || '';   // идентичность СТАРОГО процесса
        if (!restartOldBootId.value) { await fetchBootId(); restartOldBootId.value = serverBootId.value || ''; }
        let armed = false;
        try {
            const r = await fetch('/api/restart', { method: 'POST' });
            const j = await r.json().catch(() => null);
            armed = !!(r.ok && j && j.restart_armed === true);
            if (!armed) restartError.value = (j && j.reason) || '';
        } catch (e) { restartError.value = ''; }
        if (!armed) {
            // Сервер НЕ остановлен: подготовка не удалась. Показываем причину и разрешаем повтор.
            restartPhase.value = 'failed';
            restartInProgress.value = false;
            return;
        }
        restartWaitLong.value = !!dataDirPending.value;   // 29.09.2026: перенос папки данных — ждать дольше
        await restartWaitReady();
    };
    const retryRestartConnection = async () => {
        const probe = await restartProbe();
        if (probe.alive) {
            const oldBoot = restartOldBootId.value || '';
            if (probe.bootId && oldBoot && probe.bootId !== oldBoot) { hardReloadOnce(probe.bootId); return; }
            if (!oldBoot || !probe.bootId) { location.reload(); return; }
        }
        restartPhase.value = 'timeout';
    };
    const dismissRestartState = () => { restartPhase.value = 'idle'; restartError.value = ''; restartInProgress.value = false; };
    const dismissRestart = () => { showRestartModal.value = false; };
    // ── 16.10.2026 (R-151): папка данных фермы недоступна ───────────────────────────────────
    // Сервер не нашёл свою папку данных (флешка, сетевой диск) и работает из пустой временной
    // папки, ничего в ней не сохраняя. Окно закрыть нельзя: работа в пустой ферме стала бы второй,
    // ненастоящей фермой. Принтеры допечатывают начатое; программа перезапустится сама, как только
    // папка вернётся, а страница перезагрузится, увидев новый процесс сервера.
    const dataDirUnavailable = computed(() => (storageInfo.value && storageInfo.value.data_dir_unavailable) || null);
    const dduBusy = ref(false);
    const dduMsg = ref('');
    const dduWhere = computed(() => {
        const u = dataDirUnavailable.value || {};
        return u.reason === 'move_source_missing' ? (u.move_from || '') : (u.configured_abs || u.configured || '');
    });
    const dduTitle = computed(() => {
        const w = dduWhere.value;
        return lang.value === 'ru' ? ('Папка данных фермы недоступна' + (w ? ': ' + w : ''))
                                   : ('The farm data folder is unavailable' + (w ? ': ' + w : ''));
    });
    const dduText = computed(() => {
        const u = dataDirUnavailable.value || {};
        const ru = lang.value === 'ru';
        const why = ({
            missing: ['Папки нет: диск не подключён или папку переименовали.', 'The folder is missing: the drive is not connected or the folder was renamed.'],
            no_farm_data: ['Папка есть, но данных фермы в ней нет — возможно, подключён другой диск.', 'The folder exists but holds no farm data — maybe another drive is connected.'],
            not_writable: ['В папку нельзя записывать.', 'The folder cannot be written to.'],
            unreachable: ['Диск не отвечает.', 'The drive does not respond.'],
            move_source_missing: ['Перенос папки данных ждёт прежнюю папку, а её нет: диск не подключён.', 'The data folder move is waiting for the previous folder, which is missing: the drive is not connected.'],
            config_unreadable: ['Файл настроек программы config.json повреждён (его копия сохранена рядом), поэтому неизвестно, где лежит ферма.', 'The app settings file config.json is damaged (a copy was kept next to it), so the farm location is unknown.'],
        })[u.reason] || ['', ''];
        const tail = u.returned
            ? ['Папка снова доступна — нажмите «Повторить», чтобы открыть ферму.', 'The folder is available again — press “Retry” to open the farm.']
            : ['Принтеры продолжают печатать то, что уже начали. Программа ничего не сохраняет и перезапустится сама, когда диск подключат.',
               'Printers keep printing what they have started. The app saves nothing and restarts by itself once the drive is connected.'];
        return ((ru ? why[0] : why[1]) + ' ' + (ru ? tail[0] : tail[1])).trim();
    });
    // Ход перезапуска — внутри красного окна: общее окно перезапуска лежит ниже него.
    const dduRestartText = computed(() => (restartPhase.value === 'idle' ? '' : restartMessage.value));
    const dduRetry = async () => { dduMsg.value = ''; await doRestart(); };
    const dduAdopt = async (path) => {
        if (dduBusy.value) return;
        dduBusy.value = true; dduMsg.value = '';
        try {
            const j = await (await fetch('/api/storage/data', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: String(path || '').trim(), adopt: true }) })).json();
            if (j && j.status === 'ok') { dduBusy.value = false; await doRestart(); return; }
            dduMsg.value = (j && (lang.value === 'ru' ? j.message : (j.message_en || j.message))) || _L('Не удалось выбрать папку', 'Could not choose the folder');
        } catch (e) { dduMsg.value = _L('Не удалось выбрать папку', 'Could not choose the folder'); }
        dduBusy.value = false;
    };
    const dduPickElsewhere = () => { dduMsg.value = ''; pickDirTarget.value = 'ddu'; return exOpenWith('pickdir', null, ''); };
    const dduStartNew = async () => {
        if (dduBusy.value) return;
        const w = dduWhere.value;
        const yes = await askConfirm({
            title: _L('Начать новую пустую ферму?', 'Start a new empty farm?'),
            text: _L('Программа откроет пустую ферму в папке по умолчанию. Данные' + (w ? ' в ' + w : ' фермы') + ' останутся нетронутыми: подключите диск позже и укажите эту папку снова, чтобы вернуться к ним.',
                     'The app opens an empty farm in the default folder. The data' + (w ? ' in ' + w : '') + ' stays untouched: connect the drive later and choose that folder again to get back to it.'),
            okText: _L('Начать новую ферму', 'Start a new farm') });   // не удаление: значок корзины ввёл бы в заблуждение
        if (!yes) return;
        dduBusy.value = true; dduMsg.value = '';
        try {
            const j = await (await fetch('/api/storage/data', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: '', abandon: true }) })).json();
            if (j && j.status === 'ok') { dduBusy.value = false; await doRestart(); return; }
            dduMsg.value = (j && (lang.value === 'ru' ? j.message : (j.message_en || j.message))) || _L('Не удалось', 'Failed');
        } catch (e) { dduMsg.value = _L('Не удалось', 'Failed'); }
        dduBusy.value = false;
    };
    // Новый процесс сервера (папка вернулась и программа перезапустилась сама) — перезагрузить страницу.
    let _dduPoll = null;
    watch(dataDirUnavailable, async (u) => {
        if (u && !_dduPoll) {
            if (!serverBootId.value) await fetchBootId();
            _dduPoll = setInterval(async () => {
                if (restartPhase.value !== 'idle') return;          // идёт свой перезапуск — он сам перезагрузит
                const probe = await restartProbe();
                if (probe.alive && probe.bootId && serverBootId.value && probe.bootId !== serverBootId.value) hardReloadOnce(probe.bootId);
                else if (probe.alive) loadStorageInfo();               // «папка вернулась» — показать «Повторить»
            }, 3000);
        } else if (!u && _dduPoll) { clearInterval(_dduPoll); _dduPoll = null; }
    });
    onMounted(() => { loadStorageInfo(); });
    // ── 16.10.2026 (R-151): настройки, которые живут только в этом окне браузера ────────────
    // Адреса IP-камер, темы оформления и профили этикеток модули держат в памяти браузера: при
    // смене порта или компьютера они пропадают. Здесь их можно сохранить в файл и загрузить обратно.
    // Переносятся только ключи этих модулей; запросы этикеток в ожидании — временные, не переносятся.
    const BROWSER_SETTINGS_PREFIXES = ['3diwell.camera_wall.', 'fm_appearance_', 'fm.inventory.labels.profile.'];
    const BROWSER_SETTINGS_FORMAT = '3diwell-browser-settings';
    const browserSettingsMsg = ref('');
    const _browserKeyOk = (k) => typeof k === 'string' && BROWSER_SETTINGS_PREFIXES.some(p => k.startsWith(p));
    const exportBrowserSettings = () => {
        const items = {};
        try {
            for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (_browserKeyOk(k)) items[k] = localStorage.getItem(k); }
        } catch (e) { browserSettingsMsg.value = _L('Браузер не даёт прочитать сохранённые настройки.', 'The browser blocks access to saved settings.'); return; }
        const n = Object.keys(items).length;
        if (!n) { browserSettingsMsg.value = _L('В этом окне нет сохранённых настроек модулей.', 'This window has no saved module settings.'); return; }
        try {
            const doc = { format: BROWSER_SETTINGS_FORMAT, version: 1, exported_at: new Date().toISOString(), items };
            const blob = new Blob([JSON.stringify(doc, null, 1)], { type: 'application/json;charset=utf-8' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'fm-browser-settings-' + new Date().toISOString().slice(0, 10) + '.json';
            document.body.appendChild(a); a.click(); a.remove();
            setTimeout(() => { try { URL.revokeObjectURL(a.href); } catch (e) {} }, 4000);
            browserSettingsMsg.value = _L('Сохранено настроек: ' + n + '.', 'Settings saved: ' + n + '.');
        } catch (e) { browserSettingsMsg.value = _L('Не удалось сохранить файл', 'Save failed'); }
    };
    const importBrowserSettings = () => {
        browserSettingsMsg.value = '';
        const inp = document.createElement('input');
        inp.type = 'file'; inp.accept = '.json,application/json';
        inp.onchange = async () => {
            const f = inp.files && inp.files[0];
            if (!f) return;
            const bad = _L('Это не файл настроек окна Farm Manager.', 'This is not a Farm Manager window settings file.');
            if (f.size > 16 * 1024 * 1024) { browserSettingsMsg.value = bad; return; }
            let doc = null;
            try { doc = JSON.parse(await f.text()); } catch (e) { browserSettingsMsg.value = bad; return; }
            if (!doc || doc.format !== BROWSER_SETTINGS_FORMAT || doc.version !== 1 || !doc.items || typeof doc.items !== 'object' || Array.isArray(doc.items)) { browserSettingsMsg.value = bad; return; }
            const keys = Object.keys(doc.items).filter(k => _browserKeyOk(k) && typeof doc.items[k] === 'string');
            let n = 0;
            try { keys.forEach(k => { localStorage.setItem(k, doc.items[k]); n++; }); }
            catch (e) { browserSettingsMsg.value = _L('Браузер не дал сохранить настройки (нет места или запрещено).', 'The browser refused to store the settings (no space or not allowed).'); return; }
            browserSettingsMsg.value = _L('Загружено настроек: ' + n + '. Откройте модуль заново или обновите страницу, чтобы он их подхватил.',
                                          'Settings loaded: ' + n + '. Reopen the module or reload the page to apply them.');
        };
        inp.click();
    };
    const showAbout = ref(false);
    const appVersion = ref('{{ VERSION }}');
    const openAbout = async () => {
        closeSettings(); showAbout.value = true;
        try { const r = await fetch('/version'); if (r.ok) { const v = (await r.json()).version; if (v) appVersion.value = v; } } catch (e) {}
    };
    const closeAbout = () => { showAbout.value = false; };
    const showChangelog = ref(false);
    const changelog = ref([]);
    const changelogLoaded = ref(false);
    try { changelog.value = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob('{{ CHANGELOG_B64 }}'), c => c.charCodeAt(0)))); changelogLoaded.value = true; } catch (e) {}
    const openChangelog = async () => {
        showChangelog.value = true;
        if (changelogLoaded.value) return;
        try { const r = await fetch('/api/changelog'); if (r.ok) { changelog.value = (await r.json()).items || []; changelogLoaded.value = true; } } catch (e) {}
    };
    const closeChangelog = () => { showChangelog.value = false; };

    // ---- Опциональный режим «Доступ и аудит»: вход / создание администратора / выход (бэкенд в server.py) ----
    const authEnabled = ref(false);
    const authUser = ref(null);
    const authChecked = ref(false);
    // R-128: защита включена, а администраторов нет, и программа открыта на этом компьютере —
    // окно входа предлагает создать администратора (признак даёт только сервер).
    const authSetupAvailable = ref(false);
    const loginUser = ref(''); const loginPass = ref(''); const loginError = ref(''); const loginBusy = ref(false);
    const showSecuritySetup = ref(false);
    const setupUser = ref(''); const setupPass = ref(''); const setupPass2 = ref(''); const setupError = ref('');
    const showSecurityDisable = ref(false);
    const disablePass = ref(''); const disableError = ref('');
    const roleLabel = (role) => {
        const ru = { admin: 'Администратор', operator: 'Оператор', assembler: 'Сборщик', observer: 'Наблюдатель' };
        const en = { admin: 'Administrator', operator: 'Operator', assembler: 'Assembler', observer: 'Observer' };
        return (lang.value === 'ru' ? ru : en)[role] || role;
    };
    const fetchAuthStatus = async () => {
        try { const r = await fetch('/api/auth/status'); if (r.ok) { const j = await r.json(); authEnabled.value = !!j.enabled; authUser.value = j.user || null; authSetupAvailable.value = !!(j.enabled && !j.authenticated && j.setup_available); } } catch (e) {}
        authChecked.value = true;
    };
    // Alpha 2.790: общий текст для ответа 429. Retry-After показываем округлённо, чтобы
    // пользователь понимал, что ждать, но без раскрытия внутренних счётчиков сервера.
    const rateLimitMsg = (r) => {
        const ra = parseInt((r && r.headers && r.headers.get('Retry-After')) || '0', 10);
        const mins = (ra > 0) ? Math.ceil(ra / 60) : 0;
        if (lang.value === 'ru') {
            return 'Слишком много неудачных попыток. Повторите позже' + (mins ? ' (примерно через ' + mins + ' мин)' : '') + '.';
        }
        return 'Too many failed attempts. Try again later' + (mins ? ' (about ' + mins + ' min)' : '') + '.';
    };
    const doLogin = async () => {
        loginError.value = ''; loginBusy.value = true;
        try {
            const r = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: loginUser.value, password: loginPass.value }) });
            if (r.ok) { location.reload(); return; }
            // Alpha 2.790: 429 — сервер ограничил повторные попытки. Сообщение общее: ни имени,
            // ни счётчиков, ни подсказки о существовании учётной записи.
            if (r.status === 429) { loginError.value = rateLimitMsg(r); }
            else { loginError.value = (lang.value === 'ru') ? 'Неверный логин или пароль' : 'Invalid username or password'; }
        } catch (e) { loginError.value = (lang.value === 'ru') ? 'Ошибка соединения' : 'Connection error'; }
        loginBusy.value = false;
    };
    const openSecuritySetup = () => { setupUser.value = ''; setupPass.value = ''; setupPass2.value = ''; setupError.value = ''; showSecuritySetup.value = true; };
    const doSecuritySetup = async () => {
        setupError.value = '';
        if (setupUser.value.trim().length < 3) { setupError.value = (lang.value === 'ru') ? 'Логин не короче 3 символов' : 'Username min 3 chars'; return; }
        if (setupPass.value.length < 6) { setupError.value = (lang.value === 'ru') ? 'Пароль не короче 6 символов' : 'Password min 6 chars'; return; }
        if (setupPass.value !== setupPass2.value) { setupError.value = (lang.value === 'ru') ? 'Пароли не совпадают' : 'Passwords do not match'; return; }
        try {
            const r = await fetch('/api/auth/setup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: setupUser.value.trim(), password: setupPass.value }) });
            if (r.ok) { location.reload(); return; }
            let j = {}; try { j = await r.json(); } catch (e2) {}
            if (r.status === 429) { setupError.value = rateLimitMsg(r); }
            else if (j.error === 'username_taken') { setupError.value = (lang.value === 'ru') ? 'Такой логин уже есть — выберите другой' : 'This username is taken — choose another'; }
            else if (j.error === 'already_enabled' && authEnabled.value) { setupError.value = (lang.value === 'ru') ? 'Администратор уже есть — войдите под ним' : 'An administrator already exists — sign in with it'; authSetupAvailable.value = false; }
            else { setupError.value = (lang.value === 'ru') ? 'Не удалось включить режим' : 'Could not enable'; }
        } catch (e) { setupError.value = (lang.value === 'ru') ? 'Ошибка соединения' : 'Connection error'; }
    };
    const doLogout = async () => { try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (e) {} location.reload(); };
    const openSecurityDisable = () => { disablePass.value = ''; disableError.value = ''; showSecurityDisable.value = true; };
    const doSecurityDisable = async () => {
        disableError.value = '';
        try {
            const r = await fetch('/api/auth/disable', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: disablePass.value }) });
            if (r.ok) { location.reload(); return; }
            disableError.value = (lang.value === 'ru') ? 'Неверный пароль' : 'Invalid password';
        } catch (e) { disableError.value = (lang.value === 'ru') ? 'Ошибка соединения' : 'Connection error'; }
    };
    // ---- Alpha 2.798: локальное одноразовое восстановление доступа администратора ----
    // Токен приходит ТОЛЬКО во фрагменте URL (#local-admin-recovery=...), поэтому на сервер как
    // часть запроса он не уходит. Он читается один раз, фрагмент немедленно стирается через
    // history.replaceState, а сам токен хранится ТОЛЬКО в этой замкнутой переменной — не в
    // localStorage, не в sessionStorage, не в cookie, не в DOM и не в консоли (в шаблон он тоже
    // не попадает, т.к. это не ref). После успеха/отмены переменная очищается. Префикс admRec*
    // отделяет это от recovery ОЧЕРЕДИ печати (recoveryNotice/recoveryBusy, Alpha 2.629) — иное имя.
    const ADM_REC_FRAGMENT_PREFIX = 'local-admin-recovery=';
    const ADM_REC_TOKEN_MAX = 256;
    let _admRecToken = '';
    const showAdminRecovery = ref(false);
    const admRecUser = ref(''); const admRecPass = ref(''); const admRecPass2 = ref('');
    const admRecError = ref(''); const admRecBusy = ref(false); const admRecDone = ref(false);
    const _clearAdmRecToken = () => { _admRecToken = ''; };
    const initAdminRecovery = () => {
        let h = '';
        try { h = String(location.hash || ''); } catch (e) { h = ''; }
        if (h.charAt(0) === '#') h = h.slice(1);
        if (h.indexOf(ADM_REC_FRAGMENT_PREFIX) !== 0) return;
        const tok = h.slice(ADM_REC_FRAGMENT_PREFIX.length);
        // Немедленно убрать фрагмент из адресной строки (в history не остаётся; на сервер не уходил).
        try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {}
        if (!tok || tok.length > ADM_REC_TOKEN_MAX) { _admRecToken = ''; return; }
        _admRecToken = tok;
        admRecUser.value = ''; admRecPass.value = ''; admRecPass2.value = '';
        admRecError.value = ''; admRecBusy.value = false; admRecDone.value = false;
        showAdminRecovery.value = true;
    };
    const cancelAdminRecovery = () => {
        _clearAdmRecToken();
        admRecUser.value = ''; admRecPass.value = ''; admRecPass2.value = '';
        admRecError.value = ''; admRecDone.value = false; showAdminRecovery.value = false;
    };
    const admRecFailMsg = () => (lang.value === 'ru')
        ? 'Не удалось восстановить доступ. Запустите восстановление ещё раз из меню Farm Manager.'
        : 'Recovery failed. Start recovery again from the Farm Manager menu.';
    const doAdminRecovery = async () => {
        if (admRecBusy.value) return;   // один submit -> один запрос: Enter не создаёт двойной вызов
        admRecError.value = '';
        if (admRecPass.value.length < 6) { admRecError.value = (lang.value === 'ru') ? 'Пароль не короче 6 символов' : 'Password min 6 chars'; return; }
        if (admRecPass.value !== admRecPass2.value) { admRecError.value = (lang.value === 'ru') ? 'Пароли не совпадают' : 'Passwords do not match'; return; }
        if (!_admRecToken) { admRecError.value = admRecFailMsg(); return; }
        admRecBusy.value = true;
        try {
            const r = await fetch('/api/auth/local-recovery/complete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ recovery_token: _admRecToken, username: admRecUser.value.trim(), new_password: admRecPass.value, confirm_password: admRecPass2.value }) });
            const j = await r.json().catch(() => ({}));
            if (r.ok && j.ok) {
                _clearAdmRecToken();
                admRecPass.value = ''; admRecPass2.value = '';
                admRecDone.value = true;
                try { await fetchAuthStatus(); } catch (e) {}
                return;
            }
            if (j.error === 'weak') { admRecError.value = (lang.value === 'ru') ? 'Пароль не короче 6 символов' : 'Password min 6 chars'; }
            else if (j.error === 'mismatch') { admRecError.value = (lang.value === 'ru') ? 'Пароли не совпадают' : 'Passwords do not match'; }
            else if (r.status === 429) { admRecError.value = rateLimitMsg(r); }
            else { admRecError.value = admRecFailMsg(); }
        } catch (e) { admRecError.value = (lang.value === 'ru') ? 'Ошибка соединения' : 'Connection error'; }
        admRecBusy.value = false;
    };
    // Успех: токен уже очищен; переходим на обычный экран входа (сессии администратора отозваны).
    const finishAdminRecovery = () => { admRecDone.value = false; showAdminRecovery.value = false; location.reload(); };
    const admRecDoneMsg = () => (lang.value === 'ru')
        ? 'Пароль администратора изменён. Войдите с новым паролем.'
        : 'Administrator password changed. Sign in with the new password.';
    // ---- Управление пользователями (экран для администратора) ----
    const authRoles = ['admin', 'operator', 'assembler', 'observer'];
    const showUsers = ref(false);
    const usersList = ref([]);
    const usersMe = ref('');
    const usersError = ref('');
    const newUserName = ref(''); const newUserPass = ref(''); const newUserRole = ref('operator');
    // 26.09.2026: запомненные устройства («Запомнить это устройство» в приложении Android).
    // Список приходит вместе с пользователями; «Отозвать» — PATCH пользователя с revoke_device.
    const devicesList = ref([]);
    const deviceBusy = ref(false);
    const fetchUsers = async () => {
        usersError.value = '';
        try {
            const r = await fetch('/api/auth/users');
            if (r.ok) { const j = await r.json(); usersList.value = j.users || []; usersMe.value = j.me || ''; devicesList.value = Array.isArray(j.devices) ? j.devices : []; }
            else { usersError.value = (lang.value === 'ru') ? 'Нет доступа' : 'No access'; }
        } catch (e) { usersError.value = (lang.value === 'ru') ? 'Ошибка соединения' : 'Connection error'; }
    };
    const openUsers = async () => { showUsers.value = true; newUserName.value = ''; newUserPass.value = ''; newUserRole.value = 'operator'; usersError.value = ''; await fetchUsers(); };
    const createUser = async () => {
        usersError.value = '';
        if (newUserName.value.trim().length < 3) { usersError.value = (lang.value === 'ru') ? 'Логин не короче 3 символов' : 'Username min 3 chars'; return; }
        if (newUserPass.value.length < 6) { usersError.value = (lang.value === 'ru') ? 'Пароль не короче 6 символов' : 'Password min 6 chars'; return; }
        try {
            const r = await fetch('/api/auth/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: newUserName.value.trim(), password: newUserPass.value, role: newUserRole.value }) });
            const j = await r.json().catch(() => ({}));
            if (r.ok && j.ok) { newUserName.value = ''; newUserPass.value = ''; newUserRole.value = 'operator'; await fetchUsers(); return; }
            const m = { exists: (lang.value === 'ru') ? 'Такой логин уже есть' : 'Username already exists', weak: (lang.value === 'ru') ? 'Логин ≥3, пароль ≥6' : 'Username ≥3, password ≥6', bad_role: (lang.value === 'ru') ? 'Неверная роль' : 'Bad role' };
            usersError.value = m[j.error] || ((lang.value === 'ru') ? 'Не удалось создать пользователя' : 'Could not create user');
        } catch (e) { usersError.value = (lang.value === 'ru') ? 'Ошибка соединения' : 'Connection error'; }
    };
    const _userPatch = async (u, body, lastAdminMsg) => {
        usersError.value = '';
        try {
            const r = await fetch('/api/auth/users/' + u.id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            const j = await r.json().catch(() => ({}));
            if (!(r.ok && j.ok)) { usersError.value = (j.error === 'last_admin') ? lastAdminMsg : ((lang.value === 'ru') ? 'Не удалось изменить' : 'Could not change'); }
        } catch (e) {}
        await fetchUsers();
    };
    const revokeDevice = async (d) => {
        if (deviceBusy.value || !d) return;
        deviceBusy.value = true; usersError.value = '';
        const ru = lang.value === 'ru';
        let msg = '';
        try {
            const r = await fetch('/api/auth/users/' + encodeURIComponent(d.user_id), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revoke_device: d.id }) });
            const j = await r.json().catch(() => ({}));
            if (!(r.ok && j.ok)) msg = ru ? 'Не удалось отозвать устройство' : 'Could not revoke the device';
            else if (d.current) { location.reload(); return; }   // отозвано это же устройство — его вход закончился
            //  Доступ закрыт сразу, но запись на диск не удалась: программа повторит её сама.
            else if (j.persisted === false) msg = ru ? 'Доступ закрыт. Запись на диск не удалась — программа повторит её сама через полминуты.' : 'Access is closed. Saving to disk failed; the app will retry in half a minute.';
        } catch (e) { msg = ru ? 'Ошибка соединения' : 'Connection error'; }
        finally { deviceBusy.value = false; }
        await fetchUsers();          // перечитывает список и сбрасывает сообщение — поэтому оно ставится после
        if (msg) usersError.value = msg;
    };
    const changeUserRole = (u, role) => _userPatch(u, { role }, (lang.value === 'ru') ? 'Нельзя снять роль последнего администратора' : 'Cannot remove the last administrator');
    const toggleUserActive = (u) => _userPatch(u, { is_active: u.is_active ? 0 : 1 }, (lang.value === 'ru') ? 'Нельзя отключить последнего администратора' : 'Cannot disable the last administrator');
    const deleteUser = async (u) => {
        usersError.value = '';
        try {
            const r = await fetch('/api/auth/users/' + u.id, { method: 'DELETE' });
            const j = await r.json().catch(() => ({}));
            if (!(r.ok && j.ok)) { usersError.value = (j.error === 'last_admin') ? ((lang.value === 'ru') ? 'Нельзя удалить последнего администратора' : 'Cannot delete the last administrator') : ((j.error === 'self') ? ((lang.value === 'ru') ? 'Нельзя удалить себя' : 'Cannot delete yourself') : ((lang.value === 'ru') ? 'Не удалось удалить' : 'Could not delete')); }
        } catch (e) {}
        await fetchUsers();
    };
    // ---- Просмотр журнала аудита (администратор) ----
    const showAudit = ref(false);
    const auditEntries = ref([]);
    const auditTotal = ref(0);
    const auditError = ref('');
    const auditBusy = ref(false);
    const auditLabel = (action) => {
        const ru = { 'login': 'Вход', 'logout': 'Выход', 'security.enable': 'Включение режима', 'security.local_admin_setup': 'Создание администратора на этом компьютере', 'security.disable': 'Выключение режима', 'user.create': 'Создание пользователя', 'user.update': 'Изменение пользователя', 'user.delete': 'Удаление пользователя' };
        const en = { 'login': 'Sign in', 'logout': 'Sign out', 'security.enable': 'Mode enabled', 'security.local_admin_setup': 'Administrator created on this computer', 'security.disable': 'Mode disabled', 'user.create': 'User created', 'user.update': 'User updated', 'user.delete': 'User deleted' };
        return (lang.value === 'ru' ? ru : en)[action] || action;
    };
    const fetchAudit = async (before) => {
        auditError.value = ''; auditBusy.value = true;
        try {
            const url = '/api/auth/audit?limit=200' + (before ? ('&before=' + before) : '');
            const r = await fetch(url);
            if (r.ok) { const j = await r.json(); auditTotal.value = j.total || 0; auditEntries.value = before ? auditEntries.value.concat(j.entries || []) : (j.entries || []); }
            else { auditError.value = (lang.value === 'ru') ? 'Нет доступа' : 'No access'; }
        } catch (e) { auditError.value = (lang.value === 'ru') ? 'Ошибка соединения' : 'Connection error'; }
        auditBusy.value = false;
    };
    const openAudit = async () => { showAudit.value = true; auditEntries.value = []; auditError.value = ''; await fetchAudit(); };
    const loadMoreAudit = async () => { const last = auditEntries.value[auditEntries.value.length - 1]; if (last) await fetchAudit(last.id); };
    const exportAudit = () => { window.open('/api/auth/audit/export', '_blank'); };
    // ---- Проверка прав в интерфейсе (зеркало серверной модели) ----
    const _rolePerms = { admin: ['view', 'operate', 'project', 'printer_write', 'printer_delete', 'count', 'rework', 'admin'], operator: ['view', 'operate', 'project', 'printer_write', 'count', 'rework'], assembler: ['view', 'rework'], observer: ['view'] };
    const can = (perm) => {
        if (!authEnabled.value) return true;
        if (!authUser.value) return false;
        return (_rolePerms[authUser.value.role] || []).includes(perm);
    };
    fetchAuthStatus();
    initAdminRecovery();   // Alpha 2.798: если в URL есть recovery-фрагмент — считать токен, стереть фрагмент, открыть диалог
    // ---- Alpha 2.793: единый capability contract окон модулей ----
    // Ядро — ЕДИНСТВЕННЫЙ источник решения can(). Контракт своей таблицы прав НЕ имеет и не
    // может иметь: он делегирует тому же can() выше, которым пользуется основной интерфейс.
    // Модулю НЕ передаются токен сессии, cookie, пароль/хеш, запись пользователя и НАЗВАНИЕ РОЛИ —
    // модуль спрашивает право, а не «кто ты». Словарь имён совпадает с правами маршрутов модулей
    // (app/route_policy_registry.py); printer_delete в него намеренно не входит — ни один маршрут
    // модуля его не проверяет, а лишнее имя в контракте расширяло бы поверхность без нужды.
    const MODULE_CAPABILITIES = Object.freeze(['view', 'project', 'operate', 'printer_write', 'count', 'rework', 'admin']);
    const MODULE_ACCESS_CONTRACT_VERSION = 1;
    const accessRevision = ref(0);
    // Строгая нормализация: разрешено ТОЛЬКО точное имя из словаря. Неизвестное имя, пустая строка,
    // не-строка, префикс и подстрока -> false ВСЕГДА, в том числе при выключенной авторизации:
    // иначе owner-режим стал бы fail-open для любой выдуманной модулем строки.
    const moduleCan = (cap) => ((typeof cap === 'string' && MODULE_CAPABILITIES.indexOf(cap) >= 0) ? !!can(cap) : false);
    // Переоценка прав по ответу 403/401 от модуля. Модуль НЕ меняет состояние доступа — он лишь
    // просит ядро перечитать правду с сервера (тот же fetchAuthStatus, что и при загрузке).
    // Дебаунс 3 с + флаг «уже идёт» — шквала запросов при серии отказов не будет.
    let _accessRevalidateAt = 0;
    let _accessRevalidating = false;
    const revalidateAccess = async () => {
        const now = Date.now();
        if (_accessRevalidating || (now - _accessRevalidateAt) < 3000) return;
        _accessRevalidating = true; _accessRevalidateAt = now;
        try { await fetchAuthStatus(); accessRevision.value++; } catch (e) {} finally { _accessRevalidating = false; }
    };
    // Реактивность: computed зависит от authEnabled/authUser (через can) и от accessRevision,
    // поэтому вход, выход, смена прав и переоценка по 403 отдают НОВЫЙ замороженный объект —
    // уже открытое окно модуля получает обновлённый prop без перезапуска программы.
    const moduleAccess = computed(() => {
        const rev = accessRevision.value;
        const caps = MODULE_CAPABILITIES.filter((c) => moduleCan(c));
        return Object.freeze({
            contractVersion: MODULE_ACCESS_CONTRACT_VERSION,
            authEnabled: !!authEnabled.value,
            capabilities: Object.freeze(caps),
            revision: rev,
            can: moduleCan,
            revalidate: revalidateAccess,
        });
    });
    // Реестр модулей-плагинов (задел). Меню «Модули» строится из этого списка.
    // Дескриптор: { id, en, ru, icon, status:'planned'|'active'(+run) }. Добавить плагин = запись со status:'active' + действие в runModule.
    //  3.0: список пуст — задуманные, но не сделанные модули («AI-агент», «Подключение к CRM»)
    //  пользователю не показываются: в выпуске нет ничего про планы разработки.
    const appModules = ref([]);
    const runModule = (m) => { /* встроенных активных модулей больше нет: реальные модули — плагины, их запускает runInstalledModule */ };
    // --- Установленные модули-плагины (из /api/modules) + установка из .zip ---
    const { printerBadges, startPrinterBadges } = usePrinterBadges();   // бейджи модулей на карточках принтеров (блок-файл)
    // Привязанный филамент из складского модуля (read-only) — блок «Филамент» в расширенной карточке.
    const { printerFilament, startPrinterFilament } = usePrinterFilament();
    const filamentForPrinter = (p) => {
        const pid = (p && typeof p === 'object') ? p.id : p;
        return printerFilament.value[pid] || null;
    };
    // Alpha 2.736: БЕЗОПАСНАЯ нормализация HEX для круглого маркера цвета катушки в секции «Филамент».
    // color_hex из generic snapshot (_inv_spool_brief) приходит без «#» → сырой в CSS невалиден и круг пустой.
    // Принимает #RGB/RGB/#RRGGBB/RRGGBB/#RRGGBBAA/RRGGBBAA; короткий разворачивает, alpha отбрасывает; итог —
    // '#RRGGBB' upper. Пусто/служебное/CSS/URL/';'/любой не-hex → null (нейтральный fallback в шаблоне; сырой
    // текст в style не вставляем). Только generic-поля snapshot; ядро НЕ импортирует Inventory и его БД.
    const safeHex = (v) => {
        if (v == null) return null;
        let s = String(v).trim();
        if (s[0] === '#') s = s.slice(1);
        if (s.length === 3) s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2];
        else if (s.length === 8) s = s.slice(0, 6);
        return /^[0-9a-fA-F]{6}$/.test(s) ? ('#' + s.toUpperCase()) : null;
    };
    // Значок «привязана складская катушка» на карточке принтера (компактная сетка И список).
    // Alpha 2.755 — БАГ «значок периодически пропадает» решён раз и навсегда: раньше значок зависел
    // ТОЛЬКО от явных полей строки inventory_bound/source, которые появились лишь в свежих версиях
    // модуля склада (1.7.21+). Со старой установленной версией (напр. 1.7.20) провайдер отдаёт ту же
    // привязанную катушку, но БЕЗ этих полей — и значок гас, хотя катушка привязана и секция
    // «Филамент» показывалась. Теперь признак не привязан к версии модуля: помимо явных полей
    // принимаем сам факт, что строка пришла ЧЕРЕЗ generic-агрегатор модулей — ядро штампует
    // fil.module_id на КАЖДУЮ запись независимо от версии модуля, и тот же module_id использует клик
    // по значку (openFilamentSource). Так значок горит и со старым складом, и с новым.
    // Сырые строки без module_id (пришли НЕ от модуля) значок по-прежнему не включают.
    // Модуль не установлен/принтера нет в снапшоте -> false (fail-open). Несколько катушек = ОДИН значок.
    const printerStockBound = (p) => {
        const pid = (p && typeof p === 'object') ? p.id : p;
        const fil = printerFilament.value[pid];
        if (!fil || !Array.isArray(fil.slots)) return false;
        return fil.slots.some(s => s && s.spool && (s.inventory_bound === true || s.source === 'inventory' || !!fil.module_id));
    };
    const filamentRows = (p) => {
        const pid = (p && typeof p === 'object') ? p.id : p;
        const fil = printerFilament.value[pid];
        if (!fil || !Array.isArray(fil.slots)) return [];
        // Подпись AMS-юнита — из amsGroups (единый источник: unit>=128 → «AMS HT», обычные → «AMS 1/2/…»),
        // чтобы карточка и живой ряд не расходились. Привязанная HT-катушка офлайн-принтера (её нет в живом
        // ряду) всё равно подписывается «AMS HT», а НЕ «Слот 513».
        const unitLbl = {};
        for (const g of (amsGroups(p) || [])) unitLbl[g.unit] = g.label;
        const gU = (lang.value === 'ru' ? 'г' : 'g');
        return fil.slots.filter(s => s && s.spool).map((s, i) => {
            const sp = s.spool;
            let label;
            //  16.10.2026 (R-137): у H2D две внешние катушки; склад помечает сторону (ext_side), иначе
            //  обе строки назывались бы одинаково «Внешняя катушка».
            if (s.external && s.ext_side === 'left') label = (lang.value === 'ru' ? 'Внешняя левая' : 'External left');
            else if (s.external && s.ext_side === 'right') label = (lang.value === 'ru' ? 'Внешняя правая' : 'External right');
            else if (s.external) label = (lang.value === 'ru' ? 'Внешняя катушка' : 'External spool');
            else if (s.unit != null && unitLbl[s.unit] && s.tray != null) label = unitLbl[s.unit] + '·' + (s.tray + 1);
            else if (amsIsHt(s.unit) && s.tray != null) label = 'AMS HT·' + (s.tray + 1);
            else label = (lang.value === 'ru' ? 'Слот ' : 'Slot ') + ((s.index != null ? s.index : 0) + 1);
            const parts = [];
            if (sp.vendor_name) parts.push(sp.vendor_name);
            if (sp.material) parts.push(sp.material);
            if (sp.color_name) parts.push(sp.color_name);
            const rem = Math.max(0, Math.round(sp.weight_remaining_g || 0));
            const tot = Math.round(sp.weight_total_g || 0);
            const pct = tot > 0 ? Math.max(0, Math.min(100, Math.round((rem / tot) * 100))) : null;
            return {
                key: 'fil' + i,
                hex: safeHex(sp.color_hex) || '',
                label: label,
                text: parts.join(' · '),
                rem: (pct != null ? (rem + ' ' + gU + ' · ' + pct + '%') : (rem + ' ' + gU)),
                low: (pct != null && pct <= 15),
            };
        });
    };
    // ══════════════════════════════════════════════════════════════════════════

    //  ── 2.965: экран «Филамент» и предупреждение «скоро кончится» (R-047, R-018) ────────
    //  Одна таблица на всю ферму: принтер — слот — материал — цвет — остаток. Новых обращений
    //  к принтерам нет: слоты берутся из той же телеметрии, что рисует карточки (ams_trays /
    //  cfs_trays), а граммы — из того же снимка склада (/api/printer-filament), что и значок
    //  катушки. Экран НИЧЕГО не меняет: ни печати, ни склада, ни привязок.
    //
    //  Порог «скоро кончится» — общий для всей фермы (настройка farm_low_pct, 2.927): с какого
    //  компьютера ни посмотри, красным подсвечено одно и то же.
    const ui3FilLowPct = ref(15);
    const _ui3FilLowSet = (v, push) => {
        let n = parseInt(v, 10);
        if (!(n >= 1)) n = 15;
        n = Math.max(1, Math.min(90, n));
        ui3FilLowPct.value = n;
        if (push) _farmSettingsPush();
    };
    const setUi3FilLowPct = (v) => _ui3FilLowSet(v, true);
    //  2.974: поле порога правится, а не перерисовывается под руками. Раньше оно было привязано
    //  односторонне (:value), и любая перерисовка страницы — а она идёт каждую секунду от
    //  телеметрии — возвращала в поле прежнее число прямо во время набора. Пара get/set с
    //  ленивым v-model решает это по-честному: пока поле в работе, страница его не трогает,
    //  а по завершении правки число проверяется теми же границами, что и раньше.
    const ui3FilLowInput = computed({
        get: () => ui3FilLowPct.value,
        set: (v) => _ui3FilLowSet(v, true),
    });
    //  Слоты одного принтера: сперва то, что принтер сам сообщает о своих слотах, затем к каждому
    //  слоту подставляется привязанная катушка склада — по НОМЕРУ слота, а не по подписи: подписи
    //  у AMS и CFS строятся по-разному и совпадать не обязаны.
    const _ui3FilSlots = (p) => {
        const pid = p.id;
        const st = (wsData.value && wsData.value[pid]) || {};
        const fil = printerFilament.value[pid] || {};
        const bound = {};
        let ext = null, extL = null;
        for (const s of (fil.slots || [])) {
            if (!s) continue;
            //  16.10.2026 (R-137): левая внешняя катушка H2D (склад: ext_side 'left') — своя строка.
            //  Раньше вторая внешняя строка затирала первую, и левая катушка пропадала из таблицы.
            if (s.external && s.ext_side === 'left') { extL = s; continue; }
            if (s.external) { ext = s; continue; }
            if (s.index != null) bound[String(s.index)] = s;
        }
        const ru = lang.value === 'ru';
        const rows = [];
        const _push = (key, label, tray, slot) => {
            const sp = (slot && slot.spool) || null;
            const type = (tray && tray.type && tray.type !== 'Empty') ? String(tray.type) : '';
            const material = type || (sp && sp.material) || '';
            const rem = sp ? Math.max(0, Math.round(sp.weight_remaining_g || 0)) : null;
            const tot = sp ? Math.round(sp.weight_total_g || 0) : 0;
            const pct = (rem != null && tot > 0) ? Math.max(0, Math.min(100, Math.round((rem / tot) * 100))) : null;
            rows.push({
                key: pid + ':' + key,
                label: label,
                material: material,
                colorName: (sp && sp.color_name) || '',
                vendor: (sp && sp.vendor_name) || '',
                hex: (sp && safeHex(sp.color_hex)) || (tray && tray.color) || '',
                empty: !material,
                bound: !!sp,
                offline: !!(slot && slot.offline),
                rem: rem, pct: pct,
                low: (pct != null && pct <= ui3FilLowPct.value),
                //  2.974: ключ катушки НЕ зависит от того, каким путём слот попал в таблицу.
                //  Раньше в него входил ключ строки (c0 / a0 / b0), а он меняется: сразу после
                //  перезагрузки телеметрии ещё нет, и слот приходит из склада как «b0», а через
                //  секунду тот же слот приходит от принтера как «c0». Ключ менялся — и
                //  предупреждение о конце материала выдавалось на ту же катушку второй раз.
                spoolKey: sp ? (pid + '/' + (sp.id != null ? 'id' + sp.id
                                : 'm' + (sp.material || '') + '|' + (sp.color_name || ''))) : '',
            });
        };
        if (p.type === 'bambu') {
            for (const g of (amsGroups(p) || [])) {
                for (const t of (g.slots || [])) {
                    const n = (t.tray == null ? t.index : t.tray) + 1;
                    _push('a' + t.index, g.label + '·' + n, t, bound[String(t.index)]);
                }
            }
        } else {
            (st.cfs_trays || []).forEach((t, i) => {
                const idx = (t.index == null ? i : t.index);
                _push('c' + idx, 'CFS ' + (idx + 1), t, bound[String(idx)]);
            });
        }
        //  Подписи короткие, как у ячейки склада «Лев. внеш.»: колонка слота на узком экране — 80 px.
        if (extL) _push('extl', ru ? 'Лев. внеш.' : 'Left ext.', null, extL);
        if (ext) _push('ext', (ext.ext_side === 'right') ? (ru ? 'Прав. внеш.' : 'Right ext.') : (ru ? 'Внешняя' : 'External'), null, ext);
        //  Катушка склада, привязанная к слоту, которого сейчас не видно (принтер офлайн):
        //  показать её всё равно — иначе остаток пропадёт из таблицы вместе с принтером.
        for (const k of Object.keys(bound)) {
            if (rows.some(r => r.key === pid + ':a' + k || r.key === pid + ':c' + k)) continue;
            _push('b' + k, (ru ? 'Слот ' : 'Slot ') + (Number(k) + 1), null, bound[k]);
        }
        return rows;
    };
    const ui3FilRows = computed(() => (printers.value || [])
        .filter(p => p && !p.__demo)
        .map(p => ({
            pid: p.id,
            name: p.name,
            model: p.model || '',
            status: String(((wsData.value && wsData.value[p.id]) || {}).status || 'OFFLINE').toUpperCase(),
            slots: _ui3FilSlots(p),
        }))
        .filter(r => r.slots.length));
    const ui3FilTotals = computed(() => {
        let slots = 0, low = 0, empty = 0, grams = 0, known = 0;
        for (const pr of ui3FilRows.value) for (const s of pr.slots) {
            slots += 1;
            if (s.empty) empty += 1;
            if (s.low) low += 1;
            if (s.rem != null) { grams += s.rem; known += 1; }
        }
        return { printers: ui3FilRows.value.length, slots, low, empty, grams, known };
    });
    //  Предупреждение о конце материала. Сообщение уходит в «Подсказки» ОДИН раз на катушку:
    //  повторять его каждые десять секунд опроса — значит приучить не читать подсказки вовсе.
    //  Катушка снова поднялась выше порога (заменили, долили) — метка снимается, и следующее
    //  падение снова будет замечено.
    const _ui3FilWarned = new Set();
    const _ui3FilCheckLow = () => {
        if (!ui3Mode) return;
        const ru = lang.value === 'ru';
        const seen = new Set();
        for (const pr of ui3FilRows.value) {
            for (const s of pr.slots) {
                if (!s.bound || s.pct == null) continue;
                seen.add(s.spoolKey);
                if (!s.low) { _ui3FilWarned.delete(s.spoolKey); continue; }
                if (_ui3FilWarned.has(s.spoolKey)) continue;
                _ui3FilWarned.add(s.spoolKey);
                pushToast((ru ? 'Скоро кончится: ' : 'Running low: ')
                    + pr.name + ' · ' + s.label + ' · ' + (s.material || (ru ? 'материал' : 'material'))
                    + ' — ' + s.rem + (ru ? ' г' : ' g') + ' (' + s.pct + ' %)', 'warn');
            }
        }
        for (const k of Array.from(_ui3FilWarned)) if (!seen.has(k)) _ui3FilWarned.delete(k);
    };
    // БЛОК: активные предупреждения принтеров (Alpha 2.731). State-driven, ТОЛЬКО чтение.
    // НЕ Suggestions, НЕ toast; без localStorage/config/БД; без команд принтеру. Источник —
    // телеметрия wsData (error_code/hms_codes/mc_err/status/err_msg/seen_ago). После перезагрузки
    // восстанавливается из телеметрии. OFFLINE/stale НЕ создаёт alert, а ЗАМОРАЖИВАЕТ уже активный
    // (telemetry_fresh=false), не помечая решённым. resolve — только по положительному доказательству.
    // ══════════════════════════════════════════════════════════════════════════
    // Проверенная НА ЖЕЛЕЗЕ таблица кодов Bambu (RU/EN). Расшифровки без подтверждённого источника
    // НЕ добавлять. 07FF-8011 (print_error) и 12FF-8011 (HMS) — ОДИН и тот же сбой → одна запись.
    const KNOWN_BAMBU_CODES = {
        '07FF-8011': { severity: 'warning', category: 'filament',
            ru: { title: 'Закончился филамент в AMS', message: 'Установите новую катушку в тот же AMS-слот и нажмите «Повторить» на принтере.' },
            en: { title: 'AMS filament runout', message: 'Load a new spool into the same AMS slot and press “Retry” on the printer.' } },
        '07FF-8007': { severity: 'warning', category: 'filament',
            ru: { title: 'Проверьте подачу филамента', message: 'Проверьте сопло. Если филамент выходит — нажмите «Готово»; иначе слегка подайте его и нажмите «Повторить».' },
            en: { title: 'Check filament feeding', message: 'Check the nozzle. If filament is extruding, press “Done”; otherwise extrude a little and press “Retry”.' } },
    };
    KNOWN_BAMBU_CODES['12FF-8011'] = KNOWN_BAMBU_CODES['07FF-8011'];   // HMS-вариант того же сбоя
    KNOWN_BAMBU_CODES['12FF-8007'] = KNOWN_BAMBU_CODES['07FF-8007'];
    // ═══════════════════════════════════════════════════════════════════════════════════
    //  2.992: УВЕДОМЛЕНИЯ ПРИНТЕРА (HMS) — то, что всплывает на его экране.
    //  Просьба владельца 10.09.2026: сообщения принтера должны быть видны в программе, а на
    //  свёрнутой ячейке — значок, что уведомление есть. Сервер отдаёт разобранные записи:
    //  печатный код (как на экране), важность и узел. Текста в них нет: его рисует прошивка
    //  из своей таблицы, по сети приходят только числа.
    //  ПРАВИЛО ТАБЛИЦЫ ТО ЖЕ, ЧТО У KNOWN_BAMBU_CODES: расшифровку без подтверждённого
    //  источника НЕ добавлять. Неизвестный код показываем кодом, узлом и важностью — это
    //  честнее выдуманного текста и всё равно говорит оператору, куда идти.
    const KNOWN_HMS_TEXT = {
        //  Источник: wiki.bambulab.com, страница кода 0C00-0100-0001-0004 «Micro Lidar Lens dirty».
        //  Снято с экрана владельца 10.09.2026.
        '0C00-0100-0001-0004': {
            ru: 'Загрязнилась линза микро-лидара — протрите её',
            en: 'Micro Lidar lens is dirty — clean the lens' },
        //  Источник: wiki.bambulab.com, код 0700-2000-0003-0002: штатная подмена катушки AMS.
        //  Снято с экрана владельца 10.09.2026.
        '0700-2000-0003-0002': {
            ru: 'Филамент в слоте AMS закончился — принтер сам перешёл на такой же',
            en: 'AMS slot ran out of filament — the printer switched to an identical spool' },
    };
    const _HMS_SEV_RANK = { fatal: 4, serious: 3, common: 2, info: 1, unknown: 0 };
    const hmsFor = (pid) => {
        const id = (pid && typeof pid === 'object') ? pid.id : pid;
        const list = (wsData.value[id] || {}).hms;
        return Array.isArray(list) ? list : [];
    };
    const hmsCount = (pid) => hmsFor(pid).length;
    const hmsTopSeverity = (pid) => {
        let top = 'unknown', r = -1;
        hmsFor(pid).forEach(h => { const rr = _HMS_SEV_RANK[h && h.severity] || 0; if (rr > r) { r = rr; top = (h && h.severity) || 'unknown'; } });
        return top;
    };
    const hmsSevText = (sev) => {
        const ru = lang.value === 'ru';
        return ({ fatal: ru ? 'критично' : 'fatal', serious: ru ? 'серьёзно' : 'serious',
                  common: ru ? 'обычное' : 'common', info: ru ? 'к сведению' : 'info' })[sev]
               || (ru ? 'важность неизвестна' : 'unknown severity');
    };
    const hmsModuleText = (mod) => {
        const ru = lang.value === 'ru';
        return ({ mc: ru ? 'плата движения' : 'motion board', mainboard: ru ? 'материнская плата' : 'mainboard',
                  ams: ru ? 'AMS' : 'AMS', toolhead: ru ? 'печатающая голова' : 'toolhead',
                  xcam: ru ? 'камера и лидар' : 'camera and lidar', amsht: 'AMS-HT',
                  firmware: ru ? 'прошивка' : 'firmware', printer: ru ? 'принтер' : 'printer' })[mod]
               || (ru ? 'узел неизвестен' : 'unknown module');
    };
    //  Текст уведомления, если он известен программе; иначе пусто — окно покажет код и узел.
    //  15.09.2026: текст приходит с сервера в самой записи (h.text — из официальной таблицы Bambu или
    //  слово в слово от прошивки Klipper); встроенная таблица — запасной вариант.
    const hmsText = (h) => {
        const L = lang.value === 'ru' ? 'ru' : 'en';
        const st = h && h.text;
        if (st && typeof st === 'object' && (st[L] || st.en || st.ru)) return st[L] || st.en || st.ru;
        const t = KNOWN_HMS_TEXT[(h && h.code) || ''];
        return t ? (lang.value === 'ru' ? t.ru : t.en) : '';
    };
    //  Подпись для значка на свёрнутой ячейке: одной строкой, без переносов.
    const hmsTip = (pid) => {
        const ru = lang.value === 'ru';
        const list = hmsFor(pid);
        if (!list.length) return '';
        const head = ru ? ('Уведомления принтера: ' + list.length) : ('Printer notifications: ' + list.length);
        return head + '\n' + list.map(h => (hmsText(h) || h.code) + ' · ' + hmsSevText(h.severity)).join('\n');
    };
    const _ALERT_SEV_RANK = { critical: 4, error: 3, warning: 2, info: 1 };
    const _ALERT_STALE_S = 60;   // seen_ago >= порога (или OFFLINE) → телеметрия НЕ свежа
    // ── Alpha 2.818: КЛАССИФИКАЦИЯ ОТМЕНЫ ПЕРЕЕХАЛА В БЭКЕНД (app/printer_health_policy.py). ──────────
    // Раньше здесь был хардкод-список кодов отмены Bambu (_BAMBU_CANCEL_CODES: 0300-400C/0002-0070) —
    // каждый новый код прошивки (0300-000A на H2D) заново показывался как «Ошибка принтера». Теперь бэкенд
    // КОНТЕКСТНО (адаптер + активная сессия/переход + признак семейства отмены + отсутствие реального сбоя)
    // отдаёт готовое поле s.device_error (код неисправности или null). Фронтенд его только ПОКАЗЫВАЕТ, своего
    // whitelist кодов не держит. Сырой error_code/hms_codes/mc_err остаётся в p_states для диагностики.

    const printerAlerts = ref({});   // "pid|source" -> alert (in-memory, неперсистентно)
    const _alertPending = {};        // "pid|source" -> { code, count } антидребезг (2 подряд свежих кадра)
    let _alertSeq = 0;
    const _alertNow = () => Date.now();
    // Свежесть телеметрии для целей alert: не OFFLINE и seen_ago < порога (для «залипшего» подключённого принтера).
    const _alertFresh = (s) => !!s && s.status !== 'OFFLINE' && !(typeof s.seen_ago === 'number' && s.seen_ago >= _ALERT_STALE_S);
    // Сырая проблема принтера: null (нет), {stale:true} (нет свежих данных → заморозка), либо объект проблемы.
    // Ручная PAUSE без активного кода → null (alert не создаём). Дедуп print_error+mc+hms в один код — здесь.
    //  15.09.2026: текст ошибки печати Bambu из официальной таблицы (сервер кладёт его рядом с кодом).
    const _devErrText = (s, L) => { const t = s && s.device_error_text; return (t && typeof t === 'object' && (t[L] || t.en || t.ru)) || ''; };
    const _printerProblem = (pid, s) => {
        if (!s) return null;                        // принтер отсутствует в снимке (удалён / сервер только стартовал) → не проблема
        if (!_alertFresh(s)) return { stale: true };   // присутствует, но OFFLINE / устаревшая телеметрия → заморозка активного
        const type = (((printers.value || []).find(p => p.id === pid) || {}).type || '').toLowerCase();
        const st = s.status, L = (lang.value === 'ru') ? 'ru' : 'en';
        if (type === 'bambu') {
            if (st === 'RUNNING' || st === 'FINISH') return null;   // возобновилось/завершилось → снято
            const code = s.device_error || null;                    // Alpha 2.818: health-канал уже классифицирован бэкендом (отмена отфильтрована по контексту, реальный код сохранён)
            if (!code) return null;                                 // нет кода / ручная пауза / штатная отмена → alert не создаём
            const k = KNOWN_BAMBU_CODES[code];
            return { source: 'bambu', code, severity: k ? k.severity : 'error', category: k ? k.category : 'printer_error',
                title: k ? k[L].title : (L === 'ru' ? 'Ошибка принтера' : 'Printer error'),
                message: k ? k[L].message : (_devErrText(s, L) ? (_devErrText(s, L) + ' [' + code + ']') : ((L === 'ru' ? 'Код: ' : 'Code: ') + code)) };
        }
        if (type === 'creality') {
            //  12.10.2026: Creality на заводской прошивке — тот же health-канал (s.device_error); текст —
            //  код с экрана принтера, если прошивка его дала.
            if (!s.device_error) return null;
            const msg = (s.err_msg || '').trim() || (L === 'ru' ? 'Принтер сообщил о сбое печати. Проверьте принтер.' : 'The printer reported a print failure. Check the printer.');
            return { source: 'creality', code: (s.err_code || 'FAILED'), severity: 'error', category: 'printer_error',
                title: (L === 'ru' ? 'Ошибка печати' : 'Print error'), message: msg };
        }
        if (type === 'klipper') {
            // Alpha 2.826: health-канал классифицирован БЭКЕНДОМ (s.device_error) — как у Bambu.
            // Отмена (print_stats 'cancelled') отделена от сбоя: device_error=None → alert не создаём.
            // err_msg остаётся человекочитаемым текстом; при сбое device_error непуст.
            if (!s.device_error) return null;                       // отмена / печать / пауза → нет alert
            const msg = (s.err_msg || '').trim() || String(s.device_error);
            return { source: 'klipper', code: (msg.slice(0, 80) || 'error'), severity: 'error', category: 'printer_error',
                title: (L === 'ru' ? 'Ошибка Klipper' : 'Klipper error'), message: msg };
        }
        if (type === 'flashforge') {
            // Alpha 2.826: раньше фронтенд сам считал status==='FAILED' сбоем, и ШТАТНАЯ остановка
            // (raw 'cancel'/'cancelled', сваленный бэкендом в FAILED) показывалась как «Ошибка печати».
            // Теперь единственный источник — s.device_error: бэкенд отделил исход задания (cancelled)
            // от здоровья устройства и маскирует липкий FAILED. Отмена → device_error=None → нет alert;
            // настоящий сбой ('error') → device_error='FAILED' → карточка красная как прежде.
            if (!s.device_error) return null;
            return { source: 'flashforge', code: 'FAILED', severity: 'error', category: 'printer_error',
                title: (L === 'ru' ? 'Ошибка печати' : 'Print error'),
                message: (L === 'ru' ? 'Принтер сообщил о сбое печати. Проверьте принтер.' : 'The printer reported a print failure. Check the printer.')
                    + (s.err_code ? ((L === 'ru' ? ' Код на экране: ' : ' Code on screen: ') + s.err_code) : '') };
        }
        return null;
    };
    const _mkAlert = (pid, prob) => ({ printer_id: pid, alert_id: 'al' + (++_alertSeq), source: prob.source, code: prob.code,
        severity: prob.severity, category: prob.category, title: prob.title, message: prob.message,
        active_since: _alertNow(), last_seen: _alertNow(), telemetry_fresh: true });
    // Пересчёт по свежему снимку wsData. Дедуп по printer_id+source; новый код того же source ЗАМЕНЯЕТ прежний;
    // resolve только по положительному доказательству; OFFLINE/stale — заморозка; антидребезг — 2 свежих кадра.
    const _reconcileAlerts = () => {
        if (tourActive.value) return;   // во время тура телеметрия фейковая — alert'ы не трогаем
        const wd = wsData.value || {};
        const cur = printerAlerts.value || {};
        const next = Object.assign({}, cur);
        const pids = new Set(Object.keys(wd));
        Object.keys(cur).forEach(k => pids.add(k.split('|')[0]));
        pids.forEach(pid => {
            const prob = _printerProblem(pid, wd[pid]);
            const keysHere = Object.keys(next).filter(k => k.indexOf(pid + '|') === 0);
            const clearPending = () => Object.keys(_alertPending).forEach(k => { if (k.indexOf(pid + '|') === 0) delete _alertPending[k]; });
            if (prob && prob.stale) { keysHere.forEach(k => { next[k] = Object.assign({}, next[k], { telemetry_fresh: false }); }); clearPending(); return; }
            if (!prob) { keysHere.forEach(k => { delete next[k]; }); clearPending(); return; }
            const key = pid + '|' + prob.source, ex = next[key];
            if (ex) {
                if (ex.code === prob.code) next[key] = Object.assign({}, ex, { last_seen: _alertNow(), telemetry_fresh: true, severity: prob.severity, category: prob.category, title: prob.title, message: prob.message });
                else next[key] = _mkAlert(pid, prob);   // код сменился → заменить событие
                delete _alertPending[key];
            } else {
                const pnd = _alertPending[key];
                if (pnd && pnd.code === prob.code) { pnd.count += 1; if (pnd.count >= 2) { next[key] = _mkAlert(pid, prob); delete _alertPending[key]; } }
                else _alertPending[key] = { code: prob.code, count: 1 };
            }
        });
        printerAlerts.value = next;
    };
    watch(wsData, _reconcileAlerts, { deep: false });
    const _allAlerts = computed(() => Object.keys(printerAlerts.value).map(k => printerAlerts.value[k]));
    const _sortAlerts = (arr) => arr.slice().sort((a, b) => (_ALERT_SEV_RANK[b.severity] || 0) - (_ALERT_SEV_RANK[a.severity] || 0) || (a.active_since - b.active_since));
    const alertsForPrinter = (p) => { const pid = (p && typeof p === 'object') ? p.id : p; return _sortAlerts(_allAlerts.value.filter(a => a.printer_id === pid)); };
    const cardTopAlert = (p) => { const arr = alertsForPrinter(p); return arr.length ? { top: arr[0], more: arr.length - 1 } : null; };
    const alertBadgeCount = computed(() => { const s = new Set(); _allAlerts.value.forEach(a => s.add(a.printer_id)); return s.size; });
    const alertTopSeverity = computed(() => { let top = 'info', r = 0; _allAlerts.value.forEach(a => { const rr = _ALERT_SEV_RANK[a.severity] || 0; if (rr > r) { r = rr; top = a.severity; } }); return top; });
    const alertPanelRows = computed(() => _sortAlerts(_allAlerts.value).map(a => Object.assign({}, a, { printer_name: _printerNameOf(a.printer_id) })));
    const alertTimeLabel = (ts) => { try { return new Date(ts).toLocaleTimeString(lang.value === 'ru' ? 'ru-RU' : 'en-US', { hour: '2-digit', minute: '2-digit' }); } catch (e) { return ''; } };
    const alertsPanelOpen = ref(false);
    const toggleAlertsPanel = () => { alertsPanelOpen.value = !alertsPanelOpen.value; };
    const closeAlertsPanel = () => { if (alertsPanelOpen.value) alertsPanelOpen.value = false; };
    const focusPrinterCard = (pid) => {
        closeAlertsPanel();
        try { if (isMobile.value) mobileTab.value = 'printers'; } catch (e) {}
        nextTick(() => {
            try {
                const el = document.querySelector('.printer-card[data-pid="' + pid + '"]') || document.querySelector('[data-pid="' + pid + '"]');
                if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.classList.add('fm-alert-flash'); setTimeout(() => { try { el.classList.remove('fm-alert-flash'); } catch (e) {} }, 1600); }
            } catch (e) {}
        });
    };

    const installedModules = ref([]);
    const moduleRestartNeeded = ref(false);   // программа требует перезапуск после действий с модулями
    // Alpha 2.808: состояние ЗАГРУЗКИ списка модулей — отдельно от самого списка. Раньше любая
    // неудача запроса молча оставляла пустой массив, и «не удалось получить список» выглядело
    // ровно как «модулей нет». Это разные вещи, и пользователю нужно видеть разницу.
    const modulesLoadState = ref('loading');   // loading | ready | unauthorized | unavailable
    const loadInstalledModules = async () => {
        try {
            const r = await fetch('/api/modules');
            if (r.status === 401 || r.status === 403) { modulesLoadState.value = 'unauthorized'; return; }
            if (!r.ok) { modulesLoadState.value = 'unavailable'; return; }
            const d = await r.json();
            if (!d || !Array.isArray(d.modules)) { modulesLoadState.value = 'unavailable'; return; }
            installedModules.value = d.modules;
            moduleRestartNeeded.value = !!d.restart_needed;
            modulesLoadState.value = 'ready';
        } catch (e) { modulesLoadState.value = 'unavailable'; }
    };
    // Модуль пригоден к работе только в состоянии loaded. Состояние приходит с backend; старый
    // ответ без поля state считаем loaded — иначе обновление ядра скрыло бы рабочие модули.
    const moduleIsLoaded = (m) => !m.disabled && (!m.state || m.state === 'loaded');
    // Найден на диске, но не работает: установлен, но требует внимания. Такой модуль ОБЯЗАН быть
    // виден в настройках — иначе его нечем обновить.
    const problemModules = computed(() => installedModules.value.filter(
        (m) => m.state && m.state !== 'loaded' && m.state !== 'disabled'));
    const moduleStateText = (m) => {
        const s = m && m.state;
        const ru = lang.value === 'ru';
        if (s === 'version_mismatch') return ru ? 'Требуется обновление' : 'Update required';
        if (s === 'pending_restart') return ru ? 'Установлен, нужен перезапуск' : 'Installed, restart needed';
        if (s === 'route_mismatch') return ru ? 'Несовместим с этой версией программы' : 'Incompatible with this app version';
        if (s === 'invalid_manifest') return ru ? 'Повреждён файл модуля' : 'Module file is damaged';
        //  16.10.2026 (R-151): модуль не уложился в срок запуска — программа поднялась без него.
        if (s === 'load_error' && m.reason === 'timeout') return ru ? 'Не ответил при запуске' : 'No answer at start';
        if (s === 'load_error') return ru ? 'Не удалось запустить' : 'Failed to start';
        //  26.09.2026: подписанный пакет не прошёл проверку — код не запускается, данные целы.
        if (s === 'integrity_failed') return ru ? 'Пакет повреждён' : 'Package damaged';   // переустановите модуль
        if (s === 'package_untrusted') return ru ? 'Подпись неизвестна' : 'Unknown signature';   // ключ поставщика не знаком этой программе
        return ru ? 'Не загружен' : 'Not loaded';
    };
    // 16.10.2026 (R-151): подробность для всплывающей подсказки у состояния модуля.
    const moduleStateTitle = (m) => {
        if (!(m && m.state === 'load_error' && m.reason === 'timeout')) return '';
        return lang.value === 'ru'
            ? 'Модуль не ответил за 30 с при запуске и не подключён; перезапустите программу, при повторе обновите или отключите модуль'
            : 'The module did not answer within 30 s at start and is not connected; restart the app, and if it happens again, update or disable the module';
    };
    // Подсказка с версиями: только цифры из манифеста и карты прав, без путей и подробностей.
    const moduleVersionHint = (m) => {
        if (!m) return '';
        const ru = lang.value === 'ru';
        const inst = m.installed_version || m.version || '';
        const exp = m.expected_version || '';
        //  23.09.2026: с картой прав ядра сверяется КОНТРАКТ модуля (core_contract), а не номер выпуска.
        //  Объявлен контракт отдельно — сравниваем его: иначе «установлено 1.7.30, требуется 1.7.29»
        //  выглядело бы как отказ по номеру выпуска, который больше ничего не решает.
        const con = m.installed_contract || '';
        if (con && exp && con !== exp && con !== inst) return (ru ? 'контракт ' : 'contract ') + con + (ru ? ', требуется ' : ', required ') + exp;
        if (inst && exp && inst !== exp) return (ru ? 'установлено ' : 'installed ') + inst + (ru ? ', требуется ' : ', required ') + exp;
        return inst ? 'v' + inst : '';
    };
    onMounted(async () => { await loadInstalledModules(); await loadModuleComponents(); await loadModuleSettingsComponents(); });
    // ── Alpha 2.781: ключ интеграции со слайсером ─────────────────────────────
    // Ключ живёт в reactive state ТОЛЬКО между «Создать» и закрытием блока: в
    // localStorage/sessionStorage не кладём, в DOM-атрибуты и подсказки не пишем, в тост и
    // в журнал не выводим. Сервер отдаёт значение единственный раз — повторно узнать его
    // нельзя, поэтому «Закрыть» стирает его безвозвратно.
    const sliCb = ref({ configured: false, enabled: true, created_at: '', header: 'X-Api-Key' });
    const sliCbToken = ref('');
    const sliCbBusy = ref(false);
    const sliCbLoad = async () => {
        try { const r = await fetch('/api/slicer-callback/status'); if (r.ok) sliCb.value = await r.json(); } catch (e) {}
    };
    const sliCbGenerate = async () => {
        if (sliCbBusy.value) return;
        sliCbBusy.value = true;
        try {
            const r = await fetch('/api/slicer-callback/generate', { method: 'POST' });
            const j = await r.json();
            if (j && j.token) sliCbToken.value = j.token;
            await sliCbLoad();
        } catch (e) {} finally { sliCbBusy.value = false; }
    };
    const sliCbRevoke = async () => {
        if (sliCbBusy.value) return;
        sliCbBusy.value = true;
        try { await fetch('/api/slicer-callback/revoke', { method: 'POST' }); sliCbToken.value = ''; await sliCbLoad(); }
        catch (e) {} finally { sliCbBusy.value = false; }
    };
    const sliCbCopy = () => { try { navigator.clipboard.writeText(sliCbToken.value); } catch (e) {} };
    const sliCbHide = () => { sliCbToken.value = ''; };
    onMounted(() => { sliCbLoad(); });
    const moduleInstalling = ref(false);
    const moduleBusy = ref(false);   // busy-lock действий с модулем (удалить/отключить/включить): один запрос за раз, без двойных кликов
    const moduleInstallMsg = ref(null);
    const pickModuleZip = () => exOpenWith('modzip', null);   // выбор .zip модуля через НАШ Проводник
    const exInstallModule = async () => {
        const it = exSelItem.value;
        if (!it || it.is_dir || (it.ext || '').toLowerCase() !== '.zip') return;
        const path = it.path;   // фиксируем до закрытия окна
        exOpen.value = false;
        moduleInstalling.value = true; moduleInstallMsg.value = null;
        try {
            const _post = async (extra) => {
                const r = await fetch('/api/modules/install-path', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({ path }, extra || {})) });
                return r.json().catch(() => ({}));
            };
            let j = await _post();
            //  16.10.2026 (R-150): установлен модуль, подписанный поставщиком, а новый файл без подписи
            //  или подписан другим ключом — сервер ничего не меняет и спрашивает. Заменяем только после
            //  явного «Заменить»; отказ оставляет прежний модуль как был.
            if (j.status === 'confirm_required' && j.reason === 'signed_replaced') {
                const _nm = '«' + (j.name || j.id || '') + '»' + (j.installed_version ? ' v' + j.installed_version : '');
                const _nv = j.version ? ' v' + j.version : '';
                const yes = await askConfirm({
                    title: _L('Заменить подписанный модуль?', 'Replace a signed module?'),
                    text: _L('Сейчас установлен ' + _nm + ', подписанный поставщиком. Новый файл' + _nv + (j.new_signed ? ' подписан другим ключом — убедитесь, что он получен от поставщика модуля.' : ' без подписи: платные функции в нём работать не будут.') + ' Вернуть подписанную версию можно, установив её файл заново.',
                             'Installed now: ' + _nm + ', signed by the vendor. The new file' + _nv + (j.new_signed ? ' is signed with a different key — make sure it comes from the module vendor.' : ' is not signed: its paid features will not work.') + ' To return the signed version, install its file again.'),
                    okText: _L('Заменить', 'Replace'), danger: true });
                j = yes ? await _post({ confirm_provenance: true }) : { status: 'cancelled' };
            }
            if (j.status === 'cancelled') {
                moduleInstallMsg.value = { ok: false, text: _L('Установка отменена: прежний модуль на месте.', 'Install cancelled: the previous module is kept.') };
            } else if (j.status === 'ok') {
                //  26.09.2026: версия не проверяется — ставится любая. Поставили старее прежней или
                //  программа знает выпуск новее — говорим об этом, но установку не отменяем.
                const _ru = lang.value === 'ru';
                const _warn = (j.older_than_replaced && j.replaced_version ? (_ru ? ' Установлена версия старее прежней (была v' + j.replaced_version + ').' : ' This version is older than the previous one (was v' + j.replaced_version + ').') : '')
                    //  10.10.2026: «Оформление» старее прежней может не увидеть темы, сохранённые новой версией
                    //  (у них новее номер схемы). Версии до 0.17.5 сами об этом не говорят — говорим при установке.
                    //  newer_version — и когда модуль перед этим удалили: тогда «прежней» версии у сервера нет.
                    + (j.id === 'appearance' && (j.older_than_replaced || j.newer_version) ? (_ru ? ' Темы, сохранённые новой версией, старая может не показать — они не удалены и вернутся после установки новой версии.' : ' The older version may not show themes saved by the newer one — they are not deleted and will return once the newer version is installed again.') : '')
                    + (j.newer_version ?(_ru ? ' Есть более новая версия: v' + j.newer_version + '.' : ' A newer version exists: v' + j.newer_version + '.') : '');
                moduleInstallMsg.value = { ok: true, text: (_ru ? 'Модуль установлен: ' : 'Module installed: ') + (j.name || j.id || '') + (j.version ? ' v' + j.version : '') + (_ru ? ' — перезапустите программу.' : ' — restart the app.') + _warn };
            } else {
                const reasons = { 'not a zip': lang.value==='ru'?'это не .zip-архив':'not a .zip', 'no module.json': lang.value==='ru'?'в архиве нет module.json':'no module.json in archive', 'bad manifest': lang.value==='ru'?'повреждён module.json':'bad module.json', 'bad module id': lang.value==='ru'?'некорректный id модуля':'bad module id', 'extract failed': lang.value==='ru'?'не удалось распаковать':'extract failed', 'read failed': lang.value==='ru'?'не удалось прочитать файл':'read failed', 'unpack failed': lang.value==='ru'?'не удалось распаковать — прежняя версия модуля осталась на месте':'could not unpack — the previous module version is kept', 'bad archive': lang.value==='ru'?'в архиве недопустимые имена файлов':'the archive has invalid file names', 'swap_failed': lang.value==='ru'?'не удалось заменить файлы модуля — прежняя версия вернётся на место при следующем запуске программы':'could not replace the module files — the previous version will be restored on the next start', 'package_integrity': lang.value==='ru'?'пакет повреждён или изменён — файлы не совпадают с подписью. Прежняя версия модуля осталась на месте':'the package is damaged or modified — files do not match the signature. The previous module version is kept', 'package_untrusted': lang.value==='ru'?'пакет подписан ключом, которого эта программа не знает':'the package is signed with a key this app does not know', 'update_not_covered': lang.value==='ru'?'эта версия вышла после окончания оплаченных обновлений. Работает прежняя версия; для новой нужно продление лицензии':'this version was released after your paid updates ended. The previous version keeps working; renew the license to get this one' };
                moduleInstallMsg.value = { ok: false, text: (lang.value === 'ru' ? 'Не удалось установить: ' : 'Install failed: ') + (reasons[j.reason] || j.reason || '\u2014') };
            }
        } catch (e) { moduleInstallMsg.value = { ok: false, text: lang.value === 'ru' ? 'Ошибка сети' : 'Network error' }; }
        moduleInstalling.value = false;
        await loadInstalledModules();
        await licLoad();   // 26.09.2026: статус платных модулей после установки
    };
    // ── 26.09.2026: лицензии платных модулей (Настройки → Модули → «Лицензии модулей»). Полностью
    //    офлайн: файл лицензии .fmlic переносится на этот компьютер любым способом. Ядро проверяет
    //    подпись и хранит файл как есть; платный модуль перепроверяет исходный документ сам.
    const licInfo = ref({ licenses: [], modules: [], install_id: '', test_keys: false, activation_request: null,
                          machine: '', consent: false, terms_url: '', privacy_url: '', service: { configured: false, url: '' }, mark_requests: [],
                          transmitted: { requests: [], answers: {} } });
    const licBusy = ref(false);
    const licMsg = ref(null);
    //  10.10.2026, вариант 3: ключ текстом и согласие на передачу номера лицензии и номера компьютера.
    const licKey = ref('');
    const licConsent = ref(false);
    let _licRelayBusy = false;
    const licLoad = async (relay = true) => {
        if (!can('admin')) return;   // список лицензий — только администратору (как установка модулей)
        try {
            //  ?relay=1 — программа отдаёт отметки, которые пора отправить, только если страница их понесёт.
            const r = await fetch('/api/licenses' + (relay ? '?relay=1' : ''));
            if (!r.ok) return;
            const j = await r.json();
            //  Неполный ответ (старая программа, сбой) — пустые списки, а не ошибка в шаблоне.
            if (j && j.status === 'ok') licInfo.value = {
                licenses: Array.isArray(j.licenses) ? j.licenses : [], modules: Array.isArray(j.modules) ? j.modules : [],
                install_id: String(j.install_id || ''), test_keys: !!j.test_keys,
                activation_request: (j.activation_request && typeof j.activation_request === 'object') ? j.activation_request : null,
                machine: String(j.machine || ''), consent: !!j.consent,
                terms_url: String(j.terms_url || ''), privacy_url: String(j.privacy_url || ''),
                service: (j.service && typeof j.service === 'object') ? { configured: !!j.service.configured, url: String(j.service.url || '') } : { configured: false, url: '' },
                mark_requests: Array.isArray(j.mark_requests) ? j.mark_requests : [],
                transmitted: (j.transmitted && typeof j.transmitted === 'object') ? j.transmitted : { requests: [], answers: {} } };
        } catch (e) {}
        if (relay) licRelay();
    };
    //  Отметка через браузер: у компьютера фермы может не быть интернета, а у телефона или офисного
    //  компьютера, открывшего программу, он есть. Страница относит отметку службе лицензий и
    //  возвращает её подписанный ответ программе. Нет связи — сообщения нет (лицензии работают).
    //  11.10.2026: программа отдаёт только отметки, которые пора отправить. Отказ службы и просьба
    //  подождать (429/503, Retry-After) возвращаются программе — она не повторит отметку раньше срока.
    //  17.10.2026: «нет связи» тоже возвращается программе (relay_status=network) — повтор через 15 минут.
    const licRelayNote = async (req, status, retryAfter) => {
        try {
            const fd = new FormData();
            fd.append('relay_license_id', String(req.license_id || ''));
            fd.append('relay_status', String(status));
            if (retryAfter) fd.append('relay_retry_after', String(retryAfter));
            await fetch('/api/licenses/import', { method: 'POST', body: fd });
        } catch (e) {}
    };
    //  17.10.2026 (приёмка H09): итог отметки через этот браузер — одним сообщением. На телефоне вкладки
    //  «Модули» нет, а отметка уходит сразу при открытии главной страницы: без сообщения владелец узнавал
    //  результат только позже, на компьютере. На телефоне сообщение встаёт в угол экрана, на компьютере —
    //  в панель «Подсказки». Нет связи со службой или служба просит подождать (429/503) — молчим, как
    //  прежде: лицензии от этого не меняются, программа попробует сама.
    //    answers  — ответы службы, которые программа приняла ({ service_state, service_reason });
    //    refused  — коды HTTP, которыми служба отказала;
    //    rejected — сколько ответов пришло, но программа их не приняла.
    const licRelayToast = (answers, refused, rejected) => {
        const ru = lang.value === 'ru';
        if (answers.length) {
            //  Несколько лицензий — одно сообщение: показываем худшее состояние (аннулирована > остановлена > работает).
            const rank = (s) => (s === 'ok' ? 0 : (s === 'revoked' ? 2 : 1));
            let worst = answers[0];
            for (const a of answers) if (rank(a.service_state) > rank(worst.service_state)) worst = a;
            const n = answers.length;
            const r0 = rank(worst.service_state);
            const cnt = answers.filter((a) => rank(a.service_state) === r0).length;
            const of = (n > 1 && r0 > 0) ? (ru ? ' (' + cnt + ' из ' + n + ')' : ' (' + cnt + ' of ' + n + ')') : '';
            const head = (ru ? 'Лицензии модулей' : 'Module licenses') + (n > 1 ? ' (' + n + ')' : '')
                + (ru ? ': служба лицензий ответила через этот браузер — ' : ': the license service answered via this browser — ');
            //  «Работает» держится 15 с, а не обычные 3: сообщение приходит само, сразу после открытия
            //  страницы, — за 3 секунды его легко не заметить. Остановка — предупреждение (обычный срок).
            if (r0 === 0) pushToast(head + (ru ? 'работает (' : 'OK (') + _msgTime() + ')', 'success', 15000);
            else if (r0 === 2) pushToast(head + (ru ? 'АННУЛИРОВАНА' : 'REVOKED') + of + (ru ? ' — платные функции закрыты' : ' — paid features are closed'), 'warn');
            else pushToast(head + (ru ? 'ОСТАНОВЛЕНА' : 'STOPPED') + of + ': ' + licStopWhy(worst.service_reason), 'warn');
        }
        if (refused.length || rejected) {
            const parts = [];
            if (refused.length) parts.push((ru ? 'служба лицензий отказала (HTTP\u00a0' : 'the license service refused (HTTP\u00a0')
                + refused.filter((c, i) => refused.indexOf(c) === i).join(', ') + ')');
            if (rejected) parts.push(ru ? 'ответ службы лицензий не принят' : 'the license service answer was not accepted');
            //  Права от отказа не меняются (их меняет только подписанный ответ службы) — говорим об этом,
            //  чтобы сообщение не пугало. Висит минуту: программа сама попробует снова.
            pushToast((ru ? 'Лицензии модулей: ' : 'Module licenses: ') + parts.join('; ')
                + (ru ? ' — лицензии работают как прежде, программа попробует ещё раз позже.' : ' — licenses work as before, the app will try again later.'),
                'warn', 60000);
        }
    };
    const licRelay = async () => {
        const L = licInfo.value || {};
        if (_licRelayBusy || !L.service || !L.service.configured || !L.service.url || !(L.mark_requests || []).length) return;
        _licRelayBusy = true;
        let got = 0;
        const answers = [], refused = [];
        let rejected = 0;
        try {
            for (const req of L.mark_requests) {
                try {
                    let r;
                    const ac = (typeof AbortController === 'function') ? new AbortController() : null;
                    const timer = ac ? setTimeout(() => ac.abort(), 20000) : null;   // служба молчит — не ждём дольше 20 с
                    try {
                        r = await fetch(L.service.url, { method: 'POST', mode: 'cors', credentials: 'omit', referrerPolicy: 'no-referrer',
                            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({}, req, { via: 'browser' })),
                            signal: ac ? ac.signal : undefined });
                    } catch (e) {
                        //  17.10.2026: у этого устройства тоже нет связи со службой, она молчит 20 с или браузер
                        //  не показал ответ (ответ службы без заголовков CORS) — сообщаем программе «нет связи»:
                        //  следующая попытка не раньше чем через 15 минут, как и напрямую. Остальные не пробуем.
                        await licRelayNote(req, 'network');
                        break;
                    }
                    finally { if (timer) clearTimeout(timer); }
                    if (!r.ok) {
                        //  Retry-After виден странице, только если служба открыла его браузеру
                        //  (Access-Control-Expose-Headers: Retry-After); не виден — программа ждёт 15 / 5 минут.
                        await licRelayNote(req, r.status, r.headers.get('Retry-After'));
                        if (r.status === 429 || r.status === 503) break;
                        refused.push(r.status);
                        continue;
                    }
                    const txt = await r.text();
                    const fd = new FormData();
                    fd.append('text', txt);
                    const a = await fetch('/api/licenses/import', { method: 'POST', body: fd });
                    const aj = await a.json().catch(() => ({}));
                    if (aj.status === 'ok') { got++; if (aj.kind === 'verdict') answers.push(aj); }
                    else { rejected++; await licRelayNote(req, 'rejected'); }   // ответ не принят — следующая попытка через 6 часов
                } catch (e) {}
            }
        } finally { _licRelayBusy = false; }
        if (got) { await licLoad(false); await loadInstalledModules(); }
        try { licRelayToast(answers, refused, rejected); } catch (e) {}   // сообщение не важнее самой отметки
    };
    const licDate = (s) => (s ? String(s).slice(0, 10).split('-').reverse().join('.') : '');
    const licCodeText = (code) => {
        const ru = lang.value === 'ru';
        const t = {
            bad_signature: ru ? 'подпись не сходится — файл изменён или подделан' : 'signature mismatch — the file was changed or forged',
            unknown_key: ru ? 'выдана ключом, которого эта программа не знает' : 'issued with a key this app does not know',
            wrong_format: ru ? 'это не файл лицензии FM' : 'this is not an FM license file',
            malformed: ru ? 'файл повреждён' : 'the file is damaged',
            wrong_product: ru ? 'лицензия другого продукта' : 'a license for another product',
            missing_field: ru ? 'в файле не хватает сведений' : 'the file lacks required data',
            consent_required: ru ? 'нужно согласие на передачу номера лицензии и номера компьютера' : 'consent to send the license and computer numbers is required',
            verdict_foreign: ru ? 'ответ службы лицензий для другого компьютера' : 'the license service answer is for another computer',
            verdict_stale: ru ? 'устаревший ответ службы лицензий' : 'an outdated license service answer',
            verdict_unknown_license: ru ? 'ответ службы по лицензии, которой здесь нет' : 'an answer for a license that is not here',
            verdict_future: ru ? 'дата ответа службы лицензий позже часов этого компьютера — проверьте дату и время' : 'the license service answer is dated later than this computer clock — check the date and time',
            unknown_field: ru ? 'в файле незнакомые поля' : 'the file has unknown fields',
            bad_value: ru ? 'в файле неверные значения' : 'the file has invalid values',
            crypto_unavailable: ru ? 'в программе нет модуля проверки подписи' : 'the signature check module is missing',
            license_rejected: ru ? 'файл не принят' : 'the file was not accepted',
            'write failed': ru ? 'не удалось сохранить файл' : 'could not save the file',
            'read failed': ru ? 'не удалось прочитать файл' : 'could not read the file',
        };
        return t[code] || code || '\u2014';
    };
    const licLine = (l) => {
        const ru = lang.value === 'ru';
        if (!l || !l.ok) return (ru ? 'не действует: ' : 'not valid: ') + licCodeText(l && l.code);
        const mods = (l.grants || []).map((g) => g.module_id + (g.edition ? ' (' + g.edition + ')' : '')).join(', ');
        const use = l.use_type === 'term'
            ? (ru ? 'пользование до ' : 'use until ') + licDate(l.use_valid_until)
            : (ru ? 'бессрочно' : 'perpetual');
        const upd = (ru ? 'обновления до ' : 'updates until ') + licDate(l.updates_before);
        const bind = l.bound ? (l.bound_here ? (ru ? ' · для этой установки' : ' · for this installation') : (ru ? ' · для ДРУГОЙ установки' : ' · for ANOTHER installation')) : '';
        return mods + ' · ' + use + ' · ' + upd + bind + licServiceText(l);
    };
    //  10.10.2026: что ответила служба лицензий для ЭТОГО компьютера.
    const licServiceText = (l) => {
        const ru = lang.value === 'ru';
        //  11.10.2026: «работает» тоже видно — с временем последнего ответа (иначе не понять, дошла ли отметка).
        if (l && l.service_state === 'ok' && l.last_answer_at) {
            const d = new Date(l.last_answer_at);
            const p2 = (n) => String(n).padStart(2, '0');
            const t = isNaN(d) ? licDate(l.last_answer_at) : p2(d.getDate()) + '.' + p2(d.getMonth() + 1) + '.' + d.getFullYear() + ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes());
            return (ru ? ' · служба лицензий: работает (' : ' · license service: OK (') + t + ')';
        }
        if (!l || l.service_state === 'ok' || !l.service_state) return '';
        if (l.service_state === 'revoked') return ru ? ' · АННУЛИРОВАНА — платные функции закрыты' : ' · REVOKED — paid features are closed';
        return (ru ? ' · ОСТАНОВЛЕНА: ' : ' · STOPPED: ') + licStopWhy(l.service_reason);
    };
    //  Почему служба остановила ключ — те же слова в строке лицензии и в сообщении об отметке
    //  через браузер (17.10.2026). Незнакомая причина — общие слова, а не код службы.
    const licStopWhy = (reason) => {
        const ru = lang.value === 'ru';
        const why = {
            seat_taken: ru ? 'ключ уже работает на другом компьютере — подтвердите перенос в личном кабинете на сайте 3diwell.com' : 'the key already works on another computer — confirm the move in your account on 3diwell.com',
            moved: ru ? 'лицензия перенесена на другой компьютер' : 'the license was moved to another computer',
            blocked: ru ? 'владелец лицензии не подтвердил этот компьютер' : 'the license owner did not confirm this computer',
        };
        return (Object.prototype.hasOwnProperty.call(why, reason) ? why[reason] : '') || (ru ? 'служба лицензий остановила ключ на этом компьютере' : 'the license service stopped the key on this computer');
    };
    //  proof — доказательство владения ключом (свёртка подписи ключа). Уходит службе целиком, но на
    //  экране — только начало: экран снимают на телефон и пересылают, а proof — секрет владельца ключа.
    const licSentText = computed(() => {
        const t = licInfo.value && licInfo.value.transmitted;
        const reqs = (t && Array.isArray(t.requests)) ? t.requests : [];
        return reqs.length ? JSON.stringify(reqs.map((r) => Object.assign({}, r, (r && typeof r.proof === 'string') ? { proof: r.proof.slice(0, 8) + '\u2026' } : {})), null, 1) : '';
    });
    const licSentNote = computed(() => {
        const L = licInfo.value || {};
        const ru = lang.value === 'ru';
        if (!L.consent) return ru ? 'Пока вы не дали согласие при вводе ключа, программа ничего не передаёт.' : 'Until you give consent when adding a key, the app sends nothing.';
        if (!L.service || !L.service.configured) return ru ? 'Адрес службы лицензий ещё не задан: программа ничего не передаёт. Когда он появится, будет уходить ровно это:' : 'The license service address is not set yet, so the app sends nothing. Once it is set, exactly this will be sent:';
        return ru ? 'Когда у компьютера фермы есть интернет — или администратор открыл программу с устройства, у которого он есть, — службе лицензий уходит ровно это, без имён, принтеров и данных фермы. Через браузер служба видит ещё адрес, по которому открыта программа: так устроены браузеры. Доказательство владения ключом (proof) здесь показано не целиком; случайное число (nonce) в каждой отправке новое.' : 'When the farm computer is online, or an administrator opened the app from a device that is online, exactly this goes to the license service, with no names, printers or farm data. Through a browser the service also sees the address the app was opened at: that is how browsers work. The proof of key ownership (proof) is shown only in part here; every send carries a new random number (nonce).';
    });
    //  Короткая пометка в строке модуля. Модуль без подписи (все прежние и сторонние) — без пометки:
    //  для него ничего не изменилось.
    const licNote = (m) => {
        const L = (m && m.licensing) || {};
        const ru = lang.value === 'ru';
        if (!L.state || L.state === 'unsigned') return '';
        if (L.license === 'not_required') return ru ? 'подписан' : 'signed';
        if (L.license === 'active') return ru ? 'лицензия действует' : 'license active';
        if (L.license === 'missing') return ru ? 'платные функции — по лицензии' : 'paid features need a license';
        if (L.license === 'update_not_covered') return ru ? 'выпуск вне оплаченных обновлений' : 'release outside paid updates';
        if (L.license === 'use_expired') return ru ? 'срок лицензии истёк' : 'license expired';
        if (L.license === 'binding_mismatch') return ru ? 'лицензия другой установки' : 'license for another installation';
        if (L.license === 'license_stopped') return ru ? 'остановлена: ключ на другом компьютере' : 'stopped: the key is on another computer';
        if (L.license === 'license_revoked') return ru ? 'лицензия аннулирована' : 'license revoked';
        return ru ? 'лицензия не подходит' : 'license does not fit';
    };
    const licModuleText = (m) => {
        const ru = lang.value === 'ru';
        const n = licNote({ licensing: m });
        const upd = m && m.updates_before ? ((ru ? ', обновления до ' : ', updates until ') + licDate(m.updates_before)) : '';
        return (ru ? (m.ru || m.module_id) : (m.en || m.module_id)) + (m.version ? ' v' + m.version : '') + ' — ' + n + (m.license === 'active' ? upd : '');
    };
    const importLicense = async (ev) => {
        const f = ev && ev.target && ev.target.files && ev.target.files[0];
        if (ev && ev.target) ev.target.value = '';
        if (!f || licBusy.value) return;
        licBusy.value = true; licMsg.value = null;
        const ru = lang.value === 'ru';
        try {
            const fd = new FormData();
            fd.append('file', f);
            if (licConsent.value || licInfo.value.consent) fd.append('consent', '1');
            const r = await fetch('/api/licenses/import', { method: 'POST', body: fd });
            const j = await r.json().catch(() => ({}));
            if (j.status === 'ok') {
                licMsg.value = { ok: true, text: (ru ? 'Лицензия добавлена: ' : 'License added: ') + (j.license_id || '') + ((j.modules || []).length ? ' (' + j.modules.join(', ') + ')' : '') + (ru ? '. Платные функции доступны сразу.' : '. Paid features are available right away.') };
            } else {
                licMsg.value = { ok: false, text: (ru ? 'Лицензия не принята: ' : 'License not accepted: ') + licCodeText(j.code || j.reason) };
            }
        } catch (e) { licMsg.value = { ok: false, text: ru ? 'Ошибка соединения' : 'Connection error' }; }
        finally { licBusy.value = false; }
        await licLoad();
        await loadInstalledModules();
    };
    //  10.10.2026: ключ текстом («FMK1.…» из письма или личного кабинета).
    const addLicenseKey = async () => {
        const key = (licKey.value || '').trim();
        if (!key || licBusy.value) return;
        licBusy.value = true; licMsg.value = null;
        const ru = lang.value === 'ru';
        try {
            const fd = new FormData();
            fd.append('text', key);
            if (licConsent.value || licInfo.value.consent) fd.append('consent', '1');
            const r = await fetch('/api/licenses/import', { method: 'POST', body: fd });
            const j = await r.json().catch(() => ({}));
            if (j.status === 'ok' && j.kind !== 'verdict') {
                licKey.value = '';
                licMsg.value = { ok: true, text: (ru ? 'Ключ принят: ' : 'Key accepted: ') + (j.license_id || '') + ((j.modules || []).length ? ' (' + j.modules.join(', ') + ')' : '') + (ru ? '. Платные функции доступны сразу.' : '. Paid features are available right away.') };
            } else if (j.status === 'ok') {
                licMsg.value = { ok: true, text: ru ? 'Ответ службы лицензий принят.' : 'The license service answer is accepted.' };
            } else {
                licMsg.value = { ok: false, text: (ru ? 'Ключ не принят: ' : 'Key not accepted: ') + licCodeText(j.code || j.reason) };
            }
        } catch (e) { licMsg.value = { ok: false, text: ru ? 'Ошибка соединения' : 'Connection error' }; }
        finally { licBusy.value = false; }
        await licLoad();
        await loadInstalledModules();
    };
    const removeLicense = async (l) => {
        if (licBusy.value || !l || !l.license_id) return;
        if (!await askConfirm({ title: _L('Удалить лицензию?', 'Remove the license?'),
            text: _L('Платные функции модулей по этой лицензии закроются сразу. Данные модулей и программы не удаляются. Вернуть лицензию можно тем же файлом.',
                     'Paid features covered by this license close right away. Module and program data are not deleted. You can bring the license back with the same file.'),
            okText: _L('Удалить', 'Remove') })) return;
        licBusy.value = true; licMsg.value = null;
        try {
            const r = await fetch('/api/licenses/' + encodeURIComponent(l.license_id), { method: 'DELETE' });
            const j = await r.json().catch(() => ({}));
            licMsg.value = j.status === 'ok' ? { ok: true, text: _L('Лицензия удалена.', 'License removed.') } : { ok: false, text: _L('Не удалось удалить лицензию.', 'Could not remove the license.') };
        } catch (e) { licMsg.value = { ok: false, text: _L('Ошибка соединения', 'Connection error') }; }
        finally { licBusy.value = false; }
        await licLoad();
        await loadInstalledModules();
    };
    //  Запрос активации — файл для поставщика: номер установки, версия программы и модули. Без имён,
    //  адресов и данных фермы. Собирается сервером, скачивается здесь.
    const downloadActivationRequest = () => {
        const req = licInfo.value && licInfo.value.activation_request;
        if (!req) return;
        const blob = new Blob([JSON.stringify(req, null, 1)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'fm-activation-request-' + (req.install_id || 'fm') + '.json';
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
        licMsg.value = { ok: true, text: _L('Файл запроса сохранён. Отправьте его поставщику любым способом — в ответ придёт файл лицензии.', 'The request file is saved. Send it to the vendor any way you like — you will get a license file back.') };
    };
    onMounted(() => { licLoad(); });
    //  Открыли вкладку «Модули» (в том числе после входа администратора) — перечитать лицензии.
    watch(curSetTab, (v) => { if (v === 'modules') licLoad(); });
    // --- Динамический интерфейс модулей: подгружаем web-компонент модуля из его папки и открываем окно ---
    const moduleComps = ref({});
    const activeModuleId = ref('');
    const activeModuleComp = computed(() => (activeModuleId.value && moduleComps.value[activeModuleId.value]) || null);
    const moduleHasUi = (id) => !!moduleComps.value[id];
    const activeModuleProps = ref({});
    const moduleLaunchers = computed(() => {
        const out = [];
        for (const m of installedModules.value) {
            if (m.disabled) continue;
            // Alpha 2.808: плитку запуска получает ТОЛЬКО работающий модуль. Не загрузившийся
            // показывается отдельным блоком «требует внимания»: у него нет ни UI-компонента,
            // ни маршрутов, и плитка-обманка открывала бы пустоту.
            if (!moduleIsLoaded(m)) continue;
            const ls = (m.launchers && m.launchers.length) ? m.launchers : [{}];
            //  2.1002: модуль МОЖЕТ НЕ ИМЕТЬ своего окна — тогда в манифесте нет entry, есть
            //  только settings_entry. Такой модуль показывается единственной ячейкой настроек
            //  во вкладке «Модули»; строка списка остаётся (в ней отключение и удаление), но
            //  она не притворяется кнопкой, которая что-то откроет.
            const cfgOnly = !m.entry && !!m.settings_entry;
            //  26.09.2026: предупреждения вместо отказа — newer (программа знает выпуск новее) и
            //  adminOnly (функции модуля, которых нет в карте прав этой версии программы), newerThanApp
            //  (контракт модуля новее карты), skipped (функции, которые подключить не удалось).
            ls.forEach((l, i) => out.push({ key: m.id + ':' + i, moduleId: m.id, source: m.source, first: i === 0, ru: l.ru || m.ru, en: l.en || m.en, icon: l.icon || m.icon || 'module', version: m.version, props: l.props || {}, settingsOnly: cfgOnly, newer: m.newer_version || '', adminOnly: Number(m.admin_only_routes) || 0, newerThanApp: !!m.newer_than_app, skipped: Number(m.skipped_routes) || 0, lic: licNote(m) }));
        }
        // Alpha 2.710: дедупликация плиток по отображаемому имени. Пример дубля: старый отдельный
        // модуль «Стоимость производства» v1.0.0 + одноимённая вторая плитка модуля склада.
        // При совпадении имён оставляем строку С КНОПКАМИ управления (first) — иначе модуль-дубль
        // нельзя удалить/отключить из UI; после его удаления скрытая плитка снова появится сама.
        const seen = {}; const dedup = [];
        for (const l of out) {
            const k = String(l.ru || l.en || '').trim().toLowerCase();
            if (!(k in seen)) { seen[k] = dedup.length; dedup.push(l); }
            else { const prev = dedup[seen[k]]; if (!prev.first && l.first) dedup[seen[k]] = l; }
        }
        return dedup;
    });
    const loadModuleComponents = async () => {
        for (const m of installedModules.value) {
            if (!m.entry || moduleComps.value[m.id]) continue;
            const entry = String(m.entry).replace(/^web\//, '');
            try {
                const mod = await import('/modules/' + m.id + '/' + entry);
                if (mod && mod.default) moduleComps.value[m.id] = markRaw(mod.default);
            } catch (e) { console.warn('[modules] UI load failed for', m.id, e); }
        }
    };
    // ═══ 3.000: модули на баре «Проекты / Задачи / Очередь / Филамент» и их настройки ═══
    //  Заказ владельца 11.09.2026: установленные модули — кнопками на том же баре, справа и
    //  отделённые от штатных вкладок; какие показывать — выбор во вкладке настроек «Модули».
    //  Выбор хранится НА СЕРВЕРЕ (настройка фермы): сделали один раз — видно на всех компьютерах.
    //  null = владелец ещё не выбирал, показываем все работающие модули с окном.
    const barModuleIds = ref(null);
    const barModulesBusy = ref(false);
    //  2.1001. Владелец: «галочка ни к чему не приводит». Причина — отказ сервера: прежний код
    //  откатывал выбор назад, и нажатие выглядело как несработавшее. Теперь выбор в силе всегда:
    //  сервер принял — настройка общая для фермы; отказал — остаётся на этом компьютере, и в
    //  настройках об этом сказано прямо. Так нажатие всегда даёт результат.
    const barLocalOnly = ref(false);
    const _BAR_LS_KEY = 'fm_bar_modules';
    const _barLocalRead = () => {
        try {
            const raw = localStorage.getItem(_BAR_LS_KEY);
            if (raw === null) return null;
            const v = JSON.parse(raw);
            return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : null;
        } catch (e) { return null; }
    };
    const _barLocalWrite = (ids) => {
        try {
            if (ids === null) localStorage.removeItem(_BAR_LS_KEY);
            else localStorage.setItem(_BAR_LS_KEY, JSON.stringify(ids));
        } catch (e) { /* браузер запретил хранение — выбор проживёт до перезагрузки страницы */ }
    };
    //  Кандидаты на бар: работающие модули, у которых есть окно (открывать нечего — нет кнопки).
    const barCandidates = computed(() => installedModules.value
        .filter((m) => moduleIsLoaded(m) && moduleHasUi(m.id))
        //  2.1001: на баре остались ОДНИ ЗНАЧКИ, поэтому пустой кнопки быть не должно:
        //  незнакомый значок (их набор конечный) подменяем общим значком модуля.
        .map((m) => ({ id: m.id, ru: m.ru, en: m.en, version: m.version,
                       icon: (m.icon && icons[m.icon]) ? m.icon : 'module' })));
    const barModuleShown = (id) => (barModuleIds.value === null) || barModuleIds.value.indexOf(id) >= 0;
    const barModules = computed(() => barCandidates.value.filter((m) => barModuleShown(m.id)));
    const _barPush = async (ids) => {
        try {
            const r = await fetch('/api/farm-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bar_modules: ids }) });
            const j = await r.json();
            return !!(j && j.ok);
        } catch (e) { return false; }
    };
    //  Переключатель «показывать на баре». Пока владелец не выбирал, список равен всем кандидатам —
    //  иначе первое же снятие галочки означало бы «оставить только этот».
    const barModuleToggle = async (id, on) => {
        if (barModulesBusy.value) return;
        const base = (barModuleIds.value === null) ? barCandidates.value.map((m) => m.id) : barModuleIds.value.slice();
        const next = on ? (base.indexOf(id) >= 0 ? base : base.concat([id])) : base.filter((x) => x !== id);
        barModulesBusy.value = true;
        barModuleIds.value = next;                       // результат виден сразу
        const ok = await _barPush(next);
        //  Отказ сервера НЕ отменяет выбор: он просто перестаёт быть общим для фермы.
        barLocalOnly.value = !ok;
        _barLocalWrite(ok ? null : next);
        if (!ok) {
            pushToast(lang.value === 'ru' ? 'Сохранено только на этом компьютере'
                                          : 'Saved on this computer only', 'info');
        }
        barModulesBusy.value = false;
    };

    //  Встроенные настройки модуля: модуль объявляет settings_entry в module.json, ядро грузит
    //  компонент и показывает его ЯЧЕЙКОЙ во вкладке «Модули». Модуль без этого поля остаётся
    //  как был — его настройки живут внутри его окна.
    const moduleSettingsComps = ref({});
    const loadModuleSettingsComponents = async () => {
        for (const m of installedModules.value) {
            if (!m.settings_entry || moduleSettingsComps.value[m.id] || !moduleIsLoaded(m)) continue;
            const entry = String(m.settings_entry).replace(/^web\//, '');
            try {
                const mod = await import('/modules/' + m.id + '/' + entry);
                if (mod && mod.default) moduleSettingsComps.value[m.id] = markRaw(mod.default);
            } catch (e) { console.warn('[modules] settings UI load failed for', m.id, e); }
        }
    };
    const modulesWithSettings = computed(() => installedModules.value
        .filter((m) => moduleIsLoaded(m) && moduleSettingsComps.value[m.id])
        .map((m) => ({ id: m.id, ru: m.ru, en: m.en, icon: m.icon || 'module',
                       version: m.version, comp: moduleSettingsComps.value[m.id] })));

    const runInstalledModule = (l) => { if (!l || !moduleHasUi(l.moduleId)) return; closeSettings(); activeModuleProps.value = l.props || {}; activeModuleId.value = l.moduleId; };
    // Открытие модуля по клику на карточку. Двухуровневая защита от конфликта с кнопками карточки:
    // событие, пришедшее из action-зоны (элемент с data-module-action — Удалить/Отключить/Включить),
    // модуль НЕ открывает. Первый уровень — @click.stop на самих кнопках; это второй, страховочный.
    //  3.000: запуск модуля кнопкой бара. Тот же путь, что из настроек: окно модуля.
    const runModuleById = (id) => { if (!moduleHasUi(id)) return; closeSettings(); activeModuleProps.value = {}; activeModuleId.value = id; };
    const openModuleFromCard = (ev, l) => {
        try { if (ev && ev.target && ev.target.closest && ev.target.closest('[data-module-action]')) return; } catch (e) {}
        runInstalledModule(l);
    };
    const openModuleForBadge = (pid) => {
        const list = printerBadges.value[pid] || [];
        if (!list.length) return;
        const l = moduleLaunchers.value.find((x) => x.moduleId === list[0].module_id);
        if (l) runInstalledModule(l);
    };
    // Клик по значку источника филамента на карточке принтера -> открыть инструмент сверки В ЕГО модуле.
    // Ядро НЕ знает про склад: module_id проставляет generic-агрегатор /api/printer-filament (тот же приём,
    // что у бейджей), а окно открывает ШТАТНЫЙ runInstalledModule — отдельного канала/слушателя не нужно,
    // поэтому и повторной регистрации подписок не бывает. Модуль отключён/удалён/без UI -> лаунчера нет ->
    // клик безопасно ничего не делает. nonce — чтобы ПОВТОРНЫЙ клик при уже открытом окне снова навёл
    // инструмент на нужный принтер (props меняются -> модуль реагирует), не создавая второго окна.
    let _filSourceNonce = 0;
    const openFilamentSource = (p) => {
        const pid = (p && typeof p === 'object') ? p.id : p;
        const fil = printerFilament.value[pid];
        const mid = fil && fil.module_id;
        if (!mid) return;
        const l = moduleLaunchers.value.find((x) => x.moduleId === mid);
        if (!l) return;
        _filSourceNonce += 1;
        runInstalledModule({ moduleId: mid, props: Object.assign({}, l.props || {},
            { action: 'reconcile', printerId: pid, nonce: _filSourceNonce }) });
    };
    // ══════════════════════════════════════════════════════════════════════════════════════════
    // «Печатать весь проект» — UI-ФАЗА A (Alpha 2.740, DRY-RUN). Только предварительный расчёт и
    // сохранение ПЛАНА. Печать НЕ запускается: сервер держит dispatch выключенным и на /start
    // отвечает 409, поэтому /start отсюда не вызывается вообще. Панель run, «Стол очищен»,
    // ambiguity и polling — фаза B, их здесь намеренно нет.
    // Источник истины — ответ сервера: план на фронте НЕ пересчитывается.
    // ══════════════════════════════════════════════════════════════════════════════════════════
    const showProjectWholePreflight = ref(false);
    const projectWholeProject = ref(null);
    const projectWholePreflight = ref(null);      // GET preflight (allow_overproduction=0)
    const projectWholeOverPreview = ref(null);    // read-only вариант плана СЕРВЕРА с разрешённым перепроизводством
    const projectWholeLoading = ref(false);
    const projectWholeError = ref('');            // ошибка расчёта (блокирует содержимое)
    const projectWholeSaveError = ref('');        // ошибка сохранения (показывается поверх плана, план виден)
    const projectWholeSaving = ref(false);
    const projectWholeAllowOverproduction = ref(false);
    const projectWholeSavedRun = ref(null);
    const projectWholeNotice = ref('');           // '' | saved | existing | stale
    let _pwAbort = null;

    // Показываем ИМЕННО тот план, который будет сохранён: с согласием — серверный вариант с перепроизводством.
    const projectWholePlan = computed(() => {
        const src = (projectWholeAllowOverproduction.value && projectWholeOverPreview.value)
            ? projectWholeOverPreview.value : projectWholePreflight.value;
        return src ? src.plan : null;
    });
    const projectWholeParts = computed(() => ((projectWholePreflight.value || {}).parts || []).filter((p) => p.remaining > 0));
    const projectWholeCompleted = computed(() => {
        const p = projectWholePreflight.value;
        return !!(p && !Object.keys(p.remaining || {}).length);
    });
    const projectWholeNeedsApproval = computed(() =>
        !!(projectWholePreflight.value && projectWholePreflight.value.plan.requires_overproduction_approval));
    // «Нужно / Будет напечатано / Лишнее» — целиком из серверного превью, своих вычислений плана нет.
    const projectWholeOverRows = computed(() => {
        const pre = projectWholeOverPreview.value;
        if (!pre) return [];
        const need = pre.plan.deficits || {}, over = pre.plan.overproduction_total || {};
        const names = {};
        for (const p of (pre.parts || [])) names[p.part_id] = p.part_name;
        return Object.keys(over).sort().map((pid) => ({
            part_id: pid, name: names[pid] || pid, need: need[pid] || 0,
            extra: over[pid] || 0, total: (need[pid] || 0) + (over[pid] || 0),
        }));
    });
    const projectWholePartName = (pid) => {
        for (const p of ((projectWholePreflight.value || {}).parts || [])) if (p.part_id === pid) return p.part_name;
        return pid;
    };
    const projectWholeCanSave = computed(() =>
        !projectWholeLoading.value && !projectWholeSaving.value && !projectWholeError.value
        && !projectWholeCompleted.value && !projectWholeSavedRun.value && !!projectWholePreflight.value
        && (!projectWholeNeedsApproval.value || projectWholeAllowOverproduction.value));

    const _pwCancel = () => { if (_pwAbort) { try { _pwAbort.abort(); } catch (e) {} _pwAbort = null; } };
    const loadProjectWholePreflight = async () => {
        const pid = projectWholeProject.value && projectWholeProject.value.id;
        if (!pid || projectWholeLoading.value) return;      // один активный GET: двойной клик второго не создаёт
        _pwCancel();
        const ac = new AbortController(); _pwAbort = ac;
        projectWholeLoading.value = true;
        projectWholeError.value = ''; projectWholeSaveError.value = ''; projectWholeNotice.value = '';
        projectWholeAllowOverproduction.value = false;      // новый расчёт -> согласие всегда сбрасывается
        projectWholeOverPreview.value = null; projectWholeSavedRun.value = null;
        try {
            const r = await fetch('/api/projects2/' + encodeURIComponent(pid) + '/whole-print/preflight', { signal: ac.signal });
            const j = await r.json();
            if (!r.ok) throw new Error((j && j.reason) || 'preflight failed');
            projectWholePreflight.value = j;
            if (j.plan && j.plan.requires_overproduction_approval) {
                // Точные числа лишних деталей знает только сервер — берём его же read-only расчёт.
                const r2 = await fetch('/api/projects2/' + encodeURIComponent(pid) + '/whole-print/preflight?allow_overproduction=1', { signal: ac.signal });
                if (r2.ok) projectWholeOverPreview.value = await r2.json();
            }
        } catch (e) {
            if (e && e.name === 'AbortError') return;       // штатная отмена — это не ошибка
            projectWholeError.value = String((e && e.message) || e);
        } finally {
            if (_pwAbort === ac) _pwAbort = null;
            projectWholeLoading.value = false;
        }
    };
    // Alpha 2.753: расчёт плана живёт ВСТРОЕННЫМ блоком внутри раскрытого проекта, а не модалкой.
    // Блок участвует в обычном layout (не fixed, без backdrop), поэтому Escape-слой не нужен, а
    // закрытие — это просто сворачивание блока той же кнопкой шапки проекта.
    const closeProjectWholePreflight = () => {
        _pwCancel();
        showProjectWholePreflight.value = false;
    };
    const openProjectWholePreflight = (pr) => {
        projectWholeProject.value = pr;
        projectWholePreflight.value = null; projectWholeSavedRun.value = null; projectWholeNotice.value = '';
        showProjectWholePreflight.value = true;
        loadProjectWholePreflight();
    };
    const refreshProjectWholePreflight = () => loadProjectWholePreflight();
    const saveProjectWholeDraft = async () => {
        if (!projectWholeCanSave.value) return;             // защита от повторного клика: один POST на действие
        const pid = projectWholeProject.value.id;
        const ver = projectWholePreflight.value.plan.snapshot_version;
        projectWholeSaving.value = true; projectWholeSaveError.value = ''; projectWholeNotice.value = '';
        try {
            const r = await fetch('/api/projects2/' + encodeURIComponent(pid) + '/whole-print/runs', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                // Клиентский план серверу НЕ отправляем: он пересчитает сам. Только версия снимка и согласие.
                body: JSON.stringify({ snapshot_version: ver,
                                       allow_overproduction: !!projectWholeAllowOverproduction.value }),
            });
            const j = await r.json().catch(() => ({}));
            if (r.status === 409 && j.reason === 'project_run_exists') {
                const g = await fetch('/api/project-runs/' + encodeURIComponent(j.existing_run_id));
                projectWholeSavedRun.value = g.ok ? await g.json() : { run_id: j.existing_run_id };
                projectWholeNotice.value = 'existing';
                mergeProjectRun(projectWholeSavedRun.value); focusProjectRun(j.existing_run_id);   // та же панель, без дубля
                syncProjectRunsPolling();
                return;
            }
            if (r.status === 409 && j.reason === 'project_plan_stale') { projectWholeNotice.value = 'stale'; return; }
            if (!r.ok || j.status === 'error') throw new Error((j && j.reason) || 'save failed');
            const g = await fetch('/api/project-runs/' + encodeURIComponent(j.run_id));
            projectWholeSavedRun.value = g.ok ? await g.json() : { run_id: j.run_id, state: 'draft' };
            projectWholeNotice.value = 'saved';
            mergeProjectRun(projectWholeSavedRun.value); focusProjectRun(j.run_id);   // добавляем в единую панель
            syncProjectRunsPolling();
        } catch (e) {
            projectWholeSaveError.value = String((e && e.message) || e);   // окно не закрываем, согласие не теряем
        } finally {
            projectWholeSaving.value = false;
        }
    };

    // ══════════════════════════════════════════════════════════════════════════════════════════
    // «Планы проектов» — UI-ФАЗА B1 (Alpha 2.740, DRY-RUN). ОДНА немодальная панель на ВСЕ активные
    // run'ы разных проектов (отдельного окна на run НЕТ). Печать не запускается: /start отсюда не
    // вызывается, dispatch на сервере выключен. Clearance/ambiguity/индикатор на карточке — фаза B2.
    // Состояние server-driven: единственный источник активных run'ов — GET /api/project-runs?active=1
    // (полный run_public + project_name уже в ответе, поэтому отдельный GET на каждый run не нужен).
    // ══════════════════════════════════════════════════════════════════════════════════════════
    const PROJECT_RUNS_POLL_MS = 4000;
    const projectRunsById = ref({});             // run_id -> snapshot
    const projectRunOrder = ref([]);             // стабильный порядок из ответа сервера
    // Alpha 2.753: глобальной плавающей панели «Планы проектов» больше НЕТ. Каждый run живёт
    // ВСТРОЕННЫМ блоком внутри своего раскрытого проекта. wpxOpenMap — явный выбор пользователя
    // (project_id -> bool); без явного выбора блок открыт автоматически, если у проекта есть run —
    // так активный план восстанавливается после перезагрузки внутри СВОЕГО проекта.
    const wpxOpenMap = ref({});
    const projectRunsInitialLoading = ref(false);
    const projectRunsListError = ref('');
    const projectRunActions = ref({});           // run_id -> 'pause'|'resume'|'cancel' (action-lock)
    const projectRunErrors = ref({});            // run_id -> текст ошибки (живёт ВНУТРИ карточки)
    const projectRunConfirm = reactive({ open: false, kind: '', run: null, target: null, resolution: '' });
    const highlightedRunId = ref('');
    let projectRunsPollTimer = null, projectRunsPollController = null, projectRunsPollInFlight = false;
    let _prConfirmEsc = null, _prCancelBtn = null, _prTerminalIds = new Set();

    const projectRunsList = computed(() => projectRunOrder.value.map((id) => projectRunsById.value[id]).filter(Boolean));
    // Alpha 2.763: опрос обязан идти, пока на экране есть план, который НЕ терминален ЛИБО ещё
    // ВЛАДЕЕТ принтером (отменён, но деталь не разрешена). Прежний счётчик считал локально
    // отменённый план «неактивным» -> опрос останавливался -> результат разрешения никогда не
    // доезжал до экрана, и интерфейс замирал на устаревшем снимке до перезагрузки страницы.
    const projectRunsActiveCount = computed(() => projectRunsList.value.filter(
        (r) => !['completed', 'cancelled'].includes(r.state) || _prStillOwns(r)).length);
    // Alpha 2.760: убрать план из КЛИЕНТСКОГО снимка. Терминальный план (завершён/отменён) не
    // должен висеть в проекте вечно: опрос при нуле активных останавливается, поэтому сам он уже
    // не обновится — и пока он в снимке, wpxRunFor его возвращает, а «Печатать весь проект» не
    // считает новый план. Раньше из этого выходили только перезагрузкой страницы.
    // Alpha 2.761: состояния, в которых деталь ВЛАДЕЕТ принтером (печатается / уже на столе /
    // неоднозначность после отправки). План с такой деталью убирать с экрана НЕЛЬЗЯ: оператор
    // обязан иметь возможность её разрешить, иначе принтер удержан, а интерфейс об этом молчит.
    const _PR_OWNING = ['leased', 'sending', 'waiting_start_confirmation', 'printing',
                        'waiting_plate_clear', 'ambiguous_after_dispatch'];
    const _prStillOwns = (r) => !!(r && (r.items || []).some((it) => _PR_OWNING.includes(it.state)));
    const _prDrop = (id) => {
        if (!id) return;
        if (_prStillOwns(projectRunsById.value[id])) return;   // ещё держит принтер — не прячем
        const by = Object.assign({}, projectRunsById.value); delete by[id];
        projectRunsById.value = by;
        projectRunOrder.value = projectRunOrder.value.filter((x) => x !== id);
    };
    const projectRunName = (r) => (r && r.project_name) ? r.project_name
        : (lang.value === 'ru' ? 'Проект недоступен' : 'Project unavailable');   // project_name=null: run не теряем
    const projectRunCounts = (r) => {
        const c = (r && r.counts) || {};
        const done = c.completed || 0, blocked = (c.blocked || 0) + (c.superseded_by_external_progress || 0);
        let planned = 0;
        for (const k in c) planned += c[k];
        return { planned, done, blocked };
    };
    // Кнопки — по ФАКТИЧЕСКОМУ state; окончательное решение всё равно за backend (409 обрабатываем).
    const projectRunCanPause = (r) => !!r && ['draft', 'running', 'waiting_for_printer', 'waiting_for_plate_clear'].includes(r.state);
    const projectRunCanResume = (r) => !!r && r.state === 'paused';
    const projectRunCanCancel = (r) => !!r && !['completed', 'cancelled'].includes(r.state);
    const projectRunBusy = (r) => !!(r && projectRunActions.value[r.run_id]);

    const mergeProjectRun = (run) => {
        if (!run || !run.run_id) return;
        projectRunsById.value = Object.assign({}, projectRunsById.value, { [run.run_id]: run });
        if (!projectRunOrder.value.includes(run.run_id)) projectRunOrder.value = projectRunOrder.value.concat([run.run_id]);
        if (['completed', 'cancelled'].includes(run.state)) _prTerminalIds.add(run.run_id);
    };
    const focusProjectRun = (runId) => {
        // Раскрыть ИМЕННО проект этого run'а и его встроенный блок — общей панели больше нет.
        const r = projectRunsById.value[runId];
        if (r && r.project_id) {
            project2Expanded.value = r.project_id;
            wpxOpenMap.value = Object.assign({}, wpxOpenMap.value, { [r.project_id]: true });
        }
        highlightedRunId.value = runId || '';
    };
    // Список — источник СОСТАВА и ПОРЯДКА runs; detail — источник items/printers/clearance
    // (list endpoint их не отдаёт). Оба живут в ОДНОМ общем тике: отдельного таймера на run нет.
    const _prFetchDetail = async (id, signal) => {
        const r = await fetch('/api/project-runs/' + encodeURIComponent(id), { signal });
        if (!r.ok) throw new Error('http ' + r.status);
        return await r.json();
    };
    const _prTick = async (signal) => {
        const r = await fetch('/api/project-runs?active=1', { signal });
        if (!r.ok) throw new Error('http ' + r.status);
        const j = await r.json();
        const by = {}, order = [];
        for (const run of ((j && j.runs) || [])) {          // дедупликация по run_id + порядок сервера
            if (!run || !run.run_id || by[run.run_id]) continue;
            // Alpha 2.763: run, который сервер ВЕРНУЛ, показываем ВСЕГДА и со свежим состоянием —
            // в т.ч. отменённый план, ещё удерживающий принтер (2.761 возвращает и такие).
            // Прежний фильтр «отменённый локально назад не воскрешаем» замораживал до-отменочный
            // снимок навсегда: на сервере план уже cancelled с неразрешённой деталью, а экран
            // показывал старое состояние с кнопкой «Отменить план» (сервер отвечал 409 bad_state)
            // и не узнавал о разрешении. Правда сервера главнее локальной памяти.
            by[run.run_id] = run; order.push(run.run_id);
        }
        // Статус вооружения (5B2a) — в ТОМ ЖЕ тике и ТОЛЬКО GET: отдельного таймера не заводим,
        // POST опрос не делает никогда. Ошибка статуса не должна ломать обновление планов.
        const det = await Promise.allSettled(order.map((id) => _prFetchDetail(id, signal))
            .concat([loadArmStatus(signal)])).then((all) => all.slice(0, order.length));
        const bad = [];
        order.forEach((id, k) => {
            const d = det[k];
            if (d.status === 'fulfilled' && d.value && d.value.run_id) {
                // project_name есть ТОЛЬКО у списка — detail его не перетирает.
                by[id] = Object.assign({}, by[id], d.value, { project_name: by[id].project_name });
                return;
            }
            // Упавший detail НЕ стирает snapshot: держим прежние items/printers этого run,
            // остальные run'ы вообще не затронуты.
            const prev = projectRunsById.value[id];
            if (prev) by[id] = Object.assign({}, by[id],
                { items: prev.items, counts: prev.counts, printers: prev.printers });
            if (!(d.reason && d.reason.name === 'AbortError')) bad.push(id);
        });
        for (const id of projectRunOrder.value) {           // терминальные показываем до сворачивания панели
            // Alpha 2.763: держим только снимок, НЕ владеющий принтером. Если снимок утверждает,
            // что деталь ещё владеет, а сервер run уже НЕ вернул (2.761: удерживающие планы он
            // возвращает всегда) — снимок устарел (деталь уже разрешили): показывать его = врать
            // и вечно блокировать «Печатать весь проект».
            if (!by[id] && _prTerminalIds.has(id) && projectRunsById.value[id]
                && !_prStillOwns(projectRunsById.value[id])) { by[id] = projectRunsById.value[id]; order.push(id); }
        }
        projectRunsById.value = by; projectRunOrder.value = order;
        return bad;
    };
    // ОДИН тик на всё: и восстановление, и polling. Перекрытия запрещены, контроллер один.
    const _prRunTick = async (initial) => {
        if (projectRunsPollInFlight) return false;           // перекрытия тиков запрещены
        projectRunsPollInFlight = true;
        if (initial) projectRunsInitialLoading.value = true;
        const ac = new AbortController(); projectRunsPollController = ac;
        try {
            const bad = await _prTick(ac.signal);
            projectRunsListError.value = bad.length              // успешный ответ гасит временную ошибку
                ? (lang.value === 'ru' ? 'Не удалось обновить детали планов: ' : 'Failed to refresh plan details: ') + bad.join(', ')
                : '';
            return true;
        } catch (e) {
            // Ошибка НЕ ломает SPA и НЕ стирает последний хороший snapshot — только помечает панель.
            if (!(e && e.name === 'AbortError')) projectRunsListError.value = String((e && e.message) || e);
            return false;
        } finally {
            if (projectRunsPollController === ac) projectRunsPollController = null;
            projectRunsPollInFlight = false;
            if (initial) projectRunsInitialLoading.value = false;
            syncProjectRunsPolling();
        }
    };
    const loadActiveProjectRuns = (initial) => _prRunTick(!!initial);
    const pollProjectRunsOnce = () => _prRunTick(false);
    const startProjectRunsPolling = () => {
        if (projectRunsPollTimer) return;                    // ровно ОДИН таймер на всю систему
        projectRunsPollTimer = setInterval(pollProjectRunsOnce, PROJECT_RUNS_POLL_MS);
    };
    const stopProjectRunsPolling = () => {
        if (projectRunsPollTimer) { clearInterval(projectRunsPollTimer); projectRunsPollTimer = null; }
        if (projectRunsPollController) { try { projectRunsPollController.abort(); } catch (e) {} projectRunsPollController = null; }
        projectRunsPollInFlight = false;
    };
    // Опрашиваем ТОЛЬКО пока есть активный (нетерминальный) run. Свёрнутая панель опрос не прекращает.
    const syncProjectRunsPolling = () => {
        if (projectRunsActiveCount.value > 0) startProjectRunsPolling();
        else stopProjectRunsPolling();
    };
    const refreshProjectRuns = () => loadActiveProjectRuns(false);

    // ══════════════════════════════════════════════════════════════════════════════════════════
    // Alpha 2.753: ВСТРОЕННЫЙ блок «Печатать весь проект» (wpx-*). Живёт внутри раскрытого
    // проекта, участвует в обычном layout: НЕ fixed, НЕ модалка, без backdrop. Показывает ТОЛЬКО
    // значения backend (preflight / run detail): фронт ничего не пересчитывает и не выдумывает.
    // Один проект — не больше одного блока; run чужого проекта здесь появиться не может, потому
    // что выбирается строго по r.project_id.
    // ══════════════════════════════════════════════════════════════════════════════════════════
    const wpxTechOpen = ref({});                  // project_id -> раскрыты ли технические подробности
    const wpxRunFor = (pid) => {
        if (!pid) return null;
        const mine = projectRunsList.value.filter((r) => r && r.project_id === pid);
        return mine.find((r) => !['completed', 'cancelled'].includes(r.state)) || mine[mine.length - 1] || null;
    };
    const wpxOpenFor = (pid) => {
        if (pid in wpxOpenMap.value) return !!wpxOpenMap.value[pid];
        return !!wpxRunFor(pid);                  // reload: активный план сам виден в СВОЁМ проекте
    };
    const toggleWholePrint = (pr) => {
        const pid = pr && pr.id;
        if (!pid) return;
        // Alpha 2.760: ТЕРМИНАЛЬНЫЙ план (завершён/отменён) — уже история, и он не должен висеть в
        // проекте. Проверяем это ДО переключения показа: иначе блок считается «открытым» из-за
        // самого этого плана, первый клик просто сворачивал бы его, и новый план требовал бы двух
        // нажатий (а до 2.760 — вообще перезагрузки страницы). Кнопка называется «Печатать весь
        // проект» — одно нажатие обязано дать НОВЫЙ план. Расчёт плана read-only, ничего не печатает.
        const _rf = wpxRunFor(pid);
        if (_rf && ['completed', 'cancelled'].includes(_rf.state)) {
            _prTerminalIds.add(_rf.run_id); _prDrop(_rf.run_id);
            wpxOpenMap.value = Object.assign({}, wpxOpenMap.value, { [pid]: true });
            // Alpha 2.763: если план НЕ убрался (ещё владеет принтером — деталь не разрешена),
            // показываем ЕГО, а не расчёт нового: сперва оператор обязан подтвердить исход.
            if (!wpxRunFor(pid)) openProjectWholePreflight(pr);
            return;
        }
        if (wpxOpenFor(pid)) {
            wpxOpenMap.value = Object.assign({}, wpxOpenMap.value, { [pid]: false });
            if ((projectWholeProject.value || {}).id === pid) closeProjectWholePreflight();
            return;
        }
        wpxOpenMap.value = Object.assign({}, wpxOpenMap.value, { [pid]: true });
        if (!wpxRunFor(pid)) openProjectWholePreflight(pr);   // run'а нет — сразу считаем план
    };
    // Preflight этого проекта (расчёт открыт по одному проекту за раз — как и раньше).
    const wpxPreflightFor = (pid) => (showProjectWholePreflight.value
        && (projectWholeProject.value || {}).id === pid);
    // Человеческий статус. raw-коды состояния здесь НЕ показываются (они в «Технических подробностях»).
    const wpxStatus = (pid) => {
        const ru = lang.value === 'ru';
        const r = wpxRunFor(pid);
        if (!r) {
            if (!wpxPreflightFor(pid)) return { k: 'idle', t: ru ? 'План не рассчитан' : 'No plan yet' };
            if (projectWholeLoading.value) return { k: 'idle', t: ru ? 'Считаем план…' : 'Calculating…' };
            if (projectWholeError.value) return { k: 'bad', t: ru ? 'Не удалось рассчитать план' : 'Plan calculation failed' };
            if (projectWholeCompleted.value) return { k: 'ok', t: ru ? 'Проект уже напечатан' : 'Already printed' };
            if (projectWholePreflight.value) return { k: 'warn', t: ru ? 'План рассчитан — проверьте и сохраните' : 'Plan ready — review and save' };
            return { k: 'idle', t: ru ? 'План не рассчитан' : 'No plan yet' };
        }
        const items = r.items || [];
        const has = (st) => items.some((it) => it.state === st);
        if (r.state === 'completed') return { k: 'ok', t: ru ? 'Завершён' : 'Completed' };
        if (r.state === 'cancelled') return { k: 'idle', t: ru ? 'Отменён' : 'Cancelled' };
        if (r.state === 'paused') return { k: 'warn', t: ru ? 'Приостановлен' : 'Paused' };
        if (r.state === 'attention_required' || has('ambiguous_after_dispatch'))
            return { k: 'bad', t: ru ? 'Нужно решение человека' : 'Human decision required' };
        if (has('waiting_plate_clear') || r.state === 'waiting_for_plate_clear')
            return { k: 'warn', t: ru ? 'Ожидается снятие детали' : 'Waiting for part removal' };
        if (has('printing') || has('waiting_start_confirmation') || has('sending') || has('leased'))
            return { k: 'run', t: ru ? 'Выполняется' : 'In progress' };
        const cur = wpxCurrentItem(r);
        if (cur && ['pending', 'eligible'].includes(cur.state) && feedBlockState(cur) === 'ready') {
            // Кнопка отправки доступна либо по in-app-разрешению (2.757), либо по CLI-вооружению.
            if (canStartInApp(r, cur) || canControlledStart(r, cur))
                return { k: 'ok', t: ru ? 'Готов к запуску' : 'Ready to start' };
            const t2 = wpxItemClearance(r, cur);
            if (t2 && !t2.printer.clearance)
                return { k: 'warn', t: ru ? 'Подтвердите пустой стол' : 'Confirm the plate is empty' };
            if (!printEnabled.value)
                return { k: 'warn', t: ru ? 'План готов · включите печать из приложения'
                                          : 'Plan ready · enable printing from the app' };
            return { k: 'warn', t: ru ? 'Ожидание принтера' : 'Waiting for the printer' };
        }
        if (cur && ['pending', 'eligible'].includes(cur.state))
            return { k: 'warn', t: ru ? 'Нужно настроить' : 'Needs setup' };
        return { k: 'idle', t: ru ? 'Ожидание' : 'Waiting' };
    };
    // Пояснение под статусом, когда главной кнопки нет и это НЕ ошибка.
    const wpxHint = (pid) => {
        const ru = lang.value === 'ru';
        const r = wpxRunFor(pid);
        if (!r) return '';
        const cur = wpxCurrentItem(r);
        if (!cur) return '';
        // План готов, но печать из приложения ещё не включена -> подсказываем включить (кнопка ниже).
        if (['pending', 'eligible'].includes(cur.state) && feedBlockState(cur) === 'ready'
            && !printEnabled.value && !canControlledStart(r, cur)) {
            return ru ? 'Включите печать из приложения кнопкой ниже, чтобы появилась кнопка запуска.'
                      : 'Enable printing from the app with the button below to get the start button.';
        }
        return '';
    };
    // ── Alpha 2.754: серия «текущий запуск + очередь». Для одного принтера запуски строго
    // последовательные, поэтому подробно показывается ТОЛЬКО текущий, остальные — компактной
    // строкой очереди. Всё ниже — длины/суммы реальных значений backend, ничего не выдумывается. ──
    const WPX_ACTIVE_STATES = ['leased', 'sending', 'waiting_start_confirmation', 'printing',
                               'waiting_plate_clear', 'ambiguous_after_dispatch'];
    const WPX_DONE_STATES = ['completed', 'cancelled', 'superseded_by_external_progress'];
    const wpxItems = (r) => (r && r.items) || [];
    // ТЕКУЩИЙ запуск: активный (что-то уже происходит) всегда приоритетнее; иначе — первый ещё не
    // выполненный по порядку плана. Всё завершено -> null.
    // 2.769 (аудит): blocked-деталь (seq=0, без файла) сортируется первой и раньше ЗАХВАТЫВАЛА
    // карточку текущего запуска: у неё нет ни одной кнопки, а настоящие pending-детали уезжали
    // в «Очередь» без управления. Теперь blocked становится «текущей» только если больше нечего.
    const wpxCurrentItem = (r) => wpxItems(r).find((it) => WPX_ACTIVE_STATES.includes(it.state))
        || wpxItems(r).find((it) => !WPX_DONE_STATES.includes(it.state) && it.state !== 'blocked')
        || wpxItems(r).find((it) => !WPX_DONE_STATES.includes(it.state)) || null;
    const wpxCurrentIndex = (r) => {
        const c = wpxCurrentItem(r);
        return c ? wpxItems(r).findIndex((it) => it.item_id === c.item_id) : -1;
    };
    // Очередь: всё ПОСЛЕ текущего, что ещё предстоит. Будущий запуск не бывает «готов к запуску».
    const wpxQueueItems = (r) => {
        const i = wpxCurrentIndex(r);
        if (i < 0) return [];
        return wpxItems(r).slice(i + 1).filter((it) => !WPX_DONE_STATES.includes(it.state));
    };
    const _qty = (it) => Object.values((it && it.planned_parts) || {}).reduce((a, b) => a + (+b || 0), 0);
    // Сводка: ЭКЗЕМПЛЯРЫ (need/done/left) и ЗАПУСКИ (cur/total) — раздельно, не под одной подписью.
    const wpxSummary = (pid) => {
        const r = wpxRunFor(pid);
        if (!r) return null;
        const all = wpxItems(r).filter((it) => it.state !== 'cancelled');
        const need = all.reduce((a, it) => a + _qty(it), 0);
        const done = all.filter((it) => it.state === 'completed').reduce((a, it) => a + _qty(it), 0);
        const runsTotal = all.length;
        const runsDone = all.filter((it) => WPX_DONE_STATES.includes(it.state)).length;
        const issues = (projectRunCounts(r).blocked || 0)
            + wpxItems(r).filter((it) => it.state === 'ambiguous_after_dispatch').length
            + wpxItems(r).filter((it) => ['pending', 'eligible'].includes(it.state)
                && ['blocked', 'attention', 'corrupt'].includes(feedBlockState(it))).length;
        return { need, done, left: Math.max(0, need - done),
                 runsTotal, runsDone, cur: wpxCurrentIndex(r) + 1, issues };
    };
    const wpxProgressPct = (pid) => {
        const s = wpxSummary(pid);
        if (!s || !s.need) return 0;
        return Math.round(100 * s.done / s.need);
    };
    // Имя ДЕТАЛИ и человеческое имя файла — из canonical part_names/filename снимка (2.754).
    // pfile_/pitem_-идентификаторы на первом уровне запрещены.
    const wpxPartsText = (r, it) => {
        const names = (r && r.part_names) || {};
        const parts = Object.entries((it && it.planned_parts) || {});
        if (!parts.length) return '';
        return parts.map(([pid2, q]) => (names[pid2] || (lang.value === 'ru' ? 'деталь' : 'part'))
            + ' × ' + q).join(', ');
    };
    const wpxFileLabel = (it) => (it && it.filename) || '';
    // Принтер серии: у последовательных запусков он один (feed_plan.printer_id текущего).
    const wpxSeriesPrinter = (r) => {
        const cur = wpxCurrentItem(r);
        return cur ? wpxPrinterName(r, cur) : '';
    };
    // Материал серии: если ВСЕ предстоящие запуски используют один и тот же источник — показываем
    // его ОДИН раз на уровне серии; иначе null (тогда строка остаётся в карточке текущего).
    const wpxSeriesMaterial = (r) => {
        const rest = [wpxCurrentItem(r)].concat(wpxQueueItems(r)).filter(Boolean)
            .filter((it) => !WPX_DONE_STATES.includes(it.state));
        if (!rest.length) return null;
        const lines = rest.map((it) => wpxMaterialLine(it));
        return lines.every((l) => l === lines[0]) ? lines[0] : null;
    };
    // Единый статус пустого стола: при ДЕЙСТВУЮЩЕМ подтверждении — один компактный факт и слабое
    // «Отозвать»; кнопка «Стол очищен» и подсказка «уже действует» при этом НЕ показываются.
    const wpxClrState = (r, it) => {
        const t = wpxItemClearance(r, it);
        if (!t) return null;
        if (t.printer.clearance) return { t, kind: 'active' };
        return { t, kind: t.initial ? 'need-initial' : 'need-post' };
    };
    // Человеческое состояние запуска (карточки). raw — только в технических подробностях.
    const wpxItemState = (r, it) => {
        const ru = lang.value === 'ru';
        const M = {
            leased: [ 'Отправляется', 'Sending' ], sending: [ 'Отправляется', 'Sending' ],
            waiting_start_confirmation: [ 'Ожидается подтверждение старта', 'Awaiting start confirmation' ],
            printing: [ 'Печатается', 'Printing' ],
            waiting_plate_clear: [ 'Снимите готовую деталь', 'Remove the printed part' ],
            ambiguous_after_dispatch: [ 'Требуется решение', 'Decision required' ],
            failed_before_dispatch: [ 'Отправка не удалась', 'Send failed' ],
            completed: [ 'Завершено', 'Done' ], cancelled: [ 'Отменён', 'Cancelled' ],
            blocked: [ 'Заблокировано', 'Blocked' ],
            superseded_by_external_progress: [ 'Уже напечатано вне плана', 'Printed outside the plan' ],
        };
        if (M[it.state]) return M[it.state][ru ? 0 : 1];
        // pending/eligible: статус определяет ГОТОВНОСТЬ материала, а не внутренний код.
        const fb = feedBlockState(it);
        if (fb === 'ready') {
            const t = wpxItemClearance(r, it);
            if (t && !t.printer.clearance)
                return ru ? 'Ожидается подтверждение пустого стола' : 'Awaiting empty-plate confirmation';
            return ru ? 'Готово к запуску' : 'Ready to start';
        }
        if (fb === 'none') return ru ? 'Нужно выбрать материал' : 'Material not selected';
        if (fb === 'approval') return ru ? 'Материал ждёт подтверждения' : 'Material awaits confirmation';
        if (fb === 'blocked' || fb === 'attention' || fb === 'corrupt')
            return ru ? 'Принтер или материал недоступен' : 'Printer or material unavailable';
        return ru ? 'Ожидает запуска' : 'Queued';
    };
    const wpxItemKind = (r, it) => {
        if (['ambiguous_after_dispatch', 'failed_before_dispatch'].includes(it.state)) return 'bad';
        if (['printing', 'waiting_start_confirmation', 'sending', 'leased'].includes(it.state)) return 'run';
        if (it.state === 'waiting_plate_clear') return 'warn';
        if (it.state === 'completed') return 'ok';
        if (['pending', 'eligible'].includes(it.state))
            return feedBlockState(it) === 'ready' ? 'ok' : 'warn';
        return 'idle';
    };
    // Компактная строка материала: «PETG · внешняя катушка · подтверждено».
    const wpxMaterialLine = (it) => {
        const ru = lang.value === 'ru';
        const fb = feedBlockState(it);
        if (fb === 'none' || fb === 'readonly-none') return ru ? 'не выбран' : 'not selected';
        if (fb === 'corrupt') return ru ? 'запись повреждена — выберите заново' : 'corrupted — pick again';
        const fp = it.feed_plan || {};
        const mat = fp.inventory_material || fp.required_material || '—';
        const src = fp.mode === 'external' ? (ru ? 'внешняя катушка' : 'external spool') : feedSlotLabel(fp.ams_slot);
        const st = fb === 'ready' ? (ru ? 'подтверждено' : 'confirmed')
            : fb === 'approval' ? (ru ? 'нужно подтверждение' : 'needs confirmation')
            : (ru ? 'недоступно' : 'unavailable');
        return mat + ' · ' + src + ' · ' + st;
    };
    const wpxMaterialWarn = (it) => !['ready', 'readonly-plan'].includes(feedBlockState(it))
        && feedBlockState(it).indexOf('readonly') !== 0;
    // Цель «Стол очищен» ИМЕННО этого запуска (первичная или постпечатная) — кнопка живёт в карточке.
    const wpxItemClearance = (r, it) =>
        projectRunClearanceTargets(r).find((t) => t.item.item_id === it.item_id) || null;
    const wpxPrinterName = (r, it) => {
        const pid = (it.feed_plan && it.feed_plan.printer_id) || it.assigned_printer_id || '';
        if (!pid) return lang.value === 'ru' ? 'принтер не выбран' : 'no printer';
        const p = ((r && r.printers) || []).find((x) => x.printer_id === pid);
        return (p && p.name) || pid;
    };
    const wpxPartsLine = (it) => {
        const q = Object.values(it.planned_parts || {}).reduce((a, b) => a + (+b || 0), 0);
        return q ? (q + ' ' + (lang.value === 'ru' ? 'шт.' : 'pcs')) : '';
    };
    // ОДНО главное действие. Возвращает {key, label} — обработчик wpxDoMain по key.
    const wpxMainCta = (pid) => {
        const ru = lang.value === 'ru';
        const r = wpxRunFor(pid);
        if (!r) {
            if (projectWholeLoading.value || projectWholeSaving.value) return null;
            if (!wpxPreflightFor(pid) || projectWholeError.value)
                return { key: 'calc', label: ru ? 'Рассчитать план' : 'Calculate plan' };
            if (projectWholeCanSave.value) return { key: 'save', label: ru ? 'Сохранить план' : 'Save plan' };
            return null;
        }
        if (r.state === 'paused') return { key: 'resume', label: ru ? 'Продолжить план' : 'Resume plan' };
        // 2.754: step-действия (материал / стол / контрольный запуск) живут ЕДИНСТВЕННОЙ кнопкой
        // в карточке ТЕКУЩЕГО запуска — вторая primary сверху была бы дублем того же действия.
        return null;
    };
    const wpxDoMain = (pr) => {
        const pid = pr && pr.id;
        const cta = wpxMainCta(pid);
        if (!cta) return;
        if (cta.key === 'calc') return openProjectWholePreflight(pr);
        if (cta.key === 'save') return saveProjectWholeDraft();
        if (cta.key === 'resume') return resumeProjectRun(wpxRunFor(pid));
    };
    const wpxQueueOpen = ref({});                 // project_id -> раскрыт ли список очереди
    const wpxToggleQueue = (pid) => {
        wpxQueueOpen.value = Object.assign({}, wpxQueueOpen.value, { [pid]: !wpxQueueOpen.value[pid] });
    };
    const wpxMatMenu = ref({});                   // project_id -> раскрыты ли настройки материала
    const wpxToggleMatMenu = (pid) => {
        wpxMatMenu.value = Object.assign({}, wpxMatMenu.value, { [pid]: !wpxMatMenu.value[pid] });
    };
    const wpxToggleTech = (pid) => {
        wpxTechOpen.value = Object.assign({}, wpxTechOpen.value, { [pid]: !wpxTechOpen.value[pid] });
    };

    const _prAction = async (run, kind, url, body) => {
        if (!run || projectRunActions.value[run.run_id]) return;   // action-lock по КОНКРЕТНОМУ run
        projectRunActions.value = Object.assign({}, projectRunActions.value, { [run.run_id]: kind });
        projectRunErrors.value = Object.assign({}, projectRunErrors.value, { [run.run_id]: '' });
        try {
            const r = await fetch(url, body
                ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
                : { method: 'POST' });
            const j = await r.json().catch(() => ({}));
            if (!r.ok || j.status === 'error') throw new Error((j && j.reason) || ('http ' + r.status));
            if (kind === 'cancel') {
                // Alpha 2.760: отменённый план УБИРАЕМ из проекта. Раньше он возвращался сюда как
                // «Отменён» и оставался на экране навсегда (помогала только перезагрузка).
                _prTerminalIds.add(run.run_id);   // назад из ответа сервера не воскрешаем
                _prDrop(run.run_id);              // и убираем из текущего снимка -> проект чист
            }
            await loadActiveProjectRuns(false);
        } catch (e) {
            // Ошибка живёт ВНУТРИ карточки и не блокирует другие run'ы.
            projectRunErrors.value = Object.assign({}, projectRunErrors.value, { [run.run_id]: String((e && e.message) || e) });
        } finally {
            const a = Object.assign({}, projectRunActions.value); delete a[run.run_id]; projectRunActions.value = a;
            syncProjectRunsPolling();
        }
    };
    const pauseProjectRun = (run) => _prAction(run, 'pause', '/api/project-runs/' + encodeURIComponent(run.run_id) + '/pause');
    const resumeProjectRun = (run) => _prAction(run, 'resume', '/api/project-runs/' + encodeURIComponent(run.run_id) + '/resume');
    // Один styled confirm на все опасные действия панели (cancel / «Стол очищен» / решение по
    // ambiguous). Пока он открыт — НИ ОДНОГО POST: подтверждение утверждает физический факт.
    const _prOpenConfirm = (kind, run, ev, extra) => {
        try { _prCancelBtn = (ev && ev.currentTarget) || null; } catch (e) { _prCancelBtn = null; }
        projectRunConfirm.kind = kind; projectRunConfirm.run = run;
        projectRunConfirm.target = (extra && extra.target) || null;
        projectRunConfirm.resolution = (extra && extra.resolution) || '';
        projectRunConfirm.open = true;
        if (!_prConfirmEsc) _prConfirmEsc = registerEscapeLayer(closeCancelProjectRunConfirm);
    };
    const requestCancelProjectRun = (run, ev) => _prOpenConfirm('cancel', run, ev, null);
    const closeCancelProjectRunConfirm = () => {
        projectRunConfirm.open = false; projectRunConfirm.run = null;
        projectRunConfirm.target = null; projectRunConfirm.resolution = ''; projectRunConfirm.kind = '';
        if (_prConfirmEsc) { unregisterEscapeLayer(_prConfirmEsc); _prConfirmEsc = null; }
        const b = _prCancelBtn; _prCancelBtn = null;
        nextTick(() => { try { if (b && b.focus) b.focus(); } catch (e) {} });
    };
    const confirmCancelProjectRun = async () => {
        const run = projectRunConfirm.run, kind = projectRunConfirm.kind;
        const t = projectRunConfirm.target, res = projectRunConfirm.resolution;
        if (!run || projectRunActions.value[run.run_id]) return;
        const base = '/api/project-runs/' + encodeURIComponent(run.run_id);
        closeCancelProjectRunConfirm();
        if (kind === 'cancel') return await _prAction(run, 'cancel', base + '/cancel');
        if (kind === 'clear') {
            if (!t) return;
            // confirmed:true ставит ЧЕЛОВЕК этой кнопкой. finished_job_id — точный id проектного
            // задания этого item ('' = initial clearance, стол пуст до первой печати).
            return await _prAction(run, 'clear',
                base + '/printers/' + encodeURIComponent(t.printer.printer_id) + '/plate-clear',
                { confirmed: true, finished_job_id: t.finished_job_id });
        }
        if (kind === 'resolve') {
            if (!t || !res) return;
            return await _prAction(run, 'resolve',
                base + '/items/' + encodeURIComponent(t.item.item_id) + '/resolve', { resolution: res });
        }
    };

    // ══════════════════════════════════════════════════════════════════════════════════════════
    // UI-фаза B2: «Стол очищен», отзыв подтверждения, ручное решение по ambiguous.
    // ══════════════════════════════════════════════════════════════════════════════════════════
    // ЕДИНСТВЕННАЯ модель eligibility. Питает И кнопку в панели, И индикатор на карточке принтера —
    // второй модели нет намеренно, иначе они разъедутся. Связь обязана быть ФАКТИЧЕСКОЙ:
    // run -> его item -> assigned_printer_id -> состояние, требующее подтверждения.
    // IDLE/FINISH, свежесть телеметрии, имя и модель принтера пустой стол НЕ доказывают и в
    // определении цели не участвуют (они влияют только на то, можно ли нажать кнопку).
    const projectRunClearanceTargets = (r) => {
        if (!r || ['completed', 'cancelled'].includes(r.state)) return [];   // терминальный run целей не даёт
        const byId = {};
        for (const p of (r.printers || [])) byId[p.printer_id] = p;
        const out = [];
        const used = new Set();          // не больше ОДНОЙ цели на принтер; постпечатная приоритетнее
        for (const it of (r.items || [])) {
            if (it.state !== 'waiting_plate_clear' || !it.assigned_printer_id) continue;
            const p = byId[it.assigned_printer_id];
            if (!p || used.has(p.printer_id)) continue;      // принтера нет в снимке — угадывать нечего
            used.add(p.printer_id);
            out.push({ run_id: r.run_id, item: it, printer: p, initial: false,
                       finished_job_id: it.project_print_job_id || '' });
        }
        // Alpha 2.752 — ПЕРВИЧНАЯ цель: стол пуст ДО первой печати. Раньше цель существовала только
        // для waiting_plate_clear + assigned_printer_id, а перед первой печатью item ещё
        // pending/eligible и принтер не присвоен — кнопки «Стол очищен» не было вовсе, и /start
        // закономерно получал no_active_clearance. Точный принтер здесь уже известен: он сохранён
        // в item.feed_plan.printer_id, и цель строится ТОЛЬКО из готового (ready) плана — никаких
        // догадок по совместимости. Телеметрия clearance по-прежнему НЕ создаёт: это лишь кнопка.
        for (const it of (r.items || [])) {
            if (!['pending', 'eligible'].includes(it.state)) continue;
            const fp = it.feed_plan;
            if (!fp || fp.effective_status !== 'ready' || !fp.printer_id) continue;
            const p = byId[fp.printer_id];
            if (!p || used.has(p.printer_id)) continue;
            used.add(p.printer_id);
            out.push({ run_id: r.run_id, item: it, printer: p, initial: true,
                       finished_job_id: '' });               // '' -> initial clearance
        }
        return out;
    };
    // Тот же helper -> индикатор на карточке принтера. printer_id -> run_id.
    const projectRunPlateClearIds = computed(() => {
        const s = {};
        for (const r of projectRunsList.value)
            for (const t of projectRunClearanceTargets(r)) s[t.printer.printer_id] = r.run_id;
        return s;
    });
    const printerAwaitsPlateClear = (p) => {
        const pid = (p && typeof p === 'object') ? p.id : p;
        return !!(pid && projectRunPlateClearIds.value[pid]);
    };
    const focusPlateClearRun = (p) => {
        const pid = (p && typeof p === 'object') ? p.id : p;
        const rid = projectRunPlateClearIds.value[pid];
        if (rid) focusProjectRun(rid);
    };
    // 16.10.2026 (R-140): «Стол очищен» в пульте принтера — ОДНА кнопка на принтер, откуда бы ни шла
    // печать. Проектный запуск главнее: у него своё окно подтверждения (focusPlateClearRun). Иначе —
    // подтверждение очереди (queuePlateClear: спрашивает и шлёт {confirmed: true}). Вариант очереди —
    // только когда принтер ждёт подтверждения (plate_wait) И есть ради чего: он закончил печать, на нём
    // ждёт строка очереди или ему разрешён автозапуск. Иначе у каждого свободного разрешённого принтера
    // висела бы жёлтая кнопка, которая ничего не меняет.
    const ppPlateClearKind = (p) => {
        const pid = (p && typeof p === 'object') ? p.id : p;
        if (!pid) return '';
        if (printerAwaitsPlateClear(pid)) return 'project';
        const w = (queuePlateWait.value || []).find((x) => x.id === pid);
        if (!w) return '';
        const rowWaits = (queueWait.value || []).some((r) => r.match_printer_id === pid
            && r.state !== 'launching' && r.state !== 'starting');
        return (w.finished || rowWaits || (queueAutoOn.value && queueAutoPids.value.includes(pid))) ? 'queue' : '';
    };
    const ppPlateClear = (p) => {
        const k = ppPlateClearKind(p);
        const pid = (p && typeof p === 'object') ? p.id : p;
        if (k === 'project') focusPlateClearRun(p);
        else if (k === 'queue') queuePlateClear(pid);
    };
    // Нажать «Стол очищен» можно, только если backend ФАКТИЧЕСКИ это позволит. Локальная проверка —
    // лишь понятная подсказка; окончательное решение всегда за backend (409 показываем как есть).
    // Первичная цель (initial) строже постпечатной: до первой печати принтер обязан быть в
    // safe_idle. После FINISH этого требовать нельзя — FINISH по определению не safe_idle.
    // Backend авторитетно повторяет оба правила в create_clearance; здесь — только подсказка.
    const clearanceCanConfirm = (t) => !!t && !!t.printer.telemetry_fresh
        && !['RUNNING', 'PREPARE'].includes(t.printer.status) && !t.printer.clearance
        && (!t.initial || !!t.printer.safe_idle);
    const clearanceCanRevoke = (t) => !!(t && t.printer.clearance);   // отзывают только ДЕЙСТВУЮЩЕЕ
    const clearanceBlockReason = (t) => {
        const ru = lang.value === 'ru';
        if (!t) return '';
        if (!t.printer.telemetry_fresh) return ru ? 'Нет свежей телеметрии' : 'No fresh telemetry';
        if (['RUNNING', 'PREPARE'].includes(t.printer.status))
            return (ru ? 'Принтер занят: ' : 'Printer busy: ') + t.printer.status;
        if (t.initial && !t.printer.safe_idle)
            // Alpha 2.791: причина показывается понятным текстом, а не кодом/сырой строкой.
            return (ru ? 'Принтер не в безопасном простое: ' : 'Printer is not safely idle: ')
                + (t.printer.unsafe_reason ? readinessReasonText(t.printer.unsafe_reason)
                                           : (t.printer.status || '—'));
        if (t.printer.clearance) return ru ? 'Подтверждение уже действует' : 'Confirmation already active';
        return '';
    };
    // Честный текст состояния подтверждения. `clearance` — ТОЛЬКО действующее разрешение;
    // `last_clearance` — история и ПРИЧИНА. Молчаливое исчезновение подтверждения недопустимо:
    // оператор обязан видеть, что его подтверждение погибло при перезапуске сервера.
    const clearanceStateText = (t) => {
        const ru = lang.value === 'ru';
        if (!t) return '';
        if (t.printer.clearance) return ru ? 'Стол подтверждён' : 'Plate confirmed';
        const lc = t.printer.last_clearance;
        if (!lc) return ru ? 'Подтверждение ещё не создавалось' : 'No confirmation yet';
        if (lc.status === 'consumed') return ru ? 'Подтверждение использовано' : 'Confirmation used';
        if (lc.status === 'revoked') return ru ? 'Подтверждение отозвано' : 'Confirmation revoked';
        if (lc.status === 'invalidated')
            return lc.invalid_reason === 'server_restart'
                ? (ru ? 'Подтверждение недействительно после перезапуска сервера'
                      : 'Confirmation invalid after server restart')
                : (ru ? 'Подтверждение недействительно: ' : 'Confirmation invalid: ') + (lc.invalid_reason || '—');
        return ru ? 'Подтверждение ещё не создавалось' : 'No confirmation yet';
    };
    const projectRunAmbiguousItems = (r) =>
        ((r && r.items) || []).filter((it) => it.state === 'ambiguous_after_dispatch');
    // Подтверждение «Стол очищен» — утверждение о физическом мире, поэтому за confirm.
    const requestPlateClear = (run, t, ev) => _prOpenConfirm('clear', run, ev, { target: t });
    // Отзыв — движение в БЕЗОПАСНУЮ сторону (снимает разрешение), поэтому без лишнего барьера.
    const revokePlateClear = (run, t) => {
        if (!run || !t) return;
        return _prAction(run, 'revoke', '/api/project-runs/' + encodeURIComponent(run.run_id)
            + '/printers/' + encodeURIComponent(t.printer.printer_id) + '/plate-clear/revoke');
    };
    const requestResolveItem = (run, it, resolution, ev) =>
        _prOpenConfirm('resolve', run, ev, { target: { item: it }, resolution });

    // ══════════════════════════════════════════════════════════════════════════════════════════
    // UI-фаза 5A3b: «Источник материала» — выбор и подтверждение подачи (feed plan).
    // ЭТОТ UI НИЧЕГО НЕ ПЕЧАТАЕТ. Он работает ровно с четырьмя эндпоинтами 5A3a
    // (feed-candidates / feed-plan/select / feed-plan/approve / feed-plan/clear) и с уже
    // существующим снимком run. Ни /start, ни печати, ни отправки, ни планировщика, ни резервации,
    // ни подтверждения очистки стола он не касается — это разные вещи и разные кнопки.
    // ВСЯ арифметика (материал, ΔE, статусы, отпечаток) считается СЕРВЕРОМ: фронт только показывает.
    // ══════════════════════════════════════════════════════════════════════════════════════════
    const FEED_APPROVABLE = ['close_color', 'inventory_declared', 'manual_external']; // как backend
    const FEED_ACTIVE_STATES = ['leased', 'sending', 'waiting_start_confirmation', 'printing', 'waiting_plate_clear'];
    const feedWin = reactive({ open: false, runId: '', itemId: '', label: '', loading: false, error: '', data: null });
    const feedConfirm = reactive({ open: false, kind: '', cand: null, runId: '', itemId: '', checks: {} });
    const feedBusy = ref({});      // 'run|item' -> действие (action-lock: двойной клик => один POST)
    const feedNotice = ref({});    // 'run|item' -> сообщение об успехе (живёт в карточке item)
    const feedErrors = ref({});    // 'run|item' -> ошибка (живёт в карточке item, панель не ломает)
    let feedCtl = null, feedEsc = null, feedBtn = null, feedCfEsc = null, feedCfBtn = null;

    const feedKey = (runId, itemId) => String(runId || '') + '|' + String(itemId || '');
    const feedItemActive = (it) => !!it && FEED_ACTIVE_STATES.includes(it.state);
    const feedItemBusy = (runId, itemId) => !!feedBusy.value[feedKey(runId, itemId)];
    const feedItemNotice = (runId, itemId) => feedNotice.value[feedKey(runId, itemId)] || '';
    const feedItemError = (runId, itemId) => feedErrors.value[feedKey(runId, itemId)] || '';
    // Состояние блока «Источник материала» у item. Единственный источник истины — сам feed_plan из
    // снимка run: фронт статус не выводит и не пересчитывает.
    const feedBlockState = (it) => {
        if (!it) return 'none';
        const p = it.feed_plan;
        if (feedItemActive(it)) return p ? 'readonly' : 'readonly-none';   // печать уже пошла — только чтение
        if (!p) return 'none';
        if (p.reason === 'feed_plan_corrupt') return 'corrupt';
        const eff = p.effective_status;
        if (eff === 'ready') return 'ready';
        if (eff === 'approval_required') return 'approval';
        if (p.status === 'blocked') return 'blocked';
        return 'attention';
    };
    // Подпись слота. Глобальный индекс строится как unit*4 + tray (так его собирает парсер отчётов),
    // поэтому 512 — это unit 128, а НЕ «слот 513». Внешняя катушка — отдельная позиция -1, не AMS 0.
    //  16.10.2026 (R-137): -2 — левая внешняя катушка H2D (Bambu 254); у двухсопельного -1 — правая (255).
    const feedSlotLabel = (slot, pid) => {
        const ru = lang.value === 'ru';
        if (slot === null || slot === undefined || slot === '') return ru ? 'Слот не назначен' : 'No slot';
        const n = Number(slot);
        if (n === -2) return ru ? 'Левая внешняя катушка' : 'Left external spool';
        if (n === -1) {
            //  Подпись не должна ронять отрисовку: нет данных о принтере — нейтральное «Внешняя катушка».
            let dual = false;
            try { dual = !!pid && Number((wsData.value[pid] || {}).nozzle_count || 1) >= 2; } catch (e) { dual = false; }
            return dual ? (ru ? 'Правая внешняя катушка' : 'Right external spool') : (ru ? 'Внешняя катушка' : 'External spool');
        }
        if (!Number.isFinite(n) || n < 0) return ru ? 'Слот не назначен' : 'No slot';
        const unit = Math.floor(n / 4), tray = (n % 4) + 1;
        return (unit === 128 ? 'AMS HT' : 'AMS ' + (unit + 1)) + '·' + tray;
    };
    // Цвет — ТОЛЬКО через существующий safeHex: сырой текст в style не попадает никогда.
    const feedSwatch = (hex) => {
        const h = safeHex(hex);
        return h ? { background: h } : {};
    };
    const feedSwatchOk = (hex) => !!safeHex(hex);
    const feedHexText = (hex) => safeHex(hex) || (lang.value === 'ru' ? 'не задан' : 'not set');
    const feedDeltaText = (c) => {
        const d = c && c.color_distance;
        return (typeof d === 'number') ? ('ΔE ' + d.toFixed(2)) : '';
    };
    const feedRelText = (rel) => {
        const ru = lang.value === 'ru';
        if (rel === 'exact') return ru ? 'Цвет совпадает точно' : 'Exact colour match';
        if (rel === 'close') return ru ? 'Цвет близкий, но не точный' : 'Close, not exact colour';
        if (rel === 'mismatch') return ru ? 'Цвет не совпадает' : 'Colour mismatch';
        return ru ? 'Цвет не сравнивался' : 'Colour not compared';
    };
    const feedVerifyText = (v) => {
        const ru = lang.value === 'ru';
        if (v === 'telemetry_confirmed') return ru ? 'Подтверждено датчиком принтера' : 'Confirmed by printer sensor';
        if (v === 'manual_external') return ru ? 'Внешняя катушка подтверждается оператором' : 'External spool is confirmed by the operator';
        return ru ? 'Заявлено привязкой склада' : 'Declared by inventory binding';
    };
    // Alpha 2.792: ЕДИНСТВЕННАЯ таблица представления статусов анализа плана.
    // До 2.792 бейдж печатал код backend как есть ({{ c.effective_status }}), а сводка
    // сверху имела СВОИ рукописные подписи — две несогласованные таблицы. Теперь и бейдж,
    // и сводка берут подпись отсюда. Коды backend (ready / approval_required /
    // attention_required / blocked) НЕ меняются: это машинный контракт, его разбирают тесты.
    // Здесь только представление — решения о безопасности и о выбираемости варианта
    // принимает backend, таблица на них не влияет.
    const FEED_STATUS_VIEW = {
        ready:              { ru: 'Готов',               en: 'Ready',                 sum_ru: 'готовы',           sum_en: 'ready',                 cls: 'ok'   },
        approval_required:  { ru: 'Нужно подтверждение', en: 'Confirmation required', sum_ru: 'нужно подтвердить', sum_en: 'confirmation required', cls: 'warn' },
        attention_required: { ru: 'Требуется настройка', en: 'Setup required',        sum_ru: 'требуют настройки', sum_en: 'setup required',        cls: 'warn' },
        blocked:            { ru: 'Недоступен',          en: 'Unavailable',           sum_ru: 'недоступны',        sum_en: 'unavailable',           cls: 'bad'  },
    };
    // Незнакомый код НЕ показываем сырым snake_case и НЕ прячем: даём понятную подпись,
    // а сам код оставляем в подсказке title — он нужен для диагностики, но не оператору.
    const feedStatusInfo = (code) => {
        const ru = lang.value === 'ru';
        const v = FEED_STATUS_VIEW[String(code || '')];
        if (!v) return { label: ru ? 'Неизвестное состояние' : 'Unknown state', cls: 'warn', code: String(code || ''), known: false };
        return { label: ru ? v.ru : v.en, cls: v.cls, code: String(code), known: true };
    };
    const feedStatusLabel = (code) => feedStatusInfo(code).label;
    const feedStatusClass = (code) => feedStatusInfo(code).cls;
    // Подписи сводки берутся из ТОЙ ЖЕ таблицы — расхождение бейджа и сводки исключено.
    const feedSummaryLabel = (code) => {
        const ru = lang.value === 'ru';
        const v = FEED_STATUS_VIEW[String(code || '')];
        if (!v) return ru ? 'прочие' : 'other';
        return ru ? v.sum_ru : v.sum_en;
    };

    // Канонические причины backend -> человеческий текст. Неизвестный код показываем КАК ЕСТЬ:
    // выдумывать перевод опаснее, чем показать сырой код.
    const feedReasonText = (code) => {
        const ru = lang.value === 'ru';
        const M = {
            run_not_running: [ 'План сейчас не в работе (приостановлен или ждёт решения). Продолжите план и повторите запуск.',
                               'The plan is not active right now (paused or awaiting a decision). Resume the plan and retry.' ],
            close_color: [ 'Цвет близкий, но не совпадает точно.', 'Colour is close but not an exact match.' ],
            inventory_declared: [ 'Катушка указана привязкой склада, но её материал и цвет не подтверждены датчиком принтера.',
                                  'The spool is declared by an inventory binding, but its material and colour are not confirmed by the printer sensor.' ],
            manual_external: [ 'FlashForge работает с внешней катушкой без складской привязки. Подтвердите, что на принтере действительно установлены материал и цвет, указанные в файле.',
                               'FlashForge uses an external spool without an inventory binding. Confirm that the material and colour specified by the file are actually loaded.' ],
            material_mismatch: [ 'Материал катушки не совпадает с материалом файла.', 'Spool material does not match the file.' ],
            color_mismatch: [ 'Цвет отличается слишком сильно.', 'Colour differs too much.' ],
            material_unknown: [ 'Материал катушки не заполнен в складе.', 'Spool material is not filled in inventory.' ],
            color_unknown: [ 'Цвет не удалось сравнить.', 'Colour could not be compared.' ],
            reported_material_mismatch: [ 'Принтер сообщает не тот материал, что записан в складе.',
                                          'The printer reports a different material than inventory records.' ],
            slot_empty: [ 'Слот пуст по данным принтера.', 'The slot is empty according to the printer.' ],
            telemetry_stale: [ 'Данные принтера устарели.', 'Printer data is stale.' ],
            inventory_source_unavailable: [ 'Нет привязанной складской катушки.', 'No bound inventory spool.' ],
            multi_filament_not_supported: [ 'Файл с несколькими филаментами пока не поддерживается.',
                                            'Multi-filament files are not supported yet.' ],
            filament_count_unknown: [ 'Не удалось определить число филаментов в файле.', 'Cannot determine filament count.' ],
            file_material_unknown: [ 'В файле не указан материал.', 'The file does not specify a material.' ],
            file_color_unknown: [ 'В файле не указан цвет.', 'The file does not specify a colour.' ],
            file_missing: [ 'Файл не найден на диске.', 'File not found on disk.' ],
            file_hash_changed: [ 'Файл изменился после планирования.', 'The file changed after planning.' ],
            file_unreadable: [ 'Файл не читается.', 'File cannot be read.' ],
            feed_plan_corrupt: [ 'Сохранённый план подачи повреждён. Выполните повторный подбор.',
                                 'The stored feed plan is corrupt. Please re-run the selection.' ],
            feed_plan_stale: [ 'Данные материала или принтера изменились. Обновите кандидатов.',
                               'Material or printer data changed. Refresh the candidates.' ],
            feed_plan_approval_required: [ 'Требуется подтверждение оператора.', 'Operator confirmation required.' ],
            approval_incomplete: [ 'Подтверждены не все причины.', 'Not all reasons were confirmed.' ],
            item_already_active: [ 'Печать этой плиты уже началась — источник менять поздно.',
                                   'This plate is already printing — the source can no longer be changed.' ],
            printer_incompatible: [ 'Принтер несовместим с этим файлом.', 'Printer is incompatible with this file.' ],
            candidate_not_found: [ 'Такой катушки в этом слоте больше нет.', 'That spool is no longer in that slot.' ],
        };
        const t = M[code];
        return t ? (ru ? t[0] : t[1]) : String(code || '');
    };
    const feedPlanReasons = (it) => {
        const p = it && it.feed_plan;
        return (p && p.required_approval_reasons) || [];
    };

    // ── Окно «Источник материала» ─────────────────────────────────────────────────────────────
    const feedCandidates = computed(() => (feedWin.data && feedWin.data.candidates) || []);
    const feedSummary = computed(() => (feedWin.data && feedWin.data.summary) || null);
    // Кандидатов НЕ пересортировываем: порядок задаёт backend (ranking 5A2a), и второй модели быть
    // не должно — иначе UI и планировщик покажут/выберут разное.
    const loadFeedCandidates = async () => {
        if (feedCtl) { try { feedCtl.abort(); } catch (e) {} }   // refresh отменяет предыдущий GET
        const ac = new AbortController(); feedCtl = ac;
        feedWin.loading = true; feedWin.error = '';
        try {
            const r = await fetch('/api/project-runs/' + encodeURIComponent(feedWin.runId)
                + '/items/' + encodeURIComponent(feedWin.itemId) + '/feed-candidates', { signal: ac.signal });
            const j = await r.json().catch(() => ({}));
            if (!r.ok || (j && j.status === 'error')) throw new Error((j && j.reason) || ('http ' + r.status));
            if (feedCtl !== ac) return;                          // ответ отменённого запроса игнорируем
            feedWin.data = j;
        } catch (e) {
            if (e && e.name === 'AbortError') return;            // штатная отмена — не ошибка, не показываем
            feedWin.error = feedReasonText(String((e && e.message) || e));
        } finally {
            if (feedCtl === ac) { feedCtl = null; feedWin.loading = false; }
        }
    };
    const openFeedWindow = (run, it, ev) => {
        try { feedBtn = (ev && ev.currentTarget) || null; } catch (e) { feedBtn = null; }
        feedWin.runId = (run && run.run_id) || ''; feedWin.itemId = (it && it.item_id) || '';
        feedWin.label = (it && it.file_id) || '';
        feedWin.data = null; feedWin.error = ''; feedWin.open = true;
        if (!feedEsc) feedEsc = registerEscapeLayer(closeFeedWindow);
        return loadFeedCandidates();
    };
    const closeFeedWindow = () => {
        if (feedCtl) { try { feedCtl.abort(); } catch (e) {} feedCtl = null; }
        feedWin.open = false; feedWin.data = null; feedWin.error = ''; feedWin.loading = false;
        if (feedEsc) { unregisterEscapeLayer(feedEsc); feedEsc = null; }
        const b = feedBtn; feedBtn = null;
        nextTick(() => { try { if (b && b.focus) b.focus(); } catch (e) {} });
    };
    const refreshFeedCandidates = () => loadFeedCandidates();

    // Кнопки — по ФАКТИЧЕСКОМУ ответу backend. Окончательное решение всё равно за ним (409 показываем).
    const feedCanSelect = (c) => !!c && c.effective_status === 'ready'
        && !((c.required_approval_reasons || []).length);
    const feedCanApprove = (c) => !!c && c.status === 'approval_required'
        && c.effective_status !== 'ready' && !!((c.required_approval_reasons || []).length);

    // Обновление снимка run после действия: ОДИН существующий GET деталей. Второго таймера не
    // создаём — периодический опрос B1 остаётся единственным.
    const refreshFeedRun = async (runId) => {
        try {
            const d = await _prFetchDetail(runId);
            if (d && d.run_id) {
                const prev = projectRunsById.value[runId] || {};
                mergeProjectRun(Object.assign({}, prev, d, { project_name: prev.project_name }));
            }
        } catch (e) { /* не удалось обновить — действие всё равно состоялось, покажет обычный тик */ }
    };
    const _feedPost = async (runId, itemId, kind, path, body) => {
        const k = feedKey(runId, itemId);
        if (feedBusy.value[k]) return null;                      // action-lock: второй POST не уходит
        feedBusy.value = Object.assign({}, feedBusy.value, { [k]: kind });
        feedErrors.value = Object.assign({}, feedErrors.value, { [k]: '' });
        try {
            const r = await fetch('/api/project-runs/' + encodeURIComponent(runId)
                + '/items/' + encodeURIComponent(itemId) + '/feed-plan/' + path, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
            });
            const j = await r.json().catch(() => ({}));
            if (!r.ok || (j && j.status === 'error')) {
                const reason = (j && j.reason) || ('http ' + r.status);
                return { ok: false, reason, data: j };
            }
            await refreshFeedRun(runId);
            return { ok: true, data: j };
        } catch (e) {
            return { ok: false, reason: String((e && e.message) || e), data: null };
        } finally {
            const b = Object.assign({}, feedBusy.value); delete b[k]; feedBusy.value = b;
        }
    };
    const _feedFail = (runId, itemId, reason) => {
        feedErrors.value = Object.assign({}, feedErrors.value, { [feedKey(runId, itemId)]: feedReasonText(reason) });
        if (reason === 'item_already_active') refreshFeedRun(runId);   // блок сам станет read-only
        if (feedWin.open && (reason === 'feed_plan_stale' || reason === 'approval_incomplete')) {
            feedWin.error = feedReasonText(reason);                    // окно НЕ закрываем: нужен refresh
        } else if (feedWin.open) {
            closeFeedWindow();
        }
    };
    const _feedOk = (runId, itemId, msg) => {
        feedNotice.value = Object.assign({}, feedNotice.value, { [feedKey(runId, itemId)]: msg });
        if (feedWin.open) closeFeedWindow();
    };
    // Тело запроса — ТОЛЬКО факты выбора. Материал/цвет/статус не шлём: сервер им всё равно не верит.
    const feedBody = (c, extra) => Object.assign({
        printer_id: c.printer_id, ams_slot: c.ams_slot, spool_id: c.spool_id,
        expected_fingerprint: c.fingerprint,
    }, extra || {});
    const selectFeedCandidate = async (c) => {
        if (!c || !feedCanSelect(c)) return;
        const runId = feedWin.runId, itemId = feedWin.itemId;
        const r = await _feedPost(runId, itemId, 'select', 'select', feedBody(c));
        if (!r) return;
        if (!r.ok) return _feedFail(runId, itemId, r.reason);
        _feedOk(runId, itemId, lang.value === 'ru'
            ? 'Источник материала сохранён. Печать ещё не запускается.'
            : 'Material source saved. Printing does not start yet.');
    };

    // ── Подтверждение: отдельный styled confirm ВЫШЕ окна кандидатов. native confirm() не
    //    используем. Причин может быть ДВЕ (близкий цвет И источник без датчика) — на каждую
    //    отдельная галочка: это разные риски, и согласие должно быть на каждый явно.
    const feedConfirmReasons = computed(() => {
        const c = feedConfirm.cand;
        return (c && c.required_approval_reasons) || [];
    });
    const feedConfirmUnknown = computed(() =>
        feedConfirmReasons.value.filter((r) => !FEED_APPROVABLE.includes(r)));
    const feedApproveReady = computed(() => {
        const req = feedConfirmReasons.value;
        if (!req.length) return false;
        if (feedConfirmUnknown.value.length) return false;      // неизвестную причину UI не подтверждает
        return req.every((r) => feedConfirm.checks[r] === true);
    });
    const requestFeedApprove = (c, ev) => {
        if (!c || !feedCanApprove(c)) return;
        try { feedCfBtn = (ev && ev.currentTarget) || null; } catch (e) { feedCfBtn = null; }
        const ch = {};
        for (const r of (c.required_approval_reasons || [])) ch[r] = false;   // по умолчанию ВЫКЛЮЧЕНЫ
        feedConfirm.kind = 'approve'; feedConfirm.cand = c;
        feedConfirm.runId = feedWin.runId; feedConfirm.itemId = feedWin.itemId;
        feedConfirm.checks = ch; feedConfirm.open = true;
        if (!feedCfEsc) feedCfEsc = registerEscapeLayer(closeFeedConfirm);
    };
    const requestFeedClear = (run, it, ev) => {
        if (!run || !it || feedItemActive(it)) return;
        try { feedCfBtn = (ev && ev.currentTarget) || null; } catch (e) { feedCfBtn = null; }
        feedConfirm.kind = 'clear'; feedConfirm.cand = null;
        feedConfirm.runId = run.run_id; feedConfirm.itemId = it.item_id;
        feedConfirm.checks = {}; feedConfirm.open = true;
        if (!feedCfEsc) feedCfEsc = registerEscapeLayer(closeFeedConfirm);
    };
    const closeFeedConfirm = () => {
        feedConfirm.open = false; feedConfirm.kind = ''; feedConfirm.cand = null;
        feedConfirm.runId = ''; feedConfirm.itemId = ''; feedConfirm.checks = {};
        if (feedCfEsc) { unregisterEscapeLayer(feedCfEsc); feedCfEsc = null; }
        const b = feedCfBtn; feedCfBtn = null;
        nextTick(() => { try { if (b && b.focus) b.focus(); } catch (e) {} });
    };
    const toggleFeedReason = (code) => {
        feedConfirm.checks = Object.assign({}, feedConfirm.checks, { [code]: !feedConfirm.checks[code] });
    };
    const confirmFeedApprove = async () => {
        const c = feedConfirm.cand, runId = feedConfirm.runId, itemId = feedConfirm.itemId;
        if (!c || !feedApproveReady.value) return;
        // approved_reasons формируем ТОЛЬКО из перечня backend. approved_by не шлём никогда:
        // подпись под решением ставит сервер по своей сессии.
        const reasons = (c.required_approval_reasons || []).slice();
        closeFeedConfirm();
        const r = await _feedPost(runId, itemId, 'approve', 'approve',
            feedBody(c, { confirmed: true, approved_reasons: reasons }));
        if (!r) return;
        if (!r.ok) return _feedFail(runId, itemId, r.reason);
        _feedOk(runId, itemId, lang.value === 'ru'
            ? 'Источник материала подтверждён. Печать ещё не запускается.'
            : 'Material source confirmed. Printing does not start yet.');
    };
    // ══════════════════════════════════════════════════════════════════════════════════════════
    // UI-фаза 5B2a: КОНТРОЛЬНЫЙ ЗАПУСК ОДНОЙ ПЕЧАТИ. Это НЕ автозапуск и слова «Автозапуск» здесь
    // нет намеренно: один ручной запуск, вооружённый оператором из командной строки, у принтера.
    // Кнопка вообще не существует, пока сервер не сообщит, что этот запуск вооружён РОВНО на эту
    // пару run/item/printer. Ни таймеров, ни повторов: опрос делает только GET.
    // ══════════════════════════════════════════════════════════════════════════════════════════
    const armStatus = ref(null);          // ответ /transport-status; null = ещё не спрашивали
    const startConfirm = reactive({ open: false, run: null, item: null, cand: null, checks: {} });
    const startBusy = ref({});            // 'run|item' -> true (action-lock: двойной клик => один POST)
    const startNotice = ref({});          // 'run|item' -> честный текст исхода
    const startUnknown = ref({});         // 'run|item' -> ответ потерян: повторять НЕЛЬЗЯ
    let startCfEsc = null, startCfBtn = null;
    // Четыре отдельных утверждения о ФИЗИЧЕСКОМ мире. Одной галочкой их закрыть нельзя: это разные
    // проверки, и человек должен подтвердить каждую сам.
    const START_CHECKS = ['plate_empty', 'printer_ok', 'spool_ok', 'nearby'];
    const startCheckText = (k) => {
        const ru = lang.value === 'ru';
        const M = {
            plate_empty: ['Я физически проверил: стол пуст и распечатанные детали сняты.',
                          'I physically checked: the plate is empty and printed parts are removed.'],
            printer_ok: ['Принтер исправен, находится в безопасном состоянии и готов к запуску.',
                         'The printer is healthy, in a safe state and ready to start.'],
            spool_ok: ['Катушка и указанная позиция подачи проверены.',
                       'The spool and the specified feed position are verified.'],
            nearby: ['Я нахожусь рядом с принтером и понимаю, что будет отправлена одна реальная печать.',
                     'I am next to the printer and understand that one real print will be sent.'],
        };
        return (M[k] || ['', ''])[ru ? 0 : 1];
    };
    const startKey = (runId, itemId) => String(runId || '') + '|' + String(itemId || '');
    const startItemBusy = (runId, itemId) => !!startBusy.value[startKey(runId, itemId)];
    const startItemNotice = (runId, itemId) => startNotice.value[startKey(runId, itemId)] || '';
    const startItemUnknown = (runId, itemId) => !!startUnknown.value[startKey(runId, itemId)];
    // Статус вооружения — ТОЛЬКО чтение. Опрашивается вместе с обычным тиком панели; POST не делает.
    const loadArmStatus = async (signal) => {
        try {
            const r = await fetch('/api/project-orchestrator/transport-status', { signal });
            if (!r.ok) throw new Error('http ' + r.status);
            armStatus.value = await r.json();
        } catch (e) {
            if (!(e && e.name === 'AbortError')) armStatus.value = null;   // не знаем -> считаем невооружённым
        }
    };
    const armScope = computed(() => (armStatus.value && armStatus.value.scope) || null);
    const armReady = computed(() => !!(armStatus.value && armStatus.value.armed && !armStatus.value.consumed));
    // Три значения optimistic-lock — ТОЛЬКО из текущего detail-снимка (GET /api/project-runs/{id}).
    // Alpha 2.749: fallback'а нет и быть не может. Раньше item.updated_at не приходил вовсе, здесь
    // получался undefined, JSON.stringify выбрасывал ключ, и сервер молча пропускал проверку
    // устаревшего экрана. Подставить сюда Date.now()/run.updated_at/created_at/0 нельзя: это
    // означало бы «подтверждаю версию, которой не видел».
    const startVersions = (r, it) => {
        const p = it && it.feed_plan;
        const num = (v) => typeof v === 'number' && isFinite(v);
        if (!r || !it || !p) return null;
        if (!num(r.updated_at) || !num(it.updated_at)) return null;
        if (typeof p.fingerprint !== 'string' || !p.fingerprint) return null;
        return { run: r.updated_at, item: it.updated_at, fp: p.fingerprint };
    };
    // Вооружение и scope совпали, а версии снимка получить не удалось -> честная постоянная ошибка
    // вместо кнопки. Показываем её ТОЛЬКО у той детали, на которую вооружились: у остальных этого
    // блока и так нет.
    const startVersionBlocked = (r, it) => {
        if (!armReady.value || !armScope.value || !r || !it) return false;
        if (armScope.value.run_id !== r.run_id || armScope.value.item_id !== it.item_id) return false;
        return !startVersions(r, it);
    };
    // Кнопка появляется, ТОЛЬКО если совпало всё сразу. Любое несовпадение — кнопки нет вовсе.
    const canControlledStart = (r, it) => {
        if (!armReady.value || !armScope.value) return false;
        if (!r || !it || feedItemActive(it)) return false;
        // 2.769 (аудит): backend принимает старт только в этих состояниях run — на paused/attention
        // кнопка давала 409 run_not_running сырым кодом рядом с «Продолжить план».
        if (!['draft', 'running', 'waiting_for_printer'].includes(r.state)) return false;
        if (armScope.value.run_id !== r.run_id || armScope.value.item_id !== it.item_id) return false;
        const p = it.feed_plan;
        if (!p || p.effective_status !== 'ready') return false;
        if (armScope.value.printer_id !== p.printer_id) return false;   // принтер плана обязан совпасть
        if (!startVersions(r, it)) return false;      // нет версии снимка -> запуск невозможен
        return ['pending', 'eligible'].includes(it.state);
    };
    const startApproveReady = computed(() => START_CHECKS.every((k) => startConfirm.checks[k] === true));
    const toggleStartCheck = (k) => {
        startConfirm.checks = Object.assign({}, startConfirm.checks, { [k]: !startConfirm.checks[k] });
    };
    const requestControlledStart = (r, it, ev) => {
        if (!canControlledStart(r, it) || startItemBusy(r.run_id, it.item_id)) return;
        try { startCfBtn = (ev && ev.currentTarget) || null; } catch (e) { startCfBtn = null; }
        const ch = {};
        for (const k of START_CHECKS) ch[k] = false;      // все ЧЕТЫРЕ по умолчанию выключены
        startConfirm.run = r; startConfirm.item = it; startConfirm.cand = it.feed_plan;
        startConfirm.checks = ch; startConfirm.open = true;
        if (!startCfEsc) startCfEsc = registerEscapeLayer(closeStartConfirm);
    };
    const closeStartConfirm = () => {
        startConfirm.open = false; startConfirm.run = null; startConfirm.item = null;
        startConfirm.cand = null; startConfirm.checks = {};
        if (startCfEsc) { unregisterEscapeLayer(startCfEsc); startCfEsc = null; }
        const b = startCfBtn; startCfBtn = null;
        nextTick(() => { try { if (b && b.focus) b.focus(); } catch (e) {} });
    };
    // ОБЩАЯ отправка контрольного запуска (POST /start). Одна логика для обоих путей: старого
    // CLI-вооружённого (четыре галочки) и простого «печать из приложения» (одно подтверждение).
    // Тело — ТОЛЬКО canonical optimistic-lock из ПРОВЕРЕННОГО снимка; принтер/слот сервер берёт из
    // плана сам. Потеря ответа -> повтор запрещён (блокировка не снимается). action-lock от двойного POST.
    const _sendControlledStart = async (r, it) => {
        if (!r || !it) return;
        const k = startKey(r.run_id, it.item_id);
        if (startBusy.value[k]) return;                   // action-lock: второй POST не уходит
        const ru = lang.value === 'ru';
        const ver = startVersions(r, it);                 // перечитываем версии ПРЯМО ПЕРЕД отправкой
        if (!ver) {
            startNotice.value = Object.assign({}, startNotice.value, { [k]: ru
                ? 'Не удалось получить версию плана. Обновите данные; запуск заблокирован.'
                : 'Could not read the plan version. Refresh the data; the start is blocked.' });
            return;
        }
        startBusy.value = Object.assign({}, startBusy.value, { [k]: true });
        startNotice.value = Object.assign({}, startNotice.value, { [k]: '' });
        const body = { confirmed: true, item_id: it.item_id,
                       expected_run_updated_at: ver.run, expected_item_updated_at: ver.item,
                       expected_feed_fingerprint: ver.fp };
        let lost = false;
        try {
            const resp = await fetch('/api/project-runs/' + encodeURIComponent(r.run_id) + '/start', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
            });
            const j = await resp.json().catch(() => ({}));
            if (!resp.ok || (j && j.status === 'error')) {
                startNotice.value = Object.assign({}, startNotice.value,
                    { [k]: feedReasonText((j && j.reason) || ('http ' + resp.status)) });
            } else {
                // Команда ПРИНЯТА транспортом — это ещё НЕ «печать началась». Старт подтверждает
                // только телеметрия принтера, и до неё в панели будет waiting_start_confirmation.
                startNotice.value = Object.assign({}, startNotice.value, { [k]: ru
                    ? 'Команда отправлена. Ожидается подтверждение старта от принтера.'
                    : 'Command sent. Awaiting start confirmation from the printer.' });
            }
        } catch (e) {
            // Ответ потерян (сеть/таймаут). Команда МОГЛА уйти — повторять НЕЛЬЗЯ.
            lost = true;
            startUnknown.value = Object.assign({}, startUnknown.value, { [k]: true });
            startNotice.value = Object.assign({}, startNotice.value, { [k]: ru
                ? 'Результат отправки неизвестен. Не повторяйте запуск; дождитесь обновления состояния плана и проверьте принтер.'
                : 'The send result is unknown. Do not retry; wait for the plan state to refresh and check the printer.' });
        }
        // Блокировку снимаем ТОЛЬКО после авторитетного снимка сервера (или окончательного отказа).
        try { await refreshFeedRun(r.run_id); } catch (e) {}
        await loadArmStatus();
        if (!lost) {
            const b = Object.assign({}, startBusy.value); delete b[k]; startBusy.value = b;
        }
    };
    // Старый путь: четыре галочки (CLI-вооружение / помощник).
    const confirmControlledStart = async () => {
        const r = startConfirm.run, it = startConfirm.item;
        if (!r || !it || !startApproveReady.value) return;
        closeStartConfirm();
        return _sendControlledStart(r, it);
    };

    // ── Alpha 2.757: печать проектов ИЗ ПРИЛОЖЕНИЯ. Владелец включает реальную отправку один раз
    // (персистентно), дальше — кнопка «Запустить печать» + ОДНО подтверждение. Без командной строки,
    // без четырёх галочек. Каждая отправка по-прежнему требует: подтверждения человеком, безопасного
    // простоя принтера, действующего подтверждения стола, свежих версий снимка. ──
    const printEnabled = computed(() => !!(armStatus.value && armStatus.value.print_enabled));
    const printEnableBusy = ref(false);
    const setPrintEnabled = async (on) => {
        if (printEnableBusy.value) return;
        printEnableBusy.value = true;
        try {
            await fetch('/api/project-orchestrator/print-enabled', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: !!on }),
            });
            await loadArmStatus();
        } catch (e) { /* следующий тик статуса поправит */ } finally {
            printEnableBusy.value = false;
        }
    };
    // Кнопка «Запустить печать» доступна ТОЛЬКО для ТЕКУЩЕГО запуска, когда: печать из приложения
    // включена, план готов, версии снимка есть, стол подтверждён, принтер плана в безопасном простое.
    const canStartInApp = (r, it) => {
        if (!printEnabled.value || !r || !it || feedItemActive(it)) return false;
        if (!['draft', 'running', 'waiting_for_printer'].includes(r.state)) return false;   // 2.769: как guard бэкенда
        if (!['pending', 'eligible'].includes(it.state)) return false;
        const p = it.feed_plan;
        if (!p || p.effective_status !== 'ready' || !p.printer_id) return false;
        if (!startVersions(r, it)) return false;
        const t = wpxItemClearance(r, it);
        if (!t || !t.printer.clearance) return false;     // стол должен быть подтверждён пустым
        const pr = ((r.printers || []).find((x) => x.printer_id === p.printer_id));
        return !!(pr && pr.safe_idle);                    // принтер в безопасном простое
    };
    const inAppConfirm = reactive({ open: false, run: null, item: null });
    let _inAppEsc = null, _inAppBtn = null;
    const closeInAppStartConfirm = () => {
        inAppConfirm.open = false;
        if (_inAppEsc) { unregisterEscapeLayer(_inAppEsc); _inAppEsc = null; }
        const b = _inAppBtn; _inAppBtn = null;
        nextTick(() => { try { if (b && b.focus) b.focus(); } catch (e) {} });
    };
    const requestInAppStart = (r, it, ev) => {
        if (!canStartInApp(r, it) || startItemBusy(r.run_id, it.item_id)) return;
        try { _inAppBtn = (ev && ev.currentTarget) || null; } catch (e) { _inAppBtn = null; }
        inAppConfirm.run = r; inAppConfirm.item = it; inAppConfirm.open = true;
        if (!_inAppEsc) _inAppEsc = registerEscapeLayer(closeInAppStartConfirm);
    };
    const confirmInAppStart = async () => {
        const r = inAppConfirm.run, it = inAppConfirm.item;
        if (!r || !it || !canStartInApp(r, it)) { closeInAppStartConfirm(); return; }
        closeInAppStartConfirm();
        return _sendControlledStart(r, it);
    };
    const inAppStartFacts = computed(() => {
        const it = inAppConfirm.item, r = inAppConfirm.run;
        if (!it || !r) return null;
        const p = it.feed_plan || {};
        return { file: (it.filename || it.file_id || ''),
                 printer: wpxPrinterName(r, it),
                 material: wpxMaterialLine(it) };
    });

    const confirmFeedClear = async () => {
        const runId = feedConfirm.runId, itemId = feedConfirm.itemId;
        if (!runId || !itemId) return;
        closeFeedConfirm();
        const r = await _feedPost(runId, itemId, 'clear', 'clear', { confirmed: true });
        if (!r) return;
        if (!r.ok) return _feedFail(runId, itemId, r.reason);
        feedNotice.value = Object.assign({}, feedNotice.value, { [feedKey(runId, itemId)]:
            lang.value === 'ru' ? 'Выбор источника сброшен.' : 'Material source selection cleared.' });
    };

    // Тексты confirm по виду действия. Ни один из них не утверждает, что печать запущена.
    const projectRunConfirmTitle = computed(() => {
        const ru = lang.value === 'ru', k = projectRunConfirm.kind;
        if (k === 'clear') return ru ? 'Подтвердить очистку стола' : 'Confirm plate cleared';
        if (k === 'resolve') return projectRunConfirm.resolution === 'started'
            ? (ru ? 'Печать началась?' : 'Print started?') : (ru ? 'Печать не начиналась?' : 'Print not started?');
        return ru ? 'Отменить план' : 'Cancel plan';
    });
    const projectRunConfirmText = computed(() => {
        const ru = lang.value === 'ru', k = projectRunConfirm.kind, t = projectRunConfirm.target;
        if (k === 'clear') {
            const nm = (t && t.printer && (t.printer.name || t.printer.printer_id)) || '';
            return ru ? ('Подтвердите, что стол принтера «' + nm + '» физически пуст и детали сняты. '
                       + 'Программа проверить это не может: IDLE и FINISH пустой стол не доказывают.')
                      : ('Confirm that the plate of "' + nm + '" is physically empty and parts are removed. '
                       + 'The software cannot verify this: IDLE and FINISH do not prove an empty plate.');
        }
        if (k === 'resolve') return projectRunConfirm.resolution === 'started'
            ? (ru ? 'Подтвердите, что печать этого задания фактически началась. Это решение принимает человек — программа доказать его не может.'
                  : 'Confirm that this job actually started printing. Only a human can make this decision.')
            : (ru ? 'Подтвердите, что печать этого задания не начиналась. Автоматический повтор не выполняется.'
                  : 'Confirm that this job never started. No automatic retry will be performed.');
        return ru ? 'Отменить сохранённый план проекта? Это не отправит команду остановки принтерам.'
                  : 'Cancel the saved project plan? This will NOT send a stop command to printers.';
    });
    const projectRunConfirmOk = computed(() => {
        const ru = lang.value === 'ru', k = projectRunConfirm.kind;
        if (k === 'clear') return ru ? 'Да, стол очищен' : 'Yes, plate is clear';
        if (k === 'resolve') return projectRunConfirm.resolution === 'started'
            ? (ru ? 'Печать началась' : 'Print started') : (ru ? 'Печать не начиналась' : 'Print not started');
        return ru ? 'Отменить план' : 'Cancel plan';
    });

    const closeActiveModule = () => { activeModuleId.value = ''; activeModuleProps.value = {}; };
    const disabledModules = computed(() => installedModules.value.filter((m) => m.disabled));
    const disableModule = async (l) => {
        if (moduleBusy.value) return;
        const nm = lang.value === 'ru' ? l.ru : l.en;
        if (!await askConfirm({ title: _L('Отключить модуль «' + nm + '»?', 'Disable module "' + nm + '"?'),
                                text: _L('Его плитки исчезнут, данные сохранятся. Полное выключение — после перезапуска программы.',
                                         'Its tiles will be hidden; data is kept. Restart completes the shutdown.'),
                                okText: _L('Отключить', 'Disable') })) return;
        moduleBusy.value = true;
        try {
            const r = await fetch('/api/modules/' + l.moduleId + '/disable', { method: 'POST' });
            const j = await r.json().catch(() => ({}));
            if (j.status === 'ok') {
                if (activeModuleId.value === l.moduleId) closeActiveModule();
                moduleInstallMsg.value = { ok: true, text: lang.value === 'ru' ? 'Модуль отключён (полностью выключится после перезапуска).' : 'Module disabled (restart completes the shutdown).' };
            } else {
                moduleInstallMsg.value = { ok: false, text: (lang.value === 'ru' ? 'Не удалось отключить: ' : 'Disable failed: ') + (j.reason || '\u2014') };
            }
        } catch (e) { moduleInstallMsg.value = { ok: false, text: lang.value === 'ru' ? 'Ошибка сети' : 'Network error' }; }
        await loadInstalledModules();
        moduleBusy.value = false;
    };
    const enableModule = async (m) => {
        if (moduleBusy.value) return;
        moduleBusy.value = true;
        try {
            const r = await fetch('/api/modules/' + m.id + '/enable', { method: 'POST' });
            const j = await r.json().catch(() => ({}));
            if (j.status === 'ok') {
                moduleInstallMsg.value = { ok: true, text: j.live ? (lang.value === 'ru' ? 'Модуль включён.' : 'Module enabled.') : (lang.value === 'ru' ? 'Модуль включится после перезапуска программы.' : 'Module will be enabled after a restart.') };
            } else {
                moduleInstallMsg.value = { ok: false, text: (lang.value === 'ru' ? 'Не удалось включить: ' : 'Enable failed: ') + (j.reason || '\u2014') };
            }
        } catch (e) { moduleInstallMsg.value = { ok: false, text: lang.value === 'ru' ? 'Ошибка сети' : 'Network error' }; }
        await loadInstalledModules();
        await loadModuleComponents();
        moduleBusy.value = false;
    };
    const deleteModule = async (l) => {
        if (moduleBusy.value) return;
        const nm = lang.value === 'ru' ? l.ru : l.en;
        if (!await askConfirm({ title: _L('Удалить модуль «' + nm + '»?', 'Delete module "' + nm + '"?'),
                                text: _L('Файлы модуля будут удалены, его данные (база) сохранятся. Полное отключение — после перезапуска программы.',
                                         'Module files will be removed; its data (DB) is kept. Restart completes the removal.'),
                                okText: _L('Удалить', 'Delete'), danger: true })) return;
        moduleBusy.value = true;
        try {
            const r = await fetch('/api/modules/' + l.moduleId, { method: 'DELETE' });
            const j = await r.json().catch(() => ({}));
            if (j.status === 'ok') {
                if (activeModuleId.value === l.moduleId) closeActiveModule();
                moduleInstallMsg.value = { ok: true, text: lang.value === 'ru' ? 'Модуль удалён — перезапустите программу.' : 'Module removed — restart the app.' };
            } else {
                const reasons = { 'bundled': lang.value === 'ru' ? 'это штатный модуль программы' : 'built-in module', 'not found': lang.value === 'ru' ? 'модуль не найден' : 'not found' };
                moduleInstallMsg.value = { ok: false, text: (lang.value === 'ru' ? 'Не удалось удалить: ' : 'Delete failed: ') + (reasons[j.reason] || j.reason || '\u2014') };
            }
        } catch (e) { moduleInstallMsg.value = { ok: false, text: lang.value === 'ru' ? 'Ошибка сети' : 'Network error' }; }
        await loadInstalledModules();
        moduleBusy.value = false;
    };

    // ---- Срок сдачи проекта + настройки отображения дат ----
    const showCreatedDate = ref(localStorage.getItem('farm_show_created') !== '0');   // по умолчанию вкл.
    const yellowDays = ref(parseInt(localStorage.getItem('farm_due_yellow') || '3', 10) || 3);
    const setShowCreatedDate = (v) => { showCreatedDate.value = !!v; try { localStorage.setItem('farm_show_created', v ? '1' : '0'); } catch (e) {} };
    const showSuggestions = ref(localStorage.getItem('farm_show_suggest') !== '0');   // панель «Подсказки» (Коллективный/Корпоративный): по умолчанию вкл.
    const setShowSuggestions = (v) => { showSuggestions.value = !!v; try { localStorage.setItem('farm_show_suggest', v ? '1' : '0'); } catch (e) {} };
    // Alpha 2.867: панель «Подсказки» сворачивается в одну строку заголовка. Это НЕ то же самое,
    // что галка «Панель подсказок» в настройках: та убирает панель совсем, свёрнутая остаётся
    // видимой и разворачивается одним кликом. Состояние помнится между запусками.
    const suggestCollapsed = ref(localStorage.getItem('farm_suggest_collapsed') === '1');
    //  05.09.2026: панель показывает отправки и очереди. Счётчик активных дел живёт в её
    //  заголовке, чтобы свёрнутая панель не прятала происходящее.
    const suggestActiveCount = computed(() => (toasts.value || []).length + (sendActiveCount.value || 0) + ((printQueue.value || []).length)
        + (printSendingNow.value ? 1 : 0) + ((queueWait.value || []).length));
    const toggleSuggestCollapsed = () => {
        suggestCollapsed.value = !suggestCollapsed.value;
        try { localStorage.setItem('farm_suggest_collapsed', suggestCollapsed.value ? '1' : '0'); } catch (e) {}
    };
    const setYellowDays = (v) => { let n = parseInt(v, 10); if (!(n >= 0)) n = 3; n = Math.max(0, Math.min(60, n)); yellowDays.value = n; try { localStorage.setItem('farm_due_yellow', String(n)); } catch (e) {} };
    const yellowDaysInput = computed({ get: () => yellowDays.value, set: setYellowDays });
    // ===== Режим интерфейса (basic/advanced/pro; per-browser; только набор видимых разделов, не лицензия) =====
    const _editions = ['basic', 'advanced', 'pro'];
    const appEdition = ref('advanced');
    try { const _e = localStorage.getItem('farm_edition'); if (_editions.includes(_e)) appEdition.value = _e; } catch (e) {}
    const setEdition = (e) => {
        if (!_editions.includes(e)) e = 'basic';
        appEdition.value = e;
        try { localStorage.setItem('farm_edition', e); } catch (e2) {}
        // При смене редакции всегда возвращаемся на главный экран, в каком бы окне/меню ни находились:
        // закрываем настройки, открытый проект и архив-режим. Иначе в младшей редакции, где раздел
        // проектов скрыт, ранее открытый проект продолжал бы прятать Tasks
        // (v-if="!project2Expanded") и правая область осталась бы полностью пустой.
        showSettings.value = false;
        project2Expanded.value = '';
        archiveMode.value = false;
    };
    // Какие функции УБРАНЫ в редакции (pro — полный набор; advanced распишем позже). edHas('feat') → есть ли функция.
    // Alpha 2.808: 'modules' УБРАН из этого списка во всех редакциях. Управление модулями —
    // функция ядра, а не платная возможность: именно из-за гейта редакции (по умолчанию
    // 'advanced', где modules были вычеркнуты) раздел «Модули» отсутствовал в настройках
    // на любом свежем профиле браузера и в собственном окне, и установленные модули нечем
    // было ни увидеть, ни обновить. Редакция хранится в localStorage и клиентской косметикой
    // быть может, а правом на управление установкой — нет.
    // R-132 (решение владельца 29.09.2026): выбор называется «Режим интерфейса» и меняет только
    // набор видимых разделов. «Доступ и аудит» (пользователи, журнал аудита, отзыв телефонов) —
    // защита фермы, а не платная возможность, поэтому 'security' не прячется ни в одном режиме.
    const _editionRemoved = { basic: ['projects', 'dates'], advanced: [], pro: [] };   // 05.09.2026: «Подсказки» — статусы отправок и очередей, нужны в любой редакции
    const edHas = (feat) => !(_editionRemoved[appEdition.value] || []).includes(feat);
    const _patchProject2 = async (pid, body) => {
        try { await fetch('/api/projects2/' + encodeURIComponent(pid), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }
        catch (e) { console.warn('due patch failed', e); }
    };
    const setProjectDue = (pid, iso) => { const p = projects2.value.find(x => x.id === pid); if (p) p.due_date = iso || ''; _patchProject2(pid, { due_date: iso || '' }); };
    const clearProjectDue = (pid) => { const p = projects2.value.find(x => x.id === pid); if (p) p.due_date = ''; _patchProject2(pid, { due_date: '' }); };





    // ------------------------------------------------------------------------
    // БЛОК: интерактивное обучение.
    // Работает на временных демонстрационных данных в памяти и не отправляет
    // изменения на сервер. Анимации этого блока описаны в app.css.
    // ------------------------------------------------------------------------
    // ============================================================================
    //  ИНТЕРАКТИВНОЕ ОБУЧЕНИЕ (тур по интерфейсу). Кольцо box-shadow вешаем прямо на
    //  реальный элемент (устойчиво к zoom), плюс фиксированная карточка-подсказка
    //  снизу. Запуск: кнопка «Обучение». Ферму не трогает.
    // ============================================================================
    const tourActive = ref(false);
    const tourStep = ref(0);
    const tourBox = ref(null);   // {left,top,width,height} подсвечиваемого элемента в координатах экрана
    const tourCardRect = ref(null);   // прямоугольник карточки тура (для соединительной линии)
    let _tourRaf = 0;
    let _tourMeasureUntil = 0;
    let _savedWin = { x: 0, y: 0 };   // позиция окна на старте тура — держим её все шаги, чтобы не обрезалась шапка
    /* =====================================================================
       ИНТЕРАКТИВНОЕ ОБУЧЕНИЕ — сценарий вынесен из app.js
       ---------------------------------------------------------------------
       Сами шаги обучения теперь находятся в отдельном файле:
         web/composables/tourSteps.js

       Почему так безопаснее:
         1) текст, порядок шагов и селекторы обучения редактируются отдельно;
         2) рабочая логика принтеров, проектов, API и расчётов остаётся в app.js;
         3) при будущих правках обучения меньше риск случайно задеть код приложения.

       ВАЖНО: при копировании этого app.js обязательно копировать и новый файл
       web/composables/tourSteps.js, иначе браузер не сможет загрузить модуль тура.

       В этой версии поддерживаются два режима: короткий тур startTour('quick')
       и полный тур startTour('full'). Оба берут шаги из одного сценария.
       Подробная инструкция по правкам: web/tour/TOUR_GUIDE_RU.md
       ===================================================================== */
    const tourEnabled = TOUR_ENABLED;   // шаблону: окно и кнопки обучения прячутся, пока тур выключен
    const tourMode = ref('full');
    const tourSteps = ref(FULL_TOUR_STEPS);
    const tourModeTitle = computed(() => tourMode.value === 'quick' ? 'Quick tour' : 'Full tour');
    const tourMarks = ref([]);
    const tourHints = ref([]);
    // Прогресс и стартовое окно обучения храним только в браузере.
    // Это не уходит на сервер и не влияет на принтеры/проекты.
    const TOUR_PROGRESS_KEY = 'farm_tour_progress_v1';
    const TOUR_COMPLETED_KEY = 'farm_tour_completed_v1';
    const TOUR_START_PROMPT_KEY = 'farm_tour_start_prompt_v1';
    const savedTourProgress = ref(null);
    const _tourReadStartupPrompt = () => { try { return localStorage.getItem(TOUR_START_PROMPT_KEY) !== '0'; } catch (e) { return true; } };
    const _tourReadCompleted = () => { try { return localStorage.getItem(TOUR_COMPLETED_KEY) === '1'; } catch (e) { return false; } };
    const tourStartupPromptEnabled = ref(_tourReadStartupPrompt());
    const tourCompleted = ref(_tourReadCompleted());
    const showTourStartDialog = ref(false);
    const tourStartNoShow = ref(!tourStartupPromptEnabled.value);
    const currentTourStep = computed(() => tourSteps.value[tourStep.value] || { title: '', text: '', more: '' });
    const tourProjectDemoOpen = computed(() => tourActive.value && currentTourStep.value && currentTourStep.value.scene === 'project');
    const tourMoreOpen = ref(false);
    const currentTourPrimaryText = computed(() => currentTourStep.value && currentTourStep.value.text ? currentTourStep.value.text : '');
    const currentTourHasMore = computed(() => !!(currentTourStep.value && currentTourStep.value.more));
    const _tourRefreshMeasure = (durationMs = 420) => {
        nextTick(() => {
            if (!tourActive.value) return;
            const ms = Math.max(120, Number(durationMs) || 420);
            _tourMeasureUntil = Math.max(_tourMeasureUntil || 0, performance.now() + ms);
            if (_tourRaf) cancelAnimationFrame(_tourRaf);
            _tourRaf = requestAnimationFrame(_tourTick);
        });
    };
    // Публичный хук только для тура: пересчитать подсветку после поздней загрузки
    // изображений/превью, которые могут сдвинуть кнопки внутри раскрытой карточки.
    const refreshTourLayout = (durationMs = 1200) => { _tourRefreshMeasure(durationMs); };
    const toggleTourMore = () => { if (!currentTourHasMore.value) return; tourMoreOpen.value = !tourMoreOpen.value; _tourRefreshMeasure(); };
    // Раздел текущего шага: нужен для понятной структуры длинного обучения.
    const currentTourGroup = computed(() => currentTourStep.value && currentTourStep.value.group ? currentTourStep.value.group : 'basics');
    const currentTourGroupLabel = computed(() => TOUR_GROUP_LABELS[currentTourGroup.value] || 'Section');
    const currentTourGroupBounds = computed(() => {
        const group = currentTourGroup.value;
        const steps = tourSteps.value || [];
        let first = -1, last = -1, indexInGroup = 0, totalInGroup = 0;
        for (let i = 0; i < steps.length; i++) {
            if (steps[i] && steps[i].group === group) {
                if (first < 0) first = i;
                last = i;
                totalInGroup++;
                if (i <= tourStep.value) indexInGroup++;
            }
        }
        return { group, first, last, indexInGroup: Math.max(1, indexInGroup), totalInGroup: Math.max(1, totalInGroup) };
    });
    const currentTourGroupProgress = computed(() => {
        const b = currentTourGroupBounds.value;
        return tr('Section') + ': ' + tr(currentTourGroupLabel.value) + ' · ' + b.indexInGroup + ' ' + tr('of') + ' ' + b.totalInGroup;
    });
    const tourCanSkipGroup = computed(() => {
        const b = currentTourGroupBounds.value;
        return tourActive.value && b.last >= 0 && b.last < tourSteps.value.length - 1;
    });
    const _tourStepsForMode = (mode) => (mode === 'quick' && QUICK_TOUR_STEPS.length) ? QUICK_TOUR_STEPS : FULL_TOUR_STEPS;
    const _tourLoadProgress = () => {
        try {
            const raw = localStorage.getItem(TOUR_PROGRESS_KEY);
            if (!raw) return null;
            const saved = JSON.parse(raw);
            const mode = saved && saved.mode === 'quick' ? 'quick' : 'full';
            const steps = _tourStepsForMode(mode);
            const byId = saved && saved.stepId ? steps.findIndex(s => s && s.id === saved.stepId) : -1;
            const byIndex = Number.isFinite(saved && saved.stepIndex) ? Math.max(0, Math.min(steps.length - 1, saved.stepIndex)) : 0;
            const stepIndex = byId >= 0 ? byId : byIndex;
            if (!steps[stepIndex]) return null;
            return { mode, stepId: steps[stepIndex].id || '', stepIndex, updatedAt: saved.updatedAt || 0 };
        } catch (e) { return null; }
    };
    const _tourRefreshSavedProgress = () => { savedTourProgress.value = _tourLoadProgress(); };
    const _tourClearProgress = () => { try { localStorage.removeItem(TOUR_PROGRESS_KEY); } catch (e) {} savedTourProgress.value = null; };
    const _tourSetCompleted = (value) => {
        tourCompleted.value = !!value;
        try {
            if (value) localStorage.setItem(TOUR_COMPLETED_KEY, '1');
            else localStorage.removeItem(TOUR_COMPLETED_KEY);
        } catch (e) {}
    };
    const _tourSaveProgress = () => {
        if (!tourActive.value) return;
        const steps = tourSteps.value || [];
        const step = steps[tourStep.value];
        if (!step) return;
        const payload = { mode: tourMode.value, stepId: step.id || '', stepIndex: tourStep.value, updatedAt: Date.now() };
        try { localStorage.setItem(TOUR_PROGRESS_KEY, JSON.stringify(payload)); } catch (e) {}
        savedTourProgress.value = payload;
    };
    _tourRefreshSavedProgress();
    const hasSavedTourProgress = computed(() => !!savedTourProgress.value);
    const tourSavedProgressLabel = computed(() => {
        const p = savedTourProgress.value;
        if (!p) return '';
        const steps = _tourStepsForMode(p.mode);
        const n = Math.max(1, Math.min(steps.length, (p.stepIndex || 0) + 1));
        const modeLabel = p.mode === 'quick'
            ? (lang.value === 'ru' ? 'короткое' : 'quick')
            : (lang.value === 'ru' ? 'полное' : 'full');
        return modeLabel + ' · ' + n + '/' + steps.length;
    });
    const tourStartupStatusLabel = computed(() => tourStartupPromptEnabled.value
        ? (lang.value === 'ru' ? 'вкл' : 'on')
        : (lang.value === 'ru' ? 'выкл' : 'off'));
    const tourStartSections = computed(() => {
        const fullSteps = Array.isArray(FULL_TOUR_STEPS) ? FULL_TOUR_STEPS : [];
        const quickSteps = Array.isArray(QUICK_TOUR_STEPS) ? QUICK_TOUR_STEPS : [];
        const quickGroups = new Set(quickSteps.map(step => step && step.group).filter(Boolean));
        const declaredGroups = Array.isArray(TOUR_GROUP_ORDER) && TOUR_GROUP_ORDER.length
            ? TOUR_GROUP_ORDER
            : Array.from(new Set(fullSteps.map(step => step && step.group).filter(Boolean)));
        return declaredGroups.map((group) => {
            const fullCount = fullSteps.filter(step => step && step.group === group).length;
            if (!fullCount) return null;
            return {
                group,
                label: tr(TOUR_GROUP_LABELS[group] || group),
                fullCount,
                quickIncluded: quickGroups.has(group)
            };
        }).filter(Boolean);
    });
    const setTourStartupPrompt = (value) => {
        tourStartupPromptEnabled.value = !!value;
        tourStartNoShow.value = !tourStartupPromptEnabled.value;
        try { localStorage.setItem(TOUR_START_PROMPT_KEY, tourStartupPromptEnabled.value ? '1' : '0'); } catch (e) {}
    };
    const applyTourStartNoShow = () => { setTourStartupPrompt(!tourStartNoShow.value); };
    const openTourStartDialog = () => {
        if (!TOUR_ENABLED) return;   // обучение выключено (решение владельца 12.09.2026)
        _tourRefreshSavedProgress();
        tourCompleted.value = _tourReadCompleted();
        tourStartNoShow.value = !tourStartupPromptEnabled.value;
        showTourStartDialog.value = true;
    };
    const closeTourStartDialog = () => { showTourStartDialog.value = false; };
    const dismissTourStartDialog = () => { applyTourStartNoShow(); closeTourStartDialog(); };
    const startTourFromDialog = (mode) => { applyTourStartNoShow(); closeTourStartDialog(); startTour(mode); };
    const resumeTourFromDialog = () => { applyTourStartNoShow(); closeTourStartDialog(); resumeTour(); };
    const resetTourProgress = () => { _tourClearProgress(); _tourSetCompleted(false); };
    const tourCtxDemo = computed(() => { const s = currentTourStep.value, b = tourBox.value; if (!s || !s.ctxDemo || !b) return null; return { x: b.left + Math.min(b.width * 0.32, 110), y: b.top + Math.min(b.height * 0.28, 36) }; });
    // ── Демо-данные тура (для первого запуска, когда ещё нет принтеров/проектов/задач). Только в памяти:
    //    на сервер НЕ пишем, фоновые обновления на время тура заморожены (guard'ы по tourActive), по выходу — полный откат.
    const _TOUR_PID = '__tour_demo__';
    const _TOUR_PUID = '__tour_demo_part__';
    const _TOUR_FILE = 'demo_panel.gcode';
    const _TOUR_MODEL = 'demo_model.3mf';
    let _tourSnap = null;
    const _tourSeedDemo = () => {
        wsData.value[_TOUR_PID] = { status: 'RUNNING', percent: 42, file_name: 'demo_bracket', nozzle_count: 1, nozzle_temp: 218, nozzle_target: 220, bed_temp: 60, bed_target: 60, elapsed: 3725, remaining_time: 4080, parts: [{ name: 'DEMO PART', qty: 2 }], ams_trays: [] };
        printers.value = ([{ id: _TOUR_PID, __demo: true, name: 'DEMO PRINTER', type: 'bambu', ip: '192.168.0.123', port: 8883, serial: '', access_code: '', model: '' }]);
        parts.value = ([{ part_name: 'DEMO PART', required_qty: 4, printed_qty: 1, status: 'in_progress', project_name: 'Demo Project', due_date: '', is_deleted: 0, order_idx: 999000, _uid: _TOUR_PUID, __demo: true, preview_base64: '', notes: '', gcode_file: 'demo_bracket.gcode', src_path: '' }]);
        stagingFiles.value = ([{ filename: _TOUR_FILE, status: 'printing', printer_id: _TOUR_PID, __demo: true, required_qty: 2, printed_qty: 0, notes: '', cb: 0, mtime: 0 }]);
        projects2.value = ([{ id: 'proj_tour_demo', __demo: true, name: 'DEMO PROJECT', parts_count: 3, done_count: 1, printing_count: 1, files_count: 2, required_total: 8, printed_total: 3, rework_pending: 1, needs_rework: true, part_thumbs: [], due_date: new Date(Date.now()+3*864e5).toISOString().slice(0,10), created_at: new Date().toISOString().slice(0,10) }]);
        // (А) демо-наполнение раскрытого проекта: дерево файлов + детали со счётчиками, чтобы реальный вид «По деталям» показывал данные во время тура. Берётся только когда демо-проект раскрыт (шаги 21–26); фетч не вызывается, т.к. project2Expanded задаётся напрямую.
        project2Trees.value = Object.assign({}, project2Trees.value, { 'proj_tour_demo': { project: { id: 'proj_tour_demo', name: 'DEMO PROJECT' }, nodes: [ { id: 'f_demo_1', name: 'housing.3mf', type: 'file' }, { id: 'f_demo_2', name: 'panel.gcode', type: 'file' } ] } });
        project2Parts.value = Object.assign({}, project2Parts.value, { 'proj_tour_demo': { project: { id: 'proj_tour_demo', name: 'DEMO PROJECT' }, parts: [
            { part_id: 'pt_demo_1', part_name: 'Housing', required_qty: 2, printed_qty: 2, status: 'done', live_printers: [], notes: '', rework_qty: 0, rework_done: 0, plates: [ { file_part_id: 'fp_demo_1', file_id: 'f_demo_1', filename: 'housing.3mf', on_plate_qty: 1, total_parts: 1, src_path: '', target_model: '', is_printable: true } ] },
            { part_id: 'pt_demo_2', part_name: 'Cover', required_qty: 4, printed_qty: 1, status: 'in_progress', live_printers: [], notes: '', rework_qty: 0, rework_done: 0, plates: [ { file_part_id: 'fp_demo_2', file_id: 'f_demo_2', filename: 'panel.gcode', on_plate_qty: 4, total_parts: 4, src_path: '', target_model: '', is_printable: true } ] },
            { part_id: 'pt_demo_3', part_name: 'Bracket', required_qty: 2, printed_qty: 0, status: 'pending', live_printers: [], notes: '', rework_qty: 1, rework_done: 0, plates: [ { file_part_id: 'fp_demo_3', file_id: 'f_demo_2', filename: 'panel.gcode', on_plate_qty: 1, total_parts: 4, src_path: '', target_model: '', is_printable: true } ] }
        ] } });
        project2Expanded.value = '';
        expandedProjects.value = Object.assign({}, expandedProjects.value, { 'Demo Project': true });
    };
    const _tourInject = () => {
        _tourSnap = {
            parts: parts.value.slice(), staging: stagingFiles.value.slice(), printers: printers.value.slice(),
            expanded: Object.assign({}, expandedProjects.value), view: viewMode.value, openPlan: openPlan.value,
            showModal: showModal.value, activeId: activeModalPrinterId.value, porder: projectOrder.value.slice(),
            edition: appEdition.value, p2: projects2.value.slice(), p2exp: project2Expanded.value
        };
        appEdition.value = 'pro';   // на время тура показываем ВСЕ функции (в младших редакциях часть скрыта)
        _tourSeedDemo();
    };
    const _tourRestore = () => {
        try {
            if (_tourSnap) {
                parts.value = _tourSnap.parts; stagingFiles.value = _tourSnap.staging; printers.value = _tourSnap.printers;
                expandedProjects.value = _tourSnap.expanded; viewMode.value = _tourSnap.view; openPlan.value = _tourSnap.openPlan;
                showModal.value = _tourSnap.showModal; activeModalPrinterId.value = _tourSnap.activeId; projectOrder.value = _tourSnap.porder;
                appEdition.value = _tourSnap.edition; projects2.value = _tourSnap.p2; project2Expanded.value = _tourSnap.p2exp;
                const _pt = Object.assign({}, project2Trees.value); delete _pt['proj_tour_demo']; project2Trees.value = _pt;
                const _pp = Object.assign({}, project2Parts.value); delete _pp['proj_tour_demo']; project2Parts.value = _pp;   // (А) убрать демо-наполнение раскрытого проекта
            } else {
                parts.value = parts.value.filter(p => p._uid !== _TOUR_PUID);
                stagingFiles.value = stagingFiles.value.filter(f => f.filename !== _TOUR_FILE);
                printers.value = printers.value.filter(p => p.id !== _TOUR_PID);
            }
        } catch (e) {}
        try { delete wsData.value[_TOUR_PID]; } catch (e) {}
        exitSpotlight();
        if (editingProjects.value['Demo Project']) editingProjects.value = Object.assign({}, editingProjects.value, { 'Demo Project': false });
        _tourSnap = null;
    };
    // Демо-проводник (шаг fake): выбор файла -> подсветка -> пульс кнопки «Загрузить в задачи». Без реального проводника.
    const tourFakeEx = ref(false);
    const tourFakeStep = ref(0);
    const tourSceneId = ref(null);
    const _sceneMaxPhase = () => tourSceneId.value === 'attach' ? 8 : (tourSceneId.value === 'diag' ? 6 : (tourSceneId.value === 'slice' ? 4 : (tourSceneId.value === 'reveal' ? 4 : 7)));
    const sceneCursorPx = ref({ x: 0, y: 0 });
    const _sceneTargetSel = () => { const p = tourFakeStep.value; if (tourSceneId.value === 'attach') { if (p <= 1) return '[data-scene=editbtn]'; if (p === 2 || p === 3) return '[data-scene=attachbtn]'; if (p === 4) return '[data-scene=filerow]'; if (p === 5) return '[data-scene=loadbtn]'; return '[data-scene=editbtn]'; } if (tourSceneId.value === 'print') { if (p <= 1) return '[data-scene=printupld]'; if (p === 2 || p === 3) return '[data-scene=filerow]'; if (p === 4) return '[data-scene=loadbtn]'; return '[data-scene=amsslot]'; } if (tourSceneId.value === 'diag') { if (p <= 1) return '[data-tour="diag"]'; if (p === 2 || p === 3) return '[data-scene=diagbody]'; return '[data-scene=diagclose]'; } if (tourSceneId.value === 'slice') { if (p <= 0) return '[data-scene=slicename]'; return '[data-scene=slicebtn]'; } if (tourSceneId.value === 'reveal') { if (p <= 1) return '[data-scene=slicename]'; return '[data-scene=filerow]'; } if (p === 2 || p === 3) return '[data-scene=filerow]'; if (p === 4) return '[data-scene=loadbtn]'; return '.qt-open'; };
    const _sceneMeasureCursor = () => {
        if (!tourFakeEx.value) return;
        const z = _tourZoom();
        const el = document.querySelector(_sceneTargetSel());
        if (el) { const r = el.getBoundingClientRect(); if (r.width > 0) { sceneCursorPx.value = { x: (r.left + r.width / 2) / z, y: (r.top + r.height / 2) / z }; return; } }
        const b = tourBox.value; if (b) sceneCursorPx.value = { x: b.left + b.width / 2, y: b.top + b.height / 2 };
    };
    const sceneClick = computed(() => { const p = tourFakeStep.value; if (tourSceneId.value === 'attach') return p === 1 || p === 3 || p === 4 || p === 5 || p === 7; if (tourSceneId.value === 'print') return p === 1 || p === 3 || p === 4 || p === 6; if (tourSceneId.value === 'diag') return p === 1 || p === 5; if (tourSceneId.value === 'slice') return p === 2; if (tourSceneId.value === 'reveal') return p === 1; return p === 1 || p === 3 || p === 4; });
    const sceneCursorShow = computed(() => tourSceneId.value !== 'diag');   // в диагностике курсор-указатель не показываем — шаг полностью статичный
    const sceneFmOpen = computed(() => { const p = tourFakeStep.value; if (tourSceneId.value === 'attach') return (p >= 3 && p <= 5); if (tourSceneId.value === 'print') return (p >= 2); if (tourSceneId.value === 'diag') return false; if (tourSceneId.value === 'slice') return false; if (tourSceneId.value === 'reveal') return p >= 2; return (p >= 2 && p <= 4); });
    const sceneFileSel = computed(() => { const p = tourFakeStep.value; if (tourSceneId.value === 'attach') return (p >= 4 && p <= 5); if (tourSceneId.value === 'print') return (p >= 3 && p <= 4); if (tourSceneId.value === 'reveal') return p >= 2; return (p >= 3 && p <= 4); });
    const sceneActionPress = computed(() => { const p = tourFakeStep.value; if (tourSceneId.value === 'attach') return (p === 5); if (tourSceneId.value === 'print') return (p === 4); return (p === 4); });
    const sceneActionLabel = computed(() => tourSceneId.value === 'attach' ? 'Attach' : (tourSceneId.value === 'print' ? 'Print' : 'Load to tasks'));
    const sceneAmsOpen = computed(() => tourSceneId.value === 'print' && (tourFakeStep.value === 5 || tourFakeStep.value === 6));
    const sceneAmsSel = computed(() => tourSceneId.value === 'print' && tourFakeStep.value === 6);
    const sceneDiagOpen = computed(() => tourSceneId.value === 'diag');   // окно диагностики открыто весь шаг: появляется сразу вместе с подсветкой и затемнением, без задержки фазы и без повторного гашения по циклу
    const sceneDiagSel = computed(() => tourSceneId.value === 'diag' && tourFakeStep.value === 5);
    const sceneDiagScroll = computed(() => { const p = tourFakeStep.value; if (tourSceneId.value !== 'diag') return 0; if (p <= 1) return 0; if (p === 2) return -75; return -150; });
    const sceneSliceToast = computed(() => tourSceneId.value === 'slice' && tourFakeStep.value >= 2);
    let _fakeTO = 0, _fakeIV = 0;
    const _tourFakeStop = () => { if (_fakeTO) { clearTimeout(_fakeTO); _fakeTO = 0; } if (_fakeIV) { clearInterval(_fakeIV); _fakeIV = 0; } tourFakeEx.value = false; tourFakeStep.value = 0; tourSceneId.value = null; };
    const _sceneDemoFile = () => ({ filename: _TOUR_FILE, status: 'pending', __demo: true, required_qty: 1, printed_qty: 0, notes: '', cb: 0, mtime: 0 });
    const _sceneSyncStaging = () => {
        const has = stagingFiles.value.some(f => f.filename === _TOUR_FILE);
        if (tourFakeStep.value >= 5 && !has) stagingFiles.value = stagingFiles.value.concat([_sceneDemoFile()]);
        else if (tourFakeStep.value < 5 && has) stagingFiles.value = stagingFiles.value.filter(f => f.filename !== _TOUR_FILE);
    };
    const _sceneSyncEdit = () => {
        const p = tourFakeStep.value;
        const ed = (p >= 1 && p <= 6);
        if (!!editingProjects.value['Demo Project'] !== ed) editingProjects.value = Object.assign({}, editingProjects.value, { 'Demo Project': ed });
        const dp = parts.value.find(x => x._uid === _TOUR_PUID);
        if (dp) { const want = (p >= 5) ? 'demo_panel.gcode' : ''; if (dp.gcode_file !== want) dp.gcode_file = want; }
    };
    const _sceneSyncPrint = () => {
        const d = wsData.value[_TOUR_PID]; if (!d) return;
        const want = (tourFakeStep.value === 6) ? 'RUNNING' : 'IDLE';
        if (d.status !== want) d.status = want;
        if (d.percent !== 0) d.percent = 0;
    };
    const _tourFakeStart = (sceneId) => {
        _tourFakeStop();
        tourSceneId.value = sceneId || 'load';
        tourFakeEx.value = true; tourFakeStep.value = 0;
        if (tourSceneId.value === 'load') stagingFiles.value = stagingFiles.value.filter(f => f.filename !== _TOUR_FILE);
        if (tourSceneId.value === 'attach') { if (!!editingProjects.value['Demo Project']) editingProjects.value = Object.assign({}, editingProjects.value, { 'Demo Project': false }); const dp = parts.value.find(x => x._uid === _TOUR_PUID); if (dp && dp.gcode_file) dp.gcode_file = ''; }
        if (tourSceneId.value === 'print') { const d = wsData.value[_TOUR_PID]; if (d) { d.ams_trays = [{ index: 0, unit: 1, tray: 0, type: 'PLA', color: '#22c55e' }, { index: 1, unit: 1, tray: 1, type: 'PETG', color: '#3b82f6' }, { index: 2, unit: 1, tray: 2, type: 'ABS', color: '#ef4444' }]; d.ams_now = -1; } _sceneSyncPrint(); }
        if (tourSceneId.value === 'slice') { stagingFiles.value = ([{ filename: _TOUR_MODEL, status: 'pending', __demo: true, required_qty: 1, printed_qty: 0, notes: '', cb: 0, mtime: 0 }]); }
        if (tourSceneId.value === 'reveal') { stagingFiles.value = ([{ filename: _TOUR_FILE, status: 'pending', __demo: true, required_qty: 1, printed_qty: 0, notes: '', cb: 0, mtime: 0 }]); }
        nextTick(() => requestAnimationFrame(_sceneMeasureCursor));
        if (tourSceneId.value !== 'diag') _fakeIV = setInterval(() => { tourFakeStep.value = (tourFakeStep.value + 1) % _sceneMaxPhase(); if (tourSceneId.value === 'attach') _sceneSyncEdit(); else if (tourSceneId.value === 'print') _sceneSyncPrint(); else if (tourSceneId.value === 'diag') {} else if (tourSceneId.value === 'slice') {} else if (tourSceneId.value === 'reveal') {} else _sceneSyncStaging(); nextTick(() => requestAnimationFrame(_sceneMeasureCursor)); }, 1150);
    };
    // getBoundingClientRect отдаёт ВИЗУАЛЬНЫЕ px (с учётом zoom). Спотлайт телепортирован в body — вне
    // .zoom-wrap, но ВНУТРИ html{zoom:1.04}, поэтому его CSS-координаты ещё раз домножаются на html-zoom.
    // Делим rect на html-zoom, иначе рамка уезжает от элемента тем сильнее, чем дальше он от левого-верхнего угла.
    const tourCardPos = computed(() => {
        const step = tourSteps.value[tourStep.value];
        if (step && step.card) return step.card;
        const b = tourBox.value;
        const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1.04;
        const vw = (window.innerWidth || 1280) / z, vh = (window.innerHeight || 800) / z;
        const compact = vw < 760 || vh < 620;
        const navH = compact ? 112 : 74, cardW = Math.min(480, Math.max(280, vw - (compact ? 24 : 36))), m = compact ? 12 : 18;
        if (!b) return 'top';
        if (!compact && vw >= 900 && b.width < vw * 0.72) {
            if (b.left + b.width < vw * 0.6 && (vw - b.left - b.width) >= cardW + m) return 'right';
            if (b.left > vw * 0.4 && b.left >= cardW + m) return 'left';
        }
        return ((b.top + b.height / 2) > (vh - navH) * 0.5) ? 'top' : 'bottom';
    });
    const tourCardStyle = computed(() => {
        const pos = tourCardPos.value, b = tourBox.value;
        const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1.04;
        const vw = (window.innerWidth || 1280) / z, vh = (window.innerHeight || 800) / z;
        const compact = vw < 760 || vh < 620;
        const cardExpanded = tourMoreOpen.value && currentTourStep.value && currentTourStep.value.more;
        const navH = compact ? 112 : 74, cardW = Math.min(480, Math.max(280, vw - (compact ? 24 : 36))), chEst = compact ? (cardExpanded ? 332 : 236) : (cardExpanded ? 300 : 180), ch = (tourCardRect.value && tourCardRect.value.height > 0) ? tourCardRect.value.height : chEst, m = compact ? 12 : 18, g = compact ? 18 : 30;
        const maxTop = Math.max(m, vh - navH - ch);
        const fix = { position: 'fixed', zIndex: 9999, pointerEvents: 'none' };
        if (compact) {
            if (!b || pos === 'top' || pos === 'tl' || pos === 'tr') return Object.assign({}, fix, { left: '0px', right: '0px', display: 'flex', justifyContent: 'center', top: m + 'px' });
            return Object.assign({}, fix, { left: '0px', right: '0px', display: 'flex', justifyContent: 'center', top: maxTop + 'px' });
        }
        if (pos === 'tr') return Object.assign({}, fix, { right: m + 'px', top: m + 'px' });
        if (pos === 'br') return Object.assign({}, fix, { right: m + 'px', top: maxTop + 'px' });
        if (pos === 'tl') return Object.assign({}, fix, { left: m + 'px', top: m + 'px' });
        if (pos === 'bl') return Object.assign({}, fix, { left: m + 'px', top: maxTop + 'px' });
        if (!b || pos === 'top') return Object.assign({}, fix, { left: '0px', right: '0px', display: 'flex', justifyContent: 'center', top: '20px' });
        if (pos === 'bottom') return Object.assign({}, fix, { left: '0px', right: '0px', display: 'flex', justifyContent: 'center', top: maxTop + 'px' });
        if (pos === 'below' || pos === 'above') {
            const lf = Math.max(m, Math.min(vw - cardW - m, (b.left + b.width / 2) - cardW / 2));
            let tp = (pos === 'below') ? (b.top + b.height + g) : (b.top - ch - g);
            tp = Math.max(m, Math.min(maxTop, tp));
            return Object.assign({}, fix, { left: lf + 'px', top: tp + 'px' });
        }
        const top = Math.max(m, Math.min(maxTop, (b.top + b.height / 2) - ch / 2));
        const hasRoomRight = (b.left + b.width + g + cardW) <= (vw - m);
        const hasRoomLeft = (b.left - g - cardW) >= m;
        if (pos === 'right') {
            if (hasRoomRight) return Object.assign({}, fix, { left: (b.left + b.width + g) + 'px', top: top + 'px' });
            if (hasRoomLeft) return Object.assign({}, fix, { left: (b.left - cardW - g) + 'px', top: top + 'px' });
        }
        if (pos === 'left') {
            if (hasRoomLeft) return Object.assign({}, fix, { left: (b.left - cardW - g) + 'px', top: top + 'px' });
            if (hasRoomRight) return Object.assign({}, fix, { left: (b.left + b.width + g) + 'px', top: top + 'px' });
        }
        const lf = Math.max(m, Math.min(vw - cardW - m, (b.left + b.width / 2) - cardW / 2));
        let tp = ((b.top + b.height / 2) > (vh - navH) * 0.5) ? (b.top - ch - g) : (b.top + b.height + g);
        tp = Math.max(m, Math.min(maxTop, tp));
        return Object.assign({}, fix, { left: lf + 'px', top: tp + 'px' });
    });
    const _tourZoom = () => { const z = parseFloat(getComputedStyle(document.documentElement).zoom); return (z && z > 0.1) ? z : 1.04; };
    const tourConnector = computed(() => {
        const b = tourBox.value, c = tourCardRect.value;
        if (!b || !c) return null;
        const step = tourSteps.value[tourStep.value];
        const P = (step && step.noDim) ? 0 : 6;   // рамка подсветки нарисована с отступом 6px (для noDim рамки нет)
        const frame = { left: b.left - P, top: b.top - P, width: b.width + P * 2, height: b.height + P * 2 };
        const card = { left: c.left, top: c.top, width: c.width, height: c.height };
        const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
        const clean = (v) => Math.round(v * 10) / 10;
        const center = (r) => ({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
        const pointOnRectToward = (r, tx, ty, outward = 0) => {
            const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
            const dx = tx - cx, dy = ty - cy;
            const halfW = Math.max(1, r.width / 2), halfH = Math.max(1, r.height / 2);
            // Выбираем ближайшую грань прямоугольника по направлению на вторую точку.
            // Такой коннектор всегда остаётся одной прямой линией и не может сложиться в зигзаг
            // при изменении масштаба браузера или размеров окна.
            if (Math.abs(dx) / halfW >= Math.abs(dy) / halfH) {
                const sideRight = dx >= 0;
                return {
                    x: clean(sideRight ? r.left + r.width + outward : r.left - outward),
                    y: clean(clamp(ty, r.top + 10, r.top + r.height - 10))
                };
            }
            const sideBottom = dy >= 0;
            return {
                x: clean(clamp(tx, r.left + 10, r.left + r.width - 10)),
                y: clean(sideBottom ? r.top + r.height + outward : r.top - outward)
            };
        };
        const fc = center(frame), cc = center(card);
        const start = pointOnRectToward(frame, cc.x, cc.y, 0);   // точка привязки на подсвеченном элементе
        const end = pointOnRectToward(card, start.x, start.y, 0); // точка на ближайшей грани окна описания
        const dx = end.x - start.x, dy = end.y - start.y;
        if (!Number.isFinite(dx) || !Number.isFinite(dy)) return null;
        if (Math.hypot(dx, dy) < 12) return { d: '', fx: start.x, fy: start.y };
        const d = 'M ' + start.x + ' ' + start.y + ' L ' + end.x + ' ' + end.y;
        return { d: d, fx: start.x, fy: start.y };
    });
    const tourHintBoxes = computed(() => {
        return (tourHints.value || []).map(function(h){
            const cx = h.x + h.w / 2, cy = h.y + h.h / 2;
            let st, cls;
            if (h.pos === 'top') { st = { position: 'absolute', left: cx + 'px', top: (h.y - 9) + 'px', transform: 'translate(-50%,-100%)' }; cls = 'ht-top'; }
            else if (h.pos === 'left') { st = { position: 'absolute', left: (h.x - 9) + 'px', top: cy + 'px', transform: 'translate(-100%,-50%)' }; cls = 'ht-left'; }
            else if (h.pos === 'right') { st = { position: 'absolute', left: (h.x + h.w + 9) + 'px', top: cy + 'px', transform: 'translateY(-50%)' }; cls = 'ht-right'; }
            else { st = { position: 'absolute', left: cx + 'px', top: (h.y + h.h + 9) + 'px', transform: 'translateX(-50%)' }; cls = 'ht-bottom'; }
            return { t: h.t, style: st, cls: cls };
        });
    });
    const _tourMeasure = () => {
        if (!tourActive.value) return;
        if (window.scrollX !== _savedWin.x || window.scrollY !== _savedWin.y) window.scrollTo(_savedWin.x, _savedWin.y);   // окно держим на месте — шапка не уезжает
        const step = tourSteps.value[tourStep.value];
        const el = step ? document.querySelector(step.sel) : null;
        if (el) {
            const r = el.getBoundingClientRect();
            const z = _tourZoom();
            tourBox.value = (r.width > 0 && r.height > 0) ? { left: r.left / z, top: r.top / z, width: r.width / z, height: r.height / z } : null;
        } else { tourBox.value = null; }
        if (step && step.marks && step.marks.length) {
            const mz = _tourZoom(); const mm = [];
            for (let i = 0; i < step.marks.length; i++) {
                const mk = step.marks[i];
                const me = document.querySelector('[data-tour-mark=' + mk.m + ']');
                if (me) { const mr = me.getBoundingClientRect();
                    if (mr.width > 0 && mr.height > 0) {
                        const px = mk.pos && mk.pos.indexOf('r') !== -1 ? mr.right : (mk.pos && mk.pos.indexOf('l') !== -1 ? mr.left : mr.left + mr.width / 2);
                        const py = mk.pos && mk.pos.indexOf('b') !== -1 ? mr.bottom : mr.top;
                        mm.push({ x: px / mz, y: py / mz, n: mk.n, bx: mr.left / mz, by: mr.top / mz, bw: mr.width / mz, bh: mr.height / mz }); } }
            }
            tourMarks.value = mm;
        } else { tourMarks.value = []; }
        if (step && step.hints && step.hints.length) {
            const hz = _tourZoom(); const hh = [];
            for (let i = 0; i < step.hints.length; i++) {
                const hn = step.hints[i];
                const he = document.querySelector(hn.sel);
                if (he) { const hr = he.getBoundingClientRect();
                    if (hr.width > 0 && hr.height > 0) { hh.push({ x: hr.left / hz, y: hr.top / hz, w: hr.width / hz, h: hr.height / hz, t: hn.t, pos: hn.pos || 'bottom' }); } }
            }
            tourHints.value = hh;
        } else { tourHints.value = []; }
        const cardEl = document.querySelector('#tourCardEl');
        if (cardEl) { const cz = _tourZoom(); const cr = cardEl.getBoundingClientRect(); tourCardRect.value = (cr.width > 0) ? { left: cr.left / cz, top: cr.top / cz, width: cr.width / cz, height: cr.height / cz } : null; } else { tourCardRect.value = null; }
        if (tourFakeEx.value) _sceneMeasureCursor();
    };
    const _tourTick = () => {
        _tourMeasure();
        if (tourActive.value && performance.now() < _tourMeasureUntil) { _tourRaf = requestAnimationFrame(_tourTick); }
        else { _tourRaf = 0; }
    };
    const _tourResetUI = () => {
        showAddPrinterModal.value = false;
        showModelPicker.value = false;
        cellAmsOpen.value = false;
        printMenuUid.value = null;
        ctxMenu.value = { show: false, x: 0, y: 0, items: [] };
        showDiag.value = false;
        showFileManager.value = false;
        exOpen.value = false;
        exPrintPid.value = '';
        exAmsOpen.value = false;
        tourMarks.value = [];
        tourHints.value = [];
    };
    const _tourApply = () => {
        const step = tourSteps.value[tourStep.value];
        if (!step) { tourBox.value = null; return; }
        _tourResetUI(); _tourSeedDemo();
        if (step.view && viewMode.value !== step.view) viewMode.value = step.view;   // нужный вид шага (компактная сетка / развёрнутая карточка)
        if (step.spot) { enterSpotlight([_TOUR_PID], 'st:' + _TOUR_FILE); } else if (spotlight.value.length) { exitSpotlight(); }
        if (step.scene && step.scene !== 'project') { _tourFakeStart(step.scene); } else { _tourFakeStop(); }   // демо-сцены файлов/диагностики; project — отдельная безопасная панель
        // (А) реальная раскрытая карточка демо-проекта (шаги 21–26): раскрываем напрямую, p2FlipRect=null → без flip-анимации, мгновенно. _tourSeedDemo уже сбросил project2Expanded в '' для остальных шагов.
        if (step.expandProject) { p2FlipRect.value = null; project2Expanded.value = 'proj_tour_demo'; }
        // Раскрытая карточка принтера (шаг «Управление»): делаем демо-карточку активной, чтобы показался пульт; иначе закрываем.
        if (step.expand) { activeModalPrinterId.value = _TOUR_PID; showModal.value = true; }
        else { showModal.value = false; activeModalPrinterId.value = null; }
        if (step.openSettings) { settingsPos.value = { top: 54, right: 14 }; showSettings.value = true; if (step.tab) settingsTab.value = step.tab; } else { showSettings.value = false; }
        if (step.sel === '#tour-demo-part') {
            openPlan.value = 'Demo Project';
            expandedProjects.value = Object.assign({}, expandedProjects.value, { 'Demo Project': true });
            editingProjects.value = Object.assign({}, editingProjects.value, { 'Demo Project': !!step.edit });
        } else {
            openPlan.value = null;
            if (editingProjects.value['Demo Project']) editingProjects.value = Object.assign({}, editingProjects.value, { 'Demo Project': false });
        }
        nextTick(() => {
            try { const el = document.querySelector(step.sel); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' }); } catch (e) {}
            window.scrollTo(_savedWin.x, _savedWin.y);   // только внутренние контейнеры скроллятся; окно — на месте
            const measureMs = step.marks && step.marks.length ? 1800 : 560;
            _tourMeasureUntil = performance.now() + measureMs;   // шаги с нумерованными метками дольше отслеживают сдвиги, например после появления превью
            if (_tourRaf) cancelAnimationFrame(_tourRaf);
            _tourRaf = requestAnimationFrame(_tourTick);
        });
    };
    let _tourOrigFetch = null;
    const _tourBlockFetch = () => {
        if (_tourOrigFetch) return;
        _tourOrigFetch = window.fetch;
        window.fetch = (u, o) => {
            const m = ((o && o.method) || 'GET').toUpperCase();
            if (m !== 'GET' && String(u).indexOf('/api/') !== -1) {
                return Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }));
            }
            return _tourOrigFetch(u, o);
        };
    };
    const _tourUnblockFetch = () => { if (_tourOrigFetch) { window.fetch = _tourOrigFetch; _tourOrigFetch = null; } };
    const _tourOnLayoutChange = () => { if (tourActive.value) _tourRefreshMeasure(900); };
    const _tourOnKey = (ev) => {
        if (!tourActive.value || !ev) return;
        const target = ev.target;
        const tag = target && target.tagName ? String(target.tagName).toLowerCase() : '';
        if (tag === 'input' || tag === 'textarea' || tag === 'select' || (target && target.isContentEditable)) return;
        if (ev.key === 'Escape') { ev.preventDefault(); endTour(); return; }
        if (ev.key === 'ArrowRight' || ev.key === 'Enter') { ev.preventDefault(); tourNext(); return; }
        if (ev.key === 'ArrowLeft') { ev.preventDefault(); tourPrev(); }
    };
    const startTour = (mode = 'full', startIndex = 0) => {
        showTourStartDialog.value = false;
        if (!TOUR_ENABLED) return;   // обучение выключено (решение владельца 12.09.2026): тур не стартует ниоткуда
        if (!Number.isFinite(startIndex) || startIndex <= 0) _tourSetCompleted(false);
        tourMode.value = (mode === 'quick') ? 'quick' : 'full';
        tourSteps.value = _tourStepsForMode(tourMode.value);
        const idx = Number.isFinite(startIndex) ? startIndex : 0;
        tourStep.value = Math.max(0, Math.min(tourSteps.value.length - 1, idx));
        tourMoreOpen.value = false;
        tourActive.value = true;
        _tourBlockFetch();
        // ГАРАНТИЯ снятия песочницы fetch: если запуск тура упадёт ПОСЛЕ _tourBlockFetch,
        // window.fetch не должен остаться в песочнице — иначе все POST/PUT в /api/ молча
        // "проглатываются" (фейковый 200) и сохранения не проходят до перезагрузки страницы.
        // endTour() (ниже) снимает песочницу первым делом и откатывает демо-данные; ошибку
        // не прячем — прокидываем дальше, чтобы она попала в диагностику.
        try {
            _tourInject();
            _tourSaveProgress();
            _savedWin = { x: window.scrollX, y: window.scrollY };
            window.addEventListener("resize", _tourOnLayoutChange);
            if (window.visualViewport) window.visualViewport.addEventListener("resize", _tourOnLayoutChange);
            window.addEventListener("scroll", _tourOnLayoutChange, true);
            window.removeEventListener("keydown", _tourOnKey);
            window.addEventListener("keydown", _tourOnKey);
            nextTick(_tourApply);
        } catch (e) {
            endTour();
            throw e;
        }
    };
    const resumeTour = () => {
        if (!TOUR_ENABLED) return;   // обучение выключено (решение владельца 12.09.2026)
        const saved = _tourLoadProgress();
        if (!saved) { startTour('full'); return; }
        startTour(saved.mode, saved.stepIndex);
    };
    const _tourMoveTo = (i) => { i = Math.max(0, Math.min(tourSteps.value.length - 1, i)); if (i === tourStep.value) return; tourMoreOpen.value = false; tourStep.value = i; const _st = tourSteps.value[i]; p2FlipRect.value = null; project2Expanded.value = (_st && _st.expandProject) ? 'proj_tour_demo' : '';   /* раскрываем/сворачиваем демо-проект сразу при навигации (данные уже подсеяны), а не на следующий тик — иначе свёрнутая карточка мелькает */ _tourSaveProgress(); nextTick(_tourApply); };
    const tourNext = () => { if (tourStep.value >= tourSteps.value.length - 1) { endTour(true); return; } _tourMoveTo(tourStep.value + 1); };
    const tourPrev = () => { if (tourStep.value <= 0) return; _tourMoveTo(tourStep.value - 1); };
    const tourGoTo = (i) => { _tourMoveTo(i); };
    const tourSkipGroup = () => { const b = currentTourGroupBounds.value; if (b.last >= 0 && b.last < tourSteps.value.length - 1) tourGoTo(b.last + 1); else endTour(true); };
    const endTour = (completed = false) => {
        _tourUnblockFetch();   // ГАРАНТИЯ: снять песочницу fetch ПЕРВЫМ делом — ДО сохранения прогресса,
                               // чтобы ошибка в _tourSaveProgress/_tourClearProgress не оставила fetch в песочнице.
        if (completed) { _tourClearProgress(); _tourSetCompleted(true); }
        else _tourSaveProgress();
        _tourRestore(); _tourFakeStop(); tourActive.value = false; tourBox.value = null;
        if (_tourRaf) { cancelAnimationFrame(_tourRaf); _tourRaf = 0; }
        window.removeEventListener("resize", _tourOnLayoutChange);
        if (window.visualViewport) window.visualViewport.removeEventListener("resize", _tourOnLayoutChange);
        window.removeEventListener("scroll", _tourOnLayoutChange, true); window.removeEventListener("keydown", _tourOnKey);
        window.scrollTo(_savedWin.x, _savedWin.y);
        if (!completed) _tourRefreshSavedProgress();
    };

    // ------------------------------------------------------------------------
    // БЛОК: настоящее окно live-диагностики и дельта-опрос журнала.
    // ------------------------------------------------------------------------
    const showDiag = ref(false);
    // Alpha 2.816: какой экран занимает центральную рабочую область. Источник истины — showSettings/showDiag
    // (их открытие взаимоисключающее). 'projects' — обычная область проектов и задач. <main> держится через
    // v-show (DOM не уничтожается), поэтому выбор проекта, поиск, фильтры, раскрытые строки и прокрутка
    // переживают уход в «Настройки»/«Диагностику» и возвращаются нетронутыми.
    const workspaceView = computed(() => showSettings.value ? 'settings' : (showDiag.value ? 'diagnostics' : (showPrinterFiles.value ? 'printerFiles' : (showReports.value ? 'reports' : 'projects'))));
    const diagEntries = ref([]);
    const diagFilter = ref('all');
    const diagVerbose = ref(false);
    const diagAutoscroll = ref(true);
    const diagFilters = [{ id: 'all', label: 'All' }, { id: 'info', label: 'Info+' }, { id: 'warn', label: 'Warnings' }, { id: 'error', label: 'Errors' }];
    let diagLastId = 0, diagTimer = null;
    const diagLevelClass = (lvl) => lvl === 'ERROR' ? 'lvl-error' : (lvl === 'WARNING' ? 'lvl-warning' : (lvl === 'INFO' ? 'lvl-info' : 'lvl-debug'));
    const diagTime = (ts) => { try { return new Date(ts * 1000).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' }); } catch (e) { return ''; } };
    // Alpha 2.813: поиск идёт по УЖЕ полученным безопасным строкам. На сервер он не уходит вовсе:
    // выполнять пользовательский шаблон поиска на бэкенде незачем и небезопасно.
    const diagSearch = ref('');
    const diagPaused = ref(false);
    const diagLostConnection = ref(false);
    const diagFiltered = computed(() => {
        const f = diagFilter.value, arr = diagEntries.value;
        let out = arr;
        if (f === 'error') out = arr.filter(e => e.level === 'ERROR');
        else if (f === 'warn') out = arr.filter(e => e.level === 'ERROR' || e.level === 'WARNING');
        else if (f !== 'all') out = arr.filter(e => e.level !== 'DEBUG');   // info+
        const q = diagSearch.value.trim().toLowerCase();
        if (!q) return out;
        return out.filter(e => (String(e.msg || '') + ' ' + String(e.source || '')).toLowerCase().includes(q));
    });
    const diagStateText = computed(() => {
        if (diagLostConnection.value) return lang.value === 'ru' ? 'Соединение потеряно' : 'Connection lost';
        if (diagPaused.value) return lang.value === 'ru' ? 'Приостановлено' : 'Paused';
        return lang.value === 'ru' ? 'В реальном времени' : 'Live';
    });
    // Текст для копирования и сохранения строится из ВИДИМЫХ записей — тех же безопасных строк,
    // что показаны на экране. Другого источника у этих кнопок нет.
    const diagVisibleText = () => diagFiltered.value
        .map(e => diagTime(e.ts) + '  ' + String(e.level || '') + '  ' + String(e.source || '') + '  ' + String(e.msg || ''))
        .join('\n');
    const copyDiag = async () => {
        const text = diagVisibleText();
        try { await navigator.clipboard.writeText(text); pushToast(lang.value === 'ru' ? 'Записи скопированы' : 'Entries copied'); }
        catch (e) { pushToast(lang.value === 'ru' ? 'Не удалось скопировать' : 'Copy failed', 'warn'); }
    };
    const exportDiag = () => {
        try {
            const blob = new Blob([diagVisibleText()], { type: 'text/plain;charset=utf-8' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'farm-manager-log.txt';
            a.click();
            setTimeout(() => URL.revokeObjectURL(a.href), 5000);
        } catch (e) { pushToast(lang.value === 'ru' ? 'Не удалось сохранить файл' : 'Save failed', 'warn'); }
    };
    const toggleDiagPause = () => {
        diagPaused.value = !diagPaused.value;
        // После продолжения дочитываем ровно то, что накопилось: нумерация записей сквозная,
        // поэтому ни одна строка не теряется и не показывается дважды.
        if (!diagPaused.value) fetchDiag();
    };
    const diagScrollBottom = () => { try { const el = document.getElementById('diagBody'); if (el) el.scrollTop = el.scrollHeight; } catch (e) {} };
    const fetchDiag = async () => {
        if (diagPaused.value) return;      // пауза: экран не трогаем, номер последней записи храним
        try {
            const r = await fetch('/api/diagnostics?since=' + diagLastId + '&limit=250');
            if (!r.ok) { diagLostConnection.value = (r.status !== 401 && r.status !== 403); return; }
            const j = await r.json();
            diagLostConnection.value = false;
            diagVerbose.value = !!j.verbose;
            if (j.entries && j.entries.length) {
                for (const e of j.entries) { diagEntries.value.push(e); if (e.id > diagLastId) diagLastId = e.id; }
                if (diagEntries.value.length > 1200) diagEntries.value.splice(0, diagEntries.value.length - 1200);   // не копим бесконечно в памяти вкладки
                if (diagAutoscroll.value) nextTick(diagScrollBottom);
            }
        } catch (e) {
            // Сервер мог перезапуститься (в т.ч. со сменой порта). Показываем честное состояние —
            // окно не зависает молча; следующий успешный опрос сам снимет признак.
            diagLostConnection.value = true;
        }
    };
    const openDiagnostics = () => {
        // Alpha 2.816: «Диагностика» — рабочий экран основной области, а не окно. Настройки занимают
        // тот же слот, поэтому уводим их, если открыты (deep-link/трей могут открыть журнал из любого места).
        if (showSettings.value) closeSettings();
        if (showPrinterFiles.value) closePrinterFiles();   // Alpha 2.823: тот же слот
        if (showReports.value) closeReports();             // Alpha 2.898: тот же слот
        showDiag.value = true; diagEntries.value = []; diagLastId = 0;
        diagPaused.value = false; diagLostConnection.value = false;
        fetchDiag();
        if (diagTimer) clearInterval(diagTimer);
        diagTimer = setInterval(fetchDiag, 1500);   // живой опрос дельты раз в 1.5с, пока панель открыта
        if (diagTab.value === 'conn') setDiagTab('conn');   // возобновить авто-обновление вкладки «Связь»
        if (diagTab.value === 'queue') refreshDurableQueue();   // Alpha 2.627: обновить снимок durable-очереди при повторном открытии
    };
    const diagWheel = (e) => { if (!e.target.closest('.diag-body')) e.preventDefault(); };   // колесо вне списка журнала не крутит страницу позади
    const closeDiagnostics = () => { showDiag.value = false; if (diagTimer) { clearInterval(diagTimer); diagTimer = null; } if (connTimer) { clearInterval(connTimer); connTimer = null; } if (_liveTrendTimer) { clearInterval(_liveTrendTimer); _liveTrendTimer = null; } if (sniffTimer) { clearInterval(sniffTimer); sniffTimer = null; } };

    // ══════════════════════════════════════════════════════════════════════════
    // БЛОК: «Файлы принтеров» (Alpha 2.823, экспериментально) — статичный workspace-экран
    // по контракту 2.816/2.817. UI оперирует ТОЛЬКО непрозрачными refs от сервера; путей,
    // IP и credentials здесь нет. Удаление доступно лишь когда сервер разрешил (флаг +
    // права) — и всё равно каждый запрос перепроверяется на сервере.
    // ══════════════════════════════════════════════════════════════════════════
    const showPrinterFiles = ref(false);
    const pfPrinterId = ref('');
    const pfCapsResp = ref(null);      // весь ответ /capabilities (флаги + caps + printer)
    //  2.989: предпросмотр файла. Картинку кладёт в файл слайсер: у Bambu она внутри .3mf,
    //  у Klipper лежит рядом и отдаётся Moonraker'ом. Программа ничего не дорисовывает —
    //  нет картинки, значит показываем причину, а не пустую рамку.
    const pfPreview = ref(null);       // { entry, url, state: 'loading'|'ready'|'error', reason }
    let _pfPreviewSeq = 0;             // номер запроса: ответ на устаревший не показываем
    const pfStorages = ref([]);
    const pfStorageId = ref('');
    const pfPath = ref([]);            // хлебные крошки: [{ref, name}]; пусто = корень
    const pfEntries = ref([]);
    const pfState = ref('idle');       // idle|loading|ready|empty|unsupported|offline|error|nostorage|readdisabled
    const pfReason = ref('');
    const pfSearch = ref('');
    const pfCat = ref('');             // ''|program|timelapse|video|image|log|other
    const pfAge = ref(0);              // 0|7|30|90 (дней; только при достоверной дате)
    const pfSortKey = ref('name');
    const pfSortDir = ref(1);
    const pfSelected = ref(new Set());
    const pfBusy = ref(false);
    const pfDeleteBusy = ref(false);
    const pfFlags = ref({ read_enabled: true, delete_enabled: false, delete_ui_allowed: false });
    const pfAdapterSummary = ref([]);  // для карточки настроек: [{name, text}]
    const pfFlagsBusy = ref(false);
    let _pfGen = 0;                    // защита от stale-ответов после смены принтера/закрытия
    const pfCaps = computed(() => (pfCapsResp.value && pfCapsResp.value.capabilities) || null);
    const pfDeleteAllowed = computed(() => !!(pfFlags.value.delete_enabled && pfFlags.value.delete_ui_allowed
        && pfCaps.value && pfCaps.value.delete_files));
    const pfStorage = computed(() => (pfStorages.value || []).find(s => s.storage_id === pfStorageId.value) || null);
    const pfReasonText = (r) => {
        const ru = lang.value === 'ru';
        const map = {
            unsupported: ru ? 'Файловый доступ для этого принтера пока не поддерживается' : 'File access is not supported for this printer yet',
            no_credentials: ru ? 'Не задан код доступа принтера — файловый доступ невозможен' : 'Printer access code is not configured',
            read_disabled: ru ? 'Чтение файлов с принтеров выключено в настройках' : 'Reading printer files is disabled in settings',
            storage_offline: ru ? 'Накопитель не найден или извлечён' : 'Storage not found or removed',
            read_only: ru ? 'Только чтение' : 'Read only',
            file_busy: ru ? 'Файл занят принтером' : 'File is busy',
            active_print_file: ru ? 'Файл текущей печати' : 'Active print file',
            stale_reference: ru ? 'Список устарел — обновите' : 'Listing is stale — refresh',
            not_found: ru ? 'Файл не найден' : 'Not found',
            permission_denied: ru ? 'Недостаточно прав' : 'Permission denied',
            delete_disabled: ru ? 'Удаление выключено предохранителем' : 'Deletion is disabled by the safety switch',
            timeout: ru ? 'Принтер не ответил (таймаут)' : 'Printer did not respond (timeout)',
            connection_lost: ru ? 'Принтер недоступен' : 'Printer is unreachable',
            file_not_printable: ru ? 'Этот файл нельзя напечатать' : 'This file cannot be printed',
            printer_offline: ru ? 'Принтер не в сети' : 'Printer is offline',
            printer_busy: ru ? 'Принтер занят' : 'Printer is busy',
            print_from_storage_unsupported: ru ? 'Печать с этого накопителя не поддерживается' : 'Printing from this storage is not supported',
            preflight_failed: ru ? 'Предстартовая проверка не пройдена' : 'Preflight check failed',
            //  2.989: предпросмотр. Обе причины — не поломка, а честный ответ.
            no_preview: ru ? 'В этом файле нет картинки предпросмотра' : 'This file has no preview image',
            too_large: ru ? 'Файл слишком велик, чтобы качать его ради картинки' : 'The file is too large to download just for a preview',
            delete_unconfirmed: ru ? 'Удаление не подтверждено принтером' : 'Deletion not confirmed by the printer',
            partial_failure: ru ? 'Часть операций не выполнена' : 'Some operations failed',
            system_file: ru ? 'Служебный файл — защищён' : 'System file — protected',
            directory: ru ? 'Папка' : 'Directory',
            printing_delete_unverified: ru ? 'Идёт печать — удаление заблокировано' : 'Printing — deletion is blocked',
            malformed_response: ru ? 'Некорректный ответ принтера' : 'Malformed printer response',
            bad_request: ru ? 'Некорректный запрос' : 'Bad request',
        };
        return map[r] || (ru ? 'Ошибка чтения' : 'Read error');
    };
    const pfCatText = (e) => {
        const ru = lang.value === 'ru';
        if (e.is_directory) return ru ? 'Папка' : 'Folder';
        const m = { program: ru ? 'Программа' : 'Program', video: ru ? 'Видео' : 'Video',
                    image: ru ? 'Изображение' : 'Image', log: ru ? 'Журнал' : 'Log', other: ru ? 'Прочее' : 'Other' };
        return m[e.category] || m.other;
    };
    const pfFmtSize = (b) => {
        if (b === null || b === undefined) return '—';
        const u = lang.value === 'ru' ? ['Б', 'КБ', 'МБ', 'ГБ'] : ['B', 'KB', 'MB', 'GB'];
        let v = Number(b) || 0, i = 0;
        while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
        return (i ? v.toFixed(1) : Math.round(v)) + ' ' + u[i];
    };
    const pfFmtDate = (t) => {
        if (!t) return lang.value === 'ru' ? 'Дата неизвестна' : 'Date unknown';
        try { return new Date(t * 1000).toLocaleDateString(lang.value === 'ru' ? 'ru-RU' : 'en-GB',
            { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }
        catch (e) { return lang.value === 'ru' ? 'Дата неизвестна' : 'Date unknown'; }
    };
    const pfRowsView = computed(() => {
        let arr = pfEntries.value || [];
        const c = pfCat.value;
        if (c === 'timelapse') arr = arr.filter(e => e.is_directory || (e.category === 'video' && e.timelapse));
        else if (c) arr = arr.filter(e => e.is_directory || e.category === c);
        const age = pfAge.value | 0;
        if (age > 0) {
            const cutoff = Date.now() / 1000 - age * 86400;
            // «старше N дней» — ТОЛЬКО при достоверной дате; без даты файл в фильтр не попадает
            arr = arr.filter(e => e.is_directory || (e.modified_at && e.modified_at < cutoff));
        }
        const q = pfSearch.value.trim().toLowerCase();
        if (q) arr = arr.filter(e => String(e.name || '').toLowerCase().includes(q));
        const k = pfSortKey.value, d = pfSortDir.value;
        arr = arr.slice().sort((a, b) => {
            if (a.is_directory !== b.is_directory) return a.is_directory ? -1 : 1;   // папки всегда сверху
            let x, y;
            if (k === 'size') { x = a.size_bytes ?? -1; y = b.size_bytes ?? -1; }
            else if (k === 'date') { x = a.modified_at ?? -1; y = b.modified_at ?? -1; }
            else { x = String(a.name || '').toLowerCase(); y = String(b.name || '').toLowerCase(); }
            return (x < y ? -1 : (x > y ? 1 : 0)) * d;
        });
        return arr;
    });
    const pfSetSort = (k) => { if (pfSortKey.value === k) pfSortDir.value = -pfSortDir.value; else { pfSortKey.value = k; pfSortDir.value = 1; } };
    const pfSummary = computed(() => {
        const files = (pfEntries.value || []).filter(e => !e.is_directory);
        const size = files.reduce((s, e) => s + (e.size_bytes || 0), 0);
        const selEntries = files.filter(e => pfSelected.value.has(e.file_ref));
        const selSize = selEntries.reduce((s, e) => s + (e.size_bytes || 0), 0);
        // Alpha 2.825: подмножества выбора считаются ОТДЕЛЬНО — выбор не зависит от delete
        const selDeletable = selEntries.filter(e => e.deletable);
        const selPrintable = selEntries.filter(e => e.printable);
        const selNoSize = selEntries.filter(e => e.size_bytes == null).length;
        return { count: files.length, size, sel: selEntries.length, selSize,
                 selEntries, selDeletable, selPrintable, selNoSize };
    });
    // Ровно один выбранный printable-файл — единственная цель печати (multi-select печать не даёт).
    const pfPrintTarget = computed(() => {
        const s = pfSummary.value;
        return (s.sel === 1 && s.selPrintable.length === 1) ? s.selPrintable[0] : null;
    });
    // Причина блокировки печати (пусто = можно): те же правила занятости, что у карточки (cellBusy).
    const pfPrintBlockReason = computed(() => {
        const ru = lang.value === 'ru';
        const s = pfSummary.value;
        if (!s.sel) return ru ? 'Выберите файл' : 'Select a file';
        if (s.sel > 1) return ru ? 'Для печати выберите один файл' : 'Select a single file to print';
        if (!pfPrintTarget.value) return ru ? 'Этот файл нельзя напечатать' : 'This file cannot be printed';
        const pid = pfPrinterId.value;
        const st = (wsData.value[pid] && wsData.value[pid].status) || 'OFFLINE';
        if (st === 'OFFLINE') return ru ? 'Принтер не в сети' : 'Printer is offline';
        if (cellBusy(pid) || st === 'PREPARE' || st === 'PAUSED') return ru ? 'Принтер занят' : 'Printer is busy';
        return '';
    });
    const _pfJson = async (url, opts) => {
        const r = await fetch(url, opts);
        return await r.json().catch(() => null);
    };
    const pfLoadFlags = async () => {
        // Флаги + сводка адаптеров для карточки настроек. capabilities статичен (без сети к устройству).
        try {
            const list = printers.value || [];
            const out = [];
            for (const p of list) {
                const j = await _pfJson('/api/printer-files/capabilities?printer_id=' + encodeURIComponent(p.id));
                if (j && j.status === 'ok') {
                    pfFlags.value = { read_enabled: !!j.read_enabled, delete_enabled: !!j.delete_enabled, delete_ui_allowed: !!j.delete_ui_allowed };
                    const c = j.capabilities || {};
                    const ru = lang.value === 'ru';
                    out.push({ name: p.name, text: !c.supported ? pfReasonText(c.reason || 'unsupported')
                        : (c.delete_files ? (ru ? 'просмотр и удаление' : 'browse & delete') : (ru ? 'только просмотр' : 'read only')) });
                }
            }
            pfAdapterSummary.value = out;
        } catch (e) {}
    };
    const pfSetFlag = async (key, val) => {
        if (pfFlagsBusy.value) return;
        pfFlagsBusy.value = true;
        try {
            const body = {}; body[key] = !!val;
            const j = await _pfJson('/api/printer-files/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            if (j && j.status === 'ok') { pfFlags.value = { ...pfFlags.value, read_enabled: !!j.read_enabled, delete_enabled: !!j.delete_enabled }; }
            else if (j && j.error) alert(lang.value === 'ru' ? 'Недостаточно прав (нужен системный администратор).' : 'Not enough permissions (system admin required).');
        } catch (e) {} finally { pfFlagsBusy.value = false; }
    };
    // Alpha 2.827: резервное копирование конфигурации (Настройки → Система, только админ/локально).
    const cbBusy = ref(false);
    const cbProtect = ref(false);          // Alpha 2.828: «Защитить резервную копию паролем», по умолчанию OFF
    const cbExportPw = ref('');
    const cbExportPw2 = ref('');           // подтверждение пароля
    const cbImportPw = ref('');
    const cbImportName = ref('');
    const cbImportB64 = ref('');
    const cbImportRequiresPw = ref(false); // из inspect: требует ли выбранная копия пароль
    const cbPlan = ref(null);
    const cbInfo = ref(null);
    const cbMsg = ref(null);
    const cbDone = ref(null);              // панель результата восстановления { restart_required }
    const cbPendingRestart = ref(false);   // ненавязчивый индикатор «Требуется перезапуск»
    // R-125: модули, которые пользователь исключил из восстановления («Восстановить без этого
    // модуля»). План и применение идут с ОДНИМ списком; смена файла его сбрасывает.
    const cbExclude = ref([]);
    const cbReasonText = (r) => {
        const ru = lang.value === 'ru';
        const m = {
            backup_corrupted_or_wrong_password: ru ? 'Неверный пароль или файл повреждён.' : 'Wrong password or corrupted file.',
            backup_from_newer_version: ru ? 'Копия из более новой версии программы.' : 'Backup from a newer app version.',
            unsupported_format: ru ? 'Неподдерживаемый формат файла.' : 'Unsupported file format.',
            validation_failed: ru ? 'Копия не прошла проверку.' : 'Backup failed validation.',
            active_prints: ru ? 'Идёт печать — восстановление запрещено.' : 'A print is active — restore is blocked.',
            restore_locked: ru ? 'Восстановление уже выполняется.' : 'A restore is already running.',
            rollback_completed: ru ? 'Не удалось применить — изменения отменены.' : 'Apply failed — changes were rolled back.',
            weak_encryption_params: ru ? 'Задайте пароль.' : 'Enter a password.',
            backup_invalid: ru ? 'Некорректный файл копии.' : 'Invalid backup file.'
        };
        return m[r] || (ru ? 'Не удалось выполнить операцию.' : 'Operation failed.');
    };
    // Alpha 2.830: понятное сообщение из СТРУКТУРНОГО безопасного ответа (reason+section+module_id)
    // без раскрытия значений. «Не удалось выполнить операцию.» больше не единственный текст.
    const cbErrorText = (j) => {
        const ru = lang.value === 'ru';
        j = j || {};
        const reason = j.reason;
        if (reason === 'validation_failed' && j.section === 'modules' && j.module_id) {
            const name = cbModLabel(j.module_id);
            return (ru ? ('Резервная копия не прошла проверку данных модуля «' + name + '». Файл не был применён.')
                       : ('The backup failed data validation for module "' + name + '". Nothing was applied.'))
                   + (ru ? ' Код: ' : ' Code: ') + j.module_id + '_snapshot_invalid';
        }
        if (reason === 'manual_resolution_required' && j.module_id && j.field_path) {
            // R-125: модуль установлен, но его данные сюда не ложатся (модуль старее копии или
            // номер из копии уже занят) — причину план показывает строкой выше.
            return ru ? ('Данные модуля «' + cbModLabel(j.module_id) + '» нельзя применить на этом компьютере — причина указана в плане восстановления. Ничего не изменено.')
                      : ('The data of module "' + cbModLabel(j.module_id) + '" cannot be applied on this computer — see the reason in the restore plan. Nothing was changed.');
        }
        if (reason === 'manual_resolution_required' && j.module_id) {
            return ru ? ('Для восстановления данных требуется модуль «' + cbModLabel(j.module_id) + '».')
                      : ('Restoring the data requires the module "' + cbModLabel(j.module_id) + '".');
        }
        return cbReasonText(reason);
    };
    // R-125/R-128: предупреждения плана с известным кодом — по-русски и по-английски, с названием
    // модуля; остальные — текстом сервера, как раньше.
    const cbWarnText = (w) => {
        const ru = lang.value === 'ru';
        w = w || {};
        const name = cbModLabel(w.module_id || '');
        const n = Number(w.count || 0);
        if (w.code === 'security_held_no_admin') {
            return ru ? 'В копии включена защита входом, но на этом компьютере нет администратора. Защита останется выключенной: создайте администратора в «Доступ и аудит».'
                      : 'The backup has sign-in protection enabled, but this computer has no administrator. Protection stays off: create an administrator in "Access & audit".';
        }
        if (w.code === 'module_not_initialized') {
            return ru ? ('Модуль «' + name + '» на этом компьютере ещё ни разу не запускался. Включите его в «Модулях», перезапустите программу и повторите восстановление — или восстановите без этого модуля.')
                      : ('The "' + name + '" module has never run on this computer. Enable it in Modules, restart the app and restore again — or restore without this module.');
        }
        if (w.code === 'module_tables_missing') {
            return ru ? ('Модуль «' + name + '» на этом компьютере старее копии. Обновите модуль и повторите восстановление.')
                      : ('The "' + name + '" module on this computer is older than the backup. Update the module and restore again.');
        }
        if (w.code === 'module_restore_conflict') {
            if (w.table === 'orders') {
                return ru ? ('Номера заказов из копии уже заняты другими заказами на этом компьютере: ' + n + '. Измените номера этих заказов в «Расчёте заказа» и повторите восстановление — или восстановите без этого модуля: его заказы здесь останутся как есть.')
                          : ('Order numbers from the backup are already used by other orders on this computer: ' + n + '. Change those order numbers in Order calculation and restore again — or restore without this module: its orders here stay as they are.');
            }
            return ru ? ('Записи модуля «' + name + '» из копии конфликтуют с данными на этом компьютере: ' + n + '.')
                      : ('Records of the "' + name + '" module in the backup conflict with data on this computer: ' + n + '.');
        }
        if (w.code === 'legacy_cost_not_restored') {
            return ru ? ('Данные прежней «Себестоимости печати» из этой копии не восстанавливаются — «Расчёт заказа» их не использует. Записей: ' + n + '.')
                      : ('Data of the former Print cost module in this backup is not restored — Order calculation does not use it. Records: ' + n + '.');
        }
        return w.text || '';
    };
    const cbExport = async () => {
        if (cbBusy.value) return;
        const ru = lang.value === 'ru';
        let payload = { protection_mode: 'none' };
        if (cbProtect.value) {
            if (!cbExportPw.value) { cbMsg.value = { ok: false, text: cbReasonText('weak_encryption_params') }; return; }
            if (cbExportPw.value !== cbExportPw2.value) { cbMsg.value = { ok: false, text: ru ? 'Пароли не совпадают.' : 'Passwords do not match.' }; return; }
            payload = { protection_mode: 'password_aes256gcm', passphrase: cbExportPw.value };
        }
        cbBusy.value = true; cbMsg.value = null;
        try {
            const resp = await fetch('/api/config-backup/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            if (!resp.ok) { let j = {}; try { j = await resp.json(); } catch (e) {} cbMsg.value = { ok: false, text: cbErrorText(j) }; return; }
            const blob = await resp.blob();
            const cd = resp.headers.get('Content-Disposition') || '';
            const mm = /filename="([^"]+)"/.exec(cd);
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = (mm && mm[1]) || '3diwell-config.3diwell-backup';
            document.body.appendChild(a); a.click(); a.remove();
            setTimeout(() => { try { URL.revokeObjectURL(a.href); } catch (e) {} }, 4000);
            cbExportPw.value = ''; cbExportPw2.value = '';
            cbMsg.value = { ok: true, text: cbProtect.value
                ? (ru ? 'Резервная копия создана. Храните файл и пароль вместе — без пароля восстановить нельзя.' : 'Backup created. Keep the file and password together — it cannot be restored without the password.')
                : (ru ? 'Резервная копия создана без пароля. Храните файл в защищённом месте.' : 'Backup created without a password. Keep the file in a safe place.') };
        } catch (e) { cbMsg.value = { ok: false, text: cbReasonText('backup_invalid') }; }
        finally { cbBusy.value = false; }
    };
    const cbPhase = ref('idle');             // idle|checking|password|preparing|ready|error
    let _cbFileToken = 0;                    // stale-guard: план принадлежит КОНКРЕТНОМУ файлу
    const cbPickImport = async (ev) => {
        // Alpha 2.829 AUTO-PLAN: выбор файла сам ведёт к плану. Passwordless -> план сразу;
        // protected -> поле пароля, план строится после ввода (Enter/Продолжить) без отдельной
        // кнопки «Показать план восстановления». Смена файла делает прежний план stale.
        const token = ++_cbFileToken;
        cbPlan.value = null; cbInfo.value = null; cbMsg.value = null; cbDone.value = null;
        cbImportRequiresPw.value = false; cbImportPw.value = ''; cbPhase.value = 'idle';
        cbExclude.value = [];
        const f = ev && ev.target && ev.target.files && ev.target.files[0];
        if (!f) { cbImportName.value = ''; cbImportB64.value = ''; return; }
        cbImportName.value = f.name;
        cbPhase.value = 'checking';
        const b64 = await new Promise((res) => {
            const rd = new FileReader();
            rd.onload = () => { const s = String(rd.result || ''); const i = s.indexOf('base64,'); res(i >= 0 ? s.slice(i + 7) : ''); };
            rd.onerror = () => res('');
            rd.readAsDataURL(f);
        });
        if (token !== _cbFileToken) return;                  // выбран другой файл — этот путь stale
        cbImportB64.value = b64;
        if (!b64) { cbPhase.value = 'error'; cbMsg.value = { ok: false, text: cbReasonText('backup_invalid') }; return; }
        // Режим копии — по безопасному header (пароль показываем ТОЛЬКО если файл его требует).
        try {
            const j = await _pfJson('/api/config-backup/inspect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ backup_b64: b64 }) });
            if (token !== _cbFileToken) return;
            if (j && j.status === 'ok' && j.info) {
                cbInfo.value = j.info; cbImportRequiresPw.value = !!j.info.requires_password;
                if (cbImportRequiresPw.value) { cbPhase.value = 'password'; }
                else { await cbInspect(token); }             // авто-план без пароля
            } else { cbPhase.value = 'error'; cbMsg.value = { ok: false, text: cbErrorText(j) }; }
        } catch (e) { cbPhase.value = 'error'; cbMsg.value = { ok: false, text: cbReasonText('backup_invalid') }; }
    };
    const cbInspect = async (token) => {
        if (cbBusy.value) return;
        const tok = (typeof token === 'number') ? token : _cbFileToken;
        if (!cbImportB64.value) { cbPhase.value = 'error'; cbMsg.value = { ok: false, text: cbReasonText('backup_invalid') }; return; }
        if (cbImportRequiresPw.value && !cbImportPw.value) { cbMsg.value = { ok: false, text: cbReasonText('weak_encryption_params') }; return; }
        cbBusy.value = true; cbMsg.value = null; cbPlan.value = null; cbDone.value = null;
        cbPhase.value = 'preparing';
        try {
            const req = { mode: 'plan', backup_b64: cbImportB64.value };
            if (cbImportRequiresPw.value) req.passphrase = cbImportPw.value;
            if (cbExclude.value.length) req.exclude_modules = cbExclude.value.slice();
            const j = await _pfJson('/api/config-backup/restore', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(req) });
            if (tok !== _cbFileToken) return;                 // stale-план другого файла не показываем
            if (j && j.status === 'ok' && j.mode === 'plan') { cbPlan.value = j.plan; cbInfo.value = j.info; cbPhase.value = 'ready'; }
            else { cbPhase.value = (cbImportRequiresPw.value ? 'password' : 'error'); cbMsg.value = { ok: false, text: cbErrorText(j) }; }
        } catch (e) { cbPhase.value = 'error'; cbMsg.value = { ok: false, text: cbReasonText('backup_invalid') }; }
        finally { cbBusy.value = false; }
    };
    const cbApply = async () => {
        if (cbBusy.value || !cbPlan.value || cbPlanBlocked()) return;
        const ru = lang.value === 'ru';
        if (!await askConfirm({ title: _L('Восстановить из резервной копии?', 'Restore from the backup?'),
                                text: _L('Текущие настройки и принтеры будут перезаписаны согласно плану.',
                                         'Current settings and printers will be overwritten per the plan.'),
                                okText: _L('Восстановить', 'Restore'), danger: true })) return;
        cbBusy.value = true; cbMsg.value = null;
        try {
            const req = { mode: 'apply', backup_b64: cbImportB64.value };
            if (cbImportRequiresPw.value) req.passphrase = cbImportPw.value;
            if (cbExclude.value.length) req.exclude_modules = cbExclude.value.slice();
            const j = await _pfJson('/api/config-backup/restore', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(req) });
            if (j && j.status === 'ok' && j.mode === 'apply') {
                cbPlan.value = null; cbImportB64.value = ''; cbImportName.value = ''; cbImportPw.value = ''; cbImportRequiresPw.value = false;
                const needRestart = !!(j.result && j.result.restart_required);
                cbDone.value = { restart_required: needRestart };
                cbPendingRestart.value = needRestart;
                if (needRestart) {
                    // Маркер живёт до появления НОВОГО процесса (boot_id) — закрытие панели
                    // «Позже» его НЕ снимает; снятие только после реального перезапуска.
                    try { if (!serverBootId.value) await fetchBootId(); localStorage.setItem('fm_pending_restart_boot', serverBootId.value || 'unknown'); } catch (e) {}
                }
                cbPhase.value = 'idle';
            } else { cbMsg.value = { ok: false, text: cbErrorText(j) }; }
        } catch (e) { cbMsg.value = { ok: false, text: cbReasonText('backup_invalid') }; }
        finally { cbBusy.value = false; }
    };
    // R-125: план, который применить нельзя (модуль не подходит этой установке). Выход —
    // исключить модуль: план строится заново, остальное восстановление проходит.
    const cbPlanBlocked = () => !!(cbPlan.value && cbPlan.value.module_data && cbPlan.value.module_data.blocked);
    const cbBlockedModules = () => (cbPlan.value && cbPlan.value.module_data && cbPlan.value.module_data.blocked_modules) || [];
    const cbExcludedModules = () => (cbPlan.value && cbPlan.value.module_data && cbPlan.value.module_data.excluded) || [];
    const cbSetExclude = async (mid, on) => {
        if (cbBusy.value || !mid) return;
        const cur = cbExclude.value.filter((x) => x !== mid);
        if (on) cur.push(mid);
        cbExclude.value = cur;
        await cbInspect();
    };
    const cbRestartLater = () => { cbDone.value = null; };   // индикатор cbPendingRestart остаётся
    const cbModLabel = (mid) => {
        const ru = lang.value === 'ru';
        const m = { inventory: ru ? 'Складской учёт' : 'Inventory', cost: ru ? 'Расчёт заказа' : 'Order calculation',
                    quality: ru ? 'Аналитика качества' : 'Quality analytics', appearance: ru ? 'Оформление и темы' : 'Appearance and themes',
                    camera_wall: ru ? 'Видеостена' : 'Camera Wall', messengers: ru ? 'Уведомления в мессенджеры' : 'Messenger notifications' };
        return m[mid] || mid;
    };
    const cbMbLabel = (k) => {
        const ru = lang.value === 'ru';
        const m = { data_dir: ru ? 'Папка данных' : 'Data folder', archive_dir: ru ? 'Папка архивов' : 'Archive folder',
                    server_port: ru ? 'Порт сервера' : 'Server port', slicer_path: ru ? 'Путь к слайсеру' : 'Slicer path' };
        return m[k] || k;
    };
    const _pfResetView = () => { pfStorages.value = []; pfStorageId.value = ''; pfPath.value = []; pfEntries.value = []; pfSelected.value = new Set(); pfReason.value = ''; };
    const pfSelectPrinter = async (pid) => {
        pfPrinterId.value = pid;
        try { localStorage.setItem('fm_pf_last_printer', pid); } catch (e) {}
        const gen = ++_pfGen;
        _pfResetView();
        if (!pid) { pfState.value = 'idle'; return; }
        pfState.value = 'loading'; pfBusy.value = true;
        try {
            const cj = await _pfJson('/api/printer-files/capabilities?printer_id=' + encodeURIComponent(pid));
            if (gen !== _pfGen) return;                       // stale-ответ прошлого принтера игнорируем
            pfCapsResp.value = (cj && cj.status === 'ok') ? cj : null;
            if (cj && cj.status === 'ok') pfFlags.value = { read_enabled: !!cj.read_enabled, delete_enabled: !!cj.delete_enabled, delete_ui_allowed: !!cj.delete_ui_allowed };
            if (!cj || cj.status !== 'ok') { pfState.value = 'error'; pfReason.value = (cj && cj.reason) || ''; return; }
            if (!cj.read_enabled) { pfState.value = 'readdisabled'; return; }
            const caps = cj.capabilities || {};
            if (!caps.supported) { pfState.value = 'unsupported'; pfReason.value = caps.reason || 'unsupported'; return; }
            const sj = await _pfJson('/api/printer-files/storages?printer_id=' + encodeURIComponent(pid));
            if (gen !== _pfGen) return;
            if (!sj || sj.status !== 'ok') {
                const r = (sj && sj.reason) || 'connection_lost';
                pfState.value = (r === 'timeout' || r === 'connection_lost') ? 'offline' : 'error';
                pfReason.value = r; return;
            }
            pfStorages.value = sj.storages || [];
            if (!pfStorages.value.length) { pfState.value = 'nostorage'; return; }
            await pfSelectStorage(pfStorages.value[0].storage_id, gen);
        } finally { if (gen === _pfGen) pfBusy.value = false; }
    };
    const pfSelectStorage = async (sid, gen) => {
        pfStorageId.value = sid; pfPath.value = []; pfSelected.value = new Set();
        await pfLoadList(false, gen);
    };
    const pfLoadList = async (fresh, genIn) => {
        const gen = genIn !== undefined ? genIn : ++_pfGen;
        pfState.value = 'loading'; pfBusy.value = true;
        try {
            const crumb = pfPath.value.length ? pfPath.value[pfPath.value.length - 1].ref : '';
            const j = await _pfJson('/api/printer-files/list', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ printer_id: pfPrinterId.value, storage_id: pfStorageId.value, directory_ref: crumb, fresh: !!fresh, limit: 1000 }) });
            if (gen !== _pfGen) return;                       // ответ для уже закрытого/сменённого вида
            if (!j || j.status !== 'ok') {
                const r = (j && j.reason) || 'connection_lost';
                if (r === 'stale_reference') { pfPath.value = []; return pfLoadList(true, gen); }   // одна корректирующая попытка от корня
                pfState.value = (r === 'timeout' || r === 'connection_lost') ? 'offline' : 'error';   // ошибка чтения НЕ показывается как пустой список
                pfReason.value = r; pfEntries.value = []; return;
            }
            pfEntries.value = j.entries || [];
            pfSelected.value = new Set();                     // старые refs недействительны после обновления
            pfState.value = pfEntries.value.length ? 'ready' : 'empty';
        } finally { if (gen === _pfGen) pfBusy.value = false; }
    };
    const pfOpenDir = async (e) => { if (!e.is_directory) return; pfPath.value = [...pfPath.value, { ref: e.file_ref, name: e.name }]; await pfLoadList(false); };
    const pfCrumbTo = async (i) => { pfPath.value = i < 0 ? [] : pfPath.value.slice(0, i + 1); await pfLoadList(false); };
    const pfRefresh = async () => { await pfLoadList(true); };
    // Alpha 2.825: выбор НЕЗАВИСИМ от удаления (selectable ≠ deletable ≠ printable).
    // Выбирается любой файл (не каталог); что с ним можно сделать — решают отдельные
    // подмножества pfSelDeletable / pfSelPrintable ниже.
    const pfSelectable = (e) => !!e && !e.is_directory;
    const pfToggleSel = (e) => {
        if (!pfSelectable(e)) return;
        const s = new Set(pfSelected.value);
        if (s.has(e.file_ref)) s.delete(e.file_ref); else s.add(e.file_ref);
        pfSelected.value = s;
    };
    const pfSelectShown = () => {
        // ТОЛЬКО выделение показанных (после фильтров) строк-файлов; ничего не удаляет и не печатает
        const s = new Set(pfSelected.value);
        for (const e of pfRowsView.value) if (pfSelectable(e)) s.add(e.file_ref);
        pfSelected.value = s;
    };
    const pfClearSel = () => { pfSelected.value = new Set(); };
    // Клик по строке = выбор (кроме кликов по кнопкам/чекбоксу/меню и по строке-каталогу).
    const pfRowClick = (ev, e) => {
        if (ev && ev.target && ev.target.closest && ev.target.closest('button, input, select, a, .pfw-rowmenu')) return;
        pfToggleSel(e);
    };
    const pfPresetOldPrograms = () => { pfCat.value = 'program'; if (!pfAge.value) pfAge.value = 30; };   // только фильтр, без выбора и удаления
    const _pfDeleteRun = async (refs) => {
        pfDeleteBusy.value = true;
        try {
            const j = await _pfJson('/api/printer-files/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ printer_id: pfPrinterId.value, file_refs: refs }) });
            const ru = lang.value === 'ru';
            if (!j) { alert(ru ? 'Нет ответа сервера.' : 'No server response.'); return; }
            if (j.error) { alert(ru ? 'Недостаточно прав (нужен системный администратор).' : 'Not enough permissions (system admin required).'); return; }
            if (j.status === 'error') { alert(pfReasonText(j.reason)); return; }
            const results = j.results || [];
            const failed = results.filter(r => !r.ok);
            if (failed.length) {
                const lines = failed.slice(0, 12).map(r => '• ' + (r.name || '?') + ' — ' + pfReasonText(r.reason));
                alert((ru ? 'Удалено: ' : 'Deleted: ') + (j.deleted || 0) + (ru ? '. Не удалось: ' : '. Failed: ') + failed.length + '\n' + lines.join('\n'));
            }
        } catch (e) {} finally {
            pfDeleteBusy.value = false;
            await pfLoadList(true);                            // список после удаления всегда перечитывается с устройства
        }
    };
    const pfDeleteOne = async (e) => {
        if (!pfDeleteAllowed.value || !e.deletable || e.is_directory || pfDeleteBusy.value) return;
        const ru = lang.value === 'ru';
        const st = pfStorage.value;
        const txt = ''
            + (ru ? 'Имя: ' : 'Name: ') + e.name + '\n'
            + (ru ? 'Тип: ' : 'Type: ') + pfCatText(e) + '\n'
            + (ru ? 'Размер: ' : 'Size: ') + pfFmtSize(e.size_bytes) + '\n'
            + (ru ? 'Принтер: ' : 'Printer: ') + ((pfCapsResp.value && pfCapsResp.value.printer && pfCapsResp.value.printer.name) || pfPrinterId.value) + '\n'
            + (ru ? 'Накопитель: ' : 'Storage: ') + (st ? st.display_name : pfStorageId.value) + '\n\n'
            ;
        if (!await askConfirm({ title: _L('Удалить файл с принтера?', 'Delete this file from the printer?'),
                                text: _L('Восстановление невозможно.', 'This cannot be undone.'), list: txt,
                                okText: _L('Удалить', 'Delete'), danger: true })) return;
        await _pfDeleteRun([e.file_ref]);
    };
    const pfDeleteSelected = async () => {
        if (!pfDeleteAllowed.value || pfDeleteBusy.value) return;
        const byRef = new Map((pfEntries.value || []).map(e => [e.file_ref, e]));
        const items = [...pfSelected.value].map(r => byRef.get(r)).filter(e => e && e.deletable && !e.is_directory);
        if (!items.length) return;
        const ru = lang.value === 'ru';
        const size = items.reduce((s, e) => s + (e.size_bytes || 0), 0);
        const nProg = items.filter(e => e.category === 'program').length;
        const nTl = items.filter(e => e.category === 'video' && e.timelapse).length;
        const names = items.slice(0, 12).map(e => '• ' + e.name).join('\n') + (items.length > 12 ? '\n…' : '');
        const txt = ''
            + (ru ? 'Файлов: ' : 'Files: ') + items.length + ' · ' + pfFmtSize(size) + '\n'
            + (ru ? 'Программ печати: ' : 'Print programs: ') + nProg + (ru ? ' · Таймлапсов: ' : ' · Timelapses: ') + nTl + '\n\n'
            + names;
        if (!await askConfirm({ title: _L('Удалить выбранные файлы с принтера?', 'Delete the selected files from the printer?'),
                                text: _L('Восстановление невозможно.', 'This cannot be undone.'), list: txt,
                                okText: _L('Удалить', 'Delete'), danger: true })) return;
        if (items.length > 20 && !await askConfirm({
                title: _L('Точно удалить ' + items.length + ' файлов?', 'Really delete ' + items.length + ' files?'),
                text: _L('Это безвозвратно.', 'This is permanent.'),
                okText: _L('Да, удалить', 'Yes, delete'), danger: true })) return;
        await _pfDeleteRun(items.map(e => e.file_ref));
    };
    // ═══ Alpha 2.825: «Выбрать для печати» и «Печать» — существующий C1-flow, никакой второй реализации ═══
    const pfActionBusy = ref(false);
    const pfCardPending = ref(null);       // { pid, name } — ожидание для старой выпадашки карточки
    // Resolve на backend: непрозрачная ссылка -> нормализованное имя (raw path из UI не уходит).
    const pfResolveForPrint = async () => {
        const t = pfPrintTarget.value;
        if (!t) return null;
        const j = await _pfJson('/api/printer-files/select-for-print', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ printer_id: pfPrinterId.value, file_ref: t.file_ref }) });
        if (!j || j.status !== 'ok') {
            const ru = lang.value === 'ru';
            const r = (j && j.reason) || 'connection_lost';
            pushToast(r === 'not_found' ? (ru ? 'Файл больше не найден' : 'File is no longer there') : pfReasonText(r), 'info');
            if (r === 'not_found' || r === 'stale_reference') { pfClearSel(); pfLoadList(true); }
            return null;
        }
        return { resolved: j, ref: t.file_ref };
    };
    const pfSelectForPrint = async () => {
        if (pfActionBusy.value || !pfPrintTarget.value) return;
        pfActionBusy.value = true;
        try {
            const got = await pfResolveForPrint();
            if (!got) return;
            const j = got.resolved;
            // Передаём в СУЩЕСТВУЮЩЕЕ состояние выбора файла карточки (старая выпадашка);
            // если модалка этого принтера открыта и файл в её списке — выбираем сразу.
            pfCardPending.value = { pid: j.printer_id, name: j.print_name };
            if (activeModalPrinterId.value === j.printer_id && (printerFiles.value || []).includes(j.print_name)) printFileName.value = j.print_name;
            const ru = lang.value === 'ru';
            pushToast(ru ? ('Файл выбран для печати: ' + j.name) : ('File selected for print: ' + j.name), 'info');
        } finally { pfActionBusy.value = false; }
    };
    // Отправка старта — ТОТ ЖЕ backend-flow, что кнопка PRINT карточки (C1 p_cmd start_print):
    // hold, compat-preflight, reservation/busy 409, панель отправок, lifecycle, аудит.
    const pfStartCmd = async (pid, printName, fileRef, amsSlot) => {
        const ru = lang.value === 'ru';
        const _ctx = { printer_id: pid, printer_name: _printerNameOf(pid), file_name: String(printName || '').split(/[\\/]/).pop(), source: 'printer_file' };
        const body = { cmd: 'start_print', val: printName, file_ref: fileRef || null };
        body.ams_slot = (amsSlot === null || amsSlot === undefined) ? null : Number(amsSlot);
        try {
            let j = await (await fetch('/api/printer/' + pid + '/cmd', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json().catch(() => ({}));
            if (j && j.status === 'incompatible') {
                // ПРЕЖНЕЕ подтверждение C1: отмена = ничего не запущено (ни job, ни reservation)
                if (!await askConfirm({ title: _L('Принтер не тот', 'Wrong printer'), text: tr(j.reason || 'The file is sliced for a different printer type.'), okText: _L('Печатать всё равно', 'Print anyway') })) return;
                body.force = true;
                j = await (await fetch('/api/printer/' + pid + '/cmd', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json().catch(() => ({}));
            }
            if (j && j.status === 'error') {
                pushToast((ru ? 'Печать не запущена: ' : 'Print not started: ') + pfReasonText(j.reason || 'connection_lost'), 'info');
                if (j.reason === 'not_found' || j.reason === 'stale_reference') { pfClearSel(); pfLoadList(true); }
                return;
            }
            if (handleSendResp(j, _ctx) === 'other') pushToast(tr('Print not started. ') + tr((j && j.reason) || ''), 'info');
        } catch (e) { pushToast(tr('Could not start print.'), 'info'); }
    };
    const pfPrintNow = async () => {
        if (pfActionBusy.value || pfPrintBlockReason.value) return;
        pfActionBusy.value = true;
        try {
            const got = await pfResolveForPrint();
            if (!got) return;
            const j = got.resolved;
            // СУЩЕСТВУЮЩИЙ pre-start диалог (printStart) с явными «Печать»/«Отмена»;
            // c1: без пункта «Авто» (в C1 его нет) и без Bambu-опций (C1 их не применяет).
            openPrintStart({ printerId: j.printer_id, label: j.name, c1: true,
                onConfirm: (opts, srcSlot) => { pfStartCmd(j.printer_id, j.print_name, got.ref, srcSlot); } });
        } finally { pfActionBusy.value = false; }
    };
    // Компактное меню действий строки (⋯): выбрать для печати / печать / удалить (с причиной).
    const pfRowMenu = ref(null);           // { entry, x, y }
    //  Кнопка есть только там, где картинка вообще может быть: файл (не каталог) и
    //  принтер, умеющий отдавать предпросмотр.
    const pfCanPreview = (e) => !!(e && !e.is_directory && pfCaps.value && pfCaps.value.read_previews);
    const pfPreviewClose = () => {
        const cur = pfPreview.value;
        pfPreview.value = null;
        //  Ссылку на картинку освобождаем: иначе за смену браузер держит их все.
        try { if (cur && cur.url) URL.revokeObjectURL(cur.url); } catch (e) {}
    };
    const pfPreviewOpen = async (e) => {
        if (!pfCanPreview(e)) return;
        pfPreviewClose();
        const my = ++_pfPreviewSeq;
        pfPreview.value = { entry: e, url: '', state: 'loading', reason: '' };
        try {
            const r = await fetch('/api/printer-files/preview?printer_id=' + encodeURIComponent(pfPrinterId.value)
                                  + '&file_ref=' + encodeURIComponent(e.file_ref));
            if (my !== _pfPreviewSeq) return;                  // окно уже закрыли или открыли другое
            const ct = String(r.headers.get('content-type') || '');
            if (r.ok && ct.indexOf('image/') === 0) {
                const blob = await r.blob();
                if (my !== _pfPreviewSeq) return;
                pfPreview.value = { entry: e, url: URL.createObjectURL(blob), state: 'ready', reason: '' };
                return;
            }
            let reason = '';
            try { reason = ((await r.json()) || {}).reason || ''; } catch (err) { reason = ''; }
            pfPreview.value = { entry: e, url: '', state: 'error', reason };
        } catch (err) {
            if (my !== _pfPreviewSeq) return;
            pfPreview.value = { entry: e, url: '', state: 'error', reason: '' };
        }
    };
    const pfRowMenuFor = (ev, e) => {
        ev.stopPropagation();
        const r = ev.currentTarget.getBoundingClientRect();
        pfRowMenu.value = { entry: e, x: Math.max(8, Math.min(r.left - 160, window.innerWidth - 240)), y: Math.min(r.bottom + 4, window.innerHeight - 140) };
    };
    const pfRowMenuClose = () => { pfRowMenu.value = null; };
    const pfRowMenuAct = async (what) => {
        const e = pfRowMenu.value && pfRowMenu.value.entry;
        pfRowMenuClose();
        if (!e) return;
        if (what === 'select' || what === 'print') {
            if (!e.printable) return;
            pfSelected.value = new Set([e.file_ref]);   // действие строки = ровно этот файл
            if (what === 'select') await pfSelectForPrint(); else await pfPrintNow();
        } else if (what === 'preview') {
            await pfPreviewOpen(e);
        } else if (what === 'delete') {
            await pfDeleteOne(e);
        }
    };
    // Статус строки: printable-файл больше НЕ выглядит бесполезным «Только чтение».
    const pfStatusText = (e) => {
        const ru = lang.value === 'ru';
        if (e.active_print) return ru ? 'Активная печать' : 'Active print';
        if (!e.is_directory && e.printable) return ru ? 'Можно печатать' : 'Printable';
        if (!e.is_directory && !e.deletable) return pfReasonText(e.protected_reason);
        return '—';
    };
    const pfStatusTitle = (e) => {
        const ru = lang.value === 'ru';
        if (!e.is_directory && e.printable && !e.deletable) return ru ? 'Печать доступна · удаление недоступно' : 'Printing available · deletion unavailable';
        if (!e.is_directory && e.printable) return ru ? 'Печать доступна' : 'Printing available';
        return pfReasonText(e.protected_reason || e.print_blocked_reason || '');
    };
    // Capability-driven колонки метаданных: скрываются ТОЛЬКО когда адаптер честно
    // объявляет read_sizes/read_mtime = false (FlashForge); Bambu/Moonraker не трогаются.
    const pfShowSize = computed(() => !pfCaps.value || pfCaps.value.read_sizes !== false);
    const pfShowDate = computed(() => !pfCaps.value || pfCaps.value.read_mtime !== false);
    const pfMetaNote = computed(() => !!pfCaps.value && pfCaps.value.read_sizes === false && pfCaps.value.read_mtime === false);
    const openPrinterFiles = (pid) => {
        if (showDiag.value) closeDiagnostics();
        if (showSettings.value) closeSettings();
        if (showReports.value) closeReports();             // Alpha 2.900: тот же слот, что и отчёты
        showPrinterFiles.value = true;
        let target = pid || '';
        if (!target) { try { target = localStorage.getItem('fm_pf_last_printer') || ''; } catch (e) {} }
        if (!target || !(printers.value || []).some(p => p.id === target)) target = (printers.value[0] && printers.value[0].id) || '';
        pfSelectPrinter(target);
    };
    const closePrinterFiles = () => { showPrinterFiles.value = false; _pfGen++; };

    // ══════════════════════════════════════════════════════════════════════════
    // БЛОК: «Отчёты и статистика» (Alpha 2.898) — рабочий экран основной области.
    //
    // ОТКУДА ДАННЫЕ. Ядро истории печатей не ведёт вовсе: её пишет модуль «Качество печати»
    // в свою базу. Отчёт читает готовый журнал (/api/mod/quality/print-runs) и считает всё
    // сам, в интерфейсе. Новых маршрутов, новых таблиц и правок сервера здесь нет.
    // Модуль не установлен — так и говорим, а не показываем нули как правду.
    //
    // ЧЕСТНОСТЬ СЧЁТА. У печати четыре исхода, и третий с четвёртым нельзя валить в кучу:
    //   завершена — принтер доложил о завершении;
    //   сбой      — принтер доложил об ошибке;
    //   отменена  — остановлена, ЛИБО принтер ушёл в покой без доказанного завершения;
    //   не ясен   — печать сменил новый файл, и чем кончилась прежняя, никто не знает.
    // Доля успеха считается от суммы первых трёх; «не ясен» показывается ОТДЕЛЬНО, потому
    // что считать его сбоем — завысить брак, а успехом — завысить выработку.
    // ══════════════════════════════════════════════════════════════════════════
    const showReports = ref(false);
    const repDays = ref(30);
    const repPeriods = [7, 30, 90];
    const repRuns = ref([]);
    const repBusy = ref(false);
    const repState = ref('');            // '' | 'nomodule' | 'error'
    const repCapped = ref(false);
    const REP_PAGE = 500;                //  столько отдаёт журнал за один раз (предел модуля)
    const REP_CAP = 2000;                //  дальше не идём: это отчёт, а не выгрузка всей базы
    //  Время в журнале печати хранится по Гринвичу, поэтому и границу периода строим в нём же.
    const _repSince = (days) => {
        const d = new Date(Date.now() - Math.max(1, Number(days) || 1) * 86400000);
        const p = (n) => String(n).padStart(2, '0');
        return d.getUTCFullYear() + '-' + p(d.getUTCMonth() + 1) + '-' + p(d.getUTCDate())
            + ' ' + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes()) + ':' + p(d.getUTCSeconds());
    };
    //  А показываем — по местному времени владельца: печать, начатая вечером, должна попасть
    //  в свой день, а не в предыдущий.
    const _repLocalDate = (raw) => {
        const t = Date.parse(String(raw || '').replace(' ', 'T') + 'Z');
        if (!t) return '';
        const d = new Date(t), p = (n) => String(n).padStart(2, '0');
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
    };
    //  Модуль качества установлен и работает? Список модулей приложение и так держит; спрашивать
    //  журнал у ненужного адреса незачем, а «нет модуля» и «нет печатей» — РАЗНЫЕ ответы, и
    //  показывать их одинаково нельзя.
    const repQualityReady = computed(() => (installedModules.value || [])
        .some(m => m && m.id === 'quality' && moduleIsLoaded(m)));
    //  Alpha 2.900: что именно мешает считать. 'ready' — модуль работает; 'nomodule' — его нет
    //  на диске; 'moduleoff' — установлен, но выключен или не запустился (его надо ВКЛЮЧИТЬ, а
    //  не ставить заново); 'nolist' — список модулей не пришёл, и мы просто не знаем.
    const repModuleState = computed(() => {
        if (repQualityReady.value) return 'ready';
        const found = (installedModules.value || []).find(m => m && m.id === 'quality');
        if (found) return 'moduleoff';
        if (modulesLoadState.value !== 'ready') return 'nolist';
        return 'nomodule';
    });
    //  Alpha 2.900: почему здесь счётчик поколений. Кнопки срока запускают загрузку, а сеть
    //  отвечает не в том порядке, в каком её спросили: медленный ответ за 90 дней мог прийти
    //  ПОСЛЕ быстрого за 7 и лечь под подпись «7 дней». Хуже того, поздняя ошибка старого
    //  запроса стирала уже показанные верные числа. Применяет результат только самая свежая
    //  загрузка; всё, что пришло от отменённой, молча выбрасывается.
    let _repGen = 0;
    const loadReports = async () => {
        const gen = ++_repGen;
        const mine = () => gen === _repGen;
        repBusy.value = true;
        repState.value = '';
        repCapped.value = false;
        if (!installedModules.value || !installedModules.value.length) {
            try { await loadInstalledModules(); } catch (e) {}
        }
        if (!mine()) return;
        //  «Модуля нет», «модуль выключен/сломан» и «список модулей не пришёл» — РАЗНЫЕ ответы.
        //  Одинаковый текст про установку послал бы владельца делать не то: переустановка
        //  выключенного модуля оставит его выключенным.
        const st = repModuleState.value;
        if (st !== 'ready') {
            repRuns.value = [];
            repState.value = st;
            repBusy.value = false;
            return;
        }
        const since = _repSince(repDays.value);
        const acc = [];
        let state = '', capped = false;
        try {
            for (let off = 0; off < REP_CAP; off += REP_PAGE) {
                const r = await fetch('/api/mod/quality/print-runs?limit=' + REP_PAGE
                    + '&offset=' + off + '&date_from=' + encodeURIComponent(since));
                if (!mine()) return;
                if (r.status === 404) { state = 'nomodule'; break; }
                if (!r.ok) { state = 'error'; break; }
                const j = await r.json();
                if (!mine()) return;
                const part = (j && Array.isArray(j.runs)) ? j.runs : [];
                acc.push(...part);
                if (part.length < REP_PAGE) break;
                if (acc.length >= REP_CAP) { capped = true; break; }
            }
        } catch (e) {
            state = 'error';
        }
        if (!mine()) return;
        repState.value = state;
        repCapped.value = capped;
        repRuns.value = state ? [] : acc;
        repBusy.value = false;
    };
    const setRepDays = (d) => {
        if (!repPeriods.includes(Number(d))) return;
        repDays.value = Number(d);
        loadReports();
    };
    const openReports = () => {
        if (showSettings.value) closeSettings();
        if (showDiag.value) closeDiagnostics();
        if (showPrinterFiles.value) closePrinterFiles();
        showReports.value = true;
        loadReports();
    };
    const closeReports = () => { showReports.value = false; };
    const _repOutcome = (r) => {
        const o = String((r && r.outcome_raw) || '').toLowerCase();
        return (o === 'finished' || o === 'failed' || o === 'cancelled' || o === 'running')
            ? o : 'unknown';
    };
    const repStats = computed(() => {
        const runs = repRuns.value || [];
        const t = { total: runs.length, finished: 0, failed: 0, cancelled: 0, unknown: 0, running: 0, seconds: 0 };
        const byPrinter = new Map(), byFile = new Map(), byDay = new Map();
        for (const r of runs) {
            const o = _repOutcome(r);
            t[o] += 1;
            const secs = Math.max(0, Number(r.elapsed_s) || 0);
            if (o === 'finished') t.seconds += secs;
            const pk = String(r.printer_id || r.printer_name || '');
            const pn = String(r.printer_name || r.printer_id || '—');
            if (!byPrinter.has(pk)) byPrinter.set(pk, { key: pk, name: pn, total: 0, finished: 0, failed: 0, cancelled: 0, unknown: 0, running: 0, seconds: 0 });
            const P = byPrinter.get(pk);
            P.total += 1; P[o] += 1;
            if (o === 'finished') P.seconds += secs;
            const fk = String(r.filename || r.file_norm || '—');
            if (!byFile.has(fk)) byFile.set(fk, { name: fk, total: 0, finished: 0, failed: 0 });
            const F = byFile.get(fk);
            F.total += 1;
            if (o === 'finished') F.finished += 1;
            if (o === 'failed') F.failed += 1;
            const dk = _repLocalDate(r.started_at);
            if (dk) {
                if (!byDay.has(dk)) byDay.set(dk, { day: dk, total: 0, finished: 0, failed: 0 });
                const D = byDay.get(dk);
                D.total += 1;
                if (o === 'finished') D.finished += 1;
                if (o === 'failed') D.failed += 1;
            }
        }
        const judged = t.finished + t.failed + t.cancelled;
        const rate = judged ? Math.round((t.finished / judged) * 100) : 0;
        const printers = [...byPrinter.values()].sort((a, b) => b.total - a.total
            || String(a.name).localeCompare(String(b.name), undefined, { numeric: true, sensitivity: 'base' }));
        for (const p of printers) {
            const j = p.finished + p.failed + p.cancelled;
            p.judged = j;
            p.rate = j ? Math.round((p.finished / j) * 100) : 0;
        }
        const files = [...byFile.values()].sort((a, b) => b.total - a.total
            || String(a.name).localeCompare(String(b.name), undefined, { numeric: true, sensitivity: 'base' })).slice(0, 10);
        const days = [...byDay.values()].sort((a, b) => String(a.day).localeCompare(String(b.day)));
        const dayMax = days.reduce((m, d) => Math.max(m, d.total), 0);
        return { ...t, judged, rate, printers, files, days, dayMax };
    });
    //  Время печати словами: «14 ч 05 мин». Секунды на ферме не нужны, а часы — нужны.
    const repDuration = (secs) => {
        const s = Math.max(0, Math.round(Number(secs) || 0));
        //  Ноль — это не «печатали меньше минуты», а «завершённых печатей не было»: суммировать
        //  нечего. Разные вещи, и путать их на отчёте нельзя.
        if (!s) return '—';
        //  Округляем ВНИЗ: «14 ч 05 мин» должно значить «не меньше», а не «примерно».
        const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
        const ru = lang.value === 'ru';
        if (!h && !m) return ru ? 'меньше минуты' : 'under a minute';
        if (!h) return m + (ru ? ' мин' : ' min');
        return h + (ru ? ' ч ' : ' h ') + String(m).padStart(2, '0') + (ru ? ' мин' : ' min');
    };
    //  Подпись дня для столбика: «27.08».
    const repDayLabel = (day) => {
        const p = String(day || '').split('-');
        return p.length === 3 ? (p[2] + '.' + p[1]) : String(day || '');
    };
    //  Высота столбика — в ТОЧКАХ, а не в процентах: проценты считались бы от высоты всей
    //  колонки вместе с подписями, и самый высокий столбик наезжал бы на них.
    const REP_BAR_MAX = 84;
    const repDayHeight = (d) => {
        const max = repStats.value.dayMax || 0;
        if (!max) return 0;
        return Math.max(4, Math.round((Number(d && d.total) || 0) / max * REP_BAR_MAX));
    };
    // Alpha 2.633: окно диагностики — перетаскивание за шапку + изменение размера (по образцу окна проводника .ex-win).
    // Слушатели pointermove/pointerup вешаются на window ТОЛЬКО на время жеста и снимаются в up() — без дублей и утечек.
    const diagWin = ref({ x: 0, y: 0, w: 860, h: 600, init: false });
    let diagLastMoveResize = 0;
    const diagWinStyle = computed(() => {
        const s = {};
        if (diagWin.value.init) { s.position = 'fixed'; s.left = diagWin.value.x + 'px'; s.top = diagWin.value.y + 'px'; s.width = diagWin.value.w + 'px'; s.height = diagWin.value.h + 'px'; s.maxWidth = 'none'; s.maxHeight = 'none'; }
        return s;
    });
    const _diagWinSave = () => { try { const g = diagWin.value; localStorage.setItem('diag_win', JSON.stringify({ x: g.x, y: g.y, w: g.w, h: g.h })); } catch (e) {} };
    const diagWinClampIntoView = () => {   // держим окно в пределах экрана (после ресайза окна браузера/перетаскивания)
        const W = window.innerWidth, H = window.innerHeight;
        const g = diagWin.value;
        const w = Math.min(g.w, W), h = Math.min(g.h, H);
        const x = Math.max(0, Math.min(Math.max(0, W - w), g.x));
        const y = Math.max(0, Math.min(Math.max(0, H - h), g.y));
        diagWin.value = { x, y, w, h, init: true };
    };
    const diagWinEnsure = () => {   // первый показ: восстановить сохранённые размеры или задать компактный дефолт по центру
        if (!diagWin.value.init) {
            const W = window.innerWidth, H = window.innerHeight;
            let g = null; try { g = JSON.parse(localStorage.getItem('diag_win') || 'null'); } catch (e) {}
            if (g && g.w >= 420 && g.h >= 300) { diagWin.value = { x: g.x, y: g.y, w: g.w, h: g.h, init: true }; }
            else { const w = Math.min(860, Math.round(W * 0.9)), h = Math.min(600, Math.round(H * 0.88)); diagWin.value = { x: Math.round((W - w) / 2), y: Math.round((H - h) / 2), w, h, init: true }; }
        }
        diagWinClampIntoView();
    };
    window.addEventListener('resize', () => { if (showDiag.value && diagWin.value.init) diagWinClampIntoView(); });
    const _diagScale = (e) => {   // окно fixed под html{zoom} — переводим визуальные px в логические (rect/логич. ширина)
        try { const w = e.currentTarget && e.currentTarget.closest ? e.currentTarget.closest('.diag-win') : null; if (w && diagWin.value.w) { const k = w.getBoundingClientRect().width / diagWin.value.w; if (k > 0.1 && k < 10) return k; } } catch (err) {}
        return 1;
    };
    const diagDragStart = (e) => {
        if (e.target && e.target.closest && e.target.closest('button, input, label, select, a, .diag-x')) return;   // не тащим, если клик по вкладке/кнопке/чекбоксу/крестику
        e.preventDefault();
        const k = _diagScale(e);
        const sx = e.clientX, sy = e.clientY, ox = diagWin.value.x, oy = diagWin.value.y;
        document.body.style.userSelect = 'none';
        const mv = (ev) => {
            const VIS = 140;   // всегда оставляем >=140px окна видимыми — нельзя утащить полностью за экран
            let nx = ox + (ev.clientX - sx) / k, ny = oy + (ev.clientY - sy) / k;
            nx = Math.max(VIS - diagWin.value.w, Math.min(window.innerWidth - VIS, nx));
            ny = Math.max(0, Math.min(window.innerHeight - 40, ny));
            diagWin.value.x = nx; diagWin.value.y = ny;
        };
        const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); document.body.style.userSelect = ''; diagLastMoveResize = Date.now(); _diagWinSave(); };
        window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    };
    const diagResizeStart = (e, dir) => {
        e.preventDefault();
        const k = _diagScale(e);
        const sx = e.clientX, sy = e.clientY, o = { x: diagWin.value.x, y: diagWin.value.y, w: diagWin.value.w, h: diagWin.value.h };
        const minW = 420, minH = 300;   // юзабельный минимум (кнопки/вкладки/таблица не ломаются)
        document.body.style.userSelect = 'none';
        const mv = (ev) => {
            const dx = (ev.clientX - sx) / k, dy = (ev.clientY - sy) / k;
            let x = o.x, y = o.y, w = o.w, h = o.h;
            if (dir.indexOf('e') >= 0) w = o.w + dx;
            if (dir.indexOf('s') >= 0) h = o.h + dy;
            if (dir.indexOf('w') >= 0) { w = o.w - dx; x = o.x + dx; if (w < minW) { x = o.x + (o.w - minW); w = minW; } }
            if (dir.indexOf('n') >= 0) { h = o.h - dy; y = o.y + dy; if (h < minH) { y = o.y + (o.h - minH); h = minH; } }
            if (w < minW) w = minW;
            if (h < minH) h = minH;
            if (x < 0) { if (dir.indexOf('w') >= 0) w += x; x = 0; }
            if (y < 0) { if (dir.indexOf('n') >= 0) h += y; y = 0; }
            if (x + w > window.innerWidth) w = window.innerWidth - x;
            if (y + h > window.innerHeight) h = window.innerHeight - y;
            if (w < minW) w = minW;
            if (h < minH) h = minH;
            diagWin.value.x = x; diagWin.value.y = y; diagWin.value.w = w; diagWin.value.h = h;
        };
        const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); document.body.style.userSelect = ''; diagLastMoveResize = Date.now(); _diagWinSave(); };
        window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    };
    const toggleDiagVerbose = async () => {
        try {
            const r = await fetch('/api/diagnostics/verbose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on: !diagVerbose.value }) });
            const j = await r.json(); diagVerbose.value = !!j.verbose;
        } catch (e) {}
    };
    // Alpha 2.813: «Очистить экран» очищает ТОЛЬКО показанное. Файл журнала не трогается никогда,
    // серверный буфер тоже: следующая же запись снова появится в окне. Раньше кнопка чистила и
    // буфер на сервере — то есть у одного окна был шанс стереть историю у остальных.
    const clearDiag = () => { diagEntries.value = []; diagLastId = diagLastId; };
    // Скачать файл журнала для отправки в техподдержку. Эндпоинт отдаёт его с Content-Disposition:
    // attachment, поэтому переход по ссылке запускает скачивание (без ухода со страницы).
    const downloadLogs = () => {
        try {
            const a = document.createElement('a');
            a.href = '/api/logs/download'; a.download = '';
            document.body.appendChild(a); a.click(); a.remove();
        } catch (e) { try { window.open('/api/logs/download', '_blank'); } catch (e2) {} }
    };

    // --- Диагностика связи с принтерами (вкладка «Связь» в окне диагностики) ---
    const diagTab = ref('log');
    const connDiag = ref([]);          // сводка по парку
    const connExpanded = ref(null);    // раскрытый pid
    const connDetail = ref({});        // pid -> полный отчёт (с пробой файлового порта)
    const connDiagLoading = ref(false);
    const netMonitor = ref(true);      // тумблер фонового мониторинга (значение приходит из ответа сводки)
    let connTimer = null;              // авто-обновление таблицы, пока вкладка открыта
    let _liveTrendTimer = null;        // ежесекундный пинг раскрытого принтера для живого графика задержки
    const refreshConnDiag = async (silent) => {
        if (!silent) connDiagLoading.value = true;
        try {
            const r = await fetch('/api/diagnostics/fleet?lang=' + lang.value);
            if (r.ok) { const j = await r.json(); connDiag.value = (j && j.printers) || []; if (typeof j.monitor !== 'undefined') netMonitor.value = !!j.monitor; }
        } catch (e) {} finally { if (!silent) connDiagLoading.value = false; }
    };
    const _startConnAuto = () => {
        if (connTimer) clearInterval(connTimer);
        connTimer = setInterval(() => refreshConnDiag(true), 4000);   // тихое авто-обновление раз в 4с
    };
    const setDiagTab = (tab) => {
        diagTab.value = tab;
        if (connTimer) { clearInterval(connTimer); connTimer = null; }
        if (_liveTrendTimer) { clearInterval(_liveTrendTimer); _liveTrendTimer = null; }
        if (sniffTimer && tab !== 'sniff') { clearInterval(sniffTimer); sniffTimer = null; }   // уходим со вкладки — прекращаем ОПРОС (сам перехват на сервере продолжается до таймаута/стопа)
        if (tab === 'conn') { refreshConnDiag(connDiag.value.length > 0); _startConnAuto(); }
        if (tab === 'queue') refreshDurableQueue();   // Alpha 2.627: одна загрузка при открытии вкладки (без авто-опроса)
        if (tab === 'sniff') { if (!sniffPrinterId.value && bambuPrinters.value.length) sniffPrinterId.value = bambuPrinters.value[0].id; refreshSniff(); }   // Alpha 2.722: разовая загрузка состояния перехвата (+авто-опрос, если активен)
    };
    const toggleNetMonitor = async () => {
        const v = !netMonitor.value;
        netMonitor.value = v;
        try { await fetch('/api/diagnostics/monitor', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: v }) }); } catch (e) {}
    };
    const pingExpanded = async (pid) => {
        try {
            const r = await fetch('/api/printer/' + encodeURIComponent(pid) + '/ping');
            if (!r.ok) return;
            const j = await r.json();
            const dt = connDetail.value[pid];
            if (dt && j && j.spark) {
                dt.spark = j.spark;
                if (j.latency_ms != null && dt.checks) { const nc = dt.checks.find(c => c.key === 'network'); if (nc) nc.value = Math.round(j.latency_ms) + ' ' + tr('ms'); }
            }
        } catch (e) {}
    };
    const toggleConnRow = async (pid) => {
        if (_liveTrendTimer) { clearInterval(_liveTrendTimer); _liveTrendTimer = null; }
        if (connExpanded.value === pid) { connExpanded.value = null; return; }
        connExpanded.value = pid;
        try {
            const r = await fetch('/api/printer/' + encodeURIComponent(pid) + '/diagnose?lang=' + lang.value);
            if (r.ok) { const j = await r.json(); if (j && j.checks) connDetail.value[pid] = j; }
        } catch (e) {}
        _liveTrendTimer = setInterval(() => pingExpanded(pid), 1000);   // живой график задержки: пинг раз в секунду, пока деталь открыта
    };
    const cdiagNet = (d) => { const c = (d.checks || []).find(x => x.key === 'network'); return c ? c.value : '—'; };
    const cdiagIssues = (d) => { const bad = (d.checks || []).filter(x => x.status !== 'ok'); return bad.length ? bad.map(x => x.label).join(', ') : '—'; };
    const speedTest = ref({});   // pid -> {loading, result}
    const runSpeedTest = async (pid, ptype, state) => {
        if ((state === 'RUNNING' || state === 'PREPARE') && !await askConfirm({
                title: _L('Принтер сейчас печатает', 'The printer is printing'),
                text: tr('The printer is printing. The speed test will upload and delete a small file, which may briefly affect the print. Continue?'),
                okText: _L('Продолжить', 'Continue') })) return;
        speedTest.value[pid] = { loading: true, result: null };
        try {
            const r = await fetch('/api/printer/' + encodeURIComponent(pid) + '/speedtest?lang=' + lang.value, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
            const j = await r.json();
            speedTest.value[pid] = { loading: false, result: j };
        } catch (e) { speedTest.value[pid] = { loading: false, result: { ok: false, error: 'network' } }; }
    };
    // ── Alpha 2.627: READ-ONLY просмотр durable-очереди запуска печати (print_launch_queue).
    // Вкладка «Очередь запуска» в окне диагностики. Только показ статусов; НЕ запускает, НЕ отменяет,
    // НЕ меняет строки — единственный GET /api/print-queue/durable (сервер тоже только читает).
    const dpqRows = ref([]);
    const dpqLoading = ref(false);
    const dpqError = ref(false);
    const dpqCanceling = ref(false);   // Alpha 2.628: идёт запрос отмены (блокирует кнопки)
    const dpqActionErr = ref('');      // Alpha 2.628: текст ошибки отмены (показываем в шапке вкладки)
    const refreshDurableQueue = async () => {
        dpqLoading.value = true; dpqError.value = false; dpqActionErr.value = '';
        try {
            const r = await fetch('/api/print-queue/durable');
            if (!r.ok) { dpqError.value = true; return; }
            const j = await r.json();
            if (!j || j.ok === false) { dpqError.value = true; return; }
            dpqRows.value = (j && j.rows) || [];
        } catch (e) { dpqError.value = true; } finally { dpqLoading.value = false; }
    };
    const dpqStatusLabel = (s) => {
        const ru = { pending: 'ожидает', launching: 'запускается', sent: 'запущен', failed: 'ошибка', canceled: 'отменён', stale: 'устаревшая', recovery_attention: 'требует внимания', recovery_hold: 'ждёт подтверждения' };
        const en = { pending: 'pending', launching: 'launching', sent: 'sent', failed: 'failed', canceled: 'canceled', stale: 'stale', recovery_attention: 'attention', recovery_hold: 'awaiting confirmation' };
        return (lang.value === 'ru' ? ru : en)[s] || s || '—';
    };
    const dpqDotClass = (s) => {
        if (s === 'sent') return 'cdiag-dot--ok';
        if (s === 'failed') return 'cdiag-dot--fail';
        if (s === 'pending' || s === 'launching' || s === 'recovery_attention' || s === 'recovery_hold') return 'cdiag-dot--warn';
        return '';   // canceled / stale — нейтральный серый (базовый .cdiag-dot)
    };
    const dpqTime = (ts) => {
        const n = Number(ts);
        if (!(n > 0)) return '—';
        try { return new Date(n * 1000).toLocaleString(lang.value === 'ru' ? 'ru-RU' : 'en-US'); } catch (e) { return '—'; }
    };
    // ── Alpha 2.628: отмена ещё НЕ стартовавших (pending) отложенных запусков из вкладки «Очередь запуска».
    // Только для status==='pending'; POST /api/print-queue/durable/cancel (бэкенд: UPDATE только pending → canceled,
    // без удаления строк, + снятие из in-memory очереди). Другие статусы не отменяются. Спрашиваем подтверждение.
    const dpqPendingInBatch = (batchId) => (dpqRows.value || []).filter(q => q.batch_id === batchId && q.status === 'pending').length;
    const _dpqCancel = async (body) => {
        dpqActionErr.value = ''; dpqCanceling.value = true;
        let ok = false;
        try {
            const r = await fetch('/api/print-queue/durable/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            if (r.ok) { const j = await r.json(); ok = !!(j && j.ok); }
        } catch (e) { ok = false; }
        dpqCanceling.value = false;
        if (ok) { await refreshDurableQueue(); }                       // показать обновлённые статусы (canceled)
        else { dpqActionErr.value = (lang.value === 'ru' ? 'Не удалось отменить' : 'Cancel failed'); }
    };
    const cancelDurableRow = async (row) => {
        if (!row || row.status !== 'pending' || dpqCanceling.value) return;
        const name = row.printer_name || row.printer_id;
        const msg = lang.value === 'ru'
            ? ('Отменить ожидающий запуск на «' + name + '»? Печать по нему НЕ начнётся. Уже запущенные задания не затрагиваются.')
            : ('Cancel the pending launch on "' + name + '"? Its printing will NOT start. Already-launched jobs are unaffected.');
        if (!await askConfirm({ title: _L('Отменить ожидающий запуск?', 'Cancel the pending launch?'), text: msg,
                                okText: _L('Отменить запуск', 'Cancel launch') })) return;
        _dpqCancel({ id: row.id });
    };
    const cancelDurableBatch = async (row) => {
        if (!row || !row.batch_id || dpqCanceling.value) return;
        const n = dpqPendingInBatch(row.batch_id);
        const msg = lang.value === 'ru'
            ? ('Отменить все ожидающие запуски этой пачки (' + n + ' шт.)? Печать по ним НЕ начнётся. Уже запущенные не затрагиваются.')
            : ('Cancel all pending launches in this batch (' + n + ')? Their printing will NOT start. Already-launched are unaffected.');
        if (!await askConfirm({ title: _L('Отменить запуски этой пачки?', 'Cancel this batch?'), text: msg,
                                okText: _L('Отменить запуски', 'Cancel launches') })) return;
        _dpqCancel({ batch_id: row.batch_id });
    };
    // ── Alpha 2.722: ВРЕМЕННЫЙ инструмент «Перехват команды Bambu Studio» (вкладка «Перехват Studio»).
    // Read-only: сервер поднимает ОТДЕЛЬНОЕ MQTT-подключение (только подписка, без publish) и складывает
    // перехваченные команды в память (макс. 20, секреты вырезаны). UI выбирает Bambu-принтер, стартует/
    // останавливает перехват и опрашивает состояние раз в секунду, пока сессия активна. Ничего не пишет на
    // принтер и не влияет на печать/очередь/recovery.
    const sniffPrinterId = ref('');
    const sniffState = ref({ active: false, status: 'idle', messages: [], remaining_s: 0, received: 0, stored: 0, max: 20 });
    const sniffBusy = ref(false);
    const sniffCopied = ref(false);
    let sniffTimer = null;
    const bambuPrinters = computed(() => (printers.value || []).filter(p => (p.type || 'bambu') === 'bambu'));
    const refreshSniff = async () => {
        try {
            const r = await fetch('/api/diagnostics/bambu-sniff');
            if (r.ok) { const j = await r.json(); if (j) sniffState.value = j; }
        } catch (e) {}
        // Пока сессия активна — опрашиваем раз в секунду; иначе таймер снимаем (сообщения остаются видимы).
        if (sniffState.value && sniffState.value.active) { if (!sniffTimer) sniffTimer = setInterval(refreshSniff, 1000); }
        else if (sniffTimer) { clearInterval(sniffTimer); sniffTimer = null; }
    };
    const startSniff = async () => {
        if (sniffBusy.value || !sniffPrinterId.value) return;
        sniffBusy.value = true;
        try {
            const r = await fetch('/api/diagnostics/bambu-sniff/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ printer_id: sniffPrinterId.value }) });
            const j = r.ok ? await r.json() : null;
            if (!j || j.ok === false) {
                const em = { no_printer: 'Выберите принтер', not_found: 'Принтер не найден', not_bambu: 'Это не Bambu-принтер', no_serial: 'Серийный номер принтера ещё не получен — откройте карточку принтера, дождитесь связи и повторите', already_running: 'Перехват уже идёт', connect_failed: 'Не удалось подключиться к принтеру' };
                pushToast((em[j && j.error] || (lang.value === 'ru' ? 'Не удалось начать перехват' : 'Failed to start capture')), 'warn', 4000);
            }
        } catch (e) { pushToast(lang.value === 'ru' ? 'Не удалось начать перехват' : 'Failed to start capture', 'warn', 4000); }
        sniffBusy.value = false;
        await refreshSniff();
    };
    const stopSniff = async () => {
        if (sniffBusy.value) return;
        sniffBusy.value = true;
        try { await fetch('/api/diagnostics/bambu-sniff/stop', { method: 'POST' }); } catch (e) {}
        sniffBusy.value = false;
        await refreshSniff();
    };
    const sniffStatusLabel = computed(() => {
        const s = sniffState.value || {};
        const map = { idle: ['Готов', 'Idle'], connecting: ['Подключение…', 'Connecting…'], listening: ['Слушает команды', 'Listening'], stopped: ['Остановлен', 'Stopped'], timeout: ['Остановлен по таймауту', 'Stopped (timeout)'], error: ['Ошибка подключения', 'Connection error'] };
        const t = map[s.status] || ['—', '—'];
        return lang.value === 'ru' ? t[0] : t[1];
    });
    const sniffFmt = (m) => { try { return JSON.stringify(m && m.json, null, 2); } catch (e) { return ''; } };
    const sniffTime = (ts) => { const n = Number(ts); if (!(n > 0)) return '—'; try { return new Date(n * 1000).toLocaleTimeString(lang.value === 'ru' ? 'ru-RU' : 'en-US'); } catch (e) { return '—'; } };
    const copySniff = async () => {
        try {
            const payload = JSON.stringify((sniffState.value && sniffState.value.messages) || [], null, 2);
            await navigator.clipboard.writeText(payload);
            sniffCopied.value = true; setTimeout(() => { sniffCopied.value = false; }, 1500);
        } catch (e) { pushToast(lang.value === 'ru' ? 'Не удалось скопировать' : 'Copy failed', 'warn', 3000); }
    };

    // ── Alpha 2.629: подтверждение восстановления прерванной очереди (recovery_hold).
    // После перезапуска восстановление НЕ авто-запускает — строки удержаны; модалка спрашивает
    // «Продолжить очередь / Отменить оставшиеся / Открыть очередь». Проверяем ОДИН раз при загрузке (без авто-опроса).
    const recoveryNotice = ref(null);   // {active, held, attention, batch_ids} | null
    const recoveryBusy = ref(false);
    const checkRecoveryNotice = async () => {
        try {
            const r = await fetch('/api/print-queue/recovery-notice');
            if (!r.ok) return;
            const j = await r.json();
            recoveryNotice.value = (j && j.ok && j.active) ? j : null;
        } catch (e) {}
    };
    const recoveryContinue = async () => {
        if (recoveryBusy.value) return;
        recoveryBusy.value = true;
        try { await fetch('/api/print-queue/recovery/continue', { method: 'POST' }); } catch (e) {}
        recoveryBusy.value = false;
        recoveryNotice.value = null;
        fetchPrintQueue();   // показать восстановленные элементы в баннере очереди
    };
    const recoveryCancel = async () => {
        if (recoveryBusy.value) return;
        const n = (recoveryNotice.value && recoveryNotice.value.held) || 0;
        const msg = lang.value === 'ru'
            ? ('Отменить все оставшиеся ожидающие запуски (' + n + ' шт.)? Печать по ним НЕ начнётся. Уже запущенные принтеры не затрагиваются.')
            : ('Cancel all remaining pending launches (' + n + ')? Their printing will NOT start. Already-running printers are unaffected.');
        if (!await askConfirm({ title: _L('Отменить все ожидающие запуски?', 'Cancel all pending launches?'), text: msg,
                                okText: _L('Отменить запуски', 'Cancel launches') })) return;
        recoveryBusy.value = true;
        try { await fetch('/api/print-queue/recovery/cancel', { method: 'POST' }); } catch (e) {}
        recoveryBusy.value = false;
        recoveryNotice.value = null;
    };
    const recoveryOpenQueue = () => {
        openDiagnostics();      // окно диагностики (z выше модалки) — по закрытии модалка ещё активна
        setDiagTab('queue');    // вкладка «Очередь запуска» покажет строки «ждёт подтверждения»
    };
    // Смена языка интерфейса: мгновенно перезапрашиваем раздел «Связь» на нужном языке
    watch(lang, () => {
        if (diagTab.value !== 'conn') return;
        refreshConnDiag(true);
        const pid = connExpanded.value;
        if (pid) {
            fetch('/api/printer/' + encodeURIComponent(pid) + '/diagnose?lang=' + lang.value)
                .then(r => r.ok ? r.json() : null)
                .then(j => { if (j && j.checks) connDetail.value[pid] = j; })
                .catch(() => {});
        }
    });
    const sparkPoints = (arr) => {
        const a = (arr || []).filter(v => v !== null && v !== undefined && !isNaN(v));
        if (a.length < 2) return '';
        const w = 120, h = 28, mn = Math.min(...a), mx = Math.max(...a), rng = (mx - mn) || 1;
        return a.map((v, i) => (i * (w / (a.length - 1))).toFixed(1) + ',' + (h - 2 - ((v - mn) / rng) * (h - 4)).toFixed(1)).join(' ');
    };
    const sparkRange = (arr) => {
        const a = (arr || []).filter(v => v !== null && v !== undefined && !isNaN(v));
        if (!a.length) return '';
        const mn = Math.round(Math.min(...a)), mx = Math.round(Math.max(...a));
        return mn === mx ? (mn + ' ' + tr('ms')) : (mn + '–' + mx + ' ' + tr('ms'));
    };

    // ------------------------------------------------------------------------
    // БЛОК: завершение Vue-компонента — остановка части интервалов,
    // снятие глобальных обработчиков и закрытие WebSocket.
    // Возможные дополнительные очистки перечислены в WEB_ANALYSIS_RU.md.
    // ------------------------------------------------------------------------
    onUnmounted(() => {
        stopProjectRunsPolling();   // «Планы проектов»: abort текущего тика + clearInterval (без утечек)
        clearInterval(pollInterval);
        clearInterval(stagingInterval);
        if (diagTimer) clearInterval(diagTimer);
        if (_diagAlertTimer) clearInterval(_diagAlertTimer);
        document.removeEventListener('click', onDocClick);
        document.removeEventListener('keydown', onKeydown);
        document.removeEventListener('mousedown', onDocMouseDown, true);
        document.removeEventListener('contextmenu', onDocContextMenu, true);
        window.removeEventListener('resize', _onResize);
        if (ws) ws.close(); 
    });
    // ------------------------------------------------------------------------
    // БЛОК: компактный файловый менеджер только для рабочих папок программы.
    // ------------------------------------------------------------------------
    // --- Файловый менеджер рабочих папок программы (просмотр/скачивание/удаление) ---
    const showFileManager = ref(false);
    const fmSize = (b) => { b = b || 0; if (b < 1024) return b + ' B'; if (b < 1048576) return (b/1024).toFixed(1) + ' KB'; if (b < 1073741824) return (b/1048576).toFixed(1) + ' MB'; return (b/1073741824).toFixed(2) + ' GB'; };
    const fmDate = (t) => { try { return new Date((t||0)*1000).toLocaleString('ru-RU', { year:'2-digit', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' }); } catch(e) { return ''; } };

    // ------------------------------------------------------------------------
    // БЛОК: расширенный проводник всего диска.
    // Хранит размер/позицию окна и масштаб в localStorage, поддерживает выбор
    // нескольких файлов, импорт, привязку, Tasks и прямую печать.
    // ------------------------------------------------------------------------
    // --- Win11-обзор всего диска (только чтение) ---
    const exOpen = ref(false);
    const exMode = ref('tasks');   // 'tasks' = загрузить в Задачи, 'attach' = привязать к детали Plan
    const exPart = ref(null);      // деталь Plan для режима привязки
    const exProject = ref('');     // целевой проект для режима 'parts' (выбор файлов → создание деталей)
    const exItems = ref([]);
    const exQuick = ref([]);
    const exDrives = ref([]);
    const exDriveName = (d) => {                       // 🔒 ОТЛАЖЕНО — имя диска «метка (буква:)»; без метки тип локализуется через tr. Согласовано с fs_roots (label/letter/dtype). Не менять без перепроверки.
        if (!d) return '';
        if (!d.letter) return tr(d.name || '');
        const base = d.label ? d.label : tr(d.dtype || 'Local Disk');
        return base + ' (' + d.letter + ':)';
    };
    const exCrumbs = ref([]);
    const exParent = ref('');
    const exPath = ref('');
    const exSelected = ref([]);
    const exAnchor = ref('');
    const _exFsInit = () => { try { const v = parseFloat(localStorage.getItem('ex_fs')); return (v >= 0.8 && v <= 1.6) ? v : 1; } catch (e) { return 1; } };
    const exFs = ref(_exFsInit());
    const _exFsSave = () => { try { localStorage.setItem('ex_fs', String(exFs.value)); } catch (e) {} };
    const exZoom = (d) => { exFs.value = Math.min(1.6, Math.max(0.8, Math.round((exFs.value + d) * 100) / 100)); _exFsSave(); };
    const exZoomReset = () => { exFs.value = 1; _exFsSave(); };
    const exWheel = (e) => { if (e.ctrlKey) { e.preventDefault(); exZoom(e.deltaY < 0 ? 0.1 : -0.1); } };
    const exWin = ref({ x: 0, y: 0, w: 1040, h: 600, init: false });
    let exLastMoveResize = 0;
    const exWinStyle = computed(() => {
        const s = { '--ex-fs': exFs.value };
        if (exWin.value.init) { s.position = 'fixed'; s.zIndex = 1; s.left = exWin.value.x + 'px'; s.top = exWin.value.y + 'px'; s.width = exWin.value.w + 'px'; s.height = exWin.value.h + 'px'; s.maxWidth = 'none'; s.maxHeight = 'none'; }
        return s;
    });
    const _exWinSave = () => { try { const g = exWin.value; localStorage.setItem('ex_win', JSON.stringify({ x: g.x, y: g.y, w: g.w, h: g.h })); } catch (e) {} };
    // Эффективный зум окна проводника = html{zoom} (зависит от шрифта UI, applyUiFont) × zoom(.zoom-wrap ≈1.097).
    // Сначала пробуем измерить из отрисованного .ex-win (учитывает все зумы и мобильные оверрайды), иначе считаем
    // как html{zoom}×1.097. Нужен, чтобы clamp/ensure/reset работали в ЛОГИЧЕСКИХ координатах окна, а не в визуальных.
    const _exZoom = () => {
        try { const el = document.querySelector('.ex-win'); if (el && exWin.value.w) { const k = el.getBoundingClientRect().width / exWin.value.w; if (k > 0.1 && k < 10) return k; } } catch (e) {}
        try { const z = (parseFloat(getComputedStyle(document.documentElement).zoom) || 1) * _wrapZoom(); if (z > 0.1 && z < 10) return z; } catch (e) {}
        return 1;
    };
    const _EX_MINW = 520, _EX_MINH = 360, _EX_PAD = 12;
    const exWinClampIntoView = () => {
        const Z = _exZoom();
        const Wlog = window.innerWidth / Z, Hlog = window.innerHeight / Z;   // вьюпорт в логических px окна (с учётом зума)
        const g = exWin.value;
        const w = Math.min(g.w, Math.max(_EX_MINW, Wlog - _EX_PAD * 2));     // не шире доступного (нижняя граница — _EX_MINW)
        const h = Math.min(g.h, Math.max(_EX_MINH, Hlog - _EX_PAD * 2));
        const maxX = Math.max(_EX_PAD, Wlog - w - _EX_PAD);
        const maxY = Math.max(_EX_PAD, Hlog - h - _EX_PAD);
        const x = Math.min(Math.max(_EX_PAD, g.x), maxX);                    // левый/верхний край ≥ _EX_PAD → шапка всегда в экране
        const y = Math.min(Math.max(_EX_PAD, g.y), maxY);
        exWin.value = { x, y, w, h, init: true };
    };
    const _exWinDefault = () => {   // дефолт 1040×600 по центру, ужатый под текущий вьюпорт
        const Z = _exZoom();
        const Wlog = window.innerWidth / Z, Hlog = window.innerHeight / Z;
        const w = Math.max(_EX_MINW, Math.min(1040, Wlog - _EX_PAD * 2));
        const h = Math.max(_EX_MINH, Math.min(600, Hlog - _EX_PAD * 2));
        return { x: Math.round((Wlog - w) / 2), y: Math.round((Hlog - h) / 2), w, h, init: true };
    };
    const _exWinValid = (g) => {   // сохранённое ex_win пригодно, только если это разумные числа (иначе → центр)
        if (!g || typeof g !== 'object') return false;
        const num = (v) => (typeof v === 'number' && isFinite(v));
        if (!num(g.x) || !num(g.y) || !num(g.w) || !num(g.h)) return false;             // NaN/null/undefined/мусор
        if (g.x < 0 || g.y < 0) return false;                                           // отрицательные координаты
        if (g.w < 480 || g.h < 320) return false;                                       // слишком мелкое/битое
        if (g.w > 20000 || g.h > 20000 || g.x > 100000 || g.y > 100000) return false;   // абсурдно большое
        return true;                                                                    // великоватый, но валидный размер ужмёт clamp
    };
    const exWinEnsure = () => {
        if (!exWin.value.init) {
            let g = null; try { g = JSON.parse(localStorage.getItem('ex_win') || 'null'); } catch (e) {}
            exWin.value = _exWinValid(g) ? { x: g.x, y: g.y, w: g.w, h: g.h, init: true } : _exWinDefault();
        }
        exWinClampIntoView();   // всегда возвращаем окно в видимую область (в т.ч. при смене зума/размера экрана)
    };
    const exWinReset = (e) => {   // двойной клик по шапке → окно по центру с дефолтным размером
        if (e && e.target && e.target.closest && e.target.closest('.ex-x, button, input, select, a, label')) return;
        exWin.value = _exWinDefault(); exWinClampIntoView(); _exWinSave();
    };
    window.addEventListener('resize', () => { if (exOpen.value && exWin.value.init) exWinClampIntoView(); });
    const _exScale = (e) => {
        try { const w = e.currentTarget && e.currentTarget.closest ? e.currentTarget.closest('.ex-win') : null; if (w && exWin.value.w) { const k = w.getBoundingClientRect().width / exWin.value.w; if (k > 0.1 && k < 10) return k; } } catch (err) {}
        return 1;
    };
    const exDragStart = (e) => {
        if (e.target && e.target.closest && e.target.closest('.ex-x')) return;
        e.preventDefault();
        const k = _exScale(e);
        const sx = e.clientX, sy = e.clientY, ox = exWin.value.x, oy = exWin.value.y;
        document.body.style.userSelect = 'none';
        const mv = (ev) => {
            const Wlog = window.innerWidth / k, Hlog = window.innerHeight / k;   // логический вьюпорт с учётом зума
            const maxX = Math.max(_EX_PAD, Wlog - exWin.value.w - _EX_PAD);
            const maxY = Math.max(_EX_PAD, Hlog - exWin.value.h - _EX_PAD);
            let nx = ox + (ev.clientX - sx) / k, ny = oy + (ev.clientY - sy) / k;
            nx = Math.min(Math.max(_EX_PAD, nx), maxX);   // окно (и шапка) всегда целиком в экране
            ny = Math.min(Math.max(_EX_PAD, ny), maxY);
            exWin.value.x = nx; exWin.value.y = ny;
        };
        const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); document.body.style.userSelect = ''; exLastMoveResize = Date.now(); _exWinSave(); };
        window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    };
    const exResizeStart = (e, dir) => {
        e.preventDefault();
        const k = _exScale(e);
        const sx = e.clientX, sy = e.clientY, o = { x: exWin.value.x, y: exWin.value.y, w: exWin.value.w, h: exWin.value.h };
        const minW = 480, minH = 320;
        document.body.style.userSelect = 'none';
        const mv = (ev) => {
            const Wlog = window.innerWidth / k, Hlog = window.innerHeight / k;   // границы в логических px окна (с учётом зума)
            const pad = _EX_PAD;
            const dx = (ev.clientX - sx) / k, dy = (ev.clientY - sy) / k;
            let x = o.x, y = o.y, w = o.w, h = o.h;
            if (dir.indexOf('e') >= 0) w = o.w + dx;
            if (dir.indexOf('s') >= 0) h = o.h + dy;
            if (dir.indexOf('w') >= 0) { w = o.w - dx; x = o.x + dx; if (w < minW) { x = o.x + (o.w - minW); w = minW; } }
            if (dir.indexOf('n') >= 0) { h = o.h - dy; y = o.y + dy; if (h < minH) { y = o.y + (o.h - minH); h = minH; } }
            if (w < minW) w = minW;
            if (h < minH) h = minH;
            if (x < pad) { if (dir.indexOf('w') >= 0) w -= (pad - x); x = pad; }
            if (y < pad) { if (dir.indexOf('n') >= 0) h -= (pad - y); y = pad; }
            if (x + w > Wlog - pad) w = Wlog - pad - x;
            if (y + h > Hlog - pad) h = Hlog - pad - y;
            if (w < minW) w = minW;
            if (h < minH) h = minH;
            exWin.value.x = x; exWin.value.y = y; exWin.value.w = w; exWin.value.h = h;
        };
        const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); document.body.style.userSelect = ''; exLastMoveResize = Date.now(); _exWinSave(); };
        window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    };
    const exBackdropClose = () => { if (Date.now() - exLastMoveResize < 250) return; exOpen.value = false; };
    const exError = ref('');
    const exLoading = ref(false);
    const exPrevOk = ref(true);
    const exPrintPid = ref('');
    const exAmsOpen = ref(false);
    const exLastPath = ref('');
    try { exLastPath.value = localStorage.getItem('ex_last_path') || ''; } catch (e) {}
    const exSort = ref('name');
    const exSortDir = ref(1);
    const exSetSort = (key) => {
        if (exSort.value === key) { exSortDir.value = -exSortDir.value; }
        else { exSort.value = key; exSortDir.value = 1; }
    };
    // Изменение ширины колонок Explorer перетаскиванием разделителей (как в Windows). Имя — гибкая (1fr);
    // ручка на левом крае колонок «Изменён/Тип/Размер» двигает границу, Имя поглощает изменение. Ширины (px)
    // привязаны к CSS-переменным на .ex-main и сохраняются в localStorage.
    // 🔒 ОТЛАЖЕНО — ресайз панелей проводника (колонки + боковая + предпросмотр) с сохранением ширин в localStorage, единый паттерн. Не менять знаки дельты (боковая +, предпросмотр −) и ключи ex_col_w/ex_side_w/ex_prev_w без перепроверки.
    const exColW = ref({ mod: 111, type: 54, size: 68 });
    try { const s = JSON.parse(localStorage.getItem('ex_col_w') || 'null'); if (s && typeof s === 'object') exColW.value = { mod: (+s.mod) || 111, type: (+s.type) || 54, size: (+s.size) || 68 }; } catch (e) {}
    const _exColMin = { mod: 80, type: 46, size: 52 };
    let _exColDrag = null;
    const exColMove = (e) => { if (!_exColDrag) return; const w = _exColDrag.w - (e.clientX - _exColDrag.x); exColW.value[_exColDrag.col] = Math.max(_exColMin[_exColDrag.col] || 46, Math.min(420, Math.round(w))); };
    const exColEnd = () => { if (!_exColDrag) return; _exColDrag = null; document.removeEventListener('mousemove', exColMove); document.removeEventListener('mouseup', exColEnd); document.body.style.cursor = ''; try { localStorage.setItem('ex_col_w', JSON.stringify(exColW.value)); } catch (e) {} };
    const exColStart = (col, e) => { _exColDrag = { col, x: e.clientX, w: exColW.value[col] }; document.addEventListener('mousemove', exColMove); document.addEventListener('mouseup', exColEnd); document.body.style.cursor = 'col-resize'; };
    // ширина боковой панели проводника (Быстрый доступ / Этот компьютер) — тянется за разделитель, сохраняется
    const exSideW = ref(210);
    try { const v = +(localStorage.getItem('ex_side_w')); if (v >= 150 && v <= 480) exSideW.value = v; } catch (e) {}
    let _exSideDrag = null;
    const exSideMove = (e) => { if (!_exSideDrag) return; const w = _exSideDrag.w + (e.clientX - _exSideDrag.x); exSideW.value = Math.max(150, Math.min(480, Math.round(w))); };
    const exSideEnd = () => { if (!_exSideDrag) return; _exSideDrag = null; document.removeEventListener('mousemove', exSideMove); document.removeEventListener('mouseup', exSideEnd); document.body.style.cursor = ''; try { localStorage.setItem('ex_side_w', String(exSideW.value)); } catch (e) {} };
    const exSideStart = (e) => { e.preventDefault(); _exSideDrag = { x: e.clientX, w: exSideW.value }; document.addEventListener('mousemove', exSideMove); document.addEventListener('mouseup', exSideEnd); document.body.style.cursor = 'col-resize'; };
    // ширина панели предпросмотра — тянется за левый разделитель (влево = шире), сохраняется
    const exPrevW = ref(240);
    try { const v = +(localStorage.getItem('ex_prev_w')); if (v >= 160 && v <= 520) exPrevW.value = v; } catch (e) {}
    let _exPrevDrag = null;
    const exPrevMove = (e) => { if (!_exPrevDrag) return; const w = _exPrevDrag.w - (e.clientX - _exPrevDrag.x); exPrevW.value = Math.max(160, Math.min(520, Math.round(w))); };
    const exPrevEnd = () => { if (!_exPrevDrag) return; _exPrevDrag = null; document.removeEventListener('mousemove', exPrevMove); document.removeEventListener('mouseup', exPrevEnd); document.body.style.cursor = ''; try { localStorage.setItem('ex_prev_w', String(exPrevW.value)); } catch (e) {} };
    const exPrevStart = (e) => { e.preventDefault(); _exPrevDrag = { x: e.clientX, w: exPrevW.value }; document.addEventListener('mousemove', exPrevMove); document.addEventListener('mouseup', exPrevEnd); document.body.style.cursor = 'col-resize'; };
    const exSortedItems = computed(() => {
        const k = exSort.value, d = exSortDir.value;
        return [...exItems.value].sort((a, b) => {
            if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
            let r = 0;
            if (k === 'name') r = (a.name||'').localeCompare(b.name||'', undefined, {numeric:true, sensitivity:'base'});
            else if (k === 'modified') r = (Number(a.mtime)||0) - (Number(b.mtime)||0);
            else if (k === 'type') r = (a.ext||'').localeCompare(b.ext||'', undefined, {sensitivity:'base'});
            else if (k === 'size') r = (Number(a.size)||0) - (Number(b.size)||0);
            if (r === 0) r = (a.name||'').localeCompare(b.name||'', undefined, {numeric:true, sensitivity:'base'});
            return r * d;
        });
    });
    const exSelItem = computed(() => {
        const arr = exSelected.value;
        if (!arr.length) return null;
        const a = exAnchor.value;
        return (a && arr.indexOf(a) >= 0 && exItems.value.find(i => i.path === a)) || exItems.value.find(i => i.path === arr[arr.length - 1]) || null;
    });
    const exPrintableSel = computed(() => exItems.value.filter(i => exSelected.value.indexOf(i.path) >= 0 && i.printable).map(i => i.path));
    const _isPartFile = (n) => { const m = (n || '').toLowerCase(); return m.endsWith('.stl') || m.endsWith('.3mf') || m.endsWith('.gcode'); };
    const exPartFilesSel = computed(() => exItems.value.filter(i => exSelected.value.indexOf(i.path) >= 0 && !i.is_dir && _isPartFile(i.name)).map(i => i.path));
    const _isImportFile = (n) => { const m = (n || '').toLowerCase(); return m.endsWith('.csv') || m.endsWith('.xlsx') || m.endsWith('.json'); };   // план/архив для импорта (.json = архив Проектов 2.0)
    const exImportable = computed(() => { const it = exSelItem.value; return !!(it && !it.is_dir && _isImportFile(it.name)); });
    const exGo = async (path) => {
        exLoading.value = true; exError.value = ''; exSelected.value = []; exAnchor.value = '';
        try {
            const r = await fetch('/api/fs/list?path=' + encodeURIComponent(path || ''));
            const j = await r.json();
            if (j.status !== 'ok') { exError.value = j.reason || tr('Error'); exItems.value = []; exCrumbs.value = []; }
            else { exItems.value = j.items || []; exPath.value = j.path || ''; exParent.value = j.parent || ''; exCrumbs.value = j.crumbs || []; exSelected.value = j.select ? [j.select] : []; exAnchor.value = j.select || ''; exPrevOk.value = true; exLastPath.value = j.path || ''; try { localStorage.setItem('ex_last_path', exLastPath.value); } catch (e) {} }
        } catch (e) { exError.value = String(e); exItems.value = []; }
        exLoading.value = false;
    };
    const exOpenWith = async (mode, part, startPath) => {
        exMode.value = mode; exPart.value = part || null;
        exOpen.value = true; exWinEnsure(); exSelected.value = []; exAnchor.value = ''; exError.value = ''; exAmsOpen.value = false;
        try {
            const j = await (await fetch('/api/fs/roots')).json();
            exQuick.value = j.quick || []; exDrives.value = j.drives || [];
            const home = j.home || (j.quick && j.quick[0] && j.quick[0].path) || (j.drives && j.drives[0] && j.drives[0].path) || '';
            if (startPath) { await exGo(startPath); if (exError.value) await exGo(home); }   // принудительно открыть в заданной папке (напр. Archive)
            else { await exGo(exLastPath.value || home); if (exError.value && exLastPath.value) await exGo(home); }
        } catch (e) { exError.value = String(e); }
    };
    const openExplorer = () => exOpenWith('tasks', null);
    const openExplorerForPrint = (pid) => { exPrintPid.value = pid; return exOpenWith('print', null); };
    // Лёгкие всплывающие уведомления (тосты): короткий отклик о фоновых действиях.
    //  ── 2.958 (заказ владельца): сообщения программы живут в панели «Подсказки», а не всплывают
    //  в углу экрана. Раньше сообщение висело 3 секунды и пропадало — пропустил, и всё. Теперь оно
    //  остаётся в списке, пока его не закроют; храним последние 30. Имя pushToast сохранено: его
    //  зовут из 49 мест, и переименование ничего бы не улучшило.
    const MSG_KEEP = 30;
    const MSG_FRESH_MS = 6000;
    //  ── 2.973 (заказ владельца): сообщение живёт, пока оно про «сейчас» ─────────────────
    //  2.958 сделала сообщения вечными — до неё они висели три секунды, и владелец их не
    //  успевал прочесть. Другая крайность оказалась не лучше: в панели копились строки,
    //  которые уже ничего не описывают. «Нет свободных принтеров» — когда они появились;
    //  «принтер пока недоступен» — когда он давно на связи. Теперь у каждого сообщения есть
    //  СРОК, а у некоторых ещё и УСЛОВИЕ: как только положение изменилось, строка уходит сама.
    //
    //  Беду (красное) сама программа не убирает: её закрывает человек — иначе можно
    //  не заметить, что печать сорвалась. «Дело идёт» (колесо) снимает тот, кто его завёл.
    //  2.974 (заказ владельца): отчёт об удавшемся деле и обычное сообщение живут 3 секунды
    //  после того, как дело закончилось. Предупреждение держится двадцать минут, беда — пока
    //  её не закроют: её пропустить нельзя.
    const MSG_LIFE = { ok: 3000, info: 3000, warn: 1200000, bad: 0, work: 0 };
    const MSG_MIN_LIFE = 3000;       // меньше — не успеть заметить
    const MSG_SWEEP_MS = 5000;       // как часто подметаем
    //  ── 2.959 (заказ владельца): вопросы задаёт САМА программа, а не браузер. Раньше здесь был
    //  голый confirm(): чужое серое окно без объяснений, с кнопками «ОК» и «Отмена». Теперь это
    //  наше окно: заголовок, понятный текст, при нужде список затрагиваемого и кнопка, названная
    //  действием. Enter — согласиться, Esc или щелчок мимо — отказаться.
    //  askConfirm возвращает обещание: true — согласился, false — отказался.
    const _L = (ru, en) => (lang.value === 'ru' ? ru : en);
    const confirmBox = ref(null);
    const askConfirm = (opts) => new Promise((resolve) => {
        const o = opts || {};
        confirmBox.value = {
            title: o.title || _L('Подтвердите действие', 'Confirm'),
            text: o.text || '',
            list: o.list || '',
            okText: o.okText || _L('Продолжить', 'Continue'),
            danger: !!o.danger,
            resolve: resolve,
        };
        nextTick(() => { try { const b = document.querySelector('.fm-ask-ok'); if (b) b.focus(); } catch (e) {} });
    });
    const confirmAnswer = (yes) => {
        const box = confirmBox.value;
        confirmBox.value = null;
        if (box && box.resolve) box.resolve(!!yes);
    };

    const toasts = ref([]);
    let _toastSeq = 0;
    const dismissToast = (id) => {
        const i = toasts.value.findIndex(x => x.id === id);
        if (i >= 0) toasts.value.splice(i, 1);
    };
    const clearMessages = () => { toasts.value = []; };
    //  Вид сообщения по его типу: 'work' — идёт дело (колесо и полоса), 'ok' — получилось,
    //  'bad' — беда, 'warn' — предупреждение, 'info' — просто сообщение.
    const msgKind = (t) => {
        if (!t) return 'info';
        if (t.type === 'progress' || t.pct != null) return 'work';
        if (t.type === 'success' || t.type === 'ok') return 'ok';
        if (t.type === 'error') return 'bad';
        if (t.type === 'warn') return 'warn';
        return 'info';
    };
    //  Подметание: раз в несколько секунд убираем то, что уже не про «сейчас». Сообщение
    //  с условием уходит, как только условие сказало «неактуально», но не раньше, чем его
    //  можно было прочитать.
    const _msgSweep = () => {
        const now = Date.now();
        const keep = toasts.value.filter(t => {
            if (t.pct != null || t.type === 'progress') return true;       // дело идёт — не трогаем
            if (t.stale && (now - (t.bornAt || 0)) >= MSG_MIN_LIFE) {
                try { if (t.stale()) return false; } catch (e) { /* условие сломалось — держим по сроку */ }
            }
            return !t.dieAt || now < t.dieAt;
        });
        if (keep.length !== toasts.value.length) toasts.value = keep;
    };
    if (typeof window !== 'undefined') setInterval(_msgSweep, MSG_SWEEP_MS);

    //  Порядок показа: свежее сверху.
    const msgView = computed(() => toasts.value.slice().reverse());
    const _msgTime = () => {
        const d = new Date();
        return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
    };
    const pushToast = (msg, type, ttl, opts) => {
        const id = ++_toastSeq;
        const t = { id: id, msg: msg, type: type || 'info', at: _msgTime(), fresh: true };
        //  Срок: явно заданный (но не короче читаемого) либо обычный для этого вида. Ноль — вечно.
        const _life = (ttl != null && ttl > 0) ? Math.max(MSG_MIN_LIFE, ttl) : MSG_LIFE[msgKind(t)];
        t.bornAt = Date.now();
        t.dieAt = _life ? t.bornAt + _life : 0;
        //  Условие: функция, которая говорит, что сообщение УЖЕ НЕ ПРО СЕЙЧАС.
        t.stale = (opts && typeof opts.stale === 'function') ? opts.stale : null;
        //  2.974: одно и то же сообщение не встаёт в панель дважды. Раньше повтор (перезагрузка
        //  страницы, второй заход того же кода) добавлял ещё одну такую же строку, и владелец
        //  видел два предупреждения об одной катушке. Теперь повтор лишь обновляет время у той,
        //  что уже стоит: сообщение остаётся одно, но видно, что оно снова про сейчас.
        const _same = toasts.value.find(x => x && x.msg === t.msg && x.type === t.type && x.pct == null);
        if (_same) {
            _same.at = t.at; _same.fresh = true; _same.bornAt = t.bornAt; _same.dieAt = t.dieAt;
            setTimeout(() => { const y = toasts.value.find(z => z.id === _same.id); if (y) y.fresh = false; }, MSG_FRESH_MS);
            return _same.id;
        }
        toasts.value.push(t);
        if (toasts.value.length > MSG_KEEP) toasts.value.splice(0, toasts.value.length - MSG_KEEP);
        //  «Свежее» — только подсветка на несколько секунд, само сообщение не исчезает.
        setTimeout(() => { const x = toasts.value.find(y => y.id === id); if (x) x.fresh = false; }, MSG_FRESH_MS);
        //  Беду прятать нельзя: свёрнутая панель разворачивается сама.
        if (t.type === 'error' || t.type === 'warn') {
            try { if (suggestCollapsed.value) toggleSuggestCollapsed(); } catch (e) {}
        }
        return id;
    };
    const updateToast = (id, patch) => {
        const t = toasts.value.find(x => x.id === id);
        if (!t) return;
        Object.assign(t, patch);
        //  Вид сообщения сменился (дело шло — и закончилось): срок считаем заново от этого
        //  мгновения, иначе «готово» осталось бы висеть вечно со сроком «дела в работе».
        if (patch && ('type' in patch || 'pct' in patch)) {
            const life = MSG_LIFE[msgKind(t)];
            t.bornAt = Date.now();
            t.dieAt = life ? t.bornAt + life : 0;
        }
    };
    // Фоновый опрос сводки здоровья парка (даже когда окно диагностики закрыто): переход принтера
    // в проблему пишем в журнал диагностики — только на ПЕРЕХОДЕ (без повторов, пока она держится);
    // первые опросы — тихо запоминаем базу. Всплывающих тостов о связи нет: статус виден на карточках.
    let _diagAlertTimer = null, _diagAlertSeed = 2;
    const _diagAlerted = {};   // pid -> { msg, ts }: тот же сбой по принтеру шлём в журнал один раз; повтор той же формулировки — не чаще раза в 10 минут, «моргание» связи повторов не создаёт
    const pollDiagSummary = async () => {
        try {
            const r = await fetch('/api/diagnostics/summary');
            if (!r.ok) return;
            const j = await r.json();
            const probs = (j && j.problems) || [];
            const now = Date.now();
            if (_diagAlertSeed > 0) { _diagAlertSeed--; probs.forEach(p => { _diagAlerted[p.pid] = { sig: (p.name + ': ' + (p.issue || 'connection issue')).replace(/\d+/g, '#'), ts: now }; }); return; }   // прогрев: запоминаем базу молча
            for (const p of probs) {
                const msg = p.name + ': ' + (p.issue || 'connection issue');
                const sig = msg.replace(/\d+/g, '#');   // числа (мс задержки и т.п.) не делают сбой «новым»
                const e = _diagAlerted[p.pid];
                if (e && e.sig === sig && (now - e.ts) < 600000) continue;   // тот же сбой — уже сообщали
                _diagAlerted[p.pid] = { sig: sig, ts: now };
                try { fetch('/api/diagnostics/client', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ level: p.overall === 'fail' ? 'error' : 'warning', msg: '[LINK] ' + msg }) }); } catch (e2) {}
            }
        } catch (e) {}
    };
    // Универсальный индикатор «в процессе»: для любого долгого серверного действия
    // (загрузка на принтер, привязка/загрузка файла, обновление превью, импорт и т.п.)
    // показываем тост со спиннером, пока запрос выполняется. Порог 300мс не даёт быстрым
    // запросам мигать; скрывается автоматически по завершении. Перехват один — отдельные
    // функции дорабатывать не нужно. Оригинальный fetch вызывается всегда (тост — побочный
    // эффект в try/catch), поэтому перехватчик не может сломать сетевые запросы.
    const _BUSY_RULES = [
        [/\/api\/printer\/[^/?]+\/print_path/, 'Uploading to printer…'],
        [/\/api\/part\/print/, 'Uploading to printer…'],
        [/\/api\/projects2\/[^/]+\/files\/[^/?]+\/print/, 'Uploading to printer…', 'POST'],   // Alpha 2.630: печать файла проекта (мгновенная) — раньше busy-правила не было
        [/\/api\/printer\/[^/?]+\/cmd/, 'Sending to printer…'],
        [/\/api\/(part\/(attach-path|pick|pick-path)|staging\/pick)/, 'Adding file…'],
        [/\/api\/parts\/rebuild-previews/, 'Refreshing previews…'],
        [/\/api\/import-path/, 'Importing…'],
        [/\/api\/projects2\/import-files/, 'Importing…'],
        [/\/api\/fs\/stage/, 'Adding to tasks…'],
        // Расширенное покрытие: частые действия, у которых раньше не было индикации.
        // ВАЖНО: пути уникальны и НЕ совпадают с GET-опросами (перехватчик матчит по URL, без метода):
        // '/api/staging/save|delete' ≠ GET '/api/staging'; '/api/projects2/<id>/parts' ≠ GET '/partsview'.
        [/\/api\/staging\/save/, 'Saving...'],
        [/\/api\/staging\/delete/, 'Working…'],
        [/\/api\/projects2\/[^/]+\/parts(\/|$)/, 'Working…'],
        // Метод-aware правила (необязательный 3-й элемент = HTTP-метод): покрывают действия, чьи URL
        // пересекаются с GET-опросами, поэтому различаем ПО МЕТОДУ — фоновые GET-опросы под них не попадают.
        [/\/api\/projects2\/[^/?]+$/, 'Saving...', 'PATCH'],                 // переименование проекта / смена срока (saveProject2Name, _patchProject2)
        [/\/api\/projects2\/[^/?]+$/, 'Working…', 'DELETE'],                 // удаление проекта (deleteProject2)
        [/\/api\/projects2\/[^/]+\/files\/[^/?]+$/, 'Working…', 'DELETE'],   // удаление файла проекта (deleteProject2File)
    ];
    // Необязательный 3-й элемент правила — HTTP-метод: если задан и не совпал, правило пропускается.
    // Правила без метода матчат по URL при любом методе — прежнее поведение сохраняется.
    const _busyLabel = (u, m) => { for (let k = 0; k < _BUSY_RULES.length; k++) { const r = _BUSY_RULES[k]; if (r[2] && r[2] !== m) continue; if (r[0].test(u)) return r[1]; } return null; };
    const _origFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
        let tid = null, timer = null;
        try {
            const u = (typeof input === 'string') ? input : ((input && input.url) || '');
            const m = String((init && init.method) || (typeof input !== 'string' && input && input.method) || 'GET').toUpperCase();
            const label = _busyLabel(u, m);
            // Alpha 2.684: печатный тост «Uploading to printer…» не дублируем, если уже показан полноценный
            // индикатор отправки (sendJob) или пакетный оверлей (printSending). Прочие busy-тосты не трогаем.
            const _suppress = (label === 'Uploading to printer…') && (sendActiveCount.value > 0);
            if (label && !_suppress) timer = setTimeout(() => { try { tid = pushToast(tr(label), 'info', 0); } catch (e) {} }, 300);
        } catch (e) {}
        const p = _origFetch(input, init);
        if (timer) { const fin = () => { try { clearTimeout(timer); if (tid !== null) dismissToast(tid); } catch (e) {} }; p.then(fin, fin); }
        return p;
    };
    // Загрузка файла из браузера на сервер с РЕАЛЬНОЙ шкалой прогресса. XHR, в отличие от
    // fetch, отдаёт прогресс отправки байтов. Тост-«progress» показывает 0–100% по мере
    // отдачи; когда отдача завершена — переключается на спиннер (сервер дообрабатывает запрос
    // и, для печати, отправляет файл на принтер). Возвращает { ok, status, body } —
    // совместимо с местами, где раньше читали r.json().
    const uploadWithProgress = (url, formData, label) => {
        return new Promise((resolve, reject) => {
            let tid = null;
            try { tid = pushToast(tr(label || 'Uploading file…'), 'info', 0); } catch (e) {}
            const xhr = new XMLHttpRequest();
            xhr.open('POST', url, true);
            if (xhr.upload) {
                xhr.upload.onprogress = (ev) => {
                    try {
                        if (tid === null) return;
                        if (ev.lengthComputable && ev.total > 0) {
                            const pct = Math.round(ev.loaded * 100 / ev.total);
                            if (pct >= 100) updateToast(tid, { type: 'info', pct: 100 });
                            else updateToast(tid, { type: 'progress', pct: pct });
                        }
                    } catch (e) {}
                };
                xhr.upload.onload = () => { try { if (tid !== null) updateToast(tid, { type: 'info', pct: 100 }); } catch (e) {} };
            }
            xhr.onload = () => {
                try { if (tid !== null) dismissToast(tid); } catch (e) {}
                let body = null;
                try { body = JSON.parse(xhr.responseText); } catch (e) { body = null; }
                resolve({ ok: (xhr.status >= 200 && xhr.status < 300), status: xhr.status, body: body });
            };
            xhr.onerror = () => { try { if (tid !== null) dismissToast(tid); } catch (e) {} reject(new Error('upload failed')); };
            xhr.send(formData);
        });
    };
    const exPrint = async (amsSlot, print_opts = undefined) => {
        exAmsOpen.value = false;
        const it = exSelItem.value;
        if (!it || it.is_dir || !exPrintPid.value) return;
        const low = (it.ext || '').toLowerCase();
        if (low !== '.gcode' && low !== '.3mf') { alert(tr('only .gcode and .3mf are supported')); return; }
        // Alpha 2.687: окно параметров запуска ПЕРЕД отправкой (печать из проводника). После «Печать» — повтор с print_opts.
        if (print_opts === undefined) {
            openPrintStart({ printerId: exPrintPid.value, label: (it.name || ''), source: 'explorer', amsSlot: (amsSlot === undefined ? null : amsSlot), onConfirm: (opts, srcSlot) => exPrint((srcSlot === undefined ? (amsSlot === undefined ? null : amsSlot) : srcSlot), opts) });
            return;
        }
        const _slot = (amsSlot === undefined || amsSlot === null) ? null : Number(amsSlot);
        const pid = exPrintPid.value, path = it.path;
        // Окно закрывается сразу; загрузка файла на принтер и старт идут в фоне.
        // Alpha 2.684: показываем ЕДИНЫЙ индикатор отправки (sendJob), как и в остальных сценариях.
        exOpen.value = false; showModal.value = false;
        const _ctx = { printer_id: pid, printer_name: _printerNameOf(pid), file_name: (it.name || String(path || '').split(/[\\/]/).pop()), source: 'print_path' };
        try {
            const _pbody = { path: path, ams_slot: _slot };
            if (print_opts) _pbody.print_opts = print_opts;   // Alpha 2.687: опции запуска (только Bambu)
            const _url = '/api/printer/' + encodeURIComponent(pid) + '/print_path';
            // R-019: отказ «принтер удержан» (план проекта держит принтер) приходит кодом — словами.
            const _failText = (r) => (r && (r.reason === 'printer_held' || r.reason === 'printer_busy'))
                ? readinessReasonText(r.reason) : tr((r && r.reason) || 'Failed to start print.');
            // 29.09.2026 (R-019): повторная отправка из окна «Материал закончился». skipFilament —
            // владелец выбрал «Печатать всё равно» (остаток уже списан окном), склад не спрашиваем.
            const _launch = async (skipFilament) => {
                const b = Object.assign({}, _pbody);
                if (skipFilament) b.skip_filament = true;
                const r = await (await fetch(_url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })).json();
                //  16.10.2026 (R-019): склад снова против — окно покажет новую нехватку.
                if (!skipFilament && r && r.status === 'low_filament')
                    return { low_filament: Object.assign({}, r, { printer_id: pid, printer_name: _ctx.printer_name }) };
                ((r && r.notes) || []).forEach(n => pushFilNote(n));
                const how = handleSendResp(r, _ctx);
                if (how === 'other') pushToast(_failText(r), 'info');
                return how === 'accepted';
            };
            const j = await (await fetch(_url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(_pbody) })).json();
            // R-019: склад против — то же окно решения, что у запуска из задач, проекта и очереди.
            if (j && j.status === 'low_filament') {
                openFilamentDecision([Object.assign({}, j, { printer_id: pid, printer_name: _ctx.printer_name })],
                                     [{ printer_id: pid, launch: _launch }], 0, true);
                return;
            }
            ((j && j.notes) || []).forEach(n => pushFilNote(n));
            // Alpha 2.728: accepted → панель отправок; 409 → тост; иначе — ошибка тостом (окно уже закрыто, UI не блокируется).
            if (handleSendResp(j, _ctx) === 'other') pushToast(_failText(j), 'info');
        } catch (e) { pushToast(String(e), 'info'); }
    };
    const exReveal = async (srcPath) => {
        exMode.value = 'tasks'; exPart.value = null;
        exOpen.value = true; exWinEnsure(); exSelected.value = []; exAnchor.value = ''; exError.value = '';
        try {
            const j = await (await fetch('/api/fs/roots')).json();
            exQuick.value = j.quick || []; exDrives.value = j.drives || [];
        } catch (e) {}
        await exGo((srcPath || '').trim());
        await nextTick();
        try {
            const list = document.querySelector('.ex-list');
            const el = list ? list.querySelector('.ex-row.sel') : null;
            if (list && el) {
                const lr = list.getBoundingClientRect(), er = el.getBoundingClientRect();
                list.scrollTop += (er.top - lr.top) - (list.clientHeight / 2) + (el.offsetHeight / 2);
            }
        } catch (e) {}
    };
    const exRefresh = async () => {
        if (!exOpen.value || exLoading.value) return;
        try {
            const j = await (await fetch('/api/fs/roots')).json();
            exQuick.value = j.quick || []; exDrives.value = j.drives || [];
        } catch (e) {}
        try {
            const r = await fetch('/api/fs/list?path=' + encodeURIComponent(exPath.value || ''));
            const j = await r.json();
            if (j.status === 'ok') {
                exItems.value = j.items || []; exParent.value = j.parent || ''; exCrumbs.value = j.crumbs || []; exError.value = '';
                exSelected.value = exSelected.value.filter(p => exItems.value.some(it => it.path === p));
            } else { exGo(''); }
        } catch (e) {}
    };
    setInterval(exRefresh, 2500);
    const exAttach = async () => {
        const it = exSelItem.value;
        if (!it || it.is_dir || !exPart.value) return;
        const low = (it.ext || '').toLowerCase();
        if (low !== '.gcode' && low !== '.3mf') { alert(tr('only .gcode and .3mf are supported')); return; }
        const part = exPart.value;   // фиксируем до закрытия окна
        exOpen.value = false;        // окно закрываем сразу; привязка идёт в фоне (тост «Добавление файла…»)
        try {
            const r = await fetch('/api/part/pick-path', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: it.path }) });
            const j = await r.json();
            if (j.status === 'ok' && j.filename) {
                part.gcode_file = j.filename;
                part.src_path = j.src_path || '';
                part.preview_base64 = j.preview || '';
                debouncedSave();
            } else alert(tr(j.reason || 'Failed to attach file.'));
        } catch (e) { alert(String(e)); }
    };
    const exUp = () => { if (exParent.value) exGo(exParent.value); };
    const exSelect = (it, e) => {
        e = e || {};
        const p = it.path;
        if (e.ctrlKey || e.metaKey) {
            const arr = exSelected.value.slice();
            const i = arr.indexOf(p);
            if (i >= 0) arr.splice(i, 1); else arr.push(p);
            exSelected.value = arr; exAnchor.value = p;
        } else if (e.shiftKey && exAnchor.value) {
            const paths = exSortedItems.value.map(x => x.path);
            let a = paths.indexOf(exAnchor.value), b = paths.indexOf(p);
            if (a < 0) a = b;
            exSelected.value = paths.slice(Math.min(a, b), Math.max(a, b) + 1);
        } else {
            exSelected.value = [p]; exAnchor.value = p;
        }
        exPrevOk.value = true;
    };
    // 2.716: ЕДИНЫЙ диспетчер подтверждения файла Проводника — по exMode отдаёт валидацию типа + ту же
    // confirm-функцию, что и соответствующая кнопка внизу окна (index.html «ex-foot»). Двойной клик и
    // кнопка вызывают ОДНУ функцию — второго пути бизнес-логики нет; новый режим добавляется одной строкой.
    // ВАЖНО: режим 'import' принимает И план/архив (_isImportFile → exImport), И реальные файлы деталей
    // (_isPartFile → exImportFiles) — именно второй случай («Новый проект → Загрузить» + .gcode/.stl/.3mf)
    // не срабатывал до 2.716. Возвращает функцию-подтверждение или null (тип не подходит → только выделение).
    const exConfirmFnFor = (it) => {
        const low = (it.ext || '').toLowerCase();
        const isPart = _isPartFile(it.name);
        switch (exMode.value) {
            case 'tasks':  return it.printable ? exLoad : null;
            case 'attach': return (low === '.gcode' || low === '.3mf') ? exAttach : null;
            case 'parts':  return isPart ? exAddFilesToParts : null;
            case 'import': return _isImportFile(it.name) ? exImport : (isPart ? exImportFiles : null);
            case 'p2add':  return isPart ? exAddFilesToProject2 : null;
            case 'slicer': return low === '.exe' ? exChooseSlicer : null;
            case 'modzip': return low === '.zip' ? exInstallModule : null;
            case 'print':  return (low === '.gcode' || low === '.3mf')
                ? (() => exPrint(null))   // Alpha 2.729: сразу «Параметры запуска печати» (источник — только там); старый exAms-дропдаун не открываем
                : null;
            default:       return null;   // pickdir и пр.: файл не подтверждаем (папки навигируются двойным кликом)
        }
    };
    const exOpenItem = (it) => {
        if (it.is_dir) { exGo(it.path); return; }                                        // папка → открыть
        if (moduleInstalling.value || importProg.value.active) return;                   // операция уже идёт — игнорируем повторный dblclick (без двойного запуска)
        exSelected.value = [it.path]; exAnchor.value = it.path; exPrevOk.value = true;   // выделить дважды кликнутый файл (как обычный клик)
        const fn = exConfirmFnFor(it);
        if (fn) fn();                                                                    // подходящий тип → та же функция, что кнопка; иначе только выделение
    };
    const exLoad = async () => {
        const paths = exPrintableSel.value;
        if (!paths.length) return;
        exOpen.value = false;   // окно закрываем сразу; загрузка идёт в фоне (тост «Добавление в задачи…»)
        try {
            const r = await fetch('/api/fs/stage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths }) });
            const j = await r.json();
            if ((j.added || []).length) { fetchStaging(); } else alert(tr('Failed to load files.'));
        } catch (e) { alert(String(e)); }
    };
    const exIcon = (it) => { const e = (it.ext || '').toLowerCase(); if (it.printable) return '🧩'; if (['.png','.jpg','.jpeg','.gif','.bmp','.webp','.svg'].includes(e)) return '🖼'; if (['.txt','.md','.csv','.log','.ini','.cfg','.json','.xml'].includes(e)) return '📄'; if (['.zip','.rar','.7z','.tar','.gz'].includes(e)) return '🗜'; if (['.exe','.bat','.msi'].includes(e)) return '⚙'; return '📄'; };
    const _uniquePartName = (base) => {
        const used = new Set(parts.value.filter(p => !p.is_deleted).map(p => p.part_name));
        if (!used.has(base)) return base;
        let n = 2; while (used.has(base + ' (' + n + ')')) n++;
        return base + ' (' + n + ')';
    };
    const _mkPartFromPath = (path, name, pName, due) => {
        const dot = (name || '').lastIndexOf('.');
        const base = ((dot > 0 ? name.slice(0, dot) : name) || name || 'Part').trim() || 'Part';
        parts.value.push({
            part_name: _uniquePartName(base), required_qty: 1, printed_qty: 0, status: 'pending',
            project_name: pName, due_date: due || '', is_deleted: 0,
            order_idx: parts.value.length, _uid: 'new_' + Date.now() + '_' + Math.random().toString(36).slice(2, 9),
            preview_base64: '', notes: '', gcode_file: name, src_path: path
        });
    };
    const exAddFilesToParts = () => {
        const pName = exProject.value; if (!pName) return;
        const sel = exItems.value.filter(i => exSelected.value.indexOf(i.path) >= 0 && !i.is_dir && _isPartFile(i.name));
        if (!sel.length) return;
        const ex = parts.value.find(p => p.project_name === pName); const due = ex ? ex.due_date : '';
        sel.forEach(i => _mkPartFromPath(i.path, i.name, pName, due));
        expandedProjects.value[pName] = true; debouncedSave(); exOpen.value = false;
    };
    const exAddFolderToParts = async () => {
        const pName = exProject.value; const it = exSelItem.value;
        if (!pName || !it || !it.is_dir) return;
        const folderPath = it.path;   // фиксируем до закрытия окна
        exOpen.value = false;         // окно закрываем сразу; добавление папки идёт в фоне
        try {
            const r = await fetch('/api/fs/list?path=' + encodeURIComponent(folderPath));
            const j = await r.json();
            if (j.status !== 'ok') { alert(tr(j.reason || 'No access to this folder')); return; }
            const files = (j.items || []).filter(x => !x.is_dir && _isPartFile(x.name));
            if (!files.length) { alert(tr('No STL / 3MF / G-code files in this folder')); return; }
            const ex = parts.value.find(p => p.project_name === pName); const due = ex ? ex.due_date : '';
            files.forEach(x => _mkPartFromPath(x.path, x.name, pName, due));
            expandedProjects.value[pName] = true; debouncedSave();
        } catch (e) { alert(String(e)); }
    };
    const openExplorerForImport = () => exOpenWith('import', null);
    const openExplorerInArchive = async () => {   // импорт архива: всегда открыть Проводник в папке Archive
        let ap = '';
        try { const r = await fetch('/api/archive-path'); const j = await r.json(); ap = j.path || ''; } catch (e) {}
        return exOpenWith('import', null, ap);
    };
    const openExplorerForSlicer = () => exOpenWith('slicer', null);   // выбрать .exe слайсера через наш Проводник
    const pickArchiveDir = () => { pickDirTarget.value = 'archive'; return exOpenWith('pickdir', null, (storageInfo.value && storageInfo.value.archive_dir) || ''); };   // выбрать папку архивов через наш Проводник
    const pickDataDir = () => { pickDirTarget.value = 'data'; return exOpenWith('pickdir', null, (storageInfo.value && storageInfo.value.data_dir) || ''); };   // выбрать папку данных через наш Проводник
    const exPickDir = () => {   // подтвердить выбор папки: выбранная папка-элемент, иначе текущая открытая
        const sel = exSelItem.value;
        const target = (sel && sel.is_dir) ? sel.path : exPath.value;
        if (!target) return;
        exOpen.value = false;
        if (pickDirTarget.value === 'ddu') { dduAdopt(target); }   // 16.10.2026 (R-151): «папка теперь в другом месте»
        else if (pickDirTarget.value === 'data') { applyDataDir(target); }
        else { archiveDirInput.value = target; applyArchiveDir(); }
    };
    const exChooseSlicer = async () => {
        const it = exSelItem.value;
        if (!it || it.is_dir || (it.ext || '').toLowerCase() !== '.exe') return;
        const path = it.path;   // фиксируем до закрытия окна
        exOpen.value = false;   // окно закрываем сразу
        try {
            const r = await (await fetch('/api/slicer/choose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) })).json();
            if (r && r.status === 'ok') slicerChoice.value = path;
        } catch (e) {}
        await loadSlicers();
    };
    const exImportSel = computed(() => exItems.value.filter(i => exSelected.value.indexOf(i.path) >= 0 && !i.is_dir && _isImportFile(i.name)).map(i => i.path));
    const exImport = async () => {
        // все выбранные файлы-архивы/планы (а не только сфокусированный) — чтобы импортировать несколько проектов разом
        let paths = exImportSel.value.slice();
        if (!paths.length) { const it = exSelItem.value; if (it && !it.is_dir && _isImportFile(it.name)) paths = [it.path]; }
        if (!paths.length) return;
        exOpen.value = false;   // окно закрываем сразу; импорт идёт в фоне
        let okCount = 0, partTotal = 0, anyArchive = false, anyParts = false, failReason = '';
        for (const p of paths) {
            try {
                const r = await fetch('/api/import-path', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: p }) });
                const j = await r.json();
                if (j.status === 'ok' || j.status === 'success') {
                    okCount++;
                    if (j.imported && typeof j.imported === 'object') anyArchive = true;
                    else if (j.imported !== undefined) { anyParts = true; partTotal += (parseInt(j.imported) || 0); }
                } else { failReason = failReason || (j.reason || 'unknown'); }
            } catch (e) { failReason = failReason || 'unknown'; }
        }
        printersEditMode.value = false; editingProjects.value = {};
        await fetchStateMatrix();
        await loadProjects2();                                                    // архив мог создать/дополнить Проекты 2.0
        const _ep = project2Expanded.value; if (_ep) await loadProject2Tree(_ep); // обновить открытый проект
        if (okCount > 1) alert(tr('Archive loaded') + ' · ' + okCount);
        else if (anyArchive) alert(tr('Archive loaded'));
        else if (anyParts) alert(tr('Imported: ') + partTotal + tr(' parts'));
        else alert(tr('Import failed: ') + tr(failReason || 'unknown'));
    };
    // ── Пофайловый импорт с полосой прогресса (короткие запросы, сервер не блокируется) ──
    const importProg = ref({ active: false, done: 0, total: 0, name: '', label: '' });
    const _addOneToProject2 = async (pid, path, order) => {
        try {
            const body = { path };
            if (order !== undefined && order !== null) body.order = order;
            const r = await fetch('/api/projects2/' + pid + '/files/pick-path', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            const j = await r.json().catch(() => null);
            return !!(j && j.status === 'ok');
        } catch (e) { return false; }
    };
    const _runImportWithProgress = async (paths, addOne, label) => {
        if (importProg.value.active) return { ok: 0, fail: 0 };   // не запускать второй импорт поверх первого
        importProg.value = { active: true, done: 0, total: paths.length, name: '', label: tr(label) };
        let ok = 0, fail = 0;
        // Параллелизм = число рабочих процессов сервера (~70% ядер), но не больше числа файлов.
        let conc = 4;
        try {
            const r = await fetch('/api/import/parallelism');
            const j = await r.json();
            if (j && j.workers) conc = j.workers | 0;
        } catch (e) {}
        conc = Math.max(1, Math.min(conc, paths.length));
        let next = 0;
        const worker = async () => {
            while (next < paths.length) {
                const i = next++;
                const p = paths[i];
                importProg.value.name = String(p).split(/[\\/]/).pop();
                try { if (await addOne(p, i)) ok++; else fail++; } catch (e) { fail++; }
                importProg.value.done++;
            }
        };
        try {
            await Promise.all(Array.from({ length: conc }, () => worker()));
        } finally { importProg.value.active = false; }
        return { ok, fail };
    };
    // Импорт выбранных файлов-моделей/g-code как НОВОГО проекта 2.0 (оригиналы по пути, без копий).
    const exImportFiles = async () => {
        const paths = exPartFilesSel.value.slice();
        if (!paths.length || importProg.value.active) return;
        exOpen.value = false;   // окно закрываем сразу; импорт идёт с полосой прогресса
        let pid = '';
        try {
            const r = await fetch('/api/projects2/import-begin', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
            const j = await r.json();
            if (j.status === 'ok' && j.project_id) pid = j.project_id;
        } catch (e) {}
        if (!pid) { alert(tr('Import failed')); return; }
        const res = await _runImportWithProgress(paths, (p, i) => _addOneToProject2(pid, p, i), 'Importing…');
        await loadProjects2();
        project2Expanded.value = pid;
        await loadProject2Tree(pid);
        await loadPartsView(pid);
        if (res.fail) alert(tr('Import failed: ') + res.fail + ' / ' + paths.length);
    };
    // Открыть модель проектной детали в слайсере (по file_id). Использует выбранный в шапке слайсер.
    const sliceProject2File = async (fileId, slicerPath) => {
        if (!fileId) return;
        try {
            const body = slicerPath ? JSON.stringify({ slicer: slicerPath }) : '{}';
            const send = () => fetch('/api/projects2/files/' + fileId + '/slice', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body }).then(r => r.json());
            let j = await send();
            if (j.status === 'no_slicer') {
                if (await askConfirm({ title: _L('Слайсер не найден', 'Slicer not found'), text: tr('Slicer not found automatically. Select the slicer program (.exe) manually?'), okText: _L('Выбрать программу', 'Choose program') })) {
                    const pr = await (await fetch('/api/slicer/pick', { method: 'POST' })).json();
                    if (pr.status === 'ok' && pr.path) { loadSlicers(); j = await send(); }
                    else if (pr.status === 'error') { alert(tr(pr.reason || 'Failed to set the slicer.')); }
                }
            }
            if (j.status === 'error') alert(tr('Failed to open in slicer: ') + tr(j.reason || ''));
        } catch (e) {}
    };
    // Строка детали: file_id первой плиты (иконка превью) и file_id плиты-модели (кнопка слайсера).
    const pvFirstFid = (pp) => (pp && pp.plates && pp.plates[0] && pp.plates[0].file_id) || '';
    // Alpha 2.822: единый резолвер миниатюр РЕДАКТОРА проекта. Тот же preview-контракт, что и
    // основной список: для детали /part-thumb (per-part slicer -> плита -> контур -> mesh), для
    // файла /thumb (встроенный PNG плиты -> mesh). URL строится ТОЛЬКО из file_id (same-origin);
    // локальные пути (stored_path/src_path/DATA_DIR) во фронт не приходят и в URL не попадают.
    // Токен ?v= — из content_hash файла: стабилен между рендерами, но меняется при переслайсинге
    // (cache-bust без случайного timestamp). Нет file_id -> безопасная иконка THUMB_FALLBACK.
    const _p2Ver = (h) => { const s = String(h == null ? '' : h); return s ? s.slice(0, 12) : ''; };
    const p2PartThumb = (pp) => {
        const fid = pvFirstFid(pp);
        if (!fid) return THUMB_FALLBACK;
        const pl = (pp && pp.plates && pp.plates[0]) || {};
        const v = _p2Ver(pl.content_hash);
        return '/api/projects2/files/' + encodeURIComponent(fid) + '/part-thumb?name='
            + encodeURIComponent(pp && pp.part_name ? pp.part_name : '') + (v ? '&v=' + encodeURIComponent(v) : '');
    };
    const p2FileThumb = (fn) => {
        const fid = (fn && fn.file_id) || '';
        if (!fid) return THUMB_FALLBACK;
        const v = _p2Ver(fn.content_hash);
        return '/api/projects2/files/' + encodeURIComponent(fid) + '/thumb?v=' + encodeURIComponent(v || fid);
    };
    // Счётчик вариантов печати у имени детали: считаем ТОЛЬКО печатаемые файлы (модель .stl/.3mf не вариант печати).
    // Чистая модель без g-code всё равно читается как «1», чтобы не показывать «0».
    const pvVariantCount = (pp) => { const n = ((pp && pp.plates) || []).filter(p => p.is_printable).length; return n > 0 ? n : 1; };

    // ===== Интерактивные подсказки (обучение при наведении) =====
    // Один глобальный слушатель ловит наведение на ЛЮБОЙ элемент с атрибутом
    // data-help, через 0.5 с показывает подсказку из реестра HELP_HINTS и ставит
    // её рядом с элементом — не перекрывая его и не выходя за экран. Новым
    // элементам достаточно атрибута data-help + записи в web/composables/helpHints.js.
    const HELP_HINT_KEY = 'farm_help_hints';
    const helpHintsEnabled = ref(false);
    try { if (localStorage.getItem(HELP_HINT_KEY) === '1') helpHintsEnabled.value = true; } catch (e) {}
    const helpTip = ref({ show: false, title: '', text: '' });
    const helpTipPos = ref({ left: 0, top: 0, ready: false });
    let _helpEl = null, _helpTimer = null;
    const helpTipStyle = computed(() => ({
        left: helpTipPos.value.left + 'px',
        top: helpTipPos.value.top + 'px',
        opacity: helpTipPos.value.ready ? '1' : '0'
    }));
    const _helpEntry = (key) => {
        const e = HELP_HINTS[key];
        if (!e) return null;
        // 16.10.2026 (аудит docs-materials-15): часть подсказок записана как {ru:{…}, en:{…}} — русский
        // вариант читался из e.title/e.text и был пуст, рамка подсказки появлялась без текста.
        const b = (lang.value === 'en' && e.en) ? e.en : (e.ru || e);
        return { title: b.title, text: b.text };
    };
    const _helpClearTimer = () => { if (_helpTimer) { clearTimeout(_helpTimer); _helpTimer = null; } };
    const _helpHideNow = () => {
        _helpClearTimer();
        _helpEl = null;
        if (helpTip.value.show) helpTip.value = { show: false, title: '', text: '' };
        if (helpTipPos.value.ready) helpTipPos.value = { left: 0, top: 0, ready: false };
    };
    // Размещение: выбираем сторону с запасом места (снизу→сверху→справа→слева),
    // отступаем gap от элемента (не перекрываем), затем зажимаем в экран (не обрезаем).
    const _helpPlace = (rect) => {
        const el = document.getElementById('helpTipEl');
        if (!el) return;
        // getBoundingClientRect и innerWidth/Height — ВИЗУАЛЬНЫЕ px (с учётом html{zoom}).
        // Подсказка position:fixed рендерится ПОД этим zoom, поэтому считаем и ставим всё в CSS-px
        // (делим визуальные величины на живой zoom) — как контекстное меню / rework-поп-ап. offsetWidth/Height уже в CSS-px.
        const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
        const gap = 10, m = 8;
        const r = { left: rect.left / z, top: rect.top / z, right: rect.right / z, bottom: rect.bottom / z, width: rect.width / z, height: rect.height / z };
        const vw = (window.innerWidth || 1280) / z, vh = (window.innerHeight || 800) / z;
        const tipW = el.offsetWidth, tipH = el.offsetHeight;
        const sBelow = vh - r.bottom, sAbove = r.top, sRight = vw - r.right, sLeft = r.left;
        let side;
        if (sBelow >= tipH + gap + m) side = 'below';
        else if (sAbove >= tipH + gap + m) side = 'above';
        else if (sRight >= tipW + gap + m) side = 'right';
        else if (sLeft >= tipW + gap + m) side = 'left';
        else { const a = [['below', sBelow], ['above', sAbove], ['right', sRight], ['left', sLeft]]; a.sort((x, y) => y[1] - x[1]); side = a[0][0]; }
        let left, top;
        if (side === 'below' || side === 'above') {
            top = (side === 'below') ? (r.bottom + gap) : (r.top - gap - tipH);
            left = r.left + r.width / 2 - tipW / 2;
        } else {
            left = (side === 'right') ? (r.right + gap) : (r.left - gap - tipW);
            top = r.top + r.height / 2 - tipH / 2;
        }
        left = Math.max(m, Math.min(vw - tipW - m, left));
        top = Math.max(m, Math.min(vh - tipH - m, top));
        helpTipPos.value = { left: left, top: top, ready: true };
    };
    const _helpShow = (target, key) => {
        const data = _helpEntry(key);
        if (!data) return;
        helpTip.value = { show: true, title: data.title, text: data.text };
        helpTipPos.value = { left: 0, top: 0, ready: false };
        nextTick(() => {
            if (!helpTip.value.show || _helpEl !== target) return;
            try { _helpPlace(target.getBoundingClientRect()); } catch (e) { _helpHideNow(); }
        });
    };
    //  16.10.2026 (R-110): обучение в интерфейсе 3.0 — эти подсказки при наведении (тур 2.0 выключен
    //  флагом TOUR_ENABLED). Новичку панель «Подсказки» ОДИН РАЗ предлагает их включить; любой ответ
    //  (или переключатель в настройках) снимает карточку навсегда для этого браузера. Хранилище
    //  недоступно — карточка не показывается: без памяти об ответе она бы приставала каждый запуск.
    const HELP_OFFER_KEY = 'farm_help_offer_v1';
    const helpOfferDone = ref(true);
    try { helpOfferDone.value = localStorage.getItem(HELP_OFFER_KEY) === '1'; } catch (e) {}
    const helpOfferShow = computed(() => !helpOfferDone.value && !helpHintsEnabled.value && !tourActive.value);
    const _helpOfferMark = () => {
        helpOfferDone.value = true;
        try { localStorage.setItem(HELP_OFFER_KEY, '1'); } catch (e) {}
    };
    const setHelpHints = (v) => {
        helpHintsEnabled.value = !!v;
        try { localStorage.setItem(HELP_HINT_KEY, helpHintsEnabled.value ? '1' : '0'); } catch (e) {}
        if (!helpHintsEnabled.value) _helpHideNow();
        _helpOfferMark();
    };
    const helpOfferAnswer = (yes) => {
        if (yes) setHelpHints(true);
        _helpOfferMark();
    };
    const _onHelpOver = (e) => {
        if (!helpHintsEnabled.value || tourActive.value) { if (_helpEl) _helpHideNow(); return; }
        const t = e.target;
        const el = (t && t.closest) ? t.closest('[data-help]') : null;
        const key = el ? el.getAttribute('data-help') : '';
        if (!el || !key || !HELP_HINTS[key]) { if (_helpEl) _helpHideNow(); return; }
        if (el === _helpEl) return;
        _helpHideNow();
        _helpEl = el;
        _helpTimer = setTimeout(() => { if (_helpEl === el) _helpShow(el, key); }, 500);
    };
    const _onHelpOut = (e) => { if (_helpEl && !e.relatedTarget) _helpHideNow(); };
    const _onHelpDismiss = () => { if (_helpEl || helpTip.value.show) _helpHideNow(); };
    onMounted(() => {
        document.addEventListener('mouseover', _onHelpOver, true);
        document.addEventListener('mouseout', _onHelpOut, true);
        document.addEventListener('scroll', _onHelpDismiss, true);
        document.addEventListener('mousedown', _onHelpDismiss, true);
        document.addEventListener('keydown', _onHelpDismiss, true);
        window.addEventListener('resize', _onHelpDismiss);
        window.addEventListener('wheel', _onHelpDismiss, { passive: true });
    });

    //  2.976: стыкованная камера живёт в правой половине, а большие окна (настройки,
    //  диагностика, файлы принтеров, отчёты, проводник) эту половину накрывают. Окно камеры
    //  при этом всплывало поверх чужого окна — потому что оно телепортировано наружу. Пока
    //  сверху большое окно, камера гасится; окно закрылось, а пульт всё ещё на камере —
    //  стыкуется заново. Пульт при этом не закрывается: он ждёт под окном.
    if (ui3Mode) {
        //  R-107 (2.985): раскладка дашборда. Пока принтер не выбран — колонка принтеров во всю
        //  ширину, правая половина скрыта и места не занимает; выбрали принтер — справа пульт,
        //  сетка ужимается; закрыли — снова полный обзор. Большие окна (настройки, файлы,
        //  отчёты, диагностика) возвращают обычную ширину колонки.
        watch(() => [viewMode.value, ui3Printer.value, workspaceView.value], ([vm, pp, wv]) => {
            try {
                const cl = document.documentElement.classList;
                const on = ui3Mode && vm === 'dash';
                cl.toggle('ui3-dash', on);
                cl.toggle('ui3-dash-full', on && !pp && wv === 'projects');
                cl.toggle('ui3-dash-pp', on && !!pp && wv === 'projects');
            } catch (e) { /* нет DOM */ }
            nextTick(() => { try { recalcLeftCol(); } catch (e) {} });
        }, { immediate: true });
        watch(() => [workspaceView.value, !!exOpen.value], ([wv, ex]) => {
            if (!ui3Printer.value) return;
            const covered = (wv !== 'projects') || ex;
            if (covered) {
                if (cameraPrinterId.value) { _ui3CamArm(); closeCamera(); document.documentElement.classList.remove('ui3-cam-dock'); }
            } else if (ui3PpView.value === 'cam' && !cameraPrinterId.value && ui3HasCamera(ui3PpP.value)) {
                nextTick(() => setTimeout(ui3PpCamOn, 60));
            }
        });
    }

    return {
        sliCb, sliCbToken, sliCbBusy, sliCbGenerate, sliCbRevoke, sliCbCopy, sliCbHide,
        helpHintsEnabled, setHelpHints, helpTip, helpTipStyle, helpOfferShow, helpOfferAnswer,
        showFileManager, fmSize, fmDate,
        exOpen, exItems, exSortedItems, exSort, exSortDir, exSetSort, exColW, exColStart, exSideW, exSideStart, exPrevW, exPrevStart, exQuick, exDrives, exDriveName, exCrumbs, exParent, exPath, exSelected, exError, exLoading, exPrevOk, exSelItem, exPrintableSel, exGo, openExplorer, exUp, exSelect, exOpenItem, exLoad, exIcon, exMode, exPart, exAttach, exReveal, openExplorerForPrint, exPrint, exAmsOpen, exPrintPid, exAddFilesToParts, exAddFolderToParts, exPartFilesSel, openExplorerForImport, openExplorerInArchive, openExplorerForSlicer, pickArchiveDir, pickDataDir, exPickDir, exChooseSlicer, exImport, exImportFiles, exImportable, exImportSel, importProg, exFs, exZoom, exZoomReset, exWheel, exWinStyle, exWinReset, exDragStart, exResizeStart, exBackdropClose,
        tr, lang, setLang, uiFonts, uiFont, setUiFont, uiTextSizes, uiTextSize, setUiTextSize,
        setSecGo, setSecActive,
        parts, printers, wsData, wsConnected, syncStatus, showAddPrinterModal, printerAddBusy, newPrinter,
        showModelPicker, modelSearch, filteredModels, groupedModels, selectedModelCover, isCrealityModel, setCrealityLink, openModelPicker, pickModel, 
        expandedProjects, expandedStaging, openPlan, editingProjectNames, editingProjectDates, 
        toggleStagingParts, stagingExpandAll, stagingCollapseAll, debouncedSave, 
        addPrinterNode, removePrinterById, openEditPrinter, openAddPrinter, printerSecretHint, toggleAddPrinter, editingPrinterId, openCamera, closeCamera, camFmp4On, setCamFmp4, cameraUsesFmp4, cameraSupportsFmp4, camFmp4Status, camFmp4Reason, camVideo, webrtcFailed, cameraIsWebRTC, cameraStreamSrc, onCameraStreamError, onCameraStreamLoad, retryCameraNow, camGaveUp, camRetry, printingThumb, shortFilament, isLightColor, showThumbPop, hideThumbPop, namePop, showNamePop, hideNamePop, cameraPrinterId,
        openCopyPrinter, savePrinterCopy, copyBaseName, addDemoPrinter, demoCount, setDemoCount,
        discOpen, discInfo, discBusy, discDevices, discStart, discStop, discClose, discUse, discRebind, discWarnLines,
        newPrinterAddrProblem, newPrinterAddrText, printerAddrMark, printerAddrTip,   // 16.10.2026 (R-020)
        discStateText, discRowNote,
        tempChamber, ui3PpChamber,
        ui3PresetEdit, ui3PresetDraft, ui3PresetBusy, ui3PresetError, ui3PresetLimits, ui3PresetTitle,
        ui3PresetEditOpen, ui3PresetEditClose, ui3PresetAdd, ui3PresetRemove, ui3PresetReset, ui3PresetSave,
        ui3FilLowInput, ui3FilesOpen, ui3FilesToggle, ui3PickFile, openPrinterFiles, revealPart, ui3CamPending,   // Alpha 2.831: копирование принтеров 
        getStatusStyles, dotClass, getStatusIndicator, getCardTint, getStatusTextColor, getPrinterName, convertSecondsToReadable, printerIcon, modelPickerIcon, svgAssets, 
        printersEditMode, editingProjects, printerSort, setPrinterSort, sortedPrinters, visiblePrinters, spotlight, spotlightRow,
        printerSortMode, setPrinterSortMode, printerSortMenu, openPrinterSortMenu, closePrinterSortMenu, pickPrinterSortKey, printerSortKey, printerSortDir, printerSortLabel, modelHeaderBefore, modelHeaderLabel,   // сортировка принтеров: ключ и направление
        cfsTitle, cfsSlotTitle,
        enterSpotlight, exitSpotlight, enterPrintSpotlight, onPrinterCardClick, printSel, sendJobsView, sendReserved, sendActiveCount, suggestActiveCount, dismissSendJob, sendStateLabel, sendErrLabel, sendIsTerminal, msgView, clearMessages, msgKind, dismissToast, confirmBox, confirmAnswer, cellBusy, printBtnActive, printBtnLabel, launchPrintSelected, onPrintBtn, staggerOn, staggerInterval, setStaggerOn, setStaggerInterval, staggerIntervalInput, yellowDaysInput, printQueue, printSendingNow, pqSel, togglePqSel, cancelPqSelected, pqEtaLabel, liveStagingPrintingQty, livePartPrintingQty, spotlightLift, pvPartLift, viewMode, viewModes, setViewMode, viewModeHint, dashState, dashStateText, dashPct, dashEta, gridPopStyle, theme, toggleTheme, setTheme, 
        showModal, activeModalPrinterId, toasts,
        // Alpha 2.848: окно решения по материалу при запуске печати
        filDecision, filRowsLeft, filReceiveAndStart, filSkipPrinter, filForceStart, closeFilamentDecision,
        tempNozzle, tempNozzleL, tempNozzleR, nozzleById, tempBed, printFileName, printAmsSlot, cellAmsOpen, cellAmsStyle, toggleCellAms, amsGroups,
        printerAlerts, cardTopAlert, alertsForPrinter, alertBadgeCount, alertTopSeverity, alertPanelRows, alertsPanelOpen, toggleAlertsPanel, closeAlertsPanel,
        hmsFor, hmsCount, hmsTopSeverity, hmsText, hmsSevText, hmsModuleText, hmsTip, focusPrinterCard, alertTimeLabel,
        projects2, project2Trees, project2Parts, pvExpanded, project2Expanded, project2Busy, newProject2Name, showNewProject2,
        project2NameErr, project2RenameErr, p2NameMsg,   // Alpha 2.804: предупреждения об имени проекта
        project2Mode, setProject2Mode, project2EditAdv, setProject2EditAdv, p2EditOrdered, pvTogglePart, pvPlate, pvExpandAll, pvCollapseAll, sliceProject2File, pvFirstFid, p2PartThumb, p2FileThumb, pvVariantCount,
        // Alpha 2.823: «Файлы принтеров» (экспериментальный файловый менеджер)
        showReports, openReports, closeReports, repDays, repPeriods, setRepDays, repBusy, repState, repCapped, repRuns, repStats, repDuration, repDayLabel, repDayHeight, loadReports, repQualityReady, repModuleState,
        showPrinterFiles, openPrinterFiles, closePrinterFiles, pfPrinterId, pfSelectPrinter, pfStorages, pfStorageId, pfSelectStorage, pfStorage,
        pfPath, pfCrumbTo, pfOpenDir, pfEntries, pfRowsView, pfState, pfReason, pfReasonText, pfSearch, pfCat, pfAge, pfSortKey, pfSortDir, pfSetSort,
        pfSelected, pfToggleSel, pfSelectShown, pfClearSel, pfPresetOldPrograms, pfSummary, pfBusy, pfDeleteBusy, pfRefresh, pfDeleteOne, pfDeleteSelected,
        pfDeleteAllowed, pfCaps, pfCapsResp, pfFmtSize, pfFmtDate, pfCatText, pfFlags, pfFlagsBusy, pfSetFlag, pfAdapterSummary,
        cbBusy, cbExportPw, cbImportPw, cbImportName, cbImportB64, cbPlan, cbInfo, cbMsg, cbExport, cbPickImport, cbInspect, cbApply,
        cbProtect, cbExportPw2, cbImportRequiresPw, cbDone, cbPendingRestart, cbRestartLater, cbMbLabel, cbPhase, cbModLabel, cbWarnText,
        cbExclude, cbPlanBlocked, cbBlockedModules, cbExcludedModules, cbSetExclude,
        pfSelectable, pfRowClick, pfPrintTarget, pfPrintBlockReason, pfActionBusy, pfSelectForPrint, pfPrintNow,
        pfRowMenu, pfRowMenuFor, pfRowMenuClose, pfRowMenuAct, pfStatusText, pfStatusTitle, pfShowSize, pfShowDate, pfMetaNote,
        pfPreview, pfCanPreview, pfPreviewOpen, pfPreviewClose,
        loadProjects2, exportProjects2, loadProject2Tree, loadPartsView, reworkPart, reworkPos, reworkAddQty, openRework, closeRework, submitRework, clearRework, toggleProject2, p2Enter, p2Leave, createProject2, deleteProject2,
        readinessReasonText, readinessReasonsText,
        openExplorerForProject2Files, exAddFilesToProject2, saveProject2Name, deleteProject2File, deleteProject2Part, saveProject2Part, saveProject2PartField, p2FieldFocus, addProject2PartToFile, saveProject2OnPlate,
        project2PrintFor, printProject2File, printBtnState, printerFiles, loadingFiles, openModal, 
        sendCmd, confirmStop, stagingFiles, stagingSyncTip, toggleStagingSync, isDraggingStaging, handleStagingDrop, deleteStagingFile, pickingFiles, printMenuUid, compatiblePrintersFor, togglePrintMenu, printFileOn, printStart, printExtLabel, printExtNote, printerCapabilities, openPrintStart, closePrintStart, confirmPrintStart, printStartTypeLabel, klCapNote, klRep, klRepPhaseText, klRepBusy, klRepDone, klRepSummaryLines, collectKlipperReport, saveKlipperReport, copyKlipperSummary, klDiag, openKlipperDiag, closeKlipperDiag, amsPick, openAmsPick, amsPickSlot, printPickPrinter, closeAmsPick, amsSelectFor, isAmsStep, saveStaging, markStagingDirty, stagingStatusKey, stagingStatusLabel, stagingStatusTitle, fileSendState, p2PartSending, p2PartOwnKey, p2PartOwnLabel, liveStatusKey, liveStatusLabel, printersPrintingFile, printersPrintingFileName, revealStaging, isPreviewable, onThumbErr, isSliceable, addToSlicer, slicerList, slicerChoice, chooseSlicer, 
        stagingProgress, stagingProgressText, stepStagingQty, stagingProblems, stagingProblemCount, stagingPartReason, stGroup, setStGroup, stGroupClosed, toggleStGroup, stagingViewGroups, stagingFolder, stagingFolderKnown, tasksWord,
        goToUi3,
        goToUi2, uiSwitchVisible, ui3Mode, ui3Printer, ui3SelectPrinter, ui3HasCamera,
        ui3PpP, ui3PpS, ui3PpBusy, ui3PpDot, ui3PpStateText, ui3PpPct, ui3Dur, ui3PpRemainText, ui3PpFinishText, ui3PpStartText, ui3PpIdleText, ui3PpDeg, ui3PpTgt,
        ui3TempStep, ui3TempPresets, ui3TempPreset, ui3PpTrays, ui3PpNowLabel, ui3AmsOpen, ui3AmsToggle, ui3PpAmsChoices, ui3PpPrintLabel, ui3PpPrint, ui3PpPrintWith,
        ui3PpView, ui3PpCamShown, ui3PpCamOn, ui3PpSetView, ui3PpCamFull,
        ui3RightTab, setUi3RightTab, ui3RailClass, ui3NoteEditFor, ui3NoteStart, ui3NoteStop, ui3NoteCancel, ui3PartTask, ui3PartRailClass, stepPartQty, ui3PartPct,
        ui3FilRows, ui3FilTotals, ui3FilLowPct, setUi3FilLowPct,
        queueWait, queueAllowed, queueBusy, loadQueueWait, queueAdd, queueRemove,
        queueStart, queueSetAllowed, queueReasonText, queueVerdictText, queueWhyLines, queueMatSource,
        queuePlateWait, queueAwaitsClear, queueClearHere, queuePlateClear,
        queueAutoOn, queueAutoPids, queueAutoToggle, queueAutoHas, queueAutoSet,
        queueStateText,
        queuePickMode, queueIsAllowed, toggleQueuePick,
        sortKey, sortDir, setSort, sortParts, stSortKey, stSortDir, setStSort, sortStaging, stSearch, filterStaging, stagingTotals, stStatus, filterStagingView, projSort, setProjSort, sortedProjects2, projSearch, filterProjects, getProjectTint, archiveMode, selectedForArchive, toggleArchiveMode, toggleNewProject2, confirmArchive, authEnabled, authUser, authSetupAvailable, loginUser, loginPass, loginError, loginBusy, doLogin, showSecuritySetup, setupUser, setupPass, setupPass2, setupError, openSecuritySetup, doSecuritySetup, doLogout, showSecurityDisable, disablePass, disableError, openSecurityDisable, doSecurityDisable, showAdminRecovery, admRecUser, admRecPass, admRecPass2, admRecError, admRecBusy, admRecDone, doAdminRecovery, cancelAdminRecovery, finishAdminRecovery, admRecDoneMsg, roleLabel, authRoles, showUsers, usersList, usersMe, usersError, newUserName, newUserPass, newUserRole, openUsers, createUser, changeUserRole, toggleUserActive, deleteUser, devicesList, deviceBusy, revokeDevice, showAudit, auditEntries, auditTotal, auditError, auditBusy, auditLabel, openAudit, loadMoreAudit, exportAudit, can, idlePrinters,
        ctxMenu, closeContextMenu, runCtxItem, partDisplayName, onPrinterMenu, onStagingMenu, onProjectMenu, lpStart, lpMove, lpEnd, isMobile, mobileTab, updateInfo, openUpdate, updateCheckOn, setUpdateCheck, leftColH, rightColH, printerBadges, openModuleForBadge, filamentForPrinter, filamentRows, printerStockBound, openFilamentSource, onSpotWheel,
        projectRunsById, projectRunOrder, projectRunsList, projectRunsActiveCount,
        projectRunsInitialLoading, projectRunsListError, projectRunActions,
        projectRunErrors, projectRunConfirm, highlightedRunId, projectRunName, projectRunCounts,
        projectRunCanPause, projectRunCanResume, projectRunCanCancel, projectRunBusy, refreshProjectRuns,
        wpxOpenMap, wpxTechOpen, wpxRunFor, wpxOpenFor, toggleWholePrint, wpxPreflightFor, wpxStatus,
        wpxSummary, wpxProgressPct, wpxItemState, wpxItemKind, wpxMaterialLine, wpxMaterialWarn,
        wpxItemClearance, wpxPrinterName, wpxPartsLine, wpxMainCta, wpxDoMain, wpxToggleTech,
        wpxCurrentItem, wpxCurrentIndex, wpxQueueItems, wpxPartsText, wpxFileLabel, wpxSeriesPrinter,
        wpxSeriesMaterial, wpxClrState, wpxHint, wpxQueueOpen, wpxToggleQueue, wpxMatMenu, wpxToggleMatMenu,
        printEnabled, printEnableBusy, setPrintEnabled, canStartInApp, inAppConfirm, requestInAppStart,
        closeInAppStartConfirm, confirmInAppStart, inAppStartFacts,
        pauseProjectRun, resumeProjectRun, requestCancelProjectRun,
        closeCancelProjectRunConfirm, confirmCancelProjectRun,
        projectRunClearanceTargets, projectRunPlateClearIds, printerAwaitsPlateClear, focusPlateClearRun,
        ppPlateClearKind, ppPlateClear,
        clearanceCanConfirm, clearanceCanRevoke, clearanceBlockReason, clearanceStateText,
        projectRunAmbiguousItems, requestPlateClear, revokePlateClear, requestResolveItem,
        projectRunConfirmTitle, projectRunConfirmText, projectRunConfirmOk,
        // UI-фаза 5A3b «Источник материала». Имена БЕЗ ведущего «_»: helper с «_» из setup шаблону
        // не виден (ReferenceError в рантайме), поэтому всё template-facing — только так.
        feedWin, feedConfirm, feedCandidates, feedSummary, feedKey, feedItemActive, feedItemBusy,
        feedItemNotice, feedItemError, feedBlockState, feedSlotLabel, feedSwatch, feedSwatchOk,
        feedHexText, feedDeltaText, feedRelText, feedVerifyText, feedReasonText, feedPlanReasons,
        feedStatusInfo, feedStatusLabel, feedStatusClass, feedSummaryLabel,
        openFeedWindow, closeFeedWindow, refreshFeedCandidates, feedCanSelect, feedCanApprove,
        selectFeedCandidate, requestFeedApprove, requestFeedClear, closeFeedConfirm,
        toggleFeedReason, confirmFeedApprove, confirmFeedClear, feedConfirmReasons,
        feedConfirmUnknown, feedApproveReady,
        // UI-фаза 5B2a «Контрольный запуск одной печати» (имена БЕЗ ведущего «_» — иначе шаблон их не видит)
        armStatus, armScope, armReady, startConfirm, START_CHECKS, startCheckText, startKey,
        startItemBusy, startItemNotice, startItemUnknown, canControlledStart, startApproveReady,
        startVersions, startVersionBlocked,
        toggleStartCheck, requestControlledStart, closeStartConfirm, confirmControlledStart,
        loadArmStatus,
        showProjectWholePreflight, projectWholeProject, projectWholePreflight, projectWholeLoading, projectWholeError,
        projectWholeSaveError, projectWholeSaving, projectWholeAllowOverproduction, projectWholeSavedRun,
        projectWholeNotice, projectWholePlan, projectWholeParts, projectWholeCompleted, projectWholeNeedsApproval,
        projectWholeOverRows, projectWholePartName, projectWholeCanSave, openProjectWholePreflight,
        closeProjectWholePreflight, refreshProjectWholePreflight, saveProjectWholeDraft, showSettings, workspaceView, settingsPos, settingsMaxH, openSettings, closeSettings, setWinStyle, setDragStart, setResizeStart, setWinReset, setBackdropClose, setScrollEl, onSetScroll, settingsTab, curSetTab, setTabPrintShown, storageInfo, archiveDirInput, storageBusy, loadStorageInfo, applyArchiveDir, resetArchiveDir, applyDataDir, resetDataDir, dataDirPending, dataDirUnavailable, dduTitle, dduText, dduRestartText, dduBusy, dduMsg, dduRetry, dduPickElsewhere, dduStartNew, exportBrowserSettings, importBrowserSettings, browserSettingsMsg, openStorageFolder, showRestartModal, restartPendingPath, restartInProgress, doRestart, dismissRestart,
        netPort, netPendingPort, showPortDialog, portInput, portBusy, portError, portCanChange, openPortDialog, closePortDialog, applyPort,
        restartPhase, restartMessage, restartReasonCode, retryRestartConnection, dismissRestartState, lanAccess, lanApplied, lanRestartRequired, lanBusy, setLanAccess, loadNetworkInfo, lanCanEnable, lanBlockedReason, lanAuthEnabled, lanAdminPresent, lanHint, lanChangeAllowed, lanBlockedText, lanError, lanUrl,showAbout, appVersion, openAbout, closeAbout, showChangelog, changelog, openChangelog, closeChangelog, appModules, runModule, installedModules, moduleInstalling, moduleInstallMsg, pickModuleZip, exInstallModule, licInfo, licBusy, licMsg, licLine, licModuleText, importLicense, removeLicense, downloadActivationRequest, licKey, licConsent, addLicenseKey, licSentText, licSentNote, activeModuleComp, moduleHasUi, runInstalledModule, openModuleFromCard, moduleBusy, closeActiveModule, deleteModule, disabledModules, disableModule, enableModule, moduleRestartNeeded, moduleLaunchers,
        modulesLoadState, problemModules, moduleStateText, moduleStateTitle, moduleVersionHint, loadInstalledModules, activeModuleProps, moduleAccess,
        barModules, barCandidates, barModuleShown, barModuleToggle, barModulesBusy, barLocalOnly, modulesWithSettings, runModuleById, showCreatedDate, yellowDays, setShowCreatedDate, setYellowDays, showSuggestions, setShowSuggestions, suggestCollapsed, toggleSuggestCollapsed, appEdition, setEdition, edHas, setProjectDue, clearProjectDue,
        tourEnabled, tourActive, tourStep, tourBox, tourCardStyle, tourSteps, tourMode, tourModeTitle, hasSavedTourProgress, tourSavedProgressLabel, resumeTour, resetTourProgress, showTourStartDialog, tourStartNoShow, tourStartupPromptEnabled, tourStartupStatusLabel, tourStartSections, openTourStartDialog, closeTourStartDialog, dismissTourStartDialog, setTourStartupPrompt, startTourFromDialog, resumeTourFromDialog, currentTourStep, tourProjectDemoOpen, currentTourPrimaryText, currentTourHasMore, tourMoreOpen, toggleTourMore, refreshTourLayout, currentTourGroupLabel, currentTourGroupProgress, tourCanSkipGroup, startTour, tourNext, tourPrev, tourGoTo, tourSkipGroup, endTour, tourFakeEx, tourFakeStep, tourMarks, tourConnector, tourCtxDemo, tourHintBoxes, sceneCursorPx, sceneCursorShow, sceneClick, sceneFmOpen, sceneFileSel, sceneActionPress, sceneActionLabel, sceneAmsOpen, sceneAmsSel, sceneDiagOpen, sceneDiagSel, sceneDiagScroll, sceneSliceToast,
        showDiag, diagEntries, diagFilter, diagFilters, diagVerbose, diagAutoscroll, diagFiltered, diagLevelClass, diagTime, openDiagnostics, diagWheel, closeDiagnostics, toggleDiagVerbose, clearDiag, downloadLogs, diagWinStyle, diagDragStart, diagResizeStart,
        diagSearch, diagPaused, diagLostConnection, diagStateText, toggleDiagPause, copyDiag, exportDiag,
        diagTab, connDiag, connExpanded, connDetail, connDiagLoading, refreshConnDiag, setDiagTab, toggleConnRow, cdiagNet, cdiagIssues, netMonitor, toggleNetMonitor, speedTest, runSpeedTest, sparkPoints, sparkRange,
        dpqRows, dpqLoading, dpqError, refreshDurableQueue, dpqStatusLabel, dpqDotClass, dpqTime,
        dpqCanceling, dpqActionErr, dpqPendingInBatch, cancelDurableRow, cancelDurableBatch,
        sniffPrinterId, sniffState, sniffBusy, sniffCopied, bambuPrinters, startSniff, stopSniff, sniffStatusLabel, sniffFmt, sniffTime, copySniff,
        recoveryNotice, recoveryBusy, recoveryContinue, recoveryCancel, recoveryOpenQueue
    };
}
});
// БЛОК: финальная страховка Vue и монтирование приложения в #app.
// Перехватчик ошибок Vue: исключение в render / lifecycle / обработчике события компонента
// идёт СЮДА, а не «вверх» по дереву, поэтому один сбойный виджет не роняет всё приложение.
// Логируем в панель и продолжаем работу (обработчик не пробрасывает исключение дальше).
__app.config.errorHandler = (err, instance, info) => {
    console.error('[Vue]', err, info);
    reportClientError('error', (err && err.message ? err.message : String(err)) + (info ? ' (' + info + ')' : ''), 'Vue');
};
// Глобальная регистрация компонентов (доступны в шаблоне #app по kebab-имени, напр. <status-badge>).
__app.component('StatusBadge', StatusBadge);
__app.component('Toast', Toast);
__app.component('ProjectCell', ProjectCell);
__app.component('DueChip', DueChip);
__app.component('ViewModeSwitch', ViewModeSwitch);
__app.component('ContextMenu', ContextMenu);
__app.component('DiagRow', DiagRow);
__app.component('SvgIcon', SvgIcon);
// Alpha 2.674: общий backdrop-close. Затемнение закрывает окно ТОЛЬКО если pointerdown И pointerup оба
// пришлись на сам backdrop (el). Если нажатие началось внутри окна/поля (drag-выделение текста с выходом
// курсора наружу) — отпускание на затемнении НЕ закрывает окно. Обычный клик по backdrop (down+up на нём)
// закрывает как прежде. Значение директивы — функция закрытия. Заменяет уязвимый @click.self на бэкдропах.
__app.directive('backdrop-close', {
    mounted(el, binding) {
        el.__bdValue = binding.value;
        el.__bdDown = (e) => { el.__bdOnSelf = (e.target === el); };
        el.__bdUp = (e) => { const ok = el.__bdOnSelf && e.target === el; el.__bdOnSelf = false; if (ok && typeof el.__bdValue === 'function') el.__bdValue(e); };
        el.__bdCancel = () => { el.__bdOnSelf = false; };
        el.addEventListener('pointerdown', el.__bdDown);
        el.addEventListener('pointerup', el.__bdUp);
        el.addEventListener('pointercancel', el.__bdCancel);
    },
    updated(el, binding) { el.__bdValue = binding.value; },
    unmounted(el) {
        el.removeEventListener('pointerdown', el.__bdDown);
        el.removeEventListener('pointerup', el.__bdUp);
        el.removeEventListener('pointercancel', el.__bdCancel);
    },
});
// === Alpha 2.815: ЕДИНЫЙ СТЕК МОДАЛЬНЫХ ОКОН ==============================================
// Один список слоёв на всё приложение: [{id, level, el, close, restore}], верхний слой — последний.
// До 2.815 каждый диалог сам выбирал себе z-index, поэтому «Порт сервера» (100051) оказывался
// НИЖЕ окна настроек (100060) и его затемнение не забирало клики. Теперь слой берётся из шкалы
// --fm-z-* в app.css, а поведение (фокус, ловушка Tab, возврат фокуса, блокировка фона) — отсюда.
// Директива вешается на САМО окно диалога, а не на затемнение.
const fmModalStack = [];
const fmModalTop = () => (fmModalStack.length ? fmModalStack[fmModalStack.length - 1] : null);
// Верхний ВЛОЖЕННЫЙ слой (level >= 2). Escape-цепочка в setup() спрашивает именно его: окна
// 1-го уровня по-прежнему закрывает отлаженный жёсткий порядок, вложенные — этот стек.
const fmModalTopNested = () => {
    for (let i = fmModalStack.length - 1; i >= 0; i--) if (fmModalStack[i].level >= 2) return fmModalStack[i];
    return null;
};
// Закрыть все вложенные слои (сверху вниз) — например, когда закрывается родительское окно:
// «не оставлять backdrop без окна» и не оставлять диалог без родителя.
const fmCloseNested = () => {
    for (let i = fmModalStack.length - 1; i >= 0; i--) {
        const s = fmModalStack[i];
        if (s.level >= 2 && typeof s.close === 'function') { try { s.close(); } catch (e) {} }
    }
};
const FM_FOCUSABLE = 'a[href],area[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),button:not([disabled]),iframe,[tabindex]:not([tabindex="-1"]),[contenteditable="true"]';
const fmFocusable = (el) => {
    try { return Array.from(el.querySelectorAll(FM_FOCUSABLE)).filter((n) => n.offsetParent !== null || n === document.activeElement); }
    catch (e) { return []; }
};
// Блокировка прокрутки фона. Значения совпадают с отлаженным наблюдателем showSettings
// (body.style.overflow hidden/auto), поэтому два механизма никогда не расходятся.
const fmModalLock = () => {
    try {
        const on = fmModalStack.length > 0;
        document.body.classList.toggle('fm-modal-open', on);
        document.body.style.overflow = on ? 'hidden' : 'auto';
    } catch (e) {}
};
// Ловушка Tab: фокус не уходит из ВЕРХНЕГО слоя. Слои ниже свой Tab не перехватывают.
const fmTrapTab = (entry, e) => {
    if (fmModalTop() !== entry) return;
    const items = fmFocusable(entry.el);
    if (!items.length) { e.preventDefault(); return; }
    const first = items[0], last = items[items.length - 1], cur = document.activeElement;
    if (e.shiftKey) {
        if (cur === first || !entry.el.contains(cur)) { e.preventDefault(); last.focus(); }
    } else if (cur === last || !entry.el.contains(cur)) { e.preventDefault(); first.focus(); }
};
__app.directive('modal-layer', {
    mounted(el, binding) {
        const cfg = (binding && binding.value && typeof binding.value === 'object') ? binding.value : {};
        const entry = {
            id: String(cfg.id || ''),
            level: Number(cfg.level) || 2,
            el,
            close: (typeof cfg.close === 'function') ? cfg.close : null,
            // Куда вернуть фокус после закрытия — кнопка, из которой диалог открыли. Элемент
            // внутри самого окна точкой возврата быть не может, иначе фокус вернётся в никуда.
            restore: (document.activeElement && document.activeElement !== document.body
                      && !el.contains(document.activeElement)) ? document.activeElement : null,
        };
        // Повторное открытие того же окна НЕ создаёт второй слой (двойной клик = один диалог)
        // и НЕ теряет исходную точку возврата фокуса.
        const dup = fmModalStack.findIndex((s) => s.id === entry.id);
        if (dup >= 0) { entry.restore = fmModalStack[dup].restore || entry.restore; fmModalStack.splice(dup, 1); }
        fmModalStack.push(entry);
        el.__fmLayer = entry;
        el.__fmKey = (e) => { if (e.key === 'Tab') fmTrapTab(entry, e); };
        el.addEventListener('keydown', el.__fmKey);
        fmModalLock();
        if (cfg.autofocus !== false) {
            setTimeout(() => {
                if (fmModalTop() !== entry) return;
                const items = fmFocusable(el);
                try { (items[0] || el).focus(); } catch (e) {}
            }, 0);
        }
    },
    updated(el, binding) {
        const cfg = (binding && binding.value && typeof binding.value === 'object') ? binding.value : {};
        if (el.__fmLayer && typeof cfg.close === 'function') el.__fmLayer.close = cfg.close;
    },
    unmounted(el) {
        const entry = el.__fmLayer;
        if (el.__fmKey) el.removeEventListener('keydown', el.__fmKey);
        const i = fmModalStack.indexOf(entry);
        if (i >= 0) fmModalStack.splice(i, 1);
        el.__fmLayer = null;
        fmModalLock();
        // Возврат фокуса на элемент, из которого окно открыли (кнопка «Изменить порт»).
        if (entry && entry.restore && document.contains(entry.restore)) { try { entry.restore.focus(); } catch (e) {} }
    },
});
__app.mount('#app');
