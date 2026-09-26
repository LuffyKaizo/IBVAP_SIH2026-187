"""Real EasyOCR Validation Test.

Runs actual EasyOCR inference on synthetic ANPR test images and reports
structured results. Does NOT fabricate any OCR output.

Usage:
    cd netraksh-tactical-intelligence-sih
    python -m ai.anpr.test_easyocr_real
"""

import sys
import os
import time
import re
import statistics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import easyocr
import cv2
import numpy as np


def normalize_plate_text(text: str):
    """Conservative normalization: uppercase, strip whitespace/separators, keep alphanumeric."""
    if not text:
        return None
    normalized = text.strip().upper()
    normalized = re.sub(r'[\s\-_.]', '', normalized)
    normalized = re.sub(r'[^A-Z0-9]', '', normalized)
    if len(normalized) < 2:
        return None
    return normalized


def extract_expected_plate(filename: str):
    """Extract expected plate text from filename patterns like 'plate_MH12AB1234.jpg' or 'vehicle_MH12AB1234.jpg'."""
    match = re.search(r'(?:plate|vehicle|processed)_([A-Z0-9]+)\.', filename, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def char_accuracy(pred: str, expected: str) -> float:
    """Character-level similarity using longest common subsequence ratio."""
    if not expected:
        return 0.0
    if not pred:
        return 0.0
    m, n = len(pred), len(expected)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if pred[i - 1] == expected[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs_len = dp[m][n]
    return lcs_len / max(len(expected), 1)


def main():
    print("=" * 70)
    print("REAL EasyOCR VALIDATION TEST")
    print("=" * 70)

    # --- Step 1: Initialize EasyOCR ---
    print("\n[1] Initializing EasyOCR (CPU mode)...")
    init_start = time.time()
    try:
        reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        init_time = (time.time() - init_start) * 1000
        print(f"    EasyOCR initialized in {init_time:.0f} ms")
    except Exception as e:
        print(f"    FAILED to initialize EasyOCR: {e}")
        sys.exit(1)

    # --- Step 2: Discover test images ---
    data_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'anpr_test')
    data_dir = os.path.normpath(data_dir)

    if not os.path.isdir(data_dir):
        print(f"\n    ERROR: Test data directory not found: {data_dir}")
        sys.exit(1)

    # Only test plate_*.jpg images (contain actual plate crops)
    plate_images = sorted([
        f for f in os.listdir(data_dir)
        if f.startswith('plate_') and f.endswith('.jpg')
    ])

    # Also test clean_plate.jpg (no expected value from filename)
    if os.path.exists(os.path.join(data_dir, 'clean_plate.jpg')):
        plate_images.append('clean_plate.jpg')

    print(f"\n[2] Found {len(plate_images)} plate test images in {data_dir}")

    # --- Step 3: Run EasyOCR on each image ---
    print("\n[3] Running EasyOCR inference...\n")

    results = []
    latencies = []
    successes = 0
    exact_matches = 0
    total_chars = 0
    matched_chars = 0

    for fname in plate_images:
        fpath = os.path.join(data_dir, fname)
        expected = extract_expected_plate(fname)

        img = cv2.imread(fpath)
        if img is None:
            results.append({
                'filename': fname,
                'expected': expected,
                'raw_text': None,
                'normalized': None,
                'confidence': 0.0,
                'latency_ms': 0.0,
                'status': 'FAILED_TO_LOAD',
            })
            continue

        # Run EasyOCR
        t0 = time.time()
        ocr_results = reader.readtext(img)
        latency_ms = (time.time() - t0) * 1000
        latencies.append(latency_ms)

        # Extract raw text and confidence
        texts = []
        confidences = []
        for (bbox, text, conf) in ocr_results:
            if conf > 0.1 and text.strip():
                texts.append(text.strip())
                confidences.append(conf)

        raw_text = ' '.join(texts) if texts else None
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        normalized = normalize_plate_text(raw_text) if raw_text else None

        # Determine status
        status = 'NO_TEXT'
        if normalized:
            status = 'RECOGNIZED'
            successes += 1

        # Compare with expected (if available)
        is_exact = False
        char_sim = 0.0
        if expected and normalized:
            is_exact = (normalized == expected)
            char_sim = char_accuracy(normalized, expected)
            if is_exact:
                exact_matches += 1
            total_chars += len(expected)
            matched_chars += int(char_sim * len(expected))

        results.append({
            'filename': fname,
            'expected': expected,
            'raw_text': raw_text,
            'normalized': normalized,
            'confidence': round(avg_conf, 4),
            'latency_ms': round(latency_ms, 1),
            'status': status,
            'exact_match': is_exact,
            'char_similarity': round(char_sim, 4),
        })

    # --- Step 4: Print structured results ---
    print("-" * 70)
    print(f"{'FILENAME':<30} {'EXPECTED':<14} {'RAW TEXT':<20} {'NORMALIZED':<14} {'CONF':>6} {'LATENCY':>8} {'STATUS'}")
    print("-" * 70)

    for r in results:
        print(f"{r['filename']:<30} {str(r.get('expected') or '-'):<14} {str(r.get('raw_text') or '-'):<20} {str(r.get('normalized') or '-'):<14} {r['confidence']:>6.2f} {r['latency_ms']:>7.1f}ms {r['status']}")

    print("-" * 70)

    # --- Step 5: Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Images tested:          {len(results)}")
    print(f"  Successfully recognized: {successes}/{len(results)}")
    print(f"  Exact matches:          {exact_matches}/{len([r for r in results if r.get('expected')])}")
    if total_chars > 0:
        print(f"  Character accuracy:     {matched_chars}/{total_chars} ({100*matched_chars/total_chars:.1f}%)")
    else:
        print(f"  Character accuracy:     N/A (no expected values)")

    if latencies:
        print(f"\n  OCR Latency:")
        print(f"    Average:  {statistics.mean(latencies):.1f} ms")
        print(f"    Median:   {statistics.median(latencies):.1f} ms")
        print(f"    Min:      {min(latencies):.1f} ms")
        print(f"    Max:      {max(latencies):.1f} ms")
        if len(latencies) >= 5:
            sorted_lat = sorted(latencies)
            p95_idx = int(len(sorted_lat) * 0.95)
            print(f"    P95:      {sorted_lat[min(p95_idx, len(sorted_lat)-1)]:.1f} ms")
        print(f"    Total calls: {len(latencies)}")

    # --- Step 6: Verdict ---
    print("\n" + "=" * 70)
    has_expected = [r for r in results if r.get('expected')]
    if has_expected:
        match_rate = exact_matches / len(has_expected)
        if match_rate >= 0.6:
            print("  VERDICT: PASS — EasyOCR can recognize plates from test images")
        elif match_rate >= 0.2:
            print("  VERDICT: PARTIAL — EasyOCR recognizes some plates but not all")
        else:
            print("  VERDICT: FAIL — EasyOCR could not reliably recognize plates")
        print(f"  Match rate: {match_rate*100:.0f}% ({exact_matches}/{len(has_expected)})")
    else:
        print("  VERDICT: NO EXPECTED VALUES — cannot determine accuracy")
    print("=" * 70)

    # Return exit code
    if has_expected and exact_matches == 0 and successes == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
