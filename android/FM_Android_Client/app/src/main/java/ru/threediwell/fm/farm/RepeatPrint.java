// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import java.util.*;
import ru.threediwell.fm.i18n.I18n;

/** Resolves a successful FM-sent last run to its exact project file or quick task; never guesses by name. */
public final class RepeatPrint {
    private RepeatPrint(){}
    public record Last(String key,String projectId,String fileId,String filename,String hash,String source) {}
    public static final class Target {
        public final Last last;public final JSONObject file;public final String projectId,projectName,printerId;
        private final String signature;
        public Target(Last last,JSONObject file,String project,String name,String printer) {
            this.last=last;this.file=file;projectId=project;projectName=name;printerId=printer;
            signature=String.join("\n",last.key(),project,FarmValues.text(file,"file_id"),FarmValues.text(file,"filename"),FarmValues.text(file,"content_hash"),FarmValues.text(file,"mtime"),FarmValues.text(file,"size"));
        }
        public boolean same(Target other){return other!=null&&printerId.equals(other.printerId)&&signature.equals(other.signature);}
        public boolean matches(PrintRequest request){return printerId.equals(request.printerId)&&projectId.equals(request.projectId)&&FarmValues.text(file,"file_id").equals(request.fileId)&&FarmValues.text(file,"filename").equals(request.filename);}
    }
    public static boolean finished(JSONObject p,JSONObject s,long age) {
        if(!PrinterState.fresh(s,age)||!"FINISH".equals(FarmValues.text(s,"status")))return false;
        return switch(FarmValues.text(p,"type")){
            case "bambu"->"FINISH".equals(FarmValues.text(s,"status_raw"));
            case "klipper"->"complete".equals(FarmValues.text(s,"status_raw"));
            case "flashforge"->Arrays.asList("completed","complete").contains(FarmValues.text(s,"status_raw"));
            case "demo"->"finish".equals(FarmValues.text(s,"status_raw"));
            default->false;
        };
    }
    /** Completed printers require an explicit empty-plate confirmation before POST. */
    public static boolean eligible(JSONObject p,JSONObject s,long age){return PrinterState.ready(p,s,age)||finished(p,s,age);}
    /** Только запуск, который FM отправил сам: проект (с project_id/file_id) или быстрая задача, server_sent=true.
     * Печать из слайсера или с экрана принтера не повторяется: файл по имени не подбирается. */
    public static Last last(JSONObject history,JSONObject p,JSONObject s,long age) {
        String pid=FarmValues.text(p,"id");
        if(!eligible(p,s,age))throw new IllegalStateException(I18n.t("Повтор доступен на свободном принтере или после успешного завершения печати со свежими данными."));
        if(history==null)throw new IllegalStateException(I18n.t("Повтор доступен только для печати, которую отправил FM. Нужен модуль «Аналитика качества»; иначе откройте файл из проектов или задач."));
        JSONArray runs=history.optJSONArray("runs");
        if(runs==null)throw new IllegalArgumentException(I18n.t("Не удалось прочитать историю печати FM."));
        if(runs.length()==0)throw new IllegalStateException(I18n.t("Нет достоверных данных о последней успешной печати. Откройте файл из проектов или задач."));
        JSONObject row=runs.optJSONObject(0);
        if(row==null||!pid.equals(FarmValues.text(row,"printer_id"))||!"finished".equals(FarmValues.text(row,"outcome_raw"))||FarmValues.text(row,"run_id").isEmpty())
            throw new IllegalStateException(I18n.t("Последний запуск в FM не завершён успешно. Повтор последней печати недоступен."));
        if(runs.length()>1){JSONObject previous=runs.optJSONObject(1);if(previous!=null&&FarmValues.text(row,"started_at").equals(FarmValues.text(previous,"started_at"))&&FarmValues.text(row,"created_at").equals(FarmValues.text(previous,"created_at")))
            throw new IllegalStateException(I18n.t("Не удалось однозначно определить последний запуск FM."));}
        String source=FarmValues.text(row,"source"),filename=FarmValues.text(row,"filename"),project=FarmValues.text(row,"project_id"),file=FarmValues.text(row,"file_id");
        JSONObject payload=row.optJSONObject("source_payload");
        if(!serverSent(row)||!("project".equals(source)||"quick".equals(source)))
            throw new IllegalStateException(I18n.t("Последнюю печать запустили не из FM (из слайсера или с экрана принтера). Её файл неизвестен — откройте нужный файл из проектов или задач."));
        if("quick".equals(source)&&!FarmValues.text(payload,"staging_file").isEmpty())filename=FarmValues.text(payload,"staging_file");
        if(filename.isEmpty())throw new IllegalStateException(I18n.t("FM не сообщил имя последнего напечатанного файла."));
        if("project".equals(source)&&(project.isEmpty()||file.isEmpty()))throw new IllegalStateException(I18n.t("У последнего запуска нет точной связи с файлом проекта."));
        if(finished(p,s,age)&&!FarmValues.text(s,"file_name").isEmpty()&&!nameMatches(filename,FarmValues.text(s,"file_name")))
            throw new IllegalStateException(I18n.t("История FM ещё не соответствует последней печати принтера. Обновите карточку."));
        return new Last(FarmValues.text(row,"run_id"),"project".equals(source)?project:"","project".equals(source)?file:"",filename,FarmValues.text(row,"file_hash"),source);
    }
    /** Признак «FM отправил файл сам» из журнала качества. Отсутствие признака — не FM. */
    public static boolean serverSent(JSONObject run){JSONObject payload=run==null?null:run.optJSONObject("source_payload");return payload!=null&&payload.optBoolean("server_sent",false)&&Boolean.TRUE.equals(payload.opt("server_sent"));}
    public static boolean nameMatches(String filename,String reported) {
        String a=base(filename),b=base(reported);if(a.isEmpty()||b.isEmpty())return false;
        if(a.equalsIgnoreCase(b))return true;
        // Only an extensionless firmware name may match a full printable filename.
        return !b.contains(".")&&stem(a).equalsIgnoreCase(b);
    }
    private static String base(String value){if(value==null)return "";String s=value.replace('\\','/');return s.substring(s.lastIndexOf('/')+1).trim();}
    private static String stem(String value){String lower=value.toLowerCase(Locale.ROOT);for(String suffix:new String[]{".gcode.3mf",".gcode",".3mf",".gco"})if(lower.endsWith(suffix))return value.substring(0,value.length()-suffix.length());return value;}
    public static Target resolve(Last last,List<Target> candidates,String printerId) {
        List<Target> matches=new ArrayList<>();
        for(Target target:candidates){
            boolean same="project".equals(last.source())?last.projectId().equals(target.projectId)&&last.fileId().equals(FarmValues.text(target.file,"file_id")):
                "quick".equals(last.source())&&target.projectId.isEmpty()&&last.filename().equals(FarmValues.text(target.file,"filename"));
            if(same)matches.add(target);
        }
        if(matches.size()!=1)throw new IllegalStateException(matches.isEmpty()?I18n.t("Последний файл отсутствует в доступных проектах и задачах FM."):I18n.t("Найдено несколько файлов с именем последней печати. Выберите нужный файл в FM."));
        Target result=matches.get(0);
        if(!last.hash().isEmpty()&&!last.hash().equals(FarmValues.text(result.file,"content_hash")))throw new IllegalStateException(I18n.t("Файл проекта изменён после последней печати. Выберите и проверьте его заново."));
        if(!PrintRequest.compatible(result.file,printerId))throw new IllegalStateException(I18n.t("Последний файл недоступен для печати на этом принтере."));
        return result;
    }
    public static boolean reserved(JSONObject sends,String printerId){JSONArray ids=sends.optJSONArray("reserved_printer_ids");if(ids==null)throw new IllegalStateException(I18n.t("Не удалось проверить отправки FM."));for(int i=0;i<ids.length();i++)if(printerId.equals(ids.optString(i)))return true;return false;}
}
