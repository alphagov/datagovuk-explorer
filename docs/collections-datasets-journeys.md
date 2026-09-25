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

A distance threshold of **0.75** means 72 of 83 collections show related datasets. The 11 that don't are mostly niche topics where the directory genuinely has nothing close.

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
