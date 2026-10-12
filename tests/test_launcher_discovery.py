import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

@unittest.skipUnless(os.name=='nt','Native Windows VBS launcher')
class NativeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.launcher=self.root/'Launchers'/'OPEN-DISCORD-ARCHIVE.vbs';self.launcher.parent.mkdir()
        shutil.copy2(Path(__file__).resolve().parents[1]/self.launcher.name,self.launcher)
    def tearDown(self):self.temp.cleanup()
    def studio(self,path):
        for item in ('runtime/pythonw.exe','app.py','studio/server.py','web/index.html'):
            f=path/item;f.parent.mkdir(parents=True,exist_ok=True);f.touch()
        return path
    def locate(self):return subprocess.run(['cscript.exe','//Nologo',str(self.launcher),'/locate'],capture_output=True,text=True,timeout=15)
    def test_containing_app_survives_a_whole_folder_move(self):
        app=self.studio(self.launcher.parent);moved=self.root/'Moved app';app.rename(moved);self.launcher=moved/self.launcher.name
        result=self.locate();self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),str(moved))
    def test_depth_six_is_found_and_depth_seven_is_not(self):
        deep=self.studio(self.root.joinpath(*['level'+str(n) for n in range(6)]))
        result=self.locate();self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),str(deep))
        deeper=deep/'level6';deeper.mkdir()
        for name in ('runtime','studio','web','app.py'):shutil.move(str(deep/name),str(deeper/name))
        result=self.locate();self.assertEqual(result.returncode,1,result.stdout)
    def test_multiple_copies_require_an_explicit_choice(self):
        self.studio(self.root/'One');self.studio(self.root/'Two')
        result=self.locate();self.assertEqual(result.returncode,2,result.stderr);self.assertIn('More than one',result.stdout)
