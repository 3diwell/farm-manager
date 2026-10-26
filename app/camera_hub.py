# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.855 — ОДИН владелец видеопотока на принтер и раздача кадров зрителям.

ЗАЧЕМ. До этого каждый зритель камеры открывал СВОЁ подключение к принтеру: открыли камеру
в двух местах — два процесса ffmpeg и два независимых RTSPS-сеанса к одному аппарату.
Испытания на железе (P2S и H2S, 17-18.08.2026) показали, что так делать нельзя:

  · P2S: два сеанса могли жить одновременно, но закрытие одного ЗАСТОПОРИВАЛО другой;
  · H2S: второй сеанс подвешивал первый примерно через 1.2 с, ещё до своего закрытия;
  · в обоих случаях процесс был жив, соединение «Established», а кадры идти переставали —
    то есть по живости процесса и по загрузке ЦП здоровье определять НЕЛЬЗЯ: у P2S зависший
    поток давал ≈0 % ЦП, у H2S — 45-50 %. Признаки противоположны, вывод один.
  · после снятия зависшего процесса штатная камера H2S больше НЕ открывалась заново, хотя сам
    принтер был здоров и отдельный свежий сеанс сразу получал кадры. Значит убить процесс мало —
    надо сбрасывать и ЛОГИЧЕСКОЕ состояние сеанса.

ЧТО ДЕЛАЕТ ЭТОТ МОДУЛЬ.

  Принтер ──> ОДИН владелец потока ──> текущий кадр ──┬── обычная камера
                                                      ├── стена камер
                                                      └── любой другой зритель

  · один владелец на принтер, сколько бы зрителей ни было;
  · уход зрителя не гасит владельца, пока остались другие;
  · зритель всегда получает ПОСЛЕДНИЙ кадр: медленный зритель пропускает промежуточные и
    не отращивает очередь в памяти;
  · сторож считает здоровье ТОЛЬКО по движению кадров: не пришёл первый кадр за отведённое
    время либо кадры перестали идти — владелец останавливается целиком;
  · перезапуск строго «сначала погасить, потом поднять»: новый владелец не создаётся, пока
    прежний не остановлен полностью (поток дождан, источник закрыт, состояние стёрто);
  · при отсутствии зрителей владелец гаснет по истечении льготного времени;
  · повторные неудачи разводятся нарастающей паузой, без тесного цикла на офлайн-принтере.

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО. Модуль не знает ни про ffmpeg, ни про адреса, ни про коды доступа:
источник кадров передаётся снаружи фабрикой. Поэтому здесь нечего логировать из секретов,
и весь модуль проверяется тестами без принтеров, без сети и без сервера.

БЕЗОПАСНОСТЬ ЗАВЕРШЕНИЯ. Модуль закрывает ТОЛЬКО свой собственный объект источника. Никаких
завершений «по имени процесса» — это правило проекта и оно здесь не нарушается.
"""
import threading
import time

__all__ = ["CameraHub", "OwnerState", "log_key"]


def log_key(value):
    """Ключ владельца потока для журнала. У Bambu ключ — «адрес|код доступа» (12.10.2026: код попадал в
    farm.log, который владелец отправляет разработке кнопкой «Скачать журнал»). В журнал идёт только
    адрес — часть до «|»; ключ без «|» (адрес потока FlashForge) остаётся как есть."""
    s = str(value)
    return s.split("|", 1)[0] + "|…" if "|" in s else s


class OwnerState(object):
    """Состояния владельца потока. Строковые — чтобы их можно было писать в журнал как есть."""
    STARTING = "starting"      # источник создан, первого кадра ещё не было
    LIVE = "live"              # кадры идут
    STOPPING = "stopping"      # гасим; новый владелец не создаётся, пока не догашен
    DEAD = "dead"              # остановлен, состояние стёрто


class _Subscription(object):
    """Подписка одного зрителя. Отдаёт ПОСЛЕДНИЙ кадр, а не накопленную очередь."""

    def __init__(self, hub, key):
        self._hub = hub
        self._key = key
        self._closed = False
        self._seen = 0

    @property
    def closed(self):
        return self._closed

    def frames(self, timeout=None):
        """Генератор кадров. Отдаёт каждый НОВЫЙ кадр владельца; пропущенные промежуточные
        не накапливаются. Завершается, когда подписку закрыли либо владелец умер."""
        while True:
            item = self._hub._wait_frame(self._key, self._seen, timeout)
            if item is None or self._closed:
                return
            self._seen, data = item
            yield data

    def close(self):
        """Идемпотентно: повторный вызов ничего не ломает (зритель может уйти как угодно)."""
        if self._closed:
            return
        self._closed = True
        self._hub._unsubscribe(self._key)


class CameraHub(object):
    """Реестр владельцев потока: один владелец на ключ (принтер), раздача кадров зрителям.

    open_source(key) -> объект источника с методами:
        frames() — генератор байтов кадра (по одному целому кадру за раз);
        close()  — закрыть СВОЙ ресурс (процесс/сокет). Обязан быть идемпотентным.

    Пороги заданы явно и обоснованы:
      first_frame_timeout — сколько ждём ПЕРВЫЙ кадр, прежде чем признать попытку неудачной;
      stall_timeout       — сколько терпим тишину после того, как кадры уже шли;
      idle_grace          — сколько владелец живёт без зрителей (быстрый повторный вход
                            не должен дёргать принтер новым сеансом);
      retry_base/retry_max — нарастающая пауза между попытками поднять владельца.

    now — источник времени (монотонный). В тестах подменяется, поэтому проверки не спят.
    """

    def __init__(self, open_source, first_frame_timeout=15.0, stall_timeout=10.0,
                 idle_grace=5.0, retry_base=1.0, retry_max=30.0, restart_give_up=5,
                 now=None, log=None, can_start=None):
        self._open_source = open_source
        self._first_frame_timeout = float(first_frame_timeout)
        self._stall_timeout = float(stall_timeout)
        self._idle_grace = float(idle_grace)
        self._retry_base = float(retry_base)
        self._retry_max = float(retry_max)
        # Сколько неудачных попыток подряд терпит ЗРИТЕЛЬ, прежде чем его поток честно
        # завершится. Ноль означал бы «держим соединение вечно на выключенном принтере».
        self._restart_give_up = int(restart_give_up)
        #  Alpha 2.886: право на внешний поток. Спрашивается ПЕРЕД подъёмом источника.
        #  Пока право у другого пути показа (тот же принтер, другой раздатчик), источник
        #  не поднимается вовсе — иначе у принтера окажется два соединения с камерой,
        #  а он держит одно.
        self._can_start = can_start
        self._now = now or time.monotonic
        self._log = log
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._owners = {}
        self._shutdown = False

    # ── внутреннее ───────────────────────────────────────────────────────────────────────
    def _say(self, level, msg, *args):
        if self._log is None:
            return
        try:
            #  12.10.2026: любой строковый аргумент с «|» — это ключ «адрес|код»; код в журнал не идёт.
            getattr(self._log, level)(msg, *[log_key(a) if isinstance(a, str) and "|" in a else a for a in args])
        except Exception:
            pass

    def _blank(self, key):
        return {"key": key, "state": OwnerState.DEAD, "source": None, "thread": None,
                "seq": 0, "frame": None, "started_at": None, "last_frame_at": None,
                "subs": 0, "generation": 0, "stop": False, "fails": 0, "retry_after": None,
                "last_reason": "", "prev_thread": None}

    def _owner(self, key):
        o = self._owners.get(key)
        if o is None:
            o = self._blank(key)
            self._owners[key] = o
        return o

    # ── публичное ────────────────────────────────────────────────────────────────────────
    def subscribe(self, key):
        """Подписать зрителя. Владелец поднимается, только если его ещё нет.

        ВАЖНО: если прежний владелец в состоянии STOPPING, новый здесь НЕ создаётся — это и есть
        «сначала погасить, потом поднять». Зритель дождётся кадра или уйдёт по таймауту."""
        key = str(key)
        with self._lock:
            if self._shutdown:
                raise RuntimeError("camera hub is shut down")
            o = self._owner(key)
            o["subs"] += 1
            if o["state"] == OwnerState.DEAD:
                self._start_locked(o)
            return _Subscription(self, key)

    def stats(self, key=None):
        """Снимок состояния для журнала и тестов. Секретов здесь нет — только счётчики."""
        with self._lock:
            def one(o):
                return {"key": o["key"], "state": o["state"], "subs": o["subs"], "seq": o["seq"],
                        "generation": o["generation"], "fails": o["fails"],
                        "has_frame": o["frame"] is not None,
                        "last_frame_at": o["last_frame_at"], "started_at": o["started_at"],
                        "last_reason": o["last_reason"]}
            if key is not None:
                o = self._owners.get(str(key))
                return one(o) if o else None
            return {k: one(v) for k, v in self._owners.items()}

    def owners_alive(self):
        """Сколько владельцев сейчас держат источник. Для тестов и диагностики."""
        with self._lock:
            return sum(1 for o in self._owners.values()
                       if o["state"] in (OwnerState.STARTING, OwnerState.LIVE))

    def tick(self):
        """Один проход сторожа: первый кадр, замершие кадры, простой без зрителей, пауза перед
        повтором. Вызывается фоновым потоком владельца процесса и НАПРЯМУЮ в тестах —
        поэтому проверки не зависят от реального времени."""
        with self._lock:
            for o in list(self._owners.values()):
                self._tick_one_locked(o)

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
        """Погасить всех владельцев при выходе программы. Идемпотентно."""
        with self._lock:
            self._shutdown = True
            keys = list(self._owners)
        for k in keys:
            with self._lock:
                o = self._owners.get(k)
                if o and o["state"] in (OwnerState.STARTING, OwnerState.LIVE, OwnerState.STOPPING):
                    self._stop_locked(o, "выход программы")
        with self._lock:
            self._cond.notify_all()

    # ── жизненный цикл владельца ─────────────────────────────────────────────────────────
    def _start_locked(self, o):
        """Поднять владельца. Вызывается ТОЛЬКО когда прежний уже мёртв (см. subscribe/_tick).

        Alpha 2.858: «сначала погасить» теперь означает И поток чтения прежнего поколения, а не
        только его процесс. Источник закрывается с ожиданием фактического выхода процесса, но
        поток чтения может ещё доживать в своём finally. Пока он жив, новый источник НЕ
        открывается — иначе на короткое время существовали бы две внешние сессии к одному
        принтеру, а именно это и подвешивает H2S. Ждать здесь нельзя (поток доживает под этим же
        замком — получилось бы взаимное ожидание), поэтому просто откладываем до следующего
        обхода сторожа: он приходит раз в секунду."""
        #  Alpha 2.886: право на внешний поток — в единственном месте подъёма (см. camera_fmp4).
        if self._can_start is not None and not self._can_start(o["key"]):
            return
        if o["state"] != OwnerState.DEAD:
            return
        prev = o.get("prev_thread")
        if prev is not None:
            if prev.is_alive():
                return                 # прежнее поколение ещё догорает — не поднимаем новое
            o["prev_thread"] = None
        now = self._now()
        if o["retry_after"] is not None and now < o["retry_after"]:
            return                     # пауза после неудачи — не дёргаем принтер тесным циклом
        try:
            src = self._open_source(o["key"])
        except Exception as exc:
            self._fail_locked(o, "источник не открылся: %s" % type(exc).__name__)
            return
        o["source"] = src
        o["state"] = OwnerState.STARTING
        o["started_at"] = now
        o["last_frame_at"] = None
        o["frame"] = None
        o["stop"] = False
        o["generation"] += 1
        gen = o["generation"]
        t = threading.Thread(target=self._pump, args=(o["key"], gen, src),
                             name="cam-owner-%s-%d" % (log_key(o["key"]), gen), daemon=True)
        o["thread"] = t
        self._say("info", "[CAM] %s: владелец потока поднят (попытка %d, зрителей %d)",
                  o["key"], gen, o["subs"])
        t.start()

    def _pump(self, key, gen, src):
        """Поток владельца: тянет кадры из источника и публикует ПОСЛЕДНИЙ.
        Не держит замок во время чтения — иначе чтение из процесса блокировало бы всех."""
        reason = "источник закончился"
        try:
            for frame in src.frames():
                with self._lock:
                    o = self._owners.get(key)
                    if o is None or o["generation"] != gen or o["stop"]:
                        break                      # это уже чужое поколение — молча уходим
                    o["frame"] = frame
                    o["seq"] += 1
                    o["last_frame_at"] = self._now()
                    if o["state"] == OwnerState.STARTING:
                        o["state"] = OwnerState.LIVE
                        o["fails"] = 0
                        o["retry_after"] = None
                        self._say("info", "[CAM] %s: первый кадр получен, поток живой", key)
                    self._cond.notify_all()
        except Exception as exc:
            reason = "источник упал: %s" % type(exc).__name__
        finally:
            with self._lock:
                o = self._owners.get(key)
                if o is not None and o["generation"] == gen and o["state"] != OwnerState.DEAD:
                    self._stop_locked(o, reason)

    def _stop_locked(self, o, reason):
        """Полная остановка: источник закрыт, поток отпущен, ЛОГИЧЕСКОЕ состояние стёрто.

        Стирание состояния — не формальность. На H2S снятие процесса без сброса состояния
        оставляло камеру навсегда закрытой: программа считала, что владелец ещё есть."""
        if o["state"] == OwnerState.DEAD:
            return
        o["state"] = OwnerState.STOPPING
        o["stop"] = True
        src, subs, key = o["source"], o["subs"], o["key"]
        self._say("info", "[CAM] %s: владелец потока остановлен — %s (зрителей %d)", key, reason, subs)
        try:
            if src is not None:
                src.close()                        # ТОЛЬКО свой источник, никаких kill по имени
        except Exception:
            self._say("debug", "[CAM] %s: закрытие источника дало ошибку (проигнорировано)", key)
        # логический сброс: всё, что могло удержать «мёртвую» сессию, обнуляется.
        # Поток чтения не забываем совсем, а перекладываем в prev_thread: по нему _start_locked
        # убеждается, что прежнее поколение догорело, прежде чем открывать новый источник.
        o["source"] = None
        o["prev_thread"] = o["thread"]
        o["thread"] = None
        o["frame"] = None
        o["last_frame_at"] = None
        o["started_at"] = None
        o["state"] = OwnerState.DEAD
        o["last_reason"] = reason
        self._cond.notify_all()

    def _fail_locked(self, o, reason):
        """Неудачная попытка: считаем и разводим паузой. Тесного цикла на офлайн-принтере нет."""
        o["fails"] += 1
        delay = min(self._retry_max, self._retry_base * (2 ** max(0, o["fails"] - 1)))
        o["retry_after"] = self._now() + delay
        o["last_reason"] = reason
        self._say("info", "[CAM] %s: %s; следующая попытка не раньше чем через %.0f c",
                  o["key"], reason, delay)
        self._cond.notify_all()

    def _tick_one_locked(self, o):
        now = self._now()
        if o["state"] == OwnerState.STARTING:
            if o["started_at"] is not None and now - o["started_at"] >= self._first_frame_timeout:
                self._stop_locked(o, "первый кадр не пришёл")
                self._fail_locked(o, "первый кадр не пришёл")
            return
        if o["state"] == OwnerState.LIVE:
            # ЕДИНСТВЕННЫЙ признак здоровья — возраст последнего кадра. Ни ЦП, ни живость
            # процесса, ни состояние сокета: на P2S и H2S они показывали противоположное.
            if o["last_frame_at"] is not None and now - o["last_frame_at"] >= self._stall_timeout:
                self._stop_locked(o, "кадры перестали идти")
                self._fail_locked(o, "кадры перестали идти")
                return
            if o["subs"] <= 0:
                if o.get("idle_since") is None:
                    o["idle_since"] = now
                elif now - o["idle_since"] >= self._idle_grace:
                    o["idle_since"] = None
                    self._stop_locked(o, "зрителей не осталось")
            else:
                o["idle_since"] = None
            return
        # Alpha 2.858: ПРОЗРАЧНОЕ ВОССТАНОВЛЕНИЕ. Пока у владельца остались зрители, сторож
        # поднимает его заново сам. Прежде поток зрителя завершался вместе с владельцем, и
        # штатное окно камеры оставалось пустым до ручного переоткрытия — восстановление не было
        # прозрачным. Теперь HTTP-поток зрителя не рвётся: он просто ждёт кадров нового
        # поколения. «Сначала погасить, потом поднять» при этом не ослаблено — _start_locked
        # поднимается только из состояния DEAD и только когда догорел поток прежнего поколения.
        if o["state"] == OwnerState.DEAD and o["subs"] > 0 and not self._shutdown:
            self._start_locked(o)

    # ── подписка ─────────────────────────────────────────────────────────────────────────
    def _wait_frame(self, key, seen, timeout):
        """Дождаться кадра НОВЕЕ seen. -> (seq, кадр) либо None, если ждать больше нечего.

        Alpha 2.858: смена поколения владельца зрителя НЕ роняет. Номер кадра сквозной и при
        остановке не сбрасывается, поэтому кадр нового поколения просто оказывается новее того,
        что зритель уже видел, и приходит в тот же HTTP-поток. Ждать бесконечно тоже нельзя:
        если восстановиться не удаётся (принтер выключен), после restart_give_up неудачных
        попыток подряд поток зрителя честно заканчивается, и браузер сам решает, просить ли
        картинку снова."""
        deadline = None if timeout is None else self._now() + float(timeout)
        with self._cond:
            while True:
                o = self._owners.get(key)
                if o is None or self._shutdown:
                    return None
                if o["seq"] > seen and o["frame"] is not None:
                    return (o["seq"], o["frame"])
                if o["subs"] <= 0:
                    return None          # подписчиков не осталось — держать поток не для кого
                if o["fails"] >= self._restart_give_up:
                    return None          # восстановиться не выходит — отпускаем зрителя
                if deadline is not None and self._now() >= deadline:
                    return None
                self._cond.wait(0.2)

    def _unsubscribe(self, key):
        with self._lock:
            o = self._owners.get(key)
            if o is None:
                return
            o["subs"] = max(0, o["subs"] - 1)
            if o["subs"] == 0:
                o["idle_since"] = self._now()
            self._cond.notify_all()
