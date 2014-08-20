# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack Foundation
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Base Test Case for all Unit Tests"""

import contextlib
import logging
import os

import eventlet.timeout
import fixtures
from oslo.config import cfg
import stubout
import testtools

from neutron.common import exceptions
from neutron import manager


CONF = cfg.CONF
TRUE_STRING = ['True', '1']
LOG_FORMAT = "%(asctime)s %(levelname)8s [%(name)s] %(message)s"


class BaseTestCase(testtools.TestCase):

    def _cleanup_coreplugin(self):
        manager.NeutronManager._instance = self._saved_instance

    def setup_coreplugin(self, core_plugin=None):
        self._saved_instance = manager.NeutronManager._instance
        self.addCleanup(self._cleanup_coreplugin)
        manager.NeutronManager._instance = None
        if core_plugin is not None:
            cfg.CONF.set_override('core_plugin', core_plugin)

    def setUp(self):
        super(BaseTestCase, self).setUp()

        if os.environ.get('OS_DEBUG') in TRUE_STRING:
            _level = logging.DEBUG
        else:
            _level = logging.INFO
        capture_logs = os.environ.get('OS_LOG_CAPTURE') in TRUE_STRING
        if not capture_logs:
            logging.basicConfig(format=LOG_FORMAT, level=_level)
        self.log_fixture = self.useFixture(
            fixtures.FakeLogger(
                format=LOG_FORMAT,
                level=_level,
                nuke_handlers=capture_logs,
            ))

        # suppress all but errors here
        self.useFixture(
            fixtures.FakeLogger(
                name='neutron.api.extensions',
                format=LOG_FORMAT,
                level=logging.ERROR,
                nuke_handlers=capture_logs,
            ))

        test_timeout = int(os.environ.get('OS_TEST_TIMEOUT', 0))
        if test_timeout == -1:
            test_timeout = 0
        if test_timeout > 0:
            self.useFixture(fixtures.Timeout(test_timeout, gentle=True))

        # If someone does use tempfile directly, ensure that it's cleaned up
        self.useFixture(fixtures.NestedTempfile())
        self.useFixture(fixtures.TempHomeDir())

        self.temp_dir = self.useFixture(fixtures.TempDir()).path
        cfg.CONF.set_override('state_path', self.temp_dir)

        self.addCleanup(CONF.reset)

        if os.environ.get('OS_STDOUT_CAPTURE') in TRUE_STRING:
            stdout = self.useFixture(fixtures.StringStream('stdout')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stdout', stdout))
        if os.environ.get('OS_STDERR_CAPTURE') in TRUE_STRING:
            stderr = self.useFixture(fixtures.StringStream('stderr')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stderr', stderr))
        self.stubs = stubout.StubOutForTesting()
        self.stubs.Set(exceptions, '_FATAL_EXCEPTION_FORMAT_ERRORS', True)

    def config(self, **kw):
        """Override some configuration values.

        The keyword arguments are the names of configuration options to
        override and their values.

        If a group argument is supplied, the overrides are applied to
        the specified configuration option group.

        All overrides are automatically cleared at the end of the current
        test by the fixtures cleanup process.
        """
        group = kw.pop('group', None)
        for k, v in kw.iteritems():
            CONF.set_override(k, v, group)

    @contextlib.contextmanager
    def assert_max_execution_time(self, max_execution_time=5):
        with eventlet.timeout.Timeout(max_execution_time, False):
            yield
            return
        self.fail('Execution of this test timed out')
