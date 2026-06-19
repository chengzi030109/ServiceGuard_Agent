# ServiceGuard Evaluation Report

- Generated at: `2026-06-19T09:47:10.129833+00:00`
- Dataset: `data\samples\tickets_sample.csv`
- Gate status: `PASS`

## Summary

| Metric | Value | Threshold |
| --- | ---: | ---: |
| Total cases | 20 |  |
| JSON success rate | 1.0000 |  |
| Risk accuracy | 1.0000 | 0.95 |
| Violation accuracy | 1.0000 | 0.95 |
| Expected violation recall | 1.0000 |  |
| Citation coverage | 1.0000 | 0.9 |
| High-risk recall | 1.0000 | 0.95 |
| Average score | 85.9000 |  |
| Average latency ms | 21.5500 |  |

## Confusion Matrix

| Expected \ Predicted | low | medium | high | other |
| --- | ---: | ---: | ---: | ---: |
| low | 11 | 0 | 0 | 0 |
| medium | 0 | 3 | 0 | 0 |
| high | 0 | 0 | 6 | 0 |

## Row Results

| Ticket | Expected risk | Predicted risk | Expected violation | Predicted violations | Risk match | Violation match | Citations | Latency ms |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| T001 | high | high | over_promise | over_promise,process_missing | True | True | 4 | 93 |
| T002 | low | low |  |  | True | True | 0 | 19 |
| T003 | high | high | privacy_risk | privacy_risk | True | True | 1 | 16 |
| T004 | medium | medium | attitude_issue | attitude_issue | True | True | 1 | 18 |
| T005 | high | high | policy_conflict | policy_conflict | True | True | 2 | 18 |
| T006 | low | low |  |  | True | True | 0 | 17 |
| T007 | medium | medium | process_missing | process_missing | True | True | 2 | 16 |
| T008 | low | low |  |  | True | True | 0 | 18 |
| T009 | high | high | over_promise | over_promise | True | True | 2 | 16 |
| T010 | low | low |  |  | True | True | 0 | 19 |
| T011 | low | low |  |  | True | True | 0 | 19 |
| T012 | medium | medium | attitude_issue | attitude_issue | True | True | 1 | 19 |
| T013 | low | low |  |  | True | True | 0 | 18 |
| T014 | high | high | policy_conflict | over_promise,policy_conflict | True | True | 3 | 16 |
| T015 | low | low |  |  | True | True | 0 | 19 |
| T016 | low | low |  |  | True | True | 0 | 19 |
| T017 | low | low |  |  | True | True | 0 | 16 |
| T018 | low | low |  |  | True | True | 0 | 19 |
| T019 | high | high | over_promise | over_promise | True | True | 2 | 18 |
| T020 | low | low |  |  | True | True | 0 | 18 |
