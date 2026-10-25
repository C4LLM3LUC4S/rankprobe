"""A rejected MTEB score must identify the source entry to inspect."""

import ast
import json
from pathlib import Path
import re

import pytest


DOC = Path(__file__).resolve().parents[1] / "docs" / "mteb-workflow.md"
SUBSET = "community,subset"
SPLIT = "validation"


def bridge(source, destination):
    blocks = re.findall(r"```python\n(.*?)```", DOC.read_text(encoding="utf-8"), re.S)
    code = next(block for block in blocks if "def unique_keys" in block)
    tree = ast.parse(code)
    values = {
        "source": ast.parse(f"Path({str(source)!r})", mode="eval").body,
        "destination": ast.parse(f"Path({str(destination)!r})", mode="eval").body,
        "subset": ast.Constant(SUBSET),
        "split": ast.Constant(SPLIT),
    }
    changed = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in values:
                node.value = values[name]
                changed.add(name)
    assert changed == set(values)
    return compile(ast.fix_missing_locations(tree), str(DOC), "exec")


def predictions(query, document, score):
    return {
        "mteb_model_meta": {"model_name": "metadata-not-for-error", "revision": None},
        SUBSET: {SPLIT: {"q-first": {"doc-first": 0.7}, query: {document: score}}},
        "other-scope": {"test": {"unselected-private-query": {"unselected-doc": 99}}},
    }


@pytest.mark.parametrize("query,document,score,detail", [
    ("q-second", "doc-invalid", "bad", "score must be a finite number"),
    ("q-second", "doc-invalid", True, "score must be a finite number"),
    ("q-second", "doc-invalid", None, "score must be a finite number"),
    ("", "doc-invalid", 0.2, "query_id must be a non-empty string"),
    ("q-second", "", 0.2, "item_id must be a non-empty string"),
])
def test_error_locates_pair_without_echoing_metadata_or_touching_old_csv(
    tmp_path, query, document, score, detail
):
    source = tmp_path / "original predictions.json"
    destination = tmp_path / "old scores.csv"
    original = json.dumps(predictions(query, document, score)).encode()
    source.write_bytes(original)
    destination.write_bytes(b"Keep existing CSV\n")

    with pytest.raises(ValueError) as failed:
        exec(bridge(source, destination), {"__name__": "__main__"})

    message = str(failed.value)
    for part in (str(source), f"subset={SUBSET!r}", f"split={SPLIT!r}",
                 f"query={query!r}", f"document={document!r}"):
        assert part in message
    assert detail in message
    assert "metadata-not-for-error" not in message
    assert "unselected-private-query" not in message
    assert source.read_bytes() == original
    assert destination.read_bytes() == b"Keep existing CSV\n"


def test_new_source_and_destination_retry_retains_scope_values_and_unknowns(tmp_path):
    from rankprobe.io import read_predictions

    original_source = tmp_path / "original.json"
    original = json.dumps(predictions("q-second", "doc-invalid", "bad")).encode()
    original_source.write_bytes(original)
    old_csv = tmp_path / "old.csv"
    old_csv.write_bytes(b"Keep old export\n")
    with pytest.raises(ValueError):
        exec(bridge(original_source, old_csv), {"__name__": "__main__"})

    new_source = tmp_path / "new source.json"
    corrected = json.dumps(predictions("q-second", "doc-invalid", 9007199254740993)).encode()
    new_source.write_bytes(corrected)
    new_csv = tmp_path / "new scores.csv"
    exec(bridge(new_source, new_csv), {"__name__": "__main__"})
    rows = read_predictions(new_csv)
    assert [(row.query_id, row.item_id, row.score, row.relevance) for row in rows] == [
        ("q-first", "doc-first", 0.7, None),
        ("q-second", "doc-invalid", 9007199254740993, None),
    ]
    assert type(rows[1].score) is int
    assert original_source.read_bytes() == original
    assert new_source.read_bytes() == corrected
    assert old_csv.read_bytes() == b"Keep old export\n"
