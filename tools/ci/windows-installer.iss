; Inno Setup 6 script for JasperEngine Editor (Windows x64).
; Built after `tools/ci/windows.sh editor` installs into instdir/bin.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#ifndef NumericVersion
  #define NumericVersion "0.0.0.0"
#endif
#ifndef AppURL
  #define AppURL "https://github.com/Arakuma-Studio/JasperEngine"
#endif
#ifndef BinDir
  #define BinDir "..\..\instdir\bin"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "JasperEngine-" + AppVersion + "-windows-x64-setup"
#endif

[Setup]
AppId={{7D8B4B3F-9E2E-4C4D-9B2B-6C3E1A5F8D10}
AppName=JasperEngine
AppVersion={#AppVersion}
AppVerName=JasperEngine {#AppVersion}
AppPublisher=JasperEngine Community
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\JasperEngine
DefaultGroupName=JasperEngine
AllowNoIcons=yes
LicenseFile=..\..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
SetupIconFile=..\..\editor\resources\icons\jasperengine-editor.ico
UninstallDisplayIcon={app}\jasperengine-editor.exe
UninstallDisplayName=JasperEngine
VersionInfoVersion={#NumericVersion}
VersionInfoCompany=JasperEngine Community
VersionInfoDescription=JasperEngine Editor Installer
VersionInfoProductName=JasperEngine
VersionInfoProductVersion={#NumericVersion}
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#BinDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef VCRedistPath
Source: "{#VCRedistPath}"; DestDir: "{tmp}"; DestName: "vc_redist.x64.exe"; Flags: deleteafterinstall; Check: NeedsVCRedist
#endif

[Icons]
Name: "{group}\JasperEngine"; Filename: "{app}\jasperengine-editor.exe"
Name: "{group}\{cm:UninstallProgram,JasperEngine}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\JasperEngine"; Filename: "{app}\jasperengine-editor.exe"; Tasks: desktopicon

[Run]
#ifdef VCRedistPath
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /passive /norestart"; StatusMsg: "Installing Microsoft Visual C++ Redistributable..."; Flags: shellexec waituntilterminated; Check: NeedsVCRedist
#endif
Filename: "{app}\jasperengine-editor.exe"; Description: "{cm:LaunchProgram,JasperEngine}"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsVCRedist: Boolean;
begin
  Result :=
    (not FileExists(ExpandConstant('{sys}\vcruntime140.dll'))) or
    (not FileExists(ExpandConstant('{sys}\vcruntime140_1.dll'))) or
    (not FileExists(ExpandConstant('{sys}\msvcp140.dll')));
end;
