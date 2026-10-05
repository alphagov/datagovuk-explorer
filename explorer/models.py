"""Django models — the tables the migrations own.

Schema notes:
- Timestamps are TEXT in the DB (format_date exists for a reason) — TextField,
  not DateTimeField. The one exception is LinkCheckResult.checked_at
  (DateTimeField, converted in migration history).
- links.id / series.id are SERIAL -> AutoField.
- embedding_map.rowid / dataset_embeddings.rowid are plain INTEGER PRIMARY KEY
  (embed_batch assigns dense rowids from 1) -> IntegerField(primary_key=True),
  not AutoField.
- datasets.id is SERIAL (AutoField) — the CKAN UUID lives in ckan_id.
- datasets.fts is a SearchVectorField (tsvector), populated by build_db.py.
- dataset_embeddings.embedding and collection_embeddings.embedding are
  VectorField(dimensions=768) from pgvector.django.
- All indexes are declared in Meta.indexes — FK fields use db_index=False so
  Django doesn't emit its own.
- metadata_values and series_datasets use Django 6 composite primary keys
  (pk = CompositePrimaryKey(...)) — no implicit id column.

The query layer is raw SQL via django.db.connection; these models exist to
own the schema via migrations.
"""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models.functions import Coalesce, Lower
from pgvector.django import HnswIndex, VectorField


class Organisation(models.Model):
    slug = models.TextField(primary_key=True)
    name = models.TextField(blank=True, null=True)
    display_name = models.TextField(blank=True, null=True)
    package_count = models.IntegerField(blank=True, null=True)
    type = models.TextField(blank=True, null=True)
    state = models.TextField(blank=True, null=True)
    approval_status = models.TextField(blank=True, null=True)
    created = models.TextField(blank=True, null=True)
    title = models.TextField(blank=True, null=True)
    json = models.TextField(blank=True, null=True)

    class Meta:
        app_label = "explorer"
        db_table = "organisations"

    def __str__(self):
        return self.slug


class HarvestSource(models.Model):
    id = models.TextField(primary_key=True)
    title = models.TextField(blank=True, null=True)
    url = models.TextField(blank=True, null=True)
    type = models.TextField(blank=True, null=True)
    active = models.BooleanField(blank=True, null=True)
    frequency = models.TextField(blank=True, null=True)
    organization_id = models.TextField(blank=True, null=True)
    org_slug = models.TextField(blank=True, null=True)
    created = models.TextField(blank=True, null=True)
    json = models.TextField(blank=True, null=True)
    dataset_count = models.IntegerField(blank=True, null=True)
    last_run = models.TextField(blank=True, null=True)

    class Meta:
        app_label = "explorer"
        db_table = "harvest_sources"

    def __str__(self):
        return self.title or self.id


class Dataset(models.Model):
    id = models.AutoField(primary_key=True)
    ckan_id = models.TextField(unique=True)
    org_slug = models.TextField()
    org_display_name = models.TextField(blank=True, null=True)
    title = models.TextField(blank=True, null=True)
    name = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    metadata_created = models.TextField(blank=True, null=True)
    metadata_modified = models.TextField(blank=True, null=True)
    resource_count = models.IntegerField(blank=True, null=True)
    theme_primary = models.TextField(blank=True, null=True)
    harvested = models.IntegerField(db_default=0)
    harvest_source_title = models.TextField(blank=True, null=True)
    # The CKAN harvest source id (the datasets→sources join key, from the
    # dataset's harvest_source_id extra). Not a FK: harvest_sources is keyed
    # by id but the build truncates both tables independently.
    harvest_source_id = models.TextField(blank=True, null=True)
    views = models.IntegerField(db_default=0)
    tags = models.TextField(blank=True, null=True)
    fts = SearchVectorField(null=True)

    class Meta:
        app_label = "explorer"
        db_table = "datasets"
        indexes = [
            models.Index(fields=["org_slug"], name="idx_datasets_org"),
            models.Index(fields=["org_slug", "resource_count"], name="idx_datasets_org_resource"),
            models.Index(fields=["theme_primary"], name="idx_datasets_theme"),
            models.Index(fields=["metadata_created"], name="idx_datasets_created"),
            models.Index(fields=["metadata_modified"], name="idx_datasets_modified"),
            models.Index(fields=["-views"], name="idx_datasets_views_desc"),
            models.Index(
                fields=["ckan_id"],
                include=["org_slug", "org_display_name", "title", "theme_primary"],
                name="idx_datasets_ckan_id_cover",
            ),
            GinIndex(fields=["fts"], name="idx_datasets_fts"),
        ]

    def __str__(self):
        return self.title or self.name or self.ckan_id


class TemporalPeriod(models.Model):
    """One normalised coverage period for a dataset: [from_year, to_year]
    (either year NULL for open-ended coverage). Rows are written by the
    build from the publisher's temporal_coverage-from/to (source='declared')
    or, when the publisher declared none, inferred from the dataset title
    (source='title') or a resource name (source='resource'). The facet
    layer queries this table directly — no jsonb anywhere."""

    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        db_column="dataset_id",
        db_index=False,
    )
    position = models.IntegerField()
    from_year = models.IntegerField(blank=True, null=True)
    to_year = models.IntegerField(blank=True, null=True)
    source = models.TextField()
    pk = models.CompositePrimaryKey("dataset", "position")

    class Meta:
        app_label = "explorer"
        db_table = "temporal_periods"

    def __str__(self):
        return f"{self.dataset_id} [{self.from_year}, {self.to_year}] ({self.source})"


class DatasetApi(models.Model):
    """One row per dataset that has an API, populated at build time.

    api_category is 'map-layers' or 'data-apis'. The table is wiped and
    rebuilt on every build; the report and datasets-page facet query it
    instead of running the full 22-condition EXISTS chain at request time."""

    dataset = models.OneToOneField(
        Dataset,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="dataset_id",
        db_index=False,
    )
    api_category = models.TextField()

    class Meta:
        app_label = "explorer"
        db_table = "dataset_api"
        indexes = [
            models.Index(fields=["api_category"], name="dataset_api_category_idx"),
        ]

    def __str__(self):
        return f"{self.dataset_id} ({self.api_category})"


class DatasetContentHash(models.Model):
    """One row per dataset: an md5 hash of its normalised title, notes and
    resource URL set, for exact-duplicate detection. content_hash is indexed
    (not unique — GROUP BY content_hash HAVING COUNT(*) > 1 finds duplicates)
    so other queries can join/filter on it cheaply."""

    dataset = models.OneToOneField(
        Dataset,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="dataset_id",
        db_index=False,
    )
    content_hash = models.TextField()

    class Meta:
        app_label = "explorer"
        db_table = "dataset_content_hash"
        indexes = [
            models.Index(fields=["content_hash"], name="dataset_content_hash_idx"),
        ]

    def __str__(self):
        return f"{self.dataset_id} ({self.content_hash})"


class DatasetYear(models.Model):
    """One row per (dataset, year) in its temporal coverage window, expanded
    from temporal_periods at build time. Avoids generate_series at request
    time; the year column is indexed so GROUP BY year is a fast index scan.

    Only years in [1900, 2100] are stored; the query layer applies
    TEMPORAL_MAX_YEAR at runtime so the facet window stays current without
    a rebuild."""

    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        db_column="dataset_id",
        db_index=False,
    )
    year = models.IntegerField()

    class Meta:
        app_label = "explorer"
        db_table = "dataset_years"
        constraints = [
            models.UniqueConstraint(fields=["dataset", "year"], name="dataset_years_dataset_year_uniq"),
        ]
        indexes = [
            models.Index(fields=["year"], name="dataset_years_year_idx"),
        ]

    def __str__(self):
        return f"{self.dataset_id} ({self.year})"


class DatasetJson(models.Model):
    dataset = models.OneToOneField(
        Dataset,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="dataset_id",
        db_index=False,
    )
    json = models.JSONField()

    class Meta:
        app_label = "explorer"
        db_table = "dataset_json"

    def __str__(self):
        return str(self.dataset)


class Link(models.Model):
    id = models.AutoField(primary_key=True)
    resource_id = models.TextField(blank=True, null=True)
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        db_column="dataset_id",
        db_index=False,
    )
    org_slug = models.TextField()
    org_display_name = models.TextField(blank=True, null=True)
    dataset_title = models.TextField(blank=True, null=True)
    name = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    url = models.TextField(blank=True, null=True)
    host = models.TextField(blank=True, null=True)
    format = models.TextField(blank=True, null=True)
    format_norm = models.TextField(blank=True, null=True)
    year_created = models.TextField(blank=True, null=True)
    created = models.TextField(blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)

    class Meta:
        app_label = "explorer"
        db_table = "links"
        indexes = [
            models.Index(fields=["host"], name="idx_links_host"),
            models.Index(fields=["format_norm"], name="idx_links_format"),
            models.Index(fields=["year_created"], name="idx_links_year"),
            models.Index(fields=["dataset"], name="idx_links_dataset"),
            models.Index(fields=["org_slug"], name="idx_links_org"),
            models.Index(
                fields=["url", "dataset", "org_slug"],
                name="idx_links_url_dataset_org",
                condition=models.Q(url__isnull=False) & ~models.Q(url=""),
            ),
            models.Index(
                Lower(Coalesce("host", models.Value(""))),
                name="idx_links_host_lower",
            ),
        ]

    def __str__(self):
        return self.name or self.dataset_title or self.resource_id


class MetadataKey(models.Model):
    key = models.TextField(primary_key=True)
    section = models.TextField()
    count = models.IntegerField()
    non_empty = models.IntegerField()
    distinct_values = models.IntegerField()

    class Meta:
        app_label = "explorer"
        db_table = "metadata_keys"

    def __str__(self):
        return self.key


class MetadataValue(models.Model):
    metadata_key = models.ForeignKey(
        MetadataKey,
        on_delete=models.CASCADE,
        db_column="key",
        db_index=False,
    )
    value = models.TextField()
    count = models.IntegerField()
    pk = models.CompositePrimaryKey("metadata_key", "value")

    class Meta:
        app_label = "explorer"
        db_table = "metadata_values"

    def __str__(self):
        return self.value


class EmbeddingMap(models.Model):
    """Maps a dataset id to its dense rowid in dataset_embeddings."""

    rowid = models.IntegerField(primary_key=True)
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        db_column="dataset_id",
        db_index=False,
    )

    class Meta:
        app_label = "explorer"
        db_table = "embedding_map"
        indexes = [
            models.Index(fields=["dataset"], name="idx_embedding_map_dataset"),
        ]

    def __str__(self):
        return str(self.dataset)


class DatasetEmbedding(models.Model):
    rowid = models.IntegerField(primary_key=True)
    embedding = VectorField(dimensions=768, null=True)

    class Meta:
        app_label = "explorer"
        db_table = "dataset_embeddings"
        indexes = [
            HnswIndex(
                fields=["embedding"],
                name="idx_dataset_embeddings_hnsw",
                opclasses=["vector_l2_ops"],
            ),
        ]

    def __str__(self):
        return str(self.rowid)


class Series(models.Model):
    id = models.AutoField(primary_key=True)
    root_title = models.TextField()
    type = models.TextField()
    dataset_count = models.IntegerField(db_default=0)
    org_count = models.IntegerField(db_default=0)

    class Meta:
        app_label = "explorer"
        db_table = "series"
        # Django Meta option, mutable by design — RUF012's class-attribute
        # default guard doesn't apply to Meta.
        constraints = [
            models.CheckConstraint(
                condition=models.Q(type__in=("template", "timeseries")),
                name="series_type_check",
            ),
        ]

    def __str__(self):
        return self.root_title


class SeriesDataset(models.Model):
    series = models.ForeignKey(
        Series,
        on_delete=models.CASCADE,
        db_column="series_id",
        db_index=False,
    )
    dataset_id = models.IntegerField()
    dataset_title = models.TextField()
    date_suffix = models.TextField(blank=True, null=True)
    org_slug = models.TextField()
    org_display_name = models.TextField()
    pk = models.CompositePrimaryKey("series", "dataset_id")

    class Meta:
        app_label = "explorer"
        db_table = "series_datasets"
        indexes = [
            models.Index(fields=["series"], name="idx_series_datasets_series"),
            models.Index(fields=["dataset_id"], name="idx_series_datasets_dataset"),
        ]

    def __str__(self):
        return self.dataset_title


class Review(models.Model):
    """One row per dataset — exactly one LLM quality-score record per dataset_id.

    Ingest is TRUNCATE + COPY; failed (ok:false) records are skipped at ingest
    time so the one-per-dataset invariant is enforced here as a UNIQUE constraint.
    """

    id = models.AutoField(primary_key=True)
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        db_column="dataset_id",
        db_index=False,
    )
    findability = models.IntegerField(blank=True, null=True)
    resources = models.IntegerField(blank=True, null=True)
    created_at = models.TextField(blank=True, null=True)
    json = models.TextField()

    class Meta:
        app_label = "explorer"
        db_table = "reviews"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset"],
                include=["findability", "resources"],
                name="uniq_reviews_dataset",
            ),
        ]

    def __str__(self):
        return str(self.dataset)


class Suggestion(models.Model):
    """One row per dataset — exactly one LLM suggestion record per dataset_id.

    Ingest is TRUNCATE + COPY; failed (ok:false) records are skipped at ingest
    time so the one-per-dataset invariant is enforced here as a UNIQUE constraint.
    """

    id = models.AutoField(primary_key=True)
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        db_column="dataset_id",
        db_index=False,
    )
    theme = models.TextField(blank=True, null=True)
    theme_confidence = models.TextField(blank=True, null=True)
    tags = models.TextField(blank=True, null=True)
    title = models.TextField(blank=True, null=True)
    desc = models.TextField(blank=True, null=True)
    created_at = models.TextField(blank=True, null=True)
    json = models.TextField()

    class Meta:
        app_label = "explorer"
        db_table = "suggestions"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset"],
                include=["theme", "theme_confidence", "tags", "title", "desc"],
                name="uniq_suggestions_dataset",
            ),
        ]

    def __str__(self):
        return self.title or str(self.dataset)


class LinkCheckResult(models.Model):
    """One row per unique URL.

    checked_at is NULL for pending (not yet checked) rows; set once processed.
    method is HEAD | GET | PLAYWRIGHT | SKIPPED | ERROR.
    error uses a short prefix (ssl: dns: timeout: connect: url: playwright:)
    so failures are queryable without a separate column.
    """

    url = models.TextField(primary_key=True)
    checked_at = models.DateTimeField(blank=True, null=True)
    method = models.TextField(blank=True, null=True)
    ok = models.BooleanField(blank=True, null=True)
    http_status = models.IntegerField(blank=True, null=True)
    final_url = models.TextField(blank=True, null=True)
    error = models.TextField(blank=True, null=True)

    class Meta:
        app_label = "explorer"
        db_table = "link_check_results"
        indexes = [
            models.Index(
                fields=["url"],
                include=["ok", "http_status", "error", "checked_at"],
                name="idx_lcr_url_cover",
            ),
        ]

    def __str__(self):
        return self.url or ""


class Collection(models.Model):
    """A curated collection page — one per topic (e.g. "Air quality").

    Populated by scripts/ingest_collections.py from the markdown files in
    data/collections/{collection}/{slug}.md. Views combine Search Console
    clicks (data/console-clicks-apr-aug.csv) with GA page views and Google
    landing sessions (data/ga-views-apr-aug.csv,
    data/ga-google-landing-apr-aug.csv).

    slug is the full path below data/collections/ without extension, e.g.
    "environment/air-quality" — supports arbitrary nesting depth.
    collection is the first path segment for faceting.
    """

    slug = models.TextField(primary_key=True)
    collection = models.TextField()
    title = models.TextField()
    description = models.TextField(blank=True, null=True)
    websites = models.JSONField(blank=True, null=True)
    api = models.JSONField(blank=True, null=True)
    dataset = models.JSONField(blank=True, null=True)
    page_last_updated = models.TextField(blank=True, null=True)
    visualisation_data = models.TextField(blank=True, null=True)
    status = models.TextField(blank=True, null=True)
    views = models.IntegerField(db_default=0)
    related_count = models.IntegerField(blank=True, null=True)

    class Meta:
        app_label = "explorer"
        db_table = "collection_pages"

    def __str__(self):
        return self.title or self.slug


class CollectionEmbedding(models.Model):
    """Pre-computed vector for a collection page, used as a KNN probe
    against the dataset_embeddings HNSW index."""

    slug = models.OneToOneField(
        Collection,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="slug",
        db_index=False,
    )
    embedding = VectorField(dimensions=768)

    class Meta:
        app_label = "explorer"
        db_table = "collection_embeddings"

    def __str__(self):
        return str(self.slug)


class RelatedDataset(models.Model):
    """Pre-computed semantic related datasets for the dataset detail page.

    Populated by scripts/build_related.py after build-embeddings. rank is
    1-based position; score is L2 distance. The baked query joins through
    datasets for display columns."""

    dataset_id = models.IntegerField(db_index=False)
    related = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        db_column="related_id",
        related_name="+",
        db_index=False,
    )
    rank = models.IntegerField()
    score = models.FloatField()
    pk = models.CompositePrimaryKey("dataset_id", "rank")

    class Meta:
        app_label = "explorer"
        db_table = "related_datasets"

    def __str__(self):
        return f"{self.dataset_id} → {self.related_id} (#{self.rank})"


class CollectionRelatedDataset(models.Model):
    """Pre-computed related datasets for the collection detail page.

    Populated by scripts/build_related.py after build-embeddings. rank is
    1-based position (1-12); distance is L2 distance from the collection
    embedding."""

    slug = models.ForeignKey(
        Collection,
        on_delete=models.CASCADE,
        db_column="slug",
        db_index=False,
    )
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        db_column="dataset_id",
        related_name="+",
        db_index=False,
    )
    rank = models.IntegerField()
    distance = models.FloatField()
    pk = models.CompositePrimaryKey("slug", "rank")

    class Meta:
        app_label = "explorer"
        db_table = "collection_related_datasets"

    def __str__(self):
        return f"{self.slug_id} → {self.dataset_id} (#{self.rank})"
