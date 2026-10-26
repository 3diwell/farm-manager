// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Модуль «Уведомления в мессенджеры» — ОБЩАЯ РЕАЛИЗАЦИЯ: логика (useMessengers), свойства
// (MESSENGERS_PROPS) и разметка содержимого (MESSENGERS_BODY). Показывает это MessengersSettings.js —
// ячейка в «Настройки → Модули».
//
// 0.1.6 (заказ владельца 11.09.2026): у модуля ОДНИ НАСТРОЙКИ, поэтому своего окна у него больше
// нет — в module.json не объявлен entry, только settings_entry. Ядро такой модуль не выводит ни
// кнопкой на баре, ни плиткой запуска: он живёт единственной ячейкой внутри настроек.
//
// Стили инлайном на CSS-переменных темы; иконки — глобальный <svg-icon>.
//
// 0.1.1 (поправка владельца 11.09.2026 «где брать этот ключ? описания никакого не было»):
//   · на КАЖДОМ шаге написано, что нажать, что ответить и что придёт в ответ;
//   · кнопка «Назад» между шагами — раньше вернуться к ссылке на BotFather было нечем;
//   · на шаге с ключом — вторая кнопка «Открыть @BotFather ещё раз» и готовый адрес бота
//     с кнопкой «Копировать» (чтобы не придумывать адрес и не ловить «занято»);
//   · сверху — короткая честная справка, почему один шаг всё-таки делается руками.
// Права: единственный источник решения — props.access.can('admin') (contract ядра); своей таблицы
// прав у модуля нет. Секреты окно не хранит: сервер отдаёт «ключ задан», ключ вводится один раз.
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue';

const STYLE_ID = 'msg-panel-styles';
const MSG_CSS = [
  '.msg-ico svg{width:24px;height:24px;display:block}',
  '.msg-body{flex:1 1 auto;min-height:0;overflow:auto;padding:16px 20px 20px;display:flex;flex-direction:column;gap:14px}',
  '.msg-how{border:1px solid var(--fm-border);border-radius:12px;background:var(--fm-surface-raised);padding:11px 14px;font-size:12.5px;color:var(--fm-text-secondary);line-height:1.5}',
  '.msg-how b{color:var(--fm-text-primary)}',
  '.msg-card{border:1px solid var(--fm-border);border-radius:14px;background:var(--fm-surface-card);padding:14px 16px}',
  '.msg-card.on{border-color:color-mix(in srgb,var(--fm-accent) 55%,var(--fm-border))}',
  '.msg-card-h{display:flex;align-items:center;gap:12px;flex-wrap:wrap}',
  '.msg-title{font-size:15px;font-weight:800;color:var(--fm-text-primary)}',
  '.msg-pill{font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px;border:1px solid var(--fm-border);color:var(--fm-text-muted);white-space:nowrap}',
  '.msg-pill.ok{color:var(--fm-success);border-color:color-mix(in srgb,var(--fm-success) 55%,var(--fm-border))}',
  '.msg-pill.bad{color:var(--fm-danger);border-color:color-mix(in srgb,var(--fm-danger) 55%,var(--fm-border))}',
  '.msg-pill.wait{color:var(--fm-accent);border-color:color-mix(in srgb,var(--fm-accent) 55%,var(--fm-border))}',
  '.msg-note{font-size:12.5px;color:var(--fm-text-muted);line-height:1.45;margin-top:6px}',
  '.msg-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px}',
  '.msg-btn{font-size:13px;font-weight:700;padding:8px 14px;border-radius:9px;border:1px solid var(--fm-border-strong);background:var(--fm-surface-control);color:var(--fm-text-primary);cursor:pointer;line-height:1.2;white-space:nowrap;text-decoration:none;display:inline-flex;align-items:center;gap:6px}',
  '.msg-btn:hover{border-color:var(--fm-accent)}',
  '.msg-btn.pri{background:color-mix(in srgb,var(--fm-accent) 24%,var(--fm-surface-control));border-color:color-mix(in srgb,var(--fm-accent) 65%,var(--fm-border-strong))}',
  '.msg-btn.ghost{background:transparent;color:var(--fm-text-secondary);font-weight:600}',
  '.msg-btn.big{font-size:14px;padding:10px 18px}',
  '.msg-btn:disabled{opacity:.5;cursor:default}',
  '.msg-steps{display:flex;flex-direction:column;gap:10px;margin-top:12px}',
  '.msg-step{display:flex;gap:12px;padding:12px 14px;border-radius:12px;border:1px solid var(--fm-border);background:var(--fm-surface-raised);opacity:.5}',
  '.msg-step.cur{opacity:1;border-color:color-mix(in srgb,var(--fm-accent) 55%,var(--fm-border))}',
  '.msg-step.done{opacity:.75}',
  '.msg-step-n{flex:0 0 28px;width:28px;height:28px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:13px;background:var(--fm-surface-control);color:var(--fm-text-primary);border:1px solid var(--fm-border-strong)}',
  '.msg-step.done .msg-step-n{background:color-mix(in srgb,var(--fm-success) 30%,var(--fm-surface-control));color:var(--fm-success)}',
  '.msg-step-b{display:flex;flex-direction:column;gap:6px;min-width:0;flex:1 1 auto}',
  '.msg-step-t{font-size:13.5px;font-weight:700;color:var(--fm-text-primary)}',
  '.msg-step-x{font-size:12.5px;color:var(--fm-text-secondary);line-height:1.5;white-space:pre-line}',
  '.msg-sug{display:flex;flex-direction:column;gap:5px;padding:9px 11px;border-radius:9px;border:1px dashed var(--fm-border-strong);background:rgba(var(--fm-black-rgb),.25)}',
  '.msg-sug-l{font-size:11.5px;color:var(--fm-text-muted)}',
  '.msg-sug-v{display:flex;align-items:center;gap:8px;flex-wrap:wrap}',
  '.msg-sug-v code{font-family:ui-monospace,Consolas,monospace;font-size:13px;font-weight:700;color:var(--fm-accent);word-break:break-all}',
  '.msg-in{width:100%;max-width:520px;height:34px;box-sizing:border-box;padding:0 10px;border-radius:8px;border:1px solid var(--fm-border-strong);background:rgba(var(--fm-black-rgb),.4);color:var(--fm-text-primary);font-size:13px}',
  '.msg-in:focus{outline:none;border-color:var(--fm-accent)}',
  '.msg-wait{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;color:var(--fm-accent)}',
  '.msg-spin{width:14px;height:14px;border-radius:50%;border:2px solid color-mix(in srgb,var(--fm-accent) 35%,transparent);border-top-color:var(--fm-accent);animation:msg-spin .9s linear infinite}',
  '@keyframes msg-spin{to{transform:rotate(360deg)}}',
  '.msg-err{font-size:12.5px;color:var(--fm-danger)}',
  '.msg-ok{font-size:12.5px;color:var(--fm-success)}',
  '.msg-fields{display:flex;flex-direction:column;gap:8px;margin-top:10px}',
  '.msg-f{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center}',
  '.msg-f-l{flex:1 1 220px;display:flex;flex-direction:column;gap:2px;min-width:0}',
  '.msg-f-l b{font-size:12.5px;color:var(--fm-text-primary)}',
  '.msg-f-l span{font-size:11.5px;color:var(--fm-text-muted)}',
  '.msg-f .msg-in{flex:1 1 240px;width:auto}',
  '.msg-ev{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 18px;margin-top:8px}',
  '@media (max-width:760px){.msg-ev{grid-template-columns:1fr}}',
  '.msg-chk{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--fm-text-primary);cursor:pointer}',
  '.msg-chk input{width:16px;height:16px;accent-color:var(--fm-accent)}',
  '.msg-last{font-size:11.5px;color:var(--fm-text-muted);margin-top:8px}',
  '.msg-last.bad{color:var(--fm-danger)}',
  '.msg-vars{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 2px}',
  '.msg-var{font:inherit;font-size:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;padding:3px 9px;border-radius:999px;border:1px solid var(--fm-border-strong);background:transparent;color:var(--fm-text-secondary);cursor:pointer}',
  '.msg-var:hover{color:var(--fm-text-primary);border-color:var(--fm-accent)}',
  '.msg-tpl{margin-top:10px;padding-top:10px;border-top:1px solid var(--fm-border)}',
  '.msg-tpl-h{display:flex;align-items:center;gap:8px;min-height:26px}',
  '.msg-tpl-t{font-size:13px;font-weight:700;color:var(--fm-text-primary)}',
  '.msg-tpl-b{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;margin-top:6px}',
  '@media (max-width:760px){.msg-tpl-b{grid-template-columns:1fr}}',
  '.msg-ta{width:100%;box-sizing:border-box;min-height:78px;padding:8px 10px;border-radius:10px;border:1px solid var(--fm-border-strong);background:rgba(var(--fm-black-rgb),.4);color:var(--fm-text-primary);font:inherit;font-size:13px;line-height:1.45;resize:vertical}',
  '.msg-ta:focus{outline:none;border-color:var(--fm-accent)}',
  '.msg-prev{white-space:pre-line;font-size:13px;line-height:1.5;padding:8px 10px;border-radius:10px;background:var(--fm-surface-raised);border:1px solid var(--fm-border);color:var(--fm-text-primary);min-height:78px;box-sizing:border-box}',
  '.msg-prev-l{font-size:11px;color:var(--fm-text-subtle);margin-bottom:3px}',
  '.msg-btn.sm{padding:4px 9px;font-size:12px}',
  '.msg-sel{height:30px;border-radius:8px;border:1px solid var(--fm-border-strong);background:var(--fm-surface-control);color:var(--fm-text-primary);font-size:12.5px;padding:0 8px}',
].join('\n');
function ensureStyles() {
  try {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    const s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = MSG_CSS;
    document.head.appendChild(s);
  } catch (e) { /* стиль не критичен для работы окна */ }
}

// Готовый адрес бота: латиница, заканчивается на bot, 5-32 знака (правила Telegram).
// Случайный хвост — чтобы адрес не оказался занятым и человеку не пришлось придумывать заново.
function suggestBotUsername() {
  const abc = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let tail = '';
  for (let i = 0; i < 5; i++) tail += abc[Math.floor(Math.random() * abc.length)];
  return 'ferma_' + tail + '_bot';
}
async function copyText(v) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(v); return true; }
  } catch (e) { /* ниже запасной путь */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = v; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch (e) { return false; }
}

const REASON_RU = {
  ok: 'доставлено', disabled: 'канал выключен', not_configured: 'не заполнены обязательные поля',
  bad_request: 'площадка отвергла параметры', bad_token: 'ключ не принят — проверьте, что скопировали его целиком',
  no_permission: 'у ключа нет права «Сообщения сообщества» — создайте ключ заново и отметьте это право',
  messages_off: 'в сообществе выключены сообщения: Управление → Сообщения → включить и сохранить', bad_recipient: 'получатель не найден',
  recipient_not_allowed: 'получатель должен сам написать первым или разрешить сообщения',
  too_long: 'сообщение слишком длинное', rate_limited: 'слишком часто — площадка просит подождать',
  network: 'нет связи с площадкой', platform_error: 'ошибка площадки', bad_response: 'непонятный ответ площадки',
  unknown_kind: 'неизвестная площадка', write_failed: 'не удалось сохранить настройки',
};
const REASON_EN = {
  ok: 'delivered', disabled: 'channel is off', not_configured: 'required fields are empty',
  bad_request: 'the platform rejected the parameters', bad_token: 'token rejected — check that you copied it whole',
  no_permission: 'the token lacks the community messages permission — create it again with that permission',
  messages_off: 'community messages are off: Manage → Messages → enable and save', bad_recipient: 'recipient not found',
  recipient_not_allowed: 'the recipient must write first or allow messages',
  too_long: 'message too long', rate_limited: 'too frequent — the platform asks to wait',
  network: 'no connection to the platform', platform_error: 'platform error', bad_response: 'unexpected reply from the platform',
  unknown_kind: 'unknown platform', write_failed: 'could not save the settings',
};
const EVENT_RU = {
  print_finished: 'Печать завершена', print_failed: 'Печать прервана сбоем', print_cancelled: 'Печать остановлена',
  printer_error: 'Ошибка принтера', printer_notice: 'Уведомление на экране принтера (критичное и серьёзное)',
  printer_offline: 'Нет связи с принтером дольше 3 минут (и восстановление)',
};
const EVENT_EN = {
  print_finished: 'Print finished', print_failed: 'Print failed', print_cancelled: 'Print cancelled',
  printer_error: 'Printer error', printer_notice: 'Notice on the printer screen (fatal and serious)',
  printer_offline: 'Printer offline for over 3 minutes (and back online)',
};

//  3.000: логика и содержимое вынесены отдельно — их использует и окно модуля,
//  и ВСТРОЕННАЯ ячейка настроек (MessengersSettings.js). Реализация одна.
export function useMessengers(props) {
    ensureStyles();
    const L = (ru, en) => (props.lang === 'ru' ? ru : en);
    const CAP_CONTRACT_VERSION = 1;
    const capReady = computed(() => {
      const a = props.access;
      return !!(a && a.contractVersion === CAP_CONTRACT_VERSION && typeof a.can === 'function');
    });
    const can = (cap) => (capReady.value ? !!props.access.can(cap) : false);
    const isAdmin = computed(() => can('admin'));

    const loading = ref(true);
    const loadError = ref('');
    const settings = ref({ lang: 'ru', channels: {}, events: {} });
    const catalog = ref([]);
    const events = ref([]);
    const chStatus = ref({});
    const pairing = ref({});
    const wiz = reactive({});        // kind -> { step, token, busy, error, link, botName, done, open, suggest, copied }
    const note = reactive({});       // kind -> { ok, text }
    const adv = reactive({});        // kind -> поля формы (WhatsApp)
    const evBusy = ref(false);
    const evNote = ref('');
    let pollTimer = null;

    const api = async (path, opts) => {
      const r = await fetch('/api/mod/messengers/' + path, Object.assign({ cache: 'no-store' }, opts || {}));
      let j = null;
      try { j = await r.json(); } catch (e) { j = null; }
      if (r.status === 401 || r.status === 403) {
        try { if (props.access && typeof props.access.revalidate === 'function') props.access.revalidate(); } catch (e) {}
        return { status: 'error', reason: 'forbidden', http: r.status };
      }
      return j || { status: 'error', reason: 'bad_response', http: r.status };
    };
    const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    const reasonText = (r) => ((props.lang === 'ru' ? REASON_RU : REASON_EN)[r] || r || '');
    const eventLabel = (k) => ((props.lang === 'ru' ? EVENT_RU : EVENT_EN)[k] || k);

    const load = async () => {
      loading.value = true; loadError.value = '';
      const j = await api('settings?lang=' + (props.lang === 'ru' ? 'ru' : 'en'));
      if (!j || j.status !== 'ok') {
        loadError.value = j && j.reason === 'forbidden'
          ? L('Настраивать уведомления может только администратор.', 'Only an administrator can set up notifications.')
          : L('Не удалось загрузить настройки модуля.', 'Could not load the module settings.');
        loading.value = false; return;
      }
      settings.value = j.settings || settings.value;
      catalog.value = j.catalog || [];
      events.value = Array.isArray(j.events) ? j.events : Object.keys((j.settings || {}).events || {});
      chStatus.value = j.channel_status || {};
      pairing.value = j.pairing || {};
      tplMeta.value = Object.assign({ defaults: {}, vars: [], hints: {}, sample: {}, preview: {} }, j.templates || {});
      tplInit();
      for (const p of catalog.value) {
        if (!wiz[p.kind]) wiz[p.kind] = { step: 0, token: '', busy: false, error: '', link: '', botName: '', done: false, open: false, suggest: suggestBotUsername(), copied: false };
        if (!adv[p.kind]) {
          const row = {};
          const ch = (settings.value.channels || {})[p.kind] || {};
          for (const f of (p.fields || [])) if (!f.info) row[f.key] = f.secret ? '' : (ch[f.key] || '');
          adv[p.kind] = row;
        }
        // мастер, который ждал человека в момент открытия окна: показать последний шаг
        const ps = pairing.value[p.kind];
        if (ps && ps.state === 'waiting' && p.has_wizard) { wiz[p.kind].open = true; wiz[p.kind].step = ((p.wizard || []).length - 1); wiz[p.kind].link = ps.link || ''; wiz[p.kind].botName = ps.bot_name || ''; startPolling(p.kind); }
      }
      loading.value = false;
    };

    const channel = (kind) => (settings.value.channels || {})[kind] || {};
    const connected = (kind) => !!channel(kind).connected;
    const enabled = (kind) => !!channel(kind).enabled;
    const pillClass = (kind) => {
      const ps = pairing.value[kind] || {};
      if (wiz[kind] && wiz[kind].open && ps.state === 'waiting') return 'wait';
      if (connected(kind) && enabled(kind)) return 'ok';
      if (ps.state === 'error') return 'bad';
      return '';
    };
    const pillText = (kind) => {
      const ps = pairing.value[kind] || {};
      if (wiz[kind] && wiz[kind].open && ps.state === 'waiting') return L('Подключение…', 'Connecting…');
      if (connected(kind)) {
        const lbl = channel(kind).connected_label || '';
        return (enabled(kind) ? L('Подключён', 'Connected') : L('Выключен', 'Off')) + (lbl ? ' · ' + lbl : '');
      }
      return L('Не подключён', 'Not connected');
    };
    const lastLine = (kind) => {
      const s = chStatus.value[kind];
      if (!s) return '';
      const head = s.ok ? L('Последняя отправка: доставлено', 'Last send: delivered') : (L('Последняя отправка: ', 'Last send: ') + reasonText(s.reason));
      return head + (s.at ? ' · ' + s.at : '') + ((s.detail && !s.ok) ? ' · ' + s.detail : '');
    };
    const setNote = (kind, ok, text) => { note[kind] = { ok, text }; };

    // ── мастер ──────────────────────────────────────────────────────────────────────────
    const openWizard = (kind) => { if (!isAdmin.value) return; const w = wiz[kind]; w.open = true; w.step = 0; w.error = ''; w.done = false; w.token = ''; w.copied = false; };
    const closeWizard = async (kind) => {
      const w = wiz[kind]; w.open = false; stopPolling();
      const ps = pairing.value[kind] || {};
      if (ps.state === 'waiting') await post('pair/stop', { kind });
      await load();
    };
    const lastStep = (kind) => {
        const p = catalog.value.find((x) => x.kind === kind);
        return Math.max(0, ((p && p.wizard) || []).length - 1);
    };
    const nextStep = (kind) => { wiz[kind].error = ''; wiz[kind].step = Math.min(wiz[kind].step + 1, lastStep(kind)); };
    // Назад: со страницы ожидания возвращаемся к вводу ключа, остановив ожидание на сервере.
    const prevStep = async (kind) => {
      const w = wiz[kind];
      const ps = pairing.value[kind] || {};
      if (ps.state === 'waiting') { stopPolling(); await post('pair/stop', { kind }); pairing.value = Object.assign({}, pairing.value, { [kind]: { kind, state: 'stopped' } }); }
      w.error = ''; w.step = Math.max(0, w.step - 1);
    };
    const copySuggest = async (kind) => {
      const w = wiz[kind];
      w.copied = await copyText(w.suggest);
      if (w.copied) setTimeout(() => { w.copied = false; }, 2500);
    };
    const startPairing = async (kind) => {
      const w = wiz[kind];
      if (!isAdmin.value) return;
      const token = String(w.token || '').trim();
      if (!token) { w.error = L('Вставьте ключ — он приходит от бота на прошлом шаге.', 'Paste the token — it comes from the previous step.'); return; }
      w.busy = true; w.error = '';
      const j = await post('pair/start', { kind, token });
      w.busy = false;
      const ps = (j && j.pairing) || {};
      pairing.value = Object.assign({}, pairing.value, { [kind]: ps });
      if (j && j.status === 'ok' && ps.state === 'waiting') {
        w.link = ps.link || ''; w.botName = ps.bot_name || ''; w.step = lastStep(kind); w.token = '';
        startPolling(kind);
      } else {
        w.error = reasonText(ps.reason || (j && j.reason) || 'platform_error') + (ps.detail ? ' · ' + ps.detail : '');
      }
    };
    const startPolling = (kind) => {
      stopPolling();
      pollTimer = setInterval(async () => {
        const j = await api('pair/status?kind=' + encodeURIComponent(kind));
        const ps = (j && j.pairing) || {};
        pairing.value = Object.assign({}, pairing.value, { [kind]: ps });
        if (ps.state === 'paired') {
          stopPolling();
          await load();
          wiz[kind].open = true; wiz[kind].done = true; wiz[kind].step = lastStep(kind) + 1;
        } else if (ps.state === 'error' || ps.state === 'timeout' || ps.state === 'stopped') {
          stopPolling();
          const w = wiz[kind];
          if (ps.state !== 'stopped') w.step = Math.max(0, lastStep(kind) - 1);
          w.error = ps.state === 'timeout' ? L('Не дождался нажатия. Откройте бота и нажмите Start, потом попробуйте ещё раз.', 'Timed out. Open the bot, press Start and try again.')
                  : ps.state === 'stopped' ? '' : (reasonText(ps.reason) + (ps.detail ? ' · ' + ps.detail : ''));
        }
      }, 2000);
    };
    const stopPolling = () => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } };

    // ── действия с каналом ──────────────────────────────────────────────────────────────
    const setEnabled = async (kind, v) => {
      if (!isAdmin.value) return;
      const j = await post('settings', { channels: { [kind]: { enabled: !!v } } });
      if (j && j.status === 'ok') settings.value = j.settings || settings.value; else setNote(kind, false, reasonText('write_failed'));
    };
    const sendTest = async (kind) => {
      if (!isAdmin.value) return;
      setNote(kind, true, L('Отправляю пробное…', 'Sending a test…'));
      const j = await post('test', { kind });
      const r = (j && j.result) || {};
      if (j && j.status === 'ok') setNote(kind, true, L('Пробное сообщение доставлено — проверьте телефон.', 'Test message delivered — check your phone.'));
      else setNote(kind, false, reasonText(r.reason || (j && j.reason)) + (r.detail ? ' · ' + r.detail : ''));
      chStatus.value = Object.assign({}, chStatus.value, { [kind]: { ok: !!r.ok, reason: r.reason, detail: r.detail, at: new Date().toLocaleString() } });
    };
    const saveAdvanced = async (kind, test) => {
      if (!isAdmin.value) return;
      const row = adv[kind] || {};
      const ch = {};
      for (const k of Object.keys(row)) ch[k] = row[k] == null ? '' : String(row[k]);
      const j = await post('settings', { channels: { [kind]: ch } });
      if (!(j && j.status === 'ok')) { setNote(kind, false, reasonText('write_failed')); return; }
      settings.value = j.settings || settings.value;
      const p = catalog.value.find((x) => x.kind === kind);
      for (const f of ((p && p.fields) || [])) if (f.secret && adv[kind]) adv[kind][f.key] = '';
      setNote(kind, true, L('Сохранено', 'Saved'));
      if (test) await sendTest(kind);
    };
    const secretPlaceholder = (kind, f) => {
      const ch = channel(kind);
      if (!f.secret || !ch[f.key + '_set']) return f.placeholder || '';
      const tail = ch[f.key + '_tail'] || '';
      return L('сохранён', 'saved') + (tail ? ' ····' + tail : '');
    };

    // ── шаблоны сообщений (2.1007) ──────────────────────────────────────────────────────
    //  Живой предпросмотр считается здесь тем же правилом, что и на сервере: подстановки в
    //  фигурных скобках, строка со сплошь пустыми подстановками выбрасывается, висящие « · »
    //  убираются. Образцы данных приходят с сервера — окно их не выдумывает.
    const tplMeta = ref({ defaults: {}, vars: [], hints: {}, sample: {}, preview: {} });
    const tpl = reactive({});
    const tplBusy = ref(false);
    const tplNote = ref('');
    const tplFocus = ref('');
    const renderTpl = (t, ctx) => {
      const out = [];
      for (const raw of String(t || '').split('\n')) {
        const names = []; raw.replace(/\{([a-z_]+)\}/g, (m, n) => { names.push(n); return m; });
        const known = names.filter((n) => n in (ctx || {})).map((n) => String((ctx || {})[n] || ''));
        if (known.length && known.every((v) => v === '')) continue;
        let line = raw.replace(/\{([a-z_]+)\}/g, (m, n) => (n in (ctx || {}) ? String((ctx || {})[n] || '') : m));
        line = line.split(' · ').map((p) => p.trim()).filter(Boolean).join(' · ').replace(/«»|\(\)|\[\]/g, '').replace(/[ \t]{2,}/g, ' ').trim();
        if (line) out.push(line);
      }
      return out.join('\n').trim();
    };
    const tplSaved = (k) => ((settings.value.templates || {})[k] || (tplMeta.value.defaults || {})[k] || '');
    const tplInit = () => { for (const k of events.value) tpl[k] = tplSaved(k); };
    const tplPreview = (k) => renderTpl(tpl[k], (tplMeta.value.sample || {})[k] || {});
    const tplIsDefault = (k) => (tpl[k] || '').trim() === ((tplMeta.value.defaults || {})[k] || '').trim();
    const tplDirty = computed(() => events.value.some((k) => (tpl[k] || '').trim() !== tplSaved(k).trim()));
    const resetTemplate = (k) => { tpl[k] = (tplMeta.value.defaults || {})[k] || ''; };
    const insertVar = (v) => { const k = tplFocus.value || events.value[0]; if (!k) return; tpl[k] = (tpl[k] || '').replace(/\s+$/, '') + (tpl[k] ? ' ' : '') + '{' + v + '}'; };
    const varHint = (v) => ((tplMeta.value.hints || {})[v] || v);
    const saveTemplates = async () => {
      if (!isAdmin.value) return;
      const body = {};
      for (const k of events.value) body[k] = tplIsDefault(k) ? '' : String(tpl[k] || '');
      tplBusy.value = true;
      const j = await post('settings', { templates: body });
      tplBusy.value = false;
      if (j && j.status === 'ok') { settings.value = j.settings || settings.value; tplInit(); tplNote.value = L('Сохранено', 'Saved'); setTimeout(() => { tplNote.value = ''; }, 1500); }
      else tplNote.value = reasonText('write_failed');
    };

    // ── события ─────────────────────────────────────────────────────────────────────────
    const toggleEvent = async (k, v) => {
      if (!isAdmin.value) return;
      evBusy.value = true;
      const j = await post('settings', { events: { [k]: !!v } });
      evBusy.value = false;
      if (j && j.status === 'ok') { settings.value = j.settings || settings.value; evNote.value = L('Сохранено', 'Saved'); setTimeout(() => { evNote.value = ''; }, 1500); }
      else evNote.value = reasonText('write_failed');
    };
    const setLang = async (v) => {
      if (!isAdmin.value) return;
      const j = await post('settings', { lang: v });
      if (j && j.status === 'ok') settings.value = j.settings || settings.value;
    };

    onMounted(load);
    onBeforeUnmount(stopPolling);
    return { L, isAdmin, loading, loadError, settings, catalog, events, chStatus, pairing, wiz, note, adv, evBusy, evNote,
             channel, connected, enabled, pillClass, pillText, lastLine, reasonText, eventLabel,
             openWizard, closeWizard, nextStep, prevStep, lastStep, copySuggest, startPairing, setEnabled, sendTest, saveAdvanced, secretPlaceholder, toggleEvent, setLang,
             tplMeta, tpl, tplBusy, tplNote, tplFocus, tplPreview, tplIsDefault, tplDirty, resetTemplate, insertVar, varHint, saveTemplates };
}

//  Свойства окна и ячейки одинаковы: язык и права от ядра; у окна добавляется open.
const MESSENGERS_PROPS = {
  lang: { type: String, default: 'ru' },
  // Единый capability contract окна модуля (ядро Alpha 2.793): решение принимает ядро своим
  // can(); модуль спрашивает право, а не «кто ты». Нет контракта -> только чтение.
  access: { type: Object, default: null },
};

export { MESSENGERS_PROPS };

//  Содержимое: карточки площадок, шаги мастера, выбор событий. Одно и то же в окне и в ячейке.
export const MESSENGERS_BODY = `
        <div v-if="loading" class="msg-note">{{ L('Загружаю…','Loading…') }}</div>
        <div v-else-if="loadError" class="msg-err">{{ loadError }}</div>
        <template v-else>
          <div class="msg-how" data-msg-how>
            <b>{{ L('Как это работает.','How this works.') }}</b>
            {{ L('Сообщения вам присылает ваш собственный бот в Telegram (или ваше сообщество ВКонтакте). Один раз его нужно создать — и Telegram, и ВКонтакте не дают программам делать это самим, это их защита от рассылок. Создание занимает минуту: нажать кнопку, отправить готовую команду, ответить на два вопроса и скопировать ключ. Всё остальное — найти ваш чат, включить канал, проверить связь — программа делает сама. На каждом шаге ниже написано, что нажимать.','Messages are sent to you by your own Telegram bot (or your own VK community). It has to be created once — neither Telegram nor VK lets programs do that on their own, it is their protection against spam. It takes a minute: press a button, send a ready-made command, answer two questions and copy the token. Everything else — finding your chat, enabling the channel, checking the connection — the program does itself. Each step below says what to press.') }}
          </div>
          <div v-if="!isAdmin" class="msg-note">{{ L('Просмотр: менять настройки может только администратор.','Read-only: only an administrator can change the settings.') }}</div>

          <div v-for="p in catalog" :key="p.kind" class="msg-card" :class="{ on: connected(p.kind) && enabled(p.kind) }" :data-msg-kind="p.kind">
            <div class="msg-card-h">
              <span class="msg-title">{{ p.title }}</span>
              <span class="msg-pill" :class="pillClass(p.kind)">{{ pillText(p.kind) }}</span>
              <label v-if="connected(p.kind)" class="msg-chk" style="margin-left:auto"><input type="checkbox" :checked="enabled(p.kind)" :disabled="!isAdmin" @change="setEnabled(p.kind, $event.target.checked)"><span>{{ L('присылать сообщения','send messages') }}</span></label>
            </div>
            <div class="msg-note">{{ p.note }}</div>

            <!-- Площадка с мастером: Telegram, VK -->
            <template v-if="p.has_wizard">
              <div v-if="!wiz[p.kind].open" class="msg-row">
                <button v-if="!connected(p.kind)" type="button" class="msg-btn pri big" :disabled="!isAdmin" data-msg-connect @click="openWizard(p.kind)">{{ L('Подключить','Connect') }}</button>
                <template v-else>
                  <button type="button" class="msg-btn" :disabled="!isAdmin" @click="sendTest(p.kind)">{{ L('Проверить','Test') }}</button>
                  <button type="button" class="msg-btn ghost" :disabled="!isAdmin" @click="openWizard(p.kind)">{{ L('Переподключить','Reconnect') }}</button>
                </template>
                <span v-if="note[p.kind]" :class="note[p.kind].ok ? 'msg-ok' : 'msg-err'">{{ note[p.kind].text }}</span>
              </div>
              <div v-else class="msg-steps" data-msg-wizard>
                <div v-for="(s, i) in p.wizard" :key="i" class="msg-step" :class="{ cur: wiz[p.kind].step === i, done: wiz[p.kind].step > i }">
                  <span class="msg-step-n">{{ wiz[p.kind].step > i ? '✓' : (s.n || (i + 1)) }}</span>
                  <div class="msg-step-b">
                    <span class="msg-step-t">{{ s.title }}</span>
                    <span class="msg-step-x">{{ s.text }}</span>
                    <template v-if="wiz[p.kind].step === i">
                      <div v-if="s.suggest" class="msg-sug" data-msg-suggest>
                        <span class="msg-sug-l">{{ s.suggest_label }}</span>
                        <span class="msg-sug-v"><code>{{ wiz[p.kind].suggest }}</code>
                          <button type="button" class="msg-btn ghost" data-msg-copy @click="copySuggest(p.kind)">{{ wiz[p.kind].copied ? L('Скопировано','Copied') : L('Копировать','Copy') }}</button>
                        </span>
                      </div>
                      <div v-if="s.next" class="msg-row">
                        <a v-if="s.url" class="msg-btn pri" :href="s.url" target="_blank" rel="noopener" data-msg-site>{{ s.button }} ›</a>
                        <a v-if="s.link_url" class="msg-btn" :href="s.link_url" target="_blank" rel="noopener" data-msg-site>{{ s.link_button }} ›</a>
                        <button type="button" class="msg-btn" data-msg-next @click="nextStep(p.kind)">{{ s.next }}</button>
                      </div>
                      <div v-else-if="s.input" class="msg-row" style="align-items:stretch">
                        <input class="msg-in" type="password" v-model="wiz[p.kind].token" :placeholder="s.placeholder" autocomplete="off" spellcheck="false" data-msg-token @keydown.enter.prevent="startPairing(p.kind)">
                        <button type="button" class="msg-btn pri" :disabled="wiz[p.kind].busy" data-msg-next @click="startPairing(p.kind)">{{ wiz[p.kind].busy ? L('Проверяю…','Checking…') : s.button }}</button>
                        <a v-if="s.link_url" class="msg-btn ghost" :href="s.link_url" target="_blank" rel="noopener" data-msg-site>{{ s.link_button }} ›</a>
                      </div>
                      <div v-else class="msg-row">
                        <a class="msg-btn pri big" :href="wiz[p.kind].link" target="_blank" rel="noopener" data-msg-open>{{ s.button }} {{ wiz[p.kind].botName }} ›</a>
                        <span class="msg-wait"><span class="msg-spin"></span>{{ s.wait }}</span>
                      </div>
                      <span v-if="wiz[p.kind].error" class="msg-err">{{ wiz[p.kind].error }}</span>
                    </template>
                  </div>
                </div>
                <div v-if="wiz[p.kind].done" class="msg-step cur done" data-msg-done>
                  <span class="msg-step-n">✓</span>
                  <div class="msg-step-b">
                    <span class="msg-step-t">{{ L('Готово','Done') }}</span>
                    <span class="msg-step-x">{{ L('Пробное сообщение отправлено — проверьте, что оно пришло. Сообщения о ферме будут приходить туда же.','A test message has been sent — check that it arrived. Farm messages will come to the same place.') }}</span>
                  </div>
                </div>
                <div class="msg-row">
                  <button v-if="!wiz[p.kind].done && wiz[p.kind].step > 0" type="button" class="msg-btn ghost" data-msg-back @click="prevStep(p.kind)">‹ {{ L('Назад','Back') }}</button>
                  <button type="button" class="msg-btn ghost" @click="closeWizard(p.kind)">{{ wiz[p.kind].done ? L('Закрыть мастер','Close the wizard') : L('Отмена','Cancel') }}</button>
                </div>
              </div>
            </template>

            <!-- Площадка без мастера: WhatsApp (поля для продвинутых) -->
            <template v-else>
              <div class="msg-fields">
                <div v-for="f in p.fields.filter(x => !x.info)" :key="f.key" class="msg-f">
                  <label class="msg-f-l"><b>{{ f.label }}<template v-if="!f.required"> — {{ L('не обязательно','optional') }}</template></b><span>{{ f.hint }}</span></label>
                  <input class="msg-in" :type="f.secret ? 'password' : 'text'" v-model="adv[p.kind][f.key]" :placeholder="secretPlaceholder(p.kind, f)" :maxlength="f.max_len" :disabled="!isAdmin" autocomplete="off" spellcheck="false">
                </div>
              </div>
              <div class="msg-row">
                <button type="button" class="msg-btn" :disabled="!isAdmin" @click="saveAdvanced(p.kind, false)">{{ L('Сохранить','Save') }}</button>
                <button type="button" class="msg-btn pri" :disabled="!isAdmin" @click="saveAdvanced(p.kind, true)">{{ L('Сохранить и отправить пробное','Save and send a test') }}</button>
                <a v-if="p.docs_url" class="msg-btn ghost" :href="p.docs_url" target="_blank" rel="noopener">{{ L('Документация Meta','Meta docs') }} ›</a>
                <span v-if="note[p.kind]" :class="note[p.kind].ok ? 'msg-ok' : 'msg-err'">{{ note[p.kind].text }}</span>
              </div>
            </template>
            <div v-if="lastLine(p.kind)" class="msg-last" :class="(chStatus[p.kind] && chStatus[p.kind].ok) ? '' : 'bad'">{{ lastLine(p.kind) }}</div>
          </div>

          <div class="msg-card" data-msg-events>
            <div class="msg-card-h"><span class="msg-title">{{ L('О чём сообщать','What to report') }}</span>
              <span v-if="evNote" class="msg-ok" style="margin-left:auto">{{ evNote }}</span>
            </div>
            <div class="msg-ev">
              <label v-for="k in events" :key="k" class="msg-chk"><input type="checkbox" :checked="!!settings.events[k]" :disabled="!isAdmin || evBusy" @change="toggleEvent(k, $event.target.checked)"><span>{{ eventLabel(k) }}</span></label>
            </div>
            <div class="msg-row"><span class="msg-note" style="margin:0">{{ L('Язык сообщений','Message language') }}</span>
              <select class="msg-sel" :value="settings.lang" :disabled="!isAdmin" @change="setLang($event.target.value)"><option value="ru">Русский</option><option value="en">English</option></select>
            </div>
          </div>

          <div class="msg-card" data-msg-templates>
            <div class="msg-card-h"><span class="msg-title">{{ L('Текст сообщений','Message text') }}</span>
              <span v-if="tplNote" class="msg-ok" style="margin-left:auto">{{ tplNote }}</span>
            </div>
            <div class="msg-note" style="margin-top:2px">{{ L('Слова в фигурных скобках программа заменит данными события. Строка, в которой все такие слова оказались пустыми, в сообщение не попадает. Справа — как это будет выглядеть.','Words in curly braces are replaced with event data. A line whose braces are all empty is left out of the message. On the right — how it will look.') }}</div>
            <div class="msg-vars"><button v-for="v in tplMeta.vars" :key="v" type="button" class="msg-var" :title="varHint(v)" :disabled="!isAdmin" @click="insertVar(v)" data-msg-var>{{ '{' + v + '}' }}</button></div>
            <div v-for="k in events" :key="'tpl:' + k" class="msg-tpl" data-msg-tpl>
              <div class="msg-tpl-h"><span class="msg-tpl-t">{{ eventLabel(k) }}</span>
                <button v-if="!tplIsDefault(k)" type="button" class="msg-btn ghost sm" :disabled="!isAdmin" style="margin-left:auto" @click="resetTemplate(k)" data-msg-tpl-reset>{{ L('Как было','Default') }}</button>
              </div>
              <div class="msg-tpl-b">
                <textarea class="msg-ta" rows="3" :disabled="!isAdmin || tplBusy" v-model="tpl[k]" @focus="tplFocus = k" spellcheck="false" data-msg-tpl-in></textarea>
                <div><div class="msg-prev-l">{{ L('Так придёт на телефон','How it arrives on the phone') }}</div><div class="msg-prev" data-msg-tpl-prev>{{ tplPreview(k) }}</div></div>
              </div>
            </div>
            <div class="msg-row" style="margin-top:12px"><button type="button" class="msg-btn pri" :disabled="!isAdmin || tplBusy || !tplDirty" @click="saveTemplates" data-msg-tpl-save>{{ L('Сохранить тексты','Save texts') }}</button>
              <span class="msg-note" style="margin:0">{{ L('Пробное сообщение («Проверить») своё, по шаблонам не идёт.','The test message (“Test”) is fixed and does not follow the templates.') }}</span></div>
          </div>
        </template>`;
