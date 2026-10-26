# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Печать проектов из приложения — Alpha 2.757.
# ЗАЧЕМ. Владелец включает реальную отправку из интерфейса ОДИН раз (персистентно), это заменяет
# громоздкое одноразовое CLI-вооружение для повседневной работы. Тест доказывает, что механизм:
#   • по умолчанию ВЫКЛЮЧЕН (свежая установка печать не шлёт);
#   • включается ТОЛЬКО из персистентной настройки (переключатель пишет config, применяет предохранители);
#   • при включении открывает три предохранителя для ВСЕХ принтеров фермы; при выключении — безопасный дефолт;
#   • dispatch расходует одноразовое вооружение ТОЛЬКО когда печать из приложения ВЫКЛЮЧЕНА;
#     при включённой — вооружения нет, гейтом служат предохранители + confirmed + clearance + lease;
#   • adapters подключают arm_check ТОЛЬКО когда печать из приложения выключена;
#   • статус отдаёт print_enabled; переключатель НЕ присваивает предохранители из произвольного поля.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_print_enable.py   (0 = пройдено)
import os, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
fail = 0


def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


def blk(a, b):
    i = _SRV.index(a)
    return _SRV[i:_SRV.index(b, i)]


# ── стенд: фейковый _orch, config в памяти, список принтеров ──
class Orch:
    DISPATCH_ENABLED = False
    TRANSPORT_ENABLED = False
    ALLOWED_PRINTER_IDS = frozenset()


CFG = {}          # текущий config (в памяти)
PRINTERS = ['pr1', 'pr2', 'pr3']
WROTE = []        # что записал _write_config


class _Cur:
    def __init__(self, rows): self._rows = rows
    def fetchall(self): return self._rows


class _Conn:
    def execute(self, q, *a): return _Cur([{"id": p} for p in PRINTERS])


class _Lock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


NS = {
    '_orch': Orch, 'lock_pr': _Lock(), 'conn_pr': _Conn(),
    '_read_config': lambda: dict(CFG),
    '_write_config': lambda c: (WROTE.append(dict(c)), True)[1],
    '_ONE_SHOT_ARM': None,
    'log': type('L', (), {'warning': staticmethod(lambda *a, **k: None),
                          'error': staticmethod(lambda *a, **k: None)})(),
    'app': type('A', (), {'post': staticmethod(lambda *a, **k: (lambda f: f)),
                          'get': staticmethod(lambda *a, **k: (lambda f: f))})(),
    'Request': object, '_json_body': None, 'threading': __import__('threading'),
}
# блок «печать из приложения»: от _project_print_enabled до GET transport-status
exec(blk('def _project_print_enabled(', '@app.get("/api/project-orchestrator/transport-status")'), NS)
ppe = NS['_project_print_enabled']
apply_fuses = NS['_apply_project_print_fuses']

# ── A. по умолчанию выключено ──
CFG.clear()
check('A1. без настройки печать из приложения ВЫКЛЮЧЕНА', ppe() is False)
apply_fuses()
check('A2. предохранители остаются выключены/пусты', Orch.DISPATCH_ENABLED is False
      and Orch.TRANSPORT_ENABLED is False and Orch.ALLOWED_PRINTER_IDS == frozenset())

# ── B. включение открывает предохранители для ВСЕХ принтеров ──
CFG['project_print_enabled'] = True
check('B1. настройка прочитана как включённая', ppe() is True)
apply_fuses()
check('B2. КРИТИЧНО: три предохранителя открыты и allowlist = все принтеры фермы',
      Orch.DISPATCH_ENABLED is True and Orch.TRANSPORT_ENABLED is True
      and Orch.ALLOWED_PRINTER_IDS == frozenset(PRINTERS))

# новый принтер после включения тоже попадает в allowlist (повторное применение)
PRINTERS.append('pr4'); apply_fuses()
check('B3. добавленный принтер входит в allowlist при повторном применении',
      'pr4' in Orch.ALLOWED_PRINTER_IDS)
PRINTERS.pop()

# ── C. выключение возвращает безопасный дефолт (нет активного CLI-вооружения) ──
CFG['project_print_enabled'] = False
NS['_ONE_SHOT_ARM'] = None
apply_fuses()
check('C1. КРИТИЧНО: выключение -> предохранители снова выключены/пусты',
      Orch.DISPATCH_ENABLED is False and Orch.TRANSPORT_ENABLED is False
      and Orch.ALLOWED_PRINTER_IDS == frozenset())

# ── C2. выключение НЕ гасит активное CLI-вооружение ──
Orch.DISPATCH_ENABLED = True; Orch.TRANSPORT_ENABLED = True
Orch.ALLOWED_PRINTER_IDS = frozenset({'prX'})
NS['_ONE_SHOT_ARM'] = {'consumed': False}          # активное вооружение
CFG['project_print_enabled'] = False
apply_fuses()
check('C2. КРИТИЧНО: при активном CLI-вооружении выключение печати из приложения его НЕ трогает',
      Orch.DISPATCH_ENABLED is True and Orch.ALLOWED_PRINTER_IDS == frozenset({'prX'}))
NS['_ONE_SHOT_ARM'] = None; apply_fuses()           # прибрать

# ── D. переключатель: пишет ПЕРСИСТЕНТНУЮ настройку, только литеральный true включает ──
_toggle = blk('async def orch_set_print_enabled(', '@app.get("/api/project-orchestrator/transport-status")')
_toggle_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _toggle))
check('D1. переключатель включает только по литеральному true (d.get("enabled") is True)',
      're.' not in _toggle and 'd.get("enabled") is True' in _toggle_code)
check('D2. КРИТИЧНО: переключатель пишет настройку project_print_enabled и вызывает применение',
      "cfg[\"project_print_enabled\"]" in _toggle and '_write_config(cfg)' in _toggle
      and '_apply_project_print_fuses()' in _toggle)
check('D3. КРИТИЧНО: переключатель НЕ присваивает предохранители из произвольного поля напрямую',
      not re.search(r'_orch\.(?:DISPATCH_ENABLED|TRANSPORT_ENABLED|ALLOWED_PRINTER_IDS)\s*=', _toggle_code))

# ── E. dispatch: расход вооружения ТОЛЬКО когда печать из приложения выключена ──
_pd = blk('def _orch_prod_dispatch(', 'def _orch_prod_adapters(')
_pd_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _pd))
check('E1. КРИТИЧНО: расход вооружения обёрнут в «if not _project_print_enabled()»',
      re.search(r'if not _project_print_enabled\(\):\s*\n\s*_ok, _why = _one_shot_arm_consume', _pd_code))
# ── F. adapters: arm_check подключается ТОЛЬКО когда печать из приложения выключена ──
_ad = blk('def _orch_prod_adapters(', '@app.get("/api/projects2/{project_id}/whole-print/preflight")')
_ad_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _ad))
check('F1. КРИТИЧНО: arm_check в adapters под «if not _project_print_enabled()»',
      re.search(r'if not _project_print_enabled\(\):\s*\n\s*a\["arm_check"\] = _one_shot_arm_check', _ad_code))
check('F2. dispatch в adapters есть всегда', '"dispatch": _orch_prod_dispatch' in _ad)

# ── G. статус отдаёт print_enabled ──
check('G1. transport-status отдаёт поле print_enabled из настройки',
      '"print_enabled": _project_print_enabled()' in _SRV)

# ── H. применение вызвано на старте и при сохранении принтеров ──
check('H1. предохранители применяются на старте — вызов apply идёт вскоре ПОСЛЕ разбора вооружения',
      bool(re.search(r'_one_shot_boot_arm\(\)[\s\S]{0,900}_apply_project_print_fuses\(\)', _SRV)))
check('H2. и при сохранении принтеров (обновить allowlist под новый состав)',
      re.search(r'restart_workers\(\)[\s\S]{0,200}_apply_project_print_fuses\(\)', _SRV))

print('\nПРОВАЛЕНО: ' + str(fail) if fail else
      '\nВСЁ ЗЕЛЁНОЕ: печать из приложения выключена по умолчанию; включается только персистентной '
      'настройкой (переключатель пишет config + применяет); открывает предохранители для всех принтеров, '
      'выключение возвращает безопасный дефолт и не трогает активное CLI-вооружение; вооружение '
      'расходуется лишь при выключенной печати из приложения; статус отдаёт print_enabled.')
raise SystemExit(1 if fail else 0)
