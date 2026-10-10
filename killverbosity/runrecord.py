"""The two sidecars a run leaves beside its output."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

RUN_SUFFIX = ".kvrun"
JOURNAL_SUFFIX = ".kvjournal"
CROSS_SUFFIX = ".kvcross"


def run_record_path(out_path: Path | str) -> Path:
    return Path(out_path).with_suffix(Path(out_path).suffix + RUN_SUFFIX)


def journal_path(out_path: Path | str) -> Path:
    return Path(out_path).with_suffix(Path(out_path).suffix + JOURNAL_SUFFIX)


def crosscheck_record_path(out_path: Path | str) -> Path:
    return Path(out_path).with_suffix(Path(out_path).suffix + CROSS_SUFFIX)


def baseline_path(src: Path | str, out_path: Path | str,
                  explicit_out: bool = False) -> Path:
    """Where `run` keeps the untouched copy of `src`, taken before it edits."""
    src, out_path = Path(src), Path(out_path)
    if src.stem.endswith(".orig"):
        return src
    name_from = out_path if explicit_out else src
    return out_path.parent / name_from.with_suffix(f".orig{src.suffix}").name


def evidence_of_reading(meaning_findings, kinds, examined, meaning_kinds):
    """What shows the reviewer actually read: "findings", "examined", "none"."""
    if meaning_findings or any(n for k, n in (kinds or {}).items()
                               if k in meaning_kinds):
        return "findings"
    return "examined" if examined else "none"


def write_crosscheck_record(out_path: Path | str, **fields: object) -> None:
    """That a second model read this exact output for meaning, and what it said."""
    if "evidence" not in fields and "meaning_kinds" in fields:
        fields["evidence"] = evidence_of_reading(
            fields.get("meaning_findings"), fields.get("kinds"),
            fields.get("examined"), fields.get("meaning_kinds") or ())
    crosscheck_record_path(out_path).write_text(
        json.dumps(fields, indent=1) + "\n", encoding="utf-8")


def crosscheck_state(out_path: Path | str) -> str:
    """`"ok"`, `"missing"`, `"stale"` or `"bad"` - the same four as the run record."""
    out_path = Path(out_path)
    p = crosscheck_record_path(out_path)
    if not p.is_file():
        return "missing"
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return "bad"
    if not isinstance(rec, dict):
        return "bad"
    if rec.get("unavailable"):
        return "unavailable"
    if rec.get("checked") is False:
        return "not-checked"
    if p.stat().st_mtime < out_path.stat().st_mtime:
        return "stale"
    return "ok"


def crosscheck_not_checked_reason(out_path: Path | str) -> str | None:
    """Why nobody was asked, as the writer recorded it, or None."""
    if crosscheck_state(out_path) != "not-checked":
        return None
    try:
        rec = json.loads(crosscheck_record_path(out_path).read_text(
            encoding="utf-8"))
    except (ValueError, OSError):
        return None
    why = rec.get("not_checked_reason") if isinstance(rec, dict) else None
    return why if isinstance(why, str) and why.strip() else None


def crosscheck_findings(out_path: Path | str) -> list | None:
    """What the reviewer reported, or `None` when that cannot be told."""
    if crosscheck_state(out_path) != "ok":
        return None
    try:
        rec = json.loads(crosscheck_record_path(out_path).read_text(
            encoding="utf-8"))
    except (ValueError, OSError):
        return None
    findings = rec.get("findings") if isinstance(rec, dict) else None
    return findings if isinstance(findings, list) else None


def _journal_rows(out_path: Path | str, fingerprint: str) -> list[dict]:
    """The rows of one journal that belong to this document, or nothing."""
    p = journal_path(out_path)
    if not p.is_file():
        return []
    rows: list[dict] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
            row["key"], row["result"], source = (
                row["key"], row["result"], row["source"])
        except (ValueError, TypeError, KeyError):
            continue
        if source != fingerprint:
            return []
        rows.append(row)
    return rows


def read_journal(out_path: Path | str, fingerprint: str,
                 agent: str | None = None) -> dict[str, str]:
    """Answers this run may reuse, keyed by the prompt that earned them."""
    out: dict[str, str] = {}
    for row in _journal_rows(out_path, fingerprint):
        if agent is not None and row.get("agent", "") != agent:
            continue
        out[row["key"]] = row["result"]
    return out


def journal_agents(out_path: Path | str, fingerprint: str) -> dict[str, int]:
    """How many banked answers each backend gave, for this document."""
    counts: dict[str, int] = {}
    for row in _journal_rows(out_path, fingerprint):
        who = row.get("agent", "")
        counts[who] = counts.get(who, 0) + 1
    return counts


def bank_timeout(out_path: Path | str, fingerprint: str, job: str,
                 seconds: int) -> None:
    """Record that `job` ran out its whole `seconds` ceiling."""
    with journal_path(out_path).open("a", encoding="utf-8") as bank:
        bank.write(json.dumps({"source": fingerprint, "timeout": int(seconds),
                               "job": job}) + "\n")


def journal_timeouts(out_path: Path | str, fingerprint: str) -> dict[str, int]:
    """Jobs this document's last run timed out, with the longest ceiling each hit."""
    p = journal_path(out_path)
    if not p.is_file():
        return {}
    out: dict[str, int] = {}
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
            job, secs, source = row["job"], int(row["timeout"]), row["source"]
        except (ValueError, TypeError, KeyError):
            continue
        if source == fingerprint:
            out[job] = max(secs, out.get(job, 0))
    return out


ANSWERED_READ = "read"
ANSWERED_UNKNOWABLE = "unknowable"
ANSWERED_NOT_LOOKED = "not looked at"


CROSSCHECK_OBSERVED = "observed"
CROSSCHECK_ASSUMED = "assumed"


def answered_fields(result: dict) -> dict[str, object]:
    """One job's provenance, for its `job_spans` entry."""
    return {"answered_rung": result.get("answered_rung"),
            "answered_by": result.get("answered_by"),
            "answered_by_state": result.get("answered_by_state",
                                            ANSWERED_NOT_LOOKED),
            "substituted": bool(result.get("substituted"))}


def answering_backends(record: dict) -> list[str]:
    """Who actually wrote this run's edits, for the same-family guard."""
    agent = record.get("agent")
    agent = agent if isinstance(agent, str) and agent else None
    spans = record.get("job_spans")
    tracked = [j for j in spans if isinstance(j, dict)
               and "answered_by_state" in j] if isinstance(spans, list) else []
    if not tracked:
        return [agent] if agent else []
    out: list[str] = []
    for j in tracked:
        via, rung = j.get("answered_by"), j.get("answered_rung")
        if j["answered_by_state"] == ANSWERED_READ and isinstance(via, str) \
                and via:
            who = via
        elif isinstance(rung, str) and rung:
            who = rung
        else:
            who = agent
        if who and who not in out:
            out.append(who)
    return out


def cross_writers(target: Path | str) -> list[str]:
    """The writer(s) an EARLIER crosscheck's `.kvcross` recorded under `wrote`."""
    p = crosscheck_record_path(target)
    if not p.is_file():
        return []
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    if not isinstance(rec, dict):
        return []
    wrote = rec.get("wrote")
    if isinstance(wrote, str) and wrote:
        return [wrote]
    if isinstance(wrote, list):
        return [w for w in wrote if isinstance(w, str) and w]
    return []


def answered_tail(answered: list[dict], agent: str | None) -> str | None:
    """One line naming who really answered, when most jobs were substituted."""
    subst = [a for a in answered if a.get("substituted")]
    if not answered or 2 * len(subst) <= len(answered):
        return None
    who: dict[str, int] = {}
    for a in subst:
        via, rung = a.get("answered_by"), a.get("answered_rung")
        if a.get("answered_by_state") == ANSWERED_READ and via:
            name = via
        elif rung and rung != agent:
            name = f"{rung} (model not named)"
        else:
            name = "an unnamed agent"
        who[name] = who.get(name, 0) + 1
    names = ", ".join(f"{w} ({n})" for w, n in
                      sorted(who.items(), key=lambda i: -i[1]))
    return (f"answered by: {names} — {len(subst)} of {len(answered)} jobs "
            f"did not run on {agent}, the agent this run asked for")


def journal_key(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest()[:16]


def source_fingerprint(text: str) -> str:
    """What the run read, so `accept` can tell it is still that file."""
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def write_run_record(out_path: Path | str, **fields: object) -> None:
    """What `verify` and `accept` need to know about the run that wrote this."""
    run_record_path(out_path).write_text(json.dumps(fields, indent=1) + "\n",
                                         encoding="utf-8")


def stale_record(out_path: Path | str) -> dict[str, object]:
    """A stale record's contents, for the one caller that can use them."""
    out_path = Path(out_path)
    p = run_record_path(out_path)
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return rec if isinstance(rec, dict) else {}


def record_state(out_path: Path | str) -> str:
    """Why there is no usable record: `"ok"`, `"missing"`, `"stale"`, `"bad"`."""
    out_path = Path(out_path)
    p = run_record_path(out_path)
    if not p.is_file():
        return "missing"
    if p.stat().st_mtime < out_path.stat().st_mtime:
        return "stale"
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return "bad"
    return "ok" if isinstance(rec, dict) else "bad"


def read_run_record(out_path: Path | str) -> dict[str, object]:
    """The record, or `{}` when there is none this run can trust."""
    out_path = Path(out_path)
    p = run_record_path(out_path)
    if not p.is_file():
        return {}
    if p.stat().st_mtime < out_path.stat().st_mtime:
        print(f"ignoring {p.name}: it is older than {out_path.name}, so the "
              f"output changed after the record was written and nothing here "
              f"can tell which parts the run wrote. Rerun to refresh it.\n")
        return {}
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        print(f"ignoring {p.name}: it is not a readable run record.\n")
        return {}
    return rec if isinstance(rec, dict) else {}
