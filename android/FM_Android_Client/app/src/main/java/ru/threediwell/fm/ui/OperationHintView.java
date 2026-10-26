// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;

import android.content.Context;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import ru.threediwell.fm.R;
import ru.threediwell.fm.i18n.I18n;
import java.util.List;

/** Approved transparent artwork with native, scalable and translated labels. */
public final class OperationHintView extends LinearLayout {
    public OperationHintView(Context context, FmStyle style, OperationFlow flow, boolean scanning) {
        super(context);
        setOrientation(VERTICAL);
        if (flow == OperationFlow.NONE) { setVisibility(GONE); return; }
        setPadding(0, style.dp(8), 0, style.dp(10));
        if (scanning) {
            TextView instruction = style.label(switch (flow) {
                case SELECT_PRINTER -> I18n.t("Сканируйте QR позиции");
                case REMOVE -> I18n.t("Сканируйте позицию или катушку");
                default -> I18n.t("Сканируйте катушку");
            }, 14, style.accent);
            instruction.setPadding(0, 0, 0, style.dp(6));
            addView(instruction);
        }
        LinearLayout row = new LinearLayout(context);
        row.setGravity(Gravity.CENTER);
        // Arrows represent physical flow, independent of the device's system language.
        row.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
        addView(row, new LayoutParams(-1, -2));
        List<OperationFlow.Item> items = flow.items();
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) {
                TextView arrow = style.label("→", 22, style.muted);
                arrow.setGravity(Gravity.CENTER);
                arrow.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
                LayoutParams ap = new LayoutParams(style.dp(24), style.dp(80));
                ap.gravity = Gravity.TOP;
                row.addView(arrow, ap);
            }
            OperationFlow.Item item = items.get(i);
            boolean active = scanning && flow.scanTarget(item);
            LinearLayout tile = new LinearLayout(context);
            tile.setOrientation(VERTICAL);
            tile.setGravity(Gravity.CENTER_HORIZONTAL);
            tile.setPadding(style.dp(5), style.dp(4), style.dp(5), style.dp(6));
            if (active) {
                GradientDrawable background = style.box(FmStyle.isDark(context) ? 0xFF233547 : 0xFFE3EFFB, 14);
                background.setStroke(style.dp(1), style.accent);
                tile.setBackground(background);
            }
            ImageView image = new ImageView(context);
            image.setImageResource(switch (item) {
                case PRINTER -> R.drawable.hint_printer;
                case FULL_SPOOL -> R.drawable.hint_spool_full;
                case LOW_SPOOL -> R.drawable.hint_spool_low;
                case WAREHOUSE -> R.drawable.hint_warehouse;
            });
            image.setScaleType(ImageView.ScaleType.FIT_CENTER);
            image.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
            tile.addView(image, new LayoutParams(-1, style.dp(76)));
            TextView label = style.label(switch (item) {
                case PRINTER -> I18n.t("Принтер");
                case FULL_SPOOL, LOW_SPOOL -> I18n.t("Катушка");
                case WAREHOUSE -> I18n.t("Склад");
            }, 13, active ? style.accent : style.text);
            label.setGravity(Gravity.CENTER);
            label.setPadding(0, style.dp(5), 0, 0);
            tile.addView(label, new LayoutParams(-1, -2));
            LayoutParams tp = items.size() == 1
                    ? new LayoutParams(style.dp(116), -2) : new LayoutParams(0, -2, 1);
            tp.gravity = Gravity.TOP;
            row.addView(tile, tp);
        }
        if (flow == OperationFlow.REMOVE) {
            TextView note = style.label(I18n.t("Остаток смотрите в карточке. Место хранения сохраняется."), 12, style.muted);
            note.setPadding(0, style.dp(8), 0, 0);
            addView(note);
        }
    }

    /** Only attach to a result screen after FM has acknowledged the inventory request. */
    public static View confirmed(Context context, FmStyle style) {
        LinearLayout row = new LinearLayout(context);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(style.dp(12), style.dp(12), style.dp(12), style.dp(12));
        row.setBackground(style.box(style.card, 14));
        row.setContentDescription(I18n.t("Подтверждено FM"));
        row.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_YES);
        row.setAccessibilityLiveRegion(ACCESSIBILITY_LIVE_REGION_POLITE);
        ImageView check = new ImageView(context);
        check.setImageResource(R.drawable.hint_brand_check);
        check.setScaleType(ImageView.ScaleType.FIT_CENTER);
        check.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        row.addView(check, new LayoutParams(style.dp(42), style.dp(36)));
        TextView label = style.label(I18n.t("Подтверждено FM"), 17, style.text);
        label.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        label.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        label.setPadding(style.dp(12), 0, 0, 0);
        row.addView(label, new LayoutParams(0, -2, 1));
        return row;
    }
}
