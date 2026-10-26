// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;

import ru.threediwell.fm.i18n.I18n;
import org.json.*;
import ru.threediwell.fm.core.FmApi;
import ru.threediwell.fm.nfc.NfcReading;
import java.util.*;

public final class InventoryRepository {
    private final FmApi api;
    public JSONObject data = new JSONObject(), ams = new JSONObject(), places = new JSONObject();
    public String server = "";
    public InventoryRepository(FmApi api) { this.api = api; }
    public void refresh() throws Exception {
        JSONObject next = api.call("GET", "/api/mod/inventory/filament", null);
        JSONObject mobile = next.optJSONObject("mobile");
        server = mobile != null && mobile.optInt("protocol") == 1 ? mobile.optString("server_id") : "";
        JSONObject nextPlaces = api.call("GET", "/api/mod/inventory/locations", null);
        JSONObject nextAms = api.call("GET", "/api/mod/inventory/ams", null);
        data = next; places = nextPlaces; ams = nextAms;
    }
    public List<JSONObject> rows(JSONObject obj, String key) {
        List<JSONObject> out = new ArrayList<>(); JSONArray a = obj.optJSONArray(key);
        if (a != null) for (int i = 0; i < a.length(); i++) if (a.optJSONObject(i) != null) out.add(a.optJSONObject(i));
        return out;
    }
    public JSONObject mapping(String code) {
        JSONObject mobile = data.optJSONObject("mobile");
        if (mobile != null) for (JSONObject r : rows(mobile, "codes")) if (r.optString("code").equals(code)) return r;
        return null;
    }
    public List<JSONObject> findSpools(String raw) {
        String code = Labels.normalize(raw), sid = "", fid = "";
        if (code.startsWith("fm1:")) {
            Labels.Label label = Labels.parse(code, server);
            if (!label.kind().equals("spool")) throw new IllegalArgumentException(I18n.t("Нужна метка катушки, не позиции"));
            sid = label.id();
        } else {
            JSONObject m = mapping(code);
            if (m != null) {
                if (m.optString("kind").equals("unique")) sid = m.optString("spool_id");
                else fid = m.optString("filament_id");
            }
        }
        List<JSONObject> out = new ArrayList<>();
        for (JSONObject s : rows(data, "spools")) {
            if ((!sid.isEmpty() && sid.equals(s.optString("id"))) || (!fid.isEmpty() && fid.equals(s.optString("filament_id")))
                    || (!code.startsWith("fm1:") && code.equals(s.optString("nfc_uid")))) out.add(s);
        }
        return out;
    }
    public JSONObject envelope(String code, String kind) throws JSONException {
        return new JSONObject().put("protocol", 1).put("server_id", server).put("request_id", UUID.randomUUID().toString())
                .put("code", code).put("code_kind", kind);
    }
    public boolean supportsSlotExchange() {
        return supports("slot_exchange_v2");
    }
    public boolean supportsPreparedLabels() {return supports("prepared_labels_v3");}
    public boolean supportsNfc() {return supports("nfc_spools_v4");}
    public boolean supportsWriteOff() {return !server.isEmpty()&&supports("empty_spool_writeoff_v6");}
    /** Product barcodes identify a material, never the physical spool being discarded. */
    public JSONObject writeOffSpool(String raw) {
        String code=Labels.normalize(raw),sid;
        if(code.startsWith("fm1:")) {
            Labels.Label label=Labels.parse(code,server);
            if(!label.kind().equals("spool"))throw new IllegalArgumentException(I18n.t("Для списания нужен индивидуальный QR катушки."));
            sid=label.id();
        } else {
            JSONObject mapped=mapping(code);
            if(mapped==null||!"unique".equals(mapped.optString("kind"))||mapped.optString("spool_id").isEmpty())
                throw new IllegalArgumentException(I18n.t("Для списания нужен индивидуальный QR катушки. Общий код товара не подходит."));
            sid=mapped.optString("spool_id");
        }
        return spool(sid);
    }
    public JSONObject writeOffRequest(String sid) throws JSONException {
        if(!supportsWriteOff())throw new IllegalArgumentException(I18n.t("Модуль склада не поддерживает списание пустых катушек. Обновите модуль FM."));
        JSONObject s=spool(sid);
        if(s.optBoolean("is_deleted")||s.optInt("is_deleted",0)!=0)throw new IllegalArgumentException(I18n.t("Катушка уже списана или удалена."));
        if(s.optBoolean("pending"))throw new IllegalArgumentException(I18n.t("Катушка участвует в незавершённой печати"));
        double weight=s.optDouble("weight_remaining_g",Double.NaN);
        if(!Double.isFinite(weight)||weight<0)throw new IllegalArgumentException(I18n.t("Не удалось проверить остаток катушки. Обновите данные FM."));
        String pid=s.optString("ams_printer_id");int slot=s.getInt("ams_slot");
        if(!pid.isEmpty()) {
            JSONObject occupant=position(new Labels.Label("slot",server,pid,slot)).optJSONObject("spool");
            if(occupant==null||!sid.equals(occupant.optString("id")))throw new IllegalArgumentException(I18n.t("Привязка изменилась или неоднозначна. Обновите данные."));
        }
        JSONObject mobile=new JSONObject().put("protocol",6).put("operation","writeoff").put("server_id",server).put("request_id",UUID.randomUUID().toString());
        return new JSONObject().put("mobile",mobile).put("spool_id",sid).put("confirm_empty",true)
                .put("expected_filament_id",s.getString("filament_id")).put("expected_printer_id",pid)
                .put("expected_ams_slot",slot).put("expected_weight_remaining_g",weight);
    }
    /** «Пустая» катушка с заметным остатком — почти всегда неверный скан. Выше этих порогов списание
     *  требует отдельного подтверждения с числом граммов. */
    public static final double WRITE_OFF_FREE_G=50, WRITE_OFF_FREE_SHARE=0.05;
    /** remaining — остаток, который уйдёт в FM (expected_weight_remaining_g); total — номинал катушки (weight_total_g, может быть неизвестен). */
    public static boolean heavyWriteOff(double remaining,double total) {
        if(!Double.isFinite(remaining)||remaining<=0)return false;
        return remaining>WRITE_OFF_FREE_G||(Double.isFinite(total)&&total>0&&remaining>total*WRITE_OFF_FREE_SHARE);
    }
    /** Тот же вопрос для запроса списания (writeOffRequest или снимок замены со списанием); пусто — подтверждать не нужно. */
    public String heavyWriteOffQuestion(JSONObject request) {
        double remaining=request.optDouble("expected_weight_remaining_g",Double.NaN);
        JSONObject s=spool(request.optString("spool_id"));
        double total=s.isNull("weight_total_g")?Double.NaN:s.optDouble("weight_total_g",Double.NaN);
        return heavyWriteOff(remaining,total)?heavyWriteOffQuestion(remaining):"";
    }
    public static String heavyWriteOffQuestion(double remaining) {
        return I18n.t("На катушке ещё {g} г. Списать {g} г?").replace("{g}",grams(remaining));
    }
    public static String heavyWriteOffButton(double remaining) {return I18n.t("Списать {g} г").replace("{g}",grams(remaining));}
    /** Целые граммы, но 50,4 г не округляются до «50» у порога: показываем десятые, если они есть. */
    public static String grams(double value) {
        long whole=Math.round(value);
        if(Math.abs(value-whole)<0.05)return String.valueOf(whole);
        return String.format(Locale.ROOT,"%.1f",value).replace('.',I18n.language().equals("en")?'.':',');
    }
    public boolean supportsReplaceWriteOff() {return supportsWriteOff()&&supportsSlotExchange()&&supports("slot_replace_writeoff_v7");}
    /** Immutable confirmation context: refreshes and scanner fallbacks cannot change the chosen old spool. */
    public record SlotSelection(Labels.Label target,String expectedSpoolId,String writeOffSnapshot) {
        public boolean discard() {return !writeOffSnapshot.isEmpty();}
    }
    public SlotSelection selectSlot(Labels.Label target,String displayedSpoolId,boolean discard) throws JSONException {
        SlotSelection choice=new SlotSelection(target,displayedSpoolId,"");
        validateSelection(choice);
        if(!discard)return choice;
        if(!supportsReplaceWriteOff())throw new IllegalArgumentException(I18n.t("Модуль склада не поддерживает замену со списанием. Обновите модуль FM."));
        if(displayedSpoolId.isEmpty())throw new IllegalArgumentException(I18n.t("Позиция уже свободна. Снимать нечего."));
        SlotSelection result=new SlotSelection(target,displayedSpoolId,writeOffRequest(displayedSpoolId).toString());
        validateSelection(result);
        return result;
    }
    public void validateSelection(SlotSelection choice) throws JSONException {
        JSONObject occupant=position(choice.target()).optJSONObject("spool");
        if(!choice.expectedSpoolId().equals(occupant==null?"":occupant.optString("id")))
            throw new IllegalArgumentException(I18n.t("Катушка в слоте изменилась. Выберите слот и действие заново."));
        if(choice.discard()) {
            if(!supportsReplaceWriteOff())throw new IllegalArgumentException(I18n.t("Модуль склада не поддерживает замену со списанием. Обновите модуль FM."));
            JSONObject before=new JSONObject(choice.writeOffSnapshot()),now=writeOffRequest(choice.expectedSpoolId());
            if(!choice.target().id().equals(before.getString("expected_printer_id"))||choice.target().slot()!=before.getInt("expected_ams_slot"))
                throw new IllegalArgumentException(I18n.t("Привязка изменилась или неоднозначна. Обновите данные."));
            for(String key:List.of("spool_id","expected_filament_id","expected_printer_id","expected_ams_slot","expected_weight_remaining_g"))
                if(!before.get(key).toString().equals(now.get(key).toString()))
                    throw new IllegalArgumentException(I18n.t("Данные старой катушки изменились. Выберите слот и действие заново."));
        }
    }
    public JSONObject replaceWriteOffRequest(SlotSelection choice,String newSid) throws JSONException {
        validateSelection(choice);
        if(!choice.discard()||choice.expectedSpoolId().equals(newSid))throw new IllegalArgumentException(I18n.t("Для замены нужна другая катушка."));
        JSONObject s=spool(newSid);
        if(s.optBoolean("is_deleted")||s.optInt("is_deleted",0)!=0)throw new IllegalArgumentException(I18n.t("Катушка уже списана или удалена."));
        if(s.optBoolean("pending"))throw new IllegalArgumentException(I18n.t("Катушка участвует в незавершённой печати"));
        if(!s.optString("ams_printer_id").isEmpty())throw new IllegalArgumentException(I18n.t("Новая катушка установлена в другом месте. Сначала снимите её через «Снять катушку с принтера»."));
        double weight=s.optDouble("weight_remaining_g",Double.NaN);
        if(!Double.isFinite(weight)||weight<=0)throw new IllegalArgumentException(I18n.t("У новой катушки нет подтверждённого положительного остатка."));
        JSONObject body=new JSONObject(choice.writeOffSnapshot());
        body.getJSONObject("mobile").put("protocol",7).put("operation","replace_writeoff").put("request_id",UUID.randomUUID().toString());
        return body.put("new_spool_id",newSid).put("expected_new_filament_id",s.getString("filament_id")).put("expected_new_weight_remaining_g",weight);
    }
    public JSONObject nfcEnvelope(String operation,String uid) throws JSONException {
        if(!supportsNfc())throw new IllegalArgumentException(I18n.t("Для операций NFC обновите модуль склада до расширения 0.7. Обычные QR продолжают работать."));
        if(!Arrays.asList("nfc_receipt","nfc_attach").contains(operation))throw new IllegalArgumentException(I18n.t("Неизвестная операция NFC"));
        return new JSONObject().put("protocol",4).put("operation",operation).put("nfc_uid",NfcReading.uid(uid))
                .put("server_id",server).put("request_id",UUID.randomUUID().toString());
    }
    public JSONObject nfcAttachRequest(String sid,String uid) throws JSONException {
        JSONObject s=spool(sid);
        return new JSONObject().put("mobile",nfcEnvelope("nfc_attach",uid)).put("spool_id",sid)
                .put("expected_filament_id",s.getString("filament_id"));
    }
    /** Returns exactly one live owner or null; deleted/ambiguous/product matches fail closed. */
    public JSONObject nfcSpool(String raw) {
        String uid=NfcReading.uid(raw);Set<String> ids=new HashSet<>();JSONObject m=data.optJSONObject("mobile");
        if(m!=null) {
            for(JSONObject r:rows(m,"nfc_tags"))if(uid.equals(r.optString("uid")))ids.add(r.optString("spool_id"));
            for(JSONObject r:rows(m,"codes"))if(uid.equals(NfcReading.legacyUid(r.optString("code")))) {
                if(!"unique".equals(r.optString("kind"))||r.optString("spool_id").isEmpty())throw new IllegalArgumentException(I18n.t("UID совпал с общим кодом товара. Проверьте записи в FM; автоматический выбор запрещён."));
                ids.add(r.optString("spool_id"));
            }
        }
        for(JSONObject s:rows(data,"spools"))if(uid.equals(NfcReading.legacyUid(s.optString("nfc_uid"))))ids.add(s.optString("id"));
        if(ids.size()>1)throw new IllegalArgumentException(I18n.t("NFC связан с несколькими карточками. Сначала исправьте конфликт в FM."));
        if(ids.isEmpty())return null;
        String id=ids.iterator().next();
        for(JSONObject s:rows(data,"spools"))if(id.equals(s.optString("id"))&&!s.optBoolean("is_deleted")&&s.optInt("is_deleted",0)==0)return s;
        throw new IllegalArgumentException(I18n.t("Эта NFC-метка уже учтена, но карточка удалена или недоступна. Повторная приёмка запрещена."));
    }
    private boolean supports(String feature) {
        JSONObject mobile = data.optJSONObject("mobile");
        JSONArray features = mobile == null ? null : mobile.optJSONArray("features");
        if (features != null) for (int i=0;i<features.length();i++)
            if (feature.equals(features.optString(i))) return true;
        return false;
    }
    public List<JSONObject> preparedBatches() {
        JSONObject m=data.optJSONObject("mobile");return m==null?new ArrayList<>():rows(m,"prepared_batches");
    }
    public JSONObject preparedBatch(String id) {
        for(JSONObject b:preparedBatches())if(id.equals(b.optString("id")))return b;
        throw new IllegalArgumentException(I18n.t("Партия этикеток не найдена. Обновите данные FM."));
    }
    public List<JSONObject> preparedLabels(String batchId) {
        preparedBatch(batchId);List<JSONObject> out=new ArrayList<>();JSONObject m=data.optJSONObject("mobile");
        for(JSONObject l:rows(m,"prepared_labels"))if(batchId.equals(l.optString("batch_id")))out.add(l);
        return out;
    }
    public JSONObject preparedEnvelope(String operation) throws JSONException {
        if(!supportsPreparedLabels())throw new IllegalArgumentException(I18n.t("Для подготовки этикеток обновите модуль склада до мобильной версии 0.4"));
        if(!Arrays.asList("prepare_labels","claim_label","cancel_labels").contains(operation))throw new IllegalArgumentException(I18n.t("Неизвестная операция с этикетками"));
        return new JSONObject().put("protocol",3).put("server_id",server).put("request_id",UUID.randomUUID().toString()).put("operation",operation);
    }
    public JSONObject claimRequest(String raw,String batchId,String location) throws JSONException {
        Labels.Label label=Labels.parse(Labels.normalize(raw),server);
        if(!label.kind().equals("spool"))throw new IllegalArgumentException(I18n.t("Сканируйте подготовленную метку катушки, не QR позиции"));
        JSONObject ticket=null;for(JSONObject l:preparedLabels(batchId))if(label.id().equals(l.optString("id"))){ticket=l;break;}
        if(ticket==null)throw new IllegalArgumentException(I18n.t("Этикетка не относится к выбранной партии. Откройте её партию или проверьте QR."));
        if("cancelled".equals(ticket.optString("status")))throw new IllegalArgumentException(I18n.t("Эта этикетка отменена. Приёмка запрещена."));
        boolean place=false;for(JSONObject l:rows(places,"locations"))if(location.equals(l.optString("id")))place=true;
        if(!place)throw new IllegalArgumentException(I18n.t("Место хранения не найдено. Выберите его заново."));
        return new JSONObject().put("mobile",preparedEnvelope("claim_label").put("code",raw.trim()))
                .put("batch_id",batchId).put("location",location);
    }
    public record ReceiptTarget(String kind,String spoolId,String batchId) {}
    /** Read-only dispatch for a single receipt entry point; never infer identity from product text. */
    public ReceiptTarget receiptTarget(String raw) {
        String code=Labels.normalize(raw);
        if(!code.startsWith("fm1:"))return new ReceiptTarget("factory","","");
        Labels.Label label=Labels.parse(code,server);
        if(!label.kind().equals("spool"))throw new IllegalArgumentException(I18n.t("Это QR позиции принтера. Для приёмки нужен код катушки."));
        JSONObject m=data.optJSONObject("mobile");
        if(m!=null)for(JSONObject ticket:rows(m,"prepared_labels"))if(label.id().equals(ticket.optString("id"))) {
            String state=ticket.optString("status");
            if("cancelled".equals(state))throw new IllegalArgumentException(I18n.t("Этикетка отменена. Приёмка запрещена."));
            if(!Arrays.asList("prepared","received").contains(state))throw new IllegalArgumentException(I18n.t("Неизвестное состояние этикетки. Обновите модуль."));
            String batch=ticket.optString("batch_id");preparedBatch(batch);
            return new ReceiptTarget("prepared",label.id(),batch);
        }
        for(JSONObject s:rows(data,"spools"))if(label.id().equals(s.optString("id")))return new ReceiptTarget("existing",label.id(),"");
        throw new IllegalArgumentException(I18n.t("QR относится к этому складу, но катушка или подготовленная этикетка не найдена. Новый приход не выполнен."));
    }
    public JSONObject automaticClaimRequest(String raw,String location) throws JSONException {
        ReceiptTarget target=receiptTarget(raw);
        if(!"prepared".equals(target.kind()))throw new IllegalArgumentException(I18n.t("Это не подготовленная этикетка новой катушки."));
        return claimRequest(raw,target.batchId(),location);
    }
    public JSONObject spool(String sid) {
        for (JSONObject s : rows(data,"spools")) if (s.optString("id").equals(sid)) return s;
        throw new IllegalArgumentException(I18n.t("Катушка больше не найдена. Обновите данные склада."));
    }
    public JSONObject position(Labels.Label target) {
        if (!target.kind().equals("slot") || !target.server().equals(server))
            throw new IllegalArgumentException(I18n.t("Это не позиция выбранного склада FM"));
        for (JSONObject p : rows(ams,"printers")) if (p.optString("printer_id").equals(target.id()))
            for (JSONObject s : rows(p,"slots")) if (s.optInt("index",-99)==target.slot()
                    && !s.optBoolean("offline") && !s.optBoolean("unconfirmed")) return s;
        throw new IllegalArgumentException(I18n.t("Позиция отсутствует или не подтверждена. Обновите данные FM."));
    }
    public JSONObject slotRequest(Labels.Label target, String operation, String expectedSid) throws JSONException {
        if (!supportsSlotExchange()) throw new IllegalArgumentException(I18n.t("Обновите модуль склада до мобильной версии 0.2: снятие и замена пока недоступны."));
        if (!Arrays.asList("bind","replace","unbind").contains(operation)) throw new IllegalArgumentException(I18n.t("Неизвестная операция"));
        position(target);
        JSONObject m = envelope(Labels.slot(server,target.id(),target.slot()),"unique").put("protocol",2).put("operation",operation);
        return new JSONObject().put("mobile",m).put("printer_id",target.id()).put("ams_slot",target.slot())
                .put("external",target.slot()==-1).put("expected_spool_id",expectedSid);
    }
    public static String title(JSONObject row) {
        return (row.optString("vendor_name") + " " + row.optString("material") + " · " + row.optString("color_name")
                + " · Ø " + row.optString("diameter") + I18n.t(" мм")).trim();
    }
}
