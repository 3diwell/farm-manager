# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.822 — миниатюры в РЕДАКТОРЕ проекта (детали и файлы).
#
#  ПОЛНОСТЬЮ OFFLINE. Ни рабочей БД, ни DATA_DIR, ни сети, ни слайсера, ни принтера,
#  ни production-рантайма. Реальные функции превью и эндпоинты извлекаются разбором AST и
#  исполняются на СИНТЕТИЧЕСКИХ 3MF/gcode во временной папке; frontend-резолвер извлекается
#  из web/app.js и исполняется в изолированном Node-харнессе на фейковых part/file; раскладка
#  меряется в реальном движке (headless Edge) на синтетическом стенде с настоящим app.css.
#  Пользовательские файлы не используются; содержимое файлов в вывод не печатается.
#
#  ЧТО ДОКАЗЫВАЕТ. (1) В режиме правки каждая строка детали и каждая строка файла получает
#  ровно одну миниатюру, а имя и управляющие кнопки сохранены. (2) Единый резолвер строит
#  ТОЛЬКО same-origin URL по file_id (per-part -> плита -> контур -> mesh для детали; PNG
#  плиты -> mesh для файла); локальный путь/DATA_DIR/src_path во фронт не уходят; ?v= из
#  content_hash даёт cache-bust при переслайсинге без случайного timestamp; нет file_id ->
#  безопасная fallback-иконка. (3) Раскладка не ломается на zoom 100/125/150 RU/EN: миниатюра
#  ограничена, не перекрывает имя/кнопки, страница не получает горизонтальный scroll.
#  (4) Основной список, фикс Bambu 2.820, диагностика 2.821 и схема БД не тронуты.
#
#  Запуск:  python tools/test_project_editor_thumbnails.py   (0 = всё пройдено)
# ============================================================================
import ast
import atexit
import base64
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _edge_dom   # Alpha 2.834: DOM через CDP + проверка живости движка

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

# ── Ловушка: ни одного реального сокета за прогон (эндпоинты/резолвер в сеть не ходят) ──
_SOCKETS = []
_real_socket = socket.socket


class _TrapSocket(object):
    def __init__(self, *a, **k):
        _SOCKETS.append(a)
        raise AssertionError("offline-тест: сокеты запрещены")


socket.socket = _TrapSocket

FAILED = []
PASSED = [0]
SKIPPED = []


def check(name, ok, detail=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, (" :: " + detail) if detail else ""))


def skip(name, why):
    SKIPPED.append(name)
    print("SKIP — %s (%s)" % (name, why))


def section(t):
    print("\n--- %s ---" % t)


SENTINEL = "PROJECT_EDITOR_THUMBNAILS_SENTINEL_2_822"

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
APPJS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
INDEXHTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
APPCSS = open(os.path.join(REPO, "web", "app.css"), encoding="utf-8").read()
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
HEALTH = open(os.path.join(REPO, "app", "printer_health_policy.py"), encoding="utf-8").read()
OWN = open(os.path.abspath(__file__), encoding="utf-8").read()


def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""


EDGE = next((p for p in [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"] if os.path.isfile(p)), None)

# Alpha 2.835: наличие бинарника не значит работоспособность, НО неработоспособность движка
# больше НЕ повод пропускать браузерные проверки — это КРАСНЫЙ тест с точной причиной. Прежний
# SKIP был слепой зоной: именно он однажды спрятал реальный дефект интерфейса.
_ENGINE_WHY = ""
if not EDGE:
    _ENGINE_WHY = "движок рендера (Edge/Chrome) не найден"
elif not _edge_dom.engine_usable(EDGE):
    _ENGINE_WHY = "движок найден (%s), но не отдаёт документ по CDP" % EDGE
    EDGE = None


def _css_rule(selector):
    """Тело одного CSS-правила `selector{...}` из app.css (или '')."""
    key = selector + "{"
    i = APPCSS.find(key)
    if i < 0:
        return ""
    return APPCSS[i + len(key):APPCSS.find("}", i)]


print("=== Alpha 2.822: миниатюры в редакторе проекта (offline) ===")

# ════════════════════════════════════════════════════════════════════════════
section("1. СТРУКТУРА РЕДАКТОРА (разметка режима правки)")

# Область режима правки: от первого v-show edit до конца блока файлов.
_edit_i = INDEXHTML.find("project2Mode[pr.id] === 'edit'")
EDIT_REGION = INDEXHTML[_edit_i:_edit_i + 6000] if _edit_i >= 0 else ""
# Блок-детали (таблица) и блок-файлы различаем по якорям edit-part-name / edit-del-file.
check("1. редактор содержит список деталей (таблица правки с data-help=edit-part-name)",
      'data-help="edit-part-name"' in INDEXHTML and "project2Mode[pr.id] === 'edit'" in INDEXHTML)
check("2. каждая строка детали имеет контейнер миниатюры (img.p2ed-thumb со src=p2PartThumb(pp))",
      re.search(r'<img[^>]*:src="p2PartThumb\(pp\)"[^>]*class="p2ed-thumb"', INDEXHTML) is not None)
check("3. список добавленных файлов имеет миниатюру (img.p2ed-thumb со src=p2FileThumb(fn))",
      re.search(r'<img[^>]*:src="p2FileThumb\(fn\)"[^>]*class="p2ed-thumb"', INDEXHTML) is not None)
check("4. миниатюра встречается один раз на строку (по одному сайту вызова резолвера)",
      INDEXHTML.count("p2PartThumb(pp)") == 1 and INDEXHTML.count("p2FileThumb(fn)") == 1
      and INDEXHTML.count('class="p2ed-thumb"') == 2)
check("5. основное имя и управляющие кнопки сохранены (имя детали/файла + удаление)",
      'data-help="edit-part-name"' in INDEXHTML and "deleteProject2Part(pr.id, pp.part_id)" in INDEXHTML
      and "deleteProject2File(pr.id, fn.file_id)" in INDEXHTML and "{{ fn.filename }}" in INDEXHTML)
# Порядок строк не меняется: v-for идёт по исходным коллекциям без добавления сортировки.
check("6. порядок строк деталей/файлов не меняется (v-for по partsview/p2EditOrdered, без новой сортировки)",
      "pp in (project2Parts[pr.id] ? project2Parts[pr.id].parts : [])" in INDEXHTML
      and "(fn, fi) in p2EditOrdered(pr.id)" in INDEXHTML)

# ════════════════════════════════════════════════════════════════════════════
section("2. ЕДИНЫЙ РЕЗОЛВЕР (исполняется в изолированном Node)")

# Извлекаем именно тот исходник, что в app.js: THUMB_FALLBACK + блок pvFirstFid..p2FileThumb.
_mfb = re.search(r'const THUMB_FALLBACK = [^\n]+', APPJS)
FALLBACK_SRC = _mfb.group(0) if _mfb else ""
_i0 = APPJS.find("const pvFirstFid = (pp) =>")
_iF = APPJS.find("const p2FileThumb = (fn) =>", _i0)
_iEnd = APPJS.find("\n    };", _iF)
RESOLVER_SRC = APPJS[_i0:_iEnd + len("\n    };")] if (_i0 >= 0 and _iF >= 0 and _iEnd >= 0) else ""

_resolver_extracted = bool(FALLBACK_SRC) and bool(RESOLVER_SRC) and "p2PartThumb" in RESOLVER_SRC
check("R0. резолвер и fallback извлечены из app.js без правки", _resolver_extracted)

RES = {}
if _resolver_extracted:
    DRIVER = r"""
var out = {};
out.partA = p2PartThumb({part_name:'Bracket A', plates:[{file_id:'pfile_abc123def456', content_hash:'deadbeefcafe0011ff'}]});
out.partB = p2PartThumb({part_name:'Gear_B',   plates:[{file_id:'pfile_abc123def456', content_hash:'deadbeefcafe0011ff'}]});
out.partNoFid = p2PartThumb({part_name:'X', plates:[]});
out.partRepl1 = p2PartThumb({part_name:'P', plates:[{file_id:'pfile_same', content_hash:'aaaaaaaaaaaa'}]});
out.partRepl2 = p2PartThumb({part_name:'P', plates:[{file_id:'pfile_same', content_hash:'bbbbbbbbbbbb'}]});
out.partMal = p2PartThumb({part_name:'../../etc/passwd?javascript:alert(1)&z=<x>', plates:[{file_id:'pfile_same'}]});
out.partStable1 = p2PartThumb({part_name:'P', plates:[{file_id:'pfile_same', content_hash:'aaaaaaaaaaaa'}]});
out.partStable2 = p2PartThumb({part_name:'P', plates:[{file_id:'pfile_same', content_hash:'aaaaaaaaaaaa'}]});
out.fileOk = p2FileThumb({file_id:'pfile_def456abc123', content_hash:'0123456789abcdef'});
out.fileNoHash = p2FileThumb({file_id:'pfile_def456abc123'});
out.fileNoFid = p2FileThumb({});
out.fileRepl1 = p2FileThumb({file_id:'pfile_same', content_hash:'1111aaaa'});
out.fileRepl2 = p2FileThumb({file_id:'pfile_same', content_hash:'2222bbbb'});
out.fallback = THUMB_FALLBACK;
out.usesDate = /Date\.now|Math\.random/.test(p2PartThumb.toString()+p2FileThumb.toString());
process.stdout.write('@@RES@@'+JSON.stringify(out)+'@@END@@');
"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_p2thumb_res_") as _td:
        _hp = os.path.join(_td, "h.js")
        io.open(_hp, "w", encoding="utf-8", newline="\n").write(FALLBACK_SRC + "\n" + RESOLVER_SRC + "\n" + DRIVER)
        try:
            _pr = subprocess.run(["node", _hp], capture_output=True, text=True, encoding="utf-8", timeout=30)
            _m = re.search(r"@@RES@@(\{.*\})@@END@@", _pr.stdout or "", re.S)
            if _m:
                RES = json.loads(_m.group(1))
        except Exception as _e:
            RES = {}

check("R1. резолвер исполнился в Node и вернул URL", bool(RES))
if RES:
    check("7. part thumbnail имеет первый приоритет: резолвер указывает на /part-thumb (per-part slicer)",
          RES["partA"].startswith("/api/projects2/files/pfile_abc123def456/part-thumb?name="))
    check("13. разные part_id/имена -> разные thumbnails (name= различается)",
          RES["partA"] != RES["partB"] and "name=Bracket%20A" in RES["partA"] and "name=Gear_B" in RES["partB"])
    check("14. одна plate/file thumbnail НЕ выдаётся всем деталям (URL зависит от имени детали)",
          "Bracket%20A" in RES["partA"] and "Bracket%20A" not in RES["partB"])
    check("15. удалённая/безфайловая деталь не показывает старое preview (нет file_id -> fallback-иконка)",
          RES["partNoFid"] == RES["fallback"] and RES["fallback"].startswith("data:image/svg+xml"))
    check("16/17. добавленный файл: резолвер указывает на /thumb (оригинальное preview слайсера)",
          RES["fileOk"].startswith("/api/projects2/files/pfile_def456abc123/thumb?v="))
    check("20. generic-иконка только при отсутствии preview (нет file_id -> data-URI иконка)",
          RES["fileNoFid"] == RES["fallback"])
    check("21/36. новый content_hash обновляет thumbnail (?v= меняется при переслайсинге)",
          RES["partRepl1"] != RES["partRepl2"] and RES["fileRepl1"] != RES["fileRepl2"])
    check("22. старое preview не остаётся после замены (v-токен детали/файла сменился)",
          "v=aaaaaaaaaaaa" in RES["partRepl1"] and "v=bbbbbbbbbbbb" in RES["partRepl2"])
    check("35. cache key стабилен: одинаковый вход -> идентичный URL",
          RES["partStable1"] == RES["partStable2"])
    check("37. нет случайного timestamp на каждый render (ни Date.now, ни Math.random в резолвере)",
          RES["usesDate"] is False)
    # SECURITY
    _pathmal = RES["partMal"].split("?")[0]
    check("23. URL не строится из абсолютного пути клиента (только относительный /api/ путь)",
          RES["partA"].startswith("/api/") and RES["fileOk"].startswith("/api/") and ":\\" not in RES["partMal"])
    check("26. file:// URL запрещён (резолвер отдаёт same-origin путь/иконку)",
          "file:" not in RES["partA"] and "file:" not in RES["fileOk"] and "file:" not in RES["partMal"])
    check("27. javascript: запрещён (двоеточие схемы кодируется -> не исполняемая схема)",
          "javascript:" not in RES["partMal"] and RES["partMal"].startswith("/api/projects2/files/"))
    check("28. внешний произвольный origin запрещён (нет http(s)://, нет //host)",
          "://" not in RES["partA"] and "://" not in RES["fileOk"] and "://" not in RES["partMal"])
    check("29. same-origin preview разрешён (путь начинается с /api/projects2/files/)",
          RES["partA"].startswith("/api/projects2/files/") and RES["fileOk"].startswith("/api/projects2/files/"))
    check("SEC-path. path-часть malicious-имени чиста (traversal/<>/? ушли в кодированный query)",
          _pathmal == "/api/projects2/files/pfile_same/part-thumb" and "<" not in RES["partMal"] and ">" not in RES["partMal"])
    check("18/19-file. file resolver даёт корректный ?v= (well-formed, для повторной попытки onThumbErr)",
          RES["fileNoHash"].endswith("/thumb?v=pfile_def456abc123") and "?v=" in RES["fileOk"])
else:
    for _n in ("7", "13", "14", "15", "16/17", "20", "21/36", "22", "35", "37", "23", "26", "27", "28", "29",
               "SEC-path", "18/19-file"):
        check("Node-резолвер: проверка %s не выполнена (нет ответа Node)" % _n, False, "node harness no result")

# ════════════════════════════════════════════════════════════════════════════
section("3. ЦЕПОЧКА ПРИОРИТЕТА BACKEND (AST-исполнение на синтетических 3MF/gcode)")

# Реюз контракта Alpha 2.800: те же реальные функции извлечения превью и эндпоинты.
BASE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PLATE_PNG = BASE_PNG + b"\n# PLATE"
PERPART_PNG = BASE_PNG + b"\n# PERPART"
CONTOUR_PNG = BASE_PNG + b"\n# CONTOUR"
MESH_PNG = BASE_PNG + b"\n# MESH"


class _Log(object):
    def _r(self, *a, **k):
        pass
    info = warning = error = debug = exception = _r


class _Lock(object):
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Resp(object):
    def __init__(self, content=None, media_type=None, headers=None, status_code=200):
        self.content = content
        self.media_type = media_type
        self.headers = headers or {}
        self.status_code = status_code


from app.part_counter import _pc_match_key  # noqa: E402

NS = {
    "os": os, "io": io, "re": re, "base64": base64, "json": json, "zipfile": zipfile, "hashlib": __import__("hashlib"),
    "log": _Log(), "lock_p": _Lock(), "_exc_brief": lambda: "err", "_pc_match_key": _pc_match_key,
    "_PP_BEGIN": "3DIWELL_PARTS_V1_BEGIN", "_PP_END": "3DIWELL_PARTS_V1_END",
    "_PART_PREV_CACHE": {}, "_PART_PREV_CACHE_MAX": 64, "_SLICER_THUMB_MAX": 25 * 1024 * 1024,
    "_RENDER_VER": "t", "THUMB_CACHE_DIR": tempfile.mkdtemp(prefix="fm_p2thumb_cache_"),
    "Response": _Resp, "JSONResponse": _Resp, "FileResponse": _Resp,
    "_render_part_contours": lambda p: {}, "_render_mesh_png": lambda p, n: MESH_PNG,
    "_extract_local_png": None, "conn_p": None,
    "app": type("A", (), {"get": lambda *a, **k: (lambda f: f), "post": lambda *a, **k: (lambda f: f)})(),
}
_chain_ok = True
try:
    for _f in ("_pp_block_text", "_extract_part_previews", "_extract_3mf_png", "_extract_gcode_png",
               "_extract_local_png", "_slicer_image_ok", "project2_file_thumb", "project2_file_part_thumb"):
        exec(compile(fn_src(_f), "<server>", "exec"), NS)
except Exception as _e:
    _chain_ok = False

if _chain_ok:
    extract_part = NS["_extract_part_previews"]
    part_thumb_fn = NS["project2_file_part_thumb"]
    file_thumb_fn = NS["project2_file_thumb"]

    def make_3mf(path, entries):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in entries.items():
                z.writestr(name, data)

    def perpart_gcode(part_name, png):
        b64 = base64.b64encode(png).decode()
        man = base64.b64encode(json.dumps({"parts": [{"thumb": 0, "name": part_name}]}).encode()).decode()
        lines = ["3DIWELL_PARTS_V1_BEGIN", "; MANIFEST " + man, "; THUMB id:0 name:" + part_name]
        lines += ["; " + b64[i:i + 76] for i in range(0, len(b64), 76)]
        lines += ["; THUMB_END", "3DIWELL_PARTS_V1_END", "G28"]
        return ("\n".join(lines) + "\n").encode("utf-8")

    class _Conn(object):
        def __init__(self, sp): self._sp = sp
        def execute(self, sql, params=None): return self
        def fetchone(self): return {"stored_path": self._sp, "src_path": ""}

    def run_part(fixture, name, contour=None):
        NS["conn_p"] = _Conn(fixture)
        NS["_render_part_contours"] = (lambda p: {_pc_match_key(name): contour}) if contour else (lambda p: {})
        r = part_thumb_fn("fid1", name)
        return r.content if isinstance(r, _Resp) and isinstance(r.content, (bytes, bytearray)) else None

    def run_file(fixture):
        NS["conn_p"] = _Conn(fixture)
        r = file_thumb_fn("fid1")
        return r.content if isinstance(r, _Resp) and isinstance(r.content, (bytes, bytearray)) else None

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_p2thumb_fx_") as TMP:
        _TREE0 = set(os.listdir(os.path.join(REPO, "tools")))
        f_perpart = os.path.join(TMP, "perpart.3mf")
        make_3mf(f_perpart, {"Metadata/plate_1.png": PLATE_PNG,
                             "Metadata/plate_1.gcode": perpart_gcode("PartA", PERPART_PNG)})
        f_plate = os.path.join(TMP, "plate.3mf")
        make_3mf(f_plate, {"Metadata/plate_1.png": PLATE_PNG, "Metadata/plate_1.gcode": b"; g\nG28\n"})
        f_nothumb = os.path.join(TMP, "nothumb.3mf")
        make_3mf(f_nothumb, {"Metadata/plate_1.gcode": b"; plain\nG28\n"})
        f_stl = os.path.join(TMP, "model.stl")
        open(f_stl, "wb").write(b"solid x\nendsolid x\n")

        check("8/7. per-part slicer thumbnail имеет ПРИОРИТЕТ (деталь = свой per-part PNG, не плита)",
              run_part(f_perpart, "PartA", contour=CONTOUR_PNG) == PERPART_PNG)
        check("9. plate thumbnail используется ВТОРЫМ (нет per-part -> плита, выше контура)",
              run_part(f_plate, "PartA", contour=CONTOUR_PNG) == PLATE_PNG)
        check("10/11. contour используется ПОСЛЕ slicer preview (только когда нет ни per-part, ни плиты)",
              run_part(f_nothumb, "PartA", contour=CONTOUR_PNG) == CONTOUR_PNG)
        check("11b/12. mesh/generic — последний откат (нет slicer/контура -> mesh-рендер, без исключения)",
              run_part(f_nothumb, "PartA", contour=None) == MESH_PNG)
        check("14b. другая деталь того же файла берёт СВОЙ per-part (по имени), не чужой",
              run_part(f_perpart, "PartB", contour=None) in (PLATE_PNG,)  # у PartB per-part нет -> плита
              and run_part(f_perpart, "PartA", contour=None) == PERPART_PNG)
        check("17/18. file /thumb: встроенный PNG плиты имеет приоритет над mesh",
              run_file(f_plate) == PLATE_PNG)
        check("19. file /thumb: mesh-рендер как fallback для модели без встроенного превью",
              run_file(f_stl) == MESH_PNG)
        check("PERF-32/33. эндпоинт превью не запускает анализ на render: не распаковывает 3MF при mesh-модели",
              b"extractall" not in fn_src("_extract_3mf_png").encode()
              and "extractall" not in fn_src("project2_file_thumb"))
        check("PERF-34. готовые thumbnails кешируются (Cache-Control max-age на ответе превью)",
              "max-age" in fn_src("project2_file_thumb") and "max-age" in fn_src("project2_file_part_thumb"))
        check("30/31. битое/отсутствующее превью -> нет изображения (frontend уходит в fallback), без исключения",
              run_part(os.path.join(TMP, "nope.3mf"), "PartA") is None and run_file(os.path.join(TMP, "nope.stl")) is None)
        check("SE-tree. тест не создал файлов в дереве tools/", set(os.listdir(os.path.join(REPO, "tools"))) == _TREE0)
else:
    for _n in ("8/7", "9", "10/11", "11b/12", "14b", "17/18", "19", "PERF-32/33", "PERF-34", "30/31"):
        check("backend-цепочка: проверка %s (AST-исполнение не удалось)" % _n, False, "ast exec failed")

# ════════════════════════════════════════════════════════════════════════════
section("4. РАСКЛАДКА (реальный движок Edge + свойства CSS)")

_p2 = _css_rule(".p2ed-thumb")
check("40. размер миниатюры ограничен (фикс. width/height у .p2ed-thumb)",
      bool(re.search(r"width:\s*\d+px", _p2)) and bool(re.search(r"height:\s*\d+px", _p2)))
check("41. используется object-fit:contain (без cover, изображение не обрезается)",
      "object-fit:contain" in _p2 and "object-fit:cover" not in _p2)
check("42. соотношение сторон сохраняется (object-fit:contain + фикс. бокс flex:0 0 auto -> не тянется)",
      "object-fit:contain" in _p2 and "flex:0 0 auto" in _p2)
check("43/44. длинное имя не перекрывает миниатюру/кнопки (имя в min-w-0+truncate, кнопки shrink-0)",
      "min-w-0" in INDEXHTML and "truncate" in INDEXHTML
      and 'class="shrink-0 h-7 w-7' in INDEXHTML)


def layout_page(lang, bz):
    css_href = "file:///" + os.path.join(REPO, "web", "app.css").replace("\\", "/")
    long_part = ("Кронштейн крепления левый усиленный вариант 3 ревизия B" if lang == "ru"
                 else "Left reinforced mounting bracket assembly variant 3 revision B") * 2
    long_file = ("деталь_очень_длинное_имя_файла_ревизия_финальная_v12" if lang == "ru"
                 else "very_long_project_file_name_final_revision_v12_export") + ".gcode.3mf"
    img = ("data:image/png;base64," + base64.b64encode(BASE_PNG).decode())
    U = ("<style>.flex{display:flex}.items-center{align-items:center}.gap-2{gap:.5rem}.gap-1{gap:.25rem}"
         ".min-w-0{min-width:0}.truncate{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
         ".shrink-0{flex-shrink:0}.justify-between{justify-content:space-between}.h-7{height:1.75rem}"
         ".w-7{width:1.75rem}.px-3{padding-left:.75rem;padding-right:.75rem}.py-1\\.5{padding-top:.375rem;"
         "padding-bottom:.375rem}.py-2{padding-top:.5rem;padding-bottom:.5rem}.text-sm{font-size:.875rem}"
         ".font-semibold{font-weight:600}.font-mono{font-family:monospace}.rounded-md{border-radius:.375rem}"
         ".pvdot{width:8px;height:8px;border-radius:50%;background:#888}.p2dot{width:8px;height:8px;border-radius:50%;"
         "background:#888}table{width:100%;border-collapse:collapse}</style>")
    part_row = (
        "<table><tbody><tr>"
        "<td class='px-3 py-1.5'><div class='flex items-center gap-2 min-w-0'>"
        "<button class='shrink-0 h-7 w-7 rounded-md' id='pdel'>x</button>"
        "<span class='pvdot shrink-0'></span>"
        "<img class='p2ed-thumb' id='pthumb' src='" + img + "'>"
        "<span class='font-semibold text-sm truncate' id='pname'>" + long_part + "</span>"
        "</div></td>"
        "<td class='px-3 py-1.5'><input style='width:76px' value='9'></td>"
        "</tr></tbody></table>")
    file_row = (
        "<div class='px-3 py-2 flex items-center justify-between gap-2' style='border:1px solid #333'>"
        "<div class='flex items-center gap-2 min-w-0'>"
        "<span class='p2dot p2node-dot p2filedot shrink-0'></span>"
        "<img class='p2ed-thumb' id='fthumb' src='" + img + "'>"
        "<span class='text-sm font-mono truncate' id='fname'>" + long_file + "</span></div>"
        "<div class='flex items-center gap-1 shrink-0'>"
        "<button class='h-7 w-7 rounded-md' id='fdel'>x</button></div></div>")
    body = ("<div id='panel' style='width:520px;max-width:100%;border:1px solid #333;overflow:hidden'>"
            + part_row + file_row + "</div>")
    meas = (
        "<pre id='__res'></pre><script>"
        "function R(id){return document.getElementById(id).getBoundingClientRect();}"
        "function ov(a,b){return a.left<b.right-1&&b.left<a.right-1&&a.top<b.bottom-1&&b.top<a.bottom-1;}"
        "function measure(){var o={ok:true,fails:[]};function bad(m){o.ok=false;o.fails.push(m);}"
        "var pt=R('pthumb'),ft=R('fthumb'),pn=R('pname'),fn=R('fname'),pd=R('pdel'),fd=R('fdel');"
        "o.ptw=Math.round(pt.width);o.pth=Math.round(pt.height);o.ftw=Math.round(ft.width);"
        # миниатюра ограничена (квадратный бокс ~44px, зум учитываем множителем)
        "var z=" + str(bz) + ";function bnd(w,nm){var eff=w/z;if(eff<28||eff>80)bad(nm+' size '+Math.round(eff));}"
        "bnd(pt.width,'part-thumb-w');bnd(pt.height,'part-thumb-h');bnd(ft.width,'file-thumb-w');bnd(ft.height,'file-thumb-h');"
        "if(Math.abs(pt.width-pt.height)>2)bad('part-thumb not square');"
        # object-fit:contain применён
        "if(getComputedStyle(document.getElementById('pthumb')).objectFit!=='contain')bad('no contain');"
        # миниатюра не перекрывает имя и кнопки; имя не перекрывает кнопки
        "if(ov(pt,pn))bad('thumb overlaps part name');if(ov(pt,pd))bad('thumb overlaps del');"
        "if(ov(pn,pd))bad('name overlaps del btn');if(ov(ft,fn))bad('fthumb overlaps fname');if(ov(fn,fd))bad('fname overlaps fdel');"
        # кнопки видимы и в пределах панели
        "var panel=R('panel');if(pd.right>panel.right+2)bad('part del clipped');if(fd.right>panel.right+2)bad('file del clipped');"
        # страница не получает горизонтальный scroll
        "var de=document.documentElement;if(de.scrollWidth>de.clientWidth+2)bad('page hscroll '+de.scrollWidth+'>'+de.clientWidth);"
        "return o;}"
        "document.getElementById('__res').textContent='@@RES@@'+JSON.stringify(measure())+'@@END@@';</script>")
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<link rel='stylesheet' href='" + css_href + "'>" + U +
            "<style>html,body{margin:0;background:#141416}#bz{zoom:" + str(bz) + "}"
            "#__res{position:fixed;left:-9999px}</style></head><body><div id='bz'>" + body + "</div>" + meas +
            "</body></html>")


def run_layout(td, lang, bz, idx):
    pg = os.path.join(td, "lay_%s_%s.html" % (lang, str(bz)))
    io.open(pg, "w", encoding="utf-8", newline="\n").write(layout_page(lang, bz))
    prof = os.path.join(td, "p%d" % idx)
    # Alpha 2.834: --dump-dom в Edge 150 не отдаёт документ -> читаем DOM по CDP (tools/_edge_dom.py).
    dom = _edge_dom.dump_dom_compatible(EDGE, "file:///" + pg.replace("\\", "/"), prof,
                                        window_size=(1200, 800), budget_ms=4000)
    m = re.search(r"@@RES@@(\{.*?\})@@END@@", dom, re.S)
    return json.loads(m.group(1)) if m else None


LAY_CASES = [("45. RU 100%", "ru", 1.0), ("46. EN 100%", "en", 1.0),
             ("47. RU zoom125%", "ru", 1.25), ("48. RU zoom150%", "ru", 1.5),
             ("49. EN zoom150% (resize-эквивалент)", "en", 1.5), ("50. RU 100% (страница без h-scroll)", "ru", 1.0)]
if not EDGE:
    for lbl, _l, _z in LAY_CASES:
        check("L.%s" % lbl, False, _ENGINE_WHY)
else:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_p2thumb_lay_") as _ltd:
        for _i, (lbl, lang, bz) in enumerate(LAY_CASES):
            Rr = run_layout(_ltd, lang, bz, _i)
            if Rr is None:
                check("L.%s (нет ответа рендера)" % lbl, False, "no render result")
                continue
            check("L.%s (thumb=%sx%s)" % (lbl, Rr.get("ptw"), Rr.get("pth")), bool(Rr.get("ok")),
                  "; ".join(Rr.get("fails", []))[:180])

# ════════════════════════════════════════════════════════════════════════════
section("5. ПРОИЗВОДИТЕЛЬНОСТЬ / ПОВЕДЕНИЕ / ДОСТУПНОСТЬ")

check("38/39. object URL не создаётся (нет blob:/createObjectURL в резолвере -> нечего утекать)",
      "createObjectURL" not in RESOLVER_SRC and "blob:" not in RESOLVER_SRC)
check("6b. миниатюра ленивая (loading=lazy) — не грузит всё сразу",
      INDEXHTML.count('class="p2ed-thumb" loading="lazy"') == 2 or INDEXHTML.count('loading="lazy"') >= 2)
check("31b. при ошибке <img> -> безопасная fallback без бесконечного цикла (onThumbErr со стражем dataset.fb)",
      '@error="onThumbErr"' in INDEXHTML and "img.dataset.fb === '1'" in APPJS and "img.dataset.fb = '1'" in APPJS)
check("9-a11y. alt-текст детали/файла безопасен (без пути/ID/секрета)",
      ':alt="tr(\'Part thumbnail\')"' in INDEXHTML and ':alt="tr(\'File thumbnail\')"' in INDEXHTML
      and '"Part thumbnail": "Миниатюра детали"' in APPJS and '"File thumbnail": "Миниатюра файла"' in APPJS)
# 51-59 поведение: обработчики сохранены, part_id/file_id резолвер не пишет
check("51/52. добавление/удаление файла сохраняются (deleteProject2File + pick-path импорт целы)",
      "deleteProject2File" in APPJS and "/files/pick-path" in APPJS and "_addOneToProject2" in APPJS)
check("53. переименование детали сохраняется (saveProject2PartField цел)",
      "saveProject2PartField" in APPJS and "saveProject2PartField(pr.id, pp, 'notes')" in INDEXHTML)
check("54/55/56. количество деталей/part_id/file_id не меняются резолвером (он только читает id)",
      "part_id =" not in RESOLVER_SRC and "file_id =" not in RESOLVER_SRC and ".part_id=" not in RESOLVER_SRC)
check("57. Save/Cancel редактора сохранены (переключение режима правки цело)",
      "setProject2Mode(pr.id, 'edit')" in INDEXHTML and "setProject2Mode(pr.id, 'view')" in INDEXHTML)
check("58/59. миниатюра не влияет на проект/печать (резолвер без fetch/print/DELETE/POST)",
      not re.search(r"\bfetch\b|_send_file_to_printer|/print\b|method:\s*'(POST|DELETE|PATCH)'", RESOLVER_SRC))

# ════════════════════════════════════════════════════════════════════════════
section("6. РЕГРЕССИЯ И ГРАНИЦЫ")

check("60. основной список деталей сохраняет свои thumbnails (/part-thumb?name= >= 2 в index.html)",
      INDEXHTML.count("/part-thumb?name=") >= 2)
_pvprev = re.findall(r"\.pvprev-img\{([^}]*)\}", APPCSS)
check("61. Alpha 2.800 slicer previews сохранены (.pvprev-img contain, без cover; /part-thumb эндпоинт один)",
      bool(_pvprev) and all("object-fit:cover" not in b for b in _pvprev) and any("object-fit:contain" in b for b in _pvprev)
      and SRV.count('@app.get("/api/projects2/files/{file_id}/part-thumb")') == 1)
check("62. Bambu stop fix Alpha 2.820 сохранён (BAMBU_CANCEL_HMS в policy)",
      "BAMBU_CANCEL_HMS" in HEALTH)
check("63. Diagnostics responsive Alpha 2.821 сохранён (группы toolbar 2.821 + flex-wrap в app.css)",
      "diag-view-options" in INDEXHTML and "diag-actions-group" in INDEXHTML and "flex-wrap" in APPCSS)
check("64. Workspace height Alpha 2.817 сохранён (leftColH на статичных экранах)",
      'height: leftColH' in INDEXHTML or "leftColH" in INDEXHTML)
check("65. Workspace mode Alpha 2.816 сохранён (fm-settings-workspace/fm-diagnostics-workspace)",
      "fm-settings-workspace" in INDEXHTML and "fm-diagnostics-workspace" in INDEXHTML)
check("66. Nested modal stack сохранён (fm-overlay-root / v-modal-layer)",
      "fm-overlay-root" in INDEXHTML or "v-modal-layer" in INDEXHTML or "v-modal-layer" in APPJS)
check("67. Port Settings сохранён (POST /api/network + server_port)",
      '@app.post("/api/network")' in SRV and "server_port" in SRV)
check("68. Restart E2E/supervisor сохранён (импорт restart_supervisor + restart_cli в server.py)",
      "from app import restart_supervisor" in SRV and "restart_cli" in SRV)
check("69. Module management сохранён (/api/modules в server.py)",
      "/api/modules" in SRV)
check("70. DB/schema не менялись (нет ALTER TABLE project_files ADD; content_hash — существующий столбец)",
      "ALTER TABLE project_files ADD COLUMN" not in SRV
      and 'content_hash, target_nozzles' in SRV)  # существующий состав INSERT
check("71. Routes не менялись без необходимости (новых project-thumb роутов нет; /thumb и /part-thumb по 1)",
      SRV.count('@app.get("/api/projects2/files/{file_id}/thumb")') == 1
      and SRV.count('@app.get("/api/projects2/files/{file_id}/part-thumb")') == 1)
#  23.09.2026: сверяется контракт модуля с ядром (core_contract из module.json), а не номер выпуска: выпуск склада 1.7.30 при прежнем контракте 1.7.29.
_mods = {m: (lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(open(os.path.join(REPO, "modules", m, "module.json"), encoding="utf-8")))
         for m in ("inventory", "cost", "quality")}
#  Закреплённые версии модулей. Inventory поднят до 1.7.28 намеренно, в 2.890-2.891:
#  склад научился видеть подачу CFS у принтеров Creality K2. Остальные не менялись.
#  3.0: Cost — «Расчёт заказа» 0.2.0 на месте удалённой «Себестоимости печати» (слово владельца).
check("72. Module ZIP/версии не менялись (Inventory 1.7.29, Cost 0.2.0, Quality 0.2.3)",
      _mods == {"inventory": "1.7.29", "cost": "0.2.0", "quality": "0.2.3"}, _mods)
check("73. DISPATCH_ENABLED остаётся False", re.search(r"^DISPATCH_ENABLED = False\s*$", ORCH, re.M) is not None)
check("74. TRANSPORT_ENABLED остаётся False", re.search(r"^TRANSPORT_ENABLED = False\s*$", ORCH, re.M) is not None)
check("75. реальные printer commands отсутствуют в пути миниатюр (резолвер/эндпоинты превью не шлют команд)",
      "_send_file_to_printer" not in RESOLVER_SRC and "_send_file_to_printer" not in fn_src("project2_file_thumb"))
check("76. `_incoming/` не используется фичей миниатюр",
      "_incoming" not in RESOLVER_SRC and "_incoming" not in fn_src("project2_file_part_thumb"))
check("77. test artifacts отсутствуют (tools/_e2e_payload.json нет)",
      not os.path.isfile(os.path.join(REPO, "tools", "_e2e_payload.json")))

# ── Sentinel ────────────────────────────────────────────────────────────────
check("S1. sentinel отсутствует в production-исходниках",
      SENTINEL not in SRV and SENTINEL not in APPJS and SENTINEL not in INDEXHTML
      and SENTINEL not in APPCSS and SENTINEL not in ORCH and SENTINEL not in HEALTH)
check("S2. sentinel определён один раз в оснастке теста", OWN.count(SENTINEL) == 1)
check("SE-socket. за прогон не открыт ни один сокет", not _SOCKETS)

# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
_total = PASSED[0] + len(FAILED)
if SKIPPED:
    print("ПРОПУЩЕНО %d: %s" % (len(SKIPPED), ", ".join(SKIPPED)))
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), _total))
    for f in FAILED:
        print("   - %s" % f)
    _DONE["ok"] = True
    sys.exit(1)
print("PASS: миниатюры редактора проекта — все %d проверок пройдены; server.py не импортирован (AST); "
      "резолвер исполнен в Node; раскладка измерена в Edge" % _total)
_DONE["ok"] = True
sys.exit(0)
