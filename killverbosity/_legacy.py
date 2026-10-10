#!/usr/bin/env python3
"""kill-verbosity — the deterministic half of the kill-verbosity skill.

The script never rewrites prose. It builds the work list, then checks the result.

    plan FILE        chunks, shape hits, duplicates, inconsistencies, fact inventory
    run FILE         fan the work out to the specialists, merge, verify
    verify ORIG NEW  facts survived, shapes gone. 0 pass, 3 review, 1 broken
    accept FILE      put the run's output in place of FILE, once verify allows it
    crosscheck FILE  a second opinion from another local agent CLI
    selftest         assert the parser and the gate still work

`run` is the orchestrator. It splits the file, routes each shape hit to the one
specialist that owns it, calls that specialist on its own span with its own
prompt, then merges every reply into one file and gates it with `verify`.

Counts are a work list, never a grade. A regex matches text, not meaning, so every
hit needs a human or an agent to read it before it is touched.
"""
import argparse
import ast
import contextlib
import difflib
import hashlib
import io
import inspect
import json
import ntpath
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


class UsageError(ValueError):
    """Something the caller can fix, printed as one line and exit 2."""



DEFAULT_VOCAB = {
    "filler": [
        r"leverag(?:e|es|ed|ing)", r"utili[sz](?:e|es|ed|ing)",
        r"facilitat(?:e|es|ed|ing)", r"robust", r"seamless", r"holistic",
        r"synerg\w*", r"paradigm", r"best-in-class", r"deep dive",
        r"delve[sd]? into", r"tapestry", r"landscape of",
    ],
    "domain_jargon": [
        r"TOCTOU", r"code smell", r"cross-cutting concerns",
    ],
    "tooling_names": [
        r"codex", r"gemini", r"agy", r"claude", r"openrouter",
    ],
    "id_families": [
        r"round-\d+", r"[A-Z]\.\d+", r"R-\d+",
    ],
    "corporate_headers": [
        r"Executive Summary", r"Quick Summary", r"Priority Order",
        r"Next Steps", r"Pre-Submission Checklist", r"Expected Test Results",
        r"Recommendations?", r"Assessment", r"Key Findings?",
    ],
    "safe_metaphors": [
        "sandbox", "pipeline", "cache", "thread", "stream", "bridge", "handler",
    ],
    "safe_acronyms": [
        "CLI", "API", "HTTP", "HTTPS", "JSON", "YAML", "URL", "CI", "CD", "MR",
        "PR", "SDK", "UUID", "SQL", "TLS", "SSH", "CPU", "RAM", "OS", "UI",
        "LLM", "BYOK",
    ],
    "units": [
        r"seconds?", r"secs?", r"minutes?", r"mins?", r"hours?", r"days?",
        r"weeks?", r"months?", r"years?", r"ms", r"GB", r"MB", r"KB", r"TB",
        r"%", r"s",
    ],
    "unit_canon": {
        "second": "s", "sec": "s", "s": "s", "ms": "ms",
        "minute": "min", "min": "min", "hour": "h", "day": "d",
        "week": "w", "month": "mo", "year": "y",
        "kb": "KB", "mb": "MB", "gb": "GB", "tb": "TB",
    },
    "unit_family": {
        "ms": "time", "s": "time", "min": "time", "h": "time",
        "d": "time", "w": "time", "mo": "time", "y": "time",
        "KB": "size", "MB": "size", "GB": "size", "TB": "size",
    },
    "code_ext": [
        "py", "md", "ts", "js", "tsx", "jsx", "yaml", "yml", "json", "sh",
        "toml", "tf", "sql", "txt", "cfg", "ini", "go", "rs", "java",
    ],
    "never_swap": [],
}

DEFAULT_THRESHOLDS = {
    "long_sentence": 30,
    "summary_max_words": 500,
    "summary_min_words": 40,
    "summary_needed_from": 800,
    "summary_share": 0.18,
    "chat_max_words": 150,
    "length_target": 0.5,
    "max_span": 80,
    "max_span_words": 800,
    "paragraph_wall": 4,
    "wall_seam_words": 150,
    "duplicate_from_words": 5,
    "claim_kept": 0.5,
    "genre_dated_heads": 0.5,
    "genre_task_lines": 0.3,
    "genre_table_rows": 0.5,
    "genre_majority": 0.7,
}

THRESHOLD_KIND = {
    "long_sentence": "count", "summary_max_words": "count",
    "summary_min_words": "count", "summary_needed_from": "count",
    "paragraph_wall": "count", "wall_seam_words": "count",
    "summary_share": "share", "chat_max_words": "count", "max_span": "count",
    "max_span_words": "count",
    "length_target": "share",
    "duplicate_from_words": "count", "claim_kept": "share",
    "genre_dated_heads": "share", "genre_task_lines": "share",
    "genre_table_rows": "share", "genre_majority": "share",
}

WORD_ONLY_SHAPES = {"summary heading", "rule word", "claim word",
                    "abbreviation", "recommendation verb", "advice word"}

VOCAB_IS_REGEX = {"filler", "domain_jargon", "tooling_names", "id_families",
                  "corporate_headers", "units", "code_ext", "never_swap"}

PROFILE_DIR = HERE / "profiles"

PROJECT_FILE = ".killverbosity.json"
PROJECT_KEYS = {"profile", "specialists", "refuse", "freeze", "targets"}


def find_project(start, after=None):
    """The nearest `.killverbosity.json` at or above `start`. None if there is
    none.
    """
    here = Path(start).resolve()
    if here.is_file():
        here = here.parent
    chain = [here, *here.parents]
    if after is not None:
        after = Path(after).resolve()
        try:
            chain = chain[chain.index(after) + 1:]
        except ValueError:
            chain = []
    for d in chain:
        p = d / PROJECT_FILE
        if p.is_file():
            return p
    return None


def profile_is_path(spec) -> bool:
    """Whether a `profile` value names a FILE rather than a shipped profile."""
    return "/" in spec or spec.endswith(".json")


def read_project(path):
    """`{"profile": name, "specialists": [names], "refuse": why}`. Refuses
    anything else.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"kill-verbosity: {path} is not valid JSON — {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"kill-verbosity: {path} must hold an object.")
    unknown = sorted(set(data) - PROJECT_KEYS)
    if unknown:
        raise SystemExit(f"kill-verbosity: {path} has keys this build does "
                         f"not know: {unknown}. Known: "
                         f"{sorted(PROJECT_KEYS)}.")
    only = data.get("specialists")
    if only is not None and not (isinstance(only, list)
                                 and all(isinstance(x, str) for x in only)):
        raise SystemExit(f"kill-verbosity: {path}: specialists must be a list "
                         f"of names.")
    profile = data.get("profile")
    if profile is not None and not isinstance(profile, str):
        raise SystemExit(f"kill-verbosity: {path}: profile must be a name or "
                         f"a path.")
    targets = data.get("targets")
    if targets is not None and not (isinstance(targets, list) and targets
                                    and all(isinstance(x, str) and x.strip()
                                            for x in targets)):
        raise SystemExit(f"kill-verbosity: {path}: targets must be a "
                         f"non-empty list of globs, relative to this file. "
                         f"Omit it to declare the whole tree.")
    if profile is not None and profile_is_path(profile) \
            and not os.path.isabs(profile):
        profile = str((path.parent / profile).resolve())
    refuse = data.get("refuse")
    if isinstance(refuse, dict):
        unknown = sorted(set(refuse) - {"paths", "reason"})
        if unknown:
            raise SystemExit(f"kill-verbosity: {path}: refuse has keys this "
                             f"build does not know: {unknown}. Known: "
                             f"['paths', 'reason'].")
        globs = refuse.get("paths")
        reason = refuse.get("reason")
        if not (isinstance(globs, list) and globs
                and all(isinstance(x, str) and x.strip() for x in globs)):
            raise SystemExit(f"kill-verbosity: {path}: refuse.paths must be a "
                             f"non-empty list of globs. Omit the object form "
                             f"and give a bare reason string to refuse the "
                             f"whole tree.")
        if not (isinstance(reason, str) and reason.strip()):
            raise SystemExit(f"kill-verbosity: {path}: refuse.reason must be "
                             f"the reason, as a sentence.")
        refuse = (list(globs), reason)
    elif refuse is not None:
        if not (isinstance(refuse, str) and refuse.strip()):
            raise SystemExit(f"kill-verbosity: {path}: refuse must be the "
                             f"reason, as a sentence.")
        refuse = (None, refuse)
    freeze = data.get("freeze")
    if freeze is not None:
        if not isinstance(freeze, dict):
            raise SystemExit(f"kill-verbosity: {path}: freeze must be an "
                             f"object with `lines` and `reason` — "
                             f"{{\"freeze\": {{\"lines\": [\"^\\\\s*\\\\|\"], "
                             f"\"reason\": \"...\"}}}}. A whole file is "
                             f"`refuse`.")
        unknown = sorted(set(freeze) - {"paths", "lines", "reason"})
        if unknown:
            raise SystemExit(f"kill-verbosity: {path}: freeze has keys this "
                             f"build does not know: {unknown}. Known: "
                             f"['lines', 'paths', 'reason'].")
        globs = freeze.get("paths")
        if globs is not None and not (isinstance(globs, list) and globs
                                      and all(isinstance(x, str) and x.strip()
                                              for x in globs)):
            raise SystemExit(f"kill-verbosity: {path}: freeze.paths must be a "
                             f"non-empty list of globs. Omit it to freeze "
                             f"these lines in every document in the tree.")
        pats = freeze.get("lines")
        if not (isinstance(pats, list) and pats
                and all(isinstance(x, str) and x.strip() for x in pats)):
            raise SystemExit(f"kill-verbosity: {path}: freeze.lines must be a "
                             f"non-empty list of regexes, each matching a line "
                             f"your own gates parse.")
        for p in pats:
            try:
                re.compile(p)
            except re.error as e:
                raise SystemExit(f"kill-verbosity: {path}: freeze.lines "
                                 f"{p!r} is not a regex — {e}")
        reason = freeze.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            raise SystemExit(f"kill-verbosity: {path}: freeze.reason must be "
                             f"the reason, as a sentence.")
        freeze = (list(globs) if globs else None, list(pats), reason)
    return profile, (",".join(only) if only else None), refuse, freeze, \
        (list(targets) if targets else None)


def _matched_glob(globs, project_file, document):
    """The pattern in `globs` that `document` matches, `""` for a declaration
    with no `paths` (which covers the whole tree), None for no match.
    """
    if globs is None:
        return ""
    try:
        rel = Path(document).resolve().relative_to(project_file.parent.resolve())
    except ValueError:
        return None
    for g in globs:
        if rel.match(g):
            return g
    return None


def refused_by(refuse, project_file, document):
    """(glob, reason) when `document` is refused, else None."""
    if not refuse:
        return None
    globs, reason = refuse
    g = _matched_glob(globs, project_file, document)
    return None if g is None else (g or None, reason)


def frozen_by(freeze, project_file, document):
    """(patterns, reason) when `document` has lines frozen, else None."""
    if not freeze:
        return None
    globs, pats, reason = freeze
    return None if _matched_glob(globs, project_file, document) is None \
        else (pats, reason)


def freeze_lines(lines, patterns):
    """1-based line numbers matching any of `patterns`."""
    rx = [re.compile(p) for p in patterns]
    return {i for i, ln in enumerate(lines, 1)
            if any(r.search(ln) for r in rx)}


def blank_frozen(prose, frozen):
    """`prose` with every frozen line emptied, line numbers intact."""
    if not frozen:
        return prose
    return ["" if i in frozen else ln for i, ln in enumerate(prose, 1)]


def in_play(prose, tables, headings, quotes, frozen):
    """(editable, editable_if_nothing_were_frozen), in that order."""
    return (len(editable_lines(blank_frozen(prose, frozen), tables, headings,
                               quotes, frozen)),
            len(editable_lines(prose, tables, headings, quotes)))


def frozen_no_op(record, args, orig, name):
    """(editable, unfrozen, frozen, of, whose) when the freeze emptied the
    editable set, else None.
    """
    if isinstance(record.get("editable"), int) \
            and isinstance(record.get("editable_unfrozen"), int):
        ed, free = record["editable"], record["editable_unfrozen"]
        froze, of = record.get("frozen_lines"), record.get("document_lines")
        whose = "counted by the run, over the paragraphs it folded"
    else:
        hit = getattr(args, "freeze", None)
        if not hit:
            return None
        pats, _why = hit
        body = orig[:-1] if orig.endswith("\n") else orig
        lines = body.split("\n")
        froze, of = freeze_lines(lines, pats), len(lines)
        ed, free = in_play(*mask_for_play(body, name), froze)
        froze = len(froze)
        whose = "counted here from the original, line by line"
    if ed or not free:
        return None
    return (ed, free, froze, of, whose)


def mask_for_play(text, name):
    """`mask()` reordered into the argument order `editable_lines` takes."""
    prose, headings, tables, quotes = mask(text, name)
    return prose, tables, headings, quotes


def frozen_damage(args, orig_lines, new_lines):
    """Frozen lines of the original that are not in the edited file, verbatim."""
    hit = getattr(args, "freeze", None)
    if not hit:
        return []
    pats, _why = hit
    was = Counter(orig_lines[i - 1] for i in freeze_lines(orig_lines, pats))
    return sorted((was - Counter(new_lines)).elements())


def freeze_barrier(args, source_lines):
    """0-based indexes of the frozen lines, as the AUTHOR wrote them."""
    hit = getattr(args, "freeze", None)
    if not hit:
        return frozenset()
    pats, _why = hit
    return frozenset(i - 1 for i in freeze_lines(source_lines, pats))


def report_freeze(args, lines):
    """The frozen line set for this document, announced. Empty set for none."""
    hit = getattr(args, "freeze", None)
    if not hit:
        return set()
    pats, why = hit
    frozen = freeze_lines(lines, pats)
    where = getattr(args, "project", None)
    if not frozen:
        print(f"freeze matched nothing: {args.file} against {list(pats)} "
              f"declared in {where} — NOTHING in this file is protected. "
              f"Fix the patterns before running; a freeze that matches no line "
              f"is a silence a reader takes for protection.", file=sys.stderr)
        return set()
    print(f"frozen: {len(frozen)} of {len(lines)} lines in {args.file} "
          f"matched {list(pats)} in {where}; the rest runs normally",
          file=sys.stderr)
    print(f"kill-verbosity: those lines are not offered to any specialist, and "
          f"they are fold barriers, so they come out byte-identical and the "
          f"paragraph around one is left unfolded — {why}", file=sys.stderr)
    return frozen


from killverbosity.runrecord import (
    ANSWERED_NOT_LOOKED,
    ANSWERED_READ,
    ANSWERED_UNKNOWABLE,
    CROSSCHECK_ASSUMED,
    CROSSCHECK_OBSERVED,
    JOURNAL_SUFFIX,
    RUN_SUFFIX,
    answered_fields,
    answered_tail,
    answering_backends,
    baseline_path,
    cross_writers,
    crosscheck_findings,
    crosscheck_record_path,
    crosscheck_state,
    journal_key,
    journal_path,
    journal_timeouts,
    bank_timeout,
    read_journal,
    read_run_record,
    record_state,
    run_record_path,
    source_fingerprint,
    crosscheck_not_checked_reason,
    write_crosscheck_record,
    write_run_record,
)


VOCAB = {k: (dict(v) if isinstance(v, dict) else list(v))
         for k, v in DEFAULT_VOCAB.items()}
THRESHOLDS = dict(DEFAULT_THRESHOLDS)
PROFILE_NAME = "default"

PROFILE_GENRE = None


def alt(frags):
    """Regex alternation, longest fragment first so no short one shadows a long."""
    return "|".join(sorted(frags, key=len, reverse=True))


def threshold(key):
    return THRESHOLDS[key]


def _merge_list(current, given, where):
    """A profile key either replaces a list or edits it. Never both."""
    if isinstance(given, list):
        return [str(x) for x in given]
    if isinstance(given, dict):
        unknown = set(given) - {"add", "drop"}
        if unknown:
            raise SystemExit(f"kill-verbosity: {where} has {sorted(unknown)}. "
                             f"A profile key takes a list, or an object with "
                             f"'add' and 'drop'.")
        drop = set(map(str, given.get("drop", [])))
        missing = drop - set(current)
        if missing:
            raise SystemExit(f"kill-verbosity: {where} drops {sorted(missing)}, "
                             f"which is not in the default list. Check the "
                             f"spelling — a drop that matches nothing is a "
                             f"profile that does not do what it says.")
        return [x for x in current if x not in drop] + \
               [str(x) for x in given.get("add", [])]
    raise SystemExit(f"kill-verbosity: {where} must be a list or an object "
                     f"with 'add' and 'drop', not {type(given).__name__}.")


def _merge_dict(current, given, where):
    """A profile key that is a table. null on a key drops that row."""
    if not isinstance(given, dict):
        raise SystemExit(f"kill-verbosity: {where} must be an object of "
                         f"key to value, not {type(given).__name__}.")
    out = dict(current)
    for k, v in given.items():
        if v is None:
            if k not in out:
                raise SystemExit(f"kill-verbosity: {where} drops {k!r}, which "
                                 f"is not in the default table.")
            del out[k]
        else:
            out[k] = str(v)
    return out


def load_profile(spec):
    """Read a profile and rebuild everything derived from it."""
    global PROFILE_NAME, PROFILE_GENRE
    path = Path(spec) if profile_is_path(spec) \
        else PROFILE_DIR / f"{spec}.json"
    if not path.is_file():
        known = sorted(q.stem for q in PROFILE_DIR.glob("*.json")) \
            if PROFILE_DIR.is_dir() else []
        raise SystemExit(f"kill-verbosity: no profile at {path}."
                         + (f" Available: {', '.join(known)}." if known else
                            f" No profiles in {PROFILE_DIR}."))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"kill-verbosity: {path} is not valid JSON — {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"kill-verbosity: {path} must hold an object.")

    reserved = {"name", "genre", "thresholds", "shapes", "specialists",
                "langs", "words"}
    unknown = set(data) - set(DEFAULT_VOCAB) - reserved
    if unknown:
        raise SystemExit(
            f"kill-verbosity: {path} has keys this build does not know: "
            f"{sorted(unknown)}. Known: {sorted(set(DEFAULT_VOCAB) | reserved)}.")

    for key in DEFAULT_VOCAB:
        if key not in data:
            continue
        merge = _merge_dict if isinstance(DEFAULT_VOCAB[key], dict) \
            else _merge_list
        VOCAB[key] = merge(VOCAB[key], data[key], f"{path}: {key}")
        if key in VOCAB_IS_REGEX:
            for frag in VOCAB[key]:
                try:
                    re.compile(frag)
                except re.error as e:
                    raise SystemExit(
                        f"kill-verbosity: {path}: {key} has {frag!r}, which is "
                        f"not a valid pattern — {e}.")

    for section in ("thresholds", "shapes", "specialists", "words"):
        if section in data and not isinstance(data[section], dict):
            raise SystemExit(f"kill-verbosity: {path}: {section} must be an "
                             f"object, not {type(data[section]).__name__}.")

    given = data["thresholds"] if "thresholds" in data else {}
    bad = set(given) - set(DEFAULT_THRESHOLDS)
    if bad:
        raise SystemExit(f"kill-verbosity: {path} sets unknown thresholds "
                         f"{sorted(bad)}. Known: {sorted(DEFAULT_THRESHOLDS)}.")
    for k, v in given.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise SystemExit(f"kill-verbosity: {path}: threshold {k} is {v!r}. "
                             f"Every threshold is a positive number.")
        if THRESHOLD_KIND[k] == "share" and v > 1:
            raise SystemExit(f"kill-verbosity: {path}: threshold {k} is {v}. "
                             f"It is a share of a total, so it is above 0 and "
                             f"at most 1. Above 1 it can never be reached and "
                             f"the check it gates never fires.")
        if THRESHOLD_KIND[k] == "count" and int(v) != v:
            raise SystemExit(f"kill-verbosity: {path}: threshold {k} is {v}. "
                             f"It counts words or lines, so it is a whole "
                             f"number.")
    THRESHOLDS.update({k: (int(v) if THRESHOLD_KIND[k] == "count" else v)
                       for k, v in given.items()})

    if "langs" in data:
        active = _merge_list(ACTIVE_LANGS, data["langs"], f"{path}: langs")
        unknown_lang = [c for c in active if c not in LANGS
                        and c not in data.get("words", {})]
        if unknown_lang:
            raise SystemExit(
                f"kill-verbosity: {path} turns on {unknown_lang}, which this "
                f"build has no words for. Known: {sorted(LANGS)}. Add the "
                f"words under 'words' in the same profile.")
        ACTIVE_LANGS[:] = active

    for code, shapes_for_lang in data.get("words", {}).items():
        if not isinstance(shapes_for_lang, dict):
            raise SystemExit(f"kill-verbosity: {path}: words.{code} must be an "
                             f"object of shape name to word list.")
        bank = LANGS.setdefault(code, {})
        for shape, given_words in shapes_for_lang.items():
            if shape not in CHAT_TEMPLATES and shape not in WORD_ONLY_SHAPES:
                raise SystemExit(
                    f"kill-verbosity: {path}: words.{code} names {shape!r}, "
                    f"which takes no word list. Known: "
                    f"{sorted(set(CHAT_TEMPLATES) | WORD_ONLY_SHAPES)}.")
            bank[shape] = _merge_list(bank.get(shape, []), given_words,
                                      f"{path}: words.{code}.{shape}")
            for frag in bank[shape]:
                try:
                    re.compile(frag)
                except re.error as e:
                    raise SystemExit(
                        f"kill-verbosity: {path}: words.{code}.{shape} has "
                        f"{frag!r}, which is not a valid pattern — {e}.")

    PROFILE_NAME = str(data.get("name", path.stem))
    PROFILE_GENRE = data.get("genre")
    if PROFILE_GENRE is not None and PROFILE_GENRE not in GENRES:
        raise SystemExit(f"kill-verbosity: {path}: genre {PROFILE_GENRE!r} is "
                         f"not a kind this build reads. Pick from: "
                         f"{', '.join(GENRES)}.")
    apply_profile(data.get("shapes", {}), data.get("specialists", {}), path)
    return PROFILE_NAME


def reset_profile():
    """Put the default build back. Used between profiles in the selftest."""
    global PROFILE_NAME, PROFILE_GENRE
    VOCAB.clear()
    VOCAB.update({k: (dict(v) if isinstance(v, dict) else list(v))
                  for k, v in DEFAULT_VOCAB.items()})
    THRESHOLDS.clear()
    THRESHOLDS.update(DEFAULT_THRESHOLDS)
    SYNTHETIC.clear()
    SYNTHETIC.update(_BASE_SYNTHETIC)
    SUBSTITUTION.clear()
    SUBSTITUTION.update(_BASE_SUBSTITUTION)
    OCCURRENCE.clear()
    OCCURRENCE.update(_BASE_OCCURRENCE)
    LANGS.clear()
    LANGS.update({k: {s: list(w) for s, w in v.items()}
                  for k, v in DEFAULT_LANGS.items()})
    ACTIVE_LANGS[:] = DEFAULT_ACTIVE_LANGS
    EXISTENCE.clear()
    EXISTENCE.update(_BASE_EXISTENCE)
    SPECIALISTS.clear()
    SPECIALISTS.update(_BASE_SPECIALISTS)
    SWITCHED_OFF.clear()
    PROFILE_NAME = "default"
    PROFILE_GENRE = None
    apply_profile({}, {}, "<defaults>")


def apply_profile(shapes, specialists, where):
    """Rebuild every global that was derived from VOCAB or THRESHOLDS."""
    global CODE_EXT, UNITS, UNIT_RX, SAFE, SUMMARY_HEADING
    global SEGMENTED, CLAIM_RULE, RECOMMENDATION, ABBR, ADVICE
    CODE_EXT = alt(VOCAB["code_ext"])
    UNITS = alt(VOCAB["units"])
    UNIT_RX = re.compile(rf"\b(\d[\d,]*(?:\.\d+)?)\s*(?:-\s*)?({UNITS})"
                         rf"(?![A-Za-z0-9])", re.I)
    UNIT_CANON.clear()
    UNIT_CANON.update(VOCAB["unit_canon"])
    UNIT_FAMILY.clear()
    UNIT_FAMILY.update(VOCAB["unit_family"])
    orphan = sorted(u for u in set(VOCAB["unit_canon"].values())
                    if u not in VOCAB["unit_family"])
    if orphan:
        raise SystemExit(
            f"kill-verbosity: {where}: {orphan} have a spelling but no family, "
            f"so two of them can never be reported as disagreeing. Give each a "
            f'family, or "" if it is alone in its kind.')
    SAFE = set(VOCAB["safe_metaphors"])
    for name, build in FACT_BUILDERS.items():
        FACT_RX[name] = build()
    SEGMENTED = _segmented_rx()
    for name, build in VOCAB_SHAPES.items():
        EXISTENCE[name] = build()
    CHAT.clear()
    CHAT.update(_chat_shapes())
    _wordless = set(CHAT_TEMPLATES) - set(CHAT)
    for sp, (scope, owned) in list(SPECIALISTS.items()):
        if _wordless & set(owned):
            SPECIALISTS[sp] = (scope, tuple(s for s in owned
                                            if s not in _wordless))
    ABBR = _abbr_rx()
    CLAIM_RULE = _claim_rule_rx()
    RECOMMENDATION = _recommendation_rx()
    ADVICE = _advice_rx()
    SUMMARY_HEADING = _summary_heading_rx()
    if not words_for("summary heading"):
        raise SystemExit(f"kill-verbosity: {where}: no language in use has any "
                         f"summary headings, so no summary could ever be found.")
    for const, key in THRESHOLD_CONSTS.items():
        globals()[const] = THRESHOLDS[key]

    for name in shapes.get("drop", []):
        homes = [d for d in (EXISTENCE, SUBSTITUTION, OCCURRENCE, CHAT)
                 if name in d]
        if not homes and name not in SYNTHETIC:
            raise SystemExit(f"kill-verbosity: {where} drops shape {name!r}, "
                             f"which does not exist.")
        for home in homes:
            del home[name]
        SYNTHETIC.discard(name)
        for sp, (scope, owned_shapes) in list(SPECIALISTS.items()):
            if name in owned_shapes:
                SPECIALISTS[sp] = (scope, tuple(s for s in owned_shapes
                                                if s != name))
    for name, pattern in shapes.get("add", {}).items():
        if name in all_shape_names():
            raise SystemExit(f"kill-verbosity: {where} adds shape {name!r}, "
                             f"which already exists. Rename it, or drop the "
                             f"original first.")
        try:
            EXISTENCE[name] = re.compile(pattern, re.I)
        except re.error as e:
            raise SystemExit(f"kill-verbosity: {where}: shape {name!r} is not "
                             f"a valid regex — {e}")
    for name, spec in specialists.items():
        if spec is None:
            if name not in SPECIALISTS:
                raise SystemExit(f"kill-verbosity: {where} drops specialist "
                                 f"{name!r}, which does not exist.")
            for shape in SPECIALISTS[name][1]:
                EXISTENCE.pop(shape, None)
                CHAT.pop(shape, None)
                SUBSTITUTION.pop(shape, None)
                OCCURRENCE.pop(shape, None)
                SYNTHETIC.discard(shape)
            del SPECIALISTS[name]
            SWITCHED_OFF[name] = Path(where).stem or where
            continue
        if not isinstance(spec, dict) or "shapes" not in spec:
            raise SystemExit(f"kill-verbosity: {where}: specialist {name!r} "
                             f"needs {{'scope': …, 'shapes': [...]}}.")
        scope = spec.get("scope", "section")
        if scope not in ("section", "document"):
            raise SystemExit(f"kill-verbosity: {where}: specialist {name!r} "
                             f"has scope {scope!r}. Use 'section' or 'document'.")
        if not (SPECIALIST_DIR / f"{name}.md").is_file():
            raise SystemExit(f"kill-verbosity: {where}: specialist {name!r} has "
                             f"no prompt at {SPECIALIST_DIR / f'{name}.md'}.")
        SPECIALISTS[name] = (scope, tuple(spec["shapes"]))

    owned = [s for _, shp in SPECIALISTS.values() for s in shp]
    if len(owned) != len(set(owned)):
        dupes = sorted({s for s in owned if owned.count(s) > 1})
        raise SystemExit(f"kill-verbosity: {where}: {dupes} have two owners. "
                         f"Each shape goes to exactly one specialist.")
    unrouted = all_shape_names() - set(owned)
    if unrouted:
        raise SystemExit(f"kill-verbosity: {where}: {sorted(unrouted)} have no "
                         f"specialist. Add each to one specialist's shape list.")
    unknown = set(owned) - all_shape_names()
    if unknown:
        raise SystemExit(f"kill-verbosity: {where}: a specialist claims "
                         f"{sorted(unknown)}, which is not a shape.")



TREE_CHARS = set("├│└┌┐┘─┬┴┼")
CODE_EXT = alt(VOCAB["code_ext"])
UNITS = alt(VOCAB["units"])

UNIT_CANON = dict(VOCAB["unit_canon"])
UNIT_FAMILY = dict(VOCAB["unit_family"])

UNIT_RX = re.compile(rf"\b(\d[\d,]*(?:\.\d+)?)\s*(?:-\s*)?({UNITS})"
                     rf"(?![A-Za-z0-9])", re.I)


def canon_unit(u):
    """One spelling per unit. '' when two of it could never disagree."""
    low = u.lower()
    if low in UNIT_CANON:
        return UNIT_CANON[low]
    base = low[:-1] if low.endswith("s") and len(low) > 1 else low
    return UNIT_CANON.get(base, "")


def number_token(val):
    """The one token standing for a number and its unit."""
    v = re.sub(r"[\s-]+", "", val)
    m = re.fullmatch(r"([\d.,]+)(.*)", v)
    if not m:
        return v
    num, unit = m.groups()
    key = unit.lower().rstrip("s") or unit.lower()
    return num + UNIT_CANON.get(key, unit)


from killverbosity.pointers import (
    HTML_COMMENT,
    heading_name,
)


SWAP_WORD = re.compile(r"[A-Za-z][\w'-]*|\d[\d,._]*")

MEANING_SETS = {
    "a quantifier": frozenset({
        "every", "all", "any", "always", "never", "no", "none", "not",
        "nothing", "neither", "nor", "only", "each", "both", "some", "most"}),
    "a modal": frozenset({
        "must", "may", "might", "can", "cannot", "could", "should", "shall",
        "will", "would", "need", "needs", "needed", "required", "optional",
        "holds", "hold"}),
    "a claim verb": frozenset({
        "proves", "proved", "proven", "prove", "shows", "showed", "shown",
        "show", "demonstrates", "demonstrated", "demonstrate", "establishes",
        "established", "establish", "tests", "tested", "test", "checks",
        "checked", "check", "suggests", "suggested", "suggest", "indicates",
        "indicated", "indicate", "implies", "implied", "imply", "confirms",
        "confirmed", "confirm", "means", "meant", "mean"}),
    "a reporting verb": frozenset({
        "said", "say", "says", "state", "states", "stated", "note", "notes",
        "noted", "report", "reports", "reported",
        "claim", "claims", "claimed", "describe", "describes", "described"}),
    "a permission verb": frozenset({
        "allows", "allow", "allowed", "permits", "permit", "permitted",
        "enables", "enable", "enabled", "admits", "admit"}),
}

COPULA = frozenset({"is", "are", "was", "were", "be", "been", "being",
                    "has", "have", "had"})


def aligned_swaps(old, new):
    """Every 1<->1 word substitution between two texts. `(was, now)` pairs."""
    ow, nw = SWAP_WORD.findall(old), SWAP_WORD.findall(new)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, ow, nw, autojunk=False).get_opcodes():
        if tag == "replace" and (i2 - i1) == 1 and (j2 - j1) == 1:
            yield ow[i1], nw[j1]


PLAIN_WORDS = frozenset({
    "stay", "stays", "stayed", "keep", "keeps", "kept", "hand",
    "use", "uses", "used", "need", "needs", "needed", "put", "puts",
    "make", "makes", "made", "get", "gets", "got", "have",
    "help", "helps", "start", "starts", "end", "ends", "hold", "holds",
    "let", "lets", "try", "tries", "ask", "asks", "tell", "tells",
    "worse", "enough", "wrong", "right", "same",
})


def formal_swaps(old, new):
    """Plain words replaced by longer ones. `(was, now)` pairs."""
    out = []
    for was, now in aligned_swaps(old, new):
        if was.lower() == now.lower() or same_number_stem(was, now):
            continue
        if was.lower() in PLAIN_WORDS and len(now) > len(was):
            out.append((was, now))
    return out


def same_number_stem(was, now):
    """`check -> checks` and `test's -> test`: a number change, not a claim."""
    def forms(w):
        w = w.lower()
        out = {w}
        for suf in ("'s", "es", "s"):
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                out.add(w[:-len(suf)])
        return out
    return bool(forms(was) & forms(now))


def meaning_swaps(old, new):
    """Substitutions crossing one of `MEANING_SETS`. `(was, now, what)`."""
    out = []
    for was, now in aligned_swaps(old, new):
        if was.lower() == now.lower() or same_number_stem(was, now):
            continue
        for what, vocab in MEANING_SETS.items():
            if was.lower() in vocab or now.lower() in vocab:
                out.append((was, now, what))
                break
        else:
            if was.lower() in COPULA and now.lower() not in COPULA:
                out.append((was, now, "a relation for an action"))
    return out


def output_line(merged, new):
    """Where a reworded line ENDED UP in the text that ships, or None."""
    target = " ".join(new.split())
    if not target:
        return None
    flat = [" ".join(l.split()) for l in merged]
    joined = " ".join(flat)
    if joined.count(target) != 1:
        return None
    pos, run = joined.find(target), 0
    for i, t in enumerate(flat, 1):
        run += len(t) + 1
        if pos < run:
            return i
    return None


def word_swaps(applied, merged=None):
    """Every place an edit put one word where another had been."""
    out = []
    for ln, why, _kind, pair in applied:
        if not pair:
            continue
        old, new = pair
        for was, now in aligned_swaps(old, new):
            row = {"line": ln, "by": why.split(":")[0],
                   "was": was, "now": now,
                   "in": swap_excerpt(new, now)}
            if merged is not None:
                row["line_out"] = output_line(merged, new)
            out.append(row)
    return out


def swap_excerpt(new, now, width=70):
    """The new text around the swapped word, not the start of the line."""
    flat = " ".join(new.split())
    m = re.search(rf"(?<!\w){re.escape(now)}(?!\w)", flat)
    if not m or len(flat) <= width:
        return flat[:width]
    mid = (m.start() + m.end()) // 2
    lo = max(0, min(mid - width // 2, len(flat) - width))
    return ("…" if lo else "") + flat[lo:lo + width] + (
        "…" if lo + width < len(flat) else "")


def word_count(text):
    """Words a reader sees."""
    return len(HTML_COMMENT.sub(" ", text).split())


def fence_delim(line):
    """The fence token this line carries and whether it is delimiter-only."""
    m = re.match(r"^ {0,3}(`{3,}|~{3,})[ \t]*(.*)$", line)
    return (None, False) if not m else (m.group(1), not m.group(2).strip())


def fence_closes(tok, opened):
    """True when `tok` can close a fence opened with `opened`."""
    return tok[0] == opened[0] and len(tok) >= len(opened)


CODE_SPAN = re.compile(r"(`+)(?:(?!\1)[^\n])+\1")
INLINE_QUOTE = re.compile(r"\"[^\"\n]{2,400}\"|“[^”\n]{2,400}”")

QUOTE_CLOSER = {'"': '"', "“": "”"}


def quote_carry_head(line, carry):
    """Blank the head of `line` that belongs to a quotation carried in from
    the line above. -> (line, whole_line_is_inside_it).
    """
    if not carry:
        return line, False
    close = line.find(QUOTE_CLOSER[carry])
    if close < 0:
        return " " * len(line), True
    return " " * (close + 1) + line[close + 1:], False


def mask_quotes(line, carry=""):
    """Blank "quotations" to spaces of the same width. -> (masked, still_open)."""
    out, still = quote_carry_head(line, carry)
    if still:
        return out, carry
    out = INLINE_QUOTE.sub(lambda m: " " * len(m.group(0)), out)
    if out.count('"') % 2:
        at = out.rfind('"')
    elif out.count("“") > out.count("”"):
        at = out.rfind("“")
    else:
        return out, ""
    return out[:at] + " " * (len(out) - at), out[at]


def quoted_claims(lines):
    """Every same-line inline-quoted span in the document's prose, with its
    line number.
    """
    out, fence, carry = [], None, ""
    pending = None
    for i, ln in enumerate(lines, 1):
        tok, bare = fence_delim(ln)
        if tok:
            if fence is None:
                fence = tok
            elif fence_closes(tok, fence) and bare:
                fence = None
            carry, pending = "", None
            continue
        if fence is not None:
            carry, pending = "", None
            continue
        s = ln.strip()
        if not s or s.startswith(("#", ">")) or re.match(r"^ {0,3}\|", ln):
            carry, pending = "", None
            continue
        scan, inside = quote_carry_head(ln, carry)
        if pending is not None:
            if inside:
                pending[1].append(ln.strip())
            else:
                close = ln.find(QUOTE_CLOSER[carry])
                pending[1].append(ln[:close + 1].strip())
                out.append((pending[0], " ".join(t for t in pending[1] if t)))
                pending = None
        for m in INLINE_QUOTE.finditer(scan):
            out.append((i, m.group(0)))
        _masked, carry_out = mask_quotes(ln, carry)
        if carry_out and not inside:
            rest = INLINE_QUOTE.sub(lambda m: " " * len(m.group(0)), scan)
            idx = rest.rfind(carry_out)
            pending = (i, [ln[idx:].strip()]) if idx >= 0 else None
        carry = carry_out
    return out


HASHLIKE = re.compile(r"^`+(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}`+$",
                      re.I)


TICK_RUN = re.compile(r"`+")


def mask_code_spans(line, carry=0):
    """Blank `code spans` to spaces of the same width. -> (masked, open_run)."""
    out = line
    want = 1 if carry is True else int(carry or 0)
    if want:
        close = next((m for m in TICK_RUN.finditer(out)
                      if len(m.group(0)) == want), None)
        if close is None:
            return " " * len(out), want
        out = " " * close.end() + out[close.end():]
    out = CODE_SPAN.sub(
        lambda m: m.group(0) if HASHLIKE.match(m.group(0))
        else " " * len(m.group(0)), out)
    probe = CODE_SPAN.sub(lambda m: " " * len(m.group(0)), out)
    runs = list(TICK_RUN.finditer(probe))
    if not runs:
        return out, 0
    open_run = runs[-1]
    return (out[:open_run.start()] + " " * (len(out) - open_run.start()),
            len(open_run.group(0)))


LINE_NUMBER_PASTE = re.compile(r"^\s{0,6}\d+\t")

KV_MARK = re.compile(r"<!--\s*kv:([A-Za-z_-]*)")

TIMESTAMP_HEAD = re.compile(
    r"^[\[(]?\d{1,2}:\d{2}(?::\d{2})?"
    r"(?:\s*[-–—]\s*\d{1,2}:\d{2}(?::\d{2})?)?[\])]?"
    r"(?:\s*[-–—:]?\s*\S[^\n]{0,60})?$")


SPEAKER_TIME_HEAD = re.compile(
    r"^(?:[A-Z][\w.'’-]*)(?:\s[A-Z][\w.'’-]*){0,3}[ \t]{2,}"
    r"[\[(]?(\d{1,2}:\d{2}(?::\d{2})?)[\])]?$")


def stamp_head(txt):
    """The time in a transcript heading, whichever end it is written at."""
    t = txt.strip()
    if TIMESTAMP_HEAD.match(t):
        return t
    m = SPEAKER_TIME_HEAD.match(t)
    return m.group(1) if m else None


_STAMP_LEAD = re.compile(r"^[\[(]?(\d{1,2}):(\d{2})(?::(\d{2}))?")


def stamp_seconds(txt):
    m = _STAMP_LEAD.match(txt.strip())
    if not m:
        return None
    a, b, c = m.group(1), m.group(2), m.group(3)
    return (int(a) * 3600 + int(b) * 60 + int(c)) if c else (int(a) * 60 + int(b))


TRANSCRIPT_START_MAX = 300


def transcript_stamps(headings):
    """Indexes of headings that are a transcript's elapsed-time marks."""
    at = {i: stamp_seconds(stamp_head(txt)) for i, _, txt in headings
          if stamp_head(txt)}
    secs = [v for v in at.values() if v is not None]
    if len(at) < 2 or not secs or min(secs) > TRANSCRIPT_START_MAX:
        return set()
    return set(at)


def timed_but_not_transcript(headings):
    """True for the state the bar creates: timestamp headings, none near zero."""
    secs = [stamp_seconds(stamp_head(txt)) for i, _, txt in headings
            if stamp_head(txt)]
    secs = [v for v in secs if v is not None]
    return len(secs) >= 2 and min(secs) > TRANSCRIPT_START_MAX


def transcript_speech(lines, headings):
    """Line indexes holding words a named person said."""
    head_at = {i: txt for i, _, txt in headings}
    stamps = transcript_stamps(headings)
    if not stamps:
        return set()

    out, under = set(), False
    for i in range(len(lines)):
        if i in head_at:
            under = i in stamps
        elif under and lines[i].strip():
            out.add(i)
    for i in stamps:
        j = i - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j >= 0 and j not in head_at:
            out.add(j)
    return out


def parser_blocks(text):
    """What CommonMark says is a heading, a table or a quotation. 1-based."""
    heads, tables, quotes, want = {}, set(), set(), None
    for t in mdblocks.parse(text):
        if t.type == "inline" and want is not None:
            heads[want[0]] = (want[1], t.content, want[2])
            want = None
            continue
        if t.map is None:
            continue
        lo, hi = t.map[0] + 1, t.map[1]
        if t.type == "heading_open":
            want = (lo, int(t.tag[1:]), hi)
        elif t.type == "table_open":
            tables |= set(range(lo, hi + 1))
        elif t.type == "blockquote_open":
            quotes |= set(range(lo, hi + 1))
    return heads, tables, quotes


def mask(text, label="input"):
    """Blank every line that is not prose, keeping line numbers intact."""
    lines = text.split("\n")

    stamped = sum(1 for ln in lines if LINE_NUMBER_PASTE.match(ln))
    body = sum(1 for ln in lines if ln.strip())
    if body >= 20 and stamped > body / 2:
        raise UsageError(
            f"{label}: {stamped} of {body} lines start with a line number. "
            f"This looks like a paste from a file viewer, and every word count "
            f"here would include the numbers. Strip them and rerun.")

    prose = [""] * len(lines)
    headings, tables, quotes = [], [], []
    fence = fence_line = None
    code_open, quote_open, last_prose = False, "", -2
    list_indent = []
    frontmatter = bool(lines) and lines[0].strip() == "---"

    for i, ln in enumerate(lines):
        s = ln.strip()

        if frontmatter:
            if i and s == "---":
                frontmatter = False
            continue

        tok, bare = fence_delim(ln)
        if tok:
            if fence is None:
                fence, fence_line = tok, i + 1
            elif fence_closes(tok, fence) and bare:
                fence = None
            continue
        if fence is not None:
            continue

        h = re.match(r"^ {0,3}(#{1,6})(?:\s+(.*?))?\s*#*$", ln.rstrip())
        if h:
            headings.append((i, len(h.group(1)), (h.group(2) or "").strip()))
            list_indent = []
            continue

        if re.match(r"^ {0,3}\|", ln):
            cells = " ".join(c.strip() for c in s.strip("|").split("|"))
            if cells.strip("-: "):
                tables.append((i + 1, cells))
            continue

        if s.startswith(">"):
            body = s.lstrip("> ").strip()
            if body:
                quotes.append((i + 1, body))
            continue
        if not s:
            continue
        if s.startswith(("---", "***", "___")) and len(set(s)) <= 2:
            continue
        if any(c in ln for c in TREE_CHARS):
            continue
        mark = re.match(r"( *)([-*+]|\d+[.)])(\s+)", ln)
        if mark:
            at = len(mark.group(1))
            while list_indent and list_indent[-1] > at:
                list_indent.pop()
            list_indent.append(at + len(mark.group(2)) + len(mark.group(3)))
        elif not ln.startswith(" "):
            list_indent = []
        floor = list_indent[-1] if list_indent else 0
        if (len(ln) - len(ln.lstrip(" "))) >= floor + 4 and not mark:
            continue

        code_in = code_open if i == last_prose + 1 else 0
        blanked, code_open = mask_code_spans(ln, code_in)
        quote_in = quote_open if i == last_prose + 1 else ""
        blanked, quote_open = mask_quotes(blanked, quote_in)
        prose[i] = (ln if not blanked.strip() and not code_open and not quote_open
                    and not code_in and not quote_in
                    else blanked)
        last_prose = i

    if fence is not None:
        opener = lines[fence_line - 1] if fence_line <= len(lines) else ""
        before = lines[fence_line - 2].strip() if fence_line > 1 else ""
        wrapped = bool(before) and not before.startswith("#")
        how = (" These backticks start a wrapped line, so they read as a fence "
               "and a renderer swallows the rest of the sentence. Rewrap the "
               "paragraph so they are not first on the line, or escape them."
               if wrapped else
               " Close it, or delete it if it was never meant to open a block.")
        raise UsageError(
            f"{label}: code fence opened at line {fence_line} never closes. "
            f"Everything after it would be skipped.\n"
            f"  L{fence_line}  {opener.strip()[:90]}\n"
            f" {how}")
    if frontmatter:
        raise UsageError(
            f"{label}: frontmatter opened at line 1 never closes. The whole file "
            f"would be skipped. Fix the '---' and rerun.")

    _ph, _pt, _pq = parser_blocks(text)
    _head_at = {h[0] + 1 for h in headings}
    for _lo, (_lvl, _txt, _hi) in sorted(_ph.items()):
        if _lo in _head_at or not prose[_lo - 1].strip():
            continue
        headings.append((_lo - 1, _lvl, _txt))
        for i in range(_lo, _hi + 1):
            prose[i - 1] = ""
    headings.sort()
    _table_at = {t[0] for t in tables}
    for i in sorted(_pt):
        if i in _table_at or not prose[i - 1].strip():
            continue
        tables.append((i, prose[i - 1].strip()))
        prose[i - 1] = ""
    tables.sort()
    _quote_at = {q[0] for q in quotes}
    for i in sorted(_pq):
        if i in _quote_at or not prose[i - 1].strip():
            continue
        quotes.append((i, prose[i - 1].strip()))
        prose[i - 1] = ""

    for i in transcript_speech(lines, headings):
        if prose[i].strip():
            quotes.append((i + 1, prose[i].strip()))
            prose[i] = ""
    quotes.sort()

    markers = ("keep", "allow", "allow-shape", "freeze", "end", "summary")
    live = ({i + 1 for i, p in enumerate(prose) if p.strip()}
            | {h[0] + 1 for h in headings}
            | {t[0] for t in tables} | {q[0] for q in quotes})
    typos = [(i + 1, m.group(1)) for i, ln in enumerate(lines)
             if i + 1 in live
             for m in KV_MARK.finditer(CODE_SPAN.sub(" ", ln))
             if m.group(1) not in markers]
    if typos:
        n, name = typos[0]
        more = f" ({len(typos)} in all)" if len(typos) > 1 else ""
        raise UsageError(
            f"{label}: line {n} writes 'kv:{name}', which is not a marker and "
            f"protects nothing{more}. They are "
            + ", ".join(f"kv:{m}" for m in markers) + ".")

    marks = [i + 1 for i, ln in enumerate(lines) if i + 1 in live
             and SUMMARY_MARK.search(CODE_SPAN.sub(" ", ln))]
    first = 1 if marks and _summary.has_title(headings, prose,
                                              _summary_rules()) else 0
    if marks and first < len(headings):
        stop = headings[first][0] + 1
        if late := [n for n in marks if n >= stop]:
            raise UsageError(
                f"{label}: line {late[0]} writes 'kv:summary' at or below the "
                f"first section heading (line {stop}). It marks the opening "
                f"prose as the summary, so it goes above that heading.")

    return prose, headings, tables, quotes


def countable(text, label="input"):
    """Prose, with a transcript's turns put back, for counting sentences."""
    prose, headings, _tables, quotes = mask(text, label)
    src = text.splitlines()
    said = transcript_speech(src, headings) & {n - 1 for n, _t in quotes}
    if not said:
        return prose
    return [src[i] if i in said else p for i, p in enumerate(prose)]


def with_spans(prose, text):
    """Prose with code spans put back, for measuring and printing length."""
    src = text.splitlines()
    return [INLINE_QUOTE.sub(lambda m: " " * len(m.group(0)), src[i])
            if i < len(src) and prose[i].strip() else prose[i]
            for i in range(len(prose))]


def _abbr_rx():
    words = words_for("abbreviation")
    if not words:
        return re.compile(r"(?!)")
    return re.compile(rf"\b(?:{alt(words)})\.$")


def sentences(chunk_lines):
    """Split prose into sentences. Yields (line_no, sentence)."""
    for first, _last, sent in sentence_spans(chunk_lines):
        yield first, sent


def sentence_spans(chunk_lines, rows=()):
    """Split prose into sentences. Yields (first_line, last_line, sentence)."""
    rows = set(rows)
    para = []
    for i, ln in chunk_lines:
        if not ln.strip():
            yield from _emit(para)
            para = []
            continue
        bullet = re.match(r"\s*(?:[-*+]|\d+[.)]|[a-zA-Z][.)])\s+", ln)
        if bullet and para:
            yield from _emit(para)
            para = []
        para.append((i, HTML_COMMENT.sub(
            "", ln[bullet.end():] if bullet else ln).strip()))
        if i in rows:
            yield from _emit(para)
            para = []
    yield from _emit(para)


def _emit(para):
    """Split one paragraph and map each sentence back to its own source lines."""
    if not para:
        return
    text = " ".join(t for _, t in para)
    starts, pos = [], 0
    for line_no, t in para:
        starts.append((pos, line_no))
        pos += len(t) + 1

    def at_line(off):
        line_no = starts[0][1]
        for start, ln in starts:
            if start > off:
                break
            line_no = ln
        return line_no

    cursor = 0
    for sent in _split(text):
        at = text.find(sent, cursor)
        if at < 0:
            at = cursor
        cursor = at + len(sent)
        yield at_line(at), at_line(max(at, cursor - 1)), sent


_SENT_END = re.compile(
    r"(?:(?<=[.!?]\*\*)|(?<=[.!?])|(?<=[.!?]\")|(?<=[.!?]')|(?<=[.!?]”)"
    r"|(?<=[.!?]’)|(?<=[.!?]\*)|(?<=[.!?]`)|(?<=[.!?]\)))"
    r"\s+(?=[A-Z\"'`(\[“*])")


def _split(text):
    """Yield sentences. The caller maps them back to source lines."""
    buf = ""
    for p in _SENT_END.split(text):
        buf = f"{buf} {p}".strip() if buf else p
        if not ABBR.search(buf):
            yield buf
            buf = ""
    if buf:
        yield buf


DATE_HEAD = re.compile(
    r"^\s*(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}"
    r"|\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},\s*\d{4})")
TASK_LINE = re.compile(r"^\s*[-*+]\s*\[[ xX]\]")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")

PHASE_HEAD = re.compile(
    r"^\s*(?:phase|milestone|sprint|workstream|week)\s+"
    r"(?:\d+|[IVX]+\b|one|two|three|four|five|six)\b"
    r"|^\s*(?:Q[1-4]|H[12])\s+(?:of\s+)?20\d\d\b"
    r"|^\s*(?:roadmap|timeline|rollout plan|delivery plan|release plan)"
    r"\s*(?:$|[-\u2013:(])",
    re.I)

GENRES = ("transcript", "log", "checklist", "reference", "roadmap", "prose")

_STATUS_STATE_CELL = re.compile(r"^\**\s*(?:status|state)\s*\**$", re.I)


def _table_header_has_status(row_line):
    """True when a `| ... |` row (the table's header) has a Status/State cell."""
    cells = row_line.strip().strip("|").split("|")
    return any(_STATUS_STATE_CELL.match(c) for c in cells)


def _section_genre(heading_text, body):
    """One section's kind, from its heading and its own lines."""
    if heading_text is not None and TIMESTAMP_HEAD.match(heading_text.strip()):
        return "transcript"
    if heading_text is not None and DATE_HEAD.match(heading_text):
        return "log"
    if heading_text is not None and PHASE_HEAD.match(heading_text):
        return "roadmap"
    if not body:
        return None
    if sum(1 for ln in body if TASK_LINE.match(ln)) / len(body) \
            >= THRESHOLDS["genre_task_lines"]:
        return "checklist"
    table_lines = [ln for ln in body if TABLE_ROW.match(ln)]
    if len(table_lines) / len(body) >= THRESHOLDS["genre_table_rows"]:
        if table_lines and _table_header_has_status(table_lines[0]):
            return "checklist"
        return "reference"
    return "prose"


_GENRE_MARK = {
    "checklist": lambda ln: TASK_LINE.match(ln) or TABLE_ROW.match(ln),
    "reference": lambda ln: TABLE_ROW.match(ln),
}


def genre_mix(lines, headings):
    """How many body lines each genre covers. Weighted by size, not by count."""
    heads = {i: txt for i, _, txt in headings}
    mix, cur_head, body = Counter(), None, []

    def close():
        kind = _section_genre(cur_head, body)
        if not kind:
            return
        mark = _GENRE_MARK.get(kind)
        if mark is None:
            mix[kind] += len(body)
            return
        hit = sum(1 for ln in body if mark(ln))
        mix[kind] += hit
        if len(body) > hit:
            mix["prose"] += len(body) - hit

    for i, ln in enumerate(lines):
        if i in heads:
            close()
            cur_head, body = heads[i], []
        elif ln.strip():
            body.append(ln)
    close()
    return mix


def detect_genre(lines, headings):
    """Which kind of document this is."""
    mix = genre_mix(lines, headings)
    total = sum(mix.values())
    if not total:
        return "prose"
    kind, covered = mix.most_common(1)[0]
    if covered / total < THRESHOLDS["genre_majority"]:
        return "prose"
    return kind




def _corporate_header_rx():
    return re.compile(rf"^(?:{alt(VOCAB['corporate_headers'])})\s*$", re.I)


def _jargon_rx():
    """Two lists, one shape."""
    return re.compile(
        rf"\b(?:{alt(VOCAB['filler'] + VOCAB['domain_jargon'])})\b", re.I)


def _bare_id_rx():
    """A naked id with no gloss after it."""
    return re.compile(
        rf"(?<![\w.])(?:{alt(VOCAB['id_families'])})(?!\w)(?!\.\w)(?!\s*[—(:])"
        r"|\([A-Z]\d{1,4}(?:\s*[–—-]\s*[A-Z]?\d{1,4})?\)"
        r"|\b(?:per |see )?finding [A-Z]?\d{1,4}\b(?!\s*[—(:])")


_DEFINITE = re.compile(r"\b(?:the|that|this|these|those)\s+$", re.I)
_NOT_A_NOUN = {
    "for", "of", "in", "on", "at", "to", "with", "from", "by", "as", "and",
    "or", "but", "is", "was", "were", "are", "be", "been", "has", "had",
    "have", "does", "did", "do", "showed", "shows", "says", "said", "found",
    "gave", "made", "ran", "above", "below", "here", "there", "than", "then",
    "which", "that", "who", "when", "where", "while", "because", "so",
}


def _classifying(line, m) -> bool:
    """True when an id modifies the noun after it rather than standing alone."""
    if m.group(0).lstrip().startswith("("):
        return False
    after = line[m.end():]
    nxt = re.match(r"\s+([a-z][\w-]*)", after)
    if not nxt or nxt.group(1) in _NOT_A_NOUN:
        return False
    return not _DEFINITE.search(line[:m.start()])


SHA_REF = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")

_VERIFY_VERB = (r"check(?:ed|s)?|verif(?:ied|y|ies)|confirm(?:ed|s)?|measured"
                r"|tested|reproduced|traced|reviewed|read|compared|validated")

VERIFIED_AGAINST = re.compile(r"\b(?:" + _VERIFY_VERB + r")\b[^.!?]{0,80}$",
                              re.I)

SOURCE_LABEL = re.compile(r"(?:^|[.!?]\s)\s*[-*]?\s*sources?\s*:[^.!?]{0,80}$",
                          re.I)

VERIFIED_AFTER = re.compile(r"^[^.!?]{0,80}?\b(?:" + _VERIFY_VERB + r")\b",
                            re.I)


def _cited_as_evidence(line, lo, hi):
    """Is the ref at [lo:hi) cited as evidence, or named as process?"""
    return bool(VERIFIED_AGAINST.search(line[:lo])
                or SOURCE_LABEL.search(line[:lo])
                or VERIFIED_AFTER.search(line[hi:]))


def _cites_a_ref(line):
    """Does any sha on this line carry one of the three evidence marks?"""
    return any(_cited_as_evidence(line, m.start(), m.end())
               for m in SHA_REF.finditer(line))


def _process_leak_rx():
    """How the document was made instead of what it says."""
    tools = alt(VOCAB["tooling_names"])
    return re.compile(
        r"\b(?:cross[- ]?check(?:ed|ing)? (?:by|with)|cross[- ]?review(?:ed)?"
        rf"|(?:{tools}|the agents?|both models?|all three models?)"
        rf"(?:\s*(?:,|and)\s*(?:{tools}))*\s+(?:both\s+|all\s+)?"
        r"(?:said|says|suggested?|flagged|agreed|accepted?|noted|proposed|recommend(?:ed|s)?)"
        rf"|(?:reviewed|verified|confirmed) by (?:{tools}|an? external"
        r"|(?:two|three|both|all) (?:external )?(?:models?|agents?|llms?))"
        r"|(?:the )?(?:earlier |previous |above |this )?"
        r"(?:transcript|thread|conversation|chat log|session)s?\s+"
        r"(?:say|says|said|show|shows|showed|note[sd]?|recommend(?:ed|s)?|flagged)"
        rf"|per (?:{tools}|the reviewer)|external model|second opinion from)", re.I)


VOCAB_SHAPES = {
    "corporate header": _corporate_header_rx,
    "jargon": _jargon_rx,
    "bare internal id": _bare_id_rx,
    "process leak": _process_leak_rx,
}

_ROLE_ACTOR = (r"(?:the|a|an|our|their)\s+(?:\w+[- ]){0,2}?"
               r"(?:reviewer|implementer|author|maintainer|editor"
               r"|contributor|committer|engineer|developer|team)s?\b")

DEADLINE_WORD = re.compile(
    r"\b(?:due|deadline|target(?:s|ed|ing)?|ETA|SLA|no later than"
    r"|cut[- ]?off|by (?:the )?end of|must (?:land|ship|be done)"
    r"|remains? open|still open|not (?:yet )?done)\b", re.I)

EXISTENCE = {
    "frame": re.compile(
        r"\b(?:one (?:more|caveat|note|thing|concern|honest note|last thing)\b[^.\n]{0,60}?"
        r"(?:before|because|worth|that shapes|to flag)"
        r"|it(?:'s| is) worth (?:noting|knowing|saying|mentioning)"
        r"|before we (?:trust|dive|get into|go further|look)"
        r"|a (?:quick |brief )?(?:note|word|caveat) (?:on|about|before))", re.I),
    "hedge": re.compile(
        r"\b(?:this is not the whole story|that said,|having said that|that'?s not to say"
        r"|it should be noted|needless to say|to be fair,|it(?:'s| is) important to note"
        r"|arguably|somewhat|relatively speaking)", re.I),
    "purpose hedge": re.compile(
        r"\b(?:aim(?:s|ed|ing)? to|aimed at|seek(?:s|ing)? to|sought to"
        r"|(?:is|are|was|were|being)\s+(?:intended|meant|designed)\s+to"
        r"|intended to|meant to|designed to"
        r"|striv(?:es|ed|ing) to|hop(?:es|ed|ing) to|serves? to"
        r"|look(?:s|ing|ed)? to (?!the\b|a\b|an\b|it\b|us\b|them\b|you\b|me\b"
        r"|him\b|her\b|our\b|your\b|their\b|his\b|its\b)"
        r"|(?:should|will|would|can|may) help\b|helps? to\b)", re.I),
    "wrapper": re.compile(
        r"\b(?:[A-Z][a-z]+'s (?:point|concern|comment|feedback|note|observation) about"
        r"|I (?:think|believe|would say|feel) that\b|I (?:think|believe)\b"
        r"|what I(?:'d| would) say is)"),
    "agreement move": re.compile(
        r"\b(?:good (?:point|catch|call)[,.]? (?:and|but)|you'?re right (?:that|,)"
        r"|I agree (?:that|with)|fair (?:point|enough)[,.])", re.I),
    "empty framing": re.compile(
        r"\b(?:in order to|this (?:section|document) describes|the purpose of this"
        r"|as (?:previously )?(?:mentioned|noted|discussed)|as we (?:can see|have seen)"
        r"|it goes without saying)", re.I),
    "echo": re.compile(
        r"^\s*(?:#+\s*(?!(?:tl;?dr|key takeaways?|highlights)\b)|\*\*)?"
        r"(?:In summary|In conclusion|Key takeaway|To summar|TL;DR"
        r"|Overall,|To recap|Bottom line)", re.I),
    "corporate header": _corporate_header_rx(),
    "jargon": _jargon_rx(),
    "bare internal id": _bare_id_rx(),
    "worklog": re.compile(
        r"^\s*(?:#+\s*)?(?:What changed|Changelog|Work ?log|Update \d|Revision history"
        r"|Current status:|As of \d{4}-\d{2}|Progress:)"
        r"|\b(?:fixed|added|removed|deleted|dropped|shipped|landed|merged"
        r"|closed|filed|done|measured|re-?derived|re-?measured|re-?checked"
        r"|verified|reviewed|updated|implemented|reproduced|retracted"
        r"|corrected)\b[^.!?\n]{0,24}?"
        r"(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}\b"
        r"|\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
        r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2})"
        r"|(?P<dated_actor>(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}\b)[^.!?\n]{0,24}?"
        r"\bby (?:@|(?-i:[A-Z][a-z])|" + _ROLE_ACTOR + r"))", re.I),
    "phase plan": re.compile(
        r"(?:^[ \t>]*(?:#{1,6}\s*|[-*+]\s*|\d+[.)]\s*)?(?:\*\*)?)"
        r"(?:phase|milestone|sprint|workstream)\s+"
        r"(?:\d+|[IVX]+\b|one|two|three|four|five|six)\b"
        r"|\b(?:Q[1-4]|H[12])\s+(?:of\s+)?20\d\d\b", re.I | re.M),
    "task list": re.compile(r"^[ \t>]*(?:[-*+]|\d+[.)])\s*\[ \]", re.M),
    "estimate": re.compile(
        r"\b(?:\d+(?:[.,]\d+)?|a|one|two|three|four|five|six|seven|eight"
        r"|nine|ten|a few|several)\s*(?:[-\u2013]|to)?\s*(?:\d+\s*)?"
        r"(?:person[- ]?|dev[- ]?|engineer[- ]?)?"
        r"(?:hour|day|week|month|quarter|sprint)s?\s+of\s+"
        r"(?:work|effort|engineering|dev\b|development)"
        r"|\bstory points?\b|\bt-?shirt siz\w+|\blevel of effort\b", re.I),
    "target date": re.compile(
        r"\b(?:target|due|delivery|completion|launch|go[- ]live|ship(?:ping)?)"
        r"\s*date\s*[:=]"
        r"|\bby (?:the )?end of (?:the )?(?:Q[1-4]\b|quarter|month|week|year"
        r"|20\d\d|Jan\w*|Feb\w*|Mar\w*|Apr\w*|May\b|Jun\w*|Jul\w*"
        r"|Aug\w*|Sep\w*|Oct\w*|Nov\w*|Dec\w*)"
        r"|\bby (?:EOW|EOD|EOM|EOQ|EOY)\b"
        r"|\b(?:ships|lands|launches|go(?:es)? live|is due|are due"
        r"|is targeted|is slated|is scheduled)\s+(?:in|for|by|on)\s+"
        r"(?:Q[1-4]\b|20\d\d\b|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct"
        r"|Nov|Dec)[a-z]*\b)", re.I),

    "defers its own point": re.compile(
        r"\b(?:that is|that's|this is) (?:a|another) separate (?:conversation"
        r"|discussion|question|matter|topic)"
        r"|\bbeyond the scope of th(?:is|e) (?:document|section|note|page)"
        r"|\b(?:more|details) on (?:that|this) (?:later|below|elsewhere)"
        r"|\ba (?:topic|subject) for another (?:time|day|document)", re.I),


    "process leak": _process_leak_rx(),

    "draft diff": re.compile(
        r"\b(?:since the (?:first|last|previous|earlier) (?:draft|pass|round|version)"
        r"|in (?:this|the last|the previous) (?:pass|round|revision)"
        r"|in (?:this|the) (?:updated|revised|new|latest) (?:version|draft|revision)"
        r"|(?:previously|earlier) (?:i|we|this) (?:said|wrote|reported|had)"
        r"|(?:has|have|had) been (?:dropped|added|removed|reworded) since"
        r"|(?:removed|dropped|added|cut|reworded|changed) (?:from|since|in) (?:the )?"
        r"(?:first|last|previous|earlier|this|updated) (?:draft|pass|version|revision|round)"
        r"|the (?:count|number|total) (?:had|has) (?:gone|come) (?:up|down)"
        r"[^.!?]{0,40}?\b(?:draft|pass|version|revision|round)\b"
        r"|(?:up|down) from the (?:first|earlier|previous))", re.I),

    "commit or checkout ref": re.compile(
        r"(?:\b(?:commit|sha|checkout|revision|at|built from|based on|sourced from"
        r"|as of)\s+`?(?=[0-9a-f]{7,40}\b)(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])"
        r"[0-9a-f]{7,40}\b`?"
        r"|\(`(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}`\)"
        r"|\bcheckout\s+(?:main|master|HEAD|[\w.-]+/[\w.-]+|v?\d[\w.-]*)\b"
        r"|\blocal (?:main|master|feature) checkout\b)", re.I),

    "asks reader to verify": re.compile(
        r"\b(?:that is unverified|this (?:is|remains) unverified|needs? (?:to be )?verif"
        r"|(?:^|(?<=[.!?]\s))(?:confirm|verify) "
        r"(?:this|the (?:claim|number|figure|statement|finding))\b"
        r"|(?:^|(?<=[.!?]\s))(?:confirm|verify)\b"
        r"(?![^.!?]*\b(?:before|after|during|then|first|once|until)\b)\s+\S"
        r"|worth (?:confirming|checking|verifying)"
        r"|someone should (?:check|confirm|verify)|to be confirmed|\(unconfirmed\))",
        re.I | re.M),

    "citation plumbing": re.compile(
        r"(?:\b[Ii]n [#@][\w-]+ on \d{1,2} [A-Z][a-z]+"
        r"|\b[Ii]n (?:the )?(?:thread|channel|meeting|call|review|standup) "
        r"(?:on|of) \d{1,2} [A-Z][a-z]+"
        r"|\b(?:[Pp]er|[Aa]ccording to) [A-Z][a-z]+(?:'s)? "
        r"(?:message|comment|note|post|reply) (?:in|on)\b"
        r"|\b[Aa]s [A-Z][a-z]+ (?:said|noted|wrote|put it) (?:in|on) "
        r"(?:[#@][\w-]+|\d{1,2} [A-Z][a-z]+))"),

    "unsourced citation": re.compile(
        r"\b(?:[A-Z][a-z]+ (?:et al\.?|and colleagues|and co[- ]?workers)"
        r"|according to (?:research|a study|the literature)"
        r"|studies (?:show|suggest|found)|research (?:shows|suggests|indicates)"
        r"|the [a-z]+ (?:benchmark|test[- ]suite|paper) (?:shows|reports|measured))"),

    "planning language": re.compile(
        r"(?:(?:^[ \t>]*(?:[-*+]|\d+[.)])?[ \t]*|(?<=[.;:]\s)|(?<=,\s))"
        r"we (?:should|will|shall|need to|ought to|must)\b"
        r"|\bi (?:think|believe|reckon|suspect)\b[^.!?]{0,24}?"
        r"\bwe (?:should|will|shall|need to|ought to|must)\b"
        r"|(?:^|(?<=[.!?]\s))in the future\b"
        r"|\b(?:will|shall|should|can|could|may|might|plan|intend|revisit|address"
        r"|handle|fix|add|support|move|migrate)\b[^.!?]{0,80}?\bin the future\b"
        r"|\bgoing forward|\bdown the line|\bat some point|\bfurther down the line"
        r"|\blater (?:we|this|it) (?:can|could|will|should)"
        r"|\beventually (?:we|this|it)|\bfor now,)", re.I | re.M),

    "changelog narration": re.compile(
        r"\b(?:used to be|formerly (?:called|named|known)|previously (?:called|named|was)"
        r"|(?:has|have) been (?:renamed|reverted|rolled back)"
        r"|(?:has|have) since been (?:renamed|moved|replaced|dropped|reverted|removed)"
        r"|(?:was|were) (?:renamed|reverted|rolled back|refactored) (?:to|from|in|out)"
        r"|(?:version|release|v)\s*\d+(?:\.\d+)*\s+"
        r"(?:added|removed|introduced|dropped|changed|renamed|replaced)"
        r"|no longer (?:called|named)|now (?:renamed|called|known as))", re.I),

    "unexplained reference": re.compile(
        r"\b(?:Decision|Item|Point|Finding|Comment|Thread|Overlaps?|Issue|Note)"
        r"\s+#?\d{1,5}\b(?!\s*[—:\-])(?!\s*\((?!see\b|cf\b|per\b|ref\b|above\b|below\b))"
        r"(?!\s+of\b)", re.I),

    "editor note": re.compile(
        r"\b(?:(?:is )?not document content|options not taken"
        r"|(?:note|reminder) (?:for|to) [A-Z][a-z]+"
        r"|(?:left|leave[sd]?|leaving) (?:this |that |it )?(?:for|to) you"
        r"|your call\b|before sending\b|draft skeleton|scaffold only"
        r"|(?:this|the last|the next) pass (?:deliberately |intentionally )?"
        r"(?:left|leaves|skipped|skips|covers)"
        r"|(?:is|are) session \d|in session \d"
        r"|(?:to be|must be|still to be|needs? to be) (?:hand[- ]written|written by hand)"
        r"|not generated yet|not yet generated"
        r"|the skeleton above)", re.I),


    "parked problem": re.compile(
        r"\b(?:(?:is|are) (?:a |an )?(?:real |genuine |slight |minor |major )?"
        r"(?:concern|problem|worry)s?\b"
        r"|(?:is|are) (?:concerning|problematic|sub-?optimal|not ideal"
        r"|less than ideal)"
        r"|(?:needs?|requires?|warrants?|deserves?) (?:further |more |some |urgent )?"
        r"(?:attention|thought|consideration|discussion|investigation|scrutiny)"
        r"|(?:should|must|needs? to) be (?:addressed|looked at|revisited|considered)"
        r"|raises? (?:questions|concerns|doubts)"
        r"|room for improvement|could be (?:better|improved)"
        r"|TBD\b|TODO\b"
        r"|[XN]%)"
        r"|\?\?\?|\([^)\n]{3,80}\?\)", re.I),

    "vague action": re.compile(
        r"\b(?:look(?:s|ed|ing)? into\b|take a (?:closer|deeper|second|proper) look"
        r"|keep an eye on|keep (?:a )?(?:close )?watch on"
        r"|(?:keep|continue) (?:to )?monitor(?:ing)?|monitor the situation"
        r"|(?:worth|needs?) revisiting|revisit (?:this|that|it|later)"
        r"|align on\b|sociali[sz]e (?:this|the|it)"
        r"|explore (?:the )?options|investigate further|further investigation"
        r"|think (?:about|through) (?:this|that|it|whether)"
        r"|give (?:some |more )?thought to|be mindful of|bear in mind"
        r"|pay (?:closer |more )?attention to)", re.I),


    "number without its noun": re.compile(
        r"\b\d{1,3}(?:[.,]\d+)?\s?%\s*(?:→|->|-->|to|na|do|and|,)\s*"
        r"\d{1,3}(?:[.,]\d+)?\s?%(?!\s*[\w(])", re.I),

    "identifier as subject": re.compile(
        r"(?:^|(?<=[.!?;:,)\"'”’]\s)|(?<=\bthat\s)|(?<=\bbut\s)"
        r"|(?<=\band\s)|(?<=\bor\s)|(?<=\bso\s)|(?<=\bbecause\s))\s*"
        r"\b[A-Z][A-Z0-9_]{3,}\b\s+(?:is|was|are|were|being|seems?|looks?|"
        r"remains?|stays?|becomes?)\b(?!\s+(?:a|an|the)\b)", re.M),

    "evaluative adjective": re.compile(
        r"(?:\b(?:loose|looser|loosest|unreliable|flak(?:e)?y|messy|brittle"
        r"|fragile|weak|poor|decent|good enough|useless"
        r"|nice|neat|elegant|ugly)\b"
        r"|(?<!\bto )(?<!\bnot )(?<!\bwill )(?<!\bmust )(?<!\bcan )(?<!\bmay )"
        r"(?<!\bshould )(?<!\bwould )(?<!\bcould )(?<!\bdoes )(?<!\bdo )"
        r"(?<!\bdid )(?<!\bhelp )(?<!\bhelps )"
        r"\bclean(?:er|est)?\b(?!\s+(?:up|out)\b))"
        r"(?!\s+(?:crypto|cryptography|cipher|hash|key|keys|password|passwords"
        r"|reference|references|typing|checkout|build|builds|tree|state"
        r"|install|room|shutdown|exit|slate|code|architecture|coding)\b)"),

    "inanimate perceiver": re.compile(
        r"\b(?:code|config(?:uration)?|rules?|patterns?|scripts?|tests?"
        r"|parsers?|systems?|tools?|quer(?:y|ies)|filters?|detectors?|checks?"
        r"|agents?|pipelines?)\s+(?:never saw|saw|sees|knows?|knew|thinks?"
        r"|thought|believes?|understands?|remembers?|forgets?|hopes?|cares?"
        r"|wants?)\b", re.I),

    "bare nominalisation": re.compile(
        r"\bthe (?:invocation|execution|utili[sz]ation|calling|creation"
        r"|deletion|modification|initiali[sz]ation|verification|validation"
        r"|generation|computation|transformation|configuration|installation"
        r"|migration|removal|addition|introduction|application) of\b", re.I),

    "idiom": re.compile(
        r"\b(?:on paper|under the hood|out of the box|in the wild"
        r"|at the end of the day|moving? the needle|low[- ]hanging fruit"
        r"|boil the ocean|circle back|touch base|move the goalposts"
        r"|baked?[- ]in(?:to)?|hand in hand|across the board"
        r"|the elephant in the room|a stone'?s throw|heavy lifting"
        r"|the lay of the land|par for the course)\b", re.I),

    "activity report": re.compile(
        r"\b(?:(?:has|have|had) been (?:looking|working|thinking) "
        r"(?:at|on|into|about|with)"
        r"|(?:is|are|was|were) (?:already|currently|still) "
        r"(?:looking|working|thinking) (?:at|on|into|about|with))", re.I),
}

QUOTE_RULES = ("editor note", "process leak", "changelog narration",
               "bare internal id", "draft diff", "commit or checkout ref")

PREPROCESS = {
    "unsourced citation": lambda s: re.sub(
        r"\[[^\]\n]*\]\(https?://[^)\n]*\)"
        r"|[A-Z][a-z]+ (?:et al\.?|and colleagues)\s*(?:\[\^[^\]\n]+\]|\[[^\]\n]+\])",
        " ", s),
}

SUBSTITUTION = {
    "nominalisation": re.compile(
        r"\b(?:make[sd]? a decision|provide[sd]? (?:a |an )?(?:explanation|description)"
        r"|perform[sd]? (?:a |an )?(?:analysis|review|validation)"
        r"|conduct(?:s|ed|ing)? (?:a |an )?(?:review|analysis|assessment)"
        r"|give[sn]? consideration to|take[ns]? into (?:account|consideration)"
        r"|is (?:a |an )?indication of|has the ability to)", re.I),
}

OCCURRENCE = {
    "X-not-Y": re.compile(
        r"\b(?:it'?s not (?:just |merely |only )?[a-z]{3,15},? (?:it'?s|but)"
        r"|not (?:a|an|the) [a-z]{3,20},? but (?:a|an|the))", re.I),
}

DEFAULT_LANGS = {
    "en": {
        "message scaffold": [
            r"to paste", r"paste this", r"here'?s the draft",
            r"draft(?: reply| message)?", r"proposed reply", r"suggested reply",
            r"key distinction", r"context for you",
        ],
        "omission note": [
            r"omitted", r"left out", r"not included here", r"skipped here",
            r"if (?:he|she|they|you) ask(?:s)?",
            r"happy to (?:add|share|send) more", r"more on request",
        ],
        "sign-off": [
            r"let me know", r"shout if", r"hope (?:that|this) helps",
            r"happy to (?:take|have|do|jump|dig|chat|discuss|walk|help)",
            r"feel free to (?:ask|ping|reach out)", r"any other questions",
        ],
        "corrects the reader": [
            r"no,", r"not quite", r"wrong,", r"actually,",
            r"that'?s not (?:it|right|quite|true)",
            r"you'?re (?:conflating|mixing|confusing|wrong|misreading)",
        ],
        "buried lead": [
            r"most important(?:ly)?", r"the (?:key|main|real) point",
            r"the real (?:issue|problem)", r"what matters most",
            r"the headline", r"bottom line up front",
        ],
        "summary heading": [
            r"summary", r"abstract", r"at a glance", r"overview",
            r"the short version", r"brief", r"one[ -]page(?: summary)?",
            r"in one page", r"what this says", r"read this first", r"tl;?dr",
            r"highlights", r"takeaways", r"key (?:points|facts|takeaways)",
            r"decisions?", r"the decisions?", r"recommendations?",
            r"results?", r"conclusions?", r"verdicts?", r"findings?",
            r"the answer", r"what to do",
        ],
        "rule word": [
            r"must not", r"must", r"never", r"always", r"do not", r"don'?t",
            r"shall", r"may not", r"required to", r"is forbidden",
            r"is prohibited",
            r"refuses?", r"cannot",
        ],
        "recommendation verb": [
            r"re-?check", r"check", r"confirm", r"verify", r"replace",
            r"remove", r"delete", r"drop", r"avoid", r"ensure",
            r"say",
        ],
        "advice word": [
            r"should", r"ought to", r"recommend\w*", r"is advised",
            r"we advise", r"is expected to", r"are expected to",
        ],
        "claim word": [
            r"cannot", r"require[sd]?", r"mandatory", r"forbidden",
            r"prohibited", r"does not", r"doesn'?t", r"no one", r"nobody",
            r"risks?", r"unsafe", r"dangerous", r"corrupt\w*", r"breaks",
            r"irreversible", r"open question", r"undecided", r"unclear",
            r"unknown", r"disagree\w*", r"objection",
        ],
        "abbreviation": [r"e\.g", r"i\.e", r"etc", r"vs", r"cf", r"Dr", r"Mr",
                         r"Ms", r"approx", r"Fig", r"No", r"al"],
    },
    "pl": {
        "message scaffold": [r"do wklejenia", r"kluczowe rozróżnienie"],
        "omission note": [r"pominięte", r"jak dopyta", r"dorzuć"],
        "sign-off": [r"daj znać", r"w razie czego"],
        "corrects the reader": [r"nie,", r"nieprawda,"],
        "buried lead": [r"najważniejsze"],
        "summary heading": [r"podsumowanie", r"streszczenie", r"wnioski"],
        "rule word": [r"nie wolno", r"nie należy", r"musi", r"muszą",
                      r"nigdy", r"zawsze", r"wymagane", r"zabronione"],
        "advice word": [r"powin\w+", r"zaleca się", r"zalecane",
                        r"rekomend\w*", r"warto"],
        "claim word": [r"ryzyko", r"niebezpieczn\w*", r"nieodwracaln\w*",
                       r"otwarte pytanie", r"niejasne", r"nie zgadzam się",
                       r"sprzeciw"],
        "abbreviation": [r"np", r"itp", r"itd", r"tzn", r"tj", r"m\.in",
                         r"dr", r"prof"],
    },
}

DEFAULT_ACTIVE_LANGS = ["en", "pl"]

LANGS = {k: {s: list(w) for s, w in v.items()}
         for k, v in DEFAULT_LANGS.items()}
ACTIVE_LANGS = list(DEFAULT_ACTIVE_LANGS)

CHAT_TEMPLATES = {
    "colon label": r"^\s*(?:[-*+]\s*)?(?:\*\*)?[^\s:][^\n:]{0,34}:(?:\*\*)?\s+\S",
    "message scaffold": r"^\s*(?:\*\*)?(?:{words})\b",
    "omission note": r"\b(?:{words})\b",
    "sign-off": r"\b(?:{words})\b",
    "corrects the reader": r"^\s*(?:\*\*)?(?:{words})",
    "buried lead": r"\b(?:{words})\b",
}


def words_for(shape):
    """Every alternative for one shape, across the live languages."""
    out = []
    for code in ACTIVE_LANGS:
        out += LANGS.get(code, {}).get(shape, [])
    return out


RULE_GATE_SHAPES = ("rule word", "claim word")

DELETION_ORDERED = frozenset({
    "commit or checkout ref", "changelog narration", "citation plumbing",
    "unsourced citation", "bare internal id", "unexplained reference",
    "process leak", "editor note", "asks reader to verify", "worklog",
    "draft diff", "echo", "sign-off", "defers its own point",
    "phase plan", "task list", "estimate", "target date",
})

NEVER_A_RULE = DELETION_ORDERED | {
    "planning language", "vague action", "sign-off", "echo", "purpose hedge",
    "empty framing",
}


def blind_shapes():
    """Live languages that bring no words for the rule check."""
    return {code: miss for code in ACTIVE_LANGS
            if (miss := sorted(s for s in RULE_GATE_SHAPES
                               if not LANGS.get(code, {}).get(s)))}


def _chat_shapes():
    built = {}
    for name, tmpl in CHAT_TEMPLATES.items():
        if "{words}" not in tmpl:
            built[name] = re.compile(tmpl)
            continue
        words = words_for(name)
        if not words:
            continue
        built[name] = re.compile(tmpl.format(words=alt(words)), re.I)
    return built


CHAT = _chat_shapes()
ABBR = _abbr_rx()

SAFE = set(VOCAB["safe_metaphors"])

CRITICAL_MARK = re.compile(r"^\s*CRITICAL INFO FOR AGENTS\b")
KEEP_MARK = re.compile(r"<!--\s*kv:keep\s*-->|" + CRITICAL_MARK.pattern)
FREEZE_START = re.compile(r"<!--\s*kv:freeze\s*-->")
FREEZE_END = re.compile(r"<!--\s*kv:end\s*-->")
ALLOW_MARK = re.compile(r"<!--\s*kv:allow\s+([^>]*?)\s*-->")
ALLOW_SHAPE_MARK = re.compile(r"<!--\s*kv:allow-shape\s+([^>]*?)\s*-->")
SUMMARY_MARK = re.compile(r"<!--\s*kv:summary\s*-->")


def unflaggable(prose, headings):
    """1-based lines no shape or candidate may be reported on."""
    return protected.lines(headings, len(prose)) | keep_lines(prose)


def without_lines(dups, held):
    """Repeated-text clusters with the `held` lines taken out, empty ones dropped."""
    out = []
    for d in dups:
        left = [l for l in d["lines"] if l not in held]
        if left:
            out.append({**d, "lines": left})
    return out


def keep_lines(prose):
    """1-based lines a marker protects, continuations included."""
    out, running, frozen = set(), False, False
    for i, ln in enumerate(prose, 1):
        if frozen:
            out.add(i)
            if FREEZE_END.search(ln):
                frozen = False
            continue
        if FREEZE_START.search(ln):
            out.add(i)
            frozen = True
            continue
        if not ln.strip():
            running = False
        elif KEEP_MARK.search(ln):
            out.add(i)
            running = CRITICAL_MARK.search(ln) is not None
        elif running:
            out.add(i)
    return out | attribution.lines(prose) | superseded_lines(prose)


def allowed_words(lines):
    """Words this document has declared are the right words."""
    out = set()
    for ln in lines:
        for m in ALLOW_MARK.finditer(ln):
            out |= {w.strip().lower() for w in m.group(1).split(",") if w.strip()}
    return out


def allowed_shapes(lines):
    """Shapes this document has declared are its subject, not its faults."""
    out, known = set(), all_shape_names()
    for ln in lines:
        for m in ALLOW_SHAPE_MARK.finditer(ln):
            for raw in m.group(1).split(","):
                name = raw.strip().lower()
                if not name:
                    continue
                if name not in known:
                    near = difflib.get_close_matches(name, sorted(known), 1)
                    raise UsageError(
                        f"kv:allow-shape names {name!r}, which is not a shape."
                        + (f" Closest is {near[0]!r}." if near else "")
                        + f" There are {len(known)} shapes; `plan` prints the "
                        f"name of every one it finds.")
                out.add(name)
    return out


CELL_BLIND = {"number without its noun", "worklog"}


_LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)]|[a-zA-Z][.)])\s+(.*)$")
_LIST_COMMAND = re.compile(
    r"^(?:add|run|set|use|create|make|check|write|see|get|call|keep|avoid|"
    r"do|don'?t|install|configure|update|remove|enable|disable|ensure|start|"
    r"stop|read|open|close|pick|choose|copy|move|delete|build|test)\b", re.I)


def _list_key(s):
    """An item's text with formatting and case removed, for matching."""
    return " ".join(re.findall(r"[a-z0-9]+", re.sub(r"[`*_\[\]()]", "", s.lower())))


def list_groups(prose):
    """Runs of three or more consecutive list items, as (first_line, items)."""
    out, cur, start = [], [], 0
    for i, ln in enumerate(prose, 1):
        m = _LIST_ITEM.match(ln or "")
        if m:
            if not cur:
                start = i
            cur.append((i, m.group(2).strip()))
        else:
            if len(cur) >= 3:
                out.append((start, cur))
            cur = []
    if len(cur) >= 3:
        out.append((start, cur))
    return out


def list_faults(prose, raw=None):
    """Faults that belong to a list rather than to any one line."""
    hits = []
    for _start, items in list_groups(prose):
        seen = {}
        for ln, txt in items:
            if raw and 0 < ln <= len(raw):
                m = _LIST_ITEM.match(raw[ln - 1])
                txt = m.group(2).strip() if m else txt
            k = _list_key(txt)
            if len(k.split()) < 3:
                continue
            if re.match(r"^\s*(?:#|//|/\*|--)\s", txt):
                continue
            if k in seen:
                hits.append((ln, "repeated list item",
                             f"same as line {seen[k]}: {txt[:56]}"))
            else:
                seen[k] = ln
        real = [(ln, s) for ln, s in items if len(s.split()) >= 3]
        if len(real) < 3:
            continue
        cmds = sum(1 for _l, s in real if _LIST_COMMAND.match(s))
        stops = sum(1 for _l, s in real if s.rstrip().endswith("."))

        def _split(n):
            """A real split, not one odd item out."""
            small = min(n, len(real) - n)
            return small >= 2 and small / len(real) >= 0.25

        why = []
        if _split(cmds):
            why.append(f"{cmds} of {len(real)} start with a command")
        if _split(stops):
            why.append(f"{stops} of {len(real)} end with a full stop")
        if why:
            hits.append((real[0][0], "mixed list styles", "; ".join(why)))
    return hits


def _is_tag_list(cell):
    """A table cell that is a list of keywords rather than a sentence."""
    s = re.sub(r"[`*_]", "", str(cell)).strip()
    if "," not in s or "." in s or ";" in s or ":" in s:
        return False
    parts = [x.strip() for x in s.split(",") if x.strip()]
    return len(parts) >= 3 and all(len(x.split()) <= 3 for x in parts)


_SHAPES_SEEN = None


def find_shapes(prose, tables=(), headings=(), quotes=(), chat=False,
                extra_allowed=()):
    """Return hits as (line_no, category, matched_text)."""
    numbered = [(i + 1, ln) for i, ln in enumerate(prose) if ln.strip()]
    heads = [(h[0] + 1, mask_code_spans(h[2])[0]) for h in headings]
    cells = [(ln, mask_code_spans(txt)[0]) for ln, txt in tables
             if not _is_tag_list(txt)]
    hits = []
    groups = (EXISTENCE, SUBSTITUTION, OCCURRENCE) + ((CHAT,) if chat else ())
    cell_rules = {n for g in groups for n in g} - CELL_BLIND
    ok_words = SAFE | allowed_words(prose)
    _ANCHOR = re.compile(
        r"^\s*(?:[-*+]\s+|\#{1,6}\s+)?(?:\*\*)?(?:[A-Za-z][\w-]*\s+)?"
        r"[A-Za-z]{0,2}(\d{1,5})(?:\*\*)?\s*[.):\u2014-]")
    resolves = {m.group(1) for _, t in heads
                for m in [re.match(r"^[A-Za-z]{0,2}(\d{1,5})\s*[.):]?\s", t)] if m}
    resolves |= {m.group(1)
                 for _, t in (heads + numbered)
                 for m in [_ANCHOR.match(t)] if m}
    kept = keep_lines(prose)
    off = allowed_shapes(prose) | set(extra_allowed)
    for line, ln, allowed in ([(a, b, None) for a, b in numbered + heads] +
                              [(a, b, cell_rules) for a, b in cells] +
                              [(a, b, QUOTE_RULES) for a, b in quotes]):
        if line in kept or KEEP_MARK.search(ln):
            continue
        for group in groups:
            for name, rx in group.items():
                if allowed is not None and name not in allowed:
                    continue
                if name in off:
                    continue
                target = PREPROCESS[name](ln) if name in PREPROCESS else ln
                for m in rx.finditer(target):
                    txt = m.group(0).strip()
                    if txt.lower() in ok_words:
                        continue
                    if name == "bare internal id" and _classifying(target, m):
                        continue
                    if name == "commit or checkout ref" and SHA_REF.search(txt):
                        if _cited_as_evidence(target, m.start(), m.end()):
                            continue
                    if name == "worklog" and _cites_a_ref(target):
                        continue
                    if (name == "worklog"
                            and m.groupdict().get("dated_actor")
                            and DEADLINE_WORD.search(target)):
                        continue
                    if name == "unexplained reference":
                        num = re.search(r"(\d+)\s*$", txt)
                        if num and num.group(1) in resolves:
                            continue
                    hits.append((line, name, txt[:70]))
    frozen = unflaggable(prose, headings)
    out = sorted(h for h in hits if h[0] not in frozen)
    if _SHAPES_SEEN is not None:
        _SHAPES_SEEN.update(h[1] for h in out)
    return out


LIST_ITEM = re.compile(r"\s*(?:[-*+]|\d+[.)]|[a-zA-Z][.)])\s")

NUMBERED_ITEM = re.compile(r"\s*\d+[.)]\s")
NUMBERED_MARKER = re.compile(r"\s*(\d+)[.)]\s")


def ordered_runs(prose):
    """Runs of 3+ numbered-list markers whose VALUES are exactly consecutive
    (N, N+1, N+2, ...), in document order.
    """
    seq = [int(m.group(1)) for ln in prose
           for m in [NUMBERED_MARKER.match(ln or "")] if m]
    runs, cur = [], []
    for v in seq:
        if cur and v == cur[-1] + 1:
            cur.append(v)
        else:
            if len(cur) >= 3:
                runs.append(tuple(cur))
            cur = [v]
    if len(cur) >= 3:
        runs.append(tuple(cur))
    return runs


def paragraphs(prose):
    """Yields (first_line, [lines]) per paragraph, 1-based."""
    para, start = [], None
    for i, ln in enumerate(prose):
        blank = not ln.strip()
        if blank or LIST_ITEM.match(ln):
            if para:
                yield start + 1, para
            para, start = [], None
            if blank:
                continue
        start = i if start is None else start
        para.append(ln)
    if para:
        yield start + 1, para


def em_dash_pressure(prose):
    """Paragraphs holding more than one em-dash. Section 8 allows one."""
    return [(start, " ".join(p).count("—")) for start, p in paragraphs(prose)
            if " ".join(p).count("—") > 1]


def wall_paragraphs(prose, floor=None):
    """Paragraphs of `floor` or more sentences, with their word count."""
    floor = THRESHOLDS["paragraph_wall"] if floor is None else floor
    out = []
    for start, para in paragraphs(prose):
        n = sum(1 for _ in sentences(list(enumerate(para))))
        if n >= floor:
            out.append((start, n, sum(len(l.split()) for l in para)))
    return out



WORD = re.compile(r"[a-z0-9']+")


def _repeat_said(run, src, prose):
    """The author's text from the first word of `run` to its last."""
    (l0, _, a, _), (l1, _, _, b) = run[0], run[-1]
    rows = [r for r in range(l0, l1 + 1) if 0 < r <= min(len(src), len(prose))]
    if a is None or b is None or len(rows) != l1 - l0 + 1 or any(
            len(src[r - 1]) != len(prose[r - 1]) for r in rows):
        return " ".join(src[r - 1].strip() for r in rows if src[r - 1].strip())
    if l0 == l1:
        return src[l0 - 1][a:b]
    parts = ([src[l0 - 1][a:].strip()]
             + [src[r - 1].strip() for r in range(l0 + 1, l1)]
             + [src[l1 - 1][:b].strip()])
    return " ".join(p for p in parts if p)


def duplicates(prose, window=8, src=None):
    """Repeated 8-word windows, grown to their full length."""
    toks = []
    for i, ln in enumerate(prose):
        raw = SEGMENTED.sub(lambda m: " " * len(m.group()) or " ", ln)
        low = raw.lower()
        cols = len(raw) == len(ln) and len(low) == len(raw)
        for m in WORD.finditer(low):
            toks.append((i + 1, m.group(),
                         m.start() if cols else None,
                         m.end() if cols else None))
    if len(toks) < window:
        return []

    seen = defaultdict(list)
    for i in range(len(toks) - window + 1):
        key = " ".join(t[1] for t in toks[i:i + window])
        seen[key].append(i)

    claimed, out = set(), []
    for key, spots in seen.items():
        if len(spots) < 2:
            continue
        spots = [s for s in spots
                 if not any(i in claimed for i in range(s, s + window))]
        if len(spots) < 2:
            continue
        length = window
        while True:
            nxt = {tuple(t[1] for t in toks[s:s + length + 1]) for s in spots}
            if len(nxt) != 1 or spots[-1] + length + 1 > len(toks):
                break
            length += 1
        lines = sorted({toks[s][0] for s in spots})
        if len(lines) < 2:
            continue
        for s in spots:
            claimed.update(range(s, s + length))
        first = toks[spots[0]:spots[0] + length]
        entry = {
            "words": length,
            "lines": lines,
            "text": " ".join(t[1] for t in first)[:120],
        }
        if src is not None:
            entry["said"] = _repeat_said(first, src, prose)
        out.append(entry)
    return sorted(out, key=lambda d: -d["words"])


def parallel_list(d, prose) -> bool:
    """True when every copy in a cluster is a bullet in one unbroken list."""
    ln = sorted(d["lines"])
    if len(ln) < 2:
        return False
    for i in range(ln[0], ln[-1] + 1):
        line = prose[i - 1] if 0 < i <= len(prose) else ""
        if line.strip() and not LIST_ITEM.match(line):
            return False
    return True


RESTATING_HEADING = re.compile(
    r"^(?:\d+[.)]\s*)?(?:cross[- ]?check|cross[- ]?reference|"
    r"sanity[- ]check|traceability|review of|audit)\b", re.I)


def restating_section(headings, line) -> bool:
    """True when `line` sits under a heading that restates by design."""
    lvl = 99
    for ln0, level, txt in reversed([h for h in headings if h[0] + 1 <= line]):
        if level >= lvl:
            continue
        lvl = level
        txt = txt.strip()
        if SUMMARY_HEADING.match(txt) or RESTATING_HEADING.match(txt):
            return True
    return False


def restates_a_summary(d, headings) -> bool:
    """True unless every copy in the cluster sits in ordinary body prose."""
    return any(restating_section(headings, ln) for ln in d["lines"])


def cluster_lines(dups, limit=5):
    """Line numbers for repeated-text clusters, one row per distinct line set."""
    rows = defaultdict(int)
    for d in dups:
        rows[tuple(d["lines"])] += 1
    limit = top(limit)
    shown = list(rows.items())[:limit]
    out = "; ".join(", ".join(str(n) for n in ln) + (f" ({c} texts)" if c > 1 else "")
                    for ln, c in shown)
    if len(rows) > limit:
        out += f"; … {len(rows) - limit} more"
    return out


def snip(s, n=55):
    """`s` cut to n characters at a word boundary, plus the mark."""
    if len(s) <= n:
        return s
    head = s[:n].rsplit(" ", 1)[0].rstrip()
    return (head or s[:n].rstrip()) + "…"


def number_spans(ns):
    """`[2, 3, 4, 7]` as `2-4, 7`."""
    out, run = [], []
    for n in sorted(ns):
        if run and n == run[-1] + 1:
            run.append(n)
            continue
        if run:
            out.append(run)
        run = [n]
    if run:
        out.append(run)
    return ", ".join(str(r[0]) if len(r) == 1 else f"{r[0]}-{r[-1]}"
                     for r in out)



SENTENCE_OPENERS = {
    "a", "an", "the", "this", "that", "these", "those", "it", "its", "we",
    "you", "they", "he", "she", "i", "and", "but", "or", "if", "when",
    "where", "while", "so", "then", "each", "every", "all", "any", "no",
    "not", "never", "always", "do", "does", "did", "use", "using", "see",
    "note", "also", "for", "to", "in", "on", "at", "by", "as", "of", "with",
    "there", "here", "both", "either", "neither", "one", "two", "three",
}


def inconsistencies(text):
    """Term spelling variants and numbers carrying two different units."""
    out = []

    def _line_of(pos):
        return text.count("\n", 0, pos) + 1

    def _opens_sentence(pos):
        before = text[max(0, pos - 24):pos].rstrip(" \t*_`>#-+")
        return not before or before[-1] in ".!?:\n"

    variants = defaultdict(dict)
    for m in re.finditer(r"\b[A-Z][A-Za-z0-9]*(?:[ -][A-Z][A-Za-z0-9]*)+", text):
        term = m.group(0)
        forms = [(term, m.start())]
        head = re.split(r"[ -]", term)
        if (len(head) > 2 and head[0].lower() in SENTENCE_OPENERS
                and _opens_sentence(m.start())):
            forms.append((term[len(head[0]) + 1:], m.start() + len(head[0]) + 1))
        for txt, pos in forms:
            variants[re.sub(r"[ -]", "", txt).lower()].setdefault(
                txt, _line_of(pos))
    for spellings in variants.values():
        if len(spellings) > 1:
            out.append({"kind": "term", "forms": sorted(spellings),
                        "lines": {k: spellings[k] for k in sorted(spellings)}})

    unit_at = {}
    units = defaultdict(lambda: defaultdict(set))
    for m in UNIT_RX.finditer(text):
        u = canon_unit(m.group(2))
        if u:
            unit_at.setdefault((m.group(1).replace(",", ""), u),
                               _line_of(m.start()))
        fam = UNIT_FAMILY.get(u) if u else None
        if fam:
            units[m.group(1).replace(",", "")][fam].add(u)
    for num, fams in units.items():
        for us in fams.values():
            if len(us) > 1:
                out.append({"kind": "number", "value": num,
                            "units": sorted(us),
                            "lines": {u: unit_at[(num, u)]
                                      for u in sorted(us) if (num, u) in unit_at}})

    return out[:40]





def _path_fact_rx():
    return re.compile(
        rf"(?<![\w/])\.{{1,2}}/(?:[\w.-]{{1,64}}/)*[\w.-]{{0,64}}[\w-]"
        rf"|(?<![\w/])/(?:[\w.-]{{1,64}}/)+[\w.-]{{0,64}}[\w-]"
        rf"|(?:[\w.-]{{1,64}}/){{2,}}(?!etc\b)[\w.-]{{0,64}}[\w-]"
        rf"|(?:[\w.-]{{1,64}}/)+[\w-]{{1,64}}\.(?:{CODE_EXT})\b"
        rf"|\b[\w-]{{1,64}}\.(?:{CODE_EXT})\b")


def _version_fact_rx():
    return re.compile(rf"\bv?\d+\.\d+(?:\.\d+)*(?:-[\w.]+)?\b"
                      rf"(?!\s*(?:{UNITS})(?!\w))")


def _number_fact_rx():
    has_comma = any(lang in {"es", "pl"} for lang in ACTIVE_LANGS)
    comma_part = rf"(?<!\d,)\d+,\d+(?!,\d)|" if has_comma else ""
    return re.compile(
        rf"(?<![\w.])(?:{comma_part}\d+(?:,\d{{3}})*(?:\.\d+)?)"
        rf"(?:[\s-]*(?:{UNITS}))?(?!\w)(?!\.\d)")


FACT_BUILDERS = {"path": _path_fact_rx, "version": _version_fact_rx,
                 "number": _number_fact_rx}

FACT_RX = {
    "placeholder": re.compile(r"\{\{[ \t]*[A-Za-z_][\w.-]*[ \t]*\}\}"),
    "url": re.compile(r"https?://[^\s)>\]\"']*[^\s)>\]\"'.,;:!?]"),
    "ticket": re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b"),
    "path": _path_fact_rx(),
    "code": re.compile(r"(?P<tick>`+)(?P<val>(?:(?!(?P=tick))[^\n])+"
                       r"(?:\n(?:(?!(?P=tick))[^\n])+)?)(?P=tick)"),
    "date": re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    "version": _version_fact_rx(),
    "ratio": re.compile(r"(?<!-)\b\d+\s*/\s*\d+\b(?!-)"
                        r"|(?<!-)\b\d+(?:\s+of\s+|-in-|\s+in\s+)\d+\b(?!-)"),
    "number": _number_fact_rx(),
}

ROW_INDEX = re.compile(
    r"^[ \t]*\d{1,2}[.)](?=\s)|(?<=\|)[ \t]*\d{1,2}[ \t]*(?=\|)"
    r"|(?<=\s)\d{1,2}\)(?=\s)", re.M)

BARE_WORD = re.compile(r"^[a-z]{2,15}$")

ID_SHAPE = re.compile(r"[A-Z][A-Z0-9]{0,9}-?\d+")
BARE_ID = re.compile(r"\b[A-Z]{1,3}\d{2,6}\b")
_COUNT_NOUN = re.compile(r"\s+(?!(?:of|on|in|at|to|for|and|or|the|an?|is|was"
                         r"|are|were|by|per|from|with)\b)[a-z][a-z-]+")


def never_pardon(kind, value, orig):
    """True for a lost token no deletion excuses: a url, an id or a count."""
    if kind in ("url", "ticket", "ratio") or ID_SHAPE.fullmatch(value):
        return True
    if kind != "number" or not re.fullmatch(r"\d[\d,]*", value):
        return False
    said = re.escape(value)
    if value in SMALL_NUMBERS:
        said = rf"(?:{said}|(?i:{SMALL_NUMBERS[value]}))"
    for m in re.finditer(rf"(?<![\w.,]){said}(?![\w.,%])", orig):
        before = orig[:m.start()].rsplit("\n", 1)[-1].split()[-1:]
        if before and before[0][:1].isupper() and before[0].isalpha():
            continue
        if _COUNT_NOUN.match(orig, m.end()):
            return True
    return False

SMALL_NUMBERS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    "10": "ten", "11": "eleven", "12": "twelve",
}

SPELLED_OUT = {
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
    "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15",
    "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19",
    "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
    "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
}
SPELLED = re.compile(rf"\b({'|'.join(SPELLED_OUT)})\b", re.I)

COUNT_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy",
              "eighty", "ninety")
COUNT_UNITS = ("one", "two", "three", "four", "five", "six", "seven", "eight",
               "nine")
COMPOUND_COUNT = re.compile(
    rf"\b({'|'.join(COUNT_TENS)})-({'|'.join(COUNT_UNITS)})\b", re.I)


def _compound(m):
    return str(int(SPELLED_OUT[m.group(1).lower()])
               + COUNT_UNITS.index(m.group(2).lower()) + 1)

RATIO_FILLER = re.compile(
    r"\s+of\s+(?:its|his|her|their|our|your|these|those|the|all|only|about|"
    r"roughly|around|some)\s+(?=\d)", re.I)

NAME_NOT = {"Here", "There", "That", "This", "What", "Who", "It", "He", "She",
            "Let", "One", "Everyone", "Someone", "Anyone", "Nobody",
            "The", "They", "Their", "Its", "You", "Your", "We", "Our",
            "Both", "Each", "Every", "Either", "Neither", "Nothing", "None",
            "All", "Any", "Some", "Most", "Many", "Few", "Several",
            "Also", "Then", "Already", "Only", "Still", "Now", "Never",
            "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen"}
CREDITED_POSSESSIVE = re.compile(r"\b([A-Z][a-z]{2,15})'s\b")
CREDITED_SUBJECT = re.compile(
    r"\b([A-Z][a-z]{2,15})\s+(?:asked|says?|said|flagged|noted|proposed"
    r"|suggested|raised|reported|recommended|argued|objected|requested"
    r"|pointed\s+out|called\s+for|wants?|wanted)\b")


def credited_names(text):
    """Every person the text puts in the position of a source."""
    seen = set()
    for m in CREDITED_POSSESSIVE.finditer(text):
        seen.add(m.group(1))
        yield m
    for m in CREDITED_SUBJECT.finditer(text):
        who = m.group(1)
        if who in seen:
            yield m
        elif not re.search(r"\b%s\b" % re.escape(who.lower()), text):
            yield m


CREDITED = CREDITED_POSSESSIVE

_SOURCE_VERB = (r"paid\s+for|funded|sponsored|commissioned|flagged|proposed"
                r"|requested|recommended")
CREDITED_SOURCE = re.compile(
    rf"\b(?:the|an?|our|their|its|his|her)\s+([a-z][a-z-]{{2,20}})\s+"
    rf"({_SOURCE_VERB})\b"
    rf"|\b({_SOURCE_VERB}|reported|raised|written)\s+by\s+(?:the\s+|an?\s+)?"
    rf"([a-z][a-z-]{{2,20}})\b"
    r"|\b[Aa]ccording\s+to\s+(?:the\s+|an?\s+)?([a-z][a-z-]{2,20})\b")


def credit_key(m):
    """`sponsor (paid for)`: the source and how it is credited."""
    g = m.groups()
    who, how = ((g[0], g[1]) if g[0] else (g[3], g[2]) if g[3]
                else (g[4], "according to"))
    return f"{who} ({' '.join(how.lower().split())})"

SHOW_ALL = False


def top(n):
    return 10 ** 9 if SHOW_ALL else n

def _segmented_rx():
    return re.compile(FACT_RX["url"].pattern + "|" + FACT_RX["path"].pattern)


SEGMENTED = _segmented_rx()


def n_words(s):
    """Words a reader parses. A code span, a link or a path counts as one."""
    return len(SEGMENTED.sub("_", _MD_LINK.sub(r"\1", CODE_SPAN.sub("_", s)))
               .split())


def facts(text, counted=False):
    """Protected tokens: the mechanically recognisable part of Preserve."""
    out = defaultdict(Counter)
    text = HTML_COMMENT.sub(" ", text)
    seen, kept, fence, lang = defaultdict(int), [], None, None
    for ln in text.split("\n"):
        tok, bare = fence_delim(ln)
        if tok and fence is None:
            fence = tok
            lang = ln.strip().lstrip("`~").strip() or "plain"
        elif tok and fence_closes(tok, fence) and bare:
            seen[lang] += 1
            out["fence_lang"][f"{lang} #{seen[lang]}"] += 1
            fence = None
        elif fence is None:
            kept.append(ln)
        else:
            for m in FACT_RX["placeholder"].finditer(ln):
                out["placeholder"]["{{" + m.group(0).strip("{} \t\n")
                                  + "}}"] += 1
    stripped = "\n".join(kept)
    named = ("url", "placeholder", "date", "version", "ticket", "path",
             "ratio")
    for kind in ("code",) + named + ("number",):
        rx = FACT_RX[kind]
        if kind == "ratio":
            stripped = COMPOUND_COUNT.sub(_compound, stripped)
            stripped = SPELLED.sub(lambda m: SPELLED_OUT[m.group(1).lower()],
                                   stripped)
            stripped = RATIO_FILLER.sub(" of ", stripped)
        if kind == "number":
            stripped = ROW_INDEX.sub(" ", stripped)
        for m in rx.finditer(stripped):
            val = (m.group("val") if "val" in rx.groupindex
                   else m.group(1) if rx.groups else m.group(0)).strip()
            val = re.sub(r"\s+", " ", val)
            if kind == "number":
                val = number_token(val)
            if not val:
                continue
            real = kind
            if kind == "code":
                real = next((k for k in named + ("number",)
                             if FACT_RX[k].fullmatch(val)), "code")
            if real == "placeholder":
                val = "{{" + val.strip("{} \t\n") + "}}"
            out[real][val] += 1
        stripped = rx.sub(" ", stripped)
    if counted:
        return out
    return defaultdict(set, {k: set(v) for k, v in out.items()})



def _summary_heading_rx():
    """The headings that mean "this section is the summary"."""
    return re.compile(
        r"^(?:\d+[.)]\s*)?(?:executive|management|technical|project)?\s*"
        rf"(?:{alt(words_for('summary heading'))})\b", re.I)


SUMMARY_HEADING = _summary_heading_rx()

THRESHOLD_CONSTS = {
    "LONG_SENTENCE": "long_sentence",
    "SUMMARY_MAX_WORDS": "summary_max_words",
    "SUMMARY_MIN_WORDS": "summary_min_words",
    "SUMMARY_NEEDED_FROM": "summary_needed_from",
    "CHAT_MAX_WORDS": "chat_max_words",
    "DUPLICATE_FROM_WORDS": "duplicate_from_words",
    "MAX_SPAN": "max_span",
    "CLAIM_KEPT": "claim_kept",
    "LENGTH_TARGET": "length_target",
}
LONG_SENTENCE = THRESHOLDS["long_sentence"]
SUMMARY_MAX_WORDS = THRESHOLDS["summary_max_words"]
SUMMARY_MIN_WORDS = THRESHOLDS["summary_min_words"]
SUMMARY_NEEDED_FROM = THRESHOLDS["summary_needed_from"]
CHAT_MAX_WORDS = THRESHOLDS["chat_max_words"]
DUPLICATE_FROM_WORDS = THRESHOLDS["duplicate_from_words"]
LENGTH_TARGET = THRESHOLDS["length_target"]
OVER_TARGET_BAND = 1.5
SPLICE_WINDOW = 4
CROSSCHECK_TIMEOUT = 900
from killverbosity import attribution
from killverbosity import blame
from killverbosity import budget
from killverbosity import inflect
from killverbosity import layout
from killverbosity import mdblocks
from killverbosity import moves
from killverbosity import pointers
from killverbosity import protected
from killverbosity import reply
from killverbosity import rerun
from killverbosity import gates as gatelib
from killverbosity import rescue
from killverbosity import spawn
from killverbosity import unmask

JOB_TIMEOUT = 240
RUN_BUDGET = 3600
JOBS = 4


CLAUDE_READONLY = ["--restricted", "--tools=Read,Grep,Glob"]
CLAUDE_NO_TOOLS = ["--restricted", "--tools="]


def claude_flag_missing(err: str) -> bool:
    """Whether the local `claude` refused one of the flags above."""
    low = err.lower()
    return ("restricted" in low or "--tools" in low) and (
        "unknown option" in low or "unrecognized" in low
        or "unknown argument" in low)


_POINTING = frozenset("""
    above below listed shown described covered section sections
    see later earlier following preceding next previous
""".split())


def _paraphrased_pointers(text, heading_texts):
    """Brackets in `text` that name a section by a paraphrase of its heading."""
    def words(s):
        return {w for w in re.findall(r"[a-z]{3,}", s.lower())
                if w not in _HEADING_GRAMMAR}

    live = {heading_name(h).casefold() for h in heading_texts if h.strip()}
    heads = [words(h) for h in heading_texts if h.strip()]
    out = set()
    for p in re.findall(r"\(([^()\n]{3,60})\)", text):
        p = heading_name(p)
        if p.casefold() in live:
            continue
        named = words(p) - _POINTING
        if len(named) >= 2 and any(named <= h for h in heads if h):
            out.add(p)
    return out


def ghost_pointers(text, heading_texts):
    """Brackets naming no heading, and whether that is a broken pointer."""
    names = {heading_name(h).lower() for h in heading_texts if h.strip()}

    def unresolved(pointer):
        """The halves of a pointer that name no heading."""
        if pointer.lower() in names:
            return []
        parts = [x.strip() for x in re.split(r"[;,]", pointer) if x.strip()]
        if len(parts) < 2:
            return [pointer]
        missing = [x for x in parts if x.lower() not in names]
        return [pointer] if len(missing) == len(parts) else missing

    brackets = [q for q in (heading_name(p) for p in outer_brackets(text))
                if 3 <= len(q) <= 60
                and " " in q
                and not re.match(r"(?:see|cf|per|ref|e\.?g|i\.?e|and|or)\b",
                                 q, re.I)
                and not re.fullmatch(r"[^a-z]+", q)]
    ghosts = sorted({g for p in brackets for g in unresolved(p)})
    if not ghosts:
        return [], False
    stems = {w[:5].lower() for h in heading_texts
             for w in re.findall(r"[A-Za-z]{4,}", h)}
    near = any(w[:5].lower() in stems
               for g in ghosts for w in re.findall(r"[A-Za-z]{4,}", g))
    return ghosts, near and any(not unresolved(p) for p in brackets)


def heads_after(headings, renames):
    """The heading texts the run is about to write."""
    out = []
    for h in headings:
        old = heading_name(h[2])
        new = renames.get(old, old)
        if new:
            out.append(new)
    return out


def _orphaned_pointers(o_heads, n_heads, new):
    """Brackets in the edit that named an original heading and now name none."""
    def words(s):
        return {w for w in re.findall(r"[a-z]{3,}", s.lower())
                if w not in _HEADING_GRAMMAR}

    was = [words(h[2]) for h in o_heads if h[2].strip()]
    now = [words(h[2]) for h in n_heads if h[2].strip()]
    live = {heading_name(h[2]).casefold() for h in n_heads if h[2].strip()}
    out = set()
    for p in re.findall(r"\(([^()\n]{3,60})\)", new):
        p = heading_name(p)
        if p.casefold() in live:
            continue
        named = words(p) - _POINTING
        if len(named) >= 2 and any(named <= h for h in was if h) \
                and not any(named <= h for h in now if h):
            out.add(p)
    return sorted(out)


def summary_cap(body_words):
    """How long this document's summary may be."""
    if not body_words:
        return SUMMARY_MAX_WORDS
    share = int(body_words * THRESHOLDS["summary_share"])
    return max(SUMMARY_MIN_WORDS, min(SUMMARY_MAX_WORDS, share))


from killverbosity import summary as _summary


def _summary_words(text):
    """Word count for one line, blind to a `kv:` marker riding on it."""
    text = ALLOW_SHAPE_MARK.sub(" ", text)
    text = ALLOW_MARK.sub(" ", text)
    text = KEEP_MARK.sub(" ", text)
    text = SUMMARY_MARK.sub(" ", text)
    return len(text.split())


def _summary_rules():
    return _summary.Rules(heading=SUMMARY_HEADING,
                          needed_from=SUMMARY_NEEDED_FROM,
                          min_words=SUMMARY_MIN_WORDS,
                          cap=summary_cap,
                          words=_summary_words)


def has_title(headings, body):
    return _summary.has_title(headings, body, _summary_rules())


def opening_summary(headings, prose, words, text=None, headings_raw=None):
    """`text` is the RAW file, not the masked prose, and only for one question."""
    if SWITCHED_OFF.get("summary"):
        return None
    return _summary.opening_summary(
        headings, prose, words, _summary_rules(),
        declared=bool(text) and _summary.declares_abstract(text),
        verbatim=bool(transcript_stamps(headings_raw or headings)),
        raw=text.split("\n") if text else None,
        marked=any(SUMMARY_MARK.search(CODE_SPAN.sub(" ", p)) for p in prose))


def declares_abstract(text):
    return _summary.declares_abstract(text)


def _unheaded_lede(headings, prose, words):
    """The COUNT only. The branch that produced it reaches the messages through
    the state's `lede_where`; this wrapper stays int-valued because its callers
    ask "how many words" and nothing else."""
    return _summary._unheaded_lede(headings, prose, words, _summary_rules())[0]


def section_level(headings, body):
    return _summary.section_level(headings, body, _summary_rules())


def buried_above(summary):
    return _summary.buried_above(summary)


def buried_reason(summary):
    return _summary.buried_reason(summary)


def heads_summary(text):
    return _summary.heads_summary(text, _summary_rules())


def opens_with_summary(headings, prose, words):
    """The line the file opens its summary on, or 0. See summary.py."""
    return _summary.opens_with_summary(headings, prose, words,
                                       _summary_rules())


def summary_opens_after(lines, edits, owner):
    """The line the file will open its summary on once this run lands, or 0."""
    text = _summary.projected(lines, edits, owner, _summary_rules())
    try:
        prose, headings, _t, _q = mask(text)
    except UsageError:
        return 0
    return opens_with_summary(headings, prose, word_count(text))


def summary_verdict(s, written=None, refused=None):
    """One verdict on the opening summary, as `(key, sentence)`."""
    if not s:
        return None
    cap = summary_cap(s.get("doc"))
    if not s["present"] and s.get("buried"):
        return ("buried",
                f"BURIED — there is one at line {s['buried']}, with "
                f"{buried_reason(s)}. `structure` can "
                f"send those lines into a section with `move-block`, or "
                f"delete them if they only announce the document. Bringing "
                f"the summary up instead puts them inside it. Do not add a "
                f"second summary.")
    if not s["present"] and s.get("marked"):
        return ("marked",
                "MARKED — `<!-- kv:summary -->` says the opening prose "
                + (f"({s['lede']} words) " if s.get("lede") else "")
                + "is this file's summary. No summary section is owed. "
                "Nothing here checks that the prose states the result.")
    if not s["present"] and s.get("verbatim"):
        return ("verbatim",
                f"VERBATIM — this is a transcript (two or more elapsed-time "
                f"headings, starting near zero), and a verbatim record of what named "
                f"people said does not owe a reader an editorial summary at "
                f"the top. Writing one is the edit the speech protection "
                f"exists to prevent. If a summary of this meeting is wanted, "
                f"it belongs in a separate file.")
    if not s["present"] and s.get("declared"):
        return ("declared",
                f"DECLARED — the frontmatter carries a `description:`, which "
                f"is this file's abstract, and what sits under it is the "
                f"instruction body a harness reads, not an article's opening. "
                f"No summary section is owed. Nothing here checks that the "
                f"description is accurate.")
    if not s["present"] and s.get("lede"):
        where = _summary.lede_where_phrase(s.get("lede_where"))
        return ("unheaded",
                f"UNHEADED — {s['lede']} words of prose sit {where}. "
                f"If that is the summary, give it a heading with the "
                f"word Summary in it. If it is an introduction, it is not one "
                f"and it should go. If it is neither — a scope sentence, a "
                f"pointer list, a contents table, a definition the rest of the "
                f"file rests on — leave it, and say in your report that it is "
                f"none of the three.")
    if not s["present"] and refused:
        return ("refused",
                f"REFUSED — the run wrote one and its own gates dropped it: "
                f"{refused}. The file has no summary because of that, not "
                f"because none was attempted. A summary states the result in "
                f"its own words; one assembled out of sentences already in the "
                f"body will be dropped again.")
    if not s["present"] and s.get("headed"):
        return ("headed",
                f"HEADED — {s['headed']} words of prose sit under "
                f"'{s['headed_title']}' at line {s['headed_at']}, the first "
                f"section. Nothing here can tell a summary from a scope "
                f"section, so it is not counted as one. If it is the summary, "
                f"put the word Summary in that heading and change not one "
                f"word of the prose. If it is an introduction, it is not one "
                f"and it should go. If it is neither — a scope sentence, a "
                f"pointer list, a contents table, a definition the rest of "
                f"the file rests on — leave it, and say in your report that "
                f"it is none of the three.")
    if not s["present"]:
        return ("missing",
                f"MISSING — {s['words']} words with no one-page summary at the "
                f"top. State what this file is for and what a reader gets from "
                f"it, then where to go for each part. For a report that is "
                f"what was examined, the result and the open questions; for a "
                f"rules or reference file it is the scope and the map.")
    if s["words"] < SUMMARY_MIN_WORDS:
        return ("thin",
                f"'{s['title']}' at line {s['line']} holds {s['words']} words. "
                f"A heading is not a summary. State what was examined, the "
                f"result, the open questions with short answers, and which "
                f"section covers each.")
    if s["words"] > cap:
        if written is not None and written <= cap:
            return ("inherited",
                    f"{written} new words, inside the page. Its section reads "
                    f"{s['words']} because {s['words'] - written} words that "
                    f"were already in the file now sit under its heading. Move "
                    f"them below the summary or give them their own heading.")
        return ("over",
                f"{s['words']} words, over a page. Keep the result and the "
                f"pointers; move the rest into the body.")
    if not s.get("title"):
        return ("ok", f"line {s['line']}, {s['words']} words, no heading.")
    return ("ok", f"'{s['title']}' at line {s['line']}, {s['words']} words.")


def summary_headline(sentence):
    """The leading sentence of a `summary_verdict` text, for `plan`'s default
    (non-`--full`) report.
    """
    i = sentence.find(". ")
    if i == -1:
        return sentence
    return sentence[:i + 1] + " (--full for what to do)"



def chunk(prose, headings, target=2, tables=()):
    """Split on H2, then H3, then fixed paragraph runs. No overlap."""
    for level in (2, 3, 4, 5, 6):
        marks = [h for h in headings if h[1] == level]
        if len(marks) >= target:
            bounds = [m[0] for m in marks]
            titles = [m[2] for m in marks]
            break
    else:
        safe = []
        for i, ln in enumerate(prose):
            if ln.strip():
                continue
            nxt = next((prose[j] for j in range(i + 1, len(prose)) if prose[j].strip()), "")
            if nxt and not re.match(r"\s*(?:[-*+]|\d+\.)\s", nxt):
                safe.append(i)
        step = max(1, len(safe) // 6) if safe else 1
        bounds = [0] + safe[step::step]
        titles = [f"part {i + 1}" for i in range(len(bounds))]

    if bounds and bounds[0] > 0:
        bounds, titles = [0] + bounds, ["(preamble)"] + titles

    restored = with_table_text(prose, tables) if tables else prose

    out = []
    for n, (start, title) in enumerate(zip(bounds, titles)):
        end = bounds[n + 1] if n + 1 < len(bounds) else len(prose)
        body = [(i, restored[i]) for i in range(start, end)]
        out.append({"n": n + 1, "title": title, "start": start + 1, "end": end,
                    "lines": body})
    return out



SPECIALISTS = {
    "planning": ("document", (
        "phase plan", "task list", "estimate", "target date")),
    "noise": ("section", (
        "process leak", "editor note", "draft diff", "worklog",
        "commit or checkout ref", "unexplained reference",
        "asks reader to verify", "unsourced citation", "citation plumbing",
        "echo", "empty framing", "changelog narration", "bare internal id",
        "defers its own point")),
    "actionable": ("section", (
        "parked problem", "vague action", "activity report",
        "planning language")),
    "quotable": ("section", (
        "number without its noun", "identifier as subject",
        "evaluative adjective", "inanimate perceiver", "bare nominalisation",
        "idiom")),
    "prose": ("section", (
        "frame", "hedge", "purpose hedge", "wrapper", "agreement move",
        "jargon", "nominalisation", "X-not-Y", "em-dash pressure",
        "long sentence", "paragraph wall", "repeated list item",
        "mixed list styles")),
    "chat": ("document", tuple(CHAT)),
    "structure": ("document", ("corporate header",)),
    "summary": ("document", ()),
}



CHAT_ONLY = ("chat",)
DOC_ONLY = ("summary", "structure", "planning")

SPECIALIST_DIR = HERE / "specialists"



SYNTHETIC = {"em-dash pressure", "long sentence", "paragraph wall",
             "repeated list item", "mixed list styles"}


_BASE_EXISTENCE = dict(EXISTENCE)
_BASE_SPECIALISTS = dict(SPECIALISTS)

SWITCHED_OFF = {}
_BASE_SYNTHETIC = set(SYNTHETIC)
_BASE_SUBSTITUTION = dict(SUBSTITUTION)
_BASE_OCCURRENCE = dict(OCCURRENCE)


def all_shape_names():
    return (set(EXISTENCE) | set(SUBSTITUTION) | set(OCCURRENCE) | set(CHAT)
            | SYNTHETIC)


def owner_of(shape):
    for name, (_, shapes) in SPECIALISTS.items():
        if shape in shapes:
            return name
    return None


PROMPT_VALUES = {
    "SUMMARY_CAP": lambda dw: summary_cap(dw),
    "SUMMARY_MIN_WORDS": lambda dw: SUMMARY_MIN_WORDS,
    "SUMMARY_NEEDED_FROM": lambda dw: SUMMARY_NEEDED_FROM,
    "LONG_SENTENCE": lambda dw: LONG_SENTENCE,
    "CHAT_MAX_WORDS": lambda dw: CHAT_MAX_WORDS,
    "SAFE_ACRONYMS": lambda dw: ", ".join(VOCAB["safe_acronyms"]),
    "LENGTH_TARGET_PCT": lambda dw: f"{LENGTH_TARGET:.0%}",
    "INSERT_BLOCKING": lambda dw: ", ".join(sorted(INSERT_BLOCKING)),
}


def specialist_prompt(name, doc_words=None):
    """The specialist's own rules, on top of the floor every one of them shares."""
    common, own = SPECIALIST_DIR / "_common.md", SPECIALIST_DIR / f"{name}.md"
    for p in (common, own):
        if not p.is_file():
            raise UsageError(
                f"no prompt at {p}. The specialist prompts live next to "
                f"SKILL.md; reinstall the skill, or name the others in "
                f"{PROJECT_FILE} to skip this one.")
    text = f"{common.read_text()}\n\n{own.read_text()}"
    for key, fn in PROMPT_VALUES.items():
        text = text.replace("{{" + key + "}}", str(fn(doc_words)))
    left = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", text)))
    if left:
        raise UsageError(
            f"{name}.md asks for {left}, which this build cannot fill. "
            f"Known: {sorted(PROMPT_VALUES)}.")
    return text


def editable_lines(prose, tables, headings, quotes, frozen=()):
    """1-based lines a specialist may touch."""
    ok = {i + 1 for i, ln in enumerate(prose) if ln.strip()}
    ok |= {l for l, _ in tables} | {l for l, _ in quotes}
    ok |= {h[0] + 1 for h in headings}
    return (ok - keep_lines(prose) - protected.lines(headings, len(prose))
            - protected.dated_status_lines(headings) - set(frozen))


def count(n, word, plural=None):
    """`n` and its noun, agreeing. `1 candidates` was printed on a real run."""
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def numbered(lines, lo, hi):
    return "\n".join(f"{i:>5} | {lines[i - 1]}" for i in range(lo, hi + 1))


def empty_span_error(job, lines):
    """None, or the reason this job must not be dispatched."""
    if job.get("outline"):
        return None
    hi = job["hi"] or len(lines)
    if numbered(lines, job["lo"], hi).strip():
        return None
    return (f"this job's span (lines {job['lo']}-{hi} of {len(lines)}) is "
            f"empty -- the specialist would be asked to edit text that "
            f"never reached the prompt")


def version_line():
    """The build, and the file it was hashed from."""
    try:
        where = Path(__file__).resolve()
    except OSError:
        where = Path(__file__)
    return (f"kill-verbosity build {build_id()} "
            f"(_legacy.py is this tool's live main module, not dead code), "
            f"hashed from:\n{where}")


def build_id():
    """Short hash of this file, for the run header."""
    try:
        raw = Path(__file__).read_bytes()
    except OSError:
        return "unknown"
    return f"{hashlib.sha256(raw).hexdigest()[:8]} {len(raw.splitlines())}L"


def summary_blocked(summary):
    """Why the `summary` job did not run, in one sentence."""
    if off := SWITCHED_OFF.get("summary"):
        return f"off for {off} — this kind of document is not owed one"
    if (summary or {}).get("buried"):
        return (f"BURIED at line {summary['buried']} — `structure` has it. "
                f"There are {buried_reason(summary)}, and they have no "
                f"heading, so they go into a section with `move-block`; "
                f"moving the summary up swallows them into it instead")
    v = summary_verdict(summary)
    return v[1] if v else "the file already opens with a summary, within the cap"


def unheaded_note(lede, for_summary, where=None):
    """What a job is told about an unheaded opening."""
    head = (f"\n\nIt opens with {lede} words of prose "
            f"{_summary.lede_where_phrase(where)}. "
            "That may be the summary already. ")
    if for_summary:
        return head + (
            "Read them and decide. They are the summary only if they state "
            "the result and name what to read next; a block that says what "
            "the document is about is an introduction. If they are the "
            "summary, give them a heading with the word Summary in it and "
            "change not one word of the prose. If they are an introduction, "
            "write a summary and insert it above them. Never write a second "
            "summary that repeats what they already say.")
    return head + ("Leave those words as they are — do not add a heading over "
                   "them, do not rewrite them, and do not write a second "
                   "summary.")


def summary_owed(summary):
    """True when the document-scope summary job has something to answer."""
    if not summary:
        return True
    if not summary["present"]:
        if summary.get("verbatim"):
            return False
        if summary.get("marked"):
            return False
        if summary.get("declared"):
            return False
        if summary.get("buried"):
            return False
        return True
    return not (SUMMARY_MIN_WORDS <= summary["words"]
                <= summary_cap(summary.get("doc")))


def build_jobs(chunks, hits, chat, only, breaks=(), needs_summary=True,
               summary=None, chosen_by_tool=False):
    """One job per (specialist, unit) that has work. Returns them in pass order."""
    wanted = set(only.split(",")) if only else None
    missing = sorted(wanted - set(SPECIALISTS)) if wanted else []
    if off := [n for n in missing if n in SWITCHED_OFF]:
        raise UsageError(
            f"{', '.join(off)} {'is' if len(off) == 1 else 'are'} switched off "
            f"by {SWITCHED_OFF[off[0]]}. It exists; this document's kind does "
            f"not use it.")
    if missing:
        raise UsageError(f"no such specialist: {', '.join(missing)}. "
                         f"Pick from: {', '.join(SPECIALISTS)}")
    off = set(DOC_ONLY if chat else CHAT_ONLY)
    if wanted and wanted <= off:
        raise UsageError(
            f"{', '.join(sorted(wanted))} "
            f"{'does' if len(wanted) == 1 else 'do'} not run "
            f"{'on a chat message' if chat else 'without --chat'}.")
    if not needs_summary:
        if wanted == {"summary"}:
            raise UsageError(f"the file is under {SUMMARY_NEEDED_FROM} words, "
                             f"so it is already its own summary.")
        off.add("summary")
    jobs, blocked = [], {}
    for name, (scope, shapes) in SPECIALISTS.items():
        if wanted is not None and name not in wanted:
            continue
        if name in off:
            continue
        mine = [h for h in hits if h[1] in shapes]
        if scope == "document":
            if name == "summary" and not summary_owed(summary):
                blocked["summary"] = summary_blocked(summary)
                continue
            if name == "planning" and not mine:
                blocked["planning"] = ("nothing schedules anything: no phase, "
                                       "task list, estimate or target date "
                                       "fired")
                continue
            notes_only = name == "structure" and not hits
            jobs.append({"specialist": name, "unit": "document",
                         "lo": 1, "hi": None, "hits": mine,
                         "notes_only": notes_only,
                         "unbury": bool(notes_only and summary
                                        and summary.get("buried"))})
            continue
        for c in chunks:
            wins = windows(c["start"], c["end"], breaks,
                           words=_span_words(c))
            for k, (lo, hi) in enumerate(wins, 1):
                here = [h for h in mine if lo <= h[0] <= hi]
                if here:
                    part = f" ({k}/{len(wins)})" if len(wins) > 1 else ""
                    jobs.append({"specialist": name,
                                 "unit": f"chunk {c['n']}{part} · {c['title']}",
                                 "lo": lo, "hi": hi, "hits": here})
    if wanted:
        ran = {j["specialist"] for j in jobs}
        idle = sorted(wanted - ran)
        if idle:
            why = "; ".join(
                f"{n}: {blocked.get(n, 'no shape it owns fired in this file')}"
                for n in idle)
            if not ran and not chosen_by_tool:
                raise UsageError(why)
            if not ran:
                print(f"kill-verbosity: the declared specialist set found "
                      f"nothing it owns in this file - {why}. Widen or drop "
                      f"`specialists` in the .killverbosity.json to run the "
                      f"rest.", file=sys.stderr)
            elif ran:
                print(f"kill-verbosity: idle this file, the rest still run - "
                      f"{why}", file=sys.stderr)
    return jobs


MAX_SPAN = THRESHOLDS["max_span"]
MAX_SPAN_WORDS = THRESHOLDS["max_span_words"]


def _span_words(c):
    """A chunk's word count per line number, 1-based to match start/end."""
    if not c.get("lines"):
        return None
    return {i + 1: len(ln.split()) for i, ln in c["lines"]}


def _word_windows(start, end, breaks, words):
    """windows() with the cap counted in words. See windows()."""
    def tally(a, b):
        return sum(words.get(i, 0) for i in range(a, b + 1))

    if tally(start, end) <= MAX_SPAN_WORDS:
        return [(start, end)]
    brk = sorted(b for b in breaks if start < b <= end)
    out, s = [], start
    while tally(s, end) > MAX_SPAN_WORDS:
        limit, acc = s, 0
        for i in range(s, end + 1):
            acc += words.get(i, 0)
            if acc > MAX_SPAN_WORDS:
                break
            limit = i
        if limit >= end:
            break
        near = [b for b in brk
                if s < b <= limit + 1 and tally(s, b - 1) >= MAX_SPAN_WORDS // 2]
        cut = max(near[-1] if near else limit + 1, s + 1)
        out.append((s, cut - 1))
        s = cut
    out.append((s, end))
    return out


def windows(start, end, breaks=(), words=None):
    """Split a line range into editable spans."""
    if words is not None:
        return _word_windows(start, end, breaks, words)
    if end - start < MAX_SPAN:
        return [(start, end)]
    brk = sorted(b for b in breaks if start < b <= end)
    out, s = [], start
    while end - s + 1 > MAX_SPAN:
        limit = s + MAX_SPAN
        near = [b for b in brk if s + max(1, MAX_SPAN // 2) <= b <= limit]
        cut = near[-1] if near else limit
        out.append((s, cut - 1))
        s = cut
    out.append((s, end))
    return out


def token_lines(lines):
    """Every protected token in the file, mapped to the lines that hold it."""
    out, fenced = defaultdict(set), fence_lines(lines)
    for i, ln in enumerate(lines, 1):
        if i in fenced:
            continue
        for vals in facts(ln).values():
            for v in vals:
                out[v].add(i)
    return out


def only_copy(index, lo, hi):
    """Protected tokens inside the span that appear nowhere else in the file."""
    return sorted(v for v, where in index.items()
                  if len(where) == 1 and lo <= next(iter(where)) <= hi)


def resolving_refs(lines, lo, hi, base):
    """Relative paths named in the span that exist on disk next to the file."""
    out = []
    for ln in lines[lo - 1:hi]:
        for m in re.finditer(r"[\w./-]+\.(?:%s)\b" % CODE_EXT, ln):
            p = base / m.group(0)
            if p.is_file() and m.group(0) not in out:
                out.append(m.group(0))
    return out


def repeat_key(s):
    """A string reduced to what `duplicates` compares: lowercase word tokens."""
    return " ".join(WORD.findall(SEGMENTED.sub(" ", s).lower()))


def repeat_blame(added, results):
    """Edits whose replacement text carries a repeat the pass introduced."""
    want = [head for d in added
            if (head := " ".join(d["text"].split()[:DUPLICATE_FROM_WORDS]))]
    return {id(e) for r in results for e in r.get("edits", ())
            if (body := repeat_key(e.get("new", "")))
            and any(w in body for w in want)}


def repeat_delta(o_dups, n_dups):
    """(resolved count, introduced clusters), matched on the repeated text."""
    def copies(d):
        return len(d.get("lines") or ()) or 2

    def key(d):
        return " ".join(d["text"].split()[:DUPLICATE_FROM_WORDS])

    was = {key(d): copies(d) for d in o_dups}
    out = []
    for d in n_dups:
        before = was.get(key(d))
        if copies(d) > (before or 1):
            out.append({**d, "before": before, "now": copies(d)})
    return len(set(was) - {key(d) for d in n_dups}), out


def duplicate_jobs(dups, n_lines, spans=None):
    """One `structure` job per repeated-text cluster."""
    out = []
    for d in dups:
        ln = sorted(d["lines"])
        if len(ln) < 2:
            continue
        lo, hi = max(1, ln[0] - 2), min(n_lines, ln[-1] + 2)
        said = [_wrapping.source_span(i, i, spans or [])[0]
                for i in (ln[0], ln[-1])]
        out.append({
            "specialist": "structure",
            "unit": f"repeat · lines {said[0]}/{said[1]}",
            "lo": lo, "hi": hi,
            "hits": [(i, "repeated text", d["text"][:90]) for i in ln],
            "one_duplicate": d,
        })
    return out


def outline_of(headings, lines, prose, scheduled=None):
    """One line per heading: where it is, what it says, how big, what it opens."""
    hs = [(h[0] + 1, h[1], h[2]) for h in headings]
    out = []
    for i, (ln, lvl, txt) in enumerate(hs):
        end = hs[i + 1][0] - 1 if i + 1 < len(hs) else len(lines)
        first = next((l.strip() for l in prose[ln:end] if l.strip()
                      and not LIST_ITEM.match(l)), "")
        words = sum(len(l.split()) for l in lines[ln:end])
        mark = ""
        if scheduled is not None:
            mark = "  " + body_mark(scheduled.get(ln))
        out.append(f"{ln:>5} | {'#' * lvl} {heading_name(txt)}  ({words}w)"
                   + mark
                   + (f"\n        {first[:120]}" if first else ""))
    return "\n".join(out)


def group_notes(notes):
    """`(specialist, note)` pairs bundled by text, rarest bundle first."""
    def key(n):
        out, at = [], 0
        for m in CODE_SPAN.finditer(n):
            out += [n[at:m.start()].lower(), m.group(0)]
            at = m.end()
        out.append(n[at:].lower())
        return tuple(re.findall(r"[A-Za-z0-9]+", "".join(out)))

    groups = {}
    for who, n in notes:
        groups.setdefault(key(n), []).append((who, n))
    return sorted(groups.values(), key=len)


def error_digest(err, keep=2):
    """The first two lines of a failure. The rest of a stack trace is dropped."""
    got = [ln.strip() for ln in (err or "").splitlines() if ln.strip()]
    if not got:
        return ""
    out = " · ".join(got[:keep])
    return out if len(got) <= keep else f"{out} … +{len(got) - keep} lines"


def job_prompt(job, lines, context, index, extra="", base=None):
    """The specialist's rules, the document it lives in, and its own span."""
    if job.get("outline") and job["specialist"] == "planning":
        return (
            f"{specialist_prompt(job['specialist'], sum(len(l.split()) for l in lines))}\n\n"
            f"# The document you are working inside\n\n{context}\n\n"
            f"# This job is which sections come out, and nothing else\n\n"
            f"Below is every heading in the document: its real line number, "
            f"its level, how many words the section holds, and the line it "
            f"opens on. The prose is not here. What you are deciding is "
            f"whether a section is a SCHEDULE -- a phase, a milestone, a "
            f"sprint, a task list, an estimate, a target date -- and the "
            f"heading and the size are what answer that.\n\n"
            f"```````\n{job['outline']}\n```````\n\n"
            f"Send `delete-section` operations only. Each one names the line "
            f"of ONE heading, and the whole section comes out with it -- its "
            f"body, its subsections, its tables and its fenced blocks:\n"
            f'  {{"op": "delete-section", "line": 88, '
            f'"why": "Phase 2 is a rollout plan"}}\n\n'
            f"You do not name a line range and you do not send one edit per "
            f"line. The section is worked out from the heading, so it lands "
            f"whole or not at all: a run of `replace` edits is where half a "
            f"roadmap comes from.\n\n"
            f"Send no `replace`, no `insert` and no `move`. Rewording is "
            f"another specialist's job on the real lines, and an edit written "
            f"from here would be written without the section in front of "
            f"you.\n\n"
            f"Zero deletions is a legal answer and often the right one. It is "
            f"not a free one. Whatever you send, put one `note` naming the "
            f"section you came closest to deleting and why you left it. A "
            f"reader has to be able to see which ones you weighed.\n\n"
            f"A section naming a phase is not automatically a plan. `Phase 2` "
            f"in a state machine, a build or a release procedure names a real "
            f"thing the reader needs; a roadmap section exists to say when "
            f"work will happen, and nothing under it survives the week. If "
            f"the heading alone does not settle it, leave it and say so in a "
            f"note.\n\n"
            f"The heading NEVER settles it on its own, and the gate enforces "
            f"that: a `delete-section` is refused unless the section's own "
            f"body schedules something -- an unchecked box, a date, an owner "
            f"or an estimate. Each heading below is marked with what its body "
            f"schedules, and `{BODY_MARK_NONE}` means the heading is "
            f"the only evidence there is. Those are the methodology sections "
            f"an ordinal heading makes look like a plan; flag one in a note "
            f"if you must, and do not send it.\n\n"
            f"Deleting a section is the most destructive operation in this "
            f"tool. Proving you worked by taking one out is worse than "
            f"sending nothing.\n"
            f"{extra}\n")
    if job.get("outline"):
        return (
            f"{specialist_prompt(job['specialist'], sum(len(l.split()) for l in lines))}\n\n"
            f"# The document you are working inside\n\n{context}\n\n"
            f"# This job is the section order, and nothing else\n\n"
            f"Below is every heading in the document: its real line number, "
            f"its level, how many words the section holds, and the line it "
            f"opens on. The prose is not here because you do not need it to "
            f"decide what order the sections go in.\n\n"
            f"```````\n{job['outline']}\n```````\n\n"
            f"Send `move` operations only. Each one names the line of the "
            f"heading to move and the line of the heading it goes before:\n"
            f'  {{"op": "move", "line": 431, "to": 88, "why": "result first"}}\n\n'
            f"Send no `replace` and no `insert` — renaming and rewording are a "
            f"separate job on the real lines, and an edit from here would be "
            f"written without the section in front of you.\n\n"
            f"Move a section when the reader needs it earlier: the result "
            f"before the background, the decision before the reasoning, the "
            f"runbook before the history.\n\n"
            f"Zero moves is a legal answer and often the right one. It is not "
            f"a free one. Whatever you send, put one `note` naming the two "
            f"headings you came closest to moving, where you thought of "
            f"putting each, and why you did or did not. A reader has to be "
            f"able to see which order you checked.\n\n"
            f"Do not reorder a document that already reads in the right order. "
            f"A move is the most destructive operation here — proving you "
            f"worked by shuffling sections is worse than sending nothing.\n"
            f"{extra}\n")
    doc_words = sum(len(ln.split()) for ln in lines)
    hi = job["hi"] or len(lines)
    flagged = "\n".join(f"   {l:>5}  {k:<24} {t}" for l, k, t in job["hits"]) \
        or "   (nothing matched here — read the span and use your own judgement)"
    last = only_copy(index, job["lo"], hi)
    unique = ("\n\n# The document's only copy of these\n\n"
              + ", ".join(f"`{v}`" for v in last[:60])
              + "\n\nEach appears nowhere else in the file. Deleting the line "
                "that holds one loses it for good. Keep the fact and cut the "
                "words around it.\n" if last else "")
    spans = sorted({v for ln, v in wrap_runs(lines).items()
                    if job["lo"] <= ln <= hi})
    wrapped = ("\n\n# Sentences that wrap in your span\n\n"
               + "\n".join(f"   lines {a}-{b}" for a, b in spans[:60])
               + "\n\nEach is one sentence over several lines. Edit it whole: "
                 "the rewrite on the first line, `new: \"\"` on every other "
                 "line of the range. Do not count the lines yourself.\n\n"
                 "Editing one line of a wrap on its own is refused every time, "
                 "because the other half is left as a fragment — and on a "
                 "hard-wrapped document that is a fifth of the file you cannot "
                 "otherwise touch, including the long sentences most worth "
                 "rewriting.\n\n"
                 "Your first line must carry **everything those lines said**, "
                 "not only the sentence you came to fix. The last line often "
                 "starts the next sentence and the first line often ends the "
                 "one before; both have to survive, or you have deleted text "
                 "nobody asked you to touch. Read the whole of the first and "
                 "last line of the range and check your replacement against "
                 "them before you send it.\n"
               if spans else "")
    span_words = sum(len(lines[i - 1].split()) for i in range(job["lo"], hi + 1))
    budget = (f"\n\n# How much comes out\n\n"
              f"Your span holds {span_words} words. The document holds "
              f"{doc_words} and should come back near "
              f"{round(doc_words * LENGTH_TARGET)}.\n\n"
              f"That budget is shared with every other job in this run, so do "
              f"not try to reach it alone — take what your own rules give you. "
              f"But a reply that leaves your span the same length has spent "
              f"its edits and bought nothing.\n" if span_words >= 40 else "")
    live = resolving_refs(lines, job["lo"], hi, base) if base else []
    resolvable = ("\n\n# References that resolve\n\n"
                  + ", ".join(f"`{v}`" for v in live[:40])
                  + "\n\nEach of these files exists next to this document. The "
                    "reader can open it, so none of them is an unexplained "
                    "reference. Leave the link.\n" if live else "")
    return (
        f"{specialist_prompt(job['specialist'], doc_words)}\n\n"
        f"# The document you are working inside\n\n{context}\n\n"
        f"# Your span — lines {job['lo']} to {hi}\n\n"
        f"Change nothing outside these lines. Other specialists own the rest.\n\n"
        f"```````\n{numbered(lines, job['lo'], hi)}\n```````\n\n"
        f"# Flagged in your span\n\n{flagged}\n"
        f"{unique}{budget}{wrapped}{resolvable}{extra}\n"
        f"The middle column is the rule's own name. Your prompt may word it "
        f"differently — put that name in `why` so the report reads back.\n\n"
        f"A flag is a place to look, not a verdict. Leave the ones that are "
        f"right as they are — an empty `edits` already says you rejected them, "
        f"so do not write a note about it. Fix anything your rules catch that "
        f"the list missed.\n"
    )


def _why_it_died(stderr: str) -> str:
    """The reason a backend exited, taken from the END of its stderr.

    Failure markers land at the end, so the last three non-blank lines are the
    reason and the first lines (banners, progress) are not.
    """
    lines = [l for l in (stderr or "").splitlines() if l.strip()]
    return " · ".join(l.strip() for l in lines[-3:])


LOCAL_AGENTS = ("claude", "codex", "agy", "delegate")
AGENT_ALIASES = {"gemini": "agy", "antigravity": "agy"}


NO_AGENT = ("no agent CLI found: install one of claude/codex/agy/delegate, "
            "or pass "
            "--agent '<your agent command>' that reads the prompt on stdin "
            "and prints the answer")


def agent_name(name):
    """The canonical local agent for `name`, or the command line itself.

    A command whose first word is not one of `LOCAL_AGENTS` is a CUSTOM agent:
    it is run as given, with the prompt on stdin and the answer on stdout.
    """
    words = shlex.split(name or "", posix=sys.platform != "win32")
    if not words:
        raise UsageError(f"empty agent: {NO_AGENT}")
    first = AGENT_ALIASES.get(words[0].lower(), words[0].lower())
    if first not in LOCAL_AGENTS:
        return name.strip()
    if len(words) > 1:
        raise UsageError(f"{words[0]} is run with its own flags; pass "
                         f"--agent {first} alone")
    return first


def is_custom_agent(agent):
    """Whether `agent` is a user-given command line, not a `LOCAL_AGENTS` name."""
    return agent not in LOCAL_AGENTS


def default_agent():
    """`KV_AGENT`, else the first installed of `LOCAL_AGENTS`, else `UsageError`."""
    named = os.environ.get("KV_AGENT")
    if named:
        return agent_name(named)
    for b in LOCAL_AGENTS:
        if agent_installed(b):
            return b
    raise UsageError(NO_AGENT)


def _agent_type(value):
    """argparse `type=` for an agent name."""
    try:
        return agent_name(value)
    except UsageError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


_INSTALLED_OVERRIDE = None


def agent_installed(name):
    """Whether the agent's CLI is on PATH.

    `_INSTALLED_OVERRIDE`, when set to a dict, answers instead of PATH, so the
    selftest and the tests can pin which agents exist.
    """
    if is_custom_agent(AGENT_ALIASES.get(name, name)):
        argv, _ = _cli_argv(name)
        return bool(argv) and shutil.which(argv[0]) is not None
    if _INSTALLED_OVERRIDE is not None:
        return bool(_INSTALLED_OVERRIDE.get(AGENT_ALIASES.get(name, name)))
    return shutil.which(name) is not None


def local_availability():
    """{agent: installed} for every local agent CLI."""
    return {b: agent_installed(b) for b in LOCAL_AGENTS}


def rung_available(avail, backend):
    """True/False for `backend` in a `local_availability` result, None if unknown."""
    if not avail:
        return None
    return avail.get(AGENT_ALIASES.get(backend, backend))


def agent_chain(agent, avoid=()):
    """The agents one job may try, in order, first is the caller's own.

    The caller's own agent always leads, installed or not, so its failure is
    the one reported. The rest are the other installed local agent CLIs, in
    `LOCAL_AGENTS` order, never a duplicate, and never one in `avoid` -- the
    agents that already answered this job with a reply that would not parse.
    """
    out = [] if agent in avoid else [agent]
    for b in LOCAL_AGENTS:
        if b not in out and b not in avoid and agent_installed(b):
            out.append(b)
    return out


def _accepts(fn, name):
    """Whether `fn` has a parameter of that name."""
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _takes_say(fn):
    """Whether a launcher accepts the fallback reporter."""
    return _accepts(fn, "say")


def call_agent(prompt, agent, timeout, say=None, avoid=(), answered=None):
    """Try each agent in `agent_chain` until one answers. Returns (out, err).

    The error returned is the FIRST one: that is the agent the caller asked
    for, and the one whose reason they can act on. Every later reason is
    printed as it happens. The clock is shared across the chain, so a fallback
    never gets more time than the job had left.
    """
    first = None
    left = float(timeout)
    chain = agent_chain(agent, avoid)
    if not chain:
        return "", (f"every agent has already answered this span badly "
                    f"({', '.join(avoid)}), so there is none left to ask")
    for i, one in enumerate(chain):
        if i and left < 20:
            if say:
                say(f"no clock left to try {one} ({left:.0f}s of {timeout}s)")
            break
        _t0 = time.monotonic()
        _one_kw = {"say": say} if _accepts(_call_one, "say") else {}
        _via = []
        if answered and _accepts(_call_one, "answered"):
            _one_kw["answered"] = _via.append
        got, err = _call_one(prompt, one, max(1, int(left)), **_one_kw)
        left -= time.monotonic() - _t0
        if err is None:
            if i and say:
                say(f"{agent} failed, answered by {one} instead — {first}")
            if answered:
                answered(one, _via[-1] if _via else None, bool(_via))
            return got, None
        if first is None:
            first = err
        elif say:
            say(f"fallback {one} also failed — {err}")
    return "", first


class BackendUnusable(Exception):
    """The request itself is wrong, so no other agent can answer it."""


class _LaunchError(str):
    """An error string that also says the agent could never be started.

    A subclass of `str` so it flows everywhere a plain error string does; only
    the retry pass tells it apart, because re-dialling a missing binary only
    spends the retry.
    """


def _cli_argv(name, platform=None):
    """The argv prefix to launch an installed CLI by name. Returns (argv, error).

    On Windows `CreateProcess` needs the real file name with its extension, and
    a CLI installed through npm is a `.cmd` shim, so the name is resolved the
    way a shell would (`shutil.which` honours PATHEXT). A custom agent's
    command line is split into words and its first word resolved the same way.
    """
    win = (sys.platform if platform is None else platform) == "win32"
    words = ([name] if name in LOCAL_AGENTS
             else shlex.split(name, posix=not win) or [name])
    if not win:
        return words, None
    found = shutil.which(words[0])
    if not found:
        return None, f"no {words[0]} found on PATH"
    return [found, *words[1:]], None


AGY_STREAM_ARGS = ["--input-format", "stream-json",
                   "--output-format", "stream-json"]


def agent_command(agent, argv, prompt, timeout, grounded=False, workdir=None):
    """The full command line and the stdin text for one agent call.

    Every agent gets the prompt on stdin, never in argv: a long prompt
    overflows the Windows command-line limit. `grounded` is a crosscheck, where
    the agent must read files; a specialist call needs no tools at all.

    claude  `claude -p` with no tools, or read-only tools when grounded.
    codex   `codex exec --sandbox read-only`, prompt from stdin (`-`).
    agy     the Antigravity CLI in print mode, `--sandbox`, with the prompt as
            one stream-json message (its only stdin route for a prompt).
    delegate  the multi-backend `delegate` dispatcher, `--mode raw` (the one
            template with no output contract of its own), the task read from
            stdin via `--prompt-file -`, `--grounded` when files must be read.
            No `--strict`: delegate's own fallback chain stays on.
    other   a custom command line, run as given, prompt on stdin.
    """
    if agent == "claude":
        return ([*argv, "-p", *(CLAUDE_READONLY if grounded else CLAUDE_NO_TOOLS)],
                prompt)
    if agent == "codex":
        return ([*argv, "exec", "--skip-git-repo-check",
                 "--sandbox", "read-only", "-"], prompt)
    if agent == "agy":
        dirs = ["--add-dir", str(workdir)] if workdir else []
        return ([*argv, *AGY_STREAM_ARGS, "--sandbox",
                 "--dangerously-skip-permissions", "--disable-slash-commands",
                 *dirs, "--print-timeout", f"{max(1, int(timeout))}s"],
                json.dumps({"event": "user", "message": {"content": prompt}})
                + "\n")
    if agent == "delegate":
        return ([*argv, "--mode", "raw", "--timeout", str(max(1, int(timeout))),
                 *(["--grounded"] if grounded else []),
                 "--prompt-file", "-"], prompt)
    return list(argv), prompt


def agent_answer(agent, stdout):
    """The answer text out of an agent's stdout.

    agy answers in stream-json: the answer is `result.response` on the last
    `"event":"result"` line, and a result whose status is not SUCCESS is no
    answer. Lines that are not JSON (a login prompt, an error) are returned as
    they were, so the caller still sees them.
    """
    if agent != "agy":
        return stdout or ""
    result, plain = None, []
    for line in (stdout or "").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            plain.append(line)
            continue
        if isinstance(ev, dict) and ev.get("event") == "result":
            result = ev.get("result") or {}
    if result is None:
        return "\n".join(plain)
    if result.get("status") and result.get("status") != "SUCCESS":
        return ""
    return result.get("response") if isinstance(result.get("response"), str) else ""


_CAUSE_402_RE = re.compile(r"\b402\b|insufficient credit", re.I)
_CAUSE_QUOTA_RE = re.compile(
    r"\bquota\b|\brate.?limit(?:ed)?\b|\b429\b|usage limit", re.I)
_CAUSE_AUTH_RE = re.compile(
    r"\bunauthoriz|\b401\b|\b403\b|\bapi.?key\b|not authenticated|"
    r"\blogin\b|\bauth(?:entication)?\b|token refresh|\boauth\b", re.I)


def _subst_cause(reason):
    """One of `402` / `quota` / `auth` / `other` for a failure text."""
    if _CAUSE_402_RE.search(reason):
        return "402"
    if _CAUSE_QUOTA_RE.search(reason):
        return "quota"
    if _CAUSE_AUTH_RE.search(reason):
        return "auth"
    return "other"


_FELL_FAILED_RE = re.compile(r"^(\S+) failed, answered by \S+ instead — (.*)$")


def _subst_rung_causes(msgs):
    """(agent, cause) for every failed agent a substituted job's messages name."""
    out = []
    for msg in msgs:
        m = _FELL_FAILED_RE.match(msg)
        if m:
            out.append((m.group(1), _subst_cause(m.group(2))))
    return out


def _call_one(prompt, agent, timeout, say=None, answered=None):
    """One shot at one local agent CLI. Returns (stdout, error).

    Raises `BackendUnusable` when the failure is the caller's argument rather
    than the agent's state. A launch failure -- the process never started --
    comes back as a `_LaunchError`. A timeout kills the agent's whole process
    tree, not only the CLI itself.
    """
    argv, argv_err = _cli_argv(agent)
    if argv_err:
        return "", _LaunchError(f"could not run {agent}: {argv_err}")
    cmd, stdin = agent_command(agent, argv, prompt, timeout)
    try:
        r = spawn.run_tree(cmd, timeout=timeout + 30, input=stdin)
    except subprocess.TimeoutExpired:
        return "", f"{agent} timed out after {timeout}s"
    except OSError as e:
        return "", _LaunchError(f"could not run {agent}: {e}")
    out = agent_answer(agent, r.stdout)
    if r.returncode != 0:
        said = _why_it_died(r.stderr) or out.strip()
        if agent == "claude" and claude_flag_missing(r.stderr + r.stdout):
            raise BackendUnusable(
                f"the local `claude` on this machine does not accept "
                f"{' '.join(CLAUDE_NO_TOOLS)}, so this tool cannot bound what "
                f"it may do: {said[:200]}. Upgrade `claude`, or run with "
                f"`--agent codex` / `--agent agy`.")
        return "", budget.local_flags(
            f"{agent} exited {r.returncode}: {said[:300]}")
    if not out.strip():
        return "", f"{agent} exited 0 with no answer"
    if answered:
        answered(agent)
    return out, None


_NO_SOURCE_LINES_RE = re.compile(
    r"no\b[^.]{0,60}\bsource lines?\b[^.]{0,60}\b(provided|given|included|"
    r"present)", re.I)


def parse_reply(raw):
    """Pull the JSON object out of a model answer. Returns (payload, error)."""
    payload, err = reply.payload(raw)
    if err:
        return None, err
    if not isinstance(payload, dict):
        return None, "answer is not a JSON object"
    edits = payload.get("edits") or []
    notes = payload.get("notes") or []
    if not isinstance(edits, list) or not isinstance(notes, list):
        return None, "`edits` and `notes` must be lists"
    clean = []
    for e in edits:
        if not isinstance(e, dict):
            return None, f"an edit is not an object: {e!r:.60}"
        if type(e.get("line")) is not int:
            return None, f"an edit has no integer `line`: {e!r:.60}"
        if not all(isinstance(e.get(k, ""), str) for k in ("old", "new", "why", "op")):
            return None, f"an edit field is not a string: {e!r:.60}"
        clean.append(e)
    return {"edits": clean, "notes": [str(n) for n in notes]}, None


DELETERS = ("noise", "planning")

MOVERS = ("structure",)

SECTION_DELETERS = ("planning",)

GROUPERS = ("structure",)
MAX_GROUP_LINES = 6


def section_span(headings, n_lines, line):
    """The lines a heading owns, 1-based and inclusive. None if not a heading."""
    hs = [(h[0] + 1, h[1]) for h in headings]
    for i, (ln, lvl) in enumerate(hs):
        if ln != line:
            continue
        for nxt, nxt_lvl in hs[i + 1:]:
            if nxt_lvl <= lvl:
                return ln, nxt - 1
        return ln, n_lines
    return None


PLAN_DATE = re.compile(
    r"\b\d{4}-\d{2}(?:-\d{2})?\b"
    r"|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b"
    r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b"
    r"|\b(?:Q[1-4]|H[12])\s*(?:of\s+)?20\d\d\b", re.I)
PLAN_OWNER = re.compile(
    r"(?:^|\|)\s*(?:[-*+]\s*)?(?:\*\*)?"
    r"(?:owner|owned by|assignee|assigned to|dri|responsible|accountable)"
    r"(?:\*\*)?\s*[:=]", re.I)


def plan_body_lines(body):
    """Which of a section's own lines say work is SCHEDULED."""
    out = []
    for i, ln in enumerate(body):
        for name in ("task list", "estimate", "target date"):
            rx = EXISTENCE.get(name)
            if rx is not None and rx.search(ln):
                out.append((i, name))
                break
        else:
            if PLAN_OWNER.search(ln):
                out.append((i, "owner"))
            elif PLAN_DATE.search(ln):
                _wl = EXISTENCE.get("worklog")
                if _wl is None or not _wl.search(ln):
                    out.append((i, "date"))
    return out


def section_schedules(headings, lines, line, end=None):
    """`(span, plan markers)` for one heading, or `(None, [])`."""
    span = section_span(headings, end if end is not None else body_end(lines),
                        line)
    if span is None:
        return None, []
    return span, plan_body_lines(lines[span[0]:span[1]])


def body_mark(what):
    """The outline cell that tells `planning` what a section's body schedules."""
    return f"[body schedules: {what or 'nothing'}]"


BODY_MARK_NONE = body_mark(None)


def scheduled_sections(headings, lines):
    """Heading line → what that section's body schedules. Empty ones omitted."""
    end, out = body_end(lines), {}
    for h in headings:
        ln = h[0] + 1
        _span, marks = section_schedules(headings, lines, ln, end=end)
        if marks:
            out[ln] = ", ".join(sorted({m for _i, m in marks}))
    return out


def block_span(lines, headings, ln, thru, end):
    """The lines a `move-block` carries, or (None, why it may not)."""
    if not isinstance(thru, int) or not ln <= thru <= end:
        return None, "`thru` is not a line at or after `line`"
    if {h[0] + 1 for h in headings} & set(range(ln, thru + 1)):
        return None, "that block holds a heading — move the section instead"
    if not lines[ln - 1].strip() or not lines[thru - 1].strip():
        return None, "a block opens and closes on a line with text on it"
    if ln > 1 and lines[ln - 2].strip():
        return None, (f"line {ln - 1} runs straight into it — start the block "
                      f"where the text starts")
    if thru < len(lines) and lines[thru].strip():
        return None, (f"line {thru + 1} carries on from it — end the block "
                      f"where the text ends")
    fenced = fence_lines(lines)
    if (ln in fenced and ln - 1 in fenced) or (thru in fenced
                                               and thru + 1 in fenced):
        return None, "that is half a fenced block — take the whole fence"
    body = lines[ln - 1:thru]
    if (_list_material(body[0])
            and _list_material(_nearest_text(lines, ln - 1, -1))) or (
            _list_material(body[-1])
            and _list_material(_nearest_text(lines, thru + 1, 1))):
        return None, "that is part of a list — take the whole list"
    return (ln, thru), None


def _list_material(line):
    """A bullet, or a line indented far enough to sit under one."""
    return bool(line) and (bool(LIST_ITEM.match(line))
                           or line[:2].strip() == "" and bool(line.strip()))


def _nearest_text(lines, i, step):
    """The nearest line with text on it in one direction, or ''."""
    while 1 <= i <= len(lines):
        if lines[i - 1].strip():
            return lines[i - 1]
        i += step
    return ""


FOOTNOTE_DEF = re.compile(r"^\s{0,3}\[\^[^\]\s]+\]:")


def body_end(lines):
    """The last line the sections own, 1-based."""
    i = len(lines)
    while i > 0 and not lines[i - 1].strip():
        i -= 1
    end = i
    while i > 0 and (FOOTNOTE_DEF.match(lines[i - 1]) or not lines[i - 1].strip()):
        i -= 1
    return i if 0 < i < end else len(lines)


def dropped_here(old, new):
    """Facts in the original line the replacement lost. Never mind who did it."""
    after = facts(new)
    return sorted(v for k, vals in facts(old).items()
                  for v in vals - after.get(k, set()))


def reply_tokens(result):
    """Tokens this reply writes, per line, credited only along one run of them."""
    at = {}
    for e in result.get("edits", []):
        ln = e.get("line")
        if not isinstance(ln, int):
            continue
        at.setdefault(ln, set())
        for vals in facts(e.get("new", "")).values():
            at[ln].update(vals)
    out = {}
    for ln in at:
        run, k = set(), ln
        while k in at:
            run |= at[k]
            k -= 1
        k = ln + 1
        while k in at:
            run |= at[k]
            k += 1
        out[ln] = run
    return out


def ties(result, over=False):
    """Line sets one reply asks to stand or fall together, cap applied."""
    named = {}
    if result.get("specialist") in GROUPERS:
        for e in result.get("edits", ()):
            if (e.get("group") is not None and isinstance(e.get("line"), int)
                    and e.get("op", "replace") == "replace"):
                named.setdefault(str(e["group"]), set()).add(e["line"])
    if over:
        return {ln for v in named.values() if len(v) > MAX_GROUP_LINES
                for ln in v}
    return [v for v in named.values() if len(v) <= MAX_GROUP_LINES]


def edit_runs(result):
    """Maximal runs of consecutive lines one reply rewrites together."""
    mine = [e for e in result.get("edits", ())
            if isinstance(e.get("line"), int)
            and e.get("op", "replace") == "replace"]
    at = sorted(e["line"] for e in mine)
    runs, run = [], []
    for ln in at:
        if run and ln == run[-1] + 1:
            run.append(ln)
        else:
            if run:
                runs.append(set(run))
            run = [ln]
    if run:
        runs.append(set(run))
    base = list(runs)
    comps = [set().union(tied, *[r for r in base if r & tied])
             for tied in ties(result)]
    if comps:
        hit = set().union(*comps)
        runs = [r for r in base if not (r & hit)] + comps
    return runs


def run_facts(lines, result):
    """Tokens the original lines of each run already hold, per line of the run."""
    out = {}
    for run in edit_runs(result):
        have = set()
        for k in run:
            if 1 <= k <= len(lines):
                for vals in facts(lines[k - 1]).values():
                    have |= vals
        for k in run:
            out[k] = out.get(k, set()) | have
    return out


def written_down(v, text):
    """`v` already in `text` as a whole word, hyphens counted into the word."""
    if not v.strip():
        return False
    needle = r"\s+".join(re.escape(w) for w in v.split())
    return bool(re.search(rf"(?<![\w-]){needle}(?![\w-])",
                          HTML_COMMENT.sub(" ", text)))


def tokens_added(old, new, carried=(), index=None, document=""):
    """A protected token the replacement has and the document does not."""
    before = {v for vals in facts(old).values() for v in vals}
    bare = {re.match(r"[\d.,]+", v).group(0)
            for v in list(before) + list(carried)
            + (list(index) if index is not None else [])
            if re.match(r"[\d.,]+", v)}
    known = set(bare)
    for v in (list(before) + list(carried)
              + (list(index) if index is not None else [])):
        known |= set(re.findall(r"[\d.,]+", v))
    out = set()
    for kind, vals in facts(new).items():
        if kind == "fence_lang":
            continue
        for v in vals:
            if v in before or v in carried:
                continue
            if index is not None and v in index:
                continue
            if kind == "code" and written_down(v, document or old):
                continue
            if kind == "number" and v in bare:
                continue
            if kind == "ratio":
                parts = re.findall(r"[\d.,]+", v)
                if parts and all(p in known for p in parts):
                    continue
            out.add(v)
    return ", ".join(sorted(out))


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def wrap_runs(lines):
    """1-based line -> (first, last) for each sentence that wraps, exclusively."""
    text = "\n".join(lines)
    prose, _, _, _ = mask(text)
    spanned = with_spans(prose, text)
    covers, runs = {}, {}
    for sid, (a, b, _s) in enumerate(
            sentence_spans(list(enumerate(spanned)))):
        runs[sid] = (a + 1, b + 1)
        for k in range(a + 1, b + 2):
            covers.setdefault(k, set()).add(sid)
    out = {}
    for sid, (a, b) in runs.items():
        if b > a and all(covers[k] == {sid} for k in range(a, b + 1)):
            for k in range(a, b + 1):
                out[k] = (a, b)
    return out


def widen_wraps(lines, results, editable, runs):
    """Grow a one-line edit to the whole sentence it only half covers."""
    spoken = {e["line"] for r in results for e in (r.get("edits") or [])
              if isinstance(e.get("line"), int)}
    for r in results:
        edits = r.get("edits") or []
        mine = {e["line"] for e in edits if isinstance(e.get("line"), int)}
        add = []
        for e in edits:
            ln, op = e.get("line"), e.get("op", "replace")
            if op != "replace" or ln not in runs:
                continue
            first, last = runs[ln]
            rest = [k for k in range(first, last + 1) if k != ln]
            if len(rest) != 1 or rest[0] in spoken:
                continue
            if any(k not in editable for k in rest):
                continue
            new = (e.get("new") or "").strip()
            if new and (ln != first or not ends_sentence(new)):
                continue
            add += [{"line": k, "op": "replace", "new": "",
                     "old": lines[k - 1]} for k in rest]
            mine.update(rest)
        if add:
            r["edits"] = edits + add
    return results


def _diff_span(old, new):
    """(start, end, replacement) — the middle where `old` and `new` differ."""
    head = 0
    while head < min(len(old), len(new)) and old[head] == new[head]:
        head += 1
    tail = 0
    while (tail < min(len(old), len(new)) - head
           and old[-1 - tail] == new[-1 - tail]):
        tail += 1
    return head, len(old) - tail, new[head:len(new) - tail]


def reoffer(old, new, now):
    """The loser's change re-aimed at the winner's text, or ""."""
    if not old or not new or old == now:
        return ""
    if len(list(_split(now.strip()))) < 2:
        return ""
    l_from, l_to, becomes = _diff_span(old, new)
    w_from, w_to, _ = _diff_span(old, now)
    if l_from < w_to and w_from < l_to:
        return ""
    was = old[l_from:l_to]
    if len(was) < 3 or now.count(was) != 1:
        return ""
    return now.replace(was, becomes)


def sentences_lost(lines, result):
    """A sentence the reply's collapse drops, per line of the run it covers."""
    if result.get("specialist") in DELETERS + MOVERS:
        return {}
    at = {e["line"]: e.get("new", "") for e in result.get("edits", [])
          if isinstance(e.get("line"), int) and 1 <= e["line"] <= len(lines)
          and e.get("op", "replace") == "replace"}
    out = {}
    for ln in sorted(at):
        if ln - 1 in at:
            continue
        run = [ln]
        while run[-1] + 1 in at:
            run.append(run[-1] + 1)
        if len(run) < 2:
            continue
        after = " ".join(at[k] for k in run).lower()
        for part in _SENTENCE_SPLIT.split(
                " ".join(lines[k - 1] for k in run).strip()):
            if not _trim(part).endswith((".", "!", "?")):
                continue
            keys = [w for w in (_word(x) for x in part.split())
                    if len(w) >= 4 and not _DANGLES.search(w)]
            if keys and not any(w in after for w in keys):
                out.update({k: part.strip() for k in run})
                break
    return out


def rules_eaten(lines, result, prose, tables):
    """Rules a reply drops, per line of the run that drops them."""
    at = {e["line"]: e.get("new", "") for e in result.get("edits", [])
          if isinstance(e.get("line"), int) and 1 <= e["line"] <= len(lines)
          and e.get("op", "replace") == "replace"
          and e.get("old", "").strip() == lines[e["line"] - 1].strip()}
    if not at:
        return {}
    old = with_table_text(prose, tables)
    new = [at.get(i, t) for i, t in enumerate(old, 1)]
    _rows = [ln for ln, _c in tables]
    gone, _w, _t, _r = claims_lost(old, new, untouched_lines(old, new),
                                   o_rows=_rows, n_rows=_rows)
    ends = {a: b for a, b, _s in sentence_spans(list(enumerate(old, 1)), _rows)}
    out = {}
    for ln, s in gone:
        if label_not_rule(s):
            continue
        said = unmask.as_written(lines, old, ln, s)
        out.update({j: said
                    for j in blame.carriers(ln, ends.get(ln, ln), at)})
    return out


def tokens_dropped(who, old, new, index=None, ln=None, kept=(), excused=None):
    """The dropped facts that leave the document. '' when none."""
    if who in DELETERS:
        return ""
    gone, spared = [], []
    for v in dropped_here(old, new):
        if v in kept:
            continue
        at = (tuple(sorted(index.get(v, set()) - {ln}))
              if index is not None else ())
        if at:
            spared.append((v, at))
        else:
            gone.append(link_target(old, v) or v)
    if excused is not None:
        excused.extend(spared)
    return ", ".join(gone[:4]) + (f" and {len(gone) - 4} more" if len(gone) > 4 else "")


def quotes_dropped(old, new, kept=""):
    """The quotations an edit takes out of the document. '' when none."""
    _new = " ".join(new.split())
    _kept = " ".join(kept.split())
    gone = []
    for _ln, span in quoted_claims([old]):
        flat = " ".join(span.split())
        if flat in _new or (_kept and flat in _kept):
            continue
        if flat not in gone:
            gone.append(flat)
    return ", ".join(gone[:2]) + (f" and {len(gone) - 2} more"
                                  if len(gone) > 2 else "")


def echoed_template(s):
    """True when the model sent the prompt's own placeholder back."""
    return bool(re.fullmatch(r"\s*<[^<>]+>\s*", s or ""))


def link_target(old, tok):
    """`the link target #…` when the token lives only inside a link, else ''."""
    for m in re.finditer(r"\]\(([^)\s]+)", old):
        target = m.group(1)
        if tok in target and tok not in old.replace(target, ""):
            return f"the link target {target}"
    return ""


def fence_lines(lines):
    """1-based lines that are inside a fenced block, the fences themselves too."""
    out, fence = set(), None
    for i, ln in enumerate(lines, 1):
        tok, bare = fence_delim(ln)
        if tok:
            if fence is None:
                fence, out = tok, out | {i}
                continue
            if fence_closes(tok, fence) and bare:
                fence = None
            out.add(i)
            continue
        if fence is not None:
            out.add(i)
    return out


def open_ended(line):
    """True when the line is prose that does not finish its sentence."""
    if line.rstrip("\n").endswith("  ") or line.rstrip().endswith("<br>"):
        return False
    s = _trim(line)
    if not s or s.startswith(("#", "|", ">", "```", "~~~")):
        return False
    return not s.endswith((".", "!", "?"))


def _trim(line):
    return line.strip().rstrip("*_`)\"']”’")


def _word(w):
    """A token with its edge punctuation off, for comparing one to another."""
    return re.sub(r"^\W+|\W+$", "", w.lower())


ARTICLE = {"the", "a", "an", "this", "that", "these", "those", "its", "their"}


def ends_sentence(s):
    """True when the line finishes what it was saying."""
    bare = re.sub(r"\s*\([^()]*\)\s*$", "", s)
    return (_trim(s).endswith((".", "!", "?", ":"))
            or (bare != s and _trim(bare).endswith((".", "!", "?", ":"))))


_DANGLES = re.compile(
    r"\b(?:a|an|the|and|or|but|of|in|on|at|to|for|with|from|by|into|over|"
    r"under|than|that|which|who|when|while|if|as|is|are|was|were|be|been|"
    r"has|have|had|will|would|can|could|not|no|its|their|this|these|those)$",
    re.I)

_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")

_TAIL = re.compile(r"^[a-z`\"'(\[]")


def is_tail(line, after=""):
    """True when the line reads as the back half of a wrapped sentence."""
    s = line.strip()
    if not s or s.startswith(("- ", "* ", "+ ", "|", ">", "#", "```", "~~~")):
        return False
    return bool(_TAIL.match(s)) or bool(_DANGLES.search(_trim(after)))


def dangling(lines, ln, new, edited):
    """The line a reword would strand, or 0. Both halves of a wrap can strand."""
    prev, nxt = ln - 1, ln + 1
    if (nxt <= len(lines) and nxt not in edited
            and open_ended(lines[ln - 1]) and not open_ended(new)
            and is_tail(lines[nxt - 1], lines[ln - 1])):
        return nxt
    if (prev >= 1 and prev not in edited
            and open_ended(lines[prev - 1])
            and is_tail(lines[ln - 1], lines[prev - 1])
            and not is_tail(new)):
        return prev
    return 0


def slugify(title):
    """The anchor a Markdown heading answers to."""
    return re.sub(r"\s+", "-",
                  re.sub(r"[^\w\s-]", "", title.strip().lower()))


def broken_anchors(text):
    """In-document link targets with no heading to land on."""
    slugs = {slugify(m.group(1))
             for m in re.finditer(r"^ {0,3}#{1,6}\s+(.*?)\s*#*$", text, re.M)}
    links = {m.group(1).lower() for m in re.finditer(r"]\(#([^)\s]+)\)", text)}
    return links - slugs


INSERT_BLOCKING = frozenset({
    "frame", "hedge", "purpose hedge", "wrapper", "agreement move", "echo",
    "empty framing",
    "planning language", "parked problem", "vague action", "activity report",
    "process leak", "editor note", "worklog", "draft diff",
    "changelog narration", "corporate header", "asks reader to verify",
    "em-dash pressure", "defers its own point",
})

REPORTING_SHAPES = frozenset({
    "parked problem", "unexplained reference", "bare internal id",
    "asks reader to verify", "number without its noun",
})


def reporting_text(marker, said, flat):
    """True when `flat` already says this and `said` is repeating it."""
    if not marker or marker.lower() not in flat:
        return False
    if any(ch.isdigit() for ch in marker):
        return True
    at = said.lower().find(marker.lower())
    if at < 0:
        return False
    about = [w for w in (_word(x)
                         for x in said[:at + len(marker)].split()[-5:])
             if len(w) >= 4 and w not in marker.lower()]
    return not about or any(w in flat for w in about)


def shapes_in(text):
    """Every shape name in text. Empty set if it cannot be parsed."""
    try:
        p, h, t, q = mask(text)
        out = {c for _, c, _ in find_shapes(p, t, h, q)}
        if em_dash_pressure(p):
            out.add("em-dash pressure")
        return out
    except Exception:
        return set()


def added_shapes(text, quoting=""):
    """Shape names in text somebody is about to insert."""
    try:
        p, h, t, q = mask(text)
        flat = " ".join(quoting.lower().split())
        sents = [s for _a, _b, s in sentence_spans(list(enumerate(p)))]

        def reporting(m):
            said = next((s for s in sents if m and m.lower() in s.lower()), "")
            return reporting_text(m, said, flat)

        hits = {c for _, c, m in find_shapes(p, t, h, q)
                if not (c in REPORTING_SHAPES and reporting(m))}
    except Exception:
        return ["text this tool could not parse"]
    if em_dash_pressure(p):
        hits.add("em-dash pressure")
    out = sorted(hits & INSERT_BLOCKING)
    body = text.split("\n")
    while body and not body[0].strip():
        body.pop(0)
    if any(re.match(r"\s{0,3}#{1,6}\s", l) for l in body[1:]):
        out.append("a heading below its first line")
    return out


def heading_payload(old, new, sent, body=()):
    """The instruction a heading rename dropped and nobody kept, or None."""
    tail = re.split(r"\s+[—–-]\s+|:\s+",
                    re.sub(r"^\s*#+\s*", "", old).strip(), maxsplit=1)
    if len(tail) < 2:
        return None
    tail = tail[1].strip()
    words = [w for w in (_word(x) for x in tail.split()) if len(w) >= 4]
    if len(words) < 3:
        return None
    if not (tail.endswith("?") or _word(tail.split()[0]) in IMPERATIVE_OPENERS):
        return None
    kept = " ".join([str(e.get("new", "")) for e in sent]
                    + [str(b) for b in body]).lower()
    if sum(1 for w in words if w in kept) >= 0.7 * len(words):
        return None
    if sum(1 for w in words
           if w in re.sub(r"^\s*#+\s*", "", new).lower()) >= 0.7 * len(words):
        return None
    return tail


IMPERATIVE_OPENERS = frozenset("""
read start run check use do not never always pick choose open follow copy
skip stop write send ask keep leave fix add remove call go see try
""".split())


_CARRIES_POINT = re.compile(
    r"\b(?:because|so that|the reason|otherwise|different|differs|cheaper|"
    r"faster|slower|safer|costlier|harder|easier|worse|better|instead of|"
    r"rather than|not the same)\b", re.I)


_RANK_ONLY = re.compile(r"(?<![\w-])(?<!not )only\s+\w", re.I)
_RANK_CONSTRAIN = re.compile(
    r"\b(?:must|never|always|do not|don'?t|cannot|can'?t|required|"
    r"forbidden|unless|except|otherwise|avoid|ensure|shall|prohibited|"
    r"no longer|not supported|verify|check that)\b", re.I)
_RANK_DEFINE = re.compile(
    r"\b(?:is defined as|means that|means |refers to|is any |is a |are the |"
    r"consists of|is the )", re.I)
_RANK_HOWTO = re.compile(
    r"\b(?:run |install|set |configure|add |create |export |enable|disable|"
    r"requires|prerequisite|before you|first )", re.I)
_RANK_SOCIAL = re.compile(
    r"(?:star(?:ring)?\s+(?:the|this|our|it)|"
    r"(?:support|share|sponsor|back)\s+(?:the|this|our)\s+"
    r"(?:project|repo|work|tool)|buy me a|thank(?:s| you)\b|"
    r"if (?:this|it) (?:helps|saves|is useful)|feel free to|we welcome|"
    r"contributions are|consider (?:starring|supporting|sponsoring)|"
    r"give (?:it|us) a star|find it useful)", re.I)
_RANK_SOCIAL_HEAD = re.compile(
    r"\b(?:support the|thanks|acknowledg|sponsor|star|table of contents)\b",
    re.I)
_RANK_HARDFACT = re.compile(
    r"(?:https?://|[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+|`[^`]+`|"
    r"\b\d+(?:\.\d+)+\b|\b\d+%|\b[A-Z][A-Z0-9_]{3,}\b)")


_RANK_ORDER = re.compile(
    r"\b(?:prior to|beforehand|precede[sd]?|preceding|subsequent(?:ly)?|"
    r"before (?:any|anything|the|this|that|these|those|all|you|it|we|doing|"
    r"running|starting|touching|beginning|changing|editing)|"
    r"in (?:this|the following|that) order|"
    r"first\b[^.]{0,60}\bthen\b)", re.I)


def finding_rank(text, heading=""):
    """How much a lost line is worth reading. Higher is read sooner."""
    s, why = 0, []
    if _RANK_CONSTRAIN.search(text) or _RANK_ONLY.search(text):
        s += 5
        why.append("constrains")
    if _RANK_ORDER.search(text):
        s += 5
        why.append("orders")
    if _RANK_DEFINE.search(text):
        s += 4
        why.append("defines")
    if _RANK_HOWTO.search(text):
        s += 2
        why.append("how-to")
    if _RANK_HARDFACT.search(text):
        s += 2
        why.append("names something")
    if _RANK_SOCIAL.search(text):
        s -= 8
        why.append("asks a favour")
    if heading and _RANK_SOCIAL_HEAD.search(heading):
        s -= 4
        why.append("under a thanks heading")
    return s, why


def _rank_tag(s):
    """Why a finding sits where it does, for the reader who wonders."""
    _, why = finding_rank(s)
    return f"  [{', '.join(why)}]" if why else ""


_HARD_WORD = re.compile(r"[0-9]|[-./_]")


def _word_forms(w):
    """The spellings that count as the same word."""
    w = re.sub(r"(?:'s|\u2019s)$", "", w)
    out = {w}
    if w.endswith("s") and not w.endswith(("ss", "is", "us")):
        out.add(w[:-1])
    else:
        out.add(w + "s")
    return out


def words_not_found(sentence, edited_lower, original=""):
    """Of a sentence's content words, which are nowhere in the edited file."""
    named, ordinary = [], []
    for w in sorted(claim_words(sentence)):
        if any(re.search(r"(?<![0-9a-z_-])" + re.escape(f) + r"(?![0-9a-z_-])",
                         edited_lower) for f in _word_forms(w)):
            continue
        hard = bool(_HARD_WORD.search(w)) or (
            original and any(
                any(c.isupper() for c in m.group(0)[1:]) for m in
                re.finditer(r"(?<![\w`.])" + re.escape(w) + r"(?![\w])",
                            original, re.I)))
        (named if hard else ordinary).append(w)
    return named, ordinary


def label_not_rule(text):
    """Why a line the rule check caught is a label and not a rule, or None."""
    s = text.strip()
    if re.search(r"\[(?:required|optional|recommended|deprecated|beta|"
                 r"experimental|default|wip|todo)\]\s*$", s, re.I):
        return "a capability label"
    if s.startswith(":"):
        return "half of a definition-list row"
    if re.match(r"^[✅❌✔✖⚠⭐]", s):
        return "a checklist tick"
    if re.match(r"^(?:[-*]\s*)?\[[^\]]{3,}\]\([^)]+\)", s):
        return "a link line"
    return None


def not_a_claim(text):
    """Why this line was never a fact, or None."""
    s = text.strip()
    if re.match(r"^\|?\s*[-: ]+\|[-:| ]*$", s):
        return "a table rule line"
    if re.match(r"^\[[^\]]+\]\(#", s):
        return "a link to this same document"
    if not re.search(r"[a-z]", s):
        return "no words in it"
    if len(s.split()) <= 3:
        return "too short to be a claim"
    if s.count("|") >= 2:
        cells = [c.strip() for c in s.strip("|").split("|") if c.strip()]
        if cells and all(len(c.split()) <= 2 for c in cells):
            return "a table row of one-word labels"
    return None


def joined_sentences(who, old, new):
    """The two sentences a reword folded into one, or None."""
    if who != "prose":
        return None

    def keys(s):
        return {w for w in (_word(x) for x in s.split())
                if len(w) >= 4 and not _DANGLES.search(w)}

    was = [(s, keys(s)) for s in _split(old)]
    was = [(s, k) for s, k in was if len(k) >= 3]
    kept_same = {s.strip() for s in _split(old)} & {s.strip()
                                                    for s in _split(new)}
    now = [keys(s) for s in _split(new) if s.strip() not in kept_same]
    if len(was) < 2:
        return None
    for i, (a, ka) in enumerate(was):
        for b, kb in was[i + 1:]:
            da, db = ka - kb, kb - ka
            if not da or not db:
                continue
            for ks in now:
                if (len(da & ks) >= 0.7 * len(da)
                        and len(db & ks) >= 0.7 * len(db)):
                    return (a, b)
    return None


def parity_broken(old, new):
    """The delimiter the replacement leaves unclosed, or ''."""
    for name, a, b in (("backtick", "`", "`"), ("bracket", "[", "]"),
                       ("parenthesis", "(", ")"), ("quote", '"', '"')):
        was = (old.count(a) - old.count(b)) if a != b else old.count(a) % 2
        now = (new.count(a) - new.count(b)) if a != b else new.count(a) % 2
        if was == 0 and now != 0:
            return name
    return ""


_MOVE_NUMBERED_HEAD = re.compile(r"^#{1,6}\s*(?:\*\*)?(\d{1,5})(?:\*\*)?\s*[.):]")
_MOVE_ITEM_REF = re.compile(r"\b(?:item|row)\s+#?(\d{1,5})\b", re.I)


def merge(lines, results, editable, quoted=(), headings=(), summary_line=0,
          _round=1, chat=False, margin_from=None, excused_drops=None,
          held=(), reorder=True):
    """Apply every specialist's edits to one copy of the file."""
    out = list(lines)
    claimed, inserts, applied, refused = {}, {}, [], []
    claimed_by = {}
    moves, taken = [], set()
    fenced = fence_lines(lines)
    level = {h[0] + 1: h[1] for h in headings}
    marked = keep_lines(lines)
    frozen = protected.lines(headings, len(lines))
    dated = protected.dated_status_lines(headings)
    same_text = {}

    head_text = {h[2].strip().lower() for h in headings if h[2].strip()}
    for _r in results:
        for _e in _r.get("edits", ()):
            _ln = _e.get("line")
            if _e.get("op", "replace") != "replace" \
                    or not isinstance(_ln, int) or not 1 <= _ln <= len(lines):
                continue
            _was = re.match(r"^\s*#+\s+(.*)", lines[_ln - 1])
            _now = re.match(r"^\s*#+\s+(.*)",
                            str(_e.get("new", "")).strip().split("\n")[0])
            if _was and _now:
                if (_r.get("specialist") != "summary"
                        and _ln != summary_line
                        and SUMMARY_HEADING.match(_now.group(1).strip())
                        and not SUMMARY_HEADING.match(_was.group(1).strip())):
                    continue
                head_text.discard(_was.group(1).strip().lower())
                head_text.add(_now.group(1).strip().lower())
    summary_named = {t for t in head_text if SUMMARY_HEADING.match(t)}
    dropped_by_noise = []
    _pending_excused = {}
    if excused_drops is None:
        excused_drops = []
    index = token_lines(lines)
    whole = "\n".join(lines)
    def survives_order_free(who, e, lo, hi, kept=(), quote_kept=""):
        """True when nothing that can be decided up front refuses this edit."""
        ln = e.get("line")
        if not isinstance(ln, int) or not 1 <= ln <= len(lines):
            return False
        new = e.get("new", "")
        old = lines[ln - 1]
        return (lo <= ln <= hi
                and ln in editable and ln not in fenced
                and (ln not in quoted or who in DELETERS)
                and e.get("old", "").strip() == old.strip()
                and not (ln == summary_line and not SUMMARY_HEADING.match(
                    re.sub(r"^\s*#+\s*", "", new).strip()))
                and not tokens_dropped(who, old, new, index, ln, kept)
                and not quotes_dropped(old, new, quote_kept)
                and not parity_broken(old, new)
                and not [s for s in added_shapes(new)
                         if s not in added_shapes(old)]
                and not (new.strip() and _trim(old).endswith((".", "!", "?"))
                         and not ends_sentence(new)
                         and not new.lstrip().startswith(
                             ("#", "|", ">", "-", "*"))))

    results = widen_wraps(
        lines, results,
        set(editable) - set(marked) - set(quoted) - set(fenced),
        wrap_runs(lines))

    kept = {id(r): reply_tokens(r) for r in results}
    quote_kept = {id(r): " ".join(" ".join(str(e.get("new", "")).split())
                                  for e in r.get("edits", ())
                                  if isinstance(e, dict))
                  for r in results}
    origin = {id(r): run_facts(lines, r) for r in results}
    ceded = defaultdict(set)
    lost = {id(r): sentences_lost(lines, r) for r in results}
    _p, _h, _t, _q = mask("\n".join(lines))
    eaten = {id(r): rules_eaten(lines, r, _p, _t) for r in results}

    def ok_free(r, e):
        return (not lost[id(r)].get(e.get("line"))
                and not eaten[id(r)].get(e.get("line"))
                and survives_order_free(
                    r["specialist"], e, r.get("lo", 1),
                    r.get("hi") or len(lines),
                    kept[id(r)].get(e.get("line"), ()),
                    quote_kept[id(r)]))

    edited = {e["line"] for r in results for e in r.get("edits", [])
              if e.get("op", "replace") == "replace" and ok_free(r, e)}

    territory = {}
    if summary_line:
        sum_level = next((h[1] for h in headings if h[0] + 1 == summary_line), 2)
        stop = next((h[0] + 1 for h in headings
                     if h[0] + 1 > summary_line and h[1] <= sum_level),
                    len(lines) + 1)
        territory.update({k: "summary" for k in range(summary_line, stop)})
    for r in results:
        if r["specialist"] == "chat":
            for k in range(r.get("lo", 1), (r.get("hi") or len(lines)) + 1):
                territory.setdefault(k, "chat")
    cut = {e["line"] for r in results for e in r.get("edits", [])
           if e.get("op", "replace") == "replace" and isinstance(e.get("line"), int)
           and not e.get("new", "").strip()
           and territory.get(e["line"]) != r["specialist"]
           and ok_free(r, e)}
    owns = {e["line"] for r in results for e in r.get("edits", [])
            if isinstance(e.get("line"), int) and e["line"] not in cut
            and territory.get(e["line"]) == r["specialist"]
            and e.get("op", "replace") == "replace" and ok_free(r, e)}

    proposed = {}
    for r in results:
        for e in r.get("edits", []):
            ln = e.get("line")
            if (e.get("op", "replace") == "replace" and ln in edited
                    and ln not in proposed and ok_free(r, e)
                    and (ln not in owns
                         or territory.get(ln) == r["specialist"])):
                proposed[ln] = e.get("new", "")

    def beheaded(ln, new):
        """True when deleting this line leaves the one above unfinished."""
        if new.strip() or ln < 2 or not lines[ln - 2].strip():
            return False
        above = proposed[ln - 1] if ln - 1 in edited else lines[ln - 2]
        return open_ended(above) and is_tail(lines[ln - 1], above)

    while True:
        gone = {ln for ln in edited
                if dangling(lines, ln, proposed[ln], edited)
                or beheaded(ln, proposed[ln])}
        if not gone:
            break
        edited -= gone

    renamed = renamed_headings(headings, {ln: proposed[ln] for ln in edited})

    inbound = defaultdict(list)
    for i, raw in enumerate(lines, 1):
        for m in re.finditer(r"]\(#([^)\s]+)\)", raw):
            inbound[m.group(1).lower()].append(i)

    def orphans(ln, new, mine):
        """Lines whose link this rename would break, and the reply leaves."""
        was = next((h[2] for h in headings if h[0] + 1 == ln), None)
        if was is None:
            return []
        to = re.sub(r"^\s*#+\s*", "", new).strip()
        if slugify(to) == slugify(was):
            return []
        return [k for k in inbound.get(slugify(was), ()) if k not in mine]

    opens_already = summary_opens_after(
        lines, {k: proposed[k] for k in edited},
        {k: territory.get(k) for k in edited})

    def dead_pointers(who, new):
        if who != "summary":
            return []
        low = {r.casefold() for r in renamed}
        return sorted({heading_name(p)
                       for p in re.findall(r"\(([^()\n]{3,60})\)", new)
                       if heading_name(p).casefold() in low})

    owns = {ln: territory[ln] for ln in owns
            if ln in edited
            and not dead_pointers(territory[ln], proposed.get(ln, ""))}

    def separator(k):
        t = lines[k - 1].strip() if 1 <= k <= len(lines) else ""
        return is_separator(t)

    def table_broken(ln):
        """Why deleting this table row leaves a broken table, or ''."""
        if not lines[ln - 1].strip().startswith("|"):
            return ""
        if separator(ln + 1):
            return "it is the header row of a table"
        lo, hi = ln, ln
        while lo > 1 and lines[lo - 2].strip().startswith("|"):
            lo -= 1
        while hi < len(lines) and lines[hi].strip().startswith("|"):
            hi += 1
        if not [k for k in range(lo, hi + 1)
                if k != ln and not separator(k)
                and not (k in edited and not proposed[k].strip())]:
            return "it is the last row of a table whose separator stays"
        return ""

    sum_span = {k for k, v in territory.items() if v == "summary"}

    def guts_summary(ln):
        """Why this delete removes the summary instead of rewriting it, or ''."""
        if ln not in sum_span:
            return ""
        had = sum(len(lines[k - 1].split()) for k in sum_span)
        cut = sum(len(lines[k - 1].split()) for k in sum_span
                  if k in edited and not proposed[k].strip())
        if had and cut * 2 > had:
            return (f"this run deletes {cut} of the opening summary's {had} "
                    f"words — rewrite the summary, do not remove it")
        return ""

    def neighbour(k):
        """Line k as the finished file will have it, or '' off the ends."""
        if not 1 <= k <= len(lines):
            return ""
        return proposed[k] if k in edited else lines[k - 1]

    queue = [(r, e) for r in results for e in r.get("edits", [])
             if owns.get(e.get("line")) == r["specialist"]]
    queue += [(r, e) for r in results for e in r.get("edits", [])
              if owns.get(e.get("line")) != r["specialist"]]
    oversize = {id(r): ties(r, over=True) for r in results}
    for res, e in queue:
        who = res["specialist"]
        if e.get("line") in oversize[id(res)]:
            refused.append((e["line"], f"{who}: {e.get('why', '')}".strip(),
                            f"this edit is tied to more than "
                            f"{MAX_GROUP_LINES} lines under one `group` — "
                            f"send one tie per repeat"))
            continue
        lo, hi = res.get("lo", 1), res.get("hi") or len(lines)
        ln, op = e.get("line"), e.get("op", "replace")
        new = e.get("new", "")
        if type(ln) is int and 1 <= ln <= len(lines) and op == "replace":
            new = recapitalise(lines[ln - 1], new)
            lead = lines[ln - 1][:len(lines[ln - 1]) - len(lines[ln - 1].lstrip())]
            if new.strip() and not new.startswith(lead):
                new = lead + new.lstrip()
        _why = e.get("why", "")
        why = f"{who}: {'' if echoed_template(_why) else _why}" \
            .strip().rstrip(":")
        if type(ln) is not int or not 1 <= ln <= len(lines):
            refused.append((ln, why, "line is outside the file"))
            continue
        if not lo <= ln <= hi:
            refused.append((ln, why, f"outside its span ({lo}-{hi})"))
            continue
        if op not in ("replace", "insert", "move", "move-block",
                      "delete-section"):
            refused.append((ln, why, f"no such op: {op!r}"))
            continue
        _outline_op = ("delete-section" if who in SECTION_DELETERS else "move")
        if res.get("outline") and op != _outline_op:
            refused.append((ln, why, f"this job holds the outline, so it may "
                                     f"only send `{_outline_op}`"))
            continue
        if op in ("move", "move-block") and not reorder:
            refused.append((ln, why, "--no-reorder: this run leaves every "
                                     "section where it is"))
            continue
        if op in ("move", "move-block"):
            _end = body_end(lines)
            if op == "move":
                span = section_span(headings, _end, ln)
                bad = None if span else ("not a heading — a move takes a "
                                         "whole section")
            else:
                span, bad = block_span(lines, headings, ln, e.get("thru"),
                                       _end)
            top = headings[0][0] + 1 if headings else None
            bottom = body_end(lines) + 1
            what = "section" if op == "move" else "block"
            anchor = e.get("to") if op == "move" else e.get("into")
            field = "to" if op == "move" else "into"
            dest = (anchor + 1 if op != "move" and isinstance(anchor, int)
                    and anchor != bottom else anchor)
            _sec_nums = [int(m.group(1)) for i in range(span[0], span[1] + 1)
                        for m in [_MOVE_NUMBERED_HEAD.match(lines[i - 1])]
                        if m] if span else []
            _cited_nums = sorted({
                n for i, _txt in enumerate(lines, 1)
                if span and not span[0] <= i <= span[1]
                for m in _MOVE_ITEM_REF.finditer(_txt)
                for n in [int(m.group(1))] if n in _sec_nums
            }) if _sec_nums else []
            if who not in MOVERS:
                refused.append((ln, why, f"only structure may move a {what}"))
            elif span is None:
                refused.append((ln, why, bad))
            elif op == "move" and ln == top:
                refused.append((ln, why, "that is the title, it owns the "
                                         "whole file"))
            elif op == "move" and ln in dated:
                refused.append((ln, why, "that heading records a dated "
                                         "status and may not be moved"))
            elif not isinstance(anchor, int):
                refused.append((ln, why,
                                f"`{field}` takes a line number, not a name"))
            elif not 1 <= anchor <= bottom:
                refused.append((ln, why,
                                f"`{field}` is not a line in the file"))
            elif anchor == top:
                refused.append((ln, why, "that would land above the title"
                                if op == "move" else
                                "the title owns the whole file — give the line "
                                "of the heading this belongs under"))
            elif anchor != bottom and \
                    section_span(headings, body_end(lines), anchor) is None:
                refused.append((ln, why, f"line {anchor} is not a heading — "
                                f"give the line of the heading it goes "
                                f"{'before' if op == 'move' else 'into'}"))
            elif (span[0] <= dest and all(not lines[i - 1].strip()
                                          for i in range(span[1] + 1, dest))
                  if op == "move" else
                  dest <= span[0] and all(not lines[i - 1].strip()
                                          for i in range(dest, span[0]))):
                refused.append((ln, why, "it is already there"))
            elif op == "move" and level.get(anchor, 0) > level.get(ln, 0):
                refused.append((ln, why,
                                f"that would nest line {anchor} under it"))
            elif (summary_line and dest <= summary_line
                  and not span[0] <= summary_line <= span[1]):
                refused.append((ln, why, f"that would put the {what} above "
                                         f"the summary, and the summary opens "
                                         f"the document"))
            elif out[ln - 1] is None or (anchor <= len(lines)
                                         and out[anchor - 1] is None):
                refused.append((ln, why, f"a line this {what} move needs was "
                                         f"deleted earlier in this run"))
            elif taken & set(range(span[0], span[1] + 1)) or anchor in taken:
                refused.append((ln, why, "overlaps something already moved"))
            elif any(span[0] <= d <= span[1] for _, _, d in moves):
                refused.append((ln, why, "an earlier move targets inside it"))
            elif op == "move" and _cited_nums:
                refused.append((ln, why,
                                f"item {_cited_nums[0]} in this numbered "
                                f"section is referenced by number elsewhere "
                                f"in the document — moving the section "
                                f"would change reading order around that "
                                f"reference"))
            else:
                taken |= set(range(span[0], span[1] + 1))
                moves.append((span[0], span[1], dest))
                applied.append((ln, why, op, None))
            continue
        if op == "delete-section":
            _end = body_end(lines)
            span, _sched = section_schedules(headings, lines, ln, end=_end)
            top = headings[0][0] + 1 if headings else None
            inside = set(range(span[0], span[1] + 1)) if span else set()
            _rest = ("\n".join(s for j, s in enumerate(lines, 1)
                               if not span[0] <= j <= span[1])
                     if span else None)
            if who not in SECTION_DELETERS:
                refused.append((ln, why, f"only "
                                         f"{', '.join(SECTION_DELETERS)} may "
                                         f"delete a section"))
            elif span is None:
                refused.append((ln, why, "not a heading — a section delete "
                                         "takes a whole section, named by its "
                                         "heading"))
            elif ln == top:
                refused.append((ln, why, "that is the title, it owns the "
                                         "whole file"))
            elif summary_line and span[0] <= summary_line <= span[1]:
                refused.append((ln, why, "that section is the summary, and "
                                         "the summary opens the document"))
            elif not _sched:
                refused.append((ln, why, "its body schedules nothing: no "
                                         "unchecked box, no date, no owner, "
                                         "no estimate. Only the heading names "
                                         "a plan here, and a heading is not "
                                         "enough to delete a section"))
            elif _gone := claims_lost(
                    _old := with_table_text(_p, _t),
                    _new := ["" if span[0] <= i <= span[1] else s
                             for i, s in enumerate(_old, 1)],
                    untouched_lines(_old, _new),
                    o_rows=(_rows := [r for r, _c in _t]), n_rows=_rows)[0]:
                refused.append((ln, why, f"line {_gone[0][0]} in that section "
                                         f"states a rule nothing else in the "
                                         f"document keeps"))
            elif _qhit := next(
                    ((i, g) for i in range(span[0], span[1] + 1)
                     if (g := quotes_dropped(lines[i - 1], _rest))),
                    None):
                refused.append((ln, why, f"line {_qhit[0]} in that section "
                                         f"carries a quotation ({_qhit[1]}) "
                                         f"a section delete would drop — a "
                                         f"quotation is somebody else's "
                                         f"words, not the author's to cut, "
                                         f"and a section comes out whole or "
                                         f"not at all"))
            elif _held := sorted(inside & (marked | frozen | set(held) | dated)):
                refused.append((ln, why, f"line {_held[0]} in that section is "
                                         f"protected, and a section comes out "
                                         f"whole or not at all"))
            elif taken & inside:
                refused.append((ln, why, "overlaps something already moved"))
            elif any(span[0] <= d <= span[1] for _, _, d in moves
                     if d is not None):
                refused.append((ln, why, "an earlier move targets inside it"))
            else:
                taken |= inside
                moves.append((span[0], span[1], None))
                applied.append((ln, why, "delete-section", None))
                for k in inside:
                    claimed.setdefault(k, who)
                for k in inside:
                    for _vals in facts(lines[k - 1]).values():
                        for _v in _vals:
                            dropped_by_noise.append((k, _v))
            continue
        if op == "insert":
            if chat:
                refused.append((ln, why, "a chat message has one author and "
                                         "the tool is not it — reword a line "
                                         "or delete one, do not add text"))
                continue
            _top = new.strip().split("\n")[0].strip()
            if (who == "summary" and _top.startswith("#")
                    and SUMMARY_HEADING.match(
                        re.sub(r"^\s*#+\s*", "", _top))):
                if has_title(headings, lines):
                    gate = headings[0][0] + 2
                else:
                    gate = 1
                if 1 <= gate <= len(lines) and re.match(r"^\s*(=+|-{2,})\s*$",
                                                        lines[gate - 1]):
                    gate += 1
                if lines and lines[0].strip() == "---":
                    end = next((i for i in range(1, len(lines))
                                if lines[i].strip() in ("---", "...")), 0)
                    gate = max(gate, end + 2)
                if ln > gate:
                    ln = gate
                want = section_level(headings, lines)
                if want and len(_top) - len(_top.lstrip("#")) > want:
                    _txt = re.sub(r"\s+#+$", "", _top.lstrip("# ").strip())
                    _nl = new.split("\n")
                    _at = next(i for i, l in enumerate(_nl) if l.strip())
                    _nl[_at] = "#" * want + " " + _txt
                    new = "\n".join(_nl)
            if ln in fenced:
                refused.append((ln, why, "insert lands inside a code fence"))
                continue
            if re.match(r"#{1,6}\s", lines[ln - 1]):
                inside = False
            elif lines[ln - 1].strip():
                inside = ln not in editable
            else:
                above = next((k for k in range(ln - 1, 0, -1)
                              if lines[k - 1].strip()), 0)
                below = next((k for k in range(ln + 1, len(lines) + 1)
                              if lines[k - 1].strip()), 0)

                def blocky(k):
                    if not k or k in editable:
                        return False
                    s = lines[k - 1]
                    return (s.startswith(("    ", "\t"))
                            or s.strip().startswith("|")
                            or bool(TREE_CHARS & set(s)))

                inside = blocky(above) and blocky(below)
            if inside:
                refused.append((ln, why, "insert lands inside a code "
                                         "block, table or diagram"))
                continue
            if ln in inserts:
                refused.append((ln, why,
                                f"{inserts[ln][0]} already inserts here"))
                continue
            if (opens_already and who == "summary" and SUMMARY_HEADING.match(
                    re.sub(r"^\s*#+\s*", "",
                           new.strip().split("\n")[0]).strip())):
                refused.append((ln, why, f"line {opens_already} already opens "
                                         f"the file with a summary — rewrite "
                                         f"that one, do not add a second"))
                continue
            dead = dead_pointers(who, new)
            if dead:
                refused.append((ln, why, "it points at " + ", ".join(dead)
                                + ", renamed by another specialist in this "
                                  "run"))
                continue
            bad = added_shapes(new, "\n".join(lines))
            if bad:
                refused.append((ln, why, "the text you are inserting has "
                                         + ", ".join(bad)))
                continue
            unpaired = parity_broken("", new)
            if unpaired:
                refused.append((ln, why,
                                f"the insert leaves a {unpaired} unclosed"))
                continue
            made = tail_added(neighbour(ln - 1), "", new, neighbour(ln))
            if made:
                refused.append((ln, why, f"the insert would leave "
                                         f"'{unmask.quote(made)}' on both "
                                         f"sides of a line break"))
                continue
            new_head = re.match(r"^\s*#+\s+(.*)", new.strip().split("\n")[0])
            if new_head and new_head.group(1).strip().lower() in head_text:
                refused.append((ln, why, f"the file already has a heading "
                                         f"'{new_head.group(1).strip()}' — two "
                                         f"of them share one link target"))
                continue
            if who == "summary" and summary_named and SUMMARY_HEADING.match(
                    re.sub(r"^\s*#+\s*", "",
                           new.strip().split("\n")[0]).strip()):
                refused.append((ln, why, f"this run already names a section "
                                         f"'{sorted(summary_named)[0]}' — two "
                                         f"summary sections leave the reader "
                                         f"two places to start"))
                continue
            if who == "summary" and new_head and SUMMARY_HEADING.match(
                    new_head.group(1).strip()):
                _top_line = new.strip().split("\n")[0].strip()
                _lvl = len(_top_line) - len(_top_line.lstrip("#"))
                _want_lvl = section_level(headings, lines)
                if _want_lvl and _lvl < _want_lvl:
                    refused.append((ln, why, f"a level-{_lvl} summary "
                                             f"heading here is shallower "
                                             f"than this document's own "
                                             f"section level ({_want_lvl}) "
                                             f"— it has no heading at or "
                                             f"above its own level before "
                                             f"the end of the file, so it "
                                             f"would re-parent every "
                                             f"section under it. Write it "
                                             f"at level {_want_lvl}, the "
                                             f"level the document's "
                                             f"sections already use"))
                    continue
                _cap = summary_cap(_summary_words("\n".join(lines)))
                _words = _summary_words(new)
                if _words > _cap:
                    refused.append((ln, why, f"the summary is {_words} "
                                             f"words, over the {_cap}-word "
                                             f"cap for this document — cut "
                                             f"it down instead of inserting "
                                             f"it"))
                    continue
            if new_head:
                head_text.add(new_head.group(1).strip().lower())
            if ln >= 2 and lines[ln - 2].strip() and not new.startswith("\n"):
                new = "\n" + new
            if ln - 1 < len(lines) and lines[ln - 1].strip() \
                    and not new.endswith("\n"):
                new += "\n"
            inserts[ln] = (who, new)
            applied.append((ln, why, "insert", None))
            continue
        if ln not in editable:
            if ln in marked:
                own = lines[ln - 1]
                reason = ("protected by CRITICAL INFO FOR AGENTS"
                          if CRITICAL_MARK.search(own) else
                          "protected by kv:keep" if KEEP_MARK.search(own) else
                          "protected by the CRITICAL INFO FOR AGENTS line above")
            elif ln in frozen:
                reason = "line is inside a section marked do-not-edit"
            elif ln in held:
                reason = "line is frozen by .killverbosity.json"
            elif ln in dated:
                reason = "that heading records a dated status and is frozen"
            elif lines[ln - 1].strip().startswith("|"):
                reason = "line is a table separator row"
            else:
                reason = "line is a code fence, diagram or blank"
            refused.append((ln, why, reason))
            continue
        if ln in quoted and who not in DELETERS:
            refused.append((ln, why, "line is inside a quotation"))
            continue
        if ln in claimed:
            ceded[id(res)].add(ln)
            refused.append((ln, why, f"already changed by {claimed[ln]}"))
            continue
        if ln in level and who not in MOVERS and not new.strip():
            refused.append((ln, why, "that is a heading — empty the section "
                                     "if it has nothing to say, and leave the "
                                     "heading for structure to remove"))
            continue
        if ln in level and who not in MOVERS and new.strip() and not \
                next(l for l in new.splitlines() if l.strip()).lstrip() \
                .startswith("#"):
            refused.append((ln, why, "that drops the heading marker, so the "
                                     "section merges into the one above — "
                                     "reword it and keep the leading #"))
            continue
        if ln == summary_line and not SUMMARY_HEADING.match(
                re.sub(r"^\s*#+\s*", "", new).strip()):
            refused.append((ln, why, "that is the summary heading — the "
                                     "tool finds the summary by its name"))
            continue
        if (ln in level and ln != summary_line and who != "summary"
                and SUMMARY_HEADING.match(re.sub(r"^\s*#+\s*", "", new).strip())
                and not SUMMARY_HEADING.match(
                    re.sub(r"^\s*#+\s*", "", lines[ln - 1]).strip())):
            refused.append((ln, why, "that renames a section into the summary "
                                     "heading the detector looks for, and only "
                                     "`summary` reads the prose under it"))
            continue
        if ln in level:
            _span = section_span(headings, body_end(lines), ln)
            _touched = {x.get("line") for x in res.get("edits", ())}
            payload = heading_payload(
                lines[ln - 1], new, res.get("edits", ()),
                [lines[k - 1] for k in range(_span[0] + 1, _span[1] + 1)
                 if k not in _touched] if _span else ())
            if payload:
                refused.append((ln, why, f"the heading tells the reader to "
                                         f"'{unmask.quote(payload, 50)}' and "
                                         f"the new one does not. Put it under "
                                         f"the heading in this same reply, or "
                                         f"keep it"))
                continue
        left = orphans(ln, new, {x.get("line") for x in res.get("edits", ())})
        if left:
            refused.append((ln, why, f"renaming this heading breaks the link "
                                     f"on line{'s' if len(left) > 1 else ''} "
                                     f"{', '.join(str(k) for k in left[:6])} — "
                                     f"rewrite the link in the same reply, or "
                                     f"leave the heading"))
            continue
        if e.get("old", "").strip() != lines[ln - 1].strip():
            refused.append((ln, why, "`old` does not match the file"))
            continue
        bad = sorted(set(added_shapes(new)) - set(added_shapes(lines[ln - 1]))
                     | (shapes_in(new) - shapes_in(lines[ln - 1])))
        if bad:
            refused.append((ln, why, "the replacement text has "
                                     + ", ".join(bad)))
            continue
        _exc = []
        dropped = tokens_dropped(who, lines[ln - 1], new, index, ln,
                                 kept[id(res)].get(ln, ()), excused=_exc)
        _pending_excused[ln] = _exc
        if dropped:
            refused.append((ln, why, f"the reword drops {dropped}"))
            continue
        cut_quote = ("" if parity_broken(lines[ln - 1], new) else
                     quotes_dropped(lines[ln - 1], new, quote_kept[id(res)]))
        if cut_quote:
            refused.append((ln, why, f"this is a "
                                     f"{'delete' if not new.strip() else 'reword'}"
                                     f" by {who} and {cut_quote} goes with it."
                                     f" A quotation is somebody else's words, "
                                     f"not the author's to cut — keep the "
                                     f"sentence, or shorten around the quote"))
            continue
        invented = tokens_added(lines[ln - 1], new,
                                origin[id(res)].get(ln, ()), index, whole)
        if invented:
            refused.append((ln, why, f"the reword adds {invented}, which is "
                                     f"nowhere in this document — take a fact "
                                     f"from the document, not from outside it"))
            continue
        _mean = meaning_swaps(lines[ln - 1], new)
        if _mean:
            refused.append((ln, why, "; ".join(
                f"`{a}` -> `{b}` swaps {what}" for a, b, what in _mean)
                + ". That changes what the sentence claims, not how long it "
                  "is. Shorten around the word or leave it."))
            continue
        _formal = formal_swaps(lines[ln - 1], new)
        if _formal:
            refused.append((ln, why, "; ".join(
                f"`{a}` -> `{b}`" for a, b in _formal)
                + (" replaces a plain word with a longer one that says the "
                   "same thing. Cut words instead, or leave it.")))
            continue
        merged = joined_sentences(who, lines[ln - 1], new)
        if merged:
            refused.append((ln, why, f"that folds two sentences into one and "
                                     f"keeps both — '{unmask.quote(merged[0])}'"
                                     f" and '{unmask.quote(merged[1])}'. "
                                     f"Shorten them or "
                                     f"drop one; joining makes the line longer "
                                     f"to read, not shorter"))
            continue
        if (new.strip() and _trim(lines[ln - 1]).endswith((".", "!", "?"))
                and not ends_sentence(new)
                and not new.lstrip().startswith(("#", "|", ">", "-", "*"))):
            refused.append((ln, why, "the original line ended a sentence "
                                     "and the replacement does not"))
            continue
        if beheaded(ln, new):
            refused.append((ln, why, f"line {ln - 1} does not finish its "
                                     f"sentence and this line held the rest"))
            continue
        if not new.strip():
            broke = table_broken(ln) or guts_summary(ln)
            if broke:
                refused.append((ln, why, broke))
                continue
        gone = lost[id(res)].get(ln)
        if gone:
            refused.append((ln, why, f"the lines you rewrite together drop "
                                     f"'{unmask.quote(gone)}' — keep the "
                                     f"sentences you are not changing"))
            continue
        ate = eaten[id(res)].get(ln)
        if ate:
            refused.append((ln, why, f"'{unmask.quote(ate)}' states a rule, "
                                     f"a risk, an "
                                     f"open question or a disagreement, and "
                                     f"the replacement says none of it. "
                                     f"Reword it, do not drop it"))
            continue
        dead = dead_pointers(who, new)
        if dead:
            refused.append((ln, why, "it points at " + ", ".join(dead)
                            + ", renamed by another specialist in this run"))
            continue
        made = tail_added(neighbour(ln - 1), lines[ln - 1], new,
                          neighbour(ln + 1))
        if made:
            refused.append((ln, why, f"it would leave '{unmask.quote(made)}' "
                                     f"on both sides of a line break"))
            continue
        unpaired = parity_broken(lines[ln - 1], new)
        if unpaired:
            refused.append((ln, why, f"the replacement leaves an unpaired "
                                     f"{unpaired}"))
            continue
        strand = dangling(lines, ln, new, edited)
        if strand:
            refused.append((ln, why, f"the sentence wraps with line {strand}, "
                                     f"which nobody edited — it would be left "
                                     f"as a fragment"))
            continue
        if (new.strip() in same_text
                and len(new.split()) >= DUPLICATE_FROM_WORDS):
            refused.append((ln, why, f"line {same_text[new.strip()]} is "
                                     f"already being rewritten to these exact "
                                     f"words — a pointer is written once"))
            continue
        if op == "replace" and new.strip() and "|" in lines[ln - 1]:
            _was, _now = lines[ln - 1].count("|"), new.count("|")
            if _was != _now:
                refused.append((ln, why, f"this is a table row with {_was} "
                                         f"pipes and the reword has {_now} — "
                                         f"a row keeps its columns"))
                continue
        if who in DELETERS:
            for v in dropped_here(lines[ln - 1], new):
                for _ in range(max(1, lines[ln - 1].count(v) - new.count(v))):
                    dropped_by_noise.append((ln, v))
        if new.strip():
            same_text[new.strip()] = ln
        excused_drops += [(ln, tok, at)
                          for tok, at in _pending_excused.pop(ln, ())]
        out[ln - 1] = None if new.strip() == "" else new
        claimed[ln] = who
        claimed_by[ln] = id(res)
        applied.append((ln, why, "delete" if new.strip() == "" else "reword",
                        (lines[ln - 1], new)))

    why_at = {ln: why for ln, why, _, _ in applied}
    rollback = {}
    reason = {}
    refused_why = {}
    for _ln, _, _r in refused:
        refused_why.setdefault(_ln, _r)
    cause_of = {}
    bars = {i + 1 for i, ln in enumerate(lines)
            if is_separator(ln)}
    while True:
        grew = False
        for r in results:
            mine = {e["line"] for e in r.get("edits", ())
                    if isinstance(e.get("line"), int)
                    and e.get("op", "replace") == "replace"}
            landed = {ln for ln in mine
                      if claimed_by.get(ln) == id(r)} - set(rollback)
            tied = set().union(set(), *ties(r))
            blocked = ((mine - landed - (ceded[id(r)] - tied) - bars)
                       | (mine & set(rollback)))
            for run in edit_runs(r):
                if len(run) > 1 and blocked & run:
                    for ln in run & landed:
                        rollback[ln] = why_at[ln]
                        cause_of.setdefault(ln, sorted(blocked & run))
                        grew = True
        for ln in [a[0] for a in applied if a[0] in level]:
            if ln in rollback:
                continue
            span = section_span(headings, body_end(lines), ln)
            if not span:
                continue
            body = []
            for k in range(span[0] + 1, span[1] + 2):
                if k in inserts:
                    body.append(inserts[k][1])
                cur = lines[k - 1] if k in rollback else (
                    out[k - 1] if k <= len(out) else None)
                if cur is not None and k <= span[1]:
                    body.append(cur)
            gone = heading_payload(lines[ln - 1], out[ln - 1], (), body)
            if gone:
                rollback[ln] = why_at[ln]
                reason[ln] = (f"the heading tells the reader to "
                              f"'{unmask.quote(gone, 50)}' and nothing that "
                              f"landed says it — the edit that was going to "
                              f"carry it did not survive")
                grew = True
        if not grew:
            break
    if rollback:
        for ln in rollback:
            out[ln - 1] = lines[ln - 1]
            claimed.pop(ln, None)
        applied[:] = [a for a in applied if a[0] not in rollback
                      or a[2] not in ("reword", "delete")]
        dropped_by_noise[:] = [d for d in dropped_by_noise
                               if d[0] not in rollback]
        excused_drops[:] = [d for d in excused_drops if d[0] not in rollback]
        def block_cause(ln):
            """The line that broke this block, and the reason it broke."""
            seen, queue, found = set(), list(cause_of.get(ln, ())), []
            while queue:
                c = queue.pop(0)
                if c in seen:
                    continue
                seen.add(c)
                if c in reason or c in refused_why:
                    found.append((c, reason.get(c) or refused_why[c]))
                    continue
                queue += [x for x in cause_of.get(c, ()) if x not in seen]
            return (*found[0], len(found) - 1) if found else (None, None, 0)

        tail = " — half a rewrite is worse than none"
        _per_key = Counter(
            (e["line"], f"{r['specialist']}: {e.get('why', '')}".strip()
             .rstrip(":"))
            for r in results for e in r.get("edits", [])
            if type(e.get("line")) is int)
        _need = _per_key - Counter(a[:2] for a in applied)
        _said = Counter(x[:2] for x in refused)
        for ln, why in sorted(rollback.items()):
            if _said[(ln, why)] >= _need[(ln, why)]:
                continue
            _said[(ln, why)] += 1
            if ln in reason:
                refused.append((ln, why, reason[ln]))
                continue
            at, cause, more = block_cause(ln)
            if at is None:
                refused.append((ln, why, "the rest of this block followed a "
                                         "line the owner rule gave to another "
                                         "specialist" + tail))
            else:
                refused.append((ln, why, f"line {at} was refused ({cause})"
                                         + (f", and {more} more" if more else "")
                                         + f", and this is the rest of that "
                                           f"block{tail}"))

    if _round == 1 and not moves and not inserts:
        again, want = [], {}
        for r in results:
            picks = []
            done = set()
            for tie in ties(r):
                if any(claimed_by.get(ln) != id(r) or ln in rollback
                       for ln in tie):
                    done |= tie
            for e in r.get("edits", ()):
                ln = e.get("line")
                if ln not in ceded[id(r)] or out[ln - 1] is None:
                    continue
                if ln in done:
                    continue
                got = reoffer(e.get("old", ""), e.get("new", ""), out[ln - 1])
                if got and got.strip():
                    picks.append({"line": ln, "op": "replace",
                                  "old": out[ln - 1], "new": got,
                                  **({"group": e["group"]}
                                     if e.get("group") is not None else {})})
            if picks:
                again.append({**r, "edits": picks})
        if again:
            base = [ln if ln is not None else "" for ln in out]
            _m2, ok2, _no2, drop2 = merge(base, again, editable, quoted,
                                          headings, summary_line, _round=2,
                                          chat=chat,
                                          excused_drops=excused_drops,
                                          reorder=reorder)
            want = {(r["specialist"], e["line"]): e["new"]
                    for r in again for e in r["edits"]}
            for ln, who2, kind, _pair2 in ok2:
                out[ln - 1] = want[(who2, ln)]
                claimed[ln] = who2
                applied.append((ln, who2, kind,
                                (lines[ln - 1], want[(who2, ln)])))
            dropped_by_noise += drop2
            won = {(a[1], a[0]) for a in ok2}
            refused[:] = [x for x in refused
                          if not ((str(x[1]).split(":")[0].strip(), x[0]) in won
                                  and x[2].startswith("already changed by "))]

    merged, moved_src = [], set()
    for s_lo, s_hi, _to in moves:
        moved_src |= set(range(s_lo, s_hi + 1))
    by_dest = defaultdict(list)
    for m in moves:
        if m[2] is not None:
            by_dest[m[2]].append(m)

    def emit(i):
        if i in inserts:
            merged.extend(inserts[i][1].split("\n"))
        if i <= len(out) and out[i - 1] is not None:
            merged.append(out[i - 1])

    for i in range(1, len(out) + 2):
        for s_lo, s_hi, _to in by_dest.get(i, ()):
            if merged and merged[-1].strip():
                merged.append("")
            for j in range(s_lo, s_hi + 1):
                emit(j)
            if merged and merged[-1].strip():
                merged.append("")
        if i <= len(out) and i not in moved_src:
            emit(i)
    merged = collapse_blanks(merged) if applied else merged
    while (applied and merged and not merged[0].strip()
           and lines and lines[0].strip()):
        merged.pop(0)
    if applied:
        merged = (join_paragraphs(merged) if chat
                  else rewrap_prose(
                      lines if margin_from is None else margin_from, merged))
    elif margin_from is not None:
        merged = list(margin_from)
    cut = set()
    for _s_lo, _s_hi, _dest in moves:
        if _dest is None:
            cut |= set(range(_s_lo, _s_hi + 1))
    gone = sum(1 for i, l in enumerate(lines, 1)
               if fence_delim(l)[0] and i in cut)
    if gone % 2:
        raise UsageError(
            f"a deleted section holds {gone} code-fence lines, an odd number, "
            f"so one fence opens inside it and closes outside. That is a "
            f"section boundary falling inside a fence, not an edit. Nothing "
            f"was written.")
    was, now = (sum(1 for i, l in enumerate(lines, 1)
                    if fence_delim(l)[0] and i not in cut),
                sum(1 for l in "\n".join(merged).split("\n")
                    if fence_delim(l)[0]))
    if was != now:
        raise UsageError(
            f"the merge changed the number of code-fence lines, {was} → {now}. "
            f"Every fence below the first change swaps opener for closer, so "
            f"the output is corrupt. Nothing was written.")
    return merged, applied, refused, dropped_by_noise


LEADING_LABEL = re.compile(r"^\s*(?:[-*+]\s+)?[A-Z][^:`|]{0,40}:\s+\S")


def recapitalise(old, new):
    """Put the capital back when a reword dropped a leading colon label."""
    if not LEADING_LABEL.match(old) or LEADING_LABEL.match(new):
        return new
    m = re.match(r"^(\s*(?:[-*+]\s+)?)([a-z][a-z']*)(\s|$)", new)
    return f"{m.group(1)}{m.group(2).capitalize()}{new[m.end(2):]}" if m else new


def fold_cascade(gates, label=None):
    """Collapse a seam cascade into the one refusal that caused it."""
    label = label or (lambda a, b: f"L{a}" if a == b else f"L{a}-{b}")
    ordered, out, i = sorted(gates), [], 0
    while i < len(ordered):
        ln, why, reason = ordered[i]
        last, j = ln, i + 1
        while j < len(ordered) and ordered[j][0] == last + 1 and \
                ordered[j][2] == (f"line {last} does not finish its sentence "
                                  f"and this line held the rest"):
            last, j = ordered[j][0], j + 1
        n = last - ln
        out.append((label(ln, last), why,
                    reason if not n else
                    f"{reason}, and the {n} wrapped line{'' if n == 1 else 's'} "
                    f"under it went with it"))
        i = j
    grouped = {}
    for label, why, reason in out:
        grouped.setdefault((why, reason), []).append(label)
    return [(", ".join(labels), why, reason)
            for (why, reason), labels in grouped.items()]


from killverbosity import wrapping as _wrapping


def wrap_width(orig_lines):
    return _wrapping.wrap_width(orig_lines, mask)


def rewrap_prose(orig_lines, merged):
    return _wrapping.rewrap_prose(orig_lines, merged, mask)


def join_paragraphs(merged):
    return _wrapping.join_paragraphs(merged, mask)


def unwrap_source(lines, never_join=frozenset()):
    return _wrapping.unwrap_source(lines, mask, never_join)


def genre_lines(text, args):
    """The lines a genre is detected from: FOLDED, the way `run` folds them."""
    src = text.split("\n")
    return unwrap_source(src, freeze_barrier(args, src))[0]


def no_margin_notice(prose):
    """What `run` and `plan` both say about a file with no wrap margin."""
    n = len(_wrapping._continuation_lengths(prose))
    p = _wrapping.multiline_paragraphs(prose)
    return ("no wrap margin found, so the lines go to the specialists as "
            "written" + (f". {p} paragraph{'' if p == 1 else 's'} "
                         f"run{'s' if p == 1 else ''} over more "
                         f"than one line ({n} continuation line"
                         f"{'' if n == 1 else 's'}), and an edit rewriting one "
                         f"of those paragraphs will land on its first line only"
                         if n else ""))


def source_span(first, last, spans):
    return _wrapping.source_span(first, last, spans)


def collapse_blanks(lines):
    """One blank line between blocks. Deleting a paragraph leaves two."""
    out, fence, blanks = [], None, 0
    for ln in lines:
        m = re.match(r"^\s*(```+|~~~+)", ln)
        if m:
            tok = m.group(1)[:3]
            fence = tok if fence is None else (None if tok == fence else fence)
        if fence is None and not ln.strip():
            blanks += 1
            if blanks > 1:
                continue
        else:
            blanks = 0
        out.append(ln)
    return out


MARKDOWN_EXT = (".md", ".markdown", ".mdx")
BACKUP_EXT = (".bak", ".orig", ".old", ".save", ".backup", ".copy", ".rej")


def not_markdown(path):
    """The refusal for a source file, or None."""
    sfx = [s.lower() for s in path.suffixes[-2:]]
    if sfx and sfx[-1] in MARKDOWN_EXT:
        return None
    if len(sfx) == 2 and sfx[0] in MARKDOWN_EXT and sfx[1] in BACKUP_EXT:
        return None
    return (f"{path.name} is not Markdown, and every specialist in this "
            f"pipeline reads Markdown. On source it either changes nothing and "
            f"reports a pass, or reflows comments past the project's line "
            f"limit. To simplify code, read "
            f"{SPECIALIST_DIR / 'code.md'} and do it directly.")


class _Terminated(Exception):
    """Raised from the SIGTERM handler `cmd_run` installs around dispatch."""


def _sigterm_raises(signum, frame):
    raise _Terminated()


_FULL_TIMEOUT_RE = re.compile(r"timed out after \d+s|exited 124\b")


def cmd_run(args, launcher=None):
    """Run every specialist over one file and merge what comes back."""
    if launcher is None:
        launcher = call_agent
    if getattr(args, "agent", None) is None:
        try:
            args.agent = default_agent()
            args.agent_explicit = bool(os.environ.get("KV_AGENT"))
        except UsageError as e:
            if not (getattr(args, "no_agents", False)
                    or getattr(args, "dry_run", False)):
                print(f"kill-verbosity: {e}", file=sys.stderr)
                print(_exit_line(2))
                return 2
            args.agent = LOCAL_AGENTS[0]
    _run0 = time.monotonic()
    bad = not_markdown(Path(args.file))
    if bad:
        print(f"kill-verbosity: {bad}", file=sys.stderr)
        print(_exit_line(2))
        return 2
    _raw = Path(args.file).read_bytes()
    text = _raw.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    _crlf = _raw.count(b"\r\n")
    _ends = {"\n": _raw.count(b"\n") - _crlf, "\r\n": _crlf,
             "\r": _raw.count(b"\r") - _crlf}
    newline = max(("\n", "\r\n", "\r"), key=lambda e: _ends[e])
    src = Path(args.file)
    ends_nl = text.endswith("\n")
    body = text[:-1] if ends_nl else text
    source_lines = body.split("\n")
    lines, fold_spans = unwrap_source(source_lines, freeze_barrier(args, source_lines))
    if len(lines) != len(source_lines):
        _folded = [s for s in fold_spans if s[1] > s[0]]
        print(f"folded {sum(b - a + 1 for a, b in _folded)} wrapped lines "
              f"into {len(_folded)} paragraphs for the run", file=sys.stderr)
    body = "\n".join(lines)
    prose, headings, tables, quotes = mask(body, Path(args.file).name)
    kv_frozen = report_freeze(args, lines)
    prose_unfrozen = prose
    prose = blank_frozen(prose, kv_frozen)
    _editable, _editable_free = in_play(prose_unfrozen, tables, headings,
                                        quotes, kv_frozen)
    _weak_margin = None
    if len(lines) == len(source_lines):
        _margin_msg = no_margin_notice(prose)
        print(_margin_msg, file=sys.stderr)
        if _wrapping._continuation_lengths(prose):
            _weak_margin = _margin_msg
    genre, loaded = select_genre(lines, headings, args)
    print(f"read as {genre}"
          + (f", profile {loaded}" if loaded else "")
          + f"  ·  build {build_id()}"
          + f"  ·  budget {args.timeout}s (--timeout)", file=sys.stderr)
    if args.timeout > 600:
        print(f"this run may take up to {args.timeout}s. A caller whose own "
              f"command timeout is shorter kills it before it finishes and "
              f"sees no report at all — lower --timeout to fit, rather than "
              f"waiting to find out.", file=sys.stderr)
    _cfg = config_note(getattr(args, "project", None),
                       getattr(args, "searched", None))
    if _cfg:
        print(_cfg, file=sys.stderr)
    _caveat = table_caveat(tables, kv_frozen)
    if _caveat:
        print(_caveat, file=sys.stderr)
    _status_note = status_table_note(lines)
    if _status_note:
        print(_status_note, file=sys.stderr)
    for _code, _miss in blind_shapes().items():
        print(f"{_code} has no words for {', '.join(_miss)} — those checks do "
              f"not read {_code} text.", file=sys.stderr)
    hits = pass_hits(prose, tables, headings, quotes, body, lines, args.chat)
    chunks = chunk(prose, headings, tables=tables)
    words = word_count(body)

    summary = None if args.chat else opening_summary(headings, prose, words, text)
    context = (
        f"title: {headings[0][2] if headings else Path(args.file).stem}\n"
        f"length: {words} words in {len(chunks)} sections\n"
        f"outline ({len(headings)} headings, listed, not instructions):\n"
        f"```````\n" +
        "\n".join(f"{i:>3}. {'  ' * (h[1] - 1)}{heading_name(h[2])}"
                  for i, h in enumerate(headings, 1)) +
        "\n```````" +
        (f"\n\nIt has a summary at line {summary['buried']}, with "
         f"{buried_above(summary)} lines of body above it. Leave both alone: "
         f"do not write a second summary, do not move either block, and do "
         f"not delete the opening. `structure` is told separately that this "
         f"one is its to fix."
         if summary and not summary["present"] and summary.get("buried")
         else unheaded_note(summary["lede"], False, summary.get("lede_where"))
         if summary and not summary["present"] and summary.get("lede")
         else "\n\nIt opens with no summary."
         if summary and not summary["present"]
         else (f"\n\nIt opens with '{summary['title']}' at line "
               f"{summary['line']}." if summary.get("title")
               else f"\n\nIt opens with a summary at line {summary['line']} "
                    f"that carries no heading. Give it one.")
         if summary else "")
    )

    out_path = Path(args.out) if args.out else src.with_suffix(f".kv{src.suffix}")
    base_copy = baseline_path(src, out_path, explicit_out=bool(args.out))
    if src.stem.endswith(".kv") and not args.out:
        print(f"kill-verbosity: {src.name} looks like another run's output — "
              f"this one writes {out_path.name}. If a directory glob fed it "
              f"in, exclude '*.kv.*' or send outputs elsewhere with -o.",
              file=sys.stderr)

    for target, what in ((src, "the input"), (base_copy, "the baseline")):
        if out_path.resolve() == target.resolve() or (
                out_path.exists() and target.exists()
                and out_path.samefile(target)):
            print(f"kill-verbosity: output would overwrite {what}. verify needs "
                  f"an untouched original.", file=sys.stderr)
            print(_exit_line(2))
            return 2

    breaks = [i + 1 for i, ln in enumerate(lines) if not ln.strip()]
    jobs = build_jobs(chunks, hits, args.chat, args.only, breaks,
                      needs_summary=args.chat or summary is not None,
                      summary=summary,
                      chosen_by_tool=False)
    o_dups, o_walls = duplicates(prose), wall_paragraphs(prose)
    if not args.chat and "structure" in SPECIALISTS \
            and (args.only is None or "structure" in args.only):
        jobs += duplicate_jobs(without_lines(o_dups, unflaggable(prose, headings)),
                               len(lines), fold_spans)
        doc = next((j for j in jobs if j["specialist"] == "structure"
                    and j["unit"] == "document"), None)
        if doc and not doc.get("notes_only") and len(headings) >= 4 \
                and not getattr(args, "no_reorder", False):
            jobs.append({**doc, "unit": "document · order",
                         "hits": [], "outline": outline_of(headings, lines, prose)})
            doc["order_elsewhere"] = True
    if not args.chat and "planning" in SPECIALISTS \
            and (args.only is None or "planning" in args.only):
        _pl = next((j for j in jobs if j["specialist"] == "planning"), None)
        if _pl is not None and headings:
            _pl["unit"] = "document · sections"
            _pl["outline"] = outline_of(
                headings, lines, prose,
                scheduled=scheduled_sections(headings, lines))
        elif _pl is not None:
            jobs.remove(_pl)
            print("kill-verbosity: planning language is here and the file has "
                  "no headings, so there is no section to delete. The hits are "
                  "in the shape list above.", file=sys.stderr)
    if not jobs:
        print("nothing to do: no shape fired and no specialist owes an answer.")
        print(_exit_line(0))
        return 0

    _avail_note = None
    if args.dry_run:
        _dr = agent_installed(args.agent)
        _avail_note = "installed, not probed" if _dr else "NOT INSTALLED"
    print(dispatch_density(hits, word_count(text), len(jobs), args.agent,
                           sending=not getattr(args, "no_agents", False),
                           avail_note=_avail_note))
    if not args.chat:
        print(yield_line(yield_ceiling(hits, prose, tables, headings, quotes,
                                       lines, kv_frozen)))
        _realised = realised_yield_note(src, text)
        if _realised:
            print(_realised)

    if not any(j["specialist"] == "summary" for j in jobs) \
            and (summary or SWITCHED_OFF.get("summary")):
        print(f"  summary     skipped — {summary_blocked(summary)}")

    for _name, _prof in sorted(SWITCHED_OFF.items()):
        if _name != "summary":
            print(f"  {_name:<11} skipped — off for {_prof} — this kind of "
                  f"document does not use it")

    _budget_note = "" if getattr(args, "no_agents", False) else \
        budget.matrix_note(len(jobs), JOBS, args.job_timeout,
                           None if args.no_budget else args.timeout,
                           journal_timeouts(out_path, source_fingerprint(
                               f"{args.agent}\0{build_id()}\0{text}")))
    if _budget_note:
        print(_budget_note, file=sys.stderr)

    if args.dry_run:
        print()
        for j in jobs:
            lo, hi = source_span(j["lo"], j["hi"] or len(lines), fold_spans)
            print(f"  {j['specialist']:<11} lines {lo:>4}-{hi:<4} "
                  f"{len(j['hits']):>3} hits   {j['unit']}")
        print(_exit_line(0))
        return 0

    _made_baseline = not base_copy.exists()
    if _made_baseline:
        shutil.copyfile(src, base_copy)
    print(f"baseline: "
          f"{base_copy.name if base_copy.parent == src.parent else base_copy} "
          f"({'created' if _made_baseline else 'existing'})",
          file=sys.stderr)
    fingerprint = source_fingerprint(f"{args.agent}\0{build_id()}\0{text}")
    _journal_was_there = journal_path(out_path).is_file()
    banked = read_journal(out_path, fingerprint)
    if not banked:
        journal_path(out_path).unlink(missing_ok=True)
    if rerun.verdict(out_path, src, text, banked) == rerun.REFUSE:
        print(rerun.refusal(out_path.name, out_path.stat().st_mtime,
                            src.stat().st_mtime,
                            "banked" if banked
                            else "discarded" if _journal_was_there
                            else "none"), file=sys.stderr)
        print(_exit_line(2))
        return 2

    print(f"{JOBS} at a time:", file=sys.stderr)
    queued = defaultdict(int)
    for j in jobs:
        queued[j["specialist"]] += 1
    print("  " + ", ".join(f"{n}x {who}" for who, n in queued.items()),
          file=sys.stderr)

    index = token_lines(lines)

    dup_note = ""
    if not args.chat:
        incs = inconsistencies(text)
        if incs:
            dup_note += "\n\n# One thing said two ways\n\n" + "\n".join(
                "  " + (f"term: {' / '.join(i['forms'])}" if i["kind"] == "term"
                        else f"number {i['value']} with units {i['units']}")
                for i in incs[:20])
        if dup_note:
            dup_note += ("\n\nTwo numbers for one finding is a factual bug, "
                         "so raise it in `notes` rather than picking one.\n")

    base = Path(args.file).resolve().parent
    if banked:
        print(f"  resuming: {len(banked)} answer"
              f"{'' if len(banked) == 1 else 's'} already paid for, in "
              f"{journal_path(out_path).name}", file=sys.stderr)
    run_budget = budget.Budget(None if args.no_budget else args.timeout)
    unusable = []

    def one(job, note=""):
        job = {k: v for k, v in job.items()
               if k not in ("answered_rung", "answered_by",
                            "answered_by_state")}
        if getattr(args, "no_agents", False):
            return {**job, "edits": [], "notes": []}
        extra = (dup_note if job["specialist"] == "structure" else "") + note
        d = job.get("one_duplicate")
        if d:
            extra += (
                "\n\n# This job is one repeat, and nothing else\n\n"
                f"These lines say the same thing: {', '.join(str(l) for l in sorted(d['lines']))}\n\n"
                f"    {d['text'][:200]}\n\n"
                "Pick the copy that owns it — the one whose section the reader "
                "would look in — and leave it whole. Cut every other copy to a "
                "pointer, or delete it where the sentence around it still "
                "reads without it. Send no other edit in this reply: another "
                "job owns the rest of this span.\n\n"
                "If both copies are load-bearing where they sit, say so in "
                "`notes` and send no edits.\n")
        if job.get("order_elsewhere"):
            extra += ("\n\n# Section order is a separate job\n\nAnother job "
                      "holds the outline and sends the `move` operations. "
                      "Send none from here. Rename, fold a fact back to its "
                      "one owner, and raise the rest in `notes`.\n")
        if job.get("notes_only"):
            extra += ("\n\n# Report only\n\nNo shape fired anywhere in this "
                      "file, so send no `edits` — an empty list. Put what you "
                      "found in `notes` and a person decides. Say where the "
                      "result should sit and which fact has two homes; do not "
                      "move or rename anything yourself.\n")
        if job.get("unbury"):
            extra += ("\n\nOne exception. The summary is buried, and "
                      "`move-block` is the operation that clears it. Send "
                      "those and nothing else. Every other edit is dropped.\n")
        job_context = context
        if summary and not summary["present"] and summary.get("lede"):
            if job["specialist"] == "summary":
                _w = summary.get("lede_where")
                job_context = context.replace(
                    unheaded_note(summary["lede"], False, _w),
                    unheaded_note(summary["lede"], True, _w))
            elif SPECIALISTS[job["specialist"]][0] == "document":
                job_context += (" Say in your report that the opening is "
                                "unheaded and let a human decide.")
        elif summary and not summary["present"] and summary.get("buried") \
                and job["specialist"] == "structure" \
                and job["unit"] == "document":
            job_context += (
                f" That last rule is for the others. The summary is buried "
                f"and it is yours: the {buried_above(summary)} lines above "
                f"line {summary['buried']} have no heading, so read them and "
                f"decide which they are. Body material for a section already "
                f"in the file goes there with `move-block`, one edit per "
                f"block of lines, and it becomes that section's opening. An "
                f"opening that only announces the document is a deletion. If "
                f"it is neither, say so in your report and leave it — do not "
                f"invent a heading for it.")
        if (_msg := empty_span_error(job, lines)) is not None:
            return {**job, "error": _msg, "unsent": True}
        prompt = job_prompt(job, lines, job_context, index, extra, base)
        key = journal_key(prompt)
        if key in banked:
            return {**job, **banked[key]}
        if unusable:
            return {**job, "error": unusable[0], "unsent": True}
        if run_budget.exhausted():
            return {**job, "error": budget.unsent_reason(run_budget.total),
                    "unsent": True}
        if run_budget.starved(args.job_timeout):
            return {**job, "error": budget.unsent_reason(run_budget.total),
                    "unsent": True}
        given = run_budget.job_timeout(args.job_timeout)

        _subst = []

        def _fell(msg, _j=job):
            if "failed, answered by" in msg:
                _subst.append(msg)
            # An agent nobody named falls back silently: the job line's `~`
            # and the `answered by:` tail say who answered.
            if not getattr(args, "agent_explicit", True):
                return
            print(f"  {_j['specialist']} {_j['unit']}: {msg}",
                  file=sys.stderr, flush=True)

        _kw = {}
        if _takes_say(launcher):
            _kw["say"] = _fell
        if job.get("avoid") and _accepts(launcher, "avoid"):
            _kw["avoid"] = tuple(job["avoid"])
        _who = {}
        if _accepts(launcher, "answered"):
            def _answered(rung, via, looked):
                _who.update(
                    answered_rung=rung, answered_by=via,
                    answered_by_state=(ANSWERED_NOT_LOOKED if not looked
                                       else ANSWERED_READ if via
                                       else ANSWERED_UNKNOWABLE))
            _kw["answered"] = _answered
        try:
            raw, err = launcher(prompt, args.agent, given, **_kw)
        except BackendUnusable as e:
            unusable.append(str(e))
            return {**job, "error": str(e), "unsent": True, "dispatched": True}
        if err:
            if given < run_budget.cap(args.job_timeout):
                return {**job, "unsent": True, "dispatched": True,
                        "error": budget.cut_clock_reason(
                            run_budget.total, given, args.job_timeout)}
            if _FULL_TIMEOUT_RE.search(err):
                bank_timeout(out_path, fingerprint,
                             f"{job['specialist']} {job['unit']}", given)
            return {**job, "error": err}
        payload, err = parse_reply(raw)
        if err:
            return {**job, "error": err, "reply_error": err}
        if _NO_SOURCE_LINES_RE.search(raw):
            _msg = ("the reply says no source lines were provided -- the "
                    "prompt did not reach the backend intact")
            return {**job, "error": _msg, "reply_error": _msg}
        edits = payload.get("edits", [])
        if job.get("notes_only"):
            edits = [e for e in edits if job.get("unbury")
                     and e.get("op") == "move-block"]
        notes = payload.get("notes", [])
        if (dropped := len(payload.get("edits", [])) - len(edits)):
            notes = notes + [f"{dropped} edits dropped: nothing "
                             f"matched in this file, so structure reports only"]
        answer = {"edits": edits, "notes": notes}
        with journal_path(out_path).open("a", encoding="utf-8") as bank:
            bank.write(json.dumps({"source": fingerprint, "key": key,
                                   "result": {**answer, **_who,
                                              "substituted": bool(_subst)}})
                       + "\n")
        return {**job, **answer, "substituted": bool(_subst),
                "subst_msgs": list(_subst), **_who}

    _first = ("summary", "structure")
    _sending = sorted(jobs, key=lambda j: (j["specialist"] not in _first,
                                           _first.index(j["specialist"])
                                           if j["specialist"] in _first else 0))

    _prev_sigterm = signal.signal(signal.SIGTERM, _sigterm_raises)
    _terminated = False
    try:
        with ThreadPoolExecutor(max_workers=JOBS) as pool:
            futures = {pool.submit(one, j): j for j in _sending}
            _slot = {id(j): i for i, j in enumerate(jobs)}
            results = [None] * len(jobs)
            t0 = time.monotonic()
            said, _done = set(), 0
            try:
                for f in as_completed(futures):
                    r = f.result()
                    results[_slot[id(futures[f])]] = r
                    _done += 1
                    mark = "!" if r.get("error") else (
                        "~" if r.get("substituted") else "·")
                    n_ed = len(r.get("edits", []))
                    tag = error_digest(r.get("error")) if r.get("error") else ""
                    if tag in said:
                        tag = ""
                    elif tag:
                        said.add(tag)
                    print(f"  [{_done:>2}/{len(jobs)}] {mark} "
                          f"{int(time.monotonic() - t0):>4}s {r['specialist']:<11} "
                          f"{n_ed:>2} proposed  {r['unit']}"
                          f"{'  ' + tag if tag else ''}",
                          file=sys.stderr)
            except _Terminated:
                _terminated = True
                pool.shutdown(wait=False, cancel_futures=True)
                print(f"\nkill-verbosity: SIGTERM received -- {_done} of "
                      f"{len(jobs)} jobs had already answered. Not sending "
                      f"any more; letting whatever was already in flight "
                      f"land, then reporting what landed.", file=sys.stderr)
    finally:
        signal.signal(signal.SIGTERM, _prev_sigterm)

    if _terminated:
        for f, job in futures.items():
            idx = _slot[id(job)]
            if results[idx] is not None:
                continue
            try:
                results[idx] = f.result()
            except Exception:
                results[idx] = {
                    **job, "unsent": True,
                    "error": budget.sigterm_reason()}

    asking = defaultdict(list)
    for r in results:
        if r.get("error") and not r.get("unsent"):
            asking[error_digest(r["error"])].append(f"{r['specialist']} · {r['unit']}")
    for _cause, _who in asking.items():
        _cap = top(3)
        _more = f" and {len(_who) - _cap} more" if len(_who) > _cap else ""
        print(f"  {len(_who)} job{'' if len(_who) == 1 else 's'} failed "
              f"({_cause}), asking once more: {', '.join(_who[:_cap])}{_more}",
              file=sys.stderr)
    for i, r in enumerate(results):
        if not r.get("error") or r.get("unsent"):
            continue
        bad = r.get("reply_error")
        launch_failed = isinstance(r.get("error"), _LaunchError)
        _t0 = time.monotonic()
        again = one(
            {**{k: v for k, v in r.items()
                if k not in ("error", "reply_error")},
             **({"avoid": (args.agent,)} if bad or launch_failed else {})},
            note=("\n\n# Your last answer was rejected\n\n"
                  f"    {bad}\n\n"
                  "Send the same work again as one JSON object and nothing "
                  "around it. Every edit needs an integer `line`, and `old`, "
                  "`new`, `why` and `op` are strings.\n" if bad else ""))
        _tag = error_digest(again["error"]) if again.get("error") else ""
        if _tag in said:
            _tag = ""
        elif _tag:
            said.add(_tag)
        _retry_mark = "!" if again.get("error") else (
            "~" if again.get("substituted") else "·")
        print(f"  [ retry ] {_retry_mark} "
              f"{int(time.monotonic() - _t0):>4}s {again['specialist']:<11} "
              f"{len(again.get('edits', [])):>2} proposed  {again['unit']}"
              f"{'  ' + _tag if _tag else ''}",
              file=sys.stderr)
        if not again.get("error"):
            results[i] = again
        elif again.get("dispatched"):
            results[i] = again
        elif again.get("unsent"):
            results[i] = {**r, "unsent": True,
                          "error": budget.unretried_reason(
                              run_budget.total, error_digest(r["error"]))}

    by_line = {e["line"]: e.get("new", "")
               for r in results for e in r.get("edits", [])
               if e.get("op", "replace") == "replace"
               and isinstance(e.get("line"), int)}
    renames = renamed_headings(headings, by_line)
    _renames = pointers.rename_map(headings, by_line)
    _will_write = heads_after(headings, _renames)
    _followed = pointers.follow(results, _renames)
    if _followed:
        print(f"  {len(_followed)} summary pointer"
              f"{'' if len(_followed) == 1 else 's'} sent after a heading "
              f"`structure` renames in this run", file=sys.stderr)
    _owner = {e["line"]: r["specialist"] for r in results
              for e in r.get("edits", [])
              if e.get("op", "replace") == "replace"
              and isinstance(e.get("line"), int)}
    opens = bool(summary_opens_after(
        lines, {k: v for k, v in by_line.items() if 1 <= k <= len(lines)},
        _owner))
    summary_tried = any(
        r["specialist"] == "summary"
        and any(e.get("op", "replace") in ("insert", "replace")
                and heads_summary(e.get("new", ""))
                for e in r.get("edits", []))
        for r in results)
    for i, r in enumerate(results):
        if r["specialist"] != "summary" or r.get("error"):
            continue
        edits = r.get("edits", [])
        n = sum(len(e.get("new", "").split()) for e in edits)
        ins = [e for e in edits if e.get("op") == "insert"]
        bad = sorted({b for e in ins
                      for b in added_shapes(e.get("new", ""), body)})
        dead = sorted({heading_name(p) for e in edits
                       for p in re.findall(r"\(([^()\n]{3,60})\)",
                                           e.get("new", ""))
                       if heading_name(p) in renames})
        adrift = sorted({p for e in edits
                         for p in _paraphrased_pointers(e.get("new", ""),
                                                        _will_write)})
        ghosts = set()
        for e in edits:
            miss, broken = ghost_pointers(e.get("new", ""), _will_write)
            if broken:
                ghosts |= set(miss)
        ghosts = sorted(ghosts - set(adrift))
        double = opens and any(heads_summary(e.get("new", "")) for e in ins)
        say = []
        cap = summary_cap(summary.get("doc") if summary else None)
        if n > cap:
            say.append(f"Your last answer was {n} words. The cap is "
                       f"{cap} and it is not a target. Keep the "
                       f"result and the pointers; the body already holds the "
                       f"detail.")
        if bad:
            say.append(f"It was refused whole because the text you sent has "
                       f"{', '.join(bad)}. Send one heading line followed by "
                       f"prose, and nothing else.")
        if dead:
            say.append(f"It points at {', '.join(dead)}, which another "
                       f"specialist renames in this same run. Name those "
                       f"sections by what they are about, not by their current "
                       f"heading.")
        if adrift or ghosts:
            say.append(f"It points at {', '.join(adrift + ghosts)}, and no "
                       f"heading reads that way. A bracket naming a section "
                       f"has to copy the heading word for word, or say what "
                       f"the section is about without brackets.")
        if double:
            at = (f" at line {summary['line']}"
                  if summary and summary.get("present") else "")
            say.append(f"The file already opens with a summary{at}. Rewrite "
                       f"that one line by line with `replace`; do not insert "
                       f"a second.")
        if not say:
            continue
        print(f"  summary answer refused, asking once more: "
              f"{say[0].split('.')[0]}", file=sys.stderr)
        again = one(r, "\n\n" + "\n\n".join(say) + "\n")
        summary_tried = summary_tried or any(
            e.get("op", "replace") in ("insert", "replace")
            and heads_summary(e.get("new", ""))
            for e in again.get("edits", []))
        if not again.get("error"):
            pointers.follow([again], _renames)
            results[i] = again
            continue
        bad = {**r, "edits": [], "error": again["error"]}
        if again.get("unsent"):
            bad["unsent"] = True
            if not again.get("dispatched"):
                bad["error"] = budget.unretried_reason(
                    run_budget.total,
                    f"summary answer refused: {say[0].split('.')[0]}")
        results[i] = bad

    order = list(SPECIALISTS)
    _answered = [answered_fields(r) for r in results]
    _who_tail = answered_tail(_answered, args.agent)

    _all_substituted = bool(_answered) and all(a["substituted"] for a in _answered)
    if _all_substituted and getattr(args, "agent_explicit", False):
        if getattr(args, "any_agent", False):
            print(f"  --any-agent: proceeding -- all {len(jobs)} jobs were "
                  f"answered by a substituted backend, not {args.agent}, "
                  f"which you named explicitly (ANY-AGENT)\n")
        else:
            _who = sorted({a.get("answered_by") or a.get("answered_rung")
                           or "an unnamed agent"
                           for a in _answered})
            print(f"\nALL {len(jobs)} jobs were answered by a substituted "
                  f"backend ({', '.join(_who)}), not {args.agent} -- which "
                  f"you named explicitly. Nothing was answered by "
                  f"{args.agent}, so nothing is written.\nRerun with "
                  f"--any-agent to accept these answers anyway, or fix why "
                  f"{args.agent} did not answer and rerun -- the paid-for "
                  f"answers above are banked in {journal_path(out_path).name} "
                  f"and are not spent again.", file=sys.stderr)
            print(_exit_line(6))
            return 6

    results.sort(key=lambda r: (order.index(r["specialist"]), r["lo"], r["unit"]))
    failed = [r for r in results if r.get("error")]
    promoted = moves.promote([r for r in results if not r.get("error")],
                             len(lines))
    if promoted:
        print(f"  {len(promoted)} move{'' if len(promoted) == 1 else 's'} "
              f"described in a note, made as edits", file=sys.stderr)
    excused_drops = []
    merged, applied, refused, noise_drops = merge(
        lines, [r for r in results if not r.get("error")],
        editable_lines(prose, tables, headings, quotes, kv_frozen),
        {l for l, _ in quotes}, headings,
        summary["line"] if summary and summary["present"] else 0,
        chat=args.chat, margin_from=source_lines,
        excused_drops=excused_drops, held=kv_frozen,
        reorder=not getattr(args, "no_reorder", False))

    _added = repeat_delta(o_dups, duplicates(
        mask("\n".join(merged), src.name)[0],
        src="\n".join(merged).split("\n")))[1]
    blamed = repeat_blame(_added, results) if _added else set()
    if blamed:
        thinner = [dict(r, edits=[e for e in r["edits"] if id(e) not in blamed])
                   for r in results if not r.get("error")]
        _again_excused = []
        again = merge(
            list(lines), thinner,
            editable_lines(prose, tables, headings, quotes, kv_frozen),
            {l for l, _ in quotes}, headings,
            summary["line"] if summary and summary["present"] else 0,
            chat=args.chat, margin_from=source_lines,
            excused_drops=_again_excused, held=kv_frozen,
            reorder=not getattr(args, "no_reorder", False))
        if not repeat_delta(o_dups, duplicates(
                mask("\n".join(again[0]), src.name)[0]))[1]:
            merged, applied, refused, noise_drops = again
            excused_drops = _again_excused
            refused = list(refused) + [
                (ln, f"{who}: dedup",
                 f"the replacement repeats text already in the "
                 f"file: {unmask.quote(txt)}")
                for ln, who, txt in blame.repeat_rows(
                    _added, [r for r in results if not r.get("error")],
                    repeat_key, DUPLICATE_FROM_WORDS)]

    with open(out_path, "w", encoding="utf-8", newline="") as _fh:
        _fh.write(newline.join(merged) + (newline if ends_nl else ""))

    _own = "already changed by "
    owned = [r for r in refused if r[2].startswith(_own)]
    gates = [r for r in refused if r not in owned]
    proposed = sum(len(r.get("edits", [])) for r in results)
    print(f"\n{len(applied)} of {proposed} "
          f"edits applied, {len(gates)} refused by the gates"
          + (f", {len(owned)} went to the line's owner" if owned else "")
          + f" → {out_path}\n")
    _subst = [r for r in results if r.get("substituted")]
    if _subst and getattr(args, "agent_explicit", True):
        _cap = top(3)
        _who = [f"{r['specialist']} · {r['unit']}" for r in _subst]
        _more = f" and {len(_who) - _cap} more" if len(_who) > _cap else ""
        print(f"  {len(_subst)} of {len(jobs)} job"
              f"{'' if len(_subst) == 1 else 's'} answered by a substituted "
              f"backend, not {args.agent} ({', '.join(_who[:_cap])}{_more})\n")
        _causes = Counter()
        for r in _subst:
            for rung, cause in _subst_rung_causes(r.get("subst_msgs", [])):
                _causes[(rung, cause)] += 1
        if _causes:
            _parts = [f"{rung} {n} fail ({cause})"
                      for (rung, cause), n in sorted(_causes.items())]
            print(f"    {', '.join(_parts)}\n")
        if len(_subst) == len(jobs):
            print(f"  ALL {len(jobs)} JOBS SUBSTITUTED -- nothing here was "
                  f"answered by {args.agent}\n")
    _sum = len(applied) + len(gates) + len(owned)
    if _sum != proposed:
        _why = ("an edit landed on more than one line" if _sum > proposed
                else "some edits are in no bucket")
        print(f"  (the three add to {_sum}, not {proposed} — {_why}. "
              f"Report this.)\n")
    by_who = defaultdict(list)
    for ln, why, kind, _pair in applied:
        by_who[why.split(":")[0]].append((ln, kind, why))
    for who in order:
        if who in by_who:
            kinds = defaultdict(int)
            for _, kind, _ in by_who[who]:
                kinds[kind] += 1
            print(f"  {who:<11} " + ", ".join(f"{n} {k}" for k, n in
                                              sorted(kinds.items())))
    for who in order:
        n = sum(len(r.get("edits", [])) for r in results
                if r["specialist"] == who and not r.get("error"))
        if n and who not in by_who:
            mine = [r for r in refused if r[1].split(":")[0] == who]
            o = sum(1 for r in mine if r in owned)
            g = len(mine) - o
            if o and not g:
                what = f"all {o} went to the line's owner"
            elif g and not o:
                what = f"all {g} refused by the gates"
            else:
                what = f"{g} refused by the gates, {o} went to the line's owner"
            print(f"  {who:<11} nothing applied — {what}")
    if refused:
        if owned:
            for _line in owner_report(owned, _own, fold_spans):
                print(_line)
        if gates:
            folded = fold_cascade(
                gates, label=lambda a, b: _wrapping.label(a, b, fold_spans))
            _n = (f"{len(gates)}" if len(folded) == len(gates) else
                  f"{len(gates)} in {len(folded)} group"
                  f"{'' if len(folded) == 1 else 's'}")
            print(f"\nrefused ({_n}) — these lines are unchanged:")
            for label, why, reason in folded:
                print(f"  {label}  {reason}   [{why}]")
    n_prose = mask("\n".join(merged), src.name)[0]
    o_w, n_w = word_count(text), word_count("\n".join(merged))
    n_mv = sum(1 for _, _, k, _ in applied if k == "move")
    n_bk = sum(1 for _, _, k, _ in applied if k == "move-block")
    n_ds = sum(1 for _, _, k, _ in applied if k == "delete-section")
    _pc = abs(o_w - n_w) * 100 / max(o_w, 1)
    print(f"\nthe document: {o_w} → {n_w} words "
          f"({_pc:.1f}% {'cut' if n_w <= o_w else 'longer'}), "
          f"{n_mv} section{'' if n_mv == 1 else 's'} moved"
          + (f", {n_bk} block{'' if n_bk == 1 else 's'} moved" if n_bk else "")
          + (f", {n_ds} section{'' if n_ds == 1 else 's'} deleted"
             if n_ds else ""))
    if n_ds:
        print("  deleted — read these rather than diffing the file:")
        for _ln, _w, _k, _ in applied:
            if _k == "delete-section" and 0 < _ln <= len(lines):
                _sp = section_span(headings, body_end(lines), _ln)
                _n = (_sp[1] - _sp[0] + 1) if _sp else 0
                print(f"    L{_ln:<16} {lines[_ln - 1].strip()[:56]}"
                      f"   ({_n} lines)")
    _mv = [(ln, lines[ln - 1].strip())
           for ln, _w, k, _p in applied
           if k in ("move", "move-block") and 0 < ln <= len(lines)]
    if _mv:
        print(f"  moved — read these rather than diffing the file:")
        for ln, txt in _mv:
            _to = merged.index(lines[ln - 1]) + 1 \
                if lines[ln - 1] in merged else None
            _where = f"L{ln} → L{_to}" if _to else f"L{ln} → (rewrapped)"
            print(f"    {_where:<18} {txt[:70]}")
    _seen = set()
    for j in jobs:
        if j["specialist"] in DOC_ONLY:
            continue
        _seen |= set(range(j.get("lo", 1),
                           (j["hi"] if j.get("hi") else len(prose)) + 1))
    _pw = sum(len(prose[i - 1].split()) for i in range(1, len(prose) + 1))
    _dw = sum(len(prose[i - 1].split()) for i in sorted(_seen)
              if 1 <= i <= len(prose))
    _share = _dw / _pw if _pw else 0.0
    _aim = round(o_w * (1 - _share + _share * LENGTH_TARGET))
    _over = n_w / _aim if _aim else 0
    _wrote_summary = any(
        op == "insert" and str(why).split(":")[0].strip() == "summary"
        for _ln, why, op, _p in applied)
    if o_w and n_w > _aim and _dw:
        _tail = (f"Past {OVER_TARGET_BAND}x is the tail — read the diff: "
                 f"either the document has to be this long, or the pass "
                 f"stopped early.")
        if _wrote_summary:
            _tail = (f"Past {OVER_TARGET_BAND}x is the tail, and this run "
                     f"INSERTED an opening summary, so some of that figure is "
                     f"text this pass wrote"
                     + (f" — the document ended {n_w - o_w} words LONGER than "
                        f"it started" if n_w > o_w else "")
                     + f". Read the diff: the document has to be this long, "
                       f'the pass stopped early, or the summary is not worth '
                       f'its words here — {{"specialists": [...]}} in '
                       f".killverbosity.json names the ones to run, and a "
                       f"list without `summary` writes none.")
        print(f"  {'over target':<24} {n_w} against {_aim} ({_over:.2f}x). "
              f"A run lands at about 1.2x this. "
              + (_tail if _over > OVER_TARGET_BAND else "This one is normal."))
    if _pw and _share < 0.99:
        print(f"  {'not sent to anyone':<24} {_pw - _dw} of {_pw} prose words "
              f"({100 * (1 - _share):.0f}%). No shape fired there, so no "
              f"specialist was given those lines and they cannot shrink."
              + (" The target above is charged only on what was sent."
                 if _dw else ""))
    elif not _pw and kv_frozen and _editable_free:
        print(f"  {'not sent to anyone':<24} the whole file. "
              f"{len(kv_frozen)} line(s) are frozen by "
              f"{getattr(args, 'project', None) or '.killverbosity.json'}, "
              f"which is all of the prose, so no reworder was given anything.")
    elif not _pw:
        print(f"  {'not sent to anyone':<24} the whole file. It holds no "
              f"prose — every line is quotation, a fence or a table — so no "
              f"reworder was given anything and nothing here can shrink.")
    o_s = sum(1 for _ in _split(" ".join(countable(text, src.name))))
    n_s = sum(1 for _ in _split(" ".join(
        countable("\n".join(merged), src.name))))
    if o_s != n_s:
        print(f"  {'sentences':<24} {o_s} → {n_s} "
              f"({'+' if n_s > o_s else ''}{n_s - o_s}"
              f"{', the survivors got longer' if n_s < o_s else ''})")
    _fixed, _added = repeat_delta(o_dups, duplicates(n_prose))
    if o_dups:
        print(f"  {'repeats resolved':<24} {_fixed} of {len(o_dups)}")
    if _added:
        print(f"  {'repeats introduced':<24} {len(_added)} "
              f"(lines {cluster_lines(_added)} of {out_path.name})")
    if o_walls:
        print(f"  {'paragraph walls':<24} {len(o_walls)} → "
              f"{len(wall_paragraphs(n_prose))}")

    still_here = {v for vals in facts("\n".join(merged)).values() for v in vals}
    reshaped = [(ln, t) for ln, t in noise_drops if t in still_here]
    noise_drops = [(ln, t) for ln, t in noise_drops if t not in still_here]
    if noise_drops:
        print(f"\nnoise dropped {len(noise_drops)} protected token"
              f"{'' if len(noise_drops) == 1 else 's'} — that is "
              f"the job it was called to do. Read the line each one sat on:")
        for ln, tok in noise_drops:
            print(f"  {_wrapping.label(ln, ln, fold_spans)}  {tok}")
            print(f"        {unmask.quote(lines[ln - 1], top(90))}")
    if reshaped:
        _rows = list(dict.fromkeys(reshaped))
        print(f"\n{len(_rows)} protected token"
              f"{'' if len(_rows) == 1 else 's'} moved off the line noise "
              f"edited and {'is' if len(_rows) == 1 else 'are'} still "
              f"somewhere in the file. Check that the sentence still says what "
              f"it said:")
        for ln, tok in _rows[:top(5)]:
            at = [str(i) for i, line in enumerate(merged, 1) if tok in line]
            print(f"  {_wrapping.label(ln, ln, fold_spans)}  {tok}"
                  + (f"  → now L{', L'.join(at[:3])} of {out_path.name}"
                     if at else ""))
        if len(_rows) > top(5):
            print(f"      … showing {top(5)} of {len(_rows)}")
    if excused_drops:
        _rows = list(dict.fromkeys(excused_drops))
        print(f"\n{len(_rows)} protected token"
              f"{'' if len(_rows) == 1 else 's'} left a reworded line and the "
              f"same token is on another line. That is allowed where both say "
              f"one fact. Check it is not two facts sharing a value:")
        for ln, tok, at in _rows[:top(5)]:
            print(f"  {_wrapping.label(ln, ln, fold_spans)}  {tok}"
                  f"  → also L{', L'.join(str(i) for i in at[:3])}")
        if len(_rows) > top(5):
            print(f"      … showing {top(5)} of {len(_rows)}")
    notes = [(r["specialist"], n) for r in results for n in r.get("notes", [])
             if not echoed_template(n)]
    if _weak_margin:
        notes.append(("kill-verbosity", _weak_margin))
    if notes:
        _groups = group_notes(notes)
        print(f"\nnotes ({len(notes)}) — read these, no tool can decide them:"
              + (f"  showing {top(12)} of {len(_groups)}; --full for the rest"
                 if len(_groups) > top(12) else ""))
        for members in _groups[:top(12)]:
            who, n = members[0]
            print(f"  {who:<11} {n}")
            if len(members) > 1:
                by = Counter(w for w, _ in members)
                others = [w for w in sorted(by) if w != who]
                said = ([f"also from {', '.join(others)}"] if others else []) \
                    + ([f"{who} raised it in {by[who]} of its jobs"]
                       if by[who] > 1 else [])
                print(f"  {'':<11} … {'; '.join(said)}")
    if failed:
        _n = len(failed)
        print(f"\n{_n} specialist{'' if _n == 1 else 's'} failed and "
              f"{'its' if _n == 1 else 'their'} span is unedited:")
        _seen = defaultdict(list)
        for r in failed:
            print(f"  {r['specialist']:<11} {r['unit']}")
            _seen[error_digest(r["error"])].append(r["specialist"])
        for _cause, _who in sorted(_seen.items(), key=lambda kv: -len(kv[1])):
            print(f"  → {len(_who)} of them on: {_cause}")

    try:
        _at_finish = source_fingerprint(src.read_text(errors="replace"))
    except OSError as _e:
        _at_finish = None
        print(f"could not re-read {src.name} at the end of the run ({_e}), so "
              f"source_at_finish is null in "
              f"{run_record_path(out_path).name}: nobody looked, which is not "
              f"the same as the input not having moved. Read {src.name} "
              f"yourself before accepting.", file=sys.stderr)
    if _at_finish is not None and _at_finish != source_fingerprint(text):
        _same_dir = base_copy.parent == src.parent == out_path.parent
        _bc = base_copy.name if _same_dir else str(base_copy)
        _op = out_path.name if _same_dir else str(out_path)
        print(f"INPUT MOVED UNDER THIS RUN — {src.name} hashes "
              f"{_at_finish[:12]} now and hashed "
              f"{source_fingerprint(text)[:12]} when this run read it. "
              f"Something else wrote it while the specialists were out.\n"
              f"  diff {_bc} {src.name}      "
              f"— what the other writer changed\n"
              f"  diff {_bc} {_op}      "
              f"— what this run changed\n"
              f"Read those two before believing any finding below: a row this "
              f"run never touched can read as content it dropped, and a row a "
              f"specialist put back reads the same way. Both digests are in "
              f"{run_record_path(out_path).name}.", file=sys.stderr)
    write_run_record(
        out_path,
        agent=args.agent,
        genre=genre,
        no_agents=bool(getattr(args, "no_agents", False)),
        chat=bool(getattr(args, "chat", False)),
        inserted=any(op == "insert" for _ln, _why, op, _p in applied),
        moves=moves.records(applied),
        summary_added=any(
            op == "insert" and str(why).split(":")[0].strip() == "summary"
            for _ln, why, op, _p in applied),
        swaps=word_swaps(applied, merged),
        source=source_fingerprint(text),
        source_at_finish=_at_finish,
        frozen_lines=len(kv_frozen),
        document_lines=len(lines),
        jobs_planned=len(jobs),
        job_spans=[
            dict(zip(("lo", "hi"), source_span(
                j["lo"], j["hi"] or len(lines), fold_spans)),
                 specialist=j["specialist"], unit=j.get("unit", "?"), **a)
            for j, a in zip(jobs, _answered)],
        substituted_jobs=sum(1 for a in _answered if a["substituted"]),
        budget_floor=budget.matrix_seconds(len(jobs), JOBS,
                                           args.job_timeout),
        budget_seconds=run_budget.total,
        editable=_editable,
        editable_unfrozen=_editable_free,
        exempt=sorted(t for _, t in noise_drops),
        refused_summary=next(
            (txt for _ln, who, txt in refused
             if str(who).split(":")[0].strip() == "summary"), None)
        if summary_tried else None,
        incomplete=sorted(
            "{} lines {}-{} ({})".format(
                r["specialist"],
                *source_span(r["lo"], r["hi"] or len(lines), fold_spans),
                r.get("unit", "?"))
            for r in failed),
    )

    _tail0 = time.monotonic()
    _sent = _tail0 - _run0
    _vbuf = io.StringIO()
    _vargs = argparse.Namespace(
        original=args.file, edited=str(out_path), chat=args.chat,
        exempt=[t for _, t in noise_drops],
        freeze=getattr(args, "freeze", None),
        project=getattr(args, "project", None),
        searched=getattr(args, "searched", None),
        gates_file=getattr(args, "gates_file", None),
        verdict=not failed)
    with contextlib.redirect_stdout(_vbuf):
        rc = cmd_verify(_vargs)
    _tally = getattr(_vargs, "shape_tally", None)
    if _tally:
        _o, _n, _new, _kept = _tally
        _word = ("FAIL" if failed or _terminated or rc not in (0, 3)
                 else "PASS" if rc == 0 else "REVIEW")
        _bits = [f"{max(0, _o - _kept)} of {_o} shape{'' if _o == 1 else 's'} "
                 f"fixed, {_kept} carried over, {_new} new",
                 f"words {o_w} → {n_w} "
                 f"({(n_w - o_w) * 100 / max(o_w, 1):+.1f}%)"]
        if o_w and n_w > _aim and _dw:
            _bits.append(f"still {_over:.2f}x the length target")
        if failed:
            _bits.append(f"{len(failed)} span{'' if len(failed) == 1 else 's'} "
                         f"never edited")
        if _terminated:
            _bits.append("cut short by SIGTERM")
        print(f"\n{_word} — " + " · ".join(_bits))
    print("\n── verify ──" + (
        f"  ({len(failed)} span{'' if len(failed) == 1 else 's'} never "
        f"edited — everything below describes an INCOMPLETE file)"
        if failed else ""))
    sys.stdout.write(_vbuf.getvalue())
    if not failed and rc != 1:
        journal_path(out_path).unlink(missing_ok=True)
    if failed:
        _n = len(failed)
        print(f"\n{_n} span{'' if _n == 1 else 's'} "
              f"{'was' if _n == 1 else 'were'} never edited. The file is "
              f"incomplete.")
        try:
            _same = (Path(args.file).read_bytes()
                     == Path(out_path).read_bytes())
        except OSError:
            _same = False
        if _same:
            print(f"  and {Path(out_path).name} is BYTE-IDENTICAL to "
                  f"{Path(args.file).name}: nothing was edited at "
                  f"all. This is not a result. `verify` on this pair reads "
                  f"clean because it is comparing a file with itself.")
        _causes = defaultdict(int)
        for r in failed:
            _causes[error_digest(r["error"])] += 1
        for _cause, _n in sorted(_causes.items(), key=lambda kv: -kv[1]):
            print(f"  {_n} job{'' if _n == 1 else 's'} on: {_cause}")
        _found = {0: "On what was written, every token and claim survived.",
                  3: "On what was written, no token was lost, but verify "
                     "found something to read above.",
                  1: "Verify also found a break in what was written."}
        print(f"\nFAIL — the file is incomplete, so this run cannot be "
              f"accepted. {_found.get(rc, '')}".rstrip())
        _unsent = [r for r in failed if r.get("unsent")]
        _dead = [r for r in failed if not r.get("unsent")]
        print(budget.finish_advice(
            len(_unsent), len(_dead),
            ",".join(sorted({r["specialist"] for r in _dead})),
            len(applied), shlex.quote(out_path.name),
            journal_path(out_path).name,
            f"{shlex.quote(args.file)} {shlex.quote(str(out_path))}",
            unusable[0] if unusable else "",
            terminated=sum(1 for r in _unsent
                           if r.get("error") == budget.sigterm_reason())))
        print(tail_note(time.monotonic() - _tail0, args.timeout,
                        args.no_budget, sent=_sent))
        if _who_tail:
            print(_who_tail)
        if _terminated:
            print(_exit_line(143))
            return 143
        print(_exit_line(1))
        return 1

    print("\nNothing here checked this file for meaning. Every gate above "
          "matches text, so a reversed sentence would have passed them all.")
    if rc != 1 and not failed:
        _wrote = answering_backends(read_run_record(out_path))
        if _wrote:
            _candidates = [b for b in ("agy", "codex")
                           if not same_family(b, _wrote)]
        else:
            _candidates = (["agy", "codex"] if args.agent in ("codex", "claude")
                           else ["codex", "agy"])
        _out = shlex.quote(str(out_path))
        if not _candidates:
            print(f"\nread it for sense: {crosscheck_remedy(_wrote)}"
                  f"\nkeep all of it:  kill-verbosity accept "
                  f"{shlex.quote(args.file)} {_out}"
                  f"\nkeep none of it: delete {_out}. There "
                  f"is no third option — hand-picking edits is how the gates "
                  f"get bypassed.")
        else:
            _pref = _candidates[0]
            _alt = _candidates[1] if len(_candidates) > 1 else None
            _avail = local_availability()
            _pref_up = rung_available(_avail, _pref)
            _alt_up = rung_available(_avail, _alt) if _alt else None
            if _alt is None:
                reviewer = None if _pref_up is False else _pref
            elif _pref_up is False and _alt_up is True:
                reviewer = _alt
            elif _pref_up is False and _alt_up is False:
                reviewer = None
            else:
                reviewer = _pref
            if reviewer is None:
                _hedge = (" (neither candidate reviewer is installed — pass "
                          "--backend yourself)")
            else:
                _hedge = "" if _avail is not None else " (availability not checked)"
            _kv_backend = f"KV_BACKEND={reviewer} " if reviewer else ""
            print(f"\nread it for sense{_hedge}: {_kv_backend}"
                  f"kill-verbosity crosscheck {_out} {shlex.quote(args.file)}"
                  f"\nkeep all of it:  kill-verbosity accept "
                  f"{shlex.quote(args.file)} {_out}"
                  f"\nkeep none of it: delete {_out}. There "
                  f"is no third option — hand-picking edits is how the gates get "
                  f"bypassed.")
    print(tail_note(time.monotonic() - _tail0, args.timeout, args.no_budget,
                    sent=_sent))
    if _who_tail:
        print(_who_tail)
    if _terminated:
        print(_exit_line(143))
        return 143
    print(_exit_line(rc))
    return rc



SUMMARY_VERDICT_OWNER = {
    "buried": "structure",
    "declared": "summary", "marked": "summary", "unheaded": "summary",
    "refused": "summary",
    "verbatim": "summary", "headed": "summary",
    "missing": "summary", "thin": "summary", "inherited": "summary",
    "over": "summary",
}


def unowned_note(key, args):
    """`  ` or a sentence saying no run will act on this finding."""
    who = SUMMARY_VERDICT_OWNER.get(key)
    only = getattr(args, "only", None)
    if not who or not only:
        return ""
    if who in [n.strip() for n in only.split(",")]:
        return ""
    where = getattr(args, "project", None) or PROJECT_FILE
    return (f" — the '{who}' specialist is OFF in {where}, so no run will "
            f"write this. Enable it there, or do it by hand.")


def genre_evidence(g):
    """` (prose 141 of 178 body lines; reference 24, log 13)` - or `` when the
    mix is unavailable, which is what an older payload has.
    """
    mix = g.get("genre_mix")
    if not mix:
        return ""
    total = sum(mix.values())
    if not total:
        return ""
    mine = mix.get(g["genre"], 0)
    rest = sorted(((k, n) for k, n in mix.items() if k != g["genre"]),
                  key=lambda kv: -kv[1])
    tail = ("; " + ", ".join(f"{k} {n}" for k, n in rest[:3])) if rest else ""
    return f" ({g['genre']} {mine} of {total} body lines{tail})"


def select_genre(lines, headings, args):
    """Detect the genre and load its profile, unless the project named one."""
    genre = detect_genre(lines, headings)
    mix = genre_mix(lines, headings)
    total = sum(mix.values())
    named = getattr(args, "profile", None)
    if named and PROFILE_GENRE:
        if PROFILE_GENRE != genre:
            print(f"read as {PROFILE_GENRE} — named by profile "
                  f"{PROFILE_NAME}, detected {genre}.", file=sys.stderr)
        return PROFILE_GENRE, None
    if genre == "prose" and total:
        other = [(k, n) for k, n in mix.most_common() if k != "prose"]
        if other and other[0][1] / total >= 0.25:
            share = ", ".join(f"{k} {round(100 * n / total)}%"
                              for k, n in other[:3])
            print(f"mixed document — {share}. Read as prose, which relaxes "
                  f"nothing. Name a genre in {PROJECT_FILE} if one should "
                  f"win.", file=sys.stderr)
    if named:
        return genre, None
    pf = PROFILE_DIR / f"genre-{genre}.json"
    if not pf.is_file():
        return genre, None
    load_profile(str(pf))
    return genre, PROFILE_NAME


def apply_genre(genre, args):
    """Load the profile for a genre somebody else already decided."""
    if getattr(args, "profile", None):
        return None
    pf = PROFILE_DIR / f"genre-{genre}.json"
    if not pf.is_file():
        return None
    if PROFILE_NAME == pf.stem:
        return None
    load_profile(str(pf))
    return PROFILE_NAME


LOW_YIELD_SHARE = 0.05

_WHOLE_BLOCK_SHAPES = {"paragraph wall", "em-dash pressure",
                       "mixed list styles", "repeated list item"}


def _block_span(ln, prose):
    """The blank-line-delimited block `ln` sits in, as an inclusive (lo, hi)."""
    lo = hi = ln
    while lo > 1 and prose[lo - 2].strip():
        lo -= 1
    while hi < len(prose) and prose[hi].strip():
        hi += 1
    return lo, hi


def _block_unflaggable(ln, prose, frozen):
    """True only when EVERY line of `ln`'s block is unflaggable."""
    lo, hi = _block_span(ln, prose)
    return all(l in frozen for l in range(lo, hi + 1))


def _hit_unflaggable(ln, kind, prose, frozen):
    """True when this hit is unflaggable and should be dropped from the list."""
    if kind in _WHOLE_BLOCK_SHAPES:
        return _block_unflaggable(ln, prose, frozen)
    return ln in frozen


def pass_hits(prose, tables, headings, quotes, body, lines, chat):
    """Every hit `run` routes to a specialist, in `run`'s coordinates."""
    hits = find_shapes(prose, tables, headings, quotes, chat=chat)
    hits += [(ln, "em-dash pressure", f"{n} em dashes in this paragraph")
             for ln, n in em_dash_pressure(prose)]
    hits += [(ln + 1, "long sentence", f"{n_words(s)} words: {s[:60]}")
             for ln, s in sentences(list(enumerate(with_spans(prose, body))))
             if n_words(s) > LONG_SENTENCE]
    hits += [(ln, "paragraph wall",
              f"{n} sentences, {w} words — keep the claim and its strongest "
              f"support")
             for ln, n, w in wall_paragraphs(prose)]
    hits += [(ln, kind, detail) for ln, kind, detail in list_faults(prose, lines)]
    frozen = unflaggable(prose, headings)
    hits = [h for h in hits if not _hit_unflaggable(h[0], h[1], prose, frozen)]
    hits.sort()
    return hits


def yield_ceiling(hits, prose, tables, headings, quotes, lines, frozen):
    """The most words fixing these hits can remove: `{words, of, lines, low}`."""
    ok = editable_lines(prose, tables, headings, quotes, frozen)
    heads = sorted(h[0] + 1 for h in headings)
    end = body_end(lines)
    at = set()
    for ln, kind, _t in hits:
        if kind in _WHOLE_BLOCK_SHAPES:
            lo, hi = _block_span(ln, prose)
            at |= set(range(lo, hi + 1))
        elif owner_of(kind) == "planning":
            top = max((h for h in heads if h <= ln), default=None)
            span = section_span(headings, end, top) if top else None
            at |= set(range(span[0], span[1] + 1)) if span else {ln}
        else:
            at.add(ln)
    for d in without_lines(duplicates(prose), unflaggable(prose, headings)):
        at |= set(d["lines"])
    at &= ok
    words = sum(word_count(lines[l - 1]) for l in at if 0 < l <= len(lines))
    of = word_count("\n".join(lines))
    return {"words": words, "of": of, "lines": len(at),
            "low": words < LOW_YIELD_SHARE * of}


def yield_line(y):
    """One line, before any dispatch, saying what the run can land at most."""
    share = 100 * y["words"] / max(y["of"], 1)
    return (f"expected yield: at most {y['words']} of {y['of']} words "
            f"({share:.1f}%), the words on the {count(y['lines'], 'line')} "
            f"a dispatched candidate fires on or pulls in -- every routed "
            f"shape, long sentence, em-dash paragraph, wall and list fault "
            f"together, not only the headline's fault-shapes. An UPPER "
            f"BOUND on what fixing them can remove, not a prediction."
            + (f" Under {LOW_YIELD_SHARE:.0%}, a run is unlikely to land much: "
               f"consider not running it." if y["low"] else ""))


def realised_yield_note(src, text):
    """What the last real run on this file actually removed, or None."""
    out_path = Path(src).with_suffix(f".kv{Path(src).suffix}")
    if not out_path.is_file():
        return None
    state = record_state(out_path)
    if state != "ok":
        return (f"realised yield of the last run ({out_path.name}): its "
                f"record is {state}, so nothing here can say what it "
                f"actually removed.")
    record = read_run_record(out_path)
    if source_fingerprint(text) != record.get("source"):
        return (f"realised yield of the last run ({out_path.name}): the "
                f"input has changed since that run, so its realised figure "
                f"is not about the file being planned now.")
    try:
        out_text = out_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"realised yield of the last run ({out_path.name}): unreadable ({e})."
    before, after = word_count(text), word_count(out_text)
    removed = before - after
    share = 100 * removed / max(before, 1)
    when = time.strftime("%Y-%m-%d %H:%M:%S",
                         time.localtime(out_path.stat().st_mtime))
    return (f"realised yield of the last run ({out_path.name}, {when}): "
            f"{share:.1f}% ({removed} of {before} words) actually removed.")


def plan_yield(text, name, args):
    """`yield_ceiling` for `plan`, read the way `run` reads the file."""
    src = (text[:-1] if text.endswith("\n") else text).split("\n")
    lines, _spans = unwrap_source(src, freeze_barrier(args, src))
    body = "\n".join(lines)
    prose, headings, tables, quotes = mask(body, name)
    hit = getattr(args, "freeze", None)
    frozen = freeze_lines(lines, hit[0]) if hit else set()
    prose = blank_frozen(prose, frozen)
    hits = pass_hits(prose, tables, headings, quotes, body, lines, args.chat)
    return yield_ceiling(hits, prose, tables, headings, quotes, lines, frozen)


def dispatch_density(hits, words, n_jobs, agent, sending=True, avail_note=None):
    """What this pass is about to cost, against how much it has to find."""
    real = sum(1 for _l, k, _t in hits if k not in SYNTHETIC)
    _tag = f" ({avail_note})" if sending and avail_note else ""
    would = (f"dispatches {n_jobs} job{'' if n_jobs == 1 else 's'} against "
             f"{agent}{_tag}" if sending else
             f"would dispatch {n_jobs} job{'' if n_jobs == 1 else 's'}; "
             f"--no-agents sends none")
    return (f"{real} fault-shape{'' if real == 1 else 's'} in {words} words "
            f"({real * 1000 / max(words, 1):.1f} per 1000). This pass "
            f"{would}.")


def id_families_note(payload, full=True) -> str:
    """The `id_families` remedy, said ONCE, or ""."""
    kinds = Counter(s["kind"] for c in payload["chunks"] for s in c["shapes"])
    if not kinds.get("bare internal id"):
        return ""
    if VOCAB["id_families"] != DEFAULT_VOCAB["id_families"]:
        return ""
    n, plural = kinds["bare internal id"], kinds["bare internal id"] != 1
    if not full:
        return (f"the {n} `bare internal id` {'hits' if plural else 'hit'} "
                f"above are matched against this build's default id "
                f"families (--full for how to fix a wrong one).")
    return (f"the {n} `bare internal id` "
            f"{'hit' if not plural else 'hits'} above are "
            f"matched against this build's default id families. Which shapes "
            f"are ids is a per-tree fact: set `id_families` in a profile and "
            f"name it in .killverbosity.json (`{{\"profile\": \"./kv.json\"}}` "
            f"— a relative path resolves against that file). Gloss the id or "
            f"override the line if the vocabulary is right and the hit is not.")


def shape_census(payload):
    """One line: how many of each shape, and how dense the file is."""
    kinds = Counter(s["kind"] for c in payload["chunks"] for s in c["shapes"])
    long_n = sum(len(c["long_sentences"]) for c in payload["chunks"])
    emd_n = sum(len(c["em_dash_paragraphs"]) for c in payload["chunks"])
    wall_n = sum(len(c["wall_paragraphs"]) for c in payload["chunks"])
    words = payload["global_context"]["words"] or 1
    parts = ([f"long {long_n}"] if long_n else []) \
        + ([f"em-dash {emd_n}"] if emd_n else []) \
        + ([f"wall {wall_n}"] if wall_n else []) \
        + [f"{k} {n}" for k, n in kinds.most_common()]
    synth = Counter({k: n for k, n in kinds.items() if k in SYNTHETIC})
    other = sum(n for k, n in kinds.items() if k not in SYNTHETIC)
    out = [f"{n} {w}{'' if n == 1 else 's'}"
           for n, w in ((long_n, "length candidate"),
                        (emd_n, "em-dash paragraph"),
                        (wall_n, "paragraph wall")) if n] \
        + [f"{n} {k}{'' if n == 1 else 's'}" for k, n in synth.most_common()]
    named = (out[0] if len(out) == 1
             else ", ".join(out[:-1]) + f" and {out[-1]}" if out else "")
    left_out = long_n + emd_n + wall_n + sum(synth.values())
    n_counted = sum(1 for k, n in kinds.items() if k not in SYNTHETIC and n)
    scanned = payload["global_context"].get("scanned_words")
    if scanned == 0:
        return ("shapes: none scanned"
                f"\nno fault-shapes counted in {words} words: every line is "
                f"protected from editing, so nothing was scanned. This is not "
                f"a clean document, it is an unread one — a transcript's "
                f"speech and a fenced-code file both land here.")
    denom = scanned or words
    _prose_denom = bool(scanned and scanned != words)
    _denom_name = "prose words" if _prose_denom else "words"
    _total_rate = (f", {other * 1000 / max(words, 1):.1f} per 1000 of all "
                   f"{words} words"
                   if _prose_denom else "")
    return (f"shapes: {', '.join(parts) if parts else 'none'}"
            f"\n{other} fault-shape{'' if other == 1 else 's'} in {words} words"
            + (f", {scanned} of them prose" if scanned and scanned != words
               else "")
            + f" ({other * 1000 / denom:.1f} per 1000 {_denom_name} over the "
            f"{n_counted} counted kind{'' if n_counted == 1 else 's'}"
            f"{_total_rate}, "
            f"{left_out} candidate{'' if left_out == 1 else 's'} not counted)."
            + (f" The {named} "
               f"{'is' if left_out == 1 else 'are'} left out "
               f"of that count: each is a place to look, not a fault."
               if out else ""))


def cmd_plan(args):
    bad = not_markdown(Path(args.file))
    if bad:
        print(f"kill-verbosity: {bad}", file=sys.stderr)
        return 2
    text = Path(args.file).read_text(errors="replace")
    prose, headings, tables, quotes = mask(text, Path(args.file).name)
    _src = text.split("\n")
    kv_frozen = report_freeze(args, _src)
    prose = blank_frozen(prose, kv_frozen)
    if timed_but_not_transcript(headings):
        print("timestamp headings, none starting near zero: read as a SCHEDULE "
              "(agenda, runbook, rota) and left editable. A recording exported "
              "from the middle of a meeting looks identical from the headings "
              "alone — if this is speech, nothing here is protecting it.",
              file=sys.stderr)
    _weak_margin_paragraphs = 0
    if len(unwrap_source(_src)[0]) == len(_src):
        print(no_margin_notice(prose), file=sys.stderr)
        _weak_margin_paragraphs = _wrapping.multiline_paragraphs(prose)
    _gl = genre_lines(text, args)
    genre, loaded = select_genre(_gl, headings, args)
    spanned = with_spans(prose, text)
    inv = facts(text)
    chunks = chunk(prose, headings, tables=tables)
    hits = find_shapes(prose, tables, headings, quotes, chat=args.chat)
    dups = duplicates(prose, src=_src)
    incs = inconsistencies(text)
    frozen = unflaggable(prose, headings)
    dups = without_lines(dups, frozen)
    emd = [e for e in em_dash_pressure(prose) if not _block_unflaggable(e[0], prose, frozen)]
    walls = [w for w in wall_paragraphs(prose) if not _block_unflaggable(w[0], prose, frozen)]
    hits += [h for h in list_faults(prose, _src)
             if not _block_unflaggable(h[0], prose, frozen)]
    bad_tables = broken_tables(text)
    para_sents = {}
    _para_head = {}
    for _line, _plines in paragraphs(prose):
        _para_head[_line] = _plines[0]
        _base = _line - 1
        _ss = [(_base + _off + 1, s)
               for _off, s in sentences(list(enumerate(_plines)))]
        if _ss:
            para_sents[_line] = _ss
    _wall_lines = {_w[0] for _w in walls}
    _runs = [_r for _r in layout.label_runs([(_l, [_para_head[_l]])
                                             for _l in sorted(_para_head)])
             if any(_l in _wall_lines for _l in _r)]
    _listed = {_l for _r in _runs for _l in _r}
    walls = [_w for _w in walls if _w[0] not in _listed]

    seams = {}
    _label_lists = []
    for _l, _n, _w in walls:
        if _w <= threshold("wall_seam_words"):
            continue
        _pairs = para_sents.get(_l, [])
        _sents = [s for _sl, s in _pairs]
        _marks = layout.labelled(_sents)
        if len(_marks) >= 3:
            _label_lists.append((_pairs[_marks[0]][0], None,
                                 [" ".join(_sents[m].split()) for m in _marks]))
            continue
        if len(_marks) == 1 and _marks[0] > 0:
            _i, _score = _marks[0], None
        else:
            _i, _score = layout.seam(_sents)
        if _i is not None:
            seams[_l] = (_i, _score, " ".join(_sents[_i].split()),
                         _pairs[_i][0])
    lists = sorted([r for r in layout.list_runs(sorted(para_sents.items()))
                    if r[0] not in frozen]
                   + [r for r in _label_lists if r[0] not in frozen],
                   key=lambda r: r[0])
    walls = [w for w in walls if w[0] not in {r[0] for r in lists}]

    payload = {
        "file": str(args.file),
        "global_context": {
            "title": headings[0][2] if headings else Path(args.file).stem,
            "headings": [f"{'#' * h[1]} {h[2]}" for h in headings],
            "words": word_count(text),
            "scanned_words": sum(len(l.split()) for l in prose),
            "genre": genre,
            "genre_mix": dict(genre_mix(_gl, headings)),
            "profile": loaded or PROFILE_NAME,
            "fact_counts": {k: len(v) for k, v in sorted(inv.items())},
        },
        "chunks": [],
        "duplicates": dups,
        "inconsistencies": incs,
        "broken_tables": [{"line": l, "problem": p} for l, p in bad_tables],
        "editable_table_rows": editable_table_rows(tables, kv_frozen),
        "weak_margin_paragraphs": _weak_margin_paragraphs,
        "frozen_lines": len(kv_frozen),
        "opening_summary": None if args.chat else
                           opening_summary(headings, prose, word_count(text),
                                           text),
    }

    payload["yield_ceiling"] = (None if args.chat
                                else plan_yield(text, Path(args.file).name, args))

    breaks = [i + 1 for i, ln in enumerate(text.split("\n")) if not ln.strip()]

    for c in chunks:
        lo, hi = c["start"], c["end"]
        long_s = [{"line": ln + 1, "words": len(s.split()), "text": s[:150]}
                  for ln, s in sentences([(i, spanned[i]) for i, _ in c["lines"]])
                  if n_words(s) > LONG_SENTENCE and ln + 1 not in frozen]
        payload["chunks"].append({
            "n": c["n"], "title": c["title"], "lines": f"{lo}-{hi}",
            "spans": len(windows(lo, hi, breaks, words=_span_words(c))),
            "words": sum(len(ln.split()) for _, ln in c["lines"]),
            "shapes": [{"line": l, "kind": k, "text": t}
                       for l, k, t in hits if lo <= l <= hi],
            "long_sentences": long_s,
            "em_dash_paragraphs": [l for l, _ in emd if lo <= l <= hi],
            "wall_paragraphs": [dict({"line": l, "sentences": n, "words": w},
                                     **({"seam": {"sentence": seams[l][0],
                                                  "overlap": seams[l][1],
                                                  "text": seams[l][2][:150],
                                                  "line": seams[l][3]}}
                                        if l in seams else {}))
                                for l, n, w in walls if lo <= l <= hi],
            "prose_lists": [{"line": l, "shape": k, "sentences": len(ss),
                             "text": [s[:100] for s in ss]}
                            for l, k, ss in lists if lo <= l <= hi],
            "numbered_runs": [{"line": r[0], "items": len(r), "last": r[-1]}
                              for r in _runs if lo <= r[0] <= hi],
            "duplicate_lines": sorted({l for d in dups for l in d["lines"]
                                       if lo <= l <= hi}),
        })

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    g = payload["global_context"]
    print(f"{g['title']}  —  {count(g['words'], 'word')}, "
          f"{count(len(payload['chunks']), 'chunk')}"
          f"  ·  read as {g['genre']}{genre_evidence(g)}"
          + (f", profile {g['profile']}" if g['profile'] != "default" else ""))
    _full = bool(getattr(args, "full", False))
    _cfg = config_note(getattr(args, "project", None),
                       getattr(args, "searched", None))
    if _cfg:
        print(_cfg, file=sys.stderr)
    _caveat = table_caveat(tables, kv_frozen)
    if _caveat:
        print(_caveat if _full else table_caveat(tables, kv_frozen, full=False))
    _status_note = status_table_note(_src)
    if _status_note:
        print(_status_note if _full else status_table_note(_src, full=False))
    for _code, _miss in blind_shapes().items():
        print(f"{_code} has no words for {', '.join(_miss)} — those checks do "
              f"not read {_code} text.")
    print(f"If that is wrong, the rules are wrong too. Name the right one "
          f"in {PROJECT_FILE}.")
    if g["fact_counts"]:
        print("facts to preserve: "
              + ", ".join(f"{k} {v}" for k, v in g["fact_counts"].items()))
    if args.chat and g["words"] > CHAT_MAX_WORDS:
        print(f"chat length: {g['words']} words. Past {CHAT_MAX_WORDS} a reply "
              f"reads as a document. Lead with the one point, send the rest "
              f"only if asked.")
    verdict = summary_verdict(payload["opening_summary"])
    if verdict:
        _vtext = verdict[1] if _full else summary_headline(verdict[1])
        print(f"opening summary: {_vtext}{unowned_note(verdict[0], args)}")
    print(shape_census(payload))
    if payload["yield_ceiling"] is not None:
        print(yield_line(payload["yield_ceiling"]))
        _realised = realised_yield_note(Path(args.file), text)
        if _realised:
            print(_realised)
    _idfam = id_families_note(payload)
    if _idfam:
        print(_idfam if _full else id_families_note(payload, full=False))
    _folded_n = _folded_shape_count(text, Path(args.file).name, args.chat,
                                    -1)
    _this_n = _census_n(payload)
    if _folded_n >= 0 and _folded_n != _this_n:
        if _folded_n > _this_n:
            print(f"this file hard-wraps. `run` folds it into paragraphs "
                  f"first and counts {_folded_n} there, "
                  f"{_folded_n - _this_n} more: folding reveals a shape "
                  f"split across two lines that this list cannot see.")
        else:
            print(f"this file hard-wraps. `run` folds it into paragraphs "
                  f"first and counts {_folded_n} there, "
                  f"{_this_n - _folded_n} fewer: folding also joins short "
                  f"lines into one paragraph, which can merge two shapes "
                  f"this list counted separately into one.")
    total = 0
    quiet = []
    if any(c["wall_paragraphs"] for c in payload["chunks"]):
        print("\nwall: keep the claim and its strongest support.")
    for c in payload["chunks"]:
        n = (len(c["shapes"]) + len(c["long_sentences"])
             + len(c["em_dash_paragraphs"]) + len(c["wall_paragraphs"])
             + len(c["prose_lists"]) + len(c["numbered_runs"]))
        total += n
        flag = "" if n else "   (nothing found)"
        big = c["words"] > 1500
        if big:
            flag += (f"   [{c['words']}w — split into {c['spans']} for "
                     f"dispatch]" if c["spans"] > 1 else
                     f"   [{c['words']}w in one span]")
        if not n and not big:
            quiet.append(c["n"])
            continue
        print(f"\n── chunk {c['n']}  lines {c['lines']}  ·  {c['title']}{flag}")
        _seen = Counter()
        for s in c["shapes"]:
            _key = (s["line"], s["text"])
            print(f"   {s['line']:>5}  {s['kind']:<18} "
                  f"{unmask.in_context(_src, prose, s['line'], s['text'], nth=_seen[_key], abbr=ABBR)}")
            _seen[_key] += 1
        for s in c["long_sentences"]:
            said = unmask.as_written(_src, prose, s["line"], s["text"])
            print(f"   {s['line']:>5}  "
                  f"{'long (' + str(s['words']) + 'w)':<18} "
                  f"{unmask.quote(said, 90)}")
        if c["em_dash_paragraphs"]:
            _em = c["em_dash_paragraphs"]
            print(f"   {_em[0]:>5}  {'em-dash cluster':<18} "
                  f"{len(_em)} paragraph{'' if len(_em) == 1 else 's'}: "
                  f"{', '.join(str(l) for l in _em[:top(12)])}"
                  + (f", … and {len(_em) - top(12)} more"
                     if len(_em) > top(12) else ""))
        for s_ in c["wall_paragraphs"]:
            print(f"   {s_['line']:>5}  "
                  f"{'wall (' + str(s_['sentences']) + ' sent)':<18} "
                  f"{s_['words']}w")
            if s_.get("seam"):
                _sm = s_["seam"]
                print(f"   {_sm['line']:>5}  {'':<18} "
                      f"subject changes here (sentence "
                      f"{_sm['sentence'] + 1}) — a sub-heading splits it: "
                      f"{snip(_sm['text'])!r}")
        for l_ in c["prose_lists"]:
            _how = (f"all opening {l_['shape']!r}" if l_["shape"]
                    else "each with a bold label")
            print(f"   {l_['line']:>5}  {'list as prose':<18} "
                  f"{l_['sentences']} sentences {_how} — reads as bullets")
        for r_ in c["numbered_runs"]:
            print(f"   {r_['line']:>5}  {'numbered list':<18} "
                  f"{r_['items']} entries through line {r_['last']} — "
                  f"list items, not walls")
    if quiet:
        _quiet_n = set(quiet)
        _qw = sum(len(prose[i - 1].split())
                  for c in chunks if c["n"] in _quiet_n
                  for i in range(c["start"], c["end"] + 1))
        _tw = payload["global_context"]["scanned_words"] or 1
        print(f"\n── {len(quiet)} chunk{'' if len(quiet) == 1 else 's'} found "
              f"nothing: {number_spans(quiet)}")
        if _qw:
            print(f"   {_qw} of {_tw} prose words ({100 * _qw / _tw:.0f}%). No shape "
                  f"fired there, so no section specialist was given those "
                  + ("lines. `chat` reads the whole message and may still "
                     "rewrite them."
                     if args.chat else
                     "lines and nothing was asked to shorten them. `structure` "
                     "may move a section and `summary` may write one; neither "
                     "rewords a paragraph. Read them yourself, or accept "
                     "them."))
        _quiet_set = set(quiet)
        _by_n = {qc["n"]: qc for qc in payload["chunks"] if qc["n"] in _quiet_set}
        for qn in quiet:
            qc = _by_n[qn]
            print(f"   chunk {qc['n']:>3}  lines {qc['lines']}  ·  "
                  f"{qc['title']}")
    if dups:
        _body, _restated = [], []
        for d in dups:
            (_restated if restates_a_summary(d, headings) else _body).append(d)
        print(f"\n── repeated text  ({len(dups)} "
              f"cluster{'' if len(dups) == 1 else 's'}"
              + (f", {len(_body)} body-to-body · {len(_restated)} restating a "
                 f"summary or cross-check section" if _restated else "")
              + ")")
        for d, _rs in ([(d, False) for d in _body]
                       + [(d, True) for d in _restated])[:10]:
            tag = "  · parallel list" if parallel_list(d, prose) else ""
            tag += "  · restates a summary section" if _rs else ""
            print(f"   lines {d['lines']}  {d['words']}w  "
                  f"{unmask.quote(d.get('said') or d['text'], 80)}{tag}")
    if incs:
        print(f"\n── inconsistencies  ({len(incs)})")
        def _at(i, k):
            ln = (i.get("lines") or {}).get(k)
            return f"{k} (L{ln})" if ln else k
        for i in incs[:12]:
            print("   " + (
                f"term: {' / '.join(_at(i, f) for f in i['forms'])}"
                if i["kind"] == "term"
                else f"number {i['value']} with units "
                     f"{', '.join(_at(i, u) for u in i['units'])}"))
    if bad_tables:
        print(f"\n── broken tables  ({len(bad_tables)})  ·  already broken in "
              f"this file, not something a pass will cause")
        for l, p in bad_tables[:12]:
            print(f"   {l:>5}  {p}")
    print(f"\n{count(total + len(dups) + len(incs) + len(bad_tables), 'candidate')}. "
          f"Read every one before "
          f"touching it: a match is text, not meaning.\nQuoted examples, precise "
          f"technical names and credited people are not hits.")
    return 0


def _claim_rule_rx():
    words = [w for s in RULE_GATE_SHAPES for w in words_for(s)]
    if not words:
        return re.compile(r"(?!)")
    return re.compile(rf"\b(?:{alt(words)})\b", re.I)


def _advice_rx():
    words = words_for("advice word")
    if not words:
        return re.compile(r"(?!)")
    return re.compile(rf"\b(?:{alt(words)})\b", re.I)


def _recommendation_rx():
    """A sentence that opens on a corrective imperative."""
    words = words_for("recommendation verb")
    if not words:
        return re.compile(r"(?!)")
    rel = r"that|which|who|whose|whom"
    fin = (r"is|are|was|were|be|been|being|has|have|had|does|do|did"
           r"|will|would|can|could|shall|should|may|might|must")
    dash = r"\-‐-―"
    hard = r"\-‐‑‒"
    verb = rf"(?<![{hard}])\b(?:{fin})(?:n['’]t)?\b(?![{hard}])"
    plain = (rf"(?:\((?:[^()]|\([^()]*\))*\)|(?!{verb})(?!\b(?:{rel})\b)"
             rf"(?![,;]\s*\b(?:{rel})\b)[^(])*?")
    mid = (r"not|never|also|already|still|just|always|then|now|again"
           r"|soon|and|or|\w+ly")
    run = rf"{verb}(?:\s+(?:(?:{mid})\s+)?{verb})*"
    gap = rf"{plain}(?:\b(?:{rel})\b{plain}{run}{plain})*"
    hold = (rf"(?:stop|keep|hold|pause|block)\b(?!['’]s|[{hard}.(])"
            rf"{gap}\b(?:until|before)\b")
    return re.compile(rf"^[\s>*_`#•‣◦+]*(?:[{dash}]+\s+)?[\s>*_`#]*"
                      rf"(?:\d+[.)]\s*)?(?:\[[ xX]\]\s*)?"
                      rf"[\s*_`]*(?:please\s+)?"
                      rf"(?:(?:{alt(words)})\b(?!['’]s|[{hard}.(])(?=[^\w]*\w)"
                      rf"|{hold})",
                      re.I)


CLAIM_RULE = _claim_rule_rx()
RECOMMENDATION = _recommendation_rx()
ADVICE = _advice_rx()
_STATUS_SUPERSEDED = re.compile(
    r"\b(?:supersed(?:ed|es|ing)|deprecat(?:ed|es|ing)|retired|obsolete[d]?"
    r"|retract(?:ed|s|ing)?|withdraw(?:n|s|ing)?"
    r"|no longer (?:valid|current|applies|applicable|recommended|in effect))"
    r"\b", re.I)


def superseded_lines(prose):
    """1-based lines a supersede/retract/withdraw marker protects, the same
    way `keep_lines` protects a wrapped `kv:keep` paragraph.
    """
    out = set()
    for first, last, sent in sentence_spans(list(enumerate(prose, 1))):
        if not _STATUS_SUPERSEDED.search(sent):
            continue
        marker_from = next(
            (i for i in range(first, last + 1)
             if _STATUS_SUPERSEDED.search(prose[i - 1])), first)
        out.update(range(marker_from, last + 1))
    return out
CLAIM_KEPT = THRESHOLDS["claim_kept"]

MEANING_GAP = (
    "  Meaning is not checked here: a sentence whose main verb or stated\n"
    "  cause changed, or that now says the opposite, passes everything above.\n"
    "  Run `crosscheck` before `accept`.")

PASS_GAP = (
    "  Compared: protected tokens, rule sentences, shapes, headings, links,\n"
    "  credited names, counts. Every one of those matches text. A sentence\n"
    "  carrying no protected token and no rule word — \"Rollback is manual.\" —\n"
    "  can be deleted with all of them silent, and a changed main verb or cause\n"
    "  is not compared at all. Read the diff for meaning, or run crosscheck.")

_EXIT_MEANINGS = {
    0: "pass -- nothing here needs fixing, or there was nothing to do",
    1: "broken -- a rule, token or claim did not survive, or the file is "
       "incomplete",
    2: "bad input -- nothing ran",
    3: "hits remain, nothing broke",
    4: "forced -- a gate was overridden and the write landed anyway",
    5: "not checked -- the reviewer could not run; the document was not "
       "judged",
    6: "all substituted -- every job answered by a backend other than the "
       "--agent you named; nothing was written. --any-agent accepts it",
    143: "terminated by SIGTERM -- the report above covers what had landed",
}


def _exit_line(code):
    """`exit N: <what N means>`, the last line a run/verify/crosscheck prints."""
    return f"exit {code}: " + _EXIT_MEANINGS.get(
        code, "the backend's own exit status, not one of this tool's codes")


def with_table_text(prose, tables):
    """The prose stream with each table row's cell text put back on its line."""
    out = list(prose)
    for ln, cells in tables:
        if 1 <= ln <= len(out):
            out[ln - 1] = cells
    return out


def section_spans(heads, lines):
    """Body line span of each section, one per section, keyed by heading text."""
    out, marks = {}, [(h[0], h[2].strip()) for h in heads if h[2].strip()]
    for i, (ln, txt) in enumerate(marks):
        end = marks[i + 1][0] - 1 if i + 1 < len(marks) else len(lines)
        out.setdefault(txt, []).append((ln, end))
    return out


def section_bodies(heads, lines):
    """The content words under each heading, one set per section, keyed by text."""
    out = {}
    for txt, spans in section_spans(heads, lines).items():
        for ln, end in spans:
            body = " ".join(lines[ln:end])
            out.setdefault(txt, []).append(
                {w for w in (_word(x) for x in body.split())
                 if len(w) >= 4 and not _DANGLES.search(w)})
    return out


_HEADING_GRAMMAR = frozenset("""
    the and for with from into over under than that this these those its
    their our your all any not but when while how why what which who via
    are was were been has have had will would can could should about
""".split())


def _rescue_by_body(renames, gone, o, n, o_body, n_body):
    """Pair a heading that was renamed *and* moved in the same run."""
    o_text = Counter(t for _l, t in o)
    o_level = {t: lvl for lvl, t in o}

    def bodies(m, k):
        v = m.get(k) or [set()]
        return [v] if isinstance(v, (set, frozenset)) else v

    def shared_body(was, txt):
        return max((_overlap(mine, theirs)
                    for mine in bodies(o_body, was)
                    for theirs in bodies(n_body, txt)), default=0.0)

    def _overlap(mine, theirs):
        both = mine & theirs
        return (len(both) / max(1, len(mine), len(theirs))
                if len(both) >= 3 else 0.0)

    def kept_whole(was, txt):
        """Is `was`'s body inside `txt`'s, and are the two alone in that."""
        mine = [b for b in bodies(o_body, was) if b]
        if not mine:
            return False
        holds = [t for t in n_body
                 if any(m <= s for m in mine for s in bodies(n_body, t) if s)]
        if holds != [txt]:
            return False
        claims = [w for w in o_body
                  if any(b <= s for b in bodies(o_body, w) if b
                         for s in bodies(n_body, txt) if s)]
        return claims == [was]

    solid, doubtful = [], []
    for pair in renames:
        (solid if shared_body(pair[0], pair[1]) >= 0.5
         else doubtful).append(pair)
    paired = {now for _was, now, _slot in solid}
    free = [(slot, lvl, txt) for slot, (lvl, txt) in enumerate(n)
            if not o_text[txt] and txt not in paired]
    kept, rescued = [], []
    for was in gone + [p[0] for p in doubtful]:
        best, score = None, 0.0
        for cand in free:
            _slot, lvl, txt = cand
            if lvl != o_level.get(was):
                continue
            overlap = shared_body(was, txt)
            if overlap < 0.5 and kept_whole(was, txt):
                overlap = 0.5
            if overlap > score:
                best, score = cand, overlap
        if best and score >= 0.5:
            free.remove(best)
            rescued.append((was, best[2], best[0]))
        else:
            kept.append(was)
    def shared_word(a, b):
        """Do the two headings have a real word in common."""
        def words(s):
            return {w for w in re.findall(r"[a-z]{3,}", s.lower())
                    if w not in _HEADING_GRAMMAR}

        return bool(words(a) & words(b))

    taken = {now for _was, now, _slot in solid + rescued}
    still = set(kept)
    back = [p for p in doubtful if p[0] in still and p[1] not in taken
            and shared_word(p[0], p[1])]
    for pair in back:
        kept.remove(pair[0])
    return solid + rescued + back, kept


def heading_moves(o_heads, n_heads, o_body=None, n_body=None):
    """Split "not in the edit" into renames and real deletions."""
    pairs, gone = heading_pairs(o_heads, n_heads, o_body, n_body)
    return [(was, now) for was, now, _slot in pairs], gone


def heading_pairs(o_heads, n_heads, o_body=None, n_body=None):
    """`heading_moves` with the slot each rename landed in."""
    o = [(h[1], h[2].strip()) for h in o_heads if h[2].strip()]
    n = [(h[1], h[2].strip()) for h in n_heads if h[2].strip()]
    o_have = Counter(t for _l, t in o)
    n_have = Counter(t for _l, t in n)
    ops = difflib.SequenceMatcher(None, o, n, autojunk=False).get_opcodes()
    for tag, i1, i2, _j1, _j2 in ops:
        if tag == "equal":
            for _l, t in o[i1:i2]:
                o_have[t] -= 1
                n_have[t] -= 1
    renames, gone = [], []
    for tag, i1, i2, j1, j2 in ops:
        if tag in ("equal", "insert"):
            continue
        old = []
        for e in o[i1:i2]:
            if n_have[e[1]] > 0:
                n_have[e[1]] -= 1
            else:
                old.append(e)
        new = []
        if tag == "replace":
            for k, e in enumerate(n[j1:j2]):
                if o_have[e[1]] > 0:
                    o_have[e[1]] -= 1
                else:
                    new.append((j1 + k, e))
        pending = []
        for k, (lvl, txt) in enumerate(old):
            if k < len(new) and new[k][1][0] == lvl:
                slot, (_l, new_txt) = new[k]
                renames.append((txt, new_txt, slot))
                new[k] = None
            else:
                pending.append((lvl, txt))
        left = [e for e in new if e is not None]
        for lvl, txt in pending:
            hit = next((i for i, (_s, e) in enumerate(left) if e[0] == lvl),
                       None)
            if hit is None:
                gone.append(txt)
            else:
                slot, (_l, new_txt) = left.pop(hit)
                renames.append((txt, new_txt, slot))
    if (gone or renames) and o_body and n_body:
        renames, gone = _rescue_by_body(renames, gone, o, n, o_body, n_body)
    return renames, gone


def inbound_anchors(doc, heading):
    """Files in the same tree holding a `](#slug)` link to this heading."""
    slug = re.sub(r"[^a-z0-9\s-]", "", heading.lower()).strip()
    slug = re.sub(r"\s+", "-", slug)
    if not slug:
        return []
    out, target = [], Path(doc).resolve()
    root = Path(doc).parent
    for p in sorted(list(root.glob("*.md")) + list(root.glob("*/*.md"))):
        if p.resolve() == target:
            continue
        try:
            text = p.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.finditer(r"\]\(\s*(<[^>]*>|[^)\s]+)", text):
            path, _, frag = m.group(1).strip("<>").partition("#")
            if frag != slug or not path:
                continue
            try:
                if (p.parent / path).resolve() == target:
                    out.append(str(p.relative_to(root)))
                    break
            except (OSError, ValueError):
                continue
    return out


def untouched_lines(o_lines, n_lines):
    """1-based original line numbers the edit left byte-identical."""
    n_count, o_count = Counter(n_lines), Counter(o_lines)
    return {i + 1 for i, l in enumerate(o_lines)
            if l.strip() and o_count[l] == 1 and n_count[l] >= 1}


def section_lines(heads, starts, last):
    """Every 1-based line under each heading in `starts`, the heading included."""
    hs = sorted((h[0] + 1, h[1]) for h in heads)
    out = set()
    for i, (at, depth) in enumerate(hs):
        if at not in starts:
            continue
        end = next((nxt - 1 for nxt, d in hs[i + 1:] if d <= depth), last)
        out |= set(range(at, end + 1))
    return out


def section_owner(heads):
    """A function from 1-based line to the heading text that owns it."""
    hs = sorted((h[0] + 1, h[2].strip()) for h in heads)

    def owner(ln):
        who = ""
        for at, txt in hs:
            if at > ln:
                break
            who = txt
        return who.lower()
    return owner


_SIGN_OFF_WORD = r"unclear|niejasne"
_SIGN_OFF_INVITE = (
    r"let me know|let us know|reach out|get in touch|"
    r"feel free to (?:ask|reach out)|happy to (?:answer|help)|"
    r"(?:any|more) questions|"
    r"daj(?:cie)? znać|w razie pytań|odezwij(?:cie)? się|"
    r"chętnie (?:odpowiem|pomogę)|śmiało pytaj(?:cie)?|"
    r"pytaj(?:cie)? śmiało|służę pomocą"
)
SIGN_OFF_UNCLEAR = re.compile(
    rf"\b(?:{_SIGN_OFF_INVITE})\b[^.!?]{{0,80}}?\b(?P<after>{_SIGN_OFF_WORD})\b"
    rf"|\b(?P<before>{_SIGN_OFF_WORD})\b[^.!?]{{0,20}}?\b(?:{_SIGN_OFF_INVITE})\b",
    re.I)


def _mute_sign_off(s):
    """Blank the uncertainty word where it sits inside a contact invitation."""
    def cut(m):
        g = "after" if m.group("after") else "before"
        at, end = m.start(g) - m.start(), m.end(g) - m.start()
        whole = m.group(0)
        return whole[:at] + " " * (end - at) + whole[end:]

    return SIGN_OFF_UNCLEAR.sub(cut, s)


def rule_strength(s):
    """How hard a sentence tells the reader to do something. 2, 1 or 0."""
    scan = _mute_sign_off(s)
    if (CLAIM_RULE.search(scan) or RECOMMENDATION.match(s)
            or _STATUS_SUPERSEDED.search(scan)):
        return 2
    return 1 if ADVICE.search(scan) else 0


def asked_verbs(s):
    """The verbs this sentence asks for, whatever grammar it asks in."""
    forms, nominal = set(), set()
    m = re.search(r"\bplease\s+([a-z][a-z-]{2,})", s, re.I)
    if m:
        forms |= inflect.grow(m.group(1).lower())
    m = re.search(r"\b(?:must|shall|should|ought)\s+"
                  r"(?:(?:remember|ensure|try|be\s+sure|be\s+careful|"
                  r"be\s+certain|take\s+care|make\s+sure|not\s+forget)"
                  r"\s+)?to\s+([a-z][a-z-]{2,})", s, re.I)
    if m:
        forms |= inflect.grow(m.group(1).lower())
    low = s.lower()
    for w in re.findall(r"[a-z][a-z-]{4,}", low):
        nominal |= inflect.verbs_from_noun(w)
        for base in inflect.noun_stems(w):
            nominal |= inflect.verbs_from_noun(base)
    for g in re.findall(r"\b(?:the|a|an|any|each|its|this|that)\s+([a-z]+ing)\b",
                        low):
        nominal |= inflect.verb_stems(g)
    was_written = set(re.findall(r"[a-z][a-z-]*", low))
    for v in nominal:
        if len(v) > 2:
            forms |= inflect.grow(v) - was_written
    return forms


CLAIM_WINDOW = 3
CLAIM_WINDOW_OVERLAP = 0.34

_TERM_CODE = re.compile(r"`([^`]+)`")
_TERM_WORD = re.compile(r"[A-Za-z0-9_./#-]+")
_POINTER = re.compile(r"#?\d+\.?$")


def protected_terms(s):
    """Code spans, dotted or underscored names, numbers and acronyms, unmasked."""
    out = set()
    for c in _TERM_CODE.findall(s):
        out |= {w.lower().strip(".,;:()") for w in _TERM_WORD.findall(c)
                if len(w) > 2}
    for w in _TERM_WORD.findall(_TERM_CODE.sub(" ", s)):
        w = w.strip(".,;:()")
        if (len(w) > 2 or (len(w) == 2 and w.isdigit())) and (
                "_" in w or "/" in w or "." in w or w.isupper()
                or any(ch.isdigit() for ch in w)):
            out.add(w.lower())
    return {t for t in out if t}


def still_said(thinned, n_prose, n_src, keys, n_rows=()):
    """Entries of `thinned` whose content is in the edited file, read unmasked."""
    spans = sentence_spans(list(enumerate(n_prose, 1)), n_rows)
    text = []
    for a, b, s in spans:
        try:
            text.append(unmask.joined(n_src, n_prose, a, b, s))
        except Exception:
            text.append(s)
    terms = [protected_terms(t) for t in text]
    words = [keys(t) for t in text]
    out = set()
    for pos, (ln, s) in enumerate(thinned):
        want, mine = protected_terms(s), keys(s)
        _solid = {w for w in want if not _POINTER.match(w)}
        if _solid:
            want = _solid
        if not mine:
            continue
        if not want:
            continue
        for i in range(len(text)):
            hit = False
            for w in range(1, CLAIM_WINDOW + 1):
                if i + w > len(text):
                    break
                have = set().union(*terms[i:i + w])
                if not want <= have:
                    continue
                seen = set().union(*words[i:i + w])
                if len(mine & seen) / len(mine) >= CLAIM_WINDOW_OVERLAP:
                    hit = True
                    break
            if hit:
                out.add(pos)
                break
    return out


def claim_words(s):
    """The content words a sentence is judged on."""
    return {w for w in (_word(x) for x in _MD_LINK.sub(r"\1 \2", s).split())
            if len(w) >= 4 and not _DANGLES.search(w)}


def _sentence_norm(s):
    return " ".join(s.split()).rstrip(" .!?;:").lower()


def tail_cut(orig, edited, in_row=False):
    """The clause `edited` cut out of `orig`, or None. From the END, unless
    `in_row`, where a trailing run may survive it.
    """
    o, e = _sentence_norm(orig), _sentence_norm(edited)
    if not e or o == e:
        return None
    p = 0
    while p < min(len(e), len(o)) and o[p] == e[p]:
        p += 1
    tail = 0
    if in_row:
        while (tail < min(len(e) - p, len(o) - p)
               and o[len(o) - 1 - tail] == e[len(e) - 1 - tail]):
            tail += 1
    swap = 0
    if (p + tail != len(e) and p + 1 + tail == len(e)
            and e[p:p + 1] in (".", "!", "?")):
        swap = 1
    if p + swap + tail != len(e):
        return None
    end = len(o) - tail
    if p and o[p - 1].isalnum() and o[p:p + 1].isalnum():
        return None
    if tail and o[end - 1:end].isalnum() and o[end:end + 1].isalnum():
        return None
    cut = o[p:end].strip(" ,;:.\u2014\u2013-")
    return cut if len(cut.split()) >= 2 else None


def cut_where(orig, cut, in_row):
    """The words for WHERE a cut fell, or `""` for the ordinary end cut."""
    if not in_row:
        return ""
    o = _sentence_norm(orig)
    at = o.find(cut)
    if at < 0:
        return " (in a table row)"
    if at == 0:
        return " (from the FRONT of a table row, not the end)"
    if at + len(cut) < len(o.rstrip(" ,;:.\u2014\u2013-")):
        return " (from the MIDDLE of a table row, not the end)"
    return " (from a table row)"


def tails_cut(o_prose, n_prose, o_rows=(), n_rows=()):
    """Sentences that kept their opening and lost their tail, and nothing else
    reports them.
    """
    hits = []
    _rows = set(o_rows)
    _doc_kept = claim_words(" ".join(n_prose))
    news = [(s, _sentence_norm(s)) for _a, _b, s in
            sentence_spans(list(enumerate(n_prose, 1)), n_rows)]
    for ln, _end, s in sentence_spans(list(enumerate(o_prose, 1)), o_rows):
        words = claim_words(s)
        if not words:
            continue
        for cand, cnorm in news:
            if not cnorm:
                continue
            cut = tail_cut(s, cand, in_row=ln in _rows)
            if cut is None:
                continue
            kept = claim_words(cand)
            if not (claim_words(cut) - _doc_kept):
                continue
            if inflect.share(words, inflect.spread(kept)) < CLAIM_KEPT:
                break
            hits.append((ln, s, cand, cut))
            break
    return hits


def claims_lost(o_prose, n_prose, untouched=(), o_heads=(), n_heads=(),
                o_hits=(), o_src=None, n_src=None, o_rows=(), n_rows=()):
    """Original sentences whose content is nowhere in the edit."""
    keys = claim_words

    n_owner = section_owner(n_heads)
    o_owner = section_owner(o_heads)
    _pairs, _absorbed = heading_moves(
        o_heads, n_heads,
        section_bodies(o_heads, o_prose),
        section_bodies(n_heads, n_prose))
    renamed = {was.strip().lower(): now.strip().lower()
               for was, now in _pairs}
    _order = [h[2].strip().lower() for h in sorted(o_heads) if h[2].strip()]
    _gone = {h.strip().lower() for h in _absorbed}
    absorbed_into, _above = {}, ""
    for _txt in _order:
        if _txt in _gone:
            absorbed_into[_txt] = _above
        else:
            _above = _txt
    _was_named = {h[2].strip().lower() for h in o_heads}
    fresh = {h[2].strip().lower() for h in n_heads
             if h[2].strip().lower() not in _was_named
             and h[2].strip().lower() not in renamed.values()}
    shaped = {}
    for ln, cat, _t in o_hits:
        shaped.setdefault(ln, set()).add(cat)
    all_padding, ordered_out = set(), set()
    if shaped:
        for _a, _b, _s in sentence_spans(list(enumerate(o_prose, 1)), o_rows):
            cats = set().union(*(shaped.get(i, set())
                                 for i in range(_a, _b + 1)))
            if cats and cats <= NEVER_A_RULE:
                all_padding.add(_a)
                if cats & DELETION_ORDERED:
                    ordered_out.add(_a)
    kept = []
    for _a, _b, s in sentence_spans(list(enumerate(n_prose, 1)), n_rows):
        k = keys(s)
        if k:
            kept.append((k, rule_strength(s), n_owner(_a), s, inflect.spread(k)))
    spans = [(*x, None) for x in kept] + [
        (a | b, max(ar, br), ao, f"{at} {bt}", af | bf, (af, bf))
        for (a, ar, ao, at, af), (b, br, _bo, bt, bf) in zip(kept, kept[1:])]

    def share(k, f, halves):
        """Overlap, but a pair only counts when both halves carry the claim."""
        sc = inflect.share(k, f)
        if halves and sc and min(inflect.share(k, halves[0]),
                                 inflect.share(k, halves[1])) < 0.4 * sc:
            return 0.0
        return sc

    where = {}
    for _k, _r, o, t, _f in kept:
        where.setdefault(t, set()).add(o)

    gone, weakened, thinned, relocated = [], [], [], []
    untouched = set(untouched)
    for ln, _end, s in sentence_spans(list(enumerate(o_prose, 1)), o_rows):
        if untouched and all(i in untouched for i in range(ln, _end + 1)):
            here = o_owner(ln)
            still = {here, renamed.get(here, here),
                     absorbed_into.get(here, here)} | fresh
            if (o_heads and n_heads and here and rule_strength(s)
                    and s in where and not where[s] & still):
                relocated.append((ln, s, here))
            continue
        k = keys(s)
        was = rule_strength(s)
        rule = bool(was)
        if len(k) < 3 and not rule:
            continue
        scored = [(share(k, f, h), o) for _n, _r, o, _t, f, h in spans]
        best = max((sc for sc, _o in scored), default=0.0)
        ask = asked_verbs(s)
        ok = inflect.spread(k)

        def rev_share(n):
            """`share`, reversed: how much of survivor `n` came from `ok`."""
            if inflect.overlap(n, ok) < rescue.LEAST_SHARED:
                return 0.0
            return inflect.share(n, ok)

        rev = [(rev_share(n), r, t, o) for n, r, o, t, _f, _h in spans]
        as_rule = max((sc for sc, r, t, _o in rev
                       if r >= was or any(re.search(rf"\b{re.escape(v)}\b", t, re.I)
                                          for v in ask)),
                      default=0.0)
        bar = 1.0 if len(k) < 3 else CLAIM_KEPT
        if (as_rule if rule else best) >= bar:
            here = o_owner(ln)
            still = {here, renamed.get(here, here),
                     absorbed_into.get(here, here)}
            if o_heads and n_heads and rule and here and not any(
                    sc >= bar and (o in still or o in fresh)
                    for sc, _r, _t, o in rev):
                relocated.append((ln, s, here))
            continue
        if not rule or ln in ordered_out or (was == 1 and ln in all_padding):
            thinned.append((ln, s))
        elif best >= bar:
            weakened.append((ln, s))
        else:
            gone.append((ln, s))
    def evidence(t):
        return {(c, v) for c, vs in facts(t).items() for v in vs}

    survivors = [(i, n) for i, (n, _r, _o, _t, _f) in enumerate(kept)]
    taken: set[int] = set()
    _alive = evidence("\n".join(n_prose))
    rescued = rescue.answered(
        [(i, inflect.spread(keys(s))) for i, (_ln, s) in enumerate(gone)
         if evidence(s) <= _alive],
        survivors, CLAIM_KEPT, taken)
    weakened.extend(g for i, g in enumerate(gone) if i in rescued)
    weakened.sort()
    gone = [g for i, g in enumerate(gone) if i not in rescued]
    survived = rescue.answered(
        [(i, inflect.spread(keys(s))) for i, (_ln, s) in enumerate(thinned)
         if evidence(s) <= _alive],
        survivors, CLAIM_KEPT, taken)
    thinned = [t for i, t in enumerate(thinned) if i not in survived]
    tokenised = [(f, evidence(t)) for _n, _r, _o, t, f in kept]
    by_token = set()
    for ln, s in gone:
        want = evidence(s)
        mine = keys(s)
        if want and any(want <= have and inflect.overlap(mine, f) >= 3
                        for f, have in tokenised):
            by_token.add(ln)
    weakened.extend((ln, s) for ln, s in gone if ln in by_token)
    weakened.sort()
    gone = [(ln, s) for ln, s in gone if ln not in by_token]
    _EMPHASIS_ONLY = frozenset({
        "always", "everyone", "everybody", "anybody", "anyone", "every",
        "all", "times", "time", "constantly", "rule", "rules", "follow",
        "followed", "following", "obey", "obeyed", "required",
        "requirement", "mandatory",
    })
    _all_sent = list(sentence_spans(list(enumerate(o_prose, 1)), o_rows))
    _prev_of = {}
    for (pa, pb, pt), (a, _b, t) in zip(_all_sent, _all_sent[1:]):
        if all((o_prose[i - 1] if 0 < i <= len(o_prose) else "").strip()
               for i in range(pb + 1, a)):
            _prev_of[(a, t)] = (pa, pt)
    _gone_set = set(gone)
    emphasis_only = set()
    for ln, s in gone:
        prev = _prev_of.get((ln, s))
        if not prev or rule_strength(s) != 2:
            continue
        pa, pt = prev
        if rule_strength(pt) != 2 or (pa, pt) in _gone_set:
            continue
        shared = keys(s) & keys(pt)
        leftover = keys(s) - keys(pt)
        if shared and leftover <= _EMPHASIS_ONLY:
            emphasis_only.add((ln, s))
    weakened.extend(p for p in gone if p in emphasis_only)
    weakened.sort()
    gone = [p for p in gone if p not in emphasis_only]
    if o_src and n_src:
        _ends = {(a, t): b for a, b, t in
                 sentence_spans(list(enumerate(o_prose, 1)), o_rows)}
        _unmasked = [(ln, unmask.joined(o_src, o_prose, ln,
                                        _ends.get((ln, s), ln), s))
                     for ln, s in thinned]
        _alive_now = still_said(_unmasked, n_prose, n_src, keys, n_rows)
        thinned = [t for i, t in enumerate(thinned) if i not in _alive_now]
    return gone, weakened, thinned, relocated


def floor_skipped_drops(o_prose, new_text, o_rows=()):
    """Original sentences `claims_lost` never scores, that are gone anyway."""
    flat = " ".join(new_text.split())
    out = []
    for a, _b, s in sentence_spans(list(enumerate(o_prose, 1)), o_rows):
        t = s.strip()
        if not t or not re.search(r"[a-zA-Z]", t):
            continue
        if re.match(r"^\|?\s*[-: ]+\|[-:| ]*$", t):
            continue
        if rule_strength(s):
            continue
        k = claim_words(s)
        if not (1 <= len(k) < 3):
            continue
        if " ".join(s.split()) in flat:
            continue
        out.append((a, s))
    return out


def split_shapes(o_hits, n_hits):
    """Shapes the pass added, and shapes that were already there."""
    o_keys = {(c, t.lower()) for _, c, t in o_hits}
    o_count, n_count = (Counter(c for _, c, _ in o_hits),
                        Counter(c for _, c, _ in n_hits))
    surplus = {c: n_count[c] - o_count[c] for c in n_count if n_count[c] > o_count[c]}
    o_pairs = Counter((c, t.lower()) for _l, c, t in o_hits)
    n_pairs = Counter((c, t.lower()) for _l, c, t in n_hits)
    room = {k: n_pairs[k] - o_pairs[k] for k in n_pairs if n_pairs[k] > o_pairs[k]}
    new_ix = set()
    for i, (_l, c, t) in enumerate(n_hits):
        if surplus.get(c, 0) > 0 and (c, t.lower()) not in o_keys:
            new_ix.add(i)
            surplus[c] -= 1
            room[(c, t.lower())] = room.get((c, t.lower()), 1) - 1
    for i, (_l, c, t) in enumerate(n_hits):
        key = (c, t.lower())
        if surplus.get(c, 0) > 0 and i not in new_ix and room.get(key, 0) > 0:
            new_ix.add(i)
            surplus[c] -= 1
            room[key] -= 1
    return ([h for i, h in enumerate(n_hits) if i in new_ix],
            [h for i, h in enumerate(n_hits) if i not in new_ix])


def pair_changed(lost, gained):
    """Lost and gained tokens that are two halves of one corrected fact."""
    pairs, l_out, g_out = [], {}, dict(gained)
    for kind, vals in lost.items():
        left, pool = [], list(g_out.get(kind, []))
        for v in vals:
            near = difflib.get_close_matches(v, pool, n=1, cutoff=0.6)
            if near:
                pairs.append((kind, v, near[0]))
                pool.remove(near[0])
                g_out[kind] = [x for x in g_out[kind] if x != near[0]]
            else:
                left.append(v)
        if left:
            l_out[kind] = left
    return pairs, l_out, {k: v for k, v in g_out.items() if v}


DELIMITERS = (("backtick", "`", "`"), ("bracket", "[", "]"),
              ("parenthesis", "(", ")"), ("quote", '"', '"'))


def unpaired_paragraphs(prose):
    """Unbalanced delimiters, as {the line carrying it: [names]}."""
    out, start, buf = {}, 0, []
    for i, line in enumerate(list(prose) + [""]):
        if line.strip():
            if not buf:
                start = i + 1
            buf.append(line)
            continue
        if buf:
            for name, a, b in DELIMITERS:
                run, culprit = 0, start
                for k, row in enumerate(buf):
                    step = (row.count(a) if a == b
                            else row.count(a) - row.count(b))
                    if step:
                        run, culprit = run + step, start + k
                for _ in range(abs(run % 2 if a == b else run)):
                    out.setdefault(culprit, []).append(name)
            buf = []
    return out


def duplicated_tail(prose, least=3):
    """Paragraph line breaks with the same four words on both sides."""
    out = []
    for i in range(len(prose) - 1):
        a, b = prose[i].split(), prose[i + 1].split()
        if not a or not b or not prose[i].strip() or not prose[i + 1].strip():
            continue
        run = [_word(w) for w in a[-8:]]
        head = [_word(w) for w in b[:8]]
        starts = [(0, head)]
        if _word(b[0]) in ARTICLE:
            starts.append((1, [_word(w) for w in b[1:9]]))
        hit = ""
        for off, cand in starts:
            for n in range(min(len(run), len(cand)), least - 1, -1):
                if run[-n:] == cand[:n] and all(run[-n:]):
                    hit = " ".join(b[:off + n])
                    break
            if hit:
                break
        if hit:
            out.append((i + 2, hit))
        else:
            #
            # Not across a blanked code span. `mask` turns `TASK_LINE` into
            # spaces, so "…from the" over "`TASK_LINE` the genre" reads as
            # "the" over "the" when the words are a span apart. The gap shows
            # as whitespace at the end of one line or the start of the next.
            gap = prose[i] != prose[i].rstrip() or prose[i + 1] != prose[i + 1].lstrip()
            if (run[-1] and run[-1] == head[0] and not gap
                    and re.sub(r"^\W+", "", b[0])[:1].islower()):
                out.append((i + 2, b[0]))
    return out


def renamed_headings(headings, by_line):
    """Heading text that `by_line` renames or deletes, as {line: new text}."""
    return {heading_name(h[2]) for h in headings
            if h[0] + 1 in by_line
            and heading_name(re.sub(r"^\s*#+\s*", "", by_line[h[0] + 1]))
            != heading_name(h[2])}


def tail_added(above, old, new, below):
    """The words a rewrite would leave on both sides of a break, or ''."""
    def pair(mid):
        return [l for l in (above, mid, below) if l.strip()]

    was = Counter(t for _, t in duplicated_tail(pair(old), 2))
    for _, t in duplicated_tail(pair(new), 2):
        if was[t]:
            was[t] -= 1
            continue
        return t
    return ""


def orphan_separators(text):
    """Lines holding a table separator with no header row above it."""
    out, lines, fence = [], text.split("\n"), None
    for i, ln in enumerate(lines):
        tok, bare = fence_delim(ln)
        if tok:
            if fence is None:
                fence = tok
            elif fence_closes(tok, fence) and bare:
                fence = None
            continue
        if fence is not None:
            continue
        s = ln.strip()
        if is_separator(s):
            if not (i and is_table_row(lines[i - 1])):
                out.append(i + 1)
    return out


def is_table_row(ln):
    """A pipe line that Markdown will render as a table row."""
    return bool(re.match(r"^ {0,3}\|", ln))


def is_separator(s):
    """True for a table's `|---|---|` row."""
    s = s.strip()
    return s.startswith("|") and not s.strip("|-: ") and "-" in s


def row_cells(s):
    """Cells in one table row."""
    s = CODE_SPAN.sub(lambda m: " " * len(m.group(0)), s.replace(r"\|", "  "))
    return s.strip().strip("|").count("|") + 1


def ragged_rows(text):
    """Table rows whose cell count does not match their separator."""
    out, lines, fence, want = [], text.split("\n"), None, None
    for i, ln in enumerate(lines):
        tok, bare = fence_delim(ln)
        if tok:
            if fence is None:
                fence = tok
            elif fence_closes(tok, fence) and bare:
                fence = None
            want = None
            continue
        if fence is not None:
            continue
        s = ln.strip()
        if not is_table_row(ln):
            want = None
            continue
        n = row_cells(s)
        if is_separator(s):
            want = n
        elif want is not None and n != want:
            out.append((i + 1, n, want))
    return out


def separatorless_tables(text):
    """First line of every run of table rows holding no separator."""
    out, fence, run = [], None, []

    def flush():
        if len(run) > 1 and not any(is_separator(r) for _, r in run):
            out.append(run[0][0])
        run.clear()

    for i, ln in enumerate(text.split("\n") + [""]):
        tok, bare = fence_delim(ln)
        if tok:
            if fence is None:
                fence = tok
            elif fence_closes(tok, fence) and bare:
                fence = None
            flush()
            continue
        if fence is not None:
            continue
        if is_table_row(ln):
            run.append((i + 1, ln.strip()))
        else:
            flush()
    return out


def newly_broken(o_lines, n_lines, orig, new):
    """Lines in `new` that are broken and were not broken in `orig`."""
    was = Counter(orig.split("\n")[ln - 1].strip() for ln in o_lines)
    fresh = []
    for ln in n_lines:
        text = new.split("\n")[ln - 1].strip()
        if was[text]:
            was[text] -= 1
        else:
            fresh.append(ln)
    return fresh


def broken_tables(text):
    """Every table already broken in the file, as (line, what is wrong)."""
    out = [(ln, "table rows with no separator row above them")
           for ln in separatorless_tables(text)]
    out += [(ln, "separator row with no table under it")
            for ln in orphan_separators(text)]
    out += [(ln, f"table row has {n} cells, the header has {want}")
            for ln, n, want in ragged_rows(text)]
    return sorted(out)


def outer_brackets(text):
    """What is inside each outermost `(...)`, nesting and wrapping included."""
    out, stack = [], []
    for i, ch in enumerate(text):
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            at = stack.pop()
            if not stack:
                out.append(text[at + 1:i])
    return out


def _census_n(payload):
    """The fault-shape count `shape_census` prints, as a number."""
    return sum(len(c["shapes"]) for c in payload["chunks"])


def _folded_shape_count(text, name, chat, fallback):
    """Shapes in `text` read the way `run` reads it: paragraphs, not lines."""
    lines = text.split("\n")
    folded, _spans = unwrap_source(lines)
    if len(folded) == len(lines):
        return fallback
    prose, heads, tables, quotes = mask("\n".join(folded), name)
    return (len(find_shapes(prose, tables, heads, quotes, chat=chat))
            + len(list_faults(prose, folded)))


def summary_unbacked(sentences, body):
    """[(sentence, missing tokens)] for each sentence naming what `body` does not."""
    b_facts = facts(body)
    b_digits = set(re.findall(r"\d+(?:[.,]\d+)*", body))
    b_words = set(re.findall(r"[\w-]+", body))
    out = []
    for s in sentences:
        miss = set()
        for kind, vals in facts(s).items():
            if kind in ("fence_lang", "placeholder"):
                continue
            for v in vals:
                if v in b_facts.get(kind, ()) or v in body:
                    continue
                digits = re.findall(r"\d+(?:[.,]\d+)*", v)
                if kind in ("number", "ratio") and digits and all(
                        d in b_digits or (d in SMALL_NUMBERS and re.search(
                            rf"\b{SMALL_NUMBERS[d]}\b", body, re.I))
                        for d in digits):
                    continue
                miss.add(v)
        for w in re.findall(r"(?<=\s)[A-Z][a-z]{2,}\b", s):
            if w not in NAME_NOT and w not in b_words \
                    and w.lower() not in b_words:
                miss.add(w)
        if miss:
            out.append((s, sorted(miss)))
    return out


def cmd_verify(args):
    """`_cmd_verify`, with any genre profile IT loaded put back."""
    _before = PROFILE_NAME
    try:
        return _cmd_verify(args)
    finally:
        if PROFILE_NAME != _before and _before == "default":
            reset_profile()


def _cmd_verify(args):
    op, ep = Path(args.original).resolve(), Path(args.edited).resolve()
    for p in (op, ep):
        bad = not_markdown(p)
        if bad:
            print(f"kill-verbosity: {bad}", file=sys.stderr)
            return 2
    if op == ep or op.samefile(ep):
        print("kill-verbosity: original and edited are the same file. Keep an "
              "untouched copy of the original before editing.", file=sys.stderr)
        return 2

    _cfg = config_note(getattr(args, "project", None),
                       getattr(args, "searched", None))
    if _cfg:
        print(_cfg, file=sys.stderr)
    _stale = rerun.stale_note(op.name, ep.name, op.stat().st_mtime,
                              ep.stat().st_mtime)
    if _stale:
        print("kill-verbosity: " + _stale, file=sys.stderr)

    orig, new = op.read_text(errors="replace"), ep.read_text(errors="replace")
    record = read_run_record(ep)
    o_prose, o_heads, o_tables, o_quotes = mask(orig, op.name)
    n_prose, n_heads, n_tables, n_quotes = mask(new, ep.name)
    _rec_genre = record.get("genre")
    if _rec_genre:
        if apply_genre(_rec_genre, args):
            print(f"reading {run_record_path(ep).name}: read as "
                  f"{_rec_genre}, the genre the run scored under.\n")
    else:
        select_genre(genre_lines(orig, args), o_heads, args)
    fyi = []
    noted = []
    before_c, after_c = facts(orig, counted=True), facts(new, counted=True)
    before = defaultdict(set, {k: set(v) for k, v in before_c.items()})
    after = defaultdict(set, {k: set(v) for k, v in after_c.items()})

    lost = {k: sorted(v - after.get(k, set())) for k, v in before.items()
            if v - after.get(k, set())}
    exempt = Counter(getattr(args, "exempt", ()) or ())
    if not exempt and record.get("exempt"):
        exempt = Counter(record["exempt"])
        print(f"reading {run_record_path(ep).name}: {sum(exempt.values())} "
              f"deletions noise was allowed to make.\n")
    if record.get("chat"):
        args.chat = True
    if record.get("no_agents"):
        print(f"reading {run_record_path(ep).name}: this run called no "
              f"specialist, so the output IS the input. What follows checks "
              f"the gates and this command; it says nothing about any edit.\n")
    _noop = frozen_no_op(record, args, orig, op.name)
    if _noop:
        _ed, _free, _froze, _of, _whose = _noop
        print(f"NOTHING WAS IN PLAY — "
              f"{_froze}{f' of {_of}' if _of else ''} line(s) are frozen "
              f"({_whose}), which is every one of the {_free} line(s) a "
              f"specialist could otherwise have been given. No span was "
              f"editable, so nothing below is a statement about an edit: it is "
              f"this command checking a file against itself.\n"
              f"{getattr(args, 'project', None) or 'The declaration'} is what "
              f"decides this. Narrow `freeze.lines` if you meant to leave part "
              f"of the file in play; leave it if this file is out of scope.\n")
    _swaps = record.get("swaps") or []
    if _swaps:
        _flips = [x for x in _swaps if polarity_flip(x["was"], x["now"])]
        _rest = [x for x in _swaps if x not in _flips]
        print(f"{len(_swaps)} word{'s' if len(_swaps) > 1 else ''} replaced "
              f"one-for-one — read these:")

        def _row(x, mark=""):
            _to = x.get("line_out")
            _where = (f"line {x['line']}->{_to:<7}" if _to and _to != x["line"]
                      else f"~line {x['line']:<5}")
            print(f"  {_where} {x['by']:<11} "
                  f"{x['was']} → {x['now']}{mark}")
            if x.get("in"):
                print(f"         {x['in']}")
        for x in _flips:
            _row(x, "   ← NEGATION: this line now says the opposite")
        for x in _rest[:40]:
            _row(x)
        if len(_rest) > 40:
            print(f"  ... and {len(_rest) - 40} more")
        pass

    _evidence = set()

    def pardoned(k, v):
        if v not in exempt:
            return False
        held = orig.count(v)
        if held and held - new.count(v) > exempt[v]:
            return False
        if never_pardon(k, v, orig):
            _evidence.add((k, v))
            return False
        return True

    if exempt:
        lost = {k: [v for v in vals if not pardoned(k, v)]
                for k, vals in lost.items()}
        lost = {k: v for k, v in lost.items() if v}
    gained = {k: sorted(v - before.get(k, set())) for k, v in after.items()
              if k in ("url", "ticket", "number", "date", "version", "path",
                       "ratio", "code", "fence_lang")
              and v - before.get(k, set())}
    if "code" in gained:
        real = [v for v in gained["code"] if not written_down(v, orig)]
        gained["code"] = real
        if not real:
            del gained["code"]
    if record.get("inserted"):
        print(f"reading {run_record_path(ep).name}: the run inserted text, so "
              f"this checks what went missing and not what arrived.\n")
        gained = {}
    changed, lost, gained = pair_changed(lost, gained)
    changed = [(k, w, n) for k, w, n in changed
               if " ".join(w.split()) != " ".join(n.split())]

    o_hits = find_shapes(o_prose, o_tables, o_heads, o_quotes, chat=args.chat)
    n_hits = find_shapes(n_prose, n_tables, n_heads, n_quotes, chat=args.chat,
                         extra_allowed=allowed_shapes(o_prose))
    introduced, survived = split_shapes(o_hits, n_hits)
    o_folded = _folded_shape_count(orig, op.name, args.chat, len(o_hits))
    n_folded = _folded_shape_count(new, ep.name, args.chat, len(n_hits))

    _o_txt = with_table_text(o_prose, o_tables)
    _n_txt = with_table_text(n_prose, n_tables)
    _o_rows = [ln for ln, _c in o_tables]
    _n_rows = [ln for ln, _c in n_tables]
    _rg_raw, weakened, thinned, relocated = claims_lost(
        _o_txt, _n_txt, untouched_lines(_o_txt, _n_txt), o_heads, n_heads,
        o_hits, orig.splitlines(), new.splitlines(),
        o_rows=_o_rows, n_rows=_n_rows)
    _floor_gone = floor_skipped_drops(_o_txt, new, o_rows=_o_rows)
    rule_gone, _rg_label = [], {}
    for _r in _rg_raw:
        _why = label_not_rule(_r[1])
        if _why:
            _rg_label[_why] = _rg_label.get(_why, 0) + 1
        else:
            rule_gone.append(_r)
    if _rg_label:
        _n = sum(_rg_label.values())
        fyi.append(f"{_n} line{'' if _n == 1 else 's'} the rule check caught "
                   f"{'is not a rule' if _n == 1 else 'are not rules'} — "
                   + ", ".join(f"{v}× {k}" for k, v in
                               sorted(_rg_label.items(), key=lambda i: -i[1])))
    cut_tails = tails_cut(_o_txt, _n_txt, _o_rows, _n_rows)
    _thin_at = {ln for ln, _s in thinned}
    _dropped = {i for a, b, _s in sentence_spans(list(enumerate(_o_txt, 1)),
                                                 _o_rows)
                if a in _thin_at for i in range(a, b + 1)}
    _o_row_txt = [c.strip() for _l, c in o_tables]
    _n_row_txt = [c.strip() for _l, c in n_tables]
    for _op, _i1, _i2, _j1, _j2 in difflib.SequenceMatcher(
            None, _o_row_txt, _n_row_txt).get_opcodes():
        if _op == "delete":
            _dropped |= {o_tables[_k][0] for _k in range(_i1, _i2)}
        elif _op == "replace" and (_i2 - _i1) > (_j2 - _j1):
            _free = list(range(_i1, _i2))
            for _j in range(_j1, _j2):
                if not _free:
                    break
                _best = max(_free, key=lambda _k: difflib.SequenceMatcher(
                    None, _o_row_txt[_k], _n_row_txt[_j]).ratio())
                _free.remove(_best)
            _dropped |= {o_tables[_k][0] for _k in _free}

    o_flat = " ".join(orig.lower().split())
    n_lines = new.split("\n")
    n_spans = list(sentence_spans(list(enumerate(n_prose, 1))))

    def said_at(line, marker):
        for a, b, s in n_spans:
            if a <= line <= b and marker and marker.lower() in s.lower():
                return s
        return n_lines[line - 1] if 0 < line <= len(n_lines) else ""

    quoted_back = [(l, c, t) for l, c, t in introduced
                   if c in REPORTING_SHAPES
                   and reporting_text(t, said_at(l, t), o_flat)]
    if quoted_back:
        introduced = [h for h in introduced if h not in quoted_back]
        survived = survived + quoted_back

    broke = broken_anchors(new) - broken_anchors(orig)

    emd, dups = em_dash_pressure(n_prose), duplicates(n_prose)
    spliced = repeat_delta(duplicates(o_prose, SPLICE_WINDOW),
                           duplicates(n_prose, SPLICE_WINDOW, src=n_lines))[1]
    def _copies(flat, run):
        return sum(1 for _ in re.finditer("(?= %s )" % re.escape(run), flat))

    _o_run, _n_run = (" %s " % " ".join(WORD.findall(SEGMENTED.sub(" ", t).lower()))
                      for t in (orig, new))
    spliced = [d for d in spliced
               if _copies(_n_run, " ".join(d["text"].split()[:SPLICE_WINDOW]))
               > _copies(_o_run, " ".join(d["text"].split()[:SPLICE_WINDOW]))]
    hard = False
    hard_blocks = []

    def _failed_block(name):
        if name not in hard_blocks:
            hard_blocks.append(name)
        return True

    _pardoned = False
    evidence = []

    if broke:
        hard = _failed_block("LINKS BROKEN")
        print(f"\nLINKS BROKEN — {len(broke)} links in this file point at no "
              f"heading in it.\nA renamed heading takes every link to it with "
              f"it. Links from other files are not checked — grep the "
              f"directory for the anchor.")
        print("  " + ", ".join(f"#{a}" for a in sorted(broke)[:10]) + "\n")

    _froze = frozen_damage(args, orig.split("\n"), new.split("\n"))
    if _froze:
        hard = _failed_block("FROZEN LINES CHANGED")
        _pats, _why = getattr(args, "freeze")
        print(f"\nFROZEN LINES CHANGED — {len(_froze)} line"
              f"{'' if len(_froze) == 1 else 's'} this tree froze are not in "
              f"the edited file, byte for byte.\n{args.project} froze "
              f"{list(_pats)} — {_why}")
        for _ln in _froze[:10]:
            print(f"  gone: {_ln.strip()[:100]}")
        if len(_froze) > 10:
            print(f"  … and {len(_froze) - 10} more")
        print("  Put each back exactly as it was. A gate somewhere reads these "
              "by line, which is why they were declared.\n")

    def show(v, width=60):
        v = re.sub(r"^(\d[\d,.]*)([A-Za-z]{2,})$", r"\1 \2", v)
        v = " ".join(v.split())
        return v if len(v) <= width else v[:width] + "…"

    edited = ""
    if changed:
        hard = _failed_block("TOKENS EDITED")
        edited = (f"{len(changed)} token"
                  f"{' was' if len(changed) == 1 else 's were'} edited rather "
                  f"than lost: "
                  + "; ".join(f"{show(w, 24)} → {show(x, 24)}"
                              for _, w, x in changed[:top(3)])
                  + (f" and {len(changed) - top(3)} more"
                     if len(changed) > top(3) else ""))

    _hit = {ln for ln, cat, _t in o_hits if cat in DELETION_ORDERED}
    _cut_lines = _hit | section_lines(o_heads, _hit, len(o_prose))
    _cut_lines |= {i
                   for a, b, _s in sentence_spans(list(enumerate(o_prose, 1)))
                   if _hit & set(range(a, b + 1))
                   for i in range(a, b + 1)}

    if lost:
        o_lines = orig.splitlines()
        index = token_lines(o_lines)
        def still_there(v):
            if v in new:
                return True
            word = SMALL_NUMBERS.get(v)
            return bool(word) and re.search(rf"\b{word}\b", new, re.I)

        gone = {k: [v for v in vals if not still_there(v)]
                for k, vals in lost.items()}
        loose = [v for v in gone.get("code", ()) if BARE_WORD.match(v)]
        if loose:
            gone["code"] = [v for v in gone["code"] if v not in loose]
        NEVER_PARDON = {"url"}
        ordered = sorted({(k, v) for k, vals in gone.items() for v in vals
                          if k not in NEVER_PARDON
                          and index.get(v) and set(index[v]) <= _cut_lines})
        if ordered:
            _drop = {v for _k, v in ordered}
            gone = {k: [v for v in vals if v not in _drop]
                    for k, vals in gone.items()}
        dropped = sorted({(k, v) for k, vals in gone.items() for v in vals
                          if k not in NEVER_PARDON
                          and index.get(v) and set(index[v]) <= _dropped})
        if dropped:
            _drop = {v for _k, v in dropped}
            gone = {k: [v for v in vals if v not in _drop]
                    for k, vals in gone.items()}
        _in_gone = {(k, v) for k, vals in gone.items() for v in vals}
        evidence = sorted({p for p in ordered + dropped
                           if never_pardon(*p, orig)}
                          | (_evidence & _in_gone))
        ordered = [p for p in ordered if p not in evidence]
        dropped = [p for p in dropped if p not in evidence]
        gone = {k: [v for v in vals if (k, v) not in evidence]
                for k, vals in gone.items()}
        gone = {k: v for k, v in gone.items() if v}
        moved = {k: [v for v in vals if v in new] for k, vals in lost.items()}
        moved = {k: v for k, v in moved.items() if v}
        _pardoned = bool(moved or loose or ordered or dropped)

        def dump(d, limit=10):
            _shown = set()
            for kind, vals in sorted(d.items()):
                print(f"  {kind} ({len(vals)}): " +
                      ", ".join(show(v) for v in vals[:top(limit)]))
                if len(vals) > top(limit):
                    print(f"      … showing {top(limit)} of {len(vals)}")
                for v in vals[:top(limit)]:
                    for ln in sorted(index.get(v, ()))[:1]:
                        _row = f"      L{ln}  {o_lines[ln - 1].strip()[:90]}"
                        if _row in _shown:
                            continue
                        _shown.add(_row)
                        print(_row)

        if gone:
            hard = _failed_block("TOKENS LOST")
            n = sum(len(v) for v in gone.values())
            print(f"\nTOKENS LOST — {n} protected token"
                  f"{' is' if n == 1 else 's are'} gone. Restore each, or say "
                  f"in the report why it went.")
            dump(gone, 5)
            pass
        if moved:
            n = sum(len(v) for v in moved.values())
            fyi.append(f"{n} protected token{'' if n == 1 else 's'} left "
                       f"the sentence {'it' if n == 1 else 'they'} sat in and "
                       f"{'is' if n == 1 else 'are'} still elsewhere in the "
                       f"file")
        if loose:
            print(f"words in backticks gone — {len(loose)} single lowercase "
                  f"word{'' if len(loose) == 1 else 's'}, naming nothing.")
            dump({"code": loose}, 3)
            pass
        if ordered:
            by_kind = defaultdict(list)
            for kind, v in ordered:
                by_kind[kind].append(v)
            print(f"tokens in text the skill deletes — {len(ordered)} sat only "
                  f"in a commit ref, a changelog line, an unexplained "
                  f"reference or a citation nobody can follow. Cutting those "
                  f"is the job, so this is not a failure; check each one was "
                  f"the cut you meant.")
            dump(dict(by_kind), 5)
            measurement_note(by_kind)
            pass
        if dropped:
            by_kind = defaultdict(list)
            for kind, v in dropped:
                by_kind[kind].append(v)
            print(f"tokens in deleted sentences — {len(dropped)} went with "
                  f"text the file no longer says. Check each deletion was "
                  f"meant.")
            dump(dict(by_kind), 3)
            measurement_note(by_kind)
            pass

    diluted = {}
    for _k, _vals in before_c.items():
        _after_k = after_c.get(_k, Counter())
        _cand = sorted(v for v, _n in _vals.items()
                       if _after_k[v] and _after_k[v] < _n)
        if _cand:
            diluted[_k] = _cand
    if diluted:
        _items = sorted(
            ((k, v, before_c[k][v], after_c.get(k, Counter())[v])
             for k, vals in diluted.items() for v in vals),
            key=lambda t: t[3] - t[2])
        n = len(_items)
        fyi.append(
            f"{n} protected token{'' if n == 1 else 's'} thinned — fewer "
            f"copies than before but still said at least once: "
            + ", ".join(f"{show(v)} {b}→{a}" for _, v, b, a in _items[:5])
            + (f" and {n - 5} more" if n > 5 else ""))

    _o_quoted = quoted_claims(orig.splitlines())
    _new_flat = " ".join(new.split())
    _quote_lost = []
    for _qln, _qspan in _o_quoted:
        if " ".join(_qspan.split()) in _new_flat:
            continue
        if _cut_lines and _qln in _cut_lines:
            continue
        if pardoned("quote", _qspan):
            continue
        _quote_lost.append((_qln, _qspan))
    if _quote_lost:
        hard = _failed_block("QUOTATIONS LOST")
        _nq = len(_quote_lost)
        print(f"\nQUOTATIONS LOST — {_nq} quoted span"
              f"{'' if _nq == 1 else 's'} in the original "
              f"{'is' if _nq == 1 else 'are'} nowhere in the edited file. "
              f"A quotation is somebody else's words, not the author's to "
              f"shorten. Put {'it' if _nq == 1 else 'each'} back, or say in "
              f"the report why it went.")
        for _qln, _qspan in _quote_lost[:top(10)]:
            print(f"  L{_qln:<5} {_qspan[:top(110)]}")
        if _nq > top(10):
            print(f"      … showing {top(10)} of {_nq}")
        pass

    _o_lines = orig.splitlines()
    _seen = {v for _k, v in evidence}
    evidence += [("id", i) for i in sorted(set(BARE_ID.findall(orig)))
                 if i not in _seen and not re.search(rf"\b{i}\b", new)]
    if evidence:
        print(f"\nids and counts in deleted text — {len(evidence)} went with "
              f"text the run cut. These are never pardoned: an id or a count "
              f"is the evidence itself and cannot be looked up again. Restore "
              f"each, or say in the report why it went.")
        for _k, _v in evidence[:top(10)]:
            _at = next((i for i, ln in enumerate(_o_lines, 1)
                        if _v in ln), None)
            print(f"  {_k}: {_v}" + (f"\n      L{_at}  "
                                     f"{_o_lines[_at - 1].strip()[:90]}"
                                     if _at else ""))
        if len(evidence) > top(10):
            print(f"  … and {len(evidence) - top(10)} more")
    credited = {}
    for m in credited_names(orig):
        who = m.group(1)
        if who in NAME_NOT:
            continue
        _was = len(re.findall(rf"\b{who}\b", orig))
        _now = len(re.findall(rf"\b{who}\b", new))
        if _now >= _was:
            continue
        at = [i for i, ln in enumerate(_o_lines, 1) if re.search(rf"\b{who}\b", ln)]
        _spoken = [i for i in at if i not in (_cut_lines | _dropped)]
        if _spoken and (_was - _now) > (len(at) - len(_spoken)):
            credited[who] = (_spoken, _was, _now)
    _src_was = Counter(credit_key(m) for m in CREDITED_SOURCE.finditer(orig))
    _src_now = Counter(credit_key(m) for m in CREDITED_SOURCE.finditer(new))
    for who, _was in _src_was.items():
        _now = _src_now.get(who, 0)
        if _now >= _was:
            continue
        at = [i for i, ln in enumerate(_o_lines, 1)
              if any(credit_key(m) == who
                     for m in CREDITED_SOURCE.finditer(ln))]
        _spoken = [i for i in at if i not in (_cut_lines | _dropped)]
        if _spoken and (_was - _now) > (len(at) - len(_spoken)):
            credited[who] = (_spoken, _was, _now)
    if credited:
        _cr = sorted(credited.items())
        print(f"\ncredits that left their sentence — {len(_cr)} name"
              f"{'' if len(_cr) == 1 else 's'} or source"
              f"{'' if len(_cr) == 1 else 's'} credited with a claim "
              f"{'is' if len(_cr) == 1 else 'are'} no longer credited where "
              f"{'it was' if len(_cr) == 1 else 'they were'}. Losing who said "
              f"or paid for something is losing a fact: put each back, or "
              f"say in the report why it went.")
        print("  said fewer times than before: "
              + ", ".join(f"{w} {a}→{b}" for w, (_, a, b) in _cr[:top(5)])
              + (f" and {len(_cr) - top(5)} more" if len(_cr) > top(5)
                 else ""))
        for _w, (_sp, _a, _b) in _cr[:top(5)]:
            print(f"      L{_sp[0]}  {_o_lines[_sp[0] - 1].strip()[:90]}")

    recomposed = [v for v in gained.get("ratio", ())
                  if len(re.findall(r"\d+", v)) == 2
                  and all(re.search(rf"(?<![\w.]){h}(?![\w.])", orig)
                          for h in re.findall(r"\d+", v))]
    if recomposed:
        gained["ratio"] = [v for v in gained["ratio"] if v not in recomposed]
        if not gained["ratio"]:
            del gained["ratio"]

    relabelled = [v for v in gained.get("number", ())
                  if re.search(rf"/{re.escape(v)}(?![\w.])", orig)]
    if relabelled:
        gained["number"] = [v for v in gained["number"] if v not in relabelled]
        if not gained["number"]:
            del gained["number"]

    counted = [v for v in gained.get("number", ())
               if not re.search(rf"(?<![\w.]){re.escape(v)}(?![\w.])", new)
               and SMALL_NUMBERS.get(v)]
    if counted:
        gained["number"] = [v for v in gained["number"] if v not in counted]
        if not gained["number"]:
            del gained["number"]

    _orig_bases = {v.rsplit("/", 1)[-1] for v in before.get("path", ())}
    repointed = [v for v in gained.get("path", ())
                 if v.rsplit("/", 1)[-1] in _orig_bases
                 and v not in _orig_bases
                 and re.search(rf"\]\(\s*{re.escape(v)}[\s)#]", new)
                 and not re.search(
                     rf"(?<!\]\()(?<![\w./]){re.escape(v)}(?![\w./])", new)]
    if repointed:
        gained["path"] = [v for v in gained["path"] if v not in repointed]
        if not gained["path"]:
            del gained["path"]

    if gained:
        hard = _failed_block("TOKENS ADDED")
        print(f"\nTOKENS ADDED — {sum(len(v) for v in gained.values())} are in "
              f"the edit and not the original. A pass does not add facts.")
        for kind, vals in sorted(gained.items()):
            print(f"  {kind} ({len(vals)}): " + ", ".join(show(v) for v in vals[:top(10)]))
            if len(vals) > top(10):
                print(f"      … showing {top(10)} of {len(vals)}")
        pass

    if recomposed:
        print(f"ratios composed — {len(recomposed)} join two numbers the "
              f"original already had. Not a new fact; check the pairing.")
        print("  " + ", ".join(show(v) for v in recomposed[:10]) + "\n")

    if edited:
        print(f"\nTOKENS EDITED — {edited}. Each is a protected token the edit "
              f"rewrote. This block FAILS the run: put every one back in the "
              f"edited file and rerun `verify`.")

    if repointed:
        print(f"links repointed — {len(repointed)} link target(s) name a file "
              f"the original already pointed at, from a new place. Not a new "
              f"fact; check each one still resolves from where the file now "
              f"sits.")
        print("  " + ", ".join(show(v) for v in sorted(repointed)[:10]) + "\n")

    if counted:
        print(f"counts introduced — {len(counted)} tallies the original did not "
              f"state. Counting what the file lists is the job; check each "
              f"number against the list it counts.")
        print("  " + ", ".join(f"{SMALL_NUMBERS[v]} ({v})"
                               for v in sorted(counted)) + "\n")

    _o_lines, _n_lines = orig.splitlines(), new.splitlines()

    def _end_map(txt, rows=()):
        out = {}
        for a, b, s in sentence_spans(list(enumerate(txt, 1)), rows):
            out[(a, s)] = None if (a, s) in out else b
        return out

    _ends = {"new": _end_map(_n_txt, _n_rows), "old": _end_map(_o_txt, _o_rows)}

    def as_written(ln, s, side=None):
        src = _n_lines if side == "new" else _o_lines
        txt = _n_txt if side == "new" else _o_txt
        end = _ends["new" if side == "new" else "old"].get((ln, s)) or ln
        if end > ln:
            return unmask.joined(src, txt, ln, end, s)
        return unmask.as_written(src, txt, ln, s)

    arrived = []
    if args.chat:
        _a_gone, _a_weak, _a_thin, _ = claims_lost(
            _n_txt, _o_txt, untouched_lines(_n_txt, _o_txt), n_heads, o_heads)
        arrived = sorted(set(_a_gone) | set(_a_weak) | set(_a_thin))
    if arrived:
        n = len(arrived)
        whole = n * 2 > sum(1 for _a, _b, _s in sentence_spans(
                                list(enumerate(_n_txt, 1)), _n_rows))
        head = ("text with no counterpart" if whole else "TEXT ADDED")
        if not whole:
            hard = _failed_block("TEXT ADDED")
        print(f"{head} — {n} sentence"
              f"{'' if n == 1 else 's'} in the edit {'has' if n == 1 else 'have'}"
              f" no counterpart in the message.\nA message has one author and "
              f"the tool is not it. Read {'it' if n == 1 else 'them'}: a merge "
              f"of several originals is fine, a sentence nobody wrote is not.")
        for ln, s in arrived[:top(10)]:
            print(f"  L{ln:<5} {unmask.quote(as_written(ln, s, 'new'), top(110))}")
        if n > top(10):
            print(f"      … showing {top(10)} of {n}")
        pass

    if rule_gone:
        hard = _failed_block("RULES LOST")
        n = len(rule_gone)
        print(f"\nRULES LOST — {n} sentence{'' if n == 1 else 's'} stating a "
              f"rule, a risk, an open question or a disagreement went, and "
              f"nothing left says it. Put each back, or say why it went.")
        _job_spans = record.get("job_spans")
        for ln, s in sorted(rule_gone, key=lambda r: -finding_rank(r[1])[0])[:top(10)]:
            _owners = blame.job_owners(ln, _job_spans)
            print(f"  L{ln:<5} {unmask.quote(as_written(ln, s), top(110))}"
                  + (f"\n         sent to: {', '.join(_owners)}"
                     if _owners else ""))
        if len(rule_gone) > top(10):
            print(f"      … showing the {top(10)} worth reading first, "
                  f"of {len(rule_gone)}")
        pass
    if weakened:
        rules_hard = [r for r in weakened if rule_strength(r[1]) == 2]
        rules_soft = [r for r in weakened if rule_strength(r[1]) != 2]
        n = len(weakened)
        print(f"rules reworded — {n} sentence{'' if n == 1 else 's'} kept "
              f"{'its' if n == 1 else 'their'} words and lost "
              f"{'its' if n == 1 else 'their'} force."
              + (f" {len(rules_hard)} stated a RULE (`must`, `never`, a corrective "
                 f"imperative): check the instruction is still an instruction "
                 f"and not a description." if rules_hard else "")
              + (f" {len(rules_soft)} only gave ADVICE (`should`, `ought`, "
                 f"`recommended`) — deleting a hedge is this pass's job, so "
                 f"these are usually correct work, and the tool cannot tell "
                 f"which." if rules_soft else ""))
        _rw_rows = [(k, r) for k, rows in (("rule  ", rules_hard),
                                           ("advice", rules_soft))
                    for r in sorted(rows, key=lambda r: -finding_rank(r[1])[0])]
        for kind, (ln, s) in _rw_rows[:top(8)]:
            print(f"  {kind} L{ln:<5} "
                  f"{unmask.quote(as_written(ln, s), top(104))}")
        if len(_rw_rows) > top(8):
            print(f"      … showing the {top(8)} worth reading first, "
                  f"of {len(_rw_rows)}")
        pass
    if relocated:
        noted.append(f"{len(relocated)} rule"
                   f"{'' if len(relocated) == 1 else 's'} turned up under a "
                   f"different heading than in the original")
    if cut_tails:
        n = len(cut_tails)
        print(f"clause cut from the end — {count(n, 'sentence')} kept "
              f"{'its' if n == 1 else 'their'} opening and lost the rest, and "
              f"enough words survive that no other check here says so. Read "
              f"each cut and decide: a repeated or explanatory tail is the job, "
              f"an obligation, a scope limit or the evidence for the claim is "
              f"not.\n")
        print("    (in PROSE this sees a tail dropped off an otherwise "
              "untouched opening, and cannot see a dropped opening, a dropped "
              "middle, or any cut whose surviving half was reworded — the "
              "stump's own full stop moving back over the cut is not a "
              "reword and IS seen. In a "
              "TABLE ROW the cells either side of a cut survive it, so a "
              "front or middle cut inside a row IS reported here and says so "
              "on its own line. Nothing here sees a sentence SPLIT as a cut: "
              "a clause moved to the next sentence keeps every content word "
              "in the file and is pardoned.)\n")
        for _ln, _was, _now, _cut in cut_tails[:12]:
            print(f"  L{_ln}  cut{cut_where(_was, _cut, _ln in _o_rows)}: "
                  f"{_cut}")
            print(f"        now: {_now.strip()[:110]}")
        if n > 12:
            print(f"  ... and {n - 12} more")
        print()

    if thinned:
        finding_lost = [(ln, s) for ln, s in thinned
                        if 0 < ln <= len(_o_lines) and
                        (NUMBERED_ITEM.match(_o_lines[ln - 1])
                         or "**Fix:**" in _o_lines[ln - 1])]
        if finding_lost:
            hard = _failed_block("FINDING LOST")
            thinned = [t for t in thinned if t not in finding_lost]
            n = len(finding_lost)
            print(f"FINDING LOST — {count(n, 'sentence')} left a numbered "
                  f"finding item or a **Fix:** line, and nothing left there "
                  f"says what {'it' if n == 1 else 'they'} said. A finding's "
                  f"key point often carries no number, path or rule word, so "
                  f"the gates above are blind to it -- this is not.\n")
            for ln, s in finding_lost[:top(10)]:
                print(f"  L{ln:<5} {unmask.quote(as_written(ln, s), top(110))}")
            if n > top(10):
                print(f"      … showing {top(10)} of {n}")
            print()

    if thinned:
        n = len(thinned)
        print(f"content dropped — {count(n, 'sentence')} left the "
              f"file and no surviving sentence carries what {'it' if n == 1 else 'they'} "
              f"said. Deleting noise is the job, so this is a list to read, "
              f"not a failure.\n")
        short = [(ln, s) for ln, s in thinned
                 if (len(s.split()) < 12 and _CARRIES_POINT.search(s))
                 or finding_rank(s)[0] >= 5]
        rest = [t for t in thinned if t not in short]
        junk = [(ln, s) for ln, s in rest if not_a_claim(s)]
        rest = [t for t in rest if t not in junk]
        short.sort(key=lambda t: -finding_rank(t[1])[0])
        _edited_low = new.lower()

        def _show_thinned(ln, s):
            print(f"  L{ln:<5} {unmask.quote(as_written(ln, s), top(110))}"
                  f"{_rank_tag(s)}")
            _named, _plain = words_not_found(as_written(ln, s), _edited_low,
                                             orig)
            if not _named and not _plain:
                return
            _tail = f"         not found: {', '.join(_named[:top(6)])}"
            if _named and _plain:
                _tail += f"   (also {len(_plain)} ordinary word" \
                         f"{'' if len(_plain) == 1 else 's'})"
            elif not _named:
                _tail = (f"         not found: "
                         f"{', '.join(_plain[:top(4)])}   (ordinary words)")
            print(_tail)

        if short:
            print(f"  most worth reading — a rule, a definition or something "
                  f"named:")
            for ln, s in short[:top(4)]:
                _show_thinned(ln, s)
            if len(short) > top(6):
                print(f"      … showing {top(6)} of {len(short)}")
            pass
        if junk:
            print(f"  and {len(junk)} line{'' if len(junk) == 1 else 's'} that "
                  f"never carried a claim (table labels, contents links, "
                  f"fragments) — not listed.\n")
        if short and rest:
            print(f"  the rest, worth reading first at the top:")
        for ln, s in sorted(rest, key=lambda r: -finding_rank(r[1])[0])[:top(6)]:
            _show_thinned(ln, s)
        if len(rest) > top(6):
            print(f"      … showing the {top(6)} worth reading first, "
                  f"of {len(rest)}")
        pass
        if not any(s.strip() for s in with_table_text(n_prose, n_tables)):
            hard = _failed_block("EVERYTHING GONE")
            print("EVERYTHING GONE — no prose is left in the file. That is a "
                  "deletion, not an edit. Restore it, or say in your report "
                  "what the document is for now.\n")

    renames, lost_heads = heading_moves(
        o_heads, n_heads,
        section_bodies(o_heads, _o_txt), section_bodies(n_heads, _n_txt))
    broken_links = []
    if renames:
        _rn_rows, _rn_clean = [], 0
        _nl = new.split("\n")
        _at = ({h[0] + 1 for h in n_heads}
               | pointers.unreadable(_nl, _n_txt))
        for i, (was, now) in enumerate(renames):
            broke = inbound_anchors(Path(args.original), was)
            broken_links += [(was, b) for b in broke]
            here = pointers.stale_mentions(_nl, was, _at)
            if not broke and not here:
                _rn_clean += 1
                continue
            if len(_rn_rows) < top(8):
                _rn_rows.append(
                    f"  {was[:52]} → {now[:52]}"
                    + (f"\n      breaks {len(broke)} link"
                       f"{'' if len(broke) == 1 else 's'}: "
                       f"{', '.join(broke[:top(3)])}" if broke else "")
                    + (f"\n      still named on L"
                       f"{', L'.join(str(n) for n in here[:top(6)])}"
                       if here else ""))
        _rn_bad = len(renames) - _rn_clean
        if _rn_rows:
            print(f"headings renamed and still referred to — {_rn_bad} of "
                  f"{len(renames)}. The old name is still written somewhere, "
                  f"so the reference now points at nothing.")
            for _r in _rn_rows:
                print(_r)
            if _rn_bad > top(8):
                print(f"      … showing {top(8)} of {_rn_bad}")
            pass
        if _rn_clean:
            fyi.append(f"{_rn_clean} heading"
                       f"{' was' if _rn_clean == 1 else 's were'} renamed with "
                       f"no link or mention left pointing at the old name")
    if lost_heads:
        n = len(lost_heads)
        print(f"headings gone or renamed — {n} heading"
              f"{'' if n == 1 else 's'} in the original pair with nothing in "
              f"the edit. A section that was deleted and one that was renamed "
              f"and rewritten read the same from here. Find each of these in "
              f"the file before you act on it.\n")
        _o_raw, _spans = orig.split("\n"), section_spans(o_heads,
                                                         orig.split("\n"))
        for h in lost_heads[:top(5)]:
            body = "\n".join("\n".join(_o_raw[a:b])
                             for a, b in _spans.get(h, ()))
            held = sum(len(v) for v in facts(body).values())
            missing = dropped_here(body, new) if held else []
            if not held:
                say = "no number, path or identifier under it to trace"
            elif missing:
                what = ", ".join(str(m)[:24] for m in missing[:top(3)])
                say = (f"its one protected token is gone from the file: "
                       f"{what}" if held == 1 else
                       f"{len(missing)} of its {held} protected tokens are "
                       f"gone from the file: {what}")
            else:
                say = (f"its {held} protected token"
                       f"{' is' if held == 1 else 's are'} still in the file")
            print(f"  {h[:80]} — {say}")
        if len(lost_heads) > top(8):
            print(f"      … showing {top(8)} of {len(lost_heads)}")
        pass

    orphan_pointers = _orphaned_pointers(o_heads, n_heads, new)
    if orphan_pointers:
        n = len(orphan_pointers)
        print(f"pointers with no section — {n} bracket"
              f"{'' if n == 1 else 's'} in the edit name"
              f"{'s' if n == 1 else ''} a section the original had and this "
              f"file does not. Point {'it' if n == 1 else 'them'} at the new "
              f"name, or drop the bracket.")
        for p in orphan_pointers[:top(8)]:
            print(f"  ({p[:78]})")
        if n > top(8):
            print(f"      … showing {top(8)} of {n}")
        pass

    o_tails = Counter(t for _, t in duplicated_tail(o_prose))
    tails = []
    for ln, txt in duplicated_tail(n_prose):
        if o_tails[txt]:
            o_tails[txt] -= 1
            continue
        tails.append((ln, txt))
    if tails:
        hard = _failed_block("DUPLICATED TAIL")
        print(f"DUPLICATED TAIL — {len(tails)} line breaks repeat the same words "
              f"on both sides. A wrapped sentence was rewritten on one side "
              f"only and the old half is still there.")
        for ln, txt in tails[:8]:
            print(f"  L{ln:<5} {txt[:80]}")
        pass

    was = Counter(n for names in unpaired_paragraphs(o_prose).values()
                  for n in names)
    orphans = {}
    for ln, names in sorted(unpaired_paragraphs(n_prose).items()):
        for name in names:
            if was[name]:
                was[name] -= 1
                continue
            orphans.setdefault(ln, name)
    if orphans:
        hard = _failed_block("UNPAIRED")
        print(f"UNPAIRED — {len(orphans)} paragraphs lost the other half of a "
              f"delimiter. A wrapped sentence was reworded on one line and the "
              f"opener or closer on the neighbouring line is now alone.")
        for ln, name in sorted(orphans.items())[:top(8)]:
            print(f"  L{ln:<5} {name}: {n_prose[ln - 1].strip()[:70]}")
        pass

    if VOCAB["never_swap"]:
        _ns_rx = re.compile(r"\b(?:%s)\b" % "|".join(VOCAB["never_swap"]), re.I)
        _o_ns = Counter(w.lower() for w in _ns_rx.findall(orig))
        _n_ns = Counter(w.lower() for w in _ns_rx.findall(new))
        swapped = {w: _o_ns[w] - _n_ns.get(w, 0)
                   for w in _o_ns if _o_ns[w] > _n_ns.get(w, 0)}
        if swapped:
            hard = _failed_block("NEVER-SWAP WORD LOST")
            total = sum(swapped.values())
            print(f"\nNEVER-SWAP WORD LOST — {total} occurrence"
                  f"{'' if total == 1 else 's'} of a word this tree named "
                  f"never to swap for a synonym "
                  f"{'is' if total == 1 else 'are'} gone from the edited "
                  f"file. The words are unchanged in the inventory sense, so "
                  f"only this list catches the swap.")
            for w, n in sorted(swapped.items()):
                print(f"  {w!r}: {_o_ns[w]} -> {_n_ns.get(w, 0)}")
            pass

    o_ordered = ordered_runs(o_prose)
    n_marker_vals = {int(m.group(1)) for ln in n_prose
                     for m in [NUMBERED_MARKER.match(ln or "")] if m}
    gone_markers = {}
    for run in o_ordered:
        missing = [v for v in run if v not in n_marker_vals]
        if missing:
            gone_markers[run] = missing
    if gone_markers:
        hard = _failed_block("ORDERED LIST BROKEN")
        total = sum(len(m) for m in gone_markers.values())
        print(f"\nORDERED LIST BROKEN — {total} numbered item marker"
              f"{'' if total == 1 else 's'} from a list of 3 or more are "
              f"gone from the edited file. The item's own text may still "
              f"be there, unmarked -- a demoted numbered item reads as an "
              f"ordinary paragraph and every \"item N\" reference to it is "
              f"now stale.")
        for run, missing in sorted(gone_markers.items()):
            print(f"  list {run[0]}-{run[-1]}: missing "
                  f"{', '.join(map(str, missing))}")
        pass

    smashed = {ln for ln, _ in tails} | set(orphans)

    o_seps, n_seps = orphan_separators(orig), orphan_separators(new)
    fresh_seps = newly_broken(o_seps, n_seps, orig, new)
    if fresh_seps:
        hard = _failed_block("TABLE BROKEN")
        smashed |= set(fresh_seps)
        print(f"TABLE BROKEN — {len(fresh_seps)} table separator "
              f"row(s) have no header above them. A separator on its own does "
              f"not render as a table.")
        for l in fresh_seps[:8]:
            print(f"  L{l:<5} {new.split(chr(10))[l - 1][:80]}")
        pass

    o_rag, n_rag = ragged_rows(orig), ragged_rows(new)
    fresh_rag_lines = set(newly_broken([l for l, _, _ in o_rag],
                                       [l for l, _, _ in n_rag], orig, new))
    fresh_rag = [r for r in n_rag if r[0] in fresh_rag_lines]
    if fresh_rag:
        hard = _failed_block("TABLE BROKEN")
        smashed |= fresh_rag_lines
        print(f"TABLE BROKEN — {len(fresh_rag)} table row(s) have the "
              f"wrong number of cells. A row that does not match its separator "
              f"does not render.")
        for l, n, want in fresh_rag[:8]:
            print(f"  L{l:<5} {n} cells, the separator says {want}")
            print(f"         {new.split(chr(10))[l - 1][:80]}")
        pass

    o_nos, n_nos = separatorless_tables(orig), separatorless_tables(new)
    fresh_nos = newly_broken(o_nos, n_nos, orig, new)
    if fresh_nos:
        hard = _failed_block("TABLE BROKEN")
        smashed |= set(fresh_nos)
        print(f"TABLE BROKEN — {len(fresh_nos)} table(s) have no "
              f"separator row under the header. Without one the header and "
              f"every row under it render as a single paragraph of pipe "
              f"characters.")
        for l in fresh_nos[:top(8)]:
            print(f"  L{l:<5} {new.split(chr(10))[l - 1][:80]}")
        pass

    if introduced:
        hard = _failed_block("SHAPES INTRODUCED")
        print(f"\nSHAPES INTRODUCED — {len(introduced)} verbose shapes are new in "
              f"the edit. The pass made these worse.")
        for l, c, t in introduced[:top(15)]:
            mark = "   ← this line is already reported broken above" \
                if l in smashed else ""
            print(f"  L{l:<5} {c:<18} {t}{mark}")
        pass

    if survived:
        by_kind = defaultdict(list)
        for line, cat, txt in survived:
            by_kind[cat].append((line, txt))
        _sv = sum(len(v) for v in survived.values()) if isinstance(
            survived, dict) else len(survived)
        noted.append(f"{len(survived)} verbose shape"
                   f"{'' if len(survived) == 1 else 's'} the pass did not "
                   f"reach {'is' if len(survived) == 1 else 'are'} still in "
                   f"the edited file — work for the next run, not a loss from "
                   f"this one")
        for cat, items in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
            seen = Counter()
            shown = []
            for l, t in items[:top(6)]:
                said = unmask.in_context(_n_lines, _n_txt, l, t,
                                         top(34), seen[l, t], abbr=ABBR)
                seen[l, t] += 1
                shown.append(f"L{l} {said!r}")
            print(f"  {cat} ({len(items)}): " + ", ".join(shown)
                  + (f" … {len(items) - top(6)} more"
                     if len(items) > top(6) else ""))
        pass

    def longs(prose):
        return [(ln, n_words(s), s)
                for ln, s in sentences(list(enumerate(prose)))
                if n_words(s) > LONG_SENTENCE]

    o_long = longs(with_spans(o_prose, orig))
    n_long = longs(with_spans(n_prose, new))

    o_sets = [{w.lower() for w in s.split()} for _, _, s in o_long]
    o_flat = " ".join(orig.split()).lower()

    def rewritten(s):
        flat = " ".join(s.split()).lower()
        if flat and flat in o_flat:
            return True
        w = {x.lower() for x in s.split()}
        return any(len(w & o) / len(w | o) >= 0.5 for o in o_sets)

    new_long = [v for v in n_long if not rewritten(v[2])]
    if new_long:
        print(f"\nNEW LONG SENTENCES — {len(new_long)} over {LONG_SENTENCE} words "
              f"are not in the original. Length finds candidates; read these "
              f"and decide. A list to read, not a failure.")
        for ln, n, s in new_long[:top(8)]:
            print(f"  L{ln + 1:<5} {n}w  {s[:110]}")
        pass

    if emd:
        print(f"em-dash: {len(emd)} paragraph{'' if len(emd) == 1 else 's'} "
              f"hold{'s' if len(emd) == 1 else ''} more than one "
              f"(showing {min(top(8), len(emd))}: "
              f"lines {[l for l, _ in emd[:top(8)]]}).")
    if dups:
        print(f"repeated text: {len(dups)} "
              f"cluster{'' if len(dups) == 1 else 's'} still present "
              f"(lines {cluster_lines(dups)}).")
    if spliced:
        print(f"text the edit repeated: {len(spliced)} "
              f"{'run' if len(spliced) == 1 else 'runs'} of words the edit "
              f"says more often than the original did "
              f"(lines {cluster_lines(spliced)}). A "
              f"sentence built from the tail of another one looks like this. "
              f"Read those lines against the original.")
        for d in spliced[:top(8)]:
            was = ("no run of these words in the original"
                   if d.get("before") is None
                   else f"the original had {d['before']}")
            print(f"  {was}, the edit has {d.get('now', 2)}: "
                  f"{unmask.quote(d.get('said') or d['text'])}")
        if len(spliced) > top(8):
            print(f"      … showing {top(8)} of {len(spliced)}")

    bw, aw = (word_count(t) for t in (orig, new))
    chat_over_cap = args.chat and aw > CHAT_MAX_WORDS
    if chat_over_cap:
        print(f"still {aw} words against a {CHAT_MAX_WORDS}-word cap. Lead "
              f"with the one point and send the rest only if asked. If what "
              f"is left is a quotation or a fence, say so in the report.\n")
    o_sum = None if args.chat else opening_summary(o_heads, o_prose, bw, orig)
    n_sum = None if args.chat else opening_summary(n_heads, n_prose, aw, new)
    over_cap = None
    n_written = 0
    ghosts = []
    if n_sum and n_sum["present"]:
        fresh = set()
        for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
                None, o_prose, n_prose, autojunk=False).get_opcodes():
            if tag in ("insert", "replace"):
                fresh |= set(range(j1, j2))
        start, end = n_sum["line"] - 1, n_sum["end"]
        n_written = sum(len(n_prose[j].split())
                        for j in range(start, min(end, len(n_prose)))
                        if j in fresh)
        summary_text = " ".join(n_prose[j] for j in
                                range(start, min(end, len(n_prose))))
        ghosts, broken = ghost_pointers(summary_text,
                                        [h[2] for h in n_heads])
        wrote = heading_name(" ".join(
            n_prose[j] for j in range(start, min(end, len(n_prose)))
            if j in fresh))
        mine = [g for g in ghosts if g in wrote]
        if ghosts:
            if broken and mine:
                hard = _failed_block("SUMMARY POINTERS BROKEN")
            print(f"\n{'SUMMARY POINTERS BROKEN — ' if broken and mine else ''}"
                  f"summary pointers: {len(ghosts)} name no heading in this "
                  f"file. A pointer the reader cannot follow is the reference "
                  f"this tool deletes elsewhere."
                  + (" Copy the name out of the heading list, or drop the "
                     "bracket." if broken and mine else ""))
            for g in ghosts[:8]:
                print(f"  ({g})" + ("" if g in wrote else
                                    "  — already in the file, not this run's"))
    if (o_sum and o_sum["present"] and aw >= SUMMARY_NEEDED_FROM
            and not (n_sum and n_sum["present"])):
        hard = _failed_block("SUMMARY LOST")
        print("\nSUMMARY LOST — the original opened with a one-page summary and "
              "the edit does not. Put it back: a long document has to tell the "
              "reader the result before it asks for a page of their time.")
    else:
        v = summary_verdict(n_sum, written=n_written,
                            refused=record.get("refused_summary"))
        if v and v[0] != "ok":
            over_cap = v[0]
            print(f"\nopening summary: {v[1]}")
    if fyi:
        print(f"\n{FYI_TITLE}")
        for line in fyi:
            print(f"  {line}")
    if noted:
        print(f"\n{NOTED_TITLE}")
        for line in noted:
            print(f"  {line}")

    _pw = (sum(len(l.split()) for l in n_prose)
           - sum(len(l.split()) for l in o_prose))
    args.shape_tally = (o_folded, n_folded, len(introduced), len(survived))
    print(f"\nshapes {o_folded} → {n_folded} "
          f"({len(introduced)} new shape{'' if len(introduced) == 1 else 's'}, "
          f"{len(survived)} carried over) · "
          f"long sentences {len(o_long)} → {len(n_long)} "
          f"({len(new_long)} new) · "
          f"words {bw} → {aw} ({aw - bw:+d})"
          + (f" · prose alone {_pw:+d}"
             if abs(_pw - (aw - bw)) > 20 else ""))
    o_s = o_sum["words"] if o_sum and o_sum["present"] else 0
    n_s = n_sum["words"] if n_sum and n_sum["present"] else 0
    sum_slot = next((i for i, h in enumerate(
        [h for h in n_heads if h[2].strip()])
        if n_sum and n_sum["present"] and h[0] == n_sum["line"] - 1), None)
    renamed_into_summary = bool(
        n_sum and n_sum["present"] and not (o_sum and o_sum["present"])
        and sum_slot is not None and not n_written
        and any(slot == sum_slot
                for _w, _n, slot in heading_pairs(
                    o_heads, n_heads,
                    section_bodies(o_heads, _o_txt),
                    section_bodies(n_heads, _n_txt))[0]))
    def _shape(s):
        return tuple(re.findall(r"[a-z0-9]+", s.lower()))

    promoted = doubled = False
    unbacked = []
    if n_sum and n_sum["present"] and not (o_sum and o_sum["present"]) \
            and not renamed_into_summary:
        was = {_shape(s) for s in _split(" ".join(o_prose))}
        body = n_prose[n_sum["line"]:min(n_sum["end"], len(n_prose))]
        block = [s for s in _split(" ".join(body)) if _shape(s)]
        promoted = bool(block) and all(_shape(s) in was for s in block)
        kept = [s for s in block if _shape(s) in was]
        fresh = [s for s in block if _shape(s) not in was]
        unbacked = summary_unbacked(fresh, "\n".join(
            ln for i, ln in enumerate(new.split("\n"), 1)
            if not n_sum["line"] <= i <= n_sum["end"]))
        d_old = sum(len(s.split()) for s in kept)
        d_new = sum(len(s.split()) for s in fresh)
        doubled = (not promoted and d_old >= SUMMARY_MIN_WORDS
                   and d_new >= SUMMARY_MIN_WORDS)
    if renamed_into_summary:
        print(f"opening summary: “{n_sum['title'][:52]}”, a section this run "
              f"renamed rather than wrote. Its {n_s} words were always in the "
              f"file, so there is no body/summary split to show.")
    elif promoted:
        print(f"opening summary: promoted, no new prose. A heading was added "
              f"over {n_s} words that were already in the file. Every sentence "
              f"under it was there before, so nothing was written — this run "
              f"scores zero for the summary.")
    elif o_s or n_s:
        carried = n_s - n_written
        note = (f" ({n_written} new"
                + (f", {carried} already in the file)" if carried else ")")) \
            if n_s else ""
        print(f"body {bw - o_s} → {aw - n_s} ({(aw - n_s) - (bw - o_s):+d}) · "
              f"opening summary {o_s} → {n_s}{note}")
        if doubled:
            print(f"\nopening summary: written over an opening the file "
                  f"already had. {d_new} new words sit above {d_old} that were "
                  f"there before, both under the one heading. Read the lower "
                  f"block: if it says what the new summary says, one of them "
                  f"goes; if it only announces the document, it goes too.")
    if unbacked:
        print(f"\nsummary sentences the body does not state — {len(unbacked)} "
              f"sentence{'' if len(unbacked) == 1 else 's'} this run wrote "
              f"into the summary name a number, id or name the body never "
              f"mentions. A summary says only what the body says: correct "
              f"each one or cut it.")
        for _s, _miss in unbacked[:top(5)]:
            print(f"  {_s.strip()[:110]}\n      not in the body: "
                  + ", ".join(_miss))
        if len(unbacked) > top(5):
            print(f"  … and {len(unbacked) - top(5)} more")

    _gf = getattr(args, "gates_file", None)
    if _gf:
        try:
            _decl = gatelib.load(Path(_gf))
        except gatelib.Declined as e:
            print(f"kill-verbosity: {e}", file=sys.stderr)
            _decl = []
        if _decl and not gatelib.trusted(Path(_gf)):
            print(f"kill-verbosity: {_gf} declares "
                  f"{len(_decl)} check(s) with no acknowledgement in "
                  f"{gatelib.trust_store()}.{gatelib.store_moved()} "
                  f"Read it, then: kill-verbosity trust {_gf}\n"
                  f"kill-verbosity: nothing was executed. The declaration is "
                  f"found by walking UP from the document, so a file you have "
                  f"not opened can name a command.", file=sys.stderr)
            _decl = []
        if not _decl and _gf:
            print("kill-verbosity: no declared check ran, so the verdict "
                  "below is about the document alone and says nothing about "
                  "this tree's own checks.", file=sys.stderr)
        if _decl:
            _side = ep.name if ep != op else ""
            _res = gatelib.run(_decl, Path(_gf).parent, op, ep, ep)
            _lines, _ghard, _dead, _blind = gatelib.report(_res, _side)
            for _l in _lines:
                print(_l)
            hard = hard or _ghard
            args.gates_blind = _blind

    _say = getattr(args, "verdict", True)
    _n_findings = 0
    for _f in (survived, emd, dups, new_long, thinned, broken_links,
               relocated, spliced, lost_heads, ghosts, weakened, credited,
               counted, orphan_pointers, unbacked, evidence, cut_tails):
        try:
            _n_findings += len(_f)
        except TypeError:
            _n_findings += 1 if _f else 0
    for _f in (over_cap, doubled, chat_over_cap):
        _n_findings += 1 if _f else 0
    if not _say:
        if hard:
            print("\nchecklist done — read the blocks above. "
                  + ("FAILED the run: " + ", ".join(hard_blocks) + ". "
                     if hard_blocks else "")
                  + "`verify` on the command line never blocks; `accept` "
                    "refuses this edit.")
        else:
            print(f"\nchecklist done — {_n_findings} thing"
                  f"{'' if _n_findings == 1 else 's'} to read above. Nothing "
                  f"here blocks. You decide which cuts were meant.")
            print(MEANING_GAP)
    if hard:
        if _say:
            print("\nFAIL — fix the blocks above and rerun.")
            if hard_blocks:
                print("FAILED the run: " + ", ".join(hard_blocks)
                      + ". Every other block above is a list to read.")
            else:
                print("FAILED the run: no block recorded itself. That is a "
                      "defect in this report, not a run with nothing wrong.")
            print(MEANING_GAP)
        return 1
    if _noop and _say:
        print("\nNOTHING IN PLAY — no check above compared an edit, "
              "because the freeze left no editable line to edit. Read the "
              "block at the top: this is not a clean bill of health, it is "
              "the absence of anything to give one about.")
    if (survived or emd or dups or new_long or over_cap or thinned or doubled
            or broken_links or relocated or spliced
            or lost_heads or ghosts or weakened or chat_over_cap or credited
            or counted or orphan_pointers or unbacked or evidence):
        why = [w for w, on in (("shapes still in the file", survived),
                               ("em-dash pressure", emd),
                               ("repeated text", dups),
                               ("new long sentences", new_long),
                               ({"missing": "no opening summary",
                                 "buried": "a buried summary",
                                 "unheaded": "an unheaded summary",
                                 "thin": "a summary too thin to be one",
                                 "refused": "a summary the gates dropped",
                                 }.get(over_cap, "an over-cap summary"),
                                over_cap),
                               ("a summary over an opening the file already "
                                "had", doubled),
                               ("content that thinned out", thinned),
                               ("rules that stopped reading as rules",
                                weakened),
                               ("rules that changed section", relocated),
                               ("text the edit repeated", spliced),
                               ("headings that went", lost_heads),
                               ("links other files had to this one",
                                broken_links),
                               ("summary pointers with no section",
                                orphan_pointers),
                               ("links with no target", ghosts),
                               ("a message still over the chat cap",
                                chat_over_cap),
                               ("credited names that went", credited),
                               ("counts the original did not state",
                                counted),
                               ("summary sentences the body does not state",
                                unbacked),
                               ("ids and counts in deleted text", evidence),
                               ("a clause cut from the end", cut_tails))
                if on]
        if _say:
            if _pardoned:
                _lead = "some tokens were lost and pardoned"
            elif relocated:
                _n_reloc = len(relocated)
                _lead = (f"{_n_reloc} rule sentence"
                         f"{'' if _n_reloc == 1 else 's'} only matched text "
                         f"under a different heading, not this edit — read "
                         f"the relocation note above before calling this "
                         f"clean")
            else:
                _lead = "no token was lost and no shape was added"
            print(f"\nREVIEW — {_lead}. "
                  f"{'; '.join(why)}. Read the "
                  f"block{'' if len(why) == 1 else 's'} above: each needs a "
                  f"fix or a stated reason.")
            print(MEANING_GAP)
        return 3
    if _noop:
        if _say:
            print(MEANING_GAP)
        return 3
    if _say:
        if _pardoned:
            print("\nPASS — every remaining protected token and rule sentence "
                  "survived, and no shape is left. Some tokens were lost and "
                  "pardoned (blocks above); read them to confirm each cut was "
                  "meant.")
        else:
            print("\nPASS — every protected token and every rule sentence "
                  "survived, and no shape is left.")
        print(PASS_GAP)
        if _floor_gone:
            _nf = len(_floor_gone)
            print(f"  In this file: {count(_nf, 'sentence')} "
                  f"{'matches' if _nf == 1 else 'match'} that shape and "
                  f"{'is' if _nf == 1 else 'are'} gone from the edited "
                  f"file. Not a failure -- named because a hypothetical is "
                  f"not a lead.")
            for _fln, _fs in _floor_gone[:top(5)]:
                print(f"    L{_fln:<5} {_fs.strip()[:top(110)]}")
            if _nf > top(5):
                print(f"      … showing {top(5)} of {_nf}")
        if cut_tails:
            _nc = len(cut_tails)
            print(f"  Also above: {count(_nc, 'sentence')} kept "
                  f"{'its' if _nc == 1 else 'their'} opening and lost the "
                  f"rest (\"clause cut from the end\"). Not a failure -- "
                  f"named here so PASS does not read as though nothing were "
                  f"printed above it.")
    return 0


IP_CTX = 1
IP_LNUM = re.compile(r"^\s+L(\d+)\s")
IP_HLINES = re.compile(r"\(lines ([^)]*)")
IP_ANYL = re.compile(r"\bL(\d+)\b")
IP_TOKLINE = re.compile(
    r"^\s+(?:code|url|path|name|number|id|token)\s*\((\d+)\):\s*(.+)$")
IP_SHOWING = re.compile(r"^\s+…\s*showing")
IP_SHORT = {
    "content dropped": "dropped", "RULES LOST": "RULE",
    "TOKENS LOST": "token", "tokens in deleted sentences": "token",
    "words in backticks gone": "token", "rules reworded": "reworded",
    "rules that changed section": "moved",
    "headings gone or renamed": "heading", "headings renamed": "heading",
    "credited names dropped": "credit", "SHAPES INTRODUCED": "verbose",
    "NEW LONG SENTENCES": "long", "TOKENS ADDED": "ADDED",
    "text the edit repeated": "repeated", "counts introduced": "count",
    "TOKENS EDITED": "token",
    "LINKS BROKEN": "link",
    "QUOTATIONS LOST": "quote",
    "FROZEN LINES CHANGED": "frozen", "TEXT ADDED": "invented",
    "EVERYTHING GONE": "emptied", "DUPLICATED TAIL": "half-merged",
    "UNPAIRED": "unpaired", "TABLE BROKEN": "table",
    "SUMMARY POINTERS BROKEN": "pointer", "SUMMARY LOST": "summary",
    "FINDING LOST": "finding", "NEVER-SWAP WORD LOST": "swap",
    "ORDERED LIST BROKEN": "list",
}
IP_EDIT_SIDE = {"TOKENS ADDED", "text the edit repeated",
                "NEW LONG SENTENCES", "counts introduced",
                "SHAPES INTRODUCED"}
FYI_TITLE = "also checked, nothing to act on:"
NOTED_TITLE = "also checked, and these are named in the verdict:"
IP_SKIP = {t.rstrip(":") for t in (FYI_TITLE, NOTED_TITLE)}
IP_NAME_MAX = 48
IP_TOKY = {"token", "heading", "ADDED", "credit", "count", "link"}


def ip_kind(t):
    """The kind a row is counted under."""
    first = t.split(" ", 1)[0]
    return first if first in IP_TOKY else t
IP_FITS = 96
IP_NUMUNIT = re.compile(r"^[\d.,]+\s*[A-Za-z%]+$")


def _ip_flat(s):
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def ip_untrunc(needle):
    """The searchable part of a reported token."""
    n = needle.strip().strip("`").strip()
    if n.endswith("…"):
        n = n[:-1].strip()
    return n


def ip_find_line(needle, lines, used, loose=False):
    """The first line holding this text that is not already spoken for."""
    whole = needle.strip().strip("`").strip()
    n = ip_untrunc(needle)
    if not n:
        return None
    if whole != n:
        for i, ln in enumerate(lines, 1):
            if i not in used and whole in ln:
                return i
        for i, ln in enumerate(lines, 1):
            if whole in ln:
                return i
    if loose:
        want = _ip_flat(n)
        if want:
            for i, ln in enumerate(lines, 1):
                if want in _ip_flat(ln):
                    return i
    for i, ln in enumerate(lines, 1):
        if i not in used and n in ln:
            return i
    for i, ln in enumerate(lines, 1):
        if n in ln:
            return i
    return None


def ip_find_fact(needle, lines, used):
    """A token the report canonicalised, placed by re-running the extractor."""
    n = ip_untrunc(needle)
    if not n:
        return None
    flat = n.replace(" ", "") if IP_NUMUNIT.match(n) else n
    spare, fence = None, None
    for i, ln in enumerate(lines, 1):
        tok, bare = fence_delim(ln)
        if tok and fence is None:
            fence = tok
            continue
        if tok and fence is not None and fence_closes(tok, fence) and bare:
            fence = None
            continue
        if fence is not None:
            continue
        if any(flat == (v.replace(" ", "") if IP_NUMUNIT.match(v) else v)
               for vals in facts(ln).values() for v in vals):
            if i not in used:
                return i
            spare = spare or i
    return spare


def ip_parse(report, o, e, adds=None):
    """The printed report -> where each finding sits."""
    on, en, lost, head, hlines = {}, {}, [], None, []
    e_add = e if adds is None else [ln if i in adds else ""
                                    for i, ln in enumerate(e, 1)]
    for ln in report.splitlines():
        if not ln.strip():
            continue
        if not ln.startswith(" "):
            name = ln.split(" — ")[0].split(":")[0].strip()
            if name in IP_SHORT or name in IP_SKIP or (
                    len(name) <= IP_NAME_MAX
                    and (" — " in ln or ln.rstrip().endswith(":"))):
                head = name
                mh = IP_HLINES.search(ln)
                hlines = [int(n) for seg in mh.group(1).split(";")
                          for n in re.findall(r"\d+", seg.split("(")[0])
                          ] if mh else []
            else:
                head, hlines = None, []
            continue
        if head is None:
            continue
        if head in IP_SKIP or IP_SHOWING.match(ln):
            continue
        tag = IP_SHORT.get(head, head)
        m = IP_LNUM.match(ln)
        if m:
            (en if head in IP_EDIT_SIDE else on).setdefault(
                int(m.group(1)), []).append(tag)
            continue
        t = IP_TOKLINE.match(ln)
        if t:
            for tok in [x.strip() for x in t.group(2).split(",") if x.strip()]:
                tgt, side = ((e_add, en) if head in IP_EDIT_SIDE else (o, on))
                i = (ip_find_line(tok, tgt, set(side))
                     or ip_find_fact(tok, tgt, set(side)))
                if i:
                    side.setdefault(i, []).append(
                        f"{tag} {tok}" if tag in IP_TOKY else tag)
                else:
                    lost.append(f"{tag}: {tok}")
            continue
        inner = [int(x) for x in IP_ANYL.findall(ln)]
        if inner:
            for i in inner:
                pick = (on if 0 < i <= len(o) and o[i - 1].strip()
                        else en if 0 < i <= len(e) and e[i - 1].strip()
                        else None)
                if pick is None:
                    lost.append(f"{tag}: L{i}")
                else:
                    pick.setdefault(i, []).append(tag)
            continue
        if head == "headings gone or renamed":
            title = ln.split(" — ")[0].strip()
            i = ip_find_line(title, o, set(on), loose=True)
            if i:
                on.setdefault(i, []).append(tag)
            else:
                lost.append(f"{tag}: {title}")
            continue
        if hlines:
            side = en if head in IP_EDIT_SIDE else on
            for i in hlines:
                side.setdefault(i, []).append(tag)
        else:
            lost.append(f"{tag}: {ln.strip()[:60]}")
    tidy = lambda d: {k: sorted(set(v)) for k, v in d.items()}
    return tidy(on), tidy(en), lost


def ip_hunks(src, why, dels, sign="-"):
    """Prose findings get a hunk with context. A lone token gets one line."""
    ns = sorted(n for n in why if 0 < n <= len(src))
    if not ns:
        return []
    prose = {n for n in ns if any(ip_kind(x) not in IP_TOKY for x in why[n])}
    solo = [n for n in ns if n not in prose
            and not any(abs(n - p) <= 2 * IP_CTX + 1 for p in prose)
            and len(src[n - 1].strip()) <= IP_FITS]
    ns = [n for n in ns if n not in solo]
    chunks = []
    if ns:
        groups, cur = [], [ns[0]]
        for x in ns[1:]:
            if x - cur[-1] <= 2 * IP_CTX + 1:
                cur.append(x)
            else:
                groups.append(cur)
                cur = [x]
        groups.append(cur)
        for g in groups:
            out = []
            lo, hi = max(1, g[0] - IP_CTX), min(len(src), g[-1] + IP_CTX)
            out.append(f"@@ L{lo}-{hi}")
            for n in range(lo, hi + 1):
                txt = src[n - 1]
                if not txt.strip() and n not in why:
                    continue
                if n in why:
                    mark = sign if (dels is None or n in dels) else "~"
                    out.append(f"{mark} {txt}".rstrip()
                               + f"    ← {' + '.join(why[n])}")
                else:
                    out.append(f"  {txt}".rstrip())
            chunks.append((lo, out))
    for n in solo:
        chunks.append((n, [f"{sign} L{n:<5} {src[n - 1].strip()}"
                           f"    ← {' + '.join(why[n])}"]))
    return [ln for _, block in sorted(chunks, key=lambda c: c[0])
            for ln in block]


def ip_render(orig, edit, report):
    """The report, shown where the losses sit instead of grouped by check."""
    o, e = orig.splitlines(), edit.splitlines()
    dels, adds = set(), set()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, o, e, autojunk=False).get_opcodes():
        if tag in ("delete", "replace"):
            dels.update(range(i1 + 1, i2 + 1))
        if tag in ("insert", "replace"):
            adds.update(range(j1 + 1, j2 + 1))
    on, en, lost = ip_parse(report, o, e, adds)

    out = ip_hunks(o, on, dels, "-")
    added = ip_hunks(e, en, None, "+")
    if added:
        out += ["", "findings on the edited side"] + added
    if lost:
        by = {}
        for x in lost:
            k, _, v = x.partition(": ")
            by.setdefault(k, []).append(v)
        out += ["", "could not place — no line in either file holds these"]
        for k, v in sorted(by.items(), key=lambda i: -len(i[1])):
            out.append(f"  {k} ({len(v)}): "
                       + ", ".join(x[:40] for x in v[:6])
                       + (f" … {len(v) - 6} more" if len(v) > 6 else ""))
    if not out:
        return "nothing flagged.\n"
    kinds = {}
    for tags in list(on.values()) + list(en.values()):
        pick = ip_kind(next((t for t in tags if ip_kind(t) not in IP_TOKY),
                            tags[0]))
        kinds[pick] = kinds.get(pick, 0) + 1
    tally = ", ".join(f"{v} {k}" for k, v
                      in sorted(kinds.items(), key=lambda i: -i[1]))
    out += ["", f"{len(on) + len(en)} lines carry a finding, in {len(on)} "
                f"place{'' if len(on) == 1 else 's'}"
                + (f" plus {len(en)} in the edit" if en else "")
                + (f", {len(lost)} unplaced" if lost else "")
                + (f" · {tally}" if tally else "")]
    return "\n".join(out) + "\n"


cmd_verify.__wrapped__ = _cmd_verify


def cmd_verify_cli(args):
    """`verify` from the command line. Same verdict `run` and `accept` see."""
    if not getattr(args, "in_place", False):
        rc = cmd_verify(args)
        print(_exit_line(rc))
        return rc

    args.verdict = False
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_verify(args)
    if rc == 2:
        sys.stdout.write(buf.getvalue())
        print(_exit_line(2))
        return 2
    try:
        orig = Path(args.original).read_text(encoding="utf-8")
        edit = Path(args.edited).read_text(encoding="utf-8")
    except OSError:
        sys.stdout.write(buf.getvalue())
        print(_exit_line(2))
        return 2
    sys.stdout.write(ip_render(orig, edit, buf.getvalue()))
    print(_exit_line(rc))
    return rc

def _next_copy(src: Path) -> Path:
    """The first free `<stem>.copyN<ext>` beside `src`, N from 1."""
    n = 1
    while (c := src.with_suffix(f".copy{n}{src.suffix}")).exists():
        n += 1
    return c




def _print_crosscheck_notice(out):
    """The crosscheck warning, shared so `accept` and `accept --dry-run`
    print the identical line rather than the real path alone.
    """
    _cross = crosscheck_state(out)
    if _cross != "ok":
        _cross_why = {
            "missing": "no .kvcross sidecar exists beside this output",
            "stale": "the .kvcross sidecar is older than this output and "
                     "was ignored",
            "bad": "the .kvcross sidecar will not parse",
            "unavailable": "the crosscheck ran and found nobody to ask",
            "not-checked": "the .kvcross sidecar says the crosscheck did "
                           "not run, so no second model read this output",
        }.get(_cross, f"the .kvcross sidecar reads as {_cross!r}")
        _why_detail = crosscheck_not_checked_reason(out)
        if _why_detail:
            _cross_why = f"{_cross_why} ({_why_detail})"
        print(f"\nNothing here has crosschecked this output for meaning: "
              f"{_cross_why}. Run `kill-verbosity crosscheck "
              f"{shlex.quote(str(out))}` before trusting it -- accept does "
              f"not refuse on this, it only took the text.")
    elif crosscheck_findings(out) is None:
        print(f"\nThe .kvcross sidecar says this was crosschecked, but it "
              f"was written before this build could record what the "
              f"reviewer found -- it cannot tell you clean from unread. "
              f"Run `kill-verbosity crosscheck {shlex.quote(str(out))}` "
              f"again before trusting it.")


def cmd_accept(args):
    """Put the run's output in place of the input, in one step."""
    src = Path(args.file)
    out = Path(args.edited) if args.edited else src.with_suffix(f".kv{src.suffix}")
    if not out.is_file():
        print(f"kill-verbosity: no run output at {out}. Run it first.",
              file=sys.stderr)
        return 2
    if src.is_file() and out.samefile(src):
        print("kill-verbosity: those are the same file.", file=sys.stderr)
        return 2
    record = read_run_record(out)
    spans = record.get("incomplete") or []
    forced = os.environ.get("KV_FORCE") == "1"
    forced_past = []
    state = record_state(out)
    if state != "ok":
        why = {"missing": "there is no run record at",
               "stale": "the run record belongs to an earlier run,",
               "bad": "the run record will not parse,"}[state]
        if not forced:
            print(f"\nnot accepted: {why} {run_record_path(out).name}, so "
                  f"nothing here knows whether that run finished. Without it "
                  f"an incomplete run looks exactly like a clean one.\n"
                  f"Rerun to write a new one. KV_FORCE=1 takes the output as "
                  f"it is.", file=sys.stderr)
            return 1
        forced_past.append(f"{why} {run_record_path(out).name}, so nothing "
                           f"knows whether that run finished")
    was = record.get("source")
    if was and was != source_fingerprint(src.read_text(errors="replace")):
        if not forced:
            print(f"\nnot accepted: {src.name} changed after the run that "
                  f"wrote {out.name}, so accepting would throw those changes "
                  f"away.\nDiff the two, then rerun on the current file. "
                  f"KV_FORCE=1 takes the output as it is and loses the "
                  f"change.", file=sys.stderr)
            return 1
        forced_past.append(f"{src.name} changed after the run that wrote "
                           f"{out.name}, and that change is now gone")
    if spans:
        if not forced:
            print(f"\nnot accepted: the run that wrote {out.name} left "
                  f"{len(spans)} span(s) unedited, so the file is incomplete:",
                  file=sys.stderr)
            for _s, _n in Counter(spans).most_common():
                print(f"  {_s}{'' if _n == 1 else f'  ×{_n}'}",
                      file=sys.stderr)
            print("Delete the output and rerun with a different --agent. "
                  "KV_FORCE=1 takes it as it is.", file=sys.stderr)
            return 1
        forced_past.append(f"the run left {len(spans)} span(s) unedited")
    _inner = argparse.Namespace(original=str(src), edited=str(out),
                                chat=args.chat, exempt=[],
                                freeze=getattr(args, "freeze", None),
                                project=getattr(args, "project", None),
                                searched=getattr(args, "searched", None),
                                gates_file=getattr(args, "gates_file", None))
    rc = cmd_verify(_inner)
    _blind = getattr(_inner, "gates_blind", None) or []
    if _blind:
        if not forced:
            print(f"\nnot accepted: {len(_blind)} declared check(s) passed "
                  f"with {{edited}} pointed at a path that does not exist, so "
                  f"they are reading a fixed path of their own and have never "
                  f"judged this edit: {', '.join(_blind)}.\nMake each take "
                  f"the path it is given, or say so once by name: "
                  f"KV_GATE_BLIND_OK={','.join(_blind)}. KV_FORCE=1 takes the "
                  f"output as it is and excuses every other refusal with it.",
                  file=sys.stderr)
            return 1
        forced_past.append(f"{len(_blind)} declared check(s) never read the "
                           f"edit: {', '.join(_blind)}")
    if rc not in (0, 3):
        if not forced:
            print("\nnot accepted: verify says something broke. Rerun it, or "
                  "fix the tool and rerun. Do not lift edits out of the "
                  "output by hand — set KV_FORCE=1 if you have read the diff "
                  "and want it anyway.", file=sys.stderr)
            return 1
        forced_past.append("verify says something broke")
    if record.get("no_agents"):
        if not forced:
            print("\nnot accepted: this run called no specialist, so the "
                  "output IS the input and there is nothing here to accept. "
                  "Every other check passed — which is what you were "
                  "measuring. Run without --no-agents to produce an edit, or "
                  "KV_FORCE=1 to copy the file over itself and clear the "
                  "sidecar.", file=sys.stderr)
            return 1
        forced_past.append("this run called no specialist, so there was "
                           "nothing to accept")
    _cands = ([src] if src.stem.endswith(".orig")
              else [baseline_path(src, out, explicit_out=bool(args.edited)),
                    src.with_suffix(f".orig{src.suffix}")])
    base_copy = next((c for c in _cands if c.is_file()), None)
    where = ("gone unless git has it" if base_copy is None
             else base_copy.name if base_copy.parent == src.parent
             else str(base_copy))
    if getattr(args, "dry_run", False):
        print(f"\ndry run: nothing was copied and {src.name} is "
              f"unchanged. `accept` here would replace it with "
              f"{out.name}, keeping {_next_copy(src).name} as a copy of "
              f"{src.name} as it stands now. The text before the first "
              f"run: {where}.")
        if forced_past:
            print(f"It would only go through because KV_FORCE=1 overrules: "
                  f"{'; '.join(forced_past)}.")
        _print_crosscheck_notice(out)
        return 4 if forced_past else 0
    kept = _next_copy(src)
    shutil.copyfile(src, kept)
    print(f"\n{src.name} → {kept.name} (copy kept before the write)")
    shutil.copyfile(out, src)
    run_record_path(out).unlink(missing_ok=True)
    print(f"\n{out.name} → {src.name}. The text before the first run: {where}.")
    _print_crosscheck_notice(out)
    if rc == 3:
        print("The REVIEW above is unanswered: this command records no "
              "decision about any of it, and the file is already replaced. "
              "Read those blocks against the diff now, or say in your report "
              "that nobody did.")
    if not forced_past:
        return 0
    print(f"\nKV_FORCE overruled: {'; '.join(forced_past)}.")
    for s in spans:
        print(f"  still unedited: {s}")
    print("Say in your report that you forced it, and what you read in "
          "the diff.")
    return 4


FAMILY = {"codex": "openai", "openai": "openai", "gpt": "openai",
          "agy": "google", "gemini": "google", "google": "google",
          "antigravity": "google",
          "claude": "anthropic", "anthropic": "anthropic"}


def same_family(answered, wrote):
    """True when the backend that answered is the vendor that wrote the edits."""
    if isinstance(wrote, (list, tuple)):
        return any(same_family(answered, w) for w in wrote)
    mine = ({FAMILY[wrote.lower()]} if wrote.lower() in FAMILY
            else _families(wrote))
    return bool(mine & _families(answered))


def _families(text):
    """Every vendor a word of `text` names."""
    return {FAMILY[w] for w in re.findall(r"[a-z-]+", text.lower())
            if w in FAMILY}


def _no_writer_reason(target):
    """Why nothing names who wrote `target`'s edits -- one phrase, `record_state`'s
    three failures plus the ordinary case of a record naming no writer at all.
    """
    base = {"missing": "no .kvrun record exists beside this file",
            "stale": "the .kvrun record is older than the file and was "
                     "ignored",
            "bad": "the .kvrun record could not be read"}.get(
        record_state(target), "the .kvrun record names no writer")
    if crosscheck_state(target) == "missing":
        return base
    return f"{base}, and its .kvcross sidecar names no writer either"


def same_family_state(reviewer, writers, target):
    """`(True|False|"unknown", reason)` for the same-family check, never a
    silent `None`.
    """
    if not writers:
        return "unknown", _no_writer_reason(target)
    return same_family(reviewer, writers), None


GROUNDED_BACKENDS = LOCAL_AGENTS

CROSSCHECK_NOT_CHECKED = 5


def crosscheck_default_backend():
    """The reviewer when nothing named one: the first installed of codex, agy,
    claude, delegate, and `codex` when none is installed (its failure then
    says so).
    """
    return next((b for b in ("codex", "agy", "claude", "delegate")
                 if agent_installed(b)),
                "codex")


def crosscheck_offer(wrote):
    """The backends that can actually serve a crosscheck of a run `wrote` made."""
    return [b for b in GROUNDED_BACKENDS
            if not (wrote and same_family(b, wrote))]


def crosscheck_remedy(wrote):
    """The whole remedy sentence, and it claims only what this side knows."""
    usable = crosscheck_offer(wrote)
    if not usable:
        return ("Every file-capable backend is the one that wrote these edits, "
                "so there is no second opinion to be had here.")
    excl = " other than the one that wrote the edits" if wrote else ""
    return (f"Pass --backend, or set KV_BACKEND, to a file-capable backend{excl}: "
            f"{' '.join(usable)}. "
            "Only installation is checked here — a quota-walled agent looks "
            "the same from this side as a working one.")


def sandbox_copies(box, paths):
    """Copy each real path into `box`, one subdirectory apiece."""
    out = {}
    for i, p in enumerate(paths):
        sub = Path(box) / f"f{i}"
        sub.mkdir()
        copy = sub / p.name
        shutil.copy2(p, copy)
        out[p] = copy
    return out


def unsandbox(text, mapping, box):
    """Put the real paths back into the reviewer's answer."""
    subs = []
    for real, copy in mapping.items():
        subs.append((str(copy), str(real)))
        subs.append((str(copy.relative_to(box)), str(real)))
    for frm, to in sorted(subs, key=lambda s: -len(s[0])):
        text = text.replace(frm, to)
    return text


def crosscheck_backend(args):
    """Which model reads the result. `--backend`, else `KV_BACKEND`, else
    `crosscheck_default_backend()`.
    """
    named = getattr(args, "backend", None) or os.environ.get("KV_BACKEND")
    return agent_name(named) if named else crosscheck_default_backend()


def editable_table_rows(tables, frozen=()):
    """How many table rows a specialist can rewrite without a shape firing."""
    return sum(1 for l, _ in tables if l not in frozen)


def config_note(project, searched):
    """Whether a `.killverbosity.json` governs this file, or ""."""
    if project:
        return f"config: {project}"
    if searched:
        return (f"config: none declared, so no freeze and no refuse govern "
                f"this file (searched upward from "
                f"{', '.join(dict.fromkeys(searched))})")
    return ""


def status_table_note(lines, full=True):
    """One advisory line when a table here has a Status/State header, or ""."""
    n = sum(1 for ln in lines
            if TABLE_ROW.match(ln) and _table_header_has_status(ln))
    if not n:
        return ""
    if not full:
        return (f"  {n} table{'' if n == 1 else 's'} here carry a "
                f"Status/State column — read the diff by hand "
                f"(--full for why).")
    return (f"  {n} table{'' if n == 1 else 's'} here carry a Status/State "
            f"column — that shape is usually another tool's parsed state (a "
            f"tracker, a monitor, a queue), not this document's reference "
            f"material. Nothing here refuses on it; read the rewritten rows "
            f"in the diff by hand.")


def table_caveat(tables, frozen=(), full=True):
    """What to say about table rows before the run, or ""."""
    n = editable_table_rows(tables, frozen)
    if not n:
        return ""
    if not full:
        return (f"  {n} table row{'' if n == 1 else 's'}: cell text is "
                f"scanned and editable — read the diff by hand "
                f"(--full for why).")
    _bl = [f"`{s}`" for s in sorted(CELL_BLIND)]
    blind = " and ".join([", ".join(_bl[:-1]), _bl[-1]] if len(_bl) > 1
                         else _bl)
    return (f"  {n} table row{'' if n == 1 else 's'}: cell text IS scanned, "
            f"against every shape but {blind}, so a hit can be reported inside "
            f"a cell — and a cell can also be rewritten by a specialist "
            f"working the span around it, while verify only holds a cell that "
            f"carries a "
            f"number, path, ticket or link. Read table rows in the diff by "
            f"hand. If anything PARSES this file per row — a status monitor, a "
            f"gate, a script counting cells — a rewrite that keeps the meaning "
            f"can still break it, and nothing here can see that: do not run "
            f"this on a file that is another tool's state.")


def tail_note(tail, timeout, no_budget=False, sent=None):
    """How much of this run happened after `--timeout` stopped governing."""
    if no_budget or not timeout:
        return (f"\nThis run spent {tail:.0f}s after the last job was sent — "
                f"the merge, verify and this report. If you ever set "
                f"--timeout, it governs only the sending, so leave at least "
                f"that much under whatever outer limit you run below.")
    margin = f"{max(tail, 1.0):.0f}s"
    measured = (f"this run took {sent:.0f}s to send"
                if sent else "the sending is not timed on this path")
    return (f"\nTail: {tail:.0f}s after the last job was sent (merge, verify, "
            f"this report). --timeout {timeout:.0f} governs the sending only; "
            f"{measured}, so the wall clock was about {(sent or 0) + tail:.0f}s "
            f"— set the next --timeout at least {margin} under your outer "
            f"limit, not just under it.")


def measurement_note(by_kind):
    """Say what a pardoned NUMBER costs, which is not what a pardoned ref costs."""
    nums = by_kind.get("number") or []
    if not nums:
        return
    print(f"      of these, {len(nums)} "
          f"{'is a number' if len(nums) == 1 else 'are numbers'} — a ref can "
          f"be looked up again and a measurement cannot, so read "
          f"{'this one' if len(nums) == 1 else 'these'} against wherever "
          f"{'it was' if len(nums) == 1 else 'they were'} registered before "
          f"you accept.")


NEGATED = re.compile(
    r"\b(?:not|no|never|none|nothing|nobody|nowhere|cannot|can't|won't|don't"
    r"|doesn't|didn't|isn't|aren't|wasn't|weren't|shouldn't|wouldn't|couldn't"
    r"|mustn't|hasn't|haven't|hadn't|nor|neither|without|unable|fails? to)\b",
    re.I)


def polarity_flip(was, now):
    """True when one side of a swap is negated and the other is not."""
    return bool(NEGATED.search(was or "")) != bool(NEGATED.search(now or ""))


def run_notes_prompt(record):
    """What the reviewer has to be told about the run, or ""."""
    note = ""
    gone = sorted({t for t in record.get("exempt") or [] if t})
    if gone:
        note += (
            " The run deliberately removed these references: "
            + ", ".join(gone[:40]) + ". Each was a label the reader could not "
            "resolve, and removing it is a specialist's documented job. Do "
            "not report any of them as a lost fact.")
    if record.get("summary_added"):
        note += (
            " This run INSERTED the opening summary. A summary restates what "
            "the sections below say, each with a pointer to where it is said, "
            "and writing one was this run's job. Do not report it as a fact "
            "stated twice, and do not ask for it to be removed. Judge it on "
            "whether each line is accurate and each pointer resolves.")
    return note


def owner_report(owned, prefix, fold_spans):
    """The ownership block: the counts, then the lines behind each count."""
    by_owner = defaultdict(list)
    for r in owned:
        by_owner[r[2][len(prefix):].strip()].append(r[0])
    order = sorted(by_owner.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    out = [f"\nwent to the line's owner ({len(owned)}) — the ownership rule, "
           f"not a gate: "
           + ", ".join(f"{len(v)} to {w}" for w, v in order)]
    for w, lns in order:
        out.append(f"  to {w:<9} " + " ".join(
            _wrapping.label(ln, ln, fold_spans) for ln in sorted(set(lns))))
    return out


def crosscheck_prompt(target, orig, simplified):
    """The instruction the second opinion is given, and what it may assert."""
    if orig:
        return (
            f"Compare {orig} (original) with {target} "
            f"(simplified). Report two things. First, any fact, caveat, number or "
            f"disagreement present in the original and missing or weakened in the "
            f"simplified version. Second, what is still verbose in the simplified "
            f"version: framing sentences that delay the point, hedges, opinion "
            f"wrappers, facts stated twice, jargon a non-specialist would not know, "
            f"internal IDs used without saying what they mean."
        )
    return (
        f"Read {target}. "
        + ("It has been simplified. Find what is still verbose: "
           if simplified else "Find what is verbose: ")
        + "framing sentences that delay the point, hedges, opinion wrappers, "
        "facts stated twice, jargon a non-specialist would not know, and "
        "internal IDs used without saying what they mean."
    )


def cmd_crosscheck(args):
    """Returns (exit status, kinds found). Always the pair."""
    try:
        crosscheck_backend(args)
    except UsageError as e:
        print(f"kill-verbosity: {e}", file=sys.stderr)
        return 2, Counter()
    real_target = Path(args.file).resolve()
    real_orig = Path(args.original).resolve() if args.original else None
    real_extra = [Path(c).resolve()
                  for c in getattr(args, "context", None) or []]
    for p in (real_target, real_orig):
        bad = not_markdown(p) if p else None
        if bad:
            print(f"kill-verbosity: {bad}", file=sys.stderr)
            return 2, Counter()
    for p in (real_target, real_orig, *real_extra):
        if p and not p.is_file():
            print(f"kill-verbosity: {p} does not exist, so there is nothing "
                  f"to check.", file=sys.stderr)
            return 2, Counter()
    box = tempfile.mkdtemp(prefix="kv-xcheck-")
    look = sandbox_copies(box, [p for p in [real_target, real_orig, *real_extra]
                                if p])
    target, orig = look[real_target], look[real_orig] if real_orig else None
    record = read_run_record(real_target)
    prompt = crosscheck_prompt(target, orig, bool(record))
    extra = [str(look[p]) for p in real_extra]
    if extra:
        prompt += (" Read these too and judge the document against them: "
                   + ", ".join(extra) + ".")
    prompt += run_notes_prompt(record)
    _stale = rerun.moved_note(
        real_orig.name, real_target.name, real_orig.stat().st_mtime,
        real_target.stat().st_mtime, record.get("source"),
        source_fingerprint(real_orig.read_text(errors="replace"))
    ) if real_orig else None
    if _stale:
        prompt += (
            f" IMPORTANT — the two files are NOT a matched pair: {_stale} So a "
            f"fact present in the original and absent from the edited file may "
            f"never have been deleted; it may have arrived in the original "
            f"after the edit was made. Do not report a lost fact unless the "
            f"edited file contradicts the original, and never propose "
            f"restoring a number from the original into the edited file.")
    kind = getattr(args, "genre", None)
    if kind is None and getattr(args, "profile", None) and PROFILE_GENRE:
        kind = PROFILE_GENRE
    if kind is None:
        try:
            whole = real_target.read_text(errors="replace")
            kind = detect_genre(whole.split("\n"),
                                mask(whole, real_target.name)[1])
        except (OSError, ValueError):
            kind = None
    prompt += (
        " Third, any finding, recommendation or action that is missing a part: "
        "the problem it fixes, the change to make, or what stops going wrong "
        "once the change lands. Flag a fault with no change attached and a verb "
        "the reader cannot execute."
        + ("" if kind in ("transcript", "log", "checklist") else
           " Flag any sentence naming who is busy instead of what changes.")
        + " You only know what these files say. Never invent a name, an owner, a "
        "number or a value the document does not already contain. When one is "
        "missing, say so in 'problem' — \"the owner is not stated in the "
        "document\" — and make the fix \"name the owner\", not a name you "
        "chose. Do not ask for an owner at all unless the document names "
        "owners elsewhere."
        " A gap the document declares is not a gap. When the document says a "
        "decision is open, an owner is not yet assigned or a number is not yet "
        "measured, that is a stated fact and there is nothing to fix. Do not "
        "report it."
        " A path, filename, command, ticket or identifier attached to a claim "
        "is a citation, not jargon: it is what makes the claim checkable, and "
        "removing or glossing it deletes the evidence. You hold only the files "
        "named above, so you cannot open what a citation points at, and its "
        "absence from your view is not a finding. Report a reference only when "
        "this document is where it must resolve and does not — a bare "
        "\"Decision 11\" in a document carrying no decision list."
        " Shortening is the job. Do not report text as missing because the "
        "edited file says it in fewer words, and do not ask for anything to be "
        "restored unless the fact itself is gone. Cite the edited file in "
        "every entry."
        " Quote the exact line you are judging, with its line number. Plain "
        "simple English, no summary sections, and use exactly this shape per "
        "entry:\n"
        "- problem: <what goes wrong today>\n"
        "  kind: <one of: reversed_rule, weakened_rule, lost_fact, verbose, "
        "missing_part>\n"
        f"  file: <the full path as given above, then :line — "
        f"start it with {target.anchor or '/'}>\n"
        "  fix: <the change to make>\n"
        "  solves: <what stops going wrong once the fix lands>\n"
        "Every entry must have all five lines. Omit the entry if you cannot "
        "fill 'solves'. Use 'reversed_rule' when the edit inverted, negated or "
        "reversed an instruction, and 'weakened_rule' when it turned an "
        "instruction into a description or a requirement into an option. Those "
        "two stop the run; be exact with them."
        " Read the diff between the two files first, and judge what this "
        "change did. A fault the original already had is not this run's, so "
        "do not report it unless the change made it worse."
        " One entry per problem. Where the same problem repeats, write it "
        "once and list the line numbers in 'file'."
        " Never put a code span from the document inside a double-quoted "
        "shell string. To search for one, write the pattern to a file and "
        "pass it with `rg -F -f`."
        " Write no files. Your answer is the report; a scratch script or a "
        "saved diff is not part of it.")
    backend = crosscheck_backend(args)
    # Nobody named the reviewer: walking to the next installed one is the
    # default behaviour, not an error, so it is not printed.
    _loud = bool(getattr(args, "backend", None) or os.environ.get("KV_BACKEND"))
    _wrote_before = answering_backends(read_run_record(real_target))
    _wrote_before_via = ".kvrun" if _wrote_before else None
    if not _wrote_before:
        _wrote_before = cross_writers(real_target)
        if _wrote_before:
            _wrote_before_via = ".kvcross"
    if not agent_installed(backend):
        _alt = next((b for b in crosscheck_offer(_wrote_before)
                     if b != backend and agent_installed(b)), None)
        if _alt is None:
            _tried = list(dict.fromkeys([backend, *crosscheck_offer(_wrote_before)]))
            _fam = (", ".join(sorted(_families(" ".join(_wrote_before))))
                    if _wrote_before else "the writer")
            _reason = (f"{backend} is not installed; no other agent outside "
                       f"{_fam} is installed (tried: {', '.join(_tried)})")
            if not any(local_availability().values()):
                _reason += f". {NO_AGENT}"
            print(f"crosscheck: not checked -- {_reason}", file=sys.stderr)
            _sf0, _sf0_why = same_family_state(backend, _wrote_before,
                                               real_target)
            write_crosscheck_record(
                real_target, backend=backend, answered_by=None,
                wrote=_wrote_before, same_family=_sf0,
                same_family_reason=_sf0_why, checked=False,
                not_checked_reason=_reason, dispatched=[])
            return CROSSCHECK_NOT_CHECKED, Counter()
        if _loud:
            print(f"crosscheck: {backend} is not installed; falling to {_alt}.",
                  file=sys.stderr)
        backend = _alt
    tried_walk = []
    _failed_reasons = []
    try:
        while True:
            _sf_before, _sf_before_why = same_family_state(backend, _wrote_before,
                                                            real_target)
            if _sf_before is True:
                _via_note = ("" if _wrote_before_via == ".kvrun" else
                             f" (named by its .kvcross sidecar -- the .kvrun "
                             f"record is gone)")
                _reason_family = (f"{backend} is the model that wrote these edits "
                                  f"({', '.join(_wrote_before)}); a model does not "
                                  f"find its own mistakes, so no second opinion was "
                                  f"asked for")
                print(f"kill-verbosity: {backend} is the model that wrote these edits "
                      f"({', '.join(_wrote_before)}{_via_note}). A model does not find "
                      f"its own mistakes. {crosscheck_remedy(_wrote_before)}",
                      file=sys.stderr)
                write_crosscheck_record(
                    real_target, backend=backend, answered_by=None,
                    wrote=_wrote_before, same_family=True,
                    same_family_reason=(None if _wrote_before_via == ".kvrun"
                                        else "writer named by .kvcross; its "
                                        "own .kvrun is gone"),
                    checked=False, not_checked_reason=_reason_family,
                    dispatched=list(tried_walk))
                return 2, Counter()
            if _sf_before == "unknown":
                print(f"kill-verbosity: the self-review check (same-family) did not "
                      f"run: {_sf_before_why}, so whether {backend} wrote these "
                      f"edits cannot be told. Read the diff yourself before trusting "
                      f"this review.", file=sys.stderr)
            _argv, _argv_err = _cli_argv(backend)
            if _argv_err:
                print(f"kill-verbosity: {_argv_err}", file=sys.stderr)
                return 2, Counter()
            cmd, _stdin = agent_command(backend, _argv, prompt,
                                        CROSSCHECK_TIMEOUT, grounded=True,
                                        workdir=box)
            if _stale and not tried_walk:
                print("kill-verbosity: " + _stale, file=sys.stderr)
            print(f"kill-verbosity: {backend} …", file=sys.stderr)
            _timed_out = False
            try:
                r = spawn.run_tree(cmd, timeout=CROSSCHECK_TIMEOUT, cwd=box,
                                   input=_stdin)
            except subprocess.TimeoutExpired:
                _timed_out = True
                r = subprocess.CompletedProcess(
                    cmd, 124, "", f"{backend} timed out after "
                    f"{CROSSCHECK_TIMEOUT}s")
            except OSError as e:
                print(f"kill-verbosity: could not run {cmd[0]}: {e}", file=sys.stderr)
                return 2, Counter()
            tried_walk.append(backend)
            left = sorted(p.name for p in Path(box).iterdir() if p.is_file())
            if left:
                print(f"kill-verbosity: the reviewer wrote {', '.join(left)} while it "
                      f"worked. Discarded with the copies.", file=sys.stderr)
                for _lp in left:
                    try:
                        (Path(box) / _lp).unlink()
                    except OSError:
                        pass
            if (backend == "claude" and r.returncode != 0
                    and claude_flag_missing(r.stderr + r.stdout)):
                _others = [b for b in crosscheck_offer(_wrote_before)
                           if b != "claude" and agent_installed(b)]
                print(f"kill-verbosity: the local `claude` on this machine does not "
                      f"accept {' '.join(CLAUDE_READONLY)}, so crosscheck cannot bound "
                      f"what the reviewer may do and did not run it. Upgrade `claude`, "
                      + (f"or pass --backend {' / '.join(_others)}."
                         if _others else
                         "or install codex or agy and pass it with --backend."),
                      file=sys.stderr)
                return 2, Counter()
            answer = ""
            _text = agent_answer(backend, r.stdout)
            if _text.strip() and r.returncode == 0:
                answer = unsandbox(_text.rstrip(), look, box)
                print(answer)
            noisy = [unsandbox(l, look, box)
                     for l in r.stderr.splitlines() if l.strip()]
            wrote = answering_backends(record)
            if not wrote:
                wrote = cross_writers(real_target)
            _reviewer = backend
            _reviewer_state = CROSSCHECK_OBSERVED
            _sf, _sf_why = same_family_state(_reviewer, wrote, real_target)
            if r.returncode != 0 or not answer:
                _died = (_why_it_died(r.stderr) or _why_it_died(_text)
                         or "no answer")
                _reason = (f"{backend} exited {r.returncode}: {_died}"
                           if r.returncode else f"{backend}: {_died}")
                _failed_reasons.append(_reason)
                if _loud and not _timed_out and r.returncode:
                    print(f"kill-verbosity: {backend} exited {r.returncode}. Last "
                          f"lines of its output:", file=sys.stderr)
                    for l in noisy[-12:]:
                        print(f"  {l[:160]}", file=sys.stderr)
                _next = next(
                    (b for b in crosscheck_offer(_wrote_before)
                     if b not in tried_walk and agent_installed(b)), None)
                if _next is None:
                    _excluded = [b for b in GROUNDED_BACKENDS
                                 if b not in crosscheck_offer(_wrote_before)
                                 and b not in tried_walk]
                    _reason_all = ("every installed non-writer agent failed -- "
                                   + "; ".join(_failed_reasons)
                                   + (f"; skipped as the writer's own "
                                      f"family: {', '.join(_excluded)}"
                                      if _excluded else ""))
                    print(f"crosscheck: not checked -- {_reason_all}",
                          file=sys.stderr)
                    write_crosscheck_record(
                        real_target, backend=backend, answered_by=None,
                        wrote=wrote, same_family=None,
                        same_family_reason=None, checked=False,
                        not_checked_reason=_reason_all,
                        dispatched=list(tried_walk))
                    return CROSSCHECK_NOT_CHECKED, Counter()
                if _loud:
                    print(f"crosscheck: {_reason}; falling to {_next}.",
                          file=sys.stderr)
                backend = _next
                continue
            _kinds = crosscheck_kinds(answer)
            write_crosscheck_record(
                real_target, backend=backend, answered_by=_reviewer,
                answered_by_state=_reviewer_state, wrote=wrote,
                same_family=_sf, same_family_reason=_sf_why, checked=True,
                not_checked_reason=None, dispatched=list(tried_walk),
                findings=list(_kinds.elements()))
            return 0, _kinds
    finally:
        shutil.rmtree(box, ignore_errors=True)


MEANING_KINDS = ("reversed_rule", "weakened_rule", "lost_fact")


def crosscheck_kinds(answer):
    """Which `kind:` values the reviewer's entries carried."""
    return Counter(m.group(1) for m in re.finditer(
        r"^\s*(?:[-*]\s*)?kind:\s*[`\"']?([a-z_]+)", answer or "", re.M))


def _walk_returns(fn):
    """How many values each `return` in `fn` hands back. 1 unless it is a tuple."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    return [len(n.value.elts) if isinstance(n.value, ast.Tuple) else 1
            for n in ast.walk(tree)
            if isinstance(n, ast.Return) and n.value is not None]


def cmd_crosscheck_cli(args):
    """The command-line entry. `run` calls `cmd_crosscheck` for the pair."""
    rc, kinds = cmd_crosscheck(args)
    if rc == 0 and sum(kinds[k] for k in MEANING_KINDS):
        rc = 3
    print(_exit_line(rc))
    return rc


def _selftest_no_agents(args):
    """selftest stubs every agent call, so no agent need be on PATH. On Windows
    _cli_argv resolves the agent with shutil.which first; resolve the three
    known names to themselves for the whole run."""
    real = shutil.which
    shutil.which = lambda n, *a, **k: n if n in LOCAL_AGENTS else real(n, *a, **k)
    try:
        return cmd_selftest(args)
    finally:
        shutil.which = real


def cmd_selftest(_):
    if not __debug__:
        print("kill-verbosity: assertions are disabled (python3 -O or "
              "PYTHONOPTIMIZE), so selftest would check nothing and still "
              "report success. Run it without -O.", file=sys.stderr)
        return 2
    global _SHAPES_SEEN, SPECIALIST_DIR, _INSTALLED_OVERRIDE
    _SHAPES_SEEN = set()
    _saved_installed = _INSTALLED_OVERRIDE
    _INSTALLED_OVERRIDE = {"agy": True, "codex": True}
    t = "---\nname: x\n---\n# T\n\nreal prose here.\n\n```\nnot prose —— — —\n```\n\n" \
        "| a | it is worth noting b |\n\n> quoted — — —\n\n├── tree — — —\n"
    prose, heads, tables, _q = mask(t)
    assert [l for l in prose if l.strip()] == ["real prose here."], prose
    assert heads and heads[0][2] == "T", heads
    assert not em_dash_pressure(prose), "masked lines leaked into em-dash count"
    assert tables and "worth noting" in tables[0][1], tables

    assert any(c == "frame" for _, c, _ in find_shapes(prose, tables))

    for bad, why in (("# T\n\n```\nopen forever\n", "fence"),
                     ("---\nname: x\nstill open\n", "frontmatter")):
        try:
            mask(bad)
            raise AssertionError(f"unterminated {why} was accepted")
        except ValueError as e:
            assert "never closes" in str(e), e

    _pasted = "\n".join(f"{i}\tParagraph {i} about the redaction gate and scope."
                        for i in range(1, 31))
    try:
        mask(_pasted)
        raise AssertionError("a line-numbered paste was accepted")
    except ValueError as e:
        assert "line number" in str(e), e
    mask("# T\n\n1. first step\n2. second step\n3. third step\n")

    for _bad in ("I think this is quite clean.  <!-- kv:kep -->",
                 "<!-- kv:banana flaky -->"):
        try:
            mask(f"# T\n\n{_bad}\n\nMore prose.\n")
            raise AssertionError(f"a typo marker was accepted: {_bad}")
        except ValueError as e:
            assert "is not a marker" in str(e), e
    mask("# T\n\nHeld.  <!-- kv:keep -->\n\n<!-- kv:allow flaky -->\n\n"
         "<!-- kv:allow-shape parked problem -->\n\nBody.\n")

    _sub = ("# T\n\nA parked problem is a concern with no change attached.\n\n"
            "Nothing in this tool knows what a project does.\n")
    _sp, _sh, _st, _sq = mask(_sub)
    _before = {c for _, c, _ in find_shapes(_sp, _st, _sh, _sq)}
    assert {"parked problem", "inanimate perceiver"} <= _before, _before
    _sp2, _sh2, _st2, _sq2 = mask(
        "<!-- kv:allow-shape parked problem, inanimate perceiver -->\n" + _sub)
    _after = {c for _, c, _ in find_shapes(_sp2, _st2, _sh2, _sq2)}
    assert not ({"parked problem", "inanimate perceiver"} & _after), _after
    _sp3, _sh3, _st3, _sq3 = mask(
        "<!-- kv:allow-shape parked problem -->\n" + _sub)
    _left = {c for _, c, _ in find_shapes(_sp3, _st3, _sh3, _sq3)}
    assert "inanimate perceiver" in _left and "parked problem" not in _left, _left
    try:
        allowed_shapes(["<!-- kv:allow-shape inanimate perciever -->"])
        raise AssertionError("a misspelled shape name was accepted")
    except ValueError as e:
        assert "is not a shape" in str(e), e
        assert "'inanimate perceiver'" in str(e), e
    _ue_dir = tempfile.mkdtemp()
    _ue_a, _ue_b = Path(_ue_dir) / "a.md", Path(_ue_dir) / "b.md"
    _ue_a.write_text("# T\n\nIt works.\n", encoding="utf-8")
    _ue_b.write_text("# T\n\nIt works.\n", encoding="utf-8")

    def _ue_raise(_a):
        raise UsageError("'inanimate perceiver' is not a shape")

    def _ue_other(_a):
        raise RuntimeError("I/O operation on closed file")

    _ue_real, _ue_argv = cmd_verify_cli, sys.argv[:]
    _ue_err = io.StringIO()
    try:
        sys.argv = ["kill-verbosity", "verify", str(_ue_a), str(_ue_b)]
        globals()["cmd_verify_cli"] = _ue_raise
        try:
            with contextlib.redirect_stderr(_ue_err), \
                    contextlib.redirect_stdout(io.StringIO()):
                _ue_rc = main()
        except UsageError as _ue_esc:
            raise AssertionError(
                "main let a UsageError escape instead of turning it into "
                f"exit 2: {_ue_esc}") from None
        assert _ue_rc == 2, \
            f"main no longer turns a bad marker into exit 2: got {_ue_rc!r}"
        assert "is not a shape" in _ue_err.getvalue(), \
            f"main swallowed the one line the caller can act on: {_ue_err.getvalue()!r}"
        globals()["cmd_verify_cli"] = _ue_other
        try:
            with contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()):
                _ue_rc2 = main()
            raise AssertionError(
                f"main reported an incidental crash as usage: {_ue_rc2!r}")
        except RuntimeError:
            pass
    finally:
        globals()["cmd_verify_cli"] = _ue_real
        sys.argv = _ue_argv
        shutil.rmtree(_ue_dir, ignore_errors=True)

    assert not_markdown(Path("a.md")) is None
    assert not_markdown(Path("a.MD")) is None
    for _src in ("m6-config.py", "redact.ts", "main.go"):
        assert "not Markdown" in (not_markdown(Path(_src)) or ""), _src
    for _bak in ("a.md.bak", "a.md.orig", "a.MD.BAK"):
        assert not_markdown(Path(_bak)) is None, _bak
    for _no in ("a.md.py", "a.bak", "a.md.ts"):
        assert "not Markdown" in (not_markdown(Path(_no)) or ""), _no

    assert n_words("use `git status --porcelain -z` now") == 3
    assert n_words("see [the porcelain format](https://x/y) now") == 5
    _plain = "the team reviews each deployment and records the outcome"
    assert n_words(_plain) == len(_plain.split())

    assert snip("alpha beta gamma", 12) == "alpha beta…"
    assert snip("short", 12) == "short", "an uncut string keeps no mark"
    assert snip("x" * 20, 12) == "x" * 12 + "…", "no boundary: cut and mark"

    _, h, _, _ = mask("## Executive Summary\n\nbody here.\n")
    assert any(c == "corporate header" for _, c, _ in find_shapes([""], (), h))

    assert list(_split("See Fig. 1 now. Then stop.")) == \
        ["See Fig. 1 now.", "Then stop."]

    para = [(4, "First one here."), (5, "Second starts here."),
            (6, "Third is on its own line.")]
    assert [ln for ln, _ in sentences(para)] == [4, 5, 6], list(sentences(para))
    assert [ln for ln, _ in sentences([(9, "One. Two.")])] == [9, 9]

    dup = duplicates(["the quick brown fox jumps over the lazy dog today", "",
                      "the quick brown fox jumps over the lazy dog today"])
    assert dup and dup[0]["words"] >= 8, dup
    _paths = [f"/home/user/notes/.claude/{n}.md"
              for n in ("one", "two", "three", "four", "five", "six")]
    assert not duplicates(_paths), duplicates(_paths)
    assert not duplicates([f"see https://ex.io/a/b/c/d/e/f/{n}" for n in "xyz"])
    _mixed = [f"the gate refuses the edit when /a/b/c.py does not match", "",
              f"the gate refuses the edit when /d/e/f.py does not match"]
    assert duplicates(_mixed), _mixed

    _dbt = facts("a leading dot defeats it: `` `.env` `` is a code\n"
                 "token and bare `.env` is nothing.")["code"]
    assert _dbt == {"`.env`", ".env"}, _dbt

    f = facts("see `foo.bar` at https://x.io/a and INS-1112 plus 85% in path/to/f.py")
    assert "INS-1112" in f["ticket"] and "foo.bar" in f["code"], dict(f)
    assert "85%" in f["number"], f["number"]
    assert any("path/to/f.py" in p for p in f["path"]), f["path"]
    _dup = "see INS-1112 and INS-1112 again, plus 1.5 seconds and 1.5 seconds"
    _fc = facts(_dup, counted=True)
    assert _fc["ticket"] == Counter({"INS-1112": 2}), dict(_fc)
    assert _fc["number"] == Counter({"1.5s": 2}), dict(_fc)
    assert facts(_dup) == defaultdict(set, {k: set(v) for k, v in _fc.items()}), \
        (dict(facts(_dup)), dict(_fc))
    for punct in (".", ",", "!", ")"):
        assert facts(f"see https://x.io/a{punct}")["url"] == {"https://x.io/a"}, punct
        assert facts(f"is 85%{punct}")["number"] == {"85%"}, punct
    assert facts("takes 30 ms.")["number"] == {"30ms"}
    line = ("`/sl-init` sets up a repo — ADRs fetched, `CLAUDE.md` generated — "
            "in seconds. `/sl-technical-design` explores the codebase.")
    assert facts(line)["code"] == {"/sl-init", "/sl-technical-design"}, \
        sorted(facts(line)["code"])
    assert facts(line)["path"] == {"CLAUDE.md"}, sorted(facts(line)["path"])
    one = ("Importing source files with `@`. They load every session. `@` is "
           "allowed only for README, `compose.yml`, `.gitlab-ci.yml`.")
    assert facts(one)["code"] == {"@", ".gitlab-ci.yml"}, sorted(facts(one)["code"])
    assert facts(one)["path"] == {"compose.yml"}, sorted(facts(one)["path"])
    assert facts("see `OPS-3753` for the case")["ticket"] == {"OPS-3753"}
    assert facts("see OPS-3753 for the case")["ticket"] == {"OPS-3753"}
    for a, b in (("`OPS-3753`", "OPS-3753"), ("`CLAUDE.md`", "CLAUDE.md"),
                 ("`v1.2.3`", "v1.2.3"), ("`2026-08-07`", "2026-08-07")):
        assert facts(a) == facts(b), (a, b, dict(facts(a)), dict(facts(b)))
    assert facts("run `npm test` now")["code"] == {"npm test"}
    plain, marked = "run the review-agent now", "run the `review-agent` now"
    assert facts(marked)["code"] == {"review-agent"}
    assert not facts(plain)["code"]
    assert "review-agent" in plain and "rm -rf /data" not in plain
    blocks = ["```python\na\n```", "```bash\nb\n```", "```python\nc\n```"]
    a, b, c = blocks
    assert facts("\n".join([a, b, c]))["fence_lang"] == \
        {"python #1", "bash #1", "python #2"}, \
        facts("\n".join([a, b, c]))["fence_lang"]
    for order in (("b", "a", "c"), ("c", "b", "a"), ("b", "c", "a")):
        moved = "\n".join({"a": a, "b": b, "c": c}[k] for k in order)
        assert facts(moved)["fence_lang"] == facts("\n".join(blocks))["fence_lang"], \
            (order, facts(moved)["fence_lang"])
    assert facts("\n".join([a, b]))["fence_lang"] == {"python #1", "bash #1"}
    assert facts("```text\n```literal\n## fake\n```")["fence_lang"] == {"text #1"}
    for block in ("  ```\n  42 inside\n  ```", "````\n42\n```\nstill in\n````",
                  "~~~\n42 inside\n~~~"):
        assert not facts(f"text\n\n{block}\n")["number"], block

    assert (facts("see `tuned + every\nregion` now")["code"]
            == facts("see `tuned + every region` now")["code"]
            == {"tuned + every region"})
    assert not facts("the org/team owns retry/fallback")["path"]
    assert sorted(facts("in path/to/f.py, /etc/x.py, .claude/x.md, a/b/c")
                  ["path"]) == [".claude/x.md", "/etc/x.py", "a/b/c",
                                "path/to/f.py"]
    assert facts("scoring 22/26")["ratio"] == {"22/26"}
    assert facts("scoring 22/26") != facts("scoring 26/22")
    for spelling in ("4 of 8", "4-in-8", "4 in 8"):
        assert facts(f"hit {spelling}")["ratio"] == {spelling}, spelling
        assert facts(f"hit {spelling}") != facts(f"hit {spelling.replace('4', '3')}")
    for _j in ("/", " of ", " in "):
        _rp = f"`checkFlag` at 134 (was 101-124{_j}130-132)"
        assert not facts(_rp)["ratio"], (_rp, facts(_rp)["ratio"])
    assert facts("a 1-in-5 chance")["ratio"] == {"1-in-5"}
    assert facts("scoring 22/26")["ratio"] == {"22/26"}
    for word in ("grep", "run", "gcloud"):
        assert BARE_WORD.match(word), word
    for name in ("redact.ts", "prompt_id", "S16", "checkFlag", "kill-verbosity"):
        assert not BARE_WORD.match(name), name
    assert facts("takes 1.5 seconds") != facts("takes 1.5 minutes")
    assert facts("release v1.5.2")["version"] == {"v1.5.2"}
    assert facts("version 1.5 is out")["version"] == {"1.5"}

    assert facts("see ./README")["path"] == {"./README"}
    assert facts("run /sl-init")["path"] == set()
    assert facts("this and/or that")["path"] == set()

    _t0 = time.perf_counter()
    facts("aaaa." * 18000 + "/x")
    _took = time.perf_counter() - _t0
    assert _took < 3.0, (
        f"the path rule went quadratic again: {_took:.2f}s over 18,000 "
        f"segments, where linear measures ~0.19s and the uncapped rule measures ~64s")

    assert facts("edit src/main.py.")["path"] == {"src/main.py"}
    assert not facts("| 3 | row |\n| 10 | row |\n\n1. first\n2. second")["number"]
    assert facts("cut 3, then 4")["number"] == {"3", "4"}
    assert facts("about `47` items") == facts("about 47 items")
    assert facts("ships v1.2")["version"] == {"v1.2"}
    assert facts("ships v1.2") != facts("ships v1.3")
    assert facts("takes 5 seconds") != facts("takes 5 minutes")
    assert facts("takes 30 ms.")["number"] == {"30ms"}

    pairs, lost_, gained_ = pair_changed({"path": [".claude/x.md"]},
                                         {"path": [".claude/backup/x.md"]})
    assert pairs == [("path", ".claude/x.md", ".claude/backup/x.md")], pairs
    assert not lost_ and not gained_, (lost_, gained_)
    pairs, _, _ = pair_changed({"number": ["85%"]}, {"number": ["86%"]})
    assert pairs == [("number", "85%", "86%")], pairs
    assert re.search(
        r'if changed:\s*\n\s*hard = _failed_block\("TOKENS EDITED"\)',
        inspect.getsource(cmd_verify)), \
        "a paired change still has to fail the run"
    pairs, lost_, _ = pair_changed({"ticket": ["OPS-1"]}, {"path": ["a/b/c.py"]})
    assert not pairs and lost_ == {"ticket": ["OPS-1"]}, (pairs, lost_)

    tail = duplicated_tail(["The address exclusion rule only",
                            "the address exclusion rule only does anything."])
    assert tail and tail[0][0] == 2, tail
    assert not duplicated_tail(["A whole sentence here.", "Another one here."])
    assert duplicated_tail(["rules fall from 82% to 17% on new wording.",
                            "wording, which is what the drop shows"]), \
        "a one-word repeat across a break is still a repeat"
    for a, b in (("the check is fed by", "Model Armor and the DLP scanner."),
                 ("this is how the model is reached), **Gateway**",
                  "key-first), and **the proxy**"),
                 ("it will not catch \"X causes Y\" turned into \"X does not",
                  "Y\". It cannot protect a fact carrying no number."),
                 ("the field is called status.", "Status is optional here."),
                 ("we track the cost.", "Cost is the blocker."),
                 ("it returns a Model.", "Model Armor then runs.")):
        assert not duplicated_tail([a, b]), (a, b)
    assert duplicated_tail(["the field is called **status**.",
                            "**status**, which the caller reads"]), \
        "markdown around the first word hides a repeat"
    dup = duplicated_tail(
        ["A measurement nobody can check is worth less. These first real numbers",
         "the first real numbers this work will produce and they will be read."])
    assert dup == [(2, "the first real numbers")], dup
    for a, b in (("This is the first real test.",
                  "The first thing to note is unrelated entirely here."),
                 ("we ship on Monday.",
                  "The team is ready for it and nothing else blocks.")):
        assert not duplicated_tail([a, b]), (a, b)
    assert tail_added("a rule can collide", "x",
                      "a rule can collide", "a rule can collide")
    assert not tail_added("", "the same words here", "the same words here",
                          "the same words here again")
    assert tail_added("a head that can collide", "with the tail",
                      "A head that can collide with the tail", "")

    linked = "# The decision\n\nSee [the decision](#the-decision).\n"
    assert not broken_anchors(linked), broken_anchors(linked)
    renamed = linked.replace("# The decision\n",
                             "# Use Model Armor advanced mode\n", 1)
    assert broken_anchors(renamed) == {"the-decision"}, broken_anchors(renamed)
    for title, anchor in (("What is already known?", "what-is-already-known"),
                          ("The eleven open items", "the-eleven-open-items"),
                          ("`run` and `verify`", "run-and-verify")):
        doc = f"# {title}\n\n[x](#{anchor})\n"
        assert not broken_anchors(doc), (title, broken_anchors(doc))
    assert broken_anchors("# A\n\n[x](#gone)\n") == {"gone"}

    sumdoc = ["# Rollout", "", "## Summary — read this page, then pick what to "
              "read properly", "", "the result is here", "", "## Overview", "x"]
    s_ed = set(range(1, len(sumdoc) + 1))
    _g, ok, no, _ = merge(sumdoc, [{"specialist": "structure", "edits": [
        {"line": 3, "old": sumdoc[2],
         "new": "## Rollout status and decisions", "why": "corporate header"}]}],
        s_ed, (), (), 3)
    assert not ok and no and "summary heading" in no[0][2], (ok, no)
    got, ok, no, _ = merge(sumdoc, [{"specialist": "structure", "edits": [
        {"line": 3, "old": sumdoc[2], "new": "## Summary", "why": "shorter"}]}],
        s_ed, (), (), 3)
    assert ok and not no, (ok, no)
    assert got[2] == "## Summary", got
    _g, ok, no, _ = merge(sumdoc, [{"specialist": "structure", "edits": [
        {"line": 7, "old": "## Overview", "new": "## What we decided",
         "why": "name the decision"}]}], s_ed, (), (), 3)
    assert ok and not no, (ok, no)
    assert not facts("v1.2.3 ships")["number"]
    assert not facts("1.2.3 ships")["number"]
    assert facts("1.5% of runs")["number"] == {"1.5%"}
    assert not facts("1.5% of runs")["version"]
    assert facts("v1.5.2 ships")["version"] == {"v1.5.2"}
    assert facts("1.5 seconds")["number"] == {"1.5s"}
    assert (facts("the timeout is 60 seconds")["number"]
            == facts("the 60-second timeout")["number"]
            == facts("a 60s timeout")["number"] == {"60s"}), \
        facts("the 60-second timeout")["number"]
    assert facts("3 days")["number"] == facts("a 3-day wait")["number"] == {"3d"}
    assert facts("5 minutes")["number"] != facts("5 seconds")["number"]
    assert facts("60s")["number"] != facts("60 items")["number"]
    assert facts("200 MB")["number"] == {"200MB"}
    _n12 = "Application logs are held for 12 months here."
    assert not tokens_added(_n12, "Logs are held 12 months."), \
        tokens_added(_n12, "Logs are held 12 months.")
    assert not tokens_added(_n12, "Logs live 12 months; the 12 is fixed.")
    assert tokens_added(_n12, "Logs are held 30 months.") == "30mo"
    assert tokens_added("The gate is open.", "The gate is 47.") == "47"
    assert facts("was 101-124 rows")["number"] == {"101", "124"}
    assert facts("OWASP LLM Top 10, and")["number"] == {"10"}
    assert facts("cut 3, then 4")["number"] == {"3", "4"}
    assert facts("about 10,000 rows")["number"] == {"10,000"}
    assert facts("1,234,567 total")["number"] == {"1,234,567"}
    assert facts("La precision es del 69,0% y la tasa es del 4%. El p95 es 5,2 s.")["number"] == {"69,0%", "4%", "5,2s"}
    assert facts("steps 1,2,3")["number"] == {"1", "2", "3"}
    if any(lang in {"es", "pl"} for lang in ACTIVE_LANGS):
        assert facts("Sections 1,2 and 3")["number"] == {"1,2", "3"}
    else:
        assert facts("Sections 1,2 and 3")["number"] == {"1", "2", "3"}
    assert facts("in 2024, 5 people")["number"] == {"2024", "5"}
    assert facts("1,000,5")["number"] == {"1,000", "5"}
    assert facts("1,0000")["number"] == {"1,0000"}
    assert "INS-9999" not in facts("<!-- INS-9999 -->")["ticket"]
    assert "/etc/x.py" in facts("see /etc/x.py")["path"], facts("see /etc/x.py")["path"]
    tilde = facts("~~~python\nINS-1\n~~~\n")
    assert not tilde["ticket"], dict(tilde)
    two = facts("```py\na\n```\ntext\n```py\nb\n```\n")["fence_lang"]
    one = facts("```py\na\n```\n")["fence_lang"]
    assert len(two) == 2 and two - one, (two, one)

    assert [h[1] for h in find_shapes(["I think that the gate is closed"])] == ["wrapper"]
    assert {c for _, c, _ in find_shapes(["I think that is right. We should go."])} == \
        {"wrapper", "planning language"}
    assert not find_shapes(["the retry that we should keep"])
    assert not find_shapes(["the pipeline and the sandbox are fine"])
    assert find_shapes(["fixed in round-6 per G.3"])

    cases = [
        ("process leak", "Cross-checked by three external models.",
         "The gate rejects the request."),
        ("process leak", "Codex suggested folding the two calls together.",
         "Folding the two calls together removes a round trip."),
        ("process leak", "Gemini and codex both said the split is fine.",
         "The split is fine."),
        ("draft diff", "Two actions have been dropped since the first draft.",
         "Two actions remain."),
        ("draft diff", "The count had gone up before this pass, not down.",
         "53 checks are open."),
        ("commit or checkout ref", "This dates from Oct 2025 (`4737d6b`).",
         "This dates from Oct 2025."),
        ("commit or checkout ref", "Findings come from the local main checkout.",
         "Findings come from the current code."),
        ("asks reader to verify", "Confirm Batch serves it. That is unverified.",
         "Batch serves it."),
        ("asks reader to verify", "Worth confirming the quota before buying.",
         "The quota is 300 requests a minute."),
        ("unsourced citation", "Zhong et al. measured that at ~6.5%.",
         "Our run measured 6.5%."),
        ("unsourced citation", "Zhong et al. measured that at ~6.5%.",
         "[Zhong et al.](https://aclanthology.org/2020.emnlp-main.29/) measured 6.5%."),
        ("unexplained reference", "Decision 11 blocks this.",
         "Decision 11 — drop the retry — blocks this."),
        ("unexplained reference", "Overlaps 1357 is the worst case.",
         "The 1357 overlapping rows are the worst case."),
        ("unexplained reference", "Getting it wrong is report item 5.",
         "Row 12 of the results file shows the leak."),
        ("asks reader to verify", "That is unverified.",
         "Run it at minimal and check whether test quality drops."),
        ("asks reader to verify", "Residency rules that out. Confirm the gateway accepts it.",
         "Residency rules that out. The gateway accepts it."),
        ("planning language", "We should drop the retry.", "Drop the retry."),
        ("phase plan", "## Phase 2 - Rollout",
         "The resolver runs in phase 2 of the parse, after masking."),
        ("phase plan", "- Milestone 3: the exporter is wired.",
         "Milestone markers are drawn once per release."),
        ("phase plan", "Enablement completes in Q3 2026.",
         "The Q3 table is in the appendix."),
        ("task list", "- [ ] Wire the exporter",
         "- [see the note](notes.md) for the rest"),
        ("task list", "1. [ ] Ship the parser",
         "1. [x] Ship the parser"),
        ("task list", "- [ ] T6 PR2: model auto-discovery",
         "- [x] T5 PR1 run and verdicted."),
        ("task list", "- [ ] T11 fix-report",
         "1. The parser ships with the exporter."),
        ("task list", "  * [ ] Wire the exporter",
         "  * [x] Wire the exporter"),
        ("task list", "2) [ ] Ship the parser", "2) The parser ships."),
        ("estimate", "Rollout is about three weeks of work.",
         "The retry budget keeps three weeks of logs."),
        ("estimate", "Sized at 8 story points.",
         "The points table lists one score per run."),
        ("target date", "Target date: 2026-10-01",
         "The 2026-10-01 snapshot is the input."),
        ("target date", "The exporter ships in Q3.",
         "The exporter shipped in Q3 and has run since."),
        ("target date", "Done by end of March.",
         "The March build is the one under test."),
        ("target date", "Wire the exporter by EOW.",
         "The week ends on Friday."),
        ("worklog", "FIXED 2026-09-11 - the gate now reads the span.",
         "The cache expires on 2026-10-01."),
        ("worklog", "Re-derived 2026-09-07 by a second reader.",
         "Every threshold is read by the profile loader."),
        ("worklog", "Measured 2026-09-04 after five more stale assertions.",
         "The retry ran 2026-09-07 through the same chain."),
        ("worklog", "Confirmed 2026-09-10 by Dana.",
         "The 2026-09-07 snapshot is cached by the resolver."),
        ("worklog", "The parser was rewritten on 2026-08-21 by the reviewer.",
         "The 2026-09-07 export is parsed by the monitor every cycle."),
        ("worklog", "Section 4 was rewritten 2026-08-21 by the original author.",
         "The 2026-09-07 index is rebuilt by the indexer on every pass."),
        ("worklog", "The migration was signed off 2026-10-01 by the implementer.",
         "The migration is due 2026-10-01 and is owned by the implementer."),
        ("worklog", "The gateway was verified 9 September.",
         "The gateway sat at `5bb0c2a`, verified 9 September."),
        ("planning language", "The gate is closed. We should drop the retry.",
         "That reads like a limit we could raise."),
        ("planning language", "In the future this moves to Kafka.",
         "This moves to Kafka in v3."),
        ("process leak", "The earlier transcript says the retry is unsafe.",
         "The safety controls were reviewed by two independent auditors."),
        ("asks reader to verify", "Confirm Batch and Flex serve gemini-3.5-flash.",
         "Confirm the checksum matches before installing."),
        ("draft diff", "Two actions were removed from the first draft.",
         "The number had gone down after the treatment."),
        ("commit or checkout ref", "Built from `4737d6b`.",
         "We looked at defaced surfaces."),
        ("unsourced citation", "Zhong and colleagues measured that at 6.5%.",
         "Zhong et al.[^1] measured 6.5%."),
        ("planning language", "- We should move this to Kafka.",
         "The balance due in the future is discounted."),
        ("changelog narration", "Version 2 added a cache.",
         "The connection has been dropped by the server."),
        ("unexplained reference", "Decision 11 (see appendix) blocks this.",
         "Row 12 contains the total."),
        ("changelog narration", "The handler used to be called `run_all`.",
         "The handler is called `run_all`."),
        ("changelog narration", "This has since been renamed to `router`.",
         "This is `router`."),
        ("asks reader to verify", "Verify that the endpoint is active.",
         "The endpoint is active."),
        ("asks reader to verify", "Confirm this before quoting it.",
         "Confirm the checksum matches before installing."),
        ("bare internal id", "The gate rejects round-3.",
         "The gate rejects the third round."),
        ("draft diff", "In this updated version, we changed the timeout.",
         "The timeout is 30 s."),
        ("commit or checkout ref", "We verified this against checkout master.",
         "We verified this against the current code."),
        ("unsourced citation", "[Zhong et al.](about:blank) measured 6.5%.",
         "[Zhong et al.](https://aclanthology.org/2020.emnlp-main.29/) measured 6.5%."),
        ("number without its noun", "Worth switching on, from 83% to 86%.",
         "86% of values have a detector switched on, up from 83%."),
        ("number without its noun", "Coverage moves 61% → 80%.",
         "Coverage moves from 61% to 80% of branches."),
        ("identifier as subject", "LOCATION is matching field labels.",
         "DLP returned the Passport Number field as an address."),
        ("identifier as subject", "PASSWORD was never switched on.",
         "DLP was never pointed at the template."),
        ("evaluative adjective", "The address detector is loose.",
         "The address detector returned a field label as a place."),
        ("inanimate perceiver", "prompts the patterns never saw",
         "prompts written after the patterns"),
        ("bare nominalisation", "This blocks the invocation of the scorer.",
         "This blocks the scorer from running."),
        ("idiom", "The gate holds on paper.",
         "The gate holds in the config, and no run has tested it."),
        ("parked problem", "The 27 unresolved notes are a concern.",
         "27 notes are unresolved. Answer them, then merge MR !1."),
        ("parked problem", "Coverage should be addressed.",
         "Coverage is 61%. Add parser suites until it reaches 80%."),
        ("parked problem", "The identity model needs further thought.",
         "The identity model has no owner. Name one at sign-off."),
        ("parked problem", "Integrations with test management tools (Xray, TBD).",
         "Integrations with Jira and Xray ship in March 2026."),
        ("parked problem", "Authoring adoption by X% within the customer base.",
         "Authoring adoption by 30% of accounts."),
        ("parked problem", "Pricing defined (in collab with Billing team?)",
         "Pricing is defined with the Billing team by Feb 16, 2026."),
        ("parked problem", "The owner of the rollout is ???",
         "Dana owns the rollout."),
        ("vague action", "Look into the review-agent quality bar.",
         "Set the review-agent bar at 3 useful findings per 100 MRs."),
        ("vague action", "Worth revisiting the timeout later.",
         "Raise the timeout to 900 s for the importer."),
        ("vague action", "Keep monitoring the error rate.",
         "Monitor the error rate in Grafana and page above 2%."),
        ("activity report", "Sam has been looking at hooking telemetry to it.",
         "Sam owns the telemetry hook to the gateway."),
        ("commit or checkout ref", "Rebuilt from checkout main.",
         "The local Atlas checkout goes stale within a day."),
        ("identifier as subject", "LOCATION is matching field labels.",
         "AIX_DB is a Snowflake table with one row per run."),
        ("inanimate perceiver", "the rules never saw that prompt",
         "the model sees the whole file in one window"),
        ("citation plumbing", "In #platform on 8 May, Priya asked for a date.",
         "The rollout needs a date."),
        ("activity report", "Andrzej is already working with the managers on this.",
         "Andrzej publishes the per-team baseline by sign-off."),
        ("activity report", "The team has been working on the identity model.",
         "The parser is working on the wrong branch."),
        ("wrapper", "I think the gate is wrong.",
         "I feel the pressure of the deadline."),
        ("planning language", "I think we should drop the retry.",
         "The checks we must run are listed here."),
    ]
    for kind, dirty, clean in cases:
        got = {c for _, c, _ in find_shapes([dirty])}
        assert kind in got, f"{kind!r} missed on {dirty!r} (got {got or 'nothing'})"
        got = {c for _, c, _ in find_shapes([clean])}
        assert kind not in got, f"{kind!r} false-positive on {clean!r}"

    assert {c for _l, c, _t in find_shapes(["- [x] T5 PR1 run and verdicted."])} \
        == set(), find_shapes(["- [x] T5 PR1 run and verdicted."])
    assert {c for _l, c, _t in find_shapes(["- [ ] T5 PR1 run and verdicted."])} \
        == {"task list"}, find_shapes(["- [ ] T5 PR1 run and verdicted."])
    assert TASK_LINE.match("- [x] T5 PR1 run and verdicted.")
    assert not EXISTENCE["task list"].search("- [x] T5 PR1 run and verdicted.")

    assert "worklog" in {c for _l, c, _t in
                         find_shapes(["Fixed 2026-09-11; the due date moved."])}, \
        "the deadline pardon reached the completion-verb arm"
    assert "worklog" in {c for _l, c, _t in
                         find_shapes(["## Current status: due 2026-10-01"])}, \
        "the deadline pardon reached the section-opener arm"
    assert "worklog" in {c for _l, c, _t in find_shapes(
        ["The schema was renamed 2026-10-01 by the maintainer."])}, \
        "the attribution arm stopped firing, so the deadline pair holds nothing"

    def _cb_kinds(src):
        _p, _h, _t, _q = mask(src, "t.md")
        return {c for _l, c, _t2 in find_shapes(_p, _t, _h, _q)}, _t

    _cb_sent = "FIXED 2026-09-11 - the gate now reads the span."
    assert "worklog" in _cb_kinds(f"# T\n\n{_cb_sent}\n")[0], \
        "the prose control stopped firing, so the row case below holds nothing"
    _cr_got, _cr_rows = _cb_kinds(
        f"# T\n\n| id | status |\n|---|---|\n| F3 | {_cb_sent} |\n")
    assert _cb_sent in " ".join(t for _l, t in _cr_rows), _cr_rows
    assert "worklog" not in _cr_got, _cr_got
    assert "evaluative adjective" in _cb_kinds(
        "# T\n\n| id | note |\n|---|---|\n| F3 | a clean review of it |\n")[0]
    assert "worklog" in _cb_kinds(
        "## Status re-verified against the code, 2026-08-21\n\nbody\n")[0]

    chat_cases = [
        ("colon label", "Regionalne: detektory per kraj i numery.",
         "Regionalne detektory per kraj są warte włączenia."),
        ("message scaffold", "Do wklejenia:", "The gate rejects the request."),
        ("omission note", "Pominięte: pełna tabela. Dorzuć, jak dopyta.",
         "The full table is in the report."),
        ("buried lead", "Najważniejsze jest to: nie ma detektora na hasła.",
         "There is no password detector."),
        ("colon label", "Note: the gate is open.",
         "See https://example.com/x at 14:30 today."),
        ("corrects the reader", "You're conflating the two settings.",
         "The two settings are separate."),
        ("corrects the reader", "Nie, to co innego.", "To co innego."),
        ("sign-off", "Happy to take another look.",
         "The retry count is the one open question."),
        ("sign-off", "Let me know your thoughts.", "Which region do you want?"),
        ("sign-off", "Shout if you need anything else.", "Ping Dana on quota."),
        ("sign-off", "Hope that helps!", "That is the whole change."),
    ]
    for kind, dirty, clean in chat_cases:
        got = {c for _, c, _ in find_shapes([dirty], chat=True)}
        assert kind in got, f"{kind!r} missed on {dirty!r} (got {got or 'nothing'})"
        got = {c for _, c, _ in find_shapes([clean], chat=True)}
        assert kind not in got, f"{kind!r} false-positive on {clean!r}"
        assert kind not in {c for _, c, _ in find_shapes([dirty])}, \
            f"{kind!r} fired without --chat on {dirty!r}"

    _cs, _, _, _ = mask("# T\n\nAn allow-list — `weak\ncrypto`, `clean "
                        "checkout` — is the cheap version.\n")
    assert not any(c == "evaluative adjective" for _, c, _ in find_shapes(_cs)), \
        find_shapes(_cs)
    assert "`worklog`" not in "".join(mask("# T\n\n`worklog.md` holds it.\n")[0])
    assert mask("# T\n\n`--dry-run`\n")[0][2].strip()
    for ref in ("from Oct 2025 (`4737d6b`)", "Commit `b044068`, BIQ-1131.",
                "Reverted at commit `4737D6B`."):
        _h, _, _, _ = mask(f"# T\n\n{ref}\n")
        assert [c for _, c, _ in find_shapes(_h)] == ["commit or checkout ref"], \
            (ref, _h[2], find_shapes(_h))
    assert not HASHLIKE.match("`ACCEDED`")
    _r, _, _, _ = mask("# T\n\nThe discovery document was revision 20260729.\n")
    assert not find_shapes(_r), find_shapes(_r)
    _li = mask("# T\n\n- The first line of the item,\n"
               "  and the rest of the sentence.\n")[0]
    assert "the rest of the sentence" in "".join(_li), _li
    _li4 = mask("# T\n\n  - A nested item that runs on,\n"
                "    finishing on the next line.\n")[0]
    assert "finishing on the next line" in "".join(_li4), _li4
    _code = mask("# T\n\n- Step one:\n\n      literal_code_here()\n")[0]
    assert "literal_code_here" not in "".join(_code), _code
    _bare = mask("# T\n\n## Step 2\n\n    git add CLAUDE.md\n")[0]
    assert "git add" not in "".join(_bare), _bare
    _after = mask("# T\n\n- An item.\n\n## Next\n\n    git push origin HEAD\n")[0]
    assert "git push" not in "".join(_after), _after
    _q, _, _, _ = mask('# T\n\nSean said: "the approach is useless" in review.\n')
    assert not find_shapes(_q), find_shapes(_q)
    assert [c for _, c, _ in find_shapes(mask(
        "# T\n\nThe approach is useless.\n")[0])] == ["evaluative adjective"]
    assert not find_shapes(["The scan found weak crypto in the auth module."])
    assert find_shapes(["The scan found a weak argument in the design doc."])
    assert list(_split("**Bold lead.** Plain second one.")) == [
        "**Bold lead.**", "Plain second one."]
    for _ref in ("(L5)", "(L65)", "(L115)", "(L1150)"):
        assert [c for _, c, _ in find_shapes([f"See {_ref} for the detail."])] \
            == ["bare internal id"], _ref
    assert not facts("uninstalled/blacklisted/etc.")["path"]
    assert facts("acme/arch/adr")["path"] == {"acme/arch/adr"}

    long_doc = ["x"] * SUMMARY_NEEDED_FROM
    h_none = [(0, 1, "Rollout plan"), (2, 2, "How we pick work")]
    assert opening_summary(h_none, long_doc, SUMMARY_NEEDED_FROM)["present"] is False
    assert opening_summary(h_none, long_doc, 200) is None
    h_late = [(0, 1, "Rollout plan"), (2, 2, "Detail"), (4, 2, "Summary")]
    assert opening_summary(h_late, long_doc, 900)["present"] is False
    h_deep = [(0, 1, "T"), (1, 2, "Summary"), (3, 3, "First"), (9, 3, "Second")]
    assert opening_summary(h_deep, ["a b"] * 40, 900)["words"] == 4, \
        opening_summary(h_deep, ["a b"] * 40, 900)
    h_sub = [(0, 1, "T"), (1, 2, "Summary"), (2, 3, "Detail"), (6, 2, "Body")]
    assert opening_summary(h_sub, ["a b"] * 40, 900)["words"] == 10, \
        opening_summary(h_sub, ["a b"] * 40, 900)
    assert opening_summary([(0, 1, "T"), (1, 2, "Summary"), (2, 2, "Body")],
                           ["a b"] * 40, 900)["words"] < SUMMARY_MIN_WORDS
    h_ok = [(0, 1, "Rollout plan"), (1, 2, "Summary"), (4, 2, "Detail")]
    got = opening_summary(h_ok, ["a b"] * 6, 900)
    assert got["present"] and got["line"] == 2 and got["words"] == 6, got
    assert opening_summary([(0, 1, "T"), (1, 2, "Abstract")],
                           ["w"] * 3, 900)["present"] is True
    for _h in ("Executive Summary", "1. Executive Summary", "1. Summary",
               "2) Summary", "Technical Overview"):
        assert opening_summary([(0, 1, "T"), (1, 2, _h)],
                               ["w"] * 3, 900)["present"] is True, _h
    for _h in ("Failing checks", "Appendix", "Technical",
               "Notes on the decision to retry", "Summarising the failures"):
        assert opening_summary([(0, 1, "T"), (1, 2, _h)],
                               ["w"] * 3, 900)["present"] is False, _h
    for _h in ("Conclusion", "Conclusions", "Result", "Results", "Decision",
               "Decisions", "Recommendation", "Recommendations", "Finding",
               "Findings", "Verdict", "Verdicts"):
        assert opening_summary([(0, 1, "T"), (1, 2, _h)],
                               ["w"] * 3, 900)["present"] is True, _h
    for _h in ("Resultant load", "Findingsomething", "Decisional review",
               "Conclusionary notes"):
        assert opening_summary([(0, 1, "T"), (1, 2, _h)],
                               ["w"] * 3, 900)["present"] is False, _h

    got = [s for _, s in sentences([(0, 'Call it "spec-driven." One view differs.')])]
    assert got == ['Call it "spec-driven."', "One view differs."], got

    assert any(i["kind"] == "term"
               for i in inconsistencies("AI Insights and AI-Insights both appear"))
    assert any(i["kind"] == "number"
               for i in inconsistencies("took 30 ms then 30 s"))

    c = chunk(["a", "", "- one", "- two", "", "b"], [])
    assert not any(ch["lines"] and ch["lines"][0][1].startswith("- ") for ch in c[1:]), c


    owned = [s for _, shapes in SPECIALISTS.values() for s in shapes]
    assert len(owned) == len(set(owned)), \
        f"shape owned twice: {sorted({s for s in owned if owned.count(s) > 1})}"
    assert set(owned) == all_shape_names(), \
        f"unrouted: {sorted(all_shape_names() - set(owned))}, " \
        f"unknown: {sorted(set(owned) - all_shape_names())}"

    numdoc = "# T\n\n## 3. The gate\n\nGetting it wrong is Item 3.\n\n" \
             "Overlaps 1357 is the worst case.\n"
    p_, h_, t_, q_ = mask(numdoc)
    kinds = {k for _, k, txt in find_shapes(p_, t_, h_, q_)
             if k == "unexplained reference"}
    hits_ = [txt for _, k, txt in find_shapes(p_, t_, h_, q_)
             if k == "unexplained reference"]
    assert kinds and all("1357" in h for h in hits_), hits_

    keep = "# T\n\nCRITICAL INFO: this is a design doc, not a changelog. " \
           "<!-- kv:keep -->\n\nReal prose.\n"
    p_, h_, t_, q_ = mask(keep)
    assert not find_shapes(p_, t_, h_, q_), find_shapes(p_, t_, h_, q_)
    assert 3 not in editable_lines(p_, t_, h_, q_)
    _ci = ("# T\n\nCRITICAL INFO FOR AGENTS: this is a design doc. It is not "
           "a changelog and not a worklog.\n\nThe approach is useless.\n")
    _cp, _ch, _ct, _cq = mask(_ci)
    assert [(l, c) for l, c, _ in find_shapes(_cp, _ct, _ch, _cq)] == \
        [(5, "evaluative adjective")], find_shapes(_cp, _ct, _ch, _cq)
    assert 3 not in editable_lines(_cp, _ct, _ch, _cq)
    _wrap = ("# T\n\nCRITICAL INFO FOR AGENTS: do not delete the retry loop,\n"
             "it is the only thing handling the 429 from upstream.\n\n"
             "Real prose.\n")
    _wp, _wh, _wt, _wq = mask(_wrap)
    _we = editable_lines(_wp, _wt, _wh, _wq)
    assert 3 not in _we and 4 not in _we, _we
    assert 6 in _we, _we
    _kw = "# T\n\nHeld line.  <!-- kv:keep -->\nThe next line is not held.\n"
    _kp, _kh, _kt, _kq = mask(_kw)
    _ke = editable_lines(_kp, _kt, _kh, _kq)
    assert 3 not in _ke and 4 in _ke, _ke
    allow = "# T\n\n<!-- kv:allow flaky -->\n\nThe run is flaky today.\n"
    p_, h_, t_, q_ = mask(allow)
    assert not find_shapes(p_, t_, h_, q_), find_shapes(p_, t_, h_, q_)

    span_doc = ("# T\n\nIt was split across seven.\n"
                "`run` does not load it because the router picks one.\n")
    sp_p, _sp_h, _sp_t, _sp_q = mask(span_doc, "t")
    assert len(list(sentences(list(enumerate(sp_p))))) == 1
    got_ = [s for _, s in sentences(list(enumerate(with_spans(sp_p, span_doc))))]
    assert len(got_) == 2, got_
    assert got_[1].startswith("`run`"), got_[1]
    assert with_spans(["", "x"], "aaa\nx")[0] == ""
    _qd = ('# T\n\nSean said: "the detector coverage is reasonable in my '
           'experience and the address field is the one problem we keep hitting '
           'on every run of the tuned pipeline" during the review.\n')
    _qp, _, _, _ = mask(_qd, "t")
    assert not [s for _, s in sentences(list(enumerate(with_spans(_qp, _qd))))
                if len(s.split()) > LONG_SENTENCE], with_spans(_qp, _qd)

    for lead in ("## Summary", "## Decision", "## Recommendation"):
        pad = ("word " * 900).strip()
        p_, h_, _t, _q = mask(f"# T\n\n{lead}\n\nUse Model Armor.\n\n## Body"
                              f"\n\n{pad}\n")
        assert opening_summary(h_, p_, 909)["present"] is True, lead

    for name in SPECIALISTS:
        assert (SPECIALIST_DIR / f"{name}.md").is_file(), \
            f"no prompt for specialist {name!r} at {SPECIALIST_DIR}"
    assert (SPECIALIST_DIR / "_common.md").is_file(), SPECIALIST_DIR
    _skill_md = (SPECIALIST_DIR.parent / "SKILL.md").read_text()
    for _hand in ("code.md", "jargon-hunt.md"):
        assert (SPECIALIST_DIR / _hand).is_file(), \
            f"{_hand} is gone and SKILL.md still sends the reader to it"
        assert _hand in _skill_md, \
            f"SKILL.md no longer tells anyone {_hand} exists or how to run it"
    for _hand in ("code.md", "jargon-hunt.md"):
        _t = (SPECIALIST_DIR / _hand).read_text()
        assert "{{" not in _t, \
            f"{_hand} asks for a value, and nothing ever substitutes it"
    _rows = dict(re.findall(r"^\|\s*`(\w+)`\s*\|\s*(\w+)\s*\|",
                            (SPECIALIST_DIR.parent / "SKILL.md").read_text(),
                            re.M))
    for _name, (_scope, _) in SPECIALISTS.items():
        assert _rows.get(_name) == _scope, \
            (f"SKILL.md calls {_name} {_rows.get(_name)!r}, the code runs it "
             f"as {_scope!r}")
    _owns = "\n".join(l for l in _skill_md.splitlines()
                      if re.match(r"^\|\s*`\w+`\s*\|\s*\w+\s*\|", l))
    _unnamed = sorted({s for _, shapes in SPECIALISTS.values() for s in shapes
                       if s.lower() not in _owns.lower()})
    assert not _unnamed, \
        (f"SKILL.md's specialist table names no owner for {len(_unnamed)} "
         f"shape(s): {_unnamed}")
    _flags = {o for _c, opts in cli_surface().items() for o in opts}
    _undoc = sorted(f for f in _flags if f not in _skill_md)
    assert not _undoc, \
        (f"SKILL.md documents no flag {_undoc}, under a sentence saying the "
         f"table is the whole list")
    for _name in ("docs/user-guide.md", "SKILL.md"):
        _doc = HERE / _name
        _quoted = re.search(r"selftest ok \(\d+ checks?\)", _doc.read_text())
        assert not _quoted, \
            (f"{_name} quotes {_quoted.group(0)!r}; the count rises with "
             f"every case, so it is stale the next time one lands")

    _waves = [f"- Wave {i} — turn the sandbox on for the platform team."
              for i in range(1, 6)]
    _para = [f"Paragraph {i} records the window, the path and the owner for "
             f"each stage." for i in range(1, 6)]
    _plines = ["# T", ""] + _waves + ["", "## Detail", ""] + _para
    _pd = duplicates(_plines)
    assert len(_pd) == 2, [d["lines"] for d in _pd]
    _plist = {tuple(d["lines"]): parallel_list(d, _plines) for d in _pd}
    assert sorted(_plist.values()) == [False, True], _plist
    assert _plist[(3, 4, 5, 6, 7)] is True and _plist[(11, 12, 13, 14, 15)] \
        is False, _plist
    _broken = _plines[:5] + ["", "That is the whole wave list, and it is."] \
        + _plines[5:]
    _bd = [d for d in duplicates(_broken) if len(d["lines"]) == 5]
    assert _bd and not parallel_list(_bd[0], _broken), _bd
    with tempfile.TemporaryDirectory() as _td:
        _pf = Path(_td) / "p.md"
        _pf.write_text("\n".join(
            _plines + [" ".join(f"pad{i}x{j}" for j in range(30))
                       for i in range(30)]) + "\n")
        _args = build_parser().parse_args(["plan", str(_pf)])
        _out = io.StringIO()
        with contextlib.redirect_stdout(_out):
            _args.fn(_args)
        _rows = [l for l in _out.getvalue().splitlines() if "lines [" in l]
    assert len(_rows) == 2, _rows
    assert "parallel list" in next(r for r in _rows if "sandbox" in r), _rows
    assert "parallel list" not in next(r for r in _rows if "records" in r), \
        _rows

    def _dups_of(_md):
        _pr, _hd, _tb, _qt = mask(_md, "t.md")
        return [(d, restates_a_summary(d, _hd)) for d in duplicates(_pr)]

    _S = "the gate refused every envelope the old host had sent"
    _B = "both halves must hold and the run of lines between"
    _doc = (f"# R\n\n## Summary\n\n{_S}.\n\n## The gate\n\n{_S}.\n\n"
            f"## Detail\n\n{_B}.\n\n## More detail\n\n{_B}.\n")
    _sd = _dups_of(_doc)
    assert len(_sd) == 2, [d["lines"] for d, _ in _sd]
    _tagged = {d["text"][:20]: rs for d, rs in _sd}
    assert _tagged[_S[:20]] is True and _tagged[_B[:20]] is False, _tagged
    _cc = _dups_of(_doc.replace("## Summary", "## Cross-check"))
    assert [rs for d, rs in _cc if d["text"].startswith(_S[:20])] == [True], _cc
    _nest = _dups_of(_doc.replace("## Summary\n", "## Summary\n\n### Ordering\n"))
    assert [rs for d, rs in _nest if d["text"].startswith(_S[:20])] == [True], \
        _nest
    with tempfile.TemporaryDirectory() as _td:
        _sf = Path(_td) / "s.md"
        _sf.write_text(_doc)
        _args = build_parser().parse_args(["plan", str(_sf)])
        _out = io.StringIO()
        with contextlib.redirect_stdout(_out):
            _args.fn(_args)
        _txt = _out.getvalue()
    assert "1 body-to-body · 1 restating a summary" in _txt, _txt
    _rows = [l for l in _txt.splitlines() if "lines [" in l]
    assert len(_rows) == 2 and "restates a summary" in _rows[1] \
        and "restates a summary" not in _rows[0], _rows

    _readme = (HERE / "docs" / "user-guide.md").read_text()
    _shown = re.findall(r"<!--\s*kv:[^>]*-->", _readme)
    for _rx, _name in ((KEEP_MARK, "kv:keep"), (ALLOW_MARK, "kv:allow"),
                       (ALLOW_SHAPE_MARK, "kv:allow-shape")):
        _hit = [m for m in _shown if _rx.fullmatch(m)]
        assert _hit, (f"README.md, the user guide, shows no {_name} that "
                      f"{_rx.pattern} accepts; it shows {_shown}")

    _named = set(re.search(r"kinds are detected: ([^.]+)\.",
                           (SPECIALIST_DIR.parent / "SKILL.md").read_text())
                 .group(1).replace("and ", "").split(", "))
    assert _named == set(GENRES), \
        (f"SKILL.md names {sorted(_named)}, the code detects {sorted(GENRES)}")
    assert "line of the range. Do not count" in inspect.getsource(job_prompt), \
        "no prompt tells a specialist how to reword a wrapped sentence"
    _op = job_prompt({"specialist": "structure", "outline": "1 # T",
                      "hits": [], "lo": 1, "hi": None}, ["# T"], "ctx", {})
    assert "you do not need to write a note" not in _op, \
        "the outline prompt still makes an empty answer free"
    assert "came closest to moving" in _op and "Zero moves is a legal" in _op
    assert "most destructive operation" in _op, \
        "nothing warns the outline job off shuffling to look busy"
    assert "as though your edit already happened" in _op, \
        "nothing stops a specialist reporting an edit that the gates refused"

    assert windows(1, 40) == [(1, 40)], windows(1, 40)
    _ten = {i: 10 for i in range(1, 201)}
    assert windows(1, 200, [74, 75], words=_ten) == windows(1, 200, [74, 75]), \
        "the word cap disagrees with the line cap at 10 words a line"
    _fat = {i: 200 for i in range(1, 21)}
    _w = windows(1, 20, (), words=_fat)
    assert len(_w) > 1 and all(
        sum(_fat[i] for i in range(a, b + 1)) <= MAX_SPAN_WORDS
        for a, b in _w), _w
    assert windows(1, 3, (), words={1: 5000, 2: 10, 3: 10}) == [(1, 1), (2, 3)]
    for lo, hi in ((1, 200), (5, 405), (1, 81), (17, 17)):
        for brk in ((), range(lo, hi + 1, 7), (lo + 3,)):
            w = windows(lo, hi, brk)
            assert w[0][0] == lo and w[-1][1] == hi, (w, list(brk)[:3])
            assert all(b[0] == a[1] + 1 for a, b in zip(w, w[1:])), w
            assert all(e - s + 1 <= MAX_SPAN for s, e in w), w
            assert all(e >= s for s, e in w), w
    assert windows(1, 200, [74, 75])[1][0] == 75, windows(1, 200, [74, 75])
    assert windows(1, 200, [3])[0] == (1, 80), windows(1, 200, [3])

    assert "split this before handing" not in inspect.getsource(cmd_plan), \
        "plan still asks the reader to split a chunk run splits itself"
    assert 'split into {c[\'spans\']} for' in inspect.getsource(cmd_plan), \
        "plan does not print the span count it computes"

    fake_chunks = [{"n": 1, "title": "a", "start": 1, "end": 10},
                   {"n": 2, "title": "b", "start": 11, "end": 20}]
    jobs = build_jobs(fake_chunks, [(3, "jargon", "leverage")], False, None)
    woken = {(j["specialist"], j["lo"]) for j in jobs}
    assert ("prose", 1) in woken, woken
    assert ("prose", 11) not in woken, "woke prose on a chunk with no hit"
    assert ("noise", 1) not in woken, "woke noise on a jargon hit"
    assert {"structure", "summary"} <= {j["specialist"] for j in jobs}, woken

    _sum_of = lambda **kw: {**{"present": True, "line": 3, "title": "Summary",
                               "words": 200, "end": 9, "doc": 5000}, **kw}
    assert not summary_owed(_sum_of()), "woke summary on a good one"
    assert summary_owed(_sum_of(present=False)), "missed a missing summary"
    assert not summary_owed(_sum_of(buried=40, present=False)), \
        "summary is still woken for a move it cannot make"
    _bj = {j["specialist"]: j for j in
           build_jobs([{"n": 1, "title": "t", "start": 1, "end": 2, "lines": []}],
                      [], False, None,
                      summary=_sum_of(buried=40, present=False))}
    assert "summary" not in _bj, "summary was scheduled for a buried summary"
    assert _bj["structure"]["notes_only"], \
        "structure was sent as a full editor for a notes-only pass"
    assert _bj["structure"]["unbury"], \
        "structure was not told to clear the buried summary"
    assert "`structure` has it" in \
        summary_blocked(_sum_of(buried=13, present=False)), \
        "the skip reason no longer names who clears a buried summary"
    assert "move-block" in \
        summary_verdict(_sum_of(buried=13, present=False))[1], \
        "plan no longer names the operation that clears it"
    for _fn in (build_jobs, cmd_run):
        assert "summary_blocked(summary)" in inspect.getsource(_fn), \
            f"{_fn.__name__} grew its own copy of the skip reason again"
    assert summary_owed(_sum_of(words=SUMMARY_MAX_WORDS + 1)), "missed an overrun"
    assert summary_owed(_sum_of(words=SUMMARY_MIN_WORDS - 1)), \
        "a summary too short to state a result is still owed a rewrite"
    assert summary_owed(None)
    clean = build_jobs(fake_chunks, [], False, None, summary=_sum_of())
    assert {j["specialist"] for j in clean} == {"structure"}, clean
    assert clean[0]["notes_only"], clean
    live = build_jobs(fake_chunks, [(3, "jargon", "leverage")], False, None,
                      summary=_sum_of())
    assert not next(j for j in live if j["specialist"] == "structure")["notes_only"]

    _settled = ("# Report\n\n## Summary\n\n"
                + "The gate rejects 41 of 92 requests. Raise the threshold to "
                  "0.8 and the rejects drop to 12. The owner is the platform "
                  "team and the change ships in v3. "
                + "Each region reports its own count and the totals agree. " * 4
                + "\n\n## Detail\n\n"
                + "The counts come from the 2026-03 export. " * 160)
    _p, _h, _t, _q = mask(_settled)
    _hits = find_shapes(_p, _t, _h, _q, chat=False)
    assert not _hits, _hits[:5]
    _rep = opening_summary(_h, _p, len(_settled.split()))
    assert _rep and _rep["present"] and not summary_owed(_rep), _rep
    _jobs = build_jobs(chunk(_p, _h), _hits, False, None,
                       needs_summary=_rep is not None, summary=_rep)
    assert _jobs and all(j.get("notes_only") for j in _jobs), \
        [j["specialist"] for j in _jobs if not j.get("notes_only")]
    chat_jobs = {j["specialist"] for j in build_jobs(fake_chunks, [], True, None)}
    assert chat_jobs == {"chat"}, chat_jobs
    assert "chat" not in {j["specialist"]
                          for j in build_jobs(fake_chunks, [], False, None)}
    for only, is_chat in (("structure", True), ("chat", False)):
        try:
            build_jobs(fake_chunks, [], is_chat, only)
            raise AssertionError(f"--only {only} chat={is_chat} was allowed")
        except ValueError as e:
            assert "does not run" in str(e), e
    assert not build_jobs(fake_chunks, [], True, "chat")[0]["hits"]
    short = {j["specialist"]
             for j in build_jobs(fake_chunks, [], False, None, needs_summary=False)}
    assert "summary" not in short and "structure" in short, short
    assert "summary" in {j["specialist"] for j in build_jobs(fake_chunks, [], False, None)}
    try:
        build_jobs(fake_chunks, [], False, "summary", needs_summary=False)
        raise AssertionError("--only summary was allowed on a short file")
    except ValueError as e:
        assert "already its own summary" in str(e), e

    _ld = _sum_of(present=False, lede=328)
    assert summary_owed(_ld), \
        "an unheaded opening still skips the summary specialist"
    _off, _on = unheaded_note(328, False), unheaded_note(328, True)
    assert "do not add a heading over them" in _off and "Read them" not in _off
    assert "give them a heading" in _on and "Leave those words" not in _on
    assert 'unheaded_note(summary["lede"], True, _w)' in inspect.getsource(cmd_run), \
        "summary is handed the same hands-off text as everyone else"
    assert 'unheaded_note(summary["lede"], False, _w)' in inspect.getsource(cmd_run) \
        and 'unheaded_note(summary["lede"], False, summary.get("lede_where"))' \
        in inspect.getsource(cmd_run), \
        "an unheaded opening is described to the specialists at the wrong place"
    assert ("between the title and the first section heading"
            in unheaded_note(328, True, "below-title")), \
        "the note no longer says where a titled document's lede sits"
    assert "above the first heading" in unheaded_note(328, True, "above-first")
    assert "name what to read next" in _on, \
        "a lede that states the result is enough again"
    assert "write a summary and insert it above them" in _on, \
        "the specialist is no longer told what to do when it is an intro"
    for _hs, _ps in ((_hs_b := [(0, 1, "T"), (4, 2, "Summary"), (9, 2, "B")],
                      ["# T", "lede words here", "", "", "## Summary",
                       "body", "", "", "", "## B"]),
                     ([(0, 1, "T"), (4, 2, "B")],
                      ["# T", "lede words here", "", "", "## B"])):
        _os = opening_summary(_hs, _ps, 4000)
        assert not (_os.get("buried") and _os.get("lede")), _os
    assert "settle_lede" not in globals(), \
        "the two lede flags are back, and they ask the reader the question " \
        "the specialist is there to answer"

    _lede = _sum_of(present=False, lede=328)
    assert "summary" in {j["specialist"] for j in
                         build_jobs(fake_chunks, [], False, "summary",
                                    summary=_lede)}, \
        "--only summary still refuses the case it was built for"
    try:
        build_jobs(fake_chunks, [], False, "summary", summary=_sum_of())
        raise AssertionError("--only summary exited 0 on a good summary")
    except ValueError as e:
        assert "summary" in str(e), e
    try:
        build_jobs(fake_chunks, [], False, "noise")
        raise AssertionError("--only noise exited 0 with no shape fired")
    except ValueError as e:
        assert "no shape it owns fired" in str(e), e
    assert build_jobs(fake_chunks, [], False, None, summary=_lede) is not None
    import io as _io, contextlib as _cl
    _cap = _io.StringIO()
    try:
        with _cl.redirect_stderr(_cap):
            _mixed = build_jobs(fake_chunks, [], False, "summary,noise",
                                summary=_lede)
    except ValueError as e:
        raise AssertionError(
            f"one idle name in the set refused the whole run: {e}") from None
    assert "summary" in {j["specialist"] for j in _mixed}, \
        "one idle name in the set stopped the specialist that had work"
    assert "idle this file, the rest still run" in _cap.getvalue(), \
        "the idle specialist went unmentioned"
    assert "noise: no shape it owns fired" in _cap.getvalue(), \
        "the notice does not name which specialist was idle"
    _cap2 = _io.StringIO()
    try:
        with _cl.redirect_stderr(_cap2):
            build_jobs(fake_chunks, [], False, "noise,summary",
                       summary=_sum_of())
        raise AssertionError("a wholly idle set returned instead of refusing")
    except ValueError as e:
        assert "no shape it owns fired" in str(e), e
    assert "idle this file" not in _cap2.getvalue(), \
        "the wholly-idle case printed the keep-going notice as well"

    assert crosscheck_offer("agy") == ["claude", "codex", "delegate"], \
        "the offer names the model that wrote the edits"
    assert crosscheck_offer(None) == list(GROUNDED_BACKENDS), \
        "a run with no recorded writer lost backends anyway"
    _saved_gb = GROUNDED_BACKENDS
    try:
        globals()["GROUNDED_BACKENDS"] = ("codex",)
        _empty = crosscheck_remedy("codex")
        assert "no second opinion" in _empty, \
            "an empty offer rendered as an empty remedy"
        assert "--backend" not in _empty, \
            "the empty case still tells the reader to pass a backend"
    finally:
        globals()["GROUNDED_BACKENDS"] = _saved_gb
    _agy = crosscheck_remedy("agy")
    assert "claude codex" in _agy, "the offer stopped naming the backends"
    assert "other than the one that wrote" in _agy, \
        "the applied exclusion went unsaid"
    assert "other than the one that wrote" not in crosscheck_remedy(None), \
        "an exclusion that never ran is described as though it had"
    assert "Only installation is checked" in _agy, \
        "the offer promises the named backends can answer"
    _ccsrc = inspect.getsource(cmd_crosscheck)
    assert "grounded=True" in _ccsrc, \
        "crosscheck stopped giving the reviewer read access to the files"
    _cmd, _stdin = agent_command("codex", ["codex"], "PROMPT", 60, grounded=True)
    assert "PROMPT" not in _cmd and _stdin == "PROMPT", \
        "the prompt went into argv -- a long one overflows Windows' limit"
    _cmd, _stdin = agent_command("agy", ["agy"], "PROMPT", 60)
    assert "PROMPT" not in " ".join(_cmd) and "PROMPT" in _stdin, _cmd
    assert json.loads(_stdin)["message"]["content"] == "PROMPT", _stdin
    _cmd, _ = agent_command("claude", ["claude"], "P", 60, grounded=True)
    assert _cmd[-2:] == CLAUDE_READONLY, _cmd
    _cmd, _ = agent_command("claude", ["claude"], "P", 60)
    assert _cmd[-2:] == CLAUDE_NO_TOOLS, _cmd
    assert "read-only" in agent_command("codex", ["codex"], "P", 60)[0], \
        "codex lost its read-only sandbox"
    _cmd, _stdin = agent_command("delegate", ["delegate"], "PROMPT", 60)
    assert _cmd == ["delegate", "--mode", "raw", "--timeout", "60",
                    "--prompt-file", "-"] and _stdin == "PROMPT", _cmd
    assert "--grounded" in agent_command("delegate", ["delegate"], "P", 60,
                                         grounded=True)[0], \
        "a delegate crosscheck lost --grounded, so it may answer unread"
    assert agent_answer("agy", '{"event":"start"}\n{"event":"result",'
                        '"result":{"status":"SUCCESS","response":"hi"}}\n') \
        == "hi"
    assert agent_answer("agy", '{"event":"result","result":{"status":'
                        '"ERROR","response":"x"}}') == ""
    assert agent_answer("agy", "Please log in\n") == "Please log in"

    _xa = ("- problem: the rule was inverted\n"
           "  file: /t/a.md:12\n"
           "  kind: reversed_rule\n"
           "  fix: put the negation back\n"
           "  solves: the instruction means what it meant\n"
           "- problem: still wordy\n  file: /t/a.md:20\n  kind: verbose\n"
           "  fix: cut the frame\n  solves: shorter\n")
    _xk = crosscheck_kinds(_xa)
    assert _xk["reversed_rule"] == 1 and _xk["verbose"] == 1, _xk
    assert sum(_xk[k] for k in MEANING_KINDS) == 1, _xk
    assert "lost_fact" in MEANING_KINDS
    assert not sum(crosscheck_kinds("").values())
    assert crosscheck_kinds("* kind: `weakened_rule`")["weakened_rule"] == 1
    assert crosscheck_kinds("  kind: lost_fact")["lost_fact"] == 1
    _xsrc = inspect.getsource(cmd_crosscheck)
    assert "kind: <one of:" in _xsrc, "the prompt stopped asking for a kind"
    for _k in MEANING_KINDS:
        assert _k in _xsrc, f"the prompt does not name {_k}"
    assert cmd_crosscheck_cli.__doc__ and "MEANING_KINDS" in inspect.getsource(
        cmd_crosscheck_cli), "a reversed rule still cannot change the verdict"
    _rsrc = inspect.getsource(cmd_run)
    assert "cmd_crosscheck" not in _rsrc, \
        "run calls crosscheck again, and the coupling that came with it"

    _RD = [
        "# Retention", "",
        "In order to facilitate the retention of session rows the system "
        "leverages a robust and scalable architecture designed for storage.",
        "", "## Storage", "",
        "Session rows are retained for twelve months in the primary store. It "
        "should be noted that this is a very important consideration here.",
        "",
        "The utilisation of the archival tier enables the organisation to "
        "reduce costs in a manner that is both efficient and effective.",
        "", "## Policy", "",
        "Session rows are retained for twelve months in the primary store. It "
        "should be noted that this is a very important consideration here.",
        "",
        "The gate holds at 85% and the latency budget is 250ms for every "
        "request the service must process during normal operations.", ""]
    _RUNDOC = "\n".join(_RD) + "\n"

    def _runfix(reply, doc=None, name="doc.md", **over):
        """Run `cmd_run` end to end against a stub launcher."""
        _d = Path(tempfile.mkdtemp())
        _s = _d / name
        _body = _RUNDOC if doc is None else doc
        if isinstance(_body, bytes):
            _s.write_bytes(_body)
        else:
            _s.write_text(_body, encoding="utf-8")
        _seen = []

        def _stub(prompt, agent, timeout):
            _seen.append(prompt)
            return reply(prompt, agent, len(_seen))

        _ns = argparse.Namespace(
            file=str(_s), out=None, agent="codex", chat=False, dry_run=False,
            job_timeout=30, no_budget=True, only=None, timeout=60,
            full=False, profile=None)
        _ns.__dict__.update(over)
        _o, _e = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(_o), contextlib.redirect_stderr(_e):
            _rc = cmd_run(_ns, launcher=_stub)
        return argparse.Namespace(rc=_rc, out=_o.getvalue(), err=_e.getvalue(),
                                  prompts=_seen, dir=_d, src=_s)

    def _quiet(_p, _a, _n):
        return json.dumps({"edits": [], "notes": ["nothing to do"]}), None

    _rf = _runfix(_quiet)
    try:
        assert "Nothing here checked this file for meaning" in _rf.out \
            and "read it for sense" in _rf.out, \
            f"run stopped naming the reader that judges meaning: {_rf.out[-300:]!r}"
    finally:
        shutil.rmtree(_rf.dir, ignore_errors=True)
    def _dead(_p, _a, _n):
        return None, "backend refused"

    _rd = _runfix(_dead)
    try:
        assert "BYTE-IDENTICAL" in _rd.out, \
            ("a run whose every span died did not say the output is the input: "
             f"{_rd.out[-400:]!r}")
        assert "This is not a result" in _rd.out
        assert _rd.out.index("BYTE-IDENTICAL") \
            < _rd.out.index("FAIL — the file is incomplete"), \
            "the byte-identity notice moved below the verdict it qualifies"
        _up = next((ln for ln in _rd.out.splitlines()
                    if ln.startswith("FAIL — ") and "shapes fixed" in ln), "")
        assert "never edited" in _up and "survived" not in _up, \
            f"the up-front verdict on a dead run reads as a result: {_up!r}"
        assert _rd.src.read_bytes() == (_rd.dir / "doc.kv.md").read_bytes()
    finally:
        shutil.rmtree(_rd.dir, ignore_errors=True)
    _rk = _runfix(_quiet)
    try:
        assert "BYTE-IDENTICAL" not in _rk.out, \
            ("a run with nothing to change was accused of having died: "
             f"{_rk.out[-400:]!r}")
    finally:
        shutil.rmtree(_rk.dir, ignore_errors=True)

    def _bnote(err):
        return next((l for l in err.splitlines()
                     if l.startswith("budget: ")), "")

    _btight = dict(no_budget=False, timeout=50, job_timeout=30)
    _bw = _runfix(_quiet, **_btight)
    try:
        _wl = _bnote(_bw.err)
        assert _wl, ("a run whose matrix cannot fit its --timeout said "
                     f"nothing at dispatch: {_bw.err[-500:]!r}")
        _wm = re.match(r"budget: (\d+) jobs?, (\d+) at a time = (\d+) waves?\. "
                       r"At the full (\d+)s --job-timeout that is (\d+)s of "
                       r"wall clock, against a --timeout of (\d+)s\.", _wl)
        assert _wm, f"the budget line stopped stating its arithmetic: {_wl!r}"
        _bj, _bp, _bwv, _bc, _bprod, _bt = (int(g) for g in _wm.groups())
        assert f"dispatches {_bj} job" in _bw.out, \
            (f"the budget line counts {_bj} jobs and the dispatch line does "
             f"not: {_bw.out[:400]!r}")
        assert (_bp, _bc, _bt) == (JOBS, 30, 50), (_bp, _bc, _bt)
        assert _bj % JOBS, \
            (f"the fixture now builds {_bj} jobs, an exact multiple of the "
             f"{JOBS}-wide pool, so this case can no longer see a floor "
             f"division in the wave count")
        assert _bwv == -(-_bj // JOBS) and _bprod == _bwv * _bc, \
            (f"{_bj} jobs {JOBS} at a time is not {_bwv} waves of {_bc}s "
             f"= {_bprod}s")
        assert _bprod > _bt, (_bprod, _bt)
        assert f"raise --timeout to {_bprod}" in _wl and \
            f"lower --job-timeout to {_bt // _bwv}" in _wl, _wl
        _brec = json.loads((_bw.dir / "doc.kv.md.kvrun").read_text())
        assert (_brec["jobs_planned"], _brec["budget_floor"],
                _brec["budget_seconds"]) == (_bj, _bprod, 50), _brec
    finally:
        shutil.rmtree(_bw.dir, ignore_errors=True)
    _bok = _runfix(_quiet, no_budget=False, timeout=100000, job_timeout=30)
    try:
        assert not _bnote(_bok.err), \
            ("a budget with room to spare was warned about anyway: "
             f"{_bnote(_bok.err)!r}")
        assert "at a time:" in _bok.err and f"dispatches {_bj} job" in _bok.out, \
            ("the control never reached the dispatch, so its silence says "
             f"nothing: {_bok.err[-300:]!r}")
        assert json.loads((_bok.dir / "doc.kv.md.kvrun").read_text())[
            "budget_floor"] == _bprod, "the control's matrix is not the same one"
    finally:
        shutil.rmtree(_bok.dir, ignore_errors=True)
    _bdry = _runfix(_quiet, dry_run=True, **_btight)
    try:
        assert _bdry.rc == 0 and _bnote(_bdry.err), \
            (f"--dry-run did not carry the budget arithmetic: {_bdry.rc}, "
             f"{_bdry.err[-400:]!r}")
        assert "hits   " in _bdry.out, \
            f"--dry-run printed no matrix to warn about: {_bdry.out[-300:]!r}"
        assert not _bdry.prompts, "--dry-run dispatched"
    finally:
        shutil.rmtree(_bdry.dir, ignore_errors=True)
    _bna = _runfix(_quiet, no_agents=True, **_btight)
    try:
        assert not _bnote(_bna.err), \
            ("--no-agents sends nothing and was still warned about its "
             f"budget: {_bnote(_bna.err)!r}")
    finally:
        shutil.rmtree(_bna.dir, ignore_errors=True)
    assert budget.waves(5, 4) == 2 and budget.waves(8, 4) == 2 \
        and budget.waves(0, 4) == 0, "the wave count is not a ceiling division"
    assert budget.matrix_seconds(5, 4, 240) == 480, \
        budget.matrix_seconds(5, 4, 240)
    assert not budget.matrix_note(5, 4, 240, 480), \
        "a budget that exactly covers the matrix was warned about"
    assert budget.matrix_note(5, 4, 240, 479), \
        "a budget one second short of the matrix said nothing"
    assert not budget.matrix_note(5, 4, 240, None), \
        "--no-budget was given a budget warning"
    assert "lower --job-timeout" not in budget.matrix_note(40, 4, 240, 9) \
        and "lower --job-timeout to 60" in budget.matrix_note(40, 4, 240, 600), \
        budget.matrix_note(40, 4, 240, 9)
    _slow = budget.matrix_note(40, 4, 240, 600, {"structure document": 240})
    assert "lower --job-timeout to 60," not in _slow \
        and "structure document already timed out at 240s" in _slow, _slow
    assert "lower --job-timeout to 60," in \
        budget.matrix_note(40, 4, 240, 600, {"noise 1": 30})

    _fz_wrap = ("In order to facilitate the retention of session rows the "
                "system\nleverages a robust and scalable architecture that is "
                "designed for\nthe storage of rows over a long period of time "
                "and is a thing.\n")
    _fz_rules = "\n".join(f"  rule {i} kept on its own line" for i in range(1, 13))
    _fz_doc = ("# Rules\n\n"
               + "\n".join(f"## Section {n}\n\n{_fz_wrap}" for n in range(1, 9))
               + f"\n{_fz_rules}\n\n## After\n\n{_fz_wrap}")

    def _fz_reply(_p, _a, _n):
        _folded = " ".join(_fz_wrap.split())
        return json.dumps({"edits": [
            {"line": _l, "old": _folded, "new": "Session rows are retained."}
            for _l in (9, 13)], "notes": []}), None

    def _fz_kept(run):
        out = (run.dir / "doc.kv.md").read_text().split("\n")
        return sum(1 for i in range(1, 13)
                   if f"  rule {i} kept on its own line" in out)

    _fz = _runfix(_fz_reply, doc=_fz_doc,
                  freeze=(["^  rule "], "a monitor reads one rule per line"))
    try:
        assert _fz_kept(_fz) == 12, (
            "a frozen line was reflowed by the run's own fold, with no "
            f"specialist having touched it: {_fz_kept(_fz)} of 12 survived")
    finally:
        shutil.rmtree(_fz.dir, ignore_errors=True)
    _fzc = _runfix(_fz_reply, doc=_fz_doc)
    try:
        assert _fz_kept(_fzc) < 12, (
            "the undeclared control kept every line too, so this fixture "
            "cannot see the barrier at all")
    finally:
        shutil.rmtree(_fzc.dir, ignore_errors=True)

    _rq = _runfix(_quiet, name="my doc.md")
    try:
        _adv = [_l for _l in _rq.out.splitlines() if "kill-verbosity accept" in _l]
        assert _adv, f"the run printed no accept line at all: {_rq.out[-300:]!r}"
        assert f"'{_rq.src}'" in _adv[0] and f"'{_rq.dir / 'my doc.kv.md'}'" in _adv[0], \
            ("the accept line stopped naming, or stopped quoting, the file the "
             f"run actually wrote: {_adv[0]!r}")
    finally:
        shutil.rmtree(_rq.dir, ignore_errors=True)
    for _r in _walk_returns(cmd_crosscheck):
        assert _r == 2, \
            f"cmd_crosscheck returns {_r} values somewhere; the caller " \
            f"unpacks two"
    _saved_cc = cmd_crosscheck
    try:
        globals()["cmd_crosscheck"] = lambda _a: (0, Counter({"verbose": 3}))
        assert cmd_crosscheck_cli(None) == 0, "a clean crosscheck is not 0"
        globals()["cmd_crosscheck"] = lambda _a: (0, Counter(
            {"reversed_rule": 1, "verbose": 1}))
        assert cmd_crosscheck_cli(None) == 3, \
            "a reversed rule did not raise the standalone verdict to 3"
        globals()["cmd_crosscheck"] = lambda _a: (2, Counter())
        assert cmd_crosscheck_cli(None) == 2, "a refusal stopped being 2"
    finally:
        globals()["cmd_crosscheck"] = _saved_cc

    _dj = duplicate_jobs([{"lines": [464, 622], "words": 9, "text": "the same"},
                          {"lines": [12], "words": 4, "text": "alone"},
                          {"lines": [3, 8, 40], "words": 5, "text": "thrice"}],
                         900)
    assert len(_dj) == 2, _dj
    assert all(j["specialist"] == "structure" for j in _dj), _dj
    assert _dj[0]["lo"] <= 464 and _dj[0]["hi"] >= 622, _dj[0]
    assert _dj[1]["lo"] <= 3 and _dj[1]["hi"] >= 40, _dj[1]
    assert duplicate_jobs([{"lines": [1, 899], "words": 3, "text": "x"}],
                          900)[0]["hi"] == 900
    assert all("one_duplicate" in j for j in _dj), _dj

    _wp = ["One. Two. Three. Four.", "", "One. Two.", "",
           "- Aa. Bb.", "- Cc. Dd.", "",
           "Alpha runs. Beta runs.", "Gamma runs. Delta runs."]
    assert wall_paragraphs(_wp) == [(1, 4, 4), (8, 4, 8)], wall_paragraphs(_wp)
    assert not [w for w in wall_paragraphs(_wp) if w[0] in (5, 6)], _wp
    assert wall_paragraphs(_wp, floor=2)[1] == (3, 2, 2), wall_paragraphs(_wp, 2)
    assert em_dash_pressure(["a — b — c"]) == [(1, 2)]
    assert em_dash_pressure(["- a — b — c", "- d — e — f"]) == [(1, 2), (2, 2)]
    assert owner_of("paragraph wall") == "prose", owner_of("paragraph wall")
    assert "paragraph wall" in SYNTHETIC
    assert "wall_paragraphs(prose)" in inspect.getsource(cmd_run), \
        "no chunk is ever scheduled for a paragraph wall"
    assert "Paragraph walls" in (SPECIALIST_DIR / "prose.md").read_text(), \
        "prose is flagged for a shape its own prompt does not name"
    assert "wall_paragraphs(prose)" in inspect.getsource(cmd_plan), \
        "plan hides a shape run dispatches"
    _rrc = inspect.getsource(cmd_run)
    for _need in ("section{'' if n_mv == 1 else 's'} moved", "repeats resolved",
                  "paragraph walls", "repeats introduced",
                  "the document: {o_w} → {n_w}"):
        assert _need in _rrc, f"the run never reports {_need.strip()}"

    _ol_txt = ("# Title\n\nintro line\n\n## History\n\n```py\nx = 1\n```\n\n"
               "It began long ago.\n\n## Result\n\n| a | b |\n\n"
               "The answer is 42.\n\n## Notes\n\n- a bullet\n")
    _ol_lines = _ol_txt.split("\n")
    _ol_prose, _ol_h = mask(_ol_txt, "outline")[:2]
    _ol = outline_of(_ol_h, _ol_lines, _ol_prose)
    assert len(_ol_h) == 4, _ol_h
    assert [int(l.split("|")[0]) for l in _ol.split("\n") if "|" in l] \
        == [h[0] + 1 for h in _ol_h], _ol
    assert "It began long ago." in _ol and "x = 1" not in _ol, _ol
    assert "The answer is 42." in _ol and "| a | b |" not in _ol, _ol
    assert "a bullet" not in _ol, _ol
    assert "intro line" in _ol and len(_ol.split("\n")) < len(_ol_lines), _ol

    _ol_job = {"specialist": "structure", "unit": "document · order",
               "lo": 1, "hi": None, "hits": [], "outline": _ol}
    _ol_p = job_prompt(_ol_job, _ol_lines, "ctx", token_lines(_ol_lines))
    assert _ol in _ol_p, _ol_p
    assert numbered(_ol_lines, 1, len(_ol_lines)) not in _ol_p, _ol_p
    assert '"op": "move"' in _ol_p and "Send no `replace`" in _ol_p, _ol_p
    _osrc = inspect.getsource(cmd_run)
    assert "outline_of(headings, lines, prose)" in _osrc, \
        "the order job is never scheduled"
    assert _osrc.count("order_elsewhere") == 2, \
        "the document job is not told that order moved out"
    _b_txt = "# T\n\nlede\n\n## S\n\n**Label** — the real opening.\n"
    _b_l = _b_txt.split("\n")
    _b_p, _b_h = mask(_b_txt, "b")[:2]
    assert "**Label** — the real opening." in outline_of(_b_h, _b_l, _b_p), \
        outline_of(_b_h, _b_l, _b_p)
    _f_txt = "# T\n\nlede\n\n## S\n\n~~~\nnot a sentence\n~~~\n\nThe real one.\n"
    _f_l = _f_txt.split("\n")
    _f_p, _f_h = mask(_f_txt, "f")[:2]
    _f_o = outline_of(_f_h, _f_l, _f_p)
    assert "The real one." in _f_o and "not a sentence" not in _f_o, _f_o

    _m_txt = ("# T\n\nlede\n\n## Background\n\nold news\n\n## Result\n\n"
              "the answer\n\n[^1]: a footnote\n")
    _m_l = _m_txt.split("\n")
    _m_p, _m_h, _m_t, _m_q = mask(_m_txt, "m")
    _m_ed = editable_lines(_m_p, _m_t, _m_h, _m_q)
    _m_res = [
        {"specialist": "structure", "unit": "document · order", "lo": 1,
         "hi": None, "outline": "x", "edits": [
             {"op": "move", "line": 9, "to": 5, "why": "result first"},
             {"op": "insert", "line": 3, "new": "smuggled", "why": "no"}]},
        {"specialist": "structure", "unit": "document", "lo": 1, "hi": None,
         "edits": [{"op": "replace", "line": 5, "old": "## Background",
                    "new": "## How we got here", "why": "name the decision"}]},
    ]
    _m_out, _m_ok, _m_ref, _ = merge(_m_l, _m_res, _m_ed, (), _m_h)
    _m_j = "\n".join(_m_out)
    assert "smuggled" not in _m_j, _m_j
    assert any("only send `move`" in r[2] for r in _m_ref), _m_ref

    _ds_txt = ("# T\n\nlede\n\n## Phase 2 - Rollout\n\n"
               "Target date: 2026-10-01, owner Dana.\n\n"
               "| step | when |\n|---|---|\n| pilot | Q3 2026 |\n\n"
               "### Phase 2a\n\n```sh\nmake rollout\n```\n\n"
               "## Result\n\nthe answer is 42\n")
    _ds_l = _ds_txt.split("\n")
    _ds_p, _ds_h, _ds_t, _ds_q = mask(_ds_txt, "d")
    _ds_ed = editable_lines(_ds_p, _ds_t, _ds_h, _ds_q)
    _ds_head = next(i for i, ln in enumerate(_ds_l, 1)
                    if ln.startswith("## Phase 2"))

    def _ds_run(who="planning", line=None, outline=True, op="delete-section",
                extra=None, lines=None, held=()):
        res = [{"specialist": who, "unit": "document \u00b7 sections",
                "lo": 1, "hi": None, "outline": "x" if outline else None,
                "edits": [{"op": op, "line": _ds_head if line is None else line,
                           "why": "Phase 2 is a rollout plan"}]}]
        if extra:
            res.append(extra)
        src = lines or _ds_l
        pr, hd, tb, qt = mask("\n".join(src), "d")
        return merge(src, res, editable_lines(pr, tb, hd, qt, held),
                     {l for l, _ in qt}, hd, held=held)

    _ds_out, _ds_ok, _ds_ref, _ds_drop = _ds_run()
    _ds_j = "\n".join(_ds_out)
    for _gone in ("Phase 2 - Rollout", "Target date", "| pilot |", "Phase 2a",
                  "make rollout"):
        assert _gone not in _ds_j, (_gone, _ds_j)
    assert "the answer is 42" in _ds_j and "## Result" in _ds_j, _ds_j
    assert "lede" in _ds_j and "# T" in _ds_j, _ds_j
    assert [a[2] for a in _ds_ok] == ["delete-section"], _ds_ok
    assert "2026-10-01" in {v for _l, v in _ds_drop}, _ds_drop
    assert "42" not in {v for _l, v in _ds_drop}, _ds_drop

    for _who in ("structure", "noise", "prose"):
        assert any("may delete a section" in r[2]
                   for r in _ds_run(who=_who, outline=False)[2]), _who
    assert any("only send `move`" in r[2]
               for r in _ds_run(who="structure")[2]), _ds_run(who="structure")[2]
    assert any("not a heading" in r[2] for r in _ds_run(line=3)[2]), \
        _ds_run(line=3)[2]
    assert any("that is the title" in r[2] for r in _ds_run(line=1)[2]), \
        _ds_run(line=1)[2]
    assert any("only send `delete-section`" in r[2]
               for r in _ds_run(op="replace")[2]), _ds_run(op="replace")[2]

    _kp_l = list(_ds_l)
    _kp_l[_ds_head + 1] = ("Target date: 2026-10-01, owner Dana. "
                           "<!-- kv:keep -->")
    _kp_out, _kp_ok, _kp_ref, _ = _ds_run(lines=_kp_l)
    assert not _kp_ok, _kp_ok
    assert any("is protected, and a section comes out whole" in r[2]
               for r in _kp_ref), _kp_ref
    _kp_j = "\n".join(_kp_out)
    for _kept in ("## Phase 2 - Rollout", "| pilot |", "Phase 2a",
                  "make rollout"):
        assert _kept in _kp_j, (_kept, _kp_j)

    _sm_res = [{"specialist": "planning", "unit": "document \u00b7 sections",
                "lo": 1, "hi": None, "outline": "x",
                "edits": [{"op": "delete-section", "line": _ds_head,
                           "why": "no"}]}]
    _sm_ref = merge(_ds_l, _sm_res, _ds_ed, (), _ds_h,
                    summary_line=_ds_head)[2]
    assert any("that section is the summary" in r[2] for r in _sm_ref), _sm_ref
    assert merge(_ds_l, _sm_res, _ds_ed, (), _ds_h, summary_line=3)[1], \
        "the summary gate is refusing every section, not the summary's"

    _cl = _ds_run(extra={
        "specialist": "prose", "unit": "chunk 1", "lo": 1, "hi": len(_ds_l),
        "edits": [{"op": "replace", "line": _ds_head + 2,
                   "old": "Target date: 2026-10-01, owner Dana.",
                   "new": "Rollout lands on 2026-10-01.", "why": "shorter"}]})
    assert any("already changed by planning" in r[2] for r in _cl[2]), _cl[2]
    assert not any(a[0] == _ds_head + 2 and a[2] == "reword" for a in _cl[1]), \
        _cl[1]
    _cl2 = _ds_run(extra={
        "specialist": "prose", "unit": "chunk 1", "lo": 1, "hi": len(_ds_l),
        "edits": [{"op": "replace", "line": 3, "old": "lede",
                   "new": "the lede", "why": "shorter"}]})
    assert any(a[0] == 3 and a[2] == "reword" for a in _cl2[1]), _cl2[1]

    _bs_txt = ("# Security audit method\n\nlede\n\n"
               "## Phase 1: Reconnaissance\n\n"
               "Read the deployment manifest before the code, because a "
               "service nobody can reach is not an exposure.\n\n"
               "A hostname in the manifest and in no DNS zone is a finding.\n\n"
               "## Phase 2 - Rollout\n\n"
               "Target date: 2026-10-01, owner Dana.\n\n"
               "| step | when |\n|---|---|\n| pilot | Q3 2026 |\n\n"
               "## Result\n\nthe answer is 42\n")
    _bs_l = _bs_txt.split("\n")
    _bs_p, _bs_h, _bs_t, _bs_q = mask(_bs_txt, "d")
    _bs_method = next(i for i, ln in enumerate(_bs_l, 1)
                      if ln.startswith("## Phase 1"))
    _bs_plan = next(i for i, ln in enumerate(_bs_l, 1)
                    if ln.startswith("## Phase 2"))
    _bs_res = [{"specialist": "planning", "unit": "document · sections",
                "lo": 1, "hi": None, "outline": "x",
                "edits": [{"op": "delete-section", "line": _bs_method,
                           "why": "Phase 1 is a plan"},
                          {"op": "delete-section", "line": _bs_plan,
                           "why": "Phase 2 is a rollout plan"}]}]
    _bs_out, _bs_ok, _bs_ref, _ = merge(
        _bs_l, _bs_res, editable_lines(_bs_p, _bs_t, _bs_h, _bs_q),
        {l for l, _ in _bs_q}, _bs_h)
    _bs_j = "\n".join(_bs_out)
    assert any(r[0] == _bs_method and "its body schedules nothing" in r[2]
               for r in _bs_ref), _bs_ref
    for _kept in ("## Phase 1: Reconnaissance", "deployment manifest",
                  "no DNS zone"):
        assert _kept in _bs_j, (_kept, _bs_j)
    assert [a[0] for a in _bs_ok] == [_bs_plan], (_bs_ok, _bs_ref)
    for _gone in ("## Phase 2 - Rollout", "Target date", "| pilot |"):
        assert _gone not in _bs_j, (_gone, _bs_j)
    assert "the answer is 42" in _bs_j and "lede" in _bs_j, _bs_j

    def _pb(ln):
        return [m for _i, m in plan_body_lines([ln])]

    assert _pb("- [ ] wire the exporter") == ["task list"], _pb("- [ ] x")
    assert _pb("- [x] wired the exporter") == [], _pb("- [x] x")
    assert _pb("### Phase 2") == [], _pb("### Phase 2")
    assert EXISTENCE["phase plan"].search("### Phase 2"), \
        "the near-miss above is not a phase plan hit, so it controls nothing"
    assert _pb("Target date: 2026-10-01") == ["target date"]
    assert _pb("three weeks of work") == ["estimate"]
    assert _pb("Owner: Dana") == ["owner"]
    assert _pb("- Assigned to: Dana") == ["owner"]
    assert _pb("reported by @binance-research") == [], \
        _pb("reported by @binance-research")
    assert _pb("| Module | Owner |") == [], _pb("| Module | Owner |")
    assert _pb("| pilot | Q3 2026 |") == ["date"]
    assert _pb("the Q3 table is in the appendix") == [], _pb("the Q3 table")
    assert _pb("re-derived 2026-09-07 by a second reader") == [], \
        _pb("re-derived 2026-09-07 by a second reader")
    assert _pb("the pilot opens 2026-09-07") == ["date"], \
        _pb("the pilot opens 2026-09-07")

    _hd_txt = ("# T\n\nlede\n\n## Phase 1 - due 2026-10-01\n\n"
               "Read the manifest before the code.\n\n"
               "## Result\n\nthe answer is 42\n")
    _hd_l = _hd_txt.split("\n")
    _hd_h = mask(_hd_txt, "d")[1]
    _hd_head = next(i for i, ln in enumerate(_hd_l, 1)
                    if ln.startswith("## Phase 1"))
    assert section_schedules(_hd_h, _hd_l, _hd_head)[1] == [], \
        section_schedules(_hd_h, _hd_l, _hd_head)
    _hd_l2 = list(_hd_l)
    _hd_l2[_hd_head + 1] = "The pilot opens 2026-10-01."
    assert [m for _i, m in section_schedules(_hd_h, _hd_l2, _hd_head)[1]] \
        == ["date"], section_schedules(_hd_h, _hd_l2, _hd_head)

    _bs_sched = scheduled_sections(_bs_h, _bs_l)
    assert _bs_plan in _bs_sched and _bs_method not in _bs_sched, _bs_sched
    _bs_ol = outline_of(_bs_h, _bs_l, _bs_p, scheduled=_bs_sched)
    _ol_meth = next(l for l in _bs_ol.splitlines()
                    if "Phase 1: Reconnaissance" in l)
    _ol_plan = next(l for l in _bs_ol.splitlines() if "Phase 2 - Rollout" in l)
    assert _ol_meth.endswith("[body schedules: nothing]"), _ol_meth
    assert "[body schedules: date, target date]" in _ol_plan, _ol_plan
    assert "body schedules" not in outline_of(_bs_h, _bs_l, _bs_p), \
        outline_of(_bs_h, _bs_l, _bs_p)
    _bs_prompt = job_prompt(
        {"specialist": "planning", "unit": "document · sections",
         "lo": 1, "hi": None, "hits": [], "outline": _bs_ol},
        _bs_l, "ctx", token_lines(_bs_l))
    _bs_rules = _bs_prompt.replace(_bs_ol, "")
    assert BODY_MARK_NONE in _bs_rules and "unchecked box" in _bs_rules, \
        _bs_rules
    assert BODY_MARK_NONE in _bs_ol, _bs_ol
    assert "scheduled=scheduled_sections(headings, lines)" \
        in inspect.getsource(cmd_run), \
        "the planning outline is built without the body marks"
    assert _m_j.index("the answer") < _m_j.index("old news"), _m_j
    assert "## How we got here" in _m_j, _m_j
    assert _m_j.rstrip().endswith("[^1]: a footnote"), _m_j
    _m2 = [{"specialist": "structure", "unit": "document", "lo": 1, "hi": None,
            "edits": [{"op": "move", "line": 5, "to": body_end(_m_l) + 1,
                       "why": "background last"}]}]
    _m2_j = "\n".join(merge(_m_l, _m2, _m_ed, (), _m_h)[0])
    assert _m2_j.rstrip().endswith("[^1]: a footnote"), _m2_j
    assert _m2_j.index("the answer") < _m2_j.index("old news"), _m2_j

    o_h = [(5, "colon label", "What I found: t"), (7, "colon label", "Impact: it")]
    n_h = [(5, "colon label", "What I found: t"), (7, "colon label", "Impact: w")]
    new, old = split_shapes(o_h, n_h)
    assert not new, new
    assert len(old) == 2, old
    n_more = n_h + [(9, "colon label", "Next: r")]
    new, old = split_shapes(o_h, n_more)
    assert len(new) == 1, new
    assert len(new) + len(old) == len(n_more)
    new, old = split_shapes(o_h, [(5, "colon label", "What I found: t")])
    assert not new and len(old) == 1, (new, old)
    dup = o_h + [(9, "colon label", "Impact: it")]
    new, old = split_shapes(o_h, dup)
    assert len(new) == 1, (new, old)

    for _doc, _tgt in (
            ("# T\n\nIntro line here.\n\n    one\n    two\n\nEnd of it.\n", 6),
            ("# T\n\nIntro line here.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nEnd.\n", 6),
            ("# T\n\nIntro line here.\n\n    src/\n    |-- a.py\n    `-- b.py\n\nEnd.\n", 7)):
        _l = _doc.split("\n")
        _p, _h, _t, _q = mask(_doc)
        _e = editable_lines(_p, _t, _h, _q)
        _, _ok, _no, _ = merge(_l[:], [{"specialist": "prose", "edits": [
            {"op": "insert", "line": _tgt, "new": "BROKEN"}]}], _e)
        assert _no and "code block, table or diagram" in _no[0][2], (_tgt, _ok, _no)
    _doc = "# T\n\nIntro line here.\n\n    one\n\n    two\n\nEnd of it.\n"
    _l = _doc.split("\n")
    _p, _h, _t, _q = mask(_doc)
    _e = editable_lines(_p, _t, _h, _q)
    _, _ok, _no, _ = merge(_l[:], [{"specialist": "prose", "edits": [
        {"op": "insert", "line": 6, "new": "BROKEN"}]}], _e)
    assert _no and not _ok, (_ok, _no)
    _, _ok, _no, _ = merge(["First sentence.", "Second sentence."],
                           [{"specialist": "prose", "lo": 1, "hi": 2, "edits": [
                               {"op": "replace", "line": True,
                                "old": "First sentence.", "new": "X."}]}], {1, 2})
    assert not _ok and _no, (_ok, _no)
    assert parse_reply('{"edits":[{"line":true,"op":"replace",'
                       '"old":"a","new":"b"}]}')[0] is None, \
        "a boolean line survives the sanitiser and indexes line 1"
    _o, _ok, _no, _ = merge(["- Parent.", "  - Child.", "- Sibling."],
                            [{"specialist": "prose", "lo": 1, "hi": 3, "edits": [
                                {"op": "replace", "line": 2, "old": "- Child.",
                                 "new": "- Changed child."}]}], {1, 2, 3})
    assert _o[1] == "  - Changed child.", _o
    _one = ["Alpha cats are calm. Beta dogs are quiet. Gamma birds are small."]
    _res = [{"specialist": _s, "lo": 1, "hi": 1,
             "edits": [{"op": "replace", "line": 1, "old": _one[0],
                        "new": _n, "why": "reword"}]}
            for _s, _n in (
                ("prose", "Alpha felines are calm. Beta dogs are quiet. "
                          "Gamma birds are small."),
                ("quotable", "Alpha cats are calm. Beta hounds are quiet. "
                             "Gamma birds are small."),
                ("actionable", "Alpha cats are calm. Beta dogs are quiet. "
                               "Gamma finches are small."))]
    _o, _ok, _no, _ = merge(_one[:], _res, {1})
    _text = _o[0]
    for _who, _word in (("prose", "felines"), ("quotable", "hounds"),
                        ("actionable", "finches")):
        _said = any(str(a[1]).split(":")[0].strip() == _who for a in _ok)
        _in = _word in _text
        _ref = any(str(r[1]).split(":")[0].strip() == _who for r in _no)
        assert _said == _in, (_who, _said, _in, _text)
        assert _in or _ref, (f"{_who} lost with no report", _ok, _no)
    _doc = "# T\n\nIntro line here.\n\nEnd of it.\n"
    _l = _doc.split("\n")
    _p, _h, _t, _q = mask(_doc)
    _e = editable_lines(_p, _t, _h, _q)
    for _tgt in (1, 4):
        _, _ok, _no, _ = merge(_l[:], [{"specialist": "summary", "edits": [
            {"op": "insert", "line": _tgt, "new": "A new paragraph."}]}], _e)
        assert _ok and not _no, (_tgt, _ok, _no)

    wrapped = ["The retry policy is applied by the",
               "API Gateway when the upstream is",
               "unavailable for more than thirty seconds."]
    _g, _ok, _no, _ = merge(wrapped[:], [{"specialist": "prose", "edits": [
        {"line": 1, "old": wrapped[0], "new": "The API Gateway retries."},
        {"line": 2, "old": wrapped[1], "new": "It waits for the upstream."}]}],
        {1, 2, 3})
    assert not _ok and len(_no) == 2, (_ok, _no)
    assert _g == wrapped, _g
    assert "ln not in proposed" in inspect.getsource(merge), \
        "the dangling prune is back to keeping the last claim"

    src = ["# T", "the gate is a concern", "```", "code —— here", "```"]
    _p, _h, _t, _q = mask("\n".join(src))
    ed = editable_lines(_p, _t, _h, _q)
    assert ed == {1, 2}, ed
    got, ok, no, _ = merge(src, [{"specialist": "actionable", "edits": [
        {"line": 2, "old": "the gate is a concern", "new": "open the gate"}]}], ed)
    assert got[1] == "open the gate" and len(ok) == 1 and not no, (got, ok, no)
    _, ok, no, _ = merge(src, [{"specialist": "actionable", "edits": [
        {"line": 2, "old": "a line nobody wrote", "new": "x"}]}], ed)
    assert not ok and no and "does not match" in no[0][2], no
    _, ok, no, _ = merge(src, [{"specialist": "prose", "edits": [
        {"line": 4, "old": "code —— here", "new": "x"}]}], ed)
    assert not ok and no and "code fence" in no[0][2], no
    fact_src = ["fixed in BIQ-1131, scoring 22/26 on the set"]
    _, ok, no, _ = merge(fact_src, [{"specialist": "prose", "edits": [
        {"line": 1, "old": fact_src[0], "new": "fixed, scoring well"}]}], {1})
    assert not ok and "BIQ-1131" in no[0][2] and "22/26" in no[0][2], no
    _, ok, no, _ = merge(fact_src, [{"specialist": "prose", "edits": [
        {"line": 1, "old": fact_src[0], "new": "BIQ-1131 scores 22/26"}]}], {1})
    assert ok and not no, (ok, no)
    _ias = (SUBSTITUTION.get("identifier as subject")
            or OCCURRENCE.get("identifier as subject")
            or EXISTENCE.get("identifier as subject"))
    assert not _ias.search("How `Chef` publishes events without LWJP is open.")
    assert not _ias.search("The row from AIX_DB is stale.")
    assert _ias.search("LOCATION is matching field labels.")
    _echo = (EXISTENCE.get("echo") or SUBSTITUTION.get("echo")
             or OCCURRENCE.get("echo"))
    assert not _echo.search("## TL;DR") and not _echo.search("## Key Takeaways")
    assert _echo.search("TL;DR the gate is red.")
    assert _echo.search("In summary, it works.")
    _fm = ["---", "title: x", "---", "", "# Kill verbosity", "", "Body text."]
    _fmp, _fmh, _, _ = mask("\n".join(_fm))
    _fmed = {i + 1 for i, l in enumerate(with_spans(_fmp, "\n".join(_fm)))
             if l.strip()}
    for _blank in (4, 6):
        _, _fa, _fr, _ = merge(list(_fm), [{"specialist": "summary", "edits": [
            {"op": "insert", "line": _blank,
             "new": "## Summary\n\nThe result."}]}], _fmed, (), _fmh)
        assert _fa and not _fr, (_blank, _fa, _fr)
    def _ed(ls):
        return {i + 1 for i, l in enumerate(ls) if l.strip()
                and not l.startswith(("    ", "\t"))
                and not l.strip().startswith("|")
                and not TREE_CHARS & set(l)}
    for _blk, _at in ((["| a | b |", "|---|---|", "", "| c | d |"], 3),
                      (["    code line", "", "    more code"], 2),
                      (["├── src/", "│   └── a.js", "", "└── test/"], 3)):
        _, _fa, _fr, _ = merge(list(_blk), [{"specialist": "summary", "edits": [
            {"op": "insert", "line": _at, "new": "text"}]}],
            _ed(_blk), (), [])
        assert not _fa and "inside a code block" in _fr[0][2], (_blk, _fa, _fr)
    for _blk, _at in ((["| a | b |", "|---|---|", "| c | d |", "", "more"], 4),
                      (["    code line", "", "prose follows."], 2)):
        _, _fa, _fr, _ = merge(list(_blk), [{"specialist": "summary", "edits": [
            {"op": "insert", "line": _at, "new": "text"}]}],
            _ed(_blk), (), [])
        assert _fa and not _fr, (_blk, _fa, _fr)
    _dup = ["Alpha line about the retry budget.", "Beta line about the queue.",
            "Gamma line about the gate."]
    _ptr = "See the finding and fix in the failing-checks section."
    _dg, _da, _dr, _ = merge(list(_dup), [{"specialist": "structure", "lo": 1,
        "hi": 3, "edits": [{"line": i + 1, "old": _dup[i], "new": _ptr}
                           for i in range(3)]}], {1, 2, 3})
    assert sum(1 for l in _dg if l.strip() == _ptr) == 0, _dg
    _direct = [r for r in _dr if "the rest of that block" not in r[2]]
    assert sum("written once" in r[2] for r in _direct) == 2, _dr
    assert any("was refused (" in r[2] and "the rest of that block" in r[2]
               for r in _dr), _dr
    _tb = ["| Tool | Owner | State |", "|---|---|---|",
           "| atlas | platform | live |"]
    for _new, _ok in ((" | atlas | platform |", False),
                      ("| atlas | platform | shipped |", True)):
        _, _ta, _tr, _ = merge(list(_tb), [{"specialist": "structure", "edits": [
            {"line": 3, "old": _tb[2], "new": _new}]}], {1, 2, 3})
        if _ok:
            assert _ta and not _tr, (_new, _ta, _tr)
        else:
            assert not _ta and _tr and "keeps its columns" in _tr[0][2], \
                (_new, _ta, _tr)
    _dg, _da, _dr, _ = merge(list(_dup), [{"specialist": "noise", "lo": 1,
        "hi": 3, "edits": [{"line": i + 1, "old": _dup[i], "new": ""}
                           for i in range(3)]}], {1, 2, 3})
    assert len(_da) == 3 and not _dr, (_da, _dr)
    ref = ["This dates from Oct 2025 (`4737d6b`)."]
    _, ok, no, drops = merge(ref, [{"specialist": "noise", "edits": [
        {"line": 1, "old": ref[0], "new": "This dates from Oct 2025."}]}], {1})
    assert ok and not no, (ok, no)
    assert drops == [(1, "4737d6b")], drops

    two = ["The gate covers 85% of rows.", "Coverage is 85% today."]
    _, ok, no, _ = merge(two, [{"specialist": "prose", "edits": [
        {"line": 1, "old": two[0], "new": "The gate covers most rows."}]}],
        {1, 2})
    assert ok and not no, (ok, no)
    one = ["The gate covers 85% of rows.", "Nothing else here."]
    _, ok, no, _ = merge(one, [{"specialist": "prose", "edits": [
        {"line": 1, "old": one[0], "new": "The gate covers most rows."}]}],
        {1, 2})
    assert not ok and "85%" in no[0][2], no

    cut = ["Both numbers describe the hand-written rules, so they agree."]
    _, ok, no, _ = merge(cut, [{"specialist": "prose", "edits": [
        {"line": 1, "old": cut[0], "new": "Both numbers describe the rules"}]}],
        {1})
    assert not ok and "ended a sentence" in no[0][2], no

    par = ['It "starts measuring what DLP finds" today.']
    _, ok, no, _ = merge(par, [{"specialist": "prose", "edits": [
        {"line": 1, "old": par[0], "new": 'It starts measuring what DLP finds".'}
    ]}], {1})
    assert not ok and "unpaired quote" in no[0][2], no

    multi = ["A plain line here."]
    _, ok, no, _ = merge(multi, [{"specialist": "prose", "edits": [
        {"line": 1, "old": multi[0],
         "new": "A plain line.\n\n## Next Steps\n\nIt is worth noting this."}]}],
        {1})
    assert not ok and "replacement text has" in no[0][2], no

    _inv = ["The URL pattern already ends on", "`[^a]` and the number pattern."]
    _, _ok, _no, _ = merge(list(_inv), [{"specialist": "prose", "lo": 1, "hi": 2,
        "edits": [{"line": 1, "old": _inv[0],
                   "new": "The URL pattern ends on `[^^]`"}]}], {1, 2})
    assert not _ok and any("adds [^^]" in n[2] for n in _no), _no
    _mv = ["The counter reached 312 values", "across fixtures/pii.json today."]
    _, _ok, _no, _ = merge(list(_mv), [{"specialist": "prose", "lo": 1, "hi": 2,
        "edits": [
            {"line": 1, "old": _mv[0],
             "new": "The counter reached 312 values across fixtures/pii.json."},
            {"line": 2, "old": _mv[1], "new": ""}]}], {1, 2})
    assert len(_ok) == 2 and not _no, (_ok, _no)
    _mk = ["Run the deploy command now."]
    _, _ok, _no, _ = merge(list(_mk), [{"specialist": "prose", "lo": 1, "hi": 1,
        "edits": [{"line": 1, "old": _mk[0], "new": "Run `deploy` now."}]}], {1})
    assert _ok and not _no, (_ok, _no)

    fen = ["text", "```py", "a = 1", "```", "more"]
    try:
        merge(fen, [{"specialist": "noise", "edits": [
            {"line": 1, "old": "text", "new": "text\n```\nx\n```"}]}], {1, 5})
        raise AssertionError("a fence-count change has to stop the merge")
    except ValueError as exc:
        assert "code-fence" in str(exc), exc
    _, ok, no, _ = merge(fen, [{"specialist": "noise", "edits": [
        {"line": 1, "old": "text", "new": "text\n```"}]}], {1, 5})
    assert not ok and "could not parse" in no[0][2], no

    got, ok, no, _ = merge(src, [
        {"specialist": "noise", "edits": [
            {"line": 2, "old": "the gate is a concern", "new": ""}]},
        {"specialist": "prose", "edits": [
            {"line": 2, "old": "the gate is a concern", "new": "reworded"}]}], ed)
    assert "the gate is a concern" not in got and "reworded" not in got, got
    assert len(no) == 1 and "already changed by noise" in no[0][2], no
    got, ok, _, _ = merge(src, [{"specialist": "summary", "edits": [
        {"op": "insert", "line": 2, "new": "## Summary\n\nOne line."}]}],
        ed, (), [(0, 1, "T")])
    assert got[:5] == ["# T", "", "## Summary", "", "One line."], got
    assert got[6] == "the gate is a concern", got
    def _real_ed(ls):
        _p, _h, _, _ = mask("\n".join(ls))
        return ({i + 1 for i, l in enumerate(with_spans(_p, "\n".join(ls)))
                 if l.strip()}, _h)
    for _one in (["# T", "", "a.", "", "b.", "", "c.", "", "d."],
                 ["plain text.", "", "more.", "", "and more.", "", "end."],
                 ["# T", "", "## Bg", "", "a.", "", "b.", "", "c."],
                 ["# T", "", "intro para.", "", "| a | b |", "|---|---|",
                  "| c | d |", "", "## Bg", "", "a.", "", "b."]):
        _oned, _onh = _real_ed(_one)
        _og, _oa, _or_, _ = merge(
            list(_one), [{"specialist": "summary", "edits": [
                {"op": "insert", "line": len(_one),
                 "new": "## Summary\n\nThe result in one line."}]}],
            _oned, (), _onh)
        assert _oa and not _or_, (_one, _oa, _or_)
        assert "## Summary" in _og[:3], _og
        _op_, _oh, _, _ = mask("\n".join(_og))
        assert opening_summary(_oh, _op_, SUMMARY_NEEDED_FROM)["present"], _og
    _bur = ["# T", "", "a paragraph of body that runs on long enough to be real text a reader must get through before reaching the summary, rather than a byline or a link, which is the whole distinction this check exists to make.", "", "## Summary", "", "late."]
    _burp, _burh, _, _ = mask("\n".join(_bur))
    assert not opening_summary(_burh, _burp, SUMMARY_NEEDED_FROM)["present"]
    _fine = ["# T", "", "**Date:** 2026-03-22 | **Author:** AIX Team", "",
             "See `./other.md` and [the brief](./brief.md)", "",
             "## Summary", "", "The answer is 12 months."]
    _fp, _fh, _, _ = mask("\n".join(_fine))
    assert opening_summary(_fh, _fp, SUMMARY_NEEDED_FROM)["present"], _fine

    for _rt in (["Andrzej Figas", "", "###### 00:00 - 04:30", "", "speech."],
                ["# Title", "", "## Background", "", "text."],
                ["## Background", "", "text."]):
        _rted, _rth0 = _real_ed(_rt)
        _rtg, _rta, _rtr, _ = merge(
            list(_rt), [{"specialist": "summary", "edits": [
                {"op": "insert", "line": len(_rt),
                 "new": "## Summary\n\nThe result in one line."}]}],
            _rted, (), _rth0)
        assert _rta and not _rtr, (_rt, _rta, _rtr)
        _rtp, _rth, _, _ = mask("\n".join(_rtg))
        _found = opening_summary(_rth, _rtp, SUMMARY_NEEDED_FROM)
        assert _found and _found["present"], (_rt, _rtg, _found)
    _sp = ["Dana", "", "###### 00:00 - 01:10", "", "speech.", "",
           "Alex", "", "###### 01:10 - 02:00", "", "more speech.", ""]
    _spp, _sph, _spt, _spq = mask("\n".join(_sp))
    got, ok, _, _ = merge(_sp, [{"specialist": "summary", "edits": [
        {"op": "insert", "line": 1, "new": "## Summary\n\nThe result."}]}],
        editable_lines(_spp, _spt, _sph, _spq), (), _sph)
    assert got[:5] == ["## Summary", "", "The result.", "", "Dana"], got
    _dup = ["# T", "", "Body text here that runs on long enough to be real prose which a reader must get through before reaching the summary, rather than a byline or a link line that costs no reading at all.", "", "## Summary", "",
            "Inside a template.", "", "More body."]
    _dupp, _duph, _dupt, _dupq = mask("\n".join(_dup))
    _de = editable_lines(_dupp, _dupt, _duph, _dupq)
    _, ok, no, _ = merge(_dup, [{"specialist": "summary", "edits": [
        {"op": "insert", "line": 2, "new": "## Summary\n\nThe result."}]}],
        _de, (), _duph)
    assert not ok and no and "already has a heading 'Summary'" in no[0][2], no
    _two = ["# T", "", "Body text here.", "", "More body here."]
    _twop, _twoh, _twot, _twoq = mask("\n".join(_two))
    got, ok, no, _ = merge(_two, [{"specialist": "summary", "edits": [
        {"op": "insert", "line": 2, "new": "## Summary\n\nOne."},
        {"op": "insert", "line": 4, "new": "## Summary\n\nTwo."}]}],
        editable_lines(_twop, _twot, _twoh, _twoq), (), _twoh)
    assert len(ok) == 1 and len(no) == 1, (ok, no)
    assert "\n".join(got).count("## Summary") == 1, got
    _, ok, no, _ = merge(src, [{"specialist": "prose", "edits": [
        {"op": "insert", "line": 4, "new": "INJECTED"}]}], ed)
    assert not ok and no and "code fence" in no[0][2], no
    _, ok, no, _ = merge(src, [
        {"specialist": "structure", "edits": [
            {"op": "insert", "line": 2, "new": "first"}]},
        {"specialist": "summary", "edits": [
            {"op": "insert", "line": 2, "new": "second"}]}], ed)
    assert len(ok) == 1 and len(no) == 1 and "already inserts" in no[0][2], (ok, no)
    real_sum = ("## Summary\n\nFirst, priorities are open, and Alex must "
                "propose a list to Priya, as discussed in §\"1. Priorities\".")
    _, ok, no, _ = merge(src, [{"specialist": "summary", "edits": [
        {"op": "insert", "line": 2, "new": real_sum}]}], ed)
    assert not ok and no and "inserting has" in no[0][2], no
    assert "empty framing" in no[0][2], no
    _, ok, no, _ = merge(src, [{"specialist": "summary", "edits": [
        {"op": "insert", "line": 2, "new": "Run `kv verify to check it."}]}], ed)
    assert not ok and no and "backtick unclosed" in no[0][2], no

    assert "em-dash pressure" in added_shapes("a — b — c — d — e in one go.")

    assert added_shapes("text\n\n## Security\n\nmore") == \
        ["a heading below its first line"]
    assert not added_shapes("## Summary\n\nThe gate is missing.")
    assert not added_shapes("\n\n## Summary\n\nThe gate is missing.")
    assert added_shapes("## Summary\n\nText.\n\n### Detail\n\nMore.") == \
        ["a heading below its first line"]
    _park = "# Roadmap\n\nThe adoption target is X%. Nobody set it.\n"
    _quotes = "One question is open: the adoption target is X%."
    assert added_shapes(_quotes) == ["parked problem"]
    assert not added_shapes(_quotes, _park)
    assert added_shapes("It is worth noting that the target is X%.", _park) \
        == ["frame"]
    assert "parked problem" in added_shapes(
        "The retry loop needs further investigation.", _park)
    _tbd = "# Roadmap\n\nPricing is TBD.\n"
    assert not added_shapes("Pricing is still TBD.", _tbd)
    assert "parked problem" in added_shapes("The new rollout owner is TBD.",
                                            _tbd)
    assert not added_shapes("One question is open: the target is X%.", _park)
    _tbc = "# Plan\n\nThe rollout date is To Be Confirmed.\n"
    assert added_shapes("The rollout date is To Be Confirmed.") == \
        ["asks reader to verify"]
    assert not added_shapes("The rollout date is To Be Confirmed.", _tbc)
    assert reporting_text("17% to 68%", "measured 17% to 68%.",
                          "the range is 17% to 68% overall")
    assert not reporting_text("17% to 68%", "measured 17% to 68%.",
                              "the range is 19% to 71% overall")

    _rule = ["Never run the importer against the production warehouse.",
             "", "The importer reads the drop and writes it to the warehouse.",
             "", "It is unclear whether the retry reuses the batch id."]
    _gone, _weak, _thin, _rel = claims_lost(_rule, [_rule[2]])
    assert [s for _l, s in _gone] == [_rule[0], _rule[4]], _gone
    assert not _weak and not _thin, (_weak, _thin)
    _kept = ["Do not run the importer against the production warehouse.",
             "Whether the retry reuses the batch id is unclear.", _rule[2]]
    assert claims_lost(_rule, _kept) == ([], [], [], []), claims_lost(_rule, _kept)
    _g, _w, _t, _rl = claims_lost(
        ["The dashboard shows the last successful run."], [""])
    assert not _g and not _w and len(_t) == 1, (_g, _w, _t)
    assert claims_lost(["That is the point."], [""]) == ([], [], [], [])

    _amp = ["A decorator alone is not enough, and the cross-review proved it.",
            "", "Security is a scheduled task list, not an assessment."]
    _kept_amp = ["A decorator alone is not enough.", "",
                 "Security is a scheduled task list."]
    assert claims_lost(_amp, _kept_amp) == ([], [], [], []), \
        "the retention gate is supposed to be silent here — that is the defect"
    assert [c for _l, _o, _n, c in tails_cut(_amp, _kept_amp)] == \
        ["and the cross-review proved it", "not an assessment"]
    assert len(claim_words("not an assessment")) == 1
    _row2 = ["D2 A decorator alone is not enough for parametrised fixtures, "
             "and the audit showed that the decorator is skipped."]
    _row2n = ["D2 A decorator alone is not enough for parametrised fixtures."]
    _row3 = [_row2[0] + " testing"]
    _row3n = [_row2n[0] + " testing"]
    assert tails_cut(_row2, _row2n, [1], [1]), "the last-column case regressed"
    assert [c for _l, _o, _n, c in tails_cut(_row3, _row3n, [1], [1])] == \
        ["and the audit showed that the decorator is skipped"], \
        "a cut in a cell that is not the last column is still invisible"
    assert not tails_cut(_row3, _row3n), \
        "the row allowance leaked into prose, where a middle cut is not this " \
        "check's finding"
    _cit = ("D5 build the decorator A DECORATOR ALONE IS NOT ENOUGH, AND THE "
            "CROSS-REVIEW PROVED IT. (C270) open")
    _citn = "D5 build the decorator A DECORATOR ALONE IS NOT ENOUGH. open"
    assert tail_cut(_cit, _citn, in_row=True) == \
        "and the cross-review proved it. (c270)", \
        "the cut that also takes a trailing citation is still invisible"
    assert "c270" in (tail_cut(_cit, _citn, in_row=True) or ""), \
        "the dropped provenance token has to be IN the reported cut -- " \
        "nothing else in this tool names it"
    assert tail_cut("D5 goal Retries are capped at three per the audit "
                    "(C270) open",
                    "D5 goal Retries are capped at three. open",
                    in_row=True) == "per the audit (c270)", \
        "an unterminated cell losing its tail is the same amputation"
    assert tail_cut(_cit, "D5 build the decorator A DECORATOR ALONE IS NOT "
                          "ENOUGH?! open", in_row=True) is None, \
        "two characters at the cut point is a reworded stump, not a repair"
    assert tail_cut("D5 goal the runner retries and the audit proved it open",
                    "D5 goal the runner retriesx open", in_row=True) is None, \
        "a letter at the cut point is a reword, not a moved full stop"
    assert tail_cut("D5 build the decorator A decorator on its own is "
                    "insufficient, and the cross-review proved it. (C270) open",
                    "D5 build the decorator A decorator alone is not enough. "
                    "open", in_row=True) is None, \
        "a reworded stump is a condensation and this check does not own it"
    assert tail_cut(_cit, _citn) is None, \
        "the terminator allowance leaked into prose"
    _sfx = "D2 run the whole suite and report the failures"
    assert tail_cut(_sfx, "D2 run the ures", in_row=True) is None, \
        "a cut whose trailing edge lands mid-word is a clipped word, not a " \
        "dropped clause"
    assert tail_cut(_sfx, "D2 run the failures", in_row=True) == \
        "whole suite and report the", \
        "the trailing-boundary guard swallowed a real clause cut"
    _spl_o = ["Routing inference happens in our own BigQuery, and that was "
              "set up in OPS-4125."]
    assert not tails_cut(_spl_o,
                         ["Routing inference happens in our own BigQuery.",
                          "That was set up in OPS-4125."]), \
        "a clause moved to the next sentence is a split, not a cut"
    assert tails_cut(_spl_o, ["Routing inference happens in our own "
                              "BigQuery."]), \
        "the document-scoped pardon swallowed a cut whose clause is gone"
    assert tails_cut(
        ["Routing inference happens in our own BigQuery, and the latency "
         "budget covers OPS-4125."],
        ["Routing inference happens in our own BigQuery.",
         "The latency budget is documented."]), \
        "a cut only SOME of whose words survive elsewhere is still a cut; " \
        "the pardon is for TOTAL survival and this one is partial"
    _fr_o = ("Unless explicitly authorized by the security lead, production "
             "database access is prohibited.")
    _fr_c = tail_cut(_fr_o, "Production database access is prohibited.",
                     in_row=True)
    assert "FRONT" in cut_where(_fr_o, _fr_c, True), \
        "a front cut in a row is printed under a heading that says the " \
        "opening was kept, and must name itself"
    assert cut_where(_sfx, "whole suite and report the", False) == "", \
        "prose is the end case and must add nothing"
    assert not tails_cut(
        ["It is important to note that you should validate every single frame "
         "before decoding it, and parser acceptance must be treated as "
         "untrusted."],
        ["Validate every frame before decoding; treat parser acceptance as "
         "untrusted."])
    assert not tails_cut(["The build fails on macOS only, unfortunately."],
                         ["The build fails on macOS only."])
    _hard = ["Rotate the signing key every ninety days without exception."]
    assert not tails_cut(_hard, ["Rotate."])
    assert claims_lost(_hard, ["Rotate."])[2], "claims_lost should own it"
    assert not tails_cut(["The cache must remain enabled, the cache must "
                          "remain enabled."],
                         ["The cache must remain enabled."])
    _redundant = ["The service writes a complete audit record for every "
                  "rejected request, which provides a complete audit record "
                  "of rejected requests."]
    assert tails_cut(_redundant, ["The service writes a complete audit record "
                                  "for every rejected request."]), \
        "declared residue: a redundant tail carrying any new word is reported"
    assert not tails_cut(["The dashboard shows the last successful run."],
                         ["The dashboard shows the last successful run."])
    assert tail_cut("the log writes the prompt and the completion",
                    "the log write") is None

    _rel_o = ("# Doc\n\n## Gate\n\nNever run the importer against production "
              "without a backup.\n\n## Notes\n\nNever run the importer against "
              "production without a backup.\n")
    _rel_n = ("# Doc\n\n## Gate\n\n\n\n## Notes\n\nNever run the importer "
              "against production without a backup.\n")
    _ro_p, _ro_h, _ro_t, _ = mask(_rel_o, "rel")
    _rn_p, _rn_h, _rn_t, _ = mask(_rel_n, "rel")
    _ro, _rn = with_table_text(_ro_p, _ro_t), with_table_text(_rn_p, _rn_t)
    _r4 = claims_lost(_ro, _rn, untouched_lines(_ro, _rn), _ro_h, _rn_h)
    assert not _r4[0] and not _r4[1], _r4
    assert [(x[0], x[2]) for x in _r4[3]] == [(5, "gate")], _r4[3]
    assert claims_lost(_ro, _rn, untouched_lines(_ro, _rn))[3] == []
    _mv_n = ("# Doc\n\n## Notes\n\nNever run the importer against production "
             "without a backup.\n\n## Gate\n\nNever run the importer against "
             "production without a backup.\n")
    _mn_p, _mn_h, _mn_t, _ = mask(_mv_n, "rel")
    _mn = with_table_text(_mn_p, _mn_t)
    assert claims_lost(_ro, _mn, untouched_lines(_ro, _mn),
                       _ro_h, _mn_h)[3] == [], "a moved section is not a loss"
    _rn_txt = ("# Doc\n\n## How we got here\n\nNever run the importer against "
               "production without taking a backup first.\n\n## Notes\n\n"
               "nothing here.\n")
    _rp, _rh, _rt, _ = mask(_rn_txt, "rel")
    _rr = with_table_text(_rp, _rt)
    _ren_o = ("# Doc\n\n## Gate\n\nNever run the importer against production "
              "without a backup.\n\n## Notes\n\nnothing here.\n")
    _eo_p, _eo_h, _eo_t, _ = mask(_ren_o, "rel")
    _eo = with_table_text(_eo_p, _eo_t)
    assert claims_lost(_eo, _rr, untouched_lines(_eo, _rr),
                       _eo_h, _rh)[3] == [], "a renamed heading is not a move"
    assert not wall_paragraphs(["1) One. Two.", "2) Three. Four."])
    assert em_dash_pressure(["1) a — b", "2) c — d"]) == []
    _od = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    _nd = [{"text": "c"}, {"text": "d"}]
    _rd_fixed, _rd_new = repeat_delta(_od, _nd)
    assert (_rd_fixed, [d["text"] for d in _rd_new]) == (2, ["d"]), _rd_new
    assert repeat_delta(_od, _od) == (0, [])
    assert _rd_new[0]["before"] is None and _rd_new[0]["now"] == 2, _rd_new
    _r6, _a3 = repeat_delta([{"text": str(i)} for i in range(6)],
                            [{"text": f"n{i}"} for i in range(3)])
    assert (_r6, len(_a3)) == (6, 3), (_r6, _a3)
    _t2 = [{"text": "x", "lines": [1, 2]}]
    _t3 = [{"text": "x", "lines": [1, 2, 3]}]
    _t3_out = repeat_delta(_t2, _t3)[1]
    assert [d["text"] for d in _t3_out] == ["x"], "a third copy is not reported"
    assert repeat_delta(_t2, _t2)[1] == [], "the same count is not a change"
    assert (_t3_out[0]["before"], _t3_out[0]["now"]) == (2, 3), _t3_out
    _sp_dir = tempfile.mkdtemp()
    try:
        _sp_head = "Session rows are retained"
        _sp_pad = ("Some unrelated prose sits here to give the document a "
                   "little length.")
        _sp_o = (f"# T\n\n{_sp_head} for twelve months in the primary store."
                 f"\n\n{_sp_pad}\n\n{_sp_head} under the archival policy as "
                 f"well.\n")
        _sp_n = _sp_o + f"\n{_sp_head} in the cold tier too.\n"
        _sp_po, _sp_pn = Path(_sp_dir) / "o.md", Path(_sp_dir) / "n.md"
        _sp_po.write_text(_sp_o, encoding="utf-8")
        _sp_pn.write_text(_sp_n, encoding="utf-8")
        _sp_buf = io.StringIO()
        with contextlib.redirect_stdout(_sp_buf):
            cmd_verify(argparse.Namespace(
                original=str(_sp_po), edited=str(_sp_pn), chat=False,
                content_edit=False, exempt=[]))
        _sp_out = _sp_buf.getvalue()
        assert "the original had 2, the edit has 3" in _sp_out, \
            ("verify no longer reports the count it measured for a repeat the "
             f"original already had: {_sp_out[-400:]!r}")
        assert "no run of these words in the original" not in _sp_out, \
            ("verify calls a measured before-count an absent one, which is "
             "the measurement nobody took")
    finally:
        shutil.rmtree(_sp_dir, ignore_errors=True)
    _mg_dir = tempfile.mkdtemp()
    try:
        _mg_o = ("# Runbook\n\nThe restart looks transient but usually is not, "
                 "so page the on-call engineer before you touch anything.\n\n"
                 "You must never run this against production alone.\n\n"
                 "See `deploy/rollback.sh` for the path and ticket OPS-4471.\n")
        _mg_po = Path(_mg_dir) / "o.md"
        _mg_po.write_text(_mg_o, encoding="utf-8")

        def _mg(edited):
            pn = Path(_mg_dir) / "n.md"
            pn.write_text(edited, encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cmd_verify(argparse.Namespace(
                    original=str(_mg_po), edited=str(pn), chat=False,
                    content_edit=False, exempt=[]))
            return rc, buf.getvalue()

        _needle = "Meaning is not checked here"
        _rc, _out = _mg(_mg_o.replace("looks transient but usually is not",
                                      "looks transient and usually is"))
        assert _rc == 0 and "PASS" in _out, (_rc, _out[-300:])
        assert _out.count(_needle) == 0 and "run crosscheck" in _out, \
            f"CONTROL FAILED - PASS printed the caveat twice: {_out[-300:]!r}"
        _rc, _out = _mg(_mg_o.replace("# Runbook\n\n", ""))
        assert _rc == 3 and _out.count(_needle) == 1, (_rc, _out[-300:])
        _rc, _out = _mg(_mg_o.replace("OPS-4471", "OPS-9999"))
        assert _rc == 1 and _out.count(_needle) == 1, (_rc, _out[-300:])
    finally:
        shutil.rmtree(_mg_dir, ignore_errors=True)

    _src_spl = inspect.getsource(cmd_verify)
    assert "no run of these words in the original" in _src_spl \
        and "the original said once" not in _src_spl, \
        "the repeated-text line must report the count it measured"
    assert SPLICE_WINDOW < 8, "the splice window must be shorter than the scan"
    _sp = ["Alpha before it gives up today.", "Beta before it gives up now."]
    assert duplicates(_sp, SPLICE_WINDOW), "the splice window finds no graft"
    assert not duplicates(_sp), "eight words would have caught it already"
    assert cluster_lines([{"lines": [143, 173]}, {"lines": [143, 173]},
                          {"lines": [9, 11]}]) == "143, 173 (2 texts); 9, 11"
    assert "more" in cluster_lines([{"lines": [i, i + 1]} for i in range(9)])
    assert "repeat_delta(o_dups" in inspect.getsource(cmd_run) and \
        "repeats introduced" in inspect.getsource(cmd_run), \
        "the run nets resolved against introduced"
    assert "of {out_path.name}" in inspect.getsource(cmd_run), \
        "repeats introduced prints output lines without saying so"
    assert "if relocated:" in inspect.getsource(cmd_verify) and \
        "rules that changed section" in inspect.getsource(cmd_verify), \
        "verify computes relocated rules and never shows them"
    assert "hard = _failed_block(" not in inspect.getsource(
        cmd_verify).split("if relocated:")[1].split("if thinned:")[0], \
        "a relocated rule must not fail the run"

    _keep = ["The importer runs nightly against the warehouse."]
    _rec = "**Re-check any 'unassertable' record against the code.**"
    _gone, _weak, _thin, _rel = claims_lost(_keep + [_rec], _keep)
    assert _gone == [(2, _rec)], (_gone, _weak, _thin)
    _plain = "Re-check any unassertable record against the code."
    assert claims_lost(_keep + [_plain], _keep)[0] == [(2, _plain)]
    for _f, _txt in (("- Confirm every citation against the file in this turn.",
                      "Confirm every citation against the file in this turn."),
                     ("1. Replace the retry with a single call here.",
                      "Replace the retry with a single call here.")):
        assert claims_lost(_keep + [_f], _keep)[0] == [(2, _txt)], _f
    for _f in ("The parser removes the stale entry before shipping.",
               "We removed the retry from the write path last week.",
               "Removing the retry made the importer faster overall."):
        assert claims_lost(_keep + [_f], _keep)[0] == [], _f
    _oh = [(0, 1, "T"), (2, 2, "Build list"), (8, 2, "Shape"),
           (14, 2, "Open"), (20, 2, "Detail")]
    _nh = [(0, 1, "T"), (2, 2, "Files to build"), (8, 2, "Session layout"),
           (14, 2, "Questions to verify"), (20, 2, "Detail")]
    _ren, _gone_h = heading_moves(_oh, _nh)
    assert _ren == [("Build list", "Files to build"),
                    ("Shape", "Session layout"),
                    ("Open", "Questions to verify")], _ren
    assert _gone_h == [], _gone_h
    assert heading_moves(_oh, [h for h in _oh if h[2] != "Shape"]) \
        == ([], ["Shape"]), heading_moves(_oh, [h for h in _oh if h[2] != "Shape"])
    assert heading_moves(_oh, _oh) == ([], [])
    _lvl = [(0, 1, "T"), (2, 3, "Build list")]
    assert heading_moves([(0, 1, "T"), (2, 2, "Build list")], _lvl) \
        == ([], []), heading_moves([(0, 1, "T"), (2, 2, "Build list")], _lvl)
    assert inbound_anchors(Path(__file__), "no such heading anywhere") == []

    assert not RECOMMENDATION.match("**verify's hard failures** are three.")
    assert RECOMMENDATION.match("Verify the header before the write.")
    for _hold in ("Keep the human approval gate before any write.",
                  "Stop the delete until the copy reports done.",
                  "Hold the direction until the gate in item 9 runs.",
                  "Keep the retry at 3.5 seconds until the copy confirms.",
                  "Keep the U.S. endpoint isolated until migration completes.",
                  "Block requests that could expose credentials before logs.",
                  "Hold locks that were acquired until the transaction ends.",
                  "Stop the deploy (the window is closing) until Dana says.",
                  "Keep the retry at 3.5s, in the copy path, until it says ok.",
                  "Keep the is-a-directory check on until migration completes.",
                  "Block requests that have been flagged until review ends.",
                  "Hold the lock that must be released before the commit lands.",
                  "Keep the gate open until Dana confirms the copy is done.",
                  "Stop the delete until the copy has finished.",
                  "Hold the release until the security review is signed off.",
                  "Keep the flag on before the migration has run.",
                  "Remove (or rename) the stale file.",
                  "Block requests that may not have been reviewed until Dana.",
                  "Keep the gate (see policy 2 (current) is binding) before it.",
                  "Keep the file that is marked stale which has expired until 5.",
                  "Block requests that can also be processed before logs.",
                  "Keep the lock that has already been taken until the write.",
                  "Block requests that must eventually be signed before merge.",
                  "**Verify**: confirm the hypothesis before fixing.",
                  "**Verify** — check against codebase reality.",
                  "[ ] Verify the production database checksum before deploy.",
                  "- [ ] Keep the gate closed until the owner confirms.",
                  "[x] Remove the stale file.",
                  "Keep the branch that doesn't build until CI is green.",
                  "Stop the run that hasn’t finished before the deploy.",
                  "Keep files that may or may not be needed until the audit.",
                  "Block jobs that will and should be retried before the cut.",
                  "Keep the flag that can only be set until the release.",
                  "Please verify the checksum before deployment.",
                  "• Verify the checksum before deployment.",
                  "Remove duplicates.",
                  "`Verify` the checksum before deploy.",
                  "+ Verify the checksum before deployment.",
                  "- Verify the checksum before deployment.",
                  "— Verify the checksum before deployment.",
                  "Verify—before deploying—that the checksum matches."):
        assert RECOMMENDATION.match(_hold), _hold
    for _bare in ("Use the staging host for the smoke test.",
                  "Keep the file short.", "Stop the service.",
                  "Add a retry to the fetch call.",
                  "Block storage is cheaper before you hit the tier limit.",
                  "Keep alive probes are cheap before the load test.",
                  "Hold times were long before the fix landed.",
                  "Block writes should be batched before the flush.",
                  "Block's latency spikes before demand peaks.",
                  "Stop-the-world pauses happen before a collection.",
                  "Block storage, which the team sized, is cheap before peak.",
                  "Hold times, which nobody tracked, were long before the fix.",
                  "Block storage when demand is low is cheap before the limit.",
                  "Block storage,  which the team sized, is cheap before peak.",
                  "Block storage,\twhich the team sized, is cheap before peak.",
                  "Block storage ,which the team sized, is cheap before peak.",
                  "Block storage that is local is cheaper before peak demand.",
                  "Drop-down menus are easier to scan.",
                  "Remove-only mode is faster than a full sync.",
                  "Check-in times are longer before the holiday weekend.",
                  "Drop.payload is large.",
                  "Verify() is called.",
                  "Check‑in times are longer before the holiday weekend.",
                  "Drop‑down menus are easier to scan.",
                  "Stop‑the‑world pauses happen before a collection.",
                  "Block storage shall cost less before the tier limit.",
                  "Block storage isn't cheap before the tier limit.",
                  "Hold times weren’t long before the fix landed.",
                  "Keep.alive stays on until the socket closes.",
                  "Block(name) is called before the gate opens.",
                  "Verify:", "Remove:", "Confirm:", "Check:",
                  "--verify is enabled by default.",
                  "`--verify` is enabled by default.",
                  "--check-only runs without writing.",
                  "Block storage—is cheap—before peak demand."):
        assert not RECOMMENDATION.match(_bare), _bare
    _t0 = time.perf_counter()
    for _bomb in ("Keep " + "the (a b) c " * 200 + "done.",
                  "Keep " + "the (a (b) c) d " * 200 + "done.",
                  "Keep " + "the (a (b c d " * 100 + "done.",
                  "Keep " + "the a that b which c who d " * 80 + "done.",
                  "Block items that may " + "only be " * 20 + "done.",
                  "Block items that may " + "really be " * 20 + "done.",
                  "Block items that may " + "or may " * 20 + "be done.",
                  "Block items that may " + "and may " * 20 + "be done."):
        RECOMMENDATION.match(_bomb)
    assert time.perf_counter() - _t0 < 1, \
        "RECOMMENDATION backtracks on repeated parentheses, clauses or adverbs"

    _bur = {"present": False, "words": 4000, "doc": 4000, "buried": 9}
    assert summary_verdict(_bur)[0] == "buried", summary_verdict(_bur)
    assert "BURIED" in summary_verdict(_bur)[1]

    _fm_body = ("---\nname: t\ndescription: what this does\n---\n\n"
                "Prose that is the instruction body and has no heading over "
                "it, which is the contract.\n\n## Run it\n\n"
                + ("w " * 30 + "\n\n") * 40)
    def _sum_of(_txt):
        _pp, _hh, _tt, _ = mask(_txt, "t.md")
        return opening_summary(_hh, _pp, word_count(_txt), _txt)
    _decl = _sum_of(_fm_body)
    assert _decl.get("declared") and summary_verdict(_decl)[0] == "declared", \
        (_decl, summary_verdict(_decl))
    _dsaid = summary_verdict(_decl)[1]
    assert "it should go" not in _dsaid and "what was examined" not in _dsaid, \
        _dsaid
    assert not summary_owed(_decl), _decl
    _no_desc = _sum_of(_fm_body.replace("description: what this does",
                                        "date: 2026-08-22"))
    assert not _no_desc.get("declared") and summary_owed(_no_desc), _no_desc
    assert summary_verdict(_no_desc)[0] in ("unheaded", "missing"), \
        summary_verdict(_no_desc)
    _bare = _sum_of(_fm_body.split("---\n\n", 1)[1])
    assert not _bare.get("declared") and summary_owed(_bare), _bare
    assert not declares_abstract("Some prose.\n\ndescription: not frontmatter")
    assert not declares_abstract("Title\n---\ndescription: x\n")
    _has = _sum_of(_fm_body.replace("## Run it", "## Summary\n\n" + "w " * 60
                                    + "\n\n## Run it"))
    assert summary_verdict(_has)[0] == "ok", summary_verdict(_has)

    _unh = summary_verdict({"present": False, "words": 900, "doc": 900,
                            "lede": 235})
    assert _unh[0] == "unheaded" and "none of the three" in _unh[1], _unh
    _mis = summary_verdict({"present": False, "words": 3337, "doc": 3337})
    assert _mis[0] == "missing" and "rules or reference" in _mis[1] \
        and "what this file is for" in _mis[1].lower(), _mis

    _lede_words = ("This document records how the gateway resolves a request, "
                   "which services it consults in order, and what each failure "
                   "mode looks like from the caller's side so an operator can "
                   "tell them apart without reading the code. It is scope and "
                   "not summary: every stage below is described where it runs, "
                   "and nothing here restates a result.")
    _hd_body = "".join(f"\n## Section {i}\n\n"
                       + "".join("The resolver consults the stage and records "
                                 "the outcome with its duration so a later "
                                 "reader can reconstruct the branch taken.\n"
                                 for _ in range(8))
                       for i in range(1, 7))

    def _sum_of_doc(_t):
        _p, _h, _tb, _q = mask(_t)
        return summary_verdict(opening_summary(_h, _p, word_count(_t), _t))

    _bare_v = _sum_of_doc(f"# Gateway notes\n\n{_lede_words}\n{_hd_body}")
    _headed_v = _sum_of_doc(
        f"# Gateway notes\n\n## Scope\n\n{_lede_words}\n{_hd_body}")
    assert _bare_v[0] == "unheaded", _bare_v
    assert _headed_v[0] != "missing", _headed_v
    assert _headed_v[0] == "headed" and "'Scope' at line 3" in _headed_v[1] \
        and "none of the three" in _headed_v[1], _headed_v
    _named_v = _sum_of_doc(
        f"# Gateway notes\n\n## Summary\n\n{_lede_words}\n{_hd_body}")
    assert _named_v[0] == "ok" and "'Summary' at line 3" in _named_v[1], _named_v
    def _state_of_doc(_t):
        _p, _h, _tb, _q = mask(_t)
        return opening_summary(_h, _p, word_count(_t), _t)
    _marked_doc = f"# Gateway notes\n\n<!-- kv:summary -->\n{_lede_words}\n{_hd_body}"
    _mk = _state_of_doc(_marked_doc)
    _mk_v = summary_verdict(_mk)
    assert _mk.get("marked") and _mk_v[0] == "marked" \
        and "kv:summary" in _mk_v[1], (_mk, _mk_v)
    assert not summary_owed(_mk), _mk
    _mk_p, _mk_h, _mk_t, _ = mask(_marked_doc)
    assert not any(j["specialist"] == "summary" for j in build_jobs(
        chunk(_mk_p, _mk_h, tables=_mk_t), [], False, None,
        summary=_mk)), "a kv:summary lede was dispatched to `summary`"
    _unm = _state_of_doc(f"# Gateway notes\n\n{_lede_words}\n{_hd_body}")
    assert not _unm.get("marked") and summary_verdict(_unm)[0] == "unheaded" \
        and summary_owed(_unm), _unm
    _late_doc = _marked_doc.replace("<!-- kv:summary -->\n", "").replace(
        "## Section 2\n\n", "## Section 2\n\n<!-- kv:summary -->\n")
    _late_at = _late_doc.split("\n").index("<!-- kv:summary -->") + 1
    try:
        mask(_late_doc)
        raise AssertionError("a kv:summary below the first section was accepted")
    except UsageError as e:
        assert f"line {_late_at} writes 'kv:summary'" in str(e), e
    assert not _state_of_doc(_late_doc.replace(
        "<!-- kv:summary -->", "`<!-- kv:summary -->`")).get("marked")
    _ser = _sum_of_doc(f"# Gateway notes\n\n## Section 0\n\n{_lede_words}\n"
                       f"{_hd_body}")
    assert _ser[0] == "missing", _ser
    _short_lede = ("A short note before the sections begin, twenty words or "
                   "so, well under the forty a lede has to clear to be "
                   "reported at all here.")
    _stacked = _sum_of_doc(f"# Gateway notes\n\n{_short_lede}\n\n## Scope\n\n"
                           f"{_lede_words}\n{_hd_body}")
    assert len(_short_lede.split()) < SUMMARY_MIN_WORDS, "fixture lede grew"
    assert _stacked[0] == "missing", _stacked
    for _series in ("Section 1", "1. The kernel", "S-paper-1 — evaluators",
                    "I17 — delete the fallback chain", "Round 3"):
        assert _summary._series_member(_series), _series
    for _open in ("Introduction", "Preamble", "About this document", "Goal",
                  "What this is", "Scope and format", "What was tested",
                  "Where this stands", "What I did this week",
                  "Migrating to v2 storage"):
        assert not _summary._series_member(_open), _open
    _hd_state = {"present": False, "words": 1713, "doc": 1713,
                 "headed": 57, "headed_title": "Scope", "headed_at": 3}
    assert summary_owed(_hd_state), _hd_state
    assert summary_verdict(_hd_state, refused="it repeats the body")[0] \
        == "refused", "headed swallowed REFUSED"

    _chk = "# Release checklist\n\n" + "".join(
        f"- [ ] step {i}: check the reading on the host and record the exit "
        f"code beside it in the ledger row\n" for i in range(1, 71))
    _cp, _ch, _ct, _cq = mask(_chk)
    assert opening_summary(_ch, _cp, word_count(_chk), _chk) is not None, \
        "the checklist fixture stopped reaching the rule"
    SWITCHED_OFF["summary"] = "genre-checklist"
    try:
        assert opening_summary(_ch, _cp, word_count(_chk), _chk) is None, \
            "a genre that owes no summary was still asked for one"
        assert "off for genre-checklist" in summary_blocked(None), \
            summary_blocked(None)
    finally:
        SWITCHED_OFF.pop("summary", None)
    assert opening_summary(_ch, _cp, word_count(_chk), _chk) is not None

    def _jargon_hits(s):
        return [k for _, k, _ in find_shapes([s]) if k == "jargon"]
    for _ok in ("The gate fails open when the token is malformed.",
                "It fails OPEN, so a bad frame is admitted.",
                "These are the load-bearing rules.",
                "That comment is load-bearing and must not move."):
        assert not _jargon_hits(_ok), (_ok, find_shapes([_ok]))
    for _bad in ("This module is a code smell.",
                 "Logging is one of the cross-cutting concerns here.",
                 "A TOCTOU window opens between the two calls."):
        assert _jargon_hits(_bad), _bad

    def _unex(_txt):
        _p2, _h2, _t2, _q2 = mask(_txt, "t.md")
        return [t for _, k, t in find_shapes(_p2, _t2, _h2, _q2)
                if k == "unexplained reference"]
    _ref = "# Doc\n\nThe gate rejects it, see decision 154.\n\n"
    assert not _unex(_ref + "## Decisions\n\n- **154.** No backup, no run.\n")
    assert not _unex(_ref + "### Decision 154 - the backup rule\n\nNo run.\n")
    assert _unex(_ref + "## Notes\n\nNothing here defines anything.\n")
    assert _unex(_ref + "## Notes\n\nWe shipped 154 of them that week.\n")

    _banner = ("codex: starting session\n"
               "codex: reading the prompt\n"
               "\n"
               "codex: you are out of quota until Aug 24\n")
    _said = _why_it_died(_banner)
    assert _said.endswith("out of quota until Aug 24"), _said
    assert "starting session" in _said and "\n" not in _said, _said
    assert _why_it_died("") == "" and _why_it_died("   \n\n") == ""

    def _pr(_t):
        return [l.strip() for l in mask(_t)[0]]
    _wrapnest = ("Cite ``[DOC-R085] moved and are named in\n"
                 "no `## What changed` entry ...`` - done.\n")
    assert not any("What changed" in l for l in _pr(_wrapnest)), _pr(_wrapnest)
    assert not find_shapes(mask(_wrapnest)[0]), find_shapes(mask(_wrapnest)[0])
    for _c in ("Cite ``a `## What changed` b`` done.\n",
               "Cite ``[DOC-R085] moved\nand ## What changed here`` done.\n",
               "Cite `## What changed` done.\n"):
        assert not any("What changed" in l for l in _pr(_c)), _pr(_c)
    assert "`" not in "".join(_pr(_wrapnest)), _pr(_wrapnest)
    assert _pr("the `weak\ncrypto` finding\n")[:2] == ["the", "finding"]
    assert [h[2] for h in mask("## What changed\n\nnothing\n")[1]] \
        == ["What changed"]
    assert mask_code_spans("plain text", 0) == ("plain text", 0)
    assert mask_code_spans("``open run", 0)[1] == 2, mask_code_spans("``open", 0)
    assert mask_code_spans("a `one` b", 0)[1] == 0

    def _bid(_s):
        return [t for _, k, t in find_shapes([_s]) if k == "bare internal id"]
    _classify = ["which both round-3 reviewers found",
                 "arm both round-5 engines asked",
                 "MET). Both round-7 reviewers then",
                 "round-9 reviewers refused it",
                 'slug". Both round-10 reviewers inverted',
                 "which both round-7 reviewers refused",
                 "and both round-6 engines refused",
                 "disk. Both round-6 reviewers found,"]
    for _s in _classify:
        assert not _bid(_s), _s
    for _s in ("so the round-5 objection that",
               "directory, which is the round-8 failure",
               "That was the round-8 failure."):
        assert _bid(_s), _s
    for _s in ("The gate rejects round-3.", "See (L5) for the detail.",
               "See (L1150) for the detail.", "round-3 showed nothing new."):
        assert _bid(_s), _s
    assert _bid("(K1-K4) findings were dropped without a reason."), \
        "a parenthesised id is an aside, never a modifier"

    _inc_txt = ("# Doc\n\nline two\n\nSee (Owns / Must NOT) in the other "
                "file.\n\nfiller\n\nit MUST NOT modify anything.\n")
    _inc2 = [i for i in inconsistencies(_inc_txt) if i["kind"] == "term"
             and set(i["forms"]) == {"MUST NOT", "Must NOT"}]
    assert _inc2 and _inc2[0]["lines"] == {"MUST NOT": 9, "Must NOT": 5}, \
        _inc2
    with tempfile.TemporaryDirectory() as _itd:
        _if = Path(_itd) / "i.md"
        _if.write_text(_inc_txt + "\n".join(
            " ".join(f"q{i}w{j}" for j in range(12)) for i in range(30)) + "\n")
        _ia = build_parser().parse_args(["plan", str(_if)])
        _ib = io.StringIO()
        with contextlib.redirect_stdout(_ib):
            _ia.fn(_ia)
        _iout = [l for l in _ib.getvalue().splitlines()
                 if l.strip().startswith("term: ")]
    assert _iout and "(L9)" in _iout[0] and "(L5)" in _iout[0], _iout

    _burw = dict(_bur, above=4, above_words=34)
    _bsaid = summary_verdict(_burw)[1]
    assert "4 lines" in _bsaid and "34 words" in _bsaid \
        and f"{_summary.BURIED_MIN_WORDS}-word floor" in _bsaid, _bsaid
    assert "lines of body above it" in summary_verdict(_bur)[1] \
        and "word" not in summary_verdict(_bur)[1], summary_verdict(_bur)
    _b1 = summary_verdict(dict(_bur, above=1, above_words=1))[1]
    assert "1 line of body" in _b1 and "1 word," in _b1, _b1

    def _lede(txt):
        _pr = ["# T", ""] + txt.strip().split("\n") + [
            "", "## Summary", "", "w " * 40, "", "## Body"] + ["w " * 30] * 40
        _hd = [(i, len(l) - len(l.lstrip("#")), l.lstrip("# ").strip())
               for i, l in enumerate(_pr) if l.startswith("#")]
        return opening_summary(_hd, _pr, sum(len(l.split()) for l in _pr))
    _four = ("This file is the plan.\nThe reasoning behind every action is in "
             "`deep.md`.\nIt was written after the pilot closed and the "
             "numbers were collected.\nRead the summary first, then the wave "
             "you own.")
    _over = _lede(_four)
    assert _over.get("buried") and _over["above"] == 4 \
        and _over["above_words"] >= _summary.BURIED_MIN_WORDS, _over
    _under = _lede("This file is the plan.\nThe reasoning is in `deep.md`.\n"
                   "It was written after the pilot closed.\nRead the summary "
                   "first, then your wave.")
    assert not _under.get("buried") and _under["present"], _under
    assert len(_four.split("\n")) == 4, "the control moved the line count too"
    assert summary_verdict(None) is None
    for _fn in (cmd_plan, cmd_verify):
        assert "summary_verdict(" in inspect.getsource(_fn), _fn.__name__
        assert "BURIED" not in inspect.getsource(_fn), \
            f"{_fn.__name__} prints the verdict itself again"
    assert summary_verdict({"present": False, "words": 4000,
                            "doc": 4000})[0] == "missing"
    assert summary_verdict({"present": False, "words": 4000, "doc": 4000,
                            "lede": 200})[0] == "unheaded"
    _title = [(0, 1, "T")]
    _p = ["# T"] + ["w " * 30] * 8 + ["## Body"] + ["w " * 30] * 200
    _hs = [(0, 1, "T"), (9, 2, "Body")]
    assert _unheaded_lede(_hs, _p, 4000) == 240, _unheaded_lede(_hs, _p, 4000)
    assert _unheaded_lede([(0, 1, "T"), (1, 2, "Body")], ["# T", "## Body"],
                          4000) == 0
    assert _unheaded_lede(_hs, ["# T", "hi", "## Body"], 4000) == 0
    _huge = ["# T"] + ["w " * 30] * 400 + ["## Body"]
    assert _unheaded_lede([(0, 1, "T"), (401, 2, "Body")], _huge, 4000) == 0
    _over = ["# T"] + ["w " * 30] * 20 + ["## Body"] + ["w " * 30] * 400
    assert _unheaded_lede([(0, 1, "T"), (21, 2, "Body")], _over, 12000) == 600
    assert _unheaded_lede([(0, 1, "T"), (401, 2, "Body")], _huge, 12000) == 0
    assert summary_owed({"present": False, "words": 4000, "doc": 4000,
                         "lede": 200})
    assert summary_owed({"present": False, "words": 4000, "doc": 4000})
    assert summary_verdict({"present": True, "line": 3, "title": "Summary",
                            "words": 1, "doc": 4000})[0] == "thin"
    _big = {"present": True, "line": 3, "title": "Summary",
            "words": summary_cap(4000) + 50, "doc": 4000}
    assert summary_verdict(_big)[0] == "over"
    assert summary_verdict(_big, written=10)[0] == "inherited"
    assert summary_verdict(_big, written=summary_cap(4000) + 40)[0] == "over"
    assert summary_verdict({"present": True, "line": 3, "title": "Summary",
                            "words": SUMMARY_MIN_WORDS + 1,
                            "doc": 4000})[0] == "ok"

    class _A:
        only = project = None
    _off = _A(); _off.only = "noise,quotable,prose"; _off.project = "/p/.killverbosity.json"
    _said = unowned_note("missing", _off)
    assert "'summary' specialist is OFF" in _said, _said
    assert "/p/.killverbosity.json" in _said, _said
    assert "no run will write this" in _said, _said
    _on = _A(); _on.only = "noise,summary"; _on.project = "/p/.killverbosity.json"
    assert unowned_note("missing", _on) == "", unowned_note("missing", _on)
    assert unowned_note("missing", _A()) == ""
    _b = _A(); _b.only = "noise,summary"; _b.project = "/p/.killverbosity.json"
    assert "'structure' specialist is OFF" in unowned_note("buried", _b)
    assert unowned_note("buried", _off) != ""
    _keys = set(re.findall(r'return \("(\w+)"', inspect.getsource(summary_verdict)))
    assert _keys - {"ok"} <= set(SUMMARY_VERDICT_OWNER), \
        f"summary verdicts with no owner: {_keys - {'ok'} - set(SUMMARY_VERDICT_OWNER)}"

    _g = {"genre": "prose", "genre_mix": {"prose": 141, "reference": 24, "log": 13}}
    _ev = genre_evidence(_g)
    assert "prose 141 of 178 body lines" in _ev, _ev
    assert "reference 24" in _ev and "log 13" in _ev, _ev
    assert genre_evidence({"genre": "prose"}) == ""
    assert genre_evidence({"genre": "prose", "genre_mix": {}}) == ""
    _plansrc = inspect.getsource(cmd_plan)
    assert 'if g["genre"] != "prose":' not in _plansrc, \
        "the contest invitation is gated on the genre again"
    assert "If that is wrong, the rules are wrong too" in _plansrc

    with tempfile.TemporaryDirectory() as _td:
        _wf = Path(_td) / "w.md"
        _wf.write_text("# Wiring\n\n" + "\n".join(
            " ".join(f"word{i}x{j}" for j in range(28)) for i in range(60)) + "\n")
        _wa = build_parser().parse_args(["plan", str(_wf)])
        _wa.only, _wa.project = "noise,quotable,prose", "/p/.killverbosity.json"
        _wout = io.StringIO()
        with contextlib.redirect_stdout(_wout), \
                contextlib.redirect_stderr(io.StringIO()):
            _wa.fn(_wa)
        _wtext = _wout.getvalue()
    _whead = next(l for l in _wtext.splitlines() if "read as" in l)
    assert "body lines" in _whead, _whead
    _wsum = next((l for l in _wtext.splitlines() if l.startswith("opening summary:")), "")
    assert "specialist is OFF" in _wsum, _wsum
    assert "no run will write this" in _wsum, _wsum
    _runsrc = re.sub(r'"\s*\n\s*[fr]?"', "", inspect.getsource(cmd_run))
    assert "do not write a second summary" in _runsrc, \
        "the summary specialist is told to add one over the one that is there"
    assert "Every other edit is dropped" in _runsrc, \
        "the unbury exception no longer narrows structure to the one operation"
    _ask = "The summary is buried and it is yours"
    assert _runsrc.count(_ask) == 1, \
        f"the buried-summary ask appears {_runsrc.count(_ask)} times in cmd_run"
    assert _runsrc.index(_ask) > _runsrc.index("job_context = context"), \
        "the buried-summary ask is in the shared context, so every job reports it"
    _bl = ("This service keeps session rows for twelve months and then moves "
           "them to the archival tier where they cost far less to hold. ")
    _bbody = "\n\n".join(f"## Section {_i}\n\n"
                         + ("Filler prose here that says very little indeed. " * 14)
                         for _i in range(1, 7))
    _bdoc = (f"# Retention\n\n{_bl * 6}\n\n{_bl * 5}\n\n## Summary\n\n"
             f"{_bl * 2}\n\n{_bbody}\n")
    _bp, _bh, _bt, _bq = mask(_bdoc, "d.md")
    _bs = opening_summary(_bh, _bp, word_count(_bdoc))
    assert _bs.get("buried") and not _bs["present"], \
        f"the fixture no longer buries its summary, so it asks nothing: {_bs}"
    _br = _runfix(_quiet, doc=_bdoc)
    try:
        _n_struct = sum(1 for _l in _br.err.splitlines()
                        if "structure" in _l and "proposed" in _l)
        assert _n_struct >= 3, \
            (f"the fixture built {_n_struct} structure jobs; with fewer than "
             "three the `unit` half of the rule is not being tested")
        _asked = [_pr for _pr in _br.prompts
                  if "The summary is buried and it is yours" in _pr]
        assert len(_asked) == 1, \
            (f"the buried-summary ask went to {len(_asked)} of "
             f"{len(_br.prompts)} jobs; it belongs to the one document-scope "
             "structure job and nothing else")
    finally:
        shutil.rmtree(_br.dir, ignore_errors=True)

    def _bs(lines, heads, ln, thru):
        return block_span(lines, heads, ln, thru, len(lines))

    _bt = [(0, 1, "T")]
    _bplain = ["# T", "", "para one", "", "para two", ""]
    assert _bs(_bplain, _bt, 3, 3) == ((3, 3), None), _bs(_bplain, _bt, 3, 3)
    _span, _why = _bs(_bplain, _bt, 2, 2)
    assert _span is None and "text on it" in _why, \
        f"the edge rule is gone, so a range may take half of any block shape: {_why}"
    _brun = ["# T", "", "line a", "line b", "", ""]
    assert _bs(_brun, _bt, 4, 4)[0] is None \
        and _bs(_brun, _bt, 3, 3)[0] is None, \
        "a range with text across either edge is being taken as a whole block"
    _bfence = ["# T", "", "```", "code a", "", "code b", "```", ""]
    assert _bs(_bfence, _bt, 3, 7) == ((3, 7), None), _bs(_bfence, _bt, 3, 7)
    _span, _why = _bs(_bfence, _bt, 3, 4)
    assert _span is None and "whole fence" in _why, \
        f"half a fenced block is movable again — the closer becomes an opener: {_why}"
    _blist = ["# T", "", "- one", "", "- two", ""]
    assert _bs(_blist, _bt, 3, 5) == ((3, 5), None), _bs(_blist, _bt, 3, 5)
    _span, _why = _bs(_blist, _bt, 5, 5)
    assert _span is None and "whole list" in _why, \
        f"one item of a blank-separated list is movable again: {_why}"
    _bhead = ["# T", "", "para", "", "## B", "", "para2", ""]
    _bhs = [(0, 1, "T"), (4, 2, "B")]
    assert _bs(_bhead, _bhs, 3, 3) == ((3, 3), None), _bs(_bhead, _bhs, 3, 3)
    _span, _why = _bs(_bhead, _bhs, 3, 5)
    assert _span is None and "move the section instead" in _why, \
        f"a heading inside a block no longer sends the sender to `move`: {_why}"
    _msrc = inspect.getsource(merge)
    assert "anchor + 1 if op != \"move\"" in _msrc, \
        "a block no longer lands under its heading, so it arrives above it"
    assert "bottom = body_end(lines) + 1" in _msrc, \
        "the bottom destination is the end of the file, so a block sent " \
        "there lands under the footnote definitions"

    _pl = {"global_context": {"words": 1000},
           "chunks": [{"shapes": [{"kind": "jargon"}, {"kind": "jargon"},
                                  {"kind": "hedge"}],
                       "long_sentences": [1, 2, 3, 4], "em_dash_paragraphs": [9],
                       "wall_paragraphs": [{"line": 9}]}]}
    _cen = shape_census(_pl)
    assert "long 4" in _cen and "em-dash 1" in _cen and "jargon 2" in _cen, _cen
    assert "3 fault-shapes in 1000 words (3.0 per 1000 words over the 2 counted kinds, 6 candidates not counted)" in _cen, _cen
    _syn = shape_census({"global_context": {"words": 1000}, "chunks": [
        {"shapes": [{"kind": "jargon"}, {"kind": "mixed list styles"},
                    {"kind": "repeated list item"}],
         "long_sentences": [], "em_dash_paragraphs": [], "wall_paragraphs": []}]})
    assert "1 fault-shape in 1000 words (1.0 per 1000 words over the 1 counted kind" in _syn, _syn
    assert ("The 1 mixed list styles and 1 repeated list item are left out of "
            "that count") in _syn, _syn
    assert "1 fault-shape in 1000 words" in dispatch_density(
        [(1, "jargon", "x"), (2, "mixed list styles", "y"),
         (3, "repeated list item", "z")], 1000, 1, "codex")
    def _census(long_n):
        return shape_census({"global_context": {"words": 1000}, "chunks": [
            {"shapes": [{"kind": "jargon"}], "long_sentences": ["x"] * long_n,
             "em_dash_paragraphs": [], "wall_paragraphs": []}]})
    _lbody = "\n\n".join(f"## Section {i}\n\n" + ("Filler prose here. " * 30)
                         for i in range(1, 9))
    _llede = "This service keeps session rows for twelve months. " * 12
    for _name, _d, _want in (("no-H1", "## Setup\n\n" + _llede + "\n\n" + _lbody, 0),
                             ("H1", "# R\n\n" + _llede + "\n\n" + _lbody, 1)):
        _lp, _lh, _lt, _lq = mask(_d, "d.md")
        _got = _unheaded_lede(_lh, _lp, word_count(_d))
        assert bool(_got) == bool(_want), (_name, _got)
        assert summary_owed(opening_summary(_lh, _lp, word_count(_d))), _name
    assert 'summary.get("lede")' in inspect.getsource(cmd_run), \
        "cmd_run tells the specialists an unheaded lede is no summary"
    _ctx = re.sub(r'"\s*\n\s*"', "", inspect.getsource(cmd_run))
    assert "Say in your report that the opening is unheaded" in _ctx
    assert re.search(r'SPECIALISTS\[job\["specialist"\]\]\[0\] == "document":'
                     r'\s*job_context \+= \(" Say in your report', _ctx), \
        "the unheaded ask reaches specialists that cannot act on it"
    _same = "The opening is unheaded and a human has to decide what it is."
    _notes = [("noise", _same),
              ("quotable", _same.upper()),
              ("structure", "Both copies are load-bearing: line 547 and 911."),
              ("prose", _same + "  ")]
    _g = group_notes(_notes)
    assert [len(m) for m in _g] == [1, 3], [len(m) for m in _g]
    assert _g[0][0][0] == "structure", "the one real note is not printed first"
    assert len(group_notes([("a", "line 40 has two claims"),
                            ("a", "line 900 has two claims")])) == 2, \
        "two notes about different lines were collapsed into one"
    _open = "The opening is unheaded; a human must decide whether it "
    assert len(group_notes([("noise", _open + "needs a heading."),
                            ("prose", _open + "is already the summary.")])) == 2, \
        "opposite advice was collapsed behind a shared opening"
    assert len(group_notes([("noise", "Rename `Foo` to `foo`."),
                            ("prose", "Rename `foo` to `Foo`.")])) == 2, \
        "opposite renames were collapsed by lowercasing"
    assert len(group_notes([("noise", "the retry budget is `Rt`."),
                            ("prose", "The retry budget is `Rt`.")])) == 1, \
        "one sentence in two sentence-cases stopped collapsing"

    assert "candidate is left out" in _census(1), _census(1)
    assert "candidates are left out" in _census(3), _census(3)
    assert "left out" not in _census(0), _census(0)
    _empty = shape_census({"global_context": {"words": 0}, "chunks": []})
    assert "none" in _empty, _empty
    assert "hide_length" not in globals() \
        and "hide_length" not in inspect.getsource(cmd_plan), \
        "the listing can be shortened again without shortening the work"
    _d = dispatch_density([(1, "jargon", "x"), (2, "long sentence", "y"),
                           (3, "em-dash pressure", "z")], 2000, 7, "codex")
    assert "1 fault-shape in 2000 words" in _d, _d
    assert "(0.5 per 1000)" in _d and "7 jobs against codex" in _d, _d
    assert "return 2" not in inspect.getsource(dispatch_density)

    def _units(t):
        return [i["units"] for i in inconsistencies(t) if i["kind"] == "number"]
    assert _units("It is 30s here.\nIt is 30 min there.\n") == [["min", "s"]]
    assert _units("It is 30s here.\nIt is 30 hours there.\n") == [["h", "s"]]
    assert _units("It takes 500ms.\nIt takes 500 s.\n") == [["ms", "s"]]
    assert _units("The dump is 10GB.\nThe dump is 10 MB.\n") == [["GB", "MB"]]
    assert not _units("Takes 3s warm.\nWindow is 3 sec.\nMode is 3x faster.\n")
    assert not _units("Recall was 73%.\nThe corpus holds 73k rows.\n")
    assert not _units("The timeout is 60 seconds.\nThe 60-second timeout.\n")

    _run_src = inspect.getsource(cmd_run)
    assert "owner_report(owned, _own, fold_spans)" in _run_src, \
        "ownership losses are back in the refusal list"
    _own_rows = [(2, "prose: x", "already changed by structure"),
                 (2, "prose: y", "already changed by structure"),
                 (3, "noise: z", "already changed by structure"),
                 (1, "prose: w", "already changed by quotable")]
    _orp = owner_report(_own_rows, "already changed by ", [])
    assert "went to the line's owner (4)" in _orp[0] and \
        "3 to structure, 1 to quotable" in _orp[0], \
        f"the ownership header lost its counts or its order: {_orp[0]!r}"
    assert len(_orp) == 3, "an owner has no line behind its count"
    assert _orp[1].split() == ["to", "structure", "L2", "L3"], \
        f"ownership lines are not deduped, sorted and labelled: {_orp[1]!r}"
    assert _orp[2].split() == ["to", "quotable", "L1"], _orp[2]
    _folded = owner_report(_own_rows, "already changed by ",
                           [(9, 9), (39, 40), (41, 41)])
    assert "L40" in _folded[1] and "L42" in _folded[1] \
        and "L2" not in _folded[1] and "L3" not in _folded[1], \
        f"ownership line numbers skip the fold map: {_folded[1]!r}"
    assert "{len(gates)} refused by the gates" in _run_src, \
        "the header counts ownership hand-offs as gate refusals again"
    assert "CROSSCHECK_TIMEOUT" in inspect.getsource(cmd_crosscheck), \
        "crosscheck is back on someone else's timeout"
    assert JOB_TIMEOUT < 600 and CROSSCHECK_TIMEOUT > JOB_TIMEOUT, \
        "a per-call timeout at or above the harness ceiling kills the run"
    _bid = build_id()
    assert _bid != "unknown", "the run header cannot name its own build"
    _bh, _bl = _bid.split()
    assert len(_bh) == 8 and _bl.endswith("L")
    assert int(_bl[:-1]) == len(Path(__file__).read_bytes().splitlines()), \
        f"build_id says {_bl}, wc -l disagrees"
    assert "spawn.run_tree(" in inspect.getsource(cmd_crosscheck), \
        "crosscheck spawns its reviewer without the process-tree kill"
    assert "spawn.run_tree(" in inspect.getsource(_call_one), \
        "a specialist call spawns without the process-tree kill"

    _ssrc = ["# Review call", "", "## Attendees", "", "Four joined.", "",
             "## What we decided", "", "The retry ships in v3.", ""]
    _sheads = [(0, 1, "Review call"), (2, 2, "Attendees"),
               (6, 2, "What we decided")]
    _sout, _, _sno, *_ = merge(_ssrc, [
        {"specialist": "structure", "edits": [
            {"line": 7, "old": "## What we decided",
             "new": "## Summary of decisions"}]},
        {"specialist": "summary", "edits": [
            {"op": "insert", "line": 2, "new": "## Summary\n\nIt ships.\n"}]},
    ], set(range(1, len(_ssrc) + 1)), headings=_sheads)
    assert sum(1 for l in _sout if "ummary" in l and l.startswith("#")) == 1, _sout
    assert _sno and "only `summary` reads the prose" in _sno[0][2], _sno
    assert "It ships." in _sout, _sout
    _csrc = ["# Review call", "", "## Summary of decisions", "", "It ships.", ""]
    _cout, _, _cno, *_ = merge(_csrc, [
        {"specialist": "summary", "edits": [
            {"op": "insert", "line": 2, "new": "## Summary\n\nAgain.\n"}]},
    ], set(range(1, len(_csrc) + 1)),
        headings=[(0, 1, "Review call"), (2, 2, "Summary of decisions")])
    assert _cno and "already opens the file" in _cno[0][2], _cno
    _dsrc = ["# Review call", "", "## Scope", "", "The importer.", "",
             "## Summary of decisions", "", "It ships.", ""]
    _dout, _, _dno, *_ = merge(_dsrc, [
        {"specialist": "summary", "edits": [
            {"op": "insert", "line": 2, "new": "## Summary\n\nAgain.\n"}]},
    ], set(range(1, len(_dsrc) + 1)),
        headings=[(0, 1, "Review call"), (2, 2, "Scope"),
                  (6, 2, "Summary of decisions")])
    assert _dno and "two places to start" in _dno[0][2], _dno

    _ph = EXISTENCE["purpose hedge"]
    for _s in ("The layer aims to reduce personal data.",
               "It should help with the audit finding.",
               "We can also look to extend it later.",
               "This work seeks to address the gap.",
               "The change is intended to make the log safer."):
        assert _ph.search(_s), _s
    for _s in ("The client tries to reconnect three times.",
               "The job is expected to take twenty minutes.",
               "Look to the runbook for the rollback steps.",
               "The parser attempts to read the header first."):
        assert not _ph.search(_s), _s

    _hsrc = ["# Runbook", "", "## Scope", "", "Covers the importer.", "",
             "## Key Principles", "", "Verify before documenting.", ""]
    _hheads = [(0, 1, "Runbook"), (2, 2, "Scope"), (6, 2, "Key Principles")]
    _hout, _, _hno, *_ = merge(_hsrc, [
        {"specialist": "structure", "edits": [
            {"line": 7, "old": "## Key Principles", "new": "## Summary"}]},
        {"specialist": "summary", "edits": [
            {"op": "insert", "line": 2, "new": "## Summary\n\nIt verifies.\n"}]},
    ], set(range(1, len(_hsrc) + 1)), headings=_hheads)
    assert sum(1 for l in _hout if l.strip() == "## Summary") == 1, _hout
    assert _hno and "only `summary` reads the prose" in _hno[0][2], _hno
    _ksrc = ["# Runbook", "", "## Scope", "", "Covers the importer.", "",
             "## Key Principles", "", "Verify before documenting.", ""]
    _kout, _, _kno, *_ = merge(_ksrc, [
        {"specialist": "structure", "edits": [
            {"op": "insert", "line": 6, "new": "## Scope\n\nAlso this.\n"}]},
    ], set(range(1, len(_ksrc) + 1)),
        headings=[(0, 1, "Runbook"), (2, 2, "Scope"), (6, 2, "Key Principles")])
    assert _kno and "share one link target" in _kno[0][2], _kno

    _dr = {"specialist": "structure", "edits": [
        {"line": 5, "old": "a", "new": "", "group": "dup1"},
        {"line": 40, "old": "b", "new": "c", "group": "dup1"},
        {"line": 41, "old": "d", "new": "e"}]}
    _runs = edit_runs(_dr)
    assert any(r >= {5, 40, 41} for r in _runs), _runs
    assert len(_runs) == 1, _runs
    assert edit_runs({"edits": [{"line": 5, "old": "a", "new": ""},
                                {"line": 40, "old": "b", "new": "c"}]}) \
        == [{5}, {40}]
    assert "group" in (SPECIALIST_DIR / "structure.md").read_text(), \
        "nothing tells structure to group a dedup, so the field is never sent"
    assert edit_runs({**_dr, "specialist": "prose"}) == [{5}, {40, 41}], \
        edit_runs({**_dr, "specialist": "prose"})
    _wide = {"specialist": "structure", "edits":
             [{"line": n, "old": "a", "new": "b", "group": "all"}
              for n in range(1, MAX_GROUP_LINES + 2)]}
    assert len(edit_runs(_wide)) == 1, "a run of consecutive lines is one run"
    _wide["edits"] = [{**e, "line": e["line"] * 10} for e in _wide["edits"]]
    assert len(edit_runs(_wide)) == MAX_GROUP_LINES + 1, \
        "a tie over the cap was obeyed"
    assert len(ties(_wide, over=True)) == MAX_GROUP_LINES + 1, \
        "an over-cap tie's lines were not collected for refusal"
    _wide["edits"] = _wide["edits"][:-1]
    assert len(edit_runs(_wide)) == 1, "a tie at the cap was dropped"
    assert not ties(_wide, over=True), "a tie at the cap was refused"
    _osrc = ["# T", ""] + [f"Sentence number {n} sits on its own line."
                           for n in range(1, 80)]
    _oed = [{"line": n * 10, "old": _osrc[n * 10 - 1], "group": "all",
             "new": f"Short {n}."} for n in range(1, MAX_GROUP_LINES + 2)]
    _ogot, _ook, _ono, *_ = merge(list(_osrc), [
        {"specialist": "structure", "edits": _oed}],
        set(range(3, len(_osrc) + 1)), headings=[(0, 1, "T")])
    assert not _ook, _ook
    assert all("tied to more than" in x[2] for x in _ono), _ono
    assert _ogot == _osrc, "an over-cap tie changed the file"
    _chain = {"specialist": "structure", "edits": [
        {"line": 5, "old": "a", "new": "b", "group": "one"},
        {"line": 20, "old": "a", "new": "b", "group": "one"},
        {"line": 20, "old": "a", "new": "b", "group": "two"},
        {"line": 60, "old": "a", "new": "b", "group": "two"}]}
    assert not any(r >= {5, 60} for r in edit_runs(_chain)), edit_runs(_chain)
    _docs = ((SPECIALIST_DIR.parent / "SKILL.md").read_text()
             + (HERE / "docs" / "user-guide.md").read_text())
    for _cmd, _opts in sorted(cli_surface().items()):
        for _f in sorted(_opts):
            assert _f in _docs or _f == "--out", \
                f"{_f} is in {_cmd} and in no document"
    _dsrc = (["# T", "", "The retry budget is 45 seconds per call.", ""]
             + ["Filler line here."] * 6 + ["",
                "The retry budget is 45 seconds per call.", ""])
    _de = [{"line": 11, "old": _dsrc[10], "new": "", "group": "dup"},
           {"line": 3, "old": _dsrc[2], "group": "dup",
            "new": "It is worth noting that the retry budget is 45 seconds."}]
    _dgot = {}
    for _tag, _es in (("grouped", _de),
                      ("ungrouped", [{k: v for k, v in e.items() if k != "group"}
                                     for e in _de])):
        _, _dok, _dno, *_ = merge(list(_dsrc), [
            {"specialist": "structure", "edits": _es}],
            set(range(1, len(_dsrc) + 1)), headings=[(0, 1, "T")])
        _dgot[_tag] = sorted(a[0] for a in _dok)
    assert _dgot["ungrouped"] == [11], _dgot
    assert _dgot["grouped"] == [], _dgot
    _cs = (["# T", "", "Alpha handles queue requests in strict order.", ""]
           + ["Filler line here."] * 6
           + ["", "Alpha handles queue requests in strict order.", ""])
    _ce = [{"specialist": "noise", "edits": [
                {"line": 3, "old": _cs[2],
                 "new": "Alpha handles queue requests in order."}]},
           {"specialist": "structure", "edits": [
                {"line": 12, "old": _cs[11], "new": "", "group": "dup"},
                {"line": 3, "old": _cs[2], "group": "dup",
                 "new": "Alpha handles queue requests in strict order, and "
                        "line 12 says so again."}]}]
    _, _cok, _cno, *_ = merge(list(_cs), _ce, set(range(1, len(_cs) + 1)),
                              headings=[(0, 1, "T")])
    assert sorted(a[0] for a in _cok) == [3], sorted(a[0] for a in _cok)
    assert any("half a rewrite" in x[2] for x in _cno), _cno
    _tg_old = ("The alpha part is very verbose here. "
               "The beta part is quite terse there.")
    _tg_win = ("The alpha part is verbose here. "
               "The beta part is quite terse there.")
    _tg_lose = ("The alpha part is very verbose here. "
                "The beta part is terse there.")
    assert reoffer(_tg_old, _tg_lose, _tg_win), \
        "the fixture no longer re-offers, so round two is never reached"

    def _tg_run(group):
        seen = []
        _tg_real = globals()["ties"]

        def _tg_spy(result, over=False):
            seen.append([dict(e) for e in result.get("edits", ())])
            return _tg_real(result, over)

        _tg_lines = ["# T", "", _tg_old, "Another line of prose sits here.", ""]
        _tg_e = {"line": 3, "op": "replace", "old": _tg_old, "new": _tg_lose}
        if group is not None:
            _tg_e["group"] = group
        globals()["ties"] = _tg_spy
        try:
            merge(list(_tg_lines),
                  [{"specialist": "prose",
                    "edits": [{"line": 3, "op": "replace",
                               "old": _tg_old, "new": _tg_win}]},
                   {"specialist": "noise", "edits": [_tg_e]}],
                  {3, 4}, (), [(0, 1, "T")])
        finally:
            globals()["ties"] = _tg_real
        return [e for eds in seen for e in eds if e.get("new") == _tg_win_re]

    _tg_win_re = reoffer(_tg_old, _tg_lose, _tg_win)
    _tg_kept = _tg_run("g1")
    assert _tg_kept, "round two never rebuilt the ceded edit at all"
    assert all(e.get("group") == "g1" for e in _tg_kept), \
        f"round two rebuilds the edit without its tie: {_tg_kept}"
    assert all(e.get("group") is None for e in _tg_run(None)), \
        "round two invented a tie the specialist never asked for"

    _hd = "## Summary — read this page, then pick what to read properly"
    assert heading_payload(_hd, "## Summary", ()), "the measured rename walked through"
    assert not heading_payload(_hd, _hd, ())
    assert not heading_payload(_hd, "## Summary", [
        {"op": "insert", "line": 4,
         "new": "Read this page, then pick what to read properly.\n"}])
    assert not heading_payload("## Rollout — three waves", "## Rollout", ())
    assert not heading_payload("## Scope", "## What it covers", ())
    _rdoc = ["# T", "", "## Rollout — read this before you deploy anything",
             "", "Waves land weekly.", "", "## Other", "",
             "The retry budget is 45 seconds.", ""]
    _rh = [(0, 1, "T"), (2, 2, "Rollout — read this before you deploy anything"),
           (6, 2, "Other")]
    _red = set(range(1, len(_rdoc) + 1))

    def _rmerge(edits):
        return merge(list(_rdoc), [{"specialist": "structure", "edits": edits}],
                     set(_red), headings=_rh)

    _ro, _rok, _rno, _ = _rmerge([
        {"line": 3, "old": _rdoc[2], "new": "## Rollout", "why": "shorten"},
        {"line": 5, "old": _rdoc[4],
         "new": "Read this before you deploy anything. Waves land weekly.",
         "why": "carry it", "group": "g1"},
        {"line": 9, "old": _rdoc[8], "new": "The retry budget is short.",
         "why": "thin", "group": "g1"}])
    assert _ro[2] == _rdoc[2], ("the rename survived its carrier", _ro[2])
    assert not _rok, _rok
    assert any(r[0] == 3 and "did not survive" in r[2] for r in _rno), _rno
    for _name, _edits in (
            ("an insert carries it", [
                {"line": 3, "old": _rdoc[2], "new": "## Rollout",
                 "why": "shorten"},
                {"line": 5, "op": "insert",
                 "new": "Read this before you deploy anything.",
                 "why": "carry it"}]),
            ("the carrier lands", [
                {"line": 3, "old": _rdoc[2], "new": "## Rollout",
                 "why": "shorten"},
                {"line": 5, "old": _rdoc[4],
                 "new": "Read this before you deploy anything. Waves land "
                        "weekly.", "why": "carry it"}])):
        _ro, _rok, _rno, _ = _rmerge(_edits)
        assert _ro[2] == "## Rollout", (_name, _ro[2], _rno)
        assert not any(r[0] == 3 for r in _rno), (_name, _rno)
    _mdoc = _rdoc + ["## Last", "", "Tail.", ""]
    _mh = _rh + [(10, 2, "Last")]
    _mo, _mok, _mno, _ = merge(list(_mdoc), [{"specialist": "structure",
                                              "edits": [
        {"line": 3, "op": "move", "to": 11, "why": "later"},
        {"line": 3, "old": _rdoc[2], "new": "## Rollout", "why": "shorten"},
        {"line": 5, "old": _rdoc[4],
         "new": "Read this before you deploy anything. Waves land weekly.",
         "why": "carry it", "group": "g1"},
        {"line": 9, "old": _rdoc[8], "new": "The retry budget is short.",
         "why": "thin", "group": "g1"}]}],
        set(range(1, len(_mdoc) + 1)), headings=_mh)
    assert [a[2] for a in _mok] == ["move"], _mok
    assert _mo.index("## Other") < _mo.index(_rdoc[2]), _mo
    _rkeep = list(_rdoc)
    _rkeep[4] = "Read this before you deploy anything, every wave."
    _ro, _rok, _rno, _ = merge(_rkeep, [{"specialist": "structure", "edits": [
        {"line": 3, "old": _rdoc[2], "new": "## Rollout", "why": "shorten"}]}],
        set(_red), headings=_rh)
    assert _ro[2] == "## Rollout" and not _rno, (_ro[2], _rno)

    _psrc = ["# T", "", _hd, "", "Body.", ""]
    _pout, _, _pno, *_ = merge(_psrc, [
        {"specialist": "structure",
         "edits": [{"line": 3, "old": _hd, "new": "## Summary"}]}],
        set(range(1, 7)), headings=[(0, 1, "T"), (2, 2, "Summary — read this "
                                                        "page, then pick what "
                                                        "to read properly")])
    assert _pno and "tells the reader to" in _pno[0][2], _pno
    assert _pout[2] == _hd, _pout
    _psaid = ["# T", "", _hd, "",
              "Read this page first, then pick what to read properly.", ""]
    _pout, _pok, _pno, *_ = merge(_psaid, [
        {"specialist": "structure",
         "edits": [{"line": 3, "old": _hd, "new": "## Summary"}]}],
        set(range(1, 7)), headings=[(0, 1, "T"), (2, 2, "Summary")])
    assert _pok and not _pno, (_pok, _pno)
    _pout, _pok, _pno, *_ = merge(_psaid, [
        {"specialist": "structure", "edits": [
            {"line": 3, "old": _hd, "new": "## Summary"},
            {"line": 5, "old": _psaid[4], "new": ""}]}],
        set(range(1, 7)), headings=[(0, 1, "T"), (2, 2, "Summary")])
    assert any("tells the reader to" in x[2] for x in _pno), _pno

    for _s, _first in (
            ("Merged code and a closed problem are different things here.", 1),
            ("Approving a spec early is cheaper than fixing code late.", 1),
            ("Both halves matter.", 0),
            ("This action owns that question for the whole plan.", 0)):
        assert bool(len(_s.split()) < 12 and _CARRIES_POINT.search(_s)) \
            == bool(_first), _s
    assert "_CARRIES_POINT.search(s)" in inspect.getsource(cmd_verify), \
        "the dropped list is one pile again"

    _jold = ("The skill exists and RDC is running it through real merge "
             "requests. The path is a weekly bot, then org-wide.")
    _jnew = ("The skill exists, RDC is running it through real merge requests, "
             "and the path is a weekly bot, then org-wide.")
    assert joined_sentences("prose", _jold, _jnew), "the measured join walked through"
    assert not joined_sentences("prose", _jnew, _jold), "a split was refused"
    assert not joined_sentences(
        "prose", _jold, "The skill exists and RDC is running it through real "
                        "merge requests."), "a deletion was read as a join"
    assert not joined_sentences(
        "prose", "The retry ships in v3. And soon.",
        "The retry ships in v3 and soon."), "a fragment merge was refused"
    assert not joined_sentences("structure", _jold, _jnew)
    _jsplit = ("The review skill already exists. RDC runs it through real "
               "merge requests. The path is a weekly bot, then org-wide, and "
               "Bratislava owns the rollout.")
    assert joined_sentences(
        "prose", _jsplit,
        "The review skill already exists and RDC runs it through real merge "
        "requests. The path is a weekly bot, then org-wide. Bratislava owns "
        "the rollout."), "a join behind a split walked through"
    assert joined_sentences(
        "prose", "The review skill already exists. Numbers land on Tuesday. "
                 "RDC runs it through real merge requests.",
        "The review skill already exists and RDC runs it through real merge "
        "requests."), "a join across a deleted sentence walked through"
    _jdup = ("The Alpha system handles requests from the queue. The Alpha "
             "system handles requests from the queue in order.")
    assert not joined_sentences(
        "prose", _jdup,
        "The Alpha system handles requests from the queue in order."), \
        "deleting a near-duplicate was read as a join"
    _jsum = ("The retry budget covers three attempts and the queue drains "
             "within ninety seconds.")
    assert not joined_sentences(
        "prose", "The retry budget covers three attempts. The queue drains "
                 "within ninety seconds. " + _jsum, _jsum), \
        "a deletion under an unchanged summary was read as a join"
    _jone = "Alpha validates requests. Beta validates requests."
    assert joined_sentences(
        "prose", _jone, "Alpha and Beta validate requests."), \
        "a one-word-apiece join walked through"
    assert not joined_sentences("prose", _jone, "Alpha validates requests."), \
        "deleting one of the pair was read as a join"
    _jsrc = ["# T", "", _jold, ""]
    _jout, _, _jno, *_ = merge(_jsrc, [
        {"specialist": "prose",
         "edits": [{"line": 3, "old": _jold, "new": _jnew}]}],
        {3}, headings=[(0, 1, "T")])
    assert _jno and "folds two sentences into one" in _jno[0][2], _jno
    assert _jout[2] == _jold, _jout

    _, ok, no, _ = merge(src, [{"specialist": "prose", "edits": [
        {"line": 2, "old": src[1], "new": "It is worth noting that one."}]}], ed)
    assert not ok and no and "frame" in no[0][2], no
    keeps = ["# T", "It is worth noting that the cache warms.", "b", "c", "d"]
    _, ok, no, _ = merge(keeps, [{"specialist": "prose", "edits": [
        {"line": 2, "old": keeps[1],
         "new": "It is worth noting that the cache clears."}]}], ed)
    assert ok and not no, (ok, no)
    _, ok, no, _ = merge(src, [{"specialist": "summary", "edits": [
        {"op": "insert", "line": 2,
         "new": "## Summary\n\nThe file check has a TOCTOU race."}]}], ed)
    assert ok and not no, (ok, no)
    _, ok, no, _ = merge(src, [{"specialist": "summary", "edits": [
        {"op": "insert", "line": 2, "new": "```python\nx=1"}]}], ed)
    assert isinstance(no, list), no
    _, ok, no, _ = merge(src, [{"specialist": "summary", "edits": [
        {"op": "insert", "line": 2,
         "new": "## Summary\n\nThree of seven goals wait on one service "
                "account."}]}], ed)
    assert ok and not no, (ok, no)
    _has = ["# T", "", "## Summary", "", "It ships in March.", "", "## Body",
            "", "Detail."]
    _, ok, no, _ = merge(_has, [{"specialist": "summary", "edits": [
        {"op": "insert", "line": 2,
         "new": "## Summary\n\nThree goals wait on one account."}]}],
        {2, 5, 9}, headings=[(0, 1, "T"), (2, 2, "Summary"), (6, 2, "Body")])
    assert not ok and "already opens the file" in no[0][2], no
    _in = ["# Title", "", "# Introduction", "", "body text"]
    _got, ok, no, _ = merge(_in, [
        {"specialist": "structure", "edits": [
            {"line": 3, "old": "# Introduction", "new": "# Summary"}]},
        {"specialist": "summary", "edits": [
            {"op": "insert", "line": 3, "new": "## Summary\n\nThe result is X."}]}],
        {3, 5}, headings=[(0, 1, "Title"), (2, 1, "Introduction")])
    assert not any("already opens the file" in r[2] for r in no), no
    assert sum(1 for _l in _got
               if SUMMARY_HEADING.match(re.sub(r"^\s*#+\s*", "", _l).strip())
               and _l.lstrip().startswith("#")) == 1, _got
    _sr = inspect.getsource(cmd_run)
    assert "summary_opens_after(" in _sr and "opens and any(" in _sr, \
        "the summary retry no longer shares merge's answer about the opening"
    assert "first_h" not in _sr, \
        "the retry has grown its own heading walk again"
    _pj = ("# Handbook\n\nThe importer reads the manifest and resolves every "
           "symbol it names.\n\n```\nrun it\n```\n\nThe scheduler reads the "
           "queue and resolves every symbol it names.\n").rstrip("\n").split("\n")
    assert summary_opens_after(_pj, {3: "```"}, {3: "prose"}) == 0, \
        "a projection that cannot be parsed must answer no, not raise"
    assert summary_opens_after(
        _pj, {3: "## Summary\n\nThe importer resolves the manifest nightly."},
        {3: "summary"}), "a projected summary went unseen"
    _rt_line = _RD[2]
    _rt_new = "Session rows are retained by a scalable store."

    def _rt_reply(_p, _a, _n, _seen={}):
        _seen[_p] = _seen.get(_p, 0) + 1
        if _seen[_p] == 1:
            return "", "backend exploded"
        return json.dumps({"edits": [{"line": 3, "op": "replace",
                                      "old": _rt_line, "new": _rt_new,
                                      "why": "verbose"}], "notes": []}), None

    _rt = _runfix(_rt_reply)
    try:
        assert "asking once more" in _rt.err, \
            f"a failed job is no longer retried: {_rt.err[-400:]!r}"
        assert _rt_new in (_rt.dir / "doc.kv.md").read_text(encoding="utf-8"), \
            "the retry was announced and its answer was then dropped"
    finally:
        shutil.rmtree(_rt.dir, ignore_errors=True)

    def _rt_clean(_p, _a, _n):
        return json.dumps({"edits": [{"line": 3, "op": "replace",
                                      "old": _rt_line, "new": _rt_new,
                                      "why": "verbose"}], "notes": []}), None

    _rc2 = _runfix(_rt_clean)
    try:
        assert "asking once more" not in _rc2.err, \
            "a run where nothing failed still announced a retry"
        assert _rt_new in (_rc2.dir / "doc.kv.md").read_text(encoding="utf-8"), \
            "the control never landed its edit, so it proves nothing"
    finally:
        shutil.rmtree(_rc2.dir, ignore_errors=True)
    assert error_digest("a\nb\nc\nd") == "a · b … +2 lines", error_digest("a\nb\nc\nd")
    assert error_digest("only one") == "only one"
    assert error_digest("") == "" and error_digest(None) == ""
    assert "budget.finish_advice" in _sr, \
        "an incomplete run no longer says how to finish it"
    _fa = budget.finish_advice(0, 1, "summary", 431, "d.kv.md", "d.kvjournal",
                               "d.md d.kv.md")
    assert f"KV_FORCE=1 {sys.argv[0]} accept d.md d.kv.md" in _fa \
        and "still unedited" in _fa, "the failure advice hides the other option"
    _cc_new = crosscheck_prompt("t.md", None, False)
    _cc_ran = crosscheck_prompt("t.md", None, True)
    assert "has been simplified" not in _cc_new and "still verbose" not in _cc_new, \
        "a file no run has touched is described to the backend as simplified"
    assert "It has been simplified" in _cc_ran and "still verbose" in _cc_ran, \
        "an edited file is no longer described as edited"
    for _p in (_cc_new, _cc_ran):
        assert "hedges" in _p and "facts stated twice" in _p
    assert "(simplified)" in crosscheck_prompt("t.md", "o.md", False)
    assert "crosscheck_prompt(target, orig, bool(record))" \
        in inspect.getsource(cmd_crosscheck), \
        "crosscheck no longer tells the prompt whether a run touched the file"

    _r = lambda st: rerun.refusal("in.kv.md", 1_700_000_090.0, 1_700_000_000.0, st)
    assert "the next run resumes from it" in _r("banked")
    assert "pays for every job again" in _r("discarded") \
        and "already been discarded" in _r("discarded")
    assert "pays for every job again" in _r("none") \
        and "already been discarded" not in _r("none"), \
        "an absent journal is reported as one this run threw away"
    assert "was not checked here" in _r("unknown") \
        and "resumes from it" not in _r("unknown"), \
        "a caller that did not look is answered as though it had"
    assert "pays for every job again" not in _r("banked"), \
        "a usable journal is reported as lost"
    _rs = inspect.getsource(cmd_run)
    assert _rs.index("_journal_was_there = ") < _rs.index("read_journal("), \
        "the journal is checked after the run that discards it"
    assert '"discarded" if _journal_was_there' in _rs, \
        "the refusal is not told which of the three states this run is in"

    assert "Otherwise delete" in _fa, "the delete instruction lost its Otherwise"
    assert _fa.index("KV_FORCE=1") < _fa.index("Otherwise delete"), \
        "the delete instruction is read before the recovery"
    assert "costs the 431 edits" in _fa and "nobody read it" in _fa, \
        "the advice offers a way out without saying what it costs"
    _low = _fa.lower()
    assert "delete d.kv.md and rerun" in _low and "kv_force" in _low, \
        f"a half of the advice is missing entirely:\n{_fa}"
    assert _low.index("kv_force") < _low.index("delete d.kv.md and rerun"), \
        f"the destructive instruction comes before the recovery:\n{_fa}"
    assert _fa.startswith("KEEP WHAT LANDED FIRST"), \
        f"the first line is not the one that keeps the work:\n{_fa}"
    _fb = budget.finish_advice(0, 1, "summary", 431, "d.kv.md", "d.kvjournal")
    assert not _fb.startswith("Otherwise"), \
        f"'Otherwise' with no option before it:\n{_fb}"
    assert "delete d.kv.md and rerun" in _fb.lower() \
            and "different --agent" in _fb, \
        f"the no-accept branch lost its instruction:\n{_fb}"
    assert "KV_FORCE" not in budget.finish_advice(2, 0, "", 9, "d.kv.md", "d.kvjournal",
                                                  "d.md d.kv.md"), \
        "a run with nothing dead is offered a forced accept"
    assert "KV_FORCE" not in budget.finish_advice(0, 1, "summary", 431, "d.kv.md",
                                                  "d.kvjournal"), \
        "a caller that passed no accept command still gets one printed"
    _doc = "# T\n\nA paragraph of prose.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    _tbl = mask(_doc)[2]
    assert _tbl and isinstance(_tbl[0], tuple), \
        f"the fixture is not mask()'s shape any more: {_tbl!r}"
    _tc = table_caveat(_tbl)
    assert "2 table rows" in _tc and "by hand" in _tc, \
        f"the table caveat does not say how many or what to do: {_tc!r}"
    assert "per row" in _tc and "another tool's state" in _tc, \
        f"the table caveat never mentions a downstream parser: {_tc!r}"
    assert "no shape fires inside a table" not in _tc, \
        f"the caveat is back to claiming no shape fires in a cell: {_tc!r}"
    assert "IS scanned" in _tc, \
        f"the caveat never says a cell is scanned at all: {_tc!r}"
    for _cb in CELL_BLIND:
        assert f"`{_cb}`" in _tc, \
            f"the caveat does not name the blind shape {_cb!r}: {_tc!r}"
    assert table_caveat([]) == "", "the table caveat fires on a file with no table"
    assert table_caveat(mask("# T\n\nProse only, no pipes at all.\n")[2]) == "", \
        "a table-free document is being given the table caveat"
    assert "1 table row:" in table_caveat(mask("# T\n\nx\n\n| only |\n")[2]), \
        "the singular is wrong"
    assert inspect.getsource(cmd_run).count("table_caveat(tables, kv_frozen)") == 1, \
        "the table caveat no longer rides the read-as line"
    assert editable_table_rows(mask("# T\n\nProse only, no pipes.\n")[2]) == 0, \
        "a table-free document reports editable table rows"
    assert editable_table_rows(mask("# T\n\nx\n\n| a | b |\n|---|---|\n| c | d |\n")[2]) == 2, \
        "the row count is not the number of content rows"
    assert editable_table_rows(mask("# T\n\nx\n\n| a | b |\n|---|---|\n|   |   |\n")[2]) == 1, \
        "a blank table row is being counted as editable content"
    assert inspect.getsource(cmd_plan).count("editable_table_rows(tables, kv_frozen)") == 1, \
        "`plan --json` does not carry the intact-row count, so a JSON " \
        "consumer is told about the tables already broken and nothing about " \
        "the rows a specialist can rewrite with every gate passing"
    assert inspect.getsource(cmd_plan).count("table_caveat(tables, kv_frozen)") == 1, \
        "`plan` does not say the table cells stay editable, so the one fact " \
        "that would make a reader diff the rows by hand arrives after the run"

    _tn = tail_note(140.0, 520.0, sent=380.0)
    assert "140s" in _tn and "520s" in _tn and "380s" in _tn, \
        f"the tail note does not report measured sending + tail: {_tn!r}"
    assert "660s" not in _tn, \
        f"the tail note is still adding the BUDGET to the tail: {_tn!r}"
    _tnw = tail_note(0.0, 3600.0, sent=210.0)
    assert "about 210s" in _tnw and "3600s" not in _tnw, \
        f"an unused budget still inflates the wall clock: {_tnw!r}"
    assert "at least 0s" not in _tnw and "at least 1s under" in _tnw, \
        f"the tail note advises a margin of zero: {_tnw!r}"
    assert "at least 140s under" in _tn, \
        "the tail note does not say the next --timeout must clear the tail"
    _tnb = tail_note(140.0, 0.0, no_budget=True, sent=380.0)
    assert "140s" in _tnb and "660" not in _tnb and "--timeout 0" not in _tnb, \
        f"the no-budget tail note invents a total or a flag value: {_tnb!r}"
    assert inspect.getsource(cmd_run).count("print(tail_note(") == 2, \
        "one of the two run exits reports no tail"
    assert polarity_flip("can", "cannot"), "a negation added reads as ordinary"
    assert polarity_flip("nothing here is safe", "everything here is safe")
    assert polarity_flip("is", "is not") and polarity_flip("will", "won't")
    assert not polarity_flip("the", "each"), "an ordinary swap reads as a flip"
    assert not polarity_flip("cannot be read", "cannot be parsed"), \
        "a negation on BOTH sides is not a flip — the polarity did not move"
    assert not polarity_flip("the casino", "the table"), \
        "the negation pattern has no leading word boundary"
    assert not polarity_flip("notation", "table"), \
        "the negation pattern has no trailing word boundary"
    _src_sw = inspect.getsource(cmd_verify)
    assert "_rest[:40]" in _src_sw and "for x in _flips:" in _src_sw, \
        "polarity flips are back inside the truncated list"
    def quiet_print(fn, *a):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(*a)
        return buf.getvalue()
    _mn = quiet_print(measurement_note, {"number": ["11/18", "+10.57%"],
                                         "ticket": ["ABC-1"]})
    assert "2 are numbers" in _mn and "cannot" in _mn and "registered" in _mn, \
        f"a pardoned measurement reads as a pardoned ref: {_mn!r}"
    assert quiet_print(measurement_note, {"ticket": ["ABC-1"]}) == "", \
        "the measurement note fires on a block with no measurement in it"
    assert "1 is a number" in quiet_print(measurement_note, {"number": ["7"]})
    _src_v = inspect.getsource(cmd_verify)
    assert _src_v.count("measurement_note(by_kind)") == 2, \
        "only one of the two pardon blocks says what a lost number costs"
    _src_r = inspect.getsource(cmd_run)
    _hdr = _src_r.split('── verify ──')[1][:400]
    assert "INCOMPLETE" in _hdr and "if failed else" in _hdr, \
        "the verify header no longer says the file it describes is incomplete"

    _pe = reply.payload("Here is my thinking. No object at all.")[1]
    assert '"edits"' in _pe and '"notes"' in _pe and "Here is my thinking" in _pe, \
        "the no-JSON error still shows only what came back"
    assert '"edits"' not in reply.payload('{"edits": [,]}')[1], \
        "the bad-JSON error answers a question nobody asked there"
    assert "nothing applied — {what}" in _sr, \
        "a fully refused specialist is invisible again"
    assert "went to the line's owner" in _sr.split("nothing applied")[0][-400:], \
        "the per-specialist line calls an owner transfer a gate refusal again"
    assert "the full path as given above" in inspect.getsource(cmd_crosscheck), \
        "crosscheck may print an unopenable path again"
    _cc = inspect.getsource(cmd_crosscheck)
    assert "Read the diff" in _cc, "crosscheck judges the file, not the change"
    assert "One entry per problem" in _cc, "one habit can fill the report again"
    assert "double-quoted" in _cc, "crosscheck may run the document again"
    mis = ["The rule can collide and", "the address is hit by chance."]
    _, ok, no, _ = merge(mis, [
        {"specialist": "quotable", "edits": [
            {"line": 1, "old": "THIS DOES NOT MATCH", "new": "wrong text."}]},
        {"specialist": "prose", "edits": [
            {"line": 1, "old": mis[0], "new": "The rule can collide and"}]}],
        {1, 2})
    assert any("does not match" in r[2] for r in no), no
    assert any(a[0] == 1 and a[2] == "reword" for a in ok), (ok, no)
    _both = ["intro line.", "The rule can collide and",
             "the address is hit by chance."]
    _, ok, no, _ = merge(_both, [{"specialist": "prose", "edits": [
        {"line": 2, "old": _both[1], "new": "The rule can collide."},
        {"line": 3, "old": _both[2],
         "new": "The rule can collide with the address."}]}], {1, 2, 3})
    assert not ok and len(no) == 2, (ok, no)
    ptr = ["# Overview", "", "some prose here"]
    _, ok, no, _ = merge(ptr, [
        {"specialist": "structure", "edits": [
            {"line": 1, "old": "# Overview", "new": "# What we found"}]},
        {"specialist": "summary", "edits": [
            {"op": "insert", "line": 3,
             "new": "The result is one blocked account. (Overview)"}]}],
        {1, 3}, headings=[(0, 1, "Overview")])
    assert any("renamed by another specialist" in r[2] for r in no), no
    half = ["the rate decides whether blocking is on, and",
            "the March sample is what set it."]
    _, ok, no, _ = merge(half, [{"specialist": "structure", "edits": [
        {"line": 1, "old": half[0], "new": half[0]},
        {"line": 2, "old": half[1], "new": ""}]}], {1, 2})
    assert any("does not finish its sentence" in r[2] for r in no), no
    dup = ["parts. An invented local part can collide",
           "with a real address by chance."]
    _, ok, no, _ = merge(dup, [{"specialist": "structure", "edits": [
        {"line": 2, "old": dup[1],
         "new": "An invented local part can collide with a real address."}]}],
        {1, 2})
    assert not ok and "on both sides of a line break" in no[0][2], no
    _, ok, no, _ = merge(dup, [{"specialist": "structure", "edits": [
        {"line": 1, "old": dup[0],
         "new": "parts. An invented local part can collide with a real address."},
        {"line": 2, "old": dup[1], "new": ""}]}], {1, 2})
    assert len(ok) == 2 and not no, (ok, no)
    li = ["- run the linter", "- run the tests", "- ship it"]
    _, ok, no, _ = merge(li, [{"specialist": "noise", "edits": [
        {"line": 2, "old": li[1], "new": ""}]}], {1, 2, 3})
    assert ok and not no, (ok, no)
    pr = ["# Costs", "", "The team pays for it (Costs) every month."]
    _, ok, no, _ = merge(pr, [
        {"specialist": "structure", "edits": [
            {"line": 1, "old": "# Costs", "new": "# What it costs"}]},
        {"specialist": "prose", "edits": [
            {"line": 3, "old": pr[2],
             "new": "The team pays for it (Costs) monthly."}]}],
        {1, 3}, headings=[(0, 1, "Costs")])
    assert len(ok) == 2 and not no, (ok, no)
    own = ["# T", "", "## Summary", "", "The gate blocks 85% of traffic today.",
           "", "## Body", "", "text"]
    o_res = [
        {"specialist": "quotable", "lo": 1, "hi": 9, "edits": [
            {"line": 5, "old": own[4], "new": "The gate blocks 85% of it."}]},
        {"specialist": "summary", "lo": 1, "hi": 9, "edits": [
            {"line": 5, "old": own[4],
             "new": "The gate blocks 85% of traffic today, per Body."}]}]
    o_res.sort(key=lambda r: (list(SPECIALISTS).index(r["specialist"]), r["lo"]))
    _, ok, no, _ = merge(own, o_res, {5, 9}, (), [(0, 1, "T"), (2, 2, "Summary"),
                                                  (6, 2, "Body")], 3)
    assert [a[1] for a in ok] == ["summary"], (ok, no)
    assert any("already changed by summary" in r[2] for r in no), no

    two = ["We should leverage the retry loop here. The gate blocks 85% of "
           "traffic today.", "", "Happy to help."]
    t_res = [
        {"specialist": "prose", "lo": 1, "hi": 3, "edits": [
            {"line": 1, "old": two[0], "new": two[0].replace("leverage",
                                                             "use")}]},
        {"specialist": "chat", "lo": 1, "hi": None, "edits": [
            {"line": 1, "old": two[0], "new": two[0].replace("traffic today",
                                                             "it today")}]}]
    t_res.sort(key=lambda r: (list(SPECIALISTS).index(r["specialist"]), r["lo"]))
    got, ok, no, _ = merge(two, t_res, {1, 3})
    assert not no and len(ok) == 2, (ok, no)
    assert got[0] == ("We should use the retry loop here. The gate blocks 85% "
                      "of it today."), got[0]
    over = [{"specialist": "prose", "lo": 1, "hi": 3, "edits": [
                {"line": 1, "old": two[0],
                 "new": two[0].replace("leverage", "use")}]},
            {"specialist": "chat", "lo": 1, "hi": None, "edits": [
                {"line": 1, "old": two[0],
                 "new": two[0].replace("leverage the retry loop", "retry")}]}]
    over.sort(key=lambda r: (list(SPECIALISTS).index(r["specialist"]), r["lo"]))
    _, ok, no, _ = merge(two, over, {1, 3})
    assert [a[1] for a in ok] == ["chat"], (ok, no)
    assert any("already changed by chat" in r[2] for r in no), no
    assert "_round=2" in inspect.getsource(merge), \
        "round two must be marked, or it can call itself forever"

    lk = ["# T", "", "## The decision", "",
          "See [the decision](#the-decision) for it.", "", "more text here."]
    lk_h = [(0, 1, "T"), (2, 2, "The decision")]
    _all = set(range(1, len(lk) + 1))
    g, ok, no, _ = merge(list(lk), [{"specialist": "structure", "lo": 1,
                                     "hi": 7, "edits": [
        {"line": 3, "old": lk[2], "new": "## Ship in v3"}]}], _all, (), lk_h)
    assert not ok and no and "breaks the link on line 5" in no[0][2], no
    assert not broken_anchors("\n".join(g)), broken_anchors("\n".join(g))
    g, ok, no, _ = merge(list(lk), [{"specialist": "structure", "lo": 1,
                                     "hi": 7, "edits": [
        {"line": 3, "old": lk[2], "new": "## Ship in v3"},
        {"line": 5, "old": lk[4], "new": "See Ship in v3 for it."}]}],
        _all, (), lk_h)
    assert len(ok) == 2 and not no, (ok, no)
    assert not broken_anchors("\n".join(g)), broken_anchors("\n".join(g))
    _, ok, no, _ = merge(list(lk), [{"specialist": "structure", "lo": 1,
                                     "hi": 7, "edits": [
        {"line": 3, "old": lk[2], "new": "## The decision!"}]}],
        _all, (), lk_h)
    assert len(ok) == 1 and not no, (ok, no)
    msg = ["There might be an issue with the retry loop.", "", "Happy to help."]
    c_res = [
        {"specialist": "quotable", "lo": 1, "hi": 3, "edits": [
            {"line": 1, "old": msg[0], "new": "There may be an issue here."}]},
        {"specialist": "chat", "lo": 1, "hi": None, "edits": [
            {"line": 1, "old": msg[0], "new": "the retry loop drops one try."}]}]
    c_res.sort(key=lambda r: (list(SPECIALISTS).index(r["specialist"]), r["lo"]))
    got, ok, no, _ = merge(msg, c_res, {1, 3})
    assert got[0] == "the retry loop drops one try.", got
    assert any("already changed by chat" in r[2] for r in no), no
    d_res = [
        {"specialist": "noise", "lo": 1, "hi": 3, "edits": [
            {"line": 1, "old": msg[0], "new": ""}]},
        {"specialist": "chat", "lo": 1, "hi": None, "edits": [
            {"line": 1, "old": msg[0], "new": "the retry loop drops one try."}]}]
    d_res.sort(key=lambda r: (list(SPECIALISTS).index(r["specialist"]), r["lo"]))
    _, ok, no, _ = merge(msg, d_res, {1, 3})
    assert [a[2] for a in ok] == ["delete"], (ok, no)
    b_res = [
        {"specialist": "quotable", "lo": 1, "hi": 9, "edits": [
            {"line": 5, "old": own[4], "new": "The gate blocks 85% of it."}]},
        {"specialist": "summary", "lo": 1, "hi": 9, "edits": [
            {"line": 5, "old": "THIS DOES NOT MATCH", "new": "whatever"}]}]
    b_res.sort(key=lambda r: (list(SPECIALISTS).index(r["specialist"]), r["lo"]))
    got, ok, no, _ = merge(own, b_res, {5, 9}, (),
                           [(0, 1, "T"), (2, 2, "Summary"), (6, 2, "Body")], 3)
    assert got[4] == "The gate blocks 85% of it.", got[4]
    wr = ["The gate blocks the traffic and the",
          "threshold is 2029 requests per hour."]
    got, ok, no, _ = merge(wr, [{"specialist": "prose", "lo": 1, "hi": 2, "edits": [
        {"line": 1, "old": wr[0], "new": "The gate blocks traffic over 2029 "
                                         "requests per hour."},
        {"line": 2, "old": wr[1], "new": ""}]}], {1, 2})
    assert len(ok) == 2 and not no, (ok, no)
    assert got == ["The gate blocks traffic over 2029 requests per hour."], got
    _, ok, no, _ = merge(wr, [
        {"specialist": "quotable", "lo": 1, "hi": 2, "edits": [
            {"line": 1, "old": wr[0], "new": "The gate blocks 2029 of them."}]},
        {"specialist": "prose", "lo": 1, "hi": 2, "edits": [
            {"line": 2, "old": wr[1], "new": "the threshold is high."}]}], {1, 2})
    assert any("drops 2029" in r[2] for r in no), no
    far = ["The retry budget is 2029 attempts.", "", "filler one.", "",
           "filler two.", "", "The cache holds entries."]
    _, ok, no, _ = merge(far, [{"specialist": "prose", "lo": 1, "hi": 7, "edits": [
        {"line": 1, "old": far[0], "new": "The retry budget is capped."},
        {"line": 7, "old": far[6], "new": "The cache holds 2029 entries."}]}],
        {1, 3, 5, 7})
    assert any("drops 2029" in r[2] for r in no), no
    assert ends_sentence("Three of seven goals are blocked. (Rollout status)")
    assert ends_sentence("He said \"stop.\"")
    assert not ends_sentence("the rate decides whether blocking is on, and")
    assert not ends_sentence("it is capped at (roughly) two")
    ptr = ["Three of seven goals are blocked today."]
    _, ok, no, _ = merge(ptr, [{"specialist": "summary", "lo": 1, "hi": 1, "edits": [
        {"line": 1, "old": ptr[0],
         "new": "Three of seven goals are blocked. (Rollout status)"}]}], {1})
    assert ok and not no, (ok, no)
    d_own = ["# T", "", "## Summary", "", "The gate blocks 85% of traffic today.",
             "", "## Body", "", "text"]
    d_hd = [(0, 1, "T"), (2, 2, "Summary"), (6, 2, "Body")]
    d2 = [{"specialist": "noise", "lo": 1, "hi": 9, "edits": [
              {"line": 5, "old": "DOES NOT MATCH", "new": ""}]},
          {"specialist": "quotable", "lo": 1, "hi": 9, "edits": [
              {"line": 5, "old": d_own[4], "new": "The gate blocks 85% of it."}]},
          {"specialist": "summary", "lo": 1, "hi": 9, "edits": [
              {"line": 5, "old": d_own[4],
               "new": "The gate blocks 85% of traffic daily."}]}]
    d2.sort(key=lambda r: (list(SPECIALISTS).index(r["specialist"]), r["lo"]))
    got, ok, no, _ = merge(d_own, d2, {5, 9}, (), d_hd, 3)
    assert got[4] == "The gate blocks 85% of traffic daily.", got[4]
    w_own = ["# T", "", "## Summary", "", "The gate blocks traffic and the",
             "threshold is high today.", "", "## Body", "", "text"]
    w2 = [{"specialist": "quotable", "lo": 1, "hi": 10, "edits": [
              {"line": 5, "old": w_own[4], "new": "The gate blocks traffic and the"}]},
          {"specialist": "summary", "lo": 1, "hi": 10, "edits": [
              {"line": 5, "old": w_own[4],
               "new": "The gate blocks traffic when the threshold is high today."},
              {"line": 6, "old": w_own[5], "new": ""}]}]
    w2.sort(key=lambda r: (list(SPECIALISTS).index(r["specialist"]), r["lo"]))
    got, ok, no, _ = merge(w_own, w2, {5, 6, 10}, (),
                           [(0, 1, "T"), (2, 2, "Summary"), (7, 2, "Body")], 3)
    assert len(ok) == 2 and got[4].endswith("high today."), (ok, no, got[4])
    v_own = ["# T", "", "## Summary", "", "the rule can collide",
             "with the address by chance.", "", "## Body", "", "text"]
    v2 = [{"specialist": "quotable", "lo": 1, "hi": 10, "edits": [
              {"line": 6, "old": v_own[5], "new": "with the address."}]},
          {"specialist": "summary", "lo": 1, "hi": 10, "edits": [
              {"line": 6, "old": v_own[5],
               "new": "the rule can collide with the address by chance."}]}]
    v2.sort(key=lambda r: (list(SPECIALISTS).index(r["specialist"]), r["lo"]))
    got, ok, no, _ = merge(v_own, v2, {5, 6, 10}, (),
                           [(0, 1, "T"), (2, 2, "Summary"), (7, 2, "Body")], 3)
    assert got[5] == "with the address.", (got[5], ok, no)
    assert '"error", "reply_error"' in inspect.getsource(cmd_run), \
        "a successful retry is still counted as a dead span"
    blanks = ["para", "", "```", "", "x = 1", "```"]
    assert fence_lines(blanks) == {3, 4, 5, 6}, fence_lines(blanks)
    two = ["first line here", "second line here"]
    _, ok, no, _ = merge(two, [{"specialist": "prose", "lo": 1, "hi": 1, "edits": [
        {"line": 2, "old": "second line here", "new": "x"}]}], {1, 2})
    assert not ok and "outside its span" in no[0][2], no
    _, ok, no, _ = merge(fact_src, [{"specialist": "prose", "edits": [
        {"line": 1, "old": fact_src[0], "new": ""}]}], {1})
    assert not ok and "BIQ-1131" in no[0][2], no
    _, ok, no, _ = merge(fact_src, [{"specialist": "noise", "edits": [
        {"line": 1, "old": fact_src[0], "new": ""}]}], {1})
    assert ok and not no, (ok, no)
    _fd = ["# T", "", "It reads its own wider scope from there.", "",
           "The loader lives in `filters.py` and runs first.", ""]
    _fp, _fh, _ft, _fq = mask("\n".join(_fd))
    _fe = editable_lines(_fp, _ft, _fh, _fq)

    def _reword(new):
        return merge(_fd, [{"specialist": "quotable", "edits": [
            {"line": 3, "old": _fd[2], "new": new}]}], _fe, (), _fh)[1:3]

    _ok, _no = _reword("`filters.py` reads its own wider scope.")
    assert _ok and not _no, (_ok, _no)
    _ok, _no = _reword("`nowhere.py` reads its own wider scope.")
    assert not _ok and "nowhere in this document" in _no[0][2], _no

    q = ["> Alice said the gate is closed."]
    _, ok, no, _ = merge(q, [{"specialist": "prose", "edits": [
        {"line": 1, "old": q[0], "new": "> the gate is open"}]}], {1}, {1})
    assert not ok and "quotation" in no[0][2], no
    _, ok, no, _ = merge(q, [{"specialist": "noise", "edits": [
        {"line": 1, "old": q[0], "new": ""}]}], {1}, {1})
    assert ok and not no, (ok, no)

    _tr = ("Dana\n\n###### 00:00 - 01:10\n\n"
           "We should like maybe extract the rules per merge request class.\n\n"
           "Alex Morgan\n\n###### 01:10 - 01:54\n\n"
           "Yeah. I also ask Claude some questions that are repeated.\n\n"
           "## Analysis\n\nIt is worth noting that nothing was decided.\n")
    _tp, _th, _tt, _tq = mask(_tr)
    assert [l for l, _ in _tq] == [1, 5, 7, 11], _tq
    assert [i + 1 for i, l in enumerate(_tp) if l.strip()] == [15], _tp
    assert find_shapes(_tp, _tt, _th, _tq) == [(15, "frame", "It is worth noting")]
    _one = "# T\n\n###### 00:00\n\nOrdinary prose it is worth noting.\n"
    _op, _oh, _ot, _oq = mask(_one)
    assert not _oq and _op[4].strip(), (_oq, _op)

    spaced = ["a", "", "", "b"]
    assert merge(spaced, [], {1, 4})[0] == spaced, merge(spaced, [], {1, 4})[0]

    wrapped = ["`vocab` tries all 105 hand-typed words on a prompt carrying no",
               "labelled value."]
    got, ok, no, _ = merge(wrapped, [{"specialist": "prose", "edits": [
        {"line": 1, "old": wrapped[0],
         "new": "`vocab` tries all 105 hand-typed words."}]}], {1, 2})
    assert not no and len(ok) == 2, (ok, no)
    assert got == ["`vocab` tries all 105 hand-typed words."], got
    _kept = [wrapped[0], wrapped[1] + "  <!-- kv:keep -->"]
    _, ok, no, _ = merge(_kept, [{"specialist": "prose", "edits": [
        {"line": 1, "old": _kept[0],
         "new": "`vocab` tries all 105 hand-typed words."}]}], {1, 2})
    assert not ok and no and "fragment" in no[0][2], no
    _half = ["The gate blocks the traffic and the", "threshold is high."]
    _g, ok, no, _ = merge(_half, [{"specialist": "prose", "edits": [
        {"line": 1, "old": _half[0], "new": "The gate blocks traffic and the"}]}],
        {1, 2})
    assert len(ok) == 1 and not no, (ok, no)
    assert _g == ["The gate blocks traffic and the", "threshold is high."], _g
    got, ok, no, _ = merge(wrapped, [{"specialist": "prose", "edits": [
        {"line": 1, "old": wrapped[0],
         "new": "`vocab` tries all 105 hand-typed words."},
        {"line": 2, "old": wrapped[1], "new": ""}]}], {1, 2})
    assert len(ok) == 2 and not no, (ok, no)
    assert got == ["`vocab` tries all 105 hand-typed words."], got
    real = ["many fire, how many appear in no set, how many fire on English carrying no",
            "credential. Today, 105 fire, 35 appear in no set, and 0 fire on English."]
    _, ok, no, _ = merge(real, [{"specialist": "prose", "edits": [
        {"line": 2, "old": real[1],
         "new": "Today, 105 fire, 35 appear in no set, and 0 fire on English."}]}],
        {1, 2})
    assert not ok and no and "fragment" in no[0][2], no
    for pair, new in ((["Three things matter:", "- the first"], "Three things."),
                      (["| a | b |", "| c | d |"], "| x | y |"),
                      (["the gate is open", "Then it closes."], "the gate is shut.")):
        _, ok, no, _ = merge(pair, [{"specialist": "prose", "edits": [
            {"line": 1, "old": pair[0], "new": new}]}], {1, 2})
        assert ok and not no, (pair, ok, no)
    caps = ["Send each request to", "API Gateway when the",
            "upstream is unavailable."]
    _, ok, no, _ = merge(caps, [{"specialist": "prose", "edits": [
        {"line": 1, "old": caps[0], "new": "Send each request."}]}], {1, 2, 3})
    assert not ok and no and "fragment" in no[0][2], no
    curly = ["He said “stop.”", "then he left."]
    _, ok, no, _ = merge(curly, [{"specialist": "prose", "edits": [
        {"line": 2, "old": curly[1], "new": "Then he left."}]}], {1, 2})
    assert ok and not no, (ok, no)
    _, ok, no, _ = merge(wrapped, [{"specialist": "prose", "edits": [
        {"line": 1, "old": wrapped[0],
         "new": "`vocab` tries all 105 hand-typed words."},
        {"line": 2, "old": "not the line at all", "new": ""}]}], {1, 2})
    assert not ok and len(no) == 2, (ok, no)
    assert any("fragment" in r[2] for r in no), no
    _, ok, no, _ = merge(wrapped, [{"specialist": "prose", "edits": [
        {"line": 1, "old": wrapped[0],
         "new": "`vocab` tries all 105 hand-typed words."},
        {"line": 2, "old": wrapped[1], "new": "with `an unclosed span."}]}],
        {1, 2})
    assert not ok and len(no) == 2, (ok, no)

    assert unpaired_paragraphs(['He said "the gate', "is missing. Then he left."]) \
        == {1: ["quote"]}
    assert not unpaired_paragraphs(['He said "the gate', 'is missing." Then he left.'])
    assert unpaired_paragraphs(['A `span and a "quote here.']) \
        == {1: ["backtick", "quote"]}
    assert unpaired_paragraphs(["A (b (c here."]) \
        == {1: ["parenthesis", "parenthesis"]}
    assert "unpaired_paragraphs(o_prose)" in inspect.getsource(cmd_verify)
    _o = ["A line (open here.", "", "Second paragraph is fine."]
    _n = ["A line (open here.", "", "Second (paragraph is not."]
    assert len(unpaired_paragraphs(_n)) == 2 and len(unpaired_paragraphs(_o)) == 1
    assert "Counter(n for names in unpaired_paragraphs" in inspect.getsource(cmd_verify)

    fenced_doc = ["# T", "## A", "```text", "```literal", "## fake",
                  "```still literal", "```", "body", "## B", "b"]
    f_p, f_h, _f_t, _f_q = mask("\n".join(fenced_doc))
    assert [(h[0] + 1, h[1]) for h in f_h] == [(1, 1), (2, 2), (9, 2)], f_h
    assert not f_p[4].strip(), f_p[4]
    assert section_span(f_h, 10, 2) == (2, 8), section_span(f_h, 10, 2)
    ind = ["# T", "## A", "a", "", "    ## example", "    code", "", "more",
           "## B", "b"]
    i_p, i_h, _i_t, _i_q = mask("\n".join(ind))
    assert [(h[0] + 1, h[1]) for h in i_h] == [(1, 1), (2, 2), (9, 2)], i_h
    assert section_span(i_h, 10, 2) == (2, 8), section_span(i_h, 10, 2)

    hard = ["Set feature_enabled to no  ", "Restart the service."]
    _, ok, no, _ = merge(hard, [{"specialist": "prose", "edits": [
        {"line": 2, "old": hard[1], "new": "Restart it."}]}], {1, 2})
    assert ok and not no, (ok, no)
    pair = ["the run finished in", "12 minutes and 4 seconds."]
    _, ok, no, _ = merge(pair, [{"specialist": "prose", "edits": [
        {"line": 1, "old": pair[0], "new": "the run finished."},
        {"line": 2, "old": pair[1], "new": "It was quick."}]}], {1, 2})
    assert not ok and len(no) == 2, (ok, no)
    quad = ["# T", "````text", "```", "## fake", "````", "## B"]
    q_p, q_h, _q_t, _q_q = mask("\n".join(quad))
    assert [(h[0] + 1, h[1]) for h in q_h] == [(1, 1), (6, 2)], q_h
    assert not q_p[3].strip(), q_p[3]

    tagged = ["# Real", "", "#hashtag is not a heading", "", "####### nor this",
              "", "## Also real"]
    t_p, t_h, _t_t, _t_q = mask("\n".join(tagged))
    assert [(h[0] + 1, h[1]) for h in t_h] == [(1, 1), (7, 2)], t_h
    assert "#hashtag is not a heading" in t_p[2], t_p[2]
    assert section_span(t_h, 7, 1) == (1, 7), section_span(t_h, 7, 1)

    doc = ["# Title", "", "## Background", "history here", "",
           "## Result", "the answer", "", "### Detail", "sub point", "",
           "## Next", "do this"]
    d_p, d_h, d_t, d_q = mask("\n".join(doc))
    d_ed = editable_lines(d_p, d_t, d_h, d_q)
    assert section_span(d_h, 13, 6) == (6, 11), section_span(d_h, 13, 6)
    assert section_span(d_h, 13, 9) == (9, 11), section_span(d_h, 13, 9)
    assert section_span(d_h, 13, 1) == (1, 13), section_span(d_h, 13, 1)
    assert section_span(d_h, 13, 3) == (3, 5), section_span(d_h, 13, 3)
    assert section_span(d_h, 13, 4) is None

    def mv(**kw):
        return merge(doc, [{"specialist": kw.pop("who", "structure"),
                            "edits": [{"op": "move", **kw}]}], d_ed,
                     (), d_h)

    got, ok, no, _ = mv(line=6, to=3, why="result first")
    assert ok and not no, (ok, no)
    assert got.index("## Result") < got.index("## Background"), got
    assert got.index("### Detail") < got.index("## Background"), got
    assert got.index("sub point") == got.index("### Detail") + 1, got
    assert sorted(x for x in got if x.strip()) == \
        sorted(x for x in doc if x.strip()), got
    got, ok, no, _ = mv(line=12, to=3, why="result first")
    assert ok and not no, (ok, no)
    _i = got.index("do this")
    assert got[_i + 1] == "" and got[_i + 2] == "## Background", got[_i:_i + 3]
    assert sorted(x for x in got if x.strip()) == \
        sorted(x for x in doc if x.strip()), got
    _fn = ["# T", "", "## Where logs live", "",
           "Application logs are held 12 months[^loki].", "",
           "## What the audit needs", "",
           "The auditor asked for one answer[^audit].", "",
           "[^loki]: Loki retention policy, confirmed 2026-05-02.",
           "[^audit]: ISO 42001 evidence request, ticket OPS-4118.", ""]
    assert body_end(_fn) == 9, body_end(_fn)
    _fnp, _fnh, _fnt, _fnq = mask("\n".join(_fn))
    assert section_span(_fnh, body_end(_fn), 7) == (7, 9)
    got, ok, no, _ = merge(_fn, [{"specialist": "structure", "edits": [
        {"op": "move", "line": 7, "to": 3, "why": "result first"}]}],
        editable_lines(_fnp, _fnt, _fnh, _fnq), (), _fnh)
    assert ok and not no, (ok, no)
    assert got.index("## What the audit needs") < got.index("## Where logs live")
    for _m in ("[^loki]:", "[^audit]:"):
        _d = next(i for i, l in enumerate(got) if l.startswith(_m))
        _u = next(i for i, l in enumerate(got) if _m[:-1] + "." in l)
        assert _u < _d, f"{_m} used at {_u}, defined at {_d}"
    assert body_end(doc) == len(doc), body_end(doc)
    got, ok, no, _ = mv(line=3, to=14, why="appendix")
    assert ok and not no, (ok, no)
    assert got.index("## Background") > got.index("do this"), got
    got, ok, no, _ = mv(line=6, to=2, why="result first")
    assert not ok and no, (ok, no)
    _bur = ["# T", "", "This is preamble a reader does not need first, and it runs on long enough to count as real body text rather than a byline or a link, which is the whole distinction this check exists to make.", "",
            "## Summary", "", "The answer is 12 months.", "", "## Body", "",
            "detail"]
    _bp, _bh, _bt, _bq = mask("\n".join(_bur))
    _bs = opening_summary(_bh, _bp, SUMMARY_NEEDED_FROM)
    assert _bs["buried"] == 5
    assert _bs["above"] == 1 and buried_above(_bs) == 1, _bs
    for _msg in (summary_verdict(_bs)[1], summary_blocked(_bs)):
        assert "1 line of body" in _msg and "4 line" not in _msg, _msg
    assert "buried_above(summary)" in inspect.getsource(cmd_run), \
        "the run-time message went back to counting physical lines"
    _by_hand = _bur[:1] + _bur[4:8] + _bur[1:4] + _bur[8:]
    _hp, _hh, _ht, _hq = mask("\n".join(_by_hand))
    _after = opening_summary(_hh, _hp, SUMMARY_NEEDED_FROM)
    assert _after["present"] and _after["words"] > 12, _after
    assert "preamble" in " ".join(_hp[2:_after["end"]]), _by_hand
    got, ok, no, _ = merge(doc, [
        {"specialist": "structure", "edits": [
            {"op": "move", "line": 6, "to": 3, "why": "result first"}]},
        {"specialist": "summary", "edits": [
            {"op": "insert", "line": 7, "new": "INSERTED"}]}], d_ed, (), d_h)
    assert len(ok) == 2 and not no, (ok, no)
    assert got.index("INSERTED") == got.index("## Result") + 2, got
    assert got[got.index("## Result") + 1] == "", got
    assert got.index("INSERTED") < got.index("## Background"), got

    _sd = ["# Title", "", "## Summary", "the result in one line", "",
           "## Background", "why it happened", "", "## Result", "do this", "",
           "## Next", "later"]
    _sp, _sh, _st, _sq = mask("\n".join(_sd))
    _g, ok, no, _ = merge(_sd, [{"specialist": "structure", "edits": [
        {"op": "move", "line": 9, "to": 6, "why": "result first"}]}],
        editable_lines(_sp, _st, _sh, _sq), (), _sh, summary_line=3)
    assert ok and not no, (ok, no)
    assert _g.index("## Result") < _g.index("## Background"), _g

    _g, ok, no, _ = merge(doc, [
        {"specialist": "structure", "edits": [
            {"line": 12, "old": "## Next", "new": "", "why": "dead"}]},
        {"specialist": "structure", "edits": [
            {"op": "move", "line": 3, "to": 12, "why": "background last"}]}],
        d_ed, (), d_h)
    assert len(ok) == 1 and len(no) == 1 and "was deleted" in no[0][2], (ok, no)

    _g, ok, no, _ = merge(doc, [{"specialist": "noise", "edits": [
        {"line": 12, "old": "## Next", "new": "", "why": "dead"}]}],
        d_ed, (), d_h)
    assert not ok and "that is a heading" in no[0][2], (ok, no)
    assert _g[11] == "## Next", _g[11]
    _g, ok, no, _ = merge(doc, [{"specialist": "noise", "edits": [
        {"line": 12, "old": "## Next", "new": "## Later", "why": "shorter"}]}],
        d_ed, (), d_h)
    assert ok and not no, (ok, no)

    for kw, want in (
            (dict(line=4, to=3), "not a heading"),
            (dict(line=6, to=4), "not a heading"),
            (dict(line=1, to=6), "the title"),
            (dict(line=6, to=1), "above the title"),
            (dict(line=3, to=6), "already there"),
            (dict(line=6, to=99), "not a line in the file"),
            (dict(line=6, to="3"), "takes a line number, not a name"),
            (dict(line=6, to=3, who="prose"), "only structure"),
    ):
        _g, ok, no, _ = mv(**kw)
        assert not ok and no and want in no[0][2], (kw, ok, no)

    _g, ok, no, _ = merge(doc, [{"specialist": "structure", "edits": [
        {"op": "move", "line": 6, "to": 3},
        {"op": "move", "line": 9, "to": 14}]}], d_ed, (), d_h)
    assert len(ok) == 1 and len(no) == 1 and "already moved" in no[0][2], (ok, no)
    _g, ok, no, _ = merge(doc, [{"specialist": "prose", "edits": [
        {"op": "delete", "line": 4, "old": "history here", "new": ""}]}], d_ed)
    assert not ok and no and "no such op" in no[0][2], no

    assert facts("shipped 2026-08-07")["date"] == {"2026-08-07"}
    assert facts("shipped 2026-08-07") != facts("shipped 2026-07-08")
    assert facts("use v1.2.3")["version"] == {"v1.2.3"}
    assert facts("use v1.2.3") != facts("use v9.9.9")
    fenced_doc = ["ticket BIQ-1131 in prose", "```", "BIQ-1131", "```"]
    assert only_copy(token_lines(fenced_doc), 1, 1) == ["BIQ-1131"]

    for bad in ('{"edits": 5}', '{"edits": [1]}',
                '{"edits": [{"old": "a", "new": "b"}]}',
                '{"edits": [{"line": 1, "new": []}]}'):
        payload, err = parse_reply(bad)
        assert payload is None and err, (bad, payload, err)
    for empty in ('{"edits": null}', '{"edits": [], "notes": null}', "{}"):
        payload, err = parse_reply(empty)
        assert payload == {"edits": [], "notes": []} and not err, (empty, payload)

    doc = ["ticket BIQ-1131 here", "path `src/a.py` twice", "again `src/a.py`"]
    idx = token_lines(doc)
    assert only_copy(idx, 1, 1) == ["BIQ-1131"], only_copy(idx, 1, 1)
    assert only_copy(idx, 2, 2) == [], only_copy(idx, 2, 2)

    assert collapse_blanks(["a", "", "", "", "b"]) == ["a", "", "b"]
    assert collapse_blanks(["```", "", "", "```"]) == ["```", "", "", "```"]

    assert same_family("codex", "codex")
    assert same_family("agy", "gemini") and same_family("claude", "claude")
    assert not same_family("agy (model=gemini-3.5-flash)", "codex")
    assert not same_family("claude", "codex")
    _cc_src = inspect.getsource(cmd_crosscheck)
    assert "same_family_state(_reviewer, wrote, real_target)" in _cc_src, \
        "crosscheck no longer checks who actually answered"
    assert 'read_run_record(real_target)' in _cc_src \
        and 'answering_backends(record)' in _cc_src, \
        "crosscheck cannot see which model wrote the edits it is reading"

    assert 'same_family_state(backend, _wrote_before,' in _cc_src, \
        "crosscheck no longer refuses a backend explicitly set to the model that wrote"
    with tempfile.TemporaryDirectory() as _d:
        _f = Path(_d) / "d.kv.md"
        _f.write_text("# a\n\ntext\n")
        (Path(_d) / "d.md").write_text("# a\n\ntext\n")
        _f.with_suffix(".md.kvrun").write_text(json.dumps(
            {"agent": "codex", "chat": False, "inserted": True,
             "summary_added": False, "swaps": [], "exempt": [], "incomplete": [],
             "source": hashlib.sha256(b"# a\n\ntext\n").hexdigest()}))
        _ns = argparse.Namespace(file=str(_f), original=str(Path(_d) / "d.md"),
                                 context=[], backend="codex", full=False)

        def _no_subprocess(*a, **k):
            raise AssertionError(
                "crosscheck spawned a codex reviewer of a codex-written run. "
                "The pre-flight did not refuse; only the post-hoc check can have, and that "
                "one costs the whole read first.")

        _real_run = spawn.run_tree
        spawn.run_tree = _no_subprocess
        try:
            with contextlib.redirect_stderr(io.StringIO()) as _err:
                _rc, _ = cmd_crosscheck(_ns)
        finally:
            spawn.run_tree = _real_run
        assert _rc == 2, f"crosscheck accepted a self-review: exit {_rc}, expected 2"
        assert "is the model that wrote these edits" in _err.getvalue(), \
            "crosscheck refused without saying the reviewer wrote the edits"

    assert recapitalise("Context: as discussed in the thread, the gate was red.",
                        "the release gate had been red.") \
        == "The release gate had been red."
    assert recapitalise("- Context: the gate went red on Tuesday and again.",
                        "- the gate went red twice.") == "- The gate went red twice."
    assert recapitalise("Note: gemini-3.5-flash is the default model here.",
                        "gemini-3.5-flash is the default.") \
        == "gemini-3.5-flash is the default."
    assert recapitalise("Note: `verify` is the command that checks this.",
                        "`verify` checks this.") == "`verify` checks this."
    assert recapitalise("the gate was already lowercase here.",
                        "the gate stays lowercase.") == "the gate stays lowercase."
    assert recapitalise("Context: we saw red.", "Context: we saw red, still.") \
        == "Context: we saw red, still."

    _toc = "- 5.2 [Extract to Memoized Components](#52-extract-to-memoized-components)"
    assert tokens_dropped("structure", _toc, "- 5.2 [Memoized](#memoized)") \
        == "the link target #52-extract-to-memoized-components"
    assert tokens_dropped("prose", "we saw 52 failures", "we saw failures") == "52"
    assert tokens_dropped("prose", "see 52 in [x](#52)", "see in [x](#y)") == "52"

    _said = 'He said "a precise number on the wrong finish line is worse".'
    assert quotes_dropped(_said, "")
    assert quotes_dropped(_said, "He said the number was worse.")
    assert not quotes_dropped(_said, _said)
    assert not quotes_dropped(
        _said, 'He said "a precise number on the\n  wrong finish line is '
               'worse".')
    assert not quotes_dropped(_said, "", kept=_said)
    assert not quotes_dropped('## The "wrong finish line" problem',
                              "## The problem")
    assert not quotes_dropped('| "not started" | ok |', "| none | ok |")
    assert not quotes_dropped('> He said "no".', "> He refused.")

    def _seam(n):
        return f"line {n} does not finish its sentence and this line held the rest"
    _cas = [(108, "prose", "the replacement text has planning language"),
            (109, "prose", _seam(108)), (110, "prose", _seam(109)),
            (111, "prose", _seam(110)),
            (113, "prose", "the replacement text has parked problem"),
            (114, "prose", _seam(113)), (115, "prose", _seam(114))]
    _f = fold_cascade(_cas)
    assert [x[0] for x in _f] == ["L108-111", "L113-115"], _f
    assert _f[0][2].endswith("and the 3 wrapped lines under it went with it")
    assert [x[0] for x in fold_cascade([(9, "prose", _seam(8))])] == ["L9"]
    assert len(fold_cascade([(9, "prose", "bad"), (11, "prose", _seam(10))])) == 2

    wrapped = []
    for _n in range(14):
        wrapped += ["Ordinary prose sitting under the margin this file uses",
                    "throughout its body, line after line, for many lines.", ""]
    assert wrap_width(wrapped) == 54, wrap_width(wrapped)
    long_line = "The rewritten sentence runs well past the margin " * 3
    assert len(rewrap_prose(wrapped, [long_line] + wrapped[1:])) > len(wrapped)
    assert rewrap_prose(wrapped, wrapped) == wrapped
    bullet = rewrap_prose(wrapped, ["- " + long_line] + wrapped[1:])
    assert bullet[0].startswith("- ") and bullet[1].startswith("  "), bullet[:2]
    fenced = wrapped + ["```", "x " * 60, "```", "| " + "y " * 50 + "|",
                        "> " + "z " * 50]
    assert rewrap_prose(fenced, fenced) == fenced
    loose = ["A paragraph the editor soft-wraps, so it is one very long line in "
             "the file and no margin at all can be read off it, however far past "
             "the usual column it happens to run." for _n in range(20)]
    assert wrap_width(loose) is None
    assert rewrap_prose(loose, loose) == loose
    _w80 = [("word " * 15).strip() for _ in range(12)]
    _links = ["see [the very long runbook section title spelled out in full]"
              "(https://example.internal/docs/runbooks/database/failover/"
              "step-by-step-with-rollback.md) for the rest" for _ in range(4)]
    _mixed = []
    for _i in range(8):
        _mixed += [_w80[_i], _w80[_i], ""]
    for _l in _links:
        _mixed += [_l, _w80[0], ""]
    assert wrap_width(_mixed) == 74, wrap_width(_mixed)
    _clean = [ln for ln in _mixed if "https://" not in ln]
    assert wrap_width(_clean) == 74, wrap_width(_clean)
    assert len(_wrapping._continuation_lengths(_mixed)) \
        > len(_wrapping._continuation_lengths(_mixed, evidence_only=True))
    _nm = no_margin_notice(["A paragraph wrapped narrow at about",
                            "fifty columns for two lines here.", ""])
    assert _nm.startswith("no wrap margin found") and "1 paragraph runs" in _nm \
        and "1 continuation line" in _nm, _nm
    _one_big = no_margin_notice(["one", "two", "three", "four", "five",
                                 "six", "seven", "eight", "nine", "ten", ""])
    _many = no_margin_notice(["a", "b", "", "c", "d", "", "e", "f", "",
                              "g", "h", "", "i", "j", ""])
    assert "1 paragraph runs over" in _one_big, _one_big
    assert "5 paragraphs run over" in _many, _many
    _mixed_para = no_margin_notice(["a heading line", "", "alone", "",
                                    "wrapped one", "wrapped two", "", "solo", ""])
    assert "1 paragraph runs over" in _mixed_para, _mixed_para

    assert no_margin_notice(["alpha", "", "beta", ""]) == \
        "no wrap margin found, so the lines go to the specialists as written", \
        no_margin_notice(["alpha", "", "beta", ""])
    _nm0 = no_margin_notice(["One line.", "", "Another line.", ""])
    assert _nm0 == ("no wrap margin found, so the lines go to the specialists "
                    "as written"), _nm0
    for _c in (cmd_run, cmd_plan):
        assert "no_margin_notice(prose)" in inspect.getsource(_c), \
            f"{_c.__name__} does not say what the other says about a margin"

    for head in ("12:04", "[12:04]", "(12:04:31)", "12:04 - 12:09",
                 "12:04 — Alex", "12:04:31 Alex Morgan"):
        assert TIMESTAMP_HEAD.match(head), head
    assert not TIMESTAMP_HEAD.match("12:04 " + "x " * 40)

    payload, err = parse_reply('here you go:\n```json\n{"edits": [], "notes": ["x"]}\n```')
    assert not err and payload["notes"] == ["x"], (payload, err)
    assert parse_reply("I could not find anything to change.")[0] is None

    pad = ("word " * 900).strip()
    for lead, want in (("## Summary", True), ("# Summary", True),
                       ("## Intro", False)):
        p_, h_, _t, _q = mask(f"# T\n\n{lead}\n\nIt works.\n\n## Body\n\n{pad}\n")
        got = opening_summary(h_, p_, 909)
        assert got["present"] is want, (lead, got)

    _seen_spawn = []

    def _fenced_run(cmd, **kw):
        _seen_spawn.append((list(cmd), dict(kw)))
        _out = ('{"event":"result","result":{"status":"SUCCESS",'
                '"response":"ok"}}\n') if "agy" in cmd[0] else "ok"
        return subprocess.CompletedProcess(cmd, 0, _out, "")

    _huge = "X" * 40000
    _real_spawn = spawn.run_tree
    _saved_io = _INSTALLED_OVERRIDE
    _real_which = shutil.which
    spawn.run_tree = _fenced_run
    # on Windows _cli_argv resolves the name on PATH; no agent need be installed
    shutil.which = lambda name, *a, **k: name
    try:
        globals()["_INSTALLED_OVERRIDE"] = dict.fromkeys(LOCAL_AGENTS, True)
        for _ag in LOCAL_AGENTS:
            _o, _e = call_agent(_huge, _ag, 5)
            assert _e is None and _o == "ok", (_ag, _o, _e)
    finally:
        spawn.run_tree = _real_spawn
        shutil.which = _real_which
        globals()["_INSTALLED_OVERRIDE"] = _saved_io
    assert len(_seen_spawn) == len(LOCAL_AGENTS), \
        (f"call_agent did not reach every agent ({len(_seen_spawn)} of "
         f"{len(LOCAL_AGENTS)})")
    for (_cmd, _kw), _ag in zip(_seen_spawn, LOCAL_AGENTS):
        assert _huge not in " ".join(_cmd), \
            f"the {_ag} path puts the prompt in argv"
        assert _huge in (_kw.get("input") or ""), \
            f"the {_ag} path no longer feeds the prompt over stdin"
        assert _kw.get("timeout"), f"the {_ag} path spawns with no timeout"

    _real_platform = sys.platform
    try:
        sys.platform = "win32"
        _argv_w, _err_w = _cli_argv("no-such-agent-cli-here")
        assert _argv_w is None and "no-such-agent-cli-here" in _err_w, \
            (_argv_w, _err_w)
        sys.platform = "linux"
        assert _cli_argv("codex") == (["codex"], None)
    finally:
        sys.platform = _real_platform

    _saved_io = _INSTALLED_OVERRIDE
    try:
        globals()["_INSTALLED_OVERRIDE"] = {"claude": True, "codex": False,
                                            "agy": True}
        assert agent_chain("codex") == ["codex", "claude", "agy"], \
            agent_chain("codex")
        assert agent_chain("agy", avoid=("claude",)) == ["agy"], \
            agent_chain("agy", avoid=("claude",))
        assert agent_chain("claude", avoid=("claude",)) == ["agy"]
        assert agent_name("Gemini") == "agy" and agent_name("CODEX") == "codex"
        assert agent_name("my-llm --json") == "my-llm --json", \
            "a custom agent command was not kept as given"
        try:
            agent_name("codex --model x")
            raise AssertionError("a known agent took flags it would drop")
        except UsageError as e:
            assert "--agent codex" in str(e), e
    finally:
        globals()["_INSTALLED_OVERRIDE"] = _saved_io

    src_v = inspect.getsource(cmd_verify)
    assert "return 3" in src_v and "return 1" in src_v, "verify lost a verdict"

    src_r = inspect.getsource(cmd_run)
    for _ag, _want in (("codex", "agy"), ("claude", "agy"), ("agy", "codex")):
        _rb = _runfix(_quiet, agent=_ag)
        try:
            _adv = [_l for _l in _rb.out.splitlines() if "KV_BACKEND=" in _l]
            assert _adv, f"the run named no reviewer for --agent {_ag}"
            _got = _adv[0].split("KV_BACKEND=")[1].split()[0]
            assert _got != _ag, \
                f"the reviewer must not be the model that made the edits: " \
                f"--agent {_ag} was reviewed by {_got}"
            assert _got == _want, f"--agent {_ag} picked {_got}, not {_want}"
        finally:
            shutil.rmtree(_rb.dir, ignore_errors=True)

    _saved_dc = _INSTALLED_OVERRIDE
    try:
        globals()["_INSTALLED_OVERRIDE"] = {"agy": False, "codex": True}
        _rs = _runfix(_quiet, agent="claude")
        try:
            _adv = [_l for _l in _rs.out.splitlines() if "KV_BACKEND=" in _l]
            _got = _adv[0].split("KV_BACKEND=")[1].split()[0]
            assert _got == "codex", \
                (f"agy is not installed and codex is, and the advice still "
                 f"named {_got}")
        finally:
            shutil.rmtree(_rs.dir, ignore_errors=True)

        globals()["_INSTALLED_OVERRIDE"] = {"agy": False, "codex": False}
        _rn = _runfix(_quiet, agent="claude")
        try:
            assert "KV_BACKEND=" not in _rn.out, \
                f"neither reviewer is installed and a name was still " \
                f"printed: {_rn.out[-300:]!r}"
            assert "kill-verbosity crosscheck" in _rn.out, _rn.out[-300:]
        finally:
            shutil.rmtree(_rn.dir, ignore_errors=True)
    finally:
        globals()["_INSTALLED_OVERRIDE"] = _saved_dc

    _ns_nobackend = argparse.Namespace(backend=None)
    _saved_dc = _INSTALLED_OVERRIDE
    _saved_kvb = os.environ.pop("KV_BACKEND", None)
    try:
        globals()["_INSTALLED_OVERRIDE"] = {"agy": True, "codex": True}
        assert crosscheck_backend(_ns_nobackend) == "codex", \
            "the ordinary default moved off codex with nothing telling it to"
        globals()["_INSTALLED_OVERRIDE"] = {"agy": True, "codex": False}
        assert crosscheck_backend(_ns_nobackend) == "agy", \
            "codex is not installed and agy is, and the default kept codex"
        globals()["_INSTALLED_OVERRIDE"] = {}
        assert crosscheck_backend(_ns_nobackend) == "codex", \
            "with nothing installed the default moved off codex anyway"
        assert crosscheck_backend(argparse.Namespace(backend="claude")) \
            == "claude"
        os.environ["KV_BACKEND"] = "gemini"
        assert crosscheck_backend(_ns_nobackend) == "agy"
    finally:
        globals()["_INSTALLED_OVERRIDE"] = _saved_dc
        os.environ.pop("KV_BACKEND", None)
        if _saved_kvb is not None:
            os.environ["KV_BACKEND"] = _saved_kvb

    with tempfile.TemporaryDirectory() as _ad:
        _af = Path(_ad) / "d.kv.md"
        _af.write_text("# a\n\ntext\n")
        (Path(_ad) / "d.md").write_text("# a\n\ntext\n")
        _af.with_suffix(".md.kvrun").write_text(json.dumps(
            {"agent": "agy", "chat": False, "inserted": True,
             "summary_added": False, "swaps": [], "exempt": [], "incomplete": [],
             "source": hashlib.sha256(b"# a\n\ntext\n").hexdigest()}))
        _ans = argparse.Namespace(file=str(_af), original=str(Path(_ad) / "d.md"),
                                  context=[], backend="claude", full=False)

        def _claude_missing(cmd, **kw):
            return subprocess.CompletedProcess(
                cmd, 2, "", "error: unrecognized arguments: --restricted")

        _real_run2 = spawn.run_tree
        spawn.run_tree = _claude_missing
        _saved_dc2 = _INSTALLED_OVERRIDE
        try:
            globals()["_INSTALLED_OVERRIDE"] = {"agy": False, "codex": True,
                                                "claude": True}
            with contextlib.redirect_stderr(io.StringIO()) as _err2:
                _rc2, _ = cmd_crosscheck(_ans)
            assert _rc2 == 2
            _msg2 = _err2.getvalue()
            assert "--backend codex" in _msg2, _msg2

            globals()["_INSTALLED_OVERRIDE"] = {"agy": False, "codex": False,
                                                "claude": True}
            with contextlib.redirect_stderr(io.StringIO()) as _err3:
                _rc3, _ = cmd_crosscheck(_ans)
            _msg3 = _err3.getvalue()
            assert "--backend codex" not in _msg3 \
                and "--backend claude" not in _msg3, \
                f"an uninstalled or failing agent was suggested: {_msg3!r}"
        finally:
            spawn.run_tree = _real_run2
            globals()["_INSTALLED_OVERRIDE"] = _saved_dc2

    assert src_r.index("would overwrite") < src_r.index("if args.dry_run"), \
        "the -o guard is back below the dry-run return"

    assert 'getattr(args, "context"' in inspect.getsource(cmd_crosscheck), \
        "crosscheck lost --context"
    src_x = inspect.getsource(cmd_crosscheck)
    assert "Never invent a name" in src_x, \
        "crosscheck may invent a value again"
    assert "Assigning a named owner IS a concrete action" not in src_x, \
        "crosscheck is being told to demand an owner again"
    assert "run_notes_prompt(record)" in src_x, \
        "crosscheck no longer tells the reviewer what the run did on purpose"
    _drop = run_notes_prompt({"exempt": ["next-steps item 9"]})
    assert "not report any of them as a lost fact" in _drop \
        and "next-steps item 9" in _drop, \
        "crosscheck may report a deliberate deletion as a loss again"
    assert "INSERTED the opening summary" not in _drop, \
        "the summary note fires on a run that wrote no summary"
    _sum = run_notes_prompt({"summary_added": True})
    assert "do not ask for it to be removed" in _sum, \
        "crosscheck may ask for the run's own summary to be deleted again"
    assert "lost fact" not in _sum, \
        "the deletion note fires on a run that dropped no reference"
    assert run_notes_prompt({}) == "", \
        "a run that did neither is told about both"
    assert "is a citation, not jargon" in src_x, \
        "crosscheck may report a proof path as verbosity again"
    assert "absence from your view is not a finding" in src_x, \
        "crosscheck may read a path it cannot open as unresolvable again"
    assert "Report a reference only when" in src_x, \
        "the citation exemption now covers an unresolvable reference too"
    assert run_notes_prompt({"exempt": [], "summary_added": False}) == "", \
        "an empty pardon list reads as a deliberate deletion"
    assert 'str(why).split(":")[0].strip() == "summary"' in src_r, \
        "summary_added is set for any insert, not for the summary"
    assert "added_shapes(e.get" in src_r, "the summary insert is not retried"

    assert "exempt=sorted(" in src_r, "run stopped recording them"
    src_a = inspect.getsource(cmd_accept)
    assert "exempt=[]" in src_a and "exempt=exempt" not in src_a, \
        "accept is reading the pardon list again instead of leaving it to verify"
    assert "run_record_path(out).unlink" in src_a, \
        "accept leaves the record behind for the next run to trust"
    assert "st_mtime" in inspect.getsource(read_run_record), \
        "verify takes the pardon list without checking it belongs to this run"
    assert "content_edit=False" not in src_a, \
        "accept hardcodes content_edit off, so a content pass needs --force"
    assert "The version before this run is in git." not in src_a, \
        "accept is promising git again"
    assert 'f".orig{src.suffix}"' in src_a, "accept stopped naming the baseline"
    _bb = _RUNDOC.encode("utf-8") + b"\nA stray \xff byte ends this file.\n"
    _bc = _runfix(_quiet, doc=_bb)
    try:
        _base = _bc.dir / "doc.orig.md"
        assert _base.is_file(), "the run wrote no baseline at all"
        assert _base.read_bytes() == _bb, \
            "the baseline is being rewritten from decoded text again"
        assert b"\xef\xbf\xbd" not in _base.read_bytes(), \
            "the unreadable byte was frozen into the baseline as U+FFFD"
    finally:
        shutil.rmtree(_bc.dir, ignore_errors=True)
    src_v = inspect.getsource(cmd_verify)
    assert "Counter(getattr(args" in src_v and "exempt[v]" in src_v, \
        "the noise exemption is back to a membership test"
    import contextlib as _cl
    import io as _io
    import random as _rnd
    import tempfile as _tf
    _d = _tf.mkdtemp()
    _o, _n = Path(_d) / "o.md", Path(_d) / "n.md"
    _o.write_text("# T\n\nAccuracy is 85% today.\n\nThe gate is 85% as well.\n")

    def _ver(edited, pardons):
        _n.write_text(edited)
        buf = _io.StringIO()
        with _cl.redirect_stdout(buf):
            rc = cmd_verify(argparse.Namespace(
                original=str(_o), edited=str(_n), chat=False,
                content_edit=False, exempt=pardons))
        return rc, "TOKENS LOST" in buf.getvalue()

    _gone = "# T\n\nAccuracy is good today.\n\nThe gate is fine as well.\n"
    _half = "# T\n\nAccuracy is good today.\n\nThe gate is 85% as well.\n"
    _side = run_record_path(_n)
    _buf = _io.StringIO()
    _n.write_text(_gone)
    write_run_record(_n, exempt=["85%", "85%"])
    with _cl.redirect_stdout(_buf):
        cmd_verify(argparse.Namespace(original=str(_o), edited=str(_n),
                                      chat=False, content_edit=False))
    assert "TOKENS LOST" not in _buf.getvalue(), _buf.getvalue()
    assert RUN_SUFFIX in _buf.getvalue(), "verify did not say it read the record"
    _lo, _ln2 = Path(_d) / "lo.md", Path(_d) / "ln.md"
    _lo.write_text("# Doc\n\nSee the [changelog](CHANGELOG.md) and the "
                   "[decisions](decisions.md).\n\nThe importer reads "
                   "`data/extracted/` every night.\n")
    _ln2.write_text("# Doc\n\nSee the [changelog](../tests/CHANGELOG.md) and "
                    "the [decisions](../.claude/decisions.md).\n\nThe importer "
                    "reads `data/extracted/` every night.\n")
    _lbuf = _io.StringIO()
    with _cl.redirect_stdout(_lbuf):
        _lrc = cmd_verify(argparse.Namespace(original=str(_lo),
                                             edited=str(_ln2), chat=False,
                                             content_edit=False))
    _lout = _lbuf.getvalue()
    assert _lrc == 1 and "TOKENS EDITED" in _lout, (_lrc, _lout)
    assert "nothing to act on" not in _lout, _lout
    assert "A pass does not add facts" not in _lout, \
        "a repointed link is not an invented fact"
    _fl = next((l for l in _lout.split("\n")
                if l.startswith("FAILED the run:")), None)
    assert _fl and "TOKENS EDITED" in _fl, \
        "the FAIL verdict names no block:\n%s" % _lout
    assert [k for k in IP_SHORT if k in _fl], \
        "the FAIL verdict names nothing IP_SHORT knows: %r" % _fl
    _ro, _rn = Path(_d) / "ro.md", Path(_d) / "rn.md"
    _ro.write_text("# Doc\n\nSee the [changelog](CHANGELOG.md) for history.\n\n"
                   "Older entries are in the [changelog](CHANGELOG.md) too.\n\n"
                   "The importer reads `data/extracted/` every night.\n")
    _rn.write_text(_ro.read_text().replace(
        "[changelog](CHANGELOG.md) for", "[changelog](../tests/CHANGELOG.md) for"))
    _rbuf = _io.StringIO()
    with _cl.redirect_stdout(_rbuf):
        _rrc = cmd_verify(argparse.Namespace(original=str(_ro), edited=str(_rn),
                                             chat=False, content_edit=False))
    _rout = _rbuf.getvalue()
    assert "links repointed" in _rout and "../tests/CHANGELOG.md" in _rout, _rout
    assert "A pass does not add facts" not in _rout and _rrc == 0, (_rrc, _rout)
    _rn3 = Path(_d) / "rn3.md"
    _rn3.write_text(_ro.read_text().replace(
        "every night.", "every night, and mirrors it to ../tests/CHANGELOG.md."))
    _r3buf = _io.StringIO()
    with _cl.redirect_stdout(_r3buf):
        cmd_verify(argparse.Namespace(original=str(_ro), edited=str(_rn3),
                                      chat=False, content_edit=False))
    assert "links repointed" not in _r3buf.getvalue() \
        and "TOKENS ADDED" in _r3buf.getvalue(), _r3buf.getvalue()

    _rn2 = Path(_d) / "rn2.md"
    _rn2.write_text(_ro.read_text().replace(
        "[changelog](CHANGELOG.md) for", "[changelog](../tests/HISTORY.md) for"))
    _r2buf = _io.StringIO()
    with _cl.redirect_stdout(_r2buf):
        cmd_verify(argparse.Namespace(original=str(_ro), edited=str(_rn2),
                                      chat=False, content_edit=False))
    assert "links repointed" not in _r2buf.getvalue(), _r2buf.getvalue()

    _ln3 = Path(_d) / "ln3.md"
    _ln3.write_text(_lo.read_text().replace(
        "every night.", "and `data/staging/notes.md` every night."))
    _abuf = _io.StringIO()
    with _cl.redirect_stdout(_abuf):
        cmd_verify(argparse.Namespace(original=str(_lo), edited=str(_ln3),
                                      chat=False, content_edit=False))
    assert "TOKENS ADDED" in _abuf.getvalue(), _abuf.getvalue()

    _bl, _wp = Path(_d) / "bl.md", Path(_d) / "wp.md"
    _bl.write_text("# N\n\nThe room was warm and the window faced the garden.\n"
                   "Someone brought biscuits for the table.\n")
    _wp.write_text("# N\n")
    _wbuf = _io.StringIO()
    with _cl.redirect_stdout(_wbuf):
        _wrc = cmd_verify(argparse.Namespace(original=str(_bl), edited=str(_wp),
                                             chat=False, content_edit=False))
    assert _wrc == 1 and "EVERYTHING GONE" in _wbuf.getvalue(), \
        f"wiping every prose line is not a failure: {_wrc}"
    _sp, _spe = Path(_d) / "sp.md", Path(_d) / "spe.md"
    _sp.write_text(
        "# N\n\nThe room was warm and the window faced the garden.\n"
        "Merged code and a closed problem are different things here.\n"
        "It is worth noting that the biscuits were on the table.\n"
        "Approving a spec early is cheaper than fixing code late.\n"
        "In order to proceed, the committee reviewed the agenda again.\n")
    _spe.write_text("# N\n\nThe room was warm and the window faced the "
                    "garden.\n")
    _spbuf = _io.StringIO()
    with _cl.redirect_stdout(_spbuf):
        cmd_verify(argparse.Namespace(original=str(_sp), edited=str(_spe),
                                      chat=False, content_edit=False))
    _spout = _spbuf.getvalue()
    assert "most worth reading" in _spout, _spout
    _nfo = ("Deployments use ArgoCD and Flux. An SBOM is produced. "
            "Access to the status analysis is optional.")
    _named, _plain = words_not_found(_nfo, "use flux.", _nfo)
    assert _named == ["argocd", "sbom"], _named
    for _t in ("Read-only filesystem where possible",
               "Repo-only skills are still available",
               "Not only that, it also works",
               "This repo contains Markdown files only."):
        assert finding_rank(_t)[0] <= 0, (_t, finding_rank(_t))
    for _t in ("Only files under 384KB are indexed",
               "Use this skill only when the task matches"):
        assert "constrains" in finding_rank(_t)[1], (_t, finding_rank(_t))
    for _w in ("access", "status", "analysis"):
        assert _w in _plain, (_w, _plain)
    assert not words_not_found("Use Flux.", "use flux.", "Use Flux.")[1]
    assert ("Merged code and a closed problem" in _spout.split(
        "the rest, in file order")[0]), \
        f"a sentence carrying the point was not promoted:\n{_spout}"
    assert "the rest, worth reading first" in _spout, \
        f"the second list printed with no heading:\n{_spout}"
    _wp.write_text("# N\n\nThe room was warm and the window faced the garden.\n")
    _tbuf = _io.StringIO()
    with _cl.redirect_stdout(_tbuf):
        _trc = cmd_verify(argparse.Namespace(original=str(_bl), edited=str(_wp),
                                             chat=False, content_edit=False))
    assert _trc == 3 and "EVERYTHING GONE" not in _tbuf.getvalue(), \
        f"an ordinary cut is being called a deletion: {_trc}"

    _stale = _io.StringIO()
    os.utime(_side, (1, 1))
    with _cl.redirect_stdout(_stale):
        cmd_verify(argparse.Namespace(original=str(_o), edited=str(_n),
                                      chat=False, content_edit=False))
    assert "TOKENS LOST" in _stale.getvalue(), \
        "verify honoured a pardon list older than the file it sits beside"
    assert "ignoring" in _stale.getvalue(), "verify did not say it skipped it"
    _side.unlink()
    assert _ver(_gone, ["85%"]) == (1, True), _ver(_gone, ["85%"])
    assert _ver(_half, ["85%"]) == (0, False), _ver(_half, ["85%"])
    assert _ver(_gone, ["85%", "85%"]) == (0, False), _ver(_gone, ["85%", "85%"])
    _o.write_text("# T\n\n| Check | Ticket |\n|---|---|\n"
                  "| fence gate | BIQ-9902 |\n\nThe `pipeline` step runs.\n")
    _n.write_text("# T\n\n| Check | Ticket |\n|---|---|\n\nThe step runs.\n")
    _tb = _io.StringIO()
    with _cl.redirect_stdout(_tb):
        cmd_verify(argparse.Namespace(original=str(_o), edited=str(_n),
                                      chat=False, content_edit=False,
                                      exempt=[]))
    assert "L5  | fence gate | BIQ-9902 |" in _tb.getvalue(), _tb.getvalue()
    assert "L7  The `pipeline` step runs." in _tb.getvalue(), _tb.getvalue()

    _long = ("# T\n\n## Guidance\n\n" + " ".join(f"w{i}" for i in range(400))
             + "\n\n## Detail\n\n" + " ".join(f"b{i}" for i in range(600))
             + "\n")
    _o.write_text(_long)
    _n.write_text(_long.replace("## Guidance", "## Summary: Guidance"))
    _rn = _io.StringIO()
    with _cl.redirect_stdout(_rn):
        cmd_verify(argparse.Namespace(original=str(_o), edited=str(_n),
                                      chat=False, content_edit=False,
                                      exempt=[]))
    assert f"words {word_count(_long)} → {word_count(_n.read_text())}" \
        in _rn.getvalue(), _rn.getvalue()

    def _vsplit(orig_text, edit_text):
        _o.write_text(orig_text)
        _n.write_text(edit_text)
        b = _io.StringIO()
        with _cl.redirect_stdout(b):
            cmd_verify(argparse.Namespace(original=str(_o), edited=str(_n),
                                          chat=False, content_edit=False,
                                          exempt=[]))
        return b.getvalue()

    _bd = " ".join(f"b{i}" for i in range(1000))
    _sm = " ".join(f"s{i}" for i in range(120))
    _plain = f"# T\n\n## Guidance\n\n{_bd}\n"
    _hit = _vsplit(_plain, f"# T\n\n## Summary: Guidance\n\n{_bd}\n")
    assert "renamed rather than wrote" in _hit and "\nbody " not in _hit, _hit
    _both = _vsplit(_plain,
                   f"# T\n\n## Summary\n\n{_sm}\n\n## Summary: Guidance\n\n{_bd}\n")
    assert "renamed rather than wrote" not in _both, _both
    assert "opening summary 0 → 120 (120 new)" in _both, _both

    _ld = Path(_tf.mkdtemp())
    (_ld / "target.md").write_text("# T\n\n## Access needed\n\nx\n")
    (_ld / "sub").mkdir()
    (_ld / "sub" / "target.md").write_text("# Other\n\n## Access needed\n\nx\n")
    for _f, _body in (
            ("plain.md", "See [a](./target.md#access-needed) here.\n"),
            ("titled.md", 'See [a](target.md#access-needed "T") here.\n'),
            ("angled.md", "See [a](<target.md#access-needed>) here.\n"),
            ("own.md", "See [a](#access-needed) here.\n"),
            ("far.md", "See [a](./sub/target.md#access-needed) here.\n")):
        (_ld / _f).write_text(_body)
    _in = inbound_anchors(_ld / "target.md", "Access needed")
    assert sorted(_in) == ["angled.md", "plain.md", "titled.md"], _in

    def _hd(*names):
        return [(i * 4, 1 if i == 0 else 2, t) for i, t in enumerate(names)]

    assert heading_moves(_hd("T", "The problem", "Evidence", "What to do"),
                         _hd("T", "What to do", "Retention gap", "Evidence")) \
        == ([("The problem", "Retention gap")], []), \
        heading_moves(_hd("T", "The problem", "Evidence", "What to do"),
                      _hd("T", "What to do", "Retention gap", "Evidence"))
    assert heading_moves(_hd("T", "A", "B"), _hd("T", "B", "A")) == ([], []), \
        heading_moves(_hd("T", "A", "B"), _hd("T", "B", "A"))
    assert heading_pairs(_hd("T", "The problem", "Evidence", "What to do"),
                         _hd("T", "What to do", "Retention gap",
                             "Evidence"))[0][0][2] == 2
    assert heading_moves(_hd("T", "Alpha", "Shared"),
                         _hd("T", "Shared", "Gamma")) == ([], ["Alpha"]), \
        heading_moves(_hd("T", "Alpha", "Shared"), _hd("T", "Shared", "Gamma"))
    assert heading_moves(_hd("T", "A", "A"), _hd("T", "A")) == ([], ["A"]), \
        heading_moves(_hd("T", "A", "A"), _hd("T", "A"))
    _dr = heading_moves(_hd("T", "A", "A", "B"), _hd("T", "A", "C"))
    assert len(_dr[0]) == 1 and len(_dr[1]) == 1, _dr
    assert heading_moves(
        [(0, 1, "T"), (4, 2, "Setup"), (8, 3, "Keys"), (12, 2, "Usage")],
        [(0, 1, "T"), (4, 2, "Setup"), (8, 2, "Keys"),
         (12, 2, "Usage")]) == ([], []), \
        heading_moves([(0, 1, "T"), (4, 2, "Setup"), (8, 3, "Keys"),
                       (12, 2, "Usage")],
                      [(0, 1, "T"), (4, 2, "Setup"), (8, 2, "Keys"),
                       (12, 2, "Usage")])
    assert heading_moves([(0, 1, "T"), (4, 2, "A"), (8, 2, "B")],
                         [(0, 1, "T"), (4, 3, "C"), (8, 2, "D")]) == (
                             [("B", "D")], ["A"]), \
        heading_moves([(0, 1, "T"), (4, 2, "A"), (8, 2, "B")],
                      [(0, 1, "T"), (4, 3, "C"), (8, 2, "D")])
    _rng = _rnd.Random(11)
    for _ in range(400):
        _fo = [(i * 4, _rng.choice([1, 2, 3]), _rng.choice("ABCDEF"))
               for i in range(_rng.randint(1, 6))]
        _fn = [(i * 4, _rng.choice([1, 2, 3]), _rng.choice("ABCDEF"))
               for i in range(_rng.randint(0, 6))]
        _fr, _fg = heading_moves(_fo, _fn)
        _fot, _fnt = Counter(h[2] for h in _fo), Counter(h[2] for h in _fn)
        assert len(_fr) + len(_fg) <= len(_fo), (_fo, _fn, _fr, _fg)
        for _was, _now in _fr:
            assert _fnt[_now] and _fot[_was], (_fo, _fn, _fr)
        _used = Counter([w for w, _ in _fr] + _fg)
        for _txt in _fot:
            assert _used[_txt] == max(0, _fot[_txt] - _fnt[_txt]), \
                (_fo, _fn, _fr, _fg, _txt)
        _fnf = [h for h in _fn if h[2].strip()]
        for _was, _now, _slot in heading_pairs(_fo, _fn)[0]:
            assert 0 <= _slot < len(_fnf) and _fnf[_slot][2].strip() == _now, \
                (_fo, _fn, _slot, _now)

    assert heading_moves(
        [(0, 1, "Title"), (4, 2, "Setup"), (8, 3, "Keys")],
        [(0, 1, "Title"), (4, 3, "Credentials"),
         (8, 2, "Getting started")]) == (
             [("Setup", "Getting started"), ("Keys", "Credentials")], []), \
        heading_moves([(0, 1, "Title"), (4, 2, "Setup"), (8, 3, "Keys")],
                      [(0, 1, "Title"), (4, 3, "Credentials"),
                       (8, 2, "Getting started")])

    _o.write_text("# T\n\nThe timeout is 1.5 seconds.\n\nA ref to OPS-4118.\n")
    _norm = "# T\n\nThe timeout is short.\n\nA ref to OPS-4118.\n"
    assert _ver(_norm, ["OPS-4118"]) == (1, True), _ver(_norm, ["OPS-4118"])

    def _thin_ver(before, edited):
        _o.write_text(before)
        _n.write_text(edited)
        buf = _io.StringIO()
        with _cl.redirect_stdout(buf):
            rc = cmd_verify(argparse.Namespace(
                original=str(_o), edited=str(_n), chat=False,
                content_edit=False, exempt=[]))
        return rc, buf.getvalue()

    _four = ("# T\n\nINS-1112 opened it. INS-1112 tracked it. INS-1112 "
             "escalated it. INS-1112 closed it.\n")
    _rc, _txt = _thin_ver(_four, "# T\n\nINS-1112 closed it.\n")
    assert "thinned" in _txt, _txt
    assert "INS-1112 4→1" in _txt, _txt
    assert "TOKENS LOST" not in _txt, _txt
    assert "FAIL — fix the blocks above" not in _txt, _txt
    assert _rc != 1, (_rc, _txt)

    _four_url = ("# T\n\nSee https://example.com/x here. Also "
                 "https://example.com/x there. Check https://example.com/x "
                 "again. Confirm https://example.com/x now.\n")
    _rc, _txt = _thin_ver(_four_url, "# T\n\nAll gone now.\n")
    assert "TOKENS LOST" in _txt, _txt
    assert "example.com" in _txt, _txt
    assert "thinned" not in _txt, _txt
    assert _rc == 1, (_rc, _txt)

    _secs4 = ("# T\n\nThe timeout is 1.5 seconds. Again, 1.5 seconds. Still "
              "1.5 seconds. Finally 1.5 seconds.\n")
    _rc, _txt = _thin_ver(_secs4, "# T\n\nThe timeout is 1.5 seconds once.\n")
    assert "thinned" in _txt, _txt
    assert "1.5s 4→1" in _txt, _txt
    assert "TOKENS LOST" not in _txt, _txt
    assert _rc != 1, (_rc, _txt)

    _two = "Accuracy is 85% and the gate is 85% too."
    _, _, _, _drops = merge([_two], [{"specialist": "noise", "edits": [
        {"line": 1, "old": _two, "new": ""}]}], {1})
    assert len(_drops) == 2, _drops
    assert "[t for _, t in noise_drops]" in inspect.getsource(cmd_run), \
        "run is collapsing the drops to a set again"
    _wrap = ["The counter reached 312 values", "across fixtures/pii.json today."]
    _m, _, _, _wd = merge(_wrap, [{"specialist": "noise", "edits": [
        {"line": 1, "old": _wrap[0],
         "new": "The counter reached 312 values across fixtures/pii.json."},
        {"line": 2, "old": _wrap[1], "new": ""}]}], {1, 2})
    assert _wd, "the line-to-line check stopped recording drops"
    _here = {v for vals in facts("\n".join(_m)).values() for v in vals}
    assert not [t for _, t in _wd if t not in _here], [t for _, t in _wd]
    assert "still_here" in inspect.getsource(cmd_run), \
        "run went back to comparing the old line with the new one"
    assert "Nothing here checked this file for meaning" in src_r, \
        "run no longer says when nothing read it for meaning"
    assert "'#' * h[1]" not in inspect.getsource(cmd_run), \
        "the outline is handing specialists heading markers to copy again"

    def _out(before, edited):
        _o.write_text(before)
        _n.write_text(edited)
        buf = _io.StringIO()
        with _cl.redirect_stdout(buf):
            cmd_verify(argparse.Namespace(original=str(_o), edited=str(_n),
                                          chat=False, content_edit=False,
                                          exempt=[]))
        return buf.getvalue()

    _body = ("body word " * 1400).strip()
    _pre = ("# T\n\nTicket BIQ-1196 owns this.\n\n" + ("pre word " * 64).strip()
            + "\n\n# Findings\n\n" + _body + "\n")
    _sum = ("# T\n\n## Summary\n\n" + ("new word " * 240).strip()
            + "\n\nTicket BIQ-1196 owns this.\n\n" + ("pre word " * 64).strip()
            + "\n\n# Findings\n\n" + _body + "\n")
    _txt = _out(_pre, _sum)
    assert "new words, inside the page" in _txt, _txt
    assert "over a page" not in _txt, _txt
    _short = ("body word " * 450).strip()
    _sp = "# T\n\n# Findings\n\n" + _short + "\n"
    _ss = ("# T\n\n## Summary\n\n" + ("new word " * 240).strip()
           + "\n\n# Findings\n\n" + _short + "\n")
    assert "over a page" in _out(_sp, _ss), _out(_sp, _ss)
    assert summary_cap(1000) < summary_cap(10000), "cap ignores document size"
    assert summary_cap(10 ** 6) == SUMMARY_MAX_WORDS, "cap lost its ceiling"
    assert summary_cap(10) == SUMMARY_MIN_WORDS, "cap lost its floor"
    _big = _sum.replace(("new word " * 240).strip(), ("new word " * 400).strip())
    assert "over a page" in _out(_pre, _big), _out(_pre, _big)
    _o.write_text(_pre); _n.write_text(_big)
    with _cl.redirect_stdout(_io.StringIO()):
        _rc = cmd_verify(argparse.Namespace(original=str(_o), edited=str(_n),
                                            chat=False, content_edit=False,
                                            exempt=[]))
    assert _rc == 3, f"an over-cap summary exited {_rc}"
    _para = "\n\n".join(f"Paragraph {i} says something about the system here."
                        for i in range(1, 75))
    _cp = ("# T\n\n" + _para + "\n\n# Findings\n\n"
           + ("body word " * 500).strip() + "\n")
    _cpd = ("# T\n\n## Summary\n\n" + _para + "\n\n" + _para
            + "\n\n# Findings\n\n" + ("body word " * 500).strip() + "\n")
    assert "over a page" in _out(_cp, _cpd), _out(_cp, _cpd)
    _o.write_text(_pre); _n.write_text(_sum)
    with _cl.redirect_stdout(_io.StringIO()):
        _rc = cmd_verify(argparse.Namespace(original=str(_o), edited=str(_n),
                                            chat=False, content_edit=False,
                                            exempt=[]))
    assert _rc == 3, f"an inherited over-cap opening exited {_rc}"
    _res = ["The threshold is fixed.", "It is 2029 requests."]
    _got, _ap, _rf, _ = merge(_res, [{"specialist": "prose", "lo": 1, "hi": 2,
        "edits": [
            {"line": 1, "old": "DOES NOT MATCH", "new": "The threshold is 2029."},
            {"line": 2, "old": _res[1], "new": ""}]}], {1, 2})
    assert _got == _res, _got
    assert not _ap, _ap
    assert any("half a rewrite" in r[2] for r in _rf), _rf
    _far = ["The threshold is fixed.", "Filler.", "It is 2029 requests."]
    _got, _ap, _rf, _ = merge(_far, [{"specialist": "prose", "lo": 1, "hi": 3,
        "edits": [
            {"line": 1, "old": "DOES NOT MATCH", "new": "The threshold is 2029."},
            {"line": 3, "old": _far[2], "new": ""}]}], {1, 2, 3})
    assert _got == _far, _got
    assert not _ap and any("drops 2029" in r[2] for r in _rf), (_ap, _rf)
    _blk = ["The gate blocks the request. It is enabled by default.",
            "The counter records every block. It resets nightly.",
            "The report lists the blocks. It runs at 06:00."]
    _got, _ap, _rf, _ = merge(list(_blk), [{"specialist": "prose", "lo": 1,
        "hi": 3, "edits": [
            {"line": 1, "old": _blk[0], "new": "The gate blocks the request, on by default."},
            {"line": 2, "old": "STALE", "new": "The counter records every block and resets nightly."},
            {"line": 3, "old": _blk[2], "new": "The report lists the blocks at 06:00."}]}],
        {1, 2, 3})
    assert _got == _blk and not _ap, (_got, _ap)
    assert sum("half a rewrite" in r[2] for r in _rf) == 2, _rf
    _two = [{"specialist": "prose", "lo": 1, "hi": 3, "edits": [
        {"line": 1, "old": _blk[0], "new": "The gate blocks the request, on by default."},
        {"line": 2, "old": "STALE", "new": "The counter records every block and resets nightly."},
        {"line": 3, "old": _blk[2], "new": "The report lists the blocks at 06:00."}]}
        for _ in range(2)]
    _got, _ap, _rf, _ = merge(list(_blk), _two, {1, 2, 3})
    assert _got == _blk and not _ap, (_got, _ap)
    assert len(_rf) == 6, _rf
    _wrap = ["The retry runs on a schedule. The gate refuses an edit that would",
             "drop a fact the reader cannot recover from anywhere else in",
             "the document. Operators must be told when that happens."]
    _got, _ap, _rf, _ = merge(_wrap, [{"specialist": "prose", "lo": 1, "hi": 3,
        "edits": [
            {"line": 1, "old": _wrap[0],
             "new": "The gate refuses an edit that drops a fact."},
            {"line": 2, "old": _wrap[1], "new": ""},
            {"line": 3, "old": _wrap[2], "new": ""}]}], {1, 2, 3})
    assert _got == _wrap and not _ap, _got
    assert any("The retry runs on a schedule." in r[2] for r in _rf), _rf
    _fold = ["The threshold is fixed.", "It is 2029 requests."]
    _got, _ap, _, _ = merge(_fold, [{"specialist": "prose", "lo": 1, "hi": 2,
        "edits": [
            {"line": 1, "old": _fold[0],
             "new": "The threshold is 2029 requests."},
            {"line": 2, "old": _fold[1], "new": ""}]}], {1, 2})
    assert _got == ["The threshold is 2029 requests."], _got
    _chat = ["hi all", "", "Context: as discussed, the gate went red.", "",
             "the flaky rate is 4% and the EX metric sits at 69.0%."]
    _got, _ap, _rf, _ = merge(_chat, [{"specialist": "chat", "lo": 1, "hi": 5,
        "edits": [
            {"line": 1, "old": _chat[0], "new": ""},
            {"line": 3, "old": _chat[2],
             "new": "the release gate went red."}]}], set(range(1, 6)))
    assert _got[0] == "The release gate went red.", _got
    assert len(_ap) == 2 and not _rf, (_ap, _rf)

    _seam = ["some text", "the rule can collide with a real address."]
    _got, _ap, _rf, _ = merge(_seam, [{"specialist": "summary", "lo": 1, "hi": 2,
        "edits": [{"op": "insert", "line": 2, "old": "",
                   "new": "Read this first. The rule can collide"}]}], {1, 2})
    assert not _ap and any("both sides" in r[2] for r in _rf), (_ap, _rf)
    _pt = ["# Overview", "", "the cost sits here (overview) for now."]
    _got, _ap, _rf, _ = merge(_pt, [
        {"specialist": "structure", "lo": 1, "hi": 3,
         "edits": [{"line": 1, "old": "# Overview", "new": "# Costs"}]},
        {"specialist": "summary", "lo": 1, "hi": 3,
         "edits": [{"line": 3, "old": _pt[2],
                    "new": "the cost sits here (overview)."}]}],
        {1, 3}, (), [(0, 1, "Overview")])
    assert any("renamed by another specialist" in r[2] for r in _rf), _rf
    _sw = ["# Doc", "", "Every gate copies the digest.", ""]
    _got, _ap, _rf, _ = merge(list(_sw), [
        {"specialist": "prose", "lo": 1, "hi": 4,
         "edits": [{"op": "replace", "line": 3, "old": _sw[2],
                    "new": "No gate copies the digest."}]}],
        {1, 3}, (), [(0, 1, "Doc")])
    assert not _ap and len(_rf) == 1, (_ap, _rf)
    assert "`Every` -> `No`" in _rf[0][2] and "a quantifier" in _rf[0][2], _rf
    _sw2 = ["# Doc", "", "The parser stays open.", ""]
    _got, _ap, _rf, _ = merge(list(_sw2), [
        {"specialist": "prose", "lo": 1, "hi": 4,
         "edits": [{"op": "replace", "line": 3, "old": _sw2[2],
                    "new": "The parser remains open."}]}],
        {1, 3}, (), [(0, 1, "Doc")])
    assert not _ap and len(_rf) == 1, (_ap, _rf)
    assert "`stays` -> `remains`" in _rf[0][2], _rf
    assert "longer one that says the same thing" in _rf[0][2], _rf
    _got, _ap, _rf, _ = merge(
        ["# Doc", "", "It is worth noting that the parser stays open.", ""],
        [{"specialist": "prose", "lo": 1, "hi": 4,
          "edits": [{"op": "replace", "line": 3,
                     "old": "It is worth noting that the parser stays open.",
                     "new": "The parser stays open."}]}],
        {1, 3}, (), [(0, 1, "Doc")])
    assert _ap and not _rf, (_ap, _rf)
    assert output_line(["a", "", "the reworded", "line is", "here."],
                       "the reworded line is here.") == 3
    assert output_line(["a", "", "something else."], "the parser is shut") \
        is None, "a not-found output line must be None, never a guess"
    assert output_line(["x.", "", "x."], "x.") is None, \
        "an ambiguous match must be None rather than the first occurrence"
    _wsa = [(3, "prose", "replace", ("the parser is open",
                                     "the parser is shut"))]
    assert "line_out" not in word_swaps(_wsa)[0], \
        "the field must be ABSENT when there was no output to look in"
    assert word_swaps(_wsa, ["", "", "the parser is shut"])[0]["line_out"] == 3
    _tb = ["# T", "", "| Column | Result |", "| :--- | :--- |",
           "| Atlas | good |", "", "some prose here."]
    _got, _ap, _rf, _ = merge(_tb, [{"specialist": "summary", "lo": 1, "hi": 7,
        "edits": [{"line": 3, "old": _tb[2], "new": ""},
                  {"line": 5, "old": _tb[4], "new": ""}]}], {3, 5, 7})
    assert not _ap and len(_rf) == 2, (_ap, _rf)
    assert "header row" in _rf[0][2] and "last row" in _rf[1][2], _rf
    assert orphan_separators("\n".join(_tb[:2] + _tb[3:])) == [3]
    assert not orphan_separators("\n".join(_tb))
    _rag = "| a | b | c |\n|---|---|---|\n| one | two | three |\n"
    assert not ragged_rows(_rag), ragged_rows(_rag)
    assert not separatorless_tables(_rag)
    assert separatorless_tables(_rag.replace("|---|---|---|\n", "")) == [1]
    assert not separatorless_tables("| just the one |")
    assert not separatorless_tables("```\n| a | b |\n| c | d |\n```")
    assert ragged_rows(_rag.replace("| one | two | three |",
                                    "| one, then two | three |")) \
        == [(3, 2, 3)], ragged_rows(_rag.replace("| one | two | three |",
                                                 "| one, then two | three |"))
    _t_o = "# T\n\n| a | b |\n| --- | --- |\n| 1 |\n\n| c | d |\n| --- | --- |\n| 3 | 4 |\n"
    _t_n = "# T\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n| c | d |\n| --- | --- |\n| 3 |\n"
    assert newly_broken([l for l, _, _ in ragged_rows(_t_o)],
                        [l for l, _, _ in ragged_rows(_t_n)], _t_o, _t_n), \
        "a table broken by the edit hides behind one the edit fixed"
    _t_f = "# T\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n| c | d |\n| --- | --- |\n| 3 | 4 |\n"
    assert not newly_broken([l for l, _, _ in ragged_rows(_t_o)],
                            [l for l, _, _ in ragged_rows(_t_f)], _t_o, _t_f)
    assert not newly_broken([l for l, _, _ in ragged_rows(_t_o)],
                            [l for l, _, _ in ragged_rows(_t_o)], _t_o, _t_o)
    assert not broken_tables(_rag)
    _bt = broken_tables(_rag.replace("|---|---|---|\n", "")
                        + "\n| x | y |\n|---|---|\n| one |\n")
    assert [l for l, _ in _bt] == [1, 6], _bt
    assert "no separator row" in _bt[0][1] and "1 cells" in _bt[1][1], _bt
    assert row_cells("| `a|b` | c |") == 2, row_cells("| `a|b` | c |")
    assert row_cells(r"| a \| b | c |") == 2, row_cells(r"| a \| b | c |")
    _, _, _rf, _ = merge(_tb, [{"specialist": "prose", "lo": 1, "hi": 7,
        "edits": [{"line": 4, "old": _tb[3], "new": "| :-- | :-- |"}]}], {3, 5, 7})
    assert "table separator row" in _rf[0][2], _rf
    _got, _ap, _rf, _ = merge(_tb, [{"specialist": "prose", "lo": 1, "hi": 7,
        "edits": [{"line": 3, "old": _tb[2], "new": "| Ran | Result |"},
                  {"line": 4, "old": _tb[3], "new": "| :-- | :-- |"},
                  {"line": 5, "old": _tb[4], "new": "| Atlas | ok |"}]}],
        {3, 5, 7})
    assert sorted(a[0] for a in _ap) == [3, 5], (_ap, _rf)
    assert len(_rf) == 1 and "table separator row" in _rf[0][2], _rf
    _mk = ("# T\n\nCRITICAL INFO FOR AGENTS: keep the retry loop,\n"
           "it handles the 429 from upstream.\n\n"
           "The release is flaky.  <!-- kv:keep -->\n").split("\n")
    _mp, _mh, _mt, _mq = mask("\n".join(_mk))
    _, _, _rf, _ = merge(_mk, [{"specialist": "prose", "edits": [
        {"line": n, "old": _mk[n - 1], "new": "reworded"} for n in (3, 4, 6)]}],
        editable_lines(_mp, _mt, _mh, _mq), (), _mh)
    assert [w for _, _, w in _rf] == [
        "protected by CRITICAL INFO FOR AGENTS",
        "protected by the CRITICAL INFO FOR AGENTS line above",
        "protected by kv:keep"], _rf
    _fz = ("# T\n\n## NOTE FOR AGENTS\n\nKeep every rule below.\n\n"
           "## Body\n\nThe release is flaky.\n").split("\n")
    _fp, _fh, _ft, _fq = mask("\n".join(_fz))
    _, _fa, _rf, _ = merge(_fz, [{"specialist": "prose", "edits": [
        {"line": n, "old": _fz[n - 1], "new": "Reworded."} for n in (5, 9)]}],
        editable_lines(_fp, _ft, _fh, _fq), (), _fh)
    assert [a[0] for a in _fa] == [9], _fa
    assert [(l, w) for l, _, w in _rf] == [
        (5, "line is inside a section marked do-not-edit")], _rf
    _shift = "# T\n\nsome text\n\nthe rule can collide\ncollide with the rest.\n"
    assert "DUPLICATED TAIL" not in _out(
        _shift, _shift.replace("# T\n\n", "# T\n\nADDED LINE\n\n", 1)), \
        "a shifted pre-existing duplicate reads as new"
    assert re.search(r"body \d+ → \d+ .*opening summary 0 → ", _txt), _txt
    _p1 = ("# T\n\n## Summary\n\n" + ("sum word " * 180).strip()
           + "\n\n# Findings\n\n" + ("body word " * 450).strip() + "\n")
    _p2 = _p1.replace(("body word " * 450).strip(),
                      ("body word " * 448).strip())
    _txt2 = _out(_p1, _p2)
    assert "opening summary 360 → 360 (0 new, 360 already in the file)" in _txt2, \
        _txt2
    assert "body 906 → 902 (-4)" in _txt2, _txt2
    assert "SUMMARY LOST" not in _txt2, _txt2
    _pr1 = ("# T\n\n" + "The loop runs twice and files the result. " * 22
            + "\n\n## Findings\n\n" + ("body word " * 450).strip() + "\n")
    _pr2 = _pr1.replace("# T\n\n", "# T\n\n## Summary\n\n", 1)
    _txt4 = _out(_pr1, _pr2)
    assert "promoted, no new prose" in _txt4, _txt4
    assert "scores zero for the summary" in _txt4, _txt4
    _pr3 = _pr2.replace("## Summary\n\n",
                        "## Summary\n\nRetries are capped at 45 seconds "
                        "and the queue drains first.\n\n", 1)
    _txt5 = _out(_pr1, _pr3)
    assert "promoted, no new prose" not in _txt5, _txt5
    _rl = ("The implementer must never merge a change without the reviewer "
           "signing the diff first.")
    _rl2 = ("The implementer must never merge a change until the reviewer has "
            "signed the diff.")
    _re1 = ("# T\n\n" + "The loop runs twice and files the result. " * 20
            + "\n" + _rl + "\n\n## Findings\n\n"
            + ("body word " * 450).strip() + "\n")
    _re2 = _re1.replace("# T\n\n", "# T\n\n## Summary\n\n", 1).replace(_rl, _rl2)
    assert "changed section" not in _out(_re1, _re2), _out(_re1, _re2)
    _ro_p = ["# T", "", "## Findings", "", _rl, "", "## Other", "", "Tail."]
    _rn_p = ["# T", "", "## Findings", "", "Tail.", "", "## Other", "", _rl2]
    _ro_h = [(0, 1, "T"), (2, 2, "Findings"), (6, 2, "Other")]
    assert claims_lost(_ro_p, _rn_p, set(), _ro_h, _ro_h)[3], \
        "a rule that changed section is no longer reported"
    _rn_i = ["# T", "", "## Summary", "", "Tail.", "", "## Other", "", _rl2]
    _rn_h = [(0, 1, "T"), (2, 2, "Summary"), (6, 2, "Other")]
    assert claims_lost(_ro_p, _rn_i, set(), _ro_h, _rn_h)[3], \
        "an inserted heading now excuses a rule that really moved"
    _nom = ("# T\n\nThe release is flaky today and the team should look at it "
            "soon.\nIt is important to note that the retry loop saves us here.\n")
    _txt3 = _out(_nom, _nom.replace("soon.\n", "soon.  <!-- kv:keep -->\n"))
    assert "NEW LONG SENTENCES" not in _txt3, _txt3
    assert re.search(r"words (\d+) → \1 \(\+0\)", _txt3), _txt3
    _lng = ("Uh, this is the first stage of this initiative, so it lands in "
            "Jira and the team picks it up from the backlog in the usual way "
            "once the intake call has actually happened.")
    _tr = "Andrzej Figas\n\n###### 00:00 - 04:30\n\n" + _lng + "\n"
    _txt4 = _out(_tr, "## Summary\n\nShort opener.\n\n" + _tr)
    assert "NEW LONG SENTENCES" not in _txt4, _txt4
    _txt5 = _out(_tr, _tr + "\nEvery retained artefact must be catalogued by "
                            "owner, region and lawful basis before any "
                            "downstream consumer may query against it under "
                            "the agreed retention window, whichever of those "
                            "two dates happens to fall earlier.\n")
    assert "NEW LONG SENTENCES" in _txt5, _txt5
    _gb = "\n".join(f"Body sentence number {i} carries a fact worth keeping."
                    for i in range(1, 120))
    _go = "# D\n\n## Evidence for each finding\n\n" + _gb + "\n"
    _gn = ("# D\n\n## Summary\n\nSix issues (SQL execution-control findings)\n"
           "and a data loss prevention (DLP) gap sit in\n"
           "(Evidence for each finding).\n\n## Evidence for each finding\n\n"
           + _gb + "\n")
    _txt6 = _out(_go, _gn)
    assert "(SQL execution-control findings)" in _txt6, _txt6
    assert "(DLP)" not in _txt6 and "(Evidence for each" not in _txt6, _txt6
    def _capped(before, edited, full):
        _fo, _fn = Path(_d) / "cap.md", Path(_d) / "cap.kv.md"
        _fo.write_text(before)
        _fn.write_text(edited)
        global SHOW_ALL
        _was = SHOW_ALL
        SHOW_ALL = full
        buf = _io.StringIO()
        try:
            with _cl.redirect_stdout(buf), _cl.redirect_stderr(buf):
                _rc = cmd_verify(argparse.Namespace(
                    original=str(_fo), edited=str(_fn), chat=False,
                    content_edit=False, exempt=[]))
        finally:
            SHOW_ALL = _was
        return _rc, buf.getvalue()

    _fail_pair = ("# T\n\n" + "\n".join(
        f"Step {i} calls `svc-{i}.example.com/api/v{i}` before the retry."
        for i in range(1, 13)) + "\n",
        "# T\n\n" + "\n".join(
            f"Step {i} runs before the retry." for i in range(1, 13)) + "\n")
    _rev_pair = ("# T\n\n## Rollout\n\nThe deploy waits for the health "
                 "check.\nIt is worth noting that the wait is fifteen "
                 "seconds.\n",
                 "# T\n\nThe deploy waits for the health check.\n")
    _pass_pair = ("# T\n\nIt is worth noting that the deploy waits for the "
                  "health check.\n",
                  "# T\n\nThe deploy waits for the health check.\n")
    _seen = set()
    for _o_, _n_ in (_fail_pair, _rev_pair, _pass_pair):
        _short_rc, _short = _capped(_o_, _n_, False)
        _full_rc, _fulltxt = _capped(_o_, _n_, True)
        assert _short_rc == _full_rc, (_short_rc, _full_rc, _short, _fulltxt)
        _seen.add(_short_rc)
    assert _seen == {0, 1, 3}, f"the pairs reach {sorted(_seen)}, not 0/1/3"
    _short_rc, _short = _capped(*_fail_pair, False)
    _full_rc, _fulltxt = _capped(*_fail_pair, True)
    assert "showing" in _short, _short
    assert "showing" not in _fulltxt, _fulltxt
    assert len(_fulltxt) > len(_short), (len(_fulltxt), len(_short))
    _ver = version_line()
    _vlines = _ver.splitlines()
    assert len(_vlines) == 2, _ver
    assert _vlines[0].startswith("kill-verbosity build "), _ver
    assert _vlines[0].rstrip().endswith("hashed from:"), _ver
    assert Path(_vlines[1]).is_file(), _ver
    assert Path(_vlines[1]).is_absolute(), _ver
    assert build_id().split()[0] == \
        hashlib.sha256(Path(_vlines[1]).read_bytes()).hexdigest()[:8], _ver
    assert any("--version" in a.option_strings for a in build_parser()._actions), \
        "--version is handled but not registered, so --help does not list it"
    _argv, _cols = sys.argv, os.environ.get("COLUMNS")
    sys.argv = ["kill-verbosity", "--version"]
    os.environ["COLUMNS"] = "60"
    _vbuf = _io.StringIO()
    try:
        with _cl.redirect_stdout(_vbuf):
            _vrc = main()
    except SystemExit as _e:
        _vrc = _e.code
    finally:
        sys.argv = _argv
        os.environ.pop("COLUMNS") if _cols is None else \
            os.environ.__setitem__("COLUMNS", _cols)
    assert _vrc == 0, _vrc
    assert _vbuf.getvalue().strip() == _ver.strip(), \
        (f"`--version` prints {_vbuf.getvalue()!r}, version_line() returns "
         f"{_ver!r} — the flag is wired to something else")
    assert len(_vbuf.getvalue().strip().splitlines()) == 2, \
        f"`--version` wrapped at 60 columns: {_vbuf.getvalue()!r}"
    _rbo = ("# Deploy runbook\n\n"
            "The service is deployed behind a feature flag. Rollback is "
            "manual.\nTraffic moves in three stages. The shift is not "
            "automatic.\n")
    _rbn = ("# Deploy runbook\n\n"
            "The service is deployed behind a feature flag.\n"
            "Traffic moves in three stages.\n")
    for _s in ("Rollback is manual.", "The shift is not automatic."):
        assert not CLAIM_RULE.search(_s), \
            f"{_s!r} is now a held rule — this case no longer tests the gap"
    _rbtxt = _out(_rbo, _rbn)
    assert "PASS" in _rbtxt, _rbtxt
    assert "Read the diff for meaning" in _rbtxt, _rbtxt
    assert "Compared:" in _rbtxt, _rbtxt
    assert "every token and every claim survived" not in _rbtxt, _rbtxt
    _ado = ["alpha out.csv here", "beta", "gamma"]
    _adrep = "TOKENS ADDED — 1 thing\n  code (1): out.csv\n"
    _adtxt = ip_render("\n".join(_ado), "alpha out.csv here\ngamma", _adrep)
    assert "could not place" in _adtxt and "L1" not in _adtxt, _adtxt
    _adtxt2 = ip_render("\n".join(_ado),
                        "alpha out.csv here\nbeta\nnew line with out.csv\ngamma",
                        _adrep)
    assert "could not place" not in _adtxt2, _adtxt2
    assert "+ L3" in _adtxt2 and "← ADDED out.csv" in _adtxt2, _adtxt2
    _ipo = ["# T", "", "Call `svc.example.com` before the retry.", ""]
    _ipe = ["# T", "", "Call before the retry.", ""]
    _sentence = ("Nothing here checked this file for meaning, and every gate "
                 "above matches text — so a reversed sentence would have "
                 "passed all of them without a word being lost.")
    _rep = (f"{_sentence}\n"
            "  code (1): svc.example.com\n"
            "TOKENS LOST — 1 protected token went\n"
            "  code (1): svc.example.com\n")
    _on, _en, _lostip = ip_parse(_rep, _ipo, _ipe)
    _tags = sorted({t for v in list(_on.values()) + list(_en.values())
                    for t in v})
    assert _sentence[:40] not in " ".join(_tags), _tags
    assert _tags == ["token svc.example.com"], _tags
    assert ip_kind(_tags[0]) == "token", _tags
    _vtree = ast.parse(textwrap.dedent(inspect.getsource(cmd_verify)))

    def _fb_name(node):
        """The block name of a `_failed_block("X")` call, else None."""
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_failed_block" and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            return node.args[0].value
        return None

    _hardnames = [n for n in map(_fb_name, ast.walk(_vtree)) if n is not None]
    _hardassigned = [n for n in
                     (_fb_name(nd.value) for nd in ast.walk(_vtree)
                      if isinstance(nd, ast.Assign))
                     if n is not None]
    _resid = ('def _f(a):\n'
              '    """quotes _failed_block("DOC") for the reader."""\n'
              '    hard = _failed_block("REAL")  # _failed_block("TRAIL")\n'
              '    s = \'names _failed_block("STR")\'\n'
              '    return hard, s\n')
    _resid_ast = [n for n in map(_fb_name, ast.walk(ast.parse(_resid)))
                  if n is not None]
    assert _resid_ast == ["REAL"], (
        "the census counts something that is not a call site: %s" % _resid_ast)
    assert len(re.findall(r'_failed_block\(\s*"([^"]+)"\s*\)',
                          "\n".join(l for l in _resid.splitlines()
                                    if not l.strip().startswith("#")))) == 4, \
        ("the fixture no longer carries the residue the AST walk exists to "
         "drop, so the assertion above holds nothing")
    assert len(_hardassigned) == len(_hardnames), (
        "a `_failed_block(...)` result is not assigned to `hard`: the block is "
        "named in the FAIL verdict but the run still passes. %d call(s) vs %d "
        "assignment(s): %s" % (len(_hardnames), len(_hardassigned),
                               sorted(set(_hardnames) - set(_hardassigned))))
    assert len(_hardnames) == 20, (
        "cmd_verify records %d failing blocks, expected 20 — if a blocking "
        "block was added or retired on purpose, move the number in the same "
        "commit: %s" % (len(_hardnames), _hardnames))
    _vsrc = inspect.getsource(cmd_verify)
    assert _vsrc.count("            if hard_blocks:\n") == 1, \
        "the FAIL verdict's two arms moved; the check below anchors on one"
    assert "no block recorded itself" in _vsrc.split(
        "            if hard_blocks:\n")[1].split("        return 1")[0], \
        "an empty hard_blocks must be said in words, not printed as a gap"
    for _hn in _hardnames:
        assert _hn in IP_SHORT, (
            "the FAIL verdict can name %r, which is not a block name "
            "IP_SHORT knows — the verdict and the blocks would be naming "
            "different things" % _hn)

    for _nm in sorted(IP_SHORT) + sorted(IP_SKIP):
        assert len(_nm) <= IP_NAME_MAX, \
            f"block name {_nm!r} is {len(_nm)} chars, over IP_NAME_MAX"
        _side = 1 if _nm in IP_EDIT_SIDE else 0
        _one = ip_parse(f"{_nm} — 1 thing\n  L3 something\n", _ipo, _ipe)[_side]
        assert _one.get(3) == [IP_SHORT.get(_nm, _nm)] or _nm in IP_SKIP, \
            f"the guard drops the real block name {_nm!r}"
        _bare = ip_parse(f"{_nm}: 1 run of words. Read those lines against "
                         f"the original.\n  L3 x\n", _ipo, _ipe)[_side]
        assert _bare.get(3) == [IP_SHORT.get(_nm, _nm)] or _nm in IP_SKIP, \
            "a known block name is dropped when its headline is a sentence"
    _rep = ("text the edit repeated: 1 run of words the edit says more often "
            "than the original did (lines 2). Read those lines against the "
            "original.\n  no run of these words in the original, the edit "
            "has 2: the tail\n")
    assert ip_parse(_rep, _ipo, _ipe)[1] == {2: ["repeated"]}, \
        "a block that states its lines in the headline places nowhere"
    _rep2 = ("text the edit repeated: 2 runs (lines 1, 2; 3 (4 texts)).\n"
             "  no run of these words in the original, the edit has 2: aaa\n"
             "  the original had 1, the edit has 3: bbb\n")
    assert ip_parse(_rep2, _ipo, _ipe)[1] == {
        1: ["repeated"], 2: ["repeated"], 3: ["repeated"]}, \
        "a headline count is being read as a line number, or rows duplicate"
    _both = ip_parse("RULES LOST — 1 rule (lines 1, 2).\n  L3 something\n",
                     _ipo, _ipe)[0]
    assert _both == {3: ["RULE"]}, \
        f"a row with its own L3 also took the headline's lines: {_both}"
    _nowhere = ip_parse("content dropped — 1 thing\n  nowhere in either\n",
                        _ipo, _ipe)
    assert _nowhere[2] == ["dropped: nowhere in either"], \
        f"an unplaceable row vanished instead of being reported: {_nowhere}"
    assert ip_parse(f"{_sentence}\n  L3 x\n", _ipo, _ipe)[0] == {}, \
        "a stray column-0 sentence is being read as a block again"
    _stats = ("shapes 2 → 0 (0 new shapes, 0 carried over) · long sentences "
              "0 → 0 (0 new) · words 268 → 30 (-238)")
    assert ip_parse(f"{_stats}\n  L3 something\n", _ipo, _ipe)[0] == {}, \
        "the stats line is still being read as a block"
    _emit = inspect.getsource(cmd_verify)
    assert "new shape{'' if len(introduced) == 1 else 's'}" in _emit \
        and "({len(new_long)} new) · " in _emit, \
        "the stats line no longer names the population of each count"
    _wrapo = ["# T", "",
              "The retry budget is `45s` per call and the deploy",
              "waits for `svc.example.com` before it proceeds.", ""]
    _wrape = ["# T", "", "The deploy waits.", ""]
    _tally = ip_render("\n".join(_wrapo), "\n".join(_wrape),
                       "TOKENS LOST — 2 protected tokens went\n"
                       "  code (2): 45s, svc.example.com\n")
    assert "lines carry a finding" in _tally, _tally
    assert "findings in" not in _tally, _tally
    assert _tally.startswith("2 lines carry a finding") or \
        "\n2 lines carry a finding" in _tally, _tally
    assert positive_int("4") == 4
    for _bad in ("0", "-3", "abc"):
        try:
            positive_int(_bad)
            raise AssertionError(f"{_bad!r} accepted")
        except argparse.ArgumentTypeError:
            pass
    _ai, _ao = Path(_d) / "acc.md", Path(_d) / "acc.kv.md"
    _ai.write_text("# T\n\nThe gate is 85% today.\n")
    _ao.write_text("# T\n\nThe gate is 85%.\n")
    write_run_record(_ao, incomplete=["prose lines 2-3"])

    def _acc(force):
        buf = _io.StringIO()
        was = os.environ.get("KV_FORCE")
        os.environ["KV_FORCE"] = "1" if force else "0"
        try:
            with _cl.redirect_stdout(buf), _cl.redirect_stderr(buf):
                rc = cmd_accept(argparse.Namespace(
                    file=str(_ai), edited=str(_ao), chat=False))
        finally:
            os.environ.pop("KV_FORCE") if was is None else \
                os.environ.__setitem__("KV_FORCE", was)
        return rc, buf.getvalue()

    _rc, _msg = _acc(False)
    assert _rc == 1 and "incomplete" in _msg, (_rc, _msg)
    assert _ai.read_text().endswith("85% today.\n"), "input was written anyway"
    _frc, _fmsg = _acc(True)
    assert _frc == 4, (_frc, _fmsg)
    assert "KV_FORCE overruled" in _fmsg, _fmsg
    assert "unedited" in _fmsg, _fmsg
    assert _ai.read_text().endswith("85%.\n"), "forced accept did not write"
    _ai.write_text("# T\n\nThe gate is 85% today.\n")
    _ao.write_text("# T\n\nThe gate is 85%.\n")
    run_record_path(_ao).unlink(missing_ok=True)
    _nrc, _nmsg = _acc(True)
    assert _nrc == 4, (_nrc, _nmsg)
    assert "no run record" in _nmsg, _nmsg
    assert _acc(False)[0] == 1, "a missing record must still refuse"
    _ri, _ro = Path(_d) / "rev.md", Path(_d) / "rev.kv.md"
    _ri.write_text("# T\n\nThe room was warm and the window faced the garden, "
                   "and the afternoon went by slowly.\n")
    _ro.write_text("# T\n\nThe room was warm.\n")
    write_run_record(_ro)
    _buf = _io.StringIO()
    with _cl.redirect_stdout(_buf), _cl.redirect_stderr(_buf):
        _rrc = cmd_accept(argparse.Namespace(file=str(_ri), edited=str(_ro),
                                             chat=False))
    _rmsg = _buf.getvalue()
    assert "REVIEW" in _rmsg, f"the review path was not taken: {_rmsg}"
    _last = [l for l in _rmsg.strip().splitlines() if l.strip()][-1]
    assert "unanswered" in _last and "already replaced" in _last, \
        f"the review trailer is not the last line a tail reader sees: {_last!r}"
    _ci, _co = Path(_d) / "cln.md", Path(_d) / "cln.kv.md"
    _ci.write_text("# T\n\nThe room was warm and the window faced the garden.\n")
    _co.write_text("# T\n\nThe room was warm and the window faced the garden.\n")
    write_run_record(_co)
    _cbuf = _io.StringIO()
    with _cl.redirect_stdout(_cbuf), _cl.redirect_stderr(_cbuf):
        _crc = cmd_accept(argparse.Namespace(file=str(_ci), edited=str(_co),
                                             chat=False))
    assert _crc == 0 and "PASS" in _cbuf.getvalue(), \
        f"the control never reached a clean accept: {_crc} {_cbuf.getvalue()}"
    assert "unanswered" not in _cbuf.getvalue(), \
        f"the review trailer fires on an accept with nothing to answer:\n{_cbuf.getvalue()}"

    _wrapped = "# T\n\nThe rule holds. An invented part can collide\nwith a real address.\n"
    _smashed = ("# T\n\nThe rule holds. An invented part can collide\n"
                "An invented part can collide, and it is worth noting that "
                "this is by chance.\n")
    _txt = _out(_wrapped, _smashed)
    assert "DUPLICATED TAIL" in _txt, _txt
    assert "already reported broken above" in _txt, _txt
    _clean = "# T\n\nThe rule holds. It is worth noting that this is by chance.\n"
    _ct = _out(_wrapped, _clean)
    assert "SHAPES INTRODUCED" in _ct and "already reported broken" not in _ct, _ct

    assert not find_shapes(["The report is not generated when input is empty."])
    assert find_shapes(["This section is not generated yet."])

    assert canon_unit("seconds") == "s" and canon_unit("S") == "s"
    assert canon_unit("MB") == "MB" and canon_unit("mb") == "MB"
    assert canon_unit("ms") == "ms" and canon_unit("mins") == "min"
    assert canon_unit("%") == "" and canon_unit("bananas") == ""
    import tempfile as _tf2
    with _tf2.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh2:
        _fh2.write('{"units": {"add": ["mg", "mcg"]},'
                   ' "unit_canon": {"mg": "mg", "mcg": "mcg"},'
                   ' "unit_family": {"mg": "mass", "mcg": "mass"}}')
    load_profile(_fh2.name)
    assert canon_unit("mg") == "mg", "a profile unit did not canonicalise"
    _inc = inconsistencies("The dose is 500 mg. The dose is 500 mcg.")
    assert any(i.get("units") == ["mcg", "mg"] for i in _inc), \
        f"a profile unit never reached the conflict check: {_inc}"
    reset_profile()
    with _tf2.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh3:
        _fh3.write('{"units": {"add": ["furlong"]},'
                   ' "unit_canon": {"furlong": "fur"},'
                   ' "unit_family": {"fur": ""}}')
    load_profile(_fh3.name)
    assert canon_unit("furlong") == "fur"
    inconsistencies("It ran 5 furlong and 5 furlong.")
    reset_profile()
    assert canon_unit("furlong") == "", "reset kept a profile's unit"
    assert UNIT_FAMILY == DEFAULT_VOCAB["unit_family"], "reset kept a family"

    assert FACT_RX["number"].search("dose 500 mg").group(0) == "500", \
        "mg is not a default unit, so the default build must stop at the digits"
    load_profile(_fh2.name)
    assert FACT_RX["number"].search("dose 500 mg").group(0) == "500 mg", \
        "a profile unit did not reach the protected-token rules"
    reset_profile()
    assert FACT_RX["number"].search("dose 500 mg").group(0) == "500", \
        "reset kept a profile's unit in the protected-token rules"
    assert FACT_RX["path"].search("see notes.md today").group(0) == "notes.md"
    with _tf2.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh4:
        _fh4.write('{"code_ext": ["rtf"]}')
    load_profile(_fh4.name)
    assert not FACT_RX["path"].search("see notes.md today"), \
        "a profile dropped an extension but the path rule kept it"
    assert FACT_RX["path"].search("see notes.rtf today").group(0) == "notes.rtf"
    reset_profile()
    assert FACT_RX["path"].search("see notes.md today").group(0) == "notes.md", \
        "reset kept a profile's extensions in the path rule"
    Path(_fh4.name).unlink()
    Path(_fh2.name).unlink()

    assert SEGMENTED.search("see notes.md"), "the default build lost .md"
    with _tf2.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh5:
        _fh5.write('{"code_ext": ["rtf"]}')
    load_profile(_fh5.name)
    assert not SEGMENTED.search("see notes.md"), \
        "a profile dropped an extension but the segmented rule kept it"
    reset_profile()
    assert SEGMENTED.search("see notes.md"), "reset did not restore .md"
    Path(_fh5.name).unlink()

    assert CLAIM_RULE.search("you must not do that")
    assert CLAIM_RULE.search("nie wolno tego robić"), "pl is live by default"
    assert CLAIM_RULE.search("this is a risk")
    assert CLAIM_RULE.search("to jest ryzyko"), "pl claim words are not read"
    assert ABBR.search("see Fig.") and ABBR.search("owoce, np.")
    with _tf2.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh6:
        _fh6.write('{"langs": ["en"]}')
    load_profile(_fh6.name)
    assert not CLAIM_RULE.search("nie wolno tego robić"), \
        "a profile turned Polish off and the rule mark kept it"
    assert not CLAIM_RULE.search("to jest ryzyko"), \
        "a profile turned Polish off and the claim rule kept it"
    assert not ABBR.search("owoce, np."), \
        "a profile turned Polish off and the abbreviations kept it"
    assert CLAIM_RULE.search("you must not do that"), "English went with it"
    reset_profile()
    assert CLAIM_RULE.search("nie wolno tego robić"), "reset lost Polish"
    Path(_fh6.name).unlink()

    with _tf2.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh7:
        _fh7.write('{"shapes": {"drop": ["colon label"]}}')
    load_profile(_fh7.name)
    assert "colon label" not in CHAT, "a dropped chat shape survived"
    reset_profile()
    assert "colon label" in CHAT, "reset did not put the chat shape back"
    Path(_fh7.name).unlink()

    with _tf2.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh9:
        _fh9.write('{"langs": ["de"], "words": {"de": {'
                   '"summary heading": ["zusammenfassung"],'
                   '"sign-off": ["melde dich"]}}}')
    _partial = load_profile(_fh9.name)
    assert "sign-off" in CHAT, "the one chat shape it gave words for is gone"
    assert "buried lead" not in CHAT, "a shape with no words was still built"
    assert all("buried lead" not in owned for _, owned in SPECIALISTS.values()), \
        "a wordless shape is still claimed by its specialist"
    reset_profile()
    assert "buried lead" in CHAT, "reset did not put the chat shape back"
    Path(_fh9.name).unlink()

    _span_was = MAX_SPAN
    for _cap in (1, 2, 3, 40):
        globals()["MAX_SPAN"] = _cap
        _w = windows(0, 20, breaks=tuple(range(21)))
        assert _w and _w[-1][1] == 20 and all(b >= a for a, b in _w), \
            f"windows() is wrong at a cap of {_cap}: {_w}"
    globals()["MAX_SPAN"] = _span_was
    Path(_fh3.name).unlink()

    def _genre(src):
        _pr, _hd, _tb, _qt = mask(src, "g.md")
        return detect_genre(src.split("\n"), _hd)

    assert _genre("# Call\n\n## 00:00 - 00:41\n\nAna spoke.\n\n"
                  "## 00:41 - 01:20\n\nRavi replied.\n") == "transcript"
    assert _genre("# Log\n\n## 2026-08-01\n\nRolled out.\n\n"
                  "## 2026-07-24\n\nRaised it.\n\n"
                  "## 2026-07-02\n\nFirst deploy.\n") == "log"
    assert _genre("# List\n\n- [ ] bump the chart\n- [x] run it\n"
                  "- [ ] tag it\n- [ ] tell on-call\n") == "checklist"
    assert _genre("# Ref\n\n| F | T |\n|---|---|\n| a | int |\n"
                  "| b | str |\n| c | bool |\n") == "reference"
    _tq = ("# TASKS.md\n\n| # | Task | Prio | Status | Cite |\n"
           "|---|---|---|---|---|\n"
           "| 1 | Fix the retry budget | P1 | open | L12 |\n"
           "| 2 | Update the docs | P2 | done | L40 |\n"
           "| 3 | Add a test | P1 | open | L88 |\n")
    assert _genre(_tq) == "checklist", _genre(_tq)
    assert status_table_note(_tq.split("\n")), \
        "no advisory line for a Status-column table"
    _tq_ctl = _tq.replace("Status", "Notes")
    assert _genre(_tq_ctl) == "reference", _genre(_tq_ctl)
    assert not status_table_note(_tq_ctl.split("\n")), \
        "the advisory fired on a table with no Status/State column"
    assert _genre(_tq.replace("Status", "State")) == "checklist"
    assert not status_table_note(
        _tq.replace("Status", "Current Status Notes").split("\n")), \
        "the advisory fired on a header cell that only mentions status"
    assert _genre("# Rules\n\nNames must be lower case. You must never "
                  "abbreviate.\nHandlers must not swallow errors.\n"
                  "Do not retry a 400.\n") == "prose"
    assert _genre("# P\n\nThe retry loop drops the last error at line 88.\n"
                  "The handler returns None instead of the cause.\n") == "prose"
    assert _genre("") == "prose"
    assert _genre("\n\n\n") == "prose"
    _speech = "".join(f"## 0{i}:00 - 0{i}:30\n\nAna spoke here.\n\n"
                      for i in range(1, 4))
    _essay = "".join(f"## Point {i}\n\nThe retry loop drops the last error "
                     f"and the handler returns None to its caller instead.\n\n"
                     for i in range(1, 9))
    assert _genre("# Call\n\n" + _speech) == "transcript"
    assert _genre("# Call\n\n" + _speech + _essay) == "prose", \
        "a half-transcript still claimed the whole file"
    _pr, _hd, _tb, _qt = mask("# Call\n\n" + _speech + _essay, "g.md")
    _mx = genre_mix(("# Call\n\n" + _speech + _essay).split("\n"), _hd)
    assert _mx["transcript"] == 3 and _mx["prose"] == 8, dict(_mx)
    assert genre_mix(["# A", "", "## B", ""],
                     [(0, 1, "A"), (2, 2, "B")]) == Counter()
    _road = ("# Rollout\n\n## Phase 1 - Discovery\n\nInterview the four "
             "teams and write the brief.\n\n## Phase 2 - Pilot\n\nTwo "
             "squads run it for a month.\n\n## Milestone 3\n\nThe exporter "
             "is wired and the gate is green.\n")
    assert _genre(_road) == "roadmap", _genre(_road)
    _design = ("# Parser\n\n## Phase 2 - Rollout\n\nThe pilot runs in "
               "Q3 2026.\n\n"
               + "".join(f"## Point {i}\n\nThe retry loop drops the last "
                         f"error and the handler returns None to its caller "
                         f"instead.\n\n" for i in range(1, 9)))
    assert _genre(_design) == "prose", _genre(_design)
    _pr, _hd, _tb, _qt = mask(_road, "g.md")
    assert genre_mix(_road.split("\n"), _hd)["roadmap"] == 3, \
        dict(genre_mix(_road.split("\n"), _hd))
    assert _section_genre("2026-08-01 Phase 2", ["shipped it"]) == "log"
    assert _section_genre("Phase 2 - Rollout", ["shipped it"]) == "roadmap"
    assert _section_genre("Phases of the parse", ["a b"]) == "prose"
    assert _section_genre("Q3 revenue", ["a b"]) == "prose"
    assert _section_genre("Week 3", ["ship the exporter"]) == "roadmap"
    assert _section_genre("Q3 2026", ["ship the exporter"]) == "roadmap"
    assert _section_genre("Roadmap", ["ship the exporter"]) == "roadmap"
    assert _section_genre("Timeline: 2026", ["ship it"]) == "roadmap"
    assert _section_genre("Roadmap tooling is out of scope",
                          ["the exporter reads one file"]) == "prose"
    assert _section_genre("Weekly digest", ["the exporter reads it"]) == "prose"
    for _gp in PROFILE_DIR.glob("genre-*.json"):
        assert _gp.stem[len("genre-"):] in GENRES, \
            f"{_gp.name} is named for no genre this build detects"
    for _off in ("genre-roadmap", "genre-checklist", "genre-log"):
        load_profile(str(PROFILE_DIR / f"{_off}.json"))
        assert "planning" not in SPECIALISTS, _off
        assert SWITCHED_OFF.get("planning") == _off, SWITCHED_OFF
        assert not find_shapes(["## Phase 2 - Rollout", "- [ ] wire it"]), \
            f"{_off} left the planning shapes firing"
        reset_profile()
    assert {c for _l, c, _t in find_shapes(["## Phase 2 - Rollout",
                                            "- [ ] wire it"])} == \
        {"phase plan", "task list"}, \
        find_shapes(["## Phase 2 - Rollout", "- [ ] wire it"])
    assert {c for _l, c, _t in find_shapes(["Phase 2 shipped on 2026-08-01."])} \
        == {"phase plan", "worklog"}, \
        find_shapes(["Phase 2 shipped on 2026-08-01."])
    load_profile(str(PROFILE_DIR / "genre-log.json"))
    assert not find_shapes(["Phase 2 shipped on 2026-08-01."]), \
        "genre-log still reports a planning shape inside a log entry"
    reset_profile()
    for _keep in ("genre-reference", "genre-transcript"):
        load_profile(str(PROFILE_DIR / f"{_keep}.json"))
        assert "planning" in SPECIALISTS, \
            f"{_keep} switched `planning` off, which was not decided"
        assert {c for _l, c, _t in find_shapes(["## Phase 2 - Rollout",
                                               "- [ ] wire it"])} == \
            {"phase plan", "task list"}, \
            f"{_keep} lost the planning shapes"
        reset_profile()

    _profs = sorted(PROFILE_DIR.glob("*.json")) if PROFILE_DIR.is_dir() else []
    assert _profs, f"no profiles in {PROFILE_DIR}"
    for _pf in _profs:
        try:
            _name = load_profile(str(_pf))
        except SystemExit as e:
            raise AssertionError(f"{_pf.name} does not load: {e}")
        assert _name, f"{_pf.name} has no name"
        assert find_shapes(["It is worth noting that the result is robust."]), \
            f"{_pf.name} lost the shapes every document shares"
        assert SUMMARY_MIN_WORDS <= summary_cap(5000) <= SUMMARY_MAX_WORDS, \
            f"{_pf.name} has a summary cap outside its own floor and ceiling"
        reset_profile()
    assert find_shapes(["fixed in round-6 per G.3"]), \
        "reset_profile did not put the default id families back"
    assert VOCAB["domain_jargon"] == DEFAULT_VOCAB["domain_jargon"], \
        "reset_profile left a profile's words in place"
    assert THRESHOLDS == DEFAULT_THRESHOLDS, \
        "reset_profile left a profile's thresholds in place"
    import tempfile as _tf0
    with _tf0.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh0:
        _fh0.write('{"shapes": {"drop": ["jargon"]}}')
    load_profile(_fh0.name)
    assert "jargon" not in EXISTENCE, "a dropped shape survived"
    assert "jargon" not in SPECIALISTS["prose"][1], "its owner still claims it"
    assert not find_shapes(["We leveraged a robust paradigm."]), \
        "a dropped shape still fires"
    reset_profile()
    assert "jargon" in EXISTENCE and "jargon" in SPECIALISTS["prose"][1], \
        "reset did not put the dropped shape back"
    Path(_fh0.name).unlink()
    with _tf0.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh1:
        _fh1.write('{"specialists": {"prose": null}}')
    load_profile(_fh1.name)
    assert "prose" not in SPECIALISTS, "a dropped specialist survived"
    assert "long sentence" not in all_shape_names(), \
        "a synthetic shape outlived the specialist that owned it"
    reset_profile()
    assert "prose" in SPECIALISTS and "long sentence" in SYNTHETIC, \
        "reset did not put the dropped specialist back"
    Path(_fh1.name).unlink()

    def _globals_snapshot():
        out = {}
        for k, v in globals().items():
            if k.startswith("__") or callable(v) or isinstance(v, type):
                continue
            if isinstance(v, re.Pattern):
                out[k] = ("rx", v.pattern, v.flags)
            elif isinstance(v, (str, int, float, bool)):
                out[k] = v
            elif isinstance(v, (list, tuple)):
                out[k] = repr(v)
            elif isinstance(v, (set, frozenset)):
                out[k] = repr(sorted(map(str, v)))
            elif isinstance(v, dict):
                out[k] = repr({a: (b.pattern if isinstance(b, re.Pattern) else b)
                               for a, b in v.items()})
        return out

    def _compiled_patterns():
        for k, v in globals().items():
            if isinstance(v, re.Pattern):
                yield k, v.pattern
            elif isinstance(v, dict):
                for a, b in v.items():
                    if isinstance(b, re.Pattern):
                        yield f"{k}[{a!r}]", b.pattern

    _base_globals = _globals_snapshot()
    for _pf in _profs:
        load_profile(str(_pf))
        _moved = [k for k in _base_globals
                  if _base_globals[k] != _globals_snapshot().get(k)]
        assert _moved, f"{_pf.name} changed nothing at all"
        reset_profile()
        _now = _globals_snapshot()
        _gap = sorted(k for k in set(_base_globals) | set(_now)
                      if _base_globals.get(k) != _now.get(k))
        assert not _gap, f"after {_pf.name}, reset left {_gap} changed"

    with _tf0.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh8:
        _fh8.write('{"code_ext": ["zzq"], "units": ["qqz"],'
                   ' "unit_canon": {"qqz": "qqz"}, "unit_family": {"qqz": ""}}')
    load_profile(_fh8.name)
    _stale = sorted({f"{n} still has {w!r}" for n, p in _compiled_patterns()
                     for w in ("toml", "seconds", "GB") if w in p})
    assert not _stale, f"a profile replaced the vocabulary and {_stale}"
    reset_profile()
    assert any("toml" in p for _, p in _compiled_patterns()), \
        "reset did not put the default extensions back"
    Path(_fh8.name).unlink()

    import tempfile as _tf
    for _bad, _why in (
            ('{"thresholds": {"nope": 3}}', "unknown threshold"),
            ('{"thresholds": {"max_span": -1}}', "negative threshold"),
            ('{"nonsense": []}', "unknown key"),
            ('{"filler": {"drop": ["never-there"]}}', "drop that matches nothing"),
            ('{"shapes": {"add": {"x": "([unclosed"}}}', "broken regex"),
            ('{"specialists": {"ghost": {"shapes": []}}}', "specialist with no prompt"),
            ('{"shapes": {"drop": ["no-such-shape"]}}', "dropped a shape that does not exist"),
            ('{"shapes": {"add": {"jargon": "x"}}}', "added a shape that already exists"),
            ('{"shapes": {"add": {"colon label": "x"}}}', "reused a chat shape's name"),
            ('{"shapes": {"add": {"long sentence": "x"}}}', "reused a synthetic shape's name"),
            ('{"specialists": {"noise": null}, "shapes": {"add": {"z": "zz"}}}', "added a shape with no owner"),
            ('{"specialists": {"no-such-one": null}}', "dropped a specialist that does not exist"),
            ('{"langs": ["xx"]}', "a language with no words"),
            ('{"words": {"en": {"not a shape": ["x"]}}}', "words for something that is not a shape"),
            ('not json at all', "not JSON"),
            ('{"thresholds": {"genre_majority": 5}}', "share above 1"),
            ('{"thresholds": {"summary_share": 1.5}}', "share above 1"),
            ('{"thresholds": {"max_span": 12.5}}', "fractional count"),
            ('{"thresholds": ["max_span"]}', "thresholds that is not an object"),
            ('{"shapes": ["jargon"]}', "shapes that is not an object"),
            ('{"specialists": ["prose"]}', "specialists that is not an object"),
            ('{"words": ["en"]}', "words that is not an object"),
            ('{"units": {"add": ["dram"]}, "unit_canon": {"dram": "dr"}}',
             "a unit spelling with no family"),
            ('{"filler": {"add": ["([unclosed"]}}', "a broken vocabulary pattern"),
            ('{"words": {"en": {"sign-off": ["(oops"]}}}',
             "a broken pattern in a word bank"),
    ):
        with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh:
            _fh.write(_bad)
        try:
            load_profile(_fh.name)
            raise AssertionError(f"a profile with a {_why} was accepted")
        except SystemExit:
            pass
        finally:
            reset_profile()
            Path(_fh.name).unlink()

    for _name in SPECIALISTS:
        _pt = specialist_prompt(_name, 4000)
        assert "{{" not in _pt, f"{_name}.md has an unfilled placeholder"
        for _riddle in ("one specialist is exempt",
                        "one specialist has a further op",
                        "other specialists own"):
            assert _riddle not in _pt.lower(), f"{_name}: {_riddle}"
        _unsaid = sorted(_s for _s in INSERT_BLOCKING if _s not in _pt)
        assert not _unsaid, f"{_name} is not told about: {_unsaid}"

    _sp = specialist_prompt("summary", 4000)
    _exempt = sorted(REPORTING_SHAPES & INSERT_BLOCKING)
    assert _exempt, "no reporting exemption exists to document"
    for _e in _exempt:
        assert f"`{_e}`" in _sp, f"{_e} is exempt and summary.md is silent"
    _jargony = ("## Summary\n\nThe team leveraged synergies across the "
                "rollout to deliver the report on Tuesday.\n")
    assert "jargon" in shapes_in(_jargony), "the fixture carries no jargon"
    assert added_shapes(_jargony, _jargony) == [], (
        "an insert carrying jargon is refused, and the floor says it lands")
    assert "You may drop a number, path, ticket or link" in \
        (SPECIALIST_DIR / "noise.md").read_text(), \
        "noise no longer states its own exemption from the fact gate"
    assert '"op": "move"' in (SPECIALIST_DIR / "structure.md").read_text(), \
        "structure no longer states the op only it has"
    _sp = specialist_prompt("summary", 1000)
    assert str(summary_cap(1000)) in _sp, "summary.md lost the live cap"
    assert str(SUMMARY_NEEDED_FROM) in _sp, "summary.md lost the live threshold"
    _summary_md = (SPECIALIST_DIR / "summary.md").read_text().lower()
    _kind_words = {"number": ("number",), "ticket": ("ticket", "identifier"),
                   "url": ("link", "url"), "path": ("path",),
                   "version": ("version",), "code": ("code",),
                   "date": ("date",), "fence_lang": ("code", "fence")}
    _probe = facts("PROJ-1 ./a.md https://x.io v1.2 `f(x)` 40% 2026-01-02"
                   "\n```python\nx=1\n```\n")
    assert set(_probe) <= set(_kind_words), \
        (f"facts() gained {sorted(set(_probe) - set(_kind_words))}: say which "
         f"word names it in summary.md and add it here")
    for _kind in _probe:
        assert any(_w in _summary_md for _w in _kind_words[_kind]), \
            f"summary.md never names {_kind}, so it is not told to keep one"
    assert specialist_prompt("summary", 1000) != specialist_prompt("summary", 9000), \
        "the summary prompt says the same cap whatever the document size"
    _md = ("# Retention review\n\n## Summary\n\n"
           "The export job copies session rows into the warehouse every "
           "night, and each\nrow carries a customer identifier plus one "
           "free-text field nobody owns.\n\n## GDPR-7\n\n"
           "The free-text field is not covered by the retention policy at "
           "`docs/ret.md`.\nIt is worth noting that deleting the parent row "
           "leaves it behind.\n\nSee [the owner section](#owner) for who "
           "signs this off.\n\n## Owner\n\n"
           "Retention for the structured columns is owned by the data "
           "platform team.\n\n| field | owner |\n| --- | --- |\n"
           "| session_id | platform |\n\n> Legal said the structured columns "
           "only.\n\n```\nnot prose -- do not touch\n```\n")
    _ml = _md.split("\n")
    _mp, _mhd, _mtb, _mqt = mask(_md)
    _me = editable_lines(_mp, _mtb, _mhd, _mqt)
    _mq = {l for l, _ in _mqt}
    _msl = next((h[0] + 1 for h in _mhd
                 if SUMMARY_HEADING.match(h[2].strip())), 0)
    _at = {s: i + 1 for i, l in enumerate(_ml) for s in (
        "It is worth noting", "The free-text field is not covered",
        "## Owner", "[the owner section]", "## Summary", "not prose",
        "| session_id", "| --- |", "> Legal said",
        "Retention for the structured", "## GDPR-7") if s in l}
    assert len(_at) == 11, sorted(_at)

    def _one(spec, edits, lo=1, hi=0):
        return [{"specialist": spec, "lo": lo, "hi": hi, "edits": edits}]

    def _same(ln, **kw):
        return dict(line=ln, old=_ml[ln - 1], **kw)

    _diff = [
        ("line-outside", _one("prose", [{"line": None, "old": "x",
                                         "new": "y"}]),
         0, "line is outside the file"),
        ("out-of-span", _one("prose", [_same(_at["It is worth noting"],
                                             new="Short.")], hi=2),
         0, "outside its span (1-2)"),
        ("bad-op", _one("prose", [_same(_at["It is worth noting"], op="zap",
                                        new="Short.")]),
         0, "no such op: 'zap'"),
        ("move-not-mover", _one("prose", [{"line": _at["## Owner"],
                                           "op": "move",
                                           "to": _at["## Summary"]}]),
         0, "only structure may move a section"),
        ("fence", _one("prose", [_same(_at["not prose"], new="x.")]),
         0, "line is a code fence, diagram or blank"),
        ("table-separator", _one("prose", [_same(_at["| --- |"], new="")]),
         0, "line is a table separator row"),
        ("quotation", _one("prose", [_same(_at["> Legal said"],
                                           new="> Legal agreed.")]),
         0, "line is inside a quotation"),
        ("summary-heading", _one("structure", [_same(_at["## Summary"],
                                                     new="## Rollout status")]),
         0, "that is the summary heading — the tool finds the summary by "
            "its name"),
        ("orphan-link", _one("structure", [_same(_at["## Owner"],
                                                 new="## Sign-off")]),
         0, f"renaming this heading breaks the link on line "
            f"{_at['[the owner section]']} — rewrite the link in the same "
            f"reply, or leave the heading"),
        ("old-mismatch", _one("prose", [{"line": _at["It is worth noting"],
                                         "old": "nope", "new": "x."}]),
         0, "`old` does not match the file"),
        ("shape-introduced",
         _one("prose", [_same(_at["Retention for the structured"],
                              new="It is worth noting that the platform team "
                                  "owns it.")]),
         0, "the replacement text has frame"),
        ("token-dropped",
         _one("prose", [_same(_at["The free-text field is not covered"],
                              new="The field is not covered.")]),
         0, "the reword drops docs/ret.md"),
        ("token-invented",
         _one("prose", [_same(_at["Retention for the structured"],
                              new="Owned by the platform team, see "
                                  "`docs/nowhere.md`.")]),
         0, "the reword adds docs/nowhere.md, which is nowhere in this "
            "document — take a fact from the document, not from outside it"),
        ("no-full-stop",
         _one("prose", [_same(_at["Retention for the structured"],
                              new="Owned by the platform team")]),
         0, "the original line ended a sentence and the replacement does not"),
        ("insert-in-fence", _one("prose", [{"line": _at["not prose"] + 1,
                                            "op": "insert", "new": "added."}]),
         0, "insert lands inside a code fence"),
        ("ownership",
         _one("noise", [_same(_at["It is worth noting"], new="")])
         + _one("prose", [_same(_at["It is worth noting"],
                                new="Deleting the parent row leaves it "
                                    "behind.")]),
         1, "already changed by noise"),
        ("good-reword", _one("prose", [_same(_at["It is worth noting"],
                                             new="Deleting the parent row "
                                                 "leaves it behind.")]),
         1, None),
        ("good-delete", _one("noise", [_same(_at["[the owner section]"],
                                             new="")]),
         1, None),
        ("good-insert",
         _one("prose", [{"line": _at["Retention for the structured"],
                         "op": "insert",
                         "new": "The policy is at `docs/ret.md`."}]),
         1, None),
    ]
    for _name, _res, _n_ok, _reason in _diff:
        _, _ok, _no, _ = merge(list(_ml), _res, _me, _mq, _mhd, _msl)
        assert len(_ok) == _n_ok, f"{_name}: applied {len(_ok)}, want {_n_ok}"
        if _reason is None:
            assert not _no, f"{_name}: refused {_no}"
        else:
            assert _no and _no[0][2] == _reason, \
                f"{_name}: got {_no[0][2] if _no else 'nothing'!r}"

    _order = [
        ("span before op", _one("prose", [{"line": _at["## Owner"],
                                           "op": "zap", "old": "nope",
                                           "new": "x"}], hi=2),
         "outside its span (1-2)"),
        ("region before old",
         _one("prose", [{"line": _at["> Legal said"], "old": "nope",
                         "new": "> It is worth noting that legal agreed."}]),
         "line is inside a quotation"),
        ("old before facts",
         _one("prose", [{"line": _at["Retention for the structured"],
                         "old": "nope",
                         "new": "Owned by them, see `docs/nowhere.md`."}]),
         "`old` does not match the file"),
        ("old before shape",
         _one("prose", [{"line": _at["Retention for the structured"],
                         "old": "nope",
                         "new": "It is worth noting that they own it."}]),
         "`old` does not match the file"),
        ("shape before dropped",
         _one("prose", [_same(_at["The free-text field is not covered"],
                              new="It is worth noting that the field is not "
                                  "covered.")]),
         "the replacement text has frame"),
        ("dropped before invented",
         _one("prose", [_same(_at["The free-text field is not covered"],
                              new="The field is not covered, see "
                                  "`docs/nowhere.md`.")]),
         "the reword drops docs/ret.md"),
        ("summary before orphan",
         _one("structure", [_same(_at["## Summary"], new="## Owner")]),
         "that is the summary heading — the tool finds the summary by its "
         "name"),
    ]
    for _name, _res, _reason in _order:
        _, _ok, _no, _ = merge(list(_ml), _res, _me, _mq, _mhd, _msl)
        assert _no and _no[0][2] == _reason, \
            f"gate order changed at {_name}: got " \
            f"{(_no[0][2] if _no else 'nothing')!r}, want {_reason!r}"

    with tempfile.TemporaryDirectory() as _src_box:
        _a = Path(_src_box) / "a" / "doc.md"
        _b = Path(_src_box) / "b" / "doc.md"
        for _p, _t in ((_a, "original\n"), (_b, "edited\n")):
            _p.parent.mkdir(parents=True)
            _p.write_text(_t)
        with tempfile.TemporaryDirectory() as _box:
            _look = sandbox_copies(_box, [_a, _b])
            assert _look[_a] != _look[_b], _look
            assert _look[_a].read_text() == "original\n", "the copies collided"
            assert _look[_b].read_text() == "edited\n", "the copies collided"
            assert not [p for p in Path(_box).iterdir() if p.is_file()], _box
            _said = f"- file: {_look[_b]}:9\n  fix: shorten it\n"
            assert unsandbox(_said, _look, _box) == \
                f"- file: {_b}:9\n  fix: shorten it\n", \
                unsandbox(_said, _look, _box)
            _rel = f"- file: {_look[_b].relative_to(_box)}:10-10\n"
            assert unsandbox(_rel, _look, _box) == f"- file: {_b}:10-10\n", \
                unsandbox(_rel, _look, _box)
    assert "Write no files" in inspect.getsource(cmd_crosscheck), \
        "the crosscheck prompt no longer tells the reviewer to write nothing"
    assert "cwd=box" in inspect.getsource(cmd_crosscheck), \
        "crosscheck runs the backend in the document's own directory again"

    _gd = Path(_tf.mkdtemp())
    _tal = "".join(f"## 1{i}:00 - 1{i}:30\n\nAlex asks who owns the retention "
                   f"job.\n\nAhmed says he takes it after the release.\n\n"
                   for i in range(8))
    (_gd / "call.md").write_text("# Call notes\n\n" + _tal)
    (_gd / "plan.md").write_text("# Design\n\n## Retention\n\n"
                                 "The export job copies rows nightly.\n")
    _seen = []
    _real_run = spawn.run_tree

    def _spy(cmd, **kw):
        _seen.append(kw.get("input") or "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    spawn.run_tree = _spy
    try:
        for _f in ("call.md", "plan.md"):
            with _cl.redirect_stdout(_io.StringIO()), \
                    _cl.redirect_stderr(_io.StringIO()):
                cmd_crosscheck(argparse.Namespace(
                    file=str(_gd / _f), original=None, context=[], dropped=[],
                    backend="codex", mode="review", timeout=60))
    finally:
        spawn.run_tree = _real_run
    _busy = "naming who is busy"
    assert len(_seen) >= 2, \
        f"crosscheck never reached the backend ({len(_seen)} of 2 prompts)"
    _seen = [_seen[0], _seen[-1]]
    assert _busy not in _seen[0], \
        "crosscheck still asks a transcript not to name who is busy"
    assert _busy in _seen[1], \
        "crosscheck stopped asking a design document who is busy"

    for _bk in ("claude", "agy", "codex"):
        _ccb_seen = {}

        def _ccb_spy(cmd, **kw):
            _ccb_seen.setdefault("cmd", list(cmd))
            _ccb_seen.setdefault("kwargs", kw)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        spawn.run_tree = _ccb_spy
        try:
            with _cl.redirect_stdout(_io.StringIO()), \
                    _cl.redirect_stderr(_io.StringIO()):
                cmd_crosscheck(argparse.Namespace(
                    file=str(_gd / "call.md"), original=None, context=[],
                    dropped=[], backend=_bk, mode="review", timeout=60))
        finally:
            spawn.run_tree = _real_run
        assert not any("Find what is verbose" in str(a)
                       for a in _ccb_seen["cmd"]), \
            f"crosscheck's {_bk} branch put the prompt in argv: " \
            f"{_ccb_seen['cmd']!r}"
        assert "Find what is verbose" in (_ccb_seen["kwargs"].get("input")
                                          or ""), \
            f"crosscheck's {_bk} branch must send the prompt on stdin"

    for _p in (specialist_prompt("prose", 4000),
               specialist_prompt("noise", 4000)):
        assert "wraps across lines" not in _p and "new: \"\"` on every" not in _p, \
            "the wrap-seam rule is back in every prompt"
    assert "Never join two sentences into one" in specialist_prompt(
        "prose", 4000), "the join gate is enforced and not stated"
    _w = "Each release note is checked against the changelog before it ships"
    _flat = ["# T", "", "Short line.", "", "Another short line.", ""]
    _job = {"specialist": "prose", "lo": 1, "hi": 0, "hits": []}
    assert "Sentences that wrap in your span" not in job_prompt(
        _job, _flat, "ctx", token_lines(_flat)), \
        "a document with no wrapped sentence still gets the wrap rule"
    _wrapped_doc = ["# T", "",
                    _w + " and the two are compared line by line by a",
                    "reviewer who signs the result off before any of it reaches a customer.",
                    ""]
    _wp = job_prompt(_job, _wrapped_doc, "ctx", token_lines(_wrapped_doc))
    assert "lines 3-4" in _wp, _wp
    assert "left as a fragment" in _wp and "everything those lines said" in _wp, \
        "a wrapped span lost the wrap-seam rule"
    assert wrap_width(_wrapped_doc) is None, \
        "this fixture no longer reproduces the >100-column case"

    _real_specialist_dir = SPECIALIST_DIR
    _tmp_specialist_dir = Path(tempfile.mkdtemp(prefix="kv-selftest-specialists-"))
    try:
        shutil.copyfile(_real_specialist_dir / "_common.md",
                         _tmp_specialist_dir / "_common.md")
        shutil.copyfile(_real_specialist_dir / "summary.md",
                         _tmp_specialist_dir / "summary.md")
        _bad_prompt = _tmp_specialist_dir / "summary.md"
        _keep = _bad_prompt.read_text()
        _bad_prompt.write_text(_keep + "\n{{NO_SUCH_VALUE}}\n")
        SPECIALIST_DIR = _tmp_specialist_dir
        try:
            specialist_prompt("summary", 1000)
            raise AssertionError("an unknown placeholder was accepted")
        except ValueError:
            pass
    finally:
        SPECIALIST_DIR = _real_specialist_dir
        shutil.rmtree(_tmp_specialist_dir, ignore_errors=True)

    _smoke_docs = [SPECIALIST_DIR.parent / "SKILL.md",
                   HERE / "docs" / "user-guide.md"]

    _wordfn = globals()["_word"]

    def _content(s):
        return {w for w in (_wordfn(x) for x in s.split())
                if len(w) >= 4 and not _DANGLES.search(w)}

    def _rules_in(text):
        out = []
        for _a, _b, s in sentence_spans(list(enumerate(text.splitlines(), 1))):
            if (CLAIM_RULE.search(s) or RECOMMENDATION.match(s)) \
                    and len(_content(s)) >= 6 and len(s.split()) >= 8:
                out.append(s)
        return out

    _rules = [r for d in _smoke_docs for r in _rules_in(d.read_text())]
    assert len(_rules) >= 20, \
        f"only {len(_rules)} rules in the shipped docs — too few to test on"

    for _r in _rules:
        _w = _r.split()
        _mid = len(_w) // 2
        _halves = [" ".join(_w[:_mid]) + ".", "",
                   " ".join(_w[_mid:])[:1].upper() + " ".join(_w[_mid:])[1:]]
        assert not claims_lost([_r], _halves)[0], \
            f"splitting a rule in two reads as losing it: {_r[:90]}"

    _uo = ["rule one must never run", "", "filler", "tail line here"]
    _un = ["ADDED"] + [""] + _uo
    assert untouched_lines(_uo, _un) == {1, 3, 4}, untouched_lines(_uo, _un)
    assert untouched_lines(_uo, _uo[:2] + ["changed"] + _uo[3:]) == {1, 4}
    assert 2 not in untouched_lines(_uo, _un)
    _du = ["same rule text here", "", "same rule text here"]
    assert untouched_lines(_du, ["", "", "same rule text here"]) == set(), \
        untouched_lines(_du, ["", "", "same rule text here"])
    assert untouched_lines(_du, _du) == set(), untouched_lines(_du, _du)
    assert "for i in range(ln, _end + 1)" in inspect.getsource(claims_lost), \
        "the untouched guard no longer requires the whole sentence span"

    for _r in _rules:
        _flat = CLAIM_RULE.sub("still", _r)
        _fw = _flat.split()
        _flat = " ".join(["The"] + _fw[1:]) if _fw else _flat
        if CLAIM_RULE.search(_flat) or RECOMMENDATION.match(_flat):
            continue
        _g, _wk, _, _ = claims_lost([_r], [_flat])
        assert not _g, \
            f"a reworded rule still in the file reads as lost: {_r[:90]}"
        assert _wk, \
            f"a rule demoted to a description was not reported: {_r[:90]}"

    _wbox = Path(tempfile.mkdtemp(prefix="kv-weak-"))
    _wo, _wn = _wbox / "o.md", _wbox / "n.md"
    _head = "# T\n\nThis file exists to hold one rule and nothing else.\n\n"
    _wmark, _wsolo = "rules that stopped reading as rules", None
    try:
        for _wr in _rules:
            _wflat = " ".join(["The"] + CLAIM_RULE.sub("still", _wr).split()[1:])
            if CLAIM_RULE.search(_wflat) or RECOMMENDATION.match(_wflat):
                continue
            _wo.write_text(_head + _wr + "\n")
            _wn.write_text(_head + _wflat + "\n")
            with contextlib.redirect_stdout(io.StringIO()) as _wcap:
                _wrc = cmd_verify(argparse.Namespace(
                    original=str(_wo), edited=str(_wn), chat=False,
                    content_edit=False, exempt=[]))
            _wtail = _wcap.getvalue()
            if _wrc == 3 and f"and no shape was added. {_wmark}." in _wtail:
                _wsolo = _wr
                break
        assert _wsolo, \
            "no fixture where a demoted rule is the only thing verify reports"
    finally:
        shutil.rmtree(_wbox, ignore_errors=True)

    _cut = re.compile(r"; (?=\w)|, (?:and|but) (?=\w)")
    for _d in _smoke_docs:
        _raw = _d.read_text()
        _out, _hits = [], 0
        for _ln in _raw.split("\n"):
            _s = _ln.strip()
            if (not _s or "`" in _ln or "](" in _ln or "|" in _ln
                    or _s.startswith((">", "#", "    ", "\t", "```"))
                    or not (CLAIM_RULE.search(_ln)
                            or RECOMMENDATION.match(_s))):
                _out.append(_ln)
                continue
            _m = _cut.search(_ln)
            if not _m:
                _out.append(_ln)
                continue
            _t = _ln[_m.end():]
            _out.append(f"{_ln[:_m.start()]}. {_t[:1].upper()}{_t[1:]}")
            _hits += 1
        if not _hits:
            continue
        _box = Path(tempfile.mkdtemp(prefix="kv-smoke-"))
        try:
            (_box / "o.md").write_text(_raw)
            (_box / "n.md").write_text("\n".join(_out))
            _cap = io.StringIO()
            with contextlib.redirect_stdout(_cap):
                _rc = cmd_verify(argparse.Namespace(
                    original=str(_box / "o.md"), edited=str(_box / "n.md"),
                    chat=False, content_edit=False, exempt=[]))
            assert _rc != 1, (
                f"{_d.name}: splitting {_hits} rules in two is the edit the "
                f"skill asks for, and verify called it damage.\n"
                + "\n".join(l for l in _cap.getvalue().split("\n")
                            if l[:1].isupper() and " — " in l))
        finally:
            shutil.rmtree(_box, ignore_errors=True)

    _gbox = Path(tempfile.mkdtemp(prefix="kv-selftest-gates-"))
    _genv = {_k: os.environ.get(_k)
             for _k in ("PYTHONOPTIMIZE", "XDG_CACHE_HOME", "PATH")}
    try:
        (_gbox / "o.md").write_text("# T\n\nOK prose here.\n")
        (_gbox / "n.md").write_text("# T\n\nreworded prose here.\n")

        (_gbox / "assertgate.py").write_text(
            "import sys\n"
            "t = open(sys.argv[1]).read()\n"
            "assert 'OK' in t, 'the token went'\n")
        (_gbox / "exitgate.py").write_text(
            "import sys\n"
            "t = open(sys.argv[1]).read()\n"
            "raise SystemExit(0 if 'OK' in t else 1)\n")
        for _arm, _on in (("under PYTHONOPTIMIZE=1", True), ("clean env", False)):
            if _on:
                os.environ["PYTHONOPTIMIZE"] = "1"
            else:
                os.environ.pop("PYTHONOPTIMIZE", None)
            _k1 = {_r["name"]: _r for _r in gatelib.run(
                [{"name": _n, "argv": [sys.executable, str(_gbox / _f),
                                       "{edited}"], "timeout": 60}
                 for _n, _f in (("assert-gate", "assertgate.py"),
                                ("exit-gate", "exitgate.py"))],
                _gbox, _gbox / "o.md", _gbox / "n.md")}
            assert _k1["assert-gate"]["after"] == gatelib.BROKEN, (
                f"{_arm}: an assert-based gate that refuses the edit scored "
                f"{_k1['assert-gate']['after']} -- an inherited PYTHONOPTIMIZE "
                f"strips the child's asserts, so it exits 0 having checked "
                f"nothing and the run reads as a pass. {_k1}")
            assert _k1["exit-gate"]["after"] == gatelib.BROKEN, (
                f"{_arm}: the SystemExit control must refuse in BOTH arms, or "
                f"this case is about spawning and not about assert-stripping. "
                f"{_k1}")
            assert _k1["assert-gate"]["before"] == gatelib.OK, _k1
            assert _k1["exit-gate"]["before"] == gatelib.OK, _k1

        (_gbox / gatelib.GATES_FILE).write_text(json.dumps({"gates": [
            {"name": "k2", "argv": ["/bin/true", "{edited}"], "timeout": 60}]}))
        _moved = _gbox / "cache"
        _k2 = {}
        for _arm, _xdg in (("default", None), ("moved", str(_moved))):
            if _xdg is None:
                os.environ.pop("XDG_CACHE_HOME", None)
            else:
                os.environ["XDG_CACHE_HOME"] = _xdg
            _cap = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(_cap):
                cmd_verify(argparse.Namespace(
                    original=str(_gbox / "o.md"), edited=str(_gbox / "n.md"),
                    chat=False, content_edit=False, exempt=[],
                    gates_file=str(_gbox / gatelib.GATES_FILE)))
            _k2[_arm] = (_cap.getvalue(), str(gatelib.trust_store()))
        assert _k2["default"][1] in _k2["default"][0], (
            "the refusal named no store path, so a reader told an "
            "acknowledgement is missing has nothing to look in: "
            + _k2["default"][0])
        assert _k2["moved"][1] in _k2["moved"][0], (
            "the relocated store path is not in the refusal: "
            + _k2["moved"][0])
        assert str(_moved) in _k2["moved"][1], (
            "XDG_CACHE_HOME did not move the store, so the arms are the same "
            "arm: " + _k2["moved"][1])
        assert "XDG_CACHE_HOME" not in _k2["default"][0], (
            "the relocation clause rides an ordinary machine, where it is "
            "false and stops being read: " + _k2["default"][0])
        assert "XDG_CACHE_HOME is set" in _k2["moved"][0], _k2["moved"][0]
        assert "never been told to run" not in (
            _k2["default"][0] + _k2["moved"][0]), (
            "the refusal still claims a HISTORY it cannot know: " + str(_k2))

        _k3 = {}
        for _which in ("A", "B"):
            _bin = _gbox / f"bin{_which}"
            _bin.mkdir()
            if os.name == "nt":
                _prog = _bin / "kv-selftest-lintdoc.cmd"
                _prog.write_text('@if exist "%~1" (exit /b 0) else (exit /b 1)\r\n')
            else:
                _prog = _bin / "kv-selftest-lintdoc"
                _prog.write_text('#!/bin/sh\ntest -f "$1"\n')
                _prog.chmod(0o755)
            os.environ["PATH"] = f"{_bin}{os.pathsep}{_genv['PATH']}"
            _k3[_which] = "\n".join(gatelib.report(gatelib.run(
                [{"name": "lint", "argv": ["kv-selftest-lintdoc", "{edited}"],
                  "timeout": 60}],
                _gbox, _gbox / "o.md", _gbox / "n.md"))[0])
        assert _k3["A"] != _k3["B"], (
            "two programs of one name printed the SAME pass line: which one "
            "ran is decided by the caller's PATH and the report named "
            "neither.\n" + _k3["A"])
        assert (str(_gbox / "binA" / "kv-selftest-lintdoc") in _k3["A"]
                and str(_gbox / "binB" / "kv-selftest-lintdoc") not in _k3["A"]), \
            _k3["A"]
        assert (str(_gbox / "binB" / "kv-selftest-lintdoc") in _k3["B"]
                and str(_gbox / "binA" / "kv-selftest-lintdoc") not in _k3["B"]), \
            _k3["B"]
        assert "declared check passed" in _k3["A"], _k3["A"]
    finally:
        for _k, _v in _genv.items():
            if _v is None:
                os.environ.pop(_k, None)
            else:
                os.environ[_k] = _v
        shutil.rmtree(_gbox, ignore_errors=True)

    _INSTALLED_OVERRIDE = _saved_installed

    checks = sum(
        1 for line in inspect.getsource(cmd_selftest).splitlines()
        if line.strip().startswith("assert ")
    )
    for _dirty, _cat in [
        ("It's not just caching, it's a full index of every request we serve.",
         "X-not-Y"),
        ("Good point, and the retry budget does need to move before the release.",
         "agreement move"),
        ("That is a separate conversation, so the queue depth stays where it is.",
         "defers its own point"),
        ("In summary, the migration lands on Tuesday and the old path is deleted.",
         "echo"),
        ("The team will perform a review of the manifest before the audit runs.",
         "nominalisation"),
        ("This module aims to normalise every path before the resolver sees it.",
         "purpose hedge"),
        ("## What changed", "worklog"),
    ]:
        _got = {c for _l, c, _t in find_shapes([_dirty], chat=True)}
        assert _cat in _got, f"{_cat!r} did not fire on its own dirty line: {_got}"
    _clean = ("The resolver normalises each path once, and the cache stores the "
              "result under the normalised key.")
    _cleanhits = {c for _l, c, _t in find_shapes([_clean], chat=True)}
    assert not (_cleanhits & {"X-not-Y", "agreement move", "defers its own point",
                              "echo", "nominalisation", "purpose hedge",
                              "worklog"}), _cleanhits

    _tbl = ["| id | the 35 route pages fetches data server-side. Every page |"]
    _cut = unmask.as_written(_tbl, _tbl, 1, "Every page")
    assert _cut.startswith("Every"), _cut
    assert not _cut.startswith("\u2026"), \
        f"a span opening right after a sentence end is not truncated: {_cut!r}"
    _mid = unmask.as_written(_tbl, _tbl, 1, "fetches data server-side.")
    assert _mid.startswith("\u2026"), \
        f"a span opening mid-sentence must say so: {_mid!r}"
    for _raw, _span in [
        ("The resolver normalises each path once.", "The resolver"),
        ("One thing. Another thing entirely.", "Another thing entirely."),
        ("| a cell | Every page is server-side |", "Every page is server-side"),
        ("- Every page is server-side", "Every page is server-side"),
        ("3. Every page is server-side", "Every page is server-side"),
    ]:
        _out = unmask.as_written([_raw], [_raw], 1, _span)
        assert not _out.startswith("\u2026"), f"marked a real opening: {_raw!r} -> {_out!r}"

    _tr_txt = ("Priya\n\n###### 00:00 - 00:09\n\n" + "speech words here. " * 300
               + "\n\nAlex\n\n###### 00:11 - 00:14\n\n" + "more speech said. " * 300 + "\n")
    _tp, _th, _tt, _tq = mask(_tr_txt, "call.md")
    _tv = summary_verdict(opening_summary(_th, _tp, word_count(_tr_txt), _tr_txt))
    assert _tv[0] == "verbatim", _tv
    assert "MISSING" not in _tv[1] and "does not owe" in _tv[1], _tv[1]
    assert "frontmatter" not in _tv[1], _tv[1]
    assert not summary_owed(opening_summary(_th, _tp, word_count(_tr_txt), _tr_txt))
    _one_txt = _tr_txt.replace("###### 00:11 - 00:14", "###### Analysis")
    _op, _oh, _ot, _oq = mask(_one_txt, "notes.md")
    _ov = summary_verdict(opening_summary(_oh, _op, word_count(_one_txt), _one_txt))
    assert _ov[0] != "verbatim", _ov
    assert summary_owed(opening_summary(_oh, _op, word_count(_one_txt), _one_txt))

    _unread = shape_census({"global_context": {"words": 5594, "scanned_words": 0},
                            "chunks": []})
    assert "none scanned" in _unread and "unread one" in _unread, _unread
    assert "0.0 per 1000" not in _unread, _unread
    _clean_cen = shape_census({"global_context": {"words": 5594, "scanned_words": 5594},
                               "chunks": []})
    assert "none scanned" not in _clean_cen and "0 fault-shapes" in _clean_cen, _clean_cen
    assert "none scanned" not in shape_census({"global_context": {"words": 10},
                                               "chunks": []})

    _hbody = "\n\nOrdinary editable prose a reviewer would shorten here.\n\n"

    def _stamped(heads):
        return mask("".join(h + _hbody for h in heads), "x.md")

    for _label, _heads, _want in [
        ("zoom", ["###### 00:00 - 00:13", "###### 00:14 - 00:30"], True),
        ("youtube chapters", ["## 0:00 Intro", "## 12:30 Middle",
                              "## 1:23:45 The long tail"], True),
        ("teams", ["## [00:01:23] Dana", "## [00:02:40] Sam"], True),
        ("srt", ["### 00:00:13,240 --> 00:00:15,000",
                 "### 00:00:15,100 --> 00:00:18,000"], True),
        ("otter", ["## Dana Whitfield  00:12", "## Sam Reyes  01:40"], True),
        ("conference agenda", ["## 09:30 - 10:15 Opening remarks",
                               "## 10:30 - 11:15 Panel"], False),
        ("timed runbook", ["## 09:00 Start the drain",
                           "## 09:15 Verify replicas"], False),
        ("deadline headings", ["## release window 10:30",
                               "## release window 11:45"], False),
        ("speaker, one space", ["## Dana Whitfield 00:12",
                                "## Sam Reyes 01:40"], False),
        ("one timestamp only", ["## 00:00 Intro", "## Analysis"], False),
    ]:
        _p, _h, _t2, _q2 = _stamped(_heads)
        _is = bool(transcript_stamps(_h))
        assert _is == _want, f"{_label}: transcript={_is}, wanted {_want}"
        _scanned = sum(len(l.split()) for l in _p)
        assert (_scanned == 0) == _want, f"{_label}: scanned {_scanned}"
    assert stamp_seconds("0:00") == 0, stamp_seconds("0:00")
    assert stamp_seconds("1:23:45") == 5025, stamp_seconds("1:23:45")
    assert stamp_seconds("12:30") == 750, stamp_seconds("12:30")
    assert stamp_seconds("[00:01:23]") == 83, stamp_seconds("[00:01:23]")
    assert stamp_seconds("00:01:12,400") < TRANSCRIPT_START_MAX

    assert timed_but_not_transcript(_stamped(["## 09:30 - 10:15 A",
                                              "## 10:30 - 11:15 B"])[1])
    assert not timed_but_not_transcript(_stamped(["###### 00:00 - 00:13",
                                                  "###### 00:14 - 00:30"])[1])
    assert not timed_but_not_transcript(_stamped(["## 00:00 Intro",
                                                  "## Analysis"])[1])

    _owned = {n for _g in (EXISTENCE, SUBSTITUTION, OCCURRENCE, CHAT) for n in _g}
    assert _SHAPES_SEEN is not None, "the recorder never started"
    assert len(_owned) >= 43, (
        "find_shapes can emit %d categories and the floor is 43 - if a shape "
        "was retired on purpose, lower the floor in the same commit: %s"
        % (len(_owned), sorted(_owned)))
    _gap = sorted(_owned - (_SHAPES_SEEN or set()))
    assert not _gap, ("shapes `find_shapes` can emit that no case produces: %s"
                      % ", ".join(_gap))
    checks += 3
    _seen = (_SHAPES_SEEN or set()) & _owned
    _miss = sorted(_owned - _seen)
    _line = (f"selftest ok ({checks} checks, {len(_seen)} of {len(_owned)} "
             f"shapes exercised")
    if _miss:
        _line += ", not exercised: " + ", ".join(_miss)
    print(_line + ")")
    return 0


def positive_int(s):
    """An argparse type for a count that cannot be zero."""
    try:
        n = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r} is not a whole number")
    if n < 1:
        raise argparse.ArgumentTypeError(f"{s!r} must be 1 or more")
    return n


def cmd_trust(args):
    """Record one gates declaration as allowed to run on this machine."""
    p = Path(args.file).resolve()
    if not p.is_file():
        print(f"kill-verbosity: no such file: {p}", file=sys.stderr)
        return 2
    if p.name != gatelib.GATES_FILE:
        print(f"kill-verbosity: only a file named {gatelib.GATES_FILE} can be "
              f"trusted; this is {p.name}.", file=sys.stderr)
        return 2
    try:
        decl = gatelib.load(p)
    except gatelib.Declined as e:
        print(f"kill-verbosity: {e}", file=sys.stderr)
        return 2
    d = gatelib.trust(p)
    print(f"trusted {p}\n  {d}\n  {len(decl)} check"
          f"{'' if len(decl) == 1 else 's'}: "
          f"{', '.join(g['name'] for g in decl)}\n"
          f"Editing this file un-trusts it — the record is keyed on its "
          f"contents, not on its path alone.")
    return 0


class _ExplicitAgent(argparse.Action):
    """`store`, plus a `<dest>_explicit` flag recording that the option was
    actually typed rather than left at its default.
    """
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        setattr(namespace, f"{self.dest}_explicit", True)


def build_parser():
    """The whole command surface, so one thing can be asked what it is."""
    p = argparse.ArgumentParser(prog="kill-verbosity", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="store_true",
                   help="print the build id and the file it was hashed from")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--full", action="store_true",
                        help="print every finding, not the first few")
    sub = p.add_subparsers(dest="cmd", required=True)

    chat_help = "score it as a chat message, not a document"

    a = sub.add_parser("plan", parents=[common], help="build the work list")
    a.add_argument("file")
    a.add_argument("--json", action="store_true",
                   help="the work list as JSON — chunks, shape hits, facts, "
                        "duplicates — instead of the printed report")
    a.add_argument("--chat", action="store_true", help=chat_help)
    a.add_argument("--no-reorder", action="store_true",
                   help="leave every section where it is: no `move` and no `move-block`. Reordering stays the default -- an agent asking for a shorter document expects the sections put in reading order -- but a document whose order is load-bearing, or one whose reader has to diff it by hand, wants this.")
    a.set_defaults(fn=cmd_plan)

    r = sub.add_parser("run", parents=[common], help="fan the work out to the specialists and merge")
    r.add_argument("file")
    r.add_argument("-o", "--out", help="default: FILE.kv.EXT next to the input")
    r.add_argument("--agent", default=None, action=_ExplicitAgent,
                   type=_agent_type, metavar="AGENT",
                   help="the agent that answers: claude, codex, agy, "
                        "delegate, or any "
                        "command line that reads the prompt on stdin and "
                        "prints the answer, quoted as one argument. "
                        "Default: KV_AGENT, else the first installed of "
                        "claude, codex, agy, delegate. When it fails, the "
                        "installed ones are tried in turn, silently unless "
                        "you named the agent")
    r.add_argument("--any-agent", action="store_true",
                   help="proceed even when EVERY job was answered "
                        "by a fallback agent, not the --agent you "
                        "named explicitly. Without it such a run stops "
                        "before writing output (exit 6). Has no effect "
                        "when --agent was left at its default, or "
                        "when only some jobs were substituted.")
    r.add_argument("--timeout", type=positive_int, default=RUN_BUDGET,
                   help=f"seconds for the whole run (default {RUN_BUDGET}); "
                        f"jobs still unsent when it runs out resume on a rerun")
    r.add_argument("--job-timeout", type=positive_int, default=JOB_TIMEOUT,
                   help=f"seconds for one specialist call "
                        f"(default {JOB_TIMEOUT})")
    r.add_argument("--no-budget", action="store_true",
                   help="no ceiling on the run; every job is sent")
    r.add_argument("--dry-run", action="store_true",
                   help="print the job matrix without calling an agent")
    r.add_argument("--no-agents", action="store_true",
                   help="run everything except the specialists: the gates, "
                        "the merge, verify, and a run record saying no "
                        "specialist ran. The output is the input. Use it to "
                        "exercise the gates and the accept refusals on your "
                        "own tree without paying for a dispatch.")
    r.add_argument("--chat", action="store_true", help=chat_help)
    r.add_argument("--no-reorder", action="store_true",
                   help="leave every section where it is: no `move` and no `move-block`. Reordering stays the default -- an agent asking for a shorter document expects the sections put in reading order -- but a document whose order is load-bearing, or one whose reader has to diff it by hand, wants this.")
    r.set_defaults(fn=cmd_run, agent_explicit=False)

    b = sub.add_parser("verify", parents=[common], help="check the edit kept every fact and dropped every shape")
    b.add_argument("original")
    b.add_argument("edited")
    b.add_argument("--chat", action="store_true", help=chat_help)
    b.add_argument("--in-place", action="store_true",
                   help="show each loss where it sits, not grouped by check")
    b.set_defaults(fn=cmd_verify_cli)

    e = sub.add_parser("accept", parents=[common], help="put the run's output in place of the input")
    e.add_argument("file")
    e.add_argument("edited", nargs="?", help="default: FILE.kv.EXT")
    e.add_argument("--dry-run", action="store_true",
                   help="run every check and print what accept WOULD do, "
                        "including where the untouched original is; copy "
                        "nothing")
    e.add_argument("--chat", action="store_true", help=chat_help)
    e.set_defaults(fn=cmd_accept)

    c = sub.add_parser("crosscheck", parents=[common],
                       help="second opinion from a model that did not write the edits")
    c.add_argument("file")
    c.add_argument("original", nargs="?", help="compare against this original")
    c.add_argument("--context", action="append", metavar="FILE",
                   help="another file the reviewer should read; repeatable")
    c.add_argument("--backend", metavar="NAME",
                   help="which agent reads the result: codex, agy, claude, "
                        "or any command line that reads the prompt on stdin "
                        "and prints the answer; overrides KV_BACKEND")
    c.set_defaults(fn=cmd_crosscheck_cli)

    t = sub.add_parser("trust", parents=[common],
                       help="allow one .killverbosity.gates.json to run")
    t.add_argument("file", help="the .killverbosity.gates.json to trust")
    t.set_defaults(fn=cmd_trust)

    d = sub.add_parser("selftest", parents=[common], help="assert the parser and the gate still work")
    d.set_defaults(fn=_selftest_no_agents)
    return p


def cli_surface(p=None):
    """{subcommand: {option strings it takes}}, from the parser itself."""
    p = p or build_parser()
    subs = next((a for a in p._actions
                 if isinstance(a, argparse._SubParsersAction)), None)
    out = {"kill-verbosity": {s for a in p._actions for s in a.option_strings
                              if s not in ("-h", "--help")}}
    for name, sp in (subs.choices if subs else {}).items():
        out[name] = {s for a in sp._actions for s in a.option_strings
                     if s not in ("-h", "--help")}
    return out



def _suggest_subcommand(argv, choices):
    """argparse's `invalid choice` lists every subcommand and suggests none."""
    word = next((a for a in argv if not a.startswith("-")), None)
    if not word or word in choices:
        return None
    w = word.lower()
    limit = max(1, min(3, len(w) // 2))
    best, best_d = None, None
    for c in choices:
        b = c.lower()
        prev = list(range(len(b) + 1))
        for x, ca in enumerate(w, 1):
            cur = [x]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            prev = cur
        if best_d is None or prev[-1] < best_d:
            best, best_d = c, prev[-1]
    if best_d is None or best_d > limit:
        return None
    return 'unknown command "%s" - did you mean "%s"?' % (word, best)


def main():
    p = build_parser()
    if "--version" in sys.argv[1:]:
        print(version_line())
        return 0
    hint = _suggest_subcommand(sys.argv[1:], set(p._subparsers._group_actions[0].choices))
    if hint:
        print("kill-verbosity: " + hint, file=sys.stderr)
        return 2
    args = p.parse_args()
    global SHOW_ALL
    SHOW_ALL = bool(getattr(args, "full", False))
    args.only = args.profile = args.project = args.freeze = None
    args.gates_file = None
    target = getattr(args, "file", None) or getattr(args, "original", None)
    _named = [c for c in (target, getattr(args, "edited", None)) if c]
    _from = next((c for c in _named if find_project(c)), None)
    found = find_project(_from) if _from else None
    refuse = freeze = None
    while found is not None:
        try:
            args.profile, args.only, refuse, freeze, _targets = \
                read_project(found)
        except SystemExit as e:
            if e.code not in (0, None) and isinstance(e.code, str):
                print(e.code, file=sys.stderr)
            return 2
        if _targets is None or any(_matched_glob(_targets, found, c)
                                   is not None for c in _named):
            break
        found = find_project(_from, after=found.parent)
        args.profile = args.only = refuse = freeze = None
    args.searched = [str(Path(c).resolve().parent if Path(c).is_file()
                         else Path(c).resolve()) for c in _named]
    if found:
        try:
            args.project = found
            args.gates_file = gatelib.find(found)
            name = load_profile(args.profile) if args.profile else None
        except SystemExit as e:
            if e.code not in (0, None) and isinstance(e.code, str):
                print(e.code, file=sys.stderr)
            return 2
        args.freeze = next(
            (f for f in (frozen_by(freeze, found, c) for c in _named) if f),
            None) if freeze else None
        hit = refused_by(refuse, found, target) if refuse and target else None
        if hit:
            glob, why = hit
            why = why.rstrip().rstrip(".")
            print(f"declared: {target} matched "
                  f"{glob if glob else '<whole tree>'} in {found} — {why}. "
                  f"A note, not a gate: nothing here is refused, restricted "
                  f"or relocated. `accept` keeps a numbered copy of "
                  f"{Path(target).name} before it writes.",
                  file=sys.stderr)
        said = [f"profile {name}"] if name else []
        said += ([f"specialists {args.only}"]
                 if args.only and args.fn is cmd_run else [])
        if said:
            print(f"kill-verbosity: {found} — {', '.join(said)}",
                  file=sys.stderr)
    paths = [getattr(args, a, None) for a in ("file", "original", "edited")]
    paths += getattr(args, "context", None) or []
    for v in paths:
        if v and not Path(v).is_file():
            print(f"kill-verbosity: no such file: {v}", file=sys.stderr)
            return 2
    try:
        return args.fn(args)
    except UsageError as e:
        print(f"kill-verbosity: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
