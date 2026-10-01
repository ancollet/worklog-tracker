; Inno Setup script for Worklog. Compile with Inno Setup (https://jrsoftware.org/isinfo.php)
; after running build.ps1:
;   iscc packaging\windows\installer.iss
; Produces packaging\windows\output\WorklogSetup.exe — that's the file colleagues run.
; No admin rights needed: installs per-user into %LocalAppData%\Programs\Worklog.

#define MyAppName "Worklog"
#define MyAppVersion "0.1.0"
#define MyAppExeName "Worklog.exe"

[Setup]
AppId={{B6B6E6F0-4B7E-4B8A-9C3B-9B5C6A2B7B21}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=WorklogSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Symbole:"

[Files]
Source: "..\..\dist\Worklog\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Worklog jetzt starten"; Flags: nowait postinstall skipifsilent
