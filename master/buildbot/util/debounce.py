# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members


import functools

from twisted.internet import defer
from twisted.python import log

# debounce phases
PH_IDLE = 0
PH_WAITING = 1
PH_RUNNING = 2
PH_RUNNING_QUEUED = 3


class Debouncer:
    __slots__ = [
        'completeDeferreds',
        'function',
        'get_reactor',
        'phase',
        'stopped',
        'timer',
        'until_idle',
        'wait',
    ]

    def __init__(self, wait, function, get_reactor, until_idle):
        # time to wait
        self.wait = wait
        # zero-argument callable to invoke
        self.function = function
        # current phase
        self.phase = PH_IDLE
        # Twisted timer for waiting
        self.timer = None
        # true if this instance is stopped
        self.stopped = False
        # deferreds to fire when the call is complete
        self.completeDeferreds = []
        # for tests
        self.get_reactor = get_reactor
        # invoke after wait s of idle
        self.until_idle = until_idle

    def __call__(self):
        if self.stopped:
            return
        phase = self.phase
        if phase == PH_IDLE:
            self.timer = self.get_reactor().callLater(self.wait, self.invoke)
            self.phase = PH_WAITING
        elif phase == PH_WAITING:
            if self.until_idle:
                self.timer.reset(self.wait)
        elif phase == PH_RUNNING:
            self.phase = PH_RUNNING_QUEUED
        else:  # phase == PH_RUNNING_QUEUED:
            pass

    def __repr__(self):
        return f"<debounced {self.function!r}, wait={self.wait!r}, phase={self.phase}>"

    def invoke(self):
        self.phase = PH_RUNNING
        d = defer.maybeDeferred(self.function)
        d.addErrback(log.err, 'from debounced function:')

        @d.addCallback
        def retry(_):
            queued = self.phase == PH_RUNNING_QUEUED
            self.phase = PH_IDLE
            if queued and self.stopped:
                # If stop() is called when debouncer is running with additional run queued,
                # the queued run must still be invoked because the current run may be stale.
                self.invoke()
                return

            while self.completeDeferreds:
                self.completeDeferreds.pop(0).callback(None)
            if queued:
                self()

    def start(self):
        self.stopped = False

    def stop(self):
        self.stopped = True
        if self.phase == PH_WAITING:
            self.timer.cancel()
            self.invoke()
            # fall through with PH_RUNNING
        if self.phase in (PH_RUNNING, PH_RUNNING_QUEUED):
            d = defer.Deferred()
            self.completeDeferreds.append(d)
            return d
        return defer.succeed(None)


class _Descriptor:
    def __init__(self, fn, wait, attrName, get_reactor, until_idle):
        self.fn = fn
        self.wait = wait
        self.attrName = attrName
        self.get_reactor = get_reactor
        self.until_idle = until_idle

    def __get__(self, instance, cls):
        try:
            db = getattr(instance, self.attrName)
        except AttributeError:
            db = Debouncer(
                self.wait,
                functools.partial(self.fn, instance),
                functools.partial(self.get_reactor, instance),
                self.until_idle,
            )
            setattr(instance, self.attrName, db)
        return db


def _get_reactor_from_master(o):
    return o.master.reactor


def method(wait, until_idle=False, get_reactor=_get_reactor_from_master):
    def wrap(fn):
        stateName = "__debounce_" + fn.__name__ + "__"
        return _Descriptor(fn, wait, stateName, get_reactor, until_idle)

    return wrap
