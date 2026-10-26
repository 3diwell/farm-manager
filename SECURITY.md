# Сообщить об уязвимости

Нашли уязвимость в 3DIWELL Farm Manager или его модулях — пожалуйста, **не публикуйте её в
открытых обращениях (Issues), обсуждениях и чатах**. Напишите напрямую, закрытым каналом.

## Куда писать (по порядку)

1. **GitHub — приватное сообщение об уязвимости** (Private vulnerability reporting): вкладка
   *Security* открытого репозитория → кнопка *Report a vulnerability*. Канал появится после
   публикации открытого репозитория; сообщение видят только его владельцы.
2. **Telegram:** @Sup3DiwellBot — личное сообщение в техподдержку 3DIWELL. Работает уже сейчас и
   подходит, если первый канал недоступен.

Что приложить: версию программы (окно «О программе»), что именно происходит, шаги, по которым
это повторяется, и чем это грозит. **Не присылайте** настоящие коды доступа принтеров, пароли,
токены, файлы лицензий и резервные копии с данными фермы — хватит описания или выдуманных
значений.

## Сроки

- **Подтверждение получения** — не позже 7 дней.
- **Исправление критичной уязвимости** — цель 30 дней с подтверждения. Если нужно больше,
  сообщим, почему и когда ждать.
- Сообщим, когда выйдет исправленная версия. Пока исправления нет, просим не раскрывать
  подробности публично.

## Что считается уязвимостью

Например: доступ к ферме или данным без входа, повышение прав, выполнение чужого кода, обход
проверки подписи пакета модуля или лицензии, утечка кодов доступа принтеров или токенов.

## Поддерживаемые версии

| Версия | Исправления безопасности |
|---|---|
| последняя 3.x | да |
| более ранние | нет — обновитесь до последней 3.x |

---

# Reporting a vulnerability (English)

Please do **not** report vulnerabilities in public issues, discussions or chats. Use a private
channel, in this order:

1. **GitHub private vulnerability reporting** — the *Security* tab of the public repository →
   *Report a vulnerability*. Available once the public repository is published; only its
   maintainers see the report.
2. **Telegram:** a private message to the 3DIWELL support bot **@Sup3DiwellBot** — available now,
   and the fallback if the first channel is not available.

Include the program version (About window), what happens, how to reproduce it and the impact. Do
not send real printer access codes, passwords, tokens, license files or farm backups.

Response targets: acknowledgement within 7 days; a fix for a critical vulnerability within 30 days
of acknowledgement as a target (if it takes longer, we will say why and when to expect it).
Security fixes are released for the latest 3.x version only.
