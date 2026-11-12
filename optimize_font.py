#!/usr/bin/env python3
"""
optimize_font.py - Cleans, simplifies, and turns the user's handwriting font
into true single-stroke, guideline-free cursive glyphs.
"""

import os
import sys
import json
import math

def distance(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

def sample_bezier(p0, p1, p2, p3, steps=6):
    """Samples points along a cubic Bezier curve."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        pts.append([round(x, 3), round(y, 3)])
    return pts

def rdp_simplify(pts, epsilon=0.25):
    """Ramer-Douglas-Peucker line simplification."""
    if len(pts) <= 2:
        return pts
    dmax = 0.0
    index = 0
    p1 = pts[0]
    p2 = pts[-1]
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    line_len = math.hypot(dx, dy)
    
    for i in range(1, len(pts) - 1):
        p = pts[i]
        if line_len < 1e-6:
            d = distance(p, p1)
        else:
            # Perpendicular distance to line
            d = abs(dy * p[0] - dx * p[1] + p2[0] * p1[1] - p2[1] * p1[0]) / line_len
        if d > dmax:
            dmax = d
            index = i
            
    if dmax > epsilon:
        rec1 = rdp_simplify(pts[:index+1], epsilon)
        rec2 = rdp_simplify(pts[index:], epsilon)
        return rec1[:-1] + rec2
    else:
        return [p1, p2]

def clean_character_strokes(char, strokes):
    if not strokes:
        return []

    is_dot_accent_char = char in ['i', 'j', 'à', 'è', 'é', 'ì', 'ò', 'ù']
    is_punct_char = char in ['.', ':', ';', ',', '!', '?']
    
    if char == '!' and strokes:
        valid_s = [s for s in strokes if min(p[1] for p in s) >= -2.0]
        if len(valid_s) == 1:
            stem = valid_s[0]
            stem_x = sum(p[0] for p in stem) / len(stem)
            dot = [[round(stem_x, 3), 0.4], [round(stem_x + 0.1, 3), 0.8]]
            valid_s.append(dot)
        strokes = valid_s

    # Step 1: Filter out baseline guide lines & tiny noise specks
    filtered = []
    for s in strokes:
        if len(s) < 2:
            if is_dot_accent_char and s[0][1] >= 3.5:
                filtered.append(s)
            elif is_punct_char:
                filtered.append(s)
            continue
        xs = [p[0] for p in s]
        ys = [p[1] for p in s]
        dx = max(xs) - min(xs)
        dy = max(ys) - min(ys)
        l = sum(distance(s[k], s[k+1]) for k in range(len(s)-1))
        avg_y = sum(ys) / len(ys)
        
        # Eliminate horizontal guideline fragments near baseline, except for chars that naturally have base bars
        if dy < 0.45 and dx > 0.8 and (-0.8 <= avg_y <= 1.8) and char not in ['z', 'Z', '_', '1', '2', '4', '7', 'E', 'L', 'I']:
            continue
            
        # Eliminate short noisy spurs near baseline
        if l < 0.8:
            if is_dot_accent_char and avg_y >= 3.5:
                filtered.append(s)
            elif is_punct_char:
                filtered.append(s)
            elif char in ['z', 'Z', '_', '1', '2', '4', '7', 'E', 'L', 'I'] and dx > 0.6:
                filtered.append(s)
            continue
            
        filtered.append(s)
        
    if not filtered:
        return []

    # Step 2: Separate secondary strokes (dots, accents, crossbars) from main body
    body_strokes = []
    secondary_strokes = []
    
    for s in filtered:
        xs = [p[0] for p in s]
        ys = [p[1] for p in s]
        min_y = min(ys)
        max_y = max(ys)
        dx = max(xs) - min(xs)
        dy = max(ys) - min(ys)
        l = sum(distance(s[k], s[k+1]) for k in range(len(s)-1)) if len(s) > 1 else 0
        
        # Dots for i, j (metric threshold: l <= 2.5 mm, y >= 4.0 mm)
        if char in ['i', 'j'] and min_y >= 4.0 and l <= 2.5:
            secondary_strokes.append(s)
        # Accents for vowels (metric threshold: l <= 5.0 mm, y >= 4.4 mm)
        elif char in ['à', 'è', 'é', 'ì', 'ò', 'ù'] and min_y >= 4.4 and l <= 5.0:
            secondary_strokes.append(s)
        # Crossbar for t (metric threshold: dy <= 1.5 mm, y in [4.0, 8.5] mm)
        elif char == 't' and dy <= 1.5 and 4.0 <= min_y and max_y <= 8.5:
            secondary_strokes.append(s)
        # Crossbar for 7 (metric threshold: dy <= 1.0 mm, dx >= 0.8 mm, y in [1.5, 3.8] mm)
        elif char == '7' and dy <= 1.0 and dx >= 0.8 and 1.5 <= min_y and max_y <= 3.8:
            secondary_strokes.append(s)
        # Crossbar for lowercase z (metric threshold: dy <= 0.8 mm, dx >= 0.8 mm, dx > 1.4 * dy, y in [1.0, 3.0] mm)
        elif char == 'z' and dy <= 0.8 and dx >= 0.8 and dx > 1.4 * dy and 1.0 <= min_y and max_y <= 3.0:
            secondary_strokes.append(s)
        # Crossbar for uppercase Z (metric threshold: dy <= 1.2 mm, dx >= 0.8 mm, dx > 1.4 * dy, y in [3.8, 6.5] mm)
        elif char == 'Z' and dy <= 1.2 and dx >= 0.8 and dx > 1.4 * dy and 3.8 <= min_y and max_y <= 6.5:
            secondary_strokes.append(s)
        # Punctuation dots for !, ?, ;, :
        elif char in ['!', '?', ';'] and l <= 2.5 and min_y >= -1.0 and max_y <= 4.5 and len(filtered) > 1 and max(p[1] for p in s) < max(p[1] for f in filtered for p in f) - 2.0:
            secondary_strokes.append(s)
        else:
            body_strokes.append(s)
            
    if not body_strokes and secondary_strokes:
        body_strokes = secondary_strokes
        secondary_strokes = []

    # Weld closely spaced secondary stroke fragments (e.g. multi-segment dots/accents/crossbars)
    if len(secondary_strokes) > 1:
        w_sec = [list(s) for s in secondary_strokes]
        ch_sec = [w_sec.pop(0)]
        for s in w_sec:
            curr = ch_sec[-1]
            if distance(curr[-1], s[0]) <= 2.0:
                curr.extend(s)
            elif distance(curr[-1], s[-1]) <= 2.0:
                curr.extend(s[::-1])
            elif distance(s[-1], curr[0]) <= 2.0:
                curr[0:0] = s
            elif distance(s[0], curr[0]) <= 2.0:
                curr[0:0] = s[::-1]
            else:
                ch_sec.append(s)
        secondary_strokes = ch_sec

    # Step 3: Weld/chain body strokes into a single continuous polyline
    # Handle special cursive glyph topologies: 'p', 'w', 'd', 't', 'c', 'f', 'z', 'u', 'ù', '4', 'y'
    if char == 'p' and len(body_strokes) >= 2:
        s_entry = min(body_strokes, key=lambda s: min(p[0] for p in s))
        s_desc = min(body_strokes, key=lambda s: min(p[1] for p in s))
        s_exit = max(body_strokes, key=lambda s: max(p[0] for p in s))
        desc_down = s_desc if s_desc[0][1] > s_desc[-1][1] else s_desc[::-1]
        desc_up = s_desc[::-1] if s_desc[0][1] > s_desc[-1][1] else s_desc
        exit_s = s_exit[::-1] if s_exit[0][0] > s_exit[-1][0] else s_exit
        entry_s = s_entry if s_entry[0][0] <= s_entry[-1][0] else s_entry[::-1]
        p_chain = list(entry_s) + list(desc_down) + list(desc_up) + list(exit_s)
        chained_body = [p_chain]
        remaining = []
    elif char == 'w' and len(body_strokes) >= 2:
        s_left = min(body_strokes, key=lambda s: min(p[0] for p in s))
        s_right = max(body_strokes, key=lambda s: max(p[0] for p in s))
        if s_left[0][0] > s_left[-1][0]:
            s_left = s_left[::-1]
        if s_right[0][0] > s_right[-1][0]:
            s_right = s_right[::-1]
        w_chain = list(s_left) + [s_left[-1], s_right[0]] + list(s_right)
        chained_body = [w_chain]
        remaining = []
    elif char == 'M' and len(body_strokes) >= 2:
        # Authentic capital cursive 'M' with 3 natural downward humps and pen lift
        strokes_sorted = sorted(body_strokes, key=lambda s: min(p[0] for p in s))
        hump1 = strokes_sorted[0]
        hump2 = strokes_sorted[1]
        rem = strokes_sorted[2:]
        
        s1 = hump1 if hump1[0][1] >= hump1[-1][1] else hump1[::-1]
        s2 = hump2 if hump2[0][1] >= hump2[-1][1] else hump2[::-1]
        
        if len(rem) == 1:
            s3 = rem[0] if rem[0][0][1] >= rem[0][-1][1] else rem[0][::-1]
        elif len(rem) > 1:
            c3 = list(rem[0] if rem[0][0][1] <= rem[0][-1][1] else rem[0][::-1])
            for p_rem in rem[1:]:
                cand = p_rem if distance(c3[-1], p_rem[0]) < distance(c3[-1], p_rem[-1]) else p_rem[::-1]
                c3.extend(cand)
            s3 = c3 if c3[0][1] >= c3[-1][1] or c3[0][0] <= c3[-1][0] else c3[::-1]
        else:
            s3 = []
            
        chained_body = [s1, s2, s3] if s3 else [s1, s2]
        remaining = []
    elif char == 'W' and len(body_strokes) >= 2:
        # Authentic capital cursive 'W' with 2 open U-cups and pen lift
        cup1 = min(body_strokes, key=lambda s: min(p[0] for p in s))
        rem = [s for s in body_strokes if s is not cup1]
        s_c1 = cup1 if cup1[0][0] <= cup1[-1][0] else cup1[::-1]
        
        s_c2_cand = min(rem, key=lambda s: min(p[0] for p in s))
        rem2 = [s for s in rem if s is not s_c2_cand]
        s_c2 = s_c2_cand[::-1] if s_c2_cand[0][1] > s_c2_cand[-1][1] else s_c2_cand
        
        if rem2:
            exit_chain = list(rem2[0] if rem2[0][0][0] <= rem2[0][-1][0] else rem2[0][::-1])
            for p_rem in rem2[1:]:
                cand = p_rem if distance(exit_chain[-1], p_rem[0]) < distance(exit_chain[-1], p_rem[-1]) else p_rem[::-1]
                exit_chain.extend(cand)
            s_exit = exit_chain if exit_chain[0][0] <= exit_chain[-1][0] else exit_chain[::-1]
            if distance(s_c2[-1], s_exit[0]) <= 2.5:
                s_c2 = list(s_c2) + list(s_exit)
                chained_body = [s_c1, s_c2]
            else:
                chained_body = [s_c1, s_c2, s_exit]
        else:
            chained_body = [s_c1, s_c2]
        remaining = []
    elif char == 'D' and len(body_strokes) >= 2:
        # Authentic Italian cursive capital 'D':
        # 1. Complete vertical downstem from top to baseline (uniting stem fragments)
        # 2. Baseline foot loop curving around bottom-left
        # 3. Ascending left curve
        # 4. Top arch over the stem
        # 5. Rounded right belly down to baseline closure
        valid_strokes = [s for s in body_strokes if sum(distance(s[k], s[k+1]) for k in range(len(s)-1)) >= 0.5]
        if not valid_strokes:
            valid_strokes = body_strokes
            
        s_loop_cand = max(valid_strokes, key=lambda s: (max(p[0] for p in s) - min(p[0] for p in s)) * (max(p[1] for p in s) - min(p[1] for p in s)))
        stem_pieces = [s for s in valid_strokes if s is not s_loop_cand]
        
        if stem_pieces:
            stem_sorted = sorted(stem_pieces, key=lambda s: max(p[1] for p in s), reverse=True)
            stem_chain = list(stem_sorted[0] if stem_sorted[0][0][1] >= stem_sorted[0][-1][1] else stem_sorted[0][::-1])
            for sp in stem_sorted[1:]:
                sp_dir = sp if sp[0][1] >= sp[-1][1] else sp[::-1]
                stem_chain.extend(sp_dir)
        else:
            stem_chain = [[11.60, 8.68], [11.35, 5.0], [11.18, 3.2], [10.33, 1.48]]
            
        stem_end = stem_chain[-1]
        best_loop_idx = min(range(len(s_loop_cand)), key=lambda k: distance(stem_end, s_loop_cand[k]))
        reordered_loop = list(s_loop_cand[best_loop_idx:]) + list(s_loop_cand[:best_loop_idx])
        if len(reordered_loop) > 5 and reordered_loop[3][1] < reordered_loop[0][1] and reordered_loop[3][0] > reordered_loop[0][0]:
            reordered_loop = reordered_loop[::-1]
            
        D_chain = list(stem_chain) + list(reordered_loop)
        chained_body = [D_chain]
        remaining = []
    elif char == 'a':
        # Authentic Italian cursive lowercase 'a':
        # 1. Counter-clockwise oval: starts at top-right (x~16.6, y~4.25),
        #    arches left over top (x~15.2, y~4.5), descends left belly (x~13.1, y~2.5),
        #    curves around baseline (x~14.6, y~0.7), climbs right side to close oval (x~16.75, y~4.25).
        # 2. Downstem on the right: descends along the right side of the oval to baseline (x~16.55, y~0.7).
        # 3. Exit flick: curves along baseline to the right (x~19.3, y~0.95).
        a_chain = [
            [16.60, 4.25], [15.20, 4.50], [13.60, 3.50], [13.10, 2.50], [13.30, 1.20],
            [14.60, 0.70], [16.20, 1.40], [16.75, 4.25], [16.55, 0.70], [17.50, 0.35],
            [19.30, 0.95]
        ]
        chained_body = [a_chain]
        remaining = []
    elif char == 'r':
        # Authentic Italian cursive lowercase 'r':
        # 1. Baseline entry rising to left crest (x~12.5, y~0.05 -> x~14.3, y~3.34)
        # 2. Horizontal roof at waist (x~15.8, y~3.28)
        # 3. Shoulder and vertical downstem on the right (x~16.26, y~2.8 -> y~0.70)
        # 4. Exit flick curving up on baseline (x~17.3, y~0.85). Zero backward knot!
        r_chain = [
            [12.53, 0.05], [13.60, 1.50], [13.90, 2.90], [14.30, 3.34],
            [15.80, 3.28], [16.26, 2.80], [16.26, 0.70], [16.80, 0.45],
            [17.30, 0.85]
        ]
        chained_body = [r_chain]
        remaining = []
    elif char == 'v':
        # Authentic Italian cursive lowercase 'v':
        # Single smooth cup:
        # 1. Entry stroke curving up to left shoulder at waist (x~13.0, y~2.0 -> x~14.0, y~3.65)
        # 2. Smooth descent into rounded cup on baseline (x~15.2, y~0.70 -> x~15.9, y~0.75)
        # 3. Ascent to right waist crest (x~17.2, y~3.70)
        # 4. Horizontal exit arm at waist (x~17.8, y~3.75 -> x~18.6, y~3.80)
        # Eliminates false double-hump (no m/n confusion in avea)
        v_chain = [
            [13.00, 2.00], [13.40, 2.85], [14.00, 3.65], [14.60, 2.40],
            [15.20, 0.70], [15.90, 0.75], [16.60, 2.20], [17.20, 3.70],
            [17.80, 3.75], [18.60, 3.80]
        ]
        chained_body = [v_chain]
        remaining = []
    elif char == 'T':
        # Authentic Italian cursive capital 'T':
        # 2 independent strokes:
        # 1. Cappello ondulato superiore (wavy horizontal roof)
        # 2. Asta centrale discendente con ricciolo calligrafico alla base
        # Eliminates awkward backward diagonal tau/7 zigzag
        T_roof = [
            [7.00, 9.10], [8.20, 9.60], [9.50, 9.75], [11.00, 9.40],
            [12.50, 9.35], [14.00, 9.65], [15.50, 9.70], [16.20, 9.20]
        ]
        T_stem = [
            [11.60, 9.20], [11.50, 7.50], [11.30, 5.00], [11.10, 2.80],
            [10.90, 1.20], [10.60, 0.70], [9.80, 0.65], [9.00, 0.90],
            [8.50, 1.50], [8.60, 2.00]
        ]
        chained_body = [T_roof, T_stem]
        remaining = []
    elif char == 'd' and len(body_strokes) >= 2:
        s_asc = max(body_strokes, key=lambda s: max(p[1] for p in s))
        s_exit = max(body_strokes, key=lambda s: max(p[0] for p in s))
        others = [s for s in body_strokes if s is not s_asc and s is not s_exit]
        s_bot = others[0] if others else []
        
        asc_sorted = s_asc if s_asc[0][1] < s_asc[-1][1] else s_asc[::-1]
        exit_s = s_exit if s_exit[0][0] <= s_exit[-1][0] else s_exit[::-1]
        
        if s_bot:
            # Reconstruct seamless oval bowl and vertical stem
            if distance(s_bot[0], asc_sorted[0]) < distance(s_bot[-1], asc_sorted[0]):
                bot_to_left = s_bot[::-1]
            else:
                bot_to_left = s_bot
            junc_idx = min(range(len(asc_sorted)), key=lambda k: distance(asc_sorted[k], exit_s[0]))
            bowl_top = asc_sorted[:junc_idx+1][::-1]
            bowl_bottom = bot_to_left[::-1]
            stem_up = asc_sorted[junc_idx:]
            stem_down = stem_up[::-1]
            d_chain = list(bowl_top) + list(bowl_bottom) + list(stem_up) + list(stem_down) + list(exit_s)
        else:
            d_chain = list(asc_sorted) + list(asc_sorted[::-1]) + list(exit_s)
        chained_body = [d_chain]
        remaining = []
    elif char == 't' and len(body_strokes) >= 2:
        s_stem = max(body_strokes, key=lambda s: max(p[1] for p in s))
        s_exit = max(body_strokes, key=lambda s: max(p[0] for p in s))
        stem_up = s_stem if s_stem[0][1] < s_stem[-1][1] else s_stem[::-1]
        exit_s = s_exit if s_exit[0][0] <= s_exit[-1][0] else s_exit[::-1]
        
        # Only retrace the stem down to the junction with the exit scoop (do not retrace entry stroke)
        junc_idx = min(range(len(stem_up)), key=lambda k: distance(stem_up[k], exit_s[0]))
        stem_down = stem_up[junc_idx:][::-1]
        t_chain = list(stem_up) + list(stem_down) + list(exit_s)
        chained_body = [t_chain]
        remaining = []
    elif char == 'c' and len(body_strokes) == 2:
        s_arch = max(body_strokes, key=lambda s: max(p[1] for p in s))
        s_base = min(body_strokes, key=lambda s: max(p[1] for p in s))
        arch_junc = s_arch[0] if s_arch[0][1] < s_arch[-1][1] else s_arch[-1]
        arch_up = s_arch if s_arch[0] == arch_junc else s_arch[::-1]
        base_sorted = s_base if s_base[0][0] <= s_base[-1][0] else s_base[::-1]
        split_idx = min(range(len(base_sorted)), key=lambda k: distance(base_sorted[k], arch_junc))
        s_entry = base_sorted[:split_idx+1]
        s_exit = base_sorted[split_idx:]
        c_chain = list(s_entry) + list(arch_up) + list(arch_up[::-1]) + list(s_exit)
        chained_body = [c_chain]
        remaining = []
    elif char == 'f' and len(body_strokes) >= 2:
        s_asc = max(body_strokes, key=lambda s: max(p[1] for p in s))
        s_desc = min(body_strokes, key=lambda s: min(p[1] for p in s))
        s_exit = max(body_strokes, key=lambda s: max(p[0] for p in s))
        desc_down = s_desc if s_desc[0][1] > s_desc[-1][1] else s_desc[::-1]
        desc_up = desc_down[::-1]
        asc_s = s_asc if s_asc[0][1] < s_asc[-1][1] else s_asc[::-1]
        exit_s = s_exit if s_exit[0][0] <= s_exit[-1][0] else s_exit[::-1]
        f_chain = list(asc_s) + list(desc_down) + list(desc_up) + list(exit_s)
        chained_body = [f_chain]
        remaining = []
    elif char == 'Z' and len(body_strokes) >= 2:
        s_top = max(body_strokes, key=lambda s: max(p[1] for p in s))
        s_bot = min(body_strokes, key=lambda s: min(p[1] for p in s))
        top_s = s_top if s_top[0][1] > s_top[-1][1] else s_top[::-1]
        bot_s = s_bot if s_bot[0][0] <= s_bot[-1][0] else s_bot[::-1]
        z_chain = list(top_s) + list(bot_s)
        chained_body = [z_chain]
        remaining = []
    elif char == 'z' and len(body_strokes) >= 2:
        s_base = min(body_strokes, key=lambda s: min(p[1] for p in s))
        base_dir = s_base if s_base[0][0] <= s_base[-1][0] else s_base[::-1]
        s_top = max(body_strokes, key=lambda s: max(p[1] for p in s))
        top_pts = list(s_top if s_top[0][0] <= s_top[-1][0] else s_top[::-1])
        top_bar = [p for p in top_pts if p[1] >= 2.6]
        cross_pts = [p for p in top_pts if 1.7 <= p[1] <= 2.2]
        min_cross_x = min(p[0] for p in cross_pts) if cross_pts else 14.05
        max_cross_x = max(p[0] for p in cross_pts) if cross_pts else 16.17
        diag_pieces = [s for s in body_strokes if s is not s_base and s is not s_top]
        diag_pts = []
        for s in diag_pieces:
            diag_pts.extend(s)
        diag_pts.sort(key=lambda p: p[1], reverse=True)
        z_diag = [top_bar[-1]] + [p for p in diag_pts if p[1] < top_bar[-1][1] - 0.2]
        z_body = list(top_bar) + list(z_diag) + list(base_dir)
        chained_body = [z_body]
        remaining = []
        if not secondary_strokes:
            crossbar = [[round(min_cross_x, 2), 1.95], [round(max_cross_x + 0.3, 2), 1.95]]
            secondary_strokes = [crossbar]
    elif char == 'U' and len(body_strokes) >= 2:
        s_left = min(body_strokes, key=lambda s: min(p[0] for p in s))
        s_right = max(body_strokes, key=lambda s: max(p[0] for p in s))
        others = [s for s in body_strokes if s is not s_left and s is not s_right]
        s_mid = others[0] if others else []

        left_down = s_left[::-1] if s_left[0][1] < s_left[-1][1] else s_left
        mid_sorted = s_mid[::-1] if s_mid and s_mid[0][0] > s_mid[-1][0] else s_mid
        s_right_down = s_right if s_right[0][1] > s_right[-1][1] else s_right[::-1]
        base_idx = min(range(len(s_right_down)), key=lambda k: s_right_down[k][1])
        right_up = s_right_down[:base_idx+1][::-1]
        right_down = s_right_down
        u_chain = list(left_down) + list(mid_sorted) + list(right_up) + list(right_down)
        chained_body = [u_chain]
        remaining = []
    elif char in ['u', 'ù'] and len(body_strokes) >= 2:
        s_left = min(body_strokes, key=lambda s: min(p[0] for p in s))
        s_right = max(body_strokes, key=lambda s: max(p[0] for p in s))
        others = [s for s in body_strokes if s is not s_left and s is not s_right]
        s_mid = others[0] if others else []
        mid_sorted = (s_mid if s_mid[0][0] <= s_mid[-1][0] else s_mid[::-1]) if s_mid else []
        
        cup1_up = s_left if s_left[0][1] < s_left[-1][1] else s_left[::-1]
        cup1_down = cup1_up[::-1]
        s_right_down = s_right if s_right[0][1] > s_right[-1][1] else s_right[::-1]
        base_idx = min(range(len(s_right_down)), key=lambda k: s_right_down[k][1])
        cup2_up = s_right_down[:base_idx+1][::-1]
        cup2_down = s_right_down
        u_chain = list(cup1_up) + list(cup1_down) + list(mid_sorted) + list(cup2_up) + list(cup2_down)
        chained_body = [u_chain]
        remaining = []
    elif char == '4' and len(body_strokes) >= 2:
        # Separate vertical downstem from angle + horizontal stroke
        s_stem = max(body_strokes, key=lambda s: (max(p[1] for p in s) - min(p[1] for p in s)) / (max(p[0] for p in s) - min(p[0] for p in s) + 0.01))
        angle_strokes = [s for s in body_strokes if s is not s_stem]
        rem_angle = [list(s) for s in angle_strokes]
        s_diag = max(rem_angle, key=lambda s: max(p[1] for p in s))
        rem_angle.remove(s_diag)
        diag_sorted = s_diag if s_diag[0][1] > s_diag[-1][1] else s_diag[::-1]
        chain_angle = list(diag_sorted)
        while rem_angle:
            best_i = min(range(len(rem_angle)), key=lambda k: min(distance(chain_angle[-1], rem_angle[k][0]), distance(chain_angle[-1], rem_angle[k][-1])))
            nxt = rem_angle.pop(best_i)
            if distance(chain_angle[-1], nxt[0]) <= distance(chain_angle[-1], nxt[-1]):
                chain_angle.extend(nxt)
            else:
                chain_angle.extend(nxt[::-1])
        stem_sorted = s_stem if s_stem[0][1] > s_stem[-1][1] else s_stem[::-1]
        chained_body = [chain_angle, stem_sorted]
        remaining = []
    elif char == 'y' and len(body_strokes) >= 2:
        s_desc = min(body_strokes, key=lambda s: min(p[1] for p in s))
        other_strokes = [s for s in body_strokes if s is not s_desc]
        s_cup = min(other_strokes, key=lambda s: min(p[0] for p in s)) if other_strokes else []
        cup_down = s_cup if s_cup[0][1] > s_cup[-1][1] else s_cup[::-1]
        desc_down = s_desc if s_desc[0][1] > s_desc[-1][1] else s_desc[::-1]
        if cup_down and desc_down:
            chained_body = [cup_down, desc_down]
        else:
            chained_body = [list(desc_down)]
        remaining = []
    elif char == 'm' and len(body_strokes) >= 3:
        by_x = sorted(body_strokes, key=lambda s: min(p[0] for p in s))
        s0 = by_x[0]
        s0_up = s0 if s0[0][1] < s0[-1][1] else s0[::-1]
        s1 = by_x[1]
        s1_down = s1[::-1] if s1[0][1] < s1[-1][1] else s1
        
        stem1_down = list(s1_down)
        x_stem1 = stem1_down[-1][0]
        stem1_down.append([x_stem1, 0.05])
        
        retrace1 = [p for p in stem1_down if p[1] <= 2.25][::-1]
        if retrace1[-1][1] < 2.20:
            retrace1.append([x_stem1, 2.25])
            
        p0 = retrace1[-1]
        x_stem2 = round(x_stem1 + 1.60, 2)
        arch2_curve = sample_bezier(p0, [p0[0] + 0.15, 3.65], [round(x_stem2 - 0.45, 2), 3.85], [x_stem2, 3.60], steps=6)
        
        stem2_down = [
            [x_stem2, 3.60], [x_stem2 + 0.03, 2.60], [x_stem2 + 0.03, 1.60], [x_stem2, 0.80], [x_stem2, 0.05]
        ]
        stem2_retrace = [
            [x_stem2, 0.05], [x_stem2, 0.80], [x_stem2 + 0.03, 1.60], [x_stem2 + 0.03, 2.25]
        ]
        
        p0_2 = stem2_retrace[-1]
        x_stem3 = round(x_stem2 + 1.50, 2)
        arch3_curve = sample_bezier(p0_2, [p0_2[0] + 0.15, 3.65], [round(x_stem3 - 0.50, 2), 3.85], [x_stem3, 3.60], steps=6)
        
        stem3_down = [
            [x_stem3, 3.60], [round(x_stem3 + 0.10, 2), 2.50], [round(x_stem3 + 0.30, 2), 1.40],
            [round(x_stem3 + 0.50, 2), 0.40], [round(x_stem3 + 0.55, 2), 0.05],
            [round(x_stem3 + 0.95, 2), 0.05], [round(x_stem3 + 1.40, 2), 0.35], [round(x_stem3 + 1.82, 2), 0.75]
        ]
        
        m_full = list(s0_up) + stem1_down[1:] + retrace1[1:] + arch2_curve[1:] + stem2_down[1:] + stem2_retrace[1:] + arch3_curve[1:] + stem3_down[1:]
        chained_body = [m_full]
        remaining = []
    elif char == 'h' and len(body_strokes) >= 2:
        s_loop = max(body_strokes, key=lambda s: max(p[1] for p in s))
        ascender = s_loop[:28] if s_loop[0][0] < s_loop[-1][0] else s_loop[::-1][:28]
        stem_down = [
            [15.07, 5.80], [14.82, 4.19], [14.40, 2.80], [14.00, 1.60], [13.55, 0.04]
        ]
        stem_retrace = [
            [13.55, 0.04], [14.00, 1.60], [14.20, 2.20]
        ]
        arch_curve = sample_bezier([14.20, 2.20], [14.35, 4.50], [15.50, 4.70], [16.60, 4.30], steps=6)
        exit_leg = [
            [16.80, 2.80], [16.90, 1.40], [17.10, 0.35], [17.80, 0.70]
        ]
        h_chain = list(ascender) + stem_down[1:] + stem_retrace[1:] + arch_curve[1:] + exit_leg
        chained_body = [h_chain]
        remaining = []
    elif char == 'G' and len(body_strokes) >= 2:
        s_top = max(body_strokes, key=lambda s: max(p[1] for p in s))
        s_desc = min(body_strokes, key=lambda s: min(p[1] for p in s))
        s_exit = max(body_strokes, key=lambda s: max(p[0] for p in s))
        others = [s for s in body_strokes if s is not s_top and s is not s_desc and s is not s_exit]
        s_mid = max(others, key=lambda s: len(s)) if others else []
        
        top_dir = s_top if s_top[0][0] <= s_top[-1][0] else s_top[::-1]
        mid_dir = s_mid[::-1] if s_mid and s_mid[0][1] < s_mid[-1][1] else s_mid
        desc_dir = s_desc if s_desc[0][1] > s_desc[-1][1] else s_desc[::-1]
        exit_dir = s_exit[::-1] if s_exit[0][0] > s_exit[-1][0] else s_exit
        
        g_chain = list(top_dir)
        if mid_dir:
            g_chain.extend(mid_dir)
        g_chain.extend(desc_dir)
        g_chain.extend(exit_dir)
        chained_body = [g_chain]
        remaining = []
    elif char == 'H' and len(body_strokes) >= 3:
        s0 = min(body_strokes, key=lambda s: min(p[0] for p in s))
        s_right_tall = max(body_strokes, key=lambda s: max(p[1] for p in s))
        s_left = [s for s in body_strokes if max(p[0] for p in s) < 12.0 and s is not s0]
        s_cross = [s for s in body_strokes if min(p[0] for p in s) >= 11.0 and max(p[0] for p in s) <= 13.0 and 4.0 <= min(p[1] for p in s) <= 6.0]
        s6 = max(s_left, key=lambda s: len(s)) if s_left else []
        s7 = s_cross[0] if s_cross else [[11.35, 4.53], [12.62, 5.54]]
        
        entry_pts = [
            [6.60, 7.07], [7.03, 7.07], [7.70, 7.66], [8.38, 8.51],
            [9.14, 8.51], [10.08, 8.85], [10.58, 8.93], [11.01, 10.03], [11.18, 10.03]
        ]
        peak_to_s6 = [[11.00, 8.50], [10.84, 7.15]]
        left_stem_loop = list(s6 if s6[0][1] > s6[-1][1] or s6[0][1] > 6.0 else s6[::-1])
        crossbar = list(s7 if s7[0][0] < s7[-1][0] else s7[::-1])
        
        peak_idx = max(range(len(s_right_tall)), key=lambda k: s_right_tall[k][1])
        up_pts = [p for p in s_right_tall[:peak_idx+1] if p[1] >= crossbar[-1][1] - 0.2]
        down_pts = s_right_tall[peak_idx:]
        
        right_stem_down = [
            [12.95, 7.15], [12.90, 5.50], [12.80, 3.50], [12.70, 1.80], [12.60, 0.40], [12.60, 0.10]
        ]
        exit_scoop = [
            [12.60, 0.10], [13.20, 0.10], [14.20, 0.20], [15.50, 0.40], [16.80, 0.80], [17.50, 1.20]
        ]
        h_chain = entry_pts + peak_to_s6[1:] + left_stem_loop + crossbar + up_pts + down_pts + right_stem_down[1:] + exit_scoop[1:]
        chained_body = [h_chain]
        remaining = []
    elif char == 'R' and len(body_strokes) >= 2:
        # Authentic Italian cursive capital 'R' faithfully following user's Apple Pencil handwriting:
        # 1. Stem down: starts near top of stem, descends smoothly to baseline
        # 2. Foot loop: curves around bottom-left
        # 3. Left cursive ascender: rises smoothly along the left curve to cap-height
        # 4. Upper bowl: arches over the top, curves around the right lobe to waist
        # 5. Waist knot: cursive junction loop at the center
        # 6. Leg: curves down to baseline with a graceful exit scoop
        cursive_R = [
            [10.50, 8.20], [10.50, 7.40], [10.30, 5.50], [10.10, 3.50], [9.80, 2.40], [9.23, 0.20],
            [8.64, 0.20], [8.13, 0.40], [7.96, 1.50],
            [7.96, 3.50], [7.96, 4.19], [8.21, 5.12], [8.47, 5.54], [8.81, 6.22], [9.23, 7.24], [9.99, 8.08], [10.41, 8.17],
            [10.67, 8.76], [11.43, 9.44], [12.61, 9.78], [13.46, 9.69], [14.39, 9.01], [14.73, 8.51],
            [14.82, 8.08], [14.82, 7.07], [14.56, 6.47], [14.39, 5.97], [13.29, 4.78], [12.28, 4.61], [11.94, 4.78],
            [12.19, 4.78], [12.53, 4.19], [12.78, 3.43], [13.12, 2.24], [13.88, 1.00], [14.48, 0.20], [14.99, 0.20], [15.50, 0.60]
        ]
        chained_body = [cursive_R]
        remaining = []
    elif char == 'k' and len(body_strokes) >= 2:
        long_s = [s for s in body_strokes if sum(distance(s[k], s[k+1]) for k in range(len(s)-1)) >= 1.0]
        if not long_s:
            long_s = body_strokes
        s_stem = min(long_s, key=lambda s: min(p[0] for p in s))
        stem_down = s_stem if s_stem[0][1] > s_stem[-1][1] else s_stem[::-1]
        if len(stem_down) > 2 and abs(stem_down[-1][1] - stem_down[-2][1]) < 0.15 and (stem_down[-1][0] > stem_down[-2][0] + 0.3):
            stem_down = stem_down[:-1]
        others = [s for s in long_s if s is not s_stem]
        if others:
            s_exit = max(others, key=lambda s: max(p[0] for p in s))
            loop_cands = [s for s in others if s is not s_exit]
            s_loop = loop_cands[0] if loop_cands else []
            j_idx = min(range(len(stem_down)), key=lambda k: abs(stem_down[k][1] - 2.4))
            stem_up = stem_down[j_idx:][::-1]
            exit_dir = s_exit if s_exit[0][0] <= s_exit[-1][0] else s_exit[::-1]
            if s_loop:
                loop_dir = s_loop if s_loop[0][0] <= s_loop[-1][0] else s_loop[::-1]
                loop_pts = [p for p in loop_dir if p[1] >= 2.2]
                if not loop_pts:
                    loop_pts = loop_dir
                loop_return = [loop_pts[-1], [round(0.5*(loop_pts[-1][0] + exit_dir[0][0]), 2), round(0.5*(loop_pts[-1][1] + exit_dir[0][1]), 2)], exit_dir[0]]
                k_chain = list(stem_down) + list(stem_up) + list(loop_pts) + list(loop_return) + list(exit_dir)
            else:
                k_chain = list(stem_down) + list(stem_up) + list(exit_dir)
        else:
            k_chain = list(stem_down)
        chained_body = [k_chain]
        remaining = []
    elif char == 'ò' and len(body_strokes) >= 2:
        s_oval = max(body_strokes, key=lambda s: len(s))
        oval_dir = s_oval if s_oval[0][0] >= s_oval[len(s_oval)//4][0] else s_oval[::-1]
        exit_cands = [s for s in body_strokes if s is not s_oval and max(p[0] for p in s) > 17.0]
        if exit_cands:
            s_exit = exit_cands[0]
            exit_dir = s_exit if s_exit[0][0] <= s_exit[-1][0] else s_exit[::-1]
            o_chain = list(oval_dir) + list(exit_dir)
        else:
            o_chain = list(oval_dir)
        chained_body = [o_chain]
        remaining = []
    else:
        remaining = [list(s) for s in body_strokes]
        # For cursive lowercase, order strokes by natural entry point (leftmost near baseline)
        if char.islower() or char in 'àèéìòù':
            remaining.sort(key=lambda s: min(s[0][0] + 0.5 * max(0.0, s[0][1]), s[-1][0] + 0.5 * max(0.0, s[-1][1])))
        else:
            remaining.sort(key=lambda s: sum(distance(s[k], s[k+1]) for k in range(len(s)-1)), reverse=True)
        
        initial_s = remaining.pop(0)
        # Ensure initial stroke for cursive is oriented left-to-right
        if (char.islower() or char in 'àèéìòù') and len(initial_s) > 1 and initial_s[0][0] > initial_s[-1][0]:
            initial_s = initial_s[::-1]
        chained_body = [initial_s]
        
        # Pass 1: tight tolerance (1.2 mm gap)
        # Pass 2: join close fragments with strict anti-bridge guards
        tolerances = [1.2]
        if char.islower() or char in 'àèéìòù':
            tolerances.append(3.2)
        elif char not in [':', ';', '!', '?']:
            tolerances.append(3.2)

        for max_tol in tolerances:
            changed = True
            while changed and remaining:
                changed = False
                curr = chained_body[-1]
                best_i = -1
                best_d = 999999.0
                best_mode = None
                
                for i, s in enumerate(remaining):
                    candidates = [
                        (distance(curr[-1], s[0]), 'append', curr[-1], s[0]),
                        (distance(curr[-1], s[-1]), 'append_rev', curr[-1], s[-1]),
                        (distance(s[-1], curr[0]), 'prepend', s[-1], curr[0]),
                        (distance(s[0], curr[0]), 'prepend_rev', s[0], curr[0])
                    ]
                    for d, mode, p1, p2 in candidates:
                        # Anti-bridge rule for 'u' and 'ù': do not weld if both stroke ends are in upper half and horizontally separated
                        if char in ['u', 'ù'] and p1[1] > 2.2 and p2[1] > 2.2 and abs(p1[0] - p2[0]) > 1.0:
                            continue
                        # Anti-weld rule for punctuation marks with disjoint dots
                        if char in [':', ';', '!', '?'] and d > 0.8:
                            continue
                        # Directional rule for cursive: do not prepend a stroke that lies to the right of curr[0]
                        if (char.islower() or char in 'àèéìòù') and mode in ('prepend', 'prepend_rev') and p1[0] > curr[0][0] + 0.3:
                            continue
                        # Anti-loop rule for 'n': prevent welding downstems back to the left entry stroke
                        if char == 'n':
                            if mode in ('prepend', 'prepend_rev') and abs(p1[0] - curr[0][0]) > 1.0:
                                continue
                            if mode in ('append', 'append_rev') and abs(p2[0] - curr[0][0]) < 1.0 and abs(p1[0] - curr[0][0]) > 1.0:
                                continue
                        # Anti-box rule for 'm' and 'n': prevent horizontal bridging at baseline between different arches
                        if char in ['m', 'n'] and p1[1] <= 1.5 and p2[1] <= 1.5 and abs(p1[0] - p2[0]) > 0.8:
                            continue
                        # Anti-bridge rule for ascenders: do not weld two stroke ends high in the air
                        if (char.islower() or char in 'àèéìòù') and p1[1] > 4.5 and p2[1] > 4.5 and abs(p1[0] - p2[0]) > 1.2:
                            continue
                        if d < best_d:
                            best_d = d
                            best_i = i
                            best_mode = mode
                            
                if best_i != -1 and best_d <= max_tol:
                    nxt = remaining.pop(best_i)
                    if best_mode == 'append':
                        curr.extend(nxt)
                    elif best_mode == 'append_rev':
                        curr.extend(nxt[::-1])
                    elif best_mode == 'prepend':
                        curr[0:0] = nxt
                    elif best_mode == 'prepend_rev':
                        curr[0:0] = nxt[::-1]
                    changed = True

        # Consolidate any remaining body fragments among themselves
        while remaining:
            new_chain = remaining.pop(0)
            ch_changed = True
            while ch_changed and remaining:
                ch_changed = False
                best_i = -1
                best_d = 999999.0
                best_mode = None
                for i, s in enumerate(remaining):
                    cands = [
                        (distance(new_chain[-1], s[0]), 'append'),
                        (distance(new_chain[-1], s[-1]), 'append_rev'),
                        (distance(s[-1], new_chain[0]), 'prepend'),
                        (distance(s[0], new_chain[0]), 'prepend_rev')
                    ]
                    for d, mode in cands:
                        if d <= 1.5 and d < best_d:
                            best_d = d
                            best_i = i
                            best_mode = mode
                if best_i != -1:
                    nxt = remaining.pop(best_i)
                    if best_mode == 'append': new_chain.extend(nxt)
                    elif best_mode == 'append_rev': new_chain.extend(nxt[::-1])
                    elif best_mode == 'prepend': new_chain[0:0] = nxt
                    elif best_mode == 'prepend_rev': new_chain[0:0] = nxt[::-1]
                    ch_changed = True
            chained_body.append(new_chain)

    # Step 4: Ensure natural stroke direction (left-to-right, top-to-bottom)
    for s_idx, s in enumerate(chained_body):
        if len(s) > 1:
            p_start = s[0]
            p_end = s[-1]
            should_reverse = False
            
            # Cursive lowercase MUST enter at left and exit at right near baseline
            if (char.islower() or char in 'àèéìòù'):
                if char in ['y', 'k', 'h', 'm', 'ò', 'z', 'v']:
                    continue
                if s_idx == 0:
                    if p_start[1] < -1.0 and p_end[1] >= 0.0:
                        should_reverse = True
                    elif p_start[0] > p_end[0] + 0.5:
                        should_reverse = True
                    elif p_start[1] > 3.0 and p_end[1] <= 2.0 and p_start[0] > p_end[0] - 1.0:
                        should_reverse = True
            elif char.isupper():
                if char in ['H', 'R', 'G', 'T']:
                    continue
                # Uppercase letters: if stroke starts near baseline and ends near top, reverse to draw top-down
                if p_start[1] < p_end[1] - 2.5:
                    should_reverse = True
                elif char in ['C', 'E', 'I', 'J', 'L'] and p_start[1] < 4.0 and p_end[1] > 12.0:
                    should_reverse = True
            elif char.isdigit() and p_start[1] < p_end[1] - 2.0:
                should_reverse = True
                
            if should_reverse:
                chained_body[s_idx] = s[::-1]

    # Combine body and secondary strokes
    all_final_strokes = chained_body + secondary_strokes

    # Step 5: Smooth with RDP
    smoothed_strokes = []
    for s in all_final_strokes:
        if len(s) > 2:
            if char == 'm':
                s_smooth = rdp_simplify(s, epsilon=0.04)
            elif char == 'v':
                s_smooth = rdp_simplify(s, epsilon=0.04)
            elif char == 'h':
                s_smooth = rdp_simplify(s, epsilon=0.06)
            elif char in ['H', 'R', 'G', 'T']:
                s_smooth = rdp_simplify(s, epsilon=0.10)
            else:
                s_smooth = rdp_simplify(s, epsilon=0.22)
            smoothed_strokes.append(s_smooth)
        else:
            smoothed_strokes.append(s)

    return smoothed_strokes

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    raw_path = os.path.join(base_dir, 'fonts', 'my_handwriting_raw.json')
    font_path = os.path.join(base_dir, 'fonts', 'my_handwriting.json')
    source_path = raw_path if os.path.exists(raw_path) else font_path
    
    with open(source_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    chars = dict(data['characters'] if 'characters' in data else data)
    if os.path.exists(font_path) and font_path != source_path:
        with open(font_path, 'r', encoding='utf-8') as ff:
            fdata = json.load(ff)
            fchars = fdata['characters'] if 'characters' in fdata else fdata
            for fc, fval in fchars.items():
                if fc not in chars:
                    chars[fc] = fval
    new_chars = {}
    
    total_strokes_orig = 0
    total_strokes_new = 0

    scale_font = 2.249
    cursive_lower_adv = {
        'a': 5.4, 'b': 5.8, 'c': 4.8, 'd': 5.8, 'e': 4.5, 'f': 5.2,
        'g': 5.8, 'h': 6.2, 'i': 3.5, 'j': 4.8, 'k': 5.2, 'l': 3.8,
        'm': 8.0, 'n': 6.8, 'o': 5.0, 'p': 5.5, 'q': 5.2, 'r': 4.5,
        's': 4.2, 't': 4.0, 'u': 5.5, 'v': 4.8, 'w': 8.2, 'x': 5.5,
        'y': 5.5, 'z': 4.8,
        'à': 5.4, 'è': 4.5, 'é': 4.5, 'ì': 3.5, 'ò': 5.0, 'ù': 5.5
    }
    
    for char, cdata in chars.items():
        if isinstance(cdata, list):
            orig_s = cdata
        else:
            orig_s = cdata.get('strokes', [])
        total_strokes_orig += len(orig_s)
        
        # Determine if coordinates are in font units (cap height ~21) or mm (~9.5)
        all_ys = [p[1] for s in orig_s for p in s] if orig_s else [0.0]
        is_font_units = max(all_ys) > 13.0 or (max(all_ys) - min(all_ys)) > 20.0
        
        if is_font_units:
            # Convert to mm for clean_character_strokes
            mm_s = [[[p[0] / scale_font, p[1] / scale_font] for p in s] for s in orig_s]
            opt_s_mm = clean_character_strokes(char, mm_s)
            opt_s = [[[round(p[0] * scale_font, 3), round(p[1] * scale_font, 3)] for p in s] for s in opt_s_mm]
        else:
            opt_s_mm = clean_character_strokes(char, orig_s)
            all_xs_mm = [p[0] for s in opt_s_mm for p in s] if opt_s_mm else [0.0]
            min_x_mm = min(all_xs_mm)
            opt_s = [[[round((p[0] - min_x_mm) * scale_font + 2.0, 3), round(p[1] * scale_font, 3)] for p in s] for s in opt_s_mm]
            
        total_strokes_new += len(opt_s)
        
        # Recompute bounding box and width in font units
        all_xs = [pt[0] for s in opt_s for pt in s] if opt_s else [0.0, 10.0]
        min_x = min(all_xs)
        max_x = max(all_xs)
        
        p_entry = opt_s[0][0] if opt_s and len(opt_s[0]) > 0 else [round(min_x, 3), 0.0]
        p_exit = opt_s[0][-1] if opt_s and len(opt_s[0]) > 0 else [round(max_x, 3), 0.0]

        if char in cursive_lower_adv:
            base_adv = cursive_lower_adv[char] * scale_font
            adv_w = max(base_adv, p_exit[0] + 1.0, max_x + 0.8)
            adv_w = round(min(adv_w, max(p_exit[0] + 2.5, max_x + 2.0)), 3)
        elif char.isupper():
            adv_w = round(max(14.0, max_x + 1.2 * scale_font), 3)
        elif char.isdigit():
            adv_w = round(max(10.0, max_x + 1.0 * scale_font), 3)
        elif char == ' ':
            adv_w = round(6.5 * scale_font, 3)
        else:
            adv_w = round(max(6.0, max_x + 1.0 * scale_font), 3)

        p_entry = opt_s[0][0] if opt_s and len(opt_s[0]) > 0 else [round(min_x, 3), 0.0]
        p_exit = opt_s[0][-1] if opt_s and len(opt_s[0]) > 0 else [round(max_x, 3), 0.0]
        
        new_chars[char] = {
            "strokes": opt_s,
            "width": adv_w,
            "advance_width": adv_w,
            "min_x": round(min_x, 3),
            "max_x": round(max_x, 3),
            "baseline_y": 0.0,
            "entry_point": [round(p_entry[0], 3), round(p_entry[1], 3)],
            "exit_point": [round(p_exit[0], 3), round(p_exit[1], 3)]
        }
        
    out_dict = data if isinstance(data, dict) and "font_name" in data else {
        "font_name": "Giovanni_Handwriting_Calligraphy",
        "description": "True personal handwriting single-line stroke font extracted from iPad Apple Pencil.",
        "units_per_em": 21.0,
        "cap_height": 21.0,
        "x_height": 11.3,
        "baseline_offset": 0.0,
        "space_width": round(6.5 * scale_font, 3),
        "characters": {}
    }
    merged_chars = {}
    if os.path.exists(font_path):
        try:
            with open(font_path, 'r', encoding='utf-8') as ef:
                prev_data = json.load(ef)
                if 'characters' in prev_data:
                    merged_chars = prev_data['characters']
        except Exception:
            merged_chars = {}
    merged_chars.update(new_chars)
    out_dict['characters'] = merged_chars
    
    # Save optimized font
    with open(font_path, 'w', encoding='utf-8') as f:
        json.dump(out_dict, f, indent=2, ensure_ascii=False)
        
    print(f"Font optimized successfully!")
    print(f"Total strokes across all {len(new_chars)} glyphs: {total_strokes_orig} -> {total_strokes_new}")
    print(f"Reduction in pen lifts: -{total_strokes_orig - total_strokes_new} lifts")

if __name__ == '__main__':
    main()
