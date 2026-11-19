# AI Assistant Evaluation Report (README.md §11)

**Evaluation Date:** 20261106  
**Model Under Test:** `qwen2.5:14b` via local Ollama  
**Dataset:** `eval/ai_eval_set.json` (30 Indonesian queries)  
**Repetitions:** 3 runs (total 90 evaluation turns)

> **Catatan data:** run 14-15 Oktober memakai geometri lama Kepulauan Seribu Selatan (31.01.01). Sejak poligon OpenStreetMap ditambahkan (lihat `pipeline/data/boundaries/SOURCES.md`), nilai harapan item `scorecard_seribu_selatan_composite`, `scorecard_seribu_selatan_health` dan `blank_spot_seribu_selatan` di `eval/ai_eval_set.json` sudah tidak sesuai dengan database dan perlu diperbarui sebelum evaluasi berikutnya.

---

## 1. Summary of Benchmark Metrics

| Metric | Target (README §11) | Mean Result | Min - Max | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Tool Selection Accuracy** | >= 90% | 100.0% | 100.0% - 100.0% | PASS |
| **Error Rate** | 0% | 0.0% | 0.0% - 0.0% | PASS |
| **Final Answer Number Leaks** | 0 | 0.0 | - | PASS |
| **Final Answer Citations Consistent with Verified Corpus** | 0 | 0.0 | - | PASS |
| **Refusal Accuracy** | 100% | 100.0% | - | PASS |
| **Expected Values Present Rate** | Tracked | 91.1% | 90.0% - 93.3% | Reported |
| **Raw Unsupported Numbers Caught** | Tracked | 0.0 | - | Reported |
| **Raw Citation Hallucination Rate** | Tracked | 35.6% | - | Reported |
| **Guardrail Fallback Rate** | Tracked | 0.0% | 0.0% - 0.0% | Reported |
| **Guardrail Retry Rate** | Tracked | 1.1% | - | Reported |
| **p50 Latency** | Dilaporkan apa adanya | 5.81s | - | Reported |
| **p95 Latency** | Dilaporkan apa adanya | 18.36s | - | Reported |

---

## 2. 5 Worst Items Analysis

Below are the 5 items that accumulated the most failure penalties across the runs, showing the raw LLM output before the guardrail and the root cause:

### Item 1: `scorecard_tebet_composite` (Category: scorecard)
- **Penalty Score:** 0.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `passed`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor indeks kecukupan fasilitas di Kecamatan Tebet adalah 54.61. Skor ini merupakan hasil dari penilaian pilar kesehatan dan keselamatan (79.17) serta pendidikan (25.14), karena data untuk pilar ruang hidup dan mobilitas belum lengkap sehingga tidak termasuk dalam perhitungan skor komposit.

Berikut adalah detail skor untuk setiap jenis fasilitas y...
- **Root Cause & Diagnosis:**
  Question: `scorecard_tebet_composite` triggered `passed`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 2: `scorecard_tebet_health` (Category: pillar)
- **Penalty Score:** 0.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `passed`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor pilar kesehatan di Kecamatan Tebet adalah 79.17%. Pilar ini mencakup tiga jenis fasilitas: pos_damkar, puskesmas_kecamatan, dan puskesmas_kelurahan.

- **Pos Damkar**: Skor sempurna dengan 2 unit yang diperlukan sudah ada (defisit = 0).
- **Puskesmas Kecamatan**: Memiliki 1 dari 2 unit yang dibutuhkan (defisit = -1, atau kebutuhan <N> unit, ek...
- **Root Cause & Diagnosis:**
  Question: `scorecard_tebet_health` triggered `passed`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 3: `scorecard_gambir_composite` (Category: scorecard)
- **Penalty Score:** 0.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `passed`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor indeks kecukupan fasilitas untuk Kecamatan Gambir adalah 65.2. Skor ini mencerminkan ketersediaan dan layanan dari empat pilar utama: kesehatan & keselamatan, pendidikan, mobilitas & aksesibilitas, serta ruang hidup & rekreasi.

Namun, perlu diperhatikan bahwa skor komposit tidak mencakup Pilar 3 (Ruang Hidup) dan Pilar 4 (Mobilitas & Aksesibi...
- **Root Cause & Diagnosis:**
  Question: `scorecard_gambir_composite` triggered `passed`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 4: `scorecard_gambir_education` (Category: pillar)
- **Penalty Score:** 0.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `passed`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor pilar pendidikan di Kecamatan Gambir adalah 23.43%. Ini berarti kecamatan tersebut memiliki tingkat ketercapaian standar fasilitas pendidikan yang rendah, dengan defisit unit sekolah dasar sebanyak 49 unit (kebutuhan: 60 unit, eksisting: 11 unit), sekolah menengah atas sebanyak 12 unit (kebutuhan: 20 unit, eksisting: 8 unit), dan taman kanak-k...
- **Root Cause & Diagnosis:**
  Question: `scorecard_gambir_education` triggered `passed`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 5: `scorecard_cilandak_composite` (Category: scorecard)
- **Penalty Score:** 0.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `passed`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor indeks kecukupan fasilitas untuk Kecamatan Cilandak adalah 44.41, dengan detail sebagai berikut:

- **Pilar Kesehatan & Keselamatan (Lifeline Health)**: Skor 54.17.
- **Pilar Pendidikan**: Skor 32.69.
- **Pilar Ruang Hidup & Rekreasi (Urban Livability)**: Data cakupan rendah, tidak dihitung dalam skor komposit.
- **Pilar Mobilitas & Aksesibili...
- **Root Cause & Diagnosis:**
  Question: `scorecard_cilandak_composite` triggered `passed`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

