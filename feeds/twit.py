#coding: utf-8
import os.path
import imp
import email.utils
import getpass
import tweepy
from collections import defaultdict

FILE_PATH = os.path.dirname(__file__)

# dynamically import feeds.general
# ../feed.py should handle any exception
_ = imp.find_module('general', [FILE_PATH])
feeds_general = imp.load_module('general', *_)
FeedFetcher = feeds_general.FeedFetcher
EntryFormatter = feeds_general.EntryFormatter
FeedManager = feeds_general.FeedManager

class TwitterFetcher(FeedFetcher):
    def __init__(self, api, friends=None):
        FeedFetcher.__init__(self, uri='Twitter', ignore_time=False,
            frequent=False)
        self.api = api
        self.cache = {}
        for friend in friends or []:
            self.cache[friend] = FeedFetcher('http://twitter.com/%s' % friend,
                ignore_time=False, frequent=False)

    def get_entries(self):
        timeline = self.api.friends_timeline()
        entries = []
        for status in timeline:
            entries.append({
                'user': status.author.screen_name,
                'text': status.text,
                'title': status.text, # XXX
                'link': '', # XXX
                'updated_parsed': status.created_at,
            })
        return entries

    def get_fresh_entries(self):
        all_entries = self.get_entries()
        result = []
        for friend, cache in self.cache.items():
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
        for _, cache in self.cache.items():
            cache.update_timestamp(entries)

class TwitterFormatter(EntryFormatter):
    def __init__(self, target, user_names):
        super(TwitterFormatter, self).__init__(
            target=target,
            message_format='%(user)s: %(title)s (%(time)s)'
        )
        self.user_names = user_names

    def format_entry(self, entry):
        if entry['user'] not in self.user_names:
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
        self.api = {}

    def load(self):
        data = self.load_data()
        if not data:
            return
        friends = set()
        list_members = defaultdict(set)
        for user_name in data['user']:
            password = getpass.getpass("Twitter password for %s: " % user_name)
            self.api[user_name] = tweepy.API(tweepy.BasicAuthHandler(user_name,
                password))
        for entry in data['entry']:
            for user in entry.get('user', []):
                friends.add(user)
            for owner_slug in entry.get('list', []):
                owner, _, slug = owner_slug.partition('/')
                api = self.api[owner] # XXX
                cursor = -1
                while cursor:
                    users, cursor, _ = api.list_members(owner=owner, slug=slug,
                        cursor=cursor)
                    for user in users:
                        list_members[owner_slug].add(user.screen_name)
                for user_name in list_members[owner_slug]:
                    friends.add(user_name)
        for user_name in data['user']:
            if user_name not in self.fetcher:
                self.fetcher[user_name] = self.fetcher_class(
                    api=self.api[user_name],
                    friends=friends)
        for entry in data['entry']:
            user_names = set()
            for owner_slug in entry.get('list', []):
                for user_name in list_members[owner_slug]:
                    user_names.add(user_name)
            for user in entry.get('user', []):
                user_names.add(user)
            for target in entry['targets']:
                formatter = self.formatter_class(
                    target=target.strip(),
                    user_names=user_names)
                for user in data['user']:
                    yield (self.fetcher[user], formatter)
                    # XXX duplicate entries when multiple data['user']

    def reload(self):
        pass # TODO

manager = TwitterManager('twit.yml')

