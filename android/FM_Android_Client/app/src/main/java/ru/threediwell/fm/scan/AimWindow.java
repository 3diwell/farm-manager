// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.scan;

/** Geometry shared by the drawn aim and recognition crop. No Android dependency. */
public final class AimWindow {
    public record Box(float left,float top,float right,float bottom) {
        public float width(){return right-left;}
        public float height(){return bottom-top;}
        public boolean contains(Box b){return b.width()>0&&b.height()>0&&b.left>=left&&b.top>=top&&b.right<=right&&b.bottom<=bottom;}
        public float overlap(Box b) {
            float area=Math.max(0,Math.min(right,b.right)-Math.max(left,b.left))*Math.max(0,Math.min(bottom,b.bottom)-Math.max(top,b.top));
            float union=width()*height()+b.width()*b.height()-area;
            return union>0?area/union:0;
        }
    }
    public static Box inView(int width,int height,boolean narrow) {
        if(width<=0||height<=0)throw new IllegalArgumentException("Camera layout is not ready");
        float h=Math.min(width,height)*.68f,w=narrow?h:width*.86f;
        return new Box((width-w)/2,(height-h)/2,(width+w)/2,(height+h)/2);
    }
    /** Round inward: no pixel outside the mapped aim is sent to recognition. */
    public static Box inward(Box box,int width,int height) {
        Box b=new Box(Math.max(0,(float)Math.ceil(box.left)),Math.max(0,(float)Math.ceil(box.top)),
                Math.min(width,(float)Math.floor(box.right)),Math.min(height,(float)Math.floor(box.bottom)));
        if(b.width()<16||b.height()<16)throw new IllegalArgumentException("Recognition crop too small");
        return b;
    }
}
