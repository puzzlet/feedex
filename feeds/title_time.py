#coding: utf-8
import os.path
import re
from util import force_unicode
from config import FEEDEX_ROOT

def load():
    result = []
    for line in open(os.path.join(FEEDEX_ROOT, 'feeds/title_time.data'), 'r'):
        line = line.strip().decode('utf-8')
        if line.startswith('#'): continue
        if not line: continue
        tokens = re.split(r'\s+', line)
        result.append(parse_share(tokens, False))
    return result

def parse_share(argv, save = False):
    data = {
        'name': argv[0],
        'target': argv[1],
        'uri': argv[2],
    }
    return data['uri'], data

def display(entry, data):
    args = dict(data)
    args['link'] = force_unicode(entry.link)
    args['title'] = force_unicode(entry.title)
    msg = u'[%(name)s] \u0002%(title)s\u0002 (%(time)s)' % args
    return data['target'], msg, {}

channels = set()
for uri, data in load():
    channels.add(data['target'])

