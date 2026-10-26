// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;

import android.app.*;
import android.text.InputType;
import android.widget.*;
import ru.threediwell.fm.farm.PreheatPresets;
import ru.threediwell.fm.i18n.I18n;
import java.util.*;
import java.util.function.BiConsumer;

/** Редактируется только черновик; сервер обновляется после явного сохранения. */
public final class PreheatEditor {
    private PreheatEditor(){}
    private static final class Row {
        LinearLayout view;EditText name,nozzle,bed,chamber;
    }
    public static void show(Activity activity,FmStyle style,PreheatPresets current,BiConsumer<PreheatPresets,Runnable> save){
        LinearLayout form=new LinearLayout(activity);form.setOrientation(LinearLayout.VERTICAL);form.setPadding(style.dp(16),style.dp(8),style.dp(16),style.dp(16));
        TextView hint=style.label(I18n.t("Пресеты общие для всей фермы. Изменения вступят в силу после сохранения."),14,style.muted);hint.setPadding(0,0,0,style.dp(12));form.addView(hint);
        LinearLayout list=new LinearLayout(activity);list.setOrientation(LinearLayout.VERTICAL);form.addView(list);
        TextView error=style.label("",14,style.warning);error.setPadding(0,style.dp(8),0,style.dp(8));form.addView(error);
        List<Row> rows=new ArrayList<>();
        java.util.function.Consumer<PreheatPresets.Preset> add=p->{
            if(rows.size()>=PreheatPresets.MAX_COUNT){error.setText(I18n.t("Можно сохранить не более 24 пресетов."));return;}
            Row row=new Row();row.view=new LinearLayout(activity);row.view.setOrientation(LinearLayout.VERTICAL);row.view.setPadding(style.dp(12),style.dp(10),style.dp(12),style.dp(12));row.view.setBackground(style.box(style.card,14));
            LinearLayout.LayoutParams bounds=new LinearLayout.LayoutParams(-1,-2);bounds.setMargins(0,style.dp(4),0,style.dp(4));list.addView(row.view,bounds);
            LinearLayout heading=new LinearLayout(activity);heading.setGravity(android.view.Gravity.CENTER_VERTICAL);row.view.addView(heading);
            row.name=field(activity,style,heading,I18n.t("Имя (до 12 знаков)"),p.name,false);
            heading.addView(style.iconButton(I18n.t("Убрать пресет"),"close",()->{rows.remove(row);list.removeView(row.view);}));
            LinearLayout temperatures=new LinearLayout(activity);row.view.addView(temperatures);
            row.nozzle=field(activity,style,temperatures,I18n.t("Сопло · 0–350 °C"),Integer.toString(p.nozzle),true);
            row.bed=field(activity,style,temperatures,I18n.t("Стол · 0–120 °C"),Integer.toString(p.bed),true);
            row.chamber=field(activity,style,temperatures,I18n.t("Камера · 0–65 °C"),p.chamber==null?"":p.chamber.toString(),true);rows.add(row);
        };
        for(PreheatPresets.Preset p:current.values)add.accept(p);
        Button more=new Button(activity);more.setText(I18n.t("Добавить пресет"));style.button(more,false);form.addView(more);more.setOnClickListener(v->add.accept(new PreheatPresets.Preset(I18n.t("Новый ")+(rows.size()+1),200,60,null)));
        Button defaults=new Button(activity);defaults.setText(I18n.t("Встроенные пресеты"));style.button(defaults,false);form.addView(defaults);defaults.setOnClickListener(v->{rows.clear();list.removeAllViews();error.setText("");for(PreheatPresets.Preset p:PreheatPresets.defaults().values)add.accept(p);});
        TextView optional=style.label(I18n.t("Пустая температура камеры оставляет её текущую цель. Нагрев камеры применяется только там, где он поддерживается."),13,style.muted);form.addView(optional);
        ScrollView scroll=new ScrollView(activity);scroll.addView(form);
        AlertDialog dialog=new AlertDialog.Builder(activity).setTitle(I18n.t("Пресеты прогрева")).setView(scroll).setPositiveButton(I18n.t("Сохранить"),null).setNegativeButton(I18n.t("Отмена"),null).create();
        dialog.setOnShowListener(d->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
            try{
                List<PreheatPresets.Preset> values=new ArrayList<>();for(Row row:rows){String chamber=row.chamber.getText().toString().trim();values.add(new PreheatPresets.Preset(row.name.getText().toString(),PreheatPresets.input(row.nozzle.getText().toString()),PreheatPresets.input(row.bed.getText().toString()),chamber.isEmpty()?null:PreheatPresets.input(chamber)));}
                error.setText("");save.accept(new PreheatPresets(values),dialog::dismiss);
            }catch(Exception ex){error.setText(ex.getMessage());}
        }));dialog.show();
    }
    private static EditText field(Activity a,FmStyle style,LinearLayout parent,String caption,String value,boolean numeric){
        LinearLayout column=new LinearLayout(a);column.setOrientation(LinearLayout.VERTICAL);column.setPadding(0,style.dp(4),style.dp(6),style.dp(4));parent.addView(column,new LinearLayout.LayoutParams(0,-2,1));
        TextView title=style.label(caption,12,style.muted);column.addView(title);
        EditText input=new EditText(a);input.setSingleLine(true);input.setInputType(numeric?InputType.TYPE_CLASS_NUMBER:InputType.TYPE_CLASS_TEXT);input.setText(value);input.setTextColor(style.text);input.setTextSize(16);input.setMinHeight(style.dp(48));input.setPadding(style.dp(8),style.dp(8),style.dp(8),style.dp(8));input.setBackground(style.box(style.bg,10));input.setContentDescription(caption);column.addView(input,new LinearLayout.LayoutParams(-1,-2));return input;
    }
}
