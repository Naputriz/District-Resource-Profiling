"""
Unit tests for J1a (Redis DB config, shared OSM classification, live-DB guard).
"""

from unittest.mock import patch, MagicMock
import pytest

from backend.app.core.config import settings
from backend.app.core import db as core_db
from pipeline.osm_extractor import (
    OSMExtractor,
    classify_osm_element,
    classify_osm_element_auto,
    matching_query_groups,
)
from pipeline.load_region import (
    codab_pcode_to_codes,
    codab_pcode_to_dki_kemendagri,
    ensure_safe_database,
    is_non_district_pcode,
)

pytestmark = pytest.mark.unit


def test_redis_db_setting_passed_to_redis_client():
    """Step 0: init_db_pool passes db=settings.REDIS_DB to redis.Redis."""
    mock_pool = MagicMock()
    mock_redis_inst = MagicMock()
    orig_db = settings.REDIS_DB
    orig_pool = core_db.db_pool
    orig_rc = core_db.redis_client
    try:
        settings.REDIS_DB = 1
        with patch("backend.app.core.db.pool.ThreadedConnectionPool", return_value=mock_pool), \
             patch("backend.app.core.db.redis.Redis", return_value=mock_redis_inst) as mock_redis_cls:
            core_db.init_db_pool()
            mock_redis_cls.assert_called_once()
            _, kwargs = mock_redis_cls.call_args
            assert kwargs["db"] == 1
            assert kwargs["host"] == "127.0.0.1" or kwargs["host"] == settings.REDIS_HOST
            assert kwargs["port"] == settings.REDIS_PORT
            assert kwargs["decode_responses"] is True
    finally:
        settings.REDIS_DB = orig_db
        core_db.db_pool = orig_pool
        core_db.redis_client = orig_rc


def test_shared_osm_classification_matches_dki_extractor(tmp_path):
    """
    Step 5: Shared classify_osm_element / classify_osm_element_auto produces identical
    classification to OSMExtractor.classify_element on a DKI Jakarta sample.
    """
    samples = [
        ("group1_lifeline_health", {"type": "node", "id": 1001, "lat": -6.23, "lon": 106.85, "tags": {"amenity": "clinic", "name": "Puskesmas Kelurahan Tebet Barat"}}),
        ("group1_lifeline_health", {"type": "way", "id": 1002, "center": {"lat": -6.22, "lon": 106.84}, "tags": {"amenity": "clinic", "name": "Puskesmas Kecamatan Tebet"}}),
        ("group1_lifeline_health", {"type": "way", "id": 1003, "center": {"lat": -6.21, "lon": 106.82}, "tags": {"amenity": "hospital", "name": "RSUD Tebet"}}),
        ("group1_lifeline_health", {"type": "node", "id": 1004, "lat": -6.21, "lon": 106.82, "tags": {"amenity": "hospital", "name": "Klinik Pratama Medika"}}),
        ("group1_lifeline_health", {"type": "node", "id": 1005, "lat": -6.20, "lon": 106.83, "tags": {"amenity": "fire_station", "name": "Pos Damkar Tebet"}}),
        ("group1_lifeline_health", {"type": "node", "id": 1006, "lat": -6.20, "lon": 106.83, "tags": {"amenity": "police", "name": "Polsek Tebet"}}),
        ("group2_human_capital_education", {"type": "way", "id": 2001, "center": {"lat": -6.23, "lon": 106.85}, "tags": {"amenity": "school", "name": "SDN Tebet Timur 01"}}),
        ("group2_human_capital_education", {"type": "way", "id": 2002, "center": {"lat": -6.23, "lon": 106.85}, "tags": {"amenity": "school", "name": "SMPN 115 Jakarta"}}),
        ("group2_human_capital_education", {"type": "way", "id": 2003, "center": {"lat": -6.23, "lon": 106.85}, "tags": {"amenity": "school", "name": "SMAN 8 Jakarta"}}),
        ("group2_human_capital_education", {"type": "node", "id": 2004, "lat": -6.23, "lon": 106.85, "tags": {"amenity": "kindergarten", "name": "TK Islam Al Azhar"}}),
        ("group3_urban_livability_recreation", {"type": "way", "id": 3001, "center": {"lat": -6.24, "lon": 106.86}, "tags": {"leisure": "park", "name": "RPTRA Tebet"}}),
        ("group3_urban_livability_recreation", {"type": "way", "id": 3002, "center": {"lat": -6.24, "lon": 106.86}, "tags": {"leisure": "park", "name": "Taman Honda Tebet"}}),
        ("group4_mobility_commercial", {"type": "node", "id": 4001, "lat": -6.22, "lon": 106.85, "tags": {"railway": "station", "name": "Stasiun Tebet"}}),
        ("group4_mobility_commercial", {"type": "node", "id": 4002, "lat": -6.22, "lon": 106.85, "tags": {"highway": "bus_stop", "operator": "TransJakarta", "name": "Halte Tebet Eco Park"}}),
        ("group4_mobility_commercial", {"type": "node", "id": 4003, "lat": -6.22, "lon": 106.85, "tags": {"amenity": "marketplace", "name": "Pasar Tebet Barat"}}),
    ]

    extractor = OSMExtractor(
        raw_dir=tmp_path / "raw",
        output_file=tmp_path / "out.json",
    )
    for group_name, el in samples:
        res_method = extractor.classify_element(el, group_name)
        res_shared = classify_osm_element(el, group_name, snapshot_date=res_method["snapshot_date"])
        res_auto = classify_osm_element_auto(el, snapshot_date=res_method["snapshot_date"])

        for k in ("source", "osm_type", "osm_id", "source_id", "name", "facility_type", "pillar", "category", "coordinates", "capacity", "area_m2"):
            assert res_method[k] == res_shared[k], f"Mismatch on {k} for {el['id']}"
            assert res_auto is not None
            assert res_method[k] == res_auto[k], f"Auto mismatch on {k} for {el['id']}"


def test_codab_code_mapping_and_non_district_filter():
    """Step 2 & 5: Verifies DKI exact mapping, non-DKI unambiguous mapping, and water/forest filter."""
    # DKI exact mapping
    assert codab_pcode_to_dki_kemendagri("ID3171090") == "31.71.09"
    assert codab_pcode_to_dki_kemendagri("ID3101010") == "31.01.01"
    with pytest.raises(ValueError):
        codab_pcode_to_dki_kemendagri("ID3175888")

    # Non-DKI preserves split 7th digit unambiguously
    c_antapani = codab_pcode_to_codes("ID3273141")
    c_mandalajati = codab_pcode_to_codes("ID3273142")
    assert c_antapani["cod_ab_pcode"] == "ID3273141"
    assert c_antapani["bps_code"] == "3273141"
    assert c_antapani["kemendagri_code"] == "32.73.141"
    assert c_mandalajati["kemendagri_code"] == "32.73.142"
    assert c_antapani["kemendagri_code"] != c_mandalajati["kemendagri_code"]

    # Non-district water/forest filter
    assert is_non_district_pcode("ID3175888") is True
    assert is_non_district_pcode("ID3175555") is True
    assert is_non_district_pcode("ID3399999") is True
    assert is_non_district_pcode("ID3273230") is False


def test_live_db_guard():
    """Step 5: Refuses live database 'district_profiling' unless allow_live=True."""
    with pytest.raises(RuntimeError, match="district_profiling"):
        ensure_safe_database("district_profiling", allow_live=False)

    # Allowed when allow_live=True or when targeting staging
    ensure_safe_database("district_profiling", allow_live=True)
    ensure_safe_database("district_profiling_stage", allow_live=False)
