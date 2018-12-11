#!/usr/bin/python3
"""
Check supported Python versions in a Python package.

Makes sure the set of supported Python versions is consistent between

- setup.py PyPI classifiers
- tox.ini default env list
- .travis-ci.yml
- appveyor.yml
- (optionally) .manylinux-install.sh as used by various ZopeFoundation projects

"""

import argparse
import ast
import configparser
import logging
import os
import re
import subprocess
import sys


try:
    import yaml
except ImportError:  # pragma: nocover
    yaml = None
    print("pyaml is needed for .travis.yml support (apt install python3-yaml)")


__author__ = 'Marius Gedminas <marius@gedmin.as>'
__version__ = '0.10.0.dev0'


log = logging.getLogger('check-python-versions')


TOX_INI = 'tox.ini'
TRAVIS_YML = '.travis.yml'
APPVEYOR_YML = 'appveyor.yml'
MANYLINUX_INSTALL_SH = '.manylinux-install.sh'


MAX_PYTHON_1_VERSION = 6  # i.e. 1.6
MAX_PYTHON_2_VERSION = 7  # i.e. 2.7
CURRENT_PYTHON_3_VERSION = 7  # i.e. 3.7


def warn(msg):
    print(msg, file=sys.stderr)


def pipe(*cmd, **kwargs):
    if 'cwd' in kwargs:
        log.debug('EXEC cd %s && %s', kwargs['cwd'], ' '.join(cmd))
    else:
        log.debug('EXEC %s', ' '.join(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, **kwargs)
    return p.communicate()[0].decode('UTF-8', 'replace')


def get_supported_python_versions(repo_path='.'):
    setup_py = os.path.join(repo_path, 'setup.py')
    classifiers = get_setup_py_keyword(setup_py, 'classifiers')
    if classifiers is None:
        # AST parsing is complicated
        classifiers = pipe("python", "setup.py", "-q", "--classifiers",
                           cwd=repo_path).splitlines()
    return get_versions_from_classifiers(classifiers)


def get_versions_from_classifiers(classifiers):
    # Based on
    # https://github.com/mgedmin/project-summary/blob/master/summary.py#L221-L234
    prefix = 'Programming Language :: Python :: '
    impl_prefix = 'Programming Language :: Python :: Implementation :: '
    cpython = impl_prefix + 'CPython'
    versions = {
        s[len(prefix):].replace(' :: Only', '').rstrip()
        for s in classifiers
        if s.startswith(prefix) and s[len(prefix):len(prefix) + 1].isdigit()
    } | {
        s[len(impl_prefix):].rstrip()
        for s in classifiers
        if s.startswith(impl_prefix) and s != cpython
    }
    for major in '2', '3':
        if major in versions and any(
                v.startswith(f'{major}.') for v in versions):
            versions.remove(major)
    return sorted(versions)


def get_python_requires(setup_py='setup.py'):
    python_requires = get_setup_py_keyword(setup_py, 'python_requires')
    if python_requires is None:
        return None
    return parse_python_requires(python_requires)


def get_setup_py_keyword(setup_py, keyword):
    with open(setup_py) as f:
        try:
            tree = ast.parse(f.read(), setup_py)
        except SyntaxError as error:
            warn(f'Could not parse {setup_py}: {error}')
            return None
    node = find_call_kwarg_in_ast(tree, 'setup', keyword)
    if node is None:
        warn('Could not find setup() call in setup.py')
        return None
    return eval_ast_node(node, keyword)


def find_call_kwarg_in_ast(tree, funcname, keyword):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == funcname):
            for kwarg in node.keywords:
                if kwarg.arg == keyword:
                    return kwarg.value
            break
    return None


def eval_ast_node(node, keyword):
    if isinstance(node, ast.Str):
        return node.s
    if isinstance(node, (ast.List, ast.Tuple)):
        try:
            return ast.literal_eval(node)
        except ValueError:
            pass
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Str)
            and node.func.attr == 'join'):
        try:
            return node.func.value.s.join(ast.literal_eval(node.args[0]))
        except ValueError:
            pass
    warn('Non-literal %s= passed to setup()' % keyword)
    return None


def parse_python_requires(s):
    rx = re.compile(r'^(~=|==|!=|<=|>=|<|>|===)\s*(\d+(?:\.\d+)*(?:\.\*)?$)')
    specifiers = []
    min_ver = None
    forbidden = set()
    for specifier in map(str.strip, s.split(',')):
        m = rx.match(specifier)
        if not m:
            warn('Bad python_requires specifier: %s' % specifier)
            continue
        op, ver = m.groups()
        specifiers.append((op, ver))
        if op == '>=':
            if min_ver is not None:
                warn('Multiple >= specifiers: %s and %s' % (min_ver, ver))
            if ver.endswith('.*'):
                warn('Did not expect >= with a .*: %s' % ver)
                ver = ver[:-2]
            min_ver = ver
        elif op == '!=':
            if not ver.endswith('.*'):
                warn('Did not expect != without a .*: %s' % ver)
            elif ver.count('.') != 2:
                warn('Unexpected number of dots in %s' % ver)
            else:
                forbidden.add(ver[:-2])
        else:
            warn('Did not expect a %s specifier: %s' % (op, specifier))
    # okay, let's do magic
    versions = []
    if not min_ver:
        warn('Expected a >= specifier')
        return versions
    min_ver_tuple = tuple(map(int, min_ver.split('.')))[:2]
    for major, max_minor in [
            (1, MAX_PYTHON_1_VERSION),
            (2, MAX_PYTHON_2_VERSION),
            (3, CURRENT_PYTHON_3_VERSION)]:
        for minor in range(0, max_minor + 1):
            ver = '%d.%d' % (major, minor)
            if (major, minor) >= min_ver_tuple and ver not in forbidden:
                versions.append(ver)
    return versions


def get_tox_ini_python_versions(filename=TOX_INI):
    conf = configparser.ConfigParser()
    try:
        conf.read(filename)
        envlist = conf.get('tox', 'envlist')
    except configparser.Error:
        return []
    envlist = parse_envlist(envlist)
    return sorted(set(
        tox_env_to_py_version(e) for e in envlist if e.startswith('py')))


def parse_envlist(envlist):
    envs = []
    for part in re.split(r'((?:[{][^}]*[}]|[^,{\s])+)|,|\s+', envlist):
        # NB: part can be None
        part = (part or '').strip()
        if not part:
            continue
        envs += brace_expand(part)
    return envs


def brace_expand(s):
    m = re.match('^([^{]*)[{]([^}]*)[}](.*)$', s)
    if not m:
        return [s]
    left = m.group(1)
    right = m.group(3)
    res = []
    for alt in m.group(2).split(','):
        res += brace_expand(left + alt + right)
    return res


def tox_env_to_py_version(env):
    if '-' in env:
        # e.g. py34-coverage, pypy-subunit
        env = env.partition('-')[0]
    if env.startswith('pypy'):
        return 'PyPy' + env[4:]
    elif env.startswith('py') and len(env) >= 4:
        return f'{env[2]}.{env[3:]}'
    else:
        return env


def get_travis_yml_python_versions(filename=TRAVIS_YML):
    with open(filename) as fp:
        conf = yaml.safe_load(fp)
    versions = []
    if 'python' in conf:
        versions += map(travis_normalize_py_version, conf['python'])
    if 'matrix' in conf and 'include' in conf['matrix']:
        for job in conf['matrix']['include']:
            if 'python' in job:
                versions.append(travis_normalize_py_version(job['python']))
    if 'jobs' in conf and 'include' in conf['jobs']:
        for job in conf['jobs']['include']:
            if 'python' in job:
                versions.append(travis_normalize_py_version(job['python']))
    if 'env' in conf:
        toxenvs = []
        for env in conf['env']:
            if env.startswith('TOXENV='):
                toxenvs.extend(parse_envlist(env.partition('=')[-1]))
        versions.extend(
            tox_env_to_py_version(e) for e in toxenvs if e.startswith('py'))
    return sorted(set(versions))


def travis_normalize_py_version(v):
    v = str(v)
    if v.startswith('pypy3'):
        # could be pypy3, pypy3.5, pypy3.5-5.10.0
        return 'PyPy3'
    elif v.startswith('pypy'):
        # could be pypy, pypy2, pypy2.7, pypy2.7-5.10.0
        return 'PyPy'
    else:
        return v


def get_appveyor_yml_python_versions(filename=APPVEYOR_YML):
    with open(filename) as fp:
        conf = yaml.safe_load(fp)
    # There's more than one way of doing this, I'm setting %PYTHON% to
    # the directory that has a Python interpreter (C:\PythonXY)
    versions = []
    for env in conf['environment']['matrix']:
        for var, value in env.items():
            if var.lower() == 'python':
                versions.append(appveyor_normalize_py_version(value))
            elif var == 'TOXENV':
                toxenvs = parse_envlist(value)
                versions.extend(
                    tox_env_to_py_version(e)
                    for e in toxenvs if e.startswith('py'))
    return sorted(set(versions))


def appveyor_normalize_py_version(ver):
    ver = str(ver).lower()
    if ver.startswith('c:\\python'):
        ver = ver[len('c:\\python'):]
    if ver.endswith('\\'):
        ver = ver[:-1]
    if ver.endswith('-x64'):
        ver = ver[:-len('-x64')]
    assert len(ver) >= 2 and ver[:2].isdigit()
    return f'{ver[0]}.{ver[1:]}'


def get_manylinux_python_versions(filename=MANYLINUX_INSTALL_SH):
    magic = re.compile(r'.*\[\[ "\$\{PYBIN\}" == \*"cp(\d)(\d)"\* \]\]')
    versions = []
    with open(filename) as fp:
        for line in fp:
            m = magic.match(line)
            if m:
                versions.append('{}.{}'.format(*m.groups()))
    return sorted(set(versions))


def important(versions):
    return {
        v for v in versions
        if not v.startswith(('PyPy', 'Jython')) and v != 'nightly'
        and not v.endswith('-dev')
    }


def parse_expect(v):
    versions = set()

    for part in v.split(','):
        if '-' in part:
            lo, hi = part.split('-', 1)
        else:
            lo = hi = part

        lo_major, lo_minor = map(int, lo.split('.', 1))
        hi_major, hi_minor = map(int, hi.split('.', 1))

        if lo_major != hi_major:
            raise ValueError(f'bad range: {part} ({lo_major} != {hi_major})')

        for v in range(lo_minor, hi_minor + 1):
            versions.add(f'{lo_major}.{v}')

    return sorted(versions)


def is_package(where='.'):
    setup_py = os.path.join(where, 'setup.py')
    return os.path.exists(setup_py)


def check(where='.', *, print=print, expect=None):

    if not os.path.isdir(where):
        print("not a directory")
        return None

    setup_py = os.path.join(where, 'setup.py')
    if not os.path.exists(setup_py):
        print("no setup.py -- not a Python package?")
        return None

    sources = [
        ('setup.py', get_supported_python_versions, None),
        ('- python_requires', get_python_requires, 'setup.py'),
        (TOX_INI, get_tox_ini_python_versions, TOX_INI),
        (TRAVIS_YML, get_travis_yml_python_versions, TRAVIS_YML),
        (APPVEYOR_YML, get_appveyor_yml_python_versions, APPVEYOR_YML),
        (MANYLINUX_INSTALL_SH, get_manylinux_python_versions,
         MANYLINUX_INSTALL_SH),
    ]

    width = max(len(title) for title, *etc in sources) + len(" says:")

    version_sets = []

    for (title, extractor, filename) in sources:
        arg = os.path.join(where, filename) if filename else where
        if not os.path.exists(arg):
            continue
        versions = extractor(arg)
        if versions is None:
            continue
        print(f"{title} says:".ljust(width), ", ".join(versions) or "(empty)")
        version_sets.append(important(versions))

    if not expect:
        expect = version_sets[0]
    else:
        print("expected:".ljust(width), ', '.join(expect))

    expect = important(expect)
    return all(
        expect == v for v in version_sets
    )


def main():
    parser = argparse.ArgumentParser(
        description="verify that supported Python versions are the same"
                    " in setup.py, tox.ini, .travis.yml and appveyor.yml")
    parser.add_argument('--version', action='version',
                        version="%(prog)s version " + __version__)
    parser.add_argument('--expect', metavar='VERSIONS',
                        help='expect these versions to be supported, e.g.'
                             ' --expect 2.7,3.4-3.7')
    parser.add_argument('--skip-non-packages', action='store_true',
                        help='skip arguments that are not Python packages'
                             ' without warning about them')
    parser.add_argument('where', nargs='*',
                        help='directory where a Python package with a setup.py'
                             ' and other files is located')
    args = parser.parse_args()

    expect = args.expect and parse_expect(args.expect)

    where = args.where
    if args.skip_non_packages:
        where = [path for path in where if is_package(path)]

    multiple = len(where) > 1
    mismatches = []
    for n, path in enumerate(where or ['.']):
        if multiple:
            if n:
                print("\n")
            print(f"{path}:\n")
        if not check(path, expect=expect):
            mismatches.append(path)

    if mismatches:
        if multiple:
            sys.exit(f"\nmismatch in {' '.join(mismatches)}!")
        else:
            sys.exit("\nmismatch!")
    elif multiple:
        print("\nall ok!")


if __name__ == '__main__':
    main()
