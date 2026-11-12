"""Widget layer. Layout and presentation only; state and rules live in
remotehub.controller.AppController. See desktop/ARCHITECTURE.md."""
from .window import MainWindow
from .widgets import keys_sequence, sequence_keys

__all__ = ["MainWindow", "keys_sequence", "sequence_keys"]
