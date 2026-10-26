[Русский](NFC_SOURCES.md) · **English**

# Sources and limits of Bambu NFC reading (20.09.2026)

The FM implementation is independent; third-party Python scripts are not included in the APK and are not run.
JCA HmacSHA256 and the standard Android MifareClassic are used, with no new libraries.

## Public description of the protocol

- [Bambu Research Group: deriveKeys.py](https://github.com/Bambu-Research-Group/RFID-Tag-Guide/blob/main/deriveKeys.py)
  — public HKDF-SHA256 parameters (salt, UID as input, context RFID-A with a trailing zero byte).
  Authors of the original research/script: thekakester and Vinyl Da.i'gyu-Kazotetsu, 2024.
  HKDF outputs 96 consecutive bytes, which are split into 16 keys of 6 bytes each.
- [BambuLabRfid.md](https://github.com/Bambu-Research-Group/RFID-Tag-Guide/blob/main/BambuLabRfid.md)
  — structure of blocks 0, 1, 2, 4, 5.
- [parse.py](https://github.com/Bambu-Research-Group/RFID-Tag-Guide/blob/main/parse.py)
  — an additional cross-check of offsets. The diameter is taken from bytes 8–11 of block 5 as float32 LE;
  the Markdown table gives an inconsistent width for this field (8 bytes), the parser uses 4 bytes.
- [RFC 5869](https://www.rfc-editor.org/rfc/rfc5869.html) — HKDF and the official test vector.
- [Android MifareClassic](https://developer.android.com/reference/android/nfc/tech/MifareClassic)
  — sector authentication, block reading and cancelling blocked I/O via close.
- [Android NfcAdapter](https://developer.android.com/reference/android/nfc/NfcAdapter)
  — foreground Reader Mode and turning off automatic NDEF reading.

This is not an official Bambu SDK/contract and not a promise to support all tag generations.
The current test is limited to Mifare Classic 1K, a 4-byte UID, sectors 0/1 and blocks 0/1/2/4/5.
Neither key trailers, nor the signature, nor a full dump are read. Keys and the raw dump are not written
to the report or log. There is no key brute-forcing, cloning, writing, or changing of signatures or firmware.
A successful read/structure check does not prove that the spool is a genuine factory one.

For the user's diagnostics, PETG Basic (tentative), Orange, 1.75 mm are expected.
These expectations are not input parameters of the decoder. The color is shown in RGBA with a swatch,
without inventing a trade name; the weight from the tag is not used as the inventory remaining amount.
