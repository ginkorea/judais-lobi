# core/tools/root.py — the directory an in-process tool may touch

"""One owner of *"is this path inside the mission's root"*.

**The sandbox does not see the tools in this package.**  bwrap isolates a
*subprocess*: ``run_shell_command``, ``run_python_code`` and ``verify`` end
in one and are confined by it.  :class:`~core.tools.fs_tools.FsTool` is
pure ``pathlib`` in this process, :class:`~core.tools.patch_tool.PatchTool`
writes through the patch engine, and neither crosses a process boundary at
all — so under a profile that grants ``fs.write`` a mission could write
anywhere the user can, sandbox or no sandbox.  The coding pack said so out
loud in its README ("the repository root is a prompt-level rule, not an
enforced one") and its ``refuse_outside_root`` mission graded whether the
*agent* honoured it, which is a measurement of the model and not a
property of the harness.

This is the property.  A mission is a governed run: it is given an
objective, a closed set of tools and a working directory, and the working
directory is the whole of what it is working on.  So the tools a mission
is built with carry a root, and a path that resolves outside it is refused
by the tool itself.

**A refusal here is a tool result, not a capability refusal.**  The scope
was granted — this profile really may write files — and what is out of
bounds is the *path*.  So it comes back as ``(1, "", …)`` from the tool,
lands on the stream as an ordinary ``tool_result``, and the model reads it
and can correct itself in the next step.  A capability refusal would say
the mission may not write at all, which is false, and would teach a model
to stop trying rather than to stay inside.

**Chat keeps its root open.**  ``lobi --shell`` is a person at a prompt
asking for a file, and the file is wherever they say it is; there is no
objective and no mission directory to be inside of.  ``root=None`` — the
default everywhere — is exactly today's behaviour, so nothing that does
not ask for a root notices this module exists.

**There is no flag and no environment variable.**  The root *is* the
working directory the mission was started in, which is the same fact
``PatchTool``, ``RepoMapTool`` and ``load_project_config`` are already
built against; a second way of saying it would be a second thing to
disagree.  A mission that needs a different root is run from there.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

__all__ = ["MissionRoot", "rooted"]


class MissionRoot:
    """The one directory this mission's in-process tools may touch.

    Constructed from the mission's working directory and handed to the
    tools when the bus is built for a mission — see
    :class:`core.tools.Tools`.  Every tool asks the same question of it,
    which is what keeps four tools from having four ideas about what
    ``..`` means.
    """

    def __init__(self, root: Union[str, Path]):
        self.path = Path(root).expanduser().resolve()

    def __str__(self) -> str:                    # pragma: no cover - display
        return str(self.path)

    def __repr__(self) -> str:                   # pragma: no cover - display
        return f"<MissionRoot {self.path}>"

    def resolve(self, path: Union[str, Path],
                base: Optional[Union[str, Path]] = None) -> Path:
        """*path* as an absolute, symlink-free path.

        Relative to *base* when one is given and to the root otherwise —
        a patch's ``file_path`` is relative to the repository the engine
        was built against, and a mission's root is the same directory in
        every deployment this ships to, but the two are separate facts and
        the caller owns which one applies.

        ``os.path.realpath`` rather than ``Path.resolve`` for one reason
        that matters here: it resolves every symlink in the path,
        including in components that do not exist yet, which is the case a
        write creates.  A confinement that only followed links on paths
        that already exist would be a confinement a mission opens by
        writing through a link into a directory it then creates.
        """
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = Path(base) if base is not None else self.path
            candidate = candidate / Path(path)
        return Path(os.path.realpath(str(candidate)))

    def holds(self, path: Union[str, Path],
              base: Optional[Union[str, Path]] = None) -> bool:
        """Whether *path* resolves to the root itself or inside it."""
        resolved = self.resolve(path, base)
        return resolved == self.path or self.path in resolved.parents

    def refusal(self, path: Union[str, Path],
                base: Optional[Union[str, Path]] = None) -> str:
        """Why that path was refused, in the words the model is shown.

        It names **both** paths — the one that was asked for and the one
        it resolved to — because the two differ in every case worth
        refusing: ``../../etc/hosts`` and a symlink out of the tree both
        look local until they are resolved, and a refusal that echoed only
        what the model typed would read as the harness being wrong about
        it.
        """
        resolved = self.resolve(path, base)
        seen = f" (resolves to {resolved})" if str(resolved) != str(path) else ""
        return (
            f"outside the mission root {self.path}: {path}{seen}. Nothing "
            f"was read, written or deleted. Every path this mission may "
            f"touch is under that root; a mission that needs another root "
            f"is run from there."
        )

    def check(self, path: Union[str, Path],
              base: Optional[Union[str, Path]] = None) -> Optional[str]:
        """``None`` where *path* is inside the root, else the refusal.

        The shape every caller uses, so no tool writes the ``if`` twice::

            problem = rooted(self._root, path)
            if problem:
                return (1, "", problem)
        """
        if self.holds(path, base):
            return None
        return self.refusal(path, base)


def rooted(root: Optional[MissionRoot], path: Union[str, Path, None],
           base: Optional[Union[str, Path]] = None) -> Optional[str]:
    """:meth:`MissionRoot.check`, tolerant of the unrooted case.

    ``None`` for a tool with no root (chat, a library caller that asked
    for none) and for a call that names no path at all, so a tool's guard
    is one line whether or not it was built with a root.
    """
    if root is None or path is None or not str(path).strip():
        return None
    return root.check(path, base)
