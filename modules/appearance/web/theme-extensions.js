// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Schema 12 additions. Shared by validation, migration and palette resolution.
export const EXTRA_PROFILE_PATHS={
 'effects.backgroundFlowUseThemeColors':'UseThemeColors',
 'effects.backgroundFlowPrimary':'Primary','effects.backgroundFlowSecondary':'Secondary',
 'shape.shadowIntensity':'Shadow','effects.panelDepth':'Depth','effects.panelAiriness':'Airiness',
 'effects.panelMaterial':'Material','effects.controlStyle':'Controls',
 'effects.matteStrength':'Matte','effects.glossStrength':'Gloss',
 'effects.glassRefraction':'Refraction','effects.glassBlur':'GlassBlur','effects.glassEdge':'GlassEdge'
};
export const EXTRA_DEFAULTS={
 typography:{customMetrics:false,bodyWeight:400,headingWeight:600,captionWeight:400,bodyLineHeight:1.45,headingLineHeight:1.2,captionLineHeight:1.35},
 shape:{independentRadii:false,buttonRadius:10,inputRadius:8,cardRadius:14},
 effects:{glassRefraction:.35,glassBlur:4,glassEdge:.25}
};
export const EXTRA_RANGES={
 'typography.bodyWeight':[300,800,100],'typography.headingWeight':[300,800,100],'typography.captionWeight':[300,800,100],
 'typography.bodyLineHeight':[1,2,0],'typography.headingLineHeight':[1,2,0],'typography.captionLineHeight':[1,2,0],
 'shape.buttonRadius':[0,32,0],'shape.inputRadius':[0,32,0],'shape.cardRadius':[0,40,0],
 'effects.glassRefraction':[0,1,0],'effects.glassBlur':[0,16,0],'effects.glassEdge':[0,1,0]
};
export const MATERIALS=['solid','soft-glass','deep-glass','hud','optical-glass'];
export const CONTROL_STYLES=['clean','glass','command'];
export function addExtensionDefaults(theme){
 for(const [section,values] of Object.entries(EXTRA_DEFAULTS))Object.assign(theme[section],values);
 for(const mode of ['dark','light'])for(const [path,suffix] of Object.entries(EXTRA_PROFILE_PATHS)){
  const [section,key]=path.split('.');theme.paletteEffects[mode+suffix]=theme[section][key];
 }
 return theme;
}
