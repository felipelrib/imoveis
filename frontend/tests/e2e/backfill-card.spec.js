// @ts-check
import { test, expect } from "@playwright/test";
import {
  BACKFILL_LAST_RUN_PROVIDER_REFUSED,
  BACKFILL_STATUS_IDLE,
  BACKFILL_STATUS_RUNNING,
  ENRICHMENT_COVERAGE,
  ENRICHMENT_COVERAGE_RUNNING,
  installCommonMocks,
  mockAdminBackfill,
  mockAdminCoverage,
  mockAdminLocale,
  mockPlatforms,
} from "./helpers/apiMocks.js";

const VALID_KEY = "e2e-test-api-key";

/** Seed the paste-once credential + the pt-BR preference the operator surface renders in. */
async function bootOperacoes(page, opts = {}) {
  await page.addInitScript((key) => {
    sessionStorage.setItem("api_key", key);
  }, VALID_KEY);
  await installCommonMocks(page);
  const locale = opts.locale ?? "pt-BR";
  await mockAdminLocale(page, { initial: locale, defaultLocale: locale });
  await mockPlatforms(page);
  await mockAdminBackfill(page, opts.backfill ?? {});
  await mockAdminCoverage(page, opts.coverage ?? ENRICHMENT_COVERAGE, {
    statusCode: opts.coverageStatusCode,
  });
}

test.describe("Operações backfill card (v0.13-s1.6)", () => {
  test("renders the pt-BR state, the three text lines and the running warning", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: { status: BACKFILL_STATUS_RUNNING },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/scraper");
    const card = page.getByTestId("backfill-card");
    await expect(card).toBeVisible();
    await expect(card).toContainText("Backfill de enriquecimento");
    await expect(page.getByTestId("backfill-state")).toHaveText("em execução");

    // 8784 / 14400 = 61%
    await expect(page.getByTestId("backfill-budget-line")).toHaveText(
      "cota de hoje: 61% usada"
    );
    await expect(page.getByTestId("backfill-throughput-line")).toHaveText(
      "ritmo: ~4.600 imóveis/dia"
    );
    await expect(page.getByTestId("backfill-eta-line")).toHaveText("ETA: ~3 dias");

    // The warning names the gate the heartbeat actually blocks. validate.sh runs
    // only against the ephemeral test stack (v0.13-fu1) and is safe during a
    // live backfill — telling the operator otherwise would park every merge for
    // the six days the pass runs.
    await expect(page.getByTestId("backfill-warning")).toContainText(
      "migrate-primary.sh vai recusar"
    );
    await expect(page.getByTestId("backfill-warning")).not.toContainText("validate.sh");
    // No bars/tracks anywhere on the card (UX-DR5).
    await expect(card.locator("progress, .progress, .bar")).toHaveCount(0);
  });

  test("pause posts to /admin/backfill/pause", async ({ page }) => {
    /** @type {{method: string, url: string}[]} */
    const calls = [];
    await bootOperacoes(page, {
      backfill: { status: BACKFILL_STATUS_RUNNING, calls },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-pause")).toBeEnabled();
    await page.getByTestId("backfill-pause").click();

    await expect
      .poll(() =>
        calls.some((c) => c.method === "POST" && c.url.includes("/admin/backfill/pause"))
      )
      .toBeTruthy();
    await expect(page.getByText("Backfill pausado")).toBeVisible();
    // Start is refused while the lease is held, so it never offers itself.
    await expect(page.getByTestId("backfill-start")).toBeDisabled();
  });

  test("with no run the card shows only the state — no ETA, rate or quota line", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: { status: BACKFILL_STATUS_IDLE },
      coverage: ENRICHMENT_COVERAGE,
    });

    await page.goto("/scraper");
    const card = page.getByTestId("backfill-card");
    await expect(page.getByTestId("backfill-state")).toHaveText("inativo");

    await expect(page.getByTestId("backfill-budget-line")).toHaveCount(0);
    await expect(page.getByTestId("backfill-throughput-line")).toHaveCount(0);
    await expect(page.getByTestId("backfill-eta-line")).toHaveCount(0);
    await expect(page.getByTestId("backfill-warning")).toHaveCount(0);
    await expect(card).not.toContainText("ETA");
    await expect(card).not.toContainText("ritmo");
    await expect(card).not.toContainText("cota de hoje");

    await expect(page.getByTestId("backfill-start")).toBeEnabled();
    await expect(page.getByTestId("backfill-pause")).toBeDisabled();
    await expect(page.getByTestId("backfill-resume")).toBeDisabled();
  });

  test("a 409 start raises a non-blocking toast naming the active run", async ({
    page,
  }) => {
    // The only way the server produces this pair is the staleness window: the
    // card is holding an idle read from its last poll when another host takes the
    // lease. So the status the refresh reads back is the live run, not the idle
    // one — a combination the control plane can actually report.
    await bootOperacoes(page, {
      backfill: {
        status: BACKFILL_STATUS_IDLE,
        statusAfterStart: BACKFILL_STATUS_RUNNING,
        startStatus: 409,
        startDetail:
          "A backfill run already holds the lease (gemma-runner@wsl-felipe, held for 2 days).",
      },
    });

    await page.goto("/scraper");
    await page.getByTestId("backfill-start").click();

    await expect(page.getByText(/gemma-runner@wsl-felipe/)).toBeVisible();
    await expect(page.getByText(/Já existe um backfill em execução/)).toBeVisible();
    // Non-blocking: the card is still there and readable behind the toast.
    await expect(page.getByTestId("backfill-card")).toBeVisible();
    // …and it now shows the run it lost the race to, with no second start on offer.
    await expect(page.getByTestId("backfill-state")).toHaveText("em execução");
    await expect(page.getByTestId("backfill-start")).toBeDisabled();
  });

  test("a 202 with no runner listening says so instead of claiming success", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      // BACKFILL_STATUS_IDLE carries runner_present: false — nothing is waiting
      // to consume the request, which is exactly the case story 1.5 added the
      // flag for.
      backfill: { status: BACKFILL_STATUS_IDLE },
    });

    await page.goto("/scraper");
    await page.getByTestId("backfill-start").click();

    await expect(page.getByText(/nenhum runner está escutando/)).toBeVisible();
    await expect(page.getByText("Execução do backfill solicitada")).toHaveCount(0);
  });

  test("a start that was already pending is reported as pending, not as new", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: {
        status: BACKFILL_STATUS_IDLE,
        startBody: { runner_present: true, already_requested: true },
      },
    });

    await page.goto("/scraper");
    await page.getByTestId("backfill-start").click();

    await expect(page.getByText(/Já havia um pedido de início pendente/)).toBeVisible();
    await expect(page.getByText("Execução do backfill solicitada")).toHaveCount(0);
  });

  test("a pending pause is rendered and stops the operator clicking pause again", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: {
        status: {
          ...BACKFILL_STATUS_RUNNING,
          pending_requests: ["pause"],
        },
      },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/scraper");
    // The runner has not applied it yet, so the state still reads "running" —
    // the pending line is what keeps that from looking like a lost click.
    await expect(page.getByTestId("backfill-state")).toHaveText("em execução");
    await expect(page.getByTestId("backfill-pending-pause")).toContainText(
      "pausa solicitada"
    );
    await expect(page.getByTestId("backfill-pause")).toBeDisabled();
    // Withdrawing it is still possible — resume clears the pause level.
    await expect(page.getByTestId("backfill-resume")).toBeEnabled();
  });

  test("a paused run reads pausado, drops the warning and resumes", async ({ page }) => {
    /** @type {{method: string, url: string}[]} */
    const calls = [];
    await bootOperacoes(page, {
      backfill: {
        calls,
        // The wire shape of a *applied* pause: the lease is still held, the
        // runner has stopped beating, and the pause level is still set — that
        // level is `pending_requests`, which is why it cannot double as a
        // "waiting for the runner" signal.
        status: {
          ...BACKFILL_STATUS_RUNNING,
          state: "paused",
          heartbeat_active: false,
          pending_requests: ["pause"],
        },
      },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-state")).toHaveText("pausado");
    // The pause has been applied: nothing is waiting on the runner any more.
    await expect(page.getByTestId("backfill-pending-pause")).toHaveCount(0);
    // Nothing is being enriched, so migrate-primary.sh is not blocked.
    await expect(page.getByTestId("backfill-warning")).toHaveCount(0);
    await expect(page.getByTestId("backfill-pause")).toBeDisabled();

    // The server measures throughput over a window clamped to the *lease*, which
    // a paused run still holds — so it keeps sending the rate from before the
    // pause and an ETA counted off it. Quoting either would promise a completion
    // date to a run that has stopped moving towards it.
    await expect(page.getByTestId("backfill-throughput-line")).toHaveCount(0);
    await expect(page.getByTestId("backfill-eta-line")).toHaveCount(0);
    // Today's consumed quota is a fact whatever the runner is doing, so it stays.
    await expect(page.getByTestId("backfill-budget-line")).toHaveText(
      "cota de hoje: 61% usada"
    );

    await page.getByTestId("backfill-resume").click();
    await expect
      .poll(() =>
        calls.some((c) => c.method === "POST" && c.url.includes("/admin/backfill/resume"))
      )
      .toBeTruthy();
    await expect(page.getByText("Backfill retomado")).toBeVisible();
  });

  test("backing-off is named as the API limit and offers nothing to resume", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: {
        // Waiting out the provider's rate limit is not a pause: there is no
        // level to clear, so a resume would be a no-op that toasted success.
        status: { ...BACKFILL_STATUS_RUNNING, state: "backing-off" },
      },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-state")).toHaveText(
      "em espera (limite da API)"
    );
    await expect(page.getByTestId("backfill-resume")).toBeDisabled();
    await expect(page.getByTestId("backfill-pause")).toBeEnabled();
    // Same reason as a pause: the lease is held, nothing is being enriched, and
    // the rate on the wire was measured before the client hit the limit.
    await expect(page.getByTestId("backfill-throughput-line")).toHaveCount(0);
    await expect(page.getByTestId("backfill-eta-line")).toHaveCount(0);
  });

  test("a pause level outliving its run stops claiming the runner is about to apply it", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      // The pause *level* has a seven-day TTL; the state key expires in two
      // minutes and the lease in fifteen. A runner that died while paused
      // therefore leaves `pause` set with no run and no `paused` word behind it,
      // and the card must not spend the rest of the week saying a runner is
      // about to pick it up.
      backfill: {
        status: {
          ...BACKFILL_STATUS_IDLE,
          state: "idle",
          pending_requests: ["pause"],
        },
      },
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-state")).toHaveText("inativo");
    await expect(page.getByTestId("backfill-pending-pause")).toHaveCount(0);
    await expect(page.getByTestId("backfill-card")).not.toContainText(
      "aguardando o runner"
    );
  });

  test("a paused state outliving its runner offers no resume", async ({ page }) => {
    await bootOperacoes(page, {
      // The runner died while paused: the state word survives its TTL but the
      // lease is gone, so resume would clear nothing and still say "retomado".
      backfill: {
        status: {
          ...BACKFILL_STATUS_IDLE,
          state: "paused",
          pending_requests: ["pause"],
        },
      },
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-state")).toHaveText("pausado");
    await expect(page.getByTestId("backfill-resume")).toBeDisabled();
    await expect(page.getByTestId("backfill-pause")).toBeDisabled();
  });

  test("a primary migration says why start is unavailable", async ({ page }) => {
    await bootOperacoes(page, {
      backfill: { status: { ...BACKFILL_STATUS_IDLE, migration_active: true } },
    });

    await page.goto("/scraper");
    // A disabled control with no stated reason reads as a broken button.
    await expect(page.getByTestId("backfill-start")).toBeDisabled();
    await expect(page.getByTestId("backfill-start-blocked")).toContainText(
      "migração do banco primário"
    );
  });

  test("a queued start with nothing listening does not promise a pickup", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: {
        status: {
          ...BACKFILL_STATUS_IDLE,
          start_requested_at: "2026-08-11T09:00:00Z",
          runner_present: false,
        },
      },
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-pending-start")).toContainText(
      "nenhum runner está escutando"
    );
    await expect(page.getByTestId("backfill-pending-start")).not.toContainText(
      "aguardando o runner assumir"
    );
  });

  test("a live run whose published state has decayed to idle can still be paused", async ({
    page,
  }) => {
    // DW-20: the state key expires under a slow row while the lease is still
    // held. `active` is the liveness signal; keying the control off `state`
    // locked the operator out of pausing a run that was very much alive.
    await bootOperacoes(page, {
      backfill: {
        status: { ...BACKFILL_STATUS_RUNNING, state: "idle" },
      },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-pause")).toBeEnabled();
    await expect(page.getByTestId("backfill-start")).toBeDisabled();
  });

  test("a status failure is stated and takes the figures with it", async ({ page }) => {
    await bootOperacoes(page, {
      backfill: { statusCode: 500 },
      coverage: ENRICHMENT_COVERAGE,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-error")).toContainText(
      "estado do backfill indisponível"
    );
    // No frozen state word, no figures, and no control that would only 500 again.
    await expect(page.getByTestId("backfill-state")).toHaveCount(0);
    await expect(page.getByTestId("backfill-lines")).toHaveCount(0);
    await expect(page.getByTestId("backfill-start")).toBeDisabled();

    // …and the DB-derived coverage card is untouched by the Redis-side failure.
    await expect(page.getByTestId("coverage-row-visual")).toContainText("62%");
    await expect(page.getByTestId("coverage-error")).toHaveCount(0);
  });

  test("a coverage failure is stated without taking the control state down", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: { status: BACKFILL_STATUS_RUNNING },
      coverageStatusCode: 500,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("coverage-error")).toContainText(
      "cobertura indisponível"
    );
    await expect(page.getByTestId("backfill-state")).toHaveText("em execução");
    await expect(page.getByTestId("backfill-error")).toHaveCount(0);
  });

  test("a rejected credential is named as such, not as a control-plane outage", async ({
    page,
  }) => {
    // `hasApiKey()` only says a credential is *stored*. A revoked or mistyped one
    // 403s exactly like a healthy request, and reporting that as "the control
    // plane could not be read" buys the operator the wrong debugging session
    // entirely — Redis and the runner, for a problem in their own sessionStorage.
    await bootOperacoes(page, {
      backfill: { statusCode: 403 },
      coverageStatusCode: 403,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-error")).toContainText(
      "credencial de API armazenada foi recusada"
    );
    await expect(page.getByTestId("backfill-error")).not.toContainText(
      "plano de controle"
    );
    await expect(page.getByTestId("coverage-error")).toContainText(
      "credencial de API armazenada foi recusada"
    );
  });

  test("without a credential the card offers a hint and fires no admin request", async ({
    page,
  }) => {
    /** @type {{method: string, url: string}[]} */
    const calls = [];
    await page.addInitScript(() => sessionStorage.clear());
    await installCommonMocks(page);
    await mockPlatforms(page);
    await mockAdminBackfill(page, { calls });
    // Recorded through the same list: the coverage route is admin-gated too, and
    // an uncredentialed session must be silent on both.
    await mockAdminCoverage(page, ENRICHMENT_COVERAGE, { calls });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-credential-hint")).toBeVisible();
    await expect(page.getByTestId("coverage-credential-hint")).toBeVisible();
    await expect(page.getByTestId("backfill-start")).toHaveCount(0);
    await expect.poll(() => calls.length, { timeout: 2000 }).toBe(0);
  });
});

test.describe("Operações coverage card (v0.13-s1.6)", () => {
  test("lists every signal the API returns with its percentage", async ({ page }) => {
    await bootOperacoes(page);

    await page.goto("/scraper");
    const card = page.getByTestId("coverage-card");
    await expect(card).toContainText("Cobertura de IA por tipo de sinal");

    await expect(page.getByTestId("coverage-row-visual")).toContainText("visual");
    await expect(page.getByTestId("coverage-row-visual")).toContainText("62%");
    await expect(page.getByTestId("coverage-row-sentiment")).toContainText("sentimento");
    await expect(page.getByTestId("coverage-row-deal_verdict")).toContainText(
      "veredito do negócio"
    );
    await expect(page.getByTestId("coverage-row-valuation")).toContainText(
      "avaliação estatística"
    );
    await expect(page.getByTestId("coverage-row-embedding")).toContainText("embeddings");
    await expect(card.locator(".cov-row")).toHaveCount(5);

    await expect(page.getByTestId("coverage-footnote")).toHaveText(
      "o painel mostra o mínimo entre os sinais: 60%"
    );
  });

  test("an undefined fraction keeps its label and shows no percentage", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      coverage: {
        signals: [
          { task_class: "visual", enriched: 0, total: 0, fraction: null },
          { task_class: "sentiment", enriched: 0, total: 0, fraction: null },
        ],
        minimum_fraction: null,
        total_properties: 0,
        backfill: {
          active: false,
          remaining: 0,
          throughput_per_day: null,
          eta_days: null,
          projected_completion_date: null,
        },
      },
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("coverage-row-visual")).toHaveText("visual");
    await expect(page.getByTestId("coverage-row-visual")).not.toContainText("%");
    await expect(page.getByTestId("coverage-footnote")).toHaveCount(0);
  });
});

test.describe("Painel health strip (v0.13-s1.6)", () => {
  test("shows the coverage minimum and the backfill chip while a run is live", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: { status: BACKFILL_STATUS_RUNNING },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/");
    const chip = page.getByTestId("health-coverage-chip");
    await expect(chip).toContainText("Cobertura de IA");
    await expect(chip).toContainText("60%");
    // The chip owns its wording — the Operações footnote ("o painel mostra…")
    // would be talking about the very page it is being read on. It also names
    // *which* signal the minimum came from: unnamed, a number pinned by a signal
    // the backfill's scope cannot move reads as a verdict on the run beside it.
    await expect(chip).toHaveAttribute(
      "title",
      "a menor cobertura entre os tipos de sinal é veredito do negócio: 60%"
    );

    const backfillChip = page.getByTestId("health-backfill-chip");
    await expect(backfillChip).toContainText("Backfill");
    await expect(backfillChip).toContainText("em execução");
    await expect(backfillChip).toContainText("⚠");
  });

  test("the chip says what the run is doing, not always 'em execução'", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      // A paused run holds the lease exactly as hard as a running one. A front
      // door that reads "em execução" contradicts the Operações card one click
      // away, which reads "pausado" off the same snapshot.
      backfill: {
        status: {
          ...BACKFILL_STATUS_RUNNING,
          state: "paused",
          heartbeat_active: false,
          pending_requests: ["pause"],
        },
      },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/");
    const backfillChip = page.getByTestId("health-backfill-chip");
    await expect(backfillChip).toContainText("Backfill");
    await expect(backfillChip).toContainText("pausado");
    await expect(backfillChip).not.toContainText("em execução");
  });

  test("a chip whose read failed disappears instead of freezing", async ({ page }) => {
    await bootOperacoes(page, {
      backfill: { status: BACKFILL_STATUS_RUNNING, statusCode: 500 },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/");
    // Coverage still answers, so its chip stays; the backfill chip cannot claim a
    // run is live off a read that failed.
    await expect(page.getByTestId("health-coverage-chip")).toContainText("60%");
    await expect(page.getByTestId("health-backfill-chip")).toHaveCount(0);
  });

  test("without a credential neither chip renders", async ({ page }) => {
    await page.addInitScript(() => sessionStorage.clear());
    await installCommonMocks(page);

    await page.goto("/");
    await expect(page.getByTestId("dashboard-health-strip")).toHaveCount(0);
    await expect(page.getByTestId("health-coverage-chip")).toHaveCount(0);
    await expect(page.getByTestId("health-backfill-chip")).toHaveCount(0);
  });
});

test.describe("Operações backfill card — run lifecycle (v0.14-s1.13)", () => {
  test("a provider-refused last run is shown with the runner's reason", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: {
        status: {
          ...BACKFILL_STATUS_IDLE,
          runner_present: true,
          last_run: BACKFILL_LAST_RUN_PROVIDER_REFUSED,
        },
      },
      coverage: ENRICHMENT_COVERAGE,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-state")).toHaveText("inativo");
    const line = page.getByTestId("backfill-last-run-line");
    // pt-BR label for the canonical English outcome word, then when it ended
    // (day/month and hour:minute; the hour depends on the browser's zone).
    await expect(line).toHaveText(
      /^última execução: encerrada — o provedor recusou por cota repetidas vezes · \d{2}\/\d{2},? \d{2}:\d{2}$/
    );
    // An ending that needs the operator is a failure line, not a plain one.
    await expect(line).toHaveClass(/ops-fail/);
    // The runner's sentence on its own line, as written.
    await expect(page.getByTestId("backfill-last-run-reason")).toHaveText(
      BACKFILL_LAST_RUN_PROVIDER_REFUSED.reason
    );
    // The run is over: starting again is the operator's call, and it is offered.
    await expect(page.getByTestId("backfill-start")).toBeEnabled();
  });

  test("a clean ending is a plain line and an unknown outcome is shown verbatim", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: {
        status: {
          ...BACKFILL_STATUS_IDLE,
          last_run: {
            outcome: "complete",
            exit_code: 0,
            reason: null,
            started_at: "2026-10-01T09:00:00Z",
            finished_at: "2026-10-06T14:30:00Z",
            source: "admin-api",
          },
        },
      },
      coverage: ENRICHMENT_COVERAGE,
    });

    await page.goto("/scraper");
    const line = page.getByTestId("backfill-last-run-line");
    await expect(line).toContainText("última execução: concluída · ");
    await expect(line).toHaveClass(/ops-line/);
    await expect(line).not.toHaveClass(/ops-fail/);
    await expect(page.getByTestId("backfill-last-run-reason")).toHaveCount(0);

    // A word this build has no label for is rendered as it came, never mapped
    // to a wrong one.
    await mockAdminBackfill(page, {
      status: {
        ...BACKFILL_STATUS_IDLE,
        last_run: { outcome: "quota_project_disabled", exit_code: 12 },
      },
    });
    await page.reload();
    const unknown = page.getByTestId("backfill-last-run-line");
    await expect(unknown).toHaveText("última execução: quota_project_disabled");
    // Nothing here knows what the word means, so it is not painted a failure.
    await expect(unknown).not.toHaveClass(/ops-fail/);

    // An operator stop is an ending someone asked for: a plain line too.
    await mockAdminBackfill(page, {
      status: {
        ...BACKFILL_STATUS_IDLE,
        last_run: {
          outcome: "stopped",
          exit_code: 6,
          finished_at: "2026-10-06T14:30:00Z",
        },
      },
    });
    await page.reload();
    const stopped = page.getByTestId("backfill-last-run-line");
    await expect(stopped).toContainText("última execução: parada pelo operador · ");
    await expect(stopped).toHaveClass(/ops-line/);
    await expect(stopped).not.toHaveClass(/ops-fail/);
  });

  test("a hung run is said while it still holds the lease", async ({ page }) => {
    await bootOperacoes(page, {
      backfill: {
        status: {
          ...BACKFILL_STATUS_RUNNING,
          // The watchdog gave the run up; the lease has not lapsed yet.
          last_run: {
            outcome: "hung",
            exit_code: null,
            reason: "The main thread made no progress for 3600s.",
            started_at: "2026-10-04T09:00:00Z",
            finished_at: "2026-10-06T14:30:00Z",
            source: "admin-api",
          },
        },
      },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/scraper");
    const line = page.getByTestId("backfill-last-run-line");
    await expect(line).toContainText(
      "última execução: travada — o processo parou de responder · "
    );
    await expect(line).toHaveClass(/ops-fail/);
    await expect(page.getByTestId("backfill-last-run-reason")).toHaveText(
      "The main thread made no progress for 3600s."
    );
  });

  test("an old hung record is not painted over a later run", async ({ page }) => {
    await bootOperacoes(page, {
      backfill: {
        status: {
          ...BACKFILL_STATUS_RUNNING,
          // This run took the lease after the watchdog gave the other one up.
          // A run started by hand writes no record, so the old one is still
          // the last in Redis.
          lease: {
            ...BACKFILL_STATUS_RUNNING.lease,
            acquired_at: "2026-10-07T08:00:00Z",
          },
          last_run: {
            outcome: "hung",
            exit_code: null,
            reason: "The main thread made no progress for 3600s.",
            started_at: "2026-10-04T09:00:00Z",
            finished_at: "2026-10-06T14:30:00Z",
            source: "admin-api",
          },
        },
      },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-state")).toHaveText("em execução");
    await expect(page.getByTestId("backfill-budget-line")).toBeVisible();
    await expect(page.getByTestId("backfill-last-run")).toHaveCount(0);
    await expect(page.getByTestId("backfill-card")).not.toContainText("travada");
  });

  test("a stale pause left by a dead runner says nothing about a paused run", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: {
        status: {
          ...BACKFILL_STATUS_IDLE,
          // No lease: the pause level outlived the run that observed it.
          active: false,
          pending_requests: ["pause"],
          paused_since: "2026-09-28T09:00:00Z",
          pause_stale: true,
        },
      },
      coverage: ENRICHMENT_COVERAGE,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-state")).toHaveText("inativo");
    await expect(page.getByTestId("backfill-paused")).toHaveCount(0);
    await expect(page.getByTestId("backfill-pause-stale")).toHaveCount(0);
  });

  test("the last run is labelled in English too", async ({ page }) => {
    const refusal = "GEMINI_API_KEY is not set: export it in the supervisor's shell.";
    await bootOperacoes(page, {
      locale: "en",
      backfill: {
        status: {
          ...BACKFILL_STATUS_IDLE,
          last_run: {
            outcome: "refused",
            exit_code: 1,
            reason: refusal,
            started_at: "2026-10-06T14:29:00Z",
            finished_at: "2026-10-06T14:30:00Z",
            source: "admin-api",
          },
        },
      },
      coverage: ENRICHMENT_COVERAGE,
    });

    await page.goto("/scraper");
    const line = page.getByTestId("backfill-last-run-line");
    await expect(line).toContainText("last run: refused by the runner · ");
    await expect(line).toHaveClass(/ops-fail/);
    await expect(page.getByTestId("backfill-last-run-reason")).toHaveText(refusal);

    await mockAdminBackfill(page, {
      status: {
        ...BACKFILL_STATUS_IDLE,
        // Derived by the API: it has a start and no end.
        last_run: {
          outcome: "interrupted",
          started_at: "2026-10-06T14:30:00Z",
          source: "admin-api",
        },
      },
    });
    await page.reload();
    const interrupted = page.getByTestId("backfill-last-run-line");
    await expect(interrupted).toContainText(
      "last run: interrupted — the process ended without recording how · "
    );
    await expect(interrupted).toHaveClass(/ops-fail/);
  });

  test("no last-run line while a run is active", async ({ page }) => {
    await bootOperacoes(page, {
      backfill: {
        status: {
          ...BACKFILL_STATUS_RUNNING,
          // The record of the run before this one is still in Redis.
          last_run: BACKFILL_LAST_RUN_PROVIDER_REFUSED,
        },
      },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-state")).toHaveText("em execução");
    await expect(page.getByTestId("backfill-budget-line")).toBeVisible();
    await expect(page.getByTestId("backfill-last-run")).toHaveCount(0);
    await expect(page.getByTestId("backfill-card")).not.toContainText("última execução");
  });

  test("the record of the run in progress is not rendered as an ending", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: {
        status: {
          ...BACKFILL_STATUS_IDLE,
          // The lease was released a moment ago and the end is not written yet.
          last_run: {
            outcome: "started",
            started_at: "2026-10-06T14:30:00Z",
            source: "admin-api",
          },
        },
      },
      coverage: ENRICHMENT_COVERAGE,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-state")).toHaveText("inativo");
    await expect(page.getByTestId("backfill-last-run")).toHaveCount(0);
  });

  test("a stale pause says since when and that it is still in force", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: {
        status: {
          ...BACKFILL_STATUS_RUNNING,
          state: "paused",
          heartbeat_active: false,
          pending_requests: ["pause"],
          paused_since: "2026-09-28T09:00:00Z",
          pause_stale: true,
        },
      },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-state")).toHaveText("pausado");
    await expect(page.getByTestId("backfill-paused-since")).toHaveText(
      /^pausado desde \d{2}\/\d{2},? \d{2}:\d{2}$/
    );
    await expect(page.getByTestId("backfill-pause-stale")).toHaveText(
      "pausa antiga — continua valendo, e nada é lançado até alguém retomar"
    );
    // Still a pause: the way out is resume, and it is offered.
    await expect(page.getByTestId("backfill-resume")).toBeEnabled();
    await expect(page.getByTestId("backfill-warning")).toHaveCount(0);
  });

  test("a fresh pause says since when and nothing about being stale", async ({
    page,
  }) => {
    await bootOperacoes(page, {
      backfill: {
        status: {
          ...BACKFILL_STATUS_RUNNING,
          state: "paused",
          heartbeat_active: false,
          pending_requests: ["pause"],
          paused_since: "2026-10-06T09:00:00Z",
          pause_stale: false,
        },
      },
      coverage: ENRICHMENT_COVERAGE_RUNNING,
    });

    await page.goto("/scraper");
    await expect(page.getByTestId("backfill-paused-since")).toContainText("pausado desde ");
    await expect(page.getByTestId("backfill-pause-stale")).toHaveCount(0);
  });
});
