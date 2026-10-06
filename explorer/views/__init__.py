"""View modules, one per route group.

core.py holds the shared helpers (health, 404, _page_param, paginate); the
rest are the per-page modules. Collected here so config/urls.py can address
every view as views.<name>.
"""

from .check_progress import check_progress, check_progress_data
from .collections import collection_detail, collections
from .core import _page_param, health, not_found, paginate
from .dashboard import dashboard
from .dataset import dataset
from .datasets import datasets, datasets_download
from .harvesters import harvester, harvesters, harvesters_download
from .links import links, links_download
from .links_errors import link_errors, link_errors_download
from .metadata import metadata_detail, metadata_download, metadata_overview
from .organisation import organisation
from .organisations import organisations, organisations_download
from .publisher_reviews import publisher_reviews, publisher_reviews_download
from .reports import report, report_download
from .reviews import reviews, reviews_download
from .search import publisher_suggest, search, search_datasets, search_publishers
from .series import series_detail, series_download, series_list
from .suggestions import suggestions, suggestions_download

__all__ = [
    "_page_param",
    "check_progress",
    "check_progress_data",
    "collection_detail",
    "collections",
    "dashboard",
    "dataset",
    "datasets",
    "datasets_download",
    "harvester",
    "harvesters",
    "harvesters_download",
    "health",
    "link_errors",
    "link_errors_download",
    "links",
    "links_download",
    "metadata_detail",
    "metadata_download",
    "metadata_overview",
    "not_found",
    "organisation",
    "organisations",
    "organisations_download",
    "paginate",
    "publisher_reviews",
    "publisher_reviews_download",
    "publisher_suggest",
    "report",
    "report_download",
    "reviews",
    "reviews_download",
    "search",
    "search_datasets",
    "search_publishers",
    "series_detail",
    "series_download",
    "series_list",
    "suggestions",
    "suggestions_download",
]
