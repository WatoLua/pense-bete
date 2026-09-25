#!/usr/bin/env python3
"""Pense-bête: sticky notes, one window per note, each versioned in its own git repository.

Each note is stored as a JSON file in its own directory, which is a git repository.
A note is saved (and committed) 10 seconds after its last modification, and
immediately when its window is closed. The application itself is the pensebete
package next to this script.
"""

import sys
from pathlib import Path

from pensebete.app import main, self_test

if __name__ == "__main__":
    # pense_bete.py --self-test <report>: check that a build starts, then quit.
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        sys.exit(self_test(Path(sys.argv[2])))
    main()
