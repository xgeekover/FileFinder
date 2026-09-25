; Inno Setup 6 Script for FileFinder
; Builds FileFinder-Setup-x64.exe installer for 64-bit Windows

#define MyAppName "FileFinder"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "FileFinder Contributors"
#define MyAppURL "https://github.com/filefinder/filefinder"
#define MyAppExeName "FileFinder.exe"
#define MyAppAssocName MyAppName + " Search"
#define MyAppAssocExt ".filefinder"
#define MyAppAssocKey StringChange(MyAppAssocName, " ", "") + MyAppAssocExt

[Setup]
; Unique application GUID for updates and uninstallation
AppId={{8B5C7D21-9F3E-4B7C-A5A4-9C21C941D780}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=FileFinder-Setup-x64
SetupIconFile=..\resources\icons\app_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion=1.0.0.0
VersionInfoCompany=FileFinder Contributors
VersionInfoDescription=FileFinder - Cross-Platform File Content Search Tool
VersionInfoProductVersion=1.0.0.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "contextmenu"; Description: "Add 'Search with FileFinder' to Explorer context menu"; GroupDescription: "Explorer Integration:"

[Files]
Source: "..\dist\FileFinder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:ProgramOnTheWeb,{#MyAppName}}"; Filename: "{#MyAppURL}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Windows Explorer folder context menu integration: Search with FileFinder
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FileFinder"; ValueType: string; ValueData: "Search with FileFinder"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FileFinder"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FileFinder\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" --path ""%V"""; Tasks: contextmenu

; Windows Explorer background context menu integration
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\FileFinder"; ValueType: string; ValueData: "Search with FileFinder"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\FileFinder"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\FileFinder\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" --path ""%V"""; Tasks: contextmenu

; Windows Explorer drive context menu integration
Root: HKCU; Subkey: "Software\Classes\Drive\shell\FileFinder"; ValueType: string; ValueData: "Search with FileFinder"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Drive\shell\FileFinder"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Drive\shell\FileFinder\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" --path ""%V"""; Tasks: contextmenu

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
