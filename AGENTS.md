# zen-harness

A CLI that lets coding agents drive the user's real Zen browser over WebDriver BiDi. User-facing docs: `README.md`; agent setup: `install.md`; the skill agents load: `src/zen_harness/SKILL.md`.

## Develop

```bash
uv sync
uv run pytest -q          # runs snippets against a headless Zen on a throwaway profile
ZH_TEST_PORT=9361 uv run pytest -q   # pick another port to run suites side by side
```

Tests and experiments must never touch the user's running Zen: use throwaway profiles and ports other than 9222.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `Astatine-213-Tian/zen-harness`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
