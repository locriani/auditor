# Performance & Scale

## Contents
- The decisive question
- Measure the SAPI that serves traffic
- CPU time is not wall time
- Amplification ratios
- Worst-case single-record assembly
- Silent-success patterns in this axis
- What to measure

## The decisive question

**What limit governs the path that actually serves traffic?**

Not the limit in the config file you found first. Not the one your shell reports. The one enforced on the process that handles a request.

This is the single most reliable source of wrong conclusions in a performance audit, because the wrong answer is easy to obtain and looks authoritative.

## Measure the SAPI that serves traffic

Runtimes routinely carry different limits per execution context, and the interactive one is almost always the permissive one:

```
php -r 'echo ini_get("max_execution_time");'   → the CLI SAPI's value
                                                  frequently 0, meaning unlimited
```

Apache mod_php, PHP-FPM, and each web SAPI carry their own. The same split exists elsewhere: a Python worker's timeout versus the shell's, a Node process manager's memory ceiling versus `node --max-old-space-size` on your terminal, a container limit versus the host's.

**Get the value from inside the serving process.** Expose a temporary endpoint that prints it, read the server's own config, or check the process's effective limits — anything but the interactive interpreter.

*Worked example.* In an OpenEMR container, the CLI reports `max_execution_time=0` while Apache mod_php enforces 60. An audit that trusted the CLI would have reported "no execution cap" and been wrong about the single limit that truncates bulk imports.

## CPU time is not wall time

Where a limit counts CPU rather than wall clock, the consequences are counterintuitive and worth stating explicitly, because they determine which operations are at risk:

```
XML/JSON parsing, serialisation, crypto   → burns CPU      → trips the limit
database waits, network I/O, sleep        → burns no CPU   → does not
```

So a request that spends ninety seconds waiting on a slow query completes, and one that spends sixty-one seconds parsing documents dies. This inverts the intuition that "slow things time out", and it explains failures that otherwise look random.

## Amplification ratios

Measure how much the system writes *about* the work relative to the work itself. Audit logs, event streams, change tables, and search indexes all amplify, and the ratio is usually unmeasured and sometimes extreme.

```sh
# per-table on-disk size, MySQL/MariaDB — adapt per engine
SELECT table_name,
       ROUND((data_length + index_length)/1024/1024, 2) AS mb
FROM information_schema.tables
WHERE table_schema = DATABASE()
ORDER BY (data_length + index_length) DESC LIMIT 20;
```

Compare the ancillary total against the payload total. A ratio far from 1:1 is a cost-model input, not a defect — it tells you that scaling this system is a storage problem rather than a throughput problem, which changes what you provision and what you budget.

*Worked example.* 32.5 MB of audit and logging tables against 0.84 MB of clinical data — roughly 39:1. Import throughput held steady as the log grew, which settles the question: storage cost, not a bottleneck.

## Worst-case single-record assembly

Find the deepest record in the system — the one with the most related rows — and time assembling it end to end. Not the median; the tail is what sets the strategy.

This single number decides whether downstream work can assemble records on demand or must pre-compute. Measure it against real data volumes, state the record you used, and state how it was reached.

## Silent-success patterns in this axis

| Pattern | How it shows up |
|---|---|
| Async Work Without Completion Signal | a batch dies mid-run; the queue is left half-drained |
| Unchecked Output | N records requested, fewer written, nothing compares the two |
| Missing Expected Metrics | throughput drops to zero and no error is raised |

The first is the expensive one. A bulk operation that exceeds a per-request limit leaves partial state behind, and if the caller reports only a bare 5xx, nobody can tell how far it got. The probe: run a batch large enough to trip the limit, then count what actually landed and look for orphaned rows on both sides of every paired write.

## What to measure

- The governing limit for the serving context, obtained from inside it.
- Whether that limit counts CPU or wall time.
- Ancillary-to-payload storage ratio, with the query that produced it.
- Worst-case single-record assembly latency, naming the record.
- What partial state a truncated bulk operation leaves behind.
