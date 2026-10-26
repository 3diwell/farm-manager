// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;
import org.junit.Test;
import static org.junit.Assert.*;

public class NfcReportTest {
    private String report(String[] tech,boolean classic) {
        return NfcReport.create("Redmi Note 14S","14",new byte[]{0,1,(byte)0xAB,(byte)0xFF},tech,classic,1024,16,"NFC-A");
    }
    @Test public void uidPreservesLeadingZerosAndByteOrder(){assertEquals("0001ABFF",NfcReport.hex(new byte[]{0,1,(byte)0xAB,(byte)0xFF}));}
    @Test public void emptyUidDoesNotInventIdentity(){assertEquals("не предоставлен",NfcReport.hex(new byte[0]));assertEquals("не предоставлен",NfcReport.hex(null));}
    @Test public void classicSupportIsNotProofOfBambuReading(){String s=report(new String[]{"android.nfc.tech.MifareClassic"},true);assertTrue(s.contains("1024 байт; секторов: 16"));assertTrue(s.contains("пока НЕ подтверждено"));assertTrue(s.contains("Материал и цвет не считывались"));assertTrue(s.contains("производитель не определён"));}
    @Test public void otherTechDoesNotDeclarePhoneIncompatible(){String s=report(new String[]{"android.nfc.tech.NfcA"},false);assertTrue(s.contains("может быть другой тип"));assertTrue(s.contains("нельзя объявить весь телефон несовместимым"));}
    @Test public void inconsistentDriverIsReported(){assertTrue(report(new String[]{"android.nfc.tech.MifareClassic"},false).contains("объявлен системой, но интерфейс недоступен"));}
    @Test public void missingTechAndSafetyAreExplicit(){String s=report(null,false);assertTrue(s.contains("Технологии: не предоставлены"));assertTrue(s.contains("Метка не изменена"));assertTrue(s.contains("Запросы к FM не отправлялись"));}
    @Test public void uidIsNotAnAuthenticationClaim(){assertTrue(report(new String[0],false).contains("UID не доказывает подлинность или уникальность"));}
}
