; Inno Setup script. Build dist\ADBFinder.exe with PyInstaller first (see README).
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
; AppId identifies the application across upgrades: never change it.
AppId={{35BA3641-0087-4499-BEA7-73BD94A0AC37}
AppName=ADBFinder
AppVersion={#AppVersion}
AppPublisherURL=https://github.com/njpd57/ADBFinder
DefaultDirName={autopf}\ADBFinder
DisableProgramGroupPage=yes
; Per-user install by default, so no administrator rights are needed.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\ADBFinder.exe
OutputDir=..\dist
OutputBaseFilename=ADBFinder-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ADBFinder.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\ADBFinder"; Filename: "{app}\ADBFinder.exe"
Name: "{autodesktop}\ADBFinder"; Filename: "{app}\ADBFinder.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ADBFinder.exe"; Description: "{cm:LaunchProgram,ADBFinder}"; Flags: nowait postinstall skipifsilent
