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

import time
from unittest import mock

from twisted.internet import defer
from twisted.python import log
from twisted.trial import unittest

from buildbot.changes import filter
from buildbot.schedulers import timed
from buildbot.test import fakedb
from buildbot.test.reactor import TestReactorMixin
from buildbot.test.util import scheduler
from buildbot.test.util.state import StateTestMixin


class Nightly(scheduler.SchedulerMixin, TestReactorMixin, StateTestMixin, unittest.TestCase):
    OBJECTID = 132
    SCHEDULERID = 32

    # not all timezones are even multiples of 1h from GMT.  This variable
    # holds the number of seconds ahead of the hour for the current timezone.
    # This is then added to the clock before each test is run (to get to 0
    # minutes past the hour) and subtracted before the time offset is reported.
    localtime_offset = time.timezone % 3600

    # Timed scheduler uses the datetime module for some time operations. Windows does not like very
    # small timestamps in these APIs, so tests are adjusted to different times.
    time_offset = 86400 * 10 + localtime_offset

    long_ago_time = 86400

    @defer.inlineCallbacks
    def makeScheduler(self, **kwargs):
        sched = yield self.attachScheduler(
            timed.Nightly(**kwargs), self.OBJECTID, self.SCHEDULERID, overrideBuildsetMethods=True
        )

        yield self.master.db.insert_test_data([
            fakedb.Builder(name=bname) for bname in kwargs.get("builderNames", [])
        ])

        self.reactor.advance(self.time_offset)

        self.addBuildsetCallTimes = []

        def recordTimes(timeList, method):
            def timedMethod(**kw):
                timeList.append(self.reactor.seconds() - self.time_offset)
                return method(**kw)

            return timedMethod

        sched.addBuildsetForSourceStampsWithDefaults = recordTimes(
            self.addBuildsetCallTimes, sched.addBuildsetForSourceStampsWithDefaults
        )
        sched.addBuildsetForChanges = recordTimes(
            self.addBuildsetCallTimes, sched.addBuildsetForChanges
        )

        # see self.assertConsumingChanges
        self.consumingChanges = None

        def startConsumingChanges(**kwargs):
            self.consumingChanges = kwargs
            return defer.succeed(None)

        sched.startConsumingChanges = startConsumingChanges

        return sched

    def mkbs(self, **kwargs):
        # create buildset for expected_buildset in assertBuildset.
        bs = {
            "reason": "The Nightly scheduler named 'test' triggered this build",
            "external_idstring": '',
            "sourcestampsetid": 100,
            "properties": [('scheduler', ('test', 'Scheduler'))],
        }
        bs.update(kwargs)
        return bs

    def mkss(self, **kwargs):
        # create sourcestamp for expected_sourcestamps in assertBuildset.
        ss = {"branch": 'master', "project": '', "repository": '', "sourcestampsetid": 100}
        ss.update(kwargs)
        return ss

    @defer.inlineCallbacks
    def mkch(self, **kwargs):
        # create changeset and insert in database.
        chd = {"branch": 'master', "project": '', "repository": ''}
        chd.update(kwargs)
        ch = self.makeFakeChange(**chd)
        # fakedb.Change requires changeid instead of number
        chd['changeid'] = chd['number']
        del chd['number']
        yield self.master.db.insert_test_data([
            fakedb.Change(**chd),
            fakedb.SourceStamp(id=92),
        ])
        return ch

    @defer.inlineCallbacks
    def setUp(self):
        self.setup_test_reactor()
        yield self.setUpScheduler()

    def assertConsumingChanges(self, **kwargs):
        self.assertEqual(self.consumingChanges, kwargs)

    # Tests

    @defer.inlineCallbacks
    def test_constructor_no_reason(self):
        sched = yield self.makeScheduler(name='test', builderNames=['test'], branch='default')
        yield sched.configureService()
        self.assertEqual(sched.reason, "The Nightly scheduler named 'test' triggered this build")

    @defer.inlineCallbacks
    def test_constructor_reason(self):
        sched = yield self.makeScheduler(
            name='test', builderNames=['test'], branch='default', reason="hourly"
        )
        yield sched.configureService()
        self.assertEqual(sched.reason, "hourly")

    @defer.inlineCallbacks
    def test_constructor_change_filter(self):
        sched = yield self.makeScheduler(
            name='test',
            builderNames=['test'],
            branch=None,
            change_filter=filter.ChangeFilter(category_re="fo+o"),
        )
        yield sched.configureService()
        assert sched.change_filter

    @defer.inlineCallbacks
    def test_constructor_month(self):
        sched = yield self.makeScheduler(
            name='test', builderNames=['test'], branch='default', month='1'
        )
        yield sched.configureService()
        self.assertEqual(sched.month, "1")

    @defer.inlineCallbacks
    def test_constructor_priority_none(self):
        sched = yield self.makeScheduler(
            name='test', builderNames=['test'], branch='default', priority=None
        )
        yield sched.configureService()
        self.assertEqual(sched.priority, None)

    @defer.inlineCallbacks
    def test_constructor_priority_int(self):
        sched = yield self.makeScheduler(
            name='test', builderNames=['test'], branch='default', priority=8
        )
        yield sched.configureService()
        self.assertEqual(sched.priority, 8)

    @defer.inlineCallbacks
    def test_constructor_priority_function(self):
        def sched_priority(builderNames, changesByCodebase):
            return 0

        sched = yield self.makeScheduler(
            name='test', builderNames=['test'], branch='default', priority=sched_priority
        )
        yield sched.configureService()
        self.assertEqual(sched.priority, sched_priority)

    @defer.inlineCallbacks
    def test_enabled_callback(self):
        sched = yield self.makeScheduler(name='test', builderNames=['test'], branch='default')
        yield sched.configureService()
        expectedValue = not sched.enabled
        yield sched._enabledCallback(None, {'enabled': not sched.enabled})
        self.assertEqual(sched.enabled, expectedValue)
        expectedValue = not sched.enabled
        yield sched._enabledCallback(None, {'enabled': not sched.enabled})
        self.assertEqual(sched.enabled, expectedValue)

    @defer.inlineCallbacks
    def test_disabled_activate(self):
        sched = yield self.makeScheduler(name='test', builderNames=['test'], branch='default')
        yield sched._enabledCallback(None, {'enabled': not sched.enabled})
        self.assertEqual(sched.enabled, False)
        r = yield sched.activate()
        self.assertEqual(r, None)

    @defer.inlineCallbacks
    def test_disabled_deactivate(self):
        sched = yield self.makeScheduler(name='test', builderNames=['test'], branch='default')
        yield sched._enabledCallback(None, {'enabled': not sched.enabled})
        self.assertEqual(sched.enabled, False)
        r = yield sched.deactivate()
        self.assertEqual(r, None)

    @defer.inlineCallbacks
    def test_disabled_start_build(self):
        sched = yield self.makeScheduler(name='test', builderNames=['test'], branch='default')
        yield sched._enabledCallback(None, {'enabled': not sched.enabled})
        self.assertEqual(sched.enabled, False)
        r = yield sched.startBuild()
        self.assertEqual(r, None)

    # end-to-end tests: let's see the scheduler in action

    @defer.inlineCallbacks
    def test_iterations_simple(self):
        # note that Nightly works in local time, but the TestReactor always
        # starts at midnight UTC, so be careful not to use times that are
        # timezone dependent -- stick to minutes-past-the-half-hour, as some
        # timezones are multiples of 30 minutes off from UTC
        yield self.makeScheduler(
            name='test', builderNames=['test'], branch=None, minute=[10, 20, 21, 40, 50, 51]
        )
        yield self.mkch(number=19)

        # add a change classification
        yield self.master.db.schedulers.classifyChanges(self.SCHEDULERID, {19: True})

        yield self.master.startService()

        # check that the classification has been flushed, since this
        # invocation has not requested onlyIfChanged
        yield self.assert_classifications(self.SCHEDULERID, {})

        self.reactor.advance(0)
        while self.reactor.seconds() < self.time_offset + 30 * 60:
            self.reactor.advance(60)
        self.assertEqual(self.addBuildsetCallTimes, [600, 1200, 1260])
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        'builderNames': None,
                        'sourcestamps': [{'codebase': ''}],
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'waited_for': False,
                    },
                ),
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        'builderNames': None,
                        'sourcestamps': [{'codebase': ''}],
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'waited_for': False,
                    },
                ),
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        'builderNames': None,
                        'sourcestamps': [{'codebase': ''}],
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'waited_for': False,
                    },
                ),
            ],
        )
        yield self.assert_state_by_class('test', 'Nightly', last_build=1260 + self.time_offset)

    @defer.inlineCallbacks
    def test_iterations_simple_with_branch(self):
        # see timezone warning above
        sched = yield self.makeScheduler(
            name='test', builderNames=['test'], branch='master', minute=[5, 35]
        )
        yield self.master.startService()

        yield sched.activate()

        self.reactor.advance(0)
        while self.reactor.seconds() < self.time_offset + 10 * 60:
            self.reactor.advance(60)
        self.assertEqual(self.addBuildsetCallTimes, [300])
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        'builderNames': None,
                        'sourcestamps': [{'codebase': ''}],
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'waited_for': False,
                    },
                )
            ],
        )
        yield self.assert_state_by_class('test', 'Nightly', last_build=300 + self.time_offset)

    @defer.inlineCallbacks
    def do_test_iterations_onlyIfChanged(
        self, changes_at, last_only_if_changed, is_new_scheduler=False, **kwargs
    ):
        fII = mock.Mock(name='fII')
        yield self.makeScheduler(
            name='test',
            builderNames=['test'],
            branch=None,
            minute=[5, 25, 45],
            onlyIfChanged=True,
            fileIsImportant=fII,
            **kwargs,
        )

        if not is_new_scheduler:
            yield self.set_fake_state(self.sched, 'last_build', self.long_ago_time)

        if last_only_if_changed is not None:
            yield self.set_fake_state(self.sched, 'last_only_if_changed', last_only_if_changed)

        return (yield self.do_test_iterations_onlyIfChanged_test(fII, changes_at))

    @defer.inlineCallbacks
    def do_test_iterations_onlyIfChanged_test(self, fII, changes_at):
        yield self.master.startService()

        # check that the scheduler has started to consume changes
        self.assertConsumingChanges(fileIsImportant=fII, change_filter=None, onlyImportant=False)

        # manually run the clock forward through a half-hour, allowing any
        # excitement to take place
        self.reactor.advance(0)  # let it trigger the first build
        while self.reactor.seconds() < self.time_offset + 30 * 60:
            # inject any new changes..
            while changes_at and self.reactor.seconds() >= self.time_offset + changes_at[0][0]:
                _, newchange, important = changes_at.pop(0)
                newchange = yield self.addFakeChange(newchange)
                yield self.sched.gotChange(newchange, important).addErrback(log.err)
            # and advance the clock by a minute
            self.reactor.advance(60)

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_no_changes_new_scheduler(self):
        yield self.do_test_iterations_onlyIfChanged(
            [], last_only_if_changed=None, is_new_scheduler=True
        )
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        'builderNames': None,
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'sourcestamps': [{'codebase': ''}],
                        'waited_for': False,
                    },
                )
            ],
        )
        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_no_changes_existing_scheduler(self):
        yield self.do_test_iterations_onlyIfChanged([], last_only_if_changed=True)
        self.assertEqual(self.addBuildsetCalls, [])
        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_no_changes_existing_scheduler_setting_changed(self):
        # When onlyIfChanged==False, builds are run every time on the time set
        # (changes or no changes). Changes are being recognized but do not have any effect on
        # starting builds.
        # It might happen that onlyIfChanged was False, then change happened, then setting was
        # changed to onlyIfChanged==True.
        # Because onlyIfChanged was False possibly important change will be missed.
        # Therefore the first build should start immediately.

        yield self.do_test_iterations_onlyIfChanged([], last_only_if_changed=False)
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        'builderNames': None,
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'sourcestamps': [{'codebase': ''}],
                        'waited_for': False,
                    },
                )
            ],
        )
        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_no_changes_existing_scheduler_update_to_v3_5_0(self):
        # v3.4.0 have not had a variable last_only_if_changed yet therefore this case is tested
        # separately
        yield self.do_test_iterations_onlyIfChanged([], last_only_if_changed=None)
        self.assertEqual(self.addBuildsetCallTimes, [])
        self.assertEqual(self.addBuildsetCalls, [])
        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_no_changes_force_at(self):
        yield self.do_test_iterations_onlyIfChanged(
            [], last_only_if_changed=True, force_at_minute=[23, 25, 27]
        )

        self.assertEqual(self.addBuildsetCallTimes, [1500])
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        'builderNames': None,
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'sourcestamps': [{'codebase': ''}],
                        'waited_for': False,
                    },
                )
            ],
        )
        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_unimp_changes_calls_for_new_scheduler(self):
        yield self.do_test_iterations_onlyIfChanged(
            [
                (60, self.makeFakeChange(number=500, branch=None), False),
                (600, self.makeFakeChange(number=501, branch=None), False),
            ],
            last_only_if_changed=None,
            is_new_scheduler=True,
        )

        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForChanges',
                    {
                        'builderNames': None,
                        'changeids': [500],
                        'external_idstring': None,
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'waited_for': False,
                    },
                )
            ],
        )

        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_unimp_changes_existing_sched_changed_only_if_changed(self):
        yield self.do_test_iterations_onlyIfChanged(
            [
                (60, self.makeFakeChange(number=500, branch=None), False),
                (600, self.makeFakeChange(number=501, branch=None), False),
            ],
            last_only_if_changed=False,
        )

        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        'builderNames': None,
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'sourcestamps': [{'codebase': ''}],
                        'waited_for': False,
                    },
                )
            ],
        )

        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_unimp_changes_existing_sched_same_only_if_changed(self):
        yield self.do_test_iterations_onlyIfChanged(
            [
                (60, self.makeFakeChange(number=500, branch=None), False),
                (600, self.makeFakeChange(number=501, branch=None), False),
            ],
            last_only_if_changed=True,
        )

        self.assertEqual(self.addBuildsetCalls, [])

        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_changes_existing_scheduler_update_to_v3_5_0(self):
        # v3.4.0 have not had a variable last_only_if_changed yet therefore this case is tested
        # separately
        yield self.do_test_iterations_onlyIfChanged(
            [
                (120, self.makeFakeChange(number=500, branch=None), False),
                (1200, self.makeFakeChange(number=501, branch=None), True),
                (1201, self.makeFakeChange(number=502, branch=None), False),
            ],
            last_only_if_changed=None,
        )

        self.assertEqual(self.addBuildsetCallTimes, [1500])
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForChanges',
                    {
                        'waited_for': False,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'external_idstring': None,
                        'changeids': [500, 501, 502],
                        'priority': None,
                        'properties': None,
                        'builderNames': None,
                    },
                ),
            ],
        )
        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_unimp_changes_force_at(self):
        yield self.do_test_iterations_onlyIfChanged(
            [
                (60, self.makeFakeChange(number=500, branch=None), False),
                (600, self.makeFakeChange(number=501, branch=None), False),
            ],
            last_only_if_changed=True,
            force_at_minute=[23, 25, 27],
        )

        self.assertEqual(self.addBuildsetCallTimes, [1500])
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForChanges',
                    {
                        'builderNames': None,
                        'changeids': [500, 501],
                        'external_idstring': None,
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'waited_for': False,
                    },
                )
            ],
        )
        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_off_branch_changes(self):
        yield self.do_test_iterations_onlyIfChanged(
            [
                (60, self.makeFakeChange(number=500, branch='testing'), True),
                (1700, self.makeFakeChange(number=501, branch='staging'), True),
            ],
            last_only_if_changed=True,
        )

        self.assertEqual(self.addBuildsetCalls, [])
        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_mixed_changes(self):
        yield self.do_test_iterations_onlyIfChanged(
            [
                (120, self.makeFakeChange(number=500, branch=None), False),
                (130, self.makeFakeChange(number=501, branch='offbranch'), True),
                (1200, self.makeFakeChange(number=502, branch=None), True),
                (1201, self.makeFakeChange(number=503, branch=None), False),
                (1202, self.makeFakeChange(number=504, branch='offbranch'), True),
            ],
            last_only_if_changed=True,
        )

        # note that the changeid list includes the unimportant changes, but not the
        # off-branch changes, and note that no build took place at 300s, as no important
        # changes had yet arrived
        self.assertEqual(self.addBuildsetCallTimes, [1500])
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForChanges',
                    {
                        'builderNames': None,
                        'changeids': [500, 502, 503],
                        'external_idstring': None,
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'waited_for': False,
                    },
                )
            ],
        )
        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_createAbsoluteSourceStamps_oneChanged(self):
        # Test createAbsoluteSourceStamps=True when only one codebase has
        # changed
        yield self.do_test_iterations_onlyIfChanged(
            [
                (120, self.makeFakeChange(number=500, codebase='a', revision='2345:bcd'), True),
            ],
            codebases={
                'a': {'repository': "", 'branch': 'master'},
                'b': {'repository': "", 'branch': 'master'},
            },
            createAbsoluteSourceStamps=True,
            last_only_if_changed=True,
        )
        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        # addBuildsetForChanges calls getCodebase, so this isn't too
        # interesting
        self.assertEqual(self.addBuildsetCallTimes, [300])
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForChanges',
                    {
                        'builderNames': None,
                        'changeids': [500],
                        'external_idstring': None,
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'waited_for': False,
                    },
                )
            ],
        )
        yield self.assert_state_by_class(
            'test',
            'Nightly',
            lastCodebases={
                'a': {"revision": '2345:bcd', "branch": None, "repository": '', "lastChange": 500}
            },
        )
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_createAbsoluteSourceStamps_oneChanged_loadOther(self):
        # Test createAbsoluteSourceStamps=True when only one codebase has changed,
        # but the other was previously changed
        fII = mock.Mock(name='fII')
        yield self.makeScheduler(
            name='test',
            builderNames=['test'],
            branch=None,
            minute=[5, 25, 45],
            onlyIfChanged=True,
            fileIsImportant=fII,
            codebases={
                'a': {'repository': "", 'branch': 'master'},
                'b': {'repository': "", 'branch': 'master'},
            },
            createAbsoluteSourceStamps=True,
        )

        yield self.set_fake_state(self.sched, 'last_only_if_changed', True)
        yield self.set_fake_state(
            self.sched,
            'lastCodebases',
            {
                'b': {
                    'branch': 'master',
                    'repository': 'B',
                    'revision': '1234:abc',
                    'lastChange': 499,
                }
            },
        )

        yield self.do_test_iterations_onlyIfChanged_test(
            fII,
            [
                (120, self.makeFakeChange(number=500, codebase='a', revision='2345:bcd'), True),
            ],
        )

        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        # addBuildsetForChanges calls getCodebase, so this isn't too
        # interesting
        self.assertEqual(self.addBuildsetCallTimes, [300])
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForChanges',
                    {
                        'builderNames': None,
                        'changeids': [500],
                        'external_idstring': None,
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'waited_for': False,
                    },
                )
            ],
        )
        yield self.assert_state_by_class(
            'test',
            'Nightly',
            lastCodebases={
                'a': {"revision": '2345:bcd', "branch": None, "repository": '', "lastChange": 500},
                'b': {
                    "revision": '1234:abc',
                    "branch": "master",
                    "repository": 'B',
                    "lastChange": 499,
                },
            },
        )
        yield self.sched.deactivate()

    @defer.inlineCallbacks
    def test_iterations_onlyIfChanged_createAbsoluteSourceStamps_bothChanged(self):
        # Test createAbsoluteSourceStamps=True when both codebases have changed
        yield self.do_test_iterations_onlyIfChanged(
            [
                (120, self.makeFakeChange(number=500, codebase='a', revision='2345:bcd'), True),
                (122, self.makeFakeChange(number=501, codebase='b', revision='1234:abc'), True),
            ],
            codebases={
                'a': {'repository': "", 'branch': 'master'},
                'b': {'repository': "", 'branch': 'master'},
            },
            last_only_if_changed=None,
            createAbsoluteSourceStamps=True,
        )

        yield self.assert_state_by_class('test', 'Nightly', last_build=1500 + self.time_offset)
        # addBuildsetForChanges calls getCodebase, so this isn't too
        # interesting
        self.assertEqual(self.addBuildsetCallTimes, [300])
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForChanges',
                    {
                        'builderNames': None,
                        'changeids': [500, 501],
                        'external_idstring': None,
                        'priority': None,
                        'properties': None,
                        'reason': "The Nightly scheduler named 'test' triggered this build",
                        'waited_for': False,
                    },
                )
            ],
        )
        yield self.assert_state_by_class(
            'test',
            'Nightly',
            lastCodebases={
                'a': {"revision": '2345:bcd', "branch": None, "repository": '', "lastChange": 500},
                'b': {"revision": '1234:abc', "branch": None, "repository": '', "lastChange": 501},
            },
        )
        yield self.sched.deactivate()
