// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Synthetic data deliberately differs from user's expected PETG / Orange / 1.75. */
final class BambuFixture {
    static final byte[] UID={1,2,3,4};
    static void text(byte[] block,int at,String s){byte[] b=s.getBytes(StandardCharsets.US_ASCII);System.arraycopy(b,0,block,at,b.length);}
    static Map<Integer,byte[]> blocks(){
        Map<Integer,byte[]> b=new LinkedHashMap<>();for(int i:new int[]{0,1,2,4,5})b.put(i,new byte[16]);
        System.arraycopy(UID,0,b.get(0),0,4);text(b.get(1),0,"A00-X");text(b.get(1),8,"GFA00");text(b.get(2),0,"PLA");text(b.get(4),0,"PLA Matte");
        byte[] p=b.get(5);p[0]=0x22;p[1]=0x33;p[2]=0x44;p[3]=(byte)0xff;p[4]=(byte)0xee;p[5]=2;
        ByteBuffer.wrap(p,8,4).order(ByteOrder.LITTLE_ENDIAN).putFloat(2.85f);return b;
    }
}
