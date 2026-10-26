# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Разбор APK приложения FM Client без сторонних программ — что приложение шлёт и ждёт от FM.

Исходников приложения у разработки FM нет (его пишет второй разработчик), а договорённость с
чужой программой не выдумывается (CLAUDE.md §6). APK — это zip; код — в classes*.dex. Скрипт
читает dex как байты: таблицу строк, классы, методы и для каждого метода — строки-константы
(const-string), вызываемые методы, обращения к полям и создаваемые типы, в порядке байткода.
Ничего из APK не исполняется и не устанавливается; jadx/apktool не нужны.

  python -I tools/_android_apk_dump.py dump  <файл.apk> <папка>   — распаковать (без опасных путей)
                                                                  и записать <папка>/app.json
  python -I tools/_android_apk_dump.py query <app.json> [подстрока класса] [--grep ТЕКСТ]
  python -I tools/_android_apk_dump.py diff  <старый app.json> <новый app.json>
                                                                — новые/исчезнувшие адреса, новые классы

Папку для APK брать пустую и вне проекта (файл чужой). Код приложения — пакет ru/threediwell/
(ключ --prefix меняет). Разбор 0.13.0 и 0.15.15 — docs/release_prep/ANDROID_CLIENT_NOTES.md.
"""
import json
import os
import re
import struct
import sys
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _uleb(b, p):
    r = s = 0
    while True:
        x = b[p]
        p += 1
        r |= (x & 0x7f) << s
        if x < 0x80:
            return r, p
        s += 7


def _mutf8(b, p):
    _, p = _uleb(b, p)
    raw = b[p:b.index(b"\x00", p)]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        out, i = [], 0
        while i < len(raw):
            c = raw[i]
            if c < 0x80:
                out.append(chr(c)); i += 1
            elif c >> 5 == 6:
                out.append(chr(((c & 0x1f) << 6) | (raw[i + 1] & 0x3f))); i += 2
            else:
                out.append(chr(((c & 0x0f) << 12) | ((raw[i + 1] & 0x3f) << 6) | (raw[i + 2] & 0x3f))); i += 3
        return "".join(out).encode("utf-16", "surrogatepass").decode("utf-16", "replace")


# Длина инструкций Dalvik в 16-битных словах (по формату опкода).
_SIZE = {op: 1 for op in range(256)}
_SIZE.update({0x02: 2, 0x03: 3, 0x05: 2, 0x06: 3, 0x08: 2, 0x09: 3, 0x13: 2, 0x14: 3, 0x15: 2, 0x16: 2, 0x17: 3, 0x18: 5,
              0x19: 2, 0x1a: 2, 0x1b: 3, 0x1c: 2, 0x1f: 2, 0x20: 2, 0x22: 2, 0x23: 2, 0x24: 3, 0x25: 3, 0x26: 3, 0x29: 2,
              0x2a: 3, 0x2b: 3, 0x2c: 3, 0xfa: 4, 0xfb: 4, 0xfc: 3, 0xfd: 3, 0xfe: 2, 0xff: 2})
for _lo, _hi, _n in ((0x2d, 0x31, 2), (0x32, 0x3d, 2), (0x44, 0x6d, 2), (0x6e, 0x72, 3), (0x74, 0x78, 3), (0x90, 0xaf, 2), (0xd0, 0xe2, 2)):
    for _op in range(_lo, _hi + 1):
        _SIZE[_op] = _n


def _code(b, off, strings, types, fields, methods):
    n = struct.unpack_from("<I", b, off + 12)[0]
    insns = struct.unpack_from("<%dH" % n, b, off + 16)
    out = {"str": [], "call": [], "field": [], "new": []}
    i = 0
    while i < n:
        w = insns[i]
        op = w & 0xff
        if op == 0 and w in (0x0100, 0x0200, 0x0300):          # таблицы switch и fill-array-data
            if w == 0x0100:
                i += insns[i + 1] * 2 + 4
            elif w == 0x0200:
                i += insns[i + 1] * 4 + 2
            else:
                i += (insns[i + 1] * (insns[i + 2] | (insns[i + 3] << 16)) + 1) // 2 + 4
            continue
        if op == 0x1a:
            out["str"].append(strings[insns[i + 1]])
        elif op == 0x1b:
            out["str"].append(strings[insns[i + 1] | (insns[i + 2] << 16)])
        elif 0x6e <= op <= 0x72 or 0x74 <= op <= 0x78 or op in (0xfa, 0xfb):
            c, m = methods[insns[i + 1]]
            out["call"].append((c[1:-1].split("/")[-1] if c.startswith("L") else c) + "." + m)
        elif 0x52 <= op <= 0x6d:
            c, f = fields[insns[i + 1]]
            out["field"].append(c[1:-1].split("/")[-1] + "." + f)
        elif op == 0x22:
            out["new"].append(types[insns[i + 1]])
        i += _SIZE[op]
    return {k: v for k, v in out.items() if v}


def _parse_dex(path, prefix):
    b = open(path, "rb").read()
    h = struct.unpack_from("<8sI20s20I", b, 0)
    (sid_n, sid_o, tid_n, tid_o, _, _, fid_n, fid_o, mid_n, mid_o, cd_n, cd_o) = h[9:21]
    strings = [_mutf8(b, struct.unpack_from("<I", b, sid_o + 4 * i)[0]) for i in range(sid_n)]
    types = [strings[struct.unpack_from("<I", b, tid_o + 4 * i)[0]] for i in range(tid_n)]
    fields = []
    for i in range(fid_n):
        c, _, nm = struct.unpack_from("<HHI", b, fid_o + 8 * i)
        fields.append((types[c], strings[nm]))
    methods = []
    for i in range(mid_n):
        c, _, nm = struct.unpack_from("<HHI", b, mid_o + 8 * i)
        methods.append((types[c], strings[nm]))
    classes = {}
    for i in range(cd_n):
        cidx, _, sup, _, _, _, cdo, _ = struct.unpack_from("<8I", b, cd_o + 32 * i)
        name = types[cidx]
        if not name.startswith(prefix):
            continue
        info = {"super": types[sup] if sup != 0xffffffff else None, "fields": [], "methods": {}}
        if cdo:
            p = cdo
            counts = []
            for _ in range(4):
                v, p = _uleb(b, p)
                counts.append(v)
            for cnt in counts[:2]:
                idx = 0
                for _ in range(cnt):
                    d, p = _uleb(b, p); _, p = _uleb(b, p); idx += d
                    info["fields"].append(fields[idx][1])
            for cnt in counts[2:]:
                idx = 0
                for _ in range(cnt):
                    d, p = _uleb(b, p); _, p = _uleb(b, p); co, p = _uleb(b, p); idx += d
                    key, k = methods[idx][1], 2
                    while key in info["methods"]:
                        key = "%s#%d" % (methods[idx][1], k); k += 1
                    info["methods"][key] = _code(b, co, strings, types, fields, methods) if co else {}
        classes[name] = info
    return classes


def _manifest_strings(raw):
    """Строки из пула двоичного AndroidManifest.xml (имя пакета, версия, разрешения)."""
    try:
        so = 8
        _, _, _, count, _, flags, start, _ = struct.unpack_from("<HHIIIIII", raw, so)
        utf8 = bool(flags & 0x100)
        out = []
        for i in range(count):
            p = so + start + struct.unpack_from("<I", raw, so + 28 + 4 * i)[0]
            if utf8:
                p += 1 + (raw[p] & 0x80 > 0)
                n = raw[p]; p += 1
                if n & 0x80:
                    n = ((n & 0x7f) << 8) | raw[p]; p += 1
                out.append(raw[p:p + n].decode("utf-8", "replace"))
            else:
                n = struct.unpack_from("<H", raw, p)[0]
                out.append(raw[p + 2:p + 2 + 2 * n].decode("utf-16-le", "replace"))
        return out
    except Exception:
        return []


def dump(apk, out_dir, prefix):
    z = zipfile.ZipFile(apk)
    safe = [n for n in z.namelist() if ".." not in n.split("/") and not n.startswith("/") and ":" not in n]
    x = os.path.join(out_dir, "x")
    z.extractall(x, members=safe)
    classes = {}
    for f in sorted(os.listdir(x)):
        if f.endswith(".dex"):
            for c, info in _parse_dex(os.path.join(x, f), prefix).items():
                info["dex"] = f
                classes[c] = info
    man = _manifest_strings(open(os.path.join(x, "AndroidManifest.xml"), "rb").read()) if os.path.isfile(os.path.join(x, "AndroidManifest.xml")) else []
    data = {"apk": os.path.basename(apk), "manifest_strings": man, "classes": classes}
    json.dump(data, open(os.path.join(out_dir, "app.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("классов приложения: %d (%s)" % (len(classes), prefix))
    print("манифест:", [s for s in man if re.match(r"^(\d+\.\d+|ru\.|android\.permission\.)", s)][:20])
    for s in sorted(_api_strings(classes)):
        print("  ", s)


def _api_strings(classes):
    out = {}
    for c, info in classes.items():
        for m, code in info["methods"].items():
            for s in code.get("str", []):
                if re.search(r"^/?(api|modules|ws|covers)\b|/api/", s):
                    out.setdefault(s, set()).add(c.split("/")[-1].rstrip(";") + "." + m)
    return out


def query(path, pat, grep):
    classes = json.load(open(path, encoding="utf-8"))["classes"]
    for c in sorted(classes):
        if pat and pat not in c:
            continue
        info, shown = classes[c], False
        for m, code in info["methods"].items():
            vals = [v for k in ("str", "call", "field", "new") for v in code.get(k, [])]
            if grep and not any(grep in v.lower() for v in vals):
                continue
            if not shown:
                print("\n### %s  (super %s)  fields=%s" % (c, info.get("super"), info.get("fields")))
                shown = True
            print("  -- %s" % m)
            for k in ("str", "call", "field", "new"):
                if code.get(k):
                    print("     %s: %s" % (k, json.dumps(code[k], ensure_ascii=False)))


def diff(old_path, new_path):
    old = json.load(open(old_path, encoding="utf-8"))["classes"]
    new = json.load(open(new_path, encoding="utf-8"))["classes"]
    ao, an = _api_strings(old), _api_strings(new)
    print("=== адреса: новые ===")
    for s in sorted(set(an) - set(ao)):
        print("  NEW ", s, "<-", sorted(an[s])[:3])
    print("=== адреса: исчезли ===")
    for s in sorted(set(ao) - set(an)):
        print("  GONE", s)
    print("=== новые классы (без вложенных) ===")
    for c in sorted(c for c in new if c not in old and "$" not in c):
        print("  ", c)


def main(argv):
    prefix = "Lru/threediwell/"
    if "--prefix" in argv:
        i = argv.index("--prefix"); prefix = argv[i + 1]; argv = argv[:i] + argv[i + 2:]
    grep = None
    if "--grep" in argv:
        i = argv.index("--grep"); grep = argv[i + 1].lower(); argv = argv[:i] + argv[i + 2:]
    if len(argv) >= 3 and argv[0] == "dump":
        return dump(argv[1], argv[2], prefix)
    if len(argv) >= 2 and argv[0] == "query":
        return query(argv[1], argv[2] if len(argv) > 2 else "", grep)
    if len(argv) == 3 and argv[0] == "diff":
        return diff(argv[1], argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
