// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { DASHBOARD_FIELDS } from './dashboard-settings.js';
import { PROFILE_PATHS } from './theme-profiles.js';
import { FONT_OPTIONS, PALETTE_FIELDS } from './theme-schema.js';

const field = (path, label, en, help, helpEn, kind = 'range', extra = {}) => ({ path, label, en, help, helpEn, kind, min: 0, max: 1, step: .01, ...extra });
const option = (value, ru, en) => ({ value, ru, en });
const select = (path, ru, en, help, helpEn, options, extra = {}) => field(path, ru, en, help, helpEn, 'select', { options: options.map(x => option(...x)), ...extra });
const toggle = (path, ru, en, help, helpEn, extra = {}) => field(path, ru, en, help, helpEn, 'toggle', extra);
const range = field;
const on = t => t.effects.animatedBackground !== 'off';
const streams = t => on(t) && ['streams','mixed'].includes(t.effects.backgroundAnimationStyle);
const mixed = t => on(t) && t.effects.backgroundAnimationStyle === 'mixed';
const glow = t => t.effects.edgeLighting !== 'off';
const glint = t => t.effects.hoverGlintPrinters || t.effects.hoverGlintProjects;
export const SECTIONS = [
  { id: 'quick', ru: 'Быстрая настройка', en: 'Quick setup', help: 'Начните с готового варианта и настройте главное.', helpEn: 'Choose a starting point and adjust the essentials.' },
  { id: 'colors', ru: 'Цвета', en: 'Colors', help: 'Цвета интерфейса и текста. Палитры настраиваются отдельно.', helpEn: 'Interface and text colors. Edit each palette separately.' },
  { id: 'text', ru: 'Текст и размеры', en: 'Text and size', help: 'Сделайте интерфейс удобным для чтения.', helpEn: 'Make the interface comfortable to read.' },
  { id: 'panels', ru: 'Панели и карточки', en: 'Panels and cards', help: 'Форма, границы, тени и оформление элементов.', helpEn: 'Shape, borders, shadows and control styles.' },
  { id: 'background', ru: 'Фон и анимации', en: 'Background and motion', help: 'Фон приложения и движение декоративных эффектов.', helpEn: 'App background and decorative motion.' },
  { id: 'themes', ru: 'Мои темы', en: 'My themes', help: 'Храните свои варианты и переносите их между браузерами.', helpEn: 'Keep your own variations and transfer them between browsers.' }
];
const paletteHelp = {
  accent: ['Кнопки, выделения и прогресс. Цвета статусов задаются отдельно.', 'Buttons, selection and progress. Status colors are separate.'],
  surfaceDeep: ['Самый нижний фон приложения.', 'The background behind the interface.'],
  surfaceBase: ['Основные области и панели приложения.', 'Main app areas and panels.'],
  surfaceRaised: ['Дополнительные панели и приподнятые поверхности.', 'Secondary panels and raised surfaces.'],
  surfaceCard: ['Фон карточек принтеров и проектов.', 'Printer and project card backgrounds.'],
  surfaceControl: ['Фон полей ввода и элементов управления.', 'Input and control backgrounds.'],
  textPrimary: ['Основные надписи и заголовки.', 'Main labels and headings.'],
  textSecondary: ['Дополнительные сведения на карточках.', 'Secondary information on cards.'],
  textMuted: ['Менее заметные пояснения.', 'Less prominent descriptions.'],
  textSubtle: ['Служебные подписи и вспомогательная информация.', 'Supporting labels and metadata.'],
  borderSoft: ['Ненавязчивые разделители и рамки.', 'Subtle separators and borders.'],
  border: ['Обычные рамки элементов.', 'Standard element borders.'],
  borderStrong: ['Более заметные рамки.', 'More prominent borders.'],
  success: ['Обозначения успешного выполнения.', 'Successful completion indicators.'],
  warning: ['Обозначения предупреждений.', 'Warning indicators.'],
  danger: ['Обозначения ошибок.', 'Error indicators.'],
  headerSurface: ['Фон верхней панели FM.', 'The Farm Manager header background.'],
  headerAction: ['Фон кнопок в верхней панели FM.', 'Header button backgrounds.'],
  headerBorder: ['Рамки верхней панели FM.', 'Header borders.']
};
export const FIELDS = [
  ...DASHBOARD_FIELDS,
  ...PALETTE_FIELDS.map(([key, ru, en]) => field(`palette.${key}`, key === 'accent' ? 'Основной цвет интерфейса' : ru, key === 'accent' ? 'Interface accent' : en, ...paletteHelp[key], 'color', { section: 'colors', advanced: !['accent', 'surfaceDeep', 'surfaceCard', 'textPrimary'].includes(key), target: key.startsWith('header') ? 'header' : 'card' })),
  field('effects.secondaryAccent', 'Дополнительный цвет эффектов', 'Secondary effect color', 'Второй оттенок свечения и связанных цветов фона.', 'Second color for glow and linked backgrounds.', 'color', { section: 'colors', advanced: true }),
  select('typography.font', 'Шрифт', 'Font', 'Шрифт интерфейса. Можно загрузить собственный ниже.', 'Interface font. You can upload a font below.', FONT_OPTIONS.map(f => [f.id, f.ru, f.en]), { section: 'text', target: 'text' }),
  range('typography.textScale', 'Размер текста', 'Text size', '100% — обычный размер. Увеличьте, если надписи мелкие.', '100% is the standard size. Increase for easier reading.', 'range', { section: 'text', min: .85, max: 1.6, target: 'text', ends: ['Мельче', 'Крупнее', 'Smaller', 'Larger'] }),
  select('interface.density', 'Расстояние между элементами', 'Element spacing', 'Действует на совместимые элементы FM и модулей.', 'Applies to compatible FM and module elements.', [['compact','Компактное','Compact'],['normal','Обычное','Normal'],['comfortable','Увеличенное','Comfortable']], { section: 'text', target: 'card' }),
  toggle('interface.highContrast', 'Повысить контрастность границ', 'Higher border contrast', 'Делает границы элементов заметнее.', 'Makes element borders more visible.', { section: 'text' }),
  select('effects.cornerStyle', 'Форма карточек', 'Card shape', 'Общий характер углов карточек.', 'The overall shape of card corners.', [['rounded','Скруглённая','Rounded'],['tech','Асимметричная','Asymmetric'],['squared','Почти прямоугольная','Nearly square']], { section: 'panels', target: 'card' }),
  range('shape.radiusScale', 'Скругление углов', 'Corner rounding', 'Настраивается для обычной скруглённой формы.', 'Adjustable for the standard rounded shape.', 'range', { section: 'panels', min: .5, max: 1.8, step: .05, enabled: t => t.effects.cornerStyle === 'rounded', reason: ['Выберите скруглённую форму карточек.', 'Select the rounded card shape.'], target: 'card' }),
  select('effects.panelMaterial', 'Поверхность панелей', 'Panel surface', 'Определяет заливку и декоративные засветки панелей.', 'Controls panel fill and decorative highlights.', [['solid','Обычная','Plain'],['soft-glass','Полупрозрачная','Translucent'],['deep-glass','Полупрозрачная с засветками','Translucent with highlights'],['hud','С акцентными границами','Accented borders'],['optical-glass','Оптическое стекло','Optical glass']], { section: 'panels', target: 'card' }),
  select('effects.edgeLighting', 'Подсветка карточек', 'Card edge glow', 'Постоянное свечение. Блик при наведении настраивается в анимациях.', 'Static glow. Hover glint is configured under motion.', [['off','Выключена','Off'],['active','Активные карточки','Active cards'],['all','Все карточки','All cards']], { section: 'panels', target: 'card' }),
  range('shape.borderWidth', 'Толщина границ', 'Border width', 'Толщина рамок совместимых элементов.', 'Border thickness on supported elements.', 'range', { section: 'panels', min: 1, max: 2, step: .25, unit: 'px', advanced: true, target: 'card' }),
  range('shape.surfaceOpacity', 'Непрозрачность заливки', 'Fill opacity', '100% — плотная заливка. Меньше — фон сильнее просвечивает. Материал панели тоже влияет на результат.', '100% is opaque. Lower values reveal more background. Panel material also affects the result.', 'range', { section: 'panels', min: .72, max: 1, advanced: true }),
  range('shape.shadowIntensity', 'Обычные тени', 'Standard shadows', 'Базовая внешняя тень. Складывается с внутренней тенью, мягкой тенью и подсветкой.', 'Base shadows. Decorative shadows may replace them on some elements.', 'range', { section: 'panels', max: 1.5, step: .05, advanced: true }),
  range('effects.panelDepth', 'Внутренняя тень панелей', 'Panel inner shadow', 'Добавляет объём внутренней тенью. Складывается с мягкой внешней тенью и подсветкой.', 'Adds depth through inner shadows. Soft outer shadows and edge glow can replace it.', 'range', { section: 'panels', advanced: true }),
  range('effects.panelAiriness', 'Мягкая тень под панелями', 'Soft panel shadow', 'Внешняя рассеянная тень. Складывается с внутренней тенью и подсветкой.', 'Diffuse outer shadow. When enabled, it replaces the depth shadow.', 'range', { section: 'panels', advanced: true }),
  range('effects.glowStrength', 'Яркость подсветки границ', 'Edge glow intensity', 'Насколько заметен свет возле рамки.', 'How prominent the light around borders is.', 'range', { section: 'panels', advanced: true, enabled: glow, reason: ['Включите подсветку карточек.', 'Enable card edge glow.'] }),
  range('effects.haloStrength', 'Свечение вокруг карточек', 'Diffuse card glow', 'Мягкий ореол дополнительного цвета.', 'A soft halo using the secondary effect color.', 'range', { section: 'panels', advanced: true, enabled: glow, reason: ['Включите подсветку карточек.', 'Enable card edge glow.'] }),
  select('effects.edgeDirection', 'Расположение подсветки', 'Glow placement', 'По каким сторонам карточки виден свет.', 'Which sides of the card receive glow.', [['full','По всему контуру','Full outline'],['lower','Снизу','Bottom'],['lower-left','Слева и снизу','Left and bottom']], { section: 'panels', advanced: true, enabled: glow, reason: ['Включите подсветку карточек.', 'Enable card edge glow.'] }),
  range('effects.matteStrength', 'Матовость поверхности', 'Surface matte', 'Меняет заливку полупрозрачных материалов.', 'Changes translucent material fills.', 'range', { section: 'panels', advanced: true, enabled: t => ['soft-glass','deep-glass'].includes(t.effects.panelMaterial) || t.effects.controlStyle === 'glass', reason: ['Выберите полупрозрачные панели или кнопки.', 'Choose translucent panels or controls.'] }),
  range('effects.glossStrength', 'Глянцевые засветки', 'Gloss highlights', 'Светлые участки поверхности. Это отдельный эффект от движущегося блика контура.', 'Bright surface highlights, separate from the moving outline glint.', 'range', { section: 'panels', advanced: true }),
  toggle('effects.panelTopHighlight', 'Светлая верхняя кромка', 'Light top edge', 'Добавляет декоративную засветку сверху панели.', 'Adds a decorative highlight at the top.', { section: 'panels', advanced: true }),
  toggle('effects.hoverLift', 'Тень карточки при наведении', 'Card shadow on hover', 'При наведении меняется тень; сама карточка не перемещается.', 'Changes the shadow on hover without moving the card.', { section: 'panels', advanced: true }),
  select('effects.tableStyle', 'Оформление таблиц', 'Table style', 'Фон заголовков и выделение строк.', 'Table header backgrounds and row highlights.', [['clean','Обычное','Plain'],['soft-neon','Мягкая подсветка','Soft glow'],['hud','Акцентные разделители','Accented separators']], { section: 'panels', advanced: true, target: 'table' }),
  select('effects.statusStyle', 'Оформление статусов', 'Status appearance', 'Вид меток состояния принтеров.', 'Printer status label style.', [['text-dot','Текст и точка','Text and dot'],['chip','Метка в рамке','Outlined badge'],['underline','Подчёркивание','Underline']], { section: 'panels', advanced: true, target: 'status' }),
  select('effects.progressStyle', 'Полосы прогресса', 'Progress bars', 'Оформление заполненной части полосы.', 'Appearance of the filled part of progress bars.', [['flat','Обычные','Plain'],['glow','С мягким свечением','Soft glow'],['dual','С переходом двух цветов','Two-color gradient']], { section: 'panels', advanced: true, target: 'progress' }),
  select('effects.controlStyle', 'Кнопки и поля', 'Buttons and inputs', 'Оформление элементов управления.', 'Control appearance.', [['clean','Обычные','Plain'],['glass','Полупрозрачные','Translucent'],['command','С акцентной рамкой','Accented border']], { section: 'panels', advanced: true, target: 'controls' }),
  range('effects.focusGlowStrength', 'Подсветка выбранного поля', 'Focused input glow', 'Помогает увидеть поле, в котором находится курсор.', 'Highlights the input currently receiving keyboard input.', 'range', { section: 'panels', advanced: true, target: 'controls' }),
  range('effects.microAccentIntensity', 'Мелкие цветовые акценты', 'Small color accents', 'Интенсивность тонких декоративных цветовых деталей.', 'Strength of subtle decorative color details.', 'range', { section: 'panels', advanced: true }),
  select('background.mode', 'Основа фона', 'Background base', 'Живой фон можно добавить поверх выбранной основы.', 'You can add an animated background over this base.', [['solid','Цвет темы','Theme color'],['image','Изображение','Image']], { section: 'background', group: 'base' }),
  field('background.overlay', 'Цвет затемнения изображения', 'Image overlay color', 'Оттенок слоя поверх изображения.', 'Tint of the image overlay.', 'color', { section: 'background', group: 'base', enabled: t => t.background.mode === 'image', reason: ['Выберите изображение в основе фона.', 'Choose an image background.'] }),
  range('background.overlayOpacity', 'Затемнение изображения', 'Image dimming', 'Помогает сохранить читаемость поверх фотографии.', 'Helps keep the interface readable over an image.', 'range', { section: 'background', group: 'base', max: .85, enabled: t => t.background.mode === 'image', reason: ['Выберите изображение в основе фона.', 'Choose an image background.'] }),
  range('background.blurPx', 'Размытие изображения', 'Image blur', 'Смягчает детали фонового изображения.', 'Softens background image details.', 'range', { section: 'background', group: 'base', max: 20, step: 1, unit: 'px', enabled: t => t.background.mode === 'image', reason: ['Выберите изображение в основе фона.', 'Choose an image background.'] }),
  toggle('live', 'Живой фон', 'Animated background', 'Включает движение цветовых переливов или световых потоков.', 'Enables animated color flow or light streams.', { section: 'background', group: 'live', target: 'background' }),
  range('effects.backgroundFlowOpacity', 'Яркость живого фона', 'Animated background brightness', 'Насколько заметны эффекты за интерфейсом.', 'How visible the effects are behind the interface.', 'range', { section: 'background', group: 'live', enabled: on, reason: ['Включите живой фон.', 'Enable the animated background.'], target: 'background', max: .34, format: 'brightness' }),
  range('effects.backgroundFlowSpeed', 'Скорость движения', 'Motion speed', 'Слева — спокойное движение, справа — более быстрое.', 'Left is calm; right is faster.', 'range', { section: 'background', group: 'live', enabled: on, reason: ['Включите живой фон.', 'Enable the animated background.'], format: 'speed', target: 'background' }),
  toggle('effects.backgroundFlowUseThemeColors', 'Использовать цвета темы', 'Use theme colors', 'Выключите, чтобы менять фон независимо от кнопок и выделений.', 'Turn off to adjust background colors independently of controls.', { section: 'background', group: 'live', enabled: on, reason: ['Включите живой фон.', 'Enable the animated background.'] }),
  field('effects.backgroundFlowPrimary', 'Первый цвет фона', 'First background color', 'Основной оттенок живого фона.', 'Primary animated background color.', 'color', { section: 'background', group: 'live', enabled: t => on(t) && !t.effects.backgroundFlowUseThemeColors, reason: ['Используются цвета темы. Выключите связь для своего оттенка.', 'Using theme colors. Turn off the link to choose a custom color.'], linked: true }),
  field('effects.backgroundFlowSecondary', 'Второй цвет фона', 'Second background color', 'Дополнительный оттенок живого фона.', 'Secondary animated background color.', 'color', { section: 'background', group: 'live', enabled: t => on(t) && !t.effects.backgroundFlowUseThemeColors, reason: ['Используются цвета темы. Выключите связь для своего оттенка.', 'Using theme colors. Turn off the link to choose a custom color.'], linked: true }),
  range('effects.backgroundFlowScale', 'Размер потоков и переливов', 'Stream and flow size', 'Меняет размер световых форм.', 'Changes the size of light shapes.', 'range', { section: 'background', group: 'live', advanced: true, enabled: on, reason: ['Включите живой фон.', 'Enable the animated background.'] }),
  range('effects.backgroundFlowBlur', 'Размытие живого фона', 'Animated background softness', 'Смягчает световые формы; у потоков меняет также ширину ореола.', 'Softens light shapes and widens stream halos.', 'range', { section: 'background', group: 'live', advanced: true, enabled: on, reason: ['Включите живой фон.', 'Enable the animated background.'] }),
  range('effects.backgroundStreamCount', 'Количество дополнительных потоков', 'Additional stream count', 'Плюс два длинных потока, которые удерживают фон в кадре. Видимое количество меняется во времени.', 'Plus two persistent long streams. The number visible varies over time.', 'range', { section: 'background', group: 'live', advanced: true, min: 2, max: 20, step: 1, unit: 'count', enabled: streams, reason: ['Выберите потоки или смешанный фон.', 'Choose streams or a mixed background.'] }),
  select('effects.backgroundMixedStyle', 'Основной эффект смешанного фона', 'Mixed background base', 'Выбранный эффект работает вместе со световыми потоками. Яркость слоёв регулируется отдельно.', 'The selected effect plays together with light streams. Adjust each contribution separately.', [['flow','Классические переливы','Classic flow'],['fluid','Плавные переливы','Fluid flow'],['aurora','Северное сияние','Aurora'],['mist','Цветной туман','Colored mist']], {section:'background',group:'live',enabled:mixed,reason:['Выберите смешанный фон.','Choose the mixed background.']}),
  range('effects.backgroundFlowMix', 'Основной эффект в смешанном фоне', 'Base effect contribution', 'Уменьшает яркость выбранного основного эффекта.', 'Reduces the selected base effect brightness.', 'range', { section: 'background', group: 'live', advanced: true, enabled: mixed, reason: ['Выберите смешанный фон.', 'Choose the mixed background.'] }),
  range('effects.backgroundStreamsMix', 'Потоки в смешанном фоне', 'Stream contribution', 'Уменьшает вклад световых потоков.', 'Reduces the light stream contribution.', 'range', { section: 'background', group: 'live', advanced: true, enabled: mixed, reason: ['Выберите смешанный фон.', 'Choose the mixed background.'] }),
  select('effects.backgroundPattern', 'Статичный узор', 'Static pattern', 'Необязательный узор поверх основы фона.', 'Optional pattern over the background base.', [['none','Без узора','None'],['grid','Тонкая сетка','Fine grid'],['micro-lines','Тонкие линии','Fine lines']], { section: 'background', group: 'base', advanced: true }),
  range('effects.patternOpacity', 'Яркость узора', 'Pattern brightness', 'Насколько заметны линии узора.', 'How visible the pattern lines are.', 'range', { section: 'background', group: 'base', max: .18, step: .005, advanced: true, enabled: t => t.effects.backgroundPattern !== 'none', reason: ['Выберите статичный узор.', 'Choose a static pattern.'] }),
  range('effects.ambientStrength', 'Дополнительный свет переливов', 'Extra ambient flow light', 'Мягкая цветовая подсветка в варианте с переливами.', 'Soft ambient color in the color flow background.', 'range', { section: 'background', group: 'live', max: .6, advanced: true, enabled: t => on(t) && (t.effects.backgroundAnimationStyle === 'flow' || t.effects.backgroundAnimationStyle === 'mixed' && t.effects.backgroundMixedStyle === 'flow'), reason: ['Выберите классические переливы отдельно или как основу смешанного фона.', 'Choose classic flow on its own or as the mixed background base.'] }),
  toggle('effects.hoverGlintPrinters', 'Блик на карточках принтеров', 'Printer outline glint', 'При наведении свет проходит по контуру и осветляет его текущий цвет.', 'On hover, light moves around the outline and lightens its current color.', { section: 'background', group: 'glint', target: 'card' }),
  toggle('effects.hoverGlintProjects', 'Блик на карточках проектов', 'Project outline glint', 'Тот же эффект на карточках проектов.', 'The same effect on project cards.', { section: 'background', group: 'glint', target: 'project' }),
  range('effects.hoverGlintIntensity', 'Яркость блика контура', 'Outline glint brightness', 'Сила осветления рамки без изменения её исходного цвета.', 'Outline lightening strength without replacing its color.', 'range', { section: 'background', group: 'glint', enabled: glint, reason: ['Включите блик хотя бы для одного типа карточек.', 'Enable glint for at least one card type.'] }),
  range('effects.hoverGlintDuration', 'Время обхода контура', 'Time around the outline', 'Больше секунд — медленнее движение блика.', 'More seconds means slower motion.', 'range', { section: 'background', group: 'glint', min: 2, max: 15, step: .1, unit: 's', enabled: glint, reason: ['Включите блик хотя бы для одного типа карточек.', 'Enable glint for at least one card type.'] }),
  toggle('effects.shimmerProgress', 'Перелив на полосе прогресса', 'Progress bar shimmer', 'Отдельная анимация внутри заполненной полосы прогресса.', 'A separate animation inside filled progress bars.', { section: 'background', group: 'glint', advanced: true, target: 'progress' }),
  toggle('interface.reduceMotion', 'Уменьшить движение', 'Reduce motion', 'Останавливает декоративное движение. Переливы остаются статичными, потоки и блики скрываются.', 'Stops decorative motion. Color flow stays static; streams and glints are hidden.', { section: 'background', group: 'motion' }),
  select('interface.performanceMode', 'Нагрузка от оформления', 'Appearance workload', 'Экономный режим ограничивает потоки шестью и снижает детализацию и частоту обновления новых фонов.', 'Economy mode limits extra streams to six and lowers the resolution and frame rate of the new backgrounds.', [['balanced','Обычная','Normal'],['economy','Экономная','Economy']], { section: 'background', group: 'motion' })
];
FIELDS.push(
 toggle('typography.customMetrics','Настроить толщину и интервалы','Customize weight and spacing','Выключено — сохраняется штатная типографика FM.','Off preserves native FM typography.',{section:'text',advanced:true}),
 ...[['body','Основной текст','Body text'],['heading','Заголовки','Headings'],['caption','Подписи','Captions']].flatMap(([key,ru,en])=>[
  range('typography.'+key+'Weight',ru+' · толщина',en+' · weight','300 — тонкий, 400 — обычный, 600 — полужирный, 800 — жирный. Доступные начертания зависят от шрифта.','300 is light, 400 regular, 600 semibold, 800 bold. Faces depend on the font.','range',{section:'text',advanced:true,min:300,max:800,step:100,unit:'count',enabled:t=>t.typography.customMetrics,reason:['Включите настройку толщины и интервалов.','Enable custom weight and spacing.'],target:'text'}),
  range('typography.'+key+'LineHeight',ru+' · межстрочный интервал',en+' · line height','Множитель высоты строки: 1,4 означает 140% размера шрифта.','Line height multiplier: 1.4 means 140% of the font size.','range',{section:'text',advanced:true,min:1,max:2,step:.05,enabled:t=>t.typography.customMetrics,reason:['Включите настройку толщины и интервалов.','Enable custom weight and spacing.'],target:'text'})]),
 toggle('shape.independentRadii','Раздельные округления','Independent rounding','Собственные радиусы кнопок, полей и карточек имеют приоритет над общей формой. Остальные панели сохраняют общую форму.','Custom button, input and card radii override the common shape. Other panels keep it.',{section:'panels',advanced:true}),
 ...[['buttonRadius','Округление кнопок','Button rounding',32],['inputRadius','Округление полей','Input rounding',32],['cardRadius','Округление карточек','Card rounding',40]].map(([key,ru,en,max])=>range('shape.'+key,ru,en,'Радиус в пикселях. 0 — прямые углы.','Radius in pixels. 0 means square corners.','range',{section:'panels',advanced:true,max,step:1,unit:'px',enabled:t=>t.shape.independentRadii,reason:['Включите раздельные округления.','Enable independent rounding.']})),
 range('effects.glassRefraction','Преломление стекла','Glass refraction','Искажает фон под карточками. 0 — только матовое размытие. SVG-преломление зависит от браузера; если его нет, установите 0. В экономном режиме остаётся только размытие.','Distorts the backdrop below cards. 0 keeps frosted blur only. SVG refraction depends on the browser; set 0 if unavailable. Economy mode keeps blur only.','range',{section:'panels',advanced:true,enabled:t=>t.effects.panelMaterial==='optical-glass',reason:['Выберите оптическое стекло.','Choose optical glass.']}),
 range('effects.glassBlur','Размытие стекла','Glass blur','Смягчает фон в собственном слое под поверхностью. Текст остаётся чётким.','Softens the backdrop in an owned layer below the surface. Text stays sharp.','range',{section:'panels',advanced:true,max:16,step:1,unit:'px',enabled:t=>t.effects.panelMaterial==='optical-glass',reason:['Выберите оптическое стекло.','Choose optical glass.']}),
 range('effects.glassEdge','Свет на кромке стекла','Glass edge light','Мягкое отражение вдоль края. На однотонном фоне преломление почти не видно; для оценки используйте изображение или живой фон. Непрозрачная заливка скрывает стекло.','Soft edge reflection. Refraction is subtle on a flat backdrop; preview over an image or live background. Opaque fills hide the glass.','range',{section:'panels',advanced:true,enabled:t=>t.effects.panelMaterial==='optical-glass',reason:['Выберите оптическое стекло.','Choose optical glass.']})
);
export const QUICK_PATHS = ['palette.accent', 'typography.textScale', 'live'];
export const BACKGROUND_STYLES = [
  { id: 'flow', ru: 'Классические переливы', en: 'Classic flow', help:'Прежний вариант с крупными вращающимися областями.', helpEn:'The original large rotating color areas.' },
  {id:'fluid',ru:'Плавные переливы',en:'Fluid flow',help:'Мягкие цветовые области постепенно меняют форму.',helpEn:'Soft color regions gradually change shape.'},
  {id:'aurora',ru:'Северное сияние',en:'Aurora',help:'Широкие размытые ленты медленно изгибаются.',helpEn:'Wide blurred ribbons slowly bend.'},
  {id:'mist',ru:'Цветной туман',en:'Colored mist',help:'Неоднородные облака меняют плотность и смешиваются.',helpEn:'Irregular clouds change density and mix.'},
  { id: 'streams', ru: 'Световые потоки', en: 'Light streams' },
  { id: 'mixed', ru: 'Смешанный', en: 'Mixed' }
];
export function fieldValue(theme, path, mode) {
  if(theme.paletteEffects?.separate && PROFILE_PATHS[path]) return theme.paletteEffects[mode+PROFILE_PATHS[path]];
  if (path === 'live') return on(theme);
  const [section, key] = path.split('.');
  if (path === 'background.mode' && theme.background.mode === 'default') return 'solid';
  return theme[section === 'palette' ? mode : section][key];
}
export function setFieldValue(theme, path, mode, value) {
  if(theme.paletteEffects?.separate && PROFILE_PATHS[path]) {theme.paletteEffects[mode+PROFILE_PATHS[path]]=value;return;}
  if (path === 'live') { theme.effects.animatedBackground = value ? 'subtle' : 'off'; return; }
  const [section, key] = path.split('.');
  theme[section === 'palette' ? mode : section][key] = value;
}
