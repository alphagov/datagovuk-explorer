"""Migrate datasets PK from TEXT (CKAN UUID) to INTEGER (auto-increment).

The CKAN UUID moves to a new ``ckan_id`` column (unique, indexed).
All FK / plain-text columns that referenced the old TEXT id are converted
to INTEGER via a JOIN on the new mapping.  Works on an empty DB (fresh-db)
and on a populated one (preserves all rows).
"""

from django.db import migrations, models


# Forward SQL — executed top-to-bottom inside a single transaction.
_FORWARD = """
-- 0. Drop every FK constraint and index that touches the old TEXT id.
--    Constraint names come from Django's auto-naming and any we created
--    in prior migrations; IF EXISTS keeps this idempotent.

DO $do$
DECLARE
    r RECORD;
BEGIN
    -- Drop ALL foreign-key constraints that reference datasets
    FOR r IN
        SELECT tc.table_name, tc.constraint_name
          FROM information_schema.table_constraints tc
          JOIN information_schema.constraint_column_usage ccu
            ON ccu.constraint_name = tc.constraint_name
           AND ccu.constraint_schema = tc.constraint_schema
         WHERE tc.constraint_type = 'FOREIGN KEY'
           AND ccu.table_name = 'datasets'
    LOOP
        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I',
                       r.table_name, r.constraint_name);
    END LOOP;
END $do$;

-- Drop composite PKs on child tables
ALTER TABLE temporal_periods      DROP CONSTRAINT IF EXISTS temporal_periods_pkey;
ALTER TABLE dataset_api           DROP CONSTRAINT IF EXISTS dataset_api_pkey;
ALTER TABLE dataset_content_hash  DROP CONSTRAINT IF EXISTS dataset_content_hash_pkey;
ALTER TABLE dataset_json          DROP CONSTRAINT IF EXISTS dataset_json_pkey;
ALTER TABLE series_datasets       DROP CONSTRAINT IF EXISTS series_datasets_pkey;
ALTER TABLE related_datasets      DROP CONSTRAINT IF EXISTS related_datasets_pkey;

-- Drop named indexes
DROP INDEX IF EXISTS idx_datasets_reviews_cover;
DROP INDEX IF EXISTS idx_links_dataset;
DROP INDEX IF EXISTS idx_links_url_dataset_org;
DROP INDEX IF EXISTS idx_embedding_map_dataset;
DROP INDEX IF EXISTS idx_series_datasets_dataset;
DROP INDEX IF EXISTS uniq_reviews_dataset;
DROP INDEX IF EXISTS uniq_suggestions_dataset;

-- The datasets PK itself
ALTER TABLE datasets DROP CONSTRAINT IF EXISTS datasets_pkey;

-- 1. Mutate the datasets table
ALTER TABLE datasets RENAME COLUMN id TO ckan_id;
ALTER TABLE datasets ADD COLUMN id SERIAL;
UPDATE datasets SET id = DEFAULT;
ALTER TABLE datasets ADD PRIMARY KEY (id);

CREATE UNIQUE INDEX idx_datasets_ckan_id ON datasets (ckan_id);
CREATE INDEX idx_datasets_ckan_id_cover
    ON datasets (ckan_id) INCLUDE (org_slug, org_display_name, title, theme_primary);

-- 2. Convert each child table's TEXT column to INTEGER

-- temporal_periods
ALTER TABLE temporal_periods ADD COLUMN dataset_id_new INTEGER;
UPDATE temporal_periods tp SET dataset_id_new = d.id
  FROM datasets d WHERE d.ckan_id = tp.dataset_id;
ALTER TABLE temporal_periods DROP COLUMN dataset_id;
ALTER TABLE temporal_periods RENAME COLUMN dataset_id_new TO dataset_id;
ALTER TABLE temporal_periods ALTER COLUMN dataset_id SET NOT NULL;
ALTER TABLE temporal_periods ADD PRIMARY KEY (dataset_id, position);

-- links
ALTER TABLE links ADD COLUMN dataset_id_new INTEGER;
UPDATE links l SET dataset_id_new = d.id
  FROM datasets d WHERE d.ckan_id = l.dataset_id;
ALTER TABLE links DROP COLUMN dataset_id;
ALTER TABLE links RENAME COLUMN dataset_id_new TO dataset_id;
ALTER TABLE links ALTER COLUMN dataset_id SET NOT NULL;

-- dataset_api
ALTER TABLE dataset_api ADD COLUMN dataset_id_new INTEGER;
UPDATE dataset_api da SET dataset_id_new = d.id
  FROM datasets d WHERE d.ckan_id = da.dataset_id;
ALTER TABLE dataset_api DROP COLUMN dataset_id;
ALTER TABLE dataset_api RENAME COLUMN dataset_id_new TO dataset_id;
ALTER TABLE dataset_api ALTER COLUMN dataset_id SET NOT NULL;
ALTER TABLE dataset_api ADD PRIMARY KEY (dataset_id);

-- dataset_content_hash
ALTER TABLE dataset_content_hash ADD COLUMN dataset_id_new INTEGER;
UPDATE dataset_content_hash dch SET dataset_id_new = d.id
  FROM datasets d WHERE d.ckan_id = dch.dataset_id;
ALTER TABLE dataset_content_hash DROP COLUMN dataset_id;
ALTER TABLE dataset_content_hash RENAME COLUMN dataset_id_new TO dataset_id;
ALTER TABLE dataset_content_hash ALTER COLUMN dataset_id SET NOT NULL;
ALTER TABLE dataset_content_hash ADD PRIMARY KEY (dataset_id);

-- dataset_json (id → dataset_id)
ALTER TABLE dataset_json ADD COLUMN dataset_id INTEGER;
UPDATE dataset_json dj SET dataset_id = d.id
  FROM datasets d WHERE d.ckan_id = dj.id;
ALTER TABLE dataset_json DROP COLUMN id;
ALTER TABLE dataset_json ALTER COLUMN dataset_id SET NOT NULL;
ALTER TABLE dataset_json ADD PRIMARY KEY (dataset_id);

-- embedding_map
ALTER TABLE embedding_map ADD COLUMN dataset_id_new INTEGER;
UPDATE embedding_map em SET dataset_id_new = d.id
  FROM datasets d WHERE d.ckan_id = em.dataset_id;
ALTER TABLE embedding_map DROP COLUMN dataset_id;
ALTER TABLE embedding_map RENAME COLUMN dataset_id_new TO dataset_id;

-- reviews
ALTER TABLE reviews ADD COLUMN dataset_id_new INTEGER;
UPDATE reviews r SET dataset_id_new = d.id
  FROM datasets d WHERE d.ckan_id = r.dataset_id;
ALTER TABLE reviews DROP COLUMN dataset_id;
ALTER TABLE reviews RENAME COLUMN dataset_id_new TO dataset_id;
ALTER TABLE reviews ALTER COLUMN dataset_id SET NOT NULL;

-- suggestions
ALTER TABLE suggestions ADD COLUMN dataset_id_new INTEGER;
UPDATE suggestions s SET dataset_id_new = d.id
  FROM datasets d WHERE d.ckan_id = s.dataset_id;
ALTER TABLE suggestions DROP COLUMN dataset_id;
ALTER TABLE suggestions RENAME COLUMN dataset_id_new TO dataset_id;
ALTER TABLE suggestions ALTER COLUMN dataset_id SET NOT NULL;

-- series_datasets
ALTER TABLE series_datasets ADD COLUMN dataset_id_new INTEGER;
UPDATE series_datasets sd SET dataset_id_new = d.id
  FROM datasets d WHERE d.ckan_id = sd.dataset_id;
ALTER TABLE series_datasets DROP COLUMN dataset_id;
ALTER TABLE series_datasets RENAME COLUMN dataset_id_new TO dataset_id;
ALTER TABLE series_datasets ALTER COLUMN dataset_id SET NOT NULL;
ALTER TABLE series_datasets ADD PRIMARY KEY (series_id, dataset_id);

-- related_datasets (both dataset_id and related_id)
ALTER TABLE related_datasets ADD COLUMN dataset_id_new INTEGER;
ALTER TABLE related_datasets ADD COLUMN related_id_new INTEGER;
UPDATE related_datasets rd SET dataset_id_new = d.id
  FROM datasets d WHERE d.ckan_id = rd.dataset_id;
UPDATE related_datasets rd SET related_id_new = d.id
  FROM datasets d WHERE d.ckan_id = rd.related_id;
ALTER TABLE related_datasets DROP COLUMN dataset_id;
ALTER TABLE related_datasets DROP COLUMN related_id;
ALTER TABLE related_datasets RENAME COLUMN dataset_id_new TO dataset_id;
ALTER TABLE related_datasets RENAME COLUMN related_id_new TO related_id;
ALTER TABLE related_datasets ALTER COLUMN dataset_id SET NOT NULL;
ALTER TABLE related_datasets ALTER COLUMN related_id SET NOT NULL;
ALTER TABLE related_datasets ADD PRIMARY KEY (dataset_id, rank);

-- collection_related_datasets
ALTER TABLE collection_related_datasets ADD COLUMN dataset_id_new INTEGER;
UPDATE collection_related_datasets crd SET dataset_id_new = d.id
  FROM datasets d WHERE d.ckan_id = crd.dataset_id;
ALTER TABLE collection_related_datasets DROP COLUMN dataset_id;
ALTER TABLE collection_related_datasets RENAME COLUMN dataset_id_new TO dataset_id;
ALTER TABLE collection_related_datasets ALTER COLUMN dataset_id SET NOT NULL;

-- 3. Recreate FK constraints
ALTER TABLE temporal_periods
    ADD CONSTRAINT temporal_periods_dataset_id_fk
    FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE;
ALTER TABLE links
    ADD CONSTRAINT links_dataset_id_fk
    FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE;
ALTER TABLE dataset_api
    ADD CONSTRAINT dataset_api_dataset_id_fk
    FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE;
ALTER TABLE dataset_content_hash
    ADD CONSTRAINT dataset_content_hash_dataset_id_fk
    FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE;
ALTER TABLE dataset_json
    ADD CONSTRAINT dataset_json_dataset_id_fk
    FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE;
ALTER TABLE embedding_map
    ADD CONSTRAINT embedding_map_dataset_id_fk
    FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE;
ALTER TABLE reviews
    ADD CONSTRAINT reviews_dataset_id_fk
    FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE;
ALTER TABLE suggestions
    ADD CONSTRAINT suggestions_dataset_id_fk
    FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE;
ALTER TABLE related_datasets
    ADD CONSTRAINT related_datasets_related_id_fk
    FOREIGN KEY (related_id) REFERENCES datasets (id) ON DELETE CASCADE;
ALTER TABLE collection_related_datasets
    ADD CONSTRAINT collection_related_datasets_dataset_id_fk
    FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE;

-- 4. Recreate indexes
CREATE INDEX idx_links_dataset ON links (dataset_id);
CREATE INDEX idx_links_url_dataset_org
    ON links (url, dataset_id, org_slug)
    WHERE url IS NOT NULL AND url != '';
CREATE INDEX idx_embedding_map_dataset ON embedding_map (dataset_id);
CREATE INDEX idx_series_datasets_dataset ON series_datasets (dataset_id);
CREATE UNIQUE INDEX uniq_reviews_dataset
    ON reviews (dataset_id) INCLUDE (findability, resources);
CREATE UNIQUE INDEX uniq_suggestions_dataset
    ON suggestions (dataset_id)
    INCLUDE (theme, theme_confidence, tags, title, "desc");
"""


class Migration(migrations.Migration):

    dependencies = [
        ("explorer", "0006_drop_related_source"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(sql=_FORWARD, reverse_sql=migrations.RunSQL.noop),
            ],
            state_operations=[
                # Dataset: TextField PK → AutoField PK + new ckan_id
                migrations.RemoveIndex(
                    model_name="dataset",
                    name="idx_datasets_reviews_cover",
                ),
                migrations.AlterField(
                    model_name="dataset",
                    name="id",
                    field=models.AutoField(primary_key=True, serialize=False),
                ),
                migrations.AddField(
                    model_name="dataset",
                    name="ckan_id",
                    field=models.TextField(unique=True, default=""),
                    preserve_default=False,
                ),
                migrations.AddIndex(
                    model_name="dataset",
                    index=models.Index(
                        fields=["ckan_id"],
                        include=["org_slug", "org_display_name", "title", "theme_primary"],
                        name="idx_datasets_ckan_id_cover",
                    ),
                ),
                # DatasetJson: db_column "id" → "dataset_id"
                migrations.AlterField(
                    model_name="datasetjson",
                    name="dataset",
                    field=models.OneToOneField(
                        db_column="dataset_id",
                        db_index=False,
                        on_delete=models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="explorer.dataset",
                    ),
                ),
                # SeriesDataset.dataset_id: TextField → IntegerField
                migrations.AlterField(
                    model_name="seriesdataset",
                    name="dataset_id",
                    field=models.IntegerField(),
                ),
                # RelatedDataset.dataset_id: TextField → IntegerField
                migrations.AlterField(
                    model_name="relateddataset",
                    name="dataset_id",
                    field=models.IntegerField(db_index=False),
                ),
            ],
        ),
    ]
