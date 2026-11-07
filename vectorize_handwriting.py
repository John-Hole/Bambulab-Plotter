#!/usr/bin/env python3
"""
vectorize_handwriting.py - Digitizes user handwriting from a calibration sheet into single-line vector strokes.

Pipeline:
  1. Loads calibration sheet image (scan or smartphone photo).
  2. Detects 4 corner fiducial markers to de-skew and perspective-warp image flat.
  3. Segments each letter cell based on templates/calibration_grid_spec.json.
  4. Filters out cell borders, guidelines, and reference labels.
  5. Computes 1-pixel medial axis skeleton using skimage morphology.
  6. Traces skeleton graph into ordered polylines (natural pen-down / pen-up paths).
  7. Simplifies polylines using Ramer-Douglas-Peucker (cv2.approxPolyDP).
  8. Normalizes coordinates (baseline at Y=0, scaled to font units).
  9. Exports fonts/my_handwriting.json and output/handwriting_extraction_preview.png.
"""

import os
import sys
import json
import math
import argparse
from typing import Dict, List, Tuple, Any, Optional

import cv2
import numpy as np
from skimage.morphology import skeletonize


class CalibrationSheetDetector:
    """Detects corner fiducials and performs perspective rectification."""

    def __init__(self, spec_data: Dict[str, Any]):
        self.spec = spec_data
        self.page_w_mm = float(spec_data["page_width_mm"])
        self.page_h_mm = float(spec_data["page_height_mm"])
        self.fiducials_meta = spec_data["fiducials_mm"]

    def rectify_image(self, img_bgr: np.ndarray, target_dpi: int = 200) -> Tuple[np.ndarray, float]:
        """Detects fiducial markers and warps image into rectified top-down view."""
        h, w = img_bgr.shape[:2]
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        # Binary inversion (markers become white on black)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 8
        )

        contours, hierarchy = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        scale_mm_to_px = target_dpi / 25.4
        target_w = int(round(self.page_w_mm * scale_mm_to_px))
        target_h = int(round(self.page_h_mm * scale_mm_to_px))

        # Check if the photo is in landscape orientation (width > height)
        # If so, rotate 90 degrees counter-clockwise so portrait is standard
        orig_img = img_bgr
        if img_bgr.shape[1] > img_bgr.shape[0] * 1.15:
            # Try rotating to portrait
            img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
            h, w = img_bgr.shape[:2]
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 8
            )
            contours, hierarchy = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        marker_candidates = []
        if hierarchy is not None:
            for i, c in enumerate(contours):
                peri = cv2.arcLength(c, True)
                approx = cv2.approxPolyDP(c, 0.04 * peri, True)
                if len(approx) == 4:
                    x, y, cw, ch = cv2.boundingRect(approx)
                    aspect = float(cw) / max(1, ch)
                    # Marker size roughly between 0.01 and 0.15 of image width
                    if 0.015 * w < cw < 0.15 * w and 0.75 <= aspect <= 1.30:
                        child_idx = hierarchy[0][i][2]
                        if child_idx != -1:  # has inner hole
                            M = cv2.moments(c)
                            if M["m00"] > 0:
                                cx = M["m10"] / M["m00"]
                                cy = M["m01"] / M["m00"]
                                marker_candidates.append((cx, cy))

        # Cluster / deduplicate candidate markers closer than 20 pixels
        unique_cands = []
        for pt in marker_candidates:
            if not any(math.hypot(pt[0] - u[0], pt[1] - u[1]) < 20 for u in unique_cands):
                unique_cands.append(pt)

        # Check if we found at least 4 markers
        if len(unique_cands) >= 4:
            pts = np.array(unique_cands, dtype=np.float32)
            s = pts[:, 0] + pts[:, 1]
            d = pts[:, 0] - pts[:, 1]

            tl_idx = int(np.argmin(s))
            br_idx = int(np.argmax(s))
            tr_idx = int(np.argmax(d))
            bl_idx = int(np.argmin(d))

            corner_indices = [tl_idx, tr_idx, bl_idx, br_idx]
            if len(set(corner_indices)) == 4:
                tl = pts[tl_idx]
                tr = pts[tr_idx]
                bl = pts[bl_idx]
                br = pts[br_idx]
                src_corners = np.array([tl, tr, bl, br], dtype=np.float32)

                # Destination points matching spec mm
                dst_corners = np.array([
                    [self.fiducials_meta[0]["x"] + 4.5, self.fiducials_meta[0]["y"] + 4.5],
                    [self.fiducials_meta[1]["x"] + 4.5, self.fiducials_meta[1]["y"] + 4.5],
                    [self.fiducials_meta[2]["x"] + 4.5, self.fiducials_meta[2]["y"] + 4.5],
                    [self.fiducials_meta[3]["x"] + 4.5, self.fiducials_meta[3]["y"] + 4.5]
                ], dtype=np.float32) * scale_mm_to_px

                matrix = cv2.getPerspectiveTransform(src_corners, dst_corners)
                rectified = cv2.warpPerspective(img_bgr, matrix, (target_w, target_h))

                # Check if upside-down: header has prominent title, footer is sparse
                gray_rect = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
                top_dark = int(np.sum(gray_rect[:int(0.15 * target_h), :] < 120))
                bot_dark = int(np.sum(gray_rect[-int(0.15 * target_h):, :] < 120))
                if bot_dark > top_dark * 1.6 and bot_dark > 2000:
                    rectified = cv2.rotate(rectified, cv2.ROTATE_180)

                print("Successfully rectified image using 4 corner fiducial markers.")
                return rectified, scale_mm_to_px

        print("Fiducials not clearly detected; resizing directly to standard aspect ratio.")
        rectified = cv2.resize(orig_img, (target_w, target_h))
        return rectified, scale_mm_to_px


class SkeletonTracer:
    """Converts 1-pixel skeleton masks into ordered continuous vector strokes."""

    NEIGHBORS = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1)
    ]

    @classmethod
    def crossing_number(cls, s: np.ndarray, r: int, c: int) -> int:
        """Computes the digital crossing number (connectivity number) of pixel (r, c)."""
        h, w = s.shape
        cyclic = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]
        vals = [1 if (0 <= r + dr < h and 0 <= c + dc < w and s[r + dr, c + dc]) else 0 for dr, dc in cyclic]
        vals.append(vals[0])
        return sum(1 for i in range(8) if vals[i] == 0 and vals[i + 1] == 1)

    @classmethod
    def thin_redundant(cls, skel_mask: np.ndarray) -> np.ndarray:
        """Removes redundant 8-connected triangle pixels to expose true endpoints."""
        s = skel_mask.copy()
        h, w = s.shape
        changed = True
        while changed:
            changed = False
            for r, c in list(zip(*np.where(s))):
                nbrs = [
                    (r + dr, c + dc) for dr, dc in cls.NEIGHBORS
                    if 0 <= r + dr < h and 0 <= c + dc < w and s[r + dr, c + dc]
                ]
                if len(nbrs) == 2:
                    p1, p2 = nbrs
                    if max(abs(p1[0] - p2[0]), abs(p1[1] - p2[1])) == 1:
                        s[r, c] = False
                        changed = True
        return s

    @classmethod
    def prune_spurs(cls, skel_mask: np.ndarray, max_len: int = 4) -> np.ndarray:
        """Prunes dead-end micro-spurs <= max_len pixels attached to junctions without destroying main strokes."""
        s = cls.thin_redundant(skel_mask)
        h, w = s.shape
        changed = True
        while changed:
            changed = False
            pixels = list(zip(*np.where(s)))
            eps = [p for p in pixels if cls.crossing_number(s, p[0], p[1]) == 1]
            for ep in eps:
                curr = ep
                prev = None
                path = [curr]
                for _ in range(max_len + 1):
                    nbrs = [
                        (curr[0] + dr, curr[1] + dc) for dr, dc in cls.NEIGHBORS
                        if 0 <= curr[0] + dr < h and 0 <= curr[1] + dc < w and s[curr[0] + dr, curr[1] + dc] and (curr[0] + dr, curr[1] + dc) != prev
                    ]
                    if cls.crossing_number(s, curr[0], curr[1]) >= 3 and curr != ep:
                        break
                    if not nbrs:
                        break
                    if len(nbrs) == 1:
                        nxt = nbrs[0]
                    else:
                        if prev is not None:
                            vx, vy = curr[1] - prev[1], curr[0] - prev[0]
                            v_norm = math.hypot(vx, vy)
                            best_dot, best_cand = -999, nbrs[0]
                            for c_r, c_c in nbrs:
                                cx, cy = c_c - curr[1], c_r - curr[0]
                                c_norm = math.hypot(cx, cy)
                                dot = (vx * cx + vy * cy) / (v_norm * c_norm) if (v_norm * c_norm > 0) else 0
                                if dot > best_dot:
                                    best_dot = dot
                                    best_cand = (c_r, c_c)
                            nxt = best_cand
                        else:
                            nxt = nbrs[0]
                    prev = curr
                    curr = nxt
                    path.append(curr)

                if cls.crossing_number(s, curr[0], curr[1]) >= 3 and curr != ep and len(path) <= max_len + 1:
                    total_b = cls.crossing_number(s, curr[0], curr[1])
                    if total_b > 2:
                        for p in path[:-1]:
                            s[p[0], p[1]] = False
                        changed = True
                        break
        return s

    @classmethod
    def trace(cls, skel_mask: np.ndarray, rdp_epsilon: float = 0.8) -> List[List[Tuple[float, float]]]:
        """Traces skeleton pixels into ordered polylines with robust junction continuation."""
        if not np.any(skel_mask):
            return []

        skel = cls.prune_spurs(skel_mask, max_len=6)
        h, w = skel.shape
        visited = np.zeros_like(skel, dtype=bool)

        def trace_from(start_pt: Tuple[int, int]) -> List[Tuple[float, float]]:
            stroke = [start_pt]
            visited[start_pt[0], start_pt[1]] = True
            curr_r, curr_c = start_pt
            while True:
                cand = [
                    (curr_r + dr, curr_c + dc) for dr, dc in cls.NEIGHBORS
                    if 0 <= curr_r + dr < h and 0 <= curr_c + dc < w and skel[curr_r + dr, curr_c + dc] and not visited[curr_r + dr, curr_c + dc]
                ]
                if not cand:
                    # 1-hop and 2-hop continuation across visited crossings
                    k = min(15, len(stroke))
                    prev_r, prev_c = stroke[-k]
                    vx, vy = curr_c - prev_c, curr_r - prev_r
                    v_norm = math.hypot(vx, vy)
                    best_dot = 0.2
                    best_step = None
                    for dr, dc in cls.NEIGHBORS:
                        jr, jc = curr_r + dr, curr_c + dc
                        if not (0 <= jr < h and 0 <= jc < w and skel[jr, jc]):
                            continue
                        for jdr, jdc in cls.NEIGHBORS:
                            ur, uc = jr + jdr, jc + jdc
                            if 0 <= ur < h and 0 <= uc < w and skel[ur, uc] and not visited[ur, uc]:
                                cx, cy = uc - curr_c, ur - curr_r
                                c_norm = math.hypot(cx, cy)
                                if c_norm > 0 and v_norm > 0:
                                    dot = (vx * cx + vy * cy) / (v_norm * c_norm)
                                    if dot > best_dot:
                                        best_dot = dot
                                        best_step = (ur, uc)
                    if best_step is not None:
                        visited[best_step[0], best_step[1]] = True
                        curr_r, curr_c = best_step
                        stroke.append((curr_r, curr_c))
                        continue
                    break

                if len(cand) == 1:
                    next_pt = cand[0]
                else:
                    k = min(15, len(stroke))
                    prev_r, prev_c = stroke[-k]
                    vx, vy = curr_c - prev_c, curr_r - prev_r
                    v_norm = math.hypot(vx, vy)
                    best_dot, best_cand = -999, cand[0]
                    for c_r, c_c in cand:
                        cx, cy = c_c - curr_c, c_r - curr_r
                        c_norm = math.hypot(cx, cy)
                        dot = (vx * cx + vy * cy) / (v_norm * c_norm) if (v_norm * c_norm > 0) else 0
                        if dot > best_dot:
                            best_dot = dot
                            best_cand = (c_r, c_c)
                    next_pt = best_cand

                visited[next_pt[0], next_pt[1]] = True
                curr_r, curr_c = next_pt
                stroke.append((curr_r, curr_c))

            return [(float(p[1]), float(p[0])) for p in stroke]

        pixels = list(zip(*np.where(skel)))
        eps = [p for p in pixels if cls.crossing_number(skel, p[0], p[1]) == 1]
        eps.sort(key=lambda p: (p[1], -p[0]))

        strokes = []
        for ep in eps:
            if not visited[ep[0], ep[1]]:
                strokes.append(trace_from(ep))

        while np.any(skel & (~visited)):
            unvisited = list(zip(*np.where(skel & (~visited))))
            if strokes:
                last_c, last_r = strokes[-1][-1]
                unvisited.sort(key=lambda p: math.hypot(p[0] - last_r, p[1] - last_c))
            else:
                unvisited.sort(key=lambda p: (p[1], -p[0]))
            strokes.append(trace_from(unvisited[0]))

        # Filter out remnant 1-pixel spurs at junctions
        valid_strokes = []
        for s in strokes:
            if len(s) == 1 and cls.crossing_number(skel, int(round(s[0][1])), int(round(s[0][0]))) >= 3:
                continue
            valid_strokes.append(s)

        # Simplify polylines using RDP (preserving single-point dots)
        simplified_strokes = []
        for s in valid_strokes:
            if len(s) == 1:
                simplified_strokes.append([(float(s[0][0]), float(s[0][1]))])
            elif len(s) >= 2:
                pts_arr = np.array([[[p[0], p[1]]] for p in s], dtype=np.float32)
                simplified = cv2.approxPolyDP(pts_arr, rdp_epsilon, False)
                simp_list = [(float(pt[0][0]), float(pt[0][1])) for pt in simplified]
                if simp_list:
                    simplified_strokes.append(simp_list)

        return simplified_strokes


class HandwritingVectorizer:
    """Processes sheet cells into clean font glyphs."""

    def __init__(self, spec_path: str):
        with open(spec_path, 'r', encoding='utf-8') as f:
            self.spec = json.load(f)

    def extract_font(
        self,
        image_path: str,
        output_font_path: str,
        preview_path: Optional[str] = None
    ) -> Dict[str, Any]:
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Input image not found: {image_path}")

        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Could not read image file: {image_path}")

        detector = CalibrationSheetDetector(self.spec)
        rectified, scale = detector.rectify_image(img, target_dpi=200)

        preview_img = rectified.copy() if preview_path else None

        characters = {}
        extracted_count = 0

        # Reference font metrics
        # Baseline = 10mm from cell bottom
        # Cap height = 13mm (23 - 10)
        # We normalize cap height to 21 units
        NORM_CAP_HEIGHT = 21.0
        scale_to_font = NORM_CAP_HEIGHT / (13.0 * scale)

        for cell in self.spec["cells"]:
            char = cell["char"]
            x_px = int(round(cell["x_mm"] * scale))
            y_px = int(round(cell["y_top_mm"] * scale))
            w_px = int(round(cell["width_mm"] * scale))
            h_px = int(round(cell["height_mm"] * scale))

            # Crop cell with small margin
            pad = 2
            roi_y0 = max(0, y_px + pad)
            roi_y1 = min(rectified.shape[0], y_px + h_px - pad)
            roi_x0 = max(0, x_px + pad)
            roi_x1 = min(rectified.shape[1], x_px + w_px - pad)
            cell_roi = rectified[roi_y0:roi_y1, roi_x0:roi_x1]

            if cell_roi.size == 0:
                continue

            # Cell baseline Y relative to ROI top
            baseline_y_roi = (cell["baseline_y_mm"] - cell["y_top_mm"]) * scale - pad

            # 1. Mask out reference label at top-left
            clean_roi = cell_roi.copy()
            label_mask_w = int(round(cell_roi.shape[1] * 0.35))
            label_mask_h = int(round(cell_roi.shape[0] * 0.22))
            clean_roi[0:label_mask_h, 0:label_mask_w] = (255, 255, 255)

            # 2. Extract ink stroke with adaptive contrast thresholding:
            gray_cell = cv2.cvtColor(clean_roi, cv2.COLOR_BGR2GRAY)
            bg_gray = float(np.percentile(gray_cell, 85))
            min_gray = float(np.min(gray_cell))
            contrast = bg_gray - min_gray

            # Check if cell has distinct dark ink markings
            if contrast < 35:
                continue

            thresh_val = bg_gray - max(25.0, contrast * 0.42)
            _, bin_mask = cv2.threshold(gray_cell, thresh_val, 255, cv2.THRESH_BINARY_INV)

            # Clear 2px border to discard any cell boundary line artifacts
            bin_mask[:2, :] = 0
            bin_mask[-2:, :] = 0
            bin_mask[:, :2] = 0
            bin_mask[:, -2:] = 0

            # Check if cell actually contains ink
            ink_pixel_count = int(np.sum(bin_mask > 0))
            if ink_pixel_count < 15:
                # Cell is empty
                continue

            # 3. Skeletonize
            bool_mask = (bin_mask > 0)
            skel = skeletonize(bool_mask)

            # 4. Trace strokes
            roi_strokes = SkeletonTracer.trace(skel, rdp_epsilon=0.9)
            if not roi_strokes:
                continue

            # 5. Normalize strokes into font coordinate space
            # Find min_x across all strokes in this glyph
            all_xs = [pt[0] for s in roi_strokes for pt in s]
            all_ys = [pt[1] for s in roi_strokes for pt in s]
            min_x = min(all_xs)
            max_x = max(all_xs)

            norm_strokes = []
            for s in roi_strokes:
                norm_s = []
                for (px, py) in s:
                    # In font space:
                    # x starts at 0 (with slight left margin 2.0 units)
                    # y is inverted so baseline is y=0, higher y is above baseline
                    fx = round((px - min_x) * scale_to_font + 2.0, 3)
                    fy = round(-(py - baseline_y_roi) * scale_to_font, 3)
                    norm_s.append([fx, fy])
                norm_strokes.append(norm_s)

            adv_width = round((max_x - min_x) * scale_to_font + 5.0, 3)
            characters[char] = {
                "advance_width": max(8.0, adv_width),
                "strokes": norm_strokes
            }
            extracted_count += 1

            # Draw extracted vector paths in bright green on preview image
            if preview_img is not None:
                for s in roi_strokes:
                    if len(s) == 1:
                        p1 = (int(round(roi_x0 + s[0][0])), int(round(roi_y0 + s[0][1])))
                        cv2.circle(preview_img, p1, 2, (0, 220, 0), -1)
                    else:
                        for i in range(len(s) - 1):
                            p1 = (int(round(roi_x0 + s[i][0])), int(round(roi_y0 + s[i][1])))
                            p2 = (int(round(roi_x0 + s[i+1][0])), int(round(roi_y0 + s[i+1][1])))
                            cv2.line(preview_img, p1, p2, (0, 220, 0), 2)
                            cv2.circle(preview_img, p1, 2, (0, 0, 255), -1)

        # Ensure space is defined
        if ' ' not in characters:
            characters[' '] = {"advance_width": 12.0, "strokes": []}

        font_dict = {
            "name": "Personal Handwritten Single-Line Font",
            "source_image": os.path.basename(image_path),
            "units_per_em": 32,
            "cap_height": NORM_CAP_HEIGHT,
            "x_height": 10.0,
            "descender": -10.0,
            "character_count": len(characters),
            "characters": characters
        }

        os.makedirs(os.path.dirname(os.path.abspath(output_font_path)), exist_ok=True)
        with open(output_font_path, 'w', encoding='utf-8') as f:
            json.dump(font_dict, f, indent=2, ensure_ascii=False)

        print(f"Extracted {extracted_count} characters into: {output_font_path}")

        if preview_img is not None and preview_path:
            os.makedirs(os.path.dirname(os.path.abspath(preview_path)), exist_ok=True)
            cv2.imwrite(preview_path, preview_img)
            print(f"Extraction verification preview saved: {preview_path}")

        return font_dict


def main():
    parser = argparse.ArgumentParser(
        description="Vectorize user handwriting from calibration sheet into single-line stroke font."
    )
    parser.add_argument("--input", "-i", required=True, help="Path to scanned or photographed calibration sheet (.png, .jpg)")
    parser.add_argument("--spec", "-s", help="Path to calibration_grid_spec.json (defaults to templates/calibration_grid_spec.json)")
    parser.add_argument("--output", "-o", default="fonts/my_handwriting.json", help="Output font JSON path")
    parser.add_argument("--preview", "-p", default="output/handwriting_extraction_preview.png", help="Extraction verification preview image")

    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    spec_path = args.spec or os.path.join(base_dir, 'templates', 'calibration_grid_spec.json')

    if not os.path.exists(spec_path):
        print(f"Error: Specification file not found: {spec_path}")
        print("Please run generate_calibration_sheet.py first.")
        sys.exit(1)

    out_font = os.path.abspath(args.output) if os.path.isabs(args.output) else os.path.join(base_dir, args.output)
    out_prev = os.path.abspath(args.preview) if os.path.isabs(args.preview) else os.path.join(base_dir, args.preview)

    vectorizer = HandwritingVectorizer(spec_path)
    vectorizer.extract_font(args.input, out_font, out_prev)


if __name__ == '__main__':
    main()
