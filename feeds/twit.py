#coding: utf-8

import os.path
import email.utils
import twitter
import getpass

from util import KoreanStandardTime
from feeds.general import FeedFetcher, EntryFormatter, FeedManager

FILE_PATH = os.path.dirname(__file__)

class TwitterFetcher(FeedFetcher):
    def __init__(self, user, password, friends=[]):
        super(TwitterFetcher, self).__init__(uri='Twitter',
                                             ignore_time=False,
                                             frequent=False)
        self.user = user
        self.api = twitter.Api(username=user, password=password)
        self.cache = {}
        for friend in friends:
            self.cache[friend] = FeedFetcher('http://twitter.com/%s' % friend,
                                             ignore_time=False,
                                             frequent=False)

    def get_entries(self):
        timeline = self.api.GetFriendsTimeline(self.user)
        entries = []
        for status in timeline:
            entries.append({
                'user': status.user.screen_name,
                'text': status.text,
                'title': status.text, # XXX
                'link': '', # XXX
                'updated_parsed': email.utils.parsedate(status.created_at)
            })
        return entries

    def get_fresh_entries(self):
        all_entries = self.get_entries()
        result = []
        for friend, cache in self.cache.iteritems():
            if not cache.initialized:
                cache.load_cache()
            entries = [_ for _ in all_entries if _['user'] == friend]
            # XXX remove duplicate
            fresh_entries = [_ for _ in entries + cache.entries \
                if cache.is_entry_fresh(_)]
            if not fresh_entries:
                continue
            cache.save_cache(entries)
            for entry in fresh_entries:
                result.append(entry)
        return result

    def update_timestamp(self, entries):
        for _, cache in self.cache.iteritems():
            cache.update_timestamp(entries)

class TwitterFormatter(EntryFormatter):
    def __init__(self, target, user_name):
        super(TwitterFormatter, self).__init__(
            target=target,
            message_format=u'%(user)s: %(title)s (%(time)s)'
        )
        self.user_name = user_name

    def format_entry(self, entry):
        print entry
        user_name = entry['user']
        if isinstance(self.user_name, list):
            if user_name not in self.user_name:
                return
        elif user_name != self.user_name:
            return
        return super(TwitterFormatter, self).format_entry(entry)

    def build_arguments(self, entry):
        result = super(TwitterFormatter, self).build_arguments(entry)
        result['user'] = entry['user']
        return result

class TwitterManager(FeedManager):
    def __init__(self, file_path):
        super(TwitterManager, self).__init__(
            file_path=os.path.join(FILE_PATH, file_path),
            fetcher_class=TwitterFetcher,
            formatter_class=TwitterFormatter)
        self.fetcher = {}

    def load(self):
        format = self.load_formats()
        data = self.load_data()
        friends = []
        for entry in data['entry']:
            for user in entry['user']:
                friends.append(user)
        for user in data['user']:
            if user not in self.fetcher:
                prompt = "Twitter password for %s: " % user
                self.fetcher[user] = self.fetcher_class(
                    user=user,
                    password=getpass.getpass(prompt),
                    friends=friends
                )
        for entry in data['entry']:
            for target in entry['targets']:
                formatter = self.formatter_class(
                    target=target.strip(),
                    user_name=entry['user']
                )
                for user in data['user']:
                    yield (self.fetcher[user], formatter)

manager = TwitterManager('twit.yml')

