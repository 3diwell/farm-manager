// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;
import android.content.Context;
import android.view.*;
import android.widget.*;
import ru.threediwell.fm.i18n.I18n;

public final class NotificationButton extends FrameLayout {
    private final ImageButton button;private final TextView badge;private final FmStyle style;
    public NotificationButton(Context context){this(context,new FmStyle(context),()->{});}
    public NotificationButton(Context context,FmStyle style,Runnable open){
        super(context);this.style=style;setLayoutParams(new LinearLayout.LayoutParams(style.dp(48),style.dp(48)));
        button=style.headerIconButton(I18n.t("Оповещения"),"bell",open);addView(button,new FrameLayout.LayoutParams(-1,-1));
        badge=style.label("",10,style.bg);badge.setGravity(Gravity.CENTER);badge.setPadding(style.dp(3),0,style.dp(3),0);badge.setMinWidth(style.dp(16));badge.setMinHeight(style.dp(16));badge.setBackground(style.box(style.accent,8));badge.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);badge.setClickable(false);
        FrameLayout.LayoutParams b=new FrameLayout.LayoutParams(-2,-2,Gravity.TOP|Gravity.END);b.topMargin=style.dp(2);b.setMarginEnd(style.dp(2));addView(badge,b);update(0,false);
    }
    public void update(int unread,boolean pending){badge.setText(unread>99?"99+":unread>0?String.valueOf(unread):"!");badge.setVisibility(unread>0||pending?VISIBLE:GONE);String text=I18n.t("Оповещения")+", "+I18n.t("Непрочитанных: ")+unread+(pending?". "+I18n.t("Есть отправка с неизвестным результатом."):"");button.setContentDescription(text);button.setTooltipText(text);}
}
