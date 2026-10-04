def post_worker_init(worker):
    try:
        from explorer.queries.collections import collections_facet_counts
        from explorer.queries.dashboard import cards
        from explorer.queries.datasets import datasets_facet_counts
        from explorer.queries.harvesters import harvest_source_rows, harvested_total
        from explorer.queries.links import links_facet_counts, links_stats
        from explorer.queries.organisations import (
            all_org_rows,
            org_aggregate_rows,
            org_created_years,
            org_last_published_years,
            org_link_health_rows,
            organisations_facet_counts,
        )
        from explorer.queries.reports import REPORTS, report_unfiltered_count, report_unfiltered_options

        cards()
        all_org_rows()
        org_aggregate_rows()
        org_created_years()
        org_last_published_years()
        org_link_health_rows()
        organisations_facet_counts()
        datasets_facet_counts()
        links_facet_counts({})
        links_stats()
        collections_facet_counts({})
        harvest_source_rows()
        harvested_total()
        for report in REPORTS:
            report_unfiltered_count(report["key"])
            report_unfiltered_options(report["key"])
    except Exception:
        pass
