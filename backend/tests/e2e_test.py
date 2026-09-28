"""End-to-end test: signup → product → project → upload 2 clips → processing → AI first pass → plans → assistant →
variations → undo/checkpoint → export 9:16 1080p → QC.   Run: python tests/e2e_test.py <fixture_dir>"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

DATA = Path(tempfile.mkdtemp(prefix="rl_e2e_"))
os.environ["RUSHLINE_DATA_DIR"] = str(DATA)
os.environ["RUSHLINE_INPROC_WORKERS"] = "0"
os.environ["RUSHLINE_ASR"] = "auto"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.storage import storage  # noqa: E402
from app import worker  # noqa: E402

FX = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures")
ok_count = 0


def check(cond, msg):
    global ok_count
    if not cond:
        raise AssertionError(msg)
    ok_count += 1
    print("  ✓", msg)


def drain(max_jobs=50):
    n = 0
    while worker.run_once() and n < max_jobs:
        n += 1
    return n


with TestClient(app) as c:
    print("auth")
    r = c.post("/api/v1/auth/signup", json={"email": "frank@example.com", "password": "hunter2hunter2", "name": "Frank"})
    check(r.status_code == 200, "signup")
    tok = r.json()["token"]
    uid = r.json()["user"]["id"]
    H = {"Authorization": f"Bearer {tok}"}
    check(c.get("/api/v1/projects").status_code == 401, "unauthenticated request rejected")
    check(c.post("/api/v1/auth/login", json={"email": "frank@example.com", "password": "wrong"}).status_code == 401, "bad password rejected")

    print("product")
    r = c.post("/api/v1/products", headers=H, json={
        "name": "CS Theory Hair Clay", "category": "Hair care", "price": "14", "discount": "20% off",
        "features": ["matte finish", "strong hold", "85g jar"], "benefits": ["adds texture without shine", "lasts all day"],
        "approved_claims": ["lasts all day"], "avoid_claims": ["cures hair loss"], "cta": "Tap the orange cart"})
    check(r.status_code == 200, "create product")
    prod = r.json()
    r = c.post(f"/api/v1/products/{prod['id']}/photos?filename=product.jpg", headers=H, content=(FX / "product.jpg").read_bytes())
    check(r.status_code == 200 and len(r.json()["photos"]) == 1, "upload product photo")

    print("project + upload")
    r = c.post("/api/v1/projects", headers=H, json={"name": "Hair clay ad", "mode": "tiktok_shop", "product_id": prod["id"],
                                                     "target_duration": 25, "strength": "fast", "generate_ads": False})
    pid, vid = r.json()["id"], r.json()["active_version_id"]
    check(r.status_code == 200, "create project")
    for name in ("raw_take", "broll"):
        r = c.post(f"/api/v1/projects/{pid}/upload?filename={name}.mp4", headers=H, content=(FX / f"{name}.mp4").read_bytes())
        check(r.status_code == 200, f"upload {name}.mp4")
        mid = r.json()["media_id"]
        shutil.copy(FX / f"{name}.words.json", storage.media_dir(uid, mid) / "transcript.json")  # sidecar ASR for tests
    r = c.post(f"/api/v1/projects/{pid}/upload?filename=evil.exe", headers=H, content=b"MZ")
    check(r.status_code == 415, "rejects non-video upload")

    print("processing (ingest → proxy → transcribe → analyze → first pass)")
    t0 = time.time()
    n = drain()
    print(f"    ran {n} jobs in {time.time() - t0:.1f}s")
    proj = c.get(f"/api/v1/projects/{pid}", headers=H).json()
    check(proj["status"] == "ready", "project ready after processing")
    v = c.get(f"/api/v1/versions/{vid}", headers=H).json()
    check(all(m["status"] == "ready" for m in v["media"]), "all media ready")
    raw_dur = sum(m["duration"] for m in v["media"])
    print(f"    raw {raw_dur:.1f}s → edited {v['timeline']['duration']:.1f}s, {len(v['timeline']['clips'])} clips")
    check(v["timeline"]["duration"] < raw_dur * 0.75, "first pass removed dead space/retakes")
    labels = [h["label"] for h in v["history"]]
    print("    history:", labels)
    check(any("silence" in l for l in labels), "dead space op in history")
    check(any("filler" in l for l in labels), "filler op in history")
    check(any("retake" in l.lower() or "mistake" in l.lower() for l in labels), "retake/mistake op in history")
    removed_text = " ".join(w["t"] for w in v["words"] if not w["kept"])
    kept_text = " ".join(w["t"] for w in v["words"] if w["kept"])
    print("    kept:", kept_text[:400])
    check("um" not in kept_text.lower().split() and "uh" not in kept_text.lower().split(), "fillers removed from kept speech")
    check("redo" in removed_text, "spoken mistake removed")
    check(kept_text.count("orange cart") == 1, "duplicate CTA take removed (one kept)")
    check(kept_text.count("CS Theory") == 1, "false start removed, clean take kept")
    secs = [s["section"] for s in v["sections"]]
    print("    sections:", secs)
    check("cta" in secs and "price" in secs or "discount" in secs, "CTA and price detected")
    check(v["sections"][0]["section"] == "hook", "opens with a hook")
    print("    hooks:", [(h["score"], h["categories"], h["text"][:40]) for h in v["hooks"][:4]])
    check(len(v["hooks"]) >= 3, "found ≥3 recorded hook candidates")
    print("    visibility:", {k: v["visibility"][k] for k in ("tracked", "first", "total", "percent", "longest_gap", "closeups")})
    check(v["visibility"]["tracked"] and v["visibility"]["total"] > 2, "product visibility tracked from product photo")
    check(len(v["captions"]) > 5, "captions generated")
    # no cut inside a word
    for cl in v["timeline"]["clips"]:
        for w in v["words"]:
            if w["media_id"] == cl["media_id"]:
                for edge in (cl["s"], cl["e"]):
                    assert not (w["s"] + 0.03 < edge < w["e"] - 0.03), f"cut inside word {w}"
    check(True, "no cut lands inside a word")

    print("plans")
    p = c.post(f"/api/v1/versions/{vid}/plan", headers=H, json={"action": "fit_duration", "args": {"seconds": 12}}).json()
    print("    fit 12s:", p["summary"], [s["label"] for s in p["steps"]])
    check(p["summary"]["after"] < v["timeline"]["duration"], "fit_duration plan shortens")
    same = c.get(f"/api/v1/versions/{vid}", headers=H).json()
    check(abs(same["timeline"]["duration"] - v["timeline"]["duration"]) < 1e-6, "planning does not change the timeline")
    p = c.post(f"/api/v1/versions/{vid}/plan", headers=H, json={"text": "Turn this into a 20 second TikTok Shop ad and use my strongest hook"}).json()
    print("    assistant:", p.get("interpreted"), [s["label"] for s in p["steps"]], p["summary"])
    check(p["steps"], "assistant produced a plan")
    r = c.post(f"/api/v1/versions/{vid}/apply", headers=H, json={"steps": p["steps"], "title": p["title"], "from_assistant": True})
    v2 = r.json()["view"]
    check(r.status_code == 200 and v2["timeline"]["duration"] <= 21.5, f"applied plan → {v2['timeline']['duration']:.1f}s")
    p = c.post(f"/api/v1/versions/{vid}/plan", headers=H, json={"text": "add background music"}).json()
    check(any("COMING SOON" in n for n in p["notes"]) and not p["steps"], "unsupported request is honest (COMING SOON)")

    print("undo / history / checkpoints")
    r = c.post(f"/api/v1/versions/{vid}/undo", headers=H).json()
    check(abs(r["view"]["timeline"]["duration"] - v2["timeline"]["duration"]) > 0.01, f"undo: {r['undone']}")
    r = c.post(f"/api/v1/versions/{vid}/redo", headers=H).json()
    check(r["redone"], "redo")
    first_op = v2["history"][0]
    r = c.patch(f"/api/v1/versions/{vid}/ops/{first_op['id']}", headers=H, json={"enabled": False}).json()
    check(r["view"]["timeline"]["duration"] > v2["timeline"]["duration"], f"undo an individual earlier op: {first_op['label']}")
    c.patch(f"/api/v1/versions/{vid}/ops/{first_op['id']}", headers=H, json={"enabled": True})
    cks = c.get(f"/api/v1/versions/{vid}", headers=H).json()["checkpoints"]
    check(len(cks) >= 2, f"{len(cks)} checkpoints recorded")
    before_ai = [ck for ck in cks if "first pass" in ck["label"]][-1]
    r = c.post(f"/api/v1/versions/{vid}/checkpoints/{before_ai['id']}/restore", headers=H).json()
    check(abs(r["view"]["timeline"]["duration"] - raw_dur) < 0.2, "restore checkpoint → original footage intact")
    cks = r["view"]["checkpoints"]
    c.post(f"/api/v1/versions/{vid}/checkpoints/{cks[0]['id']}/restore", headers=H)

    print("manual timeline edits")
    v = c.get(f"/api/v1/versions/{vid}", headers=H).json()
    clip = v["timeline"]["clips"][1]
    mid_t = (clip["s"] + clip["e"]) / 2
    r = c.post(f"/api/v1/versions/{vid}/ops", headers=H, json={"op": {"kind": "split", "params": {"media_id": clip["media_id"], "t": mid_t}, "label": "Split"}})
    check(len(r.json()["view"]["timeline"]["clips"]) == len(v["timeline"]["clips"]) + 1, "split clip")
    u = r.json()["view"]["timeline"]["clips"][2]["unit_id"]
    r = c.post(f"/api/v1/versions/{vid}/ops", headers=H, json={"op": {"kind": "props", "params": {"unit_id": u, "props": {"speed": 1.5, "volume": 1.2}}, "label": "Speed"}})
    check(r.status_code == 200, "speed/volume on a clip")
    w = next(w for w in r.json()["view"]["words"] if w["kept"])
    r = c.post(f"/api/v1/versions/{vid}/ops", headers=H, json={"op": {"kind": "remove", "params": {"ranges": [[w["media_id"], w["s"] - 0.03, w["e"] + 0.03]]}, "label": "Delete word"}})
    check(not next(x for x in r.json()["view"]["words"] if x["key"] == w["key"])["kept"], "transcript-based delete")
    r = c.post(f"/api/v1/versions/{vid}/ops", headers=H, json={"op": {"kind": "settings", "params": {"patch": {"captions": {"preset": "karaoke"}, "color": {"brightness": 0.03}, "audio": {"enhance": True}}}, "label": "Style"}})
    check(r.json()["view"]["caption_style"]["mode"] == "karaoke", "caption preset + color + audio settings")
    r = c.post(f"/api/v1/versions/{vid}/ops", headers=H, json={"op": {"kind": "bogus", "params": {}}})
    check(r.status_code == 400, "invalid op rejected")

    print("variations")
    p = c.post(f"/api/v1/versions/{vid}/plan", headers=H, json={"action": "generate_variations", "args": {"count": 3}}).json()
    print("    specs:", [(s["label"], (s["hook_text"] or "")[:35]) for s in p["variations"]])
    r = c.post(f"/api/v1/versions/{vid}/apply", headers=H, json={"steps": [], "variations": p["variations"], "title": "variations"}).json()
    check(len(r["versions"]) == 3, "3 ad versions created: " + "; ".join(x["name"] for x in r["versions"]))
    firsts = []
    for nv in r["versions"]:
        vv = c.get(f"/api/v1/versions/{nv['id']}", headers=H).json()
        firsts.append(" ".join(w["t"] for w in sorted([w for w in vv["words"] if w["kept"]], key=lambda w: w["tl"])[:6]))
    print("    openings:", firsts)
    check(len(set(firsts)) >= 2, "variations open differently")

    print("export")
    r = c.post(f"/api/v1/versions/{vid}/qc", headers=H, json={"settings": {"aspect": "9:16", "resolution": "1080p"}}).json()
    print("    pre-QC:", r["status"], [i["code"] for i in r["items"]])
    check(r["status"] != "fail", "pre-export QC passes")
    r = c.post(f"/api/v1/versions/{vid}/exports", headers=H, json={"settings": {"aspect": "9:16", "resolution": "1080p", "fps": 30, "quality": "balanced"}})
    eid = r.json()["id"]
    t0 = time.time()
    drain()
    print(f"    render+QC {time.time() - t0:.1f}s")
    ex = next(e for e in c.get("/api/v1/exports", headers=H).json() if e["id"] == eid)
    print("    post-QC:", ex["qc"]["post"]["status"], [i["message"] for i in ex["qc"]["post"]["items"]], ex.get("error"))
    check(ex["status"] == "done", "export finished")
    d = c.get(ex["download_url"])
    check(d.status_code == 200 and len(d.content) > 100_000, f"download works ({len(d.content) / 1e6:.1f} MB)")
    out = DATA / "out.mp4"
    out.write_bytes(d.content)
    import subprocess
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(out)], capture_output=True, text=True).stdout)
    vs = next(s for s in pr["streams"] if s["codec_type"] == "video")
    check((vs["width"], vs["height"]) == (1080, 1920), "export is 1080×1920 (9:16 1080p)")
    r = c.get(ex["download_url"].split("token=")[0] + "token=forged.1.x")
    check(r.status_code == 403, "forged media token rejected")
    shutil.copy(out, FX / "export_sample.mp4")

    print("isolation")
    r2 = c.post("/api/v1/auth/signup", json={"email": "other@example.com", "password": "password123"})
    H2 = {"Authorization": f"Bearer {r2.json()['token']}"}
    check(c.get(f"/api/v1/versions/{vid}", headers=H2).status_code == 404, "other user can't read project")
    check(c.get(f"/api/v1/products/{prod['id']}", headers=H2).status_code == 404, "other user can't read product")

with TestClient(app) as c:
    print("final-cut preview")
    H = {"Authorization": f"Bearer {tok}"}
    r = c.post(f"/api/v1/versions/{vid}/preview", headers=H, json={}).json()
    check(r["job"] or r["url"], "preview render queued")
    drain()
    v = c.get(f"/api/v1/versions/{vid}", headers=H).json()
    check(v["preview"]["url"], "preview file ready")
    f = c.get(v["preview"]["url"])
    import subprocess as _sp
    Path("/tmp/claude-0/pv.mp4").write_bytes(f.content)
    pr = json.loads(_sp.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", "/tmp/claude-0/pv.mp4"], capture_output=True, text=True).stdout)
    check(abs(float(pr["format"]["duration"]) - v["timeline"]["duration"]) < 0.2, f"preview length matches edit ({float(pr['format']['duration']):.2f}s vs {v['timeline']['duration']:.2f}s)")
    c.post(f"/api/v1/versions/{vid}/ops", headers=H, json={"op": {"kind": "settings", "params": {"patch": {"color": {"brightness": 0.05}}}, "label": "x"}})
    v2 = c.get(f"/api/v1/versions/{vid}", headers=H).json()
    check(v2["preview"]["hash"] != v["preview"]["hash"] and not v2["preview"]["url"], "editing invalidates the preview")

with TestClient(app) as c:
    H = {"Authorization": f"Bearer {tok}"}
    print("product B-roll")
    r = c.post(f"/api/v1/products/{prod['id']}/broll?filename=broll.mp4&label=clay%20jar%20close%20up%20texture", headers=H,
               content=(FX / "broll.mp4").read_bytes())
    check(r.status_code == 200 and len(r.json()["broll"]) == 1, "upload labelled B-roll clip")
    drain()
    pr_ = c.get(f"/api/v1/products/{prod['id']}", headers=H).json()
    check(pr_["broll"][0]["status"] == "ready", "B-roll processed (no transcription needed)")
    v = c.get(f"/api/v1/versions/{vid}", headers=H).json()
    check(len(v["broll_library"]) >= 2, f"B-roll library in editor ({len(v['broll_library'])} items incl. product photo)")
    p = c.post(f"/api/v1/versions/{vid}/plan", headers=H, json={"action": "add_broll"}).json()
    print("    ", [s_["label"] for s_ in p["steps"]], p["steps"][0]["detail"] if p["steps"] else p["notes"])
    check(p["steps"], "B-roll suggestions matched to lines")
    r = c.post(f"/api/v1/versions/{vid}/apply", headers=H, json={"steps": p["steps"], "title": p["title"]}).json()
    check(len(r["view"]["brolls"]) >= 1, f"{len(r['view']['brolls'])} B-roll shots on the timeline")

    print("text hook")
    v = r["view"]
    check(len(v["text_hook_ideas"]) >= 3, "text hook ideas: " + " | ".join(i["text"] for i in v["text_hook_ideas"][:4]))
    p = c.post(f"/api/v1/versions/{vid}/plan", headers=H, json={"action": "add_text_hook"}).json()
    r = c.post(f"/api/v1/versions/{vid}/apply", headers=H, json={"steps": p["steps"], "title": p["title"]}).json()
    hooks_ = [o for o in r["view"]["overlays"] if o["id"] == "hook"]
    check(hooks_ and hooks_[0]["t0"] < 0.05, f"text hook on screen at 0s: “{hooks_[0]['text'] if hooks_ else ''}”")

    print("retention map")
    v = c.get(f"/api/v1/versions/{vid}", headers=H).json()
    ret = v["retention"]
    check(len(ret["curve"]) > 10 and all(0 <= y <= 100 for _, y in ret["curve"]), "attention curve computed")
    print("     warnings:", [(w["kind"], w["t0"], (w.get("fix") or {}).get("action")) for w in ret["warnings"]])
    fixable = [w for w in ret["warnings"] if w.get("fix")]
    if fixable:
        f_ = fixable[0]["fix"]
        p = c.post(f"/api/v1/versions/{vid}/plan", headers=H, json={"action": f_["action"], "args": f_["args"]}).json()
        check(p["steps"] or p["notes"], f"one-tap fix '{f_['label']}' produces a plan")

    print("shop-safe check")
    from app.ai import compliance
    iss = compliance.scan([{"text": "It's only $19 and it's guaranteed to work, link in bio"}],
                          {"name": "x", "data": {"price": "14", "discount": "20% off"}})
    kinds = {i["issue"] for i in iss}
    check({"Price doesn't match the listing", "Guaranteed results", "Sends viewers off TikTok Shop"} <= kinds, "flags price mismatch, guarantee, off-platform CTA")
    iss2 = compliance.scan([{"text": "It's only $14 right now with 20% off"}], {"name": "x", "data": {"price": "14", "discount": "20% off"}})
    check(not iss2, "correct price/discount passes")
    check("shop_safe" in v and v["shop_safe"]["status"] in ("safe", "review", "risky"), f"shop-safe summary: {v['shop_safe']}")

    print("batch ads from pieces")
    print("     pieces:", len(v["pieces"]["hooks"]), "hooks,", len(v["pieces"]["ctas"]), "CTAs")
    p = c.post(f"/api/v1/versions/{vid}/plan", headers=H, json={"action": "batch_ads", "args": {"count": 4}}).json()
    check(len(p["variations"]) == 4, "4 distinct ad specs: " + "; ".join(f"{x['label']}/{(x['hook_text'] or '')[:18]}/{(x['cta_text'] or '')[:14]}" for x in p["variations"]))
    r = c.post(f"/api/v1/versions/{vid}/apply", headers=H, json={"steps": [], "variations": p["variations"], "title": p["title"]}).json()
    check(len(r["versions"]) == 4, "4 ad versions built")
    opens = set()
    for nv in r["versions"]:
        vv = c.get(f"/api/v1/versions/{nv['id']}", headers=H).json()
        kept = sorted([w for w in vv["words"] if w["kept"]], key=lambda w: w["tl"])
        opens.add(" ".join(w["t"] for w in kept[:4]))
    check(len(opens) >= 2, f"ads open differently: {opens}")

    print("performance learning")
    versions_ = [x["id"] for x in r["versions"]] + [vid]
    import random
    random.seed(3)
    for i, vv_id in enumerate(versions_):
        rr = c.post("/api/v1/performance", headers=H, json={"version_id": vv_id, "title": f"Ad {i}",
                                                             "metrics": {"views": 1000 + i * 700, "ctr": 1.0 + (2.5 if i % 2 == 0 else 0), "orders": 3 + i * 2, "gmv": 40 + i * 30}})
        check(rr.status_code == 200 and rr.json()["features"].get("duration"), f"results saved with edit snapshot (Ad {i})") if i < 1 else None
    pf = c.get("/api/v1/performance", headers=H).json()
    check(len(pf["entries"]) == len(versions_), f"{len(pf['entries'])} result entries")
    print("     insights:", [i_["text"] for i_ in pf["insights"][:3]])
    check(len(pf["insights"]) >= 1, "patterns found in creator's own data")
    r = c.post("/api/v1/performance/import", headers={**H, "Content-Type": "text/csv"},
               content=b"Video title,Video views,Likes,Orders,GMV\nOld video,12000,800,14,$210\n")
    check(r.status_code == 200 and r.json()["imported"] == 1, "CSV import from TikTok analytics export")

    print("export with B-roll + text hook")
    r = c.post(f"/api/v1/versions/{vid}/exports", headers=H, json={"settings": {"aspect": "9:16", "resolution": "720p", "fps": 30, "quality": "small"}})
    eid = r.json()["id"]
    drain()
    ex = next(e for e in c.get("/api/v1/exports", headers=H).json() if e["id"] == eid)
    print("     post-QC:", ex["qc"] and ex["qc"].get("post", {}).get("items"), ex.get("error"))
    check(ex["status"] == "done", "export with B-roll overlays + text hook succeeded")
    Path("/tmp/claude-0/export_features.mp4").write_bytes(c.get(ex["download_url"]).content)

print(f"\nALL {ok_count} CHECKS PASSED   (data dir {DATA})")
