"""
Cleaning rules — raw export → cleaned rows + quarantine.

Baseline gồm các failure mode mở rộng (allowlist doc_id, parse ngày, HR stale version).
3 rule mới thêm bởi nhóm (metric_impact ghi trong reports/group_report.md):
  - stale_hr_content_10d   : HR chunks chứa "10 ngày phép năm" nhưng eff_date ≥ 2026 (lọt qua date-filter baseline)
  - unclear_export_prefix  : chunks bắt đầu bằng "Nội dung không rõ ràng:" (noise từ export system)
  - abab_word_repetition   : chunks có cặp từ ABAB liên tiếp (copy-paste error — vd "làm việc làm việc")
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Khớp export hợp lệ trong lab (mở rộng khi nhóm thêm doc mới — phải đồng bộ contract).
ALLOWED_DOC_IDS = frozenset(
    {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
        "access_control_sop",  # thêm mới — cần cho gq_d10_10 (Level 4 Admin Access)
    }
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")

_UNCLEAR_PREFIX = "Nội dung không rõ ràng:"
_STALE_HR_MARKER = "10 ngày phép năm"


def _has_abab_repetition(text: str) -> bool:
    """Phát hiện cặp từ ABAB liên tiếp (copy-paste error vd 'làm việc làm việc')."""
    words = text.split()
    for i in range(len(words) - 3):
        pair1 = (words[i].lower(), words[i + 1].lower())
        pair2 = (words[i + 2].lower(), words[i + 3].lower())
        if pair1 == pair2:
            return True
    return False


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _stable_chunk_id(doc_id: str, chunk_text: str, seq: int) -> str:
    h = hashlib.sha256(f"{doc_id}|{chunk_text}|{seq}".encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}_{seq}_{h}"


def _normalize_effective_date(raw: str) -> Tuple[str, str]:
    """
    Trả về (iso_date, error_reason).
    iso_date rỗng nếu không parse được.
    """
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        return s, ""
    m = _DMY_SLASH.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", ""
    return "", "invalid_effective_date_format"


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Trả về (cleaned, quarantine).

    Baseline (mở rộng theo narrative Day 10):
    1) Quarantine: doc_id không thuộc allowlist (export lạ / catalog sai).
    2) Chuẩn hoá effective_date sang YYYY-MM-DD; quarantine nếu không parse được.
    3) Quarantine: chunk hr_leave_policy có effective_date < 2026-01-01 (bản HR cũ / conflict version).
    4) [NEW] Quarantine: hr_leave_policy chứa "10 ngày phép năm" dù eff_date ≥ 2026 (content stale lọt qua date-filter).
    5) Quarantine: chunk_text rỗng hoặc effective_date rỗng sau chuẩn hoá.
    6) [NEW] Quarantine: chunk_text bắt đầu bằng "Nội dung không rõ ràng:" (noise prefix từ export system).
    7) [NEW] Quarantine: chunk_text có cặp từ ABAB liên tiếp (copy-paste bloat — vd "làm việc làm việc").
    8) Loại trùng nội dung chunk_text (giữ bản đầu).
    9) Fix stale refund: policy_refund_v4 chứa '14 ngày làm việc' → 7 ngày.
    """
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    seq = 0

    for raw in rows:
        doc_id = raw.get("doc_id", "")
        text = raw.get("chunk_text", "")
        eff_raw = raw.get("effective_date", "")
        exported_at = raw.get("exported_at", "")

        if doc_id not in ALLOWED_DOC_IDS:
            quarantine.append({**raw, "reason": "unknown_doc_id"})
            continue

        eff_norm, eff_err = _normalize_effective_date(eff_raw)
        if eff_err == "empty_effective_date":
            quarantine.append({**raw, "reason": "missing_effective_date"})
            continue
        if eff_err == "invalid_effective_date_format":
            quarantine.append({**raw, "reason": eff_err, "effective_date_raw": eff_raw})
            continue

        if doc_id == "hr_leave_policy" and eff_norm < "2026-01-01":
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        # [NEW Rule 1] stale_hr_content_10d: HR chunk chứa nội dung chính sách 10 ngày
        # dù eff_date ≥ 2026-01-01 (export system gán sai ngày cho bản HR 2025).
        # metric_impact: không có rule này → E6 (hr_leave_no_stale_10d_annual) HALT.
        if doc_id == "hr_leave_policy" and _STALE_HR_MARKER in text:
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_content_10d",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        if not text:
            quarantine.append({**raw, "reason": "missing_chunk_text"})
            continue

        # [NEW Rule 2] unclear_export_prefix: export system đánh dấu nội dung mơ hồ.
        # metric_impact: quarantine_records tăng; loại ambiguous chunks khỏi index.
        if text.startswith(_UNCLEAR_PREFIX):
            quarantine.append({**raw, "reason": "unclear_export_prefix"})
            continue

        # [NEW Rule 3] abab_word_repetition: phát hiện copy-paste error "A B A B".
        # metric_impact: quarantine_records tăng; tránh bloated chunks nhiễu loạn retrieval.
        if _has_abab_repetition(text):
            quarantine.append({**raw, "reason": "abab_word_repetition"})
            continue

        key = _norm_text(text)
        if key in seen_text:
            quarantine.append({**raw, "reason": "duplicate_chunk_text"})
            continue
        seen_text.add(key)

        fixed_text = text
        if apply_refund_window_fix and doc_id == "policy_refund_v4":
            if "14 ngày làm việc" in fixed_text:
                fixed_text = fixed_text.replace(
                    "14 ngày làm việc",
                    "7 ngày làm việc",
                )
                fixed_text += " [cleaned: stale_refund_window]"

        seq += 1
        cleaned.append(
            {
                "chunk_id": _stable_chunk_id(doc_id, fixed_text, seq),
                "doc_id": doc_id,
                "chunk_text": fixed_text,
                "effective_date": eff_norm,
                "exported_at": exported_at or "",
            }
        )

    return cleaned, quarantine


def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at\n", encoding="utf-8")
        return
    fieldnames = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    keys: List[str] = []
    seen_k: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_k:
                seen_k.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)
