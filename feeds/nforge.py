#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os.path
import imp
import logging
import urllib.request
import urllib.parse
import urllib.error
import re

import lxml.html
import feedparser

# dynamically import feeds.general
# ../feed.py should handle any exception
_ = imp.find_module('general', [os.path.dirname(__file__)])
feeds_general = imp.load_module('general', *_)
FeedFetcher = feeds_general.FeedFetcher
EntryFormatter = feeds_general.EntryFormatter
FeedManager = feeds_general.FeedManager

class NForgeFetcher(FeedFetcher):
    def __init__(self, uri, ignore_time=True, frequent=False):
        if not uri.endswith('/'):
            uri += '/'
        types = ['commit', 'forum', 'issue', 'frsrelease']
        uri += 'activity?' + '&'.join('{}={}'.format(_, _) for _ in types)
        FeedFetcher.__init__(self, uri, ignore_time=ignore_time,
            frequent=frequent)

    def get_entries(self):
        html = urllib.request.urlopen(self.uri).read()
        tree = lxml.html.fromstring(html.decode('utf8', 'replace'))
        entries = []
        for table in tree.find_class('activity-list'):
            for tr in reversed(table.xpath('./tbody/tr')):
                td = tr.findall('td')
                if len(td) != 3:
                    continue
                entries.append({
                    'title': td[0].text_content().strip(),
                    'user': td[1].text_content().strip(),
                    'date': td[2].text_content().strip(),
                })
        return entries

    def get_fresh_entries(self):
        return FeedFetcher.get_fresh_entries(self)

class NForgeFormatter(EntryFormatter):
    def __init__(self, targets, message_format, arguments=None, digest=False,
            exclude=None):
        EntryFormatter.__init__(self,
            targets=targets,
            message_format='[{name}] {user} {title} ({date})')

    def build_arguments(self, entry):
        result = EntryFormatter(entry)
        result['user'] = entry['user']

manager = FeedManager(
    'nforge.yml',
    fetcher_class=NForgeFetcher,
    formatter_class=NForgeFormatter,
)

