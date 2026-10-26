// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;

import org.json.*;
import org.junit.Test;
import ru.threediwell.fm.nfc.NfcReading;
import static org.junit.Assert.*;

public class NfcWorkflowTest {
    private InventoryRepository repo() throws Exception {
        InventoryRepository r=new InventoryRepository(null);r.server="farm1";
        r.data=new JSONObject("{\"mobile\":{\"features\":[\"nfc_spools_v4\"],\"nfc_tags\":[{\"uid\":\"AABBCCDD\",\"spool_id\":\"spool1\"}]},\"spools\":[{\"id\":\"spool1\",\"filament_id\":\"fil1\",\"weight_remaining_g\":123},{\"id\":\"spool2\",\"filament_id\":\"fil1\"}]}");
        return r;
    }
    private JSONObject scan() throws Exception {
        return new JSONObject("{\"uid\":\"aabbccdd\",\"material\":\"PLA\",\"variant\":\"PLA Matte\",\"rgba\":\"223344FF\",\"diameter\":2.85,\"weight\":750}");
    }
    @Test public void validatedReadingRetainsActualValues() throws Exception {
        NfcReading v=new NfcReading(scan());assertEquals("AABBCCDD",v.uid);assertEquals("PLA Matte",v.variant);
        assertEquals(750,v.weight);assertEquals(2.85,v.diameter,0.0001);assertEquals("223344FF",v.rgba);
        assertEquals("nfc:bambu:AABBCCDD",NfcReading.code(v.uid));
    }
    @Test(expected=IllegalArgumentException.class) public void invalidUidRejected() {NfcReading.uid("AA:BB:CC:DD");}
    @Test(expected=IllegalArgumentException.class) public void invalidColorRejected() throws Exception {new NfcReading(scan().put("rgba","Orange"));}
    @Test(expected=IllegalArgumentException.class) public void invalidDiameterRejected() throws Exception {new NfcReading(scan().put("diameter",9));}
    @Test(expected=IllegalArgumentException.class) public void invalidMassRejected() throws Exception {new NfcReading(scan().put("weight",0));}
    @Test public void qrAndNfcFindSameSpoolWithoutChangingBalance() throws Exception {
        InventoryRepository r=repo();String before=r.data.toString();
        assertEquals(r.findSpools("fm1:spool:farm1:spool1").get(0).getString("id"),r.nfcSpool("aabbccdd").getString("id"));
        assertEquals(before,r.data.toString());assertEquals(123,r.nfcSpool("AABBCCDD").getInt("weight_remaining_g"));
    }
    @Test public void unknownNfcDoesNotGuessBySameMaterial() throws Exception {assertNull(repo().nfcSpool("01020304"));}
    @Test public void legacyUidNormalizedWithoutChangingOrdinaryFind() throws Exception {
        InventoryRepository r=repo();r.spool("spool2").put("nfc_uid","01:02:03:04");
        assertEquals("spool2",r.nfcSpool("01020304").getString("id"));assertEquals("AABBCCDD",NfcReading.legacyUid("nfc:bambu:aabbccdd"));
    }
    @Test(expected=IllegalArgumentException.class) public void ambiguousOwnersFailClosed() throws Exception {
        InventoryRepository r=repo();r.spool("spool2").put("nfc_uid","aa-bb-cc-dd");r.nfcSpool("AABBCCDD");
    }
    @Test(expected=IllegalArgumentException.class) public void deletedOwnerFailsClosed() throws Exception {
        InventoryRepository r=repo();r.spool("spool1").put("is_deleted",1);r.nfcSpool("AABBCCDD");
    }
    @Test(expected=IllegalArgumentException.class) public void missingOwnerFailsClosed() throws Exception {
        InventoryRepository r=repo();r.data.put("spools",new JSONArray());r.nfcSpool("AABBCCDD");
    }
    @Test(expected=IllegalArgumentException.class) public void productMappingCannotBecomeNfcOwner() throws Exception {
        InventoryRepository r=repo();r.data.getJSONObject("mobile").put("codes",new JSONArray("[{\"code\":\"01020304\",\"kind\":\"product\",\"filament_id\":\"fil1\"}]"));r.nfcSpool("01020304");
    }
    @Test public void attachPayloadCannotChangeStockAndHasRetryId() throws Exception {
        InventoryRepository r=repo();JSONObject body=r.nfcAttachRequest("spool1","01020304");
        assertEquals(3,body.length());assertEquals("fil1",body.getString("expected_filament_id"));
        JSONObject m=body.getJSONObject("mobile");assertEquals(4,m.getInt("protocol"));assertEquals("nfc_attach",m.getString("operation"));
        assertFalse(body.has("weight_remaining_g"));assertFalse(body.has("filament"));
        assertNotEquals(m.getString("request_id"),r.nfcAttachRequest("spool1","01020304").getJSONObject("mobile").getString("request_id"));
    }
    @Test(expected=IllegalArgumentException.class) public void oldServerCannotBuildNfcReceipt() throws Exception {
        InventoryRepository r=repo();r.data.getJSONObject("mobile").put("features",new JSONArray());r.nfcEnvelope("nfc_receipt","01020304");
    }
    @Test public void nfcReceiptRecordedInQrBatchOnce() throws Exception {
        InventoryRepository r=repo();ReceiptBook book=new ReceiptBook("{}");
        JSONObject body=new JSONObject().put("mobile",r.nfcEnvelope("nfc_receipt","01020304")).put("weight_total_g",750).put("location","shelf1");
        JSONObject result=new JSONObject().put("ok",true).put("id","spool1").put("operation","nfc_receipt");
        book.record("farm1","batch1","NFC",result,body,"PLA Matte");book.record("farm1","batch1","NFC",result,body,"PLA Matte");
        assertEquals(1,book.get("farm1","batch1").getJSONArray("entries").length());
    }
}
