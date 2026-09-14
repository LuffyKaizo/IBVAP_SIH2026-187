"""Pipeline-integration tests for face detection metadata.

Verifies faces[] flows through PipelineState exactly like detections/
events/anpr, that stale state is cleared on restart, and existing
ANPR metadata still works alongside faces.

Run: python -m ai.face.test_pipeline_integration
"""

import sys
import os
import json

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from ai.pipeline import PipelineState
from ai.tracking.tracker import TrackingResult, TrackedObject

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


def make_tracking(frame_index=0):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    tracking = TrackingResult(
        tracked_objects=[TrackedObject(
            track_id=17, class_id=0, class_name='person',
            confidence=0.9, bbox=(100, 80, 300, 460))],
        frame_width=640, frame_height=480,
        active_tracks=1, frame_index=frame_index)
    return frame, tracking


FACE = {
    'id': 'FACE-001', 'personTrackId': 17, 'confidence': 0.92,
    'bbox': {'x1': 0.42, 'y1': 0.18, 'x2': 0.49, 'y2': 0.31},
    'timestamp': '2026-09-05T00:00:00+00:00', 'source': 'AI',
}

print()
print('=== FACE METADATA PIPELINE INTEGRATION ===')

print()
print('--- TEST 1: faces[] present in metadata ---')
try:
    ps = PipelineState()
    frame, tracking = make_tracking()
    ps.update(frame, tracking, 'CAM-01', faces=[dict(FACE)])
    md = ps.get_latest_metadata()
    check('metadata has faces key', 'faces' in md)
    check('one face transported', len(md['faces']) == 1)
    f = md['faces'][0]
    check('face fields intact', f['id'] == 'FACE-001'
          and f['personTrackId'] == 17 and f['source'] == 'AI')
    check('existing detections untouched', len(md['detections']) == 1)
    check('detections still normalized',
          all(0.0 <= md['detections'][0]['bbox'][k] <= 1.0
              for k in ('x1', 'y1', 'x2', 'y2')))
except Exception as e:
    check('faces in metadata', False, str(e))

print()
print('--- TEST 2: empty faces replaces stale boxes ---')
try:
    ps = PipelineState()
    frame, tracking = make_tracking()
    ps.update(frame, tracking, 'CAM-01', faces=[dict(FACE)])
    # Next frame with no faces (person left / not an OCR-interval frame)
    tracking2 = make_tracking(frame_index=1)[1]
    tracking2.tracked_objects = []
    tracking2.active_tracks = 0
    ps.update(frame, tracking2, 'CAM-01', faces=[])
    md = ps.get_latest_metadata()
    check('stale faces cleared', md['faces'] == [])
except Exception as e:
    check('stale replacement', False, str(e))

print()
print('--- TEST 3: faces default to [] when not provided ---')
try:
    ps = PipelineState()
    frame, tracking = make_tracking()
    ps.update(frame, tracking, 'CAM-01')
    md = ps.get_latest_metadata()
    check('faces defaults to empty list', md['faces'] == [])
except Exception as e:
    check('default faces', False, str(e))

print()
print('--- TEST 4: JSON serialization (WebSocket shape) ---')
try:
    ps = PipelineState()
    frame, tracking = make_tracking()
    ps.update(frame, tracking, 'CAM-01', faces=[dict(FACE)])
    md = ps.get_latest_metadata()
    md['alerts'] = []
    md['anpr'] = []
    blob = json.dumps(md)  # raises on non-serializable
    back = json.loads(blob)
    check('full metadata JSON round-trip', isinstance(back, dict))
    check('faces survive round-trip', back['faces'][0]['id'] == 'FACE-001')
    b = back['faces'][0]['bbox']
    check('face bbox normalized 0..1',
          all(0.0 <= b[k] <= 1.0 for k in ('x1', 'y1', 'x2', 'y2')))
except Exception as e:
    check('json round-trip', False, str(e))

print()
print('--- TEST 5: restart clears face state ---')
try:
    ps = PipelineState()
    frame, tracking = make_tracking()
    ps.update(frame, tracking, 'CAM-01', faces=[dict(FACE)])
    ps.clear()
    check('metadata None after clear', ps.get_latest_metadata() is None)
    # After restart, next update must not resurrect old faces
    ps.update(frame, tracking, 'CAM-01', faces=[])
    check('faces empty after restart+update',
          ps.get_latest_metadata()['faces'] == [])
except Exception as e:
    check('restart clear', False, str(e))

print()
print('--- TEST 6: ANPR + faces coexist in metadata ---')
try:
    ps = PipelineState()
    frame, tracking = make_tracking()
    ps.update(frame, tracking, 'CAM-01', faces=[dict(FACE)])
    anpr_rec = {
        'id': 'ANPR-test01', 'trackId': 5, 'cameraId': 'CAM-01',
        'vehicleClass': 'car', 'plateText': 'MH12AB1234',
        'plateConfidence': 85.0, 'ocrConfidence': 90.0,
        'vehicleBbox': {'x1': 0.1, 'y1': 0.2, 'x2': 0.5, 'y2': 0.8},
        'plateBbox': None, 'status': 'CONFIRMED',
        'timestamp': '2026-09-05T00:00:00+00:00', 'source': 'AI',
        'rawOcrText': 'MH1ZAB1234', 'observationCount': 3,
        'corrected': True, 'formatStatus': 'VALID',
        'correctionNote': 'Z->2@3',
    }
    ps.set_anpr_results([anpr_rec])
    md = ps.get_latest_metadata()
    check('anpr present', len(md['anpr']) == 1)
    check('faces still present', len(md['faces']) == 1)
    check('anpr correction intact', md['anpr'][0]['corrected'] is True)
    json.dumps(md)
    check('combined metadata JSON ok', True)
except Exception as e:
    check('anpr+faces coexist', False, str(e))

print()
print('=' * 50)
print('Pipeline Integration Tests: %d passed, %d failed' % (passed, failed))
print('=' * 50)
if failed > 0:
    sys.exit(1)
