"""RJClip backend (formerly ClipForge)."""
import os as _os

# Settings from before the rename (CLIPFORGE_*) keep working: copy each to its RJCLIP_*
# name unless that is set too. Done here so it happens before any module reads them.
for _k, _v in list(_os.environ.items()):
    if _k.startswith("CLIPFORGE_"):
        _os.environ.setdefault("RJCLIP_" + _k[len("CLIPFORGE_"):], _v)
