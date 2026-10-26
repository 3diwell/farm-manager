// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.scan;

import org.junit.Test;
import static org.junit.Assert.*;
import java.util.*;
import com.google.zxing.*;
import com.google.zxing.common.*;
import com.google.zxing.qrcode.QRCodeWriter;
import com.google.zxing.multi.qrcode.QRCodeMultiReader;
import ru.threediwell.fm.inventory.Labels;

/** Real synthetic QR pixels; verifies crop isolation, not the Android camera/ML Kit pipeline. */
public class CroppedQrTest {
    private static final int W=1120,H=320;
    private int[] scene()throws Exception {
        int[] pixels=new int[W*H];Arrays.fill(pixels,0xFFFFFFFF);
        for(int slot=0;slot<4;slot++) {
            BitMatrix qr=new QRCodeWriter().encode(Labels.slot("farm","printer",slot),BarcodeFormat.QR_CODE,160,160);
            int left=80+slot*260;
            for(int y=0;y<160;y++)for(int x=0;x<160;x++)if(qr.get(x,y))pixels[(y+80)*W+left+x]=0xFF000000;
        }
        return pixels;
    }
    private Result[] read(int[] pixels,int width,int height)throws Exception {
        return new QRCodeMultiReader().decodeMultiple(new BinaryBitmap(new HybridBinarizer(new RGBLuminanceSource(width,height,pixels))));
    }
    private void aimed(int index)throws Exception {
        int[] source=scene();AimWindow.Box b=AimWindow.inView(480,320,true);
        int viewLeft=160+index*260-240;
        AimWindow.Box crop=AimWindow.inward(new AimWindow.Box(b.left()+viewLeft,b.top(),b.right()+viewLeft,b.bottom()),W,H);
        int cw=(int)crop.width(),ch=(int)crop.height();int[] pixels=new int[cw*ch];
        for(int y=0;y<ch;y++)System.arraycopy(source,((int)crop.top()+y)*W+(int)crop.left(),pixels,y*cw,cw);
        Result[] codes=read(pixels,cw,ch);assertEquals(1,codes.length);assertEquals(Labels.slot("farm","printer",index),codes[0].getText());
    }
    @Test public void fullFrameContainsAllFourNeighbors()throws Exception{assertEquals(4,read(scene(),W,H).length);}
    @Test public void aimSlot1Only()throws Exception{aimed(0);}
    @Test public void aimSlot2Only()throws Exception{aimed(1);}
    @Test public void aimSlot3Only()throws Exception{aimed(2);}
    @Test public void aimSlot4Only()throws Exception{aimed(3);}
}
