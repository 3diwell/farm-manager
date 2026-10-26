// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import org.junit.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import ru.threediwell.fm.farm.*;
import static org.junit.Assert.*;

public class CoreTransportTest {
    private ServerSocket server;private Thread worker;private FmApi api;
    private volatile String response="[]";private volatile int status=200,closeCode;private volatile boolean upgrade,invalidHandshake,fragment,ping;
    private final AtomicReference<String> cookie=new AtomicReference<>(),path=new AtomicReference<>(),failure=new AtomicReference<>();
    private final CountDownLatch pong=new CountDownLatch(1);
    private final Map<String,String> responses=new ConcurrentHashMap<>();
    private static final class Call{final String method,path,body;Call(String method,String path,String body){this.method=method;this.path=path;this.body=body;}}
    private static final class Reply{final int status;final String body;Reply(int status,String body){this.status=status;this.body=body;}}
    private final List<Call> calls=Collections.synchronizedList(new ArrayList<>());
    private final Queue<Reply> commandReplies=new ConcurrentLinkedQueue<>();
    private volatile boolean dropCommandResponse;private volatile Runnable afterCommand;
    private volatile boolean dropPrintResponse;private volatile Reply printReply;
    private static String line(InputStream in) throws IOException {ByteArrayOutputStream b=new ByteArrayOutputStream();int c;while((c=in.read())>=0&&c!='\n')if(c!='\r')b.write(c);return b.toString(StandardCharsets.ISO_8859_1.name());}
    @Before public void setup() throws Exception {
        server=new ServerSocket(0,8,InetAddress.getByName("127.0.0.1"));api=new FmApi("http://127.0.0.1:"+server.getLocalPort());
        worker=new Thread(()->{while(!server.isClosed())try(Socket s=server.accept()){
            s.setSoTimeout(3000);InputStream in=s.getInputStream();OutputStream out=s.getOutputStream();String request=line(in);path.set(request.split(" ")[1]);String key="";int length=0;cookie.set(null);
            for(String h;!(h=line(in)).isEmpty();){if(h.toLowerCase().startsWith("cookie:"))cookie.set(h.substring(7).trim());if(h.toLowerCase().startsWith("sec-websocket-key:"))key=h.substring(18).trim();if(h.toLowerCase().startsWith("content-length:"))length=Integer.parseInt(h.substring(15).trim());}
            byte[] body=new byte[length];new DataInputStream(in).readFully(body);
            String method=request.split(" ")[0];calls.add(new Call(method,path.get(),new String(body,StandardCharsets.UTF_8)));
            if(upgrade&&path.get().equals("/ws")){
                String accept=invalidHandshake?"bad":Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-1").digest((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").getBytes(StandardCharsets.US_ASCII)));
                out.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: "+accept+"\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                if(closeCode!=0){out.write(new byte[]{(byte)0x88,2,(byte)(closeCode>>8),(byte)closeCode});out.flush();continue;}
                if(ping){out.write(new byte[]{(byte)0x89,1,42});out.flush();int a=in.read(),b=in.read();assertEquals(0x8a,a);assertEquals(0x81,b);byte[] mask=new byte[4];new DataInputStream(in).readFully(mask);assertEquals(42,in.read()^(mask[0]&255));pong.countDown();}
                byte[] bytes=response.getBytes(StandardCharsets.UTF_8);
                if(fragment){int half=bytes.length/2;out.write(1);out.write(half);out.write(bytes,0,half);out.write(0x80);out.write(bytes.length-half);out.write(bytes,half,bytes.length-half);}else{out.write(0x81);out.write(bytes.length);out.write(bytes);}out.flush();Thread.sleep(150);continue;
            }
            boolean command=method.equals("POST")&&path.get().endsWith("/cmd");if(command&&afterCommand!=null)afterCommand.run();if(command&&dropCommandResponse)continue;
            boolean print=method.equals("POST")&&path.get().endsWith("/print");if(print&&dropPrintResponse)continue;
            Reply reply=print?printReply:command?commandReplies.poll():null;
            String responseBody=reply!=null?reply.body:responses.getOrDefault(method+" "+path.get(),responses.getOrDefault(path.get(),response));
            byte[] bytes=responseBody.getBytes(StandardCharsets.UTF_8);out.write(("HTTP/1.1 "+(reply!=null?reply.status:status)+" Test\r\nContent-Type: application/json\r\nContent-Length: "+bytes.length+"\r\nSet-Cookie: fm_session=fixture; Path=/; HttpOnly\r\n\r\n").getBytes(StandardCharsets.US_ASCII));out.write(bytes);out.flush();
        }catch(Exception|AssertionError ex){if(!server.isClosed())failure.set(ex.toString());}});worker.setDaemon(true);worker.start();
    }
    @After public void teardown() throws Exception {server.close();worker.join(3500);assertNull(failure.get());}
    @Test public void arraysUseSameAuthenticatedCookie() throws Exception {assertEquals(0,api.callArray("/api/printers").length());api.callArray("/api/projects2");assertTrue(cookie.get().contains("fm_session=fixture"));}
    @Test public void objectErrorOnArrayEndpointIsRejected() throws Exception {response="{\"ok\":false,\"error\":\"denied\"}";try{api.callArray("/api/printers");fail();}catch(FmApi.Rejected expected){assertEquals("denied",expected.code);}}
    @Test public void wrongFormatIsNotAcceptedAsEmptyArray() throws Exception {response="{}";try{api.callArray("/api/modules");fail();}catch(IOException expected){}}
    private FarmRepository inventoryServer(String modules) throws Exception {
        responses.put("/api/auth/status","{\"enabled\":true,\"authenticated\":true,\"user\":{\"role\":\"operator\"}}");
        responses.put("/api/modules",modules);return new FarmRepository(api);
    }
    @Test public void kernelWrappedModulesRestoreWarehouseAndItsCards() throws Exception {
        FarmRepository repo=inventoryServer("{\"modules\":[{\"id\":\"inventory\",\"state\":\"loaded\",\"disabled\":false,\"version\":\"1.7.31\"}],\"restart_needed\":false}");
        assertTrue(repo.refreshCapabilities().inventory);assertTrue(repo.capabilities.modulesKnown);assertTrue(repo.capabilities.operate);
        responses.put("/api/printer-filament","{\"printers\":{\"p1\":{\"slots\":[]}}}");assertNotNull(repo.filament().getJSONObject("p1"));
        responses.put("/api/printer-badges","{\"badges\":{\"p1\":[{\"module_id\":\"inventory\",\"text\":\"stock\"},{\"module_id\":\"missing\",\"text\":\"hidden\"}]}}");assertEquals(1,repo.badges().getJSONArray("p1").length());
        assertTrue(cookie.get().contains("fm_session=fixture"));
    }
    @Test public void legacyModuleArrayRemainsReadable() throws Exception {FarmRepository repo=inventoryServer("[{\"id\":\"inventory\",\"state\":\"loaded\",\"disabled\":false}]");assertTrue(repo.refreshCapabilities().inventory);}
    @Test public void wrappedDisabledOrMissingModuleDoesNotExposeWarehouse() throws Exception {
        FarmRepository repo=inventoryServer("{\"modules\":[{\"id\":\"inventory\",\"state\":\"disabled\",\"disabled\":true}],\"restart_needed\":true}");assertFalse(repo.refreshCapabilities().inventory);assertTrue(repo.capabilities.modulesKnown);
        responses.put("/api/modules","{\"modules\":[],\"restart_needed\":false}");assertFalse(repo.refreshCapabilities().inventory);assertTrue(repo.capabilities.operate);
    }
    @Test public void invalidModuleResponseIsUnknownInsteadOfConfirmedAbsent() throws Exception {
        FarmRepository repo=inventoryServer("{\"modules\":null}");assertFalse(repo.refreshCapabilities().inventory);assertFalse(repo.capabilities.modulesKnown);assertTrue(repo.capabilities.operate);
        try{repo.requireInventory();fail();}catch(IOException expected){assertTrue(expected.getMessage().contains("FM"));}
        Capabilities before=repo.capabilities;responses.put("/api/modules","{\"modules\":[{\"id\":\"inventory\",\"state\":\"loaded\"}]}");assertTrue(repo.refreshCapabilities().inventory);assertFalse(before.sameAvailability(repo.capabilities));repo.requireInventory();
    }
    @Test public void revokedLoginNeverFallsBackToNoModules() throws Exception {FarmRepository repo=inventoryServer("{\"modules\":[]}");responses.put("/api/auth/status","{\"enabled\":true,\"authenticated\":false}");try{repo.refreshCapabilities();fail();}catch(FmApi.Unauthorized expected){}}
    private FarmRepository controlsServer(String type) throws Exception {
        FarmRepository repo=inventoryServer("{\"modules\":[]}");responses.put("/api/printers","[{\"id\":\"p1\",\"type\":\""+type+"\"}]");responses.put("/api/printer/p1/cmd","{\"status\":\"ok\"}");responses.put("GET /api/farm-settings","{\"ok\":true,\"settings\":{}}");return repo;
    }
    private JSONObject live(String status) throws Exception{return new JSONObject().put("status",status).put("seen_ago",0);}
    private List<Call> mutations(){List<Call> result=new ArrayList<>();synchronized(calls){for(Call call:calls)if(call.method.equals("POST"))result.add(call);}return result;}
    private FarmRepository repeatServer(boolean quality)throws Exception {
        FarmRepository repo=controlsServer("bambu");
        responses.put("/api/modules",quality?"{\"modules\":[{\"id\":\"quality\",\"state\":\"loaded\"}]}":"{\"modules\":[]}");
        responses.put("/api/send-jobs","{\"jobs\":[],\"reserved_printer_ids\":[]}");
        responses.put("/api/projects2","[{\"id\":\"pr1\",\"name\":\"Project 1\"}]");
        responses.put("/api/projects2/pr1/tree","{\"nodes\":[{\"file_id\":\"f1\",\"filename\":\"Holder.gcode.3mf\",\"content_hash\":\"h1\",\"is_printable\":true,\"compatible_pids\":[\"p1\"]}]}");
        responses.put("/api/staging","[]");
        responses.put("/api/mod/quality/print-runs?printer_id=p1&limit=2",repeatHistory("r1","finished"));
        responses.put("POST /api/projects2/pr1/files/f1/print","{\"status\":\"ok\",\"accepted\":true,\"job_id\":\"send_new\",\"pjob_id\":\"pjob_new\"}");
        responses.put("POST /api/part/print","{\"status\":\"ok\",\"accepted\":true,\"job_id\":\"send_task\"}");return repo;
    }
    private String repeatHistory(String id,String outcome)throws Exception {
        return new JSONObject().put("runs",new JSONArray().put(new JSONObject().put("run_id",id).put("printer_id","p1").put("source","project").put("project_id","pr1").put("file_id","f1").put("filename","Holder.gcode.3mf").put("file_hash","h1").put("outcome_raw",outcome).put("source_payload",new JSONObject().put("server_sent",true)))).toString();
    }
    private JSONObject finishedPrinter()throws Exception{return live("FINISH").put("status_raw","FINISH").put("file_name","Holder.gcode.3mf");}
    private PrintRequest repeatRequest(RepeatPrint.Target target)throws Exception{return new PrintRequest(target.projectId,target.file.optString("file_id"),target.file.getString("filename"),target.printerId,-1,new JSONObject().put("bed_leveling",true));}
    private PrintJournal memoryJournal(){return new PrintJournal(new PrintJournal.Store(){private String value="";public String read(){return value;}public boolean write(String next){value=next;return true;}public boolean clear(){value="";return true;}});}
    @Test public void repeatCreatesOneNewProjectSendAndWaitsForConfirmation()throws Exception {
        FarmRepository repo=repeatServer(true);JSONObject state=finishedPrinter();PrintJournal journal=memoryJournal();RepeatPrint.Target target=repo.repeatTarget("p1",()->state,()->0L);
        JSONObject result=repo.repeat(target,repeatRequest(target),true,()->state,()->0L,journal);assertTrue(PrintRequest.accepted(result));assertEquals("send_new",journal.find(api.origin,"p1").jobId());assertTrue(journal.blocks(api.origin,"p1"));assertFalse(journal.blocks(api.origin,"p2"));
        assertEquals(1,mutations().size());Call call=mutations().get(0);assertEquals("/api/projects2/pr1/files/f1/print",call.path);JSONObject body=new JSONObject(call.body);assertEquals("p1",body.getString("printer_id"));assertFalse(body.has("force"));assertFalse(body.has("skip_filament"));assertFalse(body.has("printed_qty"));assertTrue(cookie.get().contains("fm_session=fixture"));
    }
    @Test public void repeatWithoutFmHistoryNeverGuessesFileFromPrinterName()throws Exception {FarmRepository repo=repeatServer(false);JSONObject s=finishedPrinter();assertThrows(IllegalStateException.class,()->repo.repeatTarget("p1",()->s,()->0L));assertTrue(mutations().isEmpty());assertTrue(calls.stream().noneMatch(c->c.path.startsWith("/api/mod/")||c.path.contains("/tree")));}
    @Test public void quickRepeatNeverScansProjectTrees()throws Exception {FarmRepository repo=repeatServer(true);JSONObject h=new JSONObject(repeatHistory("r1","finished"));h.getJSONArray("runs").getJSONObject(0).put("source","quick").put("file_hash","");responses.put("/api/mod/quality/print-runs?printer_id=p1&limit=2",h.toString());responses.put("/api/staging","[]");JSONObject s=finishedPrinter();assertThrows(IllegalStateException.class,()->repo.repeatTarget("p1",()->s,()->0L));assertTrue(calls.stream().noneMatch(c->c.path.contains("/tree")));assertTrue(mutations().isEmpty());}
    @Test public void quickHistoryRepeatsThroughTaskRouteWithQuickSource()throws Exception {
        FarmRepository repo=repeatServer(true);JSONObject h=new JSONObject(repeatHistory("r1","finished"));h.getJSONArray("runs").getJSONObject(0).put("source","quick").put("file_hash","").put("source_payload",new JSONObject().put("staging_file","Holder.gcode.3mf").put("server_sent",true));responses.put("/api/mod/quality/print-runs?printer_id=p1&limit=2",h.toString());responses.put("/api/staging","[{\"filename\":\"Holder.gcode.3mf\",\"is_printable\":true,\"compatible_pids\":[\"p1\"],\"mtime\":10}]");
        JSONObject s=finishedPrinter();RepeatPrint.Target target=repo.repeatTarget("p1",()->s,()->0L);repo.repeat(target,repeatRequest(target),true,()->s,()->0L,memoryJournal());assertEquals("/api/part/print",mutations().get(0).path);JSONObject body=new JSONObject(mutations().get(0).body);assertEquals("quick",body.getString("source"));assertEquals("Holder.gcode.3mf",body.getString("gcode_file"));
    }
    @Test public void noEmptyPlateConfirmationMeansNoRequests()throws Exception {FarmRepository repo=repeatServer(true);JSONObject s=finishedPrinter();RepeatPrint.Target t=repo.repeatTarget("p1",()->s,()->0L);int before=calls.size();PrintJournal j=memoryJournal();assertThrows(IllegalStateException.class,()->repo.repeat(t,repeatRequest(t),false,()->s,()->0L,j));assertEquals(before,calls.size());assertFalse(j.pending(api.origin));}
    @Test public void changedLastRunRejectsOldDialogBeforeJournalOrPost()throws Exception {FarmRepository repo=repeatServer(true);JSONObject s=finishedPrinter();RepeatPrint.Target t=repo.repeatTarget("p1",()->s,()->0L);responses.put("/api/mod/quality/print-runs?printer_id=p1&limit=2",repeatHistory("r2","finished"));PrintJournal j=memoryJournal();assertThrows(IllegalStateException.class,()->repo.repeat(t,repeatRequest(t),true,()->s,()->0L,j));assertFalse(j.pending(api.origin));assertTrue(mutations().isEmpty());}
    @Test public void changedTaskMtimeRejectsOldDialog()throws Exception {FarmRepository repo=repeatServer(true);JSONObject h=new JSONObject(repeatHistory("r1","finished"));h.getJSONArray("runs").getJSONObject(0).put("source","quick").put("file_hash","");responses.put("/api/mod/quality/print-runs?printer_id=p1&limit=2",h.toString());responses.put("/api/projects2","[]");responses.put("/api/staging","[{\"filename\":\"Holder.gcode.3mf\",\"is_printable\":true,\"compatible_pids\":[\"p1\"],\"mtime\":10}]");JSONObject s=finishedPrinter();RepeatPrint.Target t=repo.repeatTarget("p1",()->s,()->0L);responses.put("/api/staging",responses.get("/api/staging").replace("10","11"));assertThrows(IllegalStateException.class,()->repo.repeat(t,repeatRequest(t),true,()->s,()->0L,memoryJournal()));assertTrue(mutations().isEmpty());}
    @Test public void changedProjectHashRejectsBeforeSending()throws Exception {FarmRepository repo=repeatServer(true);JSONObject s=finishedPrinter();RepeatPrint.Target t=repo.repeatTarget("p1",()->s,()->0L);responses.put("/api/projects2/pr1/tree",responses.get("/api/projects2/pr1/tree").replace("h1","h2"));assertThrows(IllegalStateException.class,()->repo.repeat(t,repeatRequest(t),true,()->s,()->0L,memoryJournal()));assertTrue(mutations().isEmpty());}
    @Test public void printerBecomingReservedBlocksRepeat()throws Exception {FarmRepository repo=repeatServer(true);JSONObject s=finishedPrinter();RepeatPrint.Target t=repo.repeatTarget("p1",()->s,()->0L);responses.put("/api/send-jobs","{\"jobs\":[],\"reserved_printer_ids\":[\"p1\"]}");assertThrows(IllegalStateException.class,()->repo.repeat(t,repeatRequest(t),true,()->s,()->0L,memoryJournal()));assertTrue(mutations().isEmpty());}
    @Test public void revokedOperatorCannotRepeatPreparedJob()throws Exception {FarmRepository repo=repeatServer(true);JSONObject s=finishedPrinter();RepeatPrint.Target t=repo.repeatTarget("p1",()->s,()->0L);responses.put("/api/auth/status","{\"enabled\":true,\"authenticated\":true,\"user\":{\"role\":\"viewer\"}}");assertThrows(SecurityException.class,()->repo.repeat(t,repeatRequest(t),true,()->s,()->0L,memoryJournal()));assertTrue(mutations().isEmpty());}
    @Test public void busyOrStaleTelemetryCannotRepeatPreparedJob()throws Exception {FarmRepository repo=repeatServer(true);JSONObject s=finishedPrinter();RepeatPrint.Target t=repo.repeatTarget("p1",()->s,()->0L);assertThrows(IllegalStateException.class,()->repo.repeat(t,repeatRequest(t),true,()->s,()->6500L,memoryJournal()));s.put("status","RUNNING").put("status_raw","RUNNING");assertThrows(IllegalStateException.class,()->repo.repeat(t,repeatRequest(t),true,()->s,()->0L,memoryJournal()));assertTrue(mutations().isEmpty());}
    @Test public void disabledQualityIsNeverQueried()throws Exception {FarmRepository repo=repeatServer(false);responses.put("/api/modules","{\"modules\":[{\"id\":\"quality\",\"state\":\"loaded\",\"disabled\":true}]}");JSONObject s=finishedPrinter();assertThrows(IllegalStateException.class,()->repo.repeatTarget("p1",()->s,()->0L));assertTrue(calls.stream().noneMatch(c->c.path.contains("quality")));}
    @Test public void loadedHistoryWithFailedLatestRunDoesNotFallback()throws Exception {FarmRepository repo=repeatServer(true);responses.put("/api/mod/quality/print-runs?printer_id=p1&limit=2",repeatHistory("r2","failed"));JSONObject s=finishedPrinter();assertThrows(IllegalStateException.class,()->repo.repeatTarget("p1",()->s,()->0L));assertTrue(mutations().isEmpty());}
    @Test public void lostRepeatResponseKeepsUnknownJournalAndNeverResends()throws Exception {FarmRepository repo=repeatServer(true);JSONObject s=finishedPrinter();RepeatPrint.Target t=repo.repeatTarget("p1",()->s,()->0L);PrintJournal j=memoryJournal();dropPrintResponse=true;assertThrows(PrintJournal.Unknown.class,()->repo.repeat(t,repeatRequest(t),true,()->s,()->0L,j));assertTrue(j.blocks(api.origin,"p1"));assertEquals("",j.find(api.origin,"p1").jobId());assertEquals(1,mutations().size());assertThrows(IllegalStateException.class,()->repo.repeat(t,repeatRequest(t),true,()->s,()->0L,j));assertEquals(1,mutations().size());}
    @Test public void serverConflictIsOneRefusedSubmissionWithoutCountChange()throws Exception {FarmRepository repo=repeatServer(true);JSONObject s=finishedPrinter();RepeatPrint.Target t=repo.repeatTarget("p1",()->s,()->0L);PrintJournal j=memoryJournal();printReply=new Reply(409,"{\"status\":\"error\",\"reason\":\"printer_held\"}");assertThrows(FmApi.Rejected.class,()->repo.repeat(t,repeatRequest(t),true,()->s,()->0L,j));assertFalse(j.pending(api.origin));assertEquals(1,mutations().size());}
    @Test public void serverMaterialShortageClearsRejectedJournalWithoutRetry()throws Exception {FarmRepository repo=repeatServer(true);JSONObject s=finishedPrinter();RepeatPrint.Target t=repo.repeatTarget("p1",()->s,()->0L);PrintJournal j=memoryJournal();printReply=new Reply(200,"{\"status\":\"shortage\"}");assertEquals("shortage",repo.repeat(t,repeatRequest(t),true,()->s,()->0L,j).getString("status"));assertFalse(j.pending(api.origin));assertEquals(1,mutations().size());}
    @Test public void responseWithoutAcceptedJobIdKeepsUncertainty()throws Exception {FarmRepository repo=repeatServer(true);JSONObject s=finishedPrinter();RepeatPrint.Target t=repo.repeatTarget("p1",()->s,()->0L);PrintJournal j=memoryJournal();printReply=new Reply(200,"{\"status\":\"ok\"}");repo.repeat(t,repeatRequest(t),true,()->s,()->0L,j);assertTrue(j.blocks(api.origin,"p1"));assertEquals("",j.find(api.origin,"p1").jobId());assertEquals(1,mutations().size());}
    @Test public void qrOnlyReadsMetadataAndPrintersWithoutChangingStock()throws Exception {FarmRepository repo=repeatServer(false);responses.put("/api/modules","{\"modules\":[{\"id\":\"inventory\",\"state\":\"loaded\"}]}");responses.put("/api/mod/inventory/filament","{\"mobile\":{\"protocol\":1,\"server_id\":\"farm\"}}");assertEquals("p1",repo.scannedPrinter("fm1:slot:farm:p1:0").getString("id"));assertTrue(mutations().isEmpty());assertTrue(calls.stream().noneMatch(c->c.path.contains("/ams")||c.path.contains("/bind")));}
    @Test public void qrRejectsAnotherFarmWithoutStockWrite()throws Exception {FarmRepository repo=repeatServer(false);responses.put("/api/modules","{\"modules\":[{\"id\":\"inventory\",\"state\":\"loaded\"}]}");responses.put("/api/mod/inventory/filament","{\"mobile\":{\"protocol\":1,\"server_id\":\"farm\"}}");assertThrows(IllegalArgumentException.class,()->repo.scannedPrinter("fm1:slot:other:p1:0"));assertTrue(mutations().isEmpty());}
    @Test public void missingInventoryDoesNotProbeItsRoutes()throws Exception {FarmRepository repo=repeatServer(false);assertThrows(IOException.class,()->repo.scannedPrinter("fm1:slot:farm:p1:0"));assertTrue(calls.stream().noneMatch(c->c.path.startsWith("/api/mod/inventory")));}
    @Test public void viewerMayScanPrinterButCannotRepeatPrint()throws Exception {FarmRepository repo=repeatServer(false);responses.put("/api/modules","{\"modules\":[{\"id\":\"inventory\",\"state\":\"loaded\"}]}");responses.put("/api/mod/inventory/filament","{\"mobile\":{\"protocol\":1,\"server_id\":\"farm\"}}");responses.put("/api/auth/status","{\"enabled\":true,\"authenticated\":true,\"user\":{\"role\":\"viewer\"}}");assertEquals("p1",repo.scannedPrinter("fm1:slot:farm:p1:0").getString("id"));JSONObject s=finishedPrinter();assertThrows(SecurityException.class,()->repo.repeatTarget("p1",()->s,()->0L));assertTrue(mutations().isEmpty());}
    @Test public void archivedProjectIsNotReplacedBySimilarTask()throws Exception {FarmRepository repo=repeatServer(true);responses.put("/api/projects2","[{\"id\":\"pr1\",\"is_archived\":true}]");responses.put("/api/staging","[{\"filename\":\"Holder.gcode.3mf\",\"is_printable\":true,\"compatible_pids\":[\"p1\"]}]");JSONObject s=finishedPrinter();assertThrows(IllegalStateException.class,()->repo.repeatTarget("p1",()->s,()->0L));assertTrue(mutations().isEmpty());}
    @Test public void pauseResumeStopUseOfficialRouteWithoutInventory() throws Exception {FarmRepository repo=controlsServer("bambu");JSONObject s=live("RUNNING");repo.control("p1","pause",()->s,()->1);s.put("status","PAUSED");repo.control("p1","resume",()->s,()->1);repo.control("p1","stop",()->s,()->1);List<Call> sent=mutations();assertEquals(3,sent.size());for(int i=0;i<3;i++){assertEquals("/api/printer/p1/cmd",sent.get(i).path);assertEquals(new String[]{"pause","resume","stop"}[i],new JSONObject(sent.get(i).body).getString("cmd"));}assertFalse(repo.capabilities.inventory);assertTrue(cookie.get().contains("fm_session=fixture"));}
    @Test public void viewingRoleCannotSendPrinterCommand() throws Exception {FarmRepository repo=controlsServer("bambu");JSONObject s=live("RUNNING");responses.put("/api/auth/status","{\"enabled\":true,\"authenticated\":true,\"user\":{\"role\":\"observer\"}}");try{repo.control("p1","stop",()->s,()->1);fail();}catch(PrinterCommand.Failure expected){}assertTrue(mutations().isEmpty());}
    @Test public void staleTelemetryBlocksCommandBeforePost() throws Exception {FarmRepository repo=controlsServer("bambu");JSONObject s=live("RUNNING");try{repo.control("p1","pause",()->s,()->6500);fail();}catch(PrinterCommand.Failure expected){}assertTrue(mutations().isEmpty());}
    @Test public void deletedOrUnknownTypePrinterDoesNotReceiveCommands() throws Exception {FarmRepository repo=controlsServer("unknown");JSONObject s=live("RUNNING");try{repo.control("p1","stop",()->s,()->1);fail();}catch(PrinterCommand.Failure expected){}responses.put("/api/printers","[]");try{repo.control("p1","stop",()->s,()->1);fail();}catch(PrinterCommand.Failure expected){}assertTrue(mutations().isEmpty());}
    @Test public void stopFailureOrErrorBodyIsNotReportedAsSuccess() throws Exception {FarmRepository repo=controlsServer("bambu");JSONObject s=live("RUNNING");commandReplies.add(new Reply(502,"{\"status\":\"error\",\"reason\":\"stop_not_delivered\"}"));try{repo.control("p1","stop",()->s,()->1);fail();}catch(PrinterCommand.Failure expected){}commandReplies.add(new Reply(200,"{\"status\":\"error\"}"));try{repo.control("p1","stop",()->s,()->1);fail();}catch(PrinterCommand.Failure expected){}assertEquals(2,mutations().size());assertEquals("RUNNING",s.getString("status"));}
    @Test public void responseLossNeverAutomaticallyRepeatsCommand() throws Exception {FarmRepository repo=controlsServer("bambu");JSONObject s=live("RUNNING");dropCommandResponse=true;try{repo.control("p1","pause",()->s,()->1);fail();}catch(PrinterCommand.Failure expected){}assertEquals(1,mutations().size());}
    @Test public void sharedPresetUsesCanonicalTemperaturesAndNoSettingsWrite() throws Exception {FarmRepository repo=controlsServer("klipper");JSONObject s=live("IDLE");repo.preheat("p1",PreheatPresets.defaults().find("PLA"),false,()->s,()->1);List<Call> sent=mutations();assertEquals(2,sent.size());assertEquals("220",new JSONObject(sent.get(0).body).getString("val"));assertEquals("bed",new JSONObject(sent.get(1).body).getString("cmd"));for(Call call:sent)assertTrue(call.path.endsWith("/cmd"));}
    @Test public void changedPresetIsNotAppliedFromStaleDialog() throws Exception {FarmRepository repo=controlsServer("bambu");JSONObject s=live("IDLE");responses.put("GET /api/farm-settings","{\"ok\":true,\"settings\":{\"preheat_presets\":[{\"name\":\"PLA\",\"n\":230,\"b\":60}]}}");try{repo.preheat("p1",PreheatPresets.defaults().find("PLA"),false,()->s,()->1);fail();}catch(PrinterCommand.Failure expected){}assertTrue(mutations().isEmpty());}
    @Test public void partiallyAppliedHeatStopsAtFirstRejectedCommand() throws Exception {FarmRepository repo=controlsServer("bambu");JSONObject s=live("IDLE").put("nozzle_count",2).put("chamber_heater",true);PreheatPresets.Preset off=new PreheatPresets.Preset("Off",0,0,0);commandReplies.add(new Reply(200,"{\"status\":\"ok\"}"));commandReplies.add(new Reply(400,"{\"status\":\"error\"}"));try{repo.preheat("p1",off,true,()->s,()->1);fail();}catch(PrinterCommand.Failure expected){assertTrue(expected.getMessage().contains(PrinterCommand.heat("nozzle_l",0).caption()));}assertEquals(2,mutations().size());}
    @Test public void roleRevokedDuringHeatStopsRemainingCommands() throws Exception {FarmRepository repo=controlsServer("bambu");JSONObject s=live("IDLE");afterCommand=()->responses.put("/api/auth/status","{\"enabled\":true,\"authenticated\":true,\"user\":{\"role\":\"observer\"}}");try{repo.preheat("p1",new PreheatPresets.Preset("Off",0,0,0),true,()->s,()->1);fail();}catch(PrinterCommand.Failure expected){}assertEquals(1,mutations().size());}
    @Test public void coolingDoesNotRequireSavedPresetsAndNeverWritesSettings() throws Exception {FarmRepository repo=controlsServer("flashforge");JSONObject s=live("IDLE");responses.put("GET /api/farm-settings","{\"ok\":false}");repo.preheat("p1",new PreheatPresets.Preset("Off",0,0,0),true,()->s,()->1);assertEquals(2,mutations().size());for(Call call:mutations())assertEquals("0",new JSONObject(call.body).getString("val"));}
    @Test public void coolingCannotSmuggleNonzeroTargetPastPresetCheck() throws Exception {FarmRepository repo=controlsServer("bambu");JSONObject s=live("IDLE");try{repo.preheat("p1",new PreheatPresets.Preset("Other",250,90,0),true,()->s,()->1);fail();}catch(PrinterCommand.Failure expected){}assertTrue(mutations().isEmpty());}
    @Test public void savedPresetsOnlyWriteDeclaredFarmSetting() throws Exception {FarmRepository repo=controlsServer("bambu");PreheatPresets changed=new PreheatPresets(Arrays.asList(new PreheatPresets.Preset("Custom",245,80,45)));responses.put("POST /api/farm-settings",new JSONObject().put("ok",true).put("preheat_presets",changed.json()).toString());assertTrue(changed.same(repo.savePresets(PreheatPresets.defaults(),changed)));List<Call> sent=mutations();assertEquals(1,sent.size());assertEquals("/api/farm-settings",sent.get(0).path);assertEquals(1,new JSONObject(sent.get(0).body).length());}
    @Test public void concurrentPresetChangeIsNotOverwritten() throws Exception {FarmRepository repo=controlsServer("bambu");PreheatPresets changed=new PreheatPresets(Collections.emptyList());responses.put("GET /api/farm-settings",new JSONObject().put("ok",true).put("settings",new JSONObject().put("preheat_presets",changed.json())).toString());try{repo.savePresets(PreheatPresets.defaults(),changed);fail();}catch(PrinterCommand.Failure expected){}assertTrue(mutations().isEmpty());}
    @Test public void loginRevokedDuringCommandReturnsToAuthentication() throws Exception {FarmRepository repo=controlsServer("bambu");JSONObject s=live("RUNNING");commandReplies.add(new Reply(401,"{}"));try{repo.control("p1","stop",()->s,()->1);fail();}catch(FmApi.Unauthorized expected){}assertEquals(1,mutations().size());}
    // R-145: 409 heater_off_while_printing — сначала вопрос, затем ТОТ ЖЕ запрос с "force": true; без согласия повтора нет.
    @Test public void heaterOffDuringPrintIsRefusedThenRepeatedWithForceOnlyAfterConsent() throws Exception {
        FarmRepository repo=controlsServer("klipper");JSONObject s=live("RUNNING");PreheatPresets.Preset off=new PreheatPresets.Preset("Off",0,0,0);
        commandReplies.add(new Reply(409,"{\"status\":\"error\",\"reason\":\"heater_off_while_printing\"}"));
        PrinterCommand.NeedsForce refused=assertThrows(PrinterCommand.NeedsForce.class,()->repo.preheat("p1",off,true,()->s,()->1));
        assertEquals(1,mutations().size());JSONObject first=new JSONObject(mutations().get(0).body);assertFalse(first.has("force"));assertEquals(0,refused.next);assertTrue(refused.accepted.isEmpty());
        repo.preheatForced(refused,()->s,()->1);List<Call> sent=mutations();assertEquals(3,sent.size());
        JSONObject retry=new JSONObject(sent.get(1).body);assertEquals(first.getString("cmd"),retry.getString("cmd"));assertEquals(first.getString("val"),retry.getString("val"));assertTrue(retry.getBoolean("force"));assertEquals(3,retry.length());
        JSONObject bed=new JSONObject(sent.get(2).body);assertEquals("bed",bed.getString("cmd"));assertTrue(bed.getBoolean("force"));
        for(Call call:sent)assertEquals("/api/printer/p1/cmd",call.path);
    }
    @Test public void heaterRefusalAfterAcceptedCommandResumesFromTheRefusedOne() throws Exception {
        FarmRepository repo=controlsServer("klipper");JSONObject s=live("RUNNING");PreheatPresets.Preset partial=new PreheatPresets.Preset("Bed off",220,0,null);
        responses.put("GET /api/farm-settings","{\"ok\":true,\"settings\":{\"preheat_presets\":[{\"name\":\"Bed off\",\"n\":220,\"b\":0}]}}");
        commandReplies.add(new Reply(200,"{\"status\":\"ok\"}"));commandReplies.add(new Reply(409,"{\"status\":\"error\",\"reason\":\"heater_off_while_printing\"}"));
        PrinterCommand.NeedsForce refused=assertThrows(PrinterCommand.NeedsForce.class,()->repo.preheat("p1",partial,false,()->s,()->1));
        assertEquals(1,refused.next);assertEquals(1,refused.accepted.size());assertEquals(2,mutations().size());
        repo.preheatForced(refused,()->s,()->1);assertEquals(3,mutations().size());JSONObject retry=new JSONObject(mutations().get(2).body);assertEquals("bed",retry.getString("cmd"));assertTrue(retry.getBoolean("force"));
    }
    @Test public void forcedRetryIsNeverSentAutomaticallyOnOtherErrors() throws Exception {
        FarmRepository repo=controlsServer("klipper");JSONObject s=live("RUNNING");commandReplies.add(new Reply(409,"{\"status\":\"error\",\"reason\":\"printer_busy\"}"));
        PrinterCommand.Failure failure=assertThrows(PrinterCommand.Failure.class,()->repo.preheat("p1",new PreheatPresets.Preset("Off",0,0,0),true,()->s,()->1));
        assertFalse(failure.delivery);assertEquals(1,mutations().size());for(Call call:mutations())assertFalse(new JSONObject(call.body).has("force"));
    }
    // R-145: 502 command_not_delivered / command_not_confirmed / stop_not_delivered — понятный текст, состояние не меняется.
    @Test public void commandDeliveryFailuresAreReadableAndDoNotChangeShownState() throws Exception {
        FarmRepository repo=controlsServer("bambu");JSONObject s=live("RUNNING");String before=s.toString();
        String[][] cases={{"pause","command_not_delivered","Команда не дошла до принтера — проверьте связь."},{"pause","command_not_confirmed","Принтер не подтвердил команду — проверьте его состояние."},{"stop","stop_not_delivered","Команда «Стоп» не дошла до принтера — печать продолжается."}};
        for(String[] c:cases){commandReplies.add(new Reply(502,"{\"status\":\"error\",\"reason\":\""+c[1]+"\"}"));
            PrinterCommand.Failure failure=assertThrows(PrinterCommand.Failure.class,()->repo.control("p1",c[0],()->s,()->1));assertTrue(failure.delivery);assertEquals(c[2],failure.getMessage());}
        assertEquals(before,s.toString());assertEquals(3,mutations().size());
        commandReplies.add(new Reply(502,"{\"status\":\"error\",\"reason\":\"command_not_delivered\"}"));
        JSONObject idle=live("IDLE");PrinterCommand.Failure heat=assertThrows(PrinterCommand.Failure.class,()->repo.preheat("p1",PreheatPresets.defaults().find("PLA"),false,()->idle,()->1));assertTrue(heat.delivery);assertTrue(heat.getMessage().startsWith("Команда не дошла до принтера"));assertTrue(heat.getMessage().endsWith("Остальные команды не отправлены."));
    }
    @Test public void serverErrorKeepsReasonButStaysUncertain() throws Exception {status=502;response="{\"status\":\"error\",\"reason\":\"command_not_delivered\"}";FmApi.ServerError e=assertThrows(FmApi.ServerError.class,()->api.call("POST","/api/printer/p1/cmd",new JSONObject()));assertEquals("command_not_delivered",e.code);assertEquals(502,e.status);Exception asException=e;assertFalse(asException instanceof FmApi.Rejected);}
    // Отметка «запуск не проверен» — по принтеру этого FM: другой принтер можно запускать сразу.
    @Test public void launchMarksOnlyItsPrinterAndAcceptedJobId() throws Exception {
        FarmRepository repo=repeatServer(false);PrintJournal j=memoryJournal();
        JSONObject r=repo.launch(new PrintRequest("pr1","f1","Holder.gcode.3mf","p1",null,null),j);assertTrue(PrintRequest.accepted(r));
        assertEquals("send_new",j.find(api.origin,"p1").jobId());assertTrue(j.blocks(api.origin,"p1"));assertFalse(j.blocks(api.origin,"p2"));assertFalse(j.blocks("http://other.test:8000","p1"));
        assertThrows(IllegalStateException.class,()->repo.launch(new PrintRequest("pr1","f1","Holder.gcode.3mf","p1",null,null),j));assertEquals(1,mutations().size());
        repo.launch(new PrintRequest("","","Holder.gcode.3mf","p2",null,null),j);assertEquals(2,mutations().size());assertTrue(j.blocks(api.origin,"p2"));
        JSONObject body=new JSONObject(mutations().get(0).body);assertFalse(body.has("ams_slot"));assertFalse(body.has("print_opts"));
    }
    @Test public void klipperStartSendsOnlyAllowlistedStepsAndCfsCell() throws Exception {
        FarmRepository repo=repeatServer(false);responses.put("/api/printer/p1/klipper-prestart","{\"status\":\"ok\",\"reachable\":true,\"capabilities\":[{\"id\":\"bed_mesh_calibrate\",\"state\":\"supported_automatic\",\"supported\":true,\"auto_execute\":true,\"safe_each_print\":true,\"label_ru\":\"Калибровка стола (bed mesh)\"},{\"id\":\"screws_tilt\",\"state\":\"supported_manual\",\"supported\":true}],\"prefs\":{\"bed_mesh_calibrate\":true}}");
        JSONObject prestart=repo.klipperPrestart("p1");List<KlipperStart.Step> steps=KlipperStart.steps(prestart);assertEquals(1,steps.size());assertTrue(steps.get(0).selected());
        JSONObject opts=PrintChoice.options("klipper",false,false,false,2,KlipperStart.chosen(steps,Set.of("bed_mesh_calibrate","screws_tilt")));
        repo.launch(new PrintRequest("pr1","f1","Holder.gcode.3mf","p1",null,opts),memoryJournal());
        JSONObject body=new JSONObject(mutations().get(0).body);JSONObject sent=body.getJSONObject("print_opts");assertEquals(2,sent.getInt("cfs_slot"));assertEquals(1,sent.getJSONArray("klipper_prestart").length());assertEquals("bed_mesh_calibrate",sent.getJSONArray("klipper_prestart").getString(0));assertFalse(body.has("ams_slot"));
        repo.saveKlipperPrefs("p1",KlipperStart.prefs(prestart,Set.of("bed_mesh_calibrate")));Call saved=mutations().get(1);assertEquals("/api/printer/p1/klipper-prestart",saved.path);JSONObject prefs=new JSONObject(saved.body).getJSONObject("prefs");assertTrue(prefs.getBoolean("bed_mesh_calibrate"));assertFalse(prefs.getBoolean("screws_tilt"));
    }
    @Test public void mediaDoesNotFollowRedirects() throws Exception {status=302;try{api.openMedia("/api/printer/p1/camera");fail();}catch(IOException expected){}}
    @Test public void mediaRejectsForeignOrTraversalPathsWithoutNetwork() throws Exception {for(String value:new String[]{"//foreign.test/api/x","/api/../secret","/api/x#fragment","/api/x\\secret"})try{api.openMedia(value);fail(value);}catch(IOException expected){}assertNull(path.get());}
    @Test public void mediaAndBrowserUseExistingSessionOnly() throws Exception {api.callArray("/api/modules");assertTrue(api.browserSessionCookie().contains("fm_session=fixture"));try(FmApi.Media media=api.openMedia("/covers/printer.png")){assertNotNull(media.input);assertTrue(cookie.get().contains("fm_session=fixture"));}api.clearSession();assertFalse(api.browserSessionCookie().contains("fixture"));}
    private TelemetryClient start(CountDownLatch received,AtomicReference<JSONObject> states,AtomicReference<Exception> error){TelemetryClient client=new TelemetryClient(api,new TelemetryClient.Listener(){public void snapshot(JSONObject next){states.set(next);received.countDown();}public void disconnected(Exception ex){error.set(ex);received.countDown();}});client.start();return client;}
    @Test public void fragmentedTelemetryRetainsUnicodeAndCookie() throws Exception {api.callArray("/api/modules");response="{\"p1\":{\"file_name\":\"плата\",\"status\":\"IDLE\"}}";upgrade=true;fragment=true;CountDownLatch event=new CountDownLatch(1);AtomicReference<JSONObject> states=new AtomicReference<>();AtomicReference<Exception> error=new AtomicReference<>();try(TelemetryClient c=start(event,states,error)){assertTrue(event.await(3,TimeUnit.SECONDS));assertNull(error.get());assertEquals("плата",states.get().getJSONObject("p1").getString("file_name"));assertTrue(cookie.get().contains("fm_session=fixture"));assertEquals("/ws",path.get());}}
    @Test public void telemetryRespondsToPingWithMaskedPong() throws Exception {upgrade=true;ping=true;response="{}";CountDownLatch event=new CountDownLatch(1);AtomicReference<JSONObject> states=new AtomicReference<>();AtomicReference<Exception> error=new AtomicReference<>();try(TelemetryClient c=start(event,states,error)){assertTrue(pong.await(3,TimeUnit.SECONDS));assertTrue(event.await(3,TimeUnit.SECONDS));assertNull(error.get());}}
    @Test public void invalidHandshakeNeverDeliversTelemetry() throws Exception {upgrade=true;invalidHandshake=true;response="{}";CountDownLatch event=new CountDownLatch(1);AtomicReference<JSONObject> states=new AtomicReference<>();AtomicReference<Exception> error=new AtomicReference<>();try(TelemetryClient c=start(event,states,error)){assertTrue(event.await(3,TimeUnit.SECONDS));assertNull(states.get());assertNotNull(error.get());}}
    @Test public void policyAndAuthClosesRequireNewLogin() throws Exception {upgrade=true;for(int code:new int[]{1008,4401,4403}){closeCode=code;CountDownLatch event=new CountDownLatch(1);AtomicReference<JSONObject> states=new AtomicReference<>();AtomicReference<Exception> error=new AtomicReference<>();try(TelemetryClient c=start(event,states,error)){assertTrue(event.await(3,TimeUnit.SECONDS));assertTrue(error.get() instanceof FmApi.Unauthorized);assertNull(states.get());}}}
}
