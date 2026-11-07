; Inno Setup script for the RJClip installer (unsigned).
; It wraps the portable package folder that build_portable.ps1 makes, so the installed app
; is exactly the one CI smoke-tests. Built in CI with:
;   iscc /DAppVersion=0.17.<run> /DSourceDir=<repo>\portable\RJClip /DOutDir=<repo>\portable scripts\windows\rjclip.iss
;
; Installs for the current user only (no admin prompt) into %LOCALAPPDATA%\Programs\RJClip.
; Your projects are NOT in that folder (they stay in %USERPROFILE%\RJClipWorkspace), so
; uninstalling or installing a newer version never touches them.

#ifndef AppVersion
  #define AppVersion "0.17.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\portable\RJClip"
#endif
#ifndef OutDir
  #define OutDir "..\..\portable"
#endif

[Setup]
AppId={{6B1D2C4E-8F3A-4C59-9E7B-52A1D0C3F8E1}
AppName=RJClip
AppVersion={#AppVersion}
AppPublisher=RJClip
AppComments=Local-first AI video editor for YouTube
DefaultDirName={localappdata}\Programs\RJClip
DisableDirPage=yes
DefaultGroupName=RJClip
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=RJClip-Setup-win64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=RJClip
CloseApplications=yes
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Put an RJClip shortcut on the desktop"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\RJClip"; Filename: "{app}\RJClip.bat"; WorkingDir: "{app}"; Comment: "Start RJClip (close its window to stop it)"
Name: "{autodesktop}\RJClip"; Filename: "{app}\RJClip.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\RJClip.bat"; WorkingDir: "{app}"; Description: "Start RJClip now"; Flags: postinstall nowait skipifsilent shellexec

[UninstallRun]
; stop a running copy so its files can be removed (only RJClip's own python.exe)
Filename: "powershell.exe"; Parameters: "-NoProfile -Command ""Get-Process python -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -like '{app}\*' } | Stop-Process -Force"""; Flags: runhidden; RunOnceId: "StopRJClip"

[UninstallDelete]
; files Python makes while running (__pycache__ etc.). The folder is RJClip's own (the
; install page can't change it), and your projects live elsewhere.
Type: filesandordirs; Name: "{app}"
