#!/usr/bin/env python3
"""
generate_comparison_chart.py - Generates comparison specimen for the 5 perfected glyphs:
'm', 'h', 'G', 'H', 'R' with detailed visual guidelines and annotations.
"""

import os
import json
import shutil
from PIL import Image, ImageDraw, ImageFont

def build_comparison_chart(font_path, output_png):
    with open(font_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    chars = data['characters']
    cap_h = data.get('cap_height', 21.0)
    x_h = data.get('x_height', 11.3)

    items = [
        ('m', "m minuscola: 3 campate fluide con retrace aderente sul fusto,\nnessuna corda diagonale che taglia i contatori interni."),
        ('h', "h minuscola: fusto continuo dritto fino al rigo di base,\narco a piena altezza x-height e curva d'uscita sul rigo."),
        ('G', "G corsiva maiuscola: proporzionata a tutta altezza cap-height (21u),\nasola inferiore sotto il rigo e raccordo orizzontale."),
        ('H', "H corsiva maiuscola: sequenza continua a 2 fusti senza grovigli:\nentrata -> fusto sin. -> asola base -> traversa -> fusto des. -> uscita."),
        ('R', "R corsiva maiuscola: fusto sinistro dritto senza gobba a palloncino,\nocchiello destro chiuso al centro e gamba arcuata a terra."),
        ('D', "D corsiva maiuscola: fusto verticale continuo fino al rigo di base,\nasola al piede a sinistra, arco superiore e pancia destra chiusa al piede.")
    ]

    img_w = 1200
    row_h = 220
    header_h = 100
    total_h = header_h + len(items) * row_h + 60

    img = Image.new('RGB', (img_w, total_h), '#ffffff')
    draw = ImageDraw.Draw(img)

    # Header banner
    draw.rectangle([0, 0, img_w, header_h], fill='#0f172a')
    draw.text((40, 24), "CONFRONTO PERFEZIONAMENTO GLIFI CALLIGRAFICI - BAMBU LAB A1", fill='#ffffff')
    draw.text((40, 56), "Verifica e validazione geometrica tratti: m, h, G, H, R (Second Brain / Scrittura)", fill='#94a3b8')

    curr_y = header_h + 20
    glyph_scale = 6.2

    for char, desc in items:
        cy0 = curr_y
        cy1 = cy0 + row_h - 20
        cx_box0 = 40
        cx_box1 = 360

        # Letter preview card
        draw.rectangle([cx_box0, cy0, cx_box1, cy1], fill='#fbfbfa', outline='#cbd5e1', width=1)
        # Letter badge
        draw.rectangle([cx_box0, cy0, cx_box0 + 60, cy0 + 36], fill='#1e293b')
        draw.text((cx_box0 + 20, cy0 + 10), char, fill='#ffffff')

        # Description card
        draw.rectangle([cx_box1 + 20, cy0, img_w - 40, cy1], fill='#f8fafc', outline='#e2e8f0', width=1)
        draw.text((cx_box1 + 45, cy0 + 30), f"Glifo: '{char}' - Regole Topologiche Applicate", fill='#0f172a')
        
        # Render description text
        lines = desc.split('\n')
        line_y = cy0 + 70
        for l in lines:
            draw.text((cx_box1 + 45, line_y), l, fill='#475569')
            line_y += 26

        # Draw glyph inside preview card
        cdata = chars.get(char)
        if cdata and cdata.get('strokes'):
            base_y = cy0 + 145
            asc_y = int(round(base_y - cap_h * glyph_scale * 0.75))
            xh_y = int(round(base_y - x_h * glyph_scale * 0.75))
            desc_y = int(round(base_y + 10.0 * glyph_scale * 0.75))

            # Guidelines
            draw.line([cx_box0 + 10, asc_y, cx_box1 - 10, asc_y], fill='#e2e8f0', width=1) # ascender
            draw.line([cx_box0 + 10, xh_y, cx_box1 - 10, xh_y], fill='#bae6fd', width=1)   # x-height
            draw.line([cx_box0 + 10, base_y, cx_box1 - 10, base_y], fill='#94a3b8', width=2) # baseline
            if char in ['G', 'y', 'g', 'p', 'q', 'f', 'j']:
                draw.line([cx_box0 + 10, desc_y, cx_box1 - 10, desc_y], fill='#fed7aa', width=1) # descender

            strokes = cdata['strokes']
            all_xs = [pt[0] for s in strokes for pt in s]
            min_x = min(all_xs)
            max_x = max(all_xs)
            card_w = cx_box1 - cx_box0
            center_offset = (card_w - (max_x - min_x) * glyph_scale * 0.75) / 2.0 - min_x * glyph_scale * 0.75

            ink_color = '#153675'
            for stroke in strokes:
                if len(stroke) >= 2:
                    pts = [(int(cx_box0 + center_offset + pt[0] * glyph_scale * 0.75),
                            int(base_y - pt[1] * glyph_scale * 0.75)) for pt in stroke]
                    draw.line(pts, fill=ink_color, width=4, joint='round')
                elif len(stroke) == 1:
                    px = int(cx_box0 + center_offset + stroke[0][0] * glyph_scale * 0.75)
                    py = int(base_y - stroke[0][1] * glyph_scale * 0.75)
                    draw.ellipse([px-4, py-4, px+4, py+4], fill=ink_color)

            # Start and End points
            if strokes and len(strokes[0]) > 0:
                p0 = strokes[0][0]
                p1 = strokes[0][-1]
                p0_x = int(cx_box0 + center_offset + p0[0] * glyph_scale * 0.75)
                p0_y = int(base_y - p0[1] * glyph_scale * 0.75)
                p1_x = int(cx_box0 + center_offset + p1[0] * glyph_scale * 0.75)
                p1_y = int(base_y - p1[1] * glyph_scale * 0.75)

                draw.ellipse([p0_x-5, p0_y-5, p0_x+5, p0_y+5], fill='#16a34a', outline='#ffffff', width=2)
                draw.ellipse([p1_x-5, p1_y-5, p1_x+5, p1_y+5], fill='#dc2626', outline='#ffffff', width=2)

        curr_y += row_h

    # Legend at footer
    draw.rectangle([0, total_h - 45, img_w, total_h], fill='#f8fafc')
    draw.ellipse([50, total_h - 30, 60, total_h - 20], fill='#16a34a')
    draw.text((70, total_h - 30), "Punto di Inizio Tratto (Verde)", fill='#334155')
    draw.ellipse([270, total_h - 30, 280, total_h - 20], fill='#dc2626')
    draw.text((290, total_h - 30), "Punto di Fine Tratto (Rosso)", fill='#334155')
    draw.line([500, total_h - 25, 530, total_h - 25], fill='#94a3b8', width=2)
    draw.text((540, total_h - 30), "Linea di Base", fill='#334155')
    draw.line([660, total_h - 25, 690, total_h - 25], fill='#bae6fd', width=2)
    draw.text((700, total_h - 30), "Altezza Minuscole (x-height)", fill='#334155')

    os.makedirs(os.path.dirname(output_png), exist_ok=True)
    img.save(output_png, "PNG")
    print(f"Tavola confronto lettere salvata: {output_png}")

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    font_path = os.path.join(base_dir, 'fonts', 'my_handwriting.json')
    out_png = os.path.join(base_dir, 'output', 'confronto_lettere_risolte.png')
    build_comparison_chart(font_path, out_png)

    # Copy to Google Drive "2 | Second Brain/Scrittura"
    gdrive_dir = "/home/buco-py/GoogleDrive/2 | Second Brain/Scrittura"
    if os.path.exists(gdrive_dir):
        try:
            gd_png = os.path.join(gdrive_dir, "confronto_lettere_risolte.png")
            shutil.copyfile(out_png, gd_png)
            print(f"Copiata su Google Drive: {gd_png}")
            gd_json = os.path.join(gdrive_dir, "my_handwriting.json")
            shutil.copyfile(font_path, gd_json)
            print(f"Copiato su Google Drive: {gd_json}")
        except Exception as e:
            print(f"Avviso copia Google Drive: {e}")

if __name__ == '__main__':
    main()
