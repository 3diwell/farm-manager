// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import ru.threediwell.fm.i18n.I18n;
import java.util.*;

/** Общие пресеты фермы. Умолчания и пределы взяты из web/app.js и политики команд ядра. */
public final class PreheatPresets {
    public static final int MAX_COUNT=24;
    public static final class Preset {
        public final String name;public final int nozzle,bed;public final Integer chamber;
        public Preset(String name,int nozzle,int bed,Integer chamber){
            String clean=name==null?"":name.trim().replaceAll("\\s+"," ");
            if(clean.isEmpty()||clean.codePointCount(0,clean.length())>12||clean.codePoints().anyMatch(c->c<32||c==127))throw new IllegalArgumentException(I18n.t("Имя пресета должно содержать от 1 до 12 знаков."));
            PrinterCommand.heat("nozzle",nozzle);PrinterCommand.heat("bed",bed);if(chamber!=null)PrinterCommand.heat("chamber",chamber);
            this.name=clean;this.nozzle=nozzle;this.bed=bed;this.chamber=chamber;
        }
        public JSONObject json() throws JSONException{return new JSONObject().put("name",name).put("n",nozzle).put("b",bed).put("c",chamber==null?JSONObject.NULL:chamber);}
        public boolean same(Preset other){return other!=null&&name.equals(other.name)&&nozzle==other.nozzle&&bed==other.bed&&Objects.equals(chamber,other.chamber);}
    }
    public final List<Preset> values;
    public PreheatPresets(List<Preset> values){
        if(values.size()>MAX_COUNT)throw new IllegalArgumentException(I18n.t("Можно сохранить не более 24 пресетов."));
        Set<String> names=new HashSet<>();for(Preset p:values)if(!names.add(p.name.toUpperCase(Locale.ROOT).toLowerCase(Locale.ROOT)))throw new IllegalArgumentException(I18n.t("Имена пресетов не должны повторяться."));
        this.values=Collections.unmodifiableList(new ArrayList<>(values));
    }
    public static PreheatPresets defaults(){return new PreheatPresets(Arrays.asList(new Preset("PLA",220,60,null),new Preset("PETG",235,70,null),new Preset("ABS",250,90,null)));}
    public static PreheatPresets read(JSONObject response) throws JSONException {
        if(!response.optBoolean("ok"))throw new JSONException(I18n.t("Не удалось прочитать пресеты FM."));
        JSONObject settings=response.getJSONObject("settings");
        if(!settings.has("preheat_presets"))return defaults();
        JSONArray rows=settings.getJSONArray("preheat_presets");List<Preset> values=new ArrayList<>();
        for(int i=0;i<rows.length();i++){JSONObject p=rows.getJSONObject(i);values.add(new Preset(p.getString("name"),number(p.get("n")),number(p.get("b")),p.isNull("c")||"".equals(p.opt("c"))?null:number(p.get("c"))));}
        return new PreheatPresets(values);
    }
    private static int number(Object value){
        if(!(value instanceof Number))throw new IllegalArgumentException(I18n.t("Укажите целые температуры в пределах FM."));
        double n=((Number)value).doubleValue();if(!Double.isFinite(n)||n!=Math.floor(n)||n<Integer.MIN_VALUE||n>Integer.MAX_VALUE)throw new IllegalArgumentException(I18n.t("Укажите целые температуры в пределах FM."));return (int)n;
    }
    public static int input(String value){
        if(value==null||!value.trim().matches("[0-9]{1,3}"))throw new IllegalArgumentException(I18n.t("Укажите целые температуры в пределах FM."));return Integer.parseInt(value.trim());
    }
    public JSONArray json() throws JSONException{JSONArray out=new JSONArray();for(Preset p:values)out.put(p.json());return out;}
    public Preset find(String name){for(Preset p:values)if(p.name.equals(name))return p;return null;}
    public boolean same(PreheatPresets other){if(other==null||values.size()!=other.values.size())return false;for(int i=0;i<values.size();i++)if(!values.get(i).same(other.values.get(i)))return false;return true;}
}
