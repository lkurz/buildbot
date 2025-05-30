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

import json

from twisted.internet import defer
from twisted.trial import unittest

from buildbot.config.master import MasterConfig
from buildbot.schedulers.forcesched import AnyPropertyParameter
from buildbot.schedulers.forcesched import BaseParameter
from buildbot.schedulers.forcesched import BooleanParameter
from buildbot.schedulers.forcesched import ChoiceStringParameter
from buildbot.schedulers.forcesched import CodebaseParameter
from buildbot.schedulers.forcesched import CollectedValidationError
from buildbot.schedulers.forcesched import FileParameter
from buildbot.schedulers.forcesched import FixedParameter
from buildbot.schedulers.forcesched import ForceScheduler
from buildbot.schedulers.forcesched import IntParameter
from buildbot.schedulers.forcesched import NestedParameter
from buildbot.schedulers.forcesched import PatchParameter
from buildbot.schedulers.forcesched import StringParameter
from buildbot.schedulers.forcesched import UserNameParameter
from buildbot.schedulers.forcesched import oneCodebase
from buildbot.test.reactor import TestReactorMixin
from buildbot.test.util import scheduler
from buildbot.test.util.config import ConfigErrorsMixin


class TestForceScheduler(
    scheduler.SchedulerMixin, ConfigErrorsMixin, TestReactorMixin, unittest.TestCase
):
    OBJECTID = 19
    SCHEDULERID = 9
    maxDiff = None

    @defer.inlineCallbacks
    def setUp(self):
        self.setup_test_reactor()
        yield self.setUpScheduler()

    @defer.inlineCallbacks
    def makeScheduler(self, name='testsched', builderNames=None, **kw):
        if builderNames is None:
            builderNames = ['a', 'b']
        sched = yield self.attachScheduler(
            ForceScheduler(name=name, builderNames=builderNames, **kw),
            self.OBJECTID,
            self.SCHEDULERID,
            overrideBuildsetMethods=True,
            createBuilderDB=True,
        )
        sched.master.config = MasterConfig()

        self.assertEqual(sched.name, name)

        return sched

    # tests

    def test_compare_branch(self):
        self.assertNotEqual(
            ForceScheduler(name="testched", builderNames=[]),
            ForceScheduler(
                name="testched",
                builderNames=[],
                codebases=oneCodebase(branch=FixedParameter("branch", "fishing/pole")),
            ),
        )

    def test_compare_reason(self):
        self.assertNotEqual(
            ForceScheduler(
                name="testched",
                builderNames=[],
                reason=FixedParameter("reason", "no fish for you!"),
            ),
            ForceScheduler(
                name="testched",
                builderNames=[],
                reason=FixedParameter("reason", "thanks for the fish!"),
            ),
        )

    def test_compare_revision(self):
        self.assertNotEqual(
            ForceScheduler(
                name="testched",
                builderNames=[],
                codebases=oneCodebase(revision=FixedParameter("revision", "fish-v1")),
            ),
            ForceScheduler(
                name="testched",
                builderNames=[],
                codebases=oneCodebase(revision=FixedParameter("revision", "fish-v2")),
            ),
        )

    def test_compare_repository(self):
        self.assertNotEqual(
            ForceScheduler(
                name="testched",
                builderNames=[],
                codebases=oneCodebase(
                    repository=FixedParameter("repository", "git://pond.org/fisher.git")
                ),
            ),
            ForceScheduler(
                name="testched",
                builderNames=[],
                codebases=oneCodebase(
                    repository=FixedParameter("repository", "svn://ocean.com/trawler/")
                ),
            ),
        )

    def test_compare_project(self):
        self.assertNotEqual(
            ForceScheduler(
                name="testched",
                builderNames=[],
                codebases=oneCodebase(project=FixedParameter("project", "fisher")),
            ),
            ForceScheduler(
                name="testched",
                builderNames=[],
                codebases=oneCodebase(project=FixedParameter("project", "trawler")),
            ),
        )

    def test_compare_username(self):
        self.assertNotEqual(
            ForceScheduler(name="testched", builderNames=[]),
            ForceScheduler(
                name="testched",
                builderNames=[],
                username=FixedParameter("username", "The Fisher King <avallach@atlantis.al>"),
            ),
        )

    def test_compare_properties(self):
        self.assertNotEqual(
            ForceScheduler(name="testched", builderNames=[], properties=[]),
            ForceScheduler(
                name="testched",
                builderNames=[],
                properties=[FixedParameter("prop", "thanks for the fish!")],
            ),
        )

    def test_compare_codebases(self):
        self.assertNotEqual(
            ForceScheduler(name="testched", builderNames=[], codebases=['bar']),
            ForceScheduler(name="testched", builderNames=[], codebases=['foo']),
        )

    @defer.inlineCallbacks
    def test_basicForce(self):
        sched = yield self.makeScheduler()
        yield self.master.startService()

        res = yield sched.force(
            'user',
            builderNames=['a'],
            branch='a',
            reason='because',
            revision='c',
            repository='d',
            project='p',
        )

        # only one builder forced, so there should only be one brid
        self.assertEqual(res, (500, {300: 100}))
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        "builderNames": ['a'],
                        "waited_for": False,
                        "priority": 0,
                        "properties": {
                            'owner': ('user', 'Force Build Form'),
                            'reason': ('because', 'Force Build Form'),
                        },
                        "reason": "A build was forced by 'user': because",
                        "sourcestamps": [
                            {
                                'codebase': '',
                                'branch': 'a',
                                'revision': 'c',
                                'repository': 'd',
                                'project': 'p',
                            },
                        ],
                    },
                ),
            ],
        )

    @defer.inlineCallbacks
    def test_basicForce_reasonString(self):
        """Same as above, but with a reasonString"""
        sched = yield self.makeScheduler(reasonString='%(owner)s wants it %(reason)s')
        yield self.master.startService()

        res = yield sched.force(
            'user',
            builderNames=['a'],
            branch='a',
            reason='because',
            revision='c',
            repository='d',
            project='p',
        )
        _, brids = res

        # only one builder forced, so there should only be one brid
        self.assertEqual(len(brids), 1)

        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        'builderNames': ['a'],
                        'priority': 0,
                        'properties': {
                            'owner': ('user', 'Force Build Form'),
                            'reason': ('because', 'Force Build Form'),
                        },
                        'reason': 'user wants it because',
                        'sourcestamps': [
                            {
                                'branch': 'a',
                                'codebase': '',
                                'project': 'p',
                                'repository': 'd',
                                'revision': 'c',
                            }
                        ],
                        'waited_for': False,
                    },
                ),
            ],
        )

    @defer.inlineCallbacks
    def test_force_allBuilders(self):
        sched = yield self.makeScheduler()
        yield self.master.startService()

        res = yield sched.force(
            'user',
            branch='a',
            reason='because',
            revision='c',
            repository='d',
            project='p',
        )
        self.assertEqual(res, (500, {300: 100, 301: 101}))
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        "builderNames": ['a', 'b'],
                        "waited_for": False,
                        "priority": 0,
                        "properties": {
                            'owner': ('user', 'Force Build Form'),
                            'reason': ('because', 'Force Build Form'),
                        },
                        "reason": "A build was forced by 'user': because",
                        "sourcestamps": [
                            {
                                'codebase': '',
                                'branch': 'a',
                                'revision': 'c',
                                'repository': 'd',
                                'project': 'p',
                            },
                        ],
                    },
                ),
            ],
        )

    @defer.inlineCallbacks
    def test_force_someBuilders(self):
        sched = yield self.makeScheduler(builderNames=['a', 'b', 'c'])
        yield self.master.startService()

        res = yield sched.force(
            'user',
            builderNames=['a', 'b'],
            branch='a',
            reason='because',
            revision='c',
            repository='d',
            project='p',
        )
        self.assertEqual(res, (500, {300: 100, 301: 101}))
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        "builderNames": ['a', 'b'],
                        "waited_for": False,
                        "priority": 0,
                        "properties": {
                            'owner': ('user', 'Force Build Form'),
                            'reason': ('because', 'Force Build Form'),
                        },
                        "reason": "A build was forced by 'user': because",
                        "sourcestamps": [
                            {
                                'codebase': '',
                                'branch': 'a',
                                'revision': 'c',
                                'repository': 'd',
                                'project': 'p',
                            },
                        ],
                    },
                ),
            ],
        )

    def test_bad_codebases(self):
        # codebases must be a list of either string or BaseParameter types
        with self.assertRaisesConfigError(
            "ForceScheduler 'foo': 'codebases' must be a "
            "list of strings or CodebaseParameter objects:"
        ):
            ForceScheduler(
                name='foo',
                builderNames=['bar'],
                codebases=[123],
            )

        with self.assertRaisesConfigError(
            "ForceScheduler 'foo': 'codebases' must be a "
            "list of strings or CodebaseParameter objects:"
        ):
            ForceScheduler(name='foo', builderNames=['bar'], codebases=[IntParameter('foo')])

        # codebases cannot be empty
        with self.assertRaisesConfigError(
            "ForceScheduler 'foo': 'codebases' cannot be "
            "empty; use [CodebaseParameter(codebase='', hide=True)] if needed:"
        ):
            ForceScheduler(name='foo', builderNames=['bar'], codebases=[])

        # codebases cannot be a dictionary
        # dictType on Python 3 is: "<class 'dict'>"
        # dictType on Python 2 is: "<type 'dict'>"
        dictType = str(type({}))
        errMsg = (
            "ForceScheduler 'foo': 'codebases' should be a list "
            "of strings or CodebaseParameter, "
            f"not {dictType}"
        )
        with self.assertRaisesConfigError(errMsg):
            ForceScheduler(name='foo', builderNames=['bar'], codebases={'cb': {'branch': 'trunk'}})

    @defer.inlineCallbacks
    def test_good_codebases(self):
        sched = yield self.makeScheduler(codebases=['foo', CodebaseParameter('bar')])
        yield self.master.startService()
        yield sched.force(
            'user',
            builderNames=['a'],
            reason='because',
            foo_branch='a',
            foo_revision='c',
            foo_repository='d',
            foo_project='p',
            bar_branch='a2',
            bar_revision='c2',
            bar_repository='d2',
            bar_project='p2',
        )

        expProperties = {
            'owner': ('user', 'Force Build Form'),
            'reason': ('because', 'Force Build Form'),
        }
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        "builderNames": ['a'],
                        "waited_for": False,
                        "priority": 0,
                        "properties": expProperties,
                        "reason": "A build was forced by 'user': because",
                        "sourcestamps": [
                            {
                                'branch': 'a2',
                                'project': 'p2',
                                'repository': 'd2',
                                'revision': 'c2',
                                'codebase': 'bar',
                            },
                            {
                                'branch': 'a',
                                'project': 'p',
                                'repository': 'd',
                                'revision': 'c',
                                'codebase': 'foo',
                            },
                        ],
                    },
                ),
            ],
        )

    @defer.inlineCallbacks
    def test_codebase_with_patch(self):
        sched = yield self.makeScheduler(
            codebases=['foo', CodebaseParameter('bar', patch=PatchParameter())]
        )
        yield self.master.startService()
        yield sched.force(
            'user',
            builderNames=['a'],
            reason='because',
            foo_branch='a',
            foo_revision='c',
            foo_repository='d',
            foo_project='p',
            bar_branch='a2',
            bar_revision='c2',
            bar_repository='d2',
            bar_project='p2',
            bar_patch_body=b"xxx",
        )
        expProperties = {
            'owner': ('user', 'Force Build Form'),
            'reason': ('because', 'Force Build Form'),
        }

        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        "builderNames": ['a'],
                        "waited_for": False,
                        "priority": 0,
                        "properties": expProperties,
                        "reason": "A build was forced by 'user': because",
                        "sourcestamps": [
                            {
                                'branch': 'a2',
                                'project': 'p2',
                                'repository': 'd2',
                                'revision': 'c2',
                                'codebase': 'bar',
                                'patch_body': b'xxx',
                                'patch_author': '',
                                'patch_subdir': '.',
                                'patch_comment': '',
                                'patch_level': 1,
                            },
                            {
                                'branch': 'a',
                                'project': 'p',
                                'repository': 'd',
                                'revision': 'c',
                                'codebase': 'foo',
                            },
                        ],
                    },
                ),
            ],
        )

    def formatJsonForTest(self, gotJson):
        ret = ""
        linestart = "expectJson='"
        spaces = 7 * 4 + 2
        while len(gotJson) > (90 - spaces):
            gotJson = " " * spaces + linestart + gotJson
            pos = gotJson[:100].rfind(",")
            if pos > 0:
                pos += 2
            ret += gotJson[:pos] + "'\n"
            gotJson = gotJson[pos:]
            linestart = "'"
        ret += " " * spaces + linestart + gotJson + "')\n"
        return ret

    # value = the value to be sent with the parameter (ignored if req is set)
    # expect = the expected result (can be an exception type)
    # klass = the parameter class type
    # req = use this request instead of the auto-generated one based on value
    @defer.inlineCallbacks
    def do_ParameterTest(
        self,
        expect,
        klass,
        # None=one prop, Exception=exception, dict=many props
        expectKind=None,
        owner='user',
        value=None,
        req=None,
        expectJson=None,
        **kwargs,
    ):
        name = kwargs.setdefault('name', 'p1')

        # construct one if needed
        if isinstance(klass, type):
            prop = klass(**kwargs)
        else:
            prop = klass

        self.assertEqual(prop.name, name)
        self.assertEqual(prop.label, kwargs.get('label', prop.name))
        if expectJson is not None:
            gotSpec = prop.getSpec()
            gotJson = json.dumps(gotSpec)
            expectSpec = json.loads(expectJson)
            if gotSpec != expectSpec:
                try:
                    import xerox  # pylint: disable=import-outside-toplevel

                    formatted = self.formatJsonForTest(gotJson)
                    print("You may update the test with (copied to clipboard):\n" + formatted)
                    xerox.copy(formatted)
                    input()
                except ImportError:
                    print("Note: for quick fix, pip install xerox")
            self.assertEqual(gotSpec, expectSpec)

        sched = yield self.makeScheduler(properties=[prop])
        yield self.master.startService()

        if not req:
            req = {name: value, 'reason': 'because'}
        try:
            bsid, brids = yield sched.force(owner, builderNames=['a'], **req)
        except Exception as e:
            if expectKind is not Exception:
                # an exception is not expected
                raise
            if not isinstance(e, expect):
                # the exception is the wrong kind
                raise
            return None  # success

        expect_props = {
            'owner': ('user', 'Force Build Form'),
            'reason': ('because', 'Force Build Form'),
        }

        if expectKind is None:
            expect_props[name] = (expect, 'Force Build Form')
        elif expectKind is dict:
            for k, v in expect.items():
                expect_props[k] = (v, 'Force Build Form')
        else:
            self.fail("expectKind is wrong type!")

        # only forced on 'a'
        self.assertEqual((bsid, brids), (500, {300: 100}))
        self.assertEqual(
            self.addBuildsetCalls,
            [
                (
                    'addBuildsetForSourceStampsWithDefaults',
                    {
                        "builderNames": ['a'],
                        "waited_for": False,
                        "priority": 0,
                        "properties": expect_props,
                        "reason": "A build was forced by 'user': because",
                        "sourcestamps": [
                            {
                                'branch': '',
                                'project': '',
                                'repository': '',
                                'revision': '',
                                'codebase': '',
                            },
                        ],
                    },
                ),
            ],
        )
        return None

    def test_StringParameter(self):
        return self.do_ParameterTest(
            value="testedvalue",
            expect="testedvalue",
            klass=StringParameter,
            expectJson='{"name": "p1", "fullName": "p1", "label": "p1", '
            '"tablabel": "p1", "type": "text", "default": "", "required": false, '
            '"multiple": false, "regex": null, "hide": false, "maxsize": null, '
            '"size": 10, "autopopulate": null, "tooltip": ""}',
        )

    def test_StringParameter_Required(self):
        return self.do_ParameterTest(
            value=" ",
            expect=CollectedValidationError,
            expectKind=Exception,
            klass=StringParameter,
            required=True,
        )

    def test_StringParameter_maxsize(self):
        return self.do_ParameterTest(
            value="xx" * 20,
            expect=CollectedValidationError,
            expectKind=Exception,
            klass=StringParameter,
            maxsize=10,
        )

    def test_FileParameter_maxsize(self):
        return self.do_ParameterTest(
            value="xx" * 20,
            expect=CollectedValidationError,
            expectKind=Exception,
            klass=FileParameter,
            maxsize=10,
        )

    def test_FileParameter(self):
        return self.do_ParameterTest(
            value="xx",
            expect="xx",
            klass=FileParameter,
            expectJson='{"name": "p1", "fullName": "p1", "label": "p1", '
            '"tablabel": "p1", "type": "file", "default": "", "required": false, '
            '"multiple": false, "regex": null, "hide": false, '
            '"maxsize": 10485760, "autopopulate": null, "tooltip": ""}',
        )

    def test_PatchParameter(self):
        expect_json = (
            '{"name": "p1", "fullName": "p1", "label": "p1", "autopopulate": null, '
            '"tablabel": "p1", "type": "nested", "default": "", "required": false, '
            '"multiple": false, "regex": null, "hide": false, "maxsize": null, '
            '"layout": "vertical", "columns": 1, "tooltip": "", "fields": [{"name": "body", '
            '"fullName": "p1_body", "label": "body", "tablabel": "body", "autopopulate": null, '
            '"type": "file", "default": "", "required": false, "multiple": false, '
            '"regex": null, "hide": false, "maxsize": 10485760, "tooltip": ""}, {"name": "level", '
            '"fullName": "p1_level", "label": "level", "tablabel": "level", '
            '"type": "int", "default": 1, "required": false, "multiple": false, '
            '"regex": null, "hide": false, "maxsize": null, "size": 10, "autopopulate": null, "tooltip": ""}, '
            '{"name": "author", "fullName": "p1_author", "label": "author", '
            '"tablabel": "author", "type": "text", "default": "", "autopopulate": null, '
            '"required": false, "multiple": false, "regex": null, "hide": false, '
            '"maxsize": null, "size": 10, "tooltip": ""}, {"name": "comment", "autopopulate": null, '
            '"fullName": "p1_comment", "label": "comment", "tablabel": "comment", '
            '"type": "text", "default": "", "required": false, "multiple": false, '
            '"regex": null, "hide": false, "maxsize": null, "size": 10, "tooltip": ""}, '
            '{"name": "subdir", "fullName": "p1_subdir", "label": "subdir", '
            '"tablabel": "subdir", "type": "text", "default": ".", "autopopulate": null, '
            '"required": false, "multiple": false, "regex": null, "hide": false, '
            '"maxsize": null, "size": 10, "tooltip": ""}]}'
        )

        return self.do_ParameterTest(
            req={"p1_author": 'me', "reason": 'because'},
            expect={'author': 'me', 'body': '', 'comment': '', 'level': 1, 'subdir': '.'},
            klass=PatchParameter,
            expectJson=expect_json,
        )

    def test_IntParameter(self):
        return self.do_ParameterTest(
            value="123",
            expect=123,
            klass=IntParameter,
            expectJson='{"name": "p1", "fullName": "p1", "label": "p1", '
            '"tablabel": "p1", "type": "int", "default": 0, "required": false, '
            '"multiple": false, "regex": null, "hide": false, "maxsize": null, '
            '"size": 10, "autopopulate": null, "tooltip": ""}',
        )

    def test_FixedParameter(self):
        return self.do_ParameterTest(
            value="123",
            expect="321",
            klass=FixedParameter,
            default="321",
            expectJson='{"name": "p1", "fullName": "p1", "label": "p1", '
            '"tablabel": "p1", "type": "fixed", "default": "321", '
            '"required": false, "multiple": false, "regex": null, "hide": true, '
            '"maxsize": null, "autopopulate": null, "tooltip": ""}',
        )

    def test_BooleanParameter_True(self):
        req = {"p1": True, "reason": 'because'}
        return self.do_ParameterTest(
            value="123",
            expect=True,
            klass=BooleanParameter,
            req=req,
            expectJson='{"name": "p1", "fullName": "p1", "label": "p1", '
            '"tablabel": "p1", "type": "bool", "default": "", "required": false, '
            '"multiple": false, "regex": null, "hide": false, '
            '"maxsize": null, "autopopulate": null, "tooltip": ""}',
        )

    def test_BooleanParameter_False(self):
        req = {"p2": True, "reason": 'because'}
        return self.do_ParameterTest(value="123", expect=False, klass=BooleanParameter, req=req)

    def test_UserNameParameter(self):
        email = "test <test@buildbot.net>"
        expect_json = (
            '{"name": "username", "fullName": "username", '
            '"label": "Your name:", "tablabel": "Your name:", "type": "username", '
            '"default": "", "required": false, "multiple": false, "regex": null, '
            '"hide": false, "maxsize": null, "size": 30, '
            '"need_email": true, "autopopulate": null, "tooltip": ""}'
        )
        return self.do_ParameterTest(
            value=email,
            expect=email,
            klass=UserNameParameter(),
            name="username",
            label="Your name:",
            expectJson=expect_json,
        )

    def test_UserNameParameterIsValidMail(self):
        email = "test@buildbot.net"
        expect_json = (
            '{"name": "username", "fullName": "username", '
            '"label": "Your name:", "tablabel": "Your name:", "type": "username", '
            '"default": "", "required": false, "multiple": false, "regex": null, '
            '"hide": false, "maxsize": null, "size": 30, '
            '"need_email": true, "autopopulate": null, "tooltip": ""}'
        )
        return self.do_ParameterTest(
            value=email,
            expect=email,
            klass=UserNameParameter(),
            name="username",
            label="Your name:",
            expectJson=expect_json,
        )

    def test_UserNameParameterIsValidMailBis(self):
        email = "<test@buildbot.net>"
        expect_json = (
            '{"name": "username", "fullName": "username", '
            '"label": "Your name:", "tablabel": "Your name:", "type": "username", '
            '"default": "", "required": false, "multiple": false, "regex": null, '
            '"hide": false, "maxsize": null, "size": 30, '
            '"need_email": true, "autopopulate": null, "tooltip": ""}'
        )
        return self.do_ParameterTest(
            value=email,
            expect=email,
            klass=UserNameParameter(),
            name="username",
            label="Your name:",
            expectJson=expect_json,
        )

    def test_ChoiceParameter(self):
        return self.do_ParameterTest(
            value='t1',
            expect='t1',
            klass=ChoiceStringParameter,
            choices=['t1', 't2'],
            expectJson='{"name": "p1", "fullName": "p1", "label": "p1", '
            '"tablabel": "p1", "type": "list", "default": "", "required": false, '
            '"multiple": false, "regex": null, "hide": false, "maxsize": null, '
            '"choices": ["t1", "t2"], "strict": true, "autopopulate": null, "tooltip": ""}',
        )

    def test_ChoiceParameterError(self):
        return self.do_ParameterTest(
            value='t3',
            expect=CollectedValidationError,
            expectKind=Exception,
            klass=ChoiceStringParameter,
            choices=['t1', 't2'],
            debug=False,
        )

    def test_ChoiceParameterError_notStrict(self):
        return self.do_ParameterTest(
            value='t1', expect='t1', strict=False, klass=ChoiceStringParameter, choices=['t1', 't2']
        )

    def test_ChoiceParameterMultiple(self):
        return self.do_ParameterTest(
            value=['t1', 't2'],
            expect=['t1', 't2'],
            klass=ChoiceStringParameter,
            choices=['t1', 't2'],
            multiple=True,
            expectJson='{"name": "p1", "fullName": "p1", "label": "p1", '
            '"tablabel": "p1", "type": "list", "default": "", "required": false, '
            '"multiple": true, "regex": null, "hide": false, "maxsize": null, '
            '"choices": ["t1", "t2"], "strict": true, "autopopulate": null, "tooltip": ""}',
        )

    def test_ChoiceParameterMultipleError(self):
        return self.do_ParameterTest(
            value=['t1', 't3'],
            expect=CollectedValidationError,
            expectKind=Exception,
            klass=ChoiceStringParameter,
            choices=['t1', 't2'],
            multiple=True,
            debug=False,
        )

    def test_NestedParameter(self):
        fields = [IntParameter(name="foo")]
        expect_json = (
            '{"name": "p1", "fullName": "p1", "label": "p1", "autopopulate": null, '
            '"tablabel": "p1", "type": "nested", "default": "", "required": false, '
            '"multiple": false, "regex": null, "hide": false, "maxsize": null, '
            '"layout": "vertical", "columns": 1, "tooltip": "", "fields": [{"name": "foo", '
            '"fullName": "p1_foo", "label": "foo", "tablabel": "foo", "autopopulate": null, '
            '"type": "int", "default": 0, "required": false, "multiple": false, '
            '"regex": null, "hide": false, "maxsize": null, "size": 10, "tooltip": ""}]}'
        )
        return self.do_ParameterTest(
            req={"p1_foo": '123', "reason": 'because'},
            expect={"foo": 123},
            klass=NestedParameter,
            fields=fields,
            expectJson=expect_json,
        )

    def test_NestedNestedParameter(self):
        fields = [
            NestedParameter(
                name="inner", fields=[StringParameter(name='str'), AnyPropertyParameter(name='any')]
            ),
            IntParameter(name="foo"),
        ]
        return self.do_ParameterTest(
            req={
                "p1_foo": '123',
                "p1_inner_str": "bar",
                "p1_inner_any_name": "hello",
                "p1_inner_any_value": "world",
                "reason": "because",
            },
            expect={"foo": 123, "inner": {"str": 'bar', "hello": 'world'}},
            klass=NestedParameter,
            fields=fields,
        )

    def test_NestedParameter_nullname(self):
        # same as above except "p1" and "any" are skipped
        fields = [
            NestedParameter(
                name="inner", fields=[StringParameter(name='str'), AnyPropertyParameter(name='')]
            ),
            IntParameter(name="foo"),
            NestedParameter(
                name='bar',
                fields=[
                    NestedParameter(name='', fields=[AnyPropertyParameter(name='a')]),
                    NestedParameter(name='', fields=[AnyPropertyParameter(name='b')]),
                ],
            ),
        ]
        return self.do_ParameterTest(
            req={
                "foo": '123',
                "inner_str": "bar",
                "inner_name": "hello",
                "inner_value": "world",
                "reason": "because",
                "bar_a_name": "a",
                "bar_a_value": "7",
                "bar_b_name": "b",
                "bar_b_value": "8",
            },
            expect={
                "foo": 123,
                "inner": {"str": 'bar', "hello": 'world'},
                "bar": {'a': '7', 'b': '8'},
            },
            expectKind=dict,
            klass=NestedParameter,
            fields=fields,
            name='',
        )

    def test_bad_reason(self):
        with self.assertRaisesConfigError(
            "ForceScheduler 'testsched': reason must be a StringParameter"
        ):
            ForceScheduler(name='testsched', builderNames=[], codebases=['bar'], reason="foo")

    def test_bad_username(self):
        with self.assertRaisesConfigError(
            "ForceScheduler 'testsched': username must be a StringParameter"
        ):
            ForceScheduler(name='testsched', builderNames=[], codebases=['bar'], username="foo")

    def test_notidentifier_name(self):
        # FIXME: this test should be removed eventually when bug 3460 gets a
        # real fix
        with self.assertRaisesConfigError(
            "ForceScheduler name must be an identifier: 'my scheduler'"
        ):
            ForceScheduler(name='my scheduler', builderNames=[], codebases=['bar'], username="foo")

    def test_emptystring_name(self):
        with self.assertRaisesConfigError("ForceScheduler name must not be empty:"):
            ForceScheduler(name='', builderNames=[], codebases=['bar'], username="foo")

    def test_integer_properties(self):
        with self.assertRaisesConfigError(
            "ForceScheduler 'testsched': properties must be a list of BaseParameters:"
        ):
            ForceScheduler(
                name='testsched',
                builderNames=[],
                properties=1234,
            )

    def test_listofints_properties(self):
        with self.assertRaisesConfigError(
            "ForceScheduler 'testsched': properties must be a list of BaseParameters:"
        ):
            ForceScheduler(
                name='testsched',
                builderNames=[],
                properties=[1234, 2345],
            )

    def test_listofmixed_properties(self):
        with self.assertRaisesConfigError(
            "ForceScheduler 'testsched': properties must be a list of BaseParameters:"
        ):
            ForceScheduler(
                name='testsched',
                builderNames=[],
                properties=[
                    BaseParameter(
                        name="test",
                    ),
                    4567,
                ],
            )

    def test_novalue_to_parameter(self):
        with self.assertRaisesConfigError(
            "Use default='1234' instead of value=... to give a default Parameter value"
        ):
            BaseParameter(name="test", value="1234")
