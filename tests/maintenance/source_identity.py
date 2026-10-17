"""Convert host filesystem paths to portable repository ledger identities."""
from pathlib import PurePath


def repository_source_identity(path: PurePath, root: PurePath) -> str:
    relative = path.relative_to(root)
    if not relative.parts or ".." in relative.parts:
        raise ValueError("source identity must name a file inside the repository")
    return relative.as_posix()
