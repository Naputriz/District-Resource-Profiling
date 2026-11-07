# AI Assistant Evaluation Report (README.md §11)

**Evaluation Date:** 20261015  
**Model Under Test:** `qwen2.5:14b` via local Ollama  
**Dataset:** `eval/ai_eval_set.json` (30 Indonesian queries)  
**Repetitions:** 3 runs (total 90 evaluation turns)

---

## 1. Summary of Benchmark Metrics

| Metric | Target (README §11) | Mean Result | Min - Max | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Tool Selection Accuracy** | >= 90% | 100.0% | 100.0% - 100.0% | PASS |
| **Error Rate** | 0% | 0.0% | 0.0% - 0.0% | PASS |
| **Final Answer Number Leaks** | 0 | 0.0 | - | PASS |
| **Final Answer Citations Consistent with Verified Corpus** | 0 | 0.0 | - | PASS |
| **Refusal Accuracy** | 100% | 100.0% | - | PASS |
| **Expected Values Present Rate** | Tracked | 90.0% | 90.0% - 90.0% | Reported |
| **Raw Unsupported Numbers Caught** | Tracked | 1.0 | - | Reported |
| **Raw Citation Hallucination Rate** | Tracked | 52.2% | - | Reported |
| **Guardrail Fallback Rate** | Tracked | 10.0% | 6.7% - 16.7% | Reported |
| **Guardrail Retry Rate** | Tracked | 1.1% | - | Reported |
| **p50 Latency** | Dilaporkan apa adanya | 8.69s | - | Reported |
| **p95 Latency** | Dilaporkan apa adanya | 22.70s | - | Reported |

---

## 2. 5 Worst Items Analysis

Below are the 5 items that accumulated the most failure penalties across the runs, showing the raw LLM output before the guardrail and the root cause:

### Item 1: `scorecard_gambir_composite` (Category: scorecard)
- **Penalty Score:** 22.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `passed`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor indeks kecukupan fasilitas untuk Kecamatan Gambir adalah 65.2. Skor ini merupakan hasil komposit dari pilar yang dinilai, yaitu kesehatan dan keselamatan (100%) serta pendidikan (23.43%). Pilar ruang hidup dan mobilitas tidak dihitung dalam skor komposit karena tidak ada jenis fasilitas yang dinilai.

Berikut adalah detail skor untuk setiap pi...
- **Root Cause & Diagnosis:**
  Question: `scorecard_gambir_composite` triggered `passed`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 2: `scorecard_gambir_education` (Category: pillar)
- **Penalty Score:** 22.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `numeric_fallback`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[{'number': '60', 'expected_label': 'defisit:sekolah_dasar (49.0)', 'found_label': 'other_facility_metric'}, {'number': '20', 'expected_label': 'defisit:sekolah_menengah_atas (12.0)', 'found_label': 'other_facility_metric'}, {'number': '20', 'expected_label': 'defisit:sekolah_menengah_pertama (15.0)', 'found_label': 'other_facility_metric'}, {'number': '77', 'expected_label': 'defisit:taman_kanak_kanak (69.0)', 'found_label': 'other_facility_metric'}]`
- **Raw LLM Answer (before guardrail):**
> Skor pilar pendidikan di Kecamatan Gambir adalah 23.43. Ini menunjukkan bahwa kecamatan ini memiliki ketersediaan fasilitas pendidikan yang rendah dibandingkan dengan standar yang ditentukan oleh SNI 03-1733-2004 dan Perda RDTR DKI Jakarta No. 31/2022.

Beberapa indikator penting untuk pilar pendidikan di Kecamatan Gambir meliputi:
- Defisit sekola...
- **Root Cause & Diagnosis:**
  Question: `scorecard_gambir_education` triggered `numeric_fallback`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 3: `scorecard_cilandak_education` (Category: pillar)
- **Penalty Score:** 11.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `passed`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor pilar pendidikan di Kecamatan Cilandak adalah 32.69. Skor ini mencerminkan ketersediaan fasilitas pendidikan seperti sekolah dasar, sekolah menengah atas, sekolah menengah pertama, dan taman kanak-kanak.

Berikut detailnya:

1. **Sekolah Dasar**: 
   - Kebutuhan: 132 unit
   - Ada saat ini: 42 unit
   - Defisit: -90 unit (kurang dari kebutuhan...
- **Root Cause & Diagnosis:**
  Question: `scorecard_cilandak_education` triggered `passed`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 4: `blank_spot_seribu_selatan` (Category: blank_spot)
- **Penalty Score:** 9.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `numeric_fallback`
- **Unsupported Numbers:** `['03', '-1733', '-2004']`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Hasil analisis menunjukkan bahwa seluruh wilayah Kepulauan Seribu Selatan tidak terlayani fasilitas puskesmas kelurahan dalam radius standar SNI (1500 meter). Cakupan layanan saat ini adalah 0%, dengan luas area yang tidak terlayani sebesar 42.48 km² dari total luas wilayah kecamatan tersebut.

Ini menunjukkan bahwa seluruh wilayah Kepulauan Seribu...
- **Root Cause & Diagnosis:**
  Question: `blank_spot_seribu_selatan` triggered `numeric_fallback`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

### Item 5: `scorecard_cilandak_composite` (Category: scorecard)
- **Penalty Score:** 7.0
- **Tool Selection Correct:** True
- **Guardrail Final Status:** `passed`
- **Unsupported Numbers:** `[]`
- **Mislabeled Numbers:** `[]`
- **Raw LLM Answer (before guardrail):**
> Skor indeks kecukupan fasilitas untuk Kecamatan Cilandak adalah **44.41**.

Informasi tambahan:
- Skor ini didasarkan pada data yang tersedia dan diperoleh dari database.
- Pilar ruang hidup (urban livability) tidak dihitung dalam skor komposit karena tidak ada jenis fasilitas yang dinilai.
- Bobot pilar yang memenuhi syarat telah diskalakan secara...
- **Root Cause & Diagnosis:**
  Question: `scorecard_cilandak_composite` triggered `passed`. The tool was correctly invoked, but the generated textual response introduced numbers or labels not backed by the database outputs.

