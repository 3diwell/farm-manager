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

/**
 * Нагрев во время печати. Выключить нагрев сопла или стола, пока принтер печатает или готовится, —
 * сорвать печать: FM без "force": true отвечает 409 heater_off_while_printing. На паузе — можно.
 * Телефон не предлагает «Выкл.» во время печати и спрашивает перед повтором с force.
 */
public final class HeaterPolicy {
    private HeaterPolicy(){}
    public static final String HEATER_OFF_WHILE_PRINTING="heater_off_while_printing";
    /** Печать идёт (не пауза). SLICING — подготовка печати у FM, на телефоне тоже не даём выключить нагрев. */
    public static boolean activePrint(JSONObject s){return s!=null&&Arrays.asList("RUNNING","PREPARE","SLICING").contains(FarmValues.text(s,"status"));}
    /** Кнопку «Выкл.» показываем только вне печати (или на паузе) и при свежих данных. */
    public static boolean offOffered(JSONObject p,JSONObject s,long age){return PrinterCommand.allowed(p,s,age,"heat")&&!activePrint(s);}
    public static boolean turnsOff(PrinterCommand c){return c.temperature!=null&&c.temperature==0&&Arrays.asList("nozzle","nozzle_l","nozzle_r","bed").contains(c.action);}
    public static boolean turnsOff(PreheatPresets.Preset preset){return preset.nozzle==0||preset.bed==0;}
    /** Предупреждение в подтверждении; пустая строка — предупреждать не о чем. */
    public static String warning(JSONObject s,PreheatPresets.Preset preset,boolean cool){
        if(activePrint(s))return cool||turnsOff(preset)?I18n.t("Идёт печать: выключение нагрева сорвёт её."):I18n.t("Идёт печать: новые температуры сразу применятся к ней и могут её испортить.");
        if(PrinterCommand.paused(s))return I18n.t("Печать на паузе: изменятся целевые температуры текущей печати.");
        return "";
    }
    /** FM отказал, потому что выключение нагрева сорвёт печать: нужно согласие и повтор с "force": true. */
    public static boolean needsForce(Throwable ex){for(Throwable e=ex;e!=null;e=e.getCause())if(e instanceof FmApi.Rejected&&HEATER_OFF_WHILE_PRINTING.equals(((FmApi.Rejected)e).code))return true;return false;}
}
