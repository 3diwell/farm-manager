// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;
import org.junit.Test;
import java.util.*;
import static org.junit.Assert.*;

public class BambuKeysTest {
    static byte[] bytes(String hex){byte[] b=new byte[hex.length()/2];for(int i=0;i<b.length;i++)b[i]=(byte)Integer.parseInt(hex.substring(i*2,i*2+2),16);return b;}
    @Test public void rfc5869CaseOne() throws Exception {
        byte[] input=new byte[22];Arrays.fill(input,(byte)0x0b);
        assertArrayEquals(bytes("3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"),
                BambuKeys.hkdf(input,bytes("000102030405060708090a0b0c"),bytes("f0f1f2f3f4f5f6f7f8f9"),42));
    }
    @Test public void independentPythonVectorIncludesNullContextAndContinuousExpansion() throws Exception {
        byte[][] keys=BambuKeys.derive(bytes("01020304"));StringBuilder hex=new StringBuilder();for(byte[] k:keys){assertEquals(6,k.length);hex.append(NfcReport.hex(k));}
        assertEquals("6B0D673986DE9C41CDFA0A4D5AB94CC9A3B6AE3FB10303106C36A6C9CF6C45710F6E14654B012032D28D640BCB97C72684AC6F1C718779065C3C6ADC3955F280D8152D68D89656D097E262D27942814B8CAE3FBECB862A792EBABE9DA70EE88E",hex.toString());
    }
    @Test public void byteOrderMattersAndInputIsNotMutated() throws Exception {
        byte[] uid=bytes("0001ABFF"),copy=uid.clone();byte[][] a=BambuKeys.derive(uid),b=BambuKeys.derive(bytes("FFAB0100"));
        assertArrayEquals(copy,uid);assertFalse(Arrays.equals(a[0],b[0]));
    }
    @Test(expected=IllegalArgumentException.class) public void unknownUidLengthRefused() throws Exception {BambuKeys.derive(new byte[7]);}
    @Test(expected=IllegalArgumentException.class) public void emptyUidRefused() throws Exception {BambuKeys.derive(null);}
}
