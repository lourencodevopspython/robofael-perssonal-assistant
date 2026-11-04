; Instalador do Windows (Inno Setup 6): rode pelo construir.ps1, que passa a versão.
; Instala só para o usuário (sem pedir administrador) em %LOCALAPPDATA%\Programs\Robofael. A agenda e as
; preferências ficam em %LOCALAPPDATA%\Robofael e sobrevivem à desinstalação e às atualizações.

#ifndef Versao
  #define Versao "0.0.0"
#endif

[Setup]
AppId={{6F1C2B7E-4E0A-4C55-9C1B-7A2D3E9F5B10}
AppName=Robofael
AppVersion={#Versao}
AppVerName=Robofael {#Versao}
AppPublisher=Rafael Lourenço
AppPublisherURL=https://github.com/lourencodevopspython/robofael-perssonal-assistant
DefaultDirName={localappdata}\Programs\Robofael
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\..\dist\windows
OutputBaseFilename=Robofael-{#Versao}-Instalador
SetupIconFile=..\..\build\windows\robofael.ico
UninstallDisplayIcon={app}\Robofael.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\windows\Robofael\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Robofael"; Filename: "{app}\Robofael.exe"
Name: "{autodesktop}\Robofael"; Filename: "{app}\Robofael.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Robofael.exe"; Description: "{cm:LaunchProgram,Robofael}"; Flags: nowait postinstall skipifsilent

[Registry]
; "Abrir ao entrar no computador" (ligado pela tela de configurações) não sobrevive à desinstalação
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Robofael"; Flags: uninsdeletevalue dontcreatekey

[UninstallDelete]
; O comando "robofael" no terminal (ligado pela tela de configurações)
Type: files; Name: "{localappdata}\Microsoft\WindowsApps\robofael.cmd"
