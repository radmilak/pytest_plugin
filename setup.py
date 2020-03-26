from setuptools import setup

setup(
    name="pytest-html-profiling",
    version="1.0.0",
    description="Pytest plugin for generating HTML reports with per-test profiling and "
                "optionally call graph visualizations. Based on pytest-html by Dave Hunt.",
    long_description=open("README.rst").read(),
    author="Radmila Kompova and Sveinung Gundersen",
    author_email="radmilko@ifi.uio.no, sveinugu@gmail.com",
    url="https://github.com/hyperbrowser/pytest-html-profiling",
    packages=["pytest_html_profiling"],
    package_data={"pytest_html_profiling": ["resources/*"]},
    entry_points={"pytest11": ["html = pytest_html_profiling.profiling_plugin"]},
    setup_requires=["setuptools_scm"],
    install_requires=["pytest>=3.0", "pytest-metadata", 'pygraphviz', 'gprof2dot'],
    license="Mozilla Public License 2.0 (MPL 2.0)",
    keywords="py.test pytest html report",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Framework :: Pytest",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
        "Operating System :: POSIX",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: MacOS :: MacOS X",
        "Topic :: Software Development :: Quality Assurance",
        "Topic :: Software Development :: Testing",
        "Topic :: Utilities",
        "Programming Language :: Python :: 2.7"
    ],
)
