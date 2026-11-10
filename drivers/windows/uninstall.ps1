# uninstall.ps1 - put the queue back on Generic / Text Only and remove the bobina58 driver. Run elevated.
param([string]$Queue = "MTP-II (Bluetooth)")
$model = "bobina 58mm ESC/POS raster"
if (Get-Printer -Name $Queue -ErrorAction SilentlyContinue) { Set-Printer -Name $Queue -DriverName "Generic / Text Only" }
Remove-PrinterDriver -Name $model -ErrorAction SilentlyContinue
Get-PrinterDriver | Where-Object Name -like "bobina*"
