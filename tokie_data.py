"""Data layer for the Tokie widget (tokie.py): local Claude Code + Codex token counts.

Reads the session logs the CLIs/extensions write on this machine:
  Claude Code : ~/.claude/projects/**/*.jsonl   (or $CLAUDE_CONFIG_DIR/projects)
  Codex       : ~/.codex/sessions/**/*.jsonl    (or $CODEX_HOME/sessions, archived_sessions)
Also holds the Codex profile baseline (codex_profiles.json) and the combined-total maths.
"""
import json
import os
from datetime import datetime
from pathlib import Path

HOME = Path.home()


def claude_dirs():
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    roots = [Path(p) for p in env.split(",")] if env else [HOME / ".claude"]
    return [r / "projects" for r in roots]


def codex_dirs():
    root = Path(os.environ.get("CODEX_HOME") or HOME / ".codex")
    return [root / "sessions", root / "archived_sessions"]


def local_date(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except Exception:
        return None


def epoch(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def rec(date, agent, source, account, model, i, o, cw, cr, ts=""):
    return dict(date=date, agent=agent, source=source, account=account, model=model,
                input=i, output=o, cache_write=cw, cache_read=cr, ts=epoch(ts))


def rec_total(r):
    return r["input"] + r["output"] + r["cache_write"] + r["cache_read"]


def load_claude():
    best = {}  # (message id, request id) -> record; streaming repeats entries, keep the last
    n = 0
    for d in claude_dirs():
        for f in d.rglob("*.jsonl") if d.exists() else []:
            n += 1
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if '"usage"' not in line:
                            continue
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        m = e.get("message") or {}
                        u = m.get("usage")
                        model = m.get("model") or ""
                        date = local_date(e.get("timestamp", ""))
                        if not u or not date or model.startswith("<"):
                            continue
                        key = (m.get("id"), e.get("requestId")) if m.get("id") else (str(f), e.get("uuid"))
                        best[key] = rec(date, "Claude", e.get("entrypoint") or "claude", "-", model,
                                        u.get("input_tokens", 0), u.get("output_tokens", 0),
                                        u.get("cache_creation_input_tokens", 0),
                                        u.get("cache_read_input_tokens", 0), e.get("timestamp", ""))
            except OSError:
                pass
    return list(best.values()), n


def load_codex():
    out = []
    n = 0
    for d in codex_dirs():
        for f in d.rglob("*.jsonl") if d.exists() else []:
            n += 1
            source, account, model = "codex", "-", "codex"
            prev = dict(i=0, o=0, cw=0, cr=0)
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if "session_meta" in line or "turn_context" in line:
                            try:
                                e = json.loads(line)
                            except ValueError:
                                continue
                            p = e.get("payload") or {}
                            if e.get("type") == "session_meta":
                                source = p.get("originator") or source
                                account = (p.get("creator_account_id") or "-")[:8]
                            elif p.get("model"):
                                model = p["model"]
                            continue
                        if "token_count" not in line:
                            continue
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        p = e.get("payload") or {}
                        t = ((p.get("info") or {}).get("total_token_usage"))
                        date = local_date(e.get("timestamp", ""))
                        if p.get("type") != "token_count" or not t or not date:
                            continue
                        cr = t.get("cached_input_tokens", 0)
                        cur = dict(i=t.get("input_tokens", 0) - cr, o=t.get("output_tokens", 0),
                                   cw=t.get("cache_write_input_tokens", 0), cr=cr)
                        d_ = {k: cur[k] - prev[k] for k in cur}
                        if min(d_.values()) < 0:  # counter reset: treat as fresh
                            d_ = cur
                        prev = cur
                        if any(d_.values()):
                            out.append(rec(date, "Codex", source, account, model,
                                           d_["i"], d_["o"], d_["cw"], d_["cr"], e.get("timestamp", "")))
            except OSError:
                pass
    return out, n


# Per-user data lives in %APPDATA%\Tokie so the packaged .exe (and friends' copies) keep their own numbers.
DATA_DIR = Path(os.environ.get("APPDATA") or HOME) / "Tokie"
PROFILES_FILE = DATA_DIR / "codex_profiles.json"
# Empty on purpose: each person types in their own Codex profile numbers (Edit profiles file).
DEFAULT_PROFILES = {"as_of": "", "profiles": []}


def _migrate_old_file():
    """Earlier versions kept codex_profiles.json next to the script; move it into DATA_DIR once."""
    old = Path(__file__).with_name("codex_profiles.json")
    if not PROFILES_FILE.exists() and old.exists() and old.resolve() != PROFILES_FILE.resolve():
        PROFILES_FILE.write_text(old.read_text(encoding="utf-8"), encoding="utf-8")


def load_profiles():
    """Official Codex profile numbers (typed in from the profile pages). Edit codex_profiles.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_old_file()
    if not PROFILES_FILE.exists():
        PROFILES_FILE.write_text(json.dumps(DEFAULT_PROFILES, indent=2), encoding="utf-8")
    try:
        return json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_PROFILES


def save_profiles(data):
    PROFILES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def ensure_combined(data, records):
    """Freeze the baseline on first run: Codex = profile numbers (or its logs if no profiles), Claude = its logs."""
    if "combined" in data:
        return False
    now = datetime.now().astimezone()

    def logs(agent):
        return sum(rec_total(r) for r in records if r["agent"] == agent and r["ts"] <= now.timestamp())
    data["combined"] = {
        "snapshot_at": now.timestamp(),
        "snapshot_iso": now.isoformat(timespec="seconds"),
        "claude_baseline": logs("Claude"),
        "codex_log_baseline": logs("Codex"),
        "ledger": {"Claude": 0, "Codex": 0},
    }
    return True


def compute_combined(data, records):
    """Baseline + usage after the snapshot. The ledger keeps 'added' from shrinking if old logs are deleted."""
    c = data["combined"]
    snap = c["snapshot_at"]
    added = {"Claude": 0, "Codex": 0}
    for r in records:
        if r["ts"] > snap:
            added[r["agent"]] += rec_total(r)
    for agent in added:
        added[agent] = max(added[agent], c["ledger"].get(agent, 0))
    if data["profiles"]:
        codex_base = int(round(sum(p["lifetime_m"] for p in data["profiles"]) * 1e6))
    else:  # no profile numbers typed in: start from what the local Codex logs held at the snapshot
        codex_base = c.get("codex_log_baseline", 0)
    parts = dict(codex_base=codex_base, claude_base=c["claude_baseline"],
                 codex_added=added["Codex"], claude_added=added["Claude"])
    parts["total"] = sum(parts.values())
    return parts, added


def fmt(n):
    return f"{int(n):,}"


def short(n):
    n = float(n)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return str(int(n))
