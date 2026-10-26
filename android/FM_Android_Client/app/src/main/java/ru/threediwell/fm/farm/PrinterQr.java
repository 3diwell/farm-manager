// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import ru.threediwell.fm.inventory.Labels;
import ru.threediwell.fm.i18n.I18n;

/** Existing slot stickers identify a printer without changing its material binding. */
public final class PrinterQr {
    private PrinterQr(){}
    public static String server(JSONObject data) {
        JSONObject mobile=data.optJSONObject("mobile");
        String id=mobile!=null&&mobile.optInt("protocol")==1?mobile.optString("server_id"):"";
        if(!id.matches("[A-Za-z0-9_-]{1,100}"))throw new IllegalArgumentException(I18n.t("FM не поддерживает чтение этих наклеек принтеров."));
        return id;
    }
    public static JSONArray catalog(JSONArray printers) throws JSONException {
        JSONArray rows=new JSONArray();
        for(JSONObject p:FarmRepository.rows(printers))rows.put(new JSONObject().put("id",p.getString("id")).put("caption",p.optString("name",p.getString("id"))));
        if(rows.toString().length()>120000)throw new IllegalArgumentException(I18n.t("Список принтеров слишком большой для сканера."));
        return rows;
    }
    public static JSONObject resolve(String raw,String server,JSONArray printers) {
        Labels.Label label=Labels.parse(Labels.normalize(raw),server);
        if(!"slot".equals(label.kind()))throw new IllegalArgumentException(I18n.t("Это код катушки. Наведите камеру на наклейку позиции принтера."));
        JSONObject found=null;
        for(JSONObject p:FarmRepository.rows(printers))if(label.id().equals(p.optString("id"))){
            if(found!=null)throw new IllegalArgumentException(I18n.t("Не удалось однозначно найти принтер в FM."));found=p;
        }
        if(found==null)throw new IllegalArgumentException(I18n.t("Принтер с этой наклейки отсутствует в текущем FM."));
        return found;
    }
}
