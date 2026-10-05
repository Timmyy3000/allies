import pytest

from allies_runtime import files


@pytest.fixture
def root_owned_publication_spool(monkeypatch):
    if files.os.name != "nt":

        def state_root(root):
            path = root / files._PUBLICATION_STATE_DIRECTORY
            path.mkdir(parents=True, exist_ok=True)
            return path

        def publication_directory(path, *, create):
            if not path.exists():
                if not create:
                    return False
                path.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or not path.is_dir():
                raise files.IncomingFileError("publication spool was unsafe")
            return True

        def publication_file_metadata(path):
            if not path.exists():
                return None
            if path.is_symlink() or not path.is_file():
                raise files.IncomingFileError("publication spool was unsafe")
            return path.stat()

        monkeypatch.setattr(files.os, "chown", lambda *_args: None)
        monkeypatch.setattr(files, "_publication_state_root", state_root)
        monkeypatch.setattr(files, "_publication_directory", publication_directory)
        monkeypatch.setattr(
            files, "_publication_file_metadata", publication_file_metadata
        )
