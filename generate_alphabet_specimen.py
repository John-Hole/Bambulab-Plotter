#!/usr/bin/env python3
"""
generate_alphabet_specimen.py - Generates:
1. High-resolution individual letter chart (anteprima_tabella_alfabeto.png) with start/end dots and guidelines.
2. Full Italian A4 1R Notebook specimen (anteprima_alfabeto_quaderno.png) with alphabet on ruled lines.
"""

import os
import sys
import json
import shutil
from PIL import Image, ImageDraw, ImageFont

def build_alphabet_chart(font_path, output_png):
    with open(font_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    chars = data['characters']
    cap_h = data.get('cap_height', 21.0)
    x_h = data.get('x_height', 11.3)

    # Character groups to display
    groups = [
        ("MINUSCOLE", list("abcdefghijklmnopqrstuvwxyz")),
        ("ACCENTATE", ["à", "è", "é", "ì", "ò", "ù"]),
        ("MAIUSCOLE", list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")),
        ("CIFRE", list("0123456789"))
    ]

    all_items = []
    for gname, clist in groups:
        all_items.append(('header', gname))
        for c in clist:
            all_items.append(('char', c))

    cols = 6
    cell_w = 260
    cell_h = 240
    header_h = 60

    # Calculate layout
    # Lay out items row by row
    grid_rows = []
    curr_row = []
    for kind, val in all_items:
        if kind == 'header':
            if curr_row:
                grid_rows.append(('cells', curr_row))
                curr_row = []
            grid_rows.append(('header', val))
        else:
            curr_row.append(val)
            if len(curr_row) == cols:
                grid_rows.append(('cells', curr_row))
                curr_row = []
    if curr_row:
        grid_rows.append(('cells', curr_row))

    # Calculate total image height
    total_h = 80
    for rkind, _ in grid_rows:
        if rkind == 'header':
            total_h += header_h
        else:
            total_h += cell_h

    img_w = cols * cell_w + 60
    img = Image.new('RGB', (img_w, total_h), '#ffffff')
    draw = ImageDraw.Draw(img)

    # Title
    draw.rectangle([0, 0, img_w, 70], fill='#0f172a')
    draw.text((40, 20), "CAMPIONARIO ALFABETO CALLIGRAFICO - BAMBU LAB A1", fill='#ffffff')

    curr_y = 80
    glyph_scale = 7.0

    for rkind, rdata in grid_rows:
        if rkind == 'header':
            # Section header
            draw.rectangle([30, curr_y + 10, img_w - 30, curr_y + 45], fill='#f1f5f9')
            draw.text((50, curr_y + 18), f"--- {rdata} ---", fill='#334155')
            curr_y += header_h
        else:
            # Draw row of cells
            for col_idx, char in enumerate(rdata):
                cx0 = 30 + col_idx * cell_w
                cy0 = curr_y
                cx1 = cx0 + cell_w - 10
                cy1 = cy0 + cell_h - 10

                # Cell background and border
                draw.rectangle([cx0, cy0, cx1, cy1], fill='#fbfbfa', outline='#cbd5e1', width=1)

                # Character label badge at top
                draw.rectangle([cx0, cy0, cx0 + 60, cy0 + 32], fill='#e2e8f0')
                draw.text((cx0 + 12, cy0 + 8), char, fill='#0f172a')

                # Baseline and guideline positions inside cell
                base_y = cy0 + 175
                asc_y = int(round(base_y - cap_h * glyph_scale * 0.75))
                xh_y = int(round(base_y - x_h * glyph_scale * 0.75))
                desc_y = int(round(base_y + 9.0 * glyph_scale * 0.75))

                # Guidelines
                draw.line([cx0 + 10, asc_y, cx1 - 10, asc_y], fill='#e2e8f0', width=1) # ascender line
                draw.line([cx0 + 10, xh_y, cx1 - 10, xh_y], fill='#bae6fd', width=1)   # x-height line (light blue)
                draw.line([cx0 + 10, base_y, cx1 - 10, base_y], fill='#94a3b8', width=2) # baseline (solid grey)
                draw.line([cx0 + 10, desc_y, cx1 - 10, desc_y], fill='#f1f5f9', width=1) # descender line

                cdata = chars.get(char)
                if not cdata or not cdata.get('strokes'):
                    draw.text((cx0 + 70, cy0 + 90), "(non presente)", fill='#94a3b8')
                    continue

                strokes = cdata['strokes']
                all_xs = [pt[0] for s in strokes for pt in s]
                min_x = min(all_xs)
                max_x = max(all_xs)
                center_offset = (cell_w - (max_x - min_x) * glyph_scale * 0.75) / 2.0 - min_x * glyph_scale * 0.75

                # Draw strokes
                ink_color = '#153675'
                for s_idx, stroke in enumerate(strokes):
                    if len(stroke) >= 2:
                        pts = [(int(cx0 + center_offset + pt[0] * glyph_scale * 0.75),
                                int(base_y - pt[1] * glyph_scale * 0.75)) for pt in stroke]
                        draw.line(pts, fill=ink_color, width=4, joint='round')
                    elif len(stroke) == 1:
                        px = int(cx0 + center_offset + stroke[0][0] * glyph_scale * 0.75)
                        py = int(base_y - stroke[0][1] * glyph_scale * 0.75)
                        draw.ellipse([px-4, py-4, px+4, py+4], fill=ink_color)

                # Draw green dot on start of primary stroke and red dot on end
                if strokes and len(strokes[0]) > 0:
                    p0 = strokes[0][0]
                    p1 = strokes[0][-1]
                    p0_x = int(cx0 + center_offset + p0[0] * glyph_scale * 0.75)
                    p0_y = int(base_y - p0[1] * glyph_scale * 0.75)
                    p1_x = int(cx0 + center_offset + p1[0] * glyph_scale * 0.75)
                    p1_y = int(base_y - p1[1] * glyph_scale * 0.75)

                    draw.ellipse([p0_x-4, p0_y-4, p0_x+4, p0_y+4], fill='#16a34a', outline='#ffffff', width=1) # Green = start
                    draw.ellipse([p1_x-4, p1_y-4, p1_x+4, p1_y+4], fill='#dc2626', outline='#ffffff', width=1) # Red = end

            curr_y += cell_h

    # Legend at bottom
    draw.rectangle([0, total_h - 40, img_w, total_h], fill='#f8fafc')
    draw.ellipse([50, total_h - 26, 60, total_h - 16], fill='#16a34a')
    draw.text((70, total_h - 26), "Punto di Inizio Tratto (Verde)", fill='#334155')
    draw.ellipse([270, total_h - 26, 280, total_h - 16], fill='#dc2626')
    draw.text((290, total_h - 26), "Punto di Fine Tratto (Rosso)", fill='#334155')
    draw.line([500, total_h - 21, 530, total_h - 21], fill='#94a3b8', width=2)
    draw.text((540, total_h - 26), "Linea di Base (Rigo del Quaderno)", fill='#334155')

    img.save(output_png, "PNG")
    print(f"Tabella alfabeto salvata: {output_png}")


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    font_path = os.path.join(base_dir, 'fonts', 'my_handwriting.json')
    table_png = os.path.join(base_dir, 'output', 'anteprima_tabella_alfabeto.png')

    build_alphabet_chart(font_path, table_png)

    # Copy to Downloads
    user_dl = os.path.expanduser(r'~\Downloads\anteprima_tabella_alfabeto.png')
    shutil.copyfile(table_png, user_dl)
    print(f"Copiata in Download: {user_dl}")

if __name__ == '__main__':
    main()
