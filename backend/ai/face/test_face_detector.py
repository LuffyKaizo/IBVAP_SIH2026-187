"""Deterministic tests for the face DETECTION module.

Covers detector behavior (real YuNet inference on synthetic renders) and
the explainable person-track association. No fabricated detections: the
detector either finds faces in real images or the test reports failure.

Run: python -m ai.face.test_face_detector
"""

import sys
import os
import json

import numpy as np
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from ai.face.face_detector import (
    FaceDetector, FaceDetection, associate_faces_with_persons,
)
from ai.tracking.tracker import TrackedObject

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


def render_face_image(width=480, height=360, faces=1, noise=False):
    """Render a stylized-but-photogenic face scene for the REAL detector.

    Skin-tone oval + eyes + brows + mouth on photo-like background. This is
    a test FIXTURE (clearly synthetic); it exercises the real detector but
    does NOT represent real-world accuracy.
    """
    img = np.full((height, width, 3), 70, dtype=np.uint8)
    # textured background
    rng = np.random.default_rng(42)
    img = rng.integers(50, 90, size=(height, width, 3), dtype=np.uint8)
    centers = []
    for i in range(faces):
        cx = width // (faces + 1) * (i + 1)
        cy = height // 2
        # neck + shoulders
        cv2.rectangle(img, (cx - 25, cy + 90), (cx + 25, height), (150, 140, 130), -1)
        cv2.ellipse(img, (cx, height + 30), (110, 90), 0, 180, 360, (60, 80, 140), -1)
        # face oval (skin tone)
        cv2.ellipse(img, (cx, cy), (58, 78), 0, 0, 360, (120, 150, 200), -1)
        # eyes
        cv2.ellipse(img, (cx - 24, cy - 14), (11, 6), 0, 0, 360, (30, 30, 30), -1)
        cv2.ellipse(img, (cx + 24, cy - 14), (11, 6), 0, 0, 360, (30, 30, 30), -1)
        cv2.circle(img, (cx - 24, cy - 14), 3, (250, 250, 250), -1)
        cv2.circle(img, (cx + 24, cy - 14), 3, (250, 250, 250), -1)
        # brows
        cv2.line(img, (cx - 36, cy - 28), (cx - 12, cy - 31), (35, 25, 20), 4)
        cv2.line(img, (cx + 12, cy - 31), (cx + 36, cy - 28), (35, 25, 20), 4)
        # nose + mouth
        cv2.line(img, (cx, cy - 10), (cx - 4, cy + 22), (110, 90, 80), 3)
        cv2.ellipse(img, (cx, cy + 42), (20, 9), 0, 0, 360, (60, 50, 90), -1)
        centers.append((cx, cy))
    if noise:
        img = cv2.GaussianBlur(img, (5, 5), 2)
    return img, centers


print()
print('=== FACE DETECTOR (YuNet, real inference) ===')

det = FaceDetector(score_threshold=0.4)
ok = det.initialize()
check('model loads and initializes', ok)

print()
print('--- TEST 1: Empty frame -> zero faces ---')
try:
    blank = np.full((360, 480, 3), 60, dtype=np.uint8)
    res = det.detect(blank)
    check('blank frame has zero faces', len(res) == 0, 'got %d' % len(res))
except Exception as e:
    check('blank frame no crash', False, str(e))

print()
print('--- TEST 2: Face image -> face detected ---')
try:
    img, centers = render_face_image(faces=1)
    res = det.detect(img)
    check('single face detected', len(res) == 1, 'got %d' % len(res))
    if res:
        f = res[0]
        check('confidence above threshold', f.confidence >= 0.4)
        cx, cy = centers[0]
        fx1, fy1, fx2, fy2 = f.bbox
        check('bbox near rendered face center',
              fx1 <= cx <= fx2 and fy1 <= cy <= fy2,
              'bbox=%s center=%s' % (f.bbox, (cx, cy)))
except Exception as e:
    check('single face no crash', False, str(e))

print()
print('--- TEST 3: Multiple faces -> multiple detections ---')
try:
    img, centers = render_face_image(faces=3)
    res = det.detect(img)
    check('three faces detected', len(res) == 3, 'got %d' % len(res))
except Exception as e:
    check('multi face no crash', False, str(e))

print()
print('--- TEST 4/5: Association inside / outside person bbox ---')
try:
    img, centers = render_face_image(faces=1)
    faces = det.detect(img)
    check('fixture produces a face for association tests', len(faces) == 1)

    fw, fh = img.shape[1], img.shape[0]
    if faces:
        fx1, fy1, fx2, fy2 = faces[0].bbox
        # Person bbox centered on the face, large enough to contain it.
        pw, ph = int((fx2 - fx1) * 4), int((fy2 - fy1) * 6)
        pcx, pcy = int((fx1 + fx2) / 2), int((fy1 + fy2) / 2)
        inside_person = TrackedObject(
            track_id=17, class_id=0, class_name='person', confidence=0.9,
            bbox=(pcx - pw // 2, pcy - ph // 2, pcx + pw // 2, pcy + ph // 2))
        payload = associate_faces_with_persons(faces, [inside_person], fw, fh)
        check('face inside person bbox -> track 17',
              payload[0]['personTrackId'] == 17,
              'got %r' % payload[0]['personTrackId'])

        # Person far away
        far_person = TrackedObject(
            track_id=23, class_id=0, class_name='person', confidence=0.9,
            bbox=(0, 0, 60, 60))
        payload2 = associate_faces_with_persons(faces, [far_person], fw, fh)
        check('face outside person bbox -> None',
              payload2[0]['personTrackId'] is None,
              'got %r' % payload2[0]['personTrackId'])

        # Vehicle track must NEVER be associated
        vehicle = TrackedObject(
            track_id=99, class_id=2, class_name='car', confidence=0.9,
            bbox=(pcx - pw // 2, pcy - ph // 2, pcx + pw // 2, pcy + ph // 2))
        payload3 = associate_faces_with_persons(faces, [vehicle], fw, fh)
        check('vehicle track never associated',
              payload3[0]['personTrackId'] is None)
except Exception as e:
    check('association no crash', False, str(e))

print()
print('--- TEST 6: Low confidence rejected by threshold ---')
try:
    strict = FaceDetector(score_threshold=0.99)
    strict.initialize()
    img, _ = render_face_image(faces=1)
    res = strict.detect(img)
    check('strict threshold rejects faces', len(res) == 0, 'got %d' % len(res))
except Exception as e:
    check('low confidence no crash', False, str(e))

print()
print('--- TEST 7: Invalid frames -> no crash ---')
try:
    check('None image', det.detect(None) == [])
    check('empty array', det.detect(np.array([])) == [])
    check('tiny image', det.detect(np.zeros((4, 4, 3), dtype=np.uint8)) == [])
    check('grayscale ok', isinstance(det.detect(
        np.zeros((120, 160), dtype=np.uint8)), list))
except Exception as e:
    check('invalid frame no crash', False, str(e))

print()
print('--- TEST 8: Transport dict is normalized + JSON serializable ---')
try:
    img, _ = render_face_image(faces=1)
    faces = det.detect(img)
    if faces:
        d = faces[0].to_dict(img.shape[1], img.shape[0])
        b = d['bbox']
        check('bbox normalized 0..1',
              all(0.0 <= b[k] <= 1.0 for k in ('x1', 'y1', 'x2', 'y2')))
        blob = json.dumps({'faces': [dict(d, personTrackId=None,
                                          timestamp='t', source='AI',
                                          id='FACE-001')]})
        check('JSON serializable', isinstance(json.loads(blob), dict))
    else:
        check('transport dict testable', False, 'no face detected in fixture')
except Exception as e:
    check('serialization no crash', False, str(e))

print()
print('--- TEST 9: Detector unavailable -> empty results, no crash ---')
try:
    class NoModel(FaceDetector):
        def initialize(self):
            self._init_tried = True
            self._available = False
            return False
    nm = NoModel()
    check('unavailable detector returns []',
          nm.detect(np.zeros((240, 320, 3), dtype=np.uint8)) == [])
except Exception as e:
    check('unavailable no crash', False, str(e))

print()
print('--- TEST 10: Frame scaling (large image) ---')
try:
    img, _ = render_face_image(width=960, height=720, faces=1)
    res = det.detect(img)
    check('large frame face detected', len(res) >= 1, 'got %d' % len(res))
except Exception as e:
    check('large frame no crash', False, str(e))

print()
print('=' * 50)
print('Face Detector Tests: %d passed, %d failed' % (passed, failed))
print('=' * 50)
if failed > 0:
    sys.exit(1)
