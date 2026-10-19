"""Turn saved placements into KiotViet browser jobs, with every saved location of each product."""

from __future__ import annotations

from mapper.features.web_upload import LocationUpdate, UploadProduct
from mapper.persistence.models import Placement


def location_updates(db, product_ids) -> list[LocationUpdate]:
    """One update per product listing all of its saved locations (empty clears the website)."""
    product_ids = list(dict.fromkeys(product_ids))
    locations = db.get_location_sets(product_ids)
    return [LocationUpdate(pid, locations.get(pid, ())) for pid in product_ids]


def upload_products(db, placements: list[tuple[str, Placement]]) -> list[UploadProduct]:
    """Stock + location jobs; refused up front when any product has no recorded quantity."""
    missing = [pid for pid, placement in placements if placement.stock_qty is None]
    if missing:
        more = f" and {len(missing) - 3} more" if len(missing) > 3 else ""
        raise ValueError(f"Cannot upload because {', '.join(missing[:3])}{more} has no recorded quantity. "
                         "Return the product to on-hand and assign it again with a quantity.")
    locations = db.get_location_sets(pid for pid, _ in placements)
    return [UploadProduct(pid, placement.stock_qty, locations.get(pid, ())) for pid, placement in placements]
