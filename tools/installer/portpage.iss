; SPDX-License-Identifier: MPL-2.0
; SPDX-FileCopyrightText: 2025-2026 3DiWell Team
; This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
; If a copy of the MPL was not distributed with this file, You can obtain one at
; https://mozilla.org/MPL/2.0/.
;  ===========================================================================
;  Страница «Порт программы» для установщика 3DIWELL Farm Manager (17.09.2026).
;
;  ЗАЧЕМ. Слово владельца: «в процессе установки нужно добавить опцию выбора порта вручную,
;  а также автоматическую опцию, при которой установщик проверит, занят ли 8000-й порт,
;  и если да — подберёт свободный, чтобы программа после установки заработала».
;
;  КАК УСТРОЕНО. Установщик НЕ пишет config.json сам: этот файл лежит в папке данных
;  ПОЛЬЗОВАТЕЛЯ, установщик работает от администратора, и в файле уже могут быть другие
;  настройки. Поэтому после копирования файлов установщик запускает саму программу одной
;  командой ОТ ИМЕНИ ПОЛЬЗОВАТЕЛЯ (флаг runasoriginaluser):
;      "3DIWELL Farm Manager.exe" --fm-apply-port auto|<порт> --fm-port-out <файл>
;  Программа честно проверяет занятость пробным bind, атомарно пишет порт в свой config.json,
;  сохраняя остальные поля, и записывает выбранное значение в файл — установщик читает его
;  и открывает в брандмауэре ИМЕННО этот порт. Разбор и запись — app/install_port_cli.py.
;
;  ПРОВЕРКА ЗАНЯТОСТИ НА СТРАНИЦЕ — только подсказка человеку (netstat, без сети наружу).
;  Настоящее решение принимает программа: между показом страницы и установкой порт мог
;  освободиться или занятьcя.
;  ===========================================================================

[CustomMessages]
russian.PortPageCaption=Порт программы
russian.PortPageDesc=На каком порту будет работать Farm Manager
russian.PortPageSub=Интерфейс открывается по адресу вида http://127.0.0.1:ПОРТ. В автоматическом режиме программа проверит порт 8000 и, если он занят, подберёт ближайший свободный.
russian.PortAuto=Автоматически (рекомендуется)
russian.PortManual=Задать порт вручную
russian.PortLabel=Номер порта (от 1024 до 65535):
russian.PortFree=Порт 8000 сейчас свободен — программа будет работать на нём.
russian.PortBusy=Порт 8000 сейчас занят другой программой — будет подобран ближайший свободный.
russian.PortBadValue=Укажите номер порта числом от 1024 до 65535.
russian.PortBusyAsk=Порт %1 сейчас занят другой программой, и Farm Manager на нём не запустится. Всё равно использовать этот порт?
russian.PortApplyMsg=Настройка порта программы...
english.PortPageCaption=Application port
english.PortPageDesc=Which port Farm Manager will use
english.PortPageSub=The interface opens at an address like http://127.0.0.1:PORT. In automatic mode the program checks port 8000 and picks the nearest free one if it is taken.
english.PortAuto=Automatic (recommended)
english.PortManual=Set the port manually
english.PortLabel=Port number (1024 to 65535):
english.PortFree=Port 8000 is free right now — the program will use it.
english.PortBusy=Port 8000 is taken by another program right now — the nearest free port will be picked.
english.PortBadValue=Enter a port number between 1024 and 65535.
english.PortBusyAsk=Port %1 is taken by another program right now, and Farm Manager will not start on it. Use this port anyway?
english.PortApplyMsg=Applying the application port...

[Code]
var
  FmPortPage: TInputOptionWizardPage;
  FmPortEdit: TNewEdit;
  FmPortCaption: TNewStaticText;
  FmPortStatus: TNewStaticText;
  FmPortStateKnown: Boolean;
  FmPortDefaultBusy: Boolean;

// Занят ли TCP-порт ПРЯМО СЕЙЧАС. Смотрим вывод netstat: строка со слушателем на этом порту.
// Окна у команды нет (SW_HIDE), в сеть она не ходит. Ошибка запуска = «не знаем» = «свободен»:
// пугать человека из-за недоступного netstat нельзя, настоящее решение всё равно за программой.
function FmPortIsBusy(Port: Integer): Boolean;
var
  rc: Integer;
  Data: AnsiString;
  TempFile: String;
begin
  Result := False;
  TempFile := ExpandConstant('{tmp}\fm_port_check.txt');
  DeleteFile(TempFile);
  if Exec(ExpandConstant('{cmd}'),
          '/c netstat -ano -p TCP | findstr /C:":' + IntToStr(Port) + ' " | findstr /C:"LISTENING" > "' + TempFile + '"',
          '', SW_HIDE, ewWaitUntilTerminated, rc) then
  begin
    if LoadStringFromFile(TempFile, Data) then
      Result := Trim(String(Data)) <> '';
  end;
  DeleteFile(TempFile);
end;

procedure FmPortSyncControls;
var
  Manual: Boolean;
begin
  Manual := FmPortPage.SelectedValueIndex = 1;
  FmPortEdit.Enabled := Manual;
  FmPortCaption.Enabled := Manual;
  if Manual then
    FmPortStatus.Caption := ''
  else if FmPortDefaultBusy then
    FmPortStatus.Caption := ExpandConstant('{cm:PortBusy}')
  else
    FmPortStatus.Caption := ExpandConstant('{cm:PortFree}');
end;

procedure FmPortOptionClicked(Sender: TObject);
begin
  FmPortSyncControls;
end;

procedure FmCreatePortPage;
begin
  FmPortPage := CreateInputOptionPage(wpSelectDir,
    ExpandConstant('{cm:PortPageCaption}'), ExpandConstant('{cm:PortPageDesc}'),
    ExpandConstant('{cm:PortPageSub}'), True, False);
  FmPortPage.Add(ExpandConstant('{cm:PortAuto}'));
  FmPortPage.Add(ExpandConstant('{cm:PortManual}'));
  FmPortPage.SelectedValueIndex := 0;
  FmPortPage.CheckListBox.OnClickCheck := @FmPortOptionClicked;
  //  ВАЖНО: список вариантов на такой странице по умолчанию занимает ВСЮ высоту страницы,
  //  и поле ввода ниже уехало бы за край. Поэтому высоту задаём явно — под две строки текста.
  FmPortPage.CheckListBox.Height := ScaleY(68);

  FmPortCaption := TNewStaticText.Create(FmPortPage);
  FmPortCaption.Parent := FmPortPage.Surface;
  FmPortCaption.Top := FmPortPage.CheckListBox.Top + FmPortPage.CheckListBox.Height + ScaleY(10);
  FmPortCaption.Left := ScaleX(16);
  FmPortCaption.Caption := ExpandConstant('{cm:PortLabel}');

  FmPortEdit := TNewEdit.Create(FmPortPage);
  FmPortEdit.Parent := FmPortPage.Surface;
  FmPortEdit.Top := FmPortCaption.Top + FmPortCaption.Height + ScaleY(4);
  FmPortEdit.Left := ScaleX(16);
  FmPortEdit.Width := ScaleX(90);
  FmPortEdit.Text := '8000';

  FmPortStatus := TNewStaticText.Create(FmPortPage);
  FmPortStatus.Parent := FmPortPage.Surface;
  FmPortStatus.Top := FmPortEdit.Top + FmPortEdit.Height + ScaleY(12);
  FmPortStatus.Left := ScaleX(16);
  FmPortStatus.Width := FmPortPage.SurfaceWidth - ScaleX(20);
  FmPortStatus.AutoSize := False;
  FmPortStatus.Height := ScaleY(34);
  FmPortStatus.WordWrap := True;
  FmPortStatus.Caption := '';

  FmPortStateKnown := False;
  FmPortDefaultBusy := False;
end;

// Что передать программе после установки: 'auto' либо номер порта, заданный вручную.
function FmGetPortArg(Param: String): String;
begin
  if (FmPortPage <> nil) and (FmPortPage.SelectedValueIndex = 1) then
    Result := Trim(FmPortEdit.Text)
  else
    Result := 'auto';
end;

// Порт, который программа ФАКТИЧЕСКИ записала себе (его она кладёт в файл). Файла нет —
// берём 8000: правило брандмауэра для порта по умолчанию лучше, чем никакого.
function FmGetFinalPort(Param: String): String;
var
  Data: AnsiString;
  S: String;
begin
  Result := '8000';
  if LoadStringFromFile(ExpandConstant('{tmp}\fm_port_final.txt'), Data) then
  begin
    S := Trim(String(Data));
    if (S <> '') and (StrToIntDef(S, 0) >= 1024) and (StrToIntDef(S, 0) <= 65535) then
      Result := S;
  end;
end;

// ── События мастера. Эти три процедуры больше нигде не объявлены: prereqs.iss определяет
//    только PrepareToInstall и NeedRestart. ─────────────────────────────────────────────────
procedure InitializeWizard;
begin
  FmCreatePortPage;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (FmPortPage <> nil) and (CurPageID = FmPortPage.ID) then
  begin
    if not FmPortStateKnown then
    begin
      FmPortDefaultBusy := FmPortIsBusy(8000);
      FmPortStateKnown := True;
    end;
    FmPortSyncControls;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Value: String;
  Port: Integer;
begin
  Result := True;
  if (FmPortPage = nil) or (CurPageID <> FmPortPage.ID) or (FmPortPage.SelectedValueIndex <> 1) then
    exit;
  Value := Trim(FmPortEdit.Text);
  Port := StrToIntDef(Value, 0);
  if (Port < 1024) or (Port > 65535) or (IntToStr(Port) <> Value) then
  begin
    MsgBox(ExpandConstant('{cm:PortBadValue}'), mbError, MB_OK);
    Result := False;
    exit;
  end;
  //  Порт занят — не запрещаем, но спрашиваем: человек может освободить его позже сам.
  if FmPortIsBusy(Port) then
    Result := MsgBox(FmtMessage(ExpandConstant('{cm:PortBusyAsk}'), [Value]), mbConfirmation, MB_YESNO) = IDYES;
end;
