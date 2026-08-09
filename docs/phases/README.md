# Implementation Phases

This directory contains per-phase research and knowledge documents for the **AI-Powered Quantitative Trading Research & Execution Platform** project.

Each document covers: what we're building, key concepts, tech stack references, data contracts, dependencies, and definition of done.

---

## Phase Overview

| Phase | Name | Status |
|-------|------|--------|
| 00 | [Project Foundation](phase-00_project-foundation.md) | Implemented |
| 01 | [DhanHQ Data Acquisition](phase-01_dhan-data-acquisition.md) | Research |
| 02 | [Data Validation](phase-02_data-validation.md) | Research |
| 03 | [Candle Processing](phase-03_candle-processing.md) | Research |
| 04 | [Strategy Engine](phase-04_strategy-engine.md) | Research |
| 05 | [Backtester](phase-05_backtester.md) | Research |
| 06 | [Baseline Results](phase-06_baseline-results.md) | Research |
| 07 | [Eve Agent](phase-07_eve-agent.md) | Research |
| 08 | [Advanced Research](phase-08_advanced-research.md) | Research |
| 09 | [Snowflake](phase-09_snowflake.md) | Research |
| 10 | [Real-Time Data](phase-10_real-time-data.md) | Research |
| 11 | [Kafka](phase-11_kafka.md) | Research |
| 12 | [Paper Trading](phase-12_paper-trading.md) | Research |
| 13 | [Risk Engine](phase-13_risk-engine.md) | Research |
| 14 | [Human-Approved Live Trading](phase-14_human-approved-live-trading.md) | Research |

---

## Dependency Graph

```
Phase 00: Project Foundation
  └─> Phase 01: DhanHQ Data Acquisition
        └─> Phase 02: Data Validation
              └─> Phase 03: Candle Processing
                    └─> Phase 04: Strategy Engine
                          └─> Phase 05: Backtester
                                └─> Phase 06: Baseline Results
                                      └─> Phase 07: Eve Agent
                                            ├─> Phase 08: Advanced Research
                                            └─> Phase 09: Snowflake (parallel)
                                                  └─> Phase 10: Real-Time Data
                                                        └─> Phase 11: Kafka
                                                              └─> Phase 12: Paper Trading
                                                                    └─> Phase 13: Risk Engine
                                                                          └─> Phase 14: Live Trading
```

## First Milestone (Phases 00-06)

> A user can ask the AI agent to retrieve July 2026 NIFTY Futures data and run the 9/15 EMA + 30-degree strategy on 1m, 5m and 15m, with reproducible results.

---

*Source: `AI_Quant_Trading_Platform_Project_Proposal.md` — Section 60 (Implementation Phases)*
