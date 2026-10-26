// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import org.junit.*;
import java.util.*;
import ru.threediwell.fm.i18n.I18n;
import static org.junit.Assert.*;

/** Подписи слотов как в FM (web/app.js amsGroups, server.py _qw_ams_label): блок AMS по unit, AMS HT — свой блок. */
public class SlotNamingTest {
    @After public void reset(){I18n.setLanguage("ru");}
    private static JSONObject tray(int unit,int tray)throws Exception{return new JSONObject().put("index",unit*4+tray).put("unit",unit).put("tray",tray).put("type","PLA");}
    @Test public void regularUnitsAreNumberedFromOne(){for(int unit=0;unit<4;unit++)assertEquals("AMS "+(unit+1),MaterialSlots.unitName("ams",unit));}
    @Test public void everyAmsHtUnitIdIsItsOwnUnitNeverAPositionNumber(){
        assertEquals("AMS HT",MaterialSlots.unitName("ams",128));
        for(int unit=129;unit<=135;unit++)assertEquals("AMS HT "+(unit-127),MaterialSlots.unitName("ams",unit));
        for(int unit=128;unit<=135;unit++){String name=MaterialSlots.unitName("ams",unit);assertTrue(name.startsWith("AMS HT"));assertFalse(name.matches(".*\\b(129|1[3-9]\\d|5\\d\\d)\\b.*"));}
    }
    @Test public void cfsKeepsItsOwnName(){assertEquals("CFS 2",MaterialSlots.unitName("cfs",1));}
    @Test public void secondAmsFirstTrayIsAms2Dot1NotAms5()throws Exception{assertEquals("AMS 2 · 1",MaterialSlots.positionName(tray(1,0)));assertEquals("AMS 4 · 4",MaterialSlots.positionName(tray(3,3)));}
    @Test public void amsHtTrayIsNotSlot513()throws Exception{
        for(int unit=128;unit<=135;unit++){String name=MaterialSlots.positionName(tray(unit,0));assertEquals(MaterialSlots.unitName("ams",unit)+" · 1",name);assertFalse(name.contains(String.valueOf(unit*4+1)));}
        assertEquals("AMS HT · 1",MaterialSlots.positionName(tray(128,0)));
    }
    @Test public void offlineBindingWithoutUnitIsDerivedLikeFm()throws Exception{
        assertEquals("AMS 2 · 2",MaterialSlots.positionName(new JSONObject().put("index",5).put("unit",JSONObject.NULL).put("tray",JSONObject.NULL).put("offline",true)));
        assertEquals("AMS HT · 1",MaterialSlots.positionName(new JSONObject().put("index",512).put("offline",true)));
        assertEquals("AMS HT 2 · 1",MaterialSlots.positionName(new JSONObject().put("index",516)));
    }
    @Test public void externalAndCfsPositions()throws Exception{
        assertEquals("Внешняя катушка",MaterialSlots.positionName(new JSONObject().put("index",-1).put("external",true)));
        assertEquals("Внешняя катушка справа",MaterialSlots.positionName(new JSONObject().put("index",-1).put("external",true).put("ext_side","right")));
        assertEquals("Внешняя катушка слева",MaterialSlots.positionName(new JSONObject().put("index",-2).put("external",true).put("ext_side","left")));
        assertEquals("T1B",MaterialSlots.positionName(new JSONObject().put("index",1).put("unit",0).put("tray",1).put("label","T1B").put("feed","cfs")));
        assertEquals("CFS 2 · 2",MaterialSlots.positionName(new JSONObject().put("index",5).put("unit",1).put("tray",1).put("feed","cfs")));
        assertEquals("Позиция не подтверждена",MaterialSlots.positionName(new JSONObject().put("index",0).put("unconfirmed",true)));
        I18n.setLanguage("en");assertEquals("Right external spool",MaterialSlots.positionName(new JSONObject().put("index",-1).put("external",true).put("ext_side","right")));
        assertEquals("Position unconfirmed",MaterialSlots.positionName(new JSONObject().put("index",0).put("unconfirmed",true)));
    }
    @Test public void printerCardGroupsMatchFm()throws Exception{
        JSONArray trays=new JSONArray();for(int unit:new int[]{0,1})for(int t=0;t<4;t++)trays.put(tray(unit,t));trays.put(tray(128,0));
        JSONObject state=new JSONObject().put("status","IDLE").put("seen_ago",0).put("ams_trays",trays);
        List<MaterialSlots.Slot> slots=MaterialSlots.of(new JSONObject().put("id","p").put("type","bambu"),state,0,null);
        Set<String> groups=new LinkedHashSet<>();for(MaterialSlots.Slot s:slots)groups.add(s.group());
        assertTrue(groups.containsAll(List.of("AMS 1","AMS 2","AMS HT")));
        assertEquals("AMS 2 · 1",slots.get(4).position());assertEquals("AMS HT · 1",slots.get(8).position());
        for(MaterialSlots.Slot s:slots){assertFalse(s.position(),s.position().matches(".*AMS (5|9|129|513).*"));assertFalse(s.group(),s.group().matches("AMS (5|129|513)"));}
    }
    @Test public void offlineInventoryBindingUsesFmNameInsteadOfPositionNumber()throws Exception{
        JSONObject stock=new JSONObject().put("slots",new JSONArray().put(new JSONObject().put("index",512).put("unit",JSONObject.NULL).put("tray",JSONObject.NULL).put("offline",true).put("spool",new JSONObject().put("material","PLA").put("weight_remaining_g",300).put("weight_total_g",1000))));
        List<MaterialSlots.Slot> slots=MaterialSlots.of(new JSONObject().put("id","p").put("type","flashforge"),new JSONObject().put("status","IDLE").put("seen_ago",0),0,stock);
        assertEquals("AMS HT · 1",slots.get(0).position());
    }
}
