# Kiến trúc pipeline — Lab Day 10

**Nhóm:** Lab Day 10 — Data Pipeline & Observability  
**Cập nhật:** 2026-06-10

---

## 1. Sơ đồ luồng

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          ETL PIPELINE — Day 10                          │
└─────────────────────────────────────────────────────────────────────────┘

  data/raw/policy_export_dirty.csv
          │
          ▼  [INGEST — load_raw_csv]
   raw_records (247 rows)          ← ghi run_id, raw_records vào log
          │
          ▼  [TRANSFORM — clean_rows]
   ┌──────┴──────────────────────────────────────────┐
   │  Rule 1: allowlist doc_id                        │──→ quarantine/ (unknown_doc_id)
   │  Rule 2: normalize effective_date (ISO)          │──→ quarantine/ (missing/invalid date)
   │  Rule 3: HR stale date (< 2026-01-01)            │──→ quarantine/ (stale_hr_policy_effective_date)
   │  Rule 4*: HR stale content "10 ngày phép năm"    │──→ quarantine/ (stale_hr_content_10d)
   │  Rule 5: empty chunk_text                        │──→ quarantine/ (missing_chunk_text)
   │  Rule 6*: "Nội dung không rõ ràng:" prefix       │──→ quarantine/ (unclear_export_prefix)
   │  Rule 7*: ABAB word repetition                   │──→ quarantine/ (abab_word_repetition)
   │  Rule 8: deduplicate chunk_text                  │──→ quarantine/ (duplicate_chunk_text)
   │  Rule 9: fix stale refund 14→7 ngày              │
   └──────────────────────────────────────────────────┘
          │  (* = rule mới thêm bởi nhóm)
          ▼
   cleaned_records                 ← artifacts/cleaned/cleaned_<run_id>.csv
          │                           ghi cleaned_records, quarantine_records
          ▼  [VALIDATE — run_expectations]
   ┌────────────────────────────────────────────────────────┐
   │  E1: min_one_row (halt)                                │
   │  E2: no_empty_doc_id (halt)                           │
   │  E3: refund_no_stale_14d_window (halt)                │
   │  E4: chunk_min_length_8 (warn)                        │
   │  E5: effective_date_iso_yyyy_mm_dd (halt)             │
   │  E6: hr_leave_no_stale_10d_annual (halt)              │
   │  E7*: access_control_sop_present (halt)               │
   │  E8*: no_abab_word_repetition (warn)                  │
   └────────────────────────────────────────────────────────┘
          │  HALT nếu severity=halt fails
          ▼  (nếu pass)
   [EMBED — chromadb upsert]
          │  upsert theo chunk_id (idempotent)
          │  prune id lạc hậu khỏi collection
          ▼
   ChromaDB collection: day10_kb     ← CHROMA_DB_PATH/day10_kb
          │
          ▼  [MANIFEST + FRESHNESS]
   artifacts/manifests/manifest_<run_id>.json
          │  freshness_check: latest_exported_at vs SLA 24h
          ▼
   Serving — Day 08/09 agent đọc từ collection này
```

**Điểm đo freshness:** `latest_exported_at` trong manifest so với `now` (SLA 24h).  
**run_id:** UTC timestamp hoặc tên tùy chỉnh (`--run-id inject-bad`), ghi vào log + manifest + metadata mỗi chunk.  
**Quarantine:** không xóa — lưu vào `artifacts/quarantine/<run_id>.csv` để audit.

---

## 2. Ranh giới trách nhiệm

| Thành phần | Input | Output | Owner nhóm |
|------------|-------|--------|--------------|
| Ingest | `data/raw/policy_export_dirty.csv` | List[Dict] rows | Ingestion Owner |
| Transform | List[Dict] rows | (cleaned, quarantine) | Cleaning / Quality Owner |
| Quality | cleaned List[Dict] | (results, halt: bool) | Cleaning / Quality Owner |
| Embed | `artifacts/cleaned/*.csv` | ChromaDB upsert + prune | Embed Owner |
| Monitor | `artifacts/manifests/*.json` | PASS/WARN/FAIL + detail | Monitoring / Docs Owner |

---

## 3. Idempotency & rerun

Pipeline embed theo `chunk_id` ổn định (hash SHA-256 từ `doc_id|chunk_text|seq`):
- **Upsert** theo `chunk_id` → rerun 2 lần không tạo thêm bản ghi.
- **Prune** sau mỗi run: xóa vector id có trong collection nhưng không còn trong cleaned CSV hiện tại (`embed_prune_removed` trong log).
- Kết quả: index luôn là **snapshot publish** của cleaned, không tích lũy id lạc hậu.

---

## 4. Liên hệ Day 09

Pipeline này sử dụng cùng bộ `data/docs/` với Day 09 nhưng qua lớp ETL/cleaning trước khi embed:
- Day 09: embed trực tiếp từ `data/docs/*.txt`
- Day 10: export raw CSV → clean → validate → embed vào **collection riêng** `day10_kb`

Agent Day 09 đọc collection riêng của nó; Day 10 tạo collection `day10_kb` mới có thể feed lại agent Day 09 nếu cần dữ liệu đã validate.

---

## 5. Rủi ro đã biết

- **Freshness FAIL bình thường**: CSV mẫu có `exported_at` cũ (2026-04-xx) — data "stale" ≥24h so với thời điểm chạy pipeline (2026-06-10). Giải thích trong runbook.
- **access_control_sop row 217**: eff_date "25/03/2025" (DMY format) được parse tự động sang "2025-03-25" — phụ thuộc regex `_DMY_SLASH`.
- **ABAB detection**: false positive có thể xảy ra với văn bản chứa thành ngữ lặp tự nhiên; ngưỡng hiện tại (4 từ ABAB) phù hợp với corpus nhỏ này.
