"""Read the optional humor_references collection.

The CSV is the primary list. This repository only adds rows when someone has
also written them to MongoDB. It does not cache, and it does not own the sync.
"""

from pymongo.collection import Collection

from merchandise_discovery.domain.humor_references import (
    HumorReference,
    humor_reference_id,
    text_is_theme,
)


class HumorReferenceRepository:
    """Load every humor reference fresh. This repository does not cache documents."""

    def __init__(self, collection: Collection):
        self._collection = collection

    def list_all(self) -> list[HumorReference]:
        """Return the current collection. Callers should not keep the result across runs."""

        references: list[HumorReference] = []
        for document in self._collection.find({}):
            references.append(_from_document(document))
        return references


def _from_document(document: dict) -> HumorReference:
    """Map a Mongo row onto the typed reference, using `_id` as the stable text hash."""

    payload = dict(document)
    mongo_id = payload.pop("_id", None)
    text = str(payload.get("text") or payload.get("sticker_text_or_idea") or "").strip()
    flagged = bool(payload.get("is_theme"))
    niche = str(payload.get("niche") or payload.get("identity") or payload.get("identities") or "")
    sales = _as_int(
        payload.get("demand")
        or payload.get("sales")
        or payload.get("units_sold")
        or payload.get("upvotes")
    )
    reference = HumorReference(
        text=text or "untitled",
        upvotes=_as_int(payload.get("upvotes")),
        humor_type=str(payload.get("humor_type") or ""),
        niche=niche,
        subreddit=str(payload.get("subreddit") or payload.get("source") or ""),
        post_url=str(payload.get("post_url") or payload.get("url") or ""),
        date_found=str(payload.get("date_found") or ""),
        is_theme=text_is_theme(text, flagged),
        reference_id=str(payload.get("reference_id") or mongo_id or humor_reference_id(text or "untitled")),
        hook=str(payload.get("hook") or payload.get("hooks") or ""),
        theme=str(payload.get("theme") or payload.get("topic") or ""),
        demand=sales,
    )
    return reference


def _as_int(value: object) -> int:
    """Coerce upvote counts from Mongo or CSV-shaped documents."""

    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
