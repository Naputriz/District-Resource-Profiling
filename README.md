# District Resource Profiling

District Resource Profiling adalah platform web GIS dan asisten AI lokal untuk mengevaluasi profil ketersediaan fasilitas publik di 44 kecamatan DKI Jakarta berdasarkan standar SNI 03-1733-2004 serta regulasi terkait. Seluruh angka dan metrik spasial dihitung secara deterministik oleh spatial engine (PostGIS + Python), sedangkan LLM lokal hanya bertugas memahami pertanyaan, memanggil fungsi-fungsi tersebut, dan menjelaskan hasilnya dengan kutipan dari korpus regulasi yang terverifikasi. Mengintegrasikan data spasial dari OpenStreetMap (OSM) dan data kependudukan dari Badan Pusat Statistik (BPS), sistem ini membantu perencana wilayah menganalisis kecukupan fasilitas dan dampak demografis. Seluruh hasil perhitungan sistem ini merupakan bahan analisis dan simulasi, bukan dokumen keputusan izin resmi.

Status: dalam pengembangan. Modul ditambahkan bertahap lewat pull request.

## Tim Pengembang

| Nama | Peran |
|---|---|
| Novan Agung Wicaksono | Lead System Architect & Backend Engineer |
| Nabil Putra Nurfariz | GIS Fullstack & Data Pipeline Engineer |
| Muhammad Dhiya'ulhaq | AI & RAG Engineer |

## Lisensi dan Atribusi

- Data fasilitas © kontributor OpenStreetMap, lisensi ODbL.
- Data penduduk: Badan Pusat Statistik.
- Teks regulasi: dokumen publik JDIH dan BSN.
- Hasil sistem ini adalah bahan analisis, bukan dokumen resmi pemerintah.
