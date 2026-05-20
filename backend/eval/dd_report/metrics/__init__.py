"""Phase 2 metric implementations.

5 metric 对应 spec § 4.2:
  M1 CitationMetric         — extraction
  M2 NumericalMetric        — extraction
  M3 RiskPairingMetric      — summarization (LLM judge)
  M4 PredictionMetric       — reasoning (backtest)
  M5 CompositeJudgeMetric   — reasoning (multi-LLM consensus)
"""
