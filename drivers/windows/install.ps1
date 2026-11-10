# install.ps1 - install the bobina58 driver and point a printer queue at it. Run elevated:
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Queue "MTP-II (Bluetooth)"] [-Port COM9:]
# Uses the classic AddPrinterDriverEx path (like vendor installers do): the GPD is a text file and every
# binary is Windows' own Unidrv, already present, so no driver-store import or package signature is involved.
param([string]$Queue = "MTP-II (Bluetooth)", [string]$Port = "COM9:")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$model = "bobina 58mm ESC/POS raster"
$env64 = if ([Environment]::Is64BitOperatingSystem) { "Windows x64" } else { "Windows NT x86" }

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class BobinaSpool {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct DRIVER_INFO_3 {
        public uint cVersion;
        public string pName;
        public string pEnvironment;
        public string pDriverPath;
        public string pDataFile;
        public string pConfigFile;
        public string pHelpFile;
        public string pDependentFiles;
        public string pMonitorName;
        public string pDefaultDataType;
    }
    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool AddPrinterDriverExW(string server, uint level, ref DRIVER_INFO_3 info, uint flags);
    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool GetPrinterDriverDirectoryW(string server, string env, uint level, StringBuilder buf, uint cb, out uint needed);
}
"@

$sb = New-Object System.Text.StringBuilder 520
$needed = 0
if (-not [BobinaSpool]::GetPrinterDriverDirectoryW($null, $env64, 1, $sb, 1040, [ref]$needed)) {
    throw "GetPrinterDriverDirectory failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
}
$drvDir = $sb.ToString()                      # ...\spool\drivers\x64
$unidrv = @("UNIDRV.DLL", "UNIDRVUI.DLL", "UNIRES.DLL", "STDNAMES.GPD", "TTFSUB.GPD", "UNIDRV.HLP")
foreach ($f in $unidrv) {                     # Windows' own copies, same version: nothing is replaced
    $src = Join-Path $drvDir "3\$f"
    if (-not (Test-Path $src)) { throw "missing $src (is Generic / Text Only or another Unidrv driver installed?)" }
    Copy-Item $src $drvDir -Force
}
Copy-Item (Join-Path $here "bobina58.gpd") $drvDir -Force
Remove-Item (Join-Path $drvDir "3\bobina58.bud") -ErrorAction SilentlyContinue   # cached compile of an older GPD

$info = New-Object BobinaSpool+DRIVER_INFO_3
$info.cVersion = 3
$info.pName = $model
$info.pEnvironment = $env64
$info.pDriverPath = "UNIDRV.DLL"
$info.pDataFile = "bobina58.gpd"
$info.pConfigFile = "UNIDRVUI.DLL"
$info.pHelpFile = "UNIDRV.HLP"
$info.pDependentFiles = "UNIRES.DLL`0STDNAMES.GPD`0TTFSUB.GPD`0`0"
$APD_COPY_ALL_FILES = 0x4             # GPD is replaced; Unidrv files are the same version
if (-not [BobinaSpool]::AddPrinterDriverExW($null, 3, [ref]$info, $APD_COPY_ALL_FILES)) {
    $e = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    throw "AddPrinterDriverEx failed: $e ($((New-Object ComponentModel.Win32Exception $e).Message))"
}
foreach ($f in $unidrv + "bobina58.gpd") { Remove-Item (Join-Path $drvDir $f) -ErrorAction SilentlyContinue }

if (Get-Printer -Name $Queue -ErrorAction SilentlyContinue) {
    Set-Printer -Name $Queue -DriverName $model
} else {
    Add-Printer -Name $Queue -DriverName $model -PortName $Port
}
Get-Printer -Name $Queue | Format-List Name, DriverName, PortName
