// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.JSONObject;
import java.util.UUID;
import ru.threediwell.fm.i18n.I18n;

/** Собственный документ камеры, без секретов и интерфейса команд. */
public final class CameraPage {
    private CameraPage(){}
    public static String render(String path,String type,boolean dark){
        String nonce=UUID.randomUUID().toString();
        String endpoint=JSONObject.quote(path),connecting=JSONObject.quote(I18n.t("Подключение камеры…")),unavailable=JSONObject.quote(I18n.t("Камера недоступна. Проверьте её подключение в FM."));
        return "<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; style-src 'unsafe-inline'; script-src 'nonce-"+nonce+"'\"><style>body{margin:0;background:"+(dark?"#18181b":"#f3f4f6")+";color:"+(dark?"#e5e7eb":"#1f2329")+";font:16px sans-serif;min-height:100vh;overflow-x:hidden}video,img{width:100%;max-height:80vh;object-fit:contain;vertical-align:top}p{padding:12px;line-height:1.5}p:empty{display:none}.camera-frame{position:relative;line-height:0}.camera-ambient{height:clamp(220px,45vh,440px);pointer-events:none;background:"+(dark?
                "radial-gradient(ellipse 50% 60% at 47% 0%,rgba(115,75,211,.34),rgba(87,64,159,.13) 38%,rgba(87,64,159,0) 85%),radial-gradient(ellipse 56% 52% at 83% 0%,rgba(50,92,207,.3),rgba(48,78,161,.1) 42%,rgba(48,78,161,0) 90%),radial-gradient(ellipse 58% 58% at 15% 0%,rgba(56,83,186,.23),rgba(56,83,186,0) 87%),linear-gradient(180deg,rgba(74,73,124,.17),rgba(24,24,27,0) 92%)":
                "radial-gradient(ellipse 50% 60% at 47% 0%,rgba(139,107,212,.22),rgba(139,107,212,.07) 38%,rgba(139,107,212,0) 85%),radial-gradient(ellipse 56% 52% at 83% 0%,rgba(72,132,218,.19),rgba(72,132,218,.06) 42%,rgba(72,132,218,0) 90%),radial-gradient(ellipse 58% 58% at 15% 0%,rgba(87,124,208,.14),rgba(87,124,208,0) 87%),linear-gradient(180deg,rgba(133,146,199,.09),rgba(243,244,246,0) 92%)")+"}</style></head><body><p id='status'></p><div class='camera-frame'><video id='video' autoplay muted playsinline style='display:none'></video><img id='image' style='display:none' alt=''></div><div class='camera-ambient' aria-hidden='true'></div><script nonce='"+nonce+"'>"+
                "let pc=null,timer=null,abort=null,stopped=false,fallback=false;const base="+endpoint+",status=document.getElementById('status'),video=document.getElementById('video'),image=document.getElementById('image');status.textContent="+connecting+";"+
                "window.stopPlayer=()=>{stopped=true;clearTimeout(timer);if(abort)abort.abort();if(pc)pc.close();pc=null;video.srcObject=null;video.removeAttribute('src');image.removeAttribute('src');};"+
                "function jpeg(){if(stopped||fallback)return;fallback=true;clearTimeout(timer);if(abort)abort.abort();if(pc)pc.close();pc=null;video.srcObject=null;video.style.display='none';image.style.display='block';image.onload=()=>{if(!stopped)status.textContent='';};image.onerror=()=>{if(!stopped)status.textContent="+unavailable+";};image.src=base+'/camera';timer=setTimeout(()=>{if(!stopped&&status.textContent)status.textContent="+unavailable+";},18000);}"+
                ("klipper".equals(type)?"async function rtc(){try{pc=new RTCPeerConnection({iceServers:[]});pc.addTransceiver('video',{direction:'recvonly'});pc.ontrack=e=>{if(stopped)return;clearTimeout(timer);video.srcObject=e.streams[0]||new MediaStream([e.track]);video.style.display='block';status.textContent='';};pc.onconnectionstatechange=()=>{if(pc&&['failed','disconnected'].includes(pc.connectionState))jpeg();};await pc.setLocalDescription(await pc.createOffer());await new Promise(resolve=>{if(pc.iceGatheringState==='complete')return resolve();let timeout=setTimeout(resolve,2500);pc.onicegatheringstatechange=()=>{if(pc&&pc.iceGatheringState==='complete'){clearTimeout(timeout);resolve();}};});if(stopped||fallback)return;abort=new AbortController();const r=await fetch(base+'/webrtc',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'offer',sdp:pc.localDescription.sdp}),signal:abort.signal});if(!r.ok)throw Error();const answer=await r.json();if(stopped||fallback)return;await pc.setRemoteDescription(answer);}catch(e){if(!stopped)jpeg();}}timer=setTimeout(jpeg,15000);rtc();":"jpeg();")+
                "window.addEventListener('pagehide',window.stopPlayer);</script></body></html>";
    }
}
