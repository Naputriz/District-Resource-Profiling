"""
Cognitive Spatial Agent Orchestrator.
Powers the interactive conversational assistant (Qwen 2.5 14B).
Orchestrates:
1. Multi-round text-to-spatial tool calling loop (up to 4 rounds per user turn).
2. Conversation history trimming (preserves system prompt + last 6 conversation turns, no orphan tool messages).
3. Deterministic frontend Map Action Events (derived exclusively from executed tools, never LLM text).
4. Out-of-scope refusal for permit decisions and legal advice.
5. Strict numeric guardrails and verified legal citations across all rounds.
"""

import os
import re
import json
import logging
import urllib.request
import time
from typing import Dict, Any, List, Optional, Tuple, Set
from pydantic import BaseModel, Field

from backend.app.agent.tools import SPATIAL_AGENT_TOOLS, execute_tool_call
from backend.app.agent.guardrails import (
    build_allowed_numbers,
    validate_numeric_claims,
    validate_label_bindings,
    validate_and_sanitize_citations,
    build_deterministic_fallback_summary,
    build_simulation_deterministic_block,
    log_numeric_violation
)
from backend.app.core.config import settings
from backend.app.core.db import get_db_cursor
from backend.app.api.routers.regions import (
    REGIONS_CATALOG,
    get_region_meta,
    get_province_population_meta,
)

logger = logging.getLogger(__name__)


def _validated_active_province(province_code: Optional[str]) -> Optional[str]:
    """Returns stripped province_code only if known in REGIONS_CATALOG and active."""
    if not province_code:
        return None
    code = str(province_code).strip()
    if code in REGIONS_CATALOG and code in settings.active_provinces:
        return code
    return None


def build_system_prompt(province_code: Optional[str] = None) -> str:
    """Builds the system prompt describing the active region and population source."""
    valid_prov = _validated_active_province(province_code)
    prov_code = valid_prov or settings.DEFAULT_PROVINCE_CODE
    meta = get_region_meta(prov_code)
    region_name = meta.get("name") or settings.DEFAULT_PROVINCE_NAME
    if valid_prov:
        _, pop_source, _ = get_province_population_meta(prov_code)
        region_header = f"wilayah aktif: Provinsi {region_name} (kode {prov_code}, sumber data penduduk: {pop_source})"
        pop_hint = pop_source
    else:
        region_header = f"wilayah aktif (Provinsi {region_name})"
        pop_hint = "sumber data penduduk resmi dari output tool"

    return f"""Anda adalah 'District Resource Profiling Assistant', asisten AI percakapan tata ruang perkotaan dan kebijakan publik untuk {region_header}.

ATURAN PENCARIAN WILAYAH:
Setiap nama tempat dalam pertanyaan pengguna adalah nama kecamatan di wilayah provinsi aktif (kecuali dinyatakan lain secara eksplisit). Anda WAJIB langsung memanggil tool yang sesuai (misalnya get_district_scorecard) untuk mencari nama tempat tersebut sebelum meminta klarifikasi kepada pengguna.

TUGAS DAN ATURAN KETAT ANDA:
1. ATURAN #1 (DILARANG MENGARANG ANGKA): Anda DILARANG menghitung atau mengarang angka secara manual. Setiap angka dalam jawaban Anda (skor, populasi, defisit, persentase, luas, radius) WAJIB berasal persis dari data output tool giliran ini. DILARANG menghitung persentase baru secara mandiri. Jika output tool menyatakan score_status = "Data tidak memadai" atau composite_score bernilai null, nyatakan secara eksplisit "Data tidak memadai" beserta alasan cakupan (coverage_reason / composite_note), dan DILARANG menyebut skor komposit atau defisit unit sebagai nol. Selalu sebutkan sumber data penduduk dari output tool ({pop_hint}).
2. ATURAN #2 (ISOLASI SANDBOX): Jelaskan hasil simulasi dengan menyatakan bahwa data tersebut adalah skenario hipotetis terisolasi tanpa mengubah data master. Indikasi dampak adalah bahan pertimbangan perencanaan (Rendah / Sedang / Tinggi), bukan keputusan izin definitif.
3. ATURAN #3 (FORMAT SITASI REGULASI WAJIB): Anda HANYA boleh merujuk regulasi menggunakan format tag [REG:<chunk_id>] persis dengan chunk_id yang terdapat pada output tool search_regulations giliran ini. DILARANG membuat sitasi teks bebas di luar format tersebut.
4. ATURAN #4 (PEMBEDAAN DEFISIT UNIT VS CAKUPAN RADIUS):
   - "defisit unit" = kebutuhan - jumlah fasilitas (dari scorecard tool get_district_scorecard pada metrics_payload). Ini adalah defisit fisik unit fasilitas (misal: "kebutuhan <N> unit, eksisting <M> unit, defisit <N-M> unit (semua angka dari output tool)").
   - "cakupan %" = luas terlayani radius (dari blank spot tool get_unserved_blank_spots). Ini BUKAN defisit unit fasilitas.
   DILARANG menukar defisit unit dengan persentase cakupan radius.
5. Gaya Bahasa: Profesional, solutif, berbasis data spasial konkret, dan objektif sebagai analis tata ruang / perencana kota senior."""


SYSTEM_PROMPT = build_system_prompt()

# -----------------------------------------------------------------------------
# Out-of-Scope Detection & Refusal (README.md §4, §11)
# -----------------------------------------------------------------------------
OUT_OF_SCOPE_PATTERNS = [
    r"boleh(?:kah)?\s+(?:di)?setujui",
    r"izin(?:nya)?\s+(?:sah|legal|berlaku|keluar|terbit|lolos)",
    r"apakah\s+.*(?:izin|perizinan)\s+.*(?:bisa|dapat|boleh)?\s*(?:di)?(?:setujui|terbit|diterbitkan|keluar|dikeluarkan|disahkan|lolos)",
    r"apakah\s+.*(?:izin|perizinan)\s+.*(?:sah|legal|resmi|valid)",
    r"apakah\s+.*(?:boleh|layak|bisa|dapat)\s+(?:di)?(?:setujui|izinkan|diberi(?:kan)?\s+izin)",
    r"boleh(?:kah)?\s+(?:di)?(?:beri|berikan|terbitkan|keluarkan|miliki|kantongi)?\s*izin",
    r"(?:beri|berikan|memberikan)\s+izin",
    r"rekomendasi\s+(?:keputusan\s+)?perizin(?:an)?",
    r"rekomendasi\s+izin",
    r"keputusan\s+perizin(?:an)?",
    r"nasihat\s+hukum",
    r"fatwa\s+hukum",
    r"persetujuan\s+izin",
    r"legalitas\s+izin",
    r"proyek\s+.*boleh\s+(?:di)?(?:setujui|izinkan|diberi(?:kan)?\s+izin)",
]

OUT_OF_SCOPE_REFUSAL = (
    "Sistem District Resource Profiling menyediakan indikasi dampak spasial dan simulasi skenario "
    "perencanaan (Rendah / Sedang / Tinggi) berbasis regulasi teknis. Sistem ini tidak berwenang "
    "memberikan keputusan perizinan resmi atau nasihat hukum mengenai legalitas proyek.\n\n"
    "Namun, kami dapat menjalankan simulasi dampak beban penduduk ('what-if') atau audit kewajiban "
    "fasilitas superblok (RTH 20% dan Zero Delta Q) untuk wilayah Anda sebagai bahan pertimbangan teknis. "
    "Apakah Anda ingin menjalankan simulasi dampak spasial tersebut?"
)

def is_out_of_scope_request(text: str) -> bool:
    """
    Detects whether the user query requests an official permit decision or legal advice.
    Enforces README.md §4, §11:
    - Questions asking for a permit decision ('apakah proyek ini boleh disetujui?')
    - Questions asking for legal validity ('apakah izinnya sah?')
    """
    text_lower = text.lower()
    for pattern in OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False


# -----------------------------------------------------------------------------
# Conversation History Trimming
# -----------------------------------------------------------------------------
def trim_conversation_history(
    messages: List["ChatMessage"],
    max_turns: int = 6
) -> Tuple[List[Dict[str, Any]], bool, int]:
    """
    Trims conversation history:
    1. Keep the system prompt plus at most the last 6 conversation turns.
       A conversation turn is defined as starting with a 'user' message, followed by any
       corresponding 'assistant' and associated 'tool' messages until the next 'user' message.
    2. Never trim the system prompt.
    3. Never leave an orphan tool message without its tool call.

    Returns:
        (sanitized_history_messages, history_trimmed, history_turns_kept)
    """
    non_system = [m for m in messages if m.role != "system"]
    if not non_system:
        return ([], False, 0)

    # Group into conversation turns: each turn begins at a 'user' message
    turns: List[List[ChatMessage]] = []
    current_turn: List[ChatMessage] = []
    for m in non_system:
        if m.role == "user":
            if current_turn:
                turns.append(current_turn)
            current_turn = [m]
        else:
            current_turn.append(m)
    if current_turn:
        turns.append(current_turn)

    total_turns = len(turns)
    if total_turns > max_turns:
        history_trimmed = True
        kept_turns = turns[-max_turns:]
        history_turns_kept = max_turns
    else:
        history_trimmed = False
        kept_turns = turns
        history_turns_kept = total_turns

    # Flatten kept turns
    flattened: List[Dict[str, Any]] = []
    for turn in kept_turns:
        for m in turn:
            flattened.append({"role": m.role, "content": m.content})

    # Guard against orphan tool messages (must be preceded by assistant or tool)
    sanitized: List[Dict[str, Any]] = []
    for msg in flattened:
        if msg.get("role") == "tool":
            if sanitized and sanitized[-1].get("role") in ("assistant", "tool"):
                sanitized.append(msg)
            else:
                logger.warning("Dropped orphan tool message during history trimming.")
        else:
            sanitized.append(msg)

    return (sanitized, history_trimmed, history_turns_kept)


# -----------------------------------------------------------------------------
# Pydantic Schemas
# -----------------------------------------------------------------------------
class MapActionEvent(BaseModel):
    action_type: str  # fly_to, highlight_blank_spot, render_simulation_layer, clear_layers
    payload: Dict[str, Any]

class ChatMessage(BaseModel):
    role: str  # user, assistant, system, tool
    content: str

class AgentChatRequest(BaseModel):
    messages: List[ChatMessage]
    district_context: Optional[str] = None  # Current active district on map
    province_code: Optional[str] = None  # Active province scope on map

class AgentChatResponse(BaseModel):
    reply: str
    tool_calls_executed: List[Dict[str, Any]] = []
    map_actions: List[MapActionEvent] = []
    model_used: str = "deterministic-fallback"
    latency_seconds: float = 0.0
    guardrail: str = "passed"  # "passed" | "retried" | "numeric_fallback"
    unsupported_numbers: List[str] = []
    mislabeled_numbers: List[Dict[str, Any]] = []
    citations: List[str] = []
    removed_citations: List[str] = []
    rounds_used: int = 1
    stop_reason: str = "final_answer"  # "final_answer" | "max_rounds" | "llm_unavailable"
    tool_trace: List[Dict[str, Any]] = []  # list of {round, tool, args, ok}
    history_trimmed: bool = False
    history_turns_kept: int = 0
    raw_llm_reply: Optional[str] = None
    answer_mode: Optional[str] = None  # "template+narrative" | "template_only"


# -----------------------------------------------------------------------------
# Cognitive Spatial Agent Orchestrator
# -----------------------------------------------------------------------------
class CognitiveSpatialAgentOrchestrator:
    def __init__(self):
        self.api_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model_name = os.getenv("OLLAMA_MODEL_NAME", "qwen2.5:14b")

    def _call_llm(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Calls local Ollama /api/chat with num_ctx=8192 and keep_alive=24h."""
        url = f"{self.api_base}/api/chat"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "keep_alive": "24h",
            "options": {
                "num_ctx": 8192,
                "temperature": 0.1
            }
        }
        if tools:
            payload["tools"] = tools

        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def process_chat(self, req: AgentChatRequest) -> AgentChatResponse:
        """
        Executes full agentic tool-use cycle:
        1. Checks out-of-scope intent (permit refusal).
        2. Trims conversation history (max 6 turns, preserves system prompt).
        3. Multi-round tool execution loop (up to 4 tool rounds).
        4. Deterministic map action event derivation (from executed tools only).
        5. Numeric guardrail & citation validation across all rounds.
        """
        start_time = time.time()
        executed_tools: List[Dict[str, Any]] = []
        map_actions: List[MapActionEvent] = []
        all_tool_outputs: List[Dict[str, Any]] = []
        all_returned_citations: List[Dict[str, Any]] = []
        tool_trace: List[Dict[str, Any]] = []
        model_used = "deterministic-fallback"
        guardrail = "passed"
        unsupported_numbers: List[str] = []
        mislabeled_numbers: List[Dict[str, Any]] = []
        valid_citations: List[str] = []
        removed_citations: List[str] = []
        rounds_used = 0
        stop_reason = "final_answer"
        assistant_reply = ""
        raw_llm_reply: Optional[str] = None
        answer_mode: Optional[str] = None
        simulation_tool_executed: Optional[Tuple[str, Dict[str, Any]]] = None

        # Step 1: Trim conversation history (keep up to last 6 turns)
        trimmed_msgs, history_trimmed, history_turns_kept = trim_conversation_history(req.messages, max_turns=6)

        # Step 2: Out-of-scope check (§5D)
        last_user_content = ""
        for m in reversed(req.messages):
            if m.role == "user":
                last_user_content = m.content
                break

        if last_user_content and is_out_of_scope_request(last_user_content):
            logger.info("Out-of-scope request detected (permit decision / legal advice refusal).")
            return AgentChatResponse(
                reply=OUT_OF_SCOPE_REFUSAL,
                tool_calls_executed=[],
                map_actions=[],
                model_used=self.model_name,
                latency_seconds=round(time.time() - start_time, 2),
                guardrail="passed",
                unsupported_numbers=[],
                mislabeled_numbers=[],
                citations=[],
                removed_citations=[],
                rounds_used=0,
                stop_reason="final_answer",
                tool_trace=[],
                history_trimmed=history_trimmed,
                history_turns_kept=history_turns_kept
            )

        # Prepare messages: system prompt is never trimmed
        active_prov = _validated_active_province(req.province_code)
        sys_prompt = build_system_prompt(active_prov)
        messages = [{"role": "system", "content": sys_prompt}] + trimmed_msgs

        # Step 3: Multi-round Tool Loop (up to 4 rounds per user message)
        max_rounds = 4

        for round_num in range(1, max_rounds + 1):
            rounds_used = round_num

            try:
                llm_res = self._call_llm(messages, tools=SPATIAL_AGENT_TOOLS)
                model_used = llm_res.get("model", self.model_name)
                message = llm_res.get("message", {})
                tool_calls = message.get("tool_calls", [])
            except Exception as llm_err:
                logger.error(f"Local AI inference error in round {round_num}: {llm_err}")
                stop_reason = "llm_unavailable"
                model_used = "deterministic-fallback"
                guardrail = "numeric_fallback"
                if simulation_tool_executed:
                    sim_tool_name, sim_tool_output = simulation_tool_executed
                    assistant_reply = build_simulation_deterministic_block(sim_tool_name, sim_tool_output)
                    answer_mode = "template_only"
                elif all_tool_outputs:
                    assistant_reply = build_deterministic_fallback_summary(all_tool_outputs)
                else:
                    assistant_reply = (
                        f"Layanan inferensi AI lokal saat ini tidak tersedia: {str(llm_err)}. "
                        "Sistem analisis spasial deterministik tetap siap melayani kebutuhan Anda."
                    )
                break

            if not tool_calls:
                # Deterministic fallback when LLM asks for clarification on a bare place name in round 1
                if round_num == 1 and not all_tool_outputs and active_prov and last_user_content:
                    fallback_target = self._resolve_bare_place_in_province(last_user_content, active_prov)
                    if fallback_target:
                        fn_name = "get_district_scorecard"
                        args = {"district_code": fallback_target}
                        logger.info(
                            f"[Round {round_num}] LLM made no tool call; deterministic place pre-check invoking {fn_name}({args}) in province {active_prov}."
                        )
                        try:
                            tool_output = execute_tool_call(fn_name, args, province_code=active_prov)
                            tool_ok = not (isinstance(tool_output, dict) and bool(tool_output.get("error")))
                        except Exception as tool_err:
                            tool_ok = False
                            tool_output = {"error": str(tool_err)}

                        if tool_ok:
                            tool_trace.append({
                                "round": round_num,
                                "tool": fn_name,
                                "args": args,
                                "ok": True,
                            })
                            executed_tools.append({
                                "name": fn_name,
                                "arguments": args,
                                "result_summary": tool_output,
                            })
                            all_tool_outputs.append(tool_output)
                            self._extract_map_actions(
                                fn_name, args, tool_output, map_actions, province_code=active_prov
                            )
                            messages.append({
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {"function": {"name": fn_name, "arguments": args}}
                                ],
                            })
                            messages.append({
                                "role": "tool",
                                "content": json.dumps(tool_output, default=str),
                            })
                            continue

                # LLM produced a final answer without requesting further tools
                stop_reason = "final_answer"
                raw_reply = message.get("content", "")
                raw_llm_reply = raw_reply

                # Handle simulation tools with deterministic template + qualitative narrative (§13.1B)
                if simulation_tool_executed:
                    sim_tool_name, sim_tool_output = simulation_tool_executed
                    det_block = build_simulation_deterministic_block(sim_tool_name, sim_tool_output)

                    narrative_candidate = raw_reply.strip()
                    # Check if narrative has digits
                    if re.search(r"\d", narrative_candidate):
                        logger.info("Simulation narrative contains digits. Triggering single retry for pure qualitative text...")
                        sim_retry_messages = list(messages)
                        sim_retry_messages.append({"role": "assistant", "content": raw_reply})
                        sim_retry_messages.append({
                            "role": "user",
                            "content": (
                                "Penjelasan Anda mengandung angka/digit. "
                                "Seluruh data numerik simulasi telah disajikan secara terpisah pada template deterministik. "
                                "Tuliskan HANYA analisis kualitatif dan implikasi kebijakan perkotaan secara ringkas "
                                "MURNI TANPA ANGKA ATAU DIGIT SAMA SEKALI (dilarang menggunakan karakter angka 0-9)."
                            )
                        })
                        try:
                            retry_res = self._call_llm(sim_retry_messages, tools=None)
                            retry_text = retry_res.get("message", {}).get("content", "").strip()
                            if re.search(r"\d", retry_text) or not retry_text:
                                logger.warning("Simulation narrative retry still contained digits. Omitting narrative segment.")
                                answer_mode = "template_only"
                                raw_reply = det_block
                            else:
                                logger.info("Simulation narrative retry passed with no digits.")
                                answer_mode = "template+narrative"
                                raw_reply = f"{det_block}\n\n### 📝 Analisis Kualitatif\n{retry_text}"
                        except Exception as sim_err:
                            logger.warning(f"Error during simulation narrative retry: {sim_err}. Omitting narrative segment.")
                            answer_mode = "template_only"
                            raw_reply = det_block
                    elif narrative_candidate:
                        answer_mode = "template+narrative"
                        raw_reply = f"{det_block}\n\n### 📝 Analisis Kualitatif\n{narrative_candidate}"
                    else:
                        answer_mode = "template_only"
                        raw_reply = det_block

                # Guardrail & Citation validation across ALL tool outputs accumulated across all rounds
                cleaned_reply, valid_citations, removed_citations = validate_and_sanitize_citations(
                    raw_reply, all_returned_citations
                )
                allowed_numbers = build_allowed_numbers(all_tool_outputs)
                passed_num, unsupported = validate_numeric_claims(cleaned_reply, allowed_numbers)
                passed_lbl, mislabeled = validate_label_bindings(cleaned_reply, all_tool_outputs)

                if passed_num and passed_lbl:
                    assistant_reply = cleaned_reply
                    guardrail = "passed"
                else:
                    logger.warning(
                        f"Numeric/label guardrail violation detected. Unsupported: {unsupported}, Mislabeled: {mislabeled}. "
                        "Triggering single retry..."
                    )
                    issues = []
                    if unsupported:
                        issues.append(f"Angka tidak tercantum pada output tool: {unsupported}")
                    if mislabeled:
                        m_details = [
                            f"angka '{m['number']}' (diharapkan untuk {m['expected_label']}, namun terikat dengan {m['found_label']})"
                            for m in mislabeled
                        ]
                        issues.append(f"Inkonsistensi label/metrik numerik: {'; '.join(m_details)}")

                    retry_prompt = (
                        f"Jawaban Anda sebelumnya mengandung kesalahan data numerik: {' | '.join(issues)}. "
                        "Revisi jawaban Anda secara menyeluruh. Anda WAJIB mematuhi:\n"
                        "1. Hanya menggunakan angka yang tercantum persis dalam output tool di atas.\n"
                        "2. Menghubungkan setiap angka dengan metrik yang benar (skor komposit jangan tertukar dengan skor pilar, dan defisit fasilitas jangan tertukar jenis fasilitasnya).\n"
                        "DILARANG mengarang angka atau menukar metrik."
                    )
                    retry_messages = list(messages)
                    retry_messages.append({"role": "assistant", "content": raw_reply})
                    retry_messages.append({"role": "user", "content": retry_prompt})

                    try:
                        retry_res = self._call_llm(retry_messages, tools=None)
                        retry_reply = retry_res.get("message", {}).get("content", "")
                        cleaned_retry, retry_cits, retry_removed = validate_and_sanitize_citations(
                            retry_reply, all_returned_citations
                        )
                        retry_passed_num, retry_unsupported = validate_numeric_claims(cleaned_retry, allowed_numbers)
                        retry_passed_lbl, retry_mislabeled = validate_label_bindings(cleaned_retry, all_tool_outputs)

                        if retry_passed_num and retry_passed_lbl:
                            logger.info("LLM retry succeeded and passed both numeric and label guardrails.")
                            assistant_reply = cleaned_retry
                            guardrail = "retried"
                            unsupported_numbers = []
                            mislabeled_numbers = []
                            valid_citations = retry_cits
                            removed_citations.extend(retry_removed)
                            log_numeric_violation(
                                unsupported, assistant_reply, "LLM retry succeeded", resolved=True, mislabeled_numbers=mislabeled
                            )
                        else:
                            logger.warning(
                                f"LLM retry failed. Unsupported: {retry_unsupported}, Mislabeled: {retry_mislabeled}. "
                                "Falling back to deterministic summary."
                            )
                            guardrail = "numeric_fallback"
                            unsupported_numbers = retry_unsupported
                            mislabeled_numbers = retry_mislabeled
                            if simulation_tool_executed:
                                sim_tool_name, sim_tool_output = simulation_tool_executed
                                assistant_reply = build_simulation_deterministic_block(sim_tool_name, sim_tool_output)
                                answer_mode = "template_only"
                            else:
                                assistant_reply = build_deterministic_fallback_summary(all_tool_outputs)
                            valid_citations = [c.get("chunk_id") for c in all_returned_citations if c.get("chunk_id")]
                            removed_citations.extend(retry_removed)
                            log_numeric_violation(
                                retry_unsupported or unsupported,
                                retry_reply,
                                "Deterministic fallback invoked after failed retry",
                                resolved=False,
                                mislabeled_numbers=retry_mislabeled or mislabeled
                            )
                    except Exception as retry_err:
                        logger.error(f"Error during LLM retry: {retry_err}. Using deterministic fallback.")
                        guardrail = "numeric_fallback"
                        unsupported_numbers = unsupported
                        mislabeled_numbers = mislabeled
                        if simulation_tool_executed:
                            sim_tool_name, sim_tool_output = simulation_tool_executed
                            assistant_reply = build_simulation_deterministic_block(sim_tool_name, sim_tool_output)
                            answer_mode = "template_only"
                        else:
                            assistant_reply = build_deterministic_fallback_summary(all_tool_outputs)
                        log_numeric_violation(
                            unsupported, assistant_reply, f"Retry error: {retry_err}", resolved=False, mislabeled_numbers=mislabeled
                        )

                break

            else:
                # Tool calls requested in round_num
                messages.append(message)
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    fn_name = fn.get("name")
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}

                    logger.info(f"[Round {round_num}] Agent invoking tool: {fn_name}({args})")
                    tool_ok = True
                    try:
                        if active_prov:
                            tool_output = execute_tool_call(fn_name, args, province_code=active_prov)
                        else:
                            tool_output = execute_tool_call(fn_name, args)
                        tool_ok = not (isinstance(tool_output, dict) and bool(tool_output.get("error")))
                    except Exception as tool_err:
                        tool_ok = False
                        tool_output = {"error": str(tool_err)}

                    tool_trace.append({
                        "round": round_num,
                        "tool": fn_name,
                        "args": args,
                        "ok": tool_ok
                    })
                    executed_tools.append({
                        "name": fn_name,
                        "arguments": args,
                        "result_summary": tool_output
                    })
                    all_tool_outputs.append(tool_output)

                    if fn_name in ("run_what_if_simulation", "run_superblock_simulation") and tool_ok:
                        simulation_tool_executed = (fn_name, tool_output)

                    if fn_name == "search_regulations" and tool_ok:
                        cits = tool_output.get("citations", [])
                        if isinstance(cits, list):
                            all_returned_citations.extend(cits)

                    # Deterministic map actions derived strictly from executed tools
                    if tool_ok:
                        self._extract_map_actions(
                            fn_name, args, tool_output, map_actions, province_code=active_prov
                        )

                    messages.append({
                        "role": "tool",
                        "content": json.dumps(tool_output, default=str)
                    })

                # Check max rounds condition per §5A.2
                if round_num == max_rounds:
                    logger.info("Reached maximum 4 tool rounds. Stopping and synthesizing deterministic summary.")
                    stop_reason = "max_rounds"
                    if simulation_tool_executed:
                        sim_tool_name, sim_tool_output = simulation_tool_executed
                        assistant_reply = build_simulation_deterministic_block(sim_tool_name, sim_tool_output)
                        answer_mode = "template_only"
                    else:
                        assistant_reply = build_deterministic_fallback_summary(all_tool_outputs)
                    guardrail = "numeric_fallback"
                    valid_citations = [c.get("chunk_id") for c in all_returned_citations if c.get("chunk_id")]
                    break

        latency = round(time.time() - start_time, 2)

        return AgentChatResponse(
            reply=assistant_reply,
            tool_calls_executed=executed_tools,
            map_actions=map_actions,
            model_used=model_used,
            latency_seconds=latency,
            guardrail=guardrail,
            unsupported_numbers=unsupported_numbers,
            mislabeled_numbers=mislabeled_numbers,
            citations=valid_citations,
            removed_citations=removed_citations,
            rounds_used=rounds_used,
            stop_reason=stop_reason,
            tool_trace=tool_trace,
            history_trimmed=history_trimmed,
            history_turns_kept=history_turns_kept,
            raw_llm_reply=raw_llm_reply,
            answer_mode=answer_mode
        )

    def _resolve_bare_place_in_province(
        self,
        user_text: str,
        province_code: str,
    ) -> Optional[str]:
        """
        Matches a district name from `province_code` inside `user_text` when the LLM
        returned no tool calls on round 1. Returns canonical kemendagri_code if a single
        district matches uniquely (longest non-overlapping match), else None.
        """
        text = str(user_text or "").strip()
        if not text or not province_code:
            return None

        try:
            with get_db_cursor() as cur:
                cur.execute(
                    """
                    SELECT k.kemendagri_code, k.name
                    FROM kecamatan k
                    JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
                    JOIN provinces p ON p.id = c.province_id
                    WHERE p.kemendagri_code = %s;
                    """,
                    (province_code,),
                )
                rows = cur.fetchall()
        except Exception:
            return None

        matches: List[Tuple[str, str]] = []
        for r in rows:
            name = str(r.get("name") or "").strip()
            code = str(r.get("kemendagri_code") or "").strip()
            if not name or not code:
                continue
            if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, flags=re.IGNORECASE):
                matches.append((code, name))

        if not matches:
            return None

        # Prefer longest matches; drop shorter names contained inside a longer matched name
        matches.sort(key=lambda item: len(item[1]), reverse=True)
        filtered: List[Tuple[str, str]] = []
        for code, name in matches:
            nl = name.lower()
            if any(nl != kept_name.lower() and nl in kept_name.lower() for _, kept_name in filtered):
                continue
            filtered.append((code, name))

        if len(filtered) == 1:
            return filtered[0][0]
        return None

    def _resolve_district_code(
        self,
        raw_code: Optional[str],
        output: Optional[Dict[str, Any]],
        province_code: Optional[str] = None,
    ) -> Optional[str]:
        """
        Resolves canonical Kemendagri code deterministically per W11 D2:
        1. Prefer canonical code in tool output.
        2. Else look it up by case-insensitive name or code from database.
        3. If unresolvable, returns None.
        """
        if isinstance(output, dict) and output.get("error"):
            return None

        if isinstance(output, dict):
            if output.get("kemendagri_code"):
                return str(output["kemendagri_code"])
            out_dc = output.get("district_code")
            if out_dc and re.match(r"^\d{2}(\.\d{2})+(\.\d{2,4})?$", str(out_dc)):
                return str(out_dc)
            if isinstance(output.get("simulation_delta"), dict):
                sim_dc = output["simulation_delta"].get("district_code")
                if sim_dc and re.match(r"^\d{2}(\.\d{2})+(\.\d{2,4})?$", str(sim_dc)):
                    return str(sim_dc)

        target = raw_code or (output.get("district_code") if isinstance(output, dict) else None)
        if not target:
            return None

        from backend.app.engine.spatial import resolve_district_record
        try:
            record, _ = resolve_district_record(str(target), province_code=province_code)
            if record and record.get("kemendagri_code"):
                rec_prov = record.get("province_code") or str(record["kemendagri_code"])[:2]
                if rec_prov not in settings.active_provinces:
                    return None
                return str(record["kemendagri_code"])
        except Exception as e:
            logger.warning(f"Database lookup for district code '{target}' failed: {e}")

        return None

    def _extract_map_actions(
        self,
        tool_name: str,
        args: Dict[str, Any],
        output: Dict[str, Any],
        map_actions: List[MapActionEvent],
        province_code: Optional[str] = None,
    ):
        """
        Translates tool results into real-time frontend map actions deterministically.
        Map actions are NEVER generated from LLM text (§5C).
        Resolves canonical Kemendagri code deterministically; emits no action if unresolvable.
        """
        raw_code = args.get("district_code")
        d_code = self._resolve_district_code(raw_code, output, province_code=province_code)
        if not d_code:
            logger.warning(f"Could not resolve canonical district_code for map action from args={args}, output={output}. Skipping map action.")
            return

        if tool_name == "get_district_scorecard":
            # Avoid duplicate fly_to for the same district
            if not any(a.action_type == "fly_to" and a.payload.get("district_code") == d_code for a in map_actions):
                map_actions.append(MapActionEvent(
                    action_type="fly_to",
                    payload={
                        "district_code": d_code,
                        "name": output.get("name") or output.get("district_name"),
                        "score": (
                            output.get("composite_score")
                            if output.get("composite_score") is not None
                            else output.get("composite_livability_score")
                        )
                    }
                ))

        elif tool_name == "get_unserved_blank_spots":
            ftype = args.get("facility_type", "puskesmas_kelurahan")
            if not any(a.action_type == "highlight_blank_spot" and a.payload.get("district_code") == d_code and a.payload.get("facility_type") == ftype for a in map_actions):
                map_actions.append(MapActionEvent(
                    action_type="highlight_blank_spot",
                    payload={
                        "district_code": d_code,
                        "facility_type": ftype,
                        "unserved_km2": output.get("unserved_area_km2"),
                        "coverage_pct": output.get("coverage_percentage")
                    }
                ))

        elif tool_name in ["run_what_if_simulation", "run_superblock_simulation"]:
            delta_dict = output.get("simulation_delta") if isinstance(output.get("simulation_delta"), dict) else output
            map_actions.append(MapActionEvent(
                action_type="render_simulation_layer",
                payload={
                    "district_code": d_code,
                    "is_simulated": True,
                    "score_delta": delta_dict.get("score_delta", 0.0),
                    "simulated_score": delta_dict.get("simulated_composite_score") or delta_dict.get("simulated_score")
                }
            ))
