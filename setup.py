#!/usr/bin/env python

"""The setup script."""
import os.path

from setuptools import setup, find_packages


def _read_file(file: str) -> str:
    # we only needs these files if we're publishing
    if os.path.exists(file):
        with open(file) as f:
            return f.read()
    else:
        return 'N/A'


readme = _read_file('README.md')
version = _read_file('version.txt')

requirements = [
    'PyYAML>=6.0.0,<7.0.0',
    'jsonref>=1.1.0,<2.0.0',
    'openapi-schema-pydantic>=1.2.4,<2.0.0'
]

setup(
    author="Valmiki Rao",
    author_email='valmikirao@gmail.com',
    python_requires='>=3.7',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
    description="Curl with Arguments for Url",
    entry_points={
        'console_scripts': [
            'carl=curl_arguments_url.cli:main',
        ],
    },
    install_requires=requirements,
    license="Apache Software License 2.0",
    long_description=readme,
    long_description_content_type='text/markdown',
    include_package_data=True,
    keywords='curl_arguments_url,carl,curl,zsh,completions,swagger,openapi',
    name='curl_arguments_url',
    packages=find_packages(include=['curl_arguments_url', 'curl_arguments_url.*']),
    url='https://github.com/valmikirao/curl_arguments_url',
    version=version,
    zip_safe=False,
)
