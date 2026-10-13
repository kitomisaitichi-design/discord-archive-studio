import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from studio.store import Store
from studio.exporting import Exporter,options
from studio.zipreader import ZipReader
from test_studio import SID,CID,UID,message


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.parent=Path(self.temp.name);self.app=self.parent/'App';self.app.mkdir()
        self.store=Store(self.app/'Data');self.store.catalog([{'id':SID,'name':'Fixture'}],[{'id':CID,'name':'general'}],SID)
        self.exporter=Exporter(self.store);self.reader=ZipReader(self.store,app_root=self.app)
    def tearDown(self):self.temp.cleanup()
    def zip(self,path):
        path.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(path,'w') as z:z.writestr('chat.json',json.dumps({'channel':{'id':CID,'name':'general'},'guild':{'id':SID},'messages':[message(9001)]}))
        return path
    def test_existing_index_reads_without_zip_import_copy_or_network(self):
        rows=[]
        for i in range(350):
            m=message(9000+i,'cached needle' if i%2==0 else 'other');m['timestamp']='2026-04-11T%02d:%02d:00Z'%(i//60,i%60);rows.append(m)
        self.store.upsert(CID,rows)
        key=self.reader.catalogue()[0]['id'];self.assertEqual(self.reader.catalogue()[0]['source'],'library')
        with patch.object(self.reader,'build',side_effect=AssertionError('Must reuse canonical index')),patch('studio.discord.Discord.get',side_effect=AssertionError('Must stay local')):
            overview=self.reader.query(key,'overview',{});self.assertEqual(overview['channels'][0]['messages'],350)
            cal=self.reader.query(key,'calendar',{'channel':CID,'month':'2026-04','day':'2026-04-11'})
            self.assertEqual(cal['days'][0]['messages'],350);self.assertEqual(cal['hours'][0]['messages'],60)
            start=self.reader.query(key,'messages',{'channel':CID,'day':'2026-04-11','hour':2})
            self.assertEqual(start['messages'][0]['id'],'9120');self.assertEqual(len(start['messages']),80)
            later=self.reader.query(key,'messages',{'channel':CID,'after':start['last']});self.assertEqual(later['messages'][0]['id'],'9200')
            earlier=self.reader.query(key,'messages',{'channel':CID,'before':start['first']});self.assertEqual(earlier['messages'][-1]['id'],'9119')
            self.assertEqual(self.reader.query(key,'messages',{'channel':CID,'q':'needle'})['total'],175)
            self.assertEqual(self.reader.query(key,'messages',{'channel':CID,'q':'Alice'})['total'],350)
            self.assertEqual(self.reader.query(key,'messages',{'channel':CID,'message':'9100'})['messages'][0]['id'],'9100')
            with self.assertRaises(ValueError):self.reader.query(key,'messages',{'channel':CID,'before':'unsafe!'})
        self.assertEqual(self.store.stats()['messages'],350);self.assertEqual(list(self.reader.root.glob('*.sqlite3')),[])
    def test_library_includes_saved_data_excluded_from_zip_view(self):
        m=message(9001);m['timestamp']='2026-04-11T00:00:00Z';self.store.upsert(CID,[m])
        self.exporter.publish(SID,options({'start':'2026-05-01'}),self.app/'Exports')
        catalogue=self.reader.catalogue();library=next(e for e in catalogue if e['source']=='library');archive=next(e for e in catalogue if e['source']=='export')
        self.assertEqual(self.reader.query(library['id'],'overview',{})['channels'][0]['messages'],1)
        self.assertEqual(self.reader.query(archive['id'],'overview',{})['channels'][0]['messages'],0)
    def test_unrecorded_zip_depth_limits_exclusions_and_scan_cache(self):
        inside=self.zip(self.parent/'old'/'one'/'two'/'three'/'four'/'five'/'six.zip')
        outside=self.zip(self.parent/'old'/'one'/'two'/'three'/'four'/'five'/'six'/'seven.zip')
        # Parent depth six includes files in six descendant directories, not seven.
        too_deep=self.zip(self.parent/'old'/'one'/'two'/'three'/'four'/'five'/'six'/'seven'/'hidden.zip')
        self.zip(self.app/'Data'/'private.zip');self.zip(self.parent/'Discord-Archive-Studio-v1.3.0-Source.zip')
        items=self.reader.catalogue();paths={e['path'] for e in items}
        self.assertIn(str(inside.resolve()),paths);self.assertNotIn(str(outside.resolve()),paths);self.assertNotIn(str(too_deep.resolve()),paths)
        self.assertFalse(any('private.zip' in p or '-Source.zip' in p for p in paths))
        with patch('studio.zipreader.os.walk',side_effect=AssertionError('Unchanged folder inventory rescanned')):self.reader.catalogue()
        self.zip(self.parent/'new.zip');self.assertFalse(any(e['path'].endswith('new.zip') for e in self.reader.catalogue()))
        self.assertTrue(any(e['path'].endswith('new.zip') for e in self.reader.catalogue(refresh=True)))
    def test_known_path_dedup_destination_change_relocation_and_unrelated_zip(self):
        self.store.upsert(CID,[message(9001)]);result=self.exporter.publish(SID,options(None),self.app/'Exports')
        self.assertEqual(len([e for e in self.reader.catalogue() if e['path']==result['path']]),1)
        destination=self.parent/'Elsewhere';p=self.zip(destination/'saved.zip');self.store.set_setting('destination',str(destination))
        self.assertTrue(any(e['path']==str(p.resolve()) for e in self.reader.catalogue()))
        moved=self.parent/'Moved'/'App';moved.parent.mkdir();shutil.copytree(self.app,moved)
        relocated=Store(moved/'Data');reader=ZipReader(relocated,app_root=moved)
        self.assertTrue(any(e['path']==str((moved/'Exports'/Path(result['path']).name).resolve()) for e in reader.catalogue()))
        other=self.parent/'unrelated.zip'
        with zipfile.ZipFile(other,'w') as z:z.writestr('note.txt','not a message export')
        self.assertFalse(any(e['path']==str(other.resolve()) for e in self.reader.catalogue(refresh=True)))


if __name__=='__main__':unittest.main()
