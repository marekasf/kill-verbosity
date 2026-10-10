"""A tree's own structural checks, run inside `verify`."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from killverbosity import spawn

GATES_FILE = ".killverbosity.gates.json"

OK = "ok"
BROKEN = "broken"
UNRUNNABLE = "unrunnable"
BLIND = "blind"

MAX_TIMEOUT = 3600


class Declined(Exception):
    """The declaration is wrong, or has not been trusted. Carries the sentence."""


def trust_store() -> Path:
    """Where the acknowledgements live."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "kill-verbosity" / "trusted-gates.json"


def store_moved() -> str:
    """One clause when the store is not where it usually is, else ""."""
    if not os.environ.get("XDG_CACHE_HOME"):
        return ""
    return (" XDG_CACHE_HOME is set, so this is not the default location — an "
            "acknowledgement recorded elsewhere is not read from here.")


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _store_read() -> dict:
    try:
        got = json.loads(trust_store().read_text())
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def trust(path: Path) -> str:
    """Record this exact file as trusted. Returns the digest recorded."""
    path = Path(path).resolve()
    d = digest(path)
    store = _store_read()
    store[str(path)] = d
    p = trust_store()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, indent=1, sort_keys=True))
    tmp.replace(p)
    return d


def trusted(path: Path) -> bool:
    path = Path(path).resolve()
    want = _store_read().get(str(path))
    return bool(want) and want == digest(path)


def find(config: Path | None):
    """The gates file beside the winning `.killverbosity.json`. None for none."""
    if not config:
        return None
    p = Path(config).resolve().parent / GATES_FILE
    return p if p.is_file() else None


def load(path: Path) -> list[dict]:
    """Parse and validate. Raises `Declined` with the reason."""
    path = Path(path)
    try:
        got = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise Declined(f"{path} could not be read: {e}") from None
    if not isinstance(got, dict) or not isinstance(got.get("gates"), list):
        raise Declined(f'{path} must be {{"gates": [...]}}.')
    out = []
    for i, g in enumerate(got["gates"]):
        where = f"{path} gate {i}"
        if not isinstance(g, dict):
            raise Declined(f"{where} is not an object.")
        name = g.get("name")
        argv = g.get("argv")
        if not isinstance(name, str) or not name.strip():
            raise Declined(f"{where} has no `name`. The name is what a "
                           f"refusal cites and what KV_GATE_OK excuses.")
        if not isinstance(argv, list) or not argv or not all(
                isinstance(a, str) for a in argv):
            raise Declined(f"{where} ({name}): `argv` must be a non-empty "
                           f"list of strings. There is no shell here, so a "
                           f"command line in one string cannot run.")
        if not any("{edited}" in a for a in argv):
            raise Declined(
                f"{where} ({name}): no argument names {{edited}}, so this gate "
                f"cannot see the edit. It would read the same file on both "
                f"runs, pass on both, and report the same verdict for ever -- "
                f"a check that cannot fail, which is worse than no check. The "
                f"fix is to make the check TAKE A PATH, not to work around "
                f"this: use {{edited}} for the document under test and "
                f"{{original}} for what it was.")
        t = g.get("timeout")
        if not isinstance(t, int) or isinstance(t, bool) or not 0 < t <= MAX_TIMEOUT:
            raise Declined(f"{where} ({name}): `timeout` must be a whole "
                           f"number of seconds, 1 to {MAX_TIMEOUT}. A gate "
                           f"with no ceiling is a verify that hangs, and a "
                           f"hung gate and a slow one look the same.")
        out.append({"name": name, "argv": argv, "timeout": t})
    if not out:
        raise Declined(f"{path} declares no gates. Delete it, or declare one — "
                       f"an empty declaration reads as protection.")
    return out


def resolved(argv0: str, env=None) -> list[str]:
    """The argv prefix a bare command name launches, under this PATH."""
    path = (env or os.environ).get("PATH")
    got = shutil.which(argv0, path=path)
    if got:
        return [got]
    if argv0 == "ruff":
        uvx = shutil.which("uvx", path=path)
        if uvx:
            return [uvx, "ruff"]
    return [argv0]


def _run_one(gate, cwd, orig, edited, sidecar):
    argv = [a.replace("{original}", str(orig)).replace("{edited}", str(edited))
            for a in gate["argv"]]
    env = {**os.environ, "KV_ORIGINAL": str(orig), "KV_EDITED": str(edited)}
    env.pop("PYTHONOPTIMIZE", None)
    if sidecar:
        env["KV_SIDECAR"] = str(sidecar)
    ran = resolved(argv[0], env)
    try:
        r = spawn.run_tree([*ran, *argv[1:]], cwd=str(cwd),
                           timeout=gate["timeout"], env=env)
    except subprocess.TimeoutExpired:
        return BROKEN, (f"timed out after {gate['timeout']}s. Raise this "
                        f"gate's `timeout`, or find why it does not finish.")
    except OSError as e:
        return UNRUNNABLE, f"could not be launched: {e}"
    if r.returncode == 0:
        return OK, ""
    said = (r.stderr.strip() or r.stdout.strip() or "").splitlines()
    return BROKEN, (f"exited {r.returncode}"
                    + (": " + " / ".join(said[:4]) if said else
                       " and printed nothing"))


def run(gates, cwd, original: Path, edited: Path, sidecar=None):
    """Every gate, twice: against the original, then against the edit."""
    out = []
    box = tempfile.mkdtemp(prefix="kv-gates-")
    try:
        name = Path(original).name
        was, now = Path(box) / "was" / name, Path(box) / "now" / name
        for p, src in ((was, original), (now, edited)):
            p.parent.mkdir(parents=True)
            shutil.copyfile(src, p)
        gone = Path(box) / "gone" / name
        for g in gates:
            before, said_b = _run_one(g, cwd, original, was, sidecar)
            if before == UNRUNNABLE:
                after, said_a = UNRUNNABLE, said_b
            else:
                after, said_a = _run_one(g, cwd, original, now, sidecar)
            if before == OK and after == OK:
                seen, _p = _run_one(g, cwd, original, gone, sidecar)
                if seen == OK:
                    before = after = BLIND
                    said_a = ("passed with {edited} pointed at a path that "
                              "does not exist, so it never opened the file "
                              "it was handed")
            out.append({"name": g["name"], "before": before, "after": after,
                        "said": said_a or said_b,
                        "ran": " ".join(resolved(g["argv"][0]))})
    finally:
        shutil.rmtree(box, ignore_errors=True)
    return out


def excused() -> set:
    """Gate names the caller has acknowledged as already red."""
    return {s.strip() for s in os.environ.get("KV_GATE_OK", "").split(",")
            if s.strip()}


def excused_blind() -> set:
    """Gate names acknowledged as declaring `{edited}` and not reading it."""
    return {s.strip()
            for s in os.environ.get("KV_GATE_BLIND_OK", "").split(",")
            if s.strip()}


def _named(r) -> str:
    ran = r.get("ran")
    return f"{r['name']} via {ran}" if ran else r["name"]


def report(results, sidecar_name=""):
    """(lines, hard, unrunnable_names, blind_names). `hard` fails verify."""
    lines, hard, dead = [], False, []
    broke, was_red, ok, blind = [], [], [], []
    _excused_blind = excused_blind()
    for r in results:
        if r["after"] == UNRUNNABLE or r["before"] == UNRUNNABLE:
            dead.append(r)
        elif r["after"] == BLIND:
            blind.append(r)
        elif r["before"] == BROKEN:
            was_red.append(r)
        elif r["after"] == BROKEN:
            broke.append(r)
        else:
            ok.append(r)
    if broke:
        hard = True
        lines.append(f"\nGATES BROKEN — {len(broke)} check this tree declares "
                     f"passed on the original and fails on the edit.")
        for r in broke:
            lines.append(f"  {r['name']}: {r['said']}")
        lines.append("  These are the tree's own checks, not this tool's. The "
                     "edit changed something a parser here reads.\n")
    if was_red:
        red = [r for r in was_red if r["name"] not in excused()]
        if red:
            hard = True
            lines.append(f"\nGATES ALREADY RED — {len(red)} check this tree "
                         f"declares fails on the ORIGINAL, so nothing here can "
                         f"say whether the edit made it worse.")
            for r in red:
                lines.append(f"  {r['name']}: {r['said']}")
                if sidecar_name and sidecar_name in r["said"]:
                    lines.append(
                        f"    This names {sidecar_name}, which is the file "
                        f"this tool wrote beside yours. A gate that walks the "
                        f"tree sees it; teach that gate to skip $KV_SIDECAR.")
            lines.append(
                f"  Fix the original first, or excuse these by name: "
                f"KV_GATE_OK={','.join(r['name'] for r in red)}. Not "
                f"KV_FORCE=1 — that forces past every gate at once.\n")
        else:
            lines.append(f"\ngates: {len(was_red)} already red on the original "
                         f"and excused by KV_GATE_OK "
                         f"({', '.join(r['name'] for r in was_red)}).")
    named = [r for r in blind if r["name"] not in _excused_blind]
    probed = len(ok) + len(blind)
    unprobed = len(results) - probed
    ratio = (f"{len(ok)} of {probed} declared check"
             f"{'' if probed == 1 else 's'} read the edit.")
    if unprobed:
        ratio = (f"{len(ok)} of the {probed} check"
                 f"{'' if probed == 1 else 's'} that reached the probe read "
                 f"the edit; the other {unprobed} of this tree's "
                 f"{len(results)} never reached it (reported above).")
    if blind and not named:
        lines.append(f"\ngates: {len(blind)} not reading the edit and excused "
                     f"by KV_GATE_BLIND_OK "
                     f"({', '.join(r['name'] for r in blind)}). {ratio}")
    if named:
        blind = named
        lines.append(f"\nGATES NOT READING THE EDIT — {len(blind)} check this "
                     f"tree declares passed with {{edited}} pointed at a path "
                     f"that does not exist.")
        lines.append(f"  {ratio}")
        for r in blind:
            lines.append(f"  {r['name']}: {r['said']}")
        lines.append(
            "  So it is reading a fixed path of its own and the declaration's "
            "{edited} is decoration. It will report a pass on its own "
            "invariant for ever, on every edit, and a check that cannot fail "
            "is worse than no check. Make the program take the path it is "
            "given. If that means staging it into a scratch tree, CLONE the "
            "directory holding the check -- a symlinked one resolves back out "
            "through __file__ and the check reads your live file, which passes "
            "this probe and reports a clean gate over a damaged document. Or, "
            "if it really cannot, say so once by name: "
            f"KV_GATE_BLIND_OK={','.join(r['name'] for r in blind)}. `verify` "
            "reads on either way; `accept` refuses, because it copies the "
            "output over the input and is the last moment anybody looks.\n")
    if dead:
        lines.append(f"\nGATES UNRUNNABLE — {len(dead)} check this tree "
                     f"declares could not be launched. This is not a verdict "
                     f"about the document.")
        for r in dead:
            lines.append(f"  {r['name']}: {r['said']}")
        lines.append("")
    if ok and not (broke or was_red or blind):
        lines.append(f"gates: {len(ok)} declared check"
                     f"{'' if len(ok) == 1 else 's'} passed "
                     f"({', '.join(_named(r) for r in ok)}).")
    return (lines, hard, [r["name"] for r in dead],
            [r["name"] for r in named])
