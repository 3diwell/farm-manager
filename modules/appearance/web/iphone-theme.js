// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// An original FM preset: soft light and dark surfaces with a blue accent. No third-party assets are bundled.
// 16.10.2026 (R-149): shown as «Ясная» / «Clear»; the id 'iphone', this file name and IPHONE_THEME stay
// (theme-package.js SOURCE_FILES and the zip import check use them).
import { THEME_SCHEMA_VERSION } from './default-theme.js';
const theme = {
 schemaVersion:THEME_SCHEMA_VERSION,
 meta:{name:'Ясная',nameEn:'Clear',author:'3DIWELL',description:'Светлая и тёмная палитры: мягкие поверхности, синий акцент и спокойный световой фон.',descriptionEn:'Light and dark palettes: soft surfaces, a blue accent and a calm ambient background.'},
 dark:{accent:'#0a84ff',surfaceDeep:'#08080a',surfaceBase:'#141416',surfaceRaised:'#242426',surfaceCard:'#1c1c1e',surfaceControl:'#2c2c2e',borderSoft:'#29292d',border:'#38383d',borderStrong:'#55555c',textPrimary:'#f5f5f7',textSecondary:'#d1d1d6',textMuted:'#aeb0b6',textSubtle:'#8e8e93',success:'#30d158',warning:'#ffd60a',danger:'#ff453a',headerSurface:'#1c1c1e',headerAction:'#2c2c2e',headerBorder:'#38383d'},
 light:{accent:'#007aff',surfaceDeep:'#e9eaf0',surfaceBase:'#f2f2f7',surfaceRaised:'#ffffff',surfaceCard:'#ffffff',surfaceControl:'#f5f5fa',borderSoft:'#e7e7ed',border:'#d5d5dd',borderStrong:'#b9b9c3',textPrimary:'#1c1c1e',textSecondary:'#3c3c43',textMuted:'#63636b',textSubtle:'#73737d',success:'#248a3d',warning:'#946200',danger:'#d70015',headerSurface:'#f2f2f7',headerAction:'#e8e8ed',headerBorder:'#d5d5dd'},
 typography:{font:'system',textScale:1.28,customFontName:'',customFontFormat:'',customFontDataUrl:''},
 shape:{radiusScale:1.65,borderWidth:1,shadowIntensity:.35,surfaceOpacity:.94},
 interface:{density:'comfortable',reduceMotion:false,performanceMode:'balanced',highContrast:false},
 effects:{
  secondaryAccent:'#a58de8',glowStrength:.10,haloStrength:.04,
  panelMaterial:'solid',edgeLighting:'active',panelTopHighlight:true,hoverLift:false,shimmerProgress:false,
  backgroundPattern:'none',patternOpacity:0,ambientStrength:0,tableStyle:'clean',statusStyle:'text-dot',cornerStyle:'rounded',inactiveDesaturation:0,edgeDirection:'full',panelDepth:.12,progressStyle:'flat',controlStyle:'glass',focusGlowStrength:.12,matteStrength:.15,glossStrength:.12,panelAiriness:.08,
  animatedBackground:'subtle',backgroundAnimationStyle:'fluid',backgroundMixedStyle:'fluid',backgroundFlowUseThemeColors:false,backgroundFlowPrimary:'#65a9fa',backgroundFlowSecondary:'#af92ed',backgroundFlowSpeed:.18,backgroundFlowOpacity:.075,backgroundFlowBlur:.85,backgroundFlowScale:.75,backgroundStreamCount:6,backgroundFlowMix:.85,backgroundStreamsMix:.2,
  hoverGlintPrinters:true,hoverGlintProjects:true,hoverGlintIntensity:.45,hoverGlintDuration:8.5,microAccentIntensity:.08
 },
 paletteEffects:{separate:true,darkBrightness:.075,lightBrightness:.035,darkOpacity:.94,lightOpacity:.98,darkGlow:.12,lightGlow:.04,darkHalo:.05,lightHalo:.02},
 background:{mode:'solid',imageDataUrl:'',overlay:'#000000',overlayOpacity:0,blurPx:0}
};

// Explicit use of schema 12 features while retaining all earlier choices.
Object.assign(theme.typography,{customMetrics:true,bodyWeight:400,headingWeight:600,captionWeight:400,bodyLineHeight:1.45,headingLineHeight:1.2,captionLineHeight:1.35});
Object.assign(theme.shape,{independentRadii:true,buttonRadius:12,inputRadius:10,cardRadius:20});
Object.assign(theme.effects,{glassRefraction:.38,glassBlur:4,glassEdge:.22});
for(const mode of ['dark','light'])Object.assign(theme.paletteEffects,{
 [mode+'UseThemeColors']:false,[mode+'Primary']:mode==='dark'?'#65a9fa':'#90b9ed',[mode+'Secondary']:mode==='dark'?'#af92ed':'#c3ade5',
 [mode+'Shadow']:mode==='dark'?.30:.18,[mode+'Depth']:mode==='dark'?.12:.06,[mode+'Airiness']:mode==='dark'?.08:.04,
 [mode+'Material']:'optical-glass',[mode+'Controls']:'glass',[mode+'Matte']:mode==='dark'?.15:.22,[mode+'Gloss']:mode==='dark'?.12:.08,
 [mode+'Refraction']:mode==='dark'?.38:.25,[mode+'GlassBlur']:mode==='dark'?4:6,[mode+'GlassEdge']:mode==='dark'?.22:.12
});
theme.paletteEffects.darkOpacity=.78;theme.paletteEffects.lightOpacity=.84;
export default theme;
