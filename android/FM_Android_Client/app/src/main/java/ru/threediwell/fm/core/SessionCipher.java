// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import ru.threediwell.fm.i18n.I18n;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Versioned authenticated envelope. Android supplies a non-exportable Keystore key. */
public final class SessionCipher {
    private static final byte[] AAD="FM Android remembered session v1".getBytes(StandardCharsets.UTF_8);
    private SessionCipher() {}
    public static byte[] seal(SecretKey key, byte[] plain) throws Exception {
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE,key); // The provider generates a fresh random IV for every write.
        cipher.updateAAD(AAD);
        byte[] iv=cipher.getIV(), encrypted=cipher.doFinal(plain);
        if(iv.length!=12) throw new IOException(I18n.t("Некорректный формат ключа"));
        byte[] result=new byte[1+iv.length+encrypted.length];result[0]=1;
        System.arraycopy(iv,0,result,1,iv.length);System.arraycopy(encrypted,0,result,13,encrypted.length);
        return result;
    }
    public static byte[] open(SecretKey key, byte[] envelope) throws Exception {
        if(envelope.length<29 || envelope.length>16384 || envelope[0]!=1) throw new IOException(I18n.t("Повреждён сохранённый вход"));
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,key,new GCMParameterSpec(128,Arrays.copyOfRange(envelope,1,13)));
        cipher.updateAAD(AAD);
        return cipher.doFinal(envelope,13,envelope.length-13);
    }
}
