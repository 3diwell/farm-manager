// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
export const SOFT_CSS=`
#fm-appearance-editor .ap-body{overflow-y:auto;align-items:start;scrollbar-gutter:stable}
#fm-appearance-editor .ap-main{overflow:visible;scrollbar-gutter:auto}
#fm-appearance-editor .ap-preview{overflow:visible;position:sticky;top:0;align-self:start;border-radius:0 0 0 12px}
#fm-appearance-editor .ap-preview iframe{margin-top:16px;min-height:0;overflow:hidden}
#fm-appearance-editor .ap-grid{gap:24px}
#fm-appearance-editor .ap-field{gap:10px;min-height:70px}
#fm-appearance-editor .ap-field-heading{flex-wrap:wrap}
#fm-appearance-editor button.ap-hint-button{background:transparent!important;border:0!important;border-radius:50%!important;padding:2px 4px;min-width:20px;min-height:20px;color:var(--ap-muted)!important;font-size:11px!important}
#fm-appearance-editor button.ap-value{background:transparent!important;border-color:transparent!important;padding:2px 5px;color:var(--ap-accent)!important}
#fm-appearance-editor .ap-color{align-items:center}
#fm-appearance-editor .ap-color input[type=color]{width:64px!important;flex-basis:64px;height:36px}
#fm-appearance-editor .ap-field .ap-scope{margin-top:4px}
#fm-appearance-editor .ap-fine-settings{margin-top:26px;border:1px solid var(--ap-border);border-radius:12px;padding:0}
#fm-appearance-editor .ap-fine-settings>summary{padding:16px;font-size:14px;font-weight:500}
#fm-appearance-editor .ap-fine-settings>summary>.ap-help{font-weight:400;margin-top:5px}
#fm-appearance-editor .ap-fine-settings>.ap-detail-group{margin:0 12px 12px;border-radius:8px}
#fm-appearance-editor .ap-summary{font-size:11px!important;opacity:.85}
#fm-appearance-editor .ap-theme-gallery{grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:18px 0}
#fm-appearance-editor .ap-theme-gallery>button{display:flex;gap:7px;border-radius:12px!important;padding:10px;text-align:left;background:var(--ap-panel)!important;transition:border-color .12s}
#fm-appearance-editor .ap-theme-gallery>button[aria-pressed=true]{border-color:var(--ap-accent)!important}
#fm-appearance-editor .ap-theme-scene{height:140px;width:100%;position:relative;isolation:isolate;overflow:hidden;background:var(--tile-bg);border-radius:8px;padding:12px;color:var(--tile-text);border:1px solid var(--tile-border)}
#fm-appearance-editor .ap-theme-scene::before{content:'';position:absolute;inset:0;z-index:-1;opacity:var(--tile-ambient);background:radial-gradient(ellipse at 15% 85%,var(--tile-accent),transparent 70%),radial-gradient(ellipse at 85% 20%,var(--tile-secondary),transparent 65%)}
#fm-appearance-editor .ap-scene-header{display:flex;align-items:center;gap:5px;border:1px solid var(--tile-border);border-radius:5px;background:var(--tile-header);padding:5px 7px;font-size:10px;margin-bottom:9px;height:24px}
#fm-appearance-editor .ap-scene-header span{margin-right:auto;font-weight:700}
#fm-appearance-editor .ap-scene-header i{width:15px;height:3px;background:var(--tile-muted);opacity:.4;border-radius:2px}
#fm-appearance-editor .ap-scene-cards{display:grid;grid-template-columns:1fr 1fr;gap:8px}
#fm-appearance-editor .ap-scene-card{padding:9px;background:var(--tile-card);border:1px solid var(--tile-border);border-radius:var(--tile-radius);box-shadow:var(--tile-shadow);min-width:0}
#fm-appearance-editor .ap-scene-title{font-size:10px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600}
#fm-appearance-editor .ap-scene-title b{float:right;color:var(--tile-accent);font-size:7px}
#fm-appearance-editor .ap-scene-line{display:block;width:55%;height:3px;background:var(--tile-muted);opacity:.25;margin-top:6px;border-radius:2px}
#fm-appearance-editor .ap-scene-progress{display:block;width:100%;height:4px;background:var(--tile-border);margin:9px 0 5px;border-radius:3px;overflow:hidden}
#fm-appearance-editor .ap-scene-progress i{display:block;width:48%;height:100%;background:var(--tile-accent)}
#fm-appearance-editor .ap-scene-caption{font-size:8px;color:var(--tile-muted)}
#fm-appearance-editor .ap-theme-caption{display:flex;width:100%;align-items:center;gap:7px;padding:3px 2px 0}
#fm-appearance-editor .ap-theme-caption strong{font-size:14px;font-weight:600}
#fm-appearance-editor .ap-theme-selected{font-size:10px;color:var(--ap-accent);margin-left:auto}
#fm-appearance-editor .ap-theme-gallery>button>.ap-help{font-size:11px!important;padding-inline:2px}
#fm-appearance-editor .ap-theme-actions{margin-top:16px}
#fm-appearance-editor .ap-theme-actions>.ap-help{font-size:11px!important}
#fm-appearance-editor .ap-copy-form{padding:16px;background:var(--ap-panel);border:1px solid var(--ap-border);border-radius:10px}
#fm-appearance-editor .ap-my-themes>summary{padding-block:4px}
#fm-appearance-editor .ap-palette-bar{font-size:12px}
@media(max-width:840px){#fm-appearance-editor .ap-preview{position:static;max-width:500px;margin:20px auto 0;border:1px solid var(--ap-border);border-radius:12px}#fm-appearance-editor .ap-body{display:block}#fm-appearance-editor .ap-main{overflow:visible}}
@media(max-width:510px){#fm-appearance-editor .ap-head{flex-wrap:nowrap;align-items:flex-start}#fm-appearance-editor .ap-head>div{min-width:0}#fm-appearance-editor .ap-head>button{flex-shrink:0}#fm-appearance-editor .ap-theme-gallery{gap:10px}#fm-appearance-editor .ap-theme-gallery>button{padding:7px}#fm-appearance-editor .ap-theme-scene{height:140px;padding:8px}#fm-appearance-editor .ap-scene-cards{grid-template-columns:1fr}#fm-appearance-editor .ap-scene-card:nth-child(2){display:none}#fm-appearance-editor .ap-scene-card{padding:10px}#fm-appearance-editor .ap-theme-caption{flex-wrap:wrap}#fm-appearance-editor .ap-theme-selected{margin-left:0}#fm-appearance-editor .ap-preview{margin-inline:8px;padding:14px 10px}#fm-appearance-editor .ap-fine-settings>summary>.ap-help{font-size:11px!important}}
`;
