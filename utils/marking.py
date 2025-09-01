import re
from typing import Any, Dict, List, Tuple


def globalize_objective_numbers(student_text: str) -> str:
    """
    Reads a student's mixed submission (may contain 'Teil 3', 'Teil 4', essays, etc.),
    extracts objective answers, and rewrites them to GLOBAL numbering (1..N).
    Output is one-per-line: '1. B', '2. A', ...
    """
    if not student_text:
        return ""

    def parse_pairs_freeform_with_teil_offsets(text: str) -> Dict[int, str]:
        res: Dict[int, str] = {}
        offset = 0

        for raw_line in text.splitlines():
            line = raw_line.strip()

            if re.search(r"^\s*teil\s*\d+\s*$", line, flags=re.I):
                offset = max(res.keys() or [0])
                continue

            m = re.match(r"\s*(?:q\s*)?(\d+)\s*[\\.\):=\-]?\s*(.+?)\s*$", line, flags=re.I)
            if m:
                local_n = int(m.group(1))
                token = m.group(2).strip().strip("()[]{}.:=,;")
                gnum = local_n + offset if offset else local_n
                res.setdefault(gnum, token)
                continue

            anchors = list(re.finditer(r"(?i)(?:q\s*)?(\d+)\s*[\\.\):=\-]*\s*", line))
            for i, am in enumerate(anchors):
                local_n = int(am.group(1))
                start = am.end()
                end = anchors[i + 1].start() if i + 1 < len(anchors) else len(line)
                chunk = line[start:end].strip()
                if not chunk:
                    continue
                token = re.split(r"[,\|\n;/\t ]+", chunk, maxsplit=1)[0].strip("()[]{}.:=")
                if token:
                    gnum = local_n + offset if offset else local_n
                    res.setdefault(gnum, token)

        return res

    pairs = parse_pairs_freeform_with_teil_offsets(student_text)
    if not pairs:
        return ""

    lines = [f"{k}. {v}" for k, v in sorted(pairs.items())]
    return "\n".join(lines)


def _count_words(s: str) -> int:
    return len(re.findall(r"\b[\wÄÖÜäöüß]+(?:'[A-Za-z]+)?\b", s or ""))


def _canonical_token(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if re.fullmatch(r"[a-dA-D]", s):
        return s.upper()
    s = (
        s.lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    if s in {"t", "true", "ja", "j", "y", "yes"}:
        return "true"
    if s in {"f", "false", "nein", "n", "no"}:
        return "false"
    return re.sub(r"[^\w]+", "", s)


def _parse_ref_map(ref_text: str) -> Dict[int, str]:
    m: Dict[int, str] = {}
    for line in (ref_text or "").splitlines():
        hit = re.match(r"\s*(\d+)\s*[\.\)-]?\s*(.+)$", line)
        if hit:
            n = int(hit.group(1))
            tok = hit.group(2).strip()
            m[n] = tok
    return m


def _parse_student_global_map(student_text: str) -> Dict[int, str]:
    g = globalize_objective_numbers(student_text or "")
    out: Dict[int, str] = {}
    for line in g.splitlines():
        hit = re.match(r"\s*(\d+)\s*[\.\)-]?\s*(.+)$", line)
        if hit:
            out[int(hit.group(1))] = hit.group(2).strip()
    return out


def _compute_objective_diffs(student_text: str, ref_text: str) -> Tuple[int, int, List[Tuple[int, str, str]]]:
    ref_map = _parse_ref_map(ref_text)
    stu_map = _parse_student_global_map(student_text)
    total = len(ref_map) or 1
    wrong: List[Tuple[int, str, str]] = []
    correct = 0
    for n in sorted(ref_map.keys()):
        ref_tok = ref_map[n]
        stu_tok_raw = stu_map.get(n, "")
        if _canonical_token(stu_tok_raw) == _canonical_token(ref_tok):
            correct += 1
        else:
            wrong.append((n, ref_tok, stu_tok_raw))
    return correct, total, wrong


def _build_feedback_40_60(correct: int, total: int, wrong: List[Tuple[int, str, str]]) -> str:
    pieces = [f"Good effort for A1 objectives—you answered {correct} of {total} correctly."]
    if wrong:
        shown = ", ".join(f"{n}→{corr} (you wrote {stu or '—'})" for n, corr, stu in wrong[:6])
        pieces.append(f"Check these items: {shown}.")
    tips = [
        "Slow down, read each stem fully, and match letters carefully.",
        "Use umlauts (ä/ö/ü) and verify meaning before choosing.",
        "Underline keywords, compare similar options, and double-check B/C confusions.",
    ]
    for t in tips:
        pieces.append(t)
        if _count_words(" ".join(pieces)) >= 40:
            break
    text = " ".join(pieces)
    i = 0
    while _count_words(text) < 40 and i < len(tips):
        text = text + " " + tips[i]
        i += 1
    while _count_words(text) > 60:
        text = re.sub(r"\s*[^.?!]*[.?!]\s*$", "", text).strip()
        if not re.search(r"[.?!]$", text):
            break
    return text


def objective_mark(student_answer: str, ref_answers: Dict[int, str]) -> Tuple[int, str]:
    """
    Robust objective marking without AI.
    - Parses messy "Qn -> answer" formats with Teil section offsets.
    - Normalizes umlauts/ß to ASCII equivalents for comparison.
    - Accepts synonyms for True/False and Ja/Nein.
    """

    def canonical_word(s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        if re.fullmatch(r"[a-dA-D]", s):
            return s.upper()
        s = s.lower()
        s = (
            s.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        if s in {"t", "true", "ja", "j", "y", "yes"}:
            return "true"
        if s in {"f", "false", "nein", "n", "no"}:
            return "false"
        s = re.sub(r"[^\w]+", "", s)
        return s

    def parse_pairs_freeform_with_teil_offsets(text: str) -> Dict[int, str]:
        res: Dict[int, str] = {}
        offset = 0
        lines = text.splitlines()

        for line in lines:
            if re.search(r"^\s*teil\s*\d+\s*$", line, flags=re.I):
                offset = max(res.keys() or [0])
                continue

            m = re.match(r"\s*(?:q\s*)?(\d+)\s*[\\.\):=\-]?\s*(.+?)\s*$", line, flags=re.I)
            if m:
                local_n = int(m.group(1))
                token = m.group(2).strip().strip("()[]{}.:=,;")
                gnum = local_n + offset if offset else local_n
                res.setdefault(gnum, token)
                continue

            for m in re.finditer(r"(?i)(?:q\s*)?(\d+)\s*[\\.\):=\-]*\s*", line):
                local_n = int(m.group(1))
                tail = line[m.end():].strip()
                token = re.split(r"[,\|\n;/\t ]+", tail, maxsplit=1)[0].strip("()[]{}.:=")
                if token:
                    gnum = local_n + offset if offset else local_n
                    res.setdefault(gnum, token)
                    break
        return res

    ref_canon: Dict[int, str] = {int(idx): canonical_word(str(ans)) for idx, ans in (ref_answers or {}).items()}

    stu_raw = parse_pairs_freeform_with_teil_offsets(student_answer or "")
    stu_canon: Dict[int, str] = {qn: canonical_word(tok) for qn, tok in stu_raw.items()}

    total = len(ref_canon) or 1
    correct = 0
    wrong_bits: List[str] = []

    for idx in sorted(ref_canon.keys()):
        ref_tok = ref_canon[idx]
        stu_tok = stu_canon.get(idx, "")
        ok = stu_tok == ref_tok
        if ok:
            correct += 1
        else:
            stu_disp = stu_raw.get(idx, "") or "—"
            wrong_bits.append(f"{idx}→{ref_answers.get(idx, '')} (you wrote {stu_disp})")

    score = int(round(100 * correct / total))
    feedback = (
        "Great job — all correct!"
        if not wrong_bits
        else (
            "Keep going. Check these: "
            + ", ".join(wrong_bits)
            + ". Tip: match section numbering (Teil), read each stem carefully, and watch umlauts (ä/ö/ü)."
        )
    )
    return score, feedback
