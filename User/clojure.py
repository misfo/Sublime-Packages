import re, os, socket, string, sublime, sublime_plugin

max_cols = 60

def clean(str):
	return str.translate(None, '\r') if str else None

def symbol_char(char):
	return re.match("[-\w*+!?/.]", char)

def classpath_relative_path(file_name):
	(abs_path, ext) = os.path.splitext(file_name)
	segments = []
	while 1:
		(abs_path, segment) = os.path.split(abs_path)
		if segment == "src": return string.join(segments, "/")
		segments.insert(0, segment)

def find_hash_value(key, clj):
	match = re.search(key + r"[\s\n]+(\d+)", clj)
	return match.group(1) if match else None

def output_to_view(v, ns, form, output):
	v.set_read_only(False)
	edit = v.begin_edit()
	convo = "; " + ns + "=> " + ";" * (max_cols - 5 - len(ns)) + "\n" + \
		    form + "\n" + \
		    ";" * max_cols + "\n" + \
		    output + "\n\n"
	v.insert(edit, v.size(), convo)
	v.end_edit(edit)
	v.set_read_only(True)

def exit_with_status(message):
	sublime.status_message(message)
	sys.exit(1)

def exit_with_error(message):
	sublime.error_message(message)
	sys.exit(1)

class LazyViewString:
	def __init__(self, view):
		self.view = view

	def __str__(self):
		if not hasattr(self, '_string_value'):
			self._string_value = self.get_string()
		return self._string_value

class Selection(LazyViewString):
	def get_string(self):
		print "Selection#get_string"
		sel = self.view.sel()
		if len(sel) == 1:
			return self.view.substr(self.view.sel()[0]).strip()
		else:
			exit_with_status("There must be one selection to evaluate")

class SymbolUnderCursor(LazyViewString):
	def get_string(self):
		print "SymbolUnderCursor#get_string"
		begin = end = self.view.sel()[0].begin()
		while symbol_char(self.view.substr(begin - 1)): begin -= 1
		while symbol_char(self.view.substr(end)): end += 1
		if begin == end:
			exit_with_status("No symbol found under cursor")
		else:
			return self.view.substr(sublime.Region(begin, end))

class LeinReplSocket:
	def __init__(self, port):
		self.sock = socket.socket()
		self.sock.connect(('localhost', port))
		self.sock.settimeout(2)

	def send(self, expr):
		if expr: self.sock.send(expr + "\n")
		output = "" # TODO use buffer instead?
		while 1:
			output += self.sock.recv(1024)
			match = re.match(r"(.*\n)?(\S+)=> $", output, re.DOTALL)
			if match: return (clean(match.group(1)), match.group(2))

	def close(self):
		self.sock.close()


class ClojureEvaluate(sublime_plugin.TextCommand):
	def _repl_port_number(self):
		window = self.view.window()
		folders = window.folders()
		file_name = self.view.file_name()
		try:
			# FIXME doesn't work for non-file buffers
			proj_folder = (f for f in folders if file_name.startswith(f)).next()
		except StopIteration:
			exit_with_error("No folder open containing " + file_name)

		project_clj_file_name = os.path.join(proj_folder, 'project.clj')
		try:
			project_clj = open(project_clj_file_name, 'r').read()
		except IOError:
			exit_with_error("No project.clj found in " + proj_folder)

		repl_port = find_hash_value(":repl-port", project_clj)
		if repl_port:
			return int(repl_port)
		else:
			exit_with_error("No :repl-port specified in " + project_clj_file_name)

	def run(self, edit, form, in_current_ns=None, use_buffer=False, strip_nil_return=False):
		window = self.view.window()
		port = None
		repl_view = None
		repl_ns = None
		for v in window.views():
			match = re.match(r"\(in-ns '(.+)\)", v.name())
			if match:
				repl_ns = match.group(1)
				repl_view = v
				port = repl_view.settings().get('clojure_repl_port')
				print "repl_ns", repl_ns
				print "repl_view", repl_view
				print "port", port
				break

		if not port:
			port = self._repl_port_number()

		try:
			s = LeinReplSocket(port)
		except socket.error:
			exit_with_error("No repl is listening on port " + str(port) + "\nPlease start one with `lein repl`")

		if not repl_view:
			repl_view = window.new_file()
			repl_view.set_scratch(True)
			# TODO: put connection details in comment at top of view
			repl_view.set_syntax_file('Packages/Clojure/Clojure.tmLanguage')
			repl_view.settings().set('scroll_past_end', True)
			repl_view.settings().set('clojure_repl_port', port)
			repl_view.set_read_only(True)

		starting_pt = repl_view.size()

		template = string.Template(form)
		form = template.substitute({
			"selection": Selection(self.view),
			"symbol_under_cursor": SymbolUnderCursor(self.view)})

		_, initial_ns = s.send(None)
		if not repl_ns: repl_ns = initial_ns
		prev_ns = initial_ns

		file_name = self.view.file_name()
		if in_current_ns and file_name:
			path = classpath_relative_path(file_name)
			file_ns = re.sub("/", ".", path)
			load_form = "(load \"/" + path + "\")"
			output, prev_ns = s.send(load_form)
			output_to_view(repl_view, initial_ns, load_form, output)
			form = "(binding [*ns* (find-ns '" + file_ns + ")]\n  " + form + ")"

		main_form_pt = repl_view.size() + max_cols + 1
		output, last_ns = s.send(form)
		# TODO comment out (?) all output before the return value

		s.close()

		repl_view.set_name("(in-ns '" + last_ns + ")")

		output_to_view(repl_view, prev_ns, form, output)

		repl_view.set_viewport_position(repl_view.text_to_layout(starting_pt))
		repl_view.sel().clear()
		repl_view.sel().add(sublime.Region(main_form_pt))
		window.run_command('toggle_bookmark')

		active_view = window.active_view()
		active_group = window.active_group()
		repl_view_group, _ = window.get_view_index(repl_view)
		window.focus_view(repl_view)
		if repl_view_group != active_group:
			# give focus back to the originally active view if it's in a different group
			window.focus_view(active_view)
