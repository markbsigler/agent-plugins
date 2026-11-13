"""Tests for zos_encoding.py, the EBCDIC helper bundled with every mainframe skill."""

from __future__ import annotations

from pathlib import Path

import pytest
import zos_encoding
from discovery import REPO_ROOT

SKILLS = REPO_ROOT / "code-modernization-plugin" / "skills"
VENDORED = sorted(SKILLS.glob("*/scripts/zos_encoding.py"))


def test_vendored_copies_are_identical() -> None:
    """Each skill bundles the module so it stays self-contained; edit one, copy it to all."""
    assert len(VENDORED) == 4, [str(path.relative_to(REPO_ROOT)) for path in VENDORED]
    canonical = (SKILLS / "mainframe-analysis" / "scripts" / "zos_encoding.py").read_bytes()
    stale = [str(p.relative_to(REPO_ROOT)) for p in VENDORED if p.read_bytes() != canonical]
    assert not stale, f"copy mainframe-analysis/scripts/zos_encoding.py over: {stale}"


@pytest.mark.parametrize(
    ("codepage", "data", "text"),
    [
        ("037", b"\x5b\x7b\x7c\xba\xbb", "$#@[]"),
        ("IBM-1047", b"\xad\xbd\x5f", "[]^"),
        ("cp273", b"\x7c\x4a\x5a", "§Ä\u00dc"),
        ("CCSID 285", b"\x5b\x4a", "£$"),
        ("297", b"\x7b\x7c", "£à"),
        ("1141", b"\x9f", "\u20ac"),
        ("1148", b"\x9f", "\u20ac"),
        ("870", b"\x9a", "\u0142"),
        ("1025", b"\xb9", "\u0410"),
    ],
)
def test_code_pages_decode_national_characters(codepage: str, data: bytes, text: str) -> None:
    assert zos_encoding.decode(data, codepage) == text
    assert zos_encoding.encode(text, codepage) == data


def test_every_code_page_round_trips_its_printable_characters() -> None:
    for name in zos_encoding.CODEPAGES:
        table = zos_encoding.decoding_table(name)
        chars = "".join(c for c in table if c.isprintable() and c != "\ufffd")
        assert zos_encoding.decode(zos_encoding.encode(chars, name), name) == chars, name


def test_codepage_names_and_encoding_errors() -> None:
    assert zos_encoding.normalize_codepage(37) == "cp037"
    assert zos_encoding.normalize_codepage("ibm1140") == "cp1140"
    with pytest.raises(ValueError, match="unsupported code page"):
        zos_encoding.normalize_codepage("1208")
    with pytest.raises(ValueError, match="cannot encode"):
        zos_encoding.encode("\u20ac", "037")
    assert zos_encoding.encode("A\u20acB", "037", errors="replace") == b"\xc1\x6f\xc2"


def test_mixed_data_keeps_double_byte_text_as_markers() -> None:
    sbcs = zos_encoding.encode("NAME ", "937")
    mixed = sbcs + b"\x0e\x45\x41\x45\x42\x0f" + zos_encoding.encode(" END", "937")
    assert zos_encoding.decode(mixed, "937") == "NAME <DBCS:45414542> END"
    assert zos_encoding.dbcs_spans(mixed) == 1
    assert "<DBCS" not in zos_encoding.decode(mixed, "037")
    assert zos_encoding.decode(mixed, "037", shift=True).count("<DBCS:") == 1
    unbalanced = sbcs + b"\x0e\x45"
    assert zos_encoding.decode(unbalanced, "937", shift=True) == "NAME \x0e\u00e1"


def rdw(body: bytes, segment: int = 0) -> bytes:
    return (len(body) + 4).to_bytes(2, "big") + bytes([segment, 0]) + body


def test_variable_records_join_spanned_segments() -> None:
    data = rdw(b"AB") + rdw(b"CD", 1) + rdw(b"EF", 3) + rdw(b"GH", 2) + rdw(b"")
    split = zos_encoding.split_records(data)
    assert (split.recfm, split.records) == ("V", [b"AB", b"CDEFGH", b""])
    assert zos_encoding.split_records(data, recfm="VB").records == split.records
    for broken in (rdw(b"AB")[:3], rdw(b"AB", 2), rdw(b"AB", 1), b"\x00\x02\x00\x00"):
        assert zos_encoding.rdw_records(broken) is None
    with pytest.raises(ValueError, match="RDW"):
        zos_encoding.split_records(b"\x40" * 10, recfm="V")


def test_fixed_and_new_line_records() -> None:
    split = zos_encoding.split_records(b"A" * 25, recfm="FB", lrecl=10)
    assert [len(record) for record in split.records] == [10, 10, 5]
    assert "not a multiple" in split.warnings[0]
    newline = zos_encoding.encode("ONE") + b"\x15" + zos_encoding.encode("TWO")
    assert zos_encoding.split_records(newline).records == [b"\xd6\xd5\xc5", b"\xe3\xe6\xd6"]
    assert zos_encoding.split_records(newline, recfm="NL").recfm == "NL"
    assert zos_encoding.split_records(b"").records == []
    with pytest.raises(ValueError, match="unsupported record format"):
        zos_encoding.split_records(b"", recfm="U")
    with pytest.raises(ValueError, match="positive"):
        zos_encoding.split_records(b"", recfm="F", lrecl=-1)


def test_decode_member_detects_text_ebcdic_and_binary() -> None:
    ebcdic = zos_encoding.encode("       01  REC.".ljust(80) + "       05  F PIC X.".ljust(80))
    member = zos_encoding.decode_member(ebcdic)
    assert member is not None
    expected = "       01  REC.\n       05  F PIC X."
    assert (member.encoding, member.text) == ("ebcdic-cp037", expected)
    variable = zos_encoding.decode_member(rdw(zos_encoding.encode("//JOB1    JOB  ")))
    assert variable is not None
    assert (variable.encoding, variable.text) == ("ebcdic-cp037-v", "//JOB1    JOB")
    text = zos_encoding.decode_member(b"//STEP1 EXEC PGM=X\n")
    assert text is not None
    assert text.encoding == "text"
    assert zos_encoding.decode_member(b"\x00\x01\x02 binary") is None
    explicit = zos_encoding.decode_member(zos_encoding.encode("ABCDEF"), recfm="F", lrecl=3)
    assert explicit is not None
    assert explicit.text == "ABC\nDEF"


def test_cli_lists_decodes_and_dumps(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert zos_encoding.main(["--list"]) == 0
    assert "1047  Latin-1 open systems" in capsys.readouterr().out
    member = tmp_path / "MEMBER"
    member.write_bytes(zos_encoding.encode("HELLO".ljust(80) + "WORLD".ljust(80), "1047"))
    assert zos_encoding.main([str(member), "--codepage", "1047", "--max-records", "1"]) == 0
    assert capsys.readouterr().out == "HELLO\n"
    data = tmp_path / "DATA"
    data.write_bytes(b"\xc1\x00\x12\x3c" * 3)
    assert zos_encoding.main([str(data), "--hex", "--recfm", "F", "--lrecl", "8"]) == 0
    captured = capsys.readouterr()
    assert "record 1 (8 bytes, RECFM F)" in captured.out
    assert "000000  C1 00 12 3C C1 00 12 3C" in captured.out
    assert "the last record is short" in captured.err
    binary = tmp_path / "LOAD"
    binary.write_bytes(b"\x00\x01binary\n")
    assert zos_encoding.main([str(binary)]) == 1
    assert zos_encoding.main([str(member), "--codepage", "9999"]) == 1
    assert "unsupported code page" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        zos_encoding.main([])
