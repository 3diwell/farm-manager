// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;

import org.json.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class UnifiedReceiptTest {
    private InventoryRepository repo() throws Exception {
        InventoryRepository r=new InventoryRepository(null);r.server="farm1";
        r.data=new JSONObject("{\"mobile\":{\"features\":[\"prepared_labels_v3\"],\"prepared_batches\":[{\"id\":\"batch1\"},{\"id\":\"batch2\"}],\"prepared_labels\":[{\"id\":\"one\",\"batch_id\":\"batch1\",\"status\":\"prepared\"},{\"id\":\"two\",\"batch_id\":\"batch2\",\"status\":\"prepared\"},{\"id\":\"old\",\"batch_id\":\"batch1\",\"status\":\"received\"},{\"id\":\"cancelled\",\"batch_id\":\"batch1\",\"status\":\"cancelled\"}]},\"spools\":[{\"id\":\"ordinary\"}]}");
        r.places=new JSONObject("{\"locations\":[{\"id\":\"shelf1\"},{\"id\":\"shelf2\"}]}");return r;
    }
    @Test public void preparedQrSelectsItsOwnBatchAndShelf() throws Exception {
        InventoryRepository r=repo();JSONObject body=r.automaticClaimRequest("fm1:spool:farm1:one","shelf2");
        assertEquals("batch1",body.getString("batch_id"));assertEquals("shelf2",body.getString("location"));assertEquals(3,body.getJSONObject("mobile").getInt("protocol"));
    }
    @Test public void consecutiveDifferentBatchesNeedNoModeChange() throws Exception {
        InventoryRepository r=repo();assertEquals("batch1",r.automaticClaimRequest("fm1:spool:farm1:one","shelf1").getString("batch_id"));
        assertEquals("batch2",r.automaticClaimRequest("fm1:spool:farm1:two","shelf1").getString("batch_id"));
    }
    @Test public void oldQrIsNotReencodedOrChanged() throws Exception {
        InventoryRepository r=repo();String qr="fm1:spool:farm1:one",before=r.data.toString();
        assertEquals(qr,r.automaticClaimRequest(qr,"shelf1").getJSONObject("mobile").getString("code"));assertEquals(before,r.data.toString());
    }
    @Test public void factoryBarcodeAndTextStillGoToFields() throws Exception {
        for(String raw:new String[]{"6937285510440","SKU petg-orange","https://example.test/filament/123"})assertEquals("factory",repo().receiptTarget(raw).kind());
    }
    @Test public void ordinaryExistingQrDoesNotCreateStock() throws Exception {assertEquals("existing",repo().receiptTarget("fm1:spool:farm1:ordinary").kind());}
    @Test public void alreadyReceivedTicketCanOnlyUseIdempotentClaim() throws Exception {
        assertEquals("claim_label",repo().automaticClaimRequest("fm1:spool:farm1:old","shelf1").getJSONObject("mobile").getString("operation"));
    }
    @Test(expected=IllegalArgumentException.class) public void cancelledBlocked() throws Exception {repo().automaticClaimRequest("fm1:spool:farm1:cancelled","shelf1");}
    @Test(expected=IllegalArgumentException.class) public void foreignFarmBlocked() throws Exception {repo().receiptTarget("fm1:spool:foreign:one");}
    @Test(expected=IllegalArgumentException.class) public void slotQrBlocked() throws Exception {repo().receiptTarget("fm1:slot:farm1:printer:0");}
    @Test(expected=IllegalArgumentException.class) public void unknownInternalQrNeverBecomesFactoryCode() throws Exception {repo().receiptTarget("fm1:spool:farm1:missing");}
    @Test(expected=IllegalArgumentException.class) public void invalidShelfBlocked() throws Exception {repo().automaticClaimRequest("fm1:spool:farm1:one","missing");}
    @Test(expected=IllegalArgumentException.class) public void olderModuleDoesNotFallBackToOrdinaryReceipt() throws Exception {
        InventoryRepository r=repo();r.data.getJSONObject("mobile").put("features",new JSONArray());r.automaticClaimRequest("fm1:spool:farm1:one","shelf1");
    }
    @Test(expected=IllegalArgumentException.class) public void ordinaryQrCannotBuildClaimRequest() throws Exception {repo().automaticClaimRequest("fm1:spool:farm1:ordinary","shelf1");}
    @Test(expected=IllegalArgumentException.class) public void missingBatchBlocked() throws Exception {
        InventoryRepository r=repo();r.data.getJSONObject("mobile").put("prepared_batches",new JSONArray());r.receiptTarget("fm1:spool:farm1:one");
    }
}
