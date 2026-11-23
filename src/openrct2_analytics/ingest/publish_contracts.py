"""Run the contract checks against a publish candidate."""

from __future__ import annotations

from pathlib import Path

from openrct2_analytics.ingest import contracts, play_mode_feed, registry_feed
from openrct2_analytics.ingest.publish_errors import PublishFailed


def check_contracts(candidate_dir: Path, *, data_set: str | None = None) -> None:
    """Check every contract against the candidate's landing Parquet and the copied feed.

    Args:
        candidate_dir: Candidate folder containing the copied ``landing`` data.
        data_set: Data set being published; the candidate folder is not named for it, so the
            label check cannot infer it.

    Raises:
        PublishFailed: If one or more contracts report a failure.
    """
    landing = candidate_dir / "landing"
    results = contracts.check_all(landing)
    failures = [f"{name}: {problem}" for name, problems in results.items() for problem in problems]
    failures += [
        f"registry feed: {problem}" for problem in registry_feed.check_feed(landing / "registry")
    ]
    failures += [
        f"play-mode feed: {problem}"
        for problem in play_mode_feed.check_feed(landing / "registry", data_set=data_set)
    ]
    if failures:
        raise PublishFailed("contracts", "; ".join(failures))
