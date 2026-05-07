# docforge scripts

Operator scripts. Run with `python -m docforge.scripts.<name>`.

## eval_search — retrieval quality measurement

Measures how well docforge retrieves the expected source for each query in a
ground-truth set. Reports recall@1, recall@k, and mean reciprocal rank.

### Run against the live Azure deployment

```bash
python -m docforge.scripts.eval_search \
  --api-url https://your-docforge-deployment.example.azurecontainerapps.io \
  --ground-truth path/to/ground_truth.yml \
  --user your.name --team your-team --area your-area \
  --k 5
```

### Running against an Entra-protected deployment

If the target API has `auth.mode: entra` enabled, pass `--audience`:

```bash
az login --tenant <your-tenant-id>
python -m docforge.scripts.eval_search \
  --api-url https://... \
  --ground-truth .../ground_truth.yml \
  --user your.name --team your-team --area your-area \
  --audience api://<app-id> \
  --k 5
```

`DefaultAzureCredential` silently picks up the `az login` token and attaches it as a Bearer header on each request.

### Ground truth format

YAML with a `queries` list. Each entry is a natural colleague query and a
substring expected to appear in the matching source's title:

```yaml
queries:
  - q: "how do retries work"
    expected_title_contains: "HTTP error handling guidelines"
```

See your team's own ground-truth YAML for the deployment-specific set.

### Interpreting results

There is **no pass/fail threshold**. Recall magnitude depends on the authoring
style of the ground-truth set — a query set that matches source titles word-for-word
will score ~100% regardless of retrieval quality; a query set in natural colleague
phrasing will score lower even on a perfect system.

**First run -> record the baseline.** Commit the reported recall@1, recall@5, MRR
and the current `sources.yml` commit SHA to your team's baseline file (e.g.,
`eval/baseline.md` in your deployment repo).

**Future runs -> compare against the baseline.** If metrics drop materially,
investigate: did `sources.yml` change? Did ingest drift? Did embeddings change?
If metrics rise, consider re-baselining.

### When to re-baseline

- `sources.yml` changed (additions, removals, tag edits)
- Embedding model changed
- Ranking weights (`tag_match_weight`, `org_tag_weight`) changed
- Ground truth rewritten
