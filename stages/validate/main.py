"""Validate stage: measure the dataset, block only what cannot be trained on.

The dataset is dirty by design, so this stage counts the mess and reports it
rather than refusing to work with it. It fails the run for exactly three
reasons, all of them "there is nothing here to train on".
"""

from __future__ import annotations

import os
import sys

from ml_common.stageio import emit_result
from ml_common.storage import Storage, extracted_key, validation_report_key
from ml_common.validation import validate_dataframe


def main() -> int:
    fingerprint = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    storage = Storage.from_env()

    df = storage.read_parquet(extracted_key(fingerprint))
    report = validate_dataframe(df, task_type)

    report_destination = validation_report_key(fingerprint)
    storage.write_json(report, report_destination)
    print(f"report written to {report_destination}", file=sys.stderr)
    print(f"rows={report['row_count']} duplicates={report['duplicate_rows']}", file=sys.stderr)

    for column_name, counts in sorted(report["columns"].items()):
        if counts["missing_rate"] > 0 or counts["out_of_bounds"] > 0:
            print(
                f"  {column_name}: missing={counts['missing_rate']:.1%} "
                f"out_of_bounds={counts['out_of_bounds']}",
                file=sys.stderr,
            )

    for reason in report["fatal"]:
        print(f"FATAL: {reason}", file=sys.stderr)

    emit_result({"ok": report["ok"], "row_count": report["row_count"]})
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
