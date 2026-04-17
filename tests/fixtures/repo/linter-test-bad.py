# Known-bad Python file for testing ruff linter configuration.
# This file intentionally contains lint violations that ruff should catch.
# DO NOT fix these — they exist to verify the linter config works.

import os  # F401: unused import
import sys  # F401: unused import


def unused_variable_example():
    x = 42  # F841: local variable is assigned but never used
    return None
