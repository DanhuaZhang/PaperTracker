# Paper Source APIs

This note summarizes the external paper-search sources used by PaperTracker,
where they are wired into the project, how to access each source, current usage
limits, and licensing or reuse concerns.

Last checked: 2026-07-13.

## Summary Table

| Source | Used for | Where to get / access it | Limits and current project cap | License / reuse notes | Project use |
|---|---|---|---|---|---|
| arXiv API | Daily preprint discovery by subject category and submitted date. | API docs: <https://info.arxiv.org/help/api/user-manual.html>. Endpoint used by code: `https://export.arxiv.org/api/query`. **No account, sign-in, or API key required** — the public query API is anonymous; PaperTracker sends only a descriptive `User-Agent`. | arXiv asks clients to make no more than one request every 3 seconds, using a single connection. The query API supports up to 30,000 results total, in slices of at most 2,000. PaperTracker uses pages of 100 and caps each source at `max_results_per_query` (`1500` by default). | arXiv metadata is CC0. Full e-print/PDF reuse is separate: most papers are not CC licensed, and redistribution generally depends on the paper's selected license or permission from the copyright holder. | [src/papertracker/sources/arxiv_client.py](../src/papertracker/sources/arxiv_client.py), wired through [src/papertracker/cli.py](../src/papertracker/cli.py). |
| Crossref Works API | Daily ACM and IEEE publication metadata discovery by Crossref member ID and publication date window. | REST API docs: <https://www.crossref.org/documentation/retrieve-metadata/rest-api/>. Endpoint used by code: `https://api.crossref.org/works`. | No signup is required. Crossref's docs emphasize responsible use, filtering, caching, and backoff. The `rows` maximum is 1,000 per request; `offset` for `/works` is limited to 10,000 and cursor paging is recommended for deeper results. PaperTracker uses pages of 100, waits 0.5 seconds between pages, and caps each source at `max_results_per_query` (`1500` by default). | Crossref states that almost all metadata is not copyright-restricted and can be used for any purpose, but some abstracts in deposited metadata may be copyrighted by publishers or authors. Crossref metadata quality and license metadata depend on publisher deposits. | [src/papertracker/sources/crossref_client.py](../src/papertracker/sources/crossref_client.py). ACM uses member `320` in [acm_client.py](../src/papertracker/sources/acm_client.py); IEEE uses member `263` in [ieee_client.py](../src/papertracker/sources/ieee_client.py). |
| OpenAlex Works API | Abstract fallback for DOI records, related-work discovery, citation-count search, and OpenAlex semantic search. | API overview: <https://developers.openalex.org/api-reference/introduction>. Free API key: <https://openalex.org/settings/api>. Endpoint used by code: `https://api.openalex.org/works`. | OpenAlex currently uses freemium API limits. With a free key, the daily free budget is `$1/day`; no-key usage is much smaller. In the official examples, `$1/day` covers about 10,000 list/filter calls, 1,000 search calls, or 100 content-download calls. OpenAlex also returns rate-limit headers and 429s if limits are exceeded. Normal list endpoints allow `per_page` up to 100. Semantic search has separate constraints: max input 2,000 characters, max 50 results per query, and 1 request/second. PaperTracker uses singleton DOI lookups for abstract fallback, list/search calls for related work, and semantic search capped by CLI/profile settings. | OpenAlex's complete dataset is CC0. Metadata and citation fields are therefore safe for reuse under CC0. Full-text PDF/content downloads, if used outside this project, can still carry the original publisher or open-access license constraints. | [src/papertracker/sources/openalex_client.py](../src/papertracker/sources/openalex_client.py). Related-work calls are in [src/papertracker/cli.py](../src/papertracker/cli.py). |
| Journal RSS feeds | Early journal table-of-contents discovery for configured priority venues, currently IEEE TVCG, ACM TOG, and ACM TOCHI. | Feed URLs are configured as `priority_venues` in [user_data/projects.toml](../user_data/projects.toml): IEEE TVCG `https://ieeexplore.ieee.org/rss/TOC2945.XML`, ACM TOG `https://dl.acm.org/action/showFeed?type=etoc&feed=rss&jc=tog`, ACM TOCHI `https://dl.acm.org/action/showFeed?type=etoc&feed=rss&jc=tochi`. | The code fetches each configured feed once per run. The provider-side RSS limits for those publisher feeds are not stated in this repo; treat them as publisher feeds and avoid high-frequency polling. PaperTracker filters entries to the requested date window and uses OpenAlex as an abstract fallback when an RSS item has a DOI but no abstract. | RSS item metadata is publisher-provided. Titles, links, and short feed summaries are used for discovery; full paper content remains subject to the publisher/open-access license for the linked article. | [src/papertracker/sources/journal_rss.py](../src/papertracker/sources/journal_rss.py), wired through [src/papertracker/cli.py](../src/papertracker/cli.py). |
| Zotero local SQLite database | Local collection lookup and local PDF path resolution for full-text summarization. This is a local source, not a web search API. | Zotero data directory docs: <https://www.zotero.org/support/zotero_data>. Direct SQLite access docs: <https://www.zotero.org/support/dev/client_coding/direct_sqlite_database_access>. | No web quota. The practical limit is the size of the user's local Zotero library. Zotero recommends direct SQLite access only in read-only mode. PaperTracker copies `zotero.sqlite` to a temp directory, opens that copy read-only, and looks up collections, items, DOI/title metadata, and PDF attachment paths. | Zotero metadata and local PDFs inherit whatever rights apply to the user's library items and attached files. PaperTracker does not grant redistribution rights for local PDFs; it only resolves local file paths for analysis. | [src/papertracker/zotero.py](../src/papertracker/zotero.py), wired through `--list-zotero-collections` and `--zotero-collection` in [src/papertracker/cli.py](../src/papertracker/cli.py). |

## DOI-Based Backup and Enrichment Sources

PaperTracker uses these public APIs through
[doi_providers.py](../src/papertracker/sources/doi_providers.py) and the cached,
failure-isolated orchestration in
[doi_enrichment.py](../src/papertracker/sources/doi_enrichment.py). Abstract
providers are queried in order only when discovery metadata lacks an abstract.
Supplemental enrichers run only for relevant, unseen DOI papers.

| API | Best backup use | DOI access and limits | Reuse and coverage notes | Project use |
|---|---|---|---|---|
| Semantic Scholar Academic Graph API | Broad scholarly metadata, abstracts, citation counts, references, recommendations, and open-access PDF links. | Fetch a paper with `GET https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}` and request only needed fields. Most endpoints allow unauthenticated access, but anonymous traffic shares a throttled pool. A free API key is recommended; the introductory authenticated limit is 1 request/second. | Semantic Scholar maintains its own S2AG corpus from publisher partnerships, public data providers, and web indexing. It is not documented as an OpenAlex-backed API, although both services ingest overlapping upstream sources. API data and third-party content remain subject to the Semantic Scholar API agreement and their accompanying licenses. | Implemented as the second default abstract fallback, after OpenAlex. `PAPERTRACKER_SEMANTIC_SCHOLAR_API_KEY` is optional. |
| OpenAIRE Graph API | Aggregated publication metadata, repository descriptions, open-access locations, projects, and other research-product relationships. | Search by DOI with `GET https://api.openaire.eu/graph/v3/research-products?pid={doi}`. Public API rate restrictions apply; offset paging is limited to the first 10,000 results, while the current API also supports cursor paging. | OpenAIRE aggregates Crossref, DataCite, Unpaywall, repositories, and other sources, so it improves repository coverage but is not fully independent of the existing providers. Preserve provenance and check the license of linked full text separately. | Implemented as the third default abstract fallback. |
| CORE API | Harmonized repository metadata and, when available, machine-accessible open-access full text. | Search CORE records by DOI or use DOI as an exact identifier when present. CORE documents one batch request or five individual requests per 10 seconds for standard access; free access is available subject to its terms. | Coverage depends on repository deposits and DOI quality. API access to a document does not override the license attached to its full text. | Implemented as the fourth default abstract fallback. `PAPERTRACKER_CORE_API_KEY` is optional. |
| Europe PMC REST API | High-quality abstracts, references, identifiers, and open-access full text for biomedical and health literature. | Search using a DOI query and request the `core` result type for full metadata, including abstracts and full-text links. Europe PMC asks automated clients to follow its published usage guidance rather than advertising a general-purpose bulk search guarantee. | Strong but domain-specific coverage. Abstract and full-text reuse depends on the rights and license recorded for each publication. | Implemented after CORE in the default abstract fallback chain. |
| Unpaywall API | Open-access status plus legitimate repository or publisher landing-page and PDF locations for a DOI. | `GET https://api.unpaywall.org/v2/{doi}?email={email}`. An identifying email is required. Clients should cache responses and follow Unpaywall's documented rate guidance. | This is primarily an access-location service, not an abstract source. Unpaywall's metadata and OA-location data do not change the copyright or reuse license of a linked article. | Implemented as a default post-filter enricher; OA links appear in daily digests. Set `PAPERTRACKER_EMAIL` for valid requests. |
| DataCite REST API | Authoritative metadata for DataCite-registered datasets, software, reports, preprints, and repository publications. | `GET https://api.datacite.org/dois/{doi}`. Public metadata retrieval requires no authentication; frequent clients should send an identifying `User-Agent` with contact information. | DataCite metadata is openly available under CC0. It normally will not contain ACM or IEEE journal/conference DOIs registered through Crossref. | Implemented as the final abstract fallback and as a default supplemental metadata enricher for non-Crossref records. |
| OpenCitations API | DOI-to-DOI references, incoming citations, outgoing references, and citation counts. | Index V2 exposes separate DOI endpoints for citation count, incoming citations, and references. Calls are limited to 180 requests/minute per IP; an access token is encouraged for application use. | Useful for open citation edges, not abstracts. Citation coverage can be incomplete and counts will differ from OpenAlex, Semantic Scholar, and Google Scholar. OpenCitations data is openly licensed; retain source attribution where required by the specific dataset or API documentation. | Implemented as a default post-filter enricher. Citation counts and provider provenance appear in daily digests. |
| DBLP SPARQL API | Computer-science title, author, venue, year, and DOI validation. | Query `https://sparql.dblp.org/sparql` using the RDF schema's `dblp:doi` property and request SPARQL JSON results. DBLP asks clients not to overwhelm its live APIs. | Excellent CS venue coverage but no abstract service. DOI presence and completeness vary by record; DBLP metadata is CC0. | Implemented as a default post-filter enricher that fills missing bibliographic fields and records the DBLP key. |

For abstract recovery, the discovery source (Crossref, RSS, or arXiv) supplies the
abstract first; when it is missing, PaperTracker falls back in this **implemented
default order**: OpenAlex, Semantic Scholar, OpenAIRE, CORE, Europe PMC (most
useful when the paper is biomedical), then DataCite. The order and membership are
configurable via `PAPERTRACKER_ABSTRACT_FALLBACKS`, and the first provider that
returns an abstract wins.

Separately, for relevant unseen DOI papers, supplemental enrichers run in the
default order Unpaywall, OpenCitations, DBLP, DataCite (configurable via
`PAPERTRACKER_DOI_ENRICHERS`): Unpaywall adds open-access locations, while
OpenCitations and DBLP add citations and bibliographic metadata rather than
abstracts. Both chains are cached per `(provider, DOI)` for the run, and one
provider's failure never stops later providers.

## Not Used

| API | Status |
|---|---|
| IEEE Xplore API | Not used directly. IEEE papers are discovered through Crossref member `263` and configured IEEE RSS feeds. |
| ACM Digital Library API | Not used directly. ACM papers are discovered through Crossref member `320` and configured ACM RSS feeds. |

## Source Links

- arXiv API manual: <https://info.arxiv.org/help/api/user-manual.html>
- arXiv API terms of use: <https://info.arxiv.org/help/api/tou.html>
- arXiv license information: <https://info.arxiv.org/help/license/index.html>
- Crossref REST API overview: <https://www.crossref.org/documentation/retrieve-metadata/rest-api/>
- Crossref REST API tips: <https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/>
- Crossref REST API result controls: <https://github.com/CrossRef/rest-api-doc#result-controls>
- OpenAlex API overview: <https://developers.openalex.org/api-reference/introduction>
- OpenAlex authentication and pricing: <https://developers.openalex.org/api-reference/authentication>
- OpenAlex semantic search: <https://developers.openalex.org/guides/semantic-search>
- OpenAlex data downloads and CC0 snapshot notes: <https://developers.openalex.org/download/overview>
- Semantic Scholar API overview and access limits: <https://www.semanticscholar.org/product/api>
- Semantic Scholar API documentation: <https://api.semanticscholar.org/api-docs/graph>
- Semantic Scholar API license agreement: <https://www.semanticscholar.org/product/api/license>
- Semantic Scholar content sources: <https://www.semanticscholar.org/faq>
- OpenAIRE Graph API: <https://graph.openaire.eu/docs/apis/graph-api/>
- OpenAIRE research-product filters: <https://graph.openaire.eu/docs/apis/graph-api/research-products/filtering/>
- CORE API: <https://core.ac.uk/services/api>
- Europe PMC REST API: <https://dev.europepmc.org/RestfulWebService>
- Unpaywall REST API: <https://data.unpaywall.org/products/api>
- DataCite REST API guide: <https://support.datacite.org/docs/api>
- DataCite single-DOI retrieval: <https://support.datacite.org/docs/api-get-doi>
- OpenCitations APIs: <https://opencitations.net/querying/>
- OpenCitations Index V2 API: <https://api.opencitations.net/index/v2>
- DBLP SPARQL API: <https://sparql.dblp.org/>
- DBLP RDF schema: <https://dblp.org/rdf/docu/>
- Zotero data directory: <https://www.zotero.org/support/zotero_data>
- Zotero direct SQLite access: <https://www.zotero.org/support/dev/client_coding/direct_sqlite_database_access>
