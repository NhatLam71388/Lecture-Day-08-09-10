# Quality report — Lab Day 10 (nhóm)

**run_id:** `2026-06-10T07-40Z`  
**Ngày:** 2026-06-10

---

## 1. Tóm tắt số liệu

| Chỉ số | Trước fix (inject-bad) | Sau fix (chuẩn) | Ghi chú |
|--------|----------------------|-----------------|---------|
| raw_records | 247 | 247 | Không đổi — cùng input CSV |
| cleaned_records | 35 (inject-bad) | 35 (chuẩn) | Số lượng bằng nhau vì dedup giống nhau |
| quarantine_records | 212 | 212 | inject-bad: E3 fail nhưng skip-validate |
| Expectation halt? | YES (E3 fail — stale 14d) | NO — tất cả halt pass | E8 (warn) OK cả hai run |

**Expectation results (run chuẩn):**

| Expectation | Status | Severity | Detail |
|-------------|--------|----------|--------|
| min_one_row | OK | halt | cleaned_rows > 0 |
| no_empty_doc_id | OK | halt | empty_doc_id_count=0 |
| refund_no_stale_14d_window | OK | halt | violations=0 |
| chunk_min_length_8 | OK | warn | short_chunks=0 |
| effective_date_iso_yyyy_mm_dd | OK | halt | non_iso_rows=0 |
| hr_leave_no_stale_10d_annual | OK | halt | violations=0 |
| access_control_sop_present | OK | halt | access_control_sop_count ≥ 1 |
| no_abab_word_repetition | OK | warn | abab_chunks=0 |

---

## 2. Before / after retrieval (bắt buộc)

> File: `artifacts/eval/after_inject_bad.csv` (before) vs `artifacts/eval/after_fix.csv` (after)

**Câu hỏi then chốt: `gq_d10_01` — refund window**

| Run | contains_expected | hits_forbidden | top1_doc_id | top1_preview |
|-----|-------------------|----------------|-------------|--------------|
| inject-bad (--no-refund-fix --skip-validate) | no | **yes** | policy_refund_v4 | "14 ngày làm việc..." |
| fix (chuẩn) `2026-06-10T07-40Z` | **yes** | no | policy_refund_v4 | "7 ngày làm việc..." |

**Merit: `gq_d10_09` — HR version conflict**

| Run | contains_expected | hits_forbidden | top1_doc_expected |
|-----|-------------------|----------------|-------------------|
| inject-bad | yes | no | yes |
| fix (chuẩn) | **yes** | **no** | **yes** (hr_leave_policy) |

> Lưu ý: HR version conflict được giải quyết bằng `stale_hr_content_10d` rule (không phải `--no-refund-fix`); cả hai run HR đều OK vì rule quarantine là unconditional.

---

## 3. Freshness & monitor

**Kết quả:** `freshness_check=FAIL` trên data mẫu (bình thường).

- `latest_exported_at` trong CSV mẫu: `2026-04-11T00:00:00` (giá trị max)
- SLA: 24 giờ
- Age tại thời điểm chạy (2026-06-10): ~1500 giờ → FAIL

**Giải thích:** SLA áp dụng cho **pipeline run freshness** trong production (data không được cũ > 24h so với lần export gần nhất). CSV mẫu là snapshot cố định từ 2026-04 nên luôn FAIL khi chạy sau đó. Trong môi trường thật, pipeline nên chạy định kỳ mỗi 12-24h để PASS.

---

## 4. Corruption inject (Sprint 3)

**Kịch bản:** chạy pipeline với `--no-refund-fix --skip-validate`:
- `apply_refund_window_fix=False` → các chunk "14 ngày làm việc" không bị fix → vào index
- `--skip-validate` → expectation E3 fail nhưng pipeline tiếp tục embed

```bash
python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate
python eval_retrieval.py --out artifacts/eval/after_inject_bad.csv
```

**Phát hiện bằng:** `hits_forbidden=yes` trong eval CSV cho refund queries.

Sau khi chạy lại pipeline chuẩn:
```bash
python etl_pipeline.py run
python eval_retrieval.py --out artifacts/eval/after_fix.csv
```

**Kết quả:** `hits_forbidden=no`, `contains_expected=yes` cho tất cả refund queries.

---

## 5. Hạn chế & việc chưa làm

- Chưa tích hợp Great Expectations (dùng custom expectation suite).
- Freshness chỉ đo tại boundary "publish" — chưa đo tại "ingest" (hai boundary).
- Eval chỉ dùng keyword matching, chưa có LLM-judge để đánh giá chất lượng trả lời.
- `exported_at` format check (slashes vs dashes) chưa là quarantine rule riêng.
