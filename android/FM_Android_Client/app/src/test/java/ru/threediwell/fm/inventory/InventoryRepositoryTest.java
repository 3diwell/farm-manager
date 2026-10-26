// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;
import org.json.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class InventoryRepositoryTest {
    @Test public void productCodeReturnsAllCandidatesNotFirst() throws Exception {
        InventoryRepository repo=new InventoryRepository(null);repo.server="farm-1";
        repo.data=new JSONObject("{\"mobile\":{\"codes\":[{\"code\":\"EAN\",\"kind\":\"product\",\"filament_id\":\"fil_1\"}]},\"spools\":[{\"id\":\"spool_1\",\"filament_id\":\"fil_1\"},{\"id\":\"spool_2\",\"filament_id\":\"fil_1\"}]}");
        assertEquals(2,repo.findSpools("EAN").size());
        assertEquals("spool_2",repo.findSpools("fm1:spool:farm-1:spool_2").get(0).getString("id"));
        assertTrue(repo.findSpools("unknown").isEmpty());
    }
    @Test(expected=IllegalArgumentException.class) public void slotIsNotSpool() {
        InventoryRepository repo=new InventoryRepository(null); repo.server="farm-1";
        repo.findSpools("fm1:slot:farm-1:printer_1:0");
    }
    private InventoryRepository exchangeRepo() throws Exception {
        InventoryRepository repo=new InventoryRepository(null);repo.server="farm-1";
        repo.data=new JSONObject("{\"mobile\":{\"protocol\":1,\"features\":[\"slot_exchange_v2\"]}}");
        repo.ams=new JSONObject("{\"printers\":[{\"printer_id\":\"printer_1\",\"slots\":[{\"index\":-1},{\"index\":0,\"spool\":{\"id\":\"spool_old\"}},{\"index\":1,\"unconfirmed\":true}]}]}");
        return repo;
    }
    @Test public void replacementRequestCarriesExactConfirmedOccupant() throws Exception {
        InventoryRepository repo=exchangeRepo();
        JSONObject d=repo.slotRequest(new Labels.Label("slot","farm-1","printer_1",0),"replace","spool_old");
        assertEquals(2,d.getJSONObject("mobile").getInt("protocol"));
        assertEquals("replace",d.getJSONObject("mobile").getString("operation"));
        assertEquals("spool_old",d.getString("expected_spool_id"));
        assertEquals(0,d.getInt("ams_slot"));assertFalse(d.getBoolean("external"));
    }
    @Test public void unbindExternalKeepsMinusOne() throws Exception {
        JSONObject d=exchangeRepo().slotRequest(new Labels.Label("slot","farm-1","printer_1",-1),"unbind","spool_old");
        assertEquals(-1,d.getInt("ams_slot"));assertTrue(d.getBoolean("external"));
        assertEquals("unbind",d.getJSONObject("mobile").getString("operation"));
    }
    @Test public void freeSlotExplicitExpectationAndUniqueRequestIds() throws Exception {
        InventoryRepository repo=exchangeRepo();Labels.Label target=new Labels.Label("slot","farm-1","printer_1",-1);
        JSONObject a=repo.slotRequest(target,"bind","");JSONObject b=repo.slotRequest(target,"bind","");
        assertTrue(a.has("expected_spool_id"));assertEquals("",a.getString("expected_spool_id"));
        assertNotEquals(a.getJSONObject("mobile").getString("request_id"),b.getJSONObject("mobile").getString("request_id"));
    }
    @Test(expected=IllegalArgumentException.class) public void noUnbindOnOldModule() throws Exception {
        InventoryRepository repo=exchangeRepo();repo.data=new JSONObject("{\"mobile\":{\"protocol\":1}}");
        repo.slotRequest(new Labels.Label("slot","farm-1","printer_1",0),"unbind","spool_old");
    }
    @Test(expected=IllegalArgumentException.class) public void unconfirmedSlotCannotBeUsed() throws Exception {
        exchangeRepo().slotRequest(new Labels.Label("slot","farm-1","printer_1",1),"unbind","spool_old");
    }
    @Test(expected=IllegalArgumentException.class) public void otherFarmCannotBuildRequest() throws Exception {
        exchangeRepo().slotRequest(new Labels.Label("slot","farm-2","printer_1",0),"replace","spool_old");
    }
    @Test public void scanPreviewIsReadOnly() throws Exception {
        InventoryRepository repo=exchangeRepo();String before=repo.ams.toString();
        assertEquals("spool_old",repo.position(new Labels.Label("slot","farm-1","printer_1",0)).getJSONObject("spool").getString("id"));
        assertEquals(before,repo.ams.toString());
    }
}
