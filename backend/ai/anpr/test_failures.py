"""Failure and edge case tests for ANPR pipeline.

Tests that the system handles error conditions gracefully without
crashing, fabricating results, or leaving stale state.
"""

import sys
import os
import time
import json
import numpy as np
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from ai.anpr.plate_detector import PlateDetector, PlateCandidate
from ai.anpr.ocr_engine import OCREngine
from ai.anpr.temporal import TemporalStabilizer
from ai.anpr.plate_format import contextual_correct

passed = 0
failed = 0

def check(name, condition, detail=''):
    global passed, failed
    if condition:
        passed += 1
        print('  PASS:', name)
    else:
        failed += 1
        print('  FAIL:', name, detail)

print()
print('=== FAILURE / EDGE CASE TESTS ===')

# Initialize
detector = PlateDetector()
ocr = OCREngine()
ocr.initialize()
temporal = TemporalStabilizer()

# --- TEST 1: Missing image ---
print()
print('--- TEST 1: Missing image file ---')
try:
    import cv2
    img = cv2.imread('nonexistent_file.jpg')
    text, conf = ocr.read_text(img)
    check('missing image returns (None, 0)', text is None and conf == 0.0)
except Exception as e:
    check('missing image no crash', False, str(e))

# --- TEST 2: Unreadable image (noise) ---
print()
print('--- TEST 2: Unreadable noise image ---')
try:
    noise = np.random.randint(0, 256, (100, 300, 3), dtype=np.uint8)
    text, conf = ocr.read_text(noise)
    check('noise image returns (None, 0) or low conf', text is None or conf < 0.5)
except Exception as e:
    check('noise image no crash', False, str(e))

# --- TEST 3: No plate candidate ---
print()
print('--- TEST 3: No plate candidate in plain image ---')
try:
    plain = np.ones((300, 400, 3), dtype=np.uint8) * 128
    candidates = detector.detect_plates(plain)
    check('no candidates in plain image', len(candidates) == 0)
except Exception as e:
    check('no candidates no crash', False, str(e))

# --- TEST 4: Low OCR confidence ---
print()
print('--- TEST 4: Low OCR confidence handling ---')
try:
    stab = TemporalStabilizer()
    result = stab.add_observation('CAM-01', 42, 'car',
        {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
        'X', 0.1, 0.3, 0)  # Very low OCR confidence, single char
    check('low confidence: no plateText', result['plateText'] is None)
    check('low confidence: status DETECTED', result['status'] == 'DETECTED')
except Exception as e:
    check('low confidence no crash', False, str(e))

# --- TEST 5: OCR returns empty text ---
print()
print('--- TEST 5: OCR returns empty text ---')
try:
    stab = TemporalStabilizer()
    result = stab.add_observation('CAM-01', 43, 'car',
        {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
        '', 0.0, 0.5, 0)
    check('empty text: plateText is None', result['plateText'] is None)
    check('empty text: status DETECTED', result['status'] == 'DETECTED')
except Exception as e:
    check('empty text no crash', False, str(e))

# --- TEST 6: Malformed OCR output ---
print()
print('--- TEST 6: Malformed OCR output ---')
try:
    stab = TemporalStabilizer()
    # Various malformed inputs
    for text in [None, '', '!!!', '   ', '@#$%', 'A', '  AB  ']:
        result = stab.add_observation('CAM-01', 44, 'car',
            {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
            text, 0.5, 0.5, 0)
    check('malformed outputs no crash', True)
    # The '  AB  ' should normalize to 'AB'
    stab2 = TemporalStabilizer()
    result = stab2.add_observation('CAM-01', 44, 'car',
        {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
        '  AB  ', 0.9, 0.8, 0)
    check('whitespace normalized', result['plateText'] == 'AB')
    # Verify non-normalizable text is rejected
    stab3 = TemporalStabilizer()
    result3 = stab3.add_observation('CAM-01', 45, 'car',
        {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
        '@#$%', 0.9, 0.8, 0)
    check('non-alphanumeric rejected', result3['plateText'] is None)
except Exception as e:
    check('malformed no crash', False, str(e))

# --- TEST 7: Expired track ---
print()
print('--- TEST 7: Expired track cleanup ---')
try:
    stab = TemporalStabilizer()
    stab.add_observation('CAM-01', 50, 'car',
        {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
        'TEST123', 0.9, 0.8, 0)
    stab.add_observation('CAM-01', 51, 'car',
        {'x1': 0.1, 'y1': 0.2, 'x2': 0.5, 'y2': 0.7},
        'TEST456', 0.9, 0.8, 0)
    check('2 tracks active', len(stab.get_active_results()) == 2)
    
    # Track 50 disappears, track 51 stays
    stab.cleanup_stale({51}, 'CAM-01')
    results = stab.get_active_results()
    check('expired track removed', len(results) == 1)
    check('remaining track has correct plate', results[0]['plateText'] == 'TEST456')
except Exception as e:
    check('expired track no crash', False, str(e))

# --- TEST 8: Pipeline restart (resolve_all) ---
print()
print('--- TEST 8: Pipeline restart ---')
try:
    stab = TemporalStabilizer()
    for i in range(5):
        stab.add_observation('CAM-01', 60, 'car',
            {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
            'PLATE123', 0.9, 0.8, i)
    check('before restart: has results', len(stab.get_active_results()) > 0)
    
    stab.resolve_all()
    check('after restart: no results', len(stab.get_active_results()) == 0)
    
    # Can add new observations after restart
    result = stab.add_observation('CAM-01', 70, 'car',
        {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
        'NEWPLATE', 0.9, 0.8, 0)
    check('after restart: new observation works', result['plateText'] == 'NEWPLATE')
except Exception as e:
    check('pipeline restart no crash', False, str(e))

# --- TEST 9: OCR engine not initialized ---
print()
print('--- TEST 9: OCR engine not initialized ---')
try:
    fresh_ocr = OCREngine()
    # Don't call initialize()
    text, conf = fresh_ocr.read_text(np.ones((50, 150, 3), dtype=np.uint8) * 255)
    check('uninitialized OCR returns (None, 0)', text is None and conf == 0.0)
except Exception as e:
    check('uninitialized OCR no crash', False, str(e))

# --- TEST 10: JSON serialization of ANPR results ---
print()
print('--- TEST 10: JSON serialization ---')
try:
    stab = TemporalStabilizer()
    stab.add_observation('CAM-01', 80, 'car',
        {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
        'JSON1234', 0.9, 0.85, 0)
    results = stab.get_active_results()
    serialized = json.dumps(results)
    deserialized = json.loads(serialized)
    check('JSON round-trip works', len(deserialized) == 1)
    check('plateText preserved', deserialized[0]['plateText'] == 'JSON1234')
    check('source is AI', deserialized[0]['source'] == 'AI')
except Exception as e:
    check('JSON serialization no crash', False, str(e))

# --- TEST 11: Very large plate text ---
print()
print('--- TEST 11: Large OCR output ---')
try:
    stab = TemporalStabilizer()
    long_text = 'A' * 100
    result = stab.add_observation('CAM-01', 90, 'car',
        {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
        long_text, 0.9, 0.8, 0)
    check('large text handled', result is not None)
    check('large text stored', result['plateText'] is not None)
except Exception as e:
    check('large text no crash', False, str(e))

# --- TEST 12: Concurrent tracks with same plate ---
print()
print('--- TEST 12: Same plate on different tracks ---')
try:
    stab = TemporalStabilizer()
    stab.add_observation('CAM-01', 100, 'car',
        {'x1': 0.1, 'y1': 0.2, 'x2': 0.3, 'y2': 0.4},
        'SAME1234', 0.9, 0.8, 0)
    stab.add_observation('CAM-01', 101, 'car',
        {'x1': 0.7, 'y1': 0.2, 'x2': 0.9, 'y2': 0.4},
        'SAME1234', 0.9, 0.8, 0)
    results = stab.get_active_results()
    check('2 tracks with same plate tracked independently', len(results) == 2)
    plates = [r['plateText'] for r in results]
    check('both have correct plate', all(p == 'SAME1234' for p in plates))
except Exception as e:
    check('same plate different tracks no crash', False, str(e))

# --- TEST 13: Blurred plate ---
print()
print('--- TEST 13: Blurred plate ---')
try:
    data_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'anpr_test'))
    img = cv2.imread(os.path.join(data_dir, 'plate_MH12AB1234.jpg'))
    blurred = cv2.GaussianBlur(img, (31, 31), 9)
    text, conf = ocr.read_text(detector.preprocess_for_ocr(blurred))
    check('blurred plate no crash', True)
    check('blurred plate low confidence or no text', text is None or conf < 0.9,
          'got %r conf=%.2f' % (text, conf))
except Exception as e:
    check('blurred plate no crash', False, str(e))

# --- TEST 14: Rotated plate ---
print()
print('--- TEST 14: Rotated plate ---')
try:
    img = cv2.imread(os.path.join(data_dir, 'plate_MH12AB1234.jpg'))
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), 25, 1.0)
    rotated = cv2.warpAffine(img, M, (w, h))
    text, conf = ocr.read_text(detector.preprocess_for_ocr(rotated))
    check('rotated plate no crash', True)
    # Rotation must not silently turn into a confident clean reading.
    if text:
        corr = contextual_correct(text, conf)
        check('rotated garbage not auto-confirmed as clean plate',
              not (corr['changed'] and corr['corrected'] == 'MH12AB1234'),
              'text=%r' % text)
except Exception as e:
    check('rotated plate no crash', False, str(e))

# --- TEST 15: No plate region / partial ---
print()
print('--- TEST 15: No plate region ---')
try:
    plain = np.ones((300, 400, 3), dtype=np.uint8) * 128
    text, conf = ocr.read_text(plain)
    check('plain region -> no confident plate', text is None or conf < 0.5,
          'got %r conf=%.2f' % (text, conf))
except Exception as e:
    check('plain region no crash', False, str(e))

# --- TEST 16: Invalid-format OCR text not fabricated into plate ---
print()
print('--- TEST 16: Invalid format never forced to valid ---')
try:
    stab = TemporalStabilizer()
    result = None
    for i in range(5):
        result = stab.add_observation('CAM-01', 120, 'car',
            {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
            'HELLOWORLD', 0.95, 0.8, i)
    check('invalid format stored without fabrication',
          result['plateText'] == 'HELLOWORLD')
    check('invalid format flagged (not VALID)',
          result['formatStatus'] != 'VALID', 'got %s' % result['formatStatus'])
    check('invalid format not marked corrected', result['corrected'] is False)
except Exception as e:
    check('invalid format no crash', False, str(e))

# --- TEST 17: Ambiguous multi-candidate alternation ---
print()
print('--- TEST 17: Ambiguous multi-candidate ---')
try:
    stab = TemporalStabilizer()
    # Two plausible readings alternate each frame.
    result = None
    cands_a = [{'raw': 'MH1ZAB1234', 'normalized': 'MH1ZAB1234', 'confidence': 0.9, 'variant': 'p1'}]
    cands_b = [{'raw': 'MH12AB1234', 'normalized': 'MH12AB1234', 'confidence': 0.9, 'variant': 'p1'}]
    for i in range(4):
        c = cands_a if i % 2 == 0 else cands_b
        result = stab.add_observation('CAM-01', 121, 'car',
            {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
            c[0]['normalized'], c[0]['confidence'], 0.8, i, candidates=c)
    check('ambiguous case resolves deterministically', result is not None)
    # Winner is one of the observed readings or its safe correction;
    # both readings here correct to the same MH12AB1234.
    check('final is consistent reading',
          result['plateText'] in ('MH1ZAB1234', 'MH12AB1234'))
except Exception as e:
    check('ambiguous multi-candidate no crash', False, str(e))

# --- TEST 18: OCR engine unavailable ---
print()
print('--- TEST 18: OCR engine unavailable ---')
try:
    class NoEngine(OCREngine):
        def initialize(self):
            self._initialized = True
            self._engine = None
            return False
    ne = NoEngine()
    text, conf = ne.read_text(np.ones((50, 150, 3), dtype=np.uint8) * 255)
    check('no-engine read_text returns (None, 0)', text is None and conf == 0.0)
    multi = ne.read_text_multi(np.ones((50, 150, 3), dtype=np.uint8) * 255)
    check('no-engine multi returns []', multi == [])
except Exception as e:
    check('engine unavailable no crash', False, str(e))

# --- TEST 19: Cross-track isolation after correction ---
print()
print('--- TEST 19: Cross-track isolation after correction ---')
try:
    stab = TemporalStabilizer()
    a = None
    b = None
    for i in range(3):
        a = stab.add_observation('CAM-01', 130, 'car',
            {'x1': 0.1, 'y1': 0.2, 'x2': 0.3, 'y2': 0.4},
            'MH1ZAB1234', 0.9, 0.8, i)
        b = stab.add_observation('CAM-01', 131, 'car',
            {'x1': 0.7, 'y1': 0.2, 'x2': 0.9, 'y2': 0.4},
            'GJOSDE4321', 0.9, 0.8, i)
    check('track A corrected to MH12AB1234', a['plateText'] == 'MH12AB1234' and a['corrected'])
    check('track B corrected to GJ05DE4321', b['plateText'] == 'GJ05DE4321' and b['corrected'])
    check('distinct record ids', a['id'] != b['id'])
    check('raw texts distinct and preserved',
          a['rawOcrText'] == 'MH1ZAB1234' and b['rawOcrText'] == 'GJOSDE4321')
except Exception as e:
    check('cross-track isolation no crash', False, str(e))

# --- TEST 20: Stable record id + trace fields across frames ---
print()
print('--- TEST 20: Stable record id and trace fields ---')
try:
    stab = TemporalStabilizer()
    ids = set()
    last = None
    for i in range(5):
        last = stab.add_observation('CAM-01', 140, 'car',
            {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
            'KAO1BC5678', 0.9, 0.8, i)
        ids.add(last['id'])
    check('record id stable across frames', len(ids) == 1)
    check('observationCount grows', last['observationCount'] == 5)
    check('rawOcrText preserved', last['rawOcrText'] == 'KAO1BC5678')
    check('corrected flag set', last['corrected'] is True)
    check('corrected plate is KA01BC5678', last['plateText'] == 'KA01BC5678')
    check('formatStatus VALID after correction', last['formatStatus'] == 'VALID')
    check('correctionNote populated', bool(last['correctionNote']))
except Exception as e:
    check('stable id no crash', False, str(e))

# --- Summary ---
print()
print('=' * 50)
print('Failure Tests: %d passed, %d failed' % (passed, failed))
print('=' * 50)
if failed > 0:
    sys.exit(1)
