// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import ru.threediwell.fm.i18n.I18n;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.*;
import ru.threediwell.fm.core.FmApi;

/** Чтение ядра и штатные команды. Не обращается к БД и протоколам принтеров. */
public final class FarmRepository {
    public final FmApi api;
    public volatile Capabilities capabilities;
    public FarmRepository(FmApi api){this.api=api;}
    public Capabilities refreshCapabilities() throws Exception {
        JSONObject auth=api.call("GET","/api/auth/status",null);
        if(!auth.optBoolean("authenticated"))throw new FmApi.Unauthorized();
        JSONArray modules;boolean known=true;
        try{modules=api.callArray("/api/modules","modules");}catch(FmApi.Unauthorized ex){throw ex;}catch(Exception ex){modules=new JSONArray();known=false;}
        capabilities=new Capabilities(auth,modules,known);return capabilities;
    }
    public JSONArray printers() throws Exception{return api.callArray("/api/printers");}
    public void requireInventory() throws java.io.IOException {
        if(capabilities==null||!capabilities.modulesKnown)throw new java.io.IOException(I18n.t("Не удалось проверить модули FM. Обновите данные, чтобы открыть склад."));
        if(!capabilities.inventory)throw new java.io.IOException(I18n.t("Модуль склада недоступен."));
    }
    public JSONArray projects() throws Exception{return api.callArray("/api/projects2");}
    public JSONArray tasks() throws Exception{return api.callArray("/api/staging");}
    public JSONObject project(String id) throws Exception{return api.call("GET","/api/projects2/"+segment(id)+"/tree",null);}
    public JSONObject sends() throws Exception{return api.call("GET","/api/send-jobs",null);}
    public String printerLabelServer() throws Exception {
        if(capabilities==null||!capabilities.inventory)return "";
        return PrinterQr.server(api.call("GET","/api/mod/inventory/filament",null));
    }
    public JSONObject scannedPrinter(String raw) throws Exception {
        refreshCapabilities();requireInventory();String server=printerLabelServer();
        return PrinterQr.resolve(raw,server,printers());
    }
    public RepeatPrint.Target repeatTarget(String id,java.util.function.Supplier<JSONObject> state,java.util.function.LongSupplier age) throws Exception {
        JSONObject p=controlledPrinter(id),history=null;
        if(RepeatPrint.reserved(sends(),id))throw new IllegalStateException(I18n.t("FM уже отправляет задание на этот принтер."));
        if(capabilities.moduleAvailable("quality"))history=api.call("GET","/api/mod/quality/print-runs?printer_id="+segment(id)+"&limit=2",null);
        RepeatPrint.Last last=RepeatPrint.last(history,p,state.get(),age.getAsLong());List<RepeatPrint.Target> candidates=new ArrayList<>();
        // Только файл, который FM отправил сам: проект — дерево ЭТОГО проекта, быстрая задача — список задач.
        // Перебора деревьев всех проектов и подбора по имени нет.
        if("project".equals(last.source())){
            boolean available=false;for(JSONObject owner:rows(projects()))if(last.projectId().equals(owner.optString("id"))&&!PrintRequest.flag(owner,"is_archived")&&!PrintRequest.flag(owner,"is_deleted")){
                available=true;for(JSONObject file:rows(project(last.projectId()).optJSONArray("nodes")))candidates.add(new RepeatPrint.Target(last,file,last.projectId(),owner.optString("name"),id));break;
            }
            if(!available)throw new IllegalStateException(I18n.t("Проект последней печати удалён или находится в архиве."));
        }else for(JSONObject file:rows(tasks()))candidates.add(new RepeatPrint.Target(last,file,"","",id));
        RepeatPrint.Target target=RepeatPrint.resolve(last,candidates,id);
        if(!last.equals(RepeatPrint.last(history,p,state.get(),age.getAsLong())))throw new IllegalStateException(I18n.t("Состояние принтера изменилось. Обновите карточку."));
        return target;
    }
    public JSONObject repeat(RepeatPrint.Target expected,PrintRequest request,boolean plateCleared,java.util.function.Supplier<JSONObject> state,java.util.function.LongSupplier age,PrintJournal journal) throws Exception {
        if(!plateCleared)throw new IllegalStateException(I18n.t("Подтвердите, что деталь снята и стол свободен."));
        if(!expected.matches(request))throw new IllegalArgumentException(I18n.t("Файл или принтер повторной печати изменён."));
        RepeatPrint.Target current=repeatTarget(expected.printerId,state,age);
        if(!expected.same(current))throw new IllegalStateException(I18n.t("Последняя печать или её файл изменились в FM. Откройте повтор заново."));
        JSONObject p=controlledPrinter(expected.printerId);
        if(!RepeatPrint.eligible(p,state.get(),age.getAsLong())||RepeatPrint.reserved(sends(),expected.printerId))throw new IllegalStateException(I18n.t("Состояние принтера изменилось. Обновите карточку."));
        return post(request,journal);
    }
    /** Новый запуск файла. Отметка «запуск не проверен» ставится ДО запроса — по этому принтеру этого FM. */
    public JSONObject launch(PrintRequest request,PrintJournal journal) throws Exception {
        refreshCapabilities();
        if(!capabilities.operate)throw new SecurityException(I18n.t("У пользователя нет права на печать в FM."));
        return post(request,journal);
    }
    private JSONObject post(PrintRequest request,PrintJournal journal) throws Exception {
        journal.begin(api.origin,request,System.currentTimeMillis());
        JSONObject result;
        try{result=api.call("POST",request.path(),request.body());}
        catch(FmApi.Rejected|FmApi.Unauthorized ex){journal.clear(api.origin,request.printerId);throw ex;}
        catch(Exception ex){throw new PrintJournal.Unknown(ex);}   // отметка остаётся, повтора нет
        if(PrintRequest.accepted(result))journal.accepted(api.origin,request.printerId,result.getString("job_id"),System.currentTimeMillis());
        else if(Arrays.asList("error","incompatible","low_filament","shortage").contains(result.optString("status")))journal.clear(api.origin,request.printerId);
        return result;
    }
    /** Шаги подготовки Klipper (только чтение: FM опрашивает Moonraker и ничего не печатает). */
    public JSONObject klipperPrestart(String id) throws Exception{return api.call("GET","/api/printer/"+segment(id)+"/klipper-prestart",null);}
    /** Запомнить выбор шагов на сервере, как веб-интерфейс. Отказ не мешает печати и не показывается. */
    public void saveKlipperPrefs(String id,JSONObject body){if(body==null)return;try{api.call("POST","/api/printer/"+segment(id)+"/klipper-prestart",body);}catch(Exception ignored){}}
    public PreheatPresets presets() throws Exception{return PreheatPresets.read(api.call("GET","/api/farm-settings",null));}
    public PreheatPresets savePresets(PreheatPresets expected,PreheatPresets edited) throws Exception {
        try{
            requireOperate();if(!presets().same(expected))throw new IllegalStateException(I18n.t("Пресеты изменились в FM. Обновите их перед сохранением."));
            JSONObject response=api.call("POST","/api/farm-settings",new JSONObject().put("preheat_presets",edited.json()));
            return PreheatPresets.read(new JSONObject().put("ok",response.getBoolean("ok")).put("settings",new JSONObject().put("preheat_presets",response.getJSONArray("preheat_presets"))));
        }catch(FmApi.Unauthorized ex){throw ex;}catch(Exception ex){throw new PrinterCommand.Failure(I18n.t("Сохранение пресетов не подтверждено. Обновите данные FM перед повторным сохранением. ")+reason(ex),ex);}
    }
    private void requireOperate() throws Exception {refreshCapabilities();if(!capabilities.operate)throw new SecurityException(I18n.t("Нет права на управление принтером."));}
    private JSONObject controlledPrinter(String id) throws Exception {
        requireOperate();for(JSONObject p:rows(printers()))if(id.equals(p.optString("id")))return p;
        throw new IllegalArgumentException(I18n.t("Принтер не найден."));
    }
    public void control(String id,String action,java.util.function.Supplier<JSONObject> state,java.util.function.LongSupplier age) throws Exception {
        PrinterCommand command=PrinterCommand.control(action);
        try{JSONObject p=controlledPrinter(id);if(!PrinterCommand.allowed(p,state.get(),age.getAsLong(),action))throw new IllegalStateException(I18n.t("Состояние принтера изменилось или устарело. Обновите карточку."));sendCommand(id,command);}
        catch(FmApi.Unauthorized ex){throw ex;}catch(Exception ex){
            String delivery=PrinterCommand.deliveryText(ex);
            if(delivery!=null)throw new PrinterCommand.Failure(delivery,ex,true);
            throw new PrinterCommand.Failure(I18n.t("Результат команды нужно проверить по состоянию принтера. Автоматического повтора нет. ")+reason(ex),ex);
        }
    }
    public void preheat(String id,PreheatPresets.Preset preset,boolean cool,java.util.function.Supplier<JSONObject> state,java.util.function.LongSupplier age) throws Exception {heat(id,preset,cool,0,false,state,age);}
    /** После согласия «Печать сорвётся — выключить нагрев?»: тот же запрос с "force": true, с отклонённой команды. */
    public void preheatForced(PrinterCommand.NeedsForce refused,java.util.function.Supplier<JSONObject> state,java.util.function.LongSupplier age) throws Exception {heat(refused.printerId,refused.preset,refused.cool,refused.next,true,state,age);}
    private void heat(String id,PreheatPresets.Preset preset,boolean cool,int from,boolean force,java.util.function.Supplier<JSONObject> state,java.util.function.LongSupplier age) throws Exception {
        List<String> accepted=new ArrayList<>();int index=from,total=0;
        try{
            JSONObject p=controlledPrinter(id);if(!PrinterCommand.allowed(p,state.get(),age.getAsLong(),"heat"))throw new IllegalStateException(I18n.t("Состояние принтера изменилось или устарело. Обновите карточку."));
            if(cool&&(preset.nozzle!=0||preset.bed!=0||preset.chamber==null||preset.chamber!=0))throw new IllegalArgumentException(I18n.t("Команда остывания должна выключать нагрев."));
            if(!cool&&!preset.same(presets().find(preset.name)))throw new IllegalStateException(I18n.t("Пресет изменился в FM. Обновите его перед прогревом."));
            List<PrinterCommand> commands=PrinterCommand.preheat(p,state.get(),preset);total=commands.size();
            if(from<0||from>=commands.size())throw new IllegalStateException(I18n.t("Состояние принтера изменилось или устарело. Обновите карточку."));
            for(;index<commands.size();index++){PrinterCommand command=commands.get(index);
                requireOperate();if(!PrinterCommand.allowed(p,state.get(),age.getAsLong(),"heat"))throw new IllegalStateException(I18n.t("Состояние принтера изменилось или устарело. Обновите карточку."));
                sendCommand(id,command,force&&HeaterPolicy.turnsOff(command));accepted.add(command.caption());
            }
        }catch(FmApi.Unauthorized ex){throw ex;}catch(Exception ex){
            if(!force&&HeaterPolicy.needsForce(ex))throw new PrinterCommand.NeedsForce(id,preset,cool,index,accepted,ex);
            String sent=accepted.isEmpty()?"":I18n.t("FM принял команды: ")+String.join(", ",accepted)+". ";
            String delivery=PrinterCommand.deliveryText(ex);
            if(delivery!=null)throw new PrinterCommand.Failure(sent+delivery+(index<total-1?" "+I18n.t("Остальные команды не отправлены."):""),ex,true);
            throw new PrinterCommand.Failure(sent+I18n.t("Изменение температур не подтверждено полностью. Проверьте цели в карточке. Оставшиеся команды не отправлены; автоматического повтора нет. ")+reason(ex),ex);
        }
    }
    private void sendCommand(String id,PrinterCommand command) throws Exception {sendCommand(id,command,false);}
    private void sendCommand(String id,PrinterCommand command,boolean force) throws Exception {
        if(id.isEmpty()||id.equals(".")||id.equals(".."))throw new IllegalArgumentException(I18n.t("Принтер не найден."));
        JSONObject response=api.call("POST","/api/printer/"+segment(id)+"/cmd",command.body(force));
        if(!"ok".equals(response.optString("status")))throw new FmApi.Rejected(response.optString("reason",response.optString("error","command_not_confirmed")));
    }
    private String reason(Exception ex){String value=ex.getMessage();if(value==null)return "";return value.length()>250?value.substring(0,250):value;}
    public JSONObject filament() throws Exception {
        if(capabilities==null||!capabilities.inventory)return new JSONObject();
        return api.call("GET","/api/printer-filament",null).optJSONObject("printers");
    }
    public JSONObject badges() throws Exception{
        JSONObject raw=api.call("GET","/api/printer-badges",null).optJSONObject("badges"),out=new JSONObject();
        if(raw==null||capabilities==null)return out;
        Iterator<String> keys=raw.keys();while(keys.hasNext()){String id=keys.next();JSONArray available=new JSONArray();for(JSONObject badge:rows(raw.optJSONArray(id)))if(capabilities.moduleAvailable(badge.optString("module_id")))available.put(badge);if(available.length()>0)out.put(id,available);}
        return out;
    }
    public static String segment(String value){try{return URLEncoder.encode(value,"UTF-8").replace("+","%20");}catch(java.io.UnsupportedEncodingException ex){throw new IllegalStateException(ex);}}
    public static List<JSONObject> rows(JSONArray array){
        List<JSONObject> out=new ArrayList<>();if(array!=null)for(int i=0;i<array.length();i++)if(array.optJSONObject(i)!=null)out.add(array.optJSONObject(i));return out;
    }
}
