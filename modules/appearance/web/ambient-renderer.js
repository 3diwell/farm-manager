// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { paintAmbient } from './ambient-fields.js';
export const PROCEDURAL_BACKGROUNDS=['fluid','aurora','mist'];
const rgb=value=>[1,3,5].map(i=>parseInt(value.slice(i,i+2),16));
export function ambientOptions(theme,mode='dark'){
 const e=theme.effects,mixed=e.backgroundAnimationStyle==='mixed';
 const kind=mixed?e.backgroundMixedStyle:e.backgroundAnimationStyle;
 if(e.animatedBackground==='off'||!PROCEDURAL_BACKGROUNDS.includes(kind)||e.backgroundFlowOpacity<=0||mixed&&e.backgroundFlowMix<=0)return null;
 return {kind,primary:rgb(e.backgroundFlowUseThemeColors?theme[mode==='light'?'light':'dark'].accent:e.backgroundFlowPrimary),secondary:rgb(e.backgroundFlowUseThemeColors?e.secondaryAccent:e.backgroundFlowSecondary),opacity:e.backgroundFlowOpacity*(mixed?.76*e.backgroundFlowMix:1)*(e.animatedBackground==='medium'?1.28:1),softness:e.backgroundFlowBlur,scale:e.backgroundFlowScale,light:mode==='light',speed:.35+e.backgroundFlowSpeed*2,economy:theme.interface.performanceMode==='economy'};
}
// One bounded canvas per module instance. Only owned nodes are mutated.
export function createAmbientRenderer(container){
 const canvas=document.createElement('canvas');canvas.className='fm-appearance-ambient-canvas';canvas.setAttribute('aria-hidden','true');
 let ctx;try{ctx=canvas.getContext('2d',{alpha:true});}catch(_){return null;}
 if(!ctx)return null;
 container.appendChild(canvas);
 let options=null,signature='',buffer=null,time=19,last=0,lastDraw=0,frame=null,paused=true,destroyed=false,budgetScale=1,slowFrames=0,speedMultiplier=1,resizePending=false;
 const now=()=>typeof performance!=='undefined'?performance.now():Date.now();
 function resize(){
  if(destroyed||!options)return;
  const box=container.getBoundingClientRect(),ratio=Math.max(.2,Math.min(5,(box.width||window.innerWidth||320)/(box.height||window.innerHeight||240)));
  const pixels=(options.economy?14000:34000)*budgetScale;
  const w=Math.max(64,Math.round(Math.sqrt(pixels*ratio))),h=Math.max(64,Math.round(pixels/w));
  if(canvas.width!==w||canvas.height!==h||!buffer){canvas.width=w;canvas.height=h;buffer=ctx.createImageData(w,h);}
 }
 function draw(){
  if(destroyed||!options||!buffer)return;
  if(resizePending){resizePending=false;resize();}
  const start=now();paintAmbient(buffer,options,time);ctx.putImageData(buffer,0,0);
  // Lower the pixel budget after sustained expensive frames, never increase work automatically.
  if(now()-start>12){slowFrames++;if(slowFrames>=8&&budgetScale>.42){budgetScale*=.72;slowFrames=0;resizePending=true;}}else slowFrames=Math.max(0,slowFrames-1);
 }
 function tick(stamp){
  frame=null;if(destroyed)return;if(!canvas.isConnected){dispose();return;}
  if(paused||document.hidden){last=0;return;}
  if(last)time+=Math.min((stamp-last)/1000,.15)*options.speed*speedMultiplier;
  last=stamp;
  if(stamp-lastDraw>=1000/(options.economy?12:20)){draw();lastDraw=stamp;}
  frame=window.requestAnimationFrame(tick);
 }
 function schedule(){
  if(destroyed)return;
  if(paused||document.hidden){if(frame!==null)window.cancelAnimationFrame(frame);frame=null;last=0;}
  else if(frame===null){last=0;frame=window.requestAnimationFrame(tick);}
 }
 function resized(){if(destroyed)return;resize();if(!document.hidden)draw();}
 const observer=typeof ResizeObserver!=='undefined'?new ResizeObserver(resized):null;
 if(observer)observer.observe(container);else window.addEventListener('resize',resized);
 function update(next,stop=false,multiplier=1){
  if(destroyed)return;
  const key=JSON.stringify(next),changed=signature!==key;
  signature=key;options=next;paused=stop;speedMultiplier=multiplier===3?3:1;
  if(changed||!buffer){resize();draw();}
  schedule();
 }
 function dispose(){
  if(destroyed)return;destroyed=true;
  if(frame!==null)window.cancelAnimationFrame(frame);frame=null;
  observer?.disconnect();if(!observer)window.removeEventListener('resize',resized);
  canvas.remove();buffer=null;options=null;
 }
 return {update,dispose};
}
