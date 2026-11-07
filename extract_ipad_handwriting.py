#!/usr/bin/env python3
"""
extract_ipad_handwriting.py - Extracts single-line cursive strokes from iPad calibration sheet.
Supports:
1. Native Vector PDF (Goodnotes, Notability, Freeform, vector PDF) -> Native Bezier / line extraction.
2. Digital Stamp / Raster PDF (Apple Notes, iOS Files Markup, Procreate) -> High-res 300 DPI digital template subtraction & medial axis skeletonization.
"""

import os
import sys
import json
import math
import numpy as np
from PIL import Image

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

def extract_from_vector_pdf(doc, spec):
    PT_TO_MM = 25.4 / 72.0
    extracted_chars = {}
    
    for page_idx, page_info in enumerate(spec['pages']):
        if page_idx >= len(doc):
            break
        page = doc[page_idx]
        H = page.rect.height
        drawings = page.get_drawings()
        
        cells = page_info['cells']
        for cell in cells:
            char = cell['char']
            c_rect = cell['rect_pt'] # [x0, y0, x1, y1] in ReportLab coords
            c_base = cell['baseline_pt']
            
            cx0, cy0, cx1, cy1 = c_rect
            fitz_y0 = H - cy1
            fitz_y1 = H - cy0
            fitz_base = H - c_base
            
            char_strokes = []
            
            # Source A: Vector drawings
            for d in drawings:
                d_rect = d.get('rect')
                if not d_rect:
                    continue
                
                mid_x = (d_rect.x0 + d_rect.x1) * 0.5
                mid_y = (d_rect.y0 + d_rect.y1) * 0.5
                if not (cx0 <= mid_x < cx1 and fitz_y0 <= mid_y < fitz_y1):
                    continue
                    
                if d.get('fill') is not None and not d.get('color'):
                    continue
                    
                dy_box = abs(d_rect.y1 - d_rect.y0)
                dx_box = abs(d_rect.x1 - d_rect.x0)
                if dy_box < 0.25 and dx_box > (cx1 - cx0) * 0.4:
                    continue
                    
                if abs(d_rect.x0 - cx0) < 1.0 and abs(d_rect.x1 - cx1) < 1.0 and abs(d_rect.y0 - fitz_y0) < 1.0:
                    continue

                color = d.get('color')
                if color is not None and len(color) >= 3:
                    lum = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
                    if lum > 0.65 or color == (0.23137299716472626, 0.5098040103912354, 0.9647060036659241):
                        continue
                
                current_stroke = []
                for item in d.get('items', []):
                    cmd = item[0]
                    if cmd == 'l':
                        p1, p2 = item[1], item[2]
                        if not current_stroke:
                            current_stroke.append((p1.x, p1.y))
                        current_stroke.append((p2.x, p2.y))
                    elif cmd == 'c':
                        p1, p2, p3, p4 = item[1], item[2], item[3], item[4]
                        sampled = sample_cubic_bezier((p1.x, p1.y), (p2.x, p2.y), (p3.x, p3.y), (p4.x, p4.y), steps=8)
                        if current_stroke:
                            current_stroke.extend(sampled[1:])
                        else:
                            current_stroke.extend(sampled)
                
                if len(current_stroke) >= 2:
                    stroke_mm = []
                    for px, py in current_stroke:
                        mx = round((px - cx0) * PT_TO_MM, 3)
                        my = round((fitz_base - py) * PT_TO_MM, 3)
                        stroke_mm.append([mx, my])
                    char_strokes.append(stroke_mm)

            # Source B: PDF Annotations
            for annot in page.annots():
                if annot.type[0] == 15: # fitz.PDF_ANNOT_INK
                    a_rect = annot.rect
                    mid_x = (a_rect.x0 + a_rect.x1) * 0.5
                    mid_y = (a_rect.y0 + a_rect.y1) * 0.5
                    if cx0 <= mid_x < cx1 and fitz_y0 <= mid_y < fitz_y1:
                        for ink_stroke in annot.vertices:
                            if len(ink_stroke) >= 2:
                                stroke_mm = []
                                for pt in ink_stroke:
                                    px = pt[0] if isinstance(pt, (tuple, list)) else pt.x
                                    py = pt[1] if isinstance(pt, (tuple, list)) else pt.y
                                    mx = round((px - cx0) * PT_TO_MM, 3)
                                    my = round((fitz_base - py) * PT_TO_MM, 3)
                                    stroke_mm.append([mx, my])
                                char_strokes.append(stroke_mm)
            
            if char_strokes:
                extracted_chars[char] = char_strokes
                
    return extracted_chars

def extract_from_raster_pdf(doc_user, spec, template_pdf_path="templates/foglio_calibrazione_ipad.pdf", dpi=300):
    import fitz
    from skimage.morphology import skeletonize
    from vectorize_handwriting import SkeletonTracer

    doc_blank = fitz.open(template_pdf_path)
    scale = dpi / 72.0
    PX_TO_MM = 25.4 / dpi
    H_pt = doc_user[0].rect.height

    raw_char_strokes = {}

    for pidx, page_info in enumerate(spec['pages']):
        if pidx >= len(doc_user) or pidx >= len(doc_blank):
            break
        pix_blank = doc_blank[pidx].get_pixmap(dpi=dpi)
        pix_user = doc_user[pidx].get_pixmap(dpi=dpi)
        
        arr_blank = np.array(Image.frombytes('RGB', [pix_blank.width, pix_blank.height], pix_blank.samples))
        arr_user = np.array(Image.frombytes('RGB', [pix_user.width, pix_user.height], pix_user.samples))
        
        diff = (arr_blank.astype(np.int16) - arr_user.astype(np.int16))
        ink_mask = np.max(diff, axis=2) > 40
        
        for cell in page_info['cells']:
            char = cell['char']
            cx0, cy0, cx1, cy1 = cell['rect_pt']
            c_base = cell['baseline_pt']
            
            fy0 = H_pt - cy1
            fy1 = H_pt - cy0
            f_base = H_pt - c_base
            
            x0, y0 = int(round(cx0 * scale)), int(round(fy0 * scale))
            x1, y1 = int(round(cx1 * scale)), int(round(fy1 * scale))
            
            cell_mask = ink_mask[y0:y1, x0:x1].copy()
            # mask badge header and cell outer boundaries
            cell_mask[:int(round(20.0 * scale)), :] = False
            cell_mask[:, :int(round(2.0 * scale))] = False
            cell_mask[:, -int(round(2.0 * scale)):] = False
            cell_mask[-int(round(2.0 * scale)):, :] = False
            
            if np.sum(cell_mask) < 25:
                continue
                
            skel = skeletonize(cell_mask)
            raw_strokes = SkeletonTracer.trace(skel, rdp_epsilon=0.7)
            
            baseline_px = (f_base - fy0) * scale
            
            mm_strokes = []
            for s in raw_strokes:
                s_mm = []
                for (px, py) in s:
                    mx = px * PX_TO_MM
                    my = (baseline_px - py) * PX_TO_MM
                    s_mm.append([mx, my])
                mm_strokes.append(s_mm)
                
            if mm_strokes:
                raw_char_strokes[char] = mm_strokes

    return raw_char_strokes

def process_and_save_font(raw_strokes_dict, output_font_path):
    from optimize_font import clean_character_strokes

    # 1. Measure user capital letter height to calculate font scale factor
    cap_heights = []
    for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        if c in raw_strokes_dict:
            ys = [p[1] for s in raw_strokes_dict[c] for p in s]
            if ys and (max(ys) - min(ys)) > 3.0:
                cap_heights.append(max(ys) - min(ys))

    mean_cap_h = float(np.mean(cap_heights)) if cap_heights else 9.45
    scale_to_font = 21.0 / mean_cap_h
    print(f"Measured natural capital height: {mean_cap_h:.2f}mm -> font unit scale: {scale_to_font:.3f}")

    # Authentic cursive lowercase advances for Italian notebook ruling
    cursive_lower_adv = {
        'a': 5.4, 'b': 5.8, 'c': 4.8, 'd': 5.8, 'e': 4.5, 'f': 5.2,
        'g': 5.8, 'h': 6.2, 'i': 3.5, 'j': 4.8, 'k': 5.2, 'l': 3.8,
        'm': 8.0, 'n': 6.8, 'o': 5.0, 'p': 5.5, 'q': 5.2, 'r': 4.5,
        's': 4.2, 't': 4.0, 'u': 5.5, 'v': 4.8, 'w': 8.2, 'x': 5.5,
        'y': 5.5, 'z': 4.8,
        'à': 5.4, 'è': 4.5, 'é': 4.5, 'ì': 3.5, 'ò': 5.0, 'ù': 5.5
    }

    base_data = {
        "font_name": "Giovanni_Handwriting_Calligraphy",
        "description": "True personal handwriting single-line stroke font extracted from iPad Apple Pencil.",
        "units_per_em": 21.0,
        "cap_height": 21.0,
        "x_height": 11.3,
        "baseline_offset": 0.0,
        "space_width": 7.0,
        "characters": {}
    }
    if os.path.exists(output_font_path):
        try:
            with open(output_font_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
                if "characters" in existing:
                    base_data = existing
        except Exception as e:
            print(f"Warning reading existing font: {e}")

    cleaned_dict = {}
    for char, strokes in raw_strokes_dict.items():
        cleaned = clean_character_strokes(char, strokes)
        if cleaned:
            cleaned_dict[char] = cleaned

    # Synthesize missing dot for 'j' if needed by cloning i's dot aligned with j's stem
    if 'j' in cleaned_dict and 'i' in cleaned_dict:
        j_strokes = cleaned_dict['j']
        has_dot = any(min(p[1] for p in s) >= 4.5 for s in j_strokes)
        if not has_dot:
            i_dots = [s for s in cleaned_dict['i'] if min(p[1] for p in s) >= 4.5 and len(s) <= 10]
            i_body = [s for s in cleaned_dict['i'] if min(p[1] for p in s) < 4.5]
            if i_dots and i_body:
                top_i = max((p for s in i_body for p in s), key=lambda pt: pt[1])
                top_j = max((p for s in j_strokes for p in s), key=lambda pt: pt[1])
                dx = top_j[0] - top_i[0]
                dy = top_j[1] - top_i[1]
                for ds in i_dots:
                    cloned_dot = [[round(p[0] + dx, 3), round(p[1] + dy, 3)] for p in ds]
                    j_strokes.append(cloned_dot)

    space_w = round(6.5 * scale_to_font, 3)
    base_data["space_width"] = space_w
    if " " in base_data["characters"]:
        base_data["characters"][" "]["advance_width"] = space_w
        base_data["characters"][" "]["width"] = space_w
    else:
        base_data["characters"][" "] = {
            "strokes": [],
            "width": space_w,
            "advance_width": space_w,
            "min_x": 0.0,
            "max_x": space_w,
            "baseline_y": 0.0,
            "entry_point": [0.0, 0.0],
            "exit_point": [space_w, 0.0]
        }

    updated_count = 0
    for char, cleaned in cleaned_dict.items():
        all_xs = [p[0] for s in cleaned for p in s]
        min_x = min(all_xs)
        max_x = max(all_xs)
        
        scaled_strokes = []
        for s in cleaned:
            s_scaled = []
            for p in s:
                fx = round((p[0] - min_x) * scale_to_font + 2.0, 3)
                fy = round(p[1] * scale_to_font, 3)
                s_scaled.append([fx, fy])
            scaled_strokes.append(s_scaled)
            
        s_xs = [p[0] for s in scaled_strokes for p in s]
        s_min_x = min(s_xs)
        s_max_x = max(s_xs)
        
        p_entry = scaled_strokes[0][0] if scaled_strokes and scaled_strokes[0] else [round(s_min_x, 3), 0.0]
        p_exit = scaled_strokes[0][-1] if scaled_strokes and scaled_strokes[0] else [round(s_max_x, 3), 0.0]

        # Proportional advance widths in font units
        if char in cursive_lower_adv:
            base_adv = cursive_lower_adv[char] * scale_to_font
            adv = max(base_adv, p_exit[0] + 1.0, s_max_x + 0.8)
            adv = round(min(adv, max(p_exit[0] + 2.5, s_max_x + 2.0)), 3)
        elif char.isupper():
            adv = round(max(14.0, s_max_x + 1.2 * scale_to_font), 3)
        elif char.isdigit():
            adv = round(max(10.0, s_max_x + 1.0 * scale_to_font), 3)
        elif char == ' ':
            adv = space_w
        else:
            adv = round(max(6.0, s_max_x + 1.0 * scale_to_font), 3)
        
        base_data["characters"][char] = {
            "strokes": scaled_strokes,
            "width": adv,
            "advance_width": adv,
            "min_x": round(s_min_x, 3),
            "max_x": round(s_max_x, 3),
            "baseline_y": 0.0,
            "entry_point": [round(p_entry[0], 3), round(p_entry[1], 3)],
            "exit_point": [round(p_exit[0], 3), round(p_exit[1], 3)]
        }
        updated_count += 1

    with open(output_font_path, 'w', encoding='utf-8') as f:
        json.dump(base_data, f, indent=2, ensure_ascii=False)

    raw_path = os.path.join(os.path.dirname(output_font_path), 'my_handwriting_raw.json')
    try:
        with open(raw_path, 'w', encoding='utf-8') as f:
            json.dump({"units": "mm", "characters": raw_strokes_dict}, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning saving raw font: {e}")
        
    print(f"Successfully saved {updated_count} iPad handwriting glyphs into {output_font_path} (total font: {len(base_data['characters'])})")
    return updated_count

def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_ipad_handwriting.py <input.pdf> [output_font.json]")
        sys.exit(1)
        
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "fonts/my_handwriting.json"
    spec_path = "templates/ipad_grid_spec.json"
    template_path = "templates/foglio_calibrazione_ipad.pdf"
    
    import fitz
    with open(spec_path, 'r', encoding='utf-8') as f:
        spec = json.load(f)
        
    doc = fitz.open(inp)
    print(f"Analyzing PDF: {inp} ({len(doc)} pages)...")
    
    # Try native vector extraction first
    raw_glyphs = extract_from_vector_pdf(doc, spec)
    print(f"Vector extraction found: {len(raw_glyphs)} glyph(s)")
    
    # If not enough vector paths (e.g. iPad Markup saved as high-res Stamp annotations), use digital raster subtraction
    if len(raw_glyphs) < 10:
        print("Switching to High-Resolution Digital Subtraction & Medial Axis Skeletonization...")
        raw_glyphs = extract_from_raster_pdf(doc, spec, template_path, dpi=300)
        print(f"Digital skeleton extraction found: {len(raw_glyphs)} glyph(s)")
        
    if raw_glyphs:
        process_and_save_font(raw_glyphs, out)
    else:
        print("Error: No glyphs could be extracted from the provided PDF.")
        sys.exit(1)

if __name__ == '__main__':
    main()
