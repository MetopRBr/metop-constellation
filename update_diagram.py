#!/usr/bin/env python3
import math
import re
import sys
import requests
from datetime import datetime, timezone

EUMETSAT_URLS = {
    'B':    'https://service.eumetsat.int/tle/data_out/latest_m01_tle.txt',
    'C':    'https://service.eumetsat.int/tle/data_out/latest_m03_tle.txt',
    'SGA1': 'https://service.eumetsat.int/tle/data_out/latest_sga1_tle.txt',
}
SGA1_CELESTRAK_URL  = 'https://celestrak.org/SOCRATES/query.php?CATNR=65159&format=tle'
SGA1_CELESTRAK_URL2 = 'https://celestrak.org/satcat/tle.php?CATNR=65159'
HTML_FILE = 'metop_constellation_v3.html'

def fetch_url(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200 and r.text.strip():
            return r.text.strip()
    except Exception:
        pass
    return None

def fetch_tle(sat_name):
    text = fetch_url(EUMETSAT_URLS[sat_name])
    if text:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) >= 2 and lines[0].startswith('1 '):
            print(f"  Metop-{sat_name}: fetched from EUMETSAT")
            return lines[0], lines[1]
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

def parse_tle(line1, line2):
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

def propagate_ma(ma0, mm, dt_days):
    return (ma0 + mm * 360.0 * dt_days) % 360.0

def arg_of_latitude(argp, ma):
    return (argp + ma) % 360.0

def phase_ahead(u_a, u_b):
    return (u_a - u_b) % 360.0

def canvas_position(ahead_of_c_deg):
    cx, cy, rx, ry = 350, 365, 240, 250
    angle = math.pi / 2 - math.radians(ahead_of_c_deg)
    x = cx + rx * math.cos(angle)
    y = cy + ry * math.sin(angle)
    rot = math.pi / 2 + angle
    tx = -math.sin(angle)
    ty =  math.cos(angle)
    arr1 = (x - tx * 30, y - ty * 30)
    arr2 = (x - tx * 52, y - ty * 52)
    return angle, x, y, rot, arr1, arr2

def compute_ltan(raan_deg, epoch_yyddd):
    yy  = math.floor(epoch_yyddd / 1000)
    ddd = epoch_yyddd - yy * 1000
    year = 2000 + yy
    Y, M, D = year, 1, 1
    jd_jan1 = (367*Y - int(7*(Y + int((M+9)/12))/4)
               + int(275*M/9) + D + 1721013.5)
    jd = jd_jan1 + (ddd - 1)
    T = (jd - 2451545.0) / 36525.0
    L0    = (280.46646 + 36000.76983 * T) % 360.0
    M_sun = (357.52911 + 35999.05029 * T - 0.0001537 * T**2) % 360.0
    M_r   = math.radians(M_sun)
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
    h = int(ltan_hours)
    m = int((ltan_hours - h) * 60)
    return f"{h:02d}:{m:02d}"

def epoch_to_date(epoch_yyddd):
    yy  = math.floor(epoch_yyddd / 1000)
    ddd = epoch_yyddd - yy * 1000
    year = 2000 + yy
    import datetime as dt
    jan1 = dt.datetime(year, 1, 1)
    d = jan1 + dt.timedelta(days=ddd - 1)
    return d.strftime('%d/%m/%Y')

def patch_html(html, elems, results):
    b  = elems['B']
    c  = elems['C']
    sg = elems['SGA1']

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

    b_x, b_y   = results['B']['pos']
    b_rot      = results['B']['rot']
    b_a1       = results['B']['arr1']
    b_a2       = results['B']['arr2']
    b_ltan     = results['B']['ltan_str']
    b_phase    = results['B']['phase']

    html = re.sub(
        r'  // ── Metop-B at [^\n]* ────────\r?\n'
        r'  // Phase angle from TLEs: [^\n]*\r?\n'
        r'  // Parametric angle on ellipse: [^\n]*\r?\n'
        r'  // Image rotation: [^\n]*\r?\n'
        r'  ctx\.save\(\);\r?\n'
        r'  ctx\.translate\([^)]+\);\r?\n'
        r'  ctx\.rotate\([^)]+\);\r?\n'
        r'  ctx\.drawImage\(imgBC,[^)]+\);\r?\n'
        r'  ctx\.restore\(\);\r?\n'
        r'  // Arrow in direction of travel[^\n]*\r?\n'
        r'  arrow\(ctx,[^)]+\);',
        f"""  // ── Metop-B at {b_phase:.2f}° ahead of Metop-C (TLE-derived, {epoch_to_date(b['epoch'])}) ────────
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

    html = re.sub(
        r"ctx\.fillText\('LTAN \d+:\d+',\d+,\d+\);",
        f"ctx.fillText('LTAN {b_ltan}',671,403);",
        html
    )

    sg_x, sg_y = results['SGA1']['pos']
    sg_rot     = results['SGA1']['rot']
    sg_a1      = results['SGA1']['arr1']
    sg_a2      = results['SGA1']['arr2']
    sg_phase   = results['SGA1']['phase']
    sg_behind  = 360.0 - sg_phase

    html = re.sub(
        r'  // ── Metop-SGA1 — EUMETSAT TLE [^\n]* ─+\r?\n'
        r'  // TLE epoch [^\n]*\r?\n'
        r'  // SGA1 AoL [^\n]*\r?\n'
        r'  // Phase: [^\n]*\r?\n'
        r'  // Canvas position: [^\n]*\r?\n'
        r'  ctx\.save\(\);\r?\n'
        r'  ctx\.translate\([^)]+\);\r?\n'
        r'  ctx\.rotate\([^)]+\);\r?\n'
        r'  ctx\.drawImage\(imgSGA1,[^)]+\);\r?\n'
        r'  ctx\.restore\(\);\r?\n'
        r'  // Arrow in direction of travel[^\n]*\r?\n'
        r'  arrow\(ctx,[^)]+\);',
        f"""  // ── Metop-SGA1 — EUMETSAT TLE ({epoch_to_date(sg['epoch'])}) ─────────────────────────────
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

    sg_thumb_bottom = sg_y + 45
    sg_box_top  = sg_thumb_bottom + 25
    sg_box_w    = 122
    sg_box_x    = sg_x - sg_box_w / 2
    sg_text_cx  = sg_x
    sg_line1_y  = sg_box_top + 14
    sg_line2_y  = sg_box_top + 28

    html = re.sub(
        r"  roundRect\(ctx,[\d.-]+,[\d.-]+,122,34,4,'rgba\(26,42,26,0\.85\)'\);\n"
        r"  ctx\.fillStyle='#a5d6a7'; ctx\.font='bold 11px sans-serif'; ctx\.textAlign='center';\n"
        r"  ctx\.fillText\('Metop-SGA1',[\d.-]+,[\d.-]+\);\n"
        r"  ctx\.fillStyle='#81c784'; ctx\.font='11px sans-serif';\n"
        r"  ctx\.fillText\('2nd gen · Commissioning',[\d.-]+,[\d.-]+\);",
        f"  roundRect(ctx,{sg_box_x:.0f},{sg_box_top:.0f},122,34,4,'rgba(26,42,26,0.85)');\n"
        f"  ctx.fillStyle='#a5d6a7'; ctx.font='bold 11px sans-serif'; ctx.textAlign='center';\n"
        f"  ctx.fillText('Metop-SGA1',{sg_text_cx:.0f},{sg_line1_y:.0f});\n"
        f"  ctx.fillStyle='#81c784'; ctx.font='11px sans-serif';\n"
        f"  ctx.fillText('2nd gen · Commissioning',{sg_text_cx:.0f},{sg_line2_y:.0f});",
        html
    )

    html = re.sub(
        r"ctx\.fillText\('Metop-B to C: [\d.]+°', 543, 577\);",
        f"ctx.fillText('Metop-B to C: {b_phase:.1f}°', 543, 577);",
        html
    )
    html = re.sub(
        r"ctx\.fillText\('Metop-C → SGA1: [\d.]+°', 153, 548\);",
        f"ctx.fillText('Metop-C → SGA1: {360-sg_phase:.1f}°', 153, 548);",
        html
    )

    # 7. Background orbit arc sweep angles.
    #    Three arcs, anchored at Metop-C's fixed parametric position (pi/2),
    #    measured cumulatively CCW: C->SGA1 (orange), SGA1->B (grey,
    #    unoccupied), B->C (orange, wraps back past 360 deg to close the
    #    circle). orbitArc() itself handles any sweep size generically, so
    #    no topological "which side of 270 deg" branching is needed here.
    sga1_from_c     = (360.0 - sg_phase) % 360.0
    b_from_c        = (360.0 - b_phase) % 360.0
    sga1_to_b_sweep = (b_from_c - sga1_from_c) % 360.0
    arc_total = sga1_from_c + sga1_to_b_sweep + b_phase

    # Safety check: this model assumes SGA1 always sits between C and B
    # when travelling CCW (i.e. b_from_c > sga1_from_c). If SGA1's continued
    # drift ever flips that ordering, the three sweeps stop summing to 360
    # and the arcs would render incorrectly. Rather than silently draw a
    # broken diagram, skip this patch and warn loudly so a human can look
    # at it — the previous day's (still-valid) arcs stay in place.
    if abs(arc_total - 360.0) > 0.5:
        print(
            f"  WARNING: orbit arc sweep angles do not sum to 360 "
            f"(got {arc_total:.2f}). SGA1/B ordering assumption may have "
            f"flipped — skipping arc update this run, please review manually.",
            file=sys.stderr
        )
        return html

    c_rad    = math.pi / 2
    sga1_rad = c_rad + math.radians(sga1_from_c)
    b_rad    = sga1_rad + math.radians(sga1_to_b_sweep)

    sga1_deg = math.degrees(sga1_rad)
    b_deg    = math.degrees(b_rad)

    html = re.sub(
        r'  // ── Orbit arcs \(auto-computed from cumulative phase angle from Metop-C\) ──\n'
        r'  // C→SGA1: [\d.]+° \| SGA1→B \(grey, unoccupied\): [\d.]+° \| B→C: [\d.]+°\n'
        r"  orbitArc\(Math\.PI/2, \([\d.]+ \* Math\.PI / 180\), 'rgba\(255,152,0,0\.65\)', \[3,3\]\);\n"
        r"  orbitArc\(\([\d.]+ \* Math\.PI / 180\), \([\d.]+ \* Math\.PI / 180\), 'rgba\(102,102,102,0\.18\)', \[3,5\]\);\n"
        r"  orbitArc\(\([\d.]+ \* Math\.PI / 180\), Math\.PI\*2 \+ Math\.PI/2, 'rgba\(255,152,0,0\.65\)', \[3,3\]\);",
        "  // ── Orbit arcs (auto-computed from cumulative phase angle from Metop-C) ──\n"
        f"  // C→SGA1: {sga1_from_c:.2f}° | SGA1→B (grey, unoccupied): {sga1_to_b_sweep:.2f}° | B→C: {b_phase:.2f}°\n"
        f"  orbitArc(Math.PI/2, ({sga1_deg:.2f} * Math.PI / 180), 'rgba(255,152,0,0.65)', [3,3]);\n"
        f"  orbitArc(({sga1_deg:.2f} * Math.PI / 180), ({b_deg:.2f} * Math.PI / 180), 'rgba(102,102,102,0.18)', [3,5]);\n"
        f"  orbitArc(({b_deg:.2f} * Math.PI / 180), Math.PI*2 + Math.PI/2, 'rgba(255,152,0,0.65)', [3,3]);",
        html
    )

    return html

def main():
    print(f"\n{'='*60}")
    print(f"Metop diagram updater — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print('='*60)
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
    ref = elems['B']['epoch']
    print(f"\nPropagating to common epoch {ref} ({epoch_to_date(ref)})...")
    results = {}
    for sat in ('B', 'C', 'SGA1'):
        dt = ref - elems[sat]['epoch']
        ma_ref = propagate_ma(elems[sat]['ma'], elems[sat]['mm'], dt)
        aol    = arg_of_latitude(elems[sat]['argp'], ma_ref)
        results[sat] = {'aol': aol}
    for sat in ('B', 'SGA1'):
        phase = phase_ahead(results[sat]['aol'], results['C']['aol'])
        results[sat]['phase'] = phase
        print(f"  Metop-{sat} ahead of C: {phase:.2f}°  (behind: {360-phase:.2f}°)")
    for sat in ('B', 'SGA1'):
        angle, x, y, rot, arr1, arr2 = canvas_position(results[sat]['phase'])
        results[sat].update({
            'angle': angle, 'pos': (x, y), 'rot': rot,
            'arr1': arr1, 'arr2': arr2
        })
    ltan_b = compute_ltan(elems['B']['raan'], elems['B']['epoch'])
    results['B']['ltan']     = ltan_b
    results['B']['ltan_str'] = ltan_str(ltan_b)
    ltan_c = compute_ltan(elems['C']['raan'], elems['C']['epoch'])
    print(f"\n  Metop-B  LTAN: {ltan_str(ltan_b)}  (drift from 21:30: {(ltan_b-21.5)*60:+.1f} min)")
    print(f"  Metop-C  LTAN: {ltan_str(ltan_c)}  (drift from 21:30: {(ltan_c-21.5)*60:+.1f} min)")
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
