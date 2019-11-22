# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import absolute_import, print_function, unicode_literals

import datetime
import errno
from collections import defaultdict

import pytest

import cProfile
import cgi

import gprof2dot
import os
import pstats
import sys

from pytest_profiling import clean_filename

import pytest_html_profiling

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

STATS_FILENAME = 'test.cprof'

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
        config.profiling = profiling
        #plugin.HTMLReport = ProfilingHTMLReport
        config.reportCls = ProfilingHTMLReport

    config.profile_dir = config.getoption('profile_dir')
    config._html = None
    plugin.pytest_configure(config)

# @pytest.mark.hookwrapper
# def pytest_runtest_setup(item):
#     yield
#     t = open('/Users/radmilko/PycharmProjects/pytest-html-profiling/testing/testfile', 'a')
#     # t.write('--------\n')
#     # t.write(str(item) + '\n')
#     # t.write(str(item.name) + '\n')
#     # t.write(str(item.parent) + '\n')
#     # #t.write(str(item.args))
#     # t.write(str(item.config) + '\n')
#     # t.write(str(item.fspath) + '\n')
#     # #t.write(item)
#
#
#     test_profile_dir = os.path.join(item.config.profile_dir, os.path.splitext(str(item.fspath))[0])
#     test_profile_filename = os.path.join(test_profile_dir, STATS_FILENAME)
#
#     if not os.path.exists(test_profile_dir):
#         os.makedirs(test_profile_dir)
#
#     t.write('\n')
#     t.write(test_profile_filename)
#     t.write('\n')
#     t.write(item.config.profile_dir)
#     t.write('\n')
#     t.write(str(type(item.config.profile_dir)))
#     t.write('\n')
#     t.write(str(type(item.name)))
#     t.write('\n')
#
#     cProfile.runctx(str(item.name) + '()', globals(), locals(), filename=test_profile_filename, sort=1)
#
#     t.close()


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
        self._profile_dir = config.getoption('profile_dir')
        self.start_time = datetime.datetime.now()
        self.html_file = config._html
        self.profs = {}
        self.profs_results = defaultdict(list)

    #
    #  Temporarily copied from nose-html-profiler
    #

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        print('runtest protocol running for: ' + str(item.name))
        prof_filename = self._get_test_profile_filename(item)
        try:
            os.makedirs(os.path.dirname(prof_filename))
        except OSError:
            pass
        prof = cProfile.Profile()
        prof.enable()
        yield
        prof.disable()
        try:
            prof.dump_stats(prof_filename)
        except EnvironmentError as err:
            if err.errno != errno.ENAMETOOLONG:
                raise

        self.profs[item.name] = prof_filename

        output_path = prof_filename + '.txt'
        with open(output_path, 'w') as stream:
            stats = pstats.Stats(prof, stream=stream)
            stats.sort_stats(self.CUMULATIVE)
            stats.print_stats()

        #report = self._get_profile_report(prof, self.CUMULATIVE)

        self.profs_results[item.name].append(output_path)
        print('profs result saved')

    def pytest_sessionfinish(self, session, exitstatus):  # @UnusedVariable
        # if self.profs:
        #     for name, prof in self.profs.iteritems():
        #         # prof_text = pstats.Stats(prof)
        #         output_path = prof + '.txt'
        #         with open(output_path, 'w') as stream:
        #             stats = pstats.Stats(prof, stream=stream)
        #             stats.sort_stats(self.CUMULATIVE)
        #             stats.print_stats()
        #
        #         report = self._get_profile_report(prof, self.CUMULATIVE)
        #
        #         self.profs_results[name].append(output_path)

        report_content = self._generate_report(session)
        self._save_report(report_content)


            # self.combined = os.path.abspath(os.path.join(self.dir, "combined.prof"))
            # combined.dump_stats(self.combined)
            # if self.svg:
            #     self.svg_name = os.path.abspath(os.path.join(self.dir, "combined.svg"))
            #     t = pipes.Template()
            #     t.append("{} -f pstats $IN".format(self.gprof2dot), "f-")
            #     t.append("dot -Tsvg -o $OUT", "-f")
            #     t.copy(self.combined, self.svg_name)

    @pytest.hookimpl(hookwrapper=True, trylast=True)
    def pytest_runtest_makereport(self, item, call):
        print('makereport running for: ' + str(item.name))
        #pytest_html_profiling = item.config.pluginmanager.getplugin('html')
        outcome = yield
        report = outcome.get_result()
        extra = getattr(report, 'extra', [])
        if report.when == 'call':

            #print(self.profs_results)
            prof_txt_filenames = self.profs_results[item.name]
            #print(prof_txt_filenames)
            # always add url to report
            #extra.append(plugin.extras.url('http://www.example.com/'))
            for prof_txt_filename in prof_txt_filenames:
                extra.append(plugin.extras.url('file://' + prof_txt_filename))
            xfail = hasattr(report, 'wasxfail')
            if (report.skipped and xfail) or (report.failed and not xfail):
                # only add additional html on failure
                extra.append(plugin.extras.html('<div>Additional HTML</div>'))
            report.extra = extra

    def run_profiling(self, test):

        test_profile_filename = self._get_test_profile_filename(test)
        test_profile_dir = os.path.dirname(test_profile_filename)

        if not os.path.exists(test_profile_dir):
            os.makedirs(test_profile_dir)

        def run_and_profile(result, test=test):
            cProfile.runctx("test.test(result)", globals(), locals(),
                            filename=test_profile_filename, sort=1)

        return run_and_profile

    def _get_test_profile_dir(self, test):
        return os.path.join(self._profile_dir, self.start_time.strftime("%Y_%m_%d_%H_%M_%S"),
                            test.id())

    def _get_test_profile_filename(self, item):
        #return os.path.join(self._get_test_profile_dir(test), self.STATS_FILENAME)

        return os.path.abspath(os.path.join(self._profile_dir, clean_filename(item.name) + ".prof"))

    def _get_test_profile_txt_filename(self, item):
        return self._get_test_profile_filename(item) + '.txt'

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

    def _get_profile_report(self, item, type):
        report = capture(self._print_profile_report, item, type)
        report = cgi.escape(report)
        return report

    def _print_profile_report(self, prof_path, type):
        stats = pstats.Stats(prof_path)

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
