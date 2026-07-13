# How PaperTracker Computes Similarity and Scores

This note explains how PaperTracker decides whether a paper is relevant and how
it ranks related-work candidates. I will treat this like an undergraduate
lecture: first the intuition, then the math, then the exact formulas used in the
code.

The main source files are:

- `src/papertracker/relevance.py`
- `src/papertracker/cli.py`
- `src/papertracker/related_work.py`
- `papertracker.toml`
- `projects.toml`

## 1. The Big Idea

PaperTracker has to answer a practical question:

> Given a project topic and a list of fetched papers, which papers are most
> relevant to the project?

It does not answer this by looking for exact keywords only. Instead, it uses an
embedding model. An embedding model turns text into a long list of numbers, also
called a vector. Texts with similar meanings should produce vectors that point
in similar directions.

So PaperTracker compares two kinds of text:

1. The project topic statement.
2. Each paper's title plus abstract.

If the title and abstract point in a similar semantic direction to the project
topic statement, the paper gets a high relevance score. If they point in a
different direction, the paper gets a lower relevance score.

In short:

```text
project topic statement -> embedding vector
paper title + abstract  -> embedding vector
similarity score        -> dot product / cosine similarity
```

## 2. What Text Is Scored?

For each paper, the code builds one string:

```text
<title>. <abstract>
```

For example:

```text
Spatial Reasoning for Embodied Agents. We present a method for agents to
understand rooms, objects, and user gestures in augmented reality...
```

That string is passed to the embedding model.

The project topic statement comes from the active project profile in
`projects.toml`. If a profile does not override a field, defaults can come from
`papertracker.toml`.

For example, the default project topic is a long description of multimodal
embodied agents, 3D environments, XR, spatial reasoning, scene understanding,
avatars, gaze, gesture, and related topics.

This matters because the topic statement is the reference point. Changing the
topic statement changes the vector that every paper is compared against.

## 3. What Is an Embedding?

An embedding is a numerical representation of text.

Imagine every text becomes a point in a very high-dimensional space. A normal
2D point has two numbers:

```text
(x, y)
```

A 3D point has three numbers:

```text
(x, y, z)
```

An embedding has many more dimensions. Conceptually it looks like:

```text
[0.014, -0.082, 0.231, ..., 0.009]
```

You should not interpret one number as meaning exactly "XR" or another as
meaning exactly "robotics." Instead, the whole pattern of numbers captures the
model's learned representation of the text's meaning.

PaperTracker uses `fastembed` with the model configured as:

```toml
embedding_model = "BAAI/bge-small-en-v1.5"
```

The implementation is in `src/papertracker/relevance.py`.

The model is loaded lazily. That means PaperTracker does not load the model when
the program starts. It waits until the first scoring call. The loaded model is
then cached so later scoring calls reuse it.

## 4. Cosine Similarity

Once PaperTracker has two vectors, it needs a way to measure whether they point
in the same direction.

The usual measure for this is cosine similarity.

For two vectors `a` and `b`, cosine similarity is:

```text
cosine_similarity(a, b) = dot(a, b) / (||a|| * ||b||)
```

Where:

- `dot(a, b)` means multiply matching components and add them up.
- `||a||` means the length of vector `a`.
- `||b||` means the length of vector `b`.

If two vectors point in exactly the same direction, cosine similarity is `1`.
If they are unrelated or perpendicular, it is around `0`.
If they point in opposite directions, it can be negative.

For text embeddings, the scores you usually care about are not spread evenly
across the full `-1` to `1` range. In this project, a threshold such as `0.65`
is used as a practical cutoff for "relevant enough."

## 5. Why the Code Uses a Dot Product

In `src/papertracker/relevance.py`, the scoring line is:

```python
float(np.dot(v, t))
```

Here:

- `v` is the paper vector.
- `t` is the topic vector.
- `np.dot(v, t)` is the dot product.

The code comments say that BGE models output L2-normalized vectors. L2-normalized
means each vector has length `1`.

That simplifies cosine similarity:

```text
cosine_similarity(a, b) = dot(a, b) / (||a|| * ||b||)
```

If both lengths are `1`, then:

```text
cosine_similarity(a, b) = dot(a, b) / (1 * 1)
cosine_similarity(a, b) = dot(a, b)
```

So the dot product is already the cosine similarity.

This is why `score_batch()` returns:

```python
[float(np.dot(v, t)) for v in vecs]
```

## 6. A Small Numerical Example

Real embeddings have many dimensions, but we can teach the idea with tiny
3-dimensional vectors.

Suppose the project topic vector is:

```text
t = [0.60, 0.80, 0.00]
```

Suppose Paper A has vector:

```text
a = [0.58, 0.81, 0.05]
```

And Paper B has vector:

```text
b = [0.10, -0.20, 0.97]
```

The dot product for Paper A is:

```text
dot(a, t)
= (0.58 * 0.60) + (0.81 * 0.80) + (0.05 * 0.00)
= 0.348 + 0.648 + 0
= 0.996
```

Paper A is very similar to the topic.

The dot product for Paper B is:

```text
dot(b, t)
= (0.10 * 0.60) + (-0.20 * 0.80) + (0.97 * 0.00)
= 0.060 - 0.160 + 0
= -0.100
```

Paper B points in a very different direction.

PaperTracker does this same idea with real embedding vectors rather than three
numbers.

## 7. The Basic Relevance Filter

The simplest scoring path is in `filter_papers()` in
`src/papertracker/relevance.py`.

It does this:

1. Build `title + abstract` text for every paper.
2. Embed all paper texts.
3. Embed the active topic statement.
4. Compute cosine similarity for each paper.
5. Store the score as `paper["relevance_score"]`.
6. Keep only papers whose score is at or above the threshold.

The important condition is:

```python
if s >= threshold:
    kept.append(paper)
```

The threshold usually comes from the active project profile. In the current
configuration, the default is:

```toml
relevance_threshold = 0.65
```

So if a paper gets:

```text
relevance_score = 0.72
```

it passes a `0.65` threshold.

If it gets:

```text
relevance_score = 0.58
```

it does not pass a `0.65` threshold.

Higher thresholds make PaperTracker stricter. Lower thresholds make it more
inclusive.

## 8. What the Relevance Score Means

The relevance score is a semantic similarity score between:

```text
paper title + abstract
```

and:

```text
active project topic statement
```

It is not:

- a probability that the paper is relevant;
- a measure of paper quality;
- a citation count;
- an LLM judgment;
- a guarantee that the paper belongs in the bibliography.

It is simply a similarity measure in the embedding space.

That makes it useful as a first-pass filter. It is good at catching papers that
use related concepts even if they do not share exact keywords. But it can still
make mistakes, especially when abstracts are vague, use overloaded terminology,
or discuss adjacent fields.

## 9. Batch Scoring

The function is called `score_batch()` because it scores many texts at once:

```python
def score_batch(texts: list[str], topic_statement: str | None = None) -> list[float]:
```

Batching is useful because embedding models are more efficient when they process
multiple texts together.

The function returns one float per input text:

```text
input texts:  [paper1, paper2, paper3]
output scores: [0.71, 0.44, 0.82]
```

The order is preserved. The first score belongs to the first paper, the second
score belongs to the second paper, and so on.

## 10. Caching

There are two caches in the relevance code:

```python
@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
```

and:

```python
@lru_cache(maxsize=32)
def _topic_vector(topic_statement: str) -> np.ndarray:
```

The model cache avoids repeatedly loading the embedding model.

The topic-vector cache avoids repeatedly embedding the same project topic
statement. This matters because related-work ranking may compare the same batch
of papers against the project topic and also against several facet topics.

## 11. Basic Related-Work Ranking

There is another scoring path for related-work mode in `_rank_related_work()` in
`src/papertracker/cli.py`.

This mode still starts with the embedding relevance score, but it also cares
about citation signal and discovery signal.

The formula is:

```text
related_work_score =
    0.70 * relevance_score
  + 0.24 * citation_score
  + channel_bonus
  + semantic_bonus
```

Each part has a role:

- `relevance_score`: how semantically close the paper is to the project topic.
- `citation_score`: how highly cited the paper is relative to the other fetched
  candidates.
- `channel_bonus`: a small bonus if the paper was found through multiple
  discovery sources.
- `semantic_bonus`: a small bonus if one of the discovery sources was
  `"semantic"`.

The paper is still filtered by relevance:

```python
if rel_score >= threshold:
    kept.append(paper)
```

That means citation count can improve ranking among kept papers, but it does not
rescue a paper whose embedding relevance is below the threshold.

## 12. Citation Score

Citation counts can be huge. One paper might have `3` citations and another
might have `3,000`. If PaperTracker used raw citation counts directly, citation
count would dominate everything.

To avoid that, the code uses a logarithmic normalization:

```python
citation_score = math.log1p(citations) / math.log1p(max_citations)
```

`log1p(x)` means:

```text
log(1 + x)
```

The `+1` handles the case where citations are zero.

The denominator is the largest citation count among the current batch of papers.
So the most cited paper in the batch gets:

```text
citation_score = 1.0
```

A paper with zero citations gets:

```text
citation_score = 0.0
```

Papers in between get a value between `0` and `1`.

The logarithm compresses large differences. For example, suppose the most cited
candidate has `1000` citations.

Then:

```text
max_citations = 1000
```

A paper with `10` citations gets:

```text
log(1 + 10) / log(1 + 1000)
= log(11) / log(1001)
approximately 2.398 / 6.909
approximately 0.347
```

A paper with `100` citations gets:

```text
log(101) / log(1001)
approximately 4.615 / 6.909
approximately 0.668
```

A paper with `1000` citations gets:

```text
log(1001) / log(1001)
= 1.0
```

So moving from `10` to `100` citations helps, but not by a raw factor of ten.
This is a common ranking trick because citation distributions are very skewed.

## 13. Discovery Bonuses in Basic Related-Work Mode

The basic related-work formula includes two bonuses.

First:

```python
channel_bonus = min(max(len(discovery_sources) - 1, 0), 2) * 0.03
```

This means:

- If the paper was found from one discovery source, bonus is `0`.
- If found from two sources, bonus is `0.03`.
- If found from three or more sources, bonus is capped at `0.06`.

The cap happens because of:

```python
min(..., 2)
```

Second:

```python
semantic_bonus = 0.03 if "semantic" in discovery_sources else 0.0
```

If the paper was found through a semantic discovery source, it gets another
`0.03`.

These bonuses are small. They are designed to break ties or nudge papers upward,
not overpower the embedding relevance score.

## 14. Basic Related-Work Example

Suppose a paper has:

```text
relevance_score = 0.80
citations = 100
max_citations in batch = 1000
discovery_sources = ["citation", "semantic"]
```

First compute citation score:

```text
citation_score = log(101) / log(1001)
approximately 0.668
```

Then compute the channel bonus:

```text
len(discovery_sources) = 2
channel_bonus = (2 - 1) * 0.03
channel_bonus = 0.03
```

Then semantic bonus:

```text
semantic_bonus = 0.03
```

Now the full score:

```text
related_work_score =
    0.70 * 0.80
  + 0.24 * 0.668
  + 0.03
  + 0.03

= 0.560
  + 0.160
  + 0.030
  + 0.030

= 0.780
```

So this paper would have:

```text
related_work_score approximately 0.780
```

If the threshold is `0.65`, it passes because:

```text
relevance_score = 0.80 >= 0.65
```

Notice that the threshold uses `relevance_score`, not `related_work_score`.

## 15. Faceted Related-Work Ranking

The most detailed scoring path is in `rank_facet_candidates()` in
`src/papertracker/related_work.py`.

This mode is used when related work is organized into facets. A facet is a
subtopic or section-like category, such as:

```text
Benchmarks
Systems
Spatial reasoning
Gesture interpretation
```

Each facet has:

- an `id`;
- a `name`;
- a `description`;
- a `query_hint`.

For each facet, PaperTracker builds a facet topic string:

```python
facet_topic = f"{facet.name}. {facet.description}. {facet.query_hint}"
```

Then it embeds the same paper text against:

1. the overall project topic;
2. each facet topic.

So a paper can have:

```text
project_relevance_score = similarity(paper, project topic)
facet_relevance_score   = similarity(paper, facet topic)
```

This lets PaperTracker ask two related but different questions:

1. Is the paper relevant to the project overall?
2. Is the paper especially relevant to this specific facet?

## 16. Faceted Related-Work Formula

For each paper and matched facet, the formula is:

```text
related_work_score =
    0.42 * facet_relevance_score
  + 0.30 * project_relevance_score
  + 0.18 * citation_score
  + source_bonus
  + multifacet_bonus
  + hit_bonus
```

The largest weight is on `facet_relevance_score`. That makes sense because this
mode is trying to build a faceted bibliography. A paper should score highly for
the specific facet it is being considered under.

The project relevance score still matters. A paper should not be narrowly
similar to a facet phrase while being unrelated to the overall project.

Citation score still matters, but less than semantic relevance.

## 17. Faceted Threshold Rule

Faceted mode uses this condition:

```python
if max(facet_rel, project_rel) < threshold:
    continue
```

This means a paper/facet candidate is kept if at least one of these is at or
above the threshold:

```text
facet_relevance_score >= threshold
```

or:

```text
project_relevance_score >= threshold
```

That is slightly different from basic related-work mode, where the project
relevance score alone must pass.

The faceted rule is more flexible. It allows a paper to be included if it is
very strong for a particular facet, even if its overall project score is a bit
lower. It also allows a generally relevant project paper to survive even if one
facet score is not especially high.

## 18. Faceted Discovery Bonuses

Faceted related-work mode has three bonuses.

### Source Bonus

```python
source_bonus = min(max(len(discovery_sources) - 1, 0), 2) * 0.035
```

This is similar to the basic channel bonus, but the multiplier is `0.035`.

- One source: `0`
- Two sources: `0.035`
- Three or more sources: `0.070`

### Multifacet Bonus

```python
multifacet_bonus = min(max(len(facet_hits) - 1, 0), 3) * 0.025
```

This rewards papers that appear to match multiple facets.

- One facet hit: `0`
- Two facet hits: `0.025`
- Three facet hits: `0.050`
- Four or more facet hits: `0.075`

The intuition is that a paper touching multiple related-work themes may be more
useful in a bibliography.

### Hit Bonus

```python
hit_bonus = 0.04 if facet_id in facet_hits else 0.0
```

This rewards a paper when the discovery process explicitly associated it with
the current facet.

If the paper was not explicitly discovered for that facet but is still being
considered there, it does not get this bonus.

## 19. Faceted Example

Suppose a paper is being scored for the `benchmarks` facet.

Assume:

```text
facet_relevance_score = 0.86
project_relevance_score = 0.78
citations = 100
max_citations in batch = 1000
discovery_sources for this facet = ["semantic", "citation"]
facet_hits = {
  "benchmarks": ["semantic", "citation"],
  "systems": ["semantic"]
}
threshold = 0.65
```

Citation score:

```text
citation_score = log(101) / log(1001)
approximately 0.668
```

Source bonus:

```text
len(discovery_sources) = 2
source_bonus = (2 - 1) * 0.035
source_bonus = 0.035
```

Multifacet bonus:

```text
len(facet_hits) = 2
multifacet_bonus = (2 - 1) * 0.025
multifacet_bonus = 0.025
```

Hit bonus:

```text
"benchmarks" is in facet_hits
hit_bonus = 0.04
```

Full score:

```text
related_work_score =
    0.42 * 0.86
  + 0.30 * 0.78
  + 0.18 * 0.668
  + 0.035
  + 0.025
  + 0.040

= 0.3612
  + 0.2340
  + 0.1202
  + 0.0350
  + 0.0250
  + 0.0400

= 0.8154
```

So the faceted related-work score is approximately:

```text
related_work_score approximately 0.815
```

The candidate passes the threshold because both semantic scores are above
`0.65`:

```text
max(0.86, 0.78) = 0.86 >= 0.65
```

## 20. What Happens When a Paper Matches No Specific Facet?

In faceted mode, the code looks at `facet_hits`, which records which facets the
paper was discovered under.

If a paper has recognized facet hits, it is scored only for those matched
facets.

If it has no recognized facet hits, the code considers it for all facets:

```python
matched_facet_ids = [fid for fid in facet_hits if fid in facet_lookup] or [
    facet.id for facet in facets
]
```

This fallback prevents a potentially relevant paper from disappearing just
because discovery metadata did not attach it cleanly to a facet.

## 21. Round-Robin Selection Across Facets

After faceted candidates are scored, PaperTracker does not simply take the top
`N` papers globally.

Instead, it:

1. Sorts candidates within each facet by `related_work_score`.
2. Takes candidates round-robin across facets.
3. Avoids duplicates by `canonical_id`.
4. Fills remaining slots with the highest-scoring leftovers if needed.
5. Sorts the final selected list by facet order, then score.

The round-robin logic is in `_round_robin_unique()` in
`src/papertracker/related_work.py`.

This prevents one large or easy facet from crowding out all the others. For a
related-work matrix, diversity across facets is often more useful than a single
global ranking.

## 22. The Difference Between the Three Scores

PaperTracker can store several score fields on a paper.

### `relevance_score`

Used in the basic relevance filter and basic related-work mode.

Meaning:

```text
similarity(title + abstract, project topic statement)
```

### `project_relevance_score`

Used in faceted related-work mode.

Meaning:

```text
similarity(title + abstract, project topic statement)
```

This is conceptually the same as `relevance_score`, but faceted mode stores it
under a more explicit name because it also computes facet-level scores.

### `facet_relevance_score`

Used in faceted related-work mode.

Meaning:

```text
similarity(title + abstract, selected facet topic)
```

### `related_work_score`

Used for ranking related-work candidates.

In basic related-work mode, it combines:

```text
project semantic relevance + citation signal + discovery bonuses
```

In faceted related-work mode, it combines:

```text
facet semantic relevance + project semantic relevance + citation signal
+ discovery/facet bonuses
```

## 23. Why the Weights Look Like This

The weights encode ranking priorities.

In basic related-work mode:

```text
0.70 relevance + 0.24 citations + small bonuses
```

Semantic relevance dominates. Citations matter, but less. Discovery bonuses are
minor nudges.

In faceted related-work mode:

```text
0.42 facet relevance + 0.30 project relevance + 0.18 citations + small bonuses
```

Facet relevance gets the biggest single weight because the paper is being ranked
inside a facet. Project relevance is still important because a paper should fit
the overall project. Citation signal is useful but not allowed to dominate.

The weights do not need to sum to exactly `1` once bonuses are included. The
score is a ranking utility, not a probability.

## 24. Why Use Log Citations Instead of Raw Citations?

Citation counts are heavy-tailed. A few papers have extremely high counts, while
most papers have modest counts.

If raw citations were used, a classic paper with `10,000` citations could
overpower a very relevant recent paper with `15` citations. Log scaling reduces
that problem.

The transformation:

```text
log(1 + citations)
```

preserves the idea that more citations are better, but each additional citation
helps less than the previous one.

This is called diminishing returns.

For example:

```text
0 -> 10 citations
```

is a much bigger signal than:

```text
1000 -> 1010 citations
```

Log scaling reflects that intuition.

## 25. Why Use Embeddings Instead of Keywords?

Keyword filters are brittle.

Suppose the project is about spatial reasoning for embodied agents. A keyword
filter might search for:

```text
spatial reasoning embodied agents
```

But a relevant paper might say:

```text
scene-aware navigation for interactive virtual humans
```

That paper might be relevant even though it does not share the exact keywords.

An embedding model can place both texts near each other because their meanings
are related.

This is the main advantage of embeddings: they compare meaning more than exact
surface form.

## 26. Common Failure Cases

The score is useful, but it is not perfect.

### Vague abstracts

If an abstract is generic, the embedding may not have enough information to
score the paper accurately.

### Missing abstracts

If there is no abstract, the title alone may be too weak. In some source paths,
papers without abstracts may be skipped before summarization.

### Ambiguous terms

Words like "agent," "scene," "interaction," or "spatial" can mean different
things in different fields.

### Adjacent fields

A paper can be semantically close but not actually useful for the project. For
example, it may discuss spatial reasoning in a domain that does not involve
embodied agents or XR.

### Important but differently worded papers

Some foundational papers may use older terminology. Their embeddings may be
close enough, but sometimes they can score lower than expected.

This is why PaperTracker treats scores as ranking/filtering aids, not final
truth.

## 27. How to Tune the System

There are two main knobs.

### Tune the topic statement

The topic statement defines what "relevant" means. A better topic statement
usually produces better scores.

A good topic statement should include:

- the main research area;
- important subtopics;
- included methods or domains;
- boundaries around what should count as relevant.

If the topic is too broad, too many papers pass.

If the topic is too narrow, useful papers may be filtered out.

### Tune the threshold

The threshold controls strictness.

For example:

```text
threshold = 0.75
```

is stricter than:

```text
threshold = 0.60
```

A practical workflow is to run:

```bash
uv run papertracker --no-summarize --threshold -1 --days 14
uv run papertracker --no-summarize --scorer hybrid --threshold -1 --days 14
```

That shows scores without spending LLM quota. Then you can inspect the score
distribution and choose a cutoff.

## 28. Dense Mode vs Hybrid Mode

PaperTracker now treats the original computation as an explicit scorer mode.

```toml
relevance_scorer = "dense"
```

Dense mode is the original behavior:

```text
relevance_score = cosine(
  embedding(project topic statement),
  embedding(paper title + abstract)
)
```

It uses `relevance_threshold`.

Hybrid mode adds a lexical BM25 score:

```toml
relevance_scorer = "hybrid"
```

In hybrid mode, PaperTracker computes:

```text
dense_norm = clamp((dense_cosine + 1) / 2, 0, 1)
bm25_norm = batch-normalized BM25 score
hybrid_score = 0.60 * dense_norm + 0.40 * bm25_norm
```

The dense part captures semantic similarity. The BM25 part rewards exact
technical terms, acronyms, datasets, and method names that may matter even when
embeddings are a little too smooth.

Hybrid mode uses `hybrid_relevance_threshold`.

Hybrid mode can optionally use a local cross-encoder reranker:

```toml
enable_reranker = true
```

When enabled and available, the reranker reads the query and paper text together
for the strongest hybrid candidates. The final score for reranked candidates is:

```text
final_score = 0.35 * hybrid_score + 0.65 * reranker_norm
```

This is still not an LLM call. It is a local relevance model, and if the reranker
dependency or model is unavailable, PaperTracker logs a warning and falls back
to hybrid scoring.

## 29. Using Zotero PDFs for Parsing and Analysis

The relevance scoring described above uses paper metadata: title, abstract,
citations, and discovery source. The deeper paper analysis step can use the full
PDF, but only when that PDF is already stored in your local Zotero library.

The workflow is:

```text
fetched paper metadata
-> match paper to Zotero item
-> resolve local PDF attachment path
-> ask Claude to read that PDF
-> write triage or deep analysis into the digest
```

PaperTracker itself does not extract PDF text into an intermediate file. Instead,
it finds the PDF path and, for the `claude` provider, runs Claude with permission
to read that local file.

### 29.1. Put the Paper in Zotero First

Before asking PaperTracker for full-text analysis, add the paper and its PDF to
Zotero.

The most reliable path is:

1. Add the paper to Zotero with DOI metadata.
2. Attach the PDF to that Zotero item.
3. Run PaperTracker after the Zotero item exists locally.

PaperTracker matches the fetched paper to Zotero in this order:

1. DOI match.
2. Normalized title match.

DOI matching is preferred because titles can vary across sources. A title might
include punctuation differences, subtitles, capitalization differences, or
conference formatting that makes exact title matching harder.

### 29.2. Configure the Zotero Data Directory

By default, PaperTracker looks for Zotero data here:

```toml
zotero_data_dir = "~/Zotero"
```

You can also override it with an environment variable:

```bash
export PAPERTRACKER_ZOTERO_DIR="$HOME/Zotero"
```

The directory must contain:

```text
zotero.sqlite
storage/
```

For normal Zotero stored files, the PDF usually lives under:

```text
~/Zotero/storage/<attachment-key>/<filename>.pdf
```

If you use Zotero linked attachments, configure the linked attachment base:

```toml
zotero_linked_base = "/path/to/linked/pdfs"
```

or:

```bash
export PAPERTRACKER_ZOTERO_LINKED_BASE="/path/to/linked/pdfs"
```

This corresponds to Zotero's "Linked Attachment Base Directory" style of setup.

### 29.3. How PaperTracker Reads Zotero Safely

The Zotero resolver is implemented in `src/papertracker/zotero.py`.

It does not modify your Zotero library. It:

1. Locates `zotero.sqlite`.
2. Copies that database to a temporary directory.
3. Opens the temporary copy in read-only mode.
4. Searches for a Zotero item by DOI, then by normalized title.
5. Looks for PDF attachments for that item.
6. Returns the first attachment path that exists on disk.

This copy-first approach avoids writing to Zotero and avoids interfering with
Zotero's own database locks.

### 29.4. Run a Summary That Uses the PDF

Full-text PDF reading currently works with the `claude` provider.

Use a normal run:

```bash
uv run papertracker --provider claude
```

Or use interactive selection so you can choose which papers to analyze:

```bash
uv run papertracker --provider claude --select
```

In the selector, PaperTracker supports two summary modes:

- `triage`: shorter relevance-oriented bullets.
- `deep`: fills your Obsidian note template.

In the headless text selector, a bare number means triage and a trailing `d`
means deep:

```text
1, 3d
```

That means:

```text
paper 1 -> triage
paper 3 -> deep
```

Both modes try to use the Zotero PDF when the provider is `claude`.

### 29.5. What Claude Receives

When a PDF is found, PaperTracker builds a prompt that begins with:

```text
Read the full paper PDF at this path and base your answer on it:
<local pdf path>
```

Then it runs Claude with:

```text
--allowedTools Read
--add-dir <directory containing the PDF>
```

That gives Claude permission to read the specific local directory containing the
PDF. The analysis is then based on the full paper rather than only the abstract.

This is the "PDF parse and analysis" path in the current implementation:

```text
PaperTracker resolves the PDF path.
Claude reads/parses the PDF content through its Read tool.
Claude writes the requested triage or deep analysis.
PaperTracker stores the result in the digest and summary cache.
```

### 29.6. What Happens If No PDF Is Found

If PaperTracker cannot find a Zotero PDF, it falls back to the title and
abstract.

For Claude summaries, the digest is marked with:

```text
Abstract-based (no Zotero PDF found).
```

This means the analysis did not use the full paper. It used only metadata and
the abstract.

Common reasons a PDF is not found:

- The paper is not in Zotero.
- The Zotero item has no attached PDF.
- The DOI in Zotero differs from the DOI in the fetched source.
- The fetched source has no DOI and the title does not exactly normalize to the
  Zotero title.
- `PAPERTRACKER_ZOTERO_DIR` points to the wrong Zotero data directory.
- Linked attachments are used, but `zotero_linked_base` is not configured.

### 29.7. Provider Limitation

The current full-text PDF path is implemented for:

```text
provider = "claude"
```

With:

```text
provider = "codex"
```

PaperTracker currently falls back to abstract-based prompting because the Codex
subprocess path is run read-only and does not have the same PDF `Read` tool
integration in this codebase.

### 29.8. Quick Verification

To verify that Zotero lookup works for a real run:

1. Pick a paper that appears in PaperTracker output.
2. Make sure the same paper exists in Zotero with an attached PDF.
3. Prefer a Zotero item with a DOI.
4. Run:

```bash
uv run papertracker --provider claude --select -v
```

Select that paper. In verbose logs, PaperTracker should not report:

```text
No Zotero PDF
```

The resulting digest should also not show the abstract-based fallback note for
that paper.

## 30. Summary

In dense mode, the core relevance score is cosine similarity between two
embeddings:

```text
similarity(title + abstract, project topic statement)
```

Because the embedding vectors are normalized, the code computes this with a dot
product:

```python
np.dot(paper_vector, topic_vector)
```

In hybrid mode, that semantic score is combined with BM25 keyword relevance, and
optionally with a local reranker.

The basic relevance filter keeps papers whose active final score is at or above
the configured threshold for the selected mode.

Basic related-work ranking uses:

```text
0.70 * final_relevance_score
+ 0.24 * citation_score
+ discovery bonuses
```

Faceted related-work ranking uses:

```text
0.42 * facet_final_relevance_score
+ 0.30 * project_final_relevance_score
+ 0.18 * citation_score
+ discovery and facet bonuses
```

Citation scores are log-normalized so famous papers get credit without
overwhelming semantic relevance.

The final result is not a probability or an absolute quality measure. It is a
practical ranking score designed to answer:

> Which papers are semantically close to my project, credible enough to surface,
> and useful across the related-work structure I am building?
