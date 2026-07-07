; Inno Setup script for Chibi
; ffmpeg.exe / ffprobe.exe are already embedded inside Chibi.exe
; (build_exe.bat bundles them via --add-binary), so this installer just
; ships the one exe.
; 1. Install Inno Setup (free): https://jrsoftware.org/isinfo.php
; 2. Build the exe first: run build_exe.bat (with bin\ffmpeg.exe and
;    bin\ffprobe.exe in place) so dist\Chibi.exe exists.
; 3. Open this file in Inno Setup and click Build, or run:
;      "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

#define MyAppName "Chibi"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Godfrey Joseph Sule"
#define MyAppURL "https://github.com/odafe32/"
#define MyAppExeName "Chibi.exe"

[Setup]
AppId={{B3B6E3B0-6F4E-4C2A-9C36-VIDEOCOMPRESS}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=ChibiSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} — by {#MyAppPublisher}
LicenseFile=LICENSE.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist\Chibi.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\{#MyAppPublisher} on GitHub"; Filename: "{#MyAppURL}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
