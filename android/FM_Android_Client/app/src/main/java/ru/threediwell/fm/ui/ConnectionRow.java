// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;
import android.content.Context;
import android.view.Gravity;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Status followed immediately by refresh; the server address remains in the tooltip. */
public final class ConnectionRow extends LinearLayout {
    public final TextView status;
    public ConnectionRow(Context context){this(context,new FmStyle(context),()->{});}
    public ConnectionRow(Context context,FmStyle style,Runnable refresh){
        super(context);setGravity(Gravity.CENTER_VERTICAL);
        status=style.label("",12,style.muted);status.setMaxLines(2);status.setIncludeFontPadding(false);
        LayoutParams text=new LayoutParams(-2,-2);text.setMarginEnd(style.dp(8));addView(status,text);
        addView(style.headerIconButton(ru.threediwell.fm.i18n.I18n.t("Обновить"),"refresh",refresh));
    }
}
