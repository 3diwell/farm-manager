// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Only typography, border radius and fills on core nodes. Optical processing
// belongs exclusively to glass-layer.js; editor remains independently readable.
export function detailCss(theme){
 const t=theme.typography,s=theme.shape,e=theme.effects;
 const scope='html[data-fm-appearance-active="1"] ';
 const target=list=>list.split(',').map(x=>scope+x+':not(#fm-appearance-editor):not(#fm-appearance-editor *)').join(',');
 const lines=[];
 if(t.customMetrics){
  lines.push(`${scope}{--fm-font-body-weight:${t.bodyWeight};--fm-font-heading-weight:${t.headingWeight};--fm-font-caption-weight:${t.captionWeight};--fm-line-body:${t.bodyLineHeight};--fm-line-heading:${t.headingLineHeight};--fm-line-caption:${t.captionLineHeight};}`);
  lines.push(`${target('#app,button,input,select,textarea,p,td,.printer-card,.plan-cell,.glass-panel,.fm-module')}{font-weight:var(--fm-font-body-weight)!important;line-height:var(--fm-line-body)!important;}`);
  lines.push(`${target('h1,h2,h3,h4,h5,h6,.font-semibold,.font-bold,.ex-title')}{font-weight:var(--fm-font-heading-weight)!important;line-height:var(--fm-line-heading)!important;}`);
  lines.push(`${target('small,.text-xs,.ex-meta,.ex-prev-meta')}{font-weight:var(--fm-font-caption-weight)!important;line-height:var(--fm-line-caption)!important;}`);
 }
 if(s.independentRadii){
  lines.push(`${target('button,.ex-btn,[role="button"]')}{border-radius:${s.buttonRadius}px!important;}`);
  lines.push(`${target('input:not([type="checkbox"]):not([type="radio"]):not([type="range"]),select,textarea')}{border-radius:${s.inputRadius}px!important;}`);
  lines.push(`${target('.printer-card,.plan-cell')}{border-radius:${s.cardRadius}px!important;}`);
 }
 if(e.panelMaterial==='optical-glass')lines.push(`${target('.printer-card,.plan-cell,.glass-panel,.fm-module')}{background-color:rgba(var(--fm-surface-card-rgb),${s.surfaceOpacity})!important;}`);
 return lines.join('\n');
}
