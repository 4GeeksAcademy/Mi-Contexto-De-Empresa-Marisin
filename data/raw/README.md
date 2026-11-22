# `data/raw` folder

This folder is intended for **raw data** related to the company: dumps, exports, sample files, event samples, or untransformed datasets.

- **Main purpose**: serve as a landing zone or reference for original data before pipelines process it.
- **Recommendation**: document each dataset’s origin, format, expected size, privacy/PII considerations, and how it is versioned (ideally avoiding sensitive data in the repository).

> _Spanish version: [README.es.md](./README.es.md)._

## `rfp/` — RFP PDFs uploaded from the backoffice (Milestone 9)

Each PDF uploaded from the backoffice **RFPs** page (`POST /rfp/tickets`) is stored as `data/raw/rfp/<rfp_id>.pdf`. It is a runtime artifact of the intake process: **not versioned** (`.gitignore`); the BRIEFING sample PDFs are uploaded through the UI, not pre-seeded. The MarkItDown Markdown lives in PostgreSQL (`rfp_tickets.markdown`). Design: `docs/rfp-intake/rfp-intake-design.md`.
