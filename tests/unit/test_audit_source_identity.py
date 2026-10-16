"""Portable audit identities at the host-path to ledger-key boundary."""
from pathlib import PurePosixPath, PureWindowsPath
import pytest
from tests.maintenance.source_identity import repository_source_identity


@pytest.mark.parametrize("path,root", [
    (PurePosixPath('/repo/skills/Space & 世界/module.py'), PurePosixPath('/repo')),
    (PureWindowsPath(r'C:\Repo\skills\Space & 世界\module.py'), PureWindowsPath('c:/repo')),
    (PureWindowsPath(r'C:/Repo\skills/Space & 世界\module.py'), PureWindowsPath(r'C:\Repo')),
    (PureWindowsPath(r'\\Server\Share\Repo\skills\Space & 世界\module.py'), PureWindowsPath(r'\\server\share\repo')),
])
def test_repository_source_keys_are_host_independent(path, root):
    assert repository_source_identity(path, root) == 'skills/Space & 世界/module.py'


@pytest.mark.parametrize("path,root", [
    (PurePosixPath('/Repo/a.py'), PurePosixPath('/repo')),
    (PurePosixPath('/repo/../other/a.py'), PurePosixPath('/repo')),
    (PureWindowsPath(r'C:\Repo\..\other\a.py'), PureWindowsPath(r'C:\Repo')),
    (PureWindowsPath(r'D:\Repo\a.py'), PureWindowsPath(r'C:\Repo')),
    (PureWindowsPath(r'\\server\other\repo\a.py'), PureWindowsPath(r'\\server\share\repo')),
])
def test_outside_repository_or_traversing_sources_cannot_be_ledger_keys(path, root):
    with pytest.raises(ValueError):
        repository_source_identity(path, root)
