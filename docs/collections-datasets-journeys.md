# Collections and datasets: how they could work together

## What they are today

Collections and datasets are separate areas of data.gov.uk with no real connection.

**Collections** are hand-written editorial pages for a mainstream audience. Each one covers a topic (water quality, food hygiene ratings, deprivation) with an explanatory description and curated links to services, APIs and external datasets. There are 83 of them across 7 categories. The quality is controlled — they're written by the team.

**Datasets** are the open directory. Any publisher can add whatever data they want, with their own titles, descriptions and metadata. There are ~58,000 of them. Quality varies wildly. 63% have no theme assigned.

Collections are not collections of datasets. They're standalone content that exists independently. Sometimes the directory happens to contain datasets on the same topic, but often it doesn't — many collections point to services and data sources that aren't represented in the directory at all.

## Bridging the two

### Related datasets on collection pages

The most natural connection: at the bottom of a collection page, show directory datasets that are topically related. This serves two purposes:

- **For users** — "you came here to read about water quality, and here's some raw data you could explore on that topic"
- **For the editorial team** — see what already exists in the directory when writing or maintaining a collection

Where no good matches exist, the section is simply hidden. This is fine — the collections are the primary content, the related datasets are a bonus.

### What we found in the data

We tested semantic similarity (embeddings) and full-text search for matching collections to datasets.

**Full-text search** works well for some topics but fails for others. "Water quality" and "food hygiene" return clearly relevant datasets. "Bank of england interest rate" returns nothing at all. The results are binary — good or absent — with little middle ground.

**Semantic search** (using the existing bge-base-en-v1.5 embeddings) gives a richer picture. Every collection has a nearest dataset, but the distances fall into clear bands:

| Distance | Quality | Examples |
|---|---|---|
| < 0.5 | Strong match | Water quality (0.23), food hygiene (0.39), coastal erosion (0.39), LIDAR (0.47) |
| 0.5–0.7 | Decent match | Election results (0.64), road traffic (0.65), deprivation (0.68) |
| 0.7–0.75 | Borderline | Air quality (0.71), planning data (0.71), addresses (0.75) |
| > 0.75 | Weak/irrelevant | Train info (0.77), bank of england (0.81), service assessments (0.82) |

A distance threshold of **0.75** is applied, and datasets with no resource links are excluded

72 of 83 collections show related datasets. The distribution:

| Related datasets | Collections |
|---|---|
| 0 | 11 (13%) |
| 1–3 | 23 (28%) |
| 4–7 | 19 (23%) |
| 8–9 | 5 (6%) |
| 10 (cap) | 25 (30%) |

By category:

| Category | Collections | Zero matches | Avg related |
|---|---|---|---|
| environment | 18 | 0 | 6.9 |
| land-and-property | 11 | 0 | 6.5 |
| people | 17 | 1 | 5.9 |
| government-and-parliament | 8 | 3 | 4.5 |
| transport | 12 | 3 | 4.1 |
| early-years | 7 | 2 | 3.7 |
| business-and-economy | 10 | 2 | 2.5 |

### What we built

Pre-computed collection embeddings (title + first 500 chars of description, same model as the dataset embeddings), stored in a `collection_embeddings` table. At request time, the collection's vector is used as a KNN probe against the existing 58k dataset embedding index. The threshold filters out weak matches, and the section is hidden entirely when nothing passes.

The embedding generation runs as part of the collection ingest pipeline. It's optional — if llama-server isn't running, ingest still works, you just don't get related datasets until next time.

## Dataset → collection (the reverse direction)

Linking from a dataset page back to a collection is worth doing, but at the **category level** rather than specific collection pages.

The risk with linking to a specific collection: if someone is looking at a raw water quality dataset and you link them to the "Water quality" collection page, it might feel redundant — they already know what the topic is. But linking to the "Environment" category of collections says "there's a whole curated area covering this kind of topic" — a genuinely different thing that introduces them to the collections world.

Category-level linking would also be simpler to implement — a mapping between dataset themes and collection categories rather than per-dataset semantic matching. The mapping isn't clean (the taxonomies don't align, and most datasets have no theme), but it would cover a useful chunk.

This hasn't been built yet.

## Coverage and gaps

The matching reveals where the editorial layer and the directory overlap — and where they don't:

- **Strong overlap**: environment topics (water quality, LIDAR, coastal erosion, flood data), food hygiene, energy performance, school inspections
- **Partial overlap**: transport, land and property, crime — datasets exist but are more scattered
- **Little overlap**: financial/economic topics (interest rates, inflation, commodity prices), parliamentary data, service assessments

The gaps are informative either way. A collection with no related datasets means the directory doesn't cover that topic — which might be fine (collections are meant to go beyond the directory) or might highlight something worth adding. A dataset with no related collection means nobody has written a curated page for that area yet.

## Unifying across publishers

The directory is organised by publisher — Environment Agency, SEPA, Natural Resources Wales, OpenDataNI each own their slice. A user looking at the EA's flood risk dataset has no way to discover that Scotland, Wales and Northern Ireland publish equivalent data under different organisations.

Collections can cut across this. The **long-term flood risk** collection page presents five services for the same task (check your flood risk) across four nations as one coherent set:

- Flood risk in England (GOV.UK / Environment Agency)
- Flood risk for planning in England (GOV.UK)
- Flood risk in Scotland (SEPA)
- Flood risk in Wales (Natural Resources Wales)
- Flood risk in Northern Ireland (nidirect)

No dataset page can do this because each record belongs to a single publisher. The collection reassembles the data by what the user is trying to do — check flood risk — regardless of which government body happens to hold the data for their postcode.

The same pattern appears in other collections: **landfill sites** brings together EA, NRW and Scottish Government datasets; **LIDAR mapping** spans Environment Agency, Natural Resources Wales, BGS and others. This cross-publisher view is one of the strongest unique capabilities of the editorial layer — something the directory structure actively works against.

## Side-by-side comparison: what each page does

Comparing the same subject across both pages reveals what each layer is for.

### LIDAR mapping

The **collection** has two clean paragraphs explaining what LIDAR is, what the data covers (99% of England at 1m resolution), and what you can do with it. One curated link to the primary resource. 10 hand-picked related datasets — all clearly relevant (NRW LIDAR, BGS LiDAR DEM, etc.).

The **dataset** (National LIDAR Programme) has the publisher's own text with typos ("curretly", "origianl", "upto", "quartely") and dense technical detail about survey phases. 9 links in a sortable table with format/MIME/size columns, many showing "?" for format. License: "None given".

### Landfill sites

The **collection** groups two things that belong together: the current authorised landfill boundaries dataset and the historic landfill sites dataset. It explains what happens when a site stops accepting waste (removed from one, added to the other). 8 related datasets, all directly on-topic across England, Wales, and Scotland.

The **dataset** (Permitted Waste Sites - Authorised Landfill Site Boundaries) has the full regulatory name, compliance-oriented description with descriptor codes (A1, A2, A4, A5, A6, A7, 5.2 A(1) a), L04, L05), and licence status definitions. License "None given" in the structured field, but the actual licence is buried in the extras as freetext. Tags include internal jargon (EAPotential, planningCadastre). Temporal coverage: 1974 to 2099.

### Fire statistics

The **collection** assembles what is really a family of 10 datasets into a table of contents: incident level data, cause of fire, fatalities and casualties, response times, smoke alarms, prevention, non-fire incidents, etc. One curated link to the GOV.UK landing page for all fire statistics data tables.

The **dataset** (Fire statistics: Incident level datasets) is just one member of that family. 7 links — a landing page, 3 guidance PDFs, 3 ODS files, all dated 2017.

### The pattern

The collection is what you'd show a policymaker or journalist. The dataset page is what you'd show a data manager auditing the catalogue. The collection curates; the dataset page exposes. Neither can replace the other — but there are UX problems when users move between them.

In some cases the dataset page is so thin that the collection isn't just curating — it's the only useful entry point. The Ofsted school inspections datasets are catalogue stubs: a one-sentence description, a single link to a GOV.UK landing page, no data files, last modified in 2019. Without the collection page a user would land on a record with almost nothing to offer.

### Collections as a correction for stale directory records

The directory is a free-for-all — publishers can abandon records and nobody forces an update. The **museum and gallery visits** dataset was last meaningfully updated in 2014. Its 9 links are monthly results from March 2013 to July 2014, all pointing to the same GOV.UK page but labelled as individual monthly releases from over a decade ago. The description still uses the pre-2017 department name.

The data itself is still being published. The collection page proves it — it links to the 2024/25 annual performance indicators and the live monthly visits page. The collection is routing around a rotting directory entry.

This inverts the usual staleness concern. The risk isn't that collections go stale while the directory stays current — it's that the directory is already stale and the collection layer is the only thing keeping the front door accurate for these topics.

## The duplication problem

When a user reads the fire statistics collection, clicks through to "Incident level datasets", and arrives on the dataset page, they see a related datasets section showing the same family — but noisier and mixed with irrelevant results. This undermines the collection in two ways:

1. The user sees the same content repeated and wonders which list to trust
2. The algorithmic list makes the curated list look less authoritative by association

### Solution: record the relationship, suppress the duplicate

If a dataset belongs to a collection, exclude it from the algorithmic related datasets shown on other dataset pages within the same collection. The curated relationship takes priority over the algorithmic one.

This requires modelling the collection → dataset relationship explicitly. Right now the collections are static content with hand-picked links baked in. Recording the relationship properly (collection has many datasets) enables:

- **Filtering**: suppress duplicates in algorithmic related lists
- **Back-linking**: show "Part of the **Fire statistics** collection" on a dataset page
- **Staleness detection**: surface when a related dataset has been withdrawn or a new one appears that should be added
- **The merged topics idea** (below): knowing which datasets belong to a collection makes this easier

The relationship isn't recorded for the purpose of hiding — it's recorded because it's real, and one consequence is you can stop showing things twice.

## Naming: "collections" is misleading

"Collections" implies collections of dataset pages from the directory, but that's not what they are. They're editorial content that links out to datasets (and often to services and APIs that aren't in the directory at all).

Alternatives considered:

| Name | Pros | Cons |
|---|---|---|
| **Topics** | Plain, natural, familiar GOV.UK pattern | Collides with the topic facet on the datasets index |
| **Spotlights** | Distinctive, signals editorial curation | Less conventional |
| **Guides** | Emphasises the written-for-humans angle | Overpromises if pages stay short |
| **Briefings** | Clear that someone wrote this for you | Slightly formal |
| **Overviews** | Plain, accurate | Generic |
| **Features** | Journalistic tone, clearly editorial | Ambiguous with software features |

"Topics" is the most natural word but collides with browsing datasets by topic. "Spotlights" is the most distinctive option that works at both levels — "Environment spotlights" for the category listing, "the LIDAR mapping spotlight" for an individual page.

### A possible merge: topics as the front door

Instead of two separate concepts (curated pages and a topic facet), merge them. A topic page opens with the editorial content (description, curated links, hand-picked datasets) and below that shows the full browseable list of all datasets tagged with that topic.

`/topics/environment/lidar` would be:

1. The written-for-humans intro to LIDAR mapping
2. The curated links and hand-picked datasets
3. "All LIDAR datasets" — the full filtered list from the directory

A mainstream user reads the intro and clicks a curated link. A power user scrolls past to the full unfiltered listing. The editorial content becomes the front door to the data rather than a parallel path.

The risk: this only works if the collection themes align with whatever topic classification exists on the datasets. If they don't, the merge gets messy.
