# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** Lab Day 10  
**Thành viên:**
| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| Lam | All roles (solo) | vanhung71388@gmail.com |

**Ngày nộp:** 2026-06-10  
**Repo:** d:/AI_20K/Lecture-Day-08-09-10  
**Độ dài khuyến nghị:** 600–1000 từ

---

## 1. Pipeline tổng quan

**Nguồn raw:** `data/raw/policy_export_dirty.csv` — 247 dòng, export từ 5 hệ thống nguồn (policy_refund_v4, sla_p1_2026, it_helpdesk_faq, hr_leave_policy, access_control_sop) cùng nhiều doc_id không hợp lệ (invalid_doc_*, legacy_catalog_xyz_zzz, security_policy, data_privacy_guideline).

**Chuỗi lệnh end-to-end:**
```bash
cd day10/lab
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python etl_pipeline.py run
```

**run_id:** lấy từ UTC timestamp trong log — dòng đầu `run_id=2026-06-10T...`. Cũng có trong tên file log/manifest/quarantine/cleaned.

**Phát hiện pipeline gap chính:**
1. `access_control_sop` thiếu trong `ALLOWED_DOC_IDS` → toàn bộ 9 rows bị quarantine với lý do `unknown_doc_id` → agent không có dữ liệu để trả lời gq_d10_10.
2. HR rows với `effective_date ≥ 2026-01-01` nhưng nội dung "10 ngày phép năm" (bản HR 2025 gán ngày sai) → lọt qua baseline rule 3 → E6 expectation HALT.

---

## 2. Cleaning & expectation

### 2a. Bảng metric_impact (bắt buộc — chống trivial)

| Rule / Expectation mới | Trước (số liệu) | Sau / khi inject (số liệu) | Chứng cứ |
|------------------------|------------------|-----------------------------|----------|
| **stale_hr_content_10d** (Rule 4 mới) | E6 HALT — HR rows eff≥2026 + "10 ngày phép năm" lọt vào cleaned | E6 OK — quarantine tăng 8 rows | Log `run_id=lab-fix-2026`: `expectation[hr_leave_no_stale_10d_annual] OK (halt) :: violations=0` |
| **unclear_export_prefix** (Rule 6 mới) | ~7 rows "Nội dung không rõ ràng:" trong allowed doc_ids vào cleaned | quarantine tăng 7 rows (reason=unclear_export_prefix) | `quarantine_lab-fix-2026.csv` — cột reason |
| **abab_word_repetition** (Rule 7 mới) | 3 rows "làm việc làm việc" (rows 18, 109, 205) vào index | quarantine tăng 3 rows | Log: `expectation[no_abab_word_repetition] OK (warn) :: abab_chunks=0` |
| **access_control_sop_present** (E7 mới, halt) | Trước khi thêm allowlist: E7 FAIL → halt (access_control_sop_count=0) | Sau khi thêm: access_control_sop_count=6 → OK | Log: `expectation[access_control_sop_present] OK (halt) :: access_control_sop_count=6` |
| **no_abab_word_repetition** (E8 mới, warn) | inject mode (skip-validate): abab_chunks tùy | chuẩn: `abab_chunks=0` → OK | Log `2026-06-10T07-40Z`: `expectation[no_abab_word_repetition] OK (warn) :: abab_chunks=0` |

**Rule chính (baseline + mở rộng):**

- `unknown_doc_id`: allowlist gồm 5 doc_id (thêm `access_control_sop` so với baseline)
- `stale_hr_policy_effective_date`: HR eff < 2026-01-01 (baseline)
- `stale_hr_content_10d` (**MỚI**): HR "10 ngày phép năm" dù eff ≥ 2026 — đóng lỗ hổng date-filter
- `unclear_export_prefix` (**MỚI**): loại noise "Nội dung không rõ ràng:" từ export system
- `abab_word_repetition` (**MỚI**): loại copy-paste bloat ABAB pattern
- Refund fix: policy_refund_v4 "14 ngày làm việc" → "7 ngày làm việc [cleaned: stale_refund_window]"

**Ví dụ expectation fail và xử lý:**

Lần chạy đầu tiên (trước khi thêm `stale_hr_content_10d`):
```
expectation[hr_leave_no_stale_10d_annual] FAIL (halt) :: violations=8
PIPELINE_HALT: expectation suite failed (halt).
```
Fix: thêm Rule 4 vào `clean_rows()` → quarantine HR rows có "10 ngày phép năm" bất kể eff_date → rerun → E6 OK.

---

## 3. Before / after ảnh hưởng retrieval

**Kịch bản inject (Sprint 3):**
```bash
python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate
python eval_retrieval.py --out artifacts/eval/after_inject_bad.csv
```
`--no-refund-fix`: giữ nguyên "14 ngày làm việc" trong policy_refund_v4 → không fix → vào index.  
`--skip-validate`: E3 FAIL nhưng pipeline tiếp tục embed.

**Kết quả định lượng:**

| Question ID | Metric | inject-bad | fix (chuẩn) |
|-------------|--------|------------|-------------|
| gq_d10_01 (refund window) | contains_expected | no | yes |
| gq_d10_01 | hits_forbidden ("14 ngày") | **yes** | **no** |
| gq_d10_09 (HR 12 ngày) | contains_expected | yes | yes |
| gq_d10_10 (access_control) | contains_expected | no (trước allowlist fix) | **yes** |
| **Grading score** | gq_d10_01..10 all pass | inject-bad: gq_01 FAIL | **10/10 PASS** |

→ Chứng minh: retrieval TỆ HƠN khi inject (hits_forbidden=yes), TỐT HƠN sau khi pipeline chuẩn (hits_forbidden=no, contains_expected=yes).

File so sánh: `artifacts/eval/after_inject_bad.csv` vs `artifacts/eval/after_fix.csv`.

---

## 4. Freshness & monitoring

**SLA chọn:** 24 giờ (mặc định `FRESHNESS_SLA_HOURS=24` trong `.env`).

**Ý nghĩa PASS/WARN/FAIL:**
- `PASS`: `latest_exported_at` trong vòng 24h — data fresh, pipeline chạy đúng lịch.
- `WARN`: không tìm được timestamp trong manifest — cần kiểm tra pipeline log.
- `FAIL`: `latest_exported_at` > 24h trước — data có thể stale, cần rerun hoặc investigate.

**Kết quả trên data mẫu:** `FAIL` (bình thường) — max `exported_at` trong CSV là 2026-04-11, chạy tại 2026-06-10 → age ~1500h >> 24h. SLA áp cho pipeline run trong production; với data snapshot tĩnh này, FAIL là expected behavior.

---

## 5. Liên hệ Day 09

Pipeline Day 10 sử dụng cùng corpus `data/docs/` nhưng tạo collection riêng `day10_kb` (thay vì collection Day 09). Lý do tách:
- Day 10 thêm lớp ETL/cleaning kiểm soát version (HR 2026, refund v4) trước khi embed.
- Day 09 embed raw text; Day 10 embed cleaned+validated text với metadata `run_id` để trace.
- Nếu cần feed agent Day 09 bằng data đã validate: thay `CHROMA_COLLECTION=day09_kb` trong `.env` và rerun.

---

## 6. Rủi ro còn lại & việc chưa làm

- `exported_at` format (slashes) không bị quarantine — chỉ ảnh hưởng freshness calculation nếu parse lỗi.
- Chunk "Chú ý: effective_date không đồng nhất giữa các nguồn." (row 40) vào index vì text unique — noise nhỏ.
- Chưa tích hợp Great Expectations / pydantic schema validate.
- Freshness chỉ đo tại boundary "publish" (1 boundary); chưa có "ingest boundary".
- Eval chỉ dùng keyword matching — chưa có LLM-judge.
