"""Prompt templates for AI/VLM analysis tasks.

Each builder function returns a ready-to-send prompt string that instructs the
model to output **strict JSON** matching the expected schema.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Visual Condition Analysis
# ---------------------------------------------------------------------------


def build_visual_condition_prompt(num_images: int = 1) -> str:
    """Return a prompt that asks the VLM to evaluate property photos.

    The prompt includes few-shot examples so the model reliably outputs
    the ``VisualAnalysisResult`` JSON schema.

    Parameters
    ----------
    num_images:
        Number of images being sent (used for context in the prompt).
    """
    return f"""\
You are a real-estate property condition evaluator.
You will receive {num_images} photo(s) of a residential property.

Carefully analyze every photo and identify:

**Modern / positive features** (examples — detect any that apply):
- Vessel sinks, undermount sinks
- Quartz or granite countertops
- Custom or soft-close cabinetry
- Modern fixtures (matte black, brushed nickel, rain showerheads)
- LED or recessed lighting
- Glass shower enclosures, frameless glass
- Porcelain wood-look flooring
- Open floor plans, kitchen islands
- Smart home devices (smart locks, thermostats)
- Stainless steel or built-in appliances
- Balcony, terrace, or well-maintained outdoor area

**Dated / damaged features** (examples — detect any that apply):
- Old or warped parquet floors
- Cracked, chipped, or mismatched tiles
- Rusty or corroded fixtures (faucets, showerheads, drains)
- Outdated laminate or wooden cabinets with visible wear
- Water stains on ceilings or walls
- Peeling, bubbling, or cracked paint
- Mold or mildew spots
- Exposed or disorganized wiring
- Old-style fluorescent lighting
- Broken or missing window hardware
- Damaged or discolored grout

Return ONLY a JSON object with the following structure — no explanation, no \
markdown fences, no extra text:

{{"condition_score": <float 0.0 to 1.0>, "category": <string enum>, "reasoning": <string>, "features_detected": [<list of strings>], "issues_detected": [<list of strings>]}}

Where:
- condition_score: 0.0 = terrible condition, 1.0 = pristine / fully renovated.
- category: one of ["Pristine", "Good", "Average", "Needs Renovation", "Poor"].
- reasoning: a short 1-2 sentence explanation of why this category and score were chosen.
- features_detected: list of modern/positive features you identified.
- issues_detected: list of dated/damaged features you identified.

### Few-shot examples

**Example 1** (renovated apartment):
{{"condition_score": 0.88, "category": "Pristine", "reasoning": "Property appears fully renovated with modern fixtures and high-end materials.", "features_detected": ["quartz countertops", "LED recessed lighting", "glass shower enclosure", "porcelain wood-look flooring"], "issues_detected": ["minor scuff marks on baseboard"]}}

**Example 2** (older unit needing renovation):
{{"condition_score": 0.30, "category": "Needs Renovation", "reasoning": "The property shows significant signs of age and wear, requiring substantial updates.", "features_detected": ["spacious layout"], "issues_detected": ["old parquet floors with warping", "rusty bathroom fixtures", "peeling paint on ceiling", "outdated wooden cabinets", "water stain on bedroom wall"]}}

**Example 3** (average condition):
{{"condition_score": 0.55, "category": "Average", "reasoning": "The property is in fair condition but features dated materials alongside some acceptable finishes.", "features_detected": ["granite countertop", "stainless steel stove"], "issues_detected": ["cracked tile in bathroom", "outdated light fixtures", "discolored grout in kitchen"]}}

Now analyze the provided photo(s) and return the JSON object.\
"""


# ---------------------------------------------------------------------------
# Location / Description Sentiment
# ---------------------------------------------------------------------------


def build_sentiment_prompt(description: str, max_chars: int = 1000) -> str:
    """Return a prompt that asks the LLM to evaluate a property description.

    The model should identify positive and negative location/lifestyle
    signals and output a ``SentimentAnalysisResult`` JSON.

    Parameters
    ----------
    description:
        The raw property listing description text.
    max_chars:
        Truncate description to this length.
    """
    truncated_desc = description[:max_chars] if description else ""
    return f"""\
You are a real-estate location and lifestyle evaluator.
You will receive a property listing description in Portuguese (Brazil).

Analyze the description and identify:

**Positive signals (green flags)** — examples:
- Proximity to supermarkets, bakeries, pharmacies
- Close to parks, plazas, or green areas
- Near metro, bus, or train stations
- Close to schools, universities, hospitals
- Quiet or residential street
- 24-hour security, doorman (portaria 24h)
- Gated community (condomínio fechado)
- Recently renovated or newly built
- Natural lighting, cross ventilation (ventilação cruzada)
- Garage or dedicated parking
- Swimming pool, gym, playground in building
- Pet-friendly building

**Negative signals (red flags)** — examples:
- On a noisy avenue or high-traffic road
- Flood-prone area (área de alagamento)
- Near landfill, sewage treatment, or industrial area
- Construction or demolition nearby
- No parking or garage
- High crime or unsafe area mentioned
- No elevator in upper-floor unit
- Irregular property documentation
- Condominium fee unusually high
- Facing a wall or with no view

Return ONLY a JSON object — no explanation, no markdown fences, no extra text:

{{"sentiment_score": <float 0.0 to 1.0>, "category": <string enum>, "reasoning": <string>, "green_flags": [<list of strings>], "red_flags": [<list of strings>]}}

Where:
- sentiment_score: 0.0 = very negative outlook, 1.0 = extremely desirable location/property.
- category: one of ["Highly Desirable", "Good", "Average", "Undesirable", "Poor"].
- reasoning: a short 1-2 sentence explanation of why this category and score were chosen based on the location/lifestyle signals.
- green_flags: list of positive signals found in the description.
- red_flags: list of negative signals found in the description.

### Few-shot examples

**Example 1** (great location):
{{"sentiment_score": 0.92, "category": "Highly Desirable", "reasoning": "Located in a highly sought-after area with excellent amenities, transport links, and security features.", "green_flags": ["close to metro station", "24-hour security", "gated community", "near park", "2 garage spaces"], "red_flags": []}}

**Example 2** (mixed signals):
{{"sentiment_score": 0.50, "category": "Average", "reasoning": "Offers some convenience like nearby supermarkets, but major drawbacks like lack of parking and street noise balance it out.", "green_flags": ["close to supermarket", "recently painted"], "red_flags": ["on a noisy avenue", "no parking", "no elevator — 4th floor"]}}

**Example 3** (concerning listing):
{{"sentiment_score": 0.20, "category": "Poor", "reasoning": "The description highlights several serious red flags including flood risks and industrial proximity, with very few redeeming qualities.", "green_flags": ["large living area"], "red_flags": ["flood-prone region mentioned", "near industrial zone", "irregular documentation", "high condo fee"]}}

Now analyze the following property description and return the JSON object.

---
{truncated_desc}\
"""


# ---------------------------------------------------------------------------
# Deal Verdict Synthesis
# ---------------------------------------------------------------------------


def build_deal_verdict_prompt(
    stat_analysis: dict | None = None,
    visual: dict | None = None,
    sentiment: dict | None = None,
    neighborhood_name: str | None = None,
    output_language: str = "pt-br",
) -> str:
    """Return a prompt that asks the LLM to produce a concise PT-BR deal verdict.

    Combines the three scoring signals into a single natural-language sentence
    that serves as the property's "deal verdict" — the product's punchline.

    Parameters
    ----------
    stat_analysis:
        Dict with ``category`` and ``reasoning`` from statistical scoring.
    visual:
        Dict with ``condition_score``, ``category``, ``reasoning`` from VLM.
    sentiment:
        Dict with ``sentiment_score``, ``category``, ``reasoning``,
        ``green_flags``, ``red_flags`` from text LLM.
    neighborhood_name:
        The neighbourhood/area name for context (e.g. "Savassi").
    """
    stat_cat = (stat_analysis or {}).get("category", "N/A")
    stat_reason = (stat_analysis or {}).get("reasoning", "")
    vis_cat = (visual or {}).get("category", "N/A")
    vis_reason = (visual or {}).get("reasoning", "")
    sent_cat = (sentiment or {}).get("category", "N/A")
    sent_reason = (sentiment or {}).get("reasoning", "")
    red_flags = (sentiment or {}).get("red_flags", [])
    green_flags = (sentiment or {}).get("green_flags", [])

    red_flags_str = ", ".join(red_flags) if red_flags else "nenhum"
    green_flags_str = ", ".join(green_flags) if green_flags else "none"

    return f"""You are a real-estate deal evaluator. Given three analysis signals for a property in {neighborhood_name or "N/A"}, write a SHORT 1-2 sentence verdict in {output_language} that fuses them into a single punchline.

**Statistical Analysis**: {stat_cat}
{stat_reason}

**Visual Condition**: {vis_cat}
{vis_reason}

**Location Sentiment**: {sent_cat}
{sent_reason}

**Green Flags**: {green_flags_str}

**Red Flags**: {red_flags_str}

Write the verdict as a concise sentence (max ~30 words).  Start with the most impactful signal.
If signals conflict, mention the tension briefly.

Return ONLY a JSON object — no markdown fences, no explanation:

{{"verdict": "<{output_language} sentence>", "confidence": <float 0.0 to 1.0>}}

Now produce the verdict JSON object."""
