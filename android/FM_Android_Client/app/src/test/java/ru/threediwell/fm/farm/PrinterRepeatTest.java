// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import org.junit.*;
import static org.junit.Assert.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import ru.threediwell.fm.inventory.Labels;
import ru.threediwell.fm.scan.ScanPolicy;

public class PrinterRepeatTest {
    private JSONObject p(String type)throws Exception{return new JSONObject().put("id","p1").put("name","Printer 1").put("type",type);}
    private JSONObject s(String status,String raw)throws Exception{return new JSONObject().put("status",status).put("status_raw",raw).put("seen_ago",0).put("file_name","Holder.gcode.3mf");}
    private JSONObject file(String id,String name)throws Exception{return new JSONObject().put("file_id",id).put("filename",name).put("is_printable",true).put("content_hash","h1").put("compatible_pids",new JSONArray().put("p1"));}
    private JSONObject run(String id,String outcome)throws Exception{return new JSONObject().put("run_id",id).put("printer_id","p1").put("source","project").put("project_id","pr1").put("file_id","f1").put("filename","Holder.gcode.3mf").put("file_hash","h1").put("outcome_raw",outcome).put("started_at","2026-10-01 10:00:00").put("created_at","2026-10-01 10:00:00").put("source_payload",new JSONObject().put("server_sent",true));}
    private JSONObject history(JSONObject... runs)throws Exception{JSONArray a=new JSONArray();for(JSONObject r:runs)a.put(r);return new JSONObject().put("runs",a);}
    private RepeatPrint.Last last()throws Exception{return RepeatPrint.last(history(run("r1","finished")),p("bambu"),s("FINISH","FINISH"),0);}
    private RepeatPrint.Target target(RepeatPrint.Last last,String owner,String id,String name)throws Exception{return new RepeatPrint.Target(last,file(id,name),owner,"Project 1","p1");}
    private ScanPolicy scanner()throws Exception{return new ScanPolicy(ScanPolicy.PRINTER,"farm",PrinterQr.catalog(new JSONArray().put(p("bambu"))).toString());}
    @Test public void everyStickerOnPrinterFindsTheSameCard()throws Exception {for(int slot:new int[]{-1,0,1,63,999})assertEquals("p1",PrinterQr.resolve(Labels.slot("farm","p1",slot),"farm",new JSONArray().put(p("bambu"))).getString("id"));}
    @Test public void printerScanDoesNotRequireStockPositionAvailability()throws Exception {ScanPolicy policy=scanner();assertEquals("Printer 1",policy.caption(Labels.slot("farm","p1",999)));assertFalse(policy.needsConfirmation(Labels.slot("farm","p1",0)));assertTrue(policy.qrOnly());}
    @Test public void offlinePrinterCanStillBeFoundForViewing()throws Exception {assertEquals("Printer 1",scanner().caption(Labels.slot("farm","p1",-1)));}
    @Test public void wrongFarmNeverMatchesAnIdenticalPrinterId()throws Exception {assertThrows(IllegalArgumentException.class,()->scanner().caption(Labels.slot("other","p1",0)));}
    @Test public void spoolBarcodeUrlAndUnknownPrinterAreRejected()throws Exception {for(String code:new String[]{Labels.spool("farm","p1"),"0012345678","http://192.168.1.2/print",Labels.slot("farm","deleted",0)})assertThrows(IllegalArgumentException.class,()->scanner().caption(code));}
    @Test public void duplicatePrinterIdsDoNotChooseFirst()throws Exception {assertThrows(IllegalArgumentException.class,()->PrinterQr.resolve(Labels.slot("farm","p1",0),"farm",new JSONArray().put(p("bambu")).put(p("klipper"))));}
    @Test public void qrProtocolMustHaveValidatedFarmIdentity()throws Exception {assertThrows(IllegalArgumentException.class,()->PrinterQr.server(new JSONObject()));assertEquals("farm",PrinterQr.server(new JSONObject().put("mobile",new JSONObject().put("protocol",1).put("server_id","farm"))));}
    @Test public void successfulFirmwareStatesRequireBothRawAndNormalizedFinish()throws Exception {for(String[] pair:new String[][]{{"bambu","FINISH"},{"klipper","complete"},{"flashforge","completed"},{"flashforge","complete"},{"demo","finish"}}){assertTrue(RepeatPrint.finished(p(pair[0]),s("FINISH",pair[1]),0));assertFalse(RepeatPrint.finished(p(pair[0]),s("IDLE",pair[1]),0));}}
    @Test public void unknownBusyCancelledAndPausedStatesCannotRepeat()throws Exception {for(String raw:new String[]{"RUNNING","PREPARE","PAUSE","SLICING","FAILED","unknown",""})assertFalse(RepeatPrint.eligible(p("bambu"),s("FINISH",raw),0));assertFalse(RepeatPrint.eligible(p("klipper"),s("IDLE","cancelled"),0));}
    @Test public void staleFinishedStateCannotRepeat()throws Exception {assertFalse(RepeatPrint.eligible(p("bambu"),s("FINISH","FINISH"),6500));assertFalse(RepeatPrint.eligible(p("bambu"),s("FINISH","FINISH").put("seen_ago",60),0));}
    @Test public void differentTransportCannotBorrowFinishedStatus()throws Exception {assertFalse(RepeatPrint.finished(p("klipper"),s("FINISH","FINISH"),0));assertFalse(RepeatPrint.finished(p("unknown"),s("FINISH","FINISH"),0));}
    @Test public void finishTelemetryAloneNeverPicksAFileByName()throws Exception {assertThrows(IllegalStateException.class,()->RepeatPrint.last(null,p("bambu"),s("FINISH","FINISH"),0));assertThrows(IllegalStateException.class,()->RepeatPrint.last(history(),p("bambu"),s("FINISH","FINISH"),0));}
    @Test public void idleFilenameAloneDoesNotProveLastSuccessfulPrint()throws Exception {assertThrows(IllegalStateException.class,()->RepeatPrint.last(null,p("bambu"),s("IDLE","IDLE"),0));}
    @Test public void historyAllowsIdlePrinterWithExactProjectFile()throws Exception {RepeatPrint.Last last=RepeatPrint.last(history(run("r1","finished")),p("bambu"),s("IDLE","IDLE"),0);assertEquals("r1",last.key());assertEquals("f1",last.fileId());}
    @Test public void doesNotSkipLatestFailedRunToAnOlderSuccessfulOne()throws Exception {assertThrows(IllegalStateException.class,()->RepeatPrint.last(history(run("r2","failed"),run("r1","finished")),p("bambu"),s("FINISH","FINISH"),0));}
    @Test public void runningUnknownAndCancelledHistoryNeverRepeat()throws Exception {for(String status:new String[]{"running","unknown","cancelled","interrupted"})assertThrows(IllegalStateException.class,()->RepeatPrint.last(history(run("r1",status)),p("bambu"),s("FINISH","FINISH"),0));}
    @Test public void malformedOrForeignHistoryFailsClosed()throws Exception {assertThrows(IllegalArgumentException.class,()->RepeatPrint.last(new JSONObject(),p("bambu"),s("FINISH","FINISH"),0));assertThrows(IllegalStateException.class,()->RepeatPrint.last(history(run("r1","finished").put("printer_id","p2")),p("bambu"),s("FINISH","FINISH"),0));}
    @Test public void mismatchedTelemetryDoesNotUseOldHistory()throws Exception {assertThrows(IllegalStateException.class,()->RepeatPrint.last(history(run("r1","finished")),p("bambu"),s("FINISH","FINISH").put("file_name","Other.gcode.3mf"),0));}
    @Test public void equalHistoryTimesCannotGuessLatestRun()throws Exception {assertThrows(IllegalStateException.class,()->RepeatPrint.last(history(run("r2","finished"),run("r1","finished")),p("bambu"),s("FINISH","FINISH"),0));}
    @Test public void exactProjectIdentityWinsOverDuplicateNames()throws Exception {RepeatPrint.Last last=last();RepeatPrint.Target wanted=target(last,"pr1","f1","Holder.gcode.3mf");assertSame(wanted,RepeatPrint.resolve(last,Arrays.asList(wanted,target(last,"pr2","f2","Holder.gcode.3mf")),"p1"));}
    @Test public void printsNotSentByFmAreNeverRepeated()throws Exception {
        for(String source:new String[]{"screen","unknown","telemetry","plan",""})assertThrows(IllegalStateException.class,()->RepeatPrint.last(history(run("r1","finished").put("source",source)),p("bambu"),s("FINISH","FINISH"),0));
        for(Object sent:new Object[]{false,"true",1,JSONObject.NULL})assertThrows(IllegalStateException.class,()->RepeatPrint.last(history(run("r1","finished").put("source_payload",new JSONObject().put("server_sent",sent))),p("bambu"),s("FINISH","FINISH"),0));
        assertThrows(IllegalStateException.class,()->RepeatPrint.last(history(run("r1","finished").put("source","quick").put("source_payload",new JSONObject())),p("bambu"),s("FINISH","FINISH"),0));
        assertThrows(IllegalStateException.class,()->RepeatPrint.last(history(run("r1","finished").put("source","quick").put("source_payload",JSONObject.NULL)),p("bambu"),s("FINISH","FINISH"),0));
        assertEquals("project",RepeatPrint.last(history(run("r1","finished")),p("bambu"),s("FINISH","FINISH"),0).source());
    }
    @Test public void quickRepeatUsesOnlyTheExactTaskNeverAProjectOrSimilarName()throws Exception {
        RepeatPrint.Last last=RepeatPrint.last(history(run("r1","finished").put("source","quick").put("file_hash","")),p("bambu"),s("FINISH","FINISH"),0);
        assertThrows(IllegalStateException.class,()->RepeatPrint.resolve(last,List.of(target(last,"pr1","f1","Holder.gcode.3mf")),"p1"));
        assertThrows(IllegalStateException.class,()->RepeatPrint.resolve(last,List.of(target(last,"","","Holder")),"p1"));
        assertThrows(IllegalStateException.class,()->RepeatPrint.resolve(last,List.of(target(last,"","","holder.gcode.3mf")),"p1"));
        RepeatPrint.Target exact=target(last,"","","Holder.gcode.3mf");assertSame(exact,RepeatPrint.resolve(last,List.of(exact),"p1"));
    }
    @Test public void quickHistoryKeepsTaskAccountingEvenWithProjectCopy()throws Exception {RepeatPrint.Last last=RepeatPrint.last(history(run("r1","finished").put("source","quick").put("file_hash","")),p("bambu"),s("FINISH","FINISH"),0);assertEquals("",RepeatPrint.resolve(last,Arrays.asList(target(last,"","","Holder.gcode.3mf"),target(last,"pr1","f1","Holder.gcode.3mf")),"p1").projectId);}
    @Test public void changedProjectHashCannotRepeatOldRevision()throws Exception {RepeatPrint.Last last=last();RepeatPrint.Target t=target(last,"pr1","f1","Holder.gcode.3mf");t.file.put("content_hash","h2");assertThrows(IllegalStateException.class,()->RepeatPrint.resolve(last,List.of(t),"p1"));}
    @Test public void missingIncompatibleAndModelFilesAreNotPrintable()throws Exception {for(String field:new String[]{"missing","is_printable","compatible_pids"}){RepeatPrint.Last last=last();RepeatPrint.Target t=target(last,"pr1","f1","Holder.gcode.3mf");t.file.put(field,field.equals("missing")?true:field.equals("is_printable")?false:new JSONArray());assertThrows(IllegalStateException.class,()->RepeatPrint.resolve(last,List.of(t),"p1"));}}
    @Test public void absentFileDoesNotFallBackToANameInAnotherProject()throws Exception {RepeatPrint.Last last=last();assertThrows(IllegalStateException.class,()->RepeatPrint.resolve(last,List.of(target(last,"pr2","f2","Holder.gcode.3mf")),"p1"));}
    @Test public void extensionlessNameCanMatchButOtherPrintableFormatCannot() {assertTrue(RepeatPrint.nameMatches("Holder.gcode.3mf","Holder"));assertTrue(RepeatPrint.nameMatches("Holder.gcode.3mf","/cache/Holder.gcode.3mf"));assertFalse(RepeatPrint.nameMatches("Holder.gcode.3mf","Holder.gcode"));assertFalse(RepeatPrint.nameMatches("Holder_v2.gcode","Holder v2"));}
    @Test public void newRunOrChangedFileInvalidatesPreparedRepeat()throws Exception {RepeatPrint.Last last=last();RepeatPrint.Target a=target(last,"pr1","f1","Holder.gcode.3mf"),b=target(last,"pr1","f1","Holder.gcode.3mf");assertTrue(a.same(b));assertFalse(a.same(target(new RepeatPrint.Last("r2","pr1","f1",last.filename(),"h1","project"),"pr1","f1",last.filename())));b.file.put("mtime",20);assertFalse(a.same(new RepeatPrint.Target(last,b.file,"pr1","Project 1","p1")));}
    @Test public void repeatCannotSwitchToAnotherPrinterOrOwner()throws Exception {RepeatPrint.Target t=target(last(),"pr1","f1","Holder.gcode.3mf");assertTrue(t.matches(new PrintRequest("pr1","f1","Holder.gcode.3mf","p1",null,null)));assertFalse(t.matches(new PrintRequest("pr1","f1","Holder.gcode.3mf","p2",null,null)));assertFalse(t.matches(new PrintRequest("","","Holder.gcode.3mf","p1",null,null)));}
    @Test public void reservedOrUnknownSendStateBlocksAnotherStart()throws Exception {assertTrue(RepeatPrint.reserved(new JSONObject().put("reserved_printer_ids",new JSONArray().put("p1")),"p1"));assertThrows(IllegalStateException.class,()->RepeatPrint.reserved(new JSONObject(),"p1"));}
    @Test public void exportActualRepeatRequestsForCoreAccountingCheck()throws Exception {
        String dir=System.getenv("FM_REPEAT_TEST_OUTPUT");if(dir==null||dir.isEmpty())return;
        JSONObject opts=new JSONObject().put("bed_leveling",true).put("force",true).put("skip_filament",true);
        PrintRequest project=new PrintRequest("pr1","f1","Holder.gcode.3mf","p1",-1,opts),task=new PrintRequest("","","Holder.gcode.3mf","p1",0,opts);
        JSONArray fixtures=new JSONArray();for(PrintRequest r:new PrintRequest[]{project,task})fixtures.put(new JSONObject().put("path",r.path()).put("body",r.body()).put("filename",r.filename));
        Path output=Paths.get(dir);Files.createDirectories(output);Files.write(output.resolve("repeat-print-fixtures.json"),fixtures.toString(2).getBytes(StandardCharsets.UTF_8));
    }
}
