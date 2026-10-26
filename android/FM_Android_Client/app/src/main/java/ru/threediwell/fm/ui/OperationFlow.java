// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;

import org.json.JSONObject;
import java.util.List;

/** Presentation only: never authorizes, submits or confirms an inventory operation. */
public enum OperationFlow {
    NONE, RECEIVE, SELECT_PRINTER, INSTALL, REMOVE;

    public static final String EXTRA = "operation_hint";
    public enum Item { PRINTER, FULL_SPOOL, LOW_SPOOL, WAREHOUSE }

    public List<Item> items() {
        return switch (this) {
            case RECEIVE -> List.of(Item.FULL_SPOOL, Item.WAREHOUSE);
            case SELECT_PRINTER -> List.of(Item.PRINTER);
            case INSTALL -> List.of(Item.FULL_SPOOL, Item.PRINTER);
            case REMOVE -> List.of(Item.PRINTER, Item.LOW_SPOOL, Item.WAREHOUSE);
            case NONE -> List.of();
        };
    }

    public boolean scanTarget(Item item) {
        return switch (this) {
            case RECEIVE, INSTALL -> item == Item.FULL_SPOOL;
            case SELECT_PRINTER -> item == Item.PRINTER;
            case REMOVE -> item == Item.PRINTER || item == Item.LOW_SPOOL;
            case NONE -> false;
        };
    }

    public static OperationFlow fromExtra(String value) {
        if (value == null) return NONE;
        try { return valueOf(value); }
        catch (IllegalArgumentException ignored) { return NONE; }
    }

    /** Reconstruct the illustration from the durable request, including after a retry/restart.
     * This does not mean success; the caller must first receive FM's acknowledgement. */
    public static OperationFlow fromRequest(String path, JSONObject body) {
        if (path == null || body == null) return NONE;
        JSONObject mobile = body.optJSONObject("mobile");
        if (mobile == null) return NONE;
        String operation = mobile.optString("operation");
        if (path.equals("/api/mod/inventory/spools/bulk-delete")&&operation.equals("replace_writeoff")) return INSTALL;
        if (path.matches("/api/mod/inventory/spool/[^/]+/bind")) {
            return switch (operation) {
                case "unbind" -> REMOVE;
                case "", "bind", "replace" -> INSTALL;
                default -> NONE;
            };
        }
        if (path.equals("/api/mod/inventory/spool")) {
            return switch (operation) {
                case "", "nfc_receipt", "claim_label" -> RECEIVE;
                default -> NONE;
            };
        }
        return NONE;
    }
}
