#!/usr/bin/env python

"""An entry-point that allows the module to be executed.
This also simplifies the distribution as this is the
entry-point for the console script (see setup.py).
"""

import sys
from jote.jote import main as jote_main


def main() -> int:
    """The entry-point of the component."""
    return jote_main()


if __name__ == "__main__":
    sys.exit(main())
