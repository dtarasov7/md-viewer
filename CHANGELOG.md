# Changelog

All notable changes to Markdown Viewer are documented in this file.

## [1.2.0] - 2026-10-22

### Added

- Mouse wheel scrolling in the TUI: three lines in documents or three positions in the file list, with boundary limits.
- Wheel-down support on Python 3.8/3.9, where `curses` does not expose `BUTTON5_PRESSED`.

### Changed

- Renamed the entry script from `md_viewer.py` to `md-viewer.py`; updated launch commands and test module loading.

## [1.1.0] - 2026-08-28

### Added

- TUI search on `F7` and per-match navigation with `n` / `p`.
- `Home` / `End` handling compatible with additional terminfo key codes and raw escape sequences.
- `--debug` mode showing received key codes in the TUI status line.

### Changed

- TUI is now the default mode; HTML mode is selected with `--html`.

## [1.0.0] - 2026-07-12

### Added

- Browser and terminal interfaces for viewing Markdown files.
- Rendering of headings, paragraphs, lists, blockquotes, code, links, and pipe tables.
- Adaptive table columns and horizontal scrolling in the TUI.
- Interactive, case-insensitive TUI text search with instant highlighting.
- Search navigation between matching lines with `n` and `p`.
- Latin and Russian keyboard layout support for TUI hotkeys, including Caps Lock.
