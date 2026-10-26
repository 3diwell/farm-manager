// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.i18n;

import org.junit.*;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import ru.threediwell.fm.core.FmApi;
import ru.threediwell.fm.core.SavedSession;
import ru.threediwell.fm.inventory.Labels;
import ru.threediwell.fm.nfc.NfcReport;
import ru.threediwell.fm.ui.intro.IntroModel;
import static org.junit.Assert.*;

public class I18nTest {
    @After public void reset(){I18n.setLanguage("ru");}
    private JSONObject catalog() throws Exception {
        try(InputStream stream=I18n.class.getResourceAsStream("/i18n/en.json")) {
            assertNotNull(stream);return new JSONObject(new String(stream.readAllBytes(),StandardCharsets.UTF_8));
        }
    }
    @Test public void everyCatalogEntryLoadsInBothLanguages() throws Exception {
        JSONObject catalog=catalog();assertTrue(catalog.length()>=629);
        for(Iterator<String> it=catalog.keys();it.hasNext();) {
            String source=it.next();I18n.setLanguage("en");assertEquals(catalog.getString(source),I18n.t(source));
            assertFalse(I18n.t(source).isBlank());assertFalse(I18n.t(source).matches("(?s).*[А-Яа-яЁё].*"));
            I18n.setLanguage("ru");assertEquals(source,I18n.t(source));
        }
    }
    @Test public void repeatedSwitchesNeverCacheThePreviousLanguage() {
        for(int i=0;i<10;i++) {
            I18n.setLanguage("en");assertEquals("Inventory",I18n.t("Склад"));assertEquals("en",I18n.locale().getLanguage());
            I18n.setLanguage("ru");assertEquals("Склад",I18n.t("Склад"));assertEquals("ru",I18n.locale().getLanguage());
        }
    }
    @Test public void unexpectedPreferenceFallsBackToRussian() {
        I18n.setLanguage("fr");assertEquals("ru",I18n.language());I18n.setLanguage(null);assertEquals("ru",I18n.language());
    }
    @Test public void errorCodesStayStableWhileTheirMessagesChange() {
        I18n.setLanguage("en");FmApi.Rejected rejected=new FmApi.Rejected("slot_occupied");
        assertEquals("slot_occupied",rejected.code);assertTrue(rejected.getMessage().startsWith("Position already occupied"));
        I18n.setLanguage("ru");assertTrue(new FmApi.Rejected("slot_occupied").getMessage().startsWith("Позиция уже занята"));
        assertTrue(new FmApi.Unauthorized().getMessage().contains("Нужен вход"));
    }
    @Test public void allFourEnglishGreetingsUseTheSameTimeBoundaries() {
        I18n.setLanguage("en");
        for(int hour=0;hour<24;hour++) {
            assertEquals(hour<6?"Good night":hour<12?"Good morning":hour<18?"Have a good day":"Have a good evening",IntroModel.greeting(hour));
            assertFalse(IntroModel.wish(hour).matches(".*[А-Яа-яЁё].*"));
        }
    }
    @Test public void nfcReportTranslatesWithoutAlteringUserProvidedModelOrUid() {
        I18n.setLanguage("en");String report=NfcReport.create("Мой телефон","15",new byte[]{1,2,3,4},new String[]{"android.nfc.tech.NfcA"},false,0,0,"");
        assertTrue(report.contains("Phone: Мой телефон"));assertTrue(report.contains("01020304"));assertTrue(report.contains("Diagnostics only"));
    }
    @Test public void qrPayloadAndStoredSessionAreLanguageIndependent() throws Exception {
        I18n.setLanguage("ru");String qr=Labels.spool("farm","spool");
        SavedSession session=new SavedSession("https://fm.test","synthetic_token",1700000000000L,1700000001000L,true);
        byte[] stored=session.encode();I18n.setLanguage("en");assertEquals(qr,Labels.spool("farm","spool"));
        assertArrayEquals(stored,session.encode());assertEquals("synthetic_token",SavedSession.decode(stored).token);
    }
}
