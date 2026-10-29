"""
OpenStreetMap (OSM) Overpass API Extractor for DKI Jakarta (4 Pillars of Urban Amenities).
Pillar 1: Lifeline & Healthcare (RSUD, RS, Puskesmas, Damkar, Posyandu)
Pillar 2: Human Capital & Education (SD, SMP, SMA/SMK, TK)
Pillar 3: Urban Livability & Recreation (Taman RT, Taman Kelurahan, Taman Kecamatan, Taman RPTRA)
Pillar 4: Mobility & Commercial (Stasiun KRL/MRT/LRT, Halte TransJakarta, Pasar)

Strictly complies with README.md §6, §7, §14:
- Primary Overpass endpoint: https://overpass-api.de/api/interpreter
- Mandatory header: User-Agent: DistrictProfiling-UI-RPL/0.1 (muhammaddhiya2006@gmail.com)
- Fallback mirror with logging after 3 attempts on primary.
- Sleep >= 5s between queries, timeout 180s per query.
- Nodes and ways (with way centroid as point).
- Raw responses saved unchanged to osm_raw_<YYYYMMDD>/
- Normalized records saved to osm_facilities_<YYYYMMDD>.json
- Elements matching tags without unambiguous category classified as 'unclassified' (never guessed).
"""

import time
import json
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FACILITIES_DIR = DATA_DIR / "facilities"
FACILITIES_DIR.mkdir(parents=True, exist_ok=True)

SNAPSHOT_DATE = datetime.now(timezone.utc).strftime("%Y%m%d")
RAW_DIR = FACILITIES_DIR / f"osm_raw_{SNAPSHOT_DATE}"
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_FILE = FACILITIES_DIR / f"osm_facilities_{SNAPSHOT_DATE}.json"

PRIMARY_ENDPOINT = "https://overpass-api.de/api/interpreter"
FALLBACK_ENDPOINTS = [
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter"
]
USER_AGENT = "DistrictProfiling-UI-RPL/0.1 (muhammaddhiya2006@gmail.com)"

# DKI Jakarta Bounding Box: Mainland Jakarta + Kepulauan Seribu
MAINLAND_BBOX = "-6.3800,106.6800,-6.0800,106.9800"
SERIBU_BBOX = "-5.9900,106.5100,-5.5400,106.6600"

TAG_GROUP_QUERIES = {
    "group1_lifeline_health": f"""
        [out:json][timeout:180];
        (
          node["amenity"="hospital"]({MAINLAND_BBOX});
          way["amenity"="hospital"]({MAINLAND_BBOX});
          node["healthcare"="hospital"]({MAINLAND_BBOX});
          way["healthcare"="hospital"]({MAINLAND_BBOX});
          node["amenity"="clinic"]({MAINLAND_BBOX});
          way["amenity"="clinic"]({MAINLAND_BBOX});
          node["healthcare"="centre"]({MAINLAND_BBOX});
          way["healthcare"="centre"]({MAINLAND_BBOX});
          node["amenity"="fire_station"]({MAINLAND_BBOX});
          way["amenity"="fire_station"]({MAINLAND_BBOX});
          node["amenity"="police"]({MAINLAND_BBOX});
          way["amenity"="police"]({MAINLAND_BBOX});
          node["amenity"="community_centre"]({MAINLAND_BBOX});
          way["amenity"="community_centre"]({MAINLAND_BBOX});
          node["amenity"="hospital"]({SERIBU_BBOX});
          way["amenity"="hospital"]({SERIBU_BBOX});
          node["healthcare"="hospital"]({SERIBU_BBOX});
          way["healthcare"="hospital"]({SERIBU_BBOX});
          node["amenity"="clinic"]({SERIBU_BBOX});
          way["amenity"="clinic"]({SERIBU_BBOX});
          node["healthcare"="centre"]({SERIBU_BBOX});
          way["healthcare"="centre"]({SERIBU_BBOX});
          node["amenity"="fire_station"]({SERIBU_BBOX});
          way["amenity"="fire_station"]({SERIBU_BBOX});
          node["amenity"="police"]({SERIBU_BBOX});
          way["amenity"="police"]({SERIBU_BBOX});
          node["amenity"="community_centre"]({SERIBU_BBOX});
          way["amenity"="community_centre"]({SERIBU_BBOX});
        );
        out center tags;
    """,
    "group2_human_capital_education": f"""
        [out:json][timeout:180];
        (
          node["amenity"="school"]({MAINLAND_BBOX});
          way["amenity"="school"]({MAINLAND_BBOX});
          node["amenity"="kindergarten"]({MAINLAND_BBOX});
          way["amenity"="kindergarten"]({MAINLAND_BBOX});
          node["amenity"="library"]({MAINLAND_BBOX});
          way["amenity"="library"]({MAINLAND_BBOX});
          node["amenity"="school"]({SERIBU_BBOX});
          way["amenity"="school"]({SERIBU_BBOX});
          node["amenity"="kindergarten"]({SERIBU_BBOX});
          way["amenity"="kindergarten"]({SERIBU_BBOX});
          node["amenity"="library"]({SERIBU_BBOX});
          way["amenity"="library"]({SERIBU_BBOX});
        );
        out center tags;
    """,
    "group3_urban_livability_recreation": f"""
        [out:json][timeout:180];
        (
          node["leisure"="park"]({MAINLAND_BBOX});
          way["leisure"="park"]({MAINLAND_BBOX});
          node["leisure"="playground"]({MAINLAND_BBOX});
          way["leisure"="playground"]({MAINLAND_BBOX});
          node["leisure"="sports_centre"]({MAINLAND_BBOX});
          way["leisure"="sports_centre"]({MAINLAND_BBOX});
          node["leisure"="stadium"]({MAINLAND_BBOX});
          way["leisure"="stadium"]({MAINLAND_BBOX});
          node["landuse"="forest"]({MAINLAND_BBOX});
          way["landuse"="forest"]({MAINLAND_BBOX});
          node["amenity"="waste_disposal"]({MAINLAND_BBOX});
          way["amenity"="waste_disposal"]({MAINLAND_BBOX});
          node["amenity"="waste_transfer_station"]({MAINLAND_BBOX});
          way["amenity"="waste_transfer_station"]({MAINLAND_BBOX});
          node["amenity"="recycling"]({MAINLAND_BBOX});
          way["amenity"="recycling"]({MAINLAND_BBOX});
          node["leisure"="park"]({SERIBU_BBOX});
          way["leisure"="park"]({SERIBU_BBOX});
          node["leisure"="sports_centre"]({SERIBU_BBOX});
          way["leisure"="sports_centre"]({SERIBU_BBOX});
        );
        out center tags;
    """,
    "group4_mobility_commercial": f"""
        [out:json][timeout:180];
        (
          node["railway"="station"]({MAINLAND_BBOX});
          way["railway"="station"]({MAINLAND_BBOX});
          node["railway"="subway_entrance"]({MAINLAND_BBOX});
          node["station"="subway"]({MAINLAND_BBOX});
          way["station"="subway"]({MAINLAND_BBOX});
          node["station"="light_rail"]({MAINLAND_BBOX});
          way["station"="light_rail"]({MAINLAND_BBOX});
          node["amenity"="bus_station"]({MAINLAND_BBOX});
          way["amenity"="bus_station"]({MAINLAND_BBOX});
          node["highway"="bus_stop"]({MAINLAND_BBOX});
          node["amenity"="marketplace"]({MAINLAND_BBOX});
          way["amenity"="marketplace"]({MAINLAND_BBOX});
          node["shop"="marketplace"]({MAINLAND_BBOX});
          way["shop"="marketplace"]({MAINLAND_BBOX});
          node["shop"="supermarket"]({MAINLAND_BBOX});
          way["shop"="supermarket"]({MAINLAND_BBOX});
          node["amenity"="marketplace"]({SERIBU_BBOX});
          way["amenity"="marketplace"]({SERIBU_BBOX});
          node["amenity"="bus_station"]({SERIBU_BBOX});
          node["highway"="bus_stop"]({SERIBU_BBOX});
        );
        out center tags;
    """
}

def compute_area_m2(element: Dict[str, Any]) -> Optional[float]:
    """
    Computes polygon area in square meters using EPSG:32748.
    If full geometry coordinates are available in the element, projects and computes area.
    If only centroid/point is available (e.g. from Overpass 'out center tags;'), returns None.
    """
    tags = element.get("tags", {})
    if "area" in tags:
        try:
            return round(float(tags["area"]), 2)
        except ValueError:
            pass

    geom = element.get("geometry")
    if geom and isinstance(geom, list) and len(geom) >= 3:
        try:
            import shapely.geometry
            poly = shapely.geometry.Polygon([(pt["lon"], pt["lat"]) for pt in geom])
            if poly.is_valid and poly.area > 0:
                # Approximate scale factor for Jakarta (-6 deg S, UTM Zone 48S)
                # 1 deg lat ~ 110574m, 1 deg lon ~ 110700m
                return round(poly.area * (110700.0 * 110574.0), 2)
        except Exception:
            pass
    return None

def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates spherical distance between two coordinates in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

def normalize_name_for_dedup(name: Optional[str]) -> str:
    """Normalizes facility name for robust deduplication."""
    if not name:
        return ""
    s = re.sub(r"[^\w\s]", " ", name.lower())
    return " ".join(s.split())

def deduplicate_facilities(facilities: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Deduplicates facilities:
    When a node and a way (or two elements) have the same facility_type and a normalized name
    that matches (non-empty), within 150m, keep one (prefer the way centroid).
    Returns (deduped_facilities, removed_counts_per_type).
    """
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for f in facilities:
        by_type.setdefault(f["facility_type"], []).append(f)

    deduped: List[Dict[str, Any]] = []
    removed_counts: Dict[str, int] = {}

    for ft, items in by_type.items():
        name_groups: Dict[str, List[Dict[str, Any]]] = {}
        no_name: List[Dict[str, Any]] = []

        for it in items:
            nn = normalize_name_for_dedup(it.get("name"))
            if nn:
                name_groups.setdefault(nn, []).append(it)
            else:
                no_name.append(it)

        kept_for_type: List[Dict[str, Any]] = list(no_name)
        removed_for_type = 0

        for nn, group in name_groups.items():
            if len(group) == 1:
                kept_for_type.append(group[0])
                continue

            # Sort group: ways/relations first (prefer way centroid), then nodes
            # Within same type, prefer more metadata tags, then stable source_id
            def sort_key(x):
                osm_t = x.get("osm_type", "")
                type_prio = 0 if osm_t in ("way", "relation") else 1
                return (type_prio, -len(x.get("metadata", {}).get("raw_tags", {})), str(x.get("source_id")))

            sorted_group = sorted(group, key=sort_key)
            survivors: List[Dict[str, Any]] = []
            for candidate in sorted_group:
                c_coords = candidate["coordinates"]["coordinates"]
                c_lon, c_lat = c_coords[0], c_coords[1]
                is_dup = False
                for s in survivors:
                    s_coords = s["coordinates"]["coordinates"]
                    dist = haversine_meters(c_lat, c_lon, s_coords[1], s_coords[0])
                    if dist <= 150.0:
                        is_dup = True
                        break
                if is_dup:
                    removed_for_type += 1
                else:
                    survivors.append(candidate)
            kept_for_type.extend(survivors)

        if removed_for_type > 0:
            removed_counts[ft] = removed_for_type
        deduped.extend(kept_for_type)

    return deduped, removed_counts

class OSMExtractor:
    def __init__(self, raw_dir: Path = RAW_DIR, output_file: Path = NORMALIZED_FILE):
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.output_file = output_file
        self.active_endpoint = PRIMARY_ENDPOINT
        self.headers = {"User-Agent": USER_AGENT}

    def fetch_with_retry(self, group_name: str, query: str) -> Dict[str, Any]:
        """Fetches from primary endpoint with 3 retries, falling back if needed."""
        # Try primary endpoint first up to 3 attempts
        for attempt in range(1, 4):
            try:
                logger.info(f"[{group_name}] Querying Overpass primary: {self.active_endpoint} (Attempt {attempt}/3)...")
                resp = requests.post(self.active_endpoint, data={"data": query}, headers=self.headers, timeout=180)
                if resp.status_code == 200:
                    data = resp.json()
                    logger.info(f"[{group_name}] Success! Received {len(data.get('elements', []))} elements.")
                    return data
                elif resp.status_code in (429, 504):
                    wait = attempt * 8
                    logger.warning(f"[{group_name}] HTTP {resp.status_code}. Waiting {wait}s...")
                    time.sleep(wait)
                else:
                    logger.warning(f"[{group_name}] HTTP {resp.status_code}: {resp.text[:150]}")
                    time.sleep(5)
            except Exception as e:
                logger.warning(f"[{group_name}] Exception on {self.active_endpoint}: {e}")
                time.sleep(5)

        # Primary failed 3 times: switch to fallbacks
        logger.warning(f"[{group_name}] Primary endpoint failed 3 times. Attempting fallback mirrors...")
        for fb in FALLBACK_ENDPOINTS:
            logger.warning(f"SWITCHING Overpass endpoint to fallback mirror: {fb}")
            self.active_endpoint = fb
            for attempt in range(1, 4):
                try:
                    logger.info(f"[{group_name}] Fallback {fb} (Attempt {attempt}/3)...")
                    resp = requests.post(fb, data={"data": query}, headers=self.headers, timeout=180)
                    if resp.status_code == 200:
                        data = resp.json()
                        logger.info(f"[{group_name}] Fallback success! Received {len(data.get('elements', []))} elements.")
                        return data
                    elif resp.status_code in (429, 504):
                        time.sleep(attempt * 8)
                    else:
                        time.sleep(5)
                except Exception as e:
                    logger.warning(f"[{group_name}] Fallback exception: {e}")
                    time.sleep(5)

        raise RuntimeError(f"Overpass API is unreachable or returned persistent errors after 3 attempts on all endpoints for {group_name}.")

    def classify_element(self, element: Dict[str, Any], query_group: str) -> Dict[str, Any]:
        """Classifies element deterministically per OSM_TAG_MAPPING.md."""
        tags = element.get("tags", {})
        el_type = element.get("type", "node")
        el_id = element.get("id")
        source_id = f"{el_type}/{el_id}"

        # Coordinates: centroid for way, direct coords for node
        if el_type == "node":
            lat = element.get("lat")
            lon = element.get("lon")
        else:
            center = element.get("center", {})
            lat = center.get("lat")
            lon = center.get("lon")

        raw_name = tags.get("name")
        name_lower = (raw_name or "").lower().strip()

        pillar = "urban_livability"
        category = "general"
        facility_type = "unclassified"

        # Classification based on query group and tags
        if query_group == "group1_lifeline_health":
            pillar = "lifeline_health"
            amenity = tags.get("amenity", "")
            healthcare = tags.get("healthcare", "")

            if amenity == "fire_station":
                category = "emergency_fire"
                facility_type = "pos_damkar"
            elif amenity == "police":
                category = "security"
                # Removed per README §6.4: SNI only mentions pos kamtib & kantor polisi, amenity=police mixes both
                facility_type = "unclassified"
            elif "posyandu" in name_lower:
                category = "healthcare"
                facility_type = "posyandu"
            elif any(k in name_lower for k in ["puskesmas", "poskeskel", "pustu"]):
                category = "healthcare"
                if any(k in name_lower for k in ["kecamatan", "kec."]):
                    facility_type = "puskesmas_kecamatan"
                else:
                    facility_type = "puskesmas_kelurahan"
            elif amenity == "hospital" or healthcare == "hospital":
                category = "healthcare"
                # Exclude clinic, apotek, puskesmas, praktek, lab
                is_excluded_hospital = any(
                    re.search(pat, name_lower)
                    for pat in [r"klinik", r"clinic", r"apotek", r"puskesmas", r"praktek", r"\blab\b", r"laboratorium"]
                )
                if is_excluded_hospital:
                    if "puskesmas" in name_lower:
                        if any(k in name_lower for k in ["kecamatan", "kec."]):
                            facility_type = "puskesmas_kecamatan"
                        else:
                            facility_type = "puskesmas_kelurahan"
                    else:
                        facility_type = "unclassified"
                else:
                    facility_type = "rumah_sakit"
            elif amenity == "clinic" or healthcare in ["clinic", "centre"]:
                category = "healthcare"
                facility_type = "unclassified"
            else:
                facility_type = "unclassified"

        elif query_group == "group2_human_capital_education":
            pillar = "education"
            amenity = tags.get("amenity", "")

            if amenity == "library":
                category = "education"
                # Removed per README §6.4: only 5 records city-wide, SNI only mentions taman bacaan
                facility_type = "unclassified"
            elif amenity == "kindergarten":
                category = "education"
                facility_type = "taman_kanak_kanak"
            elif amenity == "school":
                category = "education"
                if any(k in name_lower for k in ["tk ", "tks ", "paud", "ra ", "taman kanak"]):
                    facility_type = "taman_kanak_kanak"
                elif any(k in name_lower for k in ["sd ", "sdn ", "sds ", "madrasah ibtidaiyah", "mi ", "min ", "primary"]):
                    facility_type = "sekolah_dasar"
                elif any(k in name_lower for k in ["smp ", "smpn", "smps", "madrasah tsanawiyah", "mts", "junior"]):
                    facility_type = "sekolah_menengah_pertama"
                elif any(k in name_lower for k in ["sma ", "sman", "smas", "smk ", "smkn", "smks", "madrasah aliyah", "man ", "senior", "kejuruan"]):
                    facility_type = "sekolah_menengah_atas"
                else:
                    facility_type = "unclassified"
            else:
                facility_type = "unclassified"

        elif query_group == "group3_urban_livability_recreation":
            pillar = "urban_livability"
            leisure = tags.get("leisure", "")
            amenity = tags.get("amenity", "")
            landuse = tags.get("landuse", "")

            if amenity in ["waste_disposal", "waste_transfer_station", "recycling"]:
                category = "waste_management"
                # Removed per README §6.4: not in SNI 03-1733-2004
                facility_type = "unclassified"
            elif "hutan kota" in name_lower or tags.get("urban_forest") in ["yes", "true"] or tags.get("forest") == "urban" or tags.get("leisure") == "nature_reserve" or tags.get("boundary") == "protected_area":
                category = "green_open_space"
                # Removed per README §6.4: not in SNI 03-1733-2004
                facility_type = "unclassified"
            elif landuse == "forest" or "hutan" in name_lower:
                category = "green_open_space"
                facility_type = "unclassified"
            elif leisure in ["sports_centre", "stadium", "pitch"]:
                category = "recreation"
                # Removed per README §6.4: not in SNI 03-1733-2004
                facility_type = "unclassified"
            elif "rptra" in name_lower or "ramah anak" in name_lower:
                category = "green_open_space"
                facility_type = "taman_rptra"
            elif leisure == "playground":
                category = "green_open_space"
                facility_type = "unclassified"
            elif leisure == "park":
                category = "green_open_space"
                if any(k in name_lower for k in ["taman kecamatan", "taman kec."]):
                    facility_type = "taman_kecamatan"
                elif "kelurahan" in name_lower:
                    facility_type = "taman_kelurahan"
                else:
                    facility_type = "taman_unspecified"
            else:
                facility_type = "unclassified"

        else: # group4_mobility_commercial
            pillar = "mobility_connectivity"
            railway = tags.get("railway", "")
            station = tags.get("station", "")
            amenity = tags.get("amenity", "")
            highway = tags.get("highway", "")
            shop = tags.get("shop", "")

            if railway in ["station", "subway_entrance"] or station in ["subway", "light_rail"]:
                category = "transit_mobility"
                facility_type = "stasiun_transit"
            elif highway == "bus_stop" or amenity == "bus_station":
                category = "transit_mobility"
                operator = (tags.get("operator") or "").lower()
                network = (tags.get("network") or "").lower()
                brand = (tags.get("brand") or "").lower()
                route = (tags.get("route") or "").lower()
                if any("transjakarta" in x or "trans jakarta" in x for x in [operator, network, brand, route]):
                    facility_type = "halte_transjakarta"
                else:
                    facility_type = "halte_unspecified"
            elif amenity == "marketplace" or shop == "marketplace":
                category = "commercial"
                facility_type = "pasar_tradisional"
            elif any(k in name_lower for k in ["sentra umkm", "lokbin", "lokasi binaan"]):
                category = "commercial"
                # Removed per README §6.4: no standard and 0 records OSM
                facility_type = "unclassified"
            else:
                category = "commercial"
                facility_type = "unclassified"

        capacity = 0
        if tags.get("capacity"):
            try:
                capacity = int(tags.get("capacity"))
            except ValueError:
                pass
        elif tags.get("beds"):
            try:
                capacity = int(tags.get("beds"))
            except ValueError:
                pass

        area_m2 = compute_area_m2(element)

        return {
            "source": "osm",
            "osm_type": el_type,
            "osm_id": el_id,
            "source_id": source_id,
            "name": raw_name,
            "facility_type": facility_type,
            "pillar": pillar,
            "category": category,
            "address": tags.get("addr:full") or tags.get("addr:street"),
            "contact": tags.get("phone") or tags.get("contact:phone"),
            "website": tags.get("website") or tags.get("contact:website"),
            "capacity": capacity,
            "area_m2": area_m2,
            "coordinates": {
                "type": "Point",
                "coordinates": [lon, lat]
            },
            "is_active": True,
            "is_verified": False,
            "snapshot_date": f"{SNAPSHOT_DATE[:4]}-{SNAPSHOT_DATE[4:6]}-{SNAPSHOT_DATE[6:]}",
            "metadata": {
                "raw_tags": tags,
                "osm_type": el_type,
                "area_m2": area_m2,
                "operator": tags.get("operator"),
                "opening_hours": tags.get("opening_hours"),
                "wheelchair": tags.get("wheelchair")
            },
            "last_synced_at": datetime.now(timezone.utc).isoformat()
        }

    def run_extraction(self) -> Dict[str, Any]:
        """Runs the complete extraction workflow with mandatory sleeps and raw persistence."""
        unique_facilities: Dict[str, Dict[str, Any]] = {}
        group_counts: Dict[str, int] = {}

        for idx, (group_name, query) in enumerate(TAG_GROUP_QUERIES.items()):
            if idx > 0:
                logger.info("Sleeping 6 seconds before next query per Overpass etiquette...")
                time.sleep(6)

            data = self.fetch_with_retry(group_name, query)

            # 1. Save raw response unchanged
            raw_path = self.raw_dir / f"raw_{group_name}.json"
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            logger.info(f"Saved raw response ({raw_path.stat().st_size:,} bytes) to {raw_path.name}")

            elements = data.get("elements", [])
            group_counts[group_name] = len(elements)

            for el in elements:
                coords = (el.get("lat") or (el.get("center", {}).get("lat")))
                if coords:
                    item = self.classify_element(el, group_name)
                    sid = item["source_id"]
                    # If duplicate across queries, prefer classified over unclassified
                    if sid in unique_facilities:
                        if unique_facilities[sid]["facility_type"] == "unclassified" and item["facility_type"] != "unclassified":
                            unique_facilities[sid] = item
                    else:
                        unique_facilities[sid] = item

        normalized_list = list(unique_facilities.values())
        deduped_list, removed_counts = deduplicate_facilities(normalized_list)
        logger.info(f"Deduplication complete. Removed {sum(removed_counts.values()):,} duplicates.")

        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(deduped_list, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved {len(deduped_list):,} normalized facilities to {self.output_file.name}")

        type_breakdown: Dict[str, int] = {}
        for f in deduped_list:
            ft = f["facility_type"]
            type_breakdown[ft] = type_breakdown.get(ft, 0) + 1

        summary = {
            "snapshot_date": SNAPSHOT_DATE,
            "raw_counts": group_counts,
            "total_before_dedup": len(normalized_list),
            "total_unique_facilities": len(deduped_list),
            "duplicates_removed_total": sum(removed_counts.values()),
            "duplicates_removed_by_type": removed_counts,
            "classified_count": sum(c for t, c in type_breakdown.items() if t not in ("unclassified", "taman_unspecified", "halte_unspecified")),
            "unclassified_count": type_breakdown.get("unclassified", 0),
            "taman_unspecified_count": type_breakdown.get("taman_unspecified", 0),
            "halte_unspecified_count": type_breakdown.get("halte_unspecified", 0),
            "type_breakdown": type_breakdown
        }
        logger.info(f"OSM Extraction completed successfully: {json.dumps(summary, indent=2)}")
        return summary

    def reclassify_from_raw(self, raw_dir: Optional[Path] = None) -> Dict[str, Any]:
        """
        Reclassifies facilities offline directly from the raw snapshot files
        ("Do NOT call Overpass again").
        Applies deduplication and saves normalized output.
        """
        target_raw_dir = raw_dir or self.raw_dir
        logger.info(f"Reclassifying from raw files in: {target_raw_dir}")

        unique_facilities: Dict[str, Dict[str, Any]] = {}
        group_counts: Dict[str, int] = {}

        for group_name in TAG_GROUP_QUERIES.keys():
            raw_path = target_raw_dir / f"raw_{group_name}.json"
            if not raw_path.exists():
                logger.warning(f"Raw file not found: {raw_path}")
                continue

            with open(raw_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            elements = data.get("elements", [])
            group_counts[group_name] = len(elements)
            logger.info(f"Processing {len(elements)} elements from {raw_path.name}...")

            for el in elements:
                coords = (el.get("lat") or (el.get("center", {}).get("lat")))
                if coords:
                    item = self.classify_element(el, group_name)
                    sid = item["source_id"]
                    if sid in unique_facilities:
                        # Prefer classified over unclassified/unspecified if duplicate across queries
                        prev_type = unique_facilities[sid]["facility_type"]
                        new_type = item["facility_type"]
                        if prev_type in ("unclassified", "taman_unspecified", "halte_unspecified") and new_type not in ("unclassified", "taman_unspecified", "halte_unspecified"):
                            unique_facilities[sid] = item
                    else:
                        unique_facilities[sid] = item

        classified_list = list(unique_facilities.values())
        logger.info(f"Total elements before deduplication: {len(classified_list):,}")

        # Deduplicate (matching normalized name within 150m, prefer way centroid)
        deduped_list, removed_counts = deduplicate_facilities(classified_list)
        logger.info(f"Deduplication complete. Removed {sum(removed_counts.values()):,} duplicates across {len(removed_counts)} types.")
        for ft, cnt in sorted(removed_counts.items()):
            logger.info(f"  - {ft}: {cnt} removed")

        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(deduped_list, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved {len(deduped_list):,} normalized facilities to {self.output_file.name}")

        type_breakdown: Dict[str, int] = {}
        for f in deduped_list:
            ft = f["facility_type"]
            type_breakdown[ft] = type_breakdown.get(ft, 0) + 1

        summary = {
            "snapshot_date": SNAPSHOT_DATE,
            "raw_counts": group_counts,
            "total_before_dedup": len(classified_list),
            "total_unique_facilities": len(deduped_list),
            "duplicates_removed_total": sum(removed_counts.values()),
            "duplicates_removed_by_type": removed_counts,
            "classified_count": sum(c for t, c in type_breakdown.items() if t not in ("unclassified", "taman_unspecified", "halte_unspecified")),
            "unclassified_count": type_breakdown.get("unclassified", 0),
            "taman_unspecified_count": type_breakdown.get("taman_unspecified", 0),
            "halte_unspecified_count": type_breakdown.get("halte_unspecified", 0),
            "type_breakdown": type_breakdown
        }
        logger.info(f"OSM Reclassification completed: {json.dumps(summary, indent=2)}")
        return summary

if __name__ == "__main__":
    import sys
    extractor = OSMExtractor()
    if "--live-fetch" in sys.argv:
        extractor.run_extraction()
    else:
        extractor.reclassify_from_raw()
