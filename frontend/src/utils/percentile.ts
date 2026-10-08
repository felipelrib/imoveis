/**
 * Cohort price/m² percentile on the card and in the filter (v0.14-s1.7).
 *
 * The value is the stored share of the neighbourhood cohort priced at or below
 * the Property (in (0, 1], lower is cheaper), served unrounded. Nothing here
 * reads the legacy `percentile_rank*` fields.
 */

/** Widest option of the `Preço no bairro` filter; also the badge cutoff. */
export const PRICE_PERCENTILE_BADGE_MAX = 0.5

/** Options the filter select offers (the API accepts any value in (0, 1]). */
export const PRICE_PERCENTILE_FILTER_OPTIONS: readonly number[] = [0.25, 0.5]

// 0.07 * 100 is 7.000000000000001 in binary floating point; without this the
// ceiling would read 8.
const FLOAT_NOISE = 1e-9

export interface PricePercentiles {
  price_per_m2_percentile_rent?: number | null
  price_per_m2_percentile_sale?: number | null
}

function validShare(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 && value <= 1
}

/**
 * N of `entre os N% mais baratos`: the smallest whole percent that keeps the
 * sentence true. 0.25 → 25, 0.2001 → 21, never below 1. `null` when there is
 * no usable value.
 */
export function cheapestPercent(value: number | null | undefined): number | null {
  if (!validShare(value)) return null
  return Math.max(1, Math.ceil(value * 100 - FLOAT_NOISE))
}

/** N for the card badge, or `null` when the card shows no badge at all. */
export function badgePercent(value: number | null | undefined): number | null {
  if (!validShare(value) || value > PRICE_PERCENTILE_BADGE_MAX) return null
  return cheapestPercent(value)
}

/** The stored percentile of one price line (listing type) of a Property. */
export function pricePercentileForType(
  property: PricePercentiles,
  listingType: string,
): number | null {
  if (listingType === 'rent') return property.price_per_m2_percentile_rent ?? null
  if (listingType === 'sale') return property.price_per_m2_percentile_sale ?? null
  return null
}

/** One percentile sentence of the detail panel (v0.14-s1.8). */
export interface PercentileSentence {
  /** Cohort listing type the sentence is about. */
  type: 'rent' | 'sale'
  /** N of `entre os N% mais baratos`; the same N the card badge shows. */
  n: number
  /** The Property has Listings of both types, so the sentence names the cohort. */
  dual: boolean
}

const SENTENCE_TYPES: readonly ('rent' | 'sale')[] = ['rent', 'sale']

/**
 * Sentences the detail panel states for a Property, rent before sale.
 *
 * `listingTypes` are the listing types of the Property's Listings: the card
 * draws one price line per type and a badge only on those lines, so a type
 * without a Listing gets no sentence either. Built on `badgePercent`, which
 * makes "the panel has a sentence" and "the card has a badge" one rule.
 */
export function percentileSentences(
  property: PricePercentiles,
  listingTypes: readonly string[],
): PercentileSentence[] {
  const present = SENTENCE_TYPES.filter((type) => listingTypes.includes(type))
  const dual = present.length > 1
  const sentences: PercentileSentence[] = []
  for (const type of present) {
    const n = badgePercent(pricePercentileForType(property, type))
    if (n != null) sentences.push({ type, n, dual })
  }
  return sentences
}

/**
 * Percent shown for a filter cap (select option, chip). The two offered caps
 * read 25 and 50; another cap (a saved search written through the API) reads
 * as it is applied, e.g. 0.305 → 30.5, never rounded to a neighbour.
 */
export function filterCapPercent(share: number): number {
  return Number((share * 100).toFixed(2))
}

/** Filter state (`''` or a number as text) → query value, `undefined` when off. */
export function parsePricePercentileFilter(value: string): number | undefined {
  const parsed = Number.parseFloat(value)
  return validShare(parsed) ? parsed : undefined
}
