---
title: FAQ
description: Common issues and how to resolve them.
---

### "Cannot connect to PostgreSQL"

Check that the database is running: `docker compose up -d db`. Verify `DATABASE_URL` in `.env` points to `postgresql://docforge:localdev@localhost:5432/docforge` (or your custom value).

### "HF_TOKEN required" or model download fails

The embedding model `google/embeddinggemma-300m` is gated on Hugging Face. Create a token at <https://huggingface.co/settings/tokens>, accept the model license at <https://huggingface.co/google/embeddinggemma-300m>, and set `HF_TOKEN=hf_...` in `.env`.

### "No results found" after ingest

Run `docforge status` to confirm sources and chunks exist. If counts are zero, check the ingest logs for per-source failures — the summary at the end lists sources that failed.

### First ingest / first container start is very slow

The first run downloads the 300M embedding model (~1.2 GB) from Hugging Face. Locally, the model is cached at `~/.cache/huggingface/`. In the Docker image, the cache is at `/app/.cache/huggingface/` — **mount this as a volume** so container restarts do not re-download:

```bash
docker run -v docforge-hf-cache:/app/.cache/huggingface ...
```

### "Ingest skipped everything"

docforge skips sources whose `content_hash` matches the stored hash (no changes detected). To force re-ingest, clear the hash:

```sql
UPDATE sources SET content_hash = NULL;
```

Then run `docforge ingest`.

### How do I remove a source from the index?

Edit `sources.yml` to remove the entry, then run:

```bash
docforge ingest --purge-orphans           # dry run (safe)
docforge ingest --purge-orphans --confirm # actually delete
```

### Can I use a different embedding model?

Set `embedding_model` in `docforge.yml`. Anything `sentence-transformers` can load works, but the schema has a hard-coded `vector(768)` dimension — changing to a differently-sized model requires a migration (`ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(N)`) and a full re-embed.

### How do I know if retrieval quality is good enough?

Ship a ground-truth query set and run `python -m docforge.scripts.eval_search`. It reports recall@1, recall@5, and MRR. Use it for **drift detection** (compare against a baseline after changes), not as an absolute quality threshold — the metric magnitude depends on how closely your ground-truth queries match source titles.

### Where do issues and questions go?

- Bug reports and feature requests: [GitHub Issues](https://github.com/GranatenUdo/docforge/issues) (use the structured templates).
- Open-ended questions, ideas, "show and tell": [GitHub Discussions](https://github.com/GranatenUdo/docforge/discussions).
- Security: email `tobias.ens@proton.me` per [`SECURITY.md`](https://github.com/GranatenUdo/docforge/blob/master/SECURITY.md).
