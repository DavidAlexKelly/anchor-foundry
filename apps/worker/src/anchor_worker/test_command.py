"""How a repository's unit tests are run, in either place they run (§890).

A test run is a person's code, run by pytest. In development it runs in a
subprocess of the worker (`python_sandbox.run_python_tests`). On a deployed
stack it runs in the transform runner's container (`transform_runner`), which
has no network and a task role that grants nothing. Until §890 it ran in the
worker there too, as the worker's own Unix user: a test could read
`/proc/1/environ` and find the database password and the path to the worker
role's credentials, which reach every workspace's connection secrets and the
whole data bucket.

The two places stage the directory and invoke pytest from this one module,
so a deployment runs the tests the way the development suite exercises them.
It imports nothing heavy: the runner loads it.
"""
from __future__ import annotations

import os

#: Where pytest writes its report, relative to the run's directory.
REPORT_FILE = "_report.xml"


class BadTarget(ValueError):
    """`target` is not a file of the working set."""


def stage(work_dir: str, files: dict[str, str], target: str | None) -> str:
    """Write the working set into `work_dir`, and return what pytest should
    collect, relative to it: `.` for every test, or the one file `target`
    names (§530)."""
    for path, content in files.items():
        # Not `target`: that is the parameter, and a loop that reused the
        # name handed pytest the last file written instead (§530).
        destination = os.path.join(work_dir, path)
        os.makedirs(os.path.dirname(destination) or work_dir, exist_ok=True)
        with open(destination, "w") as handle:
            handle.write(content)

    # **The configuration this run obeys, and the reason it is a file rather
    # than a flag.** pytest looks for an ini in the directory it was given and
    # then *upwards*, so without one here it finds whatever sits above the
    # working directory and applies it - which can be a checkout of this
    # repository, at which point our own settings reach a customer's tests. A
    # file in this directory is found first and ends the search. `--rootdir`
    # and `-c` were both tried and neither was the mechanism, which two
    # surviving mutants proved (§293). Written only when the repository did
    # not bring its own: a repository with a `pytest.ini` means it.
    config_path = os.path.join(work_dir, "pytest.ini")
    if not os.path.exists(config_path):
        with open(config_path, "w") as handle:
            handle.write("[pytest]\n")

    if target is None:
        return "."
    # The API normalised the path; this is the second guard, because the path
    # is written into a command line.
    root = os.path.realpath(work_dir)
    collect = os.path.realpath(os.path.join(work_dir, target))
    if not collect.startswith(root + os.sep) or not os.path.isfile(collect):
        raise BadTarget(f"{target} is not a file in this working set")
    return os.path.relpath(collect, root)


def command(python: str, collect: str) -> list[str]:
    """pytest, run from the run's directory.

    **That directory is the working directory, and that is load-bearing.**
    `python -m pytest` puts the directory it is invoked from first on
    `sys.path`, which is what makes `from src.daily import build` resolve to
    the repository's own file. There is no `PYTHONPATH`: it was set once, and
    deleting it changed nothing (§213).

    **`xunit1`, for `file` and `line`.** pytest 8's default family writes a
    dotted `classname` and nothing else, so the only way back to a path is to
    guess that dots are slashes - wrong the moment a test lives in a class.
    """
    return [python, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
            "-o", "junit_family=xunit1", f"--junitxml={REPORT_FILE}", collect]


def environment(home: str) -> dict[str, str]:
    """Nothing of the process that starts the tests: they see a path, a home
    and nothing else."""
    return {"PATH": "/usr/bin:/bin", "HOME": home, "PYTHONDONTWRITEBYTECODE": "1"}


def no_report(stdout: str, stderr: str) -> str:
    """Why a run left no report, in pytest's own last line: "No module named
    pytest" names the problem, and "your tests failed" would not."""
    tail = (stderr or stdout or "").strip().splitlines()
    return "the test run produced no report: " + (tail[-1] if tail else "no output")
