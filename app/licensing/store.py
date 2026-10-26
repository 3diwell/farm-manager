# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Локальное хранилище лицензий и запрос активации (26.09.2026). Полностью офлайн.

Лицензии лежат файлами <DATA_DIR>/licenses/<license_id>.fmlic — ровно в том виде, в каком их выдал
поставщик (подписанный документ). Ядро их НЕ переписывает: коммерческий модуль получает исходный
документ и проверяет подпись сам. Номер установки (install_id) — случайная строка без личных данных;
нужен только лицензиям с привязкой к установке.
"""
import datetime
import json
import os
import secrets
import threading

from app.licensing import fm_license_sdk as S

LICENSE_DIR_NAME = "licenses"
LICENSE_SUFFIX = ".fmlic"
# 10.10.2026, вариант 3 (ключ, отметка, ответ службы): служебные файлы в той же папке лицензий.
MACHINE_FILE = "machine.json"        # номер компьютера и свёртки его частей (без самих значений)
MARKS_FILE = "marks.json"            # ждущие ответа отметки, последние ответы службы
CONSENT_FILE = "consent.json"        # согласие на передачу номера лицензии и номера компьютера
VERDICT_DIR = "verdicts"             # последний подписанный ответ службы по каждой лицензии
CONSENT_VERSION = 1
INSTALL_ID_FILE = "install_id.txt"
MAX_LICENSES = 500
_ID_LOCK = threading.Lock()


def _atomic_write(path, data):
    tmp = path + ".tmp-" + secrets.token_hex(4)
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class LicenseStore(object):
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.dir = os.path.join(data_dir, LICENSE_DIR_NAME)
        self._iid = None

    # ── номер установки ──────────────────────────────────────────────────────────────────────
    def install_id(self):
        """Номер установки. Создаётся один раз и больше НИКОГДА не перезаписывается: от него
        зависят лицензии с привязкой, и тихая смена номера отняла бы их. Файл, который не удалось
        прочитать или который испорчен (например, сохранён Блокнотом с BOM), остаётся как есть; при
        порче номер пустой — привязанные лицензии не действуют, пока файл не починят, но и не теряются."""
        with _ID_LOCK:
            if self._iid is not None:
                return self._iid
            path = os.path.join(self.data_dir, INSTALL_ID_FILE)
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8-sig") as f:
                        v = f.read().strip()
                except OSError:
                    return ""          # временный сбой чтения: не запоминаем, попробуем снова
                self._iid = v if S._ID_RE.match(v) else ""
                return self._iid
            v = "fm-" + secrets.token_hex(12)
            os.makedirs(self.data_dir, exist_ok=True)
            try:
                with open(path, "x", encoding="ascii") as f:   # «x»: не затирать, если кто-то успел создать
                    f.write(v)
                    f.flush()
                    os.fsync(f.fileno())
            except FileExistsError:
                return self._reread(path)
            self._iid = v
            return v

    def _reread(self, path):
        try:
            with open(path, encoding="utf-8-sig") as f:
                v = f.read().strip()
        except OSError:
            return ""
        self._iid = v if S._ID_RE.match(v) else ""
        return self._iid

    # ── лицензии ─────────────────────────────────────────────────────────────────────────────
    def _files(self):
        try:
            names = sorted(n for n in os.listdir(self.dir) if n.endswith(LICENSE_SUFFIX))
        except FileNotFoundError:
            return []
        return [os.path.join(self.dir, n) for n in names[:MAX_LICENSES]]

    def raw_documents(self):
        """[(имя файла, байты)] — исходные документы как есть (для коммерческих модулей)."""
        out = []
        for p in self._files():
            try:
                with open(p, "rb") as f:
                    out.append((os.path.basename(p), f.read()))
            except Exception:
                continue
        return out

    def entries(self, trusted):
        """[{file, ok, code, payload}] — каждая лицензия с результатом проверки подписи и схемы."""
        out = []
        for name, raw in self.raw_documents():
            try:
                p = S.verify_license(raw, trusted)
                out.append({"file": name, "ok": True, "code": "", "payload": p})
            except S.Rejected as e:
                out.append({"file": name, "ok": False, "code": e.code, "payload": None})
            except Exception:    # 11.10.2026: испорченный файл не роняет окно лицензий и не прячет остальные
                out.append({"file": name, "ok": False, "code": S.R_MALFORMED, "payload": None})
        return out

    def valid_payloads(self, trusted):
        return [e["payload"] for e in self.entries(trusted) if e["ok"]]

    def import_document(self, raw, trusted):
        """Проверить и сохранить лицензию. -> payload. Непроверенный файл не сохраняется вовсе.
        10.10.2026: продление приходит с тем же номером лицензии; более старый документ (например,
        прежний ключ из старого письма) более новый не затирает — остаётся новый."""
        payload = S.verify_license(raw, trusted)
        os.makedirs(self.dir, exist_ok=True)
        path = os.path.join(self.dir, payload["license_id"] + LICENSE_SUFFIX)
        if os.path.exists(path):
            #  11.10.2026: прежний файл не прочитался (занят, нет доступа) — НЕ затираем: иначе более старый
            #  документ мог бы заменить более новый. Ошибка видна вызывающему, прежний файл цел.
            with open(path, "rb") as f:
                old_raw = f.read()
            try:
                old = S.verify_license(old_raw, trusted)
                if old["issued_at"] > payload["issued_at"]:
                    return old
            except Exception:
                pass            # прежний файл испорчен — его можно заменить проверенным
        elif len(self._files()) >= MAX_LICENSES:
            raise S.Rejected(S.R_BAD_VALUE, "слишком много лицензий")
        if isinstance(raw, dict):
            body = S.dump_document(raw)
        else:
            body = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
        _atomic_write(path, body)
        return payload

    def remove(self, license_id):
        if not S._ID_RE.match(str(license_id or "")):
            return False
        path = os.path.join(self.dir, str(license_id) + LICENSE_SUFFIX)
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False

    # ── запрос активации ─────────────────────────────────────────────────────────────────────
    def activation_request(self, fm_version, modules):
        """Файл для поставщика: какие модули нужны и номер установки. Без имён, адресов и данных фермы.
        modules — [{"module_id", "version", "edition"}]."""
        return {"format": "fm-activation-request", "v": 1, "product_id": S.PRODUCT_ID,
                "install_id": self.install_id(), "fm_version": str(fm_version or ""),
                "created_at": S.format_utc(datetime.datetime.now(datetime.timezone.utc)),
                "modules": [{"module_id": str(m.get("module_id", "")), "version": str(m.get("version", "")),
                             "edition": str(m.get("edition", ""))} for m in (modules or [])][:64]}

    # ── 10.10.2026, вариант 3: номер компьютера, ответы службы, отметки, согласие ─────────────────
    def _read_json(self, name):
        try:
            with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                v = json.load(f)
            return v if isinstance(v, dict) else None
        except Exception:
            return None

    def _write_json(self, name, obj):
        os.makedirs(self.dir, exist_ok=True)
        _atomic_write(os.path.join(self.dir, name),
                      json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8"))

    def machine(self, components=None):
        """Номер этого компьютера (64 hex) или "" — если ни одну часть прочитать не удалось.
        Хранятся только свёртки частей: номер не меняется при замене одной из трёх."""
        stored = self._read_json(MACHINE_FILE)
        fp, state = S.machine_identity(stored, components)
        if fp and state != stored:
            try:
                self._write_json(MACHINE_FILE, state)
            except OSError:
                pass
        return fp

    def verdict_raws(self):
        d = os.path.join(self.dir, VERDICT_DIR)
        try:
            names = sorted(n for n in os.listdir(d) if n.endswith(".json"))[:MAX_LICENSES]
        except OSError:
            return []
        out = []
        for n in names:
            try:
                with open(os.path.join(d, n), "rb") as f:
                    out.append(f.read())
            except OSError:
                continue
        return out

    def save_verdict(self, license_id, raw):
        if not S._ID_RE.match(str(license_id or "")):
            raise S.Rejected(S.R_BAD_VALUE, "license_id")
        d = os.path.join(self.dir, VERDICT_DIR)
        os.makedirs(d, exist_ok=True)
        _atomic_write(os.path.join(d, license_id + ".json"), raw if isinstance(raw, (bytes, bytearray)) else S.dump_document(raw))

    def marks(self):
        """{"pending": {license_id: {...}}, "answers": {license_id: {...}}, "next": {license_id: время},
        "backoff_until": время, "backoff_set_at": время, "backoff_s": секунды} — испорченное
        отбрасывается. Время — строго ГГГГ-ММ-ДДTчч:мм:ссZ, поэтому сравнивается как строка.
        17.10.2026: backoff_set_at и backoff_s — когда служба попросила подождать и на сколько (по ним
        программа отличает настоящую долгую паузу от испорченного срока)."""
        raw = self._read_json(MARKS_FILE) or {}
        out = {}
        for k in ("pending", "answers"):
            v = raw.get(k)
            out[k] = {str(i): dict(x) for i, x in v.items() if isinstance(x, dict)} if isinstance(v, dict) else {}
        v = raw.get("next")
        out["next"] = ({str(i): x for i, x in v.items() if isinstance(x, str) and S._UTC_RE.match(x)}
                       if isinstance(v, dict) else {})
        b = raw.get("backoff_until")
        out["backoff_until"] = b if isinstance(b, str) and S._UTC_RE.match(b) else ""
        b = raw.get("backoff_set_at")
        out["backoff_set_at"] = b if isinstance(b, str) and S._UTC_RE.match(b) else ""
        b = raw.get("backoff_s")
        out["backoff_s"] = b if isinstance(b, int) and not isinstance(b, bool) and b > 0 else 0
        return out

    def verdict_dir_key(self):
        d = os.path.join(self.dir, VERDICT_DIR)
        out = []
        try:
            for n in sorted(os.listdir(d)):
                try:
                    st = os.stat(os.path.join(d, n))
                    out.append((n, st.st_size, st.st_mtime_ns))
                except OSError:
                    continue
        except OSError:
            return ()
        return tuple(out)

    def save_marks(self, marks):
        self._write_json(MARKS_FILE, marks)

    def consent(self):
        v = self._read_json(CONSENT_FILE)
        return v if v and v.get("version") == CONSENT_VERSION else None

    def give_consent(self):
        self._write_json(CONSENT_FILE, {"version": CONSENT_VERSION,
                                        "accepted_at": S.format_utc(datetime.datetime.now(datetime.timezone.utc))})
