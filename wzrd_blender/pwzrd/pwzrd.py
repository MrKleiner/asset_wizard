from pathlib import Path
from os import path
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


try:
	import bpy
except ImportError as e:
	bpy = None

THISDIR = None
if Path(__file__).parent.is_dir():
	THISDIR = Path(__file__).parent
elif bpy:
	THISDIR = Path(
		bpy.path.abspath(bpy.data.texts[Path(__file__).name].filepath)
	).parent

	if not THISDIR.is_dir():
		THISDIR = None


def exception_to_str(err):
	import traceback
	try:
		return ''.join(
			traceback.format_exception(
				type(err),
				err,
				err.__traceback__
			)
		)
	except Exception as e:
		return str(e)


# Command index
CMD_INDEX_OUT = {
	'get_params': 0,
	'render_out': 1,
	'end': 2,
	'peek': 3,
	'item_render_done': 4,
	'do_render': 5,
	'render_output': 6,
	'end_session': 7,
}
CMD_INDEX_IN = {}
for cmd_name, cmd_idx in CMD_INDEX_OUT.items():
	CMD_INDEX_IN[cmd_idx] = cmd_name
	CMD_INDEX_OUT[cmd_name] = cmd_idx.to_bytes(2, 'little')


# Identifier strings
MAGIC_ID = b'SEX'


class EndSession(Exception):
	pass


class BlenderRender:
	"""
		Input params:
		    - material_source: Blender file from which to take
		      the material.

		    - src_material_name: The name of the material to be taken.

		    - disp_scale: set "Scale" param of the displacement node
		      to this value, if applicable. Default to 0.9

		    - disp_midlevel: 'Midlevel' param of the displacement node.
		      Default to 0.5

		    - size_factor: Scale the output image dimensions by this value.
		      The base is 256.

		    - time_limit_factor: Multiply the render time limit by this value.
		      Base is 5 seconds.

		    - render_output_path: Output the rendered image to this path.
		      Must be absolute. Default to '//render_out.png'.
		      If 'render_as' is set to 'bytes', then the image gets rendered
		      to the default output path and deleted once its bytes are sent
		      over the socket.

		    - render_as:
		        - save_to_path: Render to the specified path.
		          Returns the very or False
		        - bytes: Return rendered image as bytes.

		    - disp_method:
		        Default to 'DISPLACEMENT'.
		        - 'BUMP': Normal map only. Geometry not affected.
		        - 'DISPLACEMENT': Geometry displaced ONLY by BW height map.
		        - 'BOTH': Geometry is displaced by BOTH BW height and normal map.

		    - film_exposure:
		        Exposure (float)

		    - shape:
		        The shape of the geometry the material will be applied to.
		        Valid entries are:
		        - sphere
		        - plane

		Minimum outgoing request length is:
		MAGIC_ID(3) + CMD(2) + PAYLOAD_LENGTH(4) = 9
	"""

	# The object used to apply the target material to
	PREVIEW_OBJ_NAME = 'main_preview_obj'
	# Target scene name
	TGT_SCENE_NAME = 'main'

	RENDER_OUT_DEFAULT = '//render_out.png'

	def __init__(self, params):
		self.params = params
		self.tgt_obj = bpy.data.objects[self.PREVIEW_OBJ_NAME]
		self.scene = bpy.data.scenes[self.TGT_SCENE_NAME]

		self._material = None

	def cleanup(self):
		for mat in bpy.data.materials:
			bpy.data.materials.remove(mat)
		for img in bpy.data.images:
			if not img.name in ('panorama_main', 'Render Result'):
				bpy.data.images.remove(img)

		self.scene.render.filepath = self.RENDER_OUT_DEFAULT

	def __enter__(self):
		self.cleanup()
		return self

	def __exit__(self, type, value, traceback):
		self.cleanup()

	@property
	def material(self):
		if self._material:
			return self._material

		with bpy.data.libraries.load(self.params['material_source']) as (data_from, data_to):
			data_to.materials.append(self.params['src_material_name'])

		self._material = bpy.data.materials[self.params['src_material_name']]
		self._material.displacement_method = self.params.get(
			'disp_method',
			'DISPLACEMENT'
		)

		return self._material

	def set_render_params(self):
		resolution = int(
			256 * self.params.get('size_factor', 1)
		)
		self.scene.render.resolution_x = resolution
		self.scene.render.resolution_y = resolution

		self.scene.cycles.time_limit = 5 * self.params.get('time_limit_factor', 1)
		self.scene.cycles.film_exposure = self.params.get('film_exposure', 1.0)

	def set_disp_params(self):
		disp_scale = self.params.get('disp_scale', 0.9)
		mid_level = self.params.get('disp_midlevel', 0.5)

		mat_out = None
		for node in self.material.node_tree.nodes:
			if node.type == 'OUTPUT_MATERIAL':
				mat_out = node
				break

		if not mat_out:
			raise LookupError(
				f'Material {self.material} has no material output'
			)

		disp_node = None
		for n_input in mat_out.inputs:
			for link in n_input.links:
				linked_node = link.from_node
				if linked_node.type == 'DISPLACEMENT':
					print('PWZRD: Found disp node')
					disp_node = linked_node
					break

		if disp_node:
			disp_node.inputs['Scale'].default_value = disp_scale
			disp_node.inputs['Midlevel'].default_value = mid_level

	def render(self):
		self.set_disp_params()
		self.set_render_params()

		# Apply material to the object
		self.tgt_obj.data.materials[0] = self.material

		# Set image output path
		render_out_path = bpy.path.abspath(str(self.params.get(
			'render_output_path',
			self.RENDER_OUT_DEFAULT
		)))
		self.scene.render.filepath = render_out_path

		# Do render
		bpy.ops.render.render(write_still=1)

		if self.params.get('render_as') == 'bytes':
			render_out_payload = Path(render_out_path).read_bytes()
		else:
			render_out_payload = str(render_out_path).encode()

		return render_out_payload


class CMDGateway:
	def __init__(self, skt):
		self.skt = skt
		self.skt_rfile = skt.makefile('rb', buffering=0)
		self.skt_wfile = skt.makefile('wb')

	def send(self, tgt_cmd, payload=None):
		payload = payload or b''
		if type(payload) != bytes:
			print('PWZRD: None-byte payload:', payload)
			payload = str(payload).encode()

		# Magic ID
		self.skt_wfile.write(
			MAGIC_ID
		)
		# Command
		self.skt_wfile.write(
			CMD_INDEX_OUT[tgt_cmd]
		)
		# Out payload length
		self.skt_wfile.write(
			len(payload or b'').to_bytes(4, 'little')
		)
		# Out payload bytes
		self.skt_wfile.write(
			payload or b''
		)

		self.skt_wfile.flush()

	def read(self):
		assert self.skt_rfile.read(3) == MAGIC_ID

		tgt_cmd = int.from_bytes(
			self.skt_rfile.read(2),
			'little'
		)
		print('PWZRD Blender Renderer got cmd ID:', tgt_cmd)

		payload_len = int.from_bytes(
			self.skt_rfile.read(4),
			'little'
		)
		print('PWZRD Blender Renderer got payload len:', payload_len)

		payload_bytes = self.skt_rfile.read(payload_len)

		return tgt_cmd, payload_bytes

	def close(self):
		self.skt_rfile.close()
		self.skt_wfile.close()


class BlenderConnect:
	def __init__(self, skt):
		self.cmd_gateway = CMDGateway(skt)

		self.cmd_index = {
			5: self.do_render,
			7: self.end_session,
		}

	def do_render(self, payload_data):
		with BlenderRender(json.loads(payload_data)) as renderer:
			try:
				result = renderer.render()
			except LookupError as e:
				result = f'$fail:{e}'

		self.cmd_gateway.send(
			'render_output',
			result
		)

	def end_session(self, payload_data):
		self.cmd_gateway.close()
		raise EndSession('Session was requested to end')

	def run(self):
		while True:
			try:
				cmd_id, cmd_data = self.cmd_gateway.read()
				self.cmd_index[cmd_id](cmd_data)
			except EndSession as es:
				break
			except Exception as e:
				print(exception_to_str(e))
				continue


class PreviewWizard:
	PREVIEW_SHAPES = {
		'sphere': 'blend_files/pwzrd_spherical.blend',
		'plane': 'blend_files/pwzrd_planar.blend',
	}

	SETUP_SCRIPT = 'pwzrd_blender_setup.py'

	def __init__(self, blender_executable, preview_shape='sphere'):
		self.cmd_gateway = None
		self.skt = None
		self.blender_executable = blender_executable

		self.renderer_blend = THISDIR / self.PREVIEW_SHAPES[preview_shape]

	def __enter__(self):
		self.skt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.skt.bind(
			('127.0.0.1', 0)
		)
		self.skt.listen()

		setup_script = '; '.join((THISDIR / self.SETUP_SCRIPT).read_text().replace(
			'TARGET_PORT',
			str(self.skt.getsockname()[1])
		).strip().split('\n'))

		subprocess.Popen([
			self.blender_executable,
			'-b',
			self.renderer_blend,
			'--python-expr',
			setup_script,
			'--python',
			str(THISDIR / Path(__file__).name),
		])

		self.cl_con, self.cl_addr = self.skt.accept()
		self.cmd_gateway = CMDGateway(self.cl_con)
		print('PWZRD main: accepted connection from Blender')

		return self

	def __exit__(self, type, value, traceback):
		self.cmd_gateway.send('end_session')
		self.cl_con.shutdown(socket.SHUT_RDWR)
		self.cl_con.close()
		pass

	def render(self, render_params):
		self.cmd_gateway.send(
			'do_render',
			json.dumps(render_params).encode()
		)

		return self.cmd_gateway.read()[1]


def main():
	# While True is because this script gets executed BEFORE the other side
	# this script is trying to connect to starts listening.
	# The connection is only established once.
	# One render session (can render multiple materials) per connection
	# and per this script execution.
	while True:
		try:
			with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as skt:
				tgt_port = int(
					bpy.data.scenes[BlenderRender.TGT_SCENE_NAME]
					.get('__pwzrd_connect_port')
				)
				print('WPZRD: Connecting to port >', tgt_port, '<')
				skt.connect((
					'127.0.0.1',
					tgt_port
				))

				blender_render = BlenderConnect(skt)
				blender_render.run()
		except ConnectionAbortedError as e:
			print('Connection aborted')
		except ConnectionResetError as e:
			print('Connection aborted')
		except TimeoutError as e:
			print('Connection timed out, unfortunately')
		except BrokenPipeError as e:
			print('Connection aborted')
		except Exception as e:
			print('PWZRD Errored:', exception_to_str(e))
			continue
		finally:
			break



if __name__ == '__main__':
	print('PWZRD: Executing...')
	main()

