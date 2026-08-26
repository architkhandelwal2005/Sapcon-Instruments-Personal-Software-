# Sapcon CRM — Implementation Plan

## Stack choice: Python (FastAPI) + Supabase Postgres

**Why Python over Node/TS:**
- Whisper API + Anthropic SDK + trigram/fuzzy-matching libraries (`rapidfuzz`, or Postgres `pg_trgm` directly) are all first-class in Python, and the extraction pipeline is the riskiest/most iterative part of this build — a REPL-friendly language matters more here than framework ergonomics.
- No frontend framework needed yet (step 5 is a "minimal read surface" — likely server-rendered HTML or a CLI/Streamlit view, not an SPA), so there's no forcing function toward a JS backend for isomorphic code-sharing.
- FastAPI gives us Pydantic models for free, which double as the *forced structured output* schema for the Claude extraction call (same model, two jobs: API contract + LLM output contract).
- Your uncle is not a developer and won't touch this repo — implementation language is purely our call, optimizing for build speed and pipeline debuggability.
- Supabase's Python client is solid and RLS/auth (needed eventually per your schema comment on `assigned_to`) works the same regardless of backend language.

**Supporting choices:**
- `psycopg`/`sqlalchemy` (or just the Supabase Python client) for DB access; raw SQL for the recursive CTE traversal query since ORMs fight you on recursive CTEs.
- Migrations via plain numbered `.sql` files run through Supabase CLI (`supabase migration new`) — no need for Alembic/heavier migration tooling at this scale.
- `pg_trgm` extension in Postgres for trigram similarity (native, no external library needed for the fuzzy match itself — Python just calls `SELECT similarity(...)`).
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
      whisper_client.py
    extraction/
      prompt.py                   # builds the extraction prompt from config/relation_types.yaml
      schema.py                   # forced-output Pydantic schema for the Haiku call
      extractor.py                # one function: transcript -> structured triples+tasks
      resolve_dates.py            # relative_due -> absolute date, in app code
    entity_resolution/
      matcher.py                  # trigram scoring against existing entities
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

2. **Extraction pipeline against local test audio** — Whisper transcription -> Haiku 4.5 structured extraction -> print raw JSON output (no DB writes yet). This is where we validate the prompt against your real recordings before anything downstream depends on its output shape. Deliverable: run `scripts/ingest_audio.py <file>` on your 5-10 recordings, inspect extracted triples/tasks/relative-dates side by side with the transcript, iterate on the prompt until extraction quality looks right to you.

3. **Entity resolution + confirm-queue** — take step 2's output, resolve each mentioned entity against `entities` table via trigram score, auto-link/queue/create per your thresholds, write confirmed rows to DB. Deliverable: run the same test recordings end-to-end into the DB; walk through the CLI confirm-queue live with you on ambiguous matches to tune thresholds.

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

## Decisions locked in

- **Supabase project**: not created yet. Step 1 includes creating it and walking through getting the connection string / service key into `.env`.
- **Test recordings**: not available yet. Step 2 will build/validate the extraction pipeline against synthetic/sample transcripts first; real recordings swap in whenever you send them (can happen mid- or post-step-2 without changing the pipeline).
- **Tooling**: `pyproject.toml` + `uv`, no override.
- **Hearsay independence** and **degree/centrality**: resolved above (ambiguities 2 and 7).
