# Standards Map

Identifiers for tagging findings. Offline and deliberately compact — this file exists so a
finding can carry `Refs: A02:2025, CWE-798` without a lookup, not to teach the standards.

**Tag only where a mapping is real.** A forced tag is worse than no tag: it implies a rigour
the finding does not have, and a reader who checks will find the mismatch. Many legitimate
findings — squashed history, a sparse high-stakes field, an unmeasured amplification ratio —
map to nothing here. Omit the `Refs` line for those.

## Contents
- OWASP Top 10 (2025), with the 2021 IDs it replaces
- OWASP ASVS categories
- CWE Top 25 — most dangerous software weaknesses
- CWE identifiers for audit findings with no Top-25 entry
- Where live vulnerability data comes from

## OWASP Top 10 (2025)

The 2025 edition replaces 2021. Tag new findings with 2025 IDs. The last column maps a 2021 ID found in an older report.

| ID | Name | Typical audit finding | 2021 |
|---|---|---|---|
| A01:2025 | Broken Access Control | UI-layer-only enforcement; superuser short-circuit; unconfigured-means-open; user-controlled URL fetched server-side (SSRF, CWE-918) | A01, A10 |
| A02:2025 | Security Misconfiguration | shipped default credentials; debug services published to the host | A05 |
| A03:2025 | Software Supply Chain Failures | build fetches unpinned remote source; no artifact identity assertion; anything the ecosystem auditor reports; tooling that executes target-supplied config | A06, part of A08 |
| A04:2025 | Cryptographic Failures | encoding mistaken for encryption; plaintext in transit between internal hops | A02 |
| A05:2025 | Injection | concatenated SQL; unparameterised queries | A03 |
| A06:2025 | Insecure Design | no way to distinguish denial from absence; retention that cannot satisfy both requirements | A04 |
| A07:2025 | Authentication Failures | weak password hashing; session fixation; no timeout | A07 |
| A08:2025 | Software or Data Integrity Failures | unsigned updates; deserialising untrusted data; evidence a local account can rewrite | A08 |
| A09:2025 | Security Logging and Alerting Failures | reads not logged; no absence alerting; tamper-editable audit trail | A09 |
| A10:2025 | Mishandling of Exceptional Conditions | swallowed exceptions; success codes on failed work; fail-open error paths | — |

## OWASP ASVS categories

Cite the category when a finding is about a control area rather than a specific defect.

| ID | Category |
|---|---|
| V1 | Architecture, Design and Threat Modeling |
| V2 | Authentication |
| V3 | Session Management |
| V4 | Access Control |
| V5 | Validation, Sanitization and Encoding |
| V6 | Stored Cryptography |
| V7 | Error Handling and Logging |
| V8 | Data Protection |
| V9 | Communication |
| V10 | Malicious Code |
| V11 | Business Logic |
| V12 | Files and Resources |
| V13 | API and Web Service |
| V14 | Configuration |

## CWE Top 25 — most dangerous software weaknesses

| CWE | Name |
|---|---|
| CWE-79 | Cross-site Scripting |
| CWE-787 | Out-of-bounds Write |
| CWE-89 | SQL Injection |
| CWE-352 | Cross-Site Request Forgery |
| CWE-22 | Path Traversal |
| CWE-125 | Out-of-bounds Read |
| CWE-78 | OS Command Injection |
| CWE-416 | Use After Free |
| CWE-862 | Missing Authorization |
| CWE-434 | Unrestricted Upload of File with Dangerous Type |
| CWE-94 | Code Injection |
| CWE-20 | Improper Input Validation |
| CWE-77 | Command Injection |
| CWE-287 | Improper Authentication |
| CWE-269 | Improper Privilege Management |
| CWE-502 | Deserialization of Untrusted Data |
| CWE-200 | Exposure of Sensitive Information to an Unauthorized Actor |
| CWE-863 | Incorrect Authorization |
| CWE-918 | Server-Side Request Forgery |
| CWE-119 | Improper Restriction of Operations within the Bounds of a Memory Buffer |
| CWE-476 | NULL Pointer Dereference |
| CWE-798 | Use of Hard-coded Credentials |
| CWE-190 | Integer Overflow or Wraparound |
| CWE-400 | Uncontrolled Resource Consumption |
| CWE-306 | Missing Authentication for Critical Function |

## CWE identifiers for audit findings with no Top-25 entry

The audit findings that recur most in this method are mostly *not* in the Top 25, because the
Top 25 ranks weaknesses by how often they appear in published CVEs, weighted by severity, and an audit ranks inherited risk. These are the ones worth
knowing:

| CWE | Name | Why it comes up here |
|---|---|---|
| CWE-390 | Detection of Error Condition Without Action | the canonical swallowed exception |
| CWE-391 | Unchecked Error Condition | the silent-success class, named |
| CWE-544 | Missing Standardized Error Handling Mechanism | inconsistent error idiom across a codebase |
| CWE-252 | Unchecked Return Value | a call whose failure is never inspected |
| CWE-754 | Improper Check for Unusual or Exceptional Conditions | partial batch completion, unnoticed |
| CWE-1104 | Use of Unmaintained Third Party Components | abandoned dependency; build clones upstream |
| CWE-1395 | Dependency on Vulnerable Third-Party Component | what the ecosystem auditors report |
| CWE-532 | Insertion of Sensitive Information into Log File | the PHI/PII-in-logs finding |
| CWE-311 | Missing Encryption of Sensitive Data | encoding mistaken for encryption |
| CWE-778 | Insufficient Logging | reads absent from the audit trail |
| CWE-117 | Improper Output Neutralization for Logs | log injection via unescaped input |
| CWE-1236 | Improper Neutralization of Formula Elements in a CSV File | export paths |
| CWE-1188 | Insecure Default Initialization of Resource | shipped default credentials |
| CWE-276 | Incorrect Default Permissions | unconfigured-means-open |
| CWE-359 | Exposure of Private Personal Information to an Unauthorized Actor | the compliance framing of A01 |

## Where live vulnerability data comes from

Not from this file. It carries no CVE list, because a bundled one is stale the day it is written.

Live data comes from the ecosystem's own auditor, which `probe.sh` runs where a manifest exists:
`composer audit`, `npm audit`, `pip-audit`, `govulncheck`, `cargo audit`, `bundle audit`. Each
resolves against a maintained advisory database at the moment it runs. Cite the CVE it reports,
and cite the tool and date alongside it so the claim can be re-checked.

**Deferred, and worth saying so in the appendix:** live OSV.dev querying for ecosystems whose
native tooling is absent, a full ASVS verification-level walkthrough, and SARIF output.
