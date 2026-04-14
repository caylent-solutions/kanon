"""Auto-discover the .kanon configuration file by walking up the directory tree.

Searches from a starting directory (default: current working directory) upward
through parent directories until a .kanon file is found or the filesystem root
is reached.
"""

from pathlib import Path

from kanon_cli.constants import KANONENV_FILENAME


def find_kanonenv(start_dir: Path | None = None) -> Path:
    """Walk up from start_dir looking for a .kanon file.

    Args:
        start_dir: Directory to start searching from. Defaults to the
            current working directory.

    Returns:
        Absolute path to the nearest .kanon file.

    Raises:
        FileNotFoundError: If no .kanon file is found between start_dir
            and the filesystem root.
    """
    current = (start_dir or Path.cwd()).resolve()

    while True:
        candidate = current / KANONENV_FILENAME
        if candidate.is_file():
            return candidate

        parent = current.parent
        if parent == current:
            break
        current = parent

    msg = (
        f"No {KANONENV_FILENAME} file found in {start_dir or Path.cwd()} "
        f"or any parent directory.\n"
        f"Run 'kanon bootstrap kanon' to create one, or pass an explicit path."
    )
    raise FileNotFoundError(msg)
