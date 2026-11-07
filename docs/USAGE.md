# Using Layout Fixer

How conversion works, which apps are supported, settings and troubleshooting. Install steps are in the [README](../README.md).

## Start at login

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

