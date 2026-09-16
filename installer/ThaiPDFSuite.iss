; -----------------------------------------------------------------------------
; ตัวติดตั้ง Thai PDF Suite สำหรับ Windows
;
; ติดตั้งลงโฟลเดอร์ของผู้ใช้เป็นค่าเริ่มต้น จึงไม่ต้องขอสิทธิ์ผู้ดูแลเครื่อง
; และผู้ใช้ยังวางไฟล์ภาษาเพิ่มในโฟลเดอร์โปรแกรมได้เองภายหลัง
; ถ้าต้องการติดตั้งให้ผู้ใช้ทุกคนในเครื่อง กดปุ่มเลือกได้ตอนเริ่มติดตั้ง
;
; แปลด้วย:  ISCC.exe installer\ThaiPDFSuite.iss
; -----------------------------------------------------------------------------

#define AppName "Thai PDF Suite"
#define AppVersion "1.0"
#define AppPublisher "Thai PDF Suite"
#define AppExe "ThaiPDFSuite.exe"
#define SrcDir "..\dist\ThaiPDFSuite"

[Setup]
AppId={{7C4E1A93-5B2D-4E88-9F31-A6D0C2E74B15}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}.0.0
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
AllowNoIcons=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=ThaiPDFSuite-Setup-{#AppVersion}
SetupIconFile=..\web\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
MinVersion=10.0

[Languages]
Name: "thai"; MessagesFile: "compiler:Languages\Thai.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "full"; Description: "ติดตั้งทั้งหมด รวมข้อมูลอ่านไฟล์สแกน (แนะนำ)"
Name: "compact"; Description: "เฉพาะโปรแกรมหลัก ประหยัดพื้นที่"
Name: "custom"; Description: "เลือกเอง"; Flags: iscustom

[Components]
Name: "main"; Description: "โปรแกรมหลัก แปลง PDF เป็น Word และ Excel"; \
    Types: full compact custom; Flags: fixed
Name: "ocrdata"; Description: "ข้อมูลภาษาไทยสำหรับอ่านไฟล์สแกน (OCR)"; Types: full

[Tasks]
Name: "desktopicon"; Description: "สร้างทางลัดบนหน้าจอ"; \
    GroupDescription: "ทางลัดเพิ่มเติม"

[Files]
Source: "{#SrcDir}\{#AppExe}"; DestDir: "{app}"; \
    Flags: ignoreversion; Components: main
Source: "{#SrcDir}\_internal\*"; DestDir: "{app}\_internal"; \
    Excludes: "tessdata\*"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "{#SrcDir}\_internal\tessdata\*"; DestDir: "{app}\_internal\tessdata"; \
    Flags: ignoreversion recursesubdirs; Components: ocrdata
Source: "..\README.md"; DestDir: "{app}"; DestName: "คู่มือการใช้งาน.md"; \
    Flags: ignoreversion; Components: main

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\คู่มือการใช้งาน"; Filename: "{app}\คู่มือการใช้งาน.md"
Name: "{group}\ถอนการติดตั้ง {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "เปิดใช้งาน {#AppName} ทันที"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\Thai PDF Suite"
Type: filesandordirs; Name: "{localappdata}\Temp\thai-pdf-suite"

[Code]
function TesseractFound(): Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf}\Tesseract-OCR\tesseract.exe'))
         or FileExists(ExpandConstant('{commonpf32}\Tesseract-OCR\tesseract.exe'))
         or FileExists(ExpandConstant('{localappdata}\Programs\Tesseract-OCR\tesseract.exe'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if (not TesseractFound()) and WizardIsComponentSelected('ocrdata') then
      MsgBox('ติดตั้งเรียบร้อยแล้ว' + #13#10 + #13#10 +
             'โปรแกรมแปลงไฟล์ PDF ที่มีชั้นข้อความได้ทันที' + #13#10 + #13#10 +
             'ส่วนไฟล์ที่เป็นภาพสแกน ยังต้องติดตั้งเครื่องมืออ่านภาพเพิ่มอีกหนึ่งตัว' + #13#10 +
             'เปิด Command Prompt แล้วพิมพ์คำสั่งนี้' + #13#10 + #13#10 +
             '    winget install --id UB-Mannheim.TesseractOCR' + #13#10 + #13#10 +
             'ข้อมูลภาษาไทยติดตั้งไปให้แล้ว จึงไม่ต้องดาวน์โหลดเพิ่ม',
             mbInformation, MB_OK);
  end;
end;
