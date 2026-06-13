"""Shared state metadata for stoiclife (display names + coaching objectives)."""

STATE_DISPLAY = {
    "rattled_but_ready": "Rattled but Ready",
    "running_on_fumes": "Running on Fumes",
    "system_drain": "System Drain",
    "sweet_spot": "Sweet Spot",
    "neutral": "Neutral",
    "insufficient_data": "Insufficient Data",
}

# The coach's objective per the trigger matrix (Phase 2 spec).
STATE_OBJECTIVE = {
    "rattled_but_ready": "Encourage physical exertion (BJJ, run); the body is recovered "
                         "and can carry the mental load. Counter the felt sense of depletion.",
    "running_on_fumes": "Warn against overcommitting. Momentum is high but the body is "
                        "depleting; protect early rest tonight to avoid a crash.",
    "system_drain": "Pull the brake: active recovery, set one boundary, drop every "
                    "non-essential task today.",
}

# Only these reach the evaluation engine (Phase 3) and can be delivered (Phase 4).
NON_SILENT = set(STATE_OBJECTIVE)
