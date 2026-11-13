# What was tested on paper

bobina's defaults come from printed and photographed tests (docs/printers/). A few features are implemented from
the ESC/POS specification and tested on the bytes only, because the printer bobina was built on does not need them
(it takes UTF-8 and has no cutter). They are marked **⚠ not tested on paper** here and in the docs sections, a job
that uses one gets the note `P301`, and `bobina profile show` lists the ones a profile turns on.

The list lives in `src/bobina/features.py`: when a feature is confirmed on a real printer, set `tested_on_paper`
there with the evidence (printer, date, what was printed), and the mark and the note go away.

| Feature | Tested on paper | Where it is used |
|---|---|---|
| Native text, buttons and lists in UTF-8 | ✅ Goldensky MTP-II (docs/printers/mtp-ii-58.md) | the measured profile `mtp-ii-58` |
| Raster images, QR (native and raster), codes on the MTP-II | ✅ MTP-II | every profile |
| Feeds after images as white raster rows (safe mode) | ✅ MTP-II, 08/11 | every profile not calibrated with `bobina calibrate feed` |
| `--marks` cut and tear lines | ✅ MTP-II, 08/11 | any profile, when asked |
| Label by label (`--step`): one send per label, the Bluetooth link closed while you tear | ✅ MTP-II, 13/11 (3 labels, 20 s and 60 s idle between them: each whole, above the tear bar) | any print of several labels at a terminal |
| native text through code pages (ESC t) | ⚠ not tested on paper | profiles with `encoding = "codepage"` (most imported profiles) |
| automatic cutter (GS V) where a label ends (not between --compact labels: glued on purpose) | ⚠ not tested on paper | profiles with `cutter = "full"` or `"partial"` |
| native barcodes (GS k) on an imported profile | ⚠ not tested on paper | imported profiles whose printer has barcode commands |
| Imported printer profiles as a whole | ⚠ not tested on paper (model facts only) | every profile with `measured = false` |

Have one of these printers? Print `bobina calibrate tear`, `bobina calibrate feed` and a label with accents and a
barcode, and say what came out.

## Payment codes

A payment QR code prints fine on any printer; what needs a test is the **app**: a banking app, wallet or payment
app must read the printed code and show the right receiver and amount. The payloads follow each scheme's
specification and are checked against reference examples, but only the ones below marked ✅ were scanned by the
real app. The others give the note `P302` and read **⚠ not tested in a payment app** in FORMAT §6.3 and
`bobina help pay`. The list lives in `SCHEMES` in `src/bobina/pay.py` (`tested=` with the evidence).

| Scheme | Tested in the app |
|---|---|
| `pix` | ✅ Brazilian banking apps, MTP-II, 05/11 (CPF, e-mail and phone keys) |
| `picpay`, `mercadopago`, `paypal`, `wise`, `revolut` | ✅ each app, MTP-II, 09/11: opened the pay or profile screen |
| `bitcoin` | ✅ a bitcoin wallet, MTP-II, 09/11: address and amount read |
| `upi`, `epc`, `promptpay`, `paynow`, `lightning`, `cashapp`, `venmo` | ⚠ not tested in a payment app (apps used outside Brazil) |
| `other` | ⚠ reprinted as pasted, never checked |

Live somewhere these apps are used? Print `bobina help pay`'s example for your scheme, scan it with your app and
say what it showed.

## Contact codes

A contact code is a plain QR of the network's public link (or a vCard / MeCard), so any phone camera reads it;
what needs a test is the **app**: the link must open the right chat or profile. The links follow each network's
published format (`source=` in `NETWORKS`, `src/bobina/contact.py`), but none was scanned with the real app yet:
each gives the note `P303` and reads **⚠ not tested in the app** in `bobina help contact` and
[contact.md](contact.md). When one is, set `tested=` there with the evidence.

| Networks | Tested in the app |
|---|---|
| `whatsapp`, `telegram`, `signal`, `wechat`, `line`, `viber`, `kakao`, `kik`, `messenger`, `discord` | ⚠ not tested in the app |
| `instagram`, `facebook`, `threads`, `tiktok`, `x`, `youtube`, `linkedin`, `vk`, `snapchat`, `pinterest`, `reddit`, `twitch`, `spotify`, `baidu` | ⚠ not tested in the app |
| `phone`, `sms`, `email`, `vcard`, `mecard` | ⚠ not tested with a phone camera |
