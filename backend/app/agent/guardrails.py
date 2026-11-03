"""
AI Guardrails & Citation Validator for Cognitive Spatial Agent.
Enforces README.md §2, §11:
1. Numeric Guardrail: Disallows fabricated/hallucinated numbers; every number in the LLM answer
   must originate from PostGIS/SimEngine tool outputs of the current turn.
2. Citation Validator: Validates [REG:<chunk_id>] citations against chunks returned in this turn,
   removes unknown [REG:...] tags and unbacked free-text legal citations.
3. Incident Logging: Logs numeric violations into `incident_logs` ledger.
4. Deterministic Fallback: Generates deterministic summary from tool outputs when retry fails.
"""

import re
import math
import json
import logging
from decimal import Decimal
from typing import Dict, Any, List, Set, Tuple, Optional

from backend.app.core.db import get_db_cursor

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# 1. Numeric Guardrail
# -----------------------------------------------------------------------------

def parse_number_candidates(token: str) -> List[float]:
    """
    Parses a string number token into candidate float values, accommodating
    both Indonesian (comma decimal, period thousand) and English conventions,
    percentages, and negative signs.
    """
    cleaned = token.rstrip("%").strip()
    if not cleaned:
        return []

    candidates: List[float] = []

    # 1. Direct standard float parse
    try:
        candidates.append(float(cleaned))
    except ValueError:
        pass

    # 2. Comma as decimal: "40,71" -> 40.71, "-3,4" -> -3.4
    if "," in cleaned and "." not in cleaned:
        try:
            candidates.append(float(cleaned.replace(",", ".")))
        except ValueError:
            pass
        # Comma as thousands: "228,450" -> 228450
        try:
            candidates.append(float(cleaned.replace(",", "")))
        except ValueError:
            pass

    # 3. Period as thousands: "228.450" -> 228450
    if "." in cleaned and "," not in cleaned:
        try:
            candidates.append(float(cleaned.replace(".", "")))
        except ValueError:
            pass

    # 4. Mixed punctuation: "1.234,56" or "1,234.56"
    if "." in cleaned and "," in cleaned:
        if cleaned.rfind(".") < cleaned.rfind(","):
            # Indonesian/German style: 1.234,56
            try:
                candidates.append(float(cleaned.replace(".", "").replace(",", ".")))
            except ValueError:
                pass
        else:
            # English style: 1,234.56
            try:
                candidates.append(float(cleaned.replace(",", "")))
            except ValueError:
                pass

    return candidates


# Documented allow-list of constants that the system itself displays (README.md §2, §11)
SYSTEM_ALLOW_LIST_CONSTANTS: Set[float] = {
    # 1. Base pillar weights in 4-pillar index (30%, 25%, 20% or 0.30, 0.25, 0.20)
    30.0, 0.30,
    25.0, 0.25,
    20.0, 0.20,
    # 2. Total regulatory standards catalog count in database / standards metadata (§6: 16 total, 7 scored, 9 informational)
    16.0,
    7.0,
    9.0,
    22.0,
    # 3. Minimum types threshold for composite inclusion (types_scored >= 2)
    2.0,
    # 4. Standard 4 pillars of urban spatial framework
    4.0,
    # 5. Planning obligation assumptions exposed in responses (20% RTH, 50% KDB, 150 mm/day stormwater depth)
    50.0, 0.50,
    150.0,
    # 6. Standard 15-minute city radius concept proxy
    15.0,
}


def is_list_marker(text: str, start_pos: int, end_pos: int) -> bool:
    """
    Determines if a small integer is functioning as structural list numbering or category enumeration.
    
    EXACT RULE:
    Small integers 1-10 used as list numbering or counts of items in the answer are allowed only if
    they also appear in tool output OR are list markers / enumerations.
    
    Structural contexts recognized as list markers / section labels:
    - Ordered list items at line boundaries: "1. ", "2) ", "- 1. ", "* 1. "
    - Markdown section headers: "### 1. ", "## 2. "
    - Parenthesized item markers: "(1)", "(2)", "(3)"
    - Pillar category labels: "Pilar 1", "Pilar 2", "Pilar 3", "Pilar 4", "4 Pilar"
    - Standard spatial radius proxies: "15 menit" / "15-minute" (urban concept proxy)
    - Fraction / category enumeration: "1 dari 7", "4 dari 4"
    - Category count labels: "1 jenis", "7 jenis", "3 pilar"
    """
    prefix = text[max(0, start_pos - 20):start_pos]
    suffix = text[end_pos:min(len(text), end_pos + 20)]

    # 1. Line start / list item bullet
    if re.search(r"(?:^|\n)\s*(?:[-*]\s+)?(?:#{1,6}\s+)?$", prefix) and re.match(r"^[.)]\s+", suffix):
        return True

    # 2. Parenthesized item: (1), (2), (3)
    if prefix.rstrip().endswith("(") and suffix.lstrip().startswith(")"):
        return True

    # 3. "Pilar 1", "Pilar 2", "4 Pilar", "15-minute"
    if re.search(r"(?:pilar|pilar-)\s*$", prefix, re.IGNORECASE) or re.match(r"^\s*pilar", suffix, re.IGNORECASE):
        return True
    if re.search(r"\b15\s*$", prefix, re.IGNORECASE) and re.match(r"^-(?:menit|minute)", suffix, re.IGNORECASE):
        return True

    # 4. Fraction / category enumeration: e.g. "1 dari 7", "4 dari 4"
    if re.search(r"\bdari\s+\d+\b", suffix, re.IGNORECASE) or re.search(r"\b\d+\s+dari\s*$", prefix, re.IGNORECASE):
        return True

    # 5. Category counts: e.g. "1 jenis", "7 jenis", "3 pilar", "2 fasilitas"
    if re.match(r"^\s*(?:jenis|fasilitas|pilar)\b", suffix, re.IGNORECASE):
        return True

    return False


def build_allowed_numbers(tool_outputs: List[Dict[str, Any]]) -> Set[float]:
    """
    Recursively extracts all valid numeric values from tool outputs of the current turn,
    augmented with the documented SYSTEM_ALLOW_LIST_CONSTANTS.
    Permits signs, absolute values, percentages of ratio floats, and common rounding tolerances.
    """
    allowed: Set[float] = set(SYSTEM_ALLOW_LIST_CONSTANTS)

    def walk(obj: Any):
        if isinstance(obj, (int, float, Decimal)) and not isinstance(obj, bool):
            val = float(obj)
            allowed.add(round(val, 4))
            allowed.add(round(abs(val), 4))
            # Also allow rounded integer if decimal is integer-like
            if val.is_integer():
                allowed.add(float(int(val)))
            # If float is a ratio 0.0 < val <= 1.0 (e.g. data_coverage: 0.1429, 0.75, 0.8),
            # allow its percentage equivalents (14.29, 14.3, 14.0, 75.0, 80.0)
            if 0.0 < abs(val) <= 1.0:
                pct_val = abs(val) * 100.0
                allowed.add(round(pct_val, 2))
                allowed.add(round(pct_val, 1))
                allowed.add(float(round(pct_val)))
        elif isinstance(obj, str):
            # Parse numbers embedded in tool text strings (e.g. "92.08%", "3.5 km", "-1 unit")
            for m in re.finditer(r"-?\b\d+(?:[.,]\d+)*(?:%)?", obj):
                for cand in parse_number_candidates(m.group(0)):
                    allowed.add(round(cand, 4))
                    allowed.add(round(abs(cand), 4))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for it in obj:
                walk(it)

    for out in tool_outputs:
        walk(out)

    return allowed


def is_number_matched(candidate: float, allowed_numbers: Set[float], tolerance: float = 0.05) -> bool:
    """Checks whether a candidate number matches any allowed number within rounding tolerance."""
    # Check exact match
    if candidate in allowed_numbers or abs(candidate) in allowed_numbers:
        return True

    # Check approximate rounding (e.g., 40.71 vs 40.7, or 92.08 vs 92.1)
    for allowed in allowed_numbers:
        if math.isclose(candidate, allowed, abs_tol=tolerance):
            return True
        if math.isclose(abs(candidate), allowed, abs_tol=tolerance):
            return True

    return False


def validate_numeric_claims(text: str, allowed_numbers: Set[float]) -> Tuple[bool, List[str]]:
    """
    Extracts every number from text and verifies that each is either a structural list marker
    or backed by tool outputs.
    Returns (is_passed, unsupported_numbers).
    """
    unsupported: List[str] = []
    
    # Regex matches numbers including decimals, thousands, negatives, percentages
    pattern = r"-?\b\d+(?:[.,]\d+)*(?:%)?"

    for match in re.finditer(pattern, text):
        raw_token = match.group(0).strip()
        start_pos = match.start()
        end_pos = match.end()

        # Check if list marker (small integers 1-10)
        candidates = parse_number_candidates(raw_token)
        if not candidates:
            continue

        primary_val = candidates[0]

        # Check small integer list marker rule
        if 1.0 <= abs(primary_val) <= 10.0 and is_list_marker(text, start_pos, end_pos):
            continue

        # Check against allowed numbers
        matched = any(is_number_matched(c, allowed_numbers) for c in candidates)
        if not matched:
            if raw_token not in unsupported:
                unsupported.append(raw_token)

    return (len(unsupported) == 0, unsupported)


def extract_ground_truth_bindings(tool_outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extracts ground truth numbers and labels from tool outputs for semantic binding check."""
    bindings: Dict[str, Any] = {
        "composite_score": None,
        "composite_scores": set(),
        "pillar_scores": {},      # pillar_key -> set of valid numbers (baseline, simulated, delta)
        "facility_metrics": {}    # facility_type -> dict(deficits=set(), required=set(), existing=set())
    }

    for out in tool_outputs:
        if not isinstance(out, dict):
            continue

        dicts_to_process = [out]
        if isinstance(out.get("simulation_delta"), dict):
            dicts_to_process.append(out["simulation_delta"])

        for d in dicts_to_process:
            # Extract composite score & score deltas
            for k in ("composite_score", "composite_livability_score", "simulated_composite_score",
                      "baseline_composite_score", "overall_compliance_score", "score_delta", "abs_score_delta"):
                if k in d and d[k] is not None:
                    try:
                        c_val = float(d[k])
                        bindings["composite_scores"].add(c_val)
                        bindings["composite_scores"].add(abs(c_val))
                        if k in ("composite_score", "simulated_composite_score"):
                            bindings["composite_score"] = c_val
                    except (ValueError, TypeError):
                        pass

            # Extract pillar scores & deltas
            pillars = d.get("pillar_scores") or d.get("baseline_pillar_scores") or d.get("simulated_pillar_scores")
            if isinstance(pillars, dict):
                for p_key, p_val in pillars.items():
                    val = None
                    if isinstance(p_val, dict) and "score" in p_val and p_val["score"] is not None:
                        val = p_val["score"]
                    elif isinstance(p_val, (int, float)):
                        val = p_val
                    if val is not None:
                        try:
                            bindings["pillar_scores"].setdefault(p_key, set()).add(float(val))
                        except (ValueError, TypeError):
                            pass

            p_deltas = d.get("pillar_deltas")
            if isinstance(p_deltas, dict):
                for p_key, p_info in p_deltas.items():
                    if isinstance(p_info, dict):
                        for num_k in ("baseline_score", "simulated_score", "delta", "abs_delta"):
                            if num_k in p_info and p_info[num_k] is not None:
                                try:
                                    bindings["pillar_scores"].setdefault(p_key, set()).add(float(p_info[num_k]))
                                except (ValueError, TypeError):
                                    pass

            # Extract facility metrics
            metrics = d.get("metrics_payload") or d.get("metrics_comparison") or d.get("metrics")
            if isinstance(metrics, list):
                for m in metrics:
                    if isinstance(m, dict):
                        ft = m.get("facility_type")
                        if ft:
                            if ft not in bindings["facility_metrics"]:
                                bindings["facility_metrics"][ft] = {
                                    "existing": set(),
                                    "required": set(),
                                    "deficits": set(),
                                    "deficit": 0.0,
                                    "required_val": 0.0,
                                    "existing_val": 0.0,
                                }
                            entry = bindings["facility_metrics"][ft]
                            for k in ("existing", "baseline_existing", "simulated_existing"):
                                if k in m and m[k] is not None:
                                    try:
                                        entry["existing"].add(float(m[k]))
                                        entry["existing_val"] = float(m[k])
                                    except (ValueError, TypeError): pass
                            for k in ("required", "baseline_required", "simulated_required", "required_delta"):
                                if k in m and m[k] is not None:
                                    try:
                                        entry["required"].add(float(m[k]))
                                        entry["required_val"] = float(m[k])
                                    except (ValueError, TypeError): pass
                            for k in ("deficit", "baseline_deficit", "simulated_deficit", "new_deficit_units", "deficit_delta"):
                                if k in m and m[k] is not None:
                                    try:
                                        flt_v = float(m[k])
                                        entry["deficits"].add(flt_v)
                                        entry["deficits"].add(abs(flt_v))
                                        entry["deficit"] = abs(flt_v)
                                    except (ValueError, TypeError): pass

    return bindings


def validate_label_bindings(
    text: str,
    tool_outputs: List[Dict[str, Any]],
    tolerance: float = 0.05
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Validates semantic binding of numbers to labels:
    1. A sentence mentioning composite/livability score must contain composite_score (within rounding).
    2. A sentence/clause naming a pillar next to 'skor' must use that pillar's score.
    3. A sentence naming a facility_type next to 'defisit'/'kebutuhan'/'tersedia' must use that type's value.
    Returns (is_passed, mislabeled_numbers).
    """
    bindings = extract_ground_truth_bindings(tool_outputs)
    comp_val = bindings["composite_score"]
    comp_scores = bindings.get("composite_scores", set())
    if comp_val is not None:
        comp_scores.add(comp_val)
    elif comp_scores:
        comp_val = next(iter(comp_scores))
    pillar_scores = bindings["pillar_scores"]
    facility_metrics = bindings["facility_metrics"]

    mislabeled_numbers: List[Dict[str, Any]] = []

    if not comp_scores and not pillar_scores and not facility_metrics:
        return (True, [])

    # Clean administrative codes (e.g. "kode 31.71.09" or "(kode 31.71.09)" or "BPS 317109")
    # so administrative district numbers are not misconstrued as metric scores or facility quantities
    cleaned_text = re.sub(r"\(?\b(?:kode|kemendagri|bps)\s*[:]?\s*[\d.]+\)?", "", text, flags=re.IGNORECASE)

    raw_sentences = re.split(r"(?<=[.!?\n])\s+", cleaned_text)
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    num_pattern = r"-?\b\d+(?:[.,]\d+)*(?:%)?"

    comp_keywords = ["skor kelayakan", "skor komposit", "livability score", "skor keseluruhan", "composite score"]

    pillar_regexes = {
        "lifeline_health": r"(?:skor\s+(?:pilar\s+)?(?:layanan\s+)?(?:sektor\s+)?kesehatan(?:\s+dan\s+keselamatan)?|kesehatan(?:\s+dan\s+keselamatan)?\s*(?:\([^)]*\))?\s*(?:memiliki|sebesar|tercatat|mencapai)?\s*skor)",
        "education": r"(?:skor\s+(?:pilar\s+)?(?:layanan\s+)?(?:sektor\s+)?pendidikan|pendidikan\s*(?:\([^)]*\))?\s*(?:memiliki|sebesar|tercatat|mencapai)?\s*skor)",
        "urban_livability": r"(?:skor\s+(?:pilar\s+)?(?:layanan\s+)?(?:sektor\s+)?(?:ruang\s+hidup|lingkungan\s+hidup|rekreasi)|(?:ruang\s+hidup|lingkungan\s+hidup|rekreasi)\s*(?:\([^)]*\))?\s*(?:memiliki|sebesar|tercatat|mencapai)?\s*skor)",
        "mobility_connectivity": r"(?:skor\s+(?:pilar\s+)?(?:layanan\s+)?(?:sektor\s+)?mobilitas(?:\s+dan\s+aksesibilitas)?|mobilitas(?:\s+dan\s+aksesibilitas)?\s*(?:\([^)]*\))?\s*(?:memiliki|sebesar|tercatat|mencapai)?\s*skor)"
    }

    fac_keywords = {
        "puskesmas_kelurahan": [r"puskesmas\s+kelurahan", r"puskesmas\s+kel\b", r"poskeskel", r"pustu"],
        "puskesmas_kecamatan": [r"puskesmas\s+kecamatan", r"puskesmas\s+kec\b"],
        "rumah_sakit": [r"rumah\s+sakit", r"\brs\b", r"hospital"],
        "pos_damkar": [r"pos\s+damkar", r"pemadam\s+kebakaran", r"\bdamkar\b", r"fire\s+station"],
        "posyandu": [r"posyandu"],
        "sekolah_dasar": [r"sekolah\s+dasar", r"\bsd\b", r"\bsdn\b", r"madrasah\s+ibtidaiyah"],
        "sekolah_menengah_pertama": [r"sekolah\s+menengah\s+pertama", r"\bsmp\b", r"\bsmpn\b", r"madrasah\s+tsanawiyah"],
        "sekolah_menengah_atas": [r"sekolah\s+menengah\s+atas", r"\bsma\b", r"\bsman\b", r"\bsmk\b", r"madrasah\s+aliyah"],
        "taman_kanak_kanak": [r"taman\s+kanak", r"\btk\b", r"\bpaud\b"],
        "taman_rptra": [r"rptra"],
        "taman_kelurahan": [r"taman\s+kelurahan"],
        "taman_kecamatan": [r"taman\s+kecamatan"],
        "stasiun_transit": [r"stasiun", r"\bmrt\b", r"\blrt\b", r"\bkrl\b"],
        "halte_transjakarta": [r"halte\s+transjakarta", r"halte\s+tj", r"halte"],
        "pasar_tradisional": [r"pasar\s+tradisional", r"pasar\s+jaya", r"\bpasar\b"],
    }

    for sent in sentences:
        sent_lower = sent.lower()

        sent_tokens = []
        for m in re.finditer(num_pattern, sent):
            raw = m.group(0).strip()
            cands = parse_number_candidates(raw)
            if cands:
                sent_tokens.append((raw, cands[0], m.start(), m.end()))

        if not sent_tokens:
            continue

        # Rule 1: Composite score mention & assertion
        # Check if sentence is explaining an exclusion from composite (e.g. "pilar 3 tidak termasuk dalam skor komposit")
        # or explaining the simulation impact classification rule/threshold (e.g. "delta komposit <= -5.0")
        exclusion_pattern = r"(?:tidak\s+termasuk|belum\s+termasuk|dikecualikan|tanpa\s+memperhitungkan|tidak\s+dihitung|di\s+luar)\s+(?:ke\s+dalam\s+|dalam\s+|pada\s+)?(?:skor\s+)?komposit"
        rule_threshold_pattern = r"(?:aturan|kriteria|ambang|threshold|jika\s+(?:penurunan\s+)?(?:skor|delta)|delta\s*(?:<=|>=|<|>))"
        is_exclusion = bool(re.search(exclusion_pattern, sent_lower) or re.search(rule_threshold_pattern, sent_lower))

        if not is_exclusion and comp_scores:
            # Check explicit composite score assertion with linking predicate
            comp_match = re.search(
                r"(?:indeks\s+kecukupan(?:\s+fasilitas(?:\s+dasar)?)?|skor\s+kelayakan(?:\s+hidup)?|skor\s+komposit|livability\s+score|skor\s+keseluruhan)[^0-9\n]{0,60}?(?:adalah|sebesar|mencapai|tercatat|tetap|yakni|yaitu|:|=)\s*(?:[*_]*\s*)?(-?\d+(?:[.,]\d+)*(?:%)?)",
                sent,
                re.IGNORECASE
            )
            if not comp_match:
                # Reverse syntax: "40.71 adalah indeks kecukupan fasilitas"
                comp_match = re.search(
                    r"(-?\d+(?:[.,]\d+)*(?:%)?)\s*(?:merupakan|adalah|sebagai)?\s*(?:indeks\s+kecukupan(?:\s+fasilitas(?:\s+dasar)?)?|skor\s+kelayakan(?:\s+hidup)?|skor\s+komposit|livability\s+score)",
                    sent,
                    re.IGNORECASE
                )
            if comp_match:
                raw_comp = comp_match.group(1).strip()
                # Check if number is directly preceded by a pillar keyword (e.g. "Pilar Kesehatan: 56.71")
                match_span = comp_match.span(1)
                pre_number = sent[max(0, match_span[0] - 25):match_span[0]].lower()
                is_pillar_preceded = any(pw in pre_number for pw in ["pilar", "kesehatan", "pendidikan", "mobilitas", "ruang hidup"])

                if not is_pillar_preceded:
                    cands = parse_number_candidates(raw_comp)
                    if cands and not any(math.isclose(cands[0], cs, abs_tol=tolerance) for cs in comp_scores):
                        val = cands[0]
                        found_label = "unknown_metric"
                        for p_key, p_scores in pillar_scores.items():
                            p_set = p_scores if isinstance(p_scores, (set, list, tuple)) else {p_scores}
                            if any(math.isclose(val, ps, abs_tol=tolerance) for ps in p_set):
                                found_label = f"pillar_score:{p_key}"
                                break
                        mislabeled_numbers.append({
                            "number": raw_comp,
                            "expected_label": f"composite_score ({comp_val})",
                            "found_label": found_label
                        })

        # Rule 2: Pillar score mention next to "skor"
        for p_key, p_regex in pillar_regexes.items():
            exp_scores = pillar_scores.get(p_key)
            if not exp_scores:
                continue

            p_match = re.search(
                rf"{p_regex}[^0-9\n]{{0,50}}?(-?\d+(?:[.,]\d+)*(?:%)?)",
                sent,
                re.IGNORECASE
            )
            if p_match:
                raw_p_num = p_match.group(1).strip()
                cands = parse_number_candidates(raw_p_num)
                score_set = exp_scores if isinstance(exp_scores, set) else {exp_scores}
                if cands and not any(math.isclose(cands[0], s, abs_tol=tolerance) for s in score_set):
                    val = cands[0]
                    found_lbl = "unknown_metric"
                    if any(math.isclose(val, cs, abs_tol=tolerance) for cs in comp_scores):
                        found_lbl = "composite_score"
                    else:
                        for other_p, o_scores in pillar_scores.items():
                            o_set = o_scores if isinstance(o_scores, set) else {o_scores}
                            if any(math.isclose(val, os, abs_tol=tolerance) for os in o_set):
                                found_lbl = f"pillar_score:{other_p}"
                                break
                    mislabeled_numbers.append({
                        "number": raw_p_num,
                        "expected_label": f"pillar_score:{p_key}",
                        "found_label": found_lbl
                    })

        # Rule 3: Facility type metrics (defisit, kebutuhan, tersedia)
        clauses = re.split(r"[,;\n]|(?:\s+(?:namun|tetapi|sedangkan)\s+)", sent)
        for clause in clauses:
            cl_lower = clause.lower().strip()
            if not cl_lower:
                continue

            cl_tokens = []
            for m in re.finditer(num_pattern, clause):
                raw = m.group(0).strip()
                cands = parse_number_candidates(raw)
                if cands:
                    cl_tokens.append((raw, cands[0], m.start(), m.end()))

            if not cl_tokens:
                continue

            # Identify all facility keyword occurrences within this clause
            fac_spans = []
            for ftype, patterns in fac_keywords.items():
                for pat in patterns:
                    for f_m in re.finditer(pat, cl_lower):
                        fac_spans.append((ftype, f_m.start(), f_m.end()))

            if not fac_spans:
                continue

            for raw, val, s_pos, e_pos in cl_tokens:
                if 1.0 <= abs(val) <= 10.0 and is_list_marker(clause, s_pos, e_pos):
                    continue

                # Ignore numbers in legal references: e.g. "Bagian 7.2", "Pasal 64", "Tahun 2022", "No. 31/2022", "Tabel 3"
                pre_token = clause[max(0, s_pos - 15):s_pos].lower()
                if any(w in pre_token for w in ["bab", "pasal", "tabel", "ayat", "no.", "no ", "nomor", "sni", "tahun", "perda", "pergub", "uu "]):
                    continue

                # Ignore numbers specifying physical site dimensions or areas: e.g. "15000 m2", "150 mm", "3.5 km"
                post_token = clause[e_pos:min(len(clause), e_pos + 10)].lower()
                if any(w in post_token for w in ["m²", "m2", "m³", "m3", "meter", "km", "%", "mm"]):
                    continue

                # Bind to the closest facility keyword in the clause (prefer preceding)
                preceding = [f for f in fac_spans if f[2] <= s_pos]
                if preceding:
                    closest_ftype = max(preceding, key=lambda f: f[2])[0]
                else:
                    closest_ftype = min(fac_spans, key=lambda f: abs(f[1] - e_pos))[0]

                fm = facility_metrics.get(closest_ftype)
                if not fm:
                    continue

                # Check "defisit"
                if "defisit" in cl_lower:
                    exp_defs = fm.get("deficits", {abs(float(fm.get("deficit", 0)))})
                    exp_def = abs(float(fm.get("deficit", 0)))
                    if not any(math.isclose(abs(val), ed, abs_tol=tolerance) for ed in exp_defs):
                        found_f = "other_facility_metric"
                        for other_ft, ofm in facility_metrics.items():
                            o_defs = ofm.get("deficits", {abs(float(ofm.get("deficit", 0)))})
                            if any(math.isclose(abs(val), od, abs_tol=tolerance) for od in o_defs):
                                found_f = f"deficit:{other_ft}"
                                break
                        mislabeled_numbers.append({
                            "number": raw,
                            "expected_label": f"defisit:{closest_ftype} ({exp_def})",
                            "found_label": found_f
                        })

                # Check "kebutuhan" or "standar"
                elif ("kebutuhan" in cl_lower or "standar" in cl_lower) and "defisit" not in cl_lower:
                    if "radius" in cl_lower or "meter" in cl_lower or "km" in cl_lower:
                        continue
                    exp_reqs = fm.get("required", {float(fm.get("required_val", 0))})
                    exp_req = float(fm.get("required_val", 0))
                    if not any(math.isclose(val, er, abs_tol=tolerance) for er in exp_reqs):
                        found_f = "other_facility_metric"
                        for other_ft, ofm in facility_metrics.items():
                            o_reqs = ofm.get("required", {float(ofm.get("required_val", 0))})
                            if any(math.isclose(val, oreq, abs_tol=tolerance) for oreq in o_reqs):
                                found_f = f"required:{other_ft}"
                                break
                        mislabeled_numbers.append({
                            "number": raw,
                            "expected_label": f"kebutuhan:{closest_ftype} ({exp_req})",
                            "found_label": found_f
                        })

                # Check "tersedia" or "eksisting"
                elif ("tersedia" in cl_lower or "eksisting" in cl_lower) and "defisit" not in cl_lower and "kebutuhan" not in cl_lower:
                    if "radius" in cl_lower or "meter" in cl_lower or "km" in cl_lower:
                        continue
                    exp_exists = fm.get("existing", {float(fm.get("existing_val", 0))})
                    exp_exist = float(fm.get("existing_val", 0))
                    if not any(math.isclose(val, ee, abs_tol=tolerance) for ee in exp_exists):
                        found_f = "other_facility_metric"
                        for other_ft, ofm in facility_metrics.items():
                            o_exists = ofm.get("existing", {float(ofm.get("existing_val", 0))})
                            if any(math.isclose(val, oex, abs_tol=tolerance) for oex in o_exists):
                                found_f = f"existing:{other_ft}"
                                break
                        mislabeled_numbers.append({
                            "number": raw,
                            "expected_label": f"tersedia:{closest_ftype} ({exp_exist})",
                            "found_label": found_f
                        })

    # Deduplicate entries
    unique_mislabeled: List[Dict[str, Any]] = []
    seen = set()
    for item in mislabeled_numbers:
        key = (item["number"], item["expected_label"], item["found_label"])
        if key not in seen:
            seen.add(key)
            unique_mislabeled.append(item)

    return (len(unique_mislabeled) == 0, unique_mislabeled)


# -----------------------------------------------------------------------------
# 2. Citation Validator
# -----------------------------------------------------------------------------

def validate_and_sanitize_citations(
    text: str,
    returned_citations: List[Dict[str, Any]]
) -> Tuple[str, List[str], List[str]]:
    """
    Validates legal citations:
    1. Removes any [REG:<chunk_id>] whose ID was not returned this turn.
    2. Removes free-text citations (e.g. 'Permenkes No. 43/2019 Pasal 16') that are not backed by a returned chunk.
    3. Renders valid IDs into formatted citations (document_title, chapter, article).
    Returns (cleaned_text, valid_chunk_ids, removed_citations).
    """
    valid_citations: List[str] = []
    removed_citations: List[str] = []

    # Build lookup of allowed chunks returned this turn
    allowed_chunks: Dict[str, Dict[str, Any]] = {}
    for c in returned_citations:
        cid = str(c.get("chunk_id") or c.get("id") or "")
        if cid:
            allowed_chunks[cid] = c

    # Step 1: Process [REG:<chunk_id>] tags first using placeholders
    # Valid tags are replaced with __VALID_CIT_{idx}__ so free-text regex won't touch them.
    # Invalid tags are removed immediately and logged in removed_citations.
    cit_replacements: Dict[str, str] = {}
    placeholder_idx = 0

    def process_reg_tag(m: re.Match) -> str:
        nonlocal placeholder_idx
        cid = m.group(1).strip()
        if cid in allowed_chunks:
            if cid not in valid_citations:
                valid_citations.append(cid)
            chunk = allowed_chunks[cid]
            doc = chunk.get("regulation_code") or chunk.get("document_title") or "Regulasi"
            art = chunk.get("article_number") or chunk.get("chapter") or ""
            citation_label = f"**[{doc}: {art}]**" if art else f"**[{doc}]**"
            ph = f"__VALID_CIT_{placeholder_idx}__"
            placeholder_idx += 1
            cit_replacements[ph] = citation_label
            return ph
        else:
            if cid:
                removed_citations.append(f"[REG:{cid}]")
            else:
                removed_citations.append("[REG:]")
            return ""

    # Match optional bold asterisks around [REG:...]: \*{0,2}\[REG:([^\]]*)\]\*{0,2}
    cleaned_text = re.sub(r"\*{0,2}\[REG:([^\]]*)\]\*{0,2}", process_reg_tag, text)

    # Step 2: Detect and remove unbacked free-text citations (including optional surrounding bold)
    legal_pattern = (
        r"(?:(?:Menurut|Berdasarkan|Sesuai(?:\s+dengan)?|Merujuk\s+pada)\s+)?"
        r"\*{0,2}\b(?:Permenkes|Permendagri|Permendikbud|Perda(?:\s+DKI(?:\s+Jakarta)?)?|Pergub(?:\s+DKI(?:\s+Jakarta)?)?|UU|Undang-Undang|PP|SNI)\b"
        r"(?:\s+(?:No\.?|Nomor)?\s*[\w\d\/\.\-]+)*(?:\s+Tahun\s+\d{4})?"
        r"(?:\s+(?:Pasal|Bab|Tabel|Ayat)\s*[\w\d\.\-]+(?:\s*ayat\s*\([\d\w]+\))?)*\*{0,2}"
    )

    def check_free_text(m: re.Match) -> str:
        raw_match = m.group(0).strip()
        if not raw_match:
            return ""

        # Check if backed by any returned chunk
        is_backed = False
        match_lower = raw_match.lower()
        for chunk in allowed_chunks.values():
            reg_code = (chunk.get("regulation_code") or "").lower()
            if reg_code and reg_code in match_lower:
                art = (chunk.get("article_number") or "").lower()
                if not art or art in match_lower:
                    is_backed = True
                    break

        if not is_backed:
            removed_citations.append(raw_match.strip("* "))
            return ""
        return raw_match

    cleaned_text = re.sub(legal_pattern, check_free_text, cleaned_text, flags=re.IGNORECASE)

    # Clean empty bold spans: **** or ** ** or ** - ** BEFORE restoring valid citations
    cleaned_text = re.sub(r"\*{2,}\s*[-–—:]?\s*\*{2,}", "", cleaned_text)

    # Clean orphaned dashes or colons after list markers: e.g. "1. - Rencana..." -> "1. Rencana..."
    cleaned_text = re.sub(r"(?m)^(\s*(?:\d+[.)]|[-*]))\s*[-–—:]\s*", r"\1 ", cleaned_text)

    # Clean empty list items / blank bullets: e.g. "1. \n" or "- \n" or line with only number/bullet
    cleaned_text = re.sub(r"(?m)^\s*(?:\d+[.)]|[-*])\s*[-–—:]?\s*$", "", cleaned_text)

    # Step 3: Restore valid formatted citation labels
    for ph, label in cit_replacements.items():
        cleaned_text = cleaned_text.replace(ph, label)

    # Clean double spaces or orphaned punctuation
    cleaned_text = re.sub(r"(?:,\s*)?(?:Anda\s+dapat\s+)?(?:merujuk|berdasarkan|sesuai)\s+(?:ke|pada)?\s*(?:dan\s*)*\.", ".", cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r"\b(?:Menurut|Berdasarkan|Sesuai(?:\s+dengan)?|Merujuk\s+pada)\s*,\s*", "", cleaned_text)
    cleaned_text = re.sub(r"(?<=\n)[,\s]+", "", cleaned_text)
    cleaned_text = re.sub(r"^[,\s]+", "", cleaned_text)
    cleaned_text = re.sub(r"\s+\.", ".", cleaned_text)
    cleaned_text = re.sub(r"\s+,", ",", cleaned_text)
    cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)
    cleaned_text = re.sub(r"\n\s*\n\s*\n+", "\n\n", cleaned_text)

    return (cleaned_text.strip(), valid_citations, removed_citations)


# -----------------------------------------------------------------------------
# 3. Deterministic Fallback Builder
# -----------------------------------------------------------------------------

def build_deterministic_fallback_summary(tool_outputs: List[Dict[str, Any]]) -> str:
    """
    Builds an unambiguous, deterministic markdown summary directly from tool outputs
    when the LLM fails numeric validation twice.
    """
    lines: List[str] = [
        "### 📊 Ringkasan Analisis Spasial Deterministik (Fallback)",
        "> *Catatan: Respons ini disintesis langsung dari kalkulasi deterministik PostGIS dan SimEngine demi menjamin keandalan data tanpa halusinasi angka.*",
        ""
    ]

    for out in tool_outputs:
        # Scorecard tool output
        if "composite_score" in out or "composite_livability_score" in out:
            name = out.get("district_name") or out.get("name") or "Kecamatan"
            code = out.get("district_code") or out.get("kemendagri_code") or ""
            pop = out.get("population", 0)
            comp = out.get("composite_score", out.get("composite_livability_score"))

            lines.append(f"**Profil Wilayah {name} ({code}):**")
            lines.append(f"- **Jumlah Penduduk:** {pop:,} jiwa")
            if comp is not None:
                lines.append(f"- **Indeks Kecukupan Fasilitas Dasar:** **{comp:.2f}**")
            else:
                comp_note = out.get("composite_note") or "tidak dinilai (cakupan data rendah)"
                lines.append(f"- **Indeks Kecukupan Fasilitas Dasar:** tidak dinilai ({comp_note})")
            lines.append("")

            pillars = out.get("pillar_scores")
            if isinstance(pillars, dict):
                lines.append("**Skor per Pilar Layanan:**")
                for pk, pdata in pillars.items():
                    if isinstance(pdata, dict):
                        lbl = pdata.get("label", pk)
                        sc = pdata.get("score")
                        if sc is not None:
                            lines.append(f"- {lbl}: {sc:.2f}%")
                        else:
                            p_reason = pdata.get("status") or "cakupan data rendah"
                            if pdata.get("types_excluded") and isinstance(pdata.get("types_excluded"), list):
                                excl = pdata.get("types_excluded")
                                if len(excl) > 0 and isinstance(excl[0], dict) and excl[0].get("reason"):
                                    p_reason = excl[0].get("reason")
                            lines.append(f"- {lbl}: tidak dinilai ({p_reason})")
                    elif isinstance(pdata, (int, float)):
                        lines.append(f"- {pk}: {float(pdata):.2f}%")
                    else:
                        lines.append(f"- {pk}: tidak dinilai (cakupan data rendah)")
                lines.append("")

            metrics = out.get("metrics_payload", [])
            if isinstance(metrics, list) and metrics:
                lines.append("**Status Defisit Fasilitas Utama:**")
                for m in metrics[:8]:
                    ft = m.get("facility_type", "")
                    exist = m.get("existing", 0)
                    req = m.get("required")
                    pct = m.get("compliance_pct")
                    defic = m.get("deficit")
                    is_scored = m.get("scored", True)
                    if not is_scored or pct is None or req is None:
                        lines.append(f"- `{ft}`: Ada {exist} unit (Fasilitas informasi - tidak dinilai)")
                    else:
                        lines.append(f"- `{ft}`: Ada {exist} unit / Standar {req} unit (Kepatuhan: {pct:.1f}%, Defisit: {defic} unit)")
                lines.append("")

        # Blank spots tool output
        if "unserved_area_km2" in out and "coverage_percentage" in out:
            ft = out.get("facility_type", "")
            cov = out.get("coverage_percentage", "")
            unserved = out.get("unserved_area_km2", 0.0)
            radius = out.get("service_radius_meters", 0)
            lines.append(f"**Analisis Blank Spot `{ft}` (Radius {radius}m):**")
            lines.append(f"- Cakupan Layanan: {cov}")
            lines.append(f"- Area Belum Terlayani: {unserved} km²")
            lines.append("")

        # Simulation tool output
        if "score_delta" in out or "simulated_composite_score" in out:
            lines.append("**Hasil Simulasi Skenario (Sandbox Read-Only):**")
            lines.append(f"- Tambahan Penghuni: {out.get('population_delta', out.get('new_occupants', 0)):,} jiwa")
            score_d = out.get("score_delta")
            if score_d is not None:
                lines.append(f"- Delta Skor Komposit: {score_d:+.2f} poin")
            else:
                lines.append("- Delta Skor Komposit: tidak dinilai (cakupan data rendah)")
            sim_score_val = out.get("simulated_composite_score")
            if sim_score_val is not None:
                lines.append(f"- Skor Pasca Simulasi: {sim_score_val:.2f}")
            else:
                lines.append("- Skor Pasca Simulasi: tidak dinilai (cakupan data rendah)")
            if out.get("mandated_rth_m2"):
                lines.append(f"- Estimasi Alokasi RTH (Asumsi 20%): {out.get('mandated_rth_m2'):,.1f} m²")
            if out.get("impact_label"):
                lines.append(f"- Indikasi Dampak: {out.get('impact_label')}")
            lines.append("")

    return "\n".join(lines).strip()


def build_simulation_deterministic_block(tool_name: str, out: Dict[str, Any]) -> str:
    """
    Builds the deterministic numeric block for simulation answers:
    Includes population before/after, composite before/after and delta, per-pillar deltas,
    new deficit units per facility type, impact level + rule, and disclaimer.
    """
    lines: List[str] = []
    d_name = out.get("district_name") or "Wilayah"

    if tool_name == "run_superblock_simulation":
        proj = out.get("project_name", "Proyek Superblok")
        units = out.get("residential_units", 0)
        lines.append(f"### 🏗️ Hasil Simulasi Superblok: {proj} ({d_name})")
        lines.append(f"- **Kapasitas Hunian:** {units:,} unit ({out.get('estimated_new_occupants', 0):,} jiwa)")
        if out.get("mandated_public_rth_m2"):
            lines.append(f"- **Estimasi Alokasi RTH (Asumsi 20%):** {out.get('mandated_public_rth_m2'):,.1f} m²")
        if out.get("mandated_water_retention_m3"):
            lines.append(f"- **Estimasi Kolam Retensi (Asumsi 150 mm/hari):** {out.get('mandated_water_retention_m3'):,.1f} m³")
        lines.append("- **Catatan Parameter:** Parameter asumsi (belum diverifikasi ke Perda 31/2022): RTH 20%, retensi 150 mm/hari, KDB 50%")
        delta_data = out.get("simulation_delta") or out
    else:
        lines.append(f"### 📈 Hasil Simulasi Perubahan Populasi ({d_name})")
        delta_data = out

    base_pop = delta_data.get("baseline_population")
    sim_pop = delta_data.get("simulated_population") or out.get("new_total_population")
    delta_pop = delta_data.get("population_delta")
    if base_pop is not None and sim_pop is not None:
        delta_val = delta_pop if delta_pop is not None else (sim_pop - base_pop)
        lines.append(f"- **Populasi:** {base_pop:,} jiwa ➔ {sim_pop:,} jiwa (+{delta_val:,} jiwa) *(Sumber data penduduk belum terverifikasi (TODO-VERIFY))*")
    elif delta_pop is not None:
        lines.append(f"- **Pertambahan Populasi:** +{delta_pop:,} jiwa *(Sumber data penduduk belum terverifikasi (TODO-VERIFY))*")

    base_score = delta_data.get("baseline_composite_score")
    sim_score = delta_data.get("simulated_composite_score")
    score_delta = delta_data.get("score_delta")
    if base_score is not None and sim_score is not None:
        delta_s = score_delta if score_delta is not None else (sim_score - base_score)
        lines.append(f"- **Skor Komposit:** {base_score:.2f} ➔ {sim_score:.2f} ({delta_s:+.2f} poin)")
    elif score_delta is not None:
        lines.append(f"- **Perubahan Skor Komposit:** {score_delta:+.2f} poin")
    else:
        lines.append("- **Skor Komposit:** tidak dinilai (cakupan data rendah)")

    p_deltas = delta_data.get("pillar_deltas")
    if isinstance(p_deltas, dict) and p_deltas:
        p_lines = []
        for pk, pinfo in p_deltas.items():
            if isinstance(pinfo, dict):
                b_s = pinfo.get("baseline_score")
                s_s = pinfo.get("simulated_score")
                d_s = pinfo.get("delta")
                if b_s is not None and s_s is not None and d_s is not None:
                    p_lines.append(f"  * {pk}: {b_s:.2f} ➔ {s_s:.2f} ({d_s:+.2f})")
                else:
                    p_lines.append(f"  * {pk}: tidak dinilai (cakupan data rendah)")
        if p_lines:
            lines.append("- **Perubahan per Pilar:**")
            lines.extend(p_lines)

    metrics = delta_data.get("metrics_comparison", [])
    new_deficits = [m for m in metrics if m.get("new_deficit_units", 0) > 0 or m.get("deficit_delta", 0) < 0]
    if new_deficits:
        lines.append("- **Defisit Fasilitas Baru:**")
        for m in new_deficits:
            ft = m.get("facility_type", "")
            nd = m.get("new_deficit_units") or abs(m.get("deficit_delta", 0))
            sim_d = abs(m.get("simulated_deficit", 0))
            lines.append(f"  * {ft}: +{nd} unit (total defisit: {sim_d} unit)")
    else:
        lines.append("- **Defisit Fasilitas Baru:** Tidak ada defisit baru.")

    impact_lvl = out.get("impact_level") or delta_data.get("impact_level", "Rendah")
    impact_r = out.get("impact_rule") or delta_data.get("impact_rule", "")
    if impact_r:
        lines.append(f"- **Indikasi Dampak:** {impact_lvl} ({impact_r})")
    else:
        lines.append(f"- **Indikasi Dampak:** {impact_lvl}")

    disc = out.get("disclaimer") or delta_data.get("disclaimer") or "[DATA SIMULASI HIPOTESIS] Simulasi sandbox terisolasi, tidak mengubah data master dan bukan keputusan perizinan resmi."
    lines.append("")
    lines.append(f"> *{disc}*")

    return "\n".join(lines).strip()


# -----------------------------------------------------------------------------
# 4. Incident Logger
# -----------------------------------------------------------------------------

def log_numeric_violation(
    unsupported_numbers: List[str],
    original_reply: str,
    action_taken: str,
    resolved: bool,
    mislabeled_numbers: Optional[List[Dict[str, Any]]] = None
):
    """Logs LLM numeric hallucination or mislabeling incident to `incident_logs`."""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO incident_logs (
                    incident_type, severity, target_service, action_taken, status, error_payload
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb);
            """, (
                "llm_numeric_violation",
                "MEDIUM",
                "backend_agent",
                action_taken,
                "RESOLVED" if resolved else "FAILED",
                json.dumps({
                    "unsupported_numbers": unsupported_numbers,
                    "mislabeled_numbers": mislabeled_numbers or [],
                    "original_reply": original_reply[:500]
                })
            ))
            logger.info(f"Recorded incident_log: llm_numeric_violation (resolved={resolved}) for unsupported={unsupported_numbers} mislabeled={mislabeled_numbers}")
    except Exception as e:
        logger.warning(f"Failed to record incident log for numeric violation: {e}")
