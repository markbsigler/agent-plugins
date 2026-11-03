"""Tests for the aha-feature skill script, aha_html.py."""

from __future__ import annotations

import io
from pathlib import Path

import aha_html
import pytest

CONTEXT = aha_html.LinkContext(domain="example.aha.io", prefixes=frozenset({"APP"}))


def mention(ref: str, path: str = "records", reference_class: str = "Feature") -> str:
    icon = aha_html.MENTION_ICONS.get(reference_class, aha_html.MENTION_ICON)
    return (
        f'<a href="https://example.aha.io/{path}/{ref}?reference-class={reference_class}'
        '&amp;visible-fields=icon%2Cref" '
        f'data-linked-element-type="{reference_class}" data-visible-fields="icon,ref">'
        f"{icon} {ref}</a>"
    )


def to_html(markdown: str) -> str:
    return aha_html.markdown_to_html(markdown, CONTEXT)


@pytest.mark.parametrize(
    ("ref", "reference_class", "path"),
    [
        ("APP-12", "Feature", "records"),
        ("APP-12-3", "Requirement", "records"),
        ("APP-S-1", "Initiative", "initiatives"),
        ("APP-E-2", "Epic", "epics"),
        ("APP-R-5", "Release", "releases"),
        ("APP-G-1", "Goal", "records"),
        ("APP-G-1-KR-2", "KeyResult", "records"),
        ("APP-N-3", "Page", "pages"),
        ("APP-I-7", "Idea", "records"),
        ("APP-TODO-102", "Task", "tasks"),
    ],
)
def test_classify_reference(ref: str, reference_class: str, path: str) -> None:
    kind = aha_html.classify_reference(ref)

    assert kind == aha_html.RecordKind(reference_class, path)


@pytest.mark.parametrize("ref", ["APP", "app-1", "APP-S-1-2", "APP-12-KR-1", "APP-G-1-3"])
def test_classify_reference_rejects_other_shapes(ref: str) -> None:
    assert aha_html.classify_reference(ref) is None


def test_reference_from_url() -> None:
    requirement = "https://example.aha.io/records/APP-7-1?reference-class=Requirement"

    assert aha_html.reference_from_url(requirement) == ("example.aha.io", "APP-7-1")
    assert aha_html.reference_from_url("https://example.aha.io/tasks/APP-TODO-4%2Cname") == (
        "example.aha.io",
        "APP-TODO-4",
    )
    assert aha_html.reference_from_url("https://example.com/records/APP-1") is None
    assert aha_html.reference_from_url("https://example.aha.io/features/overview") is None


def test_headings_get_unique_ids_and_keep_bold() -> None:
    html = to_html("## Scope\n\n### **Agent Definition**\n\n## Scope ##")

    assert html == (
        '<h2 id="scope">Scope</h2>'
        '<h3 id="agent-definition"><strong>Agent Definition</strong></h3>'
        '<h2 id="scope-2">Scope</h2>'
    )


def test_inline_formatting_and_escapes() -> None:
    html = to_html(
        "**Bold** and *em* and _under_ and __strong__ and ~~gone~~ with `a < b` "
        "and snake_case_name and 5 * 3 and \\*literal\\* and a & b"
    )

    assert html == (
        "<p><strong>Bold</strong> and <em>em</em> and <em>under</em> and "
        "<strong>strong</strong> and <del>gone</del> with <code>a &lt; b</code> "
        "and snake_case_name and 5 * 3 and *literal* and a &amp; b</p>"
    )


def test_soft_and_hard_line_breaks() -> None:
    html = to_html("one\ntwo\\\nthree  \nfour")

    assert html == "<p>one two<br/>three<br/>four</p>"


def test_links_urls_and_images() -> None:
    html = to_html(
        "[docs](https://example.com/a?b=1&c=2), <https://example.com/x>, "
        "https://example.com/y. ![diagram](https://example.com/d.png)"
    )

    assert html == (
        '<p><a href="https://example.com/a?b=1&amp;c=2">docs</a>, '
        '<a href="https://example.com/x">https://example.com/x</a>, '
        '<a href="https://example.com/y">https://example.com/y</a>. '
        '<a href="https://example.com/d.png">diagram</a></p>'
    )


def test_record_mentions_follow_the_prefix_allowlist() -> None:
    html = to_html(
        "See APP-12, APP-S-1, and APP-TODO-4. PLAT-9 and UC-1 stay text. "
        "Linked: [PLAT-9](https://other.aha.io/features/PLAT-9). "
        "Named: [the agent](https://example.aha.io/features/APP-12). Code: `APP-12`."
    )

    assert mention("APP-12") in html
    assert mention("APP-S-1", "initiatives", "Initiative") in html
    assert mention("APP-TODO-4", "tasks", "Task") in html
    assert "PLAT-9 and UC-1 stay text" in html
    assert (
        'href="https://other.aha.io/records/PLAT-9?reference-class=Feature'
        '&amp;visible-fields=icon%2Cref"' in html
    )
    assert '<a href="https://example.aha.io/features/APP-12">the agent</a>' in html
    assert "<code>APP-12</code>" in html


def test_mentions_use_the_icon_aha_writes_for_each_record_type() -> None:
    html = to_html("APP-12, APP-12-3, APP-S-1, APP-E-2, and APP-R-5.")

    assert html.count("fa-grid-2") == 2
    assert '<i class="fa-solid fa-list aha-reference-icon"></i> APP-12-3' in html
    assert '<i class="fa-solid fa-sitemap aha-reference-icon"></i> APP-S-1' in html
    assert '<i class="aha-icon aha-icon-epic-solid aha-reference-icon"></i> APP-E-2' in html


def test_mentions_need_a_domain() -> None:
    context = aha_html.LinkContext(prefixes=frozenset({"APP"}))

    assert aha_html.markdown_to_html("APP-12", context) == "<p>APP-12</p>"
    assert aha_html.markdown_to_html("APP-12") == "<p>APP-12</p>"


def test_nested_lists_and_item_paragraphs() -> None:
    html = to_html(
        "1. First step\n"
        "2. Second step\n"
        "   continues here\n"
        "   - nested one\n"
        "   - nested two\n"
        "\n"
        "   A second paragraph.\n"
        "3. Third\n"
        "lazy line\n"
        "\n"
        "- other list"
    )

    assert html == (
        "<ol><li><p>First step</p></li>"
        "<li><p>Second step continues here</p>"
        "<ul><li><p>nested one</p></li><li><p>nested two</p></li></ul>"
        "<p>A second paragraph.</p></li>"
        "<li><p>Third lazy line</p></li></ol>"
        "<ul><li><p>other list</p></li></ul>"
    )


def test_list_type_change_starts_a_new_list() -> None:
    html = to_html("- bullet\n1. number")

    assert html == "<ul><li><p>bullet</p></li></ul><ol><li><p>number</p></li></ol>"


def test_checklist() -> None:
    html = to_html("- [ ] open\n- [x] done")

    assert html == (
        '<ul class="checklist">'
        '<li class="checklist-item--unchecked"><div class="checklist-item--content">'
        '<span class="checklist-item__indicator">\u2610</span><p>open</p></div></li>'
        '<li class="checklist-item--checked"><div class="checklist-item--content">'
        '<span class="checklist-item__indicator">\u2611</span><p>done</p></div></li></ul>'
    )


def test_table_with_alignment_breaks_pipes_and_ragged_rows() -> None:
    html = to_html(
        "| Element | Definition | Notes |\n"
        "|:---|:---:|---:|\n"
        "| Role | One job.<br>Second paragraph with `a \\| b` and x \\| y. |\n"
        "| Extra | a | b | c |"
    )

    assert html.startswith(
        '<table class="Editor__table"><thead class="Editor__thead"><tr class="Editor__tr">'
        '<th class="Editor__th"><p style="text-align:left">Element</p></th>'
    )
    assert '<p style="text-align:center">One job.</p>' in html
    assert "Second paragraph with <code>a | b</code> and x | y." in html
    assert '<td class="Editor__td"><p>c</p></td>' in html
    assert '<th class="Editor__th"><p></p></th>' in html


LIVE_TABLES = (
    '<p>Intro</p><div><table class="Editor__table Editor__table--sticky-header">\n'
    '<colgroup>\n<col style="width:11%">\n<col style="width: 89%"/>\n</colgroup>\n'
    '<thead class="Editor__thead"><tr class="Editor__tr">'
    '<th style="width:11%" class="Editor__th"><p style="text-align:left"><strong>Element</strong>'
    '</p></th><th class="Editor__th"><p>Definition <a href="https://example.aha.io/records/APP-7" '
    'data-linked-element-type="Feature"><i class="aha-reference-icon"></i> APP-7</a></p></th>'
    "</tr></thead><tbody><tr><td><p>Role</p></td><td><p>One</p></td></tr></tbody></table></div>"
    '<table class="Editor__table"><colgroup><col><col style="width:40%"></colgroup>'
    "<tbody><tr><td><p>A</p></td><td><p>B</p></td></tr></tbody></table>"
    '<table class="Editor__table"><tbody><tr><td><p>Plain</p></td></tr></tbody></table>'
    '<table><tr><th style="color:red; width: 30%"><p>X</p></th>'
    '<th style="width:70%"><p style="text-align:center">Y</p></th></tr></table>'
)


def test_table_layouts_read_classes_widths_and_headers() -> None:
    layouts = aha_html.table_layouts(LIVE_TABLES)

    assert layouts == [
        aha_html.TableLayout(
            ("element", "definition app-7"),
            "Editor__table Editor__table--sticky-header",
            ("11%", "89%"),
            ("left", ""),
        ),
        aha_html.TableLayout(("a", "b"), "Editor__table", ("", "40%"), ("", "")),
        aha_html.TableLayout(("plain",), "Editor__table", ("",), ("",)),
        aha_html.TableLayout(("x", "y"), "", ("30%", "70%"), ("", "center")),
    ]
    assert [layout.custom for layout in layouts] == [True, True, False, True]
    assert aha_html.table_layouts("<p>No tables</p>") == []


def test_tables_keep_their_live_layout_by_header() -> None:
    pool = aha_html.TableLayouts(aha_html.table_layouts(LIVE_TABLES))

    html = aha_html.markdown_to_html(
        "| **Element** | Definition APP-7 |\n|---|---|\n| Role | Two |\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
        "| X | Y |\n|---|---:|\n| 3 | 4 |\n\n"
        "| New | Table |\n|---|---|\n| x | y |",
        CONTEXT,
        pool,
    )

    assert html.startswith(
        '<table class="Editor__table Editor__table--sticky-header"><colgroup>'
        '<col style="width:11%"><col style="width:89%"></colgroup><thead class="Editor__thead">'
        '<tr class="Editor__tr"><th style="width:11%" class="Editor__th">'
        '<p style="text-align:left"><strong>Element</strong></p></th>'
        '<th style="width:89%" class="Editor__th"><p>Definition '
    )
    assert '<td style="width:11%" class="Editor__td"><p>Role</p></td>' in html
    assert '<table class="Editor__table"><colgroup><col><col style="width:40%"></colgroup>' in html
    assert '<td class="Editor__td"><p>1</p></td><td style="width:40%" class="Editor__td">' in html
    assert (
        '<colgroup><col style="width:30%"><col style="width:70%"></colgroup>'
        '<thead class="Editor__thead"><tr class="Editor__tr"><th style="width:30%" '
        'class="Editor__th"><p>X</p></th><th style="width:70%" class="Editor__th">'
        '<p style="text-align:right">Y</p></th>'
    ) in html
    assert '<table class="Editor__table"><thead' in html
    assert html.count("<colgroup>") == 3
    assert pool.unused() == []


def test_changed_tables_report_the_layout_they_lose() -> None:
    pool = aha_html.TableLayouts(aha_html.table_layouts(LIVE_TABLES))

    html = aha_html.markdown_to_html(
        "| Element | Definition APP-7 | Notes |\n|---|---|---|\n| Role | One | x |\n\n"
        "| Plain |\n|---|\n| y |",
        CONTEXT,
        pool,
    )

    assert "<colgroup>" not in html
    assert 'style="' not in html
    assert [layout.header for layout in pool.unused()] == [
        ("element", "definition app-7"),
        ("a", "b"),
        ("x", "y"),
    ]


def test_layout_widths_need_the_same_column_count() -> None:
    layout = aha_html.TableLayout(
        ("a", "b"), "Editor__table Editor__table--sticky-header", ("50%",)
    )
    pool = aha_html.TableLayouts([layout])

    html = aha_html.markdown_to_html("| A | B |\n|---|---|\n| 1 | 2 |", CONTEXT, pool)

    assert html.startswith('<table class="Editor__table Editor__table--sticky-header"><thead')
    assert pool.unused() == []


@pytest.mark.parametrize(
    ("marker", "kind"),
    [
        ("NOTE", "noteBlock"),
        ("INFO", "infoBlock"),
        ("IMPORTANT", "infoBlock"),
        ("TIP", "tipBlock"),
        ("WARNING", "warningBlock"),
        ("CAUTION", "warningBlock"),
    ],
)
def test_callout_types(marker: str, kind: str) -> None:
    assert to_html(f"> [!{marker}] Heads up.") == (
        f'<div data-callout-box-type="{kind}"><p>Heads up.</p></div>'
    )


def test_callout_holds_paragraphs_only() -> None:
    html = to_html("> [!NOTE]\n> ## Core\n> - one\n> - two\n>\n> Closing APP-12.")

    assert html == (
        '<div data-callout-box-type="noteBlock"><p><strong>Core</strong></p>'
        f"<p>one</p><p>two</p><p>Closing {mention('APP-12')}.</p></div>"
    )


def test_empty_callout_and_blockquotes() -> None:
    assert to_html("> [!TIP]") == '<div data-callout-box-type="tipBlock"><p></p></div>'
    assert to_html("> quoted") == "<blockquote>quoted</blockquote>"
    assert to_html("> one\n>\n> two") == "<blockquote><p>one</p><p>two</p></blockquote>"
    assert to_html("> [!UNKNOWN] text") == "<blockquote>[!UNKNOWN] text</blockquote>"


def test_code_fences_and_rules() -> None:
    html = to_html('```py\nprint("<x>")\n```\n\n~~~text\nplain\n~~~\n\n---\n\n````\n```\n````')

    assert html == (
        '<pre><code data-language="python">print("&lt;x&gt;")</code></pre>'
        "<pre><code>plain</code></pre><hr/><pre><code>```</code></pre>"
    )


def test_empty_markdown() -> None:
    assert to_html("") == ""
    assert to_html("\n\n") == ""


AHA_HTML = (
    '<div data-callout-box-type="noteBlock">\n<p>\u00a0</p>\n'
    "<p><strong>Core:</strong> see "
    '<a href="https://example.aha.io/records/APP-7?reference-class=Feature" '
    'data-linked-element-type="Feature" data-visible-fields="icon,ref">'
    '<i class="fa-solid fa-grid-2 fa-fw aha-reference-icon"></i> APP-7</a>.</p></div>'
    '<h3 id="x"><strong>Agent Definition</strong></h3>'
    '<table class="Editor__table"><tbody class="Editor__tbody">'
    '<tr class="Editor__tr"><th class="Editor__th"><p>Element</p></th>'
    '<th class="Editor__th"><p>Definition</p></th></tr>'
    '<tr class="Editor__tr"><td class="Editor__td"><p>Role</p></td>'
    '<td class="Editor__td"><p>One job | done.</p><p><br/></p><p>Second.</p>'
    "<ul><li><p>listed</p></li></ul></td></tr></tbody></table>"
    "<ol><li><p>Step <b>one</b></p><ul><li><p>nested <i>idea</i></p></li></ul></li>"
    "<li><p>Step two</p><p>More detail.</p></li></ol>"
    '<ul class="checklist"><li class="checklist-item--checked">'
    '<div class="checklist-item--content"><span class="checklist-item__indicator">\u2611</span>'
    "<p>Done</p></div></li></ul>"
    '<pre><code data-language="python">print("&lt;x&gt;")\n```</code></pre>'
    "<blockquote><p>Quoted</p></blockquote><hr/>"
    '<p>Line<br/>break <del>old</del> <em>new</em> <span class="labelPill">pill</span> '
    '<a href="https://example.com">site</a> <a href="https://example.com">https://example.com</a> '
    '<a href="https://example.aha.io/records/APP-8">APP-8</a> '
    '<a href="https://example.aha.io/records/APP-9">named</a> <a>bare</a> '
    '<img src="https://example.com/i.png" alt="img"/> <img alt="no source"/> '
    "<code>x | y</code></p><section><p>Section text</p></section>"
    "<p>Inline <p>stray</p> end</p><blockquote></blockquote>"
)

AHA_MARKDOWN = """> [!NOTE]
> **Core:** see APP-7.

### **Agent Definition**

| Element | Definition |
|---|---|
| Role | One job \\| done.<br>Second.<br>- listed |

1. Step **one**
   - nested *idea*
2. Step two

   More detail.

- [x] Done

````python
print("<x>")
```
````

> Quoted

---

Line\\
break ~~old~~ *new* pill [site](https://example.com) <https://example.com> APP-8 \
[named](https://example.aha.io/records/APP-9) bare ![img](https://example.com/i.png) no source \
`x | y`

Section text

Inline stray end"""


def test_html_to_markdown_handles_aha_editor_html() -> None:
    assert aha_html.html_to_markdown(AHA_HTML) == AHA_MARKDOWN.replace(" \\\n", " ")


def test_html_to_markdown_edge_cases() -> None:
    assert aha_html.html_to_markdown("") == ""
    assert aha_html.html_to_markdown("<table></table><ul></ul><h2> </h2>") == ""
    assert aha_html.html_to_markdown("<pre>raw</pre>") == "```\nraw\n```"
    assert aha_html.html_to_markdown('<div data-callout-box-type="tipBlock"></div>') == "> [!TIP]"
    assert aha_html.html_to_markdown("<p>a</div>b</p>") == "ab"
    assert aha_html.html_to_markdown("<p><strong> </strong>x</p>") == "x"


ROUND_TRIP = """> [!WARNING]
> **Scope:** read-only. See APP-S-1.

**As a** release manager, **I want** notes drafted, **so that** I review instead of collate.

### Agent Definition

| Element | Definition |
|---|---|
| Role | Drafts notes.<br>Second paragraph. |
| Out of scope | Publishing. Translations. Marketing copy. |

1. Collect changes.
2. Draft notes.
   - one per change

- [ ] open question

```bash
echo "done"
```

---

Final line with APP-12-1 and [docs](https://example.com/docs)."""


def test_markdown_round_trip_is_stable() -> None:
    html = to_html(ROUND_TRIP)

    assert aha_html.html_to_markdown(html) == ROUND_TRIP


def test_helpers() -> None:
    assert aha_html.split_table_row("| a | `b | c` | d \\| e |") == ["a", "`b | c`", "d \\| e"]
    assert aha_html.split_table_row("a | b") == ["a", "b"]
    assert aha_html.plain_text("**Bold** [link](https://x) ![alt](https://y)  `c`") == (
        "Bold link alt c"
    )
    assert aha_html.looks_like_html("<p>Text</p>")
    assert not aha_html.looks_like_html("**Markdown** <br>")
    assert aha_html.parse_prefixes(["app, plat", "", "OPS"]) == frozenset({"APP", "PLAT", "OPS"})


def test_main_to_html(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "draft.md"
    source.write_text("See APP-12.", encoding="utf-8")

    code = aha_html.main(
        ["to-html", str(source), "--aha-domain", "example.aha.io", "--link-prefix", "app"]
    )

    assert code == 0
    assert capsys.readouterr().out == f"<p>See {mention('APP-12')}.</p>\n"


def test_main_to_markdown_from_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("<p><strong>Hi</strong></p>"))

    assert aha_html.main(["to-markdown"]) == 0
    assert capsys.readouterr().out == "**Hi**\n"


def test_main_reports_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert aha_html.main(["to-markdown", str(tmp_path / "missing.html")]) == 2
    assert "error:" in capsys.readouterr().err
