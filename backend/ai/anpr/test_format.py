"""Unit tests for plate_format: conservative format validation and
position-constrained contextual correction (anti-fabrication).

Run: python -m ai.anpr.test_format
"""
import sys
import os
import re as _re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from ai.anpr.plate_format import format_status, contextual_correct

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

def re_only_alnum(s):
    return _re.sub(r'[^A-Z0-9]', '', s.upper())

print()
print('=== PLATE FORMAT VALIDATION ===')

print()
print('--- format_status: VALID ---')
for p in ['MH12AB1234', 'DL03XY9901', 'GJ05DE4321', 'KA01BC5678', 'TN09EF6789',
          'KA01AB123', 'DL01C1234', 'LAD01A1234']:
    check('VALID: %s' % p, format_status(p) == 'VALID')

print()
print('--- format_status: INVALID ---')
for p in ['ABCDEFG', 'HELLOWORLD', '12345678', 'AB12CD', 'A1B2C3D4E5',
          'AB12CD34EF', 'ZZZZZZZZZZ']:
    check('INVALID: %r' % p, format_status(p) == 'INVALID')

print()
print('--- format_status: UNCERTAIN ---')
for p in ['', 'AB', 'AB1', None]:
    check('UNCERTAIN: %r' % p, format_status(p) == 'UNCERTAIN')

print()
print('=== CONTEXTUAL CORRECTION ===')

print()
print('--- Known EasyOCR confusions are fixed exactly ---')
cases = [
    ('MH1ZAB1234', 'MH12AB1234'),
    ('DLO3XY9901', 'DL03XY9901'),
    ('GJOSDE4321', 'GJ05DE4321'),
    ('KAO1BC5678', 'KA01BC5678'),
    ('TNO9EF6789', 'TN09EF6789'),
]
for raw, exp in cases:
    r = contextual_correct(raw, confidence=0.9)
    check('%s -> %s' % (raw, exp), r['corrected'] == exp and r['changed'],
          'got %r' % (r['corrected'],))
    check('original preserved: %s' % raw, r['original'] == re_only_alnum(raw))

print()
print('--- NO global replacement / anti-fabrication ---')

r = contextual_correct('ABCDEFG', confidence=0.9)
check('letters-only untouched', r['changed'] is False and r['corrected'] is None,
      'got %r' % (r['corrected'],))

r = contextual_correct('HELLOWORLD', confidence=0.9)
check('10 letters (no digit slots) untouched', r['changed'] is False)

r = contextual_correct('MH12AB1234', confidence=0.9)
check('already-valid plate unchanged', r['changed'] is False)

r = contextual_correct('A1B2C3D4E5', confidence=0.9)
check('non-plate alnum untouched', r['changed'] is False)

r = contextual_correct('MH12AB1234', confidence=0.2)
check('low confidence -> no correction', r['changed'] is False)

r = contextual_correct('8HAV1234', confidence=0.9)
check('unresolvable segments not fabricated', r['changed'] is False)

print()
print('--- Corrections are flagged and traceable ---')
r = contextual_correct('MH1ZAB1234', confidence=0.9)
check('changed flag True', r['changed'] is True)
check('changes positions listed', len(r['changes']) >= 1)
check('status of original recorded', r['status'] in ('VALID', 'INVALID', 'UNCERTAIN'))
check('corrected_status VALID', r['corrected_status'] == 'VALID')
check('reason populated', bool(r['reason']))

print()
print('=' * 50)
print('Format Tests: %d passed, %d failed' % (passed, failed))
print('=' * 50)
if failed > 0:
    sys.exit(1)
