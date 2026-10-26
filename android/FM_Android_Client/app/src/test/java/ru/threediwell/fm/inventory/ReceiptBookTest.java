// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;
import org.json.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class ReceiptBookTest {
    private JSONObject body(String server) throws Exception {return new JSONObject().put("mobile",new JSONObject().put("server_id",server)).put("location","shelf-1").put("weight_total_g",1000);}
    private JSONObject result(String id) throws Exception {return new JSONObject().put("ok",true).put("id",id);}
    @Test public void successfulReceiptSurvivesReload() throws Exception {
        ReceiptBook b=new ReceiptBook("{}");b.record("farm","batch","Today",result("s1"),body("farm"),"PETG Серый");
        b=new ReceiptBook(b.toString());assertEquals("s1",b.active("farm").getJSONArray("entries").getJSONObject(0).getString("id"));
        assertEquals("PETG Серый",b.active("farm").getJSONArray("entries").getJSONObject(0).getString("caption"));
    }
    @Test public void replayDoesNotDuplicateLabel() throws Exception {
        ReceiptBook b=new ReceiptBook("{}");b.record("farm","b1","Today",result("s1"),body("farm"),"a");
        b.record("farm","b1","Today",result("s1").put("replayed",true),body("farm"),"a");
        assertEquals(1,b.active("farm").getJSONArray("entries").length());
    }
    @Test public void laterBatchDoesNotCaptureOldRetry() throws Exception {
        ReceiptBook b=new ReceiptBook("{}");b.record("farm","b1","One",result("s1"),body("farm"),"a");b.start("farm","b2","Two");
        b.record("farm","b2","Two",result("s1"),body("farm"),"a");
        assertEquals(0,b.active("farm").getJSONArray("entries").length());assertEquals(2,b.list("farm").size());
    }
    @Test public void differentSpoolsWithSameCaptionRemainDistinct() throws Exception {
        ReceiptBook b=new ReceiptBook("{}");for(int i=0;i<20;i++)b.record("farm","b1","One",result("s"+i),body("farm"),"PLA");
        assertEquals(20,b.active("farm").getJSONArray("entries").length());
    }
    @Test public void newBatchPreservesOldAndOtherFarm() throws Exception {
        ReceiptBook b=new ReceiptBook("{}");b.start("farm","b1","One");b.start("other","b1","Other");b.start("farm","b2","Two");
        assertFalse(b.get("farm","b1").getBoolean("active"));assertEquals("b2",b.active("farm").getString("id"));assertEquals("b1",b.active("other").getString("id"));
    }
    @Test(expected=IllegalArgumentException.class) public void failedReceiptIsNotAnEntry() throws Exception {
        new ReceiptBook("{}").record("farm","b","One",new JSONObject().put("ok",false),body("farm"),"a");
    }
    @Test(expected=IllegalArgumentException.class) public void wrongFarmRejected() throws Exception {
        new ReceiptBook("{}").record("farm","b","One",result("s1"),body("other"),"a");
    }
    @Test(expected=JSONException.class) public void corruptedBookNotSilentlyReset() throws Exception {new ReceiptBook("not-json");}
    @Test(expected=JSONException.class) public void malformedBatchesNotSilentlyReset() throws Exception {new ReceiptBook("{\"batches\":\"invalid\"}").active("farm");}
}
