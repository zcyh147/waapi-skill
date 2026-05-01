# Task 1 No-Leakage Evidence

## Command
```bash
python - <<'PY'
import json
from pathlib import Path
path = Path('.sisyphus/evidence/wwise-2023-test-parity/parity-baseline.json')
payload = json.loads(path.read_text(encoding='utf-8'))
forbidden = ('2024', '2025', 'resources/coverage/2024', 'resources/coverage/2025')
violations = []

def walk(value, pointer='$'):
    if isinstance(value, str):
        for needle in forbidden:
            if needle in value:
                violations.append((pointer, needle, value))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            walk(item, f'{pointer}[{index}]')
    elif isinstance(value, dict):
        for key, item in value.items():
            walk(item, f'{pointer}.{key}')

walk(payload)
assert not violations, violations[:10]
print('no-2024-2025-leakage-ok')
PY
```
Exit code: 0

Output:
```text
no-2024-2025-leakage-ok
```

## Validation Summary
- Recursively checked every string value in `.sisyphus/evidence/wwise-2023-test-parity/parity-baseline.json`.
- No string value contains `2024`, `2025`, `resources/coverage/2024`, or `resources/coverage/2025`.
