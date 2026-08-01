"""Small pure-Python compatibility fallback for the ``editdistance`` package.

FunASR imports ``editdistance.eval`` during startup.  The published extension
does not currently ship a CPython 3.13 Windows wheel, so this local module
keeps optional ASR usable without forcing users to install a C++ toolchain.
"""
from __future__ import annotations


def eval(left, right) -> int:
    """Return the Levenshtein distance between two iterable sequences."""
    if left == right:
        return 0
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_value in enumerate(left, 1):
        current = [left_index]
        for right_index, right_value in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + (left_value != right_value),
            ))
        previous = current
    return previous[-1]
