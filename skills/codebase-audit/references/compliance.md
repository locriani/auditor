# Compliance & Regulatory

## Contents
- The decisive question
- Establish the regime first
- Encoding is not encryption
- What is not logged is the harder half
- Retention, and the tension
- Data at rest and in transit
- Silent-success patterns in this axis
- What to measure

## The decisive question

**What lands in logs — and is encoding being mistaken for encryption?**

Sensitive data in logs is close to universal and close to universally unintentional. It arrives because logging is written to help debugging, and the most useful thing to log is the data that caused the problem.

## Establish the regime first

Ask what actually applies before grading anything: HIPAA, GDPR, PCI-DSS, SOC 2, CCPA, FERPA, or nothing. The regime decides what counts as sensitive, what retention is required, and what an audit trail must contain.

Where no regime applies, this axis is still worth running — the questions are the same, and only the consequence changes. Say which regime you assumed; a reader in a different jurisdiction needs to know.

## Encoding is not encryption

**Decode before concluding.** Base64, hex, and URL encoding are transport formats. They are reversible by anyone, with no key, and treating them as protection is a category error that appears in real systems with real regularity.

```sh
echo '<value>' | base64 -d
```

```sql
SELECT FROM_BASE64(comments) FROM log ORDER BY date DESC LIMIT 20;
```

Read what comes out. Then ask the question that decides severity: **do bound parameters travel with the statement?** A logged query template is low-sensitivity; the same template with its values is the data itself.

*Worked example.* Every row written through `EventAuditLogger::recordLogItem` is base64-encoded at `src/Common/Logging/EventAuditLogger.php:664`, and the encoded payload is the SQL statement *with bound parameters appended* (`:446-450`) — `... WHERE pid=? ('13')`. The code comment explains the encoding exists to protect binary UUIDs from mangling, which is true and is not a security control. A prior encryption path was removed, so base64 is all that remains.

Check the same thing in application logs, error reports, crash handlers, and anything shipped to a third party. A log that never leaves the host is a different exposure from one streamed to a vendor.

## What is not logged is the harder half

An audit log that records writes and drops reads looks healthy and answers the wrong question. Regimes that require accounting of *disclosures* care primarily about who **read** what.

Find the logging filter and read its exclusions:

```
skips statements matching the log table itself     loop prevention — legitimate
skips SELECT unless a flag is enabled              reads are not recorded by default
skips SELECT count(...)                            a whole statement shape, invisible
```

*Worked example.* `EventAuditLogger::auditSQLEvent` drops every `SELECT` unless `queryEvents` is enabled (`:437-442`) and unconditionally skips statements beginning `SELECT count(` (`:418-425`). The log is therefore a record of modifications, not of access — and it is a silent-success shape, because the log looks populated and healthy while the access-accounting requirement goes unmet.

This is harder to find than PHI-in-logs because there is nothing to grep for. You have to read the filter.

## Retention, and the tension

Two requirements point in opposite directions, and the tension is the thing to report:

```
minimise   keep sensitive data no longer than necessary
retain     keep audit records for a statutory period
```

Establish whether retention exists at all, whether it distinguishes audit records from operational logs, and whether anything enforces it or it is merely written down. Unbounded log growth carrying sensitive payloads is the worst cell of that matrix: rising cost and rising exposure from the same table.

Also check tamper-evidence. An audit log that can be silently edited by the application's own database user does not establish much. Look for checksum chaining, append-only storage, or shipment to a separate system.

## Data at rest and in transit

- **At rest.** Disk encryption, column encryption, backups — backups are routinely forgotten and are a full copy of everything.
- **In transit.** Internal hops too, not just the edge. TLS terminated at a load balancer with plaintext behind it is a defensible design and needs to be a decision rather than an accident.
- **Credentials.** Hashing algorithm and parameters for stored passwords; where the system keeps its own secrets.
- **Session handling.** Cookie flags, timeout, fixation, and whether timeouts differ between UI and API.

## Silent-success patterns in this axis

| Pattern | How it shows up |
|---|---|
| Default Values Masking Loss | encoding present, mistaken for protection, so nobody looks again |
| Missing Expected Metrics | reads are absent from the audit log and nothing reports the absence |
| Unchecked Output | a redaction filter runs and nothing verifies that it caught anything |

The third is worth a synthetic probe: put a known marker string through a path that should redact it, then grep the log for the marker. A redaction layer nobody has tested usually has a gap, and this finds it in one command.

## What to measure

- Which regime applies, stated as an assumption.
- Decoded log contents, with bound parameters checked for.
- The logging filter's exclusion list, read line by line.
- Whether reads are recorded at all.
- Retention policy, and whether anything enforces it.
- Tamper-evidence on the audit trail.
- A synthetic marker pushed through the redaction path.
