// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.scan;

import org.junit.Test;
import static org.junit.Assert.*;
import org.json.*;
import ru.threediwell.fm.inventory.Labels;

public class ScanSafetyTest {
    private final AimWindow.Box bounds=new AimWindow.Box(20,20,120,120);
    private final String slot=Labels.slot("farm","p2s_07",2);
    private ScanPolicy policy(String kind)throws Exception {
        return new ScanPolicy(kind,"farm",new JSONArray().put(new JSONObject().put("code",slot).put("caption","P2S_07 · AMS 1 · Слот 3"))
                .put(new JSONObject().put("code",Labels.slot("farm","p2s_07",-1)).put("caption","P2S_07 · Внешний держатель")).toString());
    }
    @Test public void slotRequiresExplicitConfirmation()throws Exception{assertTrue(policy(ScanPolicy.SLOT).needsConfirmation(slot));}
    @Test public void snapshotHasHumanCaption()throws Exception{assertEquals("P2S_07 · AMS 1 · Слот 3",policy(ScanPolicy.SLOT).caption(slot));}
    @Test public void externalIsNotSlotZero()throws Exception{assertEquals("P2S_07 · Внешний держатель",policy(ScanPolicy.SLOT).caption(Labels.slot("farm","p2s_07",-1)));}
    @Test public void unknownSlotRejected()throws Exception{assertThrows(IllegalArgumentException.class,()->policy(ScanPolicy.SLOT).caption(Labels.slot("farm","p2s_07",0)));}
    @Test public void foreignFarmRejected()throws Exception{assertThrows(IllegalArgumentException.class,()->policy(ScanPolicy.SLOT).caption(Labels.slot("other","p2s_07",2)));}
    @Test public void spoolCannotSelectPosition()throws Exception{assertThrows(IllegalArgumentException.class,()->policy(ScanPolicy.SLOT).caption(Labels.spool("farm","s1")));}
    @Test public void barcodeCannotSelectPosition()throws Exception{assertThrows(IllegalArgumentException.class,()->policy(ScanPolicy.SLOT).caption("6938936710110"));}
    @Test public void vendorUrlCannotSelectPosition()throws Exception{assertThrows(IllegalArgumentException.class,()->policy(ScanPolicy.SLOT).caption("https://prusament.com/spool/123"));}
    @Test public void spoolModeRejectsSlot()throws Exception{assertThrows(IllegalArgumentException.class,()->policy(ScanPolicy.SPOOL).caption(slot));}
    @Test public void spoolModePreservesFactoryBarcode()throws Exception{assertEquals("0012345678",policy(ScanPolicy.SPOOL).caption("0012345678"));}
    @Test public void spoolModePreservesText()throws Exception{assertEquals("PB01056",policy(ScanPolicy.SPOOL).caption("PB01056"));}
    @Test public void ownSpoolNoExtraConfirmation()throws Exception{ScanPolicy p=policy(ScanPolicy.SPOOL);String s=Labels.spool("farm","s1");assertTrue(p.caption(s).contains("s1"));assertFalse(p.needsConfirmation(s));}
    @Test public void spoolRejectsForeignInternalLabel()throws Exception{assertThrows(IllegalArgumentException.class,()->policy(ScanPolicy.SPOOL).caption(Labels.spool("other","s1")));}
    @Test public void mixedUnbindStillConfirmsPositions()throws Exception{ScanPolicy p=policy(ScanPolicy.ANY);assertTrue(p.needsConfirmation(slot));assertEquals("PB01056",p.caption("PB01056"));assertNotNull(p.caption(slot));}
    @Test public void noServerNeverAcceptsInternalLabel(){assertThrows(IllegalArgumentException.class,()->new ScanPolicy(null,null,null).caption(slot));}
    @Test public void noCatalogNeverAcceptsPosition(){assertThrows(IllegalArgumentException.class,()->new ScanPolicy(ScanPolicy.SLOT,"farm",null).caption(slot));}
    @Test public void malformedCatalogFailsClosed(){assertThrows(IllegalArgumentException.class,()->new ScanPolicy(ScanPolicy.SLOT,"farm","garbage"));}
    @Test public void malformedPurposeFailsClosed(){assertThrows(IllegalArgumentException.class,()->new ScanPolicy("other","farm","[]"));}
    @Test public void firstFrameNeverAccepts(){assertFalse(new StableCode().observe(slot,bounds,100000));}
    @Test public void stableCodeNeeds700ms(){StableCode g=new StableCode();assertFalse(g.observe(slot,bounds,100));assertFalse(g.observe(slot,bounds,400));assertFalse(g.observe(slot,bounds,700));assertTrue(g.observe(slot,bounds,800));}
    @Test public void disappearanceResetsHold(){StableCode g=new StableCode();g.observe(slot,bounds,100);g.observe(slot,bounds,400);g.observe(null,null,600);assertFalse(g.observe(slot,bounds,900));}
    @Test public void anotherCodeResetsHold(){StableCode g=new StableCode();g.observe(slot,bounds,100);g.observe(slot,bounds,450);assertFalse(g.observe("neighbor",bounds,800));}
    @Test public void changingPhysicalQrWithSameValueResetsHold(){StableCode g=new StableCode();g.observe(slot,bounds,100);g.observe(slot,bounds,450);assertFalse(g.observe(slot,new AimWindow.Box(150,20,250,120),800));}
    @Test public void slowOldResultsDoNotMeetStability(){StableCode g=new StableCode();g.observe(slot,bounds,100);assertFalse(g.observe(slot,bounds,1000));assertFalse(g.observe(slot,bounds,1800));}
    @Test public void explicitResetRequiresNewHold(){StableCode g=new StableCode();g.observe(slot,bounds,100);g.observe(slot,bounds,400);g.reset();assertFalse(g.observe(slot,bounds,800));}
    @Test public void smallHandMovementAllowed(){StableCode g=new StableCode();g.observe(slot,bounds,100);g.observe(slot,new AimWindow.Box(23,21,123,121),450);assertTrue(g.observe(slot,bounds,800));}
    @Test public void timeGoingBackStartsOver(){StableCode g=new StableCode();g.observe(slot,bounds,1000);assertFalse(g.observe(slot,bounds,500));}
    @Test public void aimIsNarrowAndSquare(){AimWindow.Box b=AimWindow.inView(360,240,true);assertEquals(b.width(),b.height(),.01);assertTrue(b.width()<180);assertEquals(180,(b.left()+b.right())/2,.01);}
    @Test public void barcodeAimIsWider(){assertTrue(AimWindow.inView(360,240,false).width()>AimWindow.inView(360,240,true).width());}
    @Test public void portraitAndLandscapeAimStayInside(){for(int[] size:new int[][]{{360,240},{400,300},{240,400},{200,180}})for(boolean narrow:new boolean[]{true,false}){AimWindow.Box b=AimWindow.inView(size[0],size[1],narrow);assertTrue(new AimWindow.Box(0,0,size[0],size[1]).contains(b));}}
    @Test public void neighboringCodeOutsideAimRejected(){AimWindow.Box b=AimWindow.inView(360,240,true);assertTrue(b.contains(new AimWindow.Box(140,80,220,160)));assertFalse(b.contains(new AimWindow.Box(20,80,95,160)));assertFalse(b.contains(new AimWindow.Box(265,80,340,160)));}
    @Test public void crossingEdgeRejected(){assertFalse(bounds.contains(new AimWindow.Box(10,40,70,80)));}
    @Test public void roundingNeverEnlargesCrop(){AimWindow.Box b=AimWindow.inward(new AimWindow.Box(10.2f,12.7f,200.9f,150.4f),300,200);assertEquals(new AimWindow.Box(11,13,200,150),b);}
    @Test public void cropClampsToActualImage(){assertEquals(new AimWindow.Box(0,0,320,240),AimWindow.inward(new AimWindow.Box(-10,-20,400,300),320,240));}
    @Test public void zeroPreviewFailsClosed(){assertThrows(IllegalArgumentException.class,()->AimWindow.inView(0,240,true));}
    @Test public void invalidCropFailsClosed(){assertThrows(IllegalArgumentException.class,()->AimWindow.inward(new AimWindow.Box(500,500,600,600),320,240));}
}
