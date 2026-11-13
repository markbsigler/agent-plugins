# Equivalence testing on the mainframe

The goal is evidence. For **Refactor**, prove zero external behavioral drift. For **Rearchitect**, prove parity except for differences that are explicitly listed and approved in the ADR.

## The observable surface

Define what the tests observe before writing them:

- Output data sets, compared byte for byte or field by field from the copybook layout.
- Reports, compared after normalizing volatile fields.
- End state of Db2 tables, IMS databases, and VSAM files.
- MQ messages produced, including headers that consumers read.
- CICS and IMS responses: COMMAREAs, containers, output messages, and 3270 screens.
- Return codes, abend codes, and the console or SYSOUT messages that operators or automation react to.
- Files sent to partners and other platforms.
- Ordering, where consumers depend on it.

## Batch golden master

1. **Pick inputs:** masked production extracts plus targeted edge cases: empty files, maximum volumes, records with invalid numeric data that abend today, boundary dates (month-end, year-end, leap day, daylight-saving changes, two-digit-year window edges), and every record type in multi-record files.
2. **Freeze the environment:** virtual or injected dates, control cards and `PARM` values, reference data, Db2 state (unload before, load to reset), GDG generations, and collating sequence.
3. **Run the baseline** and capture outputs, return codes, SYSOUT, and database end state.
4. **Run the candidate** with identical inputs and compare:
   - Compare field by field with the `copybook-data` skill's `record_compare.py`, which decodes both files with the layout, matches records by key or position, and names the field that differs.
   - Compare packed fields by value and, for Refactor, also by bytes; a change of sign nibble (`F` to `C`) is a difference until it is proven harmless and approved. `record_compare.py` reports these differences in format only separately.
   - Check record counts, trailer control totals, and hash totals.
   - Check sort order of every output that is consumed in order.
5. **Explain every difference.** Zero unexplained differences is the only passing result.

Comparison tooling: mainframe compare utilities (for example the ISPF SuperC compare, run by this skill's [../assets/compare-outputs.jcl](../assets/compare-outputs.jcl), or file-management products that compare with copybook layouts), DFSORT `JOINKEYS` jobs, or an off-platform comparison of binary-transferred files decoded with the layout (`record_compare.py`).

## Online golden master

- **Program level:** drive the business-logic program with recorded COMMAREAs or containers and stub `EXEC CICS`, `EXEC SQL`, and DL/I calls with a COBOL unit-testing framework (see [tooling.md](tooling.md)).
- **Transaction level:** replay recorded 3270 sessions or drive screens with an integration test framework, normalizing timestamps, terminal IDs, and user IDs.
- **IMS:** send recorded input messages through IMS Connect or OTMA and capture output messages and database state.
- **APIs:** consumer and provider contract tests against the legacy adapter and the new implementation.

## COBOL unit and regression testing

- Unit frameworks for COBOL can isolate a program or paragraph, stub subsystem calls and called programs, and record and replay test data.
- Measure code coverage on the mainframe with the debugger or coverage tooling available, and aim characterization at the paths the change touches.
- Keep tests in the same repository and pipeline as the code, and run them on every build.

## Test data management

- Mask or subset production data for privacy and regulatory rules (for example GDPR, PCI DSS, HIPAA). The `copybook-data` skill's `record_mask.py` masks by field from the layout.
- Keep masked data valid for the layout: packed and zoned fields must stay valid, check digits must still check, keys must stay unique (and files must be re-sorted where key order matters), and the same value must mask identically across files, Db2, IMS, and VSAM so joins and match-merges still work.
- Synthesize data for edge cases that production lacks.

## Parallel run and reconciliation

Used for large Refactors and for Rearchitect Stages 3 and 4:

- Run legacy and new side by side on the same inputs for full business cycles, including month-end and, where relevant, quarter-end and year-end.
- Automate reconciliation reports: counts, control totals, financial balances, and field-level differences.
- Business owners sign off on balancing; record the sign-off with the evidence.

## Nonfunctional baselines on z/OS

| Metric | Source |
| --- | --- |
| CPU time per job, step, and transaction | SMF type 30 (batch), type 110 (CICS), type 101 (Db2 accounting) |
| MSU and rolling four-hour average impact | Capacity and software-pricing reports |
| Elapsed time against the batch window | Scheduler history, SMF type 30 |
| I/O (EXCP counts), Db2 getpages, locks, and timeouts | SMF and Db2 monitors |
| CICS response time percentiles | CICS monitoring (SMF type 110) |
| Memory (region size) and storage abends | Job logs and SMF |

Measure on comparable LPARs, at comparable times, over several runs, and record the noise. Profile hotspots with the shop's performance analysis tooling before and after.

## Evidence package for a gate

```markdown
| Evidence | Baseline | Candidate | Result |
| --- | --- | --- | --- |
| Batch outputs (N data sets, field-level compare) | <run id> | <run id> | 0 differences |
| Reports (normalized) | | | |
| Db2/IMS/VSAM end state | | | |
| Return codes and abends (including invalid-data cases) | | | |
| Online responses (COMMAREA, screens, messages) | | | |
| Cycle coverage (month-end, year-end, leap day) | | | |
| CPU, elapsed, I/O | | | delta and noise band |
| Approved differences (Rearchitect only, cite ADR) | | | |
```
