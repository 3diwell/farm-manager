// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;

import org.json.JSONObject;
import org.junit.Test;
import java.util.List;
import static org.junit.Assert.*;
import static ru.threediwell.fm.ui.OperationFlow.*;
import static ru.threediwell.fm.ui.OperationFlow.Item.*;

public class OperationFlowTest {
    private JSONObject body(String operation) throws Exception {
        JSONObject mobile = new JSONObject().put("server_id", "farm-1").put("request_id", "req-1");
        if (operation != null) mobile.put("operation", operation);
        return new JSONObject().put("mobile", mobile);
    }
    @Test public void receiptAndInstallUseFullBlackSpool() {
        assertEquals(List.of(FULL_SPOOL, WAREHOUSE), RECEIVE.items());
        assertEquals(List.of(PRINTER), SELECT_PRINTER.items());
        assertEquals(List.of(FULL_SPOOL, PRINTER), INSTALL.items());
        assertTrue(INSTALL.scanTarget(FULL_SPOOL));
        assertFalse(INSTALL.scanTarget(PRINTER));
        assertFalse(RECEIVE.scanTarget(WAREHOUSE));
    }
    @Test public void removalUsesLowSpoolButAllowsEitherCode() {
        assertEquals(List.of(PRINTER, LOW_SPOOL, WAREHOUSE), REMOVE.items());
        assertTrue(REMOVE.scanTarget(PRINTER));
        assertTrue(REMOVE.scanTarget(LOW_SPOOL));
        assertFalse(REMOVE.scanTarget(WAREHOUSE));
    }
    @Test public void missingOrUnknownIntentNeverInventsAnOperation() {
        assertEquals(NONE, fromExtra(null));
        assertEquals(NONE, fromExtra(""));
        assertEquals(NONE, fromExtra("future_operation"));
        assertTrue(NONE.items().isEmpty());
        for (OperationFlow flow : OperationFlow.values()) assertEquals(flow, fromExtra(flow.name()));
    }
    @Test public void regularNfcAndPreparedReceiptsHaveSameRoute() throws Exception {
        for (String operation : new String[]{null, "nfc_receipt", "claim_label"})
            assertEquals(RECEIVE, fromRequest("/api/mod/inventory/spool", body(operation)));
    }
    @Test public void bindOldProtocolReplaceAndUnbindRemainDistinctAfterJournalRestore() throws Exception {
        String path = "/api/mod/inventory/spool/spool-1/bind";
        for (String operation : new String[]{null, "bind", "replace", "unbind"}) {
            JSONObject pending = new JSONObject().put("path", path).put("body", body(operation));
            JSONObject restored = new JSONObject(pending.toString());
            assertEquals("unbind".equals(operation) ? REMOVE : INSTALL,
                    fromRequest(restored.getString("path"), restored.getJSONObject("body")));
        }
    }
    @Test public void nfcLinkAndLabelPreparationDoNotPretendToMoveStock() throws Exception {
        for (String operation : new String[]{"nfc_attach", "prepare_labels", "cancel_labels", "future_operation"})
            assertEquals(NONE, fromRequest("/api/mod/inventory/spool", body(operation)));
    }
    @Test public void unknownOrIncompleteJournalHasNoMisleadingIllustration() throws Exception {
        assertEquals(NONE, fromRequest(null, body(null)));
        assertEquals(NONE, fromRequest("/api/mod/inventory/spool", null));
        assertEquals(NONE, fromRequest("/api/mod/inventory/spool", new JSONObject()));
        assertEquals(NONE, fromRequest("/api/mod/inventory/spool/x/bind", body("future_operation")));
        assertEquals(NONE, fromRequest("/api/mod/inventory/spool//bind", body("unbind")));
        assertEquals(NONE, fromRequest("/api/mod/inventory/spool/x/delete", body(null)));
    }
}
