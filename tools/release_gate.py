# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841: РЕЛИЗНЫЙ ГЕЙТ с долговечным доказуемым отчётом.

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ В РЕПОЗИТОРИИ. До 2.841 полный прогон делался одноразовым скриптом во
временной папке: он не версионировался, его нельзя было воспроизвести и нечем было проверить.
Релизный контракт не может держаться на неверсионируемом файле.

ЧТО ДОКАЗЫВАЕТ. Для КАЖДОГО тестового файла сохраняются stdout, stderr, время, код возврата и
структурированный результат; итог складывается из этих чисел, а не из подсчёта слов в прозе.
Ноль пропусков доказывается разбором опубликованного формата (tools/_gate_parse.py); файл, чей
формат не распознан, попадает в `unknown` и красит гейт — недоказанное не равно нулю.

ЗАПУСК:
    python tools/release_gate.py                 # полный прогон без исключений
    python tools/release_gate.py --list          # только манифест, ничего не запускать

ОТЧЁТ: C:\\3DIWELL_Builds\\logs\\release_gate_2.841\\<run-id>\\
    manifest.json  results.json  summary.json  runner.log  stdout\\*.log  stderr\\*.log
Отчёт НЕ хранится в репозитории и не попадает в Git.

Код возврата: 0 только если ВСЕ счётчики провалов, пропусков, ошибок, таймаутов, внутренних
сбоев mutation и неизвестных результатов равны нулю И manifest совпал с числом выполненных.
"""
import glob
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _gate_parse import parse_test_output          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = r"C:\Program Files\nodejs\node.exe"
LOG_ROOT = r"C:\3DIWELL_Builds\logs\release_gate_2.841"
PER_FILE_TIMEOUT = 1800.0

# Уборка брошенных headless-движков ПЕРЕД каждым файлом — только свои профили.
#
# Alpha 2.864: в список добавлена метка 'edgeboot_'. Её здесь не было, и это вторая причина
# накопления. Профили с этой меткой заводит test_frontend_boot_and_printer_sort; его
# собственная уборка не работала (отбирала по $_.Path, где метки нет никогда), а подметальщик
# гейта про метку не знал — брошенные движки не подбирал никто. Измерено 22.08.2026: 1035
# процессов msedge, самый старый прожил шесть суток.
#
# ПРАВИЛО НА БУДУЩЕЕ: завёл новый префикс временного профиля — добавь его сюда же. За этим
# следит tools/test_gate_cleanup_and_browser_kill.py.
_SWEEP = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'fm-cdp-' -or "
          "$_.CommandLine -match 'fm_cdp_' -or $_.CommandLine -match 'fm_stage835_' -or "
          "$_.CommandLine -match 'fm-bridge-' -or $_.CommandLine -match 'fm-inv-' -or "
          "$_.CommandLine -match 'edgeboot_') } | "
          "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }")


def gate_tmp_dir():
    """Временная папка дочерних процессов НА ДИСКЕ РЕПОЗИТОРИЯ. -> путь либо "" (не нужна/не вышло).

    ЗАЧЕМ. На рабочей машине владельца TEMP лежит на C:, а репозиторий на D:. Пятнадцать наборов
    из-за этого падали в os.path.relpath («path is on mount 'C:', start on mount 'D:'») ЕЩЁ ДО
    СВОИХ ПРОВЕРОК: они не выполнялись вовсе, а гейт показывал их красными — и настоящая поломка
    внутри них осталась бы незамеченной. Проверка от этой правки НЕ ослабляется: наоборот, наборы
    наконец доходят до собственных проверок (сверено вручную 2026-08-19 — все пятнадцать зелёные
    целиком, когда временная папка на диске репозитория).

    ГДЕ. Рядом с папкой проекта, но имя НЕ начинается с пути репозитория. Это не косметика:
    наборы-песочницы проверяют себя условиями вида «REPO not in ROOT» и «not ROOT.startswith(REPO)»
    (test_project_name_only_folders 100d, test_orchestrator_git_adapter 87, test_desktop_shell 89c,
    fixture_v2 «полигон вне рабочего репозитория»). Каталог с именем «<репозиторий>.gate_tmp»
    содержит путь репозитория как подстроку — 2026-08-19 это уронило семь ранее зелёных наборов.
    Внутрь репозитория временные файлы класть нельзя тем более — их поймает проверка гигиены.

    КОГДА НЕ ВМЕШИВАЕМСЯ. Системный TEMP уже на диске репозитория — ничего не подменяем и
    возвращаем "". Каталог создать не удалось — тоже "": прогон идёт как раньше, а не падает
    из-за собственной оснастки."""
    try:
        if os.path.splitdrive(tempfile.gettempdir())[0].upper() == os.path.splitdrive(ROOT)[0].upper():
            return ""
        d = os.path.join(os.path.dirname(ROOT), "_3diwell_gate_tmp")
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:
        return ""


#  Alpha 2.880: префиксы временных каталогов, которые заводят сами наборы. Список закрытый:
#  убираем ТОЛЬКО своё и ничего чужого. Завёл новый префикс — добавь сюда же, иначе мусор
#  снова начнёт копиться (за этим следит tools/test_gate_cleanup_and_browser_kill.py).
TEST_TMP_PREFIXES = ("fm_", "fm-", "caw-", "caw_", "wsp", "rvb-", "rtm-", "rt-", "ss-",
                     "pw-canon-", "hl-", "frt-", "frm-", "requal", "inv_bulk_test_",
                     "mck_", "gatepurge_")


def purge_system_tmp(older_than=None, tmp_root=None):
    """Убрать каталоги наборов в ФАКТИЧЕСКОЙ временной папке. -> (убрано, осталось).

    ЗАЧЕМ ОТДЕЛЬНО ОТ purge_gate_tmp. Та работает только когда TEMP подменён своей папкой, а
    подмена делается лишь при разных дисках у TEMP и репозитория. После переезда проекта на C:
    подмены нет — и уборки не стало вовсе: 26.08.2026 в системном TEMP насчитано 24 992 каталога
    наборов и 71,6 ГБ. Эта уборка работает всегда и не зависит от раскладки дисков.

    Трогаем только имена из TEST_TMP_PREFIXES. Занятые файлы не считаются ошибкой: попадают в
    «осталось», следующий прогон уберёт их, когда процесс умрёт.
    """
    import shutil
    import stat

    def _force(func, path, _exc):
        #  Каталоги наборов часто содержат рабочие копии git, а объекты git помечены «только
        #  чтение»: обычный rmtree на них падает с «Access is denied» (измерено 26.08.2026 —
        #  так осталось неубранными 24 544 каталога). Снимаем признак и повторяем.
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass

    root = tmp_root or tempfile.gettempdir()
    gone = kept = 0
    try:
        names = os.listdir(root)
    except Exception:
        return (0, 0)
    for name in names:
        if not name.startswith(TEST_TMP_PREFIXES):
            continue
        p = os.path.join(root, name)
        try:
            if older_than is not None and os.path.getmtime(p) >= older_than:
                kept += 1
                continue
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, onerror=_force)
            else:
                os.remove(p)
            if os.path.exists(p):
                kept += 1
            else:
                gone += 1
        except Exception:
            kept += 1
    return (gone, kept)


def purge_gate_tmp(d, older_than=None):
    """Убрать содержимое временной папки наборов. -> (убрано, осталось).

    Alpha 2.864. ПОЧЕМУ ЭТО ПОЯВИЛОСЬ. Папку из gate_tmp_dir() заводили и отдавали дочерним
    процессам как TEMP, но не убирали НИКОГДА — ни до прогона, ни после. Каждый набор,
    создавший временный каталог и не прибравший за собой (или упавший по таймауту), оставлял
    его здесь навсегда. Измерено 22.08.2026: 6591 каталог и 14 ГБ, накопленные за трое суток
    работы. Это не косметика — на машине владельца лежит рабочая ферма, и место на диске
    кончается молча.

    ЧТО УБИРАЕМ. Только СОДЕРЖИМОЕ, сама папка остаётся: её путь уже роздан в TEMP дочерним
    процессам, и удалять её из-под них нельзя.

    older_than — убирать только то, что старше этой отметки времени. Так вызывается ПЕРЕД
    прогоном: чужие свежие файлы (вдруг рядом идёт другой прогон) не трогаем, а мусор
    прошлых прогонов уносим. После своего прогона вызывается без отметки — тогда наше.

    Занятые файлы (их держит зависший процесс) не считаются ошибкой: они попадают в «осталось»,
    прогон из-за них не падает. Следующий прогон уберёт их, когда процесс умрёт.
    """
    if not d or not os.path.isdir(d):
        return (0, 0)
    import shutil
    gone = kept = 0
    for name in os.listdir(d):
        p = os.path.join(d, name)
        try:
            if older_than is not None and os.path.getmtime(p) >= older_than:
                kept += 1
                continue
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            gone += 1
        except Exception:
            kept += 1
    return (gone, kept)


def _safe_name(rel):
    return re.sub(r'[^A-Za-z0-9._-]', '_', rel)


def build_manifest():
    """Манифест полного набора. Исключений нет по построению: берём ВСЁ, что найдено.

    Порядок: сначала обычные наборы, затем mutation proof — они портят файлы репозитория,
    и во время них дерево обязано быть грязным.
    """
    py = sorted(glob.glob(os.path.join(ROOT, "tools", "test_*.py")))
    mjs = sorted(glob.glob(os.path.join(ROOT, "tools", "test_*.mjs")))
    mut = [p for p in py if "mutation_proof" in os.path.basename(p)]
    plain = [p for p in py if "mutation_proof" not in os.path.basename(p)]
    items = ([{"kind": "py", "path": p} for p in plain]
             + [{"kind": "node", "path": p} for p in mjs]
             + [{"kind": "py", "path": p} for p in mut])
    for i, it in enumerate(items, 1):
        it["index"] = i
        it["rel"] = os.path.relpath(it["path"], ROOT).replace("\\", "/")
    return items


def _sweep():
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _SWEEP],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       stdin=subprocess.DEVNULL, timeout=60)
    except Exception:
        pass


def run_one(item, out_dir, env):
    """Запустить ОДИН файл, сохранив stdout и stderr ОТДЕЛЬНО. → structured result."""
    cmd = ([sys.executable, item["path"]] if item["kind"] == "py" else [NODE, item["path"]])
    so_path = os.path.join(out_dir, "stdout", _safe_name(item["rel"]) + ".log")
    se_path = os.path.join(out_dir, "stderr", _safe_name(item["rel"]) + ".log")
    t0 = time.time()
    timed_out = False
    _sweep()
    with io.open(so_path, "wb") as so, io.open(se_path, "wb") as se:
        try:
            pr = subprocess.run(cmd, cwd=ROOT, env=env, stdout=so, stderr=se,
                                stdin=subprocess.DEVNULL, timeout=PER_FILE_TIMEOUT)
            rc = pr.returncode
        except subprocess.TimeoutExpired:
            rc, timed_out = -1000, True
    dt = time.time() - t0
    stdout = io.open(so_path, "rb").read().decode("utf-8", "replace")
    stderr = io.open(se_path, "rb").read().decode("utf-8", "replace")
    res = parse_test_output(item["rel"], stdout, stderr, rc, timed_out, dt)
    res["stdout_log"] = os.path.relpath(so_path, out_dir).replace("\\", "/")
    res["stderr_log"] = os.path.relpath(se_path, out_dir).replace("\\", "/")
    res["manifest_index"] = item["index"]
    return res


def summarize(manifest, results):
    """Прямые счётчики. Ничего не выводится из отсутствия слова."""
    s = {
        "manifest_files": len(manifest),
        "completed_files": len(results),
        "green_files": sum(1 for r in results if r["status"] == "green"),
        "red_files": sum(1 for r in results if r["status"] == "red"),
        "unknown_files": sum(1 for r in results if r["status"] == "unknown"),
        "error_files": sum(1 for r in results if r["error_count"] and not r["timed_out"]),
        "timeout_files": sum(1 for r in results if r["timed_out"]),
        "excluded_files": len(manifest) - len(results),
        "pass_checks": sum(r["pass_count"] for r in results),
        "fail_checks": sum(r["fail_count"] for r in results),
        "skip_checks": sum(r["skip_count"] for r in results),
        "unknown_skip_files": sum(1 for r in results if not r.get("skip_known")),
        "internal_mutation_failures": sum(r["internal_mutation_failures"] for r in results),
        "mutation_not_applied": sum(r["mutation_not_applied"] for r in results),
        "unexpected_green": sum(r["unexpected_green"] for r in results),
        "restore_failures": sum(r["restore_failures"] for r in results),
        "cleanup_failures": sum(r["cleanup_failures"] for r in results),
        "nonzero_rc_files": sum(1 for r in results if r["process_rc"] != 0),
    }
    blockers = ("red_files", "unknown_files", "error_files", "timeout_files", "excluded_files",
                "fail_checks", "skip_checks", "unknown_skip_files",
                "internal_mutation_failures", "mutation_not_applied", "unexpected_green",
                "restore_failures", "cleanup_failures", "nonzero_rc_files")
    s["blocking"] = {k: s[k] for k in blockers if s[k]}
    s["manifest_matches_completed"] = (s["manifest_files"] == s["completed_files"])
    s["process_rc"] = 0 if (not s["blocking"] and s["manifest_matches_completed"]) else 1
    return s


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    manifest = build_manifest()

    if "--list" in sys.argv:
        for it in manifest:
            print("%4d. %-6s %s" % (it["index"], it["kind"], it["rel"]))
        print("всего: %d, исключений: 0" % len(manifest))
        return 0

    run_id = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(LOG_ROOT, run_id)
    for sub in ("", "stdout", "stderr"):
        d = os.path.join(out_dir, sub)
        if not os.path.isdir(d):
            os.makedirs(d)
    runner_log = io.open(os.path.join(out_dir, "runner.log"), "w",
                         encoding="utf-8", newline="\n")

    def say(msg):
        print(msg, flush=True)
        runner_log.write(msg + "\n")
        runner_log.flush()

    with io.open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": "3diwell-gate-manifest-v1", "run_id": run_id,
                   "files": [{"index": i["index"], "kind": i["kind"], "rel": i["rel"]}
                             for i in manifest], "excluded": []},
                  fh, ensure_ascii=False, indent=1)

    say("МАНИФЕСТ: %d файлов, исключений: 0" % len(manifest))
    say("отчёт: %s" % out_dir)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    _tmp = gate_tmp_dir()
    if _tmp:
        env["TEMP"] = env["TMP"] = env["TMPDIR"] = _tmp
        say("временная папка наборов: %s (системный TEMP на другом диске — часть наборов там не выполняется)" % _tmp)
        # Alpha 2.864: убрать мусор ПРОШЛЫХ прогонов. Отметка времени — «сейчас»: всё, что
        # старше начала этого прогона, принадлежит завершённым прогонам. Свежее не трогаем,
        # чтобы не выдернуть файлы из-под возможного соседнего прогона.
        _g, _k = purge_gate_tmp(_tmp, older_than=time.time())
        if _g or _k:
            say("временная папка: убрано от прошлых прогонов %d, занято и оставлено %d" % (_g, _k))
    #  Alpha 2.880: уборка системной временной папки идёт ВСЕГДА, а не только при подмене TEMP.
    #  Иначе она не делается вовсе, когда TEMP и репозиторий на одном диске: 26.08.2026 так
    #  накопилось 24 992 каталога наборов и 71,6 ГБ.
    _sg, _sk = purge_system_tmp(older_than=time.time() - 86400.0)
    if _sg or _sk:
        say("временная папка системы: убран мусор прошлых прогонов — %d, оставлено %d" % (_sg, _sk))

    results = []
    res_path = os.path.join(out_dir, "results.json")
    t0 = time.time()
    try:
        for it in manifest:
            r = run_one(it, out_dir, env)
            results.append(r)
            # Инкрементальная запись: аварийное прекращение не теряет уже готовое.
            with io.open(res_path, "w", encoding="utf-8") as fh:
                json.dump({"schema": "3diwell-gate-results-v1", "run_id": run_id,
                           "results": results}, fh, ensure_ascii=False, indent=1)
            say("%-7s %4d/%d %-58s %7.1f c  rc=%-5d pass=%-4d fail=%-3d skip=%-3d src=%s"
                % (r["status"].upper(), it["index"], len(manifest), os.path.basename(it["rel"]),
                   r["duration_seconds"], r["process_rc"], r["pass_count"], r["fail_count"],
                   r["skip_count"], r["counts_source"]))
            for n in r["notes"]:
                say("        ! %s" % n)
    finally:
        # Alpha 2.864: убрать за СОБОЙ. Именно finally: прогон прерывают с клавиатуры и он падает
        # по исключению — раньше в обоих случаях мусор оставался навсегда. Отметки времени нет:
        # прогон закончен, всё в папке — наше.
        if _tmp:
            _g, _k = purge_gate_tmp(_tmp)
            say("временная папка: убрано за собой %d, занято и оставлено %d" % (_g, _k))
        #  Alpha 2.880: и системная временная папка тоже. Отметка «старше десяти минут» выбрана
        #  так, чтобы унести мусор СВОЕГО прогона (он длится часами) и не тронуть каталоги
        #  набора, который прямо сейчас может идти в соседнем окне.
        _sg2, _sk2 = purge_system_tmp(older_than=time.time() - 600.0)
        if _sg2:
            say("временная папка системы: убрано %d, занято и оставлено %d" % (_sg2, _sk2))

    s = summarize(manifest, results)
    s["run_id"] = run_id
    s["schema"] = "3diwell-gate-summary-v1"
    s["duration_seconds"] = round(time.time() - t0, 1)
    with io.open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(s, fh, ensure_ascii=False, indent=1, sort_keys=True)

    say("\n" + "=" * 92)
    say(json.dumps({k: s[k] for k in (
        "manifest_files", "completed_files", "green_files", "red_files", "unknown_files",
        "error_files", "timeout_files", "excluded_files", "pass_checks", "fail_checks",
        "skip_checks", "unknown_skip_files", "internal_mutation_failures",
        "mutation_not_applied", "unexpected_green", "restore_failures", "cleanup_failures",
        "process_rc")}, ensure_ascii=False, indent=1))
    if s["blocking"]:
        say("БЛОКИРУЮЩИЕ СЧЁТЧИКИ: %s" % json.dumps(s["blocking"], ensure_ascii=False))
        for r in results:
            if r["status"] != "green":
                say("  %-7s %s  %s" % (r["status"].upper(), r["test_file"],
                                       "; ".join(r["notes"])[:160]))
    runner_log.close()
    return s["process_rc"]


if __name__ == "__main__":
    sys.exit(main())
