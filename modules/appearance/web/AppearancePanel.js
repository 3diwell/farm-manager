// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { simpleValues, setSimpleValue } from './editor-simple.js';
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import INSTALLED_THEME from './theme-preset.js';
import DEFAULT_THEME from './default-theme.js';
import { MODULE_VERSION } from './theme-schema.js';
import { cloneTheme, mergeWithDefaults, validateTheme, safeFileName, themeHiddenReason } from './theme-validator.js';
import { bootstrapThemeRuntime, clearPreviewTheme, getAppliedTheme, getRuntimeState, setAppliedTheme, setPreviewTheme } from './theme-runtime.js';
import { exportThemePackage } from './theme-package.js';
import { BACKGROUND_STYLES, fieldValue, setFieldValue } from './editor-fields.js';
import { FIELDS, SECTIONS, GROUPS, fieldSummary } from './editor-layout.js';
import { resolveProfile, separateProfiles, PROFILE_PATHS } from './theme-profiles.js';
import { appearanceSignature, readAppliedHistory, recordAppliedTheme, packCollection, importCollection, signature, readDraft, writeDraft, readCollection, writeCollection, readLibraryState, exportLibrary, themeEntry, readEditorState, writeEditorState } from './editor-storage.js';
import { AppearanceField, PANEL_CSS } from './editor-components.js';
import { UNIFIED_CSS } from './editor-unified-style.js';
import { SOFT_CSS } from './editor-soft-style.js';
import { curatedThemes, presetThumbnail } from './editor-presets.js';
import { SAMPLE_DOCUMENT } from './editor-sample.js';
import { PANEL_TEMPLATE } from './editor-unified-template.js';

bootstrapThemeRuntime(INSTALLED_THEME);
function ensureStyles(){let node=document.getElementById('appearance-panel-styles');if(!node){node=document.createElement('style');node.id='appearance-panel-styles';document.head.appendChild(node);}const css=PANEL_CSS+UNIFIED_CSS+SOFT_CSS;if(node.textContent!==css)node.textContent=css;}
function replaceTheme(target,next){Object.keys(target).forEach(k=>delete target[k]);Object.assign(target,mergeWithDefaults(next));}
function downloadJson(theme,filename){const url=URL.createObjectURL(new Blob([JSON.stringify(theme,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=filename||`3DIWELL_Theme_${safeFileName(theme.meta.name)}.json`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);}

export default {
  name:'AppearancePanel',components:{AppearanceField},props:{open:{type:Boolean,default:false},lang:{type:String,default:'ru'}},emits:['close'],
  setup(props,{emit}){
    ensureStyles();const L=(ru,en)=>props.lang==='ru'?ru:en;
    const initial=mergeWithDefaults(getAppliedTheme()||INSTALLED_THEME);
    const baseline=ref(cloneTheme(initial)),theme=reactive(cloneTheme(initial)),ui=readEditorState();
    const joinProfiles=ref(false);
    const builtins=curatedThemes();
    const fine=reactive(ui.fine&&typeof ui.fine==='object'?ui.fine:{}),saveCopyOpen=ref(false),previewHeight=ref(460);
    const tab=ref(SECTIONS.some(s=>s.id===ui.tab)?ui.tab:ui.tab==='text'?'colors':'themes');
    const paletteMode=ref(document.documentElement.dataset.theme==='light'?'light':'dark'),editorPalette=ref(paletteMode.value);
    const advanced=reactive(ui.advanced&&typeof ui.advanced==='object'?ui.advanced:{});
    const query=ref(''),forcedField=ref(''),message=ref(''),draftStatus=ref(''),storageError=ref('');
    const comparing=ref(false),previewEnabled=ref(false),previewCollapsed=ref(false),previewFrame=ref(null),previewReady=ref(false),previewError=ref(false),previewAmbientError=ref(false);
    const editorDialog=ref(null),imageInput=ref(null),fontInput=ref(null),importInput=ref(null);
    const collection=ref(readCollection()),copyName=ref(''),deletedTheme=ref(null),staleDraft=ref(null),busy=ref(false);
    const sampleState=ref('printing'),backgroundOnly=ref(false),sampleSpeed=ref(1),longNames=ref(false),largeText=ref(false),sampleChoices=ref([]);
    const collectionInput=ref(null),sourceId=ref(typeof ui.sourceId==='string'?ui.sourceId:''),renamingId=ref(''),renameName=ref(''),appliedHistory=ref(readAppliedHistory());
    const effective=computed(()=>resolveProfile(theme,paletteMode.value));
    const runtime=ref(getRuntimeState()),systemReduced=ref(window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    // 0.17.5: если часть тем этой версии не видна (их сохранила версия модуля новее или они повреждены),
    // редактор говорит об этом словами, а не показывает пустой список молча.
    const libraryState=ref(readLibraryState()),hiddenCount=computed(()=>libraryState.value.newer+libraryState.value.invalid);
    const storageNotice=computed(()=>{
      const s=libraryState.value,applied=runtime.value.appliedHidden,out=[];
      if(s.unreadable==='newer')out.push(L('«Мои темы» сохранены более новой версией модуля и в этой версии не видны. Они не удалены и вернутся, когда вы снова поставите новую версию. До тех пор новые варианты здесь не сохраняются.','My themes were saved by a newer module version and are not visible in this version. They are not deleted and will return when you install the newer version again. Until then, new variations cannot be saved here.'));
      else if(s.unreadable)out.push(L('Список «Мои темы» повреждён и не читается, поэтому новые варианты не сохраняются. Тему, выгруженную раньше в JSON, можно открыть кнопкой «Импортировать JSON» и применить.','My themes cannot be read because the saved data is damaged, so new variations cannot be saved. A theme exported earlier as JSON can still be opened with Import JSON and applied.'));
      if(s.newer)out.push(L('Скрыто тем в «Мои темы»: '+s.newer+'. Их сохранила более новая версия модуля, эта версия их не показывает. Темы не удалены и вернутся, когда вы снова поставите новую версию.','Hidden in My themes: '+s.newer+'. They were saved by a newer module version, and this version cannot show them. They are not deleted and will return when you install the newer version again.'));
      if(s.invalid)out.push(L('Скрыто тем в «Мои темы»: '+s.invalid+' — в них ошибка, открыть их нельзя, но место из 20 они занимают. Остальные темы в порядке.','Hidden in My themes: '+s.invalid+'. They contain errors and cannot be opened, but they still take places out of 20. Your other themes are fine.'));
      if(applied==='newer')out.push(L('Применённую тему сохранила более новая версия модуля, поэтому сейчас действует стартовая тема модуля. Ваша тема вернётся после установки новой версии, если до этого не применять здесь другую.','The applied theme was saved by a newer module version, so the module starting theme is used now. Your theme will return after you install the newer version, unless you apply another theme here first.'));
      else if(applied==='invalid')out.push(L('Применённая тема повреждена, поэтому сейчас действует стартовая тема модуля.','The applied theme is damaged, so the module starting theme is used now.'));
      return out;
    });
    const history=ref([cloneTheme(initial)]),historyIndex=ref(0);
    const validation=computed(()=>validateTheme(theme)),dirty=computed(()=>signature(theme)!==signature(baseline.value));
    const simple=computed(()=>simpleValues(theme,paletteMode.value));
    const builtinMatch=computed(()=>builtins.find(e=>appearanceSignature(e.theme)===appearanceSignature(theme))?.id||'');
    const currentSection=computed(()=>SECTIONS.find(s=>s.id===tab.value));
    const canUndo=computed(()=>historyIndex.value>0||signature(theme)!==signature(history.value[historyIndex.value]));
    const canRedo=computed(()=>historyIndex.value<history.value.length-1);
    let historyTimer,saveTimer,previewTimer,readyTimer,messageTimer,runtimeTimer,highlightTimer,previousFocus,restoring=false;
    const flash=text=>{message.value=text;clearTimeout(messageTimer);messageTimer=setTimeout(()=>{message.value='';},6500);};
    const read=f=>f.linked&&effective.value.effects.backgroundFlowUseThemeColors?(f.path.endsWith('Primary')?theme[paletteMode.value].accent:theme.effects.secondaryAccent):fieldValue(theme,f.path,paletteMode.value);
    const original=f=>f.linked&&resolveProfile(baseline.value,paletteMode.value).effects.backgroundFlowUseThemeColors?(f.path.endsWith('Primary')?baseline.value[paletteMode.value].accent:baseline.value.effects.secondaryAccent):fieldValue(baseline.value,f.path,paletteMode.value);
    const enabled=f=>!f.enabled||f.enabled(effective.value),reason=f=>f.reason?L(...f.reason):'';
    const errorPath=code=>{const match=code.match(/^paletteEffects\.(dark|light)(.+)$/);return match?Object.keys(PROFILE_PATHS).find(p=>PROFILE_PATHS[p]===match[2])||code:code.replace(/^(dark|light)\./,'palette.');};
    const invalid=f=>validation.value.errors.some(code=>errorPath(code)===f.path&&(!code.startsWith('paletteEffects.')||code.startsWith('paletteEffects.'+paletteMode.value)));
    const visible=f=>enabled(f)||(f.linked&&theme.effects.animatedBackground!=='off')||forcedField.value===f.path;
    const sectionFields=(detail=false,group)=>FIELDS.filter(f=>f.section===tab.value&&!!f.advanced===detail&&(!group||f.group===group)&&visible(f));
    const detailGroups=computed(()=>GROUPS.filter(g=>g.section===tab.value&&sectionFields(true,g.id).length));
    const scope=f=>f.path.startsWith('palette.')||(theme.paletteEffects.separate&&PROFILE_PATHS[f.path])?(paletteMode.value==='dark'?L('Тёмная палитра','Dark palette'):L('Светлая палитра','Light palette')):L('Обе палитры','Both palettes');
    const groupSummary=g=>{
      const fields=sectionFields(true,g.id),changed=fields.filter(f=>JSON.stringify(read(f))!==JSON.stringify(original(f))).length;
      const text=g.id==='fonts'?fieldSummary(fields[0],read(fields[0]),props.lang):L('Параметров: ','Settings: ')+fields.length;
      return text+(changed?L(' · изменено: ',' · changed: ')+changed:'');
    };
    const searchResults=computed(()=>{const terms=query.value.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);return terms.length?FIELDS.filter(f=>terms.every(t=>`${f.label} ${f.en} ${f.help} ${f.helpEn} ${f.path} ${f.section==='background'?'фон анимация background animation':''}`.toLocaleLowerCase().includes(t))).slice(0,12):[];});
    const motionStatus=computed(()=>systemReduced.value?L('Движение остановлено системной настройкой уменьшения анимации.','Motion is stopped by the system reduced motion setting.'):theme.interface.reduceMotion?L('Движение остановлено: включено «Уменьшить движение».','Motion is stopped: Reduce motion is enabled.'):theme.effects.animatedBackground==='off'?L('Живой фон выключен. Блики карточек настраиваются отдельно.','Animated background is off. Card glints are controlled separately.'):effective.value.effects.backgroundFlowOpacity===0?L('Живой фон включён, но его яркость равна нулю.','Animated background is on, but brightness is zero.'):theme.effects.backgroundAnimationStyle==='mixed'&&theme.effects.backgroundFlowMix===0&&theme.effects.backgroundStreamsMix===0?L('Оба эффекта смешанного фона установлены на 0%.','Both mixed background contributions are 0%.'):L('Декоративные анимации останавливаются, когда вкладка скрыта.','Decorative animations pause while the tab is hidden.'));
    const sendSample=(extra={})=>{
      if(!previewReady.value||!previewFrame.value?.contentWindow)return;
      const sample=comparing.value?baseline.value:validation.value.ok?validation.value.theme:null;
      previewFrame.value.contentWindow.postMessage({type:'fm-appearance-sample',...(sample?{theme:cloneTheme(sample)}:{}),mode:paletteMode.value,lang:props.lang,paused:!props.open||previewCollapsed.value||document.hidden,state:sampleState.value,backgroundOnly:backgroundOnly.value,speed:sampleSpeed.value,longNames:longNames.value,largeText:largeText.value,...extra},window.location.origin);
    };
    const updatePreview=()=>{sendSample();if(previewEnabled.value){const next=comparing.value?baseline.value:validation.value.ok?validation.value.theme:null;if(next)setPreviewTheme(cloneTheme(next));}};
    const sampleMessage=e=>{if(e.source!==previewFrame.value?.contentWindow||e.origin!==window.location.origin)return;if(e.data?.type==='fm-appearance-sample-height'&&Number.isFinite(e.data.height)){previewHeight.value=Math.max(100,Math.min(2400,Math.ceil(e.data.height)));return;}if(e.data?.type==='fm-appearance-sample-select')selectSample(e.data.target);if(e.data?.type==='fm-appearance-sample-ready'){previewReady.value=true;previewError.value=false;clearTimeout(readyTimer);sendSample();}if(e.data?.type==='fm-appearance-sample-rendered'){previewError.value=!e.data.ok;previewAmbientError.value=!!e.data.ambientError;}};
    const frameLoaded=()=>{clearTimeout(readyTimer);if(!previewReady.value)readyTimer=setTimeout(()=>{if(!previewReady.value)previewError.value=true;},5000);};
    const highlight=target=>{if(target)sendSample({highlight:target});};
    const recordHistory=()=>{clearTimeout(historyTimer);if(restoring||signature(history.value[historyIndex.value])===signature(theme))return;const next=history.value.slice(0,historyIndex.value+1);next.push(cloneTheme(theme));if(next.length>30)next.shift();history.value=next;historyIndex.value=next.length-1;};
    const saveDraft=()=>{clearTimeout(saveTimer);if(writeDraft(theme,baseline.value)){storageError.value='';draftStatus.value=dirty.value?L('Черновик сохранён','Draft saved'):L('Все изменения применены','All changes applied');}else storageError.value=L('Не удалось сохранить черновик. Экспортируйте JSON, чтобы сохранить работу.','Could not save the draft. Export JSON to keep your work.');};
    const setValue=(f,value)=>{comparing.value=false;if(f.path==='typography.font'&&value==='custom'&&!theme.typography.customFontDataUrl){fontInput.value.click();return;}setFieldValue(theme,f.path,paletteMode.value,value);};
    const resetField=f=>{comparing.value=false;if(f.path==='live')theme.effects.animatedBackground=baseline.value.effects.animatedBackground;else setFieldValue(theme,f.path,paletteMode.value,fieldValue(baseline.value,f.path,paletteMode.value));};
    const resetSection=()=>{recordHistory();FIELDS.filter(f=>f.section===tab.value).forEach(resetField);if(tab.value==='background'){theme.effects.backgroundAnimationStyle=baseline.value.effects.backgroundAnimationStyle;theme.background.imageDataUrl=baseline.value.background.imageDataUrl;}if(tab.value==='colors')['customFontName','customFontFormat','customFontDataUrl'].forEach(k=>{theme.typography[k]=baseline.value.typography[k];});flash(L('Раздел возвращён к применённым настройкам.','Section restored to applied settings.'));};
    const undo=()=>{recordHistory();if(historyIndex.value<=0)return;restoring=true;replaceTheme(theme,history.value[--historyIndex.value]);restoring=false;};
    const redo=()=>{if(!canRedo.value)return;restoring=true;replaceTheme(theme,history.value[++historyIndex.value]);restoring=false;};
    const selectTab=id=>{tab.value=id;forcedField.value='';comparing.value=false;};
    const goToField=async f=>{tab.value=f.section;forcedField.value=f.path;query.value='';if(f.group){fine[f.section]=true;advanced[f.group]=true;}await nextTick();const n=editorDialog.value?.querySelector(`[data-field="${f.path}"]`);if(n){n.scrollIntoView({block:'nearest'});n.classList.add('ap-match');clearTimeout(highlightTimer);highlightTimer=setTimeout(()=>n.classList.remove('ap-match'),1800);n.querySelector('input:not(:disabled),select:not(:disabled),button')?.focus();}};
    const selectSample=target=>{
      const map={dashboard:['dashboard.water','dashboard.timeSize','dashboard.showModel','dashboard.heating'],text:['typography.textScale'],background:['effects.backgroundFlowOpacity'],header:['palette.headerSurface'],status:['effects.statusStyle'],progress:['effects.progressStyle'],controls:['effects.controlStyle'],table:['effects.tableStyle'],card:['palette.surfaceCard','effects.panelDepth','effects.hoverGlintIntensity'],project:['palette.surfaceCard','effects.panelDepth','effects.hoverGlintIntensity']};
      const paths=map[target];if(!paths)return;
      sampleChoices.value=paths.map(p=>FIELDS.find(f=>f.path===p)).filter(Boolean);
      if(sampleChoices.value.length===1){goToField(sampleChoices.value[0]);sampleChoices.value=[];}
    };
    const selectSampleField=f=>{goToField(f);sampleChoices.value=[];};
    const setSeparate=value=>{if(!value){joinProfiles.value=true;return;}recordHistory();separateProfiles(theme,true,paletteMode.value);comparing.value=false;};
    const confirmJoin=mode=>{recordHistory();separateProfiles(theme,false,mode);joinProfiles.value=false;comparing.value=false;};
    const errorText=code=>{
      const palette=code.startsWith('light.')?L('Светлая палитра: ','Light palette: '):code.startsWith('dark.')?L('Тёмная палитра: ','Dark palette: '):'';
      if(code.includes('.contrast.'))return palette+(code.endsWith('secondary')?L('Дополнительный текст плохо различим на карточке.','Secondary text has low contrast on cards.'):L('Основной текст плохо различим. Измените цвет текста или поверхности.','Main text has low contrast. Adjust text or surface colors.'));
      if(code==='background.imageDataUrl')return L('Выберите корректное фоновое изображение.','Choose a valid background image.');
      const f=FIELDS.find(f=>f.path===code||f.path===errorPath(code));
      if(f)return palette+L('Проверьте настройку «','Check “')+L(f.label,f.en)+L('».','”.');
      if(code.startsWith('typography.custom'))return L('Не удалось проверить шрифт. Выберите другой файл.','The font is invalid. Choose another file.');
      if(code.startsWith('meta.'))return L('Название и описание должны быть текстом без разметки. Название — до 100 символов.','Name and description must be plain text. Names can contain up to 100 characters.');
      return L('Не удалось проверить настройки темы. Проверьте импортируемый файл.','Could not validate theme settings. Check the imported file.');
    };
    const showErrorField=code=>{if(/^(dark|light)\./.test(code))paletteMode.value=code.split('.')[0];const pm=code.match(/^paletteEffects\.(dark|light)/);if(pm)paletteMode.value=pm[1];const path=code.includes('.contrast.')?'palette.textPrimary':errorPath(code);const f=FIELDS.find(f=>f.path===path);if(f)goToField(f);else selectTab(code.startsWith('background')?'background':code.startsWith('typography')?'colors':'themes');};
    const changeSimple=(key,value)=>{if(setSimpleValue(theme,key,value,paletteMode.value))comparing.value=false;};
    const chooseBuiltin=entry=>{const preset=builtins.find(e=>e.id===entry.id);if(!preset)return;recordHistory();replaceTheme(theme,preset.theme);sourceId.value='';comparing.value=false;flash(L('Тема открыта в образце. Примените её, когда результат понравится.','Theme opened in the sample. Apply it when you are happy with the result.'));};
    const startPreview=()=>{if(!validation.value.ok)return;if(runtime.value.emergencyOff){flash(L('Предпросмотр в FM отключён параметром appearance=off в адресе. Образец доступен.','FM preview is disabled by appearance=off in the address. The sample remains available.'));return;}previewEnabled.value=true;previewCollapsed.value=true;comparing.value=false;previewReady.value=false;setPreviewTheme(cloneTheme(validation.value.theme));};
    const returnEditor=()=>{previewCollapsed.value=false;previewReady.value=false;};
    const stopPreview=()=>{const remount=previewCollapsed.value;clearPreviewTheme();previewEnabled.value=false;previewCollapsed.value=false;comparing.value=false;if(remount)previewReady.value=false;};
    const applyPersonal=()=>{
      if(!validation.value.ok)return;const result=setAppliedTheme(validation.value.theme);
      if(!result.ok){storageError.value=L('Не удалось сохранить тему в браузере. Экспортируйте JSON.','Could not save the theme in this browser. Export JSON.');return;}
      const historySaved=recordAppliedTheme(result.theme);appliedHistory.value=readAppliedHistory();
      clearPreviewTheme();previewEnabled.value=false;previewCollapsed.value=false;comparing.value=false;
      // Do not invalidate a still-mounted sample frame.
      replaceTheme(theme,result.theme);baseline.value=cloneTheme(result.theme);history.value=[cloneTheme(result.theme)];historyIndex.value=0;saveDraft();runtime.value=getRuntimeState();
      if(!historySaved){flash(libraryState.value.unreadable?L('Тема применена. История применений не ведётся, пока «Мои темы» не читаются — см. сообщение вверху.','Theme applied. History is not kept while My themes cannot be read — see the message above.'):L('Тема применена, но история не сохранилась: не хватает места или хранилище недоступно.','Theme applied, but history could not be saved: storage is full or unavailable.'));return;}
      flash(runtime.value.emergencyOff?L('Сохранено. Уберите appearance=off из адреса, чтобы увидеть тему в FM.','Saved. Remove appearance=off from the address to see the theme.'):L('Ваша тема сохранена и применена в этом браузере.','Your theme is saved and applied in this browser.'));
    };
    const close=()=>{saveDraft();clearPreviewTheme();previewEnabled.value=false;previewCollapsed.value=false;previewReady.value=false;emit('close');};
    const addCopy=()=>{
      const name=copyName.value.trim()||`${theme.meta.name} ${L('— копия','— copy')}`.slice(0,100),checked=validateTheme({...cloneTheme(theme),meta:{...cloneTheme(theme.meta),name}});
      if(!checked.ok){flash(L('Исправьте ошибки темы перед сохранением варианта.','Fix theme errors before saving a variation.'));return;}
      if(collection.value.length+hiddenCount.value>=20){flash(L('Сохранено 20 вариантов. Экспортируйте или удалите ненужный.','20 variations are saved. Export or remove an unused one.'));return;}
      const next=[...collection.value,themeEntry(checked.theme,name)];if(!writeCollection(next)){flash(libraryState.value.unreadable?L('Вариант не сохранён: список «Мои темы» не читается — см. сообщение вверху.','Variation not saved: My themes cannot be read — see the message above.'):L('Не хватает места для варианта. Экспортируйте JSON.','Not enough storage for this variation. Export JSON.'));return;}
      collection.value=next;sourceId.value=next.at(-1).id;copyName.value='';saveCopyOpen.value=false;flash(L('Вариант добавлен в «Мои темы».','Variation added to My themes.'));
    };
    const loadTheme=entry=>{recordHistory();sourceId.value=collection.value.some(e=>e.id===entry.id)?entry.id:'';replaceTheme(theme,entry.theme);comparing.value=false;flash(L('Вариант открыт в образце. Нажмите «Применить», когда он будет готов.','Variation opened in the sample. Choose Apply when ready.'));};
    const removeTheme=entry=>{const next=collection.value.filter(e=>e.id!==entry.id);if(!writeCollection(next)){flash(L('Не удалось удалить вариант.','Could not delete the variation.'));return;}deletedTheme.value=entry;collection.value=next;};
    const undoDelete=()=>{if(!deletedTheme.value||collection.value.length+hiddenCount.value>=20)return;const next=[...collection.value,deletedTheme.value];if(writeCollection(next)){collection.value=next;deletedTheme.value=null;}};
    const entryApplied=entry=>appearanceSignature(entry.theme)===appearanceSignature(baseline.value);
    const entryChanged=entry=>entry.id===sourceId.value&&appearanceSignature(entry.theme)!==appearanceSignature(theme);
    const thumbnail=entry=>{const p=entry.theme[paletteMode.value];return {background:p.surfaceDeep,color:p.textPrimary,borderColor:p.border,'--ap-thumb-card':p.surfaceCard,'--ap-thumb-accent':p.accent};};
    const startRename=entry=>{renamingId.value=entry.id;renameName.value=entry.name;};
    const renameEntry=entry=>{
      const name=renameName.value.trim(),next=collection.value.map(e=>e.id===entry.id?{...e,name,theme:{...cloneTheme(e.theme),meta:{...e.theme.meta,name}}}:e);
      if(!name||name.length>100||/[<>]/.test(name)||!writeCollection(next)){flash(L('Не удалось переименовать. Проверьте название и доступное место.','Could not rename. Check the name and available storage.'));return;}
      collection.value=next;renamingId.value='';
    };
    const updateEntry=entry=>{
      if(!validation.value.ok)return;
      const copy=cloneTheme(validation.value.theme);copy.meta.name=entry.name;
      const next=collection.value.map(e=>e.id===entry.id?{...e,theme:copy}:e);
      if(!writeCollection(next)){flash(L('Не удалось обновить вариант.','Could not update the variation.'));return;}
      collection.value=next;flash(L('Сохранённый вариант обновлён.','Saved variation updated.'));
    };
    const exportCollection=()=>downloadJson(exportLibrary(collection.value),'3DIWELL_My_Themes.json');
    const onCollectionFile=async e=>{
      const file=e.target.files?.[0];e.target.value='';if(!file)return;
      if(file.size>12_000_000){flash(L('Коллекция должна быть не больше 12 МБ.','The collection must be 12 MB or smaller.'));return;}
      try{
        const result=importCollection(JSON.parse(await file.text())),{newer,invalid}=result.skipped;collection.value=result.entries;
        // 0.17.5: коллекция добавляется по одной теме; что не добавлено и почему — словами.
        flash(newer+invalid?L('Варианты добавлены в «Мои темы». Не добавлено: '+(newer+invalid)+(newer&&invalid?' — сохранены более новой версией модуля или в них ошибка.':newer?' — сохранены более новой версией модуля.':' — в них ошибка.'),'Variations added to My themes. Not added: '+(newer+invalid)+(newer&&invalid?' — saved by a newer module version or contain errors.':newer?' — saved by a newer module version.':' — contain errors.')):L('Варианты добавлены в «Мои темы».','Variations added to My themes.'));
      }
      catch(err){flash(err.message==='store'?L('Коллекция не добавлена: список «Мои темы» не читается — см. сообщение вверху.','Collection not added: My themes cannot be read — see the message above.'):err.message==='newer'?L('Эту коллекцию сохранила более новая версия модуля, эта версия не может её добавить. Обновите модуль «Оформление и темы».','This collection was saved by a newer module version and cannot be added here. Update the Appearance module.'):err.message==='limit'?L('В коллекции можно хранить до 20 вариантов. Освободите место перед импортом.','The collection holds up to 20 variations. Make room before importing.'):L('Коллекция не импортирована. Проверьте файл и свободное место. Существующие варианты сохранены.','Collection was not imported. Check the file and free storage. Existing variations are retained.'));}
    };
    const historyDate=entry=>new Date(entry.appliedAt).toLocaleString(props.lang==='ru'?'ru-RU':'en-US');
    const exportJson=()=>{if(validation.value.ok)downloadJson(validation.value.theme);};
    const exportZip=async()=>{if(!validation.value.ok||busy.value)return;busy.value=true;try{await exportThemePackage(validation.value.theme);flash(L('Установочный ZIP подготовлен.','Installable ZIP prepared.'));}catch(_){flash(L('Не удалось собрать ZIP. Настройки можно сохранить в JSON.','Could not build the ZIP. You can save settings as JSON.'));}finally{busy.value=false;}};
    const importJson=async e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;if(file.size>6_000_000){flash(L('Выберите JSON до 6 МБ.','Choose a JSON up to 6 MB.'));return;}let parsed;try{parsed=JSON.parse(await file.text());const checked=validateTheme(parsed);if(!checked.ok)throw Error('invalid');sourceId.value='';replaceTheme(theme,checked.theme);comparing.value=false;flash(L('Тема импортирована в редактор. Проверьте образец перед применением.','Theme imported. Review the sample before applying.'));}catch(_){flash(parsed!==undefined&&themeHiddenReason(parsed)==='newer'?L('Эту тему сохранила более новая версия модуля, эта версия не может её открыть. Обновите модуль «Оформление и темы».','This theme was saved by a newer module version and cannot be opened here. Update the Appearance module.'):L('Недопустимая тема. Выберите JSON, экспортированный редактором.','Invalid theme. Choose JSON exported by the editor.'));}};
    const onBackgroundFile=e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>1_500_000){flash(L('Допустимы PNG, JPEG и WEBP до 1,5 МБ.','Use PNG, JPEG or WEBP up to 1.5 MB.'));return;}const reader=new FileReader();reader.onload=()=>{const image=new Image();image.onload=()=>{theme.background.imageDataUrl=String(reader.result);theme.background.mode='image';};image.onerror=()=>flash(L('Не удалось открыть изображение.','Could not open the image.'));image.src=String(reader.result);};reader.onerror=()=>flash(L('Не удалось прочитать файл.','Could not read the file.'));reader.readAsDataURL(file);};
    const clearImage=()=>{theme.background.mode='solid';theme.background.imageDataUrl='';};
    const onFontFile=e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;const ext=file.name.split('.').pop().toLowerCase(),formats={woff2:'woff2',woff:'woff',ttf:'truetype',otf:'opentype'};if(!formats[ext]||file.size>2_000_000){flash(L('Допустимы WOFF2, WOFF, TTF и OTF до 2 МБ.','Use WOFF2, WOFF, TTF or OTF up to 2 MB.'));return;}const reader=new FileReader();reader.onload=async()=>{try{const data=`data:font/${ext};base64,${String(reader.result).split(';base64,')[1]}`;await new FontFace('FMThemeCheck',`url(${data})`).load();Object.assign(theme.typography,{font:'custom',customFontName:file.name.replace(/[<>]/g,'').slice(0,180),customFontFormat:formats[ext],customFontDataUrl:data});flash(L('Шрифт добавлен в тему.','Font added to the theme.'));}catch(_){flash(L('Файл не распознан как шрифт.','The file is not a valid font.'));}};reader.onerror=()=>flash(L('Не удалось прочитать файл.','Could not read the file.'));reader.readAsDataURL(file);};
    const clearFont=()=>Object.assign(theme.typography,{font:'system',customFontName:'',customFontFormat:'',customFontDataUrl:''});
    const recoverDraft=()=>{if(staleDraft.value?.theme){replaceTheme(theme,staleDraft.value.theme);staleDraft.value=null;saveDraft();}};
    const onDialogKeydown=e=>{if(e.key==='Escape'){e.stopPropagation();e.preventDefault();close();return;}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();saveDraft();return;}if(e.key!=='Tab')return;const nodes=Array.from(editorDialog.value.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea,summary,iframe')).filter(n=>n.getClientRects().length);if(!nodes.length)return;const first=nodes[0],last=nodes[nodes.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}};
    const beginSession=()=>{previousFocus=document.activeElement;libraryState.value=readLibraryState();runtime.value=getRuntimeState();editorPalette.value=document.documentElement.dataset.theme==='light'?'light':'dark';const current=mergeWithDefaults(getAppliedTheme()||INSTALLED_THEME);if(signature(current)!==signature(baseline.value)){baseline.value=cloneTheme(current);replaceTheme(theme,current);}const draft=readDraft(current),newerDraft=!!draft?.theme&&themeHiddenReason(draft.theme)==='newer';if(newerDraft){/* 0.17.5: черновик более новой версии эта версия открыть не может — не предлагаем и не трогаем */}else if(draft?.stale)staleDraft.value=draft;else if(draft?.theme){replaceTheme(theme,draft.theme);flash(L('Восстановлен незавершённый черновик.','Unfinished draft restored.'));}history.value=[cloneTheme(current)];historyIndex.value=0;recordHistory();nextTick(()=>editorDialog.value?.focus());};
    watch(theme,()=>{if(!restoring){clearTimeout(historyTimer);historyTimer=setTimeout(recordHistory,350);}clearTimeout(saveTimer);draftStatus.value=L('Сохраняю черновик…','Saving draft…');saveTimer=setTimeout(saveDraft,650);clearTimeout(previewTimer);previewTimer=setTimeout(updatePreview,110);},{deep:true});
    watch([paletteMode,comparing,sampleState,backgroundOnly,sampleSpeed,longNames,largeText,()=>props.lang],updatePreview);
    watch([tab,advanced,fine,sourceId],()=>writeEditorState({tab:tab.value,advanced:{...advanced},fine:{...fine},sourceId:sourceId.value}),{deep:true});
    watch(()=>props.open,open=>{if(open)beginSession();else{saveDraft();clearPreviewTheme();previewEnabled.value=false;previewCollapsed.value=false;previewReady.value=false;nextTick(()=>previousFocus?.focus?.());}});
    const visibility=()=>sendSample(),media=window.matchMedia('(prefers-reduced-motion: reduce)'),mediaChanged=()=>{systemReduced.value=media.matches;};
    onMounted(()=>{window.addEventListener('message',sampleMessage);document.addEventListener('visibilitychange',visibility);if(media.addEventListener)media.addEventListener('change',mediaChanged);else media.addListener(mediaChanged);if(props.open)beginSession();runtimeTimer=setInterval(()=>{if(props.open)runtime.value=getRuntimeState();},1500);});
    onUnmounted(()=>{saveDraft();[historyTimer,saveTimer,previewTimer,readyTimer,messageTimer,highlightTimer].forEach(clearTimeout);clearInterval(runtimeTimer);clearPreviewTheme();window.removeEventListener('message',sampleMessage);document.removeEventListener('visibilitychange',visibility);if(media.removeEventListener)media.removeEventListener('change',mediaChanged);else media.removeListener(mediaChanged);});
    return {fine,saveCopyOpen,previewHeight,presetThumbnail,effective,simple,builtins,builtinMatch,changeSimple,chooseBuiltin,scope,detailGroups,groupSummary,joinProfiles,confirmJoin,sampleState,backgroundOnly,sampleSpeed,longNames,largeText,sampleChoices,selectSampleField,setSeparate,collectionInput,sourceId,renamingId,renameName,appliedHistory,entryApplied,entryChanged,thumbnail,startRename,renameEntry,updateEntry,exportCollection,onCollectionFile,historyDate,hiddenCount,storageNotice,libraryState,L,version:MODULE_VERSION,SECTIONS,FIELDS,BACKGROUND_STYLES,theme,tab,paletteMode,editorPalette,advanced,query,forcedField,message,draftStatus,storageError,comparing,previewEnabled,previewCollapsed,previewFrame,previewReady,previewError,previewAmbientError,editorDialog,imageInput,fontInput,importInput,collection,copyName,deletedTheme,staleDraft,busy,runtime,validation,dirty,currentSection,canUndo,canRedo,read,original,enabled,reason,invalid,sectionFields,searchResults,motionStatus,frameLoaded,highlight,setValue,resetField,resetSection,undo,redo,selectTab,goToField,errorText,showErrorField,startPreview,returnEditor,stopPreview,applyPersonal,close,addCopy,loadTheme,removeTheme,undoDelete,exportJson,exportZip,importJson,onBackgroundFile,clearImage,onFontFile,clearFont,recoverDraft,onDialogKeydown,SAMPLE_DOCUMENT,replaceWithInstalled:()=>{recordHistory();sourceId.value='';replaceTheme(theme,INSTALLED_THEME);comparing.value=false;},replaceWithDefault:()=>{recordHistory();sourceId.value='';replaceTheme(theme,DEFAULT_THEME);comparing.value=false;}};
  },template:PANEL_TEMPLATE
};
