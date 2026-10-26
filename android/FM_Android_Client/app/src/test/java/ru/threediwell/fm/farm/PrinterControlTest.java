// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import org.junit.Test;
import java.util.*;
import static org.junit.Assert.*;

public class PrinterControlTest {
    private JSONObject printer(String type) throws Exception{return new JSONObject().put("type",type);}
    private JSONObject state(String status) throws Exception{return new JSONObject().put("status",status).put("seen_ago",0);}
    private JSONObject settings(Object presets) throws Exception{return new JSONObject().put("ok",true).put("settings",new JSONObject().put("preheat_presets",presets));}
    @Test public void manualCommandsCannotStartFilesOrExecuteGcode(){for(String action:new String[]{"start_print","M112","gcode","pause\nstop","PAUSE","",null})try{PrinterCommand.control(action);fail();}catch(IllegalArgumentException expected){}}
    @Test public void simpleCommandBodyContainsOnlyLogicalActionAndEmptyValue() throws Exception {for(String action:new String[]{"pause","resume","stop"}){JSONObject body=PrinterCommand.control(action).body();assertEquals(2,body.length());assertEquals(action,body.getString("cmd"));assertEquals("",body.getString("val"));}}
    @Test public void valuesOutsideActualCoreLimitsAreRejected(){for(String action:new String[]{"nozzle","nozzle_l","nozzle_r","bed","chamber"}){int max=action.equals("bed")?120:action.equals("chamber")?65:350;assertEquals(Integer.valueOf(max),PrinterCommand.heat(action,max).temperature);for(int value:new int[]{-1,max+1})try{PrinterCommand.heat(action,value);fail();}catch(IllegalArgumentException expected){}}}
    @Test public void pausedPrinterOnlyResumesAndActivePrinterOnlyPauses() throws Exception {JSONObject p=printer("bambu");assertTrue(PrinterCommand.allowed(p,state("RUNNING"),1,"pause"));assertFalse(PrinterCommand.allowed(p,state("RUNNING"),1,"resume"));assertFalse(PrinterCommand.allowed(p,state("PAUSED"),1,"pause"));assertTrue(PrinterCommand.allowed(p,state("PAUSED"),1,"resume"));assertTrue(PrinterCommand.allowed(p,state("PAUSED"),1,"stop"));}
    @Test public void idleOrCompletedPrinterDoesNotOfferPrintStop() throws Exception {for(String status:new String[]{"IDLE","FINISH","FAILED","ERROR","UNKNOWN","OFFLINE"})for(String action:new String[]{"pause","resume","stop"})assertFalse(PrinterCommand.allowed(printer("klipper"),state(status),1,action));}
    @Test public void disconnectedOrUnknownPrinterNeverReceivesControl() throws Exception {assertFalse(PrinterCommand.allowed(printer("bambu"),state("RUNNING"),6500,"pause"));assertFalse(PrinterCommand.allowed(printer("bambu"),state("RUNNING").put("seen_ago",60),1,"stop"));assertFalse(PrinterCommand.allowed(printer("unsupported"),state("IDLE"),1,"heat"));assertFalse(PrinterCommand.allowed(printer("bambu"),null,1,"heat"));assertFalse(PrinterCommand.allowed(printer("bambu"),state("UNKNOWN"),1,"heat"));}
    @Test public void completeClientCommandFixturesUseOnlyDeclaredValues() throws Exception {
        JSONArray cases=new JSONArray();PreheatPresets.Preset preset=new PreheatPresets.Preset("Custom",350,120,65);
        for(String type:new String[]{"bambu","klipper","flashforge","demo"}){
            JSONObject p=printer(type).put("chamber_heater",true),s=state("IDLE").put("nozzle_count",2);
            for(PreheatPresets.Preset pr:Arrays.asList(preset,new PreheatPresets.Preset("Off",0,0,0)))for(PrinterCommand command:PrinterCommand.preheat(p,s,pr))cases.put(new JSONObject().put("type",type).put("body",command.body()));
            for(String action:new String[]{"pause","resume","stop"})cases.put(new JSONObject().put("type",type).put("body",PrinterCommand.control(action).body()));
        }
        assertEquals(36,cases.length());for(int i=0;i<cases.length();i++){JSONObject body=cases.getJSONObject(i).getJSONObject("body");assertEquals(2,body.length());assertTrue(body.has("cmd"));assertTrue(body.has("val"));}
        String directory=System.getenv("FM_CONTROL_TEST_OUTPUT");if(directory!=null&&!directory.isEmpty()){
            java.nio.file.Path dir=java.nio.file.Paths.get(directory);java.nio.file.Files.createDirectories(dir);
            java.nio.file.Files.write(dir.resolve("printer-command-fixtures.json"),new JSONObject().put("cases",cases).put("defaults",PreheatPresets.defaults().json()).put("custom",new PreheatPresets(Arrays.asList(preset)).json()).toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
    }
    @Test public void temperaturesAreCanonicalIntegersWithoutUserFragments() throws Exception {assertEquals("220",PrinterCommand.heat("nozzle",220).body().getString("val"));for(String input:new String[]{"220\nM112","1e2","220 C","1.5","NaN","-1","true"})try{PreheatPresets.input(input);fail();}catch(IllegalArgumentException expected){}}
    @Test public void dualBambuUsesBothOfficialNozzleActions() throws Exception {List<PrinterCommand> plan=PrinterCommand.preheat(printer("bambu"),state("IDLE").put("nozzle_count",2),new PreheatPresets.Preset("PLA",220,60,null));assertEquals(3,plan.size());assertEquals("nozzle_l",plan.get(0).action);assertEquals("nozzle_r",plan.get(1).action);assertEquals("bed",plan.get(2).action);}
    @Test public void otherTypesNeverUseBambuOnlyNozzleCommands() throws Exception {for(String type:new String[]{"klipper","flashforge","demo"}){List<PrinterCommand> plan=PrinterCommand.preheat(printer(type),state("IDLE").put("nozzle_count",2),new PreheatPresets.Preset("PLA",220,60,null));assertEquals(2,plan.size());assertEquals("nozzle",plan.get(0).action);}}
    @Test public void chamberTemperatureRequiresSupportedHeaterNotJustSensor() throws Exception {PreheatPresets.Preset preset=new PreheatPresets.Preset("ABS",250,90,50);JSONObject p=printer("klipper"),s=state("IDLE").put("chamber_temp",30);assertEquals(2,PrinterCommand.preheat(p,s,preset).size());s.put("chamber_heater",true);assertEquals("chamber",PrinterCommand.preheat(p,s,preset).get(2).action);assertEquals(2,PrinterCommand.preheat(printer("flashforge").put("chamber_heater",true),s,preset).size());}
    @Test public void emptyChamberTargetLeavesHeaterUntouchedAndZeroTurnsItOff() throws Exception {JSONObject p=printer("bambu").put("chamber_heater",true),s=state("IDLE");assertEquals(2,PrinterCommand.preheat(p,s,new PreheatPresets.Preset("PLA",220,60,null)).size());List<PrinterCommand> cool=PrinterCommand.preheat(p,s,new PreheatPresets.Preset("Off",0,0,0));assertEquals(3,cool.size());for(PrinterCommand command:cool)assertEquals(Integer.valueOf(0),command.temperature);}
    @Test public void unsetFarmPresetsUseExactDesktopDefaults() throws Exception {PreheatPresets set=PreheatPresets.read(new JSONObject().put("ok",true).put("settings",new JSONObject()));assertEquals(3,set.values.size());assertTrue(set.values.get(0).same(new PreheatPresets.Preset("PLA",220,60,null)));assertTrue(set.values.get(1).same(new PreheatPresets.Preset("PETG",235,70,null)));assertTrue(set.values.get(2).same(new PreheatPresets.Preset("ABS",250,90,null)));}
    @Test public void intentionallyEmptyPresetListIsNotReplacedByDefaults() throws Exception {assertTrue(PreheatPresets.read(settings(new JSONArray())).values.isEmpty());}
    @Test public void customPresetsKeepOptionalChamberAndRoundtrip() throws Exception {PreheatPresets source=new PreheatPresets(Arrays.asList(new PreheatPresets.Preset("Custom",245,75,45),new PreheatPresets.Preset("Other",210,50,null)));assertTrue(source.same(PreheatPresets.read(settings(source.json()))));assertEquals(Integer.valueOf(45),source.find("Custom").chamber);assertNull(source.find("Other").chamber);}
    @Test public void malformedFarmDataDoesNotPretendDefaultSuccess() throws Exception {for(JSONObject response:new JSONObject[]{new JSONObject(),new JSONObject().put("ok",false).put("settings",new JSONObject()),settings(JSONObject.NULL),settings(new JSONArray().put(new JSONObject().put("name","Bad").put("n",true).put("b",60))),settings(new JSONArray().put(new JSONObject().put("name","Bad").put("n",220.5).put("b",60)))})try{PreheatPresets.read(response);fail();}catch(JSONException|IllegalArgumentException expected){}}
    @Test public void presetLimitsRejectDuplicatesControlCharsAndOversizedList(){for(String name:new String[]{"", "abcdefghijklmn","bad\u0000name"})try{new PreheatPresets.Preset(name,220,60,null);fail();}catch(IllegalArgumentException expected){}try{new PreheatPresets(Arrays.asList(new PreheatPresets.Preset("PLA",220,60,null),new PreheatPresets.Preset("pla",220,60,null)));fail();}catch(IllegalArgumentException expected){}List<PreheatPresets.Preset> many=new ArrayList<>();for(int i=0;i<25;i++)many.add(new PreheatPresets.Preset("P"+i,200,60,null));try{new PreheatPresets(many);fail();}catch(IllegalArgumentException expected){}}
}
