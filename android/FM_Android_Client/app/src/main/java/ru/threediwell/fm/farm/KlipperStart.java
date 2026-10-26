// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import java.util.*;
import ru.threediwell.fm.i18n.I18n;

/**
 * Шаги подготовки Klipper, которые владелец включил в FM (GET /api/printer/{pid}/klipper-prestart).
 * Как в web/app.js: выбрать можно только операции уровня supported_automatic; уходят только их номера
 * (print_opts.klipper_prestart), сырой G-code и имена макросов телефон не передаёт. Сохранённый выбор
 * FM — галочки по умолчанию. Ответа нет — печать «как в файле», запуск это не блокирует.
 */
public final class KlipperStart {
    private KlipperStart(){}
    public record Step(String id,String label,String explain,boolean selected){}
    public static boolean selectable(JSONObject c){
        return c!=null&&"supported_automatic".equals(FarmValues.text(c,"state"))&&c.optBoolean("supported")&&!c.optBoolean("file_controlled")&&c.optBoolean("auto_execute")&&c.optBoolean("safe_each_print")&&FarmValues.text(c,"id").matches("[a-z_]{1,40}");
    }
    public static List<Step> steps(JSONObject response){
        List<Step> out=new ArrayList<>();if(response==null||!"ok".equals(FarmValues.text(response,"status")))return out;
        JSONObject prefs=response.optJSONObject("prefs");boolean en="en".equals(I18n.language());
        for(JSONObject c:FarmRepository.rows(response.optJSONArray("capabilities"))){
            if(!selectable(c))continue;String id=FarmValues.text(c,"id");
            String label=FarmValues.text(c,en?"label_en":"label_ru");if(label.isEmpty())label=id;
            out.add(new Step(id,label,FarmValues.text(c,en?"explain_en":"explain_ru"),prefs!=null&&Boolean.TRUE.equals(prefs.opt(id))));
        }
        return Collections.unmodifiableList(out);
    }
    public static boolean reachable(JSONObject response){return response!=null&&response.optBoolean("reachable");}
    public static String startMacro(JSONObject response){return FarmValues.text(response,"start_macro");}
    /** Номера выбранных операций в порядке FM. Пусто — null: print_opts не меняется. */
    public static JSONArray chosen(List<Step> steps,Set<String> checked){
        JSONArray ids=new JSONArray();for(Step s:steps)if(checked.contains(s.id()))ids.put(s.id());return ids.length()==0?null:ids;
    }
    /** Тело POST для запоминания выбора на сервере, как делает веб-интерфейс. Доказанных операций нет — null. */
    public static JSONObject prefs(JSONObject response,Set<String> checked) throws JSONException {
        if(response==null)return null;JSONObject prefs=new JSONObject();
        for(JSONObject c:FarmRepository.rows(response.optJSONArray("capabilities")))if(c.optBoolean("supported")&&FarmValues.text(c,"id").matches("[a-z_]{1,40}"))prefs.put(FarmValues.text(c,"id"),checked.contains(FarmValues.text(c,"id"))&&selectable(c));
        return prefs.length()==0?null:new JSONObject().put("prefs",prefs);
    }
}
