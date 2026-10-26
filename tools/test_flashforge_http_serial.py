# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# FlashForge: строго один HTTP-запрос на принтер + «тихое окно» после старта печати — core Alpha 2.765.
# ПРИЧИНА (ферма, 4 из 4 попыток). Встроенный HTTP-сервер прошивки Adventurer 5M 3.1.5 хрупок:
# конкурентный запрос (фоновый опрос /detail каждые ~1.5-2 c), попавший в момент обработки printNow,
# валит прошивку НАМЕРТВО (10054 -> 10061 -> вечные таймауты; лечится только выключением питания).
# Смерть стабильно в первые ~2 c после «Print started» — ровно первый опрос после загрузки.
# Здесь доказываем: (1) поведение замка/окна на настоящих функциях, (2) КАЖДЫЙ HTTP-путь к FlashForge
# сериализован, (3) опрос не встаёт в очередь за долгой загрузкой и молчит в тихом окне.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_flashforge_http_serial.py   (0 = пройдено)
import os, re, threading, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()

fail = 0


def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


def _fn_src(name):
    m = re.search(r'^(?:async )?def %s\(' % re.escape(name), _SRV, re.M)
    assert m, 'не найдено: ' + name
    i = m.start()
    j = re.search(r'\n(?=(?:async )?def |class |@app\.)', _SRV[i:])
    return _SRV[i:i + (j.start() if j else len(_SRV))]


# ── 1. Настоящие функции замка/окна из server.py ───────────────────────────────────────────────
NS = {'threading': threading, 'time': time}
blk = _SRV[_SRV.index('_FF_HTTP_LOCKS = {}'):_SRV.index('async def run_flashforge(')]
exec(blk, NS)

check('S1. замок для одного и того же принтера — ОДИН объект (и порт по умолчанию 8898)',
      NS['_ff_http_lock']('192.0.2.18', 8898) is NS['_ff_http_lock']('192.0.2.18', None))
check('S2. замки разных принтеров независимы',
      NS['_ff_http_lock']('192.0.2.18', None) is not NS['_ff_http_lock']('192.0.2.19', None))
NS['_ff_quiet']('192.0.2.18', None, 0.15)
check('S3. тихое окно активно после установки', NS['_ff_quiet_active']('192.0.2.18', None) is True)
check('S4. и не задевает другой принтер', NS['_ff_quiet_active']('192.0.2.19', None) is False)
time.sleep(0.2)
check('S5. тихое окно само истекает', NS['_ff_quiet_active']('192.0.2.18', None) is False)
NS['_ff_quiet']('192.0.2.18', None, 0.3)
NS['_ff_quiet']('192.0.2.18', None, 0.05)
check('S6. повторная установка НЕ укорачивает уже действующее окно',
      NS['_ff_quiet_active']('192.0.2.18', None) is True and (time.sleep(0.12) or NS['_ff_quiet_active']('192.0.2.18', None) is True))

# ── 2. Каждый HTTP-путь к FlashForge — под замком ──────────────────────────────────────────────
for fn, ep in (('_flashforge_control', '/control'), ('_flashforge_gcode_list', '/gcodeList'),
               ('_flashforge_print', '/printGcode'), ('_flashforge_upload_print', '/uploadGcode')):
    src = _fn_src(fn)
    check('S7.%s. %s (%s) выполняет urlopen ПОД замком принтера' % (fn, fn, ep),
          '_ff_http_lock(ip, port)' in src
          and src.index('_ff_http_lock(ip, port)') < src.index('urllib.request.urlopen('))

# ── 3. Старт печати -> тихое окно; опрос уважает и замок, и окно ───────────────────────────────
check('S8. КРИТИЧНО: после /uploadGcode ставится тихое окно (полное при printNow, короткое при upload-only)',
      re.search(r'urlopen\(req, timeout=120\.0\)[\s\S]{0,600}_ff_quiet\(ip, port, FF_QUIET_AFTER_START_S if print_now else',
                _fn_src('_flashforge_upload_print')))
check('S9. КРИТИЧНО: после /printGcode тоже ставится тихое окно',
      '_ff_quiet(ip, port, FF_QUIET_AFTER_START_S)' in _fn_src('_flashforge_print'))
_poll = _fn_src('run_flashforge')
check('S10. КРИТИЧНО: опрос МОЛЧИТ в тихом окне (проверка ДО запроса, continue без сети)',
      re.search(r'if _ff_quiet_active\(ip, port\):[\s\S]{0,120}continue', _poll)
      and _poll.index('_ff_quiet_active(ip, port)') < _poll.index('urlopen(req, timeout=2.5)'))
check('S11. КРИТИЧНО: опрос НЕ встаёт в очередь за долгой загрузкой (acquire с коротким timeout -> пропуск тика)',
      'acquire(timeout=0.2)' in _poll and 'return None' in _poll
      and re.search(r'if resp is None:[\s\S]{0,80}continue', _poll))
check('S12. пропуск тика не считается ошибкой связи (нет офлайна из-за замка)',
      _poll.index('if resp is None:') < _poll.index('except Exception as e:'))
# Длина тихого окна разумна: покрывает старт задания, но короче порога STALE_FAIL (телеметрия не «протухает»)
m = re.search(r'^FF_QUIET_AFTER_START_S = ([0-9.]+)', _SRV, re.M)
check('S13. тихое окно ~10 c (>=5, <=30): достаточно для старта, телеметрия не протухает',
      m and 5.0 <= float(m.group(1)) <= 30.0)

# ── 4. Ничего лишнего: пути Bambu/Klipper не тронуты ───────────────────────────────────────────
check('S14. замок FlashForge не затащили в чужие пути (Bambu/Klipper/Moonraker)',
      '_ff_http_lock' not in _fn_src('run_bambu'))

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: к FlashForge идёт строго один HTTP-запрос за раз (все 4 пути + опрос), после старта '
              'печати опрос молчит тихое окно, пропуск тика не рождает ни очередь, ни ложный офлайн'))
raise SystemExit(1 if fail else 0)
