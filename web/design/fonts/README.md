# Шрифты интерфейса

| Файл | Шрифт | Основа | Лицензия |
|---|---|---|---|
| `3diwell-wide-j.woff2`, `3diwell-wide-j-bold.woff2` | 3DIWELL Wide J, 3DIWELL Wide J Bold | Jura, © 2019 The Jura Project Authors, https://github.com/ossobuffo/jura | SIL OFL 1.1 — `OFL-Jura.txt` |
| `3diwell-wide-p-regular.woff2` | 3DIWELL Wide P | Play Regular, © 2011 Jonas Hecksher, Playtypes, e-types AS | SIL OFL 1.1 — `OFL-Play.txt` |
| `3diwell-wide-p-bold.woff2` | 3DIWELL Wide P Bold | Play Bold, © 2011 Jonas Hecksher, Playtypes, e-types AS | SIL OFL 1.1 — `OFL-Play.txt` |

Это изменённые версии (Modified Versions по OFL). Что изменено (Wide P — версия 1.100, Wide J — 1.200, 26.09.2026):

- буквы уменьшены до высоты заглавной прежнего шрифта интерфейса, а средняя длина строки
  подогнана под него — поэтому замена занимает на экране то же место (Wide J — на 7 % больше);
- между буквами добавлен равный промежуток, пробел между словами — как у прежнего шрифта;
- Wide J: обычное начертание — Jura wght 850, жирное — wght 1000 (ось насыщенности продлена по
  тем же приращениям автора; у источника 300–700), буквы на 7 % крупнее прежнего шрифта; без
  своего жирного браузер раздувал буквы сам, и они слипались;
- подгонка контуров под пиксели экрана (hinting) сделана заново программой ttfautohint; у Wide J
  она поднимает строчные до целого пикселя на мелком тексте и ставит штрихи строго по пикселям;
- шрифты переименованы: имя «Play» зарезервировано автором Play, поэтому изменённые шрифты
  называются «3DIWELL Wide …». Уведомления авторов сохранены в самих файлах и в `OFL-*.txt`.

Изменённые шрифты распространяются по той же SIL Open Font License 1.1; MPL 2.0 на них не
распространяется.

Сборка из исходников Google Fonts на закреплённых коммитах (сверка SHA-256), результат повторяется
побайтно:

```bash
python tools/build_ui_fonts.py --download --src <папка вне проекта>
```

Нужны `fonttools`, `brotli` и `ttfautohint-py==0.6.1` — только для сборки.
