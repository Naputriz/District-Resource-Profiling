"""
Unit tests for Task C1: Sulawesi regions catalogue ordering/metadata,
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

SULAWESI_CODES = ["71", "72", "73", "74", "75", "76"]


def test_regions_catalog_includes_sulawesi_ordered_by_code():
    """All 6 Sulawesi provinces exist in REGIONS_CATALOG and /api/v1/regions returns codes sorted."""
    clear_regions_cache()
    for code in SULAWESI_CODES:
        assert code in REGIONS_CATALOG
        entry = REGIONS_CATALOG[code]
        assert entry["geojson_url"] == f"/data/boundaries/{code}_kecamatan.geojson"
        assert entry["total_districts"] > 0
        assert len(entry["bbox"]) == 4
        assert len(entry["center"]) == 2

    # Northern hemisphere centroids -> 326xx, southern -> 327xx
    for code in ("71", "75"):
        assert 32650 <= REGIONS_CATALOG[code]["utm_srid"] <= 32652
    for code in ("72", "73", "74", "76"):
        assert 32750 <= REGIONS_CATALOG[code]["utm_srid"] <= 32751

    res = client.get("/api/v1/regions")
    assert res.status_code == 200
    codes = [r["province_code"] for r in res.json()]
    assert codes == sorted(codes)
    assert set(SULAWESI_CODES).issubset(set(codes))


def test_load_region_sulawesi_pbf_routing_and_override():
    """Sulawesi PBF routing maps 71/73/74/75 -> sulawesi, 72 -> sulawesi+maluku, 76 -> sulawesi+kalimantan."""
    for code in ("71", "73", "74", "75"):
        assert SUPPORTED_PROVINCES[code]["island"] == "sulawesi"
        specs = resolve_pbf_specs_for_province(code)
        assert [s["path"].name for s in specs] == ["sulawesi-latest.osm.pbf"]

    specs_72 = resolve_pbf_specs_for_province("72")
    assert [s["path"].name for s in specs_72] == [
        "sulawesi-latest.osm.pbf",
        "maluku-latest.osm.pbf",
    ]

    specs_76 = resolve_pbf_specs_for_province("76")
    assert [s["path"].name for s in specs_76] == [
        "sulawesi-latest.osm.pbf",
        "kalimantan-latest.osm.pbf",
    ]

    override_specs = resolve_pbf_specs_for_province("72", pbf_override="sulawesi")
    assert [s["path"].name for s in override_specs] == ["sulawesi-latest.osm.pbf"]


def test_filter_and_dedup_drops_duplicate_source_id_across_sulawesi_maluku():
    """Facilities appearing in both Sulawesi and Maluku PBFs are deduplicated by source_id."""
    poly = Polygon([(123.3, -2.3), (124.2, -2.3), (124.2, -1.7), (123.3, -1.7)])
    districts = [{"geom": poly}]
    fac_a = {
        "source_id": "node/888001",
        "facility_type": "sekolah_dasar",
        "name": None,
        "osm_type": "node",
        "coordinates": {"type": "Point", "coordinates": [123.8, -2.0]},
        "metadata": {},
    }
    fac_b = dict(fac_a)
    deduped, _ = filter_and_dedup_facilities_for_province([fac_a, fac_b], districts)
    assert len(deduped) == 1
    assert deduped[0]["source_id"] == "node/888001"
