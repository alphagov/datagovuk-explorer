import time


def post_worker_init(worker):
    # Warm the per-process query caches after each worker forks (see the
    # @functools.cache / @cached_unfiltered entry points in
    # explorer/queries/). Imports are function-local on purpose: gunicorn
    # imports this config in the master before the WSGI app (so Django
    # settings aren't ready at module import). Wrapped in try/except so a
    # warm-up failure can never stop a worker from serving — logged, not
    # swallowed.
    start = time.perf_counter()
    try:
        from explorer.queries.collections import collections_facet_counts
        from explorer.queries.dashboard import cards
        from explorer.queries.datasets import (
            dataset_created_years,
            datasets_facet_counts,
            fetched_slugs,
        )
        from explorer.queries.harvesters import harvest_source_rows, harvested_total
        from explorer.queries.links import links_facet_counts, links_stats
        from explorer.queries.organisations import (
            org_created_years,
            org_last_published_years,
            org_link_health_rows,
            organisations_facet_counts,
        )
        from explorer.queries.reports import REPORTS, report_unfiltered_count, report_unfiltered_options

        cards()
        # org_aggregate_rows() is reached via org_last_published_years(), so
        # it isn't warmed separately.
        org_created_years()
        org_last_published_years()
        org_link_health_rows()
        organisations_facet_counts({})
        datasets_facet_counts({})
        # datasets' other memoised fixed fetches (used by the /datasets view).
        fetched_slugs()
        dataset_created_years()
        links_facet_counts({})
        links_stats()
        collections_facet_counts({})
        harvest_source_rows()
        harvested_total()
        for report in REPORTS:
            report_unfiltered_count(report["key"])
            report_unfiltered_options(report["key"])
        worker.log.info("query cache warm-up completed in %.2fs", time.perf_counter() - start)
    except Exception as exc:
        worker.log.warning("query cache warm-up failed after %.2fs: %s", time.perf_counter() - start, exc)
