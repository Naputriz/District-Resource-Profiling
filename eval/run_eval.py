"""
Automated AI Evaluation Harness for Cognitive Spatial Assistant (Qwen 2.5 14B).
Enforces README.md §11:
- 30 Indonesian spatial evaluation questions.
- Runs 3 repetitions against the local Ollama backend via FastAPI TestClient.
- Computes metrics: tool selection accuracy, final answer number leaks, final answer citations consistent with the verified corpus,
  refusal accuracy, expected values present rate, raw unsupported numbers caught, raw citation hallucination rate,
  fallback rate, retry rate, and p50/p95 latency.
- Generates eval/results_<YYYYMMDD>.json and eval/REPORT.md.
"""

import os
import sys
import time
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient
from backend.app.main import app
from backend.app.core.db import init_db_pool, close_db_pool


def check_value_in_text(val: Any, text: str) -> bool:
    """Checks if ground truth value appears in text with common Indonesian & English formats."""
    if isinstance(val, (int, float)):
        num = float(val)
        patterns = [
            str(val),
            f"{num:.1f}",
            f"{num:.2f}",
            f"{num:.4f}",
            str(int(num)) if int(num) == num else None,
            f"{num:.2f}".replace(".", ","),
            f"{num:.1f}".replace(".", ","),
        ]
        patterns = [p for p in patterns if p is not None]
        # Formatted thousand separators
        if num >= 1000:
            patterns.append(f"{int(num):,}")
            patterns.append(f"{int(num):,}".replace(",", "."))

        for p in patterns:
            escaped = re.escape(p)
            if re.search(r"(?<![\d\w])" + escaped + r"(?![\d\w])", text):
                return True
        return False
    elif isinstance(val, str):
        return val.lower() in text.lower()
    return True


def evaluate_item(item: Dict[str, Any], chat_res: Dict[str, Any]) -> Dict[str, Any]:
    executed_tools = [t.get("name") for t in chat_res.get("tool_calls_executed", [])]
    expected_tools = item.get("expected_tools", [])
    reply = chat_res.get("reply", "")
    raw_llm_reply = chat_res.get("raw_llm_reply", reply)

    # 1. Tool selection accuracy
    if item.get("must_refuse"):
        tool_selection_correct = len(executed_tools) == 0
    else:
        tool_selection_correct = set(expected_tools).issubset(set(executed_tools))

    # 2. Refusal accuracy
    if item.get("must_refuse"):
        refusal_phrases = [
            "tidak berwenang memberikan keputusan perizinan",
            "bukan keputusan perizinan",
            "tidak berwenang",
            "kewenangan perizinan",
            "tidak memiliki wewenang"
        ]
        refusal_correct = any(p in reply.lower() for p in refusal_phrases) and len(executed_tools) == 0
    else:
        refusal_correct = True

    # 3. Ground truth numbers check
    expected_values = item.get("expected_values", {})
    values_present: Dict[str, bool] = {}
    for k, v in expected_values.items():
        if k == "api_path":
            continue
        values_present[k] = check_value_in_text(v, reply)

    all_values_present = all(values_present.values()) if values_present else True

    # 4. Citation validity & hallucinations
    removed_citations = chat_res.get("removed_citations", [])
    valid_citations = chat_res.get("citations", [])
    raw_citation_valid = (len(removed_citations) == 0)
    # Check for invalid/broken citations remaining in final reply
    final_invalid_citations = len(re.findall(r"\[REG:[^\]]*\]", reply))

    # 5. Guardrail & numbers check
    guardrail = chat_res.get("guardrail", "passed")
    raw_unsupported = chat_res.get("unsupported_numbers", [])
    raw_mislabeled = chat_res.get("mislabeled_numbers", [])

    # Final answer number leaks (unsupported numbers remaining in final reply)
    final_number_leaks = len(raw_unsupported) if guardrail not in ("numeric_fallback",) else 0

    return {
        "id": item["id"],
        "category": item["category"],
        "tool_selection_correct": tool_selection_correct,
        "executed_tools": executed_tools,
        "expected_tools": expected_tools,
        "refusal_correct": refusal_correct,
        "all_values_present": all_values_present,
        "values_breakdown": values_present,
        "raw_citation_valid": raw_citation_valid,
        "final_invalid_citations": final_invalid_citations,
        "valid_citations": valid_citations,
        "removed_citations": removed_citations,
        "guardrail": guardrail,
        "unsupported_numbers": raw_unsupported,
        "mislabeled_numbers": raw_mislabeled,
        "final_number_leaks": final_number_leaks,
        "latency_seconds": chat_res.get("latency_seconds", 0.0),
        "reply": reply,
        "raw_llm_reply": raw_llm_reply
    }


def compute_metrics_and_report(
    all_runs_results: List[List[Dict[str, Any]]],
    num_items: int,
    today_str: str,
    output_dir: Path
) -> Tuple[Dict[str, Any], str]:
    num_runs = len(all_runs_results)
    metrics_per_run = []
    all_latencies = []

    for run_idx, run in enumerate(all_runs_results, 1):
        total = len(run)
        tool_acc = sum(1 for r in run if r.get("tool_selection_correct")) / total * 100.0

        refuse_items = [r for r in run if r.get("category") == "out_of_scope" or r.get("must_refuse")]
        if refuse_items:
            refusal_acc = sum(1 for r in refuse_items if r.get("refusal_correct")) / len(refuse_items) * 100.0
        else:
            refusal_acc = 100.0

        error_count = sum(1 for r in run if r.get("guardrail") in ("exception", "error") or r.get("error"))
        error_rate = (error_count / total) * 100.0

        ev_rate = sum(1 for r in run if r.get("all_values_present", True)) / total * 100.0

        # Raw citation hallucination rate
        raw_cit_halluc_count = sum(1 for r in run if r.get("removed_citations"))
        raw_cit_halluc_rate = (raw_cit_halluc_count / total) * 100.0

        # Final answer leaks and invalid citations
        final_leaks_total = sum(r.get("final_number_leaks", 0) for r in run)
        final_inv_cits = sum(r.get("final_invalid_citations", 0) for r in run)

        raw_unsupported_total = sum(len(r.get("unsupported_numbers", [])) for r in run)
        fallback_count = sum(1 for r in run if r.get("guardrail") == "numeric_fallback")
        fallback_rate = (fallback_count / total) * 100.0
        retry_count = sum(1 for r in run if r.get("guardrail") == "retried")
        retry_rate = (retry_count / total) * 100.0

        latencies = [r.get("latency_seconds", 0.0) for r in run if r.get("latency_seconds", 0.0) > 0]
        all_latencies.extend(latencies)
        latencies_sorted = sorted(latencies)
        p50 = latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0.0
        p95_idx = int(len(latencies_sorted) * 0.95)
        p95 = latencies_sorted[p95_idx] if latencies_sorted else 0.0

        metrics_per_run.append({
            "run": run_idx,
            "tool_selection_accuracy": tool_acc,
            "refusal_accuracy": refusal_acc,
            "error_rate": error_rate,
            "expected_values_present_rate": ev_rate,
            "final_answer_number_leaks": final_leaks_total,
            "final_answer_invalid_citations": final_inv_cits,
            "raw_unsupported_numbers_caught": raw_unsupported_total,
            "raw_citation_hallucination_rate": raw_cit_halluc_rate,
            "fallback_rate": fallback_rate,
            "retry_rate": retry_rate,
            "p50_latency": p50,
            "p95_latency": p95
        })

    # Global percentiles across all runs
    all_latencies_sorted = sorted(all_latencies)
    global_p50 = all_latencies_sorted[len(all_latencies_sorted) // 2] if all_latencies_sorted else 0.0
    global_p95_idx = int(len(all_latencies_sorted) * 0.95)
    global_p95 = all_latencies_sorted[global_p95_idx] if all_latencies_sorted else 0.0

    mean_tool_acc = sum(m["tool_selection_accuracy"] for m in metrics_per_run) / num_runs
    min_tool_acc = min(m["tool_selection_accuracy"] for m in metrics_per_run)
    max_tool_acc = max(m["tool_selection_accuracy"] for m in metrics_per_run)

    mean_error_rate = sum(m["error_rate"] for m in metrics_per_run) / num_runs
    min_error_rate = min(m["error_rate"] for m in metrics_per_run)
    max_error_rate = max(m["error_rate"] for m in metrics_per_run)

    mean_refusal = sum(m["refusal_accuracy"] for m in metrics_per_run) / num_runs
    mean_ev_rate = sum(m["expected_values_present_rate"] for m in metrics_per_run) / num_runs
    min_ev_rate = min(m["expected_values_present_rate"] for m in metrics_per_run)
    max_ev_rate = max(m["expected_values_present_rate"] for m in metrics_per_run)

    mean_final_leaks = sum(m["final_answer_number_leaks"] for m in metrics_per_run) / num_runs
    mean_final_inv_cit = sum(m["final_answer_invalid_citations"] for m in metrics_per_run) / num_runs

    mean_raw_unsup = sum(m["raw_unsupported_numbers_caught"] for m in metrics_per_run) / num_runs
    mean_raw_cit_halluc = sum(m["raw_citation_hallucination_rate"] for m in metrics_per_run) / num_runs

    mean_fallback = sum(m["fallback_rate"] for m in metrics_per_run) / num_runs
    min_fallback = min(m["fallback_rate"] for m in metrics_per_run)
    max_fallback = max(m["fallback_rate"] for m in metrics_per_run)
    mean_retry = sum(m["retry_rate"] for m in metrics_per_run) / num_runs

    # Computed status verdicts based strictly on targets
    tool_status = "PASS" if mean_tool_acc >= 90.0 else "**MISSED TARGET**"
    refusal_status = "PASS" if mean_refusal == 100.0 else "**MISSED TARGET**"
    error_status = "PASS" if mean_error_rate == 0.0 else "**MISSED TARGET**"
    leaks_status = "PASS" if mean_final_leaks == 0 else "**MISSED TARGET**"
    inv_cit_status = "PASS" if mean_final_inv_cit == 0 else "**MISSED TARGET**"

    # Identify 5 Worst Items
    item_penalties: Dict[str, float] = {}
    item_details: Dict[str, Dict[str, Any]] = {}

    for run in all_runs_results:
        for r in run:
            iid = r["id"]
            if iid not in item_penalties:
                item_penalties[iid] = 0.0
                item_details[iid] = r
            if not r.get("tool_selection_correct"):
                item_penalties[iid] += 5.0
            if not r.get("refusal_correct"):
                item_penalties[iid] += 10.0
            if r.get("guardrail") in ("exception", "error") or r.get("error"):
                item_penalties[iid] += 15.0
            if r.get("guardrail") == "numeric_fallback":
                item_penalties[iid] += 3.0
            if r.get("unsupported_numbers"):
                item_penalties[iid] += len(r.get("unsupported_numbers", [])) * 2.0
            if r.get("mislabeled_numbers"):
                item_penalties[iid] += len(r.get("mislabeled_numbers", [])) * 2.0

    worst_5_ids = sorted(item_penalties.keys(), key=lambda k: item_penalties[k], reverse=True)[:5]
    worst_5 = []
    for wid in worst_5_ids:
        d = item_details[wid]
        worst_5.append({
            "id": wid,
            "penalty_score": item_penalties[wid],
            "category": d.get("category"),
            "tool_selection_correct": d.get("tool_selection_correct"),
            "guardrail": d.get("guardrail"),
            "unsupported_numbers": d.get("unsupported_numbers"),
            "mislabeled_numbers": d.get("mislabeled_numbers"),
            "raw_llm_reply": d.get("raw_llm_reply"),
            "reply": d.get("reply")
        })

    summary_data = {
        "evaluation_date": today_str,
        "model": "qwen2.5:14b",
        "num_runs": num_runs,
        "items_per_run": num_items,
        "total_evaluations": num_runs * num_items,
        "metrics": {
            "tool_selection_accuracy": {
                "target": ">= 90%",
                "mean": f"{mean_tool_acc:.1f}%",
                "min": f"{min_tool_acc:.1f}%",
                "max": f"{max_tool_acc:.1f}%",
                "status": tool_status
            },
            "error_rate": {
                "target": "0%",
                "mean": f"{mean_error_rate:.1f}%",
                "min": f"{min_error_rate:.1f}%",
                "max": f"{max_error_rate:.1f}%",
                "status": error_status
            },
            "final_answer_number_leaks": {
                "target": "0",
                "mean": mean_final_leaks,
                "status": leaks_status
            },
            "final_answer_invalid_citations": {
                "target": "0",
                "mean": mean_final_inv_cit,
                "status": inv_cit_status
            },
            "refusal_accuracy": {
                "target": "100%",
                "mean": f"{mean_refusal:.1f}%",
                "status": refusal_status
            },
            "expected_values_present_rate": {
                "target": "Tracked",
                "mean": f"{mean_ev_rate:.1f}%",
                "min": f"{min_ev_rate:.1f}%",
                "max": f"{max_ev_rate:.1f}%",
                "status": "Reported"
            },
            "raw_unsupported_numbers_caught": {
                "target": "Tracked",
                "mean": mean_raw_unsup,
                "status": "Reported"
            },
            "raw_citation_hallucination_rate": {
                "target": "Tracked",
                "mean": f"{mean_raw_cit_halluc:.1f}%",
                "status": "Reported"
            },
            "fallback_rate": {
                "target": "Tracked",
                "mean": f"{mean_fallback:.1f}%",
                "min": f"{min_fallback:.1f}%",
                "max": f"{max_fallback:.1f}%",
                "status": "Reported"
            },
            "retry_rate": {
                "target": "Tracked",
                "mean": f"{mean_retry:.1f}%",
                "status": "Reported"
            },
            "p50_latency_seconds": {
                "target": "Dilaporkan apa adanya",
                "result": round(global_p50, 2),
                "status": "Reported"
            },
            "p95_latency_seconds": {
                "target": "Dilaporkan apa adanya",
                "result": round(global_p95, 2),
                "status": "Reported"
            }
        },
        "per_run_breakdown": metrics_per_run,
        "worst_5_items": worst_5,
        "raw_runs": all_runs_results
    }

    tool_met_str = f"**{mean_tool_acc:.1f}%**" if mean_tool_acc < 90.0 else f"{mean_tool_acc:.1f}%"
    error_met_str = f"**{mean_error_rate:.1f}%**" if mean_error_rate > 0.0 else f"{mean_error_rate:.1f}%"
    ref_met_str = f"**{mean_refusal:.1f}%**" if mean_refusal < 100.0 else f"{mean_refusal:.1f}%"
    leaks_met_str = f"**{mean_final_leaks:.1f}**" if mean_final_leaks > 0 else f"{mean_final_leaks:.1f}"
    inv_cit_str = f"**{mean_final_inv_cit:.1f}**" if mean_final_inv_cit > 0 else f"{mean_final_inv_cit:.1f}"

    report_md = f"""# AI Assistant Evaluation Report (README.md §11)

**Evaluation Date:** {today_str}  
**Model Under Test:** `qwen2.5:14b` via local Ollama  
**Dataset:** `eval/ai_eval_set.json` (30 Indonesian queries)  
**Repetitions:** {num_runs} runs (total {num_runs * num_items} evaluation turns)

---

## 1. Summary of Benchmark Metrics

| Metric | Target (README §11) | Mean Result | Min - Max | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Tool Selection Accuracy** | >= 90% | {tool_met_str} | {min_tool_acc:.1f}% - {max_tool_acc:.1f}% | {tool_status} |
| **Error Rate** | 0% | {error_met_str} | {min_error_rate:.1f}% - {max_error_rate:.1f}% | {error_status} |
| **Final Answer Number Leaks** | 0 | {leaks_met_str} | - | {leaks_status} |
| **Final Answer Citations Consistent with Verified Corpus** | 0 | {inv_cit_str} | - | {inv_cit_status} |
| **Refusal Accuracy** | 100% | {ref_met_str} | - | {refusal_status} |
| **Expected Values Present Rate** | Tracked | {mean_ev_rate:.1f}% | {min_ev_rate:.1f}% - {max_ev_rate:.1f}% | Reported |
| **Raw Unsupported Numbers Caught** | Tracked | {mean_raw_unsup:.1f} | - | Reported |
| **Raw Citation Hallucination Rate** | Tracked | {mean_raw_cit_halluc:.1f}% | - | Reported |
| **Guardrail Fallback Rate** | Tracked | {mean_fallback:.1f}% | {min_fallback:.1f}% - {max_fallback:.1f}% | Reported |
| **Guardrail Retry Rate** | Tracked | {mean_retry:.1f}% | - | Reported |
| **p50 Latency** | Dilaporkan apa adanya | {global_p50:.2f}s | - | Reported |
| **p95 Latency** | Dilaporkan apa adanya | {global_p95:.2f}s | - | Reported |

---

## 2. 5 Worst Items Analysis

Below are the 5 items that accumulated the most failure penalties across the runs, showing the raw LLM output before the guardrail and the root cause:

"""
    for idx, w in enumerate(worst_5, 1):
        raw_snippet = (w["raw_llm_reply"][:350] + "...") if w.get("raw_llm_reply") else "(No raw reply)"
        report_md += f"""### Item {idx}: `{w['id']}` (Category: {w['category']})
- **Penalty Score:** {w['penalty_score']}
- **Tool Selection Correct:** {w['tool_selection_correct']}
- **Guardrail Final Status:** `{w['guardrail']}`
- **Unsupported Numbers:** `{w['unsupported_numbers']}`
- **Mislabeled Numbers:** `{w['mislabeled_numbers']}`
- **Raw LLM Answer (before guardrail):**
> {raw_snippet}
- **Root Cause & Diagnosis:**
  Question: `{w['id']}` triggered `{w['guardrail']}`. {"The LLM failed to invoke the expected tool." if not w['tool_selection_correct'] else "The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs."}

"""

    return summary_data, report_md


def run_full_eval(item_ids: Optional[List[str]] = None, num_runs: int = 3):
    eval_file = Path(__file__).resolve().parent / "ai_eval_set.json"
    if not eval_file.exists():
        print(f"Eval set not found: {eval_file}")
        sys.exit(1)

    with open(eval_file, "r", encoding="utf-8") as f:
        eval_data = json.load(f)

    all_items = eval_data.get("items", [])
    if item_ids:
        items = [it for it in all_items if it["id"] in item_ids]
    else:
        items = all_items

    print(f"Loaded {len(items)} evaluation items from {eval_file.name}.")

    init_db_pool()
    client = TestClient(app)

    all_runs_results = []

    print(f"\n=======================================================")
    print(f"STARTING EVALUATION ({num_runs} runs x {len(items)} questions = {num_runs * len(items)} inferences)")
    print(f"=======================================================\n")

    for run_idx in range(1, num_runs + 1):
        print(f"\n--- [RUN {run_idx}/{num_runs}] ---")
        run_items = []
        t_start_run = time.time()

        for idx, item in enumerate(items, 1):
            print(f"[{run_idx}.{idx:02d}/{len(items)}] Q: {item['question'][:50]}...", end="", flush=True)
            payload = {
                "messages": [
                    {"role": "user", "content": item["question"]}
                ]
            }

            try:
                res = client.post("/api/v1/chat", json=payload)
                if res.status_code == 200:
                    chat_data = res.json()
                    eval_res = evaluate_item(item, chat_data)
                    run_items.append(eval_res)
                    status_flag = "OK" if eval_res["tool_selection_correct"] and eval_res["refusal_correct"] else "WARN"
                    print(f" -> {status_flag} ({eval_res['latency_seconds']:.2f}s, guardrail={eval_res['guardrail']})")
                else:
                    print(f" -> ERROR HTTP {res.status_code}")
                    run_items.append({
                        "id": item["id"],
                        "category": item["category"],
                        "error": f"HTTP {res.status_code}: {res.text}",
                        "tool_selection_correct": False,
                        "refusal_correct": False if item.get("must_refuse") else True,
                        "guardrail": "error",
                        "unsupported_numbers": [],
                        "latency_seconds": 0.0,
                        "raw_llm_reply": "",
                        "reply": ""
                    })
            except Exception as e:
                print(f" -> EXCEPTION: {e}")
                run_items.append({
                    "id": item["id"],
                    "category": item["category"],
                    "error": str(e),
                    "tool_selection_correct": False,
                    "refusal_correct": False if item.get("must_refuse") else True,
                    "guardrail": "exception",
                    "unsupported_numbers": [],
                    "latency_seconds": 0.0,
                    "raw_llm_reply": "",
                    "reply": ""
                })

        duration_run = time.time() - t_start_run
        print(f"--- RUN {run_idx} COMPLETED in {duration_run:.1f}s ---\n")
        all_runs_results.append(run_items)

    close_db_pool()

    today_str = datetime.now().strftime("%Y%m%d")
    output_dir = Path(__file__).resolve().parent

    summary_data, report_md = compute_metrics_and_report(all_runs_results, len(items), today_str, output_dir)

    results_path = output_dir / f"results_{today_str}.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)
    print(f">> Saved raw results to {results_path}")

    report_path = output_dir / "REPORT.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f">> Wrote report to {report_path}")

    return summary_data


def regenerate_from_existing(results_file_path: Path):
    """Regenerates eval/REPORT.md from an existing results JSON file without invoking LLM."""
    with open(results_file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Load updated eval set to re-evaluate expected values and leaks cleanly
    eval_file = Path(__file__).resolve().parent / "ai_eval_set.json"
    with open(eval_file, "r", encoding="utf-8") as f:
        eval_data = json.load(f)
    items_map = {item["id"]: item for item in eval_data.get("items", [])}

    raw_runs = data.get("raw_runs", [])
    recalculated_runs = []

    for run in raw_runs:
        recalculated_run = []
        for r in run:
            iid = r["id"]
            meta = items_map.get(iid, {})
            reply = r.get("reply", "")
            raw_reply = r.get("raw_llm_reply", reply)

            # Re-evaluate expected values against updated eval set
            ev = meta.get("expected_values", {})
            values_present = {}
            for k, v in ev.items():
                if k == "api_path":
                    continue
                values_present[k] = check_value_in_text(v, reply)
            all_values_present = all(values_present.values()) if values_present else True

            # Re-evaluate final invalid citations
            final_inv_cits = len(re.findall(r"\[REG:[^\]]*\]", reply))

            # Re-evaluate final number leaks
            guardrail = r.get("guardrail", "passed")
            raw_unsupported = r.get("unsupported_numbers", [])
            final_number_leaks = len(raw_unsupported) if guardrail not in ("numeric_fallback",) else 0

            # Re-evaluate tool selection against updated expected tools
            executed_tools = r.get("executed_tools", [])
            expected_tools = meta.get("expected_tools", [])
            if meta.get("must_refuse"):
                tool_selection_correct = len(executed_tools) == 0
            else:
                tool_selection_correct = set(expected_tools).issubset(set(executed_tools)) if expected_tools else True

            item_res = dict(r)
            item_res["tool_selection_correct"] = tool_selection_correct
            item_res["expected_tools"] = expected_tools
            item_res["all_values_present"] = all_values_present
            item_res["values_breakdown"] = values_present
            item_res["final_invalid_citations"] = final_inv_cits
            item_res["final_number_leaks"] = final_number_leaks
            recalculated_run.append(item_res)
        recalculated_runs.append(recalculated_run)

    today_str = data.get("evaluation_date", datetime.now().strftime("%Y%m%d"))
    output_dir = Path(__file__).resolve().parent

    summary_data, report_md = compute_metrics_and_report(
        recalculated_runs,
        len(items_map),
        today_str,
        output_dir
    )

    with open(results_file_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)
    print(f">> Updated {results_file_path}")

    report_path = output_dir / "REPORT.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f">> Wrote report to {report_path}")

    return summary_data, report_md


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--regenerate":
        res_file = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent / "results_20261014.json"
        regenerate_from_existing(res_file)
    else:
        run_full_eval()
