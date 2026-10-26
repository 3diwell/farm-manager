// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Визуальный адаптер: исходный rect и значение прогресса остаются под управлением FM.
// Свой путь повторяет фактические четыре угла карточки, а не фиксированный rx ядра.
const OWN = 'fm-appearance-progress-outline';
const SOURCE = 'data-fm-appearance-progress-source';
const SELECTOR = '.printer-card .grid-ring';
const scope = 'html[data-fm-appearance-active="1"]';
export const printerProgressCss = `
${scope} .grid-ring[${SOURCE}]{opacity:0!important;}
${scope} .${OWN}{position:absolute!important;left:var(--fp-left)!important;top:var(--fp-top)!important;width:var(--fp-width)!important;height:var(--fp-height)!important;pointer-events:none!important;overflow:visible!important;z-index:3;filter:none!important;animation:none!important;}
${scope} .${OWN} path{fill:none!important;stroke:currentColor!important;stroke-width:1.6px!important;stroke-linecap:butt!important;filter:none!important;animation:none!important;opacity:.9;}
`;
const num = value => parseFloat(value) || 0;

// Нормализация соответствует CSS: противоположные радиусы не могут перекрыться.
export function outlinePath(width, height, corners, inset = .8) {
  let r = corners.map(pair => pair.map(v => Math.max(0, v)));
  const ratios = [1, width / (r[0][0]+r[1][0] || 1), width / (r[3][0]+r[2][0] || 1),
    height / (r[0][1]+r[3][1] || 1), height / (r[1][1]+r[2][1] || 1)];
  const scale = Math.min(...ratios);
  r = r.map(pair => pair.map(v => Math.max(0, v * scale - inset)));
  const [tl,tr,br,bl]=r, x=inset,y=inset,right=width-inset,bottom=height-inset;
  const arc=(radius,endX,endY)=>radius[0]&&radius[1]?`A ${radius[0]} ${radius[1]} 0 0 1 ${endX} ${endY}`:`L ${endX} ${endY}`;
  // Начало в середине прямого участка сверху; полная дуга замыкается без зазора.
  const start=(x+tl[0]+right-tr[0])/2;
  return `M ${start} ${y} H ${right-tr[0]} ${arc(tr,right,y+tr[1])} V ${bottom-br[1]} ${arc(br,right-br[0],bottom)} H ${x+bl[0]} ${arc(bl,x,bottom-bl[1])} V ${y+tl[1]} ${arc(tl,x+tl[0],y)} Z`;
}

function geometry(card) {
  const s=getComputedStyle(card);
  const left=num(s.borderLeftWidth),top=num(s.borderTopWidth);
  const bx=left+num(s.borderRightWidth),by=top+num(s.borderBottomWidth);
  const width=num(s.width)+(s.boxSizing==='border-box'?0:bx+num(s.paddingLeft)+num(s.paddingRight));
  const height=num(s.height)+(s.boxSizing==='border-box'?0:by+num(s.paddingTop)+num(s.paddingBottom));
  const radius=value=>{const parts=value.split(/\s+/);return [parts[0],parts[1]||parts[0]].map((v,i)=>v.endsWith('%')?num(v)*(i?height:width)/100:num(v));};
  return {width,height,left,top,corners:[s.borderTopLeftRadius,s.borderTopRightRadius,s.borderBottomRightRadius,s.borderBottomLeftRadius].map(radius)};
}
function attr(node,key,value){if(node.getAttribute(key)!==String(value))node.setAttribute(key,String(value));}

export function createPrinterProgress() {
  const entries=new Map(); let frame=0,disposed=false;
  const schedule=()=>{if(!disposed&&!frame)frame=requestAnimationFrame(sync);};
  const resize=new ResizeObserver(schedule);
  function remove(svg,entry){resize.unobserve(entry.card);entry.overlay.remove();svg.removeAttribute(SOURCE);entries.delete(svg);}
  function sync(){
    frame=0;if(disposed)return;
    for(const [svg,entry] of entries){
      if(!svg.isConnected||!svg.matches(SELECTOR)||svg.closest('.printer-card')!==entry.card||svg.querySelector('rect')!==entry.rect)remove(svg,entry);
    }
    for(const svg of document.querySelectorAll(SELECTOR)){
      if(svg.closest('#fm-appearance-editor'))continue;
      const rect=svg.querySelector('rect'),card=svg.closest('.printer-card');
      if(!rect||!card)continue;
      let entry=entries.get(svg);
      if(!entry){
        const overlay=document.createElementNS('http://www.w3.org/2000/svg','svg');
        const path=document.createElementNS(overlay.namespaceURI,'path');
        overlay.classList.add(OWN);overlay.setAttribute('aria-hidden','true');overlay.setAttribute('focusable','false');
        path.setAttribute('pathLength','100');overlay.appendChild(path);card.appendChild(overlay);
        entry={card,rect,overlay,path};entries.set(svg,entry);resize.observe(card);
      }
      const g=geometry(card),{overlay,path}=entry;
      if(g.width<=1.6||g.height<=1.6)continue;
      if(!overlay.isConnected)card.appendChild(overlay);
      attr(overlay,'viewBox',`0 0 ${g.width} ${g.height}`);
      const sourceStyle=getComputedStyle(rect),svgStyle=getComputedStyle(svg);
      // Берём целевое значение FM, а не промежуточный кадр CSS-перехода старой линии.
      const dash=rect.style.strokeDasharray||rect.getAttribute('stroke-dasharray')||sourceStyle.strokeDasharray;
      const length=num(rect.getAttribute('pathLength'))||100;
      const fraction=dash==='none'?100:Math.max(0,Math.min(100,num(dash)*100/length));
      attr(path,'d',outlinePath(g.width,g.height,g.corners));
      attr(path,'stroke-dasharray',fraction>=100?'none':`${fraction} 100`);
      const css=`--fp-left:${-g.left}px;--fp-top:${-g.top}px;--fp-width:${g.width}px;--fp-height:${g.height}px;color:${sourceStyle.stroke==='none'?sourceStyle.color:sourceStyle.stroke};display:${svgStyle.display==='none'?'none':'block'};visibility:${fraction===0||sourceStyle.visibility==='hidden'?'hidden':'visible'};`;
      attr(overlay,'style',css);attr(svg,SOURCE,'1');
    }
  }
  const relevantNode=n=>n.nodeType===1&&!n.closest?.('.'+OWN)&&
    (n.matches('style,.printer-card,.grid-ring')||n.querySelector('.printer-card,.grid-ring'));
  const observer=new MutationObserver(records=>{
    if(records.some(r=>{
      if(r.target.closest?.('.'+OWN))return false;
      if(r.type==='characterData')return r.target.parentElement?.tagName==='STYLE';
      if(r.type==='childList')return r.target.tagName==='STYLE'||r.target.matches?.('.grid-ring')||[...r.addedNodes,...r.removedNodes].some(relevantNode);
      return r.target.matches?.('.printer-card,.grid-ring,.grid-ring rect')||[...entries.values()].some(e=>r.target.contains(e.card));
    }))schedule();
  });
  observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class','style','stroke-dasharray','pathLength','data-theme']});
  window.addEventListener('resize',schedule);
  // Завершившийся переход формы также должен оставить точное совпадение углов.
  document.addEventListener('transitionend',schedule);
  sync();
  return {update:schedule,dispose(){
    disposed=true;if(frame)cancelAnimationFrame(frame);observer.disconnect();resize.disconnect();
    window.removeEventListener('resize',schedule);document.removeEventListener('transitionend',schedule);
    for(const [svg,entry] of entries)remove(svg,entry);
  }};
}
