// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;
import android.graphics.*;
import android.graphics.drawable.Drawable;

/** Translucent face, thin rim, reflected light and selected glow. Does not blur child text. */
public final class GlassDrawable extends Drawable {
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF face=new RectF(),inner=new RectF();
    private final float density,radius;
    private final boolean dark,navigation,selectionOnly;
    private boolean selected,enabled=true;
    private int alpha=255;
    private Shader fill,rim,shine,edgeBloom,edgeLight;
    private float selectionCenter=-1,selectionSpan=.2f;
    public GlassDrawable(boolean dark,float density,float radius,boolean navigation,boolean selectionOnly) {
        this.dark=dark;this.density=density;this.radius=radius*density;this.navigation=navigation;this.selectionOnly=selectionOnly;
    }
    @Override protected void onBoundsChange(Rect b) {
        float inset=(navigation?3:1)*density;face.set(b.left+inset,b.top+inset,b.right-inset,b.bottom-inset);
        if(face.width()<=0||face.height()<=0)return;
        inner.set(face);inner.inset(density,density);
        fill=new LinearGradient(face.left,face.top,face.right,face.bottom,dark?new int[]{0x20DBE5FF,0x0A99ACCF,0x119FB1D3}:new int[]{0xBEFFFFFF,0x25D2DDEB,0x77FFFFFF},new float[]{0,.48f,1},Shader.TileMode.CLAMP);
        rim=new LinearGradient(face.left,face.top,face.right,face.bottom,dark?new int[]{0x9AF1F5FF,0x38D7E1F6,0x10D7E1F6,0x48D7E1F6}:new int[]{0xFFFFFFFF,0xADF9FCFF,0x25A8B7CB,0x67B5C4D9},new float[]{0,.34f,.68f,1},Shader.TileMode.CLAMP);
        shine=new LinearGradient(face.left,face.top,face.right,face.top,new int[]{0x00FFFFFF,dark?0x33FFFFFF:0xA0FFFFFF,0x00FFFFFF},new float[]{0,.35f,1},Shader.TileMode.CLAMP);
        updateEdgeLight();
    }
    /** Position comes from the measured selected tab, including layouts with hidden modules. */
    public void setNavigationSelection(float center,float span){
        float next=center<0?-1:Math.max(0,Math.min(1,center));
        if(selectionCenter==next&&selectionSpan==span)return;
        selectionCenter=next;selectionSpan=Math.max(.12f,span);updateEdgeLight();invalidateSelf();
    }
    private void updateEdgeLight(){
        if(face.isEmpty()||selectionCenter<0){edgeBloom=null;edgeLight=null;return;}
        float x=getBounds().left+selectionCenter*getBounds().width(),y=face.bottom;
        float spread=Math.max(45*density,face.width()*selectionSpan*.82f);
        edgeBloom=new RadialGradient(x,y,spread,dark?new int[]{0x62617DF2,0x263E72C5,0x003D6DCF}:new int[]{0x35426ED0,0x126887B9,0x006887B9},new float[]{0,.4f,1},Shader.TileMode.CLAMP);
        Matrix ellipse=new Matrix();ellipse.setScale(1,.32f,x,y);edgeBloom.setLocalMatrix(ellipse);
        edgeLight=new RadialGradient(x,y,spread,dark?new int[]{0xFFC2CCFF,0xCA6879E9,0x505178C2,0x005178C2}:new int[]{0xFF728ECA,0xBB5E7AC2,0x324F85BD,0x004F85BD},new float[]{0,.3f,.66f,1},Shader.TileMode.CLAMP);
        Matrix rimEllipse=new Matrix();rimEllipse.setScale(1,.27f,x,y);edgeLight.setLocalMatrix(rimEllipse);
    }
    @Override public void draw(Canvas canvas) {
        if(face.isEmpty())return;float rad=Math.min(radius,Math.min(face.width(),face.height())/2);
        paint.setAlpha(enabled?alpha:Math.round(alpha*.45f));
        if(!selectionOnly) {
            paint.setStyle(Paint.Style.FILL);paint.setShader(fill);canvas.drawRoundRect(face,rad,rad,paint);
            paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(.75f*density);paint.setShader(rim);canvas.drawRoundRect(face,rad,rad,paint);
            paint.setShader(shine);paint.setStrokeWidth(.6f*density);canvas.drawRoundRect(inner,Math.max(0,rad-density),Math.max(0,rad-density),paint);
        }
        if(navigation&&edgeBloom!=null) {
            paint.setStyle(Paint.Style.FILL);paint.setShader(edgeBloom);canvas.drawRoundRect(face,rad,rad,paint);
            // A broad reflection plus a fine illuminated rim both follow the full capsule path.
            // Transparent shader stops leave the rest of the perimeter neutral.
            paint.setStyle(Paint.Style.STROKE);paint.setShader(edgeLight);
            int opacity=enabled?alpha:Math.round(alpha*.45f);
            paint.setStrokeWidth(5*density);paint.setAlpha(Math.round(opacity*.09f));canvas.drawRoundRect(face,rad,rad,paint);
            paint.setStrokeWidth(2.7f*density);paint.setAlpha(Math.round(opacity*.19f));canvas.drawRoundRect(face,rad,rad,paint);
            paint.setStrokeWidth(1.1f*density);paint.setAlpha(Math.round(opacity*.88f));canvas.drawRoundRect(face,rad,rad,paint);
            paint.setAlpha(opacity);
        }
        paint.setShader(null);
    }
    @Override public boolean isStateful(){return true;}
    @Override protected boolean onStateChange(int[] state){
        boolean nextSelected=false,nextEnabled=state.length==0;
        for(int s:state){if(s==android.R.attr.state_selected||s==android.R.attr.state_activated)nextSelected=true;if(s==android.R.attr.state_enabled)nextEnabled=true;}
        boolean changed=selected!=nextSelected||enabled!=nextEnabled;selected=nextSelected;enabled=nextEnabled;if(changed)invalidateSelf();return changed;
    }
    @Override public void setAlpha(int value){alpha=value;invalidateSelf();}
    @Override public void setColorFilter(ColorFilter filter){paint.setColorFilter(filter);invalidateSelf();}
    @Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
}
