> Update: live connectivity and a bounded synthetic AI benchmark have now run. See [LIVE_EVALUATION.md](LIVE_EVALUATION.md). The original offline-run findings below are retained as historical evidence.

# Reliability evidence — 26 October 2026

## Conclusion

The tested deterministic workflows pass 23/23 offline regression tests after fixes.
This establishes regression coverage, not production reliability or measured LLM accuracy.
The live PostgreSQL probe could not connect (OperationalError), so database integration
remains unverified in this session. No paid model calls or database writes were made.

| Check | Before fixes | After fixes |
| --- | --- | --- |
| Offline regression tests | 12 passed; 10 failures; 1 error | 23 passed; 0 failures; 0 errors |
| SQL route / ETL route | Pass | Pass |
| Rejected SQL never executed (controlled verdict) | Pass | Pass |
| SQL history: curated question, result, final answer | 35 messages instead of 3 | 3 messages |
| CSV extraction success acknowledgement | Returned None | Explicit saved path and row count |
| JSON extraction → context reader | Trailing-data exception | Round-trip passes |
| Failed transformation acknowledgement | Claimed saved despite execution failure | Raises an error |
| HTTP timeout | Missing | 30 seconds |
| Unsupported output format | Claimed success without a file | Rejected |
| Database errors | Swallowed as None | Propagated to the caller |
| Read-only database session | Not configured | Configured, verified with mock connection |
| Live PostgreSQL SELECT 1 and transaction flag | Not tested | Could not connect; unverified |

## What actually ran

The suite executes the existing compiled LangGraph graphs. Model responses and
database responses are controlled fixtures; model clients are never instantiated.
An explicit socket guard rejects accidental external network connections.
ETL tests write and read real CSV/JSON files in disposable temporary directories;
HTTP responses are fixtures. Error tests inject timeouts, connection failures,
query failures, a rejected SQL verdict and a failed transformation.

The baseline and final results use the same 23 checks. Per-test results are in
reliability-baseline.json and reliability-results.json. The live probe outcome is
in reliability-live-db.json. Tests do not inspect or publish credential values.

## Run again

From the project root, with the existing environment:

```powershell
.\.venv\Scripts\python.exe -B tests/reliability_suite.py
```

The command exits nonzero on failure and writes reports/reliability-results.json.
No additional testing package is required. Tests use unittest from Python.
Rerun after changing an agent, database helper or ETL tool.

## Changes supported by failures

- SQL nodes return only changed fields and new messages, avoiding reducer duplication.
- Database helpers propagate failures, close resources and roll back read transactions.
- Connection timeout is 10 seconds; statement timeout is 30 seconds.
- Schema/table identifiers are quoted with psycopg2.sql.Identifier.
- Extraction returns a success acknowledgement, validates formats and response shapes,
  and sets a finite HTTP timeout.
- JSON context loading supports both JSON arrays and existing JSON Lines exports.
- Failed generated transformations no longer claim a successful save.
- Code fences are removed by lines instead of lstrip('python'), which could corrupt code.
- The standalone SQL example no longer invokes the paid graph twice.
- .env files and reliability backups are ignored by Git. This does not remove secrets
  already tracked or present in repository history; that history was not audited.

Changed source files were preserved under reliability-backup/.

## What remains unproven

1. Live PostgreSQL integration: the connection probe returned OperationalError.
   Start PostgreSQL, check the configured host/port/database and retry an actual read.
2. Live model routing and SQL correctness: fixtures validate orchestration, not model
   quality. Run a labeled set of questions against an isolated fixture database and
   compare result sets, repeat runs, and record success rate, latency and token cost.
3. Live API variability, pagination, rate limiting, malformed data and parquet engines.
   Current CSV extraction only processes the records returned by one response page.
4. Transformation correctness: the existing agent executes generated Python locally.
   It is not sandboxed. A completed exec is not proof that an output file has the
   expected rows, types or values. Outputs still require validation.
5. Adversarial SQL safety: a judge verdict and a read-only transaction do not replace
   a least-privilege database role. This suite checks session configuration with a
   mock, not server enforcement or all possible SQL statements/functions.
6. Load, concurrency, long-running tasks and deployment behavior were not tested.

The honest portfolio claim is: '23 offline regression tests pass across routing,
SQL control flow, ETL files and error handling; live accuracy evaluation is pending.'
