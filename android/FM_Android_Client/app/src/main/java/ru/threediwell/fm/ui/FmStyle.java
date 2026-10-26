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
import android.view.Gravity;
import android.widget.*;
import ru.threediwell.fm.R;
import ru.threediwell.fm.i18n.I18n;

/** Палитра штатного FM; нативные элементы и читаемые размеры для телефона. */
public final class FmStyle {
    public final int bg,card,text,muted,border,accent,success,warning;
    private final Context context;
    public FmStyle(Context context) {
        this.context=context; boolean dark=isDark(context);
        bg=Color.parseColor(dark?"#18181B":"#F3F4F6"); card=Color.parseColor(dark?"#27272A":"#FFFFFF");
        text=Color.parseColor(dark?"#E5E7EB":"#1F2329"); muted=Color.parseColor(dark?"#AEB5C1":"#59616D");
        border=Color.parseColor(dark?"#3F3F46":"#D4D8DE"); accent=Color.parseColor(dark?"#4DA6FF":"#1769AA");
        success=Color.parseColor(dark?"#65D69B":"#187944");
        warning=Color.parseColor(dark?"#F4BE62":"#875600");
    }
    public static boolean isDark(Context c) { return c.getSharedPreferences("fm-client",0).getBoolean("dark",true); }
    public static int theme(Context c) { return isDark(c)?R.style.FmDark:R.style.FmLight; }
    public void systemBars(android.app.Activity a,android.view.View root) {
        a.getWindow().setStatusBarColor(bg);
        a.getWindow().setNavigationBarColor(android.os.Build.VERSION.SDK_INT>=27?bg:0xFF18181B);
        androidx.core.view.WindowInsetsControllerCompat bars=new androidx.core.view.WindowInsetsControllerCompat(a.getWindow(),root);
        bars.setAppearanceLightStatusBars(!isDark(context));bars.setAppearanceLightNavigationBars(!isDark(context));
    }
    public int dp(int n) { return Math.round(n*context.getResources().getDisplayMetrics().density); }
    public GradientDrawable box(int color,int radius) {
        GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));d.setStroke(dp(1),border);return d;
    }
    public int glyphColor(){return isDark(context)?0xFFF4F6FC:0xFF3F4855;}
    public GlassDrawable glass(int radius){return new GlassDrawable(isDark(context),context.getResources().getDisplayMetrics().density,radius,false,false);}
    public void navigationBar(LinearLayout nav){
        nav.setPadding(dp(5),dp(5),dp(5),dp(5));
        nav.setBackground(new GlassDrawable(isDark(context),context.getResources().getDisplayMetrics().density,28,true,false));
        nav.addOnLayoutChangeListener((view,left,top,right,bottom,oldLeft,oldTop,oldRight,oldBottom)->{
            GlassDrawable surface=(GlassDrawable)nav.getBackground();float center=-1,span=0;
            for(int i=0;i<nav.getChildCount();i++){
                android.view.View item=nav.getChildAt(i);
                if(item.isSelected()&&item.getVisibility()==android.view.View.VISIBLE&&nav.getWidth()>0){
                    center=(item.getLeft()+item.getWidth()*.5f)/nav.getWidth();span=(float)item.getWidth()/nav.getWidth();break;
                }
            }
            surface.setNavigationSelection(center,span);
        });
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(dp(8),dp(6),dp(8),dp(6));nav.setLayoutParams(p);
    }
    private RippleDrawable glassRipple(int radius){
        GradientDrawable mask=new GradientDrawable();mask.setColor(Color.WHITE);mask.setCornerRadius(dp(radius));
        return new RippleDrawable(ColorStateList.valueOf(isDark(context)?0x224DA6FF:0x221769AA),glass(radius),mask);
    }
    public TextView label(String value,int size,int color) {
        TextView v=new TextView(context);v.setText(value);v.setTextSize(size);v.setTextColor(color);v.setFontFeatureSettings("kern");return v;
    }
    public void button(Button b,boolean primary) {
        b.setAllCaps(false);b.setTextSize(15);b.setMinHeight(dp(primary?56:48));b.setMinimumHeight(dp(primary?56:48));
        b.setTextColor(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled},new int[]{}},new int[]{muted,text}));
        b.setGravity(Gravity.CENTER_VERTICAL|Gravity.CENTER_HORIZONTAL);b.setPadding(dp(16),dp(10),dp(16),dp(10));
        b.setBackgroundTintList(null);b.setBackground(glassRipple(999));
        b.setStateListAnimator(null);
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,dp(5),0,dp(5));b.setLayoutParams(p);
    }
    /** Native FM cards: icon tile, clear title/subtitle hierarchy, accessible single action. */
    public LinearLayout actionCard(String title,String subtitle,String kind,boolean primary) {
        int foreground=text;
        LinearLayout row=new LinearLayout(context);row.setGravity(Gravity.CENTER_VERTICAL);row.setPadding(dp(14),dp(14),dp(14),dp(14));
        row.setMinimumHeight(dp(80));row.setBackground(new RippleDrawable(ColorStateList.valueOf(0x334DA6FF),box(card,18),null));
        LinearLayout.LayoutParams rp=new LinearLayout.LayoutParams(-1,-2);rp.setMargins(0,dp(5),0,dp(5));row.setLayoutParams(rp);
        TextView tile=label("",16,foreground);tile.setGravity(Gravity.CENTER);
        tile.setBackground(glass(999));
        Icon icon=new Icon(kind,glyphColor());icon.setBounds(0,0,dp(24),dp(24));
        tile.setCompoundDrawables(null,icon,null,null);tile.setPadding(0,dp(10),0,0);row.addView(tile,new LinearLayout.LayoutParams(dp(44),dp(44)));
        LinearLayout copy=new LinearLayout(context);copy.setOrientation(LinearLayout.VERTICAL);copy.setPadding(dp(14),0,0,0);
        TextView heading=label(title,17,foreground);heading.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));copy.addView(heading);
        if(!subtitle.isEmpty()){TextView sub=label(subtitle,13,muted);sub.setPadding(0,dp(5),0,0);sub.setLineSpacing(dp(2),1);copy.addView(sub);}
        row.addView(copy,new LinearLayout.LayoutParams(0,-2,1));row.setClickable(true);row.setFocusable(true);
        row.setContentDescription(title+(subtitle.isEmpty()?"":", "+subtitle));
        row.setAccessibilityDelegate(new android.view.View.AccessibilityDelegate(){
            @Override public void onInitializeAccessibilityNodeInfo(android.view.View host,android.view.accessibility.AccessibilityNodeInfo info){
                super.onInitializeAccessibilityNodeInfo(host,info);if(host.isClickable())info.setClassName("android.widget.Button");
            }
        });
        tile.setImportantForAccessibility(android.view.View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        copy.setImportantForAccessibility(android.view.View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        return row;
    }
    public void icon(TextView v,String kind,int color) {
        Icon d=new Icon(kind,color);d.setBounds(0,0,dp(24),dp(24));v.setCompoundDrawables(d,null,null,null);v.setCompoundDrawablePadding(dp(14));
    }
    public TextView navigationItem(String title,String kind,boolean selected,Runnable action) {
        TextView v=label(title,11,selected?accent:muted);v.setGravity(Gravity.CENTER);v.setMinHeight(dp(62));v.setPadding(dp(2),dp(5),dp(2),dp(5));
        Drawable d=FmNavigationArt.get(context,kind,selected);d.setBounds(0,0,dp(28),dp(28));v.setCompoundDrawables(null,d,null,null);v.setCompoundDrawablePadding(dp(5));
        GradientDrawable mask=new GradientDrawable();mask.setColor(Color.WHITE);mask.setCornerRadius(dp(24));
        // Selection light belongs to the shared capsule edge, not a rectangle under this item.
        v.setBackground(new RippleDrawable(ColorStateList.valueOf(0x224DA6FF),null,mask));
        v.setSelected(selected);v.setFocusable(true);v.setContentDescription(title+(selected?I18n.t(", выбран"):""));
        v.setLayoutParams(new LinearLayout.LayoutParams(0,-2,1));v.setOnClickListener(w->action.run());return v;
    }
    public ImageButton iconButton(String description,String kind,Runnable action) {
        ImageButton b=new ImageButton(context);b.setImageDrawable(new Icon(kind,accent));b.setContentDescription(description);
        b.setTooltipText(description);b.setImageTintList(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled},new int[]{}},new int[]{muted,glyphColor()}));
        b.setPadding(dp(12),dp(12),dp(12),dp(12));b.setBackground(glassRipple(999));
        b.setLayoutParams(new LinearLayout.LayoutParams(dp(48),dp(48)));b.setOnClickListener(v->action.run());return b;
    }
    /** 42dp visible disc and ~21dp glyph; retain the original 48dp touch target. */
    public ImageButton headerIconButton(String description,String kind,Runnable action){
        ImageButton button=iconButton(description,kind,action);
        int padding=Math.round(13.5f*context.getResources().getDisplayMetrics().density);
        button.setBackground(new InsetDrawable(glassRipple(999),dp(3)));
        button.setPadding(padding,padding,padding,padding);return button;
    }
    /** One useful action per row; critical captions and 48dp targets remain readable. */
    public LinearLayout compactAction(String title,String subtitle,String kind) {
        LinearLayout row=new LinearLayout(context);row.setGravity(Gravity.CENTER_VERTICAL);row.setMinimumHeight(dp(64));
        row.setPadding(dp(10),dp(8),dp(10),dp(8));row.setBackground(new RippleDrawable(ColorStateList.valueOf(0x334DA6FF),box(card,14),null));
        LinearLayout.LayoutParams bounds=new LinearLayout.LayoutParams(-1,-2);bounds.setMargins(0,dp(3),0,dp(3));row.setLayoutParams(bounds);
        ImageView image=new ImageView(context);image.setImageDrawable(new Icon(kind,accent));image.setPadding(dp(8),dp(8),dp(8),dp(8));image.setBackground(glass(999));row.addView(image,new LinearLayout.LayoutParams(dp(40),dp(40)));
        LinearLayout copy=new LinearLayout(context);copy.setOrientation(LinearLayout.VERTICAL);copy.setPadding(dp(10),0,dp(8),0);
        TextView heading=label(title,16,text);heading.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));copy.addView(heading);
        if(!subtitle.isEmpty()){TextView sub=label(subtitle,13,muted);sub.setPadding(0,dp(2),0,0);copy.addView(sub);}
        row.addView(copy,new LinearLayout.LayoutParams(0,-2,1));ImageView arrow=new ImageView(context);arrow.setImageDrawable(new Icon("forward",muted));row.addView(arrow,new LinearLayout.LayoutParams(dp(16),dp(24)));
        row.setFocusable(true);row.setClickable(true);row.setContentDescription(title+(subtitle.isEmpty()?"":", "+subtitle));
        row.setAccessibilityDelegate(new android.view.View.AccessibilityDelegate(){@Override public void onInitializeAccessibilityNodeInfo(android.view.View host,android.view.accessibility.AccessibilityNodeInfo info){super.onInitializeAccessibilityNodeInfo(host,info);info.setClassName("android.widget.Button");}});
        for(int i=0;i<row.getChildCount();i++)row.getChildAt(i).setImportantForAccessibility(android.view.View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);return row;
    }
    public static final class Icon extends Drawable {
        private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path[] paths;
        public Icon(String kind,int color){
            String[] data=FmGlyphData.paths(kind);paths=new Path[data.length];
            for(int i=0;i<data.length;i++)paths[i]=androidx.core.graphics.PathParser.createPathFromPathData(data[i]);
            paint.setColor(color==0xFF4DA6FF?0xFFF4F6FC:color==0xFF1769AA?0xFF3F4855:color);
            paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(1.7f);paint.setStrokeCap(Paint.Cap.ROUND);paint.setStrokeJoin(Paint.Join.ROUND);
        }
        @Override public void draw(Canvas canvas){canvas.save();canvas.translate(getBounds().left,getBounds().top);canvas.scale(getBounds().width()/24f,getBounds().height()/24f);for(Path path:paths)canvas.drawPath(path,paint);canvas.restore();}
        @Override public void setAlpha(int alpha){paint.setAlpha(alpha);invalidateSelf();}
        @Override public void setColorFilter(ColorFilter filter){paint.setColorFilter(filter);invalidateSelf();}
        @Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }
}
