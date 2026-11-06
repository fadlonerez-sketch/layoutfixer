# Layout Fixer

Typed Hebrew while the keyboard was on English, or the other way round? Press **Ctrl+Space**. The
text in the field you are typing in is converted key-for-key to the other layout, replaced in place,
and the Windows input language is switched, so you can keep typing.

```
typed (keyboard on English):   akuo' nv eurv?
after Ctrl+Space:              שלום, מה קורה?      ← and the keyboard is now Hebrew
```

It works in both directions, runs entirely on your PC (no network, no AI, no translation), and needs
no administrator rights.

**macOS:** the same tool with **⌘ + Fn** as the shortcut - see [README-macOS.md](README-macOS.md). The
package for a Mac is `dist\mac\LayoutFixer-macOS.zip` (built with `build_mac.bat`).

## Install and run

* **Exe:** `dist\LayoutFixer.exe` is a single file. Copy it anywhere, for example
  `%LOCALAPPDATA%\Programs\LayoutFixer\`, and double-click it. A blue **אA** icon appears in the
  tray. The first start opens Settings.
* **From source:** `run.bat` creates `.venv` on first use and starts the app with no console window.
  Needs Python 3.12 or newer.

Both the **Hebrew** and **English** keyboards must be installed in Windows (Settings > Time & language >
Language & region) for the keyboard-language switch. Conversion itself works without them.

### Start at login

Settings > *Start Layout Fixer when I sign in*. This writes a per-user entry under
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` that points at the exe (or at `main.py` when
running from source). If you move the exe, start it once from the new place and the entry is updated.

## Using it

| You do | Layout Fixer converts |
|---|---|
| Select part of the text, press Ctrl+Space | only the selection |
| Nothing selected, press Ctrl+Space | the whole focused text field (up to 10,000 characters; select a part for longer text) |
| Press Ctrl+Space again later | converts back (works as an undo) |

* The direction comes only from the keyboard layout active in that window: on **English** the text is
  converted to what the same keys type on Hebrew, on **Hebrew** to what they type on English. The text
  itself is never analysed. With any other layout active, nothing is changed and a notification says so.
* The optional **Always to Hebrew / Always to English** shortcuts in Settings force a direction.
* A small notification in the bottom-right corner confirms each conversion. It never takes the
  keyboard focus, and you can turn success notifications off.
* In most apps, Ctrl+Z undoes a conversion.

### How the conversion works

The conversion uses the physical key positions of the Windows **US** and **Hebrew** layouts. This is
not translation. The table (`layoutfixer/keymap.py`) was read from Windows itself and the tests
re-check it against the layouts installed on the PC: `t`↔`א`, `c`↔`ב`, `v`↔`ה`, `,`↔`ת`, `.`↔`ץ`,
`;`↔`ף`, `'`↔`,`, `/`↔`.`, `` ` ``↔`;`, `q`↔`/`, `w`↔`'`. On the Hebrew layout, Shift+9 and Shift+0
are mirrored, as are `[ ]`, `{ }` and `< >`.

Every character is converted on its own, in its original order, with no exceptions: letters,
punctuation (`,` → `ת`, `.` → `ץ`, `;` → `ף`), links and numbers alike. Shift works as on the real
layouts: Shift+letter on the Hebrew layout types the Latin capital, so `A` stays `A`. Characters that
have no key on the source layout (digits, spaces, line breaks, emoji, letters of the other script)
stay as they are. Every character maps to exactly one character, so the length never changes.

> Example: `akuo' nv eurv?` → `שלום, מה קורה?`. The text `akuo, vn euxv?` converts key by key to
> `שלוםת המ קוסה?`, because `,` is the key of ת, `vn` the keys of ה-מ and `euxv` those of ק-ו-ס-ה.

## Which apps work

Layout Fixer uses the most precise method each control allows. The text is always read back to check
the result.

| Control | Method | Clipboard / keystrokes |
|---|---|---|
| Standard Windows text boxes and RichEdit (Notepad, WordPad, dialogs, WinForms, Delphi) | Window messages: read, replace only the changed characters, put the caret back where it was. Undoable. | none |
| Browsers (Chrome, Edge, Firefox), Electron apps, WPF, Qt, UWP, Office | UI Automation reads the text (Chromium-based apps get up to 1 s to build their accessibility tree on the first press) and selects exactly the characters to change; the converted text is pasted with Ctrl+V; the result is read back | clipboard backed up and restored |
| Single-value fields without text access | UI Automation `SetValue` | none |
| Apps that expose no text at all | Selection only: Ctrl+C, convert, Ctrl+V | clipboard backed up and restored |

**Never touched:** password fields, read-only text (a web page that is not an input field), terminals
(Windows Terminal, cmd, PowerShell, PuTTY…) and programs running as administrator.

Safety rules:

* Layout Fixer never uses Ctrl+A. The whole field is selected through UI Automation and that
  selection is confirmed before anything is pasted, so a web page or document around the field is
  never selected.
* If the text changes between reading and writing, or the exact range can't be selected, nothing
  is changed and a notification explains why.
* Pictures inside text (emoji images in chat apps, embedded objects) are never pasted over. The words
  around them are replaced separately.
* The clipboard is restored only after the paste is seen in the field, so the app never pastes your
  old clipboard by mistake. If you copy something else in the meantime, your newer copy is kept.
  The temporary text is marked so Windows clipboard history and cloud clipboard ignore it.

## Settings

Tray icon > **Settings** (or click the icon):

* **Fix text** shortcut (default **Ctrl+Space**). Click the field and press the new combination.
* **If that is taken, use** (default **Ctrl+Shift+Space**). This is used automatically, with a
  notification, when another program already owns the main shortcut.
* **Always to Hebrew / Always to English**: optional forced-direction shortcuts.
* Enabled, switch the keyboard language after converting, success notifications, clipboard
  fallback, whole-field limit, start at login.

Settings live in `%APPDATA%\LayoutFixer\settings.json` and the log in `%APPDATA%\LayoutFixer\logs\`
(tray > *Open log folder*). The log never contains your text, only lengths and outcomes.

## Troubleshooting

| Problem | What to do |
|---|---|
| "Ctrl+Space is taken… using Ctrl+Shift+Space" | Another program registered Ctrl+Space globally. Use the fallback, choose another shortcut in Settings, or close the other program and restart Layout Fixer. |
| Ctrl+Space no longer works in VS Code, Excel or Word (autocomplete, select column, clear formatting) | While Layout Fixer is enabled it owns Ctrl+Space system-wide. Disable it from the tray menu, which gives the combination back immediately, or pick another shortcut. |
| "This window belongs to a program running as administrator" | Windows blocks normal programs from changing elevated windows. Run Layout Fixer as administrator if you need that. |
| "Layout Fixer can't read the text in this window" | The app exposes nothing. Select the text first (clipboard fallback), or check that the fallback is enabled in Settings. The log says which step failed (see below). |
| "The active keyboard layout is neither English nor Hebrew" | Switch to the English or Hebrew keyboard first; the direction comes from the active layout. |
| Something else fails | Tray > *Open log folder* > `layoutfixer.log`. Each press logs `hotkey pressed`, then `focus:` (app and control class), `layout:`, `target:`, `read:`, `convert:`, `replace:`, `switch layout:`, or `FAILED at <step>: <reason>`. Only lengths, app names and class names are logged, never your text. |
| "the keyboard was NOT switched" | The app ignored the language-change request. The text is converted; switch with Win+Space. Also check that both keyboards are installed. |
| "Release the shortcut keys and try again" | The modifier keys were still held after 1.5 s. Nothing was changed. |
| Windows says the exe is blocked (Smart App Control or SmartScreen) | The exe is not code-signed. Smart App Control decides per build: on this PC one rebuild was blocked and the next one was allowed. Use *More info > Run anyway* if offered, or run from source with `run.bat` (it uses the signed Python launcher, which Smart App Control allows). |
| The result looks wrong | Press Ctrl+Z in that app, or Ctrl+Space again to convert back. |

## Known limitations

* **Formatting:** in rich editors (Word, Gmail, Outlook) only the changed characters are pasted, as
  plain text, so they take the formatting at that position. Mixed bold/italic inside a single
  converted word is lost.
* **Undo:** native text boxes and pasting apps get a normal undo step. Fields written with
  UI Automation `SetValue` (rare) have none.
* Without a selection, very large fields are refused (default limit 10,000 characters) instead of
  being rewritten whole.
* Apps with custom-drawn text and no accessibility support (some games, remote desktop / VM windows,
  Google Docs' canvas editor) work at best through the selection fallback, or not at all.
* If an app stops responding right after the paste, the converted text is left on the clipboard instead of
  restoring yours, and the notification says so. Restoring then could make the app's late paste insert
  your old clipboard into the text.
* Some application-private clipboard formats (special OLE/GDI data) can't be copied and may not
  survive the backup and restore. Text, HTML, RTF, images and copied files do.
* Ctrl+Space is a global registration. While enabled, other apps don't receive it.

## Development

```
build_exe.bat           venv + tests + PyInstaller + verification  ->  dist\LayoutFixer.exe
run_tests.bat           run the tests (pytest)
run.bat                 run from source
python main.py --selftest report.json     self-test a build on this PC (changes nothing)
python tools\verify_build.py [exe]        exe self-test + tray start-up check (shortcuts disabled)
```

```
layoutfixer/
  keymap.py        physical key table (US / Hebrew)
  converter.py     strict key-for-key conversion; direction from the active layout (pure)
  engine.py        one conversion end to end + dispatcher (one at a time, cooldown)
  targets/         native_edit (Win32 messages), uia_target (UI Automation), clipboard_target (fallback)
  paste.py         clipboard paste with verification; clipboard.py backup/restore
  hotkeys.py       shortcut parsing + RegisterHotKey thread + fallback logic
  win/             ctypes API, focus/privilege, keyboard layouts, SendInput
  win_env.py       picks the strategy for the focused control
  app.py, ui/      tray, settings window, notification
  selftest.py      --selftest
tests/             pytest; tests/hosts/ are hidden test windows in separate processes
```

The tests never press real keys and never touch the real clipboard. Real-Windows tests use hidden
Win32 Edit/RichEdit controls and an off-screen Qt window in separate processes. Each test file's
docstring says which parts are real and which are simulated. An opt-in real clipboard round trip runs
with `set LAYOUTFIXER_REAL_CLIPBOARD_TESTS=1`.

## Test status

`run_tests.bat` runs 219 tests plus 1 opt-in. What they cover:

* **Real Windows:** the key table is compared with the US and Hebrew layouts installed on the PC.
  Real cross-process window messages to standard Edit/RichEdit controls cover whole field, selection,
  CRLF/emoji offsets, password and read-only refusal, undo, and changed-text refusal. The same runs
  against Windows 11 Notepad's own editor class (`RichEditD2DPT`, from a copy of Notepad's
  `riched20.dll` in a hidden window), including the real keyboard-layout switch.
  **Real Chrome** (`tests/test_chrome_real.py`) runs on a hidden Windows desktop with a throw-away
  profile: input, textarea and contenteditable fields, whole field and selection only, through the
  real engine and UI Automation. Only the Ctrl+V there is simulated. Real UI
  Automation runs against Qt line, plain and rich text edits, including a picture inside the text.
  Also real: switching the Windows input language of a window and checking it, RegisterHotKey
  registration and conflict detection (Ctrl+Space included, released at once), the start-at-login
  registry entry (in a test key), and process integrity checks.
* **Simulated:** the Ctrl+C/Ctrl+V keystrokes, the clipboard (a fake with Windows-like sequence
  numbers), hotkey presses (WM_HOTKEY is posted to the hotkey thread), and the focused window.

Not covered by automated tests: pressing the real shortcut, real Ctrl+V into real apps (Chrome, Word,
Teams…), and the real clipboard backup/restore. Check those by hand:

### Manual checklist (about 3 minutes)

1. Start `LayoutFixer.exe`. The tray icon appears and the notification names the shortcut.
2. Notepad, keyboard on English: type `akuo' nv eurv?`, press Ctrl+Space → `שלום, מה קורה?`. Typing
   continues in Hebrew. Press Ctrl+Z → the original text is back.
3. Notepad: type `hello world`, select only `world`, press Ctrl+Space → only that word changes.
4. Chrome or Edge, a search box or a chat box: repeat step 2. Then type `יקךךם` with the keyboard on
   Hebrew and press Ctrl+Space → `hello`, and the keyboard is now English.
5. Copy an image or some formatted text, run step 4 again, then paste somewhere → your original
   clipboard is still there.
6. Click on a web page outside any input box and press Ctrl+Space → a notification says nothing can
   be changed, and the page stays as it was.
7. Press Ctrl+Space twice quickly → it converts once.
8. Tray > uncheck Enabled → Ctrl+Space works normally in other apps again.
