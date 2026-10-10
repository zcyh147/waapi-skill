"""Public owned-copy SFX preservation proof; never Fresh Agent acceptance."""
from pathlib import Path
import json

import pytest

from tests.destructive.test_expansion_case_preflight import (
    expansion_runtime,
    _LIVE_COMMANDS,
    _record_oracle_call,
    canonical_digest,
)
from tests.semantic.support.codex_expansion_case_helpers import BusinessDraft, make_public_gateway
from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
from tests.semantic.support.codex_expansion_media_case import prepare_c03
from tests.semantic.support.codex_expansion_oracle_reads import expansion_oracle_reader
from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall

pytestmark = [pytest.mark.live, pytest.mark.destructive]


@pytest.mark.parametrize('expansion_runtime', [()], indirect=True)
def test_existing_sfx_reimport_preserves_sources_and_distinct_media(expansion_runtime):
    runtime = expansion_runtime
    receipts, oracle_receipts = [], []
    gateway = make_public_gateway(
        host=runtime.lifecycle.host, port=runtime.port, version=runtime.version,
        config_path=Path(runtime.env['WAAPI_SKILL_CONFIG_PATH']), state_dir=runtime.state_dir,
        environment=runtime.env, receipts=receipts, live_commands=_LIVE_COMMANDS,
    )
    actor = OwnedDirectWaapiCall(host=runtime.lifecycle.host, port=runtime.port)
    report = {'category': 'existing-sfx-reimport-goal', 'status': 'FAIL',
              'verifier_strength': 'operation_specific_readback_plus_independent_graph_and_media',
              'agent_pass': False, 'business_effect_verified': False}
    failure = None
    try:
        gateway(['config-set', '--project-modification-policy', 'ask_before_changes'])
        ctx = ExpansionCaseContext(
            version=runtime.version, scenario_id=f'EXP{runtime.version[2:4]}-C03',
            project_path=runtime.sandbox.sandbox_project,
            asset_root=runtime.sandbox.sandbox_path / 'ExpansionAssets' / 'C03', gateway=gateway,
            trusted_read=expansion_oracle_reader(
                version=runtime.version, read_call=lambda uri, args, options: _record_oracle_call(
                    actor, oracle_receipts, uri, args, options)),
        )
        prepared = prepare_c03(ctx)
        start = len(receipts)
        draft = BusinessDraft(ctx, 'audio.import')
        mappings = prepared.archive_preview_parameters['mappings']
        target_ids = prepared.archive_preview_parameters['target_ids']
        for index, (path, file_path) in enumerate(mappings.items()):
            row_id = f'row{index}'
            handle = draft.bind(object_id=target_ids[path])
            media = Path(file_path)
            draft.step('draft-declare-import-batch', '--row-order', row_id,
                       '--existing-row', row_id, handle, '--media-directory', str(media.parent),
                       '--media-file', row_id, media.name)
        draft.step('draft-check')
        preview = draft.step('preview-from-draft')
        transaction = preview['transaction_id']
        artifact = json.loads((runtime.state_dir / 'transactions' / transaction / 'preview.json').read_text())['artifact']
        assert prepared.approve_preview(artifact)
        assert canonical_digest(prepared.snapshot()) == canonical_digest(prepared.before)
        shown = gateway(['transaction-show', transaction, '--summary-only'])
        gateway(['confirm', transaction, '--confirmation-token', shown['confirmation']['token']])
        executed = gateway(['execute', transaction])
        verified = gateway(['verify', transaction])
        assert executed['state'] == 'executed_unverified'
        assert verified['state'] == 'verified'
        assert verified['verification']['business_state_verified'] is True
        after = prepared.snapshot()
        assertions = prepared.verify(prepared.before, after)
        assert set(assertions) == prepared.required_assertions and all(assertions.values())
        assert sum(row['argv'][0] == 'execute' for row in receipts[start:]) == 1
        report.update(status='PASS', business_effect_verified=True, preview_approved=True,
                      transaction_ids=[transaction], independent_assertions=assertions,
                      before_sha256=canonical_digest(prepared.before), after_sha256=canonical_digest(after))
    except BaseException as exc:
        failure = exc
        report['reason'] = str(exc)
        raise
    finally:
        closed = actor.close() and actor.fully_closed
        report.update(trusted_oracle_closed=closed, gateway_receipts=receipts, oracle_receipts=oracle_receipts)
        if not closed:
            report['status'] = 'FAIL'
        runtime.category_results.append(report)
        if not closed:
            if failure is not None:
                failure.add_note('Trusted read-only oracle did not close')
            else:
                raise AssertionError('Trusted read-only oracle did not close')
