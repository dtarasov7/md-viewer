# Markdown Viewer

[![Version](https://img.shields.io/badge/version-1.2.0-blue.svg)](CHANGELOG.md)

`md-viewer.py` is a small Python 3.8 program for viewing Markdown files with tables. It uses only the Python standard library and can run either as a local browser-based HTML viewer or as a terminal TUI.

## Features

- view `.md` and `.markdown` files;
- automatically discover Markdown files in the current directory when no files are provided;
- open explicitly provided files from any directory when the current user can read them;
- HTML viewing through a built-in local HTTP server;
- terminal viewing through `curses`;
- Markdown pipe tables with column alignment;
- adaptive TUI column widths;
- horizontal scrolling for wide tables;
- interactive, case-insensitive TUI text search opened with `F7`, with instant highlighting and `n` / `p` navigation between matches;
- basic rendering for headings, lists, blockquotes, links, inline code, and fenced code blocks.

## Requirements

- Python 3.8 or newer;
- a terminal with `curses` support for TUI mode;
- no third-party Python packages.

## Quick Start

Run the default TUI for all Markdown files in the current directory:

```bash
python3 md-viewer.py
```

Run it for one file:

```bash
python3 md-viewer.py RegressionTestPlan-ru.md
```

When exactly one file is provided, the program opens that file directly instead of showing the file list.

## HTML Mode

Enable HTML mode explicitly with `--html`:

```bash
python3 md-viewer.py --html --host 127.0.0.1 --port 8765
```

Options:

- `--host HOST` - server address, default `0.0.0.0`;
- `--port PORT` - server port, default `8765`;
- `--no-browser` - do not open the browser automatically.

Example without opening a browser automatically:

```bash
python3 md-viewer.py --html --no-browser
```

## TUI Mode

Start the terminal interface (the default mode):

```bash
python3 md-viewer.py
```

Start TUI mode directly for one file:

```bash
python3 md-viewer.py /path/to/file.md
```

Add `--debug` to diagnose keyboard input. The status line will show as many recent key codes as fit:

```bash
python3 md-viewer.py --debug /path/to/file.md
```

Example output: `262:KEY_HOME` for a recognized Home key, or `27:'\x1b' 91:'[' 72:'H'` when the terminal sends its escape sequence as separate characters.

Keys:

- `Enter` - open the selected file;
- `↑` / `↓` or `k` / `j` - move;
- Mouse wheel - scroll the document or move through the file list by three lines;
- `PgUp` / `PgDn` - page scrolling;
- `←` / `→` - horizontal scrolling;
- `Home` / `End` - beginning or end of the document;
- `F7` (or `/`) - start interactive search (matches update after every typed character);
- `n` / `p` (Latin or Russian layout, either case) - next / previous search match;
- `r` - reload the file;
- `b` (`back`) - return to the file list;
- `q` - quit.

## Supported Markdown

The program implements a practical Markdown subset:

- headings `#` through `######`;
- paragraphs;
- unordered and ordered lists;
- blockquotes;
- fenced code blocks;
- inline code;
- bold and italic text;
- links;
- pipe tables with `---`, `:---`, `---:`, and `:---:` separators.

This is not a full CommonMark parser. The goal is simple viewing of table-heavy files without installing extra packages.

## Verification

Syntax check:

```bash
python3 -m py_compile md-viewer.py
```

CLI help check:

```bash
./md-viewer.py --help
```

## Author

**Tarasov Dmitry**
- Email: dtarasov7@gmail.com

## Attribution

Parts of this code were generated with assistance.
