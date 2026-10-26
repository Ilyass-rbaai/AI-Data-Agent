# Live integration and AI evaluation — 26 October 2026

## Results

- Live PostgreSQL connectivity: PASS (SELECT 1).
- Existing database transaction protection: write blocked in read-only transaction
  with SQLSTATE 25006. All permission probes used WHERE FALSE and rolled back;
  no existing records were changed.
- Existing application's least-privilege configuration: FAIL. The configured login
  is a superuser with INSERT, UPDATE and DELETE permission. SET TRANSACTION READ WRITE
  allowed a zero-row UPDATE. The read-only session flag is not an authorization boundary.
- Restricted role enforcement: PASS. Under pg_read_all_data, a zero-row UPDATE in a
  read/write transaction failed with SQLSTATE 42501 (insufficient privilege).
- Real AI SQL graph: 5/5 exact-result matches on a synthetic PostgreSQL fixture.
- Real router: 2/2 expected classifications (SQL and ETL).
- Synthetic schema cleanup: PASS; the fixture schema and its invented rows were removed.

## Known answers and observed correctness

| Test | Independently calculated expected result | Observed |
| --- | --- | --- |
| Count users | 6 | Exact match |
| First five users, ordered by ID | IDs 1–5, Alice/Bob/Carla/David/Eve Example | Exact match |
| Count active users | 4 | Exact match |
| Total payment amount rounded to cents | 50.00 | Exact numeric match |
| Top riders joined to user names | IDs 1,2,3,4,5 with ride counts 3,2,1,1,1 | Exact match including order |

Fixtures: six invented users, nine rides and four payments. Expected answers were
calculated in Python independently of model-generated SQL and cross-checked against
trusted SQL before each case. Values were normalized for equivalent numeric types;
row order, column order and row counts were compared exactly. JSON evidence contains
the generated SQL and SHA-256 hashes of expected and actual normalized result sets.

## Execution scope

The real compiled SQL agent ran question curation, SQL generation, the structured
safety judge, execution and final answer generation using its configured models.
For the benchmark only, its database adapter was replaced by an executor restricted
to the synthetic fixture tables and a small SELECT/function allowlist. It used
SET LOCAL ROLE pg_read_all_data and a five-second statement timeout. The context
adapter supplied only the fixture schema, without production samples.

This validates the agent with a restricted evaluator; it is NOT an unmodified
end-to-end validation of production execution. The final natural-language response
was checked for presence, not independently scored for factual accuracy.
The router was tested separately; the ETL execution agent was not evaluated live.

The initial production-data benchmark was rejected by automatic approval review
because exporting existing schema and query results to OpenAI lacked specific
authorization. The executed alternative exported only synthetic fixture metadata
and synthetic query results. No existing database schema or records were sent to
the models. The local connectivity probe inspected table names and permissions only.

## Usage and timing

- Actual model calls: 22, below the configured limit of 24; retries disabled.
- Recorded input tokens: 4,160; recorded output tokens: 845.
- SQL case durations: 9.66s, 8.69s, 6.31s, 6.16s and 8.03s.
- Total benchmark duration, including routing: 43.91s.
- Monetary cost was not calculated; check the API Usage page for billed cost.

These are one-run measurements on five small questions. A 5/5 score is not evidence
of 100% accuracy on arbitrary questions, repeat-run stability or adversarial safety.
No claims are made about production throughput, ETL execution correctness or sandboxing.

## Reproduce

From the project root:

```powershell
# Local database checks only; no paid model calls.
.\.venv\Scripts\python.exe -B tests/live_postgres_probe.py

# Paid real-model test, maximum 24 calls; synthetic records only.
.\.venv\Scripts\python.exe -B tests/live_synthetic_evaluation.py
```

Both scripts use the project's existing .env. The synthetic test needs permission
to create and remove its uniquely named fixture schema. If the process is forcibly
terminated, inspect for a remaining reliability_fixture_* schema before retrying.
Cleanup is performed in finally on ordinary failures. The current synthetic script
has a fixed five-case dataset; expand it and repeat runs before making wider claims.

## Required security follow-up

Use a dedicated LOGIN role with SELECT on the required application tables and schema
USAGE, no superuser/ownership/CREATE privileges, and no write privileges inherited
through other roles. Update the application's DB credentials only after that role
is configured and tested. The benchmark's temporary SET ROLE change did not modify
the application's .env or fix its current superuser configuration.

Read-only transactions remain useful defense in depth. They do not replace limited
credentials, function privilege review or isolation for the ETL agent's generated exec.
