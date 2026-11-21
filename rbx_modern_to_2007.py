#!/usr/bin/env python3
"""
Converte um .rbxlx / .rbxmx moderno (2026) para o XML "version 4" no estilo
do tabulaRasa (Roblox 2007).

Uso:
    python rbx_modern_to_2007.py entrada.rbxlx saida.rbxl
    python rbx_modern_to_2007.py entrada.rbxmx saida.rbxl --with-baseplate

O que ele converte:
  - Part / WedgePart / TrussPart / MeshPart / UnionOperation / Seat / ... -> Part
    (formas que nao existem em 2007 viram bloco do mesmo tamanho)
  - SpawnLocation -> SpawnLocation
  - Model / Folder -> Model
  - Script -> Script (o codigo e copiado, mas PRECISA ser reescrito pra Lua 5.0)
  - LocalScript -> Script desabilitado
  - Color3 / Color3uint8 -> BrickColor mais proximo (paleta PALETTE abaixo)

Todo o resto (Attachments, Constraints, Terrain, Lighting moderno, Atributos,
Tags, SurfaceGuis, etc.) e descartado.
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from xml.sax.saxutils import escape

# Se a build rejeitar SpawnLocation, troque por "Part".
SPAWN_CLASS = "SpawnLocation"

# BrickColor classico -> RGB. Paleta parcial; adicione mais se precisar.
PALETTE = {
    1: (242, 243, 243), 5: (215, 197, 154), 9: (232, 186, 200),
    11: (128, 187, 219), 18: (204, 142, 105), 21: (196, 40, 28),
    23: (13, 105, 172), 24: (245, 205, 48), 26: (27, 42, 53),
    28: (40, 127, 71), 37: (75, 151, 75), 38: (160, 95, 53),
    45: (180, 210, 228), 101: (218, 134, 122), 102: (110, 153, 202),
    104: (107, 50, 124), 105: (226, 155, 64), 106: (218, 133, 65),
    119: (164, 189, 71), 124: (146, 57, 120), 125: (234, 184, 146),
    135: (116, 134, 157), 141: (39, 70, 45), 192: (105, 64, 40),
    194: (163, 162, 165), 199: (99, 95, 98), 217: (124, 92, 70),
    226: (253, 234, 141), 1001: (248, 248, 248), 1002: (205, 205, 205),
    1003: (17, 17, 17), 1004: (255, 0, 0), 1009: (255, 255, 0),
    1010: (0, 0, 255), 1011: (0, 32, 96), 1012: (33, 84, 185),
    1018: (18, 238, 212), 1019: (0, 255, 255), 1020: (0, 255, 0),
}

PART_LIKE = {
    "Part", "WedgePart", "CornerWedgePart", "TrussPart", "MeshPart",
    "UnionOperation", "NegateOperation", "Seat", "VehicleSeat", "SpawnLocation",
}
CONTAINERS = {"Model", "Folder"}
FACES = ["Back", "Bottom", "Front", "Left", "Right", "Top"]
CF_KEYS = ["X", "Y", "Z", "R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22"]
ID_CF = ["0", "0", "0", "1", "0", "0", "0", "1", "0", "0", "0", "1"]
LUA_SUSPECTS = {
    r"\btask\.": "task.* (nao existe)",
    r":Connect\(": ":Connect (em 2007 era :connect)",
    r"\+=|-=": "operadores += / -=",
    r"\bcontinue\b": "continue",
    r"#\w": "operador # (Lua 5.0 usa table.getn)",
    r"GetService": "GetService",
}

_ref = [100]


def ref():
    _ref[0] += 1
    return "RBX%d" % _ref[0]


# ---------------------------------------------------------------- leitura ---

def prop(item, name):
    props = item.find("Properties")
    if props is None:
        return None
    for el in props:
        if el.get("name") == name:
            return el
    low = name.lower()
    for el in props:
        if (el.get("name") or "").lower() == low:
            return el
    return None


def text(item, name, default=""):
    el = prop(item, name)
    if el is None or el.text is None:
        return default
    return el.text.strip()


def boolean(item, name, default):
    t = text(item, name)
    return default if t == "" else t.lower() == "true"


def number(item, name, default):
    try:
        return float(text(item, name))
    except ValueError:
        return default


def integer(item, name, default):
    try:
        return int(float(text(item, name)))
    except ValueError:
        return default


def brick_for(item):
    el = prop(item, "Color3uint8")
    if el is not None and el.text:
        v = int(el.text) & 0xFFFFFFFF
        rgb = ((v >> 16) & 255, (v >> 8) & 255, v & 255)
    else:
        el = prop(item, "Color")
        if el is not None and el.find("R") is not None:
            rgb = tuple(int(round(float(el.find(c).text) * 255)) for c in "RGB")
        else:
            el = prop(item, "BrickColor")
            if el is not None and el.text and int(el.text) in PALETTE:
                return int(el.text)
            return 194
    return min(PALETTE, key=lambda k: sum((a - b) ** 2 for a, b in zip(PALETTE[k], rgb)))


def read_part(item, cls, ctx):
    d = {"cls": SPAWN_CLASS if cls == "SpawnLocation" else "Part"}
    d["name"] = text(item, "Name", cls)

    cf = prop(item, "CFrame")
    d["cf"] = []
    for i, k in enumerate(CF_KEYS):
        el = cf.find(k) if cf is not None else None
        d["cf"].append(el.text if el is not None and el.text else ID_CF[i])

    sz = prop(item, "size")
    d["size"] = []
    for k, dflt in zip("XYZ", ("4", "1.2", "2")):
        el = sz.find(k) if sz is not None else None
        d["size"].append(el.text if el is not None and el.text else dflt)

    if cls in ("Part", "SpawnLocation"):
        s = integer(item, "shape", 1)
        d["shape"] = s if s in (0, 1, 2) else 1
    else:
        d["shape"] = 1
        if cls not in ("Seat", "VehicleSeat"):
            ctx["to_block"][cls] += 1

    ff = integer(item, "formFactorRaw", 1)
    d["form"] = ff if ff in (0, 1, 2) else 1

    d["brick"] = brick_for(item)
    d["anchored"] = boolean(item, "Anchored", False)
    d["cancollide"] = boolean(item, "CanCollide", True)
    d["transparency"] = number(item, "Transparency", 0.0)
    d["reflectance"] = number(item, "Reflectance", 0.0)
    d["locked"] = boolean(item, "Locked", False)

    d["surf"] = {}
    for f in FACES:
        v = integer(item, f + "Surface", 0)
        if v > 4:
            ctx["surf_fixed"] += 1
            v = 0
        d["surf"][f] = v
    return d


# --------------------------------------------------------------- escrita ---

def b(v):
    return "true" if v else "false"


def emit_part(d, ind, referent=None):
    t = "\t" * ind
    p = t + "\t\t"
    L = [f'{t}<Item class="{d["cls"]}" referent="{referent or ref()}">', f"{t}\t<Properties>"]
    L.append(f'{p}<bool name="Anchored">{b(d["anchored"])}</bool>')
    for f in ("Back", "Bottom"):
        L += [f'{p}<float name="{f}ParamA">-0.5</float>', f'{p}<float name="{f}ParamB">0.5</float>',
              f'{p}<token name="{f}Surface">{d["surf"][f]}</token>',
              f'{p}<token name="{f}SurfaceInput">0</token>']
    L.append(f'{p}<int name="BrickColor">{d["brick"]}</int>')
    L.append(f'{p}<CoordinateFrame name="CFrame">')
    for k, v in zip(CF_KEYS, d["cf"]):
        L.append(f"{p}\t<{k}>{v}</{k}>")
    L.append(f"{p}</CoordinateFrame>")
    L += [f'{p}<bool name="CanCollide">{b(d["cancollide"])}</bool>',
          f'{p}<bool name="CastsShadows">true</bool>',
          f'{p}<token name="Controller">0</token>',
          f'{p}<bool name="ControllerFlagShown">true</bool>',
          f'{p}<bool name="Cullable">true</bool>',
          f'{p}<bool name="DraggingV1">false</bool>',
          f'{p}<float name="Elasticity">0.5</float>',
          f'{p}<token name="FormFactor">{d["form"]}</token>',
          f'{p}<float name="Friction">0.300000012</float>']
    for f in ("Front", "Left"):
        L += [f'{p}<float name="{f}ParamA">-0.5</float>', f'{p}<float name="{f}ParamB">0.5</float>',
              f'{p}<token name="{f}Surface">{d["surf"][f]}</token>',
              f'{p}<token name="{f}SurfaceInput">0</token>']
    L += [f'{p}<bool name="Locked">{b(d["locked"])}</bool>',
          f'{p}<string name="Name">{escape(d["name"])}</string>',
          f'{p}<float name="Reflectance">{d["reflectance"]:.9g}</float>']
    for f in ("Right", "Top"):
        L += [f'{p}<float name="{f}ParamA">-0.5</float>', f'{p}<float name="{f}ParamB">0.5</float>',
              f'{p}<token name="{f}Surface">{d["surf"][f]}</token>',
              f'{p}<token name="{f}SurfaceInput">0</token>']
    L += [f'{p}<Vector3 name="RotVelocity">', f'{p}\t<X>0</X>', f'{p}\t<Y>0</Y>', f'{p}\t<Z>0</Z>', f'{p}</Vector3>',
          f'{p}<float name="Transparency">{d["transparency"]:.9g}</float>',
          f'{p}<Vector3 name="Velocity">', f'{p}\t<X>0</X>', f'{p}\t<Y>0</Y>', f'{p}\t<Z>0</Z>', f'{p}</Vector3>',
          f'{p}<bool name="archivable">true</bool>',
          f'{p}<token name="shape">{d["shape"]}</token>',
          f'{p}<Vector3 name="size">']
    for k, v in zip("XYZ", d["size"]):
        L.append(f"{p}\t<{k}>{v}</{k}>")
    L.append(f"{p}</Vector3>")
    L.append(f"{t}\t</Properties>")
    return L


def src_escape(src):
    """Escapa o codigo igual a build de 2007 (&#13;&#10;, &#9;, &quot;...)."""
    src = src.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for ch in src:
        if ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        elif ch == '"':
            out.append("&quot;")
        elif ch == "\n":
            out.append("&#13;&#10;")
        elif ch == "\t":
            out.append("&#9;")
        elif ord(ch) > 126 or ord(ch) < 32:
            out.append("&#%d;" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def emit_script(item, cls, ind, ctx):
    t = "\t" * ind
    p = t + "\t\t"
    name = text(item, "Name", cls)
    src_el = prop(item, "Source")
    src = (src_el.text or "") if src_el is not None else ""
    disabled = cls == "LocalScript" or boolean(item, "Disabled", False)
    if cls == "LocalScript":
        ctx["localscripts"].append(name)
    hits = [label for pat, label in LUA_SUSPECTS.items() if re.search(pat, src)]
    if hits:
        ctx["lua_warn"].append((name, hits))
    src = src_escape(src)
    return [f'{t}<Item class="Script" referent="{ref()}">',
            f"{t}\t<Properties>",
            f'{p}<bool name="Disabled">{b(disabled)}</bool>',
            f'{p}<string name="Name">{escape(name)}</string>',
            f'{p}<string name="Source">{src}</string>',
            f'{p}<bool name="archivable">true</bool>',
            f"{t}\t</Properties>",
            f"{t}</Item>"]


def convert(item, ind, ctx):
    cls = item.get("class")
    kids = item.findall("Item")
    if cls in PART_LIKE:
        if ctx["limit"] is not None and ctx["parts"] >= ctx["limit"]:
            ctx["skipped_limit"] += 1
            return []
        d = read_part(item, cls, ctx)
        ctx["parts"] += 1
        L = emit_part(d, ind)
        for k in kids:
            L += convert(k, ind + 1, ctx)
        L.append("\t" * ind + "</Item>")
        return L
    if cls in CONTAINERS:
        t = "\t" * ind
        ctx["models"] += 1
        L = [f'{t}<Item class="Model" referent="{ref()}">', f"{t}\t<Properties>",
             f'{t}\t\t<string name="Name">{escape(text(item, "Name", cls))}</string>',
             f'{t}\t\t<bool name="archivable">true</bool>', f"{t}\t</Properties>"]
        for k in kids:
            L += convert(k, ind + 1, ctx)
        L.append(f"{t}</Item>")
        return L
    if cls in ("Script", "LocalScript"):
        if ctx["no_scripts"] or (ctx["max_scripts"] is not None and ctx["scripts"] >= ctx["max_scripts"]):
            return []
        ctx["scripts"] += 1
        return emit_script(item, cls, ind, ctx)
    if cls not in ("Terrain", "Camera"):
        ctx["dropped"][cls] += 1
    return []


# ---------------------------------------------------------------- esqueleto ---

HEAD = """<roblox xmlns:xmime="http://www.w3.org/2005/05/xmlmime" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://www.roblox.com/roblox.xsd" version="4">
	<External>null</External>
	<External>nil</External>
	<Item class="Workspace" referent="RBX0">
		<Properties>
			<token name="Controller">0</token>
			<bool name="ControllerFlagShown">true</bool>
			<Ref name="CurrentCamera">RBX1</Ref>
			<CoordinateFrame name="ModelInPrimary">
				<X>0</X><Y>0</Y><Z>0</Z>
				<R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>0</R20><R21>0</R21><R22>1</R22>
			</CoordinateFrame>
			<string name="Name">Workspace</string>
			<Ref name="PrimaryPart">%s</Ref>
			<bool name="archivable">true</bool>
		</Properties>
		<Item class="Camera" referent="RBX1">
			<Properties>
				<Ref name="CameraSubject">null</Ref>
				<token name="CameraType">0</token>
				<CoordinateFrame name="CoordinateFrame">
					<X>237.565613</X><Y>145.16185</Y><Z>-223.038544</Z>
					<R00>-0.65920645</R00><R01>-0.379247129</R01><R02>0.649321735</R02>
					<R10>-1.49011612e-008</R10><R11>0.863503218</R11><R12>0.50434339</R12>
					<R20>-0.751962125</R20><R21>0.332466334</R21><R22>-0.569226921</R22>
				</CoordinateFrame>
				<CoordinateFrame name="Focus">
					<X>224.579178</X><Y>135.074982</Y><Z>-211.654007</Z>
					<R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>0</R20><R21>0</R21><R22>1</R22>
				</CoordinateFrame>
				<string name="Name">Camera</string>
				<bool name="archivable">true</bool>
			</Properties>
		</Item>
"""

TAIL = """	</Item>
	<Item class="RunService" referent="RBX3">
		<Properties>
			<string name="Name">Run Service</string>
			<bool name="archivable">true</bool>
		</Properties>
	</Item>
	<External>RBX4</External>
	<External>RBX5</External>
	<Item class="Players" referent="RBX6">
		<Properties>
			<int name="MaxPlayers">12</int>
			<string name="Name">Players</string>
			<bool name="archivable">true</bool>
		</Properties>
	</Item>
	<Item class="StarterPack" referent="RBX7">
		<Properties>
			<string name="Name">StarterPack</string>
			<bool name="archivable">true</bool>
		</Properties>
	</Item>
	<Item class="SoundService" referent="RBX8">
		<Properties>
			<float name="DistanceFactor">10</float>
			<float name="DopplerScale">1</float>
			<string name="Name">Soundscape</string>
			<float name="RolloffScale">1</float>
			<bool name="archivable">true</bool>
		</Properties>
		<External>RBX9</External><External>RBX10</External><External>RBX11</External>
		<External>RBX12</External><External>RBX13</External><External>RBX14</External>
		<External>RBX15</External><External>RBX16</External><External>RBX17</External>
		<External>RBX18</External><External>RBX19</External><External>RBX20</External>
		<External>RBX21</External><External>RBX22</External>
	</Item>
	<Item class="Selection" referent="RBX23">
		<Properties>
			<string name="Name">Selection</string>
			<bool name="archivable">true</bool>
		</Properties>
	</Item>
	<Item class="Lighting" referent="RBX24">
		<Properties>
			<Color3 name="BottomAmbientV9">4286220152</Color3>
			<Color3 name="ClearColor">4278190080</Color3>
			<float name="GeographicLatitude">41.7332993</float>
			<string name="Name">Lighting</string>
			<Color3 name="SpotLightV9">4290822336</Color3>
			<string name="TimeOfDay">14:00:00</string>
			<Color3 name="TopAmbientV9">4292006362</Color3>
			<bool name="archivable">true</bool>
		</Properties>
	</Item>
	<Item class="ControllerService" referent="RBX25">
		<Properties>
			<string name="Name">Instance</string>
			<bool name="archivable">true</bool>
		</Properties>
	</Item>
	<External>RBX26</External>
	<External>RBX27</External>
	<External>RBX28</External>
</roblox>
"""

BASEPLATE = {
    "cls": "Part", "name": "Part", "cf": ["0", "0.600000024"] + ID_CF[2:],
    "size": ["512", "1.20000005", "512"], "shape": 1, "form": 1, "brick": 28,
    "anchored": True, "cancollide": True, "transparency": 0.0, "reflectance": 0.0,
    "locked": True, "surf": {"Back": 0, "Bottom": 4, "Front": 0, "Left": 0, "Right": 0, "Top": 3},
}


# --------------------------------------------------------------------- main ---

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada")
    ap.add_argument("saida")
    ap.add_argument("--with-baseplate", action="store_true",
                    help="inclui o chao verde 512x512 do tabulaRasa")
    ap.add_argument("--template", help="usa um .rbxl real da build (ex: TabulaRasa.rbxl) como esqueleto")
    ap.add_argument("--max-parts", type=int, default=None, help="converte so as N primeiras Parts (para testes)")
    ap.add_argument("--no-scripts", action="store_true", help="nao copia Scripts")
    ap.add_argument("--max-scripts", type=int, default=None, help="copia so os N primeiros Scripts (para testes)")
    ap.add_argument("--palette-from", nargs="+", metavar="RBXL",
                    help="usa so BrickColors que aparecem nesses .rbxl de 2007")
    a = ap.parse_args()

    if a.palette_from:
        used = set()
        for fn in a.palette_from:
            with open(fn, "r", encoding="latin-1") as fh:
                used |= {int(x) for x in re.findall(r'name="BrickColor">(\d+)<', fh.read())}
        keep = {k: v for k, v in PALETTE.items() if k in used}
        if keep:
            PALETTE.clear()
            PALETTE.update(keep)
            print("Paleta restrita a:", sorted(keep))

    root = ET.parse(a.entrada).getroot()
    ws = next((i for i in root.findall("Item") if i.get("class") == "Workspace"), None)
    top = ws.findall("Item") if ws is not None else root.findall("Item")

    ctx = {"parts": 0, "models": 0, "scripts": 0, "surf_fixed": 0,
           "to_block": Counter(), "dropped": Counter(),
           "localscripts": [], "lua_warn": [],
           "limit": a.max_parts, "no_scripts": a.no_scripts, "max_scripts": a.max_scripts, "skipped_limit": 0}

    body = []
    for it in top:
        body += convert(it, 2, ctx)

    if a.template:
        with open(a.template, "r", encoding="latin-1", newline="") as fh:
            tpl = fh.read()
        nl = "\r\n" if "\r\n" in tpl else "\n"
        m = re.search(r'<Item class="RunService"', tpl)
        if not m:
            sys.exit("template: nao achei o RunService")
        close = tpl.rfind("</Item>", 0, m.start())
        ls = tpl.rfind("\n", 0, close) + 1
        out = tpl[:ls] + "".join(line + nl for line in body) + tpl[ls:]
        with open(a.saida, "w", encoding="latin-1", errors="replace", newline="") as f:
            f.write(out)
    else:
        out = HEAD % ("RBX2" if a.with_baseplate else "null")
        if a.with_baseplate:
            out += "\n".join(emit_part(BASEPLATE, 2, referent="RBX2") + ["\t\t</Item>"]) + "\n"
        out += "\n".join(body) + ("\n" if body else "") + TAIL
        with open(a.saida, "w", encoding="utf-8", newline="\n") as f:
            f.write(out)

    print(f"OK -> {a.saida}")
    print(f"  Parts: {ctx['parts']} | Models: {ctx['models']} | Scripts: {ctx['scripts']}")
    if ctx["skipped_limit"]:
        print(f"  Parts puladas por --max-parts: {ctx['skipped_limit']}")
    if ctx["to_block"]:
        print("  Viraram bloco:", dict(ctx["to_block"]))
    if ctx["dropped"]:
        print("  Descartados:", dict(ctx["dropped"]))
    if ctx["surf_fixed"]:
        print(f"  {ctx['surf_fixed']} superficie(s) sem equivalente viraram Smooth")
    if ctx["localscripts"]:
        print("  LocalScripts (viraram Script desabilitado):", ", ".join(ctx["localscripts"]))
    for name, hits in ctx["lua_warn"]:
        print(f"  Script '{name}' usa coisas modernas: {', '.join(hits)}")


if __name__ == "__main__":
    sys.exit(main())
