#!/usr/bin/env python3
import os
import psycopg2
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
    port=int(os.getenv("POSTGRES_PORT", "5432")),
    dbname=os.getenv("POSTGRES_DB", "district_profiling"),
    user=os.getenv("POSTGRES_USER", "postgres"),
    password=os.environ["POSTGRES_PASSWORD"]
)

with conn.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute("SELECT COUNT(*) as cnt FROM kecamatan;")
    k_cnt = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM public_facilities;")
    f_cnt = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM regulatory_standards;")
    s_cnt = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM regulatory_chunks;")
    c_cnt = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM district_compliance_scores;")
    sc_cnt = cur.fetchone()["cnt"]

print(f"DATABASE VERIFICATION:")
print(f" - Kecamatan: {k_cnt}")
print(f" - Facilities: {f_cnt}")
print(f" - Regulatory Standards: {s_cnt}")
print(f" - Regulatory Chunks: {c_cnt}")
print(f" - Compliance Scores: {sc_cnt}")

conn.close()
