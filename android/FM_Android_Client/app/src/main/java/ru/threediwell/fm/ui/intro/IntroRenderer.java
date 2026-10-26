// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui.intro;

/** Platform-independent vector drawing. Coordinates use the v06 720x1280 camera. */
public final class IntroRenderer {
    public interface Surface {
        void begin();void move(float x,float y);void line(float x,float y);
        void cubic(float a,float b,float c,float d,float e,float f);void close();
        void fill(int top,int middle,int bottom,float alpha);void stroke(int color,float width,float alpha);
        void clipLeft(float x);void unclip();
    }
    private static final int[] PARTS={8,9,10,1};
    private final IntroModel model;
    private final float[] values=new float[29],point=new float[6];
    private final float[][][] samples=new float[11][][];
    public IntroRenderer(IntroModel model) {
        this.model=model;
        for(int i=0;i<11;i++) {
            samples[i]=new float[model.paths[i].length][];
            for(int k=0;k<samples[i].length;k++) {
                float[] p=model.paths[i][k];int count=p.length/6;samples[i][k]=new float[count*12*2];
                for(int j=0;j<count;j++)for(int step=0;step<12;step++) {
                    float t=step/12f,u=1-t;int a=j*6,b=((j+1)%count)*6,d=(j*12+step)*2;
                    for(int xy=0;xy<2;xy++)samples[i][k][d+xy]=u*u*u*p[a+xy]+3*u*u*t*p[a+4+xy]+3*u*t*t*p[b+2+xy]+t*t*t*p[b+xy];
                }
            }
        }
    }
    private void project(float x,float y,float z,boolean engineering,int idx,int out) {
        if(engineering) {
            x+=model.initialCenter+(idx==9?-1.2f:0);
            float xx=values[2]*x+values[3]*y+values[4]*z+values[1];
            float yy=values[5]*x+values[6]*y+values[7]*z;
            z=values[8]*x+values[9]*y+values[10]*z;x=xx;y=yy;
        } else x+=values[18+idx];
        float scale=720/values[0]*30/(30-z);
        point[out]=360+x*scale;point[out+1]=640-y*scale;
    }
    private void path(Surface c,int idx,float z,boolean engineering) {
        c.begin();
        for(float[] p:model.paths[idx]) {
            project(p[0],p[1],z,engineering,idx,0);c.move(point[0],point[1]);int n=p.length/6;
            for(int j=0;j<n;j++) {
                int a=j*6,b=((j+1)%n)*6;
                project(p[a+4],p[a+5],z,engineering,idx,0);project(p[b+2],p[b+3],z,engineering,idx,2);project(p[b],p[b+1],z,engineering,idx,4);
                c.cubic(point[0],point[1],point[2],point[3],point[4],point[5]);
            }c.close();
        }
    }
    public void draw(Surface c,long ms) {
        float frame=IntroModel.frameAt(ms);model.sample(frame,values);
        if(frame<7)return;
        if(frame<73) {
            float alpha=values[13],front=values[11],back=values[12];
            for(int part=0;part<4;part++) {
                int idx=PARTS[part],brand=idx==1?0xFFFFFFFF:0xFFEA5E20;
                int top=model.color(frame,part,0),mid=model.color(frame,part,1),bottom=model.color(frame,part,2);
                path(c,idx,back,true);c.fill(shade(mid,.22f),shade(mid,.35f),shade(mid,.18f),alpha);
                c.stroke(shade(brand,.45f),.42f,alpha*.7f);
                // Dense ribs on a solid side surface; front face occludes rear lines.
                c.begin();
                for(float[] contour:samples[idx])for(int j=0;j<contour.length;j+=2) {
                    int next=(j+2)%contour.length;
                    project(contour[j],contour[j+1],back,true,idx,0);c.move(point[0],point[1]);
                    project(contour[next],contour[next+1],back,true,idx,0);c.line(point[0],point[1]);
                    project(contour[next],contour[next+1],front,true,idx,0);c.line(point[0],point[1]);
                    project(contour[j],contour[j+1],front,true,idx,0);c.line(point[0],point[1]);c.close();
                }
                int sideLight=IntroModel.blend(shade(brand,.35f),mid,values[14]);
                c.fill(shade(sideLight,.5f),shade(sideLight,.32f),shade(sideLight,.14f),alpha);
                c.begin();
                for(float[] contour:samples[idx]) {
                    float distance=0,lastX=contour[0],lastY=contour[1];
                    for(int j=2;j<contour.length;j+=2) {
                        float x=contour[j],y=contour[j+1];distance+=(float)Math.hypot(x-lastX,y-lastY);lastX=x;lastY=y;
                        if(distance<.055f)continue;distance=0;
                        project(x,y,back,true,idx,0);c.move(point[0],point[1]);project(x,y,front,true,idx,0);c.line(point[0],point[1]);
                    }
                }
                c.stroke(shade(brand,.65f),.48f,alpha*.7f);
                path(c,idx,front,true);c.fill(top,mid,bottom,alpha);
                c.begin();
                for(float[] contour:samples[idx]) {
                    int end=Math.max(2,(int)(contour.length/2*values[15])*2);
                    for(int j=0;j<Math.min(end,contour.length);j+=2) {
                        project(contour[j],contour[j+1],front+.01f,true,idx,0);
                        if(j==0)c.move(point[0],point[1]);else c.line(point[0],point[1]);
                    }
                    if(values[15]>=.999f)c.close();
                }
                c.stroke(brand,.8f,alpha*(1-values[14])*.9f);
            }
        } else {
            if(frame>=98) {
                c.clipLeft(360+model.gate*720/values[0]);
                for(int i=7;i>=0;i--)if(i!=1) {path(c,i,0,false);int color=i>=7?0xFFEA5E20:0xFFFFFFFF;c.fill(color,color,color,1);}
                c.unclip();
            }
            for(int idx:PARTS) {path(c,idx,0,false);int color=idx==1?0xFFFFFFFF:0xFFEA5E20;c.fill(color,color,color,1);}
        }
    }
    private static int shade(int color,float level) {return IntroModel.blend(0xFF000000,color,level);}
}
