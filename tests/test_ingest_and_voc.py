import json
import shutil

from marketplace import ingest
from marketplace.analysis.voc import macro_f1
from marketplace.analysis.voc_prompt import LABELS
from marketplace.paths import MANIFEST, ROOT


def test_manifest_matches_published_counts():
    m = json.loads(MANIFEST.read_text())
    for name, meta in m["tables"].items():
        assert meta["rows"] == ingest.PUBLISHED_ROW_COUNTS[name], name
        assert len(meta["sha256"]) == 64


def test_verify_detects_tampering(tmp_path, monkeypatch):
    m = json.loads(MANIFEST.read_text())
    src = ingest.RAW / m["tables"]["category_translation"]["file"]
    if not src.exists():
        return
    small = {
        "dataset": m["dataset"],
        "tables": {"category_translation": m["tables"]["category_translation"]},
    }
    (tmp_path / "product_category_name_translation.csv").write_bytes(src.read_bytes() + b"x,y\n")
    monkeypatch.setattr(ingest, "RAW", tmp_path)
    problems = ingest.verify(small)
    assert any("sha256" in p for p in problems)
    shutil.rmtree(tmp_path)


def test_taxonomy_and_gold():
    assert len(LABELS) >= 7
    gold = ROOT / "artifacts" / "voc_gold_labels.csv"
    lines = gold.read_text().strip().splitlines()[1:]
    assert len(lines) >= 200
    assert {line.split(",")[1] for line in lines} <= set(LABELS)


def test_macro_f1_toy():
    import pandas as pd

    f1, per = macro_f1(pd.Series(["a", "a", "b"]), pd.Series(["a", "b", "b"]))
    assert abs(per["a"]["f1"] - 2 / 3) < 1e-12 and abs(f1 - 2 / 3) < 1e-12


def test_rescore_with_silver_labels_gives_full_agreement(tmp_path, capsys):
    import pandas as pd

    from marketplace.analysis.voc import cmd_rescore

    t = pd.read_csv(ROOT / "artifacts" / "voc_author_verification_template.csv")
    silver = pd.read_csv(ROOT / "artifacts" / "voc_gold_holdout_labels.csv").set_index("review_key")
    t["author_label"] = t.review_key.map(silver.gold_label)
    f = tmp_path / "filled.csv"
    t.to_csv(f, index=False)
    cmd_rescore(str(f))
    assert "silver vs author: 1.000" in capsys.readouterr().out
