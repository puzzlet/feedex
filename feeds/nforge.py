#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os.path
import imp
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
    def __init__(self, uri, ignore_time=False, frequent=False):
        if not uri.endswith('/'):
            uri += '/'
        uri = urllib.parse.urljoin(uri, 'activity?commit=commit&forum=forum&issue=issue&frsrelease=frsrelease')
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
                    'user': td[0].text_content().strip(),
                    'title': td[1].text_content().strip(),
                    'date': td[2].text_content().strip(),
                })
        return entries

class NForgeFormatter(EntryFormatter):
    def __init__(self, targets, message_format, arguments=None, digest=False,
            exclude=None):
        EntryFormatter.__init__(self,
            targets=targets,
            message_format='[%(user)s] %(title)s (%(date)s)')

class ToonkManager:
    def load(self):
        return [(ToonkFetcher(), ToonkFormatter())]

manager = FeedManager(
    'nforge.yml',
    fetcher_class=NForgeFetcher,
    formatter_class=NForgeFormatter,
)
