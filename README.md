# reels-engine (Phase 1 + local Phase 2)

Generates and validates a Reel project (script, voice, alignment, captions, video, cover, and QC) from a
topic. Phase 2 defaults to local mock voice/alignment and a fixture renderer; ElevenLabs and Remotion can
be enabled explicitly. Publishing remains a dry-run only.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # includes Pillow and the packaged FFmpeg binary
npm --prefix renderer install
cp .env.example .env               # only needed for real providers
pytest                             # unit + Phase 1 end-to-end test
reels new --topic "What are AI Tokens and how do LLMs actually read text?"
reels status <job_id>
reels validate examples/tokens_reel.json
reels render <job_id>              # mock voice/render; writes MP4, cover, and QC report
reels render <job_id> --mode remotion
reels publish <job_id> --dry-run   # Phase 3 approval/live publish remain unavailable
reels schema                       # exports JSON Schemas for the Remotion renderer
```
Real LLM: set `llm.provider: anthropic` in `config/settings.yaml`, `pip install -e ".[llm]"`, export `ANTHROPIC_API_KEY`.
Real TTS/alignment: set `voice.provider` and `alignment.provider` to `elevenlabs`, and provide
`ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`. The mock audio track is a synthetic tone fixture, not speech.

## Layout
`src/reels/contracts` (Pydantic, single source of truth) · `scripting` (LLM interface + repair loop) ·
`validation` (deterministic script rules) · `alignment` (caption grouping, retime to audio) ·
`publishing` (guard + dry-run adapter, live stub) · `storage` (SQLite job store, atomic artefacts) ·
`monitoring` (JSON logs with redaction) · `orchestrator.py` · `cli.py` (Typer commands).

## Phase 2 notes
- Remotion's typed schema and React components cover all 17 current template enum values; local font licensing and visual polish remain deployment work.
- The fixture renderer makes valid H.264/AAC output without a browser. Use `--mode remotion` for composition-based output.
- Remotion requires its browser runtime; run `npx remotion browser ensure` from `renderer/` before first render.
- QC gates fail closed. The Phase 1 dry-run publisher still requires the separate Phase 3 approval/live publishing work.
