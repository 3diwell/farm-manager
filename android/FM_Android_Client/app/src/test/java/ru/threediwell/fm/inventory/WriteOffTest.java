// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;
import org.json.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class WriteOffTest {
    private InventoryRepository repo() throws Exception {
        InventoryRepository r=new InventoryRepository(null);r.server="farm-1";
        r.data=new JSONObject("{\"mobile\":{\"features\":[\"empty_spool_writeoff_v6\"],\"codes\":[{\"code\":\"EAN\",\"kind\":\"product\",\"filament_id\":\"fil_1\"},{\"code\":\"unique-1\",\"kind\":\"unique\",\"spool_id\":\"spool_1\"}]},\"spools\":[{\"id\":\"spool_1\",\"filament_id\":\"fil_1\",\"ams_printer_id\":\"\",\"ams_slot\":-1,\"weight_remaining_g\":42.5}]}");
        r.ams=new JSONObject("{\"printers\":[{\"printer_id\":\"p1\",\"slots\":[{\"index\":-1,\"spool\":{\"id\":\"spool_1\"}}]}]}");return r;
    }
    @Test public void exactQrAndUniqueAliasChooseOnlyThatSpool() throws Exception {
        InventoryRepository r=repo();assertEquals("spool_1",r.writeOffSpool("fm1:spool:farm-1:spool_1").getString("id"));
        assertEquals("spool_1",r.writeOffSpool("unique-1").getString("id"));
    }
    @Test(expected=IllegalArgumentException.class) public void sharedBarcodeRejectedEvenWithOneSpool() throws Exception {repo().writeOffSpool("EAN");}
    @Test(expected=IllegalArgumentException.class) public void qrFromOtherFarmRejected() throws Exception {repo().writeOffSpool("fm1:spool:farm-2:spool_1");}
    @Test(expected=IllegalArgumentException.class) public void slotQrCannotDiscardSpool() throws Exception {repo().writeOffSpool("fm1:slot:farm-1:p1:0");}
    @Test(expected=IllegalArgumentException.class) public void unknownQrRejected() throws Exception {repo().writeOffSpool("fm1:spool:farm-1:missing");}
    @Test public void requestCapturesDisplayedWeightAndBindingWithoutChangingStock() throws Exception {
        InventoryRepository r=repo();String old=r.data.toString();JSONObject d=r.writeOffRequest("spool_1");
        assertEquals(6,d.getJSONObject("mobile").getInt("protocol"));assertEquals("writeoff",d.getJSONObject("mobile").getString("operation"));
        assertTrue(d.getBoolean("confirm_empty"));assertEquals(42.5,d.getDouble("expected_weight_remaining_g"),0);
        assertEquals("",d.getString("expected_printer_id"));assertEquals(-1,d.getInt("expected_ams_slot"));
        assertEquals(old,r.data.toString());assertNotEquals(d.getJSONObject("mobile").getString("request_id"),r.writeOffRequest("spool_1").getJSONObject("mobile").getString("request_id"));
    }
    @Test public void installedExternalUsesItsExactPosition() throws Exception {
        InventoryRepository r=repo();r.spool("spool_1").put("ams_printer_id","p1");
        JSONObject d=r.writeOffRequest("spool_1");assertEquals("p1",d.getString("expected_printer_id"));assertEquals(-1,d.getInt("expected_ams_slot"));
    }
    @Test(expected=IllegalArgumentException.class) public void unavailableFeatureRejected() throws Exception {InventoryRepository r=repo();r.data.getJSONObject("mobile").remove("features");r.writeOffRequest("spool_1");}
    @Test(expected=IllegalArgumentException.class) public void deletedSpoolRejected() throws Exception {InventoryRepository r=repo();r.spool("spool_1").put("is_deleted",1);r.writeOffRequest("spool_1");}
    @Test(expected=IllegalArgumentException.class) public void pendingPrintRejected() throws Exception {InventoryRepository r=repo();r.spool("spool_1").put("pending",true);r.writeOffRequest("spool_1");}
    @Test(expected=IllegalArgumentException.class) public void unknownWeightRejected() throws Exception {InventoryRepository r=repo();r.spool("spool_1").remove("weight_remaining_g");r.writeOffRequest("spool_1");}
    @Test(expected=IllegalArgumentException.class) public void stalePositionRejected() throws Exception {
        InventoryRepository r=repo();r.spool("spool_1").put("ams_printer_id","p1");r.ams.getJSONArray("printers").getJSONObject(0).getJSONArray("slots").getJSONObject(0).put("offline",true);r.writeOffRequest("spool_1");
    }
    @Test public void zeroRemainderCanBeDiscarded() throws Exception {InventoryRepository r=repo();r.spool("spool_1").put("weight_remaining_g",0);assertEquals(0,r.writeOffRequest("spool_1").getDouble("expected_weight_remaining_g"),0);}
}
