import mset

from pathlib import Path
import socket
import os
import json
import uuid
import ctypes
from ctypes import wintypes

# Constants
WZRD_APPDATA = Path().home() / 'AppData' / 'Roaming' / 'blender_assetwzrd'

WZRD_APPDATA_TEMP_DIR = WZRD_APPDATA / 'disposable'
WZRD_APPDATA_PORTS_DIR = WZRD_APPDATA / 'ports'

BL_PORT_FILE = WZRD_APPDATA_PORTS_DIR / 'blender_mset.prt'


# ================ THE DFINITIVE ANSWER: ====================
# target_layer.maps.mask['channel'].texture = tex

"""
def retreive_active_layer():
	# print(type(mset.getSelectedObjects()[0]) == mset.TextureProjectObject)
	for obj in mset.getSelectedObjects():
		if type(obj) == mset.TextureProjectObject:
			return obj.getActiveLayer()

	return None
"""

def window_msg(msg, flags=None):
	# https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-messageboxw
	if globals()['mute_popus_cbox'].value:
		return
	prototype = ctypes.WINFUNCTYPE(
		ctypes.c_int,
		wintypes.HWND,
		wintypes.LPCWSTR,
		wintypes.LPCWSTR,
		wintypes.UINT
	)
	paramflags = (
		(1, 'hwnd', 0),
		(1, 'text', 'Hi'),
		(1, 'caption', 'Asset Wizard'),
		(1, 'flags', 0)
	)
	MessageBox = prototype(
		('MessageBoxW', ctypes.windll.user32),
		paramflags
	)
	# 0x00000010
	flags = ([flags,] if type(flags) == int else flags) or [0x00000000,]
	flag_sum = flags.pop()
	while flags:
		flag_sum |= flags.pop()
	MessageBox(
		flags=flag_sum,
		text=str(msg)
	)
	# ctypes.windll.user32.MessageBoxW(
	# 	0x00000010,
	# 	str(msg),
	# 	'INFO',
	# 	0,
	# )


def print_exception(err):
	import traceback
	try:
		print(
			''.join(
				traceback.format_exception(
					type(err),
					err,
					err.__traceback__
				)
			)
		)
	except Exception as e:
		print(e)


class UnableToEstablishPipe(Exception):
	pass

class DynamicGroupedText:
	"""
		Separate prints into groups, like so::

		    +--------------------------
		    |LOL
		    +--------------------------
		    | ('Printing text',)
		    | ('Printing more text',)
		    | ('Printing another text',)
		    +--------------------------
	"""
	def __init__(self, groupname='', indent=1):
		self.indent = '\t'*indent
		self.groupname = groupname

	def __enter__(self):
		print(f'\n{self.indent}+--------------------------')
		print(f'{self.indent}|{self.groupname}')
		print(f'{self.indent}+--------------------------')
		return self
		
	def __exit__(self, type, value, traceback):
		print(f'{self.indent}+--------------------------\n')

	def print(self, *args):
		print(f'{self.indent}| {args}')


# mat.microsurface.setField('Invert;', False)
class _MatMaker:
	# Wtf
	MAP_NAME_DICT = {
		'albedo':       ('albedo', 'Albedo Map',),
		'ao':           ('occlusion', 'Occlusion Map'),
		'normal':       ('surface', 'Normal Map'),
		'bump':         ('displacement', 'Displacement Map'),
		'rough':        ('microsurface', 'Roughness Map'),
		'gloss':        ('microsurface', 'Roughness Map'),
		'metal':        ('reflectivity', 'Metalness Map'),
		'emission':     ('emission', 'Emissive'),
		# 'emission_fac': (''),
		'alpha':        (''),
	}
	def __init__(self, texture_maps):
		self.texture_maps = texture_maps
		self._mat = None

	@property
	def mat(self):
		if self._mat:
			return self._mat

		self._mat = mset.Material()

		return self._mat

	@property
	def invert_rough(self):
		return self.mat.microsurface.getField('Invert;roughness')

	@invert_rough.setter
	def invert_rough(self, val):
		return self.mat.microsurface.setField('Invert;roughness', val)

	def __get__(self, map_name):
		# if type(map_name) != mset.Texture:
		self.mat


class MatMaker:
	def __init__(self, texture_maps, mat_name=''):
		self.texture_maps = texture_maps
		self._mat = None

		self._material = None

		self.mat_name = mat_name

	@property
	def mat(self):
		if self._mat:
			return self._mat

		self._mat = mset.Material(
			self.mat_name or str(uuid.uuid4())
		)

		return self._mat

	@staticmethod
	def mset_texture(tgt):
		if type(tgt) != mset.Texture:
			return mset.Texture(str(tgt))
		return tgt

	@property
	def albedo(self):
		try:
			return self.mat.albedo.getField('Albedo Map')
		except: return None
	@albedo.setter
	def albedo(self, tgt):
		tex = self.mset_texture(tgt)
		tex.sRGB = True
		return self.mat.albedo.setField(
			'Albedo Map',
			tex
		)


	@property
	def ao(self):
		try:
			return self.mat.occlusion.getField('Occlusion Map')
		except: return None
	@ao.setter
	def ao(self, tgt):
		tex = self.mset_texture(tgt)
		tex.sRGB = True
		return self.mat.occlusion.setField(
			'Albedo Map',
			tex
		)


	@property
	def normal(self):
		try:
			return self.mat.surface.getField('Normal Map')
		except: return None
	@normal.setter
	def normal(self, tgt):
		tex = self.mset_texture(tgt)
		tex.sRGB = False
		return self.mat.surface.setField(
			'Normal Map',
			tex
		)


	@property
	def bump(self):
		try:
			return self.mat.displacement.getField('Displacement Map')
		except: return None
	@bump.setter
	def bump(self, tgt):
		tex = self.mset_texture(tgt)
		tex.sRGB = False
		self.mat.setSubroutine('displacement', 'Height')
		return self.mat.displacement.setField(
			'Displacement Map',
			tex
		)


	@property
	def rough(self):
		try:
			return self.mat.microsurface.getField('Roughness Map')
		except: return None
	@rough.setter
	def rough(self, tgt):
		tex = self.mset_texture(tgt)
		tex.sRGB = False
		self.mat.setSubroutine('microsurface', 'Roughness')
		self.mat.microsurface.setField('Invert;roughness', False)
		self.mat.microsurface.setField('Roughness', 1.0)
		return self.mat.microsurface.setField(
			'Roughness Map',
			tex
		)


	@property
	def gloss(self):
		try:
			return self.mat.microsurface.getField('Roughness Map')
		except: return None
	@gloss.setter
	def gloss(self, tgt):
		tex = self.mset_texture(tgt)
		tex.sRGB = False
		self.mat.setSubroutine('microsurface', 'Roughness')
		self.mat.microsurface.setField('Invert;roughness', True)
		self.mat.microsurface.setField('Roughness', 1.0)
		return self.mat.microsurface.setField(
			'Roughness Map',
			tex
		)


	@property
	def metal(self):
		try:
			return self.mat.reflectivity.getField('Metalness Map')
		except: return None
	@metal.setter
	def metal(self, tgt):
		tex = self.mset_texture(tgt)
		tex.sRGB = False
		self.mat.setSubroutine('reflectivity', 'Metalness')
		self.mat.reflectivity.setField('Metalness', 1.0)
		return self.mat.reflectivity.setField(
			'Metalness Map',
			tex
		)


	@property
	def emission(self):
		try:
			return self.mat.emission.getField('Emissive map')
		except: return None
	@emission.setter
	def emission(self, tgt):
		tex = self.mset_texture(tgt)
		tex.sRGB = False
		self.mat.setSubroutine('emission', 'Emissive')
		return self.mat.emission.setField(
			'Emissive map',
			tex
		)


	@property
	def alpha(self):
		try:
			return self.mat.transparency.getField('Alpha Map')
		except: return None
	@alpha.setter
	def alpha(self, tgt):
		if not tgt:
			return
		self.mat.setSubroutine('transparency', 'Dither')
		self.mat.transparency.setField('Use Albedo Alpha', False)
		if tgt == '$from_albedo_rgb':
			return self.mat.transparency.setField(
				'Alpha Map',
				self.albedo
			)
		if tgt == '$from_albedo':
			self.mat.transparency.setField('Use Albedo Alpha', True)
			return self.mat.transparency.setField(
				'Alpha Map',
				None
			)

		tex = self.mset_texture(tgt)
		tex.sRGB = False
		return self.mat.transparency.setField(
			'Alpha Map',
			tex
		)

	"""
	def __getattr__(self, attrname):
		if hasattr(self, attrname):
			return getattr(self, attrname)
		else:
			return None
	"""

	def create_material(self):
		for map_name, map_path in self.texture_maps.items():
			# todo: THIS IS NOT NEEDED
			eligible = all((
				hasattr(self, map_name),
				not (map_path in ('None', None)),
				map_name != 'gloss',
			))
			if eligible:
				setattr(self, map_name, map_path)

		if not (self.texture_maps['rough'] in ('None', None)):
			self.rough = self.texture_maps['rough']
		elif not (self.texture_maps['gloss'] in ('None', None)):
			self.gloss = self.texture_maps['gloss']

		# WHAT THE FUCK ???????
		# THE FUCK YOU MEAN THIS CLASS HAS NO ATTRIBUTE "bump"????
		# IT'S LITERALLY THERE...
		# IT IS ACCESSIBLE SEPARATELY, BUT NOW WITH hasattr and setattr
		# WHY ????????????????????????????????????????????????????????
		# KYS PLEASE YOU STUPID TWAT
		# if not (self.texture_maps['bump'] in ('None', None)):
		# 	self.bump = self.texture_maps['bump']
		# if not (self.texture_maps['metal'] in ('None', None)):
		# 	self.metal = self.texture_maps['metal']

		self._material = self._mat

	@property
	def material(self):
		if self._material:
			return self._material

		self.create_material()

		self._material = self.mat

		return self._material




class Context:
	def __init__(self):
		self._active_texture_project = None
		self._active_layer = None

	@property
	def active_texture_project(self):
		if self._active_texture_project:
			return self._active_texture_project
	
		for obj in mset.getSelectedObjects():
			if type(obj) == mset.TextureProjectObject:
				self._active_texture_project = obj

		return self._active_texture_project

	@property
	def active_layer(self):
		if self._active_layer:
			return self._active_layer
		
		self._active_layer = self.active_texture_project.getActiveLayer()

		return self._active_layer


class Actions:
	def __init__(self):
		self.context = Context()

	def skip(self, _):
		window_msg(
			f"""Blender says there's nothing to export...""",
			flags=0x00000020
		)
		return {
			'status': 'ok',
			'info': 'Skipped',
		}

	def set_mask_fill(self, payload_data):
		active_layer = self.context.active_layer
		if not active_layer:
			return {
				'status': 'error',
				'info': 'No layer selected',
			}

		try:
			active_layer.maps.mask['channel'].texture
		except:
			return {
				'status': 'error',
				'info': """Selected layer doesn't seem to have a 'Mask' channel""",
			}

		active_layer.maps.mask['channel'].texture = mset.Texture(
			payload_data['albedo']
		)

		return {
			'status': 'ok',
			'info': """Applied mask to active layer""",
		}

	def create_material(self, payload_data):
		# if payload_data['mode'] == 'full_append':

		# Because if findMaterial fails - an exception is raised
		existing_mat = None
		for mat in mset.getAllMaterials():
			if mat.name == payload_data['name']:
				existing_mat = mset.findMaterial(payload_data['name'])
				break

		if existing_mat:
			window_msg(
				f"""Material was already imported. Skipping import, """
				'adding existing shit to the layer stack. '
				"""Delete the material from bin to re-import it.""",
				flags=0x00000020
			)
			fill = self.context.active_texture_project.addLayer('Fill')
			fill.material = existing_mat
			fill.name = existing_mat.name
			return {
				'status': 'ok',
				'info': 'Material already imported',
			}

		mat_maker = MatMaker(payload_data['maps'], payload_data['name'])
		# mat_maker.create_material()
		# mat_maker.material.name = payload_data['name']
		fill = self.context.active_texture_project.addLayer('Fill')
		fill.material = mat_maker.material
		fill.name = mat_maker.material.name
		return {
			'status': 'ok',
			'info': 'Created material',
		}


class BlenderPipe:
	def __init__(self, skt):
		self.skt = skt
		self.skt_rfile = skt.makefile('rb', buffering=0)
		self.skt_wfile = skt.makefile('wb')

		self.actions = Actions()

	def __enter__(self):
		return self

	def __exit__(self, type, value, traceback):
		self.skt_rfile.close()
		self.skt_wfile.close()

	def read_payload(self):
		payload_len = int.from_bytes(
			self.skt_rfile.read(4),
			'little'
		)
		print('Reading payload length:', payload_len)

		return json.loads(
			self.skt_rfile.read(payload_len)
		)

	def send_payload(self, payload):
		payload = json.dumps(payload).encode()
		self.skt_wfile.write(
			len(payload).to_bytes(4, 'little')
		)
		self.skt_wfile.write(
			payload
		)

		self.skt_wfile.flush()

	def run(self):
		payload = self.read_payload()

		print('Received Command:', payload['cmd'])

		try:
			self.send_payload(
				getattr(self.actions, payload['cmd'])(payload['data']) or {
					'status': 'unknown',
					'info': """The function didn't return anything"""
				}
			)
		except Exception as e:
			self.send_payload({
				'status': 'error',
				'info': f'Unknown error: {e}'
			})
			print_exception(e)
			raise e
		





def run_pipe():
	try:
		# assert False
		with DynamicGroupedText('Asset WZRD') as console:
			gprint = console.print

			gprint('Running Asset Wizard Pipe')

			if not BL_PORT_FILE.is_file():
				window_msg(
					f'Unable to read file:\n'
					f'{str(BL_PORT_FILE)} \n'
					'(This file and folder are automatically generated '
					'by the Asset Wizard Blender plugin on Blender startup)\n'
					'Is Blender + Asset Wizard plugin in it running?\n'
					'Does Blender has the rights to write to that folder?\n'
					'Does Marmoset has the rights to read from that folder?\n'
					'Try restarting Blender and making sure Asset Wizard plugin '
					'is enabled... \n'
					'As the last resort - try running Blender and Marmoset '
					'with Admin rights...',
					flags=0x00000010
				)

				msg = 'File blender_mset.prt does not exist. Aborting'
				gprint(msg)
				raise UnableToEstablishPipe(msg)

			tgt_port = int(BL_PORT_FILE.read_text())
			gprint('Connecting to port >', tgt_port, '<')
			with socket.create_connection(('127.0.0.1', tgt_port), timeout=5.0) as skt:
				gprint('Established connection')
				with BlenderPipe(skt) as bl_pipe:
					bl_pipe.run()
	except ConnectionRefusedError as e:
		msg = (
			'Blender connection refused. Is Blender running? '
			'Or are there 2 Blender instances running? '
			'(Multi instance Blender support is planned)'
		)
		print(msg)
		window_msg(msg, flags=0x00000010)
		raise e
	except Exception as e:
		window_msg(
			f'Error. Check console. \n'
			'(Please report any issues on GitHub)',
			flags=0x00000010
		)

		print_exception(e)
		raise e


def main():
	print('Executing MGE', WZRD_APPDATA)

	# Create a window
	wzrd_window = mset.UIWindow('Asset Wizard')
	wzrd_window.width = 76

	# The button that starts the import process.
	wzrd_btn = mset.UIButton()
	wzrd_btn.onClick = run_pipe

	close_btn = mset.UIButton('  Close  ')

	wzrd_btn.setIcon(str(WZRD_APPDATA / 'icon_s64.jpg'))

	wzrd_window.addElement(wzrd_btn)

	wzrd_window.addReturn()

	mute = mset.UICheckBox()
	mute.label = 'Mute popus'
	mute.value = True
	globals()['mute_popus_cbox'] = mute
	wzrd_window.addElement(mute)

	wzrd_window.addStretchSpace()
	wzrd_window.addReturn()

	close_btn.onClick = mset.shutdownPlugin
	wzrd_window.addElement(close_btn)


if __name__ == '__main__':
	main()

