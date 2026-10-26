# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841 / этап 3D — проверка сертификата квалификации UI-оснастки.

ДВА РАЗНЫХ ПОНЯТИЯ, которые нельзя путать:

  * **Квалификация ИНСТРУМЕНТА** — подтверждает, что верификатор, драйвер, сторож сети и
    сценарии ведут себя предсказуемо (серия этапа 3C). Она относится к ОСНАСТКЕ и может
    использоваться для проверки будущих изменений продукта. Повторять десять циклов после
    каждой правки продукта не нужно.
  * **Доказательство КОНКРЕТНОЙ задачи** — создаётся заново после каждого изменения:
    это UI-прогоны, доказывающие, что работает именно изменённый кандидат. Из серии 3C
    оно не наследуется никогда.

Квалификацию инструмента аннулирует изменение самой оснастки; изменение `server.py`,
`web/*` или другого продукта её НЕ аннулирует, но требует нового прогона по задаче.

ЧТО ДЕЛАЕТ. Только читает и сравнивает. Ничего не запускает, ничего не изменяет,
абсолютных путей владельца не печатает.

    python tools/validation/ui/verify_qualification.py --json

Статусы: VALID · STALE_TOOLING · STALE_SCENARIOS · STALE_ENVIRONMENT · MISSING · INVALID.
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
CERT_PATH = os.path.join(HERE, "qualification.json")
SCHEMA = "3diwell-ui-qualification-v1"

VALID, STALE_TOOLING, STALE_SCENARIOS = "VALID", "STALE_TOOLING", "STALE_SCENARIOS"
STALE_ENVIRONMENT, MISSING, INVALID = "STALE_ENVIRONMENT", "MISSING", "INVALID"

# Оснастка, чьё изменение аннулирует квалификацию инструмента.
TOOL_FILES = (
    "tools/validation/ui/run_ui_verification.py",
    "tools/validation/ui/_ui_driver.mjs",
    "tools/validation/ui/_stage_server.py",
    "tools/validation/ui/network_guard/sitecustomize.py",
    "tools/validation/ui/select_ui_coverage.py",
    "tools/validation/ui/ui_coverage_map.json",
)
SCENARIO_FILE = "tools/validation/ui/scenarios.json"


def _sha(rel):
    p = os.path.join(REPO, rel)
    return hashlib.sha256(io.open(p, "rb").read()).hexdigest() if os.path.isfile(p) else None


def tool_fingerprints():
    return dict((rel, _sha(rel)) for rel in TOOL_FILES)


def scenario_fingerprint():
    return _sha(SCENARIO_FILE)


def _ps(command):
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                            command], capture_output=True, text=True, shell=False,
                           timeout=40,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (p.stdout or "").strip()
    except Exception:
        return ""


def current_environment():
    node = ""
    npath = r"C:\Program Files\nodejs\node.exe"
    if os.path.isfile(npath):
        try:
            node = subprocess.run([npath, "--version"], capture_output=True, text=True,
                                  shell=False, timeout=20).stdout.strip()
        except Exception:
            node = ""
    engine = next((p for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if os.path.isfile(p)),
        None)
    return {
        "python": ".".join(sys.version.split()[0].split(".")[:2]),
        "python_full": sys.version.split()[0],
        "node_major": (node or "").lstrip("v").split(".")[0] or None,
        "node_full": node or None,
        "windows_build": _ps("(Get-CimInstance Win32_OperatingSystem).Version") or None,
        "engine_version": (_ps("(Get-Item %s).VersionInfo.ProductVersion" %
                               json.dumps(engine)) if engine else None) or None,
    }


def _major(v):
    return str(v or "").split(".")[0]


def load_certificate(path=None):
    p = path or CERT_PATH
    if not os.path.isfile(p):
        return None, "сертификат квалификации отсутствует"
    try:
        cert = json.load(io.open(p, encoding="utf-8"))
    except Exception as e:
        return None, "сертификат не читается: %s" % e
    if not isinstance(cert, dict) or cert.get("schema_version") != SCHEMA:
        return None, "несовместимая схема сертификата"
    for k in ("qualification_id", "source_series_id", "source_series_status",
              "qualified_scenarios", "cycles", "total_runs", "tool_fingerprints",
              "scenario_registry_fingerprint", "environment_policy",
              "qualified_environment", "coverage_units", "source_artifact_digest"):
        if k not in cert:
            return None, "в сертификате нет поля %r" % k
    if cert.get("source_series_status") != "QUALIFIED":
        return None, "сертификат выдан по серии со статусом %r"  % cert.get(
            "source_series_status")
    if int(cert.get("cycles") or 0) < 10 or int(cert.get("total_runs") or 0) < 20:
        return None, "сертификат выдан по неполной серии (%s циклов, %s прогонов)" % (
            cert.get("cycles"), cert.get("total_runs"))
    if cert.get("failed_criteria"):
        return None, "сертификат выдан при невыполненных критериях"
    if int(cert.get("individual_retries") or 0) != 0:
        return None, "сертификат выдан при индивидуальных повторах"
    return cert, ""


def verify(path=None, env=None):
    cert, err = load_certificate(path)
    if cert is None:
        status = MISSING if "отсутствует" in err else INVALID
        return {"schema_version": SCHEMA, "status": status, "reason": err,
                "warnings": [], "qualified_scenarios": [], "coverage_units": []}

    out = {"schema_version": SCHEMA, "status": VALID, "reason": "",
           "qualification_id": cert["qualification_id"],
           "source_series_id": cert["source_series_id"],
           "qualified_scenarios": list(cert["qualified_scenarios"]),
           "coverage_units": list(cert["coverage_units"]),
           "warnings": [], "environment": {}, "changed_tools": []}

    now = tool_fingerprints()
    changed = [rel for rel, h in cert["tool_fingerprints"].items() if now.get(rel) != h]
    missing_new = [rel for rel in now if rel not in cert["tool_fingerprints"]]
    if changed or missing_new:
        out["changed_tools"] = changed + missing_new
        out["status"] = STALE_TOOLING
        out["reason"] = "изменена оснастка: %s" % ", ".join((changed + missing_new)[:4])
        return out

    if scenario_fingerprint() != cert["scenario_registry_fingerprint"]:
        out["status"] = STALE_SCENARIOS
        out["reason"] = "реестр сценариев изменён после квалификации"
        return out

    cur = env or current_environment()
    out["environment"] = cur
    q = cert["qualified_environment"]
    if cur.get("windows_build") and q.get("windows_build") \
            and cur["windows_build"] != q["windows_build"]:
        out["status"] = STALE_ENVIRONMENT
        out["reason"] = "сборка Windows изменилась"
        return out
    if cur.get("python") != q.get("python"):
        out["status"] = STALE_ENVIRONMENT
        out["reason"] = "версия Python изменилась (major.minor)"
        return out
    if cur.get("node_major") != q.get("node_major"):
        out["status"] = STALE_ENVIRONMENT
        out["reason"] = "мажорная версия Node изменилась"
        return out
    if _major(cur.get("engine_version")) != _major(q.get("engine_version")):
        out["status"] = STALE_ENVIRONMENT
        out["reason"] = "мажорная версия движка браузера изменилась"
        return out
    if cur.get("engine_version") != q.get("engine_version"):
        # Патч движка квалификацию не убивает, но молчать об этом нельзя: обновление
        # Edge уже ломало автоматизацию в этом проекте.
        out["warnings"].append("движок браузера обновился в пределах мажорной версии: "
                               "%s -> %s" % (q.get("engine_version"),
                                             cur.get("engine_version")))
    return out


def render(res):
    L = ["=" * 78, "КВАЛИФИКАЦИЯ UI-ОСНАСТКИ", "=" * 78,
         "СТАТУС: %s" % res["status"]]
    if res.get("reason"):
        L.append("причина: %s" % res["reason"])
    if res.get("qualification_id"):
        L.append("сертификат: %s  (серия %s)" % (res["qualification_id"],
                                                 res["source_series_id"]))
    if res.get("qualified_scenarios"):
        L.append("квалифицированные сценарии: %s" % ", ".join(res["qualified_scenarios"]))
    if res.get("coverage_units"):
        L.append("единицы покрытия: %s" % ", ".join(res["coverage_units"]))
    if res.get("changed_tools"):
        L.append("изменённая оснастка: %s" % ", ".join(res["changed_tools"]))
    for w in res.get("warnings", []):
        L.append("   ! %s" % w)
    L.append("")
    L.append("Квалификация относится к ИНСТРУМЕНТУ. Доказательство конкретной задачи —")
    L.append("это отдельные UI-прогоны по изменённому кандидату, и оно не наследуется.")
    return "\n".join(L)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Проверка сертификата квалификации (только чтение).")
    ap.add_argument("--cert")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    res = verify(ns.cert)
    sys.stdout.write((json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True)
                      if ns.json else render(res)) + "\n")
    return 0 if res["status"] == VALID else 2


if __name__ == "__main__":
    sys.exit(main())
