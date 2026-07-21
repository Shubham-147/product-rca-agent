# Retrieval Pipeline Plan (offline, built first)

**Branch:** `agent/system-b` · **Owner:** Vinay · **Status:** proposal for staff review
**Related:** [agentic-system-plan.md](agentic-system-plan.md) · [generated-data-overview.md](generated-data-overview.md)

> Built **offline and before the agent.** Retrieval has its own gold and its own
> metric (P/R vs the hidden canonical map). Evaluate it standalone until it clears
> the bar, *then* wire it into the agent — so a failing agent is never ambiguous
> between "bad reasoning" and "bad retrieval".

---

## 1. Principles

- **Offline build / online query.** A `build-index` step runs ahead of time and
  persists artifacts; the agent only *loads and queries* them read-only at runtime.
  Never rebuild at query time.
- **Corpus is static & global.** PRD + taxonomy describe one product — identical for
  all instances. Build the index **once**, reuse everywhere. Artifacts are
  **git-ignored** (deterministically rebuildable from the corpus).
- **No LLM in the pipeline.** Pure IR (sparse + dense + fuzzy fusion). Deterministic,
  free, reproducible. Pin the embedding model + seeds.
- **Measure in isolation.** Its own eval harness scores it vs the hidden canonical
  map *before* the agent is involved.

---

## 2. Two retrieval surfaces

### 2.1 `resolve_events` — the scored RAG (cursed taxonomy → canonical)
The hard, interesting one. Map each of the ~225 firing surface names
(`evt_chkout_init`, `BeginCheckout`, `chckt_strt`, …) to a **canonical concept**.

- **Concept vocabulary (the targets)** are derived from what the system legitimately
  knows: the **funnel steps from the PRD** (`app_open … order_confirmed`) + a small
  set of **technical events** (`crash`, `app_cold_start`, `screen_load`/latency,
  `payment_error`). The hidden `event_canonical_map.json` is **never read by the
  pipeline** — only by the scorer (§4).
- **Two consumers of the resolved mapping:**
  1. the **analytics compiler** uses it to canonicalise raw event names into logical
     steps so `funnel`/`metric_by_segment` can group them;
  2. the **`resolve_events` tool** exposes query → ranked candidates to the agent for
     evidence/reasoning.

### 2.2 `retrieve_spec` — dense RAG over the PRD (intent)
Straightforward. Chunk the PRD by section, embed, persist; query-time top-k. Feeds the
agent the *intent* it needs (SLOs → recognise a regression; "upsell is optional" →
resist the decoy). Lower stakes; not P/R-scored (its value shows up downstream in the
agent's decoy-resistance / mechanism metrics).

---

## 3. The hybrid retriever (why three signals, no cross-encoder yet)

The taxonomy's pathologies need **complementary** signals — this is why dense-only
provably fails (the design-doc claim we'll now *measure*):

| Signal | Catches | Example |
| :-- | :-- | :-- |
| **Dense** (sentence-transformer) | semantic synonyms | `begin_checkout` ≈ `checkout_start` |
| **BM25** (word tokens) | word-level overlap | `start_checkout` → checkout |
| **Char-ngram / fuzzy** (char TF-IDF or token-set ratio) | **abbreviations & typos** — the cursed part | `chkout_init`, `chckt_strt` → checkout |

Fuse with **Reciprocal Rank Fusion (RRF)** → top-1 canonical + a confidence; below a
threshold → `unknown` (better to abstain than mis-resolve). The **char-ngram signal is
the cheap answer to the abbreviations** a dense model misses — likely enough to clear
the bar without a cross-encoder. If the offline P/R still misses, the cross-encoder
reranker is the heavier fallback (D2) — but we add it only when the harness says so.

**Embedding model:** a **local** sentence-transformer (e.g. `BAAI/bge-small-en-v1.5`)
— free, offline, deterministic, no API cost or variance. (OpenAI embeddings are an
option but add a dependency + cost for no reproducibility benefit here.)

**Stack:** `rank-bm25` (sparse) · sentence-transformers + **Chroma** (dense, persisted)
· scikit-learn char-TF-IDF or `rapidfuzz` (fuzzy). All already implied by the design doc.

---

## 4. The offline eval harness (the whole point of doing this first)

A standalone harness that scores the resolver **with no agent and no LLM**:

- **Input:** the resolver's `surface_name → canonical` output over the full taxonomy.
- **Gold:** `data/ground_truth/event_canonical_map.json` (held out; scorer-only).
- **Metrics:** precision / recall / **F1** overall and per-concept; plus recall@k and
  MRR for the ranked variant. Report **coverage** (fraction resolved above threshold).
- **Ablation (the money table):** dense-only vs BM25-only vs +fuzzy vs full-hybrid —
  quantifies each signal's lift and *proves hybrid > dense-only* (the design-doc thesis,
  now a number, not an assertion).
- **Gate:** full-hybrid **P/R ≥ 0.85** on the taxonomy before it's wired into the agent.
  If missed → add the cross-encoder and re-measure (not before).

`eval/run_retrieval.py` — a sibling to the agent scorer, run on a `build-index` output.

---

## 5. Build vs query (the offline/online split)

```
OFFLINE  (build-index, run once)                 ONLINE  (agent runtime, read-only)
─────────────────────────────────               ──────────────────────────────────
corpus/taxonomy/events.jsonl ─┐                  load persisted indexes
corpus/spec/prd.md ───────────┼─► chunk/embed    resolve_events(query) → candidates
corpus/spec/tickets/* ────────┘   build BM25      retrieve_spec(query)  → chunks
                                  build fuzzy      (fast, deterministic, no rebuild)
                                  resolve all names→canonical  (cached mapping)
                                  persist → index/  (git-ignored, rebuildable)
                                  ↓
                          eval/run_retrieval.py  ──►  P/R vs canonical_map (offline gate)
```

- **`agent/retrieval/`**: `loaders.py`, `chunking.py`, `dense.py` (Chroma), `sparse.py`
  (BM25), `fuzzy.py`, `fuse.py` (RRF), `resolver.py` (surface→canonical), `build.py`
  (the offline builder), `query.py` (runtime API for the two tools).
- **`index/`**: persisted Chroma + BM25 + the cached resolved mapping. Git-ignored.
- **Determinism:** pinned embedding model + revision; fixed tokenizer; the build is a
  pure function of the corpus → same corpus, same index.

---

## 6. Where it sits in the phasing

This is **Phase 1a — before the agent (Phase 2)**, inside the foundation:

1. Loaders + dense/sparse/fuzzy + RRF + resolver + `build-index`.
2. `eval/run_retrieval.py` + the ablation table; **hit the P/R gate**.
3. Freeze the retriever; expose `resolve_events` / `retrieve_spec` as agent tools;
   the analytics compiler consumes the cached mapping.
4. *Only then* build the agent on top — standing on retrieval that is already
   measured and good.

**Why first:** the agent's whole event-reasoning ability rests on this. Proving it in
isolation (with an honest ablation) de-risks the agent and gives us the design-doc's
"retrieval ≠ attribution" / "hybrid beats dense" results as clean, standalone numbers.

---

## 7. Open questions for staff

- **Embedding model:** local `bge-small` (my default) vs a larger local model vs OpenAI
  embeddings. Trade recall for cost/latency/reproducibility.
- **Abstain threshold** for `unknown` — tune on the offline harness (precision vs
  coverage).
- **Index artifacts:** git-ignore + rebuild (my default) vs commit for zero-setup repro.
