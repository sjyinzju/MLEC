# MLEC active research contract

- Read `docs/MLEC_research_protocol.md` before research changes. The authority is market-state-research-v3.0: four markets, five economic dimensions, seven core future-20-trading-day outcomes, all market states.
- Single data command: `python -m scripts.market_state.run`. Single read interface: `scripts.market_state.framework.load_dataset`.
- The formal snapshot ends at 2026-11-13 18:00 Asia/Shanghai. Consult `data/market_state/release/seal.json`, `missing_policy.json`, `research_dependencies.json` and `reports/market_state/completion_report.md` before modeling. A candidate source series is not automatically a formal feature.
- Require an explicit fold and role for training/validation/test reads. Use `view='analysis'` only for descriptive inspection. Use the unfitted preprocessing factory and fit on training rows only. State IDs are nominal, never ordinal risk scores.
- All information sets and group additions/deletions use the same cohorts and targets. Use the data task configuration for later batch experiments; do not create per-model data pipelines.
- Source libraries under `scripts/final_data_foundation`, `scripts/data_foundation_v3` and `scripts/macro_pipeline` preserve collection and repair know-how; they do not define research samples. E:/QuantData is read-only.
- A sealed release stops automatic data expansion. If the user explicitly requests a new snapshot or protocol, record the change, invalidate affected caches, rebuild and reaccept. Never silently reuse a stale acceptance manifest.
- No supervisory prediction models or results were produced in this data acceptance round. Model selection and batch training require the next explicit research task.
