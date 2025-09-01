import re
from typing import Any, Dict, List, Tuple

import pandas as pd


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.findall(r"\d+|\D+", str(s))]


def find_col(df: pd.DataFrame, candidates: List[str], default: str = "") -> str:
    norm = {c: c.lower().strip().replace(" ", "").replace("_", "") for c in df.columns}
    want = [c.lower().strip().replace(" ", "").replace("_", "") for c in candidates]
    for raw, n in norm.items():
        if n in want:
            return raw
    if default and default not in df.columns:
        df[default] = ""
        return default
    raise KeyError(f"Missing columns: {candidates}")


def list_sheet_assignments(ref_df: pd.DataFrame, assignment_col: str) -> List[str]:
    vals = ref_df[assignment_col].astype(str).fillna("").str.strip()
    vals = [v for v in vals if v]
    return sorted(vals, key=natural_key)


def ordered_answer_cols(cols: List[str]) -> List[str]:
    pairs = []
    for c in cols:
        if c.lower().startswith("answer"):
            m = re.search(r"(\d+)", c)
            if m:
                pairs.append((int(m.group(1)), c))
    return [c for _, c in sorted(pairs, key=lambda x: x[0])]


def build_reference_text_from_sheet(
    ref_df: pd.DataFrame, assignment_col: str, assignment_value: str
) -> Tuple[str, str, str, Dict[int, str]]:
    row = ref_df[ref_df[assignment_col] == assignment_value]
    if row.empty:
        return "No reference answers found.", "", "essay", {}
    row = row.iloc[0]
    ans_cols = ordered_answer_cols(list(ref_df.columns))
    chunks: List[str] = []
    answers_map: Dict[int, str] = {}
    for c in ans_cols:
        v = str(row.get(c, "")).strip()
        if v and v.lower() not in ("nan", "none"):
            m = re.search(r"(\d+)", c)
            n = int(m.group(1)) if m else 0
            chunks.append(f"{n}. {v}")
            answers_map[n] = v
    link = str(row.get("answer_url", "")).strip()
    fmt = str(row.get("format", "essay")).strip().lower() or "essay"
    return (
        "\n".join(chunks) if chunks else "No reference answers found.",
        link,
        fmt,
        answers_map,
    )


def list_json_assignments(ans_dict: Dict[str, Any]) -> List[str]:
    return sorted(list(ans_dict.keys()), key=natural_key)


def build_reference_text_from_json(
    row_obj: Dict[str, Any]
) -> Tuple[str, str, str, Dict[int, str]]:
    answers: Dict[str, Any] = row_obj.get("answers") or {
        k: v for k, v in row_obj.items() if k.lower().startswith("answer")
    }

    def n_from(k: str) -> int:
        m = re.search(r"(\d+)", k)
        return int(m.group(1)) if m else 0

    chunks: List[str] = []
    answers_map: Dict[int, str] = {}

    if isinstance(answers, dict):
        part_keys = [k for k in answers if k.lower().startswith("teil")]
        if part_keys:
            idx = 1
            for part_key in sorted(part_keys, key=natural_key):
                part = answers.get(part_key) or {}
                if part:
                    chunks.append(part_key.replace("teil", "Teil "))
                    ordered = sorted(part.items(), key=lambda kv: n_from(kv[0]))
                    for k, v in ordered:
                        v = str(v).strip()
                        if v and v.lower() not in ("nan", "none"):
                            chunks.append(f"{idx}. {v}")
                            answers_map[idx] = v
                            idx += 1
        else:
            ordered = sorted(answers.items(), key=lambda kv: n_from(kv[0]))
            for k, v in ordered:
                v = str(v).strip()
                if v and v.lower() not in ("nan", "none"):
                    idx = n_from(k)
                    chunks.append(f"{idx}. {v}")
                    answers_map[idx] = v
    fmt = str(row_obj.get("format", "essay")).strip().lower() or "essay"
    return (
        "\n".join(chunks) if chunks else "No reference answers found.",
        str(row_obj.get("answer_url", "")).strip(),
        fmt,
        answers_map,
    )


def filter_any(df: pd.DataFrame, q: str) -> pd.DataFrame:
    if not q:
        return df
    mask = df.apply(lambda c: c.astype(str).str.contains(q, case=False, na=False))
    return df[mask.any(axis=1)]
