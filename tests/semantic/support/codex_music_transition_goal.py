"""Developer-only populated Transition boolean maintenance and saved-order proof."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping
import xml.etree.ElementTree as ET

from tests.semantic.support.codex_expansion_case_helpers import BusinessDraft, CaseBoundaryError, file_evidence
from tests.semantic.support.codex_expansion_policy import canonical_digest
from tests.semantic.support.codex_music_oracle_probes import TRANSITION, TRANSITION_ROOT
from tests.semantic.support.codex_filesystem_security import read_bounded_exclusive_regular_file, path_is_link_or_reparse

FIELD = 'PlaySourcePostExit'
MEANING = 'Play Source Post-exit'
SAVE = 'ak.wwise.core.project.save'


def _tree(node):
    children = [_tree(child) for child in node]
    if node.tag == 'PropertyList':
        children.sort(key=lambda row: (row[0], row[1].get('Name', '')))
    return [node.tag, dict(sorted(node.attrib.items())), node.text if node.text and node.text.strip() else '', children]


def transition_xml_state(raw: bytes, witness: Mapping):
    if len(raw) > 8 * 1_048_576 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise CaseBoundaryError('Transition XML is not bounded entity-free owned evidence')
    root = ET.fromstring(raw)
    roots = [node for node in root.iter('MusicTransition') if node.get('ID') == TRANSITION_ROOT]
    if len(roots) != 1:
        raise CaseBoundaryError('Transition XML has no unique existing root')
    owners = [node for node in root.iter('MusicSwitchContainer') if node.get('ID') == witness['transition']['owner']]
    owned_roots = [] if len(owners) != 1 else (
        owners[0].findall('./TransitionList/MusicTransition') +
        owners[0].findall("./ReferenceList/Reference[@Name='TransitionRoot']/Custom/MusicTransition"))
    if len(owned_roots) != 1 or owned_roots[0] is not roots[0]:
        raise CaseBoundaryError('Transition root is not owned by the pinned existing Music Switch')
    rules = roots[0].findall('./ChildrenList/MusicTransition')
    ids = [node.get('ID') for node in rules]
    expected = [row['id'] for row in witness['transition']['rules']]
    if len(ids) != 15 or len(set(ids)) != 15 or set(ids) != set(expected):
        raise CaseBoundaryError('Transition XML lost its complete fifteen-rule baseline')
    targets = [node for node in rules if node.get('ID') == TRANSITION]
    if len(targets) != 1:
        raise CaseBoundaryError('Transition target is not owned by the pinned root')
    target = targets[0]
    fades = target.findall('./TransitionInfo/SourceFadeOut/MusicFade')
    if len(fades) != 1 or fades[0].get('ID') != witness['transition']['fade']:
        raise CaseBoundaryError('Transition target lost its existing source-fade role')
    properties = target.findall(f'./PropertyList/Property[@Name="{FIELD}"]')
    if len(properties) > 1 or any(node.get('Type') != 'bool' or node.get('Value') not in {'True', 'False'} for node in properties):
        raise CaseBoundaryError('Transition saved boolean is malformed or platform-dependent')
    saved_value = None if not properties else properties[0].get('Value') == 'True'
    masked = deepcopy(root)
    masked_target = next(node for node in masked.iter('MusicTransition') if node.get('ID') == TRANSITION)
    for node in masked_target.findall(f'./PropertyList/Property[@Name="{FIELD}"]'):
        masked_target.find('PropertyList').remove(node)
    return {'rule_order': ids, 'saved_value': saved_value,
        'protected_graph_sha256': canonical_digest(_tree(masked)),
        'siblings': {node.get('ID'): canonical_digest(_tree(node)) for node in rules if node.get('ID') != TRANSITION}}


def verify_transition_scalar_goal(before, after, witness, *, default):
    order = [row['id'] for row in witness['transition']['rules']]
    return {'complete_saved_rule_order_preserved': before.get('rule_order') == after.get('rule_order') == order,
        'fourteen_sibling_rules_preserved': len(before.get('siblings', {})) == 14 and before.get('siblings') == after.get('siblings'),
        'all_other_rule_reference_fade_music_graph_preserved': bool(before.get('protected_graph_sha256')) and before.get('protected_graph_sha256') == after.get('protected_graph_sha256'),
        'baseline_boolean_attested': type(before.get('value')) is bool and before['value'] == (default if before.get('saved_value') is None else before['saved_value']),
        'exact_opposite_boolean_saved_and_read_back': type(before.get('value')) is bool and type(after.get('value')) is bool and after['value'] is (not before['value']) and after.get('saved_value') is after['value'],
        'all_original_media_preserved': bool(before.get('media')) and before.get('media') == after.get('media')}


def approve_transition_scalar_preview(artifact, *, version, value):
    request = artifact.get('request', {})
    arguments = request.get('arguments', {})
    return type(value) is bool and version in {'2022.1', '2025.1'} and request.get('version') == version and (
        request.get('operation') == 'object.setProperty' and arguments == {
            'object': {'kind': 'id', 'value': TRANSITION}, 'property': FIELD, 'value': value}
        and arguments.get('value') is value)


def _boolean(ctx):
    result = ctx.gateway(['query-object', '--exact-id', TRANSITION, '--include-field', MEANING, '--include', 'parent'])
    rows = result.get('objects')
    if (result.get('status') != 'ok' or result.get('count') != 1 or result.get('query_bound') != {'mode': 'exact-object'}
            or result.get('limit_reached') is True or not isinstance(rows, list) or len(rows) != 1
            or rows[0].get('id') != TRANSITION or rows[0].get('parent', {}).get('id') != TRANSITION_ROOT
            or type(rows[0].get('properties', {}).get(FIELD)) is not bool):
        raise CaseBoundaryError('public Transition read does not disclose the exact owned boolean')
    return rows[0]['properties'][FIELD]


def transition_scalar_snapshot(ctx, path: Path, witness):
    raw = read_bounded_exclusive_regular_file(path, max_bytes=8 * 1_048_576, require_private_posix_mode=False).raw
    state = transition_xml_state(raw, witness)
    membership = ctx.gateway(['query-object', '--exact-id', TRANSITION_ROOT, '--relationship', 'children', '--max-results', '16'])
    rows = membership.get('objects', [])
    ids = [row.get('id') for row in rows]
    if (membership.get('status') != 'ok' or membership.get('count') != 15 or len(ids) != 15
            or len(set(ids)) != 15 or set(ids) != set(state['rule_order'])
            or membership.get('query_bound') != {'mode': 'take', 'value': 16} or membership.get('limit_reached') is True):
        raise CaseBoundaryError('live Transition membership is not the complete saved fifteen-rule graph')
    media = {}
    media_bytes = 0
    originals = ctx.project_path.parent / 'Originals'
    if path_is_link_or_reparse(originals) or not originals.is_dir():
        raise CaseBoundaryError('Transition originals are not one owned regular directory')
    for index, path in enumerate(originals.rglob('*')):
        if index >= 2048 or path_is_link_or_reparse(path):
            raise CaseBoundaryError('Transition media traversal exceeds its bound or contains a link')
        if path.is_file():
            media_bytes += path.stat().st_size
            if len(media) >= 256 or media_bytes > 64 * 1_048_576:
                raise CaseBoundaryError('Transition protected media exceeds its file ceiling')
            media[str(path.relative_to(originals))] = file_evidence(ctx, str(path))
    if not media:
        raise CaseBoundaryError('Transition snapshot has no owned original-media evidence')
    return {**state, 'value': _boolean(ctx), 'media': media}


def _save_owned(ctx):
    from tests.destructive.test_gateway_workflow_transaction_matrix import _save_sandbox_project
    transactions, verified = [], []
    counts = {'confirm': 0, 'execute': 0, 'verify': 0}
    def gateway(argv, *, live):
        if argv[0] in counts:
            counts[argv[0]] += 1
            if counts[argv[0]] != 1 or argv[1] not in transactions:
                raise CaseBoundaryError('owned save is not one separately previewed transaction')
        if argv[0] == 'confirm':
            shown = ctx.gateway(['transaction-show', argv[1]])
            artifact = shown.get('artifact', {})
            expected_args = {} if ctx.version == '2022.1' else {'autoCheckOutToSourceControl': False}
            request = artifact.get('request', {})
            if (shown.get('transaction_id') != argv[1] or shown.get('state') != 'awaiting_confirmation'
                    or shown.get('artifact_hash') != canonical_digest(artifact)
                    or request.get('version') != ctx.version or request.get('operation') != 'waapi.call'
                    or request.get('arguments') != {'api': SAVE, 'args': expected_args, 'options': {}}
                    or argv != ['confirm', argv[1], '--confirmation-token', shown.get('confirmation', {}).get('token')]):
                raise CaseBoundaryError('owned save Preview is not the exact closed version-pinned save')
        result = ctx.gateway(argv)
        if argv[0] == 'confirm' and result.get('state') != 'confirmed':
            raise CaseBoundaryError('owned save confirmation failed')
        if argv[0] in {'preview-from-draft', 'typed-zero-call'} and result.get('transaction_id'):
            transactions.append(result['transaction_id'])
        if argv[0] == 'verify':
            verified.append(result.get('state'))
        return result
    _save_sandbox_project(SimpleNamespace(gateway=gateway, version=ctx.version))
    if len(transactions) != 1 or any(count != 1 for count in counts.values()) or verified != ['result_schema_checked']:
        raise CaseBoundaryError('owned save lacks its honest result-schema-only lifecycle')
    return transactions[0]


def run_transition_scalar_goal(ctx, witness, snapshot):
    if ctx.version not in {'2022.1', '2025.1'}:
        raise CaseBoundaryError('Transition goal has no reviewed version lane')
    ctx.gateway(['operation-schema', 'object.setProperty'])
    before = snapshot()
    if type(before.get('value')) is not bool:
        raise CaseBoundaryError('Transition baseline is not an actual live boolean')
    expected = not before['value']
    draft = BusinessDraft(ctx, 'object.setProperty')
    owner = draft.bind(object_id=TRANSITION)
    discovered = draft.step('draft-discover-fields', '--object-handle', owner, '--meaning', MEANING)
    groups = discovered.get('meaning_results', [])
    candidates = groups[0].get('candidates', []) if len(groups) == 1 else []
    if len(candidates) != 1 or candidates[0].get('field_kind') != 'property' or candidates[0].get('value_type') != 'boolean':
        raise CaseBoundaryError('actual target metadata does not disclose one boolean property handle')
    draft.step('draft-declare-field-change', '--object-handle', owner, '--field-handle', candidates[0]['handle'],
               '--business-value', json.dumps(expected))
    draft.step('draft-check')
    preview = draft.step('preview-from-draft')
    tx = preview.get('transaction_id')
    shown = ctx.gateway(['transaction-show', tx])
    artifact = shown.get('artifact', {})
    if (shown.get('transaction_id') != tx or shown.get('artifact_hash') != canonical_digest(artifact)
            or not approve_transition_scalar_preview(artifact, version=ctx.version, value=expected) or snapshot() != before):
        raise CaseBoundaryError('Transition Preview is not the unchanged-baseline exact boolean change')
    token = shown.get('confirmation', {}).get('token')
    if shown.get('state') != 'awaiting_confirmation' or not isinstance(token, str) or not token:
        raise CaseBoundaryError('Transition Preview has no explicit confirmation')
    if ctx.gateway(['confirm', tx, '--confirmation-token', token]).get('state') != 'confirmed':
        raise CaseBoundaryError('Transition confirmation failed')
    if ctx.gateway(['execute', tx]).get('state') != 'executed_unverified':
        raise CaseBoundaryError('Transition execute failed; no retry or save')
    verified = ctx.gateway(['verify', tx])
    if verified.get('state') != 'verified' or verified.get('verification', {}).get('business_state_verified') is not True or _boolean(ctx) is not expected:
        raise CaseBoundaryError('Transition boolean lacks strong public verification')
    save_tx = _save_owned(ctx)
    if save_tx == tx:
        raise CaseBoundaryError('Transition edit and owned save must have distinct transactions')
    after = snapshot()
    assertions = verify_transition_scalar_goal(before, after, witness, default=before['value'])
    if not all(assertions.values()):
        raise CaseBoundaryError(f'Transition independent saved graph or media changed: {assertions}')
    return {'transaction_ids': [tx, save_tx], 'assertions': assertions, 'status': 'PASS',
        'before': before, 'after': after, 'scalar_maintenance_verified': True, 'agent_pass': False,
        'complete_M04_verified': False, 'saved_order_source': 'owned_version_pinned_WWU',
        'save_verifier_strength': 'result_schema_checked_plus_independent_owned_XML_readback'}
