; SPDX-License-Identifier: MPL-2.0
; SPDX-FileCopyrightText: 2025-2026 3DiWell Team
; This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
; If a copy of the MPL was not distributed with this file, You can obtain one at
; https://mozilla.org/MPL/2.0/.
;  ===========================================================================
;  3DIWELL Farm Manager Client — установщик КЛИЕНТА (Inno Setup 6, Alpha 2.805).
;  Клиент подключается к Farm Manager на другом компьютере. В установку входит ТОЛЬКО
;  клиентская оболочка: серверная часть, рабочая база и папка данных фермы, транспорт
;  принтеров и серверный tray сюда не входят; правила брандмауэра не создаются.
;  ПЕРЕД сборкой: tools\build_release.py (или tools\build_desktop_shell.ps1 — создаст dist\...Client.exe).
;  Компиляция вручную:  ISCC.exe [/DDistDir="…\dist"] [/O"куда"] 3diwell-client-setup.iss
;  3.0: те же предварительные условия, что у основного установщика (64-разрядная Windows 10+,
;  .NET Framework 4.7.2+, WebView2 Runtime) — общий файл tools\installer\prereqs.iss.
;  ===========================================================================

#define AppName "3DIWELL Farm Manager Client"
#define AppVersion "3.71"
#define AppPublisher "3DIWELL"
#define AppURL "https://www.3diwell.com"
#define AppExeName "3DIWELL Farm Manager Client.exe"
#ifndef DistDir
  #define DistDir "dist"
#endif

[Setup]
; Отдельный GUID: клиент устанавливается и удаляется НЕЗАВИСИМО от основного Farm Manager.
AppId={{7B4E9D21-0A6C-4F8E-B1D5-2C3E4F5A6B7C}
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
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=3DIWELL_Farm_Manager_Client_Setup_{#AppVersion}
SetupIconFile=web\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
; 26.09.2026: ядро — MPL 2.0; клиент показывает ту же страницу лицензии, что и основной установщик.
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"; LicenseFile: "packaging\installer\license-page-ru.txt"
Name: "english"; MessagesFile: "compiler:Default.isl"; LicenseFile: "packaging\installer\license-page-en.txt"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "{#DistDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; DestName: "THIRD_PARTY_NOTICES.txt"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.en.md"; DestDir: "{app}"; DestName: "THIRD_PARTY_NOTICES_EN.txt"; Flags: ignoreversion

#include "tools\installer\prereqs.iss"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
