// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { EXTRA_PROFILE_PATHS } from './theme-extensions.js';
import { cloneTheme } from './theme-validator.js';
export const PROFILE_PATHS = {'effects.backgroundFlowOpacity':'Brightness','shape.surfaceOpacity':'Opacity','effects.glowStrength':'Glow','effects.haloStrength':'Halo',...EXTRA_PROFILE_PATHS};
export function resolveProfile(theme,mode='dark') {
  const copy=cloneTheme(theme);
  if(copy.paletteEffects?.separate) for(const [path,suffix] of Object.entries(PROFILE_PATHS)) {
    const [section,key]=path.split('.');copy[section][key]=copy.paletteEffects[(mode==='light'?'light':'dark')+suffix];
  }
  return copy;
}
export function separateProfiles(theme,separate,mode='dark') {
  if(separate&&!theme.paletteEffects.separate) for(const m of ['dark','light']) for(const [path,suffix] of Object.entries(PROFILE_PATHS)) {
    const [section,key]=path.split('.');theme.paletteEffects[m+suffix]=theme[section][key];
  }
  if(!separate&&theme.paletteEffects.separate) for(const [path,suffix] of Object.entries(PROFILE_PATHS)) {
    const [section,key]=path.split('.');theme[section][key]=theme.paletteEffects[mode+suffix];
  }
  theme.paletteEffects.separate=separate;
}
