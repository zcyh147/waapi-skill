"""One Console log-add event observation, owned by its execute process."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from time import monotonic

from .builders.schema import SemanticValidationError, validate_resolved_semantic_event
from .runtime_log_effects import MAX_LOG_OBSERVATION_BYTES
from .subscriptions import (
    DEFAULT_WAIT_TIMEOUT, MAX_WAIT_EVENT_COUNT, SubscriptionManager,
    SubscriptionStreamIngressError, SubscriptionStreamOverflow,
)

TOPIC = 'ak.wwise.core.log.itemAdded'
CONTRACT = 'waapi-skill.console-log-add-observation/v1'


def matches(payload: Mapping, plan: Mapping) -> bool:
    return (payload['channel'] == plan['channel']
        and payload['item']['message'] == plan['message']
        and payload['item']['severity'] == plan['severity'])


def observe_console_log_add(*, client, plan: Mapping, dispatch_once: Callable,
                            remaining: Callable[[], float]) -> dict:
    """Queue before dispatch, observe within bounds, and close before returning.

    Observer facts are siblings of the native result, never native result fields.
    The caller already owns authorization and the durable execution-attempt state.
    """
    observation = {'contract': CONTRACT, 'topic': TOPIC, 'subscribed': False,
        'outcome': 'subscription_failed', 'events_observed': 0,
        'cleanup': {'status': 'not_established'}}
    result = {'ok': False, 'error_code': 'LOG_OBSERVER_SUBSCRIPTION_FAILED',
        'message': 'Console log observer could not subscribe before the add.',
        'native_dispatch_attempted': False}
    stream = None
    try:
        stream = SubscriptionManager(client).open_stream(TOPIC, options={},
            queue_size=MAX_WAIT_EVENT_COUNT, max_event_bytes=MAX_LOG_OBSERVATION_BYTES)
        observation['subscribed'] = True
        observation['outcome'] = 'native_call_failed'
        result = dispatch_once()
        if result.get('ok') is True:
            deadline = monotonic() + min(DEFAULT_WAIT_TIMEOUT, max(0.0, remaining()))
            observation['outcome'] = 'timeout'
            while observation['events_observed'] < MAX_WAIT_EVENT_COUNT:
                event = stream.poll(timeout=max(0.0, deadline - monotonic()))
                if event is None:
                    observation['outcome'] = ('no_matching_event' if observation['events_observed'] else 'timeout')
                    break
                observation['events_observed'] += 1
                payload = event.payload
                validate_resolved_semantic_event(TOPIC, payload, version=plan['version'])
                if matches(payload, plan):
                    observation.update(outcome='matched', event=payload)
                    break
            else:
                observation['outcome'] = 'event_limit'
    except SemanticValidationError as exc:
        observation.update(outcome='malformed_event', error=str(exc)[:512])
    except SubscriptionStreamOverflow:
        observation['outcome'] = 'overflow'
    except SubscriptionStreamIngressError as exc:
        observation.update(outcome='invalid_event_ingress', error_code=exc.error_code)
    except Exception as exc:
        observation['error'] = {'type': type(exc).__name__, 'message': str(exc)[:512]}
        # A native exception may have followed dispatch; preserve that uncertainty.
        if stream is not None and result.get('native_dispatch_attempted') is False:
            result = {'ok': False, 'error_code': 'LOG_ADD_DISPATCH_FAILED',
                'message': 'Console log add outcome is unknown.', 'automatic_retry': False}
    finally:
        if stream is not None:
            try:
                cleaned = stream.close()
                observation['cleanup'] = {'status': 'unsubscribed' if cleaned else 'unsubscribe_failed'}
            except Exception as exc:
                observation['cleanup'] = {'status': 'unsubscribe_failed',
                    'error': {'type': type(exc).__name__, 'message': str(exc)[:512]}}
            else:
                if cleaned:
                    # Callbacks may overflow while unsubscribe is in flight.
                    # A nonblocking poll checks the final ingress health; any
                    # extra queued item is outside the completed matching wait.
                    try:
                        stream.poll(timeout=0)
                    except SubscriptionStreamOverflow:
                        observation['outcome'] = 'overflow'
                    except SubscriptionStreamIngressError as exc:
                        observation.update(outcome='invalid_event_ingress', error_code=exc.error_code)
    return {**result, 'log_item_observation': observation}


def event_observation(execution: Mapping, plan: Mapping) -> dict:
    """Validate the durable event again against this Preview's exact request."""
    observed = execution.get('log_item_observation')
    base = {'channel': plan['channel'], 'exclusive_causation_verified': False,
        'continuing_channel_state_verified': False, 'entry_identity_verified': False,
        'effect_observed': False}
    if not isinstance(observed, Mapping) or observed.get('contract') != CONTRACT or observed.get('topic') != TOPIC:
        return {**base, 'outcome': 'console_event_observation_missing'}
    result = {**base, 'outcome': observed.get('outcome'), 'execution_observation': dict(observed)}
    if observed.get('cleanup', {}).get('status') != 'unsubscribed':
        return {**result, 'outcome': 'console_event_cleanup_failed'}
    if observed.get('subscribed') is not True or observed.get('outcome') != 'matched':
        return result
    payload = observed.get('event')
    validate_resolved_semantic_event(TOPIC, payload, version=plan['version'])
    if not matches(payload, plan):
        return {**result, 'outcome': 'console_event_mismatch'}
    return {**result, 'outcome': 'matching_item_event', 'effect_observed': True}
