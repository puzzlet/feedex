#coding: utf-8
import os.path
import re
from util import force_unicode

FILE_PATH = os.path.dirname(__file__)

def load():
    format = {}
    for line in open(os.path.join(FILE_PATH, 'format'), 'r'):
        line = line.strip().decode('utf-8')
        if line.startswith('#'):
            continue
        if ' ' not in line:
            continue
        tokens = re.split(r'\s+', line, 1)
        format[tokens[0]] = tokens[1]
    result = []
    for line in open(os.path.join(FILE_PATH, 'general.data'), 'r'):
        line = line.strip().decode('utf-8')
        if line.startswith('#'):
            continue
        if not line:
            continue
        tokens = re.split(r'\s+', line)
        result.append(parse(tokens, format))
    return result

def parse(argv, format):
    data = {
        'name': argv[0],
        'target': argv[1],
        'format': format[argv[2]],
        'uri': argv[3],
        }
    return data['uri'], data

def display(entry, data):
    kwargs = dict(data)
    kwargs['bold'] = '\x02'
    kwargs['link'] = force_unicode(entry.link)
    kwargs['title'] = force_unicode(entry.title)
    msg = kwargs['format'] % kwargs
    return data['target'], msg, {}

channels = set()
for uri, data in load():
    channels.add(data['target'])
 
