// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import org.junit.Test;
import static org.junit.Assert.*;

public class SavedSessionTest {
    private final long start=1700000000000L;
    private SavedSession session() {return new SavedSession("http://fm.test:8000","synthetic_token",start,start+SavedSession.MAX_AGE_MILLIS,false);}
    @Test public void expiresExactlyEightHoursAfterLogin() {
        SavedSession s=session();assertTrue(s.validAt(start));assertTrue(s.validAt(s.expiresAt-1));assertFalse(s.validAt(s.expiresAt));
    }
    @Test public void clockBeforeLoginCannotRestoreSession() {assertFalse(session().validAt(start-1));}
    @Test public void restartRoundTripDoesNotExtendDeadline() throws Exception {
        SavedSession s=session();
        for(int i=0;i<10;i++)s=SavedSession.decode(s.encode());
        assertEquals(start,s.issuedAt);assertEquals(start+SavedSession.MAX_AGE_MILLIS,s.expiresAt);
        assertEquals("synthetic_token",s.token);assertEquals("http://fm.test:8000",s.origin);
    }
    @Test(expected=IllegalArgumentException.class) public void rejectsLifetimeOverEightHours() {
        new SavedSession("http://fm.test","token",start,start+SavedSession.MAX_AGE_MILLIS+1,false);
    }
    @Test(expected=IllegalArgumentException.class) public void rejectsSecureCookieOnHttp() {
        new SavedSession("http://fm.test","token",start,start+1000,true);
    }
    @Test(expected=IllegalArgumentException.class) public void rejectsHeaderInjection() {
        new SavedSession("http://fm.test","token\r\nHeader: value",start,start+1000,false);
    }
    @Test(expected=IllegalArgumentException.class) public void rejectsEmptyLifetime() {
        new SavedSession("http://fm.test","token",start,start,false);
    }

    // --- remembered device (format 2) and files written by 0.13–0.15.15 (format 1) ---

    /** Exactly what 0.15.15 put inside fm_session.enc (SavedSession.encode, format 1). */
    private static byte[] fileOf0_15_15(long issued,long expires) {
        return ("{\"version\":1,\"origin\":\"http://fm.test:8000\",\"token\":\"synthetic_token\",\"issuedAt\":"+issued
                +",\"expiresAt\":"+expires+",\"secure\":false}").getBytes(java.nio.charset.StandardCharsets.UTF_8);
    }
    @Test public void sessionSavedBy0_15_15IsReadAndKeepsItsEightHourDeadline() throws Exception {
        SavedSession old=SavedSession.decode(fileOf0_15_15(start,start+SavedSession.MAX_AGE_MILLIS));
        assertFalse(old.persistent);assertEquals("synthetic_token",old.token);assertEquals("http://fm.test:8000",old.origin);
        assertTrue(old.validAt(start+SavedSession.MAX_AGE_MILLIS-1));assertFalse(old.validAt(start+SavedSession.MAX_AGE_MILLIS));
        assertFalse(old.validAt(start-1));
        // Rewriting an 8-hour login keeps format 1, readable by the previous build after a rollback.
        org.json.JSONObject rewritten=new org.json.JSONObject(new String(old.encode(),java.nio.charset.StandardCharsets.UTF_8));
        assertEquals(1,rewritten.getInt("version"));assertFalse(rewritten.has("persistent"));
    }
    @Test public void encryptedFileOf0_15_15OpensWithTheSameEnvelope() throws Exception {
        // The envelope is built by hand the way 0.15.15 did: version byte 1, 12-byte IV, AES/GCM, same AAD.
        javax.crypto.KeyGenerator generator=javax.crypto.KeyGenerator.getInstance("AES");generator.init(256);
        javax.crypto.SecretKey key=generator.generateKey();
        javax.crypto.Cipher cipher=javax.crypto.Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(javax.crypto.Cipher.ENCRYPT_MODE,key);
        cipher.updateAAD("FM Android remembered session v1".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        byte[] iv=cipher.getIV(),encrypted=cipher.doFinal(fileOf0_15_15(start,start+60000));
        byte[] envelope=new byte[1+iv.length+encrypted.length];envelope[0]=1;
        System.arraycopy(iv,0,envelope,1,iv.length);System.arraycopy(encrypted,0,envelope,13,encrypted.length);
        SavedSession old=SavedSession.decode(SessionCipher.open(key,envelope));
        assertEquals(start+60000,old.expiresAt);assertFalse(old.persistent);
    }
    @Test public void persistentLoginHasNoPhoneClockLimitAndSurvivesRestarts() throws Exception {
        SavedSession s=SavedSession.persistent("http://fm.test:8000","fmd_FIXTURE_device_token",start,false);
        assertTrue(s.persistent);assertEquals(0,s.expiresAt);
        assertTrue(s.validAt(start+SavedSession.MAX_AGE_MILLIS));assertTrue(s.validAt(start+20L*365*24*3600*1000));
        assertTrue(s.validAt(start-1));
        for(int i=0;i<10;i++)s=SavedSession.decode(s.encode());
        assertTrue(s.persistent);assertEquals(start,s.issuedAt);assertEquals("fmd_FIXTURE_device_token",s.token);
        org.json.JSONObject stored=new org.json.JSONObject(new String(s.encode(),java.nio.charset.StandardCharsets.UTF_8));
        assertEquals(2,stored.getInt("version"));assertTrue(stored.getBoolean("persistent"));
    }
    @Test public void brokenOrForeignFormatsAreRejected() throws Exception {
        for(String bad:new String[]{
                "{\"version\":3,\"origin\":\"http://fm.test\",\"token\":\"t\",\"issuedAt\":1,\"expiresAt\":0,\"secure\":false}",
                "{\"version\":2,\"origin\":\"http://fm.test\",\"token\":\"t\",\"issuedAt\":1,\"expiresAt\":5,\"secure\":false,\"persistent\":true}",
                "{\"version\":2,\"origin\":\"http://fm.test\",\"token\":\"t\",\"issuedAt\":1,\"expiresAt\":0,\"secure\":false}",
                "{\"version\":1,\"origin\":\"http://fm.test\",\"token\":\"t\",\"issuedAt\":1,\"expiresAt\":0,\"secure\":false,\"persistent\":true}"}) {
            try{SavedSession.decode(bad.getBytes(java.nio.charset.StandardCharsets.UTF_8));fail(bad);}catch(Exception expected){}
        }
        try{SavedSession.persistent("http://fm.test","token\r\nX: y",start,false);fail();}catch(IllegalArgumentException expected){}
        try{SavedSession.persistent("http://fm.test","token",start,true);fail();}catch(IllegalArgumentException expected){}
    }
}
