import re, os, socket, string, sublime, sublime_plugin

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

def output_to_view(v, output):
	edit = v.begin_edit()
	v.insert(edit, 0, output)
	v.end_edit(edit)

def output_to_scratch_buffer(window, name, output):
	v = window.new_file()
	v.set_name(name)
	v.set_scratch(True)
	v.set_syntax_file('Packages/Clojure/Clojure.tmLanguage')
	output_to_view(v, output)

def output_to_panel(window, output):
	v = window.get_output_panel('clojure_output')
	output_to_view(v, output)
	window.run_command("show_panel", {"panel": "output.clojure_output"})

def exit_with_error(window, message):
	output_to_panel(window, message)
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
			return self.view.substr(self.view.sel()[0])
		else:
			exit_with_error(self.view.window(), "There must be one selection to evaluate")

class SymbolUnderCursor(LazyViewString):
	def get_string(self):
		print "SymbolUnderCursor#get_string"
		begin = end = self.view.sel()[0].begin()
		while symbol_char(self.view.substr(begin - 1)): begin -= 1
		while symbol_char(self.view.substr(end)): end += 1
		if begin == end:
			exit_with_error(self.view.window(), "No symbol found under cursor")
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
			match = re.match(r"(.*\n)?(\S+=> )$", output, re.DOTALL)
			if match: return (clean(match.group(1)), match.group(2))

	def close(self):
		self.sock.close()


class ClojureEvaluate(sublime_plugin.TextCommand):
	def _repl_port_number(self):
		window = self.view.window()
		folders = window.folders()
		file_name = self.view.file_name()
		try:
			proj_folder = (f for f in folders if file_name.startswith(f)).next()
		except StopIteration:
			exit_with_error(window, "No folder open containing " + file_name)

		project_clj_file_name = os.path.join(proj_folder, 'project.clj')
		try:
			project_clj = open(project_clj_file_name, 'r').read()
		except IOError:
			exit_with_error(window, "No project.clj found in " + proj_folder)

		repl_port = find_hash_value(":repl-port", project_clj)
		if repl_port:
			return int(repl_port)
		else:
			exit_with_error(window, "No :repl-port specified in " + project_clj_file_name)

	def run(self, edit, form, in_current_ns=None, use_buffer=False, strip_nil_return=False):
		window = self.view.window()
		try:
			port = self._repl_port_number()
			s = LeinReplSocket(port)
		except socket.error:
			exit_with_error(window, "No repl is listenting on port " + str(port) + "\nPlease start one with `lein repl`")

		template = string.Template(form)
		expr = template.substitute({
			"selection": Selection(self.view),
			"symbol_under_cursor": SymbolUnderCursor(self.view)})

		(output, prompt) = s.send(None)
		print "prompt before everything", prompt

		file_name = self.view.file_name()
		forms = []
		if in_current_ns and file_name:
			path = classpath_relative_path(file_name)
			forms.append("(load \"/" + path + "\")")

			forms.append("(in-ns '" + re.sub("/", ".", path) + ")")

		forms.append(expr)
		do_form = "(do " + string.join(forms, "\n  ") + ")"
		(output, _) = s.send(do_form)

		s.close()

		if not output:
			exit_with_error(window, "There was an error while executing " + do_form)

		if strip_nil_return:
			output = re.sub(r"\nnil$", "", output)

		if use_buffer:
			output_to_scratch_buffer(window, expr, output)
		else:
			output_to_panel(window, prompt + do_form + "\n" + output)
