check-python-versions
=====================

.. image:: https://img.shields.io/pypi/v/check-python-versions.svg
    :target: https://pypi.org/project/check-python-versions/
    :alt: Latest release

.. image:: https://img.shields.io/pypi/pyversions/check-python-versions.svg
    :target: https://pypi.org/project/check-python-versions/
    :alt: Supported Python versions

.. image:: https://travis-ci.org/mgedmin/check-python-versions.svg?branch=master
    :target: https://travis-ci.org/mgedmin/check-python-versions
    :alt: Build status

.. image:: https://coveralls.io/repos/mgedmin/check-python-versions/badge.svg?branch=master
    :target: https://coveralls.io/r/mgedmin/check-python-versions
    :alt: Test coverage


This is a tool for Python package maintainers who want to explicitly state
which Python versions they support.


**The problem**: to properly support e.g. Python 2.7 and 3.4+ you have to
run tests with these Pythons.  This means

- you need a tox.ini with envlist = py27, py34, py35, py36, py37
- you need a .travis.yml with python: [ 2.7, 3.4, 3.5, 3.6, 3.7 ]
- if you support Windows, you need an appveyor.yml with %PYTHON% set to
  C:\\Python2.7, C:\\Python3.4, and so on
- if you're building manylinux wheels you need to ... you get the idea
- you have to tell the users which Python versions you support by specifying
  trove classifiers like "Programming Language :: Python :: 2.7"
- you probably also want to tell pip which versions you support by specifying
  python_requires=">= 2.7, !=3.0.* ..." because AFAIU PyPI classifiers are
  not fine-grained enough

Keeping all these lists consistent is a pain.

**The solution**: ``check-python-versions`` will compare these lists and warn
you if they don't match ::

    $ check-python-versions ~/projects/*
    /home/mg/projects/check-manifest:

    setup.py says:              2.7, 3.4, 3.5, 3.6, 3.7, PyPy
    - python_requires says:     2.7, 3.4, 3.5, 3.6, 3.7
    tox.ini says:               2.7, 3.4, 3.5, 3.6, 3.7, PyPy, PyPy3
    .travis.yml says:           2.7, 3.4, 3.5, 3.6, 3.7, PyPy, PyPy3
    appveyor.yml says:          2.7, 3.4, 3.5, 3.6, 3.7


    /home/mg/projects/dozer:

    setup.py says:              2.7, 3.4, 3.5, 3.6, 3.7
    tox.ini says:               2.7, 3.4, 3.5, 3.6, 3.7
    .travis.yml says:           2.7, 3.4, 3.5, 3.6, 3.7
    appveyor.yml says:          2.7, 3.4, 3.5, 3.6, 3.7


    /home/mg/projects/eazysvn:

    setup.py says:              2.7, 3.4, 3.5, 3.6, 3.7, PyPy
    tox.ini says:               2.7, 3.4, 3.5, 3.6, 3.7, PyPy, PyPy3
    .travis.yml says:           2.7, 3.4, 3.5, 3.6, 3.7, PyPy, PyPy3
    appveyor.yml says:          2.7, 3.4, 3.5, 3.6, 3.7

    ...

    all ok!


Installation
------------

You need Python 3.6 or newer (f-strings!) to run check-python-versions.
Install it with ::

    python3 -m pip install check-python-versions


Usage
-----

::

    $ check-python-versions --help
    usage: check-python-versions [-h] [--version] [--expect VERSIONS]
                                 [--skip-non-packages]
                                 [where [where ...]]

    verify that supported Python versions are the same in setup.py, tox.ini,
    .travis.yml and appveyor.yml

    positional arguments:
      where                directory where a Python package with a setup.py and
                           other files is located

    optional arguments:
      -h, --help           show this help message and exit
      --version            show program's version number and exit
      --expect VERSIONS    expect these versions to be supported, e.g. --expect
                           2.7,3.4-3.7
      --skip-non-packages  skip arguments that are not Python packages without
                           warning about them

If run without any arguments, check-python-versions will look for a setup.py in
the current working directory.

Exit status is 0 if all Python packages had consistent version numbers (and, if
--expect is specified, those numbers match your stated expectations).

If you specify multiple directories on the command line, then all packages
that failed a check will be listed at the end of the run, separated with
spaces, for easier copying and pasting onto shell command lines.  This is
helpful when, e.g. you want to run ::

    check-python-versions ~/src/zopefoundation/*

to check all 380+ packages, and then want re-run the checks only on the failed
ones, for a faster turnabout.


Files
-----

**setup.py** is the only required file; if any of the others are missing,
they'll be ignored (and this will not considered a failure).

- **setup.py**: the ``classifiers`` argument passed to ``setup()`` is expected
  to have classifiers of the form::

        classifiers=[
            ...
            "Programming Language :: Python :: x.y",
            ...
        ],

  check-python-versions will attempt to parse the file and walk the AST to
  extract classifiers, but if that fails, it'll execute
  ``python setup.py --classifiers`` and parse the output.

- **setup.py**: the ``python_requires`` argument passed to ``setup()``, if
  present::

        python_requires=">=2.7, !=3.0.*, !=3.1.*",

  check-python-versions will attempt to parse the file and walk the AST to
  extract the ``python_requires`` value.  It expects to find a string literal
  or a simple expression of the form ``"literal".join(["...", "..."])``.

  Only ``>=`` and ``!=`` constraints are currently supported.

- **tox.ini**: if present, it's expected to have ::

    [tox]
    envlist = pyXY, ...

  Environment names like pyXY-ZZZ are also accepted; the suffix is ignored.

- **.travis.yml**: if present, it's expected to have ::

    python:
      - X.Y
      - ...

  and/or ::

    matrix:
      include:
        - python: X.Y
          ...
        - ...

  and/or ::

    jobs:
      include:
        - python: X.Y
          ...
        - ...

  and/or ::

    env:
      - TOXENV=...

- **appveyor.yml**: if present, it's expected to have ::

    environment:
      matrix:
        - PYTHON: C:\\PythonX.Y
        - ...

  The environment variable name is assumed to be ``PYTHON`` (case-insensitive).
  The values should be one of

  - ``X.Y``
  - ``C:\\PythonX.Y`` (case-insensitive)
  - ``C:\\PythonX.Y-x64`` (case-insensitive)

  Alternatively, you can use ``TOXENV`` with the usual values (pyXY).

- **.manylinux-install.sh**: if present, it's expected to contain a loop like
  ::

    for PYBIN in /opt/python/*/bin; do
        if [[ "${PYBIN}" == *"cp27"* ]] || \
           [[ "${PYBIN}" == *"cp34"* ]] || \
           [[ "${PYBIN}" == *"cp35"* ]] || \
           [[ "${PYBIN}" == *"cp36"* ]] || \
           [[ "${PYBIN}" == *"cp37"* ]]; then
            "${PYBIN}/pip" install -e /io/
            "${PYBIN}/pip" wheel /io/ -w wheelhouse/
               rm -rf /io/build /io/*.egg-info
        fi
    done

  check-python-versions will look for $PYBIN tests of the form ::

    [[ "${PYBIN}" == *"cpXY"* ]]

  where X and Y are arbitrary digits.

  These scripts are used in several zopefoundation repositories like
  zopefoundation/zope.interface.  It's the least standartized format.


Python versions
---------------

In addition to CPython X.Y, check-python-versions will recognize PyPy and PyPy3
in some of the files:

- **setup.py** may have a ::

        'Programming Language :: Python :: Implementation :: PyPy',

  classifier

- **tox.ini** may have pypy[-suffix] and pypy3[-suffix] environments

- **.travis.yml** may have pypy and pypy3 jobs

- **appveyor.yml** and **.manylinux-install.sh** do not usually have pypy tests,
  so check-python-versions cannot recognize them.

These extra Pythons are shown, but not compared for consistency.

In addition, ``python_requires`` in setup.py usually has a lower limit, but no
upper limit.  check-python-versions will assume this means support up to the
current Python 3.x release (3.7 at the moment).
