# Sapcon CRM — Implementation Plan

## Stack choice: Python (FastAPI) + Supabase Postgres

**Why Python over Node/TS:**
- Self-hosted Whisper (`faster-whisper`), the Anthropic SDK, `sentence-transformers`, and trigram/fuzzy-matching libraries (`rapidfuzz`, or Postgres `pg_trgm` directly) are all first-class in Python, and the extraction pipeline is the riskiest/most iterative part of this build — a REPL-friendly language matters more here than framework ergonomics.
- No frontend framework needed yet (step 5 is a "minimal read surface" — likely server-rendered HTML or a CLI/Streamlit view, not an SPA), so there's no forcing function toward a JS backend for isomorphic code-sharing.
- FastAPI gives us Pydantic models for free, which double as the *forced structured output* schema for the Claude extraction call (same model, two jobs: API contract + LLM output contract).
- Your uncle is not a developer and won't touch this repo — implementation language is purely our call, optimizing for build speed and pipeline debuggability.
- Supabase's Python client is solid and RLS/auth (needed eventually per your schema comment on `assigned_to`) works the same regardless of backend language.

## Cost policy (added 2026-08-26)

Default to open-source/free tools over paid APIs except where quality genuinely depends on it:

| Piece | Tool | Paid alternative avoided |
|---|---|---|
| Transcription | self-hosted `faster-whisper`, run locally in-process (no server) | OpenAI Whisper API |
| Entity-resolution matching | local `sentence-transformers/all-MiniLM-L6-v2` embeddings, as a second signal alongside `pg_trgm` | a paid embedding API (OpenAI/Cohere) |
| Extraction | swappable provider (`EXTRACTION_PROVIDER` env var): **Gemini free tier for dev**, **Claude Haiku 4.5 for production** | — |
| Hosting/orchestration | no server at all needed yet (see below); free-tier options only when one is needed | a paid VM/server |

Reasoning per line item, plus where I'd push back or refine — see **Flags on the cost policy** below.

> **HARD GATE — added 2026-08-26, do not forget this:** real meeting recordings/transcripts must **never** go through the free-tier Gemini extraction path. Google's free tier (AI Studio) permits using submitted content to improve their models — fine for the synthetic test transcripts in `tests/fixtures/`, not acceptable for real business/relationship data about real companies and contacts. Before the first real recording is processed, switch `EXTRACTION_PROVIDER=anthropic` in `.env` (Anthropic credit will be added at that point). Until that switch happens, `EXTRACTION_PROVIDER` must stay `gemini` for dev/testing only.

**Supporting choices:**
- `psycopg`/`sqlalchemy` (or just the Supabase Python client) for DB access; raw SQL for the recursive CTE traversal query since ORMs fight you on recursive CTEs.
- Migrations via plain numbered `.sql` files run through a small local script (`scripts/run_migrations.py`) rather than the Supabase CLI — avoids a second login flow, tracks applied files in a `schema_migrations` table.
- `pg_trgm` extension in Postgres for trigram similarity (native, no external library needed for the fuzzy match itself — Python just calls `SELECT similarity(...)`), as the primary/first-pass entity-resolution signal.
- `sentence-transformers/all-MiniLM-L6-v2` (downloaded once, runs locally, no API calls) as a secondary semantic-similarity signal for entity resolution, computed and compared in Python — at hundreds-of-entities scale a brute-force cosine-similarity scan is fast enough, so no `pgvector` extension or vector column needed. Revisit only if the entity count grows into the tens of thousands, which is unlikely for one person's contact base.
- `faster-whisper` for transcription, called directly from the ingestion script — since capture is local audio files for now (per the spec), there's no server involved at all: transcription happens in the same process as everything else, on your own machine, when you run `scripts/ingest_audio.py`.
- Config for the relation-type vocabulary lives in one YAML/JSON file (`config/relation_types.yaml`) imported into the extraction prompt template — swapping vocabulary is editing a list, not the prompt logic.

## Proposed file/folder structure

```
Sapcon Personal Software/
  PLAN.md
  .env.example
  pyproject.toml                  # or requirements.txt if you prefer
  config/
    relation_types.yaml           # placeholder vocabulary, swappable
  migrations/
    0001_init_schema.sql
    0002_pg_trgm.sql
    ...
  app/
    __init__.py
    db.py                         # connection/session handling
    models.py                     # Pydantic models (entities, meetings, relations, tasks)
    transcription/
      whisper_client.py           # wraps faster-whisper, runs in-process, no server
    extraction/
      prompt.py                   # builds the extraction prompt from config/relation_types.yaml
      schema.py                   # forced-output Pydantic schema for the Haiku call
      extractor.py                # one function: transcript -> structured triples+tasks
      resolve_dates.py            # relative_due -> absolute date, in app code
    entity_resolution/
      matcher.py                  # trigram score (primary) + local MiniLM embedding score (secondary) against existing entities
      confirm_queue.py            # CLI prompt for medium-confidence matches
    graph/
      traversal.py                # recursive CTE wrapper: how X connects to Y
      centrality.py               # degree count/group-by
    tasks/
      due_dates.py                # overdue status logic
    leads/
      gating.py                   # hearsay-count promotion logic
    read_surface/
      cli.py                      # step 5: meeting log / contact profile / contour view
                                   # (or a minimal FastAPI + server-rendered templates —
                                   #  decide in step 5 based on how it feels to use)
  scripts/
    ingest_audio.py                # CLI entrypoint: local audio file -> full pipeline
  tests/
    fixtures/                      # your 5-10 sample recordings + expected extraction output
    test_extraction.py
    test_entity_resolution.py
    test_graph_queries.py
    test_lead_gating.py
```

## Build order (matches your 7 steps, with notes on what each step actually delivers)

1. **Schema + migrations** — write the 4 tables exactly as specified, plus `pg_trgm` extension + a trigram index on `entities.canonical_name` (and probably a GIN index on `aliases`) since step 3 depends on fast similarity search. Apply to a fresh Supabase project. Deliverable: migrations run clean, tables exist, you can eyeball them in Supabase Studio.

2. **Extraction pipeline against local test audio** — local `faster-whisper` transcription -> Haiku 4.5 structured extraction -> print raw JSON output (no DB writes yet). This is where we validate the prompt against your real recordings before anything downstream depends on its output shape. Deliverable: run `scripts/ingest_audio.py <file>` on your 5-10 recordings, inspect extracted triples/tasks/relative-dates side by side with the transcript, iterate on the prompt until extraction quality looks right to you.

3. **Entity resolution + confirm-queue** — take step 2's output, resolve each mentioned entity against `entities` table via trigram score plus a local MiniLM embedding score, auto-link/queue/create per your thresholds, write confirmed rows to DB. Deliverable: run the same test recordings end-to-end into the DB; walk through the CLI confirm-queue live with you on ambiguous matches to tune thresholds.

4. **Graph queries** — recursive CTE for path-finding between two entities, plain aggregate query for degree/centrality. Deliverable: query "how does X connect to Y" and get a real path back from your test data; query degree ranking and see it match your intuition about who's central.

5. **Minimal read surface** — meeting log (chronological), contact profile (entity + its relations + its tasks), contour view (a rendering of the graph traversal from step 4). Deliverable: something you can actually look at after each of your first real production meetings, not just query results in a terminal.

6. **Tasks and due-date logic** — write extracted tasks to `tasks` table, resolve `relative_due` to absolute `due_date` at write time, background/on-read logic to flip `status` to `overdue` when `due_date` has passed. Deliverable: a task extracted from a recording shows up with the correct absolute date and flips to overdue correctly.

7. **Lead gating logic** — direct meeting mention -> lead; single hearsay -> "unverified" flag; second independent hearsay -> promote. This needs to query existing `relations` rows (by `provenance`) at extraction-write time, so it naturally sits after entity resolution and DB writes are solid. Deliverable: feed two separate recordings that hearsay-mention the same unmet person and watch it promote on the second one.

I'll stop after each step for you to test on real data before starting the next one, per your instruction.

## Ambiguities / things I'd flag or do differently

1. **`relations.status` — who sets `superseded`/`disputed`, and when?** The schema has the field but nothing in the spec says what triggers a transition. My assumption: this is manual for now (you or a future review step marks a relation superseded/disputed) and step 7's automatic promotion only ever writes `active`. Flag if you had automatic contradiction-detection in mind — that's a meaningfully bigger feature (need to define what "contradicts" means for each relation type) and I'd treat it as explicitly out of scope alongside WhatsApp/multi-user/etc. unless you say otherwise.

2. **RESOLVED — hearsay independence.** Independent corroboration requires two hearsay relation rows with the same `(source_id, relation_type, target_id)` where both `meeting_id` differs AND the reporting contact differs. "Reporting contact" = the `primary_contact_id` of each relation's `meeting_id` (no schema change needed — `reported_by` is derived by joining `relations.meeting_id -> meetings.primary_contact_id`, not a new column). The same contact repeating a claim across two meetings is one source, not two, and does not promote.

3. **Entity resolution confidence thresholds are unspecified.** I'll pick starting thresholds (e.g. trigram similarity ≥0.7 = auto-link, 0.4–0.7 = confirm-queue, <0.4 = new entity) and we tune them against your real recordings in step 3 — this genuinely can't be decided in the abstract, it needs your data.

4. **`meetings.primary_contact_id` is a single FK, but a meeting could plausibly involve multiple people.** I'll treat "primary contact" as literally that — the main person your uncle met with — and let *other* attendees surface as entities linked via relations extracted from the transcript, rather than trying to model a meetings-attendees join table now. Flag if you actually want multi-attendee meetings modeled explicitly; that's a schema change (join table), better to decide before step 1 lands than to migrate later.

5. **`tasks.assigned_to` is nullable with a future `users` table.** Since it's single-user right now, I'll leave every task's `assigned_to` NULL and treat all open tasks as implicitly "your uncle's" — no interim placeholder value, since a placeholder would need cleanup later.

6. **Audio file format/naming for local ingestion isn't specified.** I'll assume you'll hand me files as e.g. `.m4a`/`.mp3`/`.wav` with the meeting date and contact derivable either from filename or from you telling me per-file at ingestion time — let me know which you'd prefer once you send the sample recordings, or I'll just ask you inline per file for step 2.

7. **RESOLVED — degree/centrality.** Relations stay directional (no auto-symmetrizing at extraction time). `graph/centrality.py` implements two distinct queries, not one number:
   - **Coarse total degree** (in + out, relation-agnostic) — rough "how connected is this entity" signal, via `UNION ALL` over `source_id`/`target_id` grouped by entity.
   - **Relation-type + direction-specific counts** — the metric that actually answers real questions (e.g. "which contractor has the most end-users" = count of `end_user_of` edges pointing *into* an entity; "how many companies does X contract for" = count of `contractor_for` edges pointing *out* of X). Grouped by `(entity_id, relation_type, direction)`.
   Most real queries need the second kind. The read surface (step 5) and any future reporting should default to relation-type-specific counts, with coarse total degree available as a secondary sort/filter signal only.

8. **Where does dedup happen if the same meeting produces the same triple twice** (e.g. transcript rambles and Haiku extracts "A works_at B" twice)? I'll add an application-level dedup check (same source/target/relation_type/meeting_id) before insert rather than a DB unique constraint, since a unique constraint on that tuple would also block legitimate re-statement across *different* meetings (which is fine and expected — it's how corroboration/promotion works).

## Flags on the cost policy

1. **Transcription — no quality tradeoff here, full agreement.** OpenAI's Whisper API runs the same open-source Whisper model weights available to self-host — it isn't a distinct, improved model. Self-hosting via `faster-whisper` (CTranslate2-based, pure Python install, no build toolchain needed on Windows) should match API quality exactly, at zero marginal cost. I'd start with the `small` or `medium` multilingual model — your uncle's meetings likely include Hindi/English code-switching, and Whisper's multilingual models handle that reasonably; we'll confirm against your real recordings in step 2 and size up to `large-v3` only if accuracy on code-switched audio needs it. No server needed at all right now: since capture is local files (not remote uploads), transcription just runs in-process on your machine when you invoke the ingestion script — the "persistent process on a free-tier VM" contingency in your policy doesn't apply until we build remote capture (out of scope per the spec).

2. **Entity resolution — I'd add one more free tool, not swap to embeddings alone.** `all-MiniLM-L6-v2` embeddings are good at *semantic* similarity (different wording, same meaning) but not at what I expect to be the dominant failure mode here: **spelling/transliteration variants of Indian proper nouns** (e.g. "Shrivastava" vs "Srivastava", "Rajesh" vs "Raj"). Trigram similarity (already in the plan) actually handles that better than embeddings do, since it's character-level. A **phonetic algorithm (double metaphone)** — also free, no model download, a few lines of code — targets that specific failure mode more directly than embeddings would. My plan: keep trigram as the primary signal, add double metaphone as a cheap second signal, and hold off on installing `sentence-transformers` (which pulls in `torch`, a heavy dependency — hundreds of MB) until step 3 testing against your real data shows trigram+phonetic actually missing matches that embeddings would catch. If you'd rather I just build the embedding path from the start since you already know you want it, say so and I'll add it in step 3 directly instead of gating on evidence of need.

3. **Hosting/orchestration — Supabase Edge Functions don't fit this stack; flagging before it causes a wasted detour.** Edge Functions run on Deno (TypeScript/JavaScript only) — they can't execute `faster-whisper`, `sentence-transformers`, or any of our Python pipeline code. So they're not a like-for-like substitute for "a separate paid server" here; adopting them would mean rewriting the core pipeline in TypeScript, which contradicts the Python stack rationale above. Bigger point: **we don't need any server or hosting decision for steps 1–6.** Capture is local audio files per the spec, so everything (transcription, extraction, entity resolution, graph queries) runs as local Python scripts against Supabase Postgres + the Anthropic API — no persistent process, no hosting cost, paid or free. The only step that might eventually want a persistent surface is step 5 (minimal read surface), and since this is a personal prototype you're running yourself for now (see project memory on prototype-vs-production), a locally-run CLI or `uvicorn`/Streamlit dev server is enough — nothing to deploy. If a real hosting need shows up later (e.g. once remote capture like WhatsApp is in scope, which is explicitly deferred), I'd recommend a free-tier host that actually runs Python (Render/Fly.io free tier) over Edge Functions, and reserve that decision until it's real.

## Decisions locked in

- **Supabase project**: created, migrations applied (step 1 done).
- **Test recordings**: not available yet. Step 2 built/validated the extraction pipeline against synthetic sample transcripts (`tests/fixtures/`); real recordings swap in whenever you send them — subject to the **HARD GATE** above (Anthropic only, never free-tier Gemini, once real data is involved).
- **Tooling**: `pyproject.toml` + `uv`, no override.
- **Hearsay independence** and **degree/centrality**: resolved above (ambiguities 2 and 7).
- **Extraction provider**: swappable via `EXTRACTION_PROVIDER` env var (`gemini` for dev, `anthropic` for production) — see cost policy and hard gate above.
- **Relation-type direction correctness (step 2 review, 2026-08-26)**: an early pass produced mirrored/reversed-direction triples for the same fact (e.g. both `A distributor_for B` and `B end_user_of A`) and inconsistent direct/hearsay labeling. Fixed by: (1) giving each relation type in `config/relation_types.yaml` an explicit direction description + concrete example, consumed by the prompt; (2) instructing the model not to emit mirrored duplicate triples; (3) redefining direct/hearsay around whether the *informant* has firsthand knowledge, not whether every named entity was physically present; (4) setting `temperature=0` on both providers, since structured extraction should be deterministic. Verified stable across repeated runs on both fixtures after the fix.
- **Provenance/certainty conflation bug (found via the Patil correction test, fixed 2026-08-26)**: the round 1 fix above still conflated two independent axes in the `hearsay` definition — "is the informant firsthand?" (provenance) vs. "is the fact settled or tentative?" (certainty) — by saying uncertainty is "exactly what hearsay is for". This wrongly tagged Suresh (present, describing his own company's tentative future plan to become an end user) as `hearsay`, when it should be `direct` — a real correctness bug, not a stylistic one: a company stating its own buying intent is the *strongest* kind of lead, and mistagging it hearsay would filter it out of lead-gating as unverified. Fixed by rewriting the prompt to state explicitly that provenance is about informant firsthand-ness only, never about certainty, with worked examples for both axes (Ambuja = direct despite the named entity being absent; Suresh/Patil = direct despite the fact being tentative; Shree Distributors = hearsay, third-party and unverified). Tentativeness itself is still not captured as a separate structured field — only extracted as natural language within the relation, same as before. If lead-gating (step 7) later needs to distinguish "confirmed intent" from "vague maybe" as a queryable signal, that's a dedicated field to add then, not something to smuggle into provenance. Verified stable across 3 repeated runs on both original fixtures plus the specific Patil case that exposed the bug (all 3 runs now correctly `direct`, previously flipped to `hearsay`).
- **Standard validation method for extraction quality: re-run 3x and check for drift, not a one-time pass.** This is how the direction/hearsay-flakiness bugs above were actually caught — a single run looked fine and hid a bug that only 2 of 3 repeated runs exposed. `temperature=0` reduces but does not eliminate run-to-run variance. This applies to real recordings too, not just synthetic fixtures: before trusting an extraction from a real meeting recap (especially early on, or after any prompt/config change), re-run it a few times and check the triples/tasks/dates are stable, not just plausible-looking on one pass.
- **Step 3 (entity resolution) done, 2026-08-26.** Extraction schema gained an `entities` list (name + type) so `entities.entity_type` has somewhere to come from — the model classifies each mentioned entity once, in the same call. `app/entity_resolution/` implements trigram+phonetic scoring, the confirm-queue CLI, and DB writes; `scripts/ingest_audio.py` now does a full ingest (meeting + relations + tasks) by default, with `--dry-run` to fall back to step 2's print-only behavior. Verified end-to-end on both fixtures: auto-linking, the confirm-queue (both the link and reject-and-create-new paths), and alias recording all work; the cross-meeting hearsay corroboration case (`Shree Distributors` reported independently in both fixtures) resolved to the same entity row as intended, exactly what step 7 will need. Also noted `gemini-2.5-flash` had a 20-req/day free-tier cap and has since been superseded — default Gemini model bumped to `gemini-3.5-flash-lite`.
- **Note: the live Supabase project now has the two fixture meetings in it** (test/synthetic data, not real). Fine to leave for continued dev, but say the word before real data starts flowing if you want a clean slate — a quick reset script (truncate all 4 tables) takes two minutes to write.
- **Failure handling added, 2026-08-26**: `migrations/0003_ingestion_failures.sql` + `app/ingestion/failures.py`. Any failure in `scripts/ingest_audio.py` past DB-connect (extraction, resolution, or the writes themselves) logs a loud stderr banner, classifies the error (`rate_limit`/`network_error`/`api_error`/`validation_error`/`unknown_error`, checked against the real installed SDK exception classes), persists a retryable row to `ingestion_failures`, falls back to a local JSON file if the DB itself is unreachable, and exits non-zero. Verified with a real forced failure: correct classification, zero partial writes (rollback confirmed via row counts), non-zero exit.
- **Step 4 (graph/contour queries) done, 2026-08-26.** `app/graph/traversal.py`: recursive-CTE shortest path between two entities, treating relations as traversable in either direction (connectivity, not directional flow), while each step still records the real relation_type/direction/provenance so a path reads like an explanation, not just a node list. `app/graph/centrality.py`: both metrics from ambiguity #7 — coarse total degree and relation-type+direction-specific counts — with one correctness fix baked in: both dedupe to **distinct** `(source, relation_type, target)` edges before counting, since the same fact can be inserted as multiple relation rows (one per corroborating meeting, needed for step 7) and a raw row count would inflate degree for anything mentioned repeatedly rather than measuring actual connectivity. Verified against real data: multi-hop paths correct in both directions (including a 4-hop path requiring two reversed traversals), same-entity and no-path-within-depth edge cases correct, and the dedup fix confirmed directly (2 raw corroborating rows for the same edge correctly counted as degree 1, not 2). `scripts/graph_query.py` exposes `path`, `degree`, and `relation-counts` subcommands.
- **Step 5 (web interface) started, 2026-08-27.** Stack: FastAPI + Jinja2 (server-rendered, no client-JS framework or CDN dependency — matters for a phone on patchy travel connectivity), hand-rolled mobile-first CSS, talking to the DB directly via the existing `app/` package (no PostgREST layer — FastAPI is a trusted backend, that tradeoff only matters once there's untrusted browser-direct access, deferred to multi-user). **Refactor done first, as required**: `app/ingestion/pipeline.py` now holds `ingest_new_meeting`/`append_correction`, shared by the CLI and the web app — one code path for corrections, not two. **Real bugs found and fixed while building, not just plumbing**: (1) Starlette's `TemplateResponse` API changed — `request` is now a required first positional argument, not embedded in the context dict; the old pattern silently passed a dict where a template name was expected. (2) The confirm-queue reads from stdin, which would hang a web request forever on any medium-confidence match — added `interactive=False` to `resolve_entity()`, which skips the prompt and creates a new entity instead, but durably flags it: a new `entity_review_queue` table (migration 0005, same pattern as `ingestion_failures`) records the new entity id, which existing entity it almost matched, and why, so the future review queue has something real to surface — not just a log line, which was the first cut and wasn't good enough. **Meeting view** (`/meetings/{id}`): renders the same underlying data as the stored plaintext minutes (`app/minutes/generate.py` refactored to share one `fetch_meeting_minutes_data()` between both renderers) as styled HTML, plus the embedded correction form (text or audio) posting through the shared pipeline with `interactive=False`. Verified end-to-end via real HTTP requests and re-queried DB state (not just response text): home page, meeting rendering matches DB exactly, correction success/error paths, and the ambiguous-match flagging path (confirmed a real `entity_review_queue` row lands, and the flash message surfaces it). **Not verified**: the mobile visual layout — the Browser pane's screenshot/click simulation wasn't available this session (client-side state), so CSS responsiveness was reviewed but not eyeballed; said so plainly rather than claiming it.
- **Contact/Company profile done, 2026-08-27** (`/entities/{id}`). `app/graph/entity_view.py`'s `fetch_entity_connections()` is new shared query logic (same distinct-edge dedup rule as centrality) meant to be reused by the Contour view next, not duplicated. Sections, in the order specified: interaction history (meetings referencing this entity via any relation — works uniformly for a person or a company, since a company never has its own `primary_contact_id` meetings), last conversation (most recent meeting's relations + a link to full minutes), open commitments (reusing the same overdue-flagging helper as the Meeting view, now factored into `app/web/helpers.py`), and connections. Deliberately did **not** build a separate "role/company" field that special-cases a `works_at`-shaped relation — that would hardcode a vocabulary assumption the interface is explicitly supposed to survive swapping; a person's employer relation just shows up in Connections like anything else. Meeting view entity names are now clickable links to profiles (required `MeetingMinutesData`'s dataclasses to carry entity ids, not just names — added, and re-verified plaintext `generate_minutes()` output was unaffected). Verified via real HTTP requests + regex-checked hrefs (not just page text) on both a person profile (Rajesh — single connection, correctly not more) and a company/hub profile (Sapcon Instruments — 5 distinct connections in the "in" direction, empty-commitments state renders correctly, the corroborated Shree Distributors edge still counts as one connection not two). **One real design edge case, not yet hit but worth knowing**: interaction history is defined as "meetings with at least one relation touching this entity" — if extraction ever failed to link a meeting's primary contact to any relation in their own meeting, that meeting would be invisible on their profile. Narrow, but a genuine blind spot rather than a guaranteed-safe assumption. (Confirmed this edge case for real, incidentally, while testing the review-flag feature below — a task-only correction with no relation correctly shows "No meetings yet" in interaction history despite the entity having an open commitment.)
- **entity_review_queue surfaced on the profile, 2026-08-27** — view-only, no resolve/merge action yet, per instruction. `app/entity_resolution/review_queue.py`'s `fetch_flags_for_entity()` checks both directions: this entity was auto-created ambiguously (shows who it might duplicate), or some other entity was auto-created and almost matched *this* one (shows the reverse link). Rendered as a warning-styled banner at the top of the profile, only when a flag exists. Verified live: re-triggered the ambiguous "Raj Kumar"/"Rajesh Kumar" case via a real correction, confirmed both profile pages show the correct cross-linked banner (with working hrefs each way), and confirmed an unflagged entity (Sapcon Instruments) shows no banner at all. Cleaned up the test entities/task/queue row afterward.
