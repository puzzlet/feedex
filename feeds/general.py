#coding: utf-8
import os.path
import re
from util import force_unicode
from config import FEEDEX_ROOT

def load():
    result = []
    for line in open(os.path.join(FEEDEX_ROOT, 'feeds/general.data'), 'r'):
        line = line.strip().decode('utf-8')
        if line.startswith('#'): continue
        if not line: continue
        tokens = re.split(r'\s+', line)
        result.append(parse(tokens))
    return result

def parse(argv):
    data = {
        'name': argv[0],
        'target': argv[1],
        'uri': argv[2],
        }
    return data['uri'], data

def display(entry, data):
    kwargs = dict(data)
    kwargs['link'] = force_unicode(entry.link)
    kwargs['title'] = force_unicode(entry.title)
    msg = u'[%(name)s] \u0002%(link)s\u0002 [%(title)s] (%(time)s)' % kwargs
    return data['target'], msg, {}

channels = set()
for uri, data in load():
    channels.add(data['target'])
 
