# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import absolute_import, print_function, unicode_literals

import pytest

import cProfile
import cgi

import gprof2dot
import os
import pstats
import sys

try:
    import pygraphviz
except ImportError:
    pygraphviz = None

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

from xml.sax import saxutils

import pytest_html_profiling.plugin as plugin
from .plugin import HTMLReport


def pytest_addhooks(pluginmanager):
    plugin.pytest_addhooks(pluginmanager)


def pytest_addoption(parser):
    plugin.pytest_addoption(parser)

    group = parser.getgroup('terminal reporting')
    group.addoption("--html-profiling", action="store_true", default=False,
                     help="Adds per-test profiling out put to the report HTML file.")

    if pygraphviz:
        group.addoption("--html-call-graph", action="store_true", default=False,
                        help="Adds call graph visualizations based on the profiling to the "
                              "HTML file for each test.")


def pytest_configure(config):
    profiling = config.getoption('html_profiling')
    if profiling:
        plugin.HTMLReport = ProfilingHTMLReport

    plugin.pytest_configure(config)


class ProfilingHTMLReport(HTMLReport):
    PROFILE_DIRNAME = 'results_profiles'
    STATS_FILENAME = 'test.cprof'
    DOT_SUFFIX = '.dot'
    GRAPH_SUFFIX = '.png'

    CUMULATIVE = 'cumulative'
    INTERNAL = 'time'

    PROFILE_HEADER = {CUMULATIVE: '--- PROFILE (SORTED BY CUMULATIVE TIME)---\n',
                      INTERNAL: '--- PROFILE (SORTED BY INTERNAL TIME)---\n'}
    PROFILE_FOOTER = '--- END PROFILE ---'
    PROFILE_LINK = {CUMULATIVE: 'Profiling report (cumulative time)',
                    INTERNAL: 'Profiling report (internal time)'}

    PRUNED_CUMULATIVE = 'pruned_cumulative'
    PRUNED_INTERNAL = 'pruned_internal'
    NON_PRUNED = 'non_pruned'

    CALLGRAPH_NAME = {PRUNED_CUMULATIVE: 'call_graph_pruned_cumulative',
                      PRUNED_INTERNAL: 'call_graph_pruned_internal',
                      NON_PRUNED: 'call_graph_non_pruned'}
    CALLGRAPH_TITLE = {PRUNED_CUMULATIVE: 'Call-graph (pruned, colored by cumulative time)',
                       PRUNED_INTERNAL: 'Call-graph (pruned, colored by internal time)',
                       NON_PRUNED: 'Call-graph (not pruned, colored by cumulative time)'}

    LINK_TEMPLATE = """
</pre>
<a class ="popup_link" onfocus="this.blur();" href="javascript:showTestDetail('{0}')">{1}</a>
<p>
<div id='{0}' class="popup_window" style="background-color: #D9D9D9; margin-top: 10; margin-bottom: 10">
    <div style='text-align: right; color:black;cursor:pointer'>
        <a onfocus='this.blur();' onclick="document.getElementById('{0}').style.display = 'none' " >
           [x]</a>
    </div>
    <pre>{2}</pre>
</div>
</p>
<pre>"""  # divId, linkText, content

    IMG_TEMPLATE = """
<img src="{0}">
"""  # graph_filename

    TEMPERATURE_COLORMAP = gprof2dot.Theme(
        mincolor=(2.0 / 3.0, 0.80, 0.25),  # dark blue
        maxcolor=(0.0, 1.0, 0.5),  # satured red
        gamma=1.0,
        fontname='vera'
    )

    def __init__(self, logfile, config):
        super(ProfilingHTMLReport, self).__init__(logfile, config)
        self._call_graph = config.getoption('html_call_graph')

    #
    #  Temporarily copied from nose-html-profiler
    #
    def prepareTestCase(self, test):
        """Wrap test case run in :func:`prof.runcall`.
        """
        test_profile_filename = self._get_test_profile_filename(test)
        test_profile_dir = os.path.dirname(test_profile_filename)

        if not os.path.exists(test_profile_dir):
            os.makedirs(test_profile_dir)

        def run_and_profile(result, test=test):
            cProfile.runctx("test.test(result)", globals(), locals(),
                            filename=test_profile_filename, sort=1)

        return run_and_profile

    def _get_test_profile_dir(self, test):
        return os.path.join(self._profile_dir, self.startTime.strftime("%Y_%m_%d_%H_%M_%S"),
                            test.id())

    def _get_test_profile_filename(self, test):
        return os.path.join(self._get_test_profile_dir(test), self.STATS_FILENAME)

    def _get_test_dot_filename(self, test, prune):
        return os.path.join(self._get_test_profile_dir(test),
                            self.CALLGRAPH_NAME[prune] + self.DOT_SUFFIX)

    def _get_test_graph_filename(self, test, prune):
        return os.path.join(self._get_test_profile_dir(test),
                            self.CALLGRAPH_NAME[prune] + self.GRAPH_SUFFIX)

    def _generate_report_test(self, rows, cid, tid, n, t, o, e):
        o = saxutils.escape(o)

        o += self._get_profile_report_html(t, self.CUMULATIVE)
        o += self._get_profile_report_html(t, self.INTERNAL)

        if self._call_graph:
            o += self._get_callgraph_report_html(t, self.PRUNED_CUMULATIVE)
            o += self._get_callgraph_report_html(t, self.PRUNED_INTERNAL)
            o += self._get_callgraph_report_html(t, self.NON_PRUNED)

        super(ProfilingHTMLReport, self)._generate_report_test(rows, cid, tid, n, t, o, e)

    def _get_profile_report_html(self, test, type):
        report = self._get_profile_report(test, type)
        return self._link_to_report_html(test, type, self.PROFILE_LINK[type], report)

    def _link_to_report_html(self, test, label, title, report):
        return self.LINK_TEMPLATE.format(test.id() + '.' + label, title, report)

    def _get_profile_report(self, test, type):
        report = capture(self._print_profile_report, test, type)
        report = cgi.escape(report)
        return report

    def _print_profile_report(self, test, type):
        stats = pstats.Stats(self._get_test_profile_filename(test))

        if stats:
            print(self.PROFILE_HEADER[type])
            stats.sort_stats(type)
            stats.print_stats()
            print(self.PROFILE_FOOTER)

    def _get_callgraph_report_html(self, test, prune):
        report = self._get_callgraph_report(test, prune)
        return self._link_to_report_html(test, self.CALLGRAPH_NAME[prune],
                                         self.CALLGRAPH_TITLE[prune], report)

    def _get_callgraph_report(self, test, prune):
        self._write_dot_graph(test, prune)
        self._render_graph(test, prune)
        rel_graph_filename = os.path.relpath(self._get_test_graph_filename(test, prune),
                                             os.path.dirname(self.html_file))
        return self.IMG_TEMPLATE.format(rel_graph_filename)

    def _write_dot_graph(self, test, prune=False):
        parser = gprof2dot.PstatsParser(self._get_test_profile_filename(test))
        profile = parser.parse()

        funcId = self._find_func_id_for_test_case(profile, test)
        if funcId:
            profile.prune_root(funcId)

        if prune == self.PRUNED_CUMULATIVE:
            profile.prune(0.005, 0.001, False)
        elif prune == self.PRUNED_INTERNAL:
            profile.prune(0.005, 0.001, True)
        else:
            profile.prune(0, 0, False)

        with open(self._get_test_dot_filename(test, prune), 'wt') as f:
            dot = gprof2dot.DotWriter(f)
            dot.graph(profile, self.TEMPERATURE_COLORMAP)

    def _find_func_id_for_test_case(self, profile, test):
        testName = test.id().split('.')[-1]
        funcIds = [func.id for func in profile.functions.values() if func.name.endswith(testName)]

        if len(funcIds) == 1:
            return funcIds[0]

    def _render_graph(self, test, prune):
        graph = pygraphviz.AGraph(self._get_test_dot_filename(test, prune))
        graph.layout('dot')
        graph.draw(self._get_test_graph_filename(test, prune))

    def finalize(self, result):
        if not self.available():
            return


def capture(func, *args, **kwArgs):
    out = StringIO()
    old_stdout = sys.stdout
    sys.stdout = out
    func(*args, **kwArgs)
    sys.stdout = old_stdout
    return out.getvalue()
