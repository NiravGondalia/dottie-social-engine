# CLAUDE.md -- MiloAgent

MiloAgent is an AI growth bot (Reddit + Telegram automation) for the SoClose fleet.
Stack: Python 3.11 / FastAPI dashboard (`dashboard/web.py`) / SQLite (`core/database.py`) /
orchestrator engine (`core/orchestrator.py`). Prod: systemd, fronted at https://milo.soclose.co,
internal port 8420. Owner-only admin dashboard (Bearer-token auth from `POST /api/auth/login`).

> Never use em dashes anywhere. Use `--`.

## Neo Connector (auto)
Ce projet expose `NEO_CONNECTOR.md` : le manifeste machine-lisible de TOUS ses
endpoints/auth/env, consommé par NeoBot pour se câbler automatiquement.
- RÈGLE : à chaque ajout/suppression/modif d'un endpoint, d'une auth ou d'une env var,
  régénère le manifeste via `/neo-connector` (ou le prompt dans .claude/skills/neo-connector).
- Ne jamais éditer NEO_CONNECTOR.md à la main : il est généré.
- Le hook pre-commit (.git/hooks/pre-commit) avertit si des routes ont changé sans MAJ du manifeste.
