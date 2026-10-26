// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Только оформление существующего Dashboard. Данные и обработчики FM не заменяются.
// Собственные слои удаляются при отключении; к принтерам и API адаптер не обращается.
import { contrastRatio } from './theme-validator.js';
import { HOVER_GLINT_CLASS } from './theme-schema.js';
const ROOT='html[data-fm-appearance-active="1"]';
const CARD='.printer-card.pc-dashcard';
const ACTIVE='data-fm-dash-active';
const OWN='fm-ap-dash-own';
const NS='http://www.w3.org/2000/svg';
const prefix='--fm-ap-dash-';
const vars=['base','water','text','state','heating','cooling','percent-size','time-size','period'];
export function dashboardCss(t) {
  if(!t.dashboard.enabled)return '';
  const c=ROOT+' '+CARD+'['+ACTIVE+']';
  return `
${c}{background:var(--fm-ap-dash-base)!important;overflow:hidden!important;}
${c}>.pc-dash{position:relative;flex:1;min-width:0;}
${c} .pcd-top{padding-right:calc(var(--fm-ap-dash-percent-size) * 2.7 + 6px);flex-wrap:wrap;min-height:calc(var(--fm-ap-dash-percent-size) * 1.2);}
${c}[data-fm-dash-percent="false"] .pcd-top{padding-right:0;}
${c} .pcd-name{flex:1 1 40px;}
${c}[data-fm-dash-model="false"] .pcd-model{display:none!important;}
${c} .pcd-line>b,${c} .fm-ap-dash-percent{position:absolute;top:0;right:0;font-size:var(--fm-ap-dash-percent-size)!important;line-height:1.15;font-weight:650;letter-spacing:-.03em;color:var(--fm-text-primary)!important;font-variant-numeric:tabular-nums;pointer-events:none;}
${c} .pcd-line{flex-wrap:wrap;}
${c} .pcd-line>[data-fm-dash-time-source]{display:none!important;}
${c} .fm-ap-dash-time{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 5px;min-width:0;width:100%;color:var(--fm-text-primary);font-variant-numeric:tabular-nums;}
${c} .fm-ap-dash-time>strong{font-size:var(--fm-ap-dash-time-size)!important;line-height:1.25;font-weight:650;white-space:normal;overflow-wrap:anywhere;}
${c} .fm-ap-dash-time>span{font-size:14px!important;line-height:1.4;white-space:normal;overflow:visible;}
${c} .pcd-file,${c} .pcd-line,${c} .pcd-model{color:var(--fm-ap-dash-text)!important;}
/* 0.17.4: подпись состояния своего цвета, но читаемая на заливке (>= 4.5:1, как остальной текст карточки) */
${c}.pcd-error .pcd-msg,${c}.pcd-done .pcd-msg,${c}.pcd-paused .pcd-st{color:var(--fm-ap-dash-state)!important;}
${c} .pcd-temps{flex-wrap:wrap;gap:4px 8px;}
${c}[data-fm-dash-thermal="true"] .pcd-temps>span{color:var(--fm-ap-dash-text)!important;}
/* 0.17.4: включённый нагреватель (класс .hot ядра) остаётся подсвеченным цветом нагрева, как без модуля */
${c}[data-fm-dash-thermal="true"] .pcd-temps>span.hot{color:var(--fm-ap-dash-heating)!important;}
${c}[data-fm-dash-thermal="true"] .pcd-temps>span[data-fm-dash-trend="heating"]{color:var(--fm-ap-dash-heating)!important;}
${c}[data-fm-dash-thermal="true"] .pcd-temps>span[data-fm-dash-trend="cooling"]{color:var(--fm-ap-dash-cooling)!important;}
${c}[data-fm-dash-thermal="true"] .pcd-temps>[data-fm-dash-trend="heating"]::after{content:"↑";}
${c}[data-fm-dash-thermal="true"] .pcd-temps>[data-fm-dash-trend="cooling"]::after{content:"↓";}
${c}[data-fm-dash-water="true"] .pcd-bar{display:none!important;}
/* 0.17.4: полоска выбранного принтера (ui3.css, .ui3-sel::before) видна поверх заливки */
${c}.ui3-sel::before{z-index:1;}
${c}>.fm-ap-dash-water{position:absolute;inset:0;overflow:hidden;border-radius:inherit;pointer-events:none!important;}
${c} .fm-ap-dash-wave{position:absolute;display:block;left:0;bottom:0;width:300%!important;min-width:300%;max-width:none!important;height:100%!important;max-height:none;fill:var(--fm-ap-dash-water);pointer-events:none!important;animation:fm-ap-dash-drift var(--fm-ap-dash-period) linear infinite;transform-box:fill-box;}
${c} .fm-ap-dash-wave>path{fill:var(--fm-ap-dash-water)!important;stroke:none!important;}
${c}[data-fm-dash-moving="false"] .fm-ap-dash-wave,html[data-fm-appearance-paused] .fm-ap-dash-wave{animation-play-state:paused;}
@keyframes fm-ap-dash-drift{from{transform:translateX(0)}to{transform:translateX(-33.3333333333%)}}
@media(prefers-reduced-motion:reduce){${c} .fm-ap-dash-wave{animation:none!important;}}
${c} .fm-ap-dash-own[hidden]{display:none!important;}
`;
}
function mix(a,b,t){const read=h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)),x=read(a),y=read(b);return '#'+x.map((v,i)=>Math.round(v+(y[i]-v)*t).toString(16).padStart(2,'0')).join('');}
function ink(color,backgrounds){
  const score=c=>Math.min(...backgrounds.map(b=>contrastRatio(c,b)));
  const toward=score('#ffffff')>score('#000000')?'#ffffff':'#000000';
  let result=color;for(let i=0;i<48&&score(result)<4.5;i++)result=mix(result,toward,.12);return result;
}
function tint(color,palette,amount){
  let result=mix(color,palette.surfaceCard,amount);
  for(let i=0;i<48&&contrastRatio(result,palette.textPrimary)<4.5;i++)result=mix(result,palette.surfaceCard,.15);
  return result;
}
export function dashboardState(card){
  return ['offline','error','paused','done','print'].find(s=>card.classList.contains('pcd-'+s))||'idle';
}
export function dashboardPercent(state,text){
  if(state==='done')return 100;
  if(!['print','paused'].includes(state))return 0;
  const match=String(text||'').trim().match(/^(-?\d+(?:\.\d+)?)\s*%$/);
  return match?Math.max(0,Math.min(100,Number(match[1]))):0;
}
export function splitDashboardTime(text){
  const match=String(text||'').trim().match(/^(.+?\d.*?)\s+(осталось|left)$/i);
  return match?{value:match[1],label:match[2]}:null;
}
// Один непрерывный путь: поверхность и заливка не могут разойтись на стыке.
// Три одинаковых периода; сдвиг ровно на один период не меняет поверхность.
export function dashboardWave(height,percent,amplitude){
  const y=height*(1-percent/100),a=Math.max(0,Math.min(amplitude,y,height-y)),k=a*Math.PI/6;
  const n=v=>Number(v.toFixed(5));let d='M0 '+n(y);
  for(let x=0;x<600;x+=200){
    d+=' C'+n(x+50/3)+' '+n(y-k)+' '+n(x+100/3)+' '+n(y-a)+' '+(x+50)+' '+n(y-a);
    d+=' C'+n(x+200/3)+' '+n(y-a)+' '+n(x+250/3)+' '+n(y-k)+' '+(x+100)+' '+n(y);
    d+=' C'+n(x+350/3)+' '+n(y+k)+' '+n(x+400/3)+' '+n(y+a)+' '+(x+150)+' '+n(y+a);
    d+=' C'+n(x+500/3)+' '+n(y+a)+' '+n(x+550/3)+' '+n(y+k)+' '+(x+200)+' '+n(y);
  }
  return d+' V'+height+' H0 Z';
}
// Целевую температуру не используем: нагреватель может быть включён при остывании.
// 0.17.4: показание приходит округлённым до градуса (ядро: Math.round), и неизменная температура около
// x.5 прыгает 219↔220 — прежде это давало мигание ↑/↓. Тренд — отход от опорного значения на 2° и больше;
// опора переезжает вместе с трендом, через 12 с без такого отхода тренд гаснет.
export function temperatureTrend(previous,value,now){
  if(!Number.isFinite(value))return null;
  if(!previous||now-previous.sampleAt>20000)return {value,ref:value,sampleAt:now,changedAt:now,trend:'stable'};
  const ref=Number.isFinite(previous.ref)?previous.ref:previous.value,delta=value-ref;
  if(Math.abs(delta)>=2)return {value,ref:value,sampleAt:now,changedAt:now,trend:delta>0?'heating':'cooling'};
  return {value,ref,sampleAt:now,changedAt:previous.changedAt,trend:now-previous.changedAt>=12000?'stable':previous.trend};
}
const attr=(node,key,value)=>{const text=String(value);if(node.getAttribute(key)!==text)node.setAttribute(key,text);};
const text=(node,value)=>{if(node.textContent!==value)node.textContent=value;};
const variable=(node,key,value)=>{if(node.style.getPropertyValue(prefix+key)!==value)node.style.setProperty(prefix+key,value);};
function own(tag,cls){const node=document.createElement(tag);node.className=OWN+' '+cls;return node;}
export function createDashboardCards(){
  const entries=new Map();let theme=null,frame=0,disposed=false,forcedPause=false;
  const schedule=()=>{if(!disposed&&!frame&&!document.hidden)frame=requestAnimationFrame(sync);};
  const resize=typeof ResizeObserver==='function'?new ResizeObserver(schedule):null;
  function remove(card,e){
    resize?.unobserve(card);e.layer.remove();e.percent.remove();e.time?.remove();e.timeSource?.removeAttribute('data-fm-dash-time-source');
    e.temperatures.forEach((_,node)=>node.removeAttribute('data-fm-dash-trend'));
    for(const key of ['active','percent','model','thermal','water','moving'])card.removeAttribute('data-fm-dash-'+key);
    vars.forEach(key=>card.style.removeProperty(prefix+key));entries.delete(card);
  }
  function make(card,dash){
    const layer=own('div','fm-ap-dash-water');layer.setAttribute('aria-hidden','true');
    const svg=document.createElementNS(NS,'svg'),path=document.createElementNS(NS,'path');
    svg.classList.add('fm-ap-dash-wave');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('focusable','false');svg.appendChild(path);layer.appendChild(svg);
    card.insertBefore(layer,card.firstChild);
    const percent=own('b','fm-ap-dash-percent');dash.appendChild(percent);
    const e={pid:card.getAttribute('data-pid'),dash,layer,svg,path,percent,temperatures:new Map(),time:null,timeSource:null};
    entries.set(card,e);resize?.observe(card);return e;
  }
  function timeLabel(e,state){
    const source=state==='print'?e.dash.querySelector('.pcd-line>span:not([class~="'+OWN+'"])'):null;
    const parts=source?splitDashboardTime(source.textContent):null;
    if(e.timeSource!==source||!parts||!e.time?.isConnected){
      e.time?.remove();e.time=null;e.timeSource?.removeAttribute('data-fm-dash-time-source');e.timeSource=null;
    }
    if(!parts)return;
    if(!e.time){
      e.time=own('div','fm-ap-dash-time');
      e.timeValue=document.createElement('strong');e.timeLabel=document.createElement('span');
      e.time.append(e.timeValue,e.timeLabel);source.parentElement.appendChild(e.time);
      e.timeSource=source;attr(source,'data-fm-dash-time-source','1');
    }
    text(e.timeValue,parts.value);text(e.timeLabel,parts.label);
  }
  function sync(){
    frame=0;if(disposed||!theme)return;
    observer.disconnect();
    try{
      for(const [card,e] of entries)if(!card.isConnected||!card.matches(CARD)||card.querySelector('.pc-dash')!==e.dash||card.getAttribute('data-pid')!==e.pid)remove(card,e);
      const d=theme.dashboard,p=theme[document.documentElement.dataset.theme==='light'?'light':'dark'];
      const now=performance.now(),reduced=forcedPause||theme.interface.reduceMotion||theme.interface.performanceMode==='economy'||window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      for(const card of document.querySelectorAll(CARD)){
        if(card.closest('#fm-appearance-editor'))continue;
        const dash=card.querySelector('.pc-dash');if(!dash)continue;
        const e=entries.get(card)||make(card,dash),st=dashboardState(card);
        if(!e.layer.isConnected)card.insertBefore(e.layer,card.firstChild);
        const originalPercent=dash.querySelector('.pcd-line>b');
        const value=dashboardPercent(st,dash.querySelector('.pcd-bar>i')?.style.width||originalPercent?.textContent);
        const show=['print','paused','done'].includes(st),filled=d.water&&show&&value>0;
        const source=st==='paused'?d.pause:mix(d.blue,d.green,value/100);
        const stateColor=st==='error'?d.error:st==='idle'?d.idle:st==='paused'?d.pause:st==='done'?d.green:st==='print'?d.blue:p.surfaceCard;
        const base=tint(stateColor,p,st==='print'?.88:.7),water=tint(source,p,.42);
        const backgrounds=filled?[base,water]:[base];
        for(const [key,val] of Object.entries({base,water,text:ink(p.textSecondary,backgrounds),state:ink(st==='error'?d.error:st==='paused'?d.pause:st==='done'?d.green:p.textSecondary,backgrounds),heating:ink(d.heating,backgrounds),cooling:ink(d.cooling,backgrounds),'percent-size':d.percentSize+'px','time-size':d.timeSize+'px',period:d.wavePeriod+'s'}))variable(card,key,val);
        attr(card,ACTIVE,'1');attr(card,'data-fm-dash-percent',show);attr(card,'data-fm-dash-model',d.showModel);attr(card,'data-fm-dash-thermal',d.temperatureColors);
        attr(card,'data-fm-dash-water',d.water&&show);attr(card,'data-fm-dash-moving',d.motion&&!reduced&&st==='print'&&value>0&&value<100);
        e.layer.hidden=!filled;e.percent.hidden=st!=='done'||!!originalPercent;text(e.percent,'100%');
        if(!e.percent.isConnected)dash.appendChild(e.percent);
        const height=card.clientHeight||1;
        attr(e.svg,'viewBox','0 0 600 '+height);attr(e.path,'d',dashboardWave(height,value,d.waveHeight));
        timeLabel(e,st);
        const current=new Set(st==='offline'?[]:dash.querySelectorAll('.pcd-temps>span'));
        for(const [node] of e.temperatures)if(!current.has(node)){node.removeAttribute('data-fm-dash-trend');e.temperatures.delete(node);}
        for(const node of current){
          const match=node.textContent.match(/(-?\d+(?:[.,]\d+)?)\s*°/),value=match?Number(match[1].replace(',','.')):NaN;
          const next=temperatureTrend(e.temperatures.get(node),value,now);
          if(next)e.temperatures.set(node,next);else e.temperatures.delete(node);
          attr(node,'data-fm-dash-trend',next?.trend||'stable');
        }
      }
    }finally{if(!disposed)observe();}
  }
  const observer=new MutationObserver(records=>{
    if(records.some(r=>{
      const target=r.target.nodeType===1?r.target:r.target.parentElement;
      // 0.17.4: блик при наведении двигает свой span каждый кадр — это не изменение карточки
      // (так же отсекает его glass-layer.js); иначе пока мышь на карточке, пересчёт всех карточек ~30 раз/с.
      if(target?.closest('.'+OWN+',.'+HOVER_GLINT_CLASS))return false;
      if(entries.has(target)||target?.closest(CARD)||target===document.documentElement)return true;
      return r.type==='childList'&&[...r.addedNodes,...r.removedNodes].some(n=>n.nodeType===1&&!n.classList.contains(OWN)&&(n.matches(CARD)||n.querySelector(CARD)));
    }))schedule();
  });
  function observe(){observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class','style','data-pid','data-theme']});}
  observe();
  // Один таймер на Dashboard: погасить стрелку после стабилизации, без анимации в JS.
  const timer=window.setInterval(()=>{if(entries.size)schedule();},4000);
  document.addEventListener('visibilitychange',schedule);window.addEventListener('resize',schedule);
  return {
    update(value,paused=false){theme=value;forcedPause=paused;schedule();},
    dispose(){disposed=true;if(frame)cancelAnimationFrame(frame);observer.disconnect();resize?.disconnect();window.clearInterval(timer);
      document.removeEventListener('visibilitychange',schedule);window.removeEventListener('resize',schedule);
      for(const [card,e] of entries)remove(card,e);
    }
  };
}
