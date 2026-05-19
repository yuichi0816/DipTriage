# Launcher Helper — Design Spec
Date: 2026-05-19

## Overview

A standalone single-file HTML app (`tools/launcher_helper.html`) that manages localhost server profiles, shows live running status, and generates start/stop batch files for Windows. No external dependencies; runs offline by opening the file in a browser.

---

## Architecture

- **Single HTML file** — vanilla JS + CSS, no CDN or npm
- **Persistence** — `localStorage` for server profiles
- **No backend** — pure client-side; status detection uses `fetch` pings

---

## Data Model

Profiles stored as a JSON array in `localStorage` key `"launcher_profiles"`.

```json
[
  {
    "id": "1716000000000",
    "name": "DipTriage",
    "port": 8000,
    "workDir": "C:\\Users\\yuich\\OneDrive\\ドキュメント\\GitHub\\DipTriage",
    "command": "uv run uvicorn app.main:app --reload",
    "browserPath": "/dashboard"
  }
]
```

Fields:
| Field | Required | Description |
|-------|----------|-------------|
| id | auto | `Date.now()` string, used as key |
| name | yes | Display name |
| port | yes | Port number (integer) |
| workDir | yes | Absolute path to project root |
| command | yes | Shell command to start the server |
| browserPath | no | Path to open in browser on start (e.g. `/dashboard`) |

---

## Layout (top to bottom)

```
┌─────────────────────────────┐
│  Server Launcher Helper     │
├─────────────────────────────┤
│  [1] Server Status          │
├─────────────────────────────┤
│  [2] Batch File Generator   │
├─────────────────────────────┤
│  [3] Profile Manager        │
└─────────────────────────────┘
```

---

## Section 1: Server Status

- Lists all registered profiles with live status indicator
- Status is detected via `fetch('http://localhost:PORT', { mode: 'no-cors' })` with a 2-second `AbortController` timeout
  - Resolves → **running** (green pulsing dot)
  - Rejects (network error or timeout) → **stopped** (red dot)
- Status refreshes on page load and every **10 seconds**
- Each row has: `[status dot] [name] [:port] [status label] [Generate] [Edit] [Delete]`
- Clicking **Generate** scrolls to Section 2 and pre-selects that profile

---

## Section 2: Batch File Generator

Flow:
1. Select profile (dropdown; pre-filled if arrived from Section 1 Generate button)
2. Select type: **Start** or **Stop** (radio buttons with visual highlight)
3. Click **Generate**
4. Output appears in a `readonly` textarea
5. Buttons: **Copy** (clipboard) and **Download (.bat)**

### Generated batch content (ASCII only — no Japanese to avoid Shift-JIS encoding issues)

**Start batch** (`start_<name>.bat`):
```bat
@echo off
cd /d "<workDir>"
echo Starting <name>...
start "" "http://localhost:<port><browserPath>"
<command>
pause
```
`start ""` line is omitted if `browserPath` is empty.

**Stop batch** (`stop_<name>.bat`):
```bat
@echo off
echo Stopping <name> on port <port>...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":<port> "') do (
    taskkill /F /PID %%a 2>nul
)
echo Done.
pause
```

**Encoding note:** The Blob is created with charset UTF-8. All batch content is ASCII-only to guarantee no mojibake on any Windows locale.

---

## Section 3: Profile Manager

### Add
- Form fields: Name, Port, Work Directory, Command, Browser Path (optional)
- Validation: name/port/workDir/command are required; show inline error if missing
- On submit: appends to localStorage array, re-renders Section 1 and dropdown

### Edit (inline)
- Clicking **Edit** on a profile row replaces that row with an editable form in-place
- Fields pre-filled with current values
- Buttons: **Save** (update localStorage) and **Cancel** (restore row view)
- No page navigation

### Delete
- `confirm()` dialog before removal
- Removes from localStorage and re-renders

---

## Error Handling

- Invalid port (non-integer, out of range): show validation error, block save
- Empty required fields: inline error message
- localStorage unavailable: degrade gracefully (form still works, profiles not saved; note shown)

---

## File Location

`tools/launcher_helper.html` within the DipTriage repository. Intended to be opened directly in a browser (file:// protocol).
