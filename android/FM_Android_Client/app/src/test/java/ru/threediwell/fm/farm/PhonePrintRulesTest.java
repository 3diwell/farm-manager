// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import org.junit.*;
import java.util.*;
import ru.threediwell.fm.core.FmApi;
import ru.threediwell.fm.i18n.I18n;
import static org.junit.Assert.*;

/** Решения телефона при запуске печати и командах принтеру (ANDROID_CLIENT_NOTES.md, пункты 1-3, 6, 7, 10, 15; R-145). */
public class PhonePrintRulesTest {
    @After public void reset(){I18n.setLanguage("ru");}
    private static JSONObject printer(String id,String type)throws Exception{return new JSONObject().put("id",id).put("name","Printer "+id).put("type",type);}
    private static JSONObject state(String status,String raw)throws Exception{return new JSONObject().put("status",status).put("status_raw",raw).put("seen_ago",0);}
    private static JSONObject tray(int index,String type)throws Exception{return new JSONObject().put("index",index).put("type",type);}
    private static JSONObject file(String... printers)throws Exception{JSONArray ids=new JSONArray();for(String p:printers)ids.put(p);return new JSONObject().put("file_id","f1").put("filename","Holder.gcode.3mf").put("is_printable",true).put("compatible_pids",ids);}
    private static JSONObject sends(JSONArray jobs,String... reserved)throws Exception{JSONArray r=new JSONArray();for(String id:reserved)r.put(id);return new JSONObject().put("jobs",jobs).put("reserved_printer_ids",r);}
    private static JSONObject job(String id,String printer,String state)throws Exception{return new JSONObject().put("job_id",id).put("printer_id",printer).put("file_name","Holder.gcode.3mf").put("state",state);}

    // ── 1. Bambu: источник материала ─────────────────────────────────────────────
    @Test public void bambuWithAmsOffersAutoFirstAndAutoOmitsAmsSlot()throws Exception {
        JSONObject s=state("IDLE","IDLE").put("ams_trays",new JSONArray().put(tray(0,"PLA")).put(tray(5,"PETG")));
        List<PrintChoice.Source> sources=PrintChoice.bambuSources(s);
        assertEquals("Авто (как в файле)",sources.get(0).label());assertNull(sources.get(0).slot());
        assertEquals("Внешняя катушка",sources.get(1).label());assertEquals(Integer.valueOf(-1),sources.get(1).slot());
        assertEquals("AMS 1 · 1 · PLA",sources.get(2).label());assertEquals("AMS 2 · 2 · PETG",sources.get(3).label());assertEquals(Integer.valueOf(5),sources.get(3).slot());
        JSONObject body=new PrintRequest("pr1","f1","Holder.gcode.3mf","p1",sources.get(0).slot(),PrintChoice.options("bambu",true,false,false,null,null)).body();
        assertFalse(body.has("ams_slot"));assertTrue(body.getJSONObject("print_opts").getBoolean("bed_leveling"));
        assertEquals(-1,new PrintRequest("pr1","f1","Holder.gcode.3mf","p1",sources.get(1).slot(),null).body().getInt("ams_slot"));
    }
    @Test public void bambuWithoutReportedTraysPrintsFromExternalSpoolOnly()throws Exception {
        for(JSONObject s:new JSONObject[]{state("IDLE","IDLE"),state("IDLE","IDLE").put("ams_trays",new JSONArray()),null}){
            List<PrintChoice.Source> sources=PrintChoice.bambuSources(s);assertEquals(1,sources.size());assertEquals(Integer.valueOf(-1),sources.get(0).slot());
        }
    }
    @Test public void dualNozzleExternalSpoolSideComesFromTheFile()throws Exception {
        assertEquals("Внешняя катушка (сторона — по соплу в файле)",PrintChoice.bambuSources(state("IDLE","IDLE").put("nozzle_count",2)).get(0).label());
    }
    @Test public void amsHtAndMalformedTraysAreLabelledLikeFm()throws Exception {
        JSONObject s=state("IDLE","IDLE").put("ams_trays",new JSONArray().put(new JSONObject().put("index",512).put("unit",128).put("tray",0).put("type","Empty")).put(new JSONObject().put("type","PLA")).put(tray(-1,"PLA")));
        List<PrintChoice.Source> sources=PrintChoice.bambuSources(s);assertEquals(3,sources.size());assertEquals("AMS HT · 1",sources.get(2).label());   // как в FM: первый AMS HT — «AMS HT», без номера
    }

    // ── 2. Принтеры для нового файла: свободен ИЛИ завершил печать ───────────────
    @Test public void finishedBambuIsOfferedButNeedsEmptyPlateConfirmation()throws Exception {
        JSONObject p=printer("p1","bambu"),finished=state("FINISH","FINISH"),idle=state("IDLE","IDLE");
        assertTrue(PrintChoice.offered(file("p1"),p,finished,0,sends(new JSONArray())));
        assertTrue(PrintChoice.needsPlateConfirmation(p,finished,0));assertFalse(PrintChoice.needsPlateConfirmation(p,idle,0));
        assertFalse(PrintChoice.startAllowed(p,finished,0,false));assertTrue(PrintChoice.startAllowed(p,finished,0,true));assertTrue(PrintChoice.startAllowed(p,idle,0,false));
    }
    @Test public void finishedOtherTransportsAlsoUseConfirmedPlate()throws Exception {
        for(String[] pair:new String[][]{{"klipper","complete"},{"flashforge","completed"}}){JSONObject p=printer("p1",pair[0]);JSONObject s=state("FINISH",pair[1]);assertTrue(PrintChoice.offered(file("p1"),p,s,0,sends(new JSONArray())));assertTrue(PrintChoice.needsPlateConfirmation(p,s,0));}
    }
    @Test public void busyStaleReservedOrIncompatiblePrintersAreNotOffered()throws Exception {
        JSONObject p=printer("p1","bambu");
        for(String[] busy:new String[][]{{"RUNNING","RUNNING"},{"PREPARE","PREPARE"},{"PAUSED","PAUSE"},{"FAILED","FAILED"},{"FINISH","RUNNING"}})assertFalse(PrintChoice.offered(file("p1"),p,state(busy[0],busy[1]),0,sends(new JSONArray())));
        assertFalse(PrintChoice.offered(file("p1"),p,state("IDLE","IDLE"),6500,sends(new JSONArray())));
        assertFalse(PrintChoice.offered(file("p1"),p,state("IDLE","IDLE"),0,sends(new JSONArray(),"p1")));
        assertFalse(PrintChoice.offered(file("p2"),p,state("IDLE","IDLE"),0,sends(new JSONArray())));
        assertFalse(PrintChoice.offered(file("p1").put("missing",true),p,state("IDLE","IDLE"),0,sends(new JSONArray())));
        assertFalse(PrintChoice.startAllowed(p,state("RUNNING","RUNNING"),0,true));
    }

    // ── 3. Отметка «запуск не проверен»: по принтеру и адресу FM, правила снятия ─
    private static final class Memory implements PrintJournal.Store {String value="";public String read(){return value;}public boolean write(String v){value=v;return true;}public boolean clear(){value="";return true;}}
    private static final String FM="http://fm.test:8000",OTHER="http://other.test:8000";
    private static PrintRequest request(String printer){return new PrintRequest("pr1","f1","Holder.gcode.3mf",printer,null,null);}
    private static PrintJournal.Mark accepted(String job,long at){return new PrintJournal.Mark(FM,"p1","Holder.gcode.3mf",job,false,"",at,at);}
    private static PrintJournal.Mark unknown(long at){return new PrintJournal.Mark(FM,"p1","Holder.gcode.3mf","",false,"",at,at);}
    @Test public void markIsPerPrinterAndPerFmAddress()throws Exception {
        PrintJournal j=new PrintJournal(new Memory());j.begin(FM,request("p1"),1);
        assertTrue(j.blocks(FM,"p1"));assertFalse(j.blocks(FM,"p2"));assertFalse(j.blocks(OTHER,"p1"));
        j.begin(FM,request("p2"),2);j.begin(OTHER,request("p1"),3);assertEquals(2,j.marks(FM).size());assertEquals(1,j.marks(OTHER).size());
        assertThrows(IllegalStateException.class,()->j.begin(FM,request("p1"),4));
        j.clear(FM,"p1");assertFalse(j.blocks(FM,"p1"));assertTrue(j.blocks(FM,"p2"));assertTrue(j.blocks(OTHER,"p1"));
    }
    @Test public void ownCompletedOrFailedSendClearsTheMark()throws Exception {
        for(String done:new String[]{"completed","failed"})assertEquals(PrintJournal.Decision.CLEAR,PrintJournal.decide(accepted("send_1",10),sends(new JSONArray().put(job("send_1","p1",done))),11,null,0));
        for(String active:new String[]{"queued","preparing","uploading","waiting_confirmation"})assertEquals(PrintJournal.Decision.KEEP,PrintJournal.decide(accepted("send_1",10),sends(new JSONArray().put(job("send_1","p1",active))),11,state("RUNNING","RUNNING").put("file_name","Holder.gcode.3mf"),0));
    }
    @Test public void goneSendWithPrinterPrintingThatFileClearsTheMark()throws Exception {
        JSONObject printing=state("RUNNING","RUNNING").put("file_name","Holder.gcode.3mf");
        assertEquals(PrintJournal.Decision.CLEAR,PrintJournal.decide(accepted("send_1",10),sends(new JSONArray()),11,printing,0));
        assertEquals(PrintJournal.Decision.CLEAR,PrintJournal.decide(accepted("send_1",10),sends(new JSONArray().put(job("send_other","p2","uploading"))),11,printing,0));
        // другой файл или устаревшие данные — это не доказательство
        assertEquals(PrintJournal.Decision.SOFT_GONE,PrintJournal.decide(accepted("send_1",10),sends(new JSONArray().put(job("send_other","p2","uploading"))),11,state("RUNNING","RUNNING").put("file_name","Other.gcode.3mf"),0));
        assertEquals(PrintJournal.Decision.SOFT_RESTART,PrintJournal.decide(accepted("send_1",10),sends(new JSONArray()),11,printing,6500));
    }
    @Test public void fmRestartOrDismissedSendBecomesSoftReminderNotEternalBlock()throws Exception {
        assertEquals(PrintJournal.Decision.SOFT_RESTART,PrintJournal.decide(accepted("send_1",10),sends(new JSONArray()),11,state("IDLE","IDLE"),0));
        assertEquals(PrintJournal.Decision.SOFT_GONE,PrintJournal.decide(accepted("send_1",10),sends(new JSONArray().put(job("send_2","p2","completed"))),11,state("IDLE","IDLE"),0));
        PrintJournal j=new PrintJournal(new Memory());j.begin(FM,request("p1"),1);j.accepted(FM,"p1","send_1",2);
        assertTrue(j.resolve(FM,sends(new JSONArray()),3,id->null,0));
        PrintJournal.Mark mark=j.find(FM,"p1");assertTrue(mark.soft());assertEquals(PrintJournal.SOFT_RESTART,mark.softReason());
        assertFalse(j.blocks(FM,"p1"));assertTrue(j.pending(FM));assertTrue(PrintJournal.describe(mark).contains("перезапускался"));
        j.begin(FM,request("p1"),4);assertTrue(j.blocks(FM,"p1"));assertEquals(1,j.marks(FM).size());   // напоминание заменяется новым запуском
    }
    @Test public void snapshotTakenBeforeTheStartProvesNothing()throws Exception {
        assertEquals(PrintJournal.Decision.KEEP,PrintJournal.decide(accepted("send_1",10),sends(new JSONArray()),10,null,0));
        assertEquals(PrintJournal.Decision.KEEP,PrintJournal.decide(accepted("send_1",10),sends(new JSONArray()),9,null,0));
        assertEquals(PrintJournal.Decision.KEEP,PrintJournal.decide(accepted("send_1",10),new JSONObject(),11,null,0));
        assertEquals(PrintJournal.Decision.KEEP,PrintJournal.decide(accepted("send_1",10),null,11,null,0));
    }
    @Test public void lostResponseWaitsForGraceAndActiveSendsOfThatPrinter()throws Exception {
        long t=1000,late=t+PrintJournal.UNKNOWN_GRACE_MS;
        assertEquals(PrintJournal.Decision.KEEP,PrintJournal.decide(unknown(t),sends(new JSONArray()),t+1,null,0));
        assertEquals(PrintJournal.Decision.SOFT_RESTART,PrintJournal.decide(unknown(t),sends(new JSONArray()),late,null,0));
        assertEquals(PrintJournal.Decision.KEEP,PrintJournal.decide(unknown(t),sends(new JSONArray().put(job("send_x","p1","uploading"))),late,null,0));
        assertEquals(PrintJournal.Decision.KEEP,PrintJournal.decide(unknown(t),sends(new JSONArray(),"p1"),late,null,0));
        assertEquals(PrintJournal.Decision.SOFT_GONE,PrintJournal.decide(unknown(t),sends(new JSONArray().put(job("send_x","p1","failed"))),late,null,0));
        assertEquals(PrintJournal.Decision.CLEAR,PrintJournal.decide(unknown(t),sends(new JSONArray()),t+1,state("PREPARE","PREPARE").put("file_name","Holder"),0));
    }
    @Test public void softReminderClearsWhenPrinterPrintsThatFile()throws Exception {
        PrintJournal.Mark soft=new PrintJournal.Mark(FM,"p1","Holder.gcode.3mf","send_1",true,PrintJournal.SOFT_GONE,1,2);
        assertEquals(PrintJournal.Decision.KEEP,PrintJournal.decide(soft,sends(new JSONArray()),3,state("IDLE","IDLE"),0));
        assertEquals(PrintJournal.Decision.CLEAR,PrintJournal.decide(soft,sends(new JSONArray()),3,state("PAUSED","PAUSE").put("file_name","Holder.gcode.3mf"),0));
    }
    @Test public void resolvingOneFmNeverTouchesMarksOfAnotherFm()throws Exception {
        PrintJournal j=new PrintJournal(new Memory());j.begin(FM,request("p1"),1);j.accepted(FM,"p1","send_1",2);j.begin(OTHER,request("p1"),1);j.accepted(OTHER,"p1","send_1",2);
        assertTrue(j.resolve(FM,sends(new JSONArray().put(job("send_1","p1","completed"))),3,id->null,0));
        assertNull(j.find(FM,"p1"));assertTrue(j.blocks(OTHER,"p1"));
        assertFalse(j.resolve(OTHER,sends(new JSONArray().put(job("send_1","p1","uploading"))),3,id->null,0));assertTrue(j.blocks(OTHER,"p1"));
    }
    @Test public void previousSinglePhoneMarkIsMigratedToItsPrinterAndFm()throws Exception {
        Memory m=new Memory();m.value=new JSONObject().put("origin",FM).put("printer_id","p1").put("filename","Holder.gcode.3mf").put("created_at",5).put("state","accepted").put("job_id","send_1").toString();
        PrintJournal j=new PrintJournal(m);assertTrue(j.blocks(FM,"p1"));assertFalse(j.blocks(FM,"p2"));assertEquals("send_1",j.find(FM,"p1").jobId());
        assertTrue(j.resolve(FM,sends(new JSONArray().put(job("send_1","p1","completed"))),6,id->null,0));assertFalse(j.pending(FM));assertEquals("",m.value);
    }
    @Test public void unreadableMarkFailsClosedUntilCheckedByHand()throws Exception {
        Memory m=new Memory();m.value="{broken";PrintJournal j=new PrintJournal(m);
        assertTrue(j.blocks(FM,"p1"));assertTrue(j.blocks(OTHER,"p2"));assertTrue(j.pending(FM));assertFalse(j.marks(OTHER).get(0).soft());
        assertFalse(j.resolve(FM,sends(new JSONArray()),Long.MAX_VALUE,id->null,0));assertTrue(j.blocks(FM,"p1"));
        j.clear("","");assertFalse(j.pending(FM));assertFalse(j.blocks(FM,"p1"));
    }

    // ── 5. Нагрев во время печати ────────────────────────────────────────────────
    @Test public void heaterOffIsNotOfferedWhilePrintingButAllowedOnPauseOrIdle()throws Exception {
        JSONObject p=printer("p1","bambu");
        for(String status:new String[]{"RUNNING","PREPARE","SLICING"}){assertTrue(HeaterPolicy.activePrint(state(status,status)));assertFalse(HeaterPolicy.offOffered(p,state(status,status),0));}
        for(String status:new String[]{"PAUSED","PAUSE","IDLE","FINISH","FAILED"}){assertFalse(HeaterPolicy.activePrint(state(status,status)));assertTrue(HeaterPolicy.offOffered(p,state(status,status),0));}
        assertFalse(HeaterPolicy.offOffered(p,state("IDLE","IDLE"),6500));
    }
    @Test public void confirmationsSayThatThePrintWillFail()throws Exception {
        PreheatPresets.Preset off=new PreheatPresets.Preset("Off",0,0,0),pla=new PreheatPresets.Preset("PLA",220,60,null),bedOff=new PreheatPresets.Preset("Bed off",220,0,null);
        assertEquals("Идёт печать: выключение нагрева сорвёт её.",HeaterPolicy.warning(state("RUNNING","RUNNING"),off,true));
        assertEquals("Идёт печать: выключение нагрева сорвёт её.",HeaterPolicy.warning(state("PREPARE","PREPARE"),bedOff,false));
        assertTrue(HeaterPolicy.warning(state("RUNNING","RUNNING"),pla,false).startsWith("Идёт печать"));
        assertTrue(HeaterPolicy.warning(state("PAUSED","PAUSE"),off,true).startsWith("Печать на паузе"));
        assertEquals("",HeaterPolicy.warning(state("IDLE","IDLE"),off,true));
    }
    @Test public void onlyZeroNozzleOrBedTargetsCountAsTurningHeatOff(){
        for(String a:new String[]{"nozzle","nozzle_l","nozzle_r","bed"}){assertTrue(HeaterPolicy.turnsOff(PrinterCommand.heat(a,0)));assertFalse(HeaterPolicy.turnsOff(PrinterCommand.heat(a,60)));}
        assertFalse(HeaterPolicy.turnsOff(PrinterCommand.heat("chamber",0)));assertFalse(HeaterPolicy.turnsOff(PrinterCommand.control("stop")));
    }
    @Test public void forceIsAddedOnlyToTheRetriedBodyAndOnlyFor409HeaterCode()throws Exception {
        JSONObject plain=PrinterCommand.heat("bed",0).body(),forced=PrinterCommand.heat("bed",0).body(true);
        assertEquals(2,plain.length());assertFalse(plain.has("force"));assertTrue(forced.getBoolean("force"));assertEquals("bed",forced.getString("cmd"));assertEquals("0",forced.getString("val"));
        assertTrue(HeaterPolicy.needsForce(new FmApi.Rejected("heater_off_while_printing")));assertTrue(HeaterPolicy.needsForce(new java.io.IOException("x",new FmApi.Rejected("heater_off_while_printing"))));
        assertFalse(HeaterPolicy.needsForce(new FmApi.Rejected("printer_busy")));assertFalse(HeaterPolicy.needsForce(new FmApi.ServerError(502,"heater_off_while_printing")));assertFalse(HeaterPolicy.needsForce(new java.io.IOException("x")));
    }

    // ── 6. Ошибки команд, в том числе на 5xx ─────────────────────────────────────
    @Test public void deliveryReasonsAreReadableOnServerErrors(){
        assertEquals("Команда не дошла до принтера — проверьте связь.",PrinterCommand.deliveryText(new FmApi.ServerError(502,"command_not_delivered")));
        assertEquals("Принтер не подтвердил команду — проверьте его состояние.",PrinterCommand.deliveryText(new FmApi.ServerError(502,"command_not_confirmed")));
        assertEquals("Команда «Стоп» не дошла до принтера — печать продолжается.",PrinterCommand.deliveryText(new FmApi.ServerError(502,"stop_not_delivered")));
        assertEquals("Принтер не подтвердил команду — проверьте его состояние.",PrinterCommand.deliveryText(new FmApi.Rejected("command_not_confirmed")));
        assertNull(PrinterCommand.deliveryText(new FmApi.ServerError(500,"")));assertNull(PrinterCommand.deliveryText(new FmApi.ServerError(502,"internal")));assertNull(PrinterCommand.deliveryText(new java.io.IOException("timeout")));
        I18n.setLanguage("en");assertEquals("The Stop command did not reach the printer. The print continues.",PrinterCommand.deliveryText(new FmApi.ServerError(502,"stop_not_delivered")));
    }
    @Test public void serverErrorRemainsAnUncertainResultForStoredOperations(){
        FmApi.ServerError error=new FmApi.ServerError(502,"command_not_delivered");Exception asException=error;
        assertFalse(asException instanceof FmApi.Rejected);assertTrue(error.getMessage().startsWith("Ошибка сервера FM"));assertEquals("command_not_delivered",error.code);
    }

    // ── 7. Klipper: шаги подготовки FM и ячейка CFS ──────────────────────────────
    private static JSONObject cap(String id,String state,boolean supported)throws Exception{return new JSONObject().put("id",id).put("state",state).put("supported",supported).put("auto_execute",true).put("safe_each_print",true).put("file_controlled",false).put("label_ru","RU "+id).put("label_en","EN "+id).put("explain_ru","").put("explain_en","");}
    private static JSONObject prestart()throws Exception{
        return new JSONObject().put("status","ok").put("reachable",true).put("capabilities",new JSONArray()
            .put(cap("quad_gantry_level","supported_automatic",true)).put(cap("bed_mesh_calibrate","supported_automatic",true)).put(cap("clean_nozzle","supported_manual",true))
            .put(cap("z_tilt_adjust","file_controlled",true).put("file_controlled",true)).put(cap("screws_tilt","detected",false)).put(cap("G28\nM112","supported_automatic",true)))
            .put("prefs",new JSONObject().put("bed_mesh_calibrate",true).put("quad_gantry_level",false));
    }
    @Test public void onlyAutomaticStepsAreSelectableAndOwnerChoiceIsTheDefault()throws Exception {
        List<KlipperStart.Step> steps=KlipperStart.steps(prestart());
        assertEquals(2,steps.size());assertEquals("quad_gantry_level",steps.get(0).id());assertFalse(steps.get(0).selected());assertEquals("bed_mesh_calibrate",steps.get(1).id());assertTrue(steps.get(1).selected());assertEquals("RU bed_mesh_calibrate",steps.get(1).label());
        I18n.setLanguage("en");assertEquals("EN bed_mesh_calibrate",KlipperStart.steps(prestart()).get(1).label());
    }
    @Test public void chosenStepsAndCfsCellGoIntoPrintOptionsOnly()throws Exception {
        List<KlipperStart.Step> steps=KlipperStart.steps(prestart());
        JSONArray ids=KlipperStart.chosen(steps,Set.of("bed_mesh_calibrate","quad_gantry_level","clean_nozzle","G28"));
        assertEquals(new JSONArray().put("quad_gantry_level").put("bed_mesh_calibrate").toString(),ids.toString());
        JSONObject body=new PrintRequest("pr1","f1","Holder.gcode","k1",null,PrintChoice.options("klipper",true,true,true,3,ids)).body();
        JSONObject opts=body.getJSONObject("print_opts");assertEquals(3,opts.getInt("cfs_slot"));assertEquals(2,opts.getJSONArray("klipper_prestart").length());assertFalse(opts.has("bed_leveling"));assertFalse(body.has("ams_slot"));
        assertNull(KlipperStart.chosen(steps,Set.of()));assertNull(PrintChoice.options("klipper",false,false,false,null,null));
        assertFalse(new PrintRequest("pr1","f1","Holder.gcode","k1",null,PrintChoice.options("klipper",false,false,false,null,null)).body().has("print_opts"));
    }
    @Test public void printRequestDropsRawGcodeAndInvalidCells()throws Exception {
        JSONObject opts=new JSONObject().put("klipper_prestart",new JSONArray().put("G28\nM112").put("BED_MESH_CALIBRATE").put(5).put("bed_mesh_calibrate")).put("cfs_slot",-1).put("force",true);
        JSONObject body=new PrintRequest("pr1","f1","Holder.gcode","k1",null,opts).body();
        assertEquals(new JSONArray().put("bed_mesh_calibrate").toString(),body.getJSONObject("print_opts").getJSONArray("klipper_prestart").toString());assertFalse(body.getJSONObject("print_opts").has("cfs_slot"));assertFalse(body.has("force"));
        assertFalse(new PrintRequest("pr1","f1","Holder.gcode","k1",null,new JSONObject().put("cfs_slot","2")).body().has("print_opts"));
    }
    @Test public void missingOrUnreachableDiscoveryMeansPrintAsInFile()throws Exception {
        assertTrue(KlipperStart.steps(null).isEmpty());assertTrue(KlipperStart.steps(new JSONObject()).isEmpty());assertFalse(KlipperStart.reachable(new JSONObject()));
        assertTrue(KlipperStart.steps(new JSONObject().put("status","error").put("capabilities",prestart().getJSONArray("capabilities"))).isEmpty());
        assertNull(KlipperStart.prefs(null,Set.of()));assertNull(KlipperStart.prefs(new JSONObject().put("capabilities",new JSONArray()),Set.of()));
    }
    @Test public void savedPreferencesCoverProvenStepsLikeWebInterface()throws Exception {
        JSONObject prefs=KlipperStart.prefs(prestart(),Set.of("bed_mesh_calibrate","clean_nozzle")).getJSONObject("prefs");
        assertTrue(prefs.getBoolean("bed_mesh_calibrate"));assertFalse(prefs.getBoolean("quad_gantry_level"));assertFalse(prefs.getBoolean("clean_nozzle"));assertFalse(prefs.getBoolean("z_tilt_adjust"));
        assertFalse(prefs.has("screws_tilt"));assertFalse(prefs.has("G28\nM112"));
    }
    @Test public void cfsCellsWithoutMaterialAreNotOffered()throws Exception {
        JSONObject s=state("IDLE","standby").put("cfs_trays",new JSONArray().put(tray(0,"PLA").put("label","T1A")).put(tray(1,"Empty")).put(tray(2,"")).put(tray(5,"PETG")));
        List<PrintChoice.Source> cells=PrintChoice.cfsSources(s);
        assertEquals(3,cells.size());assertNull(cells.get(0).slot());assertEquals("T1A · PLA",cells.get(1).label());assertEquals(Integer.valueOf(0),cells.get(1).slot());assertEquals("CFS 2 · 2 · PETG",cells.get(2).label());assertEquals(Integer.valueOf(5),cells.get(2).slot());
        assertEquals(1,PrintChoice.cfsSources(state("IDLE","standby")).size());
    }
}
