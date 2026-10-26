// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;

import android.app.AlertDialog;
import android.content.*;
import android.graphics.*;
import android.graphics.drawable.*;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.*;
import android.widget.*;
import java.util.*;
import ru.threediwell.fm.farm.MaterialSlots;
import ru.threediwell.fm.i18n.I18n;

/** Five adaptive columns; up to five feeds share one row, including external spools. */
public final class MaterialSlotsView extends LinearLayout {
    private final FmStyle style;private List<MaterialSlots.Slot> current;
    public MaterialSlotsView(Context context){this(context,new FmStyle(context));}
    public MaterialSlotsView(Context context,FmStyle style){super(context);this.style=style;setOrientation(VERTICAL);}
    public void update(List<MaterialSlots.Slot> slots){if(slots.equals(current))return;current=slots;removeAllViews();
        if(slots.isEmpty()){addView(style.label(I18n.t("Нет данных о материале."),13,style.muted));return;}
        Map<String,List<MaterialSlots.Slot>> groups=new LinkedHashMap<>();for(var s:slots)groups.computeIfAbsent(s.group(),k->new ArrayList<>()).add(s);
        if(slots.size()<=5)addGroup(TextUtils.join(" · ",groups.keySet()),slots);
        else for(var e:groups.entrySet())addGroup(e.getKey(),e.getValue());
    }
    private void addGroup(String title,List<MaterialSlots.Slot> slots){
        TextView heading=style.label(title,12,style.muted);heading.setPadding(0,style.dp(6),0,style.dp(4));addView(heading);
        LinearLayout row=null;
        for(int index=0;index<slots.size();index++){
                if(index%5==0){row=new LinearLayout(getContext());row.setOrientation(HORIZONTAL);row.setWeightSum(5);addView(row,new LayoutParams(-1,-2));}
                MaterialSlots.Slot slot=slots.get(index);
                LinearLayout tile=new LinearLayout(getContext());tile.setOrientation(VERTICAL);tile.setGravity(Gravity.CENTER);tile.setPadding(style.dp(2),0,style.dp(2),style.dp(4));
                LinearLayout cell=new LinearLayout(getContext());cell.setOrientation(VERTICAL);cell.setGravity(Gravity.CENTER);cell.setPadding(style.dp(3),style.dp(7),style.dp(3),style.dp(5));cell.setMinimumHeight(style.dp(46));
                GradientDrawable box=style.box(style.bg,10);box.setStroke(style.dp(slot.active()?2:1),slot.active()?style.accent:style.border);cell.setBackground(box);
                View chip=new View(getContext());chip.setBackground(new Chip(slot,style));cell.addView(chip,new LayoutParams(style.dp(24),style.dp(8)));
                TextView material=style.label(slot.external()?I18n.t("внешн."):slot.material(),11,style.muted);material.setMaxLines(1);material.setEllipsize(TextUtils.TruncateAt.END);material.setAutoSizeTextTypeUniformWithConfiguration(8,11,1,TypedValue.COMPLEX_UNIT_SP);material.setGravity(Gravity.CENTER);material.setPadding(0,style.dp(3),0,0);cell.addView(material,new LayoutParams(-1,-2));
                FrameLayout frame=new FrameLayout(getContext());frame.addView(cell,new FrameLayout.LayoutParams(-1,-2));if(slot.active()){View dot=new View(getContext());GradientDrawable circle=new GradientDrawable();circle.setShape(GradientDrawable.OVAL);circle.setColor(style.accent);dot.setBackground(circle);dot.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);frame.addView(dot,new FrameLayout.LayoutParams(style.dp(6),style.dp(6),Gravity.TOP|Gravity.END));}tile.addView(frame,new LayoutParams(-1,-2));
                TextView percent=style.label(slot.percent()<0?"—":slot.percent()+"%",12,style.muted);percent.setMaxLines(1);percent.setAutoSizeTextTypeUniformWithConfiguration(9,12,1,TypedValue.COMPLEX_UNIT_SP);percent.setGravity(Gravity.CENTER);percent.setPadding(0,style.dp(3),0,0);tile.addView(percent,new LayoutParams(-1,-2));
                tile.setContentDescription(slot.details()+(slot.active()?". "+I18n.t("Активная подача"):""));tile.setFocusable(true);tile.setOnClickListener(v->new AlertDialog.Builder(getContext()).setTitle(slot.position()).setMessage(slot.details()).setPositiveButton(I18n.t("Закрыть"),null).show());
                tile.setAccessibilityDelegate(new View.AccessibilityDelegate(){@Override public void onInitializeAccessibilityNodeInfo(View host,android.view.accessibility.AccessibilityNodeInfo info){super.onInitializeAccessibilityNodeInfo(host,info);info.setClassName("android.widget.Button");}});
                cell.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);percent.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);row.addView(tile,new LayoutParams(0,-2,1));
        }
    }
    private static final class Chip extends Drawable {
        private final MaterialSlots.Slot slot;private final FmStyle style;private final Paint p=new Paint(3);
        Chip(MaterialSlots.Slot slot,FmStyle style){this.slot=slot;this.style=style;}
        @Override public void draw(Canvas c){RectF b=new RectF(getBounds());p.setColor(slot.empty()||slot.color().isEmpty()?style.border:Color.parseColor(slot.color()));p.setStyle(Paint.Style.FILL);c.drawRoundRect(b,style.dp(3),style.dp(3),p);if(slot.external()&&slot.color().isEmpty()){c.save();c.clipRect(b);p.setColor(style.muted);p.setStrokeWidth(style.dp(1));for(float x=b.left-b.height();x<b.right;x+=style.dp(7))c.drawLine(x,b.top,x+b.height(),b.bottom,p);c.restore();}if(slot.stale()){p.setColor(style.bg);p.setAlpha(150);c.drawRoundRect(b,style.dp(3),style.dp(3),p);p.setAlpha(255);}}
        @Override public void setAlpha(int a){p.setAlpha(a);}@Override public void setColorFilter(ColorFilter f){p.setColorFilter(f);}@Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }
}
