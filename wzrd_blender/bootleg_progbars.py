import socket
import sys
import os
import struct
import time
import pickle

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





class _BootlegProgBar:
	# BAR_FILL = '='
	BAR_FILL = '█'
	BAR_EMPTY = ' '
	# BAR_CAPS = ('◄⌠[', ']⌡►')
	BAR_CAPS = ('◄●│', '│●►')
	PROG_DIVS = 60

	SPECIAL = '\0'

	CENTER = '\1'

	LINE_RES = 80

	def __init__(self, skt):
		self.skt = skt
		self.skt_rfile = None
		self.bars = None

	def __enter__(self):
		self.skt.connect((
			'127.0.0.1',
			int(sys.argv[-1])
		))
		self.skt_rfile = self.skt.makefile('rb', buffering=0)
		return self

	def __exit__(self, type, value, traceback):
		pass

	def render(self):
		# os.system('cls')
		bar_cap_start, bar_cap_end = self.BAR_CAPS
		lines = [
			self.CENTER + '☼☼☼ Asset Wizard Progress Report ☼☼☼',
			self.SPECIAL + ('═' * (self.LINE_RES + 2)),
		]

		# lines.append(
			
		# )
		for bar_prog, bar_msg in self.bars:
			lines.append(
				# bar_msg[0:self.LINE_RES].ljust(self.LINE_RES, ' ')
				bar_msg[0:self.LINE_RES]
			)
			prog = min(
				int(self.PROG_DIVS*bar_prog),
				self.PROG_DIVS
			)

			lines.append(''.join((
				bar_cap_start,
				(self.BAR_FILL * prog).ljust(self.PROG_DIVS, self.BAR_EMPTY),
				bar_cap_end,
			)))

			lines.append('')

			# lines.append(bar.ljust(self.LINE_RES, ' '))

		"""
		for l in lines:
			sys.stdout.write('\x1b[1A\x1b[2K')
			# sys.stdout.write('\x1b[1A\x1b[2K')
		sys.stdout.flush()

		for l in lines:
			sys.stdout.write(l)
			sys.stdout.write('\n')
			sys.stdout.write('\x1b[1A\x1b[2K')
		"""

		for i, l in enumerate(lines):
			if l.startswith(self.CENTER):
				lines[i] = f"""║ {l.replace(self.CENTER, '').center(self.LINE_RES, ' ')} ║"""
				continue
			if l.startswith('\0'):
				lines[i] = f"""╠{l.replace(self.SPECIAL, '').ljust(self.LINE_RES + 2, ' ')}╣"""
			else:
				lines[i] = f"""║ {l.ljust(self.LINE_RES, ' ')} ║"""


		lines.insert(
			0,
			'╔' + ('═' * (self.LINE_RES + 2)) + '╗',
		)
		lines.append(
			'╚' + ('═' * (self.LINE_RES + 2)) + '╝'
		)
		lines.append('')
		

		sys.stdout.write('\x1b[1A\x1b[2K' * len(lines))
		# sys.stdout.write(('\n' + '\x1b[1A\x1b[2K').join(lines))
		sys.stdout.write('\n'.join(lines))

		# sys.stdout.flush()

	def read_params(self):
		bars_count = int.from_bytes(
			self.skt_rfile.read(2),
			'little'
		)
		self.bars = tuple(
			[0.0, '',] for i in range(bars_count)
		)

	def run(self):
		self.read_params()
		while True:
			cmd = self.skt_rfile.read(3)
			if cmd == b'DIE':
				time.sleep(1)
				sys.exit()

			bar_idx = int.from_bytes(self.skt_rfile.read(2), 'little')
			# print('Tweaking bar idx', bar_idx, self.bars)
			# todo: get rid of [0]
			self.bars[bar_idx][0] = struct.unpack('d', self.skt_rfile.read(8))[0]
			self.bars[bar_idx][1] = self.skt_rfile.read(
				int.from_bytes(self.skt_rfile.read(4), 'little')
			).decode()

			self.render()


class BootlegProgBar:
	BAR_FILL = '█'
	BAR_EMPTY = ' '
	BAR_CAPS = ('◄●│', '│●►')
	PROG_DIVS = 60
	LINE_RES = 80

	FRAME_CHARS = (
		'═','║','╠','╣'
	)

	HEADER = (
		'☼☼☼ Asset Wizard Progress Report ☼☼☼'
	)

	LPAD = 2

	def __init__(self, skt):
		self.skt = skt
		self.skt_rfile = None
		self.bars = None

	def __enter__(self):
		self.skt.connect((
			'127.0.0.1',
			int(sys.argv[-1])
		))
		self.skt_rfile = self.skt.makefile('rb', buffering=0)
		return self

	def __exit__(self, type, value, traceback):
		pass

	def read_params(self):
		bars_count = int.from_bytes(
			self.skt_rfile.read(2),
			'little'
		)
		self.bars = tuple(
			[0.0, '',] for i in range(bars_count)
		)

	def create_line(self, text, sep=False, center=False):
		return (text, sep, center,)

	def render(self):
		bar_cap_start, bar_cap_end = self.BAR_CAPS

		lines = [
			self.create_line(self.HEADER, center=True),
			self.create_line('', True),
		]

		for bar_prog, bar_msg in self.bars:
			lines.append(self.create_line(bar_msg))

			prog = min(
				int(self.PROG_DIVS*bar_prog),
				self.PROG_DIVS
			)

			lines.append(self.create_line(''.join((
				bar_cap_start,
				(self.BAR_FILL * prog).ljust(self.PROG_DIVS, self.BAR_EMPTY),
				bar_cap_end,
			))))

			lines.append(self.create_line(''))

		return lines

	def display(self, lines):
		for i, l in enumerate(lines):
			text, sep, center = l

			if sep:
				lines[i] = ''.join((
					self.FRAME_CHARS[2],
					text.center(self.LINE_RES, self.FRAME_CHARS[0]),
					self.FRAME_CHARS[3],
				))
				continue

			if center:
				lines[i] = ''.join((
					self.FRAME_CHARS[1],
					text.center(self.LINE_RES, ' '),
					self.FRAME_CHARS[1],
				))
				continue

			lines[i] = ''.join((
				self.FRAME_CHARS[1],
				' ' * self.LPAD,
				text.ljust(self.LINE_RES - self.LPAD, ' '),
				self.FRAME_CHARS[1],
			))

		
		lines.insert(
			0,
			'╔' + ('═' * (self.LINE_RES + 0)) + '╗',
		)
		lines.insert(0, '')
		lines.append(
			'╚' + ('═' * (self.LINE_RES + 0)) + '╝',
		)

		sys.stdout.write('\x1b[1A\x1b[2K' * len(lines))
		sys.stdout.write('\n'.join(lines))

	def run(self):
		self.read_params()
		while True:
			cmd = self.skt_rfile.read(3)
			if cmd == b'DIE':
				time.sleep(1)
				sys.exit()

			bar_idx = int.from_bytes(self.skt_rfile.read(2), 'little')
			# print('Tweaking bar idx', bar_idx, self.bars)
			# todo: get rid of [0]
			self.bars[bar_idx][0] = struct.unpack('d', self.skt_rfile.read(8))[0]
			self.bars[bar_idx][1] = self.skt_rfile.read(
				int.from_bytes(self.skt_rfile.read(4), 'little')
			).decode()

			self.display(self.render())


def main():
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as skt:
		with BootlegProgBar(skt) as bootleg_bar:
			bootleg_bar.run()

if __name__ == '__main__':
	try:
		main()
	except Exception as e:
		print(exception_to_str(e))
		while True:
			time.sleep(1)
	


