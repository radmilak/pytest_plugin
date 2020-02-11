# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import absolute_import, print_function, unicode_literals

import cProfile
import cgi
import datetime
import errno
import os
import pstats
import sys
from collections import defaultdict

import gprof2dot
import pygraphviz
import pytest

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

import pytest_html_profiling.plugin as plugin
from .plugin import HTMLReport


def pytest_addhooks(pluginmanager):
    plugin.pytest_addhooks(pluginmanager)


def pytest_addoption(parser):
    plugin.pytest_addoption(parser)

    group = parser.getgroup('terminal reporting')
    group.addoption("--html-profiling", action="store_true", default=False, dest='html_profiling',
                     help="Adds per-test profiling out put to the report HTML file.")


    group.addoption("--html-call-graph", action="store_true", default=False, dest='call_graph',
                    help="Adds call graph visualizations based on the profiling to the "
                          "HTML file for each test.")

    group.addoption("--html-profile-dir", action="store",
                          default=os.environ.get('PYTEST_HTML_PROFILE_DIR', 'pytest_profiles'),
                          dest="profile_dir",
                          metavar="FILE",
                          help="Use the specified directory to store the directory containing "
                               "call graph and statistic files for each individual test. The "
                               "result HTML file links to the call graph files thus created."
                               "Default value: profile_dir. Can also be specified in the "
                               "environment variable PYTEST_HTML_PROFILE_DIR.")


def pytest_configure(config):
    profiling = config.getoption('html_profiling')
    if profiling:
        config.reportCls = ProfilingHTMLReport
    else:
        config.reportCls = HTMLReport

    config.profile_dir = config.getoption('profile_dir')
    config._html = None
    plugin.pytest_configure(config)


class ProfilingHTMLReport(HTMLReport):
    STATS_FILENAME = 'test.cprof'
    PROFILE_DIRNAME = 'results_profiles'
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
            <a onfocus="this.blur();" href="javascript:toggle_collapsed(\'{0}\')">{1}</a>
            <p>
            <div id='{0}' class="popup_window collapsed" style="background-color: #D9D9D9; margin-top: 10; margin-bottom: 10">
                <div style='text-align: right; color:black;cursor:pointer'>
                    <a onfocus='this.blur();' onclick="document.getElementById('{0}').style.display = 'none' " >
                       [x]</a>
                </div>
                <pre>{2}</pre>
            </div>
            </p>
            
            """

    IMG_TEMPLATE = """
    <img src="{0}">
    """

    TEMPERATURE_COLORMAP = gprof2dot.Theme(
        mincolor=(2.0 / 3.0, 0.80, 0.25),  # dark blue
        maxcolor=(0.0, 1.0, 0.5),  # satured red
        gamma=1.0,
        fontname='vera'
    )

    def __init__(self, logfile, config):
        super(ProfilingHTMLReport, self).__init__(logfile, config)
        self.profiling = config.getoption('html_profiling')
        self._call_graph = config.getoption('call_graph', False)
        self._profile_dir = config.getoption('profile_dir')
        if not os.path.exists(self._profile_dir):
            os.makedirs(self._profile_dir)
        self.start_time = datetime.datetime.now()
        self.profs_results = defaultdict(dict)
        self.graph_results = defaultdict(dict)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item):
        if not self.profiling:
            yield
        else:
            prof_filename = self._get_test_profile_filename(item.name)
            prof_dir = os.path.dirname(prof_filename)
            if not os.path.exists(prof_dir):
                os.makedirs(prof_dir)
            prof = cProfile.Profile()
            prof.enable()
            yield
            prof.disable()
            try:
                prof.dump_stats(prof_filename)
            except EnvironmentError as err:
                if err.errno != errno.ENAMETOOLONG:
                    raise

            self._generate_stats_and_graphs(item.name, prof_filename)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        if self.profiling:
            report = outcome.get_result()
            extra = getattr(report, 'extra', [])
            if report.when == 'call':
                for stat in [self.INTERNAL, self.CUMULATIVE]:
                    prof_result = self.profs_results[item.name][stat]
                    profHtml = self._link_to_report_html(item.name, stat, self.PROFILE_LINK[stat], prof_result)
                    extra.append(plugin.extras.html(profHtml))

                if self._call_graph:
                    for pruned in [self.PRUNED_INTERNAL, self.PRUNED_CUMULATIVE, self.NON_PRUNED]:
                        graph_abspath = self.graph_results[item.name][pruned]
                        graph_report_relpath = os.path.relpath(graph_abspath, os.path.dirname(self.logfile))
                        graph_link = self.IMG_TEMPLATE.format(graph_report_relpath)
                        graphHtml = self._link_to_report_html(item.name, self.CALLGRAPH_NAME[pruned],
                                                  self.CALLGRAPH_TITLE[pruned], graph_link)
                        extra.append(plugin.extras.html(graphHtml))

                report.extra = extra

    def _generate_stats_file(self, name, path, statType):
        report = self._get_profile_report(path, statType)
        self.profs_results[name][statType] = report

    def _generate_stats_and_graphs(self, name, path):
        self._generate_stats_file(name, path, self.CUMULATIVE)
        self._generate_stats_file(name, path, self.INTERNAL)
        if self._call_graph:
            self._generate_graphs(name, path, self.PRUNED_CUMULATIVE)
            self._generate_graphs(name, path, self.PRUNED_INTERNAL)
            self._generate_graphs(name, path, self.NON_PRUNED)

    def _generate_graphs(self, name, path, prune):
        self._write_dot_graph(name, path, prune)
        self._render_graph(name, prune)

    def _write_dot_graph(self, name, path, prune=''):
        parser = gprof2dot.PstatsParser(path)
        profile = parser.parse()

        funcId = self._find_func_id_for_test_case(profile, name)
        if funcId:
            profile.prune_root(funcId)

        if prune == self.PRUNED_CUMULATIVE:
            profile.prune(0.005, 0.001, None, True)
        elif prune == self.PRUNED_INTERNAL:
            profile.prune(0.005, 0.001, None, True)
        else:
            profile.prune(0, 0, None, False)

        with open(self._get_test_dot_filename(name, prune), 'wt') as f:
            dot = gprof2dot.DotWriter(f)
            dot.graph(profile, self.TEMPERATURE_COLORMAP)

    def _find_func_id_for_test_case(self, profile, testName):
        funcIds = [func.id for func in profile.functions.values() if func.name.endswith(testName)]

        if len(funcIds) == 1:
            return funcIds

    def _get_test_profile_dir(self, name):
        return os.path.join(self._profile_dir, self.start_time.strftime("%Y_%m_%d_%H_%M_%S"), name)

    def _get_test_profile_filename(self, name):
        return os.path.abspath(os.path.join(self._get_test_profile_dir(name), self.STATS_FILENAME))

    def _get_test_dot_filename(self, name, prune):
        return os.path.abspath(os.path.join(self._get_test_profile_dir(name),
                            self.CALLGRAPH_NAME[prune] + self.DOT_SUFFIX))

    def _render_graph(self, name, prune):
        graph = pygraphviz.AGraph(self._get_test_dot_filename(name, prune))
        graph.layout('dot')
        graph_path = self._get_test_graph_filename(name, prune)
        graph.draw(graph_path)
        self.graph_results[name][prune] = graph_path

    def _get_test_graph_filename(self, name, prune):
        return os.path.abspath(os.path.join(self._get_test_profile_dir(name),
                            self.CALLGRAPH_NAME[prune] + self.GRAPH_SUFFIX))

    def _link_to_report_html(self, name, label, title, report):
        return self.LINK_TEMPLATE.format(name + '.' + label, title, report)

    def _get_profile_report(self, path, type):
        report = capture(self._print_profile_report, path, type)
        report = cgi.escape(report)
        return report

    def _print_profile_report(self, prof_path, type):
        stats = pstats.Stats(prof_path)

        if stats:
            print(self.PROFILE_HEADER[type])
            stats.sort_stats(type)
            stats.print_stats()
            print(self.PROFILE_FOOTER)


def capture(func, *args, **kwArgs):
    out = StringIO()
    old_stdout = sys.stdout
    sys.stdout = out
    func(*args, **kwArgs)
    sys.stdout = old_stdout
    return out.getvalue()
