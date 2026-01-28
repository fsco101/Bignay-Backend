from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Recommendation:
    primary: str
    alternatives: list[str]
    reason: str


def recommend(*, ripeness_stage: str | None, mold_present: bool, quality: str | None) -> Recommendation:
    # Safety-first default policy
    if mold_present:
        return Recommendation(
            primary="discard",
            alternatives=[],
            reason="Mold detected; not recommended for consumption or processing.",
        )

    if quality == "reject":
        return Recommendation(
            primary="discard",
            alternatives=[],
            reason="Quality assessment indicates rejection.",
        )

    if ripeness_stage == "unripe":
        return Recommendation(
            primary="vinegar",
            alternatives=["wine"],
            reason="Unripe fruit is typically better for acidic/fermented processing than eating fresh.",
        )

    if ripeness_stage == "ripe":
        return Recommendation(
            primary="eat",
            alternatives=["wine", "jam"],
            reason="Ripe fruit is generally suitable to eat fresh; also good for wine/jam.",
        )

    if ripeness_stage == "overripe":
        return Recommendation(
            primary="jam",
            alternatives=["wine", "vinegar"],
            reason="Overripe fruit is usually best processed soon (jam/wine/vinegar).",
        )

    return Recommendation(
        primary="unknown",
        alternatives=[],
        reason="Not enough information to recommend a use.",
    )
