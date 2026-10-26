// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;

import ru.threediwell.fm.i18n.I18n;
import java.security.GeneralSecurityException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Independent RFC 5869 implementation; public Bambu protocol parameters, see NFC_SOURCES.md. */
public final class BambuKeys {
    private BambuKeys() {}
    private static final byte[] SALT={(byte)0x9a,0x75,(byte)0x9c,(byte)0xf2,(byte)0xc4,(byte)0xf7,(byte)0xca,(byte)0xff,
            0x22,0x2c,(byte)0xb9,0x76,(byte)0x9b,0x41,(byte)0xbc,(byte)0x96};
    public static byte[][] derive(byte[] uid) throws GeneralSecurityException {
        if(uid==null||uid.length!=4)throw new IllegalArgumentException(I18n.t("Эта версия поддерживает UID из 4 байт; другой формат не проверен."));
        byte[] expanded=hkdf(uid,SALT,"RFID-A\0".getBytes(StandardCharsets.US_ASCII),96);
        byte[][] keys=new byte[16][];
        for(int i=0;i<16;i++)keys[i]=Arrays.copyOfRange(expanded,i*6,i*6+6);
        Arrays.fill(expanded,(byte)0);return keys;
    }
    static byte[] hkdf(byte[] input,byte[] salt,byte[] info,int length) throws GeneralSecurityException {
        if(length<1||length>255*32)throw new IllegalArgumentException("HKDF length");
        Mac mac=Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(salt.length==0?new byte[32]:salt,"HmacSHA256"));
        byte[] prk=mac.doFinal(input),previous=new byte[0],out=new byte[length];
        mac.init(new SecretKeySpec(prk,"HmacSHA256"));
        for(int offset=0,counter=1;offset<length;counter++) {
            mac.update(previous);mac.update(info);mac.update((byte)counter);previous=mac.doFinal();
            int count=Math.min(previous.length,length-offset);System.arraycopy(previous,0,out,offset,count);offset+=count;
        }
        Arrays.fill(prk,(byte)0);Arrays.fill(previous,(byte)0);return out;
    }
}
