; Inno Setup script for pyflashgui. Built by build.cmd after PyInstaller.
;
; Installs the one-directory PyInstaller build, so Qt and libusb stay as
; separate replaceable DLLs -- what the LGPL asks for -- while the user sees a
; single Start menu entry and an uninstaller.
;
; Download Inno Setup from https://jrsoftware.org/isinfo.php if it is missing.

#define AppName "pyflashgui"
#define AppPublisher "davhodg"
#define AppURL "https://github.com/davhodg/pyflashgui"
#define AppExe "pyflashgui.exe"
; build.cmd passes both, from build\version.py. 0.0.0 marks an installer
; compiled by hand, which has no version to give it.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef FileVersion
  #define FileVersion "0.0.0.0"
#endif

[Setup]
AppId={{B4E6A1D2-58C7-4F0B-A3E9-6D1F2C8B9A47}
AppName={#AppName}
AppVersion={#AppVersion}
; The setup.exe's own version resource. The file version is numbers only,
; and its text is cut at 20 characters, so the full version -- -dev and
; commit included -- goes in the product version, which is not.
VersionInfoVersion={#FileVersion}
VersionInfoTextVersion={#FileVersion}
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} installer
VersionInfoProductTextVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
; The third-party notices on the page after the licence, before anything is
; installed: what comes with pyflashgui is worth reading before it is on the
; machine, not on the way to Finish.
InfoBeforeFile=..\THIRD-PARTY-NOTICES.txt
OutputDir=..\dist
OutputBaseFilename=pyflashgui-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; The installer's own icon, and the one Settings > Apps shows for it. The
; shortcuts need nothing: they take theirs from pyflashgui.exe.
SetupIconFile=..\pyflashgui\resources\pyflashgui.ico
UninstallDisplayIcon={app}\{#AppExe}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Setup asks who it is for: everybody, which needs administrator rights and
; is what it suggests, or only the person running it, which needs none.
PrivilegesRequiredOverridesAllowed=dialog commandline

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\pyflashgui\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; An upgrade would otherwise leave the last version's shortcuts beside the
; new ones, named for a version that is no longer installed. The desktop
; pattern needs a digit-dot after the name, so a shortcut of somebody's own
; that happens to start with "pyflashgui " is left alone.
[InstallDelete]
Type: files; Name: "{group}\{#AppName} *.lnk"
Type: files; Name: "{autodesktop}\{#AppName} ?.*.lnk"

; Named with the version: an installed pyflashgui stays the version it is
; until the next installer, unlike a source folder's entry, which starts
; whatever was last pulled and is called plain pyflashgui.
[Icons]
Name: "{group}\{#AppName} {#AppVersion}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Third party notices"; Filename: "{app}\THIRD-PARTY-NOTICES.txt"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName} {#AppVersion}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

[Messages]
; Say plainly that probe drivers are the user's to install
FinishedLabel=pyflashgui is installed.%n%nA CMSIS-DAP v2 probe, such as the Raspberry Pi Debug Probe, needs no driver. Other probes, such as ST-Link, need their vendor's own software, which is not included: install it and pyflashgui will find the probe.%n%nYour workspaces and settings live in %%APPDATA%%\pyflashgui and are left alone by upgrades and by uninstalling.
