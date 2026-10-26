// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import java.util.*;
import ru.threediwell.fm.core.FmApi;
import ru.threediwell.fm.i18n.I18n;

/** Ответ FM на запуск печати словами для человека: итог и уведомления склада (`notes`).
 *  Уведомления печать не останавливают — FM уже принял запуск; их только показывают списком,
 *  тем же смыслом, что и окно FM на компьютере (web/app.js, filNoteText). */
public final class PrintOutcome {
    private PrintOutcome(){}
    /** Итог и уведомления одной строкой для подсказки экрана фермы: каждое уведомление — с новой строки. */
    public static String text(JSONObject result){
        StringBuilder out=new StringBuilder(message(result));
        for(String note:notes(result))out.append("\n• ").append(note);
        return out.toString();
    }
    public static String message(JSONObject result){
        if(PrintRequest.accepted(result))return I18n.t("FM принял отправку. Ожидаем подтверждение запуска принтером.");
        return I18n.t("Запуск не подтверждён. ")+reason(result);
    }
    public static String reason(JSONObject result){
        switch(result.optString("status")){
            case "incompatible":return I18n.t("Файл несовместим с принтером.")+extra(FarmValues.text(result,"reason"));
            case "low_filament":case "shortage":return I18n.t("FM сообщил о недостатке материала. Проверьте катушки и требования файла в FM.");
            default:
        }
        String code=FarmValues.text(result,"reason");if(code.isEmpty())code=FarmValues.text(result,"error");
        if(code.isEmpty())return I18n.t("Проверьте результат в FM.");
        String known=FmApi.Rejected.text(code,FarmValues.text(result,"detail"));
        return known!=null?known:code;
    }
    /** Причина несовместимости FM пишет сам (по-русски); показываем её как есть, без перевода. */
    private static String extra(String reason){return reason.isEmpty()?"":" "+reason;}
    public static List<String> notes(JSONObject result){
        List<String> out=new ArrayList<>();
        for(JSONObject note:FarmRepository.rows(result==null?null:result.optJSONArray("notes"))){String line=note(note);if(!line.isEmpty())out.add(line);}
        return out;
    }
    public static String note(JSONObject n){
        String who=FarmValues.text(n,"printer_name");if(who.isEmpty())who=FarmValues.text(n,"printer_id");
        String prefix=who.isEmpty()?"":who+": ";String kind=FarmValues.text(n,"kind");
        if("check_unavailable".equals(kind)){
            boolean en="en".equals(I18n.language());
            String module=en?FarmValues.text(n,"module_name_en"):"";if(module.isEmpty())module=FarmValues.text(n,"module_name");if(module.isEmpty())module=FarmValues.text(n,"module_id");
            String why=switch(FarmValues.text(n,"reason")){
                case "license"->I18n.t("работает без действующей лицензии");
                case "error"->I18n.t("не смог выполнить проверку");
                default->I18n.t("не ответил вовремя");
            };
            return prefix+I18n.t("модуль «{module}» {why} — печать запущена без проверки остатка").replace("{module}",module).replace("{why}",why);
        }
        JSONObject shortage=first(n);String material=(FarmValues.text(shortage,"material")+" "+FarmValues.text(shortage,"color_name")).trim();
        if(material.isEmpty())material=I18n.t("материал");
        if("spool_replaced".equals(kind)){
            String text=I18n.t("{material} закончился — поставлена катушка со склада").replace("{material}",material);
            double left=FarmValues.number(shortage,"left_in_stock");
            if(Double.isFinite(left))text+=I18n.t(", осталось {n}").replace("{n}",String.valueOf(Math.round(left)));
            return prefix+text;
        }
        if("filament_tight".equals(kind)||shortage.length()>0)
            return prefix+I18n.t("{material} на исходе — катушку скоро менять").replace("{material}",material);
        return n.length()==0?"":prefix+I18n.t("FM прислал уведомление о запуске — подробности в FM");
    }
    private static JSONObject first(JSONObject n){
        for(String key:new String[]{"resolved","tight"}){JSONArray rows=n.optJSONArray(key);if(rows!=null&&rows.optJSONObject(0)!=null)return rows.optJSONObject(0);}
        return new JSONObject();
    }
}
