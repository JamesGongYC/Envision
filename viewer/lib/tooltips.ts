export const TOOLTIPS = {
  brier:
    'Brier score: a calibration metric for probabilistic forecasts. Lower is better. A perfect skill scores 0; random guessing scores around 0.25.',
  hit:
    'Hit: forecast issued and a matching ground-truth event occurred within the validity window.',
  falsePositive:
    'False positive: forecast issued but no matching ground-truth event occurred within the validity window.',
} as const;
