// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;
import android.content.Context;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.ImageView;
import android.widget.LinearLayout;
import ru.threediwell.fm.R;

/** Compact v5 toolbar; large fonts move the status row above the trademark. */
public final class BrandHeader extends LinearLayout {
    private final FmStyle style;private final View left;private final LinearLayout right;
    private final int rightWidth;private Boolean stackedLayout;private final boolean emptyLeft;
    public BrandHeader(Context context){this(context,new FmStyle(context));}
    public BrandHeader(Context context,FmStyle style){this(context,style,null,null);}
    public BrandHeader(Context context,FmStyle style,View leading,View notifications){
        super(context);this.style=style;setGravity(Gravity.CENTER_VERTICAL);setMinimumHeight(style.dp(56));
        setLayoutParams(new LayoutParams(-1,-2));emptyLeft=leading==null;left=emptyLeft?new View(context):leading;
        // A zero-height spacer cannot grow during ScrollView.fillViewport's second measure.
        addView(left,new LayoutParams(0,emptyLeft?0:-2,1));
        right=new LinearLayout(context);right.setGravity(Gravity.CENTER_VERTICAL);
        if(notifications!=null){LayoutParams params=new LayoutParams(style.dp(48),style.dp(48));params.setMarginEnd(style.dp(9));right.addView(notifications,params);}
        ImageView wordmark=new ImageView(context);wordmark.setImageResource(R.drawable.ic_3diwell);
        wordmark.setScaleType(ImageView.ScaleType.FIT_CENTER);wordmark.setContentDescription("3diwell");
        boolean light=!FmStyle.isDark(context);int logoWidth=style.dp(light?100:90);
        if(light){GradientDrawable backing=new GradientDrawable();backing.setColor(0xFF18181B);backing.setCornerRadius(style.dp(8));wordmark.setBackground(backing);wordmark.setPadding(style.dp(7),style.dp(5),style.dp(7),style.dp(5));}
        right.addView(wordmark,new LayoutParams(logoWidth,style.dp(light?34:28)));
        rightWidth=logoWidth+(notifications==null?0:style.dp(57));addView(right,new LayoutParams(rightWidth,style.dp(48)));
    }
    @Override protected void onMeasure(int widthMeasureSpec,int heightMeasureSpec){
        int available=MeasureSpec.getSize(widthMeasureSpec)-getPaddingLeft()-getPaddingRight();
        left.measure(MeasureSpec.makeMeasureSpec(0,MeasureSpec.UNSPECIFIED),MeasureSpec.makeMeasureSpec(0,MeasureSpec.UNSPECIFIED));
        boolean stacked=!emptyLeft&&left.getMeasuredWidth()+rightWidth+style.dp(6)>available;
        if(stackedLayout==null||stackedLayout!=stacked){
            stackedLayout=stacked;setOrientation(stacked?VERTICAL:HORIZONTAL);
            LayoutParams lp=new LayoutParams(stacked?-1:0,emptyLeft?0:-2,stacked?0:1);left.setLayoutParams(lp);
            LayoutParams rp=new LayoutParams(rightWidth,style.dp(48));rp.gravity=Gravity.END;rp.topMargin=stacked?style.dp(2):0;right.setLayoutParams(rp);
        }
        super.onMeasure(widthMeasureSpec,heightMeasureSpec);
    }
}
