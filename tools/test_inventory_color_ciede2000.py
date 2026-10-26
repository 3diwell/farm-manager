# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# CIEDE2000 + перцептивная сверка цветов катушки — inventory 1.7.22.
# Проверяет РЕАЛЬНЫЕ хелперы из modules/inventory/backend.py (без БД и без core):
#   • ΔE00 против ЭТАЛОННОГО набора Sharma/Wu/Dalal (2005), Table 1 — 34 пары, точность 1e-4.
#     Это единственная защита от «тихо неправильной» формулы: CIEDE2000 легко реализовать почти верно.
#   • sRGB -> linear -> XYZ(D65) -> Lab: опорные цвета (белый/чёрный/красный).
#   • _inv_color_compare: exact/close/far, порог ΔE00 = 5.0, регистр и формат HEX не влияют,
#     невалидный HEX с любой стороны -> (None, None) (цвет не сравнивается).
# Запуск: python tools/test_inventory_color_ciede2000.py   (0 = пройдено)
import importlib.util, os, sys, logging

logging.disable(logging.CRITICAL)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('inv_backend', os.path.join(REPO, 'modules', 'inventory', 'backend.py'))
inv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inv)

fail = 0
def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1

# ── Эталон Sharma/Wu/Dalal (2005), Table 1: L1,a1,b1, L2,a2,b2, ожидаемый ΔE00 ──
SHARMA = [
    (50.0000, 2.6772, -79.7751, 50.0000, 0.0000, -82.7485, 2.0425),
    (50.0000, 3.1571, -77.2803, 50.0000, 0.0000, -82.7485, 2.8615),
    (50.0000, 2.8361, -74.0200, 50.0000, 0.0000, -82.7485, 3.4412),
    (50.0000, -1.3802, -84.2814, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -1.1848, -84.8006, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -0.9009, -85.5211, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, 0.0000, 0.0000, 50.0000, -1.0000, 2.0000, 2.3669),
    (50.0000, -1.0000, 2.0000, 50.0000, 0.0000, 0.0000, 2.3669),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0009, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0010, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0011, 7.2195),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0012, 7.2195),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0009, -2.4900, 4.8045),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0010, -2.4900, 4.8045),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0011, -2.4900, 4.7461),
    (50.0000, 2.5000, 0.0000, 50.0000, 0.0000, -2.5000, 4.3065),
    (50.0000, 2.5000, 0.0000, 73.0000, 25.0000, -18.0000, 27.1492),
    (50.0000, 2.5000, 0.0000, 61.0000, -5.0000, 29.0000, 22.8977),
    (50.0000, 2.5000, 0.0000, 56.0000, -27.0000, -3.0000, 31.9030),
    (50.0000, 2.5000, 0.0000, 58.0000, 24.0000, 15.0000, 19.4535),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.1736, 0.5854, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.2972, 0.0000, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 1.8634, 0.5757, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.2592, 0.3350, 1.0000),
    (60.2574, -34.0099, 36.2677, 60.4626, -34.1751, 39.4387, 1.2644),
    (63.0109, -31.0961, -5.8663, 62.8187, -29.7946, -4.0864, 1.2630),
    (61.2901, 3.7196, -5.3901, 61.4292, 2.2480, -4.9620, 1.8731),
    (35.0831, -44.1164, 3.7933, 35.0232, -40.0716, 1.5901, 1.8645),
    (22.7233, 20.0904, -46.6940, 23.0331, 14.9730, -42.5619, 2.0373),
    (36.4612, 47.8580, 18.3852, 36.2715, 50.5065, 21.2231, 1.4146),
    (90.8027, -2.0831, 1.4410, 91.1528, -1.6435, 0.0447, 1.4441),
    (90.9257, -0.5406, -0.9208, 88.6381, -0.8985, -0.7239, 1.5381),
    (6.7747, -0.2908, -2.4247, 5.8714, -0.0985, -2.2286, 0.6377),
    (2.0776, 0.0795, -1.1350, 0.9033, -0.0636, -0.5514, 0.9082),
]
worst = 0.0
bad = []
for L1, a1, b1, L2, a2, b2, exp in SHARMA:
    got = inv._inv_delta_e2000((L1, a1, b1), (L2, a2, b2))
    d = abs(got - exp)
    worst = max(worst, d)
    if d > 1e-4:
        bad.append((L1, a1, b1, L2, a2, b2, exp, round(got, 4)))
check('C1. ΔE00 совпал со ВСЕМИ %d эталонными парами Sharma (макс. отклонение %.6f)' % (len(SHARMA), worst), not bad)
for b in bad:
    print('     ожидали %.4f, получили %.4f для %s' % (b[6], b[7], b[:6]))
check('C2. ΔE00 симметричен (dE(a,b) == dE(b,a))',
      all(abs(inv._inv_delta_e2000((L1, a1, b1), (L2, a2, b2)) - inv._inv_delta_e2000((L2, a2, b2), (L1, a1, b1))) < 1e-9
          for L1, a1, b1, L2, a2, b2, _ in SHARMA))
check('C3. ΔE00 к самому себе = 0', all(inv._inv_delta_e2000((L1, a1, b1), (L1, a1, b1)) < 1e-12
                                        for L1, a1, b1, _, _, _, _ in SHARMA))

# ── sRGB -> Lab: опорные значения ──
def close(got, exp, eps=0.02):
    return got is not None and all(abs(g - e) <= eps for g, e in zip(got, exp))
check('L1. белый #FFFFFF -> L*=100, a*=b*=0', close(inv._inv_hex_to_lab('#FFFFFF'), (100.0, 0.0, 0.0)))
check('L2. чёрный #000000 -> L*=0, a*=b*=0', close(inv._inv_hex_to_lab('#000000'), (0.0, 0.0, 0.0)))
check('L3. красный #FF0000 -> L*≈53.24, a*≈80.09, b*≈67.20', close(inv._inv_hex_to_lab('#FF0000'), (53.24, 80.09, 67.20), 0.05))
check('L4. средний серый #808080 -> нейтраль (a*≈0, b*≈0), L*≈53.59',
      close(inv._inv_hex_to_lab('#808080'), (53.59, 0.0, 0.0), 0.05))
check('L5. невалидный/пустой вход -> None',
      inv._inv_hex_to_lab('') is None and inv._inv_hex_to_lab(None) is None and inv._inv_hex_to_lab('#GGGGGG') is None)

# ── _inv_color_compare: exact / close / far, порог 5.0 ──
d_exact, r_exact = inv._inv_color_compare('#FF0000', '#FF0000')
check('R1. точный HEX -> distance=0, relation=exact', d_exact == 0.0 and r_exact == 'exact')
d1, r1 = inv._inv_color_compare('#FF0000', '#FE0000')
check('R2. соседний оттенок (ΔE00 мал) -> relation=close, distance>0', r1 == 'close' and 0 < d1 <= 5.0)
d2, r2 = inv._inv_color_compare('#C12E1F', '#FF0000')
check('R3. заметно другой красный -> relation=far (ΔE00 > 5)', r2 == 'far' and d2 > 5.0)
d3, r3 = inv._inv_color_compare('#FF0000', '#00FF00')
check('R4. красный vs зелёный -> far', r3 == 'far' and d3 > 50)
check('R5. невалидный HEX с ЛЮБОЙ стороны -> (None, None): цвет не сравнивается',
      inv._inv_color_compare('#FF0000', None) == (None, None) and inv._inv_color_compare('', '#FF0000') == (None, None)
      and inv._inv_color_compare(None, None) == (None, None))
check('R6. регистр/формат HEX не влияет (после штатной нормализации)',
      inv._inv_color_compare(inv._inv_norm_hex('ff0000'), inv._inv_norm_hex('#FF0000')) == (0.0, 'exact')
      and inv._inv_color_compare(inv._inv_norm_hex('FF0000AA'), inv._inv_norm_hex('#ff0000')) == (0.0, 'exact'))
# граница порога: подбираем пару вокруг 5.0 и проверяем, что классификация идёт строго по ΔE00
near = inv._inv_color_compare('#FF0000', '#F51505')
check('R7. классификация строго по порогу ΔE00=5.0 (<=5 близкий, >5 отличается)',
      (near[1] == 'close') == (near[0] <= 5.0) and inv._INV_COLOR_CLOSE_DE == 5.0)
check('R8. sRGB-каналы НЕ используются как метрика (ΔE00 нелинеен по HEX): '
      'равный шаг в HEX даёт разное ΔE00 в тёмной и светлой зоне',
      inv._inv_color_compare('#000000', '#101010')[0] != inv._inv_color_compare('#EFEFEF', '#FFFFFF')[0])

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: CIEDE2000 совпадает с эталоном Sharma (34/34), sRGB->Lab верен, сверка цветов даёт '
              'exact/close/far по порогу ΔE00=5.0, невалидный HEX цвет не сравнивает'))
sys.exit(1 if fail else 0)
