// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import org.junit.Test;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import static org.junit.Assert.*;

public class SessionCipherTest {
    private SecretKey key() throws Exception {KeyGenerator generator=KeyGenerator.getInstance("AES");generator.init(256);return generator.generateKey();}
    private byte[] plain() {return "synthetic_token_NEVER_A_REAL_CREDENTIAL".getBytes(StandardCharsets.UTF_8);}
    @Test public void authenticatedEncryptionRoundTripAndNoPlaintext() throws Exception {
        SecretKey key=key();byte[] envelope=SessionCipher.seal(key,plain());
        assertArrayEquals(plain(),SessionCipher.open(key,envelope));
        assertFalse(new String(envelope,StandardCharsets.ISO_8859_1).contains("synthetic_token"));
    }
    @Test public void freshIvForEachWrite() throws Exception {
        SecretKey key=key();byte[] a=SessionCipher.seal(key,plain()),b=SessionCipher.seal(key,plain());
        assertFalse(Arrays.equals(Arrays.copyOfRange(a,1,13),Arrays.copyOfRange(b,1,13)));
    }
    @Test public void tamperingWithCiphertextOrIvOrVersionIsRejected() throws Exception {
        SecretKey key=key();byte[] original=SessionCipher.seal(key,plain());
        for(int index:new int[]{0,1,13,original.length-1}) {
            byte[] changed=original.clone();changed[index]^=1;
            try {SessionCipher.open(key,changed);fail("Tampering accepted");}catch(java.security.GeneralSecurityException|java.io.IOException expected){}
        }
    }
    @Test public void differentDeviceKeyCannotOpenSession() throws Exception {
        byte[] envelope=SessionCipher.seal(key(),plain());
        try {SessionCipher.open(key(),envelope);fail();}catch(java.security.GeneralSecurityException expected){}
    }
    @Test public void truncatedFileRejected() throws Exception {
        SecretKey key=key();byte[] envelope=SessionCipher.seal(key,plain());
        try {SessionCipher.open(key,Arrays.copyOf(envelope,envelope.length-1));fail();}catch(java.security.GeneralSecurityException expected){}
    }
}
