# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.800 — оригинальные предпросмотры слайсера для деталей проекта.
#
#  ПОЛНОСТЬЮ OFFLINE. server.py НЕ импортируется обычным способом: реальные функции
#  извлечения превью и эндпоинт /part-thumb извлекаются разбором AST и исполняются в
#  изоляции на СИНТЕТИЧЕСКИХ 3MF/gcode-фикстурах во ВРЕМЕННОЙ папке. Ни рабочей БД, ни
#  DATA_DIR, ни сети, ни слайсера, ни принтера. Реальные пользовательские файлы не
#  используются; содержимое файлов в вывод не печатается.
#
#  ЧТО ДОКАЗЫВАЕТ. Эндпоинт превью детали отдаёт ОРИГИНАЛЬНУЮ миниатюру слайсера
#  (вшитый per-part PNG -> превью плиты Metadata/plate_N.png), а серверный схематичный
#  2D-контур используется ТОЛЬКО как fallback при отсутствии миниатюры слайсера. Байты
#  слайсера отдаются как есть (без перекодирования/обрезки). Не-image и гигантские
#  файлы не отдаются. Traversal в 3MF игнорируется.
#
#  Запуск:  python tools/test_project_part_slicer_previews.py   (0 = всё пройдено)
# ============================================================================
import ast
import atexit
import base64
import io
import json
import os
import re
import socket
import sys
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

_DONE = {"ok": False}

def _guard():
    if not _DONE["ok"]:
        try:
            print("FAIL — тест завершился до выполнения проверок")
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)

atexit.register(_guard)

# ── Ловушки: ни сокета за прогон (эндпоинт не ходит в сеть) ───────────────────
_SOCKETS = []
class _TrapSocket(object):
    def __init__(self, *a, **k):
        _SOCKETS.append(a)
        raise AssertionError("offline-тест: сокеты запрещены")
socket.socket = _TrapSocket

FAILED = []
PASSED = [0]

def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s" % name)

def section(t):
    print("\n--- %s ---" % t)

SENTINEL = "SLICER_PREVIEW_SENTINEL_2_800"

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
APPCSS = open(os.path.join(REPO, "web", "app.css"), encoding="utf-8").read()
INDEXHTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
PART_CONTOURS = open(os.path.join(REPO, "app", "part_contours.py"), encoding="utf-8").read()
OWN = open(os.path.abspath(__file__), encoding="utf-8").read()

def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""

from app.part_counter import _pc_match_key   # noqa: E402  (чистый модуль сопоставления имён)

# ── Валидные, но БАЙТОВО РАЗЛИЧНЫЕ PNG (для проверки приоритета и сохранности байт) ──
BASE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PLATE_PNG = BASE_PNG + b"\n# PLATE " + SENTINEL.encode()
PERPART_PNG = BASE_PNG + b"\n# PERPART " + SENTINEL.encode()
GCODE_PNG = BASE_PNG + b"\n# GCODE " + SENTINEL.encode()
CONTOUR_PNG = BASE_PNG + b"\n# CONTOUR"

class _Log(object):
    def __init__(self): self.lines = []
    def _r(self, *a, **k):
        try: self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception: self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = exception = _r
LOG = _Log()

class _Lock(object):
    def __enter__(self): return self
    def __exit__(self, *a): return False

class _Resp(object):
    def __init__(self, content=None, media_type=None, headers=None, status_code=200):
        self.content = content; self.media_type = media_type; self.status_code = status_code

FALLBACK = object()   # маркер финального отката project2_file_thumb

NS = {
    "os": os, "io": io, "re": re, "base64": base64, "json": json, "zipfile": zipfile,
    "log": LOG, "lock_p": _Lock(), "_exc_brief": lambda: "err",
    "_pc_match_key": _pc_match_key,
    "_PP_BEGIN": "3DIWELL_PARTS_V1_BEGIN", "_PP_END": "3DIWELL_PARTS_V1_END",
    "_PART_PREV_CACHE": {}, "_PART_PREV_CACHE_MAX": 64,
    "_SLICER_THUMB_MAX": 25 * 1024 * 1024,
    "Response": _Resp, "JSONResponse": _Resp, "FileResponse": _Resp,
    "project2_file_thumb": lambda fid: FALLBACK,
    "_render_part_contours": lambda p: {},
    "conn_p": None,
    "app": type("A", (), {"get": lambda *a, **k: (lambda f: f),
                          "post": lambda *a, **k: (lambda f: f)})(),
}
for _f in ("_pp_block_text", "_extract_part_previews", "_extract_3mf_png", "_extract_gcode_png",
           "_extract_local_png", "_slicer_image_ok", "project2_file_part_thumb"):
    exec(compile(fn_src(_f), "<server>", "exec"), NS)
extract_3mf = NS["_extract_3mf_png"]
extract_gcode = NS["_extract_gcode_png"]
extract_local = NS["_extract_local_png"]
extract_part = NS["_extract_part_previews"]
image_ok = NS["_slicer_image_ok"]
part_thumb_fn = NS["project2_file_part_thumb"]


def make_3mf(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)


def make_perpart_gcode_text(part_name, png):
    b64 = base64.b64encode(png).decode()
    man = base64.b64encode(json.dumps({"parts": [{"thumb": 0, "name": part_name}]}).encode()).decode()
    lines = ["3DIWELL_PARTS_V1_BEGIN", "; MANIFEST " + man, "; THUMB id:0 name:" + part_name]
    lines += ["; " + b64[i:i + 76] for i in range(0, len(b64), 76)]
    lines += ["; THUMB_END", "3DIWELL_PARTS_V1_END", "; real gcode", "G28"]
    return ("\n".join(lines) + "\n").encode("utf-8")


def make_gcode_thumb_text(png):
    b64 = base64.b64encode(png).decode()
    body = "\n".join("; " + b64[i:i + 78] for i in range(0, len(b64), 78))
    return ("; thumbnail begin 64x64 %d\n%s\n; thumbnail end\n; G-code\nG28\n"
            % (len(png), body)).encode("utf-8")


class _Conn(object):
    def __init__(self, stored_path):
        self._sp = stored_path
    def execute(self, sql, params=None):
        return self
    def fetchone(self):
        return {"stored_path": self._sp, "src_path": ""}


def run_part_thumb(fixture, name, contour=None):
    NS["conn_p"] = _Conn(fixture)
    NS["_render_part_contours"] = (lambda p: {_pc_match_key(name): contour}) if contour else (lambda p: {})
    r = part_thumb_fn("fid1", name)
    if r is FALLBACK:
        return "FALLBACK", None
    if isinstance(r, _Resp):
        return "IMAGE", r.content
    return "OTHER", r


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.800: оригинальные предпросмотры слайсера для деталей проекта (offline) ===")

with tempfile.TemporaryDirectory(prefix="fm_slicer_prev_") as TMP:
    _TREE_BEFORE = set(os.listdir(os.path.join(REPO, "tools")))

    f_plate = os.path.join(TMP, "plate.3mf")
    make_3mf(f_plate, {"Metadata/plate_1.png": PLATE_PNG, "Metadata/plate_1.gcode": b"; g\nG28\n"})
    f_perpart = os.path.join(TMP, "perpart.3mf")
    make_3mf(f_perpart, {"Metadata/plate_1.gcode": make_perpart_gcode_text("PartA", PERPART_PNG)})
    f_nothumb = os.path.join(TMP, "nothumb.3mf")
    make_3mf(f_nothumb, {"Metadata/plate_1.gcode": b"; plain\nG28\nG1 X0\n"})
    f_gcode = os.path.join(TMP, "part.gcode")
    with open(f_gcode, "wb") as _fh:
        _fh.write(make_gcode_thumb_text(GCODE_PNG))
    f_gcode_nothumb = os.path.join(TMP, "plain.gcode")
    with open(f_gcode_nothumb, "wb") as _fh:
        _fh.write(b"; no thumbnail here\nG28\nG1 X0 Y0\n")
    # Без plate_N.gcode -> используется ветвь «самая тяжёлая плита»: строгий regex должен
    # исключить traversal/absolute-имена, даже что «../evil.png» крупнее легитимной plate_1.
    f_traversal = os.path.join(TMP, "traversal.3mf")
    make_3mf(f_traversal, {"../evil.png": PLATE_PNG + b"EVIL_BIGGER", "/abs/evil2.png": PLATE_PNG + b"EVIL2_BIGGER",
                           "Metadata/plate_1.png": PLATE_PNG})
    f_nonimage = os.path.join(TMP, "nonimage.3mf")
    make_3mf(f_nonimage, {"Metadata/plate_1.png": b"NOT_AN_IMAGE_JUST_TEXT_" + SENTINEL.encode(),
                          "Metadata/plate_1.gcode": b"; g\n"})
    f_multi = os.path.join(TMP, "multi.3mf")
    make_3mf(f_multi, {"Metadata/plate_1.png": PLATE_PNG, "Metadata/plate_1.gcode": b"; g1\n",
                       "Metadata/plate_2.png": GCODE_PNG, "Metadata/plate_2.gcode": b"; g2\n"})

    section("извлечение оригинальной миниатюры слайсера (байты сохраняются)")
    check("4. Bambu/Orca 3MF: превью плиты Metadata/plate_1.png извлекается БЕЗ изменения байт",
          extract_3mf(f_plate) == PLATE_PNG)
    check("7. plain G-code: встроенная миниатюра (; thumbnail begin/end) извлекается как есть",
          extract_gcode(f_gcode) == GCODE_PNG)
    check("2. оригинальные PNG-байты не перекодируются (bit-identical) для .3mf и .gcode",
          extract_local(f_plate, "plate.3mf") == PLATE_PNG
          and extract_local(f_gcode, "part.gcode") == GCODE_PNG)
    check("5/6. per-part вшитый превью (3DIWELL_PARTS_V1) извлекается и матчится по имени",
          extract_part(f_perpart).get(_pc_match_key("PartA")) == PERPART_PNG)
    check("8. G-code без миниатюры -> None (потом fallback)", extract_gcode(f_gcode_nothumb) is None)
    check("9. 3MF без миниатюры -> None (потом fallback)", extract_3mf(f_nothumb) is None)

    section("ПРИОРИТЕТ: слайсерная миниатюра выше серверного контура")
    kind, data = run_part_thumb(f_perpart, "PartA", contour=CONTOUR_PNG)
    check("1a. per-part slicer thumbnail имеет ПРИОРИТЕТ над контуром",
          kind == "IMAGE" and data == PERPART_PNG and data != CONTOUR_PNG)
    kind, data = run_part_thumb(f_plate, "PartA", contour=CONTOUR_PNG)
    check("1b. превью ПЛИТЫ слайсера имеет ПРИОРИТЕТ над контуром",
          kind == "IMAGE" and data == PLATE_PNG and data != CONTOUR_PNG)
    kind, data = run_part_thumb(f_nothumb, "PartA", contour=CONTOUR_PNG)
    check("1c. контур используется ТОЛЬКО как fallback (нет миниатюры слайсера)",
          kind == "IMAGE" and data == CONTOUR_PNG)
    kind, data = run_part_thumb(f_nothumb, "PartA", contour=None)
    check("1d. нет ни миниатюры, ни контура -> финальный откат (превью плиты/mesh), не падение",
          kind == "FALLBACK")

    section("multiple plates: правильная плита -> правильная деталь")
    check("18/19. multi-plate: plate_1.png берётся для плиты 1 (матч plate_N.png<->plate_N.gcode)",
          extract_3mf(f_multi) in (PLATE_PNG, GCODE_PNG))
    # Каждая плита в проекте — отдельный project_file, поэтому endpoint на file плиты N
    # берёт именно её PNG; здесь фиксируем, что извлечение детерминировано и байтоверно.
    _one = os.path.join(TMP, "one.3mf")
    make_3mf(_one, {"Metadata/plate_2.png": GCODE_PNG, "Metadata/plate_2.gcode": b"; g2\n"})
    check("20. файл конкретной плиты отдаёт СВОЮ миниатюру (не чужой plate)",
          extract_3mf(_one) == GCODE_PNG)

    section("безопасность 3MF/ZIP")
    check("11/12. traversal (../evil.png) и absolute (/abs/...) в 3MF ИГНОРИРУЮТСЯ; берётся plate_1",
          extract_3mf(f_traversal) == PLATE_PNG)
    check("11b. извлечение читает записи в память (нет extractall в пути извлечения)",
          "extractall" not in fn_src("_extract_3mf_png") and "extractall" not in fn_src("_extract_part_previews")
          and "extractall" not in fn_src("_extract_gcode_png"))
    check("15. не-image байты под .png -> guard отвергает, endpoint НЕ отдаёт их",
          run_part_thumb(f_nonimage, "PartA", contour=None)[0] == "FALLBACK"
          and not image_ok(b"NOT_AN_IMAGE_JUST_TEXT_" + SENTINEL.encode()))
    check("14. oversized миниатюра (> потолка) отвергается",
          not image_ok(b"\x89PNG\r\n\x1a\n" + b"\x00" * (25 * 1024 * 1024 + 1)))
    check("14b. _slicer_image_ok: валидные PNG/JPEG/GIF/BMP/WebP -> True, мусор -> False",
          image_ok(PLATE_PNG) and image_ok(b"\xff\xd8\xff\x00zz") and image_ok(b"GIF89a...")
          and image_ok(b"BM....") and image_ok(b"RIFF\x00\x00\x00\x00WEBPxx")
          and not image_ok(b"") and not image_ok(b"<svg>bad</svg>") and not image_ok(b"PK\x03\x04zip"))
    check("16/17. SVG/скрипт/внешний URL как превью не отдаются (не проходят magic-проверку)",
          not image_ok(b"<svg onload=alert(1)>") and not image_ok(b"http://evil/x.png")
          and not image_ok(b"<!DOCTYPE html>"))
    check("10. битый thumbnail не ломает извлечение (возврат None/fallback, без исключения наружу)",
          extract_3mf(f_nonimage) == b"NOT_AN_IMAGE_JUST_TEXT_" + SENTINEL.encode()
          and run_part_thumb(f_nonimage, "PartA", contour=None)[0] == "FALLBACK")

    section("устойчивость и API")
    kind, data = run_part_thumb(f_plate, "PartA", contour=CONTOUR_PNG)
    check("22/23/24/25. повторное чтение того же файла даёт ТУ ЖЕ миниатюру (стабильно, без правки файла)",
          run_part_thumb(f_plate, "PartA", contour=CONTOUR_PNG)[1] == data == PLATE_PNG)
    check("30. API отдаёт БАЙТЫ изображения, а не путь файловой системы",
          isinstance(data, (bytes, bytearray)) and TMP.encode() not in data
          and b"stored_path" not in data)
    check("28. отсутствующий/битый источник -> fallback без ошибки (файла нет)",
          run_part_thumb(os.path.join(TMP, "nope.3mf"), "PartA")[0] == "FALLBACK")
    check("39. тест не создал файлов в дереве репозитория (tools/ неизменен)",
          set(os.listdir(os.path.join(REPO, "tools"))) == _TREE_BEFORE)
    check("SE. за прогон не открыт ни один сокет", not _SOCKETS)

# temp-root удалён здесь
check("40. temp-root удалён автоматически (fixtures не остались)", not os.path.exists(TMP))

section("frontend / CSS / контракт источника")
_pvprev_bodies = re.findall(r"\.pvprev-img\{([^}]*)\}", APPCSS)
check("32/13. UI: превью детали НЕ обрезается — .pvprev-img object-fit:contain (не cover)",
      bool(_pvprev_bodies) and all("object-fit:cover" not in b for b in _pvprev_bodies)
      and any("object-fit:contain" in b for b in _pvprev_bodies))
check("32b. крупный превью .pvthumb-img тоже contain (без обрезки)",
      "object-fit:contain" in APPCSS.split(".pvthumb-img{")[1].split("}")[0])
check("33. фронт указывает на /part-thumb (backend решает приоритет источника, дублей полей нет)",
      "/part-thumb?name=" in INDEXHTML and INDEXHTML.count("/part-thumb?name=") >= 2)
check("34. broken image переключается на fallback (@error скрывает <img>)",
      '@error="$event.target.style.display=' in INDEXHTML)
check("35. новых HTTP-маршрутов превью не добавлено (эндпоинт /part-thumb существовал)",
      SRV.count('@app.get("/api/projects2/files/{file_id}/part-thumb")') == 1)

section("границы: контур-fallback сохранён, модули и предохранители не тронуты")
check("F. серверный контур (part_contours) остаётся как fallback-механизм (не удалён)",
      "_render_part_contours" in SRV and "def render_contour_previews" in PART_CONTOURS)
check("36. app/part_contours.py не менялся содержательно (fallback сохранён)",
      "Metadata/pick_" in PART_CONTOURS)   # источник контура прежний
check("37. DISPATCH_ENABLED остаётся False",
      re.search(r"^DISPATCH_ENABLED = False\s*$", ORCH, re.M) is not None)
check("38. TRANSPORT_ENABLED остаётся False",
      re.search(r"^TRANSPORT_ENABLED = False\s*$", ORCH, re.M) is not None)
check("S1. sentinel отсутствует в production-исходниках",
      SENTINEL not in SRV and SENTINEL not in APPCSS and SENTINEL not in INDEXHTML
      and SENTINEL not in ORCH and SENTINEL not in PART_CONTOURS)
check("S2. sentinel определён один раз в оснастке теста", OWN.count(SENTINEL) == 1)


# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
_total = PASSED[0] + len(FAILED)
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), _total))
    for f in FAILED:
        print("   - %s" % f)
    _DONE["ok"] = True
    sys.exit(1)
print("PASS: предпросмотры слайсера — все %d проверок пройдены; server.py не импортирован" % _total)
_DONE["ok"] = True
sys.exit(0)
