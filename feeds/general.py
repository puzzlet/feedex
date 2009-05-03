#coding: utf-8
import os.path
import re
import time
import calendar
from util import force_unicode, parse_feed, trace
from util import TimedOutException
try: # preparing for Python 3.0
    from urllib.parse import quote
except ImportError:
    from urllib import quote

FILE_PATH = os.path.dirname(__file__)

class FeedFetcher(object):
    def __init__(self, uri):
        self.uri = uri
        self.timestamp = 0
        self.id_set = set() # {}
        self.load_timestamp()

    def __hash__(self):
        return self.uri.__hash__()

    def _get_timestamp_filename(self):
        return os.path.join(FILE_PATH, '../timestamps', quote(self.uri, ''))

    def load_timestamp(self):
        now = time.time()
        file_name = self._get_timestamp_filename()
        if not os.access(file_name, os.F_OK):
            self.last_updated = now
            self.save_timestamp()
            return
        try:
            f = open(file_name, 'r')
            timestamp = float(f.next().strip())
            for line in f:
                id = line.strip()
                if not id:
                    continue
                self.id_set.add(id)
            f.close()
            if timestamp > now: # + config.FUTURE_THRESHOLD:
                self.last_updated = now
                self.save_timestamp()
                return
            self.last_updated = timestamp
        except:
            pass

    def save_timestamp(self):
        file_name = self._get_timestamp_filename()
        f = open(file_name, 'w+')
        f.write(str(self.last_updated))
        f.write('\n')
        f.write('\n'.join(self.id_set).encode('utf-8'))
        f.write('\n')
        f.close()

    def is_entry_fresh(self, entry):
        if entry.get('updated_parsed', None):
            # assuming entry.updated_parsed is UTC:
            t = calendar.timegm(entry.updated_parsed)
            return self.last_updated < t < time.time()
        if entry.get('id', None):
            return entry.id not in self.id_set
        if entry.get('link', None):
            return entry.link not in self.id_set
        return True

    def get_entries(self):
        try:
            feed = parse_feed(str(self.uri))
        except TimedOutException:
            trace('Timed out while parsing %s' % self.uri)
            return []
        except LookupError:
            trace('Invalid character in %s' % self.uri)
            return []
        except UnicodeDecodeError:
            trace('Invalid character in %s' % self.uri)
            return []
        feed.entries.reverse()
        fresh_entries = [entry for entry in feed.entries if self.is_entry_fresh(entry)]
        if not fresh_entries:
            return []
        max_timestamp = 0
        new_id_set = set() # {}
        for entry in feed.entries:
            key = entry.get('id', None) or entry.get('link', None)
            if key:
                new_id_set.add(key)
            if entry.get('updated_parsed', None):
                # assuming entry.updated_parsed is UTC
                t = calendar.timegm(entry.updated_parsed)
                if t > max_timestamp:
                    max_timestamp = t
            else:
                max_timestamp = time.time()
        if self.last_updated < max_timestamp:
            self.last_updated = max_timestamp
        if new_id_set:
            self.id_set = new_id_set
        self.save_timestamp()
        return fresh_entries

def load():
    format = {}
    for line in open(os.path.join(FILE_PATH, 'format'), 'r'):
        line = line.strip().decode('utf-8')
        if line.startswith('#'):
            continue
        if ' ' not in line:
            continue
        tokens = re.split(r'\s\s+', line, 1)
        format[tokens[0]] = tokens[1]
    result = []
    for line in open(os.path.join(FILE_PATH, 'general.data'), 'r'):
        line = line.strip().decode('utf-8')
        if line.startswith('#'):
            continue
        if not line:
            continue
        tokens = re.split(r'\s\s+', line)
        for item in parse(tokens, format):
            result.append(item)
    return result

def parse(argv, format):
    for target in argv[1].split(','):
        data = {
            'name': argv[0],
            'target': target.strip(),
            'format': format[argv[2]],
            'uri': argv[3],
        }
        yield (FeedFetcher(data['uri']), data)

def display(entry, data):
    kwargs = dict(data)
    kwargs['bold'] = '\x02'
    kwargs['link'] = force_unicode(entry.get('link', ''))
    kwargs['title'] = force_unicode(entry.title)
    msg = kwargs['format'] % kwargs
    return data['target'], msg, {}

channels = set()
for uri, data in load():
    channels.add(data['target'])

