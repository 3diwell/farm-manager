# Approved identity — Android 0.10

User choice: header A (Farm Manager left, 3diwell right), icon 3 (glass), ordinary shape.

- `3diwell-original.svg` and `res/drawable/ic_3diwell.xml`: original 11 paths from
  `сайт/materials-for-sites-2026-09-13/brand/logo-for-dark-background.svg`, groups
  `logo-word`, `logo-orange-accent`, `logo-bars`. Fixed #FFFFFF / #EA5E20.
  No theme tint, gradients, animations or recoloring of this registered wordmark.
  Only whitespace in the viewport is trimmed. Light theme uses a neutral dark backing.
- `fm-glass.svg`: original 3 paths and rounded inner square from
  `module/3diwell_icon_pack/favicon.svg`. Approved blue/glass variant 3 uses only new
  fills and a highlight clipped to the original silhouette. Geometry is unchanged.
- `render-assets.cjs` rasterizes this checked-in SVG at 48/72/96/144/192 px plus 1024 px.
  It requires Node + Playwright and accepts a local Chromium/Edge executable as argv[2].
  Generated density PNGs are checked in; a normal Gradle build needs no browser.

The launcher references ordinary transparent PNGs, not an adaptive-icon/roundIcon/monochrome
resource. This avoids adding our own circular backing, but an Android launcher or user icon
theme may still normalize/mask icons. The app cannot guarantee the launcher's chosen shape
or full display of its label at every icon-grid/font setting.

App label is `Farm Manager`. Package ID, debug signing key, preferences, networking,
scanner, NFC parser and inventory operations are unchanged by this branding update.
