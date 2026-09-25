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
from .datasets import datasets
from .harvesters import harvester, harvesters
from .links import links
from .links_errors import link_errors
from .metadata import metadata_detail, metadata_overview
from .organisation import organisation
from .organisations import organisations
from .reports import report
from .reviews import reviews
from .search import publisher_suggest, search, search_datasets, search_publishers
from .series import series_detail, series_list
from .suggestions import suggestions

__all__ = [
    "_page_param",
    "check_progress",
    "check_progress_data",
    "collection_detail",
    "collections",
    "dashboard",
    "dataset",
    "datasets",
    "harvester",
    "harvesters",
    "health",
    "link_errors",
    "links",
    "metadata_detail",
    "metadata_overview",
    "not_found",
    "organisation",
    "organisations",
    "paginate",
    "publisher_suggest",
    "report",
    "reviews",
    "search",
    "search_datasets",
    "search_publishers",
    "series_detail",
    "series_list",
    "suggestions",
]
