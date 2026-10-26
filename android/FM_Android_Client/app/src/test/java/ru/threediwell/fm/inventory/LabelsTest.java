// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;
import org.junit.Test;
import static org.junit.Assert.*;

public class LabelsTest {
    @Test public void slotZeroAndExternalStayDistinct() {
        assertEquals(0, Labels.parse(Labels.slot("farm-1", "printer_1", 0), "farm-1").slot());
        assertEquals(-1, Labels.parse(Labels.slot("farm-1", "printer_1", -1), "farm-1").slot());
    }
    @Test(expected=IllegalArgumentException.class) public void otherFarmRejected() {
        Labels.parse(Labels.spool("farm-2", "spool_1"), "farm-1");
    }
    @Test(expected=IllegalArgumentException.class) public void malformedSlotRejected() {
        Labels.parse("fm1:slot:farm:printer:-2", "farm");
    }
    @Test public void codeIsNotChangedOrOpened() {
        assertEquals("000123", Labels.normalize(" 000123 "));
        assertEquals("https://example.test/AbC", Labels.normalize("https://example.test/AbC"));
    }
    @Test public void realPhotoEanChecksum() {
        assertTrue(Labels.productBarcode("8594173675322"));
        assertTrue(Labels.productBarcode("6938936713784"));
        assertFalse(Labels.productBarcode("8594173675323"));
    }
}
