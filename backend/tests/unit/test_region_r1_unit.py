"""
Unit tests for Task R1: Rest of Indonesia (Bali-Nusa Tenggara 51-53, Kalimantan 61-65, Maluku 81-82).
Validates 38-province REGIONS_CATALOG ordering/metadata and load_region.py PBF routing.
Marker: unit.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routers.regions import REGIONS_CATALOG, clear_regions_cache
from backend.app.main import app
from pipeline.load_region import SUPPORTED_PROVINCES, resolve_pbf_specs_for_province

pytestmark = pytest.mark.unit
client = TestClient(app)

REST_CODES = ["51", "52", "53", "61", "62", "63", "64", "65", "81", "82"]


def test_regions_catalog_has_all_38_provinces_ordered_by_code():
    """All 38 Indonesian provinces exist in REGIONS_CATALOG and /api/v1/regions returns codes sorted."""
    clear_regions_cache()
    assert len(REGIONS_CATALOG) == 38
    for code in REST_CODES:
        assert code in REGIONS_CATALOG
        entry = REGIONS_CATALOG[code]
        assert entry["geojson_url"] == f"/data/boundaries/{code}_kecamatan.geojson"
        assert entry["total_districts"] > 0
        assert len(entry["bbox"]) == 4
        assert len(entry["center"]) == 2
        assert 32649 <= entry["utm_srid"] <= 32753

    res = client.get("/api/v1/regions")
    assert res.status_code == 200
    codes = [r["province_code"] for r in res.json()]
    assert len(codes) == 38
    assert codes == sorted(codes)
    assert set(REST_CODES).issubset(set(codes))


def test_load_region_rest_pbf_routing():
    """load_region.py maps 51-53 -> nusa-tenggara, 61-65 -> kalimantan, 81-82 -> maluku."""
    assert len(SUPPORTED_PROVINCES) == 37  # All provinces except DKI 31 (pre-loaded)

    for code in ("51", "52", "53"):
        assert SUPPORTED_PROVINCES[code]["island"] == "nusa-tenggara"
        specs = resolve_pbf_specs_for_province(code)
        assert [s["path"].name for s in specs] == ["nusa-tenggara-latest.osm.pbf"]

    for code in ("61", "62", "63", "64", "65"):
        assert SUPPORTED_PROVINCES[code]["island"] == "kalimantan"
        specs = resolve_pbf_specs_for_province(code)
        assert [s["path"].name for s in specs] == ["kalimantan-latest.osm.pbf"]

    for code in ("81", "82"):
        assert SUPPORTED_PROVINCES[code]["island"] == "maluku"
        specs = resolve_pbf_specs_for_province(code)
        assert [s["path"].name for s in specs] == ["maluku-latest.osm.pbf"]

    override_specs = resolve_pbf_specs_for_province("34", pbf_override="nusa-tenggara")
    assert [s["path"].name for s in override_specs] == ["nusa-tenggara-latest.osm.pbf"]
