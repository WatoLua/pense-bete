#!/usr/bin/env python3
"""Pense-bête: sticky notes, one window per note, each versioned in its own git repository.

Each note is stored as a JSON file in its own directory, which is a git repository.
A note is saved (and committed) 10 seconds after its last modification, and
immediately when its window is closed. The application itself is the pensebete
package next to this script.
"""

from pensebete.app import main

if __name__ == "__main__":
    main()
