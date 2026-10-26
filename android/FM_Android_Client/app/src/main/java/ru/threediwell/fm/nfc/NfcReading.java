// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;

import ru.threediwell.fm.i18n.I18n;
import org.json.*;
import java.util.Locale;

/** Validated result of a complete Bambu read; never a guessed UID-only product. */
public final class NfcReading {
    public final String uid,material,variant,rgba;
    public final double diameter;
    public final int weight;
    public NfcReading(JSONObject value) throws JSONException {
        uid=uid(value.getString("uid"));material=value.getString("material");variant=value.getString("variant");
        rgba=value.getString("rgba");diameter=value.getDouble("diameter");weight=value.getInt("weight");
        if(material.isEmpty()||material.length()>16||variant.isEmpty()||variant.length()>16
                ||!rgba.matches("[0-9A-F]{8}")||!Double.isFinite(diameter)||diameter<.5||diameter>5||weight<1||weight>10000)
            throw new IllegalArgumentException(I18n.t("Неполный результат NFC. Повторите чтение."));
    }
    public static String uid(String raw) {
        if(raw==null||!raw.matches("[0-9a-fA-F]{8}"))throw new IllegalArgumentException(I18n.t("Неверный UID Bambu. Повторите чтение."));
        return raw.toUpperCase(Locale.ROOT);
    }
    public static String legacyUid(String raw) {
        if(raw==null)return "";
        String s=raw.trim().toUpperCase(Locale.ROOT);
        if(s.startsWith("NFC:BAMBU:"))s=s.substring(10);
        s=s.replace(":","").replace(" ","").replace("-","");
        return s.matches("[0-9A-F]{8}")?s:"";
    }
    public static String code(String uid){return "nfc:bambu:"+uid(uid);}
    public static JSONObject from(BambuData data) throws JSONException {
        return new JSONObject().put("uid",data.uid).put("material",data.material).put("variant",data.variant)
                .put("rgba",data.rgba).put("diameter",data.diameter).put("weight",data.weight);
    }
    public String caption(){return variant+" · #"+rgba.substring(0,6)+" · "+String.format(Locale.ROOT,"%.3f",diameter)+I18n.t(" мм\nNFC: ")+uid;}
}
