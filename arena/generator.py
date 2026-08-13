"""Adaptive mutation-plan generator with a deterministic offline fallback."""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

from .synthetic import ALLOWED_MUTATIONS, MutationPlan


def default_state() -> dict[str, Any]:
    return {
        "schema": 1,
        "round": 0,
        "weights": {name: 1.0 for name in sorted(ALLOWED_MUTATIONS)},
        "seen_signatures": [],
        "history": [],
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_state()
    state = json.loads(path.read_text(encoding="utf-8"))
    defaults = default_state()
    defaults.update(state)
    for name in ALLOWED_MUTATIONS:
        defaults["weights"].setdefault(name, 1.0)
    return defaults


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def update_strategy(
    state: dict[str, Any], evaluations: list[dict[str, Any]]
) -> None:
    """Reward validator misses so later rounds explore those families harder."""
    weights = state["weights"]
    for item in evaluations:
        caught = bool(item["caught"])
        factor = 0.92 if caught else 1.35
        for mutation in item["mutations"]:
            weights[mutation] = round(
                min(8.0, max(0.25, float(weights.get(mutation, 1.0)) * factor)),
                4,
            )
        signature = str(item["signature"])
        if signature not in state["seen_signatures"]:
            state["seen_signatures"].append(signature)
    state["history"].append(
        {
            "round": state["round"],
            "caught": sum(bool(item["caught"]) for item in evaluations),
            "missed": sum(not bool(item["caught"]) for item in evaluations),
        }
    )
    state["history"] = state["history"][-100:]


def _weighted_choice(
    rng: random.Random, names: list[str], weights: dict[str, float]
) -> str:
    return rng.choices(names, weights=[weights[name] for name in names], k=1)[0]


def offline_plans(
    state: dict[str, Any], count: int, seed: int
) -> list[MutationPlan]:
    """Keep the arena useful before a Cursor API key is configured."""
    rng = random.Random(seed)
    names = sorted(ALLOWED_MUTATIONS)
    seen = set(state["seen_signatures"])
    plans: list[MutationPlan] = []
    attempts = 0
    while len(plans) < count and attempts < count * 30:
        attempts += 1
        max_size = min(3, len(names))
        size = rng.choices(range(1, max_size + 1), weights=[5, 3, 1], k=1)[0]
        selected: list[str] = []
        while len(selected) < size:
            choice = _weighted_choice(rng, names, state["weights"])
            if choice not in selected:
                selected.append(choice)
        plan = MutationPlan(tuple(sorted(selected)), label="offline-evolution")
        if plan.signature in {item.signature for item in plans}:
            continue
        # Prefer novelty but permit a replay when the combination space is small.
        if plan.signature in seen and rng.random() < 0.7:
            continue
        plans.append(plan)
    if not plans:
        plans.append(MutationPlan((names[seed % len(names)],), "offline-fallback"))
    return plans


def _extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("generator returned no JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("generator response must be an object")
    return value


def sdk_plans(
    repo_root: Path,
    state: dict[str, Any],
    count: int,
    model: str,
    prompt_template: str,
) -> list[MutationPlan]:
    """Ask a tool-less agent to choose only whitelisted structural mutations."""
    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

    prompt = prompt_template.format(
        count=count,
        allowed=json.dumps(sorted(ALLOWED_MUTATIONS), ensure_ascii=False),
        state=json.dumps(state, ensure_ascii=False),
    )
    options = AgentOptions(
        api_key=os.environ["CURSOR_API_KEY"],
        model=model,
        name="pdf-arena-generator",
        local=LocalAgentOptions(cwd=repo_root),
        tools=[],
    )
    result = Agent.prompt(prompt, options)
    if str(result.status).lower().split(".")[-1] != "finished":
        raise RuntimeError(f"generator run failed: {result.status}")
    payload = _extract_json(result.result)
    raw_plans = payload.get("plans")
    if not isinstance(raw_plans, list):
        raise ValueError("generator response has no plans array")

    plans: list[MutationPlan] = []
    for raw in raw_plans[:count]:
        if not isinstance(raw, dict) or not isinstance(raw.get("mutations"), list):
            continue
        plan = MutationPlan(
            tuple(str(item) for item in raw["mutations"]),
            str(raw.get("label") or "agent-evolution")[:120],
        )
        if plan.signature not in {item.signature for item in plans}:
            plans.append(plan)
    if not plans:
        raise ValueError("generator returned no valid plans")
    return plans
