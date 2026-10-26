// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;

import ru.threediwell.fm.i18n.I18n;
import java.util.*;

/** Общая геометрия PDF и проверка набора меток без зависимости от Android. */
public final class LabelSheet {
    public static final int WIDTH=595, HEIGHT=842, PER_PAGE=8;
    public record Entry(String id,String caption,String code) {}
    public record Cell(int x,int y,int width,int height) {}
    public static Cell cell(int index) {
        if(index<0||index>=PER_PAGE)throw new IllegalArgumentException(I18n.t("Неверная позиция этикетки"));
        return new Cell(24+(index%2)*278,58+(index/2)*188,269,177);
    }
    public static int pages(int count) {
        if(count<1||count>500) throw new IllegalArgumentException(I18n.t("Выберите от 1 до 500 катушек для одного PDF"));
        return (count+PER_PAGE-1)/PER_PAGE;
    }
    public static List<Entry> validate(List<Entry> source) {
        pages(source.size()); Set<String> ids=new HashSet<>(); String server=null;
        for(Entry e:source) {
            if(e.id()==null||e.caption()==null||e.code()==null) throw new IllegalArgumentException(I18n.t("Неполная этикетка"));
            String[] parts=e.code().split(":",-1);
            Labels.Label label=Labels.parse(e.code(),parts.length>2?parts[2]:"");
            if(!label.kind().equals("spool")||!label.id().equals(e.id())) throw new IllegalArgumentException(I18n.t("PDF предназначен для катушек"));
            if(server==null) server=label.server();
            if(!server.equals(label.server())) throw new IllegalArgumentException(I18n.t("Нельзя объединить разные склады"));
            if(!ids.add(e.id())) throw new IllegalArgumentException(I18n.t("Повтор катушки в PDF"));
        }
        return Collections.unmodifiableList(new ArrayList<>(source));
    }
}
