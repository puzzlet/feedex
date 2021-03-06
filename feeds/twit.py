#coding: utf-8
import datetime
import email.utils
import getpass
import html.entities
import http.client
import imp
import os.path
import re
import traceback
import zlib

from collections import defaultdict

import tweepy

FILE_PATH = os.path.dirname(__file__)

from .general import FeedFetcher, EntryFormatter, FeedManager

class TwitterFetcher(FeedFetcher):
    def __init__(self, api, friends=None):
        FeedFetcher.__init__(self, uri='Twitter', ignore_time=False,
            frequent=False)
        self.api = api
        self.cache = {}
        self.next_fetch = datetime.datetime.now()
        self.fetch_period = datetime.timedelta(seconds=180)
        for friend in friends or []:
            self.cache[friend] = FeedFetcher('http://twitter.com/%s' % friend,
                ignore_time=False, frequent=False)

    def get_entries(self):
        try:
            timeline = self.api.friends_timeline()
        except http.client.HTTPException:
            traceback.print_exc()
            return
        except tweepy.error.TweepError as e:
            traceback.print_exc()
            self.fetch_period *= 2
            self.next_fetch += self.fetch_period
            return
        self.fetch_period = datetime.timedelta(seconds=180)
        self.next_fetch = datetime.datetime.now() + self.fetch_period
        entries = []
        for status in timeline:
            entries.append({
                'user': status.author.screen_name,
                'text': status.text,
                'title': status.text, # XXX
                'link': '', # XXX
                'updated': status.created_at.isoformat(' '),
                'updated_parsed': status.created_at.timetuple(),
            })
        return entries

    def get_fresh_entries(self):
        if datetime.datetime.now() < self.next_fetch:
            return None
        all_entries = self.get_entries()
        result = []
        for friend, cache in self.cache.items():
            if not cache.initialized:
                cache.load_cache()
            entries = [_ for _ in (all_entries or []) if _['user'] == friend]
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
        users = set(_['user'] for _ in entries)
        for user, cache in self.cache.items():
            if user in users:
                cache.update_timestamp(entries)

def format_nick(nick):
    colors = [3, 4, 5, 6, 7, 9, 10, 11, 12, 13]
    color = colors[zlib.adler32(nick.encode('utf-8')) % len(colors)]
    return '\x03{color:02}{nick}\x03\x02\x02'.format(
        color=color,
        nick=nick,
    )

def nick_repl(match):
    return format_nick(match.group(1))

def entity_repl(match):
    return html.entities.entitydefs[match.group(1)]

class TwitterFormatter(EntryFormatter):
    def __init__(self, targets, user_names=None, matches=None):
        EntryFormatter.__init__(
            self,
            targets=targets,
            message_format='{user}: {title} ({time})')
        self.user_names = [_.lower() for _ in user_names or []]
        self.matches = matches or []

    def format_entry(self, entry):
        if len(self.user_names):
            if entry['user'].lower() not in self.user_names:
                return
        if len(self.matches):
            if not any(re.match(_, entry['title']) for _ in self.matches):
                return
        return EntryFormatter.format_entry(self, entry)

    def build_arguments(self, entry):
        result = EntryFormatter.build_arguments(self, entry)
        result['title'] = re.sub(r'&(\w+);', entity_repl, result['title'])
        result['title'] = re.sub(
            r'(?<=@)(\w+)',
            nick_repl,
            result['title'])
        result['user'] = format_nick(entry['user'])
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
            auth = tweepy.OAuthHandler(data['consumer_key'],
                data['consumer_secret'])
            url = auth.get_authorization_url()
            print('')
            print('Authorization URL: {0}'.format(url))
            verifier = input('Input verifier PIN: ')
            auth.get_access_token(verifier)
            self.api[user_name] = tweepy.API(auth)
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
            formatter = self.formatter_class(
                targets=entry['targets'],
                user_names=user_names,
                matches=entry.get('match', []))
            for user in data['user']:
                yield (self.fetcher[user], formatter)
                # XXX duplicate entries when multiple data['user']

    def reload(self):
        pass # TODO

manager = TwitterManager('twit.yml')

