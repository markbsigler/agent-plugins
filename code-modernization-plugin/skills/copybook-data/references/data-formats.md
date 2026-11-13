# How the record tools read mainframe data

The decoders follow IBM z/OS storage formats. Use this page to interpret `record_decode.py` values and `issues`, and `record_compare.py` differences.

## Record formats

| RECFM | Downloaded form | Option |
| --- | --- | --- |
| F, FB | Records of exactly LRECL bytes, no separators | Default when the layout has one length; or `--recfm F --lrecl n` |
| V, VB | Each record starts with a 4-byte RDW: a 2-byte length that includes the RDW, then 2 zero bytes | `--recfm V`; found automatically when every RDW is valid |
| VS, VBS | Spanned segments, with the third RDW byte marking first, middle, and last segments | `--recfm V` joins the segments |
| z/OS UNIX text | EBCDIC lines ended by NL (X'15') | `--recfm NL` |

Block descriptor words are not supported; transfer variable data sets with RDWs only. With `dfsort-symbols --rdw`, positions include the RDW, as DFSORT expects for variable-length input.

## Numeric formats

| Category | Storage | Valid signs | Issues reported |
| --- | --- | --- | --- |
| `zoned-decimal` | One digit per byte, zone F; the sign is the zone of the last (or, with SIGN LEADING, the first) byte, or a separate `+` (X'4E') or `-` (X'60') byte | C, A, E, F positive; D, B negative | invalid digit, invalid sign zone, a zone other than F in a digit position, spaces, low-values, high-values |
| `packed-decimal` | Two digits per byte; the last half-byte is the sign | C, A, E, F positive; D, B negative | invalid digit or sign, a negative sign in an unsigned field, spaces, low-values, high-values |
| `binary` | Big-endian two's complement, or unsigned when the PICTURE has no S; COMP-5 and TRUNC(BIN) can exceed the PICTURE | n/a | none |
| `float` | IBM hexadecimal floating point (COMP-1, COMP-2, HLASM E and D) | sign bit | none; COMP-2 has more precision than a Python float, so compare bytes, not printed values |
| `national-decimal` | UTF-16 digits | separate sign character | none |

Scale comes from the PICTURE: `V` positions are decimals and `P` positions scale by powers of ten. Values print as exact decimal strings.

## Text formats

- Alphanumeric fields decode with `--codepage`. Trailing blanks are trimmed in decoded values, but comparisons use the raw bytes.
- National fields (PIC N, PL/I WIDECHAR, HLASM CU) are UTF-16. DBCS fields (PIC G, DISPLAY-1, GRAPHIC) show as `<DBCS:hex>` unless they are all double-byte blanks.
- Mixed data with shift-out (X'0E') and shift-in (X'0F') keeps the double-byte part as a `<DBCS:hex>` marker.
- `zos_encoding.py --list` prints the supported code pages. National code pages move `@`, `#`, `$`, `[`, `]`, `{`, `}`, `|`, and the currency sign, so decode with the code page the data was written in.

## Format-only differences

`record_compare.py` reports a format-only difference when two fields decode to the same number but their bytes differ. Common causes:

- A packed or zoned positive sign of C versus F. This comes from compiler options such as NUMPROC, from MOVE semantics, or from a different producer.
- Leading zeros versus blanks after an edited move into a numeric field.
- Different zone nibbles in digit positions.

Downstream byte comparisons, sorts on packed fields, hash totals, and file transfers can depend on these bytes. Decide whether consumers depend on them before you accept the difference with `--numeric-equal`.

## Masking guarantees

- Lengths, offsets, record counts, and record formats never change. Variable records keep their RDW lengths.
- Numbers keep their sign and stay within the digit count of their PICTURE. Packed and zoned values keep their original positive sign nibble (C or F). Zero stays zero under `hash`.
- Text keeps blanks, punctuation, and the positions of letters and digits.
- The `hash` rule is a keyed permutation: balanced Feistel rounds with HMAC-SHA256 as the round function, applied to a number's digits (keeping the leading digit nonzero, so the digit count stays the same) or to a text's letters and its digits (keeping case, spaces, and punctuation in place). The same value and secret always give the same result, and two different values never give the same result, so keys stay unique; for text this holds among values with the same pattern of letters, digits, and other characters. Like any permutation it can leave a few values unchanged, most often in small domains such as one-digit numbers, which have only nine possible values; use `zero` or `fixed` for short codes that must change. Without `--secret-env`, a random secret is used, and results differ on every run.
- Masking keeps keys unique but not in order. Re-sort files that must be in key sequence (KSDS loads, match-merge and `JOINKEYS` inputs) after masking.
