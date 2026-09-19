"""The doctest gate: pytest's configuration must agree with what CI runs.

Two ways a package's own doctests stop running without anything going red, both
of which had happened here:

1. **CI passes no path.** This repo's ``.github/workflows/ci.yml`` calls
   ``i2mint/wads/.github/workflows/uv-ci.yml``, whose Linux **and** Windows test
   jobs both use the ``run-tests-uv`` action. That action builds
   ``pytest --doctest-modules -o doctest_optionflags=...`` and never names a
   directory, so pytest falls back to ``testpaths``. With ``testpaths =
   ["tests"]`` the collector never descends into ``burns/`` and every ``>>>`` in
   the package is invisible — a green tick over zero module doctests.

   (wads also ships a ``windows-tests`` action that *does* pass a path, which is
   why a reader can conclude the Windows leg was already covered. ``uv-ci.yml``
   does not use it — verified at its lines 385 and 451, both ``run-tests-uv``.)
2. **CI overrides the flags.** ``-o`` replaces the whole ini key, so a doctest
   written against a flag the ini sets and CI does not (``NORMALIZE_WHITESPACE``
   was the one) passes on a laptop and fails on the runner.

These tests read the configuration pytest actually resolved, so they fail if
either drifts again.
"""

import burns

#: Exactly what wads' run-tests-uv action passes with `-o`.
CI_DOCTEST_OPTIONFLAGS = ("ELLIPSIS", "IGNORE_EXCEPTION_DETAIL")


def test_the_package_is_on_the_default_collection_path(pytestconfig):
    """Without this, `pytest --doctest-modules` (CI's command) skips burns/."""
    testpaths = pytestconfig.getini("testpaths")
    assert "burns" in testpaths, (
        "burns/ is not in testpaths, so CI's pathless `pytest --doctest-modules` "
        f"collects only {testpaths} and no module doctest runs."
    )


def test_the_doctest_flags_match_what_ci_passes(pytestconfig):
    """`-o` replaces the ini key wholesale, so the two must be identical."""
    assert tuple(pytestconfig.getini("doctest_optionflags")) == CI_DOCTEST_OPTIONFLAGS


def test_the_public_moves_surface_carries_doctests():
    """A named-move resolver whose examples never run is documentation, not a test."""
    import burns.moves

    documented = [
        obj
        for obj in (burns.moves.resolve_move, burns.moves.choose_move)
        if ">>>" in (obj.__doc__ or "")
    ]
    assert len(documented) == 2
    assert ">>>" in (burns.moves.__doc__ or "")
