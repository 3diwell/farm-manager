# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.870 — камера БЕЗ ПЕРЕКОДИРОВАНИЯ: разбор fMP4, раздача зрителям, контракт маршрута.

ПОЧЕМУ ЭТОТ НАБОР ВАЖЕН. Живого принтера у разработки нет, а путь камеры — критическая
область. Поэтому всё, что можно проверить без железа, проверяется здесь и по-настоящему:
байты fMP4 берутся у НАСТОЯЩЕГО ffmpeg (он лежит рядом с server.py), источник и время
поддельные, поэтому набор не спит и ничего не запускает по сети.

ЧЕГО ЭТОТ НАБОР НЕ ДОКАЗЫВАЕТ: что камера Bambu отдаёт поток по RTSPS именно так, как мы
ждём. Это проверяется только на живом принтере — и об этом сказано владельцу прямо.
"""
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SENTINEL = "CAMERA_FMP4_SENTINEL_2_870"
_n = {"pass": 0, "fail": 0}


def check(label, cond, extra=""):
    ok = bool(cond)
    print(("PASS — " if ok else "FAIL — ") + label + (("\n        " + str(extra)[:220]) if (extra and not ok) else ""))
    _n["pass" if ok else "fail"] += 1
    return ok


def section(t):
    print("\n=== %s ===" % t)


from app.camera_fmp4 import Fmp4Splitter, Fmp4Hub, OwnerState  # noqa: E402
from app.camera_hub import CameraHub  # noqa: E402

SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
REG = io.open(os.path.join(ROOT, "app", "route_policy_registry.py"), encoding="utf-8").read()
PLAYER = io.open(os.path.join(ROOT, "web", "composables", "useCameraFmp4.js"), encoding="utf-8").read()
HUB = io.open(os.path.join(ROOT, "app", "camera_fmp4.py"), encoding="utf-8").read()


# ── настоящий поток fMP4 от ffmpeg (без сети и без принтера) ─────────────────────────────
def _ffmpeg():
    for c in (os.path.join(ROOT, "ffmpeg.exe"), os.path.join(ROOT, "ffmpeg")):
        if os.path.isfile(c):
            return c
    from shutil import which
    return which("ffmpeg")


def _make_stream():
    """Сделать короткий настоящий fMP4 ровно теми ключами, что использует сервер."""
    ff = _ffmpeg()
    if not ff:
        return None
    movflags = re.search(r'MOVFLAGS = "([^"]+)"', SRV)
    flags = movflags.group(1) if movflags else "+frag_keyframe+empty_moov+default_base_moof"
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", "testsrc2=size=320x240:rate=10", "-t", "3", "-c:v", "libx264",
           "-preset", "ultrafast", "-g", "10", "-pix_fmt", "yuv420p",
           "-an", "-f", "mp4", "-movflags", flags, "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=120)
        return p.stdout if p.returncode == 0 and p.stdout else None
    except Exception:
        return None


STREAM = _make_stream()

# ══════════════════════════════════════════════════════════════════════════════════════
section("A. Разбор fMP4 на настоящих байтах ffmpeg")

if STREAM is None:
    check("A0. настоящий поток fMP4 получен от ffmpeg", False, "ffmpeg недоступен — разбор недоказан")
else:
    check("A0. настоящий поток fMP4 получен от ffmpeg", len(STREAM) > 5000, len(STREAM))

    sp = Fmp4Splitter()
    frags = sp.feed(STREAM)
    init = sp.init_segment
    check("A1. шапка отделена и начинается с ftyp", bool(init) and init[4:8] == b"ftyp", init[:16] if init else None)
    check("A2. в шапке есть moov (описание дорожки)", bool(init) and b"moov" in init)
    check("A3. фрагменты найдены", len(frags) >= 2, len(frags))
    check("A4. каждый фрагмент начинается с moof", all(f[4:8] == b"moof" for f in frags))
    check("A5. в каждом фрагменте есть mdat (сами кадры)", all(b"mdat" in f for f in frags))
    check("A6. склейка шапки и фрагментов = исходный поток БАЙТ В БАЙТ",
          init + b"".join(frags) == STREAM[:len(init) + sum(len(f) for f in frags)])
    # ffmpeg дописывает служебный указатель mfra, когда закрывает файл. В живом потоке
    # его не бывает, но проверка гоняет тот же код на записанном ролике — и он обязан
    # такую коробку отбросить: браузер ждёт moof+mdat и на постороннем куске спотыкается.
    check("A6b. служебные коробки отброшены, а не выданы за видео",
          sp.skipped_boxes >= 1 and all(f[4:8] == b"moof" for f in frags), sp.skipped_boxes)

    # Куски приходят как попало: ffmpeg отдаёт по мере готовности, а сеть режет ещё раз.
    for size in (1, 3, 7, 4096, 65536):
        sp2 = Fmp4Splitter()
        got = []
        for i in range(0, len(STREAM), size):
            got += sp2.feed(STREAM[i:i + size])
        check("A7. разбор не зависит от размера кусков (%d байт)" % size,
              sp2.init_segment == init and got == frags, "кусков=%d" % len(got))

    # Половина коробки — не фрагмент: отдавать её браузеру нельзя.
    sp3 = Fmp4Splitter()
    half = len(init) + len(frags[0]) // 2
    out = sp3.feed(STREAM[:half])
    check("A8. недочитанная коробка НЕ отдаётся как фрагмент", out == [])
    out += sp3.feed(STREAM[half:len(init) + len(frags[0])])
    check("A9. дочитанная коробка отдаётся целиком и без потерь", out == [frags[0]])

sp4 = Fmp4Splitter()
try:
    sp4.feed(b"\x00\x00\x00\x02junk")
    _raised = False
except ValueError:
    _raised = True
check("A10. испорченная коробка даёт ЯВНУЮ ошибку, а не молчание", _raised)


# ══════════════════════════════════════════════════════════════════════════════════════
section("B. Раздача зрителям: одно соединение с принтером, зрителей сколько угодно")


class FakeSource(object):
    """Источник без сети и без процессов. after() вызывается ПОСЛЕ того, как насос обработал
    очередной кусок: ровно в этот момент владелец жив, и зрителей можно честно прочитать."""

    def __init__(self, chunks, after=None):
        self._chunks = list(chunks)
        self._after = after
        self.closed = False

    def chunks(self):
        for c in self._chunks:
            if self.closed:
                return
            yield c
            if self._after:
                self._after()

    def close(self):
        self.closed = True


class Clock(object):
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def build_hub(chunks, after=None, **kw):
    """Распределитель с ручным временем и ручным запуском владельца (без настоящих потоков)."""
    clock = Clock()
    made = []
    pending = []

    def opener(key):
        src = FakeSource(chunks, after=after)
        made.append(src)
        return src

    hub = Fmp4Hub(open_source=opener, now=clock, spawn=lambda fn: pending.append(fn), **kw)
    return hub, clock, made, pending


def drain(sub):
    """Забрать у зрителя всё, что уже готово, не дожидаясь нового."""
    return list(sub.chunks(timeout=0))


if STREAM is not None:
    INIT = sp.init_segment
    FRAGS = frags

    # ── одно соединение с принтером на любое число зрителей ──────────────────────────
    seen = {"s1": [], "s2": [], "late": [], "late_sub": None}
    hub = None

    def after_chunk():
        seen["s1"] += drain(seen["sub1"])
        seen["s2"] += drain(seen["sub2"])
        if seen["late_sub"] is None and len(seen["s1"]) >= 2:
            seen["late_sub"] = hub.subscribe("1.2.3.4|CODE")     # зритель пришёл посреди эфира
        if seen["late_sub"] is not None:
            seen["late"] += drain(seen["late_sub"])

    hub, clock, made, pending = build_hub([STREAM[i:i + 4096] for i in range(0, len(STREAM), 4096)],
                                          after=after_chunk)
    seen["sub1"] = hub.subscribe("1.2.3.4|CODE")
    seen["sub2"] = hub.subscribe("1.2.3.4|CODE")
    check("B1. два зрителя — ОДИН источник (принтер видит одно соединение)", len(made) == 1, len(made))
    pending.pop(0)()

    check("B2. первый кусок каждому зрителю — шапка",
          seen["s1"][:1] == [INIT] and seen["s2"][:1] == [INIT],
          [len(x) for x in seen["s1"][:2]])
    check("B3. дальше идут целые фрагменты",
          all(x[4:8] == b"moof" for x in seen["s1"][1:]), len(seen["s1"]))
    check("B4. оба зрителя получили одно и то же", seen["s1"] == seen["s2"])
    check("B5. поздний зритель тоже получает шапку первой",
          seen["late"][:1] == [INIT], [len(x) for x in seen["late"][:2]])
    check("B6. поздний зритель не тянет за собой второй источник", len(made) == 1, len(made))
    check("B7. зритель получил все фрагменты потока", len(seen["s1"]) - 1 == len(FRAGS),
          (len(seen["s1"]) - 1, len(FRAGS)))
    check("B8. служебные коробки (mfra) зрителю не уходят",
          all(x[4:8] != b"mfra" for x in seen["s1"]) and sp.skipped_boxes >= 1, sp.skipped_boxes)

    # ── отстающий зритель: очередь ограничена, остальных он не держит ────────────────
    slowseen = {"fast": [], "slow_sub": None}

    def after_slow():
        slowseen["fast"] += drain(slowseen["fast_sub"])          # быстрый читает каждый раз

    hub2, clock2, made2, pending2 = build_hub([STREAM[i:i + 4096] for i in range(0, len(STREAM), 4096)],
                                              after=after_slow, max_fragments_per_viewer=2)
    slowseen["fast_sub"] = hub2.subscribe("k")
    slow = hub2.subscribe("k")                                    # этот не читает вовсе
    pending2.pop(0)()
    slow_got = drain(slow)
    check("B9. быстрый зритель получил все фрагменты, отстающий его не задержал",
          len(slowseen["fast"]) - 1 == len(FRAGS), (len(slowseen["fast"]) - 1, len(FRAGS)))
    check("B10. очередь отстающего ОГРАНИЧЕНА (память не растёт)",
          len(slow_got) <= 3, len(slow_got))
    check("B11. потерянное у отстающего посчитано честно", slow.dropped >= 1, slow.dropped)

    # ── сторож: замерший поток и никому не нужный поток ──────────────────────────────
    stall = {"done": False}

    def after_stall():
        if stall["done"]:
            return
        stall["done"] = True
        h, c, m = stall["hub"], stall["clock"], stall["made"]
        drain(stall["sub"])
        c.t += 11.0                                               # поток «замер» на 11 секунд
        h.tick()
        stall["closed"] = m[0].closed
        stall["state"] = h.stats("k")["state"]

    hub4, clock4, made4, pending4 = build_hub([STREAM], after=after_stall, stall_timeout=10.0)
    stall.update({"hub": hub4, "clock": clock4, "made": made4})
    stall["sub"] = hub4.subscribe("k")
    pending4.pop(0)()
    check("B12. поток замер -> источник закрыт сторожем",
          stall.get("closed") is True and stall.get("state") == OwnerState.IDLE,
          (stall.get("closed"), stall.get("state")))
    clock4.t += 2.0
    hub4.tick()
    check("B13. после паузы владелец поднимается снова", len(made4) == 2, len(made4))

    idle = {}

    def after_idle():
        if idle.get("done"):
            return
        idle["done"] = True
        idle["sub"].close()                                       # зритель ушёл
        idle["clock"].t += 6.0
        idle["hub"].tick()
        idle["closed"] = idle["made"][0].closed

    hub3, clock3, made3, pending3 = build_hub([STREAM], after=after_idle, idle_grace=5.0)
    idle.update({"hub": hub3, "clock": clock3, "made": made3})
    idle["sub"] = hub3.subscribe("k")
    pending3.pop(0)()
    check("B14. смотреть некому -> источник закрыт, соединение освобождено",
          idle.get("closed") is True)

    hub5, clock5, made5, pending5 = build_hub([], first_data_timeout=15.0)
    hub5.subscribe("k")
    pending5.pop(0)()
    clock5.t += 16.0
    hub5.tick()
    check("B15. первый фрагмент не пришёл -> источник закрыт", made5[0].closed is True)

    hub6, clock6, made6, pending6 = build_hub([STREAM])
    hub6.subscribe("k")
    hub6.shutdown()
    check("B16. остановка программы гасит все источники", made6[0].closed is True)
    check("B17. статистика показывает состояние и число зрителей",
          isinstance(hub6.stats(), dict) and "state" in (hub6.stats("k") or {}))
else:
    for i in range(1, 18):
        check("B%d. раздача зрителям" % i, False, "нет настоящего потока — проверка не выполнена")


# ══════════════════════════════════════════════════════════════════════════════════════
section("C. Контракт сервера: без перекодирования, без утечки кода доступа")

_src = SRV[SRV.find("class _BambuFmp4Source"):SRV.find("def _bambu_camera_frames")]
check("C1. источник fMP4 существует", len(_src) > 500, len(_src))
check("C2. ffmpeg вызывается БЕЗ перекодирования (-c:v copy)",
      '"-c:v", "copy"' in _src and '"-f", "mp4"' in _src)
check("C3. в потоке нет звука (-an) — камере он не нужен", '"-an"' in _src)
check("C4. фрагменты начинаются с ключевого кадра (frag_keyframe)",
      "+frag_keyframe" in _src and "empty_moov" in _src)
check("C5. прежний путь MJPEG НЕ тронут (перекодирование осталось только там)",
      '"-f", "mjpeg"' in SRV and '"-q:v", "5"' in SRV)
check("C6. код доступа принтера не попадает в журнал",
      not re.search(r"log\.[a-z]+\([^)]*self\._code", _src))
check("C7. источник гасит СВОЙ процесс по объекту, а не по имени",
      "pr.terminate()" in _src and "taskkill" not in _src and "/IM" not in _src)

_route = SRV[SRV.find("def printer_camera_mp4"):SRV.find("class WebRTCOffer")]
check("C8. маршрут камеры без перекодирования существует", len(_route) > 300, len(_route))
check("C9. P1/P1S отбиты явно (у них не H.264, а свой поток JPEG)",
      "01P" in _route and "01S" in _route and "p1_jpeg_stream" in _route)
check("C10. не-Bambu отбит явно", "fmp4_not_applicable" in _route)
check("C11. отдаётся как video/mp4", 'media_type="video/mp4"' in _route)
check("C12. маршрут зарегистрирован в реестре прав",
      "'/api/printer/{pid}/camera.mp4'" in REG and "'printer_camera_mp4'" in REG)
check("C13. распределитель отдельный, прежний не тронут",
      "_camera_fmp4_hub = Fmp4Hub(" in SRV and "_camera_hub = CameraHub(" in SRV)
check("C14. сторож и остановка учитывают новый распределитель",
      "_camera_fmp4_hub.tick()" in SRV and "_camera_fmp4_hub.shutdown()" in SRV)
check("C15. ключ владельца — адрес и код: сменили адрес, значит другой источник",
      '_camera_fmp4_hub.subscribe("%s|%s" % (ip, code))' in SRV)


# ══════════════════════════════════════════════════════════════════════════════════════
section("D. Интерфейс: путь выбирается явно, прежний остаётся по умолчанию")

check("D1. переключатель по умолчанию ВЫКЛЮЧЕН (прежний путь — выбор по умолчанию)",
      "const camFmp4On = ref(false);" in APPJS)
check("D2. выбор запоминается между запусками", "farm_cam_fmp4" in APPJS)
check("D3. переключатель не показывается там, где он бессмысленен (P1/P1S и не-Bambu)",
      "cameraSupportsFmp4" in APPJS and "01P" in APPJS and "01S" in APPJS)
check("D4. окно камеры показывает видео вместо картинки только при включённом пути",
      'v-else-if="cameraUsesFmp4"' in IDX and '!camGaveUp && !cameraUsesFmp4' in IDX)
check("D5. закрытие окна останавливает проигрыватель (процесс на сервере освобождается)",
      "_stopFmp4();" in APPJS and "const closeCamera" in APPJS)
check("D6. строка кодека берётся ИЗ ПОТОКА (avcC), а зашитая — только запасная",
      "const codec = codecFromInit(init);" in PLAYER
      and "(codec || " in PLAYER
      and PLAYER.count("avc1.640028") == 1)
check("D7. проигрыватель режет поток по целым коробкам", "splitBoxes" in PLAYER)
check("D8. буфер не растёт бесконечно и не отстаёт", "sourceBuffer.remove(" in PLAYER
      and "currentTime" in PLAYER)
# Alpha 2.874: очередь зрителя ограничивает СЕРВЕР. В браузере выбрасывать фрагменты нельзя —
# у H.264 выброшенный кусок рвёт декодирование (ровно поэтому не подошёл прежний
# распределитель кадров). Здесь проверяем, что разросшаяся очередь не молчит.
check("D9. разросшаяся очередь в браузере сообщает о себе, а не рвёт видео",
      "append_backlog" in PLAYER and "pending.length > 60" in PLAYER)


# ══════════════════════════════════════════════════════════════════════════════════════
section("E. Проигрыватель на настоящих байтах (Node)")

NODE = r"C:\Program Files\nodejs\node.exe"
_node = NODE if os.path.exists(NODE) else "node"
if STREAM is None:
    check("E1. разбор в браузере на настоящем потоке", False, "нет потока")
else:
    import base64
    import tempfile
    td = tempfile.mkdtemp(prefix="fm870_")
    b64 = base64.b64encode(STREAM).decode("ascii")
    harness = (
        "import { codecFromInit, splitBoxes } from " +
        json.dumps("file:///" + os.path.join(ROOT, "web", "composables", "useCameraFmp4.js").replace("\\", "/")) + ";\n"
        "const raw = Buffer.from(" + json.dumps(b64) + ", 'base64');\n"
        "const buf = new Uint8Array(raw);\n"
        "const { boxes, consumed } = splitBoxes(buf);\n"
        "const firstMoof = boxes.findIndex(b => b.type === 'moof');\n"
        "const init = buf.slice(0, boxes[firstMoof].start);\n"
        "const codec = codecFromInit(init);\n"
        "const frags = boxes.filter(b => b.type === 'moof').length;\n"
        "console.log('@@' + JSON.stringify({ codec, frags, consumed, initLen: init.length,\n"
        "  types: boxes.slice(0, 4).map(b => b.type) }) + '@@');\n")
    hp = os.path.join(td, "h.mjs")
    io.open(hp, "w", encoding="utf-8", newline="\n").write(harness)
    res = None
    try:
        r = subprocess.run([_node, hp], capture_output=True, timeout=120)
        out = (r.stdout or b"").decode("utf-8", "replace")
        m = re.search(r"@@(\{.*\})@@", out, re.S)
        res = json.loads(m.group(1)) if m else None
        if res is None:
            check("E1. проигрыватель разобрал поток в Node", False,
                  ((r.stderr or b"").decode("utf-8", "replace") or out)[-200:])
    except Exception as e:
        check("E1. проигрыватель разобрал поток в Node", False, str(e))
    finally:
        try:
            os.remove(hp)
            os.rmdir(td)
        except Exception:
            pass
    if res:
        check("E1. проигрыватель разобрал поток в Node", True)
        check("E2. первые коробки — ftyp и moov", res["types"][:2] == ["ftyp", "moov"], res["types"])
        check("E3. строка кодека получена из потока и имеет вид avc1.xxxxxx",
              bool(re.match(r"^avc1\.[0-9a-f]{6}$", res["codec"] or "")), res["codec"])
        check("E4. фрагменты найдены", res["frags"] >= 2, res["frags"])
        check("E5. шапка совпала по длине с серверной",
              res["initLen"] == len(sp.init_segment), (res["initLen"], len(sp.init_segment)))


# ══════════════════════════════════════════════════════════════════════════════════════
section("H. Ровный поток: нарезка по времени и вход с ключевого фрагмента")

# Alpha 2.874. Числа владельца от 24.08.2026: частота прыгает 0..15 на P2S и 0..30 на H2S,
# задержка заметна. Измерено на этой машине: при нарезке ТОЛЬКО по ключевым кадрам порция
# приходит раз в интервал ключевых кадров (2 с при -g 60), а с нарезкой по 200 мс — 50 порций
# вместо 5 на тех же данных, прирост объёма 0,2 %.
_src = SRV[SRV.find("class _BambuFmp4Source"):SRV.find("def _bambu_camera_frames")]
check("H1. поток режется ещё и по времени", '"-frag_duration"' in _src and "FRAG_DURATION_US" in _src)
check("H2. шаг нарезки 200 мс", 'FRAG_DURATION_US = "200000"' in _src, _src[:0])
check("H3. нарезка по ключевым кадрам сохранена (иначе входить будет некуда)",
      "+frag_keyframe" in _src)

if STREAM is not None and _ffmpeg():
    _ff = _ffmpeg()
    _mk = lambda extra: subprocess.run(
        [_ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=320x240:rate=30", "-t", "4", "-c:v", "libx264",
         "-preset", "ultrafast", "-g", "60", "-pix_fmt", "yuv420p", "-an", "-f", "mp4",
         "-movflags", "+frag_keyframe+empty_moov+default_base_moof"] + extra + ["-"],
        capture_output=True, timeout=180).stdout
    _by_key = Fmp4Splitter().feed(_mk([]))
    _by_time = Fmp4Splitter().feed(_mk(["-frag_duration", "200000"]))
    check("H4. нарезка по времени даёт заметно больше порций (поток идёт ровно, а не рывками)",
          len(_by_time) >= 3 * max(1, len(_by_key)), (len(_by_key), len(_by_time)))
    _keys_time = [i for i, f in enumerate(_by_time) if Fmp4Splitter.is_keyframe_fragment(f)]
    _keys_key = [i for i, f in enumerate(_by_key) if Fmp4Splitter.is_keyframe_fragment(f)]
    check("H5. при нарезке по ключевым кадрам КАЖДЫЙ фрагмент ключевой",
          len(_keys_key) == len(_by_key), (len(_keys_key), len(_by_key)))
    check("H6. при нарезке по времени ключевых ровно столько, сколько ключевых кадров",
          0 < len(_keys_time) < len(_by_time), (len(_keys_time), len(_by_time)))
    check("H7. первый фрагмент всегда ключевой (с него и начинается эфир)",
          0 in _keys_time and 0 in _keys_key)

    # Зритель, подключившийся в середине, обязан начать с КЛЮЧЕВОГО фрагмента: кусок из
    # середины группы декодировать не с чего, и картинка рассыплется.
    hubK, clockK, madeK, pendingK = build_hub([b""], max_fragments_per_viewer=64)
    subK = hubK.subscribe("k")
    subK._sent_init = True                      # шапку он уже получил
    first_key = _keys_time[1] if len(_keys_time) > 1 else 0
    for n, f in enumerate(_by_time):
        if n < first_key - 2:
            continue
        subK._put(f, Fmp4Splitter.is_keyframe_fragment(f))
        if n >= first_key + 1:
            break
    got = list(subK._q)
    check("H8. поздний зритель получает первым КЛЮЧЕВОЙ фрагмент",
          bool(got) and Fmp4Splitter.is_keyframe_fragment(got[0]), len(got))
    check("H9. пропущенные до ключевого посчитаны честно", subK.waited_for_key >= 1,
          subK.waited_for_key)
else:
    for i in range(4, 10):
        check("H%d. ровный поток" % i, False, "ffmpeg недоступен")

# pending.shift() в pump() — это ВЫДАЧА следующего куска, она законна. Запрещено другое:
# подрезать очередь циклом, выбрасывая ещё не показанные фрагменты.
check("H10. проигрыватель НЕ выбрасывает фрагменты из середины очереди",
      "while (pending.length >" not in PLAYER and "append_backlog" in PLAYER)
# Alpha 2.877: порог догона стал именованным (MAX_LATENCY) вместо числа 6 — проверяем смысл.
check("H11. живой край догоняется мягко, а не прыжком времени",
      "playbackRate" in PLAYER and "lag > MAX_LATENCY" in PLAYER)


# ══════════════════════════════════════════════════════════════════════════════════════
section("G. Окно ffmpeg и сведения о потоке")

# Alpha 2.873. Дефект со снимка владельца 24.08.2026: при старте камер поверх интерфейса
# всплыли два чёрных окна ffmpeg.exe. Консольной программе Windows даёт окно, если не запретить.
#  17.09.2026: флаг «без окна» перестал быть личным делом ffmpeg — его получают ВСЕ консольные
#  программы продукта (окно выбора файлов, tasklist, netsh; жалоба владельца на окна cmd при
#  загрузке файлов). Поэтому число вхождений больше не закрепляем: проверяем, что флаг стоит у
#  ОБОИХ запусков ffmpeg. Правило целиком закреплено в tools/test_no_console_windows.py.
_ff_a = SRV[SRV.find("proc = subprocess.Popen(self._cmd()"):][:400]
_ff_b = SRV[SRV.find("proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL"):][:400]
check("G1. оба запуска ffmpeg просят Windows НЕ открывать окно",
      "creationflags=_no_window_flags()" in _ff_a and "creationflags=_no_window_flags()" in _ff_b
      and SRV.count("creationflags=_no_window_flags()") >= 2,
      SRV.count("creationflags=_no_window_flags()"))
check("G2. запрет окна берётся у subprocess и не ломает не-Windows",
      'getattr(subprocess, "CREATE_NO_WINDOW", 0)' in SRV)

_watch = SRV[SRV.find("def _watch_stderr"):SRV.find("def close", SRV.find("def _watch_stderr"))]
check("G3. сведения о потоке камеры читаются у самого ffmpeg", len(_watch) > 400, len(_watch))
check("G4. строка с адресом (в нём код доступа) в журнал НЕ попадает",
      '"://" in line' in _watch and "continue" in _watch)
check("G5. в журнал уходит только разобранное: кодек, разрешение, частота",
      "_RE_SIZE" in _watch and "_RE_FPS" in _watch and "камера отдаёт" in _watch)
check("G6. читается ВХОДНОЙ поток (что даёт камера), а не выходной",
      'line.startswith("Input #")' in _watch and 'line.startswith("Output #")' in _watch)
check("G7. stderr дренируется до конца — переполненная труба остановила бы ffmpeg посреди эфира",
      "iter(proc.stderr.readline" in _watch and "told" in _watch)

# Разбор проверяем на НАСТОЯЩЕМ выводе ffmpeg, а не на придуманной строке.
if STREAM is not None:
    _ff = _ffmpeg()
    _err = subprocess.run([_ff, "-hide_banner", "-f", "lavfi",
                           "-i", "testsrc2=size=1280x720:rate=15", "-t", "1", "-c:v", "libx264",
                           "-preset", "ultrafast", "-an", "-f", "null", "-"],
                          capture_output=True, timeout=120).stderr.decode("utf-8", "replace")
    _rc = re.compile(r"Video:\s*([a-z0-9_]+)", re.I)
    _rs = re.compile(r"\b(\d{2,5}x\d{2,5})\b")
    _rf = re.compile(r"([\d.]+)\s*fps\b", re.I)
    _in, _got = False, None
    for _ln in _err.splitlines():
        _ln = _ln.strip()
        if "://" in _ln:
            continue
        if _ln.startswith("Input #"):
            _in = True
            continue
        if _ln.startswith("Output #"):
            _in = False
            continue
        if not _in or "Video:" not in _ln:
            continue
        _sz = _rs.search(_ln)
        if not _sz:
            continue
        _got = (_rc.search(_ln).group(1), _sz.group(1), _rf.search(_ln).group(1) if _rf.search(_ln) else None)
        break
    check("G8. на настоящем выводе ffmpeg разбираются разрешение и частота",
          _got is not None and _got[1] == "1280x720" and _got[2] == "15", _got)
else:
    check("G8. на настоящем выводе ffmpeg разбираются разрешение и частота", False, "ffmpeg недоступен")


# ══════════════════════════════════════════════════════════════════════════════════════
section("I. Ровность потока: чей это рывок — программы или камеры")

# Alpha 2.875. Вопрос владельца 24.08.2026: «фризы — это плохая оптимизация программы или
# принтер/связь?». Отвечать надо фактом. Перерывы считаются ЗДЕСЬ, на приёме от принтера,
# то есть ДО показа: если перерыв виден тут, к отрисовке он отношения не имеет.
class _Log(object):
    def __init__(self):
        self.lines = []

    def _add(self, msg, *a):
        try:
            self.lines.append((msg % a) if a else msg)
        except Exception:
            self.lines.append(msg)

    def info(self, msg, *a):
        self._add(msg, *a)

    def warning(self, msg, *a):
        self._add("WARN " + msg, *a)

    def debug(self, msg, *a):
        pass


def _hub_with_log(chunks, after=None, **kw):
    lg = _Log()
    clock = Clock()
    made = []
    pending = []
    hub = Fmp4Hub(open_source=lambda key: made.append(FakeSource(chunks, after=after)) or made[-1],
                  now=clock, spawn=lambda fn: pending.append(fn), log=lg, **kw)
    return hub, clock, made, pending, lg


if STREAM is not None:
    # Ровный поток: доклад без тревоги.
    step = {"n": 0}

    def tick_even():
        step["n"] += 1
        even["clock"].t += 0.2          # порции строго каждые 200 мс

    even = {}
    # Кормим ЦЕЛЫМИ фрагментами: в жизни фрагмент собирается из нескольких кусков байтов и
    # готов раз в 200 мс. Если двигать часы на каждый КУСОК, модель врёт — фрагмент выходит
    # раз в тринадцать шагов, и ровный поток выглядит рваным. Ошибка была в проверке, не в коде.
    _sp0 = Fmp4Splitter()
    _fr0 = _sp0.feed(STREAM)
    # Окно доклада — 3 секунды при шаге 0,2 с, значит порций нужно не меньше пятнадцати.
    # Тестовый ролик короткий, поэтому фрагменты повторяются: распорядителю важно ЧИСЛО
    # приходов и промежутки между ними, а не содержимое картинки.
    FEED = [_sp0.init_segment] + _fr0 * 12
    hub, clock, made, pending, lg = _hub_with_log(
        FEED, after=tick_even, report_every=3.0, long_gap=1.0)
    even["clock"] = clock
    hub.subscribe("k")
    pending.pop(0)()
    _even_lines = [x for x in lg.lines if "порций" in x]
    check("I1. по ровному потоку есть доклад в журнал", bool(_even_lines), lg.lines[-2:])
    check("I2. ровный поток НЕ помечается тревогой",
          all(not x.startswith("WARN") for x in _even_lines), _even_lines[:2])
    check("I3. в докладе есть число порций и самый долгий перерыв",
          any("самый долгий перерыв" in x for x in _even_lines), _even_lines[:2])

    # Рваный поток: перерывы обязаны быть названы прямо.
    gap = {"n": 0}

    def tick_gappy():
        gap["n"] += 1
        gappy["clock"].t += 3.0 if gap["n"] % 5 == 0 else 0.2   # раз в пять порций — провал

    gappy = {}
    hub2, clock2, made2, pending2, lg2 = _hub_with_log(
        FEED, after=tick_gappy, report_every=3.0, long_gap=1.0)
    gappy["clock"] = clock2
    hub2.subscribe("k")
    pending2.pop(0)()
    _bad = [x for x in lg2.lines if x.startswith("WARN")]
    check("I4. рваный поток помечается тревогой", bool(_bad), lg2.lines[-2:])
    check("I5. в тревоге назван самый долгий перерыв и их число",
          bool(_bad) and "самый долгий" in _bad[0] and "раз(а)" in _bad[0], _bad[:1])
    check("I6. прямо сказано, что перерыв случился В ПОТОКЕ ОТ ПРИНТЕРА",
          bool(_bad) and "ОТ ПРИНТЕРА" in _bad[0], _bad[:1])
else:
    for i in range(1, 7):
        check("I%d. ровность потока" % i, False, "нет настоящего потока")


# ══════════════════════════════════════════════════════════════════════════════════════
section("I. Отставший зритель: пересинхронизация вместо каши")

# Alpha 2.875. Владелец 24.08.2026: «на работающих камерах до сих пор видны фризы».
# Здесь была НАША причина: при переполнении очереди зрителя выбрасывался старый фрагмент
# (popleft). Для H.264 это рвёт цепочку декодирования, и картинка сыплется до следующего
# ключевого кадра — то есть секунды. Правильно — начать заново с ключевого фрагмента.
if STREAM is not None:
    _hub, _clock, _made, _pending = build_hub([b""], max_fragments_per_viewer=3)
    _sub = _hub.subscribe("k")
    _sub._sent_init = True
    _keyfrags = [f for f in frags if Fmp4Splitter.is_keyframe_fragment(f)]
    check("I0. в тестовом потоке есть ключевые фрагменты", len(_keyfrags) >= 2, len(_keyfrags))
    # первый ключевой принят, затем заваливаем очередь сверх предела
    _sub._put(frags[0], True)
    for f in frags[1:]:
        _sub._put(f, Fmp4Splitter.is_keyframe_fragment(f))
    for i in range(6):
        _sub._put(frags[0], True)
    check("I1. при переполнении очередь ОЧИЩАЕТСЯ, а не подрезается по одному",
          len(_sub._q) <= 3 + 1, len(_sub._q))
    check("I2. пересинхронизации посчитаны", _sub.resyncs >= 1, _sub.resyncs)
    # после пересинхронизации первым уходит именно ключевой фрагмент
    _hub2, _c2, _m2, _p2 = build_hub([b""], max_fragments_per_viewer=2)
    _s2 = _hub2.subscribe("k")
    _s2._sent_init = True
    # Ровно до переполнения: при пределе 2 третья порция обязана вызвать пересинхронизацию.
    for i in range(3):
        _s2._put(frags[0], True)
    check("I2b. переполнение вызвало пересинхронизацию", _s2.resyncs == 1 and not _s2._q,
          (_s2.resyncs, len(_s2._q)))
    _fake = bytes([0, 0, 0, 16]) + b"moof" + b"NOTKEY__"   # неключевой сразу после сброса
    _s2._put(_fake, False)
    check("I3. сразу после пересинхронизации неключевой фрагмент НЕ выдаётся",
          all(x[4:8] == b"moof" for x in _s2._q) and b"NOTKEY" not in b"".join(_s2._q))
    _st = _hub.stats("k")
    check("I4. пересинхронизации видны в статистике", "resyncs" in (_st or {}), _st)
else:
    for i in range(5):
        check("I%d. пересинхронизация" % i, False, "нет настоящего потока")

# popleft() в выдаче зрителю — это ВЫДАЧА очередной порции, она законна. Запрещено другое:
# подрезать очередь циклом, выбрасывая ещё не показанные фрагменты.
_CAM = io.open(os.path.join(ROOT, "app", "camera_fmp4.py"), encoding="utf-8").read()
check("I5. очередь зрителя не подрезается выбрасыванием старых фрагментов",
      "while len(self._q) > self._max" not in _CAM and "self._q.clear()" in _CAM)
check("I6. отставание зрителя попадает в журнал (иначе причину фризов не найти)",
      "зритель отстал" in io.open(os.path.join(ROOT, "app", "camera_fmp4.py"), encoding="utf-8").read())


# ══════════════════════════════════════════════════════════════════════════════════════
section("J. Живой приём и укладка без дыр (причина фризов у Bambu)")

# Alpha 2.876. Числа владельца 24.08.2026: P2S показывал 0.0 к/с ПРИ ЖИВОЙ КАРТИНКЕ, H2S 18
# вместо 30, а K2 через WebRTC шёл ровно. Разобрано по источникам: у RTSP-камер метки времени
# бывают неровными, а браузер в режиме 'segments' раскладывает куски ИМЕННО по этим меткам —
# на ленте появляются дыры, и видео на дыре ВСТАЁТ. Документация Chrome для MSE прямо
# предлагает режим 'sequence': куски укладываются подряд, без дыр. Оговорка про
# рассинхронизацию дорожек к нам не относится — звука в потоке нет вовсе.
# Слово 'segments' в пояснении — это объяснение, почему так нельзя; запрещено ПРИСВОЕНИЕ.
check("J1. куски укладываются подряд, а не по меткам времени из потока",
      "sourceBuffer.mode = 'sequence'" in PLAYER
      and "sourceBuffer.mode = 'segments'" not in PLAYER)
check("J2. в коде объяснено, почему не 'segments' (иначе вернут обратно)",
      "дыр" in PLAYER and "sequence" in PLAYER)
check("J3. есть сторож застревания: время не идёт, а данные впереди есть",
      "function watchStall" in PLAYER and "stallJumps" in PLAYER)
check("J4. сторож перешагивает ИМЕННО на ближайший кусок после текущего времени",
      "b.start(i) > cur" in PLAYER)
check("J5. сторож запускается и останавливается вместе с потоком",
      "stallTimer = env.setInterval(watchStall" in PLAYER and "clearInterval(stallTimer)" in PLAYER)

_src2 = SRV[SRV.find("class _BambuFmp4Source"):SRV.find("def _bambu_camera_frames")]
# Сама команда без пояснений: в комментариях выброшенные ключи названы поимённо, и проверка
# по всему тексту класса ловила бы их снова.
_cmd_src = _src2[_src2.find("return [_ffmpeg_bin()"):]
_cmd_src = _cmd_src[:_cmd_src.find(chr(34) + "-" + chr(34) + "]") + 4]
_cmd_src = chr(10).join(l for l in _cmd_src.split(chr(10)) if not l.strip().startswith("#"))
# Alpha 2.878. Проверки J6-J9 РАЗВЁРНУТЫ: раньше они требовали «ключи живого приёма», а именно
# они и выбрасывали данные. Основание — прямое сравнение владельца 24.08.2026: та же камера,
# та же сеть, тот же ffmpeg, старый путь идёт ровно, наш фризит. Для H.264 без перекодирования
# любая потеря стоит до двух секунд замершей картинки (ключевой кадр у камеры раз в 2 секунды).
check("J6. битые пакеты НЕ выбрасываются: для H.264 это до двух секунд замершей картинки",
      "discardcorrupt" not in _cmd_src)
check("J7. опоздавшие и переставленные пакеты НЕ выбрасываются",
      "reorder_queue_size" not in _cmd_src and "max_delay" not in _cmd_src)
check("J8. метки времени не переписываются: перекладка не должна вмешиваться в поток",
      "genpts" not in _cmd_src)
check("J8a. приём такой же осторожный, как в проверенном рабочем пути",
      '"-rtsp_transport", "tcp"' in _cmd_src and "nobuffer" not in _cmd_src)
check("J8b. порции отдаются в трубу сразу: direct стоит ПОСЛЕ входа, то есть на выходе",
      _cmd_src.find('"-avioflags", "direct"') > _cmd_src.find('"-i", url') > 0)
check("J9. поток не изучается пять секунд перед первым кадром",
      '"-analyzeduration", "500000"' in _cmd_src and '"-probesize", "500000"' in _cmd_src)
check("J10. перекодирования по-прежнему НЕТ (иначе вся затея теряет смысл)",
      '"-c:v", "copy"' in _cmd_src)

# Ключи обязаны работать на настоящем ffmpeg, а не только выглядеть правильно.
if _ffmpeg():
    _ff = _ffmpeg()
    _cmd = [_ff, "-hide_banner", "-loglevel", "error",
            "-analyzeduration", "500000", "-probesize", "500000",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15", "-t", "3",
            "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-pix_fmt", "yuv420p",
            "-an", "-avioflags", "direct",
            "-f", "mp4", "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
            "-frag_duration", "200000", "-"]
    _p = subprocess.run(_cmd, capture_output=True, timeout=180)
    _sp = Fmp4Splitter()
    _fr = _sp.feed(_p.stdout or b"")
    check("J11. настоящий ffmpeg принимает НОВЫЙ набор ключей и отдаёт годный поток",
          _p.returncode == 0 and bool(_sp.init_segment) and len(_fr) >= 5,
          (_p.returncode, len(_fr), (_p.stderr or b"")[-160:]))
    check("J12. в потоке есть ключевые фрагменты — зрителю есть с чего начать",
          any(Fmp4Splitter.is_keyframe_fragment(f) for f in _fr))
else:
    check("J11. настоящий ffmpeg принимает эти ключи", False, "ffmpeg недоступен")
    check("J12. в потоке есть ключевые фрагменты", False, "ffmpeg недоступен")


# ══════════════════════════════════════════════════════════════════════════════════════
section("K. Запас видео вместо погони за живым краем")

# Alpha 2.877. Фризы остались и после укладки без дыр. При разборе СВОЕГО кода нашлась
# причина на ровном месте: воспроизведение гналось вплотную к последнему пришедшему кадру
# (догон при отставании 1,2 с, прыжок на 0,2-0,4 с от края). Порции идут каждые 200 мс по
# сети — при таком запасе любая задержка означает, что играть нечего, картинка встаёт,
# сторож прыгает обратно на край, и всё повторяется.
check("K1. запас видео задан явной величиной, а не разбросанными числами",
      "const TARGET_LATENCY" in PLAYER and "const MAX_LATENCY" in PLAYER
      and "const KEEP_BUFFER" in PLAYER)
check("K2. запас не меньше секунды (шесть порций по 200 мс)",
      re.search(r"TARGET_LATENCY\s*=\s*([\d.]+)", PLAYER)
      and float(re.search(r"TARGET_LATENCY\s*=\s*([\d.]+)", PLAYER).group(1)) >= 1.0,
      re.search(r"TARGET_LATENCY\s*=\s*([\d.]+)", PLAYER).group(1) if re.search(r"TARGET_LATENCY\s*=\s*([\d.]+)", PLAYER) else None)
check("K3. прыжок ведёт НА ЗАПАС, а не на край (иначе застревание повторится)",
      "end - TARGET_LATENCY" in PLAYER and "end - 0.2" not in PLAYER and "end - 0.4" not in PLAYER)
check("K4. скорость правится мягко: 5 % ускорения, а не 10 %",
      "rate = 1.05" in PLAYER and "rate = 1.1;" not in PLAYER)
check("K5. когда запас кончается — чуть замедляемся, чтобы он восстановился",
      "rate = 0.97" in PLAYER)
# Alpha 2.879: порог опущен с половины цели до трети — при половине сторож молчал ровно в той
# полосе, где проигрыватель и живёт.
check("K6. накопление запаса не считается застреванием",
      "TARGET_LATENCY * 0.35" in PLAYER)
check("K7. в памяти держим прошлое ограниченно", "KEEP_BUFFER" in PLAYER and "sourceBuffer.remove(" in PLAYER)


# ══════════════════════════════════════════════════════════════════════════════════════
section("L. Плитка сама отвечает: перерыв связи или застревание показа")

# Владелец журналы не читает, и это нормально: ответ обязан быть там, куда он смотрит.
# Считаем ДВЕ РАЗНЫЕ вещи: перерыв ПРИЁМА (данные не пришли — связь и камера) и застревание
# ПОКАЗА (данные есть, картинка стоит — это мы). Смешивать их нельзя: смешанный счётчик
# ничего не доказывает.
check("L1. перерыв приёма считается отдельно от застревания показа",
      "streamGaps" in PLAYER and "stallJumps" in PLAYER)
check("L2. перерывом считается тишина от секунды (порции идут каждые 200 мс)",
      "const STREAM_GAP_MS = 1000" in PLAYER)
check("L3. время прихода порции можно подменить в тесте",
      "options.now" in PLAYER)
check("L4. счётчики обнуляются при новом запуске",
      "state.streamGaps = 0" in PLAYER and "lastFragAt = 0" in PLAYER)

# ── настоящий счёт: настоящий код проигрывателя, настоящие байты ffmpeg, подменённые часы ──
# Стенд tools/_camera_fmp4_gap_harness.mjs подставляет только то, чего в Node нет физически
# (MediaSource, SourceBuffer, fetch, видеоэлемент). Разбор потока и счёт перерывов делает сам
# проигрыватель. Часы переводятся на две секунды между порциями — это и есть провал связи.
if STREAM is None:
    check("L5. перерыв приёма считается по настоящим байтам", False, "нет потока")
else:
    import base64 as _b64
    import tempfile as _tmp
    _td = _tmp.mkdtemp(prefix="fm877_")
    _bp = os.path.join(_td, "stream.b64")
    io.open(_bp, "w", encoding="ascii").write(_b64.b64encode(STREAM).decode("ascii"))
    _purl = "file:///" + os.path.join(ROOT, "web", "composables",
                                      "useCameraFmp4.js").replace(chr(92), "/")
    _hp = os.path.join(ROOT, "tools", "_camera_fmp4_gap_harness.mjs")
    _res = None
    try:
        _r = subprocess.run([_node, _hp, _purl, _bp], capture_output=True, timeout=120)
        _o = (_r.stdout or b"").decode("utf-8", "replace")
        _m = re.search(r"@@(.*)@@", _o, re.S)
        _res = json.loads(_m.group(1)) if _m else None
        if _res is None:
            check("L5. проигрыватель отработал на стенде", False,
                  ((_r.stderr or b"").decode("utf-8", "replace") or _o)[-300:])
    except Exception as _e:
        check("L5. проигрыватель отработал на стенде", False, str(_e))
    # Alpha 2.879: тот же стенд, но доставка по сокету. Данные те же настоящие байты ffmpeg.
    _res_ws = None
    try:
        _r2 = subprocess.run([_node, _hp, _purl, _bp, "ws"], capture_output=True, timeout=120)
        _o2 = (_r2.stdout or b"").decode("utf-8", "replace")
        _m2 = re.search(r"@@(.*)@@", _o2, re.S)
        _res_ws = json.loads(_m2.group(1)) if _m2 else None
        if _res_ws is None:
            check("L6. проигрыватель отработал по сокету", False,
                  ((_r2.stderr or b"").decode("utf-8", "replace") or _o2)[-300:])
    except Exception as _e2:
        check("L6. проигрыватель отработал по сокету", False, str(_e2))
    finally:
        try:
            os.remove(_bp)
            os.rmdir(_td)
        except Exception:
            pass
    if _res_ws:
        check("L6. по сокету приезжают те же порции, и это видно в состоянии",
              _res_ws.get("transport") == "ws" and int(_res_ws.get("frags") or 0) >= 2, _res_ws)
        check("L6a. адрес сокета выведен из адреса маршрута (camera.mp4 -> camera.ws)",
              str(_res_ws.get("wsUrl") or "").endswith("/camera.ws")
              and str(_res_ws.get("wsUrl") or "").startswith("ws://"), _res_ws)
        check("L6b. счёт перерывов работает и по сокету",
              _res_ws.get("gaps") == 1, _res_ws)
    if _res:
        check("L5. две секунды тишины засчитаны как ОДИН перерыв приёма",
              _res.get("gaps") == 1, _res)
        check("L5a. самый долгий перерыв измерен верно (2 секунды)",
              1900 <= float(_res.get("max") or 0) <= 2100, _res)
        check("L5b. застреваний показа при этом не приписано",
              _res.get("stalls") == 0, _res)
        check("L5c. порции дошли до буфера, а укладка без дыр включена",
              int(_res.get("frags") or 0) >= 2 and _res.get("mode") == "sequence", _res)

#  26.09.2026: «Видеостены» может не быть — в открытой выгрузке модуль придержан до решения
#  владельца об авторстве. Тогда L6-L8 пропускаются с пометкой; проигрыватель ядра проверен выше.
if not os.path.isfile(os.path.join(ROOT, "modules", "camera_wall", "module.json")):
    print("SKIP — L6-L8. модуля «Видеостена» в этой копии нет (придержан вне открытой выгрузки)")
else:
    _MOD = io.open(os.path.join(ROOT, "modules", "camera_wall", "web", "provider-core-fmp4.js"),
                   encoding="utf-8").read()
    _PANEL = io.open(os.path.join(ROOT, "modules", "camera_wall", "web", "CameraWallPanel.js"),
                     encoding="utf-8").read()
    check("L6. модуль забирает счётчики у проигрывателя, а не выдумывает свои",
          "player.state" in _MOD and "streamGaps" in _MOD and "stallJumps" in _MOD)
    check("L7. на плитке связь и показ названы разными словами",
          "связь: " in _PANEL and "показ: " in _PANEL)
    check("L8. молчаливого счёта нет: пока перерывов нет, лишнего на плитке не появляется",
          "if (st.streamGaps)" in _MOD and "if (st.stallJumps)" in _MOD)


# ══════════════════════════════════════════════════════════════════════════════════════
section("M. Мы не теряем данные: у H.264 потеря стоит до двух секунд")

# Владелец 24.08.2026: «если убрать галку «без кодировки», становится намного лучше и
# практически не фризится». Это прямое сравнение на ОДНОЙ камере и ОДНОЙ сети, и оно
# доказывает: поток от принтера в порядке, теряем данные мы. Разница между путями в том,
# что MJPEG — независимые картинки (потеря = один кадр), а H.264 без перекодирования —
# цепочка (потеря = замершая картинка до следующего ключевого кадра, у Bambu это 2 секунды).
# Поэтому здесь проверяется ровно одно: в нашем пути НЕТ мест, где данные выбрасываются.

_hub_src = SRV[SRV.find("_camera_fmp4_hub = Fmp4Hub("):SRV.find("_camera_fmp4_hub = Fmp4Hub(") + 900]
_m_q = re.search(r"max_fragments_per_viewer=(\d+)", _hub_src)
check("M1. очередь зрителя вмещает не меньше 25 порций (5 секунд), а не 1,6 секунды",
      _m_q and int(_m_q.group(1)) >= 25, _m_q.group(1) if _m_q else None)
check("M2. переполнение очереди — редкое событие, и о нём сообщают",
      "зритель отстал" in HUB)
check("M3. промежуточные фрагменты по-прежнему НЕ выбрасываются поштучно",
      "self._q.popleft()" not in HUB.replace("data = self._q.popleft()", ""))
check("M4. ключи, выбрасывающие данные, не вернулись в команду ffmpeg",
      not any(k in _cmd_src for k in ("discardcorrupt", "reorder_queue_size")))

# ══════════════════════════════════════════════════════════════════════════════════════
section("N. Шесть камер — это предел БРАУЗЕРА, и мы из него выходим")

# ИЗМЕРЕНО 25.08.2026 на этой машине (локальный сервер + 12 одинаковых длинных потоков в
# настоящем браузере): потоки 0-5 получили первый байт сразу, потоки 6-11 не получили НИЧЕГО.
# Двенадцать WebSocket к тому же адресу открылись все за 0,2 секунды. Это и есть жалоба
# владельца «загружаются шесть камер, остальные пытаются подключиться».
_ws_src = SRV[SRV.find("async def printer_camera_ws"):]
_ws_src = _ws_src[:_ws_src.find("class WebRTCOffer")]
check("N1. маршрут камеры по WebSocket есть", "@app.websocket(" in SRV
      and "/api/printer/{pid}/camera.ws" in SRV)
check("N2. он записан в реестр маршрутов как WS, а не как GET",
      "('WS', '/api/printer/{pid}/camera.ws'" in REG)
check("N3. рукопожатие проверяется ДО приёма: сначала Origin, затем сессия",
      _ws_src.find("ws_origin_allowed") < _ws_src.find("_ws_access.evaluate")
      < _ws_src.find("await ws.accept()"))
check("N4. чужая страница не получит камеру: при отказе сокет закрывается без приёма",
      _ws_src.count("await ws.close(code=1008)") >= 2)
# Alpha 2.880: сокет обязан перепроверять доступ и ПОСЛЕ рукопожатия — так же, как сокет
# телеметрии. Иначе отозванная сессия смотрела бы камеру, пока браузер сам не отключится.
# 16.10.2026 (R-150): перепроверка идёт всегда, и при выключенной защите; включение защиты
# закрывает открытую без входа камеру — исполнением это закрепляет
# tools/test_websocket_session_lifecycle.py, пункт 51c.
check("N4a. доступ перепроверяется и после приёма, тем же движком и с тем же периодом",
      "handshake=False" in _ws_src and "_WS_REVALIDATE_S" in _ws_src)
check("N4b. при потере доступа соединение закрывается кодом из вердикта",
      "_v.close_code or _ws_access.CLOSE_POLICY" in _ws_src)
check("N5. данные берутся у ТОГО ЖЕ владельца потока — соединение с принтером по-прежнему одно",
      "_bambu_hub_fmp4(" in _ws_src)
check("N6. синхронный генератор крутится в отдельном потоке, а не в цикле событий",
      "iterate_in_threadpool" in _ws_src)
check("N7. при разрыве поток закрывается явно — иначе ffmpeg остался бы без зрителей",
      "gen.close" in _ws_src)
check("N8. не-Bambu и P1/P1S сюда не пускаются (у них другой поток)",
      "01P" in _ws_src and "01S" in _ws_src and 'ptype != "bambu"' in _ws_src)
check("N9. код доступа принтера в сокет не уходит",
      "rtsps://" not in _ws_src and "self._code" not in _ws_src)

check("N10. проигрыватель пробует сокет ПЕРВЫМ, а HTTP оставляет запасным",
      PLAYER.find("streamOverWs(") < PLAYER.find("await env.fetch(url")
      and "ws_no_data" in PLAYER)
check("N11. адрес сокета выводится из адреса маршрута — модуль менять не нужно",
      "camera.ws" in PLAYER and "wsUrlFrom" in PLAYER)
check("N12. сокет закрывается вместе с показом",
      "sock.close()" in PLAYER and "sock = null" in PLAYER)
check("N13. видно, чем реально приехало видео",
      "state.transport" in PLAYER)

# ══════════════════════════════════════════════════════════════════════════════════════
section("O. Рабочая камера не должна выглядеть сломанной")

# Все три дефекта найдены разбором 25.08.2026 и перепроверены по коду вручную.
# Смотрим на КОД, а не на пояснения: в комментарии прежнее условие названо дословно — именно
# оно и было дефектом.
_pl_code = chr(10).join(l for l in PLAYER.split(chr(10)) if not l.strip().startswith("//"))
# Alpha 2.885: у разбора теперь ОДИН выход, поэтому и вызов один — это правильнее, чем два.
check("O1. «пошло видео» говорится при ПЕРВОЙ порции, в какой бы куске она ни пришла",
      "function noteLive" in _pl_code and _pl_code.count("noteLive()") >= 2
      and "state.fragments === 1" not in _pl_code)
check("O2. признак сбрасывается при новом запуске",
      "liveSaid = false" in PLAYER)
check("O3. отставание очереди — предупреждение, а не смерть плитки",
      "say('backlog'" in PLAYER and "pending.length > 200" in PLAYER)
check("O4. запас подтягивается К ЦЕЛИ, а не оседает на нижнем краю",
      "TARGET_LATENCY * 1.6" in PLAYER and "TARGET_LATENCY * 0.9" in PLAYER
      and "TARGET_LATENCY * 2)" not in PLAYER)
check("O5. сторож не выключен в рабочей полосе",
      "TARGET_LATENCY * 0.35" in PLAYER)

# Первая порция ПОСЛЕ шапки обязана быть ключевой — иначе декодировать не от чего.
check("O6. после выдачи шапки распределитель снова ждёт ключевой фрагмент",
      "sub._need_key = True" in HUB)

# Настоящая проверка поведением: зритель подписался ПОЗЖЕ начала, накопились не-ключевые
# фрагменты, и первым после шапки обязан прийти именно ключевой.
_kh = Fmp4Hub(open_source=lambda key: None, log=None)
_ok7 = False
_why7 = ""
try:
    _key = "10.0.0.9|FIXTURE"
    _sub = _kh.subscribe(_key)
    with _kh._lock:
        _kh._owners[_key]["init"] = b"INIT"
        _sub._need_key = False           # как будто ключевой фрагмент уже был получен
        _sub._q.append(b"PFRAME")        # накопился НЕ ключевой фрагмент
    _first = _kh._wait_chunk(_key, _sub, 0.1)
    _second = _kh._wait_chunk(_key, _sub, 0.1)
    _ok7 = (_first == b"INIT" and _second is None and _sub._need_key is True)
    _why7 = (_first, _second, _sub._need_key)
    _sub.close()
except Exception as _e7:
    _why7 = str(_e7)
check("O7. не-ключевой фрагмент за шапкой зрителю НЕ уходит (проверено поведением)",
      _ok7, _why7)

# ══════════════════════════════════════════════════════════════════════════════════════
section("P. Цепочка камеры сходится во всех пяти местах")

# Alpha 2.882. Адрес камеры живёт в пяти файлах: окно программы, модуль стены,
# проигрыватель (выводит адрес сокета), маршрут сервера и опись прав. Каждый прежний набор
# смотрел на свою половину — переименование в одном месте прошло бы незамеченным, а картинка
# пропала бы только на части экранов.
_HTTP_ROUTE = "/api/printer/{pid}/camera.mp4"
_WS_ROUTE = "/api/printer/{pid}/camera.ws"
#  26.09.2026: «Видеостены» может не быть (придержана вне открытой выгрузки) — тогда P5 пропускается.
_CAM_JS = os.path.join(ROOT, "modules", "camera_wall", "web", "camera-providers.js")
_MODJS = io.open(_CAM_JS, encoding="utf-8").read() if os.path.isfile(_CAM_JS) else None

check("P1. маршрут HTTP объявлен в server.py",
      (chr(34) + _HTTP_ROUTE + chr(34)) in SRV and "@app.get(" in SRV)
check("P2. маршрут сокета объявлен в server.py",
      (chr(34) + _WS_ROUTE + chr(34)) in SRV and "@app.websocket(" in SRV)
check("P3. оба маршрута записаны в опись прав",
      ("'" + _HTTP_ROUTE + "'") in REG and ("'" + _WS_ROUTE + "'") in REG)
check("P4. окно программы зовёт ровно этот адрес",
      "/camera.mp4" in APPJS and "camFmp4.start(" in APPJS)
if _MODJS is None:
    print("SKIP — P5. модуля «Видеостена» в этой копии нет (придержан вне открытой выгрузки)")
else:
    check("P5. модуль стены зовёт ровно этот адрес",
          "/camera.mp4" in _MODJS and "CoreFmp4Provider(" in _MODJS)
check("P6. проигрыватель выводит адрес сокета ИЗ адреса маршрута",
      "camera.ws" in PLAYER and "camera" + chr(92) + ".mp4$" in PLAYER)
check("P7. имена обработчиков в описи совпадают с объявленными в коде",
      "printer_camera_mp4" in SRV and "printer_camera_mp4" in REG
      and "printer_camera_ws" in SRV and "printer_camera_ws" in REG)
check("P8. запасной путь MJPEG на месте — его никто не сломал",
      (chr(34) + "/api/printer/{pid}/camera" + chr(34)) in SRV and "camera-providers" not in SRV)

# ══════════════════════════════════════════════════════════════════════════════════════
section("Q. Поток можно резать где угодно — разбор не меняется")

# Alpha 2.885. Замечание тестировщика (аппаратный стенд, 2.877) подтвердилось по коду:
# сеть режет поток где попало, а разбор считал разобранным то, что дошло не целиком.
# ИЗМЕРЕНО на прежнем коде тем же стендом: при обычных сетевых блоках по 64 КБ терялось
# 6 фрагментов из 30, а при мелких блоках проигрыватель отдавал браузеру ОДИН ftyp в 28
# байт и больше ничего — картинка не появлялась вовсе.
# Здесь доказывается обратное: место разреза не влияет ни на один байт.

def _boxes_py(data):
    """Границы коробок MP4 — своя, независимая от проверяемого кода, разметка."""
    out = []
    off = 0
    while off + 8 <= len(data):
        size = int.from_bytes(data[off:off + 4], "big")
        head = 8
        if size == 1:
            if off + 16 > len(data):
                break
            size = int.from_bytes(data[off + 8:off + 16], "big")
            head = 16
        if size < head or off + size > len(data):
            break
        out.append((data[off + 4:off + 8].decode("ascii", "replace"), off, off + size))
        off += size
    return out


def _chunk_run(mode, b64_path, node_bin, harness, player_url):
    r = subprocess.run([node_bin, harness, player_url, b64_path, mode],
                       capture_output=True, timeout=600)
    out = (r.stdout or b"").decode("utf-8", "replace")
    m = re.search(r"@@(.*)@@", out, re.S)
    if not m:
        return None, ((r.stderr or b"").decode("utf-8", "replace") or out)[-300:]
    return json.loads(m.group(1)), ""


if STREAM is None:
    check("Q1. поток режется где угодно", False, "нет потока ffmpeg")
else:
    import base64 as _b64q
    import tempfile as _tmpq
    _tdq = _tmpq.mkdtemp(prefix="fm885_")
    _bpq = os.path.join(_tdq, "stream.b64")
    io.open(_bpq, "w", encoding="ascii").write(_b64q.b64encode(STREAM).decode("ascii"))
    _purlq = "file:///" + os.path.join(ROOT, "web", "composables",
                                       "useCameraFmp4.js").replace(chr(92), "/")
    _hpq = os.path.join(ROOT, "tools", "_camera_fmp4_chunk_harness.mjs")
    _base, _err = _chunk_run("all", _bpq, _node, _hpq, _purlq)
    check("Q1. эталон: весь поток одним куском разобран", bool(_base and _base.get("appends")), _err)
    if _base:
        _ap = _base["appends"]
        check("Q2. первым в приёмник уходит ОДНА шапка, и она начинается с ftyp",
              _ap and _ap[0]["type"] == "ftyp", _ap[0] if _ap else None)
        _boxes = _boxes_py(STREAM)
        _moov = [b for b in _boxes if b[0] == "moov"]
        check("Q3. шапка отдана целиком — до конца moov, а не до конца ftyp",
              bool(_moov) and _ap[0]["len"] == _moov[0][2],
              (_ap[0]["len"] if _ap else None, _moov[0][2] if _moov else None))
        _pairs = sum(1 for i, b in enumerate(_boxes[:-1])
                     if b[0] == "moof" and _boxes[i + 1][0] == "mdat")
        check("Q4. отданы ВСЕ фрагменты потока, ни один не потерян",
              len(_ap) == 1 + _pairs, (len(_ap) - 1, _pairs))

        _same = []
        for _mode in ("size:1", "size:3", "size:64", "size:1000", "size:65536"):
            _r, _e = _chunk_run(_mode, _bpq, _node, _hpq, _purlq)
            _same.append((_mode, bool(_r) and _r.get("appends") == _ap))
        check("Q5. разрез по 1, 3, 64, 1000 и 65536 байт даёт ТО ЖЕ САМОЕ, побайтно",
              all(ok for _m, ok in _same), [m for m, ok in _same if not ok])

        #  Самый злой разрез — ровно по шву между moof и его mdat, и на байт раньше.
        _cuts = []
        for _i, _b in enumerate(_boxes[:-1]):
            if _b[0] == "moof" and _boxes[_i + 1][0] == "mdat":
                _cuts.append(_b[2])
                _cuts.append(max(1, _b[2] - 1))
        _cuts = sorted(set(_cuts))[:60]
        _r, _e = _chunk_run("offsets:" + ",".join(str(c) for c in _cuts), _bpq, _node, _hpq, _purlq)
        check("Q6. разрез ровно по шву moof|mdat ничего не меняет",
              bool(_r) and _r.get("appends") == _ap,
              (len((_r or {}).get("appends") or []), len(_ap), _e))

        #  Шапка, разорванная между ftyp и moov, обязана собраться в ОДНУ шапку.
        _r, _e = _chunk_run("offsets:%d" % (_boxes[0][2],), _bpq, _node, _hpq, _purlq)
        check("Q7. ftyp и moov, пришедшие разными кусками, дают одну правильную шапку",
              bool(_r) and _r.get("appends") == _ap, _e)

        check("Q8. ни один байт неполной коробки не потерян (сумма длин совпала)",
              bool(_r) and sum(a["len"] for a in _r["appends"]) == sum(a["len"] for a in _ap))
    try:
        os.remove(_bpq)
        os.rmdir(_tdq)
    except Exception:
        pass

# Сторожа против возврата обоих дефектов — на случай, если кто-то «упростит» разбор.
_q_moov = "=== " + chr(39) + "moov" + chr(39)
check("Q9. шапка не отправляется, пока не пришёл moov целиком",
      _q_moov in PLAYER and "findIndex" in PLAYER)
check("Q10. moof без своего mdat остаётся в остатке, а не выбрасывается",
      "if (!mdat) break;" in PLAYER)
check("Q11. разобранным считается только дошедшее целиком (keep, а не consumed)",
      "carry = merged.slice(keep)" in PLAYER and "const { boxes, consumed }" not in PLAYER)

# ══════════════════════════════════════════════════════════════════════════════════════
section("R. Один внешний поток на принтер — каким бы путём его ни смотрели")

# Alpha 2.886. Замер тестировщика на живом P2S: одновременно жили MJPEG-процесс и
# fMP4-процесс, у каждого своё соединение на порт 322, и через ~10 секунд наступало
# зависание; после закрытия окна сторож пересоздавал оба с новыми номерами. Причина в коде:
# раздатчика два, ключ одинаковый, но объекты разные — общий ключ их не объединял.
# Здесь проверяется поведением: право на поток одно, чужой путь гасится, а сторож не может
# поднять источник, пока право у другого.

_R_opened = []
_R_closed = []


class _RSrc(object):
    """Подставной источник: помнит, что его открыли и закрыли. Ни сети, ни процессов."""

    def __init__(self, key):
        self.key = key
        _R_opened.append(key)

    def read(self, n=65536):
        return b""

    def close(self):
        _R_closed.append(self.key)


_R_allow = {"fmp4": True}
#  Часы подставные: отказ в праве откладывает следующую попытку на секунду, и без управляемого
#  времени проверка зависела бы от скорости машины.
_R_clock = {"t": 1000.0}
_rhub = Fmp4Hub(open_source=lambda key: _RSrc(key), spawn=lambda fn: None,
                idle_grace=0.0, log=None, now=lambda: _R_clock["t"],
                can_start=lambda key: _R_allow["fmp4"])
_rkey = "10.0.0.55|FIXTURE"
#  Право отдано другому пути ЕЩЁ ДО подписки: именно так и бывает, когда стена переключается
#  на запасной путь, а прежний зритель ещё жив.
_R_allow["fmp4"] = False
_rsub = _rhub.subscribe(_rkey)
_rhub.tick()
check("R1. пока право у другого пути, источник НЕ поднимается даже при живом зрителе",
      not _R_opened, _R_opened)

_R_allow["fmp4"] = True
_R_clock["t"] += 2.0          # прошло две секунды — отсрочка после отказа истекла
_rhub.tick()
check("R2. как только право получено, источник поднимается", _R_opened == [_rkey], _R_opened)

check("R3. stop_key гасит владельца и ЗАКРЫВАЕТ источник (сначала погасить, потом поднять)",
      _rhub.stop_key(_rkey) and _R_closed == [_rkey], (_R_closed,))

_R_allow["fmp4"] = False
_R_clock["t"] += 2.0
_rhub.tick()
check("R4. после гашения сторож не поднимает источник заново, пока право у чужого пути",
      _R_opened == [_rkey], _R_opened)

check("R5. stop_key для незнакомого принтера ничего не ломает и говорит False",
      _rhub.stop_key("10.0.0.56|FIXTURE") is False)
_rsub.close()

# ── то же самое у прежнего пути (MJPEG): раздатчик другой, правило одно ──
_M_opened = []
_M_allow = {"ok": False}
_mhub = CameraHub(open_source=lambda key: _RSrc(key), log=None,
                  can_start=lambda key: _M_allow["ok"])
check("R6. прежний путь тоже спрашивает право перед подъёмом источника",
      "self._can_start" in io.open(os.path.join(ROOT, "app", "camera_hub.py"),
                                   encoding="utf-8").read())
check("R7. прежний путь тоже умеет гасить владельца по ключу",
      hasattr(_mhub, "stop_key"))

# ── контракт в сервере: право берётся ДО подписки, ключ у обоих путей одинаковый ──
_SRV_ARB = SRV[SRV.find("def _camera_claim_stream"):SRV.find("def _bambu_hub_fmp4")]
check("R8. распорядитель права есть и гасит чужой путь через stop_key",
      "stop_key(key)" in _SRV_ARB and "_camera_claim[key] = kind" in _SRV_ARB)
check("R9. оба пути берут право ПЕРЕД подпиской",
      SRV.count('_camera_claim_stream("fmp4"') == 1
      and SRV.count('_camera_claim_stream("mjpeg"') == 1
      and SRV.find('_camera_claim_stream("fmp4"') < SRV.find("_camera_fmp4_hub.subscribe("))
check("R10. ключ у обоих путей один и тот же — адрес и код принтера",
      SRV.count('"%s|%s" % (ip, code)') >= 3)
check("R11. оба раздатчика получают право при создании",
      'can_start=lambda key: _camera_can_start("fmp4", key)' in SRV
      and 'can_start=lambda key: _camera_can_start("mjpeg", key)' in SRV)

# ══════════════════════════════════════════════════════════════════════════════════════
section("F. Метка оснастки не попала в продукт")
leaks = []
for base in ("server.py", "app", "web", "modules", "3diwell-setup.iss"):
    pth = os.path.join(ROOT, base)
    files = [pth] if os.path.isfile(pth) else []
    if os.path.isdir(pth):
        for r, _d, fs in os.walk(pth):
            for fn in fs:
                if fn.endswith((".py", ".js", ".html", ".css", ".json", ".iss")):
                    files.append(os.path.join(r, fn))
    for fp in files:
        try:
            if SENTINEL.encode() in io.open(fp, "rb").read():
                leaks.append(os.path.relpath(fp, ROOT))
        except Exception:
            pass
check("F1. метка оснастки только в этом наборе: %s" % (leaks or "нигде"), not leaks)

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
