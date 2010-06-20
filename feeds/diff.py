import difflib
import itertools
import re

from .general import EntryFormatter

class DiffFormatter(EntryFormatter):
    def __init__(self, target, message_format='%(title)s'):
        EntryFormatter.__init__(self, target=target, message_format=message_format)
        self.last_message = ''

    def format_entries(self, entries):
        if not entries:
            return
        message = entries[0]['title']
        if self.last_message:
            generator = self.format_diff(self.last_message, message)
        else:
            self.last_message = message
            generator = message.split('\n')
        for line in generator:
            yield (self.target, line, {})
        self.last_message = message

    @classmethod
    def format_diff(cls, str1, str2):
        """Format line-by-line difference in mIRC color."""
        a = str1.split('\n')
        b = str2.split('\n')
        diff = difflib.SequenceMatcher(None, a, b)
        for tag, i1, i2, j1, j2 in diff.get_opcodes():
            if tag == 'equal':
                continue
            if tag == 'delete':
                for line in a[i1:i2]:
                    yield '\x0304{0}\x03'.format(line)
            if tag == 'insert':
                for line in b[j1:j2]:
                    yield '\x0303{0}\x03'.format(line)
            if tag == 'replace':
                for sub_a, sub_b in itertools.zip_longest(a[i1:i2], b[j1:j2],
                        fillvalue=''):
                    line = ''.join(cls.format_diff_line(sub_a, sub_b))
                    if line:
                        yield line

    @classmethod
    def format_diff_line(cls, str1, str2):
        """Format per-line difference in mIRC color."""
        a = re.split(r'(\s+)', str1)
        b = re.split(r'(\s+)', str2)
        diff = difflib.SequenceMatcher(None, a, b)
        for tag, i1, i2, j1, j2 in diff.get_opcodes():
            if tag == 'equal':
                yield ''.join(b[j1:j2])
            if tag in ['delete', 'replace']:
                yield '\x0304{0}\x03\x02\x02'.format(''.join(a[i1:i2]))
            if tag in ['insert', 'replace']:
                yield '\x0303{0}\x03\x02\x02'.format(''.join(b[j1:j2]))

