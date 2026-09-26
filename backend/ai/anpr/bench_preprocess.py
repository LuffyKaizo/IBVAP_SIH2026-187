"""Preprocessing variant benchmark for EasyOCR (real inference).

Compares multiple plate-crop preprocessing pipelines on the labeled
synthetic test images and reports exact-match / char-accuracy / latency
per variant. Evidence-based selection only; no fabricated results.

Usage: python -m ai.anpr.bench_preprocess
"""
import sys, os, time, re, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import cv2
import numpy as np
import easyocr


def norm(text):
    if not text:
        return None
    n = re.sub(r'[^A-Z0-9]', '', text.strip().upper())
    return n if len(n) >= 2 else None


def lcs_sim(a, b):
    if not a or not b:
        return 0.0
    m, n = len(a), len(b)
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(1, m+1):
        for j in range(1, n+1):
            dp[i][j] = dp[i-1][j-1] + 1 if a[i-1] == b[j-1] else max(dp[i-1][j], dp[i][j-1])
    return dp[m][n] / len(b)


def expected_of(fname):
    m = re.search(r'plate_([A-Z0-9]+)\.', fname)
    return m.group(1) if m else None


def v_original(bgr): return bgr

def v_gray_color(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)

def v_upscale_only(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = g.shape[:2]
    if h < 120:
        g = cv2.resize(g, (int(w*3), int(h*3)), interpolation=cv2.INTER_CUBIC)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)

def v_upscale3_gray_clahe(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = g.shape[:2]
    if h < 120:
        g = cv2.resize(g, (int(w*3), int(h*3)), interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    g = clahe.apply(g)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)

def v_clahe(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    g = clahe.apply(g)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)

def v_adaptive_thresh(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    b = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    return cv2.cvtColor(b, cv2.COLOR_GRAY2BGR)

def v_otsu(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(b, cv2.COLOR_GRAY2BGR)

def v_contrast_norm(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    g = cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)

VARIANTS = {
    'original': v_original,
    'gray': v_gray_color,
    'upscale3x': v_upscale_only,
    'upscale3x+clahe': v_upscale3_gray_clahe,
    'clahe': v_clahe,
    'adaptive': v_adaptive_thresh,
    'otsu': v_otsu,
    'contrast_norm': v_contrast_norm,
}


def main():
    print("=" * 78)
    print("PREPROCESSING VARIANT BENCHMARK (real EasyOCR inference)")
    print("=" * 78)
    data_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'anpr_test'))
    files = sorted([f for f in os.listdir(data_dir) if f.startswith('plate_') and f.endswith('.jpg')])
    files = [f for f in files if expected_of(f)]

    t0 = time.time()
    reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    print(f"\nEasyOCR init: {(time.time()-t0)*1000:.0f} ms | {len(files)} labeled images | {len(VARIANTS)} variants\n")

    results = {}
    detail = {}
    for vname, fn in VARIANTS.items():
        exact, total, ch_match, ch_total = 0, 0, 0, 0
        confs, lats = [], []
        rows = []
        for fname in files:
            exp = expected_of(fname)
            bgr = cv2.imread(os.path.join(data_dir, fname))
            if bgr is None:
                continue
            img = fn(bgr)
            t1 = time.time()
            res = reader.readtext(img)
            lat = (time.time()-t1)*1000
            lats.append(lat)
            texts = [t for (_, t, c) in res if c > 0.1 and t.strip()]
            raw = ' '.join(texts) if texts else None
            n = norm(raw)
            conf = statistics.mean([c for (_, _, c) in res]) if res else 0.0
            confs.append(conf)
            total += 1
            if n == exp:
                exact += 1
            if n:
                sim = lcs_sim(n, exp)
                ch_match += int(round(sim * len(exp)))
                ch_total += len(exp)
            rows.append((fname, exp, n, conf, lat))
        results[vname] = dict(exact=exact, total=total, chm=ch_match, cht=ch_total,
                              conf=statistics.mean(confs) if confs else 0,
                              lat=statistics.mean(lats) if lats else 0)
        detail[vname] = rows
        print(f"[{vname:>14}] exact {exact}/{total} | char {ch_match}/{ch_total} "
              f"({100*ch_match/ch_total:.0f}%) | conf {results[vname]['conf']:.2f} | avg {results[vname]['lat']:.0f}ms")

    print("\n" + "-" * 78)
    print("Detail (expected -> recognized per image):")
    for vname in VARIANTS:
        parts = []
        for (fname, exp, n, conf, lat) in detail[vname]:
            mark = '=' if n == exp else ('~' if n else 'x')
            parts.append(f"{mark} {exp}->{n}")
        print(f"  {vname:>14}: " + " | ".join(parts))

    print("\n" + "=" * 78)
    best = max(results, key=lambda k: (results[k]['exact'], results[k]['chm'], -results[k]['lat']))
    print(f"BEST VARIANT by exact match: {best}  ({results[best]['exact']}/{results[best]['total']} exact, "
          f"char {results[best]['chm']}/{results[best]['cht']})")
    print("=" * 78)


if __name__ == '__main__':
    main()
