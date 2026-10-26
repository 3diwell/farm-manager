# 3DIWELL Farm Manager

Программа управления фермой 3D-принтеров с одного экрана: проекты и детали, очередь и запуск
печати, мониторинг принтеров Bambu Lab, FlashForge, Klipper/Moonraker и других, пользователи с
ролями, резервные копии. Работает на компьютере фермы, без облака и без обязательного интернета.

*English summary below.*

## Что есть в этом репозитории

- **Ядро FM** — сервер (`server.py`, `app/`) и интерфейс в браузере или в собственном окне
  (`web/`). Бесплатное, открытое, лицензия [MPL 2.0](LICENSE).
- **Бесплатные модули** (`modules/`): «Аналитика качества», «Уведомления в мессенджеры»,
  «Оформление и темы» и «Видеостена». Модуль ставится в программе: *Настройки → Модули → Установить*.
- **Основа платных модулей** (`app/licensing/`): проверка подписанных пакетов и лицензий,
  полностью без интернета после активации. Описание —
  [docs/licensing/MODULE_LICENSING_FOUNDATION.md](docs/licensing/MODULE_LICENSING_FOUNDATION.md).
- **Приложение для телефона** (`android/FM_Android_Client/`) — FM Client для Android: принтеры,
  запуск печати, склад по QR и NFC, лицензии через телефон. Сборка — Gradle (JDK 17, Android SDK 35).
- **Демонстрационные модули** (`examples/modules/`) — бесплатный и платный примеры для
  разработчиков модулей.

Платных модулей («Складской учёт», «Расчёт заказа») в репозитории нет: они распространяются
отдельно подписанными сборками; без лицензии в них доступен только просмотр.

## Установка

Готовые установщики для Windows 10/11 (64-разрядная) публикуются в разделе Releases. Установщик
сам ставит недостающие компоненты Windows (.NET Framework, WebView2). Данные фермы хранятся в
`%LOCALAPPDATA%\3DIWELL` и переживают обновление программы.

Инструкции для пользователя — [docs/user/](docs/user/README.md): установка, модули, лицензии,
резервные копии, телефон.

## Запуск из исходников

Нужен Python 3.14.

```bash
python -m pip install -r requirements.txt
python server.py
```

Интерфейс откроется по адресу http://127.0.0.1:8000. Сборка EXE и установщиков —
[docs/dev/building.md](docs/dev/building.md), проверки — [docs/dev/testing.md](docs/dev/testing.md).

Некоторых файлов официальной сборки здесь нет намеренно: программы ffmpeg для камер Bambu Lab и
изображений моделей принтеров (см. [NOTICE.md](NOTICE.md)). Без них программа работает:
значки-заглушки вместо обложек, а для камер Bambu нужно положить `ffmpeg.exe` рядом с `server.py`.

## Лицензия и права

- Собственный код — [Mozilla Public License 2.0](LICENSE); подробности и исключения —
  [NOTICE.md](NOTICE.md).
- Сторонние компоненты — [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Название и логотипы 3DIWELL — товарные знаки, см. [TRADEMARKS.md](TRADEMARKS.md).

## Участие и безопасность

Как сообщить об ошибке и предложить изменение — [CONTRIBUTING.md](CONTRIBUTING.md).
Об уязвимостях — не в открытых обращениях, а как описано в [SECURITY.md](SECURITY.md).

---

## English summary

3DIWELL Farm Manager runs a 3D printer farm from one screen: projects and parts, print queue and
launch, live monitoring of Bambu Lab, FlashForge, Klipper/Moonraker and other printers, users
with roles and backups. It runs on the farm PC with no cloud and no mandatory internet.

This repository holds the free open-source core (MPL 2.0), the free modules (quality analytics,
messenger notifications, appearance and themes, camera wall), the offline signed-module and license foundation for paid
modules, the FM Client Android app (`android/`), and demo modules for module developers. Paid modules are distributed separately under
their own terms.

Run from source with Python 3.14: `python -m pip install -r requirements.txt`, then
`python server.py`, and open http://127.0.0.1:8000. License: [MPL 2.0](LICENSE); see
[NOTICE.md](NOTICE.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and
[TRADEMARKS.md](TRADEMARKS.md). Report vulnerabilities privately as described in
[SECURITY.md](SECURITY.md).
