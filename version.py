"""Intermission's version: the VERSION file next to the tools, major.minor.patch.
Bump it with release.py, never by hand: the tag and the changelog go with it."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "VERSION")


def read():
    try:
        return open(FILE).read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


if __name__ == "__main__":
    print(read())
