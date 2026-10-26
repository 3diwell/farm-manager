// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;

import org.json.*;
import org.junit.*;
import ru.threediwell.fm.i18n.I18n;
import static org.junit.Assert.*;

/** «Списать как пустую» с остатком выше 50 г или 5 % номинала — отдельное подтверждение «Списать N г». */
public class HeavyWriteOffTest {
    @After public void reset(){I18n.setLanguage("ru");}
    private InventoryRepository repo(Object remaining,Object total) throws Exception {
        InventoryRepository r=new InventoryRepository(null);r.server="farm-1";
        r.data=new JSONObject().put("mobile",new JSONObject().put("features",new JSONArray().put("empty_spool_writeoff_v6")))
                .put("spools",new JSONArray().put(new JSONObject().put("id","spool_1").put("filament_id","fil_1").put("ams_printer_id","").put("ams_slot",-1).put("weight_remaining_g",remaining).put("weight_total_g",total)));
        r.ams=new JSONObject().put("printers",new JSONArray());return r;
    }
    @Test public void belowBothThresholdsKeepsTheSingleConfirmation(){
        assertFalse(InventoryRepository.heavyWriteOff(0,1000));assertFalse(InventoryRepository.heavyWriteOff(42.5,1000));
        assertFalse(InventoryRepository.heavyWriteOff(50,1000));assertFalse(InventoryRepository.heavyWriteOff(12,250));
        assertFalse(InventoryRepository.heavyWriteOff(Double.NaN,1000));assertFalse(InventoryRepository.heavyWriteOff(-3,1000));
    }
    @Test public void aboveFiftyGramsAsksEvenForBigSpools(){
        assertTrue(InventoryRepository.heavyWriteOff(50.1,1000));assertTrue(InventoryRepository.heavyWriteOff(60,3000));
        assertTrue(InventoryRepository.heavyWriteOff(980,1000));assertTrue(InventoryRepository.heavyWriteOff(60,Double.NaN));assertTrue(InventoryRepository.heavyWriteOff(60,0));
    }
    @Test public void aboveFivePercentOfNominalAsksForSmallSpools(){
        assertTrue(InventoryRepository.heavyWriteOff(13,250));assertFalse(InventoryRepository.heavyWriteOff(12.5,250));
        assertFalse(InventoryRepository.heavyWriteOff(30,Double.NaN));assertFalse(InventoryRepository.heavyWriteOff(30,0));
    }
    @Test public void questionNamesTheGramsThatWillBeWrittenOff() throws Exception {
        assertEquals("На катушке ещё 120 г. Списать 120 г?",InventoryRepository.heavyWriteOffQuestion(120));
        assertEquals("Списать 120 г",InventoryRepository.heavyWriteOffButton(120));
        assertEquals("На катушке ещё 50,4 г. Списать 50,4 г?",InventoryRepository.heavyWriteOffQuestion(50.4));
        I18n.setLanguage("en");assertEquals("The spool still holds 50.4 g. Write off 50.4 g?",InventoryRepository.heavyWriteOffQuestion(50.4));
        assertEquals("Write off 120 g",InventoryRepository.heavyWriteOffButton(120));
    }
    @Test public void requestBasedQuestionUsesTheWeightThatGoesToFm() throws Exception {
        InventoryRepository full=repo(640,1000);JSONObject request=full.writeOffRequest("spool_1");
        assertEquals("На катушке ещё 640 г. Списать 640 г?",full.heavyWriteOffQuestion(request));
        InventoryRepository empty=repo(42.5,1000);assertEquals("",empty.heavyWriteOffQuestion(empty.writeOffRequest("spool_1")));
        InventoryRepository small=repo(20,250);assertEquals("На катушке ещё 20 г. Списать 20 г?",small.heavyWriteOffQuestion(small.writeOffRequest("spool_1")));
        InventoryRepository unknownNominal=repo(20,JSONObject.NULL);assertEquals("",unknownNominal.heavyWriteOffQuestion(unknownNominal.writeOffRequest("spool_1")));
    }
    @Test public void questionDoesNotChangeTheRequestOrStock() throws Exception {
        InventoryRepository r=repo(640,1000);JSONObject request=r.writeOffRequest("spool_1");String before=request.toString(),stock=r.data.toString();
        r.heavyWriteOffQuestion(request);assertEquals(before,request.toString());assertEquals(stock,r.data.toString());
        assertEquals(640,request.getDouble("expected_weight_remaining_g"),0);assertTrue(request.getBoolean("confirm_empty"));
    }
}
