"""Read the canonical local IM app; publish only its reviewed xtdata snapshot."""
from __future__ import annotations
import copy
import importlib.util
import json
import os
from pathlib import Path


def load_im_term_snapshot(previous=None):
    try:
        vault = Path(os.environ.get("IM_THRESHOLD_VAULT", r"D:\思维知识库"))
        script = vault / "90_Agent指令/scripts/update_im_thresholds.py"
        spec = importlib.util.spec_from_file_location("published_im_threshold_reader", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        history_spec = importlib.util.spec_from_file_location("publisher_im_history", Path(__file__).with_name("im_term_history.py"))
        history_reader = importlib.util.module_from_spec(history_spec)
        history_spec.loader.exec_module(history_reader)
        snapshot, _ = module.make_snapshot(module.load(module.STATE / "metadata.json"), "shared_cache",
                                          term_history_builder=history_reader.build_history_queries)
        assert snapshot["imMetadata"]["sourceOnly"] == "xtdata"
        assert snapshot["imMetadata"]["extremeDisplayMethod"] == "current_pair_lifetime"
        assert snapshot["queries"]["latest"]["rows"]
        for row in snapshot["queries"]["latest"]["rows"]:
            assert row["lowerAnnualRatePct"] == 9 and row["upperAnnualRatePct"] == 12
            assert row["extremeScope"] == "current_pair_lifetime"
        snapshot["buildStatus"] = "complete"
        # Public provenance retains exact dataset identities and file hashes,
        # while machine-specific absolute directories stay on the local app.
        for query in snapshot["queries"].values():
            query["source"]["files"] = [Path(name).name for name in query["source"].get("files", [])]
        metadata = snapshot["imMetadata"]
        metadata.pop("sharedRoot", None)
        for collection in ("records", "termHistoryRecords"):
            for record in metadata.get(collection, []):
                record["path"] = Path(record["path"]).name
        return snapshot
    except Exception:
        if previous and previous.get("queries", {}).get("latest", {}).get("rows"):
            snapshot = copy.deepcopy(previous)
            snapshot["status"] = "stale"
            snapshot["buildStatus"] = "complete"
            for row in snapshot["queries"]["latest"]["rows"]:
                row["stale"] = True
                row["lastRefreshStatus"] = "xtdata_unavailable"
            return snapshot
        raise RuntimeError("IM xtdata snapshot unavailable and no prior valid snapshot exists") from None


def attach_im_term_snapshot(payload, output_path):
    previous = None
    if Path(output_path).exists():
        previous = json.loads(Path(output_path).read_text(encoding="utf-8")).get("imTerm")
    payload["imTerm"] = load_im_term_snapshot(previous)
    return payload
