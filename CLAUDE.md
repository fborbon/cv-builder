# cv-builder notes for Claude

- AI-assisted features (e.g. cover-letter polishing/elaboration) use the Anthropic API
  (model `claude-haiku-4-5-20251001`) called from app.py via the `anthropic` SDK.
  Key is read from `ANTHROPIC_API_KEY` in a local `.env` (gitignored, see `.env.example`).
  This is the default approach for any future AI text-generation needs in this app —
  no need to ask again before adding similar Anthropic-backed endpoints.
