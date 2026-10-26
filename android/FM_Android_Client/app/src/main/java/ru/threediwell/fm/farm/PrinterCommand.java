// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import ru.threediwell.fm.i18n.I18n;
import java.util.*;

/** Только штатные действия FM: телефон не формирует G-code и не запускает файл этим путём. */
public final class PrinterCommand {
    public final String action;
    public final Integer temperature;
    private PrinterCommand(String action,Integer temperature){this.action=action;this.temperature=temperature;}
    public static PrinterCommand control(String action){
        if(!Arrays.asList("pause","resume","stop").contains(action))throw new IllegalArgumentException(I18n.t("Команда принтера не поддерживается."));
        return new PrinterCommand(action,null);
    }
    public static PrinterCommand heat(String action,int temperature){
        int max=switch(action){case "nozzle","nozzle_l","nozzle_r"->350;case "bed"->120;case "chamber"->65;default->-1;};
        if(temperature<0||temperature>max)throw new IllegalArgumentException(I18n.t("Температура вне допустимого диапазона FM."));
        return new PrinterCommand(action,temperature);
    }
    public JSONObject body() throws JSONException{return new JSONObject().put("cmd",action).put("val",temperature==null?"":Integer.toString(temperature));}
    /** force — только после явного согласия выключить нагрев во время печати (ответ FM 409 heater_off_while_printing). */
    public JSONObject body(boolean force) throws JSONException{JSONObject b=body();if(force)b.put("force",true);return b;}
    public static boolean supported(JSONObject p){return p!=null&&Arrays.asList("bambu","klipper","flashforge","demo").contains(p.optString("type"));}
    public static boolean printing(JSONObject s){return s!=null&&Arrays.asList("RUNNING","PREPARE","SLICING","PAUSED","PAUSE").contains(s.optString("status"));}
    public static boolean paused(JSONObject s){return s!=null&&Arrays.asList("PAUSED","PAUSE").contains(s.optString("status"));}
    public static boolean allowed(JSONObject p,JSONObject s,long age,String action){
        if(!supported(p)||!PrinterState.fresh(s,age))return false;
        return switch(action){case "pause"->printing(s)&&!paused(s);case "resume"->paused(s);case "stop"->printing(s);case "heat"->printing(s)||Arrays.asList("IDLE","FINISH","FAILED","ERROR").contains(s.optString("status"));default->false;};
    }
    public static boolean chamber(JSONObject p,JSONObject s){
        return supported(p)&&!"flashforge".equals(p.optString("type"))&&(PrintRequest.flag(p,"chamber_heater")||(s!=null&&PrintRequest.flag(s,"chamber_heater")));
    }
    public static List<PrinterCommand> preheat(JSONObject p,JSONObject s,PreheatPresets.Preset preset){
        if(!supported(p))throw new IllegalArgumentException(I18n.t("Команда принтера не поддерживается."));
        List<PrinterCommand> commands=new ArrayList<>();
        if("bambu".equals(p.optString("type"))&&s!=null&&s.optInt("nozzle_count",1)>=2){commands.add(heat("nozzle_l",preset.nozzle));commands.add(heat("nozzle_r",preset.nozzle));}
        else commands.add(heat("nozzle",preset.nozzle));
        commands.add(heat("bed",preset.bed));
        if(preset.chamber!=null&&chamber(p,s))commands.add(heat("chamber",preset.chamber));
        return Collections.unmodifiableList(commands);
    }
    public String caption(){return switch(action){case "pause"->I18n.t("Пауза");case "resume"->I18n.t("Продолжить печать");case "stop"->I18n.t("Остановить печать");case "nozzle"->I18n.t("Сопло");case "nozzle_l"->I18n.t("Левое сопло");case "nozzle_r"->I18n.t("Правое сопло");case "bed"->I18n.t("Стол");case "chamber"->I18n.t("Термокамера");default->action;};}
    /**
     * Понятный текст для отказов доставки команды (FM отвечает 502 с reason). null — код не из этого списка.
     * Состояние принтера на экране при таких ответах не меняется: его по-прежнему показывает телеметрия.
     */
    public static String deliveryText(Throwable ex){
        for(Throwable e=ex;e!=null;e=e.getCause()){
            String code=e instanceof ru.threediwell.fm.core.FmApi.ServerError?((ru.threediwell.fm.core.FmApi.ServerError)e).code:e instanceof ru.threediwell.fm.core.FmApi.Rejected?((ru.threediwell.fm.core.FmApi.Rejected)e).code:null;
            if(code==null)continue;
            switch(code){
                case "command_not_delivered":return I18n.t("Команда не дошла до принтера — проверьте связь.");
                case "command_not_confirmed":return I18n.t("Принтер не подтвердил команду — проверьте его состояние.");
                case "stop_not_delivered":return I18n.t("Команда «Стоп» не дошла до принтера — печать продолжается.");
                default:return null;
            }
        }
        return null;
    }
    /** Неизвестный или частичный результат требует проверки; автоматического повтора нет. */
    public static final class Failure extends java.io.IOException {
        /** true — FM точно сообщил, что команда не дошла или не подтверждена; сообщение показывается как есть. */
        public final boolean delivery;
        public Failure(String message,Exception cause){this(message,cause,false);}
        public Failure(String message,Exception cause,boolean delivery){super(message,cause);this.delivery=delivery;}
    }
    /** FM не выключил нагрев во время печати без согласия. Повтор — только после ответа человека «да». */
    public static final class NeedsForce extends java.io.IOException {
        public final String printerId;public final PreheatPresets.Preset preset;public final boolean cool;public final int next;public final List<String> accepted;
        public NeedsForce(String printerId,PreheatPresets.Preset preset,boolean cool,int next,List<String> accepted,Exception cause){
            super(I18n.t("Печать сорвётся — выключить нагрев?"),cause);this.printerId=printerId;this.preset=preset;this.cool=cool;this.next=next;this.accepted=Collections.unmodifiableList(new ArrayList<>(accepted));
        }
    }
}
