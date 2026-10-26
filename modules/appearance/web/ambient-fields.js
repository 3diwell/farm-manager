// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Procedural fields from the approved three-background preview.
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const mix=(a,b,t)=>a+(b-a)*t;
const smooth=x=>x*x*(3-2*x);
const hashes=new Float32Array(4096);
let seed=20319;
for(let i=0;i<hashes.length;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;hashes[i]=seed/4294967295;}
function noise(x,y){
 const ix=Math.floor(x),iy=Math.floor(y),u=smooth(x-ix),v=smooth(y-iy);
 const a=((ix*73)^(iy*179))&4095,b=(((ix+1)*73)^(iy*179))&4095,c=((ix*73)^((iy+1)*179))&4095,d=(((ix+1)*73)^((iy+1)*179))&4095;
 return mix(mix(hashes[a],hashes[b],u),mix(hashes[c],hashes[d],u),v);
}
function cloud(x,y){return noise(x,y)*.64+noise(x*2.03+17.2,y*2.03-11.4)*.26+noise(x*4.09-8.1,y*4.09+23.5)*.10;}
export function ambientField(kind,x,y,t,soft,out=[0,0]){
 const drift=t*.033;
 if(kind==='fluid'){
  const wx=cloud(x*1.9+drift*.4,y*1.8-drift*.3)-.5,wy=cloud(x*1.7+12-drift*.3,y*1.9+4+drift*.4)-.5;
  const qx=x+wx*.68,qy=y+wy*.66;
  const ax=.24+Math.sin(t*.047)*.19,ay=.37+Math.cos(t*.039)*.16;
  const bx=.75+Math.cos(t*.036+2)*.20,by=.67+Math.sin(t*.051+1)*.18;
  const spread=.085+soft*.125;
  const a=Math.exp(-((qx-ax)**2*.75+(qy-ay)**2*1.3)/spread);
  const b=Math.exp(-((qx-bx)**2*1.2+(qy-by)**2*.7)/spread);
  const deep=.22*Math.exp(-((qx-.5)**2+(qy-.82)**2)/.37);
  out[0]=a*.93+deep;out[1]=b*.92+deep*.45;return out;
 }
 if(kind==='aurora'){
  const u=x*1.35,fold=noise(u*2+3+drift*.25,drift*.25+5)-.5;
  const c1=.35+.16*Math.sin(u*3.7+t*.052)+.065*Math.sin(u*8-t*.061)+fold*.17;
  const c2=.63+.16*Math.sin(u*3.9-t*.047+2)+.075*Math.sin(u*6.7+t*.041);
  const width=.050+soft*.092;
  const d1=y-c1,d2=y-c2;
  const curtain=.70+.30*Math.sin(u*5-t*.08)**2;
  const a=Math.exp(-d1*d1/(width*width))*curtain*.76+.29*Math.exp(-((d1+.10)**2)/(width*width*7));
  const b=Math.exp(-d2*d2/(width*width*1.5))*.72+.30*Math.exp(-((d2-.07)**2)/(width*width*6));
  out[0]=a;out[1]=b;return out;
 }
 const wx=cloud(x*1.8+drift*.22,y*1.8-drift*.16)-.5;
 const wy=cloud(x*1.8+8-drift*.12,y*1.8+drift*.2)-.5;
 const scale=3.9-soft*1.25;
 const n1=cloud(x*scale+wx*1.45+drift*.30,y*scale+wy*1.25-drift*.25);
 const n2=cloud(x*scale+wx*1.3+11-drift*.22,y*scale+wy*1.45+7+drift*.31);
 const a=smooth(clamp((n1-.18)/.64)),b=smooth(clamp((n2-.22)/.66));
 const veil=.82+.18*Math.cos((x-y)*2+t*.025);
 out[0]=a*veil;out[1]=b*(1-.24*a);return out;
}

export function paintAmbient(buffer,options,time){
 const {width:w,height:h,data:pixels}=buffer;
 const {kind,primary,secondary,opacity,softness,scale,light}=options;
 const strength=clamp(opacity*3.28*(light?.66:1),0,.84),pair=[0,0];
 const zoom=.62+scale*.73;
 for(let j=0;j<h;j++)for(let i=0;i<w;i++){
  const x=(i/(w-1)-.5)/zoom+.5,y=(j/(h-1)-.5)/zoom+.5;
  ambientField(kind,x,y,time,softness,pair);
  const sum=pair[0]+pair[1],weight=smooth(clamp((pair[1]/(sum+.0001)-.12)/.76));
  const density=1-Math.exp(-sum*1.25),vignette=clamp(1-.17*((x-.5)**2+(y-.5)**2),.65,1);
  const alpha=clamp(density*strength*vignette),at=(j*w+i)*4;
  const grain=(hashes[((i*37)^(j*113))&4095]-.5)*.9;
  for(let c=0;c<3;c++)pixels[at+c]=clamp(mix(primary[c],secondary[c],weight),0,255);
  pixels[at+3]=alpha===0?0:clamp(alpha*255+grain,0,255);
 }
 return buffer;
}
