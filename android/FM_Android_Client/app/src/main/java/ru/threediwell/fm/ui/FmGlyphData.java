// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;
/** Approved v5 outline geometry, 24-unit grid. No actions or transport dependencies. */
final class FmGlyphData {
    private FmGlyphData() {}
    static String[] paths(String kind) {
        switch(kind) {
            case "back": return new String[]{"M20 12H4m7-7-7 7 7 7"};
            case "batch": return new String[]{"M5 7H3v14h14v-2M7 3h10l4 4v10H7Z","M10.3 6.0H12.7Q13.0 6.0 13.0 6.3V8.7Q13.0 9.0 12.7 9.0H10.3Q10.0 9.0 10.0 8.7V6.3Q10.0 6.0 10.3 6.0Z","M17 10h1m-8 3h8"};
            case "bell": return new String[]{"M6 10a6 6 0 0 1 12 0v5l2 3H4l2-3Zm4 11h4M12 2v2"};
            case "camera": return new String[]{"M8 6 9.5 3h5L16 6h4a1 1 0 0 1 1 1v12H3V7a1 1 0 0 1 1-1Z","M16.0 12.0a4.0 4.0 0 1 0 -8.0 0a4.0 4.0 0 1 0 8.0 0Z"};
            case "check": return new String[]{"m4 12 5 5L20 6"};
            case "clock": return new String[]{"M21.0 12.0a9.0 9.0 0 1 0 -18.0 0a9.0 9.0 0 1 0 18.0 0Z","M12 6v7l4 2"};
            case "close": return new String[]{"M5 5l14 14M5 19 19 5"};
            case "connection": return new String[]{"M3 8a14 14 0 0 1 18 0M6 12a9 9 0 0 1 12 0M9 16a4.5 4.5 0 0 1 6 0","M12.5 20.0a0.5 0.5 0 1 0 -1.0 0a0.5 0.5 0 1 0 1.0 0Z"};
            case "download": return new String[]{"M12 3v12m-4-4 4 4 4-4M5 19v2h14v-2"};
            case "edit": return new String[]{"m4 15 12-12a2 2 0 0 1 3 0l2 2a2 2 0 0 1 0 3L9 20l-6 1Zm9-9 5 5"};
            case "file": return new String[]{"M5 3h9l5 5v13H5ZM14 3v5h5M8 12h8m-8 4h6"};
            case "forward": return new String[]{"m8 4 8 8-8 8"};
            case "heat": return new String[]{"M7 14V5a2.5 2.5 0 0 1 5 0v9a4.5 4.5 0 1 1-5 0Zm2.5-6v9m7-12c3 3-3 4 0 7m4-9c4 5-4 7 0 11","M10.5 17.5a1.0 1.0 0 1 0 -2.0 0a1.0 1.0 0 1 0 2.0 0Z"};
            case "history": return new String[]{"M3 9a9 9 0 1 1 .1 7M3 3v6h6M12 7v6l4 2"};
            case "info": return new String[]{"M21.0 12.0a9.0 9.0 0 1 0 -18.0 0a9.0 9.0 0 1 0 18.0 0Z","M12 11v6","M12.5 7.0a0.5 0.5 0 1 0 -1.0 0a0.5 0.5 0 1 0 1.0 0Z"};
            case "link": return new String[]{"m14 9 1.5-1.5a3.5 3.5 0 0 1 5 5l-4 4a3.5 3.5 0 0 1-5 0m-1-1L9 17a3.5 3.5 0 0 1-5-5l4-4a3.5 3.5 0 0 1 5 0m-5 6 6-6"};
            case "logout": return new String[]{"M10 3H4v18h6m0-9h11m-5-5 5 5-5 5"};
            case "moon": return new String[]{"M9 3a9 9 0 1 0 12 12A10 10 0 0 1 9 3Z"};
            case "more": return new String[]{"M5 12h.1m6.9 0h.1m6.9 0h.1"};
            case "nfc": return new String[]{"M5.0 4.0H12.0Q14.0 4.0 14.0 6.0V18.0Q14.0 20.0 12.0 20.0H5.0Q3.0 20.0 3.0 18.0V6.0Q3.0 4.0 5.0 4.0Z","M6.5 15V9l4 6V9m6-1a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"};
            case "pause": return new String[]{"M7.0 4.0H8.5Q9.5 4.0 9.5 5.0V19.0Q9.5 20.0 8.5 20.0H7.0Q6.0 20.0 6.0 19.0V5.0Q6.0 4.0 7.0 4.0Z","M15.5 4.0H17.0Q18.0 4.0 18.0 5.0V19.0Q18.0 20.0 17.0 20.0H15.5Q14.5 20.0 14.5 19.0V5.0Q14.5 4.0 15.5 4.0Z"};
            case "person": return new String[]{"M16.0 7.0a4.0 4.0 0 1 0 -8.0 0a4.0 4.0 0 1 0 8.0 0Z","M4 21v-2a8 6 0 0 1 16 0v2"};
            case "play": return new String[]{"M7 4.5v15L20 12Z"};
            case "plus": return new String[]{"M12 4v16M4 12h16"};
            case "printer": return new String[]{"M4 20V3h16v17M4 8h16M9 8v4h6V8m-3 4v3M2 20h20v2H2Z"};
            case "projects": return new String[]{"M3 7V4h7l3 3h8v14H3ZM3 10h18"};
            case "qr": return new String[]{"M5 3h10l4 4v14H5Z","M8.2 7.0H10.8Q11.0 7.0 11.0 7.2V9.8Q11.0 10.0 10.8 10.0H8.2Q8.0 10.0 8.0 9.8V7.2Q8.0 7.0 8.2 7.0Z","M13.2 7.0H15.8Q16.0 7.0 16.0 7.2V9.8Q16.0 10.0 15.8 10.0H13.2Q13.0 10.0 13.0 9.8V7.2Q13.0 7.0 13.2 7.0Z","M8.2 13.0H10.8Q11.0 13.0 11.0 13.2V15.8Q11.0 16.0 10.8 16.0H8.2Q8.0 16.0 8.0 15.8V13.2Q8.0 13.0 8.2 13.0Z","M14 13h2v3h-2m-6 3h8"};
            case "receive": return new String[]{"M12 3v12m-4-4 4 4 4-4M4 14v6h16v-6"};
            case "refresh": return new String[]{"M20 8a9 9 0 1 0 .5 8M20 3v5h-5"};
            case "remove": return new String[]{"M12 15V3M8 7l4-4 4 4M4 14v6h16v-6"};
            case "discard": return new String[]{"M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7"};
            case "repeat": return new String[]{"M20 8a9 9 0 1 0 .6 8M20 3v5h-5","m10 8 6 4-6 4Z"};
            case "scan": return new String[]{"M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5","M7.4 7.0H9.6Q10.0 7.0 10.0 7.4V9.6Q10.0 10.0 9.6 10.0H7.4Q7.0 10.0 7.0 9.6V7.4Q7.0 7.0 7.4 7.0Z","M14.4 7.0H16.6Q17.0 7.0 17.0 7.4V9.6Q17.0 10.0 16.6 10.0H14.4Q14.0 10.0 14.0 9.6V7.4Q14.0 7.0 14.4 7.0Z","M7.4 14.0H9.6Q10.0 14.0 10.0 14.4V16.6Q10.0 17.0 9.6 17.0H7.4Q7.0 17.0 7.0 16.6V14.4Q7.0 14.0 7.4 14.0Z","M14 14h3v3h-3"};
            case "search": return new String[]{"M18.0 10.5a7.5 7.5 0 1 0 -15.0 0a7.5 7.5 0 1 0 15.0 0Z","m16 16 5 5"};
            case "send_print": return new String[]{"M3 18V4h14v8M3 8h14M8 8v3h4V8m-2 3v3M2 18h11v3H2m12-4h7m-3-3 3 3-3 3"};
            case "settings": return new String[]{"M5 3v4m0 4v10M12 3v10m0 4v4M19 3v4m0 4v10","M7.0 9.0a2.0 2.0 0 1 0 -4.0 0a2.0 2.0 0 1 0 4.0 0Z","M14.0 15.0a2.0 2.0 0 1 0 -4.0 0a2.0 2.0 0 1 0 4.0 0Z","M21.0 9.0a2.0 2.0 0 1 0 -4.0 0a2.0 2.0 0 1 0 4.0 0Z"};
            case "sort": return new String[]{"M3 5h14M3 10h10M3 15h6m10-4v10m-3-3 3 3 3-3"};
            case "spool": return new String[]{"M21.0 12.0a9.0 9.0 0 1 0 -18.0 0a9.0 9.0 0 1 0 18.0 0Z","M14.2 12.0a2.2 2.2 0 1 0 -4.4 0a2.2 2.2 0 1 0 4.4 0Z","m10 6 2-1 2 1m4 4 1 2-1 2m-4 4-2 1-2-1m-4-4-1-2 1-2"};
            case "stop": return new String[]{"M7.0 5.0H17.0Q19.0 5.0 19.0 7.0V17.0Q19.0 19.0 17.0 19.0H7.0Q5.0 19.0 5.0 17.0V7.0Q5.0 5.0 7.0 5.0Z"};
            case "sun": return new String[]{"M16.0 12.0a4.0 4.0 0 1 0 -8.0 0a4.0 4.0 0 1 0 8.0 0Z","M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5"};
            case "tasks": return new String[]{"M8 4H4v17h16V4h-4M8 2h8v4H8ZM7 10l2 2 3-4m2 3h3M7 16l2 2 3-4m2 3h3"};
            case "unlink": return new String[]{"m15 7 1-1a3.5 3.5 0 0 1 5 5l-3 3M9 17l-1 1a3.5 3.5 0 0 1-5-5l3-3M3 3l18 18"};
            case "video": return new String[]{"M5.0 6.0H13.0Q15.0 6.0 15.0 8.0V16.0Q15.0 18.0 13.0 18.0H5.0Q3.0 18.0 3.0 16.0V8.0Q3.0 6.0 5.0 6.0Z","m15 10 6-3v10l-6-3"};
            case "warehouse": return new String[]{"M3 3v18M21 3v18M3 12h18M3 21h18","M6 5h4v5H6ZM14 5h4v5h-4ZM6 14h4v5H6ZM14 14h4v5h-4Z"};
            case "warning": return new String[]{"M11 3a1.15 1.15 0 0 1 2 0l9 17a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1ZM12 8v5","M12.5 17.0a0.5 0.5 0 1 0 -1.0 0a0.5 0.5 0 1 0 1.0 0Z"};
            default: return paths("info");
        }
    }
}
