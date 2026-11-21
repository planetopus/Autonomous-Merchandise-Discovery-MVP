# Autonomous Merchandise Discovery

This repository contains the modular MVP for discovering merchandise niches, validating them with public evidence, generating concepts, and producing artwork candidates for visual review.

## Current chunk

Chunks one through eight establish the complete automated funnel through display-only artwork results. The former human-approval implementation remains only as dormant compatibility code for historical review records. Chunk 9 adds bounded
retries, durable stage logs, stage-version provenance, continuous worker mode, and live run-detail
polling. Chunk 10 adds opt-in live provider calls, usage accounting, and AI-assisted Stage 2 identity
expansion plus Stage 3 intersection generation. The default runtime remains fixture-backed unless
`MVP_PROVIDER_MODE=live` and the required API key are configured.

The Create Run page also includes a separate `Social behavior — copy + Grok artwork`
pipeline. It is intentionally one stage: in live mode, one OpenAI structured request uses web search
restricted to the selected Reddit and/or X domains, extracts concrete behavior, and returns
source-backed merchandise text. It does not use the seed library, identity funnel, artwork
generation, or image variants. Fixture mode returns clearly marked deterministic sample output.

## Local setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
streamlit run app.py
```

Run tests with:

```powershell
pytest
```

Verify a configured MongoDB deployment with:

```powershell
python scripts/check_mongodb.py
```

To permanently clear the entire configured MongoDB database, run:

```powershell
python scripts/clear_database.py
```

The command shows the target database and requires typing its exact name. For a deliberate
non-interactive reset, use `python scripts/clear_database.py --yes` only after verifying `.env`.

Process one queued run with:

```powershell
python worker.py --once
```

Keep the worker polling for new runs with:

```powershell
python worker.py --loop --poll-interval 2
```

Set `MVP_MAX_STAGE_ATTEMPTS` in `.env` to change the retry ceiling. A failed stage is retried when
the worker is run again until that ceiling is reached; after that, the run remains failed and is no
longer reclaimed automatically.

Set `MVP_PROVIDER_MODE=live` only when you intend to spend API credits. In live mode,
`OPENAI_API_KEY` enables OpenAI structured outputs for Stages 2–4, 7–10, and 13, plus OpenAI web
search for Stage 6. Stages 1 and 5 remain deterministic, while Stage 8 uses AI only for its
bounded qualitative components and calculates evidence strength and the final total locally.
`OPENAI_API_KEY` also enables the batched structured comparison in Stage 12 and Luna's multimodal
artwork critique in long Stage 16 or compact Stage 8. `OPENAI_IMAGE_DETAIL` controls the vision
detail level and defaults to `high`. `XAI_API_KEY` enables the configured xAI image model for
generation and targeted artwork edits in long Stage 17 or compact Stage 9. `XAI_IMAGE_EDIT_PRICE`
defaults to `$0.022` for edit-cost estimates. Missing keys
continue to use the fixture provider or deterministic fallback. Token costs are estimated from the
configured OpenAI rates; Stage 6 also adds `OPENAI_WEB_SEARCH_PRICE_PER_CALL` (default `$0.01`,
derived from `$10 per 1,000 calls`); xAI image costs are estimated from the configured per-image rate.
Live artwork binaries are downloaded into `ARTWORK_STORAGE_DIR` (default `.artifacts`) behind an
object-storage boundary; fixture artwork remains reference-only and does not perform network I/O.
The final gallery is long Stage 18 or compact Stage 10. Luna's review is not repeated after a Grok
edit; the stage history records the edit as `edited_without_reverification`.

When `MONGODB_URI` is present in `.env`, starting Streamlit performs the same health check and
initialization automatically. MongoDB databases are created lazily, so the app creates an
`_app_metadata` infrastructure collection and the workflow indexes; the configured database then
appears in Compass or `show dbs`.

At runtime startup, the registered JSON seed libraries are imported into MongoDB. The current
libraries are `data/seed_knowledge.json` (MVP Seed Library) and
`data/seed_knowledge_coherent_mashups.json` (Coherent Mashups). Seed records are scoped by
`library_id`, existing records are preserved, and the Create Run page lets you choose which active
library Stage 1 should use. JSON remains the version-controlled source; MongoDB is the runtime
catalog and query source.

The current client demo defaults to `MVP_STOP_AFTER_STAGE=1`. Stage 1 is executed and the run is
persisted as `paused` so later stages do not run until the client approves expanding the funnel.
When a run is created from Streamlit, a process-local background runner advances it independently
of the visible page; the Run Detail view reads and polls the durable MongoDB state. The stop
boundary is shared by Streamlit and the worker. The Social Behavior pipeline has two stages; set
`MVP_STOP_AFTER_STAGE=2` when you want Stage 1's Grok artwork prompt to be executed by its artwork
generation stage as part of the same run.

Copy `.env.example` to `.env` when local credentials are needed. Real credentials belong in environment variables or a local Streamlit secrets file; they must not be committed.

## Secrets

Set these in the environment or in `.streamlit/secrets.toml` (flat keys). Environment variables win when both are present. Leave a value blank to skip that integration.

| Name | Required | Used for |
| --- | --- | --- |
| `OPENAI_API_KEY` | Live research and copy | OpenAI structured outputs, web search, and artwork critique |
| `XAI_API_KEY` | Live sticker images | xAI `grok-imagine-image` generation and edits |
| `REDDIT_CLIENT_ID` | Optional | Reddit app-only OAuth client id |
| `REDDIT_CLIENT_SECRET` | Optional | Reddit app-only OAuth client secret |
| `REDDIT_USER_AGENT` | Optional | Descriptive User-Agent sent with every Reddit request |
| `ETSY_API_KEY` | Optional | Etsy listing counts for the crowded-line check |
| `EBAY_APP_TOKEN` | Optional | Extra eBay Browse API check. Final lines are already searched with the OpenAI web search tool, with no token required |
| `HUMOR_REFERENCE_CSV_URL` | Optional | Fresh top-selling merch CSV. Blank uses the raw GitHub URL of `data/humor_references.csv` on `main`, then the committed file |
| `MVP_TRENDING_SHARE` | Optional | Share of auto identity picks that follow trending buyers, from 0 to 1. Default `0.6`. The Create Run slider starts here |

Reddit uses the client-credentials flow against `oauth.reddit.com` when both `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are set. The reader backs off when `X-Ratelimit-Remaining` is exhausted. If those credentials are absent, live runs fall back to Reddit's public JSON endpoints. Create the script app at `https://www.reddit.com/prefs/apps`. `ETSY_API_KEY` is optional; without it, live mode counts public web results for the phrase plus "sticker", and fixture mode skips the check. Final sticker lines are also searched with the OpenAI web search tool, one quoted phrase at a time plus `sticker OR shirt OR decal`. A page that already sells that line on eBay, Etsy, Amazon, Redbubble, Teepublic, or another shop is flagged `already for sale` with the URL. The search is rate-limited, skipped on errors, and limited to the final candidates. `EBAY_APP_TOKEN` adds the Browse API as an extra check.

`OPENAI_REASONING_MODEL` defaults to `gpt-5`. `gpt-4o-mini` rejects the `filters` parameter on web search, and a live search with a model that does not support those filters fails before the request with a message to switch models.

`data/humor_references.csv` is a market signal: top-selling merch concepts, not a joke sheet. Each run loads it with no cache. A fetch that returns no rows falls back to the committed file; zero rows after that fails the run. The file weights which atlas identities and themes are trending. Funniness comes from `data/ant_ratings.csv` and `data/humor_lab/`. Product wording is still blocked by the copy guard. Extra columns are ignored. Recognized columns include `sticker_text_or_idea` (or `text`), `upvotes`, `sales` / `units_sold` / `trend_score`, `niche` / `identity`, `theme`, `hook`, `subreddit`, and `post_url`. A row whose text contains `(theme)` is a topic. The app fetches `HUMOR_REFERENCE_CSV_URL` when set, otherwise `https://raw.githubusercontent.com/planetopus/Autonomous-Merchandise-Discovery-MVP/main/data/humor_references.csv`. MongoDB collection `humor_references` is an optional extra. Expected document:

```json
{
  "_id": "<sha256 hex of the lowercased, whitespace-collapsed text>",
  "text": "string",
  "upvotes": 0,
  "humor_type": "dark/absurd",
  "niche": "nurses",
  "subreddit": "nursing",
  "post_url": "https://www.reddit.com/...",
  "date_found": "2026-11-21",
  "is_theme": false
}
```

## Design rules

- `entrypoints` contains Streamlit and worker adapters only.
- `application` owns use cases and workflow orchestration.
- `domain/stages` contains one module per pipeline stage.
- `infrastructure/mongo/repositories` is the only place for MongoDB queries.
- `infrastructure/providers` is the only place for external AI and research API clients.
- Stage logic must not import Streamlit, MongoDB clients, or provider SDKs directly.
