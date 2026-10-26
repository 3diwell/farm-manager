// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;
import org.junit.Test;
import java.nio.*;
import java.util.*;
import static org.junit.Assert.*;

public class BambuDataTest {
    @Test public void actualFieldsAreNotExpectedValues(){BambuData d=BambuData.parse(BambuFixture.UID,BambuFixture.blocks());assertEquals("PLA",d.material);assertEquals("PLA Matte",d.variant);assertEquals("223344FF",d.rgba);assertEquals(2.85f,d.diameter,0.0001);assertEquals(750,d.weight);assertEquals(0xff223344,d.rgbPreview());assertFalse(d.report().contains("Материал: PETG"));}
    @Test public void floatUsesFourLittleEndianBytesNotErroneousEightByteDocWidth(){Map<Integer,byte[]> b=BambuFixture.blocks();b.get(5)[12]=99;assertEquals(2.85f,BambuData.parse(BambuFixture.UID,b).diameter,0.0001);}
    @Test public void cautionLabelsRemainExplicit(){String r=BambuData.parse(BambuFixture.UID,BambuFixture.blocks()).report();assertTrue(r.contains("НЕ текущий остаток"));assertTrue(r.contains("RSA-подпись не проверялись"));assertTrue(r.contains("Orange не подставляется"));}
    @Test(expected=IllegalArgumentException.class) public void wrongUidRefused(){BambuData.parse(new byte[]{4,3,2,1},BambuFixture.blocks());}
    @Test(expected=IllegalArgumentException.class) public void missingBlockRefused(){Map<Integer,byte[]> b=BambuFixture.blocks();b.remove(4);BambuData.parse(BambuFixture.UID,b);}
    @Test(expected=IllegalArgumentException.class) public void shortBlockRefused(){Map<Integer,byte[]> b=BambuFixture.blocks();b.put(5,new byte[8]);BambuData.parse(BambuFixture.UID,b);}
    @Test(expected=IllegalArgumentException.class) public void unrelatedCardRefused(){Map<Integer,byte[]> b=BambuFixture.blocks();Arrays.fill(b.get(1),(byte)0);BambuData.parse(BambuFixture.UID,b);}
    @Test(expected=IllegalArgumentException.class) public void invalidEncodingRefused(){Map<Integer,byte[]> b=BambuFixture.blocks();b.get(2)[0]=(byte)0xff;BambuData.parse(BambuFixture.UID,b);}
    @Test(expected=IllegalArgumentException.class) public void nanDiameterRefused(){Map<Integer,byte[]> b=BambuFixture.blocks();ByteBuffer.wrap(b.get(5),8,4).order(ByteOrder.LITTLE_ENDIAN).putFloat(Float.NaN);BambuData.parse(BambuFixture.UID,b);}
    @Test(expected=IllegalArgumentException.class) public void zeroMassRefused(){Map<Integer,byte[]> b=BambuFixture.blocks();b.get(5)[4]=b.get(5)[5]=0;BambuData.parse(BambuFixture.UID,b);}
}
