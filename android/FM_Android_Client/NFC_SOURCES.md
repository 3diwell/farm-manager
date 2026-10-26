# Источники и границы чтения NFC Bambu (20.09.2026)

Реализация FM самостоятельная; сторонние Python-скрипты в APK не включаются и не исполняются.
Используются JCA HmacSHA256 и штатный Android MifareClassic, без новых библиотек.

## Публичное описание протокола

- [Bambu Research Group: deriveKeys.py](https://github.com/Bambu-Research-Group/RFID-Tag-Guide/blob/main/deriveKeys.py)
  — публичные параметры HKDF-SHA256 (salt, UID как вход, context RFID-A с завершающим нулём).
  Авторы исходного исследования/скрипта: thekakester и Vinyl Da.i'gyu-Kazotetsu, 2024.
  HKDF выдаёт 96 последовательных байтов, которые делятся на 16 ключей по 6 байт.
- [BambuLabRfid.md](https://github.com/Bambu-Research-Group/RFID-Tag-Guide/blob/main/BambuLabRfid.md)
  — структура блоков 0, 1, 2, 4, 5.
- [parse.py](https://github.com/Bambu-Research-Group/RFID-Tag-Guide/blob/main/parse.py)
  — дополнительная сверка смещений. Диаметр берётся из байтов 8–11 блока 5 как float32 LE;
  в таблице Markdown ширина этого поля указана противоречиво (8 байт), в парсере — 4 байта.
- [RFC 5869](https://www.rfc-editor.org/rfc/rfc5869.html) — HKDF и официальный тестовый вектор.
- [Android MifareClassic](https://developer.android.com/reference/android/nfc/tech/MifareClassic)
  — аутентификация сектора, чтение блока и отмена заблокированного I/O через close.
- [Android NfcAdapter](https://developer.android.com/reference/android/nfc/NfcAdapter)
  — foreground Reader Mode и отключение автоматического NDEF-чтения.

Это не официальный SDK/контракт Bambu и не обещание поддержки всех поколений меток.
Текущий тест ограничен Mifare Classic 1K, UID 4 байта, секторами 0/1 и блоками 0/1/2/4/5.
Ни трейлеры с ключами, ни подпись, ни полный дамп не читаются. Ключи и сырой дамп не выводятся
в отчёт или лог. Нет перебора ключей, клонирования, записи, изменения подписи или прошивок.
Успешное чтение/проверка структуры не доказывает заводскую подлинность катушки.

Для диагностики пользователя ожидаются PETG Basic (предварительно), Orange, 1,75 мм.
Эти ожидания не являются входными параметрами декодера. Цвет выводится в RGBA с образцом,
без выдумывания торгового названия; масса из метки не используется как остаток склада.
