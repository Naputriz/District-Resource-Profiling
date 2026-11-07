# Sumber Data Batas Wilayah Kecamatan DKI Jakarta

- **42 kecamatan**: GeoJSON dari https://raw.githubusercontent.com/SakifAbdillah/jakartaKecamatanGeoJSON/master/kecamatan.geojson (lihat `pipeline/update_real_boundaries.py`).
- **Kepulauan Seribu Selatan & Utara**: OpenStreetMap relation 5802402 dan 5802411 (via Nominatim, diambil 2026-11-06), © OpenStreetMap contributors, lisensi ODbL.

| Nama | Relasi OSM | Jumlah Poligon | Luas Poligon (km²) | Luas BPS (km²) | Rasio |
|---|---|---|---|---|---|
| Kepulauan Seribu Selatan | 5802402 | 22 | 3.98 | 1.13 | 3.52x |
| Kepulauan Seribu Utara | 5802411 | 6 | 0.97 | 9.57 | 0.10x |

Catatan: luas poligon OSM berbeda dengan luas BPS; data BPS masih TODO-VERIFY, perlu dicek ke publikasi resmi.

Perhatian: `pipeline/update_real_boundaries.py` hanya menulis 42 kecamatan dari sumber pertama. Jika dijalankan ulang, dua fitur Kepulauan Seribu di atas akan hilang dan harus ditambahkan kembali.
