// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Optical backdrop processing is confined to module-owned nodes in the ambient
// layer. Core targets are read for geometry; never mutated or wrapped.
// SVG displacement: https://www.w3.org/TR/filter-effects-1/#feDisplacementMapElement
const NS='http://www.w3.org/2000/svg';
let serial=0;
export function lensVector(x,y,w,h,r){
 r=Math.max(1,Math.min(r,w/2,h/2));
 const qx=Math.abs(x-w/2)-(w/2-r),qy=Math.abs(y-h/2)-(h/2-r);
 const ax=Math.max(qx,0),ay=Math.max(qy,0),len=Math.hypot(ax,ay);
 const distance=len+Math.min(Math.max(qx,qy),0)-r;
 const band=Math.max(6,Math.min(32,r*1.6));
 const strength=distance>0?0:Math.pow(Math.max(0,1+distance/band),2);
 let nx=0,ny=0;
 if(len>0){nx=ax/len;ny=ay/len;}else if(qx>qy)nx=1;else ny=1;
 return [nx*Math.sign(x-w/2)*strength,ny*Math.sign(y-h/2)*strength];
}
export function glassRects(targets,viewport,limit=25){
 const result=[];let area=0;
 for(const target of targets){
  const b=target.getBoundingClientRect();
  if(!Number.isFinite(b.left)||!Number.isFinite(b.top)||b.width<16||b.height<16||b.bottom<=0||b.right<=0||b.left>=viewport.width||b.top>=viewport.height)continue;
  // Large full-page shells are intentionally left as ordinary translucent surfaces.
  if(b.width*b.height>viewport.width*viewport.height*.65||area+b.width*b.height>viewport.width*viewport.height*1.5)continue;
  result.push({target,box:b});area+=b.width*b.height;if(result.length>=limit)break;
 }
 return result;
}
function node(tag,attrs={}){const n=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;}
function normalMap(w,h,r){
 const scale=Math.min(1,160/Math.max(w,h)),cw=Math.max(8,Math.round(w*scale)),ch=Math.max(8,Math.round(h*scale));
 const canvas=document.createElement('canvas');canvas.width=cw;canvas.height=ch;
 const ctx=canvas.getContext('2d');if(!ctx||typeof canvas.toDataURL!=='function')return null;
 const data=ctx.createImageData(cw,ch);
 for(let y=0;y<ch;y++)for(let x=0;x<cw;x++){
  const [nx,ny]=lensVector((x+.5)/scale,(y+.5)/scale,w,h,r),i=(y*cw+x)*4;
  data.data[i]=Math.round(127.5+nx*127.5);data.data[i+1]=Math.round(127.5+ny*127.5);data.data[i+2]=128;data.data[i+3]=255;
 }
 ctx.putImageData(data,0,0);return canvas.toDataURL('image/png');
}
export function createGlassLayer(ambient){
 if(!ambient)return null;
 const root=document.createElement('div');root.className='fm-appearance-optical-layer';root.setAttribute('aria-hidden','true');
 Object.assign(root.style,{position:'absolute',inset:'0',pointerEvents:'none'});ambient.appendChild(root);
 // getBoundingClientRect returns viewport pixels, while these owned nodes use
 // CSS pixels under FM's html zoom. Measure that coordinate space, including
 // the negative ambient inset, instead of applying zoom a second time.
 const probe=document.createElement('span');probe.className='fm-appearance-optical-probe';
 Object.assign(probe.style,{position:'absolute',display:'block',left:'0',top:'0',width:'100px',height:'100px',padding:'0',margin:'0',border:'0',boxSizing:'border-box',visibility:'hidden',pointerEvents:'none'});root.appendChild(probe);
 const svg=node('svg',{width:0,height:0,'aria-hidden':'true'});Object.assign(svg.style,{position:'absolute',pointerEvents:'none'});const defs=node('defs');svg.appendChild(defs);root.appendChild(svg);
 let theme=null,disposed=false,frame=null,timer=null,pool=[];
 const supported=typeof CSS!=='undefined'&&CSS.supports('backdrop-filter','blur(1px)');
 function make(){
  const tile=document.createElement('div'),frost=document.createElement('div'),lens=document.createElement('div');
  Object.assign(tile.style,{position:'absolute',pointerEvents:'none',overflow:'hidden'});
  for(const n of [frost,lens]){Object.assign(n.style,{position:'absolute',inset:'0',pointerEvents:'none',borderRadius:'inherit'});tile.appendChild(n);}
  const id='fm-ap-lens-'+(++serial),filter=node('filter',{id,filterUnits:'userSpaceOnUse',primitiveUnits:'userSpaceOnUse',x:0,y:0,width:1,height:1,'color-interpolation-filters':'sRGB'});
  const map=node('feImage',{result:'normal',x:'0',y:'0',width:'100%',height:'100%',preserveAspectRatio:'none'});
  const displacement=node('feDisplacementMap',{in:'SourceGraphic',in2:'normal',xChannelSelector:'R',yChannelSelector:'G',scale:0});
  filter.appendChild(map);filter.appendChild(displacement);defs.appendChild(filter);root.appendChild(tile);
  return {tile,frost,lens,filter,map,displacement,id,key:''};
 }
 function remove(item){item.tile.remove();item.filter.remove();}
 function layout(){
  frame=null;if(disposed||!theme||document.hidden)return;
  if(!root.isConnected){dispose();return;}
  const viewport={width:window.innerWidth||document.documentElement.clientWidth||320,height:window.innerHeight||document.documentElement.clientHeight||240};
  const cards=Array.from(document.querySelectorAll('.printer-card,.plan-cell'));
  const panels=Array.from(document.querySelectorAll('.glass-panel,.fm-module')).filter(n=>!n.querySelector('.printer-card,.plan-cell,.glass-panel,.fm-module'));
  const candidates=[...cards,...panels].filter(n=>!n.closest('#fm-appearance-editor'));
  const rects=glassRects(candidates,viewport,theme.interface.performanceMode==='economy'?8:25),origin=probe.getBoundingClientRect(),e=theme.effects;
  const sx=origin.width/100,sy=origin.height/100;
  if(!Number.isFinite(sx)||!Number.isFinite(sy)||sx<=0||sy<=0){pool.forEach(item=>item.tile.style.display='none');return;}
  while(pool.length>rects.length)remove(pool.pop());
  rects.forEach(({target,box:b},i)=>{
   const item=pool[i]||(pool[i]=make()),computed=getComputedStyle(target);
   const width=b.width/sx,height=b.height/sy;
   // A card may also live inside .zoom-wrap. Scale its corner geometry into
   // the same CSS coordinate space as the lens, not just its bounding box.
   const tx=b.width/Math.max(1,target.offsetWidth)/sx,ty=b.height/Math.max(1,target.offsetHeight)/sy;
   const corners=['borderTopLeftRadius','borderTopRightRadius','borderBottomRightRadius','borderBottomLeftRadius'];
   const radii=corners.map(key=>{const parts=computed[key].split(/\s+/),a=parts[0],b=parts[1]||a;return [Math.min(width/2,a.endsWith('%')?parseFloat(a)*width/100:(parseFloat(a)||0)*tx),Math.min(height/2,b.endsWith('%')?parseFloat(b)*height/100:(parseFloat(b)||0)*ty)];});
   const radius=Math.min(radii[0][0],radii[0][1]);
   for(const n of [item.filter,item.map]){n.setAttribute('width',String(width));n.setAttribute('height',String(height));}
   // Match scroll clipping without changing the scrolling element.
   let left=Math.max(0,b.left),top=Math.max(0,b.top),right=Math.min(viewport.width,b.right),bottom=Math.min(viewport.height,b.bottom);
   for(let p=target.parentElement;p&&p!==document.body;p=p.parentElement){
    const cs=getComputedStyle(p),pb=p.getBoundingClientRect();
    if(/hidden|clip|auto|scroll/.test(cs.overflowX||cs.overflow||'')){left=Math.max(left,pb.left);right=Math.min(right,pb.right);}
    if(/hidden|clip|auto|scroll/.test(cs.overflowY||cs.overflow||'')){top=Math.max(top,pb.top);bottom=Math.min(bottom,pb.bottom);}
   }
   item.tile.style.display=right<=left||bottom<=top||computed.visibility==='hidden'||computed.opacity==='0'?'none':'block';
   // Overflow clipping does not establish a backdrop root. A clip-path here
   // would isolate the filters from the background they need to sample.
   Object.assign(item.tile.style,{left:((left-origin.left)/sx)+'px',top:((top-origin.top)/sy)+'px',width:(Math.max(0,right-left)/sx)+'px',height:(Math.max(0,bottom-top)/sy)+'px'});
   for(const n of [item.frost,item.lens]){
    Object.assign(n.style,{inset:'auto',left:((b.left-left)/sx)+'px',top:((b.top-top)/sy)+'px',width:width+'px',height:height+'px'});
    corners.forEach((key,j)=>{n.style[key]=radii[j][0]+'px '+radii[j][1]+'px';});
   }
   const blur=Math.min(e.glassBlur,theme.interface.performanceMode==='economy'?6:16);
   item.frost.style.backdropFilter=supported?`blur(${blur}px)`:'none';
   item.frost.style.background=theme.interface.highContrast?'transparent':`rgba(255,255,255,${e.glassEdge*.035})`;
   item.lens.style.boxShadow=`inset 0 1px 1px rgba(255,255,255,${e.glassEdge*.6}),inset 0 -1px 2px rgba(0,0,0,${e.glassEdge*.18})`;
   const refract=supported&&e.glassRefraction>0&&theme.interface.performanceMode!=='economy';
   const key=[Math.round(width),Math.round(height),Math.round(radius)].join(':');
   if(refract&&key!==item.key){
    let url=null;try{url=normalMap(width,height,radius);}catch(_){}
    item.key=key;item.hasMap=!!url;if(url)item.map.setAttribute('href',url);
   }
   item.displacement.setAttribute('scale',String(e.glassRefraction*48));
   // The separate frosted layer remains present when a browser parses the URL
   // syntax but cannot render SVG backdrop filters. No false support claim.
   item.lens.style.backdropFilter=refract&&item.hasMap?`url("#${item.id}")`:'none';
  });
  if(timer!==null)window.clearTimeout(timer);
  timer=rects.length?window.setTimeout(request,250):null;
 }
 function request(){if(disposed||document.hidden)return;if(frame===null)frame=window.requestAnimationFrame(layout);}
 const observer=typeof MutationObserver!=='undefined'?new MutationObserver(records=>{
  if(records.some(r=>!r.target?.closest?.('.fm-appearance-optical-layer,.fm-appearance-hover-glint'))){request();}
 }):null;
 observer?.observe(document.body,{subtree:true,childList:true});
 window.addEventListener('resize',request);document.addEventListener('scroll',request,true);
 function update(next){theme=next;request();}
 function dispose(){if(disposed)return;disposed=true;if(frame!==null)window.cancelAnimationFrame(frame);if(timer!==null)window.clearTimeout(timer);observer?.disconnect();window.removeEventListener('resize',request);document.removeEventListener('scroll',request,true);root.remove();pool=[];theme=null;}
 return {update,dispose};
}
