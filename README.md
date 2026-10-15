# Morse Paddle

Morse Paddle USB interface VBand diagnostics.

This Python project captures raw HID reports from a USB paddle interface, records raw and
debounced paddle transitions, flags likely contact bounce, and translates accepted dit/dah
events into Morse letters. It can be exercised entirely with simulated input before connecting
to hardware.

## Quick start

1. Open this folder in VS Code.
2. Select the `.venv` interpreter if VS Code does not select it automatically.
3. Run **Terminal: Run Task** → **Simulate bouncing paddle**.

Equivalent terminal commands:

```powershell
.\.venv\Scripts\Activate.ps1
morse-paddle simulate --text "SOS TEST" --bounce
pytest
```

The simulator prints every raw edge, rejected bounce transition, accepted symbol, and decoded
character. The final line shows the decoded message and bounce count.

## Monitor the hamradio.solutions PaddleAdapter on Windows

The PaddleAdapter (`VID 0x04D8`, `PID 0x01A6`) can expose several HID collections. Windows
normally reserves keyboard and mouse collections, and opening one of those through hidapi can
produce `OSError: read error`. First list only the PaddleAdapter collections:

```powershell
morse-paddle devices --vid 0x04D8 --pid 0x01A6
```

Each entry includes its collection index, exact HID path, usage page, usage, and interface number.
The listener automatically skips keyboard/mouse collections and probes the remaining collections
in a deterministic order. Start capture with:

```powershell
morse-paddle listen --vid 0x04D8 --pid 0x01A6 --capture captures\paddle.jsonl
```

If automatic selection cannot identify a readable collection, select the index from the filtered
`devices` output:

```powershell
morse-paddle listen --vid 0x04D8 --pid 0x01A6 --collection 1 --capture captures\paddle.jsonl
```

For an exact, stable selection, copy the complete `path=` value and wrap it in single quotes.
Single quotes are important because Windows HID paths contain PowerShell metacharacters such as
`&`. For example:

```powershell
morse-paddle listen --vid 0x04D8 --pid 0x01A6 --path '\\?\hid#vid_04d8&pid_01a6&mi_01&col02#...' --capture captures\paddle.jsonl
```

Use the path printed on your machine; do not type the abbreviated example literally. If every
collection is a keyboard or mouse collection, Windows may prevent hidapi from reading the device.
Close VBand, keyer utilities, browser tabs, or other software that may have exclusive use of the
paddle and retry. The CLI reports this limitation without a Python traceback.

### Capture a protected `\KBD` collection with Windows Raw Input

If the only PaddleAdapter HID path ends in `\KBD`, use the Raw Input backend instead of `listen`.
Raw Input can attribute keyboard events to the exact physical device even though Windows prevents
hidapi from opening the keyboard collection.

First discover the Raw Input path:

```powershell
morse-paddle raw-devices --vid 0x04D8 --pid 0x01A6
```

Then inspect the make/break events while pressing each paddle:

```powershell
morse-paddle raw-listen --vid 0x04D8 --pid 0x01A6 --inspect --capture captures\paddle-keys.jsonl
```

The diagnostic output includes the ordinary scan code, an extended `scan_id`, virtual-key code,
and E0/E1 flags. Extended scan IDs use `0xE000 | scan` for E0 and `0xE100 | scan` for E1. For
example, E0 scan code `0x001D` is selected as `0xE01D`.

After identifying the two codes, map them to dit and dah. Replace the example values with those
reported by `--inspect`:

```powershell
morse-paddle raw-listen --vid 0x04D8 --pid 0x01A6 --dit-scan 0xE01D --dah-scan 0xE038 --diagnostic --capture captures\paddle-raw.jsonl
```

Virtual-key mappings are also supported with `--dit-vkey` and `--dah-vkey`. If more than one Raw
Input keyboard matches, select the filtered index with `--device-index N`, or copy the complete
path from `raw-devices` and pass it in single quotes:

```powershell
morse-paddle raw-listen --path '\\?\HID#VID_04D8&PID_01A6#...' --inspect
```

Raw Input registration **does not suppress normal keystrokes**. Paddle-generated keyboard input
continues to reach the focused application while it is observed and device-filtered by this tool.
Press `Ctrl+C` on the regular keyboard to stop the background Windows message loop cleanly.

The default report mapping treats bit 0 as dit and bit 1 as dah. Adjust `--byte-index`,
`--dit-mask`, and `--dah-mask` to match the interface. Add `--invert` if the contacts are
active-low. Missing capture parent directories are created automatically.

The debounce window defaults to 5 ms. Compare runs with `--debounce-ms 2`, `5`, and `10` to
measure whether apparent extra events are contact bounce or originate in the USB interface.
Press `Ctrl+C` to stop capture.

## Project layout

```text
.vscode/                 VS Code interpreter, launch, task, and extension settings
captures/                Optional JSON Lines diagnostic captures
src/morse_paddle/
  cli.py                  Command-line entry point
  debounce.py             Per-contact debounce and bounce accounting
  decoder.py              Morse symbol and character translation
  hid_source.py           HID enumeration and report capture
  raw_keyboard.py         Portable Raw Input device selection and key mapping
  _win_raw_input.py       Windows ctypes Raw Input discovery and message loop
  simulator.py            Repeatable simulated reports, including contact bounce
tests/                    Unit tests for decoding and debounce behavior
```

## Diagnostic model

Each HID report is timestamped with `time.perf_counter_ns()`. A transition is accepted only
after the new electrical state remains stable for the configured debounce window. A transition
that returns to the accepted state before that window expires is counted as bounce. Accepted
presses become dots or dashes; elapsed time between presses determines letter and word gaps.

For definitive timing analysis, use a raw capture and confirm the HID report mapping before
drawing conclusions about the mechanical contacts.
