#!/usr/bin/env python
"""A/B harness: Gemini vs local Ollama for generative AI enrichment.

Runs the three generative enrichment stages — visual condition (VLM), listing
sentiment, and deal verdict — for a sample of *real* properties across three
arms:

    * ``ollama``            — the current local baseline (from create_ai_client)
    * ``gemini-2.5-flash``  — best-quality Gemini candidate
    * ``gemini-2.5-flash-lite`` — cheapest / highest-quota, whole-DB candidate

Every arm sees the *same* locally-cached images (via ImageStore) and the *same*
prompts, so latency / JSON-validity / score deltas are directly comparable. No
production wiring or DB scores are mutated — this is an offline read-only
comparison that also answers "can we enrich the whole DB in one day?".

Embeddings are intentionally excluded (they stay on local bge-m3; see the
GeminiClient docstring).

Usage
-----
    GEMINI_API_KEY=... python scripts/dev/ab_gemini_vs_ollama.py \
        --limit 25 --out /path/to/report.md

    GEMINI_API_KEY=... python scripts/dev/ab_gemini_vs_ollama.py \
        --property-ids 1023,e4f...uuid

This calls the live Gemini API and spends real Tier-1 money.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Bootstrap sys.path so both `import adapters...` and config's `from src....`
# resolve regardless of how the script is invoked.
_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapters.ai.client import OllamaClient, _gemini_client_for, create_ai_client
from adapters.ai.image_store import ImageStore
from adapters.ai.prompts import (
    build_deal_verdict_prompt,
    build_sentiment_prompt,
    build_visual_condition_prompt,
)
from infra.config import get_config
from infra.db import SessionLocal

# Observed FREE-TIER requests-per-day caps (user's AI Studio dashboard, 2026-07-30).
# RPD is the binding constraint for a full backfill. Paid tiers are far higher —
# pass --rpd-cap to model a specific account. Confirm live values on the dashboard.
DOCUMENTED_RPD = {
    "gemini-2.5-flash": 20,
    "gemini-2.5-flash-lite": 20,
    "gemini-3-flash": 20,
    "gemini-3.5-flash": 20,
    "gemini-3.6-flash": 20,
    "gemini-3.1-flash-lite": 500,
    "gemini-3.5-flash-lite": 500,
    # Gemma (free tier: 30 RPM / 16K TPM / 14.4K RPD) — highest free RPD, but the
    # low 16K TPM is the real throttle for multi-image visual calls.
    "gemma-4-31b-it": 14_400,
    "gemma-4-26b-a4b-it": 14_400,
}
_DEFAULT_RPD = 20  # conservative free-tier fallback for unlisted models
_REQUESTS_PER_PROPERTY = 3  # visual + sentiment + verdict


@dataclass
class StageRecord:
    """One stage (visual/sentiment/verdict) result for one property + arm."""

    latency: float
    ok: bool  # True = model produced usable output; False = template/error fallback
    score: float | None = None
    category: str | None = None
    text: str = ""


@dataclass
class ArmStats:
    arm: str
    model: str
    visual: list[StageRecord] = field(default_factory=list)
    sentiment: list[StageRecord] = field(default_factory=list)
    verdict: list[StageRecord] = field(default_factory=list)
    request_count: int = 0
    retry_count: int = 0
    rate_limit_hits: int = 0
    last_error: str = ""


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _summary(records: list[StageRecord]) -> dict[str, float]:
    lats = [r.latency for r in records]
    return {
        "n": len(records),
        "p50": round(_pct(lats, 0.5), 2),
        "p95": round(_pct(lats, 0.95), 2),
        "mean": round(statistics.mean(lats), 2) if lats else 0.0,
        "fallback_rate": round(sum(0 if r.ok else 1 for r in records) / len(records), 3)
        if records
        else 0.0,
    }


@dataclass
class PropertySample:
    property_id: str
    public_id: str
    description: str
    image_urls: list[str]
    paths: list[str] = field(default_factory=list)


def _load_samples(ids: list[str] | None, limit: int) -> tuple[list[PropertySample], int]:
    """Return (samples, total_property_count) from the DB."""
    from sqlalchemy import func, or_

    from adapters.db.models import Property

    with SessionLocal() as session:
        total = session.query(func.count(Property.id)).scalar() or 0
        q = session.query(Property).filter(Property.image_urls.isnot(None))
        if ids:
            uuid_ids = [x for x in ids if not x.isdigit()]
            public_ids = [int(x) for x in ids if x.isdigit()]
            conds = []
            if uuid_ids:
                conds.append(Property.id.in_(uuid_ids))
            if public_ids:
                conds.append(Property.public_id.in_(public_ids))
            q = q.filter(or_(*conds)) if conds else q
        else:
            q = q.order_by(Property.first_seen.desc()).limit(limit)
        rows = q.all()
        samples = [
            PropertySample(
                property_id=str(r.id),
                public_id=str(r.public_id),
                description=r.description or "",
                image_urls=list(r.image_urls or []),
            )
            for r in rows
        ]
    return samples, int(total)


async def _run_one_property(client, sample: PropertySample, language: str) -> dict[str, StageRecord]:
    """Run visual -> sentiment -> verdict for one property (mirrors prod order)."""
    visual_prompt = build_visual_condition_prompt(len(sample.paths), output_language=language)
    sentiment_prompt = build_sentiment_prompt(
        sample.description,
        max_chars=get_config().ai.max_description_chars,
        output_language=language,
    )

    t0 = time.perf_counter()
    v = await client.analyze_visuals(sample.paths, visual_prompt)
    v_lat = time.perf_counter() - t0
    visual_rec = StageRecord(
        latency=v_lat,
        ok=v.analysis != "Error",
        score=v.condition_score,
        category=v.category,
        text=(v.reasoning or v.analysis)[:400],
    )

    t0 = time.perf_counter()
    s = await client.analyze_text(sample.description, sentiment_prompt)
    s_lat = time.perf_counter() - t0
    sentiment_rec = StageRecord(
        latency=s_lat,
        ok=s.analysis != "Error",
        score=s.sentiment_score,
        category=s.category,
        text=(s.reasoning or s.analysis)[:400],
    )

    t0 = time.perf_counter()
    d = await client.summarize_deal(
        stat_analysis={},
        visual=v.model_dump(),
        sentiment=s.model_dump(),
        neighborhood_name=None,
        output_language=language,
    )
    d_lat = time.perf_counter() - t0
    verdict_rec = StageRecord(
        latency=d_lat,
        ok=d.confidence > 0.0,  # confidence == 0.0 == deterministic template fallback
        score=d.confidence,
        text=d.verdict[:400],
    )

    return {"visual": visual_rec, "sentiment": sentiment_rec, "verdict": verdict_rec}


async def _run_arm(
    arm: str,
    model: str,
    client,
    samples: list[PropertySample],
    language: str,
    concurrency: int,
) -> ArmStats:
    stats = ArmStats(arm=arm, model=model)
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _guarded(sample: PropertySample) -> dict[str, StageRecord]:
        async with sem:
            return await _run_one_property(client, sample, language)

    async with client.session_context():
        results = await asyncio.gather(*[_guarded(s) for s in samples])

    for res in results:
        stats.visual.append(res["visual"])
        stats.sentiment.append(res["sentiment"])
        stats.verdict.append(res["verdict"])

    # Gemini arms expose observed-request counters for empirical quota headroom.
    stats.request_count = getattr(client, "request_count", 0)
    stats.retry_count = getattr(client, "retry_count", 0)
    stats.rate_limit_hits = getattr(client, "rate_limit_hits", 0)
    stats.last_error = getattr(client, "last_error", "")
    return stats


def _category_agreement(base: list[StageRecord], other: list[StageRecord]) -> float:
    pairs = [(b.category, o.category) for b, o in zip(base, other) if b.category and o.category]
    if not pairs:
        return 0.0
    return round(sum(1 for b, o in pairs if b == o) / len(pairs), 3)


def _score_delta(base: list[StageRecord], other: list[StageRecord]) -> dict[str, float]:
    deltas = [
        o.score - b.score
        for b, o in zip(base, other)
        if b.score is not None and o.score is not None
    ]
    if not deltas:
        return {"mean": 0.0, "mean_abs": 0.0}
    return {
        "mean": round(statistics.mean(deltas), 3),
        "mean_abs": round(statistics.mean([abs(d) for d in deltas]), 3),
    }


def _feasibility(model: str, total_properties: int, verdict_summary: dict, visual_summary: dict,
                 sentiment_summary: dict, concurrency: int, rpd_override: int | None = None) -> dict[str, Any]:
    rpd = rpd_override if rpd_override else DOCUMENTED_RPD.get(model, _DEFAULT_RPD)
    requests_needed = total_properties * _REQUESTS_PER_PROPERTY
    within_rpd = requests_needed <= rpd
    # Per-property wall time = sum of the three stage p50s (stages run sequentially
    # within a property); properties run `concurrency` at a time.
    per_property = visual_summary["p50"] + sentiment_summary["p50"] + verdict_summary["p50"]
    eta_seconds = (total_properties * per_property) / max(1, concurrency)
    eta_hours = round(eta_seconds / 3600, 2)
    return {
        "model": model,
        "approx_rpd_cap": rpd,
        "total_properties": total_properties,
        "requests_needed": requests_needed,
        "within_rpd": within_rpd,
        "per_property_p50_sec": round(per_property, 2),
        "eta_hours_at_concurrency": eta_hours,
        "concurrency": concurrency,
        "whole_db_in_one_day": bool(within_rpd and eta_hours < 24),
    }


def _build_report(
    total_properties: int,
    n_sample: int,
    arms: list[ArmStats],
    concurrency: int,
    rpd_override: int | None = None,
) -> tuple[str, dict]:
    baseline = next((a for a in arms if a.arm == "ollama"), arms[0])
    base_visual = baseline.visual
    base_sentiment = baseline.sentiment

    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_properties": total_properties,
        "sample_size": n_sample,
        "concurrency": concurrency,
        "arms": [],
        "feasibility": [],
    }

    lines: list[str] = []
    lines.append("# Gemini vs Ollama — AI enrichment A/B")
    lines.append("")
    lines.append(f"- Generated: {payload['generated_at']}")
    lines.append(f"- Sample size: **{n_sample}** properties (DB total: **{total_properties}**)")
    lines.append(f"- Gemini concurrency: {concurrency}")
    lines.append("")
    lines.append("## Per-arm results")
    lines.append("")
    lines.append(
        "| Arm | Stage | n | p50 (s) | p95 (s) | mean (s) | fallback | score Δ vs ollama | cat agree |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")

    for arm in arms:
        arm_payload = {"arm": arm.arm, "model": arm.model, "stages": {}}
        for stage_name, records, base_records in (
            ("visual", arm.visual, base_visual),
            ("sentiment", arm.sentiment, base_sentiment),
            ("verdict", arm.verdict, baseline.verdict),
        ):
            summ = _summary(records)
            is_base = arm.arm == baseline.arm
            delta = {"mean": 0.0, "mean_abs": 0.0} if is_base else _score_delta(base_records, records)
            agree = 1.0 if is_base else _category_agreement(base_records, records)
            arm_payload["stages"][stage_name] = {**summ, "score_delta": delta, "cat_agreement": agree}
            lines.append(
                f"| {arm.arm} | {stage_name} | {summ['n']} | {summ['p50']} | {summ['p95']} | "
                f"{summ['mean']} | {summ['fallback_rate']} | "
                f"{delta['mean']} (|{delta['mean_abs']}|) | {agree} |"
            )
        arm_payload["requests"] = {
            "request_count": arm.request_count,
            "retry_count": arm.retry_count,
            "rate_limit_hits": arm.rate_limit_hits,
        }
        payload["arms"].append(arm_payload)

    lines.append("")
    lines.append("## Observed request health (Gemini arms)")
    lines.append("")
    lines.append("| Arm | requests | retries | 429s | last error |")
    lines.append("|---|---|---|---|---|")
    for arm in arms:
        if arm.request_count:
            err = arm.last_error.replace("|", "\\|") if arm.last_error else "—"
            lines.append(
                f"| {arm.arm} | {arm.request_count} | {arm.retry_count} | "
                f"{arm.rate_limit_hits} | {err} |"
            )
    for arm in arms:
        if arm.last_error:
            lines.append("")
            lines.append(f"> **{arm.arm} fully failed** — every call fell back. Reason: `{arm.last_error}`")

    lines.append("")
    lines.append("## Full-backfill feasibility (whole DB in one day?)")
    lines.append("")
    lines.append(
        "| Model | approx RPD cap | reqs needed (3×P) | within RPD | per-prop p50 | ETA @ conc | 1-day? |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for arm in arms:
        if arm.arm == "ollama":
            continue
        vs = _summary(arm.visual)
        ss = _summary(arm.sentiment)
        ds = _summary(arm.verdict)
        feas = _feasibility(arm.model, total_properties, ds, vs, ss, concurrency, rpd_override)
        payload["feasibility"].append(feas)
        lines.append(
            f"| {feas['model']} | {feas['approx_rpd_cap']} | {feas['requests_needed']} | "
            f"{feas['within_rpd']} | {feas['per_property_p50_sec']}s | "
            f"{feas['eta_hours_at_concurrency']}h | "
            f"{'✅ yes' if feas['whole_db_in_one_day'] else '❌ no'} |"
        )
    lines.append("")
    lines.append(
        "> RPD caps are approximate documented Tier-1 values — confirm the live "
        "number in your AI Studio *Rate limits* dashboard."
    )

    # Side-by-side verdict/reasoning for the first few properties (manual quality read).
    lines.append("")
    lines.append("## Sample outputs (first 5 properties — manual quality read)")
    for i in range(min(5, n_sample)):
        lines.append("")
        lines.append(f"### Property {i + 1}")
        for arm in arms:
            v = arm.visual[i] if i < len(arm.visual) else None
            s = arm.sentiment[i] if i < len(arm.sentiment) else None
            d = arm.verdict[i] if i < len(arm.verdict) else None
            lines.append(f"- **{arm.arm}**")
            if v:
                lines.append(f"    - visual: `{v.category}` score={v.score} — {v.text}")
            if s:
                lines.append(f"    - sentiment: `{s.category}` score={s.score} — {s.text}")
            if d:
                lines.append(f"    - verdict: {d.text}")

    return "\n".join(lines) + "\n", payload


def _downscale_images(paths: list[str], max_px: int) -> list[str]:
    """Return copies of *paths* resized so the longest side is <= max_px.

    Resized JPEGs are written next to the originals under a ``_downscaled_{px}``
    sibling dir so the full-size cache is preserved for the other arm. Images
    already within the limit are copied as-is.
    """
    from PIL import Image

    out: list[str] = []
    for p in paths:
        src = Path(p)
        dest_dir = src.parent / f"_downscaled_{max_px}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / (src.stem + ".jpg")
        if not dest.exists():
            try:
                with Image.open(src) as im:
                    im = im.convert("RGB")
                    w, h = im.size
                    if max(w, h) > max_px:
                        scale = max_px / max(w, h)
                        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
                    im.save(dest, "JPEG", quality=85)
            except Exception:
                out.append(p)  # fall back to original on any decode error
                continue
        out.append(str(dest))
    return out


async def _amain(args: argparse.Namespace) -> int:
    cfg = get_config()
    api_key = cfg.ai.gemini_api_key
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set (put it in .env.local or the env).")
        return 2

    ids = [x.strip() for x in args.property_ids.split(",") if x.strip()] if args.property_ids else None
    samples, total = _load_samples(ids, args.limit)
    if not samples:
        print("ERROR: no properties with images matched the selection.")
        return 2

    # Shared image cache — download once, both arms read identical bytes.
    store = ImageStore()
    for sample in samples:
        sample.paths = await store.download_images(
            sample.property_id, sample.image_urls, max_images=cfg.ai.max_images_per_property
        )
    samples = [s for s in samples if s.paths]
    if not samples:
        print("ERROR: no images could be downloaded for the selected properties.")
        return 2

    if args.downscale:
        for sample in samples:
            sample.paths = _downscale_images(sample.paths, args.downscale)
        print(f"Downscaled images to <= {args.downscale}px longest side.")

    print(f"Prepared {len(samples)} properties (DB total {total}). Running arms...")

    gemini_models = [m.strip() for m in args.gemini_models.split(",") if m.strip()]

    arms: list[ArmStats] = []

    # Baseline: local Ollama (sequential — one GPU request at a time).
    ollama = create_ai_client()
    if not isinstance(ollama, OllamaClient):
        print("WARNING: configured backend is not Ollama; baseline arm uses cfg.ai.backend anyway.")
    arms.append(await _run_arm("ollama", cfg.ai.visual_model, ollama, samples, args.language, 1))
    await ollama.close()

    for model in gemini_models:
        client = _gemini_client_for(
            model, api_key=api_key, base_url=cfg.ai.gemini_url, timeout=cfg.ai.timeout
        )
        arms.append(await _run_arm(model, model, client, samples, args.language, args.concurrency))
        await client.close()

    report_md, payload = _build_report(total, len(samples), arms, args.concurrency, args.rpd_cap)

    out = args.out
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(report_md)
    with open(out.rsplit(".", 1)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    print(report_md)
    print(f"\nReport written to {out} (+ .json)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--property-ids", help="Comma-separated public_ids or UUIDs (overrides --limit).")
    parser.add_argument("--limit", type=int, default=25, help="Sample size when --property-ids is omitted.")
    parser.add_argument(
        "--gemini-models",
        default="gemini-2.5-flash,gemini-2.5-flash-lite",
        help="Comma-separated Gemini models to test as arms.",
    )
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrent properties per Gemini arm (use 1 on free tier — 5-15 RPM).")
    parser.add_argument("--rpd-cap", type=int, default=None, help="Override RPD in the feasibility calc (e.g. after upgrading to a paid tier).")
    parser.add_argument("--downscale", type=int, default=0, help="Resize images to this longest-side px before analysis (0 = full size).")
    parser.add_argument("--language", default="en", help="output_language for prompts (en | pt-BR).")
    parser.add_argument(
        "--out",
        default="/tmp/claude-1000/-home-felipe-workfolder-imoveis/"
        "323ed479-4d7c-47dc-8f77-a146d5594ac6/scratchpad/gemini_ab_report.md",
        help="Markdown report path (a .json sibling is also written).",
    )
    args = parser.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
