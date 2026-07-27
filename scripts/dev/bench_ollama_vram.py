#!/usr/bin/env python3
"""Benchmark Ollama VRAM / system-RAM for AI enrichment payloads.

Uses a real property's image URLs from the local DB (read-only SELECT),
downloads up to N images, then runs generate matrix cases:

  A — num_ctx=16384, 8 images, 1 concurrent generate (serial visual then text)
  B — num_ctx=16384, 8 images, 2 concurrent generates (visual+text gather)
  C — num_ctx=8192,  8 images, 1 concurrent generate
  D — num_ctx=16384, 8 images, 2 concurrent *property* payloads
      (requires OLLAMA_NUM_PARALLEL>=2 on the host)

Samples during each case:
  - Ollama GET /api/ps  → size / size_vram (bytes)
  - Optional Windows GPU dedicated adapter memory via powershell
  - Ollama process WorkingSet (Windows)

No DB writes. Does not drop data.

Examples::

  PYTHONPATH=src python scripts/dev/bench_ollama_vram.py
  PYTHONPATH=src python scripts/dev/bench_ollama_vram.py --cases A,C --ollama-url http://host.docker.internal:11434
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

import httpx

DEFAULT_MODEL = "qwen2.5vl:7b"
DEFAULT_IMAGES = 8
POLL_INTERVAL_SEC = 0.5


@dataclass
class MemSample:
    t: float
    size_vram_mb: float
    size_mb: float
    gpu_dedicated_mb: Optional[float] = None
    ollama_ws_mb: Optional[float] = None


@dataclass
class CaseResult:
    case: str
    num_ctx: int
    images: int
    concurrent_generates: int
    duration_sec: float
    peak_size_vram_mb: float
    peak_size_mb: float
    peak_gpu_dedicated_mb: Optional[float]
    peak_ollama_ws_mb: Optional[float]
    spill_mb: float  # size - size_vram (system/CPU offload estimate)
    ok: bool
    error: Optional[str] = None
    samples: List[MemSample] = field(default_factory=list)


def _resolve_ollama_url(cli: Optional[str]) -> str:
    if cli:
        return cli.rstrip("/")

    def _windows_host_url() -> Optional[str]:
        try:
            out = subprocess.check_output(
                ["ip", "route", "show", "default"], text=True, timeout=2
            )
            parts = out.split()
            if "via" in parts:
                return f"http://{parts[parts.index('via') + 1]}:11434"
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            return None
        return None

    for key in ("OLLAMA_HOST", "OLLAMA_BASE_URL"):
        val = os.environ.get(key)
        if not val:
            continue
        host = val.rstrip("/")
        # Ollama may advertise 0.0.0.0 / localhost — clients need a routable host.
        if any(x in host for x in ("0.0.0.0", "127.0.0.1", "localhost")):
            routed = _windows_host_url()
            if routed:
                return routed
            continue
        return host

    routed = _windows_host_url()
    if routed:
        return routed
    # Docker Compose workers use this alias to the Windows host.
    return "http://host.docker.internal:11434"


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # Host-side default from .env.local compose mapping
    return "postgresql://imoveis:imoveis_local_dev@127.0.0.1:5433/realestate"


def _fetch_property_urls(limit_images: int) -> tuple[str, List[str], str]:
    """Return (property_id, image_urls[:N], description) via read-only SQL."""
    import psycopg2

    conn = psycopg2.connect(_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, image_urls, COALESCE(description, '')
                FROM properties
                WHERE active IS TRUE
                  AND image_urls IS NOT NULL
                  AND jsonb_typeof(to_jsonb(image_urls)) = 'array'
                  AND jsonb_array_length(to_jsonb(image_urls)) >= %s
                ORDER BY random()
                LIMIT 1
                """,
                (limit_images,),
            )
            row = cur.fetchone()
            if not row:
                raise SystemExit(f"No active property with ≥{limit_images} image_urls")
            prop_id, raw_urls, description = row
            if isinstance(raw_urls, str):
                urls = json.loads(raw_urls)
            else:
                urls = list(raw_urls)
            urls = [u for u in urls if isinstance(u, str) and u.startswith("http")][
                :limit_images
            ]
            if len(urls) < limit_images:
                raise SystemExit(
                    f"Property {prop_id} had only {len(urls)} http image URLs"
                )
            return prop_id, urls, description or ""
    finally:
        conn.close()


async def _download_images(urls: Sequence[str], dest: Path) -> List[Path]:
    paths: List[Path] = []
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        for i, url in enumerate(urls):
            ext = Path(urlparse(url).path).suffix.lower() or ".jpg"
            if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                ext = ".jpg"
            path = dest / f"img_{i:02d}{ext}"
            resp = await client.get(url)
            resp.raise_for_status()
            path.write_bytes(resp.content)
            paths.append(path)
    return paths


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _windows_mem() -> tuple[Optional[float], Optional[float]]:
    """Return (gpu_dedicated_mb, ollama_ws_mb) via powershell, or (None, None)."""
    ps = r"""
$gpu = $null
try {
  $samples = (Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction Stop).CounterSamples
  $gpu = ($samples | Measure-Object -Property CookedValue -Maximum).Maximum / 1MB
} catch {}
$ws = $null
try {
  $ws = (Get-Process ollama -ErrorAction Stop | Measure-Object WorkingSet64 -Sum).Sum / 1MB
} catch {}
Write-Output ("{0}|{1}" -f ($(if ($null -eq $gpu) {''} else {[math]::Round($gpu,1)}), $(if ($null -eq $ws) {''} else {[math]::Round($ws,1)})))
"""
    try:
        out = subprocess.check_output(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            text=True,
            timeout=15,
            stderr=subprocess.DEVNULL,
        ).strip()
        parts = out.split("|")
        gpu = float(parts[0]) if parts and parts[0] else None
        ws = float(parts[1]) if len(parts) > 1 and parts[1] else None
        return gpu, ws
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, None


async def _ollama_ps(client: httpx.AsyncClient, base: str) -> tuple[float, float]:
    r = await client.get(f"{base}/api/ps")
    r.raise_for_status()
    models = r.json().get("models") or []
    size = sum(float(m.get("size") or 0) for m in models) / (1024 * 1024)
    size_vram = sum(float(m.get("size_vram") or 0) for m in models) / (1024 * 1024)
    return size_vram, size


async def _sample_loop(
    client: httpx.AsyncClient,
    base: str,
    stop: asyncio.Event,
    samples: List[MemSample],
    t0: float,
) -> None:
    while not stop.is_set():
        try:
            size_vram, size = await _ollama_ps(client, base)
            gpu, ws = await asyncio.to_thread(_windows_mem)
            samples.append(
                MemSample(
                    t=time.time() - t0,
                    size_vram_mb=round(size_vram, 1),
                    size_mb=round(size, 1),
                    gpu_dedicated_mb=gpu,
                    ollama_ws_mb=ws,
                )
            )
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_SEC)
        except asyncio.TimeoutError:
            continue


async def _generate(
    client: httpx.AsyncClient,
    base: str,
    *,
    model: str,
    prompt: str,
    images: Optional[List[str]],
    num_ctx: int,
    num_predict: int = 256,
) -> None:
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": num_ctx, "num_predict": num_predict},
    }
    if images is not None:
        payload["images"] = images
    r = await client.post(f"{base}/api/generate", json=payload, timeout=300.0)
    if r.status_code != 200:
        raise RuntimeError(f"generate HTTP {r.status_code}: {r.text[:400]}")


async def _run_case(
    *,
    case: str,
    base: str,
    model: str,
    num_ctx: int,
    image_b64: List[str],
    description: str,
    concurrent_generates: int,
    dual_property: bool = False,
) -> CaseResult:
    visual_prompt = (
        f"Return JSON only: {{\"condition_score\":0.5,\"category\":\"Average\","
        f"\"reasoning\":\"bench\",\"features_detected\":[],\"issues_detected\":[]}}. "
        f"You see {len(image_b64)} property photos."
    )
    text_prompt = (
        "Return JSON only: {\"sentiment_score\":0.5,\"category\":\"Average\","
        "\"reasoning\":\"bench\",\"green_flags\":[],\"red_flags\":[]}.\n\n"
        f"Description: {description[:800] or 'Apartment in Belo Horizonte near Savassi.'}"
    )

    samples: List[MemSample] = []
    stop = asyncio.Event()
    t0 = time.time()
    error: Optional[str] = None
    ok = True

    async with httpx.AsyncClient(timeout=60.0) as client:
        sampler = asyncio.create_task(_sample_loop(client, base, stop, samples, t0))
        try:
            # Warm / load model once before peak sampling window
            await _generate(
                client,
                base,
                model=model,
                prompt="Reply with ok",
                images=None,
                num_ctx=min(num_ctx, 2048),
                num_predict=8,
            )
            samples.clear()
            t0 = time.time()

            if dual_property:
                # Two full visual payloads at once (semaphore=2 ceiling probe)
                await asyncio.gather(
                    _generate(
                        client,
                        base,
                        model=model,
                        prompt=visual_prompt + " [propA]",
                        images=image_b64,
                        num_ctx=num_ctx,
                    ),
                    _generate(
                        client,
                        base,
                        model=model,
                        prompt=visual_prompt + " [propB]",
                        images=image_b64,
                        num_ctx=num_ctx,
                    ),
                )
            elif concurrent_generates >= 2:
                await asyncio.gather(
                    _generate(
                        client,
                        base,
                        model=model,
                        prompt=visual_prompt,
                        images=image_b64,
                        num_ctx=num_ctx,
                    ),
                    _generate(
                        client,
                        base,
                        model=model,
                        prompt=text_prompt,
                        images=None,
                        num_ctx=num_ctx,
                    ),
                )
            else:
                await _generate(
                    client,
                    base,
                    model=model,
                    prompt=visual_prompt,
                    images=image_b64,
                    num_ctx=num_ctx,
                )
                await _generate(
                    client,
                    base,
                    model=model,
                    prompt=text_prompt,
                    images=None,
                    num_ctx=num_ctx,
                )
        except Exception as exc:
            ok = False
            error = str(exc)
        finally:
            stop.set()
            await sampler

    duration = time.time() - t0
    peak_vram = max((s.size_vram_mb for s in samples), default=0.0)
    peak_size = max((s.size_mb for s in samples), default=0.0)
    peak_gpu = None
    gpu_vals = [s.gpu_dedicated_mb for s in samples if s.gpu_dedicated_mb is not None]
    if gpu_vals:
        peak_gpu = max(gpu_vals)
    peak_ws = None
    ws_vals = [s.ollama_ws_mb for s in samples if s.ollama_ws_mb is not None]
    if ws_vals:
        peak_ws = max(ws_vals)
    spill = max(0.0, peak_size - peak_vram)

    return CaseResult(
        case=case,
        num_ctx=num_ctx,
        images=len(image_b64),
        concurrent_generates=concurrent_generates,
        duration_sec=round(duration, 2),
        peak_size_vram_mb=round(peak_vram, 1),
        peak_size_mb=round(peak_size, 1),
        peak_gpu_dedicated_mb=round(peak_gpu, 1) if peak_gpu is not None else None,
        peak_ollama_ws_mb=round(peak_ws, 1) if peak_ws is not None else None,
        spill_mb=round(spill, 1),
        ok=ok,
        error=error,
        samples=samples,
    )


def _parse_cases(raw: str) -> List[str]:
    allowed = {"A", "B", "C", "D"}
    cases = [c.strip().upper() for c in raw.split(",") if c.strip()]
    bad = [c for c in cases if c not in allowed]
    if bad:
        raise SystemExit(f"Unknown cases {bad}; allowed {sorted(allowed)}")
    return cases


async def _amain(args: argparse.Namespace) -> int:
    base = _resolve_ollama_url(args.ollama_url)
    cases = _parse_cases(args.cases)
    n_images = args.images

    print(f"Ollama URL: {base}")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            tags = await client.get(f"{base}/api/tags")
            tags.raise_for_status()
        except Exception as exc:
            print(f"ERROR: cannot reach Ollama at {base}: {exc}", file=sys.stderr)
            return 2

    prop_id, urls, description = _fetch_property_urls(n_images)
    print(f"Property: {prop_id} ({len(urls)} images)")

    with tempfile.TemporaryDirectory(prefix="ollama_vram_") as tmp:
        dest = Path(tmp)
        print("Downloading images…")
        paths = await _download_images(urls, dest)
        image_b64 = [_b64(p) for p in paths]
        print(f"Encoded {len(image_b64)} images ({sum(len(x) for x in image_b64)//1024} KB b64)")

        results: List[CaseResult] = []
        specs = {
            "A": dict(num_ctx=16384, concurrent_generates=1, dual_property=False),
            "B": dict(num_ctx=16384, concurrent_generates=2, dual_property=False),
            "C": dict(num_ctx=8192, concurrent_generates=1, dual_property=False),
            "D": dict(num_ctx=16384, concurrent_generates=2, dual_property=True),
        }
        for case in cases:
            print(f"\n=== Case {case} {specs[case]} ===")
            if case == "D":
                print(
                    "NOTE: Case D needs OLLAMA_NUM_PARALLEL>=2 on the host; "
                    "otherwise the second request will queue serially."
                )
            res = await _run_case(
                case=case,
                base=base,
                model=args.model,
                image_b64=image_b64,
                description=description,
                **specs[case],
            )
            results.append(res)
            print(json.dumps({k: v for k, v in asdict(res).items() if k != "samples"}, indent=2))

        summary = [{k: v for k, v in asdict(r).items() if k != "samples"} for r in results]
        out_path = Path(args.output) if args.output else None
        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(summary, indent=2) + "\n")
            print(f"\nWrote {out_path}")

        print("\n=== Summary ===")
        print(
            f"{'case':4} {'ctx':>5} {'conc':>4} {'vram':>8} {'size':>8} "
            f"{'spill':>7} {'gpu':>8} {'ws':>8} {'sec':>7} ok"
        )
        for r in results:
            print(
                f"{r.case:4} {r.num_ctx:5d} {r.concurrent_generates:4d} "
                f"{r.peak_size_vram_mb:8.1f} {r.peak_size_mb:8.1f} "
                f"{r.spill_mb:7.1f} "
                f"{(r.peak_gpu_dedicated_mb if r.peak_gpu_dedicated_mb is not None else float('nan')):8.1f} "
                f"{(r.peak_ollama_ws_mb if r.peak_ollama_ws_mb is not None else float('nan')):8.1f} "
                f"{r.duration_sec:7.1f} {r.ok}"
            )

        # Recommendation heuristic: stay under ~16 GB VRAM with spill < 1 GB
        safe = [r for r in results if r.ok and r.spill_mb < 1024 and r.peak_size_vram_mb <= 16000]
        if any(r.case == "D" and r in safe for r in results):
            print("\nRecommendation: semaphore_limit=2 viable (case D under budget).")
        elif any(r.case == "A" and r in safe for r in results):
            print("\nRecommendation: keep semaphore_limit=1; serialize visual→text (case A safe).")
        else:
            print(
                "\nRecommendation: if A spills, drop num_ctx to 8192 (case C) "
                "and keep concurrency=1."
            )
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ollama-url", default=None, help="Ollama base URL")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--images", type=int, default=DEFAULT_IMAGES)
    p.add_argument("--cases", default="A,B,C,D", help="Comma-separated cases")
    p.add_argument(
        "--output",
        default="data/bench/ollama_vram_results.json",
        help="JSON summary path (relative to cwd)",
    )
    args = p.parse_args()
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
