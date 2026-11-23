; Instalador do Eco (Inno Setup 6). Compilado por installer\build.ps1; nao compile a mao sem /DAppVersion.
; Principios: sem admin por padrao (por usuario), sem tocar em PATH/firewall/drivers, modelos grandes baixados depois (nao no .exe),
; desinstalador que PERGUNTA antes de apagar dados do usuario.

#ifndef AppVersion
  #define AppVersion Trim(FileRead(FileOpen(SourcePath + "VERSION")))
#endif
#ifndef AppVersionNum
  #define AppVersionNum "0.0.0.0"
#endif
#ifndef StagingDir
  #define StagingDir "staging\app"
#endif
#ifndef OutDir
  #define OutDir "dist"
#endif

#define AppName "Eco"
#define PyDir "{app}\runtime\python"
#define PyW PyDir + "\pythonw.exe"
#define PyC PyDir + "\python.exe"

[Setup]
; GUID fixo: identifica o app para atualizar por cima e desinstalar. NAO mude entre versoes.
AppId={{4B0D7A52-8C1E-4F5B-9A63-7E2D1C9F3A18}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Eco
VersionInfoVersion={#AppVersionNum}
VersionInfoProductName={#AppName}
VersionInfoDescription=Instalador do Eco (assistente de voz local)
DefaultDirName={autopf}\Eco
DefaultGroupName=Eco
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19044
OutputDir={#OutDir}
OutputBaseFilename=Eco-Setup-{#AppVersion}
SetupIconFile=assets\eco.ico
UninstallDisplayIcon={app}\eco.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=assets\wizard-164x314.bmp,assets\wizard-192x386.bmp,assets\wizard-246x459.bmp
WizardSmallImageFile=assets\small-55.bmp,assets\small-64.bmp,assets\small-80.bmp
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=no
ChangesAssociations=no
AllowNoIcons=yes
ShowLanguageDialog=auto
LanguageDetectionMethod=uilanguage
#ifdef SignTool
SignTool={#SignTool}
SignedUninstaller=yes
#endif

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"; LicenseFile: "LICENSE.pt-BR.txt"
Name: "en"; MessagesFile: "compiler:Default.isl"; LicenseFile: "LICENSE.en.txt"

[Types]
Name: "full"; Description: "{cm:TypeFull}"
Name: "custom"; Description: "{cm:TypeCustom}"; Flags: iscustom

[Components]
Name: "core"; Description: "{cm:CompCore}"; Types: full custom; Flags: fixed
Name: "vision"; Description: "{cm:CompVision}"; Types: full; ExtraDiskSpaceRequired: 2950000000
Name: "voice"; Description: "{cm:CompVoice}"; Types: full; ExtraDiskSpaceRequired: 66000000
Name: "stt"; Description: "{cm:CompStt}"; Types: full
Name: "stt\small"; Description: "{cm:CompSttSmall}"; Types: full; Flags: exclusive; ExtraDiskSpaceRequired: 490000000
Name: "stt\base"; Description: "{cm:CompSttBase}"; Flags: exclusive; ExtraDiskSpaceRequired: 150000000

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; GroupDescription: "{cm:TaskGroupShortcuts}"
Name: "startmenuicon"; Description: "{cm:TaskStartMenu}"; GroupDescription: "{cm:TaskGroupShortcuts}"
Name: "autostart"; Description: "{cm:TaskAutostart}"; GroupDescription: "{cm:TaskGroupStartup}"; Flags: unchecked

[Dirs]
; Pastas de dados do usuario. Instalacao por usuario: so o usuario acessa (ver [Code], icacls). Por maquina: usuarios comuns gravam.
Name: "{app}\data"; Permissions: users-modify; Check: IsAdminInstallMode
Name: "{app}\logs"; Permissions: users-modify; Check: IsAdminInstallMode
Name: "{app}\models"; Permissions: users-modify; Check: IsAdminInstallMode
Name: "{app}\data"; Check: not IsAdminInstallMode
Name: "{app}\logs"; Check: not IsAdminInstallMode
Name: "{app}\models"; Check: not IsAdminInstallMode

[InstallDelete]
; Atualizacao por cima: troca SO o codigo (src, runtime, bin). Nunca toca em data\, models\, logs\ nem config.toml.
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\bin"
; Migracao do nome antigo (Jarvis): remove atalhos e arquivos de entrada que nao existem mais.
Type: filesandordirs; Name: "{autoprograms}\Jarvis"
Type: files; Name: "{autodesktop}\Jarvis.lnk"
Type: files; Name: "{app}\Jarvis.pyw"
Type: files; Name: "{app}\Jarvis.cmd"
Type: files; Name: "{app}\jarvis_boot.py"
Type: files; Name: "{app}\jarvis.ico"

[Files]
Source: "{#StagingDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: core

[Icons]
Name: "{autoprograms}\Eco\Eco"; Filename: "{#PyW}"; Parameters: "-I -X utf8 ""{app}\Eco.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\eco.ico"; Comment: "{cm:IconRun}"; Tasks: startmenuicon
Name: "{autoprograms}\Eco\{cm:IconSettings}"; Filename: "{#PyW}"; Parameters: "-I -X utf8 ""{app}\Eco.pyw"" settings"; WorkingDir: "{app}"; IconFilename: "{app}\eco.ico"; Tasks: startmenuicon
Name: "{autoprograms}\Eco\{cm:IconRepair}"; Filename: "{#PyW}"; Parameters: "-I -X utf8 ""{app}\Eco.pyw"" setup --repair"; WorkingDir: "{app}"; IconFilename: "{app}\eco.ico"; Tasks: startmenuicon
Name: "{autoprograms}\Eco\{cm:IconUninstall}"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{autodesktop}\Eco"; Filename: "{#PyW}"; Parameters: "-I -X utf8 ""{app}\Eco.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\eco.ico"; Tasks: desktopicon

[Registry]
; Iniciar com o Windows: so se o usuario marcar. Removido na desinstalacao.
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Eco"; ValueData: """{#PyW}"" -I -X utf8 ""{app}\Eco.pyw"""; Tasks: autostart; Flags: uninsdeletevalue
; Nome antigo: remove a entrada de inicializacao "Jarvis" (aponta para um arquivo que nao existe mais).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Jarvis"; Flags: deletevalue

[Run]
; 1) pacote offline (detectado ao lado do instalador ou passado em /OFFLINEPACK=...): importa e confere o SHA-256
Filename: "{#PyC}"; Parameters: "-I -X utf8 ""{app}\eco_boot.py"" setup --offline ""{code:OfflinePackPath}"" --components {code:ComponentsCsv}"; WorkingDir: "{app}"; StatusMsg: "{cm:StatusImport}"; Flags: runhidden waituntilterminated; Check: HasOfflinePack
; 2) download durante a instalacao: so com /DOWNLOADMODELS=1 (o assistente de primeira execucao baixa com progresso)
Filename: "{#PyC}"; Parameters: "-I -X utf8 ""{app}\eco_boot.py"" setup --fetch --components {code:ComponentsCsv}"; WorkingDir: "{app}"; StatusMsg: "{cm:StatusFetch}"; Flags: runhidden waituntilterminated; Check: WantDownloadNow
; 3) assistente de configuracao (primeira execucao ou reparo)
Filename: "{#PyW}"; Parameters: "-I -X utf8 ""{app}\Eco.pyw"" setup"; WorkingDir: "{app}"; Description: "{cm:RunSetup}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Lixo gerado em execucao (pycache etc.). Dados do usuario (data, models, logs, config.toml) sao tratados em [Code], com pergunta.
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\bin"

[CustomMessages]
ptbr.TypeFull=Completa (recomendada)
ptbr.TypeCustom=Personalizada
ptbr.CompCore=Eco (programa, Python embutido e servidor de modelo Vulkan)
ptbr.CompVision=Modelo de visão e linguagem Qwen3-VL 4B (~3 GB, baixado depois)
ptbr.CompVoice=Voz do Eco em português (~65 MB, baixada depois)
ptbr.CompStt=Reconhecimento de fala (Whisper, baixado depois)
ptbr.CompSttSmall=Whisper small: melhor precisão (~490 MB) - recomendado
ptbr.CompSttBase=Whisper base: mais leve e rápido (~150 MB)
ptbr.TaskGroupShortcuts=Atalhos:
ptbr.TaskGroupStartup=Inicialização:
ptbr.TaskDesktop=Criar atalho na Área de Trabalho
ptbr.TaskStartMenu=Criar atalhos no Menu Iniciar
ptbr.TaskAutostart=Iniciar o Eco com o Windows
ptbr.IconRun=Abrir o Eco
ptbr.IconSettings=Eco - Configurações
ptbr.IconRepair=Reparar ou reconfigurar o Eco
ptbr.IconUninstall=Desinstalar o Eco
ptbr.StatusImport=Importando modelos do pacote offline e conferindo o SHA-256...
ptbr.StatusFetch=Baixando e conferindo os modelos (pode demorar)...
ptbr.RunSetup=Abrir o assistente de configuração (baixa os modelos e testa o som)
ptbr.ReqTitle=Requisitos do computador
ptbr.ReqSub=Conferimos o seu PC. Isto é só informativo: nada será alterado e nenhum driver será mexido.
ptbr.ReqIntro=Resultado da verificação:
ptbr.ReqOs=Windows: compilação %1 (mínimo 19044 = Windows 10 21H2)  [OK]
ptbr.ReqRamOk=Memória: %1 GB  [OK]
ptbr.ReqRamLow=Memória: %1 GB  [AVISO] o recomendado é 16 GB (mínimo 12 GB). O Eco pode ficar lento.
ptbr.ReqDisk=Disco: %1 GB livres em %2 (modelos de IA ocupam ~3,5 GB e são baixados depois)  [%3]
ptbr.ReqGpu=Placa de vídeo: %1 (driver %2, de %3)
ptbr.ReqGpuOldDriver=   [AVISO] driver com mais de 3 anos. Só um aviso: atualizar pelo site do fabricante pode melhorar a velocidade. Este instalador não mexe em drivers.
ptbr.ReqGpuNone=Placa de vídeo: não consegui listar (isso não impede a instalação). O assistente de configuração testa o Vulkan de verdade.
ptbr.ReqVulkanOk=Vulkan: vulkan-1.dll encontrado  [OK]
ptbr.ReqVulkanMissing=Vulkan: vulkan-1.dll NÃO encontrado  [AVISO] sem Vulkan o Eco usa a CPU (bem mais lento). Instale o driver de vídeo do fabricante.
ptbr.ReqProceed=Continuar mesmo assim
ptbr.ReqRamAsk=Este PC tem menos de 12 GB de memória. O Eco pode funcionar mal. Deseja continuar a instalação?
ptbr.AskPurgeData=Deseja APAGAR também os seus dados do Eco (memória e conversas, gravações da sua voz, configuração e logs)?%n%nEscolha "Não" para mantê-los (recomendado): uma reinstalação os reaproveita.
ptbr.AskPurgeModels=Remover também os modelos de IA baixados (~3,5 GB)? Eles podem ser baixados de novo depois.
ptbr.PurgeNote=Dados apagados conforme a sua escolha.

en.TypeFull=Full (recommended)
en.TypeCustom=Custom
en.CompCore=Eco (program, embedded Python and Vulkan model server)
en.CompVision=Qwen3-VL 4B vision-language model (~3 GB, downloaded later)
en.CompVoice=Eco Portuguese voice (~65 MB, downloaded later)
en.CompStt=Speech recognition (Whisper, downloaded later)
en.CompSttSmall=Whisper small: better accuracy (~490 MB) - recommended
en.CompSttBase=Whisper base: lighter and faster (~150 MB)
en.TaskGroupShortcuts=Shortcuts:
en.TaskGroupStartup=Startup:
en.TaskDesktop=Create a Desktop shortcut
en.TaskStartMenu=Create Start Menu shortcuts
en.TaskAutostart=Start Eco with Windows
en.IconRun=Open Eco
en.IconSettings=Eco - Settings
en.IconRepair=Repair or reconfigure Eco
en.IconUninstall=Uninstall Eco
en.StatusImport=Importing models from the offline pack and verifying SHA-256...
en.StatusFetch=Downloading and verifying the models (this can take a while)...
en.RunSetup=Open the setup assistant (downloads the models and tests the sound)
en.ReqTitle=System requirements
en.ReqSub=We checked your PC. Informational only: nothing is changed and no driver is touched.
en.ReqIntro=Check result:
en.ReqOs=Windows: build %1 (minimum 19044 = Windows 10 21H2)  [OK]
en.ReqRamOk=Memory: %1 GB  [OK]
en.ReqRamLow=Memory: %1 GB  [WARNING] 16 GB is recommended (minimum 12 GB). Eco may be slow.
en.ReqDisk=Disk: %1 GB free on %2 (AI models take ~3.5 GB and are downloaded later)  [%3]
en.ReqGpu=Graphics card: %1 (driver %2, from %3)
en.ReqGpuOldDriver=   [WARNING] driver older than 3 years. Just a notice: updating from the vendor's site may improve speed. This installer never touches drivers.
en.ReqGpuNone=Graphics card: could not list (does not block installation). The setup assistant tests Vulkan for real.
en.ReqVulkanOk=Vulkan: vulkan-1.dll found  [OK]
en.ReqVulkanMissing=Vulkan: vulkan-1.dll NOT found  [WARNING] without Vulkan, Eco falls back to the CPU (much slower). Install the vendor's graphics driver.
en.ReqProceed=Continue anyway
en.ReqRamAsk=This PC has less than 12 GB of memory. Eco may run poorly. Do you want to continue installing?
en.AskPurgeData=Do you also want to DELETE your Eco data (memory and conversations, voice recordings, configuration and logs)?%n%nChoose "No" to keep them (recommended): a reinstall reuses them.
en.AskPurgeModels=Also remove the downloaded AI models (~3.5 GB)? They can be downloaded again later.
en.PurgeNote=Data removed according to your choice.

[Code]
type
  TMemoryStatusEx = record
    dwLength: DWORD;
    dwMemoryLoad: DWORD;
    ullTotalPhys: Int64;
    ullAvailPhys: Int64;
    ullTotalPageFile: Int64;
    ullAvailPageFile: Int64;
    ullTotalVirtual: Int64;
    ullAvailVirtual: Int64;
    ullAvailExtendedVirtual: Int64;
  end;

function GlobalMemoryStatusEx(var Buffer: TMemoryStatusEx): BOOL;
  external 'GlobalMemoryStatusEx@kernel32.dll stdcall';

var
  ReqPage: TOutputMsgMemoWizardPage;
  RamLow: Boolean;
  PurgeData, PurgeModels: Boolean;

{ ---------------------------------------------------------------- utilidades }
function TotalRamGB: Integer;
var
  M: TMemoryStatusEx;
begin
  Result := 0;
  M.dwLength := SizeOf(M);
  if GlobalMemoryStatusEx(M) then
    Result := Integer((M.ullTotalPhys + 536870912) div 1073741824);   { arredonda: 15,9 GB -> 16 }
end;

function OfflinePackPath(Param: String): String;
var
  P: String;
begin
  P := ExpandConstant('{param:OFFLINEPACK|}');
  if (P <> '') and (DirExists(P) or FileExists(P)) then begin Result := P; exit; end;
  P := ExpandConstant('{src}\Eco-Modelos');
  if DirExists(P) then begin Result := P; exit; end;
  P := ExpandConstant('{src}\Eco-Modelos.zip');
  if FileExists(P) then begin Result := P; exit; end;
  Result := '';
end;

function HasOfflinePack: Boolean;
begin
  Result := OfflinePackPath('') <> '';
end;

function WantDownloadNow: Boolean;
begin
  Result := (ExpandConstant('{param:DOWNLOADMODELS|0}') = '1') and (not HasOfflinePack);
end;

function ComponentsCsv(Param: String): String;
begin
  Result := '';
  if WizardIsComponentSelected('vision') then Result := Result + 'vision,';
  if WizardIsComponentSelected('voice') then Result := Result + 'voice,';
  if WizardIsComponentSelected('stt\base') then Result := Result + 'stt_base,'
  else if WizardIsComponentSelected('stt\small') or WizardIsComponentSelected('stt') then Result := Result + 'stt_small,';
  if Result <> '' then Delete(Result, Length(Result), 1) else Result := 'vision,voice,stt_small';
end;

function Pipe(const S: String; Idx: Integer): String;
var
  I, N: Integer;
  Cur: String;
begin
  Result := '';
  N := 0;
  Cur := '';
  for I := 1 to Length(S) do
    if S[I] = '|' then begin
      if N = Idx then begin Result := Cur; exit; end;
      N := N + 1;
      Cur := '';
    end else Cur := Cur + S[I];
  if N = Idx then Result := Cur;
end;

{ Lista as placas de video (so leitura). Cada linha: Nome|Versao do driver|Ano do driver }
function GpuLines: TArrayOfString;
var
  Tmp, Args: String;
  Code: Integer;
  Lines: TArrayOfString;
begin
  SetArrayLength(Result, 0);
  Tmp := ExpandConstant('{tmp}\eco-gpu.txt');
  DeleteFile(Tmp);
  Args := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_VideoController | ForEach-Object { $y = 0; if ($_.DriverDate) { $y = $_.DriverDate.Year }; $_.Name + ''|'' + $_.DriverVersion + ''|'' + $y } | Out-File -Encoding ascii -FilePath ''' + Tmp + '''"';
  if Exec('powershell.exe', Args, '', SW_HIDE, ewWaitUntilTerminated, Code) and FileExists(Tmp) then
    if LoadStringsFromFile(Tmp, Lines) then
      Result := Lines;
end;

function BuildRequirements: String;
var
  V: TWindowsVersion;
  Gpus: TArrayOfString;
  I, Ram, NowYear, Y: Integer;
  FreeMB, TotalMB: Cardinal;
  FreeGB: Integer;
  Drive, Status, Txt, Name, Drv: String;
begin
  GetWindowsVersionEx(V);
  Txt := FmtMessage(CustomMessage('ReqOs'), [IntToStr(V.Build)]) + #13#10;
  Ram := TotalRamGB;
  RamLow := Ram < 12;
  if RamLow then Txt := Txt + FmtMessage(CustomMessage('ReqRamLow'), [IntToStr(Ram)]) + #13#10
  else Txt := Txt + FmtMessage(CustomMessage('ReqRamOk'), [IntToStr(Ram)]) + #13#10;
  Drive := ExtractFileDrive(WizardDirValue) + '\';
  FreeGB := 0;
  if GetSpaceOnDisk(Drive, True, FreeMB, TotalMB) then FreeGB := FreeMB div 1024;
  if FreeGB >= 6 then Status := 'OK' else Status := '!';
  Txt := Txt + FmtMessage(CustomMessage('ReqDisk'), [IntToStr(FreeGB), Drive, Status]) + #13#10;
  Gpus := GpuLines;
  if GetArrayLength(Gpus) = 0 then Txt := Txt + CustomMessage('ReqGpuNone') + #13#10
  else begin
    NowYear := StrToIntDef(GetDateTimeString('yyyy', #0, #0), 2026);
    for I := 0 to GetArrayLength(Gpus) - 1 do begin
      Name := Pipe(Gpus[I], 0);
      Drv := Pipe(Gpus[I], 1);
      Y := StrToIntDef(Trim(Pipe(Gpus[I], 2)), 0);
      if Name = '' then continue;
      Txt := Txt + FmtMessage(CustomMessage('ReqGpu'), [Name, Drv, IntToStr(Y)]) + #13#10;
      if (Y > 0) and (NowYear - Y >= 3) then Txt := Txt + CustomMessage('ReqGpuOldDriver') + #13#10;
    end;
  end;
  if FileExists(ExpandConstant('{sys}\vulkan-1.dll')) then Txt := Txt + CustomMessage('ReqVulkanOk') + #13#10
  else Txt := Txt + CustomMessage('ReqVulkanMissing') + #13#10;
  Result := Txt;
end;

procedure InitializeWizard;
begin
  ReqPage := CreateOutputMsgMemoPage(wpSelectTasks, CustomMessage('ReqTitle'), CustomMessage('ReqSub'),
    CustomMessage('ReqIntro'), '');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = ReqPage.ID then
    ReqPage.RichEditViewer.Lines.Text := BuildRequirements;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = ReqPage.ID) and RamLow then
    Result := (MsgBox(CustomMessage('ReqRamAsk'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES);
end;

{ ---------------------------------------------------------------- pos-instalacao }
procedure HardenDataDir(const Dir: String);
var
  Code: Integer;
begin
  { Por usuario: tira a heranca e deixa so o usuario atual e o SYSTEM }
  Exec(ExpandConstant('{sys}\icacls.exe'), '"' + Dir + '" /inheritance:r /grant:r "' + GetUserNameString + ':(OI)(CI)F" /grant:r *S-1-5-18:(OI)(CI)F',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

procedure WriteInstallInfo;
var
  Dir, Json, Comps: String;
begin
  Dir := ExpandConstant('{app}\data\setup');
  ForceDirectories(Dir);
  Comps := ComponentsCsv('');
  StringChange(Comps, ',', '", "');
  Json := '{"version": "{#AppVersion}", "components": ["' + Comps + '"], "mode": "';
  if IsAdminInstallMode then Json := Json + 'machine' else Json := Json + 'user';
  Json := Json + '"}';
  SaveStringToFile(Dir + '\install.json', Json, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if CurStep = ssPostInstall then begin
    WriteInstallInfo;
    if not IsAdminInstallMode then begin
      HardenDataDir(ExpandConstant('{app}\data'));
      HardenDataDir(ExpandConstant('{app}\logs'));
    end else
      { Por maquina: usuarios comuns precisam criar/substituir config.toml na raiz (gravacao atomica) sem poder alterar o codigo }
      Exec(ExpandConstant('{sys}\icacls.exe'), '"' + ExpandConstant('{app}') + '" /grant "*S-1-5-32-545:(NP)(RX,WD,AD,DC)"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
  if CurStep = ssDone then
    FileCopy(ExpandConstant('{log}'), ExpandConstant('{app}\logs\install.log'), False);
end;

{ ---------------------------------------------------------------- desinstalacao }
function InitializeUninstall: Boolean;
begin
  Result := True;
  PurgeData := False;
  PurgeModels := True;
  if UninstallSilent then begin
    PurgeData := ExpandConstant('{param:PURGEDATA|0}') = '1';
    PurgeModels := ExpandConstant('{param:KEEPMODELS|0}') <> '1';
  end else begin
    PurgeData := MsgBox(CustomMessage('AskPurgeData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
    PurgeModels := MsgBox(CustomMessage('AskPurgeModels'), mbConfirmation, MB_YESNO) = IDYES;
  end;
end;

procedure DeleteConfigFiles(const AppDir: String);
var
  FR: TFindRec;
begin
  if FindFirst(AppDir + '\config.toml*', FR) then
    try
      repeat
        DeleteFile(AppDir + '\' + FR.Name);
      until not FindNext(FR);
    finally
      FindClose(FR);
    end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDir: String;
begin
  if CurUninstallStep <> usPostUninstall then exit;
  AppDir := ExpandConstant('{app}');
  { Iniciar com o Windows (inclusive se o assistente o ligou depois): sempre removido }
  RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Eco');
  RegDeleteValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Eco');
  if PurgeModels then DelTree(AppDir + '\models', True, True, True);
  if PurgeData then begin
    DelTree(AppDir + '\data', True, True, True);
    DelTree(AppDir + '\logs', True, True, True);
    DeleteConfigFiles(AppDir);
    RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Eco');
  end;
  DelTree(AppDir + '\__pycache__', True, True, True);
  RemoveDir(AppDir);   { só remove se estiver vazia: o que o usuário escolheu manter fica }
end;
