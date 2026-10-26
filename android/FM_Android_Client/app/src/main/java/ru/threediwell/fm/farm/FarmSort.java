// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import java.text.Collator;
import java.util.*;
import ru.threediwell.fm.i18n.I18n;

/** Personal presentation only: never changes server objects, print eligibility or queues. */
public final class FarmSort {
    public enum FileState { READY, PRINTING, COMPLETE, PREPARING, MISSING }
    private FarmSort() {}
    public static String mode(String value,boolean printer) {
        return (printer?Set.of("name","model","status"):Set.of("name","ready")).contains(value)?value:(printer?"status":"name");
    }
    public static int printerRank(JSONObject state,long age) {
        if(!PrinterState.fresh(state,age))return 8;
        return switch(state.optString("status")) {
            case "FAILED","ERROR"->0;case "PAUSED","PAUSE"->1;case "FINISH"->2;
            case "RUNNING"->3;case "PREPARE","SLICING"->4;case "IDLE"->5;default->6;
        };
    }
    public static FileState fileState(JSONObject file) {
        if(PrintRequest.flag(file,"missing"))return FileState.MISSING;
        if(!PrintRequest.flag(file,"is_printable"))return FileState.PREPARING;
        if("printing".equalsIgnoreCase(file.optString("status")))return FileState.PRINTING;
        JSONArray children=file.optJSONArray("children");boolean anyRequired=false,complete=true;
        if(children!=null) {
            for(JSONObject part:FarmRepository.rows(children)) {
                if(Set.of("printing","in_progress").contains(part.optString("status").toLowerCase(Locale.ROOT)))return FileState.PRINTING;
                long required=part.optLong("required_qty",0);
                if(required>0){anyRequired=true;if(part.optLong("printed_qty",0)<required)complete=false;}
            }
        }else {
            long required=file.optLong("required_qty",0);
            anyRequired=required>0;complete=anyRequired&&file.optLong("printed_qty",0)>=required;
        }
        return anyRequired&&complete?FileState.COMPLETE:FileState.READY;
    }
    public static String fileCaption(JSONObject file) {
        return switch(fileState(file)) {
            case READY->I18n.t("Готов к печати");case PRINTING->"printing".equalsIgnoreCase(file.optString("status"))?I18n.t("Печатается"):I18n.t("Детали в работе");
            case COMPLETE->I18n.t("План выполнен");case PREPARING->I18n.t("Нужна подготовка");case MISSING->I18n.t("Нет файла");
        };
    }
    public static List<JSONObject> printers(JSONArray source,JSONObject states,long age,String selected,boolean reverse) {
        String mode=mode(selected,true);Collator collator=collator();
        Comparator<JSONObject> names=(a,b)->natural(a.optString("name"),b.optString("name"),collator);
        Comparator<JSONObject> primary=switch(mode) {
            case "model"->(a,b)->natural(a.optString("model"),b.optString("model"),collator);
            case "status"->Comparator.comparingInt(p->printerRank(states.optJSONObject(p.optString("id")),age));
            default->names;
        };
        if(reverse)primary=primary.reversed();
        List<JSONObject> rows=new ArrayList<>(FarmRepository.rows(source));
        rows.sort(primary.thenComparing(names).thenComparing(p->p.optString("id")));return rows;
    }
    public static List<JSONObject> files(JSONArray source,String selected,boolean reverse) {
        String mode=mode(selected,false);Collator collator=collator();
        Comparator<JSONObject> names=(a,b)->natural(a.optString("filename"),b.optString("filename"),collator);
        Comparator<JSONObject> primary=mode.equals("ready")?Comparator.comparing(FarmSort::fileState):names;
        if(reverse)primary=primary.reversed();
        List<JSONObject> rows=new ArrayList<>(FarmRepository.rows(source));
        rows.sort(primary.thenComparing(names).thenComparing(p->p.optString("file_id")));return rows;
    }
    /** Core tree emits a shared part only under its first file, with extra_files references.
     * Build detached presentation copies so sorting cannot lose those plans or change print payloads. */
    public static JSONArray projectFiles(JSONArray nodes) {
        try {
        JSONArray result=new JSONArray();Map<String,JSONObject> copies=new HashMap<>();
        for(JSONObject file:FarmRepository.rows(nodes)) {
            JSONObject copy=new JSONObject(file.toString());result.put(copy);copies.put(copy.optString("file_id"),copy);
        }
        for(JSONObject file:FarmRepository.rows(nodes))for(JSONObject part:FarmRepository.rows(file.optJSONArray("children"))) {
            for(JSONObject extra:FarmRepository.rows(part.optJSONArray("extra_files"))) {
                JSONObject target=copies.get(extra.optString("file_id"));if(target==null)continue;
                JSONArray parts=target.optJSONArray("children");if(parts==null){parts=new JSONArray();target.put("children",parts);}
                boolean exists=false;String id=part.optString("part_id");for(JSONObject linked:FarmRepository.rows(parts))if(!id.isEmpty()&&id.equals(linked.optString("part_id")))exists=true;
                if(!exists){JSONObject linked=new JSONObject(part.toString());linked.remove("extra_files");linked.put("on_plate_qty",extra.optInt("on_plate_qty",part.optInt("on_plate_qty")));linked.put("file_part_id",extra.optString("file_part_id"));parts.put(linked);}
            }
        }
        return result;
        }catch(JSONException ex){throw new IllegalArgumentException("Invalid project tree",ex);}
    }
    private static Collator collator(){Collator c=Collator.getInstance(I18n.locale());c.setStrength(Collator.SECONDARY);return c;}
    /** Human ordering: plate2 before plate10; no parsing overflow on long identifiers. */
    static int natural(String a,String b,Collator collator) {
        int i=0,j=0;
        while(i<a.length()&&j<b.length()) {
            boolean ad=digit(a.charAt(i)),bd=digit(b.charAt(j));int ai=i+1,bj=j+1;
            while(ai<a.length()&&digit(a.charAt(ai))==ad)ai++;
            while(bj<b.length()&&digit(b.charAt(bj))==bd)bj++;
            String x=a.substring(i,ai),y=b.substring(j,bj);int compared;
            if(ad&&bd){String nx=x.replaceFirst("^0+(?!$)",""),ny=y.replaceFirst("^0+(?!$)","");compared=Integer.compare(nx.length(),ny.length());if(compared==0)compared=nx.compareTo(ny);}
            else compared=collator.compare(x,y);
            if(compared!=0)return compared;i=ai;j=bj;
        }
        return Integer.compare(a.length()-i,b.length()-j);
    }
    private static boolean digit(char c){return c>='0'&&c<='9';}
}
