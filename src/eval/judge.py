"""LLM-as-judge evidence-faithfulness grading and human calibration."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, Field, ValidationError

from src.systems.llm_client import LLMClient
from src.systems.schema import Hypothesis

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CALIBRATION_PATH = PROJECT_ROOT / "data" / "judge_calibration.json"

RUBRIC = """Evidence-faithfulness rubric (assign exactly one integer score):
1 — The narrative is contradicted by, or unrelated to, the cited numbers and does not disclose limitations.
2 — The narrative has weak numerical support, makes major unsupported causal leaps, or omits major unresolved alternatives.
3 — The narrative partially follows from the cited numbers but contains a material gap, ambiguity, or incomplete limitation disclosure.
4 — The narrative follows from the cited numbers with only minor gaps and discloses the important factors it could not rule out.
5 — The narrative is fully supported by the cited numbers, clearly separates observation from inference, and explicitly discloses what it could not rule out.
"""


class JudgeScore(BaseModel):
    """Validated qualitative grade for one answer."""

    score: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=1)


class JudgeHumanAgreement(BaseModel):
    """Calibration summary over paired human and judge labels."""

    sample_count: int = Field(ge=0)
    exact_match_rate: float = Field(ge=0.0, le=1.0)
    pearson_correlation: float = Field(ge=-1.0, le=1.0)


def build_grading_prompt(symptom: str, hypothesis: Hypothesis) -> str:
    """Create the fixed single-answer grading prompt."""
    return f"""You are grading one root-cause answer for evidence faithfulness.

{RUBRIC}
Evaluate both requirements: (1) does the narrative follow from its cited numbers, and
(2) does it disclose what the analysis could not rule out? Do not reward eloquence.

Symptom:
{symptom}

Answer to grade:
{hypothesis.model_dump_json(indent=2)}

Return JSON only: {{"score": <integer 1-5>, "rationale": "<specific explanation>"}}.
"""


def judge_answer(
    client: LLMClient, symptom: str, hypothesis: Hypothesis
) -> JudgeScore:
    """Grade one hypothesis through the shared LLM client and validate its result."""
    raw = client.complete(build_grading_prompt(symptom, hypothesis), temperature=0)
    text = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        return JudgeScore.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("Judge output was not valid score/rationale JSON.") from exc


def _pearson(left: list[int], right: list[int]) -> float:
    if len(left) < 2:
        return 0.0
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_ss = sum((a - left_mean) ** 2 for a in left)
    right_ss = sum((b - right_mean) ** 2 for b in right)
    denominator = math.sqrt(left_ss * right_ss)
    return numerator / denominator if denominator else 0.0


def judge_human_agreement(
    client: LLMClient | None = None,
    calibration_path: Path = DEFAULT_CALIBRATION_PATH,
) -> JudgeHumanAgreement:
    """Compare judge labels with reserved human labels.

    Without a client, this uses checked stub judge labels. Passing a client recomputes
    judge scores from the stored symptoms/answers, which is the path for real calibration.
    """
    rows = json.loads(Path(calibration_path).read_text(encoding="utf-8"))
    human_scores: list[int] = []
    judge_scores: list[int] = []
    for row in rows:
        human_scores.append(int(row["human_score"]))
        if client is None:
            judge_scores.append(int(row["stub_judge_score"]))
        else:
            hypothesis = Hypothesis.model_validate(row["hypothesis"])
            judge_scores.append(judge_answer(client, row["symptom"], hypothesis).score)
    exact = (
        sum(a == b for a, b in zip(human_scores, judge_scores)) / len(rows)
        if rows
        else 0.0
    )
    return JudgeHumanAgreement(
        sample_count=len(rows),
        exact_match_rate=exact,
        pearson_correlation=_pearson(human_scores, judge_scores),
    )

