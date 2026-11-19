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
| **Expected Values Present Rate** | Tracked | 88.9% | 86.7% - 90.0% | Reported |
| **Raw Unsupported Numbers Caught** | Tracked | 0.3 | - | Reported |
| **Raw Citation Hallucination Rate** | Tracked | 34.4% | - | Reported |
| **Guardrail Fallback Rate** | Tracked | 1.1% | 0.0% - 3.3% | Reported |
| **Guardrail Retry Rate** | Tracked | 1.1% | - | Reported |
| **p50 Latency** | Dilaporkan apa adanya | 3.21s | - | Reported |
| **p95 Latency** | Dilaporkan apa adanya | 16.06s | - | Reported |

---

## 2. 5 Worst Items Analysis

Below are the 5 items that accumulated the most failure penalties across the runs, showing the raw LLM output before the guardrail and the root cause:

### Item 1: `scorecard_senen_composite` (Category: scorecard)
- **Penalty Score:** 5.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `numeric_fallback`
- **Unsupported Numbers:** `['153']`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor indeks kecukupan fasilitas di Kecamatan Senen adalah **42.2**.

Berikut rincian skor pilar-pilarnya:
- Pilar 1: Kesehatan & Keselamatan (lifeline_health) = 60.0
- Pilar 2: Pendidikan (education) = 20.85

Pilar Ruang Hidup dan Mobilitas tidak dihitung dalam skor komposit karena tidak ada jenis fasilitas yang dinilai, sehingga bobot pilar lainny...
- **Root Cause & Diagnosis:**
  Question: `scorecard_senen_composite` triggered `numeric_fallback`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 2: `scorecard_tebet_composite` (Category: scorecard)
- **Penalty Score:** 0.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `passed`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor indeks kecukupan fasilitas di Kecamatan Tebet adalah 54.61. Skor ini merupakan hasil dari penilaian pilar kesehatan dan keselamatan (79.17) serta pendidikan (25.14), karena data untuk pilar ruang hidup dan mobilitas belum lengkap sehingga tidak dihitung dalam skor komposit.

Berikut adalah detail skor untuk setiap jenis fasilitas yang dinilai:...
- **Root Cause & Diagnosis:**
  Question: `scorecard_tebet_composite` triggered `passed`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 3: `scorecard_tebet_health` (Category: pillar)
- **Penalty Score:** 0.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `passed`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor pilar kesehatan di Kecamatan Tebet adalah 79.17%. Pilar ini mencakup tiga jenis fasilitas: pos_damkar, puskesmas_kecamatan, dan puskesmas_kelurahan.

- **Pos Damkar**: Skor sempurna dengan 2 unit yang diperlukan dan ada 2 unit yang tersedia.
- **Puskesmas Kecamatan**: Ada defisit satu unit (kebutuhan: 2 unit, eksisting: 1 unit).
- **Puskesmas ...
- **Root Cause & Diagnosis:**
  Question: `scorecard_tebet_health` triggered `passed`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 4: `scorecard_gambir_composite` (Category: scorecard)
- **Penalty Score:** 0.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `passed`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor indeks kecukupan fasilitas untuk Kecamatan Gambir adalah 65.2. Skor ini merupakan hasil dari penilaian pilar kesehatan dan keselamatan serta pendidikan, karena data untuk pilar ruang hidup dan mobilitas tidak tersedia sehingga tidak dihitung dalam skor komposit.

Berikut rincian skor pilar yang dinilai:

- **Pilar 1: Kesehatan & Keselamatan** ...
- **Root Cause & Diagnosis:**
  Question: `scorecard_gambir_composite` triggered `passed`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 5: `scorecard_gambir_education` (Category: pillar)
- **Penalty Score:** 0.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `retried`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor pilar pendidikan di Kecamatan Gambir adalah **23.43**.

Informasi lebih lanjut:
- Skor ini didasarkan pada standar yang ditentukan oleh SNI 03-1733-2004.
- Defisit unit fasilitas pendidikan di Kecamatan Gambir mencakup sekolah dasar, sekolah menengah atas, sekolah menengah pertama, dan taman kanak-kanak. Total kebutuhan adalah 157 unit (60 SD ...
- **Root Cause & Diagnosis:**
  Question: `scorecard_gambir_education` triggered `retried`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

