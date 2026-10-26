// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui.intro;

import ru.threediwell.fm.i18n.I18n;
import org.json.*;

/** Small vector asset evaluated from the approved Blender v06; no video/bitmap frames. */
public final class IntroModel {
    public static final long DURATION_MS=7000;
    public final float[][][] paths;
    public final float[][] frames;
    public final int[][][] surfaceColors;
    public final float initialCenter,gate;
    public IntroModel(String json) throws JSONException {
        JSONObject root=new JSONObject(json);
        if(root.getInt("version")!=6||root.getInt("fps")!=24||root.getLong("durationMs")!=DURATION_MS)
            throw new JSONException("Unsupported intro data");
        initialCenter=(float)root.getDouble("initialCenter");gate=(float)root.getDouble("gate");
        JSONArray shapes=root.getJSONArray("paths");paths=new float[shapes.length()][][];
        if(paths.length!=11)throw new JSONException("Original logo needs 11 paths");
        for(int i=0;i<paths.length;i++) {
            JSONArray contours=shapes.getJSONArray(i);paths[i]=new float[contours.length()][];
            for(int j=0;j<contours.length();j++) {
                paths[i][j]=numbers(contours.getJSONArray(j));
                if(paths[i][j].length<12||paths[i][j].length%6!=0)throw new JSONException("Invalid contour");
            }
        }
        JSONArray timeline=root.getJSONArray("frames"),colors=root.getJSONArray("surfaceColors");
        if(timeline.length()!=168||colors.length()!=168)throw new JSONException("Invalid timeline");
        frames=new float[168][];surfaceColors=new int[168][4][3];
        for(int i=0;i<168;i++) {
            frames[i]=numbers(timeline.getJSONArray(i));if(frames[i].length!=29)throw new JSONException("Invalid frame");
            for(int j=0;j<4;j++)for(int k=0;k<3;k++)surfaceColors[i][j][k]=0xFF000000|colors.getJSONArray(i).getJSONArray(j).getInt(k);
        }
    }
    private static float[] numbers(JSONArray a) throws JSONException {
        float[] out=new float[a.length()];for(int i=0;i<out.length;i++) {
            out[i]=(float)a.getDouble(i);if(!Float.isFinite(out[i]))throw new JSONException("Nonfinite coordinate");
        }return out;
    }
    public static float frameAt(long ms) {return Math.max(1,Math.min(168,1+ms*24f/1000));}
    public void sample(float frame,float[] into) {
        float at=Math.max(0,Math.min(167,frame-1));int a=(int)at,b=Math.min(167,a+1);float t=at-a;
        for(int i=0;i<into.length;i++)into[i]=frames[a][i]+(frames[b][i]-frames[a][i])*t;
    }
    public int color(float frame,int shape,int stop) {
        float at=Math.max(0,Math.min(167,frame-1));int a=(int)at,b=Math.min(167,a+1);
        return blend(surfaceColors[a][shape][stop],surfaceColors[b][shape][stop],at-a);
    }
    public static int blend(int a,int b,float t) {
        t=Math.max(0,Math.min(1,t));int out=0xFF000000;
        for(int shift=16;shift>=0;shift-=8)out|=Math.round(((a>>shift)&255)*(1-t)+((b>>shift)&255)*t)<<shift;
        return out;
    }
    public static String greeting(int hour) {
        if(hour<0||hour>23)throw new IllegalArgumentException("hour");
        return hour<6?I18n.t("Спокойной ночи"):hour<12?I18n.t("Доброе утро"):hour<18?I18n.t("Хорошего дня"):I18n.t("Хорошего вечера");
    }
    public static String wish(int hour) {
        if(hour<0||hour>23)throw new IllegalArgumentException("hour");
        return hour<6?I18n.t("и стабильности процессу!"):hour<12?I18n.t("и пусть всё начнётся ровно!"):hour<18?I18n.t("и точного результата!"):I18n.t("и реализации планов!");
    }
}
