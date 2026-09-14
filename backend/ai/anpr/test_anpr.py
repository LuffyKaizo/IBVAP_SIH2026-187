"""Deterministic unit tests for ANPR pipeline components."""
import sys, os
import numpy as np
import cv2
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from ai.anpr.plate_detector import PlateDetector, PlateCandidate
from ai.anpr.ocr_engine import OCREngine
from ai.anpr.temporal import TemporalStabilizer

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
print('=== PLATE DETECTOR TESTS ===')
detector = PlateDetector()

print()
print('--- TEST 1: Valid plate crop preprocessing ---')
plate_img = np.ones((50, 150, 3), dtype=np.uint8) * 255
cv2.putText(plate_img, 'AB1234', (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
processed = detector.preprocess_for_ocr(plate_img)
check('preprocessing produces output', processed is not None and processed.size > 0)
check('output is grayscale', len(processed.shape) == 2)

print()
print('--- TEST 2: Invalid crop coordinates ---')
crop = detector.extract_plate_crop(np.zeros((100, 200, 3), dtype=np.uint8),
    PlateCandidate(bbox=(0, 0, 0, 0), confidence=0.5, area=0))
check('zero-area crop returns None', crop is None)

print()
print('--- TEST 3: Empty/None crop ---')
crop = detector.extract_plate_crop(None, PlateCandidate(bbox=(0, 0, 10, 10), confidence=0.5, area=100))
check('None image returns None', crop is None)
crop = detector.extract_plate_crop(np.array([]), PlateCandidate(bbox=(0, 0, 10, 10), confidence=0.5, area=100))
check('Empty array returns None', crop is None)

print()
print('--- TEST 4: Preprocess with empty image ---')
result = detector.preprocess_for_ocr(np.array([]))
check('empty image returns valid default', result is not None and result.size > 0)

print()
print('--- TEST 5: No plates in plain image ---')
plain = np.ones((300, 400, 3), dtype=np.uint8) * 128
candidates = detector.detect_plates(plain)
check('no candidates in plain image', len(candidates) == 0)

print()
print('--- TEST 6: Plate detection on synthetic vehicle ---')
vehicle_roi = np.ones((300, 400, 3), dtype=np.uint8) * 100
cv2.rectangle(vehicle_roi, (120, 200), (280, 260), (255, 255, 255), -1)
cv2.rectangle(vehicle_roi, (120, 200), (280, 260), (0, 0, 0), 2)
candidates = detector.detect_plates(vehicle_roi)
check('plate detection runs without crash', True)

print()
print('=== OCR ENGINE TESTS ===')
ocr = OCREngine()
ocr.initialize()
print('  (Engine:', ocr._engine_name or 'none', ')')

print()
print('--- TEST 7: OCR text normalization ---')
check('lowercase/spaces normalized', OCREngine.normalize_plate_text(' ab 12 cd 3456 ') == 'AB12CD3456')
check('hyphens removed', OCREngine.normalize_plate_text('KA-01-AB-1234') == 'KA01AB1234')
check('empty string returns None', OCREngine.normalize_plate_text('') is None)
check('single char returns None', OCREngine.normalize_plate_text('X') is None)
check('valid plate preserved', OCREngine.normalize_plate_text('AB1234') == 'AB1234')

print()
print('--- TEST 8: OCR on None/empty ---')
text, conf = ocr.read_text(None)
check('None image returns (None, 0)', text is None and conf == 0.0)
text, conf = ocr.read_text(np.array([]))
check('Empty image returns (None, 0)', text is None and conf == 0.0)

print()
print('=== TEMPORAL STABILIZER TESTS ===')
stab = TemporalStabilizer()

print()
print('--- TEST 9: Same plate repeated ---')
for i in range(5):
    result = stab.add_observation('CAM-01', 17, 'car',
        {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
        'AB12CD3456', 0.91, 0.85, i * 10)
check('plate confirmed', result['plateText'] == 'AB12CD3456')
check('status is CONFIRMED', result['status'] == 'CONFIRMED')
check('trackId is 17', result['trackId'] == 17)
check('cameraId is CAM-01', result['cameraId'] == 'CAM-01')

print()
print('--- TEST 10: Noisy OCR rejection ---')
stab2 = TemporalStabilizer()
for i in range(6):
    text = 'AB12CD3456' if i != 3 else 'AB12CD34S6'
    result = stab2.add_observation('CAM-01', 17, 'car',
        {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8},
        text, 0.9, 0.85, i * 10)
check('noisy frame handled', result['plateText'] == 'AB12CD3456')

print()
print('--- TEST 11: Independent vehicles ---')
stab3 = TemporalStabilizer()
for i in range(3):
    stab3.add_observation('CAM-01', 17, 'car', {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8}, 'AB12CD3456', 0.9, 0.85, i * 10)
    stab3.add_observation('CAM-01', 23, 'truck', {'x1': 0.1, 'y1': 0.2, 'x2': 0.5, 'y2': 0.7}, 'XY99ZZ7890', 0.88, 0.8, i * 10)
results = stab3.get_active_results()
check('2 vehicles tracked', len(results) == 2)

print()
print('--- TEST 12: Track expiry ---')
stab4 = TemporalStabilizer()
stab4.add_observation('CAM-01', 17, 'car', {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8}, 'AB12', 0.9, 0.85, 0)
stab4.add_observation('CAM-01', 23, 'car', {'x1': 0.1, 'y1': 0.2, 'x2': 0.5, 'y2': 0.7}, 'XY99', 0.88, 0.8, 0)
stab4.cleanup_stale({23}, 'CAM-01')
results = stab4.get_active_results()
check('track 17 removed', len(results) == 1)

print()
print('--- TEST 13: OCR throttling ---')
stab5 = TemporalStabilizer()
check('first frame should OCR', stab5.should_ocr('CAM-01', 17, 0))
stab5.add_observation('CAM-01', 17, 'car', {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8}, 'AB12', 0.9, 0.85, 0)
check('frame 5 throttled', not stab5.should_ocr('CAM-01', 17, 5))
check('frame 10 should OCR', stab5.should_ocr('CAM-01', 17, 10))

print()
print('--- TEST 14: Low confidence -> DETECTED ---')
stab7 = TemporalStabilizer()
result = stab7.add_observation('CAM-01', 17, 'car', {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8}, None, 0.0, 0.3, 0)
check('no plate text -> DETECTED', result['status'] == 'DETECTED')
check('plateText is None', result['plateText'] is None)

print()
print('--- TEST 15: resolve_all ---')
stab8 = TemporalStabilizer()
stab8.add_observation('CAM-01', 17, 'car', {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8}, 'AB12', 0.9, 0.85, 0)
stab8.resolve_all()
check('resolve_all clears state', len(stab8.get_active_results()) == 0)

print()
print('--- TEST 16: Deduplication ---')
stab9 = TemporalStabilizer()
for i in range(20):
    stab9.add_observation('CAM-01', 17, 'car', {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8}, 'AB12CD', 0.9, 0.85, i)
results = stab9.get_active_results()
check('20 frames -> 1 observation', len(results) == 1)

print()
print('--- TEST 17: New track new observation ---')
stab10 = TemporalStabilizer()
stab10.add_observation('CAM-01', 17, 'car', {'x1': 0.3, 'y1': 0.4, 'x2': 0.7, 'y2': 0.8}, 'AB12', 0.9, 0.85, 0)
stab10.add_observation('CAM-01', 99, 'truck', {'x1': 0.1, 'y1': 0.2, 'x2': 0.5, 'y2': 0.7}, 'XY99', 0.88, 0.8, 0)
check('2 separate observations', len(stab10.get_active_results()) == 2)

print()
print('=' * 50)
print('ANPR Tests: %d passed, %d failed' % (passed, failed))
print('=' * 50)
if failed > 0:
    sys.exit(1)
