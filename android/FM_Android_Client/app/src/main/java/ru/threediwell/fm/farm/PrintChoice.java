// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import java.util.*;
import ru.threediwell.fm.i18n.I18n;

/** Выбор принтера и источника материала для запуска с телефона — так же, как окно запуска в веб-интерфейсе FM. */
public final class PrintChoice {
    private PrintChoice(){}
    /** slot == null — поле не передаётся (Bambu: FM сам сопоставит слоты; Klipper: ячейка как в файле). */
    public record Source(String label,Integer slot){}

    /**
     * Bambu. Есть живые лотки AMS — первым «Авто (как в файле)» (ams_slot не передаём), затем явная
     * «Внешняя катушка» (-1) и слоты. Принтер не сообщает ams_trays — только «Внешняя катушка» (-1).
     */
    public static List<Source> bambuSources(JSONObject state){
        List<Source> out=new ArrayList<>();
        List<JSONObject> trays=new ArrayList<>();for(JSONObject t:FarmRepository.rows(state==null?null:state.optJSONArray("ams_trays")))if(t.has("index")&&!t.isNull("index")&&t.optInt("index",-1)>=0)trays.add(t);
        boolean dual=state!=null&&state.optInt("nozzle_count",1)>=2;
        String external=dual?I18n.t("Внешняя катушка (сторона — по соплу в файле)"):I18n.t("Внешняя катушка");
        if(!trays.isEmpty())out.add(new Source(I18n.t("Авто (как в файле)"),null));
        out.add(new Source(external,-1));
        for(JSONObject t:trays){
            int index=t.optInt("index");
            //  Подпись слота — общая с карточкой принтера и складом (MaterialSlots.positionName), как в FM:
            //  «AMS 2 · 1», первый AMS HT — «AMS HT · 1», второй — «AMS HT 2 · 1».
            String type=FarmValues.text(t,"type");
            out.add(new Source(MaterialSlots.positionName(t)+(type.isEmpty()||"Empty".equalsIgnoreCase(type)?"":" · "+type),index));
        }
        return Collections.unmodifiableList(out);
    }
    /** Klipper с CFS: «Как в файле» (cfs_slot не передаём) и только ячейки, в которых есть материал. */
    public static List<Source> cfsSources(JSONObject state){
        List<Source> out=new ArrayList<>();out.add(new Source(I18n.t("Ячейка CFS как в файле"),null));
        for(JSONObject t:FarmRepository.rows(state==null?null:state.optJSONArray("cfs_trays"))){
            if(!t.has("index")||t.isNull("index")||t.optInt("index",-1)<0)continue;
            String type=FarmValues.text(t,"type");if(type.isEmpty()||"Empty".equalsIgnoreCase(type))continue;
            int index=t.optInt("index"),unit=t.optInt("unit",index/4),tray=t.optInt("tray",index%4);
            String position=FarmValues.text(t,"label");if(position.isEmpty())position="CFS "+(unit+1)+" · "+(tray+1);
            out.add(new Source(position+" · "+type,index));
        }
        return Collections.unmodifiableList(out);
    }
    /** Принтер можно предложить для нового файла: совместим, свободен или завершил печать, FM ему ничего не отправляет. */
    public static boolean offered(JSONObject file,JSONObject p,JSONObject s,long age,JSONObject sends){
        String id=FarmValues.text(p,"id");if(id.isEmpty()||!PrintRequest.compatible(file,id)||!RepeatPrint.eligible(p,s,age))return false;
        JSONArray reserved=sends==null?null:sends.optJSONArray("reserved_printer_ids");
        if(reserved!=null)for(int i=0;i<reserved.length();i++)if(id.equals(reserved.optString(i)))return false;
        return true;
    }
    /** После завершённой печати запуск только с подтверждением «деталь снята, стол свободен». */
    public static boolean needsPlateConfirmation(JSONObject p,JSONObject s,long age){return !PrinterState.ready(p,s,age)&&RepeatPrint.finished(p,s,age);}
    public static boolean startAllowed(JSONObject p,JSONObject s,long age,boolean plateCleared){return PrinterState.ready(p,s,age)||RepeatPrint.finished(p,s,age)&&plateCleared;}
    /** print_opts запуска. Ничего не выбрано у не-Bambu — null: запрос прежний, байт в байт. */
    public static JSONObject options(String type,boolean bedLeveling,boolean flowCalibration,boolean timelapse,Integer cfsSlot,JSONArray prestart) throws JSONException {
        JSONObject opts=null;
        if("bambu".equals(type))opts=new JSONObject().put("bed_leveling",bedLeveling).put("flow_cal",flowCalibration).put("timelapse",timelapse);
        if("klipper".equals(type)){
            if(prestart!=null&&prestart.length()>0)opts=new JSONObject().put("klipper_prestart",prestart);
            if(cfsSlot!=null&&cfsSlot>=0)opts=(opts==null?new JSONObject():opts).put("cfs_slot",cfsSlot);
        }
        return opts;
    }
}
