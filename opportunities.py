#!/usr/bin/env python
"""Oportunitati de CASTIG pentru agent — raporteaza DOAR ce e nou, altfel TACE.

De ce asa: Antonio a cerut sa cautam modalitati de a face bani — pentru agent
sau impreuna cu el, NU locuri de munca pentru el. De aceea scanner-ul a fost
schimbat din temelie la 2026-10-25: job board-urile (WeWorkRemotely, RemoteOK,
Himalayas, Remotive) au fost scoase, pentru ca cautau angajatori, nu bani.

Ce rămâne — si ce poate fi facut de un agent:
    bug bounty   : arkadiyt/bounty-targets-data — TOATE cele 4 fisiere
                   (HackerOne 449 · Bugcrowd 298 · Intigriti 143 · YesWeHack 56).
                   634 de programe platesc; semnalul de valoare e recompensa
                   declarata, nu numarul de programe.
                   Model: agentul face recon + scrie raportul, Antonio il
                   trimite sub identitatea lui.
    micro-taskuri: r/slavelabour, r/forhire — oameni care CER o treaba mica
                   si platesc. Agentul poate livra direct (scraping, curatat
                   date, PDF, scripturi). Sume mici, dar executabile fara
                   identitate. (r/freelance_forhire e BANAT — scos 2026-10-25.)

Onestitate: asta GASESTE oportunitati, nu produce bani. Nu garanteaza venit.
Bug bounty: plata merge pe o identitate umana; agentul nu poate incasa direct.

Folosire:
    python opportunities.py              # tick (pentru cron)
    python opportunities.py --all        # ignora starea, arata tot
    python opportunities.py --stats      # cate stim deja
    python opportunities.py --reset      # uita tot (re-raporteaza)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


def stable_id(prefix: str, text: str) -> str:
    """ID stabil intre procese.

    NU folosi hash(): e randomizat per proces (PYTHONHASHSEED), deci acelasi
    anunt primea alt ID la fiecare rulare si starea nu recunoştea nimic —
    scanner-ul repeta tot la infinit. Bug prins la a doua rulare.
    """
    return f"{prefix}:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}"

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "opportunities_state.json")
UA = {"User-Agent": "hermes-cat/1.0 (opportunity-scanner)", "Accept": "*/*"}

# Cuvinte care fac o oportunitate relevanta pentru Antonio
# (developer/researcher, Python, AI, remote, Europa/Romania ok)
RELEVANT = re.compile(
    r"\b(python|ai|ml|machine learning|llm|data|backend|api|automation|scrap|"
    r"research|devops|infra|security|pentest|bug bounty|freelance|contract|"
    r"remote|europe|romania|anywhere)\b", re.I)

# Cele 4 platforme de bug bounty. Dupa 2026-10-25 se citesc TOATE, nu doar
# HackerOne: Bugcrowd/Intigriti/YesWeHack adauga 497 de programe, iar platile
# lor sunt EXPLICITE in JSON (max_payout / max_bounty) — semnal real de
# valoare, spre deosebire de HackerOne unde doar `offers_bounties` e boolean.
BOUNTY_REPO = ("https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/"
               "main/data/{name}")
BOUNTY_HEAD = ("https://api.github.com/repos/arkadiyt/bounty-targets-data"
               "/commits?per_page=1")
CACHE_DIR = os.path.join(HERE, "bounty_cache")
# (fisier, platforma, cum se citeste recompensa)
BOUNTY_SOURCES = [
    ("hackerone_data.json", "HackerOne", "offers_bounties"),
    ("bugcrowd_data.json", "Bugcrowd", "max_payout"),
    ("intigriti_data.json", "Intigriti", "max_bounty_value"),
    ("yeswehack_data.json", "YesWeHack", "max_bounty"),
]
HN = ("https://hn.algolia.com/api/v1/search_by_date?query={q}"
      "&tags=story&hitsPerPage={n}")

# Subreddit-uri unde oamenii CER o treaba si platesc — ce poate livra un agent
# direct, fara identitate umana. Se filtreaza pe tag-ul din titlu: [task] /
# [hire] / [paid]. Postarile [offer] sunt oameni care se vanz, nu cumperi.
#
# r/freelance_forhire a fost SCOS la 2026-10-25: e BANAT. Dovada e corpul
# raspunsului (404): <title>freelance_forhire: banned</title>. Un subreddit
# banat nu mai poate aparea ca "fără raspuns" — e mort, nu rate-limit.
# r/jobbit a fost încercat și RESPINS (2026-10-25): majoritatea postărilor
# sunt angajări cu salariu ($115.000–$300.000/an), nu micro-taskuri plătite.
# Exact zgomotul pe care Antonio l-a respins („nu căutăm locuri de muncă").
TASK_SUBS = [
    ("slavelabour", re.compile(r"\[(task|hire|paid)", re.I)),
    ("forhire", re.compile(r"\[(task|hire|paid)", re.I)),
]
TASK_CACHE = os.path.join(HERE, "task_cache")
TASK_TTL = 6 * 3600
# Reddit acorda ~O cerere pe IP, apoi 429 pentru ~75s (masurat 2026-10-25).
# De aceea UN subreddit pe rulare, rotit — nu trei cereri in 2 secunde.
TASK_PER_RUN = 1
TASK_GAP = 60

# Reddit trateaza UA-ul de bot mai rau decat IP-ul; cu UA de browser trece.
BROWSER_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/155.0.0.0 Safari/537.36"),
              "Accept": "*/*"}


def get(url, timeout=25):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return None


def fetch(url, timeout=25, headers=None):
    """(corp, cod HTTP). Codul deosebește 429 (rate-limit) de 404/000.

    `get()` intoarce doar corpul, deci un 429 arata la fel ca o sursa moarta —
    exact confuzia care scosese doua din trei surse din acoperire.
    """
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers or UA),
                timeout=timeout) as r:
            return r.read().decode("utf-8", "replace"), r.status
    except urllib.error.HTTPError as e:
        return None, e.code
    except (urllib.error.URLError, OSError):
        return None, None


def _task_cache_path(sub):
    return os.path.join(TASK_CACHE, sub + ".json")


def read_task_cache(sub):
    """(items, 'fresh'|'stale'|None) — aceeași semantică ca signal_fetch."""
    p = _task_cache_path(sub)
    if not os.path.exists(p):
        return None, None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if time.time() - d.get("ts", 0) > TASK_TTL:
            return d.get("items", []), "stale"
        return d.get("items", []), "fresh"
    except (OSError, json.JSONDecodeError):
        return None, None


def write_task_cache(sub, items):
    try:
        os.makedirs(TASK_CACHE, exist_ok=True)
        tmp = _task_cache_path(sub) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": int(time.time()), "items": items}, f,
                      ensure_ascii=False)
        os.replace(tmp, _task_cache_path(sub))
    except OSError:
        pass


def clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", s.replace("&amp;", "&").replace("&#39;", "'")
                  .replace("&quot;", '"')).strip()


def parse_feed(xml: str):
    """Entry-uri RSS/Atom: [(titlu, link)]."""
    out = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    for item in root.iter():
        if item.tag.split("}")[-1] not in ("item", "entry"):
            continue
        title = link = None
        for ch in item:
            tag = ch.tag.split("}")[-1]
            if tag == "title" and not title:
                title = clean(ch.text)
            elif tag == "link":
                link = ch.get("href") or clean(ch.text)
        if title and len(title) > 10:
            out.append((title, link))
    return out


# ─────────────────────── surse ───────────────────────

def _cache_paths(name: str):
    return (os.path.join(CACHE_DIR, name), os.path.join(CACHE_DIR, name + ".sha"))


def load_dataset(name: str):
    """Intoarce dataset-ul unei platforme, din cache daca repo-ul n-a schimbat.

    `hackerone_data.json` are 18,9 MB — redescarcat la fiecare 6h inseamna
    ~90 MB/zi inutil. Deci se cere SHA-ul ultimului commit (un apel mic) si
    se descarca doar cand s-a schimbat.

    Regula invatata de la crypto_watch: un esec de retea nu suprascrie ultima
    observatie buna. Daca descarcarea pica dar cache-ul exista, folosim cache-ul
    in loc sa raportam platforma ca moarta.
    """
    head = None
    raw = get(BOUNTY_HEAD, timeout=15)
    if raw:
        try:
            head = json.loads(raw)[0]["sha"]
        except (json.JSONDecodeError, IndexError, KeyError, TypeError):
            head = None
    path, shapath = _cache_paths(name)
    if head and os.path.exists(path) and os.path.exists(shapath):
        try:
            if open(shapath, encoding="utf-8").read().strip() == head:
                return json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    raw = get(BOUNTY_REPO.format(name=name), timeout=60)
    if not raw:
        if os.path.exists(path):                    # fallback pe cache
            try:
                return json.load(open(path, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    try:                                            # cache-ul e optimizare
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        if head:
            with open(shapath, "w", encoding="utf-8") as f:
                f.write(head)
    except OSError:
        pass
    return data


def payout_of(p: dict, how: str):
    """Recompensa maxima: (numar pentru sortare, text pentru om).

    Intoarce (None, '') daca programul NU plateste — asta e filtruul de
    valoare: un VDP cu offers_bounties=false nu intra deloc in lista.
    """
    try:
        if how == "offers_bounties":
            if not p.get("offers_bounties"):
                return (None, "")
            return (1, "plătește (sumă nedeclarată)")
        if how == "max_payout":
            v = p.get("max_payout") or 0
            return (v, f"până la ${v:,}") if v > 0 else (None, "")
        if how == "max_bounty_value":
            mb = p.get("max_bounty")
            if not isinstance(mb, dict):
                return (None, "")
            v = mb.get("value") or 0
            cur = mb.get("currency", "")
            return (v, f"până la {v:,} {cur}".strip()) if v > 0 else (None, "")
        if how == "max_bounty":
            v = p.get("max_bounty") or 0
            return (v, f"până la {v:,}") if v > 0 else (None, "")
    except (AttributeError, TypeError):
        return (None, "")
    return (None, "")


def bounty_id(platform: str, p: dict, name: str) -> str:
    """ID stabil si unic per platforma.

    HackerOne isi pastreaza formatul vechi `h1:<handle>` ca starea de dinainte
    de upgrade sa nu le vada ca noi.
    """
    if platform == "HackerOne":
        return f"h1:{p.get('handle') or stable_id('h1', name)}"
    if platform == "Intigriti":
        return f"ig:{p.get('handle') or stable_id('ig', name)}"
    if platform == "YesWeHack":
        return f"yh:{p.get('id') or stable_id('yh', name)}"
    return f"bc:{stable_id('bc', name)}"


def scan_bounties():
    """Programe de bug bounty care platesc, pe 4 platforme.

    Semnalul de valoare e recompensa, nu numarul de programe. Se sorteaza
    descrescator dupa recompensa, cu bonus pentru programe a caror nume se
    potriveste cu stack-ul lui Antonio (python/ai/security).
    """
    out, failed = [], []
    for fname, platform, how in BOUNTY_SOURCES:
        data = load_dataset(fname)
        if data is None:
            failed.append(platform)
            continue
        items = []
        for p in data:
            amt, txt = payout_of(p, how)
            if not amt:
                continue
            name = clean(p.get("name") or p.get("handle") or "")
            if not name:
                continue
            targets = p.get("targets")
            n_scope = (len(targets.get("in_scope") or [])
                       if isinstance(targets, dict) else 0)
            items.append({
                "id": bounty_id(platform, p, name),
                "platform": platform,
                "title": name[:100],
                "meta": f"{platform} · {txt}"
                        + (f" · {n_scope} target-uri" if n_scope else ""),
                "link": p.get("url")
                        or (f"https://hackerone.com/{p.get('handle')}"
                            if platform == "HackerOne" else ""),
                "score": amt,
                "rel": bool(RELEVANT.search(name)),
            })
        items.sort(key=lambda x: (-int(x["rel"]), -x["score"]))
        out.extend(items)
    return out, failed


def scan_hn():
    """Firuri HN despre munca independenta / ce se intampla in domeniu."""
    out = []
    for q in ("freelance", "bug bounty"):
        raw = get(HN.format(q=urllib.parse.quote(q), n=5), timeout=20)
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for h in d.get("hits", [])[:4]:
            t = clean(h.get("title") or "")
            if not t:
                continue
            out.append({"id": f"hn:{h.get('objectID')}", "title": t,
                        "meta": f"{h.get('points', 0)}p · {h.get('num_comments', 0)}c",
                        "link": f"https://news.ycombinator.com/item?id={h.get('objectID')}"})
    return out


def scan_tasks(state):
    """Micro-taskuri platite — oameni care CER o treaba, agentul o livreaza.

    Reddit acorda ~O cerere pe IP si apoi 429 pentru ~75s (masurat 2026-10-25).
    Versiunea veche trimitea trei cereri una dupa alta, deci doar prima
    trecea si celelalte doua apareau ca "fără raspuns" — jumatate din
    acoperire pierduta in start, in liniste.

    Acum: cache cu TTL, ROTIRE (un subreddit pe rulare) si 429 tratat ca
    rate-limit (folosim cache-ul), nu ca sursa moarta. Daca 429 vine fara
    cache, astept TASK_GAP si incerc inca o data.
    """
    idx = int(state.get("task_idx", 0)) % len(TASK_SUBS)
    todo = [TASK_SUBS[(idx + i) % len(TASK_SUBS)] for i in range(TASK_PER_RUN)]
    state["task_idx"] = (idx + TASK_PER_RUN) % len(TASK_SUBS)

    out, notes = [], []
    for i, (sub, rx) in enumerate(todo):
        if i:
            time.sleep(TASK_GAP)
        cached, how = read_task_cache(sub)
        if how == "fresh":
            out.extend(cached)
            notes.append(f"{sub}: cache")
            continue
        raw, code = fetch(f"https://www.reddit.com/r/{sub}/new/.rss?limit=25",
                          headers=BROWSER_UA)
        if not raw and code == 429:
            # rate-limit, nu sursa moarta: astept si incerc inca o data.
            # Fară asta, un singur 429 amana subreddit-ul cu o rotire întreagă.
            time.sleep(TASK_GAP)
            raw, code = fetch(
                f"https://www.reddit.com/r/{sub}/new/.rss?limit=25",
                headers=BROWSER_UA)
        if raw and code == 200:
            items = [{
                "id": stable_id(f"task:{sub}", link or title),
                "title": title[:120],
                "meta": f"r/{sub} · cerut de cineva",
                "link": link or "",
            } for title, link in parse_feed(raw) if rx.search(title)]
            write_task_cache(sub, items)
            out.extend(items)
            notes.append(f"{sub}: {len(items)}")
        elif cached:
            out.extend(cached)
            notes.append(f"{sub}: cache ({code})")
        else:
            notes.append(f"{sub}: amânat ({code})")
    return out, notes


# ─────────────────────── main ───────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()

    state = {}
    if os.path.exists(STATE) and not a.reset:
        try:
            state = json.load(open(STATE, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    seen = set(state.get("vazute", []))

    if a.stats:
        print(f"  oportunitati cunoscute: {len(seen)}")
        print(f"  ultima scanare: {state.get('ultima_scanare', '(niciodata)')[:19]}")
        return 0

    results, failures = {}, []
    bb, bb_failed = scan_bounties()
    results["bug bounty"] = bb
    failures.extend(bb_failed)
    tasks, task_notes = scan_tasks(state)
    results["micro-taskuri"] = tasks
    failures.extend(n.split(":")[0] for n in task_notes if "amânat" in n)
    hn = scan_hn()
    results["comunitate"] = hn

    total = sum(len(v) for v in results.values())
    if total == 0 and failures:
        # Toate sursele au picat — asta merita spus, nu ascuns.
        print(f"⚠️ Scanner oportunitati: toate sursele au picat ({', '.join(failures)}). "
              f"Acoperire zero, nu 'nimic nou'.")
        return 0

    fresh = []
    for cat, items in results.items():
        for it in items:
            if it["id"] in seen and not a.all:
                continue
            fresh.append((cat, it))

    state["vazute"] = list(seen | {it["id"] for v in results.values() for it in v})
    state["ultima_scanare"] = datetime.now(timezone.utc).isoformat()
    state["total_cunoscute"] = len(state["vazute"])
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)

    if not fresh:
        return 0                      # TACERE: nimic nou, nimic de spus.

    print(f"🎯 **Oportunitati noi** — {datetime.now().astimezone():%d.%m %H:%M}")
    print(f"   ({len(fresh)} din {total} verificate; restul le stiam deja)\n")
    for cat in ("bug bounty", "micro-taskuri", "comunitate"):
        items = [it for c, it in fresh if c == cat]
        if not items:
            continue
        if cat == "bug bounty":
            # grupat pe platforma, cu platile reale inainte — altfel lista e
            # doar un indice de programe, nu un semnal de valoare.
            for platform in ("HackerOne", "Bugcrowd", "Intigriti", "YesWeHack"):
                pl = [it for it in items if it.get("platform") == platform]
                if not pl:
                    continue
                print(f"**BUG BOUNTY — {platform}** ({len(pl)} care plătesc)")
                for it in pl[:6]:
                    print(f"• {it['title']} — {it['meta']}")
                    if it.get("link"):
                        print(f"  {it['link']}")
                print()
            continue
        print(f"**{cat.upper()}** ({len(items)})")
        for it in items[:10]:
            meta = f" — {it['meta']}" if it.get("meta") else ""
            print(f"• {it['title']}{meta}")
            if it.get("link"):
                print(f"  {it['link']}")
        print()
    if failures:
        print(f"⚠️ Surse fara raspuns: {', '.join(set(failures))} — acoperire incompleta.")
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402
    try:
        sys.exit(main())
    except Exception as e:
        print(f"⚠️ Scanner oportunitati: eroare — {type(e).__name__}: {e}")
        sys.exit(0)
