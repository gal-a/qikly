"""
Make stdout carry UTF-8, whatever the console's codepage is.

On Windows, Python encodes stdout using the console codepage, which is
typically cp1252. That is fine while everything is ASCII and wrong the moment
it is not, in a way that only shows up in a file:

    qikly --criteria-from ticket.md >> inputs_private/config/tasks/MY_TASK.yaml

is a documented workflow. With a euro sign, an accent or an em dash in a
criterion, cp1252 writes byte 0x80 where UTF-8 wants three bytes, and the task
file that comes out cannot be decoded by any UTF-8 reader, including qikly's
own, which opens task files as UTF-8 by name.

The corruption is invisible at the terminal, because the same console that
wrote the bytes reads them back consistently. It surfaces later, as a task that
mysteriously will not parse.

So every entry point that prints something a person might redirect reconfigures
its streams first. `errors="replace"` because a display problem must never be
the thing that ends a run: a character that cannot be represented becomes a
replacement mark rather than a traceback.

Files were never affected. Everything qikly writes to disk already names
`encoding="utf-8"` explicitly, for the same reason and after the same kind of
bug: a model's em dash once reached a reader as a lone 0x97 because a patch was
written in cp1252 and read back as UTF-8.
"""
import sys


def use_utf8():
    """
    Idempotent, and never raises.

    Called at the top of each entry point rather than at import, because a
    library that reconfigures a process's streams on import is a library that
    surprises whoever imported it.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if getattr(stream, "encoding", "").lower().replace("-", "") != "utf8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # A stream that cannot be reconfigured (already wrapped, replaced
            # by a test harness, or closed) is left as it is. Correct output is
            # worth having; it is not worth failing a run over.
            pass
