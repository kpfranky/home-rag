# Local UI acceptance — 2026-10-16

Scope: Home RAG UI v0.1.0, running locally on the developer's Mac with the existing evidence-first backend. Evidence consists of user-provided screenshots, downloaded answer JSON files, and explicit user confirmations. This record summarizes acceptance testing; it does not include the screenshots, private documents or execution data.

## Real-index mode

| Check | Result | Evidence |
| --- | --- | --- |
| Table-row answer | Pass | Allergy values 59% (61), 41% (43), 0% (0); only the requested condition. Screenshot and exported JSON. |
| Source expansion | Pass | Source S1 expands to PDF 97, column headers and the exact requested row. |
| JSON download | Pass | User confirmed download; the exported question, values and evidence matched the displayed table answer. |
| Text answer | Pass | The original quote states limited generalization potential; PDF 52. Screenshot and exported JSON. |
| Refresh after completion | Pass | User confirmed restoration of the completed question and result. |
| Out-of-scope refusal | Pass | No-answer message; JSON has answerable=false, claims=[] and sources=[]. |
| No stale sources after refusal | Pass | Refusal screen contains no sources from the previous text answer. |
| Refresh while processing | Pass | User confirmed return to the same question and ongoing processing; final refusal displayed normally. |

Observed timings on these individual executions: table 13.8 s, text 80.4 s, refusal 53.0 s. They include execution startup and are not controlled performance measurements.

## Synthetic-demo mode

The UI states that it uses synthetic content without invoking a model.

| Example | Result |
| --- | --- |
| Document-preparation steps | Pass: scanning, text recognition and quality checking, with the matching synthetic source. |
| Quality-control table | Pass: 80% (8), 20% (2), 0% (0), with the matching synthetic source. |
| Out-of-scope question | Pass: refusal without sources. |

Demo results are predefined keyword-based examples, not evidence of retrieval or LLM quality.

## Automated and manual scope

Eight new tests passed during UI development: HTTP serving, request restrictions, question validation, a real subprocess using the synthetic backend, JSON/log retrieval, refusal, backend error reporting, single active execution, and citation checks. Some tests cover more than one behavior. The backend previously had 145 passing tests; 153 combined tests are expected. This record does not claim a captured 153-test run on the Mac.

The provided browser screenshots demonstrate the accepted desktop layout. They do not establish mobile-browser support, browser-matrix coverage, accessibility conformance, or manual recovery from a backend failure. Automated tests cover backend failure handling; it was not manually exercised in these acceptance examples.

Known backend limitations, including extra contextual evidence in L02, remain documented in the [backend checkpoint](evaluation/evidence_first_2026-10-12.md).

Decision: the basic local UI is accepted for a repository demonstration with explicit synthetic-mode labelling. This is not a production-readiness or general accuracy claim.
