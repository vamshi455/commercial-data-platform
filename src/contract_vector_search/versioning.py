"""Amendment / version decision logic — PURE PYTHON, unit-testable.

The gold task collects the (small) set of currently-active contracts and the
incoming contracts to the driver and calls :func:`detect_amendments` to decide
which contract_ids are being superseded and what version the incoming chunks get.
Keeping this out of Spark makes the amendment rule testable without a cluster and
guarantees the notebook and the tests apply the exact same rule.
"""

from __future__ import annotations

from collections import defaultdict


def detect_amendments(
    current: list[tuple[str, str, int]],
    incoming: list[tuple[str, str]],
) -> dict[str, int]:
    """Return ``{contract_id: new_version}`` for contracts being amended.

    A contract_id is *amended* when an incoming file references it under a
    ``source_file`` that differs from every currently-active file for that id.
    The new version is ``max(current version for that id) + 1``.

    Args:
        current:  active gold rows as ``(contract_id, source_file, version)``.
        incoming: incoming rows as ``(contract_id, source_file)``.
    """
    cur_files: dict[str, set[str]] = defaultdict(set)
    cur_maxver: dict[str, int] = defaultdict(int)
    for cid, sf, ver in current:
        if cid is None:
            continue
        cur_files[cid].add(sf)
        cur_maxver[cid] = max(cur_maxver[cid], ver or 1)

    bumps: dict[str, int] = {}
    for cid, sf in incoming:
        if cid is None or cid not in cur_files:
            continue  # brand-new contract -> stays version 1, not an amendment
        if sf not in cur_files[cid]:
            bumps[cid] = cur_maxver[cid] + 1
    return bumps
