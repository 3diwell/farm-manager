// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import java.util.*;
import java.util.function.Function;
import ru.threediwell.fm.i18n.I18n;

/**
 * Отметки «запуск не проверен» — по адресу FM и принтеру, а не одна на телефон.
 * Повторной отправки нет; cookie и пароли не хранятся.
 * Отметка снимается своей отправкой FM (completed/failed) либо печатью этого файла на принтере,
 * когда отправки уже нет в списке. Пропавшая отправка (FM перезапускался, «убрать» в панели)
 * превращает отметку в мягкое напоминание: оно не блокирует новые запуски.
 * Нечитаемая запись блокирует все запуски (как раньше), пока человек не проверит FM и не снимет её.
 */
public final class PrintJournal {
    public interface Store {String read();boolean write(String value);boolean clear();}
    public enum Decision {KEEP,CLEAR,SOFT_GONE,SOFT_RESTART}
    /** Без номера отправки FM мог ещё готовить запуск: пропажу из списка учитываем не раньше этого срока. */
    public static final long UNKNOWN_GRACE_MS=60000;
    public static final String SOFT_GONE="gone",SOFT_RESTART="restart",SOFT_CORRUPT="corrupt";
    public record Mark(String origin,String printerId,String filename,String jobId,boolean soft,String softReason,long createdAt,long updatedAt){
        public String key(){return key(origin,printerId);}
        static String key(String origin,String printer){return origin+"\n"+printer;}
    }
    /** Результат запуска неизвестен: отметка сохранена, автоматического повтора нет. */
    public static final class Unknown extends java.io.IOException {
        public Unknown(Exception cause){super(I18n.t("Результат запуска неизвестен. Проверьте отправку в FM и состояние принтера перед новым запуском."),cause);}
    }
    private final Store store;
    public PrintJournal(Store store){this.store=store;}

    public synchronized List<Mark> all(){
        String raw=store.read();List<Mark> out=new ArrayList<>();if(raw==null||raw.isEmpty())return out;
        try{
            JSONObject root=new JSONObject(raw);JSONArray rows=root.optJSONArray("marks");
            if(rows==null){out.add(mark(root));return out;}   // запись версии 0.15.15: одна отметка на телефон
            for(int i=0;i<rows.length();i++)out.add(mark(rows.getJSONObject(i)));
            return out;
        }catch(JSONException|IllegalArgumentException ex){
            out.clear();out.add(new Mark("","","","",false,SOFT_CORRUPT,0,0));return out;
        }
    }
    private static Mark mark(JSONObject v) throws JSONException {
        String origin=FarmValues.text(v,"origin"),printer=FarmValues.text(v,"printer_id");
        if(origin.isEmpty()||printer.isEmpty())throw new JSONException("mark without origin or printer");
        long created=v.optLong("created_at",0);
        return new Mark(origin,printer,FarmValues.text(v,"filename"),FarmValues.text(v,"job_id"),v.optBoolean("soft",false),FarmValues.text(v,"soft_reason"),created,v.optLong("updated_at",created));
    }
    private static JSONObject json(Mark m) throws JSONException {
        JSONObject v=new JSONObject().put("origin",m.origin()).put("printer_id",m.printerId()).put("filename",m.filename()).put("created_at",m.createdAt()).put("updated_at",m.updatedAt()).put("state",m.jobId().isEmpty()?"unknown":"accepted");
        if(!m.jobId().isEmpty())v.put("job_id",m.jobId());
        if(m.soft())v.put("soft",true).put("soft_reason",m.softReason());
        return v;
    }
    private boolean save(List<Mark> marks) throws JSONException {
        List<Mark> kept=new ArrayList<>();for(Mark m:marks)if(!m.printerId().isEmpty())kept.add(m);
        if(kept.isEmpty())return store.clear();
        JSONArray rows=new JSONArray();for(Mark m:kept)rows.put(json(m));
        return store.write(new JSONObject().put("v",2).put("marks",rows).toString());
    }
    /** Отметки этого FM. Нечитаемая запись показывается на любом FM. */
    public synchronized List<Mark> marks(String origin){List<Mark> out=new ArrayList<>();for(Mark m:all())if(m.origin().equals(origin)||m.origin().isEmpty())out.add(m);return out;}
    public synchronized Mark find(String origin,String printer){for(Mark m:all())if(m.origin().equals(origin)&&m.printerId().equals(printer))return m;return null;}
    /** Блокирует новый запуск только на этом принтере этого FM (нечитаемая запись — везде). Напоминание не блокирует. */
    public synchronized boolean blocks(String origin,String printer){for(Mark m:all())if(!m.soft()&&(m.printerId().isEmpty()||m.origin().equals(origin)&&m.printerId().equals(printer)))return true;return false;}
    public synchronized boolean pending(String origin){return !marks(origin).isEmpty();}

    public synchronized void begin(String origin,PrintRequest request,long now) throws JSONException {
        if(blocks(origin,request.printerId))throw new IllegalStateException(I18n.t("Сначала проверьте предыдущий запуск в FM."));
        List<Mark> marks=all();marks.removeIf(m->m.key().equals(Mark.key(origin,request.printerId))||m.printerId().isEmpty());
        marks.add(new Mark(origin,request.printerId,request.filename,"",false,"",now,now));
        if(!save(marks))throw new IllegalStateException(I18n.t("Не удалось сохранить состояние запуска. Печать не отправлена."));
    }
    public synchronized void accepted(String origin,String printer,String id,long now) throws JSONException {
        List<Mark> marks=all();boolean found=false;
        for(int i=0;i<marks.size();i++){Mark m=marks.get(i);if(m.origin().equals(origin)&&m.printerId().equals(printer)){marks.set(i,new Mark(origin,printer,m.filename(),id,false,"",m.createdAt(),now));found=true;}}
        if(!found)throw new IllegalStateException("Missing print journal");
        if(!save(marks))throw new IllegalStateException(I18n.t("Не удалось сохранить номер отправки. Проверьте запуск в FM."));
    }
    public synchronized void clear(String origin,String printer){
        List<Mark> marks=all();marks.removeIf(m->m.origin().equals(origin)&&m.printerId().equals(printer)||m.printerId().isEmpty()&&printer.isEmpty());
        try{if(!save(marks))throw new IllegalStateException(I18n.t("Не удалось удалить состояние отправки."));}catch(JSONException ex){throw new IllegalStateException(I18n.t("Не удалось удалить состояние отправки."),ex);}
    }

    static boolean printingFile(JSONObject s,long age,String filename){
        return PrinterState.fresh(s,age)&&Arrays.asList("RUNNING","PREPARE","PAUSED","PAUSE","SLICING").contains(FarmValues.text(s,"status"))&&RepeatPrint.nameMatches(filename,FarmValues.text(s,"file_name"));
    }
    private static boolean terminal(String state){return "completed".equals(state)||"failed".equals(state);}
    /**
     * Что делать с отметкой по снимку /api/send-jobs, снятому в момент fetchedAt (часы телефона).
     * Снимок, начатый не позже последнего изменения отметки, ничего не доказывает: в нём ещё нет своей отправки.
     */
    public static Decision decide(Mark m,JSONObject sends,long fetchedAt,JSONObject state,long age){
        if(m.printerId().isEmpty())return Decision.KEEP;
        if(m.soft())return printingFile(state,age,m.filename())?Decision.CLEAR:Decision.KEEP;
        JSONArray jobs=sends==null?null:sends.optJSONArray("jobs");
        if(jobs==null||fetchedAt<=m.updatedAt())return Decision.KEEP;
        if(!m.jobId().isEmpty()){
            for(JSONObject job:FarmRepository.rows(jobs))if(m.jobId().equals(FarmValues.text(job,"job_id")))return terminal(FarmValues.text(job,"state"))?Decision.CLEAR:Decision.KEEP;
            if(printingFile(state,age,m.filename()))return Decision.CLEAR;
            return jobs.length()==0?Decision.SOFT_RESTART:Decision.SOFT_GONE;
        }
        // Ответ на запуск не дошёл: номера отправки нет. Своё задание опознать нельзя, поэтому ждём,
        // пока у этого принтера нет активной отправки и прошёл запас времени.
        if(printingFile(state,age,m.filename()))return Decision.CLEAR;
        JSONArray reserved=sends.optJSONArray("reserved_printer_ids");
        if(reserved!=null)for(int i=0;i<reserved.length();i++)if(m.printerId().equals(reserved.optString(i)))return Decision.KEEP;
        for(JSONObject job:FarmRepository.rows(jobs))if(m.printerId().equals(FarmValues.text(job,"printer_id"))&&!terminal(FarmValues.text(job,"state")))return Decision.KEEP;
        if(fetchedAt-m.createdAt()<UNKNOWN_GRACE_MS)return Decision.KEEP;
        return jobs.length()==0?Decision.SOFT_RESTART:Decision.SOFT_GONE;
    }
    /** Применяет decide ко всем отметкам этого FM. Возвращает true, если что-то изменилось. */
    public synchronized boolean resolve(String origin,JSONObject sends,long fetchedAt,Function<String,JSONObject> states,long age){
        List<Mark> marks=all(),next=new ArrayList<>();boolean changed=false;
        for(Mark m:marks){
            if(!m.origin().equals(origin)||m.printerId().isEmpty()){next.add(m);continue;}
            Decision d=decide(m,sends,fetchedAt,states.apply(m.printerId()),age);
            switch(d){
                case CLEAR->changed=true;
                case SOFT_GONE,SOFT_RESTART->{next.add(new Mark(m.origin(),m.printerId(),m.filename(),m.jobId(),true,d==Decision.SOFT_RESTART?SOFT_RESTART:SOFT_GONE,m.createdAt(),fetchedAt));changed=true;}
                default->next.add(m);
            }
        }
        if(!changed)return false;
        try{return save(next);}catch(JSONException ex){return false;}
    }
    /** Текст для панели отправок. */
    public static String describe(Mark m){
        if(m.printerId().isEmpty())return I18n.t("Не удалось прочитать отметку прошлого запуска. Проверьте отправки в FM.");
        if(!m.soft())return I18n.t("Результат запуска нужно проверить.");
        return SOFT_RESTART.equals(m.softReason())?I18n.t("FM не помнит эту отправку — вероятно, FM перезапускался. Проверьте принтер; новые запуски с телефона не заблокированы."):I18n.t("Отправки больше нет в списке FM. Проверьте принтер; новые запуски с телефона не заблокированы.");
    }
}
