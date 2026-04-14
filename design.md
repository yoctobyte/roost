Below is a practical functional design your sister AI can implement.

---

# Functional Design: GTK Console Browser over tmux

## 1. Purpose

Build a Linux desktop application that reduces terminal-window clutter by presenting multiple persistent shell sessions inside one GUI.

The application is a **GUI frontend over tmux**:

* **tmux** is the persistence and session backend
* **GTK** is the GUI toolkit
* **VTE** is the embedded terminal widget
* the GUI provides:

  * one main window
  * one tab per tmux window
  * one GUI-only overview tab
  * toolbar actions for common window management
  * easy recovery after GUI close/restart

The GUI must remain compatible with ordinary tmux usage from shell or SSH.

---

## 2. Design Goals

### Primary goals

* Replace many terminal windows with one application window.
* Keep terminal sessions alive independently of the GUI.
* Make all tmux windows easily discoverable and accessible.
* Make the overview page the default landing page.
* Keep the system simple and robust.

### Secondary goals

* Allow normal tmux CLI usage outside the GUI.
* Reflect external tmux changes inside the GUI.
* Avoid creating a parallel session model when tmux already provides one.

### Non-goals for now

* No custom terminal emulator.
* No advanced pane-graphical editing.
* No internal shell/session implementation replacing tmux.
* No plugin system.
* No multi-host orchestration yet.
* No browser embedding, file manager, or IDE features.

---

## 3. Scope

## Included

* Linux desktop app
* Python implementation
* GTK-based GUI
* VTE terminal rendering
* tmux integration through subprocess / command calls
* single main application window
* overview page
* tabs for tmux windows
* create / rename / close / force-kill actions
* session persistence across GUI restarts
* resync with external tmux state changes

## Excluded for first implementation

* multiple simultaneous live terminal widgets for all tabs
* rich live thumbnails rendered from active emulators
* pane-level editing in GUI
* drag-drop pane rearranging
* session sharing across machines
* configuration editor UI
* advanced theming UI
* deep history analytics

---

## 4. User Problem

The user has many terminal windows open for different tasks. This causes:

* cluttered desktop/taskbar
* poor overview
* difficulty locating the right session
* accidental window loss
* weak organization

The application solves this by providing:

* one taskbar item
* persistent sessions via tmux
* browser-like tab access
* overview grid with miniature summaries
* fast recovery by reopening the GUI

---

## 5. Core Concept

The application is a **console browser**.

### Mapping

* **tmux session** = backend session namespace
* **tmux window** = one real console unit
* **GUI tab** = visual representation of one tmux window
* **overview tab** = GUI-only page showing all tmux windows
* **active terminal area** = one embedded VTE widget connected to selected tmux target

### Important rule

The GUI does **not** own terminal process lifetime.
tmux owns process lifetime.

Closing the GUI must not terminate shells or jobs.

---

## 6. High-Level Architecture

## 6.1 Components

### A. tmux backend adapter

Responsible for:

* creating/querying/killing/renaming tmux windows
* listing sessions/windows
* querying titles and status
* capturing window text for overview cards
* sending commands/keys when needed

### B. application state controller

Responsible for:

* keeping a current in-memory model of tmux windows
* syncing GUI state with tmux state
* handling selected tab
* handling overview/default state
* coordinating refreshes

### C. GTK GUI

Responsible for:

* main window
* header/action bar
* tabs
* overview page
* terminal display area
* dialogs for rename/confirm when needed

### D. VTE terminal host

Responsible for:

* rendering the active terminal tab
* handling keyboard input
* handling resize
* copy/paste behavior
* displaying full-screen terminal apps properly

---

## 7. Runtime Model

## 7.1 Backend session strategy

The application uses tmux as backend.

A dedicated tmux session name should be used by default, for example:

* `console-browser`
  or configurable later.

At startup:

* if the session exists, connect to it
* otherwise create it

Alternative later:

* support attaching to an existing user-selected session

For initial implementation, use one managed tmux session.

## 7.2 Window strategy

Each tmux window corresponds to:

* one logical GUI tab
* one overview card

The overview page is not a tmux window.

## 7.3 Terminal display strategy

To keep the design simple:

* only the selected tab needs a live interactive terminal
* overview cards use captured snapshots from tmux
* inactive tabs do not need separate active VTE widgets

This reduces complexity and resource usage.

---

## 8. Functional Requirements

# 8.1 Startup

On application startup, the system shall:

1. start the GTK application
2. verify tmux is available
3. connect to or create the configured tmux session
4. query tmux windows in that session
5. build GUI tabs for those windows
6. open the overview tab as the default visible page
7. show the currently known state without blocking on advanced features

If tmux is unavailable, the application shall show a clear error and exit.

---

# 8.2 Overview Tab

The application shall provide a GUI-only overview tab.

### Overview behavior

* visible as the first/default tab
* always available
* shows all real tmux windows as cards/tiles
* each tile includes:

  * window title
  * small text preview
  * optional activity marker
  * optional window index
* clicking a tile opens/selects the associated real tab

### Overview preview source

The preview should come from tmux text capture, not from full embedded live rendering.

### Preview content

For each tmux window, capture a useful portion of visible content, such as:

* current visible lines of the active pane
* trimmed to fit card size

The card may render as:

* monospace label/text area
* simplified text block

No full ANSI-perfect rendering is required on the overview page.

---

# 8.3 Real Console Tabs

For each tmux window, the application shall provide one real tab.

### Real tab behavior

* selecting the tab activates a live embedded terminal view
* the terminal connects to the correct tmux target
* input is sent normally through VTE/tmux
* full-screen terminal apps should work as expected
* resizing the application updates terminal size

### Tab titles

Tab titles should come from tmux window names.

When the tmux window name changes externally, the GUI must reflect that after refresh or sync.

---

# 8.4 Create New Console

The application shall provide a “new window” action.

### Behavior

* create a new tmux window in the managed session
* assign a default title if none is specified
* create corresponding GUI tab
* select the new tab or return to overview depending on preference

Default behavior:

* create and immediately open the new tab

---

# 8.5 Rename Console

The application shall support renaming the current tmux window.

### Behavior

* user activates rename action
* a small dialog or inline editor appears
* new name is applied using tmux window rename
* GUI updates immediately

---

# 8.6 Close Console

The application shall support closing the current tmux window.

### Behavior

* close action kills the tmux window
* corresponding GUI tab disappears
* if the closed tab was active, switch to overview

Since tmux already backgrounds everything and the user requested low friction, no confirmation is required by default.

Optional later:

* warning only when process activity suggests danger

---

# 8.7 Force Kill

The application shall support a forceful termination action.

### Behavior

This may be implemented in stages:

#### initial acceptable implementation

* same as tmux kill-window

#### later stronger behavior

* kill the foreground process tree inside the window or pane
* if needed, then kill the tmux window

Because process-tree semantics can get messy, first implementation may expose:

* **Close Window**
* **Kill Window Hard**

Even if both initially map to tmux kill-window, the UI label should allow later refinement.

---

# 8.8 Freeze / Hold View

The application shall support a visual freeze mode for the active tab.

### Purpose

Let the user inspect current output without auto-following updates.

### Important note

This is not OS-level Scroll Lock behavior.

### Behavior

* freezing pauses visual updates in the GUI
* tmux/processes continue running
* resuming refreshes the display again

For first implementation, this may be postponed if it complicates VTE behavior.
It is desirable but not mandatory for version 1.

---

# 8.9 GUI Close / Restart

The application shall allow the main window to close immediately without confirmation.

### Behavior

* closing the GUI must not kill tmux session or windows
* reopening the GUI reconnects to the same tmux session
* prior windows remain available

This is a key requirement.

---

# 8.10 External tmux Compatibility

The application must remain compatible with ordinary tmux usage.

### Examples

* user renames a window from a shell
* user creates window outside GUI
* user kills a window from CLI
* user attaches over SSH and uses tmux normally

### Required behavior

The GUI shall resync and reflect external changes.

This can be implemented by:

* periodic polling
* explicit refresh action
* later event-driven approach if feasible

For first implementation, polling is acceptable.

---

# 8.11 Refresh / Resync

The application shall provide a refresh mechanism.

### Behavior

Refresh updates:

* window list
* titles
* overview cards
* removed windows
* newly created windows

A toolbar refresh button is sufficient initially.

Optional:

* auto-refresh every few seconds for overview/status

---

# 8.12 Activity Indicators

The application should support lightweight activity hints.

Examples:

* changed output since last viewed
* bell marker
* current active tab highlight

This can be simplified in first version and improved later.

---

## 9. User Interface Design

# 9.1 Main Window Layout

The main window should have:

### Top header/action bar

Contains actions such as:

* New
* Overview
* Rename
* Close
* Kill
* Refresh
* optional Freeze later

### Tab bar

Contains:

* Overview tab
* one tab per tmux window

### Main content area

Shows either:

* overview grid
* active terminal view

---

# 9.2 Overview Page Layout

Overview page should display:

* grid or flow layout of cards
* each card sized to fit multiple visible items
* each card shows:

  * title
  * miniature text preview
  * optional status marker

Clicking a card:

* switches to associated tab

Double-click behavior may later:

* open and focus directly

---

# 9.3 Terminal Page Layout

Terminal page should display:

* active VTE widget
* no unnecessary chrome inside content
* title handled by tab label, not duplicated unless useful

---

# 9.4 Keyboard and Focus Model

The GUI and tmux both want to own the keyboard. A clear split is
required or both sides will feel broken.

### Rules

* When the VTE has focus, all keystrokes except a small set of GUI
  accelerators are forwarded to tmux unchanged. This includes the
  tmux prefix (`C-b` by default) — the user can still drive tmux
  normally from inside the embedded client.
* GUI accelerators use the GTK modifier conventions (`Ctrl+Shift+…`
  or `Super+…`) so they do not collide with common shell or editor
  shortcuts. Suggested defaults:

  * `Ctrl+Shift+T` — new console
  * `Ctrl+Shift+W` — close current console
  * `Ctrl+Shift+R` — rename current console
  * `Ctrl+Shift+O` — show overview
  * `F5` — refresh
  * `Ctrl+Tab` / `Ctrl+Shift+Tab` — next/previous tab

* Tab switching performed via GUI accelerator shall translate to a
  `select-window` on the managed session, matching the click path
  described in 17.1, so that GUI and tmux state never diverge.

* The overview page is a GTK widget and does not forward keys to
  tmux; arrow keys and Enter navigate cards there.

# 9.5 Visual Style

Keep the interface simple:

* functional, not flashy
* monospace for previews and terminal
* native GTK styling
* clear tab titles
* compact action bar

Avoid overdesign.

---

## 10. Sync Model

A polling-based state sync is acceptable for MVP. A control-mode
upgrade path is described in 10.4.

## 10.1 Poll source

Periodically query tmux for:

* current window list
* current names
* current active window if relevant
* preview snapshots for overview

## 10.2 Sync interval

A modest interval is sufficient, such as:

* 1–3 seconds for overview freshness
* or slower if performance becomes an issue

## 10.3 Sync responsibilities

Sync must detect:

* new windows
* removed windows
* renamed windows
* changed preview text

## 10.4 Event-driven upgrade (post-MVP)

tmux supports a **control mode** client (`tmux -C attach`) that emits
notifications like `%window-add`, `%window-close`, `%window-renamed`,
and `%output` over stdout. Once polling is proven to work, a
background control-mode client can replace or supplement polling so
that:

* the window list updates immediately on external changes
* the overview only re-captures previews for windows that actually
  produced output since the last capture

This is an upgrade, not a rewrite — the tmux adapter should be shaped
so that the controller consumes a stream of diffs, regardless of
whether those diffs come from a poll loop or from control mode.

---

## 11. Error Handling

The application shall handle at least these errors clearly:

### tmux missing

* show message
* exit cleanly

### session creation failure

* show message
* exit or retry

### VTE initialization failure

* show message
* disable terminal area if needed

### window vanished during interaction

* remove stale GUI tab
* switch to overview
* refresh state

### malformed external state

* fail safely
* rebuild tabs from current tmux truth

### managed session killed externally

If the managed session disappears while the GUI is running (user ran
`tmux kill-session` from a shell):

* the attached VTE client will exit
* the controller shall detect the missing session on next sync
* the GUI shall offer to recreate the session, or exit cleanly
* it shall never silently recreate the session under the same name
  without telling the user, because that would hide data loss

tmux remains authoritative.

---

## 12. Persistence

The main persistence comes from tmux, not from the GUI.

## GUI-side persistence

The GUI may optionally persist:

* window size
* whether to start on overview
* last selected tab
* chosen tmux session name

This is minor and not required for basic operation.

---

## 13. Implementation Constraints

* Linux-first
* Python
* GTK via PyGObject
* VTE via GI bindings
* tmux invoked through subprocess commands
* no direct dependence on fragile undocumented internals if avoidable
* use tmux commands as much as possible rather than scraping terminal output from random processes

---

## 14. Suggested Internal Modules

A simple module split:

### `app.py`

GTK app startup and shutdown.

### `main_window.py`

Main window, header bar, tabs, content switching.

### `tmux_adapter.py`

All tmux command interaction:

* create session
* list windows
* rename
* kill
* capture preview
* query state

### `models.py`

Simple data structures, for example:

* session state
* window info
* preview state

### `overview_page.py`

Overview grid/card rendering and click handling.

### `terminal_page.py`

VTE host for active window.

### `controller.py`

App coordination:

* sync
* selection changes
* action dispatch
* reconciliation between tmux and GUI

### `config.py`

Minimal config/constants.

This should remain small.

---

## 15. Data Model

A minimal internal model for a tmux window:

* tmux window id
* tmux window index
* title/name
* active flag
* preview text
* unseen activity flag
* last sync timestamp

A minimal app state model:

* managed session name
* list of known windows
* selected tab id
* overview selected state
* refresh timestamp

---

## 16. tmux Integration Strategy

The app should interact with tmux through explicit commands rather than hidden hacks.

Typical operations needed:

* ensure session exists
* list windows in a machine-readable format
* create window
* rename window
* kill window
* capture visible text for preview
* attach active VTE terminal to selected target

The implementation should avoid assuming deep tmux internals beyond stable command behavior.

---

## 17. Active Terminal Attachment Strategy

### 17.1 Chosen approach: one VTE, switch via `select-window`

A VTE widget spawns a child process once and cannot have that process
swapped out. "Retargeting" a VTE is therefore not a real operation. The
recommended approach is:

* one persistent VTE widget, mounted in the terminal content area
* at startup, the VTE spawns a single `tmux attach -t <session>` client
* when the user clicks a real tab, the controller runs
  `tmux select-window -t <session>:<winID>` against the same session
* the attached client follows, because there is only one client and it
  reflects whatever window tmux considers active

This keeps the GUI stateless with respect to terminal rendering: tmux
owns the pty, the VTE is just a viewport, and tab switching is a single
tmux command away.

### 17.2 Why not one VTE per tab

Spawning `tmux attach` in every tab is tempting but has two real
problems:

* **Size negotiation.** Multiple clients attached to the same session
  force the session size to the smallest client. Inactive tabs that are
  allocated at a tiny size would shrink active ones.
* **Resource cost.** One tmux client + pty per tab for no visible gain,
  since only the focused tab is ever displayed.

A known workaround is tmux **grouped sessions** (`new-session -t base
-s view-N`) where each view has its own active-window pointer and its
own client size. This is strictly more complex than 17.1 and is only
worth adopting if a future feature genuinely needs two tabs visible at
once (e.g. split view). It is explicitly out of scope for MVP.

### 17.3 Overview rendering

The overview shall not use VTE at all. Previews come from
`tmux capture-pane -p -t <session>:<winID>` and are rendered as plain
monospace text in a GTK label or text view. This avoids running N
parallel terminal emulators for cards the user only glances at.

---

## 18. MVP vs Near-Future

# MVP

* connect/create tmux session
* overview tab as default
* one tab per tmux window
* text previews in overview
* interactive terminal for selected tab
* new / rename / close / refresh
* GUI close without affecting backend
* resync with external tmux changes

# Nice next features

* activity badges
* freeze/hold view
* keyboard shortcuts
* quick tab search
* improved preview formatting
* optional multiple sessions
* persistent app settings

---

## 19. Acceptance Criteria

The implementation is acceptable when all of the following are true:

1. Opening the app shows an overview page.
2. Existing tmux windows appear as tabs.
3. Creating a new console creates a real tmux window.
4. Selecting a console tab opens an interactive terminal.
5. Closing the GUI does not kill running shells/jobs.
6. Reopening the GUI restores access to the same tmux windows.
7. Renaming a window updates both tmux and the GUI.
8. Closing a tab removes the tmux window.
9. External changes from normal tmux usage are reflected after refresh or auto-sync.
10. The app remains usable without implementing a custom terminal emulator.
11. The tmux prefix key still works inside the embedded terminal; GUI
    accelerators do not shadow it.
12. If the managed tmux session is killed externally, the GUI reports
    it instead of silently recreating the session.

---

## 20. Development Notes for Sister AI

### Preferred development order

1. tmux adapter
2. basic GTK shell
3. overview page with fake/static test cards
4. real sync from tmux
5. VTE active terminal page
6. create/rename/close actions
7. polling refresh
8. polish

### Important implementation philosophy

* keep tmux authoritative
* keep overview simple
* do not overbuild
* avoid making a second session model
* use one live terminal view first
* prefer robust boring behavior over clever behavior

---

## 21. Short Summary

This project is a **simple GTK console browser over tmux**.

It should:

* present tmux windows as tabs
* provide an overview page with preview cards
* embed one interactive terminal view for the selected tab
* let the GUI close freely while sessions survive in tmux
* remain compatible with ordinary tmux use

The system should stay small, practical, and conservative.

---

If you want, I can turn this into an even tighter **implementation spec** with file-by-file responsibilities and first-pass class names.

