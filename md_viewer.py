#!/usr/bin/env python3
"""Small Markdown table viewer with no third-party dependencies.

The program renders a practical Markdown subset to HTML and serves it through a
local HTTP server.  It focuses on pipe tables, headings, lists, paragraphs and
code blocks, which is enough for the Markdown files in this workspace.
"""

import argparse
import curses
import html
import http.server
import locale
import os
from pathlib import Path
import posixpath
import re
import socketserver
import sys
import textwrap
import threading
import urllib.parse
import webbrowser


APP_TITLE = "Markdown Viewer"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
TUI_TABLE_CELL_MAX = 38


def escape_text(value):
    """Escape text for safe HTML output.

    Экранирует текст для безопасного вывода в HTML.

    Args:
        value (str): Raw text / исходный текст.

    Returns:
        str: HTML-escaped text / HTML-экранированный текст.
    """
    return html.escape(value, quote=False)


def render_inline(value):
    """Render a conservative inline Markdown subset after HTML escaping.

    Рендерит ограниченный набор inline Markdown после HTML-экранирования.

    Args:
        value (str): Markdown text fragment / фрагмент Markdown-текста.

    Returns:
        str: HTML fragment / HTML-фрагмент.
    """
    placeholders = []

    def keep_code(match):
        """Protect inline code while other inline rules are applied.

        Защищает inline-code на время применения остальных inline-правил.

        Args:
            match (re.Match): Code span match / совпадение code span.

        Returns:
            str: Placeholder token / токен-заполнитель.
        """
        placeholders.append("<code>{}</code>".format(html.escape(match.group(1))))
        return "\x00{}\x00".format(len(placeholders) - 1)

    text = re.sub(r"`([^`]+)`", keep_code, html.escape(value))
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"<em>\1</em>", text)

    def link(match):
        """Render one Markdown link match.

        Рендерит одно совпадение Markdown-ссылки.

        Args:
            match (re.Match): Link match / совпадение ссылки.

        Returns:
            str: HTML anchor / HTML-ссылка.
        """
        label = match.group(1)
        href = html.escape(match.group(2), quote=True)
        return '<a href="{}">{}</a>'.format(href, label)

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    for index, replacement in enumerate(placeholders):
        text = text.replace("\x00{}\x00".format(index), replacement)
    return text


def split_pipe_row(line):
    """Split a Markdown pipe-table row and keep escaped pipes inside cells.

    Разбивает строку Markdown-таблицы, сохраняя экранированные `|` в ячейках.

    Args:
        line (str): Source table row / исходная строка таблицы.

    Returns:
        list[str]: Trimmed cell values / очищенные значения ячеек.
    """
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]

    cells = []
    current = []
    escaped = False
    for char in row:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells


def is_table_separator(line):
    """Return whether a line is a Markdown table separator.

    Проверяет, является ли строка разделителем Markdown-таблицы.

    Args:
        line (str): Source line / исходная строка.

    Returns:
        bool: True for a valid separator / True для корректного разделителя.
    """
    cells = split_pipe_row(line)
    if not cells:
        return False
    for cell in cells:
        normalized = cell.strip()
        if not re.fullmatch(r":?-{3,}:?", normalized):
            return False
    return True


def table_alignments(separator):
    """Parse Markdown table alignment markers.

    Разбирает маркеры выравнивания в строке-разделителе таблицы.

    Args:
        separator (str): Markdown separator row / строка-разделитель.

    Returns:
        list[str | None]: `left`, `center`, `right`, or None / типы выравнивания.
    """
    alignments = []
    for cell in split_pipe_row(separator):
        normalized = cell.strip()
        if normalized.startswith(":") and normalized.endswith(":"):
            alignments.append("center")
        elif normalized.endswith(":"):
            alignments.append("right")
        elif normalized.startswith(":"):
            alignments.append("left")
        else:
            alignments.append(None)
    return alignments


def render_table(lines, start):
    """Render one Markdown pipe table to HTML.

    Рендерит одну pipe-таблицу Markdown в HTML.

    Args:
        lines (list[str]): Markdown document lines / строки Markdown-документа.
        start (int): Header row index / индекс строки заголовка.

    Returns:
        tuple[str, int]: HTML table and next unread line index /
            HTML-таблица и индекс следующей непрочитанной строки.
    """
    header = split_pipe_row(lines[start])
    alignments = table_alignments(lines[start + 1])
    rows = []
    index = start + 2
    while index < len(lines):
        line = lines[index]
        if not line.strip() or "|" not in line:
            break
        rows.append(split_pipe_row(line))
        index += 1

    width = max([len(header)] + [len(row) for row in rows] + [len(alignments)])

    def cell_attrs(position):
        """Return HTML attributes for one table cell.

        Возвращает HTML-атрибуты для одной ячейки таблицы.

        Args:
            position (int): Column index / индекс колонки.

        Returns:
            str: Attribute string / строка атрибутов.
        """
        alignment = alignments[position] if position < len(alignments) else None
        if alignment:
            return ' style="text-align: {}"'.format(alignment)
        return ""

    def render_cells(tag, row):
        """Render all cells for one HTML table row.

        Рендерит все ячейки одной HTML-строки таблицы.

        Args:
            tag (str): HTML cell tag / HTML-тег ячейки.
            row (list[str]): Cell values / значения ячеек.

        Returns:
            str: Rendered cells / отрендеренные ячейки.
        """
        rendered = []
        for position in range(width):
            value = row[position] if position < len(row) else ""
            rendered.append("<{tag}{attrs}>{value}</{tag}>".format(
                tag=tag,
                attrs=cell_attrs(position),
                value=render_inline(value),
            ))
        return "".join(rendered)

    body = ["<div class=\"table-wrap\"><table>"]
    body.append("<thead><tr>{}</tr></thead>".format(render_cells("th", header)))
    body.append("<tbody>")
    for row in rows:
        body.append("<tr>{}</tr>".format(render_cells("td", row)))
    body.append("</tbody></table></div>")
    return "\n".join(body), index


def render_markdown(source):
    """Render a practical Markdown subset to HTML.

    Рендерит практический поднабор Markdown в HTML.

    Args:
        source (str): Full Markdown source / полный Markdown-текст.

    Returns:
        str: HTML body fragment / HTML-фрагмент тела документа.
    """
    lines = source.splitlines()
    index = 0
    result = []
    list_stack = []

    def close_lists():
        """Close all currently open HTML lists.

        Закрывает все открытые HTML-списки.

        Args:
            None.

        Returns:
            None.
        """
        while list_stack:
            result.append("</{}>".format(list_stack.pop()))

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            close_lists()
            index += 1
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            close_lists()
            fence = stripped[:3]
            language = stripped[3:].strip()
            code_lines = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            class_attr = ' class="language-{}"'.format(html.escape(language, quote=True)) if language else ""
            result.append("<pre><code{}>{}</code></pre>".format(
                class_attr,
                html.escape("\n".join(code_lines)),
            ))
            continue

        if index + 1 < len(lines) and "|" in line and is_table_separator(lines[index + 1]):
            close_lists()
            table_html, index = render_table(lines, index)
            result.append(table_html)
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            close_lists()
            level = len(heading.group(1))
            result.append("<h{0}>{1}</h{0}>".format(level, render_inline(heading.group(2))))
            index += 1
            continue

        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            close_lists()
            quote_lines = []
            while index < len(lines):
                quote_match = re.match(r"^>\s?(.*)$", lines[index])
                if not quote_match:
                    break
                quote_lines.append(render_inline(quote_match.group(1)))
                index += 1
            result.append("<blockquote>{}</blockquote>".format("<br>".join(quote_lines)))
            continue

        item = re.match(r"^(\s*)([-*+]|\d+[.])\s+(.+)$", line)
        if item:
            tag = "ol" if item.group(2).endswith(".") and item.group(2)[:-1].isdigit() else "ul"
            if not list_stack or list_stack[-1] != tag:
                close_lists()
                list_stack.append(tag)
                result.append("<{}>".format(tag))
            result.append("<li>{}</li>".format(render_inline(item.group(3))))
            index += 1
            continue

        close_lists()
        paragraph = [stripped]
        index += 1
        while index < len(lines):
            next_line = lines[index]
            next_stripped = next_line.strip()
            if not next_stripped:
                break
            if (
                re.match(r"^(#{1,6})\s+", next_line)
                or re.match(r"^(\s*)([-*+]|\d+[.])\s+", next_line)
                or next_stripped.startswith(("```", "~~~"))
                or (index + 1 < len(lines) and "|" in next_line and is_table_separator(lines[index + 1]))
            ):
                break
            paragraph.append(next_stripped)
            index += 1
        result.append("<p>{}</p>".format(render_inline(" ".join(paragraph))))

    close_lists()
    return "\n".join(result)


def plain_inline(value):
    """Convert a small inline Markdown subset to terminal-friendly text.

    Преобразует небольшой набор inline Markdown в текст для терминала.

    Args:
        value (str): Markdown text fragment / фрагмент Markdown-текста.

    Returns:
        str: Plain terminal text / обычный терминальный текст.
    """
    placeholders = []

    def keep_code(match):
        """Protect terminal inline code from emphasis stripping.

        Защищает терминальный inline-code от снятия emphasis-разметки.

        Args:
            match (re.Match): Code span match / совпадение code span.

        Returns:
            str: Placeholder token / токен-заполнитель.
        """
        placeholders.append(match.group(1))
        return "\x00{}\x00".format(len(placeholders) - 1)

    text = value.replace("\\|", "|")
    text = re.sub(r"`([^`]*)`", keep_code, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1 (\2)", text)
    for index, replacement in enumerate(placeholders):
        text = text.replace("\x00{}\x00".format(index), replacement)
    return text


def wrap_plain(text, width, prefix=""):
    """Wrap plain Markdown-derived text for terminal output.

    Переносит очищенный Markdown-текст для вывода в терминал.

    Args:
        text (str): Source text / исходный текст.
        width (int): Maximum line width / максимальная ширина строки.
        prefix (str): Prefix for the first line / префикс первой строки.

    Returns:
        list[str]: Wrapped lines / перенесённые строки.
    """
    available = max(12, width - len(prefix))
    wrapped = textwrap.wrap(
        plain_inline(text),
        width=available,
        break_long_words=False,
        replace_whitespace=False,
    )
    if not wrapped:
        return [prefix.rstrip()]
    lines = [prefix + wrapped[0]]
    continuation = " " * len(prefix)
    lines.extend(continuation + item for item in wrapped[1:])
    return lines


def wrapped_cell(value, width):
    """Wrap a table cell to a fixed terminal column width.

    Переносит ячейку таблицы под фиксированную ширину терминальной колонки.

    Args:
        value (str): Cell Markdown text / Markdown-текст ячейки.
        width (int): Column width / ширина колонки.

    Returns:
        list[str]: Wrapped cell lines / строки ячейки после переноса.
    """
    lines = textwrap.wrap(
        plain_inline(value),
        width=max(1, width),
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    )
    return lines or [""]


def format_cell(value, width, alignment):
    """Pad a table cell according to alignment.

    Дополняет ячейку пробелами с учётом выравнивания.

    Args:
        value (str): Cell line / строка ячейки.
        width (int): Column width / ширина колонки.
        alignment (str | None): Alignment name / имя выравнивания.

    Returns:
        str: Padded cell text / дополненный текст ячейки.
    """
    if alignment == "right":
        return value.rjust(width)
    if alignment == "center":
        return value.center(width)
    return value.ljust(width)


def text_words(value):
    """Split text into non-empty whitespace-delimited words.

    Разбивает текст на непустые слова по пробельным символам.

    Args:
        value (str): Source text / исходный текст.

    Returns:
        list[str]: Words / слова.
    """
    return [word for word in re.split(r"\s+", value.strip()) if word]


def distribute_width(widths, targets, remaining):
    """Distribute spare terminal width toward target column widths.

    Распределяет свободную ширину терминала до целевых ширин колонок.

    Args:
        widths (list[int]): Mutable current widths / изменяемые текущие ширины.
        targets (list[int]): Desired upper bounds / желаемые верхние границы.
        remaining (int): Spare character budget / свободный бюджет символов.

    Returns:
        int: Undistributed width / нераспределённая ширина.
    """
    while remaining > 0:
        candidates = [index for index, width in enumerate(widths) if width < targets[index]]
        if not candidates:
            break
        candidates.sort(key=lambda index: targets[index] - widths[index], reverse=True)
        changed = False
        for index in candidates:
            if remaining <= 0:
                break
            if widths[index] < targets[index]:
                widths[index] += 1
                remaining -= 1
                changed = True
        if not changed:
            break
    return remaining


def adaptive_table_widths(header, rows, column_count, screen_width):
    """Calculate responsive TUI table column widths.

    Рассчитывает адаптивные ширины колонок TUI-таблицы.

    Args:
        header (list[str]): Header cells / ячейки заголовка.
        rows (list[list[str]]): Body rows / строки тела таблицы.
        column_count (int): Total column count / общее число колонок.
        screen_width (int): Current terminal width / текущая ширина терминала.

    Returns:
        list[int]: Column widths that fit the terminal / ширины колонок.
    """
    raw_rows = [header] + rows
    min_widths = []
    desired_widths = []
    long_widths = []

    for column in range(column_count):
        values = [plain_inline(row[column]) if column < len(row) else "" for row in raw_rows]
        header_text = values[0] if values else ""
        longest_value = max([len(value) for value in values] or [0])
        longest_word = max([len(word) for value in values for word in text_words(value)] or [0])

        # English: Keep short columns compact, but reserve room for headers
        # and long words so table borders stay stable.
        # Русский: короткие колонки остаются компактными, но заголовки и
        # длинные слова получают минимум места, чтобы рамки таблицы не ломались.
        min_width = max(3, min(len(header_text), 18), min(longest_word, 18))
        desired_width = max(min_width, min(longest_value, TUI_TABLE_CELL_MAX))
        long_width = max(desired_width, min(longest_value, max(TUI_TABLE_CELL_MAX, screen_width)))

        min_widths.append(min_width)
        desired_widths.append(desired_width)
        long_widths.append(long_width)

    line_budget = max(20, screen_width - 1)
    cell_budget = line_budget - (3 * column_count + 1)
    cell_budget = max(column_count * 3, cell_budget)
    widths = list(min_widths)

    while sum(widths) > cell_budget:
        widest = max(range(column_count), key=lambda index: widths[index])
        if widths[widest] <= 3:
            break
        widths[widest] -= 1

    # English: First satisfy normal readable widths, then use any extra width
    # for long columns, mimicking the browser table behavior.
    # Русский: сначала доводим колонки до читаемой ширины, затем отдаём остаток
    # длинным колонкам, как в браузерной таблице.
    remaining = max(0, cell_budget - sum(widths))
    remaining = distribute_width(widths, desired_widths, remaining)
    remaining = distribute_width(widths, long_widths, remaining)

    if remaining > 0 and column_count:
        flexible = sorted(range(column_count), key=lambda index: min_widths[index], reverse=True)
        while remaining > 0:
            for index in flexible:
                if remaining <= 0:
                    break
                widths[index] += 1
                remaining -= 1

    return widths


def render_tui_table(lines, start, screen_width):
    """Render one Markdown pipe table as fixed-width terminal lines.

    Рендерит одну pipe-таблицу Markdown в строки фиксированной ширины.

    Args:
        lines (list[str]): Markdown document lines / строки Markdown-документа.
        start (int): Header row index / индекс строки заголовка.
        screen_width (int): Terminal width / ширина терминала.

    Returns:
        tuple[list[str], int]: Rendered table lines and next unread line index /
            строки таблицы и индекс следующей непрочитанной строки.
    """
    header = split_pipe_row(lines[start])
    alignments = table_alignments(lines[start + 1])
    rows = []
    index = start + 2
    while index < len(lines):
        line = lines[index]
        if not line.strip() or "|" not in line:
            break
        rows.append(split_pipe_row(line))
        index += 1

    column_count = max([len(header)] + [len(row) for row in rows] + [len(alignments)])
    widths = adaptive_table_widths(header, rows, column_count, screen_width)

    separator = "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    def render_row(row, is_header=False):
        """Render one terminal table row, expanding wrapped cell height.

        Рендерит одну строку терминальной таблицы с учётом переноса ячеек.

        Args:
            row (list[str]): Cell values / значения ячеек.
            is_header (bool): Whether the row is a header / является ли строка заголовком.

        Returns:
            list[str]: Rendered terminal lines / отрендеренные строки терминала.
        """
        cells = []
        height = 1
        for column in range(column_count):
            value = row[column] if column < len(row) else ""
            wrapped = wrapped_cell(value, widths[column])
            cells.append(wrapped)
            height = max(height, len(wrapped))

        rendered = []
        for line_index in range(height):
            parts = []
            for column in range(column_count):
                value = cells[column][line_index] if line_index < len(cells[column]) else ""
                alignment = alignments[column] if column < len(alignments) else None
                if is_header:
                    alignment = "left"
                parts.append(" {} ".format(format_cell(value, widths[column], alignment)))
            rendered.append("|" + "|".join(parts) + "|")
        return rendered

    result = [separator]
    result.extend(render_row(header, is_header=True))
    result.append(separator)
    for row in rows:
        result.extend(render_row(row))
        result.append(separator)
    return result, index


def render_tui_document(source, screen_width):
    """Render Markdown to terminal-friendly lines.

    Рендерит Markdown в строки для терминального просмотра.

    Args:
        source (str): Full Markdown source / полный Markdown-текст.
        screen_width (int): Terminal width / ширина терминала.

    Returns:
        list[str]: Lines ready for curses output / строки для вывода curses.
    """
    lines = source.splitlines()
    result = []
    index = 0
    width = max(40, screen_width)

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            if result and result[-1] != "":
                result.append("")
            index += 1
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            language = stripped[3:].strip()
            result.append("[code{}]".format(": " + language if language else ""))
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                result.append("    " + lines[index])
                index += 1
            if index < len(lines):
                index += 1
            result.append("")
            continue

        if index + 1 < len(lines) and "|" in line and is_table_separator(lines[index + 1]):
            table_lines, index = render_tui_table(lines, index, width)
            result.extend(table_lines)
            result.append("")
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            level = len(heading.group(1))
            text = plain_inline(heading.group(2))
            if result and result[-1] != "":
                result.append("")
            result.append(text)
            underline = "=" if level == 1 else "-"
            result.append(underline * min(max(3, len(text)), width))
            index += 1
            continue

        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            while index < len(lines):
                quote_match = re.match(r"^>\s?(.*)$", lines[index])
                if not quote_match:
                    break
                result.extend(wrap_plain(quote_match.group(1), width, prefix="> "))
                index += 1
            continue

        item = re.match(r"^(\s*)([-*+]|\d+[.])\s+(.+)$", line)
        if item:
            result.extend(wrap_plain(item.group(3), width, prefix=item.group(2) + " "))
            index += 1
            continue

        paragraph = [stripped]
        index += 1
        while index < len(lines):
            next_line = lines[index]
            next_stripped = next_line.strip()
            if not next_stripped:
                break
            if (
                re.match(r"^(#{1,6})\s+", next_line)
                or re.match(r"^(\s*)([-*+]|\d+[.])\s+", next_line)
                or next_stripped.startswith(("```", "~~~"))
                or (index + 1 < len(lines) and "|" in next_line and is_table_separator(lines[index + 1]))
            ):
                break
            paragraph.append(next_stripped)
            index += 1
        result.extend(wrap_plain(" ".join(paragraph), width))

    while result and result[-1] == "":
        result.pop()
    return result


def read_markdown_file(path):
    """Read a Markdown file as UTF-8 text.

    Читает Markdown-файл как UTF-8 текст.

    Args:
        path (str | Path): File path / путь к файлу.

    Returns:
        str: File content / содержимое файла.

    Raises:
        OSError: If the file cannot be read / если файл нельзя прочитать.
    """
    try:
        return Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return Path(path).read_text(encoding="utf-8-sig")


def discover_markdown_files(root):
    """Find Markdown files directly inside a directory.

    Находит Markdown-файлы непосредственно в указанном каталоге.

    Args:
        root (str | Path): Directory path / путь к каталогу.

    Returns:
        list[Path]: Sorted Markdown paths / отсортированные пути Markdown.
    """
    return sorted(
        path for path in Path(root).iterdir()
        if path.is_file() and path.suffix.lower() in {".md", ".markdown"}
    )


def page(title, body):
    """Wrap rendered content into a complete HTML page.

    Оборачивает отрендеренный контент в полную HTML-страницу.

    Args:
        title (str): Page title / заголовок страницы.
        body (str): HTML body fragment / HTML-фрагмент тела.

    Returns:
        str: Complete HTML document / полный HTML-документ.
    """
    return """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f7f7f4;
      --panel: #ffffff;
      --text: #202124;
      --muted: #5c626a;
      --border: #d7d7d0;
      --accent: #0b6b8f;
      --table-head: #e9f2f4;
      --code: #f1f1eb;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #16181a;
        --panel: #202326;
        --text: #eceff1;
        --muted: #aab1b8;
        --border: #3b4147;
        --accent: #6cc6e8;
        --table-head: #26343a;
        --code: #292d31;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.55;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 3;
      border-bottom: 1px solid var(--border);
      background: color-mix(in srgb, var(--panel) 92%, transparent);
      backdrop-filter: blur(8px);
    }}
    .bar {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 12px 20px;
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
    }}
    .brand {{
      font-weight: 700;
      white-space: nowrap;
    }}
    .path {{
      color: var(--muted);
      overflow-wrap: anywhere;
      text-align: right;
      font-size: 14px;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 20px 56px;
    }}
    h1, h2, h3, h4, h5, h6 {{
      line-height: 1.25;
      margin: 1.2em 0 0.55em;
    }}
    h1:first-child {{ margin-top: 0; }}
    a {{ color: var(--accent); }}
    p {{ margin: 0.65em 0; }}
    ul, ol {{ padding-left: 1.5rem; }}
    blockquote {{
      border-left: 4px solid var(--accent);
      margin: 1rem 0;
      padding: 0.2rem 0 0.2rem 1rem;
      color: var(--muted);
    }}
    pre {{
      overflow: auto;
      padding: 14px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--code);
    }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.94em;
    }}
    p code, li code, td code, th code {{
      padding: 0.1rem 0.28rem;
      border-radius: 4px;
      background: var(--code);
    }}
    .table-wrap {{
      overflow: auto;
      margin: 1rem 0 1.5rem;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
    }}
    table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      min-width: 720px;
      font-size: 14px;
    }}
    th, td {{
      padding: 9px 11px;
      border-right: 1px solid var(--border);
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }}
    th:last-child, td:last-child {{ border-right: 0; }}
    tr:last-child td {{ border-bottom: 0; }}
    thead th {{
      position: sticky;
      top: 0;
      z-index: 2;
      background: var(--table-head);
      font-weight: 700;
      text-align: left;
    }}
    .file-list {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 10px;
      padding: 0;
      list-style: none;
    }}
    .file-list a {{
      display: block;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 14px;
      background: var(--panel);
      text-decoration: none;
      color: var(--text);
    }}
    .file-list a:hover {{
      border-color: var(--accent);
      color: var(--accent);
    }}
    .empty {{
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div class="brand">{app_title}</div>
      <div class="path">{title}</div>
    </div>
  </header>
  <main>{body}</main>
</body>
</html>
""".format(
        title=html.escape(title),
        body=body,
        app_title=APP_TITLE,
    )


class ViewerHandler(http.server.BaseHTTPRequestHandler):
    """Serve the Markdown viewer over HTTP.

    Обслуживает Markdown-просмотрщик через HTTP.

    Class Attributes:
        root (Path): Base directory for discovered files / базовый каталог.
        files (list[Path]): Allowed files / разрешённые файлы.
        default_file_index (int | None): File to open at `/` / файл для `/`.
    """

    root = Path.cwd()
    files = []
    default_file_index = None

    def log_message(self, fmt, *args):
        """Write HTTP logs to stderr.

        Пишет HTTP-логи в stderr.

        Args:
            fmt (str): Log format / формат сообщения.
            *args: Format arguments / аргументы форматирования.

        Returns:
            None.
        """
        sys.stderr.write("{} - {}\n".format(self.address_string(), fmt % args))

    def send_html(self, title, body, status=200):
        """Send an HTML response.

        Отправляет HTML-ответ.

        Args:
            title (str): Page title / заголовок страницы.
            body (str): HTML body fragment / HTML-фрагмент тела.
            status (int): HTTP status code / HTTP-код ответа.

        Returns:
            None.
        """
        content = page(title, body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        """Handle supported GET routes.

        Обрабатывает поддерживаемые GET-маршруты.

        Args:
            None.

        Returns:
            None.
        """
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"", "/"}:
            if self.default_file_index is not None:
                self.render_file_by_index(self.default_file_index)
                return
            self.render_index()
            return
        if parsed.path == "/view":
            params = urllib.parse.parse_qs(parsed.query)
            if "id" in params:
                self.render_file_by_index(params.get("id", [""])[0])
                return
            self.render_file(params.get("file", [""])[0])
            return
        self.send_html("404", "<h1>404</h1><p>Страница не найдена.</p>", status=404)

    def render_index(self):
        """Render the file selection page.

        Рендерит страницу выбора файлов.

        Args:
            None.

        Returns:
            None.
        """
        if not self.files:
            self.send_html(
                "Файлы Markdown",
                "<h1>Файлы Markdown</h1><p class=\"empty\">В рабочем каталоге нет .md файлов.</p>",
            )
            return

        items = []
        for index, path in enumerate(self.files):
            title = str(path) if path.parent != self.root else path.name
            href = "/view?id={}".format(index)
            items.append('<li><a href="{}">{}</a></li>'.format(href, html.escape(title)))
        self.send_html("Файлы Markdown", "<h1>Файлы Markdown</h1><ul class=\"file-list\">{}</ul>".format("".join(items)))

    def render_path(self, path):
        """Render a concrete Markdown path.

        Рендерит конкретный Markdown-файл.

        Args:
            path (Path): File path / путь к файлу.

        Returns:
            None.
        """
        try:
            body = render_markdown(read_markdown_file(path))
        except OSError as error:
            self.send_html("Ошибка чтения", "<h1>Ошибка чтения</h1><p>{}</p>".format(html.escape(str(error))), status=500)
            return
        self.send_html(str(path), body)

    def render_file_by_index(self, index_value):
        """Render a file selected by internal index.

        Рендерит файл, выбранный по внутреннему индексу.

        Args:
            index_value (str | int): File index / индекс файла.

        Returns:
            None.
        """
        try:
            index = int(index_value)
        except (TypeError, ValueError):
            self.send_html("Ошибка", "<h1>Неверный индекс файла</h1>", status=400)
            return
        if index < 0 or index >= len(self.files):
            self.send_html("Ошибка", "<h1>Файл недоступен</h1>", status=404)
            return
        self.render_path(self.files[index])

    def render_file(self, name):
        """Render a file selected by basename.

        Рендерит файл, выбранный по имени без каталога.

        Args:
            name (str): Requested filename / запрошенное имя файла.

        Returns:
            None.
        """
        safe_name = posixpath.basename(name)
        if not safe_name:
            self.send_html("Ошибка", "<h1>Файл не выбран</h1>", status=400)
            return

        for path in self.files:
            if path.name == safe_name:
                self.render_path(path)
                return
        self.send_html("Ошибка", "<h1>Файл недоступен</h1><p>{}</p>".format(html.escape(safe_name)), status=404)


def build_parser():
    """Build the command-line parser.

    Создаёт парсер аргументов командной строки.

    Args:
        None.

    Returns:
        argparse.ArgumentParser: Configured parser / настроенный парсер.
    """
    parser = argparse.ArgumentParser(
        description="Просмотр Markdown-файлов с таблицами без внешних пакетов.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Markdown-файлы для показа. Если не указаны, берутся .md файлы из текущего каталога.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Адрес сервера, по умолчанию 0.0.0.0.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Порт сервера, по умолчанию 8765.")
    parser.add_argument("--no-browser", action="store_true", help="Не открывать браузер автоматически.")
    parser.add_argument("--tui", action="store_true", help="Открыть терминальный интерфейс вместо браузера.")
    return parser


def normalize_files(root, names):
    """Resolve input Markdown files.

    Разрешает входные Markdown-файлы.

    Args:
        root (str | Path): Directory for relative paths / каталог для относительных путей.
        names (list[str]): Explicit file names / явно указанные имена файлов.

    Returns:
        list[Path]: Sorted readable Markdown paths / читаемые Markdown-пути.

    Raises:
        SystemExit: For missing, unreadable, or non-Markdown files /
            для отсутствующих, нечитаемых или не-Markdown файлов.
    """
    if not names:
        return discover_markdown_files(root)

    files = []
    for name in names:
        path = Path(name)
        if not path.is_absolute():
            path = Path(root) / path
        try:
            path = path.resolve(strict=True)
        except OSError as error:
            raise SystemExit("Не удалось открыть {}: {}".format(name, error))
        # English: Explicit file arguments may point outside the workspace.
        # Русский: явно указанные файлы могут находиться вне рабочего каталога.
        if path.suffix.lower() not in {".md", ".markdown"}:
            raise SystemExit("Ожидался Markdown-файл: {}".format(name))
        if not os.access(str(path), os.R_OK):
            raise SystemExit("Файл недоступен для чтения: {}".format(name))
        files.append(path)
    return sorted(files)


def serve(args):
    """Run the HTTP viewer.

    Запускает HTTP-просмотрщик.

    Args:
        args (argparse.Namespace): Parsed CLI arguments / разобранные аргументы CLI.

    Returns:
        None.

    Raises:
        OSError: If the server socket cannot be opened / если серверный сокет не открыть.
    """
    root = Path.cwd()
    files = normalize_files(root, args.files)
    default_file_index = 0 if len(args.files) == 1 and files else None

    handler_class = type("ConfiguredViewerHandler", (ViewerHandler,), {
        "root": root,
        "files": files,
        "default_file_index": default_file_index,
    })

    class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        """HTTP server with one worker thread per request.

        HTTP-сервер с отдельным рабочим потоком на каждый запрос.
        """

        allow_reuse_address = True
        daemon_threads = True

    with ThreadingTCPServer((args.host, args.port), handler_class) as httpd:
        base_url = "http://{}:{}/".format(args.host, httpd.server_address[1])
        url = base_url
        if default_file_index is not None:
            url = "{}view?id={}".format(base_url, default_file_index)
        print("Открыт просмотр Markdown: {}".format(url))
        print("Файлы: {}".format(", ".join(path.name for path in files) if files else "нет"))
        print("Для остановки нажмите Ctrl+C")

        if not args.no_browser:
            threading.Timer(0.25, webbrowser.open, args=(url,)).start()

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nОстановлено.")


def tui_addstr(stdscr, y, x, text, attr=0):
    """Safely write clipped text to a curses window.

    Безопасно пишет обрезанный текст в окно curses.

    Args:
        stdscr: Curses window / окно curses.
        y (int): Row / строка.
        x (int): Column / колонка.
        text (str): Text to write / текст для вывода.
        attr (int): Curses attributes / атрибуты curses.

    Returns:
        None.
    """
    height, width = stdscr.getmaxyx()
    if y < 0 or y >= height or x >= width:
        return
    visible = max(0, width - x - 1)
    if visible <= 0:
        return
    try:
        stdscr.addnstr(y, x, text, visible, attr)
    except curses.error:
        return


def tui_slice(line, x_offset):
    """Apply horizontal scroll to one rendered line.

    Применяет горизонтальную прокрутку к одной строке.

    Args:
        line (str): Rendered line / отрендеренная строка.
        x_offset (int): Horizontal offset / горизонтальное смещение.

    Returns:
        str: Visible line suffix / видимая часть строки.
    """
    if x_offset <= 0:
        return line
    return line[x_offset:]


def tui_status(stdscr, text):
    """Draw the bottom status bar.

    Рисует нижнюю строку состояния.

    Args:
        stdscr: Curses window / окно curses.
        text (str): Status text / текст статуса.

    Returns:
        None.
    """
    height, width = stdscr.getmaxyx()
    attr = curses.A_REVERSE
    tui_addstr(stdscr, height - 1, 0, text.ljust(max(0, width - 1)), attr)


def tui_render_file_list(stdscr, files, selected, scroll):
    """Render the TUI file list.

    Рендерит список файлов в TUI.

    Args:
        stdscr: Curses window / окно curses.
        files (list[Path]): Available files / доступные файлы.
        selected (int): Selected index / выбранный индекс.
        scroll (int): First visible index / первый видимый индекс.

    Returns:
        None.
    """
    height, width = stdscr.getmaxyx()
    tui_addstr(stdscr, 0, 0, APP_TITLE, curses.A_BOLD)
    tui_addstr(stdscr, 1, 0, "Выберите Markdown-файл")
    rows = max(1, height - 4)
    for row, path in enumerate(files[scroll:scroll + rows], start=2):
        index = scroll + row - 2
        prefix = "> " if index == selected else "  "
        attr = curses.A_REVERSE if index == selected else 0
        tui_addstr(stdscr, row, 0, prefix + path.name, attr)
    tui_status(stdscr, "Enter открыть | ↑↓ выбор | q выход")


def tui_render_document(stdscr, path, document_lines, scroll, x_offset):
    """Render the opened document in TUI mode.

    Рендерит открытый документ в TUI-режиме.

    Args:
        stdscr: Curses window / окно curses.
        path (Path): Document path / путь к документу.
        document_lines (list[str]): Rendered lines / отрендеренные строки.
        scroll (int): First visible line / первая видимая строка.
        x_offset (int): Horizontal offset / горизонтальное смещение.

    Returns:
        None.
    """
    height, width = stdscr.getmaxyx()
    title = "{}  строка {}/{}  x={}".format(
        path.name,
        min(scroll + 1, max(1, len(document_lines))),
        max(1, len(document_lines)),
        x_offset,
    )
    tui_addstr(stdscr, 0, 0, title[:max(0, width - 1)], curses.A_BOLD)

    body_height = max(1, height - 2)
    for row in range(body_height):
        index = scroll + row
        if index >= len(document_lines):
            break
        line = tui_slice(document_lines[index], x_offset)
        attr = curses.A_BOLD if line.startswith(("+", "|")) else 0
        tui_addstr(stdscr, row + 1, 0, line, attr)

    tui_status(stdscr, "↑↓ PgUp/PgDn прокрутка | ←→ горизонтально | Home/End | r обновить | b список | q выход")


def tui_load_document(path, width):
    """Read and render a document for TUI display.

    Читает и рендерит документ для TUI.

    Args:
        path (Path): Document path / путь к документу.
        width (int): Terminal width / ширина терминала.

    Returns:
        list[str]: Rendered lines / отрендеренные строки.

    Raises:
        OSError: If the file cannot be read / если файл нельзя прочитать.
    """
    source = read_markdown_file(path)
    return render_tui_document(source, max(40, width - 1))


def tui_main(stdscr, files):
    """Run the curses event loop.

    Запускает цикл событий curses.

    Args:
        stdscr: Curses root window / корневое окно curses.
        files (list[Path]): Files to browse / файлы для просмотра.

    Returns:
        None.
    """
    curses.cbreak()
    stdscr.keypad(True)
    try:
        curses.curs_set(0)
    except curses.error:
        # English: Some terminals cannot hide the cursor; continue normally.
        # Русский: некоторые терминалы не умеют скрывать курсор; продолжаем работу.
        stdscr.leaveok(True)

    selected = 0
    list_scroll = 0
    mode = "document" if len(files) == 1 else "list"
    current_path = files[0] if files else None
    document_lines = []
    document_width = None
    doc_scroll = 0
    x_offset = 0

    while True:
        height, width = stdscr.getmaxyx()
        stdscr.erase()

        if not files:
            tui_addstr(stdscr, 0, 0, "В рабочем каталоге нет .md файлов.", curses.A_BOLD)
            tui_status(stdscr, "q выход")
            mode = "empty"
        elif mode == "list":
            rows = max(1, height - 4)
            if selected < list_scroll:
                list_scroll = selected
            if selected >= list_scroll + rows:
                list_scroll = selected - rows + 1
            tui_render_file_list(stdscr, files, selected, list_scroll)
        else:
            if current_path is None:
                current_path = files[selected]
            if document_width != width:
                document_lines = tui_load_document(current_path, width)
                document_width = width
                doc_scroll = min(doc_scroll, max(0, len(document_lines) - 1))
            tui_render_document(stdscr, current_path, document_lines, doc_scroll, x_offset)

        stdscr.refresh()
        key = stdscr.get_wch()
        key_name = key.lower() if isinstance(key, str) else key

        if key_name in {"q", "й"}:
            return

        if mode == "empty":
            continue

        if mode == "list":
            if key in (curses.KEY_UP,) or key_name in {"k", "л"}:
                selected = max(0, selected - 1)
            elif key in (curses.KEY_DOWN,) or key_name in {"j", "о"}:
                selected = min(len(files) - 1, selected + 1)
            elif key in (curses.KEY_NPAGE,):
                selected = min(len(files) - 1, selected + max(1, height - 4))
            elif key in (curses.KEY_PPAGE,):
                selected = max(0, selected - max(1, height - 4))
            elif key in (curses.KEY_HOME,):
                selected = 0
            elif key in (curses.KEY_END,):
                selected = len(files) - 1
            elif key in (curses.KEY_ENTER, "\n", "\r"):
                current_path = files[selected]
                document_lines = tui_load_document(current_path, width)
                document_width = width
                doc_scroll = 0
                x_offset = 0
                mode = "document"
            continue

        if key in (curses.KEY_UP,) or key_name in {"k", "л"}:
            doc_scroll = max(0, doc_scroll - 1)
        elif key in (curses.KEY_DOWN,) or key_name in {"j", "о"}:
            doc_scroll = min(max(0, len(document_lines) - 1), doc_scroll + 1)
        elif key in (curses.KEY_PPAGE,):
            doc_scroll = max(0, doc_scroll - max(1, height - 3))
        elif key in (curses.KEY_NPAGE, " "):
            doc_scroll = min(max(0, len(document_lines) - 1), doc_scroll + max(1, height - 3))
        elif key in (curses.KEY_LEFT,):
            x_offset = max(0, x_offset - 8)
        elif key in (curses.KEY_RIGHT,):
            x_offset += 8
        elif key in (curses.KEY_HOME,):
            doc_scroll = 0
            x_offset = 0
        elif key in (curses.KEY_END,):
            doc_scroll = max(0, len(document_lines) - 1)
        elif key_name in {"r", "к"}:
            document_lines = tui_load_document(current_path, width)
            document_width = width
            doc_scroll = min(doc_scroll, max(0, len(document_lines) - 1))
        elif key_name in {"b", "и", "\x1b", "\x7f"}:
            if len(files) > 1:
                mode = "list"


def run_tui(args):
    """Run the terminal user interface.

    Запускает терминальный пользовательский интерфейс.

    Args:
        args (argparse.Namespace): Parsed CLI arguments / разобранные аргументы CLI.

    Returns:
        None.
    """
    root = Path.cwd()
    files = normalize_files(root, args.files)
    locale.setlocale(locale.LC_ALL, "")
    curses.wrapper(tui_main, files)


def main(argv=None):
    """Program entry point.

    Точка входа программы.

    Args:
        argv (list[str] | None): Optional CLI arguments / необязательные аргументы CLI.

    Returns:
        int: Process exit code / код завершения процесса.
    """
    args = build_parser().parse_args(argv)
    if args.tui:
        run_tui(args)
    else:
        serve(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
