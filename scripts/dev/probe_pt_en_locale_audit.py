#!/usr/bin/env python3
"""BIN-97 probe: PT listing corpus vs EN AI / semantic search (bge-m3).

Measures (no product writes):
  1. Cross-lingual cosine rank — fixture PT listings vs paired PT/EN queries.
  2. Sentiment enrichment language — PT ads → category/flags language.
  3. Optional live DB ``q=`` anecdotes when DATABASE_URL is set and embeddings exist.

Usage (from repo root, Ollama reachable)::

    export OLLAMA_HOST=http://$(ip route show default | awk '/default/{print $3}'):11434
    PYTHONPATH=src .venv/bin/python scripts/dev/probe_pt_en_locale_audit.py
    PYTHONPATH=src .venv/bin/python scripts/dev/probe_pt_en_locale_audit.py --db
    PYTHONPATH=src .venv/bin/python scripts/dev/probe_pt_en_locale_audit.py --normalize
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

# ---------------------------------------------------------------------------
# Fixture corpus (PT listing title+description) + expected-relevant queries
# ---------------------------------------------------------------------------

CORPUS: list[dict[str, str]] = [
    {
        "id": "savassi_metro",
        "text": (
            "Apartamento 2 quartos em Savassi\n"
            "Apartamento de 2 quartos em Savassi, 75m², bem localizado, "
            "próximo a restaurantes e shoppings. Prédio com portaria 24h, "
            "piscina e academia. Imóvel bem conservado, recém-pintado. "
            "Perto do metrô."
        ),
    },
    {
        "id": "reforma_urgente",
        "text": (
            "Casa antiga precisa reforma\n"
            "Casa antiga em bairro afastado, precisa de reforma geral. "
            "Telhado com infiltração, pintura descascada, piso danificado. "
            "Sem garagem, rua sem asfalto. Venda urgente. Área de alagamento."
        ),
    },
    {
        "id": "cobertura_luxo",
        "text": (
            "Cobertura duplex alto padrão\n"
            "Cobertura duplex de alto padrão, 200m², 3 suítes, vista "
            "panorâmica. Acabamento em mármore, cozinha planejada, "
            "4 vagas de garagem. Condomínio com piscina aquecida."
        ),
    },
    {
        "id": "kitnet_centro",
        "text": (
            "Kitnet estudante centro\n"
            "Kitnet pequena no centro, 25m², ideal para estudante. "
            "Prédio simples sem elevador. Imóvel funcional mas compacto. "
            "Banheiro pequeno, sem vaga de garagem."
        ),
    },
    {
        "id": "sobrado_quintal",
        "text": (
            "Sobrado 3 quartos com quintal\n"
            "Sobrado médio em bairro residencial, 3 quartos, "
            "120m², garagem para 2 carros. Casa arejada com quintal. "
            "Precisa de pequenos reparos na pintura externa."
        ),
    },
]

# Each pair: EN query + PT equivalent; ``relevant`` = corpus id that should rank #1.
QUERY_PAIRS: list[dict[str, str]] = [
    {
        "en": "apartment near metro with doorman",
        "pt": "apartamento perto do metrô com portaria",
        "relevant": "savassi_metro",
    },
    {
        "en": "house needing renovation flood area",
        "pt": "casa precisa reforma área de alagamento",
        "relevant": "reforma_urgente",
    },
    {
        "en": "luxury duplex penthouse with garage",
        "pt": "cobertura duplex alto padrão com garagem",
        "relevant": "cobertura_luxo",
    },
    {
        "en": "small studio for student no parking",
        "pt": "kitnet pequena para estudante sem garagem",
        "relevant": "kitnet_centro",
    },
    {
        "en": "townhouse with backyard and garage",
        "pt": "sobrado com quintal e garagem",
        "relevant": "sobrado_quintal",
    },
]

_PT_CHARS = re.compile(r"[àáãâéêíóôõúçÀÁÃÂÉÊÍÓÔÕÚÇ]")
_EN_CATEGORY = {
    "Highly Desirable",
    "Good",
    "Average",
    "Undesirable",
    "Poor",
}


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _rank(query_vec: list[float], corpus_vecs: dict[str, list[float]]) -> list[tuple[str, float]]:
    scored = [(cid, _cosine(query_vec, vec)) for cid, vec in corpus_vecs.items()]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _looks_english_flags(flags: list[Any]) -> bool:
    if not flags:
        return True
    joined = " ".join(str(f) for f in flags)
    # PT diacritics in free-form flags → not English-steered
    return _PT_CHARS.search(joined) is None


@dataclass
class PairResult:
    relevant: str
    en_top: str
    pt_top: str
    en_hit_at: int
    pt_hit_at: int
    en_sim: float
    pt_sim: float


async def _embed_all(client: Any, texts: dict[str, str]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for key, text in texts.items():
        out[key] = await client.embed(text)
    return out


async def run_embedding_probe(client: Any, *, normalize: bool = False) -> dict[str, Any]:
    from core.semantic_query import normalize_semantic_query

    corpus_vecs = await _embed_all(client, {c["id"]: c["text"] for c in CORPUS})
    pairs: list[PairResult] = []
    expansions: list[dict[str, str]] = []
    for pair in QUERY_PAIRS:
        en_q = normalize_semantic_query(pair["en"]) if normalize else pair["en"]
        pt_q = normalize_semantic_query(pair["pt"]) if normalize else pair["pt"]
        if normalize:
            expansions.append(
                {
                    "relevant": pair["relevant"],
                    "en_raw": pair["en"],
                    "en_norm": en_q,
                    "pt_raw": pair["pt"],
                    "pt_norm": pt_q,
                }
            )
        en_vec = await client.embed(en_q)
        pt_vec = await client.embed(pt_q)
        en_rank = _rank(en_vec, corpus_vecs)
        pt_rank = _rank(pt_vec, corpus_vecs)
        relevant = pair["relevant"]
        en_ids = [cid for cid, _ in en_rank]
        pt_ids = [cid for cid, _ in pt_rank]
        en_hit = en_ids.index(relevant) + 1
        pt_hit = pt_ids.index(relevant) + 1
        pairs.append(
            PairResult(
                relevant=relevant,
                en_top=en_ids[0],
                pt_top=pt_ids[0],
                en_hit_at=en_hit,
                pt_hit_at=pt_hit,
                en_sim=en_rank[0][1],
                pt_sim=pt_rank[0][1],
            )
        )

    en_mrr = sum(1.0 / p.en_hit_at for p in pairs) / len(pairs)
    pt_mrr = sum(1.0 / p.pt_hit_at for p in pairs) / len(pairs)
    en_top1 = sum(1 for p in pairs if p.en_hit_at == 1) / len(pairs)
    pt_top1 = sum(1 for p in pairs if p.pt_hit_at == 1) / len(pairs)

    out: dict[str, Any] = {
        "model": getattr(client, "embedding_model", "unknown"),
        "normalize": normalize,
        "n_pairs": len(pairs),
        "en_top1": round(en_top1, 3),
        "pt_top1": round(pt_top1, 3),
        "en_mrr": round(en_mrr, 3),
        "pt_mrr": round(pt_mrr, 3),
        "pairs": [
            {
                "relevant": p.relevant,
                "en_top": p.en_top,
                "pt_top": p.pt_top,
                "en_hit_at": p.en_hit_at,
                "pt_hit_at": p.pt_hit_at,
                "en_top_sim": round(p.en_sim, 4),
                "pt_top_sim": round(p.pt_sim, 4),
            }
            for p in pairs
        ],
    }
    if expansions:
        out["expansions"] = expansions
    return out


async def run_sentiment_probe(client: Any) -> dict[str, Any]:
    from adapters.ai.prompts import build_sentiment_prompt

    rows: list[dict[str, Any]] = []
    for item in CORPUS:
        # Use description portion (after title line) when present
        body = item["text"].split("\n", 1)[-1]
        prompt = build_sentiment_prompt(body)
        result = await client.analyze_text(body, prompt)
        flags_en = _looks_english_flags(result.green_flags) and _looks_english_flags(
            result.red_flags
        )
        cat_ok = result.category in _EN_CATEGORY
        reasoning_en = _PT_CHARS.search(result.reasoning or "") is None
        rows.append(
            {
                "id": item["id"],
                "score": round(float(result.sentiment_score), 3),
                "category": result.category,
                "category_en_enum": cat_ok,
                "reasoning_looks_en": reasoning_en,
                "flags_look_en": flags_en,
                "green_flags": result.green_flags,
                "red_flags": result.red_flags,
                "reasoning": (result.reasoning or "")[:120],
            }
        )

    n = len(rows) or 1
    return {
        "n": len(rows),
        "category_en_rate": round(sum(1 for r in rows if r["category_en_enum"]) / n, 3),
        "reasoning_en_rate": round(sum(1 for r in rows if r["reasoning_looks_en"]) / n, 3),
        "flags_en_rate": round(sum(1 for r in rows if r["flags_look_en"]) / n, 3),
        "rows": rows,
    }


async def run_db_probe(
    client: Any, database_url: str, *, normalize: bool = False
) -> dict[str, Any]:
    from sqlalchemy import create_engine, text

    from adapters.ai.embeddings import vector_literal
    from core.semantic_query import normalize_semantic_query

    url = database_url.replace("postgresql+psycopg://", "postgresql://")
    engine = create_engine(url)

    with engine.connect() as conn:
        counts = conn.execute(
            text(
                """
                SELECT
                  count(*) FILTER (WHERE active) AS active,
                  count(*) FILTER (WHERE active AND embedding IS NOT NULL) AS with_emb,
                  count(*) FILTER (
                    WHERE active AND description IS NOT NULL
                      AND length(trim(description)) > 0
                  ) AS with_desc
                FROM properties
                """
            )
        ).mappings().one()

    query_specs = [
        ("pt", "apartamento perto do metrô"),
        ("en", "apartment near metro"),
        ("pt", "casa com quintal"),
        ("en", "house with backyard"),
        ("pt", "cobertura luxo"),
        ("en", "luxury penthouse"),
    ]

    anecdotes: list[dict[str, Any]] = []
    with engine.connect() as conn:
        for lang, q in query_specs:
            embed_q = normalize_semantic_query(q) if normalize else q
            vec = await client.embed(embed_q)
            lit = vector_literal(vec)
            rows = conn.execute(
                text(
                    """
                    SELECT public_id,
                           left(coalesce(title, ''), 80) AS title,
                           (embedding <=> CAST(:q_vec AS vector)) AS dist
                    FROM properties
                    WHERE active AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:q_vec AS vector)
                    LIMIT 5
                    """
                ),
                {"q_vec": lit},
            ).mappings().all()
            anecdotes.append(
                {
                    "lang": lang,
                    "q": q,
                    "q_embed": embed_q,
                    "normalize": normalize,
                    "top": [
                        {
                            "public_id": r["public_id"],
                            "title": r["title"],
                            "dist": round(float(r["dist"]), 4),
                        }
                        for r in rows
                    ],
                }
            )

    return {
        "corpus": dict(counts),
        "anecdotes": anecdotes,
    }


async def async_main(args: argparse.Namespace) -> int:
    ollama_host = os.environ.get("OLLAMA_HOST")
    if not ollama_host:
        # WSL → Windows host default
        try:
            import subprocess

            gw = subprocess.check_output(
                ["bash", "-c", "ip route show default | awk '/default/{print $3}'"],
                text=True,
            ).strip()
            if gw:
                ollama_host = f"http://{gw}:11434"
        except Exception:
            ollama_host = "http://localhost:11434"
        os.environ["OLLAMA_HOST"] = ollama_host

    from adapters.ai.client import OllamaClient
    from infra.config import get_config

    cfg = get_config()
    client = OllamaClient(
        base_url=ollama_host,
        timeout=max(120, int(cfg.ai.timeout)),
        visual_model=cfg.ai.visual_model,
        text_model=cfg.ai.text_model,
        embedding_model=cfg.ai.embedding_model,
        num_ctx=cfg.ai.num_ctx,
        max_tokens=cfg.ai.max_tokens,
    )

    report: dict[str, Any] = {
        "ollama_host": ollama_host,
        "embedding_model": cfg.ai.embedding_model,
        "text_model": cfg.ai.text_model,
    }

    try:
        print("== Embedding cross-lingual probe (fixture PT corpus) ==", flush=True)
        emb = await run_embedding_probe(client, normalize=False)
        report["embeddings"] = emb
        print(json.dumps(emb, ensure_ascii=False, indent=2), flush=True)

        if args.normalize:
            print(
                "\n== Embedding probe with BIN-102 query normalize ==",
                flush=True,
            )
            emb_norm = await run_embedding_probe(client, normalize=True)
            report["embeddings_normalized"] = emb_norm
            print(json.dumps(emb_norm, ensure_ascii=False, indent=2), flush=True)
            print(
                "\nEN MRR raw={:.3f} normalized={:.3f} | EN top1 raw={:.3f} "
                "normalized={:.3f}".format(
                    emb["en_mrr"],
                    emb_norm["en_mrr"],
                    emb["en_top1"],
                    emb_norm["en_top1"],
                ),
                flush=True,
            )

        print("\n== Sentiment language probe (PT ads → EN tags) ==", flush=True)
        sent = await run_sentiment_probe(client)
        report["sentiment"] = sent
        print(json.dumps(sent, ensure_ascii=False, indent=2), flush=True)

        if args.db:
            db_url = os.environ.get("DATABASE_URL")
            if not db_url:
                port = os.environ.get("POSTGRES_PORT", "5432")
                user = os.environ.get("POSTGRES_USER", "imoveis")
                password = os.environ.get("POSTGRES_PASSWORD", "imoveis_local_dev")
                db = os.environ.get("POSTGRES_DB", "realestate")
                db_url = f"postgresql://{user}:{password}@localhost:{port}/{db}"
            print("\n== Live DB semantic q= anecdotes ==", flush=True)
            db_report = await run_db_probe(
                client, db_url, normalize=bool(args.normalize)
            )
            report["db"] = db_report
            print(json.dumps(db_report, ensure_ascii=False, indent=2), flush=True)
    finally:
        await client.close()

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"\nWrote {args.out}", flush=True)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        action="store_true",
        help="Also probe live Postgres embeddings (needs DATABASE_URL or .env.local ports)",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Also run embedding probe with BIN-102 PT↔EN query synonym expansion",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="Optional path to write full JSON report",
    )
    args = parser.parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    sys.exit(main())
