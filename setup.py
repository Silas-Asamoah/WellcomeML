import os

import setuptools

here = os.path.abspath(os.path.dirname(__file__))

"""
Load data from the__versions__.py module. Change version, etc in
that module, and it will be automatically populated here. This allows us to
access the module version, etc from inside python with

Examples:

    >>> from wellcomeml.common import about
    >>> about['__version__']
    2019.10.0

"""

about = {} # type: dict
version_path = os.path.join(here, 'wellcomeml', '__version__.py')
with open(version_path, 'r') as f:
    exec(f.read(), about)

with open('README.md', 'r') as f:
    long_description = f.read()

setuptools.setup(
    name=about['__name__'],
    version=about['__version__'],
    author=about['__author__'],
    author_email=about['__author_email__'],
    description=about['__description__'],
    long_description=long_description,
    long_description_content_type='text/markdown',
    url=about['__url__'],
    license=['__license__'],
    packages=setuptools.find_packages(include=["wellcomeml*"]),
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
    ],
    install_requires=[
        'numpy',
        'pandas',
        'boto3',
        'scikit-learn',
        'spacy==2.2.1',
        'nervaluate',
        'en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-2.2.0/en_core_web_sm-2.2.0.tar.gz#egg=en_core_web_sm'
    ],
    extras_require={
        'deep-learning': [
            'torch',
            'transformers<=2.0.0',
            'spacy-transformers @ https://github.com/nsorros/spacy-transformers/tarball/master#egg=spacy-transformers',
            'en_trf_bertbaseuncased_lg @ https://github.com/explosion/spacy-models/releases/download/en_trf_bertbaseuncased_lg-2.2.0/en_trf_bertbaseuncased_lg-2.2.0.tar.gz#egg=en_trf_bertbaseuncased_lg'
        ]
    },
    tests_require=[
        'pytest',
        'pytest-cov'
    ]
)