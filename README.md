# sales-report

A CLI tool that reads multiple sales CSV files and produces a summary report
(CSV / Markdown) broken down by store, product and date.

[![CI](https://github.com/yuten0901/sales-report/actions/workflows/ci.yml/badge.svg)](https://github.com/yuten0901/sales-report/actions/workflows/ci.yml)
[![Security](https://github.com/yuten0901/sales-report/actions/workflows/security.yml/badge.svg)](https://github.com/yuten0901/sales-report/actions/workflows/security.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)
![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

*日本語版: [README.ja.md](README.ja.md)*

> **On that coverage badge.** 100% coverage means every line and branch is executed
> by a test. It is not evidence of quality. This project reached 100% coverage and
> then had a long list of real defects found in review, before and after release
> ([docs/test-report.md](docs/test-report.md), [docs/defects.md](docs/defects.md)).
> The number is a local measurement from 2026-07-27 and is updated by hand; the
> current measured value is in the CI artifact `test-evidence-*` (`coverage.xml`).
>
> Mutation testing (mutmut) is **experimental** and manually triggered
> ([.github/workflows/mutation.yml](.github/workflows/mutation.yml)); it does not yet
> run to completion in this environment ([docs/known-issues.md](docs/known-issues.md)).
> Until it does, the discriminating power of the test suite is backed by **manual
> mutation as a complementary check** — scope, method and limits are in
> [docs/test-report.md](docs/test-report.md) §3.

---

## What this is

It aggregates sales CSVs exported from Excel or similar (multiple files, multiple
stores) and emits a summary by store, product and date, plus an error report listing
every skipped row with the reason it was skipped.

This is a portfolio project. The goal is not the feature set — it is to show
**how the quality was actually assured**, as something you can read rather than
something I claim.

```
$ sales-report --input data/sample/sales.csv --output out/summary.md
サマリレポートを出力しました: out\summary.md
```

```markdown
# 売上サマリレポート

## 店舗別

| 店舗 | 数量 | 金額 |
|---|---|---|
| 新宿店 | 4 | 104740.00 |
| 池袋店 | 11 | 109600.00 |
| 渋谷店 | 9 | 239100.00 |

## 合計

- 総数量: 24
- 総金額: 453440.00
```

---

## Approach to quality

1. **A written test design document** ([docs/test-design.md](docs/test-design.md))
   derives the test conditions from equivalence partitioning, boundary value analysis
   and decision tables.
2. Those conditions are tracked by ID, so boundaries and error paths are covered
   deliberately rather than incidentally (the document maps each condition ID to the
   test function that covers it).
3. **Property-based testing** (Hypothesis) verifies properties against large volumes
   of generated input, rather than a handful of hand-picked cases.
4. **Mutation thinking** is used to ask whether the tests can actually detect a bug.
   Automated mutmut is experimental and does not yet complete here, so this is
   currently covered by manual mutation as a complementary check
   ([docs/test-report.md](docs/test-report.md), [docs/known-issues.md](docs/known-issues.md)).
5. **CI** (GitHub Actions) runs an OS × Python version matrix, coverage and security
   scanning, and stores the results as artifacts.
6. **Test evidence is produced by CI, not by hand** — JUnit XML and the coverage HTML
   report are saved as artifacts automatically, replacing manual evidence collection.

---

## Install and usage

```bash
pip install -e .
```

```bash
# Basic (Markdown output)
sales-report --input data/sample/sales.csv --output out/summary.md

# CSV output, plus a report of skipped rows and why
sales-report --input data/sample/sales_with_errors.csv --format csv \
  --output out/summary.csv --report-errors out/errors.csv

# Aggregate a whole directory of CSVs
sales-report --input data/sample/multi_store --output out/summary.md

# Slack notification (optional; nothing is sent by default)
sales-report --input data/sample/sales.csv --slack-webhook https://hooks.slack.com/services/...

# Slack notification (preferred: pass the webhook via an environment variable so it
# does not end up in shell history or the process list)
export SALES_REPORT_SLACK_WEBHOOK=https://hooks.slack.com/services/...
sales-report --input data/sample/sales.csv
```

| Option | Description | Default |
|---|---|---|
| `--input` (required) | Path to a CSV file, or a directory containing CSVs | - |
| `--format` | Output format: `csv` or `markdown` | `markdown` |
| `--output` | Where to write the summary report | `out/summary.md` |
| `--report-errors` | Where to write the report of skipped rows with reasons (only written when specified) | not written |
| `--slack-webhook` | When set, posts the summary to Slack. **This is a secret, so prefer the environment variable `SALES_REPORT_SLACK_WEBHOOK`** to keep it out of shell history and the process list (an explicit flag takes precedence) | not sent |

Exit codes are three-valued (see `docs/test-design.md` §1.4): `0` success /
`1` no valid line items / `2` input or usage error.

`data/sample/` contains demo CSVs: clean data, data containing errors, Shift-JIS
encoded data, and a multi-store directory.

---

## Testing

- Conditions derived from **equivalence partitioning, boundary value analysis and
  decision tables** ([docs/test-design.md](docs/test-design.md))
- Quantity 0 and unit price 0 are **valid** boundary values; negatives are invalid;
  full-width digits are explicitly rejected (found and fixed during development —
  see [docs/defects.md](docs/defects.md))
- **CSV injection is neutralised** (values beginning with `=` `+` `-` `@`),
  writes are **atomic** (an interrupted process never leaves a half-written file;
  power-loss level durability via fsync is explicitly out of scope), and runs are
  **idempotent** (the same input produces byte-identical output)
- **Property-based tests** (Hypothesis): the grand total always equals the sum of the
  per-store / per-product / per-date breakdowns; reordering the input rows never
  changes the result; and so on
- **Golden tests** catch regressions in the output format
- **Performance**: 100,000 rows in roughly 1 second using about 52 MB (measured).
  The test asserts a floor of 3 seconds / 150 MB rather than the measured value, and
  is separated from the normal run (`pytest -m slow`)

```bash
pytest --cov --cov-report=term-missing   # normal tests (performance tests excluded)
pytest -m slow                            # performance tests only
ruff check .                              # lint
mypy src/ tests/ scripts/                 # type check (tests and CI scripts included)
mutmut run                                # mutation testing (requires WSL; no native Windows support)
```

## QA process documents

*These are written in Japanese. Tables, diagrams, code identifiers and paths are
readable as-is, and machine translation handles the prose well.*

The intent is to document the QA process itself with the same care as a deliverable
handed to a client, not just to write the implementation.

| Document | Contents |
|---|---|
| [docs/test-design.md](docs/test-design.md) | Test design (equivalence partitioning, boundaries, decision tables, condition-ID table, risk-based priority) |
| [docs/test-report.md](docs/test-report.md) | Test completion report (results, residual risk, release decision) |
| [docs/defects.md](docs/defects.md) | Defect log — only defects actually found during development; nothing invented |
| [docs/exploratory-notes.md](docs/exploratory-notes.md) | Exploratory testing record (charters and session notes) |
| [docs/known-issues.md](docs/known-issues.md) | Known issues, including why mutation testing is not yet complete |

CI results (JUnit XML and the coverage HTML report) are stored as workflow artifacts,
and pushes to `main` publish the coverage HTML report to GitHub Pages.

---

## Design notes

- **All monetary arithmetic uses `Decimal`; float is never used.** Decimal alone is
  not sufficient, though — beyond the default 28-digit precision it also rounds. So
  input limits are enforced up front (`unit_price` up to 12 integer digits and 2
  decimal places, `quantity` up to 9 digits) and aggregation runs at 50-digit
  precision ([docs/defects.md](docs/defects.md) DEF-010).
- **Output amounts are always rendered with 2 decimal places** (`100.00`, never `100`).
  Because unit prices are limited to 2 decimal places on input, this quantisation is
  lossless in practice. The aggregation layer (`aggregate.py`) is untouched; this is
  purely the responsibility of the output layer (`format_money` in `report.py`) —
  see DEF-016.
- **Quantity 0 and unit price 0 are valid boundary values** (free samples and similar
  real cases). Only negative values are rejected.
- **Duplicate line items are merged rather than rejected** — multiple rows for the
  same date, store and product are allowed.
- **One badly encoded file does not stop the run.** UTF-8 falls back to Shift-JIS, and
  only the files that still fail are skipped; processing continues.
- **CSV injection is mitigated** by prefixing `'` to values starting with
  `=` `+` `-` `@` (OWASP guidance).
- **The CLI has three exit codes**, so "finished successfully with zero valid line
  items" can never be reported as plain success — that silent failure mode is
  designed out.

## Development

```bash
pip install -e ".[dev]"
pytest --cov
ruff check .
mypy src/ tests/ scripts/
```

Python 3.11+. See `pyproject.toml` for dependencies.

## License

MIT
