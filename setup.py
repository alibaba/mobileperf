# -*- coding: utf-8  -*-
'''
@author:     look

@copyright:  1999-2020 Alibaba.com. All rights reserved.

@license:    Apache Software License 2.0

@contact:    390125133@qq.com
'''

from setuptools import find_packages, setup

setup(
    name='mobileperf',
    version='1.0.0',
    author='look',
    maintainer='look',
    author_email='390125133@qq.com',
    install_requires=[
        "requests",
        "urllib3",
    ],
    description="Python Android mobile perf (support Python3)"
)