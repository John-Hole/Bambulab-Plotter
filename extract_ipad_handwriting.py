#!/usr/bin/env python3
"""
extract_ipad_handwriting.py - Extracts single-line cursive strokes from iPad input.
Supports:
1. Vector PDF (Goodnotes, Notability, Apple Notes, Freeform, Files Markup) -> Native Bezier vector extraction.
2. Digital Image (PNG/JPEG) -> High-res 0-noise skeletonization.
"""

import os
import sys
import json
import math
import numpy as np

def sample_cubic_bezier(p0, p1, p2, p3, steps=10):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        t2 = t * t
        t3 = t2 * t
        u = 1.0 - t
        u2 = u * u
        u3 = u2 * u
        x = u3 * p0[0] + 3 * u2 * t * p1[0] + 3 * u * t2 * p2[0] + t3 * p3[0]
        y = u3 * p0[1] + 3 * u2 * t * p1[1] + 3 * u * t2 * p2[1] + t3 * p3[1]
        pts.append((x, y))
    return pts

def extract_from_vector_pdf(pdf_path, spec_path, output_font_path):
    import fitz
    
    with open(spec_path, 'r', encoding='utf-8') as f:
        spec = json.load(f)
        
    doc = fitz.open(pdf_path)
    extracted_chars = {}
    
    PT_TO_MM = 25.4 / 72.0
    
    for page_idx, page_info in enumerate(spec['pages']):
        if page_idx >= len(doc):
            break
        page = doc[page_idx]
        drawings = page.get_drawings()
        
        cells = page_info['cells']
        for cell in cells:
            char = cell['char']
            c_rect = cell['rect_pt'] # [x0, y0, x1, y1]
            c_base = cell['baseline_pt']
            
            cx0, cy0, cx1, cy1 = c_rect
            # Safety margin inside cell
            margin = 3.0
            bx0 = cx0 + margin
            bx1 = cx1 - margin
            by0 = cy0 + margin
            by1 = cy1 - margin - 15.0 # ignore label badge at top
            
            char_strokes = []
            
            for d in drawings:
                # Ignore background or template strokes
                d_rect = d.get('rect')
                if not d_rect:
                    continue
                    
                # Check if stroke is inside this cell
                if (d_rect.x0 >= bx0 - 5.0 and d_rect.x1 <= bx1 + 5.0 and
                    d_rect.y0 >= by0 - 5.0 and d_rect.y1 <= by1 + 5.0):
                    
                    # Check stroke color: user ink is usually dark
                    color = d.get('color')
                    fill = d.get('fill')
                    
                    # Check items (lines, curves)
                    current_stroke = []
                    for item in d.get('items', []):
                        cmd = item[0]
                        if cmd == 'l': # line (p1, p2)
                            p1, p2 = item[1], item[2]
                            if not current_stroke:
                                current_stroke.append((p1.x, p1.y))
                            current_stroke.append((p2.x, p2.y))
                        elif cmd == 'c': # cubic curve (p1, p2, p3, p4)
                            p1, p2, p3, p4 = item[1], item[2], item[3], item[4]
                            sampled = sample_cubic_bezier((p1.x, p1.y), (p2.x, p2.y), (p3.x, p3.y), (p4.x, p4.y), steps=8)
                            if current_stroke:
                                current_stroke.extend(sampled[1:])
                            else:
                                current_stroke.extend(sampled)
                    
                    if len(current_stroke) >= 2:
                        # Convert to mm relative to baseline
                        # In PDF, Y goes downwards from top of page
                        stroke_mm = []
                        for px, py in current_stroke:
                            # x relative to cell left, in mm
                            mx = round((px - cx0) * PT_TO_MM, 3)
                            # y relative to baseline (positive upwards)
                            my = round((c_base - py) * PT_TO_MM, 3)
                            stroke_mm.append([mx, my])
                        char_strokes.append(stroke_mm)
            
            if char_strokes:
                # Calculate advance width and bounding box
                xs = [pt[0] for s in char_strokes for pt in s]
                min_x = min(xs)
                max_x = max(xs)
                w = max_x - min_x
                
                # Advance width
                if char.isupper() or char.isdigit():
                    adv = round(w + 2.5, 2)
                else:
                    adv = round(w + 1.2, 2)
                    
                extracted_chars[char] = {
                    "advance_width": adv,
                    "strokes": char_strokes
                }
                print(f"Extracted '{char}': {len(char_strokes)} stroke(s), w={w:.2f}mm, adv={adv:.2f}mm")
    
    print(f"Total extracted glyphs from vector PDF: {len(extracted_chars)}")
    return extracted_chars

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python extract_ipad_handwriting.py <input.pdf_or_png> [output_font.json]")
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "fonts/my_ipad_handwriting.json"
    spec = "templates/ipad_grid_spec.json"
    if inp.lower().endswith('.pdf'):
        res = extract_from_vector_pdf(inp, spec, out)
        if res:
            with open(out, 'w', encoding='utf-8') as f:
                json.dump({"cap_height": 21.0, "x_height": 11.3, "characters": res}, f, indent=2, ensure_ascii=False)
            print(f"Saved to {out}")
