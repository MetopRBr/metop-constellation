#!/usr/bin/env python3
"""
update_diagram.py
-----------------
Fetches the latest Metop TLEs from EUMETSAT, recalculates satellite phase
positions and LTAN, then patches the constants and drawing coordinates in
metop_constellation_v3.html.

Run manually:   python3 update_diagram.py
Run via cron:   0 10 * * * /usr/bin/python3 /path/to/update_diagram.py
"""

import math
import re
import sys
import requests
from datetime import datetime, timezone

# ── TLE sources — all confirmed EUMETSAT URLs ─────────────────────────────
# Metop-B  : https://service.eumetsat.int/tle/data_out/latest_m01_tle.txt
# Metop-C  : https://service.eumetsat.int/tle/data_out/latest_m03_tle.txt
# Metop-SGA1: https://service.eumetsat.int/tle/data_out/latest_sga1_tle.txt
EUMETSAT_URLS = {
    'B':    'https://service.eumetsat.int/tle/data_out/latest_m01_tle.txt',
    'C':    'https://service.eumetsat.int/tle/data_out/latest_m03_tle.txt',
    'SGA1': 'https://service.eumetsat.int/tle/data_out/latest_sga1_tle.txt',
}

# CelesTrak fallback for Metop-SGA1 (NORAD ID 65159) in case EUMETSAT is unavailable
SGA1_CELESTRAK_URL  = 'https://celestrak.org/SOCRATES/query.php?CATNR=65159&format=tle'
SGA1_CELESTRAK_URL2 = 'https://celestrak.org/satcat/tle.php?CATNR=65159'

# HTML file to patch
HTML_FILE = 'metop_constellation_v3.html'

# ── TLE fetching ───────────────────────────────────────────────────────────

def fetch_url(url, timeout=10):
    """Fetch URL, return text or None on failure."""
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200 and r.text.strip():
            return r.text.strip()
    except Exception:
        pass
    return None


def fetch_tle(sat_name):
    """Fetch TLE lines for a satellite. Returns (line1, line2) or raises.
    
    Primary source: EUMETSAT confirmed URLs for all three satellites.
    Fallback for SGA1: CelesTrak (NORAD ID 65159) if EUMETSAT unavailable.
    """
    # Try EUMETSAT primary source first (all three satellites now have confirmed URLs)
    text = fetch_url(EUMETSAT_URLS[sat_name])
    if text:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) >= 2 and lines[0].startswith('1 '):
            print(f"  Metop-{sat_name}: fetched from EUMETSAT")
            return lines[0], lines[1]

    # CelesTrak fallback (SGA1 only — B and C not on CelesTrak weather group)
    if sat_name == 'SGA1':
        for url in [SGA1_CELESTRAK_URL, SGA1_CELESTRAK_URL2]:
            text = fetch_url(url)
            if text:
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                for i, line in enumerate(lines):
                    if line.startswith('1 65159') and i + 1 < len(lines):
                        print(f"  Metop-SGA1: fetched from CelesTrak (fallback)")
                        return lines[i], lines[i+1]

    raise RuntimeError(
        f"Failed to fetch Metop-{sat_name} TLE from EUMETSAT"
        + (" and CelesTrak" if sat_name == 'SGA1' else "")
    )


# ── TLE parsing ────────────────────────────────────────────────────────────

def parse_tle(line1, line2):
    """Parse TLE lines into a dict of orbital elements."""
    epoch_str = line1[18:32].strip()
    return {
        'epoch':  float(epoch_str),
        'inc':    float(line2[8:16]),
        'raan':   float(line2[17:25]),
        'ecc':    float('0.' + line2[26:33].strip()),
        'argp':   float(line2[34:42]),
        'ma':     float(line2[43:51]),
        'mm':     float(line2[52:63]),
    }


# ── Orbital calculations ───────────────────────────────────────────────────

def propagate_ma(ma0, mm, dt_days):
    """Propagate mean anomaly by dt_days at mean motion mm (rev/day)."""
    return (ma0 + mm * 360.0 * dt_days) % 360.0


def arg_of_latitude(argp, ma):
    """Argument of latitude u = argp + MA (valid for near-circular orbits)."""
    return (argp + ma) % 360.0


def phase_ahead(u_a, u_b):
    """Degrees that satellite A is ahead of B in CCW direction of travel."""
    return (u_a - u_b) % 360.0


def canvas_position(ahead_of_c_deg):
    """
    Map phase position to canvas (x, y, rotation, arrow points).
    Metop-C is fixed at 6-o'clock (parametric angle = pi/2).
    Orbit travels CCW → ahead = decreasing parametric angle.
    Ellipse: centre (350,365), rx=240, ry=250.
    """
    cx, cy, rx, ry = 350, 365, 240, 250
    angle = math.pi / 2 - math.radians(ahead_of_c_deg)
    x = cx + rx * math.cos(angle)
    y = cy + ry * math.sin(angle)
    rot = math.pi / 2 + angle          # image rotation (nose CCW)
    tx = -math.sin(angle)              # CCW tangent
    ty =  math.cos(angle)
    arr1 = (x - tx * 30, y - ty * 30)  # arrow tail
    arr2 = (x - tx * 52, y - ty * 52)  # arrow head
    return angle, x, y, rot, arr1, arr2


def compute_ltan(raan_deg, epoch_yyddd):
    """
    Compute LTAN (Local Time of Ascending Node) from RAAN and TLE epoch.
    Returns decimal hours (0–24).
    """
    yy  = math.floor(epoch_yyddd / 1000)
    ddd = epoch_yyddd - yy * 1000
    year = 2000 + yy

    # Julian Date of 1 Jan of that year
    Y, M, D = year, 1, 1
    jd_jan1 = (367*Y - int(7*(Y + int((M+9)/12))/4)
               + int(275*M/9) + D + 1721013.5)
    jd = jd_jan1 + (ddd - 1)

    # Julian centuries since J2000.0
    T = (jd - 2451545.0) / 36525.0

    # Sun's geometric mean longitude and mean anomaly
    L0    = (280.46646 + 36000.76983 * T) % 360.0
    M_sun = (357.52911 + 35999.05029 * T - 0.0001537 * T**2) % 360.0
    M_r   = math.radians(M_sun)

    # Equation of centre
    C = ((1.914602 - 0.004817*T - 0.000014*T**2) * math.sin(M_r)
         + (0.019993 - 0.000101*T) * math.sin(2*M_r)
         + 0.000289 * math.sin(3*M_r))

    sun_lon = L0 + C
    eps     = 23.439291 - 0.013004 * T
    eps_r   = math.radians(eps)
    lon_r   = math.radians(sun_lon)

    sun_ra  = math.degrees(math.atan2(
        math.cos(eps_r) * math.sin(lon_r), math.cos(lon_r)
    )) % 360.0

    ltan = (12.0 + (raan_deg - sun_ra) / 15.0) % 24.0
    return ltan


def ltan_str(ltan_hours):
    """Format decimal hours as HH:MM."""
    h = int(ltan_hours)
    m = int((ltan_hours - h) * 60)
    return f"{h:02d}:{m:02d}"


def epoch_to_date(epoch_yyddd):
    """Convert TLE epoch yyddd.fraction to DD/MM/YYYY string."""
    yy  = math.floor(epoch_yyddd / 1000)
    ddd = epoch_yyddd - yy * 1000
    year = 2000 + yy
    import datetime as dt
    jan1 = dt.datetime(year, 1, 1)
    d = jan1 + dt.timedelta(days=ddd - 1)
    return d.strftime('%d/%m/%Y')


# ── HTML patching ──────────────────────────────────────────────────────────

def patch_html(html, elems, results):
    """Patch TLE epoch constants, satellite positions, LTAN and date in HTML."""

    b  = elems['B']
    c  = elems['C']
    sg = elems['SGA1']

    # 1. TLE epoch constants
    html = re.sub(
        r'const TLE_EPOCH_B\s*=\s*[\d.]+;.*',
        f"const TLE_EPOCH_B    = {b['epoch']};  // Metop-B   (EUMETSAT)",
        html
    )
    html = re.sub(
        r'const TLE_EPOCH_C\s*=\s*[\d.]+;.*',
        f"const TLE_EPOCH_C    = {c['epoch']};  // Metop-C   (EUMETSAT)",
        html
    )
    html = re.sub(
        r'const TLE_EPOCH_SGA1\s*=\s*[\d.]+;.*',
        f"const TLE_EPOCH_SGA1 = {sg['epoch']};  // Metop-SGA1 (EUMETSAT)",
        html
    )

    # 2. Metop-B canvas block
    b_x, b_y   = results['B']['pos']
    b_rot      = results['B']['rot']
    b_a1       = results['B']['arr1']
    b_a2       = results['B']['arr2']
    b_ltan     = results['B']['ltan_str']
    b_phase    = results['B']['phase']

    html = re.sub(
        r'(// ── Metop-B at )[\d.]+°( ahead of Metop-C \(TLE-derived, )\S+(\) ─+\n'
        r'  // Phase angle from TLEs: B is )[\d.]+°( CCW ahead of C \(at 6 o\'clock\)\n'
        r'  // Parametric angle on ellipse: [^\n]+\n'
        r'  // Image rotation: [^\n]+\n'
        r'  ctx\.save\(\);\n'
        r'  ctx\.translate\([^)]+\);\n'
        r'  ctx\.rotate\([^)]+\);\n'
        r'  ctx\.drawImage\(imgBC,[^)]+\);\n'
        r'  ctx\.restore\(\);\n'
        r'  // Arrow in direction of travel[^\n]+\n'
        r'  arrow\(ctx,[^)]+\);',
        f"""// ── Metop-B at {b_phase:.2f}° ahead of Metop-C (TLE-derived, {epoch_to_date(b['epoch'])}) ────────
  // Phase angle from TLEs: B is {b_phase:.2f}° CCW ahead of C (at 6 o'clock)
  // Parametric angle on ellipse: {math.degrees(results['B']['angle']):.2f}° → canvas position (~{b_x:.0f}, {b_y:.0f})
  // Image rotation: π/2 + angle = {b_rot:.4f} rad ({math.degrees(b_rot):.2f}°)
  ctx.save();
  ctx.translate({b_x:.1f},{b_y:.1f});
  ctx.rotate({b_rot:.4f});
  ctx.drawImage(imgBC,-75,-46,150,92);
  ctx.restore();
  // Arrow in direction of travel (CCW tangent at this position)
  arrow(ctx,{b_a1[0]:.1f},{b_a1[1]:.1f},{b_a2[0]:.1f},{b_a2[1]:.1f},'#e53935');""",
        html
    )

    # 3. Metop-B LTAN text
    html = re.sub(
        r"ctx\.fillText\('LTAN \d+:\d+',\d+,\d+\);",
        f"ctx.fillText('LTAN {b_ltan}',671,403);",
        html
    )

    # 4. Metop-SGA1 canvas block
    sg_x, sg_y = results['SGA1']['pos']
    sg_rot     = results['SGA1']['rot']
    sg_a1      = results['SGA1']['arr1']
    sg_a2      = results['SGA1']['arr2']
    sg_phase   = results['SGA1']['phase']
    sg_behind  = 360.0 - sg_phase

    html = re.sub(
        r'(// ── Metop-SGA1 — EUMETSAT TLE \()\S+(\) ─+\n'
        r'  // TLE epoch [^\n]+\n'
        r'  // SGA1 AoL [^\n]+\n'
        r'  // Phase: [^\n]+\n'
        r'  // Canvas position: [^\n]+\n'
        r'  ctx\.save\(\);\n'
        r'  ctx\.translate\([^)]+\);\n'
        r'  ctx\.rotate\([^)]+\);\n'
        r'  ctx\.drawImage\(imgSGA1,[^)]+\);\n'
        r'  ctx\.restore\(\);\n'
        r'  // Arrow in direction of travel[^\n]+\n'
        r'  arrow\(ctx,[^)]+\);',
        f"""// ── Metop-SGA1 — EUMETSAT TLE ({epoch_to_date(sg['epoch'])}) ─────────────────────────────
  // TLE epoch {sg['epoch']}, propagated to common epoch {b['epoch']}
  // SGA1 AoL {results['SGA1']['aol']:.2f}deg, Metop-C AoL {results['C']['aol']:.2f}deg
  // Phase: {sg_phase:.2f}deg CCW ahead of Metop-C (= {sg_behind:.2f}deg behind C), drifting toward lead
  // Canvas position: ({sg_x:.1f}, {sg_y:.1f}), rotation: {sg_rot:.4f} rad ({math.degrees(sg_rot):.2f}deg)
  ctx.save();
  ctx.translate({sg_x:.1f}, {sg_y:.1f});
  ctx.rotate({sg_rot:.4f});
  ctx.drawImage(imgSGA1,-75,-45,150,91);
  ctx.restore();
  // Arrow in direction of travel (CCW tangent at this position)
  arrow(ctx,{sg_a1[0]:.1f},{sg_a1[1]:.1f},{sg_a2[0]:.1f},{sg_a2[1]:.1f},'#e53935');""",
        html
    )

    # 5. Arc angle labels
    html = re.sub(
        r"ctx\.fillText\('Metop-B to C: [\d.]+°', 543, 577\);",
        f"ctx.fillText('Metop-B to C: {b_phase:.1f}°', 543, 577);",
        html
    )
    html = re.sub(
        r"ctx\.fillText\('Metop-C to SGA1: [\d.]+°', 153, 548\);",
        f"ctx.fillText('Metop-C to SGA1: {360-sg_phase:.1f}°', 153, 548);",
        html
    )

    return html


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"Metop diagram updater — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print('='*60)

    # 1. Fetch TLEs
    print("\nFetching TLEs...")
    raw = {}
    elems = {}
    for sat in ('B', 'C', 'SGA1'):
        try:
            l1, l2 = fetch_tle(sat)
            raw[sat] = (l1, l2)
            elems[sat] = parse_tle(l1, l2)
            print(f"    epoch={elems[sat]['epoch']}, RAAN={elems[sat]['raan']:.4f}°")
        except RuntimeError as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    # 2. Propagate to common epoch (Metop-B, latest)
    ref = elems['B']['epoch']
    print(f"\nPropagating to common epoch {ref} ({epoch_to_date(ref)})...")

    results = {}
    for sat in ('B', 'C', 'SGA1'):
        dt = ref - elems[sat]['epoch']
        ma_ref = propagate_ma(elems[sat]['ma'], elems[sat]['mm'], dt)
        aol    = arg_of_latitude(elems[sat]['argp'], ma_ref)
        results[sat] = {'aol': aol}

    # 3. Phase separations relative to Metop-C
    for sat in ('B', 'SGA1'):
        phase = phase_ahead(results[sat]['aol'], results['C']['aol'])
        results[sat]['phase'] = phase
        print(f"  Metop-{sat} ahead of C: {phase:.2f}°  (behind: {360-phase:.2f}°)")

    # 4. Canvas positions
    for sat in ('B', 'SGA1'):
        angle, x, y, rot, arr1, arr2 = canvas_position(results[sat]['phase'])
        results[sat].update({
            'angle': angle, 'pos': (x, y), 'rot': rot,
            'arr1': arr1, 'arr2': arr2
        })

    # 5. LTAN for Metop-B
    ltan_b = compute_ltan(elems['B']['raan'], elems['B']['epoch'])
    results['B']['ltan']     = ltan_b
    results['B']['ltan_str'] = ltan_str(ltan_b)
    ltan_c = compute_ltan(elems['C']['raan'], elems['C']['epoch'])
    print(f"\n  Metop-B  LTAN: {ltan_str(ltan_b)}  (drift from 21:30: {(ltan_b-21.5)*60:+.1f} min)")
    print(f"  Metop-C  LTAN: {ltan_str(ltan_c)}  (drift from 21:30: {(ltan_c-21.5)*60:+.1f} min)")

    # 6. Patch HTML
    print(f"\nPatching {HTML_FILE}...")
    with open(HTML_FILE, 'r') as f:
        html = f.read()

    html = patch_html(html, elems, results)

    with open(HTML_FILE, 'w') as f:
        f.write(html)

    print(f"  Done — diagram updated for {epoch_to_date(ref)}")
    print('='*60 + '\n')


if __name__ == '__main__':
    main()
