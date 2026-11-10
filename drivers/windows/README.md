# Windows driver for 58 mm ESC/POS roll printers

Lets any Windows program (label apps, browsers, Office) print to a 58 mm ESC/POS printer such as the
Goldensky / GOOJPRT MTP-II, over its Bluetooth COM port or USB.

- `bobina58.gpd`: the printer description: 384 dots at 203 dpi, raster with `GS v 0`, 3 mm feed at the start, and
  an 8 mm tear feed at the end. The values come from the measured profile in `docs/printers/mtp-ii-58.md`.
- `bobina58.inf`: installs it on top of Windows' own Unidrv. No vendor binaries, no code: Windows renders and
  halftones the page.
- `install.ps1` / `uninstall.ps1`: run elevated. The driver is unsigned, so it is added with the classic
  `AddPrinterDriverEx` path (the driver store refuses unsigned packages); only Windows' own Unidrv files are used.

**Use the USB cable.** Tested 2026-11-07 on the MTP-II: through USB (`USB001`) the label prints perfectly;
through the Bluetooth virtual COM port the same bytes lose data mid-job (a raster band turns into text), while
the identical file sent by bobina over Bluetooth from Linux prints perfectly. Windows' Bluetooth serial port does
not pace the data for the printer. Point an existing queue at the driver with
`Set-Printer -Name <queue> -DriverName "bobina 58mm ESC/POS raster"`.

Printing through bobina itself (`bobina print`) still gives better results: its dithering and fonts are
calibrated. Use this driver when the content comes from another program.
