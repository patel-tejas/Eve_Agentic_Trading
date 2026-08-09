"""Phase 02+03: process a harvest month into timeframes + indicators."""

from __future__ import annotations

import argparse

from quant.processing.pipeline import process_month


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--timeframes", default="1,5,15", help="comma-separated minutes")
    args = parser.parse_args()

    tfs = tuple(int(x) for x in args.timeframes.split(",") if x.strip())
    result = process_month(year=args.year, month=args.month, timeframes=tfs)
    for tf, info in result.items():
        if tf == "validation":
            print(f"validation: {info}")
        elif tf == "verification":
            for tf2, status in info.items():
                print(f"verify {tf2}: {status}")
        else:
            print(f"{tf}: {info['bars']} bars -> {info['path']}")


if __name__ == "__main__":
    main()
