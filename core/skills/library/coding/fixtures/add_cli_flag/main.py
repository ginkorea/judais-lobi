"""The command line."""

import argparse

from handler import render


def build_parser():
    """The argument parser, built where a test can reach it."""
    parser = argparse.ArgumentParser(prog="greet")
    parser.add_argument("--name", default="world",
                        help="who to greet")
    return parser


def main(argv=None):
    """Parse *argv* and return the line, rather than printing it."""
    args = build_parser().parse_args(argv)
    return render(args.name)


if __name__ == "__main__":  # pragma: no cover
    print(main())
