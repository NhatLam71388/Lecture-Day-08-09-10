# Data contract — Lab Day 10

> Đồng bộ với `contracts/data_contract.yaml` (nguồn canonical).

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| `policy_refund_v4` | CSV export từ Policy DB | Chunk stale "14 ngày làm việc" (bản v3); chunk lỗi "Nội dung không rõ ràng:" | `expectation[refund_no_stale_14d_window] FAIL` → halt |
| `sla_p1_2026` | CSV export từ ITSM | effective_date thiếu; chunk mơ hồ "Nội dung không rõ ràng:" | `quarantine_records` tăng; E5 nếu ngày sai format |
| `it_helpdesk_faq` | CSV export từ Helpdesk Wiki | Chunk text rỗng sau strip; duplicate FAQ text | E2 / dedup rule |
| `hr_leave_policy` | CSV export từ HR System | **Version conflict** 2025 vs 2026 (10 ngày vs 12 ngày); eff_date gán nhầm cho bản cũ | E6 `hr_leave_no_stale_10d_annual` → halt |
| `access_control_sop` | CSV export từ IT Security Wiki | Chunk rỗng; duplicate Level 4 description | E7 `access_control_sop_present` → halt nếu thiếu |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| `chunk_id` | string | Có | SHA-256 hash ổn định: `doc_id|chunk_text|seq` — đảm bảo idempotency khi upsert |
| `doc_id` | string | Có | Phải thuộc `ALLOWED_DOC_IDS` (5 nguồn hiện tại) |
| `chunk_text` | string | Có | Sau clean: min 8 ký tự, không prefix noise, không ABAB bloat |
| `effective_date` | date (YYYY-MM-DD) | Có | Đã normalize từ `DD/MM/YYYY` nếu cần; rỗng → quarantine |
| `exported_at` | datetime (ISO 8601) | Có | Dùng để tính freshness — max(exported_at) ghi vào manifest |

---

## 3. Quy tắc quarantine vs drop

Records bị flag chuyển sang `artifacts/quarantine/<run_id>.csv` kèm cột `reason`:

| Reason | Mô tả | Có thể merge lại? |
|--------|-------|-------------------|
| `unknown_doc_id` | doc_id không trong allowlist | Sau khi xác nhận nguồn hợp lệ với data owner |
| `missing_effective_date` | effective_date rỗng | Sau khi điền lại từ nguồn gốc |
| `invalid_effective_date_format` | Format ngày không parse được | Sau khi sửa format |
| `stale_hr_policy_effective_date` | HR eff_date < 2026-01-01 | Không — bản cũ, phải dùng bản 2026 |
| `stale_hr_content_10d` | HR chunk "10 ngày phép năm" dù eff_date ≥ 2026 | Không — gán nhầm ngày cho bản cũ |
| `missing_chunk_text` | chunk_text rỗng | Sau khi lấy lại nội dung từ source |
| `unclear_export_prefix` | Prefix "Nội dung không rõ ràng:" | Sau khi xác nhận và làm sạch nội dung |
| `abab_word_repetition` | Copy-paste ABAB bloat | Sau khi de-dup và sửa nội dung gốc |
| `duplicate_chunk_text` | Nội dung trùng lặp | Không cần — dedup giữ bản đầu |

**Ai approve merge:** Data Owner của từng nguồn phải xác nhận trước khi rerun.

---

## 4. Phiên bản & canonical

| Tài liệu | Canonical | Version hiện tại | Ghi chú |
|----------|-----------|------------------|---------|
| Chính sách hoàn tiền | `data/docs/policy_refund_v4.txt` | v4 | Cửa sổ **7 ngày làm việc** — v3 có "14 ngày" là stale |
| SLA incident P1 | `data/docs/sla_p1_2026.txt` | 2026 | Effective 2026-01-15 |
| IT Helpdesk FAQ | `data/docs/it_helpdesk_faq.txt` | 2026 | Effective 2026-01-20 |
| HR Leave Policy | `data/docs/hr_leave_policy.txt` | 2026 | **12 ngày phép năm** cho < 3 năm KN — bản 2025 là "10 ngày" |
| Access Control SOP | `data/docs/access_control_sop.txt` | 2026 | Level 4 cần IT Manager + CISO |

Source of truth: các file trong `data/docs/` — pipeline export CSV chỉ là lớp staging trước khi embed.
