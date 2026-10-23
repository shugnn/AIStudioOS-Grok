import argparse
import sys
from .core import count_file

def main(argv=None):
    p = argparse.ArgumentParser(prog="wcmini", description="Tiny word count CLI")
    p.add_argument("files", nargs="*", help="files to count")
    args = p.parse_args(argv)
    if not args.files:
        p.print_help()
        return 0
    total = (0, 0, 0)
    for f in args.files:
        try:
            l, w, b = count_file(f)
        except FileNotFoundError:
            print(f"wcmini: {f}: No such file", file=sys.stderr)
            return 1
        print(f"{l:8d} {w:8d} {b:8d} {f}")
        total = (total[0]+l, total[1]+w, total[2]+b)
    if len(args.files) > 1:
        print(f"{total[0]:8d} {total[1]:8d} {total[2]:8d} total")
    return 0
