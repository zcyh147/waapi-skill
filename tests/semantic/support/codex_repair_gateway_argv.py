"""Parser-validated command projection; authenticated invocation bytes stay intact."""
from tests.semantic.support.codex_expansion_policy import ExpansionPolicyError

_OFFLINE = frozenset({"operations", "query-schema", "operation-schema", "request-schema"})


def repair_command_argv(argv, *, parser, version):
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
    prefixes = (("--version", version), ("--wwise-version", version),
                ("--version=" + version,), ("--wwise-version=" + version,))
    for prefix in prefixes:
        if values[:len(prefix)] == prefix and values[len(prefix):len(prefix)+1] == (args.command,):
            if args.command in _OFFLINE and args.version == version:
                return values[len(prefix):]
    raise ExpansionPolicyError("only the sealed version may prefix offline repair catalog/schema commands")
