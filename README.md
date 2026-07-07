# Metop Constellation Diagram — Auto-Update Setup

This repository automatically updates the Metop constellation diagram daily
using the latest TLEs published by EUMETSAT, served via GitHub Pages.

---

## Files

| File | Purpose |
|---|---|
| `metop_constellation_v3.html` | The diagram (also served as the GitHub Pages site) |
| `update_diagram.py` | Fetches TLEs, recalculates positions, patches the HTML |
| `.github/workflows/update_diagram.yml` | GitHub Actions workflow — runs daily at 10:00 UTC |

---

## TLE Sources (all confirmed EUMETSAT URLs)

| Satellite | URL |
|---|---|
| Metop-B | `https://service.eumetsat.int/tle/data_out/latest_m01_tle.txt` |
| Metop-C | `https://service.eumetsat.int/tle/data_out/latest_m03_tle.txt` |
| Metop-SG A1 | `https://service.eumetsat.int/tle/data_out/latest_sga1_tle.txt` |

EUMETSAT typically publishes updated TLEs between 07:00–09:00 UTC daily.
The workflow runs at 10:00 UTC to ensure fresh data is available.

---

## One-time GitHub Setup

### 1. Create the repository

```bash
git init metop-constellation
cd metop-constellation
cp /path/to/metop_constellation_v3.html .
cp /path/to/update_diagram.py .
mkdir -p .github/workflows
cp /path/to/update_diagram.yml .github/workflows/
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/metop-constellation.git
git push -u origin main
```

### 2. Enable GitHub Pages

In your repository on GitHub:
- Go to **Settings → Pages**
- Under **Source**, select **Deploy from a branch**
- Choose **main** branch, **/ (root)** folder
- Click **Save**

Your diagram will be live at:
`https://YOUR_USERNAME.github.io/metop-constellation/metop_constellation_v3.html`

### 3. Ensure Actions can push

In **Settings → Actions → General**:
- Under **Workflow permissions**, select **Read and write permissions**
- Click **Save**

---

## Running manually

```bash
pip install requests
python3 update_diagram.py
```

The script will:
1. Fetch the latest TLEs from EUMETSAT for Metop-B, Metop-C, and Metop-SG A1
2. Propagate all three to a common epoch (Metop-B, latest)
3. Calculate phase separations (argument of latitude differences)
4. Calculate Metop-B LTAN from RAAN and Sun position
5. Compute canvas pixel positions and image rotations
6. Patch all values directly into `metop_constellation_v3.html`

---

## What updates automatically

Each daily run recalculates and patches:

- **TLE epoch constants** (`TLE_EPOCH_B`, `TLE_EPOCH_C`, `TLE_EPOCH_SGA1`)
- **Legend date** — derived from the latest epoch, shown as DD/MM/YYYY
- **Metop-B position** — canvas x/y, image rotation, arrow direction
- **Metop-SGA1 position** — canvas x/y, image rotation, arrow direction
- **Metop-B LTAN** — shown on the Metop-B label (e.g. "LTAN 20:52")
- **Metop-B to C arc label** — phase separation in degrees (bottom-right)
- **Metop-C to SGA1 arc label** — phase separation in degrees (bottom-left)

Metop-C is fixed at the 6 o'clock position (the reference for all
phase calculations) so its canvas position never changes.

---

## Diagram layout notes

- Orbit travels **counter-clockwise (CCW)**
- Metop-C fixed at **6 o'clock** (phase reference, LTAN 21:30)
- Metop-B on the **right**, showing LTAN drift label
- Metop-SGA1 on the **left**, drifting CCW toward 12 o'clock lead position
- Sun at **~1 o'clock** (geometrically correct for LTAN 21:30)
- Svalbard CDA ground station at correct geographic position on Earth globe
- **"Metop-C to SGA1"** arc label positioned at y=548 (above Key legend box)

---

## Minimum-token manual update (Claude chat)

If running outside the automated schedule, paste this into a new Claude chat
along with the current `metop_constellation_v3.html`:

> "Update my Metop diagram with these TLEs:
> Metop-B: [paste 2 lines]
> Metop-C: [paste 2 lines]
> Metop-SGA1: [paste 2 lines]
> Apply 6 regex substitutions: epoch constants, SGA1 block, B block,
> LTAN label (y=403), Metop-B to C arc (y=577), Metop-C to SGA1 arc (y=548).
> Return updated HTML."

**Always paste TLE lines directly** — web_fetch in Claude chat may return
cached results rather than the latest published TLEs.

---

## Future change — 14 July (Metop-SGA1 manoeuvre)

When Metop-SG A1 reaches its stable lead position at 12 o'clock:
- Metop-C to SGA1 arc: reposition to reflect ~180° stable separation
- C–SGA1 arc: Metop-SGB1 will drift into position between these two satellites
- Arc colours: consider making all three arcs orange (stable constellation)
