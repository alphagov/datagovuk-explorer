"""Django models — the tables the migrations own.

Schema notes:
- Timestamps are TEXT in the DB (format_date exists for a reason) — TextField,
  not DateTimeField.
- links.id / series.id are SERIAL -> AutoField.
- embedding_map.rowid / dataset_embeddings.rowid are plain INTEGER PRIMARY KEY
  (embed_batch assigns dense rowids from 1) -> IntegerField(primary_key=True),
  not AutoField.
- datasets.fts (tsvector) and dataset_embeddings.embedding (vector(768)) are
  deliberately NOT here — they're added by a RunSQL migration (0002) that
  creates the vector extension first.
- Indexes are migration-owned (0003: the 10 idx_* + GIN) — FK fields are
  db_index=False so Django doesn't emit its own.
- metadata_values and series_datasets use Django 6 composite primary keys
  (pk = CompositePrimaryKey(...)) — no implicit id column.

The query layer is raw SQL via django.db.connection; these models exist to
own the schema via migrations.
"""

from django.db import models


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

    class Meta:
        app_label = "explorer"
        db_table = "harvest_sources"

    def __str__(self):
        return self.title or self.id


class Dataset(models.Model):
    id = models.TextField(primary_key=True)
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

    class Meta:
        app_label = "explorer"
        db_table = "datasets"

    def __str__(self):
        return self.title or self.name or self.id


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

    api_category is 'map-layers' or 'data-apis'. api_links is the jsonb
    aggregate of every matched link (name/format_norm/url). The table is
    wiped and rebuilt on every build; the report and datasets-page facet
    query it instead of running the full 22-condition EXISTS chain at
    request time."""

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
    resource URL set, for exact-duplicate detection (Tier 1 — see
    docs/ideas.md "Duplicate dataset detection"). Computed by a single
    INSERT...SELECT in scripts/build_db.py, TRUNCATE + rebuilt like
    dataset_api, so the hash algorithm can be tweaked without a full
    rebuild. content_hash is indexed (not unique — that's the point:
    GROUP BY content_hash HAVING COUNT(*) > 1 finds the duplicate sets)
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


class DatasetJson(models.Model):
    dataset = models.OneToOneField(
        Dataset,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="id",
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
    """Maps a dataset id to its dense rowid in dataset_embeddings.

    The vector itself lives only in dataset_embeddings (the pgvector probe
    is derived from it); 0001's duplicate `vector_text` column was dropped
    in 0014.
    """

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

    def __str__(self):
        return str(self.dataset)


class DatasetEmbedding(models.Model):
    rowid = models.IntegerField(primary_key=True)

    class Meta:
        app_label = "explorer"
        db_table = "dataset_embeddings"

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
    dataset_id = models.TextField()
    dataset_title = models.TextField()
    date_suffix = models.TextField(blank=True, null=True)
    org_slug = models.TextField()
    org_display_name = models.TextField()
    pk = models.CompositePrimaryKey("series", "dataset_id")

    class Meta:
        app_label = "explorer"
        db_table = "series_datasets"

    def __str__(self):
        return self.dataset_title


class Review(models.Model):
    """One row per LLM review record.

    `json` holds the JSONL record verbatim and is what the views read (via
    explorer/queries), so the dict shape the templates expect is preserved;
    the typed columns mirror its suggestion fields.
    """

    id = models.AutoField(primary_key=True)
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        db_column="dataset_id",
        db_index=True,
    )
    ok = models.BooleanField(db_default=True)
    overall = models.IntegerField(blank=True, null=True)
    findability = models.IntegerField(blank=True, null=True)
    metadata = models.IntegerField(blank=True, null=True)
    resources = models.IntegerField(blank=True, null=True)
    theme = models.TextField(blank=True, null=True)
    tags = models.TextField(blank=True, null=True)
    title = models.TextField(blank=True, null=True)
    desc = models.TextField(blank=True, null=True)
    theme_confidence = models.TextField(blank=True, null=True)
    created_at = models.TextField(blank=True, null=True)
    json = models.TextField()

    class Meta:
        app_label = "explorer"
        db_table = "reviews"

    def __str__(self):
        return self.title or str(self.dataset)


class LinkCheckResult(models.Model):
    """One row per link, keyed by link_id.

    url is copied from links.url and indexed so check_links can bulk-update
    all rows for a given URL in one UPDATE WHERE url = ?.  checked_at is NULL
    for pending (not yet checked) rows; set once the link is processed.
    method is HEAD | GET | PLAYWRIGHT | SKIPPED | ERROR.
    error uses a short prefix (ssl: dns: timeout: connect: url: playwright:)
    so failures are queryable without a separate column.
    """

    link = models.OneToOneField(
        Link,
        db_column="link_id",
        on_delete=models.DO_NOTHING,
        primary_key=True,
    )
    url = models.TextField(blank=True, null=True)
    checked_at = models.TextField(blank=True, null=True)
    method = models.TextField(blank=True, null=True)
    ok = models.BooleanField(blank=True, null=True)
    http_status = models.IntegerField(blank=True, null=True)
    final_url = models.TextField(blank=True, null=True)
    error = models.TextField(blank=True, null=True)

    class Meta:
        app_label = "explorer"
        db_table = "link_check_results"
        indexes = [models.Index(fields=["url"], name="link_check_results_url_idx")]

    def __str__(self):
        return self.url or f"link:{self.link_id}"
