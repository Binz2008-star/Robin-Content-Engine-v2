from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .highlight_features import TimeWindow, normalize_signal


@dataclass(frozen=True)
class ScoringConfig:
    """V1 evidence-traceable baseline.

    base_activity_score = audio_weight * audio_score + motion_weight * motion_score
    preserves only AutoShorts' broad "audio + video fusion" hypothesis
    (they used 0.6/0.4 for the same two signal families), not its GPU
    implementation or its exact constants beyond that one ratio.

    Scene-change density is deliberately NOT a third equally-weighted
    primary signal: fast cuts also occur at menus, respawns, and loading
    screens, which are not highlights. It is a small, capped bonus -
    scene_bonus_weight/scene_bonus_cap keep its maximum contribution well
    below either primary signal's weight, so it can nudge but never
    dominate the ranking.
    """

    audio_weight: float = 0.60
    motion_weight: float = 0.40
    scene_bonus_weight: float = 0.10
    scene_bonus_cap: float = 0.10
    reason_high_threshold: float = 0.66


@dataclass(frozen=True)
class WindowScore:
    window: TimeWindow
    final_score: float
    audio_score: float
    motion_score: float
    scene_signal: float
    reason: str


def _describe_reason(
    audio_score: float,
    motion_score: float,
    scene_signal: float,
    high_threshold: float,
) -> str:
    """Deterministic, signal-derived description - never an LLM call."""
    parts: list[str] = []
    if audio_score >= high_threshold:
        parts.append("high audio spike")
    if motion_score >= high_threshold:
        parts.append("high motion")
    if scene_signal >= high_threshold:
        parts.append("scene-cut cluster")
    if not parts:
        parts.append("moderate activity")
    return " + ".join(parts)


def score_windows(
    windows: Sequence[TimeWindow],
    raw_audio_rms: Sequence[float],
    raw_audio_flux: Sequence[float],
    raw_motion: Sequence[float],
    raw_scene_density: Sequence[float],
    config: ScoringConfig | None = None,
) -> list[WindowScore]:
    config = config or ScoringConfig()
    lengths = {
        len(windows),
        len(raw_audio_rms),
        len(raw_audio_flux),
        len(raw_motion),
        len(raw_scene_density),
    }
    if len(lengths) > 1:
        raise ValueError("All signal lists must have the same length as windows")
    if not windows:
        return []

    audio_rms_n = normalize_signal(raw_audio_rms)
    audio_flux_n = normalize_signal(raw_audio_flux)
    motion_n = normalize_signal(raw_motion)
    scene_n = normalize_signal(raw_scene_density)

    results: list[WindowScore] = []
    for i, w in enumerate(windows):
        # RMS and spectral flux are both legitimate audio-energy signals with
        # no prior evidence favoring one over the other, so they're combined
        # equally into a single audio_score before the primary fusion.
        audio_score = 0.5 * audio_rms_n[i] + 0.5 * audio_flux_n[i]
        motion_score = motion_n[i]
        scene_signal = scene_n[i]

        base_activity_score = (
            config.audio_weight * audio_score + config.motion_weight * motion_score
        )
        scene_bonus = min(config.scene_bonus_cap, config.scene_bonus_weight * scene_signal)
        final_score = base_activity_score + scene_bonus

        results.append(
            WindowScore(
                window=w,
                final_score=final_score,
                audio_score=audio_score,
                motion_score=motion_score,
                scene_signal=scene_signal,
                reason=_describe_reason(
                    audio_score, motion_score, scene_signal, config.reason_high_threshold
                ),
            )
        )
    return results
