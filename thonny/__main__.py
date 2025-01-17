import sys
import runpy

if sys.executable.endswith("thonny.exe"):
    # otherwise some library may try to run its subprocess with thonny.exe
    # NB! Must be pythonw.exe not python.exe, otherwise Runner thinks console
    # is already allocated.
    sys.executable = sys.executable[: -len("thonny.exe")] + "pythonw.exe"

from thonny import launch, check_initialization

try:
    runpy.run_module("thonny.customize", run_name="__main__")
except ImportError:
    pass

if check_initialization():
    launch()
