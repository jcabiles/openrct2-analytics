"""The dashboard's Sandbox-park texts: the banner sentence and the labels script.

Both come from one mapping of park ID to the label ``park_label`` built, so the banner and the
page's switch name a park the same way. This module never builds a label from park facts.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

REBUILD_HINT = (
    "; the warehouse was built before Sandbox parks could be told apart: file the waiting play "
    "in the OpenRCT2 Enterprise app, or run make transform DATA_SET=company"
)


def label_of_park(park_id: str, labels: dict[str, str]) -> str:
    """The park's label if it names a first-played date, else its ID with the unavailable-date note.

    ``park_label`` shows a park with no first-played time as the bare ID or ``<name> (<ID>)``; both
    are undated, and a dated label never ends with `` (<ID>)``.
    """
    label = labels.get(park_id)
    if label is None or label == park_id or label.endswith(f" ({park_id})"):
        return f"{park_id} (first-played date unavailable)"
    return label


def sandbox_sentences(ids: Iterable[str], labels: dict[str, str]) -> list[str]:
    """One banner sentence per Sandbox park, in park ID order."""
    return [
        f"Sandbox park {label_of_park(park, labels)} is left out of the All parks figures "
        f"unless Sandbox parks are included; remove it with make delete-company-data PARK={park}."
        for park in sorted(ids)
    ]


def labels_script(ids: Iterable[str], labels: dict[str, str]) -> str:
    """The script element that sets ``window.DASHBOARD_LABELS``, parks in ID order.

    Every ``<`` is escaped, so a park name cannot close the element.
    """
    mapping = {park: label_of_park(park, labels) for park in sorted(ids)}
    text = json.dumps(mapping).replace("<", "\\u003c")
    return f"<script>window.DASHBOARD_LABELS = {text};</script>"
