# Kinetiq V

A connected home workout coach that creates routines around personal goals, coordinates sessions, and tracks progress across phone, browser, Fire OS, Vega and Alexa+.

**Status:** executable platform foundations and the first session-preparation slice; live workout, vision integration, Alexa+ and cloud infrastructure remain under construction.

This repository owns the modular Django product, GraphQL API, clients, PostgreSQL records, Redis cache, business events and Alexa+ MCP. [Kinetiq V Vision](https://github.com/Riippex/kinetiq-v-vision) owns perception and movement analysis.

- [Technology stack](docs/technology-stack.md)
- [Platform clients](docs/platform-clients.md)
- [Architecture](docs/architecture.md)
- [Coaching experience](docs/coaching-experience.md)
- [Routine planning](docs/routine-planning.md)
- [Session preparation and Dynamic mode](docs/session-preparation.md)
- [GraphQL contract](packages/contracts/graphql/schema.graphql)
- [Business events](contracts/events/README.md)
- [Contributor workflow](docs/runbooks/pull-requests.md)
- [Agent skills and graph tools](docs/runbooks/agent-skills.md)

Public documentation lives in docs/. Local private planning belongs in ignored documents/. Repository artifacts are written in English.

## Local development

Install the JavaScript workspace with `npm install`. Start the browser client with `npm run dev:web`, the Expo mobile client with `npm run dev:mobile`, or the Fire OS client with `npm run dev:fire-tv`. See [Platform clients](docs/platform-clients.md) for native Fire OS and Vega setup.

Install and run the backend with `uv sync --project services/backend` and `uv run --project services/backend python services/backend/manage.py runserver`. PostgreSQL and Redis endpoints are configured through `DATABASE_URL` and `REDIS_URL`; copy `.env.example` to `.env` and fill local values without committing secrets.

License: [Apache-2.0](LICENSE). Third-party components retain their own terms.
