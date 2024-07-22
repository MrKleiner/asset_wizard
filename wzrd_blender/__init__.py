bl_info = {
	'name': 'Asset Wizrd',
	'author': 'MrKleiner',
	'version': (0, 53),
	'blender': (4, 1, 1),
	'location': 'N menu in the asset browser',
	'description': """Asset Nexus. Turn Blender into global mega asset manager""",
	'doc_url': 'https://github.com/MrKleiner/blvtf',
	'category': 'Add Mesh',
}

from pathlib import Path
import bpy
from bpy.types import (
	Header,
	Panel,
	Menu,
	UIList,
	Operator,
)
from bpy_extras import (
	asset_utils,
)


import socket
import os
import shutil
import uuid
import json
import threading

# Constants
WZRD_APPDATA = Path().home() / 'AppData' / 'Roaming' / 'blender_assetwzrd'

WZRD_APPDATA_TEMP_DIR = WZRD_APPDATA / 'disposable'
WZRD_APPDATA_PORTS_DIR = WZRD_APPDATA / 'ports'


# =========================================================
# ---------------------------------------------------------
#                       Functionality
# ---------------------------------------------------------
# =========================================================




# =========================
#         Shared
# =========================
def create_operator_name(*args):
	return 'assetwzrd.' + '_'.join(args)


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


class WZRDTempFile:
	def __init__(self, fname=None, fext=None, autodel=True):
		self._fpath = None
		self.fname = fname
		self.fext = fext
		self.autodel = autodel

	@property
	def fpath(self):
		if self._fpath:
			return self._fpath
		
		fname = self.fname or str(uuid.uuid4())
		fext = (self.fext or 'tmp').strip(' .')

		self._fpath = WZRD_APPDATA_TEMP_DIR / f'{fname}.{fext}'

		return self._fpath

	def __enter__(self):
		# shutil.rmtree(WZRD_APPDATA_TEMP_DIR, ignore_errors=True)
		WZRD_APPDATA_TEMP_DIR.mkdir(exist_ok=True, parents=True)
		return self

	def __exit__(self, type, value, traceback):
		if self._fpath and self.autodel:
			self._fpath.unlink(missing_ok=True)


class WZRDAppData:
	def __init__(self):
		pass

	def tempfile(self, fname=None, fext=None):
		pass


class LoadAssetFromSource:
	BPY_ID_TYPES = {
		'MATERIAL': 'materials',
		'COLLECTION': 'collections',
	}
	def __init__(self, asset_data, del_on_exit=True):
		self.del_on_exit = del_on_exit
		self.asset_data = asset_data
		self._asset_datablock = None

	@property
	def datablock(self):
		if self._asset_datablock:
			return self._asset_datablock

		bpy_id_type = self.BPY_ID_TYPES[self.asset_data.id_type]

		with bpy.data.libraries.load(self.asset_data.full_library_path) as (data_from, data_to):
			getattr(data_to, bpy_id_type).append(
				self.asset_data.name
			)

		self._asset_datablock = getattr(bpy.data, bpy_id_type)[self.asset_data.name]

		return self._asset_datablock

	def __enter__(self):
		return self

	def __exit__(self, type, value, traceback):
		if self.del_on_exit and self._asset_datablock:
			bpy_id_type = self.BPY_ID_TYPES[self.asset_data.id_type]
			getattr(bpy.data, bpy_id_type).remove(
				getattr(bpy.data, bpy_id_type)[self.asset_data.name]
			)










# =========================
#         Marmoset
# =========================

MARMOSET_MAT_EXPORT_MODES = (
	(
		'full_append',
		'Full Append',
		'Append asset into the materials bin and add it to the layer stack',
	),
	(
		'add_fill_layer',
		'Add Fill Layer',
		'Add a fill layer to the layer stack and assign material maps to it',
	),
	(
		'overwrite_fill_layer',
		'Overwrite Fill Layer',
		'Overwrite currently selected fill layer with maps from the selected '
		'asset',
	),
)

class MarmosetConnection:
	def __init__(self, pipe, cl_con):
		self.cl_con = cl_con
		self.pipe = pipe
		self.skt_rfile = None
		self.skt_wfile = None

	def __enter__(self):
		self.skt_rfile = self.cl_con.makefile('rb', buffering=0)
		self.skt_wfile = self.cl_con.makefile('wb')
		return self

	def __exit__(self, type, value, traceback):
		self.skt_rfile.close()
		self.skt_wfile.close()

		self.cl_con.shutdown(socket.SHUT_RDWR)
		self.cl_con.close()

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


class MarmosetPipe:
	def __init__(self, sched=None):
		self.skt = None
		self.sched = sched

	def __enter__(self):
		self.skt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.skt.bind(
			('127.0.0.1', 0)
		)
		self.skt.listen()
		WZRD_APPDATA_PORTS_DIR.mkdir(parents=True, exist_ok=True)
		(WZRD_APPDATA_PORTS_DIR / 'blender_mset.prt').write_text(
			str(self.skt.getsockname()[1])
		)

		return self

	def __exit__(self, type, value, traceback):
		pass

	def run(self):
		while True:
			cl_con, cl_addr = self.skt.accept()
			with DynamicGroupedText('Marmoset Connection') as console:
				print = console.print
				with MarmosetConnection(self, cl_con) as mset_con:
					print('Got mset connection, sending payload')
					mset_con.send_payload(self.sched.data or {
						'cmd': 'skip',
						'data': None,
					})
					print('Sent payload, awaiting response')

					print(
						'Received reply from marmoset:',
						mset_con.read_payload()
					)


class MarmosetTBMatMaker:
	MAT_GRP_SIMPLE = (
		'albedo',
		'normal',
		'bump',
		'metal',
		'emission',
		'ao',
		'alpha',
	)

	def __init__(self):
		self._albedo = None
		self._normal = None
		self._bump = None
		self._rough = None
		self._gloss = None
		self._metal = None
		self._emission = None
		self._ao = None
		self._alpha = None

	def albedo(self, path):
		self._albedo = [
			'@Sub SRAlbedo = SRAlbedoMap',
			f'    Albedo Map = @Tex file "{str(path)}" srgb 1 filter 1 mip 1 aniso 4 wrap 1 visible 1 @EndTex',
			'    Color = 1 1 1',
			'@End',
		]

	def normal(self, path, srgb=False):
		self._normal = [
			'@Sub SRSurface = SRSurfaceNormalMap',
			f'    Normal Map = @Tex file "{str(path)}" srgb {int(srgb)} filter 1 mip 1 aniso 4 wrap 1 visible 1 @EndTex',
			'    Scale & Bias = 1',
			'    Flip X = 0',
			'    Flip Y = 0',
			'    Flip Z = 0',
			'    Generate Z = 0',
			'    Object Space = 0',
			'@End',
		]

	def bump(self, path, srgb=False):
		self._bump = [
			'@Sub SRDisplacement = SRDisplacementHeight',
			f'    Displacement Map = @Tex file "{str(path)}" srgb {int(srgb)} filter 1 mip 0 aniso 4 wrap 1 visible 1 @EndTex',
			'    Channel = 0',
			'    Scale = 0.05',
			'    Scale Center = 0.5',
			'    Generate Normals = 0',
			'    Relative Scale = 1',
			'@End',
		]

	def rough(self, path, srgb=False, gloss=False):
		self._rough = [
			 '@Sub SRMicrosurface = SRMicrosurfaceRoughnessMap',
			f'    Roughness Map = @Tex file "{str(path)}" srgb {int(srgb)} filter 1 mip 1 aniso 4 wrap 1 visible 1 @EndTex',
			 '    Channel = 0',
			 '    Roughness = 1',
			f'    Invert;roughness = {int(gloss)}',
			 '@End',
		]

	def metal(self, path, srgb=False):
		self._metal = [
			'@Sub SRReflectivity = SRReflectivityMetalnessMap',
			f'    Metalness Map = @Tex file "{str(path)}" srgb {int(srgb)} filter 1 mip 1 aniso 4 wrap 1 visible 1 @EndTex',
			'    Channel = 0',
			'    Metalness = 1',
			'    Invert = 0',
			'@End',
		]

	def emission(self, path, srgb=False):
		self._emission = [
			'@Sub SREmission = SREmissiveMap',
			f'    Emissive Map = @Tex file "{str(path)}" srgb {int(srgb)} filter 1 mip 1 aniso 4 wrap 1 visible 1 @EndTex',
			'    Color = 1 1 1',
			'    Intensity = 1',
			'    UV Set = 0',
			'    Glow = 0 0 0',
			'@End',
		]

	def ao(self, path, srgb=False):
		self._ao = [
			'@Sub SROcclusion = SROcclusionMap',
			f'    Occlusion Map = @Tex file "{str(path)}" srgb {int(srgb)} filter 1 mip 1 aniso 4 wrap 1 visible 1 @EndTex'
			'    Channel;occlusion = 0',
			'    Occlusion = 1',
			'    UV Set = 0',
			'    Vertex Channel = 0',
			'    Cavity Map = nil',
			'    Channel;cavity = 0',
			'    Diffuse Cavity = 1',
			'    Specular Cavity = 1',
			'@End',
		]

	def alpha(self, path, srgb=False):
		self._alpha = [
			'@Sub SRTransparency = SRTransparencyDither',
			'    Use Albedo Alpha = 0',
			f'    Alpha Map = @Tex file "{str(path)}" srgb {int(srgb)} filter 1 mip 1 aniso 4 wrap 1 visible 1 @EndTex',
			'    Channel = 3',
			'    Alpha = 1',
			'@End',
		]

	def __str__(self):
		entries = []

		if self._bump:
			entries.append('\n'.join(self._bump))
		if self._normal:
			entries.append('\n'.join(self._normal))
		if self._albedo:
			entries.append('\n'.join(self._albedo))
		entries.append('\n'.join(['@Sub SRDiffusion = SRDiffusionLambertian', '@End']))
		entries.append('\n'.join(['@Sub SRReflection = SRReflectionGGX', '@End']))
		if self._rough:
			entries.append('\n'.join(self._rough))
		if self._metal:
			entries.append('\n'.join(self._metal))
		if self._emission:
			entries.append('\n'.join(self._emission))
		if self._ao:
			entries.append('\n'.join(self._ao))
		if self._alpha:
			entries.append('\n'.join(self._alpha))

		defaults = [
			'@Sub SRMerge = SRMerge',
			'    Texture Tiling = 1',
			'    Tile U = 1',
			'    Offset U = 0',
			'    Tile V = 1',
			'    Offset V = 0',
			'    Wrap = 1',
			'    Aniso = 2',
			'    Filter = 1',
			'@End',
		]

		entries.append('\n'.join(defaults))

		return '\n\n'.join(entries)


class MarmosetSched:
	def __init__(self):
		self.data = None


class MarmosetWZRD:
	def __init__(self):
		self.sched = MarmosetSched()
		self.pipe = None

	def run(self):
		with MarmosetPipe(self.sched) as mset_pipe:
			self.pipe = mset_pipe
			mset_pipe.run()


@bpy.app.handlers.persistent
def marmoset_connect(*args, **kwargs):
	marmoset = MarmosetWZRD()
	globals()['marmoset'] = marmoset
	th = threading.Thread(
		target=marmoset.run,
		daemon=True
	)
	th.start()




















# =========================================================
# ---------------------------------------------------------
#                       OPERATORS
# ---------------------------------------------------------
# =========================================================



# =========================
#         Shared
# =========================
class ASSETBROWSER_OT_AssetWizard_Shared_ExplorerHighlight(Operator):
	bl_idname = create_operator_name(
		'shared',
		'explorer_highlight',
	)
	bl_label = 'Highlight in Explorer'
	bl_description = (
		'Highlight selected asset in the Windows file explorer'
	)

	def execute(self, context):
		asset = context.asset
		asset_data = asset_utils.SpaceAssetInfo.get_active_asset(context)
		wm = context.window_manager
		print(
			'Highlighting asset', dir(asset), 'To Marmoset...',
			# wm.asset_path_dummy,
			asset.full_library_path,
			# asset.full_path,
		)

		with LoadAssetFromSource(asset) as asset_info:
			os.system(
				"""explorer /select,"""
				f"""{asset_info.datablock['_wzrd_asset_data']['source']}"""
			)

		return {'FINISHED'}



# =========================
#         Marmoset
# =========================
class ASSETBROWSER_OT_AssetWizard_MarmosetConnect_SendAsMaterial(Operator):
	bl_idname = create_operator_name(
		'send',
		'marmoset',
		'as_material'
	)
	bl_label = 'Send As Material'
	bl_description = (
		'Send selected asset to Marmoset as Material'
	)

	def _execute(self, context):
		asset = context.asset
		asset_data = asset_utils.SpaceAssetInfo.get_active_asset(context)
		wm = context.window_manager
		print(
			'Sending asset', dir(asset), 'To Marmoset...',
			# wm.asset_path_dummy,
			asset.full_library_path,
			# asset.full_path,
		)

		with LoadAssetFromSource(asset) as asset_info:
			print('---------------')
			print(asset_info.datablock['_wzrd_asset_data']['source'])

		return {'FINISHED'}

	def __execute(self, context):
		assert False
		with DynamicGroupedText('Marmoset Pipe') as cons:
			print = cons.print

			asset = context.asset
			asset_data = asset_utils.SpaceAssetInfo.get_active_asset(context)
			wm = context.window_manager
			piping_method = context.scene.wzrd_marmoset_piping_params.piping_method

			print('Asset Name:', asset.name)
			print('Asset Source:', asset.full_library_path)

			with LoadAssetFromSource(asset) as asset_info:
				print(
					asset_info.datablock['_wzrd_asset_data']['source']
				)
				with WZRDTempFile(fext='.tbmat') as tmp_file:
					print('Temp tbmat:', tmp_file.fpath)

					asset_maps = asset_info.datablock['_wzrd_asset_data']['maps']
					tbmat = MarmosetTBMatMaker()

					# Set simple maps
					for map_name in tbmat.MAT_GRP_SIMPLE:
						src_map = asset_maps[map_name]
						if src_map in ('None', None):
							continue

						print('Setting', map_name, 'To', src_map)
						getattr(tbmat, map_name)(src_map)

					# Roughness must be set separately
					if not asset_maps['rough'] in ('None', None):
						tbmat.rough(asset_maps['rough'])
					if not asset_maps['gloss'] in ('None', None):
						tbmat.rough(asset_maps['rough'], gloss=True)

					tmp_file.fpath.write_text(str(tbmat))
					print(tmp_file.fpath.is_file())

					try:
						with MarmosetPipe() as mset_pipe:
							pass
					except UnableToEstablishPipe as e:
						print(
							'Error: Unable to establish pipe, because', str(e)
						)
						self.report(
							{'WARNING'},
							f'Unable to reach Marmoset, because: {e}'
						)
						return {'FINISHED'}



		return {'FINISHED'}

	def execute(self, context):
		with DynamicGroupedText('Marmoset Pipe (Layer Mask)') as cons:
			piping_method = context.scene.wzrd_marmoset_piping_params.piping_method
			asset = context.asset
			asset_data = asset_utils.SpaceAssetInfo.get_active_asset(context)
			wm = context.window_manager

			cons.print('Asset Name:', asset.name)
			cons.print('Asset Source:', asset.full_library_path)

			with LoadAssetFromSource(asset) as asset_info:
				cons.print(
					asset_info.datablock['_wzrd_asset_data']['source']
				)
				globals()['marmoset'].sched.data = {
					'cmd': 'create_material',
					'data': {
						'maps': dict(
							asset_info.datablock['_wzrd_asset_data']['maps']
						),
						'mode': piping_method,
						'name': asset.name,
					}
				}

		return {'FINISHED'}


class ASSETBROWSER_OT_AssetWizard_MarmosetConnect_SendAsLayerMask(Operator):
	bl_idname = create_operator_name(
		'send',
		'marmoset',
		'as_mask'
	)
	bl_label = 'Send As Layer Mask'
	bl_description = (
		'Send selected asset into the "Mask" channel of the active layer '
		'in Marmoset'
	)

	def execute(self, context):
		with DynamicGroupedText('Marmoset Pipe (Layer Mask)') as cons:
			asset = context.asset
			asset_data = asset_utils.SpaceAssetInfo.get_active_asset(context)
			wm = context.window_manager

			cons.print('Asset Name:', asset.name)
			cons.print('Asset Source:', asset.full_library_path)

			with LoadAssetFromSource(asset) as asset_info:
				cons.print(
					asset_info.datablock['_wzrd_asset_data']['source']
				)
				globals()['marmoset'].sched.data = {
					'cmd': 'set_mask_fill',
					'data': dict(asset_info.datablock['_wzrd_asset_data']['maps'])
				}

		return {'FINISHED'}

















# =========================================================
# ---------------------------------------------------------
#                   Property declarations
# ---------------------------------------------------------
# =========================================================


# =========================
#         Marmoset
# =========================
class WZRDMarmosetPipingProperties(bpy.types.PropertyGroup):
	piping_method:bpy.props.EnumProperty(
		items=MARMOSET_MAT_EXPORT_MODES,
		name='Export Mode',
		description=(
			'How should exported assets be interpreted by the receiver '
			'(In this case - Marmoset)'
		),
		default='full_append'
	)
























# =========================================================
# ---------------------------------------------------------
#                          GUI
# ---------------------------------------------------------
# =========================================================

# =========================
#           Root
# =========================
class ASSETBROWSER_PT_AssetWizard_ConnectMainPanel(
	asset_utils.AssetBrowserPanel, Panel
	):
	bl_region_type = 'TOOL_PROPS'
	bl_category = 'AssetWizard'
	bl_label = 'Asset Wizard'

	def draw(self, context):
		layout = self.layout
		wm = context.window_manager
		asset = context.asset
		asset_data = asset_utils.SpaceAssetInfo.get_active_asset(context)

		if asset is None:
			layout.label(text='Select An Asset first', icon='INFO')
			return

		# for tag in asset_data.tags:
			# layout.row().label(text=tag.name)


# =========================
#          Shared
# =========================
class ASSETBROWSER_PT_AssetWizard_SharedOperators(
	asset_utils.AssetBrowserPanel, Panel
	):
	bl_parent_id = 'ASSETBROWSER_PT_AssetWizard_ConnectMainPanel'
	bl_region_type = 'TOOL_PROPS'
	bl_category = 'AssetWizard'
	bl_label = 'General'

	def draw(self, context):
		layout = self.layout
		wm = context.window_manager
		asset = context.asset
		asset_data = asset_utils.SpaceAssetInfo.get_active_asset(context)

		if asset is None:
			layout.label(text='Select an asset first', icon='INFO')
			return

		layout.operator(create_operator_name(
			'shared',
			'explorer_highlight',
		))


# =========================
#         Marmoset
# =========================
class ASSETBROWSER_PT_AssetWizard_MarmosetConnect(
	asset_utils.AssetBrowserPanel, Panel
	):
	bl_parent_id = 'ASSETBROWSER_PT_AssetWizard_ConnectMainPanel'
	bl_region_type = 'TOOL_PROPS'
	bl_category = 'AssetWizard'
	bl_label = 'Marmoset'

	def draw(self, context):
		layout = self.layout
		wm = context.window_manager
		asset = context.asset
		asset_data = asset_utils.SpaceAssetInfo.get_active_asset(context)
		# layout.row().label(text='Fuckshit')

		if asset is None:
			layout.label(text='No tags to display', icon='INFO')
			return

		layout.column().prop(
			context.scene.wzrd_marmoset_piping_params,
			'piping_method',
			expand=True
		)

		layout.operator(create_operator_name(
			'send',
			'marmoset',
			'as_material',
		))
		layout.operator(create_operator_name(
			'send',
			'marmoset',
			'as_mask',
		))

		# for tag in asset_data.tags:
			# layout.row().label(text=tag.name)



















# =========================================================
# ---------------------------------------------------------
#                      REGISTRATION
# ---------------------------------------------------------
# =========================================================


rclasses = (
	# ----------------------------------
	# Property declarations
	# ----------------------------------

	# Marmoset
	WZRDMarmosetPipingProperties,


	# ----------------------------------
	# Export operators
	# ----------------------------------

	# Shared
	ASSETBROWSER_OT_AssetWizard_Shared_ExplorerHighlight,

	# Marmoset
	ASSETBROWSER_OT_AssetWizard_MarmosetConnect_SendAsMaterial,
	ASSETBROWSER_OT_AssetWizard_MarmosetConnect_SendAsLayerMask,


	# ----------------------------------
	# Main GUI Panel
	# ----------------------------------
	ASSETBROWSER_PT_AssetWizard_ConnectMainPanel,


	# ----------------------------------
	# Export to various software GUI Panels
	# ----------------------------------

	# Shared
	ASSETBROWSER_PT_AssetWizard_SharedOperators,

	# Marmoset
	ASSETBROWSER_PT_AssetWizard_MarmosetConnect,

)

register_, unregister_ = bpy.utils.register_classes_factory(rclasses)

def register():
	register_()

	# Marmoset
	bpy.types.Scene.wzrd_marmoset_piping_params = bpy.props.PointerProperty(
		type=WZRDMarmosetPipingProperties
	)

	if len(bpy.app.handlers.load_post) > 0:
		# Black Magic. This somehow ensures the marmoset connect is not started twice
		if 'marmoset_connect' in bpy.app.handlers.load_post[0].__name__.lower() or marmoset_connect in bpy.app.handlers.load_post:
			return

	bpy.app.handlers.load_post.append(marmoset_connect)


def unregister():
	unregister_()
	if len(bpy.app.handlers.load_post) > 0:
		# Black Magic. This somehow ensures the marmoset connect is not started twice
		if 'marmoset_connect' in bpy.app.handlers.load_post[0].__name__.lower() or marmoset_connect in bpy.app.handlers.load_post:
			bpy.app.handlers.load_post.remove(marmoset_connect)