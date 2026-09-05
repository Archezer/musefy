#define MyAppName "Musefy"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Archezer"
#define MyAppURL "https://github.com/Archezer/musefy"
#ifndef BundleName
#define BundleName "Musefy"
#endif
#ifndef OutputName
#define OutputName "Musefy-Setup"
#endif

[Setup]
AppId={{A0B5D258-0D37-4CF4-A4F3-7E3CF2E6A861}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\Musefy
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename={#OutputName}
SetupIconFile=..\assets\musefy-mark.ico
UninstallDisplayIcon={app}\Musefy.exe
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern
ChangesAssociations=no
Uninstallable=yes
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\{#BundleName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Musefy"; Filename: "{app}\Musefy.exe"; WorkingDir: "{app}"
Name: "{commondesktop}\Musefy"; Filename: "{app}\Musefy.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Musefy.exe"; Description: "Launch Musefy"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
