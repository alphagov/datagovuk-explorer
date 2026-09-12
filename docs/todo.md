# Todo

## Move pill construction into views

Pill-building is split between two patterns: some pages build the `pills`
list in the view (e.g. `links_errors`) and some build it in Jinja2 (e.g.
`datasets`, `links`). The template approach requires the view to pass both a
slug variable (for the `if` guard) and a resolved display-name variable (for
the label), with no enforcement that both are present or consistently named.
The Python approach makes the lookup explicit.

Consolidate by moving all pill construction into views, matching the
`links_errors` pattern. This eliminates the class of bug where a new facet's
pill silently shows a slug instead of a display name.
