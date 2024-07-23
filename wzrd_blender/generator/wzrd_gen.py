from pathlib import Path
import importlib.util

import fnmatch
import uuid
import hashlib
import io
import json
import subprocess
import secrets
import os
import sys
import shutil
import socket
import multiprocessing
import threading

import bpy


try:
	import bpy
	BLENDER_EXECUTABLE = Path(sys.executable).parents[3] / 'blender.exe'
	BLEND_FILE = Path(
		bpy.path.abspath(bpy.data.filepath)
	)
except ImportError as e:
	bpy = None
	BLENDER_EXECUTABLE = None
	BLEND_FILE = None

THISDIR = None
if Path(__file__).parent.is_dir():
	THISDIR = Path(__file__).parent
elif bpy:
	THISDIR = Path(
		bpy.path.abspath(bpy.data.texts[Path(__file__).name].filepath)
	).parent

	if not THISDIR.is_dir():
		THISDIR = None


FFMPEG = THISDIR.parent / 'bins' / 'ffmpeg.exe'
PREVIEW_QUALITY = 4
PREVIEW_RESOLUTION = 256



def char_fixup(tgt_str):
	prohibited = '(){}$%^*'
	for p in prohibited:
		tgt_str = tgt_str.replace(p, '')

	return tgt_str



class AssetBaseData:
	@classmethod
	@property
	def defaults_maps(cls):
		return {
			'albedo': None,
			'ao': None,
			'normal': None,
			# Bump is disp/height
			'bump': None,
			'rough': None,
			'gloss': None,
			'metal': None,
			'emission': None,
			'emission_fac': None,
			'alpha': None,
		}

	@classmethod
	@property
	def defaults_all(cls):
		return cls.defaults_maps | {
			'tags': [],

			# Where this asset was imported from
			# Points to a file for single textures
			# Points to parent dir for materials
			'import_source': None,

			# Includes subpath
			# Must always include name
			'mat_name': None,

			# Obsolete
			'prefix': None,

			# One of:
			# mat
			# brush
			# texture
			'asset_type': None,

			# Category is a main category in the asset catalogue.
			# One of:
			# Materials
			# Grunges
			# Stencils
			# Brushes
			# Panoramas
			# Other
			'category': None,

			# Path to the preview image for this material.
			# Gets imported by Blender and burend into the .blend file
			'preview': None,

			# This allows cropping the previews.
			# To only crop out a specific section, for example
			'pre_crop_data': None,

			# Preview render params
			'custom_preview_prms': {},

			# These maps are disconnected by default
			'disconnected': [],
		}
	


class MapFinder:
	"""
		- tgt_dir:
		  Always absolute. Accepts strings and pathlib.Path
		- cfg:
		  Patterns to search by. Format is:
		  {
		      'diffuse': [
		          '*_COL_VAR1*',
		          '*_COL_VAR2*',
		          '*_COL_*',
		      ],
		      'displacement': [
		          '*_DISP*.tif',
		          '*_DISP*.jpg',
		      ],
		  }
		  Only first match is returned.
	"""
	def __init__(self, tgt_dir, cfg):
		self.tgt_dir = Path(tgt_dir)
		self.cfg = cfg

	def __enter__(self):
		return self

	def __exit__(self, type, value, traceback):
		pass

	def path_list(self, base_name):
		base_name = str(base_name).lower()
		return [
			f for f in self.tgt_dir.glob('*')
			if (not f.is_dir() and base_name in f.name.lower())
		]

	def path_list_recursive(self, base_name):
		base_name = str(base_name).lower()
		return [
			f for f in self.tgt_dir.rglob('*')
			if ( not f.is_dir() and (base_name in f.name.lower()) )
		]

	def find_group(self, base_name='', recursive=False):
		collected_data = {map_name:None for map_name in self.cfg}

		if recursive:
			path_list = self.path_list_recursive(base_name)
		else:
			path_list = self.path_list(base_name)

		for map_name, pattern_list in self.cfg.items():
			# Find FIRST pattern
			for pattern in pattern_list:
				pattern = pattern.lower()
				for fpath in path_list:
					if fnmatch.fnmatch(fpath.name.lower(), pattern):
						collected_data[map_name] = fpath
						break

				if collected_data[map_name]:
					break

		return collected_data



class BlenderCatalogue:
	"""
		Direct blender catalogue manipulator.
		Operates directly on "blender_assets.cats.txt" file.

		- cat_file: Absolute path to "blender_assets.cats.txt"
	"""

	# Whether to also save the weird ~ file
	SAVE_TILDE = False

	# Some default data
	CAT_FILE_HEADER = '\n'.join([
		"""# This is an Asset Catalog Definition file for Blender.""",
		"""#""",
		"""# Empty lines and lines starting with `#` will be ignored.""",
		"""# The first non-ignored line should be the version indicator.""",
		'''# Other lines are of the format "UUID:catalog/path/for/assets:simple catalog name"''',
		'',
		'VERSION 1',
		'',
		# '7fac3db5-9567-4666-8cfd-67aa30932412:GN Modifiers:GN Modifiers',
	])

	def __init__(self, cat_file):
		self.cat_file = Path(cat_file)

		# Parsed .txt data
		self._cats = None

	@property
	def cat_list(self):
		if self._cats:
			return self._cats

		file_content = self.cat_file.read_text(encoding='utf-8')
		lines = [
			l.strip() for l in file_content.split('\n')
			if l.strip() and not l.strip().startswith('#')
		]

		# First line is always version identifier,
		# which is useless here
		del lines[0]

		self._cats = {}

		for l in lines:
			uid, cat_path, cat_path_id = l.split(':')
			self._cats[cat_path] = (uid, cat_path_id,)

		return self._cats

	def save(self):
		file_buf = [self.CAT_FILE_HEADER]
		for cat_path, cat_data in self.cat_list.items():
			uid, cat_path_id = cat_data
			file_buf.append(':'.join([
				uid, cat_path, cat_path_id
			]))

		self.cat_file.write_text('\n'.join(file_buf))

		if self.SAVE_TILDE:
			(self.cat_file.parent / f'{self.cat_file.name}~').write_text(
				'\n'.join(file_buf)
			)

	def create_cat(self, cat_path):
		"""
			Create a catalogue. UUID is generated automatically.
			Duplicates are not re-generated and are skipped.
			Returns UUID of the catalogue that was requested to be created.
		"""
		cat_path = cat_path.strip(' /')

		if cat_path in self.cat_list:
			return self.cat_list[cat_path][0]

		uid = str(uuid.uuid4())

		self.cat_list[cat_path] = (
			uid,
			cat_path.replace('/', '-').replace(':', '-')
		)

		# Every newly created catalogue must be written to the cats.txt file,
		# otherwise Blender is too prone to crashing.
		self.save()

		return uid

	def del_cat(self, cat_path):
		"""
			Delete a catalogue.
		"""
		cat_path = cat_path.strip(' /')
		if not cat_path in self.cat_list:
			return

		del self.cat_list[cat_path]

		self.save()



# Pro tip: Bump node is shit.
# Pro tip: Displacement node's "Normal" input is rather different from
# the shader's "Normal" input.
class ImageBasedAsset:
	NODE_LOCS = {
		'shader':                 (0.0, 0.0),
		'mat_out':                (524.969, -226.546),
		'albedo':                 (-724.768, 794.767),
		'albedo_ao_mix':          (-375.595, 771.867),
		'ao':                     (-724.768, 511.072),
		'displacement':           (-40.203, -542.172),
		'displacement_data_node': (230.033, -542.131),
		'normal_map':             (-724.768, -624.73),
		'normal_map_data_node':   (-439.843, -523.823),
		'roughness':              (-724.768, -57.549),
		'gloss_invert':           (-446.403, -57.549),
		'metallic':               (-724.768, 229.464),
		'alpha':                  (-724.768, -340.217),
		'emission_col':           (-724.768, -916.083),
		'emission_fac':           (-724.768, -1203.0),
	}

	def __init__(self, input_data):
		# self.input_data = AssetBaseData.defaults_all | input_data
		self.input_data = input_data

		# Getting datablock triggers entire material to be setup
		self._datablock = None
		# Getting material simply triggers a creation of empty material
		# with minimal contents, such as Principled BSDF and Material Output
		self._material = None

		# This material's "Principled BSDF" node
		self._bsdf_node = None
		# This material's "Material Output" node
		self._mat_output_node = None

	@property
	def material(self):
		if self._material:
			return self._material

		mat_name = self.input_data['mat_name'].split('/')[-1]

		if mat_name in bpy.data.materials:
			bpy.data.materials.remove(
				bpy.data.materials[mat_name]
			)

		mat = bpy.data.materials.new(
			name=mat_name
		)
		if hasattr(mat, 'use_nodes'):
			mat.use_nodes = True

		wzrd_asset_data = {
			'asset_type': self.input_data['asset_type'],
			'source': str(self.input_data['import_source']),
			'maps': AssetBaseData.defaults_maps,
		}

		for map_name in AssetBaseData.defaults_maps.keys():
			target_map = self.input_data[map_name]
			if target_map and (target_map != 'None'):
				wzrd_asset_data['maps'][map_name] = str(target_map)

		mat['_wzrd_asset_data'] = wzrd_asset_data

		mat.node_tree.nodes.clear()

		self._material = mat

		return mat

	@property
	def node_tree(self):
		return self.material.node_tree

	@property
	def mat_output_node(self):
		if self._mat_output_node:
			return self._mat_output_node

		self._mat_output_node = self.node_tree.nodes.new(
			type='ShaderNodeOutputMaterial'
		)

		return self._mat_output_node

	@property
	def bsdf_node(self):
		if self._bsdf_node:
			return self._bsdf_node

		nodes = self.node_tree.nodes
		links = self.node_tree.links

		main_bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
		mat_output_node = self.mat_output_node

		main_bsdf_node.location = (0, 0)
		mat_output_node.location = (300, 0)

		links.new(
			main_bsdf_node.outputs['BSDF'],
			mat_output_node.inputs['Surface']
		)

		self._bsdf_node = main_bsdf_node

		return self._bsdf_node

	@property
	def datablock(self):
		if self._datablock:
			return self._datablock

		self._datablock = self.create_datablock()

		return self._datablock

	def create_image_node(
		self,
		tgt_image_path,
		premul_alpha=False,
		allow_duplicate=False
	):
		img_tex_node = self.node_tree.nodes.new(type='ShaderNodeTexImage')

		image_datablock = None
		if not allow_duplicate:
			for img in bpy.data.images:
				if Path(bpy.path.abspath(img.filepath)) == Path(tgt_image_path):
					image_datablock = img
					break

		if not image_datablock:
			image_datablock = bpy.data.images.load(str(tgt_image_path))

		if premul_alpha:
			image_datablock.alpha_mode = 'PREMUL'
		else:
			image_datablock.alpha_mode = 'CHANNEL_PACKED'

		img_tex_node.image = image_datablock

		return img_tex_node

	def create_datablock(self):
		self.material['_asset_wzrd_import_src'] = str(
			self.input_data['import_source']
		)
		# If it's just a brush or a single texture - simply create a single
		# texture node and that's it
		if self.input_data['asset_type'] in ('brush', 'texture'):
			self.create_image_node(self.input_data['albedo'])
			return self._material

		# Otherwise - setup a material

		# 
		# Albedo + AO
		# 
		if self.input_data['albedo']:
			albedo_img_node = self.create_image_node(
				self.input_data['albedo']
			)
			albedo_img_node.image.alpha_mode = 'CHANNEL_PACKED'
			albedo_img_node.location = self.NODE_LOCS['ao']
			# AO
			if self.input_data['ao']:
				albedo_img_node.location = self.NODE_LOCS['albedo']
				ao_img_node = self.create_image_node(
					self.input_data['ao']
				)
				ao_img_node.location = self.NODE_LOCS['ao']

				col_mix_node = self.node_tree.nodes.new(
					type='ShaderNodeMix'
				)
				col_mix_node.location = self.NODE_LOCS['albedo_ao_mix']
				col_mix_node.data_type = 'RGBA'
				col_mix_node.inputs['Factor'].default_value = 1.0
				col_mix_node.blend_type = 'MULTIPLY'

				self.node_tree.links.new(
					ao_img_node.outputs['Color'],
					col_mix_node.inputs['B']
				)

				self.node_tree.links.new(
					albedo_img_node.outputs['Color'],
					col_mix_node.inputs['A']
				)


				self.node_tree.links.new(
					col_mix_node.outputs['Result'],
					self.bsdf_node.inputs['Base Color']
				)
			else:
				self.node_tree.links.new(
					albedo_img_node.outputs['Color'],
					self.bsdf_node.inputs['Base Color']
				)

		# 
		# Normal + BW disp
		# 
		if self.input_data['normal']:
			normal_map_img_node = self.create_image_node(
				self.input_data['normal']
			)
			normal_map_img_node.location = self.NODE_LOCS['normal_map']
			normal_map_img_node.image.colorspace_settings.name = 'Non-Color'
			normal_map_data_node = self.node_tree.nodes.new(
				type='ShaderNodeNormalMap'
			)
			normal_map_data_node.location = self.NODE_LOCS['normal_map_data_node']
			self.node_tree.links.new(
				normal_map_img_node.outputs['Color'],
				normal_map_data_node.inputs['Color']
			)
			self.node_tree.links.new(
				normal_map_data_node.outputs['Normal'],
				self.bsdf_node.inputs['Normal']
			)

		if self.input_data['bump']:
			bump_img_node = self.create_image_node(
				self.input_data['bump']
			)
			bump_img_node.image.colorspace_settings.name = 'Non-Color'
			bump_img_node.location = self.NODE_LOCS['displacement']
			disp_node = self.node_tree.nodes.new(
				type='ShaderNodeDisplacement'
			)
			disp_node.location = self.NODE_LOCS['displacement_data_node']
			self.node_tree.links.new(
				bump_img_node.outputs['Color'],
				disp_node.inputs['Height']
			)
			self.node_tree.links.new(
				disp_node.outputs['Displacement'],
				self.mat_output_node.inputs['Displacement']
			)

		# 
		# Rough/Gloss
		# 
		if self.input_data['rough'] or self.input_data['gloss']:
			rg_img_node = self.create_image_node(
				self.input_data['rough'] or self.input_data['gloss']
			)
			rg_img_node.location = self.NODE_LOCS['roughness']
			rg_img_node.image.colorspace_settings.name = 'Non-Color'

			if self.input_data['gloss'] and not self.input_data['rough']:
				invert_node = self.node_tree.nodes.new(
					type='ShaderNodeInvert'
				)
				invert_node.location = self.NODE_LOCS['gloss_invert']
				self.node_tree.links.new(
					rg_img_node.outputs['Color'],
					invert_node.inputs['Color']
				)
				self.node_tree.links.new(
					invert_node.outputs['Color'],
					self.bsdf_node.inputs['Roughness']
				)
			else:
				self.node_tree.links.new(
					rg_img_node.outputs['Color'],
					self.bsdf_node.inputs['Roughness']
				)

		# 
		# Metal
		# 
		if self.input_data['metal']:
			metal_img_node = self.create_image_node(
				self.input_data['metal']
			)
			metal_img_node.location = self.NODE_LOCS['metallic']
			metal_img_node.image.colorspace_settings.name = 'Non-Color'
			self.node_tree.links.new(
				metal_img_node.outputs['Color'],
				self.bsdf_node.inputs['Metallic']
			)

		# 
		# Emission
		# 
		if self.input_data['emission']:
			emit_img_node = self.create_image_node(
				self.input_data['emission']
			)
			emit_img_node.location = self.NODE_LOCS['emission_col']
			self.node_tree.links.new(
				emit_img_node.outputs['Color'],
				self.bsdf_node.inputs['Emission Color']
			)
			if self.input_data['emission_fac']:
				emit_fac_img_node = self.create_image_node(
					self.input_data['emission_fac']
				)
				emit_fac_img_node.location = self.NODE_LOCS['emission_fac']
			else:
				emit_fac_img_node = emit_img_node

			self.node_tree.links.new(
				emit_fac_img_node.outputs['Color'],
				self.bsdf_node.inputs['Emission Strength']
			)

		# 
		# Alpha
		# 
		if self.input_data['alpha']:
			alpha_source = str(self.input_data['alpha'])

			# From albedo = same file as albedo
			if '$from_albedo' in alpha_source:
				alpha_img_filepath = self.input_data['albedo']
			else:
				alpha_img_filepath = self.input_data['alpha']

			# New image for alpha channel is always created
			alpha_img_node = self.create_image_node(
				alpha_img_filepath,
				allow_duplicate=True
			)
			alpha_img_node.location = self.NODE_LOCS['alpha']
			alpha_img_node.image.colorspace_settings.name = 'Non-Color'

			# Decide how to connect the node to the alpha input
			alpha_link = None
			if alpha_source == '$from_albedo_rgb':
				alpha_link = self.node_tree.links.new(
					alpha_img_node.outputs['Color'],
					self.bsdf_node.inputs['Alpha']
				)
			elif alpha_source == '$from_albedo':
				# From albedo alpha channel
				alpha_link = self.node_tree.links.new(
					alpha_img_node.outputs['Alpha'],
					self.bsdf_node.inputs['Alpha']
				)
			else:
				# Dedicated alpha mask
				alpha_link = self.node_tree.links.new(
					alpha_img_node.outputs['Color'],
					self.bsdf_node.inputs['Alpha']
				)

			if 'alpha' in self.input_data['disconnected'] and alpha_link:
				self.node_tree.links.remove(alpha_link)


		return self._material


class ImageBasedAssetPreview:
	def __init__(self, parent_asset):
		self.asset = parent_asset
		self.raw_path = self.asset.input_data['preview']
		self.cooked_path = None
		self.crop_params = self.asset.input_data['pre_crop_data']
		self.done = False

	@property
	def eligible(self):
		if not self.raw_path:
			return False
		
		if not Path(self.raw_path).is_file():
			return False

		return True

	def generate_cooked_path(self):
		return BLEND_FILE.parent / f'pwzrd_cooked_{str(uuid.uuid4())}.png'

	def cook(self, tgt_img=None, crop_params=None):
		if not self.raw_path and not tgt_img:
			return False

		if tgt_img:
			self.raw_path = tgt_img

		if crop_params:
			self.crop_params = crop_params

		intermediate = []

		tgt_img = Path(self.raw_path)
		img_write_path = self.generate_cooked_path()

		if self.crop_params:
			p = self.crop_params
			crop_str = ''.join([
				# Crop
				'in_w*', str(p['crop_w']),
				':',
				'in_h*', str(p['crop_h']),
				':',
				# Center
				'in_w*', str(p['center_w']),
				':',
				'in_h*', str(p['center_h']),
			])
			subprocess.call(
				[
					str(FFMPEG),
					'-y',
					'-loglevel', 'quiet',
					'-i', str(tgt_img),
					'-vf', f'crop={crop_str}',
					str(img_write_path)
				],
				shell=True,
				stdout=subprocess.DEVNULL
			)

			if not img_write_path.is_file():
				return False

			intermediate.append(img_write_path)

			tgt_img = img_write_path
			img_write_path = self.generate_cooked_path()

		subprocess.call(
			[
				str(FFMPEG),
				'-y',
				'-loglevel', 'quiet',
				'-i', str(tgt_img),
				'-vf', f'scale={PREVIEW_RESOLUTION}:-1',
				'-qscale:v', str(PREVIEW_QUALITY),
				str(img_write_path)
			],
			shell=True,
			stdout=subprocess.DEVNULL
		)

		while intermediate:
			intermediate.pop().unlink(missing_ok=True)

		if not img_write_path.is_file():
			return False

		self.cooked_path = img_write_path
		return True

	def apply(self, del_source=False):
		if not self.cooked_path:
			return False

		context = bpy.context
		override = context.copy()
		override['id'] = self.asset.asset_data
		with context.temp_override(**override):
			bpy.ops.ed.lib_id_load_custom_preview(
				filepath=str(self.cooked_path)
			)

		self.done = True
		self.cooked_path.unlink(missing_ok=True)
		self.cooked_path = None

		if del_source and self.raw_path:
			Path(self.raw_path).unlink(missing_ok=True)
			self.raw_path = None

		return True



class ImageBasedAssetCatalogueItem:
	def __init__(self, parent_cat, input_data):
		self.parent_cat = parent_cat
		self.input_data = AssetBaseData.defaults_all | input_data
		self.img_asset = ImageBasedAsset(self.input_data)

		self._asset_data = None

		self._cat_uid = None

		self.preview = ImageBasedAssetPreview(self)

	# Calling this will only return the underlying material
	# datablock regardless of whether it's registered in the asset catalogue
	# or not
	@property
	def datablock(self):
		return self.img_asset.datablock
	
	def validate(self):
		for map_name in AssetBaseData.defaults_maps.keys():
			if self.input_data.get(map_name):
				return True

		return False

	# Getting this triggers everything to be registered
	# Returns underlying material datablock, but in registered state
	@property
	def asset_data(self):
		if self._asset_data:
			return self._asset_data

		self.reg()

		return self._asset_data

	# Simply create a catalogue in the txt file
	def create_cat(self):
		return self.parent_cat.create_cat(
			self.input_data['category'].strip(' /') + '/' +
			'/'.join(self.input_data['mat_name'].split('/')[:-1])
		)

	# Basically same as create_cat()
	@property
	def cat_uid(self):
		if self._cat_uid:
			return self._cat_uid

		self._cat_uid = self.create_cat()

		return self._cat_uid

	# Register the asset in the catalogue
	def reg(self):
		self.datablock.asset_mark()
		self.datablock.asset_data.catalog_id = self.cat_uid
		for tag in self.input_data['tags']:
			self.datablock.asset_data.tags.new(
				tag,
				skip_if_exists=True
			)

		self.datablock.asset_data.tags.new(
			f"""${self.input_data['asset_type']}""",
			skip_if_exists=True
		)

		self._asset_data = self.datablock


def confirm(msg='Proceed?'):
	assert (input(msg).lower() != 'n')


class AssetWizard:
	"""
		Config syntax is as follows:
		    key = value
		    key = value
		    ...
		Values can have "=" symbols in them, but not keys.
		Key Value pairs are separated by line breaks.

		"asset_wzrd_cfg" text datablock accepts following keys:
		- yield_group:
		  Comma-separated yield groups.
		  $all = accept all groups.

		- worker_index:
		  Absolute path pointing to a python file, containing workers to be
		  executed. Must not have quotation marks

		- cat_file:
		  Absolute path pointing to the cats.txt file.
	"""
	def __init__(self):
		self._worker_list = None
		self._blender_cats = None
		self._preview_wizard = None

		self._allowed_workers = False

		# Create a very simple config
		self.cfg = {
			'yield_group': '$all',
			'allowed_workers': '$all',
		}
		for line in bpy.data.texts['asset_wzrd_cfg'].lines:
			line = line.body
			if not line or line.strip().startswith('#'):
				continue

			line_data = line.split('=')

			self.cfg[line_data[0].strip()] = '='.join(line_data[1:]).strip()

	@staticmethod
	def import_module_from_path(python_file_path, module_name):
		python_file_path = str(python_file_path)

		spec = importlib.util.spec_from_file_location(
			module_name,
			python_file_path
		)
		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)

		return module

	@property
	def allowed_workers(self):
		if self._allowed_workers:
			return self._allowed_workers

		txt_data = bpy.data.texts.get('allowed_workers')
		if not txt_data:
			self._allowed_workers = ['$all',]
			return self._allowed_workers

		self._allowed_workers = [
			l.body.strip() for l in txt_data.lines if l.body and not l.body.strip().startswith('#')
		]

		return self._allowed_workers

	@property
	def worker_list(self):
		if self._worker_list != None:
			return self._worker_list
	
		raw_list = self.import_module_from_path(
			self.cfg['worker_index'],
			'asset_wzrd_worker_index'
		)

		self._worker_list = []

		for worker in raw_list.WORKER_INDEX:
			worker.MapFinder = MapFinder
			self._worker_list.append(worker)

		return self._worker_list

	@property
	def blender_cats(self):
		if self._blender_cats:
			return self._blender_cats

		self._blender_cats = BlenderCatalogue(self.cfg['cat_file'])

		return self._blender_cats

	@property
	def preview_wizard(self):
		if self._preview_wizard:
			return self._preview_wizard

		self._preview_wizard = self.import_module_from_path(
			THISDIR.parent / 'pwzrd/pwzrd.py',
			'preview_wizard'
		)

		self._preview_wizard = self._preview_wizard.PreviewWizard

		return self._preview_wizard

	@staticmethod
	def traversing_worker(yield_group, worker_list, mp_pipe=None):
		asset_infos = []
		for worker in worker_list:
			for asset_info in worker():
				print(
					'Traversing',
					# asset_info['mat_name']
					' '.join(asset_info['mat_name'].split(' ')[:-1]).ljust(150, ' '),
					' '.join(asset_info['mat_name'].split(' ')[-1:]),
				)
				can_yield = any((
					'$all' in yield_group,
					asset_info['yield_category'] in yield_group,
				))
				if not can_yield:
					print(
						'Skipping', asset_info['mat_name'],
						'because target yield_category', asset_info['yield_category'],
						'is not present in config:', yield_group
					)
					continue

				asset_infos.append(asset_info)

		if mp_pipe:
			mp_pipe.send(asset_infos)
		else:
			return asset_infos

	def create_asset_info_lists_mp(self):
		disks_dict = {}
		for worker in self.worker_list:
			if (not worker.__name__ in self.allowed_workers) and (not '$all' in self.allowed_workers):
				continue

			disk_letter = Path(worker.LIB_BASE_PATH).anchor
			if not disk_letter in disks_dict:
				disks_dict[disk_letter] = []

			disks_dict[disk_letter].append(worker)

		yield_grp = self.cfg['yield_group'].strip().split(',')
		workers = []
		for worker_group in disks_dict.values():
			skt_pipe_a, skt_pipe_b = multiprocessing.Pipe()
			proc = threading.Thread(
				target=AssetWizard.traversing_worker,
				args=(yield_grp, worker_group, skt_pipe_a,)
			)
			workers.append(
				(proc, skt_pipe_b)
			)
			proc.start()

		asset_infos = []
		for proc, skt_pipe in workers:
			asset_infos.extend(skt_pipe.recv())
			proc.join()

		workers.clear()

		return asset_infos

	def assign_previews(self, asset_list):
		# Sort assets into groups based by preview's disk letter
		disks = {}
		for asset in asset_list:
			if not asset.preview.eligible:
				continue

			disk_letter = Path(asset.preview.raw_path).anchor
			if not disk_letter in disks:
				disks[disk_letter] = []

			disks[disk_letter].append(asset)

		# Cook existing previews in threads
		thread_count = 10
		thread_pool = []

		while any(d for d in disks.values()):
			thread_pool.clear()
			for disk in disks.values():
				if not disk: continue
				for i in range(thread_count):
					if not disk: break

					asset = disk.pop()

					print(
						len(disk),
						'Cooking preview for',
						asset.input_data['mat_name']
					)

					thread = threading.Thread(
						target=asset.preview.cook,
						# args=(None,)
					)
					thread_pool.append(thread)
					thread.start()

			for thread in thread_pool:
				thread.join()

		for asset in asset_list:
			if asset.preview.cooked_path:
				print('Applying preview for', asset.input_data['mat_name'])
				asset.preview.apply()

		return asset_list

	def run(self):
		asset_list = []

		yield_grp = self.cfg['yield_group'].strip().split(',')

		# 1 - Create a list of catalogue items
		for asset_info in self.create_asset_info_lists_mp():
			asset_list.append(ImageBasedAssetCatalogueItem(
				self.blender_cats,
				asset_info
			))

		# Save the blend file (just in case)
		bpy.ops.wm.save_mainfile()

		# 2 - register catalogues
		for asset in asset_list:
			asset.create_cat()

		# Save the blend file (so that it refreshes catalogues)
		bpy.ops.wm.save_mainfile()

		# 3 - Assign assets to catalogues
		for asset in asset_list:
			print('Assigning to catalogue', asset.input_data['mat_name'])
			asset.reg()

		# Save the blend file (just in case)
		bpy.ops.wm.save_mainfile()

		# confirm('Done registering. Press Enter To Continue')

		# Assign existing previews
		self.assign_previews(asset_list)

		# confirm('Done with existing previews. Press Enter To Continue')

		# Save the blend file (just in case)
		bpy.ops.wm.save_mainfile()

		# Generate previews for assets that don't have one
		with self.preview_wizard(BLENDER_EXECUTABLE) as pwzrd:
			for asset in asset_list:
				if asset.preview.done:
					continue

				print('Rendering preview for', asset.input_data['mat_name'])
				render_result = pwzrd.render(
					asset.input_data['custom_preview_prms'] | {
						'material_source': str(BLEND_FILE),
						'src_material_name': asset.datablock.name,
					}
				).decode()
				if render_result.startswith('$fail'):
					print(
						'Failed to render Blender preview for',
						asset.input_data['mat_name'],
						'Reason:', render_result.split('$fail:')[-1]
					)
					continue
				print(
					'Rendered custom preview:', render_result,
					'for', asset.input_data['mat_name']
				)
				# asset.set_preview(render_result)
				asset.preview.cook(render_result)
				asset.preview.apply(True)

		print('Done')


def unpack_ffmpeg():
	import gzip
	with gzip.open(FFMPEG.parent / 'ffmpeg.gz', 'rb') as f_in:
		with open(FFMPEG, 'wb') as f_out:
			while chunk := f_in.read(1024**2):
				f_out.write(chunk)


if __name__ == '__main__':
	if not FFMPEG.is_file():
		unpack_ffmpeg()

	asset_wzrd = AssetWizard()
	asset_wzrd.run()
