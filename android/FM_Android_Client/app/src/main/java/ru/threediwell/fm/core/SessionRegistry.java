// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

/** Сеанс остаётся в памяти процесса: cookie никогда не передаётся в Intent. */
public final class SessionRegistry {
    private static volatile FmApi current;
    private SessionRegistry(){}
    public static FmApi get(){return current;}
    public static void set(FmApi api){current=api;}
    public static void clear(){FmApi old=current;current=null;if(old!=null)old.clearSession();}
}
