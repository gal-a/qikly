"""
Saying that a call is still in flight, so a wait is not read as a hang.

A model call prints nothing until it answers. On the default small model that
is a few seconds; on a reasoning model it is minutes, and during those minutes
a run looks exactly like a run that has died. People kill it. The first thing
they then report is that qikly hangs.

So while a call is out, this prints one line every few seconds saying how long
it has been waiting. Nothing clever: no spinner, no cursor tricks, no rewriting
of the line above.

## Why plain lines rather than a spinner

Because this output is read three ways and only one of them is a terminal. It
goes into `outputs/logs/`, it is captured by CI, and it is read by whatever
agent is driving the CLI through a Skill. Carriage returns and escape codes
turn all three into noise, and a log full of `\\r` is worse than a log with no
progress at all.

## Why it is on stderr

The run's own report lines are stdout, and something downstream may yet parse
them. A heartbeat is not a result, so it goes where diagnostics go, and a
caller that only wants results can drop it without losing anything.

## What it never does

It never claims progress it cannot see. The provider gives no token stream
here, so "still waiting, 30s" is the whole truth available, and inventing a
percentage would be the kind of made-up reassurance this project exists to
argue against.
"""
import os
import sys
import threading
import time

# The first tick waits this long, so a fast call stays silent. Under the
# default model most calls finish inside this and nothing is printed at all.
FIRST_TICK_SECONDS = 10.0

# Then one line at this interval. Slow enough that a five-minute call produces
# a readable handful of lines rather than a wall.
TICK_SECONDS = 15.0

# The environment variable that turns it off, for anyone whose log collector
# hates it.
OFF_ENV = "QIKLY_NO_PROGRESS"


def enabled():
    value = (os.environ.get(OFF_ENV) or "").strip().lower()
    return value not in ("1", "true", "yes", "on")


class Heartbeat(object):
    """
    One line every few seconds while something slow is happening.

    A daemon thread, so Ctrl+C is never held up by it: the process can exit
    with the timer still pending and nothing is left to join. Stopping is a
    single Event, which is also what makes the wait interruptible rather than
    a sleep that has to run to the end.
    """

    def __init__(self, label, stream=None, first=FIRST_TICK_SECONDS,
                 interval=TICK_SECONDS):
        self.label = label
        self.stream = stream if stream is not None else sys.stderr
        self.first = first
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self.ticks = 0

    def _label(self):
        """
        The call's stage, and the task when one process is one task.

        A sweep runs thirteen tasks at once and prefixes each task's stdout
        with its name. The heartbeat goes to stderr, which is not prefixed, so
        thirteen concurrent runs produced thirty-nine lines reading
        "[test_integration] still waiting" with nothing to say whose they
        were. A single run has no ambiguity to fix, but the sweep is how this
        project's own measurements are taken.
        """
        task = (os.environ.get("QIKLY_TASK_ID") or "").strip()
        return "%s %s" % (task, self.label) if task else self.label

    def _run(self):
        started = time.monotonic()
        waited = self.first
        while not self._stop.wait(waited):
            elapsed = time.monotonic() - started
            self.ticks += 1
            try:
                self.stream.write("  [%s] still waiting on the model, %ds\n"
                                  % (self._label(), int(elapsed)))
                self.stream.flush()
            except Exception:
                # A closed or replaced stream must never take down a run over
                # a progress line. Stop trying rather than raise from a thread
                # nobody is watching.
                return
            waited = self.interval

    def __enter__(self):
        if enabled():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            # Short join: the thread is waiting on an Event that has just been
            # set, so this returns immediately in practice, and the timeout is
            # only there so a wedged stream cannot stall an exit.
            self._thread.join(timeout=1.0)
        return False
