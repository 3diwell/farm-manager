// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;
import org.json.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class PreparedLabelsTest {
    private InventoryRepository repo() throws Exception {
        InventoryRepository r=new InventoryRepository(null);r.server="farm-1";
        r.data=new JSONObject("{\"mobile\":{\"protocol\":1,\"features\":[\"prepared_labels_v3\"],\"prepared_batches\":[{\"id\":\"batch1\"},{\"id\":\"batch2\"}],\"prepared_labels\":[{\"id\":\"spool1\",\"batch_id\":\"batch1\",\"status\":\"prepared\"},{\"id\":\"spool2\",\"batch_id\":\"batch2\",\"status\":\"prepared\"}]}}");
        r.places=new JSONObject("{\"locations\":[{\"id\":\"shelf1\"}]}");return r;
    }
    @Test public void prepareEnvelopeUsesV3WithFreshRequestIds() throws Exception {
        InventoryRepository r=repo();JSONObject a=r.preparedEnvelope("prepare_labels"),b=r.preparedEnvelope("prepare_labels");
        assertEquals(3,a.getInt("protocol"));assertEquals("farm-1",a.getString("server_id"));assertNotEquals(a.getString("request_id"),b.getString("request_id"));
    }
    @Test public void claimCarriesExactQrBatchAndChosenShelf() throws Exception {
        InventoryRepository r=repo();String before=r.data.toString();JSONObject d=r.claimRequest("fm1:spool:farm-1:spool1","batch1","shelf1");
        assertEquals("claim_label",d.getJSONObject("mobile").getString("operation"));assertEquals("fm1:spool:farm-1:spool1",d.getJSONObject("mobile").getString("code"));
        assertEquals("batch1",d.getString("batch_id"));assertEquals("shelf1",d.getString("location"));assertFalse(d.has("weight_total_g"));assertEquals(before,r.data.toString());
    }
    @Test(expected=IllegalArgumentException.class) public void wrongFarmBlocked() throws Exception {repo().claimRequest("fm1:spool:other:spool1","batch1","shelf1");}
    @Test(expected=IllegalArgumentException.class) public void wrongBatchBlocked() throws Exception {repo().claimRequest("fm1:spool:farm-1:spool2","batch1","shelf1");}
    @Test(expected=IllegalArgumentException.class) public void normalSpoolNotPreparedBlocked() throws Exception {repo().claimRequest("fm1:spool:farm-1:ordinary","batch1","shelf1");}
    @Test(expected=IllegalArgumentException.class) public void slotQrBlocked() throws Exception {repo().claimRequest("fm1:slot:farm-1:printer:0","batch1","shelf1");}
    @Test(expected=IllegalArgumentException.class) public void cancelledBlocked() throws Exception {
        InventoryRepository r=repo();r.preparedLabels("batch1").get(0).put("status","cancelled");r.claimRequest("fm1:spool:farm-1:spool1","batch1","shelf1");
    }
    @Test public void receivedCanAskServerForNoOpConfirmation() throws Exception {
        InventoryRepository r=repo();r.preparedLabels("batch1").get(0).put("status","received");assertNotNull(r.claimRequest("fm1:spool:farm-1:spool1","batch1","shelf1"));
    }
    @Test(expected=IllegalArgumentException.class) public void missingShelfBlocked() throws Exception {repo().claimRequest("fm1:spool:farm-1:spool1","batch1","missing");}
    @Test(expected=IllegalArgumentException.class) public void oldModuleBlocked() throws Exception {
        InventoryRepository r=repo();r.data.getJSONObject("mobile").put("features",new JSONArray());r.preparedEnvelope("prepare_labels");
    }
    @Test(expected=IllegalArgumentException.class) public void unknownOperationBlocked() throws Exception {repo().preparedEnvelope("erase");}
    @Test public void metadataSplitByBatch() throws Exception {InventoryRepository r=repo();assertEquals(2,r.preparedBatches().size());assertEquals(1,r.preparedLabels("batch1").size());}
}
