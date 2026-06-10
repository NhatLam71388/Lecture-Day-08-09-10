# Runbook — Lab Day 10 (incident tối giản)

---

## Symptom

**Scenario A — Agent trả lời "14 ngày" thay vì "7 ngày" cho câu hỏi hoàn tiền.**  
User hoặc eval hỏi: *"Khách hàng có bao nhiêu ngày để yêu cầu hoàn tiền?"*  
Agent (hoặc `grading_run.py`) trả về context chứa "14 ngày làm việc".

**Scenario B — Agent không có thông tin về Access Control / Level 4 Admin.**  
`grading_run.py` cho câu gq_d10_10: `contains_expected=false`, `top1_doc_matches=false`.

**Scenario C — Pipeline HALT do expectation fail.**  
`python etl_pipeline.py run` thoát với exit code 2.

---

## Detection

| Signal | Nguồn | Ngưỡng |
|--------|-------|--------|
| `hits_forbidden=yes` cho refund query | `artifacts/eval/*.csv` | Bất kỳ dòng nào = alert |
| `expectation[...] FAIL (halt)` | `artifacts/logs/run_*.log` | FAIL severity=halt → exit 2 |
| `freshness_check=FAIL` | log / manifest | age_hours > sla_hours (mặc định 24h) |
| `access_control_sop_count=0` | log expectation E7 | E7 fail → halt |
| `quarantine_records` tăng đột biến | manifest | > 200 / run cần review |

---

## Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | `cat artifacts/manifests/manifest_<run-id>.json` | Xem `cleaned_records`, `quarantine_records`, `latest_exported_at` |
| 2 | `grep "expectation\|HALT\|WARN" artifacts/logs/run_<run-id>.log` | Xác định expectation nào FAIL |
| 3 | `head artifacts/quarantine/quarantine_<run-id>.csv` | Xem `reason` của các dòng bị loại |
| 4 | `python eval_retrieval.py --out artifacts/eval/diagnose.csv` | Kiểm tra `hits_forbidden` và `top1_doc_id` |
| 5 | Nếu Scenario B: `grep "access_control_sop" transform/cleaning_rules.py` | Xác nhận doc_id có trong ALLOWED_DOC_IDS |

---

## Mitigation

**Scenario A — Stale refund window:**
```bash
# Chạy lại pipeline chuẩn (có refund fix)
python etl_pipeline.py run --run-id fix-$(date +%Y%m%dT%H%M)
python eval_retrieval.py --out artifacts/eval/after_fix.csv
```
Nếu vẫn fail: kiểm tra `quarantine_<run>.csv` — tìm rows `policy_refund_v4` bị quarantine vì sai lý do.

**Scenario B — Thiếu access_control_sop:**
- Kiểm tra `ALLOWED_DOC_IDS` trong `transform/cleaning_rules.py` có chứa `"access_control_sop"` chưa.
- Kiểm tra `contracts/data_contract.yaml` → `allowed_doc_ids` đồng bộ chưa.
- Sau khi sửa: rerun pipeline.

**Scenario C — Expectation HALT:**
```bash
# Xem log chi tiết
cat artifacts/logs/run_<run-id>.log | grep "FAIL\|HALT"
# Sửa code rồi rerun
python etl_pipeline.py run
```
**Không dùng `--skip-validate` cho production run** (chỉ dùng cho Sprint 3 demo).

**Rollback embed (khi cần):**
- Chạy pipeline với run-id của lần chạy "tốt" trước đó — upsert sẽ ghi đè vector cũ.
- Prune tự động loại bỏ id không còn trong cleaned CSV đó.

---

## Prevention

1. **Expectation E7** (`access_control_sop_present`, halt): pipeline tự phát hiện nếu source này mất.
2. **Expectation E3** (`refund_no_stale_14d_window`, halt): phát hiện stale refund ngay sau clean.
3. **Expectation E6** (`hr_leave_no_stale_10d_annual`, halt): phát hiện HR version conflict.
4. **Freshness check**: chạy sau mỗi run — FAIL khi `latest_exported_at` > 24h.  
   - CSV mẫu có `exported_at` từ 2026-04-xx: freshness luôn FAIL khi chạy sau 2026-04 vì data "snapshot" cũ.  
   - Đây là **hành vi đúng** với data mẫu — giải thích trong group_report: SLA áp cho "pipeline run" không phải "data snapshot".  
   - Để test PASS: đặt `FRESHNESS_SLA_HOURS=99999` trong `.env` hoặc cập nhật `exported_at` có chủ đích.
5. **Alert channel**: `Slack #data-pipeline-alerts` (khai báo trong contract) — tích hợp khi có CI/CD thật.
6. **Nối Day 11**: guardrail có thể check `hits_forbidden` tự động trong agent response trước khi trả user.
