#!/usr/bin/env python3
"""Measure business-domain extraction without invoking semantic synthesis."""
import argparse
import json
import sys
from pathlib import Path

SPEED_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPEED_ROOT))

from lib.context.business_domain_extract import (  # noqa: E402
    Extractor, extraction_measurements,
)
from lib.context.business_domain_schema import settings  # noqa: E402
from lib.context.utils import load_speed_toml  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--repo', type=Path)
    source.add_argument('--read', type=Path, metavar='FACTS_JSON')
    parser.add_argument('--out', type=Path, metavar='FACTS_JSON')
    args = parser.parse_args()

    if args.read:
        facts = json.loads(args.read.read_text())
    else:
        root = args.repo.resolve()
        config = settings(load_speed_toml(str(root)))
        facts, _ = Extractor(root, config).extract()
        if args.out:
            args.out.write_text(json.dumps(facts, sort_keys=True))
    print(json.dumps(extraction_measurements(facts), sort_keys=True,
                     separators=(',', ':')))


if __name__ == '__main__':
    main()
