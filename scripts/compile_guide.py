#!/usr/bin/env python3
"""Compile source-ledger guide JSON; does not render or change source materials."""
import argparse
import json
from pathlib import Path
import sys
from score_sync.guide import compile_guide


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--movement-dir', required=True, type=Path)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or args.movement_dir / 'guide.json'
    try:
        payload = compile_guide(args.input, args.movement_dir, output)
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps({'output': str(output.resolve()), 'blocks': len(payload['blocks']),
                      'connection_windows': len(payload['connection_windows']),
                      'coverage_complete': payload['coverage']['complete']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
