# Timeline Reader

A translation layer for Avid Media Composer. Drop in a timeline export and get
clean department reports as spreadsheets — no manual timeline study required.

## Features

### 1. Opticals List
Every clip effect the online house needs during conform — **Resize, 3D Warp,
Timewarp / motion effects, freeze frames, masks, flip/flop, reframes** — with
clip name, source tape, record & source timecode, duration and notes (e.g.
motion speed). Automatic reformats, colour correction, dissolves and titles are
excluded so the list stays focused on true opticals.

> The **Avid bin (`.avb`) is the richest source** and the only one carrying full
> effect data. EDLs contribute motion (`M2`) and transition effects; a
> flattened "AAF Picture" export carries no effects.

### 2. Clip List
An ordered list of every clip in the timeline (record order), with **clip name,
tape/source name, source in/out and record in/out** timecodes plus duration.

### 3. Tag Finder
Finds every clip you tagged with a **timeline clip note** in Media Composer. Prep
a sequence by typing the same word into the clip note (the segment **Comment**) of
each clip you want to collect — say `stock` on every stock-footage shot — then load
the bin here and type that word. The matching clips are listed with their **note,
clip name, tape/source, track and full source/record timecodes**. Matching is a
case-insensitive substring by default, so `stock` finds "stock footage" too; tick
**Exact text matching** to keep only notes that are exactly the tag. Leaving the box
empty lists every tagged clip so you can see what tags a sequence carries. Like the
other reports it has selection-aware stats, row-selection export, **Choose
columns…** and drag-to-reorder headers, and can export the matches as Avid markers
(each marker's comment is the clip note). Note extraction lives in
`timeline_reader/parsers/avb_parser.py` (`_collect_note`).

### 4. Music Tracker
A music cue sheet built from the sound tracks — one row per piece of music with
**Reel, Track (the song name), Artist / Composer, Album, Filename, TC In, TC Out,
Duration**. You tick which sound tracks hold the music (move your music clips onto
those tracks and clear everything else off them first); the report is built by
**merging** the many segments an editor leaves behind — add edits, small nudges,
and a cue checkerboarded across two tracks so it can overlap itself — back into a
single cue. A cue ends only when it falls **silent longer than a set gap**
(default one second) or when a **different piece of music interrupts** it.
**Cross dissolves** on a cue's head/tail are included in its in/out by default
(toggleable).

**Muted clips** (clips on a track muted in Avid's audio mixer — mute is stored
per track, not per clip) are excluded by default; tick **Include muted clips** to
keep them, which adds a **Muted** column flagging them.

The **Reel** is read from the hour field of the record TC In (a sequence starting
at `01:00:00:00` is reel 1); Track, Album and Artist / Composer come from the
clip's bin metadata (the song title, album and `Lead performer(s)/Soloist(s)`
fields). Like the other reports it has the same layout, selection-aware stats,
row-selection export, **Choose columns…** chooser (with an optional Audio Track
column) and drag-to-reorder headers. Music cue merging lives in
`timeline_reader/music.py`.

### 5. Captions → SRT
Converts an **Avid DS Caption (`.txt`)** file into a standard **SubRip (`.srt`)**
subtitle file, with a live preview and a selectable frame rate (including
drop-frame for 29.97 / 59.94). Validated against a real Avid Caption export
(`@ This file written with the Avid Caption plugin` / `<begin subtitles>` form).

### Multi-sequence sources
When a bin or AAF contains more than one sequence, a **Sequence picker** appears
in the report tabs so you can switch which sequence the report is built from —
its video-track count and duration are shown for each.

### Configurable columns
Both report tabs have a **Columns…** button. The built-in columns are on by
default (unchanged from before), and any **metadata found in the source** is
offered as an extra, optional column:

- **Avid bin** — the user bin columns (Scene, Take, Circled, Comment, …),
  derived fields (Project, Format, Origin Bin), the **clip colour** (mapped to a
  nearest Avid colour name) and **marker / locator comments**.
- **Tab-delimited** — any heading not mapped to a standard field.

Tick columns to include or exclude them, and reorder them either by **dragging
a table-header directly** or by dragging a row in the dialog — both change how
the columns appear in the table and the exported spreadsheet. Both the selection
and the order are **remembered per report** (via `QSettings`) so they persist
across files and sessions. "Reset to defaults" restores the shipped set and
order. Column logic lives in `timeline_reader/columns.py`.

Exports default to the **chosen sequence's name** (e.g. `THR_L_260721.csv`).

> Marker/locator extraction is implemented but **unverified** — the sample bin
> contains no markers. It reads `avb.misc.Marker` comments wherever they attach;
> share a bin with locators and it can be confirmed/tuned.

Each report can be **exported to CSV, TSV, Excel (`.xlsx`), OpenDocument
(`.ods`) or Avid Markers (`.txt`)** — SRT for captions — or copied to the
clipboard. Excel/ODS exports carry a bold, frozen header row (with an
auto-filter in Excel). If a selection is active, only the selected rows are
exported.

**Editing the preview:** select rows and press **Delete** / **Backspace** to
remove them from the report, **⌘Z** to undo the last deletion, and a **Reset
rows** button (next to *Clear selection*, shown only once you've deleted
something) to bring every row back. Deletions survive column reorders and only
affect the export/preview — the loaded file is never changed.

**Keyboard:** **⇧← ⇧→** move between tabs, **⇧↑ ⇧↓** cycle through the
sequences in the loaded bin, **⇧Enter** opens the file picker (Browse… /
Replace…) and **Enter** exports the current report. Plain arrows move around
the table as usual, and text fields keep their keys. **⌘W** closes the app.

**Markers (`.txt`)** writes a Media Composer marker-import file — one marker per
row, placed at the row's record timecode — so a report round-trips back onto the
timeline. The marker's name / comment are filled per report: Opticals uses the
Effect as the marker name and the Notes as its comment; the Music Tracker leaves
the name blank and sets the comment to `Artist - Track (Duration)`; the Clip List
uses the clip name; and the Markers tab reproduces the loaded locators.

### Remembered between sessions
The app remembers, via `QSettings` (`timeline_reader/settings.py`): the folder
you last **opened** a file from (the file picker reopens there), the folder you
last **exported** to, your chosen **export format**, the caption **frame rate**,
and your per-report **column selection and order**.

## Running from source

```bash
./run.sh
```

This creates a virtual environment on first run, installs dependencies from
`requirements.txt`, and launches the app. Requires Python 3.11+.

Or manually:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m timeline_reader
```

## Building a standalone macOS app

```bash
./build_app.sh
```

Produces `dist/Timeline Reader.app` (a self-contained bundle — no Python
required to run it), with the app icon. Open it with
`open "dist/Timeline Reader.app"`.

This builds for the current Mac's architecture. For a **universal2** bundle that
runs on **both Apple Silicon and Intel**, use:

```bash
./build_app_universal.sh
```

It builds with the universal2 system Python (`/usr/bin/python3`) and universal2
PySide6 wheels, producing `dist/TimelineReader-<version>-macOS-universal.zip`.
(That path pins `PySide6 < 6.11`, since 6.11 dropped Python 3.9 — the only
universal2 Python on macOS. The released binaries are universal.)

The icon is generated by `./.venv/bin/python make_icon.py` → `assets/icon.icns`
(regenerate it if you tweak the design in `make_icon.py`).

> The bundle is **ad-hoc signed**. On first launch, right-click the app →
> **Open** to get past Gatekeeper, or run
> `xattr -dr com.apple.quarantine "dist/Timeline Reader.app"`.

Prebuilt macOS binaries are attached to each
[GitHub release](https://github.com/absolute-cinema-jpg/timeline-reader/releases).

## Parallel sessions (git worktrees)

Running more than one coding session against this repo at once? Give each its
own **git worktree** so they never overwrite each other's edits or tangle their
commits:

```bash
./new-worktree.sh captions      # -> ../timeline-reader-captions on branch session/captions
./new-worktree.sh export
```

Each worktree is a separate folder with its own branch and staging area,
sharing this repo's history and (via a symlink) the installed `.venv`. Point one
session at each folder (`cd ../timeline-reader-captions && ./run.sh`), then merge
when done:

```bash
git switch main && git merge session/captions
git worktree remove ../timeline-reader-captions
```

`git worktree list` shows the active ones. If sessions run strictly one after
another, a single checkout is fine and you don't need this.

## Project layout

```
timeline_reader/
  app.py              entry point (QApplication)
  timecode.py         frame-accurate timecode (drop/non-drop, SRT)
  models.py           Timeline / Clip / Effect data model
  effects.py          effect classification + opticals rules
  captions.py         DS Caption (.txt) -> SRT
  music.py            sound segments -> merged music cues
  loader.py           one cached parse per file, shared by every tab
  reports.py          Timeline -> table rows (opticals, clip list)
  exporters.py        CSV / TSV / XLSX / ODS / text writers
  captions_avb.py     SubCap subtitles read from the bin
  parsers/
    avb_parser.py     Avid bin  (pyavb)   — full effect data
    edl_parser.py     CMX3600 EDL
    aaf_parser.py     AAF       (pyaaf2)
    tab_parser.py     tab-delimited / CSV bin export
  ui/
    main_window.py    branded top bar + page tabs
    report_tab.py     shared Opticals / Clip-list / Tag-finder tab
    tagfinder_tab.py  tag finder (timeline clip notes) tab
    music_tab.py      music tracker (cue sheet) tab
    captions_tab.py   caption converter tab
    widgets.py        drop zone + report table
    theme.py          Resolve-style dark theme
```

## Notes & next steps

- **Caption format:** the DS Caption parser is written to the common
  `IN  OUT  text` shape and is deliberately forgiving. Share a real Avid DS
  Caption `.txt` and the parser can be tightened to match your facility's exact
  layout (headers, styling tags, positioning, etc.).
- **Motion speed:** the bin's stored speed ratio is reported as-is and is
  approximate for freeze frames; EDL `M2` values are exact where available.
- **Effect scope:** the opticals rules live in `effects.py` and are one line
  each to adjust if you want to include or exclude a category.
- **Multiple sequences:** if a bin holds more than one sequence, the longest
  master sequence is used. A sequence picker is a natural next addition
  (`avb_parser.list_sequences()` already enumerates them).
