"""Package for the embedded repo tool.

Public API
----------
run_from_args(argv, *, repo_dir)
    Run a repo subcommand from Python code without persistently modifying
    global process state (sys.argv, os.execv, os.environ). The function
    temporarily replaces os.execv and may temporarily write to os.environ
    during execution, but restores both in a finally block. See
    main.run_from_args for the full contract.

RepoCommandError
    Exception raised when the underlying repo command exits with an error.
    Carries the integer exit_code from the original SystemExit.
"""

from kanon_cli.repo.main import RepoCommandError
from kanon_cli.repo.main import run_from_args

__all__ = ["RepoCommandError", "run_from_args"]
