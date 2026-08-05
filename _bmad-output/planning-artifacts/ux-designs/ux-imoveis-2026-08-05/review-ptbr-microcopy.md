# Revisão de microcopy pt-BR — DESIGN.md + EXPERIENCE.md

Reviewer: pt-BR microcopy lens (Reviewer Gate, .memlog decision). Voice baseline: neutro e claro, frases profissionais simples, nunca "chatty" (EXPERIENCE.md § Voice and Tone).

## Overall verdict

The copy is largely natural, well-cased Brazilian product Portuguese with correct `há`/currency/date typography, and the verdict scale reads like real BR real-estate language. Two findings are serious: the flagship percentile badge `top 25% preço` violates the spine's own cheap-direction rule (in pt-BR "top" leans premium/most-expensive) and is not grammatical Portuguese; and `provavelmente alugado` is factually wrong on sale listings. Everything else is polish-level: one anglicism (`run`), one ambiguity with the dismiss action, and a handful of consistency nits.

## Findings

### High

- **[HIGH]** `top 25% preço` → Violates the spine's own hard rule ("wording that could be read as 'top = most expensive' is forbidden"). In pt-BR, "top" carries a premium/best-in-class connotation ("top de linha", "apartamento top"), so "top 25% preço" plausibly reads as *the priciest quarter* — the exact inversion the rule forbids. It is also not grammatical Portuguese (no preposition; telegraphic anglicized fragment, which the voice doc bans as cockpit-terse). Bare `25% mais baratos` is not a safe fix either: next to the `−8% desde julho` drop badge it reads as a 25% *discount*. The `entre os` framing removes both ambiguities and makes the badge a clean truncation of the modal sentence — one consistent phrasing family. → **Badge: `entre os 25% mais baratos`; modal sentence stays `entre os 25% mais baratos do bairro`.** (DESIGN.md: percentile-badge component, Components § Property card, Do's table last row; EXPERIENCE.md § Voice and Tone percentile hard rules, J1 step 2. Generic form: `entre os N% mais baratos`.)

- **[HIGH]** `provavelmente alugado` / `provavelmente alugado — sem atualização há N dias` → Wrong for sale listings: a gone *venda* listing was not "alugado", it was sold (or delisted). The system explicitly handles both listing types (Aluguel/Venda segmented control, per-type price filters, dual-type Properties via `primaryListing`), so this string must vary by the listing type of the gone listing. → **Per listing type: `provavelmente alugado — …` (aluguel) / `provavelmente vendido — …` (venda); dual-type follows the primary listing.** (DESIGN.md: Colors § Gone, Components § Gone card; EXPERIENCE.md: Voice table, State Patterns § Gone listing.)

### Medium

- **[MEDIUM]** `OLX: run 5× mais rápido que a mediana` → "run" is developer jargon leaking into a pt-BR surface; good native words exist and the voice doc bans anglicized fragments where clear pt-BR carries. Note the knock-on gender agreement: "coleta" is feminine, so the adjective must flip. → **`OLX: coleta 5× mais rápida que a mediana`** ("varredura" also works; pick one and use it for "run" everywhere, including the Admin run-history surface). (EXPERIENCE.md: Voice table, State Patterns § Health anomaly, J3 step 1; any Admin run-history labels derived from it.)

- **[MEDIUM]** `2 anúncios removidos` (since-last-visit panel) → "removidos" is ambiguous with the user's own dismiss/hide action ("removes from grid") — did the market drop them or did I? These are listings that left the source portals. → **`2 anúncios saíram do ar`** (natural BR for delisted ads; alternatively `2 anúncios encerrados`). (EXPERIENCE.md: J1 step 1 `7 novos imóveis nos seus filtros · 3 quedas de preço · 2 anúncios removidos`.)

- **[MEDIUM]** Backfill states `idle / running / paused / backing-off` → Written in English in the spec; if these render literally they break the pt-BR-only default on an operator surface that is otherwise localized. "Backing-off" has no good literal translation — say what it means. → **`inativo / em execução / pausado / em espera (limite da API)`.** (EXPERIENCE.md: Operator Observability § Backfill card.)

### Low

- **[LOW]** `QuintoAndar · 2h atrás` → "X atrás" is the translated-feeling form and is inconsistent with the `há` used everywhere else (`visto há 3 dias`, `sem atualização há 14 dias`). → **`QuintoAndar · há 2h`.** (EXPERIENCE.md: State Patterns § Health ok, Operator Observability § Health strip.)

- **[LOW]** `Cobertura IA 82%` → Missing preposition makes it telegraphic; the voice doc bans cockpit-terse and two extra characters fix it. → **`Cobertura de IA: 82%`** (chip may drop the colon: `Cobertura de IA 82%`). (EXPERIENCE.md: Operator Observability § Health strip.)

- **[LOW]** `Favoritos / roteiro de visitas` → Mixed casing inside one nav label (capitalized + lowercase halves). → **`Favoritos / Roteiro de visitas`** — or simply **`Roteiro de visitas`**, since favourites graduate into it and one name is calmer nav. (EXPERIENCE.md: Information Architecture table, J4 step 1.)

- **[LOW]** `Admin / Operações` → "Admin" is an anglicism and redundant next to "Operações", which already names the surface precisely. Acceptable for a solo operator tool, but the cleaner label is → **`Operações`** alone. (EXPERIENCE.md: Information Architecture table.)

- **[LOW]** `entre os 25% mais baratos do bairro` (modal, dual-type Properties only) → The sentence encodes the bairro cohort but drops the listing-type half of the cohort (bairro × tipo), which the spine itself requires ("cohort language mirrors the source"). On a dual rent/sale Property the reader can't tell which cohort the 25% refers to. → **Per type: `entre os 25% mais baratos dos aluguéis do bairro` / `…das vendas do bairro`** (single-type listings can keep the short form). (EXPERIENCE.md: percentile hard rules, cohort bullet.)

- **[LOW, optional]** Verdict scale `Excelente negócio / Bom preço / Preço de mercado / Acima do mercado` → Three verdicts sit on the *price* axis; the top one switches to the *deal* axis ("negócio"). Register and naturalness are fine — every phrase is real BR real-estate language — and the axis break is defensible as an editorial peak, but if strict parallelism is wanted: → **`Preço excelente`** for the top verdict. Keep as-is if the emphasis is intentional. (DESIGN.md: Colors § Verdict scale; EXPERIENCE.md: verdict component.)

## Strings verified as good (not flagged)

`Bom preço` · `Preço de mercado` · `Acima do mercado` · `análise de IA pendente` (natural; better than "análise pendente de IA" or a spinner) · `visto hoje na OLX` / `visto hoje` / `visto há 3 dias` / `sem atualização há 14 dias` (correct `há`, honest degradation) · `−8% desde julho` (lowercase month, true minus sign) · `2 fontes` (short, fits the deal-journal character; "2 portais" would also work but "fontes" is consistent with the dedupe framing) · `2 quartos · 68 m² · QuintoAndar + OLX` (space before m², correct) · `Aluguel / Venda / ambos` · `Savassi +3` · `Filtros (N)` · `seguro` / `reformado` / `silencioso` · `Painel` · `Buscas salvas` · `Alertas` · `Comparar` · `3 imóveis baixaram de preço desde ontem` · `7 novos imóveis nos seus filtros` · `3 quedas de preço` · `2 quartos Savassi até R$ 3.000` (correct R$ spacing and thousands dot) · `Verificar disponibilidade` · `fazer proposta` · `dia 3 de ~6 · 61% da cota de hoje` ("cota" is the correct BR spelling; "~" acceptable on an operator card) · `local — qwen2.5-vl` · POI labels (`Igreja`, `Casa dos pais`, `Casa da namorada` — user data). Terminology is consistent across both spines: always *bairro* (never "vizinhança"), always *imóvel/imóveis* (never "propriedade"), *anúncio* reserved for the platform listing — a correct and well-held distinction.

---

**~40 user-facing strings reviewed · 10 flagged (2 high · 3 medium · 5 low, 1 of them optional).**
