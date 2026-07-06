"""Prompt templates for AI/VLM analysis tasks.

Each builder function returns a ready-to-send prompt string that instructs the
model to output **strict JSON** matching the expected schema.
"""
from __future__ import annotations

from typing import List


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

{{"condition_score": <float 0.0 to 1.0>, "features_detected": [<list of strings>], "issues_detected": [<list of strings>]}}

Where:
- condition_score: 0.0 = terrible condition, 1.0 = pristine / fully renovated.
- features_detected: list of modern/positive features you identified.
- issues_detected: list of dated/damaged features you identified.

### Few-shot examples

**Example 1** (renovated apartment):
{{"condition_score": 0.88, "features_detected": ["quartz countertops", "LED recessed lighting", "glass shower enclosure", "porcelain wood-look flooring"], "issues_detected": ["minor scuff marks on baseboard"]}}

**Example 2** (older unit needing renovation):
{{"condition_score": 0.30, "features_detected": ["spacious layout"], "issues_detected": ["old parquet floors with warping", "rusty bathroom fixtures", "peeling paint on ceiling", "outdated wooden cabinets", "water stain on bedroom wall"]}}

**Example 3** (average condition):
{{"condition_score": 0.55, "features_detected": ["granite countertop", "stainless steel stove"], "issues_detected": ["cracked tile in bathroom", "outdated light fixtures", "discolored grout in kitchen"]}}

Now analyze the provided photo(s) and return the JSON object.\
"""


# ---------------------------------------------------------------------------
# Location / Description Sentiment
# ---------------------------------------------------------------------------


def build_sentiment_prompt(description: str) -> str:
    """Return a prompt that asks the LLM to evaluate a property description.

    The model should identify positive and negative location/lifestyle
    signals and output a ``SentimentAnalysisResult`` JSON.

    Parameters
    ----------
    description:
        The raw property listing description text.
    """
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

{{"sentiment_score": <float 0.0 to 1.0>, "green_flags": [<list of strings>], "red_flags": [<list of strings>]}}

Where:
- sentiment_score: 0.0 = very negative outlook, 1.0 = extremely desirable location/property.
- green_flags: list of positive signals found in the description.
- red_flags: list of negative signals found in the description.

### Few-shot examples

**Example 1** (great location):
{{"sentiment_score": 0.92, "green_flags": ["close to metro station", "24-hour security", "gated community", "near park", "2 garage spaces"], "red_flags": []}}

**Example 2** (mixed signals):
{{"sentiment_score": 0.50, "green_flags": ["close to supermarket", "recently painted"], "red_flags": ["on a noisy avenue", "no parking", "no elevator — 4th floor"]}}

**Example 3** (concerning listing):
{{"sentiment_score": 0.20, "green_flags": ["large living area"], "red_flags": ["flood-prone region mentioned", "near industrial zone", "irregular documentation", "high condo fee"]}}

Now analyze the following property description and return the JSON object.

---
{description}\
"""
