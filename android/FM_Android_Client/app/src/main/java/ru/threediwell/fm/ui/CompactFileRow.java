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
import ru.threediwell.fm.farm.FarmSort;
import ru.threediwell.fm.i18n.I18n;

/** Details and print have separate accessible targets: opening a row never starts a print. */
public final class CompactFileRow extends LinearLayout {
    public final ImageView thumbnail;
    public CompactFileRow(Context context){this(context,new FmStyle(context),new JSONObject(),"",()->{},null,false);}
    public CompactFileRow(Context context,FmStyle style,JSONObject file,String summary,Runnable details,Runnable print,boolean blocked) {
        super(context);setGravity(Gravity.CENTER_VERTICAL);setPadding(style.dp(8),style.dp(8),style.dp(8),style.dp(8));
        setBackground(style.box(style.card,14));LayoutParams outer=new LayoutParams(-1,-2);outer.setMargins(0,style.dp(3),0,style.dp(3));setLayoutParams(outer);
        LinearLayout main=new LinearLayout(context);main.setGravity(Gravity.CENTER_VERTICAL);main.setMinimumHeight(style.dp(64));
        main.setBackground(new RippleDrawable(ColorStateList.valueOf(0x334DA6FF),null,null));main.setFocusable(true);main.setOnClickListener(v->details.run());
        thumbnail=new ImageView(context);thumbnail.setImageDrawable(new FmStyle.Icon("file",style.muted));thumbnail.setScaleType(ImageView.ScaleType.FIT_CENTER);thumbnail.setPadding(style.dp(4),style.dp(4),style.dp(4),style.dp(4));
        main.addView(thumbnail,new LayoutParams(style.dp(48),style.dp(48)));
        LinearLayout copy=new LinearLayout(context);copy.setOrientation(VERTICAL);copy.setPadding(style.dp(8),0,style.dp(8),0);
        TextView name=style.label(file.optString("filename"),16,style.text);name.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));name.setMaxLines(2);name.setEllipsize(TextUtils.TruncateAt.MIDDLE);copy.addView(name);
        if(!summary.isEmpty()){TextView sub=style.label(summary,13,style.muted);sub.setMaxLines(1);sub.setEllipsize(TextUtils.TruncateAt.END);copy.addView(sub);}
        String caption=FarmSort.fileCaption(file);int color=switch(FarmSort.fileState(file)){case READY,COMPLETE->style.success;case PRINTING->style.accent;default->style.warning;};
        TextView status=style.label(caption,13,color);copy.addView(status);main.addView(copy,new LayoutParams(0,-2,1));addView(main,new LayoutParams(0,-2,1));
        main.setContentDescription(file.optString("filename")+", "+summary+", "+caption+", "+I18n.t("Сведения о файле"));
        main.setAccessibilityDelegate(new View.AccessibilityDelegate(){@Override public void onInitializeAccessibilityNodeInfo(View host,android.view.accessibility.AccessibilityNodeInfo info){super.onInitializeAccessibilityNodeInfo(host,info);info.setClassName("android.widget.Button");}});
        thumbnail.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);copy.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        if(print!=null){String description=(blocked?I18n.t("Сначала проверьте отправку"):I18n.t("На печать"))+": "+file.optString("filename");ImageButton b=style.iconButton(description,"send_print",print);b.setEnabled(!blocked);addView(b);}
        else {ImageView arrow=new ImageView(context);arrow.setImageDrawable(new FmStyle.Icon("forward",style.muted));arrow.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);addView(arrow,new LayoutParams(style.dp(16),style.dp(24)));}
    }
}
