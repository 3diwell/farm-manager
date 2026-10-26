// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;
import org.junit.Test;
import java.util.*;
import com.google.zxing.*;
import com.google.zxing.common.*;
import static org.junit.Assert.*;

public class LabelSheetTest {
    private LabelSheet.Entry e(String server,String id) {return new LabelSheet.Entry(id,"PETG · Серый",Labels.spool(server,id));}
    @Test public void pageBoundaries() {assertEquals(1,LabelSheet.pages(1));assertEquals(1,LabelSheet.pages(8));assertEquals(2,LabelSheet.pages(9));assertEquals(3,LabelSheet.pages(24));assertEquals(63,LabelSheet.pages(500));}
    @Test(expected=IllegalArgumentException.class) public void emptyRejected(){LabelSheet.validate(Collections.emptyList());}
    @Test(expected=IllegalArgumentException.class) public void tooManyRejected(){LabelSheet.pages(501);}
    @Test(expected=IllegalArgumentException.class) public void duplicatesRejected(){LabelSheet.validate(Arrays.asList(e("farm","s1"),e("farm","s1")));}
    @Test(expected=IllegalArgumentException.class) public void mixedFarmsRejected(){LabelSheet.validate(Arrays.asList(e("farm","s1"),e("other","s2")));}
    @Test(expected=IllegalArgumentException.class) public void slotRejected(){LabelSheet.validate(Arrays.asList(new LabelSheet.Entry("p1","slot",Labels.slot("farm","p1",0))));}
    @Test public void immutableSnapshot(){List<LabelSheet.Entry> a=new ArrayList<>();a.add(e("farm","s1"));List<LabelSheet.Entry>b=LabelSheet.validate(a);a.clear();assertEquals(1,b.size());}
    @Test public void everyGeneratedQrDecodesToItsExactSpool() throws Exception {
        for(int i=0;i<25;i++) {
            String value=Labels.spool("550e8400-e29b-41d4-a716-446655440000","spool_"+i);
            BitMatrix bits=new MultiFormatWriter().encode(value,BarcodeFormat.QR_CODE,640,640,Collections.singletonMap(EncodeHintType.MARGIN,4));
            int[] pixels=new int[640*640];for(int y=0;y<640;y++)for(int x=0;x<640;x++)pixels[y*640+x]=bits.get(x,y)?0xff000000:0xffffffff;
            Result result=new MultiFormatReader().decode(new BinaryBitmap(new HybridBinarizer(new RGBLuminanceSource(640,640,pixels))));assertEquals(value,result.getText());
        }
    }
    @Test public void vectorMatrixHasQuietZoneAndDecodes() throws Exception {
        String value=Labels.spool("farm_1","spool_1");
        BitMatrix small=new MultiFormatWriter().encode(value,BarcodeFormat.QR_CODE,0,0,Collections.singletonMap(EncodeHintType.MARGIN,4));
        int scale=8,n=small.getWidth()*scale;int[] pixels=new int[n*n];
        for(int y=0;y<n;y++)for(int x=0;x<n;x++)pixels[y*n+x]=small.get(x/scale,y/scale)?0xff000000:0xffffffff;
        assertEquals(value,new MultiFormatReader().decode(new BinaryBitmap(new HybridBinarizer(new RGBLuminanceSource(n,n,pixels)))).getText());
        for(int i=0;i<small.getWidth();i++)for(int margin=0;margin<4;margin++){assertFalse(small.get(i,margin));assertFalse(small.get(margin,i));}
    }
    @Test public void cellsFitPageWithoutOverlap() {
        for(int i=0;i<8;i++) {
            LabelSheet.Cell a=LabelSheet.cell(i);assertTrue(a.x()>=24);assertTrue(a.y()>=58);assertTrue(a.x()+a.width()<=LabelSheet.WIDTH-24);assertTrue(a.y()+a.height()<=LabelSheet.HEIGHT-24);
            for(int j=i+1;j<8;j++){LabelSheet.Cell b=LabelSheet.cell(j);assertTrue(a.x()+a.width()<=b.x()||b.x()+b.width()<=a.x()||a.y()+a.height()<=b.y()||b.y()+b.height()<=a.y());}
        }
    }
}
