# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Lam  
**Vai trò:** All roles (solo) — Ingestion + Cleaning & Quality + Embed + Monitoring  
**Ngày nộp:** 2026-06-10  
**Độ dài yêu cầu:** 400–650 từ

---

## 1. Tôi phụ trách phần nào?

**File / module:**

- `transform/cleaning_rules.py`: thêm `access_control_sop` vào `ALLOWED_DOC_IDS`, implement 3 rule mới (`stale_hr_content_10d`, `unclear_export_prefix`, `abab_word_repetition`) và helper `_has_abab_repetition`.
- `quality/expectations.py`: thêm E7 `access_control_sop_present` (halt) và E8 `no_abab_word_repetition` (warn).
- `contracts/data_contract.yaml`: cập nhật `allowed_doc_ids`, `canonical_sources`, `quality_rules`.
- `docs/pipeline_architecture.md`, `docs/data_contract.md`, `docs/runbook.md`, `docs/quality_report_template.md`: điền đầy đủ nội dung.
- `reports/group_report.md`: hoàn thiện bảng metric_impact và before/after.

**Kết nối với thành viên khác:** Solo — tự phụ trách toàn bộ pipeline.

**Bằng chứng:** thay đổi trong commit git; `ALLOWED_DOC_IDS` thêm `"access_control_sop"` tại `cleaning_rules.py:22`; hàm `_has_abab_repetition` tại `cleaning_rules.py:36`.

---

## 2. Một quyết định kỹ thuật

**Chủ đề: Quarantine vs Fix cho HR stale content.**

Baseline rule 3 lọc HR rows theo `effective_date < 2026-01-01`. Tuy nhiên, một số rows có `eff_date ≥ 2026-01-01` nhưng nội dung vẫn chứa "10 ngày phép năm (bản HR 2025)" — export system có vẻ gán nhầm ngày mới cho bản nội dung cũ. Hai lựa chọn:

1. **Fix approach**: thay "10 ngày" thành "12 ngày" trong chunk_text — giống cách baseline xử lý refund window.
2. **Quarantine approach**: loại hẳn rows này ra quarantine với reason `stale_hr_content_10d`.

Tôi chọn **quarantine** vì: (a) nội dung chunk là "bản HR 2025" có nhãn rõ ràng — không đủ tin cậy để tự động patch; (b) trong `data/docs/hr_leave_policy.txt` (canonical source) đã có thông tin đúng "12 ngày" với eff_date 2026-01-01; (c) quarantine cho phép data owner review và xác nhận nguồn gốc trước khi remerge. Fix chỉ phù hợp khi lỗi là format (vd ngày DD/MM) hoặc typo đơn giản.

---

## 3. Một lỗi hoặc anomaly đã xử lý

**Triệu chứng:** `python etl_pipeline.py run` thoát với exit code 2, log ghi:
```
expectation[hr_leave_no_stale_10d_annual] FAIL (halt) :: violations=8
PIPELINE_HALT: expectation suite failed (halt).
```

**Phát hiện bằng:** log `artifacts/logs/run_<id>.log`, expectation E6.

**Phân tích:** mở `artifacts/quarantine/<run>.csv` → thấy HR rows bị quarantine vì `stale_hr_policy_effective_date` (eff < 2026). Nhưng `cleaned_<run>.csv` vẫn còn các rows `hr_leave_policy` có `effective_date = 2026-01-09`, `2026-02-10`, v.v. chứa "10 ngày phép năm". Pipeline chỉ kiểm tra ngày, không kiểm tra nội dung — đây là lỗ hổng.

**Fix:** thêm rule `stale_hr_content_10d` sau rule date-check:
```python
if doc_id == "hr_leave_policy" and _STALE_HR_MARKER in text:
    quarantine.append({...,"reason": "stale_hr_content_10d"})
    continue
```
Sau fix: `quarantine_records` tăng thêm 8, `cleaned_records` giảm 8, E6 pass.

---

## 4. Bằng chứng trước / sau

**run_id inject-bad:** `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`

Dòng từ `artifacts/eval/after_inject_bad.csv` (câu `q_refund_window`):
```
q_refund_window,...,policy_refund_v4,"Yêu cầu hoàn tiền được chấp nhận trong vòng 14 ngày...",no,yes,no,8
```
→ `contains_expected=no`, `hits_forbidden=yes` (chứa "14 ngày làm việc").

**run_id `2026-06-10T07-40Z` (chuẩn):** `python etl_pipeline.py run`

Dòng từ `artifacts/eval/after_fix.csv` (câu `q_refund_window`):
```
q_refund_window,...,policy_refund_v4,"Yêu cầu được gửi trong vòng 7 ngày làm việc...",yes,no,yes,8
```
→ `contains_expected=yes`, `hits_forbidden=no`, `top1_doc_expected=yes`. Grading chính thức: **10/10 PASS**.

---

## 5. Cải tiến tiếp theo

Nếu có thêm 2 giờ: implement **freshness measurement tại boundary "ingest"** (ghi timestamp khi raw CSV được đọc) và **boundary "publish"** (khi embed hoàn tất) — so sánh delta để phát hiện "pipeline lag" ngay cả khi data source fresh nhưng pipeline bị stuck. Hiện tại chỉ có 1 boundary (publish = `latest_exported_at` từ cleaned CSV).
