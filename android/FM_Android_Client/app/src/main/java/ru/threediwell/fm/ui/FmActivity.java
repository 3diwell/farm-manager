// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;

import android.content.Context;
import android.content.res.Configuration;
import android.content.res.Resources;
import android.os.LocaleList;
import androidx.activity.ComponentActivity;
import ru.threediwell.fm.i18n.I18n;
import java.util.Locale;

/** App-local locale for native dialogs/widgets, independent of the phone's language.
 * Refreshing settings keeps this Activity and its authenticated transport alive.
 */
public abstract class FmActivity extends ComponentActivity {
    private Resources presentationResources;
    private static Configuration localized(Context context,Configuration source) {
        String language=context.getSharedPreferences("fm-client",0).getString("language","ru");
        I18n.setLanguage(language);
        Configuration config=new Configuration(source);
        config.setLocales(new LocaleList(Locale.forLanguageTag(I18n.language())));
        return config;
    }
    @Override protected void attachBaseContext(Context base) {
        super.attachBaseContext(base.createConfigurationContext(localized(base,base.getResources().getConfiguration())));
    }
    @Override public Resources getResources() {
        return presentationResources==null?super.getResources():presentationResources;
    }
    protected final void refreshPresentation() {
        setPresentation(super.getResources().getConfiguration());
    }
    private void setPresentation(Configuration config) {
        presentationResources=getBaseContext().createConfigurationContext(localized(this,config)).getResources();
        Resources.Theme next=presentationResources.newTheme();next.applyStyle(FmStyle.theme(this),true);
        getTheme().setTo(next);
    }
    @Override public void onConfigurationChanged(Configuration config) {
        super.onConfigurationChanged(config);setPresentation(config);
    }
}
