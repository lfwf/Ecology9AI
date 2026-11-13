import sys,unittest,struct,zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_public_tree import inspect_bytes
class PublicTreeTests(unittest.TestCase):
 def test_private_address_and_identity_are_blocked(self):
  self.assertIn('private_address',inspect_bytes('example.py',b'server="192.'+b'168.1.9"'))
  self.assertIn('local_marker',inspect_bytes('example.py',b'PRIVATE_LOCAL_MARKER',('PRIVATE_LOCAL_MARKER',)))
 def test_only_reserved_example_emails_are_allowed(self):
  self.assertEqual(inspect_bytes('example.json',b'{"email":"maintainers@example.invalid"}'),[])
  self.assertIn('nonexample_email',inspect_bytes('example.json',b'{"email":"real.person@'+b'company.com"}'))
 def test_data_and_credential_files_are_blocked(self):
  self.assertIn('excluded_artifact',inspect_bytes('connection.json',b'{}'))
  self.assertIn('excluded_artifact',inspect_bytes('.local/evidence.json',b'{}'))
 def test_unreviewed_binary_is_blocked(self):
  self.assertIn('unreviewed_binary',inspect_bytes('unknown.bin',b'\xff\xff'))
 def test_generated_png_metadata_is_blocked(self):
  def chunk(kind,data):
   body=kind+data
   return struct.pack('>I',len(data))+body+struct.pack('>I',zlib.crc32(body)&0xffffffff)
  raw=b'\x89PNG\r\n\x1a\n'+chunk(b'tEXt',b'Author\x00Example')+chunk(b'IEND',b'')
  self.assertIn('image_metadata',inspect_bytes('avatar.png',raw))
  provenance=b'\x89PNG\r\n\x1a\n'+chunk(b'caBX',b'provenance')+chunk(b'IEND',b'')
  self.assertIn('image_metadata',inspect_bytes('avatar.png',provenance))
