[Русский](SECURITY.md) · **English**

# Reporting a vulnerability

If you have found a vulnerability in 3DIWELL Farm Manager or its modules, please **do not publish it
in public issues, discussions or chats**. Write to us directly through a private channel.

## Where to report (in order)

1. **GitHub private vulnerability reporting**: the *Security* tab of the public repository →
   the *Report a vulnerability* button. This channel becomes available once the public repository is
   published; only its maintainers see the report.
2. **Telegram:** @Sup3DiwellBot — a private message to 3DIWELL support. Available now, and suitable
   if the first channel is not available.

What to include: the program version (the About window), what exactly happens, the steps to
reproduce it, and what the impact is. **Do not send** real printer access codes, passwords,
tokens, license files or backups with farm data — a description or made-up values are
enough.

## Response times

- **Acknowledgement of receipt** — within 7 days.
- **Fix for a critical vulnerability** — target of 30 days from acknowledgement. If it takes longer,
  we will tell you why and when to expect it.
- We will let you know when the fixed version is released. Until a fix is available, please do not
  disclose details publicly.

## What counts as a vulnerability

For example: access to the farm or its data without signing in, privilege escalation, execution of
someone else's code, bypassing the signature check of a module package or license, leakage of
printer access codes or tokens.

## Supported versions

| Version | Security fixes |
|---|---|
| latest 3.x | yes |
| earlier | no — update to the latest 3.x |
