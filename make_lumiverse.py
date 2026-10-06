"""Write Arena's Lumiverse from the rig: every par and bar segment at its DMX
address and its point on the control band (band.py), into an Advanced Output
preset. Arena keeps its own fixture types; this only places them.

    python3 make_lumiverse.py                 # into the preset "Intermission"
    python3 make_lumiverse.py --preset Other

The preset must already hold one "led par" and one "led bar pixel rgbwa" fixture
(the templates). It is backed up to Compositions/.backup/ first. Then, in Arena:
Output → Advanced… → the preset menu → load it again (Arena reads it from disk).
Bars are 12 RGBWA fixtures of 5 channels, 6 apart: the 6th (UV) stays 0.
"""
import argparse, copy, os, shutil, time
import xml.etree.ElementTree as ET
import band

ARENA = os.path.expanduser("~/Documents/Resolume Arena")
Y0, Y1 = 1080, 1200                      # the band: the bottom 120 rows of 1920x1200


def name_of(s):
    return s.find("Params[@name='Common']/Param[@name='Name']").get("value")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="Intermission")
    a = ap.parse_args()
    path = os.path.join(ARENA, "Presets", "Advanced Output", a.preset + ".xml")
    root = ET.parse(path).getroot()
    layers = root.find(".//DmxScreen").find("layers")
    slices = layers.findall("DmxSlice")
    par_t = next(s for s in slices if "led par" in name_of(s))
    bar_t = next(s for s in slices if "rgbwa" in name_of(s))
    rig = band.load("rig.json", {"fixtures": []})
    fx = {f["name"]: f for f in rig["fixtures"]}
    profiles = band.load("fixtures.json", {}).get("profiles", {})

    bak = os.path.join(ARENA, "Compositions", ".backup")
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(path, os.path.join(bak, f"AdvancedOutput {a.preset} {time.strftime('%Y-%m-%d_%H%M%S')}.xml"))

    for s in slices:
        layers.remove(s)
    uid = int(time.time() * 1000)

    def make(t, name, ch, x0, x1):
        nonlocal uid
        s = copy.deepcopy(t)
        uid += 1
        s.set("uniqueId", str(uid))
        s.find("Params[@name='Common']/Param[@name='Name']").set("value", name)
        sc = s.find("Params[@name='Input']/ParamRange[@name='Start Channel']")
        sc.set("value", str(ch))
        sc.find("PhaseSourceStatic").set("phase", repr((ch - 1) / (131072 - 1)))
        for v, (x, y) in zip(s.find("InputRect").findall("v"), [(x0, Y0), (x1, Y0), (x1, Y1), (x0, Y1)]):
            v.set("x", str(x)); v.set("y", str(y))
        layers.append(s)

    n = 0
    for c in band.layout():
        f = fx[c["name"]]
        if c["kind"] == "par":
            make(par_t, f"{c['name']} · {f['address']} - {f['address'] + 3} led par", f["address"], c["x0"], c["x1"])
            n += 1
            continue
        mode = (profiles.get(f.get("profile"), {}).get("modes") or {}).get(f.get("mode", "72ch"), {})
        stride = len(mode.get("per_pixel") or "rgbwau")
        k = len(c["samples"])
        w = (c["x1"] - c["x0"]) / k
        for i in range(k):
            ch = f["address"] + stride * i
            make(bar_t, f"{c['name']} px{i + 1:02d} · {ch} - {ch + 4} led bar pixel rgbwa", ch,
                 round(c["x0"] + w * i), round(c["x0"] + w * (i + 1)))
            n += 1
    tmp = path + ".tmp"
    open(tmp, "w", encoding="utf-8").write('<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode"))
    os.replace(tmp, path)
    print(f"[lumiverse] {n} fixtures into {a.preset}: load the preset again in Arena's Advanced Output")


if __name__ == "__main__":
    main()
