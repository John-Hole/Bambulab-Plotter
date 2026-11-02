#!/usr/bin/env python3
"""
generate_calibration_sheet.py - Generates printable handwriting calibration sheets.

Creates:
  1. templates/handwriting_calibration_sheet.pdf (High quality vector PDF for printing)
  2. templates/handwriting_calibration_sheet.png (High-res reference image)
  3. templates/calibration_grid_spec.json (Metadata describing cell bounds and fiducials)
"""

import os
import json
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw, ImageFont

# A4 dimensions in mm and points
PAGE_W_MM = 210.0
PAGE_H_MM = 297.0
MM_TO_PT = 72.0 / 25.4  # ~2.83465 pt/mm
PT_TO_MM = 25.4 / 72.0

GRID_ROWS = 7
GRID_COLS = 13

CHARS_GRID = [
    ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M"],
    ["N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"],
    ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m"],
    ["n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z"],
    ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ".", ",", ";"],
    [":", "!", "?", "'", "\"", "(", ")", "-", "+", "=", "à", "è", "é"],
    ["ì", "ò", "ù", "À", "È", "É", "€", "/", "«", "»", "_", "*", "%"]
]

# Margins and grid layout in mm
MARGIN_X_MM = 16.0
GRID_START_Y_MM = 46.0  # from top of page
CELL_W_MM = 13.6
CELL_H_MM = 28.0

# Inside cell vertical guides (measured from bottom of cell in mm):
# Cell bottom: y = 0
# Descender line: y = 4.0 mm
# Baseline: y = 10.0 mm
# X-height line: y = 17.0 mm
# Cap height line: y = 23.0 mm
# Cell top: y = 28.0 mm
BASELINE_MM = 10.0
DESCENDER_MM = 4.0
X_HEIGHT_MM = 17.0
CAP_HEIGHT_MM = 23.0

# Fiducial square size (mm)
MARKER_SIZE_MM = 9.0
MARKER_OFFSET_X_MM = 6.0
MARKER_OFFSET_Y_MM = 6.0

def generate_pdf(output_pdf_path):
    c = canvas.Canvas(output_pdf_path, pagesize=A4)
    page_w_pt = PAGE_W_MM * MM_TO_PT
    page_h_pt = PAGE_H_MM * MM_TO_PT

    # Coordinate transformation: ReportLab origin is bottom-left
    def mm_to_pdf_x(x_mm):
        return x_mm * MM_TO_PT

    def mm_to_pdf_y(y_from_top_mm):
        return (PAGE_H_MM - y_from_top_mm) * MM_TO_PT

    # 1. Draw 4 Fiducial Markers at page corners
    # (Solid square with a concentric white square inside for unambiguous corner detection)
    fiducials_mm = [
        (MARKER_OFFSET_X_MM, MARKER_OFFSET_Y_MM),  # Top-left
        (PAGE_W_MM - MARKER_OFFSET_X_MM - MARKER_SIZE_MM, MARKER_OFFSET_Y_MM),  # Top-right
        (MARKER_OFFSET_X_MM, PAGE_H_MM - MARKER_OFFSET_Y_MM - MARKER_SIZE_MM),  # Bottom-left
        (PAGE_W_MM - MARKER_OFFSET_X_MM - MARKER_SIZE_MM, PAGE_H_MM - MARKER_OFFSET_Y_MM - MARKER_SIZE_MM)  # Bottom-right
    ]

    for fx, fy in fiducials_mm:
        x_pt = mm_to_pdf_x(fx)
        y_pt = mm_to_pdf_y(fy + MARKER_SIZE_MM)
        size_pt = MARKER_SIZE_MM * MM_TO_PT
        # Outer black square
        c.setFillColor(colors.black)
        c.rect(x_pt, y_pt, size_pt, size_pt, fill=1, stroke=0)
        # Inner white square (half size)
        c.setFillColor(colors.white)
        inset = size_pt * 0.25
        c.rect(x_pt + inset, y_pt + inset, size_pt * 0.5, size_pt * 0.5, fill=1, stroke=0)

    # 2. Header and Instructions
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    title = "Bambu Lab A1 - Foglio di Calibrazione Calligrafica"
    c.drawCentredString(page_w_pt / 2.0, mm_to_pdf_y(15.0), title)

    c.setFont("Helvetica", 8)
    sub = "Scrivi ciascun carattere con la tua penna naturale al centro del riquadro, allineandolo alla riga di base."
    c.drawCentredString(page_w_pt / 2.0, mm_to_pdf_y(22.0), sub)

    c.setFont("Helvetica-Oblique", 7.5)
    hint = "Suggerimento: usa penna nera o blu scura a tratto uniforme (gel/roller/biro). Non uscire dalle caselle."
    c.drawCentredString(page_w_pt / 2.0, mm_to_pdf_y(27.0), hint)

    # 3. Draw Grid Cells and Guidelines
    light_cyan = colors.Color(0.75, 0.90, 0.95)
    guideline_color = colors.Color(0.82, 0.85, 0.88)
    label_color = colors.Color(0.4, 0.4, 0.4)

    grid_meta = {
        "page_width_mm": PAGE_W_MM,
        "page_height_mm": PAGE_H_MM,
        "fiducials_mm": [
            {"name": "top_left", "x": fiducials_mm[0][0], "y": fiducials_mm[0][1]},
            {"name": "top_right", "x": fiducials_mm[1][0], "y": fiducials_mm[1][1]},
            {"name": "bottom_left", "x": fiducials_mm[2][0], "y": fiducials_mm[2][1]},
            {"name": "bottom_right", "x": fiducials_mm[3][0], "y": fiducials_mm[3][1]}
        ],
        "grid": {
            "start_x_mm": MARGIN_X_MM,
            "start_y_mm": GRID_START_Y_MM,
            "cell_width_mm": CELL_W_MM,
            "cell_height_mm": CELL_H_MM,
            "rows": GRID_ROWS,
            "cols": GRID_COLS,
            "baseline_from_cell_bottom_mm": BASELINE_MM,
            "x_height_from_cell_bottom_mm": X_HEIGHT_MM,
            "cap_height_from_cell_bottom_mm": CAP_HEIGHT_MM,
            "descender_from_cell_bottom_mm": DESCENDER_MM
        },
        "cells": []
    }

    for row_idx in range(GRID_ROWS):
        for col_idx in range(GRID_COLS):
            char = CHARS_GRID[row_idx][col_idx]
            cell_x_mm = MARGIN_X_MM + col_idx * CELL_W_MM
            cell_y_top_mm = GRID_START_Y_MM + row_idx * CELL_H_MM
            cell_y_bot_mm = cell_y_top_mm + CELL_H_MM

            cell_x_pt = mm_to_pdf_x(cell_x_mm)
            cell_y_pt = mm_to_pdf_y(cell_y_bot_mm)
            cell_w_pt = CELL_W_MM * MM_TO_PT
            cell_h_pt = CELL_H_MM * MM_TO_PT

            # Outer cell border
            c.setStrokeColor(colors.Color(0.70, 0.70, 0.70))
            c.setLineWidth(0.5)
            c.rect(cell_x_pt, cell_y_pt, cell_w_pt, cell_h_pt, fill=0, stroke=1)

            # Guidelines:
            # Baseline (solid light line)
            base_y_pt = cell_y_pt + BASELINE_MM * MM_TO_PT
            c.setStrokeColor(colors.Color(0.45, 0.65, 0.85))
            c.setLineWidth(0.75)
            c.line(cell_x_pt + 1, base_y_pt, cell_x_pt + cell_w_pt - 1, base_y_pt)

            # X-height (dashed line)
            xh_y_pt = cell_y_pt + X_HEIGHT_MM * MM_TO_PT
            c.setStrokeColor(guideline_color)
            c.setLineWidth(0.4)
            c.setDash(1, 2)
            c.line(cell_x_pt + 1, xh_y_pt, cell_x_pt + cell_w_pt - 1, xh_y_pt)

            # Cap height (dashed line)
            cap_y_pt = cell_y_pt + CAP_HEIGHT_MM * MM_TO_PT
            c.line(cell_x_pt + 1, cap_y_pt, cell_x_pt + cell_w_pt - 1, cap_y_pt)

            # Descender (dashed line)
            desc_y_pt = cell_y_pt + DESCENDER_MM * MM_TO_PT
            c.line(cell_x_pt + 1, desc_y_pt, cell_x_pt + cell_w_pt - 1, desc_y_pt)
            c.setDash([])  # reset dash

            # Small reference character label in top-left of cell
            c.setFillColor(label_color)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(cell_x_pt + 1.5 * MM_TO_PT, cell_y_pt + cell_h_pt - 3.5 * MM_TO_PT, char)

            grid_meta["cells"].append({
                "char": char,
                "row": row_idx,
                "col": col_idx,
                "x_mm": round(cell_x_mm, 2),
                "y_top_mm": round(cell_y_top_mm, 2),
                "width_mm": round(CELL_W_MM, 2),
                "height_mm": round(CELL_H_MM, 2),
                "baseline_y_mm": round(cell_y_bot_mm - BASELINE_MM, 2)
            })

    # Footer note
    c.setFillColor(colors.gray)
    c.setFont("Helvetica", 7)
    footer = "Dopo aver compilato il foglio a mano, fotografa o scansiona e lancia: python vectorize_handwriting.py --input scansione.jpg"
    c.drawCentredString(page_w_pt / 2.0, mm_to_pdf_y(PAGE_H_MM - 10.0), footer)

    c.showPage()
    c.save()

    return grid_meta

def generate_png(grid_meta, output_png_path, dpi=200):
    scale = dpi / 25.4  # px per mm
    img_w = int(PAGE_W_MM * scale)
    img_h = int(PAGE_H_MM * scale)

    img = Image.new('RGB', (img_w, img_h), 'white')
    draw = ImageDraw.Draw(img)

    def to_px(x_mm, y_mm):
        return int(round(x_mm * scale)), int(round(y_mm * scale))

    # Fiducials
    m_sz = int(round(MARKER_SIZE_MM * scale))
    for f in grid_meta["fiducials_mm"]:
        x, y = to_px(f["x"], f["y"])
        draw.rectangle([x, y, x + m_sz, y + m_sz], fill='black')
        in_s = int(round(m_sz * 0.25))
        draw.rectangle([x + in_s, y + in_s, x + m_sz - in_s, y + m_sz - in_s], fill='white')

    # Header text
    try:
        font_title = ImageFont.truetype("arial.ttf", int(14 * scale / 2.83))
        font_sub = ImageFont.truetype("arial.ttf", int(8 * scale / 2.83))
        font_cell = ImageFont.truetype("arial.ttf", int(7 * scale / 2.83))
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        font_cell = ImageFont.load_default()

    draw.text((img_w // 2, int(15 * scale)), "Bambu Lab A1 - Foglio di Calibrazione Calligrafica", fill='black', anchor='mt', font=font_title)
    draw.text((img_w // 2, int(22 * scale)), "Scrivi ciascun carattere con la tua penna naturale al centro del riquadro.", fill='#333333', anchor='mt', font=font_sub)

    # Grid cells
    for cell in grid_meta["cells"]:
        x0, y0 = to_px(cell["x_mm"], cell["y_top_mm"])
        x1, y1 = to_px(cell["x_mm"] + cell["width_mm"], cell["y_top_mm"] + cell["height_mm"])

        # Border
        draw.rectangle([x0, y0, x1, y1], outline='#b0b0b0', width=1)

        # Baseline
        base_y = int(round(cell["baseline_y_mm"] * scale))
        draw.line([x0 + 1, base_y, x1 - 1, base_y], fill='#4a90e2', width=1)

        # X-height
        xh_y = int(round((cell["baseline_y_mm"] - (X_HEIGHT_MM - BASELINE_MM)) * scale))
        draw.line([x0 + 1, xh_y, x1 - 1, xh_y], fill='#d0d0d0', width=1)

        # Cap-height
        cap_y = int(round((cell["baseline_y_mm"] - (CAP_HEIGHT_MM - BASELINE_MM)) * scale))
        draw.line([x0 + 1, cap_y, x1 - 1, cap_y], fill='#d0d0d0', width=1)

        # Descender
        desc_y = int(round((cell["baseline_y_mm"] + (BASELINE_MM - DESCENDER_MM)) * scale))
        draw.line([x0 + 1, desc_y, x1 - 1, desc_y], fill='#d0d0d0', width=1)

        # Label
        draw.text((x0 + int(1.5 * scale), y0 + int(1.5 * scale)), cell["char"], fill='#666666', font=font_cell)

    img.save(output_png_path, "PNG")

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(base_dir, 'templates')
    os.makedirs(templates_dir, exist_ok=True)

    pdf_path = os.path.join(templates_dir, 'handwriting_calibration_sheet.pdf')
    png_path = os.path.join(templates_dir, 'handwriting_calibration_sheet.png')
    spec_path = os.path.join(templates_dir, 'calibration_grid_spec.json')

    print(f"Generating PDF: {pdf_path}")
    grid_meta = generate_pdf(pdf_path)

    print(f"Saving spec JSON: {spec_path}")
    with open(spec_path, 'w', encoding='utf-8') as f:
        json.dump(grid_meta, f, indent=2, ensure_ascii=False)

    print(f"Generating reference PNG: {png_path}")
    generate_png(grid_meta, png_path, dpi=200)

    print("Done! Calibration sheets and spec generated successfully.")

if __name__ == '__main__':
    main()
