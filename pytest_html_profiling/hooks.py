# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from datetime import datetime
from py.xml import html
import pytest

def pytest_html_results_summary(prefix, summary, postfix):
    """ Called before adding the summary section to the report """
    pass



def pytest_html_results_table_header(cells):
    pass
    # cells.insert(2, html.th('Description'))
    # cells.insert(1, html.th('Time', class_='sortable time', col='time'))
    # cells.pop()

def pytest_html_results_table_row(report, cells):
    pass
    # cells.insert(2, html.td(report.description))
    # cells.insert(1, html.td(datetime.utcnow(), class_='col-time'))
    # cells.pop()



def pytest_html_results_table_html(report, data):
    pass
