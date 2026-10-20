#include "version.iss"

[Setup]
AppId={{4596F8DC-B56E-41DA-BD3E-3E61628936F3}
AppName=Silencio
AppVersion={#AppVersion}
AppPublisher=Silencio
DefaultDirName={localappdata}\Programs\Silencio
DefaultGroupName=Silencio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist
OutputBaseFilename=Silencio-Setup-{#AppVersion}-x64
SetupIconFile=assets\silencio.ico
UninstallDisplayIcon={app}\Silencio.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableDirPage=yes
DisableProgramGroupPage=yes
LicenseFile=vendor\vbcable\readme.txt
CloseApplications=yes
RestartApplications=no
UninstallDisplayName=Silencio
VersionInfoVersion={#WindowsVersion}

[Files]
Source: "..\dist\Silencio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Silencio"; Filename: "{app}\Silencio.exe"
Name: "{userdesktop}\Silencio"; Filename: "{app}\Silencio.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Silencio"; ValueData: """{app}\Silencio.exe"" --background"; Flags: uninsdeletevalue createvalueifdoesntexist

[Run]
Filename: "{app}\Silencio.exe"; Parameters: "--first-run"; Description: "Start Silencio"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\Silencio.exe"; Parameters: "--quit"; Flags: runhidden waituntilterminated; RunOnceId: "CloseSilencio"

[Messages]
WelcomeLabel2=Silencio suppresses background Music and keeps spoken Vocal clear. Audio stays on your computer.%n%nThe app includes everything it needs. If the audio driver is missing, Windows will ask for administrator permission on first launch. A restart may be required.

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  AppPath: String;
begin
  Result := '';
  AppPath := ExpandConstant('{app}\Silencio.exe');
  if FileExists(AppPath) then
  begin
    if not Exec(AppPath, '--quit', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Result := 'Could not close Silencio. Quit Silencio and try again.'
    else if ResultCode <> 0 then
      Result := 'Silencio is still restoring playback. Wait a moment and try again.';
  end;
end;
