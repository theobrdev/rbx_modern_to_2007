# rbx_modern_to_2007

A standalone Python converter that transforms modern Roblox XML files (`.rbxlx` / `.rbxmx`) into legacy XML `.rbxl` files compatible with the **March 2007 Roblox client (`0.3.368.0`)**.

Built for historical preservation, retro sandbox projects, and safely porting modern or re-saved classic maps back into early 2007 builds without crashing the legacy XML parser.

---

## Features

- **Zero External Dependencies:** Uses only Python's built-in `xml.etree.ElementTree` and standard libraries.
- **Smart Class & Geometry Mapping:** Converts `Part`, `WedgePart`, `MeshPart`, `UnionOperation`, `Seat`, and `SpawnLocation` into legacy `Part` / `SpawnLocation` instances while preserving `CFrame`, `Size`, `Shape`, `FormFactor`, `Anchored`, `CanCollide`, `Transparency`, `Reflectance`, `Locked`, and all 6 surface types.
- **Closest BrickColor Matching:** Compares modern `Color3uint8` / `Color3` values against the classic 2007 `PALETTE` using minimum RGB Euclidean distance.
- **Legacy Surface & Script Sanitization:**
  - Maps unsupported surface enums (`> 4`, such as `Universal` or `Hinge`) to `Smooth`.
  - Escapes script source strings to match the exact 2007 XML serializer (`&#13;&#10;`, `&#9;`, `&quot;`).
  - Converts `LocalScript` instances into disabled `Script` objects and flags scripts using post-2007 Lua syntax in the final summary.
- **Clean Tree Reconstruction:** Discards modern-only instances (`Terrain`, `Weld`, `Snap`, `Attachment`, attributes, and tags) and outputs a clean XML tree matching the March 2007 schema (`version="4"`).

---

## Requirements

- **Python 3.7+** (no `pip install` required)
- Input files must be saved in **Roblox XML format** (`.rbxlx` or `.rbxmx`).
  > *Tip: If you have a binary `.rbxl` file, open it in Roblox Studio and export it via **File -> Save to File As... -> Roblox XML Place Files (`*.rbxlx`)** first.*

---

## Usage

### Basic Conversion (Using Built-in Legacy Skeleton)
```bash
python rbx_modern_to_2007.py input.rbxlx output.rbxl
```

### Converting Using a 2007 Template File
If you have a clean March 2007 baseplate (`TabulaRasa.rbxl`), you can inject the converted objects directly into its `Workspace` to preserve exact header metadata and service ordering:
```bash
python rbx_modern_to_2007.py input.rbxlx output.rbxl --template TabulaRasa.rbxl
```

### Diagnostic & Filtering Options

| Flag | Description |
| :--- | :--- |
| `--template <file.rbxl>` | Uses an existing 2007 `.rbxl` file as the base XML skeleton. |
| `--max-parts <N>` | Limits the maximum number of converted parts (useful for testing large maps). |
| `--max-scripts <N>` | Limits the maximum number of converted scripts. |
| `--no-scripts` | Strips all `Script` and `LocalScript` instances during conversion (recommended for untrusted maps). |
| `--palette-from <file.rbxl>` | Extracts custom `BrickColor` palette references from an existing legacy place file. |

---

## How It Works

1. **Parsing:** Reads the `.rbxlx` or `.rbxmx` tree. If a `Workspace` exists, its children are traversed; if the input is a standalone model (`.rbxmx`), top-level items are converted.
2. **Tree Conversion:** Recursively maps modern instances to 2007 equivalents, calculates closest `BrickColor` IDs, and logs unsupported classes or modern Lua syntax warnings.
3. **Serialization:** Writes properties in the exact order expected by the `0.3.368.0` parser.
4. **Summary Report:** Prints a full breakdown of converted parts, models, scripts, fallback blocks, discarded objects, and potential script compatibility warnings.

---

## Disclaimer

This tool only processes user-supplied XML text files and does **not** include any proprietary Roblox executables, binaries, or copyrighted game assets.
