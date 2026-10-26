# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.871 — видеостена: снятый потолок и путь без перекодирования.

ПОЧЕМУ ТАК. Логика распределения бюджета — чистые функции, поэтому проверяется НАСТОЯЩИМ
кодом модуля в Node: файлы импортируются как есть, ничего не переписывается и не имитируется.
Время в проверках поддельное, поэтому набор не спит.

ЧЕГО НЕ ДОКАЗЫВАЕТ: что двенадцать камер реально не тормозят на конкретной машине владельца.
Это меряется только на ферме — бюджет для того и растёт по измерению, а не по обещанию.
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SENTINEL = "CAMERA_WALL_GOVERNOR_SENTINEL_2_871"
MOD = os.path.join(ROOT, "modules", "camera_wall")
WEB = os.path.join(MOD, "web")
_n = {"pass": 0, "fail": 0}


def check(label, cond, extra=""):
    ok = bool(cond)
    print(("PASS — " if ok else "FAIL — ") + label + (("\n        " + str(extra)[:220]) if (extra and not ok) else ""))
    _n["pass" if ok else "fail"] += 1
    return ok


def section(t):
    print("\n=== %s ===" % t)


def furl(p):
    return "file:///" + p.replace("\\", "/")


NODE = r"C:\Program Files\nodejs\node.exe"
NODE = NODE if os.path.exists(NODE) else "node"


def run_node(body):
    """Выполнить сценарий, импортирующий НАСТОЯЩИЕ файлы модуля."""
    td = tempfile.mkdtemp(prefix="fm871_")
    hp = os.path.join(td, "h.mjs")
    io.open(hp, "w", encoding="utf-8", newline="\n").write(body)
    try:
        r = subprocess.run([NODE, hp], capture_output=True, timeout=180)
        out = (r.stdout or b"").decode("utf-8", "replace")
        err = (r.stderr or b"").decode("utf-8", "replace")
        m = re.search(r"@@(\{.*\})@@", out, re.S)
        return (json.loads(m.group(1)) if m else None), (err or out)
    except Exception as e:
        return None, str(e)
    finally:
        try:
            os.remove(hp)
            os.rmdir(td)
        except Exception:
            pass


MANIFEST = json.load(io.open(os.path.join(MOD, "module.json"), encoding="utf-8"))
PROVIDERS = io.open(os.path.join(WEB, "camera-providers.js"), encoding="utf-8").read()
GOV = io.open(os.path.join(WEB, "performance-governor.js"), encoding="utf-8").read()
FMP4 = io.open(os.path.join(WEB, "provider-core-fmp4.js"), encoding="utf-8").read()
PANEL = io.open(os.path.join(WEB, "CameraWallPanel.js"), encoding="utf-8").read()

# ══════════════════════════════════════════════════════════════════════════════════════
section("A. Источники: путь без перекодирования — основной, прежний — запасной")

HARNESS_A = """
import { sourceCostClass, providerCandidates, isBambuTlsJpeg } from %s;
const env = { document: { createElement: () => ({ style: {}, setAttribute() {}, addEventListener() {} }) } };
const x1 = { id: 'p1', sourceKind: 'printer', type: 'bambu', serial: '00M09A' };
const p1s = { id: 'p2', sourceKind: 'printer', type: 'bambu', serial: '01S00C' };
const p1 = { id: 'p3', sourceKind: 'printer', type: 'bambu', serial: '01P00C' };
const kl = { id: 'p4', sourceKind: 'printer', type: 'klipper', serial: '' };
const pick = (s) => providerCandidates(s, env).map(c => ({ key: c.key, fallback: !!c.fallback }));
console.log('@@' + JSON.stringify({
  costX1: sourceCostClass(x1), costP1: sourceCostClass(p1), costKl: sourceCostClass(kl),
  x1: pick(x1), p1s: pick(p1s), p1: pick(p1), kl: pick(kl),
  tlsX1: isBambuTlsJpeg(x1), tlsP1: isBambuTlsJpeg(p1),
}) + '@@');
""" % json.dumps(furl(os.path.join(WEB, "camera-providers.js")))

resA, errA = run_node(HARNESS_A)
if not resA:
    check("A0. файлы модуля импортируются в Node", False, errA[-220:])
else:
    check("A0. файлы модуля импортируются в Node", True)
    check("A1. камера Bambu больше НЕ считается дорогой для сервера",
          resA["costX1"] != "expensive-server", resA["costX1"])
    check("A2. у X1/H2 первым идёт путь без перекодирования",
          resA["x1"][0]["key"] == "core-fmp4", resA["x1"])
    check("A3. прежний MJPEG остался запасным (а не исчез)",
          any(c["key"] == "core-mjpeg" and c["fallback"] for c in resA["x1"]), resA["x1"])
    check("A4. у P1 и P1S путь ОДИН — прежний (у них не H.264, а снимки ~0,5 к/с)",
          [c["key"] for c in resA["p1"]] == ["core-mjpeg"]
          and [c["key"] for c in resA["p1s"]] == ["core-mjpeg"], (resA["p1"], resA["p1s"]))
    #  16.10.2026 (R-062): WebRTC больше не ходит к STUN-серверу в интернете — путь назван «webrtc-lan».
    check("A5. Klipper: WebRTC по локальной сети и его запасной путь",
          [c["key"] for c in resA["kl"]] == ["webrtc-lan", "mjpeg-fallback"], resA["kl"])
    check("A6. распознавание P1/P1S по серийному номеру не сломано",
          resA["tlsP1"] is True and resA["tlsX1"] is False)

check("A7. новый провайдер обращается к маршруту без перекодирования",
      "/camera.mp4" in PROVIDERS and "CoreFmp4Provider" in PROVIDERS)
check("A8. проигрыватель берётся из ядра, а не дублируется в модуле",
      "/assets/composables/useCameraFmp4.js" in FMP4 and "MediaSource" not in FMP4)
check("A9. на старом ядре модуль честно падает на запасной путь",
      "fmp4_player_unavailable" in FMP4 and "catch" in FMP4)
check("A10. LIVE заявляется только по первому фрагменту",
      "kind === 'live'" in FMP4 and "first_frame_timeout" in FMP4)


# ══════════════════════════════════════════════════════════════════════════════════════
section("B. Бюджет: потолка в четыре плитки больше нет, рост — по измерению")

HARNESS_B = """
import { PerformanceGovernor, GOVERNOR_LIMITS, GOVERNOR_TIMING, chooseStableLiveSet } from %s;
let t = 0;
const now = () => t;
const mk = (opts = {}) => new PerformanceGovernor({ now, hardwareConcurrency: 8, localWindow: true, ...opts });

const out = {};
out.limitsCfg = GOVERNOR_LIMITS;
out.spacing = GOVERNOR_TIMING.streamStartSpacingMs;

// стартовый бюджет
let g = mk();
out.start = g.limits();

// спокойный интерфейс: 15 хороших замеров и время -> лестница растёт
const calm = (gov, samples = 15) => { for (let i = 0; i < samples; i++) gov.recordEventLoopLag(10); };
calm(g);
const ladder = [];
for (let step = 0; step < 8; step++) { t += 8000; ladder.push(g.limits().totalLiveBudget); calm(g, 2); }
out.ladder = ladder;

// нервный интерфейс: рост не происходит
let g2 = mk();
for (let i = 0; i < 20; i++) g2.recordEventLoopLag(300);
t += 60000;
out.unstable = g2.limits().totalLiveBudget;

// защита: перегрузка роняет бюджет заметно
let g3 = mk();
calm(g3);
for (let step = 0; step < 8; step++) { t += 8000; g3.limits(); calm(g3, 2); }
out.beforeProtection = g3.limits().totalLiveBudget;
for (let i = 0; i < 5; i++) g3.recordEventLoopLag(400);
out.afterOneStep = g3.limits().totalLiveBudget;
t += 6000;
for (let i = 0; i < 5; i++) g3.recordEventLoopLag(400);
out.afterTwoSteps = g3.limits().totalLiveBudget;

// экономный режим не изменился
let g4 = mk(); g4.setMode('economy');
out.economy = g4.limits();

// выбор живых плиток: двенадцать плиток при бюджете 12 — берутся все
const tiles = Array.from({ length: 12 }, (_, i) => ({ id: 'p' + i, costClass: 'medium', visible: true }));
out.chosen12 = chooseStableLiveSet(tiles, { totalLiveBudget: 12, expensiveServerLiveBudget: 2 }).chosen.length;
out.chosenOld = chooseStableLiveSet(tiles, { totalLiveBudget: 4, expensiveServerLiveBudget: 2 }).chosen.length;
console.log('@@' + JSON.stringify(out) + '@@');
""" % json.dumps(furl(os.path.join(WEB, "performance-governor.js")))

resB, errB = run_node(HARNESS_B)
if not resB:
    check("B0. распорядитель бюджета импортируется и считает", False, errB[-220:])
else:
    check("B0. распорядитель бюджета импортируется и считает", True)
    check("B1. потолок поднят с 4 до 16 плиток",
          resB["limitsCfg"]["maxTotalLiveBudget"] == 16, resB["limitsCfg"])
    check("B2. сразу показываем 4 плитки (серверу это ничего не стоит)",
          resB["start"]["totalLiveBudget"] == 4, resB["start"])
    check("B3. при спокойном интерфейсе бюджет растёт шагами по 2 до 16",
          resB["ladder"][0] >= 6 and resB["ladder"][-1] == 16
          and all(b <= 16 for b in resB["ladder"]), resB["ladder"])
    # Нервный интерфейс не просто не даёт расти — защита ещё и уводит бюджет ВНИЗ.
    # Проверяем именно это: рост не случился, стартовые четыре не удержались.
    check("B4. при нервном интерфейсе бюджет не растёт, а защита уводит его вниз",
          resB["unstable"] <= 4, resB["unstable"])
    check("B5. перегрузка роняет бюджет заметно, а не по одной плитке",
          resB["afterOneStep"] <= 10 and resB["afterOneStep"] < resB["beforeProtection"],
          (resB["beforeProtection"], resB["afterOneStep"]))
    check("B6. вторая перегрузка роняет ещё",
          resB["afterTwoSteps"] < resB["afterOneStep"], (resB["afterOneStep"], resB["afterTwoSteps"]))
    check("B7. ниже двух плиток защита не опускает (совсем без камер стена бессмысленна)",
          resB["afterTwoSteps"] >= 2, resB["afterTwoSteps"])
    check("B8. экономный режим не изменился: 2 плитки, 1 дорогая",
          resB["economy"] == {"expensiveServerLiveBudget": 1, "totalLiveBudget": 2}, resB["economy"])
    check("B9. двенадцать плиток при бюджете 12 — берутся все двенадцать",
          resB["chosen12"] == 12, resB["chosen12"])
    check("B10. прежний бюджет 4 по-прежнему уважается (механизм не сломан)",
          resB["chosenOld"] == 4, resB["chosenOld"])
    check("B11. запуск потоков стал плотнее (250 мс вместо 750)",
          resB["spacing"] == 250, resB["spacing"])
    check("B12. бюджет дорогого пути сохранён для запасного MJPEG",
          resB["limitsCfg"]["maxExpensiveLiveBudget"] == 2, resB["limitsCfg"])


# ══════════════════════════════════════════════════════════════════════════════════════
section("D. Причина отказа видна на плитке")

# Alpha 2.875. Владелец 24.08.2026: «на K2 не могу найти, где написана ошибка. Что бы я ни делал».
# И был прав: причина жила только в подсказке при наведении на маленькую надпись состояния и в
# баннере, который перекрывается более ранними ветками показа. Дефект интерфейса: без причины
# отказ нельзя ни понять, ни передать разработчику.
check("D1. причина отказа выводится ТЕКСТОМ в строке плитки, а не только в подсказке",
      "reasonText(tile)" in PANEL and "{{ reasonText(tile) }}" in PANEL)
check("D2. коды переведены на человеческий язык",
      "FAIL_REASONS" in PANEL and "камера не прислала кадр за 15 секунд" in PANEL)
check("D3. рядом с текстом остаётся сам код — разработчику нужна точность",
      "' (' + raw + ')'" in PANEL)
check("D4. неизвестный код показывается как есть, а не прячется",
      "known ? human" in PANEL and "return known ? human" in PANEL)
check("D5. функция отдана в шаблон", "reasonText," in PANEL)
_known = ("first_frame_timeout", "fmp4_stream_failed", "fmp4_player_unavailable",
          "mse_unsupported", "codec_unsupported", "mjpeg_stream_failed", "camera_failed")
check("D6. переведены все причины, которые вообще может выдать наш код",
      all(k in PANEL for k in _known), [k for k in _known if k not in PANEL])


# ══════════════════════════════════════════════════════════════════════════════════════
section("E. Creality, WebRTC без STUN, IP-камеры на сервере (16.10.2026, R-062, R-146)")

HARNESS_E = """
import { providerCandidates } from %(prov)s;
import { resolveCameraCapability } from %(disc)s;
import { CoreWebRtcProvider } from %(rtc)s;
import { serverIpSourcesFrom, reconcileIpSources, serverPayload, fetchServerIpSources, pushServerIpSources, CameraStore } from %(store)s;
import * as storeMod from %(store)s;
const out = {};
const env = { document: { createElement: () => ({ style: {}, setAttribute() {}, addEventListener() {} }) } };
out.cr = providerCandidates({ id: 'c1', sourceKind: 'printer', type: 'creality' }, env).map(c => ({ key: c.key, fallback: !!c.fallback, label: c.label }));
out.caps = ['Creality K1', 'Creality K1C', 'Creality K1 Max', 'Creality K2', 'Creality K2 Plus', 'Creality K2 Pro',
            'Creality K1 SE', 'Creality Ender-3 V3 KE', 'Creality Ender-5 Max'].map(m => resolveCameraCapability({ type: 'creality', model: m }));
out.klCap = resolveCameraCapability({ type: 'klipper', model: 'Creality K2 Plus' });
// провайдер WebRTC на подставном браузере: что он просит у RTCPeerConnection и что шлёт ядру
const rec = {};
class FakePC {
  constructor(cfg) { rec.cfg = cfg; this.iceGatheringState = 'complete'; this.localDescription = { sdp: 'v=0 offer' }; this.connectionState = 'new'; }
  addTransceiver(k, o) { rec.tr = [k, o]; }
  async createOffer() { return { type: 'offer', sdp: 'v=0 offer' }; }
  async setLocalDescription() {}
  async setRemoteDescription(d) { rec.remote = d; }
  addEventListener() {} removeEventListener() {} close() { rec.closed = true; }
}
const el = () => ({ addEventListener() {}, removeEventListener() {}, play() { return Promise.resolve(); }, pause() {}, load() {}, remove() {}, removeAttribute() {} });
const env2 = { document: { createElement: el }, RTCPeerConnection: FakePC, AbortController, MediaStream: class {},
  setTimeout, clearTimeout,
  fetch: async (url, opts) => { rec.url = url; rec.body = JSON.parse(opts.body); return { ok: true, json: async () => ({ type: 'answer', sdp: 'v=0 answer' }) }; } };
const prov = new CoreWebRtcProvider('/api/printer/c1/webrtc', env2);
await prov.open(null, {});
prov.close();
out.rtc = rec;
// список IP-камер: что приходит с сервера и чей список побеждает
const cam = (id, name) => ({ id, name, url: 'http://192.0.2.50/' + id + '.jpg', mode: 'snapshot', fit: 'contain' });
out.unsupported = serverIpSourcesFrom({ status: 'ok' });
out.noList = serverIpSourcesFrom({ ok: true, settings: { module_ui: {} } });
out.withList = serverIpSourcesFrom({ ok: true, settings: { module_ui: { camera_wall: { ip_sources: [cam('ip_s1', 'Склад'), { id: 'bad', name: '', url: 'ftp://x' }] } } } });
out.emptyList = serverIpSourcesFrom({ ok: true, settings: { module_ui: { camera_wall: { ip_sources: [] } } } });
out.r1 = reconcileIpSources(out.withList, [cam('ip_l1', 'Локальная')], true);
out.r1m = reconcileIpSources(out.withList, [cam('ip_l1', 'Локальная'), cam('ip_s1', 'Склад')], false);
out.r1same = reconcileIpSources(out.withList, [cam('ip_s1', 'Склад')], false);
out.r2 = reconcileIpSources(out.noList, [cam('ip_l1', 'Локальная')], false);
out.r3 = reconcileIpSources(out.emptyList, [cam('ip_l1', 'Локальная')], true);
out.r4 = reconcileIpSources(out.unsupported, [cam('ip_l1', 'Локальная')], true);
out.r5 = reconcileIpSources(out.noList, [cam('ip_l1', 'Локальная')], true);
out.r4u = reconcileIpSources(out.unsupported, [cam('ip_l1', 'Локальная')], false);
// одна правка поверх свежего списка сервера (16.10.2026): «сервер» с памятью, второй компьютер пишет в него же
const oldCalls = [];
async function fakeFetchOld(url, opts) { oldCalls.push((opts && opts.method) || 'GET'); return { ok: true, status: 200, json: async () => ({ ok: false, error: 'no_fields', settings: {} }) }; }
const srvState = { ip: [cam('ip_s1', 'Склад')] };
const srvCalls = [];
const statefulFetch = async (url, opts) => {
  const method = (opts && opts.method) || 'GET';
  srvCalls.push(method);
  if (method === 'POST') { srvState.ip = JSON.parse(opts.body).module_ui.camera_wall.ip_sources; return { ok: true, status: 200, json: async () => ({ ok: true }) }; }
  return { ok: true, status: 200, json: async () => ({ ok: true, settings: { module_ui: { camera_wall: { ip_sources: srvState.ip } } } }) };
};
const ac = storeMod.applyServerIpChange;
const ic = storeMod.applyIpChange;
out.hasApply = typeof ac === 'function' && typeof ic === 'function';
if (out.hasApply) {
  // браузер A открыл стену, когда на сервере был только «Склад»; потом второй компьютер добавил «Цех 3»
  const aList = [cam('ip_s1', 'Склад')];
  srvState.ip = srvState.ip.concat([cam('ip_o1', 'Цех 3')]);
  out.addA = await ac(statefulFetch, { add: cam('ip_a1', 'Вход') }, aList.concat([cam('ip_a1', 'Вход')]), true);
  out.srvAfterAdd = srvState.ip.map(c => c.id);
  out.delA = await ac(statefulFetch, { remove: 'ip_s1' }, aList, true);
  out.srvAfterDel = srvState.ip.map(c => c.id);
  out.dupAdd = ic([cam('ip_s1', 'Склад')], { add: cam('ip_s1', 'Склад') }).map(c => c.id);
  out.delMissing = ic([cam('ip_s1', 'Склад')], { remove: 'nope' }).map(c => c.id);
  // браузер, ещё не сверявшийся с сервером: его прежние камеры тоже попадают на сервер
  srvState.ip = [cam('ip_s1', 'Склад')];
  out.unseeded = await ac(statefulFetch, { add: cam('ip_n1', 'Новая') }, [cam('ip_l9', 'Старая'), cam('ip_n1', 'Новая')], false);
  out.srvUnseeded = srvState.ip.map(c => c.id);
  // сервер списка не знает или чтение сорвалось — на сервер не пишется ничего
  const before = srvCalls.length;
  out.oldCore = await ac(fakeFetchOld, { add: cam('ip_x1', 'Икс') }, [cam('ip_x1', 'Икс')], true);
  out.failedRead = await ac(async () => { throw new Error('offline'); }, { remove: 'ip_s1' }, [], true);
  out.oldCorePosts = oldCalls.filter(m => m === 'POST').length;
  // отказ записи (нет прав) — ok=false, список этого браузера остаётся
  out.denied = await ac(async (url, opts) => ((opts && opts.method) === 'POST'
    ? { ok: false, status: 403, json: async () => ({}) }
    : { ok: true, status: 200, json: async () => ({ ok: true, settings: { module_ui: { camera_wall: { ip_sources: [] } } } }) }),
    { add: cam('ip_y1', 'Игрек') }, [cam('ip_y1', 'Игрек')], true);
}
out.payload = serverPayload([cam('ip_l1', 'Локальная'), { id: 'bad', name: '', url: 'javascript:alert(1)' }]);
const calls = [];
const fakeFetch = (answer) => async (url, opts) => { calls.push({ url, method: (opts && opts.method) || 'GET', body: opts && opts.body ? JSON.parse(opts.body) : null });
  if (answer === 'throw') throw new Error('offline');
  if (answer === 403) return { ok: false, status: 403, json: async () => ({}) };
  return { ok: true, status: 200, json: async () => answer }; };
out.pushOk = await pushServerIpSources(fakeFetch({ ok: true }), [cam('ip_l1', 'Локальная')]);
out.pushOldCore = await pushServerIpSources(fakeFetch({ ok: false, error: 'no_fields' }), [cam('ip_l1', 'Локальная')]);
out.push403 = await pushServerIpSources(fakeFetch(403), []);
out.pushThrow = await pushServerIpSources(fakeFetch('throw'), []);
out.fetchThrow = await fetchServerIpSources(fakeFetch('throw'));
out.fetchList = await fetchServerIpSources(fakeFetch({ ok: true, settings: { module_ui: { camera_wall: { ip_sources: [cam('ip_s1', 'Склад')] } } } }));
out.calls = calls;
const mem = {}; const storage = { getItem: (k) => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); } };
const st = new CameraStore(storage);
out.seed0 = st.isIpSourcesSeeded(); st.markIpSourcesSeeded(); out.seed1 = st.isIpSourcesSeeded();
out.noStorage = new CameraStore({ getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } }).isIpSourcesSeeded();
console.log('@@' + JSON.stringify(out) + '@@');
""" % {"prov": json.dumps(furl(os.path.join(WEB, "camera-providers.js"))),
       "disc": json.dumps(furl(os.path.join(WEB, "source-discovery.js"))),
       "rtc": json.dumps(furl(os.path.join(WEB, "provider-core-webrtc.js"))),
       "store": json.dumps(furl(os.path.join(WEB, "camera-store.js")))}

resE, errE = run_node(HARNESS_E)
if not resE:
    check("E0. файлы модуля импортируются в Node", False, errE[-300:])
else:
    check("E1. Creality на заводской прошивке — как Klipper: WebRTC по локальной сети, затем MJPEG через ядро",
          [(c["key"], c["fallback"]) for c in resE["cr"]] == [("webrtc-lan", False), ("mjpeg-fallback", True)]
          and "STUN" not in json.dumps(resE["cr"]), resE["cr"])
    check("E2. камера Creality «подтверждена» у K1, K1C, K1 Max и K2-семейства; у K1 SE, KE и Ender-5 Max — «неизвестно»",
          resE["caps"] == ["confirmed"] * 6 + ["unknown"] * 3 and resE["klCap"] == "confirmed", resE["caps"])
    check("E3. WebRTC стены без STUN-сервера в интернете (iceServers пуст) и с направлением sendrecv",
          resE["rtc"].get("cfg") == {"iceServers": []} and resE["rtc"].get("tr") == ["video", {"direction": "sendrecv"}],
          resE["rtc"])
    check("E4. предложение уходит ядру, ответ принтера применяется",
          resE["rtc"].get("url") == "/api/printer/c1/webrtc" and resE["rtc"].get("body", {}).get("sdp") == "v=0 offer"
          and (resE["rtc"].get("remote") or {}).get("sdp") == "v=0 answer", resE["rtc"])
    check("E5. ответ сервера: нет module_ui — старая программа; есть — список (битые записи отброшены)",
          resE["unsupported"] == {"supported": False, "present": False, "list": []}
          and resE["noList"] == {"supported": True, "present": False, "list": []}
          and [c["id"] for c in resE["withList"]["list"]] == ["ip_s1"] and resE["withList"]["present"] is True
          and resE["emptyList"] == {"supported": True, "present": True, "list": []}, (resE["unsupported"], resE["noList"]))
    check("E6. на сервере есть камеры — показываются они, а браузер их зеркалит (камера, удалённая на другом "
          "компьютере, из копии этого браузера не воскресает)",
          resE["r1"]["source"] == "server" and resE["r1"]["mirror"] is True and [c["id"] for c in resE["r1"]["list"]] == ["ip_s1"]
          and resE["r1"]["seed"] is False, resE["r1"])
    check("E6а. первая встреча браузера с сервером: свои камеры, которых на сервере нет, добавляются (не пропадают), "
          "одинаковые не дублируются",
          resE["r1m"]["source"] == "merge" and resE["r1m"]["seed"] is True
          and [c["id"] for c in resE["r1m"]["list"]] == ["ip_s1", "ip_l1"]
          and resE["r1same"]["source"] == "server" and resE["r1same"]["seed"] is False, (resE["r1m"], resE["r1same"]))
    check("E7. на сервере пусто, а в браузере камеры есть — переносятся на сервер ОДИН раз",
          resE["r2"]["seed"] is True and [c["id"] for c in resE["r2"]["list"]] == ["ip_l1"]
          and resE["r5"]["seed"] is False and resE["r5"]["source"] == "local", (resE["r2"], resE["r5"]))
    check("E8. камеры удалили на другом компьютере (на сервере пустой список) — пусто и здесь",
          resE["r3"]["list"] == [] and resE["r3"]["mirror"] is True, resE["r3"])
    check("E9. старая программа (module_ui нет) — молча остаётся список этого браузера",
          resE["r4"]["source"] == "local" and [c["id"] for c in resE["r4"]["list"]] == ["ip_l1"] and not resE["r4"]["mirror"],
          resE["r4"])
    check("E9а. сервер списка не знает (старая программа или сорвалось чтение), браузер ещё не сверялся — "
          "переноса НЕТ: иначе сбой чтения у новой программы затёр бы камеры других компьютеров",
          resE["r4u"]["seed"] is False and resE["r4u"]["source"] == "local"
          and [c["id"] for c in resE["r4u"]["list"]] == ["ip_l1"], resE["r4u"])
    if not resE.get("hasApply"):
        check("E14. правка списка IP-камер — одной операцией поверх свежего списка сервера", False, "нет applyServerIpChange")
    else:
        check("E14. добавили камеру на компьютере A — камера, добавленная тем временем на другом компьютере, на сервере "
              "остаётся (правка ложится на свежий список сервера, а не на список, загруженный при открытии стены)",
              resE["addA"]["ok"] is True and resE["srvAfterAdd"] == ["ip_s1", "ip_o1", "ip_a1"]
              and [c["id"] for c in resE["addA"]["list"]] == ["ip_s1", "ip_o1", "ip_a1"], (resE["addA"], resE["srvAfterAdd"]))
        check("E15. удалили камеру на A — уходит только она, чужие камеры не пропадают",
              resE["delA"]["ok"] is True and resE["srvAfterDel"] == ["ip_o1", "ip_a1"], (resE["delA"], resE["srvAfterDel"]))
        check("E16. повторное добавление той же камеры и удаление отсутствующей ничего не меняют",
              resE["dupAdd"] == ["ip_s1"] and resE["delMissing"] == ["ip_s1"], (resE["dupAdd"], resE["delMissing"]))
        check("E17. браузер, ещё не сверявшийся с сервером: его прежние камеры при правке тоже уходят на сервер",
              resE["unseeded"]["ok"] is True and resE["srvUnseeded"] == ["ip_s1", "ip_l9", "ip_n1"], (resE["unseeded"], resE["srvUnseeded"]))
        check("E18. старая программа или сорвалось чтение — на сервер ничего не пишется, ответ «не принято»",
              resE["oldCore"] == {"ok": False, "list": None} and resE["failedRead"] == {"ok": False, "list": None}
              and resE["oldCorePosts"] == 0, (resE["oldCore"], resE["failedRead"], resE["oldCorePosts"]))
        check("E19. запись не принята (нет прав) — «не принято», список этого браузера не подменяется",
              resE["denied"] == {"ok": False, "list": None}, resE["denied"])
    _pl = resE["payload"]
    check("E10. на сервер уходит только module_ui.camera_wall.ip_sources, без битых записей",
          list(_pl.keys()) == ["module_ui"] and list(_pl["module_ui"].keys()) == ["camera_wall"]
          and [c["id"] for c in _pl["module_ui"]["camera_wall"]["ip_sources"]] == ["ip_l1"]
          and set(_pl["module_ui"]["camera_wall"]["ip_sources"][0].keys()) == {"id", "name", "url", "mode", "fit"}, _pl)
    check("E11. запись: принято — да; старая программа, нет прав, нет сети — «нет», без исключений",
          resE["pushOk"] is True and resE["pushOldCore"] is False and resE["push403"] is False and resE["pushThrow"] is False
          and resE["fetchThrow"]["supported"] is False and [c["id"] for c in resE["fetchList"]["list"]] == ["ip_s1"])
    _c = resE["calls"]
    check("E12. запрос записи — POST /api/farm-settings, чтение — GET того же адреса",
          _c and _c[0]["url"] == "/api/farm-settings" and _c[0]["method"] == "POST"
          and _c[0]["body"]["module_ui"]["camera_wall"]["ip_sources"][0]["id"] == "ip_l1"
          and _c[-1]["method"] == "GET", _c[:1])
    check("E13. пометка «уже перенесено» живёт в браузере; запрет хранения не роняет стену",
          resE["seed0"] is False and resE["seed1"] is True and resE["noStorage"] is False)


# ══════════════════════════════════════════════════════════════════════════════════════
section("C. Модуль как исходник проекта")

# Версия сверяется по СМЫСЛУ, а не по точному числу: она поднимается при каждой правке
# модуля, и жёсткая привязка к одному числу заставляла бы править проверку каждый раз.
# Важно другое: версия больше не прототипная и владелец видит, что модуль надо переустановить.
check("C1. версия модуля поднята и не прототипная (владельцу надо переустановить)",
      re.match(r"^0\.(2|[3-9])\.\d+$", str(MANIFEST.get("version") or "")) is not None,
      MANIFEST.get("version"))
check("C2. точка входа на месте", os.path.isfile(os.path.join(MOD, MANIFEST.get("entry", ""))))
check("C3. новый провайдер лежит в модуле", os.path.isfile(os.path.join(WEB, "provider-core-fmp4.js")))
check("C4. сборщик установочного zip существует",
      os.path.isfile(os.path.join(ROOT, "tools", "build_camera_wall_zip.py")))
# Слово FFmpeg в подписи запасного пути — это подпись для человека, а не вызов.
# Запрещено другое: адреса принтеров и запуск процессов из модуля.
check("C5. модуль не знает адресов принтеров и ничего не запускает",
      not re.search(r"rtsps?://|child_process|spawn\(|exec\(", PROVIDERS + GOV + FMP4, re.I))

# Alpha 2.872. ЗДЕСЬ БЫЛ ДЕФЕКТ, И ОН ДОШЁЛ ДО ВЛАДЕЛЬЦА. Сборщик zip сделали копией сборщика
# модуля «Качество», у которого в web/ только скрипты, и в нём стоял фильтр «паковать только .js».
# camera-wall.css молча не попадал в архив: на машине владельца стена открывалась без стилей и
# выглядела пустой (в консоли 404 на camera-wall.css). На стенде разработки этого не видно —
# там файлы отдаются из папки проекта, а не из архива. Поэтому проверяем СПИСОК СБОРЩИКА, а не
# папку: собранный архив обязан содержать каждый файл модуля.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("_cw_build", os.path.join(ROOT, "tools", "build_camera_wall_zip.py"))
_bld = _ilu.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_bld)
    _collected = set(rel for _f, rel in _bld.collect())
except Exception as _e:
    _collected = None
    check("C7. сборщик zip читается и составляет список файлов", False, str(_e)[:200])
if _collected is not None:
    check("C7. сборщик zip читается и составляет список файлов", True)
    _webfiles = []
    for _r, _d, _fs in os.walk(os.path.join(MOD, "web")):
        for _fn in _fs:
            _rel = "camera_wall/web/" + os.path.relpath(os.path.join(_r, _fn), os.path.join(MOD, "web")).replace(os.sep, "/")
            _webfiles.append(_rel)
    _lost = sorted(set(_webfiles) - _collected)
    check("C8. в архив попадает КАЖДЫЙ файл модуля, включая стили", not _lost, _lost)
    check("C9. стили модуля в списке сборщика явно", "camera_wall/web/camera-wall.css" in _collected)
    check("C10. манифест в списке сборщика", "camera_wall/module.json" in _collected)

leaks = []
for r, _d, fs in os.walk(MOD):
    for fn in fs:
        try:
            if SENTINEL.encode() in io.open(os.path.join(r, fn), "rb").read():
                leaks.append(fn)
        except Exception:
            pass
check("C6. метка оснастки в модуль не попала: %s" % (leaks or "нигде"), not leaks)

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
