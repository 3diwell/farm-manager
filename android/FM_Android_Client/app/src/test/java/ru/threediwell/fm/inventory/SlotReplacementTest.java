// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;
import org.json.*;
import org.junit.Test;
import static org.junit.Assert.*;
import ru.threediwell.fm.ui.OperationFlow;

public class SlotReplacementTest {
    private final Labels.Label target=new Labels.Label("slot","farm-1","p1",-1);
    private InventoryRepository repo() throws Exception {
        InventoryRepository r=new InventoryRepository(null);r.server="farm-1";
        r.data=new JSONObject("{\"mobile\":{\"features\":[\"slot_exchange_v2\",\"empty_spool_writeoff_v6\",\"slot_replace_writeoff_v7\"]},\"spools\":[{\"id\":\"old\",\"filament_id\":\"fil_1\",\"ams_printer_id\":\"p1\",\"ams_slot\":-1,\"weight_remaining_g\":42.5},{\"id\":\"new\",\"filament_id\":\"fil_2\",\"ams_printer_id\":\"\",\"ams_slot\":-1,\"weight_remaining_g\":900}]}");
        r.ams=new JSONObject("{\"printers\":[{\"printer_id\":\"p1\",\"slots\":[{\"index\":-1,\"spool\":{\"id\":\"old\"}},{\"index\":0}]}]}");return r;
    }
    @Test public void choosingEitherActionDoesNotChangeInventoryBeforeConfirmation() throws Exception {
        InventoryRepository r=repo();String data=r.data.toString(),ams=r.ams.toString();
        assertFalse(r.selectSlot(target,"old",false).discard());assertTrue(r.selectSlot(target,"old",true).discard());
        assertEquals(data,r.data.toString());assertEquals(ams,r.ams.toString());
    }
    @Test public void returnUsesExistingReplacementAndPreservesSnapshotIdentity() throws Exception {
        InventoryRepository r=repo();var c=r.selectSlot(target,"old",false);
        JSONObject d=r.slotRequest(c.target(),"replace",c.expectedSpoolId());
        assertEquals(2,d.getJSONObject("mobile").getInt("protocol"));assertEquals("replace",d.getJSONObject("mobile").getString("operation"));
        assertEquals("old",d.getString("expected_spool_id"));assertFalse(d.has("confirm_empty"));
    }
    @Test public void replacementRequestCapturesBothSpoolsAndExactExternalSlot() throws Exception {
        InventoryRepository r=repo();var c=r.selectSlot(target,"old",true);JSONObject d=r.replaceWriteOffRequest(c,"new");
        assertEquals(7,d.getJSONObject("mobile").getInt("protocol"));assertEquals("replace_writeoff",d.getJSONObject("mobile").getString("operation"));
        assertEquals("old",d.getString("spool_id"));assertEquals("new",d.getString("new_spool_id"));assertEquals("p1",d.getString("expected_printer_id"));
        assertEquals(-1,d.getInt("expected_ams_slot"));assertEquals(42.5,d.getDouble("expected_weight_remaining_g"),0);
        assertEquals("fil_2",d.getString("expected_new_filament_id"));assertEquals(900,d.getDouble("expected_new_weight_remaining_g"),0);
        assertEquals(OperationFlow.INSTALL,OperationFlow.fromRequest("/api/mod/inventory/spools/bulk-delete",d));
    }
    @Test public void scannerContextIsImmutableAndRequestSerializationKeepsOperationId() throws Exception {
        InventoryRepository r=repo();var c=r.selectSlot(target,"old",true);String snapshot=c.writeOffSnapshot();
        JSONObject d=r.replaceWriteOffRequest(c,"new"),retry=new JSONObject(d.toString());
        assertEquals(d.getJSONObject("mobile").getString("request_id"),retry.getJSONObject("mobile").getString("request_id"));
        d.put("spool_id","changed");assertEquals(snapshot,c.writeOffSnapshot());assertEquals("old",r.replaceWriteOffRequest(c,"new").getString("spool_id"));
    }
    @Test public void oldModuleAllowsReturnAndInstallationButNotDiscardReplacement() throws Exception {
        InventoryRepository r=repo();r.data.getJSONObject("mobile").put("features",new JSONArray("[\"slot_exchange_v2\",\"empty_spool_writeoff_v6\"]"));
        assertTrue(r.supportsWriteOff());assertFalse(r.supportsReplaceWriteOff());assertFalse(r.selectSlot(target,"old",false).discard());
        assertEquals("",r.selectSlot(new Labels.Label("slot","farm-1","p1",0),"",false).expectedSpoolId());
        assertThrows(IllegalArgumentException.class,()->r.selectSlot(target,"old",true));
    }
    @Test public void refreshCannotSilentlyReplaceAnotherOccupant() throws Exception {
        InventoryRepository r=repo();var c=r.selectSlot(target,"old",false);
        r.position(target).put("spool",new JSONObject().put("id","other"));
        assertThrows(IllegalArgumentException.class,()->r.validateSelection(c));assertThrows(IllegalArgumentException.class,()->r.selectSlot(target,"old",true));
    }
    @Test public void freeSlotBecomingOccupiedRequiresNewSelection() throws Exception {
        InventoryRepository r=repo();Labels.Label free=new Labels.Label("slot","farm-1","p1",0);var c=r.selectSlot(free,"",false);
        r.position(free).put("spool",new JSONObject().put("id","other"));assertThrows(IllegalArgumentException.class,()->r.validateSelection(c));
    }
    @Test public void oldWeightChangeAfterChoiceRequiresNewChoice() throws Exception {
        InventoryRepository r=repo();var c=r.selectSlot(target,"old",true);r.spool("old").put("weight_remaining_g",30);
        assertThrows(IllegalArgumentException.class,()->r.replaceWriteOffRequest(c,"new"));
    }
    @Test public void oldMaterialOrBindingChangeRequiresNewChoice() throws Exception {
        InventoryRepository r=repo();var c=r.selectSlot(target,"old",true);r.spool("old").put("filament_id","other");
        assertThrows(IllegalArgumentException.class,()->r.validateSelection(c));r.spool("old").put("filament_id","fil_1").put("ams_slot",0);
        assertThrows(IllegalArgumentException.class,()->r.validateSelection(c));
    }
    @Test public void featureRemovalBeforeConfirmationIsRejected() throws Exception {
        InventoryRepository r=repo();var c=r.selectSlot(target,"old",true);r.data.getJSONObject("mobile").remove("features");
        assertThrows(IllegalArgumentException.class,()->r.replaceWriteOffRequest(c,"new"));
    }
    @Test public void anotherServerCannotUseOldSelection() throws Exception {
        InventoryRepository r=repo();var c=r.selectSlot(target,"old",true);r.server="farm-2";
        assertThrows(IllegalArgumentException.class,()->r.replaceWriteOffRequest(c,"new"));
    }
    @Test public void sameSpoolOrSpoolInstalledElsewhereIsRejected() throws Exception {
        InventoryRepository r=repo();var c=r.selectSlot(target,"old",true);
        assertThrows(IllegalArgumentException.class,()->r.replaceWriteOffRequest(c,"old"));r.spool("new").put("ams_printer_id","p2");
        assertThrows(IllegalArgumentException.class,()->r.replaceWriteOffRequest(c,"new"));
    }
    @Test public void deletedMissingPendingOrEmptyNewSpoolIsRejected() throws Exception {
        InventoryRepository r=repo();var c=r.selectSlot(target,"old",true);
        assertThrows(IllegalArgumentException.class,()->r.replaceWriteOffRequest(c,"missing"));
        r.spool("new").put("is_deleted",1);assertThrows(IllegalArgumentException.class,()->r.replaceWriteOffRequest(c,"new"));
        r.spool("new").put("is_deleted",0).put("pending",true);assertThrows(IllegalArgumentException.class,()->r.replaceWriteOffRequest(c,"new"));
        r.spool("new").put("pending",false).put("weight_remaining_g",0);assertThrows(IllegalArgumentException.class,()->r.replaceWriteOffRequest(c,"new"));
    }
    @Test public void discardCannotBeChosenForEmptySlot() throws Exception {
        InventoryRepository r=repo();assertThrows(IllegalArgumentException.class,()->r.selectSlot(new Labels.Label("slot","farm-1","p1",0),"",true));
    }
    @Test public void ambiguousDuplicateOccupantCannotDiscardDifferentPosition() throws Exception {
        InventoryRepository r=repo();Labels.Label other=new Labels.Label("slot","farm-1","p1",0);r.position(other).put("spool",new JSONObject().put("id","old"));
        assertThrows(IllegalArgumentException.class,()->r.selectSlot(other,"old",true));
    }
}
