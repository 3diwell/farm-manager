// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.scan;

import ru.threediwell.fm.i18n.I18n;
import java.util.*;
import org.json.*;
import ru.threediwell.fm.inventory.Labels;
import ru.threediwell.fm.farm.PrinterQr;

/** Read-only routing. Captured codes never grant authority to change stock. */
public final class ScanPolicy {
    public static final String SLOT="slot", SPOOL="spool", ANY="any", PRINTER="printer";
    private final String purpose,server;
    private final Map<String,String> slots=new HashMap<>();
    private final JSONArray printers;
    public ScanPolicy(String purpose,String server,String catalog) {
        this.purpose=purpose==null?SPOOL:purpose;this.server=server==null?"":server;
        if(!Arrays.asList(SLOT,SPOOL,ANY,PRINTER).contains(this.purpose))throw new IllegalArgumentException(I18n.t("Неизвестная задача сканирования"));
        try {
            JSONArray a=new JSONArray(catalog==null?"[]":catalog);
            printers=printerOnly()?a:new JSONArray();
            for(int i=0;i<a.length();i++) {
                JSONObject row=a.getJSONObject(i);if(printerOnly()){row.getString("id");row.getString("caption");continue;}String code=row.getString("code");
                if(!Labels.parse(code,this.server).kind().equals("slot"))throw new IllegalArgumentException(I18n.t("Неверная позиция"));
                slots.put(code,row.getString("caption"));
            }
        }catch(JSONException e){throw new IllegalArgumentException(I18n.t("Не удалось загрузить позиции FM"),e);}
    }
    public boolean slotOnly(){return SLOT.equals(purpose);}
    public boolean printerOnly(){return PRINTER.equals(purpose);}
    public boolean qrOnly(){return slotOnly()||printerOnly();}
    public String caption(String raw) {
        String code=Labels.normalize(raw);
        if(printerOnly())return PrinterQr.resolve(code,server,printers).optString("caption");
        if(code.startsWith("fm1:")) {
            Labels.Label label=Labels.parse(code,server);
            if(label.kind().equals("slot")) {
                if(SPOOL.equals(purpose))throw new IllegalArgumentException(I18n.t("Это позиция. Наведите на код катушки."));
                String caption=slots.get(code);
                if(caption==null)throw new IllegalArgumentException(I18n.t("Позиция недоступна. Вернитесь и обновите данные FM."));
                return caption;
            }
            if(slotOnly())throw new IllegalArgumentException(I18n.t("Это катушка. Наведите на QR слота или держателя."));
            return I18n.t("Катушка FM · ")+label.id();
        }
        if(slotOnly())throw new IllegalArgumentException(I18n.t("Нужен QR позиции этого склада FM."));
        return code;
    }
    public boolean needsConfirmation(String code){return !printerOnly()&&code.trim().startsWith("fm1:slot:");}
}
