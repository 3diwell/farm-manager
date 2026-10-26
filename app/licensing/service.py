# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Служба лицензий ядра FM (26.09.2026): хранилище, статусы модулей, решение по платной функции.

Ядро — открытое, поэтому его ответ «лицензия есть» для коммерческого компонента НЕ доказательство:
компонент сам проверяет исходный подписанный документ (license_documents) своими ключами и своим
вшитым выпуском. Ответы этой службы нужны для интерфейса, для штатного ограничения платных
маршрутов (ModuleCore.add_route(..., feature=...)) и для отказа в неподходящем обновлении.

Время компьютера участвует только в срочных лицензиях (use_type="term"); бессрочные права и право
на обновления решаются сравнением двух подписанных дат и от часов не зависят.
"""
import datetime
import email.utils
import math
import os
import re
import threading
import time

from app.licensing import fm_license_sdk as S
from app.licensing import package as P
from app.licensing import store as _store
from app.licensing import trust as _trust

LICENSE_OK = "active"
LICENSE_NOT_REQUIRED = "not_required"
LICENSE_MISSING = "missing"
UNSIGNED_PACKAGE = "unsigned_package"
LICENSE_STOPPED = S.R_LICENSE_STOPPED     # служба лицензий остановила ключ на этом компьютере
LICENSE_REVOKED = S.R_LICENSE_REVOKED     # лицензия аннулирована (возврат денег)
R_VERDICT_FOREIGN = "verdict_foreign"     # ответ службы для другого компьютера
R_VERDICT_STALE = "verdict_stale"         # ответ не на последнюю отметку этого компьютера
R_VERDICT_UNKNOWN = "verdict_unknown_license"
R_VERDICT_FUTURE = "verdict_future"       # дата ответа намного позже часов этого компьютера
R_VERDICT_BAD_LICENSE = "verdict_bad_license"   # вложенная в ответ лицензия не прошла проверку
VERDICT_CLOCK_SLACK_S = 24 * 3600

# 11.10.2026 (стенд службы лицензий 043): расписание отметок. Служба ограничивает число отметок
# (30 в час на лицензию, 20 в минуту с одной сети), поэтому каждая отметка уходит ОДИН раз — напрямую
# или через браузер, — с НОВЫМ случайным числом, и следующая попытка назначается по исходу:
MARK_EVERY_S = 6 * 3600            # ответ получен — следующая отметка через 6 часов
MARK_RETRY_S = 15 * 60             # отметка ушла напрямую, ответа нет (нет связи) — не раньше чем через 15 минут
#  17.10.2026 (ответ службы 043): без связи — повтор не чаще раза в 15 минут, и через браузер тоже. Было 10
#  минут: страница, у которой нет связи со службой, программе ничего не сообщала, и отметку отдавали снова
#  через 10 минут. Теперь страница сообщает «нет связи» (note_relay), а без её сообщения (вкладку закрыли)
#  отданная браузеру отметка ждёт те же 15 минут.
MARK_RELAY_WAIT_S = 15 * 60        # отметку отдали браузеру — ждём его ответа 15 минут, другой канал её не повторит
MARK_PENDING_TTL_S = 24 * 3600     # ответ принимается на отметку не старше суток (и только на последнюю)
RETRY_AFTER_DEFAULT_S = {429: 15 * 60, 503: 5 * 60}   # служба просит подождать, но не сказала сколько
RETRY_AFTER_MIN_S = 30
#  17.10.2026 (ответ службы 043): пауза 429/503 — ровно столько, сколько попросила служба, в том числе
#  дольше суток; раньше Retry-After программа не обращается ни напрямую, ни через браузер. Прежний предел
#  «не больше суток» сокращал такую паузу. Год — только защита от явной ошибки в заголовке (сотни лет).
RETRY_AFTER_MAX_S = 365 * 24 * 3600
#  Пауза без записи о том, когда и на сколько её поставили (файл прежней версии, правка руками), — как
#  прежде: действует, если кончается не дальше чем через сутки, иначе считается испорченной.
BACKOFF_UNRECORDED_MAX_S = 24 * 3600
#  17.10.2026 (замечание проверки): часы отстают от времени, когда служба попросила подождать, — конец
#  паузы в файле НЕ пересчитывается и не сокращается. Прежде пауза отсчитывалась заново от отстающих часов
#  и записывалась: один круг до сверки времени при запуске компьютера — и после поправки часов программа
#  отмечалась раньше Retry-After (пауза 3 суток превращалась в сутки, при сбросе часов на 2000 год —
#  пропадала). Конец паузы — момент по часам, как и Retry-After датой HTTP; часы спешили, когда служба
#  ответила, — пауза дольше, но не короче.
#  17.10.2026: стенд 043 принимает с одной сети не больше 20 запросов в минуту — программа отдаёт не больше
#  10 отметок в минуту на оба канала вместе (остальные остаются «пора» и уходят следующим кругом).
MARK_BURST_MAX = 10
MARK_BURST_WINDOW_S = 60


def retry_after_seconds(value, now):
    """Заголовок Retry-After (RFC 9110, 10.2.3) -> секунды ожидания или None, если заголовка нет или он
    не разобрался. Два вида: число секунд («120») и дата HTTP («Wed, 21 Oct 2026 07:28:00 GMT», а также
    устаревшие «Wednesday, 21-Oct-26 07:28:00 GMT» и «Wed Oct 21 07:28:00 2026»; дата HTTP всегда в
    GMT). Дата в прошлом — минимальная пауза (RETRY_AFTER_MIN_S)."""
    if value is None:
        return None
    v = str(value).strip()[:64]
    if not v:
        return None
    if re.fullmatch(r"[0-9]+", v):
        return int(v)          # сколь угодно большое число ограничит RETRY_AFTER_MAX_S
    try:
        d = email.utils.parsedate_to_datetime(v)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return max(RETRY_AFTER_MIN_S, int(math.ceil((d - now).total_seconds())))


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _later(now, seconds):
    return S.format_utc(now + datetime.timedelta(seconds=seconds))


def _backoff_end(marks, now):
    """Общая пауза 429/503, которая действует сейчас, -> время её конца или "". 17.10.2026: рядом с
    концом паузы хранится, когда её поставили (backoff_set_at) и на сколько попросила служба
    (backoff_s). Длинная пауза, о которой просила служба, — настоящая, даже если она дольше суток.
    Запись не сходится (конец позже, чем «поставили + длина», длина вне пределов) или её нет — пауза
    действует, только если кончается не дальше чем через сутки (как прежде). Часы перевели назад —
    конец паузы остаётся прежним (не сокращается). Испорченная запись отбрасывается в marks."""
    until = marks.get("backoff_until", "")
    if not until:
        return ""
    stamp = S.format_utc(now)
    set_at, length = marks.get("backoff_set_at", ""), marks.get("backoff_s", 0)
    recorded = False
    if set_at and isinstance(length, int) and not isinstance(length, bool) and 0 < length <= RETRY_AFTER_MAX_S:
        try:
            recorded = until <= _later(S.parse_utc(set_at, "backoff_set_at"), length + 60)
        except (S.Rejected, OverflowError, ValueError):
            #  17.10.2026: дата у предела календаря (9999 год) — «поставили + длина» не считается; такая
            #  запись испорчена, а не роняет каждый круг отметок и окно лицензий.
            recorded = False
    if not recorded and until > _later(now, BACKOFF_UNRECORDED_MAX_S + 60):
        marks["backoff_until"], marks["backoff_set_at"], marks["backoff_s"] = "", "", 0
        return ""
    return until if until > stamp else ""


class LicenseService(object):
    def __init__(self, data_dir, trusted=None):
        self.store = _store.LicenseStore(data_dir)
        self._trusted = trusted if trusted is not None else _trust.trusted_keys()
        self._lock = threading.Lock()
        self._revision = 0
        self._cache_key = None
        self._cache = []
        self._mark_lock = threading.RLock()
        self._machine_lock = threading.Lock()
        self._machine = None
        self._machine_at = 0.0
        self._verdict_key = None
        self._verdict_cache = []
        self._handed = []          # когда отданы последние отметки (оба канала) — для MARK_BURST_MAX

    # ── ключи ────────────────────────────────────────────────────────────────────────────────
    def trusted(self):
        return self._trusted

    def package_keys(self):
        return {k: v for k, v in self._trusted.items() if v.purpose == S.PURPOSE_PACKAGE}

    def license_keys(self):
        return {k: v for k, v in self._trusted.items() if v.purpose == S.PURPOSE_LICENSE}

    def test_keys_enabled(self):
        return any(k.test for k in self._trusted.values())

    def production_key_count(self):
        return sum(1 for k in self._trusted.values() if not k.test)

    # ── лицензии ─────────────────────────────────────────────────────────────────────────────
    def install_id(self):
        return self.store.install_id()

    def revision(self):
        """Меняется при импорте, удалении и замене файлов лицензий (в том числе вручную)."""
        self.entries()
        return self._revision

    def _dir_key(self):
        out = []
        for p in self.store._files():
            try:
                st = os.stat(p)
                out.append((os.path.basename(p), st.st_size, st.st_mtime_ns))
            except OSError:
                continue
        return tuple(out)

    def entries(self):
        """[{file, ok, code, payload}] — проверка подписи и схемы; повторно только при изменении файлов."""
        key = self._dir_key()
        with self._lock:
            if key != self._cache_key:
                self._cache = self.store.entries(self.license_keys())
                if self._cache_key is not None:
                    self._revision += 1
                self._cache_key = key
            return list(self._cache)

    def valid_payloads(self):
        return [e["payload"] for e in self.entries() if e["ok"]]

    def raw_documents(self):
        """Исходные байты всех файлов лицензий — как их выдал поставщик (для коммерческих модулей)."""
        return [raw for _name, raw in self.store.raw_documents()]

    def import_document(self, raw):
        payload = self.store.import_document(raw, self.license_keys())
        self.entries()
        self._mark_soon(payload["license_id"])   # новый ключ или продление — отметиться, как будет связь
        return payload

    def remove(self, license_id):
        ok = self.store.remove(license_id)
        if ok:
            #  Ответ службы («остановить»/«аннулирована») при удалении НЕ стирается: иначе «Удалить» и
            #  снова «Добавить» тот же ключ снимали бы остановку на ферме без интернета. Ответ действует,
            #  только пока лицензия с этим номером есть. Убирается лишь ждущая отметка.
            with self._mark_lock:
                marks = self.store.marks()
                marks["pending"].pop(str(license_id), None)
                marks["next"].pop(str(license_id), None)
                try:
                    self.store.save_marks(marks)
                except OSError:
                    pass
        self.entries()
        return ok

    # ── статусы ──────────────────────────────────────────────────────────────────────────────
    def module_status(self, module_id, pkg, now=None):
        """Сводка для интерфейса и для отказа в обновлении. pkg — результат package.inspect_dir."""
        pkg = pkg or {"state": P.STATE_UNSIGNED}
        out = P.summary(pkg)
        out["module_id"] = module_id
        if pkg.get("state") != P.STATE_VERIFIED:
            out["license"] = UNSIGNED_PACKAGE if pkg.get("state") == P.STATE_UNSIGNED else pkg.get("state")
            return out
        pl = pkg["payload"]
        if (pl.get("licensing") or {}).get("model", "free") == "free":
            out["license"] = LICENSE_NOT_REQUIRED
            return out
        d = S.best_decision(self.valid_payloads(), module_id, edition=pl["edition"], release=pl,
                            install_id=self.install_id(), now=now or _now(),
                            verdicts=self.verdict_payloads(), machine=self.machine())
        out["license"] = LICENSE_OK if d.ok else (LICENSE_MISSING if d.code == S.R_NO_GRANT else d.code)
        out["license_id"] = d.license_id
        if d.code in (LICENSE_STOPPED, LICENSE_REVOKED):
            out["license_reason"] = d.detail
        #  24.10.2026 (замечание сайта, пилот): какая лицензия разрешает действие, решает best_decision — она
        #  берёт ПЕРВУЮ подходящую. Сводка модуля так делать не должна: временная лицензия, добавленная к
        #  оплаченной, показывала «обновления до» своего короткого срока, будто оплаченный срок сократился.
        #  Сводка — по ВСЕМ лицензиям, каждая из которых сама даёт право на этот выпуск сейчас (подходит по
        #  модулю, редакции, выпуску и сроку, не остановлена и не аннулирована службой): бессрочно, если
        #  бессрочна хоть одна; «обновления до» и «пользование до» — самые поздние из действующих.
        if d.ok:
            granting = self._granting_payloads(module_id, pl, now or _now())
            if granting:
                out["updates_before"] = max(p["updates_before"] for p in granting)
                if any(p.get("use_type") != "term" for p in granting):
                    out["use_type"] = "perpetual"
                else:
                    out["use_type"] = "term"
                    out["use_valid_until"] = max(p.get("use_valid_until", "") for p in granting)
                out["license_ids"] = sorted(p["license_id"] for p in granting)
                return out
        lic = next((p for p in self.valid_payloads() if p.get("license_id") == d.license_id), None)
        if lic:
            out["updates_before"] = lic.get("updates_before", "")
            out["use_type"] = lic.get("use_type", "")
            if lic.get("use_type") == "term":
                out["use_valid_until"] = lic.get("use_valid_until", "")
        return out

    def _granting_payloads(self, module_id, release, now):
        """Лицензии, каждая из которых сама даёт право на выпуск release модуля сейчас, — с учётом ответов
        службы (остановленная или аннулированная для этого компьютера в счёт не идёт)."""
        verdicts, machine, iid = self.verdict_payloads(), self.machine(), self.install_id()
        out = []
        for p in self.valid_payloads():
            d = S.evaluate(p, module_id, edition=release["edition"], release=release, install_id=iid, now=now)
            if d.ok and (not verdicts or S.verdict_block(verdicts, d.license_id, machine) is None):
                out.append(p)
        return out

    def feature_decision(self, module_id, feature, pkg, now=None):
        """Можно ли выполнить платную функцию feature модуля (штатная граница ядра) -> Decision."""
        if not pkg or pkg.get("state") != P.STATE_VERIFIED:
            return S.Decision(False, UNSIGNED_PACKAGE)
        pl = pkg["payload"]
        lic = pl.get("licensing") or {}
        if feature not in (lic.get("paid_features") or []) and lic.get("model") != "paid":
            return S.Decision(True)   # бесплатная функция модуля
        return S.best_decision(self.valid_payloads(), module_id, feature=feature, edition=pl["edition"],
                               release=pl, install_id=self.install_id(), now=now or _now(),
                               verdicts=self.verdict_payloads(), machine=self.machine())

    def update_refusal(self, module_id, new_pkg, old_pkg, now=None):
        """Причина НЕ заменять рабочую версию новой — или "". Отказ, только если прежняя версия
        платного модуля покрыта лицензией, а новая — нет: иначе обновление отняло бы работающее."""
        if not new_pkg or new_pkg.get("state") != P.STATE_VERIFIED:
            return ""
        if (new_pkg["payload"].get("licensing") or {}).get("model", "free") == "free":
            return ""
        new_st = self.module_status(module_id, new_pkg, now)
        if new_st.get("license") == LICENSE_OK:
            return ""
        old_st = self.module_status(module_id, old_pkg, now) if old_pkg else {}
        if old_st.get("license") == LICENSE_OK and new_st.get("license") in (
                S.R_UPDATE_NOT_COVERED, S.R_RELEASE_SCOPE, S.R_CHANNEL, S.R_EDITION):
            return new_st["license"]
        return ""

    # ── для интерфейса ───────────────────────────────────────────────────────────────────────
    def public_list(self):
        """Лицензии для окна настроек: без подписи и без лишних сведений о покупателе."""
        out = []
        iid = self.install_id()
        verdicts, machine = self.verdict_payloads(), self.machine()
        answers = (self.store.marks().get("answers") or {})
        for e in self.entries():
            row = {"file": e["file"], "ok": e["ok"], "code": e["code"]}
            p = e.get("payload")
            if p:
                ib = (p.get("installation_binding") or {}).get("install_id", "")
                row.update({"license_id": p["license_id"], "use_type": p["use_type"],
                            "updates_before": p["updates_before"], "use_valid_until": p.get("use_valid_until", ""),
                            "issued_at": p.get("issued_at", ""), "channel": p.get("channel", "stable"),
                            "bound": bool(ib), "bound_here": (ib == iid) if ib else True,
                            "grants": [{"module_id": g["module_id"], "edition": g["edition"],
                                        "features": list(g["features"])} for g in p["grants"]]})
                blk = S.verdict_block(verdicts, p["license_id"], machine)
                row["service_state"] = "ok" if blk is None else ("revoked" if blk.code == LICENSE_REVOKED else "stop")
                row["service_reason"] = "" if blk is None else blk.detail
                ans = answers.get(p["license_id"]) or {}
                row["last_answer_at"] = ans.get("received_at", "")
            out.append(row)
        return out

    # ── 10.10.2026, вариант 3: номер компьютера, ключ текстом, отметка, ответ службы, согласие ────
    def machine(self):
        """Номер этого компьютера (пересчитывается не чаще раза в 10 минут)."""
        with self._machine_lock:
            t = time.monotonic()
            if self._machine is None or t - self._machine_at > 600:
                self._machine = self.store.machine()
                self._machine_at = t
            return self._machine

    def machine_short(self):
        return S.short_number(self.machine())

    def verdict_payloads(self):
        """Проверенные ответы службы лицензий (подпись ключом лицензий). Перепроверяются только при
        изменении файлов ответов — путь каждой платной операции и списка модулей остаётся дешёвым."""
        key = self.store.verdict_dir_key()
        with self._lock:
            if key == self._verdict_key:
                return list(self._verdict_cache)
        keys = self.license_keys()
        out = []
        for raw in self.store.verdict_raws():
            try:
                out.append(S.verify_verdict(raw, keys))
            except Exception:
                continue
        with self._lock:
            self._verdict_key, self._verdict_cache = key, out
        return list(out)

    def consent_given(self):
        return self.store.consent() is not None

    def give_consent(self):
        self.store.give_consent()

    def import_any(self, raw):
        """Ключ текстом, файл лицензии или ответ службы -> ("license", payload) | ("verdict", payload)."""
        txt = raw
        if isinstance(raw, (bytes, bytearray)):
            try:
                txt = bytes(raw).decode("utf-8-sig")
            except UnicodeDecodeError:
                txt = None
        if isinstance(txt, str) and S.is_key_text(txt):
            return "license", self.import_document(S.decode_key(txt))
        doc = S.load_document(txt if isinstance(txt, str) else raw)
        if doc.get("format") == S.FORMAT_VERDICT:
            return "verdict", self.apply_verdict(doc, via="browser")
        return "license", self.import_document(raw)

    @staticmethod
    def _mark_module(payload, installed):
        """Какой модуль назвать в отметке: установленный из лицензии, иначе первый. Модули одной
        лицензии занимают у службы ОДНО место на компьютер, поэтому отметка одна на лицензию."""
        mods = [g["module_id"] for g in payload["grants"]]
        return next((m for m in mods if m in (installed or {})), mods[0])

    def _live_documents(self):
        raws = dict(self.store.raw_documents())
        return [(e["payload"], raws[e["file"]]) for e in self.entries() if e["ok"] and e["file"] in raws]

    def preview_requests(self, installed, fm_version):
        """Отметки ровно в том виде, в каком они уходят, — для окна «Что передаётся». Ничего не
        отправляет и не запоминает; случайное число в настоящей отметке каждый раз новое."""
        if not self.consent_given():
            return []
        fp = self.machine()
        if not fp:
            return []
        out = []
        for p, raw in self._live_documents():
            mid = self._mark_module(p, installed)
            out.append(S.mark_request(raw, fp, mid, (installed or {}).get(mid, ""), fm_version, S.new_nonce()))
        return out

    def take_due(self, installed, fm_version, via="direct", now=None, force=False):
        """Отметки, которые пора отправить по этому каналу -> [dict]. installed — {module_id: version}.

        Пусто, пока не дано согласие, номер компьютера не прочитался или служба попросила подождать
        (Retry-After). Каждая отметка получает НОВОЕ случайное число (ответ на прежнюю после этого не
        примется) и время следующей попытки — до него ни прямой канал, ни браузер её не повторят.
        Не больше MARK_BURST_MAX отметок в минуту на оба канала вместе.
        force — для проверок: отметить всё сейчас."""
        if not self.consent_given():
            return []
        fp = self.machine()
        if not fp:
            return []
        now = now or _now()
        stamp = S.format_utc(now)
        docs = self._live_documents()
        out = []
        #  Срок дальше, чем бывает (часы переводили вперёд, файл правили), — недействителен: иначе отметки
        #  замолчали бы до той даты и копия ключа не обнаружилась бы. Общая пауза 429/503 проверяется по
        #  записи о ней (_backoff_end): длинная пауза, о которой просила служба, не отбрасывается.
        far_next = _later(now, MARK_EVERY_S + 3600)
        with self._mark_lock:
            marks = self.store.marks()
            before = repr(marks)
            backoff = _backoff_end(marks, now)    # испорченный срок отбрасывается и записывается ниже
            if not force and backoff:
                return []
            pending, nxt = marks["pending"], marks["next"]
            live = {p["license_id"] for p, _raw in docs}
            #  Отметки последней минуты; часы перевели — прежние отметки в счёт не идут.
            recent = [t for t in self._handed if abs((now - t).total_seconds()) < MARK_BURST_WINDOW_S]
            for p, raw in docs:
                lid = p["license_id"]
                if nxt.get(lid, "") > far_next:
                    nxt.pop(lid, None)
                if not force and nxt.get(lid, "") > stamp:
                    continue
                if not force and len(recent) + len(out) >= MARK_BURST_MAX:
                    continue     # остальные остаются «пора» и уйдут следующим кругом
                mid = self._mark_module(p, installed)
                nonce = S.new_nonce()
                pending[lid] = {"nonce": nonce, "created_at": stamp, "via": "browser" if via == "browser" else "direct"}
                nxt[lid] = _later(now, MARK_RELAY_WAIT_S if via == "browser" else MARK_RETRY_S)
                out.append(S.mark_request(raw, fp, mid, (installed or {}).get(mid, ""), fm_version, nonce, via=via))
            for lid in [k for k in list(pending) if k not in live]:
                pending.pop(lid, None)
            for lid in [k for k in list(nxt) if k not in live]:
                nxt.pop(lid, None)
            if repr(marks) != before:
                try:
                    self.store.save_marks(marks)
                except OSError:
                    return []      # не записалось, какое число ушло, — не отправляем вовсе
            self._handed = recent + ([] if force else [now] * len(out))
        return out

    def note_failure(self, license_id, outcome, retry_after=None, now=None):
        """Отметка не принесла принятого ответа. outcome:
          "network"   — нет связи или не дождались: следующая попытка не раньше чем через 15 минут;
          429 / 503   — служба просит подождать: ВСЕ отметки (оба канала) не раньше Retry-After —
                        секунды или дата HTTP (retry_after_seconds); не сказано, «0» или не разобралось —
                        15 / 5 минут; не меньше 30 секунд; 17.10.2026: дольше суток — как попросила
                        служба (предел — год, от явной ошибки в заголовке); более длинную паузу,
                        которая уже действует, более короткая не сокращает;
          другое      — служба отказала (неизвестная лицензия, неверный запрос) или ответ не прошёл
                        проверку: следующая попытка через 6 часов.
        Ни один из этих исходов не меняет права: остановку даёт только подписанный ответ службы, и
        сохранённая остановка от ошибок связи не снимается."""
        now = now or _now()
        lid = str(license_id or "")
        with self._mark_lock:
            marks = self.store.marks()
            if outcome in (429, 503):
                wait = retry_after_seconds(retry_after, now) or RETRY_AFTER_DEFAULT_S[outcome]
                wait = min(max(wait, RETRY_AFTER_MIN_S), RETRY_AFTER_MAX_S)
                until = _later(now, wait)
                if until > _backoff_end(marks, now):
                    marks["backoff_until"], marks["backoff_set_at"], marks["backoff_s"] = until, S.format_utc(now), wait
                when = until
            elif outcome == "network":
                when = _later(now, MARK_RETRY_S)
            else:
                when = _later(now, MARK_EVERY_S)
            if lid and S._ID_RE.match(lid):
                marks["next"][lid] = when      # исход заменяет предварительный срок, поставленный при отправке
            try:
                self.store.save_marks(marks)
            except OSError:
                pass

    def note_relay(self, license_id, status, retry_after=None, now=None):
        """Страница FM относила отметку службе, а принятого ответа не принесла (поля relay_* в
        /api/licenses/import) -> исход для note_failure. status:
          "429" / "503" — служба просит подождать (retry_after — заголовок Retry-After, если странице
                          его видно: служба должна открыть его браузеру Access-Control-Expose-Headers);
          "network"     — 17.10.2026: у этого браузера нет связи со службой, она не ответила за 20 секунд
                          или браузер не показал странице ответ (ответ без заголовков CORS) — 15 минут;
          другое        — служба отказала или программа не приняла ответ — 6 часов."""
        s = str(status if status is not None else "").strip()[:16]
        if s == "network":
            outcome = "network"
        else:
            try:
                code = int(s)
            except ValueError:
                code = None
            outcome = code if code in (429, 503) else "rejected"
        self.note_failure(license_id, outcome, retry_after, now=now)
        return outcome

    def _mark_soon(self, license_id):
        with self._mark_lock:
            marks = self.store.marks()
            if marks["next"].pop(str(license_id), None) is not None:
                try:
                    self.store.save_marks(marks)
                except OSError:
                    pass

    def apply_verdict(self, raw, via="direct"):
        """Принять подписанный ответ службы -> payload. Только ответ на ПОСЛЕДНЮЮ отметку ЭТОГО
        компьютера по известной лицензии; более старый ответ более новый не затирает. Если служба
        приложила продление лицензии — оно сохраняется тем же номером."""
        keys = self.license_keys()
        p = S.verify_verdict(raw, keys)
        if (S.parse_utc(p["checked_at"], "checked_at") - _now()).total_seconds() > VERDICT_CLOCK_SLACK_S:
            raise S.Rejected(R_VERDICT_FUTURE, "дата ответа в будущем")
        if p["machine"] != self.machine():
            raise S.Rejected(R_VERDICT_FOREIGN, "ответ для другого компьютера")
        if p["license_id"] not in {e["payload"]["license_id"] for e in self.entries() if e["ok"]}:
            raise S.Rejected(R_VERDICT_UNKNOWN)
        with self._mark_lock:
            marks = self.store.marks()
            pending = marks.setdefault("pending", {})
            pend = pending.get(p["license_id"]) or {}
            if pend.get("nonce") != p["nonce"]:
                raise S.Rejected(R_VERDICT_STALE, "ответ не на последнюю отметку")
            sent = str(pend.get("created_at") or "")
            if not re.match(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z", sent) or sent < _later(_now(), -MARK_PENDING_TTL_S):
                raise S.Rejected(R_VERDICT_STALE, "отметка, на которую ответ, старше суток")
            prev = [v for v in self.verdict_payloads() if v.get("license_id") == p["license_id"]]
            if prev and max(v["checked_at"] for v in prev) > p["checked_at"]:
                raise S.Rejected(R_VERDICT_STALE, "ответ старше сохранённого")
            #  11.10.2026: вложенная лицензия (продление) проверяется своей подписью и своим номером ДО
            #  того, как что-либо записано; не прошла — не принимается весь ответ, права не меняются.
            #  Более старый документ более новый не откатывает (это решает хранилище), повтор того же —
            #  ничего не меняет. Запись атомарная: сбой записи оставляет прежний файл.
            lic = p.get("license")
            if lic is not None:
                try:
                    lp = S.verify_license(lic, keys)
                except S.Rejected as e:
                    raise S.Rejected(R_VERDICT_BAD_LICENSE, e.code)
                if lp["license_id"] != p["license_id"]:
                    raise S.Rejected(R_VERDICT_BAD_LICENSE, "номер вложенной лицензии другой")
                self.store.import_document(lic, keys)
            self.store.save_verdict(p["license_id"], S.dump_document(S.load_document(raw)))
            pending.pop(p["license_id"], None)
            marks["answers"][p["license_id"]] = {
                "status": p["status"], "reason": p["reason"], "checked_at": p["checked_at"],
                "received_at": S.format_utc(_now()), "via": "browser" if via == "browser" else "direct"}
            marks["next"][p["license_id"]] = _later(_now(), MARK_EVERY_S)
            self.store.save_marks(marks)
        self.entries()
        return p

    def transmitted(self, installed, fm_version):
        """Для окна «Что передаётся»: отметки ровно в том виде, в каком они уходят (случайное число в
        каждой отметке новое), последние ответы и пауза, о которой попросила служба."""
        marks = self.store.marks()
        #  proof — секрет владельца ключа: на страницу уходит только начало (полностью — лишь в отметке,
        #  которую страница относит службе).
        reqs = [dict(r, proof=r["proof"][:8] + "\u2026") for r in self.preview_requests(installed, fm_version)]
        return {"requests": reqs,
                "answers": dict(marks.get("answers") or {}),
                "backoff_until": _backoff_end(dict(marks), _now())}   # действующая пауза; файл отметок не меняется
