"""Explainable triage risk-scoring service.

Moved out of `api/views.py` (previously the private `_score_health_risk`
function) into a dedicated service module to fix a confirmed ARC-01
violation: this is real, portfolio-relevant business logic — arguably the
"smart" core of the whole application — and it does not belong living as a
private view-module function when the project already has a
correctly-factored precedent for business logic
(`api/services/workflow_engine.py`).

Why named constants (CODE-06): the scoring weights and risk-level cutoffs
below were previously hardcoded inline inside the scoring function. Naming
them makes the scoring model's actual policy legible without reading
arithmetic, and makes a deliberate policy change (e.g. "weight blood
pressure more heavily") a one-line diff instead of a search through
unlabeled floats scattered through an expression.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from api.models import RiskAssessment

# Contribution weights. Each factor's contribution is `component * WEIGHT`,
# where `component` is a 0..1 normalized measure of how far a value sits in
# its clinically-relevant range. Weights sum to 1.0 so the final
# `risk_score` is itself naturally bounded to [0, 1] before clipping.
AGE_WEIGHT = 0.16
BMI_WEIGHT = 0.18
BLOOD_PRESSURE_WEIGHT = 0.22
CHOLESTEROL_WEIGHT = 0.14
SMOKING_WEIGHT = 0.14
EXERCISE_DEFICIT_WEIGHT = 0.06
CHRONIC_CONDITIONS_WEIGHT = 0.10

# Normalization ranges used to convert each raw clinical input into a 0..1
# "how concerning is this value" component before it is weighted above.
AGE_NORMALIZATION_MAX = 100
BMI_NORMALIZATION_FLOOR = 18.5
BMI_NORMALIZATION_RANGE = 21.5
BLOOD_PRESSURE_NORMALIZATION_FLOOR = 90
BLOOD_PRESSURE_NORMALIZATION_RANGE = 90
CHOLESTEROL_NORMALIZATION_FLOOR = 130
CHOLESTEROL_NORMALIZATION_RANGE = 220
EXERCISE_MINUTES_NORMALIZATION_MAX = 300
CHRONIC_CONDITIONS_NORMALIZATION_MAX = 5

# Risk-level cutoffs applied to the final 0..1 `risk_score`.
RISK_LEVEL_CRITICAL_THRESHOLD = 0.78
RISK_LEVEL_HIGH_THRESHOLD = 0.60
RISK_LEVEL_MEDIUM_THRESHOLD = 0.38

#: How many top contributing factors to surface in `key_drivers` for
#: explainability — enough to be useful, few enough to stay scannable.
KEY_DRIVERS_LIMIT = 3


def score_health_risk(data: dict[str, Any]) -> dict[str, Any]:
    """Score a patient's explainable triage risk from clinical inputs.

    `data` is expected to already be validated (see
    `TriageAssessmentRequestSerializer`) — this function trusts its input
    ranges and performs no independent validation of its own.

    Returns a dict with `risk_score` (0..1), `risk_level`,
    `recommended_action`, and `key_drivers` (the top contributing factors,
    for explainability — this is a transparent weighted-rule formula, not a
    black-box model, and `key_drivers` is what makes that transparency
    visible in the API response).
    """
    age = data['age']
    bmi = data['bmi']
    blood_pressure = data['blood_pressure']
    cholesterol = data['cholesterol']
    smoker = data.get('smoker', False)
    exercise_minutes = data.get('exercise_minutes', 0)
    chronic_conditions = data.get('chronic_conditions', 0)

    age_component = min(age / AGE_NORMALIZATION_MAX, 1)
    bmi_component = np.clip((bmi - BMI_NORMALIZATION_FLOOR) / BMI_NORMALIZATION_RANGE, 0, 1)
    bp_component = np.clip(
        (blood_pressure - BLOOD_PRESSURE_NORMALIZATION_FLOOR) / BLOOD_PRESSURE_NORMALIZATION_RANGE, 0, 1
    )
    chol_component = np.clip(
        (cholesterol - CHOLESTEROL_NORMALIZATION_FLOOR) / CHOLESTEROL_NORMALIZATION_RANGE, 0, 1
    )
    smoker_component = 1.0 if smoker else 0.0
    exercise_component = 1.0 - np.clip(exercise_minutes / EXERCISE_MINUTES_NORMALIZATION_MAX, 0, 1)
    chronic_component = np.clip(chronic_conditions / CHRONIC_CONDITIONS_NORMALIZATION_MAX, 0, 1)

    contributions = {
        'age': float(age_component * AGE_WEIGHT),
        'bmi': float(bmi_component * BMI_WEIGHT),
        'blood_pressure': float(bp_component * BLOOD_PRESSURE_WEIGHT),
        'cholesterol': float(chol_component * CHOLESTEROL_WEIGHT),
        'smoking': float(smoker_component * SMOKING_WEIGHT),
        'exercise_deficit': float(exercise_component * EXERCISE_DEFICIT_WEIGHT),
        'chronic_conditions': float(chronic_component * CHRONIC_CONDITIONS_WEIGHT),
    }

    score = float(np.clip(sum(contributions.values()), 0, 1))

    if score >= RISK_LEVEL_CRITICAL_THRESHOLD:
        level = RiskAssessment.LEVEL_CRITICAL
        recommendation = 'Immediate physician escalation and same-day diagnostics.'
    elif score >= RISK_LEVEL_HIGH_THRESHOLD:
        level = RiskAssessment.LEVEL_HIGH
        recommendation = 'Schedule specialist review within 72 hours and monitor vitals daily.'
    elif score >= RISK_LEVEL_MEDIUM_THRESHOLD:
        level = RiskAssessment.LEVEL_MEDIUM
        recommendation = 'Initiate lifestyle intervention plan and reassess within 30 days.'
    else:
        level = RiskAssessment.LEVEL_LOW
        recommendation = 'Maintain preventive care and standard quarterly follow-up.'

    key_drivers = [
        {'factor': factor, 'impact': round(impact, 3)}
        for factor, impact in sorted(contributions.items(), key=lambda item: item[1], reverse=True)
        if impact > 0
    ][:KEY_DRIVERS_LIMIT]

    return {
        'risk_score': round(score, 2),
        'risk_level': level,
        'recommended_action': recommendation,
        'key_drivers': key_drivers,
    }
