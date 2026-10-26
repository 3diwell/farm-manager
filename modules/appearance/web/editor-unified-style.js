// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Scoped UI layout only; no selectors target the Farm Manager underneath.
export const UNIFIED_CSS=`
#fm-appearance-editor{max-width:1360px;margin-inline:auto}
#fm-appearance-editor .ap-toolbar{display:flex;align-items:center;gap:20px;padding:12px 20px;border-bottom:1px solid var(--ap-border);flex:none}
#fm-appearance-editor .ap-nav{display:flex;gap:4px;padding:0;border:0;overflow:visible;flex:1;flex-wrap:wrap}
#fm-appearance-editor .ap-nav button{display:block;width:auto;margin:0;padding:9px 12px;white-space:nowrap}
#fm-appearance-editor .ap-toolbar input[type=search]{max-width:230px}
#fm-appearance-editor .ap-palette-bar{display:flex;align-items:center;gap:12px;padding:9px 20px;flex:none;border-bottom:1px solid var(--ap-border);position:relative;z-index:2;flex-wrap:wrap}
#fm-appearance-editor .ap-palette-bar button{padding:5px 10px}
#fm-appearance-editor .ap-profile-settings{margin:0 0 0 auto;padding:0;border:0}
#fm-appearance-editor .ap-profile-settings>summary{color:var(--ap-muted);font-weight:400}
#fm-appearance-editor .ap-profile-content{position:absolute;right:12px;top:calc(100% - 1px);width:390px;max-width:calc(100% - 24px);max-height:50vh;overflow:auto;padding:16px;background:var(--ap-panel);border:1px solid var(--ap-border);border-radius:10px;box-shadow:0 12px 30px #0005}
#fm-appearance-editor .ap-body{grid-template-columns:minmax(0,1fr) minmax(280px,350px)}
#fm-appearance-editor .ap-main{padding:8px 24px 28px;scrollbar-gutter:stable}
#fm-appearance-editor .ap-section-head{margin:18px 0 24px}
#fm-appearance-editor .ap-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:24px 20px}
#fm-appearance-editor .ap-field{padding-left:10px;gap:8px}
#fm-appearance-editor .ap-scope{font-size:11px!important;color:var(--ap-muted);opacity:.85}
#fm-appearance-editor .ap-range{display:flex;align-items:center;gap:10px}
#fm-appearance-editor .ap-range input[type=number]{flex:0 0 78px;width:78px;padding:5px 7px}
#fm-appearance-editor .ap-preview{padding:20px 16px;min-width:0}
#fm-appearance-editor .ap-preview>.ap-row{justify-content:space-between;margin-bottom:8px}
#fm-appearance-editor .ap-preview iframe{height:490px}
#fm-appearance-editor .ap-preview>.ap-help{margin-top:8px}
#fm-appearance-editor .ap-detail-group{border:1px solid var(--ap-border);border-radius:10px;padding:0;margin-top:14px;background:var(--ap-panel)}
#fm-appearance-editor .ap-detail-group>summary{padding:15px 16px;line-height:1.6}
#fm-appearance-editor .ap-detail-group>.ap-grid{margin:8px 16px 20px}
#fm-appearance-editor .ap-detail-group>.ap-block,#fm-appearance-editor .ap-detail-group>.ap-note{margin:12px 16px 18px}
#fm-appearance-editor .ap-summary{font-weight:400;margin-top:3px;overflow-wrap:anywhere}
#fm-appearance-editor .ap-theme-gallery{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:16px 0 24px}
#fm-appearance-editor .ap-theme-gallery button{display:flex;flex-direction:column;gap:9px;padding:10px;text-align:left;min-width:0}
#fm-appearance-editor .ap-theme-gallery .ap-thumbnail{width:100%;height:70px;padding:10px;gap:10px}
#fm-appearance-editor .ap-theme-gallery strong{font-size:12px;overflow-wrap:anywhere}
#fm-appearance-editor .ap-block>.ap-row{margin-top:12px}
#fm-appearance-editor .ap-block>.ap-help{margin-top:8px}
#fm-appearance-editor .ap-entry-actions{margin:0;padding:0;border:0}
#fm-appearance-editor .ap-entry-actions summary{font-weight:400;color:var(--ap-muted);padding:6px}
#fm-appearance-editor details:not(.ap-detail-group)> .ap-row{margin-top:10px}
#fm-appearance-editor .ap-foot-status{max-width:40%;min-width:0;overflow-wrap:anywhere}
#fm-appearance-editor :is(button,input,select,textarea,summary):focus-visible{outline:2px solid var(--ap-accent)!important;outline-offset:3px}
#fm-appearance-editor .ap-presets .ap-mini::before,#fm-appearance-editor .ap-presets .ap-mini::after{animation:none!important}
@media(max-width:1100px){#fm-appearance-editor .ap-toolbar{gap:10px;padding-inline:14px}#fm-appearance-editor .ap-toolbar input[type=search]{max-width:185px}#fm-appearance-editor .ap-nav button{padding:8px}#fm-appearance-editor .ap-main{padding-inline:16px}#fm-appearance-editor .ap-grid{grid-template-columns:1fr}#fm-appearance-editor .ap-theme-gallery{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:840px){#fm-appearance-editor .ap-body{display:block;overflow-y:auto}#fm-appearance-editor .ap-main,#fm-appearance-editor .ap-preview{overflow:visible}#fm-appearance-editor .ap-toolbar{flex-wrap:wrap;gap:8px}#fm-appearance-editor .ap-toolbar input[type=search]{max-width:none}#fm-appearance-editor .ap-nav{flex-basis:100%}#fm-appearance-editor .ap-palette-bar{padding:8px 14px;gap:7px}#fm-appearance-editor .ap-palette-bar>.ap-help{display:none}#fm-appearance-editor .ap-grid{grid-template-columns:repeat(2,minmax(0,1fr))}#fm-appearance-editor .ap-preview{border-left:0;border-top:1px solid var(--ap-border)}#fm-appearance-editor .ap-foot-status{max-width:100%;flex-basis:100%;width:100%}}
@media(max-width:510px){#fm-appearance-editor .ap-grid{grid-template-columns:1fr}#fm-appearance-editor .ap-nav{display:grid;grid-template-columns:1fr 1fr}#fm-appearance-editor .ap-nav button{white-space:normal;width:100%;padding:7px}#fm-appearance-editor .ap-theme-gallery{grid-template-columns:repeat(2,minmax(0,1fr))}#fm-appearance-editor .ap-head h2{font-size:17px!important}#fm-appearance-editor .ap-field-heading{flex-wrap:wrap}#fm-appearance-editor .ap-foot{gap:5px}#fm-appearance-editor .ap-foot button{flex:1;font-size:12px!important;padding:7px}#fm-appearance-editor .ap-foot-status>span:first-child{max-height:2.9em;overflow:auto}#fm-appearance-editor .ap-profile-content{max-height:38vh}#fm-appearance-editor .ap-main{padding-inline:12px}}
`;
