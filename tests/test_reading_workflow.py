import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from studio.store import Store
from studio.zipreader import ZipReader
from studio.reader_library import library_id
from studio.author_view import author_view
from studio.local_cache import LocalCache
from test_studio import SID,CID,UID,message


class ReadingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Path(self.temp.name)
        self.store=Store(self.app/'Data');self.store.catalog([{'id':SID,'name':'Fixture'}],[{'id':CID,'name':'general'}],SID)
        self.reader=ZipReader(self.store,app_root=self.app);self.key=library_id(SID)
        rows=[]
        for i in range(100):
            m=message(9000+i,'needle');m['timestamp']='2026-04-11T00:%02d:%02dZ'%(i//60,i%60);rows.append(m)
        self.store.upsert(CID,rows)
    def tearDown(self):self.temp.cleanup()
    def test_calendar_reuses_generation_and_invalidates_on_edit_and_add(self):
        params={'channel':CID,'month':'2026-04','day':'2026-04-11'}
        first=self.reader.query(self.key,'calendar',params)
        with patch('studio.reader_library._query',side_effect=AssertionError('Cache missed')):
            self.assertEqual(first,self.reader.query(self.key,'calendar',params))
        edited=message(9000,'changed');edited['timestamp']='2026-04-12T00:00:00Z';self.store.upsert(CID,[edited])
        changed=self.reader.query(self.key,'calendar',params)
        self.assertNotEqual(first['generation'],changed['generation']);self.assertEqual(changed['days'][0]['messages'],99)
        self.store.upsert(CID,[message(9500)])
        self.assertEqual(self.store.channels()[0]['count'],101);self.assertEqual(self.store.servers()[0]['messages'],101)
    def test_message_jump_retains_exact_semantics_and_optional_context(self):
        exact=self.reader.query(self.key,'messages',{'channel':CID,'message':'9050'})
        context=self.reader.query(self.key,'messages',{'channel':CID,'message':'9050','surrounding':'1'})
        self.assertEqual(exact['messages'][0]['id'],'9050');self.assertEqual(context['messages'][0]['id'],'9040')
        self.assertIn('9050',[m['id'] for m in context['messages']]);self.assertTrue(context['before'])
    def test_count_cache_invalidation_after_message_changes_channel(self):
        other=str(int(CID)+1);self.store.catalog([], [{'id':other,'name':'other'}],SID)
        self.store.channels();m=message(9000);m['channel_id']=other;self.store.upsert(other,[m])
        counts={c['id']:c['count'] for c in self.store.channels()};self.assertEqual(counts[CID],99);self.assertEqual(counts[other],1)
    def test_captured_names_share_stable_id_without_remote_enumeration(self):
        renamed=message(9500);renamed['author']['username']='New name';self.store.upsert(CID,[renamed])
        with patch('studio.discord.Discord.get',side_effect=AssertionError('Must remain local')):
            result=author_view(self.store,self.reader,UID,self.key)
        self.assertIn('Alice',result['names']);self.assertIn('New name',result['names']);self.assertEqual(result['id'],UID);self.assertEqual(result['messages'],101)
        with self.assertRaises(ValueError):author_view(self.store,self.reader,'unsafe')
    def test_local_cache_is_bounded_and_does_not_share_mutable_responses(self):
        cache=LocalCache(3);result=cache.get('a',lambda:{'rows':[1]});result['rows'].append(2)
        self.assertEqual(cache.get('a',lambda:None),{'rows':[1]})
        for i in range(20):cache.get(i,lambda:i)
        self.assertEqual(len(cache.values),3)
    def test_search_total_cache_is_invalidated_after_edit(self):
        first=self.reader.query(self.key,'messages',{'channel':CID,'q':'needle'});self.assertEqual(first['total'],100)
        edited=message(9000,'haystack');edited['timestamp']='2026-04-11T00:00:00Z';self.store.upsert(CID,[edited])
        self.assertEqual(self.reader.query(self.key,'messages',{'channel':CID,'q':'needle'})['total'],99)

    def test_saved_reading_cursor_includes_anchor_after_new_messages_arrive(self):
        first=self.store.search(limit=5);anchor=first['messages'][-1]
        newer=message(9999);newer['timestamp']='2026-04-12T00:00:00Z';self.store.upsert(CID,[newer])
        restored=self.store.search(cursor=anchor['_cursor'],inclusive=True)
        older=self.store.search(cursor=anchor['_cursor'])
        self.assertEqual(restored['messages'][0]['id'],anchor['id']);self.assertNotEqual(older['messages'][0]['id'],anchor['id'])

    def test_explicit_identity_link_invalidates_cached_author_total(self):
        other=str(int(UID)+1);m=message(9500);m['author']={'id':other,'username':'Other account'};self.store.upsert(CID,[m])
        params={'channel':CID,'author':UID}
        self.assertEqual(self.reader.query(self.key,'messages',params)['total'],100)
        self.store.alias(other,UID)
        self.assertEqual(self.reader.query(self.key,'messages',params)['total'],101)


if __name__=='__main__':unittest.main()
