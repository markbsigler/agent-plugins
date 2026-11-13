#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Mask personal and sensitive fields in mainframe test data, keeping the data valid.

Rewrites chosen fields of a binary data set using its record layout. Masking is
format-preserving: letters stay letters and digits stay digits, field lengths never change,
zoned and packed decimals keep their sign nibbles and digit counts, binary values stay within
their PICTURE, and card numbers keep a valid Luhn check digit. The ``hash`` rule applies a
keyed permutation (Feistel rounds of HMAC-SHA256): it is deterministic for a given secret, so
the same customer number masks to the same value in every file and keys still join, and it
never maps two different numbers, or two different texts of the same shape, to the same
value, so keys stay unique. ``--suggest`` lists likely personal-data fields by name without
masking anything.

The script reads the layout and data set and writes the masked data only to ``--output`` (or
standard output). Pass the secret through an environment variable named by ``--secret-env``,
never on the command line.

Rules: keep, hash, luhn, blank, zero, fixed:TEXT.

Examples:
    uv run --script record_mask.py CUSTREC.cpy CUST.DATA --suggest
    MASK_SECRET=... uv run --script record_mask.py CUSTREC.cpy CUST.DATA --secret-env MASK_SECRET
        --rule CUST-NAME=hash --rule CARD-NO=luhn --rule CUST-PIN=blank --output CUST.MASKED
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import sys
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import record_decode
import zos_encoding

if TYPE_CHECKING:
    from collections.abc import Sequence

    from copybook_layout import Item, Layout
    from record_decode import FieldValue

RULES = ("keep", "hash", "luhn", "blank", "zero", "fixed")
FEISTEL_ROUNDS = 10
NUMERIC = frozenset({"zoned-decimal", "packed-decimal", "binary", "national-decimal"})
TEXT = frozenset({"alphanumeric", "alphabetic", "alphanumeric-edited", "numeric-edited"})
# (segment pattern, rule, reason): matched against the hyphen- or underscore-separated parts of
# a field name. Suggestions are a starting point for review, not a guarantee.
SUGGESTIONS = (
    (r"CARD|PAN|CCN|CRDT?|CREDITCARD", "luhn", "payment card number"),
    (r"SSN|SOCSEC|SOC|TAXID|TIN|NINO|NATID|PASSPORT|LICENSE|LICENCE", "hash", "government ID"),
    (r"NAME|FNAME|LNAME|MNAME|SURNAME|FORENAME|GIVEN", "hash", "personal name"),
    (r"ADDR\d*|ADDRESS\d*|STREET|STR|CITY|TOWN|ZIP|ZIPCODE|POSTCODE|POSTAL", "hash", "address"),
    (r"PHONE|TEL|TELNO|MOBILE|CELL|FAX", "hash", "phone number"),
    (r"EMAIL|MAIL", "hash", "email address"),
    (r"ACCT|ACCOUNT|ACCTNO|IBAN|BIC|ROUTING|SORTCODE", "hash", "account identifier"),
    (r"DOB|BIRTH|BIRTHDATE|BDATE", "review", "date of birth; needs a date-aware rule"),
    (r"SALARY|INCOME|WAGE|WAGES", "review", "sensitive amount; choose zero or keep"),
    (r"PIN|PASSWORD|PASSWD|PWD|SECRET", "blank", "secret"),
)


@dataclass(frozen=True)
class Rule:
    """A masking rule for one field name."""

    name: str
    kind: str
    text: str = ""


def parse_rules(entries: Sequence[str]) -> list[Rule]:
    """Parse ``FIELD=RULE`` arguments; ``fixed:TEXT`` carries replacement text."""
    rules = []
    for entry in entries:
        name, separator, rule = entry.partition("=")
        kind, _, text = rule.partition(":")
        if not separator or kind.lower() not in RULES or not name.strip():
            raise ValueError(
                f"--rule must be FIELD=RULE with RULE in {', '.join(RULES)}: {entry!r}"
            )
        rules.append(Rule(name.strip().upper(), kind.lower(), text))
    return rules


def suggest(layout: Layout) -> list[dict[str, str]]:
    """Return likely personal-data fields with a suggested rule and the reason."""
    found = []
    seen: set[str] = set()
    for record in layout.records:
        for item in _elementary(record):
            parts = re.split(r"[-_]", item.name)
            for pattern, rule, reason in SUGGESTIONS:
                if item.name not in seen and any(re.fullmatch(pattern, part) for part in parts):
                    seen.add(item.name)
                    found.append(
                        {"record": record.name, "field": item.name, "rule": rule, "reason": reason}
                    )
    return found


def _elementary(item: Item) -> list[Item]:
    if not item.children:
        return [item]
    return [leaf for child in item.children for leaf in _elementary(child)]


class Masker:
    """Deterministic, format-preserving replacement values keyed by a secret."""

    def __init__(self, secret: bytes, codepage: str) -> None:
        self.secret = secret
        self.codepage = codepage

    def _stream(self, value: str, count: int) -> list[int]:
        out: list[int] = []
        block = 0
        while len(out) < count:
            message = f"{block}:{value}".encode()
            out.extend(hmac.new(self.secret, message, hashlib.sha256).digest())
            block += 1
        return out[:count]

    def permute(self, value: int, width: int, radix: int, domain: str) -> int:
        """Apply a keyed permutation to the ``width``-digit numbers in base ``radix``.

        Uses balanced Feistel rounds with HMAC-SHA256 as the round function, so every input
        has exactly one output. ``domain`` separates the permutations used for different
        kinds of data.
        """
        if width == 1:
            order = sorted(range(radix), key=lambda symbol: self._stream(f"{domain}:{symbol}", 8))
            return order[value]
        sizes = (width // 2, width - width // 2)
        left, right = divmod(value, radix ** sizes[1])
        for round_number in range(FEISTEL_ROUNDS):
            modulus = radix ** sizes[round_number % 2]
            # Draw 128 bits more than the modulus needs, so the reduced key stays uniform.
            count = modulus.bit_length() // 8 + 17
            key = int.from_bytes(
                bytes(self._stream(f"{domain}:{width}:{round_number}:{right}", count))
            )
            left, right = right, (left + key) % modulus
        return left * radix ** sizes[1] + right

    def number(self, value: int) -> int:
        """Map a positive integer to another with the same number of digits, one to one.

        Cycle walking keeps the leading digit nonzero, so the magnitude stays the same.
        """
        width = len(str(value))
        lowest = 10 ** (width - 1) if width > 1 else 1
        result = value
        while True:
            result = self.permute(result, width, 10, "number")
            if result >= lowest:
                return result

    def text(self, value: str) -> str:
        """Replace letters with letters and digits with digits, one to one.

        The ASCII letters and the digits are each permuted as a whole, keeping case, spaces,
        and punctuation in place. Other letters (for example national characters) are
        replaced with letters derived from the value.
        """
        chars = list(value)
        for alphabet, radix, domain in (
            (string.ascii_uppercase, 26, "letters"),
            (string.digits, 10, "digits"),
        ):
            positions = [i for i, char in enumerate(value) if char.upper() in alphabet]
            if not positions:
                continue
            number = 0
            for index in positions:
                number = number * radix + alphabet.index(value[index].upper())
            number = self.permute(number, len(positions), radix, domain)
            for index in reversed(positions):
                number, symbol = divmod(number, radix)
                chars[index] = (
                    alphabet[symbol] if not value[index].islower() else (alphabet[symbol].lower())
                )
        stream = self._stream(value, len(value))
        for index, char in enumerate(value):
            if char.isalpha() and char.upper() not in string.ascii_uppercase:
                letters = string.ascii_uppercase if char.isupper() else string.ascii_lowercase
                chars[index] = letters[stream[index] % 26]
        return "".join(chars)


def luhn_fix(digits: str) -> str:
    """Replace the last digit so the digit string passes the Luhn check."""
    body = digits[:-1]
    total = 0
    for index, char in enumerate(reversed(body)):
        number = int(char) * (2 if index % 2 == 0 else 1)
        total += number - 9 if number > 9 else number
    return body + str((10 - total % 10) % 10)


def _with_luhn(text: str) -> str:
    positions = [index for index, char in enumerate(text) if char.isdigit()]
    if len(positions) < 2:
        return text
    fixed = luhn_fix("".join(text[index] for index in positions))
    chars = list(text)
    for index, char in zip(positions, fixed, strict=True):
        chars[index] = char
    return "".join(chars)


def _luhn_text(text: str, masker: Masker) -> str:
    """Mask everything before the check digit, then recompute the check digit."""
    positions = [index for index, char in enumerate(text) if char.isdigit()]
    if len(positions) < 2:
        return masker.text(text)
    check = positions[-1]
    return _with_luhn(masker.text(text[:check]) + text[check:])


def encode_number(item: Item, original: bytes, number: int) -> bytes:
    """Encode an integer (scale already applied) in the field's format, keeping its signs."""
    size = item.size
    if item.category == "binary":
        return number.to_bytes(size, "big", signed=item.signed)
    digits = f"{abs(number):0{item.digits or 1}d}"[-(item.digits or 1) :]
    if item.category == "packed-decimal":
        sign = original[-1] & 0x0F
        if number < 0:
            sign = 0xD
        elif sign in {0xB, 0xD}:
            sign = 0xC
        nibbles = digits.rjust(size * 2 - 1, "0") + f"{sign:X}"
        return bytes.fromhex(nibbles)
    if item.category == "national-decimal":
        return digits.rjust(size // 2, "0").encode("utf-16-be")
    body = bytearray(0xF0 | int(char) for char in digits)
    if item.signed and item.separate:
        sign = 0x60 if number < 0 else 0x4E
        return bytes([sign, *body]) if item.leading else bytes([*body, sign])
    if item.signed:
        index = 0 if item.leading else len(body) - 1
        zone = original[index] >> 4 if original else 0xC
        if number < 0:
            zone = 0xD
        elif zone in {0xB, 0xD}:
            zone = 0xC
        body[index] = (zone << 4) | (body[index] & 0x0F)
    return bytes(body)


def mask_field(value: FieldValue, rule: Rule, masker: Masker) -> tuple[bytes, str | None]:
    """Return replacement bytes for one field, or the original bytes and a reason."""
    item, raw = value.item, value.raw
    if rule.kind == "keep":
        return raw, None
    if item.category in NUMERIC:
        if value.issue or value.value is None:
            return raw, f"invalid numeric data ({value.issue}); left unchanged"
        scale = item.scale or 0
        number = int(Decimal(value.value).scaleb(scale))
        if rule.kind in {"zero", "blank"}:
            return encode_number(item, raw, 0), None
        if rule.kind == "fixed":
            try:
                fixed = Decimal(rule.text or "0").scaleb(scale)
            except ArithmeticError:
                return raw, f"fixed value {rule.text!r} is not a number; left unchanged"
            return encode_number(item, raw, int(fixed)), None
        if number == 0:
            return raw, None
        magnitude = abs(number)
        if rule.kind == "luhn" and magnitude >= 10:
            masked = int(luhn_fix(f"{masker.number(magnitude // 10)}0"))
        else:
            masked = masker.number(magnitude)
            # Binary fields can hold more digits than their PICTURE (TRUNC(BIN)); walk the
            # permutation's cycle until the value fits the field again, keeping it one to one.
            while item.category == "binary" and masked >= 1 << (8 * item.size - item.signed):
                masked = masker.number(masked)
        return encode_number(item, raw, masked * (-1 if number < 0 else 1)), None
    if item.category in TEXT:
        text = zos_encoding.decode(raw, masker.codepage)
        if rule.kind in {"blank", "zero"}:
            new_text = ("0" if rule.kind == "zero" else " ") * len(text)
        elif rule.kind == "fixed":
            new_text = rule.text[: len(text)].ljust(len(text))
        else:
            core = text.rstrip(" ")
            new_text = _luhn_text(core, masker) if rule.kind == "luhn" else masker.text(core)
            new_text = new_text.ljust(len(text))
        return zos_encoding.encode(new_text, masker.codepage, errors="replace"), None
    if item.category in {"national", "national-edited"}:
        text = raw.decode("utf-16-be", errors="replace")
        blank = rule.kind in {"blank", "zero", "fixed"}
        new_text = " " * len(text) if blank else masker.text(text.rstrip(" ")).ljust(len(text))
        return new_text.encode("utf-16-be"), None
    if rule.kind == "blank" and item.category == "dbcs":
        return b"\x40" * len(raw), None
    return raw, f"{item.category} fields support only keep or blank; left unchanged"


def mask_records(
    records: Sequence[bytes],
    layout: Layout,
    rules: Sequence[Rule],
    masker: Masker,
    selector: record_decode.Selector | None = None,
) -> tuple[list[bytes], dict[str, Any]]:
    """Mask every record; return the new records and a summary of what changed."""
    by_name = {rule.name: rule for rule in rules}
    masked: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    out: list[bytes] = []
    for raw in records:
        record = record_decode.choose_record(raw, layout, selector, masker.codepage)
        buffer = bytearray(raw)
        if record is not None:
            for value in record_decode.decode_record(record, raw, masker.codepage):
                rule = by_name.get(value.item.name)
                if rule is None or rule.kind == "keep" or len(value.raw) < value.item.size:
                    continue
                new, reason = mask_field(value, rule, masker)
                if reason:
                    skipped[f"{value.item.name}: {reason}"] += 1
                elif new != value.raw:
                    masked[value.item.name] += 1
                buffer[value.offset : value.offset + len(new)] = new
        out.append(bytes(buffer))
    unknown = sorted(set(by_name) - {i.name for r in layout.records for i in _elementary(r)})
    summary = {
        "records": len(records),
        "masked": dict(masked),
        "skipped": dict(skipped),
        "unknown_fields": unknown,
    }
    return out, summary


def _write(records: list[bytes], recfm: str, destination: Path | None) -> None:
    if recfm == "V":
        data = b"".join((len(r) + 4).to_bytes(2, "big") + b"\x00\x00" + r for r in records)
    else:
        data = (b"\x15" if recfm == "NL" else b"").join(records)
    if destination is None:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    else:
        destination.write_bytes(data)


def _secret(name: str | None) -> bytes:
    if name is None:
        print(
            "warning: no --secret-env, so hashed values differ on every run and keys will "
            "not match across files",
            file=sys.stderr,
        )
        return secrets.token_bytes(32)
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"environment variable {name} is not set")
    return value.encode()


def _check_output(output: Path | None, data: Path) -> None:
    if output is not None and output.resolve() == data.resolve():
        raise ValueError("--output must not overwrite the input data set")


def main(argv: list[str] | None = None) -> int:
    """Suggest masking rules, or mask a data set with the given rules."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("layout", help="Copybook, PL/I structure, or DSECT source.")
    parser.add_argument("data", type=Path, help="Data set downloaded in binary.")
    record_decode.add_data_arguments(parser)
    parser.add_argument("--rule", action="append", default=[], metavar="FIELD=RULE")
    parser.add_argument("--suggest", action="store_true", help="List likely personal data.")
    parser.add_argument(
        "--secret-env", metavar="NAME", help="Environment variable that holds the secret."
    )
    parser.add_argument("--output", type=Path, help="Write masked data here (default: stdout).")
    args = parser.parse_args(argv)
    try:
        layout, selector, codepage = record_decode.open_inputs(args)
        if args.suggest:
            print(json.dumps(suggest(layout), indent=2))
            return 0
        rules = parse_rules(args.rule or ["="])
        _check_output(args.output, args.data)
        key = _secret(args.secret_env)
        split = record_decode.read_records(args.data, layout, recfm=args.recfm, lrecl=args.lrecl)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    records, summary = mask_records(split.records, layout, rules, Masker(key, codepage), selector)
    _write(records, split.recfm, args.output)
    print(json.dumps(summary), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
