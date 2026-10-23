"""Opt-in decoded EVENT counters for one existing public log-add transaction."""
from contextlib import ExitStack, contextmanager
from importlib.metadata import version as distribution_version
import os

TOPIC = 'ak.wwise.core.log.itemAdded'
ENV = 'WWISE_CONSOLE_LOG_DIAGNOSTIC'


def _replace(stack, owner, name, value):
    """Restore the exact prior instance/class attribute resolution on exit."""
    present = name in vars(owner)
    previous = vars(owner).get(name)
    stack.callback(setattr if present else delattr, owner, name, *([previous] if present else []))
    setattr(owner, name, value)


@contextmanager
def decoded_log_diagnostic(gateway, receipt, *, version):
    """Observe the acknowledged session only; delegate original methods once."""
    record = {'contract': 'waapi-skill.console-log-decoded-event-diagnostic/v1',
        'subscription_id': None, 'installed': False, 'decoded_events': 0,
        'callback_entries': 0, 'restored': False}
    receipt['delivery_diagnostic'] = record
    assert version == '2023.1' and os.getenv(ENV) == 'decoded-event-v1', 'Diagnostic opt-in requires its exact 2023.1 scope'
    assert distribution_version('waapi-client') == '0.8.1' and distribution_version('autobahn') == '24.4.2', 'Diagnostic dependency versions differ'
    from autobahn.asyncio.wamp import ApplicationSession
    from autobahn.wamp.message import Event
    from autobahn.wamp.request import Subscription
    from waapi.client.event import EventHandler
    assert callable(ApplicationSession.onMessage) and callable(EventHandler.on_event), 'Diagnostic hooks unavailable'
    factory = gateway.default_client_factory
    stack = ExitStack()
    created = 0

    def instrumented_factory(url):
        nonlocal created
        assert created < 8, 'Diagnostic client-decoration bound exceeded'
        created += 1
        client = factory(url)
        subscribe = client.subscribe

        def subscribed(uri, *args, **kwargs):
            assert uri != TOPIC or not record['installed'], 'Diagnostic owns only one log subscription'
            handler = subscribe(uri, *args, **kwargs)
            if uri != TOPIC:
                return handler
            try:
                assert isinstance(handler, EventHandler), 'Diagnostic requires the pinned EventHandler'
                subscription = handler.subscription
                assert isinstance(subscription, Subscription) and subscription.topic == TOPIC, 'Diagnostic subscription shape differs'
                assert type(subscription.id) is int and 0 < subscription.id <= 9007199254740992, 'Diagnostic subscription ID invalid'
                session = subscription.session
                assert isinstance(session, ApplicationSession), 'Diagnostic requires the acknowledged session'
                original_message = session.onMessage
                original_callback = handler._callback
                assert callable(original_message) and callable(original_callback), 'Diagnostic callable hooks unavailable'
                record['subscription_id'] = subscription.id

                def on_message(message):
                    if isinstance(message, Event) and message.subscription == subscription.id:
                        record['decoded_events'] = min(65, record['decoded_events'] + 1)
                    return original_message(message)

                def callback(*callback_args, **callback_kwargs):
                    record['callback_entries'] = min(65, record['callback_entries'] + 1)
                    return original_callback(*callback_args, **callback_kwargs)

                _replace(stack, session, 'onMessage', on_message)
                _replace(stack, handler, '_callback', callback)
                record['installed'] = True
            except BaseException:
                # The transport cannot own a handle that setup failed to return.
                # Close this already acknowledged subscription before failing.
                try:
                    record['setup_cleanup'] = handler.unsubscribe() is True
                except BaseException:
                    record['setup_cleanup'] = False
                raise
            return handler

        _replace(stack, client, 'subscribe', subscribed)
        return client

    try:
        _replace(stack, gateway, 'default_client_factory', instrumented_factory)
        yield
    finally:
        stack.close()
        record['restored'] = True
