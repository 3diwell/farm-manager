// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui.intro;

import org.junit.Test;
import static org.junit.Assert.*;
import java.nio.file.*;

public class IntroModelTest {
    private IntroModel model() throws Exception {return new IntroModel(new String(Files.readAllBytes(Paths.get("src/main/assets/intro_v06.json")),java.nio.charset.StandardCharsets.UTF_8));}
    @Test public void timingIsClampedToSevenSeconds() {
        assertEquals(1,IntroModel.frameAt(-20),0);assertEquals(73,IntroModel.frameAt(3000),0);
        assertEquals(97,IntroModel.frameAt(4000),0);assertEquals(168,IntroModel.frameAt(9999),0);
    }
    @Test public void finalPlacementAndCameraAreLockedBeforeImpact() throws Exception {
        IntroModel m=model();float[] v=new float[29];
        for(int ms=3000;ms<=7000;ms+=7){m.sample(IntroModel.frameAt(ms),v);assertEquals(21,v[0],.00001);}
        for(int f=105;f<=168;f++)for(int i:new int[]{0,2,3,4,5,6,7})assertEquals(0,m.frames[f-1][18+i],.00001);
        for(int f=109;f<=168;f++)for(int i=0;i<11;i++)assertEquals(0,m.frames[f-1][18+i],.00001);
    }
    @Test public void contactIsExactAndAnticipationPrecedesIt() throws Exception {
        IntroModel m=model();assertEquals(.30458498,m.frames[96][27],.000001);
        assertEquals(0,m.frames[96][19],.000001);
        assertEquals(-1.2,m.frames[82][27],.000001);assertEquals(-1.52,m.frames[88][27],.000001);
        assertTrue(m.frames[98][19]>0);
    }
    @Test public void engineeringUsesUniformRotationAndPositivePerspective() throws Exception {
        IntroModel m=model();
        for(int f=0;f<73;f++) {
            float[] v=m.frames[f];assertTrue(v[0]>0);
            for(int row=0;row<3;row++){double norm=0;for(int c=0;c<3;c++)norm+=v[2+row*3+c]*v[2+row*3+c];assertEquals(1,norm,.00001);}
            assertTrue(v[11]<3);assertTrue(v[12]>-3);
        }
    }
    @Test public void greetingsHaveExplicitLocalTimeBoundaries() {
        assertEquals("Спокойной ночи",IntroModel.greeting(0));assertEquals("Спокойной ночи",IntroModel.greeting(5));
        assertEquals("Доброе утро",IntroModel.greeting(6));assertEquals("Доброе утро",IntroModel.greeting(11));
        assertEquals("Хорошего дня",IntroModel.greeting(12));assertEquals("Хорошего дня",IntroModel.greeting(17));
        assertEquals("Хорошего вечера",IntroModel.greeting(18));assertEquals("Хорошего вечера",IntroModel.greeting(23));
        for(int h=0;h<24;h++) {
            String expected=h<6?"Спокойной ночи и стабильности процессу!":h<12?"Доброе утро и пусть всё начнётся ровно!":h<18?"Хорошего дня и точного результата!":"Хорошего вечера и реализации планов!";
            assertEquals(expected,IntroModel.greeting(h)+" "+IntroModel.wish(h));
        }
    }
    @Test public void rendererHidesRestUntilImpactAndUsesOriginalFinalColors() throws Exception {
        IntroRenderer r=new IntroRenderer(model());Recording c=new Recording();
        r.draw(c,0);assertEquals(0,c.fills);
        r.draw(c,4000);assertEquals(4,c.fills);assertEquals(0,c.clips);
        c=new Recording();r.draw(c,4050);assertEquals(11,c.fills);assertEquals(1,c.clips);assertEquals(0,c.clipDepth);
        c=new Recording();r.draw(c,5000);assertEquals(11,c.fills);assertEquals(4,c.orange);assertEquals(7,c.white);
    }
    @Test public void rendererStaysFiniteAcrossEveryInterpolatedFrame() throws Exception {
        IntroRenderer r=new IntroRenderer(model());for(int ms=0;ms<=7000;ms+=7){Recording c=new Recording();r.draw(c,ms);assertEquals(0,c.clipDepth);}
    }
    @Test public void sourceContoursRemainClosedCubicPaths() throws Exception {
        IntroModel m=model();assertEquals(11,m.paths.length);
        for(float[][] shape:m.paths)for(float[] c:shape)assertEquals(0,c.length%6);
        assertEquals(2,m.paths[3].length);
    }
    private static class Recording implements IntroRenderer.Surface {
        int fills,clips,clipDepth,orange,white;
        private void finite(float... values){for(float v:values)assertTrue(Float.isFinite(v));}
        public void begin(){}public void move(float x,float y){finite(x,y);}public void line(float x,float y){finite(x,y);}
        public void cubic(float a,float b,float c,float d,float e,float f){finite(a,b,c,d,e,f);}public void close(){}
        public void fill(int t,int m,int b,float alpha){finite(alpha);assertTrue(alpha>=0&&alpha<=1);fills++;if(t==0xFFEA5E20&&m==t&&b==t)orange++;if(t==0xFFFFFFFF&&m==t&&b==t)white++;}
        public void stroke(int c,float w,float alpha){finite(w,alpha);assertTrue(w>0);}
        public void clipLeft(float x){finite(x);clips++;clipDepth++;}public void unclip(){clipDepth--;}
    }
}
