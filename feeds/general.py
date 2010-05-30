#coding: utf-8
import os
import time
import calendar
import datetime
from collections import defaultdict
import urllib.parse
import traceback
import yaml
import email.utils
import re

import feedparser
import chardet

from util import limit_time
from util import rfc2timestamp, tuple2rfc
from util import KoreanStandardTime

FILE_PATH = os.path.dirname(__file__)
FUTURE_THRESHOLD = 86400
TIMEOUT_THRESHOLD = 30
MAX_CHAR = 300

def get_updated(entry, default=None):
    """Returns updated time of the entry, in unix timestamp.
    default -- current time if None
    """
    # assuming entry.updated_parsed is in UTC
    updated = entry.get('updated_parsed', None)
    if isinstance(updated, time.struct_time):
        return calendar.timegm(updated)
    if isinstance(updated, datetime.datetime):
        return calendar.timegm(updated.timetuple())
    if default is not None:
        return default
    else:
        return time.time()

class FeedFetcher(object):
    def __init__(self, uri, ignore_time=False, frequent=False):
        self.uri = str(uri)
        self.ignore_time = ignore_time
        self.frequent = frequent
        self.etag = ''
        self.last_modified = 0
        self.last_confirmed = 0
        self.main_link = ''
        self.entries = []
        self.initialized = False

    def _get_cache_filename(self):
        return os.path.join(FILE_PATH, '../cache',
            urllib.parse.quote(self.uri, ''))

    def load_cache(self):
        file_name = self._get_cache_filename()
        if not os.access(file_name, os.F_OK):
            self.initialize_cache()
            return
        try:
            data = yaml.load(open(file_name, 'r'))
        except Exception:
            traceback.print_exc()
            return
        if data:
            self.main_link = str(data.get('link', ''))
            self.etag = data.get('etag', '')
            self.last_confirmed = rfc2timestamp(data.get('last-confirmed', None), 0)
            self.last_modified = rfc2timestamp(data.get('last-modified', None), 0)
            self.entries = data.get('entries', []) if data else []
            for entry in self.entries or []:
                if 'updated' in entry:
                    entry['updated'] = email.utils.parsedate(entry['updated'])
        self.initialized = True

    def save_cache(self, entries):
        """Save the feed's information into the cache file.
        Entries timestamped at future are not saved, unless ignore_time is set.
        entries -- save only these entries, to prevent the cache from being
                   flooded with all the older entries.
        """
        now = time.time() + FUTURE_THRESHOLD
        data = {}
        data['uri'] = self.uri
        if self.main_link:
            data['link'] = self.main_link
        if self.last_modified:
            data['last-modified'] = email.utils.formatdate(self.last_modified)
        if self.last_confirmed:
            data['last-confirmed'] = email.utils.formatdate(self.last_confirmed)
        if self.etag:
            data['etag'] = self.etag
        data['entries'] = []
        for entry in entries:
            if not self.ignore_time and get_updated(entry) > now:
                continue
            entry_data = {}
            if 'id' in entry:
                entry_data['id'] = entry['id']
            if 'title' in entry:
                entry_data['title'] = entry['title']
            if 'link' in entry:
                entry_data['link'] = entry['link']
            data['entries'].append(entry_data)
        self.entries = data['entries']
        for entry in data['entries']:
            if entry.get('updated_parsed', None):
                entry_data['updated'] = tuple2rfc(entry['updated_parsed'])
        yml = yaml.dump(data,
                        default_flow_style=False,
                        encoding='utf-8',
                        allow_unicode=True)
        open(self._get_cache_filename(), 'w+').write(yml.decode('utf-8'))

    def initialize_cache(self):
        self.last_confirmed = time.time()
        self.save_cache([])
        self.initialized = True

    def is_entry_fresh(self, entry):
        if not self.ignore_time and 'updated_parsed' in entry:
            now = time.time() + FUTURE_THRESHOLD
            return self.last_confirmed < get_updated(entry) < now
        if 'id' in entry:
            return all(entry['id'] != _.get('id', None) for _ in self.entries)
        # TODO: title-link pair might be smarter
        if 'title' in entry:
            return all(entry['title'] != _.get('title', None)
                for _ in self.entries)
        if 'link' in entry:
            return all(entry['link'] != _.get('link', None)
                for _ in self.entries)
        return True

    @limit_time(TIMEOUT_THRESHOLD)
    def _parse_feed(self):
        try:
            return feedparser.parse(
                self.uri,
                etag = self.etag,
                modified = time.gmtime(self.last_modified),
                referrer = self.main_link)
        except Exception:
            print('An error occured while trying to get %s:' % self.uri)
            traceback.print_exc(limit=None)

    def get_fresh_entries(self):
        if not self.initialized:
            self.load_cache()
        entries = self.get_entries()
        # XXX remove duplicate
        fresh_entries = [_ for _ in entries + (self.entries or [])
            if self.is_entry_fresh(_)]
        if not fresh_entries:
            return []
        self.save_cache(entries)
        return fresh_entries

    def get_entries(self):
        feed = self._parse_feed()
        if not feed or not feed['entries']:
            return []
        self.main_link = feed.get('link', None)
        self.etag = feed.get('etag', None)
        if 'updated' in feed:
            self.last_modified = time.mktime(feed['updated'])
        return feed['entries']

    def update_timestamp(self, entries):
        if not entries:     
            return  
        latest = max(get_updated(entry) for entry in entries)
        if latest > self.last_confirmed:     
            self.last_confirmed = latest
        self.save_cache(self.entries)

class EntryFormatter(object):
    """format feed entry into an irc packet."""

    def __init__(self, target, message_format, arguments=None, digest=False):
        assert isinstance(target, str)
        assert isinstance(message_format, str)
        self.target = target
        self.format = message_format
        self.arguments = arguments or {}
        self.digest = digest

    def format_entry(self, entry):
        msg = self.format % self.build_arguments(entry)
        opt = {
            'timestamp': get_updated(entry)
        }
        return (self.target, msg, opt)

    def format_entries(self, entries):
        if self.digest:
            for result in self.digest_entries(entries):
                yield result
        else:
            for entry in entries:
                result = self.format_entry(entry)
                if result:
                    yield result

    def digest_entries(self, entries):
        msg_buffer = ''
        delimiter = ' | '
        titles = set()
        for entry in entries:
            args = self.build_arguments(entry)
            match = re.match(r'(?P<title>.*?)(\(.+\))?(\.\w+)?', args['title'])
            titles.add(match.group('title'))
        for title in titles:
            if not title:
                continue
            msg = '\x02%s\x02' % title
            if len(msg_buffer) + len(delimiter) + len(msg) > MAX_CHAR:
                yield (self.target, msg_buffer, {})
                msg_buffer = ''
            msg_buffer += delimiter if msg_buffer else '[%(name)s]' % args # XXX
            msg_buffer += msg
            if len(msg_buffer) > MAX_CHAR:
                yield (self.target, msg_buffer, {})
                msg_buffer = ''
        if msg_buffer:
            yield (self.target, msg_buffer, {})

    def build_arguments(self, entry):
        result = defaultdict(str)
        for key, val in self.arguments.items():
            result[key] = val
        result['link'] = entry.get('link', '')
        if 'updated_parsed' not in entry:
            result['time'] = 'datetime unknown'
        else:
            # XXX timezone should be customizable
            result['time'] = datetime.datetime.fromtimestamp(
                    get_updated(entry),
                    KoreanStandardTime()).isoformat(' ')
        if 'title' in entry:
            result['title'] = entry['title'].replace('\n', ' ')
        return result

class FeedManager(object):
    def __init__(self, file_path, fetcher_class=FeedFetcher,
                 formatter_class=EntryFormatter):
        self.file_path = os.path.join(FILE_PATH, file_path)
        self.fetcher_class = fetcher_class
        self.formatter_class = formatter_class
        self.fetcher = {}

    def load(self):
        self.fetcher = {}
        formats = self.load_formats()
        data = self.load_data()
        if not data:
            return
        for entry in data:
            if 'format' in entry and entry['format'] in formats:
                entry['format'] = formats[entry['format']]
            key = self._get_entry_key(entry)
            if key not in self.fetcher:
                self.fetcher[key] = self.fetcher_class(
                    uri=entry['uri'],
                    ignore_time = entry.get('ignore_time', False),
                    frequent = entry.get('frequent', False)
                )
            for target in entry['targets']:
                formatter = self.formatter_class(
                    target=target.strip(),
                    message_format=entry['format'],
                    arguments={'name': entry['name']},
                    digest=entry.get('digest', False)
                )
                yield (self.fetcher[key], formatter)

    def _get_entry_key(self, entry):
        return (entry['uri'], entry.get('ignore_time', False))

    def load_data(self):
        if not os.access(self.file_path, os.F_OK):
            return None
        try:
            return yaml.load(open(self.file_path).read())
        except Exception:
            traceback.print_exc()

    def load_formats(self):
        return yaml.load(open(os.path.join(FILE_PATH, 'format.yml')))

    def reload(self):
        fetcher_old = self.fetcher
        self.fetcher = {}
        formats = self.load_formats()
        data = self.load_data()

manager = FeedManager('general.yml')

