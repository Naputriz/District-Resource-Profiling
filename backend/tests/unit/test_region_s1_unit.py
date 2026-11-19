"""
Unit tests for Task S1: Sumatra regions catalogue ordering/metadata,
PBF routing in load_region.py, and source_id deduplication across overlapping PBFs.
Marker: unit.
"""

from shapely.geometry import Polygon
import pytest
from fastapi.testclient import TestClient

from backend.app.api.routers.regions import REGIONS_CATALOG, clear_regions_cache
from backend.app.main import app
from pipeline.load_region import (
    SUPPORTED_PROVINCES,
    filter_and_dedup_facilities_for_province,
    resolve_pbf_specs_for_province,
)

pytestmark = pytest.mark.unit
client = TestClient(app)

SUMATRA_CODES = ["11", "12", "13", "14", "15", "16", "17", "18", "19", "21"]


def test_regions_catalog_includes_sumatra_ordered_by_code():
    """All 10 Sumatra provinces exist in REGIONS_CATALOG and /api/v1/regions returns codes sorted."""
    clear_regions_cache()
    for code in SUMATRA_CODES:
        assert code in REGIONS_CATALOG
        entry = REGIONS_CATALOG[code]
        assert entry["geojson_url"] == f"/data/boundaries/{code}_kecamatan.geojson"
        assert entry["total_districts"] > 0
        assert len(entry["bbox"]) == 4
        assert len(entry["center"]) == 2

    # Northern hemisphere centroids -> 326xx, southern -> 327xx
    for code in ("11", "12", "14", "21"):
        assert 32646 <= REGIONS_CATALOG[code]["utm_srid"] <= 32649
    for code in ("13", "15", "16", "17", "18", "19"):
        assert 32747 <= REGIONS_CATALOG[code]["utm_srid"] <= 32749

    res = client.get("/api/v1/regions")
    assert res.status_code == 200
    codes = [r["province_code"] for r in res.json()]
    assert codes == sorted(codes)
    assert set(SUMATRA_CODES).issubset(set(codes))


def test_load_region_pbf_routing_and_override():
    """Sumatra PBF routing maps 11-18 -> sumatra, 19 -> kalimantan, 21 -> sumatra+kalimantan, and supports --pbf."""
    for code in ("11", "12", "13", "14", "15", "16", "17", "18"):
        assert SUPPORTED_PROVINCES[code]["island"] == "sumatra"
        specs = resolve_pbf_specs_for_province(code)
        assert [s["path"].name for s in specs] == ["sumatra-latest.osm.pbf"]

    specs_19 = resolve_pbf_specs_for_province("19")
    assert [s["path"].name for s in specs_19] == ["kalimantan-latest.osm.pbf"]

    specs_21 = resolve_pbf_specs_for_province("21")
    assert [s["path"].name for s in specs_21] == [
        "sumatra-latest.osm.pbf",
        "kalimantan-latest.osm.pbf",
    ]

    override_specs = resolve_pbf_specs_for_province("19", pbf_override="sumatra")
    assert [s["path"].name for s in override_specs] == ["sumatra-latest.osm.pbf"]


def test_filter_and_dedup_drops_duplicate_source_id_from_overlapping_pbfs():
    """Unnamed facilities appearing in both Sumatra and Kalimantan PBFs are deduplicated by source_id."""
    poly = Polygon([(104.0, -0.5), (105.0, -0.5), (105.0, 0.5), (104.0, 0.5)])
    districts = [{"geom": poly}]
    fac_a = {
        "source_id": "node/999001",
        "facility_type": "sekolah_dasar",
        "name": None,
        "osm_type": "node",
        "coordinates": {"type": "Point", "coordinates": [104.5, 0.0]},
        "metadata": {},
    }
    fac_b = dict(fac_a)  # same unnamed source_id from second PBF
    deduped, _ = filter_and_dedup_facilities_for_province([fac_a, fac_b], districts)
    assert len(deduped) == 1
    assert deduped[0]["source_id"] == "node/999001"
