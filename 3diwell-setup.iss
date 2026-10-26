; SPDX-License-Identifier: MPL-2.0
; SPDX-FileCopyrightText: 2025-2026 3DiWell Team
; This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
; If a copy of the MPL was not distributed with this file, You can obtain one at
; https://mozilla.org/MPL/2.0/.
;  ===========================================================================
;  3DIWELL Farm Manager — установщик (Inno Setup 6).
;  Сборка выпуска целиком — одной командой из папки проекта:  python tools\build_release.py
;  (три EXE, проверки сборки, оба установщика, папка выпуска с модулями).
;  Компиляция вручную из папки проекта:
;      ISCC.exe /DDistDir="C:\3DIWELL_Builds\Beta_3.71\dist" /O"куда" 3diwell-setup.iss
;  Без /DDistDir берётся dist\ рядом с этим файлом (так делает build.bat).
;
;  ВАЖНО: при выпуске новой версии обновляйте AppVersion ниже под APP_VERSION в server.py.
;
;  3.0: установщик ставит ВСЁ, что нужно программе на чистой Windows, и не трогает то, что
;  уже стоит: 64-разрядная Windows 10 и новее (проверяет сам Inno Setup), .NET Framework
;  4.7.2+ и Microsoft Edge WebView2 Runtime — их проверки и шаги живут в общем файле
;  tools\installer\prereqs.iss, одном на оба установщика.
;  ===========================================================================

#define AppName "3DIWELL Farm Manager"
#define AppVersion "3.71"
#define AppPublisher "3DIWELL"
#define AppURL "https://www.3diwell.com"
#define AppExeName "3DIWELL Farm Manager.exe"
; Alpha 2.805: собственное окно (WebView2). Desktop.exe запускает/переиспользует backend сам.
#define ShellExeName "3DIWELL Farm Manager Desktop.exe"
; Откуда брать собранные EXE: по умолчанию dist\ рядом, при сборке выпуска — staging снаружи.
#ifndef DistDir
  #define DistDir "dist"
#endif

[Setup]
; Постоянный GUID приложения (нужен для корректных обновлений и удаления). Не меняйте между версиями.
AppId={{8C1F2A93-5E47-4B6A-9D3C-1A2B3C4D5E6F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
; 16.10.2026 (R-149): номер в свойствах файла установщика (Свойства → Подробно). Без этой строки
; Inno Setup пишет туда 0.0.0.0; «3.71» дополняется до 3.71.0.0, версия продукта берётся отсюда же.
; Нового места версии нет — это тот же AppVersion. Обновление и удаление узнаются по AppId, не по ней.
VersionInfoVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
; 17.09.2026, по слову владельца: страница выбора папки установки показывается ВСЕГДА.
; По умолчанию Inno Setup прячет её при повторной установке поверх уже установленной
; программы (DisableDirPage=auto) — из-за этого сменить место установки было нельзя.
DisableDirPage=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=3DIWELL_Farm_Manager_Setup_{#AppVersion}
SetupIconFile=web\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
; 3.0: только 64-разрядная Windows 10 и новее — на другой системе установщик откажет
; словами, а не поставит программу, которая не запустится.
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
; 26.09.2026: ядро — MPL 2.0. Страница лицензии: короткое пояснение и полный текст MPL 2.0.
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"; LicenseFile: "packaging\installer\license-page-ru.txt"
Name: "english"; MessagesFile: "compiler:Default.isl"; LicenseFile: "packaging\installer\license-page-en.txt"

[CustomMessages]
russian.FirewallMsg=Настройка брандмауэра Windows...
english.FirewallMsg=Configuring Windows Firewall...

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "{#DistDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Alpha 2.805: desktop-оболочка ставится рядом с сервером (собирается desktop_shell.spec).
Source: "{#DistDir}\{#ShellExeName}"; DestDir: "{app}"; Flags: ignoreversion
; 26.09.2026: текст MPL 2.0 и перечень сторонних компонентов — рядом с программой (MPL 3.2).
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; DestName: "THIRD_PARTY_NOTICES.txt"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.en.md"; DestDir: "{app}"; DestName: "THIRD_PARTY_NOTICES_EN.txt"; Flags: ignoreversion
; 26.09.2026: тексты лицензий сторонних компонентов, вшитых в программу (FFmpeg — GPL-3.0,
; изображения принтеров — AGPL-3.0, шрифты интерфейса — OFL-1.1), и примечания к ним: откуда
; компонент и где его исходный код. Ставятся в папку licenses рядом с программой.
Source: "packaging\installer\licenses\*.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "web\design\fonts\OFL-*.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion

; Предварительные условия (.NET Framework 4.7.2+, WebView2 Runtime): файлы компонентов,
; проверки «уже стоит?» и шаги установки — только когда компонента нет.
#include "tools\installer\prereqs.iss"


[Icons]
; Основной ярлык — СОБСТВЕННОЕ ОКНО (оболочка переиспользует работающий backend либо запускает его).
Name: "{group}\{#AppName}"; Filename: "{app}\{#ShellExeName}"
; Прежний браузерный способ сохранён отдельным ярлыком (backend + системный браузер).
Name: "{group}\{#AppName} — браузер"; Filename: "{app}\{#ShellExeName}"; Parameters: "--open-browser"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ShellExeName}"; Tasks: desktopicon

[Run]
; 17.09.2026: порт задаёт САМА ПРОГРАММА и от имени пользователя (config.json лежит в его
; папке данных, а установщик работает от администратора). Она же честно проверяет занятость
; и сообщает выбранный порт обратно файлом — см. tools\installer\portpage.iss.
Filename: "{app}\{#AppExeName}"; Parameters: "--fm-apply-port {code:FmGetPortArg} --fm-port-out ""{tmp}\fm_port_final.txt"""; Flags: runhidden waituntilterminated runasoriginaluser; StatusMsg: "{cm:PortApplyMsg}"
; Старое правило снимаем: при смене порта иначе осталось бы висеть правило на прежний.
Filename: "{cmd}"; Parameters: "/c netsh advfirewall firewall delete rule name=""3DIWELL Farm Server"" & exit 0"; Flags: runhidden
; Разрешить входящие на ВЫБРАННЫЙ порт, чтобы интерфейс открывался с других ПК сети.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""3DIWELL Farm Server"" dir=in action=allow protocol=TCP localport={code:FmGetFinalPort}"; Flags: runhidden; StatusMsg: "{cm:FirewallMsg}"
; 09.10.2026 (R-092, разрешение владельца): «Найти в сети». Принтеры Bambu сами объявляют о себе
; на UDP 2021 и 1990, Klipper и Creality — по mDNS (UDP 5353). Брандмауэр Windows такие входящие
; пакеты в программу по умолчанию не пускает, и поиск находил 0 принтеров. Правило — только для
; самой программы и только для этих трёх UDP-портов; прежнее снимаем, чтобы не плодить копии.
Filename: "{cmd}"; Parameters: "/c netsh advfirewall firewall delete rule name=""3DIWELL Farm Manager - printer discovery"" & exit 0"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""3DIWELL Farm Manager - printer discovery"" dir=in action=allow protocol=UDP localport=2021,1990,5353 program=""{app}\{#AppExeName}"""; Flags: runhidden; StatusMsg: "{cm:FirewallMsg}"
Filename: "{app}\{#ShellExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""3DIWELL Farm Server"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""3DIWELL Farm Manager - printer discovery"""; Flags: runhidden

; Страница «Порт программы» (выбор вручную или автоподбор свободного) и её код.
; ПОДКЛЮЧАЕТСЯ ПОСЛЕДНЕЙ И ТОЛЬКО ЗДЕСЬ: после включённого файла разбор остаётся внутри его
; секции [Code], поэтому обычный комментарий с точкой с запятой посреди файла Inno Setup
; принимает за код на Паскале и отказывается компилировать (проверено 17.09.2026).
#include "tools\installer\portpage.iss"
