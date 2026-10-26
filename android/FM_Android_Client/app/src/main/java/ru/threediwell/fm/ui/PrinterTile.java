// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.drawable.RippleDrawable;
import android.text.TextUtils;
import android.view.*;
import android.widget.*;
import org.json.JSONObject;
import ru.threediwell.fm.i18n.I18n;

/** Native dashboard card using the same FM palette and spacing as warehouse actions. */
public final class PrinterTile extends LinearLayout {
    public final ImageView cover;
    private final LinearLayout heading;
    private final FmStyle style;
    private final TextView status,file,progressText;
    private final ProgressBar progress;
    private final String name,model;private String supplementary="";
    public PrinterTile(Context context){this(context,new FmStyle(context),new JSONObject(),null);}
    public PrinterTile(Context context,FmStyle style,JSONObject printer,Runnable open) {
        super(context);this.style=style;name=printer.optString("name");setOrientation(VERTICAL);
        setPadding(style.dp(10),style.dp(10),style.dp(10),style.dp(10));
        setBackground(new RippleDrawable(ColorStateList.valueOf(0x334DA6FF),style.box(style.card,18),null));
        LayoutParams bounds=new LayoutParams(-1,-2);bounds.setMargins(0,style.dp(3),0,style.dp(3));setLayoutParams(bounds);
        heading=new LinearLayout(context);heading.setGravity(Gravity.CENTER_VERTICAL);addView(heading);
        cover=new ImageView(context);cover.setScaleType(ImageView.ScaleType.FIT_CENTER);
        cover.setImageDrawable(new FmStyle.Icon("printer",style.muted));cover.setPadding(style.dp(5),style.dp(5),style.dp(5),style.dp(5));
        heading.addView(cover,new LayoutParams(style.dp(48),style.dp(48)));
        LinearLayout copy=new LinearLayout(context);copy.setOrientation(VERTICAL);copy.setPadding(style.dp(10),0,0,0);
        TextView title=style.label(name,16,style.text);title.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));if(open!=null){title.setMaxLines(2);title.setEllipsize(TextUtils.TruncateAt.END);}copy.addView(title);
        model=printer.optString("model");if(!model.isEmpty()){TextView v=style.label(model,13,style.muted);copy.addView(v);}
        heading.addView(copy,new LayoutParams(0,-2,1));
        status=style.label("",13,style.muted);copy.addView(status);
        file=style.label("",13,style.text);file.setPadding(0,style.dp(4),0,0);if(open!=null){file.setMaxLines(1);file.setEllipsize(TextUtils.TruncateAt.MIDDLE);}addView(file);
        progress=new ProgressBar(context,null,android.R.attr.progressBarStyleHorizontal);progress.setMax(100);
        progress.setProgressTintList(ColorStateList.valueOf(style.accent));progress.setProgressBackgroundTintList(ColorStateList.valueOf(style.border));
        LayoutParams bar=new LayoutParams(-1,style.dp(4));bar.topMargin=style.dp(6);addView(progress,bar);
        progressText=style.label("",13,style.muted);progressText.setPadding(0,style.dp(2),0,0);addView(progressText);
        if(open!=null){setOnClickListener(v->open.run());setFocusable(true);setAccessibilityDelegate(new View.AccessibilityDelegate(){
            @Override public void onInitializeAccessibilityNodeInfo(View host,android.view.accessibility.AccessibilityNodeInfo info){
                super.onInitializeAccessibilityNodeInfo(host,info);info.setClassName("android.widget.Button");
            }
        });for(View child:new View[]{heading,status,file,progress,progressText})child.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);}
        update("",style.muted,"",-1,"");
    }
    public void update(String state,int color,String filename,int percent,String remaining) {
        status.setText(state);status.setTextColor(color);
        file.setText(filename);file.setVisibility(filename.isEmpty()?GONE:VISIBLE);
        progress.setVisibility(percent<0?GONE:VISIBLE);progressText.setVisibility(percent<0?GONE:VISIBLE);
        if(percent>=0){progress.setProgress(percent);progressText.setText(String.format(java.util.Locale.forLanguageTag(I18n.language()),"%d%%%s",percent,remaining.isEmpty()?"":" · "+remaining));}
        if(isClickable())setContentDescription(name+", "+model+", "+state+(filename.isEmpty()?"":", "+filename)+(percent<0?"":", "+progressText.getText())+supplementary);
    }
    public void supplementary(String value){supplementary=value.isEmpty()?"":", "+value;}
    public void camera(Runnable open){if(isClickable()){heading.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);for(int i=0;i<heading.getChildCount();i++)heading.getChildAt(i).setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);}heading.addView(style.iconButton(I18n.t("Камера принтера"),"video",open));}
}
