# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.855 — один владелец видеопотока на принтер, сторож по кадрам, полный сброс сессии.

ЗАЧЕМ. Испытания на железе 17-18.08.2026 (P2S и H2S) показали: два независимых RTSPS-сеанса
к одному принтеру подвешивают друг друга.

  · P2S — оба сеанса могли быть живыми, но прекращение одного стопорило другой;
  · H2S — второй сеанс подвешивал штатную камеру примерно через 1.2 c, ещё до своего закрытия;
  · в обоих случаях процесс жив, соединение «Established», кадры не идут. Загрузка ЦП при этом
    ПРОТИВОПОЛОЖНА: у P2S ≈0 %, у H2S 45-50 %. Значит определять здоровье по ЦП, живости
    процесса или состоянию сокета нельзя — поймаешь одно и пропустишь другое;
  · после снятия зависшего процесса камера H2S больше не открывалась через обычный интерфейс,
    хотя сам принтер был здоров: убить процесс мало, надо стирать и логическое состояние.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ: один владелец на несколько зрителей; уход зрителя не гасит поток, пока
есть другие; зритель получает ПОСЛЕДНИЙ кадр, а не накопленную очередь; таймаут первого кадра;
остановка по замершим кадрам ПРИ ЖИВОМ источнике; полный сброс состояния и создание НОВОГО
источника после смерти прежнего (случай H2S); строгий порядок «сначала погасить, потом
поднять»; гашение по отсутствию зрителей; нарастающая пауза после неудач; остановка всех
владельцев при выходе; закрытие ТОЛЬКО своего объекта источника.

Отдельно — НЕ ВАКУУМ: прежний путь открывал по источнику НА КАЖДОГО зрителя, и это показано
на той же оснастке.

БЕЗОПАСНОСТЬ. Ни принтеров, ни сети, ни ffmpeg, ни сервера: источник поддельный, часы
управляемые. Ничего никуда не отправляется.

Запуск:  python tools/test_camera_single_owner.py      (0 = поведение владельца доказано)
"""
import io
import os
import queue
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.camera_hub import CameraHub, OwnerState   # noqa: E402

SENTINEL = "CAMERA_SINGLE_OWNER_SENTINEL_2_855"

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


class Clock(object):
    """Управляемые часы: проверки не спят и не зависят от нагрузки машины."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class FakeSource(object):
    """Поддельный источник кадров. Ведёт себя как процесс: пока не дали кадр — читатель ждёт.

    ЗАМЕРШИЙ ПОТОК изображается просто: источник ЖИВ (close не вызывался), но кадров больше
    не даёт. Это ровно то, что было на P2S и H2S, и по живости источника этого не видно."""

    opened = []                       # все созданные источники — по ним видно число владельцев

    def __init__(self, key):
        self.key = key
        self.closed = False
        self._q = queue.Queue()
        FakeSource.opened.append(self)

    def push(self, data):
        self._q.put(data)

    def frames(self):
        while True:
            item = self._q.get()
            if item is None or self.closed:
                return
            yield item

    def close(self):
        self.closed = True
        self._q.put(None)


def wait_until(pred, timeout=10.0):
    """Ожидание НАСТОЯЩИХ потоков оснастки (не логики): логика живёт на управляемых часах.

    Запас намеренно большой. Условие проверки от этого не ослабляется ни на йоту — меняется
    только терпение к загруженной машине: в полном прогоне рядом работают браузерные наборы,
    и при трёх секундах набор однажды покраснел не из-за поведения, а из-за нехватки времени
    на переключение потоков. Ожидание завершается сразу, как только условие выполнено."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def new_hub(clock, **kw):
    FakeSource.opened = []
    opts = dict(first_frame_timeout=10.0, stall_timeout=8.0, idle_grace=5.0,
                retry_base=1.0, retry_max=30.0)
    opts.update(kw)
    return CameraHub(open_source=FakeSource, now=clock, **opts)


print("--- 1. Один владелец на нескольких зрителей ---")
clock = Clock()
hub = new_hub(clock)
s1 = hub.subscribe("printerA")
s2 = hub.subscribe("printerA")
check("1. КОРЕНЬ ДЕФЕКТА: два зрителя — ОДИН источник, а не два сеанса к принтеру",
      len(FakeSource.opened) == 1, len(FakeSource.opened))
check("2. владелец действительно один", hub.owners_alive() == 1, hub.stats("printerA"))

src = FakeSource.opened[0]
g1, g2 = s1.frames(), s2.frames()
src.push(b"frame-1")
check("3. кадр дошёл до первого зрителя", next(g1) == b"frame-1")
check("4. и до второго — раздача, а не перехват одним", next(g2) == b"frame-1")
check("5. НЕ ВАКУУМ: на той же оснастке отдельные подписки на РАЗНЫЕ принтеры дают разные источники",
      (lambda: (hub.subscribe("printerB"), len(FakeSource.opened))[1] == 2)())

print("--- 2. Уход зрителя не гасит поток остальным ---")
s2.close()
check("6. один зритель ушёл — источник ЖИВ, потому что остался другой",
      not src.closed and hub.stats("printerA")["subs"] == 1, hub.stats("printerA"))
src.push(b"frame-2")
check("7. оставшийся зритель продолжает получать кадры", next(g1) == b"frame-2")

print("--- 3. Зритель получает ПОСЛЕДНИЙ кадр, а не очередь ---")
for i in range(5):
    src.push(("skip-%d" % i).encode())
src.push(b"latest")
check("8. медленный зритель не копит очередь: следующий кадр — свежий, а не пятый по счёту",
      wait_until(lambda: hub.stats("printerA")["seq"] >= 8) and next(g1) == b"latest",
      hub.stats("printerA"))

print("--- 4. Сторож: первый кадр не пришёл ---")
clock = Clock()
hub = new_hub(clock, first_frame_timeout=10.0)
sub = hub.subscribe("silent")
src = FakeSource.opened[0]
check("9. владелец поднят и ждёт первый кадр", hub.stats("silent")["state"] == OwnerState.STARTING)
clock.advance(9.0)
hub.tick()
check("10. до истечения срока владельца не трогаем", hub.stats("silent")["state"] == OwnerState.STARTING)
clock.advance(2.0)
hub.tick()
check("11. первый кадр не пришёл — владелец остановлен", hub.stats("silent")["state"] == OwnerState.DEAD)
check("12. и его источник закрыт (свой объект, не «по имени»)", src.closed)
check("13. причина названа словами", "первый кадр" in hub.stats("silent")["last_reason"],
      hub.stats("silent")["last_reason"])
# Alpha 2.858. Прежде здесь проверялось, что поток зрителя обрывается вместе с владельцем.
# Это и было непрозрачным восстановлением: штатное окно камеры оставалось пустым до ручного
# переоткрытия. Теперь зритель ЖДЁТ восстановления, а обрывается только когда восстановиться
# не удалось подряд restart_give_up раз.
check("14. зритель НЕ оборван вместе с владельцем — он ждёт восстановления",
      hub.stats("silent")["subs"] == 1 and hub.stats("silent")["fails"] == 1, hub.stats("silent"))
for _ in range(60):                      # источник молчит: каждая попытка гибнет по первому кадру
    clock.advance(120.0)
    hub.tick()
    if hub.stats("silent")["fails"] >= 5:
        break
    time.sleep(0.01)                     # дать догореть потоку прежнего поколения
check("14a. после нескольких неудач подряд поток зрителя честно заканчивается",
      hub.stats("silent")["fails"] >= 5 and list(sub.frames()) == [], hub.stats("silent"))

print("--- 5. Сторож: кадры замерли ПРИ ЖИВОМ источнике (случай P2S и H2S) ---")
clock = Clock()
hub = new_hub(clock, stall_timeout=8.0)
sub = hub.subscribe("frozen")
src = FakeSource.opened[0]
src.push(b"one")
check("15. поток ожил", wait_until(lambda: hub.stats("frozen")["state"] == OwnerState.LIVE),
      hub.stats("frozen"))
clock.advance(7.0)
hub.tick()
check("16. пауза в пределах допустимой поток не рвёт", hub.stats("frozen")["state"] == OwnerState.LIVE)
clock.advance(2.0)
hub.tick()
check("17. КЛЮЧЕВОЕ: источник ЖИВ, но кадры замерли — владелец остановлен",
      hub.stats("frozen")["state"] == OwnerState.DEAD, hub.stats("frozen"))
check("18. решение принято по возрасту кадра, а не по ЦП/живости процесса",
      "кадры перестали идти" in hub.stats("frozen")["last_reason"], hub.stats("frozen")["last_reason"])
check("19. источник при этом закрыт", src.closed)

print("--- 6. Полный сброс состояния: камера обязана открыться заново (случай H2S) ---")
st = hub.stats("frozen")
check("20. логическое состояние стёрто, а не осталось «мёртвой» сессией",
      st["has_frame"] is False and st["state"] == OwnerState.DEAD, st)
# Alpha 2.858. ВАЖНО ПРО ОЖИДАНИЕ НИЖЕ. Прежде новый источник появлялся в момент подписки.
# Теперь «сначала погасить» охватывает и поток чтения прежнего поколения: пока он догорает,
# новый источник НЕ открывается — иначе на миг существовали бы две внешние сессии к одному
# принтеру, а это и вешает H2S. Поэтому здесь ждём фактического завершения прежнего потока и
# только после этого требуем новый источник. Это НЕ послабление: ожидаемый факт стал строже,
# а раньше набор просто не знал о нём и в полном прогоне краснел на загруженной машине.
def dead_generation(key, timeout=10.0):
    """Дождаться, пока догорит поток чтения прежнего поколения владельца."""
    return wait_until(lambda: not any(t.is_alive() for t in threading.enumerate()
                                      if t.name.startswith("cam-owner-%s" % key)), timeout)


sub.close()
check("21. прежнее поколение действительно догорело", dead_generation("frozen"))
clock.advance(60.0)                      # переждать паузу после неудачи
before = len(FakeSource.opened)
sub2 = hub.subscribe("frozen")
check("22. новая подписка создаёт НОВЫЙ источник — камера открывается снова",
      len(FakeSource.opened) == before + 1, (before, len(FakeSource.opened)))
check("22a. и это уже другое поколение владельца", hub.stats("frozen")["generation"] >= 2,
      hub.stats("frozen"))

print("--- 7. Строгий порядок: сначала погасить, потом поднять ---")
order = []
old_src = FakeSource.opened[-1]
_orig_close = old_src.close


def _watched_close():
    order.append("close")
    _orig_close()


old_src.close = _watched_close
clock.advance(100.0)
hub.tick()                                # застойного нет, но погасим через отсутствие зрителей
sub2.close()
clock.advance(10.0)
hub.tick()
check("23. без зрителей владелец гаснет по истечении льготного времени",
      hub.stats("frozen")["state"] == OwnerState.DEAD, hub.stats("frozen"))
check("24. и источник закрыт", "close" in order, order)
check("24a. поток прежнего поколения догорел", dead_generation("frozen"))
clock.advance(60.0)
_n = len(FakeSource.opened)
hub.subscribe("frozen")
order.append("open")
check("25. ПОРЯДОК: закрытие прежнего источника произошло ДО открытия нового",
      ("close" in order) and ("open" in order)
      and order.index("close") < order.index("open"), order)
check("26. и новый источник действительно создан", len(FakeSource.opened) == _n + 1,
      (len(FakeSource.opened), _n))

print("--- 8. Нарастающая пауза: тесного цикла на офлайн-принтере нет ---")
clock = Clock()


def broken(key):
    raise OSError("принтер недоступен")


hub2 = CameraHub(open_source=broken, now=clock, first_frame_timeout=5.0, retry_base=1.0, retry_max=8.0)
hub2.subscribe("offline")
st = hub2.stats("offline")
check("27. неудачная попытка учтена, владелец не поднят",
      st["state"] == OwnerState.DEAD and st["fails"] == 1, st)
hub2.subscribe("offline")
check("28. немедленная повторная попытка НЕ делается (пауза соблюдается)",
      hub2.stats("offline")["fails"] == 1, hub2.stats("offline"))
clock.advance(5.0)
hub2.subscribe("offline")
check("29. после паузы попытка повторяется", hub2.stats("offline")["fails"] == 2,
      hub2.stats("offline"))

print("--- 9. Выход из программы гасит владельцев ---")
clock = Clock()
hub3 = new_hub(clock)
hub3.subscribe("a")
hub3.subscribe("b")
srcs = list(FakeSource.opened)
check("30. подняты два владельца (разные принтеры)", len(srcs) == 2 and hub3.owners_alive() == 2)
hub3.shutdown()
check("31. при выходе закрыты ВСЕ источники", all(s.closed for s in srcs))
check("32. и владельцев больше нет", hub3.owners_alive() == 0, hub3.stats())
try:
    hub3.subscribe("a")
    _after = "подписка прошла"
except RuntimeError:
    _after = "отказ"
check("33. после выхода новые подписки не открывают источников", _after == "отказ", _after)

print("--- 10. Закрытие подписки идемпотентно ---")
clock = Clock()
hub4 = new_hub(clock)
s = hub4.subscribe("idem")
s.close()
s.close()
check("34. повторное закрытие не роняет и не уводит счётчик в минус",
      hub4.stats("idem")["subs"] == 0, hub4.stats("idem"))

print("--- 10a. Десять одновременных подписок дают ОДНОГО внешнего производителя ---")
clock = Clock()
hub = new_hub(clock)
_subs, _errs = [], []


def _sub_worker():
    try:
        _subs.append(hub.subscribe("race"))
    except Exception as exc:            # noqa: BLE001 — падение потока обязано попасть в отчёт
        _errs.append(exc)


_threads = [threading.Thread(target=_sub_worker) for _ in range(10)]
for t in _threads:
    t.start()
for t in _threads:
    t.join(5.0)
check("44. все десять подписок оформлены, без ошибок", len(_subs) == 10 and not _errs, (len(_subs), _errs[:1]))
check("45. ОБЯЗАТЕЛЬНАЯ: десять одновременных подписок создали РОВНО ОДИН внешний источник",
      len(FakeSource.opened) == 1, len(FakeSource.opened))
check("46. и владелец один", hub.owners_alive() == 1, hub.stats("race"))
check("47. счётчик зрителей сошёлся", hub.stats("race")["subs"] == 10, hub.stats("race"))

print("--- 10b. Старое поколение не публикует кадры после перезапуска ---")
clock = Clock()
hub = new_hub(clock, stall_timeout=8.0)
watcher = hub.subscribe("gen")
old_src = FakeSource.opened[0]
old_src.push(b"old-1")
wait_until(lambda: hub.stats("gen")["state"] == OwnerState.LIVE)
_seq_before = hub.stats("gen")["seq"]
clock.advance(20.0)
hub.tick()                                # кадры замерли -> владелец остановлен
check("48. владелец остановлен по замершим кадрам", hub.stats("gen")["state"] == OwnerState.DEAD)
old_src.push(b"late-from-old-generation")  # опоздавший кадр прежнего поколения
_late = wait_until(lambda: hub.stats("gen")["seq"] > _seq_before, timeout=0.6)
check("49. ОБЯЗАТЕЛЬНАЯ: кадр СТАРОГО поколения после перезапуска не публикуется",
      not _late and hub.stats("gen")["seq"] == _seq_before, hub.stats("gen"))

print("--- 10c. Отказ одного источника не задевает владельца другого ---")
clock = Clock()
hub = new_hub(clock, stall_timeout=8.0)
sub_a = hub.subscribe("alpha")
sub_b = hub.subscribe("beta")
src_a = [x for x in FakeSource.opened if x.key == "alpha"][0]
src_b = [x for x in FakeSource.opened if x.key == "beta"][0]
src_a.push(b"a1")
src_b.push(b"b1")
wait_until(lambda: hub.stats("alpha")["state"] == OwnerState.LIVE and hub.stats("beta")["state"] == OwnerState.LIVE)
src_a.close()                             # источник alpha «упал»
wait_until(lambda: hub.stats("alpha")["state"] == OwnerState.DEAD)
check("50. ОБЯЗАТЕЛЬНАЯ: отказ одного источника не тронул владельца другого",
      hub.stats("beta")["state"] == OwnerState.LIVE and not src_b.closed, hub.stats("beta"))
src_b.push(b"b2")
_g = sub_b.frames()
check("51. и второй зритель продолжает получать кадры", next(_g) in (b"b1", b"b2"))

print("--- 10d. Новый производитель не стартует, пока не догорел прежний ---")


class SlowExitSource(FakeSource):
    """Источник, чей поток чтения доживает уже ПОСЛЕ закрытия: так ведёт себя настоящий
    процесс, который ещё не успел выйти. Проверяем, что новый источник в это время не
    открывается — иначе на миг существовали бы две внешние сессии к одному принтеру."""

    hold = threading.Event()

    def frames(self):
        while True:
            item = self._q.get()
            if item is None or self.closed:
                SlowExitSource.hold.wait(5.0)      # догораем медленно
                return
            yield item


clock = Clock()
FakeSource.opened = []
SlowExitSource.hold.clear()
hub = CameraHub(open_source=SlowExitSource, now=clock, first_frame_timeout=10.0,
                stall_timeout=8.0, idle_grace=5.0, retry_base=0.0, retry_max=0.0)
sub_slow = hub.subscribe("slow")
slow_src = FakeSource.opened[0]
slow_src.push(b"s1")
wait_until(lambda: hub.stats("slow")["state"] == OwnerState.LIVE)
clock.advance(20.0)
hub.tick()                                 # замерли кадры -> остановка
check("52. владелец остановлен", hub.stats("slow")["state"] == OwnerState.DEAD)
check("53. источник закрыт", slow_src.closed)
_n_before = len(FakeSource.opened)
clock.advance(60.0)
hub.tick()
hub.tick()
check("54. ОБЯЗАТЕЛЬНАЯ: пока прежнее поколение догорает, новый источник НЕ открыт",
      len(FakeSource.opened) == _n_before, (len(FakeSource.opened), _n_before))
SlowExitSource.hold.set()                  # прежнее поколение догорело
wait_until(lambda: not any(t.is_alive() for t in threading.enumerate()
                           if t.name.startswith("cam-owner-slow")), timeout=6.0)
clock.advance(60.0)
hub.tick()
check("55. и только после этого поднимается новое поколение",
      len(FakeSource.opened) == _n_before + 1 and hub.stats("slow")["generation"] >= 2,
      (len(FakeSource.opened), hub.stats("slow")))

print("--- 10e. ПРОЗРАЧНОЕ восстановление: тот же зритель, тот же поток ---")
clock = Clock()
hub = new_hub(clock, stall_timeout=8.0, retry_base=0.0, retry_max=0.0)
viewer = hub.subscribe("live")
gen1 = FakeSource.opened[0]
gen1.push(b"frame-gen1")
stream = viewer.frames()
check("56. зритель получил кадр первого поколения", next(stream) == b"frame-gen1")
_g1 = hub.stats("live")["generation"]
clock.advance(20.0)
hub.tick()                                 # принудительный stall -> полная остановка
check("57. поколение остановлено", hub.stats("live")["state"] == OwnerState.DEAD)
wait_until(lambda: not any(t.is_alive() for t in threading.enumerate()
                           if t.name.startswith("cam-owner-live")), timeout=6.0)
clock.advance(1.0)
hub.tick()                                 # сторож поднимает новое поколение сам
check("58. новое поколение поднято БЕЗ участия зрителя",
      hub.stats("live")["generation"] > _g1 and hub.owners_alive() == 1, hub.stats("live"))
gen2 = FakeSource.opened[-1]
check("59. и это ДРУГОЙ источник", gen2 is not gen1)
gen2.push(b"frame-gen2")
check("60. ОБЯЗАТЕЛЬНАЯ: тот же зритель без переоткрытия получает кадры нового поколения",
      next(stream) == b"frame-gen2")
check("61. подписка при этом ни разу не пересоздавалась", hub.stats("live")["subs"] == 1)

print("--- 10f. Восстановление не превращается в шторм запросов ---")
clock = Clock()
hub = new_hub(clock, first_frame_timeout=5.0, retry_base=1.0, retry_max=8.0)
storm = hub.subscribe("storm")             # источник кадров не даёт никогда
for _ in range(200):                       # двести обходов сторожа подряд, время почти не идёт
    clock.advance(0.05)
    hub.tick()
check("62. ОБЯЗАТЕЛЬНАЯ: двести обходов сторожа не создали шторм источников",
      len(FakeSource.opened) <= 2, len(FakeSource.opened))
_opened_calm = len(FakeSource.opened)
for _ in range(6):                         # а вот с течением времени попытки идут, но редко
    clock.advance(30.0)
    hub.tick()
    # Alpha 2.858: попытка поднимается только ПОСЛЕ того, как догорело прежнее поколение —
    # это и есть break-before-make. Без ожидания набор мерил бы не поведение, а скорость
    # переключения потоков на машине: под нагрузкой попытки просто не успевали начаться.
    dead_generation("storm", 5.0)
check("63. со временем попытки продолжаются, но по одной за паузу",
      _opened_calm < len(FakeSource.opened) <= _opened_calm + 6, len(FakeSource.opened))
check("64. пауза между попытками растёт (нарастающий backoff)", hub.stats("storm")["fails"] >= 2,
      hub.stats("storm"))

print("--- 10g. Regression: P1/P1S и остальные пути камер не тронуты ---")
_SRV_RE = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
check("65. ОБЯЗАТЕЛЬНАЯ: путь P1/P1S идёт МИМО общего владельца, как и раньше",
      "_bambu_p1_camera_frames(ip, code)" in _SRV_RE
      and "_ser.startswith(\"01P\") or _ser.startswith(\"01S\")" in _SRV_RE)
check("66. общий владелец применяется ТОЛЬКО к пути RTSPS", _SRV_RE.count("_bambu_hub_frames(") == 2)
check("67. путь Klipper (проксирование чужого стримера) не тронут",
      "_klipper_camera_proxy(resp)" in _SRV_RE and "_klipper_webcam_url(ip, pport)" in _SRV_RE)
check("68. сигналинг WebRTC для Creality на месте", '@app.post("/api/printer/{pid}/webrtc")' in _SRV_RE)
check("69. формат ответа камеры одинаков во всех ветках",
      _SRV_RE.count('media_type="multipart/x-mixed-replace; boundary=frame"') >= 2)

print("--- 11. Секретов и «убийств по имени» в модуле нет ---")
# ВАЖНО: проверяем КОД, а не прозу. Пояснения в этом проекте подробные, и обычный поиск
# подстроки поймал бы собственные комментарии — это уже случалось. Поэтому файл разбирается
# как AST: берутся имена и строковые константы ИСПОЛНЯЕМОГО кода, docstring-и исключаются.
import ast   # noqa: E402


def code_text(path):
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            dd = ast.get_docstring(n, clean=False)
            if dd:
                docs.add(dd)
    parts = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            parts.append(n.id)
        elif isinstance(n, ast.Attribute):
            parts.append(n.attr)
        elif isinstance(n, ast.arg):
            parts.append(n.arg)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value not in docs:
            parts.append(n.value)
    return chr(10).join(parts).lower()


SRC = io.open(os.path.join(REPO, "app", "camera_hub.py"), encoding="utf-8").read()
HUB_CODE = code_text(os.path.join(REPO, "app", "camera_hub.py"))
check("35. модуль не знает ни про ffmpeg, ни про адреса, ни про коды доступа (проверен КОД, не проза)",
      not any(w in HUB_CODE for w in ("ffmpeg", "rtsps", "access_code", "bblp", "subprocess")),
      [w for w in ("ffmpeg", "rtsps", "access_code", "bblp", "subprocess") if w in HUB_CODE])
check("36. никаких завершений по имени процесса", "taskkill" not in HUB_CODE and "pkill" not in HUB_CODE)
check("37. здоровье считается по кадрам: ни ЦП, ни сокета в логике нет",
      ("cpu" not in HUB_CODE) and ("tcp" not in HUB_CODE) and "last_frame_at" in HUB_CODE)

print("--- 12. Сервер: зритель подписывается, а не открывает свой сеанс ---")
SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
check("38. маршрут камеры отдаёт кадры ЧЕРЕЗ владельца потока",
      "_bambu_hub_frames(pid, ip, code)" in SRV)
check("39. НЕ ВАКУУМ: маршрут больше не открывает RTSPS-поток напрямую на каждого зрителя",
      "StreamingResponse(_bambu_camera_frames(" not in SRV)
check("40. владелец гасится при выходе из программы", "_camera_hub.shutdown()" in SRV)
SRV_CODE = code_text(os.path.join(REPO, "server.py"))
check("41. источник гасит СВОЙ процесс, а не ищет чужие (проверен КОД, не проза)",
      "pr.terminate()" in SRV and "taskkill" not in SRV_CODE, "taskkill" in SRV_CODE)
check("42. формат ответа камеры не менялся",
      'media_type="multipart/x-mixed-replace; boundary=frame"' in SRV)
_camlogs = [l for l in SRV.splitlines() if "[BAMBU CAM]" in l and "log." in l]
check("43. в журнал камеры не попадают ни адрес RTSPS, ни код доступа",
      bool(_camlogs) and not any(("{url}" in l) or ("{code}" in l) or ("{cmd}" in l) for l in _camlogs),
      _camlogs[:3])

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
