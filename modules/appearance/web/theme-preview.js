// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { renderIsolatedTheme, getRuntimeState } from './theme-runtime.js';
const origin=new URL(import.meta.url).origin;
let timer;
const targets=new Set(['header','background','card','text','status','progress','project','controls','table','dashboard']);
function select(target){if(targets.has(target))parent.postMessage({type:'fm-appearance-sample-select',target},origin);}
// 0.17.5: строка времени и строка температур занимают всю ширину карточки. «Dashboard» открывается щелчком
// по самим цифрам и подписям, а по пустому месту этих строк — настройки карточки, как по остальной карточке.
const clicked=(n,e)=>n.dataset.sample==='dashboard'&&(e.target===n||e.target.classList?.contains('fm-ap-dash-time'))?'card':n.dataset.sample;
document.querySelectorAll('[data-sample]').forEach(n=>{
  n.tabIndex=0;
  n.addEventListener('click',e=>{e.stopPropagation();select(clicked(n,e));});
  n.addEventListener('keydown',e=>{if(e.target===n&&(e.key==='Enter'||e.key===' ')){e.preventDefault();e.stopPropagation();select(n.dataset.sample);}});
});
document.body.addEventListener('click',e=>{if(e.target===document.body)select('background');});
window.addEventListener('message',event=>{
  if(event.source!==parent||event.origin!==origin||event.data?.type!=='fm-appearance-sample')return;
  const d=event.data;
  if(d.theme){
    const speed=d.speed===3?3:1;
    const ok=renderIsolatedTheme(d.theme,d.mode,!!d.paused,speed);
    if(ok){
      const ru=d.lang!=='en';document.documentElement.lang=ru?'ru':'en';
      document.querySelectorAll('[data-ru]').forEach(n=>{n.textContent=n.dataset[ru?'ru':'en'];});
      document.body.classList.toggle('sample-background-only',!!d.backgroundOnly);
      document.body.classList.toggle('sample-large',!!d.largeText);
      const state=['printing','ready','offline','error','selected','paused','idle'].includes(d.state)?d.state:'printing';
      const card=document.querySelector('[data-sample="card"]'),badge=document.querySelector('[data-sample="status"]');
      card.dataset.state=state;
      card.classList.remove('pcd-print','pcd-done','pcd-error','pcd-paused','pcd-offline','pcd-idle');
      card.classList.add('pcd-'+({printing:'print',ready:'done',selected:'print'}[state]||state));
      card.classList.toggle('card-active',state==='printing');card.classList.toggle('sample-selected',state==='selected');
      const states={printing:['● Печать','● Printing','success',48],ready:['● Готов','● Ready','success',100],offline:['○ Не в сети','○ Offline','text-muted',0],error:['! Ошибка','! Error','danger',48],selected:['✓ Выбрано','✓ Selected','accent',48],paused:['Пауза','Paused','warning',48],idle:['Свободен','Idle','text-muted',0]},s=states[state];
      badge.textContent=s[ru?0:1];badge.style.color='var(--fm-'+s[2]+')';
      document.querySelector('.card-progress-fill').style.width=s[3]+'%';
      document.getElementById('sample-percent').textContent=s[3]+'%';
      document.getElementById('sample-percent').hidden=['offline','error','idle'].includes(state);
      document.querySelector('.pcd-bar').hidden=['offline','error','idle','ready'].includes(state);
      document.querySelector('.pcd-temps').hidden=state==='offline';
      document.getElementById('sample-time').textContent=state==='printing'?(ru?'1 ч 24 мин осталось':'1 h 24 min left'):state==='error'?(ru?'Проверьте принтер':'Check the printer'):state==='offline'?(ru?'Нет соединения':'No connection'):state==='ready'?(ru?'Задание завершено':'Job complete'):'';
      document.getElementById('sample-printer-name').textContent=d.longNames?(ru?'Принтер мастерской · длинное название устройства и проекта':'Workshop printer · a long device and project name'):'Bambu P2S';
      // Playback speed belongs to the preview document, never to the theme.
      document.getAnimations?.().forEach(a=>{a.playbackRate=speed;});
    }
    parent.postMessage({type:'fm-appearance-sample-rendered',ok,ambientError:getRuntimeState().ambientError},origin);
  }
  if(targets.has(d.highlight)){document.querySelectorAll('.sample-highlight').forEach(n=>n.classList.remove('sample-highlight'));const n=document.querySelector(d.highlight==='dashboard'?'.pc-dash':'[data-sample="'+d.highlight+'"]');if(n){n.classList.add('sample-highlight');clearTimeout(timer);timer=setTimeout(()=>n.classList.remove('sample-highlight'),1200);}}
});
parent.postMessage({type:'fm-appearance-sample-ready'},origin);

// Fit the frame to its real content. Never conceal overflowing content behind a
// disabled scrollbar; recompute after palette, typography, font and width changes.
let lastHeight=0;
function reportHeight(){
 const height=Math.ceil(document.body.getBoundingClientRect().height)+2;
 if(height!==lastHeight){lastHeight=height;parent.postMessage({type:'fm-appearance-sample-height',height},origin);}
}
const sizeObserver=new ResizeObserver(reportHeight);
sizeObserver.observe(document.body);
document.fonts?.ready.then(reportHeight);
window.addEventListener('pagehide',()=>sizeObserver.disconnect(),{once:true});
reportHeight();
