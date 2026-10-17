"""Parser-validated command projection; authenticated invocation bytes stay intact."""
from tests.semantic.support.codex_expansion_policy import ExpansionPolicyError

_OFFLINE = frozenset({"operations", "query-schema", "operation-schema", "request-schema"})


def repair_command_argv(argv, *, parser, version, initial_admission_rejected=False):
    values = tuple(argv)
    if not values or len(values) > 256:
        raise ExpansionPolicyError("runner owns global Gateway options and argv capacity")
    try:
        args = (parser.parse_args if hasattr(parser, "parse_args") else parser)(values)
    except (SystemExit, ValueError) as exc:
        raise ExpansionPolicyError("command does not satisfy the public Gateway parser") from exc
    if not values[0].startswith("-"):
        return values
    # Only the existing offline version selector may precede a repair command.
    # Parse first: neither an unknown flag nor its value can become a command.
    # A proved initial rejection is interpretation only: a wrong version or a
    # live read with a version prefix may explain an ordinary FAIL. It grants
    # neither dispatch permission nor business evidence.
    selected_version = args.version if initial_admission_rejected else version
    if not isinstance(selected_version, str) or not selected_version:
        raise ExpansionPolicyError("version selector must have a value")
    prefixes = (("--version", selected_version), ("--wwise-version", selected_version),
                ("--version=" + selected_version,), ("--wwise-version=" + selected_version,))
    for prefix in prefixes:
        if values[:len(prefix)] == prefix and values[len(prefix):len(prefix)+1] == (args.command,):
            if (initial_admission_rejected and args.command in _OFFLINE | {"status", "query-object", "metadata"}
                    or not initial_admission_rejected and args.command in _OFFLINE and args.version == version):
                return values[len(prefix):]
    raise ExpansionPolicyError("only the sealed version may prefix offline repair catalog/schema commands")
