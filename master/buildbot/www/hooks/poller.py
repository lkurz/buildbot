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

# This change hook allows GitHub or a hand crafted curl invocation to "knock on
# the door" and trigger a change source to poll.


from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from buildbot.changes.base import ReconfigurablePollingChangeSource
from buildbot.util import bytes2unicode
from buildbot.util import unicode2bytes
from buildbot.www.hooks.base import BaseHookHandler
from buildbot.www.service import BuildbotSite

if TYPE_CHECKING:
    from twisted.internet import defer
    from twisted.web.server import Request


class PollingHandler(BaseHookHandler):
    def getChanges(self, req: Request) -> defer.Deferred[tuple[list[dict[str, Any]], str | None]]:
        site = cast(BuildbotSite, req.site)
        assert site.master is not None
        change_svc = site.master.change_svc
        assert req.args is not None
        poll_all = b"poller" not in req.args

        allow_all = True
        allowed: list[bytes] = []
        if isinstance(self.options, dict) and b"allowed" in self.options:
            allow_all = False
            allowed = self.options[b"allowed"]

        pollers: list[ReconfigurablePollingChangeSource] = []

        for source in change_svc:
            if not isinstance(source, ReconfigurablePollingChangeSource):
                continue
            if not hasattr(source, "name"):
                continue
            if not poll_all and unicode2bytes(source.name) not in req.args[b'poller']:
                continue
            if not allow_all and unicode2bytes(source.name) not in allowed:
                continue
            pollers.append(source)

        if not poll_all:
            missing = set(req.args[b'poller']) - set(unicode2bytes(s.name) for s in pollers)
            if missing:
                raise ValueError(f'Could not find pollers: {bytes2unicode(b",".join(missing))}')

        for p in pollers:
            p.force()

        return [], None


poller = PollingHandler
