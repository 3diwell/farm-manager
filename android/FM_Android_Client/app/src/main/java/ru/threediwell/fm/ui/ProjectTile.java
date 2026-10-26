// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;

import android.content.*;
import android.content.res.ColorStateList;
import android.graphics.*;
import android.graphics.drawable.*;
import android.view.*;
import android.widget.*;
import org.json.JSONObject;
import ru.threediwell.fm.farm.ProjectProgress;
import ru.threediwell.fm.i18n.I18n;

public final class ProjectTile extends LinearLayout {
    public ProjectTile(Context context){this(context,new FmStyle(context),new JSONObject(),()->{});}
    public ProjectTile(Context context,FmStyle style,JSONObject project,Runnable open){
        super(context);ProjectProgress progress=ProjectProgress.of(project);setOrientation(VERTICAL);setPadding(style.dp(12),style.dp(12),style.dp(12),style.dp(12));
        setBackground(new RippleDrawable(ColorStateList.valueOf(0x334DA6FF),new Frame(style,progress.percent()),null));
        LayoutParams bounds=new LayoutParams(-1,-2);bounds.setMargins(0,style.dp(4),0,style.dp(4));setLayoutParams(bounds);setMinimumHeight(style.dp(80));
        LinearLayout head=new LinearLayout(context);head.setGravity(Gravity.CENTER_VERTICAL);addView(head);
        String name=project.optString("name");TextView title=style.label(name,16,style.text);title.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));title.setPadding(0,0,style.dp(8),0);head.addView(title,new LayoutParams(0,-2,1));
        TextView pct=style.label(progress.percent()+"%",16,style.accent);pct.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));head.addView(pct);
        String counts=progress.done()+" / "+progress.total()+I18n.t(" деталей выполнено");TextView sub=style.label(counts,13,style.muted);sub.setPadding(0,style.dp(6),0,0);addView(sub);
        TextView files=style.label(I18n.t("Файлов: ")+project.optInt("files_count"),13,style.muted);addView(files);
        setFocusable(true);setOnClickListener(v->open.run());setContentDescription(name+", "+progress.percent()+"%, "+counts);
        setAccessibilityDelegate(new View.AccessibilityDelegate(){@Override public void onInitializeAccessibilityNodeInfo(View host,android.view.accessibility.AccessibilityNodeInfo info){super.onInitializeAccessibilityNodeInfo(host,info);info.setClassName("android.widget.Button");}});
        for(int i=0;i<getChildCount();i++)getChildAt(i).setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
    }
    /** Clockwise length along the entire rounded outline, matching FM plan-ring. */
    private static final class Frame extends Drawable {
        private final FmStyle style;private final int percent;private final Paint paint=new Paint(3);
        Frame(FmStyle style,int percent){this.style=style;this.percent=percent;}
        @Override public void draw(Canvas c){RectF b=new RectF(getBounds());float inset=style.dp(2);b.inset(inset,inset);float r=Math.min(style.dp(14),Math.min(b.width(),b.height())/2);paint.setStyle(Paint.Style.FILL);paint.setColor(style.card);c.drawRoundRect(b,r,r,paint);paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(style.dp(1));paint.setColor(style.border);c.drawRoundRect(b,r,r,paint);if(percent<=0)return;
            Path path=new Path();path.moveTo(b.left+r,b.top);path.lineTo(b.right-r,b.top);path.arcTo(new RectF(b.right-2*r,b.top,b.right,b.top+2*r),270,90);path.lineTo(b.right,b.bottom-r);path.arcTo(new RectF(b.right-2*r,b.bottom-2*r,b.right,b.bottom),0,90);path.lineTo(b.left+r,b.bottom);path.arcTo(new RectF(b.left,b.bottom-2*r,b.left+2*r,b.bottom),90,90);path.lineTo(b.left,b.top+r);path.arcTo(new RectF(b.left,b.top,b.left+2*r,b.top+2*r),180,90);path.close();
            Path segment=new Path();PathMeasure measure=new PathMeasure(path,false);measure.getSegment(0,measure.getLength()*percent/100f,segment,true);if(percent==100)segment.close();paint.setColor(style.accent);paint.setStrokeWidth(style.dp(2));paint.setStrokeCap(Paint.Cap.ROUND);c.drawPath(segment,paint);
        }
        @Override public void setAlpha(int a){paint.setAlpha(a);}
        @Override public void setColorFilter(ColorFilter f){paint.setColorFilter(f);}
        @Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }
}
