# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.870 — передача видео с камеры БЕЗ ПЕРЕКОДИРОВАНИЯ: разбор fMP4 и раздача зрителям.

ЗАЧЕМ. Прежний путь камеры Bambu перекодирует H.264 в MJPEG отдельным ffmpeg на каждую
камеру. Измерено 23.08.2026 на 20-секундном ролике 1920x1080 (ffmpeg -benchmark, эта машина):
перекодирование в MJPEG 15 к/с — 7,89 с процессорного времени, 30 к/с — 10,97 с, а ремукс
без перекодирования (-c:v copy -> fMP4) — 0,03 с. Разница в 250-340 раз: именно она и делает
невозможной стену из двенадцати камер на слабом компьютере.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ app/camera_hub.py И ПОЧЕМУ ОН НЕ ПОДОШЁЛ. Тот распределитель хранит
ТОЛЬКО ПОСЛЕДНИЙ кадр и намеренно выбрасывает промежуточные — для MJPEG это верно, каждый
кадр там самостоятельная картинка. Для H.264 это фатально: фрагменты ссылаются друг на друга,
выброшенный кусок рвёт цепочку декодирования, и картинка рассыпается. Поэтому здесь СВОЙ
распределитель с очередью на зрителя, а прежний путь не тронут вовсе.

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО: ни сети, ни процессов, ни FastAPI. Источник передаётся снаружи
объектом с chunks()/close(), поэтому весь разбор и вся раздача проверяются без принтера.
"""
import collections
import struct
import threading
import time


def log_key(value):
    """Ключ владельца потока для журнала. У Bambu ключ — «адрес|код доступа» (12.10.2026: код попадал в
    farm.log, который владелец отправляет разработке кнопкой «Скачать журнал»). В журнал идёт только
    адрес — часть до «|»; ключ без «|» (адрес потока FlashForge) остаётся как есть."""
    s = str(value)
    return s.split("|", 1)[0] + "|…" if "|" in s else s


# ── Разбор потока fMP4 ────────────────────────────────────────────────────────────────────
#  ffmpeg с -movflags +frag_keyframe+empty_moov+default_base_moof отдаёт:
#      ftyp, moov            — «шапка» (init segment), нужна КАЖДОМУ зрителю первой;
#      moof, mdat, moof, ... — фрагменты, каждый начинается с ключевого кадра.
#  Зритель, подключившийся в середине, получает шапку + ближайший целый фрагмент — и картинка
#  собирается сразу. Резать поток «как попало» нельзя: браузер не примет обрывок коробки.

_HDR = 8                       # размер (4 байта) + тип (4 байта)
_INIT_BOXES = (b"ftyp", b"moov", b"styp", b"free", b"skip")
#  Служебные коробки, которые НЕ являются куском видео. Браузеру их слать нельзя: он ждёт
#  moof+mdat. mfra/mfro ffmpeg дописывает, когда закрывает ФАЙЛ (в живом потоке их не бывает,
#  но проверка гоняет тот же код на записанном ролике); sidx/free/skip встречаются как мусор.
_SKIP_BOXES = (b"mfra", b"mfro", b"sidx", b"free", b"skip")


class Fmp4Splitter(object):
    """Режет байтовый поток ffmpeg на шапку и ЦЕЛЫЕ фрагменты. Ничего не выбрасывает."""

    def __init__(self):
        self._buf = bytearray()
        self._init = bytearray()
        self._init_done = False
        self._frag = bytearray()
        self._skipped = 0

    @property
    def skipped_boxes(self):
        """Сколько служебных коробок отброшено (для журнала и проверок)."""
        return self._skipped

    @property
    def init_segment(self):
        """Шапка потока или None, пока она не собрана целиком."""
        return bytes(self._init) if self._init_done else None

    def feed(self, data):
        """Принять кусок байтов. Вернуть список готовых фрагментов (шапка отдаётся отдельно)."""
        out = []
        if data:
            self._buf += data
        while True:
            box = self._take_box()
            if box is None:
                return out
            typ, raw = box
            if not self._init_done:
                if typ in _INIT_BOXES:
                    self._init += raw
                    continue
                self._init_done = True          # первый moof закрывает шапку
            if typ == b"moof":
                if self._frag:
                    out.append(bytes(self._frag))
                    self._frag = bytearray()
                self._frag += raw
            elif typ == b"mdat":
                self._frag += raw
                out.append(bytes(self._frag))
                self._frag = bytearray()
            elif typ in _SKIP_BOXES:
                self._skipped += 1          # служебная коробка: в видео не отдаём
            else:
                if self._frag:
                    self._frag += raw
                else:
                    out.append(raw)

    @staticmethod
    def is_keyframe_fragment(frag):
        """Начинается ли фрагмент с ключевого кадра.

        Alpha 2.874. Раньше ffmpeg резал поток ТОЛЬКО по ключевым кадрам, и любой фрагмент годился
        для подключения нового зрителя. Но тогда порция приходила раз в интервал ключевых кадров:
        измерено 24.08.2026 — при ключевом кадре раз в 2 с браузер две секунды не получал ничего,
        потом разом весь кусок. Отсюда «частота прыгает от 0 до 30» и заметная задержка.
        Теперь поток режется ещё и по времени, порции идут ровно — но кусок из середины группы
        декодировать не с чего, поэтому зрителю нужно начинать ИМЕННО с ключевого фрагмента.

        Признак берём из самого фрагмента: moof -> traf -> trun, флаги первой выборки.
        sample_depends_on == 2 означает «ни от кого не зависит», то есть ключевой кадр.
        Не разобрали — считаем ключевым: лучше показать лишний кадр, чем не показать ничего.
        """
        try:
            i = 8                                   # внутрь moof
            end = len(frag)
            while i + 8 <= end:
                sz = struct.unpack(">I", frag[i:i + 4])[0]
                typ = frag[i + 4:i + 8]
                if sz < 8 or i + sz > end:
                    return True
                if typ == b"traf":
                    j = i + 8
                    tend = i + sz
                    while j + 8 <= tend:
                        s2 = struct.unpack(">I", frag[j:j + 4])[0]
                        t2 = frag[j + 4:j + 8]
                        if s2 < 8 or j + s2 > tend:
                            return True
                        if t2 == b"trun":
                            flags = struct.unpack(">I", frag[j + 8:j + 12])[0] & 0xFFFFFF
                            p = j + 12 + 4          # версия+флаги, затем sample_count
                            if flags & 0x000001:    # data_offset_present
                                p += 4
                            if flags & 0x000004:    # first_sample_flags_present
                                sf = struct.unpack(">I", frag[p:p + 4])[0]
                                return ((sf >> 24) & 0x3) == 2 or not ((sf >> 16) & 0x1)
                            # Флагов первой выборки нет — значит выборка обычная, из середины
                            # группы. Проверено на выводе ffmpeg 24.08.2026: у ключевого фрагмента
                            # trun несёт 0x000004, у остальных — нет.
                            return False
                        j += s2
                    return True
                i += sz
        except Exception:
            return True
        return True

    def _take_box(self):
        """Снять из буфера одну ЦЕЛУЮ коробку. None — данных ещё не хватает."""
        if len(self._buf) < _HDR:
            return None
        size = struct.unpack(">I", bytes(self._buf[0:4]))[0]
        typ = bytes(self._buf[4:8])
        head = _HDR
        if size == 1:                                  # 64-битный размер
            if len(self._buf) < 16:
                return None
            size = struct.unpack(">Q", bytes(self._buf[8:16]))[0]
            head = 16
        if size == 0:                                  # «до конца потока» — в живом потоке не бывает
            return None
        if size < head or size > (1 << 31):
            raise ValueError("испорченная коробка MP4: тип=%r размер=%d" % (typ, size))
        if len(self._buf) < size:
            return None
        raw = bytes(self._buf[:size])
        del self._buf[:size]
        return typ, raw


# ── Раздача фрагментов зрителям ───────────────────────────────────────────────────────────

class OwnerState(object):
    IDLE = "idle"
    STARTING = "starting"
    LIVE = "live"


class _Subscriber(object):
    """Один зритель. Своя очередь: медленный зритель НЕ тормозит остальных и не копит память."""

    def __init__(self, hub, key, max_fragments):
        self._hub = hub
        self._key = key
        self._q = collections.deque()
        self._max = max(2, int(max_fragments))
        self._closed = False
        self._dropped = 0
        self._sent_init = False
        # Alpha 2.874: поток режется не только по ключевым кадрам, поэтому первый выданный
        # зрителю фрагмент обязан быть КЛЮЧЕВЫМ — с середины группы декодировать не с чего.
        self._need_key = True
        self._waited = 0
        self._resyncs = 0

    @property
    def resyncs(self):
        """Сколько раз зритель отставал и начинал заново с ключевого кадра.

        Это и есть честный счётчик «фризов по нашей вине»: ноль — значит рывки пришли не отсюда."""
        return self._resyncs

    @property
    def closed(self):
        return self._closed

    @property
    def waited_for_key(self):
        """Сколько фрагментов пропущено в ожидании ключевого (для журнала и проверок)."""
        return self._waited

    @property
    def dropped(self):
        """Сколько фрагментов выброшено из-за отставания зрителя (для журнала и тестов)."""
        return self._dropped

    def _put(self, data, is_key=True):
        if self._need_key:
            if not is_key:
                self._waited += 1
                return                    # ждём ключевой фрагмент, мусор зрителю не шлём
            self._need_key = False
        self._q.append(data)
        if len(self._q) > self._max:
            # Alpha 2.875. ЗДЕСЬ БЫЛ ДЕФЕКТ, И ОН ДАВАЛ ФРИЗЫ. Прежде очередь подрезалась
            # выбрасыванием СТАРЫХ фрагментов (popleft). Для MJPEG это верно, а для H.264 —
            # ровно та ошибка, из-за которой не подошёл прежний распределитель кадров:
            # выброшенный кусок рвёт цепочку декодирования, и картинка сыплется до следующего
            # ключевого кадра, то есть секунды. Правильное поведение при отставании —
            # честно начать заново с ближайшего ключевого фрагмента: короткая пауза вместо
            # длинной каши. Тот же принцип уже применён в браузерном проигрывателе.
            self._dropped += len(self._q)
            self._q.clear()
            self._need_key = True
            self._resyncs += 1
            # В журнал: это ЕДИНСТВЕННОЕ место, где рывок картинки возникает по нашей вине.
            # Пусто в журнале — значит рывки пришли из сети или от самого принтера.
            self._hub._say("warning", "[CAM/mp4] %s: зритель отстал, начинаем заново с ключевого"
                                      " кадра (раз: %d)", self._key, self._resyncs)

    def chunks(self, timeout=None):
        """Генератор: сперва шапка, затем фрагменты. Завершается при закрытии или смерти владельца."""
        while True:
            item = self._hub._wait_chunk(self._key, self, timeout)
            if item is None or self._closed:
                return
            yield item

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._hub._unsubscribe(self._key, self)


class Fmp4Hub(object):
    """Один источник (один ffmpeg, одно соединение с принтером) на ключ; зрителей сколько угодно.

    open_source(key) -> объект с методами:
        chunks() — генератор БАЙТОВ потока fMP4 (куски произвольного размера);
        close()  — гасит свой процесс, чтобы чтение разблокировалось.
    Время берётся через now(), поток владельца запускается через spawn() — в тестах и то,
    и другое поддельное, поэтому проверки не спят и ничего не запускают.
    """

    def __init__(self, open_source, first_data_timeout=15.0, stall_timeout=10.0,
                 idle_grace=5.0, retry_base=1.0, retry_max=30.0,
                 max_fragments_per_viewer=8, log=None, now=None, spawn=None,
                 report_every=60.0, long_gap=1.0, can_start=None):
        self._open_source = open_source
        self._first_data_timeout = float(first_data_timeout)
        self._stall_timeout = float(stall_timeout)
        self._idle_grace = float(idle_grace)
        self._retry_base = float(retry_base)
        self._retry_max = float(retry_max)
        self._max_frag = int(max_fragments_per_viewer)
        self._report_every = float(report_every)   # как часто докладывать о ровности потока
        self._long_gap = float(long_gap)           # перерыв, который уже считается заметным
        self._log = log
        #  Alpha 2.886: право на внешний поток. Спрашивается ПЕРЕД подъёмом источника.
        #  Пока право у другого пути показа (тот же принтер, другой раздатчик), источник
        #  не поднимается вовсе — иначе у принтера окажется два соединения с камерой,
        #  а он держит одно.
        self._can_start = can_start
        self._now = now or time.monotonic
        self._spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True,
                                                            name="cam-fmp4").start())
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._owners = {}

    # -- служебное --------------------------------------------------------------------
    def _say(self, level, msg, *args):
        if self._log is None:
            return
        try:
            #  12.10.2026: любой строковый аргумент с «|» — это ключ «адрес|код»; код в журнал не идёт.
            getattr(self._log, level)(msg, *[log_key(a) if isinstance(a, str) and "|" in a else a for a in args])
        except Exception:
            pass

    def _blank(self, key):
        return {"key": key, "state": OwnerState.IDLE, "src": None, "gen": 0, "stop": False,
                "init": None, "subs": [], "last_data_at": None, "started_at": None,
                "fails": 0, "retry_after": None, "seq": 0, "idle_since": None,
                # Alpha 2.875: ровность потока ОТ ПРИНТЕРА. Нужна, чтобы отвечать на вопрос
                # «рывки — это программа или камера?» фактом, а не рассуждением: перерывы
                # видны здесь, ДО браузера, значит к показу они отношения не имеют.
                "rate": {"since": None, "count": 0, "max_gap": 0.0, "long": 0, "prev": None}}

    def _note_fragment(self, o, now):
        """Учесть пришедший фрагмент и раз в минуту доложить, ровно ли идёт поток."""
        r = o["rate"]
        if r["since"] is None:
            r["since"] = now
        if r["prev"] is not None:
            gap = now - r["prev"]
            if gap > r["max_gap"]:
                r["max_gap"] = gap
            if gap >= self._long_gap:
                r["long"] += 1
        r["prev"] = now
        r["count"] += 1
        if now - r["since"] < self._report_every:
            return
        span = max(0.001, now - r["since"])
        if r["long"]:
            self._say("warning",
                      "[CAM/mp4] %s: за %.0f c получено %d порций, БЫЛИ ПЕРЕРЫВЫ: самый долгий "
                      "%.1f c, дольше %.0f c — %d раз(а). Это перерывы В ПОТОКЕ ОТ ПРИНТЕРА, "
                      "до показа на экране", o["key"], span, r["count"], r["max_gap"],
                      self._long_gap, r["long"])
        else:
            self._say("info", "[CAM/mp4] %s: за %.0f c получено %d порций, поток ровный "
                              "(самый долгий перерыв %.2f c)", o["key"], span, r["count"], r["max_gap"])
        o["rate"] = {"since": now, "count": 0, "max_gap": 0.0, "long": 0, "prev": now}

    def _owner(self, key):
        o = self._owners.get(key)
        if o is None:
            o = self._blank(key)
            self._owners[key] = o
        return o

    # -- публичное --------------------------------------------------------------------
    def subscribe(self, key):
        with self._lock:
            o = self._owner(key)
            sub = _Subscriber(self, key, self._max_frag)
            o["subs"].append(sub)
            o["idle_since"] = None
            if o["state"] == OwnerState.IDLE and o["retry_after"] is None:
                self._start_locked(o)
            self._cond.notify_all()
            return sub

    def stats(self, key=None):
        with self._lock:
            def one(o):
                return {"state": o["state"], "viewers": len(o["subs"]), "fails": o["fails"],
                        "has_init": o["init"] is not None, "fragments": o["seq"],
                        # Сколько раз зрителям пришлось начинать заново из-за отставания.
                        "resyncs": sum(x.resyncs for x in o["subs"])}
            if key is not None:
                o = self._owners.get(key)
                return one(o) if o else None
            return dict((k, one(v)) for k, v in self._owners.items())

    def owners_alive(self):
        with self._lock:
            return [k for k, o in self._owners.items()
                    if o["state"] in (OwnerState.STARTING, OwnerState.LIVE)]

    def tick(self):
        """Сторож: раз в секунду. Гасит зависшие и никому не нужные источники, поднимает упавшие."""
        with self._lock:
            for o in list(self._owners.values()):
                self._tick_one_locked(o)
            self._cond.notify_all()

    def stop_key(self, key, reason="уступает место другому пути показа"):
        """Погасить владельца потока для этого принтера и дождаться закрытия источника.

        Alpha 2.886. Возвращает True, если владелец действительно был. Источник закрывается
        синхронно (у него внутри terminate + ожидание процесса), поэтому после возврата
        соединения с камерой у нас уже нет — это и есть «сначала погасить, потом поднять».
        """
        with self._lock:
            o = self._owners.get(key)
            if o is None:
                return False
            self._stop_locked(o, reason)
            self._cond.notify_all()
        return True

    def shutdown(self):
        with self._lock:
            for o in list(self._owners.values()):
                self._stop_locked(o, "остановка программы")
            self._cond.notify_all()

    # -- внутреннее -------------------------------------------------------------------
    def _start_locked(self, o):
        #  Alpha 2.886. Право на внешний поток спрашивается ЗДЕСЬ — в единственном месте, где
        #  источник действительно поднимается. Проверять у вызывающих нельзя: подписка первого
        #  зрителя поднимает владельца сразу, минуя сторожа, и второе соединение к камере
        #  появилось бы ещё до первого обхода.
        if self._can_start is not None and not self._can_start(o["key"]):
            o["state"] = OwnerState.IDLE
            o["retry_after"] = self._now() + 1.0
            return
        o["gen"] += 1
        gen = o["gen"]
        o["state"] = OwnerState.STARTING
        o["stop"] = False
        o["init"] = None
        o["started_at"] = self._now()
        o["last_data_at"] = None
        o["retry_after"] = None
        try:
            src = self._open_source(o["key"])
        except Exception:
            self._fail_locked(o, "источник не открылся")
            return
        o["src"] = src
        self._say("info", "[CAM/mp4] %s: источник открыт (без перекодирования)", o["key"])
        self._spawn(lambda: self._pump(o["key"], gen, src))

    def _pump(self, key, gen, src):
        """Поток владельца: тянет байты, режет на фрагменты, раздаёт зрителям."""
        splitter = Fmp4Splitter()
        reason = "источник закончился"
        try:
            for data in src.chunks():
                frags = splitter.feed(data)
                init = splitter.init_segment
                with self._lock:
                    o = self._owners.get(key)
                    if o is None or o["gen"] != gen or o["stop"]:
                        break
                    if init is not None and o["init"] is None:
                        o["init"] = init
                        self._cond.notify_all()
                    if frags:
                        _now = self._now()
                        o["last_data_at"] = _now
                        for _ in frags:
                            self._note_fragment(o, _now)
                        if o["state"] == OwnerState.STARTING:
                            o["state"] = OwnerState.LIVE
                            o["fails"] = 0
                            self._say("info", "[CAM/mp4] %s: первый фрагмент, поток живой", key)
                        for f in frags:
                            o["seq"] += 1
                            # Ключевой фрагмент считаем ОДИН раз на всех: разбор коробок стоит
                            # денег, а зрителей может быть много.
                            is_key = Fmp4Splitter.is_keyframe_fragment(f)
                            for s in o["subs"]:
                                s._put(f, is_key)
                        self._cond.notify_all()
        except Exception as exc:
            reason = "источник упал: %s" % type(exc).__name__
        finally:
            with self._lock:
                o = self._owners.get(key)
                if o is not None and o["gen"] == gen:
                    self._stop_locked(o, reason)
                self._cond.notify_all()

    def _stop_locked(self, o, reason):
        o["stop"] = True
        src, o["src"] = o["src"], None
        o["state"] = OwnerState.IDLE
        o["init"] = None
        o["last_data_at"] = None
        o["started_at"] = None
        if src is not None:
            self._say("info", "[CAM/mp4] %s: источник закрыт (%s)", o["key"], reason)
            try:
                src.close()
            except Exception:
                self._say("debug", "[CAM/mp4] %s: закрытие источника дало исключение", o["key"])

    def _fail_locked(self, o, reason):
        o["fails"] += 1
        delay = min(self._retry_max, self._retry_base * (2 ** max(0, o["fails"] - 1)))
        self._stop_locked(o, reason)
        o["retry_after"] = self._now() + delay
        self._say("warning", "[CAM/mp4] %s: %s, повтор через %.0f c", o["key"], reason, delay)

    def _tick_one_locked(self, o):
        now = self._now()
        if o["state"] in (OwnerState.STARTING, OwnerState.LIVE):
            if not o["subs"]:
                if o["idle_since"] is None:
                    o["idle_since"] = now
                elif now - o["idle_since"] >= self._idle_grace:
                    self._stop_locked(o, "смотреть некому")
                return
            o["idle_since"] = None
            if o["state"] == OwnerState.STARTING:
                if o["started_at"] is not None and now - o["started_at"] >= self._first_data_timeout:
                    self._fail_locked(o, "первый фрагмент не пришёл")
            elif o["last_data_at"] is not None and now - o["last_data_at"] >= self._stall_timeout:
                self._fail_locked(o, "поток замер")
            return
        if o["state"] == OwnerState.IDLE and o["subs"]:
            if o["retry_after"] is None or now >= o["retry_after"]:
                self._start_locked(o)

    def _wait_chunk(self, key, sub, timeout):
        """Дождаться следующего куска ДЛЯ ЭТОГО зрителя: сначала шапка, потом фрагменты."""
        deadline = None if timeout is None else self._now() + timeout
        with self._lock:
            while True:
                o = self._owners.get(key)
                if o is None or sub.closed:
                    return None
                if not sub._sent_init:
                    if o["init"] is not None:
                        sub._sent_init = True
                        sub._q.clear()          # зритель начинает с ближайшего целого фрагмента
                        # Alpha 2.879. ЗДЕСЬ БЫЛ ДЕФЕКТ. Очередь очищалась, а признак «жду
                        # ключевой кадр» не возвращался, хотя он уже был снят накопленными
                        # фрагментами. В итоге сразу за шапкой зрителю мог уйти НЕ ключевой
                        # фрагмент: декодировать его не от чего, и картинка стоит до
                        # следующего ключевого кадра — у камер Bambu это до двух секунд.
                        sub._need_key = True
                        return o["init"]
                elif sub._q:
                    return sub._q.popleft()
                if deadline is not None:
                    left = deadline - self._now()
                    if left <= 0:
                        return None
                    self._cond.wait(timeout=left)
                else:
                    self._cond.wait(timeout=1.0)

    def _unsubscribe(self, key, sub):
        with self._lock:
            o = self._owners.get(key)
            if o is None:
                return
            try:
                o["subs"].remove(sub)
            except ValueError:
                pass
            if not o["subs"]:
                o["idle_since"] = self._now()
            self._cond.notify_all()
