"""Pengujian beban dan latensi untuk endpoint API District Resource Profiling.

Skrip ini menguji performa endpoint deterministik (kesehatan, data kecamatan,
blank spot, simulasi what-if, dan pencarian regulasi RAG) menggunakan thread pool
serta opsi pengujian chat secara sekuensial.

Penggunaan:
    python load_test.py [--base-url http://127.0.0.1:8000] [--requests 200] [--concurrency 10] [--chat] [--out hasil.json]
"""

import argparse
import concurrent.futures
import json
import math
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx


def calculate_percentiles(sorted_data: List[float]) -> Dict[str, float]:
    """Menghitung min, p50, p95, p99, dan max dari data yang sudah terurut."""
    if not sorted_data:
        return {"min": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

    n = len(sorted_data)
    if n == 1:
        val = sorted_data[0]
        return {"min": val, "p50": val, "p95": val, "p99": val, "max": val}

    def percentile(p: float) -> float:
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        d0 = sorted_data[int(f)] * (c - k)
        d1 = sorted_data[int(c)] * (k - f)
        return d0 + d1

    return {
        "min": sorted_data[0],
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": sorted_data[-1],
    }


def execute_request(
    client: httpx.Client,
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]],
    timeout: float = 30.0,
) -> Tuple[bool, float, Optional[str]]:
    """Menjalankan satu HTTP request dan mencatat durasi serta status keberhasilan."""
    start_time = time.perf_counter()
    try:
        if method == "GET":
            response = client.get(url, timeout=timeout)
        elif method == "POST":
            response = client.post(url, json=payload, timeout=timeout)
        else:
            raise ValueError(f"Metode HTTP tidak didukung: {method}")

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        is_success = 200 <= response.status_code < 300

        canonical_body: Optional[str] = None
        if is_success:
            try:
                body_json = response.json()
                canonical_body = json.dumps(body_json, sort_keys=True)
            except Exception:
                canonical_body = response.text

        return is_success, latency_ms, canonical_body
    except Exception:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return False, latency_ms, None


def run_deterministic_benchmark(
    base_url: str,
    num_requests: int,
    concurrency: int,
) -> List[Dict[str, Any]]:
    """Menjalankan pengujian beban terhadap endpoint deterministik."""
    endpoints_config = [
        {
            "name": "GET /health",
            "method": "GET",
            "path": "/health",
            "json": None,
            "check_determinism": False,
        },
        {
            "name": "GET /api/v1/districts",
            "method": "GET",
            "path": "/api/v1/districts",
            "json": None,
            "check_determinism": False,
        },
        {
            "name": "GET /api/v1/districts/31.71.09",
            "method": "GET",
            "path": "/api/v1/districts/31.71.09",
            "json": None,
            "check_determinism": True,
        },
        {
            "name": "GET /api/v1/spatial/blank-spots?district_code=31.72.08&facility_type=puskesmas_kelurahan",
            "method": "GET",
            "path": "/api/v1/spatial/blank-spots?district_code=31.72.08&facility_type=puskesmas_kelurahan",
            "json": None,
            "check_determinism": False,
        },
        {
            "name": "POST /api/v1/simulation/what-if",
            "method": "POST",
            "path": "/api/v1/simulation/what-if",
            "json": {"district_code": "31.71.09", "population_shock_percent": 30},
            "check_determinism": True,
        },
        {
            "name": "POST /api/v1/rag/search",
            "method": "POST",
            "path": "/api/v1/rag/search",
            "json": {"query": "radius pelayanan sekolah dasar"},
            "check_determinism": False,
        },
    ]

    limits = httpx.Limits(
        max_connections=max(concurrency * 2, 20),
        max_keepalive_connections=max(concurrency, 10),
    )

    results: List[Dict[str, Any]] = []

    with httpx.Client(limits=limits) as client:
        for ep in endpoints_config:
            full_url = f"{base_url.rstrip('/')}{ep['path']}"

            # Satu warm-up request per endpoint sebelum pencatatan
            try:
                if ep["method"] == "GET":
                    client.get(full_url, timeout=30.0)
                else:
                    client.post(full_url, json=ep["json"], timeout=30.0)
            except Exception:
                pass

            wall_start = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [
                    executor.submit(
                        execute_request,
                        client,
                        ep["method"],
                        full_url,
                        ep["json"],
                    )
                    for _ in range(num_requests)
                ]
                raw_outcomes = [f.result() for f in concurrent.futures.as_completed(futures)]
            wall_duration = time.perf_counter() - wall_start

            total = len(raw_outcomes)
            errors = sum(1 for is_success, _, _ in raw_outcomes if not is_success)
            error_pct = (errors / total * 100.0) if total > 0 else 0.0

            latencies = sorted(lat for _, lat, _ in raw_outcomes)
            stats = calculate_percentiles(latencies)
            throughput = (total / wall_duration) if wall_duration > 0 else 0.0

            if ep["check_determinism"]:
                bodies = [b for is_success, _, b in raw_outcomes if is_success and b is not None]
                if bodies and len(set(bodies)) == 1:
                    determinism = "yes"
                else:
                    determinism = "no"
            else:
                determinism = "n/a"

            # PASS jika error 0%, p95 < 2000 ms, dan (bila dicek) respons identik
            deterministic_ok = determinism != "no"
            status = "PASS" if (error_pct == 0.0 and stats["p95"] < 2000.0 and deterministic_ok) else "FAIL"

            results.append({
                "endpoint": ep["name"],
                "total": total,
                "errors": errors,
                "error_pct": error_pct,
                "min_ms": stats["min"],
                "p50_ms": stats["p50"],
                "p95_ms": stats["p95"],
                "p99_ms": stats["p99"],
                "max_ms": stats["max"],
                "throughput_rps": throughput,
                "deterministic": determinism,
                "status": status,
            })

    return results


def run_chat_benchmark(base_url: str) -> List[Dict[str, Any]]:
    """Menjalankan pengujian sekuensial untuk endpoint chat."""
    chat_url = f"{base_url.rstrip('/')}/api/v1/chat"
    payload = {
        "messages": [
            {"role": "user", "content": "Bagaimana skor fasilitas kesehatan di Tebet?"}
        ]
    }

    chat_results: List[Dict[str, Any]] = []

    with httpx.Client() as client:
        for idx in range(1, 4):
            start_time = time.perf_counter()
            try:
                response = client.post(chat_url, json=payload, timeout=180.0)
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                is_success = 200 <= response.status_code < 300
                if is_success:
                    body = response.json()
                    answer_mode = body.get("answer_mode", "-")
                    rounds_used = body.get("rounds_used", "-")
                    unsupported = body.get("unsupported_numbers", [])
                    unsupported_count = len(unsupported) if isinstance(unsupported, list) else unsupported
                else:
                    answer_mode = f"HTTP_{response.status_code}"
                    rounds_used = "-"
                    unsupported_count = "-"
            except Exception as e:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                answer_mode = f"EXCEPTION: {type(e).__name__}"
                rounds_used = "-"
                unsupported_count = "-"

            chat_results.append({
                "run": idx,
                "latency_ms": latency_ms,
                "answer_mode": answer_mode,
                "rounds_used": rounds_used,
                "unsupported_numbers_count": unsupported_count,
            })

    return chat_results


def print_results_table(results: List[Dict[str, Any]]) -> None:
    """Mencetak tabel hasil benchmark dalam format teks terstruktur."""
    headers = [
        "Endpoint", "Total", "Errors", "Err %", "Min (ms)",
        "p50 (ms)", "p95 (ms)", "p99 (ms)", "Max (ms)", "Req/s", "Det.", "Status"
    ]

    rows = []
    for r in results:
        rows.append([
            r["endpoint"],
            str(r["total"]),
            str(r["errors"]),
            f"{r['error_pct']:.1f}%",
            f"{r['min_ms']:.2f}",
            f"{r['p50_ms']:.2f}",
            f"{r['p95_ms']:.2f}",
            f"{r['p99_ms']:.2f}",
            f"{r['max_ms']:.2f}",
            f"{r['throughput_rps']:.1f}",
            r["deterministic"],
            r["status"],
        ])

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    def make_row_str(vals: List[str]) -> str:
        formatted = []
        for i, v in enumerate(vals):
            # Endpoint rata kiri, kolom lainnya rata kanan (kecuali Det dan Status)
            if i == 0:
                formatted.append(v.ljust(col_widths[i]))
            elif i in (10, 11):
                formatted.append(v.center(col_widths[i]))
            else:
                formatted.append(v.rjust(col_widths[i]))
        return " | ".join(formatted)

    separator = "-+-".join("-" * w for w in col_widths)

    print("\n" + make_row_str(headers))
    print(separator)
    for row in rows:
        print(make_row_str(row))
    print(separator + "\n")


def print_chat_results(chat_results: List[Dict[str, Any]]) -> None:
    """Mencetak ringkasan hasil benchmark chat."""
    print("Pengujian Chat (Sekuensial 3x, timeout 180s):")
    for cr in chat_results:
        print(
            f"  Run {cr['run']}: Latency = {cr['latency_ms']:.2f} ms | "
            f"Mode = {cr['answer_mode']} | "
            f"Rounds = {cr['rounds_used']} | "
            f"Unsupported Numbers = {cr['unsupported_numbers_count']}"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pengujian beban dan latensi endpoint District Resource Profiling."
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL API (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=200,
        help="Jumlah permintaan per endpoint (default: 200)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Jumlah worker konkuren (default: 10)",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Jalankan juga pengujian sekuensial untuk endpoint /api/v1/chat",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Path opsional untuk menyimpan hasil dalam format JSON",
    )

    args = parser.parse_args()

    print(
        f"Memulai pengujian beban: base_url={args.base_url}, "
        f"requests={args.requests}, concurrency={args.concurrency}"
    )

    results = run_deterministic_benchmark(
        base_url=args.base_url,
        num_requests=args.requests,
        concurrency=args.concurrency,
    )

    print_results_table(results)

    all_passed = all(r["status"] == "PASS" for r in results)

    chat_results = None
    if args.chat:
        chat_results = run_chat_benchmark(base_url=args.base_url)
        print_chat_results(chat_results)

    print("Hasil Akhir Per Endpoint:")
    for r in results:
        print(f"  {r['endpoint']}: {r['status']} (p95={r['p95_ms']:.2f}ms, error_pct={r['error_pct']:.1f}%, det={r['deterministic']})")

    overall_status = "PASS" if all_passed else "FAIL"
    print(f"\nStatus Keseluruhan Endpoint Deterministik: {overall_status}")

    if args.out:
        output_data = {
            "config": {
                "base_url": args.base_url,
                "requests": args.requests,
                "concurrency": args.concurrency,
                "chat": args.chat,
            },
            "deterministic_endpoints": results,
            "chat_benchmark": chat_results,
            "overall_status": overall_status,
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)
        print(f"Hasil disimpan ke: {args.out}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
