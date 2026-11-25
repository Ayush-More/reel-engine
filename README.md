# reels-engine (Phase 1 starter)

Generates and validates a Reel project (script, beats, scene plan) from a topic, fully offline with the
mock LLM, and shows what a publish *would* do. Voice, alignment, rendering and Instagram are defined as
stages that are **blocked** (never "succeeded") until their phase is built.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # pydantic, pyyaml, tenacity, httpx, pytest
cp .env.example .env               # only needed for real providers
pytest                             # unit + Phase 1 end-to-end test
reels new --topic "What are AI Tokens and how do LLMs actually read text?"
reels status <job_id>
reels validate examples/tokens_reel.json
reels publish <job_id> --dry-run   # shows blocked reasons (no QC, no approval)
reels schema                       # exports JSON Schemas for the Remotion renderer
```
Real LLM: set `llm.provider: anthropic` in `config/settings.yaml`, `pip install -e ".[llm]"`, export `ANTHROPIC_API_KEY`.

## Layout
`src/reels/contracts` (Pydantic, single source of truth) · `scripting` (LLM interface + repair loop) ·
`validation` (deterministic script rules) · `alignment` (caption grouping, retime to audio) ·
`publishing` (guard + dry-run adapter, live stub) · `storage` (SQLite job store, atomic artefacts) ·
`monitoring` (JSON logs with redaction) · `orchestrator.py` · `cli.py` (argparse; swap to Typer if preferred).

## Status of this starter
- Implemented: contracts, example Reel, rules, caption grouping, retime, job store, resume, logging, dry-run publisher, CLI.
- Stubs (blocked on purpose): ElevenLabs TTS, forced alignment, Remotion render, thumbnail, QC gates, approval UI, Instagram live publisher.
- The CLI uses argparse (stdlib) to keep the dependency surface small.
