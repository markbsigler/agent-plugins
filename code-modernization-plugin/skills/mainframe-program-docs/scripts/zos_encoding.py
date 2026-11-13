#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Decode z/OS bytes: EBCDIC code pages, fixed and RDW record formats, and DBCS shift codes.

Every mainframe skill in code-modernization-plugin bundles an identical copy of this module so
that each skill stays self-contained; a repository test keeps the copies in sync. Run it
directly to list the supported code pages, or to print an exported member or data set as UTF-8
text or as a hex dump. The script only reads files.

Single-byte text decodes exactly. In mixed single- and double-byte data, double-byte text
between shift-out (X'0E') and shift-in (X'0F') is kept as a ``<DBCS:hex>`` marker instead of
being garbled; convert such data with the platform's code page services when you need it.

Examples:
    uv run --script zos_encoding.py --list
    uv run --script zos_encoding.py PAYROLL.cbl --codepage 1047
    uv run --script zos_encoding.py CUST.DATA --recfm F --lrecl 120 --hex --max-records 5
"""

from __future__ import annotations

import argparse
import functools
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CODEPAGE = "cp037"
DEFAULT_LRECL = 80
SAMPLE_BYTES = 65536
EBCDIC_SPACE = 0x40
EBCDIC_NEWLINE = 0x15
SUBSTITUTE = "?"

# Single-byte code pages that Python's standard library provides.
STDLIB_CODEPAGES = frozenset({"cp037", "cp273", "cp424", "cp500", "cp875", "cp1026", "cp1140"})

# Other single-byte code pages, as overrides of a base page: "BBUUUU" means byte X'BB' decodes
# to U+UUUU. Generated from IBM's published mappings. X'15' stays NEL and X'25' stays LF, as in
# IBM's CDRA tables and Python's codecs (z/OS UNIX conversions often swap them).
_DERIVED: dict[str, tuple[str, str]] = {
    "cp1047": ("cp037", "5F005E AD005B B000AC BA00DD BB00A8 BD005D"),
    "cp277": (
        "cp037",
        (
            "47007D 4A0023 4F0021 5A00A4 5B00C5 5F005E 670024 6A00F8 7000A6 7B00C6 7C00D8 800040 "
            "9C007B 9E005B 9F005D A100FC B000A2 BA00AC BB007C C000E6 D000E5 DC007E"
        ),
    ),
    "cp278": (
        "cp037",
        (
            "43007B 47007D 4A00A7 4F0021 510060 5A00A4 5B00C5 5F005E 630023 670024 6A00F6 71005C "
            "7900E9 7B00C4 7C00D6 9F005D A100FC B000A2 B5005B BA00AC BB007C C000E4 CC00A6 D000E5 "
            "DC007E E000C9 EC0040"
        ),
    ),
    "cp280": (
        "cp037",
        (
            "44007B 48005C 4A00B0 4F0021 51005D 54007D 58007E 5A00E9 5F005E 6A00F2 7900F9 7B00A3 "
            "7C00A7 90005B A100EC B000A2 B10023 B50040 BA00AC BB007C C000E0 CD00A6 D000E8 DD0060 "
            "E000E7"
        ),
    ),
    "cp284": (
        "cp037",
        "4900A6 4A005B 5A005D 690023 6A00F1 7B00D1 A100A8 B000A2 BA005E BB0021 BD007E",
    ),
    "cp285": ("cp037", "4A0024 5B00A3 A100AF B000A2 B1005B BA005E BC007E"),
    "cp297": (
        "cp037",
        (
            "440040 48005C 4A00B0 4F0021 51007B 54007D 5A00A7 5F005E 6A00F9 7900B5 7B00A3 7C00E0 "
            "90005B A00060 A100A8 B000A2 B10023 B5005D BA00AC BB007C BD007E C000E9 D000E8 DD00A6 "
            "E000E7"
        ),
    ),
    "cp871": (
        "cp037",
        (
            "4A00DE 4F0021 5A00C6 5F00D6 7900F0 7C00D0 8C0060 8E007B 9C007D 9E005D A100F6 AC0040 "
            "AE005B B000A2 BA00AC BB007C BE005C C000FE CC007E D000E6 E000B4 EC005E"
        ),
    ),
    "cp870": (
        "cp037",
        (
            "440163 460103 47010D 490107 4A005B 4F0021 520119 54016F 57013E 58013A 5A005D 5F005E "
            "6402DD 660102 67010C 690106 6A007C 7002C7 720118 74016E 77013D 780139 8002D8 8A015B "
            "8B0148 8C0111 8E0159 8F015F 9A0142 9B0144 9C0161 9E02DB A00105 AA015A AB0147 AC0110 "
            "AE0158 AF015E B002D9 B10104 B2017C B30162 B4017B B6017E B7017A B8017D B90179 BA0141 "
            "BB0143 BC0160 CD0155 CF0151 DA011A DB0171 DD0165 DF011B EA010F ED0154 EF0150 FA010E "
            "FB0170 FD0164"
        ),
    ),
    "cp1025": (
        "cp037",
        (
            "420452 430453 440451 450454 460455 470456 480457 490458 4A005B 4F0021 510459 52045A "
            "53045B 54045C 55045E 56045F 57042A 582116 590402 5A005D 5F005E 620403 630401 640404 "
            "650405 660406 670407 680408 690409 6A007C 70040A 71040B 72040C 7300AD 74040E 75040F "
            "76044E 770430 780431 800446 8A0434 8B0435 8C0444 8D0433 8E0445 8F0438 900439 9A043A "
            "9B043B 9C043C 9D043D 9E043E 9F043F A0044F AA0440 AB0441 AC0442 AD0443 AE0436 AF0432 "
            "B0044C B1044B B20437 B30448 B4044D B50449 B60447 B7044A B8042E B90410 BA0411 BB0426 "
            "BC0414 BD0415 BE0424 BF0413 CA0425 CB0418 CC0419 CD041A CE041B CF041C DA041D DB041E "
            "DC041F DD042F DE0420 DF0421 E100A7 EA0422 EB0423 EC0416 ED0412 EE042C EF042B FA0417 "
            "FB0428 FC042D FD0429 FE0427"
        ),
    ),
    "cp290": (
        "cp037",
        (
            "41FF61 42FF62 43FF63 44FF64 45FF65 46FF66 47FF67 48FF68 49FF69 4A00A3 51FF6A 52FF6B "
            "53FF6C 54FF6D 55FF6E 56FF6F 57FFFD 58FF70 59FFFD 5B00A5 620061 630062 640063 650064 "
            "660065 670066 680067 690068 6AFFFD 70005B 710069 72006A 73006B 74006C 75006D 76006E "
            "77006F 780070 80005D 81FF71 82FF72 83FF73 84FF74 85FF75 86FF76 87FF77 88FF78 89FF79 "
            "8AFF7A 8B0071 8CFF7B 8DFF7C 8EFF7D 8FFF7E 90FF7F 91FF80 92FF81 93FF82 94FF83 95FF84 "
            "96FF85 97FF86 98FF87 99FF88 9AFF89 9B0072 9CFFFD 9DFF8A 9EFF8B 9FFF8C A0007E A1203E "
            "A2FF8D A3FF8E A4FF8F A5FF90 A6FF91 A7FF92 A8FF93 A9FF94 AAFF95 AB0073 ACFF96 ADFF97 "
            "AEFF98 AFFF99 B100A2 B2005C B30074 B40075 B50076 B60077 B70078 B80079 B9007A BAFF9A "
            "BBFF9B BCFF9C BDFF9D BEFF9E BFFF9F CAFFFD CBFFFD CCFFFD CDFFFD CEFFFD CFFFFD DAFFFD "
            "DBFFFD DCFFFD DDFFFD DEFFFD DFFFFD E00024 E1FFFD EAFFFD EBFFFD ECFFFD EDFFFD EEFFFD "
            "EFFFFD FAFFFD FBFFFD FCFFFD FDFFFD FEFFFD"
        ),
    ),
    "cp833": (
        "cp037",
        (
            "41FFFD 42FFA0 43FFA1 44FFA2 45FFA3 46FFA4 47FFA5 48FFA6 49FFA7 51FFFD 52FFA8 53FFA9 "
            "54FFAA 55FFAB 56FFAC 57FFAD 58FFAE 59FFAF 62FFB0 63FFB1 64FFB2 65FFB3 66FFB4 67FFB5 "
            "68FFB6 69FFB7 70005B 71FFFD 72FFB8 73FFB9 74FFBA 75FFBB 76FFBC 77FFBD 78FFBE 80005D "
            "8AFFC2 8BFFC3 8CFFC4 8DFFC5 8EFFC6 8FFFC7 90FFFD 9AFFCA 9BFFCB 9CFFCC 9DFFCD 9EFFCE "
            "9FFFCF A0203E AAFFD2 ABFFD3 ACFFD4 ADFFD5 AEFFD6 AFFFD7 B1FFFD B2005C B3FFFD B4FFFD "
            "B5FFFD B6FFFD B7FFFD B8FFFD B9FFFD BAFFDA BBFFDB BCFFDC BDFFFD BEFFFD BFFFFD CAFFFD "
            "CBFFFD CCFFFD CDFFFD CEFFFD CFFFFD DAFFFD DBFFFD DCFFFD DDFFFD DEFFFD DFFFFD E020A9 "
            "E1FFFD EAFFFD EBFFFD ECFFFD EDFFFD EEFFFD EFFFFD FAFFFD FBFFFD FCFFFD FDFFFD FEFFFD"
        ),
    ),
    # Euro variants replace the currency sign of their base page with U+20AC.
    "cp1141": ("cp273", "9F20AC"),
    "cp1142": ("cp277", "5A20AC"),
    "cp1143": ("cp278", "5A20AC"),
    "cp1144": ("cp280", "9F20AC"),
    "cp1145": ("cp284", "9F20AC"),
    "cp1146": ("cp285", "9F20AC"),
    "cp1147": ("cp297", "9F20AC"),
    "cp1148": ("cp500", "9F20AC"),
    "cp1149": ("cp871", "9F20AC"),
}

# Mixed single- and double-byte code pages, mapped to the page for their single-byte text.
MIXED_CODEPAGES = {"cp930": "cp290", "cp933": "cp833", "cp937": "cp037"}

CODEPAGES = tuple(
    sorted(STDLIB_CODEPAGES | set(_DERIVED) | set(MIXED_CODEPAGES), key=lambda name: int(name[2:]))
)
DESCRIPTIONS = {
    "cp037": "USA, Canada, Netherlands, Portugal, Brazil, Australia",
    "cp273": "Germany, Austria",
    "cp277": "Denmark, Norway",
    "cp278": "Finland, Sweden",
    "cp280": "Italy",
    "cp284": "Spain, Latin America",
    "cp285": "United Kingdom",
    "cp290": "Japanese Katakana (single-byte part of 930)",
    "cp297": "France",
    "cp424": "Hebrew",
    "cp500": "International Latin-1, Belgium, Switzerland",
    "cp833": "Korean (single-byte part of 933)",
    "cp870": "Latin-2, Central and Eastern Europe",
    "cp871": "Iceland",
    "cp875": "Greek",
    "cp930": "Japanese Katakana mixed; double-byte text kept as hex",
    "cp933": "Korean mixed; double-byte text kept as hex",
    "cp937": "Traditional Chinese mixed; double-byte text kept as hex",
    "cp1025": "Cyrillic",
    "cp1026": "Turkish",
    "cp1047": "Latin-1 open systems (z/OS UNIX, C, Java)",
}
DESCRIPTIONS.update(
    {
        f"cp{euro}": f"{DESCRIPTIONS[base]} with euro"
        for euro, base in (
            (1140, "cp037"),
            (1141, "cp273"),
            (1142, "cp277"),
            (1143, "cp278"),
            (1144, "cp280"),
            (1145, "cp284"),
            (1146, "cp285"),
            (1147, "cp297"),
            (1148, "cp500"),
            (1149, "cp871"),
        )
    }
)

# Double-byte characters are pairs of X'40'-X'FE' bytes between shift-out and shift-in.
DBCS_SPAN = re.compile(rb"\x0e((?:[\x40-\xfe][\x40-\xfe])*)\x0f")


def normalize_codepage(value: str | int) -> str:
    """Return the canonical name, such as ``cp1047``, for a code page or CCSID.

    Accepts forms like ``1047``, ``cp1047``, ``IBM-1047``, and ``CCSID 37``.
    """
    match = re.search(r"\d+", str(value))
    name = f"cp{int(match.group()):03d}" if match else ""
    if name not in CODEPAGES:
        supported = ", ".join(page[2:] for page in CODEPAGES)
        raise ValueError(f"unsupported code page {value!r}; supported: {supported}")
    return name


@functools.cache
def decoding_table(codepage: str) -> str:
    """Return the 256 characters that the bytes X'00' to X'FF' decode to."""
    name = normalize_codepage(codepage)
    if name in MIXED_CODEPAGES:
        return decoding_table(MIXED_CODEPAGES[name])
    if name in STDLIB_CODEPAGES:
        return "".join(bytes([byte]).decode(name, errors="replace") for byte in range(256))
    base, overrides = _DERIVED[name]
    table = list(decoding_table(base))
    for entry in overrides.split():
        raw = bytes.fromhex(entry)
        table[raw[0]] = chr(int.from_bytes(raw[1:], "big"))
    return "".join(table)


@functools.cache
def _decoder(codepage: str) -> dict[int, str]:
    return dict(enumerate(decoding_table(codepage)))


@functools.cache
def _encoder(codepage: str) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for byte, char in enumerate(decoding_table(codepage)):
        if char != "\ufffd":
            mapping.setdefault(char, byte)
    return mapping


def decode(data: bytes, codepage: str = DEFAULT_CODEPAGE, *, shift: bool | None = None) -> str:
    """Decode EBCDIC bytes to text.

    With ``shift`` (the default for mixed code pages), double-byte text between shift-out and
    shift-in is returned as a ``<DBCS:hex>`` marker.
    """
    name = normalize_codepage(codepage)
    mapping = _decoder(name)
    if shift is None:
        shift = name in MIXED_CODEPAGES
    if not shift:
        return data.decode("latin-1").translate(mapping)
    out: list[str] = []
    position = 0
    for match in DBCS_SPAN.finditer(data):
        out.append(data[position : match.start()].decode("latin-1").translate(mapping))
        out.append(f"<DBCS:{match.group(1).hex().upper()}>")
        position = match.end()
    out.append(data[position:].decode("latin-1").translate(mapping))
    return "".join(out)


def encode(text: str, codepage: str = DEFAULT_CODEPAGE, *, errors: str = "strict") -> bytes:
    """Encode text in a single-byte EBCDIC code page.

    ``errors="replace"`` substitutes ``?`` for characters the code page cannot represent;
    the default raises ``ValueError``.
    """
    name = normalize_codepage(codepage)
    mapping = _encoder(name)
    out = bytearray()
    for index, char in enumerate(text):
        byte = mapping.get(char)
        if byte is None:
            if errors != "replace":
                raise ValueError(f"{name} cannot encode {char!r} at position {index}")
            byte = mapping.get(SUBSTITUTE, 0x6F)
        out.append(byte)
    return bytes(out)


def dbcs_spans(data: bytes) -> int:
    """Count shift-out ... shift-in spans, which mark double-byte text in mixed data."""
    return sum(1 for _ in DBCS_SPAN.finditer(data))


def looks_like_ebcdic(sample: bytes) -> bool:
    """Guess whether bytes are EBCDIC text: EBCDIC blanks outnumber ASCII blanks."""
    return bool(sample) and sample.count(EBCDIC_SPACE) > max(sample.count(0x20), len(sample) // 20)


@dataclass
class RecordSplit:
    """Records split from a byte stream, and the record format that was applied."""

    records: list[bytes]
    recfm: str  # F (fixed), V (RDW-prefixed), or NL (EBCDIC new-line delimited)
    lrecl: int | None = None
    warnings: list[str] = field(default_factory=list)


def rdw_records(data: bytes) -> list[bytes] | None:
    """Split RDW-prefixed variable records, joining spanned segments.

    Returns None unless the whole buffer is a valid chain of record descriptor words, which
    is how variable-length data sets arrive when transferred in binary with their RDWs.
    Block descriptor words are not supported.
    """
    records: list[bytes] = []
    pending: bytearray | None = None
    position = 0
    while position < len(data):
        if position + 4 > len(data):
            return None
        length = int.from_bytes(data[position : position + 2], "big")
        segment, reserved = data[position + 2], data[position + 3]
        if length < 4 or reserved != 0 or segment > 3 or position + length > len(data):
            return None
        body = data[position + 4 : position + length]
        if segment == 0 and pending is None:
            records.append(body)
        elif segment == 1 and pending is None:
            pending = bytearray(body)
        elif segment in {2, 3} and pending is not None:
            pending += body
            if segment == 2:
                records.append(bytes(pending))
                pending = None
        else:
            return None
        position += length
    return None if pending is not None else records


def split_records(data: bytes, *, recfm: str = "auto", lrecl: int | None = None) -> RecordSplit:
    """Split a byte stream into records.

    ``recfm`` is ``F`` (fixed, with ``lrecl``), ``V`` (RDW-prefixed), ``NL`` (EBCDIC new-line
    delimited, as in z/OS UNIX files), or ``auto``, which tries RDWs, then ``lrecl``, then
    new lines, then 80-byte records.
    """
    kind = recfm.upper().rstrip("BS") or "F"
    if kind == "V":
        records = rdw_records(data)
        if records is None:
            raise ValueError("data is not a valid chain of RDW-prefixed records")
        return RecordSplit(records, "V")
    if kind == "NL":
        return RecordSplit(data.split(bytes([EBCDIC_NEWLINE])), "NL")
    if kind == "AUTO":
        records = rdw_records(data) if data else None
        if records is not None:
            return RecordSplit(records, "V")
        if lrecl is None and EBCDIC_NEWLINE in data[:SAMPLE_BYTES] and len(data) % 80:
            return RecordSplit(data.split(bytes([EBCDIC_NEWLINE])), "NL")
    elif kind != "F":
        raise ValueError(f"unsupported record format {recfm!r}; use F, V, NL, or auto")
    size = lrecl or DEFAULT_LRECL
    if size <= 0:
        raise ValueError("lrecl must be positive")
    split = RecordSplit([data[index : index + size] for index in range(0, len(data), size)], "F")
    split.lrecl = size
    if len(data) % size:
        split.warnings.append(
            f"{len(data)} bytes is not a multiple of LRECL {size}; the last record is short"
        )
    return split


@dataclass
class DecodedMember:
    """Text decoded from an exported member, with how it was decoded."""

    text: str
    encoding: str  # "text", or "ebcdic-<codepage>" with "-v" or "-nl" for those formats
    dbcs_spans: int = 0
    warnings: list[str] = field(default_factory=list)


def decode_member(
    data: bytes,
    *,
    codepage: str = DEFAULT_CODEPAGE,
    recfm: str = "auto",
    lrecl: int | None = None,
) -> DecodedMember | None:
    """Decode an exported source member or text data set; None means binary content.

    Text with ASCII line ends is decoded as UTF-8. EBCDIC text is split into records,
    decoded with ``codepage``, and stripped of trailing blanks.
    """
    sample = data[:SAMPLE_BYTES]
    explicit = recfm.lower() != "auto" or lrecl is not None
    if explicit or (b"\n" not in sample and looks_like_ebcdic(sample)):
        split = split_records(data, recfm=recfm, lrecl=lrecl)
        name = normalize_codepage(codepage)
        lines = [decode(record, name, shift=True).rstrip() for record in split.records]
        suffix = {"V": "-v", "NL": "-nl"}.get(split.recfm, "")
        spans = sum(dbcs_spans(record) for record in split.records)
        return DecodedMember("\n".join(lines), f"ebcdic-{name}{suffix}", spans, split.warnings)
    if b"\x00" in sample:
        return None
    return DecodedMember(data.decode("utf-8", errors="replace"), "text")


def hex_dump(record: bytes, codepage: str = DEFAULT_CODEPAGE, width: int = 16) -> list[str]:
    """Return offset, hex, and decoded-character lines for one record."""
    rows = []
    for start in range(0, len(record), width):
        chunk = record[start : start + width]
        text = "".join(
            char if char.isprintable() else "." for char in decode(chunk, codepage, shift=False)
        )
        rows.append(f"{start:06X}  {chunk.hex(' ').upper():<{width * 3}} {text}")
    return rows


def main(argv: list[str] | None = None) -> int:
    """Print the supported code pages, or decode one file to standard output."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("path", nargs="?", type=Path, help="Exported member or data set.")
    parser.add_argument("--list", action="store_true", help="List the supported code pages.")
    parser.add_argument("--codepage", default="037", help="EBCDIC code page (default: 037).")
    parser.add_argument(
        "--recfm", default="auto", help="Record format: auto, F, V, or NL (default: auto)."
    )
    parser.add_argument("--lrecl", type=int, help="Record length for fixed records.")
    parser.add_argument("--hex", action="store_true", help="Print a hex dump of each record.")
    parser.add_argument(
        "--max-records", type=int, default=0, help="Stop after this many records (0: all)."
    )
    args = parser.parse_args(argv)

    if args.list:
        for name in CODEPAGES:
            print(f"{name[2:]:>5}  {DESCRIPTIONS[name]}")
        return 0
    if args.path is None:
        parser.error("a file is required unless --list is given")
    try:
        data = args.path.read_bytes()
        codepage = normalize_codepage(args.codepage)
        if args.hex:
            split = split_records(data, recfm=args.recfm, lrecl=args.lrecl)
            records = split.records[: args.max_records or None]
            for number, record in enumerate(records, start=1):
                print(f"record {number} ({len(record)} bytes, RECFM {split.recfm})")
                print("\n".join(hex_dump(record, codepage)))
            warnings = split.warnings
        else:
            decoded = decode_member(data, codepage=codepage, recfm=args.recfm, lrecl=args.lrecl)
            if decoded is None:
                print("error: binary content; use --hex with --recfm and --lrecl", file=sys.stderr)
                return 1
            lines = decoded.text.splitlines()
            print("\n".join(lines[: args.max_records or None]))
            warnings = decoded.warnings
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
