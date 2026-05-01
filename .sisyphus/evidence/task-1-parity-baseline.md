# Task 1 Parity Baseline Evidence

## Artifact
- Created `.sisyphus/evidence/wwise-2023-test-parity/parity-baseline.json` from committed manifest, coverage, Phase 2/2.1 policy, and deferred resources only.
- Summary: 144 shared URIs, 37 new 2023.1 URIs, 0 missing from 2023.1, 181 `status_by_uri` entries, 181 `recommended_2023_bucket` entries.

## Commands

### Required pytest
```bash
python -m pytest tests/unit/test_2023_cross_version_audit.py tests/unit/test_2023_api_resource_coverage.py -q
```
Exit code: 0

Output:
```text
.........                                                                [100%]
9 passed in 0.08s
```

### Baseline JSON counts and required keys
```bash
python - <<'PY'
import json
from pathlib import Path
path = Path('.sisyphus/evidence/wwise-2023-test-parity/parity-baseline.json')
payload = json.loads(path.read_text(encoding='utf-8'))
assert payload['wwise_2022']['reflected_total'] == 144
assert payload['wwise_2022']['functions'] == 112
assert payload['wwise_2022']['topics'] == 32
assert payload['wwise_2023']['reflected_total'] == 181
assert payload['wwise_2023']['functions'] == 149
assert payload['wwise_2023']['topics'] == 32
for key in ['same_uri', 'new_in_2023', 'missing_from_2023', 'status_by_uri', 'recommended_2023_bucket']:
    assert key in payload, key
    assert isinstance(payload[key], list), key
print('counts-and-required-keys-ok')
print(json.dumps({
    'same_uri': len(payload['same_uri']),
    'new_in_2023': len(payload['new_in_2023']),
    'missing_from_2023': len(payload['missing_from_2023']),
    'status_by_uri': len(payload['status_by_uri']),
    'recommended_2023_bucket': len(payload['recommended_2023_bucket']),
}, sort_keys=True))
PY
```
Exit code: 0

Output:
```text
counts-and-required-keys-ok
{"missing_from_2023": 0, "new_in_2023": 37, "recommended_2023_bucket": 181, "same_uri": 144, "status_by_uri": 181}
```

## Validation Summary
- Exact reflected counts match the required values for 2022.1 and 2023.1.
- Required top-level arrays are present and are arrays.
- Runtime source and committed resource classification files were not modified.
