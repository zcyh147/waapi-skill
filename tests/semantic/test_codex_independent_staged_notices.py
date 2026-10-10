"""Independent stage judgments with source-attested phase and context projection."""
import copy
import hashlib
import json
import shlex
from pathlib import Path
import pytest
from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_FIXTURES = Path(__file__).parents[1] / 'fixtures/semantic'
_DATA = json.loads((_FIXTURES / 'expansion-independent-stage-notices-eba698d.json').read_text())


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _phase(raw, expected):
    outer = shlex.split(raw)
    assert outer[:2] == ['/bin/bash', '-lc']
    argv = shlex.split(outer[-1])
    assert argv[argv.index('gateway.py') + 1] == expected


def _case(case_id):
    if case_id == _DATA['supported_seam_control']:
        case = copy.deepcopy(_DATA['supported_control'])
        for event in case['events']:
            if 'source_gateway_phase' in event:
                _phase(event['item']['command'], event['source_gateway_phase'])
                event['item']['command'] = event['source_gateway_phase']
    else:
        raw = json.loads((_FIXTURES / _DATA['context_fixture']).read_text())
        case = copy.deepcopy(next(case for case in raw['cases'] if case['case'] == case_id))
        proof = next(row for row in _DATA['contexts'] if row['case'] == case_id)
        assert _digest(case['artifact']) == proof['artifact_value_sha256']
        assert _digest(case['before']) == proof['before_value_sha256']
        assert [e['item']['text'] for e in case['events'] if e['item']['type'] == 'agent_message'] == proof['raw_agent_messages']
        for phase, raw_command in proof['raw_phase_commands'].items():
            _phase(raw_command, phase)
            assert sum(e['item'].get('command') == phase for e in case['events']) == 1
    preview = next(i for i, e in enumerate(case['events']) if e['item'].get('command') == 'preview-from-draft')
    execute = next(i for i, e in enumerate(case['events']) if e['item'].get('command') == 'execute')
    assert preview < execute
    return case


def _record(tmp_path, node, actual, expected):
    diagnostic = {'id': node, 'actual': actual, 'expected': expected, 'passed': actual is expected}
    (tmp_path / 'notice-result.json').write_text(json.dumps(diagnostic) + '\n')
    assert actual is expected, diagnostic


def test_existing_complete_notice_confirms_staged_helper_seam(tmp_path):
    _record(tmp_path, 'supported-seam-control', _grammatical_notice(_case(_DATA['supported_seam_control'])), True)


@pytest.mark.parametrize('case_id', _DATA['positive_ids'])
def test_independent_exact_staged_notice(case_id, tmp_path):
    _record(tmp_path, case_id, _grammatical_notice(_case(case_id)), True)


@pytest.mark.parametrize('negative', _DATA['negatives'], ids=lambda row: row['id'])
def test_independent_staged_notice_phase_and_context_negatives(negative, tmp_path):
    case = _case(negative['case'])
    events = case['events']
    preview = next(i for i,e in enumerate(events) if e['item'].get('command') == 'preview-from-draft')
    post = next(e for e in events[preview + 1:] if e['item']['type'] == 'agent_message')
    damage = negative['damage']
    if damage in {'late_notice', 'adoption_before_preview'}:
        events.remove(post)
        if damage == 'late_notice': events.append(post)
        else: events.insert(preview, post)
    elif damage == 'generic_only':
        for e in events:
            if e['item']['type'] == 'agent_message': e['item']['text'] = '正在处理。'
    elif damage == 'pre_only':
        events.remove(post)
    elif damage == 'generic_adoption': post['item']['text'] = '变更预览已生成，正在处理。'
    elif damage == 'stale_artifact':
        old = 'Expansion_EXP22-C09_NewGain'
        case['artifact'] = json.loads(json.dumps(case['artifact']).replace(old, old + '2'))
    elif damage == 'competing_addition':
        prior = next(e for e in events[:preview] if '将追加' in e['item'].get('text',''))
        prior['item']['text'] += '同时追加名为 OtherGain 的 Wwise Gain 效果器。'
    elif damage == 'extra_write':
        post['item']['text'] += ('同时把 NumSegmentAdvance 改为 2。' if negative['case'].endswith('M05') else '同时修改 Pitch 为 12。')
    elif damage == 'refusal': post['item']['text'] += '我不会执行该变更。'
    else:
        substitutions = {'changed_curve': ('-12 dB', '-60 dB'),
            'foreign_owner': ('目标衰减对象', 'OtherAttenuation') if negative['case'].endswith('C08') else ('目标声音', 'OtherSound'),
            'historical_effect': ('即将追加', '此前已经追加'),
            'wrong_target': ('Backup_Team_Arrives', 'Bonus'), 'wrong_origin': ('从 Bonus 改为', '从 Combat 改为')}
        old,new = substitutions[damage]
        assert old in post['item']['text']
        post['item']['text'] = post['item']['text'].replace(old,new)
    _record(tmp_path, negative['id'], _grammatical_notice(case), False)
