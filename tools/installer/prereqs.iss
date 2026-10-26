; SPDX-License-Identifier: MPL-2.0
; SPDX-FileCopyrightText: 2025-2026 3DiWell Team
; This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
; If a copy of the MPL was not distributed with this file, You can obtain one at
; https://mozilla.org/MPL/2.0/.
;  ===========================================================================
;  3DIWELL Farm Manager — предварительные условия установки (3.0).
;  Общий файл для 3diwell-setup.iss и 3diwell-client-setup.iss, подключается директивой
;  #include из корня проекта: оба установщика ведут себя одинаково.
;
;  ЗАЧЕМ. Решение владельца 12.09.2026: установщик обязан ставиться на СОВЕРШЕННО ЧИСТУЮ
;  Windows без интернета и сам приносить всё, что нужно программе. И обязан быть умным:
;  то, что на компьютере уже стоит, не трогается и не переустанавливается.
;
;  ЧТО ПРОВЕРЯЕТСЯ И СТАВИТСЯ (только когда компонента нет):
;   · Microsoft .NET Framework 4.7.2 или новее — на нём работает собственное окно
;     программы (pywebview → pythonnet → .NET). Есть в Windows 10 начиная с 1803 и во
;     всех Windows 11; на более старой Windows 10 ставится вложенный автономный
;     установщик 4.8 (ему нужна Windows 10 версии 1607 или новее; если компьютер не
;     отвечает его требованиям — старая Windows, мало места на диске, — он отвечает кодом
;     5100, и установка останавливается с объяснением, что проверить).
;     Признак наличия — по документации Microsoft: значение Release в
;     HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full; 461808 и выше = 4.7.2+.
;     Без .NET окно программы не откроется вовсе, поэтому отказ установки .NET
;     останавливает установку с понятным сообщением.
;   · Microsoft Edge WebView2 Runtime — движок окна программы. В Windows 11 есть всегда,
;     на чистой Windows 10 может отсутствовать. Признак — значение pv в ветке
;     EdgeUpdate\Clients\{F3017226-…} (HKLM 32/64 и HKCU); пусто или 0.0.0.0 = нет.
;     Программа умеет работать и без WebView2 (предлагает обычный браузер), поэтому
;     отказ установки WebView2 установку не останавливает — только предупреждает.
;   Оба шага идут на странице «Подготовка к установке», ДО копирования файлов программы.
;   Windows 10+ и 64-разрядность проверяет сам Inno Setup (MinVersion, ArchitecturesAllowed
;   в [Setup] каждого установщика) — на другой системе отказ словами, а не битая установка.
;
;  ФАЙЛЫ КОМПОНЕНТОВ лежат ВНЕ репозитория (около 210 и 120 МБ; GitHub не принимает файлы
;  больше 100 МБ): C:\3DIWELL_Builds\vendor, либо /DVendorDir="…" при компиляции.
;   · MicrosoftEdgeWebView2RuntimeInstallerX64.exe — Evergreen Standalone Installer x64,
;     https://developer.microsoft.com/microsoft-edge/webview2/ (fwlink 2124701).
;   · ndp48-x86-x64-allos-enu.exe — .NET Framework 4.8 Offline Installer,
;     https://dotnet.microsoft.com/download/dotnet-framework/net48 (fwlink 2088631).
;   Подлинность обоих подтверждается подписью Microsoft Corporation (Get-AuthenticodeSignature).
;  Файла нет — установщик собирается без соответствующего шага (обычная сборка не
;  ломается), но сборка ВЫПУСКА (/DReleaseBuild) без него останавливается с ошибкой:
;  выпуск обязан ставиться на чистую Windows без интернета.
;  ===========================================================================

#ifndef VendorDir
  #define VendorDir "C:\3DIWELL_Builds\vendor"
#endif
#define WebView2Exe "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
#define DotNetExe "ndp48-x86-x64-allos-enu.exe"

#if FileExists(VendorDir + "\" + WebView2Exe)
  #define HaveWebView2
  #pragma message "WebView2 Runtime вшивается в установщик: " + VendorDir + "\" + WebView2Exe
#else
  #pragma message "WebView2 Runtime не найден в " + VendorDir + " — установщик собирается без него"
  #ifdef ReleaseBuild
    #error Сборка выпуска: нет MicrosoftEdgeWebView2RuntimeInstallerX64.exe в VendorDir
  #endif
#endif
#if FileExists(VendorDir + "\" + DotNetExe)
  #define HaveDotNet
  #pragma message ".NET Framework 4.8 вшивается в установщик: " + VendorDir + "\" + DotNetExe
#else
  #pragma message ".NET Framework 4.8 не найден в " + VendorDir + " — установщик собирается без него"
  #ifdef ReleaseBuild
    #error Сборка выпуска: нет ndp48-x86-x64-allos-enu.exe в VendorDir
  #endif
#endif

[CustomMessages]
russian.PrereqDotNet=Установка Microsoft .NET Framework 4.8 (нужен окну программы)…
english.PrereqDotNet=Installing Microsoft .NET Framework 4.8 (required by the app window)…
russian.PrereqWebView2=Установка Microsoft Edge WebView2 Runtime (нужен окну программы)…
english.PrereqWebView2=Installing Microsoft Edge WebView2 Runtime (required by the app window)…
russian.PrereqDotNetRequirements=Установщик Microsoft .NET Framework 4.8 сообщил, что компьютер не отвечает его требованиям (код 5100). Чаще всего это Windows 10 старше версии 1607 — обновите Windows через «Центр обновления Windows». Также проверьте, что на диске C: свободно несколько гигабайт. Затем запустите эту установку снова: без .NET окно программы не откроется.
english.PrereqDotNetRequirements=The Microsoft .NET Framework 4.8 installer reports that this computer does not meet its system requirements (code 5100). Most often this is Windows 10 older than version 1607 — update Windows through Windows Update. Also make sure drive C: has several gigabytes free. Then run this setup again: the app window cannot open without .NET.
russian.PrereqDotNetFailed=Не удалось установить Microsoft .NET Framework 4.8 (код %1). Без него окно программы не откроется. Установите .NET Framework 4.8 с сайта Microsoft и запустите эту установку снова.
english.PrereqDotNetFailed=Microsoft .NET Framework 4.8 could not be installed (code %1). The app window cannot open without it. Install .NET Framework 4.8 from Microsoft and run this setup again.
russian.PrereqWebView2Failed=Не удалось установить Microsoft Edge WebView2 Runtime (код %1). Установка продолжится: программа предложит открыть интерфейс в обычном браузере, а WebView2 можно поставить позже с сайта Microsoft.
english.PrereqWebView2Failed=Microsoft Edge WebView2 Runtime could not be installed (code %1). Setup will continue: the app will offer to open in your browser, and WebView2 can be installed later from Microsoft.

[Files]
#ifdef HaveDotNet
; dontcopy: файл не попадает в папку программы; он распаковывается во временную папку
; только тогда, когда компонента нет (ExtractTemporaryFile в PrepareToInstall ниже).
Source: "{#VendorDir}\{#DotNetExe}"; Flags: dontcopy
#endif
#ifdef HaveWebView2
Source: "{#VendorDir}\{#WebView2Exe}"; Flags: dontcopy
#endif

[Code]
const
  WV2_KEY = 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  NDP_KEY = 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full';
  //  16.10.2026 (R-109): 461808 — так .NET Framework 4.7.2 записан в Windows 10 1803 (April 2018 Update),
  //  на остальных системах 4.7.2 даёт 461814, более новые версии — больше. Поэтому сравнение «не меньше
  //  461808» и есть «4.7.2 или новее» на любой Windows (Microsoft, «How to determine which .NET Framework
  //  versions are installed»). Прежний комментарий называл 1809 — порог был верен, подпись нет.
  NDP_MIN_RELEASE = 461808;   // .NET Framework 4.7.2 (минимальное значение — Windows 10 1803)

var
  PrereqNeedRestart: Boolean;

// Наличие WebView2 Runtime определяется ровно так, как описано у Microsoft: значение pv в ветке
// EdgeUpdate\Clients\<GUID рантайма>. Пусто, отсутствует или 0.0.0.0 — рантайма нет.
// Смотрим три места: HKLM в 32- и 64-битном представлении и HKCU (установка «для пользователя»).
function _PvPresent(Root: Integer; Key: String): Boolean;
var
  V: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', V) and (V <> '') and (V <> '0.0.0.0');
end;

function WebView2Installed: Boolean;
begin
  Result := _PvPresent(HKLM32, 'SOFTWARE\' + WV2_KEY)
         or _PvPresent(HKLM64, 'SOFTWARE\' + WV2_KEY)
         or _PvPresent(HKCU,   'Software\' + WV2_KEY);
end;

function NeedsWebView2: Boolean;
begin
  Result := not WebView2Installed;
end;

// .NET Framework 4.x: одно значение Release, растёт с каждой версией (документация Microsoft
// «How to determine which .NET Framework versions are installed»).
function DotNetInstalled: Boolean;
var
  Release: Cardinal;
begin
  Result := (RegQueryDWordValue(HKLM64, NDP_KEY, 'Release', Release) and (Release >= NDP_MIN_RELEASE))
         or (RegQueryDWordValue(HKLM32, NDP_KEY, 'Release', Release) and (Release >= NDP_MIN_RELEASE));
end;

function NeedsDotNet: Boolean;
begin
  Result := not DotNetInstalled;
end;

procedure _PrereqStatus(const Msg: String);
begin
  WizardForm.PreparingLabel.Caption := Msg;
  WizardForm.PreparingLabel.Visible := True;
end;

// Распаковать вложенный установщик компонента во временную папку и дождаться его.
// Возвращает код завершения; -1 — процесс не удалось запустить.
function _RunPrereq(const ExeName, Params: String): Integer;
var
  rc: Integer;
begin
  ExtractTemporaryFile(ExeName);
  if Exec(ExpandConstant('{tmp}\') + ExeName, Params, '', SW_SHOW, ewWaitUntilTerminated, rc) then
    Result := rc
  else
    Result := -1;
end;

// Вызывается Inno Setup перед копированием файлов. Непустая строка = остановить установку
// и показать её как причину.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  rc: Integer;
begin
  Result := '';
#ifdef HaveDotNet
  if NeedsDotNet then begin
    _PrereqStatus(CustomMessage('PrereqDotNet'));
    rc := _RunPrereq('{#DotNetExe}', '/q /norestart');
    if (rc = 3010) or (rc = 1641) then
      PrereqNeedRestart := True
    else if rc = 5100 then begin
      //  16.10.2026 (R-109): 5100 по Microsoft (руководство по развёртыванию .NET Framework) —
      //  «компьютер не отвечает требованиям». Причин несколько: чаще всего Windows 10 старше 1607,
      //  но бывает и нехватка места на диске. Поэтому сообщение называет, что проверить, а не
      //  одну причину, и это не общий текст «не удалось установить».
      Result := CustomMessage('PrereqDotNetRequirements');
      exit;
    end
    else if rc <> 0 then begin
      Result := FmtMessage(CustomMessage('PrereqDotNetFailed'), [IntToStr(rc)]);
      exit;
    end;
  end;
#endif
#ifdef HaveWebView2
  if NeedsWebView2 then begin
    _PrereqStatus(CustomMessage('PrereqWebView2'));
    rc := _RunPrereq('{#WebView2Exe}', '/silent /install');
    if (rc <> 0) and (not WebView2Installed) then
      MsgBox(FmtMessage(CustomMessage('PrereqWebView2Failed'), [IntToStr(rc)]), mbError, MB_OK);
  end;
#endif
end;

// .NET Framework мог попросить перезагрузку (3010/1641) — сообщаем об этом в конце мастера.
function NeedRestart(): Boolean;
begin
  Result := PrereqNeedRestart;
end;
