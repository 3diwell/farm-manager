// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import java.util.*;
import ru.threediwell.fm.i18n.I18n;

/** Read-only telemetry plus optional inventory binding; missing weights are never guessed. */
public final class MaterialSlots {
    private MaterialSlots(){}
    public record Slot(String key,String group,String position,String material,String color,int percent,boolean external,boolean empty,boolean active,boolean stale,String details){}
    public static List<Slot> of(JSONObject printer,JSONObject state,long age,JSONObject stock){
        boolean fresh=PrinterState.fresh(state,age);JSONObject s=state==null?new JSONObject():state;
        Map<Integer,JSONObject> bound=new TreeMap<>();for(JSONObject r:FarmRepository.rows(stock==null?null:stock.optJSONArray("slots")))if(!r.isNull("index"))bound.put(r.optInt("index"),r);
        List<Slot> out=new ArrayList<>();Set<Integer> seen=new HashSet<>();boolean bambu="bambu".equals(FarmValues.text(printer,"type"));
        for(String feed:new String[]{"ams","cfs"})for(JSONObject t:FarmRepository.rows(s.optJSONArray(feed+"_trays"))){
            if(t.isNull("index"))continue;int index=t.optInt("index"),unit=t.optInt("unit",index/4),tray=t.optInt("tray",index%4);if(index<0||!seen.add(index))continue;
            String group=unitName(feed,unit);
            String pos=FarmValues.text(t,"label");if(pos.isEmpty())pos=group+" · "+(tray+1);
            int now=s.isNull(feed+"_now")?-999:s.optInt(feed+"_now",-999);
            out.add(slot(feed+index,group,pos,t,bound.remove(index),fresh,false,fresh&&now==index));
        }
        JSONObject ext=s.optJSONObject("ext_tray"),exts=s.optJSONObject("ext_trays");if(exts!=null&&exts.optJSONObject("255")!=null)ext=exts.optJSONObject("255");
        JSONObject extBound=bound.get(-1);if(extBound!=null&&!PrintRequest.flag(extBound,"external"))extBound=null;
        if(bambu||ext!=null||extBound!=null){bound.remove(-1);out.add(slot("ext",I18n.t("Внешняя подача"),I18n.t("Внешняя катушка"),ext,extBound,fresh,true,fresh&&!s.isNull("ams_now")&&s.optInt("ams_now",-999)==-1));}
        if(exts!=null&&exts.optJSONObject("254")!=null)out.add(slot("ext-left",I18n.t("Внешняя подача"),I18n.t("Внешняя катушка слева"),exts.optJSONObject("254"),null,fresh,true,fresh&&!s.isNull("ams_now")&&s.optInt("ams_now",-999)==254));
        for(var e:bound.entrySet())out.add(slot("bound"+e.getKey(),I18n.t("Привязки склада"),positionName(e.getValue()),null,e.getValue(),false,false,false));
        return Collections.unmodifiableList(out);
    }
    /** Первый номер блока AMS HT у Bambu: 128..135 — сами блоки HT, обычные AMS — 0..3. */
    public static final int AMS_HT_MIN=128;
    /** Подпись блока, как в FM: «AMS 2», «AMS HT» (второй HT — «AMS HT 2»), «CFS 1». Не порядковый номер слота. */
    public static String unitName(String feed,int unit){
        if("cfs".equals(feed))return "CFS "+(unit+1);
        if(unit>=AMS_HT_MIN)return unit==AMS_HT_MIN?"AMS HT":"AMS HT "+(unit-AMS_HT_MIN+1);
        return "AMS "+(Math.max(0,unit)+1);
    }
    /** Подпись позиции из любой строки FM (ams_trays, склад /ams, /api/printer-filament): «AMS 2 · 1»,
     *  «AMS HT · 1», метка CFS принтера, внешняя катушка. Номер внутри FM — unit*4+tray (у AMS HT 512..540);
     *  когда unit/tray не пришли (офлайн-привязка), они выводятся из него так же, как в FM. */
    public static String positionName(JSONObject slot){
        if(slot==null)return "—";
        String label=FarmValues.text(slot,"label");if(!label.isEmpty())return label;
        String side=FarmValues.text(slot,"ext_side");int index=slot.isNull("index")?Integer.MIN_VALUE:slot.optInt("index",Integer.MIN_VALUE);
        if("left".equals(side)||index==-2)return I18n.t("Внешняя катушка слева");
        if(PrintRequest.flag(slot,"external")||index==-1)return "right".equals(side)?I18n.t("Внешняя катушка справа"):I18n.t("Внешняя катушка");
        if(PrintRequest.flag(slot,"unconfirmed"))return I18n.t("Позиция не подтверждена");
        if(index<0&&(slot.isNull("unit")||!slot.has("unit")))return "—";
        int unit=slot.isNull("unit")||!slot.has("unit")?index/4:slot.optInt("unit",index/4);
        int tray=slot.isNull("tray")||!slot.has("tray")?(index>=0?index-unit*4:0):slot.optInt("tray",0);
        if(tray<0||tray>3)tray=Math.floorMod(index,4);
        String feed=FarmValues.text(slot,"feed");
        return unitName(feed.isEmpty()?"ams":feed,unit)+" · "+(tray+1);
    }
    private static Slot slot(String key,String group,String pos,JSONObject telemetry,JSONObject binding,boolean fresh,boolean ext,boolean active){
        JSONObject spool=binding==null?null:binding.optJSONObject("spool");boolean confirmed=binding!=null&&!PrintRequest.flag(binding,"offline")&&!PrintRequest.flag(binding,"unconfirmed");
        String material=FarmValues.text(telemetry,"type");boolean empty=telemetry!=null&&("Empty".equalsIgnoreCase(material)||PrintRequest.flag(telemetry,"empty"));
        String color=color(FarmValues.text(telemetry,"color"));
        if(!empty&&material.isEmpty())material=FarmValues.text(spool,"material");if(!empty&&color.isEmpty())color=color(FarmValues.text(spool,"color_hex"));
        int percent=-1;String source="";
        double total=FarmValues.number(spool,"weight_total_g"),remaining=FarmValues.number(spool,"weight_remaining_g");
        if(!empty&&fresh&&confirmed&&Double.isFinite(total)&&total>0&&Double.isFinite(remaining)&&remaining>=0){percent=(int)Math.round(Math.min(100,remaining/total*100));source=I18n.t("Остаток по складскому учёту.");}
        if(percent<0&&!empty&&fresh){double remain=FarmValues.number(telemetry,"remain");if(!Double.isFinite(remain))remain=FarmValues.number(telemetry,"percent");if(Double.isFinite(remain)&&remain>=0&&remain<=100){percent=(int)Math.round(remain);source=I18n.t("Остаток по данным принтера.");}}
        if(empty&&fresh&&(FarmValues.number(telemetry,"remain")==0||FarmValues.number(telemetry,"percent")==0)){percent=0;source=I18n.t("Остаток по данным принтера.");}
        if(empty){material=I18n.t("пусто");color="";}else if(material.isEmpty())material=ext?I18n.t("внешн."):"—";
        StringJoiner details=new StringJoiner("\n");details.add(pos);details.add(material);
        if(spool!=null){StringJoiner info=new StringJoiner(" · ");for(String f:new String[]{"vendor_name","color_name","label"}){String v=FarmValues.text(spool,f);if(!v.isEmpty())info.add(v);}if(info.length()>0)details.add(info.toString());if(Double.isFinite(remaining)&&remaining>=0)details.add(Math.round(remaining)+I18n.t(" г"));}
        if(!fresh)details.add(I18n.t("Нет свежих данных"));else if(percent<0)details.add(I18n.t("Остаток неизвестен."));else details.add(percent+"% · "+source);
        if(ext&&telemetry!=null)details.add(I18n.t("Настройка внешней подачи не подтверждает наличие катушки."));
        if(binding!=null&&!confirmed)details.add(I18n.t("Положение катушки не подтверждено."));
        return new Slot(key,group,pos,material,color,percent,ext,empty,active&&!empty,fresh?false:true,details.toString());
    }
    public static String color(String value){String s=value.startsWith("#")?value.substring(1):value;if(!s.matches("[0-9a-fA-F]{6}([0-9a-fA-F]{2})?"))return "";return "#"+s.substring(0,6);}
}
