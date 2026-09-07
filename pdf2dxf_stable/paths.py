"""Protect caller-owned inputs from report and artifact destinations."""

from pathlib import Path


def same_path(left, right):
    left, right = Path(left).expanduser().resolve(), Path(right).expanduser().resolve()
    return left == right or (left.exists() and right.exists() and left.samefile(right))


def protect_inputs(destination, inputs):
    for source in inputs:
        if source and same_path(destination, source):
            raise ValueError(
                f"output must not overwrite an input or artifact: {destination}"
            )


def result_paths(result):
    """Read artifact paths from conversion, batch and regression result envelopes."""
    if not isinstance(result, dict):
        return
    for key in ("source", "report_path", "conversion_report"):
        if result.get(key):
            yield result[key]
    for artifact in result.get("artifacts", ()):
        if artifact.get("path"):
            yield artifact["path"]
    for key in ("jobs", "documents", "runs"):
        for child in result.get(key, ()):
            yield from result_paths(child)
    if "result" in result:
        yield from result_paths(result["result"])
