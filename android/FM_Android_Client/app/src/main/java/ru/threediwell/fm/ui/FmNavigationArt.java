// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;
import android.content.Context;
import android.graphics.drawable.Drawable;
import ru.threediwell.fm.R;
final class FmNavigationArt {
    private FmNavigationArt() {}
    static Drawable get(Context context,String kind,boolean selected){
        boolean dark=FmStyle.isDark(context);int res;
        switch(kind){
            case "printer": res=dark?(selected?R.drawable.fm_nav_printer_dark_active:R.drawable.fm_nav_printer_dark_normal):(selected?R.drawable.fm_nav_printer_light_active:R.drawable.fm_nav_printer_light_normal);break;
            case "projects": res=dark?(selected?R.drawable.fm_nav_projects_dark_active:R.drawable.fm_nav_projects_dark_normal):(selected?R.drawable.fm_nav_projects_light_active:R.drawable.fm_nav_projects_light_normal);break;
            case "tasks": res=dark?(selected?R.drawable.fm_nav_tasks_dark_active:R.drawable.fm_nav_tasks_dark_normal):(selected?R.drawable.fm_nav_tasks_light_active:R.drawable.fm_nav_tasks_light_normal);break;
            case "warehouse": res=dark?(selected?R.drawable.fm_nav_warehouse_dark_active:R.drawable.fm_nav_warehouse_dark_normal):(selected?R.drawable.fm_nav_warehouse_light_active:R.drawable.fm_nav_warehouse_light_normal);break;
            case "more": res=dark?(selected?R.drawable.fm_nav_more_dark_active:R.drawable.fm_nav_more_dark_normal):(selected?R.drawable.fm_nav_more_light_active:R.drawable.fm_nav_more_light_normal);break;
            default: return new FmStyle.Icon(kind,new FmStyle(context).glyphColor());
        }
        return androidx.appcompat.content.res.AppCompatResources.getDrawable(context,res);
    }
}
