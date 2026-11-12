"""QtGui plugin policy for this Widgets-only application.

Filter before PyInstaller's binary dependency walk can pull in unused modules.
The normal upstream Qt hook still resolves all other QtGui requirements.
"""
from pathlib import Path
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [(source, destination) for source, destination in binaries
            if not any(name in Path(source).name.lower()
                       for name in ('virtualkeyboard', 'qpdf'))]
