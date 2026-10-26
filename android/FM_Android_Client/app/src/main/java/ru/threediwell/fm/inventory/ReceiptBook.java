// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;

import ru.threediwell.fm.i18n.I18n;
import org.json.*;
import java.util.*;

/** Локальный журнал подтверждённых приёмок. Не выполняет складских операций. */
public final class ReceiptBook {
    private final JSONObject book;
    public ReceiptBook(String raw) throws JSONException { book = new JSONObject(raw); }
    private JSONArray batches() throws JSONException {
        JSONArray rows=book.optJSONArray("batches");
        if(book.has("batches")&&rows==null)throw new JSONException(I18n.t("Повреждён локальный журнал партий. Не очищайте данные приложения."));
        if(rows==null) { rows=new JSONArray(); book.put("batches",rows); }
        return rows;
    }
    public List<JSONObject> list(String server) throws JSONException {
        List<JSONObject> out=new ArrayList<>(); JSONArray a=batches();
        for(int i=a.length()-1;i>=0;i--) if(server.equals(a.getJSONObject(i).getString("server"))) out.add(a.getJSONObject(i));
        return out;
    }
    public JSONObject get(String server,String id) throws JSONException {
        for(JSONObject b:list(server)) if(id.equals(b.getString("id"))) return b;
        throw new IllegalArgumentException(I18n.t("Партия не найдена в этом складе"));
    }
    public JSONObject active(String server) throws JSONException {
        for(JSONObject b:list(server)) if(b.optBoolean("active")) return b;
        return null;
    }
    public JSONObject start(String server,String id,String name) throws JSONException {
        if(server.isEmpty()||id.isEmpty()) throw new IllegalArgumentException(I18n.t("Не указан склад или номер партии"));
        for(JSONObject b:list(server)) if(id.equals(b.getString("id"))) return b;
        for(JSONObject b:list(server)) b.put("active",false);
        JSONObject b=new JSONObject().put("server",server).put("id",id).put("name",name)
                .put("active",true).put("entries",new JSONArray()); batches().put(b); return b;
    }
    public void record(String server,String batchId,String name,JSONObject result,JSONObject body,String caption) throws JSONException {
        if(!result.optBoolean("ok")||result.optString("id").isEmpty()) throw new IllegalArgumentException(I18n.t("Нет подтверждения приёмки от FM"));
        if(!server.equals(body.getJSONObject("mobile").getString("server_id"))) throw new IllegalArgumentException(I18n.t("Другая ферма"));
        // Повтор подтверждённого запроса не добавляет вторую этикетку, даже в другой партии.
        for(JSONObject b:list(server)) for(int i=0;i<b.getJSONArray("entries").length();i++)
            if(result.getString("id").equals(b.getJSONArray("entries").getJSONObject(i).getString("id"))) return;
        JSONObject batch;
        try { batch=get(server,batchId); } catch(IllegalArgumentException missing) { batch=start(server,batchId,name); }
        batch.getJSONArray("entries").put(new JSONObject().put("id",result.getString("id"))
                .put("caption",caption).put("location",body.optString("location"))
                .put("weight_total_g",body.optDouble("weight_total_g")));
    }
    @Override public String toString() { return book.toString(); }
}
