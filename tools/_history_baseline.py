# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Эталон из истории git для наборов проверок: где он есть, а где его честно нет.

Часть наборов сверяет текущий код с тем, как было в прошлом коммите («как было до правки»,
«функция не изменилась»). Эталон читается командой `git show <коммит>:<файл>`.

В закрытом репозитории эталон есть всегда. В открытой копии (tools/public_export.py) история
новая, из одного коммита, и прошлых коммитов в ней нет. Тогда исторические проверки не
выполняются, а печатаются как `SKIP — …` с причиной. Все проверки ТЕКУЩЕГО поведения при этом
выполняются как обычно.

Три режима (mode):
  present — все файлы эталона прочитаны: исторические проверки выполняются;
  public  — эталона нет, есть метка открытой копии packaging/PUBLIC_TREE.md И нет первого
            коммита закрытой истории: исторические проверки пропускаются (SKIP);
  missing — всё остальное (закрытый репозиторий с неполной историей, нет git, опечатка
            в хеше): исторические проверки выполняются и краснеют, как раньше.
Двойное условие режима public нужно, чтобы метка, случайно попавшая в закрытое дерево, не
включила пропуски: там первый коммит закрытой истории есть.

Модуль ничего не пишет, в сеть не ходит и зависит только от стандартной библиотеки и git.
"""
import os
import subprocess

# Первый коммит закрытой истории (то же значение, что ROOT_COMMIT в tools/public_export.py).
PRIVATE_ROOT_COMMIT = "c75d652945"
# Метку кладёт только выгрузка открытой копии (tools/public_export.py).
PUBLIC_MARKER = "packaging/PUBLIC_TREE.md"

PRESENT = "present"
PUBLIC = "public"
MISSING = "missing"


def _git(repo, args):
    try:
        return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, timeout=60)
    except Exception:
        return None


def show(repo, rev, rel):
    """Текст файла rel из коммита rev (str) или None, если прочитать нельзя."""
    r = _git(repo, ["show", "%s:%s" % (rev, rel)])
    if r is None or r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace")


def has_commit(repo, rev):
    r = _git(repo, ["cat-file", "-e", "%s^{commit}" % rev])
    return r is not None and r.returncode == 0


def is_public_tree(repo, root_commit=None):
    """Это открытая копия: есть метка выгрузки и нет первого коммита закрытой истории."""
    root_commit = root_commit or PRIVATE_ROOT_COMMIT
    marker = os.path.join(repo, *PUBLIC_MARKER.split("/"))
    return os.path.isfile(marker) and not has_commit(repo, root_commit)


def mode(repo, rev, rels, root_commit=None):
    """present / public / missing — см. описание модуля."""
    if all(show(repo, rev, rel) is not None for rel in rels):
        return PRESENT
    if is_public_tree(repo, root_commit):
        return PUBLIC
    return MISSING


def skip_reason(rev):
    return ("эталон %s — коммит закрытой истории; в открытой копии его нет" % rev)


class Baseline(object):
    """Исторические проверки одного набора.

    hist = Baseline(REPO, PARENT, ["server.py"], check)
    hist.check("H1. …", lambda: <условие>)   # условие вычисляется только при наличии эталона

    check — обычная функция набора check(name, ok): счёт PASS/FAIL остаётся в наборе,
    пропуски копятся в hist.skipped.
    """

    def __init__(self, repo, rev, rels, check, root_commit=None):
        self.repo = repo
        self.rev = rev
        self.rels = list(rels)
        self._check = check
        self.mode = mode(repo, rev, self.rels, root_commit)
        self.skipped = []

    @property
    def present(self):
        return self.mode == PRESENT

    @property
    def public(self):
        return self.mode == PUBLIC

    def show(self, rel):
        """Файл эталона (str) или None — без обращения к git в открытой копии."""
        if self.mode == PUBLIC:
            return None
        return show(self.repo, self.rev, rel)

    def skip(self, name):
        self.skipped.append(name)
        print("SKIP — %s: %s" % (name, skip_reason(self.rev)))

    def check(self, name, thunk):
        """Историческая проверка. В открытой копии — SKIP (thunk не вызывается); иначе
        thunk() вычисляется, исключение считается провалом (FAIL, а не обрыв набора)."""
        if self.mode == PUBLIC:
            self.skip(name)
            return None
        try:
            ok = bool(thunk())
        except Exception as e:  # эталона нет или он неполон — это провал, а не трассировка
            ok = False
            name = "%s [исключение %s]" % (name, type(e).__name__)
        self._check(name, ok)
        return ok

    def summary(self, passed, failed):
        """Итоговые строки набора. failed — число или список имён проваленных проверок.
        -> код выхода (0, если нет FAIL).

        Строка о провале нарочно не начинается с «FAIL:»: гейт считает такие строки
        построчным протоколом и сверяет их число со сводкой ИТОГО."""
        names = list(failed) if isinstance(failed, (list, tuple)) else []
        failed = len(names) if isinstance(failed, (list, tuple)) else int(failed)
        skipped = len(self.skipped)
        if failed:
            print("Провалено %d из %d (пропущено %d):" % (failed, failed + passed, skipped))
            for n in names:
                print("   - %s" % n)
        elif skipped:
            print("\nPASS: пройдено %d, пропущено %d исторических (%s)"
                  % (passed, skipped, skip_reason(self.rev)))
        else:
            print("\nPASS: все %d проверок пройдены" % passed)
        print("ИТОГО: PASS=%d FAIL=%d SKIP=%d" % (passed, failed, skipped))
        return 1 if failed else 0


if __name__ == "__main__":
    #  Селектор проверок запускает изменённый помощник как набор: запуск модуля — это запуск
    #  его собственной проверки tools/test_history_baseline.py.
    import runpy
    runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "test_history_baseline.py"), run_name="__main__")
