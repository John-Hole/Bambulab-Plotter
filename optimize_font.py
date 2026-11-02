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

    is_dot_char = char in ['i', 'j', '.', ':', ';', '!', '?', 'à', 'è', 'é', 'ì', 'ò', 'ù']
    
    # Step 1: Filter out baseline guide lines & tiny noise specks
    filtered = []
    for s in strokes:
        if len(s) < 2:
            if is_dot_char:
                filtered.append(s)
            continue
        xs = [p[0] for p in s]
        ys = [p[1] for p in s]
        dx = max(xs) - min(xs)
        dy = max(ys) - min(ys)
        l = sum(distance(s[k], s[k+1]) for k in range(len(s)-1))
        avg_y = sum(ys) / len(ys)
        
        # Eliminate horizontal guideline fragments near baseline
        if dy < 0.45 and dx > 0.8 and (-0.8 <= avg_y <= 1.8):
            continue
            
        # Eliminate short noisy spurs
        if l < 0.8 and not is_dot_char:
            continue
            
        filtered.append(s)
        
    if not filtered:
        return []

    # Step 2: Separate secondary strokes (dots, accents, crossbars) from main body
    body_strokes = []
    secondary_strokes = []
    
    for s in filtered:
        ys = [p[1] for p in s]
        min_y = min(ys)
        max_y = max(ys)
        l = sum(distance(s[k], s[k+1]) for k in range(len(s)-1)) if len(s) > 1 else 0
        
        # Dots for i, j (short stroke above y > 9.0)
        if char in ['i', 'j'] and min_y > 8.5 and l < 3.5:
            secondary_strokes.append(s)
        # Accents for vowels (short stroke above y > 10.0)
        elif char in ['à', 'è', 'é', 'ì', 'ò', 'ù'] and min_y > 10.0 and l < 6.0:
            secondary_strokes.append(s)
        # Crossbar for t (horizontal stroke around y in [7.0, 11.0])
        elif char == 't' and len(body_strokes) >= 1 and 6.5 <= min_y <= 12.0 and max_y - min_y < 2.0:
            secondary_strokes.append(s)
        else:
            body_strokes.append(s)
            
    if not body_strokes and secondary_strokes:
        body_strokes = secondary_strokes
        secondary_strokes = []

    # Step 3: Weld/chain body strokes into a single continuous polyline
    remaining = [list(s) for s in body_strokes]
    # Start with the longest body stroke
    remaining.sort(key=lambda s: sum(distance(s[k], s[k+1]) for k in range(len(s)-1)), reverse=True)
    
    chained_body = [remaining.pop(0)]
    
    changed = True
    while changed and remaining:
        changed = False
        curr = chained_body[-1]
        best_i = -1
        best_d = 999999.0
        best_mode = None
        
        for i, s in enumerate(remaining):
            d1 = distance(curr[-1], s[0])
            d2 = distance(curr[-1], s[-1])
            d3 = distance(s[-1], curr[0])
            d4 = distance(s[0], curr[0])
            
            for d, mode in [(d1, 'append'), (d2, 'append_rev'), (d3, 'prepend'), (d4, 'prepend_rev')]:
                if d < best_d:
                    best_d = d
                    best_i = i
                    best_mode = mode
                    
        # Join tolerance: up to 3.8 mm gap between fragments
        if best_i != -1 and best_d <= 3.8:
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

    # Any remaining body fragments that could not be welded
    for s in remaining:
        chained_body.append(s)

    # Step 4: Ensure the main body flows left-to-right
    if chained_body:
        main_s = chained_body[0]
        if len(main_s) > 1 and main_s[0][0] > main_s[-1][0] and (main_s[0][0] - main_s[-1][0]) > 2.0:
            chained_body[0] = main_s[::-1]

    # Combine body and secondary strokes
    all_final_strokes = chained_body + secondary_strokes

    # Step 5: Smooth with RDP
    smoothed_strokes = []
    for s in all_final_strokes:
        if len(s) > 2:
            s_smooth = rdp_simplify(s, epsilon=0.22)
            smoothed_strokes.append(s_smooth)
        else:
            smoothed_strokes.append(s)

    return smoothed_strokes

def main():
    base_dir = r'C:\Users\giova\.gemini\antigravity\scratch\bambu_a1_plotter'
    raw_path = os.path.join(base_dir, 'fonts', 'my_handwriting_raw.json')
    font_path = os.path.join(base_dir, 'fonts', 'my_handwriting.json')
    source_path = raw_path if os.path.exists(raw_path) else font_path
    
    with open(source_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    chars = data['characters']
    new_chars = {}
    
    total_strokes_orig = 0
    total_strokes_new = 0

    # Authentic cursive lowercase advances (stem-to-stem body width)
    cursive_lower_adv = {
        'a': 5.4, 'b': 5.8, 'c': 4.8, 'd': 5.8, 'e': 4.5, 'f': 5.2,
        'g': 5.8, 'h': 6.2, 'i': 3.5, 'j': 4.8, 'k': 5.2, 'l': 3.8,
        'm': 10.5, 'n': 6.8, 'o': 5.0, 'p': 5.5, 'q': 5.2, 'r': 4.5,
        's': 4.2, 't': 4.0, 'u': 5.5, 'v': 4.8, 'w': 8.2, 'x': 5.5,
        'y': 5.5, 'z': 4.8,
        'à': 5.4, 'è': 4.5, 'é': 4.5, 'ì': 3.5, 'ò': 5.0, 'ù': 5.5
    }
    
    for char, cdata in chars.items():
        orig_s = cdata.get('strokes', [])
        total_strokes_orig += len(orig_s)
        
        opt_s = clean_character_strokes(char, orig_s)
        total_strokes_new += len(opt_s)
        
        # Recompute bounding box and width
        all_xs = [pt[0] for s in opt_s for pt in s] if opt_s else [0.0, 10.0]
        min_x = min(all_xs)
        max_x = max(all_xs)
        
        # Natural cursive advance width: tight stem-to-stem spacing for connected writing
        if char in cursive_lower_adv:
            adv_w = cursive_lower_adv[char]
        elif char.isupper():
            adv_w = round(max(5.0, (max_x - min_x) + 1.2), 3)
        elif char.isdigit():
            adv_w = round(max(4.0, (max_x - min_x) + 1.0), 3)
        elif char == ' ':
            adv_w = 6.5
        else:
            # Punctuation / symbols
            adv_w = round(max(2.5, (max_x - min_x) + 1.5), 3)

        p_entry = opt_s[0][0] if opt_s and len(opt_s[0]) > 0 else [round(min_x, 3), 0.0]
        p_exit = opt_s[0][-1] if opt_s and len(opt_s[0]) > 0 else [round(max_x, 3), 0.0]
        
        new_chars[char] = {
            "strokes": [[[round(p[0], 3), round(p[1], 3)] for p in s] for s in opt_s],
            "width": adv_w,
            "advance_width": adv_w,
            "min_x": round(min_x, 3),
            "max_x": round(max_x, 3),
            "baseline_y": 0.0,
            "entry_point": [round(p_entry[0], 3), round(p_entry[1], 3)],
            "exit_point": [round(p_exit[0], 3), round(p_exit[1], 3)]
        }
        
    data['characters'] = new_chars
    
    # Save optimized font
    with open(font_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    print(f"Font optimized successfully!")
    print(f"Total strokes across all 92 glyphs: {total_strokes_orig} -> {total_strokes_new}")
    print(f"Reduction in pen lifts: -{total_strokes_orig - total_strokes_new} lifts (-{((total_strokes_orig - total_strokes_new)/total_strokes_orig)*100:.1f}%)")

if __name__ == '__main__':
    main()
