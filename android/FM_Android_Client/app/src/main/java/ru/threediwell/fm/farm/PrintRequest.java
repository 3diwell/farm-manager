// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import ru.threediwell.fm.i18n.I18n;

/** Одиночная печать существующего файла. Полей обхода проверок здесь нет. */
public final class PrintRequest {
    public final String projectId,fileId,filename,printerId;
    private final Integer slot;private final JSONObject options;
    public PrintRequest(String project,String file,String filename,String printer,Integer slot,JSONObject options){
        projectId=project==null?"":project;fileId=file==null?"":file;this.filename=filename;printerId=printer;
        if(printer==null||printer.isEmpty()||filename==null||filename.isEmpty()||(!projectId.isEmpty()&&fileId.isEmpty()))throw new IllegalArgumentException(I18n.t("Не выбран файл или принтер."));
        this.slot=slot;this.options=options;
    }
    public String path(){return projectId.isEmpty()?"/api/part/print":"/api/projects2/"+FarmRepository.segment(projectId)+"/files/"+FarmRepository.segment(fileId)+"/print";}
    public JSONObject body() throws JSONException {
        JSONObject b=new JSONObject().put("printer_id",printerId);
        if(projectId.isEmpty())b.put("gcode_file",filename).put("source","quick");
        if(slot!=null)b.put("ams_slot",slot);
        if(options!=null){
            JSONObject allowed=new JSONObject();for(String key:new String[]{"timelapse","bed_leveling","flow_cal"})if(options.opt(key) instanceof Boolean)allowed.put(key,options.getBoolean(key));
            // Klipper: только номера операций подготовки из списка FM и номер ячейки CFS. Сырого G-code нет.
            Object cfs=options.opt("cfs_slot");if(cfs instanceof Integer&&(Integer)cfs>=0)allowed.put("cfs_slot",cfs);
            JSONArray steps=options.optJSONArray("klipper_prestart");if(steps!=null){JSONArray clean=new JSONArray();for(int i=0;i<steps.length();i++){Object id=steps.opt(i);if(id instanceof String&&((String)id).matches("[a-z_]{1,40}"))clean.put(id);}if(clean.length()>0)allowed.put("klipper_prestart",clean);}
            if(allowed.length()>0)b.put("print_opts",allowed);
        }
        return b;
    }
    public static boolean compatible(JSONObject file,String printerId){
        if(!flag(file,"is_printable")||flag(file,"missing"))return false;
        JSONArray ids=file.optJSONArray("compatible_pids");
        if(ids==null)return false;
        for(int i=0;i<ids.length();i++)if(printerId.equals(ids.optString(i)))return true;
        return false;
    }
    public static boolean accepted(JSONObject response){return "ok".equals(response.optString("status"))&&response.optBoolean("accepted")&&!response.optString("job_id").isEmpty();}
    public static boolean flag(JSONObject object,String key){return object.optBoolean(key)||object.optInt(key,0)==1;}
}
