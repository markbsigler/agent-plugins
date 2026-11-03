#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Convert between draft Markdown and Aha! Editor HTML.

Aha! text fields (a feature's Description, custom note fields, and the
descriptions of requirements and To-Dos) take Aha! Editor HTML through the
Aha! MCP server's manage_record tool. This module turns the Markdown subset
used in drafts into that HTML, with Aha! table classes, callouts, checklists,
and record mentions. It also turns Aha! Editor HTML back into the same subset.

Examples:
  uv run aha-feature/scripts/aha_html.py to-html draft.md --aha-domain example.aha.io --link-prefix APP
  uv run aha-feature/scripts/aha_html.py to-markdown description.html
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

MENTION_ICON = '<i class="fa-solid fa-grid-2 fa-fw aha-reference-icon"></i>'
# The icons the Aha! editor writes for other record types; the rest use MENTION_ICON.
MENTION_ICONS = {
    "Requirement": '<i class="fa-solid fa-list aha-reference-icon"></i>',
    "Initiative": '<i class="fa-solid fa-sitemap aha-reference-icon"></i>',
    "Epic": '<i class="aha-icon aha-icon-epic-solid aha-reference-icon"></i>',
}
CHECKED_BOX = "\u2611"
UNCHECKED_BOX = "\u2610"

CALLOUT_TYPES = {
    "NOTE": "noteBlock",
    "INFO": "infoBlock",
    "IMPORTANT": "infoBlock",
    "TIP": "tipBlock",
    "WARNING": "warningBlock",
    "CAUTION": "warningBlock",
}
CALLOUT_MARKERS = {
    "noteBlock": "NOTE",
    "infoBlock": "INFO",
    "tipBlock": "TIP",
    "warningBlock": "WARNING",
}

# Languages the Aha! editor highlights, with the Markdown fence names that map to them.
_LANGUAGE_ALIASES = {
    "bash": ("bash", "sh", "shell", "zsh"),
    "shell-session": ("console", "shell-session"),
    "clike": ("c", "cpp", "c++", "cs", "csharp", "clike"),
    "css": ("css",),
    "go": ("go",),
    "html": ("html",),
    "java": ("java",),
    "lua": ("lua",),
    "markdown": ("markdown", "md"),
    "markup": ("markup", "xml"),
    "objectivec": ("objc", "objectivec"),
    "python": ("python", "py"),
    "rb": ("rb", "ruby"),
    "rust": ("rust", "rs"),
    "sql": ("sql",),
    "swift": ("swift",),
    "tsx": ("javascript", "js", "jsx", "ts", "tsx", "typescript"),
    "yaml": ("yaml", "yml"),
}
CODE_LANGUAGES = {
    alias: language for language, aliases in _LANGUAGE_ALIASES.items() for alias in aliases
}

# Aha! record references: APP-12 (feature), APP-12-3 (requirement), APP-S-1 (initiative),
# APP-E-2 (epic), APP-R-5 (release), APP-G-1 (goal), APP-G-1-KR-1 (key result),
# APP-N-3 (page), APP-I-7 (idea), and APP-TODO-102 (To-Do).
REF_PATTERN = (
    r"(?P<ref>(?P<prefix>[A-Z][A-Z0-9]{1,19})-"
    r"(?:(?P<kind>TODO|S|E|R|G|N|I)-)?"
    r"(?P<num>\d+)"
    r"(?:-(?P<sub>KR-\d+|\d+))?)"
)
REF_RE = re.compile(r"(?<![\w/#.-])" + REF_PATTERN + r"(?![\w-])")

FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([\w+#.-]*)\s*$")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
HR_RE = re.compile(r"^\s{0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
LIST_ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-*+]|\d{1,9}[.)])(?:[ \t]+(?P<text>.*))?$"
)
QUOTE_RE = re.compile(r"^\s{0,3}>[ \t]?(.*)$")
CALLOUT_RE = re.compile(r"^\[!(\w+)\][ \t]*(.*)$")
CHECKBOX_RE = re.compile(r"^\[([ xX])\][ \t]+")

INLINE_CODE_RE = re.compile(r"(`+)(.+?)(?<!`)\1(?!`)")
ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~<])")
BREAK_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
AUTOLINK_RE = re.compile(r"<(https?://[^\s<>]+)>")
IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
LINK_RE = re.compile(r"(?<!!)\[(?P<text>[^\]]+)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
BARE_URL_RE = re.compile(r"(?<![\w\"'=/])https?://[^\s<>\"]*[^\s<>\".,;:!?)'\]]")
STRONG_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
STRONG_UNDERSCORE_RE = re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
EM_RE = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])")
EM_UNDERSCORE_RE = re.compile(r"(?<!\w)_(?=[^\s_])(.+?)(?<=[^\s_])_(?!\w)")
STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
PLACEHOLDER_RE = re.compile("\x00(\\d+)\x00")
DEFAULT_TABLE_CLASS = "Editor__table"
CELL_ALIGNMENTS = frozenset({"left", "center", "right"})


@dataclass(frozen=True)
class RecordKind:
    """The Aha! reference class and URL path segment of a record reference."""

    reference_class: str
    path: str


_KINDS = {
    "S": RecordKind("Initiative", "initiatives"),
    "E": RecordKind("Epic", "epics"),
    "R": RecordKind("Release", "releases"),
    "N": RecordKind("Page", "pages"),
    "I": RecordKind("Idea", "records"),
    "TODO": RecordKind("Task", "tasks"),
}


def classify_reference(ref: str) -> RecordKind | None:
    """Return the record kind of an Aha! reference such as APP-12-3, or None."""
    match = re.fullmatch(REF_PATTERN, ref)
    if match is None:
        return None
    kind, sub = match.group("kind"), match.group("sub")
    is_key_result = sub is not None and sub.startswith("KR-")
    if kind == "G":
        if sub is None:
            return RecordKind("Goal", "records")
        return RecordKind("KeyResult", "records") if is_key_result else None
    if is_key_result or (kind is not None and sub is not None):
        return None
    if kind is not None:
        return _KINDS[kind]
    return RecordKind("Requirement" if sub else "Feature", "records")


def reference_from_url(url: str) -> tuple[str, str] | None:
    """Return (host, reference) when url points at an Aha! record."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if not host.endswith(".aha.io"):
        return None
    last = unquote(parts.path.rstrip("/").rsplit("/", 1)[-1]).split(",", 1)[0]
    if classify_reference(last) is None:
        return None
    return host, last


@dataclass(frozen=True)
class LinkContext:
    """Where record mentions point, and which workspace prefixes become mentions."""

    domain: str | None = None
    prefixes: frozenset[str] = frozenset()
    visible_fields: str = "icon,ref"

    def mention(self, ref: str, host: str | None = None) -> str | None:
        """Return Aha! mention HTML for ref, or None when it can't be linked."""
        target_host = host or self.domain
        kind = classify_reference(ref)
        if not target_host or kind is None:
            return None
        query = f"reference-class={kind.reference_class}"
        if self.visible_fields:
            query += f"&visible-fields={quote(self.visible_fields, safe='')}"
        url = f"https://{target_host}/{kind.path}/{ref}?{query}"
        icon = MENTION_ICONS.get(kind.reference_class, MENTION_ICON)
        return (
            f'<a href="{html.escape(url)}" data-linked-element-type="{kind.reference_class}" '
            f'data-visible-fields="{self.visible_fields}">{icon} {ref}</a>'
        )

    def links(self, ref: str) -> bool:
        """Return whether a bare reference in text should become a mention."""
        return ref.split("-", 1)[0] in self.prefixes


@dataclass(frozen=True)
class TableLayout:
    """How Aha! draws one table, keyed by its header row.

    widths and header_aligns hold one entry per column; "" means not set.
    """

    header: tuple[str, ...]
    classes: str = ""
    widths: tuple[str, ...] = ()
    header_aligns: tuple[str, ...] = ()

    @property
    def custom(self) -> bool:
        """Return whether the table looks different from a newly rendered one."""
        extra_classes = set(self.classes.split()) - {DEFAULT_TABLE_CLASS}
        return any(self.widths) or any(self.header_aligns) or bool(extra_classes)


@dataclass
class TableLayouts:
    """Table layouts read from a live record; a rendered table with the same header uses one."""

    tables: list[TableLayout] = field(default_factory=list)
    used: set[int] = field(default_factory=set)

    def take(self, header: tuple[str, ...]) -> TableLayout | None:
        """Return the first unused layout whose header row matches."""
        for index, layout in enumerate(self.tables):
            if index not in self.used and layout.header == header:
                self.used.add(index)
                return layout
        return None

    def unused(self) -> list[TableLayout]:
        """Return the custom layouts that no rendered table matched; those tables lose them."""
        return [
            layout
            for index, layout in enumerate(self.tables)
            if index not in self.used and layout.custom
        ]


def header_key(cells: Sequence[str]) -> tuple[str, ...]:
    """Normalize a header row's cell texts, so a draft table and its Aha! table compare equal."""
    return tuple(
        " ".join(re.sub(r"[*_`~\\]", "", re.sub(r"<[^>]*>", " ", cell)).split()).lower()
        for cell in cells
    )


def split_table_row(line: str) -> list[str]:
    """Split a Markdown table row into cells, keeping escaped pipes and code spans."""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    cells: list[str] = []
    current: list[str] = []
    in_code = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and text[index + 1 : index + 2] == "|":
            current.append("\\|")
            index += 2
            continue
        if char == "`":
            in_code = not in_code
        if char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells


def plain_text(markdown: str) -> str:
    """Return the visible words of a Markdown fragment, without formatting."""
    text = IMAGE_RE.sub(lambda match: match.group("alt"), markdown)
    text = LINK_RE.sub(lambda match: match.group("text"), text)
    text = re.sub(r"[*_`~]", "", text)
    return " ".join(text.split())


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _anchor(url: str, label_html: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{label_html}</a>'


def _emphasis(text: str) -> str:
    text = STRONG_RE.sub(r"<strong>\1</strong>", text)
    text = STRONG_UNDERSCORE_RE.sub(r"<strong>\1</strong>", text)
    text = EM_RE.sub(r"<em>\1</em>", text)
    text = EM_UNDERSCORE_RE.sub(r"<em>\1</em>", text)
    return STRIKE_RE.sub(r"<del>\1</del>", text)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _dedent(lines: list[str]) -> list[str]:
    cut = min((_indent(line) for line in lines if line.strip()), default=0)
    return [line[cut:] if line.strip() else "" for line in lines]


def is_table_start(lines: Sequence[str], index: int) -> bool:
    """Return whether lines[index] is a table header followed by a separator row."""
    return (
        "|" in lines[index]
        and index + 1 < len(lines)
        and "|" in lines[index + 1]
        and TABLE_SEPARATOR_RE.match(lines[index + 1]) is not None
    )


def _is_list_item(line: str) -> bool:
    item = LIST_ITEM_RE.match(line)
    return item is not None and item.group("text") is not None and not HR_RE.match(line)


def _continues_list(line: str, base: int, ordered: bool) -> bool:
    if _indent(line) > base:
        return True
    item = LIST_ITEM_RE.match(line)
    return (
        item is not None
        and _is_list_item(line)
        and _indent(line) == base
        and item.group("marker")[0].isdigit() == ordered
    )


def _alignment(cell: str) -> str | None:
    cell = cell.strip()
    if cell.startswith(":") and cell.endswith(":"):
        return "center"
    if cell.endswith(":"):
        return "right"
    if cell.startswith(":"):
        return "left"
    return None


def _pad(row: list[str], width: int) -> list[str]:
    return [*row, *([""] * (width - len(row)))]


class _MarkdownRenderer:
    """Render the draft Markdown subset as Aha! Editor HTML."""

    def __init__(self, context: LinkContext, layouts: TableLayouts | None = None) -> None:
        self.context = context
        self.layouts = layouts
        self._slugs: dict[str, int] = {}

    def render(self, markdown: str) -> str:
        self._slugs = {}
        text = markdown.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
        return self._blocks(text.split("\n"))

    def inline(self, text: str, *, links: bool = True) -> str:
        """Render inline Markdown: code, emphasis, links, and record mentions."""
        stash: list[str] = []

        def keep(fragment: str) -> str:
            stash.append(fragment)
            return f"\x00{len(stash) - 1}\x00"

        text = INLINE_CODE_RE.sub(
            lambda match: keep(f"<code>{_escape(match.group(2).strip())}</code>"), text
        )
        text = ESCAPE_RE.sub(lambda match: keep(_escape(match.group(1))), text)
        text = BREAK_TAG_RE.sub(lambda _match: keep("<br/>"), text)
        if links:
            text = AUTOLINK_RE.sub(
                lambda match: keep(_anchor(match.group(1), _escape(match.group(1)))), text
            )
            text = IMAGE_RE.sub(
                lambda match: keep(
                    _anchor(match.group("url"), _escape(match.group("alt") or match.group("url")))
                ),
                text,
            )
            text = LINK_RE.sub(
                lambda match: keep(self._link(match.group("text"), match.group("url"))), text
            )
        text = _escape(text)
        if links:
            text = BARE_URL_RE.sub(
                lambda match: keep(_anchor(html.unescape(match.group(0)), match.group(0))), text
            )
        text = _emphasis(text)
        if links:
            text = REF_RE.sub(self._reference, text)
        return PLACEHOLDER_RE.sub(lambda match: stash[int(match.group(1))], text)

    def _link(self, text: str, url: str) -> str:
        target = reference_from_url(url)
        if target is not None and text.strip() == target[1]:
            mention = self.context.mention(target[1], host=target[0])
            if mention is not None:
                return mention
        return _anchor(url, self.inline(text, links=False))

    def _reference(self, match: re.Match[str]) -> str:
        ref = match.group("ref")
        mention = self.context.mention(ref) if self.context.links(ref) else None
        return mention or ref

    def _starts_block(self, lines: Sequence[str], index: int) -> bool:
        line = lines[index]
        if FENCE_RE.match(line) or HEADING_RE.match(line) or HR_RE.match(line):
            return True
        if QUOTE_RE.match(line) or _is_list_item(line):
            return True
        return is_table_start(lines, index)

    def _blocks(self, lines: list[str]) -> str:
        output: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue
            heading = HEADING_RE.match(line)
            if FENCE_RE.match(line):
                block, index = self._code(lines, index)
            elif heading is not None:
                block = self._heading(len(heading.group(1)), heading.group(2))
                index += 1
            elif HR_RE.match(line):
                block = "<hr/>"
                index += 1
            elif is_table_start(lines, index):
                block, index = self._table(lines, index)
            elif QUOTE_RE.match(line):
                block, index = self._quote(lines, index)
            elif _is_list_item(line):
                block, index = self._list(lines, index)
            else:
                paragraph = [line]
                index += 1
                while (
                    index < len(lines)
                    and lines[index].strip()
                    and not self._starts_block(lines, index)
                ):
                    paragraph.append(lines[index])
                    index += 1
                block = self._paragraph(paragraph)
            output.append(block)
        return "".join(output)

    def _paragraph(self, lines: list[str]) -> str:
        parts: list[str] = []
        for index, raw in enumerate(lines):
            text = raw.strip()
            soft_break = text.endswith("\\") and not text.endswith("\\\\")
            if soft_break:
                text = text[:-1].rstrip()
            parts.append(text)
            if index < len(lines) - 1:
                parts.append("<br>" if soft_break or raw.endswith("  ") else " ")
        return f"<p>{self.inline(''.join(parts))}</p>"

    def _heading(self, level: int, text: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", plain_text(text).lower()).strip("-") or "section"
        seen = self._slugs.get(slug, 0)
        self._slugs[slug] = seen + 1
        if seen:
            slug = f"{slug}-{seen + 1}"
        return f'<h{level} id="{slug}">{self.inline(text)}</h{level}>'

    def _code(self, lines: list[str], start: int) -> tuple[str, int]:
        match = FENCE_RE.match(lines[start])
        if match is None:
            raise ValueError(f"line {start + 1} is not a code fence")
        fence, language = match.group(1), match.group(2).lower()
        body: list[str] = []
        index = start + 1
        while index < len(lines):
            closing = lines[index].strip()
            if closing and set(closing) == {fence[0]} and len(closing) >= len(fence):
                index += 1
                break
            body.append(lines[index])
            index += 1
        code = _escape("\n".join(body))
        code_language = CODE_LANGUAGES.get(language)
        attribute = f' data-language="{code_language}"' if code_language else ""
        return f"<pre><code{attribute}>{code}</code></pre>", index

    def _table(self, lines: list[str], start: int) -> tuple[str, int]:
        header = split_table_row(lines[start])
        aligns = [_alignment(cell) for cell in split_table_row(lines[start + 1])]
        rows: list[list[str]] = []
        index = start + 2
        while index < len(lines) and lines[index].strip() and "|" in lines[index]:
            rows.append(split_table_row(lines[index]))
            index += 1
        width = max([len(header), *(len(row) for row in rows)])
        layout = None
        if self.layouts is not None:
            layout = self.layouts.take(
                header_key([plain_text(cell) for cell in _pad(header, width)])
            )
        widths = layout.widths if layout is not None and len(layout.widths) == width else ()
        header_aligns = layout.header_aligns if layout is not None else ()

        def align(column: int) -> str | None:
            return aligns[column] if column < len(aligns) else None

        def header_align(column: int) -> str | None:
            live = header_aligns[column] if column < len(header_aligns) else ""
            return align(column) or live or None

        def column_width(column: int) -> str:
            return widths[column] if column < len(widths) else ""

        head = "".join(
            self._cell("th", text, header_align(column), column_width(column))
            for column, text in enumerate(_pad(header, width))
        )
        body = "".join(
            '<tr class="Editor__tr">'
            + "".join(
                self._cell("td", text, align(column), column_width(column))
                for column, text in enumerate(_pad(row, width))
            )
            + "</tr>"
            for row in rows
        )
        classes = layout.classes if layout is not None and layout.classes else DEFAULT_TABLE_CLASS
        columns = ""
        if any(widths):
            columns = (
                "<colgroup>"
                + "".join(
                    f'<col style="width:{html.escape(value)}">' if value else "<col>"
                    for value in widths
                )
                + "</colgroup>"
            )
        return (
            (
                f'<table class="{html.escape(classes)}">{columns}'
                '<thead class="Editor__thead"><tr class="Editor__tr">'
                f'{head}</tr></thead><tbody class="Editor__tbody">{body}</tbody></table>'
            ),
            index,
        )

    def _cell(self, tag: str, text: str, align: str | None, width: str = "") -> str:
        style = f' style="text-align:{align}"' if align else ""
        cell_style = f' style="width:{html.escape(width)}"' if width else ""
        # As in GFM, a table unescapes \| before inline parsing, including inside code spans.
        parts = BREAK_TAG_RE.split(text.replace("\\|", "|")) if text else [""]
        paragraphs = "".join(f"<p{style}>{self.inline(part.strip())}</p>" for part in parts)
        return f'<{tag}{cell_style} class="Editor__{tag}">{paragraphs}</{tag}>'

    def _quote(self, lines: list[str], start: int) -> tuple[str, int]:
        inner: list[str] = []
        index = start
        while index < len(lines):
            match = QUOTE_RE.match(lines[index])
            if match is None:
                break
            inner.append(match.group(1))
            index += 1
        callout = CALLOUT_RE.match(inner[0].strip()) if inner else None
        if callout is not None and callout.group(1).upper() in CALLOUT_TYPES:
            first = callout.group(2).strip()
            body = [first, *inner[1:]] if first else inner[1:]
            return self._callout(CALLOUT_TYPES[callout.group(1).upper()], body), index
        content = self._blocks(inner)
        if content.startswith("<p>") and content.endswith("</p>") and content.count("<p>") == 1:
            content = content[3:-4]
        return f"<blockquote>{content}</blockquote>", index

    def _callout(self, kind: str, lines: list[str]) -> str:
        # Aha! callouts hold paragraphs only, so list items and headings become paragraphs.
        paragraphs: list[list[str]] = [[]]
        for line in lines:
            heading = HEADING_RE.match(line)
            item = LIST_ITEM_RE.match(line)
            if not line.strip():
                paragraphs.append([])
            elif heading is not None:
                paragraphs.extend([[f"**{heading.group(2)}**"], []])
            elif item is not None and _is_list_item(line):
                paragraphs.append([item.group("text") or ""])
            else:
                paragraphs[-1].append(line.strip())
        body = "".join(self._paragraph(chunk) for chunk in paragraphs if "".join(chunk).strip())
        return f'<div data-callout-box-type="{kind}">{body or "<p></p>"}</div>'

    def _list(self, lines: list[str], start: int) -> tuple[str, int]:
        first = LIST_ITEM_RE.match(lines[start])
        if first is None:
            raise ValueError(f"line {start + 1} is not a list item")
        base = _indent(lines[start])
        ordered = first.group("marker")[0].isdigit()
        items: list[list[str]] = []
        index = start
        while index < len(lines):
            line = lines[index]
            item = LIST_ITEM_RE.match(line)
            if item is not None and _is_list_item(line) and _indent(line) == base:
                if item.group("marker")[0].isdigit() != ordered:
                    break
                items.append([item.group("text") or ""])
                index += 1
                continue
            if not line.strip():
                ahead = index + 1
                while ahead < len(lines) and not lines[ahead].strip():
                    ahead += 1
                if ahead < len(lines) and _continues_list(lines[ahead], base, ordered):
                    items[-1].append("")
                    index += 1
                    continue
                break
            if _indent(line) > base:
                items[-1].append(line)
                index += 1
                continue
            if items[-1][-1].strip() and not self._starts_block(lines, index):
                items[-1].append(" " * (base + 2) + line.strip())
                index += 1
                continue
            break
        checklist = not ordered and CHECKBOX_RE.match(items[0][0]) is not None
        rendered = [self._item(item_lines, checklist) for item_lines in items]
        if checklist:
            return f'<ul class="checklist">{"".join(rendered)}</ul>', index
        tag = "ol" if ordered else "ul"
        return f"<{tag}>{''.join(rendered)}</{tag}>", index

    def _item(self, item_lines: list[str], checklist: bool) -> str:
        head, rest = item_lines[0], item_lines[1:]
        stripped = [line.strip() for line in rest]
        paragraph = [head]
        position = 0
        while (
            position < len(rest)
            and stripped[position]
            and not self._starts_block(stripped, position)
        ):
            paragraph.append(stripped[position])
            position += 1
        inner_lines = _dedent(rest[position:])
        inner = self._blocks(inner_lines) if any(line.strip() for line in inner_lines) else ""
        if not checklist:
            return f"<li>{self._paragraph(paragraph)}{inner}</li>"
        box = CHECKBOX_RE.match(paragraph[0])
        checked = box is not None and box.group(1).lower() == "x"
        if box is not None:
            paragraph[0] = paragraph[0][box.end() :]
        state = "checked" if checked else "unchecked"
        indicator = CHECKED_BOX if checked else UNCHECKED_BOX
        return (
            f'<li class="checklist-item--{state}"><div class="checklist-item--content">'
            f'<span class="checklist-item__indicator">{indicator}</span>'
            f"{self._paragraph(paragraph)}</div>{inner}</li>"
        )


def markdown_to_html(
    markdown: str, context: LinkContext | None = None, layouts: TableLayouts | None = None
) -> str:
    """Convert draft Markdown into Aha! Editor HTML.

    With layouts (from table_layouts on the field's live HTML), a table whose header row is
    unchanged keeps its live classes and column widths.
    """
    return _MarkdownRenderer(context or LinkContext(), layouts).render(markdown)


BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "dd",
        "div",
        "dl",
        "dt",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
VOID_TAGS = frozenset({"br", "col", "hr", "img", "input", "link", "meta", "source", "wbr"})


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_Node | str] = field(default_factory=list)

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())


class _TreeBuilder(HTMLParser):
    """Build a small element tree from Aha! Editor HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self._stack: list[_Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {key: value or "" for key, value in attrs})
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack[-1].children.append(_Node(tag, {key: value or "" for key, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


def _text_content(node: _Node | str) -> str:
    if isinstance(node, str):
        return node
    if node.tag == "br":
        return "\n"
    return "".join(_text_content(child) for child in node.children)


def _wrap(inner: str, marker: str) -> str:
    match = re.fullmatch(r"(\s*)(.*?)(\s*)", inner, re.DOTALL)
    if match is None or not match.group(2):
        return inner
    lead, core, trail = match.groups()
    return f"{lead}{marker}{core}{marker}{trail}"


def _hard_breaks(text: str) -> str:
    lines = [" ".join(part.split()) for part in text.split("\n")]
    return "\\\n".join(line for line in lines if line)


def _quote_lines(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.split("\n"))


def _table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _rows(node: _Node) -> list[_Node]:
    rows: list[_Node] = []
    for child in node.children:
        if isinstance(child, _Node):
            if child.tag == "tr":
                rows.append(child)
            elif child.tag != "table":
                rows.extend(_rows(child))
    return rows


def _checklist_children(item: _Node) -> list[_Node | str]:
    children: list[_Node | str] = []
    for child in item.children:
        if isinstance(child, _Node) and "checklist-item--content" in child.classes():
            children.extend(
                inner
                for inner in child.children
                if not (isinstance(inner, _Node) and "checklist-item__indicator" in inner.classes())
            )
        else:
            children.append(child)
    return children


class _MarkdownWriter:
    """Write an Aha! Editor HTML tree as the draft Markdown subset."""

    def document(self, root: _Node) -> str:
        return "\n\n".join(self.blocks(root)).strip()

    def blocks(self, node: _Node) -> list[str]:
        output: list[str] = []
        run: list[_Node | str] = []
        for child in node.children:
            if isinstance(child, _Node) and child.tag in BLOCK_TAGS:
                self._flush(run, output)
                output.extend(self.block(child))
            else:
                run.append(child)
        self._flush(run, output)
        return output

    def _flush(self, run: list[_Node | str], output: list[str]) -> None:
        text = _hard_breaks(self.inline_all(run))
        if text:
            output.append(text)
        run.clear()

    def block(self, node: _Node) -> list[str]:
        tag = node.tag
        if tag == "p":
            text = _hard_breaks(self.inline_all(node.children))
            return [text] if text else []
        if tag in HEADING_TAGS:
            text = " ".join(self.inline_all(node.children).split())
            return [f"{'#' * int(tag[1])} {text}"] if text else []
        if tag in ("ul", "ol"):
            text = self.bullet_list(node, 0)
            return [text] if text else []
        if tag == "table":
            text = self.table(node)
            return [text] if text else []
        if tag == "pre":
            return [self.pre(node)]
        if tag == "hr":
            return ["---"]
        if tag == "blockquote":
            body = "\n\n".join(self.blocks(node))
            return [_quote_lines(body)] if body else []
        callout = node.attrs.get("data-callout-box-type")
        if tag == "div" and callout:
            body = "\n\n".join(self.blocks(node))
            marker = f"> [!{CALLOUT_MARKERS.get(callout, 'NOTE')}]"
            return [f"{marker}\n{_quote_lines(body)}" if body else marker]
        return self.blocks(node)

    def inline_all(self, nodes: Sequence[_Node | str]) -> str:
        return "".join(self.inline(node) for node in nodes)

    def inline(self, node: _Node | str) -> str:
        if isinstance(node, str):
            return re.sub(r"[ \t\r\n\f\v\xa0]+", " ", node)
        tag = node.tag
        if tag == "br":
            return "\n"
        if tag == "i" and "aha-reference-icon" in node.classes():
            return ""
        if tag == "img":
            alt, src = node.attrs.get("alt", ""), node.attrs.get("src", "")
            return f"![{alt}]({src})" if src else alt
        if tag == "code":
            return f"`{_text_content(node)}`"
        inner = self.inline_all(node.children)
        if tag in ("strong", "b"):
            return _wrap(inner, "**")
        if tag in ("em", "i"):
            return _wrap(inner, "*")
        if tag in ("del", "s", "strike"):
            return _wrap(inner, "~~")
        if tag == "a":
            return self.anchor(node, inner)
        if tag in BLOCK_TAGS:
            return f" {inner} "
        return inner

    def anchor(self, node: _Node, inner: str) -> str:
        href = node.attrs.get("href", "")
        label = " ".join(inner.split())
        target = reference_from_url(href) if href else None
        if "data-linked-element-type" in node.attrs:
            if classify_reference(label) is not None:
                return label
            if target is not None:
                return target[1]
        if target is not None and label == target[1]:
            return label
        if not href:
            return inner
        if label == href:
            return f"<{href}>"
        return f"[{label or href}]({href})"

    def bullet_list(self, node: _Node, indent: int) -> str:
        ordered = node.tag == "ol"
        checklist = "checklist" in node.classes()
        lines: list[str] = []
        number = 0
        for item in node.children:
            if not isinstance(item, _Node) or item.tag != "li":
                continue
            number += 1
            marker = f"{number}." if ordered else "-"
            pad = " " * (indent + len(marker) + 1)
            if checklist:
                marker += " [x]" if "checklist-item--checked" in item.classes() else " [ ]"
            children = _checklist_children(item) if checklist else item.children
            parts: list[str] = []
            nested: list[str] = []
            run: list[_Node | str] = []
            for child in children:
                if isinstance(child, _Node) and child.tag in ("ul", "ol"):
                    self._flush(run, parts)
                    nested.append(self.bullet_list(child, len(pad)))
                elif isinstance(child, _Node) and child.tag in BLOCK_TAGS:
                    self._flush(run, parts)
                    parts.extend(self.block(child))
                else:
                    run.append(child)
            self._flush(run, parts)
            first = (parts[0] if parts else "").split("\n")
            lines.append(f"{' ' * indent}{marker} {first[0]}".rstrip())
            lines.extend(f"{pad}{line}" for line in first[1:])
            for extra in parts[1:]:
                lines.append("")
                lines.extend(f"{pad}{line}" if line else "" for line in extra.split("\n"))
            lines.extend(nested)
        return "\n".join(lines)

    def table(self, node: _Node) -> str:
        rows: list[list[str]] = []
        for row in _rows(node):
            cells = [
                self.cell(cell)
                for cell in row.children
                if isinstance(cell, _Node) and cell.tag in ("td", "th")
            ]
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        padded = [_pad(row, width) for row in rows]
        lines = [_table_row(padded[0]), "|" + "|".join(["---"] * width) + "|"]
        lines.extend(_table_row(row) for row in padded[1:])
        return "\n".join(lines)

    def cell(self, node: _Node) -> str:
        parts: list[str] = []
        for block in self.blocks(node):
            parts.extend(line.rstrip("\\").strip() for line in block.split("\n"))
        return "<br>".join(part for part in parts if part).replace("|", "\\|")

    def pre(self, node: _Node) -> str:
        code = next(
            (child for child in node.children if isinstance(child, _Node) and child.tag == "code"),
            None,
        )
        language = code.attrs.get("data-language", "") if code is not None else ""
        text = _text_content(code if code is not None else node).strip("\n")
        fence = "```"
        while fence in text:
            fence += "`"
        return f"{fence}{language}\n{text}\n{fence}"


def html_to_markdown(source: str) -> str:
    """Convert Aha! Editor HTML into the Markdown subset used in drafts."""
    builder = _TreeBuilder()
    builder.feed(source)
    builder.close()
    return _MarkdownWriter().document(builder.root)


def _style(node: _Node | None, name: str) -> str:
    """Return one CSS property from a node's style attribute, or ""."""
    if node is None:
        return ""
    for declaration in node.attrs.get("style", "").split(";"):
        key, _, value = declaration.partition(":")
        if key.strip().lower() == name:
            return value.strip()
    return ""


def _cell_alignment(cell: _Node) -> str:
    paragraph = next(
        (child for child in cell.children if isinstance(child, _Node) and child.tag == "p"), None
    )
    value = (_style(cell, "text-align") or _style(paragraph, "text-align")).lower()
    return value if value in CELL_ALIGNMENTS else ""


def table_layouts(source: str) -> list[TableLayout]:
    """Return each table's classes, column widths, and header alignment, in document order.

    Widths come from the table's colgroup, or from its first row's cells when it has none.
    """
    builder = _TreeBuilder()
    builder.feed(source)
    builder.close()
    layouts: list[TableLayout] = []

    def visit(node: _Node) -> None:
        for child in node.children:
            if not isinstance(child, _Node):
                continue
            if child.tag != "table":
                visit(child)
                continue
            rows = _rows(child)
            cells = [
                cell
                for cell in (rows[0].children if rows else [])
                if isinstance(cell, _Node) and cell.tag in ("td", "th")
            ]
            widths = [
                _style(column, "width")
                for group in child.children
                if isinstance(group, _Node) and group.tag == "colgroup"
                for column in group.children
                if isinstance(column, _Node) and column.tag == "col"
            ] or [_style(cell, "width") for cell in cells]
            layouts.append(
                TableLayout(
                    header_key([_text_content(cell) for cell in cells]),
                    child.attrs.get("class", ""),
                    tuple(widths),
                    tuple(_cell_alignment(cell) for cell in cells),
                )
            )

    visit(builder.root)
    return layouts


def looks_like_html(text: str) -> bool:
    """Return whether a field value is HTML rather than Markdown."""
    stripped = text.lstrip()
    return stripped.startswith("<") and re.search(r"</[a-z][a-z0-9]*\s*>", stripped) is not None


def parse_prefixes(values: Sequence[str]) -> frozenset[str]:
    """Parse repeated or comma-separated workspace prefixes such as APP,PLAT."""
    return frozenset(
        part.strip().upper() for value in values for part in value.split(",") if part.strip()
    )


def _read(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert between draft Markdown and Aha! Editor HTML."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    to_html = commands.add_parser("to-html", help="Markdown to Aha! Editor HTML")
    to_html.add_argument("source", nargs="?", default="-", help="Markdown file, or - for stdin")
    to_html.add_argument("--aha-domain", help="Aha! host for record mentions, e.g. example.aha.io")
    to_html.add_argument(
        "--link-prefix",
        action="append",
        default=[],
        help="Workspace prefix whose bare references become mentions (repeatable)",
    )
    to_markdown = commands.add_parser("to-markdown", help="Aha! Editor HTML to Markdown")
    to_markdown.add_argument("source", nargs="?", default="-", help="HTML file, or - for stdin")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        text = _read(args.source)
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.command == "to-html":
        context = LinkContext(domain=args.aha_domain, prefixes=parse_prefixes(args.link_prefix))
        sys.stdout.write(markdown_to_html(text, context) + "\n")
    else:
        sys.stdout.write(html_to_markdown(text) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
